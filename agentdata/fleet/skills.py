"""The skills marketplace: every skill the operator has, and how each one has actually been used.

Two questions, two sources, one ledger.

**What is installed** (`installed`) is read from the disk each time it is asked: every folder with a
`SKILL.md` under every skills directory that exists (`update.SKILL_DIRS`, and the project's
`skills_dir` fact first). The same name in two directories is one skill shadowing another: the first
directory wins, as the CLI that reads them does, and the loser carries `shadowed_by`.

**How each is used** is folded from two kinds of transcript:

* the fleet's own agents: each agent's normalized stream (`events.norm.jsonl`) carries a `tool_call`
  with `tool: "skill"` and `arguments.skill` naming the skill, and a `tool_result` with the same `id`
  saying whether it worked (`events.from_copilot`);
* Copilot's own sessions outside the fleet: `~/.copilot/session-state/<id>/events.jsonl`, the raw
  file `sessions.py` already reads, with `workspace.yaml` naming the working directory the session
  ran in. A session the fleet piped or adopted is in both places, so a session whose id a fleet
  agent's index names (`sessions.load_sessions`, the lock, or a `session_id` event the fold has
  seen) is counted once, as the fleet's. Any other session is counted under the source `copilot`,
  and its repository is the working directory's basename.

Both fold into one file, `<fleet dir>/skills.json`, because the streams rotate (`lifecycle.rotate_all`
at `fleet.log_mb`) and a count that lived only in the live file would forget the morning the way
spend did before #210. The ledger is `spend.py`'s shape and discipline: a cursor per agent, written
atomically, folded on every `events.refresh` and before every roll, and rebuildable from every file
on disk (`rebuild`), which is the check on the whole design. The copilot side keeps a byte offset per
session file, so a poll re-reads only what Copilot appended.

Claude Code's own transcripts are not read yet: nothing here knows their shape, and guessing would
count wrong rather than count nothing.

Read-only against everything outside the fleet directory, like the rest of the fleet.
"""
from __future__ import annotations
import calendar
import hashlib
import json
import os
import re
import threading
import time

from .. import textio
from .registry import fleet_dir

LEDGER = "skills.json"
SCHEMA = 1
#: How many of the most recent ticket keys a skill remembers.
TICKETS_KEPT = 20
#: The window the settings page's line counts *used* over.
RECENT_DAYS = 30
#: The tool Copilot runs a skill through.
SKILL_TOOL = "skill"

_lock = threading.Lock()
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


# ------------------------------------------------------------------------------ what is installed


def dirs() -> list[str]:
    """Every skills directory that exists, in the order the CLI reads them: the project's own
    `skills_dir` fact first, then `update.SKILL_DIRS`. Each once."""
    from .. import update as U

    out: list[str] = []
    seen: set[str] = set()
    candidates: list[str] = []
    try:
        candidates.append(U.skills_dir())
    except Exception:                        # noqa: BLE001 - no config, no home: no project dir
        pass
    candidates.extend(U.SKILL_DIRS)
    for raw in candidates:
        try:
            d = textio.norm_path(os.path.expanduser(raw))
        except Exception:                    # noqa: BLE001
            continue
        key = d.lower()
        if key in seen or not os.path.isdir(d):
            continue
        seen.add(key)
        out.append(d)
    return out


def short_dir(d: str) -> str:
    """`~/.copilot/skills` for the home's own directories, the path otherwise."""
    home = textio.norm_path(os.path.expanduser("~")).rstrip("/")
    norm = textio.norm_path(d)
    if home and norm.lower().startswith(home.lower() + "/"):
        return "~" + norm[len(home):]
    return norm


