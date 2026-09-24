"""What each page load measured about itself, kept while the operator has switched measuring on (#350).

Playwright cannot drive the IDE hosts, and the lag the operator sees is on the laptop, not in CI. So
a shell measures itself and posts the facts, as the WebGL probe does (`probe.py`), and this module
keeps them in `~/.agentdata/fleet/loads.json`: the newest `KEEP` per shell, page and where the page
came from. `ad-fleet engines` prints them as the `loads` table, which is the baseline the native-host
gate (#354) reads.

**Off unless the config file says otherwise.** This is measurement, not a feature, and it follows
`metrics.enabled` (docs/setup.md §Usage metrics): `fleet.loads.enabled` is read from the file on
every call and cached nowhere, so a running server stops writing the moment the key goes false.

**`from` is posted, never inferred.** Every page is served with `Referrer-Policy: no-referrer`, and
`PerformanceNavigationTiming.type` reads `navigate` both for a cold open and for settings -> desk,
so the page says where it came from and the table groups by it: those two must never be averaged.

**A load is not a probe.** Nothing here touches `probes.json`, and nothing leaves the loopback
server: the page posts to it, it writes a local file, and that is all.
"""
from __future__ import annotations
import json
import math
import os
import re
import threading
import time

from .. import config as C
from .. import textio
from . import events as E
from . import probe as PROBE
from .registry import fleet_dir

ENABLED = "fleet.loads.enabled"
LOADS_FILE = "loads.json"
KEEP = 50
SCHEMA = 1

PAGES = ("desk", "settings")
FROMS = ("", "settings")
HOWS = ("navigate", "reload", "back_forward", "prerender", "")
#: The durations a page reports, each 0-`MAX_MS` or absent.
DURATIONS = ("first_paint_ms", "fleet_ms", "ink_first_frame_ms", "longest_task_ms")
MAX_MS = 600_000.0
#: `origin_ms` is the page's `performance.timeOrigin`: an epoch-ms number within a day of ours.
ORIGIN_WINDOW_MS = 24 * 60 * 60 * 1000.0
UA_CAP = 200
#: The same pattern as serve.py's `SKIN_FAMILY` (a test pins them equal); serve.py imports this
#: module, so it is spelled here rather than imported back.
SKIN_WORD = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

LOAD_COLUMNS = ["shell", "page", "from", "n",
                "first_paint_p50", "first_paint_p95", "fleet_p50", "fleet_p95",
                "ink_first_frame_p50", "ink_first_frame_p95",
                "longest_task_p50", "longest_task_p95", "settled_pct"]

_LOCK = threading.Lock()


class LoadError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = "load_shape"):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


# ---------------------------------------------------------------------------------- the switch


def enabled(cfg: dict | None = None) -> bool:
    """True only when the config file says `"fleet": {"loads": {"enabled": true}}`.

    Read on every call, cached nowhere: the switch reaches a running server with no restart. An
    unreadable config file is off -- a measurement never outranks the file being broken.
    """
    try:
        return C.get(cfg or C.load(), ENABLED) is True
    except C.ConfigError:
        return False


def off_hint() -> str:
    """The hint an off switch prints, in `ad-metrics`' words (`cli_metrics._off_note`)."""
    return ('recording is off; set `"fleet": {"loads": {"enabled": true}}` in '
            f"{C.display_path(C.path())} to record page loads")


# ---------------------------------------------------------------------------------- the record


def _choice(body: dict, key: str, allowed: tuple[str, ...]) -> str:
    value = body.get(key, "")
    if not isinstance(value, str) or value not in allowed:
        raise LoadError(f"{key} must be one of {', '.join(repr(a) for a in allowed)}, "
                        f"not {str(value)[:40]!r}",
                        "the page sends which page it is, where it came from and "
                        "PerformanceNavigationTiming.type")
    return value


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _duration(body: dict, key: str) -> float | None:
    if key not in body or body[key] is None:
        return None
    out = _number(body[key])
    if out is None or out < 0 or out > MAX_MS:
        raise LoadError(f"{key} must be milliseconds from 0 to {int(MAX_MS)}, "
                        f"not {str(body[key])[:40]!r}",
                        "leave the key out when the page did not measure it")
    return round(out, 1)


