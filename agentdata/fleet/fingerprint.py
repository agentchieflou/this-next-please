"""What an agent was started on, and whether that is still what is installed (#238, #239).

A headless agent is a new `copilot -p … --resume <session>` process every turn, and every `ad-*`
command it runs is the installed code -- so the CLI half is never stale *inside* a turn. What goes
stale is the skill text the session read when it began: the README's *skills are read when a chat
starts*. 0.13.2 changed three skills and every agent already running kept asking with `--question`,
which is how a tile came to count twelve questions nobody had open (#231). Nothing could say which
agents those were, because nothing recorded what a session began on.

So every `started` event now carries the install it began on:

    install: {version, commit, skills}

`skills` hashes the *content* of every installed `SKILL.md`, never an mtime: `ad-update` reinstalls
every skill and rewrites every timestamp, and a hash of mtimes would call every agent stale after
every update whether a word changed or not. The per-skill hashes go to
`~/.agentdata/fleet/installs/<skills>.json`, once per distinct set, which is how the reason can name
*which* skills changed without forty hashes riding in every event.

Read-only against everything outside the fleet directory, like the rest of the fleet.
"""
from __future__ import annotations
import glob
import hashlib
import json
import os
import threading
import time

from .. import textio
from .registry import fleet_dir

INSTALLS = "installs"

_lock = threading.Lock()
_cache: dict = {"key": None, "value": None, "at": 0.0}
# The desk asks on every snapshot, several times a second while agents talk. Within this long the
# last answer stands without touching the disk at all -- no glob, no stat, no metadata read.
TTL_S = 2.0


def _skill_files(d: str) -> list[str]:
    return sorted(glob.glob(os.path.join(d, "*", "SKILL.md")))


def _skills_dir() -> str:
    from .. import update as U

    try:
        return U.skills_dir()
    except Exception:                        # noqa: BLE001 - no config, no home: no skills, not a crash
        return ""


def _cli() -> tuple[str, str]:
    from .. import update as U

    commit = str(((U.direct_url().get("vcs_info") or {}).get("commit_id")) or "")[:12]
    return U.version(), commit


def current() -> dict:
    """`{version, commit, skills}` of what is installed on disk now.

    Read from disk rather than from what this process imported, because the question is what the
    *next* session would start on. Cached against the skills folder's shape (count and newest
    mtime) and re-hashed only when that moves; a re-hash that finds the same content gives the same
    answer, so an update that rewrote timestamps and nothing else changes nothing.
    """
    with _lock:
        if _cache["value"] is not None and time.monotonic() - _cache["at"] < TTL_S:
            return dict(_cache["value"])
    d = _skills_dir()
    files = _skill_files(d) if d else []
    try:
        newest = max((os.path.getmtime(f) for f in files), default=0.0)
    except OSError:
        newest = -1.0
    version, commit = _cli()
    key = (textio.norm_path(d) if d else "", len(files), newest, version, commit)
    with _lock:
        if _cache["key"] == key and _cache["value"] is not None:
            _cache["at"] = time.monotonic()
            return dict(_cache["value"])
    per = {}
    for f in files:
        try:
            with open(f, "rb") as fh:
                per[os.path.basename(os.path.dirname(f))] = hashlib.sha256(fh.read()).hexdigest()[:12]
        except OSError:
            continue
    skills = hashlib.sha256("\n".join(f"{n}:{h}" for n, h in sorted(per.items())).encode()).hexdigest()[:12] \
        if per else ""
    value = {"version": version, "commit": commit, "skills": skills}
    _remember(skills, per)
    with _lock:
        _cache.update(key=key, value=value, at=time.monotonic())
    return dict(value)


def forget() -> None:
    """Drop the cached answer. For a test that edits a skill and asks again inside `TTL_S`."""
    with _lock:
        _cache.update(key=None, value=None, at=0.0)


def _index_path(skills: str) -> str:
    return os.path.join(fleet_dir(), INSTALLS, f"{skills}.json")


def _remember(skills: str, per: dict) -> None:
    """Write the per-skill hashes for this set once. A failure costs only the names in a reason."""
    if not skills:
        return
    path = _index_path(skills)
    if os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        textio.write_json(path, per)
    except OSError:
        pass


