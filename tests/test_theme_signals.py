"""Tests for theme attention signals: OSC 9;4 progress, tab titles, bell, and scheduling (#141)."""
from __future__ import annotations

import io
import json
import os
import sys
import time
import pytest

from agentdata import color
from agentdata import config as C
from agentdata import theme
from agentdata import theme_project
from agentdata import theme_signals as signals
from agentdata import ui
from agentdata import omp
from agentdata import starship
from agentdata.fleet import notify as N


def test_signals_host_matrix():
    """Verify signal emission per host type."""
    # 1. Windows Terminal: supports progress, titles, and bell
    assert signals.supports_progress("windows-terminal") is True
    assert signals.supports_signals("windows-terminal") is True
    assert "\x1b]9;4;1;50\x1b\\" == signals.progress(1, 50, host="windows-terminal")
    assert "\x1b]9;4;0\x1b\\" == signals.progress("done", host="windows-terminal")
    assert "\x1b]9;4;2\x1b\\" == signals.progress("error", host="windows-terminal")
    assert "\x1b]9;4;3\x1b\\" == signals.progress("indeterminate", host="windows-terminal")
    assert "\x1b]2;my-proj\x1b\\" == signals.title("my-proj", host="windows-terminal")
    assert "\x07\x1b]9;hello\x1b\\" == signals.bell("hello", host="windows-terminal")

    # 2. Mintty (Git Bash): supports progress, titles, bell
    assert signals.supports_progress("mintty") is True
    assert "\x1b]9;4;1;75\x1b\\" == signals.progress(1, 75, host="mintty")
    assert "\x1b]2;repo\x1b\\" == signals.title("repo", host="mintty")
    assert "\x07" in signals.bell(host="mintty")

    # 3. VS Code: supports progress, titles, bell
    assert signals.supports_progress("vscode") is True
    assert "\x1b]9;4;0\x1b\\" == signals.progress(0, host="vscode")
    assert "\x1b]2;code\x1b\\" == signals.title("code", host="vscode")

    # 4. PyCharm: titles and bell, but no progress
    assert signals.supports_progress("pycharm-terminal") is False
    assert signals.progress(1, 50, host="pycharm-terminal") == ""
    assert "\x1b]2;pycharm\x1b\\" == signals.title("pycharm", host="pycharm-terminal")

    # 5. Conhost: titles and bell, but no progress
    assert signals.supports_progress("conhost") is False
    assert signals.progress(1, 50, host="conhost") == ""
    assert "\x1b]2;cmd\x1b\\" == signals.title("cmd", host="conhost")

    # 6. Pipe: zero escapes across all signals
    assert signals.supports_progress("pipe") is False
    assert signals.supports_signals("pipe") is False
    assert signals.progress(1, 50, host="pipe") == ""
    assert signals.progress(0, host="pipe") == ""
    assert signals.title("pipe-test", host="pipe") == ""
    assert signals.bell("pipe-test", host="pipe") == ""


def test_signals_silence_on_pipe(monkeypatch):
    """Zero escape sequences are emitted when piped or redirected."""
    monkeypatch.setattr(color, "enabled", lambda: False)

    buf_err = io.StringIO()
    buf_out = io.StringIO()

    signals.emit_progress("indeterminate", stream=buf_err)
    signals.emit_progress(1, 50, stream=buf_err)
    signals.emit_progress("done", stream=buf_err)
    signals.set_title("test", stream=buf_out)
    signals.emit_bell("alert", stream=buf_err)

    assert buf_err.getvalue() == ""
    assert buf_out.getvalue() == ""


def test_ui_progress_wires_osc_progress_to_stderr(monkeypatch):
    """ui.progress contextmanager emits OSC 9;4 to stderr and leaves stdout clean."""
    monkeypatch.setattr(color, "enabled", lambda: True)
    monkeypatch.setattr(signals, "supports_progress", lambda h=None: True)

    # Capture stderr
    buf_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf_err)

    # Successful run
    with ui.progress("querying"):
        pass

    val = buf_err.getvalue()
    assert "\x1b]9;4;3\x1b\\" in val  # indeterminate started
    assert "\x1b]9;4;0\x1b\\" in val  # done cleared

    # Error run
    buf_err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf_err)
    with pytest.raises(RuntimeError):
        with ui.progress("failing query"):
            raise RuntimeError("query failed")

    val_err = buf_err.getvalue()
    assert "\x1b]9;4;3\x1b\\" in val_err
    assert "\x1b]9;4;2\x1b\\" in val_err  # error progress emitted


