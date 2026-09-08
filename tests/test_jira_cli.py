"""What an operator sees when a changelog pull is big, is cut short, or has already been paid for.

`tests/test_jira_client.py` proves the client fetches correctly; this file is about the two commands on top of
it, and every test here is one of the ways those commands used to lie or lose work.

* **A five-thousand-issue pull built every row in memory and wrote the file at the end.** So a 502 at minute
  fourteen delivered nothing, and the peak was the size of the result. The ceiling test measures the peak with
  `tracemalloc` over a pull that writes a hundred thousand rows; the interrupt and budget tests assert that what
  arrived before the failure is on disk and counted.
* **A short result was indistinguishable from a whole one.** Nothing in the TOON said `partial`, and
  `sprint-replay` computed `committed_points` over whatever it got. Here a partial pull exits non-zero, names
  its reason, lists the issues that did not finish and prints the command that resumes it -- and the replay
  refuses such an input until `--allow-partial` says otherwise.
* **The second run cost exactly what the first one did.** The cache tests assert the request counts, not just
  the output: an unchanged JQL makes no changelog request at all, three moved `updated` stamps make exactly
  three, and `--since` filters the file while the cache keeps the whole history.

The one thing none of this may change is the output. `test_a_small_pull_renders_as_a_materialised_table_does`
is the regression that guards it: same meta, same table, same file bytes as `AgentTable` would have written.
"""
from __future__ import annotations

import os
import re
import shlex
import tracemalloc

import pytest

from agentdata import cli_jira as CLI
from agentdata import config as C
from agentdata import model as M
from agentdata import policy
from agentdata import toon
from agentdata.connectors import jira_api as J
from agentdata.model import AgentTable
from agentdata.uat import sprint as SP
from tests.fakes import jira as FJ

STAMP = "2026-09-01T10:00:00.000+0000"


# ------------------------------------------------------------------------------------------ wiring
@pytest.fixture()
def out_dir(tmp_path, monkeypatch):
    """`.agent/out` for this test: where the TSV, the JSON and the cache all land."""
    d = str(tmp_path / "out")
    monkeypatch.setattr(M, "OUT_DIR", d)
    return d


@pytest.fixture()
def wire(monkeypatch):
    """Point `ad-jira` at a fake instance, leaving `_client` itself (budget, log, flavor memo) real."""
    def _wire(fake: FJ.FakeJira, stamps: dict | None = None):
        _give_updated(fake, stamps or {})

        def detect(creds, cfg=None, redetect=False, **kw):
            return fake.client(**kw), {"displayName": "Luna Fake"}

        monkeypatch.setattr(J, "load_credentials",
                            lambda cfg=None: J.Creds(fake.base_url, FJ.FAKE_EMAIL, FJ.FAKE_TOKEN, "test"))
        monkeypatch.setattr(J, "detect_flavor", detect)
        return fake
    return _wire


def _give_updated(fake: FJ.FakeJira, stamps: dict) -> None:
    """Teach the fake's issues an `updated` field.

    Every real Jira returns one and the whole cache turns on it; the fake predates the cache and its corpus does
    not carry one. Patched here rather than in `tests/fakes/jira.py`, which another slice owns.
    """
    corpus = fake.corpus
    original = corpus.issue_json

    def issue_json(i, fields=None, base_url=""):
        js = original(i, fields, base_url)
        if fields is None or "updated" in fields:
            js["fields"]["updated"] = stamps.get(corpus.key(i), STAMP)
        return js

    object.__setattr__(corpus, "issue_json", issue_json)   # Corpus is a frozen dataclass


def run(argv, capsys) -> tuple[int, str, str]:
    rc = CLI.main(argv)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def meta_of(out: str) -> dict:
    """The meta block as a dict of strings -- enough to assert on without a TOON parser."""
    got = {}
    for line in out.splitlines():
        m = re.match(r"^  ([a-z_]+)(?:\[\d+\])?: ?(.*)$", line)
        if m and not got.get("__done"):
            got[m.group(1)] = m.group(2)
        if re.match(r"^\S+\[\d+\]", line):
            got["__done"] = "1"
    return got


