"""`ad-fleet model` (#363): a repository's or the fleet's model, set from the terminal.

The same writer as the settings page (`settings.set_model` / `set_fleet_model`), the same inherit
rule, the same `bad_model` refusal, and the same catalogue -- read from the cache, never by starting
copilot, whichever copilot is on the PATH.
"""
from __future__ import annotations
import datetime as _dt
import json
import os

import pytest

from agentdata import cli_fleet, config as C, proc, toon
from agentdata.fleet import launch as L, models as M, registry
from agentdata.fleet.registry import Registry, fleet_dir

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("NO_COLOR", "1")
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    Registry().add(make_project(tmp_path / "rdsd.pbi", ticket="RDSD-1"), name="rdsd.pbi")
    return tmp_path


def _seed(hours_old: float = 0.0) -> None:
    """`<fleet_dir>/models.json` as `ad-fleet models --refresh` would write it under 1.0.88."""
    when = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_old)
    shipped = M.shipped()
    os.makedirs(fleet_dir(), exist_ok=True)
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump({"source": "help", "cli_version": "1.0.88", "fetched_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "models": shipped["models"], "efforts": shipped["efforts"], "why": ""}, f)


@pytest.fixture()
def spawns(monkeypatch):
    """Every `proc.run` and `proc.rpc` call. `rpc` exists only once #364 merges, hence raising=False."""
    calls: list[tuple] = []

    def run(argv, **kw):
        calls.append(("run", list(argv)))
        raise AssertionError(f"ad-fleet model started {argv!r}")

    def rpc(*args, **kw):
        calls.append(("rpc", args))
        raise AssertionError("ad-fleet model started server mode")

    monkeypatch.setattr(proc, "run", run)
    monkeypatch.setattr(proc, "rpc", rpc, raising=False)
    return calls


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1].replace('""', '"') if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _split(row: str) -> list[str]:
    out, cur, q = [], "", False
    for ch in row:
        if ch == '"':
            q = not q
        if ch == "," and not q:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [_unquote(c) for c in out]


def _run(capsys, *argv) -> tuple[int, dict, list[dict], str]:
    code = cli_fleet.main(["model", *argv])
    out = capsys.readouterr().out
    assert toon.validate(out) == [], out
    assert "\x1b[" not in out
    meta, rows, cols, section = {}, [], [], ""
    for line in out.splitlines():
        if line == "meta:":
            section = "meta"
        elif line.startswith("models["):
            section = "models"
            cols = line[line.index("{") + 1:line.index("}")].split(",")
        elif section == "meta" and line.startswith("  "):
            k, _, v = line.strip().partition(": ")
            meta[k.rstrip(":")] = _unquote(v)
        elif section == "models" and line.startswith("  "):
            rows.append(dict(zip(cols, _split(line.strip()))))
    return code, meta, rows, out


def _cfg_bytes() -> bytes:
    try:
        with open(C.path(), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return b""


# ------------------------------------------------------------------------------------- writes


def test_a_repo_with_a_dot_in_its_name_gets_its_model_and_inherit_removes_it(fleet_home, capsys, spawns):
    _seed()
    code, meta, _rows, _ = _run(capsys, "rdsd.pbi", "claude-opus-5", "--effort", "high")
    assert code == 0 and meta["ok"] == "true"
    cfg = C.load()
    assert C.get_leaf(cfg, "fleet.models", "rdsd.pbi") == {"model": "claude-opus-5", "effort": "high"}
    assert list(json.loads(_cfg_bytes())["fleet"]["models"]) == ["rdsd.pbi"], "one key, dot intact"
    assert "warning" not in meta

    code, meta, _rows, _ = _run(capsys, "rdsd.pbi", "--inherit")
    assert code == 0
    assert C.get_leaf(C.load(), "fleet.models", "rdsd.pbi", None) is None
    assert meta["source"] == "cli-auto"
    assert spawns == []


def test_the_fleet_default_is_written_and_resolves_for_a_repo_with_no_entry(fleet_home, capsys, spawns):
    _seed()
    code, meta, rows, _ = _run(capsys, "--fleet", "claude-sonnet-5")
    assert code == 0 and meta["model"] == "claude-sonnet-5"
    cfg = C.load()
    assert C.get(cfg, "fleet.model") == "claude-sonnet-5"
    assert L.model_for("alpha", cfg) == ("claude-sonnet-5", "", "fleet.model")
    assert [r["id"] for r in rows if r["pressed"] == "*"] == ["claude-sonnet-5"]
    assert spawns == []


def test_effort_alone_pins_the_fleet_model_it_inherits(fleet_home, capsys, spawns):
    _seed()
    C.save({"fleet": {"model": "claude-sonnet-5"}})
    code, meta, _rows, _ = _run(capsys, "alpha", "--effort", "high")
    assert code == 0
    assert C.get_leaf(C.load(), "fleet.models", "alpha") == {"model": "claude-sonnet-5", "effort": "high"}
    assert meta["pinned_model"] == "claude-sonnet-5"
    assert "warning" not in meta


def test_effort_alone_with_nothing_to_pin_warns_that_no_model_is_passed(fleet_home, capsys, spawns):
    _seed()
    code, meta, _rows, _ = _run(capsys, "alpha", "--effort", "high")
    assert code == 0 and meta["ok"] == "true"
    assert C.get_leaf(C.load(), "fleet.models", "alpha") == {"effort": "high"}
    assert "pinned_model" not in meta
    assert meta["warning"] == ("alpha now passes no --model; fleet.model no longer applies to it — "
                               "pass a model too to keep one")


def test_effort_alone_on_a_repo_with_its_own_model_changes_only_the_effort(fleet_home, capsys, spawns):
    _seed()
    C.save({"fleet": {"model": "claude-sonnet-5", "models": {"alpha": {"model": "gpt-5.5", "effort": "low"}}}})
    code, meta, _rows, _ = _run(capsys, "alpha", "--effort", "max")
    assert code == 0
    assert C.get_leaf(C.load(), "fleet.models", "alpha") == {"model": "gpt-5.5", "effort": "max"}
    assert "pinned_model" not in meta and "warning" not in meta


# ------------------------------------------------------------------------------------- refusals


def test_a_model_that_would_become_a_second_flag_is_refused_at_the_terminal(fleet_home, capsys, spawns):
    _seed()
    C.save({"fleet": {"model": "claude-sonnet-5"}})
    before = _cfg_bytes()
    for argv in (["alpha", "x --allow-all-tools"], ["alpha", "--", "--yolo"], ["--fleet", "a b"]):
        code, meta, _rows, _ = _run(capsys, *argv)
        bad = argv[-1]
        assert code == 2, bad
        assert meta["ok"] == "false"
        assert meta["code"] == "bad_model"
        assert meta["hint"], "the refusal says how to fix it"
    code, meta, _rows, _ = _run(capsys, "alpha", "--effort", "a b")
    assert code == 2 and meta["code"] == "bad_model"
    assert _cfg_bytes() == before, "nothing written"


def test_an_unregistered_repo_is_refused_and_the_config_is_byte_identical(fleet_home, capsys, spawns):
    _seed()
    C.save({"fleet": {"model": "claude-sonnet-5"}})
    before = _cfg_bytes()
    code, meta, _rows, out = _run(capsys, "nosuch", "claude-opus-5")
    assert code == 2
    assert meta["ok"] == "false"
    assert "alpha" in meta["hint"], "the hint lists the registered names"
    assert "models[" not in out
    assert _cfg_bytes() == before


def test_an_unoffered_name_is_saved_with_a_warning(fleet_home, capsys, spawns):
    _seed()
    code, meta, rows, _ = _run(capsys, "alpha", "claude-opus-4.6")
    assert code == 0 and meta["ok"] == "true"
    assert C.get_leaf(C.load(), "fleet.models", "alpha") == {"model": "claude-opus-4.6"}
    assert meta["warning"] == "not offered by copilot 1.0.88 — the turn may fail at start"
    pressed = [r for r in rows if r["pressed"] == "*"]
    assert [(r["id"], r["offered"]) for r in pressed] == [("claude-opus-4.6", "false")]


# ------------------------------------------------------------------------------------- the table


def test_showing_a_repo_prints_the_table_from_the_cache_with_one_pressed_row(fleet_home, capsys, spawns,
                                                                            isolated_path):
    """The fake copilot is on the PATH and is never asked: a spawn would make this output depend on it."""
    _seed()
    C.save({"fleet": {"models": {"alpha": {"model": "claude-opus-5", "effort": "high"}}}})
    code, meta, rows, _ = _run(capsys, "alpha")
    assert code == 0
    assert (meta["repo"], meta["model"], meta["effort"], meta["source"]) == \
        ("alpha", "claude-opus-5", "high", "fleet.models.alpha")
    assert "actual" in meta
    assert set(rows[0]) == {"id", "group", "label", "offered", "pressed"}
    assert [r["id"] for r in rows if r["pressed"] == "*"] == ["claude-opus-5"]
    assert len(rows) == 26 + 2, "the 1.0.88 cache plus the CLI default and auto"
    assert spawns == []


def test_an_inheriting_repo_presses_the_cli_default_row(fleet_home, capsys, spawns):
    _seed()
    C.save({"fleet": {"model": "claude-sonnet-5"}})
    code, meta, rows, _ = _run(capsys, "alpha")
    assert code == 0 and meta["source"] == "fleet.model"
    pressed = [r for r in rows if r["pressed"] == "*"]
    assert len(pressed) == 1 and pressed[0]["id"] == "" and pressed[0]["label"] == "CLI default"


def test_the_account_source_with_a_stale_cache_starts_no_process(fleet_home, capsys, spawns):
    _seed(hours_old=100)
    C.save({"fleet": {"model_list": {"source": "account", "max_age_h": 1}}})
    code, meta, rows, _ = _run(capsys, "alpha")
    assert code == 0 and meta["stale"] == "true"
    assert rows
    assert spawns == [], "0 proc.run and 0 proc.rpc calls"
