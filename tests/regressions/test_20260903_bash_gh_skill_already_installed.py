"""2026-09-03, Git Bash and PowerShell alike: ad-update's skills half failed on a second run.

Symptom:

    skills  x fail   skills already installed: bitbucket-pr, confluence-publish, data-adapter, ...   run it yourself ... (exit 1, 1.6s)

`gh skill install --all` exits 1 when any skill already exists. README documented the fix as "delete
that folder and re-run", which is a manual step for a command whose whole job is to be re-runnable.

Issue: https://github.com/agentchieflou/this-next-please/issues/66
"""
from __future__ import annotations
import os

from agentdata import update
from agentdata.textio import write_text

GH_STDERR = ("skills already installed: bitbucket-pr, confluence-publish, data-adapter, "
             "dax-studio-export, dpm-consumer-integration, friction-log, hive-query, jira-changelog\n")


def test_the_names_are_parsed_from_the_refusal():
    names = update.parse_already_installed(GH_STDERR)
    assert "bitbucket-pr" in names and "jira-changelog" in names


def test_only_our_own_folders_are_removed(tmp_path):
    """The fix must never delete a skill another team put in the same directory."""
    d = str(tmp_path / "skills")
    for name, frontmatter in (("bitbucket-pr", "bitbucket-pr"), ("someone-elses", "a-different-name")):
        os.makedirs(os.path.join(d, name), exist_ok=True)
        write_text(os.path.join(d, name, "SKILL.md"),
                   f'---\nname: {frontmatter}\ndescription: "x"\n---\n')

    removed = update.remove_our_skills(d, ["bitbucket-pr", "someone-elses"])
    assert removed == ["bitbucket-pr"]
    assert os.path.isdir(os.path.join(d, "someone-elses"))
