"""The world (#626): the fleet as a rainy 3D space you walk with a controller or the keyboard.

The operator's verdict on #400 (2026-10-02): "the agents become objects. And when they need a user, a
user has to move to the agent to interact with it ... Just assume it is a rainy day. And that it can be
day or night, depending on what the local time is."

CI draws in SwiftShader, at a few frames a second, so nothing here waits on the frame rate: the tests
hold the walk (`FleetWorld.hold`) and step it themselves (`FleetWorld.step`), and measure the scene by
its draw calls and triangles. The frame rate is the laptop's to measure (docs/fleet-world.md).
"""
from __future__ import annotations
import os
import re
import threading
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import events as E, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_switcher import _repo, fleet_home, spawns  # noqa: F401

STATIC = S.STATIC
READY = "n => !!window.FleetWorld && FleetWorld.inspect().ready && FleetWorld.inspect().agents.length === n"
#: A standard-mapping gamepad the page reads through `navigator.getGamepads()`; `__press(i, on)` and
#: `__axes([...])` move it between steps.
PAD = """() => {
  const pad = { connected: true, mapping: 'standard', axes: [0, 0, 0, 0],
                buttons: Array.from({ length: 17 }, () => ({ pressed: false, value: 0 })) };
  Object.defineProperty(navigator, 'getGamepads', { configurable: true, value: () => [pad] });
  window.__press = (i, on) => { pad.buttons[i] = { pressed: on, value: on ? 1 : 0 }; };
  window.__axes = a => { pad.axes = a; };
}"""


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _asks(tmp_path):
    """An agent stopped on one question with choices, and an id the answer can name."""
    path = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-7")
    Registry().add(path, name="asks")
    E.append("asks", [
        E.event("asks", "started", {"prompt": "Ticket RDSD-7", "session": ""}, ticket="RDSD-7"),
        E.event("asks", "session_id", {"session": "sess-a"}, ticket="RDSD-7"),
        E.event("asks", "question_opened", {"id": "q1", "question": "which sprint boundary?",
                                            "choices": ["calendar", "fiscal"]}, ticket="RDSD-7"),
    ])


def _open(browser, port, token, query="", n=2):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/world?t={token}{query}", wait_until="domcontentloaded")
    page.wait_for_function(READY, arg=n, timeout=30000)
    return page, errors


def _inspect(page):
    return page.evaluate("() => FleetWorld.inspect()")


def _until_near(page, repo):
    """Walk forward a sixtieth of a second at a time until `repo` is within reach (at most 4 s)."""
    return page.evaluate("""repo => { for (let i = 0; i < 240 && FleetWorld.inspect().near !== repo; i++) FleetWorld.step(1 / 60);
                                     return FleetWorld.inspect().near; }""", repo)


# ------------------------------------------------------------------------------- served, and a door


def test_the_world_is_a_page_of_its_own_and_the_desk_opens_it(fleet_home):
    """`/world` is served with its assets carrying the token, `/open?page=world` lands on it, and the
    desk's toolbar links it. Its three.js is the vendored r160, imported through `q()`."""
    assert S.PAGES["/world"] == "world.html"
    assert "world.css" in S.ASSETS and "world/world.js" in S.ASSETS
    server, token, port = _serve()
    try:
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/world?t={token}", timeout=5).read().decode()
        assert f'"/static/world/world.js?t={token}"' in html and f'"/static/world.css?t={token}"' in html
        assert "ink-off" in html

        class Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        try:
            urllib.request.build_opener(Stay).open(f"http://127.0.0.1:{port}/open?page=world", timeout=5)
            raise AssertionError("/open answered without a redirect")
        except urllib.error.HTTPError as e:
            assert e.code == 302 and e.headers["Location"].startswith(f"/world?t={token}")
    finally:
        _stop(server)

    desk = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    world = open(os.path.join(STATIC, "world", "world.js"), encoding="utf-8").read()
    assert 'id="worldbtn"' in desk and 'worldLink.href = pageUrl("/world")' in app
    assert 'V_THREE = "/static/vendor/three/three.module.min.js"' in world and "import(q(V_THREE))" in world
    assert not re.search(r"\bimport\s+[\w{*]", world), "a classic script: three.js is imported with import(), never a static import"


# ------------------------------------------------------------------------------- the place, in a browser


