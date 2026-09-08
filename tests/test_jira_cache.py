"""What the changelog cache has to get right before it is allowed to save anyone a request.

Every test here is one of the ways a cache turns a cheap second run into a wrong answer: an issue whose `updated`
moved being served from the cache anyway, a history killed halfway through coming back as if it were whole, rows
returned in the order they happened to be inserted rather than the order the client guarantees, and a corrupt
file taking the whole pull down with it. The crash case runs in a real subprocess that is killed with `os._exit`
between pages, because an in-process `raise` proves nothing about what SQLite actually committed.
"""
from __future__ import annotations
import os
import sqlite3
import subprocess
import sys

import pytest

from agentdata import jira_cache as CACHE
from agentdata.connectors.jira_http import JiraPartialError
from agentdata.jira_cache import ChangelogCache

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row(key, cid, created, field="status", **kw):
    r = {"key": key, "changelog_id": cid, "created_utc": created, "author": "Luna",
         "field": field, "field_id": field, "field_type": "jira",
         "from_id": "1", "from_str": "To Do", "to_id": "3", "to_str": "In Progress"}
    r.update(kw)
    return r


def store(cache, key, rows, updated="2026-09-01T10:00:00.000+0000", issue_id="10001"):
    """One issue written the way the client writes it: begin, pages, finish."""
    cache.begin_issue(key, issue_id, updated)
    cache.add_rows(key, rows)
    cache.finish_issue(key)


@pytest.fixture
def cache(tmp_path):
    c = ChangelogCache.open(str(tmp_path / "out"))
    yield c
    c.close()


# ------------------------------------------------------------------ layout and round trip


def test_the_cache_is_one_file_under_the_projects_out_dir(tmp_path):
    c = ChangelogCache.open(str(tmp_path / ".agent" / "out"))
    assert CACHE.CACHE_DIR in c.path and os.path.exists(c.path)
    assert os.path.dirname(c.path).endswith(CACHE.CACHE_DIR)   # parents created, nothing else needed
    c.close()


def test_columns_match_the_cli(cache):
    """A cached row and a fetched row have to be the same row, so the two column lists must not drift."""
    from agentdata.cli_jira import CHANGELOG_COLUMNS
    assert list(CACHE.COLUMNS) == list(CHANGELOG_COLUMNS)


def test_round_trip_returns_exactly_what_was_stored(cache):
    rows = [row("RDSD-1", 101, "2026-08-01T09:00:00Z"), row("RDSD-1", 102, "2026-08-02T09:00:00Z", field="Sprint")]
    store(cache, "RDSD-1", rows)
    assert list(cache.rows_for("RDSD-1")) == rows


def test_a_key_never_stored_yields_nothing(cache):
    assert list(cache.rows_for("RDSD-404")) == []


