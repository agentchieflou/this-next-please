"""The model picker (#362): one component, provider-grouped pills pressed and never typed,
keyboard-first, drawn only with theme tokens, and silent when idle.

`static/picker.js` is built on /settings from an in-test catalogue: the 1.0.88 ids `models.catalogue`
answers before the CLI has been asked, with one id not offered, one the account cannot use, one that
takes two efforts, and premium multipliers. No host wires it yet (#366-#368), so each test mounts it
in a `.setblock`, the card /settings will host it in, and drives it with the keyboard.

Every palette and every look is worn in ONE page: `post('theme', …)`, then a wait until the page
wears it. No flat waits. One Chromium for the module, a context per test, a server per test.
"""
from __future__ import annotations

import contextlib
import gzip
import os
import re
import threading

import pytest

from agentdata import theme as T
from agentdata.fleet import models as M, registry, serve as S, skins as K

from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")

CURRENT = "claude-opus-5"          # the acceptance criteria's current model, with `xhigh`
SMALL = "gpt-5-mini"               # given `efforts: ["low", "medium"]` below
INHERITED = "claude-sonnet-5"      # what a repository inherits, in the criteria
UNAVAILABLE = "gemini-3.5-flash"   # `available: false`
UNOFFERED = "kimi-k2.7-code"       # `offered: false`
WHY = "your organisation has not enabled this model"
MARKER = "the settings page (/settings)"
FULL = ".mpick[data-variant=full]"
COMPACT = ".mpick[data-variant=compact]"


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


def _catalogue() -> dict:
    """`/api/models` as it answers before the CLI is asked (the fleet directory has no cache), with
    the marks a picker has to show put on real 1.0.88 ids."""
    cat = M.catalogue({}, spawn=False)
    assert cat["meta"]["source"] == "shipped" and cat["meta"]["cli_version"] == "1.0.88", cat["meta"]
    by = {m["id"]: m for m in cat["models"]}
    for need in ("", CURRENT, SMALL, INHERITED, UNAVAILABLE, UNOFFERED):
        assert need in by, need
    by[UNOFFERED]["offered"] = False
    by[UNAVAILABLE].update(available=False, why_unavailable=WHY)
    by[SMALL].update(efforts=["low", "medium"], multiplier=0.33)
    by[CURRENT]["multiplier"] = 3
    return cat


# A `.setblock` at the top of /settings holding a focusable button, a full picker and a compact one.
# Every key that reaches `document` is recorded, and so is every pick and every `more…`.
MOUNT = """(cat) => {
  window.__cat = cat; window.__picks = []; window.__more = []; window.__doc = [];
  document.addEventListener('keydown', (e) => window.__doc.push(e.key));
  const host = document.createElement('section');
  host.className = 'setblock';
  host.id = 'mphost';
  const before = document.createElement('button');
  before.id = 'mpbefore';
  before.textContent = 'before';
  const opts = (variant) => ({ variant, label: 'every agent', emptyLabel: 'CLI default',
    emptyTitle: 'the CLI chooses', onPick: (p) => window.__picks.push(p),
    onMore: (a) => window.__more.push(a.className) });
  window.__full = createModelPicker(opts('full'));
  window.__compact = createModelPicker(opts('compact'));
  host.append(before, window.__full, window.__compact);
  document.querySelector('main.settings').prepend(host);
}"""

DRAW = """([which, state]) => drawModelPicker(window[which], Object.assign({ catalogue: window.__cat }, state))"""

# Draws a state, then draws an equal copy of it under a MutationObserver: the records it took.
EQUAL_AGAIN = """([which, state]) => {
  const s = Object.assign({ catalogue: window.__cat }, state);
  drawModelPicker(window[which], s);
  const mo = new MutationObserver(() => {});
  mo.observe(window[which], { subtree: true, childList: true, attributes: true, characterData: true });
  drawModelPicker(window[which], JSON.parse(JSON.stringify(s)));
  const n = mo.takeRecords().length;
  mo.disconnect();
  return n;
}"""

