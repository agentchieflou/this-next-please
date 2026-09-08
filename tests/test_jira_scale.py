"""What a big Jira pull costs: memory, waiting, and requests — and the fault matrix it survives.

`tests/test_jira_client.py` proves the client fetches the right rows and `tests/test_jira_cli.py` proves the two
commands report honestly. Neither answers the three questions epic #121 was opened over, which are all about
*cost*: does a hundred-thousand-row pull hold a hundred thousand rows, does a run that meets a rate limit spend
its budget asleep, and does the second run of the same JQL really cost one search. Those are the numbers the
operator's shared token is charged for, and until they were measured the only way to learn them was to run a
remediation loop against the real tenant and watch it get throttled.

So this file is the budget proof, in `tests/test_perf_loop.py`'s style: run the real sequence against
`tests/fakes/jira.py`, measure with `tracemalloc` and with the fake's own counters, and assert numbers rather
than shapes.

* **Memory.** 500 issues x 200 histories is 100,000 rows through the process. The peak is measured inside two
  windows — one near the start of the pull, one near the end — rather than across all 100,000 rows, for two
  reasons. Tracing every allocation of the whole pull costs about twenty seconds, and this file has a ten-second
  budget on CI. And a single whole-run peak cannot tell a bounded pull from one that grew for the first thirty
  seconds and then plateaued: two windows can, because the late peak of an unbounded pull is the size of
  everything fetched so far.
* **Waiting.** Nothing here sleeps. `FakeJira.sleep` is the injected sleeper and it advances the fake's own
  clock instead of the wall clock, so a run that would have waited five minutes for a rate limit finishes in
  milliseconds. Every assertion about waiting is therefore against the *summed* sleep — `fake.waited` and
  `Stats.waited_seconds` — and never against elapsed time, which on this path is only the cost of the arithmetic.
* **Requests.** The cache's promise is not "faster", it is "exactly one search and one field lookup". An
  inequality would still pass with a cache that fetched half the issues, so the counts here are equalities and
  the arithmetic behind each one is written down.

The last section is the fault matrix. Every fault kind `tests/fakes/jira.py` offers is driven through a real
pull here, and `test_every_fault_the_fake_offers_is_exercised_somewhere_in_the_suite` reads `parse_fault`'s own
source to check that the list has not grown behind the sweep's back: a fake that can inject something no test
injects is a fault mode nobody has ever seen the client meet.
"""
from __future__ import annotations

import ast
import glob
import inspect
import os
import re
import socket
import time
import tracemalloc
from typing import Any, Iterator

import pytest

from agentdata import cli_jira as CLI
from agentdata import model as M
from agentdata.connectors import jira_api as J
from agentdata.connectors import jira_http as H

from fakes import jira as FJ

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _pull(fake: FJ.FakeJira, *, keys: list[str] | None = None, use_bulk: bool = True, bulk_issues: int = 25,
          bulk_page: int = 500, on_event=None, **kw) -> tuple[J.Jira, list[dict]]:
    """One whole `iter_changelog` through the fake, with the id map the CLI always has.

    Passing `id_to_key` is not a shortcut: `cmd_changelog` gets it free from the search it already ran, so a
    pull without it would count `key in (...)` lookups this code path never makes in production.

    `j.wall` is moved onto the fake's clock, which the client's own docstring names as the way to steer it. It
    matters here and nowhere else in the suite: `X-RateLimit-Reset` is an epoch, so a pause is `reset_at` minus
    wall time, and leaving wall time real would make the length of each pause depend on how fast the machine ran
    the loop. Measuring waiting against a clock that only the injected sleeper advances is what makes these
    numbers the same on a laptop and on a loaded CI runner.
    """
    j = fake.client(**kw)
    j.wall = lambda: fake.wall.timestamp()
    ids = {fake.corpus.issue_id(i): fake.corpus.key(i) for i in range(fake.corpus.issues)}
    rows = list(j.iter_changelog(keys or fake.corpus.keys(), use_bulk=use_bulk, bulk_issues=bulk_issues,
                                 bulk_page=bulk_page, id_to_key=ids, on_event=on_event))
    return j, rows


