"""`--shard=K/N`: run the K-th of N balanced shards of whole test files (#310).

A plugin of the suite's own, listed in `tests/conftest.py`'s `pytest_plugins`. Its collection hook is
`trylast`, so it runs after the conftest shuffle and after pytest's `-m`/`-k` deselection and sees only
the selected items. It groups them by file, packs whole files into N shards, longest first, by their
times in `tests/durations.json` (#309), and keeps the K-th shard's items in the order they came, so a
shuffled shard stays shuffled. The other items are deselected through `pytest_deselected`.

Whole files keep every module contiguous in one process, the property the serial Windows run relies
on. Every process that collects the same selection computes the same shards, so `--shard` also
works under `-n`: each xdist worker keeps the same items. Using it in CI is #311's and #312's.
"""
from __future__ import annotations
import argparse
import json
import os
import statistics
from collections.abc import Iterable

import pytest

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "durations.json")
# The tier markers, as `.github/scripts/durations.py` defines them (tests/test_hygiene_shards.py
# checks that the two agree).
TIERS = ("browser", "laptop", "measured", "scale", "slow")


def parse_shard(value: str) -> tuple[int, int]:
    """`"2/3"` -> `(2, 3)`: 1-based, and K within 1..N."""
    try:
        k, n = (int(part) for part in value.split("/"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--shard takes K/N, e.g. 2/3; got {value!r}") from None
    if n < 1 or not 1 <= k <= n:
        raise argparse.ArgumentTypeError(f"--shard K/N needs 1 <= K <= N; got {value!r}")
    return k, n


def tier_of(markers: Iterable[str]) -> str:
    """`browser+measured`, `slow`, ... or `default`: the tier markers a test carries, sorted."""
    return "+".join(sorted({m for m in markers if m in TIERS})) or "default"


def os_key(name: str = os.name) -> str:
    return "windows" if name == "nt" else "linux"


def load_table(path: str = TABLE) -> dict:
    """`{os: {file: {tier: seconds}}}`, or `{}` when the table is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            table = json.load(f)
    except (OSError, ValueError):
        return {}
    return table if isinstance(table, dict) else {}


def _known(entry, tiers: set[str]) -> float | None:
    """The seconds an OS's entry gives the tiers, or None when it knows none of them."""
    if not isinstance(entry, dict):
        return None
    present = [entry[t] for t in sorted(tiers) if t in entry]
    return float(sum(present)) if present else None


def weights(selected: dict[str, set[str]], table: dict, os_name: str) -> dict[str, float]:
    """Each file's estimated seconds, counting only the tiers of its selected tests.

    The current OS's entry first, then the other OS's; a file neither knows (or whose selected tiers
    neither knows) gets the median of the known files, and with nothing known every file weighs 1 so
    the shards split by count.
    """
    other = "linux" if os_name == "windows" else "windows"
    known: dict[str, float] = {}
    for file, tiers in selected.items():
        for key in (os_name, other):
            seconds = _known((table.get(key) or {}).get(file), tiers)
            if seconds is not None:
                known[file] = seconds
                break
    fallback = statistics.median(known.values()) if known else 1.0
    return {file: known.get(file, fallback) for file in selected}


def assign(files_seconds: dict[str, float], n: int) -> list[list[str]]:
    """Greedy, longest first, ties by path: each file goes to the lightest shard (then the one with
    fewer files, then the lowest index). Deterministic for a given table and file set; each shard's
    files are returned sorted."""
    shards: list[list[str]] = [[] for _ in range(n)]
    load = [0.0] * n
    for file, seconds in sorted(files_seconds.items(), key=lambda kv: (-kv[1], kv[0])):
        i = min(range(n), key=lambda j: (load[j], len(shards[j]), j))
        shards[i].append(file)
        load[i] += seconds
    return [sorted(s) for s in shards]


def file_of(item) -> str:
    return item.location[0].replace(os.sep, "/")


def pytest_addoption(parser):  # pragma: no cover - CLI plumbing
    parser.addoption("--shard", action="store", default=None, type=parse_shard, metavar="K/N",
                     help="run only the K-th of N shards of whole test files, balanced by tests/durations.json")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    shard = config.getoption("--shard")
    if shard is None:
        return
    k, n = shard
    selected: dict[str, set[str]] = {}
    for item in items:
        selected.setdefault(file_of(item), set()).add(tier_of(m.name for m in item.iter_markers()))
    seconds = weights(selected, load_table(), os_key())
    mine = set(assign(seconds, n)[k - 1])
    kept = [i for i in items if file_of(i) in mine]
    dropped = [i for i in items if file_of(i) not in mine]
    items[:] = kept
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    config.stash[_LINE] = (f"shard {k}/{n}: {len(mine)} files, {len(kept)} tests, "
                           f"~{sum(seconds[f] for f in mine):.0f} s estimated")


_LINE = pytest.StashKey[str]()


def pytest_report_collectionfinish(config):
    line = config.stash.get(_LINE, None)
    return [line] if line else []