@pytest.mark.browser
def test_agents_stand_in_the_rain_by_day_and_by_night(fleet_home, tmp_path, browser):
    """One figure per agent, its name over its head; the one that needs you has a beacon and the
    compass points to it. `?hour=13` is overcast day with the lamps out; `?hour=23` is night with the
    lamps lit. The scene is 13 draw calls, however many agents and however much rain."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13")
        day = _inspect(page)
        assert [(a["repo"], a["needs"]) for a in day["agents"]] == [("alpha", False), ("asks", True)], day
        assert day["beacons"] == 1 and day["rain"] >= 5000
        assert day["daylight"] == 1 and day["night"] is False and day["lamps"] == 0, day
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=30000)
        drawn = _inspect(page)
        assert 0 < drawn["calls"] <= 13 and drawn["triangles"] < 60000, drawn
        tags = page.evaluate("() => [...document.querySelectorAll('#wlabels .wtag')].map(t => [t.querySelector('.wtag-name').textContent, t.className, t.hidden])")
        assert [(n, "needs" in c) for n, c, _ in tags] == [("alpha", False), ("asks", True)], tags
        assert not dict((n, hid) for n, _, hid in tags)["asks"], "the agent you face is labelled"
        assert not page.is_hidden("#wcompass") and "asks needs you" in page.text_content("#wcompass")
        assert "1 need you" in page.text_content("#wneed")
        assert page.text_content("#wlist").count(":") == 2
        assert errors == [], errors
        page.close()

        page, errors = _open(browser, port, token, "&hour=23")
        night = _inspect(page)
        assert night["daylight"] == 0 and night["night"] is True and night["lamps"] > 0, night
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_you_walk_to_an_agent_to_talk_to_it(fleet_home, tmp_path, browser, spawns):
    """From the middle of the plaza nothing is within reach and E opens nothing. W walks 4.5 m a
    second towards the agent you face; within reach the prompt names it, E opens it, and its question
    is answered there with the desk's own verb."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13")
        page.evaluate("() => FleetWorld.hold(true)")
        start = _inspect(page)
        assert start["near"] == "" and page.is_hidden("#wprompt")
        page.keyboard.press("KeyE")
        assert _inspect(page)["open"] == "", "nothing opens from across the plaza"

        page.keyboard.down("KeyW")
        moved = page.evaluate("() => FleetWorld.step(1)")
        page.keyboard.up("KeyW")
        walked = ((moved["x"] - start["player"]["x"]) ** 2 + (moved["z"] - start["player"]["z"]) ** 2) ** 0.5
        assert 4.4 < walked < 4.6, walked
        page.keyboard.down("KeyW")
        assert _until_near(page, "asks") == "asks"
        page.keyboard.up("KeyW")
        page.wait_for_function("() => !document.getElementById('wprompt').hidden", timeout=10000)
        assert "talk to asks" in page.text_content("#wprompt")

        page.keyboard.press("KeyE")
        page.wait_for_function("() => FleetWorld.inspect().open === 'asks' && !document.getElementById('wpanel').hidden",
                               timeout=10000)
        assert page.evaluate("() => document.activeElement.textContent") == "calendar", "the keyboard lands on a choice"
        page.click("#wasklist .ask-choice >> text=fiscal")
        with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/answer")) as asked:
            page.click("#wanswer")
        assert asked.value.post_data_json == {"repo": "asks", "answers": [{"id": "q1", "answer": "fiscal"}]}
        page.keyboard.press("Escape")
        page.wait_for_function("() => FleetWorld.inspect().open === '' && document.getElementById('wpanel').hidden",
                               timeout=10000)
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_controller_walks_there_and_answers_without_a_keyboard(fleet_home, tmp_path, browser, spawns):
    """A standard-mapping gamepad: the left stick walks, A talks, the D-pad moves between the
    conversation's buttons, A presses the one that has the keyboard, and B steps back."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13")
        page.evaluate(PAD)
        page.evaluate("() => FleetWorld.hold(true)")
        start = _inspect(page)["player"]
        page.evaluate("() => window.__axes([0, -1, 0, 0])")
        moved = page.evaluate("() => FleetWorld.step(1)")
        walked = ((moved["x"] - start["x"]) ** 2 + (moved["z"] - start["z"]) ** 2) ** 0.5
        assert 4.4 < walked < 4.6, walked
        assert _until_near(page, "asks") == "asks"
        page.evaluate("() => window.__axes([0, 0, 0, 0])")

        def tap(button):
            page.evaluate(f"() => {{ window.__press({button}, true); FleetWorld.step(1 / 60);"
                          f" window.__press({button}, false); FleetWorld.step(1 / 60); }}")

        tap(0)
        assert _inspect(page)["open"] == "asks"
        assert page.evaluate("() => document.activeElement.textContent") == "calendar"
        tap(0)
        assert page.evaluate("() => document.querySelector('#wasklist .wq-answer').value") == "calendar"
        for _ in range(3):
            tap(13)
        assert page.evaluate("() => document.activeElement.id") == "wanswer"
        with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/answer")) as asked:
            tap(0)
        assert asked.value.post_data_json == {"repo": "asks", "answers": [{"id": "q1", "answer": "calendar"}]}
        tap(1)
        assert _inspect(page)["open"] == ""
        assert errors == [], errors
    finally:
        _stop(server)
