"""`ad-confluence publish`: the page write pncli does not gate, built from Markdown and run through pncli's own verb.

The verb is the operator's to pin (`pncli.verbs.page_create` / `page_update`): until then every run is a
`not_pinned` refusal, dry run included, because a guessed verb is a write nobody read the help for. A real run
waits on the approval gate in a fleet (`confluence-publish`), and the body travels as ONE argv element.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from agentdata import cli_confluence as CLI
from agentdata.fleet import approval, registry

import fakes

WINDOWS = os.name == "nt"
CREATE = "confluence create-page --space {space} --title {title} --parent {parent} --body {body}"
UPDATE = "confluence update-page --id {page_id} --title {title} --body {body}"


@pytest.fixture()
def page(tmp_path, monkeypatch):
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("- confluence_space: RDSD\n- confluence_parent: 12345\n", encoding="utf-8")
    src = tmp_path / ".agent" / "out" / "RDSD-1-confluence.md"
    src.parent.mkdir(parents=True)
    src.write_text("# RDSD-1 findings\n\nTwo rows differ.\n\n- L-1001\n- L-1002\n", encoding="utf-8")
    return tmp_path, ".agent/out/RDSD-1-confluence.md"


def _pin(tmp_path, **verbs):
    (tmp_path / "cfg.json").write_text(json.dumps({"pncli": {"verbs": verbs}}), encoding="utf-8")


def _fake(monkeypatch, tmp_path, case="page_created") -> dict:
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case=case)
    monkeypatch.setenv("PNCLI_EXE", os.path.join(str(tmp_path), "fakebin", "pncli.cmd" if WINDOWS else "pncli"))
    return {"AGENTDATA_FAKE_LOG": os.environ["AGENTDATA_FAKE_LOG"]}


def run(capsys, *argv):
    rc = CLI.main(["publish", *argv])
    return rc, capsys.readouterr().out


def test_an_unpinned_verb_is_refused_with_how_to_pin_it(page, capsys):
    _tmp, src = page
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 2 and "refused: not_pinned" in out
    assert "pncli confluence create-page --help" in out and "pncli.verbs.page_create" in out
    rc, out = run(capsys, src, "--overwrite", "98765", "--dry-run")
    assert rc == 2 and "refused: not_pinned" in out and "pncli.verbs.page_update" in out


def test_a_dry_run_prints_the_plan_and_writes_nothing(page, capsys, monkeypatch):
    tmp, src = page
    _pin(tmp, page_create=CREATE)
    env = _fake(monkeypatch, tmp)
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 0, out
    for line in ("action: create", "title: RDSD-1 findings", "space: RDSD", "dry_run: true"):
        assert line in out, out
    assert "parent: \"12345\"" in out or "parent: 12345" in out
    assert "--parent 12345 --body <" in out and "<li>" not in out, "the body is summarised, never echoed"
    assert fakes.calls(env, "pncli") == [], "a dry run never starts pncli"


def test_flags_win_over_the_facts_and_an_update_names_its_page(page, capsys, monkeypatch):
    tmp, src = page
    _pin(tmp, page_create=CREATE, page_update=UPDATE)
    rc, out = run(capsys, src, "--space", "DATAENG", "--title", "Other", "--dry-run")
    assert rc == 0 and "space: DATAENG" in out and "title: Other" in out
    rc, out = run(capsys, src, "--overwrite", "98765", "--dry-run")
    assert rc == 0 and "action: update" in out and "98765" in out and "update-page --id 98765" in out


def test_a_real_run_asks_the_gate_and_sends_the_body_as_one_argument(page, capsys, monkeypatch):
    tmp, src = page
    _pin(tmp, page_create=CREATE)
    env = _fake(monkeypatch, tmp)
    asked = []

    def require(kind, summary, payload=None, **kw):
        asked.append((kind, summary, dict(payload or {})))
        return approval.Decision(approval.APPROVED, auto=True)

    monkeypatch.setattr(approval, "require", require)
    rc, out = run(capsys, src)
    assert rc == 0, out
    assert [k for k, _s, _p in asked] == ["confluence-publish"]
    assert asked[0][2]["title"] == "RDSD-1 findings" and asked[0][2]["space"] == "RDSD"
    assert "body" not in asked[0][2], "the operator approves the command, not thousands of characters of HTML"
    (sent,) = fakes.calls(env, "pncli")
    assert sent[:4] == ["confluence", "create-page", "--space", "RDSD"]
    assert sent[-2] == "--body" and sent[-1].startswith("<p>Two rows differ.</p>") and "<li>L-1002</li>" in sent[-1]
    assert "page_id: \"98765\"" in out or "page_id: 98765" in out
    assert "url: \"https://confluence.example.test/spaces/RDSD/pages/98765\"" in out or \
        "url: https://confluence.example.test/spaces/RDSD/pages/98765" in out


def test_in_a_fleet_a_denied_publish_sends_nothing(page, capsys, monkeypatch, tmp_path):
    tmp, src = page
    _pin(tmp, page_create=CREATE)
    env = _fake(monkeypatch, tmp)
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv(registry.AGENT_ENV, "luna")

    def operator():
        deadline = time.time() + 10
        while time.time() < deadline:
            waiting = approval.pending()
            if waiting:
                approval.decide(waiting[0]["id"], approval.DENIED, reason="not today", by="operator")
                return
            time.sleep(0.02)

    t = threading.Thread(target=operator, daemon=True)
    t.start()
    rc, out = run(capsys, src)
    t.join(timeout=10)
    assert rc == 2 and "refused: approval_denied" in out and "not today" in out
    assert fakes.calls(env, "pncli") == []


@pytest.mark.parametrize("name, text, code", [
    ("page.html", "<h2>x</h2>", "not_markdown"),
    ("page.md", "<h2>x</h2>\n", "not_markdown"),
    ("page.md", "\n  \n", "empty_source"),
    ("page.md", "no heading at all\n", "no_title"),
])
def test_markdown_is_required(page, capsys, name, text, code):
    tmp, _src = page
    _pin(tmp, page_create=CREATE)
    (tmp / name).write_text(text, encoding="utf-8")
    rc, out = run(capsys, name, "--dry-run")
    assert rc == 2 and f"refused: {code}" in out, out


def test_no_space_anywhere_is_refused(page, capsys):
    tmp, src = page
    _pin(tmp, page_create=CREATE)
    (tmp / "AGENTS.md").write_text("- jira_project: RDSD\n", encoding="utf-8")
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 2 and "refused: no_space" in out and "confluence_space" in out


def test_a_template_without_the_body_or_with_an_unknown_placeholder_is_refused(page, capsys):
    tmp, src = page
    _pin(tmp, page_create="confluence create-page --space {space} --title {title}")
    assert "refused: bad_template" in run(capsys, src, "--dry-run")[1]
    _pin(tmp, page_create="confluence create-page --space {space} --body {body} --label {label}")
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 2 and "refused: bad_template" in out and "{label}" in out
