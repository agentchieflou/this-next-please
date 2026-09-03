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


def test_every_console_script_is_also_a_module_command():
    scripts = _scripts()
    assert len(scripts) >= 14
    for name in scripts:
        assert name[3:] in M.COMMANDS, f"{name} has no `python -m agentdata {name[3:]}` form"
    for name, (module, func, help_text) in M.COMMANDS.items():
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
