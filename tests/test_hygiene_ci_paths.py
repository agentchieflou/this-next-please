"""The CI path map cannot miss a path (#594, CI-2; plan §4.6, decision 23 on #429).

A path filter's one real risk is a file that affects a job but does not turn it on. This file reads
`.github/ci-paths.json` and `.github/workflows/tests.yml` and fails when the map could miss one:

- every tracked file belongs to a group (an unnamed one would run everything, which hides the gap);
- every group turns on a job, and every job but the always-on ones has a group; the map's jobs and
  their names are the workflow's; `ci-ok` (CI-3, #595) exists and `needs:` every job;
- `desk`, the only group that turns on the four Linux browser jobs, names every module in the `ast`
  import closure of `agentdata.fleet.serve`, `agentdata.cli_fleet` and every test file carrying the
  `browser` marker, and names each of those test files. A new import into the closure fails here until
  the map names it;
- CI-1's fixture diffs (`tests/test_ci_paths.py`) still give their groups against the real map.
"""
from __future__ import annotations

import ast
import copy
import functools
import importlib.util
import json
import os
import subprocess

import yaml

from test_ci_paths import ALL, FIXTURE_DIFFS
from test_hygiene_linux_shards import rows_of
from test_hygiene_windows_shards import render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "ci_paths.py")
MAP = os.path.join(ROOT, ".github", "ci-paths.json")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")

#: The desk's roots: the server and the CLI that starts it. Every browser test is a root as well.
DESK_ROOTS = ("agentdata/fleet/serve.py", "agentdata/cli_fleet.py")
#: Jobs that run on every change and so need no group (plan §4.4); `smoke` and `ci-ok` came with CI-3 (#595).
ALWAYS = {"changes", "lint-shell-scripts", "floor-lints", "smoke", "ci-ok"}
#: The closure had 121 modules (230 files with the browser tests and their helpers) when this was
#: written; a much smaller number means the walk stopped resolving imports, not that the desk shrank.
CLOSURE_FLOOR = 100


def _script():
    spec = importlib.util.spec_from_file_location("ci_paths_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CP = _script()


def _map() -> dict:
    return CP.load(MAP)


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.cache
def _tracked() -> tuple[str, ...]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True,
                         timeout=60).stdout
    return tuple(p for p in out.split("\0") if p)


def _parse(rel: str, root: str = ROOT) -> ast.Module:
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return ast.parse(f.read(), filename=rel)


def carries_browser_marker(tree: ast.Module) -> bool:
    """`pytest.mark.browser` anywhere in the code (a decorator, `pytestmark`, a `param(marks=...)`), not in a string."""
    return any(isinstance(n, ast.Attribute) and n.attr == "browser"
               and isinstance(n.value, ast.Attribute) and n.value.attr == "mark" for n in ast.walk(tree))


@functools.cache
def browser_test_files(tracked: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(p for p in tracked if p.startswith("tests/") and p.endswith(".py")
                  and carries_browser_marker(_parse(p))))


def _resolve(module: str, here: str, root: str) -> str | None:
    """A dotted name as a tracked file: from the root, the importing file's directory, or `tests/` (pytest's
    rootdir-relative imports, e.g. `from test_hygiene_windows_shards import ...`)."""
    for base in ("", here, "tests"):
        stem = os.path.join(base, *module.split("."))
        for rel in (os.path.join(stem, "__init__.py"), stem + ".py"):
            if os.path.isfile(os.path.join(root, rel)):
                return os.path.normpath(rel).replace(os.sep, "/")
    return None


def import_closure(roots, root: str = ROOT) -> set[str]:
    """Every repository file `roots` import, transitively, by `ast`: every `import` in the file, lazy ones
    inside functions included, and each package's `__init__.py` on the way down."""
    seen, todo = set(), list(roots)
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        here = os.path.dirname(rel)
        parent = here
        while parent:
            if os.path.isfile(os.path.join(root, parent, "__init__.py")):
                todo.append(f"{parent}/__init__.py")
            parent = os.path.dirname(parent)
        package = here.split("/") if here else []
        for node in ast.walk(_parse(rel, root)):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package) - node.level + 1] if node.level else []
                module = ".".join(base + ([node.module] if node.module else []))
                names = [module] + [f"{module}.{a.name}" for a in node.names]
            else:
                continue
            for name in names:
                parts = name.split(".")
                for i in range(len(parts), 0, -1):  # `from x import y`: y a module, or a name in x
                    hit = _resolve(".".join(parts[:i]), here, root)
                    if hit:
                        todo.append(hit)
                        break
    return seen


