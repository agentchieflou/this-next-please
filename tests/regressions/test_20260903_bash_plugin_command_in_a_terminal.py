"""2026-09-03, Git Bash (MINGW64): a Copilot chat command typed into a terminal.

Symptom, from the same screenshot:

    $ /plugin marketplace add microsoft/skills-for-fabric
    bash: /plugin: No such file or directory

"No such file or directory" reads like a missing tool. It is a wrong window: `/plugin` belongs to the
Copilot chat, and nothing in the repo said which surface each command belongs to.

Issue: https://github.com/agentchieflou/this-next-please/issues/68
"""
from __future__ import annotations

from agentdata.cli_help import main


def test_ad_help_explains_the_surface_instead_of_guessing(capsys):
    assert main(["/plugin"]) == 0
    out = capsys.readouterr().out
    assert "Copilot chat" in out
    assert "not a shell command" in out
    assert "Did you mean" not in out, "a near-miss suggestion would send the user further astray"


def test_the_bare_form_is_recognised_too(capsys):
    assert main(["plugin marketplace"]) == 0
    assert "Copilot" in capsys.readouterr().out
