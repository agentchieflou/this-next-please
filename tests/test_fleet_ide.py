"""Getting the dashboard in front of the operator with nothing installed.

Most of this slice is a claim about somebody else's software, and a claim is only worth what was
measured. What can be proven headlessly is proven here — the routes, the fallbacks, the launcher,
and the two headers whose absence is what lets VS Code's Simple Browser show the page at all. What
needs a person in front of an IDE is marked as such in `docs/fleet-ide.md` rather than asserted.
"""
from __future__ import annotations
import json
import os
import socket
import threading
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import opener as O, serve as S

from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-ide.md")
TOOLS = os.path.join(ROOT, "agentdata", "templates", "pycharm", "agentdata.xml")


@pytest.fixture()
def running(fleet_home):                                        # noqa: F811 - the fixture is the argument
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    S.record(server, token)
    try:
        yield server, token
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# ------------------------------------------------------------------------- the tokenless routes


def test_ping_says_it_is_us_and_nothing_else(running):
    """A launcher must tell "our dashboard is on 8765" from "something else is" before starting a
    second one — and it holds no token to ask with."""
    server, token = running
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=10) as r:
        body = json.loads(r.read())
    assert body["ok"] is True and body["service"] == "ad-fleet" and body["port"] == port
    assert body["version"] and body["contract"] == S.CONTRACT
    assert set(body) == {"ok", "service", "port", "version", "contract"}, body
    assert token not in json.dumps(body), "the liveness check leaked the token"


def test_ping_is_how_open_avoids_starting_a_second_server(running):
    server, _token = running
    port = server.server_address[1]
    assert O.ping(port) is True
    assert O.running(), "a live server was not recognised"

    with socket.socket() as s:                                  # a free port, nothing listening
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert O.ping(free, timeout=1) is False


def test_a_stale_serve_file_is_not_a_running_server(fleet_home):    # noqa: F811
    """The file outlives the process it describes. Trusting it would make `ad-fleet open` show a
    URL that answers nothing."""
    from agentdata import textio

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    textio.write_json(os.path.join(str(fleet_home), S.SERVE_FILE),
                      {"url": f"http://127.0.0.1:{dead}/?t=x", "port": dead, "token": "x"})
    assert O.serve_record()["port"] == dead
    assert O.running() == {}


def test_open_is_a_stable_address_that_redirects_to_the_tokened_one(running):
    """The whole reason it exists: a per-run token cannot be written into a keybinding or an
    External Tool that has to keep working tomorrow."""
    server, token = running
    port = server.server_address[1]

    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(f"http://127.0.0.1:{port}/open")
    assert e.value.code == 302
    assert e.value.headers["Location"] == f"/?t={token}"

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/open", timeout=10) as r:
        assert "<title>fleet</title>" in r.read().decode("utf-8")


def test_everything_else_still_needs_the_token(running):
    """Two routes are tokenless. Two, and no more."""
    server, _token = running
    port = server.server_address[1]
    for path in ("/", "/api/fleet", "/api/board", "/api/notifications", "/static/app.js"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10)
        assert e.value.code == 403, path


# ----------------------------------------------------------- what lets Simple Browser show it


def test_nothing_stops_the_page_being_framed(running):
    """Two headers would stop an iframe, and neither is present. Adding either later would break
    the VS Code embedding silently, and only for the people using it."""
    server, token = running
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/?t={token}", timeout=10) as r:
        headers = dict(r.headers)
    assert "X-Frame-Options" not in headers
    assert "frame-ancestors" not in headers.get("Content-Security-Policy", "")


def test_the_page_talks_only_to_its_own_origin():
    """Simple Browser runs the page inside a `vscode-webview://` frame. Anything the page fetched
    from another origin would be blocked there and nowhere else, which is the worst kind of bug."""
    js = open(os.path.join(ROOT, "agentdata", "fleet", "static", "app.js"), encoding="utf-8").read()
    assert "location.origin" in js
    assert "http://" not in js and "https://" not in js


# ------------------------------------------------------------------------------ the fallbacks


def test_vscode_says_plainly_that_its_cli_cannot_do_it(running, monkeypatch):
    """Measured on 1.129.1: no `--command`. The plan for this slice assumed there was one, and an
    embedding story that quietly does nothing is worse than one that says so."""
    monkeypatch.setattr(O, "vscode_exe", lambda: "C:/fake/code.cmd")
    monkeypatch.setattr(O, "clipboard", lambda text: True)
    did = O.open_in("vscode", O.running())
    assert did["opened"] == "nothing"
    assert "--command" in did["why"]
    assert "Simple Browser: Show" in did["hint"]
    assert did["url"].endswith("/open"), "the fallback must offer the address a person can reuse"
    assert did["clipboard"] is True