def toon_str(v: str) -> str:
    """A TOON value that held a space comes back quoted, with any inner quote doubled."""
    return v[1:-1].replace('""', '"') if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def path_of(out: str) -> str:
    m = re.search(r"^  path: (.+)$", out, re.M)
    assert m, f"no path in meta:\n{out}"
    return m.group(1)


def file_rows(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        return sum(1 for _ in fh) - 1                 # the header is not a row


def cache_file(out_dir: str) -> str:
    from agentdata import jira_cache

    return os.path.join(out_dir, jira_cache.CACHE_DIR, jira_cache.DB_NAME)


# ------------------------------------------------------------------------------- output compatibility
def test_a_small_pull_renders_as_a_materialised_table_does(wire, out_dir, capsys):
    """The regression that guards every changelog test in the repository.

    Streaming decides *when* the file is written, never what is in it or how the result is rendered. A pull that
    fits the buffer must therefore produce the same meta, the same table and the same file bytes as the
    `AgentTable` the CLI used to build.
    """
    fake = wire(FJ.FakeJira(4, 3))
    rc, out, _ = run(["changelog", *fake.corpus.keys()], capsys)
    assert rc == 0

    rows = [r for i in range(4) for r in FJ.rows_of(fake, i)]
    expected = policy.render(AgentTable.from_records(rows, name="changelog",
                                                     source="ad-jira changelog RDSD-1 RDSD-2 RDSD-3 …",
                                                     fields=CLI.CHANGELOG_COLUMNS))
    scrub = lambda s: re.sub(r"(path|elapsed_s): .*", r"\1: <x>", s)
    assert scrub(out.strip()) == scrub(expected)
    with open(path_of(out), "rb") as fh:
        assert fh.read() == open(AgentTable.from_records(rows, name="changelog",
                                                         fields=CLI.CHANGELOG_COLUMNS).write_tsv(), "rb").read()


def test_the_file_is_sorted_by_the_key_list_not_by_a_final_sort(wire, out_dir, capsys):
    """The rows are written as they arrive, so the order has to come from somewhere else: the key list is sorted
    before the fetch and the iterator's per-key guarantee does the rest."""
    fake = wire(FJ.FakeJira(12, 3))
    rc, out, _ = run(["changelog", "RDSD-9", "RDSD-11", "RDSD-2", "RDSD-10"], capsys)
    assert rc == 0
    with open(path_of(out), encoding="utf-8") as fh:
        body = [ln.split("\t") for ln in fh.read().splitlines()[1:]]
    seen = [r[0] for r in body]
    assert seen == sorted(seen), "keys out of order"
    assert sorted(set(seen)) == ["RDSD-10", "RDSD-11", "RDSD-2", "RDSD-9"]
    for key in set(seen):
        pairs = [(r[2], int(r[1])) for r in body if r[0] == key]
        assert pairs == sorted(pairs), f"{key} is not ascending by (created_utc, changelog_id)"


def peak_of(fn) -> int:
    """Bytes the traced heap grew above its own baseline while `fn` ran."""
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        fn()
        return tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()


def test_a_large_pull_streams_and_stays_under_the_memory_ceiling(wire, out_dir, capsys):
    """500 issues x 200 histories: 100,000 rows through the process, and the peak is one chunk plus the buffer.

    `--bulk-issues 25` is not a thumb on the scale, it is the bound being measured: the client collects one
    chunk's histories before it can order them, so the chunk size *is* the memory knob, and 25 x 200 histories is
    what a deep-history pull should be asked for. The old code's peak was the whole result and no flag moved it.
    """
    wire(FJ.FakeJira(500, 200))
    box: list = []
    grew = peak_of(lambda: box.append(run(
        ["changelog", "--jql", "project = RDSD", "--bulk-issues", "25", "--quiet", "--no-cache"], capsys)))
    rc, out, _ = box[0]
    assert rc == 0
    assert file_rows(path_of(out)) == 100_000
    assert meta_of(out)["rows"] == "100000"
    assert grew < 20 * 1024 * 1024, f"peak grew {grew / 1e6:.1f} MB above baseline"


def test_the_cache_does_not_add_the_result_back_to_memory(wire, out_dir, capsys):
    """The same ceiling with the cache on. It holds one issue's rows at a time, not the pull's -- a cache that
    buffered what it was given would have undone the streaming it exists alongside. Smaller than the pull above
    only because `ChangelogCache.add_rows` commits per row, which costs seconds, not bytes."""
    wire(FJ.FakeJira(50, 100))
    box: list = []
    grew = peak_of(lambda: box.append(run(
        ["changelog", "--jql", "project = RDSD", "--bulk-issues", "10", "--quiet"], capsys)))
    rc, out, _ = box[0]
    assert rc == 0 and file_rows(path_of(out)) == 5_000
    assert grew < 20 * 1024 * 1024, f"peak grew {grew / 1e6:.1f} MB above baseline"


# ------------------------------------------------------------------------------------ partial results
def test_an_interrupt_keeps_the_pages_that_arrived(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(60, 40, faults=[("bulkfetch", 4, "interrupt")]))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "10"], capsys)
    assert rc == 1, "a partial result must not exit 0"
    m = meta_of(out)
    assert m["ok"] == "false" and m["partial"] == "true" and m["reason"] == "interrupted"
    assert m["issues_complete"] == "30", "three chunks of ten finished before the fourth was interrupted"
    assert int(m["rows_written"]) == file_rows(path_of(out)) == 30 * 40
    assert m["issues_incomplete_count"] == "30"
    assert toon_str(m["resume"]).startswith('ad-jira changelog --jql "project = RDSD"')
    assert path_of(out) in err and "resume: ad-jira changelog" in err
    assert not fake.unfired()


