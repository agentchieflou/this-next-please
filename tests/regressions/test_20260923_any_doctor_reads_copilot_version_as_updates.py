"""2026-09-23, ad-doctor in Windows/Linux: the doctor reads copilot version as 'updates.'.

Symptom:

    copilot --version on 1.0.88 prints GitHub Copilot CLI 1.0.88. and Run 'copilot update' to check for updates.; the doctor's copilot row read updates. (this fleet was measured against 1.0.81)

The doctor parsed the version by taking text.split()[-1] from copilot --version,
which took the last word 'updates.' from the two-line output instead of the version number.

Issue: https://github.com/agentchieflou/this-next-please/issues/358
"""
from __future__ import annotations

import pytest

from agentdata.setup.steps.fleet import FleetStep
from agentdata.setup.wizard import Context, Detectors, Prompter


def test_the_version_is_read_from_the_two_line_output(monkeypatch):
    from agentdata import proc

    def fake_run(argv, timeout=60):
        if argv == ["copilot", "--version"]:
            return (0, "GitHub Copilot CLI 1.0.88.\nRun 'copilot update' to check for updates.\n", "", 0.1)
        if argv == ["copilot", "--help"]:
            return (0, "", "", 0.1)
        return (0, "", "", 0.1)

    monkeypatch.setattr(proc, "run", fake_run)
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    probe = FleetStep()._probe(ctx)
    assert probe["version"] == "1.0.88"


def test_the_copilot_row_shows_the_version_without_the_measured_suffix(monkeypatch):
    from agentdata import proc

    def fake_run(argv, timeout=60):
        if argv == ["copilot", "--version"]:
            return (0, "GitHub Copilot CLI 1.0.88.\nRun 'copilot update' to check for updates.\n", "", 0.1)
        if argv == ["copilot", "--help"]:
            return (0, "", "", 0.1)
        return (0, "", "", 0.1)

    monkeypatch.setattr(proc, "run", fake_run)
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    step = FleetStep()
    found = step._probe(ctx)
    base = {"enabled": True, "repos": [], "toast": "off",
            "settings": {"toast": False, "cooldown": 300, "idle_minutes": 20, "quiet_hours": "",
                         "dashboard": True, "chime": False},
            "version": found["version"], "why": found["why"], "login": found["login"], "port": 8765,
            "port_free": True, "ours": False}
    step.check(ctx, base)
    rows = {f"{c.step}/{c.name}": c for c in ctx.checks}
    assert rows["fleet/copilot"].detail == "1.0.88"
    assert "measured against" not in rows["fleet/copilot"].detail


def test_a_bare_version_still_parses(monkeypatch):
    from agentdata import proc

    monkeypatch.setattr(proc, "run", lambda argv, timeout=60: (0, "1.0.81\n", "", 0.1))
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    probe = FleetStep()._probe(ctx)
    assert probe["version"] == "1.0.81"
    assert probe["why"] == ""

    monkeypatch.setattr(proc, "run", lambda argv, timeout=60: (1, "", "command not found", 0.1))
    probe_fail = FleetStep()._probe(ctx)
    assert probe_fail["version"] == ""
    assert "command not found" in probe_fail["why"]
