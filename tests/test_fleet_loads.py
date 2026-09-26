"""The opt-in loads store, `POST /api/load` and the `loads` table of `ad-fleet engines` (#350).

* Off by default: the switch is `fleet.loads.enabled` in the config file, read on every post, so
  with it absent or false nothing is written and a running server stops the moment it goes false.
* On: one record per page load, the newest `KEEP` per shell, page and from; `from` is its own group
  because settings -> desk and a cold open are both `navigate`. A second post from the same
  document (the same `origin_ms`) is folded into its record (#531).
* A known key with a value the store cannot take is refused as `load_shape`, in-process and as a
  409 over the wire; an unknown key is dropped.
* `rows()` is nearest-rank p50/p95 and the settled %, and `ad-fleet engines` prints it.
"""
from __future__ import annotations
import csv
import io
import itertools
import json
import os
import re
import time
import urllib.error
import urllib.request
from contextlib import redirect_stdout

import pytest

from agentdata import cli_fleet
from agentdata import config as C
from agentdata.fleet import loads as L, probe as PR, registry, serve as S

from test_fleet_ink import _serve, _stop


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    """A fleet directory of our own; the config file is the one `isolated_home` already moved."""
    home = tmp_path / "fleet"
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(home))
    return home


@pytest.fixture()
def switched_on(fleet_home):
    C.save({"fleet": {"loads": {"enabled": True}}})
    return fleet_home


_OPENED = itertools.count()
_T0 = time.time() * 1000.0


def good(**over) -> dict:
    """What a desk page posts after a cold open in PyCharm: each call its own document (#531), so
    two calls never share a `performance.timeOrigin`, however coarse this machine's clock."""
    body = {"shell": "pycharm", "page": "desk", "from": "", "how": "navigate",
            "origin_ms": _T0 + next(_OPENED), "first_paint_ms": 120.5, "fleet_ms": 240.0,
            "ink_first_frame_ms": 310.0, "longest_task_ms": 45.0,
            "skin_first": "paper", "skin_settled": "paper", "ua": "Mozilla/5.0 JCEF"}
    body.update(over)
    return body


