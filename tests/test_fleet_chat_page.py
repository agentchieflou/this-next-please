"""The chat view (operator request, 2026-10): the agents in a left sidebar, each one's sessions beneath
it, and one session's conversation readable at a time -- "a traditional offering as well", beside the
desk and never instead of it.

It adds no route: it reads `/api/fleet`, `/api/sessions` and `/api/transcript` and posts the desk's own
verbs, so what is held here is the page -- that it is served and reachable from the desk, that a
session's conversation is that session's and nobody else's, that an earlier one is read and never
driven, that the stream reaches the open conversation, and that a message goes out as `send`.
"""
from __future__ import annotations
import json
import os
import re
import threading
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import events as E, serve as S
from agentdata.fleet.registry import Registry

from desk_waits import record_mutations
from test_fleet import make_project
from test_fleet_desk_switcher import _repo, fleet_home, spawns  # noqa: F401

STATIC = S.STATIC
READY = "() => !!window.FleetChat && FleetChat.rows.length > 0 && !FleetChat.stream.busy"
LOG = "() => [...document.querySelectorAll('#chatlog .cl:not(.cl-tool):not(.cl-note) .cl-text')].map(e => e.textContent)"


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
    """An agent stopped on one question, with an id the answer can name."""
    path = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-7")
    Registry().add(path, name="asks")
    E.append("asks", [
        E.event("asks", "started", {"prompt": "Ticket RDSD-7", "session": ""}, ticket="RDSD-7"),
        E.event("asks", "session_id", {"session": "sess-a"}, ticket="RDSD-7"),
        E.event("asks", "assistant_text", {"text": "Two readings of the boundary."}, ticket="RDSD-7"),
        E.event("asks", "tool_call", {"tool": "shell", "arguments": {"command": "ad-state ask"}}, ticket="RDSD-7"),
        E.event("asks", "question_opened", {"id": "q1", "question": "which sprint boundary?",
                                            "choices": ["calendar", "fiscal"]}, ticket="RDSD-7"),
    ])
    return path


def _open(browser, port, token, where="", width=1280):
    page = browser.new_page(viewport={"width": width, "height": 860})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/chat?t={token}{where}", wait_until="domcontentloaded")
    page.wait_for_function(READY, timeout=15000)
    return page, errors


def _settled(page, js):
    page.wait_for_function(f"() => ({js})() && !FleetChat.stream.busy", timeout=15000)


# ------------------------------------------------------------------------------- served, and a door


def test_the_chat_view_is_a_page_of_its_own_and_the_desk_opens_it(fleet_home):
    """`/chat` is served with its assets carrying the token, `/open?page=chat` lands on it, and the
    desk's toolbar and its `c` key are the doors -- the panes stay what they are."""
    assert S.PAGES["/chat"] == "chat.html"
    assert "chat.css" in S.ASSETS and "chat/chat.js" in S.ASSETS
    server, token, port = _serve()
    try:
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/chat?t={token}", timeout=5).read().decode()
        assert f'"/static/chat/chat.js?t={token}"' in html and f'"/static/chat.css?t={token}"' in html
        assert "ink-off" in html, "the chat view is served ink-off, as the desk is, until ink draws"

        class Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        try:
            urllib.request.build_opener(Stay).open(f"http://127.0.0.1:{port}/open?page=chat", timeout=5)
            raise AssertionError("/open answered without a redirect")
        except urllib.error.HTTPError as e:
            assert e.code == 302 and e.headers["Location"].startswith(f"/chat?t={token}")
    finally:
        _stop(server)

    desk = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'id="chatbtn"' in desk and "<kbd>c</kbd> the chat view" in desk
    assert 'chatLink.href = pageUrl("/chat")' in app
    assert re.search(r'e\.key === "c"\) \{ var on = openName\(\); location\.href = pageUrl\("/chat"\)', app)


# ------------------------------------------------------------------------------- the page, in a browser


