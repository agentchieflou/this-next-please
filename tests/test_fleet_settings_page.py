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
import re
import threading
import urllib.request

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
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
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


def _looks_on(palette):
    """"Glass · Smoke" for each skin variant drawn on `palette`, in the order the skin picker lists
    them (#393): what /settings says is drawn on that palette, read from the data, not the page."""
    return [f"{k['title']} · {v['title']}" for k in K.list_skins() for v in k["variants"]
            if v["base"] == palette]


def _answered(page, body):
    """Around a pick: wait for the page's `POST /api/theme` with exactly `body` to be answered. Two
    picks' writes in flight at once may be applied in either order, so a test that reads what was
    saved serializes its picks on their answers."""
    def match(r):
        return (r.request.method == "POST" and r.url.split("?")[0].endswith("/api/theme")
                and json.loads(r.request.post_data or "{}") == body)
    return page.expect_response(match, timeout=10000)


_PICKERS = """() => {
    const t = document.getElementById('theme'), s = document.getElementById('skin');
    const line = document.getElementById('palette-looks');
    return { theme: t.value, skin: s.value, disabled: t.disabled, looks: line && line.textContent,
             bg: document.documentElement.style.getPropertyValue('--bg') };
}"""


def _settled(page, **want):
    """The pickers, the line under the palette and the painted ground, read at once when they are
    `want`. A `theme` frame the stream read just before the latest write can repaint the page until
    the frame that write woke (#348) puts it back, so this waits for the state, not one reading."""
    from playwright.sync_api import TimeoutError as Late

    try:
        return page.wait_for_function(
            "(want) => { const s = (" + _PICKERS + ")();"
            " return Object.keys(want).every(k => s[k] === want[k]) ? s : false; }",
            arg=want, timeout=10000).json_value()
    except Late:
        raise AssertionError(f"never {want}; the page reads {page.evaluate(_PICKERS)}") from None


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


