"""`ad-confluence publish`: the page write toil does not preview, built from Markdown and run through toil's own verb.

toil's verbs are fixed (`confluence page create` / `page update <id>`), so nothing is pinned: a dry run prints the
exact toil command and starts nothing, because toil has no dry run of its own -- a write without `--allow-write` is
a refusal, not a preview. A real run waits on the approval gate in a fleet (`confluence-publish`), carries
`--allow-write` only then, and hands the body over on stdin (`--body-file -`), never as an argument.
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


@pytest.fixture()
def page(tmp_path, monkeypatch):
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    fakes.toil_connections(monkeypatch)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("- confluence_space: RDSD\n- confluence_parent: 12345\n", encoding="utf-8")
    src = tmp_path / ".agent" / "out" / "RDSD-1-confluence.md"
    src.parent.mkdir(parents=True)
    src.write_text("# RDSD-1 findings\n\nTwo rows differ.\n\n- L-1001\n- L-1002\n", encoding="utf-8")
    return tmp_path, ".agent/out/RDSD-1-confluence.md"


def _fake(monkeypatch, tmp_path, case="page_created") -> dict:
    fakes.apply(monkeypatch, tmp_path, ["toil"], case=case)
    monkeypatch.setenv("TOIL_EXE", os.path.join(str(tmp_path), "fakebin", "toil.cmd" if WINDOWS else "toil"))
    return {"AGENTDATA_FAKE_LOG": os.environ["AGENTDATA_FAKE_LOG"]}


def run(capsys, *argv):
    rc = CLI.main(["publish", *argv])
    return rc, capsys.readouterr().out


def test_a_dry_run_prints_the_plan_and_writes_nothing(page, capsys, monkeypatch):
    tmp, src = page
    env = _fake(monkeypatch, tmp)
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 0, out
    for line in ("action: create", "title: RDSD-1 findings", "space: RDSD", "dry_run: true"):
        assert line in out, out
    assert "parent: \"12345\"" in out or "parent: 12345" in out
    assert ("toil confluence page create --space RDSD --title 'RDSD-1 findings' --parent-id 12345 --body-file - "
            "--connection corp-wiki --allow-write < <") in out and "connection: corp-wiki" in out
    assert "<li>" not in out, "the body is summarised, never echoed"
    assert fakes.calls(env, "toil") == [], "a dry run never starts toil"


def test_flags_win_over_the_facts_and_an_update_names_its_page(page, capsys, monkeypatch):
    tmp, src = page
    rc, out = run(capsys, src, "--space", "DATAENG", "--title", "Other", "--dry-run")
    assert rc == 0 and "space: DATAENG" in out and "title: Other" in out
    rc, out = run(capsys, src, "--overwrite", "98765", "--dry-run")
    assert rc == 0 and "action: update" in out and "toil confluence page update 98765 --title" in out


def test_a_pinned_connection_is_named_on_the_call_and_cloud_is_its_own_area(page, capsys, monkeypatch):
    tmp, src = page
    lab = {"name": "lab-wiki", "area": "confluence", "isDefault": False, "host": "lab.example.test", "writes": True}
    fakes.toil_connections(monkeypatch, fakes.WRITABLE + [lab])
    (tmp / "cfg.json").write_text(json.dumps({"toil": {"connections": {"confluence": "lab-wiki"}}}), encoding="utf-8")
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 0 and "--connection lab-wiki --allow-write" in out
    (tmp / "cfg.json").write_text("{}", encoding="utf-8")
    fakes.toil_connections(monkeypatch, [dict(fakes.WRITABLE[1], area="confluence-cloud", name="cloud-wiki")])
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 0 and "toil confluence-cloud page create" in out and "--connection cloud-wiki" in out


@pytest.mark.parametrize("conns, error, code, says", [
    (None, "toil needs Node 24.14 or later; this is 22.22.0.", "toil_not_ready", "Node 24.14"),
    ([], "", "no_connection", "toil connections add <name> --area confluence"),
    ([dict(c, writes=False) for c in fakes.WRITABLE], "", "writes_off", "TOIL_CONFLUENCE_WRITES=true"),
])
def test_a_page_toil_cannot_write_is_refused_before_anyone_approves_it(page, capsys, monkeypatch, conns, error, code,
                                                                       says):
    """toil's own gate is read first (`toil connections list`, no network): a publish toil would refuse is refused
    here, dry run included, with the command it would have been -- and the operator is never asked to approve it."""
    _tmp, src = page
    fakes.toil_connections(monkeypatch, conns, error=error)
    asked = []
    monkeypatch.setattr(approval, "require", lambda *a, **k: asked.append(a) or approval.Decision(approval.APPROVED))
    for argv in ((src, "--dry-run"), (src,)):
        rc, out = run(capsys, *argv)
        assert rc == 2 and f"refused: {code}" in out and says in out, out
        assert "toil confluence page create" in out, "the refusal still shows what would have been sent"
    assert asked == []


def test_a_real_run_asks_the_gate_and_sends_the_body_on_stdin(page, capsys, monkeypatch):
    tmp, src = page
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
    (sent,) = fakes.calls(env, "toil")
    assert sent == ["confluence", "page", "create", "--space", "RDSD", "--title", "RDSD-1 findings",
                    "--parent-id", "12345", "--body-file", "-", "--connection", "corp-wiki", "--allow-write"]
    (body,) = fakes.stdins(env, "toil")
    assert body.startswith("<p>Two rows differ.</p>") and "<li>L-1002</li>" in body
    assert "page_id: \"98765\"" in out or "page_id: 98765" in out
    assert "url: \"https://jira.example.test/spaces/RDSD/pages/98765\"" in out or \
        "url: https://jira.example.test/spaces/RDSD/pages/98765" in out


def test_toils_own_write_refusal_at_run_time_is_reported_with_its_fix(page, capsys, monkeypatch):
    """The approval is the overlay's; `writes: true` on the connection is a person's, in toil. Should toil still
    refuse at run time (writes turned off between the plan and the run), its WRITE_DISABLED and fix are the answer,
    and nothing is retried."""
    tmp, src = page
    _fake(monkeypatch, tmp, case="write_disabled")
    monkeypatch.setattr(approval, "require", lambda *a, **k: approval.Decision(approval.APPROVED, auto=True))
    rc, out = run(capsys, src)
    assert rc == 1 and "refused: WRITE_DISABLED" in out and "writes" in out


def test_in_a_fleet_a_denied_publish_sends_nothing(page, capsys, monkeypatch, tmp_path):
    tmp, src = page
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
    assert fakes.calls(env, "toil") == []


@pytest.mark.parametrize("name, text, code", [
    ("page.html", "<h2>x</h2>", "not_markdown"),
    ("page.md", "<h2>x</h2>\n", "not_markdown"),
    ("page.md", "\n  \n", "empty_source"),
    ("page.md", "no heading at all\n", "no_title"),
])
def test_markdown_is_required(page, capsys, name, text, code):
    tmp, _src = page
    (tmp / name).write_text(text, encoding="utf-8")
    rc, out = run(capsys, name, "--dry-run")
    assert rc == 2 and f"refused: {code}" in out, out


def test_no_space_anywhere_is_refused(page, capsys):
    tmp, src = page
    (tmp / "AGENTS.md").write_text("- jira_project: RDSD\n", encoding="utf-8")
    rc, out = run(capsys, src, "--dry-run")
    assert rc == 2 and "refused: no_space" in out and "confluence_space" in out
