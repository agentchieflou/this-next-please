"""The fake Jira's own calibration.

`tests/fakes/jira.py` is the instrument every other slice of epic #121 measures itself with: the request layer's
retry classes, the streaming slice's partial marking, the cache's second-run request count and bulkfetch's
ordering guarantee are all judged by what this fake reports. An instrument nobody checks is worse than none — a
fake that quietly stops paging, or a fault script whose `match` never matches, turns a real regression into a
green run. So these tests assert the fake itself: both flavors serve, every paged endpoint terminates, the
JRACLOUD-94906 duplicate really duplicates, each fault fires on exactly the occurrence the script names, and a
500 x 200 corpus costs about a kilobyte until somebody asks for a page.

Faults are asserted through `fake.request` rather than through `Jira`. Whether a 502 is retried is the client's
policy and changes with #123; whether the fake answered 502 on the third bulkfetch is this module's contract and
must not.
"""
from __future__ import annotations

import email.utils
import socket
import tracemalloc
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pytest

from agentdata.connectors import jira_api as J
from agentdata.uat import sprint as SP

from fakes import jira as FJ

CHANGELOG = "/rest/api/3/issue/{}/changelog"
BULKFETCH = "/rest/api/3/changelog/bulkfetch"


# ----------------------------------------------------------------------------------- both flavors serve


def test_cloud_serves_what_the_client_asks_for():
    fake = FJ.FakeJira(4, 6)
    j = fake.client()
    assert j.myself()["displayName"] == "Luna Fake"
    assert J.pin_fields(j.fields())["sprint"] == FJ.SPRINT_FIELD
    assert j.statuses()["10001"] == "done"
    assert [i["key"] for i in j.search("project = RDSD", ["key"])] == fake.corpus.keys()
    assert len(j.changelog("RDSD-1")) == 6
    assert len(j.bulk_changelog(fake.corpus.keys())) == 24


def test_data_center_serves_the_same_run_over_the_v2_api():
    fake = FJ.FakeJira(3, 5, flavor="dc")
    j = fake.client()
    assert j.myself()["name"] == "luna"
    assert [i["key"] for i in j.search("project = RDSD", ["key"])] == fake.corpus.keys()
    assert len(j.changelog("RDSD-2")) == 5
    assert all(r.path.startswith("/rest/api/2/") for r in fake.requests), [str(r) for r in fake.requests]


def test_data_center_omits_field_id_on_custom_fields():
    """Which is the whole reason `changelog()` takes a name -> id map; a fake that filled it in would hide that."""
    fake = FJ.FakeJira(1, 3, flavor="dc")
    page = fake.request("GET", "/rest/api/2/issue/RDSD-1/changelog")
    assert "fieldId" not in page["values"][0]["items"][0]
    rows = fake.client().changelog("RDSD-1", {"sprint": FJ.SPRINT_FIELD})
    assert rows[0]["field_id"] == FJ.SPRINT_FIELD, "the name map has to be what resolves it"


def test_flavor_boundaries_answer_the_way_the_real_servers_do():
    cloud = FJ.FakeJira(1, 1)
    with pytest.raises(urllib.error.HTTPError) as ei:
        cloud.request("GET", "/rest/api/3/search", {"jql": "x"})
    assert ei.value.code == 410, "Cloud retired /search; the client's fallback must see that"

    dc = FJ.FakeJira(1, 1, flavor="dc")
    for path, body in (("/rest/api/2/search/jql", None), ("/rest/api/2/changelog/bulkfetch", {"issueIdsOrKeys": []})):
        with pytest.raises(urllib.error.HTTPError) as ei:
            dc.request("POST" if body else "GET", path, body=body)
        assert ei.value.code == 404, path
    with pytest.raises(urllib.error.HTTPError) as ei:
        dc.request("GET", "/rest/api/3/myself")
    assert ei.value.code == 404, "a v3 path on a Data Center instance is not there"


def test_an_unrouted_path_is_loud():
    """The harness's exit-99 rule: a silent answer would hide a typo'd path in the client."""
    fake = FJ.FakeJira(1, 1)
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", "/rest/api/3/nonsense")
    assert ei.value.code == 404 and "nonsense" in ei.value.read().decode()


# ------------------------------------------------------------------------------------------ paging


def test_cloud_search_pages_by_token_and_terminates():
    fake = FJ.FakeJira(23, 1)
    keys = [i["key"] for i in fake.client().search("project = RDSD", ["key"], max_results=100)]
    assert keys == fake.corpus.keys() and len(keys) == 23
    assert fake.count("/search/jql") == 1, "23 issues fit one 100-row page"
    fake2 = FJ.FakeJira(23, 1, faults=[("search/jql", "every", "cap maxResults 10")])
    keys2 = [i["key"] for i in fake2.client().search("project = RDSD", ["key"], max_results=100)]
    assert keys2 == fake2.corpus.keys() and fake2.count("/search/jql") == 3


