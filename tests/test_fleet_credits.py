"""The month's allowance and the posture it buys (`agentdata/fleet/credits.py`, 2026-10-03).

The operator: 23,000 credits last month, 18,500 used on `auto`'s efficiency tier; 50,000 this month,
so `balance` is the default and a reserve is what keeps it honest. These tests hold the two rules
the module has -- the month is the calendar month, and the reserve steps the tier down and never
stops anything -- and that the number every printer uses is the ledger's, not a new one.
"""
from __future__ import annotations

import pytest

from agentdata import config as C
from agentdata.fleet import credits as CR, launch, registry, serve as S, settings as SET, spend as SPEND
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path


# ---------------------------------------------------------------------------------- the rule


def test_the_default_tier_is_balance_now_and_the_reserve_steps_it_down_to_efficiency():
    cfg = {"fleet": {"credits": {"allowance": 50000}}}
    assert launch.DEFAULT_AUTO_TIER == "balance"
    inside = CR.posture(cfg, spent=30000, configured_tier="balance")
    assert inside["mode"] == "balanced" and inside["tier"] == "balance"
    assert inside["remaining"] == 20000 and inside["floor"] == 10000
    assert "20000" in inside["why"] and "20% reserve" in inside["why"]

    reserve = CR.posture(cfg, spent=41000, configured_tier="balance")
    assert reserve["mode"] == "reserve" and reserve["tier"] == "efficiency"
    assert "efficiency instead of balance" in reserve["why"]

    # The reserve is there at the end of the month whichever tier was asked for.
    assert CR.posture(cfg, spent=41000, configured_tier="intelligence")["tier"] == "efficiency"
    # Already on the cheapest tier: nothing to step down to, and the sentence says so.
    already = CR.posture(cfg, spent=41000, configured_tier="efficiency")
    assert already["mode"] == "reserve" and already["tier"] == "efficiency" and "already on" in already["why"]


def test_no_allowance_recorded_means_the_configured_tier_untouched():
    """`0` is the honest spelling of "nobody told the fleet": no reserve, no step-down."""
    off = CR.posture({}, spent=99999, configured_tier="balance")
    assert off["mode"] == "off" and off["tier"] == "balance" and "no allowance" in off["why"]


def test_an_allowance_nobody_can_read_is_off_and_said_not_coerced_to_zero():
    """The lesson of `fleet.budget_per_agent` (#213), applied before it is learned again."""
    bad = CR.posture({"fleet": {"credits": {"allowance": "fifty thousand"}}}, spent=1, configured_tier="balance")
    assert bad["mode"] == "off" and bad["tier"] == "balance"
    assert bad["invalid"] == "fifty thousand" and "invalid" in bad["why"]
    conf = CR.settings({"fleet": {"credits": {"allowance": 50000, "reserve": 150}}})
    assert conf["reserve_pct"] == CR.DEFAULT_RESERVE_PCT and "reserve" in conf["invalid"]


def test_the_month_is_the_calendar_month_summed_from_the_ledgers_day_rows():
    folded = {"days": {"2026-09-30": {"premium": 400.0}, "2026-10-01": {"premium": 10.5},
                       "2026-10-02": {"premium": 20.0}, "2026-11-01": {"premium": 7.0}}}
    assert CR.month_of("2026-10-03") == "2026-10"
    assert CR.spent_in_month(folded, "2026-10") == 30.5
    assert CR.spent_in_month(folded, "2026-12") == 0.0


# ------------------------------------------------------------------------ the ledger, the launch


def _ledger(name, days):
    SPEND.write_ledger(name, {"sessions": {}, "days": {d: {"premium": p, "turns": 1} for d, p in days.items()}})


def test_the_next_launch_carries_the_reserves_tier_and_the_month_rolls_over(fleet_home, tmp_path):
    """Two agents, one allowance: the month is the fleet's sum, and 1 November starts at zero."""
    for name in ("alpha", "beta"):
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    _ledger("alpha", {"2026-10-01": 30000.0, "2026-09-28": 9000.0})
    _ledger("beta", {"2026-10-02": 11000.0})
    C.save({"fleet": {"credits": {"allowance": 50000}}})
    cfg = C.load()

    assert CR.fleet_month(["alpha", "beta"], "2026-10") == 41000.0
    assert CR.tier_for(cfg, today="2026-10-03") == "efficiency"
    assert CR.tier_for(cfg, today="2026-11-01") == "balance", "a new month, a new allowance"

    row = CR.status(cfg, today="2026-10-03")
    assert row["mode"] == "reserve" and row["spent"] == 41000.0 and row["agents"] == 2
    assert row["month"] == "2026-10" and row["configured_tier"] == "balance"


def test_launch_command_takes_the_tier_the_supervisor_decided_and_defaults_to_balance(monkeypatch):
    from agentdata.fleet import models as M

    monkeypatch.setattr(M, "auto_tier_flag", lambda: "--auto-tier")
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg={}, model="auto")
    assert _patterns(argv, "--auto-tier") == ["balance"], "the default of 2026-10-03"
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg={}, model="auto",
                                 tier="efficiency")
    assert _patterns(argv, "--auto-tier") == ["efficiency"], "the reserve's step-down"
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg={}, model="auto", tier="")
    assert "--auto-tier" not in argv, "an empty tier is 'none', not 'the default'"


def _patterns(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


# --------------------------------------------------------------------------- the page, the status


def test_the_settings_page_offers_both_keys_and_refuses_what_it_cannot_read(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    assert "fleet.credits.allowance" in SET.EDITABLE and "fleet.credits.reserve" in SET.EDITABLE
    assert not SET.EDITABLE["fleet.credits.allowance"].get("agent"), "one allowance, never per agent"
    for key, bad, code in (("fleet.credits.allowance", "lots", "bad_type"),
                           ("fleet.credits.reserve", "150", "out_of_range")):
        with pytest.raises(S.ServeError) as e:
            S.act("settings", {"set": [{"key": key, "value": bad}]})
        assert e.value.code == code, (key, bad)
    S.act("settings", {"set": [{"key": "fleet.credits.allowance", "value": "50000"},
                               {"key": "fleet.credits.reserve", "value": "25"}]})
    assert CR.settings(C.load()) == {"allowance": 50000.0, "reserve_pct": 25, "invalid": ""}


def test_status_prints_the_months_spend_and_the_posture(fleet_home, tmp_path, capsys):
    from agentdata import cli_fleet

    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    _ledger("alpha", {CR._today(): 45000.0})
    C.save({"fleet": {"credits": {"allowance": 50000}}})
    assert cli_fleet.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "spent_month: 45000" in out and "credits: reserve" in out and "credits_tier: efficiency" in out
