"""The ownership epic's definition-of-done demo (issue #220).

Five agents on one desk, and the five gestures this epic exists for, done in order on one page:

* a **swap** -- open one agent, then go back to the one before, so the layout changes under a
  transition;
* a **resize** -- the open tile two tracks wide and two rows tall, from the keyboard (its edge
  handles snapped to the grid's tracks and went with the grid, #232);
* a **hide** -- off the glass and back, painting before the server answers;
* a **reconnect** -- the stream dropped and the desk still showing what it had;
* and a **redraw** -- twenty passes with nothing to change, touching nothing.

Recorded as a short video and a pair of screenshots. `AGENTDATA_SHOTS=<dir>` says where; without
it they go to pytest's own tmp dir and are thrown away, which is what CI wants and what a laptop
run does not.
"""
from __future__ import annotations
import os
import shutil
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

SKINS = ["none", "glass:smoke"]


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


def _agent(tmp_path, name, *, says, needs=False, events=14):
    Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    rows = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
            E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1")]
    for i in range(events):
        rows.append(E.event(name, "tool_call", {"name": "bash", "n": i}, ticket="RDSD-1"))
    rows.append(E.event(name, "assistant_text", {"text": says, "model": "claude-haiku-4.5"},
                        ticket="RDSD-1"))
    if needs:
        rows.append(E.event(name, "question_opened",
                            {"question": "which window should this go to?", "id": "q1",
                             "blocking": True}, ticket="RDSD-1"))
    else:
        rows.append(E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1"))
    E.append(name, rows)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _desk_of_five(tmp_path):
    _agent(tmp_path, "rdsd-pbi-reporting", says="deployed the model and kicked a refresh",
           events=26)
    _agent(tmp_path, "luna", says="the UAT numbers disagree by four rows", needs=True, events=19)
    _agent(tmp_path, "velocity", says="sprint replay written to .agent/out/", events=8)
    _agent(tmp_path, "backlog-health", says="nothing to do", events=2)
    _agent(tmp_path, "arl-usage", says="reading the usage extract", events=31)
    S.arrange(order=["rdsd-pbi-reporting", "luna", "velocity", "backlog-health",
                             "arl-usage"])


@pytest.mark.browser
def test_five_agents_a_swap_a_resize_a_hide_and_a_reconnect(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of_five(tmp_path)
    shots = os.environ.get("AGENTDATA_SHOTS") or str(tmp_path / "shots")
    os.makedirs(shots, exist_ok=True)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            context = browser.new_context(
                viewport={"width": 1600, "height": 1000},
                record_video_dir=os.path.join(shots, "video"),
                record_video_size={"width": 1600, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="rdsd-pbi-reporting"].is-solo', timeout=15000)
            page.wait_for_function(
                "() => !!document.querySelector('.tile .trace[aria-label]')", timeout=15000)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(shots, "ownership-desk.png"))

            # 1. The swap. One agent opened from its rail and then the one before it again, each
            #    through the one door a layout change has, so the transition is the same one every
            #    gesture uses.
            page.locator('.tile[data-repo="luna"] .pane-rail').click()
            page.wait_for_selector('.tile[data-repo="luna"].is-solo', timeout=8000)
            page.wait_for_timeout(450)
            page.screenshot(path=os.path.join(shots, "ownership-open.png"))
            page.evaluate("() => backToPrevious()")
            page.wait_for_selector('.tile[data-repo="rdsd-pbi-reporting"].is-solo', timeout=8000)
            page.wait_for_timeout(350)

            # 2. The resize, from the keyboard on the open tile.
            page.evaluate(
                """() => document.querySelector('.tile[data-repo="rdsd-pbi-reporting"]').focus()""")
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_function(
                """() => getComputedStyle(
                     document.querySelector('.tile[data-repo="rdsd-pbi-reporting"]'))
                       .getPropertyValue('--cols').trim() === '2'""", timeout=8000)
            page.evaluate("() => setTileSize('rdsd-pbi-reporting', 2, 2)")
            page.wait_for_timeout(450)
            page.screenshot(path=os.path.join(shots, "ownership-resized.png"))

            # 3. The hide, and back. Painted before the server answers, and the footer says where
            #    it went. `h` on the rail, which is where the band's hide button went (#233).
            page.focus('.tile[data-repo="backlog-health"] .pane-rail')
            page.keyboard.press("h")
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="backlog-health"]')
                           .classList.contains('is-hidden')""", timeout=8000)
            page.wait_for_function(
                "() => document.getElementById('hiddencount').textContent === '1 hidden'",
                timeout=8000)
            page.wait_for_timeout(350)
            page.screenshot(path=os.path.join(shots, "ownership-hidden.png"))
            page.locator("#hiddencount").click()
            page.wait_for_function(
                """() => !document.querySelector('.tile[data-repo="backlog-health"]')
                            .classList.contains('is-hidden')""", timeout=8000)

            # 4. The reconnect. The stream is dropped and the desk keeps what it had -- and the
            #    window that comes back shows it before the fleet answers.
            page.evaluate("() => { if (source) { source.close(); source = null; } }")
            page.wait_for_timeout(300)
            still_there = page.evaluate(
                "() => document.querySelectorAll('#grid .tile').length")
            assert still_there == 5, "the desk emptied when the stream went"
            page.add_init_script("""
              const real = window.fetch;
              window.fetch = function (url, opts) {
                if (String(url).indexOf('/api/fleet') >= 0) {
                  return new Promise(go => setTimeout(() => go(real(url, opts)), 1200));
                }
                return real.apply(this, arguments);
              };
            """)
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile", timeout=6000)
            early = page.evaluate("""() => ({
              tiles: document.querySelectorAll('#grid .tile').length,
              stale: document.body.classList.contains('is-stale'),
            })""")
            assert early["tiles"] == 5, early
            assert early["stale"], "the reconnect did not say the desk was the old one"
            page.screenshot(path=os.path.join(shots, "ownership-stale.png"))
            page.wait_for_function(
                "() => !document.body.classList.contains('is-stale')", timeout=15000)

            # 5. The redraw. Twenty passes with nothing to change, touching nothing at all --
            #    which is the render contract, and what every gesture above rests on.
            page.wait_for_timeout(400)
            touched = page.evaluate("""() => {
              let n = 0;
              const what = [];
              const obs = new MutationObserver(rs => {
                n += rs.length;
                rs.forEach(r => what.push(r.type + ' ' + (r.attributeName || '') + ' on ' +
                  (r.target.className || r.target.nodeName)));
              });
              obs.observe(document.body, { subtree: true, childList: true,
                                           attributes: true, characterData: true });
              for (let i = 0; i < 20; i++) redrawAll();
              obs.takeRecords().forEach(r => {
                n += 1;
                what.push(r.type + ' ' + (r.attributeName || '') + ' on ' +
                  (r.target.className || r.target.nodeName));
              });
              obs.disconnect();
              return { n: n, what: what.slice(0, 8) };
            }""")
            assert touched["n"] == 0, \
                f"twenty idle redraws made {touched['n']} DOM mutations: {touched['what']}"

            for skin in SKINS:
                S.act("theme", {"skin": skin})
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(
                    shots, "ownership-" + skin.replace(":", "-") + ".png"))

            assert not errors, errors
            video = page.video
            context.close()
            if video:
                try:
                    shutil.copyfile(video.path(),
                                    os.path.join(shots, "ownership-demo.webm"))
                except OSError:
                    pass
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    made = sorted(f for f in os.listdir(shots) if f.endswith(".png"))
    print(f"\n{len(made)} frames in {shots}: {', '.join(made)}")
    assert len(made) >= 7, made
