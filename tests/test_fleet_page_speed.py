"""Page speed (the operator, 2026-10-06: "work on optimizing the load time when clicking between chat,
desk, and world. We're aiming for ~200ms loads. Right now we're at several seconds").

And then (2026-10-06): "aim for 50ms load times, especially when actually interacting with agents
(the time from clicking send, or pressing Enter, to the agent 'running')".

What is held here is what a test can hold of it: that the desk asks the browser to prerender the
world while the pointer rests on its link, and never under test automation; and that a `send` does
no more than it must before it answers -- a running agent's pid is asked of the kernel, the row it
answers with is that checkout's alone and built once, a page may take the answer as soon as the turn
is running and fetch the row itself, the launch tier sums the month only when it has to, and a
request reads each file and parses each stream once. The server's other half (static files kept and
revalidated, a poll that finds nothing writes nothing, the store read once per change) is in
`test_fleet_serve.py`, `test_fleet_events.py` and `test_fleet_sessions.py`; the world's boot is
measured, not tested, and docs/fleet-world.md says how.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.request

import pytest

from agentdata import textio
from agentdata.fleet import credits, events as E, serve as S, spend, supervisor

from test_fleet_desk_switcher import _repo, spawns  # noqa: F401 - fixture
from test_fleet_ink import _repos, _serve, _stop, fleet_home  # noqa: F401 - fixture


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


@pytest.mark.browser
def test_the_desk_prerenders_the_world_on_a_hover_but_never_under_automation(fleet_home, tmp_path, browser):
    """The operator, 2026-10-06: "We're aiming for ~200ms loads" between the chat, the desk and the
    world. The world takes a second to build and compile; the desk asks Chrome to prerender it while
    the pointer rests on its link (`prerender("#worldbtn")`, a `moderate` document rule), so the click
    shows a world that is already drawn. Only the world's link, never under test automation (a test
    that rests the pointer on a link must not build a second world), and only in a browser with
    speculation rules."""
    _repos(tmp_path, ["alpha"])
    server, token, port = _serve()
    try:
        rules = []
        for automated in (True, False):
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            if not automated:
                page.add_init_script("Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false })")
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function("() => !!document.getElementById('worldbtn').getAttribute('href')", timeout=15000)
            supported = page.evaluate("() => !!(HTMLScriptElement.supports && HTMLScriptElement.supports('speculationrules'))")
            rules.append(page.evaluate("() => [...document.querySelectorAll('script[type=speculationrules]')].map(s => s.textContent)"))
            page.close()
        assert rules[0] == [], "a rule was written under test automation"
        if supported:
            assert len(rules[1]) == 1, rules
            assert json.loads(rules[1][0]) == {"prerender": [{"source": "document", "where": {"selector_matches": "#worldbtn"},
                                                               "eagerness": "moderate"}]}, rules
    finally:
        _stop(server)


def _post(port, token, verb, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/{verb}?t={token}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as answer:
        return json.loads(answer.read())


def test_a_running_agents_pid_is_asked_of_the_kernel(monkeypatch):
    """`pid_alive` ran `tasklist` on Windows, about 120 ms a call, once per running agent on every poll
    and in every action's answer. It asks the kernel now (a process handle and a zero wait); `tasklist`
    is only the fallback for a process the kernel will not open."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        if os.name == "nt":
            def no_tasklist(*a, **k):
                raise AssertionError(f"a process was run to ask about a pid: {a}")
            monkeypatch.setattr(subprocess, "run", no_tasklist)
        assert supervisor.pid_alive(child.pid) is True
    finally:
        child.kill()
        child.wait()
    assert supervisor.pid_alive(child.pid) is False
    assert supervisor.pid_alive(0) is False


def test_an_actions_row_is_built_for_its_checkout_and_its_siblings_only(fleet_home, tmp_path, monkeypatch):
    """What an action answers with (`row_for`) built the whole fleet's snapshot to take one row from
    it: every agent's stream read and folded. It builds the named checkout's row and its project's
    other checkouts' (its switcher strip is made of them), and they are the rows `/api/fleet` sends."""
    _repos(tmp_path, ["alpha", "omega"])
    _repos(tmp_path, ["beta", "beta-two"], project="beta")
    refreshed = []
    real = E.refresh
    monkeypatch.setattr(E, "refresh", lambda name, *a, **k: refreshed.append(name) or real(name, *a, **k))
    row = S.row_for("beta")
    assert row["repo"] == "beta" and sorted(set(refreshed)) == ["beta", "beta-two"], refreshed
    assert [s["repo"] for s in row["siblings"]] == ["beta-two"], row["siblings"]
    whole = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}
    assert set(whole) == {"alpha", "omega", "beta", "beta-two"}
    for key in ("state", "project", "siblings", "needs_human"):
        assert row[key] == whole["beta"][key], key


