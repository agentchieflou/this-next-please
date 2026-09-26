"""Renew: a fresh session for every stale agent, when it is idle, previewed first (#241).

The operator's rule, word for word as they chose it: *stale only, when idle* -- one button or verb
that lists which agents are stale and why before anything runs, waits for a running turn to
finish, skips agents waiting on a person, then starts a fresh session on the same ticket.

Stale is `fingerprint.staleness`: the session began on skills or a CLI that have since changed.
Renewing is `supervisor.start(new=True)` on the repository's active ticket, so every guard `start`
already has -- the lock, the mid-ticket check, the budget -- applies unchanged, and a refusal comes
back in `start`'s own words. A running agent is not interrupted: it gets `renew.json` beside its
lock, and the desk's tick carries that out once the turn has ended, re-judging it first -- a
question that opened during the turn cancels it, because renewing would bury the question.
"""
from __future__ import annotations
import glob
import os
import time

from .. import textio
from .registry import Registry, agent_dir, fleet_dir

RENEW_FILE = "renew.json"

NOW, AT_TURN_END, SKIPPED = "now", "at turn end", "skipped"

# Said once, on the fresh session's first turn, after whatever the configured template says: why
# this session exists, and that the work continues rather than restarts.
WHY = (" This is a fresh session: the skills or the CLI changed since the last one began ({reason}). "
       "The work continues from .agent/state.json, not from the beginning.")


def _queue_path(name: str) -> str:
    return os.path.join(agent_dir(name), RENEW_FILE)


def queued(name: str) -> dict:
    try:
        return textio.read_json(_queue_path(name), RENEW_FILE)
    except (OSError, ValueError):
        return {}


def verdict(repo, now: dict | None = None) -> dict:
    """One agent's row: is it stale, and what would renewing it do right now?"""
    from .. import state as STATE
    from . import agentstate, events as E, fingerprint as FP, supervisor
    from .serve import split_runs

    name = repo.name
    st = repo.state()
    # Brought up to date first, as the snapshot does: a question the agent asked a moment ago is
    # in `state.json` before it is in the stream, and a verdict read from a stale stream would
    # renew straight over it.
    try:
        E.refresh(name, repo.path, repo_state=st)
    except OSError:
        pass
    stream = E.read(name)
    stale = FP.staleness(stream, now)
    lock = supervisor.live(name)
    ticket = str(st.get("active_ticket") or "")
    phase = str(st.get("phase") or "")
    curr, _ = split_runs(stream, live=bool(lock))
    derived = agentstate.derive(curr["events"] or stream, live=bool(lock),
                                open_questions=(st.get("open_questions") or []) if st else None)
    last = next((ev for ev in reversed(stream) if ev.get("kind") == "started"), {})
    row = {"repo": name, "ticket": ticket, "state": derived["state"], "stale": stale["stale"],
           "unknown": stale["unknown"], "reason": stale["reason"],
           "skills_changed": stale["skills_changed"], "queued": bool(queued(name))}

    def skip(why: str) -> dict:
        return {**row, "verdict": SKIPPED, "why": why}

    if stale["unknown"] or lock.get("external"):
        return skip(f"adopted: it began outside the fleet — `ad-fleet fresh {name}` (start fresh on "
                    f"its pane) leaves it for a clean session")
    if not stale["stale"]:
        return skip("not stale")
    if lock.get("kind") == "console" or (last.get("data") or {}).get("console"):
        return skip(f"a console is yours to renew: close it, then `ad-fleet console {name} --new`")
    if phase in agentstate.TERMINAL_PHASES or derived["state"] == "done":
        return skip("done: there is nothing to continue")
    if not ticket:
        return skip("no ticket in progress to continue")
    # The fold, and `state.json` itself: the file is the record of what is open (#231), and a
    # question is exactly what a renew must never bury.
    if agentstate.needs_the_human(derived["state"]) or phase == "blocked" or any(
            STATE.is_blocking(q) for q in (st.get("open_questions") or [])):
        return skip("needs you: answer it first — renewing would bury the question")
    if lock:
        return {**row, "verdict": AT_TURN_END, "why": "running: renewed when this turn ends"}
    return {**row, "verdict": NOW, "why": "idle: renewed now"}