@pytest.mark.browser
def test_agents_in_a_sidebar_their_sessions_beneath_and_one_conversation_at_a_time(fleet_home, tmp_path, browser):
    """Every agent in the sidebar with its sessions under it, the current one first; the open
    conversation is that session's lines and no other's (sessions interleave in one stream); an
    earlier session is read, not driven; and the agent's current session follows the stream."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "#alpha")
        _settled(page, "() => FleetChat.sessions.alpha && document.querySelectorAll('#chatlog .cl').length > 0")
        side = page.evaluate("""() => [...document.querySelectorAll('#chatagents > .ca')].map(a => ({
            name: a.querySelector('.ca-name').textContent,
            sessions: [...a.querySelectorAll('.cs')].map(s => [s.dataset.sid, s.querySelector('.cs-chip').textContent,
                                                               s.classList.contains('is-open')])}))""")
        assert [a["name"] for a in side] == ["alpha", "asks"], side
        assert side[0]["sessions"] == [["sess-2", "current", True], ["sess-1", "earlier", False]], side
        assert side[1]["sessions"] == [["sess-a", "current", False]], side

        assert page.evaluate(LOG) == ["two, first turn", "two, second turn"]
        assert not page.is_hidden("#chatform") and page.is_hidden("#chatended")
        assert page.text_content("#chatname") == "alpha"

        # an earlier session: its own lines, read-only, and *Resume here* rather than a composer
        page.click("#chatagents [data-rowkey='alpha'] .cs[data-sid='sess-1'] .cs-open")
        _settled(page, "() => FleetChat.open.session === 'sess-1'")
        page.wait_for_function(f"() => ({LOG})().join('|') === 'one, first turn|one, second turn'", timeout=15000)
        assert page.is_hidden("#chatform") and not page.is_hidden("#chatended")
        assert "not alpha's current session" in page.text_content("#chatendedwhat")
        assert "#alpha/sess-1" in page.url

        page.click("#chatcurrent")
        page.wait_for_function(f"() => ({LOG})().join('|') === 'two, first turn|two, second turn'", timeout=15000)
        assert not page.is_hidden("#chatform")

        # the stream reaches the open conversation without a reload
        E.append("alpha", [E.event("alpha", "assistant_text", {"text": "two, third turn"}, ticket="RDSD-2")])
        page.wait_for_function(f"() => ({LOG})().slice(-1)[0] === 'two, third turn'", timeout=15000)

        # an idle redraw writes nothing (docs/desk-components.md, rule 1)
        seen = record_mutations(page, target="body")
        page.evaluate("() => { drawAgents(); drawMain(); drawAgents(); drawMain(); }")
        assert seen.stop().count() == 0, seen.records()

        # tool calls are one quiet line each, and the box hides them
        page.click("#chatagents [data-rowkey='asks'] .ca-head")
        _settled(page, "() => FleetChat.open.repo === 'asks' && document.querySelectorAll('#chatlog .cl-tool').length === 1")
        assert page.is_visible("#chatlog .cl-tool")
        page.uncheck("#chattools")
        assert page.is_hidden("#chatlog .cl-tool")
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_message_goes_out_as_send_and_comes_back_as_the_operators_line(fleet_home, tmp_path, browser, spawns):
    """The composer posts the desk's `send`: the turn resumes the session on screen, and the line the
    operator typed comes back on the stream as theirs. A question is answered on its card, by id."""
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "#alpha")
        _settled(page, "() => document.querySelectorAll('#chatlog .cl').length > 0")
        page.fill("#chatmessage", "use the fiscal calendar")
        page.press("#chatmessage", "Enter")
        page.wait_for_function("() => [...document.querySelectorAll('#chatlog .cl-you .cl-text')]"
                               ".some(e => e.textContent === 'use the fiscal calendar')", timeout=15000)
        assert spawns["launched"], "send launched a turn"
        argv = spawns["launched"][-1]
        assert "--resume" in argv and argv[argv.index("--resume") + 1] == "sess-2", argv
        # The composer clears when `send` answers ok, which can land after the stream has already
        # brought the line back (Windows shard 2/4 on main, 2026-10-02): wait for it, not race it.
        page.wait_for_function("() => document.getElementById('chatmessage').value === ''", timeout=10000)

        page.click("#chatagents [data-rowkey='asks'] .ca-head")
        _settled(page, "() => FleetChat.open.repo === 'asks' && !document.getElementById('chatasks').hidden")
        assert page.text_content("#chatasklist .cq-q") == "which sprint boundary?"
        page.click("#chatasklist .ask-choice >> text=fiscal")
        with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/answer")) as asked:
            page.click("#chatanswer")
        body = asked.value.post_data_json
        assert body == {"repo": "asks", "answers": [{"id": "q1", "answer": "fiscal"}]}, body
        assert errors == [], errors
    finally:
        _stop(server)


@pytest.mark.browser
def test_on_a_phone_width_the_list_and_the_conversation_take_turns(fleet_home, tmp_path, browser):
    """One column under 720 px: the page opens on the list (it picks nothing for the operator), an
    agent opens its conversation in the column, and *← agents* goes back."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, width=390)
        assert page.is_visible("#chatside") and page.is_hidden("#chatmain")
        page.click("#chatagents [data-rowkey='alpha'] .ca-head")
        _settled(page, "() => document.querySelectorAll('#chatlog .cl').length > 0")
        assert page.is_hidden("#chatside") and page.is_visible("#chatmain") and page.is_visible("#chatback")
        width = page.evaluate("() => document.documentElement.scrollWidth")
        assert width <= 390, f"the page is {width}px wide on a 390px screen"
        page.click("#chatback")
        assert page.is_visible("#chatside") and page.is_hidden("#chatmain")
        assert errors == [], errors
    finally:
        _stop(server)


