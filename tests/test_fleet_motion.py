"""Motion, and the budget it is kept inside (issue #216).

The desk had one transition in it -- the FLIP that moves a tile when the grid reorders -- and
nine panels that appeared and vanished between one frame and the next. The operator's note was
that the difference between a prototype and a product is largely "handling animations and
transitions well", and the failure mode of taking that as licence is an interface where every
animation looks fine on its own and the whole thing feels slow.

So the motion has a budget, written on `:root` in three numbers, and this file is what stops the
budget being a comment. Nothing may last longer than `--motion-slow`; nothing may repeat for
ever except the liveness dot; and everything must be reachable by the reduced-motion block,
including the view-transition pseudo-elements that `*` does not match.
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

BUDGET_MS = 320.0

#: A duration anywhere in a declaration: `220ms`, `.2s`, `0.01ms`.
DURATION = re.compile(r"(?<![\w.-])(\d*\.?\d+)(ms|s)(?![\w-])")


def _sheets():
    yield "app.css", open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    skins = os.path.join(STATIC, "skins")
    for skin in sorted(os.listdir(skins)):
        path = os.path.join(skins, skin, "skin.css")
        if os.path.isfile(path):
            yield f"skins/{skin}/skin.css", open(path, encoding="utf-8").read()


def _ms(value: str, unit: str) -> float:
    return float(value) * (1.0 if unit == "ms" else 1000.0)


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


# --------------------------------------------------------------------------------- the budget


def test_the_three_tokens_are_declared_and_none_of_them_breaks_the_budget():
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    tokens = dict(re.findall(r"--motion-(fast|base|slow):\s*([0-9.]+m?s);", css))
    assert set(tokens) == {"fast", "base", "slow"}, tokens
    values = {k: _ms(*DURATION.match(v).groups()) for k, v in tokens.items()}
    assert values["fast"] < values["base"] < values["slow"], values
    assert values["slow"] <= BUDGET_MS, values


def test_nothing_in_any_stylesheet_lasts_longer_than_the_budget():
    """Every duration in `static/`, tokens included. A number nobody bounded is how a page comes to
    feel slow while every animation in it looks fine on its own."""
    over = []
    for where, css in _sheets():
        for line_no, line in enumerate(css.splitlines(), 1):
            if not re.search(r"(transition|animation)", line) and "--motion-" not in line:
                continue
            if line.lstrip().startswith("/*") or line.lstrip().startswith("*"):
                continue
            for value, unit in DURATION.findall(line):
                got = _ms(value, unit)
                if got > BUDGET_MS:
                    over.append(f"{where}:{line_no}: {value}{unit}")
    assert over == [], f"over the {BUDGET_MS:.0f}ms budget: {over}"


def test_nothing_repeats_for_ever_except_the_one_thing_that_should():
    """A spinner that never stops is a page that is always busy, which is the opposite of the
    reassurance this epic is for. The liveness dot is the exception: it says the stream is alive,
    and a stream is alive for as long as it is alive."""
    offenders = []
    for where, css in _sheets():
        for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            selector, body = rule[0].strip(), rule[1]
            if "infinite" not in body:
                continue
            if ".dot" in selector:
                continue
            offenders.append(f"{where}: {selector.splitlines()[-1].strip()}")
    assert offenders == [], f"animates for ever: {offenders}"


def test_the_reduced_motion_block_reaches_the_pseudo_elements_the_star_does_not():
    """`*` matches no `::view-transition-*` pseudo-element, so the universal block that has covered
    this page since the beginning does not reach a view transition at all."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    assert block, "the reduced-motion block is gone"
    body = block.group(1)
    assert "*, *::before, *::after" in body
    assert "::view-transition-group(*)" in body
    assert "::view-transition-old(*)" in body and "::view-transition-new(*)" in body


def test_every_panel_that_comes_and_goes_carries_the_one_pattern():
    """One block, one class, every panel -- rather than a way of arriving per panel. (The dock was
    one of them, and went with the grid in #232.)"""
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    assert ".enters {" in css and ".enters[hidden]" in css
    assert "@starting-style" in css, "without it there is nothing to animate from"
    assert "transition-behavior: allow-discrete" in css, "without it only the arrival is seen"
    for panel in ("away-strip", "notice", "modelcard", "smenu",
                  "scopereport", "approval", "asks"):
        found = re.search(r'class="[^"]*\b' + re.escape(panel) + r'\b[^"]*"', html)
        assert found, panel
        assert "enters" in found.group(0), f"{panel} arrives without the pattern"


