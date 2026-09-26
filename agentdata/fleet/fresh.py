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