def test_data_center_search_pages_by_startat_and_terminates():
    fake = FJ.FakeJira(23, 1, flavor="dc", faults=[("search", "every", "cap maxResults 10")])
    keys = [i["key"] for i in fake.client().search("project = RDSD", ["key"], max_results=100)]
    assert keys == fake.corpus.keys()
    assert fake.count("/search") == 3
    first = fake.request("GET", "/rest/api/2/search", {"jql": "x", "startAt": 0, "maxResults": 50})
    assert first["total"] == 23 and first["startAt"] == 0


def test_changelog_pages_terminate_and_stay_ascending():
    fake = FJ.FakeJira(2, 250)
    rows = fake.client().changelog("RDSD-1")
    assert len(rows) == 250 and fake.count("/changelog") == 3, "250 histories over the client's 100-row page"
    order = [(r["created_utc"], r["changelog_id"]) for r in rows]
    assert order == sorted(order), "the ordering guarantee the replay depends on"
    assert rows == list(FJ.rows_of(fake, 0))


def test_a_page_past_the_end_is_empty_and_last():
    fake = FJ.FakeJira(1, 10)
    page = fake.request("GET", CHANGELOG.format("RDSD-1"), {"startAt": 10, "maxResults": 100})
    assert page["values"] == [] and page["isLast"] is True and page["total"] == 10


def test_expand_changelog_is_newest_first_and_capped_like_data_center():
    """The shape behind the fourth weakness: `total` tells the truth, `histories` does not."""
    fake = FJ.FakeJira(1, 150, flavor="dc", paged_changelog=False)
    issue = fake.request("GET", "/rest/api/2/issue/RDSD-1", {"expand": "changelog"})
    cl = issue["changelog"]
    assert cl["total"] == 150 and len(cl["histories"]) == 100
    ids = [int(h["id"]) for h in cl["histories"]]
    assert ids == sorted(ids, reverse=True), "newest first"
    with pytest.raises(J.JiraError) as ei:
        fake.client().changelog("RDSD-1")
    assert "truncated for RDSD-1: 100 of 150" in str(ei.value)


def test_bulkfetch_groups_by_issue_and_pages_to_the_end():
    fake = FJ.FakeJira(3, 10)
    seen, token, pages = [], None, 0
    while True:
        body = {"issueIdsOrKeys": fake.corpus.keys(), "maxResults": 7}
        if token:
            body["nextPageToken"] = token
        page = fake.request("POST", BULKFETCH, body=body)
        pages += 1
        for group in page["issueChangeLogs"]:
            seen += [(group["issueId"], h["id"]) for h in group["changeHistories"]]
        token = page.get("nextPageToken")
        if not token:
            break
        assert pages < 20, "bulkfetch paging did not terminate"
    assert len(seen) == 30 and len(set(seen)) == 30 and pages == 5
    issue_order = [i for i, _ in seen]
    assert issue_order == sorted(issue_order), "an issue's histories are complete before the next issue starts"
    assert len(fake.client().bulk_changelog(fake.corpus.keys())) == 30


def test_an_unknown_key_in_bulkfetch_is_omitted_not_invented():
    fake = FJ.FakeJira(2, 3)
    page = fake.request("POST", BULKFETCH, body={"issueIdsOrKeys": ["RDSD-1", "NOPE-9"], "maxResults": 100})
    assert [g["issueId"] for g in page["issueChangeLogs"]] == ["10000"] and "nextPageToken" not in page


def test_the_duplicate_flag_really_duplicates_across_pages():
    """JRACLOUD-94906: the same change history arrives on two consecutive pages. The client de-duplicates; the
    point of the flag is that there is something to de-duplicate."""
    plain = _bulk_ids(FJ.FakeJira(2, 10), page=4)
    dupes = _bulk_ids(FJ.FakeJira(2, 10, bulk_duplicate=True), page=4)
    assert len(plain) == len(set(plain)) == 20
    assert len(dupes) > len(set(dupes)) == 20, "the flag must add repeats, not lose rows"
    fake = FJ.FakeJira(2, 10, bulk_duplicate=True)
    assert len(fake.client().bulk_changelog(fake.corpus.keys())) == 20, "and the client still de-duplicates"