def plan(names: list[str] | None = None, *, registry: Registry | None = None) -> dict:
    """Every registered agent's verdict, and what the renew would spend. Changes nothing."""
    from . import fingerprint as FP

    reg = registry or Registry()
    now = FP.current()
    wanted = set(names or [])
    rows = [verdict(repo, now) for repo in reg.sorted() if not wanted or repo.name in wanted]
    unknown = sorted(wanted - {r["repo"] for r in rows})
    renewing = [r for r in rows if r["verdict"] in (NOW, AT_TURN_END)]
    return {"rows": rows, "now": sum(r["verdict"] == NOW for r in rows),
            "at_turn_end": sum(r["verdict"] == AT_TURN_END for r in rows),
            "stale": sum(bool(r["stale"]) for r in rows),
            # One fresh session is one first turn: the spend the operator is agreeing to.
            "premium_turns": len(renewing), "installed": now, "unknown_repos": unknown}


def _start(repo, row: dict, cfg: dict | None) -> dict:
    from . import launch as LAUNCH, supervisor

    st = repo.state()
    text = LAUNCH.prompt_for(row["ticket"], None, cfg) + WHY.format(reason=row["reason"] or "stale")
    try:
        lock = supervisor.start(repo.name, key=row["ticket"], prompt=text, new=True, cfg=cfg,
                                summary=str(st.get("summary") or ""))
    except supervisor.SupervisorError as e:
        return {**row, "done": "refused", "error": e.msg, "hint": e.hint,
                "code": getattr(e, "code", "")}
    return {**row, "done": "started", "pid": lock.get("pid")}


def run(names: list[str] | None = None, *, registry: Registry | None = None,
        cfg: dict | None = None) -> dict:
    """Renew what `plan` says: idle agents now, running ones queued for the end of their turn."""
    reg = registry or Registry()
    planned = plan(names, registry=reg)
    results = []
    for row in planned["rows"]:
        if row["verdict"] == NOW:
            results.append(_start(reg.get(row["repo"]), row, cfg))
        elif row["verdict"] == AT_TURN_END:
            path = _queue_path(row["repo"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            textio.write_json(path, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                     "ticket": row["ticket"], "reason": row["reason"]})
            results.append({**row, "done": "queued"})
        else:
            results.append({**row, "done": "skipped"})
    return {**planned, "rows": results}


def carry_out(*, registry: Registry | None = None, cfg: dict | None = None) -> list[dict]:
    """The queued renews whose turn has ended, judged again and then done or cancelled. Never raises.

    Judged again because the turn may have changed the answer: a question opened, the ticket
    finished, or the operator renewed it by hand. Only a verdict of `now` starts a session; any
    other verdict but `at turn end` cancels the queue, so a renew never waits past its reason.
    """
    from . import fingerprint as FP

    out = []
    # The desk calls this on its tick, and almost always nothing is queued. Asking the disk for a
    # queue file costs one glob; building a `Registry` to ask each repository would re-parse
    # `registry.json`, and a tick's cost has to stay flat in the number of repositories.
    if not glob.glob(os.path.join(fleet_dir(), "agents", "*", RENEW_FILE)):
        return out
    try:
        reg = registry or Registry()
        now = FP.current()
        for repo in reg.sorted():
            if not queued(repo.name):
                continue
            row = verdict(repo, now)
            if row["verdict"] == AT_TURN_END:
                continue
            try:
                os.remove(_queue_path(repo.name))
            except OSError:
                pass
            out.append(_start(repo, row, cfg) if row["verdict"] == NOW
                       else {**row, "done": "cancelled"})
    except Exception:                        # noqa: BLE001 - a renew must never stop the desk
        from ..log import debug_exc

        debug_exc("fleet renew tick")
    return out
