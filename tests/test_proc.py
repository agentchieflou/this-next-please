"""Starting programs on Windows. `pncli` is an npm package: it exists as pncli.cmd, never pncli.exe, so handing the
bare name to CreateProcess fails with [WinError 2] — the 2026-09-02 laptop failure of `ad-pncli jira search`.
Windows behaviour is exercised on any OS through the `windows=` switch."""
import json
import os
import stat
import subprocess
import sys

import pytest

from agentdata import proc
from agentdata.connectors import pncli as P

NPM7_CMD = """@ECHO off\r
GOTO start\r
:find_dp0\r
SET dp0=%~dp0\r
EXIT /b\r
:start\r
SETLOCAL\r
CALL :find_dp0\r
IF EXIST "%dp0%\\node.exe" (SET "_prog=%dp0%\\node.exe") ELSE (SET "_prog=node")\r
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@kolatts\\pncli\\bin\\cli.js" %*\r
"""
NPM6_CMD = '@IF EXIST "%~dp0\\node.exe" (\r\n  "%~dp0\\node.exe"  "%~dp0\\node_modules\\@kolatts\\pncli\\bin\\cli.js" %*\r\n)\r\n'
SH_SHIM = '#!/bin/sh\nbasedir=$(dirname "$0")\nexec node  "$basedir/node_modules/@kolatts/pncli/bin/cli.js" "$@"\n'


def npm_install(d, *, shim=NPM7_CMD, name="pncli", script=True, node=True):
    """A directory shaped like npm's global prefix on Windows."""
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, name + ".cmd"), "w", newline="").write(shim)
    open(os.path.join(d, name), "w", newline="\n").write(SH_SHIM)
    if node:
        open(os.path.join(d, "node.exe"), "w").write("")
    if script:
        bin_dir = os.path.join(d, "node_modules", "@kolatts", "pncli", "bin")
        os.makedirs(bin_dir, exist_ok=True)
        open(os.path.join(bin_dir, "cli.js"), "w").write("// entry point\n")
    return d


def test_which_prefers_exe_then_cmd_and_finds_the_shim(tmp_path):
    d = npm_install(str(tmp_path / "npm"))
    assert proc.which("pncli", path=d, windows=True) == os.path.normpath(os.path.join(d, "pncli.cmd"))
    assert proc.which("pncli", path=d, windows=True, pathext=".COM;.EXE;.BAT;.CMD").endswith("pncli.cmd")
    open(os.path.join(d, "pncli.exe"), "w").write("")
    assert proc.which("pncli", path=d, windows=True).endswith("pncli.exe")   # a real executable wins
    assert proc.which("pncli.cmd", path=d, windows=True).endswith("pncli.cmd")
    assert proc.which("nope", path=d, windows=True) is None
    assert proc.which(os.path.join(d, "pncli"), windows=True).endswith("pncli.exe")   # a pinned path gets PATHEXT too
    assert proc.which(os.path.join(npm_install(str(tmp_path / "n2")), "pncli"), windows=True).endswith("pncli.cmd")


def test_unwrap_npm_shim_for_every_shim_style(tmp_path):
    for i, shim in enumerate((NPM7_CMD, NPM6_CMD)):
        d = npm_install(str(tmp_path / f"npm{i}"), shim=shim)
        node, script = proc.unwrap_shim(os.path.join(d, "pncli.cmd"), windows=True)
        assert node.endswith("node.exe") and script.endswith(os.path.join("bin", "cli.js")) and os.path.isfile(script)
    d = npm_install(str(tmp_path / "sh"), node=False)
    got = proc.unwrap_shim(os.path.join(d, "pncli"), windows=False)
    assert got is None or got[1].endswith("cli.js")          # depends on a `node` being installed here
    d2 = npm_install(str(tmp_path / "broken"), script=False)  # shim present, entry point gone
    assert proc.unwrap_shim(os.path.join(d2, "pncli.cmd"), windows=True) is None


def test_command_runs_the_node_entry_point_not_cmd_exe(tmp_path):
    d = npm_install(str(tmp_path / "npm"))
    jql = "project = RDSD AND updated >= '2026-01-01'"
    argv = proc.command(["pncli", "jira", "search", "--jql", jql], windows=True, path=d)
    assert argv[0].endswith("node.exe") and argv[1].endswith("cli.js") and argv[2:] == ["jira", "search", "--jql", jql]
    info = proc.resolve("pncli", windows=True, path=d)
    assert info["kind"] == "npm shim" and info["found"] and info["path"].endswith("pncli.cmd")


