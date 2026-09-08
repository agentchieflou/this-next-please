"""What the Jira client does when the server misbehaves: retries, budgets, fallbacks and the ordering guarantee.

`tests/test_jira_api.py` proves the client speaks Jira -- headers, flavors, credentials, the shape of a row. It
says nothing about the run that matters, the one that fetches four hundred pages against a shared token and meets
a 502 on page forty. Epic #121 exists because that run used to end with an exception and nothing on disk, and
because a bulkfetch that hit one bad key quietly turned three requests into three thousand.

So every test here is a failure the epic names, driven through `tests/fakes/jira.py`'s fault script rather than
through a mock: a 500 that clears on retry and one that does not, a socket timeout, a `Retry-After` longer than
any run should sit idle for, rate-limit headers that ask the client to slow down *before* it is refused, a
transition that must never be replayed, a budget that stops a runaway pull, and the bulkfetch discipline of #126.

The ordering guarantee gets its own section because it is load-bearing: the streaming slice writes rows to disk as
they arrive and can never re-read them, so "keys in the order given, ascending within a key, one key finished
before the next starts" has to hold at fetch time, out of shuffled and duplicated pages, on both flavors.
"""
from __future__ import annotations

import io
import json
import random
import urllib.request

import pytest

from agentdata.connectors import jira_api as J
from agentdata.connectors import jira_http as H

from fakes import jira as FJ

CHANGELOG = "/rest/api/3/issue/{}/changelog"


def _order_of(rows: list[dict]) -> list[tuple]:
    return [(r["created_utc"], r["changelog_id"]) for r in rows]


def _keys_in_order(rows: list[dict]) -> list[str]:
    """The distinct keys in the order they appear, so a key that comes back twice is visible as a repeat."""
    out: list[str] = []
    for r in rows:
        if not out or out[-1] != r["key"]:
            out.append(r["key"])
    return out


# ------------------------------------------------------------------------------- #123 the request layer


def test_a_500_that_clears_on_retry_does_not_lose_the_pages_already_fetched():
    """Jira answers 500 for a transient backend hiccup on changelog pages; today that ends the run."""
    fake = FJ.FakeJira(1, 250, faults=[("issue/", 3, 500)])
    j = fake.client()
    rows = j.changelog("RDSD-1")
    assert len(rows) == 250, "every page, including the one that first answered 500"
    assert fake.count("/changelog") == 4, "three pages plus the one retry"
    assert j.stats.retries == 1 and j.stats.requests == 4


def test_a_second_500_on_the_same_page_is_real_and_names_the_page():
    """One more try is worth it; six are not, and the operator needs to know where it died."""
    fake = FJ.FakeJira(1, 250, faults=[("issue/", (3, 4), 500)])
    with pytest.raises(J.JiraHTTPError) as ei:
        fake.client().changelog("RDSD-1")
    assert ei.value.status == 500
    assert "startAt=200" in str(ei.value), "the page marker is the whole point of the message"
    assert fake.count("/changelog") == 4


@pytest.mark.parametrize("fault", [502, 503, 504, "timeout", "reset"])
def test_the_transient_failures_that_used_to_end_a_run_are_retried_with_jittered_backoff(fault):
    fake = FJ.FakeJira(1, 1, faults=[("myself", 1, fault)])
    j = fake.client()
    assert j.myself()["displayName"] == "Luna Fake"
    assert fake.count("myself") == 2 and j.stats.retries == 1
    assert len(fake.slept) == 1
    base, cap = J.BACKOFF_BASE, 120.0
    assert base <= fake.slept[0] < base + base, f"attempt 0 must land in [{base}, {2 * base}); got {fake.slept[0]}"
    assert fake.slept[0] <= cap


def test_two_runs_with_different_randomness_do_not_retry_in_the_same_second():
    """Several tiles share one token and start from the same schedule; identical backoff reproduces the burst."""
    waits = []
    for seed in (1, 2):
        fake = FJ.FakeJira(1, 1, faults=[("myself", "every", 503)])
        j = fake.client(rand=random.Random(seed).random, max_attempts=4)
        with pytest.raises(J.JiraHTTPError):
            j.myself()
        waits.append(fake.slept)
    assert waits[0] != waits[1], f"lockstep backoff: {waits[0]}"
    for run in waits:
        assert [round(w) for w in run] == [1, 2, 4] or all(2 ** i <= w < 2 ** i + 1 for i, w in enumerate(run))


