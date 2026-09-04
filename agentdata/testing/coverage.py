"""Coverage collection, parsing (coverage.py, lcov, cobertura), and graph node mapping."""
from __future__ import annotations
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

from .. import config as C
from .. import proc
from .. import textio
from ..graph.model import Graph
from ..graph.query import load_graph
from .detect import detect_runner
from .runner import safe_relpath


def parse_lcov(text: str, graph_root: str, known_files: set[str]) -> tuple[dict[str, Any], list[str]]:
    """Parse LCOV tracefile content into normalized files structure and unmatched list."""
    files: dict[str, Any] = {}
    unmatched: list[str] = []

    current_file = None
    lines_exec = set()
    lines_miss = set()
    branch_exec = []
    branch_miss = []

    def flush_record() -> None:
        nonlocal current_file, lines_exec, lines_miss, branch_exec, branch_miss
        if not current_file:
            return

        norm_file = current_file.replace("\\", "/")
        matched_path = None

        if norm_file in known_files:
            matched_path = norm_file
        else:
            rel = safe_relpath(norm_file, graph_root)
            if rel in known_files:
                matched_path = rel
            else:
                for kf in known_files:
                    if norm_file.endswith(kf) or kf.endswith(norm_file):
                        matched_path = kf
                        break

        if matched_path:
            files[matched_path] = {
                "lines_executed": sorted(list(lines_exec)),
                "lines_missing": sorted(list(lines_miss)),
                "branches": {
                    "branch_executed": branch_exec,
                    "branch_missing": branch_miss,
                },
            }
        else:
            unmatched.append(current_file)

        current_file = None
        lines_exec = set()
        lines_miss = set()
        branch_exec = []
        branch_miss = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("SF:"):
            current_file = line[3:].strip()
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            if len(parts) >= 2:
                try:
                    l_no = int(parts[0])
                    hits = int(parts[1])
                    if hits > 0:
                        lines_exec.add(l_no)
                    else:
                        lines_miss.add(l_no)
                except ValueError:
                    pass
        elif line.startswith("BRDA:"):
            parts = line[5:].split(",")
            if len(parts) >= 4:
                try:
                    l_no = int(parts[0])
                    b_idx = int(parts[2])
                    taken = parts[3]
                    if taken == "-" or taken == "0":
                        branch_miss.append([l_no, b_idx])
                    else:
                        branch_exec.append([l_no, b_idx])
                except ValueError:
                    pass
        elif line == "end_of_record":
            flush_record()

    flush_record()
    return files, sorted(list(set(unmatched)))


def parse_cobertura(xml_text: str, graph_root: str, known_files: set[str]) -> tuple[dict[str, Any], list[str]]:
    """Parse Cobertura XML content into normalized files structure and unmatched list."""
    files: dict[str, Any] = {}
    unmatched: list[str] = []

    try:
        tree = ET.fromstring(xml_text)
    except Exception:
        return files, unmatched

    for cls_elem in tree.findall(".//class"):
        fname = cls_elem.get("filename", "")
        if not fname:
            continue

        norm_file = fname.replace("\\", "/")
        matched_path = None

        if norm_file in known_files:
            matched_path = norm_file
        else:
            rel = safe_relpath(norm_file, graph_root)
            if rel in known_files:
                matched_path = rel
            else:
                for kf in known_files:
                    if norm_file.endswith(kf) or kf.endswith(norm_file):
                        matched_path = kf
                        break

        lines_exec = set()
        lines_miss = set()
        branch_exec = []
        branch_miss = []

        for line_elem in cls_elem.findall(".//line"):
            try:
                l_no = int(line_elem.get("number", 0))
                hits = int(line_elem.get("hits", 0))
                if hits > 0:
                    lines_exec.add(l_no)
                else:
                    lines_miss.add(l_no)

                if line_elem.get("branch") == "true":
                    cond = line_elem.get("condition-coverage", "")
                    # condition-coverage="50% (1/2)"
                    m = re.search(r"\((\d+)/(\d+)\)", cond)
                    if m:
                        cov_branches = int(m.group(1))
                        total_branches = int(m.group(2))
                        for i in range(cov_branches):
                            branch_exec.append([l_no, i])
                        for i in range(cov_branches, total_branches):
                            branch_miss.append([l_no, i])
            except ValueError:
                continue

        if matched_path:
            existing = files.get(matched_path)
            if existing:
                lines_exec.update(existing["lines_executed"])
                lines_miss.update(existing["lines_missing"])
                branch_exec.extend(existing["branches"]["branch_executed"])
                branch_miss.extend(existing["branches"]["branch_missing"])

            files[matched_path] = {
                "lines_executed": sorted(list(lines_exec)),
                "lines_missing": sorted(list(lines_miss)),
                "branches": {
                    "branch_executed": branch_exec,
                    "branch_missing": branch_miss,
                },
            }
        else:
            unmatched.append(fname)

    return files, sorted(list(set(unmatched)))