def test_fleet_needs_human_rings_bell_and_sets_tab_error(monkeypatch):
    """A needs_human event rings the bell for the matching project terminal."""
    monkeypatch.setenv("AGENTDATA_PROJECT", "proj-alpha")

    belled = []
    progress_states = []
    monkeypatch.setattr(signals, "emit_bell", lambda text=None: belled.append(text))
    monkeypatch.setattr(signals, "emit_progress", lambda state, pct=None: progress_states.append(state))

    items = [
        {"repo": "proj-alpha", "state": "needs_human", "title": "proj-alpha needs human"},
        {"repo": "proj-beta", "state": "needs_human", "title": "proj-beta needs human"},
    ]

    res = N.deliver(items, cfg={})
    assert res[0]["belled"] is True
    assert res[1]["belled"] is False
    assert len(belled) == 1
    assert "proj-alpha needs human" in belled[0]
    assert progress_states == ["error"]


def test_fleet_needs_human_respects_quiet_hours(monkeypatch):
    """Under quiet hours, bell and toast are suppressed."""
    monkeypatch.setenv("AGENTDATA_PROJECT", "proj-alpha")

    belled = []
    monkeypatch.setattr(signals, "emit_bell", lambda text=None: belled.append(text))

    cfg = {"fleet": {"notify": {"quiet_hours": "00:00-23:59"}}}
    items = [{"repo": "proj-alpha", "state": "needs_human", "title": "quiet alert"}]

    res = N.deliver(items, cfg=cfg)
    assert res[0]["quiet"] is True
    assert res[0]["belled"] is False
    assert belled == []


def test_theme_schedule_resolution(tmp_path, monkeypatch):
    """Theme schedule resolves eye-relief during scheduled window and reports reason."""
    cfg = {
        "theme": {
            "default": "greens",
            "schedule": {
                "theme": "eye-relief",
                "after": "18:00",
                "until": "07:00"
            }
        }
    }
    from agentdata import cli_theme
    # Simulate 22:30 (night) -> within 18:00-07:00
    night = time.strptime("2026-09-08 22:30:00", "%Y-%m-%d %H:%M:%S")
    assert cli_theme.is_in_schedule(cfg["theme"]["schedule"], night) is True

    # Simulate 12:00 (day) -> outside window
    day = time.strptime("2026-09-08 12:00:00", "%Y-%m-%d %H:%M:%S")
    assert cli_theme.is_in_schedule(cfg["theme"]["schedule"], day) is False


def test_directory_hooks_carry_title_and_schedule():
    """Generated hooks embed tab title logic and schedule rules."""
    entries = [{"name": "repo-a", "path": "C:/Repos/repo-a", "escapes": "\x1b]11;#0B1F14\x1b\\"}]
    sched = {"theme": "eye-relief", "after": "18:00", "until": "07:00"}

    # PowerShell
    ps1 = theme_project.generate_ps1_hook(entries, schedule=sched)
    assert "$script:SchedTheme = 'eye-relief'" in ps1
    assert "$script:SchedAfter = '18:00'" in ps1
    assert "$script:SchedUntil = '07:00'" in ps1
    assert "[Console]::Write(\"`e]2;$title`e\\\")" in ps1

    # Bash
    sh = theme_project.generate_sh_hook(entries, schedule=sched)
    assert "_AD_SCHED_THEME='eye-relief'" in sh
    assert "_AD_SCHED_AFTER='18:00'" in sh
    assert "\\033]2;" in sh

    # Lua (Clink)
    lua = theme_project.generate_lua_hook(entries, schedule=sched)
    assert "clink.settitle" in lua


def test_transient_prompt_setting(tmp_path, monkeypatch):
    """Oh My Posh transient prompt can be configured on or off."""
    t = theme.GREENS
    cfg_on = omp.generate_omp_config(t, transient=True)
    assert "transient_prompt" in cfg_on

    cfg_off = omp.generate_omp_config(t, transient=False)
    assert "transient_prompt" not in cfg_off


def test_starship_config_generation():
    """Starship configuration generates valid TOML palette mapping."""
    t = theme.GREENS
    toml_str = starship.generate_starship_config(t)
    assert "format = \"\"\"" in toml_str
    assert t.accent in toml_str
    assert "[character]" in toml_str
