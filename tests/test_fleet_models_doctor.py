"""The doctor's `models` row (#365): where the model list came from, and a configured model the
installed Copilot CLI no longer offers."""
from __future__ import annotations
import json

import pytest

from agentdata import proc
from agentdata.fleet import models as M
from agentdata.setup.steps.fleet import FleetStep
from agentdata.setup.wizard import Context, Detectors, Prompter
from tests import fakes


def _run(cfg: dict | None = None) -> dict:
    """`detect` then `check`, as `ad-doctor --only fleet` runs the step, on a fleet enabled by config."""
    cfg = {"fleet": {"enabled": True, **((cfg or {}).get("fleet") or {})}}
    ctx = Context(cfg=cfg, det=Detectors(), ask=Prompter(), interactive=False)
    step = FleetStep()
    step.check(ctx, step.detect(ctx))
    return {c.name: c for c in ctx.checks if c.step == "fleet"}


def _model_rows(rows: dict) -> list:
    return [c for name, c in rows.items() if name == "models" or name.startswith("models ")]


@pytest.fixture()
def counted(monkeypatch, tmp_path, isolated_path):
    """The fake copilot (1.0.88 transcripts, #359) on an isolated PATH, every `proc.run` recorded."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"])
    calls: list[list[str]] = []
    real = proc.run

    def run(argv, **kw):
        calls.append(list(argv[1:]))
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", run)
    return calls


def _age_cache(hours_old_iso: str = "2020-01-01T00:00:00Z") -> None:
    with open(M.cache_file(), encoding="utf-8") as f:
        cache = json.load(f)
    cache["fetched_at"] = hours_old_iso
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump(cache, f)


def test_the_fake_cli_gives_an_ok_row_naming_26_models_and_the_version(counted):
    rows = _run()
    row = rows["models"]
    assert row.status == "ok", row
    assert "26 models" in row.detail and "1.0.88" in row.detail
    assert "just now" in row.detail
    assert [c.name for c in _model_rows(rows)] == ["models"]
    names = list(rows)
    assert names.index("models") == names.index("login") + 1, "right after the copilot rows"


def test_a_configured_model_the_cli_no_longer_offers_warns_with_the_fix(counted):
    rows = _run({"fleet": {"models": {"rdsd.pbi": {"model": "claude-opus-4.6"}}}})
    warns = [c for c in _model_rows(rows) if c.status == "warn"]
    assert len(warns) == 1, warns
    assert "rdsd.pbi" in warns[0].detail and "claude-opus-4.6" in warns[0].detail
    assert "1.0.88" in warns[0].detail
    assert "ad-fleet model rdsd.pbi --inherit" in warns[0].hint
    assert rows["models"].status == "ok"


def test_the_fleet_default_is_flagged_the_same_way(counted):
    rows = _run({"fleet": {"model": "claude-sonnet-4.5"}})
    warns = [c for c in _model_rows(rows) if c.status == "warn"]
    assert len(warns) == 1
    assert "`fleet.model` = claude-sonnet-4.5 is not offered by copilot 1.0.88" in warns[0].detail
    assert "ad-fleet model --fleet --inherit" in warns[0].hint


@pytest.mark.parametrize("model", ["opus", "claude-opus-5", "auto"])
def test_an_alias_or_an_offered_id_is_never_flagged(counted, model):
    rows = _run({"fleet": {"models": {"rdsd.pbi": {"model": model}}}})
    assert [c.status for c in _model_rows(rows)] == ["ok"]


def test_no_copilot_on_the_path_warns_that_the_list_is_shipped(isolated_path):
    rows = _run({"fleet": {"models": {"rdsd.pbi": {"model": "claude-opus-4.6"}}}})
    assert rows["copilot"].status == "fail"
    row = rows["models"]
    assert row.status == "warn"
    assert "shipped with this version" in row.detail and "1.0.88" in row.detail
    assert "ad-fleet models --refresh" in row.hint
    # The shipped list cannot say what this CLI offers, so nothing is flagged against it.
    assert [c.name for c in _model_rows(rows)] == ["models"]


def test_a_fresh_cache_adds_no_process_beyond_the_probe(counted):
    M.refresh({})
    counted.clear()
    _run()
    assert counted == [["--version"], ["--help"]]


def test_a_stale_cache_adds_one_help_config_and_no_second_version(counted):
    M.refresh({})
    _age_cache()
    counted.clear()
    rows = _run()
    assert counted.count(["--version"]) == 1
    assert counted.count(["help", "config"]) == 1
    assert counted == [["--version"], ["--help"], ["help", "config"], ["--help"]]
    assert rows["models"].status == "ok" and "just now" in rows["models"].detail


def test_the_account_source_never_starts_server_mode(counted, monkeypatch):
    M.refresh({})
    _age_cache()
    counted.clear()
    rpc_calls = []
    monkeypatch.setattr(proc, "rpc", lambda *a, **kw: rpc_calls.append((a, kw)), raising=False)
    rows = _run({"fleet": {"model_list": {"source": "account"}}})
    assert not any("--headless" in argv for argv in counted), counted
    assert rpc_calls == []
    assert rows["models"].status == "ok"
    assert "account: ok" not in rows["models"].detail, "nothing cached says the account was asked"


def test_the_account_verdict_is_read_from_the_cache(counted):
    M.refresh({})
    with open(M.cache_file(), encoding="utf-8") as f:
        cache = json.load(f)
    cache["account"] = "ok"
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump(cache, f)
    rows = _run({"fleet": {"model_list": {"source": "account"}}})
    assert rows["models"].detail.endswith(" · account: ok")
    assert "account: ok" not in _run()["models"].detail, "only when the account source is chosen"


def test_the_doctor_writes_nothing_to_the_config(counted):
    cfg = {"fleet": {"models": {"rdsd.pbi": {"model": "claude-opus-4.6"}}}}
    before = json.dumps(cfg, sort_keys=True)
    _run(cfg)
    assert json.dumps(cfg, sort_keys=True) == before


def test_a_hand_built_found_without_models_gets_no_models_row():
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    found = {"enabled": True, "repos": [], "toast": "off",
             "settings": {"toast": False, "cooldown": 300, "idle_minutes": 20, "quiet_hours": "",
                          "dashboard": True, "chime": False},
             "version": "1.0.88", "why": "", "login": "ok", "port": 8765, "port_free": True, "ours": False}
    FleetStep().check(ctx, found)
    assert not [c for c in ctx.checks if c.name == "models" or c.name.startswith("models ")]


def test_a_disabled_fleet_has_no_models_row():
    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    FleetStep().check(ctx, {"enabled": False})
    assert [c.name for c in ctx.checks] == ["fleet"]


def test_run_doctor_only_fleet_prints_the_models_row(counted, capsys):
    from agentdata import config as C
    from agentdata.setup.wizard import run_doctor

    cfg = C.load()
    cfg.setdefault("fleet", {})["enabled"] = True
    cfg["fleet"]["models"] = {"rdsd.pbi": {"model": "claude-opus-4.6"}}
    C.save(cfg)
    run_doctor(["--only", "fleet"])
    out = capsys.readouterr().out
    assert "26 models from copilot 1.0.88" in out
    assert "claude-opus-4.6 is not offered by copilot 1.0.88" in out
