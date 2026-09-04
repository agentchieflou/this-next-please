"""The seams between what is installed, what is dispatched, and what the docs tell people to run.

Every bug this file guards was shipped at least once: a skill naming a command the CLI did not have, and
`python -m agentdata <cmd>` reporting a refusal as success."""
import os
import re
import sys

import pytest

from agentdata import __main__ as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scripts() -> dict:
    body = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read().split("[project.scripts]", 1)[1]
    body = body.split("\n[", 1)[0]
    return dict(re.findall(r'^(ad-[\w-]+) = "([\w.:]+)"', body, re.M))


def test_module_form_propagates_the_commands_exit_code(monkeypatch, capsys):
    """`python -m agentdata dpm …` is documented as identical to `ad-dpm …`; exit codes are the contract."""
    calls = []
    mod = type(sys)("fake_cmd")
    mod.main = lambda: (calls.append(sys.argv), 2)[1]
    monkeypatch.setitem(sys.modules, "fake_cmd", mod)
    monkeypatch.setitem(M.COMMANDS, "fake", ("fake_cmd", "main", "fake"))
    assert M.main(["fake", "--run-root", "/nope"]) == 2
    assert calls == [["ad-fake", "--run-root", "/nope"]]
    mod.main = lambda: None                       # older commands sys.exit() themselves and return None
    assert M.main(["fake"]) == 0
    mod.main = lambda: 1
    assert M.main(["ad-fake"]) == 1               # the `ad-` prefix is tolerated
    assert M.main(["nope"]) == 2 and "unknown command" in capsys.readouterr().err


# The one exemption from "every command is both a script and a module form", and it has to be
# explicit so a real command cannot become script-less by accident. `_complete` is called by a shell
# on a keypress, through the interpreter path baked into the generated script -- never typed, and a
# `Scripts` entry for it would be one more name on PATH that means nothing to a person.
MODULE_ONLY = {"_complete"}


def test_a_module_only_command_is_hidden_and_unspeakable():
    """If it is not in the catalog and has no script, nothing should invite a person to type it."""
    for name in MODULE_ONLY:
        assert name in M.COMMANDS, f"{name} is exempted but is not a command"
        assert name in M.HIDDEN, f"{name} has no console script, so it must not be in the catalog"
        assert name.startswith("_"), f"{name} reads like something to type"


def test_every_console_script_is_also_a_module_command():
    scripts = _scripts()
    assert len(scripts) >= 14
    for name in scripts:
        assert name[3:] in M.COMMANDS, f"{name} has no `python -m agentdata {name[3:]}` form"
    for name, (module, func, help_text) in M.COMMANDS.items():
        if name in MODULE_ONLY:
            assert f"ad-{name}" not in scripts, f"ad-{name} is listed as module-only but has a script"
            assert help_text, f"{name} has no help text"
            continue
        assert scripts.get(f"ad-{name}"), f"python -m agentdata {name} has no ad-{name} console script"
        assert scripts[f"ad-{name}"] == f"{module}:{func}", f"ad-{name} and the module form call different functions"
        assert help_text, f"{name} has no help text"


@pytest.mark.parametrize("where", ["skills", "docs", "."])
def test_docs_only_mention_commands_that_exist(where):
    """A skill telling Luna to run a command that does not exist is a dead end she cannot diagnose."""
    known = {n[3:] for n in _scripts()}
    files = []
    base = os.path.join(ROOT, where)
    for dirpath, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "build", "__pycache__", "skills", "docs", "tests", "agentdata", "prompts")]
        files += [os.path.join(dirpath, n) for n in names if n.endswith(".md")]
    assert files, f"no markdown under {where}"
    bad = []
    for f in files:
        text = open(f, encoding="utf-8").read()
        for cmd in re.findall(r"`?\bad-([a-z][\w-]*)", text):
            if cmd not in known and cmd not in {"hoc", "hoc-"}:
                bad.append(f"{os.path.relpath(f, ROOT)}: ad-{cmd}")
        for cmd in re.findall(r"python -m agentdata ([a-z][\w-]*)", text):
            if cmd not in M.COMMANDS and cmd not in {"--help"}:
                bad.append(f"{os.path.relpath(f, ROOT)}: python -m agentdata {cmd}")
    assert bad == [], "commands referenced but not installed: " + "; ".join(sorted(set(bad)))


def test_every_script_and_module_supports_version(capsys):
    import importlib
    from agentdata.version import version_string
    expected = version_string()
    assert expected.startswith("agentdata ")

    scripts = _scripts()
    for name, target in scripts.items():
        mod_name, func_name = target.split(":")
        mod = importlib.import_module(mod_name)
        func = getattr(mod, func_name)
        rc = None
        try:
            try:
                rc = func(["--version"])
            except TypeError:
                old_argv = sys.argv
                sys.argv = [name, "--version"]
                try:
                    rc = func()
                finally:
                    sys.argv = old_argv
        except SystemExit as exc:
            rc = exc.code
        assert rc in (0, None), f"{name} --version exited with {rc}"
        out = capsys.readouterr().out.strip()
        assert expected in out, f"{name} --version gave {out!r}, expected {expected!r}"

    # Module form --version and -v
    assert M.main(["--version"]) == 0
    assert expected in capsys.readouterr().out.strip()
    assert M.main(["-v"]) == 0
    assert expected in capsys.readouterr().out.strip()


def test_ad_help(capsys):
    from agentdata import cli_help

    # No args: prints catalog
    assert cli_help.main([]) == 0
    out = capsys.readouterr().out
    assert "usage: python -m agentdata" in out or "agentdata" in out
    assert "ad-pbip" in out and "ad-jira" in out

    # Command help
    assert cli_help.main(["pbip"]) == 0
    out = capsys.readouterr().out
    assert "ad-pbip" in out

    # Command help with ad- prefix
    assert cli_help.main(["ad-jira"]) == 0
    out = capsys.readouterr().out
    assert "ad-jira" in out

    # Command help for pbi
    assert cli_help.main(["pbi"]) == 0
    out = capsys.readouterr().out
    assert "ad-pbi" in out

    # Misspelled command: suggestions
    assert cli_help.main(["pbix"]) == 2
    err = capsys.readouterr().err
    assert "Did you mean" in err and ("ad-pbip" in err or "ad-pbi" in err)

    # Completely unknown command
    assert cli_help.main(["nonexistentcommand12345"]) == 2
    err = capsys.readouterr().err
    assert "unknown command 'nonexistentcommand12345'" in err

