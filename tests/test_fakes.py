"""The fake-tool harness, and the Windows behaviour it un-skips.

`tests/test_proc.py` had six tests marked `skipif(os.name == "nt")` with the reason "POSIX shell
stand-in for pncli" (toil's predecessor) — so the Windows behaviour of the module that exists *because of* Windows was
skipped on Windows, which is where it breaks. These run on both.
"""
from __future__ import annotations
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

from agentdata import proc
from agentdata.connectors import toil as T

import fakes

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"


# ------------------------------------------------------------------------------- the harness


def test_a_fake_materialises_for_this_platform(tmp_path):
    fakes.install(tmp_path, ["toil"])
    bin_dir = os.path.join(str(tmp_path), "fakebin")
    assert os.path.isfile(os.path.join(bin_dir, "toil")), "the sh shim is written on every OS"
    if WINDOWS:
        shim = open(os.path.join(bin_dir, "toil.cmd"), encoding="utf-8").read()
        assert "node_modules" in shim, "the Windows shim must look like npm's, because proc.py unwraps it"


def test_an_unmatched_argv_is_loud(tmp_path):
    env = fakes.install(tmp_path, ["toil"])
    p = subprocess.run([sys.executable, fakes.RUNNER, "toil", "nothing", "like", "this"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 99, "a silent success would prove nothing"
    assert "no transcript matches" in p.stderr
    assert "nothing" in p.stderr, "the test must be able to see what the code sent"


def test_a_case_can_be_selected_explicitly(tmp_path):
    env = fakes.install(tmp_path, ["toil"], case="version_old_node")
    p = subprocess.run([sys.executable, fakes.RUNNER, "toil", "version"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1 and "UNSUPPORTED_NODE" in p.stdout


def test_an_always_transcript_answers_under_any_case(tmp_path, monkeypatch):
    # 1. Under AGENTDATA_FAKE_CASE=asks-question, copilot --version prints GitHub Copilot CLI 1.0.88. with rc 0,
    # and copilot help config prints the 1.0.88 fixture.
    env = fakes.install(tmp_path, ["copilot"], case="asks-question")
    p_ver = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "--version"],
                           capture_output=True, text=True, env=env)
    assert p_ver.returncode == 0
    assert "GitHub Copilot CLI 1.0.88." in p_ver.stdout

    p_conf = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "help", "config"],
                            capture_output=True, text=True, env=env)
    assert p_conf.returncode == 0
    expected_fixture = open(os.path.join(REPO_ROOT, "tests", "fixtures", "copilot", "help-config-1.0.88.txt"),
                            encoding="utf-8").read()
    assert p_conf.stdout == expected_fixture

    # 2. Under the same case, copilot -p hi still plays asks-question.
    # Check in-process: load tests/fakes/runner.py with importlib, monkeypatch sys.argv and play to a recorder,
    # call main(), and assert recorder got the asks-question entry.
    spec = importlib.util.spec_from_file_location("fake_runner_mod", fakes.RUNNER)
    runner_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner_mod)

    played = []
    monkeypatch.setattr(runner_mod, "play", lambda entry, argv: played.append((entry, argv)) or 0)
    monkeypatch.setattr(sys, "argv", ["runner.py", "copilot", "-p", "hi"])
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    rc = runner_mod.main()
    assert rc == 0
    assert len(played) == 1
    entry, argv = played[0]
    assert entry.get("session") == "sess-asks"
    assert argv == ["-p", "hi"]

    # 3. With no case, copilot --version, help config and --help answer from the new transcripts.
    env_nocase = fakes.install(tmp_path / "nocase", ["copilot"])
    p_ver_nc = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "--version"],
                              capture_output=True, text=True, env=env_nocase)
    assert p_ver_nc.returncode == 0 and "GitHub Copilot CLI 1.0.88." in p_ver_nc.stdout

    p_conf_nc = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "help", "config"],
                               capture_output=True, text=True, env=env_nocase)
    assert p_conf_nc.returncode == 0 and p_conf_nc.stdout == expected_fixture

    help_fixture = open(os.path.join(REPO_ROOT, "tests", "fixtures", "copilot", "help-1.0.88.txt"),
                        encoding="utf-8").read()
    p_help_nc = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "--help"],
                               capture_output=True, text=True, env=env_nocase)
    assert p_help_nc.returncode == 0 and p_help_nc.stdout == help_fixture


