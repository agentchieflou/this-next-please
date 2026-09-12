"""The session index: folds events.norm.jsonl into sessions.json.

A session is a thing with an id, a title, a ticket, and an ending.
The index is a fold of history -- rebuildable from disk, never the source of truth.
"""
from __future__ import annotations
import json
import os
import shutil
import sqlite3
import tempfile
import time
from typing import Any

from .. import textio
from . import agentstate, events as E
from .registry import agent_dir, fleet_dir


def store_path() -> str:
    """Location of Copilot's own session store."""
    return os.environ.get("COPILOT_SESSION_STORE") or os.path.expanduser("~/.copilot/session-store.db")


# ------------------------------------------------------------- Copilot's own session files (#188)
#
# Copilot writes every session -- interactive or `-p` -- to `~/.copilot/session-state/<id>/events.jsonl`
# as it runs, in the catalogue `events.from_copilot` folds. A console session the fleet did not pipe
# is read from there. Read-only by construction: nothing in this block opens a file for writing,
# makes a directory or removes one, and `tests/test_fleet_console.py` reads this source to say so.


def session_state_dir() -> str:
    """Where Copilot keeps one directory per session. `COPILOT_SESSION_STATE` overrides it, the way
    `COPILOT_SESSION_STORE` overrides the store, so a test never reads a real home."""
    return os.environ.get("COPILOT_SESSION_STATE") or os.path.expanduser("~/.copilot/session-state")


def session_state_path(session_id: str) -> str:
    """The events log of one session, or "" for no id. The id is one path segment: a value read
    out of a lock or a store row never becomes a path that leaves the directory."""
    sid = os.path.basename(str(session_id or "").strip())
    if not sid or sid in (".", ".."):
        return ""
    return os.path.join(session_state_dir(), sid, "events.jsonl")


def _workspace_cwd(session_dir: str) -> str:
    """The working directory a session's `workspace.yaml` names, or "". One line of YAML is read as
    text -- no YAML library, and nothing else in the file is trusted: `cwd:` or `working_directory:`,
    quoted or not, is the whole contract, and runbook row S1 says which key the real file uses."""
    path = os.path.join(session_dir, "workspace.yaml")
    try:
        text = textio.read_text(path)
    except (OSError, ValueError):
        return ""
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("cwd", "working_directory", "workingDirectory"):
            return value.strip().strip("'\"")
    return ""


def session_files(repo_path: str) -> list[dict]:
    """Copilot's sessions whose working directory is this checkout, newest log first (#192).

    Two places can say where a session ran, and both are taken: `workspace.yaml` beside the log,
    and the store's `cwd` column where the schema has one (`read_store_sessions` already matches
    on it). Each row says which it used -- `how: "workspace"` or `"store"` -- because S1 decides
    which the real machine carries and the runbook records it. Read-only, like everything here.
    """
    want = textio.norm_path(repo_path).lower().rstrip("/")
    found: dict[str, dict] = {}
    root = session_state_dir()
    try:
        names = os.listdir(root)
    except OSError:
        names = []
    for sid in names:
        d = os.path.join(root, sid)
        if not os.path.isdir(d):
            continue
        cwd = _workspace_cwd(d)
        if cwd and textio.norm_path(cwd).lower().rstrip("/") == want:
            found[sid] = {"id": sid, "how": "workspace"}
    for row in read_store_sessions(repo_path):
        sid = str(row.get("id") or "")
        if sid and sid not in found and os.path.isdir(os.path.join(root, os.path.basename(sid))):
            found[sid] = {"id": sid, "how": "store"}
    out = []
    for sid, row in found.items():
        file = session_state_path(sid)
        try:
            mtime = os.path.getmtime(file)
        except OSError:
            mtime = 0.0
        out.append({**row, "file": file, "log_mtime": mtime,
                    "log_age_s": (time.time() - mtime) if mtime else -1.0})
    out.sort(key=lambda r: -r["log_mtime"])
    return out


