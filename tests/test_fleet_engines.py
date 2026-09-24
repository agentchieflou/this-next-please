"""What each engine really does, and what happens where it does not (issue #220).

The desk has to load inside PyCharm's JCEF tool window and VS Code's Simple Browser as well as in
a real browser, and those two are behind Chromium by a version or several. Every platform feature
this epic leaned on therefore has to answer two questions: does this engine have it, and what
happens on the one that does not.

The second question is the one that gets skipped, so it is the one asserted here: for every
feature with a fallback, the fallback is exercised *by stubbing the feature away* and checking the
page still arrives at the same place. `docs/desk-engines.md` holds the rows; this file keeps them
honest, and writes the measured Chromium column itself.
"""
from __future__ import annotations
import os
import re
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import _gutter_point

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
ENGINES = os.path.join(ROOT, "docs", "desk-engines.md")

#: Every platform feature this epic used, with the probe that answers "is it really here" and
#: what the page does when it is not. A feature with no fallback has to be one whose absence
#: costs nothing.
FEATURES = {
    "@starting-style": "() => CSS.supports('selector(:not(*))') "
                       "&& typeof CSSStartingStyleRule !== 'undefined'",
    "transition-behavior: allow-discrete":
        "() => CSS.supports('transition-behavior', 'allow-discrete')",
    "startViewTransition": "() => typeof document.startViewTransition === 'function'",
    "linear() easing": "() => CSS.supports('animation-timing-function', 'linear(0, 1)')",
    "pointer capture": "() => typeof Element.prototype.setPointerCapture === 'function'",
    "ResizeObserver": "() => typeof ResizeObserver === 'function'",
    "container queries": "() => CSS.supports('container-type', 'inline-size')",
    "OffscreenCanvas": "() => typeof OffscreenCanvas !== 'undefined'",
    # The prototype only (#384): no context is created to ask, and never a 2D one.
    "HTML-in-canvas": "() => typeof WebGL2RenderingContext !== 'undefined' "
                      "&& ['texElementImage2D', 'texElementSubImage2D', 'texElement2D']"
                      ".some(n => typeof WebGL2RenderingContext.prototype[n] === 'function')",
    "WebGL": "() => { const c = document.createElement('canvas'); "
             "return !!(c.getContext('webgl2') || c.getContext('webgl')); }",
}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})


def _repos(tmp_path, *names):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name,
                                                         "model": "claude-haiku-4.5"},
                                ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _section(heading: str) -> str:
    """One `##` section of the engines page. The file has two tables whose first column is a
    feature name, and merging them by that column would read a fallback as a verdict."""
    doc = open(ENGINES, encoding="utf-8").read()
    body = doc.split("\n## " + heading + "\n", 1)
    assert len(body) == 2, f"no section '{heading}' in docs/desk-engines.md"
    return body[1].split("\n## ", 1)[0]


def _rows():
    """The engine table, as {feature: {engine: verdict}}."""
    out = {}
    header = None
    for line in _section("The rows").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if set("".join(cells)) <= set("- :"):
            continue
        out[cells[0].strip("`")] = dict(zip(header[1:], cells[1:]))
    return out


# --------------------------------------------------------------------------------- the rows


def test_every_feature_this_epic_used_has_a_row():
    rows = _rows()
    missing = [f for f in FEATURES if f not in rows]
    assert missing == [], f"used and not in the table: {missing}"


def test_every_cell_is_filled_in_or_says_it_is_not_measured():
    """The acceptance criterion. A blank cell is a claim nobody made and a reader will take as
    'fine' -- *not yet measured* is a smaller promise and a true one."""
    allowed = ("works", "falls back", "not yet measured", "n/a — not used")
    bad = []
    for feature, engines in _rows().items():
        for engine, verdict in engines.items():
            plain = re.sub(r"[*_`]", "", verdict).strip().lower()
            if not plain:
                bad.append(f"{feature} / {engine}: blank")
            elif not any(plain.startswith(a) for a in allowed):
                bad.append(f"{feature} / {engine}: {verdict!r}")
    assert bad == [], bad


def test_the_fallback_for_every_feature_that_has_one_is_named_and_tested():
    doc = open(ENGINES, encoding="utf-8").read()
    for feature in FEATURES:
        assert feature in doc, feature
    # Each fallback names the test that proves it.
    for named in ("test_fleet_motion.py", "test_fleet_window.py", "test_fleet_trace.py",
                  "test_fleet_instant.py", "test_fleet_engines.py", "test_fleet_gutters.py"):
        assert named in doc, named