def test_the_one_door_for_a_layout_change_has_both_paths_and_takes_neither_under_reduced_motion():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function transitionLayout(fn)" in js
    assert "document.startViewTransition" in js
    assert "playFlip(first)" in js, "the fallback is still there"
    door = js[js.index("function transitionLayout(fn)"):]
    door = door[:door.index("\n}\n")]
    assert "reduceMotion()" in door, "reduced motion has to be the first thing it asks"
    # Every gesture that moves something goes through it: opening a pane and going back. The
    # grid's zoom, its way out and the edge resize were the other three, and went with the grid
    # (#232); a rearrangement is FLIP through `transitionMove` (#219).
    assert js.count("transitionLayout(") >= 3, js.count("transitionLayout(")
    for gesture in ("function openPane(", "function backToPrevious("):
        body = js[js.index(gesture):]
        assert "transitionLayout(" in body[:body.index("\n}\n")], gesture


# ------------------------------------------------------------------------------ in a browser


@pytest.mark.browser
def test_the_gestures_animate_for_the_base_duration_and_not_at_all_under_reduced_motion(
        fleet_home, tmp_path):
    """`getAnimations()` is the only honest answer to "did that animate": it reports what the
    engine is really running, not what the stylesheet hoped for."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for reduced in (False, True):
                page = browser.new_page(viewport={"width": 1400, "height": 900},
                                        reduced_motion="reduce" if reduced else "no-preference")
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                          wait_until="domcontentloaded")
                page.wait_for_selector(".tile.is-solo", timeout=15000)

                # Opening the session menu is the simplest of the three: one panel, one
                # pattern. The enter animates opacity and translate; `display` is discrete and
                # flips on the first frame, which is what makes the panel there to animate at all.
                ran = page.evaluate("""() => {
                  const menu = document.querySelector('.tile.is-solo .smenu');
                  menu.hidden = false;
                  return menu.getAnimations().map(a => ({
                    prop: a.transitionProperty || '',
                    ms: Math.round(a.effect.getComputedTiming().duration),
                  }));
                }""")
                assert not errors, errors
                if reduced:
                    assert all(a["ms"] <= 1 for a in ran), ran
                else:
                    assert ran, "the menu arrived with no animation at all"
                    props = {a["prop"] for a in ran}
                    assert props == {"opacity", "translate"}, props
                    assert all(200 <= a["ms"] <= 320 for a in ran), ran

                # And the leave, which is the half `allow-discrete` exists for: the panel is
                # still painted after it was hidden, rather than being gone before anyone saw it
                # go.
                #
                # Waited on with an interval rather than a frame. Headless Chromium throttles
                # `requestAnimationFrame` hard when nothing is compositing, so a poll built on it
                # can simply not run on a loaded runner -- and then the stylesheet gets blamed for
                # the scheduler. The `polling` argument takes a millisecond count, which is a
                # timer and is not throttled the same way.
                page.evaluate(
                    "() => { document.querySelector('.tile.is-solo .smenu').hidden = true; }")
                if reduced:
                    page.wait_for_function(
                        """() => document.querySelector('.tile.is-solo .smenu')
                                   .getBoundingClientRect().height === 0""",
                        polling=25, timeout=8000)
                else:
                    # Still there a frame's worth later, which is the whole claim.
                    page.wait_for_timeout(60)
                    left = page.evaluate("""() => {
                      const menu = document.querySelector('.tile.is-solo .smenu');
                      return { box: menu.getBoundingClientRect().height,
                               running: menu.getAnimations().length };
                    }""")
                    assert left["box"] > 0, "the panel was gone before it could be seen going"
                    assert left["running"] > 0, left
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_gesture_that_supersedes_another_is_not_an_unhandled_rejection(fleet_home, tmp_path):
    """Two gestures inside one transition is the most ordinary thing on this page, and the browser
    rejects all three of the superseded transition's promises to say so. Unhandled, that reaches
    the console as `Transition was skipped. New ViewTransition started` -- and reached this suite
    as a page error on the slower of the two CI runners, which is how it was found."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

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
                "() => document.querySelectorAll('#grid .tile[data-tier=\"rail\"]').length >= 2",
                timeout=15000)

            # Four opens inside a frame: every one of them supersedes the one before.
            page.evaluate("""() => {
              openPane('beta'); openPane('gamma'); openPane('delta'); openPane('alpha');
            }""")
            # Waited on by state and not by a clock: a fixed sleep here passes on an idle machine
            # and fails on a loaded one, which is a test measuring the load.
            page.wait_for_function(
                """() => { const t = document.querySelector('.tile.is-solo');
                           return !!t && t.dataset.repo === 'alpha'; }""", timeout=15000)
            page.wait_for_function(
                "() => !document.querySelector('[style*=\"view-transition-name\"]')",
                timeout=15000)
            assert errors == [], errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_with_view_transitions_taken_away_the_same_gestures_run_flip_and_land_identically(
        fleet_home, tmp_path):
    """The IDE shells are behind Chromium and will be for a while. Whatever the desk does on the
    good path it has to do on the other one, and end in the same place."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            shapes = {}
            for stubbed in (False, True):
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if stubbed:
                    page.add_init_script("delete Document.prototype.startViewTransition;")
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                          wait_until="domcontentloaded")
                page.wait_for_selector(".tile.is-solo", timeout=15000)
                assert page.evaluate(
                    "() => typeof document.startViewTransition === 'function'") is not stubbed

                page.evaluate("() => openPane('gamma')")
                page.wait_for_function(
                    """() => document.querySelector('.tile.is-solo')
                              && document.querySelector('.tile.is-solo').dataset.repo === 'gamma'""",
                    timeout=8000)
                page.wait_for_timeout(450)              # past --motion-base, whichever path ran
                shapes[stubbed] = page.evaluate("""() => ({
                  open: document.querySelector('.tile.is-solo').dataset.repo,
                  rails: [...document.querySelectorAll('#grid .tile[data-tier="rail"]')]
                    .map(t => t.dataset.repo),
                  names: [...document.querySelectorAll('.tile')]
                    .map(t => t.style.viewTransitionName || ''),
                })""")
                assert not errors, errors
                page.close()

            assert shapes[False]["open"] == shapes[True]["open"] == "gamma"
            assert shapes[False]["rails"] == shapes[True]["rails"] == ["alpha", "beta"], shapes
            assert shapes[False]["names"] == [""] * len(shapes[False]["names"]), \
                "the names are for the duration of the transition and are cleared after it"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
@pytest.mark.measured
def test_a_layout_change_blocks_the_main_thread_for_no_long_task(fleet_home, tmp_path):
    """The frame-rate floor, measured as the thing this code actually decides.

    A headless runner throttles `requestAnimationFrame` to whatever it feels like -- sixty-six
    millisecond gaps with the page doing nothing at all -- so a floor asserted on frame gaps here
    would be a measurement of the runner and not of the desk. What the desk owns is how long it
    holds the main thread, and the browser reports that directly: a `longtask` entry is a block of
    fifty milliseconds or more, which is three frames nobody could have drawn. None during a swap
    of five tiles at 1080p is the floor. The frame gaps are printed alongside, because the number
    is worth having in the job output even where it cannot be asserted.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon")
    S.arrange(order=["alpha", "beta", "gamma", "delta", "epsilon"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_timeout(300)               # past the first fold's own work

            out = page.evaluate("""() => new Promise(resolve => {
              const long = [];
              const obs = new PerformanceObserver(list => {
                list.getEntries().forEach(e => long.push(Math.round(e.duration)));
              });
              try { obs.observe({ entryTypes: ['longtask'] }); } catch (e) { /* older engine */ }
              const stamps = [];
              let stop = false;
              const tick = t => { stamps.push(t); if (!stop) requestAnimationFrame(tick); };
              requestAnimationFrame(tick);
              const began = performance.now();
              openPane('epsilon');
              const handed = performance.now() - began;
              setTimeout(() => {
                stop = true;
                obs.disconnect();
                const gaps = [];
                for (let i = 1; i < stamps.length; i++) gaps.push(stamps[i] - stamps[i - 1]);
                resolve({ long: long, gaps: gaps, handed: handed,
                          open: document.querySelector('.tile.is-solo').dataset.repo });
              }, 700);
            })""")
            assert not errors, errors
            assert out["open"] == "epsilon", "the swap did not happen at all"
            gaps = sorted(out["gaps"])
            if gaps:
                print(f"\nframes during the swap: median {gaps[len(gaps) // 2]:.1f}ms, "
                      f"max {gaps[-1]:.1f}ms, over {len(gaps)} frames; "
                      f"the call itself held the thread for {out['handed']:.1f}ms")
            assert out["long"] == [], f"the swap blocked the main thread: {out['long']}ms"
            assert out["handed"] <= 50.0, \
                f"the gesture held the thread for {out['handed']:.1f}ms before returning"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
