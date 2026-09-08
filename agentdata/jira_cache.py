"""The changelog cache: one SQLite file per project, keyed on each issue's `updated` stamp.

A remediation loop re-runs `ad-jira changelog --jql "project = RDSD AND ..."` after every fix, and today the
second run costs exactly what the first one did -- thousands of issues, every entry of every history, fetched
again to produce a byte-identical file. That is the request budget spent on work already done, against the
human's own token.

The fact that makes the cache safe is small and absolute: **an issue's changelog cannot change without its
`updated` stamp moving, because every history entry IS an edit.** Adding a comment, moving a status, editing a
field -- each writes a changelog entry and each bumps `updated`. So there is no expiry heuristic here, no
"is this probably still fresh", no TTL to tune: `search(jql, ["key", "updated"])` costs one paged call, and
equality on that string decides. Equal and complete means the stored history is the whole history.

Two failure modes shape the rest of the design.

*A half history that looks whole.* An interrupted pull used to leave nothing behind; the cache makes it leave
something, which is only an improvement if a partial issue can never be mistaken for a finished one. So an issue
is written in three steps -- `begin_issue()` deletes the old rows and marks the issue `complete=0` in ONE
transaction, `add_rows()` appends pages as they arrive, `finish_issue()` sets `complete=1` and the row count.
A crash anywhere in between leaves `complete=0`, and `partition()` calls that issue stale and refetches it. The
cache is therefore also the checkpoint: no separate resume file, and the resume hint is just the same command.

*Storing something that should not be on disk.* This file sits in a repository an agent can read, so it holds
changelog rows and nothing else -- no summaries, no descriptions, no field payloads, and above all no token or
credential. That is enforced by the schema (the `row` table has exactly the eleven CHANGELOG columns, and
`add_rows()` copies only those keys, so a caller that hands over a richer dict silently leaves the extras
behind) rather than by anyone remembering. Changelog rows already land in `.agent/out/*.tsv` today, so the
cache stores nothing that was not already written to disk.

Ordering matches the client's guarantee exactly -- rows come back ascending by `(created_utc, changelog_id)` --
so a cached issue and a freshly fetched one are indistinguishable in the output file.

Finally, a broken cache must never break a data pull. A corrupt or unreadable database (a killed process on a
network drive, a half-copied `.agent/`) leaves the cache `disabled` with a message and a hint naming
`ad-jira cache --clear`; every read then answers "not cached" and every write is a no-op, and the run fetches
everything, exactly as it did before this file existed. Stdlib `sqlite3`, no dependency, no async.
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterator

from .connectors.jira_http import JiraError

CACHE_DIR = ".jira-changelog-cache"
DB_NAME = "changelog.sqlite3"
# The CHANGELOG columns, in the order `cli_jira.CHANGELOG_COLUMNS` uses. A test asserts the two agree; if they
# ever drift, a cached row and a fetched row would not be the same row.
COLUMNS = ("key", "changelog_id", "created_utc", "author", "field", "field_id", "field_type",
           "from_id", "from_str", "to_id", "to_str")
CLEAR_HINT = "run `ad-jira cache --clear` to delete the cache, then rerun (the pull works without it)"

# `key` is TEXT because it is always an issue key. Every other column is declared without a type, so SQLite's
# BLOB affinity stores what it was given: a numeric changelog id stays an int and therefore sorts 9 before 10,
# where TEXT affinity would sort 10 before 9 and hand back a history in the wrong order.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS issue(
    key TEXT PRIMARY KEY,
    id TEXT,
    updated TEXT,
    fetched_at TEXT,
    complete INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS "row"(
    key TEXT NOT NULL,
    changelog_id, created_utc, author, field, field_id, field_type,
    from_id, from_str, to_id, to_str);
CREATE INDEX IF NOT EXISTS row_key ON "row"(key);
"""
_INSERT_ROW = 'INSERT INTO "row"(%s) VALUES(%s)' % (",".join(COLUMNS), ",".join("?" * len(COLUMNS)))