def test_a_small_partial_still_renders_through_the_buffer_and_names_its_file(wire, out_dir, capsys):
    """A pull that dies inside the buffer never opens the streaming writer, so it renders as the small table it
    is -- and the operator still gets the file, the counts and the resume command."""
    wire(FJ.FakeJira(6, 3, faults=[("bulkfetch", 2, "interrupt")]))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "2"], capsys)
    assert rc == 1
    m = meta_of(out)
    assert m["rule"] in ("4", "5"), "a six-row result is still an inline table"
    assert m["partial"] == "true" and m["rows_written"] == "6" and m["issues_complete"] == "2"
    assert file_rows(path_of(out)) == 6
    assert path_of(out) in err, "the stderr hint names the file it kept"
    assert not toon.validate(out), toon.validate(out)


def test_a_budget_exhaustion_is_a_partial_with_a_resume_hint(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(40, 20))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "5", "--max-requests", "8"], capsys)
    assert rc == 1
    m = meta_of(out)
    assert m["partial"] == "true" and m["reason"] == "budget"
    assert 0 < int(m["issues_complete"]) < 40
    assert int(m["issues_incomplete_count"]) == 40 - int(m["issues_complete"])
    resume = toon_str(m["resume"])
    assert "--bulk-issues 5" in resume, "the resume command carries the flags that shaped the fetch"
    assert "--max-requests" not in resume, "but never the ceiling that stopped it: that is a resume that cannot resume"
    assert "--max-requests" in toon_str(m["hint"]), "the client's own hint says what to raise, and reaches the meta"
    assert "--max-requests" in err
    assert fake.count("bulkfetch") + fake.count("/search") + fake.count("/field") == 8