# What the keyboard is on: the pill's model or effort, or the element's class.
FOCUS = """() => { const a = document.activeElement;
  return a.dataset.model !== undefined ? 'm:' + a.dataset.model
       : a.dataset.effort !== undefined ? 'e:' + a.dataset.effort : a.className || a.id; }"""

# Colours as the page computes them, read through a 1px canvas so any CSS colour syntax comes back
# as [r, g, b, a]. A ground is the first opaque background at or behind an element, with every
# translucent one on the way laid over it, as the browser composites.
COLOURS = """(sel) => {
  const g = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const rgba = (css) => { g.clearRect(0, 0, 1, 1); g.fillStyle = css; g.fillRect(0, 0, 1, 1);
    const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const ground = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) layers.push(b);
      if (b[3] >= 1) break;
    }
    let out = [255, 255, 255];
    if (layers.length && layers[layers.length - 1][3] >= 1) out = layers.pop().slice(0, 3);
    for (const l of layers.reverse()) out = out.map((v, i) => l[i] * l[3] + v * (1 - l[3]));
    return out.map(Math.round);
  };
  const ink = (el) => rgba(getComputedStyle(el).color).slice(0, 3);
  const part = (el) => ({ color: ink(el), ground: ground(el) });
  const pill = (b) => ({
    label: part(b.querySelector('.pill-label')), note: part(b.querySelector('.pill-note')),
    mark: Object.assign(part(b.querySelector('.pill-mark')), {
      text: b.querySelector('.pill-mark').textContent,
      shown: b.querySelector('.pill-mark').checkVisibility({ opacityProperty: true, visibilityProperty: true })
             && b.querySelector('.pill-mark').getBoundingClientRect().width > 0 }),
    fill: rgba(getComputedStyle(b).backgroundColor), ring: rgba(getComputedStyle(b).borderTopColor).slice(0, 3),
    ringWidth: getComputedStyle(b).borderTopWidth, around: ground(b.parentElement) });
  const root = document.querySelector('#mphost .mpick');
  return {
    pressed: pill(root.querySelector('.mp-models button.pill[aria-pressed="true"]')),
    plain: pill(root.querySelector('.mp-models button.pill[data-model="' + sel.plain + '"]')),
    glabel: part(root.querySelector('.mp-glabel')),
    inkOff: document.body.classList.contains('ink-off'),
  };
}"""


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _ratio(a, b) -> float:
    return T.contrast_ratio(_hex(a), _hex(b))


def _serve():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


@contextlib.contextmanager
def _settings(browser, *, width=1400):
    """/settings with the two pickers mounted, in a context of its own, on a server of its own."""
    server, token, port = _serve()
    context = browser.new_context(viewport={"width": width, "height": 900}, reduced_motion="no-preference")
    try:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
        page.evaluate(MOUNT, _catalogue())
        yield page
        assert errors == [], errors
    finally:
        context.close()
        _stop(server)


def _draw(page, state, which="__full"):
    page.evaluate(DRAW, [which, state])


def _press(page, key, times=1):
    for _ in range(times):
        page.keyboard.press(key)


# ---------------------------------------------------------------------------- the browser
#
# Four tests, not one per criterion: the slow tiers are held under a tenth of the suite
# (`test_the_expensive_tiers_are_a_small_part_of_the_suite`), and a context and a server per
# criterion would be most of this module's time.