def test_api_themes_says_which_palettes_no_look_is_drawn_on(fleet_home):
    """#393, without a page: `/api/themes` carries `palette_only` beside what it always carried, and
    every palette it offers is either drawn by a variant it lists or in `palette_only` with a reason
    -- the page's one source for saying which, and never both."""
    server, token, port = _serve()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/themes?t={token}", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert {"themes", "skins", "current", "palette_only"} <= set(data), sorted(data)
    assert data["palette_only"] == K.PALETTE_ONLY
    drawn = {v["base"] for k in data["skins"] for v in k["variants"]}
    for t in data["themes"]:
        listed = t["name"] in data["palette_only"]
        assert (t["name"] in drawn) != listed, t["name"]
        assert not listed or data["palette_only"][t["name"]].strip(), t["name"]


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
                const looks = document.getElementById('palette-looks');
                return { palette: t.value, paletteOff: t.disabled, paletteWhy: t.title,
                         skin: s.value, blank: t.selectedIndex < 0 || s.selectedIndex < 0,
                         painted: document.body.getAttribute('data-skin'),
                         looks: looks && looks.textContent };
            }""")
            assert state["skin"] == "glass:smoke", state
            assert state["palette"] == "dark", state
            assert not state["blank"], "a picker showing nothing at all is the one thing it may not do"
            assert state["paletteOff"] and "comes from the skin" in state["paletteWhy"], state
            # ...and the line under it, which a disabled control's tooltip cannot be, names the
            # look the palette comes from (#393).
            glass = K.SKINS["glass"]
            assert state["looks"] == f"from {glass['title']} · {glass['variants']['smoke']['title']}", state
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
    says why it is not taking instructions -- rather than accepting a choice the server overrides.

    With no skin on, every palette is offered by its title and says what is drawn on it (#393). A
    palette no look is drawn on is an ordinary choice, the plain page, and the line under the picker
    says so: Browns looked gone because nothing on the page said it was there."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C

    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            assert page.evaluate("() => document.getElementById('theme').disabled") is False

            # Each palette by its title, never its slug; the slug stays the value, and the tooltip
            # (a supplement: it is hover-only) says what is drawn on it.
            palettes = {t["name"]: t for t in S.themes()}
            offered = page.eval_on_selector_all(
                "#theme option", "os => os.slice(1).map(o => [o.value, o.textContent, o.title])")
            assert [o[:2] for o in offered] == [[n, t["title"]] for n, t in palettes.items()], offered
            for name, _, tip in offered:
                looks = _looks_on(name)
                said = f"drawn by {', '.join(looks)}" if looks else f"palette only: {K.PALETTE_ONLY[name]}"
                assert tip == f"{palettes[name]['why']}  ·  {said}", tip

            with _answered(page, {"skin": "voxel:nether"}):
                page.select_option("#skin", "voxel:nether")
                page.wait_for_function(
                    """() => document.getElementById('theme').disabled === true""", timeout=10000)
                picker = page.evaluate("""() => {
                    const t = document.getElementById('theme'), s = document.getElementById('skin');
                    return { theme: t.value, title: t.title, skin: s.value,
                             looks: document.getElementById('palette-looks').textContent };
                }""")
            assert picker["theme"] == "reds", "it shows the ground the skin brought"
            assert "comes from the skin" in picker["title"]
            assert picker["skin"] == "voxel:nether", "and the skin picker sits on the variant"
            voxel = K.SKINS["voxel"]
            nether = f"{voxel['title']} · {voxel['variants']['nether']['title']}"
            assert picker["looks"] == f"from {nether}", "the line names the look the palette is from"

            with _answered(page, {"skin": "none"}):
                page.select_option("#skin", "none")
                page.wait_for_function(
                    """() => document.getElementById('theme').disabled === false""", timeout=10000)
            _settled(page, theme="reds", skin="none", disabled=False,
                     looks=f"drawn by {', '.join(_looks_on('reds'))}")

            # A palette no look is drawn on is chosen like any other: posted, saved, worn, and said.
            for name, reason in K.PALETTE_ONLY.items():
                with _answered(page, {"theme": name}):
                    page.select_option("#theme", name)
                assert C.load()["theme"]["default"] == name, "the saved config names that palette"
                said = _settled(page, theme=name, skin="none", disabled=False,
                                bg=palettes[name]["css"]["--bg"],
                                looks=f"palette only: the plain page — {reason}")
                assert "palette only" in said["looks"], said

            # A palette with looks names every one of them.
            with _answered(page, {"theme": "dark"}):
                page.select_option("#theme", "dark")
            said = _settled(page, theme="dark", disabled=False,
                            looks=f"drawn by {', '.join(_looks_on('dark'))}")
            assert "Glass · Smoke" in said["looks"], said
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
            # A skin with one variant is one option, not a group of one (settings.js); the legal
            # pad (#251) is the first.
            singles = page.evaluate("""() => Array.from(document.querySelectorAll('#skin > option'))
                .map(o => [o.textContent, o.value])""")
            for name, skin in K.SKINS.items():
                label = skin["title"]
                if len(skin["variants"]) == 1:
                    assert [label, f"{name}:{skin['default']}"] in singles, f"{name}: {singles}"
                    assert label not in by_label, f"{name} is a group of one"
                    continue
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


def test_the_desk_layout_cannot_reach_the_settings_page():
    """The desk and the settings page share app.css. Bare element selectors in the desk portion
    must not set layout properties that clamp or clip pages that also use those elements (like main)."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    marker = "the settings page (/settings)"
    assert marker in css
    desk_css = css[:css.index(marker)]
    desk_clean = re.sub(r"/\*.*?\*/", "", desk_css, flags=re.DOTALL)
    matches = re.findall(r"([^{}]+)\{([^{}]+)\}", desk_clean)
    forbidden_tags = {"main", "section", "table", "h2"}
    layout_props = {"overflow", "overflow-x", "overflow-y", "height", "min-height", "flex", "display"}

    leaked = []
    for sel_group, body in matches:
        props = {item.split(":")[0].strip() for item in body.split(";") if ":" in item}
        if props & layout_props:
            for sel in sel_group.split(","):
                sel = sel.strip()
                m = re.match(r"^([a-zA-Z0-9_-]+)(?::[a-zA-Z0-9_-]+)?$", sel)
                if m and m.group(1) in forbidden_tags:
                    leaked.append((sel, sorted(props & layout_props)))
    assert leaked == [], f"these bare tags set layout and reach /settings: {leaked}"


def test_the_desk_keeps_its_own_why_and_scope():
    """The two names that collided, asserted from the other side: the desk's rules are still there
    and still first, so a tile's explanation and the file-drop panel look as they did."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    settings_at = css.index("the settings page (/settings)")
    desk = css[:settings_at]
    assert ".why { margin: 6px 0 0; color: var(--muted); }" in desk
    assert ".scope {" in desk and "border: 1px dashed var(--focus)" in desk