def test_the_printed_resume_line_actually_finishes_the_pull(wire, out_dir, capsys):
    """`skills/jira-changelog/SKILL.md` tells Luna to run the printed line ONCE and log friction if it is still
    short. A resume that echoed `--max-requests 8` back needed six more runs to finish forty issues, so the
    first rerun logged friction against a pull that was working exactly as designed."""
    wire(FJ.FakeJira(40, 20))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "5", "--max-requests", "8"], capsys)
    assert rc == 1
    resume = shlex.split(toon_str(meta_of(out)["resume"]))
    assert resume[0] == "ad-jira"

    rc2, out2, _ = run(resume[1:], capsys)
    m2 = meta_of(out2)
    assert rc2 == 0 and "partial" not in m2, f"the resume line left the pull short again: {m2}"
    assert int(m2["cached"]) > 0, "and it resumed from the cache rather than starting over"


def test_an_http_error_before_the_first_row_is_an_error_not_a_partial(wire, out_dir, capsys):
    """There is nothing partial about a pull that never started: the operator wants the failure, not an empty
    file with a resume hint."""
    fake = wire(FJ.FakeJira(6, 3, faults=[("bulkfetch", "every", 400), ("issue/", "every", 403)]))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 1
    assert "partial" not in out and "error" in out


def test_the_dc_truncation_is_reported_as_a_partial(wire, out_dir, capsys):
    """Data Center without the paged endpoint answers `?expand=changelog` with a hundred of four hundred entries.
    The client refuses it structurally; the CLI turns that refusal into the same shape every other short result
    has."""
    fake = wire(FJ.FakeJira(3, 150, flavor="dc", paged_changelog=False, expand_cap=100))
    rc, out, err = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 1
    m = meta_of(out)
    assert m["partial"] == "true"
    assert toon_str(m["reason"]).startswith("expand=changelog truncated: 100 of 150")
    assert m["issues_complete"] == "0"


# --------------------------------------------------------------------------------------- the cache
def test_the_second_run_of_an_unchanged_jql_fetches_nothing(wire, out_dir, capsys):
    first = wire(FJ.FakeJira(30, 4))
    rc, out1, _ = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 0 and meta_of(out1)["fetched"] == "30"
    assert first.count("bulkfetch") > 0

    second = wire(FJ.FakeJira(30, 4))
    rc, out2, err = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 0
    m = meta_of(out2)
    assert (m["cached"], m["fetched"]) == ("30", "0")
    assert second.count("bulkfetch") == 0 and second.count("issue/") == 0, "not one changelog request"
    assert "30 issues from cache" in err
    assert open(path_of(out1), "rb").read() == open(path_of(out2), "rb").read()


def test_a_moved_updated_stamp_fetches_exactly_those_issues(wire, out_dir, capsys):
    wire(FJ.FakeJira(20, 4))
    run(["changelog", "--jql", "project = RDSD"], capsys)

    moved = {"RDSD-3": "2026-09-05T09:00:00.000+0000", "RDSD-7": "2026-09-05T09:00:00.000+0000",
             "RDSD-12": "2026-09-05T09:00:00.000+0000"}
    second = wire(FJ.FakeJira(20, 4), stamps=moved)
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "1"], capsys)
    assert rc == 0
    assert (meta_of(out)["cached"], meta_of(out)["fetched"]) == ("17", "3")
    asked = [r.body["issueIdsOrKeys"] for r in second.matching("bulkfetch")]
    assert asked == [["RDSD-12"], ["RDSD-3"], ["RDSD-7"]], "one call each, in the sorted key order"
    assert file_rows(path_of(out)) == 20 * 4, "the other seventeen still came out, from the cache"


def test_refresh_refetches_everything(wire, out_dir, capsys):
    wire(FJ.FakeJira(12, 3))
    run(["changelog", "--jql", "project = RDSD"], capsys)
    again = wire(FJ.FakeJira(12, 3))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--refresh"], capsys)
    assert rc == 0 and (meta_of(out)["cached"], meta_of(out)["fetched"]) == ("0", "12")
    assert again.count("bulkfetch") > 0