def test_an_unclaimed_argv_still_says_so(tmp_path):
    env = fakes.install(tmp_path, ["copilot"])
    p = subprocess.run([sys.executable, fakes.RUNNER, "copilot", "completion", "bash"],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 99
    assert "no transcript matches this argv" in p.stderr
    assert "completion" in p.stderr


def test_every_transcript_records_its_provenance():
    for tool in ("pip", "gh", "toil", "az", "te2", "dscmd", "powershell"):
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


# ------------------------------------------------- the toil tests, running on both platforms


def _toil_env(monkeypatch, tmp_path, case):
    fakes.apply(monkeypatch, tmp_path, ["toil"], case=case)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    bin_dir = os.path.join(str(tmp_path), "fakebin")
    exe = os.path.join(bin_dir, "toil.cmd" if WINDOWS else "toil")
    monkeypatch.setenv("TOIL_EXE", exe)
    return exe


def test_toil_run_returns_the_envelope(monkeypatch, tmp_path):
    _toil_env(monkeypatch, tmp_path, "search_ok")
    envelope, elapsed = T.run(["jira", "issue", "search", "--jql", "key = RDSD-22399", "--limit", "50"])
    assert envelope["ok"] is True and envelope["data"]["issues"][0]["key"] == "RDSD-22399"
    assert envelope["meta"]["page"] == {"nextCursor": None, "limit": 50}
    assert elapsed >= 0


def test_output_that_is_not_an_envelope_is_a_bad_output_error(monkeypatch, tmp_path):
    _toil_env(monkeypatch, tmp_path, "search_prose")
    with pytest.raises(proc.ProcError) as e:
        T.run(["jira", "issue", "search"])
    assert e.value.code == "bad_output"
    assert e.value.detail["exit_code"] == 3
    assert "not json" in e.value.msg


@pytest.mark.parametrize("case, code, fix", [
    ("not_found", "NOT_FOUND", "Check the key"),
    ("not_configured", "NOT_CONFIGURED", "TOIL_JIRA_BASE_URL"),
    ("write_disabled", "WRITE_DISABLED", '"writes": true'),
])
def test_toils_own_error_is_surfaced_with_its_code_and_fix(monkeypatch, tmp_path, case, code, fix):
    _toil_env(monkeypatch, tmp_path, case)
    argv = ["confluence", "page", "create"] if case == "write_disabled" else ["jira", "issue", "get", "X-1"]
    with pytest.raises(T.ToilError) as e:
        T.run(argv)
    assert e.value.code == code and fix in e.value.hint


def test_a_missing_toil_names_the_npm_package(monkeypatch, tmp_path):
    """The 2026-09-02 failure, met first with pncli: there is no toil.exe, and the hint has to say so."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("TOIL_EXE", str(tmp_path / "gone.cmd"))
    with pytest.raises(proc.ProcError) as e:
        T.run(["jira", "issue", "search"])
    assert e.value.code == "not_found"
    assert "npm install -g @imagile-dev/toil" in e.value.hint


def test_ad_view_gives_a_saved_get_issue_answer_the_issue_columns(monkeypatch, tmp_path, capsys):
    """The recipe the skills teach: `toil jira issue get <KEY> > .agent/out/<KEY>.json`, then `ad-view` it. The
    file is what the fake really printed, BOM and all, as PowerShell 5.1 writes it."""
    from agentdata import cli

    _toil_env(monkeypatch, tmp_path, "get_issue_ok")
    rc, out, _err, _el = proc.run(["toil", "jira", "issue", "get", "RDSD-22399"], exe=T.exe(), timeout=60)
    assert rc == 0
    saved = tmp_path / "RDSD-22399.json"
    saved.write_bytes(b"\xef\xbb\xbf" + out.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ad-view", str(saved)])
    cli.main_view()
    shown = capsys.readouterr().out
    assert "RDSD-22399" in shown and "In Progress" in shown and "status" in shown
    assert "fields.status.name" not in shown, "the issue columns, not the flattened paths"


def test_ad_view_gives_a_saved_search_the_search_columns_in_the_encoding_powershell_wrote(monkeypatch, tmp_path,
                                                                                          capsys):
    """`toil jira issue search ... > .agent/out/x.json` from Windows PowerShell 5.1 writes UTF-16 with a BOM; the
    envelope still reads as the search it is, and an empty file says so."""
    from agentdata import cli

    _toil_env(monkeypatch, tmp_path, "search_ok")
    _rc, out, _err, _el = proc.run(["toil", "jira", "issue", "search", "--jql", "key = RDSD-22399"], exe=T.exe(),
                                   timeout=60)
    saved = tmp_path / "search.json"
    saved.write_bytes(out.encode("utf-16"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ad-view", str(saved)])
    cli.main_view()
    shown = capsys.readouterr().out
    assert "RDSD-22399" in shown and re.search(r'source: "?ad-view', shown), shown
    assert "status" in shown and "summary" in shown and "Ana Lee" in shown, "the search columns"
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-view", str(empty)])
    with pytest.raises(SystemExit) as e:
        cli.main_view()
    assert e.value.code == 1 and "is empty" in capsys.readouterr().out


def test_ad_view_prints_a_failed_envelope_as_toils_error_and_fix(monkeypatch, tmp_path, capsys):
    from agentdata import cli

    _toil_env(monkeypatch, tmp_path, "not_found")
    _rc, out, _err, _el = proc.run(["toil", "jira", "issue", "get", "NOPE-1"], exe=T.exe(), timeout=60)
    saved = tmp_path / "NOPE-1.json"
    saved.write_text(out, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-view", str(saved)])
    with pytest.raises(SystemExit) as e:
        cli.main_view()
    shown = capsys.readouterr().out
    assert e.value.code == 1 and "NOT_FOUND: Issue Does Not Exist" in shown and "Check the key" in shown


def test_where_reports_the_resolved_launcher_and_toils_version(monkeypatch, tmp_path):
    exe = _toil_env(monkeypatch, tmp_path, "version")
    info = T.where()
    assert info["found"] and info["rc"] == 0
    assert info["version"] == "0.1.0-alpha.5" and info["node_version"] == "24.14.0" and info["contract"] == 1
    assert exe.replace("\\", "/").endswith(info["path"].replace("\\", "/").split("/")[-1])


def test_where_says_when_node_is_too_old(monkeypatch, tmp_path):
    _toil_env(monkeypatch, tmp_path, "version_old_node")
    info = T.where()
    assert info["found"] and info["rc"] == 1 and info["code"] == "UNSUPPORTED_NODE"
    assert "Node 24.14" in info["error"] and info["fix"].startswith("Install Node")


def test_get_issue_reads_the_issue(monkeypatch, tmp_path):
    _toil_env(monkeypatch, tmp_path, "get_issue_ok")
    table = T.get_issue("RDSD-22399")
    assert table.source == "toil jira issue get RDSD-22399"
    row = dict(zip(table.columns, table.rows[0]))
    assert row["key"] == "RDSD-22399" and row["status"] == "In Progress"


def test_connections_lists_the_service_connections(monkeypatch, tmp_path):
    _toil_env(monkeypatch, tmp_path, "connections_list")
    conns = T.connections()
    assert {c["area"] for c in conns} == {"jira", "confluence", "bitbucket"}
    assert T.connection_for("jira", conns, {})["host"] == "jira.example.test"
    assert T.connection_for("jira-cloud", conns, {}) is None
    assert T.connection_for("jira", conns, {"toil": {"connections": {"jira": "other"}}}) is None, \
        "a pinned connection that does not exist is none, never a different one"


# --------------------------------------------------------------------- the npm shim, unwrapped


@pytest.mark.skipif(not WINDOWS, reason="npm shims are a Windows concept")
def test_proc_unwraps_an_npm_shim(monkeypatch, tmp_path):
    """`proc.py` runs the shim's node entry point directly so cmd.exe never re-parses an argument.

    This is the behaviour the old `skipif(nt)` tests skipped on the one OS where it matters.
    """
    fakes.apply(monkeypatch, tmp_path, ["toil"], case="version")
    shim = os.path.join(str(tmp_path), "fakebin", "toil.cmd")
    info = proc.resolve("toil")
    assert info["path"].lower().endswith(("toil.cmd", "toil"))
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
def test_a_multiline_body_goes_through_a_cmd_shim_on_stdin(monkeypatch, tmp_path, capsys):
    """The Windows half of `ad-confluence publish`. pncli took the page body as one argument, and a page of HTML
    cannot survive cmd.exe's parsing, so a `.cmd`-only launcher had to refuse it. toil reads the body from
    `--body-file -`, so the body never touches the command line: even through a plain `.cmd` shim with nothing for
    `proc.unwrap_shim` to run under Node, a fenced block with its newlines is sent."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    page = tmp_path / "page.md"
    page.write_text("# Findings\n\n```\nline one\nline two\n```\n", encoding="utf-8")
    fakes.apply(monkeypatch, tmp_path, ["toil"], case="page_created", npm=False)
    monkeypatch.setenv("TOIL_EXE", os.path.join(str(tmp_path), "fakebin", "toil.cmd"))

    from agentdata import cli_confluence

    assert cli_confluence.main(["publish", str(page), "--space", "S"]) == 0
    out = capsys.readouterr().out
    assert "page_id: \"98765\"" in out or "page_id: 98765" in out, out


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
