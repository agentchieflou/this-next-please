"""Start fresh: leave the session a checkout is on for a clean one, in one call (#488).

The operator's words: *it still does not feel intuitive to exit out of a stale session (that may
have come from a native copilot CLI chat) with a fresh clean session.* Nothing meant "leave this
session for a fresh one", and the pieces that came close refused each other: *+ new session* met
`live_agent` on an adopted pane and `mid_ticket` on any pane mid-ticket, and renew (#241) takes
every stale agent at once and never an adopted one.

`plan(name)` says what a fresh start would leave, what it would start, and whether it can happen
now. It changes nothing. `run(name)` plans again -- it never trusts a plan a page drew earlier --
and does it: it stops following an adopted chat if there is one (`adopt.release`, which only ever
removes a lock the fleet did not create) and calls `supervisor.start(new=True)` on the active
ticket, on the configured model (SESS-D4), with a sentence saying which session it left. The old
session stays listed, marked `left`, and nothing is deleted.

The verdicts, first match wins:

1. `mid_turn` -- a fleet turn is running. A session changes between turns, never during one, and
   nothing is queued (SESS-D5).
2. `console_window` -- a console the fleet opened is the operator's window (#189).
3. `needs_you` -- a fresh session would bury the question the agent is waiting on.
4. `foreign_session` -- a Copilot the fleet did not start is named by pid in the checkout. The fleet
   never ends it and never starts beside it, and `closed` never overrides this (SESS-D3).
5. `second_press` / `chat_open` -- the operator's own chat may still be open, known only by its
   session file or by an adopted lock that is still live. The first call refuses; a deliberate
   second one (`closed=True`: "my chat there is closed") proceeds (SESS-D2).
6. `now`.

`plan_listed` is the same judgement from a listing the caller already holds -- the desk's snapshot
(`row.fresh`) and a fleet-wide preview (#508) take one listing for every repository, and never a
fresh one per row.
"""
from __future__ import annotations
import os

from .registry import Registry

NOW, SECOND_PRESS, REFUSED = "now", "second_press", "refused"

# Said once, on the fresh session's first turn, after whatever the configured template says.
WHY = (" This is a fresh session: the operator left session {session} ({surface}{stale}). "
       "The work continues from .agent/state.json, not from the beginning.")
WHY_NOTHING_LEFT = " This is a fresh session. The work continues from .agent/state.json, not from the beginning."

SURFACE = {"adopted": "your own chat", "console": "a console", "fleet": "a fleet session"}

# What the row's `because` says, for each reason the pane offers *start fresh* (#489 draws it).
BECAUSE_CHAT, BECAUSE_OUTSIDE, BECAUSE_STALE = "your own chat", "began outside the fleet", "old skills"


class FreshRefused(Exception):
    """A plan whose verdict is not `now`, in the CLI's and the page's one vocabulary."""

    def __init__(self, row: dict):
        super().__init__(row.get("why", ""))
        self.row = row
        self.msg = row.get("why", "")
        self.hint = row.get("hint", "")
        self.code = row.get("code", "") or "refused"
        self.second_press = row.get("verdict") == SECOND_PRESS


def _age_words(seconds) -> str:
    from .serve import format_age_str

    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "a moment"
    return format_age_str(s) if s >= 0 else "a moment"


def _session_title(name: str, session: str) -> str:
    if not session:
        return ""
    try:
        from . import sessions as SESS

        for row in SESS.load_sessions(name):
            if row.get("id") == session:
                return str(row.get("title") or "")
    except Exception:                        # noqa: BLE001 - a title is a nicety, never a refusal
        pass
    return ""


def _leaves(name: str, stream: list[dict], lock: dict, stale: dict) -> dict:
    """The session a fresh start would leave: `session_id()`'s, or the adopted lock's."""
    from . import supervisor
    from .serve import run_origin

    last = next((ev for ev in reversed(stream) if ev.get("kind") == "started"), {})
    origin = run_origin(last.get("data") or {}) if last else ""
    if lock.get("external"):
        origin = "console" if lock.get("kind") == "console" else "adopted"
    session = str(lock.get("session") or "") if lock.get("external") else ""
    session = session or supervisor.session_id(stream)
    return {"session": session, "title": _session_title(name, session), "origin": origin,
            "stale": stale}