def test_a_missing_vscode_is_a_different_answer(running, monkeypatch):
    monkeypatch.setattr(O, "vscode_exe", lambda: "")
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    did = O.open_in("vscode", O.running())
    assert "not found" in did["why"] and did["clipboard"] is False


def test_pycharm_writes_a_launcher_when_asked(running, tmp_path):
    """PyCharm's built-in preview opens files in the project, never arbitrary URLs -- so the file
    is the thing to offer."""
    did = O.open_in("pycharm", O.running(), launcher_dir=str(tmp_path))
    body = open(did["launcher"], encoding="utf-8").read()
    assert body.count("/open") >= 1, "the launcher must not carry a token that expires"
    assert "http-equiv=\"refresh\"" in body
    assert "ad-fleet serve" in body, "a dead dashboard must say how to start one"


def test_pycharm_without_a_launcher_directory_says_what_to_do(running):
    did = O.open_in("pycharm", O.running())
    assert did["opened"] == "nothing"
    assert "External Tool" in did["hint"] and "--write-launcher" in did["hint"]


def test_edge_is_found_even_though_it_is_never_on_path(running, monkeypatch):
    """Edge is installed on every Windows machine and on almost none of their PATHs."""
    if os.name != "nt":
        pytest.skip("the fixed install paths are Windows ones")
    assert O.edge_exe(), "Edge was not found at any of the standard locations"


def test_an_unknown_target_is_refused_by_name(running):
    with pytest.raises(O.OpenError) as e:
        O.open_in("emacs", O.running())
    assert "browser" in e.value.hint and "vscode" in e.value.hint


def test_open_reuses_a_running_server_rather_than_starting_a_second(running, capsys, monkeypatch):
    from agentdata import cli_fleet

    monkeypatch.setattr(O, "start_server", lambda *a, **k: pytest.fail("a second server was started"))
    monkeypatch.setattr(O, "open_in", lambda *a, **k: {"opened": "nothing", "url": "x"})
    assert cli_fleet.main(["open", "--in", "vscode"]) == 0
    assert "already up" in capsys.readouterr().out


# ------------------------------------------------------------- the External Tools, and the doc


def test_the_pycharm_external_tools_are_well_formed_and_use_the_module_form():
    """`$PyInterpreterDirectory$/python.exe -m agentdata …` and never a bare `ad-fleet`: the
    console scripts are frequently not on PATH, which is the single most common way this package
    looks broken when it is merely unfound."""
    import xml.etree.ElementTree as ET

    root = ET.parse(TOOLS).getroot()
    tools = root.findall("tool")
    assert [t.get("name") for t in tools] == ["fleet: open", "fleet: launcher here", "fleet: status"]
    for tool in tools:
        options = {o.get("name"): o.get("value") for o in tool.iter("option")}
        assert options["COMMAND"] == "$PyInterpreterDirectory$/python.exe"
        assert options["PARAMETERS"].startswith("-m agentdata fleet ")
        assert options["WORKING_DIRECTORY"] == "$ProjectFileDir$"


def test_every_external_tool_names_a_verb_that_exists():
    import xml.etree.ElementTree as ET

    from agentdata import cli_fleet

    parser = cli_fleet.build_parser()
    verbs = set()
    for action in parser._subparsers._group_actions:            # noqa: SLF001 - argparse has no API
        verbs |= set(action.choices)

    root = ET.parse(TOOLS).getroot()
    for tool in root.findall("tool"):
        params = {o.get("name"): o.get("value") for o in tool.iter("option")}["PARAMETERS"].split()
        assert params[:3] == ["-m", "agentdata", "fleet"], params
        assert params[3] in verbs, f"{params[3]} is not an ad-fleet verb"


def test_the_wheel_ships_the_pycharm_template():
    body = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert "templates/pycharm/*" in body


def test_the_doc_records_the_measurement_that_changed_the_plan():
    """The slice was planned around `code --command simpleBrowser.show`. It does not exist, and a
    doc that quietly omitted that would send the next person down the same path."""
    text = open(CONTRACT, encoding="utf-8").read()
    assert "--command" in text and "does not exist" in text
    assert "1.129" in text, "the version the measurement was taken on"
    assert "simpleBrowser.show" in text and "keybindings" in text.lower()


def test_the_doc_is_honest_about_what_was_not_verified():
    text = open(CONTRACT, encoding="utf-8").read()
    for unproven in ("Agents Window", "built-in preview", "--app"):
        assert unproven in text, f"{unproven} is not discussed"
    assert text.lower().count("unverified") >= 3, "the unproven parts must be marked as such"


def test_the_doc_names_the_stable_address_and_why_it_is_safe():
    text = open(CONTRACT, encoding="utf-8").read()
    assert "/open" in text and "/api/ping" in text
    assert "loopback" in text and "serve.json" in text
