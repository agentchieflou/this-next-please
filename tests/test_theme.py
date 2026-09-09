"""Tests for theme model, contrast checking, palettes, and CLI.

Closes acceptance criteria for #136 and #153.
"""
from __future__ import annotations

import io
import re
import sys
import pytest

from agentdata import cli_theme
from agentdata import color
from agentdata import theme
from agentdata.theme import Theme, ThemeError, check


def test_all_builtins_pass_check():
    """All 11 built-in themes pass theme.check()."""
    themes = theme.list_themes()
    assert len(themes) >= 11
    for t in themes:
        check(t)


def test_broken_themes_refused_with_hint():
    """Deliberately broken themes are refused with an informative hint naming the pair."""
    # 1. White-on-black vanta-black exceeds 19:1 cap
    broken_vanta = Theme(
        name="vanta-broken",
        title="Broken Vanta",
        why="too harsh",
        ground="#000000",
        text="#FFFFFF",  # 21:1 contrast, exceeds 19:1
        accent="#E6E6E6",
        cursor="#E6E6E6",
        ansi=theme.VANTA_BLACK.ansi,
        status=theme.VANTA_BLACK.status,
    )
    with pytest.raises(ThemeError) as exc_vanta:
        check(broken_vanta)
    assert "exceeds 19:1 cap" in str(exc_vanta.value)
    assert "#FFFFFF" in exc_vanta.value.hint and "#000000" in exc_vanta.value.hint

    # 2. Red fail on reds ground (insufficient contrast or close in hue)
    broken_reds = Theme(
        name="reds",
        title="Broken Reds",
        why="invisible red fail",
        ground="#400000",
        text="#F2D9D9",
        accent="#FF5C5C",
        cursor="#FF5C5C",
        ansi=theme.REDS.ansi,
        status={
            "ok": "#7EE787",
            "warn": "#FFA657",
            "fail": "#4A0505",  # Contrast < 3:1 on #400000
            "skip": "#8B949E",
            "info": "#79C0FF",
        }
    )
    with pytest.raises(ThemeError) as exc_reds:
        check(broken_reds)
    assert "below 3:1 floor" in str(exc_reds.value)
    assert "status.fail" in exc_reds.value.hint

    # 3. Fail hue too close to text on reds proof theme
    broken_reds_hue = Theme(
        name="reds",
        title="Broken Reds Hue",
        why="fail too close to text",
        ground="#400000",
        text="#F2D9D9",  # Hue ~0
        accent="#FF5C5C",
        cursor="#FF5C5C",
        ansi=theme.REDS.ansi,
        status={
            "ok": "#7EE787",
            "warn": "#FFA657",
            "fail": "#FF8080",  # Hue ~0, contrast passes but hue distance < 35 to text
            "skip": "#8B949E",
            "info": "#79C0FF",
        }
    )
    with pytest.raises(ThemeError) as exc_hue:
        check(broken_reds_hue)
    assert "too close to text in hue" in str(exc_hue.value)


def test_proof_themes_fail_not_within_hue_distance_of_text():
    """Matrix and Reds are proof themes: fail is not within 35° hue distance of text."""
    for name in ("matrix", "reds"):
        t = theme.get(name)
        hd = theme.hue_distance(t.status["fail"], t.text)
        assert hd >= 35.0, f"Theme '{name}' fail ({t.status['fail']}) too close to text ({t.text}) in hue: {hd}°"


def test_random_theme_stability_and_validation():
    """Random with same seed yields identical palette; 200 rolls all pass check()."""
    t1 = theme.random_theme("repo-alpha")
    t2 = theme.random_theme("repo-alpha")
    assert t1.ground == t2.ground
    assert t1.text == t2.text
    assert t1.accent == t2.accent

    # 200 rolls all pass check()
    for i in range(200):
        t = theme.random_theme(i * 1013 + 7)
        check(t)


def test_piped_theme_list_contains_no_escape_bytes(capsys, monkeypatch):
    """ad-theme list piped contains zero escape bytes (SGR or OSC) for every theme."""
    monkeypatch.setenv("AGENTDATA_COLOR", "never")
    color.reset_cache()

    rc = cli_theme.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out

    # No ANSI escape sequences
    assert "\x1b" not in out
    # Must be valid TOON table
    assert "themes[11]{name,title,ground,accent,light,why}:" in out
    for t in theme.list_themes():
        assert t.name in out


def test_piped_gallery_prints_names_only(capsys, monkeypatch):
    """ad-theme gallery when piped prints theme names only with zero escapes."""
    monkeypatch.setenv("AGENTDATA_COLOR", "never")
    color.reset_cache()

    rc = cli_theme.main(["gallery"])
    assert rc == 0
    out = capsys.readouterr().out

    assert "\x1b" not in out
    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    assert "greens" in lines
    assert "reds" in lines
    assert "matrix" in lines
    assert "dark" in lines
    assert "vanta-black" in lines


def test_plan_cli_theming_table_matches_constants():
    """docs/plan-cli-theming.md's palette table matches the Theme constants."""
    with open("docs/plan-cli-theming.md", "r", encoding="utf-8") as f:
        content = f.read()

    # Check that each theme name appears in the palette table
    for name in ("greens", "reds", "eye-relief", "eye-relief-day", "nfl-browns",
                 "dark", "vanta-black", "matrix", "blues", "sand", "random", "none"):
        pattern = rf"\|\s*`{name}`\s*\|"
        assert re.search(pattern, content) is not None, f"Theme '{name}' missing from docs/plan-cli-theming.md table"


def test_cli_theme_show(capsys):
    """ad-theme show displays theme details in TOON."""
    rc = cli_theme.main(["show", "greens"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: greens" in out
    assert "ground: #0B1F14" in out
    assert "status[6]{role,hex}:" in out


def test_cli_theme_set_and_unset(tmp_path, monkeypatch, capsys):
    """ad-theme set and unset update config.json."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setenv("AGENTDATA_CONFIG", str(cfg_file))

    # Set default
    rc = cli_theme.main(["set", "greens"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok: true" in out
    assert "set: greens" in out

    # Show with --cwd should resolve default
    rc = cli_theme.main(["show", "--cwd"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "name: greens" in out

    # Set for specific project
    proj_dir = str(tmp_path / "myproj")
    rc = cli_theme.main(["set", "matrix", "--project", proj_dir])
    assert rc == 0

    # Unset project
    rc = cli_theme.main(["unset", "--project", proj_dir])
    assert rc == 0

    # Unset default
    rc = cli_theme.main(["unset"])
    assert rc == 0