def _starts(name: str, st: dict, cfg: dict | None) -> dict:
    """The ticket and the model a fresh session would start on: the configured model, never the
    chat's (SESS-D4), from the one call `_model_cells` makes too."""
    from . import agentstate, launch as LAUNCH

    phase = str(st.get("phase") or "")
    ticket = "" if phase in agentstate.TERMINAL_PHASES else str(st.get("active_ticket") or "")
    try:
        model, effort, source = LAUNCH.model_for(name, cfg)
        effort_source = LAUNCH.effort_source(name, cfg)
    except Exception:                        # noqa: BLE001 - a malformed setting is start's to refuse
        model, effort, source, effort_source = "", "", "cli-auto", "cli-auto"
    return {"ticket": ticket, "model": model, "effort": effort, "model_source": source,
            "effort_source": effort_source}


def seen_from(name: str, offer: dict | None) -> dict:
    """`adopt.outside`'s answer, from a candidate row the caller already listed.

    The same weighing `outside` does, without a listing of its own: the fleet's own pid and
    session, and this process, are never somebody else's, and where the listing places processes a
    pid-less candidate names nothing.
    """
    from . import adopt as A

    if not offer:
        return {}
    ours, sessions = A.fleets_own(name)
    ours.add(os.getpid())
    pid = int(offer.get("pid") or 0)
    if pid in ours:
        pid = 0
    session, session_file = str(offer.get("session") or ""), str(offer.get("session_file") or "")
    if session in sessions:
        session, session_file = "", ""
    if not pid and (not session or A.listing_places()):
        return {}
    how = offer.get("how", "") if pid or session_file else "inferred from recent activity"
    return {"pid": pid, "how": how, "session": session, "session_file": session_file,
            "age_s": offer.get("session_age_s") if session_file else offer.get("active_age_s")}


def judge(name: str, *, st: dict, stream: list[dict], lock: dict, derived_state: str,
          seen: dict, stale: dict, cfg: dict | None = None) -> dict:
    """The verdict, from what the caller has in hand. Reads no listing and changes nothing."""
    from .. import state as STATE
    from . import agentstate

    row = {"repo": name, "leaves": _leaves(name, stream, lock, stale),
           "starts": _starts(name, st, cfg)}

    def no(code: str, why: str, hint: str) -> dict:
        return {**row, "verdict": REFUSED, "code": code, "why": why, "hint": hint}

    external = bool(lock.get("external"))
    if lock and not external and lock.get("kind") != "console":
        return no("mid_turn", "a session changes between turns — press again when this one ends",
                  f"wait for this turn to end, then `ad-fleet fresh {name}` again; nothing is queued")
    if lock.get("kind") == "console":
        return no("console_window",
                  f"close that window; `ad-fleet console {name} --new` opens a fresh one",
                  "a console the fleet opened is your window, and the fleet does not close it")
    phase = str(st.get("phase") or "")
    if agentstate.needs_the_human(derived_state) or phase == "blocked" or any(
            STATE.is_blocking(q) for q in (st.get("open_questions") or [])):
        return no("needs_you", "answer it first — a fresh session would bury the question",
                  f"answer the question on the pane (or `ad-fleet answer {name}`), then start fresh")
    pid = int(seen.get("pid") or 0) or (int(lock.get("pid") or 0) if external else 0)
    if pid:
        return no("foreign_session",
                  f"your own Copilot chat is open in {name} (pid {pid}) — close it there, then start fresh",
                  f"close it in its own window, then `ad-fleet fresh {name}`; the fleet does not end a "
                  f"chat it did not start")
    if external or seen.get("session_file"):
        how = (lock.get("how") if external else seen.get("how")) or "adopted"
        if external and lock.get("session_file"):
            try:
                import time

                age = time.time() - os.path.getmtime(str(lock["session_file"]))
            except OSError:
                age = -1
        else:
            age = seen.get("age_s", -1)
        return {**row, "verdict": SECOND_PRESS, "code": "chat_open",
                "why": f"your own Copilot chat may still be open in {name} ({how}, last wrote "
                       f"{_age_words(age)} ago) — close it there, then start fresh again",
                "hint": f"once it is closed, `ad-fleet fresh {name} --closed` (on the pane, press start "
                        f"fresh again)"}
    return {**row, "verdict": NOW, "code": "", "why": "nothing is in the way: it starts now", "hint": ""}


