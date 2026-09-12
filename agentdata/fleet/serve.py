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
import calendar
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .. import textio
from . import (agentstate, approval, board as B, catalogue as CAT, events as E, handoff as HO,
               inbox as IN, lifecycle, links as LK, notify as N, poll as P, supervisor)
from .registry import Registry, RegistryError, fleet_dir
from .scope import ScopeError as SCOPE_ERROR

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


# A relative URL inside a stylesheet does not inherit the query string the stylesheet was fetched
# with -- the same rule that once made the page render as unstyled HTML, one level down. A skin
# referencing its own `sprites.svg` therefore asked for it with no token and was refused with a
# 403, silently: the chips simply had no status sprite, and nothing said why. The token goes on
# here for the same reason `_index` puts it on the page's own assets, and it goes BEFORE the
# fragment, because `sprites.svg#crop-sun?t=…` names no fragment at all.
_CSS_URL = re.compile(r"""url\(\s*(['"]?)(?!data:|https?:|//|/)([^'")#\s]+)(#[^'")\s]*)?\1\s*\)""")


def _tokenize_css_urls(css: str, token: str) -> str:
    """Put this run's token on every relative `url()` in a stylesheet."""
    def one(m: "re.Match[str]") -> str:
        quote, target, fragment = m.group(1), m.group(2), m.group(3) or ""
        joiner = "&" if "?" in target else "?"
        return f"url({quote}{target}{joiner}t={token}{fragment}{quote})"
    return _CSS_URL.sub(one, css)


class ServeError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = "", hint_code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        # The structured refusal every 409 carries (#163), so the page switches on a code rather
        # than matching a regex against prose that anyone may reword.
        self.code = code or hint_code


# --------------------------------------------------------------------------------- the API layer


# When this process started, so a tile can say whether its run belongs to the session the operator
# is looking at or to one from before they sat down. `E.stamp()` is UTC, second resolution, and the
# whole stream already agrees on it.
SERVER_STARTED = E.stamp()


def age_of_stamp(stamp: str) -> int:
    """Seconds since an `events.stamp()` timestamp, or -1 when there is nothing to measure.

    The supervisor only knows the age of the log it is tailing, so it answers -1 for every agent it
    is not currently running -- which is most of them, most of the time, and is why every chip on
    the page rendered with an empty age. The fold already carries the timestamp of the last event
    it saw (`classify()` returns it as `at`); this turns that into the number the tile shows.

    `calendar.timegm`, not `time.mktime`: the stamps are UTC and mktime would read them as local.
    """
    if not stamp:
        return -1
    try:
        return max(0, int(time.time() - calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))))
    except (ValueError, TypeError):
        return -1


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


def stream_runs(stream: list[dict]) -> list[list[dict]]:
    """The stream cut into runs, a run beginning at every `started` event.

    The same cut `split_runs` and `sessions.fold_stream` make. It is here as one function because
    the switcher (#174) needs a third caller of it, and three private copies of "where does a run
    begin" is how the tile and the report came to count different things.
    """
    from . import runs as R

    starts = [i for i, ev in enumerate(stream) if R.is_run_start(ev)]
    if not starts:
        return [list(stream)] if stream else []
    return [stream[start:(starts[i + 1] if i + 1 < len(starts) else len(stream))]
            for i, start in enumerate(starts)]


def run_session(run_events: list[dict]) -> str:
    """Which session a run belongs to: the id it announced, or the one it was resumed onto."""
    for ev in run_events:
        if ev.get("kind") == "session_id":
            sid = str((ev.get("data") or {}).get("session") or "")
            if sid:
                return sid
    first = run_events[0] if run_events else {}
    return str((first.get("data") or {}).get("session") or "")


def transcript_for(name: str, session: str, *, limit: int = 200,
                   before: int = 0) -> dict:
    """One session's transcript, read from history and paged backwards (#174).

    A session is **not** a contiguous slice of the stream: `--resume` opens a new run on the same
    conversation, and runs of other sessions can sit between them. Runs are therefore chosen by the
    id they carry rather than by where they are, which is also why this cannot be done by slicing
    `earlier[]`.

    Paged from the end, because that is the end an operator reads first: `before` is a `seq` to stop
    short of, and `cursor` comes back as the `before` for the page above this one.
    """
    stream = E.read(name)
    picked: list[dict] = []
    for run in stream_runs(stream):
        if run_session(run) == session:
            picked.extend(run)
    if before:
        picked = [ev for ev in picked if int(ev.get("seq") or 0) < before]
    more = len(picked) > limit
    page = picked[-limit:] if limit > 0 else picked
    cursor = int(page[0].get("seq") or 0) if page else 0
    derived = agentstate.derive(picked, live=False) if picked else {}
    return {"repo": name, "session": session, "events": page, "more": more,
            "cursor": cursor, "total": len(picked),
            "runs": sum(1 for run in stream_runs(stream) if run_session(run) == session),
            "state": derived.get("state", ""), "why": derived.get("why", ""),
            "ticket": derived.get("ticket", ""),
            "at": derived.get("at", "")}


