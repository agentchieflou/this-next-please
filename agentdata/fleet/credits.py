"""The fleet's share of an enterprise AI-credit allowance, and the posture it buys.

The operator, 2026-10-03: last month the allowance was 23,000 credits and the fleet used 18,500 on
Copilot's `auto` model at its *efficiency* tier; this month it is 50,000, "which suggests that we
should be able to get by more fluidly in an auto balanced mode as opposed to an auto efficiency
mode". So the default tier is `balance` now (`launch.DEFAULT_AUTO_TIER`), and this module is what
keeps that from running the allowance dry: a **reserve**. Below the last `fleet.credits.reserve`
percent of `fleet.credits.allowance`, every new launch steps the auto tier back down to
`efficiency`, and `ad-fleet status` says so in the same words a tile would.

Two rules, and they are the only ones:

* **The allowance is a month's, and the month is the calendar month.** Credits are premium
  requests -- the one unit the fleet measures (`docs/plan-meter.md` §What is reused) -- and the
  ledger already attributes each rise to the day it happened (`spend.py` §days), so a month is a
  sum over the days whose key starts with `YYYY-MM`. Nothing new is counted; nothing is estimated.
* **A reserve steps down; it never stops.** The per-agent cap (`fleet.budget_per_agent`) is the
  stop, and it is unchanged. The reserve changes the *tier* of what is launched next, which is the
  cheaper of the two reactions and the one that keeps a ticket moving. `fleet.copilot.auto_tier`
  set explicitly to anything but `efficiency` is still stepped down inside the reserve: the point
  of a reserve is to be there at the end of the month, whichever tier was asked for.

Like `fleet.budget_per_agent`, a value nobody can read is **off and said out loud** (`invalid`),
never coerced to zero: `0` is the honest spelling of "no allowance recorded".
"""
from __future__ import annotations

from .. import config as C

ALLOWANCE_KEY = "fleet.credits.allowance"
RESERVE_KEY = "fleet.credits.reserve"
DEFAULT_RESERVE_PCT = 20
# The tier a reserve steps down to. The cheapest of Copilot's auto tiers, and the one the fleet ran
# on through September 2026 at 18,500 of 23,000 -- measured, which the others are not yet.
STEP_DOWN_TIER = "efficiency"
MODES = ("off", "balanced", "reserve")


def settings(cfg: dict | None = None) -> dict:
    """`{"allowance": float, "reserve_pct": int, "invalid": str}`. Off, loudly, on a value that
    cannot be read -- the lesson of `lifecycle.settings`'s `budget_invalid`."""
    cfg = C.load() if cfg is None else cfg
    invalid = ""
    raw = C.get(cfg, "fleet.credits.allowance")
    try:
        allowance = float(raw) if raw not in (None, "", False) else 0.0
        if allowance < 0:
            raise ValueError("negative")
    except (TypeError, ValueError):
        allowance, invalid = 0.0, str(raw)
    raw_reserve = C.get(cfg, "fleet.credits.reserve")
    try:
        reserve = int(raw_reserve) if raw_reserve not in (None, "", False) else DEFAULT_RESERVE_PCT
        if not 0 <= reserve <= 100:
            raise ValueError("percent")
    except (TypeError, ValueError):
        reserve = DEFAULT_RESERVE_PCT
        invalid = invalid or f"{RESERVE_KEY}={raw_reserve!r}"
    return {"allowance": allowance, "reserve_pct": reserve, "invalid": invalid}


def month_of(day: str) -> str:
    """`2026-10` for `2026-10-03`. The calendar month is the allowance's period."""
    return str(day or "")[:7]


def spent_in_month(folded: dict, month: str) -> float:
    """What one ledger says was spent in `month`, from the day rows the fold already keeps."""
    days = folded.get("days") or {}
    return round(sum(float((row or {}).get("premium", 0.0))
                     for day, row in days.items() if str(day).startswith(month)), 2)


def fleet_month(names: list, month: str) -> float:
    """Every agent's month summed. Reads each ledger through `spend.for_agent`, so the number is
    the same one the tile and `ad-fleet spend` print."""
    from . import spend as SPEND

    return round(sum(spent_in_month(SPEND.for_agent(name), month) for name in names), 2)


