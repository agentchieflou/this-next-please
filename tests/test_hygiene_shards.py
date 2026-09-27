"""`--shard=K/N` (tests/shard.py, #310): whole files, balanced by tests/durations.json, adding up.

The packing and the weighting are pure functions, tested here on synthetic tables and on the real
one. The plugin itself runs in a throwaway project (serially and under `-n 2`). That the shards of
the real suite add up to exactly the selection, with and without `-m` and under `--shuffle-seed`, costs
seven collections of the whole suite, so it is folded into the existing `scale` test in
tests/test_suite_hygiene.py (decision 13: the slow-tier count does not grow).
"""
from __future__ import annotations
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys

import pytest

import shard

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(REPO_ROOT, "tests")
INNER = {"browser", "slow", "measured", "scale"}  # the tiers the inner loop's `-m` leaves out


def _real_files() -> list[str]:
    """Every test module pytest would collect, as `tests/...` keys, without importing any of them."""
    found = glob.glob(os.path.join(TESTS, "**", "test_*.py"), recursive=True)
    rel = (os.path.relpath(p, REPO_ROOT).replace(os.sep, "/") for p in found)
    return sorted(r for r in rel if "/fixtures/" not in r)


def _check_partition(shards: list[list[str]], files) -> None:
    flat = [f for s in shards for f in s]
    assert len(flat) == len(set(flat)), "a file is in two shards"
    assert set(flat) == set(files), "the shards do not add up to the whole"


# ------------------------------------------------------------------------------------------ assign


@pytest.mark.parametrize("n", [2, 3, 4])
def test_the_real_files_split_into_disjoint_shards_that_add_up(n):
    files = _real_files()
    assert len(files) > 200, len(files)
    seconds = shard.weights({f: {"default"} for f in files}, shard.load_table(), "linux")
    shards = shard.assign(seconds, n)
    assert len(shards) == n and all(shards)
    _check_partition(shards, files)


def test_assign_balances_longest_first_and_is_deterministic():
    table = {"a": 10.0, "b": 7.0, "c": 5.0, "d": 4.0, "e": 3.0, "f": 1.0}
    shards = shard.assign(table, 2)
    assert shards == [["a", "d", "f"], ["b", "c", "e"]]  # 15 and 15
    assert shard.assign(dict(reversed(list(table.items()))), 2) == shards, "input order does not matter"
    assert shard.assign({"b": 1.0, "a": 1.0, "c": 1.0}, 2) == [["a", "c"], ["b"]], "ties go by path"
    assert shard.assign({"a": 1.0}, 3) == [["a"], [], []]
    assert shard.assign({}, 2) == [[], []]


def test_zero_weight_files_still_spread_by_count():
    shards = shard.assign({f"t{i}.py": 0.0 for i in range(6)}, 3)
    assert [len(s) for s in shards] == [2, 2, 2]


# ----------------------------------------------------------------------------------------- weights


TABLE = {
    "linux": {"tests/a.py": {"default": 2.0, "browser": 30.0}, "tests/b.py": {"default": 4.0},
              "tests/c.py": {"default": 6.0}},
    "windows": {"tests/a.py": {"default": 3.0, "browser": 50.0}, "tests/d.py": {"default": 9.0}},
}


def test_a_file_weighs_only_its_selected_tiers():
    assert shard.weights({"tests/a.py": {"default"}}, TABLE, "linux") == {"tests/a.py": 2.0}
    assert shard.weights({"tests/a.py": {"browser"}}, TABLE, "linux") == {"tests/a.py": 30.0}
    assert shard.weights({"tests/a.py": {"default", "browser"}}, TABLE, "linux") == {"tests/a.py": 32.0}
    assert shard.weights({"tests/a.py": {"default", "browser"}}, TABLE, "windows") == {"tests/a.py": 53.0}


def test_the_other_os_then_the_median_fill_the_gaps():
    got = shard.weights({"tests/b.py": {"default"}, "tests/c.py": {"default"}, "tests/d.py": {"default"},
                         "tests/new.py": {"default"}, "tests/a.py": {"slow"}}, TABLE, "linux")
    assert got["tests/d.py"] == 9.0, "linux does not know d.py; windows does"
    assert got["tests/new.py"] == got["tests/a.py"] == 6.0, "the median of 4, 6 and 9"


