"""The flake policy: a red check becomes a reproduced cause, never a re-run into green (#316).

docs/testing-this-repo.md carries the policy in "When CI is red"; .github/ISSUE_TEMPLATE/flake.md is the issue a
red check opens before any re-run. These tests keep the section, the template and the merge-over-red rule together,
so none of them can be dropped or reworded out of existence quietly.
"""
from __future__ import annotations

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO_ROOT, "docs", "testing-this-repo.md")
TEMPLATE = os.path.join(REPO_ROOT, ".github", "ISSUE_TEMPLATE", "flake.md")

#: What a flake issue must record, in the order the policy names them.
FIELDS = ("Job URL", "Node id", "Failure output", "Commit", "Runner OS and Python", "Reproduction")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"docs/testing-this-repo.md has no '## {heading}' section"
    return match.group(1)


def _flat(text: str) -> str:
    """The section as one line, so a rule wrapped across lines still matches."""
    return re.sub(r"\s+", " ", text)


def test_the_section_exists_and_names_the_template():
    section = _section(_read(DOC), "When CI is red")
    assert ".github/ISSUE_TEMPLATE/flake.md" in section, "name the template a red check opens"


def test_the_section_asks_for_every_field_before_any_rerun():
    section = _flat(_section(_read(DOC), "When CI is red"))
    assert "Before any re-run" in section
    for needle in ("job URL", "node id", "full failure output", "_explain_the_page", "the commit",
                   "runner OS and Python"):
        assert needle in section, f"the section does not ask for {needle!r}"


def test_the_section_says_reproduce_fix_the_cause_and_never():
    section = _flat(_section(_read(DOC), "When CI is red"))
    assert "never \"a flake\"" in section, "a red that passes on re-run is a finding"
    assert "Reproduce before fixing" in section
    assert "Fix the cause" in section
    assert "tests/regressions/test_<yyyymmdd>_<any|shell>_<short>.py" in section
    never = section[section.index("**Never**"):]
    for word in ("skip", "xfail", "quarantine", "deselect", "fixed wait", "cap", "re-run until green"):
        assert word in never, f"the Never list does not forbid {word!r}"


def test_the_section_states_the_merge_over_red_rule():
    section = _flat(_section(_read(DOC), "When CI is red"))
    assert "Every pytest job is required in practice" in section
    assert "`windows · python 3.14` included" in section
    assert "K (PR #275) only" in section, "the 3.14 waiver was for K alone"
    assert "no job is advisory" in section
    assert "only at the operator's word for that PR" in section
    assert "names the check and links its flake issue" in section


def test_what_ci_runs_points_to_the_section():
    assert "When CI is red" in _section(_read(DOC), "What CI runs")


def test_the_template_has_its_front_matter_and_every_field():
    text = _read(TEMPLATE)
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "the template starts with YAML front matter"
    front = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    front = {k.strip(): v.strip() for k, v in front.items()}
    assert front.get("name"), "front matter: name"
    assert front.get("about"), "front matter: about"
    assert front.get("labels") == "flake", "front matter: labels: flake"
    headings = re.findall(r"^## (.+)$", text[match.end():], re.M)
    for field in FIELDS:
        assert field in headings, f"the template has no '## {field}' field"
    assert "_explain_the_page" in text, "the failure output includes what _explain_the_page printed"