def test_a_retry_after_longer_than_the_cap_waits_the_cap_and_says_so():
    """`Retry-After: 201` on a 900-second budget would spend a quarter of the run asleep."""
    lines: list[str] = []
    fake = FJ.FakeJira(1, 1, rate_headers=False, bucket=FJ.TokenBucket(capacity=1, refill=0.005))
    j = fake.client(retry_after_cap=120.0, log=lines.append)
    assert j.myself()["displayName"] == "Luna Fake", "the one token"
    assert j.myself()["displayName"] == "Luna Fake", "429, Retry-After 201, capped, then retried"
    assert fake.slept[0] == 120.0, f"the cap, not the header: {fake.slept}"
    assert j.stats.waited_seconds >= 120.0
    assert any("retrying in" in line for line in lines), "the wait is logged, not silent"


def test_the_client_pauses_on_the_rate_limit_headers_before_it_is_ever_refused():
    """Learning about a quota from a 429 means the request was already counted against the human's token."""
    lines: list[str] = []
    fake = FJ.FakeJira(1, 400, reset_style="delta", bucket=FJ.TokenBucket(capacity=3, refill=0.5))
    j = fake.client(log=lines.append)
    rows = j.changelog("RDSD-1")
    assert len(rows) == 400 and fake.count("/changelog") == 4, "four pages, no retries: no 429 was ever served"
    assert j.stats.retries == 0
    assert j.stats.rate_limit_waits == 2 and j.stats.waited_seconds > 0
    assert any(line.startswith("rate limit:") and "left, waiting" in line for line in lines), lines


def test_without_the_headers_a_data_center_run_stays_reactive():
    fake = FJ.FakeJira(1, 400, flavor="dc")
    j = fake.client()
    assert len(j.changelog("RDSD-1")) == 400
    assert j.rate.limit is None and j.stats.rate_limit_waits == 0 and not fake.slept


def test_a_transition_is_never_replayed_but_a_read_of_the_same_issue_is():
    """A transition that times out may well have been applied; a second POST moves the issue twice."""
    fake = FJ.FakeJira(1, 1, faults=[("POST /rest/api/3/issue/RDSD-1/transitions", "every", 502)])
    j = fake.client()
    with pytest.raises(J.JiraHTTPError) as ei:
        j.transition("RDSD-1", "31")
    assert ei.value.status == 502
    assert fake.count("POST /rest/api/3/issue/RDSD-1/transitions") == 1, "exactly one POST"
    assert j.stats.retries == 0

    idempotent = FJ.FakeJira(1, 1, faults=[("GET /rest/api/3/issue/RDSD-1/transitions", 1, 502)])
    assert idempotent.client().transitions("RDSD-1")[0]["id"] == "31"
    assert idempotent.count("transitions") == 2, "the GET is idempotent and is retried"


def test_the_request_budget_stops_a_runaway_pull_and_says_where():
    fake = FJ.FakeJira(1, 400)
    j = fake.client(budget=H.RequestBudget(max_requests=3))
    with pytest.raises(J.JiraBudgetError) as ei:
        j.changelog("RDSD-1")
    assert ei.value.limit == "requests" and ei.value.requests_made == 3
    assert "startAt=300" in ei.value.last_path
    assert "--max-requests" in ei.value.hint
    assert fake.count("/changelog") == 3, "it stops before spending the fourth request"


def test_the_seconds_budget_stops_a_slow_run():
    ticks = iter([5.0 * n for n in range(1, 200)])
    fake = FJ.FakeJira(1, 400)
    j = fake.client(budget=H.RequestBudget(max_seconds=10.0), clock=lambda: next(ticks))
    with pytest.raises(J.JiraBudgetError) as ei:
        j.changelog("RDSD-1")
    assert ei.value.limit == "seconds" and "--max-seconds" in ei.value.hint


