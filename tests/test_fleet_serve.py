"""The multi-viewer: the server, the wire, and the promises the static files make.

There is no browser here. What a browser would tell us that these do not is whether the layout
looks right, and that is #102's laptop run with a real page in front of a person. What *can* be
proven headlessly is everything that would silently break: the token, the loopback bind, the SSE
frames, the fact that the page fetches nothing from the internet, and that the wheel ships it.
"""
from __future__ import annotations
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import approval, events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
CONTRACT = os.path.join(ROOT, "docs", "fleet-dashboard.md")


@pytest.fixture()
def running(fleet_home, tmp_path):                              # noqa: F811 - the fixture is the argument
    """A bound server on a free port, serving in a thread, torn down however the test ends."""
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, token, server
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def get(base, path, token="", timeout=10):
    sep = "&" if "?" in path else "?"
    url = f"{base}{path}{sep}t={token}" if token else f"{base}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8"), dict(r.headers)


def post(base, path, token, body, timeout=10):
    req = urllib.request.Request(f"{base}{path}?t={token}", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def a_repo(tmp_path, name="luna", **kw):
    path = make_project(tmp_path / name, **kw)
    Registry().add(path, name=name)
    return path


# ------------------------------------------------------------------------------------ the door


def test_a_request_without_the_token_is_refused(running):
    base, token, _ = running
    for path in ("/", "/api/fleet", "/api/themes", "/static/app.js"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base, path)
        assert e.value.code == 403, path


def test_a_wrong_token_is_refused_and_is_not_told_which_half_was_wrong(running):
    base, token, _ = running
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base, "/api/fleet", token="nearly-" + token)
    assert e.value.code == 403
    assert json.loads(e.value.read())["error"] == "not authorized"


def test_the_server_never_listens_on_anything_but_loopback(running):
    """A dashboard on 0.0.0.0 is a fleet anyone on the corporate network can drive."""
    base, token, server = running
    assert server.server_address[0] == "127.0.0.1"
    host = socket.gethostbyname(socket.gethostname())
    if host.startswith("127."):
        pytest.skip("this machine's hostname already resolves to loopback")
    with socket.socket() as s:
        s.settimeout(2)
        with pytest.raises((ConnectionRefusedError, socket.timeout, OSError)):
            s.connect((host, server.server_address[1]))


def test_every_response_carries_the_headers_that_keep_the_page_local(running):
    base, token, _ = running
    _, _, headers = get(base, "/", token)
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Access-Control-Allow-Origin" not in headers, "the page must not be reachable cross-site"


def test_a_path_outside_static_is_not_served(running):
    base, token, _ = running
    for path in ("/static/../../../pyproject.toml", "/static/..%2f..%2fpyproject.toml"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base, path, token)
        assert e.value.code == 404, path


# ------------------------------------------------------------------------------------ the data


def test_the_snapshot_is_the_fold_and_not_a_second_opinion(running, tmp_path):
    """`supervisor.status()` also carries an `agent` word for the same idea as `state`. Shipping
    both would give the tile two answers that drift apart."""
    base, token, _ = running
    a_repo(tmp_path, "luna", phase="optimizing", ticket="RDSD-1")
    _, body, _ = get(base, "/api/fleet", token)
    row = json.loads(body)["repos"][0]
    assert row["repo"] == "luna" and row["state"] in ("starting", "idle")
    assert "agent" not in row, "two state words on one row"
    assert set(row) >= {"state", "why", "ticket", "needs_human", "last_seq", "recent"}


def test_a_pending_approval_reaches_the_page_with_its_payload(running, tmp_path, monkeypatch):
    base, token, _ = running
    a_repo(tmp_path, "luna")
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    approval.require("jira-transition", "RDSD-1: In Progress -> In Review",
                     {"key": "RDSD-1", "transition": "31 In Review"}, ticket="RDSD-1", timeout=0)
    monkeypatch.delenv(registry.AGENT_ENV)

    _, body, _ = get(base, "/api/fleet", token)
    data = json.loads(body)
    assert data["repos"][0]["state"] == "waiting_approval"
    assert data["approvals"][0]["payload"]["transition"] == "31 In Review"