def test_the_cache_survives_being_closed_and_reopened(tmp_path):
    out = str(tmp_path / "out")
    c = ChangelogCache.open(out)
    store(c, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    c.close()
    again = ChangelogCache.open(out)
    assert again.partition({"RDSD-1": "U1"}) == (["RDSD-1"], [])
    assert len(list(again.rows_for("RDSD-1"))) == 1
    again.close()


# ------------------------------------------------------------------ ordering


def test_rows_come_back_in_the_guaranteed_order_whatever_the_insertion_order(cache):
    """Ascending (created_utc, changelog_id) -- and numerically, which is why the id column has no TEXT affinity:
    stored as text, 10 would sort before 9 and the replay would read a status change before the one it followed."""
    later = row("RDSD-7", 10, "2026-08-02T09:00:00Z")
    early = row("RDSD-7", 9, "2026-08-01T09:00:00Z")
    middle = row("RDSD-7", 2, "2026-08-02T08:00:00Z")
    cache.begin_issue("RDSD-7", "1", "U")
    cache.add_rows("RDSD-7", [later, early])        # pages arriving out of order
    cache.add_rows("RDSD-7", [middle])
    cache.finish_issue("RDSD-7")
    got = [(r["created_utc"], r["changelog_id"]) for r in cache.rows_for("RDSD-7")]
    assert got == [("2026-08-01T09:00:00Z", 9), ("2026-08-02T08:00:00Z", 2), ("2026-08-02T09:00:00Z", 10)]


def test_items_of_one_history_entry_keep_their_order(cache):
    """One changelog entry that changed three fields is three rows with the same id and timestamp; the order the
    client emitted them in is the order that comes back."""
    rows = [row("RDSD-8", 5, "2026-08-01T09:00:00Z", field=f) for f in ("status", "assignee", "Sprint")]
    store(cache, "RDSD-8", rows)
    assert [r["field"] for r in cache.rows_for("RDSD-8")] == ["status", "assignee", "Sprint"]


# ------------------------------------------------------------------ partition


def test_partition_splits_fresh_stale_and_new_keeping_the_callers_order(cache):
    store(cache, "A-1", [row("A-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    store(cache, "A-2", [row("A-2", 1, "2026-08-01T09:00:00Z")], updated="U2")
    store(cache, "A-3", [row("A-3", 1, "2026-08-01T09:00:00Z")], updated="U3")
    asked = {"A-3": "U3", "A-2": "MOVED", "A-9": "U9", "A-1": "U1"}   # fresh, stale, new, fresh
    fresh, stale = cache.partition(asked)
    assert fresh == ["A-3", "A-1"]                                    # the caller's order, not the table's
    assert stale == ["A-2", "A-9"]


def test_a_moved_updated_stamp_forces_a_refetch_and_replaces_the_rows(cache):
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    assert cache.partition({"RDSD-1": "U2"}) == ([], ["RDSD-1"])
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z"),
                            row("RDSD-1", 2, "2026-08-03T09:00:00Z")], updated="U2")
    assert cache.partition({"RDSD-1": "U2"}) == (["RDSD-1"], [])
    assert [r["changelog_id"] for r in cache.rows_for("RDSD-1")] == [1, 2]   # replaced, not appended to


def test_equality_is_exact_no_timestamp_parsing(cache):
    """Two spellings of the same instant are still a refetch. Guessing that they are equal is how a cache starts
    serving a history that has since grown."""
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="2026-09-01T10:00:00.000+0000")
    assert cache.partition({"RDSD-1": "2026-09-01T10:00:00.000Z"}) == ([], ["RDSD-1"])


def test_an_issue_still_being_written_is_stale(cache):
    """complete=0 is the whole checkpoint mechanism: begun but not finished means refetch."""
    cache.begin_issue("RDSD-1", "1", "U1")
    cache.add_rows("RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")])
    assert cache.partition({"RDSD-1": "U1"}) == ([], ["RDSD-1"])
    cache.finish_issue("RDSD-1")
    assert cache.partition({"RDSD-1": "U1"}) == (["RDSD-1"], [])


def test_partition_of_nothing_is_two_empty_lists(cache):
    assert cache.partition({}) == ([], [])


def test_partition_handles_more_keys_than_sqlite_takes_parameters(cache):
    """A 3,000-issue JQL is the case this exists for; the IN clause has to be chunked."""
    for i in range(1200):
        store(cache, f"B-{i}", [row(f"B-{i}", i, "2026-08-01T09:00:00Z")], updated="U")
    asked = {f"B-{i}": ("U" if i % 2 == 0 else "MOVED") for i in range(1200)}
    fresh, stale = cache.partition(asked)
    assert len(fresh) == 600 and len(stale) == 600
    assert fresh[:2] == ["B-0", "B-2"] and stale[:2] == ["B-1", "B-3"]


# ------------------------------------------------------------------ crash safety


CRASH_SCRIPT = """
import os, sys
from agentdata.jira_cache import ChangelogCache
c = ChangelogCache.open(sys.argv[1])
c.begin_issue("RDSD-1", "10001", "U1")
c.add_rows("RDSD-1", [{"key": "RDSD-1", "changelog_id": 1, "created_utc": "2026-08-01T09:00:00Z"}])
c.add_rows("RDSD-1", [{"key": "RDSD-1", "changelog_id": 2, "created_utc": "2026-08-02T09:00:00Z"}])
os._exit(9)          # killed between pages, exactly like a lost connection or a ^C
"""