class CacheError(JiraError):
    """Raised only where a human asked the cache a direct question (`ad-jira cache --stats|--clear`) and it
    could not answer. A pull never sees this: it sees a disabled cache and fetches everything."""

    def __init__(self, msg: str, hint: str = CLEAR_HINT):
        super().__init__(msg, hint=hint)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bind(v):
    """SQLite stores None/int/float/str/bytes. Anything else is stringified rather than raising mid-pull."""
    return v if v is None or isinstance(v, (int, float, str, bytes)) else str(v)


class ChangelogCache:
    """Per-issue changelog storage. Open it with `ChangelogCache.open(out_dir)`; it is never constructed with a
    live connection, because the connection is opened lazily and dropped again by `clear()`."""

    def __init__(self, path: str):
        self.path = path.replace("\\", "/")
        self.disabled = False
        self.error = ""
        self.hint = ""
        self._conn: sqlite3.Connection | None = None

    # ---------- lifecycle ----------

    @classmethod
    def open(cls, out_dir: str) -> "ChangelogCache":
        """`out_dir` is the project's `.agent/out`; the cache is one file in `.jira-changelog-cache/` under it.
        Parents are created. A directory that cannot be created disables the cache instead of raising."""
        cache = cls(os.path.join(out_dir, CACHE_DIR, DB_NAME))
        cache._db()
        return cache

    def _db(self) -> sqlite3.Connection | None:
        """The connection, created on first use. Returns None once the cache is disabled."""
        if self.disabled:
            return None
        if self._conn is not None:
            return self._conn
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            conn = sqlite3.connect(self.path, isolation_level=None)   # explicit BEGIN, no implicit transaction
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.execute("SELECT count(*) FROM issue").fetchone()     # touches the file: a non-database raises here
        except (sqlite3.Error, OSError) as e:
            self._disable(e)
            return None
        self._conn = conn
        return conn

    def _disable(self, e: Exception) -> None:
        """One place where a broken cache stops being used. The message names the file so a human can delete it."""
        self.disabled = True
        self.error = f"changelog cache unusable ({type(e).__name__}: {e}); running without it: {self.path}"
        self.hint = CLEAR_HINT
        try:
            if self._conn is not None:
                self._conn.close()
        except sqlite3.Error:
            pass
        self._conn = None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None

    # ---------- the decision ----------

    def partition(self, updated_by_key: dict[str, str]) -> tuple[list[str], list[str]]:
        """Split the keys a search returned into (fresh, stale).

        Fresh means the cache holds that key, the issue is `complete=1`, and the stored `updated` equals the one
        the search just reported -- exact string equality, no parsing, because a stamp that differs in any way is
        a reason to refetch. Everything else is stale: new keys, incomplete keys, moved stamps.

        Both lists keep the caller's order. That matters beyond tidiness: the emitted rows are ordered by the key
        list, so a partition that reordered keys would reorder the output file.
        """
        keys = list(updated_by_key)
        known: dict[str, str] = {}
        conn = self._db()
        if conn is not None and keys:
            try:
                for i in range(0, len(keys), 500):     # SQLITE_MAX_VARIABLE_NUMBER is 999 on old builds
                    chunk = keys[i:i + 500]
                    q = "SELECT key, updated FROM issue WHERE complete = 1 AND key IN (%s)" % ",".join("?" * len(chunk))
                    for r in conn.execute(q, chunk):
                        known[r["key"]] = r["updated"]
            except sqlite3.Error as e:
                self._disable(e)
                known = {}
        fresh, stale = [], []
        for k in keys:
            (fresh if k in known and known[k] == updated_by_key[k] else stale).append(k)
        return fresh, stale

    # ---------- reading ----------

    def rows_for(self, key: str) -> Iterator[dict]:
        """The cached history of one issue, ascending by (created_utc, changelog_id) -- the same guarantee the
        client gives, with insertion order breaking ties so the items of one history entry stay together."""
        conn = self._db()
        if conn is None:
            return
        try:
            cur = conn.execute(
                'SELECT %s FROM "row" WHERE key = ? ORDER BY created_utc, changelog_id, rowid' % ",".join(COLUMNS),
                (key,))
            for r in cur:
                yield {c: r[c] for c in COLUMNS}
        except sqlite3.Error as e:
            self._disable(e)
            return

    # ---------- writing one issue ----------

    def begin_issue(self, key: str, issue_id, updated: str, now: str | None = None) -> None:
        """Start (or restart) one issue: drop whatever was stored for it and mark it incomplete, in ONE
        transaction. From here until `finish_issue()` the issue reads as stale, so a process killed mid-history
        loses nothing but the work it had not finished."""
        conn = self._db()
        if conn is None:
            return
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute('DELETE FROM "row" WHERE key = ?', (key,))
            conn.execute("INSERT OR REPLACE INTO issue(key, id, updated, fetched_at, complete, row_count) "
                         "VALUES(?,?,?,?,0,0)",
                         (key, None if issue_id is None else str(issue_id), updated, now or _now()))
            conn.execute("COMMIT")
        except sqlite3.Error as e:
            self._rollback(conn)
            self._disable(e)

    def add_rows(self, key: str, rows) -> None:
        """Append a page of changelog rows. Only the eleven CHANGELOG columns are read from each dict, and the
        key column is the `key` argument -- that is the guard that keeps a summary, a description or anything
        credential-shaped out of the file even if a caller hands one over."""
        conn = self._db()
        if conn is None:
            return
        payload = [tuple([key] + [_bind(r.get(c)) for c in COLUMNS[1:]]) for r in rows]
        if not payload:
            return
        try:
            conn.executemany(_INSERT_ROW, payload)
        except sqlite3.Error as e:
            self._disable(e)

    def finish_issue(self, key: str) -> None:
        """Mark the issue complete and record how many rows it holds. Counted from the table rather than tallied
        by the caller, so the number can never claim more than was stored."""
        conn = self._db()
        if conn is None:
            return
        try:
            n = conn.execute('SELECT count(*) FROM "row" WHERE key = ?', (key,)).fetchone()[0]
            conn.execute("UPDATE issue SET complete = 1, row_count = ? WHERE key = ?", (n, key))
        except sqlite3.Error as e:
            self._disable(e)

    def _rollback(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    # ---------- housekeeping ----------

    def stats(self) -> dict:
        """What `ad-jira cache --stats` prints. A disabled cache answers with zeros plus `error` and `hint`,
        because "the file is corrupt" is the answer to the question that was asked."""
        out = {"path": self.path, "issues": 0, "rows": 0, "bytes": self._bytes(), "oldest_fetched_at": None}
        conn = self._db()
        if conn is None:
            out["error"], out["hint"] = self.error, self.hint
            return out
        try:
            out["issues"] = conn.execute("SELECT count(*) FROM issue").fetchone()[0]
            out["rows"] = conn.execute('SELECT count(*) FROM "row"').fetchone()[0]
            out["oldest_fetched_at"] = conn.execute("SELECT min(fetched_at) FROM issue").fetchone()[0]
        except sqlite3.Error as e:
            self._disable(e)
            out["error"], out["hint"] = self.error, self.hint
        return out

    def _bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def clear(self) -> None:
        """Delete the cache file. The next operation recreates an empty one, so a cleared cache is usable rather
        than dead -- and clearing is also how a human recovers from a corrupt file, which is why this succeeds
        even when the database could never be opened."""
        self.close()
        failed: OSError | None = None
        for p in (self.path, self.path + "-journal", self.path + "-wal", self.path + "-shm"):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
            except OSError as e:
                failed = e
        if failed is not None:
            raise CacheError(f"could not delete the changelog cache: {failed}",
                             hint=f"delete {self.path} by hand, or close whatever is holding it open")
        self.disabled, self.error, self.hint = False, "", ""