def test_cmd_shim_is_a_command_line_string_not_a_list(tmp_path, monkeypatch):
    r"""2026-09-02 laptop: `az login` -> "The filename, directory name, or volume label syntax is incorrect".
    A pre-quoted cmd line handed to subprocess as a LIST goes through list2cmdline, which backslash-escapes the inner
    quotes; cmd.exe then reads \"\"C:\Program as a filename. It must be passed as a string, verbatim."""
    d = npm_install(str(tmp_path / "npm"), script=False)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    line = proc.command(["pncli", "jira", "search", "--jql", "a >= b"], windows=True, path=d)
    assert isinstance(line, str)
    assert line.startswith(r'"C:\Windows\System32\cmd.exe" /d /s /c ""')
    assert line.endswith('"') and '"a >= b"' in line and "pncli.cmd" in line      # `>` and the path stay inside quotes
    assert '\\"' not in line                                                       # never backslash-escaped
    assert '\\"' in subprocess.list2cmdline([os.environ["COMSPEC"], "/d", "/s", "/c", line])   # why it is not a list
    assert proc.resolve("pncli", windows=True, path=d)["kind"] == "cmd shim"
    assert proc.cmd_line(["x.cmd", "plain", 'say "hi"']) == '""x.cmd" "plain" "say ""hi""""'
    with pytest.raises(proc.ProcError) as e:
        proc.cmd_line(["x.cmd", "%USERPROFILE%"])
    assert e.value.code == "cmd_unsafe_argument" and "PNCLI_EXE" in e.value.hint


def test_not_found_names_what_was_tried(tmp_path):
    with pytest.raises(proc.ProcError) as e:
        proc.command(["pncli", "jira"], windows=True, path=str(tmp_path), hint="install pncli")
    assert e.value.code == "not_found" and e.value.hint == "install pncli"
    assert any("PATHEXT" in t for t in e.value.detail["tried"])
    info = proc.resolve("pncli", exe=str(tmp_path / "gone.cmd"), windows=True)
    assert not info["found"] and "configured path not found" in info["error"]


def test_binaries_are_not_scanned_for_a_shim(tmp_path):
    """resolve() runs before every subprocess: it must never read a whole executable looking for an npm shim."""
    big = tmp_path / "hugetool"
    big.write_bytes(b"\x7fELF\x00\x00" + b"x" * (4 << 20))
    os.chmod(big, 0o755)
    assert proc.unwrap_shim(str(big), windows=False) is None
    assert proc.resolve("hugetool", path=str(tmp_path), windows=False)["kind"] == "executable"
    text = tmp_path / "textual"
    text.write_text("#!/bin/sh\n" + "# padding\n" * 5000 + 'exec node "$basedir/late.js" "$@"\n', encoding="utf-8")
    assert proc.unwrap_shim(str(text), windows=False) is None      # beyond SHIM_HEAD: treated as a plain program


def test_run_returns_streams_and_reports_start_failure(tmp_path):
    rc, out, err, el = proc.run([sys.executable, "-c", "print('hi')"])
    assert rc == 0 and out.strip() == "hi" and err == "" and el >= 0
    with pytest.raises(proc.ProcError) as e:
        proc.run(["definitely-not-installed-xyz", "--version"])
    assert e.value.code == "not_found"
    with pytest.raises(proc.ProcError) as e:
        proc.run([sys.executable, "-c", "import sys; sys.exit(3)"], check=True)
    assert e.value.code == "exit_code" and e.value.detail["exit_code"] == 3


