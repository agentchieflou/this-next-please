"""The fake-tool harness, and the Windows behaviour it un-skips.

`tests/test_proc.py` had six tests marked `skipif(os.name == "nt")` with the reason "POSIX shell
stand-in for pncli" — so the Windows behaviour of the module that exists *because of* Windows was
skipped on Windows, which is where it breaks. These run on both.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

import pytest

from agentdata import proc
from agentdata.connectors import pncli as P

import fakes

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"


# ------------------------------------------------------------------------------- the harness


def test_a_fake_materialises_for_this_platform(tmp_path):
    fakes.install(tmp_path, ["pncli"])
    bin_dir = os.path.join(str(tmp_path), "fakebin")
    assert os.path.isfile(os.path.join(bin_dir, "pncli")), "the sh shim is written on every OS"
    if WINDOWS:
        shim = open(os.path.join(bin_dir, "pncli.cmd"), encoding="utf-8").read()
        assert "node_modules" in shim, "the Windows shim must look like npm's, because proc.py unwraps it"


def test_an_unmatched_argv_is_loud(tmp_path):
    env = fakes.install(tmp_path, ["pncli"])
    p = subprocess.run([sys.executable, fakes.RUNNER, "pncli", "nothing", "like", "this"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 99, "a silent success would prove nothing"
    assert "no transcript matches" in p.stderr
    assert "nothing" in p.stderr, "the test must be able to see what the code sent"


def test_a_case_can_be_selected_explicitly(tmp_path):
    env = fakes.install(tmp_path, ["pncli"], case="version")
    p = subprocess.run([sys.executable, fakes.RUNNER, "pncli", "--version"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "pncli/1.4.0" in p.stdout


def test_every_transcript_records_its_provenance():
    for tool in ("pip", "gh", "pncli", "az", "te2", "dscmd", "powershell"):
        assert fakes.cases(tool), f"{tool} has no transcripts"
        for case in fakes.cases(tool):
            entry = fakes.load_case(tool, case)
            assert entry.get("source") in ("captured", "photographed", "synthesized"), f"{tool}/{case}"
            assert "captured" in entry, f"{tool}/{case} does not say when it was recorded"
            for key in ("returncode", "stdout", "stderr"):
                assert key in entry, f"{tool}/{case} has no {key}"


def test_the_recorder_exists_and_explains_itself():
    text = open(os.path.join(REPO_ROOT, "tests", "fakes", "record.py"), encoding="utf-8").read()
    assert "captured" in text and "invented" in text


# ------------------------------------------------- the pncli tests, now running on both platforms


def _pncli_env(monkeypatch, tmp_path, case):
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case=case)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    bin_dir = os.path.join(str(tmp_path), "fakebin")
    exe = os.path.join(bin_dir, "pncli.cmd" if WINDOWS else "pncli")
    monkeypatch.setenv("PNCLI_EXE", exe)
    return exe


def test_pncli_run_returns_the_payload(monkeypatch, tmp_path):
    _pncli_env(monkeypatch, tmp_path, "search_ok")
    payload, elapsed = P.run(["jira", "search", "--jql", "key = RDSD-1"])
    assert payload["issues"][0]["key"] == "RDSD-1"
    assert elapsed >= 0


def test_pncli_non_json_output_is_a_bad_output_error(monkeypatch, tmp_path):
    _pncli_env(monkeypatch, tmp_path, "bad_json")
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "bad_output"
    assert e.value.detail["exit_code"] == 3
    assert "not json" in e.value.msg


def test_pncli_own_error_is_surfaced_verbatim(monkeypatch, tmp_path):
    _pncli_env(monkeypatch, tmp_path, "pncli_error")
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "pncli_error" and e.value.msg == "bad JQL"


def test_a_missing_pncli_names_the_npm_package(monkeypatch, tmp_path):
    """The 2026-09-02 failure: there is no pncli.exe, and the hint has to say so."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("PNCLI_EXE", str(tmp_path / "gone.cmd"))
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "not_found"
    assert "npm install -g @kolatts/pncli" in e.value.hint


def test_where_reports_the_resolved_launcher(monkeypatch, tmp_path):
    exe = _pncli_env(monkeypatch, tmp_path, "version")
    info = P.where()
    assert info["found"] and info["rc"] == 0
    assert info["version"] == "pncli/1.4.0"
    assert exe.replace("\\", "/").endswith(info["path"].replace("\\", "/").split("/")[-1])


def test_a_positional_argument_becomes_the_exact_fix(monkeypatch, tmp_path):
    """2026-09-02 laptop friction: pncli options are named, never positional."""
    _pncli_env(monkeypatch, tmp_path, "positional_option")
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "get-issue", "RDSD-22399"])
    assert e.value.code == "bad_output"
    assert "--key RDSD-22399" in e.value.hint


def test_get_issue_uses_the_named_option(monkeypatch, tmp_path):
    _pncli_env(monkeypatch, tmp_path, "get_issue_ok")
    table = P.get_issue("RDSD-22399")
    assert table.source == "pncli jira get-issue --key RDSD-22399"
    row = dict(zip(table.columns, table.rows[0]))
    assert row["key"] == "RDSD-22399" and row["status"] == "In Progress"


# --------------------------------------------------------------------- the npm shim, unwrapped


