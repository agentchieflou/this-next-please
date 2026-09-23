"""WebGL, measured in all four shells (#247, slice A of the ink epic #246).

The operator chose three.js as the desk's one renderer, and `docs/desk-engines.md` said WebGL would
not be used until its rows said all four shells run it. `/probe` is how those rows get filled: the
shell draws a fixed three.js scene for three seconds and posts what it saw to the desk, which keeps
it in `~/.agentdata/fleet/probes.json`. What is asserted here:

* the record's shape, and that the page's facts -- not its opinions -- are what is kept;
* the one rule: a software renderer is a fallback, not a pass, and so is no WebGL at all;
* `ad-fleet engines` and `ad-fleet probe` read the file, and `--open` reaches a desk that is
  already inside an IDE, so nothing is copied by hand;
* the vendored three.js is r160 byte for byte, ships in the wheel, and the desk loads it only
  through the ink layer (#248), once the gate says on and a skin draws.

The measurement of headless Chromium itself -- SwiftShader, classified as software -- lives beside
the rest of the Chromium column, in `tests/test_fleet_engines.py`.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stdout

import pytest

from agentdata import cli_fleet
from agentdata.fleet import opener as O, probe as PR, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
THREE = os.path.join(STATIC, "vendor", "three")
ENGINES = os.path.join(ROOT, "docs", "desk-engines.md")

#: three.js 0.160.0 from the npm registry's tarball (sha1 cd1e4dbd01aee0719280a9086d75545db52b7a8f,
#: the registry's own `dist.shasum`): `package/build/three.module.min.js` and `package/LICENSE`.
THREE_SHA256 = "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6"
LICENSE_SHA256 = "852e0e8699169bf9f6fdc6bda3e682d078dcbc738b5d33e74df594721bff271d"

SWIFTSHADER = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"
INTEL = "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00003EA0) Direct3D11 vs_5_0 ps_5_0, D3D11)"


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"column": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "grid": {"order": [], "size": {}, "pinned": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})
    monkeypatch.setattr(S, "_measure_asks", {})


@pytest.fixture()
def running(fleet_home):
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    S.record(server, token)
    try:
        yield server, token, server.server_address[1]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        S.forget()


def facts(**over) -> dict:
    """What the page posts from a working shell: raw facts, and no verdict among them."""
    body = {"shell": "pycharm", "ua": "Mozilla/5.0 (Windows NT 10.0) JCEF", "webgl": "webgl2",
            "renderer": INTEL, "vendor": "Google Inc. (Intel)", "caveat": False, "three": "160",
            "intervals": [16.6, 16.7, 16.7, 16.8, 16.6, 33.4, 16.7, 16.7, 16.6, 16.7],
            "first_stroke_ms": 131.04, "load_ms": 60.5, "drawn": True, "error": ""}
    body.update(over)
    return body


def post(port, token, action, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/{action}?t={token}",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def cli(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_fleet.main(list(argv))
    return rc, out.getvalue()


def table(text: str, name: str) -> list[dict]:
    """One TOON table out of a command's output, as dicts."""
    m = re.search(rf"^{name}\[(\d+)\]{{([^}}]*)}}:\n((?:  .*\n?)*)", text, re.M)
    assert m, f"no {name} table in:\n{text}"
    cols = m.group(2).split(",")
    rows = [line[2:] for line in m.group(3).splitlines() if line.startswith("  ")]
    parsed = [dict(zip(cols, next(csv.reader([r])))) for r in rows]
    assert len(parsed) == int(m.group(1)), text
    return parsed


# ------------------------------------------------------------------------------ the record


def test_the_record_keeps_facts_in_one_shape():
    rec = PR.normalize(facts())
    assert set(rec) == {"shell", "at", "ua", "webgl", "renderer", "vendor", "caveat", "three",
                        "frames", "p50_ms", "p95_ms", "first_stroke_ms", "load_ms", "drawn",
                        "hidden", "error"}
    assert rec["shell"] == "pycharm" and rec["webgl"] == "webgl2" and rec["renderer"] == INTEL
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", rec["at"]), rec["at"]
    # The intervals are reduced once, here, and not kept: every reader agrees on the arithmetic.
    assert (rec["frames"], rec["p50_ms"], rec["p95_ms"]) == (10, 16.7, 33.4)
    assert rec["first_stroke_ms"] == 131.0 and rec["load_ms"] == 60.5
    # No verdict is stored: a pattern added later reclassifies every record already on disk.
    assert "class" not in rec and "verdict" not in rec and "intervals" not in rec