# ------------------------------------------------------------------------------------- the memory ceiling

# One chunk of 20 issues x 200 histories is 4,000 rows, so a window of that size holds a whole chunk's build-up
# — the high-water mark the bound is about — and tracing 8,000 rows rather than 100,000 is what keeps this file
# inside its ten-second budget.
WINDOW = 4_000
# Generous on purpose. The number that matters is not 20 MB, it is that the late window is no bigger than the
# early one; a ceiling tight enough to argue about would fail on an interpreter with different arena behaviour.
CEILING = 20 * 1024 * 1024


def _peak_over(rows: Iterator[dict], skip: int, width: int) -> int:
    """Bytes newly allocated and still alive at the high-water mark of `width` rows, after skipping `skip`.

    Tracing is started *inside* the pull, so allocations made before the window are invisible and the number is
    what the pull grew by while the window ran. That is exactly the question: a client that streams grows by one
    page, a client that accumulates grows by everything it has fetched.
    """
    for _ in range(skip):
        next(rows)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        for _ in range(width):
            next(rows)
        return tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


def test_a_500_by_200_pull_holds_one_chunk_and_not_the_result():
    """100,000 rows through the client, and the last four thousand cost no more than the first four thousand.

    Before #124 every caller did `list(...)`: the peak of this pull was the whole result, tens of megabytes that
    grew with the JQL and that no flag could move. The bound now is one chunk — `bulk_issues` issues and their
    histories — because the client has to hold a chunk to order it, and nothing beyond it.
    """
    fake = FJ.FakeJira(issues=500, histories=200)
    j = fake.client()
    ids = {fake.corpus.issue_id(i): fake.corpus.key(i) for i in range(500)}
    rows = iter(j.iter_changelog(fake.corpus.keys(), bulk_issues=20, bulk_page=500, id_to_key=ids))

    early = _peak_over(rows, 0, WINDOW)
    late = _peak_over(rows, 80_000, WINDOW)
    seen = 2 * WINDOW + 80_000 + sum(1 for _ in rows)

    assert seen == 100_000, "the pull did not deliver every row"
    assert early < CEILING, f"the first {WINDOW:,} rows peaked at {early / 1e6:.1f} MB"
    assert late < CEILING, f"the last rows peaked at {late / 1e6:.1f} MB"
    assert late < early * 2, (f"the peak grew from {early / 1e6:.1f} MB to {late / 1e6:.1f} MB across the pull, "
                              f"which is what an accumulating client looks like")


def test_the_chunk_size_is_the_memory_knob_and_a_smaller_one_holds_less():
    """`--bulk-issues` is the flag the ceiling test leans on, so it has to actually move the peak.

    If it did not, the bound above would be an accident of the corpus rather than a property an operator can use
    on a JQL with deeper histories than this one.
    """
    peaks = {}
    for chunk in (5, 50):
        fake = FJ.FakeJira(issues=60, histories=100)
        j = fake.client()
        ids = {fake.corpus.issue_id(i): fake.corpus.key(i) for i in range(60)}
        rows = iter(j.iter_changelog(fake.corpus.keys(), bulk_issues=chunk, bulk_page=500, id_to_key=ids))
        peaks[chunk] = _peak_over(rows, 0, 2_000)
        assert 2_000 + sum(1 for _ in rows) == 6_000
    assert peaks[5] < peaks[50], f"chunk size did not change the peak: {peaks}"


# -------------------------------------------------------------------------- the clock nothing ever spends


