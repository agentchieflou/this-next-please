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
from test_fleet_desk_glass import _png_pixels

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


def _open(browser, port, token, query="", n=2, who="&who=0"):
    """The world with a character already chosen (`?who=`, a preset), unless `who` is empty: then the
    page opens on the character picker, as a first visit does."""
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/world?t={token}{query}{who}", wait_until="domcontentloaded")
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
    assert html.index("/static/world/hero.js") < html.index("/static/world/world.js"), "the character loads first"
    assert html.index("/static/world/assets.js") < html.index("/static/world/bake.js"), "the photo textures replace baked ones"
    assert not re.search(r"\bimport\s+[\w{*]", world), "a classic script: three.js is imported with import(), never a static import"


# ------------------------------------------------------------------------------- the place, in a browser


@pytest.mark.browser
def test_agents_stand_in_the_rain_by_day_and_by_night(fleet_home, tmp_path, browser):
    """One robot per agent, its name over its head; the one that needs you has a beacon and the
    compass points to it. `?hour=13` is overcast day with the lamps out; `?hour=23` is night with the
    lamps lit. Around the plaza is a city: buildings, lamps, traffic, and on its sidewalks Poly Haven's
    scanned hydrants, bins and bags (CC0, `static/world/cc0/`), its walls and streets in their photo
    textures, its light from their skies. CI draws in SwiftShader, which the page draws on its lightest
    path (`soft`, the `low` quality): there the scene stays within 64 draw calls and 400,000 triangles,
    however many agents (the robots are instanced) and however much rain."""
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
        assert drawn["soft"] is True and drawn["quality"] == "low", drawn
        assert 0 < drawn["calls"] <= 64 and drawn["triangles"] < 400000, drawn
        town = drawn["town"]
        assert town["buildings"] > 40 and town["lights"] > 60 and town["cars"] > 10, town
        assert drawn["cc0"] == {"textures": 5, "skies": 2, "props": 9}, drawn["cc0"]
        assert town["scans"] > 10, town
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
def test_the_full_pipeline_draws_without_a_shader_error(fleet_home, tmp_path, browser):
    """`?quality=high` is what a desktop GPU gets: the scene in HDR, the wet street's mirror, ambient
    occlusion, bloom and the grade. SwiftShader draws it slowly, but it draws it: every shader compiles,
    the passes after the scene run, and the buildings, their windows and signs, the trees, the cars and
    the people are in it."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page = browser.new_page(viewport={"width": 640, "height": 360})
        problems = []
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.on("console", lambda m: problems.append(m.text[:300])
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.goto(f"http://127.0.0.1:{port}/world?t={token}&hour=22&quality=high&who=0", wait_until="domcontentloaded")
        page.wait_for_function(READY, arg=2, timeout=60000)
        # `calls` first: the shaders compile before the first frame (`vWarm`), and their draws count in
        # `passes` too.
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        page.wait_for_function("() => FleetWorld.inspect().passes > FleetWorld.inspect().calls", timeout=90000)
        info = _inspect(page)
        assert info["quality"] == "high", info
        town = info["town"]
        assert town["people"] > 20 and town["parked"] > 10 and town["cars"] > 10, town
        names = page.evaluate("() => { const n = []; vState.scene.traverse(m => { if (m.name) n.push(m.name); }); return n; }")
        # The pedestrians are the people's crowd (`world/people.js`): skinned, instanced, two levels of
        # detail a character, umbrellas in their hands.
        assert info["people"]["hero"] is True and info["town"]["crowd"] >= 2, (info["people"], info["town"])
        for part in ("city-glass", "city-signs", "city-brick", "city-curb", "street-trees", "crowd-0-0", "crowd-0-1",
                     "street-umbrellas", "car-body0"):
            assert part in names, (part, names)
        # And what reaches the screen is the frame. Resizing the canvas clears it, and the frame-rate
        # tuning used to resize it straight after a frame was drawn, in the same task: the frame shown
        # was the cleared canvas, black, for as long as the scale kept changing.
        # Three frames apart each time, on the page's own clock (its frame count), not a fixed wait.
        for _ in range(3):
            frames = _inspect(page)["frames"]
            page.wait_for_function(f"() => FleetWorld.inspect().frames > {frames + 2}", timeout=60000)
            w, h, bpp, rows = _png_pixels(page.screenshot())
            row = rows[h * 2 // 3]
            lit = sum(1 for i in range(0, w * bpp, bpp) if row[i] + row[i + 1] + row[i + 2] > 24)
            assert lit > w // 4, (lit, w, _inspect(page)["quality"])
        assert problems == [], problems
    finally:
        _stop(server)


TREES = """() => { const c = {}; vState.scene.traverse(m => { if (/^tree-/.test(m.name)) c[m.name] = m.count; }); return c; }"""


@pytest.mark.browser
def test_the_streets_are_planted_with_trees_drawn_near_and_far(fleet_home, tmp_path, browser):
    """The trees are a file (`static/world/trees/trees.glb`, grown by `tools/world/trees/`), not shapes
    the page builds: London planes and lindens along the avenues, young lindens in the planters round the
    office (eight outside, four inside),
    an instanced mesh for each tree, level of detail and part (bark, leaves). Near the eye a tree is
    drawn whole, further away with fewer and larger twigs, and the eye walking moves trees between the
    two. The `low` quality keeps the page's own trees."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13&quality=medium", n=1)
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        assert _inspect(page)["town"]["trees"] >= 12, _inspect(page)["town"]
        counts = page.evaluate(TREES)
        assert {"plane_0", "plane_1", "linden_0", "linden_1", "linden_2"} == {n.split("-")[1] for n in counts}, counts
        assert counts["tree-linden_2-0-1"] == 12, counts
        near = {k: v for k, v in counts.items() if k.endswith("-0-1") and k != "tree-linden_2-0-1"}
        far = {k: v for k, v in counts.items() if k.endswith("-1-1") and k != "tree-linden_2-1-1"}
        assert sum(far.values()) > 0 and sum(near.values()) > 0, counts
        page.evaluate("() => { vState.player.x = 0; vState.player.z = -100; }")
        frames = _inspect(page)["frames"]
        page.wait_for_function(f"() => FleetWorld.inspect().frames > {frames + 3}", timeout=60000)
        moved = page.evaluate(TREES)
        assert moved != counts, (counts, moved)
        assert sum(v for k, v in moved.items() if k.endswith("-1")) == sum(v for k, v in counts.items() if k.endswith("-1")), moved
        assert errors == [], errors
        page.close()

        page, errors = _open(browser, port, token, "&hour=13&quality=low", n=1)
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        assert page.evaluate(TREES) == {} and _inspect(page)["town"]["trees"] == 0
        names = page.evaluate("() => { const n = []; vState.scene.traverse(m => { if (m.isMesh) n.push(m.name); }); return n; }")
        assert "street-trees" in names, names
        assert errors == [], errors
    finally:
        _stop(server)