def test_no_cache_neither_reads_nor_writes(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(8, 3))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--no-cache"], capsys)
    assert rc == 0
    assert not os.path.exists(cache_file(out_dir)), "the cache file must not exist after --no-cache"
    assert "cached" not in meta_of(out)
    again = wire(FJ.FakeJira(8, 3))
    run(["changelog", "--jql", "project = RDSD", "--no-cache"], capsys)
    assert again.count("bulkfetch") > 0, "and nothing was read back either"


def test_since_filters_the_output_and_never_the_cache(wire, out_dir, capsys):
    """`--since` is a client-side filter over rows the cache was already given in full. If it reached the cache,
    the next unfiltered run would be served a fragment as the whole history -- the one way a cache turns a cheap
    run into a wrong answer."""
    fake = wire(FJ.FakeJira(10, 6))
    cut = sorted(r["created_utc"] for r in FJ.rows_of(fake, 0))[3]
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--since", cut], capsys)
    assert rc == 0
    filtered = file_rows(path_of(out))
    assert 0 < filtered < 60

    second = wire(FJ.FakeJira(10, 6))
    rc, out2, _ = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 0 and second.count("bulkfetch") == 0
    assert file_rows(path_of(out2)) == 60, "the cache holds the unfiltered history"


def test_fields_turns_the_cache_off_rather_than_storing_half_a_history(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(6, 4))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--fields", "status"], capsys)
    assert rc == 0
    assert "cache off" in err
    assert not os.path.exists(cache_file(out_dir))


def test_an_interrupted_run_resumes_by_being_rerun(wire, out_dir, capsys):
    """The cache is the checkpoint, so the resume hint is just the same command."""
    wire(FJ.FakeJira(50, 10, faults=[("bulkfetch", 3, "interrupt")]))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "10"], capsys)
    assert rc == 1 and meta_of(out)["issues_complete"] == "20"

    rest = wire(FJ.FakeJira(50, 10))
    rc, out2, _ = run(shlex.split(toon_str(meta_of(out)["resume"]))[1:], capsys)
    assert rc == 0
    m = meta_of(out2)
    assert (m["cached"], m["fetched"], m["resumed"]) == ("20", "30", "true")
    assert file_rows(path_of(out2)) == 500


def test_explicit_keys_are_fetched_and_never_cached(wire, out_dir, capsys):
    """No `--jql` means no search, so no issue has an `updated` stamp: there is nothing the cache could decide
    with, and it is not even opened."""
    wire(FJ.FakeJira(3, 2))
    rc, out, _ = run(["changelog", "RDSD-1", "RDSD-2"], capsys)
    assert rc == 0 and "cached" not in meta_of(out)
    assert not os.path.exists(cache_file(out_dir))


def test_cache_stats_and_clear_are_sub_verbs_of_ad_jira(wire, out_dir, capsys):
    wire(FJ.FakeJira(5, 3))
    run(["changelog", "--jql", "project = RDSD"], capsys)

    rc, out, _ = run(["cache"], capsys)
    assert rc == 0
    m = meta_of(out)
    assert m["ok"] == "true"
    assert "issues: 5" in out and "rows: 15" in out
    assert os.path.exists(cache_file(out_dir))

    rc, out, _ = run(["cache", "--clear"], capsys)
    assert rc == 0 and "cleared: true" in out
    assert not os.path.exists(cache_file(out_dir))


# ------------------------------------------------------------------------------ progress, stats, budget
def test_progress_goes_to_stderr_and_quiet_silences_it(wire, out_dir, capsys):
    wire(FJ.FakeJira(400, 4, seed=3))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "5"], capsys)
    assert rc == 0
    assert re.search(r"changelog: [\d,]+ issues, [\d,]+ rows, page [\d,]+, \d", err), err
    assert "issues," not in out, "progress must never reach stdout"

    wire(FJ.FakeJira(400, 4, seed=3))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "5", "--refresh", "--quiet"], capsys)
    assert rc == 0 and err == ""


