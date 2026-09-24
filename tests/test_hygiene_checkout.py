"""Every `python -m agentdata...` a test spawns imports the checkout under test (#297).

A spawn with `cwd=tmp_path` imports `agentdata` only if it is installed or on `PYTHONPATH`, so on an
uninstalled checkout 73 tests failed with `No module named agentdata`, and with an older install in
site-packages they tested that copy instead. `tests/subproc.py` puts the checkout first on the child's
`PYTHONPATH`; this scan keeps every new spawn going through it.

The rule, decidable from the source: outside tests/subproc.py, a list or tuple literal that starts
`sys.executable, "-m", "agentdata..."` must sit in a function that also calls `agentdata_env(` or
`run_agentdata(`, unless its file is allow-listed below. A literal that is an operand of a comparison
(`assert cmd[:4] == [sys.executable, "-m", "agentdata", ...]`) describes a command and spawns
nothing, so it is not a spawn.
"""
from __future__ import annotations
import ast
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))

ALLOWED = {
    "fakes/runner.py": "runs as a standalone script via the fake shims; cannot import tests/subproc.py",
    "test_lifecycle.py": "spawns the agentdata of a real venv it installed, not the checkout",
    "laptop/": "runs against a real machine's installed agentdata",
    "subproc.py": "the helper itself",
}
HELPERS = ("agentdata_env", "run_agentdata")


def _is_agentdata_argv(node):
    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 3:
        return False
    first, flag, module = node.elts[:3]
    return (isinstance(first, ast.Attribute) and first.attr == "executable"
            and isinstance(first.value, ast.Name) and first.value.id == "sys"
            and isinstance(flag, ast.Constant) and flag.value == "-m"
            and isinstance(module, ast.Constant) and isinstance(module.value, str)
            and (module.value == "agentdata" or module.value.startswith("agentdata.")))


def _calls_a_helper(func):
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in HELPERS:
                return True
    return False


def unrouted_spawns(source, filename="<source>"):
    """`lineno`s of agentdata argv literals not routed through the helpers."""
    tree = ast.parse(source, filename)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found = []
    for node in ast.walk(tree):
        if not _is_agentdata_argv(node):
            continue
        if isinstance(parents.get(node), ast.Compare):
            continue
        func, up = None, parents.get(node)
        while up is not None:
            if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = up
                break
            up = parents.get(up)
        if func is None or not _calls_a_helper(func):
            found.append(node.lineno)
    return found


def _allowed(rel):
    return any(rel == key or (key.endswith("/") and rel.startswith(key)) for key in ALLOWED)


def test_every_agentdata_subprocess_imports_the_checkout():
    offenders = []
    for path in sorted(glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(path, HERE).replace(os.sep, "/")
        if _allowed(rel):
            continue
        with open(path, encoding="utf-8") as f:
            for line in unrouted_spawns(f.read(), path):
                offenders.append(f"tests/{rel}:{line}")
    assert not offenders, (
        "these spawn `python -m agentdata...` without putting the checkout on PYTHONPATH; pass "
        "`env=agentdata_env(...)` or use `run_agentdata` (tests/subproc.py):\n  " + "\n  ".join(offenders))


def test_the_scan_flags_a_bare_spawn_and_allows_a_routed_one():
    bare = (
        "import subprocess, sys\n"
        "def t(tmp_path):\n"
        "    subprocess.run([sys.executable, '-m', 'agentdata', 'doctor'], cwd=tmp_path)\n"
    )
    module = bare.replace("'agentdata'", "'agentdata.cli_state'")
    routed = (
        "import subprocess, sys\n"
        "from subproc import agentdata_env\n"
        "def t(tmp_path):\n"
        "    subprocess.run([sys.executable, '-m', 'agentdata', 'doctor'], cwd=tmp_path,\n"
        "                   env=agentdata_env())\n"
    )
    helper = (
        "import sys\n"
        "from subproc import run_agentdata\n"
        "def t(tmp_path):\n"
        "    return run_agentdata((sys.executable, '-m', 'agentdata.toon'), cwd=tmp_path)\n"
    )
    compared = (
        "import sys\n"
        "def t(cmd):\n"
        "    assert cmd[:4] == [sys.executable, '-m', 'agentdata', 'update']\n"
    )
    other = (
        "import subprocess, sys\n"
        "def t():\n"
        "    subprocess.run([sys.executable, '-m', 'pip', 'install'])\n"
    )
    assert unrouted_spawns(bare) == [3]
    assert unrouted_spawns(module) == [3]
    assert unrouted_spawns(routed) == []
    assert unrouted_spawns(helper) == []
    assert unrouted_spawns(compared) == []
    assert unrouted_spawns(other) == []


def test_the_allow_list_names_files_that_exist():
    for key in ALLOWED:
        assert os.path.exists(os.path.join(HERE, key.rstrip("/"))), f"allow-listed but gone: tests/{key}"