@pytest.mark.browser
def test_the_keyboard_walks_one_stop_per_toolbar_and_picks_once(browser, fleet_home):
    """Groups in catalogue order with their titles; one tab stop per toolbar; the arrows, Home and
    End move the focus across groups; Enter and Space pick once each; no key the picker consumes
    reaches `document`, and Escape, which it does not consume, does. `other…` is the toolbar's last
    pill and reveals an input outside every toolbar, where ArrowLeft moves the caret and not the
    focus and Enter picks the id typed. The compact picker is one stop too, and `more…` calls
    `onMore` with itself as the anchor."""
    cat = _catalogue()
    with _settings(browser) as page:
        _draw(page, {"current": {"model": CURRENT, "effort": "xhigh"}})
        _draw(page, {"current": {"model": "", "effort": ""}, "quick": [SMALL]}, which="__compact")
        groups = page.evaluate("""() => Array.from(window.__full.querySelectorAll('.mp-group')).map(g => ({
            title: g.querySelector('.mp-glabel').textContent,
            labelled: document.getElementById(g.getAttribute('aria-labelledby')) === g.querySelector('.mp-glabel'),
            role: g.getAttribute('role'),
            pills: Array.from(g.querySelectorAll('button.pill')).map(b => b.dataset.model) }))""")
        want = [{"title": g["title"], "labelled": True, "role": "group",
                 "pills": [m["id"] for m in cat["models"] if m["group"] == g["key"]]}
                for g in cat["groups"] if any(m["group"] == g["key"] for m in cat["models"])]
        assert groups == want
        bars = page.evaluate("""() => Array.from(document.querySelectorAll('#mphost [role=toolbar]')).map(t => ({
            label: t.getAttribute('aria-label'), last: t.lastElementChild.className,
            stops: Array.from(t.querySelectorAll('button.pill')).filter(b => b.tabIndex === 0)
                        .map(b => b.dataset.model !== undefined ? 'm:' + b.dataset.model : 'e:' + b.dataset.effort) }))""")
        assert bars == [{"label": "every agent", "last": "pill mp-otherbtn", "stops": [f"m:{CURRENT}"]},
                        {"label": "every agent: effort", "last": "pill", "stops": ["e:xhigh"]},
                        {"label": "every agent", "last": "pill mp-more", "stops": ["m:"]}], bars

        # Tab: into each toolbar at its pressed pill, and out of it in one press.
        page.focus("#mpbefore")
        for stop in (f"m:{CURRENT}", "e:xhigh", "m:"):
            _press(page, "Tab")
            assert page.evaluate(FOCUS) == stop
        _press(page, "End")
        _press(page, "Enter")
        assert page.evaluate("() => [window.__more, window.__picks]") == [["pill mp-more"], []]
        _press(page, "Shift+Tab")
        _press(page, "Shift+Tab")
        assert page.evaluate(FOCUS) == f"m:{CURRENT}"

        order = [p for g in want for p in g["pills"]]
        _press(page, "Home")
        assert page.evaluate(FOCUS) == "m:"
        _press(page, "End")
        assert page.evaluate(FOCUS) == "pill mp-otherbtn"
        _press(page, "ArrowRight")
        assert page.evaluate(FOCUS) == "m:", "the arrows go round"
        _press(page, "ArrowLeft")
        assert page.evaluate(FOCUS) == "pill mp-otherbtn"
        # Across a group's edge: the first group's last pill, then the second group's first.
        _press(page, "Home")
        _press(page, "ArrowRight", len(want[0]["pills"]) - 1)
        assert page.evaluate(FOCUS) == "m:" + want[0]["pills"][-1]
        _press(page, "ArrowDown")
        assert page.evaluate(FOCUS) == "m:" + want[1]["pills"][0]
        _press(page, "ArrowUp")
        assert page.evaluate(FOCUS) == "m:" + want[0]["pills"][-1]
        # The stop follows the keyboard, so Tab still leaves the toolbar in one press.
        assert page.evaluate(f"() => document.querySelectorAll('{FULL} .mp-models button.pill[tabindex=\"0\"]').length") == 1

        # Enter picks once, Space picks once.
        _press(page, "Home")
        _press(page, "ArrowRight", order.index(INHERITED))
        assert page.evaluate(FOCUS) == f"m:{INHERITED}"
        _press(page, "Enter")
        assert page.evaluate("() => window.__picks") == [
            {"model": INHERITED, "effort": "xhigh", "toolbar": "model", "droppedEffort": ""}]
        _press(page, " ")
        assert len(page.evaluate("() => window.__picks.splice(0)")) == 2
        consumed = {"Home", "End", "ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Enter", " "}
        heard = page.evaluate("() => window.__doc.splice(0)")
        assert not consumed & set(heard), heard
        _press(page, "Escape")
        assert page.evaluate("() => window.__doc.splice(0)") == ["Escape"], "Escape is the host's"

        # `other…`: an input after the model toolbar, outside every toolbar.
        other = page.evaluate("""() => { const i = window.__full.querySelector('input.mp-other');
            return { hidden: i.hidden, label: i.getAttribute('aria-label'), bar: !!i.closest('[role=toolbar]'),
                     after: i.previousElementSibling.className }; }""")
        assert other == {"hidden": True, "label": "another model id", "bar": False, "after": "mp-models"}
        _press(page, "End")
        _press(page, "Enter")
        assert page.evaluate(FOCUS) == "mp-other"
        assert page.evaluate("() => window.__full.querySelector('.mp-otherbtn').getAttribute('aria-expanded')") == "true"
        page.keyboard.type("byok-model-7")
        _press(page, "ArrowLeft", 2)
        caret = page.evaluate("() => [document.activeElement.className, document.activeElement.selectionStart]")
        assert caret == ["mp-other", len("byok-model-7") - 2], caret
        _press(page, "Enter")
        assert page.evaluate("() => window.__picks") == [
            {"model": "byok-model-7", "effort": "xhigh", "toolbar": "model", "droppedEffort": ""}]
        assert "Enter" not in page.evaluate("() => window.__doc")
        # A redraw keeps what the operator opened, and an id the catalogue lacks is still shown.
        _draw(page, {"current": {"model": "byok-model-7", "effort": "xhigh"}})
        assert page.evaluate("() => window.__full.querySelector('input.mp-other').hidden") is False
        assert page.evaluate("() => window.__full.querySelector('button.pill[aria-pressed=\"true\"]').dataset.model") \
            == "byok-model-7"