def _pieces(name: str, reg: Registry, *, refresh: bool = False) -> tuple:
    """What `judge` reads. `refresh` brings the stream up to date first, the way the snapshot does --
    `run` asks for it; `plan` writes nothing, and reads the open questions from `state.json`, which
    is the record of what is open whether or not the stream has caught up (#231)."""
    from . import agentstate, events as E, supervisor
    from .serve import _stale_cell, split_runs
    from . import fingerprint as FP

    repo = reg.get(name)
    st = repo.state() or {}
    if refresh:
        try:
            E.refresh(name, repo.path, repo_state=st)
        except OSError:
            pass
    stream = E.read(name)
    lock = supervisor.live(name)
    curr, _ = split_runs(stream, live=bool(lock))
    derived = agentstate.derive(curr["events"] or stream, live=bool(lock),
                                open_questions=(st.get("open_questions") or []) if st else None)
    try:
        installed = FP.current()
    except Exception:                        # noqa: BLE001 - as the snapshot reads it
        installed = None
    return repo, st, stream, lock, derived["state"], _stale_cell(stream, installed)


def plan_listed(name: str, offers: dict, *, registry: Registry | None = None,
                cfg: dict | None = None) -> dict:
    """`plan`, judged from a listing the caller already took (`{repo: adopt.candidates row}`).

    For a fleet-wide preview (#508): one `agent_processes(max_age=0)` for every repository, instead
    of one per row. `run` still takes its own fresh listing per repository.
    """
    reg = registry or Registry()
    _repo, st, stream, lock, state, stale = _pieces(name, reg)
    return judge(name, st=st, stream=stream, lock=lock, derived_state=state,
                 seen=seen_from(name, (offers or {}).get(name)), stale=stale, cfg=cfg)


def plan(name: str, *, registry: Registry | None = None, cfg: dict | None = None,
         refresh: bool = False) -> dict:
    """What a fresh start would leave and start, and whether it can happen now. Changes nothing.

    Takes a fresh listing where the listing can place a process, as a start does: a cached one can
    name a pid that has gone, or miss a chat opened a moment ago.
    """
    from . import adopt as A

    reg = registry or Registry()
    _repo, st, stream, lock, state, stale = _pieces(name, reg, refresh=refresh)
    fresh = A.listing_places()
    seen = {} if lock else A.outside(name, registry=reg, fresh_listing=fresh, wait=fresh)
    return judge(name, st=st, stream=stream, lock=lock, derived_state=state, seen=seen,
                 stale=stale, cfg=cfg)


def prompt(name: str, planned: dict, cfg: dict | None, *, summary: str = "") -> str:
    from . import launch as LAUNCH

    leaves = planned["leaves"]
    text = LAUNCH.prompt_for(planned["starts"]["ticket"] or None, None, cfg, summary=summary)
    if not leaves.get("session"):
        return text + WHY_NOTHING_LEFT
    stale = leaves.get("stale") or {}
    return text + WHY.format(session=leaves.get("title") or leaves["session"],
                             surface=SURFACE.get(leaves.get("origin") or "fleet", "a fleet session"),
                             stale=f"; {stale.get('reason') or 'stale'}" if stale.get("stale") else "")


