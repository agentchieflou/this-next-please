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
import time
import urllib.request

import pytest

from agentdata import textio
from agentdata.fleet import events as E, models as M, registry, serve as S, skins as K
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


def _seed_models(version="1.0.88", extra=()):
    """`<fleet_dir>/models.json` as `ad-fleet models --refresh` writes it (#360): the 1.0.88 ids
    plus `extra`, checked now. The page offers the measured list and no copilot is started."""
    shipped = M.shipped()
    os.makedirs(registry.fleet_dir(), exist_ok=True)
    textio.write_json(M.cache_file(), {
        "source": "help", "cli_version": version,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": shipped["models"] + list(extra), "efforts": shipped["efforts"], "why": ""})


def _posted(page):
    """Around a press on a model picker: wait for its `POST /api/settings` to be answered."""
    return page.expect_response(
        lambda r: r.request.method == "POST" and r.url.split("?")[0].endswith("/api/settings"),
        timeout=10000)


# What the keyboard is on in a model picker (#362): a model pill, an effort pill, or another pill.
_ON = """() => { const a = document.activeElement;
    return a.dataset.model !== undefined ? 'm:' + a.dataset.model
         : a.dataset.effort !== undefined ? 'e:' + a.dataset.effort : a.className; }"""


# ------------------------------------------------------------------------------------ the page


@pytest.mark.browser
def test_the_page_renders_every_section_and_can_get_back(fleet_home, tmp_path):
    """Every section, and the ways in and out.

    The model block is pressed, not typed (#367): the fleet-wide default is a picker beside its
    label, each repository's row is `#model-<repo>` with a picker of its own, and the line above
    the table says where the list came from -- the shipped one here, as no copilot was asked.
    `refresh the list` asks for it. The model card's link, `/settings#model-<repo>`, lands on that
    repository's row, a dotted name included: scrolled to, opened, and on its pressed pill."""
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

            # The model block: a picker for every agent, one per row, and no box to type into.
            block = page.evaluate("""() => {
                const d = document.querySelector('#fleetpicker .mpick[data-variant=full] button.pill[data-model=""]');
                return {
                    heads: Array.from(document.querySelectorAll('#modeltable th')).map(th => th.textContent),
                    rows: Array.from(document.querySelectorAll('#modelrows tr')).map(
                        tr => [tr.id, !!tr.querySelector('.mpick[data-variant=compact]')]),
                    fleet: d && [document.getElementById('fleetmodel-label').textContent,
                                 d.closest('[role=toolbar]').getAttribute('aria-label'),
                                 d.querySelector('.pill-label').textContent, d.title, d.getAttribute('aria-pressed')],
                    typed: document.getElementById('modeltable').closest('.setblock')
                        .querySelectorAll('input:not(.mp-other), datalist').length,
                    list: document.getElementById('modellist').textContent,
                    status: document.getElementById('saved').getAttribute('role') };
            }""")
            assert block == {
                "heads": ["repository", "model", "resolved from", "last turn actually used"],
                "rows": [["model-alpha", True], ["model-beta", True]],
                "fleet": ["every agent", "every agent", "CLI default", "pass no --model; the CLI chooses", "true"],
                "typed": 0, "list": "shipped list — copilot could not be asked", "status": "status"}, block

            # `refresh the list` asks the server to ask copilot, and says so. Answered here, so no
            # CLI is started on the machine running the suite.
            asked = []

            def ask(route):
                if route.request.method != "POST":
                    return route.continue_()
                asked.append(json.loads(route.request.post_data or "{}"))
                return route.fulfill(status=200, content_type="application/json",
                                     body='{"ok": true, "refreshing": true, "started": true}')

            page.route("**/api/models*", ask)
            page.click("#modelrefresh")
            page.wait_for_function("""() => !document.getElementById('saved').hidden
                && document.getElementById('saved').textContent.startsWith('asking copilot')""", timeout=10000)
            assert asked == [{"refresh": True}], asked
            page.unroute("**/api/models*")

            # The card's link, in a window short enough that the row starts off the glass.
            _repos(tmp_path, "rdsd.pbi")
            (tmp_path / "cfg.json").write_text(json.dumps(
                {"fleet": {"models": {"rdsd.pbi": {"model": "claude-opus-4.8"}}}}), encoding="utf-8")
            page.set_viewport_size({"width": 900, "height": 600})
            page.goto("about:blank")
            page.goto(f"http://127.0.0.1:{port}/settings?t={token}#model-rdsd.pbi",
                      wait_until="domcontentloaded")
            landed = page.wait_for_function("""() => {
                const tr = document.getElementById('model-rdsd.pbi'), a = document.activeElement;
                if (!tr || !a || !a.closest('.mp-expand') || !tr.contains(a)) return false;
                const r = tr.getBoundingClientRect(), b = a.getBoundingClientRect();
                return { on: a.dataset.model, pressed: a.getAttribute('aria-pressed'),
                         open: !tr.querySelector('.mp-expand').hidden, scrolled: window.scrollY > 0,
                         row: r.top < innerHeight && r.bottom > 0, pill: b.top >= 0 && b.bottom <= innerHeight };
            }""", timeout=10000).json_value()
            assert landed == {"on": "claude-opus-4.8", "pressed": "true", "open": True, "scrolled": True,
                              "row": True, "pill": True}, landed

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
    else, and full-height panels ate every click meant for what was under them.

    A row's expansion (#367) is the newest thing here that hides: closed, it takes no box. Open in a
    900x600 window, every pill in it is reachable -- by the arrows, each landing on the glass, and by
    the wheel, each at some point on the glass and the thing under the pointer."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")
    _seed_models()
    hidden_on_glass = """() => Array.from(document.querySelectorAll('[hidden]'))
        .filter(el => el.getBoundingClientRect().width > 0)
        .map(el => el.id || el.className)"""
    pills = "#model-alpha .mp-expand button.pill"
    key = """(b) => b.dataset.model !== undefined ? 'm:' + b.dataset.model
                  : b.dataset.effort !== undefined ? 'e:' + b.dataset.effort : b.className"""

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            shown = page.evaluate(hidden_on_glass)
            assert shown == [], f"hidden and still on the glass: {shown}"

            page.set_viewport_size({"width": 900, "height": 600})
            page.click("#model-alpha .mp-more")
            page.wait_for_function("(sel) => !!document.activeElement.closest(sel)",
                                   arg="#model-alpha .mp-expand", timeout=10000)
            every = page.eval_on_selector_all(pills, f"bs => bs.map({key})")
            assert len(every) > 30, every

            # The arrows: each toolbar from Home round to its first pill again, one Tab between.
            walked = []
            for bar, tab in (("mp-models", False), ("mp-effort", True)):
                if tab:
                    page.keyboard.press("Tab")
                page.keyboard.press("Home")
                for _ in range(page.eval_on_selector_all(f"#model-alpha .mp-expand .{bar} button.pill",
                                                         "bs => bs.length")):
                    walked.append(page.evaluate(f"""() => {{ const a = document.activeElement,
                        r = a.getBoundingClientRect(); return [a.closest('#model-alpha .mp-expand')
                        ? ({key})(a) : 'outside: ' + a.tagName,
                        r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth]; }}"""))
                    page.keyboard.press("ArrowRight")
            assert sorted(k for k, _ in walked) == sorted(every), walked
            assert [k for k, on in walked if not on] == [], "focused off the glass"

            # The wheel, from the top of the page to its foot.
            page.evaluate("() => { window.scrollTo(0, 0); window.__wheeled = new Set(); }")
            page.mouse.move(450, 300)
            for _ in range(80):
                seen, bottom = page.evaluate("""(sel) => {
                    for (const b of document.querySelectorAll(sel)) {
                        const r = b.getBoundingClientRect();
                        if (r.width === 0 || r.top < 0 || r.bottom > innerHeight) continue;
                        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                        if (hit && b.contains(hit)) window.__wheeled.add(b);
                    }
                    const s = document.scrollingElement;
                    return [window.__wheeled.size, Math.ceil(s.scrollTop + innerHeight) >= s.scrollHeight];
                }""", pills)
                if bottom:
                    break
                at = page.evaluate("() => document.scrollingElement.scrollTop")
                page.mouse.wheel(0, 240)
                page.wait_for_function("(at) => document.scrollingElement.scrollTop > at", arg=at, timeout=5000)
            assert bottom and seen == len(every), (seen, len(every))

            # Closed, it is hidden, and nothing hidden is on the glass.
            page.focus("#model-alpha .mp-expand button.pill")
            page.keyboard.press("Escape")
            assert page.evaluate("() => document.querySelector('#model-alpha .mp-expand').hidden") is True
            shown = page.evaluate(hidden_on_glass)
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
    the palette it was opened with and its pickers would be quietly lying.

    The model list is the same kind of fact (#367): `ad-fleet models --refresh` in a terminal
    rewrites `models.json`, the stream says so with a `models` frame, and the page asks for the list
    again and redraws its pills and the line saying where the list came from."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")
    _seed_models()

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

            # The stream has made passes by now, so the list it last looked at is the seeded one.
            page.wait_for_function("""() => document.getElementById('modellist').textContent
                .startsWith('list: copilot 1.0.88 · checked ')""", timeout=10000)
            assert page.evaluate("""() => document.querySelector(
                '#fleetpicker button.pill[data-model="byok-model-7"]')""") is None
            _seed_models("1.0.90", extra=("byok-model-7",))
            page.wait_for_function("""() => document.getElementById('modellist').textContent
                    .startsWith('list: copilot 1.0.90 · checked ')
                && !!document.querySelector('#fleetpicker button.pill[data-model="byok-model-7"]')
                && !!document.querySelector('#model-alpha button.pill[data-model=""]')""", timeout=15000)
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
    becomes `--model` on the argv the next turn is launched with.

    Typed in `other…`, the one place a name is still typed (#367): `more…` in the row, then
    `other…` in its expansion. First the two presses that need no name. A pill on the fleet-wide
    default is written to `fleet.model`, and a repository with no entry resolves it. `inherit` on a
    pinned model and effort removes the whole key, so the repository is back on that default, and
    the row is patched rather than rebuilt: the keyboard stays on the pill it pressed."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C
    from agentdata.fleet import launch as L

    _repos(tmp_path, "alpha", "beta")
    _seed_models()
    (tmp_path / "cfg.json").write_text(json.dumps(
        {"fleet": {"models": {"alpha": {"model": "claude-opus-5", "effort": "high"}}}}), encoding="utf-8")
    source = "(repo) => document.getElementById('model-' + repo).children[2].textContent"

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_selector("#modelrows tr", timeout=10000)

            # A pill on the fleet-wide default: `fleet.model`, and what beta, with no entry, runs.
            assert page.evaluate(source, "beta") == "cli-auto"
            with _posted(page):
                page.click("#fleetpicker .mp-models button.pill[data-model='claude-sonnet-5']")
            page.wait_for_function(f"() => ({source})('beta') === 'fleet.model'", timeout=10000)
            cfg = C.load()
            assert C.get(cfg, "fleet.model") == "claude-sonnet-5", cfg
            assert L.model_for("beta", cfg) == ("claude-sonnet-5", "", "fleet.model")

            # An effort on beta, which has no entry: the effort alone is written, and the model
            # keeps following the fleet's (#493, decision 15; it used to be pinned with it). The
            # row says where each half comes from.
            page.click("#model-beta .mp-more")
            with _posted(page):
                page.click("#model-beta .mp-expand .mp-effort button.pill[data-effort='high']")
            page.wait_for_function(f"""() => ({source})('beta') === 'fleet.model · effort from fleet.models.beta'
                && document.getElementById('saved').textContent === 'saved — takes effect on the next turn'""",
                                   timeout=10000)
            assert C.get_leaf(C.load(), "fleet.models", "beta", {}) == {"effort": "high"}
            assert L.model_for("beta", C.load()) == ("claude-sonnet-5", "high", "fleet.model")

            # `inherit` in alpha's row, which says what it inherits, pressed from the keyboard.
            inherit = "#model-alpha .mpick[data-variant=compact] button.pill[data-model='']"
            page.wait_for_function("(sel) => document.querySelector(sel + ' .pill-label').textContent"
                                   " === 'inherit · sonnet 5'", arg=inherit, timeout=10000)
            page.focus(inherit)
            page.evaluate("""() => { window.__pill = document.activeElement;
                                     window.__row = document.getElementById('model-alpha'); }""")
            with _posted(page):
                page.keyboard.press("Enter")
            # The model half alone (#493): alpha keeps its own effort, with the fleet's model.
            page.wait_for_function(f"() => ({source})('alpha') === 'fleet.model · effort from fleet.models.alpha'",
                                   timeout=10000)
            cfg = C.load()
            assert C.get_leaf(cfg, "fleet.models", "alpha", {}) == {"effort": "high"}, cfg
            assert L.model_for("alpha", cfg) == ("claude-sonnet-5", "high", "fleet.model")
            assert page.evaluate("""() => [document.activeElement === window.__pill,
                window.__pill.getAttribute('aria-pressed'),
                document.getElementById('model-alpha') === window.__row]""") == [True, "true", True]

            row = page.locator("#model-alpha")
            row.locator(".mp-more").click()
            row.locator(".mp-expand .mp-otherbtn").click()
            row.locator(".mp-expand input.mp-other").fill("claude-opus-5")
            row.locator(".mp-expand input.mp-other").press("Enter")
            page.wait_for_function(
                """() => document.querySelectorAll('#modelrows tr td:nth-child(3)')[0]
                          .textContent.indexOf('fleet.models') === 0""", timeout=10000)

            cfg = C.load()
            assert C.get_leaf(cfg, "fleet.models", "alpha", {}) == {"model": "claude-opus-5", "effort": "high"}
            argv = L.launch_command("copilot", "/r", "p", log_dir="/l", cfg=cfg,
                                    **dict(zip(("model", "effort"), L.model_for("alpha", cfg)[:2])))
            assert "--model" in argv and argv[argv.index("--model") + 1] == "claude-opus-5"

            # The fleet back to "CLI chooses": beta's effort pills are still pressable, and a press
            # writes the effort alone (#493). `inherit both` then clears beta's whole entry.
            with _posted(page):
                page.click("#fleetpicker .mp-models button.pill[data-model='']")
            page.wait_for_function(f"() => ({source})('beta').indexOf('cli-auto') === 0", timeout=10000)
            page.click("#model-beta .mp-more")
            low = "#model-beta .mp-expand .mp-effort button.pill[data-effort='low']"
            page.wait_for_selector(low, timeout=10000)
            assert page.get_attribute(low, "aria-disabled") is None
            with _posted(page):
                page.click(low)
            page.wait_for_function("() => document.getElementById('saved').textContent.indexOf('saved') === 0",
                                   timeout=10000)
            assert C.get_leaf(C.load(), "fleet.models", "beta", {}) == {"effort": "low"}
            assert L.model_for("beta", C.load()) == ("", "low", "cli-auto")
            with _posted(page):
                page.click("#model-beta .inherit-both")
            page.wait_for_function(f"() => ({source})('beta') === 'cli-auto'", timeout=10000)
            assert "beta" not in (C.get(C.load(), "fleet.models") or {})
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_model_that_would_become_a_second_flag_is_refused_in_the_page(fleet_home, tmp_path):
    """`--model "x --allow-all-tools"` is the case. The allow-list check never sees it: it reads the
    tool lists, not this. So it is refused here, at the keystroke, and nothing is written.

    Typed in the row's expansion (#367), and refused on its `other…` box. Then the same row by the
    keyboard alone: Escape closes the expansion onto `more…`, Enter opens it on its pressed pill,
    the arrows reach `claude-opus-5` and Enter presses it. That reaches the command line, the saved
    tag -- a live region -- says so, and the row is patched rather than rebuilt: the expansion
    closes and the keyboard lands on the row's pressed pill, which is the model just chosen."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C
    from agentdata.fleet import launch as L

    _repos(tmp_path, "alpha")
    _seed_models()

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _settings(p, port, token)
            page.wait_for_selector("#modelrows tr", timeout=10000)

            row = page.locator("#model-alpha")
            row.locator(".mp-more").click()
            row.locator(".mp-expand .mp-otherbtn").click()
            field = row.locator(".mp-expand .mp-other")
            field.fill("x --allow-all-tools")
            field.press("Enter")
            page.wait_for_function(
                """() => document.querySelector('#model-alpha .mp-expand .mp-other.bad') !== null""",
                timeout=10000)
            assert "more than one argument" in (field.get_attribute("title") or "")

            assert C.get_leaf(C.load(), "fleet.models", "alpha", {}) == {}, "it was written anyway"

            # The same row, by the keyboard alone.
            page.keyboard.press("Escape")
            assert page.evaluate("""() => [document.querySelector('#model-alpha .mp-expand').hidden,
                document.activeElement.classList.contains('mp-more'),
                document.activeElement.getAttribute('aria-expanded')]""") == [True, True, "false"]
            page.evaluate("() => { window.__row = document.getElementById('model-alpha'); }")
            page.keyboard.press("Enter")
            assert page.evaluate(_ON) == "m:", "it opens on the pressed pill, and alpha inherits"
            order = page.eval_on_selector_all("#model-alpha .mp-expand .mp-models button.pill",
                                              "bs => bs.map(b => b.dataset.model)")
            for _ in range(order.index("claude-opus-5")):
                page.keyboard.press("ArrowRight")
            assert page.evaluate(_ON) == "m:claude-opus-5"
            with _posted(page):
                page.keyboard.press("Enter")
            after = page.wait_for_function("""() => {
                const a = document.activeElement, s = document.querySelector('#saved[role=status]');
                return !!a.closest('#model-alpha .mpick[data-variant=compact]')
                    && a.dataset.model === 'claude-opus-5' && !!s && !s.hidden
                    && [a.getAttribute('aria-pressed'), s.textContent,
                        document.querySelector('#model-alpha .mp-expand').hidden,
                        document.querySelector('#model-alpha .mp-other').classList.contains('bad'),
                        document.getElementById('model-alpha') === window.__row];
            }""", timeout=10000).json_value()
            assert after == ["true", "saved — takes effect on the next turn", True, False, True], after
            cfg = C.load()
            assert C.get_leaf(cfg, "fleet.models", "alpha", {}) == {"model": "claude-opus-5"}
            argv = L.launch_command("copilot", "/r", "p", log_dir="/l", cfg=cfg,
                                    **dict(zip(("model", "effort"), L.model_for("alpha", cfg)[:2])))
            assert argv[argv.index("--model") + 1] == "claude-opus-5"
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
