"""`/map` (#405): the fleet as an accessible tree (docs/fleet-map.md §The page).

The first two tests are plain HTTP. The rest drive the page in Chromium: one browser for the
module, a fresh page per test, a server per test. Every wait is on a condition.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import approval as AP
from agentdata.fleet import events as E
from agentdata.fleet import fleetmap as M
from agentdata.fleet import serve as S
from agentdata.fleet import supervisor as SV
from agentdata.fleet.registry import AGENT_ENV, Registry

from desk_waits import WATCH
from test_fleet import make_project
from test_fleet_ink import _serve, _stop
from test_fleet_map import _worktree, fleet_home, row, snap  # noqa: F401

READY = "() => !!window.FleetMap && FleetMap.graph !== null"
#: The phone page (#581) as it lands: its window, ink, width, target heights, rows and which say they need you.
PHONE_LOOK = """() => { const d = document.documentElement, li = [...document.querySelectorAll('#agents > li')];
  return { w: FleetPhone.w, inkOff: document.body.classList.contains('ink-off'),
           canvas: document.querySelectorAll('canvas').length, sw: d.scrollWidth, cw: d.clientWidth,
           targets: [...document.querySelectorAll('#agents .pick, a, button')].filter(e => e.offsetParent)
             .map(e => e.getBoundingClientRect().height),
           rows: li.map(e => e.dataset.rowkey),
           needs: li.filter(e => e.classList.contains('needs-human')).map(e => e.dataset.rowkey),
           told: FleetPhone.rows.filter(r => r.needs_human).map(r => r.repo) }; }"""
#: Every write to the phone page from now, and the ticks and refreshes so far.
PHONE_WATCH = """() => { """ + WATCH + """ window.__refreshes = FleetPhone.stream.refreshes;
  window.__mobs = __deskWaits.watch(document.documentElement);
  return FleetPhone.stream.ticks; }"""


def _fleet(tmp_path):
    """luna, its worktree luna-hotfix, and an unrelated uat."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(main)
    Registry().add(_worktree(tmp_path, main))
    Registry().add(make_project(tmp_path / "uat", ticket="RDSD-9"))


def _get(port, path, token=None):
    sep = "&" if "?" in path else "?"
    url = f"http://127.0.0.1:{port}{path}" + (f"{sep}t={token}" if token else "")
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode("utf-8")


# --------------------------------------------------------------------------------- plain HTTP


def test_map_is_served_with_its_assets_tokened_and_keeps_ink_off(fleet_home, tmp_path):
    server, token, port = _serve()
    try:
        html = _get(port, "/map", token)
        for asset in ("app.css", "map.css", "common.js", "map/map.js"):
            assert f'"/static/{asset}?t={token}"' in html, asset
        assert '<body class="ink-off" data-ink-shell="browser"' in html, html
        assert html.count("ink-off") == 1, html
        for asset in ("map.css", "map/map.js"):
            assert _get(port, f"/static/{asset}", token)
    finally:
        _stop(server)


def test_open_page_map_lands_on_the_map(fleet_home, tmp_path):
    server, token, port = _serve()
    try:
        class Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(Stay)
        with pytest.raises(urllib.error.HTTPError) as got:
            opener.open(f"http://127.0.0.1:{port}/open?page=map&w=side", timeout=10)
        assert got.value.code == 302
        assert got.value.headers["Location"] == f"/map?t={token}&w=side"
    finally:
        _stop(server)


# -------------------------------------------------------------------------------- the browser


@pytest.fixture()
def browser(desk_browser):
    """The worker's shared Chromium (tests/desk_harness.py); this test's contexts close when it ends."""
    return desk_browser


def _open(browser, port, token, extra="", viewport=(1400, 900)):
    page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/map?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(READY, timeout=15000)
    return page, errors