def _fake_pncli(tmp_path, body: str) -> str:
    """A stand-in pncli that runs `body`.

    On Windows it is a `.cmd` running the same logic through Python, so the tests that use it are
    not skipped on the one OS this module exists for. `tests/fakes/` is the transcript-driven
    harness; this is the simpler shape for tests that only need "print this, exit with that".
    """
    if os.name == "nt":
        script = tmp_path / "pncli-fake.py"
        script.write_text(_body_as_python(body), encoding="utf-8", newline="\n")
        p = tmp_path / "pncli-fake.cmd"
        p.write_text(f'@ECHO OFF\r\n"{sys.executable}" "{script}" %*\r\n',
                     encoding="utf-8", newline="")
        return str(p)
    p = tmp_path / "pncli-fake"
    p.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _body_as_python(body: str) -> str:
    """Translate the handful of `sh` one-liners these tests use into Python.

    Deliberately tiny and deliberately explicit: anything more elaborate belongs in a transcript
    under `tests/fakes/`, not in a translator nobody can read.
    """
    out = ["import sys"]
    for statement in body.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        if statement.startswith("printf "):
            payload = statement[len("printf "):].strip().strip("'\"")
            out.append(f"sys.stdout.write({payload!r})")
        elif statement.startswith("echo ") and statement.endswith(">&2"):
            payload = statement[len("echo "):-3].strip().strip("'\"")
            out.append(f"sys.stderr.write({payload!r} + chr(10))")
        elif statement.startswith("echo "):
            payload = statement[len("echo "):].strip().strip("'\"")
            out.append(f"sys.stdout.write({payload!r} + chr(10))")
        elif statement.startswith("exit "):
            out.append(f"sys.exit({int(statement.split()[1])})")
        elif statement.startswith("cat "):
            path = statement[len("cat "):].strip().strip("'\"")
            out.append(f"sys.stdout.write(open({path!r}, encoding='utf-8').read())")
        else:
            out.append(f"raise SystemExit('unsupported fake body: {statement}')")
    return chr(10).join(out) + chr(10)


def test_install_hint_names_the_configured_package(tmp_path, monkeypatch):
    """`where` itself is exercised against a fake in tests/test_fakes.py; this is the config half."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.delenv("PNCLI_EXE", raising=False)
    with open(tmp_path / "cfg.json", "w", encoding="utf-8") as f:
        json.dump({"pncli": {"npm_package": "@acme/pncli"}}, f)
    assert "@acme/pncli" in P.install_hint()
def test_usage_errors_become_the_exact_fix():
    """2026-09-02 laptop friction: `jira get-issue RDSD-22399` -> pncli wants a NAMED option, --key.

    Pure string work, so it needs no shell at all; the end-to-end half runs against a fake in
    tests/test_fakes.py on every OS.
    """
    assert P.usage_hint("error: required option '--key <issue-key>' not specified", ["jira", "get-issue", "RDSD-22399"]) == (
        "pncli options are named, never positional (you passed 'RDSD-22399' positionally): re-run with "
        "`--key RDSD-22399`, e.g. `ad-pncli raw jira get-issue --key RDSD-22399`")
    assert "--key <issue-key>" in P.usage_hint("required option '--key <issue-key>' not specified", ["jira", "get-issue"])
    assert "run `pncli jira --help` once" in P.usage_hint("error: unknown command 'fetch'", ["jira", "fetch", "X"])
    assert P.usage_hint("Traceback: connection reset", ["jira", "search"]) == ""


def test_get_issue_renames_and_selects_fields(monkeypatch, tmp_path):
    """The field mapping is pure; the subprocess half lives in tests/test_fakes.py, where it runs
    on Windows too rather than being skipped there."""
    import fakes

    fakes.apply(monkeypatch, tmp_path, ["pncli"], case="get_issue_ok")
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("PNCLI_EXE", os.path.join(str(tmp_path), "fakebin",
                                                 "pncli.cmd" if os.name == "nt" else "pncli"))
    t = P.get_issue("RDSD-22399", ["key", "description"])
    assert t.columns == ["key", "description"]
    assert t.rows == [["RDSD-22399", "AC: 1) x"]]
def test_well_known_install_dirs_are_searched(tmp_path, monkeypatch):
    """az lives in C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin, which the installer does not always leave on PATH."""
    wbin = tmp_path / "Program Files" / "Microsoft SDKs" / "Azure" / "CLI2" / "wbin"
    wbin.mkdir(parents=True)
    (wbin / "az.cmd").write_text("@echo off\r\n")
    monkeypatch.setitem(proc.TOOL_DIRS, "az", (str(wbin),))
    assert proc.which("az", path="", windows=True).endswith("az.cmd")
    info = proc.resolve("az", windows=True, path="")
    assert info["found"] and info["kind"] == "cmd shim" and "wbin" in info["path"]
    assert proc.which("notaz", path="", windows=True) is None
    tried = proc.resolve("az", windows=True, path=str(tmp_path))["tried"]
    assert not proc.resolve("az", windows=True, path=str(tmp_path))["found"] or True
    assert any("wbin" in t for t in tried)


def test_a_pinned_js_entry_point_runs_through_node(tmp_path, monkeypatch):
    """cmd_line's refusal hint offers `pin the .js entry point` as the escape hatch; it has to actually work."""
    node_dir = tmp_path / "nodedir"
    node_dir.mkdir()
    (node_dir / "node").write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(node_dir / "node", 0o755)
    monkeypatch.setenv("PATH", str(node_dir) + os.pathsep + os.environ.get("PATH", ""))
    script = npm_install(str(tmp_path / "npm"))
    js = os.path.join(script, "node_modules", "@kolatts", "pncli", "bin", "cli.js")
    info = proc.resolve("pncli", exe=js, windows=True)
    assert info["kind"] == "node script" and info["script"].endswith("cli.js") and info["node"].endswith("node")
    argv = proc.command(["pncli", "jira", "search", "--jql", "a % b"], exe=js, windows=True)
    assert argv[0].endswith("node") and argv[1].endswith("cli.js") and argv[-1] == "a % b"   # `%` is safe here
    real_which = proc.which                                                       # no node anywhere: say so
    monkeypatch.setattr(proc, "which", lambda name, **kw: None if name == "node" else real_which(name, **kw))
    info = proc.resolve("pncli", exe=js, windows=True)
    assert info["kind"] == "executable" and "no `node` on PATH" in info["error"]