def test_the_probe_asks_every_row_the_table_has():
    """The laptop's cells come from `/probe` (#235), not from a dev console. So the probe page asks
    every row this file asks of CI's Chromium, and `probe.FEATURES` has a cell for each answer --
    one of the table's own words -- or a row would stay *not yet measured* however often the
    operator ran it."""
    from agentdata.fleet import probe as PR

    rows = set(_rows())
    asked = set(FEATURES) - {"WebGL"}           # WebGL is the probe's scene, not a yes or no
    assert set(PR.FEATURES) == asked, set(PR.FEATURES) ^ asked
    assert asked == rows - {"WebGL"}, rows ^ asked
    js = open(os.path.join(STATIC, "probe.js"), encoding="utf-8").read()
    for name, fallback in PR.FEATURES.items():
        assert f'ask("{name}", ' in js, f"probe.js does not ask {name!r}"
        assert fallback.startswith(("falls back — ", "n/a — not used")), (name, fallback)


@pytest.mark.browser
def test_the_chromium_column_is_what_chromium_actually_does(fleet_home, tmp_path):
    """Measured, not asserted from memory. The other two columns cannot be measured from here --
    JCEF and the Simple Browser are not in this container -- and the table says so rather than
    guessing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            version = page.evaluate("() => navigator.userAgent")
            got = {name: bool(page.evaluate(probe)) for name, probe in FEATURES.items()}
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    print("\n" + version)
    for name, ok in sorted(got.items()):
        if name == "WebGL":
            # A context, not a verdict: the row is the probe's (#247), printed by the test below.
            print(f"  {name:38s} {'a context' if ok else 'absent'}; the row is the probe's")
            continue
        print(f"  {name:38s} {'works' if ok else 'absent'}")

    rows = _rows()
    column = next(c for c in next(iter(rows.values())) if "Chromium" in c)
    wrong = []
    for name, ok in got.items():
        if name == "WebGL":
            # A context is not a verdict (#247): SwiftShader grants one and draws at software
            # speed. The row is the probe's, and `test_the_webgl_row_is_what_the_probe_measured`
            # below holds it to what `/probe` recorded in this same engine.
            continue
        said = re.sub(r"[*_`]", "", rows[name][column]).strip().lower()
        if ok and not said.startswith(("works", "n/a")):
            wrong.append(f"{name}: Chromium has it, the table says {said!r}")
        if not ok and said.startswith("works"):
            wrong.append(f"{name}: the table says works, Chromium has not got it")
    assert wrong == [], wrong


@pytest.mark.browser
def test_the_webgl_row_is_what_the_probe_measured(fleet_home):
    """The WebGL row, measured the way every other shell will be (#247): `/probe` in this engine,
    posted to the desk, classified by `probe.classify`.

    Headless Chromium draws WebGL2 on SwiftShader -- correctly, and in software. So CI's own cell
    says *falls back*, and a table that said *works* because a context exists would be the claim
    the operator's three.js decision rests on, made by the one engine that proves nothing about a
    GPU. The numbers are printed for the run's summary and not asserted: they are SwiftShader's.
    """
    import sys

    from agentdata.fleet import probe as PR

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    server, token, port = _serve()
    posts = []
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
            page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=chromium",
                      wait_until="domcontentloaded")
            page.wait_for_function(
                "() => /saved|not saved/.test(document.getElementById('state').textContent)",
                timeout=30000)
            shown = page.text_content("#verdict")
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    rec = PR.load()["chromium"]
    print(f"\n  webgl probe      {rec['webgl']} on {rec['renderer']} -> {PR.classify(rec)}")
    print(f"  webgl frames     p50 {rec['p50_ms']} ms, p95 {rec['p95_ms']} ms over "
          f"{rec['frames']} frames; first stroke {rec['first_stroke_ms']} ms")

    assert len(posts) == 1 and "/api/probe" in posts[0], posts
    assert rec["webgl"] in ("webgl2", "webgl1") and rec["drawn"] is True, rec
    assert rec["three"] == "160" and rec["error"] == "", rec
    assert rec["frames"] > 0 and rec["p95_ms"] >= rec["p50_ms"] > 0, rec
    assert rec["first_stroke_ms"] > 0, rec
    assert PR.classify(rec) == "software", rec["renderer"]
    if sys.platform.startswith("linux"):
        assert "SwiftShader" in rec["renderer"], rec["renderer"]
    assert "falls back" in shown, shown

    # The cell itself, not only the works/not-works bit it adds up to (#261): a cell pasted back
    # as *not yet measured* -- which the laptop's `ad-fleet engines` prints for `chromium`, a
    # shell it never probes -- is a regression the bit alone would have let through.
    column = next(c for c in _rows()["WebGL"] if "Chromium" in c)
    said = re.sub(r"[*_`]", "", _rows()["WebGL"][column]).strip().lower()
    assert said.startswith("works") == PR.works(rec), \
        f"the table says {said!r} and the probe says {PR.verdict(rec)!r}"
    if sys.platform.startswith("linux"):
        assert said == PR.verdict(rec).lower(), \
            f"the table says {said!r} and the probe measured {PR.verdict(rec)!r}"
    else:
        assert said.startswith(("falls back", "works")), said


@pytest.mark.browser
def test_the_feature_rows_are_what_the_probe_recorded_in_this_engine(fleet_home):
    """The rest of the table, measured the way the laptop's shells are (#235): `/probe` asks every
    row, the desk keeps the answers, and `probe.feature_cell` turns them into cells. In CI's
    Chromium those cells must be the Chromium column as written, and the probe's answers the ones
    `FEATURES` gets asking the same engine -- or the laptop's columns would be measuring something
    this one does not."""
    from agentdata.fleet import probe as PR

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=chromium",
                      wait_until="domcontentloaded")
            page.wait_for_function(
                "() => /saved|not saved/.test(document.getElementById('state').textContent)",
                timeout=30000)
            asked = {name: bool(page.evaluate(probe)) for name, probe in FEATURES.items()
                     if name != "WebGL"}
            shown = page.text_content("#features")
            left = page.evaluate("() => !!document.getElementById('cq-probe')")
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    rec = PR.attempts()["chromium"]
    print("\n  features        " + ", ".join(f"{k}: {v}" for k, v in rec["features"].items()))
    assert rec["features"] == asked, (rec["features"], asked)
    rows = _rows()
    column = next(c for c in rows["WebGL"] if "Chromium" in c)
    wrong = {name: (rows[name][column], PR.feature_cell(rec, name)) for name in PR.FEATURES
             if re.sub(r"[*_`]", "", rows[name][column]).strip() != PR.feature_cell(rec, name)}
    assert wrong == {}, f"the table says one thing and the probe measured another: {wrong}"
    assert shown == "HTML-in-canvas: " + PR.FEATURES["HTML-in-canvas"], shown
    assert not left, "the container query's test element was left in the page"


@pytest.mark.browser
def test_the_gutter_keeps_the_pointer_when_the_hand_leaves_its_strip(fleet_home, tmp_path):
    """Pointer capture on the gutter (#234), measured: the press takes the capture, and every move
    after it is the gutter's -- 150px to the right, and then up off the row altogether, into the
    toolbar, far from an 8px strip -- until the hand comes up, when the capture is let go. The
    width follows the hand the whole way, stays where the hand left it, and the release selects
    nothing and opens nothing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile.is-solo[data-tier="full"]').length === 2
                         && windowWrites === 0""", timeout=15000)
            page.evaluate("""() => {
              const g = document.querySelector('.tile[data-repo="alpha"] > .gutter');
              window.__cap = { got: 0, lost: 0, moves: [] };
              g.addEventListener('gotpointercapture', () => { window.__cap.got += 1; });
              g.addEventListener('lostpointercapture', () => { window.__cap.lost += 1; });
              document.addEventListener('pointermove', e => {
                if (gutterHeld) window.__cap.moves.push(e.target === g);
              }, true);
            }""")
            before = page.evaluate(
                "() => document.querySelector('.tile[data-repo=\"alpha\"]').getBoundingClientRect().width")
            selected = page.evaluate("() => desk.desk.selected || ''")
            x, y = _gutter_point(page, "alpha")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + 150, y, steps=10)
            page.mouse.move(x + 150, 4, steps=10)
            page.wait_for_function(
                """(want) => Math.abs(document.querySelector('.tile[data-repo="alpha"]')
                              .getBoundingClientRect().width - want) < 2""",
                arg=before + 150, timeout=8000)
            under = page.evaluate(f"""() => {{
              const el = document.elementFromPoint({x + 150}, 4);
              return el ? (el.closest('#grid') ? 'the row' : el.tagName.toLowerCase()) : '';
            }}""")
            page.mouse.up()
            page.wait_for_function("() => !gutterHeld && windowWrites === 0", timeout=8000)
            cap = page.evaluate("() => window.__cap")
            after = page.evaluate(
                "() => document.querySelector('.tile[data-repo=\"alpha\"]').getBoundingClientRect().width")
            now = page.evaluate("() => ({ selected: desk.desk.selected || '', open: openName() })")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    print(f"\n  gutter capture   got {cap['got']}, lost {cap['lost']}, "
          f"{sum(cap['moves'])}/{len(cap['moves'])} moves the gutter's")
    assert under and under != "the row", f"the hand was meant to leave the row, not {under!r}"
    assert cap["got"] == 1 and cap["lost"] == 1, cap
    assert cap["moves"] and all(cap["moves"]), cap
    assert abs(after - (before + 150)) < 2, (before, after)
    assert now == {"selected": selected, "open": "alpha"}, now


# -------------------------------------------------------------------- and without the feature


@pytest.mark.browser
def test_the_desk_arrives_at_the_same_place_with_every_fallback_taken(fleet_home, tmp_path):
    """All of them at once, which is the worst engine anyone will actually meet: no view
    transitions, no pointer capture, no `linear()`, no container queries, no `ResizeObserver`. The
    desk still hides a tile, still reorders, still resizes by the gutter -- whose move and release
    are heard on the document, so a lost capture costs nothing (#234) -- still gives every pane its
    tier, measured after each layout pass when there is no observer to say so (#235), still draws
    its traces, and still lands where it would have."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("""
              delete Document.prototype.startViewTransition;
              delete Element.prototype.setPointerCapture;
              delete Element.prototype.releasePointerCapture;
              delete window.ResizeObserver;
              const realSupports = CSS.supports.bind(CSS);
              CSS.supports = function (a, b) {
                const text = String(a) + ' ' + String(b === undefined ? '' : b);
                if (/linear\\(|allow-discrete|container-type/.test(text)) return false;
                return realSupports.apply(null, arguments);
              };
            """)
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            # Attached is enough: gamma is a rail (#233), on the glass, and nothing here reads it.
            page.wait_for_selector('.tile[data-repo="gamma"]', state="attached", timeout=15000)

            page.evaluate("() => setHidden('beta', true)")
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="beta"]')
                           .classList.contains('is-hidden')""", timeout=8000)
            page.evaluate("() => moveTile('gamma', -1)")
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')]
                          .map(t => t.dataset.repo).indexOf('gamma') < 2""", timeout=8000)
            # The gutter between the two panes on the glass, pulled so that the rail opens -- once
            # the move above has finished travelling, or its box is where the gutter was.
            pair = page.evaluate("""() => {
              const on = [...document.querySelectorAll('#grid .tile')]
                .filter(t => !t.classList.contains('is-hidden'));
              return { left: on[0].dataset.repo, wide: on[0].classList.contains('is-solo') };
            }""")
            x, y = _gutter_point(page, pair["left"])
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + (-400 if pair["wide"] else 400), y, steps=10)
            page.mouse.up()
            page.wait_for_function(
                "() => document.querySelectorAll('#grid .tile.is-solo').length === 2", timeout=8000)
            out = page.evaluate("""() => ({
              traces: [...document.querySelectorAll('.tile .trace')]
                        .filter(c => c.getAttribute('aria-label')).length,
              order: [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo),
              hidden: (getArrangement().hidden || []),
              observer: typeof ResizeObserver,
              tiers: [...document.querySelectorAll('#grid .tile:not(.is-hidden)')]
                       .map(t => [t.classList.contains('is-solo'), t.dataset.tier || '']),
            })""")
            assert not errors, errors
            assert out["hidden"] == ["beta"], out
            assert out["order"][0] != "alpha" or out["order"].index("gamma") < 2, out
            assert out["traces"] >= 1, "the traces stopped drawing without view transitions"
            # Without an observer the tiers still follow the widths: the pane the gutter opened is
            # drawn wide, and the rail it left is a rail.
            assert out["observer"] == "undefined", out
            assert all((tier in ("compact", "full")) if wide else tier == "rail"
                       for wide, tier in out["tiers"]), out["tiers"]
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------ the inventory, complete


def test_every_component_in_the_inventory_names_a_test_that_exists():
    """The other acceptance criterion: a component with no test named beside it is a component
    nobody will notice breaking."""
    doc = open(os.path.join(ROOT, "docs", "desk-components.md"), encoding="utf-8").read()
    rows = [line for line in doc.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")]
    assert len(rows) > 20, "the inventory has lost its table"
    missing = []
    for row in rows[1:]:                                  # past the header
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 7:
            continue
        component, named = cells[0], cells[6]
        if not named or named == "—":
            missing.append(f"{component}: no test named")
            continue
        for file in re.findall(r"`([\w./-]+\.py)`", named):
            if not os.path.isfile(os.path.join(ROOT, "tests", os.path.basename(file))):
                missing.append(f"{component}: {file} does not exist")
    assert missing == [], missing