def split_runs(stream: list[dict], live: bool = False) -> tuple[dict, list[dict]]:
    """Split an event stream into the current run and earlier runs summary.

    A run begins at a 'started' event.
    Returns:
        (current_run_dict, earlier_runs_list)
    """
    from . import runs as R

    if not stream:
        return ({"n": 0, "started": "", "resumed": False, "session": "",
                 "session_title": "", "ticket": "", "live": live, "events": []}, [])

    started_indices = [i for i, ev in enumerate(stream) if R.is_run_start(ev)]
    repo_name = stream[0].get("repo", "") if stream else ""
    if not started_indices:
        d = agentstate.derive(stream, live=live)
        return ({"n": 1, "started": stream[0].get("ts", ""), "resumed": False,
                 "session": d.get("session", ""), "session_title": "",
                 "ticket": d.get("ticket", ""), "live": live, "events": stream}, [])

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
            "session": d.get("session") or (start_ev.get("data") or {}).get("session", ""),
        })

    last_start_i = started_indices[-1]
    curr_events = stream[last_start_i:]
    curr_derived = agentstate.derive(curr_events, live=live)
    start_ev = stream[last_start_i]
    start_data = start_ev.get("data") or {}
    curr_sess = curr_derived.get("session") or start_data.get("session", "")
    curr_title = ""
    if repo_name and curr_sess:
        try:
            from . import sessions as S
            for s in S.load_sessions(repo_name):
                if s.get("id") == curr_sess:
                    curr_title = s.get("title", "")
                    break
        except Exception:
            pass

    curr_run = {
        "n": len(started_indices),
        "started": start_ev.get("ts", ""),
        # Did this run begin in the session the operator is looking at? A tile whose newest run
        # predates `ad-fleet serve` is showing history, and has to say so.
        "since_start": bool(start_ev.get("ts", "") >= SERVER_STARTED),
        "resumed": bool(start_data.get("resumed", False)),
        "session": curr_sess,
        "session_title": curr_title,
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
    from .. import config as C
    from .. import theme as T
    cfg = C.load()
    default_theme_name = cfg.get("theme", {}).get("default") or "none"
    proj_theme_map = cfg.get("theme", {}).get("projects", {})
    if not isinstance(proj_theme_map, dict):
        proj_theme_map = {}

    # Sessions the fleet did not start (#2), worked out once for the whole snapshot rather than per
    # row: the process listing behind this is a PowerShell call on Windows, and it is cached besides.
    from . import adopt as A

    try:
        offers = {c["repo"]: c for c in A.candidates(registry)}
    except Exception:                    # noqa: BLE001 - never let this stop a dashboard drawing
        offers = {}

    for row in supervisor.status():
        name = row["repo"]
        repo = None                          # rebound per row: a lookup that raised used to leave
        try:                                 # the previous row's repository in hand
            repo = registry.get(name) if registry is not None else None
            if repo is not None:
                E.refresh(name, repo.path, repo_state=repo.state())
        except (RegistryError, OSError):
            pass
        stream = E.read(name)
        is_live = bool(supervisor.live(name))
        curr_run, earlier = split_runs(stream, live=is_live)
        derived = agentstate.derive(curr_run["events"], live=is_live) if curr_run["events"] else agentstate.derive(stream, live=is_live)

        # The supervisor's age covers only the log it is tailing, so it is -1 for every agent that
        # is not running right now. The fold's own `at` covers the rest.
        last_age_s = row.get("last_event_age_s", -1)
        if last_age_s < 0:
            last_age_s = age_of_stamp(derived.get("at", ""))

        pid = row.get("pid", 0)
        # An adopted session is supervised in the sense the tile cares about -- somebody is working
        # in that checkout right now -- even where this platform would not name its pid. Requiring a
        # pid here would have every adopted Windows session draw as "nothing is supervised", which
        # is the exact lie #2 exists to remove.
        external_lock = supervisor.read_lock(name) if is_live else {}
        is_external = bool(external_lock.get("external"))
        is_supervised = bool(is_live and (pid or is_external))

        # The sentence says "nothing is supervised now". It may therefore only appear where that is
        # the WHOLE truth. An agent that stopped with a question still needs the human, and a tile
        # that says "needs you" in its chip and "nothing is supervised" in the same breath is the
        # contradiction #147 exists to remove: one of the two has to be wrong, and the operator
        # cannot tell which. So the sentence is for QUIET agents only -- done, idle, starting, and
        # a turn left open by a process that is gone. Everything `needs_the_human` covers keeps its
        # own state and its own sentence, and the age beside the chip carries the staleness.
        quiet = not agentstate.needs_the_human(derived["state"])
        if not is_supervised and quiet:
            if not stream or not curr_run["started"]:
                not_supervised_sentence = "no run yet; nothing is supervised"
            elif not curr_run.get("since_start"):
                age_text = format_age_str(last_age_s) if last_age_s >= 0 else "some time ago"
                not_supervised_sentence = f"last run ended {age_text}; nothing is supervised now"
            else:
                age_text = format_age_str(last_age_s) if last_age_s >= 0 else "recently"
                not_supervised_sentence = f"the last run ended {age_text}; nothing is supervised now"
        else:
            not_supervised_sentence = ""

        # A console that has been sitting on one tool call is, as far as anything the CLI writes
        # can say, a session asking its operator something (#190). The chip stays `running` --
        # a session *is* live -- and the sentence beside it says where to look, labelled a guess.
        if external_lock.get("kind") == "console" and derived.get("state") == "running":
            waited = age_of_stamp(agentstate.pending_tool(curr_run["events"] or stream))
            prompt_s = float(C.get(cfg, "fleet.console.prompt_s", 20) or 20)
            if waited >= prompt_s:
                derived = {**derived,
                           "why": f"waiting for you, in the console? nothing back from that tool "
                                  f"for {format_age_str(waited)}"}

        # Resolve project accent. The project key first, then this checkout's own name: two
        # working trees of one repository wear one colour (#175).
        project = repo.project if repo is not None else name
        proj_entry = (proj_theme_map.get(project) or proj_theme_map.get(name)
                      or proj_theme_map.get(os.path.abspath(row.get("path", ""))))
        if isinstance(proj_entry, dict) and "accent" in proj_entry:
            accent = proj_entry["accent"]
        elif isinstance(proj_entry, dict) and "theme" in proj_entry:
            pt = theme_or_none(proj_entry["theme"], seed=project)
            accent = pt.accent or "#3FB950"
        elif isinstance(proj_entry, str) and proj_entry:
            pt = theme_or_none(proj_entry, seed=project)
            accent = pt.accent or "#3FB950"
        else:
            pt = theme_or_none(default_theme_name, seed=name)
            accent = pt.accent or "#3FB950"

        rows.append({"repo": name, "path": row.get("path", ""),
                     # Which project this checkout is one of, and the checkouts beside it. A tile
                     # is still one working tree with one agent; the strip is how the operator gets
                     # from one to the next without hunting for its tile (#175).
                     "project": row.get("project", "") or name,
                     "worktree_of": row.get("worktree_of", ""),
                     "jira_project": row.get("jira_project", ""),
                     "accent": accent,
                     "pid": pid, "last_event_age_s": last_age_s,
                     "supervised": is_supervised,
                     # Whose session this is. `external` says the fleet adopted one it did not
                     # start; `adoptable` says there is one here it could. Never both.
                     "external": is_external,
                     "external_how": external_lock.get("how", "") if is_external else "",
                     # A console the fleet opened (#189). The reply box types into that window
                     # rather than starting a second agent beside it (#190), and the tab brings it
                     # to the front instead of opening a second one.
                     "console": ({"pid": external_lock.get("pid", 0),
                                  "session": external_lock.get("session", ""),
                                  "host": external_lock.get("host", "")}
                                 if external_lock.get("kind") == "console" else None),

                     "adoptable": offers.get(name) if not is_external else None,
                     "not_supervised_sentence": not_supervised_sentence,
                     "earlier": earlier,
                     # How many *other* sessions this checkout has, for the switcher's `earlier (n)`
                     # tab (#174). Counted off the stream that is already in hand rather than from
                     # `sessions.json`, which exists only once somebody has rebuilt it -- a tab that
                     # said `earlier (0)` over three real sessions is worse than no tab at all. The
                     # rows themselves come from `/api/sessions`, on the click.
                     "sessions_n": len({sid for sid in
                                        (run_session(run) for run in stream_runs(stream))
                                        if sid and sid != (curr_run.get("session") or "")}),
                     **derived,
                     # What it edited against what it was given (#168). Advice to the model and a
                     # report to the human: nothing here refuses an edit, it only says what happened.
                     "scope_report": _scope_report(row.get("path", ""), derived),
                     "last_seq": stream[-1]["seq"] if stream else 0,
                     "needs_human": agentstate.needs_the_human(derived["state"]),
                     # The project's own state (#131), beside the agent's. Named `polls` and not
                     # folded into the row, because a cell can be stale or grey and the agent's
                     # state never is -- flattening them would make one age apply to both.
                     "polls": poll_state(name),
                     # `run` without its events: the page needs to know WHICH run and how big it
                     # is, and it reads the transcript from `recent`. Shipping the whole current
                     # run as well meant a long-running agent's entire history was serialised on
                     # every poll -- several times a second, to every window on every screen --
                     # so that the page could take its length.
                     "run": {**curr_run, "events": None, "events_n": len(curr_run["events"])},
                     "recent": curr_run["events"][-40:] if curr_run["events"] else stream[-40:]})

    _add_siblings(rows)
    from .. import config as C

    # `fleet.preflight: false` restores #98's immediate start: a drop launches instead of opening
    # the dispatch card. Absent means on, because the card is the recoverable direction.
    return {"repos": rows, "approvals": approval.pending(), "fleet_dir": fleet_dir(),
            "desk": desk_state(), "theme": theme_state(),
            "preflight": C.get(C.load(), "fleet.preflight") is not False,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


def _add_siblings(rows: list[dict]) -> None:
    """The other checkouts of each row's project, for the switcher's strip (#175).

    A tile is still **one working tree with one agent** -- the lock, the events and the session are
    all per checkout. The strip is only how the operator gets from one to the next without hunting
    the grid for its tile, so each sibling carries just enough to be a readable tab: the branch it
    is on, the state its agent is in, and how old that is.
    """
    by_project: dict[str, list[dict]] = {}
    for row in rows:
        by_project.setdefault(row.get("project") or row["repo"], []).append(row)
    for row in rows:
        project = row.get("project") or row["repo"]
        row["siblings"] = [
            {"repo": other["repo"],
             "branch": ((other.get("polls") or {}).get("git") or {}).get("value", {}).get("branch", ""),
             "path": other.get("path", ""),
             "state": other.get("state", ""),
             "needs_human": other.get("needs_human", False),
             "age": format_age_str(other.get("last_event_age_s", -1))}
            for other in by_project.get(project, []) if other["repo"] != row["repo"]]


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
        "grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "roles": {"order": [], "hidden": []},
        "screens": {"order": [], "hidden": []},
    },
    "windows": {},
}