@pytest.mark.browser
def test_every_state_says_what_it_is_and_reports_what_was_pressed(browser, fleet_home):
    """An `available:false` pill is focusable, its `aria-describedby` resolves to the reason, and it
    is never picked. `~default` reports `{model: "", effort: ""}`. Inheriting with
    `inherited.model = ""` every effort pill is `aria-disabled` and `.mp-effort-why` is on the page;
    inheriting a model, they are live. From `{claude-opus-5, xhigh}` a model taking only low and
    medium reports `effort: ""`, `droppedEffort: "xhigh"`. The compact picker offers the pressed
    pill, the default, two quick ids and `more…`, and wraps in a narrow card."""
    effort_state = """() => ({
        disabled: Array.from(window.__full.querySelectorAll('.mp-effort button.pill')).map(b => b.getAttribute('aria-disabled')),
        pressed: Array.from(window.__full.querySelectorAll('.mp-effort button.pill[aria-pressed="true"]')).map(b => b.dataset.effort),
        described: Array.from(window.__full.querySelectorAll('.mp-effort button.pill')).every(
            b => !b.hasAttribute('aria-describedby') || document.getElementById(b.getAttribute('aria-describedby')) === window.__full.querySelector('.mp-effort-why')),
        why: window.__full.querySelector('.mp-effort-why').checkVisibility() ? window.__full.querySelector('.mp-effort-why').textContent : null,
        model: window.__full.querySelector('.mp-models button.pill[aria-pressed="true"]').dataset.model })"""
    with _settings(browser, width=900) as page:
        _draw(page, {"current": {"model": CURRENT, "effort": ""}})
        got = page.evaluate("""(id) => { const b = window.__full.querySelector('button.pill[data-model="' + id + '"]');
            const why = document.getElementById(b.getAttribute('aria-describedby'));
            return { disabled: b.getAttribute('aria-disabled'), mark: b.querySelector('.pill-mark').textContent,
                     why: why && why.textContent, sr: why && why.classList.contains('sr'), inside: why && b.contains(why),
                     edge: getComputedStyle(b).borderTopStyle, tabindex: b.tabIndex }; }""", UNAVAILABLE)
        assert got == {"disabled": "true", "mark": "⊘", "why": WHY, "sr": True, "inside": True,
                       "edge": "dashed", "tabindex": -1}, got
        page.focus(f"{FULL} .mp-models button.pill[data-model='{UNAVAILABLE}']")
        assert page.evaluate(FOCUS) == f"m:{UNAVAILABLE}", "it can be reached"
        _press(page, "Enter")
        _press(page, " ")
        # `force`: Playwright waits for an `aria-disabled` control to be enabled, which is the point.
        page.click(f"{FULL} .mp-models button.pill[data-model='{UNAVAILABLE}']", force=True)
        assert page.evaluate("() => window.__picks") == [], "and never picked"
        # Its neighbours say what they are too: the one not offered, the multiplier, the last turn's.
        marks = page.evaluate("""(ids) => ids.map(id => { const b = window.__full.querySelector('button.pill[data-model="' + id + '"]');
            return [b.querySelector('.pill-mark').textContent, b.querySelector('.pill-note').textContent,
                    b.querySelector('.pill-sr').textContent.trim(), b.title]; })""", [UNOFFERED, SMALL])
        assert marks == [["⚠", "", "(not offered by this CLI)", "not offered by copilot 1.0.88"],
                         ["", "×0.33", "", SMALL]], marks
        _draw(page, {"current": {"model": CURRENT, "effort": "xhigh"}, "actual": CURRENT})
        pressed = page.evaluate("""() => { const b = window.__full.querySelector('button.pill[aria-pressed="true"]');
            return [b.dataset.model, b.querySelector('.pill-mark').textContent, b.querySelector('.pill-note').textContent,
                    b.querySelector('.pill-sr').textContent.trim(), getComputedStyle(b).borderTopWidth]; }""")
        assert pressed == [CURRENT, "✓•", "×3", "(the last turn ran on this)", "2px"], pressed

        # The effort a picked model does not take is dropped, and named.
        efforts = page.evaluate("() => Array.from(window.__full.querySelectorAll('.mp-effort button.pill')).map(b => b.dataset.effort)")
        assert efforts == [""] + _catalogue()["efforts"], "a model with no levels of its own gets the catalogue's"
        page.click(f"{FULL} .mp-models button.pill[data-model='{SMALL}']")
        page.click(f"{FULL} .mp-models button.pill[data-model='{INHERITED}']")
        page.click(f"{FULL} .mp-effort button.pill[data-effort='max']")
        page.click(f"{FULL} .mp-models button.pill[data-model='']")
        assert page.evaluate("() => window.__picks.splice(0)") == [
            {"model": SMALL, "effort": "", "toolbar": "model", "droppedEffort": "xhigh"},
            {"model": INHERITED, "effort": "xhigh", "toolbar": "model", "droppedEffort": ""},
            {"model": CURRENT, "effort": "max", "toolbar": "effort", "droppedEffort": ""},
            {"model": "", "effort": "", "toolbar": "model", "droppedEffort": ""}]
        assert page.evaluate("""() => { const b = window.__full.querySelector('.mp-models button.pill[data-model=""]');
            return [b.dataset.rowkey, b.querySelector('.pill-label').textContent, b.title]; }""") \
            == ["~default", "CLI default", "the CLI chooses"]
        _draw(page, {"current": {"model": SMALL, "effort": ""}})
        efforts = page.evaluate("() => Array.from(window.__full.querySelectorAll('.mp-effort button.pill')).map(b => b.dataset.effort + '|' + b.textContent)")
        assert efforts == ["|✓default", "low|low", "medium|medium"], efforts

        # Inheriting nothing pins no effort; inheriting a model, the efforts are live.
        _draw(page, {"current": {"model": "", "effort": ""},
                     "inherited": {"model": "", "effort": "", "source": "fleet"}})
        off = page.evaluate(effort_state)
        assert set(off["disabled"]) == {"true"} and off["pressed"] == [""] and off["described"], off
        assert off["why"] == "effort follows the inherited model; press a model to set one", off
        assert off["model"] == ""
        page.click(f"{FULL} .mp-effort button.pill[data-effort='high']", force=True)
        assert page.evaluate("() => window.__picks") == [], "a disabled effort is not picked"
        _draw(page, {"current": {"model": "", "effort": ""},
                     "inherited": {"model": INHERITED, "effort": "high", "source": "fleet"}})
        live = page.evaluate(effort_state)
        assert set(live["disabled"]) == {None} and live["pressed"] == ["high"] and live["why"] is None, live
        page.click(f"{FULL} .mp-effort button.pill[data-effort='low']")
        assert page.evaluate("() => window.__picks.splice(0)") == [
            {"model": "", "effort": "low", "toolbar": "effort", "droppedEffort": ""}]

        # Compact, in a card 220px wide.
        page.evaluate("() => { document.getElementById('mphost').style.width = '220px'; }")
        _draw(page, {"current": {"model": CURRENT, "effort": "high"},
                     "quick": [CURRENT, "", SMALL, "gpt-5.6-terra", INHERITED]}, which="__compact")
        got = page.evaluate("""() => { const c = window.__compact, bar = c.querySelector('.mp-models');
            const cs = (el) => getComputedStyle(el);
            return { keys: Array.from(bar.querySelectorAll('button.pill')).map(b => b.dataset.rowkey),
                     titles: Array.from(bar.querySelectorAll('button.pill[data-model]')).map(b => b.title),
                     effort: !!c.querySelector('.mp-effort'), other: !!c.querySelector('.mp-other'),
                     rows: new Set(Array.from(bar.children).map(b => Math.round(b.getBoundingClientRect().top))).size,
                     fits: bar.scrollWidth <= bar.clientWidth,
                     ellipsis: cs(bar.querySelector('.pill-label')).textOverflow,
                     minWidth: cs(bar.querySelector('button.pill')).minWidth }; }""")
        assert got["keys"] == [CURRENT, "~default", SMALL, "gpt-5.6-terra", "~more"], got
        assert got["titles"] == [CURRENT, "the CLI chooses", SMALL, "gpt-5.6-terra"], got
        assert not got["effort"] and not got["other"], got
        assert got["rows"] > 1 and got["fits"], "it wraps inside a narrow card"
        assert got["ellipsis"] == "ellipsis" and got["minWidth"] == "0px", got
        page.click(f"{COMPACT} button.pill[data-model='']")
        assert page.evaluate("() => window.__picks") == [
            {"model": "", "effort": "", "toolbar": "model", "droppedEffort": ""}]