def test_stats_prints_a_line_on_stderr_and_the_five_numbers_in_the_meta(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(6, 3))
    rc, out, err = run(["changelog", "--jql", "project = RDSD", "--stats"], capsys)
    assert rc == 0
    m = meta_of(out)
    assert set(("requests", "retries", "rate_limit_waits", "waited_seconds", "elapsed_seconds")) <= set(m)
    assert int(m["requests"]) == len(fake.requests)
    assert "request" in err and "rate-limit wait" in err


def test_config_supplies_the_budget_when_the_flag_does_not(wire, out_dir, capsys, monkeypatch):
    """`jira.budget.*` is how a tenant that needs 6,000 requests stops typing it every time; the flag still wins."""
    fake = wire(FJ.FakeJira(20, 5))
    cfg = C.load()
    C.put(cfg, "jira.budget.max_requests", 5)
    C.save(cfg)
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "2"], capsys)
    assert rc == 1 and meta_of(out)["reason"] == "budget"
    assert len(fake.requests) == 5

    again = wire(FJ.FakeJira(20, 5))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--refresh", "--max-requests", "2000"], capsys)
    assert rc == 0, "the flag overrides the config"


def test_bulk_flags_reach_the_request_and_a_shrink_is_reported(wire, out_dir, capsys):
    fake = wire(FJ.FakeJira(8, 10, faults=[("bulkfetch", 1, "timeout")]))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD", "--bulk-issues", "4", "--bulk-page", "100"], capsys)
    assert rc == 0
    bodies = [r.body for r in fake.matching("bulkfetch")]
    assert bodies[0]["maxResults"] == 100 and len(bodies[0]["issueIdsOrKeys"]) == 4
    assert meta_of(out)["bulk_page_final"] == "50", "a page that timed out halved, and the meta says where it landed"


def test_skipped_keys_are_a_partial_result_and_not_a_footnote(wire, out_dir, capsys):
    """A 400 that names a key the operator asked for drops that issue's WHOLE history.

    `_invalid_keys` only ever drops keys this run requested, so `skipped_keys` is never cosmetic: RDSD-2 exists,
    has two histories, and none of its rows are in the output. Reporting that under `ok: true` with a footnote
    is the short-history-that-looks-complete this epic exists to kill, so it ends like every other short result.
    """
    fake = wire(FJ.FakeJira(5, 2, faults=[("bulkfetch", 1, "400 invalid key RDSD-2")]))
    rc, out, err = run(["changelog", "--jql", "project = RDSD"], capsys)
    m = meta_of(out)
    assert rc == 1 and m["ok"] == "false" and m["partial"] == "true"
    assert m["reason"] == "keys rejected by bulkfetch"
    assert "RDSD-2" in m["skipped_keys"] and "RDSD-2" in m["issues_incomplete"]
    assert "RDSD-2" in toon_str(m["hint"]) and "--no-bulk" in toon_str(m["hint"])
    assert file_rows(path_of(out)) == 8 == int(m["rows_written"]), "the four good issues are still kept"
    assert fake.count("issue/") == 0, "a named bad key is dropped, not paid for with a per-issue fallback"


