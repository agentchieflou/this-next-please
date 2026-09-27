r"""The suite's hygiene counts, and the baseline they ratchet against (#306).

`tests/test_hygiene_ratchet.py` holds the tree to `tests/hygiene_baseline.json` with what this
module counts. Every file under `tests/` is read once and parsed with `ast`; no test module is
imported. What is counted:

* **flat waits** -- a call to an attribute named `wait_for_timeout`; a `time.sleep` in a browser
  file (one that imports playwright, `desk_harness` or `desk_waits`, or takes a desk fixture) that
  is not inside a `while` loop that fails at its deadline; a string constant (outside
  `tests/desk_waits.py`) holding a promise that resolves on a fixed `setTimeout`. There are none,
  and there may be none.
* **fall-through loops** -- a `while` loop around a `time.sleep` in a browser file with no
  `assert` or `raise` in it, in its `else`, or as the statement right after it: it runs out its
  deadline and carries on as if it had seen what it waited for. Counted per file; the count only
  goes down.
* **skips** -- `pytest.skip(`, `pytest.mark.skip`, `pytest.mark.skipif` and `pytest.importorskip(`,
  per file; the count only goes down. A `skipif` whose condition is only an `os.name` or
  `sys.platform` comparison, on a function marked `windows` or `posix`, is the platform's label and
  is not counted.
* **xfail** -- `pytest.xfail(` or `pytest.mark.xfail`. There are none, and there may be none.
* **tests** -- `def test_*`, per file; the count only goes up.

`--update` writes the tree's counts back (the first baseline, when there is none, is the tree as it
stands): skips and loops may fall, tests may rise. A count that
would move the other way is not written: the file is printed and the exit status is 2. That change
is a hand edit of the baseline, with the reason in the commit message, as with coverage floors.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "tests")
BASELINE = os.path.join(TESTS, "hygiene_baseline.json")

#: Built by concatenation, so this file never holds the thing it looks for.
WAIT_ATTR = "wait_for" + "_timeout"
#: A promise that resolves on a fixed timer: `new Promise(go => setTimeout(go, 700))`. A delayed
#: stub -- `setTimeout(() => go(...), 1500)` -- hands the timer a function, not the resolver, and
#: does not match.
FLAT_JS = re.compile(r"new Promise\([^;]*?set" + r"Timeout\(\s*\w+\s*,\s*\d")
#: The one file allowed page-side timers of its own: the waits themselves.
JS_EXEMPT = {"tests/desk_waits.py"}
BROWSER_MODULES = ("playwright", "desk_harness", "desk_waits")
DESK_FIXTURES = {"desk_browser", "new_desk_page", "desk_chromium_with"}
PLATFORM_MARKS = {"windows", "posix"}
SKIPS = {("pytest", "skip"), ("pytest", "importorskip"), ("pytest", "mark", "skip"),
         ("pytest", "mark", "skipif")}
XFAILS = {("pytest", "xfail"), ("pytest", "mark", "xfail")}
FIX_WAIT = ("wait on a condition instead: `page.wait_for_function(...)` for what the page will "
            "show, `desk_waits.settle(page)` for a still desk, `desk_waits.observe_quiet(page)` for "
            "\"nothing happens\"")
FIX_LOOP = "fail at the deadline: an `assert` or `raise` in the loop, its `else`, or right after it"
FIX_SKIP = ("a platform-only test keeps its `windows`/`posix` marker and its `skipif`; raising "
            "the skip baseline for it is a hand edit with the reason")


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def test_files(root: str = TESTS) -> list[str]:
    out = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__",) and not d.startswith("."))
        out += [os.path.join(here, f) for f in sorted(files) if f.endswith(".py")]
    return out


def _chain(node) -> tuple:
    """`pytest.mark.skipif` as `("pytest", "mark", "skipif")`; () for anything else."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return tuple([node.id] + parts[::-1])
    return ()


