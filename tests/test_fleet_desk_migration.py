"""`desk.json` schema 2: one arrangement, and the migration that brings a schema-1 desk to it (#232).

Schema 1 had an arrangement per layout -- `column`, `grid`, `roles`, `screens` -- a `screens` list
for the per-monitor pinning, and `layout`, `view`, `screen` and `zoomed` in every window record.
Four arrangements writing one record is where the snap-back came from (#230): the grid's `zoomed`
and the column's `open` disagreed inside it. Schema 2 keeps one of each.

The file below is what a laptop that had used every arrangement would hold: the grid the default
for weeks, then the column, a hide done from a terminal (so into `grid`), two pins, a tile widened
to two columns by an older build (`size: 2`), a per-monitor pinning, and a zoom the column never
cleared.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import textio
from agentdata.fleet import registry, serve as S


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    home = tmp_path / "fleet"
    home.mkdir()
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(home))
    return home


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a suite
    that gives every test a fresh fleet directory."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


# What a laptop that had lived through every arrangement held on 2026-09-22.
LAPTOP_V1 = {
    "selected": "beta",
    "screens": ["alpha", "gamma"],
    "version": 41,
    "at": "2026-09-22T08:14:03Z",
    "arrangement": {
        "grid": {"order": ["gamma", "alpha", "beta", "delta"],
                 "size": {"alpha": 2, "gamma": {"cols": 3, "rows": 2}},
                 "pinned": ["alpha", "delta"],
                 "hidden": ["gamma"]},
        "roles": {"order": ["delta"], "hidden": ["alpha"]},
        "screens": {"order": [], "hidden": ["beta"]},
    },
    "windows": {
        "main": {"layout": "grid", "view": "all", "screen": 0, "focus": False,
                 "zoomed": "alpha", "section": "board", "open": "beta",
                 "held": ["delta"], "read": {"alpha": 12, "beta": 40},
                 "seen": "2026-09-22T08:10:00"},
        "left": {"layout": "screens", "view": "", "screen": 2, "focus": True,
                 "zoomed": "", "section": "", "open": "gamma", "held": [], "read": {},
                 "seen": "2026-09-21T17:02:11"},
        "pycharm": {"layout": "column", "zoomed": "delta", "open": ""},
    },
}

RETIRED_WINDOW_KEYS = ("layout", "view", "screen", "zoomed")


def _write_v1(home, data) -> str:
    raw = json.dumps(data, indent=2)
    with open(os.path.join(home, "desk.json"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(raw)
    return raw


def _read(home, name="desk.json"):
    with open(os.path.join(home, name), encoding="utf-8") as handle:
        return json.load(handle)


def test_a_laptops_v1_desk_comes_forward_as_schema_2_and_the_old_file_is_kept(fleet_home):
    raw = _write_v1(fleet_home, LAPTOP_V1)

    state = S.desk_state()

    # desk.v1.json is the file that was read, byte for byte, beside the new one.
    kept = os.path.join(fleet_home, "desk.v1.json")
    assert os.path.isfile(kept), "the old desk was not kept"
    with open(kept, encoding="utf-8") as handle:
        assert handle.read() == raw

    # One arrangement, from `grid` because this laptop has no `column`: the hidden list `ad-fleet
    # hide` wrote, the pins, and the old `size: 2` read the way it always was.
    assert state["schema"] == 2
    assert state["arrangement"] == {
        "order": ["gamma", "alpha", "beta", "delta"],
        "size": {"alpha": {"cols": 2, "rows": 1}, "gamma": {"cols": 3, "rows": 2}},
        "pinned": ["alpha", "delta"],
        "hidden": ["gamma"],
    }
    # `roles` and `screens` had lists of their own, and nothing of them survives.
    assert "screens" not in state
    assert state["selected"] == "beta", "the inspector reads it"
    # A write like any other: every window has to hear about it.
    assert state["version"] == 42

    # Each window keeps what is its own, and the stale zoom is not turned into anything.
    wins = state["windows"]
    assert wins["main"] == {"focus": False, "section": "board", "open": "beta", "held": ["delta"],
                            "read": {"alpha": 12, "beta": 40}, "seen": "2026-09-22T08:10:00"}
    assert wins["left"]["open"] == "gamma" and wins["left"]["focus"] is True
    assert wins["pycharm"] == {"open": ""}, "a zoom is not an open agent"
    for name, win in wins.items():
        for gone in RETIRED_WINDOW_KEYS:
            assert gone not in win, f"{name} kept {gone}"

    # And the file on disk is schema 2, not only the memory of it.
    disk = _read(fleet_home)
    assert disk["schema"] == 2
    assert disk["arrangement"] == state["arrangement"]
    assert "screens" not in disk
    assert all(not set(RETIRED_WINDOW_KEYS) & set(w) for w in disk["windows"].values())


def test_the_columns_arrangement_wins_over_the_grids_when_there_are_both(fleet_home):
    """The column was the default for the last of schema 1's life, and it is the drawing the one
    arrangement keeps. `grid` is only read when the column never wrote anything."""
    v1 = json.loads(json.dumps(LAPTOP_V1))
    v1["arrangement"]["column"] = {"order": ["delta", "beta"], "size": {},
                                   "pinned": [], "hidden": ["alpha"]}
    _write_v1(fleet_home, v1)

    arrangement = S.desk_state()["arrangement"]
    assert arrangement == {"order": ["delta", "beta"], "size": {}, "pinned": [],
                           "hidden": ["alpha"]}


def test_the_migration_runs_once(fleet_home):
    """A second load reads schema 2 and leaves it alone: the version does not climb on every restart,
    and the kept file is the one the migration read, not a copy of the new one."""
    _write_v1(fleet_home, LAPTOP_V1)
    first = S.desk_state()
    kept = os.path.join(fleet_home, "desk.v1.json")
    before = os.path.getmtime(kept)

    S.drop_handles()
    S._desk_loaded = False
    S._selection["windows"] = {}
    again = S.desk_state()
    assert again["version"] == first["version"]
    assert again["windows"] == first["windows"]
    assert os.path.getmtime(kept) == before
    assert _read(fleet_home, "desk.v1.json") == LAPTOP_V1, "the kept file is the old desk, untouched"


def test_a_desk_that_cannot_keep_its_old_file_is_not_overwritten_by_the_migration(fleet_home,
                                                                                monkeypatch):
    """The old file first, then the new one. A migration that could not write `desk.v1.json` still
    gives the page schema 2 -- the desk must open -- but it does not replace the only copy of what
    the operator had."""
    raw = _write_v1(fleet_home, LAPTOP_V1)
    real = textio.write_text

    def refuse_the_copy(path, text, **kw):
        if os.path.basename(path) == "desk.v1.json":
            raise OSError("read-only")
        return real(path, text, **kw)

    monkeypatch.setattr(textio, "write_text", refuse_the_copy)
    state = S.desk_state()
    assert state["schema"] == 2 and state["arrangement"]["hidden"] == ["gamma"]
    with open(os.path.join(fleet_home, "desk.json"), encoding="utf-8") as handle:
        assert handle.read() == raw, "the migration overwrote a desk it could not keep"


def test_a_fresh_desk_is_written_as_schema_2(fleet_home):
    S.arrange(order=["alpha"], hidden=["alpha"])
    disk = _read(fleet_home)
    assert disk["schema"] == 2
    assert disk["arrangement"]["hidden"] == ["alpha"]
    assert set(disk) == {"schema", "selected", "version", "at", "arrangement", "windows"}
    assert not os.path.exists(os.path.join(fleet_home, "desk.v1.json")), "nothing to keep"


def test_select_takes_no_screens_any_more(fleet_home):
    """`/api/select` carried the per-monitor pinning as well as the selection; the pinning went with
    `screens` (#232), and a page from before that posts it is answered as if it had not."""
    state = S.act("select", {"repo": "beta", "screens": ["alpha", "beta"]})
    assert state["selected"] == "beta"
    assert "screens" not in state and "screens" not in _read(fleet_home)
