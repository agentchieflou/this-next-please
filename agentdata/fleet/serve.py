"""`ad-fleet serve`: the multi-viewer. One local page, one tile per agent, live.

The epic is named for YouTube's multi-view and this is that page: a grid of agent tiles, each a
live view of one repository's agent, any one of which can be blown up to fill the window and
dropped back again.

**Why a local web page and not a GUI.** The same artefact has to render in a PyCharm JCEF tool
window (#99), in VS Code's Simple Browser, and in Edge on a fourth monitor (#100) -- three
embedders that agree on exactly one thing, HTML. Those issues then only decide *where* it is shown.

**Zero new dependencies.** `http.server` and `ThreadingHTTPServer`, SSE over a plain chunked
response, hand-written HTML/CSS/JS shipped as package data. No bundler, no framework, no CDN --
JCEF and Simple Browser both sit behind the corporate proxy, so anything the page fetches from the
internet is a page that does not load at work.

**It is a view, not a second source of truth.** Every number comes from #94's normalized stream and
every button calls the same #93/#95 function the CLI verb calls. The server spawns nothing itself.

**Security is loopback plus a per-run token.** The socket binds 127.0.0.1 and nothing else, every
request must carry the token this run generated, and the token is not a cookie -- so another page
on the corporate network cannot drive the fleet even if it guesses the port.

**The desk half (#130, #131, #132, #133) is read-only except for one click.** `/api/desk` answers
with what each project already publishes -- the catalogue's `show`, the link rail, the polled cells,
the newest verify summary the repo's own agent wrote, and the files Downloads is offering it. The
only write any of it can cause is `inbox.attach`, which copies one file into `<repo>/.agent/in/` and
only because somebody pressed a button.

**One process, one poller, one selection.** Four browser windows on four screens (#133) are four SSE
connections to this one server, so the poller, the inbox watcher and the catalogue handle are held
once for the process rather than once per connection -- otherwise the Jira poll would multiply by the
number of monitors the operator happens to own. The selected project lives here too, and rides the
same stream, which is what makes clicking a tile on the left monitor change the centre one.
"""
from __future__ import annotations
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import textio
from . import (agentstate, approval, board as B, catalogue as CAT, events as E, inbox as IN,
               links as LK, notify as N, poll as P, supervisor)
from .registry import Registry, RegistryError, fleet_dir

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SERVE_FILE = "serve.json"
HEARTBEAT_S = 15.0
TICK_S = 0.4                 # how often the stream looks for new events; a tile must feel live
NOTIFY_EVERY_S = 5.0         # how often the notification rules run; state changes are not frequent
MAX_BODY = 64 * 1024
# What a shell must speak to host this page. Bumped only when an embedder would have to change:
# a new route it must call, or a changed meaning for one it already calls.
CONTRACT = 1
LOOPBACK = ("127.0.0.1", "::1", "localhost")

POLL_EVERY_S = 5.0           # the floor between two ticks of the shared poller, however many tabs
# The same idea for the event fold. `E.refresh` is not free -- per repository it reads the cursor,
# reads the agent's raw log, globs `.agent/friction/`, rewrites the cursor and appends to the
# stream -- and the SSE loop ran it per repository per tick *per connection*. #133 puts four windows
# on four screens and its whole premise is that they are cheap because they share one stream; four
# folds a tick is the opposite of sharing, and on a laptop with antivirus in the open() path it is
# what makes the fan audible. Process-wide like `POLL_EVERY_S`, so N windows cost one fold between
# them. Half a second rather than the poller's five: the fold is how the agent's newest line reaches
# the transcript, and `test_a_live_stream_delivers_a_new_event_within_a_second` is the bar it has to
# stay under -- 0.5 s of floor plus one 0.4 s tick still lands inside it.
FOLD_EVERY_S = 0.5
DESK_LIMIT = 12              # verify rows and friction rows per project; a tile is not a file manager
MAX_TRAY = 60                # rows in the unsorted tray; a year of Downloads is not a work queue

# The three layouts of #133, and the three windows layout B splits into. The page reads them off
# its own query string and this list is what says which spellings exist; `cli_fleet.LAYOUTS` is the
# other half of the same seam and a test asserts the two still agree.
# The two assets `index.html` references. They are rewritten with the run token when the page is
# served; see `_index`.
ASSETS = ("app.css", "app.js")

LAYOUTS = ("grid", "roles", "screens")
VIEWS = ("board", "agents", "verify")

# What `.agent/out/` file counts as a verify summary, and which command wrote it. An allow-list of
# *names*, like the catalogue's: `.agent/out/` also holds trace jsonl, screenshots and the debug log,
# and "show the newest file" would eventually put a stack trace on the operator's centre monitor.
VERIFY_KINDS = (("*-uat-findings.md", "ad-uat reconcile"),
                ("*_uat_findings.tsv", "ad-uat reconcile"),
                ("*_pbip_*.tsv", "ad-pbip"),
                ("*-pbip-findings.md", "ad-pbip"),
                ("verification-*.toon", "laptop verification"))
VERIFY_DIR = (".agent", "out")
VERIFY_HEAD = 3000           # characters of the summary the pane shows; the link opens the rest

# The page may load nothing but itself. Belt and braces with shipping no external references: if a
# later edit pastes in a CDN script tag, the browser refuses it and the test below catches it.
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'"


class ServeError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# --------------------------------------------------------------------------------- the API layer


