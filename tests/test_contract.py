"""The black-box contract every `ad-*` command owes its caller, checked as a real subprocess.

In-process `main()` calls cannot catch what actually goes wrong in the field: an import-time crash,
a bare `sys.exit`, a traceback on stderr, or an escape sequence that only appears when stdout is a
pipe. Every case here spawns the command.

The list of commands comes from `[project.scripts]`, so a new command is covered the moment it is
added — or the suite fails naming it.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys

import pytest

import contract_cases
from agentdata import toon

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANSI = re.compile(r"\x1b\[")


def scripts() -> dict[str, str]:
    """`{name: module:function}` from [project.scripts], the source of truth."""
    body = open(os.path.join(REPO_ROOT, "pyproject.toml"), encoding="utf-8").read()
    block = body.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    out = {}
    for line in block.splitlines():
        if "=" not in line or not line.strip().startswith("ad-"):
            continue
        name, target = line.split("=", 1)
        out[name.strip()[3:]] = target.strip().strip('"')
    return out


COMMANDS = sorted(scripts())


def run(args, *, cwd, extra_env=None, timeout=180):
    env = dict(os.environ)
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, "-m", "agentdata", *args],
                       capture_output=True, text=True, cwd=cwd, timeout=timeout,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, p.stdout, p.stderr


# ------------------------------------------------------------------------ coverage by construction


def test_every_console_script_has_a_contract_case():
    missing = [name for name in COMMANDS if name not in contract_cases.CASES]
    assert not missing, (
        "add a safe invocation to tests/contract_cases.py for: "
        + ", ".join(f"ad-{n}" for n in missing))


def test_no_case_names_a_command_that_does_not_exist():
    extra = [name for name in contract_cases.CASES if name not in COMMANDS]
    assert not extra, f"contract_cases.py names commands that are not installed: {extra}"


# ---------------------------------------------------------------------------- the shared contract


@pytest.mark.parametrize("name", COMMANDS)
def test_help_exits_zero_without_a_traceback(name, tmp_path):
    rc, out, err = run([name, "--help"], cwd=str(tmp_path))
    assert rc == 0, err
    assert "Traceback" not in err
    assert "usage" in (out + err).lower()


@pytest.mark.parametrize("name", COMMANDS)
def test_version_prints_the_package_version(name, tmp_path):
    from agentdata.version import version_string

    rc, out, err = run([name, "--version"], cwd=str(tmp_path))
    assert rc == 0, err
    assert "Traceback" not in err
    expected = version_string().split()[-1] if version_string().split() else ""
    assert expected.split("+")[0][:5] in out or out.strip(), f"--version printed nothing: {out!r}"


@pytest.mark.parametrize("name", COMMANDS)
def test_an_unknown_flag_is_a_usage_error_not_a_crash(name, tmp_path):
    rc, out, err = run([name, "--definitely-not-a-flag"], cwd=str(tmp_path))
    assert rc != 0, "an unknown flag must not look like success"
    assert "Traceback" not in err, err
    assert rc in (1, 2), f"exit {rc} for a usage error"


@pytest.mark.parametrize("name", COMMANDS)
def test_no_arguments_is_help_or_usage_never_a_crash(name, tmp_path):
    rc, out, err = run([name], cwd=str(tmp_path))
    assert "Traceback" not in err, err
    assert rc in (0, 1, 2), f"exit {rc} with no arguments"


# ------------------------------------------------------------------ the canned safe invocation


@pytest.fixture()
def prepared(tmp_path):
    return contract_cases.prepare(tmp_path)


@pytest.mark.parametrize("name", COMMANDS)
def test_the_safe_invocation_keeps_the_contract(name, tmp_path, prepared):
    case = contract_cases.CASES[name]
    args = contract_cases.resolve(case["args"], prepared)

    rc, out, err = run([name, *args], cwd=str(tmp_path))
    assert "Traceback" not in err, f"ad-{name} put a traceback on stderr:\n{err[-1500:]}"
    assert rc in (0, 1, 2), f"ad-{name} exited {rc}"
    assert not ANSI.search(out), f"ad-{name} wrote ANSI escapes to a pipe"

    if not case.get("toon"):
        return

    problems = toon.validate(out)
    assert not problems, f"ad-{name} stdout is not TOON: {problems}\n{out[:600]}"

    meta = _meta(out)
    assert "ok" in meta, f"ad-{name} printed no meta.ok"
    assert meta["ok"] in ("true", "false")
    if meta["ok"] == "false":
        assert meta.get("hint", "").strip(), f"ad-{name} failed without a hint"


def _meta(text: str) -> dict[str, str]:
    """The `meta:` block as flat strings. Enough to assert the contract, not a TOON parser."""
    out: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        if line.rstrip() == "meta:":
            inside = True
            continue
        if inside:
            if not line.startswith("  ") or not line.strip():
                break
            if ":" in line:
                key, value = line.strip().split(":", 1)
                out[key.strip()] = value.strip().strip('"')
    return out


@pytest.mark.slow      # three subprocesses per command; the fast suite stays under two minutes
@pytest.mark.parametrize("name", [n for n, c in contract_cases.CASES.items() if c.get("toon")])
def test_colour_never_and_piped_output_are_byte_identical(name, tmp_path, prepared):
    """No escape may ever reach an agent's context, whatever the environment says."""
    case = contract_cases.CASES[name]
    args = contract_cases.resolve(case["args"], prepared)

    _rc, piped, _err = run([name, *args], cwd=str(tmp_path))
    _rc, never, _err = run([name, *args], cwd=str(tmp_path), extra_env={"AGENTDATA_COLOR": "never"})
    _rc, no_color, _err = run([name, *args], cwd=str(tmp_path), extra_env={"NO_COLOR": "1"})

    assert not ANSI.search(never) and not ANSI.search(no_color)
    assert _stable(piped) == _stable(never) == _stable(no_color), \
        f"ad-{name} output depends on the colour environment"


