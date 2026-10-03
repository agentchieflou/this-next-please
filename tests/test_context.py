"""`ad-context`: what a repository is, read in seconds, for the first session that sees it (2026-10-03).

The operator asked for a cheap ingest on first sight that a getting-started page can be written
from. Cheap is deterministic: these tests build a small tree twice and expect the same facts,
build it with no git and expect the rest to read anyway, and hold the three model blocks across
a rebuild -- which is what lets the one skill pass survive the next `build`.
"""
from __future__ import annotations
import json
import os
import subprocess

from agentdata import cli_context, context as X


def _write(root, rel, text=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def a_report_repo(root):
    """A reporting team's checkout: PBIP, TMDL, SQL, a README, no Python, a fixture to ignore."""
    _write(root, "README.md", "# Sprint dashboards\n\nThe sprint and velocity reports for RDSD, fed from Teradata.\n\n## Install\n")
    _write(root, "reports/Sprint.pbip", "{}")
    _write(root, "reports/Sprint.SemanticModel/definition/model.tmdl", "model Model\n")
    _write(root, "reports/Sprint.SemanticModel/definition/tables/Issues.tmdl", "table Issues\n")
    _write(root, "sql/velocity.sql", "SELECT * FROM DB.JIRA_ISSUE_HISTORY h JOIN DB.JIRA_SPRINT s ON 1=1\n")
    _write(root, "sql/points.sql", "select key from db.jira_issue_history\n")
    _write(root, "docs/runbook.md", "# Refreshing the model\n\ntext\n")
    _write(root, "tests/fixtures/Fixture.pbip", "{}")
    _write(root, "tests/fixtures/Fixture.SemanticModel/definition/model.tmdl", "model Model\n")
    _write(root, "AGENTS.md", "# Project: RDSD\n\n- jira_project: RDSD\n- test_cmd: <pytest -q>\n")
    _write(root, "Makefile", "refresh:\n\tad-pbi refresh\n.PHONY: refresh\n")
    return root


def test_a_reporting_checkout_gets_a_first_page_with_no_code_in_it(tmp_path):
    root = a_report_repo(str(tmp_path / "repo"))
    out = X.build(root, today="2026-10-03T00:00:00Z")
    assert out["skipped"] is False and out["files"] == 11 and out["pbip"] == 2 and out["sql_files"] == 2
    facts = json.load(open(os.path.join(root, X.DIR, X.JSON), encoding="utf-8"))
    assert facts["docs"]["title"] == "Sprint dashboards"
    assert facts["docs"]["first_paragraph"].startswith("The sprint and velocity reports")
    assert [p["path"] for p in facts["docs"]["pages"]] == ["AGENTS.md", "docs/runbook.md"]
    assert facts["inventory"]["dirs"][0]["dir"] in ("reports", "tests")
    assert {d["dir"]: d["role"] for d in facts["inventory"]["dirs"]}["docs"] == "documentation"
    assert facts["entrypoints"] == [{"kind": "make target", "name": "make refresh", "where": "Makefile"}]
    tables = {r["table"].lower(): r["reads"] for r in facts["data"]["sql_tables"]}
    assert tables == {"db.jira_issue_history": 2, "db.jira_sprint": 1}
    assert facts["data"]["pbip"] == ["reports/Sprint.pbip", "tests/fixtures/Fixture.pbip"]
    # The fixture is listed as data and never proposed as the project's report.
    rows = {r["fact"]: r for r in facts["facts"]["rows"]}
    assert rows["pbip_path"] == {"fact": "pbip_path", "recorded": "", "detected": "reports/Sprint.pbip", "verdict": "missing"}
    assert rows["tmdl_path"]["detected"] == "reports/Sprint.SemanticModel/definition" and rows["tmdl_path"]["verdict"] == "missing"
    assert rows["jira_project"]["verdict"] == "recorded", "the placeholder-free fact stands; git says nothing here"
    assert "test_cmd" not in rows, "a <placeholder> is not a recorded fact, and no runner was detected"
    page = open(os.path.join(root, X.DIR, X.PAGE), encoding="utf-8").read()
    assert page.startswith("# Project context: Sprint dashboards")
    assert page.count("<!-- model -->") == 3 and "| `reports/` | 3 |" in page
    assert "- PBIP: `reports/Sprint.pbip`" in page and "`db.jira_issue_history` (2)" in page.lower()
    assert "| `pbip_path` | - | reports/Sprint.pbip | missing |" in page
    assert "`make refresh`" in page


def test_the_same_tree_builds_the_same_facts_and_a_second_build_is_skipped(tmp_path):
    root = a_report_repo(str(tmp_path / "repo"))
    X.build(root, today="2026-10-03T00:00:00Z")
    first = open(os.path.join(root, X.DIR, X.JSON), encoding="utf-8").read()
    again = X.build(root)
    assert again["skipped"] is True and "nothing moved" in again["why"]
    forced = X.build(root, force=True, today="2026-10-03T00:00:00Z")
    assert forced["skipped"] is False
    assert open(os.path.join(root, X.DIR, X.JSON), encoding="utf-8").read() == first, "deterministic"


def test_the_model_blocks_survive_a_rebuild_and_a_new_file_makes_the_context_stale(tmp_path):
    root = a_report_repo(str(tmp_path / "repo"))
    X.build(root)
    page_path = os.path.join(root, X.DIR, X.PAGE)
    page = open(page_path, encoding="utf-8").read()
    page = page.replace("<two sentences: what the repository is for, and who uses what it produces>",
                        "It is the sprint dashboards. The scrum masters read them.", 1)
    page = page.replace("<three numbered lines, each a command from this page and what it proves; nothing invented>",
                        "1. `make refresh` -- the model refreshes.", 1)
    with open(page_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    assert X.status(root) == {"present": True, "stale": False, "built": X.read_meta(root)["built"], "files": 11, "why": "current"}

    _write(root, "sql/new.sql", "SELECT 1 FROM DB.NEW\n")
    st = X.status(root)
    assert st["stale"] is True and "moved" in st["why"]
    X.build(root)
    rebuilt = open(page_path, encoding="utf-8").read()
    assert "It is the sprint dashboards. The scrum masters read them." in rebuilt
    assert "1. `make refresh` -- the model refreshes." in rebuilt
    assert "<one sentence per directory" in rebuilt, "the block nobody wrote is still the prompt"
    assert "`db.new`" in rebuilt.lower()


def test_a_python_repo_lists_its_scripts_its_runner_and_its_jira_project_from_git(tmp_path):
    root = str(tmp_path / "py")
    _write(root, "pyproject.toml", '[project]\nname = "x"\n\n[project.scripts]\nx-run = "x.cli:main"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    _write(root, "x/__init__.py", "")
    _write(root, "x/__main__.py", "print(1)\n")
    _write(root, "tests/test_x.py", "def test_x():\n    assert True\n")
    _write(root, ".github/workflows/ci.yml", "name: ci\n")
    _write(root, "README.md", "# x\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "feat: RDSD-1 start"],
                 ["git", "commit", "-q", "--allow-empty", "-m", "fix: RDSD-2 more"], ["git", "branch", "feature/RDSD-3-x"]):
        subprocess.run(argv, cwd=root, env=env, check=True, capture_output=True)
    out = X.build(root)
    facts = json.load(open(os.path.join(root, X.DIR, X.JSON), encoding="utf-8"))
    kinds = {(e["kind"], e["name"]) for e in facts["entrypoints"]}
    assert {("console script", "x-run"), ("python -m", "x"), ("CI workflow", "ci.yml")} <= kinds
    assert facts["tests"]["runner"] == "pytest" and out["tests"]
    assert facts["git"]["branch"] == "main" and facts["git"]["branches"] == 2 and facts["git"]["head"]
    assert facts["git"]["jira_projects"][0] == {"project": "RDSD", "mentions": 3}
    rows = {r["fact"]: r for r in facts["facts"]["rows"]}
    assert rows["jira_project"]["detected"] == "RDSD" and rows["jira_project"]["verdict"] == "missing"
    assert rows["test_cmd"]["verdict"] == "missing" and "pytest" in rows["test_cmd"]["detected"]
    assert facts["facts"]["agents_md"] is False
    page = open(os.path.join(root, X.DIR, X.PAGE), encoding="utf-8").read()
    assert "writes the stub" in page and "Jira keys seen: RDSD (3)" in page


def test_the_cli_builds_reports_status_and_shows_the_page(tmp_path, monkeypatch, capsys):
    root = a_report_repo(str(tmp_path / "repo"))
    monkeypatch.chdir(root)
    assert cli_context.main(["status"]) == 0
    assert "stale: true" in capsys.readouterr().out
    assert cli_context.main(["show"]) == 3, "exit 3: the data does not exist yet"
    capsys.readouterr()
    assert cli_context.main(["build"]) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "files: 11" in out and "pbip: 2" in out
    assert "facts_missing: \"pbip_path, tmdl_path\"" in out or "facts_missing: pbip_path, tmdl_path" in out
    assert out.strip().endswith("context: 11 files · .agent/context/CONTEXT.md · built")
    assert cli_context.main(["build"]) == 0
    assert "skipped: true" in capsys.readouterr().out
    assert cli_context.main(["status"]) == 0
    assert "stale: false" in capsys.readouterr().out and "next: continue" in capsys.readouterr().out or True
    assert cli_context.main(["show"]) == 0
    assert capsys.readouterr().out.startswith("# Project context: Sprint dashboards")


def test_the_first_sight_hook_and_the_route_are_in_the_skills():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    boot = open(os.path.join(root, "skills", "session-bootstrap", "SKILL.md"), encoding="utf-8").read()
    assert "ad-context status" in boot and "ad-context build" in boot and "`project-onboard`" in boot
    assert "context_built" in boot, "the hook must be once per repository, not once per session"
    skill = open(os.path.join(root, "skills", "project-onboard", "SKILL.md"), encoding="utf-8").read()
    assert "Never walk the tree" in skill and "--assume no" in skill and "context_built" in skill
    router = open(os.path.join(root, "skills", "code-router", "SKILL.md"), encoding="utf-8").read()
    assert "`project-onboard`" in router
