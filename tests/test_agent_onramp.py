"""The on-ramp for the agents that develop this repository: GEMINI.md, the handover note, the PR template.

docs/developing-with-agents.md is the one source of the handover note. The PR template carries the same block, so the
builder sees it at the moment it opens a PR; GEMINI.md summarises the protocol for tools that load only that file.
These tests keep the three from drifting apart, and keep GEMINI.md small enough to sit in a system prompt.
"""
from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "developing-with-agents.md")
TEMPLATE = os.path.join(ROOT, ".github", "pull_request_template.md")
GEMINI = os.path.join(ROOT, "GEMINI.md")


def _read(path: str) -> str:
    return open(path, encoding="utf-8").read()


def _handover_headings(text: str) -> list[str]:
    """The headings between the handover markers, in order (the doc fences its copy; the template does not)."""
    m = re.search(r"<!-- handover:start -->(.*?)<!-- handover:end -->", text, re.S)
    assert m, "no handover block between the markers"
    return [ln.strip() for ln in m.group(1).splitlines() if re.match(r"\s*#{2,3} ", ln)]


def test_the_template_carries_the_docs_handover_note():
    doc, template = _handover_headings(_read(DOC)), _handover_headings(_read(TEMPLATE))
    assert doc[0] == "## Handover" and "### Next" in doc and "### Dead ends" in doc, doc
    assert template == doc, "the PR template's handover note and docs/developing-with-agents.md §4 have drifted"


def test_the_template_opens_with_the_closing_line():
    assert _read(TEMPLATE).startswith("Closes #")


def test_gemini_md_is_small_and_points_at_the_protocol():
    text = _read(GEMINI)
    assert len(text) < 8000, f"GEMINI.md is {len(text)} characters; it sits in a system prompt"
    for needle in ("AGENTS.md", "docs/developing-with-agents.md", "handover note", "Closes #"):
        assert needle in text, needle
    # The product keeps its own state under .agent/, which is ignored by git: a rule placed there is never shared.
    assert not re.search(r"(?<![\w.])\.agent/", text), "GEMINI.md names a path under .agent/"


def test_the_protocol_says_handover_not_handoff():
    """'Handoff' is a product feature here (docs/fleet-handoff.md); the builder's note is a handover note."""
    text = _read(DOC)
    assert len(text.encode("utf-8")) <= 24 * 1024, "docs/developing-with-agents.md is over 24 KB"
    assert "handover note" in text
    assert not re.search(r"handoff note", text, re.I)
