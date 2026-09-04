"""Repository test runner detection."""
from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .. import config as C
from .. import textio


@dataclass
class TestRunnerInfo:
    runner: str
    cmd: str
    evidence: str
    root: str

    def to_dict(self) -> dict[str, str]:
        return {
            "runner": self.runner,
            "cmd": self.cmd,
            "evidence": self.evidence,
            "root": self.root,
        }


def _file_exists(path: str, det: Any = None) -> bool:
    if det is not None and hasattr(det, "exists"):
        return bool(det.exists(path))
    return os.path.exists(path)


def _read_text(path: str, det: Any = None) -> str:
    try:
        if det is not None and hasattr(det, "read_text"):
            return str(det.read_text(path))
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _glob_files(pattern: str, root: str, det: Any = None) -> list[str]:
    if det is not None and hasattr(det, "glob"):
        return sorted(det.glob(pattern, root))
    full_pattern = os.path.join(root, pattern)
    return sorted(glob.glob(full_pattern, recursive=True))


def detect_all(root: str = ".", *, det: Any = None, flag_cmd: str | None = None) -> list[TestRunnerInfo]:
    """Inspect root and return all detected test runner candidates in priority order."""
    root = os.path.abspath(root)
    candidates: list[TestRunnerInfo] = []

    # 1. Configured test_cmd via flag -> env -> config -> AGENTS.md
    agents_md = os.path.join(root, "AGENTS.md")
    facts: dict[str, str] = {}
    if _file_exists(agents_md, det=det):
        facts_text = _read_text(agents_md, det=det)
        for line in facts_text.splitlines():
            m = re.match(r"^\s*-\s*([A-Za-z_][\w\-]*)\s*:\s*(.*?)\s*$", line)
            if m:
                k, v = m.group(1).lower(), m.group(2)
                v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip("`").strip('"').strip("'")
                if v and not (v.startswith("<") and v.endswith(">")):
                    facts[k] = v

    try:
        cfg = C.load() if det is None else getattr(det, "cfg", {})
    except Exception:
        cfg = {}

    test_cmd = None
    evidence = ""
    if flag_cmd:
        test_cmd = flag_cmd
        evidence = "flag:--test-cmd"
    elif os.environ.get("AGENTDATA_TEST_CMD"):
        test_cmd = os.environ["AGENTDATA_TEST_CMD"]
        evidence = "env:AGENTDATA_TEST_CMD"
    elif C.get(cfg, "project.test_cmd"):
        test_cmd = C.get(cfg, "project.test_cmd")
        evidence = "config:project.test_cmd"
    elif "test_cmd" in facts:
        test_cmd = facts["test_cmd"]
        evidence = "AGENTS.md:test_cmd"

    if test_cmd:
        candidates.append(TestRunnerInfo(
            runner="configured",
            cmd=test_cmd,
            evidence=evidence,
            root=root,
        ))

    # 2. Pytest configurations:
    # pyproject.toml [tool.pytest.ini_options], pytest.ini, tox.ini, setup.cfg [tool:pytest]
    pytest_matched = False
    pyproject_path = os.path.join(root, "pyproject.toml")
    if _file_exists(pyproject_path, det=det):
        content = _read_text(pyproject_path, det=det)
        if "[tool.pytest" in content:
            candidates.append(TestRunnerInfo(
                runner="pytest",
                cmd="python -m pytest",
                evidence="pyproject.toml",
                root=root,
            ))
            pytest_matched = True

    pytest_ini_path = os.path.join(root, "pytest.ini")
    if not pytest_matched and _file_exists(pytest_ini_path, det=det):
        candidates.append(TestRunnerInfo(
            runner="pytest",
            cmd="python -m pytest",
            evidence="pytest.ini",
            root=root,
        ))
        pytest_matched = True

    tox_ini_path = os.path.join(root, "tox.ini")
    if not pytest_matched and _file_exists(tox_ini_path, det=det):
        content = _read_text(tox_ini_path, det=det)
        if "[pytest]" in content or "pytest" in content:
            candidates.append(TestRunnerInfo(
                runner="pytest",
                cmd="python -m pytest",
                evidence="tox.ini",
                root=root,
            ))
            pytest_matched = True

    setup_cfg_path = os.path.join(root, "setup.cfg")
    if not pytest_matched and _file_exists(setup_cfg_path, det=det):
        content = _read_text(setup_cfg_path, det=det)
        if "[tool:pytest]" in content or "[pytest]" in content:
            candidates.append(TestRunnerInfo(
                runner="pytest",
                cmd="python -m pytest",
                evidence="setup.cfg",
                root=root,
            ))
            pytest_matched = True

    # 3. tests/ or test/ with test_*.py or *_test.py (and no pytest config matched)
    test_files: list[str] = []
    for tdir in ("tests", "test"):
        matched = _glob_files(f"{tdir}/**/test_*.py", root, det=det)
        matched += _glob_files(f"{tdir}/**/*_test.py", root, det=det)
        if matched:
            test_files.extend(matched)

    if test_files:
        rel_example = textio.norm_path(os.path.relpath(test_files[0], root))
        # If pytest was already matched, unittest can still be in candidates for --all
        candidates.append(TestRunnerInfo(
            runner="unittest",
            cmd="python -m unittest discover",
            evidence=rel_example,
            root=root,
        ))

    # 4. package.json with scripts.test -> npm test
    pkg_json_path = os.path.join(root, "package.json")
    if _file_exists(pkg_json_path, det=det):
        try:
            raw = _read_text(pkg_json_path, det=det)
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                scripts = data.get("scripts", {})
                if isinstance(scripts, dict) and scripts.get("test"):
                    candidates.append(TestRunnerInfo(
                        runner="npm",
                        cmd="npm test",
                        evidence="package.json:scripts.test",
                        root=root,
                    ))
        except Exception:
            pass

    # 5. *.csproj or *.sln with Microsoft.NET.Test.Sdk -> dotnet test
    csproj_files = _glob_files("**/*.csproj", root, det=det)
    sln_files = _glob_files("*.sln", root, det=det)
    dotnet_found = False
    for cf in csproj_files:
        content = _read_text(cf, det=det)
        if "Microsoft.NET.Test.Sdk" in content or "xunit" in content or "nunit" in content:
            rel = textio.norm_path(os.path.relpath(cf, root))
            candidates.append(TestRunnerInfo(
                runner="dotnet",
                cmd="dotnet test",
                evidence=f"{rel}:Microsoft.NET.Test.Sdk",
                root=root,
            ))
            dotnet_found = True
            break
    if not dotnet_found and sln_files:
        for sf in sln_files:
            content = _read_text(sf, det=det)
            if "Test" in content or "test" in content:
                rel = textio.norm_path(os.path.relpath(sf, root))
                candidates.append(TestRunnerInfo(
                    runner="dotnet",
                    cmd="dotnet test",
                    evidence=f"{rel}:Microsoft.NET.Test.Sdk",
                    root=root,
                ))
                break

    # 6. Makefile with a test: target -> make test
    for mf_name in ("Makefile", "makefile", "GNUmakefile"):
        mf_path = os.path.join(root, mf_name)
        if _file_exists(mf_path, det=det):
            content = _read_text(mf_path, det=det)
            if re.search(r"^test\s*:", content, re.MULTILINE):
                candidates.append(TestRunnerInfo(
                    runner="make",
                    cmd="make test",
                    evidence=f"{mf_name}:test",
                    root=root,
                ))
                break

    return candidates


def detect_runner(root: str = ".", *, det: Any = None, flag_cmd: str | None = None) -> TestRunnerInfo | None:
    """Detect the primary test runner for the repo (first match wins)."""
    candidates = detect_all(root, det=det, flag_cmd=flag_cmd)
    return candidates[0] if candidates else None