def _sha12(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except OSError:
        return ""


def front_matter(text: str) -> dict:
    """`name` and `description` from a SKILL.md's front matter. Not YAML: the repo's skills carry
    exactly those two keys (`tests/test_skills.py`), a one-line value each, and a folded (`>` or
    `|`) description is joined from its indented lines."""
    m = _FRONT.search(text)
    out: dict[str, str] = {}
    if not m:
        return out
    key, block = "", False
    for line in m.group(1).splitlines():
        if block and (line.startswith((" ", "\t")) or not line.strip()):
            out[key] = (out[key] + " " + line.strip()).strip()
            continue
        block = False
        mk = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not mk:
            continue
        key, value = mk.group(1).lower(), mk.group(2).strip()
        if value in (">", "|", ">-", "|-"):
            out[key], block = "", True
        else:
            out[key] = value.strip("\"'")
    return out


def _stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))


def installed() -> list[dict]:
    """Every skill on disk, across every directory, in directory order then by name.

    `{name, description, dir, path, version, installed, lines, ours, shadowed_by}`: `version` is the
    first twelve hex digits of the SKILL.md's sha256 (the same digest `fingerprint.current` takes,
    which keeps its loop inline, so it is taken again here); `installed` is the file's mtime, UTC;
    `ours` is `update.owned_by_us`. A second folder of the same name is listed too, with
    `shadowed_by` naming the directory whose copy the CLI reads.
    """
    from .. import update as U

    out: list[dict] = []
    winners: dict[str, str] = {}
    for d in dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for folder in names:
            path = os.path.join(d, folder, "SKILL.md")
            if not os.path.isfile(path):
                continue
            try:
                text = textio.read_text(path)
                st = os.stat(path)
            except (OSError, ValueError):
                continue
            front = front_matter(text)
            name = folder
            row = {"name": name, "description": front.get("description", ""),
                   "dir": short_dir(d), "path": textio.norm_path(path), "version": _sha12(path),
                   "installed": _stamp(st.st_mtime), "lines": len(text.splitlines()),
                   "ours": U.owned_by_us(os.path.join(d, folder)),
                   "shadowed_by": winners.get(name, "")}
            winners.setdefault(name, row["dir"])
            out.append(row)
    return out


# ------------------------------------------------------------------------------ the ledger


def ledger_path() -> str:
    return os.path.join(fleet_dir(), LEDGER)


def blank() -> dict:
    return {"schema": SCHEMA, "agents": {}, "copilot": {}, "fleet_sessions": {}, "skills": {},
            "updated": ""}


def _blank_skill() -> dict:
    return {"uses": 0, "ok": 0, "failed": 0, "first": "", "last": "", "repos": {}, "tickets": [],
            "sources": {"fleet": 0, "copilot": 0}}


def read_ledger() -> dict:
    """What has been folded so far, or an empty ledger. Never raises: a ledger that cannot be read
    is one that gets rebuilt, not a page that will not draw."""
    try:
        raw = json.loads(textio.read_text(ledger_path()))
    except (OSError, ValueError):
        return blank()
    if not isinstance(raw, dict) or int(raw.get("schema") or 0) != SCHEMA:
        return blank()
    out = blank()
    for key in ("agents", "copilot", "fleet_sessions", "skills"):
        if isinstance(raw.get(key), dict):
            out[key] = raw[key]
    out["updated"] = str(raw.get("updated") or "")
    out["skills"] = {str(k): dict(_blank_skill(), **v) for k, v in out["skills"].items()
                     if isinstance(v, dict)}
    return out