def test_percentiles_are_nearest_rank_and_ignore_what_is_not_a_frame():
    assert PR.percentile([], 50) is None
    assert PR.percentile(list(range(1, 21)), 50) == 10
    assert PR.percentile(list(range(1, 21)), 95) == 19
    assert PR.percentile([7.0], 95) == 7.0
    rec = PR.normalize(facts(intervals=[16.7, "x", None, -3, float("inf"), 1e9, 20.0]))
    assert rec["frames"] == 2 and rec["p95_ms"] == 20.0


def test_a_probe_the_desk_cannot_read_is_refused_by_name():
    with pytest.raises(PR.ProbeError) as e:
        PR.normalize(facts(shell="Py Charm; rm"))
    assert e.value.code == "probe_shell"
    with pytest.raises(PR.ProbeError) as e:
        PR.normalize(facts(webgl="webgpu"))
    assert e.value.code == "probe_shape"
    with pytest.raises(PR.ProbeError):
        PR.normalize(facts(intervals="16.7"))


# ------------------------------------------------------------------------------- the one rule


@pytest.mark.parametrize("renderer,name", [
    (SWIFTSHADER, "SwiftShader"),
    ("Google SwiftShader", "SwiftShader"),
    ("ANGLE (Mesa, llvmpipe (LLVM 15.0.7, 256 bits), OpenGL 4.5)", "llvmpipe"),
    ("llvmpipe (LLVM 12.0.0, 256 bits)", "llvmpipe"),
    ("ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0, D3D11)",
     "Microsoft Basic Render Driver"),
    ("ANGLE (Mesa, lavapipe (LLVM 15.0.7, 256 bits), Vulkan 1.3)", "lavapipe"),
    ("Apple Software Renderer", "Apple Software Renderer"),
])
def test_a_software_renderer_falls_back_rather_than_works(renderer, name):
    """The acceptance criterion: software draws correctly, at software speed, and counts as a
    fallback -- the same answer as no WebGL at all."""
    rec = PR.normalize(facts(renderer=renderer))
    assert PR.software_name(renderer) == name
    assert PR.classify(rec) == "software"
    assert PR.verdict(rec) == f"falls back — software ({name})"
    assert PR.works(rec) is False


@pytest.mark.parametrize("renderer", [
    INTEL,
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Laptop GPU (0x00002560) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (AMD, AMD Radeon(TM) Graphics (0x00001638) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)",
])
def test_a_hardware_renderer_works(renderer):
    rec = PR.normalize(facts(renderer=renderer))
    assert PR.classify(rec) == "hardware" and PR.verdict(rec) == "works" and PR.works(rec)


def test_no_webgl_an_undrawn_scene_and_an_unnamed_renderer_all_fall_back():
    none = PR.normalize(facts(webgl="none", renderer="", intervals=[], drawn=False,
                              error="no WebGL: getContext answered null"))
    assert PR.classify(none) == "none" and PR.verdict(none) == "falls back — no WebGL"
    undrawn = PR.normalize(facts(drawn=False, error="the first frame rendered and holds no stroke"))
    assert PR.classify(undrawn) == "none"
    # The browser's own word for software, with a string that does not say so.
    caveat = PR.normalize(facts(caveat=True))
    assert PR.classify(caveat) == "software"
    assert PR.verdict(caveat) == "falls back — software (major performance caveat)"
    unnamed = PR.normalize(facts(renderer=""))
    assert PR.classify(unnamed) == "unknown" and PR.verdict(unnamed).startswith("falls back")
    assert not any(PR.works(r) for r in (none, undrawn, caveat, unnamed))
    assert PR.verdict(None) == "not yet measured"


def test_a_probe_that_did_not_finish_is_not_a_measurement():
    """#261: a GPU string on a probe whose context was lost a second in, or on a window hidden
    straight after its first frame, is evidence of nothing -- and `hardware` is the one class that
    turns the ink layer on. They are `incomplete`: *not yet measured*, never *works*."""
    lost = PR.normalize(facts(error="the WebGL context was lost while drawing"))
    no_frames = PR.normalize(facts(intervals=[]))
    few = PR.normalize(facts(intervals=[16.7] * (PR.MIN_FRAMES - 1)))
    hidden = PR.normalize(facts(hidden=True, drawn=False, intervals=[],
                                error="the window was hidden while it drew"))
    for rec in (lost, no_frames, few, hidden):
        assert PR.classify(rec) == "incomplete", rec
        assert PR.works(rec) is False
        assert PR.verdict(rec).startswith("not yet measured — the probe did not finish")
    assert "context was lost" in PR.verdict(lost)
    # Hidden is checked before `drawn`: a window that never got a frame did not fail to draw.
    assert PR.classify(hidden) == "incomplete"
    # A software string still says software, finished or not: it falls back either way.
    assert PR.classify(PR.normalize(facts(renderer=SWIFTSHADER, intervals=[]))) == "software"
    assert PR.classify(PR.normalize(facts(intervals=[16.7] * PR.MIN_FRAMES))) == "hardware"