@pytest.mark.browser
def test_the_tree_lists_the_fleet_and_a_keyboard_walk_opens_a_checkout_on_the_desk(
        browser, fleet_home, tmp_path):
    _fleet(tmp_path)
    S.update_window("side", open="luna")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&w=side")
        # The map's own stream is a window on its network (#404, #406): the refetch that follows the
        # first `desk` and `polls` frames adds it, and the first poll pass, to the words. The copy to
        # compare with is read once the page has drawn its own window as connected, not before.
        page.wait_for_function("""() => !!document.querySelector('#maptree [data-node="w:side"].connected')""",
                               timeout=15000)
        graph = json.loads(_get(port, "/api/map", token))
        tree = page.evaluate("""() => [...document.querySelectorAll('#maptree [role=treeitem]')]
            .map(li => ({id: li.dataset.node, cls: li.className, say: li.querySelector('.say').textContent,
                         depth: (() => { let d = 0, u = li; while ((u = u.parentElement.closest('[role=treeitem]'))) d++; return d; })()}))""")
        by = {n["id"]: n for n in tree}
        # The network (#404) is the last root, in the graph's words (docs/fleet-map.md §The page).
        assert [n["id"] for n in tree if n["depth"] == 0] == ["p:luna", "p:uat", "n:network"], tree
        assert by["n:network"]["say"] == graph["network"]["says"], by["n:network"]
        assert [n["id"] for n in tree if n["depth"] == 1 and n["id"].startswith("c:")] == \
            ["c:luna", "c:luna-hotfix", "c:uat"], tree
        assert "worktree" in by["c:luna-hotfix"]["cls"].split() and "main" in by["c:luna"]["cls"].split()
        for c in graph["checkouts"]:
            a = c["agent"]
            got = by[a["id"]]
            assert got["depth"] == 2 and got["say"] == a["says"], got
            assert {f"kind-{a['kind']}", f"state-{a['state']}"} <= set(got["cls"].split()), got
        assert page.text_content("#mapsays") == graph["says"]
        assert page.get_attribute("#mapback", "href").endswith("/?t=" + token + "&w=side")

        # Tab reaches the back link, then the tree; the focused item's words carry the outline.
        page.keyboard.press("Tab")
        page.wait_for_function("() => document.activeElement.id === 'mapback'", timeout=5000)
        page.keyboard.press("Tab")
        page.wait_for_function("() => document.activeElement.dataset.node === 'p:luna'", timeout=5000)
        outline = page.evaluate("""() => { const s = getComputedStyle(document.activeElement.querySelector('.say'));
                                           return [s.outlineStyle, s.outlineWidth]; }""")
        assert outline[0] != "none" and outline[1] != "0px", outline
        page.keyboard.press("ArrowDown")
        page.wait_for_function("() => document.activeElement.dataset.node === 'c:luna'", timeout=5000)
        page.keyboard.press("ArrowRight")
        page.wait_for_function("() => document.activeElement.dataset.node === 'a:luna'", timeout=5000)
        page.keyboard.press("ArrowDown")
        page.wait_for_function("() => document.activeElement.dataset.node === 'c:luna-hotfix'",
                               timeout=5000)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/map" not in u and "w=side" in u, timeout=15000)
        assert S.desk_state()["windows"]["side"]["open"] == "luna-hotfix"
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


CONTRAST = """() => {
  function rgb(s) { const m = s.match(/[\\d.]+/g).map(Number); return m.length > 3 ? m : m.concat([1]); }
  function lum(c) {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  }
  function ground(el) {
    for (let u = el; u; u = u.parentElement) {
      const c = rgb(getComputedStyle(u).backgroundColor);
      if (c[3] > 0) return c;
    }
    return [255, 255, 255, 1];
  }
  const els = [...document.querySelectorAll('#maptree .say, header h1, #mapsays, #mapback')];
  return els.map(el => {
    const a = lum(rgb(getComputedStyle(el).color)), b = lum(ground(el));
    return { what: el.id || el.tagName + ':' + el.textContent.slice(0, 30),
             ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
  });
}"""


