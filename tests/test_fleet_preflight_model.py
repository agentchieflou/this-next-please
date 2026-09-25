"""The pre-flight's `model` row (#368): which model the agent will start on, said before Start.

Read from `<fleet dir>/models.json` alone -- the pre-flight spends nothing, so it never starts the
Copilot CLI -- and a courtesy, never a gate: `thin` only when the cache marks the configured id as
not offered (since CLI 0.0.421 a `-p` turn errors on a model the CLI cannot serve), `ready`
otherwise, and `ready` with no cache at all. The pattern is `tests/test_fleet_handoff_pickup.py`'s.
"""
from __future__ import annotations
import datetime as _dt
import json
import os

import pytest

from agentdata import proc
from agentdata.fleet import models as M, preflight as PF, registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


@pytest.fixture()
def spawned(monkeypatch):
    """Every subprocess the pre-flight asks for. There must be none: the row reads the cache."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(list(argv))
        raise AssertionError(f"the pre-flight started {argv!r}")

    monkeypatch.setattr(proc, "run", run)
    return calls


class _Table:
    """What `pncli.get_issue` returns: an AgentTable's shape, no more of it than we read."""

    def __init__(self, description):
        self.columns = ["key", "description", "comments", "attachment"]
        self.rows = [["RDSD-118", description, 0, 0]]


class _Client:
    def __init__(self, description):
        self.table = _Table(description)

    def get_issue(self, key):
        return self.table


# Long enough and with its criteria, so the model is the only row that can be thin.
RICH = ("The nightly refresh of the UAT semantic model takes over forty minutes and the team "
        "cannot validate before standup. Make it finish inside fifteen.\n"
        "Acceptance Criteria\n"
        "1. the refresh completes in under fifteen minutes\n"
        "2. no partition is dropped\n"
        "3. the Velocity measure still reconciles against the warehouse\n")


def _luna(tmp_path):
    Registry().add(make_project(tmp_path / "luna", project="RDSD"), name="luna")


def _seed():
    """`models.json` as a refresh under Copilot CLI 1.0.88 writes it (#360)."""
    shipped = M.shipped()
    os.makedirs(os.path.dirname(M.cache_file()), exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump({"source": "help", "cli_version": "1.0.88", "fetched_at": now,
                   "models": shipped["models"], "efforts": shipped["efforts"], "why": ""}, f)


def _card(model=None, repo="luna"):
    cfg = {"fleet": {"models": {"luna": {"model": model}}}} if model else {}
    return PF.preflight("RDSD-118", repo, cfg=cfg, client=_Client(RICH), now=1.0)


def _model(card):
    rows = [r for r in card["rows"] if r["row"] == "model"]
    assert len(rows) == 1, card["rows"]
    return rows[0]


def test_the_model_row_follows_the_repo_and_says_the_cli_chooses_when_nothing_is_set(
        fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    _seed()
    card = _card()
    names = [r["row"] for r in card["rows"]]
    assert names[names.index("repo") + 1] == "model", names
    row = _model(card)
    assert row["value"] == "the CLI chooses · cli-auto", row
    assert row["verdict"] == PF.READY and card["verdict"] == PF.READY, card["rows"]
    # Only for a repository that resolved: there is no model to name for one that did not.
    assert "model" not in [r["row"] for r in _card(repo="nowhere")["rows"]]
    assert spawned == []


def test_a_repos_own_model_is_its_label_and_where_it_comes_from(fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    _seed()
    row = _model(_card("claude-opus-5"))
    assert row["value"] == "opus 5 · fleet.models.luna", row
    assert row["verdict"] == PF.READY and row["why"] == "", row
    # The row on its own, as a press on the card reads it again (decision 15): the same row.
    assert PF.model_row("luna", {"fleet": {"models": {"luna": {"model": "claude-opus-5"}}}}) == row
    assert spawned == []


def test_a_model_the_cache_marks_not_offered_is_thin_and_says_the_turn_may_fail(
        fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    _seed()
    card = _card("claude-opus-4.6")
    row = _model(card)
    assert row["value"] == "opus 4.6 · fleet.models.luna", row
    assert row["verdict"] == PF.THIN, row
    assert row["why"] == "not in copilot 1.0.88's list — the turn may fail at start", row
    assert "may fail at start" in row["why"]
    # The one thin row, so the card's verdict is the model's -- and still never a block.
    assert [r["row"] for r in card["rows"] if r["verdict"] != PF.READY] == ["model"], card["rows"]
    assert card["verdict"] == PF.THIN
    assert spawned == []


def test_an_alias_is_offered_and_reads_ready(fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    _seed()
    row = _model(_card("opus"))
    assert row["value"] == "opus · fleet.models.luna", row
    assert row["verdict"] == PF.READY, row
    assert spawned == []


def test_with_no_cache_nothing_is_flagged(fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    assert not os.path.exists(M.cache_file())
    row = _model(_card("claude-opus-4.6"))
    assert row["verdict"] == PF.READY, row
    assert spawned == []


def test_a_value_the_launch_would_refuse_is_unknown_with_its_words(fleet_home, tmp_path, spawned):
    _luna(tmp_path)
    _seed()
    card = _card("x --allow-all-tools")
    row = _model(card)
    assert row["verdict"] == PF.UNKNOWN and row["value"] == "unknown", row
    assert row["why"], row
    assert card["verdict"] == PF.UNKNOWN
    assert spawned == []