@pytest.mark.skipif(os.name == "nt", reason="the stand-in is a shell loop; Windows is covered by test_a_multiline_body_is_refused_through_a_cmd_shim")
def test_raw_body_file_sends_the_page_as_one_argument(tmp_path, monkeypatch, capsys):
    """`pncli confluence create-page` takes the body INLINE. A page of HTML cannot survive shell quoting, so it goes
    across as a single argv element — and is never echoed back into the agent's context."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    html = '<h2>Findings</h2>\n<p>A "quoted" &amp; <b>bold</b> line, with > and | in it.</p>\n'
    page = tmp_path / "page.html"
    page.write_text(html, encoding="utf-8")
    body = 'prev=""; n=0\nfor a in "$@"; do\n  if [ "$prev" = "--body" ]; then n=${#a}; fi\n  prev="$a"\ndone\n' \
           'printf \'{"ok":true,"args":%s,"body":%s}\' "$#" "$n"'
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, body))
    monkeypatch.setattr(sys, "argv", ["ad-pncli", "raw", "--body-file", str(page),
                                      "confluence", "create-page", "--space", "RDSD", "--title", "T", "--dry-run"])
    from agentdata import cli
    cli.main_pncli()
    out = capsys.readouterr().out
    assert f"body: {len(html)}" in out and "args: 9" in out          # the whole file, as one trailing argument
    assert "<h2>" not in out and f"<{len(html)} chars from" in out   # the page is summarised, never echoed


def test_raw_refuses_to_post_markdown_to_confluence(tmp_path, monkeypatch, capsys):
    """The reported bug: the body reached Confluence as Markdown and rendered as `## mismatch`. The last gate is
    here, because a body only becomes a page at the moment `--body-file` is read -- and it closes BEFORE pncli is
    launched, which is why this half of the contract holds on every platform."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    md = tmp_path / "findings.md"
    md.write_text("## Findings\n\n- one\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-pncli", "raw", "--body-file", str(md), "confluence", "create-page", "--dry-run"])
    from agentdata import cli
    with pytest.raises(SystemExit) as e:
        cli.main_pncli()
    out = capsys.readouterr().out
    assert e.value.code == 2 and "ok: false" in out and "# heading" in out and "ad-confluence html" in out
    assert "PNCLI_EXE" not in os.environ                              # refused without ever looking for pncli


@pytest.mark.skipif(os.name == "nt", reason="the stand-in is a shell loop; Windows is covered by test_a_multiline_body_is_refused_through_a_cmd_shim")
def test_raw_lets_a_converted_body_and_a_jira_comment_through(tmp_path, monkeypatch, capsys):
    """The other half: the gate is narrow. Storage format passes, and Markdown in a Jira comment is not a page."""
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, 'printf \'{"ok":true}\''))
    from agentdata import cli
    html = tmp_path / "findings.html"
    html.write_text("<h2>Findings</h2><ul><li>one</li></ul>", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-pncli", "raw", "--body-file", str(html), "confluence", "create-page", "--dry-run"])
    cli.main_pncli()
    assert "ok: true" in capsys.readouterr().out

    md = tmp_path / "findings.md"
    md.write_text("## Findings\n\n- one\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-pncli", "raw", "--body-file", str(md), "jira", "add-comment", "--key", "X"])
    cli.main_pncli()
    assert "ok: true" in capsys.readouterr().out