def test_a_run_that_would_have_waited_a_quarter_of_an_hour_finishes_instantly():
    """The wall clock of a throttled run is the sum of the injected sleeps, and none of them happened.

    A token bucket that refuses is the only way today's client would learn it is throttled, and the pause it
    takes in response is the single largest cost of a long pull — larger than the requests. Asserting elapsed
    time would prove nothing here (the fake answers in microseconds) and would make the test a stopwatch race on
    CI, so the assertion is on `fake.waited`: what the run *would* have spent asleep against a real tenant.
    """
    fake = FJ.FakeJira(200, 50, bucket=FJ.TokenBucket(capacity=3, refill=0.02, retry_after=60),
                       faults=[("bulkfetch", 3, 429)])
    started = time.monotonic()
    j, rows = _pull(fake, bulk_issues=10, rand=lambda: 0.0)
    real = time.monotonic() - started

    assert len(rows) == 10_000, "a throttled run must still deliver every row"
    assert fake.waited > 600, f"the bucket did not make the client wait; it waited {fake.waited:.1f}s"
    assert j.sleep == fake.sleep, "the client has to be sleeping through the injected sleeper, not time.sleep"
    assert j.stats.waited_seconds == pytest.approx(fake.waited, abs=0.01), \
        "`--stats` must report the waiting the operator was charged for"
    assert real < 5.0, f"something really slept: {real:.1f}s of wall clock for {fake.waited:.0f}s of Jira time"
    assert j.stats.elapsed_seconds < 5.0, "elapsed is real time and stays real; only the waiting is injected"

    assert len(fake.slept) == j.stats.retries + j.stats.rate_limit_waits, \
        "every sleep is either a retry's backoff or a rate-limit pause; an unaccounted one is a wait nobody sees"
    assert j.stats.retries == 1 and j.stats.rate_limit_waits > 1, \
        "this fixture is meant to exercise both the reactive 429 and the proactive header pause"
    assert max(fake.slept) <= H.MAX_PAUSE_SECONDS, "a pause longer than the cap is indistinguishable from a hang"


def test_the_retry_after_header_is_what_sets_the_wait_not_the_backoff():
    """`Retry-After: 3` means three seconds, exactly, and the jitter is not added on top of a server's number.

    With `rand` pinned to zero the backoff ladder would give 1.0s for the first attempt, so a wait of exactly
    3.0s is proof the header won rather than proof of an accident.
    """
    fake = FJ.FakeJira(2, 5, faults=[("bulkfetch", 1, 429)])
    j, rows = _pull(fake, bulk_issues=2, rand=lambda: 0.0)
    assert len(rows) == 10
    assert fake.slept == [3.0], f"the client waited {fake.slept} instead of the server's Retry-After"
    assert j.stats.retries == 1 and j.stats.waited_seconds == pytest.approx(3.0)


# ---------------------------------------------------------------------------- the second run's exact cost


@pytest.fixture()
def out_dir(tmp_path, monkeypatch):
    """`.agent/out` for this test: the TSV, the JSON and the cache all land under it."""
    d = str(tmp_path / "out")
    monkeypatch.setattr(M, "OUT_DIR", d)
    return d


@pytest.fixture()
def wire(monkeypatch):
    """Point `ad-jira` at a fake instance, leaving `_client` itself real.

    The `updated` stamp is patched onto the corpus here rather than in `tests/fakes/jira.py`: every real Jira
    returns one and the whole cache turns on it, but the fake belongs to another slice.
    """
    def _wire(fake: FJ.FakeJira):
        corpus = fake.corpus
        original = corpus.issue_json

        def issue_json(i, fields=None, base_url=""):
            js = original(i, fields, base_url)
            if fields is None or "updated" in fields:
                js["fields"]["updated"] = "2026-09-01T10:00:00.000+0000"
            return js

        object.__setattr__(corpus, "issue_json", issue_json)      # Corpus is a frozen dataclass
        monkeypatch.setattr(J, "load_credentials",
                            lambda cfg=None: J.Creds(fake.base_url, FJ.FAKE_EMAIL, FJ.FAKE_TOKEN, "test"))
        monkeypatch.setattr(J, "detect_flavor",
                            lambda creds, cfg=None, redetect=False, **kw: (fake.client(**kw),
                                                                           {"displayName": "Luna Fake"}))
        return fake
    return _wire