def test_an_empty_or_missing_table_splits_by_count(tmp_path):
    assert shard.load_table(str(tmp_path / "absent.json")) == {}
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert shard.load_table(str(tmp_path / "bad.json")) == {}
    files = {f"tests/t{i}.py": {"default"} for i in range(7)}
    seconds = shard.weights(files, {}, "linux")
    assert set(seconds.values()) == {1.0}
    shards = shard.assign(seconds, 3)
    _check_partition(shards, files)
    assert sorted(len(s) for s in shards) == [2, 2, 3]


def test_the_tiers_are_the_ones_durations_py_writes():
    spec = importlib.util.spec_from_file_location(
        "durations_script", os.path.join(REPO_ROOT, ".github", "scripts", "durations.py"))
    durations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(durations)
    assert shard.TIERS == durations.TIERS
    for markers in ("", "browser", "measured,browser", "parametrize,slow", "scale,measured,usefixtures"):
        assert shard.tier_of(markers.split(",")) == durations.tier_of(markers), markers
    assert shard.os_key("nt") == "windows" and shard.os_key("posix") == "linux"


def test_the_shard_option_takes_k_of_n():
    assert shard.parse_shard("1/1") == (1, 1) and shard.parse_shard("3/4") == (3, 4)
    for bad in ("0/3", "4/3", "1/0", "3", "a/b", "1/2/3", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            shard.parse_shard(bad)


# --------------------------------------------------------------------- balance on tests/durations.json


def _balance(os_name: str, tiers_of_entry, n: int) -> list[float]:
    table = json.load(open(os.path.join(TESTS, "durations.json"), encoding="utf-8"))
    selected = {f: tiers_of_entry(e) for f, e in table[os_name].items() if f.startswith("tests/")}
    selected = {f: t for f, t in selected.items() if t}
    seconds = shard.weights(selected, table, os_name)
    shards = shard.assign(seconds, n)
    _check_partition(shards, selected)
    return [sum(seconds[f] for f in s) for s in shards]


def test_the_browser_files_split_in_three_within_ten_percent_of_the_mean():
    loads = _balance("linux", lambda e: {t for t in e if "browser" in t.split("+")}, 3)
    assert max(loads) <= 1.10 * sum(loads) / 3, loads


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_the_inner_selection_splits_in_two_within_ten_percent(os_name):
    """The estimate `--shard=K/2` prints for `-m "not browser and not slow and not measured and not scale"`."""
    loads = _balance(os_name, lambda e: {t for t in e if not set(t.split("+")) & INNER}, 2)
    assert max(loads) <= 1.10 * min(loads), loads


# ----------------------------------------------------------------------------- the plugin, in a project


def _project(tmp_path):
    for i, count in enumerate([3, 1, 2, 2, 1]):
        body = "".join(f"def test_{j}():\n    pass\n" for j in range(count))
        (tmp_path / f"test_m{i}.py").write_text(body, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p shard -p no:cacheprovider\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([TESTS, os.environ.get("PYTHONPATH", "")]))
    return env


def _run(tmp_path, env, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)


def _passed(out: str) -> set[str]:
    return {ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("PASSED ")}


def test_the_plugin_keeps_whole_files_serially_and_under_xdist(tmp_path):
    env = _project(tmp_path)
    whole = _run(tmp_path, env)
    everything = _passed(whole.stdout)
    assert len(everything) == 9, whole.stdout + whole.stderr

    serial = []
    for k in (1, 2):
        p = _run(tmp_path, env, f"--shard={k}/2")
        assert p.returncode == 0, p.stdout + p.stderr
        assert f"shard {k}/2: " in p.stdout and " s estimated" in p.stdout, p.stdout
        serial.append(_passed(p.stdout))
    assert serial[0] and serial[1] and not serial[0] & serial[1]
    assert serial[0] | serial[1] == everything
    # a file is never split: its tests all went one way
    for f in {t.split("::")[0] for t in everything}:
        assert sum(any(t.startswith(f + "::") for t in s) for s in serial) == 1, f

    xdist = _run(tmp_path, env, "-n", "2", "--shard=1/2")
    assert xdist.returncode == 0, xdist.stdout + xdist.stderr
    assert _passed(xdist.stdout) == serial[0], "each worker keeps the same shard"

    bad = _run(tmp_path, env, "--shard=3/2")
    assert bad.returncode == 4 and "1 <= K <= N" in bad.stderr, bad.stderr
