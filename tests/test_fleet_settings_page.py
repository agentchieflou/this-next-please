"""`/settings`: a page of its own, and everything that used to be true of the popover.

The operator's report was *the settings button isn't functional at all* — it was a popover holding
two pickers, behind a control that reads like it leads somewhere. It leads somewhere now, and the
behaviour that the popover had earned over three issues has to survive the move rather than be
re-learned:

* #195, the one that matters most: the pickers must say what is ALREADY on. They used to open
  reading *system · no skin* over a configured skin, because `/api/themes` returned the choices and
  not the choice. A standalone page makes that worse, not better — it has no desk stream behind it
  — so this page opens its own EventSource for the `theme` frame, and that is asserted here.
* #150/#154, the skin→palette coupling: while a skin is on, the palette is the skin's, and the
  control says so rather than taking an instruction the server would overrule.
* The picker that shows nothing at all, which is the one thing a picker may never do.

Same rule as the rest of the desk suite: assert on the rendered page and on the consequence, not on
the source text.
"""
from __future__ import annotations
import json
import os
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S, skins as K
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The module-level desk state, reset per test. CI runs this suite under two shuffle seeds, so
    a test that inherits another's selection fails in one order and not the other."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


def _repos(tmp_path, *names):
    for name in names:
        path = make_project(tmp_path / name, ticket="RDSD-1")
        Registry().add(path, name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _settings(p, port, token):
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
    # An <option> inside a <select> is never "visible" to Playwright, so the wait is on the count.
    page.wait_for_function("""() => {
        const t = document.getElementById('theme'), s = document.getElementById('skin');
        return t && s && t.options.length > 1 && s.options.length > 1;
    }""", timeout=15000)
    return browser, page, errors


# ------------------------------------------------------------------------------------ the page


@pytest.mark.browser
def test_the_page_renders_every_section_and_can_get_back(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_selector("#modelrows tr", timeout=10000)

            heads = page.eval_on_selector_all("h2", "els => els.map(e => e.textContent.trim())")
            assert heads == ["Appearance", "Model per agent", "Copilot", "What an agent may run"], heads

            # one row per registered repository, in the registry's order
            repos = page.eval_on_selector_all("#modelrows tr td:first-child",
                                              "els => els.map(e => e.textContent)")
            assert repos == ["alpha", "beta"], repos

            # the Copilot block is built from the server's enumerated table, not from the markup
            assert page.eval_on_selector_all("#cfgrows .setrow", "els => els.length") > 5
            assert page.eval_on_selector_all("#allowlist li", "els => els.length") > 5
            assert page.eval_on_selector_all("#denylist li", "els => els.length") > 5

            back = page.locator("#backbtn")
            assert f"t={token}" in (back.get_attribute("href") or ""), "the way back carries no token"
            back.click()
            page.wait_for_selector(".toolbar #setbtn", timeout=10000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_nothing_hidden_is_visible_or_swallows_a_click(fleet_home, tmp_path):
    """The defect that made the whole desk unusable in 0.8.0: an id selector setting `display:flex`
    outranks the browser's `[hidden]` rule, so `el.hidden = true` changed an attribute and nothing
    else, and full-height panels ate every click meant for what was under them."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            shown = page.evaluate("""() => Array.from(document.querySelectorAll('[hidden]'))
                .filter(el => el.getBoundingClientRect().width > 0)
                .map(el => el.id || el.className)""")
            assert shown == [], f"hidden and still on the glass: {shown}"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------------------ the theme


@pytest.mark.browser
def test_the_pickers_say_what_is_already_worn(fleet_home, tmp_path):
    """#195, ported. The pickers opened reading *system · no skin* over whatever the config said.

    Two faults, one visible failure. `/api/themes` returned the palettes and the skins and never
    which of them was chosen, so the page could fill the controls but not set them; and the frame
    that does carry the answer arrived while `loadThemes` was still fetching, so it was thrown away
    when the options were rebuilt under it. On a page with no stream at all this would simply never
    self-correct, which is why this one opens an EventSource for that single frame.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")
    (tmp_path / "cfg.json").write_text(
        json.dumps({"theme": {"default": "dark", "skin": "glass:smoke"}}), encoding="utf-8")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_function(
                """() => document.getElementById('skin').value === 'glass:smoke'""", timeout=10000)
            state = page.evaluate("""() => {
                const t = document.getElementById('theme'), s = document.getElementById('skin');
                return { palette: t.value, paletteOff: t.disabled, paletteWhy: t.title,
                         skin: s.value, blank: t.selectedIndex < 0 || s.selectedIndex < 0,
                         painted: document.body.getAttribute('data-skin') };
            }""")
            assert state["skin"] == "glass:smoke", state
            assert state["palette"] == "dark", state
            assert not state["blank"], "a picker showing nothing at all is the one thing it may not do"
            assert state["paletteOff"] and "comes from the skin" in state["paletteWhy"], state
            # ...and the page is actually WEARING it, not merely reporting it.
            assert state["painted"] == "glass", state

            page.select_option("#skin", "none")
            page.wait_for_function(
                """() => !document.getElementById('theme').disabled""", timeout=10000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_palette_picker_says_the_skin_is_driving_it(fleet_home, tmp_path):
    """Skins drive palettes, so while one is on the palette picker shows what is being rendered and
    says why it is not taking instructions -- rather than accepting a choice the server overrides."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            assert page.evaluate("() => document.getElementById('theme').disabled") is False

            page.select_option("#skin", "voxel:nether")
            page.wait_for_function(
                """() => document.getElementById('theme').disabled === true""", timeout=10000)
            picker = page.evaluate("""() => {
                const t = document.getElementById('theme'), s = document.getElementById('skin');
                return { theme: t.value, title: t.title, skin: s.value };
            }""")
            assert picker["theme"] == "reds", "it shows the ground the skin brought"
            assert "comes from the skin" in picker["title"]
            assert picker["skin"] == "voxel:nether", "and the skin picker sits on the variant"

            page.select_option("#skin", "none")
            page.wait_for_function(
                """() => document.getElementById('theme').disabled === false""", timeout=10000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_skin_picker_groups_variants_under_their_skin(fleet_home, tmp_path):
    """One control, not two. "Nether" means nothing beside Farmstead, and a second picker offering
    it would be offering a combination that does not exist."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            groups = page.evaluate("""() => Array.from(document.querySelectorAll('#skin optgroup'))
                .map(g => ({ label: g.label, values: Array.from(g.children).map(o => o.value) }))""")
            by_label = {g["label"]: g["values"] for g in groups}
            for name, skin in K.SKINS.items():
                label = skin["title"]
                assert label in by_label, f"{name} is not offered: {list(by_label)}"
                assert set(by_label[label]) == {f"{name}:{v}" for v in skin["variants"]}
                assert by_label[label][0] == f"{name}:{skin['default']}", "the default variant leads"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_palette_set_elsewhere_repaints_this_page(fleet_home, tmp_path):
    """The reason this page carries a stream at all. `ad-theme set` in a terminal, or the desk in
    another window, writes the same `config.json`; without the frame this page would keep showing
    the palette it was opened with and its pickers would be quietly lying."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            assert page.evaluate("() => document.body.getAttribute('data-skin')") in (None, "")

            # somebody else's write, exactly as a terminal would make it
            (tmp_path / "cfg.json").write_text(
                json.dumps({"theme": {"default": "reds", "skin": "voxel:nether"}}), encoding="utf-8")

            page.wait_for_function(
                """() => document.body.getAttribute('data-skin') === 'voxel'""", timeout=15000)
            assert page.evaluate("() => document.getElementById('skin').value") == "voxel:nether"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------------------ the model


@pytest.mark.browser
def test_a_model_typed_here_reaches_the_command_line(fleet_home, tmp_path):
    """The whole point of the section: not that the box remembers a string, but that the string
    becomes `--model` on the argv the next turn is launched with."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C
    from agentdata.fleet import launch as L

    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_selector("#modelrows tr", timeout=10000)

            row = page.locator("#modelrows tr", has_text="alpha")
            row.locator("input").first.fill("claude-opus-5")
            row.locator("input").first.dispatch_event("change")
            page.wait_for_function(
                """() => document.querySelectorAll('#modelrows tr td:nth-child(4)')[0]
                          .textContent.indexOf('fleet.models') === 0""", timeout=10000)

            cfg = C.load()
            assert C.get_leaf(cfg, "fleet.models", "alpha", {}) == {"model": "claude-opus-5"}
            argv = L.launch_command("copilot", "/r", "p", log_dir="/l", cfg=cfg,
                                    **dict(zip(("model", "effort"), L.model_for("alpha", cfg)[:2])))
            assert "--model" in argv and argv[argv.index("--model") + 1] == "claude-opus-5"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_model_that_would_become_a_second_flag_is_refused_in_the_page(fleet_home, tmp_path):
    """`--model "x --allow-all-tools"` is the case. The allow-list check never sees it: it reads the
    tool lists, not this. So it is refused here, at the keystroke, and nothing is written."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C

    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_selector("#modelrows tr", timeout=10000)

            field = page.locator("#modelrows tr", has_text="alpha").locator("input").first
            field.fill("x --allow-all-tools")
            field.dispatch_event("change")
            page.wait_for_function(
                """() => document.querySelector('#modelrows input.bad') !== null""", timeout=10000)
            assert "more than one argument" in (field.get_attribute("title") or "")

            assert C.get_leaf(C.load(), "fleet.models", "alpha", {}) == {}, "it was written anyway"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------------- the stylesheet


# The one rule in the settings block that is deliberately global: it styles the control on the
# DESK's toolbar, which is the whole point of it.
GLOBAL_IN_SETTINGS_BLOCK = (".linkbtn",)


def test_the_settings_rules_cannot_restyle_the_desk():
    """Both pages share one stylesheet, so they share one namespace.

    Written after `.why` and `.scope` -- names the desk's tiles and its file-drop panel already own
    -- were added unscoped for the settings page and silently restyled the desk. A second stylesheet
    would have avoided it and cost a second place for the palette to drift; scoping costs one
    prefix, and this is what keeps it on.
    """
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    marker = "the settings page (/settings)"
    assert marker in css, "the settings block is not in the stylesheet"
    block = css[css.index(marker):]

    leaked = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith(("/*", "*", "//")) or "{" not in line:
            continue
        for selector in line.split("{")[0].split(","):
            selector = selector.strip()
            if not selector or selector.startswith("@"):
                continue
            if selector.startswith("body.settings-page") or selector in GLOBAL_IN_SETTINGS_BLOCK:
                continue
            if selector.startswith(GLOBAL_IN_SETTINGS_BLOCK):     # :hover, :focus-visible
                continue
            leaked.append(selector)
    assert leaked == [], f"these reach the desk too: {leaked}"


def test_the_desk_keeps_its_own_why_and_scope():
    """The two names that collided, asserted from the other side: the desk's rules are still there
    and still first, so a tile's explanation and the file-drop panel look as they did."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    settings_at = css.index("the settings page (/settings)")
    desk = css[:settings_at]
    assert ".why { margin: 6px 0 0; color: var(--muted); }" in desk
    assert ".scope {" in desk and "border: 1px dashed var(--focus)" in desk