def map_coverage_to_nodes(
    graph: Graph,
    files_cov: dict[str, Any],
    contexts_by_file_line: dict[str, dict[int, list[str]]] | None = None,
) -> dict[str, Any]:
    """Map per-file executed and missing lines to code graph nodes."""
    nodes_cov: dict[str, Any] = {}
    contexts_by_file_line = contexts_by_file_line or {}

    for nid, node in graph.nodes.items():
        if node.kind not in ("function", "test", "class", "file"):
            continue

        file_key = node.path.replace("\\", "/")
        fcov = files_cov.get(file_key)
        if not fcov:
            for fk in files_cov:
                if fk.endswith(file_key) or file_key.endswith(fk):
                    fcov = files_cov[fk]
                    file_key = fk
                    break

        if not fcov:
            nodes_cov[nid] = {
                "pct": 0.0,
                "executed": [],
                "missing": [],
                "branch_pct": None,
                "tests": [],
            }
            continue

        lines_exec = set(fcov.get("lines_executed", []))
        lines_miss = set(fcov.get("lines_missing", []))
        branch_exec = fcov.get("branches", {}).get("branch_executed", [])
        branch_miss = fcov.get("branches", {}).get("branch_missing", [])

        # Filter lines to node line range
        node_exec = sorted(l for l in lines_exec if node.line_start <= l <= node.line_end)
        node_miss = sorted(l for l in lines_miss if node.line_start <= l <= node.line_end)

        # For function nodes, evaluate body lines (lines > line_start) to avoid def line inflating
        if node.kind in ("function", "test") and node.line_end > node.line_start:
            body_exec = [l for l in node_exec if l > node.line_start]
            body_miss = [l for l in node_miss if l > node.line_start]
            total_body = len(body_exec) + len(body_miss)
            if total_body > 0:
                pct = round(len(body_exec) / total_body * 100.0, 1)
                node_exec = body_exec
                node_miss = body_miss
            else:
                total_node = len(node_exec) + len(node_miss)
                pct = round(len(node_exec) / total_node * 100.0, 1) if total_node else 100.0
        else:
            total_node = len(node_exec) + len(node_miss)
            pct = round(len(node_exec) / total_node * 100.0, 1) if total_node else 100.0

        # Branch coverage for node
        b_exec = [b for b in branch_exec if node.line_start <= b[0] <= node.line_end]
        b_miss = [b for b in branch_miss if node.line_start <= b[0] <= node.line_end]
        tot_b = len(b_exec) + len(b_miss)
        branch_pct = round(len(b_exec) / tot_b * 100.0, 1) if tot_b > 0 else 100.0

        # Tests from dynamic contexts
        tests: set[str] = set()
        file_ctx = contexts_by_file_line.get(file_key, {})
        for l in range(node.line_start, node.line_end + 1):
            for c in file_ctx.get(l, []):
                if c:
                    tests.add(c)

        nodes_cov[nid] = {
            "pct": pct,
            "executed": node_exec,
            "missing": node_miss,
            "branch_pct": branch_pct,
            "tests": sorted(list(tests)),
        }

    return nodes_cov


