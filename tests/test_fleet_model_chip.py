"""The pane's model chip (#492, decision 15 on #429): the plain half.

The operator switched a pane from sonnet 5 to luna and the chip went on saying sonnet: it drew the
model the last *reply* ran on, and cut `gpt-5.6-luna` to `gpt-5.6-l…`. The model had changed; the
page could not say so. What the chip needs is here, below the page:

* a `started` event records the model its turn was launched with, so the row can say `launched`
  and the chip can mark a switch *next turn* until a turn launches with it;
* labels are name first (`luna 5.6`, `sonnet 5`), unique across the shipped list;
* a model set anywhere -- this page's card, /settings in another tab, `ad-fleet model` in a
  terminal -- reaches the desk as rows, not only as config;
* the fake copilot reports the `--model` it was launched with, as the real one does.

The page half (the chip itself, re-read, the pinned tenant) is folded into
`tests/test_fleet_column.py`'s model card test, the slow tier being full (decision 13).
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading

import pytest

from agentdata import cli_fleet
from agentdata.fleet import events as E, models as M, registry, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every id Copilot CLI 1.0.88 lists, and what its pill and chip say (decision 15, item 3).
LABELS = {
    "claude-sonnet-5": "sonnet 5", "claude-fable-5.1": "fable 5.1", "claude-fable-5": "fable 5",
    "claude-opus-5": "opus 5", "claude-opus-4.8": "opus 4.8", "claude-opus-4.8-fast": "opus 4.8 fast",
    "claude-opus-4.7": "opus 4.7", "claude-sonnet-4.6": "sonnet 4.6", "claude-haiku-4.5": "haiku 4.5",
    "gpt-6-astra": "astra 6", "gpt-5.6-sol": "sol 5.6", "gpt-5.6-terra": "terra 5.6",
    "gpt-5.6-luna": "luna 5.6", "gpt-5.5": "gpt-5.5", "gpt-5.4": "gpt-5.4", "gpt-5.4-mini": "mini 5.4",
    "gpt-5.3-codex": "codex 5.3", "gpt-5-mini": "mini 5", "mai-code-1.1-flash": "mai code 1.1 flash",
    "gemini-3.8-flash": "flash 3.8", "gemini-3.7-flash": "flash 3.7", "gemini-3.6-flash": "flash 3.6",
    "gemini-3.5-flash": "flash 3.5", "grok-4.5": "grok 4.5", "kimi-k3": "kimi k3",
    "kimi-k2.7-code": "kimi k2.7 code",
}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _alpha(tmp_path):
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")


# ------------------------------------------------------------------------------------ the labels


def test_every_shipped_id_reads_name_first_and_no_two_read_alike():
    assert list(LABELS) == M.shipped()["models"], "the table is the shipped list, in its order"
    assert {i: M.label(i) for i in LABELS} == LABELS
    assert len(set(LABELS.values())) == len(LABELS), "two shipped ids share a label"
    assert M.label("gpt-5.6-luna") == "luna 5.6"
    # A date is still no part of a name, and an id with no word of its own is left as it is.
    assert M.label("claude-opus-4.8-20260101") == "opus 4.8"
    assert [M.label(i) for i in ("opus", "auto", "o3-mini", "x-model")] == ["opus", "auto", "o3-mini", "x-model"]
    # A name the list does not know is put in the same order, never refused: it is only a label.
    assert M.label("byok-model-7") == "byok model 7"
    # The catalogue's pills say the same: every picker (/settings, the card, the dispatch card).
    by = {m["id"]: m["label"] for m in M.catalogue({}, spawn=False)["models"]}
    assert all(by[i] == label for i, label in LABELS.items()), by


# --------------------------------------------------------------------- what a turn launched with


def test_a_started_event_records_the_model_and_effort_it_was_launched_with(fleet_home, tmp_path):
    _alpha(tmp_path)
    supervisor._emit_started("alpha", {"pid": 7, "session": "s1", "ticket": "RDSD-1",
                                       "model": "gpt-5.6-luna", "effort": "high"})
    supervisor._emit_started("alpha", {"pid": 8, "session": "s2", "ticket": "RDSD-1"})
    started = [ev["data"] for ev in E.read("alpha") if ev["kind"] == "started"]
    assert [(d["model"], d["effort"]) for d in started] == [("gpt-5.6-luna", "high"), ("", "")]


def test_the_row_says_what_the_newest_turn_was_launched_with_and_what_it_reported(fleet_home, tmp_path):
    """`launched` is the newest `started`'s model; `turn_model` what that turn has said it ran on;
    `actual` the newest reply's, whichever turn it came from."""
    _alpha(tmp_path)

    def cells():
        return {k: S._model_cells("alpha", {"fleet": {"models": {"alpha": {"model": "gpt-5.6-luna"}}}})[k]
                for k in ("model", "actual", "launched", "turn_model")}

    def reply(model):
        E.append("alpha", [E.event("alpha", "assistant_text", {"text": "ok", "model": model}, ticket="RDSD-1")])

    assert cells() == {"model": "gpt-5.6-luna", "actual": "", "launched": None, "turn_model": ""}
    # A run from before the field: nothing to compare with, so nothing is claimed.
    E.append("alpha", [E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1")])
    reply("claude-sonnet-5")
    assert cells()["launched"] is None and cells()["actual"] == "claude-sonnet-5"

    supervisor._emit_started("alpha", {"pid": 2, "model": "claude-sonnet-5"})
    reply("claude-sonnet-5")
    assert cells() == {"model": "gpt-5.6-luna", "actual": "claude-sonnet-5",
                       "launched": "claude-sonnet-5", "turn_model": "claude-sonnet-5"}
    # The switch: the next turn launches with luna and has not said anything yet. The reply from
    # the turn before it is not this turn's.
    supervisor._emit_started("alpha", {"pid": 3, "model": "gpt-5.6-luna"})
    assert cells() == {"model": "gpt-5.6-luna", "actual": "claude-sonnet-5",
                       "launched": "gpt-5.6-luna", "turn_model": ""}
    # A tenant that serves its own choice: launched luna, and haiku answered.
    reply("claude-haiku-4.5")
    assert cells() == {"model": "gpt-5.6-luna", "actual": "claude-haiku-4.5",
                       "launched": "gpt-5.6-luna", "turn_model": "claude-haiku-4.5"}
    assert S.served_model("alpha") == "claude-haiku-4.5"


# ------------------------------------------------------------------ a model set anywhere is a row


class Polls:
    """A stream's `write`: the repositories each `polls` frame named, and the `tick`s."""

    def __init__(self):
        self.repos: list[str] = []
        self.heard = threading.Condition()
        self.ticks = 0

    def __call__(self, chunk: str) -> None:
        with self.heard:
            if chunk.startswith("event: polls\n"):
                self.repos.append(json.loads(chunk.split("data: ", 1)[1])["repo"])
            elif chunk.startswith("event: tick\n"):
                self.ticks += 1
            self.heard.notify_all()

    def wait(self, cond) -> bool:
        with self.heard:
            return self.heard.wait_for(cond, 10)


def test_a_model_set_elsewhere_reaches_the_desk_as_a_row(fleet_home, tmp_path, monkeypatch, capsys):
    """`ad-fleet model` in a terminal and /settings in another tab write config.json; the desk's
    stream says `polls` for the repository whose next turn changed, which is what re-reads its row.
    A write through the settings action also answers with the rows it changed."""
    _alpha(tmp_path)
    Registry().add(make_project(tmp_path / "beta", ticket="RDSD-2"), name="beta")
    frames, stop = Polls(), threading.Event()
    t = threading.Thread(target=S.stream_events, args=({}, stop, frames),
                         kwargs={"tick": 0.05, "heartbeat": 0, "sweep": False}, daemon=True)
    t.start()
    try:
        # The first poll values are news by design (`stream_events`); what follows them is not.
        assert frames.wait(lambda: frames.ticks >= 3), "the stream never finished a pass"
        with frames.heard:
            frames.repos.clear()

        assert cli_fleet.main(["model", "alpha", "gpt-5.6-sol"]) == 0
        capsys.readouterr()
        assert frames.wait(lambda: "alpha" in frames.repos), "`ad-fleet model` reached no row"

        answer = S.act("settings", {"models": [{"repo": "beta", "model": "gpt-5.6-terra"}]})
        assert [(r["repo"], r["model"]) for r in answer["rows"]] == [("beta", "gpt-5.6-terra")]
        assert frames.wait(lambda: "beta" in frames.repos), "the settings action reached no row"
    finally:
        stop.set()
        t.join(5)
    assert not t.is_alive()


# ------------------------------------------------------------------------- the fake copilot


@pytest.mark.parametrize("argv,env,said", [
    (["--model", "gpt-5.6-luna"], {}, "gpt-5.6-luna"),
    ([], {}, "claude-haiku-4.5"),
    (["--model", "gpt-5.6-luna"], {"AGENTDATA_FAKE_SERVED_MODEL": "claude-haiku-4.5"}, "claude-haiku-4.5"),
])
def test_the_fake_copilot_reports_the_model_it_was_launched_with(tmp_path, argv, env, said):
    """As the real CLI does, unless a tenant pins its own (`AGENTDATA_FAKE_SERVED_MODEL`); with no
    `--model` it reports the model its transcripts were captured on."""
    run_env = {k: v for k, v in os.environ.items() if k != "AGENTDATA_FAKE_SERVED_MODEL"}
    run_env.update(AGENTDATA_FAKE_CASE="triage-ok", PYTHONUTF8="1",
                   COPILOT_SESSION_STATE=str(tmp_path / "state"), **env)
    done = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "fakes", "runner.py"),
                           "copilot", "-p", "x", *argv], capture_output=True, text=True, env=run_env,
                          cwd=str(tmp_path), timeout=120, encoding="utf-8", errors="replace")
    raws = [json.loads(ln) for ln in done.stdout.splitlines() if ln.startswith("{")]
    models = {(r.get("data") or {}).get("model") for r in raws if r.get("type") == "assistant.message"}
    assert models == {said}, (done.returncode, done.stderr[-400:], models)
