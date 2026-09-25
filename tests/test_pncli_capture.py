"""`ad-pncli capture-help` (#498): every `pncli --help` the PR and page commands need, in one redacted file.

The Bitbucket PR verb and the Confluence page options wait on the laptop's pncli help (WRAP-D6), and
the fakes replay only real output. This command turns a dozen hand-copied outputs into one file the
operator reads and attaches. This repository is public, so the company's hosts and the operator's
home directory never reach the file.
"""
from __future__ import annotations
import json
import os
import sys

import pytest

import fakes
from agentdata.connectors import pncli as P


def _home(tmp_path, monkeypatch) -> str:
    home = str(tmp_path / "home" / "luna")
    os.makedirs(home, exist_ok=True)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    return home


def _no_fleet(monkeypatch) -> None:
    monkeypatch.delenv("AGENTDATA_FLEET_AGENT", raising=False)
    monkeypatch.delenv("AGENTDATA_FLEET_DIR", raising=False)


def _capture(monkeypatch, *args: str) -> int:
    from agentdata import cli
    monkeypatch.setattr(sys, "argv", ["ad-pncli", "capture-help", *args])
    try:
        cli.main_pncli()
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_help_is_never_a_write_whatever_the_verb():
    """commander.js prints help and exits before any action runs, so `--help` and `-h` are reads."""
    assert P.is_write(["bitbucket", "create-pr", "--help"]) is False
    assert P.is_write(["bitbucket", "--help"]) is False
    assert P.is_write(["confluence", "create-page", "-h"]) is False
    assert P.is_write(["bitbucket", "create-pr"]) is True
    assert P.is_write(["bitbucket"]) is True


# commander.js's own README, the Quick Start's `string-util` example:
# https://github.com/tj/commander.js/blob/master/Readme.md#quick-start (example file:
# https://github.com/tj/commander.js/blob/master/examples/string-util.js). The README shows the subcommand's
# help verbatim; the program's own `--help` is the same program in the layout commander.js documents for
# "a program with subcommands" (https://github.com/tj/commander.js/blob/master/docs/help-in-depth.md).
README_HELP_SPLIT = """Usage: string-util split [options] <string>

Split a string into substrings and display as an array.

Arguments:
  string                  string to split

Options:
  --first                 display just the first substring
  -s, --separator <char>  separator character (default: ",")
  -h, --help              display help for command
"""

README_PROGRAM_HELP = """Usage: string-util [options] [command]

CLI to some JavaScript string utilities

Options:
  -V, --version             output the version number
  -h, --help                display help for command

Commands:
  split [options] <string>  Split a string into substrings and display as an array.
  help [command]            display help for command
"""


def test_the_commands_parser_reads_commander_js_help():
    assert P.help_commands(README_PROGRAM_HELP) == ["split"]          # not `help`, nothing from Options:
    assert P.help_commands(README_HELP_SPLIT) == []                   # a leaf command lists none
    grouped = README_PROGRAM_HELP.replace("  help [command]", "  join [options] <strings...>  Join them\n  help [command]")
    assert P.help_commands(grouped + "\nManagement Commands:\n  prune|p  Remove unused\n\nExamples:\n  x\n") == \
        ["split", "join", "prune"]


def test_capture_help_replays_the_fake_and_records_every_call(tmp_path, monkeypatch, capsys):
    _no_fleet(monkeypatch)
    _home(tmp_path, monkeypatch)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg" / "config.json"))
    monkeypatch.delenv("PNCLI_EXE", raising=False)
    fakes.apply(monkeypatch, tmp_path, ["pncli"])
    out_file = tmp_path / "help.txt"
    code = _capture(monkeypatch, "--out", str(out_file))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "captured: 1" in out and "failed: 4" in out                 # --version answered; the four helps exit 99
    text = out_file.read_text(encoding="utf-8")
    headers = [line for line in text.splitlines() if line.startswith("==== pncli ")]
    assert len(headers) == 5, headers
    assert headers[0].startswith("==== pncli --version") and "exit 0" in headers[0]
    assert "pncli/1.4.0" in text                                       # replayed from its real transcript
    for product in ("bitbucket", "confluence", "jira"):
        line = next(h for h in headers if h.startswith(f"==== pncli {product} --help"))
        assert "exit 99" in line, line
    argvs = fakes.calls({"AGENTDATA_FAKE_LOG": os.environ["AGENTDATA_FAKE_LOG"]}, "pncli")
    assert all(a[-1] == "--help" for a in argvs if a[-1] != "--version")   # nothing but help is ever run


def test_the_default_file_sits_beside_the_config_and_names_the_version(tmp_path, monkeypatch, capsys):
    _no_fleet(monkeypatch)
    _home(tmp_path, monkeypatch)
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("AGENTDATA_CONFIG", str(cfg_dir / "config.json"))
    monkeypatch.delenv("PNCLI_EXE", raising=False)
    fakes.apply(monkeypatch, tmp_path, ["pncli"])
    assert _capture(monkeypatch) == 0
    made = [n for n in os.listdir(cfg_dir) if n.startswith("pncli-help-1.4.0-") and n.endswith(".txt")]
    assert len(made) == 1, os.listdir(cfg_dir)
    assert "read it, then attach it" in capsys.readouterr().out


def test_hosts_and_the_home_directory_are_redacted(tmp_path, monkeypatch, capsys):
    _no_fleet(monkeypatch)
    home = _home(tmp_path, monkeypatch)
    cfg = tmp_path / "cfg" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"version": 1, "jira": {"base_url": "https://jira.example.test"}}), encoding="utf-8")
    monkeypatch.setenv("AGENTDATA_CONFIG", str(cfg))
    monkeypatch.setenv("PNCLI_EXE", "pncli")
    seen: list[list[str]] = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        tail = argv[1:]
        if tail == ["--version"]:
            return 0, "1.4.0\n", "", 0.01
        if tail == ["bitbucket", "--help"]:
            return 0, ("Usage: pncli bitbucket [options] [command]\n\nCommands:\n"
                       "  create-pr [options]  Create a PR on https://git.corp.example/projects\n"
                       "  help [command]       display help for command\n"), "", 0.01
        return 0, f"config: {home}{os.sep}.pncli{os.sep}config.json\nbase: https://jira.example.test/rest/api/2\n", "", 0.01

    from agentdata import proc
    monkeypatch.setattr(proc, "run", fake_run)
    out_file = tmp_path / "help.txt"
    assert _capture(monkeypatch, "--out", str(out_file)) == 0
    text = out_file.read_text(encoding="utf-8")
    assert "<jira-host>" in text and "<home>" in text and "<host>" in text
    assert "jira.example.test" not in text and home not in text and "git.corp.example" not in text
    assert ["pncli", "bitbucket", "create-pr", "--help"] in seen      # the verb under Commands: is walked
    assert all(a[-1] in ("--help", "--version") for a in seen)
    assert any(line.startswith("# redacted:") for line in text.splitlines()[:6])     # the header says what
    assert "redacted: " in capsys.readouterr().out


def test_capture_help_is_the_operators_and_refuses_inside_a_fleet(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTDATA_FLEET_AGENT", "luna")
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setenv("AGENTDATA_CONFIG", str(cfg_dir / "config.json"))
    out_file = tmp_path / "help.txt"
    assert _capture(monkeypatch, "--out", str(out_file)) == 2
    out = capsys.readouterr().out
    assert "operator_only" in out and "your own terminal" in out
    assert not out_file.exists() and os.listdir(cfg_dir) == []