def test_every_verdict_is_a_word_the_engines_table_accepts():
    """`test_every_cell_is_filled_in_or_says_it_is_not_measured` allows four openings; the probe's
    cells are pasted into that table, so they must open with one of them."""
    allowed = ("works", "falls back", "not yet measured")
    for rec in (facts(), facts(renderer=SWIFTSHADER), facts(webgl="none"), facts(renderer=""),
                facts(caveat=True), facts(error="lost"), facts(hidden=True)):
        assert PR.verdict(PR.normalize(rec)).startswith(allowed)


def test_the_columns_are_the_ones_desk_engines_names():
    doc = open(ENGINES, encoding="utf-8").read()
    rows = doc.split("\n## The rows\n", 1)[1]
    header = next(line for line in rows.splitlines() if line.startswith("| Feature"))
    columns = [c.strip() for c in header.strip("|").split("|")][1:]
    assert list(PR.COLUMNS.values()) == columns


# -------------------------------------------------------------------------------- the file


def test_the_desk_keeps_one_record_per_shell(fleet_home):
    PR.record(facts(shell="pycharm"))
    PR.record(facts(shell="edge", renderer=SWIFTSHADER))
    PR.record(facts(shell="pycharm", renderer=SWIFTSHADER))
    data = json.loads(open(os.path.join(str(fleet_home), "probes.json"), encoding="utf-8").read())
    assert data["schema"] == 1 and set(data["probes"]) == {"pycharm", "edge"}
    assert data["probes"]["pycharm"]["renderer"] == SWIFTSHADER, "the newer record replaces"
    assert os.path.dirname(PR.probes_file()) == registry.fleet_dir()


def test_a_probe_that_did_not_finish_never_replaces_one_that_did(fleet_home):
    """#261: last week's *works*, then a tool window hidden a second into the probe. The record
    that stands is last week's; the hidden one is the shell's latest attempt, which is what the
    page and `ad-fleet probe --open` report."""
    PR.record(facts(shell="pycharm"))
    answer = PR.record(facts(shell="pycharm", hidden=True, drawn=False, intervals=[],
                             error="the window was hidden while it drew"))
    assert answer["class"] == "incomplete" and answer["kept"] is True
    assert answer["kept_verdict"] == "works" and answer["kept_at"]
    assert PR.classify(PR.load()["pycharm"]) == "hardware"
    assert PR.attempts()["pycharm"]["hidden"] is True

    # With nothing finished to protect, the attempt is the record: "did not finish" is an answer.
    first = PR.record(facts(shell="vscode", intervals=[]))
    assert first["kept"] is False and PR.classify(PR.load()["vscode"]) == "incomplete"
    # And a finished probe always replaces, whatever stood before.
    PR.record(facts(shell="pycharm", renderer=SWIFTSHADER))
    assert PR.classify(PR.load()["pycharm"]) == "software"


def test_an_unreadable_file_is_no_records(fleet_home):
    os.makedirs(str(fleet_home), exist_ok=True)
    open(os.path.join(str(fleet_home), "probes.json"), "w", encoding="utf-8").write("{nope")
    assert PR.load() == {}
    PR.record(facts())
    assert set(PR.load()) == {"pycharm"}


# ------------------------------------------------------------------------------ the route


def test_the_probe_is_posted_like_every_other_action(running):
    """Token and loopback, as every POST on this server; a refusal in the server's own words."""
    _server, token, port = running
    with pytest.raises(urllib.error.HTTPError) as e:
        post(port, "wrong", "probe", facts())
    assert e.value.code == 403
    assert not os.path.exists(PR.probes_file())

    status, answer = post(port, token, "probe", facts(renderer=SWIFTSHADER))
    assert status == 200 and answer["ok"] is True and answer["action"] == "probe"
    assert answer["class"] == "software" and answer["verdict"] == "falls back — software (SwiftShader)"
    assert answer["record"]["shell"] == "pycharm" and PR.load()["pycharm"]["frames"] == 10

    with pytest.raises(urllib.error.HTTPError) as e:
        post(port, token, "probe", facts(shell="../../etc"))
    assert e.value.code == 409
    body = json.loads(e.value.read())
    assert body["ok"] is False and body["code"] == "probe_shell" and body["hint"]