@pytest.mark.browser
def test_an_equal_draw_ink_off_and_reduced_motion_change_nothing(browser, fleet_home):
    """Two equal draws make 0 `MutationObserver` records, in every state. Under `body.ink-off` the
    picker is the same DOM with the same marks, and the same keys walk it. A pill fades for
    `--motion-fast`, and under reduced motion its `transition-duration` is at most 0.00001s."""
    states = [
        ("__full", {"current": {"model": CURRENT, "effort": "xhigh"}, "actual": SMALL}),
        ("__full", {"current": {"model": "", "effort": ""},
                    "inherited": {"model": "", "effort": "", "source": "fleet"}}),
        ("__full", {"current": {"model": "", "effort": ""},
                    "inherited": {"model": INHERITED, "effort": "high", "source": "fleet"}}),
        ("__full", {"current": {"model": "byok-model-7", "effort": "low"}}),
        ("__compact", {"current": {"model": CURRENT, "effort": ""}, "quick": [SMALL, INHERITED]}),
        ("__compact", {"current": {"model": "", "effort": ""}, "quick": [UNAVAILABLE]}),
    ]
    fade = """() => { const cs = getComputedStyle(window.__full.querySelector('button.pill'));
        return [cs.transitionProperty, cs.transitionDuration]; }"""
    with _settings(browser) as page:
        for which, state in states:
            assert page.evaluate(EQUAL_AGAIN, [which, state]) == 0, (which, state)
        which, state = states[0]
        _draw(page, state)
        on = page.evaluate("() => [document.body.classList.contains('ink-off'), window.__full.outerHTML]")
        page.evaluate("() => document.body.classList.add('ink-off')")
        assert page.evaluate(EQUAL_AGAIN, [which, state]) == 0
        off = page.evaluate("() => window.__full.outerHTML")
        assert on == [False, off], "ink-off changes nothing in the picker"
        page.focus(f"{FULL} .mp-models button.pill[tabindex='0']")
        _press(page, "ArrowRight")
        assert page.evaluate(FOCUS) != f"m:{CURRENT}"
        _press(page, "Home")
        assert page.evaluate(FOCUS) == "m:"

        assert page.evaluate(fade) == ["background-color", "0.12s"]
        page.emulate_media(reduced_motion="reduce")
        _prop, still = page.evaluate(fade)
        stills = [float(v.strip().rstrip("s")) for v in still.split(",")]
        assert max(stills) <= 0.00001, still


