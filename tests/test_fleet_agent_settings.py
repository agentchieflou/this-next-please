"""Every agent setting, fleet-wide and for one agent (`fleet.agents.<repo>`).

The operator's complaint this answers: PowerShell access "kept disabling itself". What an agent may
run was one list for the whole fleet, settable only in the file, and a per-session approval given
in a Copilot window was gone at the next fleet launch, which carried the fleet's list. Now each agent
can be given its own extras on the settings page, they are on every launch (headless and console),
and the page says, for every value, whether it is this agent's, the fleet's, or the default.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import config as C
from agentdata.fleet import launch as L, models as M, overrides as OV, registry, serve as S, settings as SET
from agentdata.fleet.registry import Registry

from test_fleet import make_project

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "copilot")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path


def _repos(tmp_path, *names):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)


def _patterns(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def _agent(snap, repo):
    return next(a for a in snap["agents"] if a["repo"] == repo)


# ------------------------------------------------------------------------------- the overlay


def test_an_agents_own_value_wins_and_the_rest_inherit():
    cfg = {"fleet": {"approval_timeout": 600, "max_restarts": 2,
                     "agents": {"luna.v2": {"fleet.approval_timeout": 60}}}}
    mine = OV.for_agent(cfg, "luna.v2")
    assert C.get(mine, "fleet.approval_timeout") == 60
    assert C.get(mine, "fleet.max_restarts") == 2
    assert C.get(cfg, "fleet.approval_timeout") == 600, "the fleet's dict is never written into"
    assert OV.for_agent(cfg, "uat") is cfg, "an agent with nothing of its own reads the fleet's"
    assert OV.source(cfg, "luna.v2", "fleet.approval_timeout") == "agent"
    assert OV.source(cfg, "luna.v2", "fleet.max_restarts") == "fleet"
    assert OV.source(cfg, "luna.v2", "fleet.budget_per_agent") == "default"


def test_list_settings_add_to_the_fleets_rather_than_replace_them():
    cfg = {"fleet": {"copilot": {"allow_extra": ["shell(Get-ChildItem)"], "deny_extra": ["shell(ssh)"]},
                     "agents": {"luna": {"fleet.copilot.allow_extra": ["powershell"],
                                         "fleet.copilot.deny_extra": ["shell(scp)"]}}}}
    argv = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=OV.for_agent(cfg, "luna"))
    allowed, denied = _patterns(argv, "--allow-tool"), _patterns(argv, "--deny-tool")
    assert "powershell" in allowed and "shell(Get-ChildItem)" in allowed
    assert "shell(ssh)" in denied and "shell(scp)" in denied, "an agent never loses a fleet denial"
    for floor in L.DEFAULT_DENY:
        assert floor in denied
    other = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=OV.for_agent(cfg, "uat"))
    assert "powershell" not in _patterns(other, "--allow-tool"), "one agent's grant is that agent's"


def test_the_launch_flags_reach_both_the_headless_turn_and_the_console():
    cfg = {"fleet": {"agents": {"luna": {"fleet.copilot.context": "long_context",
                                         "fleet.copilot.log_level": "debug",
                                         "fleet.copilot.agent": "reviewer",
                                         "fleet.copilot.add_dirs": ["C:/data/shared"],
                                         "fleet.copilot.allow_extra": ["powershell"]}}}}
    mine = OV.for_agent(cfg, "luna")
    headless = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=mine)
    console = L.console_command("copilot", "C:/repo", log_dir="C:/logs", session="abc", cfg=mine)
    for argv in (headless, console):
        assert argv[argv.index("--context") + 1] == "long_context"
        assert argv[argv.index("--log-level") + 1] == "debug"
        assert argv[argv.index("--agent") + 1] == "reviewer"
        assert "C:/data/shared" in _patterns(argv, "--add-dir")
        assert "powershell" in _patterns(argv, "--allow-tool")
    plain = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg={})
    assert "--context" not in plain and "--agent" not in plain
    assert plain[plain.index("--log-level") + 1] == "error", "the default is unchanged"


@pytest.mark.parametrize("bad", ["--allow-all", "allow-all-tools", "shell()", "shell(a) --yolo", "two words"])
def test_a_pattern_that_is_not_a_permission_is_refused_at_launch_too(bad):
    cfg = {"fleet": {"copilot": {"allow_extra": [bad]}}}
    with pytest.raises(L.LaunchError):
        L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=cfg)


# ---------------------------------------------------------------------------------- the page


def test_the_snapshot_says_for_every_agent_what_it_runs_with_and_why(fleet_home, tmp_path):
    _repos(tmp_path, "luna", "uat")
    C.save({"fleet": {"approval_timeout": 600,
                      "agents": {"luna": {"fleet.approval_timeout": 60,
                                          "fleet.copilot.allow_extra": ["powershell"]}}}})
    snap = S.settings_snapshot()
    luna, uat = _agent(snap, "luna"), _agent(snap, "uat")
    row = {r["key"]: r for r in luna["rows"]}["fleet.approval_timeout"]
    assert (row["value"], row["source"], row["fleet"]) == (60, "agent", 600)
    assert {r["key"]: r for r in uat["rows"]}["fleet.approval_timeout"]["source"] == "fleet"
    allow = {r["pattern"]: r for r in luna["tools"]["allow"]}
    assert allow["powershell"]["source"] == "agent" and allow["powershell"]["broad"] is True
    assert "powershell" not in {r["pattern"] for r in uat["tools"]["allow"]}
    fleet_row = next(r for r in snap["editable"] if r["key"] == "fleet.approval_timeout")
    assert fleet_row["per_agent"] is True and fleet_row["overridden_by"] == ["luna"]
    assert next(r for r in snap["editable"] if r["key"] == "fleet.port")["per_agent"] is False


def test_an_agent_setting_is_written_validated_and_inherited_again(fleet_home, tmp_path):
    _repos(tmp_path, "luna.v2")
    S.act("settings", {"agent": "luna.v2", "set": [{"key": "fleet.max_restarts", "value": "3"}],
                       "lists": [{"key": "fleet.copilot.allow_extra", "items": "powershell\nshell(Get-Item)"}]})
    saved = json.load(open(C.path(), encoding="utf-8"))
    assert saved["fleet"]["agents"]["luna.v2"] == {
        "fleet.max_restarts": 3, "fleet.copilot.allow_extra": ["powershell", "shell(Get-Item)"]}

    S.act("settings", {"agent": "luna.v2", "inherit": ["fleet.max_restarts", "fleet.copilot.allow_extra"]})
    saved = json.load(open(C.path(), encoding="utf-8"))
    assert "luna.v2" not in (saved["fleet"].get("agents") or {}), "an emptied entry goes"


@pytest.mark.parametrize("body,code", [
    ({"agent": "luna", "set": [{"key": "fleet.port", "value": 9000}]}, "not_per_agent"),
    ({"agent": "ghost", "set": [{"key": "fleet.max_restarts", "value": 2}]}, "no_repo"),
    ({"agent": "luna", "set": [{"key": "fleet.max_restarts", "value": "two"}]}, "bad_type"),
    ({"agent": "luna", "lists": [{"key": "fleet.copilot.allow_extra", "items": ["--yolo"]}]}, "bad_pattern"),
    ({"lists": [{"key": "fleet.copilot.add_dirs", "items": ["relative/dir"]}]}, "bad_pattern"),
    ({"lists": [{"key": "fleet.allow_tools", "items": ["shell(rm)"]}]}, "unknown_key"),
    ({"set": [{"key": "fleet.copilot.agent", "value": "x --allow-all"}]}, "bad_type"),
])
def test_a_bad_agent_write_is_refused_and_nothing_is_written(fleet_home, tmp_path, body, code):
    _repos(tmp_path, "luna")
    C.save({"fleet": {"max_restarts": 1}})
    before = open(C.path(), "rb").read()
    with pytest.raises(S.ServeError) as e:
        S.act("settings", body)
    assert e.value.code == code
    assert open(C.path(), "rb").read() == before


def test_the_fleet_wide_lists_are_editable_and_emptying_one_removes_it(fleet_home, tmp_path):
    _repos(tmp_path, "luna")
    snap = S.act("settings", {"lists": [{"key": "fleet.copilot.allow_extra", "items": ["shell(Get-ChildItem)"]}]})
    rows = next(r for r in snap["lists"] if r["key"] == "fleet.copilot.allow_extra")["rows"]
    assert rows == [{"item": "shell(Get-ChildItem)", "source": "fleet", "broad": False}]
    assert {r["pattern"]: r["source"] for r in snap["tools"]["allow"]}["shell(Get-ChildItem)"] == "added"
    S.act("settings", {"lists": [{"key": "fleet.copilot.allow_extra", "items": []}]})
    assert C.get(C.load(), "fleet.copilot.allow_extra") is None


# ------------------------------------------------------------------------- the readers use it


def test_the_supervisor_launches_an_agent_with_its_own_settings(fleet_home, tmp_path):
    from agentdata.fleet import supervisor
    from test_fleet import _fake_copilot, _settle

    _repos(tmp_path, "luna", "uat")
    cfg = {"fleet": {"agents": {"luna": {"fleet.copilot.allow_extra": ["powershell"]}}}}
    exe = _fake_copilot(tmp_path)
    luna = supervisor.start("luna", prompt="hi", cfg=cfg, exe=exe)
    uat = supervisor.start("uat", prompt="hi", cfg=cfg, exe=exe)
    _settle("luna")
    _settle("uat")
    assert "powershell" in _patterns(luna["launch"], "--allow-tool")
    assert "powershell" not in _patterns(uat["launch"], "--allow-tool")


def test_an_agents_restart_limit_and_approval_window_are_its_own():
    from agentdata.fleet import approval, lifecycle

    cfg = {"fleet": {"max_restarts": 1, "approval_timeout": 1800,
                     "agents": {"luna": {"fleet.max_restarts": 4, "fleet.approval_timeout": 90}}}}
    assert lifecycle.settings(OV.for_agent(cfg, "luna"))["max_restarts"] == 4
    assert lifecycle.settings(OV.for_agent(cfg, "uat"))["max_restarts"] == 1
    assert approval.timeout_seconds(OV.for_agent(cfg, "luna")) == 90
    assert approval.timeout_seconds(OV.for_agent(cfg, "uat")) == 1800


# --------------------------------------------------------------------- Copilot's own settings


def test_copilots_own_config_keys_are_listed_with_what_covers_them_per_agent():
    text = open(os.path.join(FIXTURES, "help-config-1.0.88.txt"), encoding="utf-8").read()
    keys = M.parse_config_keys(text)
    assert [k["key"] for k in keys] == ["logLevel", "model", "contextTier"]
    assert len(keys[1]["choices"]) == 26 and "--context flag" in keys[2]["about"]
    listed = M.config_keys({"config": keys, "cli_version": "1.0.88"})
    covered = {r["key"]: r["covered_by"] for r in listed["rows"]}
    assert covered == {"logLevel": "fleet.copilot.log_level", "model": "fleet.models",
                       "contextTier": "fleet.copilot.context"}
    assert listed["known"] is True and M.config_keys({})["known"] is False
