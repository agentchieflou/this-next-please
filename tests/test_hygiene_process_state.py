"""The desk's process state has one owner in the suite, and a leaked server thread fails its test (#298, #227).

`agentdata/fleet` keeps state in module globals -- the desk's selection and handles, the refresh
floor, the fingerprint and branch caches -- which is right for one long-running `ad-fleet serve` and
wrong for a suite where every test has its own fleet directory. Thirty-five test modules used to reset
some of it by hand, in eight different ways, and none reset all of it. Serially a file runs
contiguously and hides the gaps; `--dist load` interleaves modules in one worker and exposed them,
which is why Windows ran serially (#227).

`tests/conftest.py` now resets every name in `FLEET_PROCESS_STATE` for every test. The first test
here keeps that table complete: a new mutable module global in `agentdata/fleet`, or a name rebound
through `global`, fails here until it is in the table or allow-listed below with its reason. The
second proves that a test which leaves a desk server thread running is reported, by name.
"""
from __future__ import annotations
import ast
import glob
import os
import sys

from agentdata import proc
from conftest import FLEET_PROCESS_STATE

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.join(os.path.dirname(HERE), "agentdata", "fleet")

#: Module-level mutable state that is deliberately *not* reset per test, each with its reason.
ALLOWED = {
    "agentdata.fleet.serve._GZIPPED": "keyed by everything the gzipped body was made from, so a "
                                      "test can only ever get back the bytes it would have made",
    "agentdata.fleet.serve._STRIPPED": "keyed by the file's path, mtime and size, so a test can only "
                                       "ever get back the bytes it would have stripped (#523)",
    "agentdata.fleet.serve._desk_seq": "only compared through `_desk_written`, which is reset",
    "agentdata.fleet.serve._config_gen": "a counter a stream compares only for change against the "
                                         "value it read itself (#348); its value carries nothing",
    "agentdata.fleet.adopt._cache": "reset per test by `_no_process_listing_in_tests`",
    "agentdata.fleet.adopt._listing": "reset per test by `_no_process_listing_in_tests`",
}

#: Constructors whose result is a mutable container, when called with this dotted name.
MUTABLE_CALLS = {"dict", "list", "set", "bytearray", "itertools.count", "collections.defaultdict",
                 "collections.OrderedDict", "collections.deque", "collections.Counter"}
LOCKS = {"threading.Lock", "threading.RLock", "threading.Condition", "threading.Event",
         "threading.Semaphore", "threading.BoundedSemaphore"}


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _mutable(value) -> bool:
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    return isinstance(value, ast.Call) and _dotted(value.func) in MUTABLE_CALLS


