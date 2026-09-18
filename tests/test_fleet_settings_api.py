"""`/api/settings`: an enumerated table, and refusals instead of coercions.

The page writes `~/.agentdata/config.json`, which is the file every `ad-*` command reads. So the
interesting tests here are not the happy path -- they are the four ways a settings endpoint usually
goes wrong:

* it accepts a key nobody enumerated, and a browser becomes a way to set anything;
* it coerces a typo instead of refusing it, and a cap silently becomes zero;
* it offers a knob that is read by nobody, so the control does nothing and the operator is left
  doubting the page rather than the setting;
* it lets a value through that becomes a second flag on a command line.
"""
from __future__ import annotations
import glob
import json
import os
import re

import pytest

from agentdata import config as C
from agentdata.fleet import launch as L, registry, serve as S, settings as SET
from agentdata.fleet.registry import Registry

from test_fleet import make_project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path


def _repo(tmp_path, name="alpha"):
    Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)


# ------------------------------------------------------------------------------------- the shape


def test_the_snapshot_carries_the_options_and_the_answer(fleet_home, tmp_path):
    """`/api/themes` shipped the choices and not the choice, and the pickers opened blank over a
    configured skin (#195). The same mistake here would be a page of controls set to defaults over
    a config that says otherwise, so both halves come back in one payload."""
    _repo(tmp_path)
    C.save({"fleet": {"approval_timeout": 60, "model": "claude-opus-5"}})

    snap = S.settings_snapshot()
    keys = {row["key"] for row in snap["editable"]}
    assert "fleet.approval_timeout" in keys
    assert snap["current"]["fleet.approval_timeout"] == 60, "the answer, not the default"
    assert snap["current"]["fleet.max_restarts"] == 1, "and the default where there is no answer"

    for row in snap["editable"]:
        assert row["scope"], f"{row['key']} does not say when a change takes effect"
        assert row["why"], f"{row['key']} does not say what it does"
        assert row["type"] in ("int", "float", "bool", "str", "enum"), row
        if row["type"] == "enum":
            assert row.get("choices"), f"{row['key']} is an enum with nothing to choose"

    assert snap["model"]["fleet"]["model"] == "claude-opus-5"
    assert [r["repo"] for r in snap["model"]["repos"]] == ["alpha"]
    assert snap["model"]["repos"][0]["source"] == "fleet.model"


def test_the_tool_lists_come_back_with_their_provenance(fleet_home, tmp_path):
    """Read-only on the page, so the value it has is answering *what may this agent run* at a
    glance -- which needs a pattern the operator added to look different from one that shipped."""
    _repo(tmp_path)
    snap = S.settings_snapshot()
    allow = {r["pattern"]: r["source"] for r in snap["tools"]["allow"]}
    deny = {r["pattern"]: r["source"] for r in snap["tools"]["deny"]}
    assert allow["shell(ad-state)"] == "default"
    assert deny["shell(git push)"] == "default"
    assert snap["tools"]["allow_is_configured"] is False

    C.save({"fleet": {"allow_tools": ["shell(ad-state)"], "deny_tools": ["shell(curl --insecure)"]}})
    snap = S.settings_snapshot()
    allow = {r["pattern"]: r["source"] for r in snap["tools"]["allow"]}
    deny = {r["pattern"]: r["source"] for r in snap["tools"]["deny"]}
    assert allow == {"shell(ad-state)": "configured"}, "a configured allow-list REPLACES the default"
    assert deny["shell(curl --insecure)"] == "configured"
    assert deny["shell(git push)"] == "default", "and the deny floor is still under it"
    assert snap["tools"]["allow_is_configured"] is True


def test_every_editable_key_is_actually_read_somewhere(fleet_home):
    """A control for a setting nobody reads is a control that does nothing, and the operator will
    blame the page. `fleet.console.idle_s` is documented with a default and has no call site at
    all -- this is what keeps it, and anything like it, off the page."""
    sources = []
    for path in glob.glob(os.path.join(ROOT, "agentdata", "**", "*.py"), recursive=True):
        sources.append(open(path, encoding="utf-8").read())
    body = "\n".join(sources)

    missing = []
    for key in SET.EDITABLE:
        head, _, leaf = key.rpartition(".")
        # `C.get(cfg, "fleet.notify.chime")`, or the `f"fleet.notify.{key}"` shape, or a `get` on
        # the parent followed by the leaf -- all three are real readers in this codebase.
        if key in body:
            continue
        if re.search(rf'"{re.escape(head)}\.\{{', body) and f'"{leaf}"' in body:
            continue
        missing.append(key)
    assert missing == [], f"the page offers settings nothing reads: {missing}"


# --------------------------------------------------------------------------------- the refusals


def test_a_key_outside_the_table_is_refused_and_nothing_is_written(fleet_home, tmp_path):
    _repo(tmp_path)
    C.save({"fleet": {"max_restarts": 1}})
    before = open(C.path(), "rb").read()

    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"set": [{"key": "fleet.allow_tools", "value": ["shell(rm)"]}]})
    assert e.value.code == "unknown_key"
    assert "may change" in e.value.msg
    assert open(C.path(), "rb").read() == before, "the file moved on a refused write"

    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"set": [{"key": "jira.base_url", "value": "http://nope"}]})
    assert e.value.code == "unknown_key", "the page cannot reach outside fleet.* either"
    assert open(C.path(), "rb").read() == before