@pytest.mark.browser
@pytest.mark.parametrize("palette", ["none", "sand"])
def test_every_word_on_the_map_reads_at_four_and_a_half_to_one(browser, fleet_home, tmp_path,
                                                                 palette):
    _fleet(tmp_path)
    (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": {"default": palette}}),
                                                encoding="utf-8")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token)
        seen = page.evaluate(CONTRAST)
        assert len(seen) >= 3 + 4, seen
        low = [s for s in seen if s["ratio"] < 4.5]
        assert low == [], low
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


def _synthetic():
    """A graph from `fleetmap.graph` of rows it would never see yet (sub-agents are #402's), with
    the branches (#403) and network (#404) keys drawn from the graph's documented shape."""
    g = M.graph(snap(row("luna", subagents=2), row("uat", stale={"stale": True}, supervised=True)))
    g["projects"][0]["branches_says"] = "2 branches, 1 never reached main"
    g["projects"][0]["branches"] = [
        {"id": "b:luna:main", "says": "main · current in luna", "unmerged": False,
         "carrying": False, "current_in": ["c:luna"]},
        {"id": "b:luna:feature/x", "says": "feature/x · never reached main", "unmerged": True,
         "carrying": True, "current_in": []}]
    g["network"] = {
        "says": "the network", "server": {"id": "n:server", "says": "the server"},
        "windows": [{"id": "w:main", "says": "window main", "connected": True}],
        "sources": [{"id": "s:jira", "says": "jira", "cells": [{"ok": True}, {"ok": False}]}],
        "approvals": {"id": "n:approvals", "says": "1 approval", "pending": 1},
        "install": {"id": "n:install", "says": "the install"}}
    return g


OBSERVE = """() => { """ + WATCH + """ if (window.__obs) window.__obs.stop();
  window.__obs = __deskWaits.watch(document.getElementById('maptree')); }"""
#: What the watch `OBSERVE` put on the tree has seen since.
MUTS = "() => window.__obs.count()"