# ------------------------------------------------------------------------- the contrast


def _wear(page, body, until, arg):
    """Post a theme and wait until the page wears it, and until the pills' own fade (the 120ms
    `background-color` transition runs on a palette change too) has landed on the new colours."""
    page.evaluate("(b) => post('theme', b)", body)
    page.wait_for_function(until, arg=arg, timeout=15000)
    page.wait_for_function(SETTLED, timeout=15000)


SETTLED = """() => document.getElementById('mphost').getAnimations({ subtree: true })
    .every(a => !(a instanceof CSSTransition))"""

PALETTE_WORN = """(want) => { const s = getComputedStyle(document.documentElement);
    return !document.body.dataset.skin && Object.keys(want).every(
        k => s.getPropertyValue(k).trim().toLowerCase() === want[k].toLowerCase()); }"""

LOOK_WORN = """([skin, variant]) => { const b = document.body, link = document.querySelector('link[data-skin]');
    return b.dataset.skin === skin && (b.dataset.skinVariant || '') === variant
        && !!link && !!link.sheet && link.sheet.href === link.href; }"""


@pytest.mark.browser
def test_every_palette_and_every_look_reads_at_its_contrast(browser, fleet_home):
    """Every palette but `none`: the pressed pill's text at 4.5:1 on its fill, `.pill-note` at 4.5:1
    on `--panel` and on `--select`, `.mp-glabel` at 4.5:1 on its ground, and the ring at 3:1 against
    the card around the pill, which is `--panel` (not the pill's fill: 2.84 in sand).

    Then every skin variant, as /settings wears it and again under `body.ink-off`: the ✓ is on the
    page, and the pills' words and the group's title read at 4.5:1 against the first opaque
    background at or behind them. The ring's contrast is printed, not asserted: a pixel test (#341)
    is what can say what a ring is drawn against. All of it in one page."""
    palettes = [t for t in T.list_themes() if t.name != "none"]
    looks = [(skin, variant) for skin, variant, _spec in K.every_variant()]
    worn, seen = {}, {}
    with _settings(browser) as page:
        _draw(page, {"current": {"model": CURRENT, "effort": ""}})
        for t in palettes:
            css = T.to_css(t)
            want = {k: css[k] for k in ("--bg", "--text", "--panel", "--select", "--accent")}
            _wear(page, {"theme": t.name, "skin": "none"}, PALETTE_WORN, want)
            worn[t.name] = (css, page.evaluate(COLOURS, {"plain": SMALL}))
        for skin, variant in looks:
            _wear(page, {"skin": f"{skin}:{variant}"}, LOOK_WORN, [skin, variant])
            first = page.evaluate(COLOURS, {"plain": SMALL})
            page.evaluate("() => document.body.classList.toggle('ink-off')")
            toggled = page.evaluate(COLOURS, {"plain": SMALL})
            page.evaluate("() => document.body.classList.toggle('ink-off')")
            seen[f"{skin}:{variant}"] = (first, toggled)

    assert set(worn) == {t.name for t in palettes}
    for name, (css, c) in worn.items():
        p, q = c["pressed"], c["plain"]
        tokens = {"fill": _hex(p["fill"][:3]), "ring": _hex(p["ring"]), "text": _hex(p["label"]["color"]),
                  "plain": _hex(q["fill"][:3]), "around": _hex(p["around"])}
        assert tokens == {k: css[v].upper() for k, v in (("fill", "--select"), ("ring", "--accent"),
                          ("text", "--text"), ("plain", "--panel"), ("around", "--panel"))}, (name, tokens)
        assert p["ringWidth"] == "2px" and p["mark"]["text"] == "✓" and p["mark"]["shown"], (name, p)
        ratios = {"pressed": _ratio(p["label"]["color"], p["label"]["ground"]),
                  "note on --select": _ratio(p["note"]["color"], p["note"]["ground"]),
                  "note on --panel": _ratio(q["note"]["color"], q["note"]["ground"]),
                  "label on --panel": _ratio(q["label"]["color"], q["label"]["ground"]),
                  "group label": _ratio(c["glabel"]["color"], c["glabel"]["ground"]),
                  "ring": _ratio(p["ring"], p["around"])}
        print(f"\n  {name:15s} " + "  ".join(f"{k} {v:.2f}" for k, v in ratios.items()))
        assert ratios.pop("ring") >= 3.0, (name, ratios)
        assert min(ratios.values()) >= 4.5, (name, ratios)

    assert set(seen) == {f"{s}:{v}" for s, v in looks}
    for look, pair in seen.items():
        for c in pair:
            p, q = c["pressed"], c["plain"]
            where = f"{look}{' ink-off' if c['inkOff'] else ''}"
            assert p["mark"]["text"] == "✓" and p["mark"]["shown"], (where, p["mark"])
            ratios = {"pressed": _ratio(p["label"]["color"], p["label"]["ground"]),
                      "pressed note": _ratio(p["note"]["color"], p["note"]["ground"]),
                      "check": _ratio(p["mark"]["color"], p["mark"]["ground"]),
                      "plain": _ratio(q["label"]["color"], q["label"]["ground"]),
                      "plain note": _ratio(q["note"]["color"], q["note"]["ground"]),
                      "group label": _ratio(c["glabel"]["color"], c["glabel"]["ground"])}
            print(f"\n  {where:28s} " + "  ".join(f"{k} {v:.2f}" for k, v in ratios.items())
                  + f"  ring {_ratio(p['ring'], p['around']):.2f} (printed)")
            assert min(ratios.values()) >= 4.5, (where, ratios)