def test_a_send_can_answer_as_soon_as_the_turn_runs_and_the_row_follows(fleet_home, tmp_path, spawns, monkeypatch):
    """The desk's Send asks with `row: false`: the answer comes once the turn's process is up, saying
    `running`, and the page fetches the row from `/api/row`. A send that does not ask (the CLI, the
    phone, an older page) still gets its row with the answer, and it is built once, not twice."""
    _repo(tmp_path, "alpha")
    built = []
    real = S.row_for
    monkeypatch.setattr(S, "row_for", lambda name: built.append(name) or real(name))
    server, token, port = _serve()
    try:
        quick = _post(port, token, "send", {"repo": "alpha", "message": "carry on", "row": False})
        assert quick["ok"] and quick["state"] == "running" and "row" not in quick, quick
        assert built == [], built
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/row?repo=alpha&t={token}", timeout=10) as answer:
            got = json.loads(answer.read())
        assert got["ok"] and got["row"]["repo"] == "alpha" and got["row"]["state"] == "running", got
        assert built == ["alpha"], built

        spawns["alive"].clear()                    # the turn ended
        whole = _post(port, token, "send", {"repo": "alpha", "message": "and again"})
        assert whole["ok"] and whole["row"]["repo"] == "alpha", whole
        assert built == ["alpha", "alpha"], f"the row was built {len(built) - 1} times for one send"
    finally:
        _stop(server)


def test_the_launch_tier_sums_the_month_only_when_an_allowance_asks_it_to(fleet_home, tmp_path, monkeypatch):
    """Every `send` summed the whole fleet's month (every ledger, every stream's new events) for the
    launch tier, though with no allowance recorded the tier is the configured one whatever was spent.
    With an allowance, the month is summed again only when a ledger or a stream has changed."""
    _repos(tmp_path, ["alpha", "beta"])
    monkeypatch.setitem(credits._MONTH, "key", None)
    summed = []
    real = spend.for_agent
    monkeypatch.setattr(spend, "for_agent", lambda name: summed.append(name) or real(name))
    assert credits.tier_for({}) == "balance"
    assert summed == [], "the month was summed with no allowance"
    cfg = {"fleet": {"credits": {"allowance": 100}}}
    assert credits.tier_for(cfg) == "balance"
    first = len(summed)
    assert first == 2, summed
    assert credits.tier_for(cfg) == "balance"
    assert len(summed) == first, "summed again with nothing changed"
    E.append("alpha", [E.event("alpha", "assistant_text", {"text": "more"})])
    credits.tier_for(cfg)
    assert len(summed) == first + 2, "a stream that grew did not count"


def test_a_request_reads_a_file_once_and_again_after_writing_it(fleet_home, tmp_path, monkeypatch):
    """One `send` opened its agent's lock seven times and parsed its stream 23 times. Within a request
    (`events.reading`, which `act` and `fleet_snapshot` hold), a file is read once while it is the same
    file and again once it is written, and a stream is parsed once per version."""
    path = str(tmp_path / "x.json")
    textio.write_text(path, '{"a": 1}')
    decoded = []
    real = textio.decode
    monkeypatch.setattr(textio, "decode", lambda b: decoded.append(1) or real(b))
    with textio.memo():
        assert textio.read_text(path) == textio.read_text(path) == '{"a": 1}'
        assert len(decoded) == 1
        textio.write_text(path, '{"a": 22}')
        assert textio.read_text(path) == '{"a": 22}' and len(decoded) == 2
    textio.read_text(path)
    textio.read_text(path)
    assert len(decoded) == 4, "a read outside a request was kept"

    _repos(tmp_path, ["alpha"])
    parsed = []
    real_parse = E._parse
    monkeypatch.setattr(E, "_parse", lambda p: parsed.append(p) or real_parse(p))
    with E.reading():
        everything = E.read("alpha")
        assert E.read("alpha", kinds=("started",)) == [e for e in everything if e["kind"] == "started"]
        assert len(parsed) == 1
        E.append("alpha", [E.event("alpha", "assistant_text", {"text": "one more"})])
        assert E.read("alpha")[-1]["data"]["text"] == "one more" and len(parsed) == 2


@pytest.mark.browser
def test_the_desk_says_starting_at_once_and_running_from_the_sends_answer(fleet_home, tmp_path, browser, spawns):
    """Enter in a pane's reply box: the chip says *starting* before the server has answered, *running*
    from the answer (`send` asked with `row: false`), and the row follows from `/api/row`."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        tile = '.tile[data-repo="alpha"]'
        page.wait_for_function(f"() => !!document.querySelector('{tile} .say')", timeout=15000)
        page.fill(f"{tile} .say", "carry on")
        with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/send")) as sent:
            with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/row")):
                page.press(f"{tile} .say", "Enter")
        assert sent.value.post_data_json["row"] is False, sent.value.post_data_json
        page.wait_for_function(f"() => /\\brunning\\b/.test(document.querySelector('{tile} .chip').className)", timeout=10000)
        page.close()
    finally:
        _stop(server)