def _is_platform(cond) -> bool:
    """Only an `os.name`/`sys.platform` comparison: `os.name == "nt"`, `sys.platform != "win32"`,
    `sys.platform.startswith("win")`, or `not` one of those."""
    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        return _is_platform(cond.operand)
    if isinstance(cond, ast.Compare):
        return (_chain(cond.left) in {("os", "name"), ("sys", "platform")}
                and all(isinstance(c, ast.Constant) for c in cond.comparators))
    if isinstance(cond, ast.Call) and not cond.keywords:
        return (_chain(cond.func) in {("sys", "platform", "startswith"), ("os", "name", "startswith")}
                and all(isinstance(a, ast.Constant) for a in cond.args))
    return False


def _fails(stmts) -> bool:
    """An `assert` or `raise` among `stmts`, however deep, but not inside a function of its own."""
    todo = list(stmts)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        todo.extend(ast.iter_child_nodes(node))
    return False


class _Scan(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.AST):
        self.path = path
        self.flat: list[tuple[int, str]] = []
        self.loops: list[int] = []
        self.skips: list[int] = []
        self.xfails: list[int] = []
        self.tests = 0
        self.sleeps: set[str] = set()         # names that are `time.sleep`
        self.times: set[str] = set()          # names bound to the `time` module
        self.browser = False
        self._whiles: list[tuple[ast.While, bool]] = []
        self._exempt: set[int] = set()        # platform skipif nodes, by id
        self._look(tree)

    # What the file is, before its calls are looked at.
    def _look(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "time":
                        self.times.add(a.asname or "time")
                    if a.name.split(".")[0] in BROWSER_MODULES:
                        self.browser = True
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod in BROWSER_MODULES:
                    self.browser = True
                if node.module == "time":
                    for a in node.names:
                        if a.name == "sleep":
                            self.sleeps.add(a.asname or "sleep")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                if any(a.arg in DESK_FIXTURES for a in args):
                    self.browser = True
                if node.name.startswith("test_"):
                    self.tests += 1
                marks = {_chain(d)[-1] for d in node.decorator_list
                         if _chain(d)[:2] == ("pytest", "mark") and len(_chain(d)) == 3}
                if marks & PLATFORM_MARKS:
                    for d in node.decorator_list:
                        if (isinstance(d, ast.Call) and _chain(d.func) == ("pytest", "mark", "skipif")
                                and len(d.args) == 1 and _is_platform(d.args[0])):
                            self._exempt.add(id(d.func))

    def _is_sleep(self, func) -> bool:
        if isinstance(func, ast.Attribute) and func.attr == "sleep":
            return isinstance(func.value, ast.Name) and func.value.id in self.times
        return isinstance(func, ast.Name) and func.id in self.sleeps

    def _visit_body(self, stmts):
        """The statement right after a `while` counts as the loop's own failure."""
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, ast.While):
                after = stmts[i + 1:i + 2]
                fails = (_fails(stmt.body + stmt.orelse)
                         or bool(after and isinstance(after[0], (ast.Assert, ast.Raise))))
                self._whiles.append((stmt, fails))
                for child in stmt.body + stmt.orelse:
                    self.visit(child)
                self._whiles.pop()
                self.visit(stmt.test)
            else:
                self.visit(stmt)

    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                self._visit_body(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def _in_new_scope(self, node):
        saved, self._whiles = self._whiles, []
        self.generic_visit(node)
        self._whiles = saved

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _in_new_scope

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == WAIT_ATTR:
            self.flat.append((node.lineno, "a fixed wait (`." + WAIT_ATTR + "(...)`)"))
        elif self.browser and self._is_sleep(func):
            if not self._whiles:
                self.flat.append((node.lineno, "a fixed `time.sleep` in a browser test"))
            else:
                loop, fails = self._whiles[-1]
                if not fails and loop.lineno not in self.loops:
                    self.loops.append(loop.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        chain = _chain(node)
        if chain in SKIPS and id(node) not in self._exempt:
            self.skips.append(node.lineno)
        elif chain in XFAILS:
            self.xfails.append(node.lineno)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str) and self.path not in JS_EXEMPT:
            for m in FLAT_JS.finditer(node.value):
                line = node.lineno + node.value.count("\n", 0, m.start())
                self.flat.append((line, "a fixed wait in page code (`" + m.group(0) + "...`)"))


def scan_source(source: str, path: str = "tests/example.py") -> dict:
    """The counts for one file's source: `flat` and `xfail` as `[(line, what)]`, `loops` and
    `skips` as lines, `tests` as a number, and whether it is a browser file."""
    tree = ast.parse(source, filename=path)
    s = _Scan(path, tree)
    s.visit(tree)
    return {"flat": sorted(s.flat), "loops": sorted(s.loops), "skips": sorted(s.skips),
            "xfail": sorted(s.xfails), "tests": s.tests, "browser": s.browser}


def scan_tree(root: str = TESTS) -> dict[str, dict]:
    """Every file under `root`, keyed as `tests/...` (relative to `root`'s parent)."""
    out = {}
    top = os.path.dirname(os.path.abspath(root))
    for path in test_files(root):
        key = os.path.relpath(path, top).replace(os.sep, "/")
        with open(path, encoding="utf-8") as f:
            out[key] = scan_source(f.read(), key)
    return out


def counts(scanned: dict[str, dict]) -> dict[str, dict[str, int]]:
    """The baseline's shape: per file, only the counts that are not zero."""
    out = {}
    for path, s in sorted(scanned.items()):
        row = {"skips": len(s["skips"]), "loops": len(s["loops"]), "tests": s["tests"]}
        row = {k: v for k, v in row.items() if v}
        if row:
            out[path] = row
    return out


def load(path: str = BASELINE) -> dict[str, dict[str, int]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["files"]


def write(files: dict, path: str = BASELINE) -> None:
    about = ("The suite's hygiene counts (#306): per file, skips and fall-through loops (which may "
             "only go down) and `def test_*` (which may only go up). tests/test_hygiene_ratchet.py "
             "holds the tree to them; `python .github/scripts/hygiene_baseline.py --update` lowers "
             "and raises them. Moving one the other way is a hand edit with the reason in the commit.")
    rows = [f"  {json.dumps(p)}: {json.dumps(files[p], sort_keys=True)}" for p in sorted(files)]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n \"about\": " + json.dumps(about) + ",\n \"files\": {\n" + ",\n".join(rows)
                + "\n }\n}\n")                   # one line a file: a count's move is a one-line diff


def wrong_way(base: dict, now: dict) -> list[str]:
    """Each file whose count would move the way the ratchet forbids, as a sentence."""
    out = []
    for path in sorted(set(base) | set(now)):
        b, n = base.get(path, {}), now.get(path, {})
        for key in ("skips", "loops"):
            if n.get(key, 0) > b.get(key, 0):
                out.append(f"{path}: {key} {b.get(key, 0)} -> {n.get(key, 0)}")
        if n.get("tests", 0) < b.get("tests", 0):
            out.append(f"{path}: tests {b.get('tests', 0)} -> {n.get('tests', 0)}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true",
                    help="lower skip and loop counts and raise test counts to the tree's")
    ap.add_argument("--baseline", default=BASELINE)
    ap.add_argument("--root", default=TESTS)
    a = ap.parse_args(argv)
    now = counts(scan_tree(a.root))
    if not os.path.isfile(a.baseline):
        if not a.update:
            print(f"no {a.baseline}; `--update` writes the first one from the tree", file=sys.stderr)
            return 2
        write(now, a.baseline)                # the first baseline is the tree as it stands
        print(f"{a.baseline}: written, {len(now)} file(s)")
        return 0
    base = load(a.baseline)
    bad = wrong_way(base, now)
    if bad:
        for line in bad:
            print(line)
        print("hint: that is a hand edit of tests/hygiene_baseline.json, with the reason in the "
              "commit message", file=sys.stderr)
        return 2
    if a.update:
        write(now, a.baseline)
        moved = sum(1 for p in set(base) | set(now) if base.get(p) != now.get(p))
        print(f"{rel(a.baseline) if a.baseline.startswith(ROOT) else a.baseline}: {moved} file(s) moved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