def collect_coverage(
    root: str = ".",
    *,
    runner_name: str | None = None,
    import_format: str | None = None,
    import_file: str | None = None,
    branch: bool = False,
    contexts: bool = False,
    flag_cmd: str | None = None,
) -> dict[str, Any]:
    """Collect or import line/branch coverage and attach it to code graph nodes."""
    root = os.path.abspath(root)

    # 1. Load code graph
    graph_json = os.path.join(root, ".agent", "graph", "graph.json")
    if not os.path.exists(graph_json):
        return {
            "ok": False,
            "error": "graph file not found",
            "hint": "run ad-graph build",
        }

    try:
        graph, graph_sha = load_graph(root)
    except Exception as e:
        return {
            "ok": False,
            "error": f"failed to load graph: {e}",
            "hint": "run ad-graph build",
        }

    known_files = {n.path.replace("\\", "/") for n in graph.nodes.values()}

    files_cov: dict[str, Any] = {}
    unmatched: list[str] = []
    contexts_by_file: dict[str, dict[int, list[str]]] = {}
    source_name = "coverage.py"

    # 2. Import path (lcov or cobertura)
    if import_format and import_file:
        source_name = import_format.lower()
        if not os.path.isabs(import_file):
            import_file = os.path.join(root, import_file)
        if not os.path.exists(import_file):
            return {
                "ok": False,
                "error": f"import file not found: {import_file}",
                "hint": "check path to coverage file",
            }

        content = textio.read_text(import_file)
        if source_name == "lcov":
            files_cov, unmatched = parse_lcov(content, root, known_files)
        elif source_name in ("cobertura", "xml"):
            source_name = "cobertura"
            files_cov, unmatched = parse_cobertura(content, root, known_files)
        else:
            return {
                "ok": False,
                "error": f"unsupported import format: {import_format}",
                "hint": "supported formats: lcov, cobertura",
            }
    else:
        # 3. Python coverage execution
        try:
            import coverage
        except ImportError:
            return {
                "ok": False,
                "fail": "missing_dependency",
                "error": "coverage package not installed",
                "hint": "pip install agentdata[test] (or pip install coverage>=7)",
            }

        # Resolve test runner
        if flag_cmd:
            cmd_str = flag_cmd
        elif runner_name:
            if runner_name == "pytest":
                cmd_str = "python -m pytest"
            elif runner_name == "unittest":
                cmd_str = "python -m unittest discover"
            else:
                cmd_str = runner_name
        else:
            info = detect_runner(root)
            if not info:
                return {
                    "ok": False,
                    "error": "no test runner detected",
                    "hint": "set test_cmd in AGENTS.md",
                }
            cmd_str = info.cmd

        out_dir = os.path.join(root, ".agent", "out")
        os.makedirs(out_dir, exist_ok=True)
        cov_data_file = os.path.join(out_dir, ".coverage")
        cov_rc_file = os.path.join(out_dir, ".coveragerc")

        # Clean any prior coverage databases to avoid merging stale data
        for f in os.listdir(out_dir):
            if f.startswith(".coverage"):
                try:
                    os.remove(os.path.join(out_dir, f))
                except OSError:
                    pass

        rc_lines = ["[run]"]
        if branch:
            rc_lines.append("branch = True")
        if contexts:
            rc_lines.append("dynamic_context = test_function")
        rc_lines.append(f"data_file = {cov_data_file}")
        textio.write_text(cov_rc_file, "\n".join(rc_lines) + "\n")

        # Command: python -m coverage run --rcfile=... --data-file=... -m pytest ...
        cmd_tokens = shlex.split(cmd_str, posix=(os.name != "nt"))
        first_token = cmd_tokens[0] if cmd_tokens else ""
        first_base = os.path.basename(first_token).lower()
        if first_token in ("python", "python3") or first_base.startswith("python"):
            runner_args = cmd_tokens[1:]
        else:
            runner_args = ["-m", *cmd_tokens]

        if any("pytest" in arg for arg in runner_args):
            pytest_cache = os.path.join(out_dir, ".pytest_cache")
            if "-o" not in runner_args and "cache_dir" not in " ".join(runner_args):
                runner_args.extend(["-o", f"cache_dir={pytest_cache}"])

        cov_cmd = [
            sys.executable,
            "-B",
            "-m",
            "coverage",
            "run",
            f"--rcfile={cov_rc_file}",
            f"--data-file={cov_data_file}",
        ]
        if branch:
            cov_cmd.append("--branch")
        cov_cmd.extend(runner_args)

        # Execute
        cov_env = os.environ.copy()
        cov_env["PYTHONDONTWRITEBYTECODE"] = "1"
        real, _info = proc.prepare(cov_cmd)
        try:
            p = subprocess.run(
                real,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                env=cov_env,
            )
        except Exception as e:
            return {
                "ok": False,
                "error": f"failed to run coverage: {e}",
                "hint": "check test suite execution",
            }

        # Read coverage SQLite data through coverage.Coverage API
        if not os.path.exists(cov_data_file):
            return {
                "ok": False,
                "error": "coverage data file was not generated",
                "hint": "verify test runner executed under coverage",
            }

        cov = coverage.Coverage(data_file=cov_data_file, config_file=cov_rc_file)
        cov.load()
        cdata = cov.get_data()

        for mfile in cdata.measured_files():
            rel_mfile = safe_relpath(mfile, root)
            matched_path = None
            if rel_mfile in known_files:
                matched_path = rel_mfile
            else:
                for kf in known_files:
                    if rel_mfile.endswith(kf) or kf.endswith(rel_mfile):
                        matched_path = kf
                        break

            try:
                analysis = cov.analysis2(mfile)
                # analysis2 returns (filename, executable, excluded, missing, missing_branches_str)
                exec_lines = sorted(list(set(analysis[1]) - set(analysis[3])))
                miss_lines = sorted(analysis[3])
            except Exception:
                exec_lines = sorted(cdata.lines(mfile) or [])
                miss_lines = []

            # Branch arcs
            branch_exec = []
            branch_miss = []
            if branch:
                try:
                    f_analyzer = cov._analyze(mfile)
                    miss_arcs = f_analyzer.missing_branch_arcs()
                    for from_l, to_list in miss_arcs.items():
                        for to_l in to_list:
                            branch_miss.append([from_l, to_l])
                    exec_arcs = f_analyzer.executed_branch_arcs()
                    for from_l, to_list in exec_arcs.items():
                        for to_l in to_list:
                            branch_exec.append([from_l, to_l])
                except Exception:
                    pass

            target_path = matched_path or rel_mfile
            files_cov[target_path] = {
                "lines_executed": exec_lines,
                "lines_missing": miss_lines,
                "branches": {
                    "branch_executed": branch_exec,
                    "branch_missing": branch_miss,
                },
            }

            # Line contexts
            try:
                line_contexts = cdata.contexts_by_lineno(mfile)
                if line_contexts:
                    contexts_by_file[target_path] = line_contexts
            except Exception:
                pass

    # 4. Map file coverage to code graph nodes
    nodes_cov = map_coverage_to_nodes(graph, files_cov, contexts_by_file)

    # 5. Write .agent/graph/coverage.json
    out_graph_dir = os.path.join(root, ".agent", "graph")
    os.makedirs(out_graph_dir, exist_ok=True)
    cov_json_path = os.path.join(out_graph_dir, "coverage.json")

    result = {
        "graph_sha256": graph_sha,
        "source": source_name,
        "collected_at": datetime.datetime.now().isoformat(),
        "files": files_cov,
        "nodes": nodes_cov,
        "unmatched": unmatched,
    }

    textio.write_text(cov_json_path, json.dumps(result, indent=2))
    return {
        "ok": True,
        "source": "ad-test coverage",
        "graph_sha256": graph_sha,
        "files_covered": len(files_cov),
        "nodes_covered": len(nodes_cov),
        "path": safe_relpath(cov_json_path, root),
        "data": result,
    }


def diff_coverage(current_cov: dict[str, Any], base_cov: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare two coverage dicts node-by-node returning [node, pct_before, pct_after, delta]."""
    cur_nodes = current_cov.get("nodes", {})
    base_nodes = base_cov.get("nodes", {})

    all_nids = sorted(list(set(cur_nodes.keys()) | set(base_nodes.keys())))
    rows: list[dict[str, Any]] = []

    for nid in all_nids:
        pct_before = base_nodes.get(nid, {}).get("pct", 0.0)
        pct_after = cur_nodes.get(nid, {}).get("pct", 0.0)
        delta = round(pct_after - pct_before, 1)
        rows.append({
            "node": nid,
            "pct_before": pct_before,
            "pct_after": pct_after,
            "delta": delta,
        })

    return rows
