"""`ad-test bench` and the snapshot/compare halves of `ad-test run`.

"Make it faster" is only true if it is measured, and "nothing broke" is only true if before and after
are compared mechanically -- AGENTS.md rule 6 already forbids comparing datasets in the model's head
and points at `ad-diff`. So both comparisons here go through `AgentTable.read_tsv`, the reader
`ad-diff` uses, and both artefacts are written with `AgentTable.write_tsv`.

On the file format: the artefacts land as TSV rather than TOON because TOON is an encode-only wire
format for stdout (`agentdata/toon.py` has no decoder) and `--compare` has to read its inputs back.
Stdout still gets TOON through `policy.render`, which is the contract that actually matters.
"""
from __future__ import annotations
import os
import time
from datetime import datetime
from typing import Any

from .runner import parse_junit_cases, resolve_selectors, run_tests
from .. import proc
from ..model import OUT_DIR, AgentTable

BENCH_COLUMNS = ["node", "label", "runs", "median_ms", "min_ms", "p90_ms", "node_cum_ms", "tests", "runner"]
SNAPSHOT_COLUMNS = ["test", "outcome", "time_ms"]

# A change smaller than this is noise, not a result. Two runs of the same code differ by more than a
# few percent on any laptop, so the floor is the larger of 5% and twice the spread the "before" run
# itself showed -- a benchmark that was unstable to begin with has to clear a higher bar.
NOISE_FLOOR_PCT = 5.0


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def _out_path(root: str, name: str) -> str:
    d = os.path.join(root, OUT_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _as_ms(value: Any) -> float | None:
    """A bench cell as milliseconds, or None for the `n/a` a non-Python runner writes."""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    return ms if ms > 0 else None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


# --------------------------------------------------------------------------------- linked tests


def linked_tests(root: str, node_id: str) -> tuple[list[str], str]:
    """(test ids, "coverage" | "name" | "none") for a node.

    Coverage-derived edges are the real thing; name-derived ones are `ad-graph build`'s
    `test_foo` <-> `foo` guess, which the caller warns about rather than trusting silently.
    """
    try:
        from ..graph import query
        graph, _meta = query.load_graph(root)
        node = query.find_node(graph, node_id)
    except Exception:
        return [], "none"

    from_coverage = sorted({
        e.source for e in graph.edges
        if e.kind == "tests" and e.target == node.id and e.source_type == "coverage"
    })
    if from_coverage:
        return from_coverage, "coverage"

    cov_tests = ((graph.coverage or {}).get("nodes") or {}).get(node.id, {}).get("tests") or []
    if cov_tests:
        return sorted(cov_tests), "coverage"

    by_name = sorted({e.source for e in graph.edges if e.kind == "tests" and e.target == node.id})
    by_name = sorted(set(by_name) | set(node.tests or []))
    return (by_name, "name") if by_name else ([], "none")


# ------------------------------------------------------------------------------------ profiling


def _profile_node_ms(root: str, selectors: list[str], node_path: str, node_name: str, timeout: int) -> float | None:
    """Cumulative time inside the node itself, so the number is its cost and not the suite's."""
    prof = _out_path(root, f"bench-{_stamp()}.prof")
    argv = ["python", "-m", "cProfile", "-o", prof, "-m", "pytest", "-q", "-p", "no:cacheprovider", *selectors]
    try:
        proc.run(argv, cwd=root, timeout=timeout)
    except Exception:
        return None

    if not os.path.isfile(prof):
        return None
    try:
        import pstats
        stats = pstats.Stats(prof).stats  # type: ignore[attr-defined]
    except Exception:
        return None
    finally:
        try:
            os.remove(prof)
        except OSError:
            pass

    leaf = node_name.rsplit(".", 1)[-1]
    want_file = node_path.replace("\\", "/")
    total = 0.0
    for (fname, _lineno, func), values in stats.items():
        if func != leaf:
            continue
        if not str(fname).replace("\\", "/").endswith(want_file):
            continue
        total += float(values[3])  # cumulative seconds
    return round(total * 1000.0, 3) if total else None


# ---------------------------------------------------------------------------------------- bench


def bench_node(
    root: str = ".",
    *,
    node: str,
    runs: int = 5,
    warmup: int = 1,
    label: str = "bench",
    timeout: int = 600,
    runner_name: str | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(root)
    tests, source = linked_tests(root, node)
    if not tests:
        return {
            "ok": False,
            "error": f"no tests are linked to {node}",
            "hint": f"run test-cover for {node}",
        }

    selectors = resolve_selectors(root, [node]) or tests
    warnings = []
    if source == "name":
        warnings.append("tests linked by name, not coverage: run `ad-test coverage --contexts` for real edges")

    for _ in range(max(0, warmup)):
        run_tests(root=root, runner_name=runner_name, timeout=timeout, selectors=selectors)

    wall: list[float] = []
    runner = runner_name or ""
    for _ in range(max(1, runs)):
        t0 = time.perf_counter()
        res = run_tests(root=root, runner_name=runner_name, timeout=timeout, selectors=selectors)
        wall.append((time.perf_counter() - t0) * 1000.0)
        runner = res.get("runner") or runner
        if not res.get("ok"):
            return {
                "ok": False,
                "error": f"the tests for {node} do not pass, so timing them means nothing",
                "hint": "fix the failing tests before benchmarking",
            }

    node_cum: float | None = None
    if runner == "pytest":
        try:
            from ..graph import query
            graph, _meta = query.load_graph(root)
            n = query.find_node(graph, node)
            node_cum = _profile_node_ms(root, selectors, n.path, n.name, timeout)
        except Exception:
            node_cum = None

    row = {
        "node": node,
        "label": label,
        "runs": len(wall),
        "median_ms": round(_median(wall), 3),
        "min_ms": round(min(wall), 3),
        "p90_ms": round(_percentile(wall, 90), 3),
        "node_cum_ms": node_cum if node_cum is not None else "n/a",
        "tests": len(tests),
        "runner": runner or "unknown",
    }
    table = AgentTable.from_records([row], name=f"bench_{label}", source="ad-test bench", fields=BENCH_COLUMNS)
    path = _out_path(root, f"bench-{label}-{_stamp()}.tsv")
    _write_tsv(table, path)

    return {
        "ok": True,
        "source": "ad-test bench",
        "row": row,
        "path": os.path.relpath(path, root).replace("\\", "/"),
        "test_source": source,
        "warnings": warnings,
        "profiled": node_cum is not None,
    }


def _write_tsv(table: AgentTable, path: str) -> str:
    lines = ["\t".join(table.columns)]
    for r in table.rows:
        lines.append("\t".join("" if v is None else str(v) for v in r))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


# -------------------------------------------------------------------------------- bench compare


def compare_bench(before_path: str, after_path: str, min_speedup: float = 1.10) -> dict[str, Any]:
    before = AgentTable.read_tsv(before_path, "before")
    after = AgentTable.read_tsv(after_path, "after")
    if not before.rows or not after.rows:
        return {"ok": False, "error": "a bench file has no rows", "hint": "re-run `ad-test bench --node <id>`"}

    b = dict(zip(before.columns, before.rows[0]))
    a = dict(zip(after.columns, after.rows[0]))

    # Prefer the node's own cumulative cost over suite wall time. Wall time is dominated by runner
    # startup -- on the bench fixture a genuine 5x speedup inside the node moves the suite by 2%,
    # which would be reported as "same" and would fail every optimisation that ever worked.
    b_cum, a_cum = _as_ms(b.get("node_cum_ms")), _as_ms(a.get("node_cum_ms"))
    if b_cum and a_cum:
        basis, b_med, a_med = "node_cum_ms", b_cum, a_cum
    else:
        basis, b_med, a_med = "median_ms", float(b["median_ms"]), float(a["median_ms"])
    b_min = float(b["min_ms"])

    # the floor is the larger of 5% and twice the spread the before run's wall time showed: a
    # benchmark that was unstable to begin with has to clear a higher bar
    b_wall = float(b["median_ms"])
    spread_pct = ((b_wall - b_min) / b_wall * 100.0) if b_wall else 0.0
    floor_pct = max(NOISE_FLOOR_PCT, 2.0 * spread_pct)
    change_pct = ((b_med - a_med) / b_med * 100.0) if b_med else 0.0

    if abs(change_pct) < floor_pct:
        verdict = "same"
    elif change_pct > 0:
        verdict = "faster"
    else:
        verdict = "slower"

    speedup = round(b_med / a_med, 3) if a_med else 0.0
    row = {
        "node": a.get("node", b.get("node", "")),
        "basis": basis,
        "before_ms": b_med,
        "after_ms": a_med,
        "delta_ms": round(a_med - b_med, 3),
        "speedup": speedup,
        "change_pct": round(change_pct, 2),
        "noise_floor_pct": round(floor_pct, 2),
        "verdict": verdict,
        "meets_min_speedup": bool(verdict == "faster" and speedup >= min_speedup),
    }
    return {"ok": True, "source": "ad-test bench --compare", "row": row, "min_speedup": min_speedup}


# ----------------------------------------------------------------------------- run snapshot/diff


def snapshot_run(root: str = ".", *, label: str, timeout: int = 600, runner_name: str | None = None,
                 selectors: list[str] | None = None) -> dict[str, Any]:
    root = os.path.abspath(root)
    junit = _out_path(root, f"tests-{label}-{_stamp()}.xml")
    res = run_tests(root=root, runner_name=runner_name, timeout=timeout,
                    selectors=selectors or [], junit_out=junit)

    cases: list[dict[str, Any]] = []
    if os.path.isfile(junit):
        try:
            cases = parse_junit_cases(junit)
        except Exception:
            cases = []
    if not cases:
        return {
            "ok": False,
            "error": "the runner produced no per-test results to snapshot",
            "hint": "this runner emits no JUnit XML; `--compare` needs it",
        }

    table = AgentTable.from_records(cases, name=f"tests_{label}", source="ad-test run --snapshot",
                                    fields=SNAPSHOT_COLUMNS)
    path = _out_path(root, f"tests-{label}-{_stamp()}.tsv")
    _write_tsv(table, path)
    return {
        "ok": bool(res.get("ok")),
        "source": "ad-test run --snapshot",
        "path": os.path.relpath(path, root).replace("\\", "/"),
        "cases": len(cases),
        "passed": sum(1 for c in cases if c["outcome"] == "passed"),
        "label": label,
    }


REGRESSION_FROM = "passed"


def compare_runs(before_path: str, after_path: str) -> dict[str, Any]:
    """Any test that stopped passing, or vanished, is a regression. New passing tests are `added`."""
    before = AgentTable.read_tsv(before_path, "before")
    after = AgentTable.read_tsv(after_path, "after")
    b = {str(dict(zip(before.columns, r))["test"]): dict(zip(before.columns, r)) for r in before.rows}
    a = {str(dict(zip(after.columns, r))["test"]): dict(zip(after.columns, r)) for r in after.rows}

    rows: list[dict[str, Any]] = []
    for test in sorted(set(b) | set(a)):
        was = str(b[test]["outcome"]) if test in b else "absent"
        now = str(a[test]["outcome"]) if test in a else "absent"
        if was == now:
            status = "same"
        elif was == "absent":
            status = "added"
        elif was == REGRESSION_FROM:
            # passed -> anything else, vanishing included
            status = "regression"
        elif now == "absent":
            status = "removed"
        else:
            status = "changed"
        if status != "same":
            rows.append({"test": test, "before": was, "after": now, "status": status})

    regressions = [r for r in rows if r["status"] == "regression"]
    return {
        "ok": not regressions,
        "source": "ad-test run --compare",
        "rows": rows,
        "regressions": len(regressions),
        "added": sum(1 for r in rows if r["status"] == "added"),
        "before_total": len(b),
        "after_total": len(a),
    }