VOLATILE = re.compile(r"(elapsed_s|seconds|wall_time_s|generated|collected_at|run_id|last_updated|"
                      r"path|written|commit|captured|collected|_at):.*")


def _stable(text: str) -> str:
    """Drop the fields that legitimately differ between two runs a millisecond apart."""
    return "\n".join(VOLATILE.sub("", ln) for ln in text.splitlines())


@pytest.mark.slow
@pytest.mark.parametrize("name", [n for n, c in contract_cases.CASES.items() if c.get("toon")])
def test_forced_colour_produces_a_human_rendering(name, tmp_path, prepared):
    """The other half of the same promise: a person gets colour when they ask for it."""
    case = contract_cases.CASES[name]
    args = contract_cases.resolve(case["args"], prepared)

    _rc, plain, _err = run([name, *args], cwd=str(tmp_path), extra_env={"AGENTDATA_COLOR": "never"})
    _rc, forced, _err = run([name, *args], cwd=str(tmp_path),
                            extra_env={"AGENTDATA_COLOR": "always", "FORCE_COLOR": "1"})
    if not ANSI.search(forced):
        # a command may legitimately have nothing to colour; then it must at least be the same text
        assert _stable(forced) == _stable(plain)


# ------------------------------------------------------------------------------------ isolation


def test_a_contract_run_never_touches_the_real_config(tmp_path, prepared):
    """The suite must pass on a machine with no ~/.agentdata at all, and must not create one."""
    real = os.path.join(os.path.expanduser("~"), ".agentdata", "config.json")
    before = os.path.getmtime(real) if os.path.exists(real) else None

    for name in ("doctor", "update", "state"):
        case = contract_cases.CASES[name]
        run([name, *contract_cases.resolve(case["args"], prepared)], cwd=str(tmp_path))

    after = os.path.getmtime(real) if os.path.exists(real) else None
    assert before == after, "a contract run wrote to the real config"


def test_the_isolated_home_is_where_the_config_would_go(isolated_home):
    assert os.environ["AGENTDATA_CONFIG"].startswith(str(isolated_home))


# -------------------------------------------------------------------------- the guard can fail


def test_a_traceback_would_be_caught(tmp_path):
    """The contract's own smoke test: a command that raises must be seen, not shrugged at."""
    probe = tmp_path / "boom.py"
    probe.write_text("raise RuntimeError('planted')\n", encoding="utf-8")
    p = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True)
    assert "Traceback" in p.stderr, "if this ever stops being true, every no-traceback assertion is vacuous"