def test_one_truncated_history_costs_that_issue_and_not_the_ones_after_it(wire, out_dir, capsys):
    """The Data Center refusal used to abort the pull at the first issue it hit, permanently.

    `_expand_rows` raised, nothing between it and the row loop caught it, and every later issue in the JQL was
    never requested -- so the file had zero rows, the cache had zero issues, and "rerunning IS the resume" could
    not make progress no matter how often it ran. Here only RDSD-2 lacks the paged endpoint; the other four
    histories are whole, are on disk, and are in the cache for the rerun.
    """
    fake = wire(FJ.FakeJira(5, 200, flavor="dc", expand_cap=100,
                            faults=[("RDSD-2/changelog", "every", 404)]))
    rc, out, err = run(["changelog", "--jql", "project = RDSD"], capsys)
    m = meta_of(out)
    assert rc == 1 and m["partial"] == "true"
    assert toon_str(m["reason"]) == "expand=changelog truncated: 100 of 200"
    assert m["issues_complete"] == "4" and m["issues_incomplete"] == "RDSD-2"
    assert m["truncated_keys"] == "RDSD-2"
    assert int(m["rows_written"]) == file_rows(path_of(out)) == 4 * 200
    assert "RDSD-2" not in open(path_of(out), encoding="utf-8").read(), \
        "not one row of a knowingly short history reaches the file"
    assert fake.unfired() == []

    again = wire(FJ.FakeJira(5, 200, flavor="dc", expand_cap=100,
                             faults=[("RDSD-2/changelog", "every", 404)]))
    rc2, out2, _ = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc2 == 1, "RDSD-2 is still short, so the run is still partial"
    assert meta_of(out2)["cached"] == "4", "and the four whole histories were not fetched twice"
    assert again.count("RDSD-2") == 2, "and only RDSD-2 was asked for again: the paged 404 and the expand"
    assert [k for k in again.corpus.keys() if k != "RDSD-2" and again.count("issue/" + k)] == []


def _flaky_reads(monkeypatch, fail_on: int):
    """Break the Nth `rows_for` SELECT, the way a network drive does mid-run."""
    import sqlite3

    from agentdata import jira_cache as CACHE

    original = CACHE.ChangelogCache._db
    left = [fail_on]

    class _Flaky:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, *args):
            if 'FROM "row" WHERE key' in sql:
                left[0] -= 1
                if left[0] == 0:
                    raise sqlite3.OperationalError("disk I/O error")
            return self._conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def _db(self):
        conn = original(self)
        return None if conn is None else _Flaky(conn)

    monkeypatch.setattr(CACHE.ChangelogCache, "_db", _db)


def test_a_cache_read_that_breaks_mid_run_is_a_partial_and_not_a_short_history(wire, out_dir, capsys, monkeypatch):
    """The cache disabling itself half way through a walk of cached issues.

    `rows_for` used to `return` there, so the issue being read and every cached issue after it yielded nothing --
    and the caller counted each one complete. Ten cached issues came back as six histories under `ok: true`, no
    `partial`, no `error`: a `committed_points` computed from that looks exactly like a real number. It is the
    failure this whole epic exists to kill, arriving through the one door built to prevent it.
    """
    wire(FJ.FakeJira(10, 3))
    rc, out, _ = run(["changelog", "--jql", "project = RDSD"], capsys)
    assert rc == 0 and file_rows(path_of(out)) == 30

    again = wire(FJ.FakeJira(10, 3))
    _flaky_reads(monkeypatch, fail_on=3)
    rc2, out2, err = run(["changelog", "--jql", "project = RDSD"], capsys)
    m = meta_of(out2)
    assert rc2 == 1, "a cache that stopped answering must not exit 0"
    assert m["ok"] == "false" and m["partial"] == "true" and m["reason"] == "cache read failed"
    assert int(m["issues_complete"]) < 10 and int(m["issues_incomplete_count"]) > 0
    assert "cache --clear" in toon_str(m["hint"])
    assert "cache unusable" in err or "cache read failed" in err
    assert again.count("bulkfetch") == 0, "the failure is the cache's, and it is reported rather than papered over"


# ------------------------------------------------------------------------------------- sprint-replay
def pinned(cfg=None):
    cfg = cfg if cfg is not None else C.load()
    C.put(cfg, "jira.fields.sprint", FJ.SPRINT_FIELD)
    C.put(cfg, "jira.fields.story_points", [FJ.POINTS_FIELD, FJ.POINTS_ESTIMATE_FIELD])
    C.save(cfg)