def store_status() -> tuple[str, str, str]:
    """Check whether Copilot's session store is present and readable.

    Returns:
        (status, message, hint) where status is 'ok', 'warn', or 'skip'.
    """
    path = store_path()
    if not os.path.isfile(path):
        return "skip", "none", "Copilot session store (~/.copilot/session-store.db) not found"
    try:
        conn = _connect_ro(path)
        try:
            cur = conn.execute("SELECT count(*) FROM sessions")
            row = cur.fetchone()
            count = int(row[0]) if row else 0
            return "ok", f"{count} session(s)", ""
        finally:
            conn.close()
    except Exception as e:
        return "warn", "not readable", f"could not read {path}: {e}"


def _connect_ro(path: str) -> sqlite3.Connection:
    """Connect read-only to a SQLite database, falling back to a temp copy if locked."""
    try:
        norm = textio.norm_path(os.path.abspath(path))
        uri = f"file:{norm}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        # Locked or inaccessible via URI; copy-on-read fallback
        tmp = tempfile.NamedTemporaryFile(prefix="copilot_store_", suffix=".db", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            shutil.copy2(path, tmp_path)
            conn = sqlite3.connect(tmp_path, timeout=1.0)
            conn.execute("PRAGMA query_only = ON")
            return conn
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise


def read_store_sessions(repo_path: str = "", *, repo_name: str = "",
                        jira_project: str = "") -> list[dict]:
    """Read sessions belonging to a repository from Copilot's store.

    Read-only; never writes to the store.
    """
    path = store_path()
    if not os.path.isfile(path):
        return []
    try:
        conn = _connect_ro(path)
    except Exception:
        return []

    out = []
    norm_repo = textio.norm_path(os.path.abspath(repo_path)).rstrip("/\\").lower() if repo_path else ""
    try:
        cur = conn.cursor()
        # Verify schema carries required columns
        cols = [col[1] for col in cur.execute("PRAGMA table_info(sessions)").fetchall()]
        if "id" not in cols:
            return []
        select_cols = ["id", "summary", "created_at", "updated_at"]
        has_cwd = "cwd" in cols
        has_repo = "repository" in cols
        if has_cwd:
            select_cols.append("cwd")
        if has_repo:
            select_cols.append("repository")

        query = f"SELECT {', '.join(select_cols)} FROM sessions ORDER BY updated_at DESC"
        cur.execute(query)
        for row in cur.fetchall():
            rec = dict(zip(select_cols, row))
            sid = rec.get("id") or ""
            if not sid:
                continue
            cwd = textio.norm_path(rec.get("cwd") or "").rstrip("/\\").lower() if has_cwd else ""
            repository = str(rec.get("repository") or "") if has_repo else ""

            matched = False
            if norm_repo and cwd and cwd == norm_repo:
                matched = True
            elif repository and (repository.lower() == repo_name.lower() or
                                 (jira_project and repository.lower() == jira_project.lower())):
                matched = True

            if matched:
                out.append({
                    "id": sid,
                    "title": rec.get("summary") or "(console) copilot in this checkout",
                    "ticket": "",
                    "first_seen": rec.get("created_at") or "",
                    "last_seen": rec.get("updated_at") or "",
                    "runs": 1,
                    "ended": "",
                    "cost": 0.0,
                    "source": "store",
                })
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def sessions_path(name: str) -> str:
    """Path to sessions.json for an agent."""
    return os.path.join(agent_dir(name), "sessions.json")


def load_sessions(name: str) -> list[dict]:
    """Load the sessions list for an agent."""
    p = sessions_path(name)
    if not os.path.isfile(p):
        return []
    try:
        data = json.loads(textio.read_text(p))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_sessions(name: str, sessions: list[dict]) -> None:
    """Save the sessions list deterministically."""
    p = sessions_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    text = json.dumps(sessions, indent=2, ensure_ascii=False) + "\n"
    textio.write_text(p, text)


def fold_stream(stream: list[dict], existing_titles: dict[str, str] | None = None) -> list[dict]:
    """Fold a normalized event stream into session records.

    A session starts when an id is seen (via session_id or started.data.session).
    Cost is the high-water mark (maximum), never a sum.
    """
    titles = existing_titles or {}
    sessions_by_id: dict[str, dict] = {}
    order: list[str] = []

    # Break stream into runs at each 'started' event
    started_indices = [i for i, ev in enumerate(stream) if ev.get("kind") == "started"]
    if not started_indices and stream:
        runs = [stream]
    else:
        runs = []
        for idx, start_i in enumerate(started_indices):
            end_i = started_indices[idx + 1] if idx + 1 < len(started_indices) else len(stream)
            runs.append(stream[start_i:end_i])

    for run_events in runs:
        if not run_events:
            continue
        first_ev = run_events[0]
        start_data = first_ev.get("data") or {}

        # Look for session_id in this run
        sid = ""
        for ev in run_events:
            if ev.get("kind") == "session_id":
                sid = (ev.get("data") or {}).get("session", "")
                if sid:
                    break
        if not sid:
            sid = start_data.get("session", "")

        if not sid:
            # A run that died before emitting a session_id
            continue

        ticket = first_ev.get("ticket") or ""
        summary = start_data.get("summary") or ""
        is_adopted = bool(start_data.get("adopted") or start_data.get("external"))
        # Which surface held the session when the run began (#191): a console the fleet opened, a
        # session adopted from outside, or the fleet's own headless process.
        source = "console" if start_data.get("console") else ("adopted" if is_adopted else "fleet")

        # Derive state of this run
        derived = agentstate.derive(run_events, live=False)
        ended_state = derived.get("state") or "done"
        if not ticket:
            ticket = derived.get("ticket") or ""

        run_cost = float(derived.get("premium_requests") or 0.0)
        # Also check cost events directly
        for ev in run_events:
            if ev.get("kind") == "cost":
                c = float((ev.get("data") or {}).get("premium_requests") or 0.0)
                if c > run_cost:
                    run_cost = c

        first_ts = run_events[0].get("ts", "")
        last_ts = run_events[-1].get("ts", "") or first_ts

        if sid not in sessions_by_id:
            title = titles.get(sid) or (f"{ticket} {summary}".strip() if summary else ticket)
            sessions_by_id[sid] = {
                "id": sid,
                "title": title,
                "ticket": ticket,
                "first_seen": first_ts,
                "last_seen": last_ts,
                "runs": 1,
                "ended": ended_state,
                "cost": run_cost,
                "source": source,
                # Every surface this session has been held by, in the order it moved between them
                # (#191). `source` stays the first, because that is what it has always meant; the
                # list is how a session that began headless and was carried into a console -- or
                # the other way about -- says so without a second record of anything.
                "sources": [source],
            }
            order.append(sid)
        else:
            rec = sessions_by_id[sid]
            rec["runs"] += 1
            if source != (rec["sources"][-1] if rec["sources"] else ""):
                rec["sources"].append(source)
            if ticket and not rec["ticket"]:
                rec["ticket"] = ticket
            if last_ts > rec["last_seen"]:
                rec["last_seen"] = last_ts
                rec["ended"] = ended_state
            if run_cost > rec["cost"]:
                rec["cost"] = run_cost

    out = [sessions_by_id[sid] for sid in order]
    return out


def rebuild_sessions(name: str, repo_path: str = "") -> list[dict]:
    """Rebuild sessions.json from events.norm.jsonl, preserving custom titles."""
    existing = load_sessions(name)
    existing_titles = {s["id"]: s["title"] for s in existing if s.get("title")}

    stream = E.read(name)
    sessions = fold_stream(stream, existing_titles)

    # Incorporate store sessions if available
    if repo_path:
        store_sessions = read_store_sessions(repo_path, repo_name=name)
        seen_ids = {s["id"] for s in sessions}
        for ss in store_sessions:
            if ss["id"] not in seen_ids:
                sessions.append(ss)
                seen_ids.add(ss["id"])

    save_sessions(name, sessions)
    return sessions


def rename_session(name: str, session_id: str, title: str) -> dict:
    """Rename a session, preserving the title across future rebuilds."""
    sessions = load_sessions(name)
    found = None
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = title
            found = s
            break
    if not found:
        # If not found in current sessions.json, check if it can be created/rebuilt
        sessions = rebuild_sessions(name)
        for s in sessions:
            if s["id"] == session_id:
                s["title"] = title
                found = s
                break
    if not found:
        raise KeyError(f"session {session_id} not found for repo {name}")
    save_sessions(name, sessions)
    return found