def _rows_in(out: str) -> int:
    m = re.search(r"^  rows: (\d+)$", out, re.M)
    assert m, f"no row count in the meta:\n{out[:400]}"
    return int(m.group(1))


def test_the_second_run_of_an_unchanged_jql_costs_one_search_and_one_field_lookup(wire, out_dir, capsys):
    """The cache's promise stated as an equality, because an inequality would hide a half-served run.

    120 issues at 100 per search page is two `/search/jql` requests; `j.fields()` is one; three chunks of forty
    issues is three `/changelog/bulkfetch` requests. Six, and then three — and the three are the two the cache
    cannot avoid (it needs every `updated` stamp to decide) plus the field map. Not one changelog request is
    made the second time, which is the whole point: the remediation loop reruns this command after every fix.
    """
    first = wire(FJ.FakeJira(120, 2))
    rc = CLI.main(["changelog", "--jql", "project = RDSD", "--bulk-issues", "40", "--quiet"])
    out = capsys.readouterr().out
    assert rc == 0
    assert first.count("/search/jql") == 2 and first.count("/field") == 1
    assert first.count("bulkfetch") == 3
    assert len(first.requests) == 6, [str(r) for r in first.requests]
    assert _rows_in(out) == 240

    second = wire(FJ.FakeJira(120, 2))
    rc = CLI.main(["changelog", "--jql", "project = RDSD", "--bulk-issues", "40", "--quiet"])
    out2 = capsys.readouterr().out
    assert rc == 0
    assert len(second.requests) == 3, [str(r) for r in second.requests]
    assert second.count("bulkfetch") == 0 and second.count("/changelog") == 0, "not one changelog request"
    assert _rows_in(out2) == 240, "and every row still came out, from the cache"


def test_a_refreshed_run_pays_the_full_price_again(wire, out_dir, capsys):
    """The counter-test the equality above needs: `--refresh` is the operator saying "do not trust the cache",
    and it has to cost what the first run cost or the cache is deciding something it was told not to."""
    wire(FJ.FakeJira(120, 2))
    assert CLI.main(["changelog", "--jql", "project = RDSD", "--bulk-issues", "40", "--quiet"]) == 0
    capsys.readouterr()

    again = wire(FJ.FakeJira(120, 2))
    assert CLI.main(["changelog", "--jql", "project = RDSD", "--bulk-issues", "40", "--refresh", "--quiet"]) == 0
    assert len(again.requests) == 6, [str(r) for r in again.requests]
    assert _rows_in(capsys.readouterr().out) == 240


# --------------------------------------------------------------------------------------- the fault matrix


def test_a_429_is_waited_out_rather_than_losing_the_run():
    fake = FJ.FakeJira(4, 5, faults=[("bulkfetch", 1, 429)])
    j, rows = _pull(fake, bulk_issues=4)
    assert len(rows) == 20 and j.stats.retries == 1
    assert fake.waited == 3.0 and not fake.unfired()


def test_a_429_whose_retry_after_is_an_http_date_is_parsed_the_same_way():
    """The second legal spelling of the header, and the one a client that only calls `int()` silently ignores —
    which turns a polite wait into an immediate retry into a longer ban."""
    fake = FJ.FakeJira(4, 5, faults=[("bulkfetch", 1, "429 date")])
    j, rows = _pull(fake, bulk_issues=4)
    assert len(rows) == 20 and j.stats.retries == 1
    assert 0 < fake.waited <= 3.5, f"an HTTP-date Retry-After was read as {fake.waited}s"


