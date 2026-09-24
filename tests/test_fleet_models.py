"""The model catalogue read from the installed Copilot CLI (#360): parsers, cache, spawn rules, CLI."""
from __future__ import annotations
import json
import os

import pytest

from agentdata import cli_fleet, proc
from agentdata.fleet import launch, models as M
from tests import fakes

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "copilot")


def _fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------------------------ parsers


def test_help_config_ids_in_cli_order():
    ids_88 = M.parse_help_config(_fixture("help-config-1.0.88.txt"))
    ids_81 = M.parse_help_config(_fixture("help-config-1.0.81.txt"))
    assert len(ids_88) == 26
    assert len(ids_81) == 28
    assert ids_88[:3] == ["claude-sonnet-5", "claude-fable-5.1", "claude-fable-5"]
    assert ids_88[-1] == "kimi-k2.7-code"
    assert ids_88 == M.shipped()["models"], "models_shipped.json is the 1.0.88 list, in the CLI's order"


@pytest.mark.parametrize("name", ["help-1.0.88.txt", "help-1.0.81.txt"])
def test_efforts_from_both_help_formats(name):
    assert M.parse_efforts(_fixture(name)) == ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def test_completion_fallback_drops_auto():
    text = 'case "$prev" in\n  --model)\n    COMPREPLY=( $(compgen -W "auto gpt-5.5 claude-opus-5" -- "$cur") )\n    ;;\n'
    assert M.parse_completion(text) == ["gpt-5.5", "claude-opus-5"]


def test_version_label_and_groups():
    assert M.parse_version("GitHub Copilot CLI 1.0.88.\nRun 'copilot update'") == "1.0.88"
    assert M.label("claude-opus-4.8-20260101") == "opus-4.8"
    assert M.label("gpt-5.5") == "gpt-5.5"
    assert [M.group_of(i) for i in ("auto", "gpt-5.5", "o3-mini", "claude-opus-5", "gemini-3.8-flash",
                                    "grok-4.5", "opus")] == \
        ["copilot", "openai", "openai", "anthropic", "google", "other", "anthropic"]


# ------------------------------------------------------------------------------------ spawn rules