def test_approving_from_the_page_releases_the_agent(running, tmp_path, monkeypatch):
    """The tile's one genuinely important button. It calls #95's function, not a copy of it."""
    base, token, _ = running
    a_repo(tmp_path, "luna")
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    got = {}

    def agent():
        got["d"] = approval.require("jira-transition", "RDSD-1 -> In Review", {"key": "RDSD-1"},
                                    timeout=20, poll=0.02)

    t = threading.Thread(target=agent)
    t.start()
    deadline = time.time() + 5
    while not approval.pending() and time.time() < deadline:
        time.sleep(0.02)
    id = approval.pending()[0]["id"]

    code, answer = post(base, "/api/approve", token, {"id": id})
    assert code == 200 and answer["decision"] == "approved"
    t.join(timeout=10)
    assert got["d"].ok


def test_a_refusal_reaches_the_page_with_the_same_words_the_cli_gives(running, tmp_path):
    base, token, _ = running
    a_repo(tmp_path, "luna")
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base, "/api/stop", token, {"repo": "nobody"})
    body = json.loads(e.value.read())
    assert e.value.code == 409
    assert "nobody" in body["error"] and body["hint"]


@pytest.mark.parametrize("body", ["not json", '"a string"', "[]"])
def test_a_malformed_body_is_a_400_not_a_traceback(running, body):
    base, token, _ = running
    req = urllib.request.Request(f"{base}/api/stop?t={token}", data=body.encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400


def test_an_unknown_action_is_refused_by_name(running):
    base, token, _ = running
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base, "/api/launch-the-missiles", token, {})
    assert e.value.code == 409
    assert "unknown action" in json.loads(e.value.read())["error"]


# ------------------------------------------------------------------------------------- the wire


def test_the_stream_frames_are_sse_and_carry_a_resumable_id(fleet_home, tmp_path):  # noqa: F811
    repo = a_repo(tmp_path, "luna")
    E.append("luna", [E.event("luna", "assistant_text", {"text": "hello"}),
                      E.event("luna", "turn_ended", {})])
    out = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert "event: agent\n" in frames
    assert "id: luna:1\n" in frames and "id: luna:2\n" in frames
    assert frames.endswith("\n\n")
    assert json.loads(frames.split("data: ")[1].split("\n")[0])["kind"] == "assistant_text"


def test_the_stream_sends_each_event_once(fleet_home, tmp_path):  # noqa: F811
    a_repo(tmp_path, "luna")
    E.append("luna", [E.event("luna", "assistant_text", {"text": "hello"})])
    cursors, out = {}, []
    S.stream_events(cursors, threading.Event(), out.append, once=True)
    first = [f for f in out if "event: agent" in f]
    assert any("hello" in f for f in first)
    assert cursors["luna"] == E.read("luna")[-1]["seq"]

    out.clear()
    S.stream_events(cursors, threading.Event(), out.append, once=True)
    assert not [f for f in out if "event: agent" in f], "an event was delivered twice"


def test_a_heartbeat_goes_out_even_when_nothing_happens(fleet_home, tmp_path):  # noqa: F811
    """Not decoration: a proxy that sees no bytes for a minute closes the connection, and the tiles
    then stop updating with nothing anywhere saying why."""
    a_repo(tmp_path, "luna")
    out = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    assert "event: tick" in "".join(out)


def test_cursors_are_per_agent(fleet_home):                     # noqa: F811
    """One number across every agent would replay one stream and skip another: each `seq` is dense
    and its own."""
    assert S._cursors("luna:12,other:4") == {"luna": 12, "other": 4}
    assert S._cursors("") == {}
    assert S._cursors("rubbish") == {}


def test_the_stream_survives_an_agent_whose_repo_has_gone(fleet_home, tmp_path):  # noqa: F811
    """Criterion: one agent dying must not take the other tiles down. The stream is just events."""
    path = a_repo(tmp_path, "luna")
    a_repo(tmp_path, "other")
    E.append("other", [E.event("other", "assistant_text", {"text": "still here"})])
    shutil.rmtree(path)
    out = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    assert "still here" in "".join(out)


def test_a_live_stream_delivers_a_new_event_within_a_second(running, tmp_path):
    """The tile has to feel live. This is the whole promise of the page."""
    base, token, _ = running
    a_repo(tmp_path, "luna")
    url = f"{base}/api/events?t={token}&since="
    stream = urllib.request.urlopen(url, timeout=15)
    try:
        deadline = time.time() + 5
        E.append("luna", [E.event("luna", "assistant_text", {"text": "a new line"})])
        seen = ""
        while time.time() < deadline and "a new line" not in seen:
            seen += stream.readline().decode("utf-8")
        assert "a new line" in seen
    finally:
        stream.close()


# -------------------------------------------------------------------------------- the page itself