def test_one_500_is_retried_and_a_second_on_the_same_page_is_reported():
    """Jira answers 500 for a transient backend hiccup on a changelog page often enough to be worth one more
    try; a *second* 500 on the same page is a real server error, and five more attempts only delay the report.

    Scripted on the per-issue endpoint on purpose. Bulkfetch has a page-shrink of its own that answers a 5xx by
    halving `maxResults` and asking again, so a 500 there proves the shrink rather than the retry class.
    """
    once = FJ.FakeJira(1, 5, faults=[("issue/", 1, 500)])
    j, rows = _pull(once, use_bulk=False)
    assert len(rows) == 5 and j.stats.retries == 1 and once.count("/changelog") == 2

    twice = FJ.FakeJira(1, 5, faults=[("issue/", (1, 2), 500)])
    with pytest.raises(J.JiraHTTPError) as ei:
        _pull(twice, use_bulk=False)
    assert ei.value.status == 500
    assert twice.count("/changelog") == 2, "the second 500 is fatal, not the start of a ladder"
    assert "startAt=0" in str(ei.value), "the page that died has to name itself in the error"


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_gateway_status_is_retried_rather_than_losing_the_run(status):
    """502 and 504 come from the tenant's proxy, not from Jira. Before #123 only 429 and 503 were retried, so
    either of them on page 40 of 80 raised and threw away every page already fetched."""
    fake = FJ.FakeJira(4, 5, faults=[("bulkfetch", 1, status)])
    j, rows = _pull(fake, bulk_issues=4)
    assert len(rows) == 20 and j.stats.retries == 1 and not fake.unfired()


def test_a_timeout_and_a_reset_are_recovered_in_place():
    """A socket timeout and a reset connection are the same event as far as a pull is concerned: the page has to
    be asked for again. Matching only one of them is why a timeout on page 40 used to kill the run, so both are
    scripted into one pull — a second and a third page that fail differently and are both recovered."""
    for exc in (socket.timeout, ConnectionResetError):
        assert H.classify(exc=exc("scripted")) == "retry"
    fake = FJ.FakeJira(6, 5, faults=[("bulkfetch", 1, "timeout"), ("bulkfetch", 3, "reset")])
    j, rows = _pull(fake, bulk_issues=6, bulk_page=10)
    assert len(rows) == 30 and j.stats.retries == 2
    assert [f.fired for f in fake.faults] == [1, 1] and not fake.unfired()


def test_a_page_that_forgot_islast_still_terminates():
    """`isLast` is the terminator; without it the loop falls back to `startAt` against `total`. A client that
    trusted only `isLast` would either stop a page early or page forever."""
    fake = FJ.FakeJira(1, 150, faults=[("issue/", 1, "drop isLast")])
    _, rows = _pull(fake, use_bulk=False)
    assert len(rows) == 150 and fake.count("/changelog") == 2
    assert "isLast" not in fake.requests[0].params


def test_a_server_that_caps_maxresults_is_followed_not_argued_with():
    """Data Center caps the page it will answer with and echoes its own `maxResults`. Asking for 1,000 and
    assuming 1,000 arrived is how a history comes back a quarter complete and looks whole."""
    fake = FJ.FakeJira(1, 150, faults=[("issue/", "every", "cap maxResults 25")])
    _, rows = _pull(fake, use_bulk=False)
    assert len(rows) == 150 and fake.count("/changelog") == 6
    assert fake.last("/changelog").params["maxResults"] == "100", "the client keeps asking for its own page size"


def test_a_repeated_history_is_de_duplicated_within_a_page_and_across_two():
    """JRACLOUD-94906. The same change history arrives twice — at the end of one page and again at the start of
    the next — and a pull that counted rows would report a history longer than the issue has."""
    within = FJ.FakeJira(4, 5, faults=[("bulkfetch", 1, "duplicate histories")])
    _, rows = _pull(within, bulk_issues=4)
    assert len(rows) == 20 and within.faults[0].fired == 1

    across = FJ.FakeJira(4, 5, bulk_duplicate=True)
    _, rows2 = _pull(across, bulk_issues=4, bulk_page=6)
    assert len(rows2) == 20
    assert across.count("bulkfetch") > 1, "one page cannot show a cross-page duplicate"
    assert rows2 == rows, "and both paths produce the same history"


