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


def test_escapes_rendering():
    """theme.escapes renders OSC 4, 10, 11, 12; reset renders OSC 110, 111, 112."""
    t = theme.GREENS
    esc = theme.escapes(t)
    assert "\x1b]4;0;#0B1F14\x1b\\" in esc
    assert "\x1b]10;#CDE6D2\x1b\\" in esc
    assert "\x1b]11;#0B1F14\x1b\\" in esc
    assert "\x1b]12;#3FB950\x1b\\" in esc

    reset = theme.reset_escapes()
    assert "\x1b]110\x1b\\" in reset
    assert "\x1b]111\x1b\\" in reset
    assert "\x1b]112\x1b\\" in reset

    # none theme renders empty string
    assert theme.escapes(theme.NONE) == ""


def test_piped_apply_and_reset(capsys, monkeypatch):
    """ad-theme apply/reset when piped emit no escapes and report mechanism none."""
    monkeypatch.setenv("AGENTDATA_COLOR", "never")
    color.reset_cache()

    rc = cli_theme.main(["apply", "greens"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "mechanism: none" in out

    rc = cli_theme.main(["reset"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "mechanism: none" in out


def test_docs_themes_exists_and_covers_matrix():
    """docs/themes.md exists and documents the host matrix."""
    with open("docs/themes.md", "r", encoding="utf-8") as f:
        doc = f.read()
    assert "windows-terminal" in doc
    assert "conhost" in doc
    assert "mintty" in doc
    assert "vscode" in doc


def test_theme_css_passes_contrast_and_matches_terminal_hex():
    """theme.to_css(t) passes contrast floors on rendered pairs for built-ins and 200 random rolls,
    and css['--human'] == t.status['fail']."""
    # 1. Built-in themes
    for t in theme.list_themes():
        if t.name == "none":
            continue
        c = theme.to_css(t)
        panel = c["--panel"]
        bg = c["--bg"]
        select = c["--select"]
        assert theme.contrast_ratio(c["--text"], bg) >= 4.5
        assert theme.contrast_ratio(c["--text"], panel) >= 4.5
        assert theme.contrast_ratio(c["--muted"], bg) >= 4.5, f"{t.name} muted on bg"
        assert theme.contrast_ratio(c["--muted"], panel) >= 4.5, f"{t.name} muted on panel"
        assert theme.contrast_ratio(c["--muted"], select) >= 4.5, f"{t.name} muted on select"
        for role in ("--human", "--waiting", "--done", "--running", "--idle"):
            assert theme.contrast_ratio(c[role], panel) >= 3.0, f"{t.name} {role} contrast < 3.0"
        assert c["--human"] == t.status["fail"]

    # 2. 200 random rolls
    for i in range(200):
        t = theme.random_theme(i * 1013 + 7)
        c = theme.to_css(t)
        panel = c["--panel"]
        bg = c["--bg"]
        select = c["--select"]
        assert theme.contrast_ratio(c["--text"], panel) >= 4.5
        assert theme.contrast_ratio(c["--muted"], bg) >= 4.5
        assert theme.contrast_ratio(c["--muted"], panel) >= 4.5
        assert theme.contrast_ratio(c["--muted"], select) >= 4.5
        for role in ("--human", "--waiting", "--done", "--running", "--idle"):
            assert theme.contrast_ratio(c[role], panel) >= 3.0
        assert c["--human"] == t.status["fail"]


def test_theme_check_rule_6_muted_contrast():
    """Rule 6 of theme.check: to_css(t)['--muted'] >= 4.5:1 on target_ground for built-ins and random rolls,
    and a broken case (muted='#6E7681' on dark ground) is refused with a hint."""
    import dataclasses

    for t in theme.list_themes():
        if t.name == "none":
            continue
        theme.check(t)

    for i in range(200):
        t = theme.random_theme(i * 1013 + 7)
        theme.check(t)

    broken = dataclasses.replace(theme.DARK, muted="#6E7681")
    with pytest.raises(theme.ThemeError) as exc:
        theme.check(broken)
    err = str(exc.value)
    assert "muted contrast" in err and "below 4.5:1 floor" in err
    assert "muted '#6E7681' on ground '#14171A'" in exc.value.hint


def test_theme_check_rule_7_the_word_on_a_state_colour():
    """Rule 7 of theme.check (#327): each to_css(t)['--on-<role>'] reads >= 4.5:1 on its role colour for
    every built-in and 200 random rolls; the chosen colour is the first of text, ground, white and
    #111111 that does; and a palette whose word cannot reach 4.5:1 is refused with a hint."""
    import dataclasses

    roles = ("--running", "--waiting", "--human", "--done", "--idle")
    palettes = [t for t in theme.list_themes() if t.name != "none"]
    palettes += [theme.random_theme(i * 1013 + 7) for i in range(200)]
    for t in palettes:
        c = theme.to_css(t)
        for role in roles:
            on = c["--on-" + role[2:]]
            assert theme.contrast_ratio(on, c[role]) >= 4.5, f"{t.name} {on} on {role} {c[role]}"
            first = next(x for x in (t.text, t.ground, "#FFFFFF", "#111111")
                         if theme.contrast_ratio(x, c[role]) >= 4.5)
            assert on == first, f"{t.name} {role}: {on}, the rule's first is {first}"
        theme.check(t)

    # A mid grey no candidate reaches 4.5:1 on: the best of them is written, and check refuses it.
    grey = dataclasses.replace(theme.DARK, status=dict(theme.DARK.status, info="#787878"))
    c = theme.to_css(grey)
    assert c["--on-running"] == max((grey.text, grey.ground, "#FFFFFF", "#111111"),
                                    key=lambda x: theme.contrast_ratio(x, "#787878"))
    with pytest.raises(theme.ThemeError) as exc:
        theme.check(grey)
    assert "the word on --running" in str(exc.value) and "below 4.5:1 floor" in str(exc.value)
    assert f"--on-running '{c['--on-running']}' on --running '#787878'" in exc.value.hint


ROLES = ("--running", "--waiting", "--human", "--done", "--idle")


def test_theme_check_rule_8_a_word_in_a_state_colour():
    """Rule 8 of theme.check (#328): each `--<role>-text` token reads >= 4.5:1 on the palette's
    ground and on every panel it is drawn on -- for every built-in with `skins.panels_on(name)` and
    for 200 random rolls with none. The token is the role colour itself where that already reads on
    `--bg`, `--panel`, `--select` and every panel, else the first step of 0.02 toward `--text` that
    does; and a palette whose words cannot reach 4.5:1 on a panel is refused with a hint naming both."""
    from agentdata.fleet import skins

    palettes = [(t, skins.panels_on(t.name)) for t in theme.list_themes() if t.name != "none"]
    palettes += [(theme.random_theme(i * 1013 + 7), []) for i in range(200)]
    for t, panels in palettes:
        theme.check(t, panels=panels)
        c = theme.to_css(t, panels=panels)
        grounds = (c["--bg"], c["--panel"], c["--select"], *panels)
        for role in ROLES:
            word = c[role + "-text"]
            steps = [c[role]] + [theme.mix(c[role], c["--text"], s / 50) for s in range(1, 50)]
            first = next((x for x in steps if all(theme.contrast_ratio(x, g) >= 4.5 for g in grounds)),
                         c["--text"])
            assert word == first, f"{t.name} {role}-text {word}, the rule's first is {first}"
            assert all(theme.contrast_ratio(word, g) >= 4.5 for g in grounds), f"{t.name} {role}-text {word}"
        # The role colour itself stays for marks: rule 2's 3:1, unchanged.
        assert c["--human"] == t.status["fail"]

    # A panel on which no word reaches 4.5:1, not even the text: every word falls back to `--text`,
    # and rule 8 refuses it there. Rules 1-7 read the palette's own ground, so they pass it.
    with pytest.raises(theme.ThemeError) as exc:
        theme.check(theme.DARK, panels=["#7A7F84"])
    assert "the word in --running" in str(exc.value) and "below 4.5:1 floor" in str(exc.value)
    assert "--running-text '#E3E7EA' on '#7A7F84'" in exc.value.hint


def test_the_pressed_ground_holds_text_at_4_5():
    """Rule 9 of theme.check (#328), "pressed ground": `--text` on `--select`, the ground a pressed
    control writes its word on (the model picker's pill, the pressed tab, the pin), reads >= 4.5:1
    for every built-in and 200 random rolls. A palette whose text reads on its page and not on a
    pressed control is refused by rule 9 alone, with a hint naming the text, the select and the
    accent the select moved toward."""
    palettes = [t for t in theme.list_themes() if t.name != "none"]
    palettes += [theme.random_theme(i * 1013 + 7) for i in range(200)]
    for t in palettes:
        c = theme.to_css(t)
        assert theme.contrast_ratio(c["--text"], c["--select"]) >= 4.5, (t.name, c["--text"], c["--select"])
        theme.check(t)

    crafted = Theme(
        name="pressed-grey", title="Pressed grey", why="text that reads on the page, not when pressed",
        ground="#FFFFFF", text="#6E6E6E", accent="#000000", cursor="#000000",
        ansi=theme._make_ansi("#FFFFFF", "#6E6E6E", "#000000", light=True),
        status={"ok": "#2E7D32", "warn": "#8A6D00", "fail": "#C62828", "skip": "#6E6E6E",
                "info": "#1565C0"},
        light=True, muted="#595959",
    )
    c = theme.to_css(crafted)
    assert c["--select"] == "#D1D1D1"
    assert round(theme.contrast_ratio("#6E6E6E", "#FFFFFF"), 2) == 5.10
    assert round(theme.contrast_ratio("#6E6E6E", "#D1D1D1"), 2) == 3.34
    with pytest.raises(ThemeError) as exc:
        check(crafted)
    # Refused by rule 9, the last: rules 1-8 passed it.
    assert "pressed ground" in str(exc.value), str(exc.value)
    for colour in ("#6E6E6E", "#D1D1D1", "#000000"):
        assert colour in exc.value.hint, (colour, exc.value.hint)


def test_theme_escapes_are_byte_identical_to_golden():
    """theme.escapes(t) for every built-in is byte-identical to golden captured at 8557b2b."""
    golden = {
        'blues': '\x1b]4;0;#0B1B33\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#D6E4F7\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#D6E4F7\x1b\\\x1b]11;#0B1B33\x1b\\\x1b]12;#4DA3FF\x1b\\',
        'dark': '\x1b]4;0;#14171A\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#E3E7EA\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#E3E7EA\x1b\\\x1b]11;#14171A\x1b\\\x1b]12;#58A6FF\x1b\\',
        'eye-relief': '\x1b]4;0;#2B2A27\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#D6CDB8\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#D6CDB8\x1b\\\x1b]11;#2B2A27\x1b\\\x1b]12;#C9A227\x1b\\',
        'eye-relief-day': '\x1b]4;0;#F2ECDC\x1b\\\x1b]4;1;#B3261E\x1b\\\x1b]4;2;#2E7D4F\x1b\\\x1b]4;3;#A8651B\x1b\\\x1b]4;4;#2B6CB0\x1b\\\x1b]4;5;#7B2CBF\x1b\\\x1b]4;6;#0E8A8A\x1b\\\x1b]4;7;#3B3A34\x1b\\\x1b]4;8;#8C867A\x1b\\\x1b]4;9;#D32F2F\x1b\\\x1b]4;10;#388E3C\x1b\\\x1b]4;11;#F57C00\x1b\\\x1b]4;12;#1976D2\x1b\\\x1b]4;13;#8E24AA\x1b\\\x1b]4;14;#0097A7\x1b\\\x1b]4;15;#1A1A1A\x1b\\\x1b]10;#3B3A34\x1b\\\x1b]11;#F2ECDC\x1b\\\x1b]12;#8A6D1F\x1b\\',
        'greens': '\x1b]4;0;#0B1F14\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#CDE6D2\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#CDE6D2\x1b\\\x1b]11;#0B1F14\x1b\\\x1b]12;#3FB950\x1b\\',
        'matrix': '\x1b]4;0;#020A03\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#3DF07A\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#3DF07A\x1b\\\x1b]11;#020A03\x1b\\\x1b]12;#00FF41\x1b\\',
        'nfl-browns': '\x1b]4;0;#311D00\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#F2E8D9\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#F2E8D9\x1b\\\x1b]11;#311D00\x1b\\\x1b]12;#FF3C00\x1b\\',
        'none': '',
        'reds': '\x1b]4;0;#400000\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#F2D9D9\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#F2D9D9\x1b\\\x1b]11;#400000\x1b\\\x1b]12;#FF5C5C\x1b\\',
        'sand': '\x1b]4;0;#EFE6D2\x1b\\\x1b]4;1;#B3261E\x1b\\\x1b]4;2;#2E7D4F\x1b\\\x1b]4;3;#A8651B\x1b\\\x1b]4;4;#2B6CB0\x1b\\\x1b]4;5;#7B2CBF\x1b\\\x1b]4;6;#0E8A8A\x1b\\\x1b]4;7;#3A3126\x1b\\\x1b]4;8;#8C867A\x1b\\\x1b]4;9;#D32F2F\x1b\\\x1b]4;10;#388E3C\x1b\\\x1b]4;11;#F57C00\x1b\\\x1b]4;12;#1976D2\x1b\\\x1b]4;13;#8E24AA\x1b\\\x1b]4;14;#0097A7\x1b\\\x1b]4;15;#1A1A1A\x1b\\\x1b]10;#3A3126\x1b\\\x1b]11;#EFE6D2\x1b\\\x1b]12;#B9631E\x1b\\',
        'vanta-black': '\x1b]4;0;#000000\x1b\\\x1b]4;1;#F85149\x1b\\\x1b]4;2;#3FB950\x1b\\\x1b]4;3;#D29922\x1b\\\x1b]4;4;#58A6FF\x1b\\\x1b]4;5;#BC8CFF\x1b\\\x1b]4;6;#39C5CF\x1b\\\x1b]4;7;#C8C8C8\x1b\\\x1b]4;8;#6E7681\x1b\\\x1b]4;9;#FF7B72\x1b\\\x1b]4;10;#56D364\x1b\\\x1b]4;11;#E3B341\x1b\\\x1b]4;12;#79C0FF\x1b\\\x1b]4;13;#D2A8FF\x1b\\\x1b]4;14;#56D4DD\x1b\\\x1b]4;15;#FFFFFF\x1b\\\x1b]10;#C8C8C8\x1b\\\x1b]11;#000000\x1b\\\x1b]12;#E6E6E6\x1b\\',
    }
    for t in theme.list_themes():
        assert theme.escapes(t) == golden[t.name]