def test_stats_carry_the_five_numbers_the_meta_prints():
    fake = FJ.FakeJira(2, 150, faults=[("issue/", 2, 503)])
    j = fake.client()
    j.changelog("RDSD-1")
    d = j.stats.as_dict()
    assert set(d) == {"requests", "retries", "rate_limit_waits", "waited_seconds", "elapsed_seconds"}
    assert d["requests"] == 3 and d["retries"] == 1 and d["waited_seconds"] > 0
    assert "1 retry" in j.stats.line()


# ------------------------------------------------------------------------------- #124 one fetch path


def test_the_wrappers_are_the_iterator():
    """`changelog()` and `bulk_changelog()` keep their signatures; they are `list()` over the same generator."""
    fake = FJ.FakeJira(3, 5)
    j = fake.client()
    assert j.changelog("RDSD-2") == list(j.iter_changelog(["RDSD-2"], use_bulk=False))
    keys = fake.corpus.keys()
    assert j.bulk_changelog(keys) == list(j.iter_changelog(keys))


def test_rows_arrive_before_the_run_finishes():
    """The property the streaming slice needs: a row reaches the caller without the whole pull being resident."""
    fake = FJ.FakeJira(6, 4)
    j = fake.client()
    it = j.iter_changelog(fake.corpus.keys(), bulk_issues=1)
    first = next(it)
    assert first["key"] == "RDSD-1"
    assert fake.count("bulkfetch") == 1, "only the first chunk has been fetched"
    assert len(list(it)) == 23


def test_the_data_center_truncation_keeps_its_refusal_and_gains_a_shape():
    """A hundred entries that look like a whole history produce a `committed_points` that looks right."""
    events: list[tuple] = []
    fake = FJ.FakeJira(1, 412, flavor="dc", paged_changelog=False, expand_cap=100)
    j = fake.client()
    with pytest.raises(J.JiraPartialError) as ei:
        list(j.iter_changelog(["RDSD-1"], use_bulk=False, on_event=lambda k, p: events.append((k, p))))
    err = ei.value
    assert "truncated for RDSD-1: 100 of 412" in str(err), "the refusal itself is unchanged"
    assert err.reason == "expand=changelog truncated: 100 of 412", "the spelling the CLI renders as partial"
    assert (err.key, err.have, err.total) == ("RDSD-1", 100, 412)
    assert err.hint and isinstance(err, J.JiraError)
    assert ("truncated", {"key": "RDSD-1", "have": 100, "total": 412, "reason": err.reason}) in events


def test_a_truncated_history_skips_that_issue_and_the_refusal_comes_last():
    """The refusal is a fact about ONE issue, and it used to end the pull at the first one it met.

    Nothing between `_expand_rows` and the caller caught it, so issue 2 of 5 stopped issues 3, 4 and 5 from ever
    being requested -- and since the CLI's cache is written per finished issue, no rerun could make progress
    either. The four whole histories come out, the short one contributes not a single row (half a history stored
    under the issue's `updated` stamp would be served as the whole history forever), and the same refusal is
    raised once everything fetchable has been yielded.
    """
    fake = FJ.FakeJira(5, 200, flavor="dc", expand_cap=100, faults=[("RDSD-2/changelog", "every", 404)])
    j = fake.client()
    rows: list[dict] = []
    with pytest.raises(J.JiraPartialError) as ei:
        for row in j.iter_changelog(fake.corpus.keys(), use_bulk=False):
            rows.append(row)
    assert ei.value.reason == "expand=changelog truncated: 100 of 200"
    assert _keys_in_order(rows) == ["RDSD-1", "RDSD-3", "RDSD-4", "RDSD-5"]
    assert len(rows) == 800 and not [r for r in rows if r["key"] == "RDSD-2"]
    assert j.bulk_meta["truncated_keys"] == ["RDSD-2"]