@pytest.mark.browser
def test_redraws_of_one_graph_touch_nothing_and_keep_what_the_operator_opened(
        browser, fleet_home, tmp_path):
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token)
        g = _synthetic()
        page.evaluate("g => FleetMap.draw(g)", g)
        assert page.evaluate("() => FleetMap.paused") is True
        page.evaluate(OBSERVE)
        page.evaluate("g => FleetMap.draw(g)", g)
        assert page.evaluate(MUTS) == 0

        agents = page.evaluate("""() => [...document.querySelectorAll('#maptree [data-node^="a:"]')]
            .map(li => ({sub: +li.dataset.subagents, stale: li.classList.contains('stale'),
                         say: li.querySelector('.say').textContent}))""")
        marked = [a for a in agents if a["sub"] > 0 or a["stale"]]
        assert len(marked) == 2, agents
        assert all("sub-agent" in a["say"] or "older install" in a["say"] for a in marked), marked

        classes = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#maptree [role=treeitem]')]
            .map(li => [li.dataset.node, li.className]))""")
        assert "unmerged" in classes["b:luna:feature/x"] and "carrying" in classes["b:luna:feature/x"]
        assert "is-current" in classes["b:luna:main"]
        assert "connected" in classes["w:main"] and "grey" in classes["s:jira"]
        assert "pending" in classes["n:approvals"]
        order = page.evaluate("""() => [...document.querySelectorAll('#maptree > li')].map(li => li.dataset.node)""")
        assert order == ["p:luna", "p:uat", "n:network"], order

        group = '#maptree [data-node="bs:luna"]'
        assert page.get_attribute(group, "aria-expanded") == "false"
        assert not page.is_visible('[data-node="b:luna:main"]')
        page.click(group + " > .say")
        page.wait_for_function(f"() => document.querySelector('{group}').getAttribute('aria-expanded') === 'true'",
                               timeout=5000)
        assert page.is_visible('[data-node="b:luna:main"]')
        page.evaluate(OBSERVE)
        for _ in range(3):
            page.evaluate("g => FleetMap.draw(g)", g)
        assert page.evaluate(MUTS) == 0
        assert page.get_attribute(group, "aria-expanded") == "true"
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


# Every tree row's height on the glass, in whole px.
SAY_HEIGHTS = """() => [...document.querySelectorAll('#maptree .say')].filter(s => s.offsetParent)
  .map(s => Math.round(s.getBoundingClientRect().height))"""


@pytest.mark.browser
def test_ink_off_draws_no_canvas_and_a_narrow_scene_stacks_the_tree_over_the_stage(
        browser, fleet_home, tmp_path, monkeypatch):
    """The map with ink off, the map's scene stacked at 480 px, the map under a finger (#578), and the
    phone page (#581): /m at 390x844 under a finger lists the agents from /api/attention, opens one
    on a tap, and approves, denies, replies and answers through the four POSTs, each answer read out
    in the server's words; idle, it writes nothing over one stream tick."""
    _fleet(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "&ink=off")
        assert page.evaluate("() => document.querySelectorAll('canvas').length") == 0
        assert page.evaluate("() => document.body.classList.contains('ink-off')")
        mouse = page.evaluate(SAY_HEIGHTS)
        page.close()

        page, errors = _open(browser, port, token, viewport=(480, 800))
        page.evaluate("() => document.body.classList.add('map-scene')")
        page.wait_for_function("() => document.getElementById('mapstage').getBoundingClientRect().height > 0",
                               timeout=5000)
        box = page.evaluate("""() => { const d = document.documentElement, n = document.querySelector('#map > nav'),
                                             s = document.getElementById('mapstage');
          return {sw: d.scrollWidth, cw: d.clientWidth, nav: n.getBoundingClientRect().width,
                  stage: s.getBoundingClientRect().height,
                  inkOff: document.body.classList.contains('ink-off')}; }""")
        assert box["sw"] <= box["cw"], box
        assert box["nav"] >= box["cw"] - 1, box
        assert box["stage"] >= 240, box
        assert box["inkOff"], box
        assert mouse and set(mouse) == {21}, f"a mouse's tree is 21 px rows at 1400 px: {mouse}"
        assert not errors, errors
        page.close()

        # A finger (#578): 44 px rows, and a tap on a checkout opens it on the desk as Enter does,
        # while a tap on a project, or on a checkout's twisty, still folds it.
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = phone.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/map?t={token}&w=side", wait_until="domcontentloaded")
        page.wait_for_function(READY, timeout=15000)
        rows = page.evaluate(SAY_HEIGHTS)
        wide = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        assert rows and min(rows) >= 44, f"under a finger every row is 44 px: {rows}"
        assert wide[0] == wide[1], wide
        project = '#maptree [data-node="p:uat"]'
        assert page.get_attribute(project, "aria-expanded") == "true"
        page.tap(project + " > .say")
        page.wait_for_function(f"() => document.querySelector('{project}').getAttribute('aria-expanded') === 'false'",
                               timeout=5000)
        assert "/map" in page.url, "a tap on a project opened something"
        checkout = '#maptree [data-node="c:luna"]'
        page.tap(checkout + " > .say", position={"x": 14, "y": 22})
        page.wait_for_function(f"() => document.querySelector('{checkout}').getAttribute('aria-expanded') === 'false'",
                               timeout=5000)
        assert "/map" in page.url, "a tap on the twisty opened the checkout"
        page.tap(checkout + " > .say")
        page.wait_for_url(lambda u: "/map" not in u and "w=side" in u, timeout=15000)
        assert S.desk_state()["windows"]["side"]["open"] == "luna"
        assert not errors, errors
        phone.close()

        # The phone page (#581): two approvals waiting on luna, a question on uat, and `send` stubbed where the
        # server calls it, so a reply and an answer are answered without a CLI.
        monkeypatch.setenv(AGENT_ENV, "luna")
        waiting = {AP.require(kind, summary, {"key": "RDSD-1"}, ticket="RDSD-1", timeout=0).id
                   for kind, summary in (("jira-transition", "RDSD-1: In Progress -> In Review"),
                                         ("jira-comment", "RDSD-1: say it is done"))}
        monkeypatch.delenv(AGENT_ENV)
        E.append("uat", [E.event("uat", "question_opened", {"question": "which sprint?", "id": "q1",
                                                            "choices": ["this one", "the next"]}, ticket="RDSD-9")])
        sent = []
        monkeypatch.setattr(SV, "send", lambda repo, message, **k: sent.append((repo, message)) or {"pid": 4242})
        # A 6 s beat for the stream /m opens, not 15 s: still longer than the poller's floor, so the idle
        # window below spans a poll as well as a tick.
        monkeypatch.setattr(S, "HEARTBEAT_S", 6.0)
        assert S.POLL_EVERY_S < S.HEARTBEAT_S
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = phone.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/m?t={token}", wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.FleetPhone && FleetPhone.rows.length === 3"
                               " && FleetPhone.stream.ticks >= 1 && !FleetPhone.stream.busy", timeout=20000)
        look = page.evaluate(PHONE_LOOK)
        assert look["w"] == "phone" and look["inkOff"] and look["canvas"] == 0, look
        assert look["sw"] == look["cw"] and min(look["targets"]) >= 44, look
        assert look["rows"] == sorted(look["rows"]) == ["luna", "luna-hotfix", "uat"], look
        assert look["needs"] == look["told"] and "uat" in look["needs"], look
        # Idle: nothing written from here to the stream's next tick.
        ticks = page.evaluate(PHONE_WATCH)
        page.wait_for_function("t => FleetPhone.stream.ticks > t", arg=ticks, timeout=30000)
        idle = page.evaluate("() => { window.__mobs.stop(); return { n: window.__mobs.n,"
                             " refreshes: FleetPhone.stream.refreshes - window.__refreshes }; }")
        assert idle == {"n": 0, "refreshes": 0}, f"an idle /m wrote to the page: {idle}"

        def said(action, go):
            """Tap `go`, and wait for the live line to say what the server answered `action`."""
            with page.expect_response(lambda r: r.url.split("?")[0].endswith("/api/" + action)) as got:
                page.tap(go)
            answer = got.value.json()
            words = (" · ".join(w for w in (answer.get("action"), answer.get("decision") or answer.get("repo")) if w)
                     if answer["ok"] else answer["error"] + (" — " + answer["hint"] if answer.get("hint") else ""))
            page.wait_for_function("w => document.getElementById('said').textContent === w", arg=words,
                                   timeout=10000)
            return answer

        # The row's own order (`approval_id` is the first of `approvals`), which the sheet follows.
        first, second = page.evaluate("() => FleetPhone.rows.find(r => r.repo === 'luna').approvals")
        assert {first, second} == waiting
        page.tap('#agents [data-rowkey="luna"] .pick')
        page.wait_for_function(f"() => document.getElementById('approval').dataset.id === '{first}'"
                               " && !document.getElementById('open').hidden", timeout=10000)
        assert page.evaluate("() => getComputedStyle(document.getElementById('agents')).display") == "none"
        page.fill("#reason", "looks right")
        assert said("approve", "#approve")["decision"] == "approved"
        page.wait_for_function(f"() => document.getElementById('approval').dataset.id === '{second}'", timeout=10000)
        assert said("deny", "#deny")["ok"] is False                       # no reason: the server's refusal
        page.fill("#reason", "not yet")
        assert said("deny", "#deny")["decision"] == "denied"
        assert [AP.read_decision(i)["decision"] for i in (first, second)] == ["approved", "denied"]
        page.fill("#message", "ship it")
        said("send", "#send")
        page.tap("#back")
        page.tap('#agents [data-rowkey="uat"] .pick')
        page.wait_for_function("() => !document.getElementById('asks').hidden", timeout=10000)
        page.tap("#asklist .ask-choice")
        said("answer", "#answer")
        assert sent[0] == ("luna", "ship it") and sent[1][0] == "uat" and "this one" in sent[1][1], sent
        assert not errors, errors
        phone.close()
    finally:
        _stop(server)
