"""Model and effort inherit separately, and an effort survives a model switch (#493, decision 15).

`launch.model_for` used to read a per-repo entry as one unit: an entry holding only an effort passed
no `--model` (the fleet's model silently stopped applying), and one holding only a model lost the
fleet's effort. Each half is now its own: the repository's, else the fleet's, else none. The third
element of `model_for` still names where the *model* came from; `effort_source` names the effort's.

A turn launched with an effort that ends before its first reply may have been refused that pair by
the CLI: its pane says which effort, on which model, and where to change it.
"""
from __future__ import annotations
import os
import time

import pytest

import fakes
from agentdata import config as C
from agentdata.fleet import agentstate, events as E, launch as L, lifecycle, registry, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _flags(cfg: dict, repo: str = "luna") -> list[str]:
    """The model half of the argv a turn is launched with: `launch_command`'s own `model_flags`."""
    model, effort, _source = L.model_for(repo, cfg)
    return L.model_flags(model, effort)


def test_a_repos_effort_goes_with_the_fleets_model():
    cfg = {"fleet": {"model": "claude-sonnet-5", "models": {"luna": {"effort": "high"}}}}
    assert L.model_for("luna", cfg) == ("claude-sonnet-5", "high", "fleet.model")
    assert L.effort_source("luna", cfg) == "fleet.models.luna"
    assert _flags(cfg) == ["--model", "claude-sonnet-5", "--effort", "high"]


def test_a_repos_model_goes_with_the_fleets_effort():
    cfg = {"fleet": {"effort": "low", "models": {"luna": {"model": "gpt-5.6-luna"}}}}
    assert L.model_for("luna", cfg) == ("gpt-5.6-luna", "low", "fleet.models.luna")
    assert L.effort_source("luna", cfg) == "fleet.effort"
    assert _flags(cfg) == ["--model", "gpt-5.6-luna", "--effort", "low"]


def test_nothing_set_passes_neither_flag_and_a_fleet_effort_alone_passes_only_its_own():
    assert L.model_for("luna", {}) == ("", "", "cli-auto") and _flags({}) == []
    assert L.effort_source("luna", {}) == "cli-auto"
    only = {"fleet": {"effort": "medium"}}
    assert L.model_for("luna", only) == ("", "medium", "cli-auto")
    assert _flags(only) == ["--effort", "medium"]


def test_a_refused_pair_is_named_on_the_pane(fleet_home, tmp_path, monkeypatch):
    """A fake copilot that ends non-zero with no reply, launched with `--effort max`: the pane's
    reason names `max`, the model, and the key that opens the card to change it."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"], case="refuses-effort")
    path = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(path, name="luna")
    C.save({"fleet": {"model": "gpt-5.6-luna", "models": {"luna": {"effort": "max"}},
                      "notify": {"toast": False}}})
    supervisor.start("luna", prompt="go", cfg=C.load())
    deadline = time.time() + 60
    while supervisor.live("luna") and time.time() < deadline:
        time.sleep(0.1)
    assert not supervisor.live("luna"), "the fake never ended"
    lifecycle.reap_all()
    E.refresh("luna", path)

    argv = [a for a in fakes.calls(dict(os.environ), "copilot") if "-p" in a][-1]
    assert argv[argv.index("--model") + 1] == "gpt-5.6-luna" and argv[argv.index("--effort") + 1] == "max"
    derived = agentstate.derive(E.read("luna"))
    assert derived["state"] == "error", derived
    assert "ran with effort max on gpt-5.6-luna" in derived["why"], derived["why"]
    assert "pick another effort (m)" in derived["why"], derived["why"]


def test_a_turn_that_replied_is_not_said_to_have_been_refused():
    """The pair is named only when the run never said a word: a turn that replied and then failed
    failed for its own reasons."""
    events = [E.event("luna", "started", {"pid": 1, "model": "gpt-5.6-luna", "effort": "max"}),
              E.event("luna", "assistant_text", {"text": "on it", "model": "gpt-5.6-luna"}),
              E.event("luna", "error", {"exit_code": 1})]
    why = agentstate.derive(events)["why"]
    assert why == "the last turn exited 1", why