# ------------------------------------------------------------------------------- the desk's pane (2026-10-06)


def test_the_chat_is_a_desk_pane_and_carries_the_desks_ink_gate(fleet_home, tmp_path, monkeypatch):
    """The operator, 2026-10-06: the chat should wear every theme "1:1 with the desk view". Its
    conversation is a desk pane (the desk's classes), it loads the desk's `ink/ink.js`, its `<body>`
    carries the gate's facts as the desk's does, and a skin's module is preloaded as on the desk."""
    page = open(os.path.join(STATIC, "chat.html"), encoding="utf-8").read()
    assert re.search(r'<main id="chatmain" class="tile"', page)
    for cls in ('class="head"', 'class="repo"', 'class="chip"', 'class="chipword"', 'class="chipage"',
                'class="ticket"', 'class="runline"', 'class="why"', 'class="approval"', 'class="summary"',
                'class="asks"', 'class="asks-list"', 'class="readonly"', 'class="row bottom"',
                'class="start"', 'class="reset"', 'class="stop"', 'class="freshtoggle wordbtn"',
                'class="cq ask"', 'class="cq-q ask-q"'):
        assert cls in page, cls
    assert '<script type="module" src="/static/ink/ink.js"></script>' in page
    assert "chat.html" in S.INKED_PAGES and "chat.html" in S.INK_LAYER_PAGES

    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    (tmp_path / "cfg.json").write_text('{"theme": {"skin": "notebook"}}', encoding="utf-8")
    server, token, port = _serve()
    try:
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/chat?t={token}", timeout=5).read().decode()
        body = re.search(r"<body[^>]*>", html).group(0)
        assert re.fullmatch(r'<body class="ink-off" data-skin="notebook"(?: data-skin-variant="[a-z]+")? data-ink-shell="[a-z]+" '
                            r'data-ink-probe="[a-z]+" data-ink-skins="[a-z ]+">', body), body
        assert f'<script type="module" src="/static/ink/ink.js?t={token}"></script>' in html
        assert f'<link rel="modulepreload" href="/static/ink/skins/notebook.js?t={token}">' in html
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_bottom_row_is_the_desks_start_fresh_reset_and_stop(fleet_home, tmp_path, browser, spawns):
    """The operator, 2026-10-06: "we don't have the 'start fresh' / 'start new session' options in the
    chat section". The conversation has the desk pane's bottom row: *Start fresh* posts `fresh` (and
    the second press after a `second_press` refusal sends `closed`), *Start* on a typed ticket posts
    `start`, Reset and Stop post theirs, and Alt+N is *start fresh* as on the desk."""
    _repo(tmp_path, "alpha")
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "#alpha")
        _settled(page, "() => document.querySelectorAll('#chatlog .cl').length > 0")
        posted = []
        answers = {"fresh": [{"ok": False, "second_press": True, "code": "chat_open",
                              "error": "its chat is open", "hint": "close it first"}]}

        def answer(route, request):
            verb = request.url.split("?")[0].rsplit("/", 1)[-1]
            posted.append((verb, request.post_data_json))
            queue = answers.get(verb) or []
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(queue.pop(0) if queue else {"ok": True}))

        page.route(re.compile(r"/api/(fresh|start|reset|stop)\b"), answer)
        assert page.is_visible("#chatstart") and page.text_content("#chatstart") == "Start fresh"
        assert page.is_visible("#chatreset") and page.is_visible("#chatstop")

        page.click("#chatstart")
        page.wait_for_function("() => document.getElementById('chatstart').textContent"
                               " === 'start fresh \u2014 it is closed'", timeout=10000)
        page.click("#chatstart")
        page.wait_for_function("() => document.getElementById('chatstart').textContent === 'Start fresh'",
                               timeout=10000)
        assert posted[:2] == [("fresh", {"repo": "alpha"}), ("fresh", {"repo": "alpha", "closed": True})], posted

        page.fill("#chatmessage", "RDSD-9")
        assert page.text_content("#chatstart") == "Start"
        page.click("#chatstart")
        page.wait_for_function("() => document.getElementById('chatmessage').value === ''", timeout=10000)
        for verb, press in (("reset", lambda: page.click("#chatreset")), ("stop", lambda: page.click("#chatstop")),
                            ("fresh", lambda: page.keyboard.press("Alt+n"))):
            with page.expect_response(lambda r, v=verb: r.url.split("?")[0].endswith("/api/" + v)):
                press()
        assert posted[2:] == [("start", {"repo": "alpha", "ticket": "RDSD-9"}),
                              ("reset", {"repo": "alpha", "force": False}),
                              ("stop", {"repo": "alpha"}),
                              ("fresh", {"repo": "alpha"})], posted
        assert errors == [], errors
    finally:
        _stop(server)