def write_ledger(state: dict) -> str:
    directory = fleet_dir()
    os.makedirs(directory, exist_ok=True)
    path = ledger_path()
    state["updated"] = _stamp(time.time())
    body = {"schema": SCHEMA, "agents": state.get("agents") or {},
            "copilot": state.get("copilot") or {},
            "fleet_sessions": state.get("fleet_sessions") or {},
            "skills": state.get("skills") or {}, "updated": state["updated"]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return path


# ------------------------------------------------------------------------------ the fold


def _skill_of(data: dict) -> str:
    """The skill a `tool_call` names, or "" when the call is another tool's."""
    if str(data.get("tool") or "") != SKILL_TOOL:
        return ""
    args = data.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return ""
    if not isinstance(args, dict):
        return ""
    name = str(args.get("skill") or args.get("name") or "").strip()
    return name if re.fullmatch(r"[\w.-]{1,96}", name) else ""


def _note_use(state: dict, name: str, *, repo: str, ticket: str, ts: str, source: str) -> None:
    skills = state.setdefault("skills", {})
    row = skills.get(name)
    if row is None:
        row = skills[name] = _blank_skill()
    row["uses"] += 1
    row["sources"][source] = int(row["sources"].get(source) or 0) + 1
    if ts:
        if not row["first"] or ts < row["first"]:
            row["first"] = ts
        if ts > row["last"]:
            row["last"] = ts
    if repo:
        r = row["repos"].setdefault(repo, {"uses": 0, "last": ""})
        r["uses"] += 1
        if ts > r["last"]:
            r["last"] = ts
    if ticket:
        tickets = [t for t in row["tickets"] if t != ticket]
        tickets.append(ticket)
        row["tickets"] = tickets[-TICKETS_KEPT:]


def _note_result(state: dict, name: str, ok: bool) -> None:
    row = state.setdefault("skills", {}).get(name)
    if row is None:
        row = state["skills"][name] = _blank_skill()
    row["ok" if ok else "failed"] += 1


def advance(state: dict, agent: str, events: list[dict]) -> None:
    """Fold one agent's events, in order, into the ledger. A call is counted when it is made and its
    result when it lands, joined on the call's `id`; the join survives a refresh landing between the
    two, because the open calls are kept in the agent's own entry."""
    entry = state.setdefault("agents", {}).setdefault(agent, {"cursor": {"seq": 0}, "open": {}})
    open_calls = entry.setdefault("open", {})
    for ev in events:
        kind, data = ev.get("kind"), ev.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if kind == "session_id" and data.get("session"):
            state.setdefault("fleet_sessions", {})[str(data["session"])] = agent
        elif kind == "started" and data.get("session"):
            state.setdefault("fleet_sessions", {})[str(data["session"])] = agent
        elif kind == "tool_call":
            name = _skill_of(data)
            if name:
                _note_use(state, name, repo=str(ev.get("repo") or agent), ticket=str(ev.get("ticket") or ""),
                          ts=str(ev.get("ts") or ""), source="fleet")
                if data.get("id"):
                    open_calls[str(data["id"])] = name
        elif kind == "tool_result" and data.get("id") is not None:
            name = open_calls.pop(str(data["id"]), "")
            if name:
                _note_result(state, name, bool(data.get("ok")))
        seq = int(ev.get("seq") or 0)
        if seq > int(entry["cursor"].get("seq") or 0):
            entry["cursor"]["seq"] = seq


def update(agent: str) -> dict:
    """Fold whatever this agent's stream has gained since last time, and save it.

    Hooked where `spend.update` is: on every `events.refresh` (it reads what the tick just read) and
    in `lifecycle.rotate_all` BEFORE the normalized log is rolled, so a roll never takes a skill's
    history with it. Serialized within this process; a ledger two processes write is rebuildable.
    """
    from . import events as E

    with _lock:
        state = read_ledger()
        since = int(((state.get("agents") or {}).get(agent) or {}).get("cursor", {}).get("seq") or 0)
        try:
            fresh = E.read(agent, since=since)
        except (OSError, ValueError):
            return state
        if not fresh:
            return state
        advance(state, agent, fresh)
        try:
            write_ledger(state)
        except OSError:
            pass                              # a ledger that cannot be written is rebuildable
        return state


def _agents_on_disk() -> list[str]:
    root = os.path.join(fleet_dir(), "agents")
    try:
        return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        return []


def rebuild(copilot: bool = True) -> dict:
    """Fold every normalized log every agent has on disk, oldest first, and save that.

    `.1` is the NEWEST rotation, so the oldest file is the highest number: each agent's rolled
    files are read descending, then its live file last. The answer must equal the incremental
    ledger; that equality is what makes this a fold rather than a source.
    """
    from . import events as E
    from .registry import agent_dir

    with _lock:
        state = blank()
        for agent in _agents_on_disk():
            directory = agent_dir(agent)
            rolled = []
            try:
                for entry in os.listdir(directory):
                    match = re.fullmatch(re.escape(E.NORMALIZED) + r"\.(\d+)", entry)
                    if match:
                        rolled.append((int(match.group(1)), entry))
            except OSError:
                continue
            order = [n for _, n in sorted(rolled, reverse=True)] + [E.NORMALIZED]
            for filename in order:
                path = os.path.join(directory, filename)
                if os.path.isfile(path):
                    advance(state, agent, _read_jsonl(path))
        if copilot:
            _fold_copilot(state)
        try:
            write_ledger(state)
        except OSError:
            pass
        return state


def _read_jsonl(path: str) -> list[dict]:
    out = []
    try:
        text = textio.read_text(path)
    except (OSError, ValueError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------------------ Copilot's own sessions


def _fleet_session_ids(state: dict) -> set[str]:
    """Every session id a fleet agent is known by: the index each agent keeps, its lock, and the
    ids the fold has seen on the streams. A Copilot session file with one of these ids is the
    fleet's own transcript written twice, and is counted once."""
    from . import sessions as SESS, supervisor

    ids = set(str(k) for k in (state.get("fleet_sessions") or {}))
    for agent in _agents_on_disk():
        try:
            for s in SESS.load_sessions(agent):
                if isinstance(s, dict) and s.get("id"):
                    ids.add(str(s["id"]))
        except Exception:                    # noqa: BLE001 - an index that cannot be read names nothing
            pass
        try:
            lock = supervisor.read_lock(agent) or {}
            if lock.get("session"):
                ids.add(str(lock["session"]))
        except Exception:                    # noqa: BLE001
            pass
    return ids


def _fold_copilot(state: dict) -> bool:
    """Fold what Copilot's own session files gained since last time. Returns whether anything did.

    Each session keeps `{pos, mtime, open, repo}` in the ledger's `copilot` entry: the file is read
    from `pos` only when its mtime moved, and `open` joins a call to a result across two reads.
    Read-only against Copilot's directory, like `sessions.py`.
    """
    from . import sessions as SESS

    root = SESS.session_state_dir()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return False
    skip = _fleet_session_ids(state)
    book = state.setdefault("copilot", {})
    moved = False
    for sid in names:
        if sid in skip or sid in (".", ".."):
            continue
        d = os.path.join(root, sid)
        file = os.path.join(d, "events.jsonl")
        try:
            st = os.stat(file)
        except OSError:
            continue
        entry = book.get(sid) or {"pos": 0, "mtime": 0.0, "open": {}, "repo": ""}
        if entry.get("mtime") == st.st_mtime and entry.get("pos") == st.st_size:
            continue
        if not entry.get("repo"):
            cwd = SESS._workspace_cwd(d)
            entry["repo"] = os.path.basename(textio.norm_path(cwd).rstrip("/")) if cwd else ""
        pos = int(entry.get("pos") or 0)
        if pos > st.st_size:
            pos = 0                           # the file was rewritten: start over
        try:
            with open(file, "rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
        except OSError:
            continue
        lines = chunk.split(b"\n")
        # A line still being written has no newline yet: leave it for the next read.
        tail = lines.pop() if not chunk.endswith(b"\n") else b""
        for raw in lines:
            raw = raw.strip()
            if not raw.startswith(b"{"):
                continue
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            _advance_copilot(state, entry, ev)
        entry["pos"] = st.st_size - len(tail)
        entry["mtime"] = st.st_mtime
        book[sid] = entry
        moved = True
    return moved


def _advance_copilot(state: dict, entry: dict, ev: dict) -> None:
    kind, data = ev.get("type"), ev.get("data") or {}
    if not isinstance(data, dict):
        return
    open_calls = entry.setdefault("open", {})
    if kind == "tool.execution_start":
        name = _skill_of({"tool": data.get("toolName"), "arguments": data.get("arguments")})
        if name:
            ts = str(ev.get("timestamp") or "").replace("Z", "").replace("+00:00", "")[:19]
            _note_use(state, name, repo=entry.get("repo") or "", ticket="", ts=ts, source="copilot")
            if data.get("toolCallId"):
                open_calls[str(data["toolCallId"])] = name
    elif kind == "tool.execution_complete" and data.get("toolCallId") is not None:
        name = open_calls.pop(str(data["toolCallId"]), "")
        if name:
            _note_result(state, name, bool(data.get("success")))


def fold_copilot_sessions() -> dict:
    """Fold Copilot's own sessions outside the fleet into the ledger, and save it if anything moved."""
    with _lock:
        state = read_ledger()
        if _fold_copilot(state):
            try:
                write_ledger(state)
            except OSError:
                pass
        return state


# ------------------------------------------------------------------------------ the snapshot


def _recent(iso: str, days: int, now: float) -> bool:
    if not iso:
        return False
    try:
        then = calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return False
    return now - then <= days * 86400


def snapshot(*, fold: bool = True, copilot: bool = True) -> dict:
    """What the marketplace shows: every installed skill with its use, and every used skill that is
    no longer installed. With `fold`, every registered agent's stream is folded first (the page's
    30-second poll is also a tick), and Copilot's own sessions when `copilot`."""
    from .registry import Registry

    if fold:
        try:
            for name in Registry().repos:
                update(name)
        except Exception:                    # noqa: BLE001 - no registry is no agents
            pass
        if copilot:
            try:
                fold_copilot_sessions()
            except Exception:                # noqa: BLE001 - Copilot's directory is not ours
                pass
    state = read_ledger()
    used = state.get("skills") or {}
    now = time.time()
    rows: list[dict] = []
    seen: set[str] = set()
    for row in installed():
        name = row["name"]
        use = used.get(name) if not row.get("shadowed_by") else None
        rows.append(_row(row, use, now))
        seen.add(name)
    for name in sorted(used):
        if name in seen:
            continue
        rows.append(_row({"name": name, "description": "", "dir": "", "path": "", "version": "",
                          "installed": None, "lines": 0, "ours": False, "shadowed_by": "", "missing": True},
                         used[name], now))
    rows.sort(key=lambda r: (-r["uses"], r["name"], r.get("dir") or ""))
    counted = [r for r in rows if not r.get("shadowed_by")]
    totals = {"skills": sum(1 for r in counted if not r.get("missing")),
              "used": sum(1 for r in counted if r["uses"]),
              "unused": sum(1 for r in counted if r["unused"]),
              "uses": sum(r["uses"] for r in counted),
              "used_recently": sum(1 for r in counted if _recent(r["last"], RECENT_DAYS, now)),
              "recent_days": RECENT_DAYS, "missing": sum(1 for r in counted if r.get("missing"))}
    return {"dirs": [short_dir(d) for d in dirs()], "skills": rows, "totals": totals,
            "ledger_updated": state.get("updated") or "", "ledger": ledger_path()}


def _row(row: dict, use: dict | None, now: float) -> dict:
    use = use or _blank_skill()
    repos = sorted(({"repo": k, "uses": int(v.get("uses") or 0), "last": v.get("last") or ""}
                    for k, v in (use.get("repos") or {}).items()),
                   key=lambda r: (-r["uses"], r["repo"]))
    out = dict(row)
    out.update({"uses": int(use.get("uses") or 0), "ok": int(use.get("ok") or 0),
                "failed": int(use.get("failed") or 0), "first": use.get("first") or "",
                "last": use.get("last") or "", "repos": repos,
                "tickets": list(use.get("tickets") or []),
                "sources": {"fleet": int((use.get("sources") or {}).get("fleet") or 0),
                            "copilot": int((use.get("sources") or {}).get("copilot") or 0)},
                "recent": _recent(use.get("last") or "", RECENT_DAYS, now)})
    out["missing"] = bool(row.get("missing"))
    out["unused"] = out["uses"] == 0 and not out["missing"] and not row.get("shadowed_by")
    return out