def test_sprint_replay_refuses_a_partial_history(wire, out_dir, capsys):
    wire(FJ.FakeJira(40, 10, faults=[("bulkfetch", 3, "interrupt")]))
    pinned()
    rc, out, err = run(["sprint-replay", "--sprint", "41", "--bulk-issues", "10"], capsys)
    assert rc == 2, "a replay over a short history is a refusal, not a smaller answer"
    m = meta_of(out)
    assert m["ok"] == "false" and m["partial"] == "true" and m["reason"] == "interrupted"
    assert "--allow-partial" in m["hint"] and "ad-jira sprint-replay --sprint 41" in m["hint"]
    assert "summary" not in out and "committed_points" not in out
    assert "refused" in err
    assert not toon.validate(out), toon.validate(out)


def test_sprint_replay_computes_and_says_so_with_allow_partial(wire, out_dir, capsys):
    wire(FJ.FakeJira(40, 10, faults=[("bulkfetch", 3, "interrupt")]))
    pinned()
    rc, out, err = run(["sprint-replay", "--sprint", "41", "--bulk-issues", "10", "--allow-partial"], capsys)
    assert rc == 0
    assert "committed_points" in out
    assert "  partial: true" in out and "issues_incomplete" in out
    assert re.search(r"issues_incomplete_count: \d+", out)
    assert "partial changelog" in err


def test_sprint_replay_second_run_costs_one_search(wire, out_dir, capsys):
    wire(FJ.FakeJira(24, 6))
    pinned()
    rc, out, _ = run(["sprint-replay", "--sprint", "41"], capsys)
    assert rc == 0

    again = wire(FJ.FakeJira(24, 6))
    pinned()
    rc, out2, _ = run(["sprint-replay", "--sprint", "41"], capsys)
    assert rc == 0
    assert again.count("bulkfetch") == 0 and again.count("changelog") == 0
    assert meta_of(out2)["cached"] == str(len(again.corpus.keys())), "every issue served from the cache"


def test_the_replay_assembles_each_issue_from_its_own_rows_only(wire, out_dir, capsys, monkeypatch):
    """FETCH used to build a flat list of every row of every history and hand that same list to
    `build_issue_state` once per issue, which rescanned all of it to find the rows of one -- quadratic in issues,
    on top of holding the whole pull in memory that the streaming slice exists to avoid. The replay reads four
    fields; it is given those four fields, bucketed by the issue that owns them."""
    seen: list[int] = []
    original = SP.build_issue_state

    def spy(issue, rows, sprint_field, points_fields):
        rows = list(rows)
        seen.append(len(rows))
        assert all(r.get("key") == issue.get("key") for r in rows), "another issue's rows reached this one"
        return original(issue, rows, sprint_field, points_fields)

    monkeypatch.setattr(SP, "build_issue_state", spy)
    wire(FJ.FakeJira(20, 20))
    pinned()
    rc, out, _ = run(["sprint-replay", "--sprint", "41"], capsys)
    assert rc == 0 and "committed_points" in out
    assert len(seen) == 20
    assert max(seen) <= 20, "one issue's histories, not the pull's 400 rows"


def test_sprint_replay_numbers_are_unchanged_by_the_cache(wire, out_dir, capsys):
    """Epic #121 changed how rows are fetched, stored and reported -- never what a row means. The summary of a
    cached run and of a fetched one must be the same summary."""
    wire(FJ.FakeJira(24, 6))
    pinned()
    _, first, _ = run(["sprint-replay", "--sprint", "41"], capsys)
    wire(FJ.FakeJira(24, 6))
    _, second, _ = run(["sprint-replay", "--sprint", "41"], capsys)

    def summary(text):
        block = text.split("summary:", 1)[1]
        return [ln for ln in block.splitlines() if ln.startswith("  ")]
    assert summary(first) == summary(second)
