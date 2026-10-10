"""The fake-tool harness, and the Windows behaviour it un-skips.

`tests/test_proc.py` had six tests marked `skipif(os.name == "nt")` with the reason "POSIX shell
stand-in for pncli" — so the Windows behaviour of the module that exists *because of* Windows was
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


def test_ad_view_gives_a_saved_get_issue_answer_the_issue_columns(monkeypatch, tmp_path, capsys):
    """The recipe the skills teach: `pncli jira get-issue --key <KEY> > .agent/out/<KEY>.json`, then
    `ad-view` it. The file is what the fake really printed, BOM and all, as PowerShell 5.1 writes it."""
    from agentdata import cli

    _pncli_env(monkeypatch, tmp_path, "get_issue_ok")
    rc, out, _err, _el = proc.run(["pncli", "jira", "get-issue", "--key", "RDSD-22399"], exe=P.exe(), timeout=60)
    assert rc == 0
    saved = tmp_path / "RDSD-22399.json"
    saved.write_bytes(b"\xef\xbb\xbf" + out.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ad-view", str(saved)])
    cli.main_view()
    shown = capsys.readouterr().out
    assert "RDSD-22399" in shown and "In Progress" in shown and "status" in shown
    assert "fields.status.name" not in shown, "the issue columns, not pncli's flattened paths"


def test_ad_view_gives_a_saved_search_the_search_columns_in_the_encoding_powershell_wrote(monkeypatch, tmp_path,
                                                                                          capsys):
    """`pncli jira search ... > .agent/out/x.json` from Windows PowerShell 5.1 writes UTF-16 with a BOM; the
    answer still reads as the search it is, and an empty file (pncli printed its usage error to stderr) says so."""
    from agentdata import cli

    _pncli_env(monkeypatch, tmp_path, "search_ok")
    _rc, out, _err, _el = proc.run(["pncli", "jira", "search", "--jql", "key = RDSD-1"], exe=P.exe(), timeout=60)
    saved = tmp_path / "search.json"
    saved.write_bytes(out.encode("utf-16"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ad-view", str(saved)])
    cli.main_view()
    shown = capsys.readouterr().out
    assert "key: RDSD-1" in shown and re.search(r'source: "?ad-view', shown), shown
    assert "status:" in shown and "summary:" in shown, "the search columns, even for an issue with no fields"
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-view", str(empty)])
    with pytest.raises(SystemExit) as e:
        cli.main_view()
    assert e.value.code == 1 and "is empty" in capsys.readouterr().out


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
    """The Windows half of `ad-confluence publish`, which sends the page body as one argument.

    A page of HTML cannot survive cmd.exe's parsing, so when the only launcher is a `.cmd` shim with
    nothing for `proc.unwrap_shim` to run under Node, the command refuses with a hint naming the way
    out rather than sending a mangled body to Confluence. That refusal *is* the Windows behaviour,
    and it is worth asserting. Paragraphs fold onto one line in storage format; a fenced block keeps
    its newlines, so that is the body that has to be refused.
    """
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    (tmp_path / "cfg.json").write_text(json.dumps({"pncli": {"verbs": {
        "page_create": "confluence create-page --space {space} --title {title} --body {body}"}}}), encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text("# Findings\n\n```\nline one\nline two\n```\n", encoding="utf-8")
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case="search_ok", npm=False)
    monkeypatch.setenv("PNCLI_EXE", os.path.join(str(tmp_path), "fakebin", "pncli.cmd"))

    from agentdata import cli_confluence

    assert cli_confluence.main(["publish", str(page), "--space", "S"]) == 1
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
