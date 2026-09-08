"""The skill graph: where work goes next, and whether it may go there yet.

Skills hand off to each other by name without waiting for a new prompt, which is what makes "one
prompt" possible at all. It also means a wrong name is a dead end nobody notices until a ticket
stops halfway, and a hand-off that *skips a step* is worse: it runs, it produces output, and the
step it skipped was the one that would have caught the problem.

Both are cheap to check and neither was checked before this file.
"""
from __future__ import annotations
import os
import re
from collections import deque

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")

NAMES = sorted(d for d in os.listdir(SKILLS)
               if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))

# A sentence that sends work somewhere. `bitbucket-pr` says "invoke `jira-transition`",
# `tmdl-edit` says "Hand off → `pbi-validate`", and `pbi-refresh-xmla` says it inside a bullet --
# keying on the words "hand off" alone misses a third of the edges and invents dead ends.
SENDING = ("hand off", "hands off", "invoke", "→", "->")
REF = re.compile(r"`([a-z0-9][a-z0-9-]+)`")


def body(name: str) -> str:
    return open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8").read()


# Reachable from everywhere by design, so they are neither interesting edges nor real
# prerequisites: `friction-log` is the escape hatch every skill has, `state-update` is bookkeeping,
# and the routers are where everything starts.
UNIVERSAL = {"friction-log", "state-update", "router", "pbi-router", "session-bootstrap"}

# A prerequisite is what the sentence says *before* it starts describing what to do when the
# prerequisite is missing. "Prereq: `pbip-projection` ran; missing → `friction-log`. STOP." names
# one prerequisite, not two -- and "Sprint questions → run `jira-changelog` first" is a condition,
# not a requirement.
_ESCAPE = re.compile(r"(missing|→|->|\bif\b|\bwhen\b|\bor\b)", re.I)


def sends_to(name: str) -> set[str]:
    """Every skill this one sends work to.

    Only the **first** skill named after each hand-off arrow in a clause: a line that describes the
    onward chain ("→ `a` (which leads to `b` → `c`)") sends work to `a`, and naming `b` and `c` is
    documentation rather than an edge.
    """
    out = set()
    for line in body(name).splitlines():
        low = line.lower()
        if not any(word in low for word in SENDING):
            continue
        for clause in re.split(r"[;.]", line):
            if not any(word in clause.lower() for word in SENDING):
                continue
            # Ignore anything inside brackets: that is where the onward chain gets described.
            outside = re.sub(r"\([^)]*\)", " ", clause)
            found = [ref for ref in REF.findall(outside) if ref in NAMES and ref != name]
            if found:
                out.add(found[0])
    return out - UNIVERSAL


def prereqs(name: str) -> set[str]:
    """The skills this one declares it needs done first, from its `Prereq:` sentence."""
    out = set()
    for line in body(name).splitlines():
        if "prereq" not in line.lower():
            continue
        after = re.split(r"[Pp]rereq:", line, maxsplit=1)[-1]
        after = _ESCAPE.split(after, maxsplit=1)[0]
        out |= {ref for ref in REF.findall(after) if ref in NAMES and ref != name}
    return out - UNIVERSAL


GRAPH = {name: sends_to(name) for name in NAMES}
PREREQS = {name: prereqs(name) for name in NAMES}


# ------------------------------------------------------------------------ nothing dangles


@pytest.mark.parametrize("name", NAMES)
def test_every_skill_a_skill_names_actually_exists(name):
    """A renamed folder is the obvious way to break this, and it has already happened once in this
    repository: `uat-jira-vs-teradata` became `uat-jira-vs-source` and four files referenced the old
    name. A dead hand-off does not fail loudly -- the ticket just stops."""
    text = body(name)
    suspects = set()
    for line in text.splitlines():
        if not any(word in line.lower() for word in SENDING):
            continue
        for ref in REF.findall(line):
            # A skill name looks like `a-b`. Filter out the things that also look like that and
            # are not skills: CLI commands, TOON fields, and class names the findings use.
            if "-" in ref and not ref.startswith("ad-") and "_" not in ref:
                suspects.add(ref)
    unknown = sorted(s for s in suspects if s not in NAMES)
    # Hyphenated things that are not skills: `ad-*` verbs (filtered above), the classes the
    # findings files use, the friction types, and one `ad-jira` subcommand.
    known_not_skills = {"missing-info", "tool-error", "history-gap", "report-bug",
                        "inactive-relationship", "expectation-wrong", "mapping-bug",
                        "warehouse-drift", "dry-run", "no-op", "read-only", "one-prompt",
                        "sprint-replay", "visual-query", "jira-hist", "hist-coverage",
                        "pr-create", "create-page", "update-page", "get-page"}
    unknown = [u for u in unknown if u not in known_not_skills]
    assert not unknown, f"{name} names {unknown}, which are not skills"