def test_a_page_that_comes_back_out_of_order_is_emitted_in_order():
    """The ordering guarantee the replay depends on is enforced at fetch time, per key, because the caller
    streams rows to disk and can never re-read them to sort."""
    fake = FJ.FakeJira(4, 8, faults=[("bulkfetch", "every", "shuffle pages")])
    _, rows = _pull(fake, bulk_issues=4, bulk_page=4)
    assert len(rows) == 32
    keys = [r["key"] for r in rows]
    assert keys == sorted(keys), "a key's rows must arrive together"
    for key in set(keys):
        pairs = [(r["created_utc"], r["changelog_id"]) for r in rows if r["key"] == key]
        assert pairs == sorted(pairs), f"{key} came out in the order the server sent it"


def test_a_400_naming_a_bad_key_drops_that_key_and_keeps_the_chunk():
    """A `key in (...)` with one dead key used to reject the whole chunk into a per-issue fallback — the 3,000
    requests an operator budgeted three for. The named key is dropped, the chunk is retried once, and the meta
    says which key went."""
    fake = FJ.FakeJira(4, 5, faults=[("bulkfetch", 1, "400 invalid key RDSD-2")])
    j, rows = _pull(fake, bulk_issues=4)
    assert sorted({r["key"] for r in rows}) == ["RDSD-1", "RDSD-3", "RDSD-4"]
    assert len(rows) == 15
    assert j.bulk_meta["skipped_keys"] == ["RDSD-2"]
    assert fake.count("/issue/") == 0, "a named bad key is dropped, not paid for with a per-issue fallback"


def test_a_404_on_bulkfetch_falls_back_per_issue_and_announces_the_cost():
    """A Jira without the endpoint is a fact, not a failure — but the fallback is one request per issue, and
    doing that silently is the cheapest way there is to get a shared token throttled."""
    fake = FJ.FakeJira(6, 3, faults=[("bulkfetch", "every", 404)])
    events: list[tuple[str, dict]] = []
    j, rows = _pull(fake, bulk_issues=6, on_event=lambda kind, payload: events.append((kind, payload)))
    assert len(rows) == 18
    assert fake.count("bulkfetch") == 1 and fake.count("/issue/") == 6
    assert j.bulk_meta["fallback"] is True and "404" in j.bulk_meta["fallback_reason"]
    assert ("fallback", {"reason": j.bulk_meta["fallback_reason"], "requests": 6}) in events


# ------------------------------------------------------------------- and nothing the fake offers is unswept

# `parse_fault`'s spellings, mapped to the label a scripted fault is recorded under. The left-hand side is
# checked against the fake's own source below, so a new fault kind lands here as a failure rather than as a
# quietly untested branch.
SPELLING_LABELS = {
    "timeout": "timeout",
    "reset": "reset",
    "interrupt": "interrupt",
    "drop islast": "drop_islast",
    "duplicate histories": "duplicate",
    "shuffle pages": "shuffle",
    "cap maxresults": "cap",
    "429 date": "status 429 date",
    "400 invalid key": "status 400 named key",
}

# The statuses #127's acceptance criteria names. Any int is a scriptable fault, so the fake's source cannot say
# which ones matter; this list is the epic's answer and the reason each of them has a test above.
REQUIRED_STATUSES = ("status 400 named key", "status 404", "status 429", "status 429 date",
                     "status 500", "status 502", "status 503", "status 504")

# 500 is the one status whose *repetition* is a separate behaviour: once is retried, twice is reported.
REQUIRED_REPEATED = ("status 500",)