def test_a_process_killed_mid_issue_leaves_the_issue_incomplete_and_refetchable(tmp_path):
    out = str(tmp_path / "out")
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    p = subprocess.run([sys.executable, "-c", CRASH_SCRIPT, out], env=env, capture_output=True, text=True)
    assert p.returncode == 9, p.stderr

    c = ChangelogCache.open(out)
    assert c.partition({"RDSD-1": "U1"}) == ([], ["RDSD-1"])          # never mistaken for a whole history
    assert c.stats()["issues"] == 1                                   # the checkpoint survived the kill
    c.begin_issue("RDSD-1", "10001", "U1")                            # the refetch drops the half history
    assert list(c.rows_for("RDSD-1")) == []
    c.close()


def test_beginning_an_issue_again_never_leaves_the_old_rows_behind(cache):
    store(cache, "RDSD-1", [row("RDSD-1", i, "2026-08-01T09:00:00Z") for i in range(5)], updated="U1")
    cache.begin_issue("RDSD-1", "10001", "U2")
    assert list(cache.rows_for("RDSD-1")) == []
    assert cache.partition({"RDSD-1": "U1"}) == ([], ["RDSD-1"]) and cache.partition({"RDSD-1": "U2"}) == ([], ["RDSD-1"])


# ------------------------------------------------------------------ what is allowed on disk


def test_only_changelog_columns_are_stored_even_when_the_caller_hands_over_more(cache, tmp_path):
    """The schema is the guard, not the caller's discipline: a dict carrying a summary, a description or a token
    leaves those behind. This file sits in a repo an agent can read."""
    fat = row("RDSD-1", 1, "2026-08-01T09:00:00Z")
    fat.update({"summary": "PROD outage postmortem", "description": "long text",
                "token": "SHOULD-NEVER-BE-WRITTEN", "raw": {"fields": {}}})
    store(cache, "RDSD-1", [fat])
    got = list(cache.rows_for("RDSD-1"))
    assert list(got[0]) == list(CACHE.COLUMNS)
    blob = open(cache.path, "rb").read()
    for secret in (b"SHOULD-NEVER-BE-WRITTEN", b"postmortem", b"long text"):
        assert secret not in blob


# ------------------------------------------------------------------ stats and clear


def test_stats_counts_issues_rows_bytes_and_the_oldest_fetch(cache):
    cache.begin_issue("A-1", "1", "U1", now="2026-08-01T00:00:00Z")
    cache.add_rows("A-1", [row("A-1", 1, "2026-08-01T09:00:00Z"), row("A-1", 2, "2026-08-02T09:00:00Z")])
    cache.finish_issue("A-1")
    cache.begin_issue("A-2", "2", "U2", now="2026-09-01T00:00:00Z")
    cache.add_rows("A-2", [row("A-2", 1, "2026-08-01T09:00:00Z")])
    cache.finish_issue("A-2")
    s = cache.stats()
    assert s == {"path": cache.path, "issues": 2, "rows": 3, "bytes": s["bytes"],
                 "oldest_fetched_at": "2026-08-01T00:00:00Z"}
    assert s["bytes"] > 0


def test_stats_of_an_empty_cache_is_zeros(cache):
    s = cache.stats()
    assert (s["issues"], s["rows"], s["oldest_fetched_at"]) == (0, 0, None) and s["bytes"] > 0


def test_clear_removes_the_file_and_the_cache_still_works_afterwards(cache):
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    path = cache.path
    cache.clear()
    assert not os.path.exists(path)
    assert cache.partition({"RDSD-1": "U1"}) == ([], ["RDSD-1"])      # a cleared cache is empty, not dead
    assert cache.stats()["issues"] == 0
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    assert cache.partition({"RDSD-1": "U1"}) == (["RDSD-1"], [])