def test_a_search_wider_than_its_ceiling_refuses_instead_of_returning_the_prefix():
    """`ad-jira changelog --jql` builds its whole key list from `search()`.

    The ceiling used to `break` and hand back exactly `max_results` issues with nothing saying so, which is the
    silently short result for the one workload the epic names: "a JQL that returns thousands of issues" came
    back as the first five thousand, `ok: true`, `truncated: false`.
    """
    fake = FJ.FakeJira(12, 1)
    with pytest.raises(J.JiraPartialError) as ei:
        fake.client().search("project = RDSD", ["key"], max_results=5)
    assert ei.value.reason == "search truncated at 5 issues"
    assert ei.value.hint, "and it says what to do: narrow the JQL"

    exact = fake.client().search("project = RDSD", ["key"], max_results=12)
    assert len(exact) == 12, "a JQL that returns exactly max_results issues is a complete answer"


def test_a_data_center_search_wider_than_its_ceiling_refuses_the_same_way():
    fake = FJ.FakeJira(12, 1, flavor="dc")
    with pytest.raises(J.JiraPartialError):
        fake.client().search("project = RDSD", ["key"], max_results=5)


def test_on_event_reports_the_progress_the_cli_prints():
    events: list[tuple] = []
    fake = FJ.FakeJira(4, 6)
    rows = list(fake.client().iter_changelog(fake.corpus.keys(), bulk_issues=2,
                                             on_event=lambda k, p: events.append((k, p))))
    kinds = [k for k, _ in events]
    assert kinds.count("issue_done") == 4 and "page" in kinds
    assert sum(p["rows"] for k, p in events if k == "issue_done") == len(rows) == 24
    assert [p["key"] for k, p in events if k == "issue_done"] == fake.corpus.keys()


# ------------------------------------------------------------------------------- the ordering guarantee


def test_shuffled_and_duplicated_bulkfetch_pages_still_come_out_grouped_and_ascending():
    """Bulkfetch states no order within an issue across pages, and repeats a history (JRACLOUD-94906)."""
    fake = FJ.FakeJira(3, 12, bulk_duplicate=True, faults=[("bulkfetch", (2, 3), "shuffle pages")])
    rows = list(fake.client().iter_changelog(fake.corpus.keys(), bulk_page=10))
    assert len(rows) == 36, "de-duplicated, and nothing lost to the shuffle"
    assert _keys_in_order(rows) == fake.corpus.keys(), "one key is finished before the next begins"
    for i in range(3):
        mine = [r for r in rows if r["key"] == fake.corpus.key(i)]
        assert _order_of(mine) == sorted(_order_of(mine))
        assert mine == list(FJ.rows_of(fake, i))


def test_the_keys_come_out_in_the_order_they_were_given_across_chunks():
    fake = FJ.FakeJira(7, 3)
    asked = list(reversed(fake.corpus.keys()))
    rows = list(fake.client().iter_changelog(asked, bulk_issues=2))
    assert _keys_in_order(rows) == asked


def test_data_center_newest_first_comes_out_ascending():
    fake = FJ.FakeJira(1, 40, flavor="dc", paged_changelog=False, expand_cap=100)
    rows = fake.client().changelog("RDSD-1")
    assert len(rows) == 40 and _order_of(rows) == sorted(_order_of(rows))
    assert [r["changelog_id"] for r in rows] == [h["changelog_id"] for h in FJ.rows_of(fake, 0)]


# ------------------------------------------------------------------------------- #126 bulkfetch discipline


def test_a_400_naming_one_bad_key_skips_that_key_and_keeps_the_single_bulk_call():
    """The 400 that used to turn three requests into three thousand."""
    lines: list[str] = []
    events: list[tuple] = []
    fake = FJ.FakeJira(4, 3, faults=[("bulkfetch", 1, "400 invalid key RDSD-3")])
    j = fake.client(log=lines.append)
    rows = list(j.iter_changelog(fake.corpus.keys(), on_event=lambda k, p: events.append((k, p))))
    assert j.bulk_meta["skipped_keys"] == ["RDSD-3"]
    assert ("skipped", {"keys": ["RDSD-3"]}) in events
    assert _keys_in_order(rows) == ["RDSD-1", "RDSD-2", "RDSD-4"] and len(rows) == 9
    assert fake.count("bulkfetch") == 2, "the rejected call and one retry without the bad key"
    assert fake.count("/issue/") == 0, "no per-issue fallback"
    assert j.bulk_meta["fallback"] is False
    assert any("RDSD-3" in line for line in lines)


