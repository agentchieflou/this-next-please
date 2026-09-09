"""Tests for one theme per project, directory hooks, and Windows Terminal fragment (#139)."""
from __future__ import annotations

import json
import os
import pytest

from agentdata import cli_fleet
from agentdata import cli_theme
from agentdata import config
from agentdata import theme
from agentdata import theme_project
from agentdata.fleet.registry import Registry, Repo


@pytest.fixture
def mock_fleet_env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    fleet_d = tmp_path / "fleet"
    monkeypatch.setenv("AGENTDATA_CONFIG", str(cfg_file))
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(fleet_d))

    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "repo2"
    repo3 = tmp_path / "repo3"
    for r in (repo1, repo2, repo3):
        r.mkdir()
        (r / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (r / ".agent").mkdir()
        (r / ".agent" / "state.json").write_text(json.dumps({
            "active_ticket": "RDSD-100",
            "phase": "triage"
        }), encoding="utf-8")

    reg = Registry()
    reg.add(str(repo1), "repo1")
    reg.add(str(repo2), "repo2")
    reg.add(str(repo3), "repo3")

    cfg = {
        "version": 1,
        "theme": {
            "default": "greens",
            "projects": {
                "repo1": "matrix",
                "repo2": "nfl-browns"
            }
        }
    }
    config.save(cfg, str(cfg_file))
    return tmp_path, repo1, repo2, repo3


def test_resolve_project_themes(mock_fleet_env):
    """Registered repos receive their configured or default themes and accents."""
    entries = theme_project.resolve_project_themes()
    assert len(entries) == 3
    by_name = {e["name"]: e for e in entries}
    assert by_name["repo1"]["theme_name"] == "matrix"
    assert by_name["repo2"]["theme_name"] == "nfl-browns"
    assert by_name["repo3"]["theme_name"] == "greens"
    assert by_name["repo1"]["accent"] == theme.MATRIX.accent


def test_generated_hooks_contain_prefix_table_and_zero_python(mock_fleet_env, tmp_path):
    """Generated hooks contain prefix tables and execute zero python processes."""
    hooks = theme_project.write_hooks(hook_directory=str(tmp_path))
    for ext, path in hooks.items():
        assert os.path.isfile(path)
        content = open(path, "r", encoding="utf-8").read()
        assert "python" not in content.lower(), f"Hook {ext} must not invoke Python"
        assert "repo1" in content
        assert "repo2" in content


def test_wt_fragment_generation_and_removal(mock_fleet_env, tmp_path):
    """Windows Terminal fragment validates, lists profiles, and uninstalls cleanly."""
    target = tmp_path / "agentdata.json"
    written = theme_project.write_wt_fragment(str(target))
    assert os.path.isfile(written)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "schemes" in data
    assert "profiles" in data
    assert len(data["profiles"]) == 3
    names = [p["name"] for p in data["profiles"]]
    assert "repo1" in names and "repo2" in names and "repo3" in names

    # Removal
    removed = theme_project.remove_wt_fragment(str(target))
    assert removed is True
    assert not target.exists()


def test_hook_install_and_uninstall(mock_fleet_env, tmp_path):
    """Install and uninstall directory hook modifies startup file and reverts cleanly."""
    profile = tmp_path / "profile.ps1"
    initial = "# powershell profile\n"
    profile.write_text(initial, encoding="utf-8")

    res_inst = theme_project.install_hook("pwsh", startup_path=str(profile))
    assert res_inst["changed"] is True
    assert theme_project.HOOK_MARKER in profile.read_text(encoding="utf-8")

    res_uninst = theme_project.uninstall_hook("pwsh", startup_path=str(profile))
    assert res_uninst["removed"] is True
    assert theme_project.HOOK_MARKER not in profile.read_text(encoding="utf-8")


def test_ad_fleet_status_has_accent_column(mock_fleet_env, capsys):
    """ad-fleet status outputs the accent column."""
    class Args:
        polls = False
        repo = None
        show_launch = False

    rc = cli_fleet.cmd_status(Args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "accent" in out
    assert theme.MATRIX.accent in out


def test_random_theme_for_project_is_stable(mock_fleet_env):
    """random theme for a project produces the same palette everywhere."""
    t1 = theme.get("random", seed="repo1")
    t2 = theme.get("random", seed="repo1")
    assert t1.ground == t2.ground
    assert t1.accent == t2.accent