def _desk_file() -> str:
    return os.path.join(fleet_dir(), DESK_FILE)


_desk_loaded = False


def _ensure_desk_loaded() -> None:
    """Read `desk.json` once, on the first question anyone asks about the desk.

    It used to be read only as a side effect of the lazy handle accessor -- the one that opens the
    catalogue and the inbox watcher -- so whether the operator's saved selection and arrangement
    came back depended on which endpoint the server happened to answer first. A window that asked
    for `/api/fleet` before anything needed a catalogue handle got an empty desk and quietly lost
    the arrangement it had been given.
    """
    global _desk_loaded
    if _desk_loaded:
        return
    _desk_loaded = True
    _load_desk()


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
                wins = data.get("windows")
                if isinstance(wins, dict):
                    _selection["windows"] = {
                        k: dict(v) if isinstance(v, dict) else v for k, v in wins.items()
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
        forget_desk()
    if not _desk["dir"]:
        _load_desk()
    _desk["dir"] = here
    return _desk


def drop_handles() -> None:
    """Drop the shared handles (poller, inbox, catalogue) on shutdown.
    Preserves desk.json and selection in memory.
    """
    with _desk_lock:
        cat = _desk.get("catalogue")
        if cat is not None:
            try:
                cat.close()
            except Exception:                # noqa: BLE001 - a closed handle is the point
                pass
        _desk.update(dir="", poller=None, inbox=None, catalogue=None, last_tick=0.0,
                     last_fold=0.0)


def forget_desk() -> None:
    """Drop handles and blank selection. Called only when the fleet moves under a live process."""
    global _desk_loaded
    _desk_loaded = False
    drop_handles()
    with _desk_lock:
        _selection.update(
            selected="",
            screens=[],
            version=_selection["version"] + 1,
            at=E.stamp(),
            arrangement={
                "grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                "roles": {"order": [], "hidden": []},
                "screens": {"order": [], "hidden": []},
            },
            windows={},
        )
        _save_desk()


def reset() -> None:
    """Backwards compatibility alias for forget_desk()."""
    forget_desk()



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
    _ensure_desk_loaded()
    with _desk_lock:
        arr = _selection.get("arrangement") or {}
        wins = _selection.get("windows") or {}
        return {
            "selected": _selection["selected"],
            "screens": list(_selection["screens"]),
            "version": _selection["version"],
            "at": _selection["at"],
            "arrangement": {
                k: dict(v) if isinstance(v, dict) else v for k, v in arr.items()
            },
            "windows": {
                k: dict(v) if isinstance(v, dict) else v for k, v in wins.items()
            },
        }


def theme_or_none(name: str, seed: str = ""):
    """A palette by name, or the plain one, and never an exception.

    `theme.get()` raises on a name it does not know, and the names live in a file a person edits by
    hand and an update can rename out from under them. Unguarded, one stale `theme.default` turned
    every request for `/api/fleet` and `/api/themes` into a 500 -- the dashboard did not degrade to
    an unthemed page, it stopped answering at all. The page is the operator's window onto four
    agents; it does not get to go down over a colour.
    """
    from .. import theme as T
    if not name or name == "none":
        return T.get("none")
    try:
        return T.get(name, seed=seed) if seed else T.get(name)
    except Exception:                            # noqa: BLE001 - ThemeError, and anything after it
        return T.get("none")


def theme_state() -> dict:
    """The theme and skin configuration shared across windows."""
    from .. import config as C
    from .. import theme as T
    from . import skins
    cfg = C.load()
    default_name = cfg.get("theme", {}).get("default") or "none"
    skin_name = cfg.get("theme", {}).get("skin") or "none"

    # A skin is a rendering, not a palette: it is drawn against the one it declares as its base
    # (#154). Choosing `glass` while the palette is still "follow the system" put a skin designed
    # for a dark ground on a light one, which is unreadable rather than merely wrong. When the
    # operator has not chosen a palette, the skin's base is the honest answer.
    # Skins drive palettes (#4). A variant is a skin drawn against a particular ground -- Nether is
    # red because the art is red -- so while a skin is on, its variant's base IS the palette, and
    # not merely the fallback when the operator has not chosen one. Leaving the choice open was the
    # #154 bug with more ways to hit it: frosted glass designed for a dark ground rendered on a
    # light one is unreadable rather than merely wrong, and every extra free combination is one more
    # pairing nothing has checked the contrast of. Bound this way the set of reachable combinations
    # is exactly the set of variants, and `tests/test_fleet_skins.py` checks all of them.
    skin_info = skins.get_skin(skin_name) if skin_name and skin_name != "none" else None
    if skin_info:
        default_name = skin_info.get("base") or default_name
        skin_name = skin_info["full"]

    t = theme_or_none(default_name)
    css_vars = T.to_css(t) if t and t.name != "none" else {}
    proj_map = cfg.get("theme", {}).get("projects", {})
    if not isinstance(proj_map, dict):
        proj_map = {}
    accents = {}
    for proj, pinfo in proj_map.items():
        if isinstance(pinfo, dict) and "accent" in pinfo:
            accents[proj] = pinfo["accent"]
        elif isinstance(pinfo, dict) and "theme" in pinfo:
            pt = theme_or_none(pinfo["theme"], seed=proj)
            if pt and pt.accent:
                accents[proj] = pt.accent
        elif isinstance(pinfo, str) and pinfo:
            pt = theme_or_none(pinfo, seed=proj)
            if pt and pt.accent:
                accents[proj] = pt.accent

    return {
        "theme": default_name,
        "skin": skin_name,
        # Split out as well as joined: the page fetches one stylesheet per skin and switches the
        # variant with an attribute, so it needs the two halves without having to parse the name.
        "skin_family": skin_info["name"] if skin_info else "",
        "skin_variant": skin_info["variant"] if skin_info else "",
        "css": css_vars,
        "accents": accents,
    }


def select(selected=None, screens=None) -> dict:
    """Set the shared selection and/or the screen pinning, bumping the version the stream watches.

    Returns the new state whether or not anything changed, because the caller is a button and "your
    click did nothing" is not a useful answer. The version only moves on a real change, so two
    windows clicking the same tile do not each wake the other.
    """
    _ensure_desk_loaded()
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


def arrange(layout: str, *, order=None, size=None, pinned=None, hidden=None) -> dict:
    """Set the tile arrangement for a layout, persisted in desk.json and pushed down the SSE stream.

    `hidden` joins `order`, `size` and `pinned` (#173). Shared across windows like the rest of the
    arrangement -- whether it should be per window instead is a question for the sitting, and the
    plan says so; this is the default that ships.
    """
    _ensure_desk_loaded()
    with _desk_lock:
        arr = _selection.setdefault("arrangement", {})
        cur = arr.setdefault(layout, {"order": [], "size": {}, "pinned": [], "hidden": []})
        cur.setdefault("hidden", [])
        changed = False
        if order is not None and cur.get("order") != list(order):
            cur["order"] = [str(x) for x in order]
            changed = True
        if size is not None and cur.get("size") != dict(size):
            cur["size"] = {str(k): int(v) for k, v in size.items()}
            changed = True
        # Pinned and hidden are per *project* (#175): two working trees of one repository are one
        # piece of work, and putting half of it away -- or pinning half of it first -- is an
        # arrangement nobody asked for. Expanded here rather than in the page, so `ad-fleet hide`
        # and every open window agree by construction.
        if pinned is not None:
            want = _whole_projects(pinned)
            if cur.get("pinned") != want:
                cur["pinned"] = want
                changed = True
        if hidden is not None:
            want = _whole_projects(hidden)
            if cur.get("hidden") != want:
                cur["hidden"] = want
                changed = True
        if changed:
            _selection["version"] += 1
            _selection["at"] = E.stamp()
            _save_desk()
        return desk_state()


def _whole_projects(names) -> list[str]:
    """Every checkout of every project named here, in the order the names arrived.

    A name the registry does not know comes through untouched: an arrangement outlives a
    registration, and silently dropping a tile's place because the checkout is unregistered today
    would lose the operator's desk the moment a drive was disconnected.
    """
    wanted = [str(n) for n in names]
    try:
        repos = Registry().sorted()
    except (RegistryError, OSError):
        return wanted
    project_of = {r.name: r.project for r in repos}
    checkouts: dict[str, list[str]] = {}
    for repo in repos:
        checkouts.setdefault(repo.project, []).append(repo.name)

    out: list[str] = []
    for name in wanted:
        for member in checkouts.get(project_of.get(name, ""), [name]):
            if member not in out:
                out.append(member)
    return out


def update_window(w: str = "main", **kwargs) -> dict:
    """Set per-window state in desk.json and push down the SSE stream."""
    _ensure_desk_loaded()
    w = str(w or "main")
    with _desk_lock:
        wins = _selection.setdefault("windows", {})
        win = wins.setdefault(w, {
            "layout": "grid",
            "view": "all",
            "screen": 0,
            "focus": False,
            "zoomed": "",
            "section": "tickets",
            "held": [],
            "read": {},
            "seen": "",
        })
        changed = False
        if "layout" in kwargs and win.get("layout") != str(kwargs["layout"] or ""):
            win["layout"] = str(kwargs["layout"] or "")
            changed = True
        if "view" in kwargs and win.get("view") != str(kwargs["view"] or ""):
            win["view"] = str(kwargs["view"] or "")
            changed = True
        if "screen" in kwargs and win.get("screen") != int(kwargs["screen"] or 0):
            win["screen"] = int(kwargs["screen"] or 0)
            changed = True
        if "focus" in kwargs and win.get("focus") != bool(kwargs["focus"]):
            win["focus"] = bool(kwargs["focus"])
            changed = True
        if "zoomed" in kwargs and win.get("zoomed") != str(kwargs["zoomed"] or ""):
            win["zoomed"] = str(kwargs["zoomed"] or "")
            changed = True
        if "section" in kwargs and win.get("section") != str(kwargs["section"] or ""):
            win["section"] = str(kwargs["section"] or "")
            changed = True
        if "held" in kwargs:
            new_held = [str(x) for x in kwargs["held"] or []]
            if win.get("held") != new_held:
                win["held"] = new_held
                changed = True
        if "read" in kwargs and isinstance(kwargs["read"], dict):
            new_read = {str(k): int(v) for k, v in kwargs["read"].items()}
            if win.get("read") != new_read:
                win["read"] = new_read
                changed = True
        if "seen" in kwargs and win.get("seen") != str(kwargs["seen"] or ""):
            win["seen"] = str(kwargs["seen"] or "")
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
    cells = poll_state(name)
    # The branch from the poll's git cell, which shells out *in this checkout* and is therefore
    # already worktree-correct. The catalogue's own `branch` came from the index, and an index
    # entry is written once for a repository -- so two worktrees of it read the same branch, which
    # is the one string they most need to differ in. The catalogue's `_inside` wall (realpath every
    # read, refuse anything outside the repository) is not touched for the sake of one string.
    polled = ((cells.get("git") or {}).get("value") or {}).get("branch") or ""
    return {"project": repo.project, "name": name, "repo": name,
            "path": textio.norm_path(repo.path),
            "worktree_of": repo.worktree_of,
            "indexed": indexed, "jira_project": repo.jira_project,
            "branch": polled or shown.get("branch", ""),
            "branch_from": "poll" if polled else ("index" if shown.get("branch") else ""),
            "last_indexed": shown.get("last_indexed", ""),
            "facts": tile_facts(facts), "state": state,
            "friction": (shown.get("friction") or [])[:DESK_LIMIT],
            "pbip": shown.get("pbip") or [],
            "links": LK.present(rail), "missing": [r for r in rail if not r.get("url")],
            "missing_keys": LK.missing_keys(rail),
            "polls": cells, "verify": verify_for(repo)}


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


def _scope_report(repo_path: str, derived: dict) -> dict:
    """`edited 2 · 1 outside the scope you gave it`, or nothing when no scope was given."""
    from . import scope as SCOPE

    files = derived.get("files_modified") or []
    ticket = derived.get("ticket") or ""
    if not files or not ticket or not repo_path:
        return {}
    try:
        card = SCOPE.report(repo_path, ticket, files)
    except OSError:
        return {}
    if not card.get("given"):
        return {}
    return card


def _repo_record(name: str):
    """The registered checkout, or the refusal the CLI would give."""
    if not name:
        raise ServeError("no repository named", "pass `repo`", hint_code="wrong_repo")
    try:
        return Registry().get(name)
    except (RegistryError, KeyError):
        raise ServeError(f"{name!r} is not a registered repository",
                         "`ad-fleet repo add <path>` first, then reload",
                         hint_code="wrong_repo") from None


def _scope_cap() -> int:
    from .. import config as C

    try:
        return int(C.get(C.load(), "fleet.scope.max_hash_mb") or 64) * 1024 * 1024
    except (TypeError, ValueError):
        return 64 * 1024 * 1024


def _attach_cap() -> int:
    from .. import config as C

    try:
        return int(C.get(C.load(), "fleet.attach.max_mb") or 10) * 1024 * 1024
    except (TypeError, ValueError):
        return 10 * 1024 * 1024


def _attach_bytes(body: dict) -> dict:
    """A file that is not the repository's, copied in because the operator asked for it.

    Base64 in a JSON body rather than multipart, because the page has no build step and the server
    is `http.server`: one encoder on each side beats a parser nobody would otherwise need.
    """
    import base64

    from . import scope as SCOPE

    target = _repo_record(str(body.get("repo") or ""))
    ticket = str(body.get("ticket") or "") or (target.state().get("active_ticket") or "")
    name = textio.safe_name(os.path.basename(str(body.get("name") or "")))
    if not name:
        raise ServeError("the file has no usable name", "rename it and drop it again")
    try:
        blob = base64.b64decode(str(body.get("bytes") or ""), validate=True)
    except (ValueError, TypeError):
        raise ServeError("the upload was not readable", "drop the file again") from None
    cap = _attach_cap()
    if len(blob) > cap:
        raise ServeError(f"{name} is {len(blob) // 1024 // 1024} MB; the cap is {cap // 1024 // 1024} MB",
                         "raise `fleet.attach.max_mb`, or put the file in the checkout and drop it "
                         "from there so it is scoped rather than copied")

    folder = HO.in_dir(target.path, ticket)
    dest = os.path.join(folder, name)
    root = textio.norm_path(os.path.join(target.path, *HO.IN_DIR.split("/")))
    if not textio.norm_path(dest).startswith(root + "/"):
        raise ServeError(f"refusing to write {name} outside {HO.IN_DIR}",
                         "rename the file to something without path separators and retry")
    SCOPE._refuse_unscopable(os.path.join(HO.IN_DIR, HO.key_for(ticket), name))
    try:
        os.makedirs(textio.longpath(folder), exist_ok=True)
        with open(textio.longpath(dest), "wb") as handle:
            handle.write(blob)
    except OSError as e:
        raise ServeError(f"could not write {name}: {e.strerror or e}",
                         "check the disk and the repository's permissions") from None

    rel = textio.norm_path(os.path.join(HO.IN_DIR, HO.key_for(ticket), name))
    why = HO.ask_ad_state(target.path, rel)
    data = {"file": textio.norm_path(dest), "name": name, "dir": HO.rel_in_dir(ticket),
            "source": "drop", "size": len(blob), "project": target.name,
            "attached": True, "recorded": not why, "why": why}
    ev = E.event(target.name, IN.ATTACHED, data, ticket=ticket)
    try:
        E.append(target.name, [ev])
    except OSError:
        pass
    return {**data, **ev}


def act(what: str, body: dict) -> dict:
    """One action. The same function the CLI verb calls, so the two cannot drift apart."""
    repo = str(body.get("repo") or "")
    if what == "start":
        from .. import config as C

        lock = supervisor.start(repo, key=body.get("ticket") or None,
                                prompt=body.get("prompt") or None,
                                force=bool(body.get("force")), cfg=C.load(),
                                cross_project=bool(body.get("cross_project")),
                                board_rows=(B.read_cache() or {}).get("rows") or [],
                                resume=body.get("resume") or None,
                                new=bool(body.get("new")),
                                brief=body.get("brief") or None)
        return {"repo": repo, "pid": lock["pid"], "ticket": lock.get("ticket", ""),
                "summary": lock.get("summary", ""), "session": lock.get("session", "")}
    if what == "console":
        # A real window running Copilot in this checkout, with a session id the fleet chose (#189).
        from .. import config as C

        lock = supervisor.console(repo, key=body.get("ticket") or None, cfg=C.load(),
                                  resume=body.get("resume") or None, new=bool(body.get("new")),
                                  cross_project=bool(body.get("cross_project")),
                                  board_rows=(B.read_cache() or {}).get("rows") or [])
        return {"repo": repo, "pid": lock["pid"], "ticket": lock.get("ticket", ""),
                "session": lock.get("session", ""), "host": lock.get("host", "")}
    if what == "say":
        # A console session is typed into, never sent to (#190): `send` is a second
        # `copilot -p --resume` process, which in a checkout that already has a console is a second
        # agent. The helper attaches to that window and types the line the operator typed here.
        from .. import config as C

        message = str(body.get("message") or "").strip()
        if not message:
            raise ServeError("nothing to say", "type a message first")
        return supervisor.say(repo, message, cfg=C.load())
    if what == "focus":
        from .. import config as C

        return supervisor.focus(repo, cfg=C.load())
    if what == "send":
        from .. import config as C

        message = str(body.get("message") or "").strip()
        if not message:
            raise ServeError("nothing to send", "type a message first")
        lock = supervisor.send(repo, message, cfg=C.load())
        return {"repo": repo, "pid": lock["pid"]}
    if what == "scope/resolve":
        # Hashes in, paths out. Nothing is written and nothing is uploaded: the page has sent the
        # git object name of each dropped file and is asking which of its own files that is.
        from . import scope as SCOPE

        target = _repo_record(repo)
        return {"repo": target.name,
                "files": SCOPE.resolve(target.path, list(body.get("files") or []),
                                       max_bytes=_scope_cap())}
    if what == "scope":
        from . import scope as SCOPE

        # Absolute paths and no repository: a shell posted them (#167). The server decides which
        # checkout owns each one, because a shell that decided would be a shell with a rule in it.
        raw = [str(p) for p in (body.get("paths") or [])]
        if not repo and any(os.path.isabs(p) for p in raw):
            by_repo, orphans = SCOPE.group_by_checkout(raw)
            if orphans and not by_repo:
                raise ServeError(
                    f"{os.path.basename(orphans[0])} is not inside any registered checkout",
                    "`ad-fleet repo add <path>` for the checkout it lives in, then try again",
                    code="wrong_repo")
            selected = str(body.get("selected") or "")
            if selected and selected not in by_repo:
                owner = next(iter(by_repo))
                raise ServeError(
                    f"those files belong to {owner}, and {selected} is the selected tile",
                    f"select {owner} and drop them there, or give them to {owner} from its own tile",
                    code="scope_wrong_repo")
            out = []
            for name, group in by_repo.items():
                target = group["repo"]
                ticket = str(body.get("ticket") or "") or (target.state().get("active_ticket") or "")
                ev = SCOPE.add(name, target.path, ticket, group["paths"],
                               why=str(body.get("why") or "given from the IDE"),
                               how="ide", queued=bool(supervisor.live(name)))
                out.append({"repo": name, "ticket": ticket, **(ev.get("data") or {})})
            return {"scoped": out, "outside": orphans}

        target = _repo_record(repo)
        ticket = str(body.get("ticket") or "") or (target.state().get("active_ticket") or "")
        live = supervisor.live(target.name)
        ev = SCOPE.add(target.name, target.path, ticket,
                       [str(p) for p in (body.get("paths") or [])],
                       why=str(body.get("why") or "dropped on the tile"),
                       how=str(body.get("how") or SCOPE.BY_HASH),
                       queued=bool(live))
        return {"repo": target.name, "ticket": ticket, **(ev.get("data") or {}), **ev}
    if what == "attach-bytes":
        # The one route that carries bytes, and the only way a file that is *not* the repository's
        # reaches it. A click, a copy into `.agent/in/<KEY>/`, an `inbox.attached` event -- the
        # Downloads tray's rules, with `source: "drop"`.
        return _attach_bytes(body)
    if what == "answer":
        # Every answer the operator typed, in one resume. `send` is the transport, because a reply
        # to a stopped agent has always been a respawn with `--resume` -- there is no pipe to an
        # agent's stdin. What is new is that N answers cost one turn instead of N.
        from .. import config as C

        answers = [(str(a.get("id") or ""), str(a.get("answer") or ""))
                   for a in (body.get("answers") or [])
                   if str(a.get("id") or "") and str(a.get("answer") or "").strip()]
        if not answers:
            raise ServeError("nothing to answer",
                             "pick a choice or type an answer for at least one question")
        lock = supervisor.send(repo, lifecycle.answers_prompt(answers), cfg=C.load())
        return {"repo": repo, "pid": lock["pid"], "answered": [qid for qid, _ in answers]}
    if what == "stop":
        return supervisor.stop(repo)
    if what == "reset":
        from .. import config as C

        return supervisor.reset(repo, cfg=C.load(), force=bool(body.get("force")))
    if what == "adopt":
        from . import adopt as A

        return A.adopt(repo, pid=int(body.get("pid") or 0))
    if what == "release":
        from . import adopt as A

        return A.release(repo)
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
                       pinned=body.get("pinned"),
                       hidden=body.get("hidden"))
    if what == "window":
        w = str(body.get("w") or "main")
        kwargs = {k: v for k, v in body.items() if k != "w"}
        return update_window(w, **kwargs)
    if what == "attach":
        # The single exception in the epic's "nothing is written outside ~/.agentdata/fleet without
        # a click": this is the click. `Inbox.attach` does the copy and holds the rule that it lands
        # inside `<repo>/.agent/in/` and nowhere else.
        box, offer = _offer(str(body.get("id") or ""))
        ev = box.attach(offer, repo)
        data = ev.get("data") or {}
        return {"attached": data.get("attached", False),
                "dir": data.get("dir", ""),
                "why": data.get("why", ""),
                "file": data.get("file", ""),
                **ev}
    if what == "dismiss":
        box, offer = _offer(str(body.get("id") or ""))
        box.dismiss(offer)
        return {"dismissed": offer.name, "id": offer.id}
    if what == "theme":
        from .. import config as C
        cfg = C.load()
        cfg.setdefault("theme", {})
        if "theme" in body:
            theme_val = str(body["theme"]).strip()
            cfg["theme"]["default"] = theme_val if theme_val else "none"
        if "skin" in body:
            from . import skins

            skin_val = str(body["skin"]).strip()
            cfg["theme"]["skin"] = skin_val if skin_val else "none"
            # Choosing a skin chooses its ground with it, and writes that palette to the config the
            # terminal reads -- so the prompt beside the dashboard moves to Nether too. This is what
            # "skins drive themes" means in the one file both of them read.
            chosen = skins.get_skin(cfg["theme"]["skin"]) if skin_val and skin_val != "none" else None
            if chosen:
                cfg["theme"]["skin"] = chosen["full"]
                cfg["theme"]["default"] = chosen["base"]
        C.save(cfg)
        return {"theme": cfg["theme"].get("default", "none"), "skin": cfg["theme"].get("skin", "none")}
    raise ServeError(f"unknown action {what!r}",
                     "start | send | stop | reset | adopt | release | approve | deny | select | "
                     "arrange | attach | dismiss | theme")


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


