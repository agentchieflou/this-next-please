"""Guardrails for the skill set itself: size, frontmatter, router rows, referenced files."""
import glob, os, re
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = sorted(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "missing frontmatter"
    keys = [line.split(":", 1)[0] for line in m.group(1).splitlines() if line and not line.startswith(" ")]
    return keys, m.group(1)


def test_skills_exist():
    assert len(SKILLS) >= 16


def test_skill_size_and_frontmatter():
    for path in SKILLS:
        text = open(path, encoding="utf-8").read()
        lines = text.count("\n") + (0 if text.endswith("\n") else 1)
        assert lines < 120, f"{path}: {lines} lines (limit 120)"
        keys, fm = _frontmatter(text)
        assert keys == ["name", "description"], f"{path}: frontmatter keys {keys}"
        # `gh skill install` parses this block as strict YAML: an unquoted value containing ": " is a nested mapping
        data = yaml.safe_load(fm)
        assert isinstance(data, dict) and list(data) == ["name", "description"], f"{path}: frontmatter must be YAML with name, description"
        assert data["name"] == os.path.basename(os.path.dirname(path)), f"{path}: name != folder"
        assert isinstance(data["description"], str) and data["description"].strip(), f"{path}: empty description"
        desc_line = re.search(r"^description:\s*(.*)$", fm, re.M).group(1)
        assert desc_line.startswith('"'), f"{path}: quote the description (it may contain ': ' or '#')"


def test_router_rows_resolve():
    text = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    folders = {os.path.basename(os.path.dirname(p)) for p in SKILLS}
    rows = re.findall(r"^\|[^|]*\|\s*`([a-z0-9\-]+)`\s*\|$", text, re.M)
    assert rows, "router table not found"
    for skill in rows:
        assert skill in folders, f"router points at missing skill {skill}"


def test_referenced_reference_files_exist():
    for path in SKILLS:
        text = open(path, encoding="utf-8").read()
        for ref in re.findall(r"`references/([\w\-./]+)`", text):
            assert os.path.exists(os.path.join(os.path.dirname(path), "references", ref)), f"{path}: missing references/{ref}"


# A pointer at a whole reference file, with the reason. An entry here is a promise that the file
# genuinely has no sections to point at -- not a place to park a pointer somebody did not scope.
WHOLE_FILE_ALLOWED = {
    # a Power BI theme file: JSON, not prose. It has no headings, and it is loaded whole or not at all.
    ("pbi-report-design", "theme-base.json"),
}


def test_every_reference_pointer_names_a_section():
    """A skill that says "read `references/X.md`" makes Luna load the whole file.

    `dpm-contract.md` is 160 lines and a given step needs one part of it. The four query skills
    already pointed at a section (`references/teradata-sql.md` §Row limiting) and the rest did not,
    so this is the existing convention made enforceable rather than a new rule.

    The precision is deliberately "somewhere on the same line": a step is one line in every skill
    here, and a looser rule (anywhere in the file) would pass a file with one § in it and nine
    unscoped pointers.
    """
    problems = []
    for path in SKILLS:
        name = os.path.basename(os.path.dirname(path))
        for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            for ref in re.findall(r"references/([\w\-./]+\.md)", line):
                if (name, ref) in WHOLE_FILE_ALLOWED or "§" in line:
                    continue
                problems.append(f"{name}/SKILL.md:{n}: points at references/{ref} with no §section")
    assert not problems, (
        "point at the section, not the file (or add it to WHOLE_FILE_ALLOWED with the reason):\n  "
        + "\n  ".join(problems))


# `§Heading` names a section; `§ ` with a space introduces prose about one ("§ When a lint error is
# not obvious: ... §Pitfalls checklist"). That is how the four query skills already wrote it, and it
# is what lets this test tell a claim about a heading from a sentence.
SECTION = re.compile(r"§(?![\s<])([^§]*)")
WORDS = re.compile(r"[a-z0-9]+")


def _words(text):
    """A heading's name, as words. Truncated at the parenthetical: `## Rebinding (what may change
    without a contract discussion)` is pointed at as §Rebinding, and should be."""
    return WORDS.findall(re.split(r"[(—:]", text.lower(), maxsplit=1)[0])


def test_a_section_pointer_names_a_heading_that_exists():
    """A §section nobody can find is worse than no pointer: it costs a read and then a search.

    A pointer is followed by the sentence it sits in, so this matches on a leading run of words
    rather than equality — two words of a heading, or all of it when the heading is one word.
    `§<that archetype>` is a placeholder telling the reader to pick one, and is skipped by the
    pattern rather than by an exception list.
    """
    problems = []
    for path in SKILLS:
        folder = os.path.dirname(path)
        name = os.path.basename(folder)
        for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            refs = re.findall(r"references/([\w\-./]+\.md)", line)
            if not refs:
                continue
            headings = []
            for ref in refs:
                ref_path = os.path.join(folder, "references", ref)
                if os.path.exists(ref_path):
                    body = open(ref_path, encoding="utf-8").read()
                    headings += [_words(h) for h in re.findall(r"^#{2,3}\s*(.+)$", body, re.M)]
            for section in SECTION.findall(line):
                wanted = WORDS.findall(section.lower())
                if not wanted:
                    continue
                matched = 0
                for heading in headings:
                    same = 0
                    while same < min(len(wanted), len(heading)) and wanted[same] == heading[same]:
                        same += 1
                    if same and (same == len(heading) or same >= 2):
                        matched = same
                        break
                if not matched:
                    problems.append(f"{name}/SKILL.md:{n}: §{' '.join(wanted[:4])}… "
                                    f"matches no heading in {refs}")
    assert not problems, "\n  ".join([""] + problems)


def test_the_router_does_not_re_read_state_session_bootstrap_just_read():
    """`session-bootstrap` step 1 read `.agent/state.json`; its last step invokes `router`, whose
    step 1 used to read the same file again in the same turn.

    Both halves are asserted, because either alone is wrong: the router must still read the file on
    every later task in the session, since a skill has run since and state does change.
    """
    boot = open(os.path.join(ROOT, "skills", "session-bootstrap", "SKILL.md"), encoding="utf-8").read()
    router = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()

    hand_off = next(ln for ln in boot.splitlines() if "`router`" in ln and "nvoke" in ln)
    for key in ("phase", "active_ticket", "open_questions"):
        assert key in hand_off, f"session-bootstrap hands the router no {key}"

    step_one = router.splitlines()[router.splitlines().index("# Router") + 2]
    assert "session-bootstrap" in step_one, "the router does not say where the handed-in state comes from"
    assert "same turn" in step_one, "the router must scope the hand-off to the turn it happened in"
    assert ".agent/state.json" in step_one, "the router must still read state on every later task"


def test_pbi_router_and_two_level_resolution():
    """Two-level router split (issue #50 & #26): router -> pbi-router -> domain leaf skills."""
    pbi_text = open(os.path.join(ROOT, "skills", "pbi-router", "SKILL.md"), encoding="utf-8").read()
    folders = {os.path.basename(os.path.dirname(p)) for p in SKILLS}
    pbi_rows = re.findall(r"^\|[^|]*\|\s*`([a-z0-9\-]+)`\s*\|$", pbi_text, re.M)
    assert pbi_rows, "pbi-router table not found"
    for skill in pbi_rows:
        assert skill in folders, f"pbi-router points at missing skill {skill}"
        assert skill != "pbi-router", "pbi-router cannot route to itself"
    # Ensure router contains pbi-router
    router_text = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    assert "`pbi-router`" in router_text


# Every routing table in the repository. A sub-router that outgrows the limit is the same problem
# one level down, and has the same fix.
ROUTERS = ("router", "pbi-router")

# The early warning, well under the 120-line hard limit every skill has. Two numbers because they
# fail for different reasons: a router gets long (costly to read, every task) or it gets wide
# (harder to pick from, and first-match-wins turns a near-miss into the wrong skill).
ROUTER_LINES = 60
ROUTER_ROWS = 24

# What to do when one of them trips. Deliberately not "shorten the row text": the rows are already
# terse, and squeezing them trades a legible table for a cryptic one while the real growth continues.
SPLIT = ("split it: keep a top-level table routing to a handful of domain sub-routers "
         "(`pbi-router` is the worked example — `router` has one row for Power BI, and the seven "
         "report skills live behind it). Raising this limit is not the fix; it only moves the "
         "decision to a worse moment.")


def _rows(text):
    return re.findall(r"^\|[^|]*\|\s*`([a-z0-9\-]+)`\s*\|$", text, re.M)


@pytest.mark.parametrize("name", ROUTERS)
def test_a_router_stays_small_enough_to_pick_from(name):
    """The early warning from #26, with real headroom under the hard limit.

    Every task's routing decision reads one of these, so their size is paid per task rather than
    per use of a skill. The point of warning early is that a split is a decision somebody makes
    deliberately, rather than a rush once the file is already at 119 lines.
    """
    text = open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8").read()
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    rows = _rows(text)
    assert lines < ROUTER_LINES, f"{name}/SKILL.md is {lines} lines (early warning {ROUTER_LINES}): {SPLIT}"
    assert len(rows) < ROUTER_ROWS, (
        f"{name}/SKILL.md has {len(rows)} routing rows (early warning {ROUTER_ROWS}): {SPLIT}")


def test_the_early_warning_is_still_early():
    """A limit quietly raised to 119 would pass its own test and warn nobody. This is what stops
    the guardrail from being disarmed by the edit that was supposed to trip it."""
    assert ROUTER_LINES <= 60, "the router warning must stay well under the 120-line hard limit"
    assert ROUTER_ROWS <= 24, "a flat first-match table stops being reliably scannable around here"


def test_the_router_says_what_to_do_when_it_outgrows_itself():
    """The failure message is read by whoever trips it; the note is read by whoever is about to."""
    text = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    assert "sub-router" in text, "the router does not describe the split that is its own next step"
    assert "`pbi-router`" in text, "the note must point at the worked example"


# Lines that are genuinely one-shell, with the reason. Kept explicit and short: an entry here is a
# promise that the other shell has no equivalent, not a place to park work.
ONE_SHELL_ALLOWED = {
    # sbatch scripts are POSIX by definition -- the cluster runs Linux
    ("slurm-submit", "export "),
}


def test_shell_specific_commands_show_both_forms():
    """`& "<exe>"` is pwsh's call operator and is a syntax error in bash; bash needs no `&`.

    A skill that shows only one form sends half its readers to a broken command line, which is what
    docs/shells.md exists to stop. Either write it shell-neutral (`ad-*`, `python -m agentdata`) or
    show both.
    """
    problems = []
    for path in SKILLS:
        name = os.path.basename(os.path.dirname(path))
        text = open(path, encoding="utf-8").read()
        for n, line in enumerate(text.splitlines(), 1):
            # `export ` on its own matches prose ("export measures"); only the assignment form is a
            # shell command
            markers = [m for m in ('& "', "$env:") if m in line]
            if re.search(r"\bexport [A-Za-z_]\w*=", line):
                markers.append("export ")
            for marker in markers:
                if any(name == skill and marker == m for skill, m in ONE_SHELL_ALLOWED):
                    continue
                # the counterpart may be on this line or the next one
                window = "\n".join(text.splitlines()[n - 1:n + 1])
                has_pair = ("pwsh" in window and "bash" in window)
                if not has_pair:
                    problems.append(f"{name}/SKILL.md:{n}: {marker!r} with no counterpart shown")
    assert not problems, ("shell-specific command lines need both forms:\n  " + "\n  ".join(problems))