def _per_skill(skills: str) -> dict | None:
    if not skills:
        return {}
    try:
        with open(_index_path(skills), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def changed(began: str, now: str) -> list[str] | None:
    """The skills whose text differs between two sets, added and removed ones included.

    None when either set's index is gone -- the hashes still say *that* they differ, only not which.
    """
    if began == now:
        return []
    a, b = _per_skill(began), _per_skill(now)
    if a is None or b is None:
        return None
    return sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))


# ------------------------------------------------------------------------------ a session's origin


def _data(ev: dict) -> dict:
    return ev.get("data") or {}


def origin(stream: list[dict]) -> dict | None:
    """The `started` that began the session the current run is on, or None if nothing ever started.

    A run that resumed carries its origin's install forward as `origin_install` (the supervisor
    looks it up when it emits), which survives the stream rolling over. For a stream written before
    that, the origin is found here: the `new` start whose run first reported the resumed session's
    id, or failing that the latest `new` start before the resume.
    """
    starts = [(i, ev) for i, ev in enumerate(stream) if ev.get("kind") == "started"]
    if not starts:
        return None
    i_last, last = starts[-1]
    d = _data(last)
    if d.get("adopted") or d.get("external") or not d.get("resumed"):
        return last
    sid = str(d.get("session") or "")
    if sid:
        for j, ev in enumerate(stream):
            if ev.get("kind") == "session_id" and str(_data(ev).get("session") or "") == sid:
                began = [s for (k, s) in starts if k < j and not _data(s).get("resumed")]
                if began:
                    return began[-1]
                break
    began = [s for (k, s) in starts if k < i_last and not _data(s).get("resumed")]
    return began[-1] if began else last


def began_on(stream: list[dict]) -> tuple[dict | None, str]:
    """`(install, how)` for the current session. `how` is one of:

    `recorded` -- the origin says what it began on;
    `legacy`   -- the origin predates recording, so it began on an older install than this one;
    `adopted`  -- it began outside the fleet, and nobody can say;
    `none`     -- nothing ever started here.
    """
    last = next((ev for ev in reversed(stream) if ev.get("kind") == "started"), None)
    if last is None:
        return None, "none"
    d = _data(last)
    if d.get("adopted") or d.get("external"):
        return None, "adopted"
    if d.get("resumed") and isinstance(d.get("origin_install"), dict):
        return dict(d["origin_install"]), "recorded"
    if d.get("resumed") and "origin_install" in d:
        # The supervisor looked when it resumed and found no record: the session began before the
        # fleet kept one. Falling through would find this resume's own `install` and call it fresh.
        return None, "legacy"
    first = origin(stream)
    install = _data(first).get("install") if first else None
    if isinstance(install, dict):
        return dict(install), "recorded"
    return None, "legacy"


def staleness(stream: list[dict], now: dict | None = None) -> dict:
    """Is the current session on the installed skills and CLI? Derived, never stored (#240).

    `{stale, unknown, reason, skills_changed, began, now}`. Stale when the skills differ or the CLI
    version (or, for a git install, the commit) does; a session with no record began before the
    fleet kept one, which is older than any install that does. An adopted session is unknown and
    never called stale: the fleet cannot renew it anyway, and guessing would be worse than saying so.
    """
    now = now or current()
    began, how = began_on(stream)
    out = {"stale": False, "unknown": False, "reason": "", "skills_changed": [], "began": began, "now": now}
    if how == "none":
        return out
    if how == "adopted":
        return {**out, "unknown": True, "reason": "began outside the fleet; what it started on is unknown"}
    if how == "legacy":
        return {**out, "stale": True,
                "reason": f"started before the fleet recorded installs · installed {now.get('version', '?')}"}
    parts = []
    cli_moved = began.get("version") != now.get("version") or (
        began.get("commit") and now.get("commit") and began.get("commit") != now.get("commit"))
    if cli_moved:
        parts.append(f"started on {_label(began)} · installed {_label(now)}")
    names: list[str] = []
    if (began.get("skills") or "") != (now.get("skills") or ""):
        found = changed(began.get("skills") or "", now.get("skills") or "")
        names = found or []
        parts.append("skills changed: " + ", ".join(names) if names else "skills changed")
    if not parts:
        return out
    return {**out, "stale": True, "reason": " · ".join(parts), "skills_changed": names}


def _label(install: dict) -> str:
    v, c = install.get("version") or "?", install.get("commit") or ""
    return f"{v} ({c[:7]})" if c else v
