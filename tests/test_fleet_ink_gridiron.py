"""The gridiron (docs/skin-gridiron.md): the field itself, in the football genre, and the first
skin to use the state grammar's relaxation (docs/desk-ink.md §The state grammar across skins,
`expresses`): the genre's states as the field's own signs.

The skin is a module (`static/ink/skins/gridiron.js`) whose page is turf with yard lines and hash
marks and whose panes carry a line of scrimmage, a first-down line that advances a row per
transcript line, a penalty flag, a fumble and a touchdown, and a stylesheet
(`static/skins/gridiron/skin.css`) that holds the field's colours as custom properties. What is
asserted:

* `skins.py` offers it, in the football genre before the playbook, a dark side on `greens` and a
  light side on `eye-relief-day`;
* the stylesheet sets the numbers `skins.py` declares: the turf's pair, the yard line at the
  pair's end nearer the text, and every ink; every word it colours with an ink keeps 4.5:1 at
  both ends;
* `theme.check` holds both sides at both ends of the turf; the lines are decoration held at 3:1;
* the module `expresses` needs-you, running, error and done on every variant, carries no colour,
  no markup, no static import, fits `SKIN_BUDGET`, and names no team or league (#318);
* in a browser (`?ink=on`): with the ink on the table has no highlighter, bang or check row (the
  field signs instead), the scrimmage line appears when an agent runs and the first-down line
  advances a row per transcript line, a flag is thrown when a question opens and picked up when
  it is answered, an error draws the ball and it hops, a done draws the posts and the hatch; and
  with the ink off the plain page carries the whole grammar.
"""
from __future__ import annotations
import gzip
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import serve as S, skins

from desk_harness import close_pages
from test_fleet_ink import SKIN_BUDGET, _open, _repos, _serve, _stop, fleet_home  # noqa: F401 - fixtures by name
from test_fleet_ink_cues import expresses_of
from test_fleet_ink_playbook import (  # noqa: F401 - fixtures are used by name
    TRADEMARKS, _emit, _flag_off, _flag_on, _until_class, alive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "gridiron.js")
CSS = os.path.join(STATIC, "skins", "gridiron", "skin.css")

TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")
SIGNS = {"needs_name": "flag", "needs_q": "flag", "needs_card": "flag", "running": "drive",
         "error_bang": "fumble", "error_box": "fumble", "done": "touchdown"}


def _css_block(variant: str) -> dict:
    css = open(CSS, encoding="utf-8").read()
    out = {}
    for pattern in (r'body\[data-skin="gridiron"\]\s*\{(.*?)\}',
                    r'body\[data-skin="gridiron"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant):
        m = re.search(pattern, css, re.S)
        if m:
            out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1))))
    return out


# ============================================================================== without a browser


def test_the_gridiron_is_a_football_skin_the_settings_page_offers():
    assert skins.split("gridiron") == ("gridiron", "nightgame")
    assert skins.split("gridiron:daygame") == ("gridiron", "daygame")
    assert "gridiron" in S.ink_skins()
    assert skins.genre_of("gridiron") == "football"
    assert skins.GENRES["football"]["skins"] == ["gridiron", "playbook"]
    assert [v["name"] for v in skins.variants("gridiron")] == ["nightgame", "daygame"]
    assert skins.get_skin("gridiron")["base"] == "greens" and not theme.get("greens").light
    assert skins.get_skin("gridiron:daygame")["base"] == "eye-relief-day" and theme.get("eye-relief-day").light
    assert skins.get_skin("gridiron:auto")["auto"]["light"]["full"] == "gridiron:daygame"
    assert skins.get_skin("gridiron:auto")["auto"]["dark"]["full"] == "gridiron:nightgame"
    genre = next(g for g in skins.genres() if g["name"] == "football")
    assert [l["value"] for l in genre["looks"]] == ["gridiron", "playbook"]
    assert skins.resolve("gridiron", "light")["skin"] == "gridiron:daygame"


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The turf's two stripes and every ink, declared once in skins.py (where `theme.check` reads
    them) and named by skin.css (where the page and the module read them). `--paper` is the
    stripe on the palette's own side of the pair and `--turf-max` the other; the yard line is the
    end nearer the text's own ground, so a line under a word costs it nothing."""
    for variant, spec in skins.SKINS["gridiron"]["variants"].items():
        props = _css_block(variant)
        panel = spec["composited_panel"]
        light = theme.get(spec["base"]).light
        paper, other = (panel["lightest"], panel["darkest"]) if light else (panel["darkest"], panel["lightest"])
        assert props["paper"].upper() == paper.upper(), variant
        assert props["turf-max"].upper() == other.upper(), variant
        assert props["yard"].upper() == other.upper(), variant
        assert theme.is_dark(props["paper"]) == (not light), variant
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), (variant, tool)
        for token in ("text", "muted", "bg", "panel", "line"):
            assert token not in props, (variant, "the palette's own token, recoloured", token)
        # The lines are decoration, drawn between the rows: non-text contrast on both stripes.
        for line in ("gi-first", "gi-scrimmage"):
            for end in skins.composited_panels(spec):
                assert theme.contrast_ratio(props[line], end) >= 3.0, (variant, line, end)