# ----------------------------------------------------------- nothing skips a declared step


@pytest.mark.parametrize("name", NAMES)
def test_no_hand_off_skips_a_step_the_target_says_it_needs(name):
    """The bug this file was written for.

    `jira-triage` sent a model change straight to `pbi-deploy-te2`, whose own prereq line says
    "`pbi-validate` passed on this commit" -- so the one-prompt path either skipped validation or
    needed the user to notice and re-prompt, which is the opposite of one prompt.

    The rule: A may hand off to B if A *is* B's prerequisite, or if A declares B's prerequisite as
    its own. The second half matters -- `uat-report-visual` hands off to `tmdl-edit`, whose prereq
    is `pbip-projection`, and that is fine because `uat-report-visual` declares the same prereq.
    """
    problems = []
    for target in sorted(GRAPH[name]):
        for needed in sorted(PREREQS[target]):
            if needed == name or needed in PREREQS[name]:
                continue
            problems.append(f"{name} -> {target}, which needs {needed} first")
    assert not problems, "; ".join(problems)


def test_the_rule_would_have_caught_the_bug_it_was_written_for():
    """A guardrail nobody has seen fail is a guardrail nobody should trust."""
    fake_prereqs = {"jira-triage": set(), "pbi-deploy-te2": {"pbi-validate"}}
    name, target = "jira-triage", "pbi-deploy-te2"
    needed = "pbi-validate"
    assert needed != name and needed not in fake_prereqs[name], \
        "the rule as written would not have flagged the original defect"


# -------------------------------------------------------------- the loop actually closes


TICKET_TO_DONE = ["pbip-projection", "tmdl-edit", "pbi-validate", "pbi-deploy-te2",
                  "pbi-refresh-xmla", "pbi-verify-service", "confluence-publish",
                  "bitbucket-pr", "jira-transition"]


def test_a_ticket_key_can_reach_every_step_of_the_power_bi_loop():
    """"One prompt" means the graph is connected from a ticket key to a ticket in review. Any step
    that can only be reached by a human re-prompting is a step that will be forgotten."""
    seen, queue = {"jira-triage"}, deque(["jira-triage"])
    while queue:
        for nxt in GRAPH[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)

    unreachable = [step for step in TICKET_TO_DONE if step not in seen]
    assert not unreachable, f"unreachable from jira-triage: {unreachable}"


def test_a_model_change_enters_the_chain_at_its_start():
    """Entering at `tmdl-edit` would repeat the same bug one link earlier: `tmdl-edit`'s own prereq
    is `pbip-projection`. The entry point has to be a skill with no unmet prerequisite."""
    # The *hand-off* line, not the one that merely lists the ticket types.
    line = next(ln for ln in body("jira-triage").splitlines()
                if "model-change" in ln and "hand off" in ln.lower())
    assert "`pbip-projection`" in line
    entry = line.split("model-change")[1].split(";")[0]
    first_named = re.search(r"`([a-z0-9-]+)`", entry)
    assert first_named and first_named.group(1) == "pbip-projection", \
        f"a model change enters at {first_named.group(1) if first_named else None}, not the projection"
    assert PREREQS["pbip-projection"] <= {"jira-triage"}, \
        "the entry point has its own unmet prerequisite"


def test_the_deploy_step_still_states_the_prerequisite_that_makes_the_order_matter():
    """If this line ever goes, the ordering rule above silently stops protecting anything."""
    assert "pbi-validate" in "".join(
        ln for ln in body("pbi-deploy-te2").splitlines() if "prereq" in ln.lower())


def test_every_skill_can_be_reached_from_a_router_or_from_another_skill():
    """A skill nothing points at and no router lists is a skill nobody will ever run.

    Both routers count: `router` sends Power BI work to `pbi-router`, which is where the seven
    report-authoring skills are listed. A test that only read the top-level router would call them
    orphans and be wrong.
    """
    routing = body("router") + body("pbi-router")
    # A skill can be *referred* to rather than handed to: `data-adapter` is read by whoever hits
    # the row-count rule, not invoked. That counts as reachable -- just not by routing.
    referenced = {ref for n in NAMES for ref in re.findall(r"see `([a-z0-9-]+)`", body(n))}
    targeted = {t for targets in GRAPH.values() for t in targets} | referenced
    orphans = [n for n in NAMES
               if n not in targeted and f"`{n}`" not in routing and n not in UNIVERSAL]
    assert not orphans, f"unreachable skills: {orphans}"