LOOK = """() => {
    const of = (sel, props) => { const el = document.querySelector(sel); if (!el) return null;
        const cs = getComputedStyle(el); return props.map(p => cs.getPropertyValue(p)); };
    return { repo: of(%s, ['font-family', 'font-size', 'background-color']),
             asks: of(%s, ['outline-style', 'outline-width', 'outline-color']),
             q: of(%s, ['background-color']) };
}"""


@pytest.mark.browser
def test_a_skin_marks_the_chat_exactly_as_it_marks_the_desk(fleet_home, tmp_path, browser, monkeypatch):
    """1:1 with the desk view: under the notebook skin the agent that needs you has the same
    lettering, the same highlighter on its name and its question and the same loop round its
    questions on the chat as on its desk pane -- the same rules and marks, not a copy of them."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    (tmp_path / "cfg.json").write_text('{"theme": {"skin": "notebook"}}', encoding="utf-8")
    _repo(tmp_path, "alpha")
    _asks(tmp_path)
    S.arrange(order=["alpha", "asks"])
    S.update_window("main", open="asks", widths={"alpha": 1, "asks": 1})
    server, token, port = _serve()
    try:
        page, errors = _open(browser, port, token, "#asks")
        _settled(page, "() => FleetChat.open.repo === 'asks' && !document.getElementById('chatasks').hidden"
                       " && !!document.querySelector('#chatasklist .ask-q') && !!window.Ink && Ink.inspect().plain")
        chat = page.evaluate(LOOK % ("'#chatname'", "'#chatasks'", "'#chatasklist .ask-q'"))
        desk_page = browser.new_page(viewport={"width": 1280, "height": 860})
        desk_page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        desk_page.wait_for_function("""() => { const t = document.querySelector('.tile[data-repo="asks"]');
            const q = t && t.querySelector('.ask:not([hidden]) .ask-q');
            return !!q && !!q.textContent && t.classList.contains('needs-human') && !!window.Ink && Ink.inspect().plain; }""",
                                    timeout=15000)
        desk = desk_page.evaluate(LOOK % ("'.tile[data-repo=\"asks\"] .head .repo'", "'.tile[data-repo=\"asks\"] .asks'",
                                          "'.tile[data-repo=\"asks\"] .ask:not([hidden]) .ask-q'"))
        assert "Caveat" in chat["repo"][0], chat
        assert chat["repo"][2] not in ("rgba(0, 0, 0, 0)", "transparent"), chat
        assert chat["asks"][:2] == ["solid", "2px"], chat
        assert chat == desk, (chat, desk)
        assert errors == [], errors
    finally:
        _stop(server)