def run(name: str, *, closed: bool = False, cfg: dict | None = None,
        registry: Registry | None = None) -> dict:
    """Plan again and, for `now` -- or `second_press` with `closed` -- do it, in one call.

    Raises `FreshRefused` for any other verdict, and `supervisor.SupervisorError` in `start`'s own
    words when `start` refuses. A released adoption is not undone on a refusal: it is only a lock the
    fleet stops following.
    """
    from . import adopt as A, supervisor

    reg = registry or Registry()
    planned = plan(name, registry=reg, cfg=cfg, refresh=True)
    if planned["verdict"] == REFUSED or (planned["verdict"] == SECOND_PRESS and not closed):
        raise FreshRefused(planned)
    released = False
    if supervisor.read_lock(name).get("external"):
        released = bool(A.release(name, registry=reg).get("released"))
    repo = reg.get(name)
    st = repo.state() or {}
    ticket = planned["starts"]["ticket"]
    leaves = planned["leaves"]
    lock = supervisor.start(name, key=ticket or None, prompt=prompt(name, planned, cfg,
                                                                     summary=str(st.get("summary") or "")),
                            new=True, cfg=cfg, registry=reg, summary=str(st.get("summary") or ""),
                            leaves={"session": leaves.get("session") or "",
                                    "origin": leaves.get("origin") or ""})
    # `ad-fleet sessions` reads the index: it says `left` from the moment the fresh one began.
    try:
        from . import sessions as SESS

        SESS.rebuild_sessions(name, repo_path=repo.path)
    except Exception:                        # noqa: BLE001 - the index is a fold, rebuilt on any read
        pass
    return {**planned, "done": "started", "pid": lock.get("pid"), "released": released}


def row_cell(row: dict, *, st: dict, stream: list[dict], lock: dict, offer: dict | None,
             cfg: dict | None) -> dict:
    """`row.fresh`, derived and never stored: whether the pane offers *start fresh*, why, and what
    pressing it would do. From the snapshot's own pieces and its `offers`: a tick spawns nothing."""
    from . import models as M

    origin = (row.get("run") or {}).get("origin") or ""
    stale = row.get("stale") or {}
    if row.get("external"):
        because = BECAUSE_CHAT
    elif origin == "adopted":
        because = BECAUSE_OUTSIDE
    elif stale.get("stale"):
        because = BECAUSE_STALE
    else:
        because = ""
    try:
        judged = judge(row.get("repo", ""), st=st, stream=stream, lock=lock,
                       derived_state=str(row.get("state") or ""),
                       seen=seen_from(row.get("repo", ""), offer), stale=stale, cfg=cfg)
    except Exception:                        # noqa: BLE001 - a tile never fails to draw over a verdict
        return {"offer": bool(because), "because": because, "verdict": "", "why": "",
                "starts": {"ticket": "", "model_label": "", "model_source": ""}}
    starts = judged["starts"]
    return {"offer": bool(because), "because": because, "verdict": judged["verdict"],
            "code": judged.get("code", ""), "why": judged["why"],
            "leaves": {k: judged["leaves"].get(k, "") for k in ("session", "title", "origin")},
            "starts": {"ticket": starts["ticket"],
                       "model": starts["model"],
                       "model_label": M.label(starts["model"]) if starts["model"] else "",
                       "model_source": starts["model_source"],
                       "effort": starts["effort"], "effort_source": starts["effort_source"]}}


# ------------------------------------------------------------------------ a fresh day (#508)
#
# `ad-fleet fresh --all`: #488's `plan` and `run` over the whole fleet, previewed and confirmed. The
# operator: *a way to start the fleet with all sessions fresh (envisioning beginning a day)*. It is
# a loop over the one-pane door with three checks only a sweep needs, and it never acts on the
# operator's own chat: #488's *adopted, then quiet -> now* is right for a press on that pane and
# wrong for a sweep, so the sweep skips it before #488 is asked (#497's non-goal).

SKIPPED, CHANGED = "skipped", "changed"

YOUR_OWN_CHAT = ("your own Copilot chat — a sweep never acts on it; start fresh on its pane (Alt+N) "
                 "when you are done with it")
CHAT_OPEN_SWEEP = "your own chat may still be open — close it, then start fresh on its pane"
KEYLESS_WHY = "no ticket in progress — a keyless session runs session-bootstrap, then router"
NOT_BEGUN_WHY = "today's fresh start did not begin"


def _is_session_start(event: dict) -> bool:
    """A `started` that began a session: not a resume, or marked `new`, or adopted from outside --
    the boundary `supervisor.session_id()` applies. A Send or a Reset is a run, never a session."""
    if event.get("kind") != "started":
        return False
    data = event.get("data") or {}
    return bool(not data.get("resumed") or data.get("new") or data.get("adopted") or data.get("external"))