def _module_statements(tree):
    """Every statement at module level, including those under a module-level `if` or `try`."""
    todo = list(tree.body)
    while todo:
        node = todo.pop(0)
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            for field in ("body", "orelse", "finalbody"):
                todo.extend(getattr(node, field, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                todo.extend(handler.body)


def process_globals(source: str) -> dict[str, str]:
    """`{name: why}` for each piece of process state `source` keeps: a module-level name bound to a
    mutable value, or any name a function rebinds through `global`. An UPPER_CASE name (or
    `__all__`) that is never rebound is a frozen table, not state, and is left out."""
    tree = ast.parse(source)
    rebound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            rebound.update(node.names)
    found: dict[str, str] = {}
    for node in _module_statements(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not _mutable(value):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                name = target.id
                if (name.isupper() or name == "__all__") and name not in rebound:
                    continue
                found[name] = f"line {node.lineno}: a mutable value at module level"
    for name in sorted(rebound):
        found.setdefault(name, "rebound through `global` in a function")
    return found


def unowned(modules: dict[str, str]) -> list[str]:
    """Each `module.name` in the sources `modules` maps to that no one resets and no one excused."""
    missing = []
    for module, source in sorted(modules.items()):
        owned = set(FLEET_PROCESS_STATE.get(module, ()))
        for name, why in sorted(process_globals(source).items()):
            if name not in owned and f"{module}.{name}" not in ALLOWED:
                missing.append(f"{module}.{name} ({why})")
    return missing


def _fleet_sources() -> dict[str, str]:
    out = {}
    for path in sorted(glob.glob(os.path.join(FLEET, "*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        module = "agentdata.fleet" if name == "__init__" else f"agentdata.fleet.{name}"
        with open(path, encoding="utf-8") as f:
            out[module] = f.read()
    return out


def test_every_fleet_global_is_reset_for_every_test():
    missing = unowned(_fleet_sources())
    assert not missing, (
        "process state in agentdata/fleet that no test resets. Add each to FLEET_PROCESS_STATE in "
        "tests/conftest.py, or to ALLOWED here with the reason it may carry over:\n  "
        + "\n  ".join(missing))


def test_the_table_names_only_globals_that_exist():
    """A name the table resets but the module no longer has would be set on it, silently."""
    import importlib

    for module, names in FLEET_PROCESS_STATE.items():
        mod = importlib.import_module(module)
        for name in names:
            assert hasattr(mod, name), f"{module}.{name} is in FLEET_PROCESS_STATE but not in {module}"


SYNTHETIC = '''\
import itertools
import threading

TABLE = {"a": 1}                 # frozen: upper case, never rebound
__all__ = ["x"]
LOADED = None
_lock = threading.Lock()
_count = 0
_known = {"serve": 1}
_seen: list[str] = []
_ids = itertools.count(1)
_made = dict(a=1)

if True:
    _nested = set()


def load():
    global LOADED, _count
    LOADED = {}
    _count += 1
'''


def test_the_scan_finds_every_kind_of_process_state_in_a_synthetic_module():
    found = process_globals(SYNTHETIC)
    assert set(found) == {"LOADED", "_count", "_known", "_seen", "_ids", "_made", "_nested"}
    assert "global" in found["LOADED"] and "global" in found["_count"]
    assert unowned({"agentdata.fleet.synthetic": SYNTHETIC}) == [
        f"agentdata.fleet.synthetic.{name} ({found[name]})" for name in sorted(found)]


def test_a_new_global_in_a_real_fleet_module_fails_the_scan():
    """The real serve.py passes; the same file with one new mutable global does not, by name."""
    sources = _fleet_sources()
    assert unowned(sources) == []
    sources["agentdata.fleet.serve"] += "\n_new_cache: dict = {}\n"
    missing = unowned(sources)
    assert len(missing) == 1 and missing[0].startswith("agentdata.fleet.serve._new_cache ("), missing


# --------------------------------------------------------------------------------- the thread guard

CONFTEST = f"""\
import importlib.util
import sys

sys.path.insert(0, {HERE!r})
_spec = importlib.util.spec_from_file_location("repo_conftest", {os.path.join(HERE, "conftest.py")!r})
_repo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_repo)
_a_test_leaves_no_server_thread_running = _repo._a_test_leaves_no_server_thread_running
"""

TEST = """\
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve_and_forget():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={{"poll_interval": 0.05}}, daemon=True)
    thread.start()
    return server


def test_leaves_a_server():
    server = serve_and_forget()
    if {clean}:
        server.shutdown()
        server.server_close()
"""


def _inner(tmp_path, *, clean: bool):
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(TEST.format(clean=clean), encoding="utf-8")
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_inner.py"]
    code, out, err, _ = proc.run(argv, cwd=str(tmp_path), timeout=180)
    return code, out + err


def test_a_test_that_leaves_a_serve_forever_thread_fails_naming_it(tmp_path):
    code, out = _inner(tmp_path, clean=False)
    assert code != 0, out
    assert "test_leaves_a_server" in out and "left a desk server thread running" in out, out
    assert "(serve_forever)" in out, out
    assert "serve_forever" in out.split("left a desk server thread running", 1)[1], out


def test_a_test_that_shuts_its_server_down_passes(tmp_path):
    code, out = _inner(tmp_path, clean=True)
    assert code == 0, out