def test_the_probe_page_and_three_need_the_token_and_arrive_with_it(running):
    _server, token, port = running
    base = f"http://127.0.0.1:{port}"
    for path in ("/probe", "/static/probe.js", "/static/vendor/three/three.module.min.js"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + path, timeout=10)
        assert e.value.code == 403, path

    html = urllib.request.urlopen(f"{base}/probe?t={token}", timeout=10).read().decode()
    refs = re.findall(r'src="(/static/[^"]+)"', html)
    assert refs == [f"/static/common.js?t={token}", f"/static/probe.js?t={token}"], refs
    assert '<script type="module"' in html
    for ref in refs:
        with urllib.request.urlopen(base + ref, timeout=10) as r:
            assert r.status == 200 and r.read()
    with urllib.request.urlopen(f"{base}/static/vendor/three/three.module.min.js?t={token}",
                                timeout=10) as r:
        assert "javascript" in r.headers["Content-Type"]
        assert hashlib.sha256(r.read()).hexdigest() == THREE_SHA256


def test_open_page_probe_is_the_stable_address_of_the_probe(running):
    """What goes on the clipboard for VS Code's Simple Browser: tokenless, and still right tomorrow."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    _server, token, port = running
    opener = urllib.request.build_opener(NoRedirect)
    for asked, landed in (("/open?page=probe&w=vscode", f"/probe?t={token}&w=vscode"),
                          ("/open?page=nowhere&w=left", f"/?t={token}&w=left")):
        with pytest.raises(urllib.error.HTTPError) as e:
            opener.open(f"http://127.0.0.1:{port}{asked}", timeout=10)
        assert e.value.code == 302 and e.value.headers["Location"] == landed, asked


# -------------------------------------------------------------------------------- the CLI


def test_ad_fleet_engines_reads_the_file(fleet_home):
    PR.record(facts(shell="chromium", renderer=SWIFTSHADER))
    PR.record(facts(shell="pycharm"))
    PR.record(facts(shell="browser", webgl="none", renderer="", intervals=[], drawn=False))
    rc, out = cli("engines")
    assert rc == 0
    assert "source: ad-fleet engines" in out and "measured: 3" in out, out
    rows = {r["shell"]: r for r in table(out, "engines")}
    assert list(rows) == ["chromium", "edge", "pycharm", "vscode", "browser"]
    assert rows["chromium"]["column"] == "Chromium 141"
    assert rows["chromium"]["webgl"] == "falls back — software (SwiftShader)"
    assert rows["pycharm"]["webgl"] == "works" and rows["pycharm"]["p50_ms"] == "16.7"
    assert rows["edge"]["webgl"] == rows["vscode"]["webgl"] == "not yet measured"
    assert rows["browser"]["webgl"] == "falls back — no WebGL"


def test_ad_fleet_engines_with_nothing_measured_says_so(fleet_home):
    rc, out = cli("engines")
    assert rc == 0 and "measured: 0" in out
    assert {r["webgl"] for r in table(out, "engines")} == {"not yet measured"}


def test_ad_fleet_probe_lists_the_facts_and_the_class(fleet_home):
    PR.record(facts(shell="edge", renderer=SWIFTSHADER))
    rc, out = cli("probe")
    assert rc == 0
    (row,) = table(out, "probes")
    assert row["shell"] == "edge" and row["class"] == "software" and row["three"] == "160"
    assert row["renderer"] == SWIFTSHADER


def test_probe_open_asks_the_ide_window_and_prints_what_it_posted(running, monkeypatch):
    """PyCharm's tool window cannot be pointed at a URL from outside; the desk inside it can be
    asked. The CLI marks the window's record, waits for the shell's own answer in the file, and
    prints it -- the whole of "nothing to copy by hand", without a browser."""
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    _server, token, port = running

    def the_shell_answers():
        deadline = time.time() + 10
        while time.time() < deadline:
            if S._measure_asks.get("pycharm"):
                post(port, token, "probe", facts(shell="pycharm"))
                return
            time.sleep(0.05)

    threading.Thread(target=the_shell_answers, daemon=True).start()
    rc, out = cli("probe", "--open", "pycharm", "--wait", "15")
    assert rc == 0, out
    assert "asked the desk's `pycharm` window to go to the probe" in out
    assert "server: already up" in out, "the probe is asked of a current desk (#242)"
    assert "arrived: true" in out and "class: hardware" in out and "webgl: works" in out
    assert "/open?page=probe&w=pycharm" in out, "the stable URL is the fallback, not the token"
    assert token not in out
    (row,) = table(out, "probes")
    assert row["shell"] == "pycharm"


def test_probe_open_says_when_nothing_answered(running, monkeypatch):
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    rc, out = cli("probe", "--open", "vscode", "--wait", "0")
    assert rc == 0 and "arrived: false" in out and "ad-fleet engines" in out
    assert S.desk_state()["measure"].get("vscode", 0) > 0
    assert "Simple Browser" in out


def test_probe_open_reports_a_probe_that_arrived_and_did_not_finish(running, monkeypatch):
    """The attempt is what the CLI waits for, so a hidden window's post is reported -- with the
    measurement that still stands -- rather than waited out as silence (#261)."""
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    _server, token, port = running
    PR.record(facts(shell="pycharm"))

    def the_hidden_shell_answers():
        deadline = time.time() + 10
        while time.time() < deadline:
            if S._measure_asks.get("pycharm"):
                post(port, token, "probe", facts(shell="pycharm", hidden=True, drawn=False,
                                                 intervals=[], error="hidden while it drew"))
                return
            time.sleep(0.05)

    threading.Thread(target=the_hidden_shell_answers, daemon=True).start()
    rc, out = cli("probe", "--open", "pycharm", "--wait", "15")
    assert rc == 0 and "arrived: true" in out and "class: incomplete" in out, out
    assert "measurement stands: works" in out, out


def test_probe_open_asks_a_current_desk(fleet_home, monkeypatch):
    """#242: the first thing run on the laptop after `ad-update` is this command, and last week's
    server has neither `/probe` nor `measure`. The desk it asks is the one `ad-fleet open` would
    use -- and a desk that would not be replaced is a refusal, not a sixty-second wait."""
    monkeypatch.setattr(O, "running", lambda: pytest.fail("the probe asked whatever desk was up"))

    def stuck(port):
        raise O.OpenError("the desk on port 8765 is running 0.14.0 and would not stop",
                          "stop it by hand (Ctrl-C in its window), then `ad-fleet open` again")

    monkeypatch.setattr(O, "current_desk", stuck)
    started = time.time()
    rc, out = cli("probe", "--open", "pycharm", "--wait", "30")
    assert rc != 0 and "would not stop" in out and "ok: false" in out, out
    assert time.time() - started < 5


def test_probe_open_edge_without_edge_opens_nothing_and_labels_nothing(fleet_home, monkeypatch):
    """#261: the clipboard fallback put `/open?page=probe&shell=edge` in reach of whatever browser
    was open, and pasting it there filed that browser's renderer under `edge`."""
    monkeypatch.setattr(O, "edge_exe", lambda: "")
    monkeypatch.setattr(O, "clipboard", lambda text: pytest.fail(f"put {text} on the clipboard"))
    monkeypatch.setattr(O, "current_desk", lambda port: pytest.fail("started a desk for nothing"))
    started = time.time()
    rc, out = cli("probe", "--open", "edge", "--wait", "30")
    assert rc != 0 and "Edge was not found" in out and "--open browser" in out, out
    assert "--in" not in out, "the hint names a flag this command does not take"
    assert time.time() - started < 5


def test_probe_open_does_not_wait_when_nothing_was_asked(running, monkeypatch):
    """#261: a desk that refused the ask has no window on its way to the probe; the full `--wait`
    was a minute spent waiting for nothing."""
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    monkeypatch.setattr(O, "post_action", lambda record, action, body, timeout=5.0:
                        {"ok": False, "error": "unknown action 'measure'"})
    started = time.time()
    rc, out = cli("probe", "--open", "pycharm", "--wait", "30")
    assert rc == 0 and "opened: nothing" in out and "arrived: false" in out, out
    assert "unknown action" in out
    assert time.time() - started < 5


# --------------------------------------------------------------------------------- the ask


def test_an_ask_is_taken_once_and_lives_in_memory_only(fleet_home):
    """#261: the one-shot "go and measure" is not state. It reaches every window in the desk frame
    (the version moves), is claimed by exactly one of them, and is never written to desk.json."""
    before = S.desk_state()["version"]
    state = S.measure("pycharm")
    assert state["measure"]["pycharm"] > 0 and state["version"] == before + 1
    desk_json = os.path.join(str(fleet_home), S.DESK_FILE)
    if os.path.exists(desk_json):
        on_disk = open(desk_json, encoding="utf-8").read()
        assert "measure" not in on_disk and '"probe"' not in on_disk, on_disk

    assert S.measure("pycharm", take=True)["go"] is True
    assert S.measure("pycharm", take=True)["go"] is False, "a second desk went round too"
    assert "pycharm" not in S.desk_state()["measure"]
    with pytest.raises(S.ServeError):
        S.measure("")


def test_an_ask_older_than_ten_minutes_is_dropped_not_obeyed(fleet_home, monkeypatch):
    """A tool window opened tomorrow asked for the desk, not for a measurement. The server drops
    the ask, so the desk's `take` answers `go: false` and it stays where it is."""
    S.measure("pycharm")
    real = time.time
    monkeypatch.setattr(S.time, "time", lambda: real() + S.MEASURE_ASK_S + 1)
    assert S.desk_state()["measure"] == {}
    assert S.measure("pycharm", take=True) == {"w": "pycharm", "go": False, "asked": 0}


def test_the_ask_is_an_action_like_every_other(running):
    _server, token, port = running
    status, answer = post(port, token, "measure", {"w": "vscode"})
    assert status == 200 and answer["ok"] is True and answer["measure"]["vscode"] > 0
    status, answer = post(port, token, "measure", {"w": "vscode", "take": True})
    assert answer["go"] is True
    # The old window-record mark is gone: a `probe` key on /api/window is just ignored.
    status, answer = post(port, token, "window", {"w": "vscode", "probe": float("inf")})
    assert status == 200 and "probe" not in answer["windows"]["vscode"]


# ---------------------------------------------------------------------------- the vendoring


def test_the_vendored_three_is_r160_byte_for_byte():
    """MIT, from the npm tarball, with its licence beside it. A file that is not these bytes is not
    the library the operator chose, whatever its header says."""
    body = open(os.path.join(THREE, "three.module.min.js"), "rb").read()
    assert hashlib.sha256(body).hexdigest() == THREE_SHA256
    assert b'const t="160"' in body[:400] and b"SPDX-License-Identifier: MIT" in body[:200]
    licence = open(os.path.join(THREE, "LICENSE"), "rb").read()
    assert hashlib.sha256(licence).hexdigest() == LICENSE_SHA256
    assert b"The MIT License" in licence and b"three.js authors" in licence


def test_the_desk_loads_three_only_through_the_ink_layer_and_the_probe_imports_it_from_the_package():
    """Slice A changed nothing anyone sees, and slice B (#248) keeps it so: the desk's own files
    never name three.js. The ink layer's `layer.js` is the one module of the desk that imports it --
    from the package, with the token -- and it is fetched only when the gate says on and a skin
    draws (`tests/test_fleet_ink.py` holds that in a browser). The probe imports it the same way."""
    for name in ("index.html", "settings.html", "app.js", "common.js", "settings.js", "app.css",
                 os.path.join("ink", "ink.js"), os.path.join("ink", "shapes.js"),
                 os.path.join("ink", "pen.js")):
        body = open(os.path.join(STATIC, name), encoding="utf-8").read()
        for needle in ("vendor/three", "three.module"):
            assert needle not in body, f"{name} names {needle}"
    for name in ("app.js", "common.js", "settings.js"):
        body = open(os.path.join(STATIC, name), encoding="utf-8").read()
        assert "THREE." not in body, name
    layer = open(os.path.join(STATIC, "ink", "layer.js"), encoding="utf-8").read()
    assert 'const VENDOR = "/static/vendor/three/three.module.min.js";' in layer
    assert "import(q(VENDOR))" in layer
    js = open(os.path.join(STATIC, "probe.js"), encoding="utf-8").read()
    assert 'import(q("/static/vendor/three/three.module.min.js"))' in js
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js


def test_the_wheel_globs_reach_the_vendored_files():
    body = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert '"fleet/static/**/*"' in body
    attrs = open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8").read()
    assert "agentdata/fleet/static/vendor/** -text" in attrs, \
        "autocrlf would rewrite the vendored bytes on a Windows checkout"


@pytest.mark.slow
def test_the_wheel_ships_three_and_the_probe(tmp_path):
    out = tmp_path / "w"
    # `--ignore-requires-python`: this asks what the wheel CONTAINS, which is the same on every
    # interpreter, so a machine below the floor can still answer it.
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--ignore-requires-python",
                        "-w", str(out), ROOT], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    whl = next(out.glob("agentdata-*.whl"))
    with zipfile.ZipFile(whl) as z:
        names = set(z.namelist())
        for need in ("agentdata/fleet/static/vendor/three/three.module.min.js",
                     "agentdata/fleet/static/vendor/three/LICENSE",
                     "agentdata/fleet/static/probe.html", "agentdata/fleet/static/probe.js",
                     "agentdata/fleet/probe.py"):
            assert need in names, need
        shipped = z.read("agentdata/fleet/static/vendor/three/three.module.min.js")
    assert hashlib.sha256(shipped).hexdigest() == THREE_SHA256


