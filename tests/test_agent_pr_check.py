"""The agent PR check (.github/scripts/agent_pr_check.py) against the lanes in .github/agent-lanes.json (#324).

Each case builds a small repository under tmp_path with a trimmed lanes file and a `base` branch, commits one change on
a `work` branch, runs the script the way a reviewer does, and asserts the exit code and the lane it names.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "agent_pr_check.py")
LANES = os.path.join(ROOT, ".github", "agent-lanes.json")
DOC = os.path.join(ROOT, "docs", "developing-with-agents.md")

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

TRIMMED = {
    "version": 1,
    "lanes": {
        "ci": {"kind": "frozen", "paths": [".github/workflows/tests.yml", "tests/conftest.py"],
               "toml": ["tool.pytest.ini_options"], "planned": [], "note": ""},
        "version": {"kind": "release-only", "paths": ["CHANGELOG.md"], "toml": ["project.version"],
                    "planned": [], "note": ""},
        "desk-page": {"kind": "sequenced", "paths": ["agentdata/fleet/static/app.js"], "toml": [], "planned": [],
                      "note": ""},
        "serve": {"kind": "sequenced", "paths": ["agentdata/fleet/serve.py"], "toml": [], "planned": [], "note": ""},
        "shared-docs": {"kind": "append-rows", "paths": ["docs/desk-components.md"], "toml": [], "planned": [],
                        "note": ""},
    },
}

PYPROJECT = """[project]
name = "demo"
version = "1.0.0"