def _origin(body: dict, now_ms: float) -> float:
    out = _number(body.get("origin_ms"))
    if out is None or abs(out - now_ms) > ORIGIN_WINDOW_MS:
        raise LoadError(f"origin_ms must be epoch milliseconds within 24 h of the server's clock, "
                        f"not {str(body.get('origin_ms'))[:40]!r}",
                        "the page sends performance.timeOrigin")
    return round(out, 1)


def _skin(body: dict, key: str) -> str:
    value = body.get(key, "")
    if not isinstance(value, str) or (value and not SKIN_WORD.match(value)):
        raise LoadError(f"{key} must be empty or a skin family word, not {str(value)[:40]!r}",
                        "the family the page wore, like the `skin-<family>` class it sets")
    return value


def _ua(body: dict) -> str:
    value = body.get("ua", "")
    if not isinstance(value, str) or len(value) > UA_CAP:
        raise LoadError(f"ua must be a string of {UA_CAP} characters or fewer",
                        "the page sends navigator.userAgent, trimmed")
    return value


def normalize(body, now_ms: float | None = None) -> dict:
    """The record to keep, from what the page posted: a closed set of fields.

    A key this module does not know is dropped; a known key with a value it cannot take is refused,
    so a page that posts nonsense learns it rather than skewing the table.
    """
    if not isinstance(body, dict):
        raise LoadError("the load must be a JSON object")
    now_ms = time.time() * 1000.0 if now_ms is None else now_ms
    try:
        shell = PROBE.shell_name(body.get("shell"))
    except PROBE.ProbeError as e:
        raise LoadError(e.msg, e.hint, code="load_shape") from None
    rec = {
        "shell": shell,
        "page": _choice(body, "page", PAGES),
        "from": _choice(body, "from", FROMS),
        "how": _choice(body, "how", HOWS),
        "origin_ms": _origin(body, now_ms),
    }
    for key in DURATIONS:
        rec[key] = _duration(body, key)
    rec["skin_first"] = _skin(body, "skin_first")
    rec["skin_settled"] = _skin(body, "skin_settled")
    rec["ua"] = _ua(body)
    rec["at"] = E.stamp()
    return rec


def _group(rec: dict) -> tuple[str, str, str]:
    return (str(rec.get("shell", "")), str(rec.get("page", "")), str(rec.get("from", "")))


# ---------------------------------------------------------------------------------- the file


def loads_file() -> str:
    return os.path.join(fleet_dir(), LOADS_FILE)


def load() -> list[dict]:
    """Every kept record, oldest first. A missing or unreadable file is no records."""
    try:
        data = json.loads(textio.read_text(loads_file()))
    except (OSError, ValueError):
        return []
    got = data.get("loads") if isinstance(data, dict) else None
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


def record(body) -> dict:
    """Keep one load, and only the newest `KEEP` of its shell, page and from. Answers `{kept: n}`,
    how many that group now holds; the page's beacon never reads it."""
    rec = normalize(body)
    group = _group(rec)
    with _LOCK:
        records = load() + [rec]
        mine = [r for r in records if _group(r) == group]
        drop = {id(r) for r in mine[:-KEEP]}
        records = [r for r in records if id(r) not in drop]
        textio.write_json(loads_file(), {"schema": SCHEMA, "loads": records})
    return {"kept": min(len(mine), KEEP)}


# ---------------------------------------------------------------------------------- the rows


def rows(records: list[dict] | None = None) -> list[list]:
    """One row per shell, page and from: how many loads, the nearest-rank p50 and p95 of each
    duration (over the loads that reported it), and the % whose first skin was the settled one."""
    records = load() if records is None else records
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for rec in records:
        groups.setdefault(_group(rec), []).append(rec)
    out = []
    for key in sorted(groups):
        recs = groups[key]
        row: list = [*key, len(recs)]
        for name in DURATIONS:
            values = [v for v in (_number(r.get(name)) for r in recs) if v is not None]
            row += [PROBE.percentile(values, 50), PROBE.percentile(values, 95)]
        settled = sum(1 for r in recs if r.get("skin_first", "") == r.get("skin_settled", ""))
        row.append(round(100.0 * settled / len(recs), 1))
        out.append(row)
    return out