@functools.cache
def desk_closure(tracked: tuple[str, ...]) -> frozenset[str]:
    return frozenset(import_closure([*DESK_ROOTS, *browser_test_files(tracked)]))


def unmapped(cmap: dict, tracked) -> list[str]:
    return [p for p in tracked if not any(CP.names(spec, p) for spec in cmap["groups"].values())]


def desk_misses(cmap: dict, files) -> list[str]:
    return sorted(p for p in files if not CP.names(cmap["groups"]["desk"], p))


def job_problems(cmap: dict, workflow: dict) -> list[str]:
    problems = []
    jobs = workflow["jobs"]
    if list(cmap["jobs"]) != list(jobs):
        problems.append(f"the map's jobs {list(cmap['jobs'])} are not the workflow's {list(jobs)}")
    for job_id, job in jobs.items():
        spec = cmap["jobs"].get(job_id, {})
        names = list(dict.fromkeys(render(job.get("name", job_id), row) for row in rows_of(job)))
        if spec.get("names") != names:
            problems.append(f"{job_id}: the map names it {spec.get('names')}, the workflow {names}")
        if spec.get("always") and job_id not in ALWAYS:
            problems.append(f"{job_id}: only {sorted(ALWAYS)} may run on every change")
        if not spec.get("always") and not spec.get("groups"):
            problems.append(f"{job_id}: no group turns it on")
        for group in spec.get("groups", ()):
            if group not in cmap["groups"]:
                problems.append(f"{job_id}: turned on by `{group}`, which the map does not define")
    for group, gspec in cmap["groups"].items():
        turns_on = [j for j, s in cmap["jobs"].items() if group in s.get("groups", ())]
        if gspec.get("everything") or gspec.get("smoke_only"):
            if turns_on:
                problems.append(f"{group}: `everything`/`smoke_only` and a job list at once: {turns_on}")
        elif not turns_on:
            problems.append(f"{group}: turns on no job")
    if "ci-ok" not in jobs:  # CI-3 (#595)
        problems.append("ci-ok: no such job, so nothing sums the run up")
    else:
        needs = jobs["ci-ok"].get("needs") or []
        missing = sorted(set(jobs) - {"ci-ok"} - set([needs] if isinstance(needs, str) else needs))
        if missing:
            problems.append(f"ci-ok: does not need {missing}")
    return problems


def test_every_tracked_file_belongs_to_a_group():
    missing = unmapped(_map(), _tracked())
    assert missing == [], (
        f"{len(missing)} tracked file(s) no group in .github/ci-paths.json names; the `changes` job runs "
        f"everything for them. Add each to the group(s) whose jobs it can change: {missing[:40]}")


def test_every_group_turns_on_a_job_and_every_job_has_a_group():
    assert job_problems(_map(), _workflow()) == []


def test_the_job_check_fails_on_a_job_with_no_group_a_renamed_job_and_a_ci_ok_that_misses_one():
    cmap, wf = _map(), _workflow()
    no_group = copy.deepcopy(cmap)
    no_group["jobs"]["coverage"]["groups"] = []
    assert any(p.startswith("coverage: no group") for p in job_problems(no_group, wf))
    renamed = copy.deepcopy(wf)
    renamed["jobs"]["floor-python"]["name"] = "floor · something else"
    assert any(p.startswith("floor-python: the map names it") for p in job_problems(cmap, renamed))
    idle = copy.deepcopy(cmap)
    for spec in idle["jobs"].values():
        spec["groups"] = [g for g in spec.get("groups", ()) if g != "ide-desktop"]
    assert any(p.startswith("ide-desktop: turns on no job") for p in job_problems(idle, wf))
    with_ci_ok = copy.deepcopy(wf)
    with_ci_ok["jobs"]["ci-ok"] = {"name": "ci-ok", "needs": [j for j in wf["jobs"] if j != "browser"]}
    assert "ci-ok: does not need ['browser']" in job_problems(cmap, with_ci_ok)
    without = copy.deepcopy(wf)
    del without["jobs"]["ci-ok"]
    assert "ci-ok: no such job, so nothing sums the run up" in job_problems(cmap, without)


