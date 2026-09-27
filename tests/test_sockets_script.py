""".github/scripts/sockets.py and the Windows step that runs it after the serial suite (#435).

The step only runs on a Windows runner, so what CI alone can prove is that `netstat` and `tasklist` there
print what these samples print. Everything else is checked here: the parsing, the ranking and the
counts on synthetic output in the tools' own formats, the command line, and the step's place and
`always()` in `.github/workflows/tests.yml`.
"""
from __future__ import annotations
import importlib.util
import os
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, ".github", "scripts", "sockets.py")
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")

# `netstat -ano -p tcp` on Windows: a header, then Proto, Local, Foreign, State, PID.
NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1016
  TCP    127.0.0.1:52207        0.0.0.0:0              LISTENING       4120
  TCP    127.0.0.1:52207        127.0.0.1:61001        ESTABLISHED     4120
  TCP    127.0.0.1:52207        127.0.0.1:61002        CLOSE_WAIT      4120
  TCP    127.0.0.1:61001        127.0.0.1:52207        ESTABLISHED     7788
  TCP    127.0.0.1:61002        127.0.0.1:52207        FIN_WAIT_2      7788
  TCP    127.0.0.1:61003        127.0.0.1:52207        ESTABLISHED     7788
  TCP    127.0.0.1:61004        127.0.0.1:52207        TIME_WAIT       0
  TCP    127.0.0.1:61005        127.0.0.1:52207        TIME_WAIT       0
  TCP    [::1]:9229             [::]:0                 LISTENING       9001
"""

# `tasklist /fo csv /nh`: Image Name, PID, Session Name, Session#, Mem Usage.
TASKLIST = '''"System Idle Process","0","Services","0","8 K"
"svchost.exe","1016","Services","0","12,340 K"
"python.exe","4120","Console","1","80,112 K"
"chrome.exe","7788","Console","1","150,000 K"
"chrome.exe","7790","Console","1","40,000 K"
"node.exe","9001","Console","1","30,000 K"
"Chrome.EXE","7791","Console","1","40,000 K"
'''


@pytest.fixture(scope="module")
def sockets():
    spec = importlib.util.spec_from_file_location("sockets_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_netstat_and_tasklist_parse(sockets):
    rows = sockets.parse_netstat(NETSTAT)
    assert len(rows) == 10
    assert rows[0] == ("LISTENING", 1016) and rows[-1] == ("LISTENING", 9001)
    images = sockets.parse_tasklist(TASKLIST)
    assert images[7788] == "chrome.exe" and images[0] == "System Idle Process" and len(images) == 7


def test_the_report_ranks_pids_by_sockets_and_counts_the_browsers(sockets):
    out = sockets.report(NETSTAT, TASKLIST, top=10).splitlines()
    assert "TCP connections: 10; in TIME_WAIT: 2" in out
    assert "TCP connections in TIME_WAIT: 2" in out, "the line #465's step printed, kept for comparison"
    ranked = [ln for ln in out if ln.startswith("  ") and ln.split()[0].isdigit()]
    assert [ln.split()[0] for ln in ranked] == ["4120", "7788", "1016", "9001"], ranked
    assert ranked[0].split()[1:3] == ["3", "python.exe"]
    assert "CLOSE_WAIT 1" in ranked[0] and "ESTABLISHED 1" in ranked[0] and "LISTENING 1" in ranked[0]
    assert all(ln.split()[0] != "0" for ln in ranked), "TIME_WAIT has no owner; it is counted on its own line"
    assert "live chrome.exe: 3" in out and "live node.exe: 1" in out


def test_the_report_keeps_the_top_ten_and_names_an_unknown_pid(sockets):
    many = "\n".join(f"  TCP    127.0.0.1:{50000 + i}    127.0.0.1:80    ESTABLISHED     {100 + i % 12}"
                     for i in range(12 * 5 + 3))
    out = sockets.report(many, "", top=10).splitlines()
    ranked = [ln for ln in out if ln.startswith("  ") and ln.split()[0].isdigit()]
    assert len(ranked) == 10
    assert [ln.split()[0] for ln in ranked[:3]] == ["100", "101", "102"], "6 sockets each, then ties by PID"
    assert ranked[0].split()[2] == "?", "a PID tasklist did not list (it exited in between)"
    assert "live chrome.exe: 0" in out and "live node.exe: 0" in out


def test_the_command_line_reads_saved_output_and_never_fails(tmp_path):
    (tmp_path / "netstat.txt").write_text(NETSTAT, encoding="utf-8")
    (tmp_path / "tasklist.txt").write_text(TASKLIST, encoding="utf-8")
    p = subprocess.run([sys.executable, SCRIPT, "--netstat", str(tmp_path / "netstat.txt"),
                        "--tasklist", str(tmp_path / "tasklist.txt")], capture_output=True, text=True)
    assert p.returncode == 0 and "live chrome.exe: 3" in p.stdout, p.stdout + p.stderr

    missing = subprocess.run([sys.executable, SCRIPT, "--netstat", str(tmp_path / "absent.txt")],
                             capture_output=True, text=True)
    assert missing.returncode == 0, "diagnostics never fail the job"
    assert "could not read" in missing.stdout, missing.stdout


def _windows_steps() -> list[dict]:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)["jobs"]["windows"]["steps"]


def test_the_windows_job_prints_the_sockets_right_after_the_serial_suite():
    steps = _windows_steps()
    serial = next(i for i, s in enumerate(steps) if s.get("name") == "pytest")
    step = steps[serial + 1]
    assert "always()" in str(step.get("if")), "a red suite is exactly when the numbers are needed"
    assert ".github/scripts/sockets.py" in step["run"]
    assert "netsh int ipv4 show dynamicport tcp" in step["run"], "#465's port range stays"
    assert step["run"].rstrip().endswith("exit 0") and isinstance(step.get("timeout-minutes"), int)