def _bulk_ids(fake: FJ.FakeJira, page: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    token = None
    for _ in range(50):
        body = {"issueIdsOrKeys": fake.corpus.keys(), "maxResults": page}
        if token:
            body["nextPageToken"] = token
        resp = fake.request("POST", BULKFETCH, body=body)
        for group in resp["issueChangeLogs"]:
            out += [(group["issueId"], h["id"]) for h in group["changeHistories"]]
        token = resp.get("nextPageToken")
        if not token:
            return out
    raise AssertionError("bulkfetch paging did not terminate")


# ------------------------------------------------------------------------------------- fault scripts


def test_a_fault_fires_on_exactly_the_occurrence_the_script_names():
    fake = FJ.FakeJira(5, 2, faults=[("issue/", 3, 500)])
    for n in (1, 2):
        assert fake.request("GET", CHANGELOG.format(f"RDSD-{n}"))["total"] == 2
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", CHANGELOG.format("RDSD-3"))
    assert ei.value.code == 500
    assert fake.request("GET", CHANGELOG.format("RDSD-4"))["total"] == 2
    fault = fake.faults[0]
    assert (fault.seen, fault.fired) == (4, 1) and fake.unfired() == []


def test_an_occurrence_list_and_every_are_both_scriptable():
    fake = FJ.FakeJira(6, 1, faults=[("issue/", (2, 4), 503)])
    codes = []
    for n in range(1, 6):
        try:
            fake.request("GET", CHANGELOG.format(f"RDSD-{n}"))
            codes.append(200)
        except urllib.error.HTTPError as e:
            codes.append(e.code)
    assert codes == [200, 503, 200, 503, 200]

    always = FJ.FakeJira(2, 1, faults=[("myself", "every", 502)])
    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError):
            always.request("GET", "/rest/api/3/myself")
    assert always.faults[0].fired == 3


def test_the_first_matching_entry_wins():
    fake = FJ.FakeJira(3, 1, faults=[("issue/", 1, 500), ("", 1, 504)])
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", CHANGELOG.format("RDSD-1"))
    assert ei.value.code == 500 and fake.faults[1].seen == 0


@pytest.mark.parametrize("status", [400, 404, 429, 500, 502, 503, 504])
def test_every_http_status_the_epic_names_is_scriptable(status):
    fake = FJ.FakeJira(1, 1, faults=[("", 1, status)])
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", "/rest/api/3/myself")
    assert ei.value.code == status
    assert "errorMessages" in ei.value.read().decode(), "Jira's own error body, not a bare status"


@pytest.mark.parametrize("fault,exc", [("timeout", socket.timeout),
                                       ("reset", ConnectionResetError),
                                       ("interrupt", KeyboardInterrupt)])
def test_every_transport_fault_the_epic_names_is_scriptable(fault, exc):
    fake = FJ.FakeJira(1, 1, faults=[("myself", 1, fault)])
    with pytest.raises(exc):
        fake.request("GET", "/rest/api/3/myself")
    assert fake.faults[0].fired == 1


def test_an_interrupt_lands_mid_pull_where_the_streaming_slice_needs_it():
    fake = FJ.FakeJira(1, 500, faults=[("issue/", 3, "interrupt")])
    with pytest.raises(KeyboardInterrupt):
        fake.client().changelog("RDSD-1")
    assert fake.count("/changelog") == 3, "two pages were fetched before the interrupt, and today they are lost"


def test_a_429_carries_a_retry_after_in_both_forms():
    numeric = FJ.FakeJira(1, 1, faults=[("", 1, 429)])
    with pytest.raises(urllib.error.HTTPError) as ei:
        numeric.request("GET", "/rest/api/3/myself")
    assert ei.value.headers.get("Retry-After") == "3"

    dated = FJ.FakeJira(1, 1, faults=[("", 1, "429 date")])
    with pytest.raises(urllib.error.HTTPError) as ei:
        dated.request("GET", "/rest/api/3/myself")
    when = email.utils.parsedate_to_datetime(ei.value.headers.get("Retry-After"))
    assert 0 < (when - datetime.now(timezone.utc)).total_seconds() <= 60, "an HTTP date in the near future"

    # and the client copes with both, which is the reason to have both
    for fake in (FJ.FakeJira(1, 1, faults=[("myself", 1, 429)]),
                 FJ.FakeJira(1, 1, faults=[("myself", 1, "429 date")])):
        assert fake.client().myself()["displayName"] == "Luna Fake"
        assert fake.count("myself") == 2 and fake.waited > 0 and fake.slept


def test_400_invalid_key_names_the_key_the_way_jira_does():
    fake = FJ.FakeJira(2, 1, faults=[("search/jql", 1, "400 invalid key NOPE-9")])
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", "/rest/api/3/search/jql", {"jql": "key in (NOPE-9)"})
    assert ei.value.code == 400 and "NOPE-9" in ei.value.read().decode()