CARS = """() => { const c = {}; vState.scene.traverse(m => { if (/^car-/.test(m.name)) c[m.name] = m.count; }); return c; }"""


@pytest.mark.browser
def test_the_traffic_is_cars_from_a_file_drawn_near_and_far(fleet_home, tmp_path, browser):
    """The cars are a file (`static/world/cars/cars.glb`, lofted by `tools/world/cars/`): a sedan, a
    hatchback, an SUV and a van, each drawn near with its body, glass, trim and lamps and far as one
    mesh and its lamps, every car painted its own colour. Every car, driving or parked, is drawn once,
    near or far. The `low` quality keeps the page's own two."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13&quality=medium", n=1)
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        town = _inspect(page)["town"]
        counts = page.evaluate(CARS)
        near = {f"car-{p}{t}" for p in ("body", "glass", "trim", "lamp") for t in range(4)}
        assert set(counts) == near | {f"car-{p}{t}-far" for p in ("body", "lamp") for t in range(4)}, counts
        bodies = sum(v for k, v in counts.items() if k.startswith("car-body"))
        assert bodies == town["cars"] + town["parked"] and bodies > 20, (bodies, town)
        assert sum(counts[f"car-body{t}"] for t in range(4)) == sum(counts[f"car-glass{t}"] for t in range(4)), counts
        assert errors == [], errors
        page.close()

        page, errors = _open(browser, port, token, "&hour=13&quality=low", n=1)
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        assert set(page.evaluate(CARS)) == {f"car-{p}{t}" for p in ("body", "glass", "trim", "lamp") for t in range(2)}
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


@pytest.mark.browser
def test_you_choose_who_you_are_and_the_world_keeps_it(fleet_home, tmp_path, browser):
    """A first visit opens on the character picker: looks that between them span skin tones, hair
    textures, a headscarf and a wrap, glasses, facial hair, builds and a wheelchair, every one of them
    changeable. The choice is kept in this browser, and the next visit opens straight into the rain."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13", n=1, who="")
        # The check polls on animation frames, and the first frames compile the realistic character's
        # skinned shaders, which SwiftShader takes seconds over when the suite runs in parallel.
        page.wait_for_function("() => FleetWorld.inspect().who && !document.getElementById('wwho').hidden", timeout=60000)
        presets = page.eval_on_selector_all("#wpresets .ww-choice", "els => els.map(e => e.textContent)")
        assert len(presets) >= 10 and {"headscarf", "wrap", "locs", "wheelchair"} <= set(presets), presets
        rows = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#wopts .ww-row')]
            .map(r => [r.getAttribute('aria-label'), r.querySelectorAll('.ww-choice').length]))""")
        assert rows["skin"] >= 8 and rows["hair"] >= 9 and rows["moves by"] == 2, rows
        assert all(n >= 2 for n in rows.values()), rows

        page.click("#wpresets .ww-choice >> text=wheelchair")
        page.wait_for_function("() => FleetWorld.inspect().hero.seated && FleetWorld.inspect().hero.wheels", timeout=10000)
        page.click("#wopts .ww-row[aria-label='skin'] .ww-choice >> nth=0")
        page.click("#wopts .ww-row[aria-label='glasses'] .ww-choice >> text=round")
        look = _inspect(page)["look"]
        assert look["move"] == "wheelchair" and look["glasses"] == "round" and look["skin"] == "#3b2219", look
        assert page.eval_on_selector("#wopts .ww-row[aria-label='glasses'] .ww-choice[aria-checked='true']",
                                     "e => e.textContent") == "round"
        page.click("#wwhodone")
        page.wait_for_function("() => !FleetWorld.inspect().who && document.getElementById('wwho').hidden", timeout=10000)
        assert _inspect(page)["view"] == "third" and _inspect(page)["hero"]["visible"] is True

        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(READY, arg=1, timeout=30000)
        again = _inspect(page)
        assert again["who"] is False and again["look"] == look, "kept in this browser"
        assert errors == [], errors
    finally:
        _stop(server)


def _standin_kept(folder):
    """The operator's own people folder holding the stand-in with its skin kept in its authored colour
    (`tint: false`) and given a packed occlusion-roughness map whose blue channel says where light shows
    through (`thin`), as `tools/world/people` writes for a realistic export. The map is the skin's own
    normal map's image: what is held is that the page reads it, not what it holds. The crowd file is
    left out, so it comes from the package."""
    import json
    import shutil
    import struct

    src = os.path.join(STATIC, "world", "people")
    raw = open(os.path.join(src, "standin.glb"), "rb").read()
    n = struct.unpack("<I", raw[12:16])[0]
    doc, rest = json.loads(raw[20:20 + n]), raw[20 + n:]
    for m in doc["materials"]:
        if (m.get("extras") or {}).get("role") == "skin":
            m["extras"]["tint"] = False
            m["extras"]["thin"] = True
            tex = (m.get("normalTexture") or m["pbrMetallicRoughness"]["baseColorTexture"])["index"]
            m["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": tex}
            m["occlusionTexture"] = {"index": tex}
    body = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    body += b" " * (-len(body) % 4)
    folder.mkdir()
    (folder / "standin.glb").write_bytes(raw[:8] + struct.pack("<II", 20 + len(body) + len(rest), len(body)) + b"JSON"
                                         + body + rest)
    shutil.copy(os.path.join(src, "people.json"), folder / "people.json")


@pytest.mark.browser
def test_agents_are_people_where_the_crowd_is_drawn(fleet_home, tmp_path, browser):
    """Agents become people (docs/fleet-world.md, decided 2026-10-05): where pedestrians are drawn (WebGL 2,
    every tier but `low`), each agent is one of the crowd's characters standing in the robot's place, its
    ring at its feet in its state's colour, the one that needs you still under its beacon, and no robot.
    It faces you once you are within 6 m and presents while you talk to it. The robot stays where no crowd
    is drawn (`test_agents_stand_in_the_rain_by_day_and_by_night`, the `low` path)."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    count = """() => { const out = { agents: 0, shell: -1 }; vState.scene.traverse(o => {
      if (/^agent-/.test(o.name)) out.agents += o.count; if (o === vState.parts.shell) out.shell = o.count; }); return out; }"""
    try:
        page, errors = _open(browser, port, token, "&hour=13&quality=high")
        page.wait_for_function("() => FleetWorld.inspect().people.agents === 2", timeout=120000)
        drawn = page.evaluate(count)
        assert drawn == {"agents": 2, "shell": 0}, drawn
        assert _inspect(page)["beacons"] == 1
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_agents_go_where_their_state_puts_them(fleet_home, tmp_path, browser):
    """Where the agents are people, their state places them in the office (docs/fleet-world.md, decided
    2026-10-05, and the operator's office, 2026-10-06): a working one types at its desk; the one that
    needs you stands up beside its desk, under its beacon; an idle one sits back at its desk; a done one
    walks out through the nearest door and is gone, its label with it. `FleetWorld.step` moves the
    agents as it moves you, so 30 s of the world pass at once."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    busy = make_project(tmp_path / "busy", phase="build", ticket="RDSD-8")
    Registry().add(busy, name="busy")
    E.append("busy", [E.event("busy", "started", {"prompt": "Ticket RDSD-8", "session": ""}, ticket="RDSD-8"),
                      E.event("busy", "turn_started", {"turn": "0"}, ticket="RDSD-8")])
    gone = make_project(tmp_path / "gone", phase="done")
    Registry().add(gone, name="gone")
    server, token, port = _serve()
    modes = "() => Object.fromEntries(FleetWorld.inspect().agents.map(a => [a.repo, [a.state, a.mode, Math.hypot(a.x, a.z)]]))"
    try:
        page, errors = _open(browser, port, token, "&hour=13&quality=high", n=4)
        page.wait_for_function("() => FleetWorld.inspect().people.agents >= 3", timeout=120000)
        page.evaluate("() => FleetWorld.step(30)")
        got = page.evaluate(modes)
        R = page.evaluate("() => vState.radius")
        assert got["busy"][1] == "type" and got["alpha"][1] == "sit" and got["gone"][1] == "gone", got
        assert got["asks"][1] == "stand" and abs(got["asks"][2] - (R - 0.95)) < 0.01, (got, R)
        assert abs(got["busy"][2] - (R - 0.64)) < 0.01 and abs(got["alpha"][2] - (R - 0.64)) < 0.01, (got, R)
        assert got["busy"][0] == "running" and got["gone"][0] == "done", got
        assert got["gone"][2] > page.evaluate("() => vState.wall[0]"), got
        assert page.evaluate("() => FleetWorld.inspect().people.agents") == 3
        tags = page.evaluate("() => Object.fromEntries([...document.querySelectorAll('#wlabels .wtag')].map(t => [t.querySelector('.wtag-name').textContent, t.hidden]))")
        assert tags["gone"] is True, tags
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_agents_work_in_an_office_where_you_take_over_their_screen(fleet_home, tmp_path, browser):
    """The operator, 2026-10-06: "Let's create an office building with the humans as agents and when we
    walk up to them we have the opportunity to 'take over their screen' which would bring us back to the
    Desk/Chat screen." The middle of the district is a glass office: a desk a agent, each with a screen
    showing what its agent is doing, glass all round with a door to each avenue, no rain under the roof.
    You walk in and out by the doors, never through the glass. Near an agent, T (X on a pad) or the
    panel's button takes over its screen: the chat, on that agent."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13&quality=medium")
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        office = page.evaluate("""() => ({ desks: vState.desks.meshes.map(m => m.count), wall: vState.wall,
                                           roof: vState.parts.rain.material.uniforms.uRoof.value.toArray(),
                                           screens: Object.keys(vState.desks.drawn).length })""")
        assert office["desks"] == [2, 2, 2] and office["screens"] == 2, office
        G, half = office["wall"][0], office["wall"][1]
        assert office["roof"][2] > G and office["roof"][3] > 3, office
        page.evaluate("() => FleetWorld.hold(true)")
        out = page.evaluate(f"""() => {{ vState.player.x = Math.cos(0.75) * {G - 1}; vState.player.z = Math.sin(0.75) * {G - 1}; vState.player.yaw = Math.atan2(-Math.cos(0.75), -Math.sin(0.75));
                                       vState.keys = {{ KeyW: true }}; FleetWorld.step(3); vState.keys = {{}}; return Math.hypot(vState.player.x, vState.player.z); }}""")
        assert out < G, (out, G)
        door = page.evaluate(f"""() => {{ vState.player.x = {G - 1}; vState.player.z = 0; vState.player.yaw = -Math.PI / 2;
                                        vState.keys = {{ KeyW: true }}; FleetWorld.step(3); vState.keys = {{}}; return Math.hypot(vState.player.x, vState.player.z); }}""")
        assert door > G + 1, (door, G)
        page.evaluate("() => { var a = vState.agents.get('asks'); vState.player.x = 0; vState.player.z = 0; vState.player.yaw = Math.atan2(-a.x, -a.z); }")
        page.evaluate("() => FleetWorld.hold(false)")
        page.keyboard.down("KeyW")
        assert _until_near(page, "asks") == "asks"
        page.keyboard.up("KeyW")
        assert "T or X" in page.text_content("#wprompt")
        page.keyboard.press("KeyE")
        page.wait_for_function("() => !document.getElementById('wpanel').hidden")
        assert page.text_content("#wtake").strip() == "take over its screen"
        with page.expect_navigation():
            page.click("#wtake")
        assert "/chat" in page.url and page.url.endswith("#asks"), page.url
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_realistic_character_keeps_its_own_colours_and_maps(fleet_home, tmp_path, browser, monkeypatch):
    """The stand-in is dyed by the look: every skin part takes the chosen tone and reads no maps but its
    colour and normal. A realistic export's kept parts are not dyed (their colour stays white, so the
    texture shows as made), read their roughness and occlusion from the packed map, and the skin's
    scattering shader compiles, with the light through its thin parts; the parts it did not keep are
    still dyed."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()

    def drawn():
        page = browser.new_page(viewport={"width": 640, "height": 360})
        problems = []
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.on("console", lambda m: problems.append(m.text[:300])
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.goto(f"http://127.0.0.1:{port}/world?t={token}&hour=13&who=0", wait_until="domcontentloaded")
        page.wait_for_function(READY, arg=2, timeout=60000)
        page.wait_for_function("() => FleetWorld.inspect().calls > 0", timeout=90000)
        frames = _inspect(page)["frames"]
        page.wait_for_function(f"() => FleetWorld.inspect().frames > {frames + 2}", timeout=60000)
        parts = _inspect(page)["people"]["parts"]
        page.close()
        assert problems == [], problems
        return parts

    try:
        shipped = drawn()
        skin = [p for p in shipped if p["role"] == "skin"]
        assert skin and all(p["tinted"] and not p["rough"] and not p["ao"] and not p["thin"] and p["colour"] != "ffffff"
                        for p in skin), shipped

        _standin_kept(tmp_path / "own")
        monkeypatch.setenv(S.PEOPLE_DIR_ENV, str(tmp_path / "own"))
        kept = drawn()
        skin = [p for p in kept if p["role"] == "skin"]
        assert skin and all(not p["tinted"] and p["rough"] and p["ao"] and p["thin"] and p["colour"] == "ffffff"
                        for p in skin), kept
        assert any(p["tinted"] for p in kept if p["role"] in ("top", "bottom")), kept
    finally:
        _stop(server)


@pytest.mark.browser
def test_your_character_walks_turns_to_the_agent_and_presents(fleet_home, tmp_path, browser, spawns):
    """In the third person the character is where you are and faces where you face; its legs swing as
    it walks and settle when it stops; talking to an agent turns it to the agent and opens its arm, the
    pose of the character it was modelled on. V switches to the first person, which hides it. With a
    controller, Start opens the picker, the D-pad moves through it, A chooses and B closes it."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&hour=13")
        page.evaluate(PAD)
        page.evaluate("() => FleetWorld.hold(true)")
        hero = _inspect(page)["hero"]
        assert hero["visible"] and not hero["seated"] and abs(hero["legL"]) < 0.01, hero

        # The character is a skinned human (`world/people.js`, the stand-in in `static/world/people/`)
        # whose legs follow a gait: the thigh passes through the vertical twice a stride, so the swing
        # is read over a stride, a tenth of a second of walking at a time, never at one instant.
        assert hero["kind"] == "skinned", hero
        page.keyboard.down("KeyW")
        swing = 0
        for _ in range(12):
            frames = _inspect(page)["frames"]
            page.evaluate("() => FleetWorld.step(0.1)")
            page.wait_for_function(f"() => FleetWorld.inspect().frames > {frames + 1}", timeout=10000)
            swing = max(swing, abs(_inspect(page)["hero"]["legL"]))
        assert swing > 0.2, swing
        page.keyboard.up("KeyW")
        page.evaluate("() => FleetWorld.step(0.5)")
        page.wait_for_function("() => Math.abs(FleetWorld.inspect().hero.legL) < 0.05", timeout=10000)
        player = _inspect(page)["player"]
        hero = _inspect(page)["hero"]
        assert abs(hero["x"] - player["x"]) < 1e-6 and abs(hero["z"] - player["z"]) < 1e-6 and abs(hero["yaw"] - player["yaw"]) < 1e-6

        page.keyboard.down("KeyW")
        assert _until_near(page, "asks") == "asks"
        page.keyboard.up("KeyW")
        page.keyboard.press("KeyE")
        page.wait_for_function("() => FleetWorld.inspect().open === 'asks' && FleetWorld.inspect().hero.armR > 0.8",
                               timeout=10000)
        page.keyboard.press("Escape")
        page.wait_for_function("() => FleetWorld.inspect().hero.armR < 0.4", timeout=10000)

        page.keyboard.press("KeyV")
        assert _inspect(page)["view"] == "first"
        page.wait_for_function("() => FleetWorld.inspect().hero.visible === false", timeout=10000)
        page.keyboard.press("KeyV")
        assert _inspect(page)["view"] == "third"

        def tap(button):
            page.evaluate(f"() => {{ window.__press({button}, true); FleetWorld.step(1 / 60);"
                          f" window.__press({button}, false); FleetWorld.step(1 / 60); }}")

        tap(9)
        assert _inspect(page)["who"] is True
        first = page.evaluate("() => document.activeElement.textContent")
        tap(15)
        tap(0)
        chosen = page.evaluate("() => document.querySelector('#wpresets .ww-choice[aria-checked=true]').textContent")
        assert chosen != first and chosen == "curls", (first, chosen)
        assert _inspect(page)["look"]["hair"] == "curls"
        tap(1)
        assert _inspect(page)["who"] is False
        assert errors == [], errors
    finally:
        _stop(server)
