"""Tests for shell tab-completion integration and inertness."""
import pytest
from agentdata import completion
from agentdata.setup import wizard


def test_completion_script_generation():
    bash_script = completion.completion_script("bash")
    assert "register-python-argcomplete" in bash_script
    assert "ad-pbip" in bash_script

    zsh_script = completion.completion_script("zsh")
    assert "bashcompinit" in zsh_script
    assert "register-python-argcomplete" in zsh_script

    ps_script = completion.completion_script("powershell")
    assert "Register-ArgumentCompleter" in ps_script
    assert "ad-jira" in ps_script

    with pytest.raises(ValueError, match="unknown shell"):
        completion.completion_script("fish")


def test_setup_print_completion(capsys):
    assert wizard.run_setup(["--print-completion", "bash"]) == 0
    out = capsys.readouterr().out
    assert "register-python-argcomplete" in out

    assert wizard.run_setup(["--print-completion", "powershell"]) == 0
    out = capsys.readouterr().out
    assert "Register-ArgumentCompleter" in out


def test_autocomplete_is_inert_without_env():
    import argparse
    parser = argparse.ArgumentParser(prog="test")
    parser.add_argument("--foo")
    # Should not raise any error or exit when completing in a normal run
    completion.autocomplete(parser)


def test_python_argcomplete_ok_marker_present_in_entrypoint_files():
    import os
    import agentdata
    pkg_dir = os.path.dirname(agentdata.__file__)
    files_to_check = [
        os.path.join(pkg_dir, "cli.py"),
        os.path.join(pkg_dir, "cli_setup.py"),
        os.path.join(pkg_dir, "setup", "wizard.py"),
        os.path.join(pkg_dir, "cli_sqlcheck.py"),
        os.path.join(pkg_dir, "cli_jira.py"),
        os.path.join(pkg_dir, "cli_pbip.py"),
        os.path.join(pkg_dir, "cli_uat.py"),
        os.path.join(pkg_dir, "cli_dpm.py"),
        os.path.join(pkg_dir, "cli_state.py"),
        os.path.join(pkg_dir, "cli_confluence.py"),
        os.path.join(pkg_dir, "update.py"),
    ]
    for path in files_to_check:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# PYTHON_ARGCOMPLETE_OK" in content, f"{path} missing PYTHON_ARGCOMPLETE_OK marker"