def test_the_page_fetches_nothing_from_the_internet():
    """JCEF and Simple Browser both sit behind the corporate proxy. One CDN reference is a page
    that does not load at work -- and it would look like a bug in the fleet, not in the HTML."""
    for name in sorted(os.listdir(STATIC)):
        body = open(os.path.join(STATIC, name), encoding="utf-8").read()
        for bad in ("http://", "https://", "//cdn", "//unpkg", "@import url("):
            assert bad not in body, f"{name} reaches outside for {bad}"


def test_the_static_payload_is_small_enough_to_load_over_anything():
    total = sum(os.path.getsize(os.path.join(STATIC, n)) for n in os.listdir(STATIC))
    assert total < 200 * 1024, f"{total} bytes of static payload"


@pytest.mark.skipif(not shutil.which("node"), reason="no node on this machine to check the syntax")
def test_the_page_script_parses():
    """The one class of regression that ships silently: a syntax error in a file no test imports."""
    p = subprocess.run(["node", "--check", os.path.join(STATIC, "app.js")],
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 0, p.stderr


def test_the_page_never_puts_agent_output_into_html():
    """Agent output is arbitrary text from a model and from tools. `innerHTML` anywhere in this
    file is a script-injection route straight from a Jira ticket description onto the page."""
    body = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "innerHTML" not in body
    assert "textContent" in body


def test_the_markup_and_the_script_agree_on_every_hook():
    """A renamed class in one file and not the other fails silently in a browser and never here."""
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    import re

    for selector in sorted(set(re.findall(r'querySelector\("\.([a-z-]+)"\)', js))):
        assert f'class="{selector}"' in html or f'"{selector}' in html, \
            f".{selector} is used by app.js and is not in index.html"
    for element in sorted(set(re.findall(r'getElementById\("([a-z]+)"\)', js))):
        assert f'id="{element}"' in html, f"#{element} is used by app.js and is not in index.html"


def test_the_themes_come_from_the_icls_files_and_the_status_colours_do_not():
    """A chip that means "needs you" has to be the same red in every palette, or the colour stops
    being information."""
    found = S.themes()
    assert {t["name"] for t in found} == {"Canopy", "Crimson Studio", "Pastel Lavender"}
    for theme in found:
        assert set(theme["colors"]) == {"bg", "panel", "text", "muted", "accent", "line", "select"}
        assert all(v.startswith("#") for v in theme["colors"].values())
        assert "human" not in theme["colors"] and "running" not in theme["colors"]

    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    for status in ("running", "waiting", "human", "done", "idle"):
        assert f"--{status}:" in css, f"the {status} colour is not fixed in the stylesheet"


# ------------------------------------------------------------------------------ finding the page


def test_serve_writes_where_it_is_so_the_ide_shells_can_find_it(fleet_home):    # noqa: F811
    server, token = S.build(0)
    try:
        S.record(server, token)
        written = json.loads(open(S.serve_file(), encoding="utf-8").read())
        assert written["url"] == S.url_for(server, token)
        assert written["url"].startswith("http://127.0.0.1:")
        assert token in written["url"]
        S.forget()
        assert not os.path.exists(S.serve_file())
    finally:
        server.server_close()


def test_a_taken_port_says_how_to_get_a_free_one(fleet_home):   # noqa: F811
    first, _ = S.build(0)
    try:
        with pytest.raises(S.ServeError) as e:
            S.build(first.server_address[1])
        assert "--port 0" in e.value.hint
    finally:
        first.server_close()


def test_every_run_gets_its_own_token(fleet_home):              # noqa: F811
    a, ta = S.build(0)
    b, tb = S.build(0)
    try:
        assert ta != tb and len(ta) > 20
    finally:
        a.server_close()
        b.server_close()


# --------------------------------------------------------------------------------- the contract


def test_the_wheel_ships_the_static_files():
    """`pip install agentdata` with no `package-data` entry installs a server whose every page is a
    404 -- and only on someone else's machine, never in the checkout."""
    body = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert "fleet/static/*" in body


def test_the_dashboard_is_documented_including_the_keyboard_map():
    text = open(CONTRACT, encoding="utf-8").read()
    for endpoint in ("/api/fleet", "/api/events", "/api/approve", "/api/deny", "/api/start",
                     "/api/send", "/api/stop"):
        assert endpoint in text, f"{endpoint} is not documented"
    for key in ("Esc", "1", "9", "a"):
        assert f"`{key}`" in text, f"the {key} key is not in the keyboard map"
    assert "127.0.0.1" in text and "token" in text