def test_desk_names_the_import_closure_of_serve_cli_fleet_and_every_browser_test():
    cmap, tracked = _map(), _tracked()
    closure = desk_closure(tracked)
    modules = {p for p in import_closure(DESK_ROOTS) if p.startswith("agentdata/")}
    assert len(modules) >= CLOSURE_FLOOR, f"only {len(modules)} modules: the import walk stopped resolving"
    assert set(DESK_ROOTS) <= closure and not closure - set(tracked), sorted(closure - set(tracked))
    missing = desk_misses(cmap, closure)
    assert missing == [], (
        f"the desk imports {missing}, and a change to them would not turn the browser jobs on. "
        "Add each to `desk` in .github/ci-paths.json")


def test_desk_names_every_test_file_that_carries_the_browser_marker():
    cmap, tracked = _map(), _tracked()
    browser = browser_test_files(tracked)
    assert len(browser) >= 80 and "tests/test_fleet_ink.py" in browser, len(browser)
    assert "tests/test_hygiene_linux_shards.py" not in browser, "the marker in a string does not count"
    assert desk_misses(cmap, browser) == []


def test_the_desk_checks_fail_when_a_closure_module_or_a_browser_test_leaves_desk():
    cmap, tracked = _map(), _tracked()
    closure, browser = desk_closure(tracked), browser_test_files(tracked)
    narrowed = copy.deepcopy(cmap)
    narrowed["groups"]["desk"]["paths"].remove("agentdata/pbi/client.py")
    assert desk_misses(narrowed, closure) == ["agentdata/pbi/client.py"]
    narrowed["groups"]["desk"]["paths"].remove("tests/test_fleet_*.py")
    assert "tests/test_fleet_ink.py" in desk_misses(narrowed, browser)


def test_a_new_import_into_the_closure_is_followed(tmp_path):
    """The walk reads lazy imports, relative imports and `from package import module`."""
    for rel, text in {
        "pkg/__init__.py": "",
        "pkg/a.py": "from . import b\nfrom .sub import c\n",
        "pkg/b.py": "def f():\n    import pkg.lazy\n",
        "pkg/lazy.py": "from pkg.sub.c import X\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/c.py": "X = 1\nfrom ..d import *\n",
        "pkg/d.py": "import os, json\n",
        "pkg/unused.py": "",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    assert import_closure(["pkg/a.py"], str(tmp_path)) == {"pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/lazy.py",
                                            "pkg/sub/__init__.py", "pkg/sub/c.py", "pkg/d.py"}


def test_ci_1s_fixture_diffs_still_hold_against_the_real_map_on_real_files():
    cmap, tracked = _map(), set(_tracked())
    for files, expected in FIXTURE_DIFFS:
        groups, missing = CP.groups_for(files, cmap)
        assert groups == (set(cmap["groups"]) if expected == ALL else expected), files
        real = [f for f in files if f not in missing]
        assert set(real) <= tracked, f"a fixture names a file that is gone: {sorted(set(real) - tracked)}"
    browser = browser_test_files(_tracked())
    assert "tests/test_fleet_ink.py" in browser, "the browser-test fixture is still a browser test"


def test_every_group_is_turned_on_by_some_tracked_file():
    cmap, tracked = _map(), _tracked()
    for group, spec in cmap["groups"].items():
        if spec.get("only"):
            assert any(CP.matches(spec["only"], p) for p in tracked), group
        else:
            assert any(CP.names(spec, p) for p in tracked), f"{group}: its paths match no tracked file"


def test_the_map_is_two_space_json_with_a_trailing_newline():
    with open(MAP, encoding="utf-8") as f:
        text = f.read()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
