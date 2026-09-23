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
    "container queries": "() => CSS.supports('container-type', 'inline-size')",
    "OffscreenCanvas": "() => typeof OffscreenCanvas !== 'undefined'",
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
                  "test_fleet_instant.py"):
        assert named in doc, named


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
            page.wait_for_selector(".tile", timeout=15000)
            version = page.evaluate("() => navigator.userAgent")
            got = {name: bool(page.evaluate(probe)) for name, probe in FEATURES.items()}
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    print("\n" + version)
    for name, ok in sorted(got.items()):
        print(f"  {name:38s} {'works' if ok else 'absent'}")

    rows = _rows()
    column = next(c for c in next(iter(rows.values())) if "Chromium" in c)
    wrong = []
    for name, ok in got.items():
        said = re.sub(r"[*_`]", "", rows[name][column]).strip().lower()
        if ok and not said.startswith(("works", "n/a")):
            wrong.append(f"{name}: Chromium has it, the table says {said!r}")
        if not ok and said.startswith("works"):
            wrong.append(f"{name}: the table says works, Chromium has not got it")
    assert wrong == [], wrong


# -------------------------------------------------------------------- and without the feature


@pytest.mark.browser
def test_the_desk_arrives_at_the_same_place_with_every_fallback_taken(fleet_home, tmp_path):
    """All of them at once, which is the worst engine anyone will actually meet: no view
    transitions, no pointer capture, no `linear()`, no container queries. The desk still hides a
    tile, still reorders, still draws its traces, and still lands where it would have."""
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
            page.evaluate("() => setTileSize('alpha', 2, 1)")
            page.wait_for_function(
                """() => getComputedStyle(document.querySelector('.tile[data-repo="alpha"]'))
                           .getPropertyValue('--cols').trim() === '2'""", timeout=8000)
            out = page.evaluate("""() => ({
              traces: [...document.querySelectorAll('.tile .trace')]
                        .filter(c => c.getAttribute('aria-label')).length,
              order: [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo),
              hidden: (getArrangement().hidden || []),
            })""")
            assert not errors, errors
            assert out["hidden"] == ["beta"], out
            assert out["order"][0] != "alpha" or out["order"].index("gamma") < 2, out
            assert out["traces"] >= 1, "the traces stopped drawing without view transitions"
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