def test_drop_islast_takes_the_terminator_away():
    fake = FJ.FakeJira(1, 50, faults=[("issue/", 1, "drop isLast")])
    page = fake.request("GET", CHANGELOG.format("RDSD-1"), {"startAt": 0, "maxResults": 100})
    assert "isLast" not in page and page["total"] == 50
    assert "isLast" in fake.request("GET", CHANGELOG.format("RDSD-1"))


def test_cap_maxresults_makes_the_server_ignore_the_asked_for_page_size():
    fake = FJ.FakeJira(1, 250, faults=[("issue/", "every", "cap maxResults 100")])
    page = fake.request("GET", CHANGELOG.format("RDSD-1"), {"startAt": 0, "maxResults": 1000})
    assert page["maxResults"] == 100 and len(page["values"]) == 100
    assert len(fake.client().changelog("RDSD-1")) == 250, "the client must follow the echoed page size"


def test_duplicate_and_shuffle_disturb_one_page():
    dup = FJ.FakeJira(1, 10, faults=[("issue/", 1, "duplicate histories")])
    page = dup.request("GET", CHANGELOG.format("RDSD-1"))
    assert len(page["values"]) == 11 and page["values"][0]["id"] == page["values"][-1]["id"]

    shuffled = FJ.FakeJira(1, 10, faults=[("issue/", 1, "shuffle pages")])
    ids = [int(h["id"]) for h in shuffled.request("GET", CHANGELOG.format("RDSD-1"))["values"]]
    assert ids == sorted(ids, reverse=True), "the page came back out of order"


def test_404_on_bulkfetch_multiplies_requests_which_is_the_weakness_126_removes():
    fake = FJ.FakeJira(30, 2, faults=[("bulkfetch", "every", 404)])
    rows = fake.client().bulk_changelog(fake.corpus.keys())
    assert len(rows) == 60, "the fallback is still correct — it is the cost that is wrong"
    assert fake.count("bulkfetch") == 1 and fake.count("/issue/") == 30, \
        "one bulkfetch the operator budgeted for became 30 requests, silently"


def test_an_unknown_fault_is_a_typo_not_a_no_op():
    with pytest.raises(ValueError) as ei:
        FJ.FakeJira(1, 1, faults=[("", 1, "explode please")])
    assert "explode please" in str(ei.value)


def test_unfired_names_a_match_that_never_matched():
    fake = FJ.FakeJira(1, 1, faults=[("bulkfitch", 1, 500)])
    fake.request("GET", "/rest/api/3/myself")
    assert [f.match for f in fake.unfired()] == ["bulkfitch"]


# ------------------------------------------------------------------------------------- rate limiting


def test_the_token_bucket_refuses_with_a_real_429_and_the_headers_say_so():
    fake = FJ.FakeJira(1, 1, bucket=FJ.TokenBucket(capacity=2, refill=0.5, retry_after=4))
    first = fake.opener(_req(fake, "/rest/api/3/myself"))
    assert first.headers.get("X-RateLimit-Limit") == "2" and first.headers.get("X-RateLimit-Remaining") == "1"
    assert first.headers.get("X-RateLimit-NearLimit") == "true"
    fake.request("GET", "/rest/api/3/myself")
    with pytest.raises(urllib.error.HTTPError) as ei:
        fake.request("GET", "/rest/api/3/myself")
    assert ei.value.code == 429 and int(ei.value.headers.get("Retry-After")) >= 1
    assert ei.value.headers.get("X-RateLimit-Remaining") == "0"

    fake.sleep(4)                       # the injected sleeper spends no real time
    assert fake.request("GET", "/rest/api/3/myself")["displayName"] == "Luna Fake"
    assert fake.waited == 4.0


def test_the_reset_header_can_be_an_epoch_or_a_delta():
    epoch = FJ.FakeJira(1, 1, bucket=FJ.TokenBucket(capacity=5))
    assert int(epoch.opener(_req(epoch, "/rest/api/3/myself")).headers["X-RateLimit-Reset"]) > 10_000_000
    delta = FJ.FakeJira(1, 1, bucket=FJ.TokenBucket(capacity=5), reset_style="delta")
    assert int(delta.opener(_req(delta, "/rest/api/3/myself")).headers["X-RateLimit-Reset"]) < 10_000_000


def test_no_rate_headers_when_the_tenant_does_not_send_them():
    """Data Center usually does not. Code that assumes the headers exist has to meet a server without them."""
    fake = FJ.FakeJira(1, 1, flavor="dc")
    assert fake.opener(_req(fake, "/rest/api/2/myself")).headers.get("X-RateLimit-Limit") is None