@pytest.fixture()
def counted(monkeypatch, tmp_path):
    """The fake copilot on PATH, with every `proc.run` argv recorded."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"])
    calls: list[list[str]] = []
    real = proc.run

    def run(argv, **kw):
        calls.append(list(argv[1:]))
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", run)
    return calls


def test_refresh_writes_the_cache_from_the_fake_cli(counted):
    cache = M.refresh({})
    assert cache["source"] == "help"
    assert cache["cli_version"] == "1.0.88"
    assert len(cache["models"]) == 26
    assert cache["efforts"][-1] == "max"
    assert counted == [["--version"], ["help", "config"], ["--help"]]
    with open(M.cache_file(), encoding="utf-8") as f:
        assert json.load(f)["models"] == cache["models"]


def test_fresh_cache_with_a_known_version_spawns_nothing(counted):
    M.refresh({})
    counted.clear()
    cat = M.catalogue({}, spawn=True, cli_version="1.0.88")
    assert counted == []
    assert cat["meta"]["source"] == "help" and cat["meta"]["stale"] is False


def test_fresh_cache_without_a_version_asks_only_for_it(counted):
    M.refresh({})
    counted.clear()
    M.catalogue({}, spawn=True)
    assert counted == [["--version"]]


def test_a_new_cli_version_refreshes_once(counted, monkeypatch):
    M.refresh({})
    counted.clear()
    real = proc.run

    def newer(argv, **kw):
        if argv[1:] == ["--version"]:
            counted.append(["--version"])
            return 0, "GitHub Copilot CLI 1.0.89.\n", "", 0.0
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", newer)
    cat = M.catalogue({}, spawn=True)
    assert counted.count(["--version"]) == 1
    assert counted.count(["help", "config"]) == 1
    assert cat["meta"]["cli_version"] == "1.0.89"


def test_spawn_false_never_spawns(counted):
    cat = M.catalogue({"fleet": {"model": "gpt-5.5"}}, spawn=False)
    assert counted == []
    assert cat["meta"]["source"] == "shipped" and cat["meta"]["stale"] is True


def test_a_stale_cache_is_refreshed(counted):
    M.refresh({})
    with open(M.cache_file(), encoding="utf-8") as f:
        cache = json.load(f)
    cache["fetched_at"] = "2020-01-01T00:00:00Z"
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump(cache, f)
    counted.clear()
    cat = M.catalogue({"fleet": {"model_list": {"max_age_h": 1}}}, spawn=True, cli_version="1.0.88")
    assert ["help", "config"] in counted
    assert cat["meta"]["stale"] is False and cat["meta"]["max_age_h"] == 1


def test_a_failed_refresh_keeps_the_cache_and_says_why(counted, monkeypatch):
    M.refresh({})

    def gone(argv, **kw):
        raise proc.ProcError("not_found", "copilot: not on PATH")

    monkeypatch.setattr(proc, "run", gone)
    kept = M.refresh({})
    assert len(kept["models"]) == 26 and "not on PATH" in kept["why"]
    assert "not on PATH" in M.catalogue({})["meta"]["why"]


# ------------------------------------------------------------------------------------ no CLI


def test_no_copilot_falls_back_to_the_shipped_list(isolated_path):
    cat = M.catalogue({}, spawn=True)
    assert cat["meta"]["source"] == "shipped"
    assert cat["meta"]["stale"] is True
    assert cat["meta"]["why"]
    assert [m["id"] for m in cat["models"][:3]] == ["", "auto", "claude-sonnet-5"]
    assert cat["efforts"] == M.shipped()["efforts"]


def test_ad_fleet_models_exits_0_without_copilot(isolated_path, capsys):
    assert cli_fleet.main(["models"]) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out
    assert "source: shipped" in out
    assert "models[" in out and "efforts[7]{level}:" in out
    assert "\x1b[" not in out


# ------------------------------------------------------------------------------------ entries


def test_configured_ids_offered_or_not_under_1_0_88(counted):
    M.refresh({})
    cfg = {"fleet": {"model": "claude-opus-5",
                     "models": {"rdsd.pbi": {"model": "claude-opus-4.6"}, "alpha": {"model": "opus"}}}}
    cat = M.catalogue(cfg, seen=["gpt-5.5", "gpt-9"])
    by = {m["id"]: m for m in cat["models"]}
    assert cat["models"][0] == {"id": "", "label": "CLI default", "group": "copilot", "via": ["builtin"],
                                "offered": True}
    assert by["claude-opus-4.6"]["offered"] is False
    assert by["claude-opus-4.6"]["via"] == ["config"]
    assert by["opus"]["offered"] is True
    assert "alias" in by["opus"]["via"] and by["opus"]["group"] == "anthropic"
    assert by["claude-opus-5"]["via"] == ["cli", "config"]
    assert by["gpt-5.5"]["via"] == ["cli", "seen"]
    assert by["gpt-9"]["offered"] is False
    assert [g["key"] for g in cat["groups"]] == ["copilot", "openai", "anthropic", "google", "other"]
    ids = [m["id"] for m in cat["models"]]
    assert len(ids) == len(set(ids))


def test_shipped_source_never_marks_a_name_unoffered():
    cat = M.catalogue({"fleet": {"models": {"rdsd.pbi": {"model": "claude-opus-4.6"}}}})
    assert cat["meta"]["source"] == "shipped"
    assert all(m["offered"] for m in cat["models"])


def test_model_for_never_reads_the_list_settings_as_a_repo():
    cfg = {"fleet": {"model": "gpt-5.5", "model_list": {"max_age_h": 6},
                     "models": {"rdsd.pbi": {"model": "claude-opus-5"}}}}
    assert launch.model_for("max_age_h", cfg) == ("gpt-5.5", "", "fleet.model")
    assert launch.model_for("model_list", cfg) == ("gpt-5.5", "", "fleet.model")
    assert launch.model_for("rdsd.pbi", cfg) == ("claude-opus-5", "", "fleet.models.rdsd.pbi")