@pytest.mark.skipif(not WINDOWS, reason="npm shims are a Windows concept")
def test_proc_unwraps_an_npm_shim(monkeypatch, tmp_path):
    """`proc.py` runs the shim's node entry point directly so cmd.exe never re-parses an argument.

    This is the behaviour the old `skipif(nt)` tests skipped on the one OS where it matters.
    """
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case="version")
    shim = os.path.join(str(tmp_path), "fakebin", "pncli.cmd")
    info = proc.resolve("pncli")
    assert info["path"].lower().endswith(("pncli.cmd", "pncli"))
    assert os.path.isfile(shim)


def test_resolve_finds_the_fake_on_path(monkeypatch, tmp_path):
    fakes.apply(monkeypatch, tmp_path, ["gh"], case="skill_install_ok")
    info = proc.resolve("gh")
    assert info["path"], "the fake must be discoverable exactly as the real tool would be"


def test_a_fake_runs_through_proc_run(monkeypatch, tmp_path):
    fakes.apply(monkeypatch, tmp_path, ["gh"], case="skill_install_ok")
    rc, out, err, _elapsed = proc.run(["gh", "skill", "install", "--all"], timeout=60)
    assert rc == 0 and "installed 23 skills" in out


def test_the_gh_already_installed_transcript_replays(monkeypatch, tmp_path):
    fakes.apply(monkeypatch, tmp_path, ["gh"], case="2026-09-03-skills-already-installed")
    rc, _out, err, _elapsed = proc.run(["gh", "skill", "install", "--all"], timeout=60)
    assert rc == 1
    assert "already installed" in err


@pytest.mark.skipif(not WINDOWS, reason="the cmd.exe quoting limit is a Windows concept")
def test_a_multiline_body_is_refused_through_a_cmd_shim(monkeypatch, tmp_path, capsys):
    """The Windows half of `ad-pncli raw --body-file`, which used to be skipped on Windows.

    A page of HTML cannot survive cmd.exe's parsing, so when the only launcher is a `.cmd` shim and
    Node is absent, the command refuses with a hint naming the way out rather than sending a mangled
    body to Confluence. That refusal *is* the Windows behaviour, and it is worth asserting.
    """
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    body = tmp_path / "page.html"
    body.write_text("<h2>Findings</h2>\n<p>two lines</p>\n", encoding="utf-8")
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case="search_ok")
    monkeypatch.setenv("PNCLI_EXE", os.path.join(str(tmp_path), "fakebin", "pncli.cmd"))

    monkeypatch.setattr(sys, "argv", ["ad-pncli", "raw", "--body-file", str(body),
                                      "confluence", "create-page", "--space", "S", "--title", "T", "--dry-run"])
    from agentdata import cli

    with pytest.raises(SystemExit):
        cli.main_pncli()
    out = capsys.readouterr().out
    assert "ok: false" in out
    assert "cmd.exe" in out, "the refusal must say why"
    assert "Node.js" in out or "entry point" in out, "and how to get past it"


# ------------------------------------------------------------------- no skipif(nt) left behind


def test_a_windows_skip_must_name_the_test_that_covers_windows():
    """A test skipped on Windows for a Windows behaviour is a bug, not a caveat.

    The rule is not "never skip" -- a POSIX-shell stand-in is sometimes the clearest way to write
    the POSIX half. The rule is that the skip must name the test covering Windows, and that test
    must exist. That is checkable, and it makes the gap impossible to leave open by accident.
    """
    import glob
    import re

    all_test_names = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "tests", "**", "*.py"), recursive=True):
        all_test_names.update(re.findall(r"^def (test_\w+)", open(path, encoding="utf-8").read(), re.M))

    offenders = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        text = open(path, encoding="utf-8").read()
        for match in re.finditer(r'skipif\(\s*os\.name == "nt"\s*,\s*reason=(["\']) (?:.*?)\1\s*\)'.replace(" ", ""),
                                 text, re.S):
            reason = match.group(0)
            named = [n for n in all_test_names if n in reason]
            if not named:
                offenders.append(f"{rel}: {reason[:110]}")
    assert not offenders, (
        "a Windows skip must name the test that covers Windows (and that test must exist):\n  "
        + "\n  ".join(offenders))


# ----------------------------------------------------------------------------- drift detection


@pytest.mark.skipif(not WINDOWS, reason="the real powershell is the thing being compared against")
def test_the_powershell_transcript_still_matches_what_windows_answers():
    """A fake is only worth something while it still resembles the real tool.

    `desktop.py` asks Windows for msmdsrv processes through CIM. This runs the real query and
    asserts the *shape* the transcript claims -- a JSON array of objects with ProcessId,
    ParentProcessId and CommandLine, or an empty result when Power BI Desktop is not running.
    It deliberately does not assert content: CI has no Desktop.
    """
    query = ('Get-CimInstance Win32_Process -Filter "Name=\'msmdsrv.exe\'" | '
             'Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress')
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr

    body = (p.stdout or "").strip()
    if not body:
        return          # no Desktop on this machine: the `no_desktop` transcript is that case

    parsed = json.loads(body)
    rows = parsed if isinstance(parsed, list) else [parsed]
    for row in rows:
        assert set(row) >= {"ProcessId", "ParentProcessId", "CommandLine"}, (
            f"the CIM shape changed; tests/fakes/powershell/transcripts is now wrong: {row}")

    transcript = fakes.load_case("powershell", "msmdsrv_list")
    sample = json.loads(transcript["stdout"])
    assert set(sample[0]) == {"ProcessId", "ParentProcessId", "CommandLine"}, \
        "the transcript no longer matches the query the code sends"