def _req(fake: FJ.FakeJira, path: str):
    return urllib.request.Request(fake.base_url + path, method="GET",
                                  headers={"Authorization": "Basic redacted"})


# ------------------------------------------------------------------------------------------ records


def test_every_request_is_recorded_and_the_token_never_is():
    fake = FJ.FakeJira(2, 2)
    j = fake.client()
    j.myself()
    j.changelog("RDSD-1")
    j.bulk_changelog(["RDSD-1"])
    assert [r.method for r in fake.requests].count("POST") == 1
    assert fake.last("bulkfetch").body["issueIdsOrKeys"] == ["RDSD-1"]
    assert fake.matching("/changelog?")[0].params["startAt"] == "0"
    for r in fake.requests:
        assert r.headers.get("Authorization") == "REDACTED"
        assert FJ.FAKE_TOKEN not in repr(r), "a fake token is still a token-shaped string in a log"


# ------------------------------------------------------------------------------------------ laziness


def test_a_500_by_200_corpus_costs_a_kilobyte_until_somebody_asks_for_a_page():
    """The budget tests in #124 measure the *client's* peak. If the fake materialised 100,000 dicts to answer the
    first page, that measurement would be of the fake and the slice would be unprovable."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        fake = FJ.FakeJira(issues=500, histories=200)
        construct = tracemalloc.get_traced_memory()[1]
        assert fake.corpus.issues * fake.corpus.histories == 100_000
        assert construct < 20_000, f"constructing the fake peaked at {construct} bytes"

        tracemalloc.reset_peak()
        window = fake.corpus.page(499, 100, 100)
        assert len(window) == 100 and tracemalloc.get_traced_memory()[1] < 300_000

        tracemalloc.reset_peak()
        page = fake.request("GET", CHANGELOG.format("RDSD-500"), {"startAt": 100, "maxResults": 100})
        served = tracemalloc.get_traced_memory()[1]
        assert len(page["values"]) == 100 and page["total"] == 200
        assert served < 1_000_000, f"serving one page peaked at {served} bytes"
    finally:
        tracemalloc.stop()


def test_the_corpus_is_deterministic_across_instances():
    a, b = FJ.FakeJira(3, 20, seed=7), FJ.FakeJira(3, 20, seed=7)
    assert a.corpus.history(2, 19) == b.corpus.history(2, 19)
    assert FJ.FakeJira(3, 20, seed=8).corpus.history(2, 19) != a.corpus.history(2, 19)


# -------------------------------------------------------------------------------------- sprint replay


def test_the_agile_endpoints_carry_a_whole_sprint_replay():
    """`ad-jira sprint-replay`'s exact sequence, with nothing mocked but the socket."""
    fake = FJ.FakeJira(8, 6)
    j = fake.client()
    sprint_json = j.sprint(41)
    assert sprint_json["originBoardId"] == 3 and sprint_json["state"] == "closed"
    assert [s["id"] for s in j.board_sprints(3)] == [40, 41, 42]
    assert [s["id"] for s in j.board_sprints(3, "future")] == [42]

    pins = J.pin_fields(j.fields())
    fields = ["key", "issuetype", "created", "status", pins["sprint"], *pins["story_points"]]
    issues = {i["key"]: i for i in j.search("sprint = 41", fields)}
    rows = j.bulk_changelog(list(issues), None, pins["name_to_id"],
                            id_to_key={str(v["id"]): k for k, v in issues.items()})
    states = [SP.build_issue_state(issues[k], rows, pins["sprint"], pins["story_points"]) for k in issues]
    replayed, summary = SP.replay(states, SP.SprintInfo.from_json(sprint_json), j.statuses(),
                                  pins["sprint"], pins["story_points"])
    assert summary["committed_points"] > 0 and summary["completed_points"] > 0
    assert summary["issues_scanned"] == len(issues)

    delta = SP.sprintreport_delta(j.sprintreport(3, 41), replayed, summary)
    assert delta["report_completed_points"] is not None and delta["keys_only_in_replay"] == []
    assert [i["key"] for i in j.sprint_issues(41, ["key"])] == sorted(issues)


def test_an_unknown_sprint_or_board_is_a_404():
    fake = FJ.FakeJira(2, 2)
    for path in ("/rest/agile/1.0/sprint/999", "/rest/agile/1.0/board/999/sprint"):
        with pytest.raises(urllib.error.HTTPError) as ei:
            fake.request("GET", path)
        assert ei.value.code == 404, path