def _poll_digests() -> dict[str, str]:
    """One string per checkout of what its cells currently say -- values only, not ages, so a
    cell merely getting older is not a change. Never raises: the stream must not die on a
    registry that is mid-write."""
    try:
        return {name: json.dumps({c: p.get("value") for c, p in poll_state(name).items()},
                                 sort_keys=True, ensure_ascii=False)
                for name in Registry().repos}
    except (RegistryError, OSError, TypeError, ValueError):
        return {}


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
    last_config_mtime = -1.0
    seen_theme_state = None
    from .. import config as C
    cfg_file = C.path()

    seen_polls: dict[str, str] | None = None
    while not stop.is_set():
        if polls:
            # A cell that changed without an event -- the git cell is the one that never has one
            # (#184) -- would otherwise sit on the tile until some agent said something. One
            # `polls` frame per changed checkout, and the page re-reads the snapshot it draws
            # cells from. Seeded before the first tick, so the first values count as a change:
            # the window's first snapshot was usually read before that tick.
            if seen_polls is None:
                seen_polls = _poll_digests()
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
        if polls and seen_polls is not None:
            # After the agent frames, for the same reason the desk frame is: the events first.
            for name, digest in _poll_digests().items():
                if seen_polls.get(name) != digest:
                    seen_polls[name] = digest
                    write(f"event: polls\ndata: {json.dumps({'repo': name})}\n\n")
                    sent = True
        state = desk_state()
        if state["version"] != seen_selection:
            # After the agent frames, not before: a window that has just connected wants the events
            # it missed first, and the selection is what it draws *with* them.
            seen_selection = state["version"]
            write(f"event: desk\ndata: {json.dumps(state, ensure_ascii=False)}\n\n")
            sent = True

        try:
            mtime = os.path.getmtime(cfg_file) if os.path.isfile(cfg_file) else 0.0
        except OSError:
            mtime = 0.0
        if seen_theme_state is None or mtime != last_config_mtime:
            last_config_mtime = mtime
            tstate = theme_state()
            if seen_theme_state is None or tstate != seen_theme_state:
                seen_theme_state = tstate
                write(f"event: theme\ndata: {json.dumps(tstate, ensure_ascii=False)}\n\n")
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

    def _refuse(self, code: int, error: str, hint: str = "", refusal_code: str = "") -> None:
        payload = {"ok": False, "error": error, "hint": hint}
        if code == 409 or refusal_code:
            payload["code"] = refusal_code or "refused"
        self._json(payload, code)

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
            forward = [(k, v[0] if isinstance(v, list) and len(v) == 1 else v)
                       for k, vs in query.items() if k != "t"
                       for v in (vs if isinstance(vs, list) else [vs])]
            dest = f"/?t={self.token}"
            if forward:
                dest += f"&{urlencode(forward)}"
            self.send_response(302)
            self.send_header("Location", dest)
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
            from . import skins
            return self._json({"ok": True, "themes": themes(), "skins": skins.list_skins()})
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
        if route == "/api/sessions":
            from . import sessions as SESS

            repo_name = (query.get("repo") or [""])[0]
            if not repo_name:
                return self._refuse(400, "repo required", "pass ?repo=<name>")
            try:
                repo_path = Registry().get(repo_name).path
            except (RegistryError, OSError):
                # An unregistered name still gets its folded sessions -- the stream outlives the
                # registration -- it just gets none of Copilot's own store, which is keyed on the
                # checkout this no longer knows the path of.
                repo_path = ""
            # Rebuilt on the click rather than read once and kept: the index is a fold of the
            # stream, so a session opened since the file was last written would be missing from the
            # very list that exists to find it again. Hand-set titles survive the rebuild.
            try:
                rows = SESS.rebuild_sessions(repo_name, repo_path=repo_path)
            except OSError:
                rows = SESS.load_sessions(repo_name)
            return self._json({"ok": True, "repo": repo_name, "sessions": rows})
        if route == "/api/transcript":
            # Read-only, and the whole point of it: choosing an earlier session must never spawn
            # anything. A GET cannot, which is why *Resume here* is a second, deliberate press on
            # `/api/start` rather than something this route does on the way past (#174).
            repo_name = (query.get("repo") or [""])[0]
            session_id = (query.get("session") or [""])[0]
            if not repo_name or not session_id:
                return self._refuse(400, "repo and session required",
                                    "pass ?repo=<name>&session=<id>")
            try:
                limit = int((query.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            try:
                before = int((query.get("before") or ["0"])[0])
            except ValueError:
                before = 0
            return self._json({"ok": True,
                               **transcript_for(repo_name, session_id,
                                                limit=max(1, min(limit, 1000)), before=before)})
        if route == "/api/preflight":
            # Read-only and it spends no premium request, which is the whole reason a drop can
            # afford to ask it. Every failure inside is a grey row, so this cannot 500 on an
            # unreachable Jira -- the card says `unknown` and Start stays enabled.
            from . import preflight as PF

            key = (query.get("key") or [""])[0]
            if not key:
                return self._refuse(400, "key required", "pass ?key=<TICKET>")
            return self._json(PF.preflight(key, (query.get("repo") or [""])[0]))
        if route == "/api/branches":
            # Every local branch of one checkout and which never reached the default (#184).
            # Read-only, local, cached for the git cell's interval; on the click, never on the
            # poll, because `rev-list` per branch across five checkouts is not a cost a
            # thirty-second tick can spend. 200 with ok:false when git cannot be asked: the pane
            # renders the reason, the way a grey cell carries its error.
            from .. import config as C

            repo_name = (query.get("repo") or [""])[0]
            if not repo_name:
                return self._refuse(400, "repo required", "pass ?repo=<name>")
            try:
                repo = Registry().get(repo_name)
            except RegistryError as e:
                return self._refuse(404, e.msg, e.hint)
            force = (query.get("refresh") or [""])[0] in ("1", "true", "yes")
            try:
                return self._json({"ok": True, "repo": repo_name,
                                   **P.branches(repo, cfg=C.load(), force=force)})
            except (OSError, ValueError) as e:
                return self._json({"ok": False, "repo": repo_name, "error": str(e)[:300],
                                   "hint": "git could not be asked in this checkout; "
                                           "`git status` there says why", "branches": []})
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
        if ctype.startswith("text/css"):
            body = _tokenize_css_urls(body.decode("utf-8"), self.token).encode("utf-8")
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
        # One route carries bytes, and only that one. Everything else on this server is a small
        # JSON object, and a 64 kB cap on all of them is what keeps a local server uninteresting to
        # a hostile tab. `attach-bytes` is the operator clicking *attach a copy*, so it gets the
        # configured attachment cap and nothing more.
        cap = _attach_cap() + 64 * 1024 if route == "/api/attach-bytes" else MAX_BODY
        if length > cap:
            return self._refuse(413, "body too large",
                                "raise `fleet.attach.max_mb`, or drop the file from inside the "
                                "checkout so it is scoped rather than copied")
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
                approval.ApprovalError, IN.InboxError, CAT.CatalogueError,
                HO.HandoffError, SCOPE_ERROR) as e:
            # The same refusal the CLI gives, with the same hint. One vocabulary.
            ref_code = getattr(e, "code", "") or "refused"
            return self._refuse(409, e.msg, getattr(e, "hint", ""), refusal_code=ref_code)
        except Exception as e:               # noqa: BLE001 - a button must never 500 silently
            from ..log import debug_exc

            debug_exc("fleet serve action")
            return self._refuse(500, str(e)[:300], "check the console running `ad-fleet serve`")


# ------------------------------------------------------------------------------------- the theme


def themes() -> list[dict]:
    """Palettes from agentdata.theme, rendered through theme.to_css()."""
    from .. import theme as T

    out = []
    for t in T.list_themes():
        if t.name == "none":
            continue
        c = T.to_css(t)
        colors = {
            "bg": c.get("--bg", ""),
            "panel": c.get("--panel", ""),
            "text": c.get("--text", ""),
            "muted": c.get("--muted", ""),
            "accent": c.get("--accent", ""),
            "line": c.get("--line", ""),
            "select": c.get("--select", ""),
        }
        out.append({
            "name": t.name,
            "title": t.title,
            "why": t.why,
            "light": t.light,
            "colors": colors,
            "css": c,
        })
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
        drop_handles()   # the poller, the inbox and the catalogue handle are this run's, not the next's
