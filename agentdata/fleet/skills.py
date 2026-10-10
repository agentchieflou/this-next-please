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

**Where the skills come from** is the setting `fleet.skills.source` (docs/fleet-skills.md §The
marketplace source): a GitHub `owner/repo` (optionally `@ref`), a git URL, or a local folder holding
`skills/*/SKILL.md`. `sync` installs what the source offers into the first skills directory that
exists, replacing only folders carrying this source's `.marketplace` marker, and `catalog` reads what
it offers without installing. Both keep their last answer in the ledger.

Read-only against everything outside the fleet directory, like the rest of the fleet.
"""
from __future__ import annotations
import calendar
import hashlib
import shutil
import json
import os
import re
import threading
import time

from .. import proc, textio
from .registry import fleet_dir

LEDGER = "skills.json"
SCHEMA = 1
#: How many of the most recent ticket keys a skill remembers.
TICKETS_KEPT = 20
#: The window the settings page's line counts *used* over.
RECENT_DAYS = 30
#: The tool Copilot runs a skill through.
SKILL_TOOL = "skill"

#: The setting naming the marketplace, and what it is when nothing was set: this repo's skills.
SOURCE_KEY = "fleet.skills.source"
DEFAULT_SOURCE = "agentchieflou/this-next-please"
#: The file a folder this module installed carries: the source it came from, one line.
MARKER = ".marketplace"
#: Where a git source is cloned: `<fleet dir>/marketplace/<sha12 of the url>/`.
CLONES = "marketplace"
SYNC_TIMEOUT_S = 120
REFRESH_TIMEOUT_S = 30
#: Where a sync installs when no skills directory exists yet: the one `gh skill install` writes.
INSTALL_DIR = "~/.copilot/skills"

_lock = threading.Lock()
_sync_lock = threading.Lock()
_running: dict = {"on": False, "source": ""}
_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_GITHUB = re.compile(r"^([A-Za-z0-9][\w.-]*)/([A-Za-z0-9][\w.-]*?)(?:\.git)?(?:@([\w./-]+))?$")
_GIT_URL = re.compile(r"^(https?://|ssh://|git://|file://|[\w.-]+@[\w.-]+:)")


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
            "sync": {}, "catalog": {}, "updated": ""}


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
    for key in ("agents", "copilot", "fleet_sessions", "skills", "sync", "catalog"):
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
            "skills": state.get("skills") or {}, "updated": state["updated"],
            "sync": state.get("sync") or {}, "catalog": state.get("catalog") or {}}
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
    src = source()
    cat = state.get("catalog") or {}
    offered = {r["name"]: r for r in (cat.get("skills") or []) if isinstance(r, dict) and r.get("name")}
    same_source = bool(offered) and cat.get("source") == src
    installed_names = {r["name"] for r in rows if not r.get("missing")}
    for r in rows:
        r["available"] = (r["name"] in offered) if same_source else None
    not_installed = [{"name": n, "description": offered[n].get("description", "")}
                     for n in sorted(offered) if n not in installed_names] if same_source else []
    last = dict(state.get("sync") or {})
    last["running"] = sync_running()
    return {"dirs": [short_dir(d) for d in dirs()], "skills": rows, "totals": totals,
            "ledger_updated": state.get("updated") or "", "ledger": ledger_path(),
            "source": {"value": src, "kind": source_kind(src), "key": SOURCE_KEY},
            "sync": last, "catalog": cat if same_source else {}, "not_installed": not_installed}


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


# ------------------------------------------------------------------------------ the source


def source() -> str:
    """`fleet.skills.source`, or the default."""
    from .. import config as C

    try:
        value = C.get(C.load(), "fleet.skills.source")
    except Exception:                        # noqa: BLE001 - no config is the default source
        value = None
    return str(value or DEFAULT_SOURCE).strip()


def source_kind(value: str) -> str:
    """`path` for a folder that exists, `github` for `owner/repo[@ref]`, `git` for anything
    `git clone` takes, "" for what none of them can be. A folder is looked for first, so a relative
    folder that happens to be spelled `a/b` is the folder -- unless it is a bare repository (a `HEAD`
    file beside an `objects/` folder), which has no skills to read and is what `git clone` takes;
    on Windows that is how a local `.git` source is spelled, since `file://` is not a path there."""
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        folder = os.path.expanduser(value)
        if os.path.isdir(folder):
            if os.path.isfile(os.path.join(folder, "HEAD")) and os.path.isdir(os.path.join(folder, "objects")):
                return "git"
            return "path"
    except OSError:
        pass
    if _GIT_URL.match(value) or value.endswith(".git"):
        return "git"
    if _GITHUB.match(value):
        return "github"
    return ""


def _github_parts(value: str) -> tuple[str, str, str]:
    m = _GITHUB.match(value.strip())
    return (m.group(1), m.group(2), m.group(3) or "") if m else ("", "", "")


def _split_ref(value: str) -> tuple[str, str]:
    """`url@ref` for a git source: the ref after the last `@` that follows the last `/`, so an
    `git@host:` user is never read as one."""
    at = value.rfind("@")
    if at > value.rfind("/") and at > value.rfind(":"):
        return value[:at], value[at + 1:]
    return value, ""


def target_dir() -> str:
    """Where a sync installs: the first `SKILL_DIRS` entry that exists, made when none does."""
    from .. import update as U

    for raw in U.SKILL_DIRS:
        d = os.path.expanduser(raw)
        if os.path.isdir(d):
            return textio.norm_path(d)
    d = os.path.expanduser(INSTALL_DIR)
    os.makedirs(d, exist_ok=True)
    return textio.norm_path(d)


def clone_dir(url: str) -> str:
    return os.path.join(fleet_dir(), CLONES, hashlib.sha256(url.strip().encode()).hexdigest()[:12])


def _dir_hashes(d: str) -> dict[str, str]:
    out = {}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        path = os.path.join(d, n, "SKILL.md")
        if os.path.isfile(path):
            out[n] = _sha12(path)
    return out


def _marker(folder: str) -> str:
    try:
        return textio.read_text(os.path.join(folder, MARKER)).strip()
    except (OSError, ValueError):
        return ""


def _skills_root(folder: str) -> str:
    """`<folder>/skills` when it is there, else the folder itself, so a checkout of this repository
    and a bare folder of skills both read."""
    sub = os.path.join(folder, "skills")
    return sub if os.path.isdir(sub) else folder


def _offered(folder: str) -> list[dict]:
    root = _skills_root(folder)
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        path = os.path.join(root, n, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            front = front_matter(textio.read_text(path))
        except (OSError, ValueError):
            front = {}
        out.append({"name": n, "description": front.get("description", ""), "version": _sha12(path)})
    return out


def _git(args: list[str], *, cwd: str | None = None, timeout: int) -> tuple[int, str, str]:
    code, out, err, _el = proc.run(["git", *args], cwd=cwd, timeout=timeout,
                                   env={"GIT_TERMINAL_PROMPT": "0"})
    return code, out or "", err or ""


def _fetch_git(url: str, ref: str, *, timeout: int) -> tuple[str, str, str, str]:
    """`(folder, commit, error, hint)`: a shallow clone the first time, a fast-forward pull after.
    A pull that cannot fast-forward, or a clone that fails, leaves what is there and says why."""
    folder = clone_dir(url + ("@" + ref if ref else ""))
    try:
        if os.path.isdir(os.path.join(folder, ".git")):
            # A fetch and a hard reset, not a pull: the clone is shallow and nobody edits it, and a
            # `pull --ff-only` of a shallow clone calls the two histories diverged.
            code, out, err = _git(["fetch", "--depth", "1", "--quiet", "origin", ref or "HEAD"],
                                  cwd=folder, timeout=timeout)
            if code == 0:
                code, out, err = _git(["reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=folder, timeout=timeout)
            if code != 0:
                tail = (err or out).strip().splitlines()
                return folder, _head(folder), f"git fetch: {tail[-1][:200] if tail else code}", \
                    f"the clone is at {folder}; delete it to clone afresh"
        else:
            os.makedirs(os.path.dirname(folder), exist_ok=True)
            args = ["clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + [url, folder]
            code, out, err = _git(args, timeout=timeout)
            if code != 0:
                tail = (err or out).strip().splitlines()
                return "", "", f"git clone: {tail[-1][:200] if tail else code}", \
                    "check the URL and that this machine can reach it; a private host needs its key loaded"
    except proc.ProcError as e:
        return folder if os.path.isdir(folder) else "", "", e.msg, e.hint or "install git and try again"
    return folder, _head(folder), "", ""


def _head(folder: str) -> str:
    try:
        code, out, _err = _git(["rev-parse", "HEAD"], cwd=folder, timeout=10)
    except proc.ProcError:
        return ""
    return out.strip()[:12] if code == 0 else ""


def _install_from(folder: str, target: str, src: str, *, kinds: dict) -> list[str]:
    """Copy every offered skill into `target`, replacing only folders carrying this source's
    marker; a folder without one, or with another source's, is left as it is and named in
    `kinds["skipped"]`. A folder with this source's marker the source no longer offers is removed.
    Returns the names installed."""
    offered = {row["name"] for row in _offered(folder)}
    root = _skills_root(folder)
    done = []
    for name in sorted(offered):
        dest = os.path.join(target, name)
        if os.path.isdir(dest):
            mark = _marker(dest)
            if mark != src:
                kinds["skipped"].append(name + (" (another source: " + mark + ")" if mark else " (not installed by a sync)"))
                continue
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(os.path.join(root, name), dest)
        with open(os.path.join(dest, MARKER), "w", encoding="utf-8", newline="\n") as f:
            f.write(src + "\n")
        done.append(name)
    try:
        for name in sorted(os.listdir(target)):
            dest = os.path.join(target, name)
            if name not in offered and os.path.isdir(dest) and _marker(dest) == src:
                shutil.rmtree(dest, ignore_errors=True)
    except OSError:
        pass
    return done


def _mark(target: str, names, src: str) -> None:
    for name in names:
        dest = os.path.join(target, name)
        if os.path.isdir(dest) and not _marker(dest):
            try:
                with open(os.path.join(dest, MARKER), "w", encoding="utf-8", newline="\n") as f:
                    f.write(src + "\n")
            except OSError:
                pass


def _github_commit(owner: str, repo: str, ref: str) -> str:
    try:
        code, out, _err, _el = proc.run(["gh", "api", f"repos/{owner}/{repo}/commits/{ref or 'HEAD'}",
                                         "--jq", ".sha"], timeout=REFRESH_TIMEOUT_S)
    except proc.ProcError:
        return ""
    return out.strip()[:12] if code == 0 else ""


def sync(value: str | None = None) -> dict:
    """Install what the marketplace offers, and say what changed.

    `github` runs `gh skill install <owner/repo> --all` as `ad-update` does, with its "already
    installed" retry; `git` clones (or pulls) under the fleet directory and copies; `path` copies.
    Before and after, the SKILL.md hashes in the target directory say what was added, updated,
    removed or left as it was. Every failure is a result with `error` and `hint`, never a raise.
    """
    from .. import update as U

    src = (value or source()).strip()
    kind = source_kind(src)
    started = time.time()
    result = {"ok": False, "source": src, "kind": kind, "started": _stamp(started), "finished": "",
              "seconds": 0.0, "added": [], "updated": [], "unchanged": [], "removed": [],
              "skipped": [], "commit": "", "error": "", "hint": "", "target": ""}

    def finish(error: str = "", hint: str = "") -> dict:
        result.update(error=error, hint=hint, ok=not error, finished=_stamp(time.time()),
                      seconds=round(time.time() - started, 1))
        with _lock:
            state = read_ledger()
            state["sync"] = dict(result)
            try:
                write_ledger(state)
            except OSError:
                pass
        return result

    if not kind:
        return finish(f"not a marketplace: {src!r}",
                      "set fleet.skills.source to a GitHub owner/repo, a git URL or a folder that exists")
    try:
        target = target_dir()
    except OSError as e:
        return finish(f"no skills directory can be made: {e}", "create ~/.copilot/skills by hand")
    result["target"] = short_dir(target)
    before = _dir_hashes(target)
    kinds = {"skipped": result["skipped"]}
    try:
        if kind == "path":
            folder = os.path.expanduser(src)
            if not _offered(folder):
                return finish(f"no skills/*/SKILL.md under {src}", "a marketplace folder holds one folder per skill, each with a SKILL.md")
            _install_from(folder, target, src, kinds=kinds)
        elif kind == "git":
            url, ref = _split_ref(src)
            folder, commit, error, hint = _fetch_git(url, ref, timeout=SYNC_TIMEOUT_S)
            result["commit"] = commit
            if error:
                return finish(error, hint)
            if not _offered(folder):
                return finish(f"no skills/*/SKILL.md in {src}", "the repository holds no skills folder at its root")
            _install_from(folder, target, src, kinds=kinds)
        else:
            owner, repo, ref = _github_parts(src)
            spec = f"{owner}/{repo}" + (f"@{ref}" if ref else "")
            cmd = U.skills_command(spec)
            try:
                code, out, err, _el = proc.run(cmd, timeout=SYNC_TIMEOUT_S)
            except proc.ProcError as e:
                return finish(e.msg, e.hint or "install GitHub CLI (gh) and sign in, or name a git URL or a folder")
            if code != 0:
                already = U.parse_already_installed(f"{out}\n{err}")
                if already:
                    U.remove_our_skills(target, already)
                    retry = cmd + ["--force"] if U.supports_force() else cmd
                    try:
                        code, out, err, _el = proc.run(retry, timeout=SYNC_TIMEOUT_S)
                    except proc.ProcError as e:
                        return finish(e.msg, e.hint)
                if code != 0:
                    return finish("gh skill install: " + U.tail_lines(out, err, 3).replace("\n", " · ")[:300],
                                  U.diagnose(code, out, err) or "run the command yourself to see why")
            result["commit"] = _github_commit(owner, repo, ref)
    except OSError as e:
        return finish(f"copy failed: {e}", f"check that {short_dir(target)} is writable")
    after = _dir_hashes(target)
    result["added"] = sorted(n for n in after if n not in before)
    result["removed"] = sorted(n for n in before if n not in after)
    result["updated"] = sorted(n for n in after if n in before and before[n] != after[n])
    result["unchanged"] = sorted(n for n in after if n in before and before[n] == after[n])
    if kind == "github":
        _mark(target, result["added"] + result["updated"], src)
    try:
        from . import fingerprint
        fingerprint.forget()
    except Exception:                        # noqa: BLE001
        pass
    return finish()


def start_sync(value: str | None = None) -> dict:
    """Run `sync` on a thread, one at a time. `{"ok": True, "started": True}` or
    `{"ok": False, "code": "skills_sync_running"}` while one is already running."""
    with _sync_lock:
        if _running["on"]:
            return {"ok": False, "code": "skills_sync_running", "error": "a sync is already running",
                    "hint": f"wait for the sync from {_running['source']} to finish", "source": _running["source"]}
        _running.update(on=True, source=(value or source()).strip())

    def go():
        try:
            sync(value)
        finally:
            with _sync_lock:
                _running.update(on=False, source="")

    threading.Thread(target=go, name="skills-sync", daemon=True).start()
    return {"ok": True, "started": True, "source": _running["source"]}


def sync_running() -> bool:
    with _sync_lock:
        return bool(_running["on"])


def catalog(value: str | None = None) -> dict:
    """What the marketplace offers, without installing: `{source, kind, fetched, skills: [{name,
    description, version}], commit, error, hint}`, kept in the ledger as `catalog`. A GitHub source
    is listed through `gh api` when gh is there (names only, the descriptions from a clone when one
    is), else cloned over https; a git source from its clone; a folder from itself."""
    src = (value or source()).strip()
    kind = source_kind(src)
    out = {"source": src, "kind": kind, "fetched": _stamp(time.time()), "skills": [], "commit": "",
           "error": "", "hint": ""}
    if not kind:
        out.update(error=f"not a marketplace: {src!r}",
                   hint="set fleet.skills.source to a GitHub owner/repo, a git URL or a folder that exists")
    elif kind == "path":
        out["skills"] = _offered(os.path.expanduser(src))
        if not out["skills"]:
            out.update(error=f"no skills/*/SKILL.md under {src}", hint="a marketplace folder holds one folder per skill")
    elif kind == "git":
        url, ref = _split_ref(src)
        folder, commit, error, hint = _fetch_git(url, ref, timeout=REFRESH_TIMEOUT_S)
        out["commit"] = commit
        if error and not folder:
            out.update(error=error, hint=hint)
        else:
            out["skills"] = _offered(folder)
            if error:
                out.update(error=error, hint=hint)
    else:
        owner, repo, ref = _github_parts(src)
        names = _github_names(owner, repo, ref)
        if names is None:
            url = f"https://github.com/{owner}/{repo}.git"
            folder, commit, error, hint = _fetch_git(url, ref, timeout=REFRESH_TIMEOUT_S)
            out["commit"] = commit
            if error and not folder:
                out.update(error=error, hint=hint or "install GitHub CLI (gh), or check the network")
            else:
                out["skills"] = _offered(folder)
        else:
            by_name = {}
            for candidate in (clone_dir(f"https://github.com/{owner}/{repo}.git" + ("@" + ref if ref else "")),):
                if os.path.isdir(candidate):
                    by_name = {r["name"]: r for r in _offered(candidate)}
            out["skills"] = [by_name.get(n) or {"name": n, "description": "", "version": ""} for n in names]
            out["commit"] = _github_commit(owner, repo, ref)
    with _lock:
        state = read_ledger()
        state["catalog"] = dict(out)
        try:
            write_ledger(state)
        except OSError:
            pass
    return out


def _github_names(owner: str, repo: str, ref: str) -> list[str] | None:
    """The skill folders a GitHub repo offers, through `gh api`; None when gh cannot answer."""
    path = f"repos/{owner}/{repo}/contents/skills" + (f"?ref={ref}" if ref else "")
    try:
        code, out, _err, _el = proc.run(["gh", "api", path, "--jq", '.[] | select(.type == "dir") | .name'],
                                        timeout=REFRESH_TIMEOUT_S)
    except proc.ProcError:
        return None
    if code != 0:
        return None
    return sorted(n.strip() for n in out.splitlines() if n.strip())