# ------------------------------------------------------------------------------ the browser


def _wait_saved(page):
    page.wait_for_function(
        "() => /saved|not saved/.test(document.getElementById('state').textContent)",
        timeout=30000)


@pytest.mark.browser
def test_a_shell_without_webgl_says_so_and_posts_once(running):
    """The honest page: no context, the browser's reason kept, one post, and no three.js fetched
    for a scene that cannot be drawn."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _server, token, port = running
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.add_init_script("""
          const real = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function (kind, attrs) {
            if (/webgl/.test(String(kind))) return null;
            return real.call(this, kind, attrs);
          };
        """)
        asked = []
        page.on("request", lambda r: asked.append((r.method, r.url.split("?")[0])))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=edge")
        _wait_saved(page)
        page.wait_for_timeout(300)
        shown = page.text_content("#verdict")
        browser.close()
    assert errors == []
    assert [a for a in asked if a[0] == "POST"] == [("POST", f"http://127.0.0.1:{port}/api/probe")]
    assert not [a for a in asked if "vendor/three" in a[1]]
    rec = PR.load()["edge"]
    assert rec["webgl"] == "none" and rec["error"].startswith("no WebGL") and rec["frames"] == 0
    assert PR.classify(rec) == "none" and "falls back — no WebGL" in shown


@pytest.mark.browser
def test_an_ide_window_goes_to_the_probe_by_itself_and_comes_back(running, tmp_path, monkeypatch):
    """The whole slice, end to end, as the operator will run it: a desk open as the `pycharm`
    window, `ad-fleet probe --open pycharm` in a terminal, and nothing else. The window goes to the
    probe, draws, posts once, returns to the desk -- and the terminal prints the shell's answer.
    The desk page itself never asks for three.js: nothing has measured this shell as hardware, and
    no skin draws with ink (#248)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    monkeypatch.setattr(O, "clipboard", lambda text: False)
    Registry().add(make_project(tmp_path / "alpha"), name="alpha")
    _server, token, port = running
    printed = {}

    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        asked = []
        page.on("request", lambda r: asked.append((r.method, r.url.split("?")[0])))
        page.goto(f"http://127.0.0.1:{port}/?t={token}&w=pycharm&layout=grid")
        page.wait_for_selector(".tile", timeout=15000)
        assert not [a for a in asked if "three" in a[1]], "the desk loaded three.js"

        terminal = threading.Thread(
            target=lambda: printed.update(zip(("rc", "out"), cli("probe", "--open", "pycharm",
                                                                 "--wait", "40"))),
            daemon=True)
        terminal.start()
        page.wait_for_url("**/probe?**", timeout=15000)
        assert "w=pycharm" in page.url and "back=1" in page.url
        _wait_saved(page)
        page.wait_for_url(lambda u: "/probe" not in u, timeout=20000)
        page.wait_for_selector(".tile", timeout=15000)
        page.wait_for_timeout(1200)
        assert "/probe" not in page.url, "the desk went round again"
        terminal.join(timeout=45)
        browser.close()

    assert [a for a in asked if a == ("POST", f"http://127.0.0.1:{port}/api/probe")] == \
        [("POST", f"http://127.0.0.1:{port}/api/probe")]
    assert printed.get("rc") == 0, printed
    assert "arrived: true" in printed["out"] and "class: software" in printed["out"], printed["out"]
    assert "pycharm" not in S.desk_state()["measure"]


MASK_THE_RENDERER = """
  for (const C of [WebGLRenderingContext, WebGL2RenderingContext]) {
    const real = C.prototype.getExtension;
    C.prototype.getExtension = function (name) {
      return name === 'WEBGL_debug_renderer_info' ? null : real.call(this, name);
    };
  }
"""

HIDDEN_UNTIL_SHOWN = """
  window.__hidden = true;
  Object.defineProperty(Document.prototype, 'hidden',
                        {configurable: true, get() { return window.__hidden; }});
  Object.defineProperty(Document.prototype, 'visibilityState',
                        {configurable: true, get() { return window.__hidden ? 'hidden' : 'visible'; }});
  window.__show = function (on) {
    window.__hidden = !on;
    document.dispatchEvent(new Event('visibilitychange'));
  };
"""


@pytest.mark.browser
def test_a_browser_that_will_not_unmask_its_renderer_is_not_called_hardware(running):
    """#261: without `WEBGL_debug_renderer_info` the masked `RENDERER` is "WebKit WebGL" -- never
    empty, so it read as a GPU. The page now sends nothing it cannot vouch for."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _server, token, port = running
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.add_init_script(MASK_THE_RENDERER)
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=browser")
        _wait_saved(page)
        shown = page.text_content("#renderer")
        browser.close()
    rec = PR.load()["browser"]
    assert rec["renderer"] == "" and rec["vendor"] == "", rec
    assert PR.classify(rec) in ("unknown", "software") and not PR.works(rec), rec
    assert "not named" in shown


@pytest.mark.browser
def test_a_hidden_window_waits_to_be_shown_and_then_measures(running):
    """#261: a VS Code view kept alive while hidden still gets the ask and comes to the probe. It
    posts nothing while hidden -- a hidden page has no frames to measure -- and measures when it
    is looked at."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _server, token, port = running
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.add_init_script(HIDDEN_UNTIL_SHOWN)
        posts = []
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=vscode")
        page.wait_for_function(
            "() => /waiting for this window/.test(document.getElementById('state').textContent)",
            timeout=15000)
        page.wait_for_timeout(1500)
        assert posts == [], "a hidden window posted"
        page.evaluate("() => __show(true)")
        _wait_saved(page)
        browser.close()
    rec = PR.load()["vscode"]
    assert rec["hidden"] is False and rec["drawn"] is True and rec["frames"] >= PR.MIN_FRAMES, rec
    assert PR.classify(rec) != "incomplete"


@pytest.mark.browser
def test_a_window_hidden_while_it_draws_does_not_overwrite_the_measurement(running):
    """#261: hidden mid-draw, it posts what it had, marked hidden -- and last week's record stands."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _server, token, port = running
    PR.record(facts(shell="vscode"))
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.add_init_script(HIDDEN_UNTIL_SHOWN.replace("window.__hidden = true;",
                                                        "window.__hidden = false;"))
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=vscode")
        page.wait_for_function(
            "() => /drawing/.test(document.getElementById('state').textContent)", timeout=15000)
        page.wait_for_timeout(500)
        page.evaluate("() => __show(false)")
        _wait_saved(page)
        state = page.text_content("#state")
        browser.close()
    assert "latest attempt only" in state and "stands (works)" in state, state
    assert PR.classify(PR.load()["vscode"]) == "hardware"
    assert PR.attempts()["vscode"]["hidden"] is True


@pytest.mark.browser
def test_a_refused_save_still_takes_the_ide_window_back(running):
    """#261: a desk replaced mid-probe (new token, 403) left a tool window on "not saved" with no
    link and no address bar. The way back is shown before the post and taken whatever it says."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _server, token, port = running
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.route("**/api/probe**", lambda route: route.fulfill(
            status=403, content_type="application/json",
            body=json.dumps({"ok": False, "error": "not authorized", "hint": "a new desk"})))
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}&w=pycharm&back=1")
        page.wait_for_function(
            "() => document.getElementById('verdict').textContent === 'not saved'", timeout=30000)
        assert "not authorized" in page.text_content("#state")
        page.wait_for_function(
            "() => { const b = document.getElementById('back');"
            "        return !b.hidden && /back to the desk \\(in \\d+ s\\)/.test(b.textContent); }",
            timeout=5000)
        href = page.get_attribute("#back", "href")
        page.wait_for_url(lambda u: "/probe" not in u and "/?t=" in u, timeout=15000)
        landed = page.url
        browser.close()
    assert "w=pycharm" in landed, landed
    # Tokenless, through `/open`: the desk that answers it may be a new one with a new token.
    assert "/open?" in href and "w=pycharm" in href, href
    assert "t=" not in href.split("?", 1)[1].split("&")[0] and token not in href, href
    assert "back=" not in href and "shell=" not in href, href


@pytest.mark.browser
def test_a_desk_with_a_half_typed_reply_waits_before_it_goes(running, tmp_path, monkeypatch):
    """#261: `goProbe` navigated the moment the ask arrived, and half a reply in a tile went with
    the page. It says what it is waiting for and goes once the box is empty -- and the ask stays
    the server's until then, so nothing else takes it meanwhile."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    Registry().add(make_project(tmp_path / "alpha"), name="alpha")
    _server, token, port = running
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(f"http://127.0.0.1:{port}/?t={token}&w=pycharm&layout=grid")
        box = page.locator('.tile[data-repo="alpha"] .say')
        box.wait_for(timeout=15000)
        box.fill("half a reply")
        S.measure("pycharm")
        page.wait_for_function(
            "() => /asked this window to go to the probe/.test(document.body.textContent)",
            timeout=10000)
        page.wait_for_timeout(1500)
        assert "/probe" not in page.url, "the desk left with a reply half typed"
        assert S._measure_asks.get("pycharm"), "the ask was taken while the desk stayed"
        box.fill("")
        page.wait_for_url("**/probe?**", timeout=10000)
        browser.close()
    assert "pycharm" not in S.desk_state()["measure"]