def test_a_400_that_survives_dropping_the_named_keys_falls_back_for_that_chunk_only():
    fake = FJ.FakeJira(6, 2, faults=[("bulkfetch", "every", 400)])
    j = fake.client()
    rows = list(j.iter_changelog(fake.corpus.keys(), bulk_issues=3))
    assert len(rows) == 12 and _keys_in_order(rows) == fake.corpus.keys()
    assert fake.count("bulkfetch") == 2, "one rejected call per chunk, no key named, so no retry"
    assert fake.count("/issue/") == 6 and j.bulk_meta["fallback"] is True


def test_a_404_falls_back_once_for_the_run_and_announces_what_it_costs():
    lines: list[str] = []
    events: list[tuple] = []
    fake = FJ.FakeJira(6, 2, faults=[("bulkfetch", "every", 404)])
    j = fake.client(log=lines.append)
    rows = list(j.iter_changelog(fake.corpus.keys(), bulk_issues=3,
                                 on_event=lambda k, p: events.append((k, p))))
    assert len(rows) == 12
    assert fake.count("bulkfetch") == 1, "one probe for the whole run, not one per chunk"
    assert fake.count("/issue/") == 6
    assert j.bulk_meta["fallback"] is True and "404" in j.bulk_meta["fallback_reason"]
    assert ("fallback", {"reason": j.bulk_meta["fallback_reason"], "requests": 6}) in events
    assert any("6" in line and "per issue" in line for line in lines), lines


def test_a_fallback_the_budget_cannot_pay_for_stops_before_the_first_per_issue_call():
    """Finding out 2,000 requests in that the run cannot finish is worse than being told before it starts."""
    fake = FJ.FakeJira(20, 2, faults=[("bulkfetch", "every", 404)])
    j = fake.client(budget=H.RequestBudget(max_requests=5))
    with pytest.raises(J.JiraBudgetError) as ei:
        list(j.iter_changelog(fake.corpus.keys()))
    assert fake.count("/issue/") == 0, "not one wasted request"
    assert "--no-bulk" in ei.value.hint and "--max-requests" in ei.value.hint
    assert "20 more requests" in ei.value.hint


def test_a_timeout_on_a_heavy_page_halves_the_page_for_the_rest_of_the_run():
    """The default 60-second timeout is per request, and the biggest allowed page is what hits it."""
    lines: list[str] = []
    events: list[tuple] = []
    fake = FJ.FakeJira(4, 400, faults=[("bulkfetch", 1, "timeout")])
    j = fake.client(log=lines.append)
    rows = list(j.iter_changelog(fake.corpus.keys(), bulk_page=500,
                                 on_event=lambda k, p: events.append((k, p))))
    sizes = [r.body["maxResults"] for r in fake.matching("bulkfetch")]
    assert sizes[0] == 500 and sizes[1] == 500, "the request layer retries the same page first"
    assert sizes[2] == 250, "and the next page is asked for at half the size"
    assert set(sizes[2:]) == {250}
    assert j.bulk_meta["bulk_page_final"] == 250
    assert ("shrink", {"bulk_page": 250}) in events
    assert len(rows) == 1600 and _keys_in_order(rows) == fake.corpus.keys()
    assert any("halving" in line for line in lines)


def test_the_shrink_stops_at_the_floor():
    fake = FJ.FakeJira(2, 400, faults=[("bulkfetch", "every", "timeout")])
    j = fake.client(max_attempts=2)
    with pytest.raises(J.JiraError):
        list(j.iter_changelog(fake.corpus.keys(), bulk_page=60))
    assert j.bulk_meta["bulk_page_final"] == J.MIN_BULK_PAGE == 50


