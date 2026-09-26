"""The map's network: the desk server, the windows listening now, the polled sources, the approval
gate and the install (#404, epic #295).

Read locally, because that is all the fleet can see: no other machine, no MCP, no ping. Who is
listening is an in-memory registry of open `/api/events` streams (`serve._live`), never written to
disk; the sources are what the poll already counted. Streaming GETs with `urllib` against a real
`serve.build(0)` for the registry, and the pure `graph()` for the words.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import pytest

from agentdata.fleet import events as E, fleetmap as M, poll as P, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_map import row, snap

GIT_ONLY = {"fleet": {"poll": {"jira": False, "pr": False, "powerbi": False}}}
T0 = 1_700_000_000.0


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture()
def running(fleet_home):
    """A bound server on a free port, stopped however the test ends."""
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}", token
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _until(read, deadline_s: float = 5.0):
    """`read()`'s answer once it is truthy; fails at the deadline. A condition, not a clock."""
    end = time.monotonic() + deadline_s
    while True:
        got = read()
        if got:
            return got
        assert time.monotonic() < end, "the condition never held"
        time.sleep(0.02)


def get(base, token, route) -> dict:
    with urllib.request.urlopen(f"{base}{route}?t={token}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def stream(base, token, query=""):
    """An open `/api/events` stream, read through its first pass (it ends with `tick`)."""
    s = urllib.request.urlopen(f"{base}/api/events?t={token}&since=&{query}", timeout=15)
    seen = ""
    while "event: tick" not in seen:
        line = s.readline().decode("utf-8")
        assert line, f"the stream ended before its first tick:\n{seen}"
        seen += line
    return s, seen


def windows(body) -> dict:
    return {w["name"]: w for w in body["network"]["windows"]}


# ------------------------------------------------------------------------------ live windows


def test_two_streams_are_two_connected_windows_with_their_shells(running, monkeypatch):
    """Acceptance criterion 1."""
    monkeypatch.setattr(S, "poller", lambda: None)
    server, base, token = running
    left, _ = stream(base, token, "w=left")
    pycharm, _ = stream(base, token, "w=pycharm&shell=pycharm")
    try:
        body = get(base, token, "/api/map")
    finally:
        left.close()
        pycharm.close()
    w = windows(body)
    assert w["left"]["connected"] and w["left"]["shell"] == "left"
    assert w["pycharm"]["connected"] and w["pycharm"]["shell"] == "pycharm"
    assert w["left"]["pages"] == ["desk"] and w["left"]["id"] == "w:left" and w["left"]["since"]
    assert w["left"]["says"] == "window left · open on desk"
    assert body["network"]["says"].startswith("the desk server, 2 windows open, ")
    assert ", 2 windows open" in body["says"]


def test_a_hostile_name_is_main_and_a_theme_stream_is_the_settings_page(running, monkeypatch):
    """Acceptance criterion 2."""
    monkeypatch.setattr(S, "poller", lambda: None)
    server, base, token = running
    bad, _ = stream(base, token, "w=%22%3E%3Cscript%3E&page=%3Cb%3E")
    settings, _ = stream(base, token, "w=right&frames=theme")
    try:
        body = get(base, token, "/api/map")
        live = S.live_windows()
    finally:
        bad.close()
        settings.close()
    w = windows(body)
    assert sorted(w) == ["main", "right"]
    assert w["main"]["pages"] == ["desk"] and w["right"]["pages"] == ["settings"]
    assert "script" not in json.dumps(body["network"]) and "<" not in json.dumps(live)


def test_a_closed_stream_reads_disconnected_on_its_next_write(running, tmp_path, monkeypatch):
    """Acceptance criterion 3: an event makes every stream write, and the closed one's write fails.
    `left` is a desk window with a record, so it stays on the map once its stream has gone."""
    monkeypatch.setattr(S, "poller", lambda: None)
    server, base, token = running
    Registry().add(make_project(tmp_path / "luna"), name="luna")
    S.update_window("left", widths={"luna": 1})
    left, _ = stream(base, token, "w=left")
    right, _ = stream(base, token, "w=right")
    try:
        assert windows(get(base, token, "/api/map"))["left"]["connected"]
        left.close()
        E.append("luna", [E.event("luna", "assistant_text", {"text": "a write for everyone"})])
        gone = _until(lambda: (lambda w: not w["left"]["connected"] and w)(
            windows(get(base, token, "/api/map"))))
    finally:
        right.close()
    assert gone["left"]["says"] == "window left · not open" and gone["left"]["pages"] == []
    assert gone["right"]["connected"]


def test_the_registry_is_empty_once_the_server_stops(fleet_home, monkeypatch):
    """Acceptance criterion 7: every entry leaves in the handler's `finally`."""
    monkeypatch.setattr(S, "poller", lambda: None)
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    a, _ = stream(base, token, "w=left")
    b, _ = stream(base, token, "w=right&frames=theme")
    try:
        assert sorted(x["w"] for x in S.live_windows()) == ["left", "right"]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    try:
        assert _until(lambda: S.live_windows() == []) is True
    finally:
        a.close()
        b.close()


def test_a_connect_writes_no_file_and_changes_no_row_or_frame(running, tmp_path, monkeypatch):
    """Acceptance criterion 6: rows and frames as before, no `desk.json`, and no Poller made."""
    monkeypatch.setattr(S, "poller", lambda: None)
    server, base, token = running
    Registry().add(make_project(tmp_path / "luna"), name="luna")
    before = get(base, token, "/api/fleet")["repos"]
    p, plain = stream(base, token, "")
    s, named = stream(base, token, "w=left&shell=pycharm&page=map")
    try:
        during = get(base, token, "/api/fleet")["repos"]
        get(base, token, "/api/map")
    finally:
        s.close()
        p.close()

    def kinds(text):
        return [line for line in text.splitlines() if line.startswith("event: ")]

    assert kinds(named) == kinds(plain), "a named window is sent the frames an unnamed one is"
    assert [sorted(r) for r in during] == [sorted(r) for r in before]
    assert not os.path.exists(S._desk_file()), "a connect wrote desk.json"
    assert S._desk_written == {}, "a connect saved the desk"
    assert S._desk["poller"] is None and S.current_poller() is None, "the map made a poller"

    # The network's own reads never ask for one: `current_poller()`, never `poller()`.
    monkeypatch.setattr(S, "poller", lambda: pytest.fail("map_network asked for a poller"))
    raw = S.map_network(8765)
    assert raw["counts"] is None and raw["port"] == 8765 and set(raw["settings"]) == set(P.SOURCES)


# ------------------------------------------------------------------------------ polled sources


def test_a_failing_reader_greys_its_cells_counts_and_is_named(running, tmp_path, monkeypatch):
    """Acceptance criterion 4: git's reader raises for every checkout."""
    for name in ("luna", "uat"):
        Registry().add(make_project(tmp_path / name), name=name)
    p = P.Poller(Registry(), cfg=GIT_ONLY, now=lambda: T0)

    def unreachable(repo):
        raise OSError(f"SECRET-ERROR-TEXT at {tmp_path} https://example.invalid/?token=SECRET")

    p.git_reader = unreachable
    p.tick(T0)
    monkeypatch.setitem(S._desk, "poller", p)
    server, base, token = running
    body = get(base, token, "/api/map")

    src = {s["id"]: s for s in body["network"]["sources"]}
    assert list(src) == ["s:jira", "s:pr", "s:powerbi", "s:git"]
    git = src["s:git"]
    assert git["name"] == "git" and git["on"] and git["errors"] >= 2
    assert [(c["checkout"], c["ok"]) for c in git["cells"]] == [("c:luna", False), ("c:uat", False)]
    assert git["says"].startswith("git · unreachable for 2 checkouts · ")
    assert not src["s:jira"]["on"] and src["s:jira"]["says"].startswith("Jira · off")
    assert body["says"].endswith(", no windows open, git unreachable for 2 checkouts")
    assert body["network"]["says"] == "the desk server, no windows open, 1 source, no approvals waiting"

    net = json.dumps(body["network"])
    for secret in ("SECRET", str(tmp_path), "http", token, "fleet_dir"):
        assert secret not in net, f"{secret!r} leaked into the network"
    for c in git["cells"]:
        assert set(c) == {"checkout", "ok", "age_s"}


# ------------------------------------------------------------------------------ the pure graph


def cell(grey=False, age=12.34) -> dict:
    return {"source": "x", "interval": 60, "value": {"text": "SECRET-VALUE"}, "age_s": age,
            "error": "SECRET-ERROR https://x/?token=t" if grey else "", "grey": grey}


def polls(**grey) -> dict:
    return {c: cell(grey.get(c, False)) for c in ("ticket", "pr", "refresh", "git")}


ALL_ON = {s: {"on": True, "interval": P.DEFAULT_INTERVALS[s]} for s in P.SOURCES}


def facts(live=(), counts=None, settings=ALL_ON) -> dict:
    return {"port": 8765, "version": "0.16.0", "live": list(live), "counts": counts,
            "settings": settings}


def test_no_network_facts_means_no_network_and_the_old_sentence():
    g = M.graph(snap(row("luna")))
    assert "network" not in g and g["says"] == "1 project, 1 checkout, no agents working, nobody needs you"


@pytest.mark.parametrize("open_n, on, pending, said", [
    (0, 0, 0, "the desk server, no windows open, no sources, no approvals waiting"),
    (1, 1, 1, "the desk server, 1 window open, 1 source, 1 approval waiting"),
    (2, 4, 3, "the desk server, 2 windows open, 4 sources, 3 approvals waiting"),
])
def test_the_network_sentence_in_every_plural_and_zero(open_n, on, pending, said):
    assert M.network_says(open_n, on, pending) == said
    live = [{"w": f"w{i}", "page": "desk", "shell": "", "since": "2026-09-25T00:00:00Z"}
            for i in range(open_n)]
    settings = {s: {"on": i < on} for i, s in enumerate(P.SOURCES)}
    s = snap(row("luna"))
    s["approvals"] = [{"id": f"r{i}"} for i in range(pending)]
    net = M.graph(s, network=facts(live, settings=settings))["network"]
    assert net["says"] == said
    assert net["approvals"] == {"id": "n:approvals", "pending": pending,
                                "says": said.rsplit(", ", 1)[1]}


def test_sources_cells_counts_and_the_unreachable_sentence():
    s = snap(row("luna", polls=polls(refresh=True)), row("uat", polls=polls(refresh=True)),
             row("zed", polls=polls()))
    counts = {"requests": {"jira": 1, "pr": 0, "powerbi": 14, "git": 0},
              "errors": {"powerbi": 2}, "stood_down": {"jira": 1}}
    g = M.graph(s, network=facts(counts=counts))
    src = {x["id"]: x for x in g["network"]["sources"]}
    pbi = src["s:powerbi"]
    assert pbi["name"] == "Power BI" and pbi["requests"] == 14 and pbi["errors"] == 2
    assert pbi["cells"] == [{"checkout": "c:luna", "ok": False, "age_s": 12.3},
                            {"checkout": "c:uat", "ok": False, "age_s": 12.3},
                            {"checkout": "c:zed", "ok": True, "age_s": 12.3}]
    assert pbi["says"] == "Power BI · unreachable for 2 checkouts · 14 requests today · 2 errors"
    assert src["s:jira"]["says"] == "Jira · 3 checkouts answering · 1 request today · 1 stand-down"
    assert src["s:pr"]["says"] == "pull requests · 3 checkouts answering · 0 requests today"
    assert g["says"] == ("3 projects, 3 checkouts, no agents working, nobody needs you, "
                         "no windows open, Power BI unreachable for 2 checkouts")
    one = M.graph(snap(row("luna", polls=polls(refresh=True))), network=facts())
    assert one["says"].endswith(", Power BI unreachable for 1 checkout")
    assert "SECRET" not in json.dumps(g["network"])


def test_a_source_with_no_cells_and_one_turned_off():
    g = M.graph(snap(row("luna")), network=facts(settings={**ALL_ON, "pr": {"on": False}}))
    src = {x["id"]: x for x in g["network"]["sources"]}
    assert src["s:git"]["cells"] == [] and src["s:git"]["says"] == "git · not polled yet · 0 requests today"
    assert src["s:pr"]["says"] == "pull requests · off · 0 requests today"
    assert g["network"]["says"].endswith(", 3 sources, no approvals waiting")


def test_windows_are_the_desk_records_and_the_live_streams_by_name():
    s = snap(row("luna"))
    s["desk"] = {"windows": {"right": {"widths": {"luna": 300}}, "main": {}}}
    live = [{"w": "main", "page": "map", "shell": "", "since": "2026-09-25T10:00:02Z"},
            {"w": "main", "page": "desk", "shell": "", "since": "2026-09-25T10:00:01Z"},
            {"w": "left", "page": "desk", "shell": "pycharm", "since": "2026-09-25T10:00:03Z"}]
    g = M.graph(s, network=facts(live))
    w = g["network"]["windows"]
    assert [x["id"] for x in w] == ["w:left", "w:main", "w:right"]
    assert w[0]["says"] == "window left · pycharm · open on desk"
    assert w[1]["pages"] == ["desk", "map"] and w[1]["since"] == "2026-09-25T10:00:01Z"
    assert w[1]["says"] == "window main · open on desk, map"
    assert w[2] == {"id": "w:right", "name": "right", "shell": "", "pages": [], "connected": False,
                    "since": "", "says": "window right · not open"}
    assert "widths" not in json.dumps(g["network"])
    assert g["says"].endswith(", 2 windows open")


def test_a_window_record_whose_name_is_not_a_name_is_main():
    """`desk.json` keeps whatever `?w=` a page posted; the map says only names, as the stream does."""
    assert M.WINDOW_NAME.pattern == S.SKIN_FAMILY.pattern
    s = snap(row("luna"))
    s["desk"] = {"windows": {'"><script>': {}, "https://example.invalid/x": {}, "C:\\Users\\me": {},
                             "Left": {}, "right": {}}}
    net = M.graph(s, network=facts())["network"]
    assert [w["name"] for w in net["windows"]] == ["main", "right"]
    for bad in ("script", "http", "Users", "Left"):
        assert bad not in json.dumps(net)


def test_the_server_and_the_install_and_who_began_on_an_older_one():
    s = snap(row("luna", stale={"stale": True}), row("uat"), row("zed", stale={"stale": True}))
    s["server"] = {"current": False, "loaded": {"version": "0.15.3"},
                   "installed": {"version": "0.16.0", "commit": "abcdef1234567", "skills": "x"}}
    net = M.graph(s, network=facts())["network"]
    assert net["server"] == {"id": "n:server", "port": 8765, "version": "0.16.0", "current": False,
                             "says": "the desk server · port 8765 · 0.16.0 · not the installed version"}
    assert net["install"] == {"id": "n:install", "version": "0.16.0", "commit": "abcdef1234567",
                              "stale_agents": ["a:luna", "a:zed"],
                              "says": "the install · 0.16.0 (abcdef1) · 2 agents began on an older install"}
    g = M.graph(s, network=facts())
    agents = {c["repo"]: c["agent"] for c in g["checkouts"]}
    assert agents["luna"]["stale_of"] == "n:install" and "stale_of" not in agents["uat"]

    one = snap(row("luna", stale={"stale": True}))
    one["server"] = {"current": True, "installed": {"version": "0.16.0", "commit": ""}}
    said = M.graph(one, network=facts())["network"]["install"]["says"]
    assert said == "the install · 0.16.0 · 1 agent began on an older install"
    none = M.graph(snap(row("luna")), network=facts())["network"]
    assert none["install"]["says"] == "the install · not readable · every agent began on it"
    assert none["server"]["says"] == "the desk server · port 8765 · 0.16.0"


def test_twenty_checkouts_add_under_eight_kib_of_network():
    """Four sources of twenty cells, three windows: the network is a few ids and numbers per cell."""
    rows = [row(f"proj01-feature-{n:02d}", project="proj01", polls=polls(refresh=n % 3 == 0))
            for n in range(20)]
    s = snap(*rows)
    s["desk"] = {"windows": {"main": {}, "left": {}, "right": {}}}
    live = [{"w": w, "page": "desk", "shell": "pycharm", "since": "2026-09-25T10:00:00Z"}
            for w in ("main", "left", "right")]
    counts = {k: {x: 100 for x in P.SOURCES} for k in ("requests", "errors", "stood_down")}
    net = M.graph(s, network=facts(live, counts=counts))["network"]
    assert sum(len(x["cells"]) for x in net["sources"]) == 80
    assert len(json.dumps(net)) < 8 * 1024


def test_the_graph_with_a_network_is_pure():
    s = snap(row("luna", polls=polls(git=True)))
    live = [{"w": "left", "page": "desk", "shell": "left", "since": "2026-09-25T10:00:00Z", "last": 1.0}]
    assert M.graph(s, network=facts(live)) == M.graph(s, network=facts(live))