def session_began(stream: list[dict]) -> str:
    """The `ts` of the `started` that began the current session, or "" when there is none.

    The day boundary is when the *session* started, never when the current run did: a Send this
    morning on yesterday's session begins a run today on yesterday's session (#497).
    """
    for event in reversed(stream or []):
        if _is_session_start(event):
            return str(event.get("ts") or "")
    return ""


def _session_has_id(stream: list[dict]) -> bool:
    """Did the current session get as far as a session id?"""
    for event in reversed(stream or []):
        data = event.get("data") or {}
        if event.get("kind") == "session_id" and data.get("session"):
            return True
        if _is_session_start(event):
            return bool(data.get("session"))
    return False


def _midnight() -> float:
    """Today's local midnight, as an epoch."""
    import time

    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _epoch(stamp: str) -> float | None:
    """The stream's clock is UTC, second resolution, no zone suffix (`events.stamp`)."""
    import calendar
    import time

    try:
        return float(calendar.timegm(time.strptime(str(stamp).replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return None


def before_today(began: str) -> bool:
    """Did this session begin before today's local midnight? An unknown beginning counts as before."""
    at = _epoch(began) if began else None
    return at is None or at < _midnight()


def _local_hm(began: str) -> str:
    import time

    at = _epoch(began)
    return time.strftime("%H:%M", time.localtime(at)) if at is not None else "?"


def _first_question(st: dict) -> dict:
    from .. import state as STATE

    for q in (st.get("open_questions") or []):
        if STATE.is_blocking(q):
            return {"id": str(q.get("id") or ""), "q": str(q.get("q") or "")} if isinstance(q, dict) \
                else {"id": "", "q": str(q)}
    return {}


def _sweep_row(name: str, reg: Registry, *, seen: dict, keyless: bool, cfg: dict | None) -> dict:
    """One agent's row in a fresh day, from the pieces `judge` reads plus the sweep's own checks."""
    from .serve import run_origin

    _repo, st, stream, lock, state, stale = _pieces(name, reg)
    began = session_began(stream)
    last = next((ev for ev in reversed(stream) if ev.get("kind") == "started"), {})
    extra = {"began": began, "ticked": False, "keyless": False}
    # 1. Before #488's verdicts: the operator's own chat, adopted or external, live or gone quiet.
    #    `adopt.release` is never reached from here.
    if lock.get("external") or (last and run_origin(last.get("data") or {}) == "adopted"):
        row = {"repo": name, "leaves": _leaves(name, stream, lock, stale), "starts": _starts(name, st, cfg)}
        return {**row, **extra, "verdict": SKIPPED, "code": "your_own_chat", "why": YOUR_OWN_CHAT,
                "hint": f"`ad-fleet fresh {name}` on its own, once your chat there is closed"}
    # 2. #488's verdicts.
    row = {**judge(name, st=st, stream=stream, lock=lock, derived_state=state, seen=seen, stale=stale,
                   cfg=cfg), **extra}
    if row["verdict"] == SECOND_PRESS:
        return {**row, "why": CHAT_OPEN_SWEEP}
    if row["verdict"] != NOW:
        if row["code"] == "needs_you":
            row["question"] = _first_question(st)
        return row
    # 3. After a `now`: already on today's session.
    if began and not before_today(began):
        if _session_has_id(stream):
            return {**row, "verdict": SKIPPED, "code": "fresh_today",
                    "why": f"already on today's session (began {_local_hm(began)})",
                    "hint": f"`ad-fleet fresh {name}` on its own if you mean a second one today"}
        row["why"] = NOT_BEGUN_WHY
    # 4. A `now` with no ticket: tickable, and ticked only when asked for (DAY-D1).
    if not row["starts"]["ticket"]:
        return {**row, "code": "keyless", "keyless": True, "ticked": bool(keyless), "why": KEYLESS_WHY}
    return {**row, "ticked": True}


def _plan_id(rows: list[dict]) -> str:
    """A hash of each row's stable fields. No ages or timestamps: two plans with nothing changed agree."""
    import hashlib
    import json

    stable = [[r["repo"], r["verdict"], r.get("code", ""), r["starts"].get("ticket", ""),
               (r.get("leaves") or {}).get("session", ""), r["starts"].get("model", ""),
               r["starts"].get("effort", ""), bool(r.get("ticked"))] for r in rows]
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def plan_all(names: list[str] | None = None, *, registry: Registry | None = None,
             keyless: bool = False, cfg: dict | None = None) -> dict:
    """Every agent's row in a fresh day, and what confirming it would spend. Changes nothing.

    One process listing for the whole fleet (`agent_processes(max_age=0)`, once), handed to each
    row's judgement: a preview of twenty agents is not twenty listings.
    """
    from . import adopt as A

    reg = registry or Registry()
    wanted = [str(n) for n in (names or []) if str(n)]
    repos = [r for r in reg.sorted() if not wanted or r.name in wanted]
    unknown = sorted(set(wanted) - {r.name for r in repos})
    try:
        listing = A.agent_processes(max_age=0)
        offers = {c["repo"]: c for c in A.candidates(reg, processes=listing)}
    except Exception:                        # noqa: BLE001 - a listing never blocks a preview
        offers = {}
    rows = [_sweep_row(r.name, reg, seen=seen_from(r.name, offers.get(r.name)), keyless=keyless, cfg=cfg)
            for r in repos]
    skipped: dict[str, int] = {}
    for r in rows:
        if r["verdict"] != NOW:
            skipped[r["code"] or r["verdict"]] = skipped.get(r["code"] or r["verdict"], 0) + 1
    try:
        from . import fingerprint as FP

        installed = FP.current()
    except Exception:                        # noqa: BLE001 - as the snapshot reads it
        installed = {}
    ticked = sum(bool(r["ticked"]) for r in rows)
    return {"rows": rows, "plan_id": _plan_id(rows), "keyless_ticked": bool(keyless),
            "now": sum(r["verdict"] == NOW for r in rows), "ticked": ticked,
            "keyless": sum(bool(r["keyless"]) for r in rows), "skipped": skipped,
            # One fresh session is one first turn (DAY-D2): the spend the operator is agreeing to.
            "premium_turns": ticked, "installed": installed or {}, "unknown_repos": unknown}


def run_all(expect: list[str] | None = None, *, registry: Registry | None = None,
            cfg: dict | None = None) -> dict:
    """Start a clean session for each repository the operator ticked that is still `now`.

    Each is judged again just before its launch -- the sweep's checks, then #488's `run`, which takes
    a fresh listing of its own -- so a repository that turned mid-turn, or whose session became
    today's, since the preview is reported and never launched. Never `closed=True`, nothing queued
    (DAY-D3), no new launch path.
    """
    from . import supervisor

    wanted = list(dict.fromkeys(str(n) for n in (expect or []) if str(n)))
    if not wanted:
        raise FreshRefused({"why": "a fresh day runs only the repositories you ticked, and none was named",
                            "hint": "preview first: `ad-fleet fresh --all --dry-run` (or {all: true, "
                                    "dry_run: true}), then confirm the ticked ones",
                            "code": "preview_first"})
    reg = registry or Registry()
    unknown = [n for n in wanted if n not in {r.name for r in reg.sorted()}]
    results = []
    for repo in reg.sorted():
        name = repo.name
        if name not in wanted:
            # Not ticked: said, never launched.
            results.append({**_sweep_row(name, reg, seen={}, keyless=False, cfg=cfg), "ticked": False,
                            "done": SKIPPED})
            continue
        row = _sweep_row(name, reg, seen={}, keyless=True, cfg=cfg)
        if row["verdict"] != NOW:
            results.append({**row, "ticked": False, "done": CHANGED})
            continue
        try:
            done = run(name, closed=False, cfg=cfg, registry=reg)
        except FreshRefused as e:
            results.append({**row, **e.row, "ticked": False, "done": CHANGED})
            continue
        except supervisor.SupervisorError as e:
            results.append({**row, "ticked": False, "verdict": REFUSED, "done": CHANGED,
                            "code": e.code or "refused", "why": e.msg, "hint": e.hint})
            continue
        results.append({**row, **done, "ticked": True, "began": row["began"]})
    started = [r for r in results if r["done"] == "started"]
    return {"rows": results, "started": len(started), "premium_turns": len(started),
            "changed": sum(r["done"] == CHANGED for r in results), "unknown_repos": unknown}