def test_every_word_written_in_an_ink_reads_at_both_ends_and_theme_check_holds():
    css = open(CSS, encoding="utf-8").read()
    coloured = set(re.findall(r"(?<![\w-])color:\s*var\(--ink-(\w+)\)", css))
    assert coloured and not coloured & {"pen", "red"}, coloured
    for variant, spec in skins.SKINS["gridiron"]["variants"].items():
        base = theme.get(spec["base"])
        dark = theme.is_dark(_css_block(variant)["paper"])
        for end in skins.composited_panels(spec):
            theme.check(base, composited_panel=end, skin=f"gridiron:{variant}", inks=spec["inks"], dark=dark)
            assert theme.contrast_ratio(theme.to_css(base)["--muted"], end) >= 4.5, (variant, end)
            for tool in coloured:
                assert theme.contrast_ratio(spec["inks"][tool], end) >= 4.5, (variant, tool, end)
        assert theme.hue_distance(spec["inks"]["pen"], spec["inks"]["marker"]) >= 30, variant


def test_the_module_expresses_the_field_and_carries_no_colour_no_markup_and_fits_its_budget():
    assert expresses_of(MODULE) == {"*": SIGNS}
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the gridiron module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList", "MutationObserver"):
        assert banned not in code, banned
    assert 'document.body.matches(".ink-off")' in code, "the plain page is handed the grammar"
    size = len(gzip.compress(open(MODULE, "rb").read(), 6, mtime=0))
    assert size < SKIN_BUDGET, size
    read = set(re.findall(r'"(--(?:gi|turf)-[\w-]+|--yard|--paper)"', body))
    css = open(CSS, encoding="utf-8").read()
    written = set("--" + p for p in re.findall(r"--((?:gi|turf)-[\w-]+|yard|paper):", css))
    assert read == written, (sorted(read - written), sorted(written - read))


def test_nothing_the_skin_says_or_draws_names_a_team_or_a_league():
    gi = skins.SKINS["gridiron"]
    said = [open(MODULE, encoding="utf-8").read(), open(CSS, encoding="utf-8").read(), gi["title"], gi["why"]]
    for spec in gi["variants"].values():
        said += [spec["title"], spec["why"]]
    for text in said:
        for word in TRADEMARKS:
            assert word not in text.lower(), (word, text[:80])


# ================================================================================ in a browser

LOAD = "async () => { window.__gi = await import(q('/static/ink/skins/gridiron.js')); }"


def _desk(tmp_path, fleet_home, names=("alpha", "beta")):
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "gridiron"}}', encoding="utf-8")


def _field(page, cond):
    page.wait_for_function(f"() => {{ const gi = window.__gi && window.__gi.inspect(); return !!gi && ({cond}); }}",
                           timeout=20000)


def _pane(page, repo):
    return page.evaluate("r => window.__gi.inspect().panes[r] || null", repo)


def _rows(page):
    return page.evaluate("() => Ink.inspect().layer ? Ink.inspect().layer.marks.map(m => [m.tool, m.shape]) : null")


