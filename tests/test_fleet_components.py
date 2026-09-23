"""The render contract, and the inventory that keeps it honest (issue #215).

`place()` runs about two and a half times a second while an agent is talking, and the page used to
rebuild itself at that rate: `drawTile` reassigned `className` wholesale and tore the state chip
down, `drawCells` emptied the cells and recreated all four with fresh listeners, `drawDock` and
`drawRail` cloned every chip again. Anything transient on any of them -- a hover, the keyboard, a
half-finished click -- was gone by the next pass.

The contract is in `docs/desk-components.md`. What is asserted here is that it holds.
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
INVENTORY = os.path.join(ROOT, "docs", "desk-components.md")


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


def _repos(tmp_path, *names, needs=()):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        rows = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1"),
                E.event(name, "assistant_text", {"text": "working on " + name,
                                                 "model": "claude-haiku-4.5"}, ticket="RDSD-1"),
                E.event(name, "cost", {"premium_requests": 1.5, "source": "checkpoint"},
                        ticket="RDSD-1"),
                E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
        if name in needs:
            rows.append(E.event(name, "question_opened",
                                {"question": "which window?", "id": "q1", "blocking": True},
                                ticket="RDSD-1"))
        E.append(name, rows)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# ------------------------------------------------------------------------------- the inventory


def test_every_draw_function_is_named_in_the_inventory():
    """A component nobody wrote down is one nobody knows the owner of -- which is how two functions
    came to paint the same tile's accent on two different edges."""
    doc = open(INVENTORY, encoding="utf-8").read()
    missing = []
    for page in ("app.js", "settings.js"):
        js = open(os.path.join(STATIC, page), encoding="utf-8").read()
        for name in sorted(set(re.findall(r"(?m)^function (draw[A-Za-z]*)\(", js))):
            if name not in doc:
                missing.append(f"{page}: {name}")
    assert missing == [], f"drawn and not in docs/desk-components.md: {missing}"


def test_every_component_class_the_inventory_names_really_exists():
    """The other direction: a row for a component that is not on the page is a row that will rot."""
    doc = open(INVENTORY, encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    # Only the `Styled in` column, which is the one that names classes and ids.
    named = set()
    for row in doc.splitlines():
        if not row.startswith("| ") or row.startswith("| ---"):
            continue
        cells = [c.strip() for c in row.split("|")]
        if len(cells) < 6:
            continue
        for token in re.findall(r"`([.#][A-Za-z][\w.-]*)`", cells[4]):
            named.add(token)
    assert named, "the inventory names no styled component at all"
    missing = [n for n in sorted(named) if n not in css and n.lstrip(".#") not in html]
    assert missing == [], f"named in the inventory and styled nowhere: {missing}"


def test_the_contract_names_one_reconciler_and_the_page_uses_it():
    """Thirty lines, owned, and the only one. The alternative -- tear the list down and clone it
    again -- is what this slice exists to remove."""
    common = open(os.path.join(STATIC, "common.js"), encoding="utf-8").read()
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function patchList(parent, rows, keyOf, create, update)" in common
    for setter in ("function setClass(", "function toggle(", "function attr(",
                   "function hide(", "function style("):
        assert setter in common, setter
    # The four lists that used to be rebuilt on every draw.
    assert app.count("patchList(") >= 4, app.count("patchList(")
    assert "while (list.children.length > 1) list.removeChild(list.lastChild);" not in app or \
        app.count("while (list.children.length > 1) list.removeChild(list.lastChild);") <= 2, \
        "a list is still being torn down and cloned on every draw"


def test_one_owner_paints_the_accent():
    """The bug the contract is named after: `drawTile` painted `border-left-color` and the `theme`
    stream handler painted `border-top-color`, an edge no rule gives a width to -- so a palette
    changed in a terminal painted an invisible stripe and left the visible one stale."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function paintAccent(el, accent)" in js
    assert "borderTopColor" not in js, "the accent is back on an edge with no width"
    assert js.count("border-left-color") == 1, "two owners again"
    assert js.count("paintAccent(") >= 3, "the fold and the theme frame both call it"


# ---------------------------------------------------------------------------- zero mutations


@pytest.mark.browser
def test_a_draw_with_nothing_to_say_touches_nothing(fleet_home, tmp_path):
    """The acceptance criterion, per component: `draw(el, row)` twice with the same row records no
    DOM mutation at all. Everything else in this slice is in service of this one number being 0."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", needs=("gamma",))
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('#bands .band:not([hidden])').length >= 2",
                timeout=15000)

            counts = page.evaluate("""() => {
              const watch = (node, run) => {
                let n = 0;
                const obs = new MutationObserver(rs => { n += rs.length; });
                obs.observe(node, { subtree: true, childList: true,
                                    attributes: true, characterData: true });
                run();
                obs.takeRecords().forEach(() => { n += 1; });
                obs.disconnect();
                return n;
              };
              const tile = document.querySelector('.tile.is-solo');
              const row = tiles.get(tile.dataset.repo).row;
              const band = document.querySelector('#bands .band:not([hidden])');
              const out = {};
              // Each drawn once more first, so the FIRST of the two passes is not the one that
              // fills in a value for the first time.
              drawTile(tile, row, []);
              out.tile = watch(tile, () => drawTile(tile, row, []));
              drawCells(tile, row.polls || {}, row);
              out.cells = watch(tile.querySelector('.cells'),
                                () => drawCells(tile, row.polls || {}, row));
              drawSessionPill(tile, row);
              out.pill = watch(tile.querySelector('.sessionbar'),
                               () => drawSessionPill(tile, row));
              drawColumn();
              out.column = watch(document.getElementById('bands'), () => drawColumn());
              place();
              out.place = watch(document.body, () => place());
              /* Together, and last. Each of the above is idempotent on its own, and #220's demo
                 found that the *pair* was not: `drawTile` rebuilt the whole class attribute and
                 dropped `is-selected`, `is-hidden`, `is-pinned` and `size-2`, which `place()`
                 then put straight back. Two writers with one draw each is still two writes a
                 pass, and it is only visible when both run. */
              redrawAll();
              out.together = watch(document.body, () => { redrawAll(); });
              return out;
            }""")
            assert not errors, errors
            for component, n in counts.items():
                assert n == 0, f"{component} made {n} DOM mutations with nothing to change"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_keyboard_and_the_hover_survive_twenty_draws(fleet_home, tmp_path):
    """What zero mutations buys: the thing under the cursor is still the thing under the cursor."""
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
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile", timeout=15000)
            page.wait_for_function(
                "() => !!document.querySelector('.tile .cells .cell')", timeout=15000)

            out = page.evaluate("""() => {
              const cell = document.querySelector('.tile .cells .cell');
              cell.__marker = 'still me';
              const say = document.querySelector('.tile .say');
              say.focus();
              say.value = 'half a sentence';
              for (let i = 0; i < 20; i++) { redrawAll(); }
              const after = document.querySelector('.tile .cells .cell');
              return {
                same: after.__marker === 'still me',
                keyboard: document.activeElement === say,
                typed: say.value,
              };
            }""")
            assert not errors, errors
            assert out["same"], "the cell was torn down and cloned again"
            assert out["keyboard"], "twenty draws took the keyboard out of the reply box"
            assert out["typed"] == "half a sentence", "and threw away what was being typed"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