def format_age_str(seconds: int | float) -> str:
    """Format seconds into human readable elapsed age string."""
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    days = int(seconds // 86400)
    return f"{days} days ago" if days > 1 else "yesterday"


def split_runs(stream: list[dict], live: bool = False) -> tuple[dict, list[dict]]:
    """Split an event stream into the current run and earlier runs summary.

    A run begins at a 'started' event.
    Returns:
        (current_run_dict, earlier_runs_list)
    """
    if not stream:
        return ({"n": 0, "started": "", "resumed": False, "session": "",
                 "ticket": "", "live": live, "events": []}, [])

    started_indices = [i for i, ev in enumerate(stream) if ev.get("kind") == "started"]
    if not started_indices:
        d = agentstate.derive(stream, live=live)
        return ({"n": 1, "started": stream[0].get("ts", ""), "resumed": False,
                 "session": d.get("session", ""), "ticket": d.get("ticket", ""),
                 "live": live, "events": stream}, [])

    earlier = []
    for idx, start_i in enumerate(started_indices[:-1]):
        end_i = started_indices[idx + 1]
        run_events = stream[start_i:end_i]
        d = agentstate.derive(run_events, live=False)
        start_ev = stream[start_i]
        end_ev = run_events[-1] if run_events else start_ev
        earlier.append({
            "n": idx + 1,
            "started": start_ev.get("ts", ""),
            "ended": end_ev.get("ts", ""),
            "state": d["state"],
            "ticket": d.get("ticket", ""),
        })

    last_start_i = started_indices[-1]
    curr_events = stream[last_start_i:]
    curr_derived = agentstate.derive(curr_events, live=live)
    start_ev = stream[last_start_i]
    start_data = start_ev.get("data") or {}
    curr_run = {
        "n": len(started_indices),
        "started": start_ev.get("ts", ""),
        "resumed": bool(start_data.get("resumed", False)),
        "session": curr_derived.get("session") or start_data.get("session", ""),
        "ticket": curr_derived.get("ticket") or start_ev.get("ticket", ""),
        "live": live,
        "events": curr_events,
    }
    return curr_run, earlier


def fleet_snapshot() -> dict:
    """Everything the page needs to draw itself from cold. Also the reconnect path.

    The row is built field by field rather than merged from `supervisor.status()` wholesale, because
    that dict also carries an `agent` word for the same idea as `state`. Two state words on one row
    is the second-source-of-truth problem in miniature: they would disagree eventually, and nobody
    would know which the tile was showing. The fold (#94) is the state; the supervisor supplies only
    what the fold cannot see -- where the checkout is, and which pid is holding it.
    """
    rows = []
    try:
        # Once, not once per row: `Registry()` re-parses `registry.json` every time it is built.
        registry = Registry()
    except RegistryError:
        registry = None
    for row in supervisor.status():
        name = row["repo"]
        try:
            repo = registry.get(name) if registry is not None else None
            if repo is not None:
                E.refresh(name, repo.path, repo_state=repo.state())
        except (RegistryError, OSError):
            pass
        stream = E.read(name)
        is_live = bool(supervisor.live(name))
        curr_run, earlier = split_runs(stream, live=is_live)
        derived = agentstate.derive(curr_run["events"], live=is_live) if curr_run["events"] else agentstate.derive(stream, live=is_live)

        last_age_s = row.get("last_event_age_s", -1)
        pid = row.get("pid", 0)
        is_supervised = bool(pid and is_live)
        if not is_supervised or (last_age_s > 120 and not is_live):
            is_supervised = False
            if not stream or not curr_run["started"]:
                not_supervised_sentence = "this agent is not supervised"
            else:
                age_text = format_age_str(last_age_s) if last_age_s >= 0 else "recently"
                not_supervised_sentence = f"last run ended {age_text}; nothing is supervised now"
        else:
            not_supervised_sentence = ""

        rows.append({"repo": name, "path": row.get("path", ""),
                     "jira_project": row.get("jira_project", ""),
                     "pid": pid, "last_event_age_s": last_age_s,
                     "supervised": is_supervised,
                     "not_supervised_sentence": not_supervised_sentence,
                     "run": curr_run,
                     "earlier": earlier,
                     **derived,
                     "last_seq": stream[-1]["seq"] if stream else 0,
                     "needs_human": agentstate.needs_the_human(derived["state"]),
                     # The project's own state (#131), beside the agent's. Named `polls` and not
                     # folded into the row, because a cell can be stale or grey and the agent's
                     # state never is -- flattening them would make one age apply to both.
                     "polls": poll_state(name),
                     "recent": curr_run["events"][-40:] if curr_run["events"] else stream[-40:]})
    return {"repos": rows, "approvals": approval.pending(), "fleet_dir": fleet_dir(),
            "desk": desk_state(),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


# ------------------------------------------------------------------- the desk (#130 #131 #132)


# The poller, the inbox watcher and the catalogue handle are per *process*, not per request and not
# per SSE connection: #133 puts four windows on four screens, and four pollers would be four times
# the Jira traffic for one operator's desk. Keyed on `fleet_dir()` so that moving the fleet -- which
# is an environment variable, and is what every test does -- drops the handles rather than answering
# from the previous one's sqlite file.
_desk = {"dir": "", "poller": None, "inbox": None, "catalogue": None, "last_tick": 0.0,
         "last_fold": 0.0}
_desk_lock = threading.RLock()

DESK_FILE = "desk.json"

# The selected project, shared by every window on the same server, now persisted in desk.json.
# Arrangement holds per-layout ordering, sizes and pinned tiles.
_selection = {
    "selected": "",
    "screens": [],
    "version": 0,
    "at": "",
    "arrangement": {
        "grid": {"order": [], "size": {}, "pinned": []},
        "roles": {"order": []},
        "screens": {"order": []},
    },
}


def _desk_file() -> str:
    return os.path.join(fleet_dir(), DESK_FILE)


def _load_desk() -> None:
    path = _desk_file()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _selection["selected"] = str(data.get("selected") or "")
                _selection["screens"] = [str(x) for x in data.get("screens") or []]
                _selection["version"] = int(data.get("version") or 0)
                _selection["at"] = str(data.get("at") or "")
                arr = data.get("arrangement")
                if isinstance(arr, dict):
                    _selection["arrangement"] = {
                        k: dict(v) if isinstance(v, dict) else v for k, v in arr.items()
                    }
        except Exception:
            pass


def _save_desk() -> None:
    path = _desk_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_text(path, json.dumps(_selection, indent=2))
    except Exception:
        pass


def _fresh() -> dict:
    """The handle bag for the current `fleet_dir()`, dropping one built for a different fleet.

    An empty `dir` is "nothing has been opened yet", not "a different fleet": resetting on that
    would throw away a selection made before the first handle was needed, which is every window that
    clicked a tile before it opened the catalogue.
    """
    here = fleet_dir()
    if _desk["dir"] and _desk["dir"] != here:
        reset()
    if not _desk["dir"]:
        _load_desk()
    _desk["dir"] = here
    return _desk


def reset() -> None:
    """Drop the shared handles and the selection. Called when the fleet moves under a live process."""
    with _desk_lock:
        cat = _desk.get("catalogue")
        if cat is not None:
            try:
                cat.close()
            except Exception:                # noqa: BLE001 - a closed handle is the point
                pass
        _desk.update(dir="", poller=None, inbox=None, catalogue=None, last_tick=0.0,
                     last_fold=0.0)
        _selection.update(
            selected="",
            screens=[],
            version=_selection["version"] + 1,
            at=E.stamp(),
            arrangement={
                "grid": {"order": [], "size": {}, "pinned": []},
                "roles": {"order": []},
                "screens": {"order": []},
            },
        )
        _save_desk()



def poller():
    """The one `Poller`, or None when there is no registry to poll. Never raises."""
    with _desk_lock:
        bag = _fresh()
        if bag["poller"] is None:
            from .. import config as C

            try:
                bag["poller"] = P.Poller(Registry(), cfg=C.load())
            except (RegistryError, C.ConfigError, OSError):
                return None
        return bag["poller"]


def inbox_folders(cfg: dict | None = None) -> list[str] | None:
    """`fleet.inbox.folders` from the config, or None for the inbox's own default.

    `ad-fleet inbox` takes `--folder`; a server started from a desktop shortcut or an IDE tool window
    has no flags to be given, so the same list has to be configuration. None rather than `[]`,
    because an empty list means "watch nothing" to `Inbox` and that is a different answer from
    "watch wherever this machine puts Downloads".
    """
    from .. import config as C

    try:
        raw = C.get(C.load() if cfg is None else cfg, "fleet.inbox.folders")
    except C.ConfigError:
        return None                          # a broken config file is `ad-doctor`'s to report
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    folders = [str(f) for f in raw if str(f).strip()]
    return folders or None


def inbox():
    """The one `Inbox`, or None when Downloads cannot be resolved. Never raises."""
    with _desk_lock:
        bag = _fresh()
        if bag["inbox"] is None:
            try:
                bag["inbox"] = IN.Inbox(folders=inbox_folders())
            except (RegistryError, IN.InboxError, OSError):
                return None
        return bag["inbox"]


def catalogue():
    """The one `Catalogue`, or None when the sqlite file cannot be opened.

    A half-written catalogue is a real laptop failure -- OneDrive syncing `~/.agentdata` mid-write is
    enough -- and the page must degrade to "search is unavailable, run `ad-fleet index`" rather than
    500 on every tile.
    """
    import sqlite3

    with _desk_lock:
        bag = _fresh()
        if bag["catalogue"] is None:
            try:
                bag["catalogue"] = CAT.Catalogue.open()
            except (sqlite3.Error, CAT.CatalogueError, OSError):
                return None
        return bag["catalogue"]


def poll_tick(now: float | None = None) -> list[dict]:
    """Tick the shared poller if it is due, and return the events that produced. Never raises.

    Rate-limited here rather than inside `Poller`, because the thing being limited is *this* page:
    every open SSE connection runs the same loop, and the poller's own per-source intervals would
    still let four windows ask four times as often as one.
    """
    now = time.time() if now is None else float(now)
    with _desk_lock:
        bag = _fresh()
        if now - bag["last_tick"] < POLL_EVERY_S:
            return []
        bag["last_tick"] = now
    live = poller()
    if live is None:
        return []
    try:
        return live.tick(now)
    except Exception:                        # noqa: BLE001 - a poll must never kill the stream
        from ..log import debug_exc

        debug_exc("fleet poll tick")
        return []


def fold_due(now: float | None = None) -> bool:
    """True at most once every `FOLD_EVERY_S`, for the whole process. Claims the slot when it says so.

    The same rate limit `poll_tick` applies to the poller, applied to `E.refresh` and for the same
    reason: the thing being limited is *this page*, and every open SSE connection runs the same loop.
    Four windows on four screens (#133) folded four times a tick, which for a dozen repositories was
    a hundred-odd `state.json` and cursor reads a second on a laptop whose antivirus is in the
    `open()` path -- all of it re-reading files that had not changed since the window next to it
    looked. One fold per floor between them; the frames it produced still go out on every tick.
    """
    now = time.time() if now is None else float(now)
    with _desk_lock:
        bag = _fresh()
        if now - bag["last_fold"] < FOLD_EVERY_S:
            return False
        bag["last_fold"] = now
        return True


def poll_state(name: str) -> dict:
    """`{ticket, pr, refresh, git}` for one tile, as JSON. `{}` when polling is not running.

    Each cell carries the last value it actually obtained, its age, and the error that greyed it.
    The page shows all three: a cell that blanked on a failed poll would lose what was known, and one
    that kept the value without the age would look current. Grey plus an age is the honest answer.
    """
    live = poller()
    if live is None:
        return {}
    try:
        return {cell: poll.to_json() for cell, poll in live.state_for(name).items()}
    except Exception:                        # noqa: BLE001 - see poll_tick
        return {}


def desk_state() -> dict:
    """What every window agrees on: the selected project, screen pinning, and tile arrangement."""
    with _desk_lock:
        arr = _selection.get("arrangement") or {}
        return {
            "selected": _selection["selected"],
            "screens": list(_selection["screens"]),
            "version": _selection["version"],
            "at": _selection["at"],
            "arrangement": {
                k: dict(v) if isinstance(v, dict) else v for k, v in arr.items()
            },
        }


def select(selected=None, screens=None) -> dict:
    """Set the shared selection and/or the screen pinning, bumping the version the stream watches.

    Returns the new state whether or not anything changed, because the caller is a button and "your
    click did nothing" is not a useful answer. The version only moves on a real change, so two
    windows clicking the same tile do not each wake the other.
    """
    with _desk_lock:
        after = dict(_selection)
        if selected is not None:
            after["selected"] = str(selected or "")
        if screens is not None:
            after["screens"] = [str(x) for x in list(screens)[:9] if str(x)]
        if (after["selected"], after["screens"]) != (_selection["selected"], _selection["screens"]):
            _selection.update(after, version=_selection["version"] + 1, at=E.stamp())
            _save_desk()
        return desk_state()


def arrange(layout: str, *, order=None, size=None, pinned=None) -> dict:
    """Set the tile arrangement for a layout, persisted in desk.json and pushed down the SSE stream."""
    with _desk_lock:
        arr = _selection.setdefault("arrangement", {})
        cur = arr.setdefault(layout, {"order": [], "size": {}, "pinned": []})
        changed = False
        if order is not None and cur.get("order") != list(order):
            cur["order"] = [str(x) for x in order]
            changed = True
        if size is not None and cur.get("size") != dict(size):
            cur["size"] = {str(k): int(v) for k, v in size.items()}
            changed = True
        if pinned is not None and cur.get("pinned") != list(pinned):
            cur["pinned"] = [str(x) for x in pinned]
            changed = True
        if changed:
            _selection["version"] += 1
            _selection["at"] = E.stamp()
            _save_desk()
        return desk_state()



# ---------------------------------------------------------------------------- the verify pane


def _verify_tool(name: str) -> str:
    """Which command wrote a file with this name, or "" -- the allow-list, matched on the name."""
    import fnmatch

    for pattern, tool in VERIFY_KINDS:
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            return tool
    return ""


def verify_for(repo, *, head: int = VERIFY_HEAD, limit: int = DESK_LIMIT) -> dict:
    """The newest `ad-uat` / `ad-pbip` summary **this** repository's own agent wrote, and no other.

    #131.4: the operator's "go and look at the chart" should be a click with the numbers already
    beside it, so the pane carries the head of the summary next to the report link. Three rules make
    that safe. The directory is not walked, so nothing under `.agent/out/shots/` or a nested checkout
    is reachable. Every candidate is resolved with `realpath` and refused unless it is still inside
    this repo's `.agent/out/` -- a symlink or an NTFS junction dropped in there is the one way a file
    from another project could otherwise appear on this tile, which AGENTS.md rule 3 forbids. And the
    excerpt is run past `catalogue.looks_like_a_credential` before it leaves the process, because a
    summary is a file we did not write.
    """
    root = os.path.join(getattr(repo, "path", "") or "", *VERIFY_DIR)
    real_root = textio.norm_path(os.path.realpath(root))
    rows: list[dict] = []
    refused: list[dict] = []
    try:
        with os.scandir(textio.longpath(root)) as it:
            entries = list(it)
    except OSError:
        entries = []                          # no `.agent/out/` yet: nothing has been verified
    for entry in entries:
        tool = _verify_tool(entry.name)
        if not tool:
            continue
        path = os.path.join(root, entry.name)
        real = textio.norm_path(os.path.realpath(path))
        if real != real_root + "/" + entry.name:
            # A link out of the repository. Named, not silently dropped: the operator should know
            # their `.agent/out/` has a door in it.
            refused.append({"name": entry.name,
                            "why": "refused: it resolves outside this repository's .agent/out/"})
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        rows.append({"name": entry.name, "tool": tool, "path": textio.norm_path(path),
                     "mtime": st.st_mtime, "bytes": int(st.st_size),
                     "age_s": round(max(0.0, time.time() - st.st_mtime), 1)})
    rows.sort(key=lambda r: (-r["mtime"], r["name"]))
    latest = dict(rows[0]) if rows else {}
    if latest:
        latest["excerpt"] = _excerpt(latest["path"], head)
    return {"repo": getattr(repo, "name", ""), "dir": "/".join(VERIFY_DIR), "found": len(rows),
            "latest": latest, "others": [{k: r[k] for k in ("name", "tool", "age_s", "path")}
                                         for r in rows[1:limit]], "refused": refused}


def _excerpt(path: str, head: int) -> str:
    """The first `head` characters, or the reason there are none. Never a credential.

    Read as bytes and cut, rather than `textio.read_text`: a findings TSV can be tens of megabytes
    and this runs while the operator is looking at a tile.
    """
    try:
        with open(textio.longpath(path), "rb") as f:
            raw = f.read(head * 4)
    except OSError as e:
        return f"(cannot read it: {e.strerror or e})"
    body = textio.decode(raw)[:head]
    found = CAT.looks_like_a_credential(body)
    if found:
        return (f"(not shown: this file has something that looks like a {found}; "
                f"open it yourself and take it out)")
    return body


# ------------------------------------------------------------------------ what one project is


def tile_facts(facts: dict) -> dict:
    """The subset of a project's fact block that may cross to the browser: `LINK_FACTS`, in order.

    Read `catalogue.LINK_FACTS` rather than restating it, so that adding a link fact is one edit in
    one place. The whole point of the list is that it is the *only* thing a tile needs -- everything
    else in `AGENTS.md` is there for the repo's own agent, and a `\\\\share\\dpm\\runs` path or a
    Teradata hostname on a tile is a leak the moment the operator screenshots the dashboard.

    Not a `looks_secret()` call: that rule drops keys *ending* in token/secret/password/api_key/pat,
    which is the right rule for a config file full of credentials and the wrong one here, where the
    keys that must not travel (`td_host`, `dpm_share`, `sql_user`, `tabular_editor`) look perfectly
    innocent. An allow-list is the only filter that holds against a fact block nobody has seen yet.
    """
    return {k: facts[k] for k in CAT.LINK_FACTS if facts.get(k)}


def show_for(name: str) -> dict:
    """The "what is this project" panel: the catalogue's facts, the link rail, the cells, the tray.

    Every half degrades on its own. An unindexed repository still gets a link rail, because the facts
    come from its own `AGENTS.md` either way and a tile with no links until somebody runs
    `ad-fleet index` is a tile that looks broken. A repository with no `.agent/out/` still gets its
    ticket cell. The panel says `indexed: false` rather than pretending.

    **The facts that leave here are `catalogue.LINK_FACTS` and nothing else.** The rail is still
    built from the whole block -- `links.links_for()` is server side and may grow a key -- but what
    crosses to the browser is the allow-list, for the reason `LINK_FACTS` is declared: a fact block
    is hand-edited prose, and a real one carries `td_host`, `dpm_share`, `sql_user` and the local
    TabularEditor path. `config.looks_secret()` does not drop those (it matches keys *ending* in
    token/secret/password/api_key/pat), so without this filter the first thing a tile does with an
    RDSD checkout is put a Teradata hostname on a page the operator screenshots into a ticket.
    """
    repo = Registry().get(name)               # raises RegistryError, which the route turns into 409
    cat = catalogue()
    facts, shown, indexed = {}, {}, False
    if cat is not None:
        try:
            shown = cat.show(name)
            facts, indexed = shown.get("facts") or {}, True
        except CAT.CatalogueError:
            shown = {}
    if not facts:
        # The same allow-listed read the index does, secret-looking keys dropped by the same rule --
        # duplicating that filter here is how the two would eventually disagree.
        facts = CAT._facts(repo.path)
    state = repo.state()
    rail = LK.links_for(repo, facts, state)
    return {"project": name, "name": name, "path": textio.norm_path(repo.path),
            "indexed": indexed, "jira_project": repo.jira_project,
            "branch": shown.get("branch", ""), "last_indexed": shown.get("last_indexed", ""),
            "facts": tile_facts(facts), "state": state,
            "friction": (shown.get("friction") or [])[:DESK_LIMIT],
            "pbip": shown.get("pbip") or [],
            "links": LK.present(rail), "missing": [r for r in rail if not r.get("url")],
            "missing_keys": LK.missing_keys(rail),
            "polls": poll_state(name), "verify": verify_for(repo)}


def desk_snapshot() -> dict:
    """Every project's panel, plus the trays, in one request.

    One round trip rather than one per tile: the grid layout draws N tiles at once and #133 puts them
    on a screen the operator is not looking at, so the page asks for the lot on a slow cadence and
    lets the SSE stream carry what is urgent.
    """
    projects, order = {}, []
    try:
        names = [r.name for r in Registry().sorted()]
    except RegistryError:
        names = []
    for name in names:
        try:
            projects[name] = show_for(name)
            order.append(name)
        except (RegistryError, OSError):
            continue
    cat = catalogue()
    return {"projects": projects, "order": order, "desk": desk_state(),
            "catalogue": cat.stats() if cat is not None else
                         {"projects": 0, "docs": 0, "fts": False,
                          "error": "the catalogue could not be opened; run `ad-fleet index`"},
            **inbox_snapshot()}


def inbox_snapshot() -> dict:
    """The three trays #132 asks for: offered per project, unsorted, and listed-but-not-offered.

    The split is the inbox's own, not a second opinion: `offered` with a project is a tile's row,
    `offered` with none is the unsorted tray, and the rest are shown with the reason so a file that
    did not appear is never a silence.
    """
    box = inbox()
    if box is None:
        return {"folders": [], "offers": {}, "unsorted": [], "not_offered": [], "still_writing": []}
    try:
        found = box.look()
    except OSError:
        found = []
    offers: dict[str, list] = {}
    unsorted, refused = [], []
    for offer in found:
        row = offer.to_json()
        if not offer.offered:
            refused.append(row)
        elif offer.project:
            offers.setdefault(offer.project, []).append(row)
        else:
            unsorted.append(row)
    return {"folders": list(box.folders), "offers": offers,
            "unsorted": unsorted[:MAX_TRAY], "not_offered": refused[:MAX_TRAY],
            "still_writing": list(box.retry)}


def _offer(id: str):
    """`(inbox, offer)` for this id from a fresh look, or a refusal naming what happened to it.

    Deliberately re-looked rather than remembered from the last `/api/desk`: between the page drawing
    a row and the operator clicking it, the file can be moved, finished downloading, or replaced by a
    newer save -- and attaching whatever used to be at that path is exactly the wrong answer.
    """
    box = inbox()
    if box is None:
        raise IN.InboxError("there is no inbox to attach from",
                            "set `fleet.inbox.folders` or check that Downloads exists")
    for offer in box.look():
        if offer.id == id:
            return box, offer
    raise IN.InboxError(f"no file with id {id!r} in the inbox now",
                        "it was moved, renamed or re-saved; reload the tray and try again")


def act(what: str, body: dict) -> dict:
    """One action. The same function the CLI verb calls, so the two cannot drift apart."""
    repo = str(body.get("repo") or "")
    if what == "start":
        from .. import config as C

        lock = supervisor.start(repo, key=body.get("ticket") or None,
                                prompt=body.get("prompt") or None,
                                force=bool(body.get("force")), cfg=C.load(),
                                cross_project=bool(body.get("cross_project")),
                                board_rows=(B.read_cache() or {}).get("rows") or [])
        return {"repo": repo, "pid": lock["pid"], "ticket": lock.get("ticket", ""),
                "summary": lock.get("summary", "")}
    if what == "send":
        from .. import config as C

        message = str(body.get("message") or "").strip()
        if not message:
            raise ServeError("nothing to send", "type a message first")
        lock = supervisor.send(repo, message, cfg=C.load())
        return {"repo": repo, "pid": lock["pid"]}
    if what == "stop":
        return supervisor.stop(repo)
    if what in ("approve", "deny"):
        id = str(body.get("id") or "")
        state = approval.APPROVED if what == "approve" else approval.DENIED
        return approval.decide(id, state, reason=str(body.get("reason") or ""))
    if what == "select":
        # The one "action" that changes nothing on disk. It is a POST rather than a query parameter
        # because its whole point is that the *other* windows hear about it (#133 layout B).
        return select(selected=body.get("repo"), screens=body.get("screens"))
    if what == "arrange":
        return arrange(str(body.get("layout") or "grid"),
                       order=body.get("order"),
                       size=body.get("size"),
                       pinned=body.get("pinned"))
    if what == "attach":
        # The single exception in the epic's "nothing is written outside ~/.agentdata/fleet without
        # a click": this is the click. `Inbox.attach` does the copy and holds the rule that it lands
        # inside `<repo>/.agent/in/` and nowhere else.
        box, offer = _offer(str(body.get("id") or ""))
        return box.attach(offer, repo)
    if what == "dismiss":
        box, offer = _offer(str(body.get("id") or ""))
        box.dismiss(offer)
        return {"dismissed": offer.name, "id": offer.id}
    raise ServeError(f"unknown action {what!r}",
                     "start | send | stop | approve | deny | select | arrange | attach | dismiss")


def _sweep(url: str) -> list[dict]:
    """Run the notification rules. Never raises: a notifier that can kill the event stream is worse
    than one that stays quiet, and the tiles carry the same information either way."""
    try:
        from .. import config as C

        return N.sweep(cfg=C.load(), url=url)
    except Exception:                        # noqa: BLE001 - see the docstring
        from ..log import debug_exc

        debug_exc("fleet notify sweep")
        return []


def _cursors(raw: str) -> dict:
    """`luna:12,other:4` -> {'luna': 12, 'other': 4}. The SSE resume point, per agent.

    One number across every agent would be wrong: each agent's `seq` is dense and its own, so a
    shared cursor replays one stream and skips another.
    """
    out = {}
    for part in (raw or "").split(","):
        name, _, seq = part.partition(":")
        if name.strip() and seq.strip().isdigit():
            out[name.strip()] = int(seq)
    return out


def stream_events(cursors: dict, stop: threading.Event, write, *, heartbeat: float = HEARTBEAT_S,
                  tick: float = TICK_S, once: bool = False, url: str = "",
                  notify_every: float = NOTIFY_EVERY_S, polls: bool = True) -> None:
    """Multiplex every agent's new events onto one SSE connection until the client goes away.

    `write` raises when the socket closes, which is how this ends -- a browser tab being shut is
    the normal case, not an error.

    The notification sweep (#97) rides on the same loop but at its own, slower cadence: the rules
    are about state *changes*, which do not happen four times a second, and each sweep writes the
    dedupe ledger to disk.

    The project poll (#131) rides on it too. `poll_tick` is rate-limited for the whole process, so
    the four windows of #133 cost one poll between them rather than four; the events it produces are
    appended to the repo's own stream by the poller and reach the tile through the loop below like
    any other, which is why there is no second code path for `project.ticket_changed`.

    **What is per tick and what is per fold.** Reading each agent's stream and writing the frames a
    connection has not seen is per tick, because that is the connection's own cursor and nothing
    else can do it. Folding raw agent output into that stream (`E.refresh`) is disk work whose
    answer is the same for every window, so it is behind `fold_due()` -- see `FOLD_EVERY_S`. The
    registry is read once per tick rather than once per repository, for the same reason.

    The shared selection (#133 layout B) is pushed as its own frame whenever its version moves. A
    connection starts at -1 so every new window is told the current selection immediately -- a
    monitor that joined late and shows a different project than the one beside it is the exact
    failure this frame exists to prevent.
    """
    last_beat = 0.0
    last_sweep = 0.0
    seen_selection = -1
    while not stop.is_set():
        if polls:
            poll_tick()
        if time.time() - last_sweep >= notify_every:
            last_sweep = time.time()
            for item in _sweep(url):
                write(f"event: notify\ndata: {json.dumps(item, ensure_ascii=False)}\n\n")
        try:
            # One registry read per tick, not one per repository plus one: `Registry()` parses
            # `registry.json` in its constructor, so the old `Registry().get(name)` inside the loop
            # re-read and re-parsed the whole file once per tile, per tick, per window.
            repos = Registry().sorted()
        except RegistryError:
            repos = []
        fold = fold_due()
        sent = False
        for repo in repos:
            name = repo.name
            if fold:
                try:
                    E.refresh(name, repo.path, repo_state=repo.state())
                except (RegistryError, OSError):
                    pass
            for ev in E.read(name, since=cursors.get(name, 0)):
                cursors[name] = ev["seq"]
                write(f"id: {name}:{ev['seq']}\nevent: agent\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n")
                sent = True
        state = desk_state()
        if state["version"] != seen_selection:
            # After the agent frames, not before: a window that has just connected wants the events
            # it missed first, and the selection is what it draws *with* them.
            seen_selection = state["version"]
            write(f"event: desk\ndata: {json.dumps(state, ensure_ascii=False)}\n\n")
            sent = True
        if sent or time.time() - last_beat > heartbeat:
            # The heartbeat is not decoration: a proxy that sees no bytes for a minute closes the
            # connection, and the tiles then quietly stop updating with no error anywhere.
            write(f"event: tick\ndata: {json.dumps({'at': time.strftime('%H:%M:%S')})}\n\n")
            last_beat = time.time()
        if once:
            return
        stop.wait(tick)


# ------------------------------------------------------------------------------------ the server


class Handler(BaseHTTPRequestHandler):
    server_version = "ad-fleet"
    sys_version = ""
    token = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):       # noqa: A003 - stdlib's name
        """Silence. The console running the server is the operator's, not a request log."""

    # ------------------------------------------------------------------ plumbing

    def _authorized(self, query: dict) -> bool:
        host = (self.client_address[0] or "").strip("[]")
        if host not in LOOPBACK:
            return False
        given = (query.get("t") or [""])[0]
        return bool(self.token) and hmac.compare_digest(given, self.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _refuse(self, code: int, error: str, hint: str = "") -> None:
        self._json({"ok": False, "error": error, "hint": hint}, code)

    # ---------------------------------------------------------------------- GET

    def do_GET(self) -> None:                # noqa: N802 - stdlib's name
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path.rstrip("/") or "/"

        # Two routes answer without the token, and both are loopback-only like everything else.
        #
        # `/api/ping` says only that ad-fleet is listening. A launcher has to know that before it
        # decides whether to start a second server, and it holds no token to ask with.
        #
        # `/open` redirects to the real, tokened URL. A per-run token cannot be written into a VS
        # Code keybinding or a PyCharm External Tool, so without this there is no stable address to
        # embed anywhere -- and #99's whole premise is embedding with nothing installed. It is not
        # a hole: any local process can already read `~/.agentdata/fleet/serve.json`, and a
        # cross-origin page that navigates a window here cannot read where it landed.
        if route in ("/api/ping", "/open") and (self.client_address[0] or "").strip("[]") in LOOPBACK:
            if route == "/api/ping":
                from ..version import version_string

                # The shells (#100) check this against their own and raise one balloon on a
                # mismatch. It rides on `ping` rather than a route of its own because a shell that
                # is already asking "are you there" should not need a second round trip to find out
                # "and are we the same age".
                return self._json({"ok": True, "service": "ad-fleet",
                                   "port": self.server.server_address[1],
                                   "version": version_string().split()[1],
                                   "contract": CONTRACT})
            self.send_response(302)
            self.send_header("Location", f"/?t={self.token}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        if not self._authorized(query):
            # Deliberately the same answer for a bad token and a non-loopback caller: neither is
            # told which of the two it got wrong.
            return self._refuse(403, "not authorized",
                                "open the URL `ad-fleet serve` printed, token and all")
        if route == "/":
            return self._index()
        if route == "/api/fleet":
            return self._json({"ok": True, **fleet_snapshot()})
        if route == "/api/themes":
            return self._json({"ok": True, "themes": themes()})
        if route == "/api/board":
            from .. import config as C

            force = (query.get("refresh") or [""])[0] in ("1", "true", "yes")
            try:
                data = B.board(cfg=C.load(), force=force)
            except B.BoardError as e:
                # 200 with ok:false, not a 5xx: the panel has to render the reason, and a bad JQL
                # is the operator's typo rather than a server fault.
                return self._json({"ok": False, "error": e.msg, "hint": e.hint, "rows": []})
            return self._json({"ok": True, "jql": data["jql"], "cached": data["cached"],
                               "age_s": data["age_s"],
                               "rows": B.with_suggestions(data["rows"])})
        if route == "/api/history":
            since = (query.get("since") or ["7d"])[0]
            return self._json({"ok": True, "since": since,
                               "runs": B.history(since=B.since_seconds(since))})
        if route == "/api/notifications":
            try:
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            from .. import config as C

            return self._json({"ok": True, "notifications": N.read_log(limit),
                               "toast": N.toast_status(C.load()),
                               "settings": N.settings(C.load())})
        if route == "/api/desk":
            return self._json({"ok": True, **desk_snapshot()})
        if route == "/api/show":
            project = (query.get("project") or [""])[0]
            try:
                return self._json({"ok": True, **show_for(project)})
            except RegistryError as e:
                # 200 with ok:false like `/api/board`: a panel has to render the reason, and asking
                # about a repository that was unregistered in another window is not a server fault.
                return self._json({"ok": False, "error": e.msg, "hint": e.hint,
                                   "project": project})
        if route == "/api/inbox":
            return self._json({"ok": True, **inbox_snapshot()})
        if route == "/api/where":
            cat = catalogue()
            if cat is None:
                return self._json({"ok": False, "results": [], "fts": False,
                                   "error": "the catalogue could not be opened",
                                   "hint": f"delete {os.path.join(fleet_dir(), CAT.CATALOGUE)} "
                                           "and run `ad-fleet index`; it is a cache"})
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except ValueError:
                limit = 20
            q = (query.get("q") or [""])[0]
            return self._json({"ok": True, "query": q, "fts": cat.fts,
                               "results": cat.where(q, limit) if q.strip() else []})
        if route == "/api/events":
            return self._sse(query)
        if route.startswith("/static/"):
            return self._static(route[len("/static/"):])
        return self._refuse(404, f"no route {route}")

    def _index(self) -> None:
        """The page, with its own asset URLs carrying this run's token.

        Everything but `/api/ping` and `/open` requires the token, and a relative `href` does not
        inherit the query string the operator opened -- so the page asked for `/static/app.css` and
        `/static/app.js` with no token and was refused, and the dashboard rendered as unstyled HTML
        with no behaviour at all. Every test missed it because a test fetches an asset directly with
        the token already in hand; only a browser asks the way the page asks, and nothing in CI is a
        browser. Found by screenshotting the real server.

        The token is put on here rather than written into the file because it is generated per run.
        `app.js` needs no help: it reads `t` out of `location.search` and puts it on every fetch of
        its own.
        """
        html = textio.read_text(os.path.join(STATIC, "index.html"))
        for asset in ASSETS:
            html = html.replace(f'"/static/{asset}"', f'"/static/{asset}?t={self.token}"')
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, name: str) -> None:
        """One file out of the package's `static/` directory, and nothing above or beside it.

        The containment check compares against `STATIC` *plus a separator* (`os.path.join(x, "")`).
        A bare `startswith(STATIC)` is a prefix match on a string, not a check that the path is
        inside the directory: it accepts every sibling whose name merely starts with `static`, so
        `/static/../static_backup/app.js` -- or one day a `static_secrets/` somebody mkdirs beside
        the package -- resolves outside and is served. Nothing in the tree is named that today,
        which is exactly why this would be found by an attacker rather than by a test.
        """
        root = os.path.join(STATIC, "")      # the directory, with its trailing separator
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(root) or not os.path.isfile(path):
            return self._refuse(404, f"no file {name}")
        with open(path, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype)

    def _sse(self, query: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        cursors = _cursors((query.get("since") or [""])[0] or self.headers.get("Last-Event-ID", ""))

        def write(chunk: str) -> None:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        url = f"http://127.0.0.1:{self.server.server_address[1]}/?t={self.token}"
        try:
            stream_events(cursors, getattr(self.server, "stopping", threading.Event()), write,
                          url=url)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                              # the tab was closed. Not an error.
        self.close_connection = True

    # --------------------------------------------------------------------- POST

    def do_POST(self) -> None:               # noqa: N802 - stdlib's name
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorized(query):
            return self._refuse(403, "not authorized", "open the URL `ad-fleet serve` printed")
        route = url.path.rstrip("/")
        if not route.startswith("/api/"):
            return self._refuse(404, f"no route {route}")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._refuse(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._refuse(400, "body is not JSON")
        if not isinstance(body, dict):
            return self._refuse(400, "body must be a JSON object")
        what = route[len("/api/"):]
        try:
            return self._json({"ok": True, "action": what, **act(what, body)})
        except (ServeError, RegistryError, supervisor.SupervisorError,
                approval.ApprovalError, IN.InboxError, CAT.CatalogueError) as e:
            # The same refusal the CLI gives, with the same hint. One vocabulary.
            return self._refuse(409, e.msg, getattr(e, "hint", ""))
        except Exception as e:               # noqa: BLE001 - a button must never 500 silently
            from ..log import debug_exc

            debug_exc("fleet serve action")
            return self._refuse(500, str(e)[:300], "check the console running `ad-fleet serve`")


# ------------------------------------------------------------------------------------- the theme


def themes() -> list[dict]:
    """The PyCharm `.icls` palettes, so the tool window can match the editor beside it.

    Status colours are deliberately NOT themed: a chip that means "needs you" must be the same red
    in every palette, or the colour stops being information.
    """
    import xml.etree.ElementTree as ET

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "themes", "pycharm")
    keys = {"bg": "CONSOLE_BACKGROUND_KEY", "panel": "CARET_ROW_COLOR", "text": "CARET_COLOR",
            "muted": "ANNOTATIONS_COLOR", "accent": "DOC_COMMENT_LINK", "line": "DOC_COMMENT_GUIDE",
            "select": "SELECTION_BACKGROUND"}
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not name.endswith(".icls"):
            continue
        try:
            tree = ET.parse(os.path.join(root, name))
        except (ET.ParseError, OSError):
            continue
        found = {o.get("name"): o.get("value") for o in tree.iter("option") if o.get("value")}
        palette = {k: "#" + found[v] for k, v in keys.items() if found.get(v)}
        if len(palette) == len(keys):
            out.append({"name": os.path.splitext(name)[0], "colors": palette})
    return out


# -------------------------------------------------------------------------------- starting it up


def serve_file() -> str:
    return os.path.join(fleet_dir(), SERVE_FILE)


def build(port: int = 8765, *, token: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    """Bind and return the server, without serving. `port=0` picks a free one."""
    handler = type("BoundHandler", (Handler,), {"token": token or secrets.token_urlsafe(24)})

    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR permits two *live* sockets on one port, so a second
        # `ad-fleet serve --port 8765` would bind happily and the two would split requests at
        # random. On POSIX the same flag only shortens TIME_WAIT, which is worth keeping.
        allow_reuse_address = os.name != "nt"

    try:
        server = Server(("127.0.0.1", port), handler)
    except OSError as e:
        raise ServeError(f"cannot bind 127.0.0.1:{port} ({e})",
                         "something else is on that port; `ad-fleet serve --port 0` picks a free one") from None
    server.daemon_threads = True             # Ctrl-C must not wait on an open SSE connection
    server.stopping = threading.Event()
    return server, handler.token


def url_for(server: ThreadingHTTPServer, token: str) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/?t={token}"


def record(server: ThreadingHTTPServer, token: str) -> str:
    """Write where the page is, so the IDE shells (#99, #100) can find it without being told."""
    return textio.write_json(serve_file(), {"url": url_for(server, token), "token": token,
                                            "port": server.server_address[1], "pid": os.getpid(),
                                            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())})


def forget() -> None:
    try:
        os.remove(serve_file())
    except OSError:
        pass


def run(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        forget()
        reset()          # the poller, the inbox and the catalogue handle are this run's, not the next's