def cli(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_fleet.main(list(argv))
    return rc, out.getvalue()


def table(text: str, name: str) -> list[dict]:
    """One TOON table out of a command's output, as dicts."""
    m = re.search(rf"^{name}\[(\d+)\]{{([^}}]*)}}:\n?((?:  .*\n?)*)", text, re.M)
    assert m, f"no {name} table in:\n{text}"
    cols = m.group(2).split(",")
    rows = [line[2:] for line in m.group(3).splitlines() if line.startswith("  ")]
    parsed = [dict(zip(cols, next(csv.reader([r])))) for r in rows]
    assert len(parsed) == int(m.group(1)), text
    return parsed


def meta(text: str) -> dict[str, str]:
    """The `meta:` block's scalar lines, TOON quoting undone."""
    out = {}
    for line in text.splitlines()[1:]:
        if not line.startswith("  "):
            break
        key, _, value = line.strip().partition(": ")
        out[key] = next(csv.reader([value]))[0] if value else ""
    return out


def _file(home) -> str:
    return os.path.join(str(home), L.LOADS_FILE)


def _post(port: int, token: str, body: dict):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/load?t={token}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return urllib.request.urlopen(req, timeout=10)


# ------------------------------------------------------------------------------------ off


def test_with_the_switch_absent_or_false_nothing_is_recorded_and_engines_says_how(fleet_home):
    assert S.act("load", good()) == {"kept": 0, "enabled": False}
    C.save({"fleet": {"loads": {"enabled": False}}})
    assert S.act("load", good()) == {"kept": 0, "enabled": False}
    # Only `true` is on: a truthy string in the file is not the operator saying yes.
    C.save({"fleet": {"loads": {"enabled": "yes"}}})
    assert S.act("load", good()) == {"kept": 0, "enabled": False}
    assert not os.path.exists(_file(fleet_home))

    rc, out = cli("engines")
    assert rc == 0
    assert "loads: off" in out, out
    hint = meta(out)["hint"]
    assert '"fleet": {"loads": {"enabled": true}}' in hint and C.display_path(C.path()) in hint, hint
    assert table(out, "loads") == []
    assert not os.path.exists(_file(fleet_home))


def test_an_unreadable_config_file_is_off():
    os.makedirs(os.path.dirname(C.path()), exist_ok=True)
    with open(C.path(), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert L.enabled() is False


# ------------------------------------------------------------------------------------- on


def test_with_the_switch_on_one_post_stores_one_record_of_known_fields(switched_on):
    assert S.act("load", good(extra="dropped", renderer="nobody asked")) == {"kept": 1}
    data = json.loads(open(_file(switched_on), encoding="utf-8").read())
    assert len(data["loads"]) == 1
    rec = data["loads"][0]
    assert set(rec) == {"shell", "page", "from", "how", "origin_ms", "first_paint_ms", "fleet_ms",
                        "ink_first_frame_ms", "longest_task_ms", "skin_first", "skin_settled",
                        "ua", "at"}
    assert (rec["shell"], rec["page"], rec["from"], rec["fleet_ms"]) == ("pycharm", "desk", "", 240.0)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", rec["at"]), rec["at"]
    # Absent durations and words are absent, not refused.
    S.act("load", {"shell": "edge", "page": "settings", "origin_ms": time.time() * 1000.0})
    rec = L.load()[-1]
    assert (rec["from"], rec["how"], rec["fleet_ms"], rec["skin_first"], rec["ua"]) == ("", "", None, "", "")


def test_sixty_posts_keep_the_newest_fifty_and_another_from_keeps_its_own(switched_on):
    for i in range(60):
        S.act("load", good(fleet_ms=float(i)))
    for i in range(55):
        S.act("load", good(fleet_ms=float(1000 + i), **{"from": "settings"}))
    recs = L.load()
    cold = [r["fleet_ms"] for r in recs if r["from"] == ""]
    back = [r["fleet_ms"] for r in recs if r["from"] == "settings"]
    assert cold == [float(i) for i in range(10, 60)]
    assert back == [float(1000 + i) for i in range(5, 55)]
    assert S.act("load", good(shell="vscode")) == {"kept": 1}
    assert S.act("load", good()) == {"kept": 50}


def test_one_document_posted_twice_is_kept_once_with_what_either_copy_measured(switched_on):
    """#531: the `pagehide` beacon and the `fetchLater` copy it failed to cancel, in either order."""
    early = good(ink_first_frame_ms=None, longest_task_ms=45.0, skin_settled="")
    late = dict(early, ink_first_frame_ms=310.0, longest_task_ms=80.0, skin_settled="paper")
    assert S.act("load", late) == {"kept": 1}
    assert S.act("load", early) == {"kept": 1}
    (rec,) = L.load()
    assert (rec["origin_ms"], rec["ink_first_frame_ms"], rec["longest_task_ms"], rec["skin_settled"]) == \
        (round(late["origin_ms"], 1), 310.0, 80.0, "paper")
    # Another document, identical but for its origin, is another load.
    assert S.act("load", dict(early, origin_ms=early["origin_ms"] + 0.5)) == {"kept": 2}
    assert len(L.load()) == 2


def test_turning_the_switch_off_in_the_file_stops_the_next_write_with_no_restart(switched_on):
    server, token, port = _serve()
    try:
        with _post(port, token, good()) as r:
            assert json.loads(r.read())["kept"] == 1
        C.save({"fleet": {"loads": {"enabled": False}}})
        with _post(port, token, good()) as r:
            got = json.loads(r.read())
        assert got["ok"] is True and got["kept"] == 0 and got["enabled"] is False, got
    finally:
        _stop(server)
    assert len(L.load()) == 1


# ------------------------------------------------------------------------------ refusals


BAD = [
    ("page", {"page": "board"}),
    ("from", {"from": "desk"}),
    ("how", {"how": "teleport"}),
    ("a negative duration", {"fleet_ms": -1}),
    ("a duration past ten minutes", {"first_paint_ms": 600_001}),
    ("a duration that is not a number", {"longest_task_ms": "fast"}),
    ("a boolean for a number", {"ink_first_frame_ms": True}),
    ("origin_ms two days off", {"origin_ms": time.time() * 1000.0 - 2 * 86_400_000}),
    ("origin_ms absent", {"origin_ms": None}),
    ("a 300-char ua", {"ua": "x" * 300}),
    ("a bad shell", {"shell": "Py Charm!"}),
    ("a skin that is not a word", {"skin_first": "Paper Dark"}),
]


@pytest.mark.parametrize("why,over", BAD, ids=[b[0] for b in BAD])
def test_a_load_of_the_wrong_shape_is_refused_as_load_shape(switched_on, why, over):
    with pytest.raises(L.LoadError) as refused:
        S.act("load", good(**over))
    assert refused.value.code == "load_shape", why
    assert refused.value.msg and refused.value.hint, why
    assert not os.path.exists(_file(switched_on))


def test_the_refusals_are_409_with_error_hint_and_code_over_the_wire(switched_on):
    server, token, port = _serve()
    try:
        for why, over in BAD:
            with pytest.raises(urllib.error.HTTPError) as http:
                _post(port, token, good(**over))
            assert http.value.code == 409, why
            body = json.loads(http.value.read())
            assert body["ok"] is False and body["error"] and body["hint"], (why, body)
            assert body["code"] == "load_shape", (why, body)
    finally:
        _stop(server)
    assert not os.path.exists(_file(switched_on))


def test_the_unknown_action_hint_names_load():
    with pytest.raises(S.ServeError) as refused:
        S.act("nonsense", {})
    assert "| load" in refused.value.hint


def test_the_skin_word_is_serves_skin_family():
    assert L.SKIN_WORD.pattern == S.SKIN_FAMILY.pattern


# ---------------------------------------------------------------------------------- rows


def test_rows_are_nearest_rank_percentiles_and_the_settled_share_per_shell_page_and_from():
    recs = [
        # pycharm desk cold: fleet_ms 10..100 in tens; nearest rank p50 = 50, p95 = 100.
        *[{"shell": "pycharm", "page": "desk", "from": "", "fleet_ms": float(v),
           "first_paint_ms": None, "ink_first_frame_ms": None, "longest_task_ms": 5.0,
           "skin_first": "paper", "skin_settled": "paper" if v <= 70 else "ink"}
          for v in (100, 20, 30, 40, 50, 60, 70, 80, 90, 10)],
        # pycharm desk back from settings: three loads, first_paint 7, 3, 5 -> p50 5, p95 7.
        *[{"shell": "pycharm", "page": "desk", "from": "settings", "first_paint_ms": v,
           "fleet_ms": None, "ink_first_frame_ms": None, "longest_task_ms": None,
           "skin_first": "", "skin_settled": s}
          for v, s in ((7.0, ""), (3.0, "paper"), (5.0, "paper"))],
    ]
    got = {tuple(r[:3]): dict(zip(L.LOAD_COLUMNS, r)) for r in L.rows(recs)}
    assert set(got) == {("pycharm", "desk", ""), ("pycharm", "desk", "settings")}
    cold, back = got[("pycharm", "desk", "")], got[("pycharm", "desk", "settings")]
    assert (cold["n"], cold["fleet_p50"], cold["fleet_p95"]) == (10, 50.0, 100.0)
    assert (cold["longest_task_p50"], cold["longest_task_p95"]) == (5.0, 5.0)
    assert (cold["first_paint_p50"], cold["first_paint_p95"]) == (None, None)
    assert cold["settled_pct"] == 70.0
    assert (back["n"], back["first_paint_p50"], back["first_paint_p95"]) == (3, 5.0, 7.0)
    assert back["settled_pct"] == 33.3
    assert L.rows([]) == []


def test_engines_prints_the_loads_table_with_from(switched_on):
    for v in (100.0, 200.0, 300.0):
        S.act("load", good(fleet_ms=v))
    S.act("load", good(fleet_ms=50.0, skin_first="ink", **{"from": "settings"}))
    rc, out = cli("engines")
    assert rc == 0
    assert meta(out)["loads"] == "on" and "hint" not in meta(out), out
    rows = {(r["shell"], r["page"], r["from"]): r for r in table(out, "loads")}
    assert set(rows) == {("pycharm", "desk", ""), ("pycharm", "desk", "settings")}, rows
    cold, back = rows[("pycharm", "desk", "")], rows[("pycharm", "desk", "settings")]
    assert (cold["n"], cold["fleet_p50"], cold["fleet_p95"], cold["settled_pct"]) == \
        ("3", "200.0", "300.0", "100.0")
    assert (back["n"], back["fleet_p50"], back["settled_pct"]) == ("1", "50.0", "0.0")


# ---------------------------------------------------------------------------- boundaries


def test_nothing_goes_to_probes_json_and_nothing_leaves_the_loopback_server(switched_on):
    server, token, port = _serve()
    try:
        assert server.server_address[0] == "127.0.0.1"
        with _post(port, token, good()) as r:
            assert json.loads(r.read())["kept"] == 1
    finally:
        _stop(server)
    assert not os.path.exists(PR.probes_file())
    assert os.listdir(str(switched_on)) == [L.LOADS_FILE] or L.LOADS_FILE in os.listdir(str(switched_on))
    source = open(L.__file__, encoding="utf-8").read()
    for network in ("urllib", "socket", "http.client", "requests", "probes_file"):
        assert network not in source, network