def _label(fault: Any) -> str:
    """The name a fault is swept under: its `parse_fault` kind, with the two statuses that carry an extra."""
    kind, arg, extra = FJ.parse_fault(fault)
    if kind != "status":
        return kind
    if extra.get("retry_after") == "date":
        return "status 429 date"
    if extra.get("bad_key"):
        return "status 400 named key"
    return f"status {arg}"


def _scripted_faults() -> dict[str, set[tuple[str, str]]]:
    """Every literal `faults=[(match, nth, fault)]` in the suite, as {label: {(how often, file)}}.

    Read with `ast` rather than by running anything: a sweep that had to execute every test to learn what they
    inject would be slower than the suite it checks, and a regex would miss a script split over two lines.
    """
    found: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(glob.glob(os.path.join(TESTS_DIR, "**", "*.py"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.keyword) and node.arg == "faults"):
                continue
            for entry in getattr(node.value, "elts", []):
                if not (isinstance(entry, ast.Tuple) and len(entry.elts) == 3):
                    continue
                nth, fault = entry.elts[1], entry.elts[2]
                if not isinstance(fault, ast.Constant):
                    continue                      # a parametrized fault; the parameters carry the spelling
                try:
                    label = _label(fault.value)
                except ValueError:
                    continue                      # `test_an_unknown_fault_is_a_typo` scripts one on purpose
                often = "once" if isinstance(nth, ast.Constant) and isinstance(nth.value, int) else "repeated"
                found.setdefault(label, set()).add((often, os.path.basename(path)))
    return found


def _spellings_the_fake_accepts() -> set[str]:
    """The fault spellings `parse_fault` compares against, read out of its own source."""
    src = inspect.getsource(FJ.parse_fault)
    out: set[str] = set()
    for group in re.findall(r"low in \(([^)]*)\)", src):
        out |= {part.strip().strip("\"'") for part in group.split(",") if part.strip()}
    out |= set(re.findall(r'low == "([^"]+)"', src))
    out |= set(re.findall(r'low\.startswith\("([^"]+)"\)', src))
    return out


def test_the_sweep_knows_every_spelling_the_fake_accepts():
    """The fake grows; this map is how the sweep finds out.

    A new fault kind in `parse_fault` that nothing injects is a failure mode the client has never been shown,
    and the only place that would notice is here.
    """
    accepted = _spellings_the_fake_accepts()
    assert accepted, "parse_fault no longer compares spellings the way this sweep reads them"
    assert set(SPELLING_LABELS) == accepted, \
        (f"tests/fakes/jira.py accepts {sorted(accepted - set(SPELLING_LABELS))} that this sweep does not know "
         f"about, and this sweep claims {sorted(set(SPELLING_LABELS) - accepted)} that it does not accept")


def test_every_fault_the_fake_offers_is_exercised_somewhere_in_the_suite():
    """A fault the fake can inject and no test injects is a failure mode nobody has watched the client meet.

    The sweep reads scripts rather than outcomes on purpose: whether a 502 is *retried* is the client's policy
    and moves with the epic, but whether some test hands the client a 502 at all is a fact about the suite, and
    it is the one that silently stops being true when a case is deleted.
    """
    exercised = _scripted_faults()
    for label in sorted(set(SPELLING_LABELS.values()) | set(REQUIRED_STATUSES)):
        assert label in exercised, f"no test in the suite injects {label}"
    for label in REQUIRED_REPEATED:
        often = {how for how, _file in exercised[label]}
        assert {"once", "repeated"} <= often, \
            f"{label} is only scripted {sorted(often)}; once and twice are different behaviours"


def test_the_cross_page_duplicate_is_exercised_too():
    """`bulk_duplicate` is the one fault the script cannot express — it needs two pages — so it is a constructor
    flag, and a sweep that only read fault scripts would not see it."""
    users = set()
    for path in sorted(glob.glob(os.path.join(TESTS_DIR, "**", "*.py"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "bulk_duplicate":
                users.add(os.path.basename(path))
    assert users, "nothing exercises the JRACLOUD-94906 cross-page duplicate"