@pytest.mark.parametrize("key,value", [
    ("fleet.max_restarts", "two"),
    ("fleet.max_restarts", ""),
    ("fleet.max_restarts", "-1"),
    ("fleet.notify.chime", "maybe"),
    ("fleet.console.host", "powershell"),
])
def test_a_wrong_value_is_refused_rather_than_coerced(fleet_home, tmp_path, key, value):
    """`fleet.budget_per_agent` is the cautionary tale: a non-numeric value there becomes 0.0, which
    turns the cap off. A settings page that coerced would do that to every number on it."""
    _repo(tmp_path)
    C.save({"fleet": {"max_restarts": 3}})
    before = open(C.path(), "rb").read()

    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"set": [{"key": key, "value": value}]})
    assert e.value.code == "bad_type", e.value.msg
    assert open(C.path(), "rb").read() == before, "a refused value still changed the file"


def test_a_model_that_would_become_a_second_flag_is_refused(fleet_home, tmp_path):
    """The launch-time check reads the allow and deny lists and would never see this. Refusing it
    here turns a failed start hours later into a refused keystroke now."""
    _repo(tmp_path)
    for bad in ("x --allow-all-tools", "--yolo", "a b"):
        with pytest.raises(S.ServeError) as e:
            S.act("settings", {"models": [{"repo": "alpha", "model": bad}]})
        assert e.value.code == "bad_model", bad
    assert C.get_leaf(C.load(), "fleet.models", "alpha", {}) == {}


def test_a_repo_that_is_not_named_is_refused(fleet_home, tmp_path):
    _repo(tmp_path)
    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"models": [{"repo": "", "model": "x"}]})
    assert e.value.code == "no_repo"


# ----------------------------------------------------------------------------------- the writes


def test_a_setting_is_written_and_comes_back_in_the_same_answer(fleet_home, tmp_path):
    _repo(tmp_path)
    out = S.act("settings", {"set": [{"key": "fleet.approval_timeout", "value": "90"},
                                     {"key": "fleet.notify.chime", "value": True}]})
    assert C.get(C.load(), "fleet.approval_timeout") == 90
    assert C.get(C.load(), "fleet.notify.chime") is True
    # the answer is the fresh snapshot, so the page never renders what it hoped it wrote
    assert out["current"]["fleet.approval_timeout"] == 90


def test_a_per_repo_model_survives_a_dot_in_the_repository_name(fleet_home, tmp_path):
    """`C.put(cfg, f"fleet.models.{name}")` would shred `rdsd.pbi` into nested keys and the setting
    would vanish with no error at all -- which is the failure `put_leaf` exists for."""
    Registry().add(make_project(tmp_path / "rdsd.pbi", ticket="RDSD-1"), name="rdsd.pbi")
    S.act("settings", {"models": [{"repo": "rdsd.pbi", "model": "claude-haiku-4.5", "effort": "low"}]})

    cfg = C.load()
    assert C.get_leaf(cfg, "fleet.models", "rdsd.pbi") == {"model": "claude-haiku-4.5", "effort": "low"}
    assert L.model_for("rdsd.pbi", cfg) == ("claude-haiku-4.5", "low", "fleet.models.rdsd.pbi")
    # and the file really holds one key with a dot in it, not two nested ones
    saved = json.loads(open(C.path(), encoding="utf-8").read())
    assert list(saved["fleet"]["models"]) == ["rdsd.pbi"]


def test_clearing_a_model_removes_the_key_rather_than_leaving_an_empty_one(fleet_home, tmp_path):
    """An empty object in the file reads as a setting somebody made. Inheriting is the absence of
    one, so that is what gets written."""
    _repo(tmp_path)
    S.act("settings", {"models": [{"repo": "alpha", "model": "claude-opus-5"}]})
    assert C.get_leaf(C.load(), "fleet.models", "alpha") == {"model": "claude-opus-5"}

    S.act("settings", {"models": [{"repo": "alpha", "model": ""}]})
    cfg = C.load()
    assert C.get_leaf(cfg, "fleet.models", "alpha", None) is None
    assert L.model_for("alpha", cfg) == ("", "", "cli-auto")


def test_the_fleet_wide_default_is_written_and_resolves_under_a_per_repo_one(fleet_home, tmp_path):
    _repo(tmp_path, "alpha")
    _repo(tmp_path, "beta")
    S.act("settings", {"model": "claude-sonnet-5", "effort": "medium"})
    S.act("settings", {"models": [{"repo": "beta", "model": "claude-opus-5"}]})

    cfg = C.load()
    assert L.model_for("alpha", cfg) == ("claude-sonnet-5", "medium", "fleet.model")
    assert L.model_for("beta", cfg)[0] == "claude-opus-5"
    assert L.model_for("beta", cfg)[2] == "fleet.models.beta"


def test_the_action_is_in_the_vocabulary_an_unknown_one_lists(fleet_home, tmp_path):
    """Every refusal in this server speaks one vocabulary; an action missing from the hint is one
    nobody can discover from the error."""
    _repo(tmp_path)
    with pytest.raises(S.ServeError) as e:
        S.act("nonsense", {})
    assert "settings" in (e.value.hint or "") + e.value.msg