@pytest.mark.browser
def test_the_field_signs_the_drive_the_flag_the_fumble_and_the_touchdown(fleet_home, tmp_path, alive, desk_browser):
    """One test for the field's signs (the fewest the budget allows). With the ink on, the table
    has no highlighter, bang or check row: the field signs instead. A supervised turn shows the
    line of scrimmage under the head and the first-down line at it; each transcript line moves the
    first-down line one row (28px) down, and it settles at its goal. A question opened throws the
    flag, answered picks it up. An error draws the ball and it hops to rest. A done draws the
    posts and the hatch. Then, with the ink off, the plain page's table is the whole grammar."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(desk_browser, port, token, "&ink=on", width=1000, height=620)
        page.wait_for_function("() => Ink.inspect().table === 'gridiron:nightgame'", timeout=15000)
        page.evaluate(LOAD)
        _field(page, "!!gi.panes.alpha && !!gi.panes.beta && gi.builds >= 1")
        rows = _rows(page)
        assert rows and not [r for r in rows if r[0] == "highlighter" or r[1] in ("bang", "check")], rows
        hooks = page.evaluate("() => Ink.inspect().layer.skin.hooks")
        assert hooks == ["paper", "frame", "tick", "dispose"], hooks
        assert _pane(page, "alpha")["scrimmage"] is None and _pane(page, "alpha")["first"] is None
        # The drive: a supervised turn, then three lines.
        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _until_class(page, "alpha", "state-running")
        _field(page, "gi.panes.alpha.scrimmage !== null && gi.panes.alpha.first !== null && gi.panes.alpha.drive.live")
        at = _pane(page, "alpha")
        y0, lines0 = at["scrimmage"], at["drive"]["lines"]
        _emit(page, "alpha", ("assistant_text", {"text": "reading the view"}),
              ("assistant_text", {"text": "found the file"}), ("assistant_text", {"text": "changing it"}))
        _field(page, f"gi.panes.alpha.drive.lines >= {lines0 + 3} && gi.panes.alpha.drive.at === gi.panes.alpha.drive.to"
                     f" && gi.panes.alpha.drive.to > 0")
        at = _pane(page, "alpha")
        assert at["scrimmage"] == y0 and at["first"] == y0 + at["drive"]["to"], at
        assert at["drive"]["to"] % 28 == 0 and at["drive"]["to"] >= 3 * 28, at
        # The flag on beta, thrown and picked up.
        _flag_on(page, "beta", "q1")
        _field(page, "gi.panes.beta.flag === 'resting' && gi.panes.beta.throws === 1")
        assert _pane(page, "beta")["flagBox"] is not None
        _flag_off(page, "beta", "q1")
        _field(page, "gi.panes.beta.flag === 'none'")
        # The fumble on beta.
        _emit(page, "beta", ("error", {"exit_code": 2}))
        _until_class(page, "beta", "state-error")
        _field(page, "gi.panes.beta.ball === 'resting' && gi.panes.beta.hops === 1")
        assert _pane(page, "beta")["ballBox"] is not None
        # The touchdown on alpha.
        alive.discard("alpha")
        _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "alpha", "is-done")
        _field(page, "gi.panes.alpha.posts === 1 && gi.panes.alpha.hatch === 1 && gi.panes.alpha.first === null")
        assert len(_pane(page, "alpha")["hatchBoxes"]) >= 10
        assert not errors, errors
        close_pages(desk_browser)

        # Ink off: the plain page is handed the whole grammar.
        page, errors, _ = _open(desk_browser, port, token, "&ink=off")
        page.wait_for_function("() => Ink.inspect().table === 'gridiron:nightgame' && Ink.inspect().plain", timeout=15000)
        table = page.evaluate("async () => { const m = await import(q('/static/ink/skins/gridiron.js'));"
                              " return m.marks('nightgame').map(r => [r.tool, r.shape]); }")
        assert [r for r in table if r[0] == "highlighter"] and ["marker", "bang"] in table and ["green", "check"] in table, table
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        _stop(server)