[tool.pytest.ini_options]
addopts = "--strict-markers"
"""

FILES = {
    ".github/agent-lanes.json": json.dumps(TRIMMED, indent=2) + "\n",
    ".github/workflows/tests.yml": "name: tests\n",
    "tests/conftest.py": "# conftest\n",
    "pyproject.toml": PYPROJECT,
    "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- first\n",
    "agentdata/fleet/serve.py": "# serve\n",
    "agentdata/fleet/static/app.js": "// app\n",
    "docs/desk-components.md": "| a | b |\n|---|---|\n| row one | 1 |\n| row two | 2 |\n",
    "README.md": "demo\n",
}


def git(repo, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True, text=True, timeout=60).stdout


def write(repo, rel: str, text: str) -> None:
    path = os.path.join(repo, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def commit(repo, changes: dict[str, str], msg: str = "change") -> None:
    for rel, text in changes.items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "checkout", "-q", "-b", "main")
    commit(r, FILES, "base")
    git(r, "branch", "base")
    git(r, "checkout", "-q", "-b", "work")
    return r


def check(repo, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, "--base", "base", *args], cwd=repo, capture_output=True,
                          text=True, timeout=120)


def violations(out: str) -> int:
    m = re.search(r"^violations: (\d+)$", out, re.M)
    assert m, out
    return int(m.group(1))


def load_script():
    spec = importlib.util.spec_from_file_location("agent_pr_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod        # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------------------------------ the map


def test_the_lanes_map_matches_the_checkout():
    mod = load_script()
    raw = json.load(open(LANES, encoding="utf-8"))
    tracked = [p for p in subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True,
                                         text=True, timeout=60).stdout.split("\0") if p]
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        pyproject = tomllib.load(f)
    assert mod.check_map(raw, tracked, pyproject) == []
    assert any(name.startswith("skin:") and name != "skin:<name>" for name in mod.expand(raw, tracked))
    assert "tests/test_agent_pr_check.py" in raw["lanes"]["relay"]["paths"]


def test_the_doc_names_the_same_lanes():
    text = open(DOC, encoding="utf-8").read()
    section = re.search(r"^## 7\. Lanes$(.*?)^## ", text, re.S | re.M).group(1)
    in_doc = re.findall(r"^\| `([^`]+)` \|", section, re.M)
    assert set(in_doc) == set(json.load(open(LANES, encoding="utf-8"))["lanes"]), in_doc
    assert "`tests/test_agent_pr_check.py`" in section


def test_the_check_imports_no_subprocess():
    tree = ast.parse(open(SCRIPT, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"subprocess", "urllib", "http", "socket", "requests"}, imported
    assert "proc" in {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "agentdata"
                      for a in n.names}


def test_the_rules_are_only_the_lane_rules():
    names = [rule.__name__ for rule in load_script().RULES]
    assert names == ["rule_frozen", "rule_declared", "rule_append_rows", "rule_two_exclusive"]


# ------------------------------------------------------------------------------------------ the check


def test_no_commits_over_the_base_touches_no_lane(repo):
    p = check(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "no lanes touched" in p.stdout


@pytest.mark.parametrize("changes, lane", [
    ({".github/workflows/tests.yml": "name: tests\non: push\n"}, "ci"),
    ({"pyproject.toml": PYPROJECT.replace("--strict-markers", "--strict-markers -q")}, "ci"),
    ({"CHANGELOG.md": "# Changelog\n\n## 1.0.1\n- next\n\n## 1.0.0\n- first\n"}, "version"),
    ({"pyproject.toml": PYPROJECT.replace('version = "1.0.0"', 'version = "1.0.1"')}, "version"),
], ids=["tests-yml", "pytest-config", "changelog", "version-line"])
def test_a_frozen_or_release_only_lane_fails_by_name(repo, changes, lane):
    commit(repo, changes)
    p = check(repo)
    assert p.returncode == 1, p.stdout + p.stderr
    assert violations(p.stdout) == 1
    assert re.search(rf"^  {lane}: ", p.stdout, re.M), p.stdout
    other = "version" if lane == "ci" else "ci"
    assert not re.search(rf"^{other} \|", p.stdout, re.M), p.stdout


def test_serve_is_its_own_lane_and_lane_declares_it(repo):
    commit(repo, {"agentdata/fleet/serve.py": "# serve\n# more\n"})
    plain, declared, wrong = check(repo), check(repo, "--lane", "serve"), check(repo, "--lane", "desk-page")
    assert "serve | sequenced | agentdata/fleet/serve.py" in plain.stdout
    assert plain.returncode == 0, plain.stdout + plain.stderr
    assert declared.returncode == 0, declared.stdout + declared.stderr
    assert wrong.returncode == 1, wrong.stdout + wrong.stderr
    assert re.search(r"^  serve: sequenced lane touched but not declared", wrong.stdout, re.M), wrong.stdout


def test_allow_passes_an_approved_frozen_lane(repo):
    commit(repo, {"tests/conftest.py": "# conftest\n# approved\n"})
    assert check(repo).returncode == 1
    p = check(repo, "--allow", "ci")
    assert p.returncode == 0, p.stdout + p.stderr
    assert violations(p.stdout) == 0
    assert re.search(r"^allowed: ci: .*tests/conftest\.py", p.stdout, re.M), p.stdout


def test_a_deleted_row_in_a_shared_doc_only_warns(repo):
    commit(repo, {"docs/desk-components.md": "| a | b |\n|---|---|\n| row one | 1 |\n"})
    p = check(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert re.search(r"^warning: shared-docs: docs/desk-components\.md lost 1 line", p.stdout, re.M), p.stdout


def test_main_s_frozen_change_merged_into_the_branch_is_not_the_branch_s(repo):
    commit(repo, {"README.md": "demo\nbranch work\n"}, "branch work")
    git(repo, "checkout", "-q", "base")
    commit(repo, {".github/workflows/tests.yml": "name: tests\non: push\n"}, "main's ci change")
    git(repo, "checkout", "-q", "work")
    git(repo, "merge", "-q", "--no-edit", "base")
    p = check(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "- | - | README.md" in p.stdout
    assert "tests.yml" not in p.stdout


def test_an_unknown_base_cannot_run_and_says_fetch(repo):
    p = subprocess.run([sys.executable, SCRIPT, "--base", "origin/nowhere"], cwd=repo, capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "git fetch origin" in p.stderr
