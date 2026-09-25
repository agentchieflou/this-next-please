"""`ad-fleet serve`: the multi-viewer. One local page, one tile per agent, live.

The epic is named for YouTube's multi-view and this is that page: one tile per repository's agent,
live, with one open at full height and every other one a band beside it (#203, #232).

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
import gzip
import hmac
import itertools
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from html import escape as _escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .. import textio
from . import (agentstate, approval, board as B, catalogue as CAT, events as E, handoff as HO,
               inbox as IN, launch as LAUNCH, lifecycle, links as LK, loads as LOADS, notify as N,
               poll as P, probe as PROBE, supervisor, trace as TRACE, wrapup as WRAP)
from .registry import Registry, RegistryError, agent_dir, fleet_dir
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

# Every asset either page references. They are rewritten with the run token when the page is
# served; see `_page`. A name missing from here is served with no `?t=`, which `_authorized`
# refuses -- and only in a real browser, because a test fetches an asset with the token already in
# hand. That is the bug `_page`'s docstring is about, and adding a page means adding its script
# here in the same edit.
#
# `ink/ink.js` (#248) is the ink layer's front door, a module beside `app.js`. The rest of the layer
# -- `ink/layer.js`, `ink/shapes.js`, `ink/pen.js` and the vendored three.js -- is never named in a
# page: the layer imports it through `q()`, token and all, and only once the gate says on.
#
# `/map` (#405) brings its stylesheet and its one script, `map/map.js`; a scene it draws later
# (#409) is imported through `q()` like the ink layer's modules, never named here.
#
# `picker.js` (#362) is the model picker, a classic script the desk and /settings both load right
# after `common.js`.
ASSETS = ("app.css", "common.js", "picker.js", "app.js", "settings.js", "probe.js", "ink/ink.js",
          "map.css", "map/map.js")

# The pages this server serves, and the file each one is. A second page rather than a view swap
# because the operator asked for an address they can land on -- and because `app.js` boots a desk
# (an EventSource, a 15-second `loadDesk`, a `place()` that rewrites `document.body` several times
# a second) that has no business running under somebody editing a dropdown.
#
# `/probe` (#247) is the third: it measures WebGL in whatever shell it is opened in and posts the
# facts to `/api/probe`. The desk loads three.js only through the ink layer (#248), only when that
# shell's probe said hardware (or the page was opened with `?ink=on`), and only once a skin draws
# with ink -- and a test holds it to that.
#
# `/map` (#405) is the fourth: the fleet's structure as an accessible tree (docs/fleet-map.md
# §The page), read-only, and a page rather than a desk view for the reason settings is one.
PAGES = {"/": "index.html", "/settings": "settings.html", "/probe": "probe.html",
         "/map": "map.html"}

#: The pages whose `<body>` carries the ink gate's facts (`_page`): the desk, and the map, whose
#: scene (#409) is gated by the same probe. The map keeps `ink-off` for its whole life.
INKED_PAGES = ("index.html", "map.html")


def ink_facts(query: dict) -> dict:
    """Which shell a desk page is, by the name the probe filed it under, and what was measured there.

    The same name `probe.js` uses -- `shell=`, else `w=`, else `browser` -- so the window
    `ad-fleet probe --open pycharm` measured is the window that reads the answer. The class is
    `probe.classify`'s; the page turns ink on for `hardware` alone, which is `probe.works`.
    """
    def first(key: str) -> str:
        return ((query.get(key) or [""])[0] or "").strip().lower()

    return PROBE.ink_gate(first("shell") or first("w") or "browser")


SKIN_FAMILY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


def ink_skins() -> list[str]:
    """The skins that draw with ink: every `static/ink/skins/<name>.js`, a skin module -- its mark
    table and its materials (#248, docs/desk-ink.md §Writing a skin). The desk is told the list,
    so its ink layer fetches a module for those and never asks a CSS-only skin for one it has not
    got. The name is the skin's name in skins.py, which is how the settings page chooses it."""
    root = os.path.join(STATIC, "ink", "skins")
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(n[:-3] for n in names
                  if n.endswith(".js") and SKIN_FAMILY.match(n[:-3])
                  and os.path.isfile(os.path.join(root, n)))

# The page, compressed once per build of it rather than once per window (#195). Below a kilobyte the
# gzip header costs more than the compression saves, and a skin's PNG is already compressed, so only
# the text of the page goes through this. The API's JSON does not: the desk polls it four times a
# second over a loopback socket, where the compression is real CPU and the saving is a number nobody
# waits on. What this *is* for is the page arriving over something that is not loopback -- a
# forwarded port, a phone on the LAN, a remote desktop -- and for the budget below meaning what it
# says: the number that matters is what goes over the wire, not what sits on the disk.
GZIP_FROM = 1024
_GZIPPED: dict[tuple, bytes] = {}
_GZIP_LOCK = threading.Lock()


def gzip_for(body: bytes, key: tuple) -> bytes:
    """`body` compressed, remembered under `key` -- which must name everything it was made from."""
    with _GZIP_LOCK:
        hit = _GZIPPED.get(key)
    if hit is not None:
        return hit
    # mtime=0: the same bytes in, the same bytes out, so a test can compare two runs.
    packed = gzip.compress(body, 6, mtime=0)
    with _GZIP_LOCK:
        if len(_GZIPPED) > 32:                # one entry per asset per token; a long-lived server
            _GZIPPED.clear()                  # that has been restyled all day still stays small
        _GZIPPED[key] = packed
    return packed

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
# here for the same reason `_page` puts it on the page's own assets, and it goes BEFORE the
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
        return ({"n": 0, "started": "", "resumed": False, "session": "", "session_began": "",
                 "session_title": "", "ticket": "", "live": live, "origin": "", "events": []}, [])

    started_indices = [i for i, ev in enumerate(stream) if R.is_run_start(ev)]
    repo_name = stream[0].get("repo", "") if stream else ""
    if not started_indices:
        d = agentstate.derive(stream, live=live)
        return ({"n": 1, "started": stream[0].get("ts", ""), "resumed": False,
                 "session": d.get("session", ""), "session_title": "",
                 "session_began": _session_began(stream, repo_name, d.get("session", "")),
                 "ticket": d.get("ticket", ""), "live": live, "origin": "", "events": stream}, [])

    earlier = []
    for idx, start_i in enumerate(started_indices[:-1]):
        end_i = started_indices[idx + 1]
        run_events = stream[start_i:end_i]
        d = agentstate.derive(run_events, live=False)
        start_ev = stream[start_i]
        end_ev = run_events[-1] if run_events else start_ev
        earlier.append({
            "n": idx + 1,
            # Which session this run belongs to, so the menu can fold it under that session instead
            # of listing it as a second, adjacent "earlier" with different behaviour (#206).
            "session": run_session(run_events),
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
        # When this *session* began (#499), which a Send does not move: derived, never stored.
        "session_began": _session_began(stream, repo_name, curr_sess),
        "ticket": curr_derived.get("ticket") or start_ev.get("ticket", ""),
        "live": live,
        # Who started this run, from its `started` event (#401): the map's `kind` reads it, because
        # a headless `copilot -p` agent exits at every turn's end and liveness alone cannot tell.
        "origin": run_origin(start_data),
        "events": curr_events,
    }
    return curr_run, earlier


def _session_began(stream: list[dict], repo_name: str, session: str) -> str:
    """The `ts` of the `started` that began the current session (#499).

    Every Send writes a `started` with `resumed: true`, so the current *run* moves on each one; the
    session does not. When that `started` has rolled out of the stream, the session's `first_seen`
    in sessions.json answers, and otherwise nothing does.
    """
    from . import runs as R

    began = R.session_start(stream).get("ts", "")
    if began or not (repo_name and session):
        return began
    try:
        from . import sessions as SS
        for rec in SS.load_sessions(repo_name):
            if rec.get("id") == session:
                return str(rec.get("first_seen") or "")
    except Exception:                    # noqa: BLE001 - an unreadable sessions.json is no boundary
        pass
    return ""


def run_origin(start_data: dict) -> str:
    """Who began a run, from its `started` event's data: console, adopted or fleet (#401)."""
    if start_data.get("console"):
        return "console"
    if start_data.get("adopted") or start_data.get("external"):
        return "adopted"
    return "fleet"


# How often one repository may be refreshed by hand. It re-reads what the tick reads, so pressing
# it twice in the same breath cannot tell the operator anything the first press did not.
REFRESH_FLOOR_S = 2.0
_refreshed_at: dict = {}


def _spend_cell(name: str, budget: float) -> dict:
    """What the tile's spend cell draws. One arithmetic, in `spend.py`, for every printer."""
    from . import spend as SPEND

    try:
        return SPEND.for_tile(name, budget=budget, today=_today())
    except Exception:                    # noqa: BLE001 - a tile never fails to draw over a number
        return {"total": 0.0, "turns": 0, "session": 0.0, "today": 0.0,
                "budget": round(float(budget or 0.0), 2), "rate": 0.0, "sessions": 0}


def _today() -> str:
    """The operator's own day. The ledger stores UTC stamps; the printer decides which day they
    belong to, because "today" on a desk means the day the person is having."""
    return time.strftime("%Y-%m-%d", time.localtime())


def _model_cells(name: str, cfg: dict) -> dict:
    """Which model this agent is launched with, and which one its last turn actually ran on.

    The same two facts the settings page shows (#199), on the tile's own row, from the same two
    functions -- `LAUNCH.model_for` and `served_model` -- so a page and a tile can never disagree
    about what an agent is running. They differ whenever a tenant pins a model, which is exactly
    the case the operator needs to be able to see without opening a second page.
    """
    try:
        model, effort, source = LAUNCH.model_for(name, cfg)
        effort_source = LAUNCH.effort_source(name, cfg)
    except Exception:                    # noqa: BLE001 - a tile never fails to draw over a setting
        model, effort, source, effort_source = "", "", "cli-auto", "cli-auto"
    actual, launched, turn = models_in_stream(name)
    # What the fleet would give each half (#493): the words of a card's `inherit` pills.
    fleet = (cfg or {}).get("fleet") if isinstance((cfg or {}).get("fleet"), dict) else {}
    return {"model": model, "effort": effort, "model_source": source, "effort_source": effort_source,
            "fleet_model": str(fleet.get("model") or ""), "fleet_effort": str(fleet.get("effort") or ""),
            "actual": actual, "launched": launched, "turn_model": turn}


# Which of two rows the server read first (#235). A row reaches the page by two roads -- an action's
# own answer (#219) and `/api/fleet`, which the page asks for whenever the stream says something
# happened -- and the page drew whichever *arrived* last. Arriving is not reading. Adopting appends
# an event, so a snapshot is asked for within the second, and on the Windows runner one read while
# the session was still adopted landed after the hand-back's answer: the tile went back to "a session
# outside the fleet is driving this repo", and stayed there, because a released lock is not an event
# and nothing came to draw it again. So every row carries the order its snapshot was begun in, and
# the page keeps the row it has over one begun before it.
#
# A count, not a clock: two snapshots begun in one tick of a 15 ms Windows clock would tie, and a
# wall clock can be stepped back. `run` says which process counted, because a desk restarted under
# the same token starts counting again, and the page must take its rows rather than hold the old
# process's numbers over them.
_read_order = {"run": secrets.token_hex(4), "n": 0}
_read_order_lock = threading.Lock()


def read_order() -> dict:
    """`{run, n}` for a snapshot about to be read: later than every one handed out before it."""
    with _read_order_lock:
        _read_order["n"] += 1
        return dict(_read_order)


def row_for(name: str) -> dict:
    """One tile's row, exactly as `/api/fleet` would send it. What an action answers with."""
    for row in fleet_snapshot().get("repos", []):
        if row.get("repo") == name:
            return row
    return {}


def fleet_snapshot() -> dict:
    """Everything the page needs to draw itself from cold. Also the reconnect path.

    The row is built field by field rather than merged from `supervisor.status()` wholesale, because
    that dict also carries an `agent` word for the same idea as `state`. Two state words on one row
    is the second-source-of-truth problem in miniature: they would disagree eventually, and nobody
    would know which the tile was showing. The fold (#94) is the state; the supervisor supplies only
    what the fold cannot see -- where the checkout is, and which pid is holding it.
    """
    # Before anything is read, the lock and the offers included (#235): a row can then only be newer
    # than its number says, so an action's answer, numbered after the action, outranks every
    # snapshot begun before it.
    as_of = read_order()
    rows = []
    try:
        # Once, not once per row: `Registry()` re-parses `registry.json` every time it is built.
        registry = Registry()
    except RegistryError:
        registry = None
    from .. import config as C
    from .. import theme as T
    cfg = C.load()
    budget_now = lifecycle.settings(cfg)["budget_per_agent"]
    default_theme_name = cfg.get("theme", {}).get("default") or "none"
    proj_theme_map = cfg.get("theme", {}).get("projects", {})
    if not isinstance(proj_theme_map, dict):
        proj_theme_map = {}

    # Sessions the fleet did not start (#2), worked out once for the whole snapshot rather than per
    # row: the process listing behind this is a PowerShell call on Windows, and it is cached besides.
    # A desk never waits for it: a stale listing is refreshed off this thread, and this answer draws
    # the one already held.
    from . import adopt as A

    try:
        offers = {c["repo"]: c for c in A.candidates(registry,
                                                      processes=A.agent_processes(wait=False))}
    except Exception:                    # noqa: BLE001 - never let this stop a dashboard drawing
        offers = {}

    # What a new session would start on, read once per snapshot (#240). Every row is judged
    # against it, so staleness is checked on every tick of every open desk -- at every turn.
    from . import fingerprint as FP
    from . import fresh as FRESH
    from . import renew as RENEW

    try:
        installed = FP.current()
    except Exception:                    # noqa: BLE001 - an unreadable skills folder is not a dead desk
        installed = None

    for row in supervisor.status():
        name = row["repo"]
        repo = None                          # rebound per row: a lookup that raised used to leave
        repo_state: dict = {}                # the previous row's repository (and its state) in hand
        try:
            repo = registry.get(name) if registry is not None else None
            if repo is not None:
                repo_state = repo.state()
                E.refresh(name, repo.path, repo_state=repo_state)
        except (RegistryError, OSError):
            pass
        stream = E.read(name)
        live_lock = supervisor.live(name)
        is_live = bool(live_lock)
        curr_run, earlier = split_runs(stream, live=is_live)
        # `state.json` says which questions are open (#231); the stream only says which were asked.
        # A file nobody has written has no say, so a missing or unreadable one reconciles nothing.
        open_questions = (repo_state.get("open_questions") or []) if repo_state else None
        derived = agentstate.derive(curr_run["events"] or stream, live=is_live,
                                    open_questions=open_questions)

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
                     # Which model this agent is launched with, and which one the last turn
                     # actually ran on -- the two differ whenever a tenant pins one. Computed by the
                     # same functions the settings page calls, so the tile and the page cannot
                     # disagree about what an agent is running (#205).
                     **_model_cells(name, cfg),
                     # What it has cost, against what (#211). On the row and not in `polls`,
                     # because a poll cell can be stale or grey and this never is: it is a fold of
                     # the agent's own stream.
                     "spend": _spend_cell(name, budget_now),
                     # The shape of the hour (#218): sixty small integers, drawn as a trace on
                     # the tile and the band. Folded from the whole stream rather than from
                     # `recent`, because forty events is not an hour -- a busy agent fills that
                     # in two minutes -- and no text comes with it.
                     "trace": TRACE.trace(stream),
                     # Is this session on the installed skills and CLI (#240)? Derived from the
                     # stream's own `started` events against what is on disk now, never stored.
                     "stale": _stale_cell(stream, installed),
                     "renew_queued": bool(RENEW.queued(name)),
                     "last_seq": stream[-1]["seq"] if stream else 0,
                     # When this was read, against the other rows the page is sent (#235).
                     "as_of": as_of,
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
        # Start fresh (#488): whether the pane offers it, why, and what it would do -- derived from
        # what this row already read and the snapshot's one listing, so a tick spawns nothing.
        rows[-1]["fresh"] = FRESH.row_cell(rows[-1], st=repo_state, stream=stream, lock=live_lock,
                                           offer=offers.get(name), cfg=cfg)

    _add_siblings(rows)
    from .. import config as C

    # `fleet.preflight: false` restores #98's immediate start: a drop launches instead of opening
    # the dispatch card. Absent means on, because the card is the recoverable direction.
    return {"repos": rows, "approvals": approval.pending(), "fleet_dir": fleet_dir(),
            # The fleet's own line (#212): today, and all time. Summed from the same ledgers the
            # tiles read, so the footer and the cells cannot disagree.
            "spend": {"today": round(sum((r.get("spend") or {}).get("today", 0.0) for r in rows), 2),
                      "all_time": round(sum((r.get("spend") or {}).get("total", 0.0) for r in rows), 2),
                      "budget_invalid": lifecycle.settings(cfg).get("budget_invalid", "")},
            "desk": desk_state(), "theme": theme_state(),
            "server": desk_currency(),
            "preflight": C.get(C.load(), "fleet.preflight") is not False,
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


def _stale_cell(stream: list[dict], installed: dict | None) -> dict:
    """`{stale, unknown, reason, skills_changed}` for the tile. Never raises: a desk draws regardless."""
    from . import fingerprint as FP

    if installed is None:
        return {"stale": False, "unknown": True, "reason": "the installed skills could not be read",
                "skills_changed": []}
    try:
        verdict = FP.staleness(stream, installed)
    except Exception:                    # noqa: BLE001 - see the docstring
        return {"stale": False, "unknown": True, "reason": "", "skills_changed": []}
    return {k: verdict[k] for k in ("stale", "unknown", "reason", "skills_changed")}


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
         "last_fold": 0.0, "last_renew": 0.0}
_desk_lock = threading.RLock()
# Held only while the catalogue's sqlite file is opened, never with `_desk_lock` waiting on it (#439).
_catalogue_lock = threading.Lock()

DESK_FILE = "desk.json"
# What `desk.json` was before schema 2, kept beside it by the migration that read it. The migration
# is one-way and runs by itself on the first load after an update, so the file it replaced is the
# only way back -- to an older build, or to what the operator had.
DESK_V1_FILE = "desk.v1.json"
DESK_SCHEMA = 2


def _blank_arrangement() -> dict:
    """An arrangement nobody has touched: registry order, nothing pinned, sized or hidden."""
    return {"order": [], "size": {}, "pinned": [], "hidden": []}


# The desk every window on this server agrees on, persisted in desk.json (#133, #172, #232).
#
# Schema 2 has one arrangement where schema 1 had one per layout. Four layouts wrote one window
# record -- the grid `zoomed`, the column `open`, roles `view` and screens `screen` -- and two of
# them disagreeing inside it is what snapped a click in the column back to the agent before it
# (#230). There is one arrangement now, so there is one of each: one `order`, one `hidden`, and one
# `open` per window.
#
# The widths are the window's, not the arrangement's (#234): two monitors hold different widths over
# the same agents in the same order, so they live in each window record beside `open`. `size` stays
# in the arrangement as what an older build wrote, and the page reads it only as the starting widths
# of a window that has never been given any; `pinned` is the order's "first", and nothing else.
_selection = {
    "schema": DESK_SCHEMA,
    "selected": "",
    "version": 0,
    "at": "",
    "arrangement": _blank_arrangement(),
    "windows": {},
}

# The fields a window record carries (#172). `open` is the one agent the keys and the composer
# address; `read` and `seen` are what this window has read and when it last looked; `section` is
# its sidebar. `widths` is each pane's weight in this window -- 0 a rail, a positive number its share
# of what the rails leave -- and `widths_at` the desk version they were written at, which is what a
# page's write of them is checked against (#234). `focus` (the needs-only filter) and `held` (what
# that filter kept on the glass) are still read and kept for a page from before the *needs me*
# preset replaced them, and no page writes them now.
WINDOW_FIELDS = ("open", "focus", "read", "seen", "held", "section", "widths", "widths_at")


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
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    schema = data.get("schema")
    if not isinstance(schema, int) or schema < DESK_SCHEMA:
        _selection.update(migrate_desk(data))
        # The old file first, then the new one: a migration that could not keep what it read must
        # not be the thing that overwrites it.
        try:
            textio.write_text(os.path.join(fleet_dir(), DESK_V1_FILE), raw)
        except OSError:
            return
        _save_desk()
        return
    _selection["selected"] = str(data.get("selected") or "")
    _selection["version"] = _version_of(data)
    _selection["at"] = str(data.get("at") or "")
    _selection["arrangement"] = _arrangement(data.get("arrangement"))
    wins = data.get("windows")
    if isinstance(wins, dict):
        _selection["windows"] = {k: dict(v) for k, v in wins.items() if isinstance(v, dict)}


def _version_of(data: dict) -> int:
    try:
        return int(data.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def _arrangement(value) -> dict:
    """One arrangement record, read leniently: an arrangement is a preference, and a preference that
    cannot be parsed is a desk in registry order, not a dashboard that will not draw."""
    one = dict(value) if isinstance(value, dict) else {}
    out = _blank_arrangement()
    for key in ("order", "pinned", "hidden"):
        if isinstance(one.get(key), list):
            out[key] = [str(x) for x in one[key]]
    # #217: `size: 2` from an older build becomes `{cols, rows}` here, so the page and the CLI
    # only ever have one shape to read.
    out["size"] = _sizes(one.get("size"))
    return out


def migrate_desk(v1: dict) -> dict:
    """A schema-1 `desk.json` as schema 2 (#232). Pure: it reads the old record and writes nothing.

    The arrangement comes from `column` when the old file has one, because that is the drawing the
    one arrangement keeps; else from `grid`, because `ad-fleet hide` wrote to `grid` whatever the
    page showed, so an operator who only ever hid from a terminal has their list there. `roles` and
    `screens` go with the arrangements they described.

    Each window keeps `open` and its own reading state. `zoomed`, `layout`, `view` and `screen` go:
    `zoomed` is the leftover that re-opened an agent on every frame (#230), and the other three
    named an arrangement that no longer exists. `screens` goes with them. `selected` stays, because
    the inspector reads it. The version rises by one, because this is a write like any other and
    every window has to hear about it.
    """
    arr = v1.get("arrangement") if isinstance(v1.get("arrangement"), dict) else {}
    source = arr.get("column") if isinstance(arr.get("column"), dict) else arr.get("grid")
    old_windows = v1.get("windows") if isinstance(v1.get("windows"), dict) else {}
    windows = {}
    for name, win in old_windows.items():
        if isinstance(win, dict):
            windows[str(name)] = {k: win[k] for k in WINDOW_FIELDS if k in win}
    return {
        "schema": DESK_SCHEMA,
        "selected": str(v1.get("selected") or ""),
        "version": _version_of(v1) + 1,
        "at": E.stamp(),
        "arrangement": _arrangement(source),
        "windows": windows,
    }


# desk.json is written OUTSIDE `_desk_lock` (#245). Every desk read -- a snapshot, the stream's
# tick, `fold_due` -- takes that lock, and on Windows one write can take seconds: `os.replace` onto
# a file the antivirus is still scanning fails and is retried (`textio._replace_with_retry`). With
# the write inside the lock, every request on the desk queued behind the disk; on the Windows CI
# leg that was a page whose answers arrived ten seconds late, three different browser tests red,
# and a console line not folded because the fold's turn had gone to a request still waiting.
#
# So a change takes a snapshot while it holds the lock, and the snapshot is written after it has
# let go. Writes still reach the disk in the order the changes were made: each snapshot takes the
# next number while the lock is held, and of two racing for the same file the older is dropped
# rather than written over the newer one.
_desk_write_lock = threading.Lock()
_desk_seq = itertools.count(1)
_desk_written: dict[str, int] = {}


def _desk_snapshot() -> tuple[str, str, int]:
    """What `desk.json` should hold now, and its place in line. Taken while holding `_desk_lock`."""
    return _desk_file(), json.dumps(_selection, indent=2), next(_desk_seq)


def _write_desk(snapshot: tuple[str, str, int] | None) -> None:
    """Write a snapshot taken under `_desk_lock`, without holding it. The latest change wins."""
    if not snapshot:
        return
    path, text, seq = snapshot
    with _desk_write_lock:
        if seq <= _desk_written.get(path, 0):
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            textio.write_text(path, text)
        except Exception:
            return
        _desk_written[path] = seq


def _save_desk() -> None:
    """Snapshot and write in one call, for a caller that does not hold `_desk_lock`."""
    with _desk_lock:
        snapshot = _desk_snapshot()
    _write_desk(snapshot)


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
        _refreshed_at.clear()
        _desk.update(dir="", poller=None, inbox=None, catalogue=None, last_tick=0.0,
                     last_fold=0.0, last_renew=0.0)


def forget_desk() -> None:
    """Drop handles and blank selection. Called only when the fleet moves under a live process."""
    global _desk_loaded
    _desk_loaded = False
    drop_handles()
    with _desk_lock:
        _selection.update(
            schema=DESK_SCHEMA,
            selected="",
            version=_selection["version"] + 1,
            at=E.stamp(),
            arrangement=_blank_arrangement(),
            windows={},
        )
        snapshot = _desk_snapshot()
    _write_desk(snapshot)


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


def current_poller():
    """The `Poller` if one exists, else None. Never constructs one: a reader that only wants what
    the poll already read (the map, #403) must not be the thing that starts polling."""
    with _desk_lock:
        return _fresh()["poller"]


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

    Opened outside `_desk_lock` (#439). The first open creates the file, turns on WAL and runs the
    schema -- seconds on a Windows machine whose scanner reads every new file -- and every window
    write, arrangement and the stream's poller wait on `_desk_lock`, none of them for the catalogue.
    `_catalogue_lock` only makes a second opener wait for the first rather than open twice.
    """
    import sqlite3

    with _desk_lock:
        bag = _fresh()
        if bag["catalogue"] is not None:
            return bag["catalogue"]
    with _catalogue_lock:
        with _desk_lock:
            bag = _fresh()
            if bag["catalogue"] is not None:
                return bag["catalogue"]
            here = bag["dir"]
        try:
            opened = CAT.Catalogue.open()
        except (sqlite3.Error, CAT.CatalogueError, OSError):
            return None
        with _desk_lock:
            bag = _fresh()
            if bag["dir"] == here and bag["catalogue"] is None:
                bag["catalogue"] = opened
                return opened
        # The fleet moved while this one was opening (a test, or a changed AGENTDATA_FLEET_DIR): the
        # handle is for a directory nobody reads any more.
        try:
            opened.close()
        except Exception:                    # noqa: BLE001 - a closed handle is the point
            pass
        with _desk_lock:
            return _fresh()["catalogue"]


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


RENEW_EVERY_S = 2.0


def renew_tick(now: float | None = None) -> list[dict]:
    """Carry out the renews queued for a turn's end (#241), at most once every `RENEW_EVERY_S` for
    the whole process -- every open window runs this loop, and one of them doing it is enough."""
    now = time.time() if now is None else float(now)
    with _desk_lock:
        bag = _fresh()
        if now - bag["last_renew"] < RENEW_EVERY_S:
            return []
        bag["last_renew"] = now
    from .. import config as C
    from . import renew as RENEW

    try:
        cfg = C.load()
    except Exception:                        # noqa: BLE001 - a broken config must not stop the stream
        return []
    return RENEW.carry_out(cfg=cfg)


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
    """What every window agrees on: the selected project and the one arrangement, beside each
    window's own record."""
    _ensure_desk_loaded()
    with _desk_lock:
        arr = _selection.get("arrangement") or _blank_arrangement()
        wins = _selection.get("windows") or {}
        return {
            "schema": DESK_SCHEMA,
            "selected": _selection["selected"],
            "version": _selection["version"],
            "at": _selection["at"],
            "arrangement": {k: (list(v) if isinstance(v, list) else dict(v))
                            for k, v in arr.items()},
            "windows": {k: _window_copy(v) for k, v in wins.items()},
            "measure": _fresh_asks(),
        }


def _window_copy(win):
    """One window record, copied a level down: `widths`, `read` and `held` are containers, and a
    caller that edited the answer it was handed must not be editing the desk."""
    if not isinstance(win, dict):
        return win
    return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
            for k, v in win.items()}


# `ad-fleet probe --open pycharm` (#247): which windows the CLI has asked to measure WebGL, and when.
# Nothing outside PyCharm can point its JCEF tool window at a URL, but the desk already inside it
# reads the desk frame down the stream -- so it takes itself to `/probe`, and nobody types an address.
#
# In memory and nowhere else (#261). It is a one-shot request, not state: it has no business in
# desk.json, surviving a restart, or being a field every window record carries. A window that
# opens within `MEASURE_ASK_S` still finds it; one opened tomorrow finds the desk it asked for. And
# it is *taken*, not read: the window that goes is the one whose `measure {take}` the server
# answered `go: true`, so two desks under one name, or a reload drawing an old snapshot, never go
# round twice.
MEASURE_ASK_S = 600
_measure_asks: dict[str, float] = {}


def _fresh_asks() -> dict[str, int]:
    """The asks younger than `MEASURE_ASK_S`, by window, in epoch seconds. Drops the rest."""
    now = time.time()
    for w, at in list(_measure_asks.items()):
        if now - at >= MEASURE_ASK_S:
            _measure_asks.pop(w, None)
    return {w: int(at) for w, at in _measure_asks.items()}


def measure(w: str, take: bool = False) -> dict:
    """Ask window `w` to go and measure WebGL, or -- with `take` -- let it claim that ask.

    Asking bumps the desk's version, so the frame carrying the ask reaches every window now rather
    than on the next unrelated change. Taking answers `go` exactly once per ask.
    """
    w = str(w or "").strip()[:64]
    if not w:
        raise ServeError("which window? `w` is empty", "the `w=` the desk window was opened with")
    _ensure_desk_loaded()
    snapshot = None
    with _desk_lock:
        _fresh_asks()
        if take:
            at = _measure_asks.pop(w, None)
            return {"w": w, "go": at is not None, "asked": int(at or 0)}
        _measure_asks[w] = time.time()
        _selection["version"] += 1
        _selection["at"] = E.stamp()
        snapshot = _desk_snapshot()
        state = desk_state()
    _write_desk(snapshot)
    return state


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
    from . import settings as SET, skins
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
    # A word in a state colour is chosen against every panel the palette is drawn on (#328), so
    # the tokens are one set per palette, the same under every skin on it.
    css_vars = T.to_css(t, panels=skins.panels_on(t.name)) if t and t.name != "none" else {}
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
        # The widths a pane changes tier at (#235). Here because this is the payload the config
        # file already reaches every window by -- `/api/fleet`, the stream's `theme` frame when the
        # file changes, and the served page itself (`page_theme`, #345) -- so the settings page's
        # "in effect now" is true of them as it is of the palette.
        "tiers": SET.tiers(cfg),
    }


# What `page_theme` lets through from `theme_state()["css"]`: a custom property's name and a hex
# colour, nothing else, so a hand-edited config cannot put a `;` or a `url()` into the page.
CSS_TOKEN = re.compile(r"^--[a-z][a-z0-9-]*$")
CSS_HEX = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
#: The epic's progressive decision (#291): `ink-off` is served on every skinned page, the desk too,
#: and ink.js lifts it in the task in which its layer first draws. False serves it on the desk only
#: where the ink gate is off.
INK_OFF_UNTIL_DRAWN = True


def _px(n) -> str:
    """A width as `applyTiers` writes it: `rail + "px"`, so 220 is `220px`, never `220.0px`."""
    return f"{int(n)}px" if float(n) == int(n) else f"{n}px"


def ink_gate_on(query: dict, probe_class: str | None = None) -> bool:
    """ink.js's gate, decided on the server: `?ink=off` is off, `?ink=on` is on, else the shell's
    probe class is `hardware` (ink.js, "the gate"). `probe_class` is `ink_facts(query)["class"]`
    when the caller has it already."""
    asked = ((query.get("ink") or [""])[0] or "").strip().lower()
    if asked in ("off", "on"):
        return asked == "on"
    return (probe_class if probe_class is not None else ink_facts(query)["class"]) == "hardware"


#: The pages that time their own load while measuring is on (#351); never `/probe`, which measures
#: a shell rather than a load.
MEASURED_PAGES = ("index.html", "settings.html")


def measure_attr(name: str) -> str:
    """` data-measure="loads"` for `<html>` while `fleet.loads.enabled` is on and `name` is a
    measured page (#351), else nothing -- so with measuring off the markup is byte-identical to what
    it was. The page reads the attribute at boot and needs no request to find out."""
    return ' data-measure="loads"' if name in MEASURED_PAGES and LOADS.enabled() else ""


def page_theme(ts: dict, token: str, *, desk: bool, gate_on: bool) -> dict:
    """The chosen palette, skin and tiers as the served page's own markup (#345), so its first
    painted frame is the one the operator chose -- not the system palette, and not the snapshot of
    the skin just replaced. Written exactly as `applyTheme`, `applySkin` and `applyTiers` write
    them, so the first `/api/fleet` answer finds every value already in place and writes nothing.

    Answers `html` (attributes for `<html lang="en">`), `link` (for `</head>`), `body_class` (a
    class to append) and `body` (attributes after the class): all empty for no skin, no palette
    and the default tiers, so that page is byte-identical to the file."""
    from . import settings as SET
    decl, attrs = [], ""
    css = ts.get("css") or {}
    if css and ts.get("theme") != "none":
        decl = [f"{k}:{v}" for k, v in css.items() if CSS_TOKEN.match(str(k)) and CSS_HEX.match(str(v))]
        attrs = ' data-theme="custom"'
    if desk:
        tiers = ts.get("tiers") or {}
        four = {k: tiers.get(k) for k in ("rail", "compact", "full", "slack")}
        if four != SET.TIER_DEFAULTS:
            attrs += ' data-tiers="{}"'.format(_escape(" ".join(str(four[k]) for k in four)))
            if four["rail"] != SET.TIER_DEFAULTS["rail"]:
                decl.append(f"--rail:{_px(four['rail'])}")
            if four["compact"] != SET.TIER_DEFAULTS["compact"]:
                decl.append(f"--compact-from:{_px(four['compact'])}")
    if decl:
        attrs += ' style="{}"'.format(_escape(";".join(decl)))
    # Split as `applySkin` splits it, not by skins.py: a skin it does not know (`example`) is still
    # the one the page wears.
    family, _, variant = str(ts.get("skin") or "").partition(":")
    if family in ("", "none") or not SKIN_FAMILY.match(family):
        return {"html": attrs, "link": "", "body_class": "", "body": ""}
    variant = variant if SKIN_FAMILY.match(variant) else ""
    link = (f'<link rel="stylesheet" data-skin="true" '
            f'href="/static/skins/{family}/skin.css?t={_escape(token)}">')
    body = f' data-skin="{family}"' + (f' data-skin-variant="{variant}"' if variant else "")
    off = not desk or INK_OFF_UNTIL_DRAWN or not gate_on
    return {"html": attrs, "link": link, "body_class": "ink-off" if off else "", "body": body}


#: What `layer.js` imports once the gate is on (layer.js `start`, `VENDOR`), after ink.js imports it.
INK_LAYER_MODULES = ("ink/layer.js", "ink/shapes.js", "ink/pen.js", "vendor/three/three.module.min.js")


def ink_preload(ts: dict, token: str, *, gate_on: bool) -> str:
    """The desk's `<link rel="modulepreload">`s for what its served skin will import (#349), so the
    modules are fetched in parallel with the page instead of as a waterfall that starts once ink.js
    has run: the skin module for an ink skin on every shell (the plain fallback draws its table
    too), and the layer, its two helpers and three.js only where `gate_on`. Each href is the URL
    `q()` builds, so the module map dedupes and each module is fetched once. Empty for no skin or
    a skin that does not draw with ink."""
    family = str(ts.get("skin") or "").partition(":")[0]
    if not SKIN_FAMILY.match(family) or family not in ink_skins():
        return ""
    paths = [f"ink/skins/{family}.js"] + (list(INK_LAYER_MODULES) if gate_on else [])
    return "".join(f'<link rel="modulepreload" href="/static/{p}?t={_escape(token)}">' for p in paths)


def select(selected=None) -> dict:
    """Set the shared selection, bumping the version the stream watches.

    Returns the new state whether or not anything changed, because the caller is a button and "your
    click did nothing" is not a useful answer. The version only moves on a real change, so two
    windows clicking the same tile do not each wake the other.
    """
    _ensure_desk_loaded()
    snapshot = None
    with _desk_lock:
        if selected is not None and str(selected or "") != _selection["selected"]:
            _selection.update(selected=str(selected or ""), version=_selection["version"] + 1,
                              at=E.stamp())
            snapshot = _desk_snapshot()
        state = desk_state()
    _write_desk(snapshot)
    return state


#: How wide and how tall a tile may be asked to become. Four columns was the whole of a 1920px
#: glass at the grid's 360px minimum track; three rows is the page height in thirds, which is the
#: coarsest useful answer to "make this one taller" and the finest one anybody can hit by eye.
#:
#: Nothing on the page writes `size` since the gutters (#234): a pane's width is a weight in its
#: window's record. It is still read, clamped and kept, because a desk.json an older build wrote
#: carries it, and the page takes `cols` as the starting weight of a window with no widths yet --
#: which is what plan-panes' migration says `size.cols` becomes.
SIZE_MAX_COLS = 4
SIZE_MAX_ROWS = 3


def size_cell(value) -> dict:
    """One tile's footprint, as columns and rows (#217).

    Every `desk.json` written before this holds `size: 2` -- one number meaning "two columns
    wide". It reads as `{"cols": 2, "rows": 1}`, and is written back in the new shape the first
    time the arrangement changes, so an old file is migrated by being used rather than by a
    migration step nobody remembers to run. Out-of-range and unreadable values clamp rather than
    raise: an arrangement is a preference, and a preference that cannot be parsed is a tile at its
    default size, not a dashboard that will not draw.
    """
    cols, rows = 1, 1
    if isinstance(value, dict):
        try:
            cols = int(value.get("cols") or 1)
        except (TypeError, ValueError):
            cols = 1
        try:
            rows = int(value.get("rows") or 1)
        except (TypeError, ValueError):
            rows = 1
    else:
        try:
            cols = int(value or 1)
        except (TypeError, ValueError):
            cols = 1
    return {"cols": max(1, min(SIZE_MAX_COLS, cols)),
            "rows": max(1, min(SIZE_MAX_ROWS, rows))}


def _sizes(mapping) -> dict:
    if not isinstance(mapping, dict):
        return {}
    return {str(k): size_cell(v) for k, v in mapping.items()}


def arrange(*, order=None, size=None, pinned=None, hidden=None) -> dict:
    """Set the desk's one arrangement (#232), persisted in desk.json and pushed down the SSE stream.

    `hidden` joins `order`, `size` and `pinned` (#173). Shared across windows, because one desk
    means the same agents in the same order on every screen.
    """
    _ensure_desk_loaded()
    snapshot = None
    with _desk_lock:
        cur = _selection.setdefault("arrangement", _blank_arrangement())
        changed = False
        if order is not None and cur.get("order") != list(order):
            cur["order"] = [str(x) for x in order]
            changed = True
        if size is not None:
            want = _sizes(size)
            if cur.get("size") != want:
                cur["size"] = want
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
            snapshot = _desk_snapshot()
        state = desk_state()
    _write_desk(snapshot)
    return state


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


#: The largest weight a pane may carry. A weight means something only beside its neighbours', so
#: the number itself is arbitrary; the cap is there so a typo cannot be 1e308.
WIDTH_MAX = 1000.0


def widths_cell(value) -> dict:
    """One window's widths (#234): repository -> weight, where 0 is a rail and a positive number is
    that pane's share of what the rails leave.

    Refused rather than repaired when it is not that shape. `size` was read leniently because it was
    a preference on disk that an older build might have written; this is a write the page is making
    now, and a width the page did not mean is not one to guess at.
    """
    hint = "0 is a rail; any other number is that pane's share of the width the rails leave"
    if not isinstance(value, dict):
        raise ServeError("`widths` is an object of repository: weight", hint, code="widths_shape")
    out = {}
    for name, weight in value.items():
        ok = isinstance(weight, (int, float)) and not isinstance(weight, bool)
        if not ok or weight != weight or weight < 0 or weight == float("inf"):
            raise ServeError(f"the width of {name!r} is {weight!r}, which is not a weight", hint,
                             code="widths_shape")
        out[str(name)] = round(min(float(weight), WIDTH_MAX), 4)
    return out


def update_window(w: str = "main", **kwargs) -> dict:
    """Set per-window state in desk.json and push down the SSE stream.

    Only `WINDOW_FIELDS` are written. A page from before #232 still sends `layout`, `view`, `screen`
    and `zoomed`; they are dropped here rather than stored, because a field that nothing reads and
    one window writes is the snap-back waiting for a reader.

    `widths` comes with the desk `version` the page last heard (#234). Two pages can share one
    window record -- two tabs with no `?w=`, or the same `?w=` opened twice -- and each sends every
    pane's width, so the one that had not yet heard the other's gesture would put that gesture back
    without anybody seeing it happen. So a write of widths older than the ones the record holds is
    refused, the page puts its own back and reads the desk again. A page's own last write is never
    older than what it has heard: its writes go one at a time, and each answer comes in through the
    page's one door before the next is posted.
    """
    _ensure_desk_loaded()
    w = str(w or "main")
    snapshot = None
    with _desk_lock:
        wins = _selection.setdefault("windows", {})
        new_widths = None
        if "widths" in kwargs:
            new_widths = widths_cell(kwargs["widths"])
            heard = kwargs.get("version")
            try:
                heard = None if heard is None or isinstance(heard, bool) else int(heard)
            except (TypeError, ValueError, OverflowError):
                # `Infinity` and `1e400` are JSON a page can send, and `int()` of them overflows:
                # an unreadable version is no version, as from a page older than the check -- not
                # a 500 (the probe's `int(float(x))` was the same trap, #261).
                heard = None
            held_at = int((wins.get(w) or {}).get("widths_at") or 0)
            if heard is not None and held_at > heard:
                raise ServeError(f"window {w!r} was given other widths since this page last heard",
                                 "another page under the same `?w=` moved them; this one reads the "
                                 "desk again, so the next gesture starts from those",
                                 code="widths_stale")
        win = wins.setdefault(w, {
            "focus": False,
            "section": "tickets",
            # Which agent this window has OPEN (#203). Per window, not shared: the left monitor
            # reads one agent while the centre reads another, and `selected` -- which the inspector
            # follows -- stays the one thing every window agrees on.
            "open": "",
            "held": [],
            "read": {},
            "seen": "",
        })
        changed = False
        if "focus" in kwargs and win.get("focus") != bool(kwargs["focus"]):
            win["focus"] = bool(kwargs["focus"])
            changed = True
        if "open" in kwargs and win.get("open") != str(kwargs["open"] or ""):
            win["open"] = str(kwargs["open"] or "")
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
        widths_moved = new_widths is not None and win.get("widths") != new_widths
        if widths_moved:
            win["widths"] = new_widths
            changed = True
        if changed:
            _selection["version"] += 1
            _selection["at"] = E.stamp()
            if widths_moved:
                win["widths_at"] = _selection["version"]
            snapshot = _desk_snapshot()
        state = desk_state()
    _write_desk(snapshot)
    return state



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


FRICTION_REGISTER = "friction.json"         # per agent, in the fleet directory: what the operator dismissed
REINDEX_PER_SNAPSHOT = 2                     # repos whose friction listing changed, re-indexed per snapshot


def _friction_listing(path: str) -> list[str]:
    """`.agent/friction/*.md`, one `listdir`, as `events.friction_files` lists them."""
    return sorted(os.path.basename(p) for p in E.friction_files(path))


def friction_register(name: str) -> dict:
    """`{"dismissed": {"<file name>": "<ts>"}}`, the operator's dismissals for one agent (#499)."""
    try:
        data = json.loads(textio.read_text(os.path.join(agent_dir(name), FRICTION_REGISTER)))
    except (OSError, ValueError):
        return {"dismissed": {}}
    dismissed = data.get("dismissed") if isinstance(data, dict) else None
    return {"dismissed": dict(dismissed) if isinstance(dismissed, dict) else {}}


def _said(text: str) -> str:
    return " ".join(str(text or "").split()).strip().rstrip(".").casefold()


def split_friction(rows: list[dict], state: dict, session_began: str, dismissed: dict) -> tuple[list, list]:
    """(open, earlier): which STOPs need the operator now, and which fold away (#499).

    Open: not dismissed, on the active ticket (or none), and either its unblock sentence is still an
    open question -- the agent is still waiting on it, `asked` -- or it was written in this session.
    Everything else is earlier. `blocking` is the severity rule the tile folds by, and only an open
    row blocks. The friction file is never touched; the fresh `state` decides, not the indexed one.
    """
    from .. import state as STATE

    ticket = str(state.get("active_ticket") or "")
    asked_now = {_said(STATE.question_text(q)) for q in state.get("open_questions") or []
                 if not STATE.is_answered(q)}
    asked_now.discard("")
    began = str(session_began or "")[:16]
    opened, earlier = [], []
    for f in rows:
        name = str(f.get("path") or "").rsplit("/", 1)[-1]
        if name in dismissed:
            continue
        stamp = f.get("stamp") or CAT._friction_stamp(name)
        unblock = _said(f.get("unblock"))
        asked = bool(unblock) and any(unblock == q or (min(len(unblock), len(q)) >= 12 and (unblock in q or q in unblock))
                                      for q in asked_now)
        on_ticket = not f.get("ticket") or not ticket or f.get("ticket") == ticket
        this_session = bool(stamp) and (not began or stamp >= began)
        is_open = on_ticket and (asked or this_session)
        row = {**f, "name": name, "stamp": stamp, "open": is_open, "asked": asked and is_open,
               "blocking": is_open and str(f.get("severity") or "").strip().lower() in agentstate.BLOCKING_SEVERITIES}
        (opened if is_open else earlier).append(row)
    return opened[:DESK_LIMIT], earlier[:DESK_LIMIT]


def _panel_catalogue(cat, repo, budget: list | None) -> tuple[dict, bool]:
    """`cat.show(repo)`, re-indexed first when the friction listing moved under it (#499).

    One `listdir`; `index` only when the names differ from the catalogue's, and at most
    `REINDEX_PER_SNAPSHOT` repos per snapshot (`budget`). A locked catalogue (`ad-fleet index`
    running) answers as it is.
    """
    import sqlite3

    try:
        shown = cat.show(repo.name)
    except CAT.CatalogueError:
        shown = None
    except sqlite3.OperationalError:
        return {}, False
    listed = _friction_listing(repo.path)
    known = sorted(str(f.get("path") or "").rsplit("/", 1)[-1] for f in (shown or {}).get("friction") or [])
    if listed != known and (shown is not None or listed) and (budget is None or budget[0] > 0):
        if budget is not None:
            budget[0] -= 1
        try:
            cat.index([repo])
            shown = cat.show(repo.name)
        except (CAT.CatalogueError, sqlite3.OperationalError):
            pass
    return (shown or {}), shown is not None


def show_for(name: str, _budget: list | None = None) -> dict:
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
        shown, indexed = _panel_catalogue(cat, repo, _budget)
        facts = (shown.get("facts") or {}) if indexed else {}
    if not facts:
        # The same allow-listed read the index does, secret-looking keys dropped by the same rule --
        # duplicating that filter here is how the two would eventually disagree.
        facts = CAT._facts(repo.path)
    state = repo.state()
    rail = LK.links_for(repo, facts, WRAP.state_with_recorded(name, state))
    cells = poll_state(name)
    # The branch from the poll's git cell, which shells out *in this checkout* and is therefore
    # already worktree-correct. The catalogue's own `branch` came from the index, and an index
    # entry is written once for a repository -- so two worktrees of it read the same branch, which
    # is the one string they most need to differ in. The catalogue's `_inside` wall (realpath every
    # read, refuse anything outside the repository) is not touched for the sake of one string.
    polled = ((cells.get("git") or {}).get("value") or {}).get("branch") or ""
    current, _ = split_runs(E.read(name))
    friction_open, friction_earlier = split_friction(shown.get("friction") or [], state,
                                                     current.get("session_began", ""),
                                                     friction_register(name)["dismissed"])
    return {"project": repo.project, "name": name, "repo": name,
            "path": textio.norm_path(repo.path),
            "worktree_of": repo.worktree_of,
            "indexed": indexed, "jira_project": repo.jira_project,
            "branch": polled or shown.get("branch", ""),
            "branch_from": "poll" if polled else ("index" if shown.get("branch") else ""),
            "last_indexed": shown.get("last_indexed", ""),
            "facts": tile_facts(facts), "state": state,
            "friction": (shown.get("friction") or [])[:DESK_LIMIT],
            # What needs the operator now, and what folds under *earlier friction* (#499).
            "friction_open": friction_open, "friction_earlier": friction_earlier,
            "pbip": shown.get("pbip") or [],
            "links": LK.present(rail), "missing": [r for r in rail if not r.get("url")],
            "missing_keys": LK.missing_keys(rail),
            "polls": cells, "verify": verify_for(repo)}


def desk_snapshot() -> dict:
    """Every project's panel, plus the trays, in one request.

    One round trip rather than one per tile: the desk draws N agents at once and #133 puts them
    on a screen the operator is not looking at, so the page asks for the lot on a slow cadence and
    lets the SSE stream carry what is urgent.
    """
    projects, order = {}, []
    try:
        names = [r.name for r in Registry().sorted()]
    except RegistryError:
        names = []
    budget = [REINDEX_PER_SNAPSHOT]
    for name in names:
        try:
            projects[name] = show_for(name, budget)
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


#: Actions that change one repository's row. The page patches that row from the answer instead of
#: fetching the whole fleet again (#219): a `send` cost two round trips, and the second one carried
#: every tile on the desk to redraw one of them. `arrange` and `window` are not here -- they change
#: the *arrangement*, which comes back as `desk` and reaches every window down the stream. `models`
#: is not here either: the model list is the fleet's, not a row's (#361).
def _act_friction(repo: str, body: dict) -> dict:
    """Dismiss friction rows on the panel (#499): the register in the fleet directory, never the file.

    `{repo, dismiss: [names]}` or `{repo, earlier: true}`. Dismissing never answers the question and
    never unblocks the agent; the pane's question card does that.
    """
    if not repo:
        raise ServeError("which agent's friction?", "name the repo: `ad-fleet friction <repo>`", code="no_repo")
    try:
        found = Registry().get(repo)
    except RegistryError as e:
        raise ServeError(e.msg, e.hint or "`ad-fleet repo list` names the registered agents", code="no_repo") from None
    listed = set(_friction_listing(found.path))
    if body.get("earlier"):
        wanted = [r["name"] for r in show_for(repo).get("friction_earlier") or []]
    else:
        wanted = [str(n) for n in body.get("dismiss") or []]
        unknown = [n for n in wanted if n not in listed]
        if unknown or not wanted:
            raise ServeError(f"{', '.join(unknown) or 'nothing'} is not a friction file of {repo}",
                             f"name a file under .agent/friction/: `ad-fleet friction {repo}` lists them",
                             code="not_friction")
    register = friction_register(repo)
    stamp = E.stamp()
    for n in wanted:
        register["dismissed"].setdefault(n, stamp)
    if wanted:
        os.makedirs(agent_dir(repo), exist_ok=True)
        textio.write_json(os.path.join(agent_dir(repo), FRICTION_REGISTER), register)
    return {"repo": repo, "dismissed": wanted, "project": show_for(repo)}


ROW_ACTIONS = ("start", "console", "say", "send", "stop", "reset", "answer", "approve", "deny",
               "adopt", "release", "refresh", "hold", "resume", "attach", "attach-bytes", "fresh")


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
        # `force` spends one more turn past the budget, and it arrives only from a second,
        # deliberate press (#213). Before this the desk called `send` with no force at all, so an
        # over-budget agent was simply unreachable from the page and `ad-fleet send --force` in a
        # terminal was the only door.
        lock = supervisor.send(repo, message, cfg=C.load(), force=bool(body.get("force")))
        return {"repo": repo, "pid": lock["pid"], "row": row_for(repo)}
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
    if what == "shutdown":
        # How `ad-fleet open` replaces an out-of-date desk (#242). Token and loopback, like every
        # other action: this is a local server being asked to stop by the one tool that starts it.
        # The answer goes out first; the stop happens on its own thread, because `shutdown()` waits
        # for the serving loop and the serving loop is waiting for this handler to return.
        server = _SERVING.get("server")
        if server is None:
            raise ServeError("this desk is not serving", "nothing to stop")
        threading.Thread(target=server.shutdown, daemon=True).start()
        return {"stopping": True, "pid": os.getpid()}
    if what == "fresh":
        # Leave this pane's session for a clean one (#488): `ad-fleet fresh`'s two functions. A
        # `second_press` refusal says so, so the page can arm its button for the deliberate press.
        from .. import config as C
        from . import fresh as FRESH

        if not repo:
            raise ServeError("which repository?", "pass {repo}", code="no_repo")
        try:
            if body.get("dry_run"):
                return {"repo": repo, **FRESH.plan(repo, cfg=C.load())}
            return {"repo": repo, **FRESH.run(repo, closed=bool(body.get("closed")), cfg=C.load())}
        except FRESH.FreshRefused as e:
            refused = ServeError(e.msg, e.hint, code=e.code)
            refused.second_press = e.second_press
            raise refused from None
    if what == "renew":
        # Stale only, when idle, previewed first (#241). The page asks with `dry_run` and shows the
        # rows before it asks again without; the CLI verb calls the same two functions.
        from .. import config as C
        from . import renew as RENEW

        names = [str(n) for n in (body.get("repos") or []) if str(n)]
        if body.get("dry_run"):
            return RENEW.plan(names or None)
        return RENEW.run(names or None, cfg=C.load())
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
        if supervisor.live(repo).get("kind") == "console":
            # A console is typed into, never sent to (#190), and `send` refused it -- so the card
            # did nothing, the operator answered in the chat instead, the agent cleared rather than
            # recorded, and the tile went on counting (#231). The same sentence, typed into the
            # window: session-bootstrap turns it into `ad-state answer`, the agent's own writer.
            said = supervisor.say(repo, lifecycle.answers_prompt(answers), cfg=C.load())
            return {"repo": repo, "pid": said["pid"], "answered": [qid for qid, _ in answers],
                    "via": "console"}
        lock = supervisor.send(repo, lifecycle.answers_prompt(answers), cfg=C.load(),
                               force=bool(body.get("force")))
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
        # It is a POST rather than a query parameter because its whole point is that the *other*
        # windows hear about it (#133): the inspector on every screen follows it.
        return select(selected=body.get("repo"))
    if what == "refresh":
        # Read what the next tick would read, NOW. It spends no premium request -- nothing is sent
        # to the agent -- so it is the one button on the tile that is always free to press.
        target = _repo_record(repo)
        now = time.time()
        since = now - _refreshed_at.get(target.name, 0.0)
        if since < REFRESH_FLOOR_S:
            raise ServeError(f"{target.name} was refreshed {since:.1f}s ago",
                             f"it re-reads what the tick reads; once every {REFRESH_FLOOR_S:g}s is "
                             f"as often as that can tell you anything new",
                             code="refresh_busy")
        _refreshed_at[target.name] = now
        try:
            E.refresh(target.name, target.path)
        except (OSError, ValueError):
            pass                                  # a stream that cannot be folded is the tile's news
        live = poller()
        if live is not None:
            try:
                live.now_for(target)
            except Exception:                     # noqa: BLE001 - see poll_tick: one cell never stops the rest
                pass
        return {"repo": target.name, "row": row_for(target.name)}
    if what == "arrange":
        # A page from before #232 still names a `layout`; there is one arrangement, so it is not
        # read.
        return arrange(order=body.get("order"),
                       size=body.get("size"),
                       pinned=body.get("pinned"),
                       hidden=body.get("hidden"))
    if what == "window":
        w = str(body.get("w") or "main")
        kwargs = {k: v for k, v in body.items() if k != "w"}
        return update_window(w, **kwargs)
    if what == "measure":
        # `ad-fleet probe --open <ide>` asking a window to measure, or that window taking the ask.
        return measure(str(body.get("w") or ""), take=body.get("take") is True)
    if what == "probe":
        # What `/probe` measured in this shell (#247). Facts in, one record per shell out to
        # `~/.agentdata/fleet/probes.json`; the answer carries the class `probe.classify` gave it,
        # so the page shows the verdict without holding a rule of its own.
        return PROBE.record(body)
    if what == "load":
        # What a page load measured about itself (#350), kept only while the operator has set
        # `fleet.loads.enabled` in the config file, read now rather than at start. Off is not a
        # refusal: a page served before the switch went off may still post once.
        if not LOADS.enabled():
            return {"kept": 0, "enabled": False}
        return LOADS.record(body)
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
    if what == "friction":
        return _act_friction(repo, body)
    if what == "settings":
        # `C` is imported inside several branches of this function, which makes the name local to
        # the whole of it -- so a branch that uses it without its own import raises UnboundLocalError
        # rather than reading the module. Found by the browser test, as a 500 in a field's tooltip.
        from .. import config as C
        from . import settings as SET

        # Under the config lock (#348): the theme write and the poller's flavour write are the
        # other in-process writers, and two read-modify-writes at once lose one of them.
        with C.LOCK:
            _write_settings(C, SET, body)
        _config_changed()
        answer = settings_snapshot()
        named = {str(item.get("repo") or "") for item in body.get("models") or []}
        if named:
            # The rows a model write changed, as `/api/fleet` would send them (#492): the desk
            # draws them from this answer, so its chip says the switch within a frame of the save.
            answer["rows"] = [row for row in fleet_snapshot().get("repos", []) if row.get("repo") in named]
        return answer
    if what == "theme":
        from .. import config as C

        with C.LOCK:
            _write_theme(C, body)
        _config_changed()
        # The stream's own `theme` payload, css and all (#346): the page that posted reconciles
        # from this answer instead of waiting a tick for the frame to say what it has just chosen.
        return theme_state()
    if what == "models":
        # Ask the Copilot CLI for its model list again (#361), on a thread: the answer goes out at
        # once, and a list that changed reaches every open page as one `models` frame. An ask while
        # a refresh runs joins it. The server's `stopping` ends it with the server.
        from . import models as MODELS

        if body.get("refresh"):
            started = MODELS.start_refresh(getattr(_SERVING.get("server"), "stopping", None), force=True)
            return {"refreshing": True, "started": started}
        return {"refreshing": MODELS.refreshing(), "started": False}
    if what == "wrapup":
        # Preview or write one agent's wrap-up (#503), on a thread as the model refresh is: a preview
        # is five adapter runs, three of them round trips to Jira or Bitbucket, and no request thread
        # waits on that. The answer goes out at once; the rows arrive as `wrapup` frames.
        try:
            if body.get("dry_run"):
                return WRAP.start_plan(repo, str(body.get("mode") or "day"), comment=body.get("comment"),
                                       to=body.get("to") or None, overwrite=body.get("overwrite") or None)
            return WRAP.start_run(str(body.get("job") or ""), list(body.get("steps") or []),
                                  comment=body.get("comment"), to=body.get("to") or None,
                                  overwrite=body.get("overwrite") or None)
        except WRAP.WrapupError as e:
            raise ServeError(e.msg, e.hint, code=e.code) from None
    raise ServeError(f"unknown action {what!r}",
                     "start | send | stop | reset | adopt | release | approve | deny | select | "
                     "arrange | attach | dismiss | theme | settings | models | refresh | probe | "
                     "measure | load | wrapup")


def _write_settings(C, SET, body: dict) -> None:
    """`act("settings")`'s read-modify-write of config.json; the caller holds `C.LOCK`."""
    cfg = C.load()
    try:
        for item in body.get("set") or []:
            SET.apply(cfg, str(item.get("key") or ""), item.get("value"))
        # What only holds between keys, once the whole batch is in: two tier boundaries that
        # only go together can be written together (#235).
        SET.check(cfg, [str(item.get("key") or "") for item in body.get("set") or []])
        for item in body.get("models") or []:
            SET.set_model(cfg, str(item.get("repo") or ""),
                          model=item.get("model"), effort=item.get("effort"))
        if "model" in body or "effort" in body:
            SET.set_fleet_model(cfg, model=body.get("model"), effort=body.get("effort"))
    except SET.SettingsError as e:
        raise ServeError(e.msg, e.hint, code=e.code) from None
    except LAUNCH.LaunchError as e:
        # A model value that would become a second flag. The launch-time check would catch it
        # too, but hours later and as a failed start rather than a refused keystroke.
        raise ServeError(e.msg, e.hint, code="bad_model") from None
    try:
        C.save(cfg)
    except C.ConfigError as e:
        # ConfigError carries `hint` but no `msg`, so it must be translated rather than left to
        # the generic handler, which would report a refusal as a 500.
        raise ServeError(str(e), e.hint, code="config_refused") from None


def _write_theme(C, body: dict) -> None:
    """`act("theme")`'s read-modify-write of config.json; the caller holds `C.LOCK`."""
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


def _model_digests() -> dict[str, str]:
    """What each checkout's next turn will be launched with, as `LAUNCH.model_for` resolves it
    (#492). A model set elsewhere -- `ad-fleet model` in a terminal, /settings in another tab -- is
    a row change no event announces, so the stream compares these when config.json moves and says
    `polls` for the ones that changed. Never raises."""
    from .. import config as C

    try:
        cfg = C.load()
        names = list(Registry().repos)
    except (RegistryError, OSError, ValueError, C.ConfigError):
        return {}
    out = {}
    for name in names:
        try:
            out[name] = json.dumps(LAUNCH.model_for(name, cfg))
        except Exception:                 # noqa: BLE001 - one bad value never stops the stream
            out[name] = ""
    return out


# A config write this server made wakes every open stream (#348). `_config_gen` counts the writes;
# a stream remembers the one its last `theme_state()` saw and waits on `_WAKE` for it to move. Writes
# made elsewhere (`ad-theme set` in a terminal, the poller's flavour write) still arrive by mtime.
_WAKE = threading.Condition()
_config_gen = 0
#: How often a waiting stream looks at `stop`: a server shutting down is not kept a whole tick.
WAKE_SLICE_S = 0.05


def _config_changed() -> None:
    """Called after every successful `C.save` of `act()`: tell every waiting stream."""
    global _config_gen
    with _WAKE:
        _config_gen += 1
        _WAKE.notify_all()


def stream_events(cursors: dict, stop: threading.Event, write, *, heartbeat: float = HEARTBEAT_S,
                  tick: float = TICK_S, once: bool = False, url: str = "",
                  notify_every: float = NOTIFY_EVERY_S, polls: bool = True,
                  agents: bool = True, sweep: bool = True) -> None:
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

    **A config write wakes it** (#348). Between passes the stream waits on `_WAKE` in slices, not on
    `stop` for a whole tick; a write through `act()` ends the wait, and the `theme` frame is written
    at the top of the next pass, before the polls, the fold and the agents' reads. The generation is
    read before `theme_state()`, so a write landing while the frame is computed is not lost.

    `agents=False` (`?frames=theme`, the settings page) skips only the per-agent reads and their
    frames: a page that listens for one frame does not download every agent's history.

    `sweep=False` (#356: `?notify=0`, or `?frames=theme`) skips the notification sweep entirely.
    `notify.sweep` advances ONE shared cursor and hands what it found to whichever stream swept
    first, so a stream that is not a desk's took the desk's `notify` frames and dropped them. With
    only such pages open nothing sweeps, as when no window is open; the next desk stream announces
    what accumulated.

    **The model list** (#361) is looked at the way config.json is: when `models.json` changes on
    disk, a digest of the ids, whether each is offered, and the efforts is compared with the one
    this stream last sent, and a `models` frame goes out only when it moved. The first pass records
    it without a frame: a page fetches `/api/models` itself.
    """
    last_beat = 0.0
    last_sweep = 0.0
    seen_selection = -1
    last_config_mtime = -1.0
    seen_theme_state = None
    seen_model_cfg: dict | None = None
    seen_gen = -1
    woke = False
    from .. import config as C
    from . import models as MODELS
    cfg_file = C.path()
    models_file = MODELS.cache_file()
    models_mark: tuple | None = None
    seen_models: str | None = None
    wrapup_marks: dict = {}
    wrapup_primed = False

    def config_mtime() -> float:
        try:
            return os.path.getmtime(cfg_file) if os.path.isfile(cfg_file) else 0.0
        except OSError:
            return 0.0

    def models_stat() -> tuple:
        try:
            st = os.stat(models_file)
        except OSError:
            return (0, 0)                     # no cache yet: the shipped list
        return (st.st_mtime_ns, st.st_size)

    def models_now() -> tuple[str, str]:
        try:
            cfg = C.load()
        except (C.ConfigError, OSError):
            cfg = {}
        cat = MODELS.catalogue(cfg, spawn=False, path=models_file)
        return MODELS.digest(cat), cat["meta"].get("fetched_at", "")

    def model_rows() -> bool:
        """A model set elsewhere (#492): `polls` for each row whose next turn changed. The first
        look only records; a stream's first snapshot already carries every model."""
        nonlocal seen_model_cfg
        digests, said = _model_digests(), False
        for name, digest in digests.items():
            if seen_model_cfg is not None and seen_model_cfg.get(name) != digest:
                write(f"event: polls\ndata: {json.dumps({'repo': name})}\n\n")
                said = True
        seen_model_cfg = digests
        return said

    seen_polls: dict[str, str] | None = None
    while not stop.is_set():
        early = False
        if woke:
            # This server wrote the config: the frame goes first, before the pass's other work.
            woke = False
            last_config_mtime = config_mtime()
            gen = _config_gen
            tstate = theme_state()
            seen_gen = gen
            if tstate != seen_theme_state:
                seen_theme_state = tstate
                write(f"event: theme\ndata: {json.dumps(tstate, ensure_ascii=False)}\n\n")
                early = True
            if polls and model_rows():
                early = True
        if polls:
            # A cell that changed without an event -- the git cell is the one that never has one
            # (#184) -- would otherwise sit on the tile until some agent said something. One
            # `polls` frame per changed checkout, and the page re-reads the snapshot it draws
            # cells from. Seeded before the first tick, so the first values count as a change:
            # the window's first snapshot was usually read before that tick.
            if seen_polls is None:
                seen_polls = _poll_digests()
            poll_tick()
        # Not behind `polls`: a renew queued for a turn's end (#241) is the fleet's own work, and a
        # desk with project polling switched off must still carry it out.
        renew_tick()
        if sweep and time.time() - last_sweep >= notify_every:
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
        sent = early
        for repo in repos:
            name = repo.name
            if fold:
                try:
                    E.refresh(name, repo.path, repo_state=repo.state())
                except (RegistryError, OSError):
                    pass
            if not agents:
                continue
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

        mtime = config_mtime()
        if seen_theme_state is None or mtime != last_config_mtime:
            last_config_mtime = mtime
            gen = _config_gen                 # before the read, so a write after it wakes the wait
            tstate = theme_state()
            seen_gen = gen
            if seen_theme_state is None or tstate != seen_theme_state:
                seen_theme_state = tstate
                write(f"event: theme\ndata: {json.dumps(tstate, ensure_ascii=False)}\n\n")
                sent = True
            if polls and model_rows():
                sent = True
        mark = models_stat()
        if mark != models_mark:
            # A refresh rewrote the model list (#361). A rewrite that found the same list is no news.
            models_mark = mark
            digest, fetched_at = models_now()
            if seen_models is not None and digest != seen_models:
                frame = {"version": digest, "fetched_at": fetched_at}
                write(f"event: models\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n")
                sent = True
            seen_models = digest
        # A wrap-up job moved (#503): one `wrapup` frame per checkout whose job file changed. The first
        # look only records, as the models list's does; a page asks `GET /api/wrapup` itself.
        for repo in repos:
            try:
                st = os.stat(WRAP.job_path(repo.name))
                mark = (st.st_mtime_ns, st.st_size)
            except OSError:
                mark = None
            if wrapup_primed and wrapup_marks.get(repo.name) != mark and mark is not None:
                job = WRAP.job_state(repo.name)
                frame = {"repo": repo.name, "job": job.get("job", ""), "state": job.get("state", "")}
                write(f"event: wrapup\ndata: {json.dumps(frame, ensure_ascii=False)}\n\n")
                sent = True
            wrapup_marks[repo.name] = mark
        wrapup_primed = True
        if sent or time.time() - last_beat > heartbeat:
            # The heartbeat is not decoration: a proxy that sees no bytes for a minute closes the
            # connection, and the tiles then quietly stop updating with no error anywhere.
            write(f"event: tick\ndata: {json.dumps({'at': time.strftime('%H:%M:%S')})}\n\n")
            last_beat = time.time()
        if once:
            return
        deadline = time.monotonic() + tick
        with _WAKE:
            while (not stop.is_set() and _config_gen == seen_gen
                   and (left := deadline - time.monotonic()) > 0):
                _WAKE.wait(min(left, WAKE_SLICE_S))
            woke = _config_gen != seen_gen


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

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None,
              cache_key: tuple | None = None) -> None:
        extra = dict(extra or {})
        if cache_key is not None and len(body) >= GZIP_FROM and \
                "gzip" in (self.headers.get("Accept-Encoding") or "").lower():
            body = gzip_for(body, cache_key)
            extra["Content-Encoding"] = "gzip"
            # Without this a cache in front of the server could hand the compressed bytes to a
            # client that never asked for them, which reads as a corrupt page rather than as a bug.
            extra["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _refuse(self, code: int, error: str, hint: str = "", refusal_code: str = "",
                second_press: bool = False) -> None:
        payload = {"ok": False, "error": error, "hint": hint}
        if code == 409 or refusal_code:
            payload["code"] = refusal_code or "refused"
        if second_press:
            # A refusal a deliberate second press gets past (#488's `chat_open`): the page arms it.
            payload["second_press"] = True
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
                currency = desk_currency()
                return self._json({"ok": True, "service": "ad-fleet",
                                   "port": self.server.server_address[1],
                                   "version": version_string().split()[1],
                                   "contract": CONTRACT,
                                   # What this process is running, and whether that is still
                                   # what is installed (#242). A launcher replaces a desk that
                                   # says `current: false`; it compares nothing itself.
                                   "loaded": (currency["loaded"] or {}).get("version", ""),
                                   "current": currency["current"]})
            # `page=probe` lands on `/probe` instead of the desk (#247): the one stable address a
            # person can paste into VS Code's Simple Browser to measure it. Only a page this server
            # serves; anything else is the desk, as it always was.
            page = (query.get("page") or [""])[0]
            path = "/" + page if page and ("/" + page) in PAGES else "/"
            forward = [(k, v[0] if isinstance(v, list) and len(v) == 1 else v)
                       for k, vs in query.items() if k not in ("t", "page")
                       for v in (vs if isinstance(vs, list) else [vs])]
            dest = f"{path}?t={self.token}"
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
        if route in PAGES:
            return self._page(PAGES[route], query)
        if route == "/api/fleet":
            return self._json({"ok": True, **fleet_snapshot()})
        if route == "/api/map":
            from . import fleetmap

            # The fleet's structure as one graph (#401): how checkouts and agents relate, read-only.
            snap = fleet_snapshot()
            # Branch lanes (#403) from the git poll's side cache: no git call of the map's own.
            rows = p.branch_rows if (p := current_poller()) else None
            return self._json({"ok": True, **fleetmap.graph(snap, branch_rows=rows),
                               "theme": snap["theme"]})
        if route == "/api/themes":
            from . import skins

            # What is *chosen*, beside what there is to choose from. Without it the pickers could
            # only be filled, never set: the page built its options after the stream had already
            # told it the answer, and rebuilding the options threw that answer away -- so the desk
            # always opened reading "system / no skin" over whatever the config actually said.
            # It is the stream's `theme` payload, css included (#346): a `current` without css was
            # painted as "no palette" and wiped the one the stream had just applied.
            return self._json({"ok": True, "themes": themes(), "skins": skins.list_skins(),
                               "palette_only": skins.PALETTE_ONLY,
                               "current": theme_state()})
        if route == "/api/settings":
            return self._json({"ok": True, **settings_snapshot()})
        if route == "/api/models":
            return self._json({"ok": True, **models_snapshot()})
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
            repo_name = (query.get("repo") or [""])[0]
            if (query.get("row") or [""])[0] == "model":
                # The one row a press on the card changes (#368, decision 15), read on its own from
                # the config and `models.json`: current at once, and never a Jira read.
                return self._json({"ok": True, "key": key.strip().upper(), "repo": repo_name,
                                   "row": PF.model_row(repo_name)})
            return self._json(PF.preflight(key, repo_name))
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
        if route == "/api/wrapup":
            # The wrap-up job's state (#503): reading, planned (with the rows), writing, or done.
            repo_name = (query.get("repo") or [""])[0]
            if not repo_name:
                return self._refuse(400, "repo required", "pass ?repo=<name>")
            try:
                Registry().get(repo_name)
            except RegistryError as e:
                return self._refuse(404, e.msg, e.hint)
            return self._json({"ok": True, "repo": repo_name, **WRAP.job_state(repo_name)})
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

    def _page(self, name: str, query: dict | None = None) -> None:
        """One HTML page, with its own asset URLs carrying this run's token.

        Everything but `/api/ping` and `/open` requires the token, and a relative `href` does not
        inherit the query string the operator opened -- so the page asked for `/static/app.css` and
        `/static/app.js` with no token and was refused, and the dashboard rendered as unstyled HTML
        with no behaviour at all. Every test missed it because a test fetches an asset directly with
        the token already in hand; only a browser asks the way the page asks, and nothing in CI is a
        browser. Found by screenshotting the real server.

        The token is put on here rather than written into the file because it is generated per run.
        The scripts need no help: `common.js` reads `t` out of `location.search` and every fetch
        either page makes goes through its `q()`.

        The desk's `<body>` also carries what `/probe` measured in this window's shell (#248):
        `data-ink-shell` and `data-ink-probe`, the class `probe.classify` gave its record, and
        `data-ink-skins`, the skins that ship a mark table (`ink_skins`). They are on the page
        before any script runs, so the ink layer's gate is decided the moment its module does,
        with no second request and nothing drawn first and taken back.
        """
        html = textio.read_text(os.path.join(STATIC, name))
        # Read once, so the markup and its gzip entry agree about the switch (#351).
        measured = measure_attr(name)
        for asset in ASSETS:
            html = html.replace(f'"/static/{asset}"', f'"/static/{asset}?t={self.token}"')
        ink: tuple = ()
        desk = name == "index.html"
        facts, gate_on = "", False
        if name in INKED_PAGES:
            gate = ink_facts(query or {})
            inked = " ".join(ink_skins())
            ink = (gate["shell"], gate["class"], inked)
            # Words from closed sets (a shell name and a skin family are both `[a-z0-9_-]`, checked
            # before they are written), so nothing here needs escaping.
            facts = (f' data-ink-shell="{gate["shell"]}" data-ink-probe="{gate["class"]}" '
                     f'data-ink-skins="{inked}"')
            # The map (#405) is told the facts and never turns ink on: it keeps `ink-off`.
            gate_on = desk and ink_gate_on(query or {}, gate["class"])
        themed: tuple = ()
        # The chosen theme, in the markup (#345): every page but the probe, which measures a shell
        # and has no business wearing a skin.
        if name != "probe.html":
            ts = theme_state()
            worn = page_theme(ts, self.token, desk=desk, gate_on=gate_on)
            # The desk alone preloads what its skin will import (#349), ahead of the skin's
            # stylesheet, which stays the last thing in <head>.
            preload = ink_preload(ts, self.token, gate_on=gate_on) if desk else ""
            themed = (worn["html"], worn["link"], worn["body_class"], worn["body"], preload)
            html = html.replace('<html lang="en">', '<html lang="en"' + worn["html"] + measured + ">", 1)
            html = html.replace("</head>", preload + worn["link"] + "</head>", 1)

            def dress(m):
                own = m.group(1) or ""
                # A page that already wears `ink-off` (/map, #405) is not given it twice.
                extra = "" if worn["body_class"] in own.split() else worn["body_class"]
                classes = " ".join(c for c in (own, extra) if c)
                return ("<body" + (f' class="{classes}"' if classes else "") + worn["body"] + facts + ">")
            html = re.sub(r'<body(?: class="([^"]*)")?>', dress, html, count=1)
        stamp = os.stat(os.path.join(STATIC, name))
        # `name` leads the cache key rather than the literal it used to be: `gzip_for` requires a
        # key that names everything it was made from, and two pages sharing one entry would serve
        # whichever was compressed first to both. The desk's shell and its class are in it too, and
        # the theme every page but the probe now wears.
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                   cache_key=(name, stamp.st_mtime_ns, stamp.st_size, self.token) + ink + themed
                   + (measured,))

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
        stamp = os.stat(path)
        with open(path, "rb") as f:
            body = f.read()
        # Decided from the *base* type, before the charset is appended -- and not from what this
        # machine happens to call a `.js` file. `mimetypes` reads the registry on Windows, where
        # `.js` is commonly `application/javascript`; deciding after the append left that failing
        # both tests ("text/" and "…javascript") and the script went out uncompressed there and
        # nowhere else. Whether a file is text is a fact about the file, not about the host.
        base = mimetypes.guess_type(path)[0] or "application/octet-stream"
        # Text compresses; a skin's PNG does not, and gzipping it would spend CPU to grow it.
        texty = base.startswith("text/") or base.endswith(("javascript", "json", "xml", "svg+xml"))
        ctype = base + ("; charset=utf-8" if texty else "")
        if base == "text/css":
            body = _tokenize_css_urls(body.decode("utf-8"), self.token).encode("utf-8")
        self._send(200, body, ctype,
                   cache_key=(name, stamp.st_mtime_ns, stamp.st_size, self.token) if texty else None)

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
            # `?frames=theme` (#348): the settings page listens for one frame, not the agents' history.
            frames = (query.get("frames") or [""])[0].split(",")
            # Only a desk's stream sweeps (#356): the sweep's cursor is shared, so a stream that
            # does not draw `notify` frames (`?notify=0`, `?frames=theme`) would take the desk's.
            notify = (query.get("notify") or [""])[0]
            stream_events(cursors, getattr(self.server, "stopping", threading.Event()), write,
                          url=url, agents="theme" not in frames,
                          sweep=notify != "0" and "theme" not in frames)
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
            out = act(what, body)
            # The row this action changed, with the answer (#219). One round trip where there
            # were two, and the tile is patched from what the server already had in hand rather
            # than from a second snapshot of the whole fleet.
            if what in ROW_ACTIONS:
                changed = str(out.get("repo") or body.get("repo") or "")
                if changed:
                    row = row_for(changed)
                    if row:
                        out = {**out, "row": row}
            return self._json({"ok": True, "action": what, **out})
        except (ServeError, RegistryError, supervisor.SupervisorError,
                approval.ApprovalError, IN.InboxError, CAT.CatalogueError,
                HO.HandoffError, SCOPE_ERROR, PROBE.ProbeError, LOADS.LoadError) as e:
            # The same refusal the CLI gives, with the same hint. One vocabulary.
            ref_code = getattr(e, "code", "") or "refused"
            return self._refuse(409, e.msg, getattr(e, "hint", ""), refusal_code=ref_code,
                                second_press=bool(getattr(e, "second_press", False)))
        except Exception as e:               # noqa: BLE001 - a button must never 500 silently
            from ..log import debug_exc

            debug_exc("fleet serve action")
            return self._refuse(500, str(e)[:300], "check the console running `ad-fleet serve`")


# ---------------------------------------------------------------------------------- the settings


# How many of a repository's newest events to look through for the model a turn actually ran on.
# The stream carries one per assistant message, so the last few hundred is comfortably the last
# turn without reading a log that has been growing all week.
MODEL_LOOKBACK = 300


def served_model(name: str) -> str:
    """The model the last turn actually ran on, from the stream -- not the one that was asked for.

    These are two different facts and the page prints both. A tenant may pin a model, and a settings
    page that reported only what was configured would show a value that is not what ran, which is
    the failure mode the whole Power BI sign-in epic was about in another guise.
    """
    return models_in_stream(name)[0]


def models_in_stream(name: str) -> tuple[str, str | None, str]:
    """`(actual, launched, turn)` from one read of the stream's newest events (#492).

    `actual` is `served_model`'s: the model the newest reply ran on. `launched` is the `--model` the
    newest turn was started with, from its `started` event (`""` for no flag), or None when that
    event predates the field or there is none -- then the desk cannot tell a switch waiting for the
    next turn from a pinned tenant, and does not try. `turn` is what that newest turn has reported
    so far, `""` before its first reply: a reply from the turn before it is not this turn's news.
    """
    try:
        rows = E.read(name, kinds=("assistant_text", "started"), limit=MODEL_LOOKBACK)
    except (OSError, ValueError):
        return "", None, ""
    actual, launched, turn, started = "", None, "", False
    for ev in reversed(rows):
        data = ev.get("data") or {}
        if ev.get("kind") == "started":
            if not started:
                started = True
                if "model" in data:
                    launched = str(data.get("model") or "").strip()
        elif not actual:
            actual = str(data.get("model") or "").strip()
            if actual and not started:
                turn = actual
        if actual and started:
            break
    return actual, launched, turn


def settings_snapshot() -> dict:
    """Everything `/settings` renders: the model per repository, the editable keys, the tool lists.

    Assembled server-side rather than left to the page to join, so the page has no rule of its own
    to keep in step -- the effect-scope it prints beside each control comes back from here, and
    cannot drift from what the code actually does.
    """
    from .. import config as C
    from . import models as MODELS, settings as SET

    cfg = C.load()
    try:
        repos = Registry().sorted()
    except (RegistryError, OSError):
        repos = []
    rows, seen = [], []
    for repo in repos:
        entry = C.get_leaf(cfg, "fleet.models", repo.name, {}) or {}
        model, effort, source = LAUNCH.model_for(repo.name, cfg)
        actual = served_model(repo.name)
        if actual and actual not in seen:
            seen.append(actual)
        rows.append({"repo": repo.name,
                     "model": str(entry.get("model") or ""),
                     "effort": str(entry.get("effort") or ""),
                     "resolved": model, "resolved_effort": effort, "source": source,
                     "effort_source": LAUNCH.effort_source(repo.name, cfg),
                     "actual": actual})
    return {
        "model": {"fleet": {"model": str(C.get(cfg, "fleet.model") or ""),
                            "effort": str(C.get(cfg, "fleet.effort") or "")},
                  "repos": rows,
                  # The ids the last turns really ran on, kept for a page that still reads them.
                  # Which names and efforts the installed CLI accepts is measured now (#360): the
                  # whole list is `GET /api/models`, and these efforts are that catalogue's.
                  "seen": seen,
                  "efforts": MODELS.catalogue(cfg, spawn=False)["efforts"]},
        "editable": SET.describe(cfg),
        "current": SET.current(cfg),
        # What the desk draws with, which is not what `current` says when the file holds a four
        # that does not go together: then it is CI's, and `invalid` says why (#235).
        "tiers": SET.tiers(cfg),
        "tools": SET.tools(cfg),
    }


def models_snapshot() -> dict:
    """`GET /api/models` (#361): the catalogue a picker offers, read from the cache, else the list
    shipped with this package marked stale, and whether a refresh is running. Never starts the CLI:
    that is `POST /api/models {refresh: true}`, or a server starting."""
    from .. import config as C
    from . import models as MODELS

    try:
        cfg = C.load()
    except (C.ConfigError, OSError):
        cfg = {}
    try:
        repos = Registry().sorted()
    except (RegistryError, OSError):
        repos = []
    return {"refreshing": MODELS.refreshing(),
            **MODELS.catalogue(cfg, seen=[served_model(r.name) for r in repos], spawn=False)}


# ------------------------------------------------------------------------------------- the theme


def themes() -> list[dict]:
    """Palettes from agentdata.theme, rendered through theme.to_css()."""
    from .. import theme as T
    from . import skins

    out = []
    for t in T.list_themes():
        if t.name == "none":
            continue
        c = T.to_css(t, panels=skins.panels_on(t.name))   # the tokens `theme_state` serves (#328)
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


# What this process was started on (#242). `ad-fleet serve` is long-running: after `ad-update` it
# keeps serving the code it imported, while `/api/ping`'s `version` -- read from the installed
# metadata on every call -- already names the new one. So the running desk could not tell that it
# was older than the thing it reported. Captured when a server is built, not at import, because a
# test or a CLI verb that imports this module is not a desk.
LOADED: dict | None = None


def desk_currency() -> dict:
    """`{loaded, installed, current, reason}`: is the running desk the installed one?

    The CLI half only -- version and commit. Skills are the agents' concern (#240); the desk does not
    read them. Judged here, by the server, so a shell only ever reads the answer (#100's rule).
    """
    from . import fingerprint as FP

    try:
        installed = FP.current()
    except Exception:                        # noqa: BLE001 - an unreadable install is not a dead desk
        installed = None
    if LOADED is None or installed is None:
        return {"loaded": LOADED, "installed": installed, "current": True, "reason": ""}
    same = LOADED.get("version") == installed.get("version") and (
        not LOADED.get("commit") or not installed.get("commit")
        or LOADED.get("commit") == installed.get("commit"))
    reason = "" if same else (f"the desk is running {FP._label(LOADED)} · installed "
                              f"{FP._label(installed)} — `ad-fleet open` replaces it")
    return {"loaded": LOADED, "installed": installed, "current": same, "reason": reason}


def build(port: int = 8765, *, token: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    """Bind and return the server, without serving. `port=0` picks a free one."""
    global LOADED
    from . import fingerprint as FP

    try:
        LOADED = FP.current()
    except Exception:                        # noqa: BLE001 - see `desk_currency`
        LOADED = None
    handler = type("BoundHandler", (Handler,), {"token": token or secrets.token_urlsafe(24)})

    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR permits two *live* sockets on one port, so a second
        # `ad-fleet serve --port 8765` would bind happily and the two would split requests at
        # random. On POSIX the same flag only shortens TIME_WAIT, which is worth keeping.
        allow_reuse_address = os.name != "nt"
        # How long closing waits for the requests still being answered (#245).
        close_wait_s = 5.0

        def __init__(self, *args, **kwargs):
            # Before the bind: a taken port makes the base class call `server_close()` from here.
            self.stopping = threading.Event()
            self.handlers: list[threading.Thread] = []
            self.handlers_lock = threading.Lock()
            super().__init__(*args, **kwargs)

        # The handler threads are daemons, so Ctrl-C never waits on an open stream -- and the
        # standard library's `server_close` joins only non-daemon ones. A request still being
        # answered went on after the server had closed: in one process that runs one desk that is
        # harmless, but a suite runs a desk per test, and a window write finishing late landed in
        # the NEXT test's desk (#245). Closing now says `stopping`, which ends every stream on its
        # next tick, and waits a bounded time for whatever is left.
        def process_request(self, request, client_address):
            t = threading.Thread(target=self.process_request_thread,
                                 args=(request, client_address), daemon=True)
            with self.handlers_lock:
                self.handlers = [h for h in self.handlers if h.is_alive()]
                self.handlers.append(t)
            t.start()

        def server_close(self):
            self.stopping.set()
            super().server_close()
            deadline = time.monotonic() + self.close_wait_s
            with self.handlers_lock:
                left = list(self.handlers)
            for t in left:
                t.join(max(0.0, deadline - time.monotonic()))

    try:
        server = Server(("127.0.0.1", port), handler)
    except OSError as e:
        raise ServeError(f"cannot bind 127.0.0.1:{port} ({e})",
                         "something else is on that port; `ad-fleet serve --port 0` picks a free one") from None
    server.daemon_threads = True             # Ctrl-C must not wait on an open SSE connection
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


_SERVING: dict = {"server": None}


def run(server: ThreadingHTTPServer) -> None:
    _SERVING["server"] = server
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        _SERVING["server"] = None
        server.stopping.set()
        server.shutdown()
        server.server_close()
        forget()
        drop_handles()   # the poller, the inbox and the catalogue handle are this run's, not the next's