# ---------------------------------------------------------------------------- the source


def _no_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def test_the_picker_stylesheet_is_tokens_only_and_every_rule_is_under_mpick():
    """Between `/* ---- the model picker` and the settings marker: no colour literal, no `--muted`,
    and every selector starts `.mpick`, so the picker can restyle nothing else on either page."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    start = css.index("/* ---- the model picker")
    section = _no_comments(css[start:css.index(MARKER)])
    assert section.count("{") > 10, "the section is where the picker's rules are"
    for bad in (r"#[0-9a-fA-F]{3,8}\b", r"\brgba?\(", r"\bhsla?\(", r"--muted"):
        assert not re.search(bad, section), bad
    selectors = []
    for group in re.findall(r"([^{};]+)\{", section):
        if group.strip().startswith("@"):
            continue
        selectors += [s.strip() for s in group.split(",")]
    assert selectors and [s for s in selectors if not s.startswith(".mpick")] == [], selectors
    assert "prefers-reduced-motion: no-preference" in section and "transition:" in section


def test_the_picker_is_one_classic_script_loaded_after_common_on_both_pages():
    js = open(os.path.join(STATIC, "picker.js"), encoding="utf-8").read()
    assert re.findall(r"(?m)^function (\w+)\(", js) == ["createModelPicker", "drawModelPicker"]
    names = set(re.findall(r"(?m)^(?:var|let|const|function|class)\s+([A-Za-z_$][\w$]*)", js))
    assert names == {"mpImpl", "createModelPicker", "drawModelPicker"}, names
    code = re.sub(r"//[^\n]*", " ", _no_comments(js))
    for bad in ("innerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "setInterval",
                "fetch(", "post(", '"select"', '"datalist"', "Ink.", "rgb(", "hsl("):
        assert bad not in code, bad
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code)
    for page in ("index.html", "settings.html"):
        html = open(os.path.join(STATIC, page), encoding="utf-8").read()
        assert ('<script src="/static/common.js"></script>\n'
                '<script src="/static/picker.js"></script>\n') in html, page
    assert S.ASSETS.index("picker.js") == S.ASSETS.index("common.js") + 1


def test_the_picker_fits_in_six_kib_on_the_wire():
    body = open(os.path.join(STATIC, "picker.js"), "rb").read()
    sent = len(gzip.compress(body, 6, mtime=0))
    print(f"\n  picker.js {sent} bytes gzipped ({len(body)} on disk)")
    assert sent <= 6 * 1024, sent