def test_more_than_ten_field_ids_is_a_second_call_not_a_silent_truncation():
    fields = [f"customfield_{100 + n}" for n in range(12)]
    fake = FJ.FakeJira(2, 4)
    j = fake.client()
    rows = list(j.iter_changelog(fake.corpus.keys(), field_ids=fields))
    sent = [r.body["fieldIds"] for r in fake.matching("bulkfetch")]
    assert sent == [fields[:10], fields[10:]], "ten per call, and the eleventh and twelfth are not dropped"
    assert len(rows) == 8, "the same histories twice must not become twice the rows"


def test_the_fields_of_the_second_batch_survive_the_de_duplication():
    """The fake ignores `fieldIds`; a server that honours them is what proves the merge, so this one does."""
    fields = [f"customfield_{100 + n}" for n in range(12)]
    op = _FieldFilteringBulkfetch(fields)
    j = J.Jira(J.Creds("https://acme.atlassian.net", "me@acme.com", "tok", "test"), J.CLOUD, opener=op)
    rows = j.bulk_changelog(["RDSD-1"], fields, id_to_key={"100": "RDSD-1"})
    assert len(op.bodies) == 2
    assert [r["field_id"] for r in rows] == fields, "all twelve, in one issue's rows, de-duplicated once"
    assert {r["key"] for r in rows} == {"RDSD-1"}


def test_a_caller_supplied_id_map_removes_the_resolution_searches():
    fake = FJ.FakeJira(300, 1)
    j = fake.client()
    id_map = {fake.corpus.issue_id(i): fake.corpus.key(i) for i in range(300)}
    assert len(list(j.iter_changelog(fake.corpus.keys(), id_to_key=id_map))) == 300
    assert fake.count("/search") == 0, "sprint-replay and the cache already ran that search"


def test_id_resolution_batches_at_two_hundred_keys():
    fake = FJ.FakeJira(300, 1)
    j = fake.client()
    assert len(list(j.iter_changelog(fake.corpus.keys()))) == 300
    jqls = [r.params["jql"] for r in fake.matching("/search")]
    assert len(set(jqls)) == 2, f"300 keys is two batches of 200, not three of 100: {len(set(jqls))}"
    assert sorted(q.count(",") for q in set(jqls)) == [99, 199]


class _FieldFilteringBulkfetch:
    """A bulkfetch that returns only the `fieldIds` it was asked for, which is what the real one does."""

    def __init__(self, fields: list[str]):
        self.fields, self.bodies = fields, []

    def __call__(self, req, timeout=None, context=None):
        body = json.loads(req.data.decode())
        self.bodies.append(body)
        wanted = set(body.get("fieldIds") or self.fields)
        items = [{"field": f, "fieldId": f, "fieldtype": "custom", "from": None, "fromString": None,
                  "to": None, "toString": "x"} for f in self.fields if f in wanted]
        return _Resp({"issueChangeLogs": [{"issueId": "100", "changeHistories": [
            {"id": "7", "created": "2026-01-01T00:00:00.000+0000", "items": items}]}]})


class _Resp(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_nothing_here_ever_holds_a_real_token():
    """The fake's token is a dummy, and the guard is that no message this module produces can carry one."""
    fake = FJ.FakeJira(1, 1, faults=[("myself", "every", 401)])
    with pytest.raises(J.JiraHTTPError) as ei:
        fake.client().myself()
    assert FJ.FAKE_TOKEN not in str(ei.value) and FJ.FAKE_TOKEN not in ei.value.hint
    assert "ad-setup" in ei.value.hint
    assert all(r.headers.get("Authorization") == "REDACTED" for r in fake.requests)


def test_the_client_is_still_a_urllib_client():
    """`urllib.request.urlopen` stays the default opener; the fake plugs into a seam, not a rewrite."""
    j = J.Jira(J.Creds("https://acme.atlassian.net", "me@acme.com", "tok", "test"), J.CLOUD)
    assert j._open is urllib.request.urlopen
    assert isinstance(j.budget, H.RequestBudget) and isinstance(j.stats, H.Stats)
    assert j.log is None, "silent unless the CLI hands it a stderr writer"