def test_clear_on_a_cache_that_was_never_written_is_not_an_error(tmp_path):
    c = ChangelogCache.open(str(tmp_path / "out"))
    c.clear()
    c.clear()
    assert not os.path.exists(c.path)


# ------------------------------------------------------------------ a broken cache never breaks a pull


def _corrupt(tmp_path):
    out = tmp_path / "out"
    (out / CACHE.CACHE_DIR).mkdir(parents=True)
    (out / CACHE.CACHE_DIR / CACHE.DB_NAME).write_bytes(b"this is not a database, it is half a file\n" * 40)
    return str(out)


def test_a_read_that_fails_after_the_cache_answered_raises_instead_of_going_quiet(cache, monkeypatch):
    """The one failure a cache must never absorb.

    `partition()` has already told the caller these issues are complete and need no request. If a read then dies
    -- a network drive, a `disk I/O error` on the third of ten issues -- returning nothing is not "no cache", it
    is a history with rows missing that the caller writes to the output file and counts as complete. Every
    cached issue after it would go the same way. So it raises, and the pull reports `partial` and keeps what it
    has; the caller\'s hint names `ad-jira cache --clear`.
    """
    store(cache, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    assert len(list(cache.rows_for("RDSD-1"))) == 1

    monkeypatch.setattr(cache, "_db", lambda: _Flaky(cache._conn))
    with pytest.raises(JiraPartialError) as ei:
        list(cache.rows_for("RDSD-1"))
    assert ei.value.reason == "cache read failed" and ei.value.key == "RDSD-1"
    assert "ad-jira cache --clear" in ei.value.hint
    assert cache.disabled, "and the cache takes itself out of the run"


class _Flaky:
    """The connection a network drive hands back: it answers everything until it answers nothing."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if 'FROM "row"' in sql:
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_a_corrupt_file_degrades_with_a_hint_instead_of_crashing_the_pull(tmp_path):
    c = ChangelogCache.open(_corrupt(tmp_path))
    assert c.disabled and "ad-jira cache --clear" in c.hint
    assert c.path in c.error
    # Every operation still answers, and the answer is always "fetch it".
    assert c.partition({"RDSD-1": "U1", "RDSD-2": "U2"}) == ([], ["RDSD-1", "RDSD-2"])
    c.begin_issue("RDSD-1", "1", "U1")
    c.add_rows("RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")])
    c.finish_issue("RDSD-1")
    assert list(c.rows_for("RDSD-1")) == []
    c.close()


def test_stats_of_a_corrupt_cache_says_so(tmp_path):
    c = ChangelogCache.open(_corrupt(tmp_path))
    s = c.stats()
    assert s["issues"] == 0 and s["bytes"] > 0
    assert "ad-jira cache --clear" in s["hint"] and s["error"]


def test_clearing_a_corrupt_cache_is_how_a_human_recovers(tmp_path):
    out = _corrupt(tmp_path)
    c = ChangelogCache.open(out)
    assert c.disabled
    c.clear()
    assert not os.path.exists(c.path) and not c.disabled
    store(c, "RDSD-1", [row("RDSD-1", 1, "2026-08-01T09:00:00Z")], updated="U1")
    assert c.partition({"RDSD-1": "U1"}) == (["RDSD-1"], [])
    c.close()


def test_an_unusable_directory_disables_the_cache_rather_than_raising(tmp_path):
    """`.agent/out/.jira-changelog-cache` cannot be created when a file of that name is in the way -- a run must
    still fetch its data."""
    out = tmp_path / "out"
    out.mkdir()
    (out / CACHE.CACHE_DIR).write_text("not a directory")
    c = ChangelogCache.open(str(out))
    assert c.disabled and c.hint
    assert c.partition({"RDSD-1": "U1"}) == ([], ["RDSD-1"])


def test_the_cache_error_carries_a_hint():
    e = CACHE.CacheError("boom")
    assert isinstance(e, CACHE.JiraError) and "ad-jira cache --clear" in e.hint
