"""2026-09-23, `ad-doctor` on any shell: the copilot row read the CLI's update hint as its version.

Symptom (`copilot --version` on Copilot CLI 1.0.88):

    GitHub Copilot CLI 1.0.88.
    Run 'copilot update' to check for updates.

and the doctor's copilot row read:

    copilot ok  updates. (this fleet was measured against 1.0.81)

`_probe` took `text.split()[-1]`, the last word of the output, which is `updates.` once the CLI
prints a second line; `_older("updates.", "1.0.81")` then read it as `[0, 0]` and appended the
"measured against" suffix. The version is now the first `N.N.N` in the output, and output with no
version in it is the `fail` row's reason instead of an empty one.

Issue: https://github.com/agentchieflou/this-next-please/issues/358
"""
from __future__ import annotations

from agentdata.setup.steps.fleet import FleetStep
from agentdata.setup.wizard import Context, Detectors, Prompter

import fakes


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

    # rc 0 with no version in it: no version, and the fail row says what the CLI printed
    monkeypatch.setattr(proc, "run", lambda argv, timeout=60: (0, "Copilot CLI (dev build)\n", "", 0.1))
    probe_none = FleetStep()._probe(ctx)
    assert probe_none["version"] == ""
    assert probe_none["why"] == "Copilot CLI (dev build)"


def test_the_fake_copilot_version_transcript_is_read_as_its_version(monkeypatch, tmp_path):
    """The fake `copilot` (#416) replays the captured two-line `--version`, through the real
    `proc.run`, so the doctor is proved against the same bytes every fleet test sees."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"])
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    probe = FleetStep()._probe(ctx)
    assert probe["version"] == "1.0.88", probe
    assert probe["why"] == ""