def posture(cfg: dict | None, *, spent: float, configured_tier: str) -> dict:
    """What the month's spend means for the next launch. Pure: give it the spend and the tier.

    `mode` is `off` (no allowance recorded: the configured tier, untouched), `balanced` (inside the
    allowance, above the reserve: the configured tier) or `reserve` (inside the last `reserve_pct`:
    `STEP_DOWN_TIER`). `why` is one sentence a tile or a status line can print as is.
    """
    conf = settings(cfg)
    allowance, reserve_pct = conf["allowance"], conf["reserve_pct"]
    tier = str(configured_tier or "")
    out = {"mode": "off", "tier": tier, "allowance": allowance, "spent": round(float(spent or 0.0), 2),
           "remaining": 0.0, "reserve_pct": reserve_pct, "floor": 0.0, "invalid": conf["invalid"],
           "why": ""}
    if conf["invalid"]:
        out["why"] = f"fleet.credits is invalid ({conf['invalid']}): no reserve, {tier or 'the CLI'} as configured"
        return out
    if allowance <= 0:
        out["why"] = "no allowance recorded (fleet.credits.allowance is 0)"
        return out
    remaining = round(allowance - out["spent"], 2)
    floor = round(allowance * reserve_pct / 100.0, 2)
    out.update({"remaining": remaining, "floor": floor})
    if remaining <= floor and tier and tier != STEP_DOWN_TIER:
        out.update({"mode": "reserve", "tier": STEP_DOWN_TIER,
                    "why": (f"{out['spent']:g} of {allowance:g} credits spent this month; the last "
                            f"{reserve_pct}% ({floor:g}) is the reserve, so auto runs on "
                            f"{STEP_DOWN_TIER} instead of {tier}")})
    elif remaining <= floor:
        out.update({"mode": "reserve",
                    "why": (f"{out['spent']:g} of {allowance:g} credits spent this month; inside the "
                            f"{reserve_pct}% reserve, already on {tier or 'the CLI`s own tier'}")})
    else:
        out.update({"mode": "balanced",
                    "why": (f"{out['spent']:g} of {allowance:g} credits spent this month; "
                            f"{remaining:g} left before the {reserve_pct}% reserve bites at {floor:g}")})
    return out


def _names(registry=None) -> list:
    from .registry import Registry, RegistryError

    try:
        return [r.name for r in (registry or Registry()).sorted()]
    except (RegistryError, OSError):
        return []


def status(cfg: dict | None = None, *, names: list | None = None, today: str = "",
           registry=None) -> dict:
    """The posture for `ad-fleet status` and the desk: the month's fleet spend against the
    allowance, and the tier the next launch gets. One I/O wrapper around `posture`."""
    from . import launch as LAUNCH

    cfg = C.load() if cfg is None else cfg
    today = today or _today()
    who = _names(registry) if names is None else list(names)
    try:
        configured = LAUNCH.auto_tier(cfg)
    except LAUNCH.LaunchError:
        configured = ""
    spent = fleet_month(who, month_of(today))
    out = posture(cfg, spent=spent, configured_tier=configured)
    out.update({"month": month_of(today), "configured_tier": configured, "agents": len(who)})
    return out


def tier_for(cfg: dict | None, *, today: str = "", registry=None) -> str:
    """The auto tier the next launch should carry: the configured one, or the reserve's.

    With no allowance recorded (or an invalid one) there is no reserve, and `posture` hands back the
    configured tier whatever was spent: so the month is not summed, which read every agent's ledger
    on every `send` and was most of its time (2026-10-06, the operator: "aim for 50ms ... from
    clicking send, or pressing Enter, to the agent running")."""
    from . import launch as LAUNCH

    cfg = C.load() if cfg is None else cfg
    conf = settings(cfg)
    try:
        configured = LAUNCH.auto_tier(cfg)
    except LAUNCH.LaunchError:
        configured = ""
    if conf["invalid"] or conf["allowance"] <= 0:
        return str(configured or "")
    today = today or _today()
    spent = _month_spent(_names(registry), month_of(today))
    return str(posture(cfg, spent=spent, configured_tier=configured)["tier"])


#: The month's fleet spend `tier_for` last summed, and what every agent's ledger and stream looked
#: like then: summed again only when one of them has changed. Summing reads every agent's ledger and
#: folds what is new in its stream, on every `send` (2026-10-06, page loads); the stamps are a stat
#: of two files an agent.
_MONTH: dict = {"key": None, "spent": 0.0}


def _month_spent(names: list, month: str) -> float:
    import os

    from . import events as E
    from . import spend as SPEND

    def stamp(path: str) -> tuple:
        try:
            st = os.stat(path)
            return (st.st_ino, st.st_mtime_ns, st.st_size)
        except OSError:
            return ()

    key = (month, tuple((n, stamp(SPEND.ledger_path(n)), stamp(E.normalized_path(n))) for n in names))
    if _MONTH["key"] != key:
        spent = fleet_month(names, month)
        # Summing folds what was new into the ledgers, which writes them: stamped after, not before.
        key = (month, tuple((n, stamp(SPEND.ledger_path(n)), stamp(E.normalized_path(n))) for n in names))
        _MONTH.update(key=key, spent=spent)
    return _MONTH["spent"]


def _today() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%d")
