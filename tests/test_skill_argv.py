"""Every command line printed in a skill or a doc must parse against the real argparse.

A skill that tells the model to run a flag which no longer exists costs a whole session: the model
runs it, gets a usage error, and has no way to know the instruction was wrong rather than its own
reading of it. `AGENTDATA_PARSE_ONLY=1` validates the arguments and stops before anything is read,
launched or written, so every line in `skills/`, `docs/`, `README.md` and the project stub can be
checked cheaply.

Also here: `§Heading` pointers must resolve, the project stub must carry every fact the code reads,
and every router row's trigger words must appear in the skill it points at.
"""
from __future__ import annotations
import glob
import os
import re
import shlex
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A placeholder in a doc stands for something the reader supplies. To parse the line we need
# *something*; the value only has to satisfy argparse, not mean anything.
PLACEHOLDERS = {
    "<KEY>": "RDSD-1", "<key>": "RDSD-1", "<ticket>": "RDSD-1", "<issue key>": "RDSD-1",
    "<one issue key>": "RDSD-1", "<any issue key>": "RDSD-1", "<any issue>": "RDSD-1",
    "<SPACE>": "SPACE", "<space>": "SPACE", "<page id>": "12345", "<parent id>": "12345",
    "<pbip>": "report.pbip", "<pbip-dir>": "reports", "<pbip_path>": "reports/Report.pbip",
    "<tmdl_path>": "Model.SemanticModel/definition", "<dir>": "somewhere",
    "<Table>": "Sales", "<table>": "Sales", "<Measure>": "Margin", "<measure>": "Margin",
    "<file>": "a.txt", "<path>": "a.txt", "<name>": "thing", "<node>": "app.py::main",
    "<node-id>": "app.py::main", "<id>": "app.py::main", "<target>": "app.py::main",
    "<from>": "a", "<to>": "b", "<ref>": "main", "<sha>": "abc1234", "<label>": "before",
    "<port>": "5000", "<server>": "localhost:5000", "<dscmd_exe>": "dscmd.exe",
    "<te2_exe>": "TabularEditor.exe", "<pbi_workspace>": "WS", "<pbi_model>": "Model",
    "<jira_board_id>": "42", "<board>": "42", "<closed sprint id>": "7", "<sprint>": "7",
    "<n>": "1", "<N>": "1", "<value>": "v", "<today YYYY-MM-DD>": "2026-09-04",
    "<row key>": "id", "<purpose>": "check", "<skill>": "router", "<shell>": "bash",
    "<owner>/<repo>": "o/r", "<KEY>-<purpose>": "RDSD-1-check", "<state>": "closed",
    "<run-id>": "RUN-1", "<RUN-id>": "RUN-1", "<sprint start minus 1 day>": "2026-01-01",
    "<any real query>": "q.sql", "<lcov|cobertura>": "lcov", "<base>": "main",
    "<before.toon>": "before.tsv", "<after.toon>": "after.tsv", "<before.tsv>": "before.tsv",
    "<after.tsv>": "after.tsv", "<tsv>": "a.tsv", "<a>": "a.tsv", "<b>": "b.tsv",
    "<yyyymmdd>": "20260904", "<short>": "thing", "<framework>": "pytest",
    "<command>": "doctor", "<cmd>": "doctor", "<step>": "pncli", "<KEY>.vpax": "RDSD-1.vpax",
    "<graph-dir>": ".agent/graph", "<exe>": "tool.exe", "<pkg>": "pkg", "<url>": "https://x",
}
# A line marked `<!-- no-parse -->` is illustrative rather than runnable. Keep this list short --
# the test prints its size so growth is visible.
NO_PARSE = "<!-- no-parse -->"

# Docs name commands as well as invoke them: "`ad-jira sprint-replay --compare-sprintreport` reports
# the delta" is prose about a flag, and argparse's complaint is that the *other* required arguments
# are absent. That is not a defect.
#
# What is a defect -- and the whole reason this test exists -- is a flag, subcommand or choice that
# no longer exists. A model following such a line gets a usage error and has no way to tell the
# instruction was wrong rather than its own reading of it.
NAMING_A_COMMAND = (
    "the following arguments are required",
    "expected one argument",
    "expected at least one argument",
    "is required",
    "expected 2 arguments",
)

COMMAND_LINE = re.compile(r"`(ad-[a-z-]+ [^`]*|python -m agentdata [^`]*)`")
FENCED = re.compile(r"^\s*(ad-[a-z-]+ .*|python -m agentdata .*)$", re.M)


def documents() -> list[str]:
    paths = []
    for pattern in ("skills/*/SKILL.md", "skills/*/references/*.md", "docs/*.md", "README.md",
                    "AGENTS.md", "agentdata/templates/project-stub/AGENTS.md"):
        paths.extend(glob.glob(os.path.join(REPO_ROOT, pattern)))
    return sorted(paths)


def substitute(line: str) -> str:
    for token, value in sorted(PLACEHOLDERS.items(), key=lambda kv: -len(kv[0])):
        line = line.replace(token, value)
    # anything still angle-bracketed becomes a plain word so shlex and argparse can cope
    return re.sub(r"<[^>\s]{1,40}>", "placeholder", line)


def strip_comment(command: str) -> str:
    """Drop a trailing shell comment. Docs annotate almost every example line with one."""
    out, quote = [], ""
    for i, ch in enumerate(command):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or command[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out).strip()



def _is_an_invocation(command: str) -> bool:
    """Is this a line someone could copy, or a mention of a command?

    Docs legitimately contain both. `ad-graph summary [--top N]` is *notation* -- the brackets mean
    "optional" -- and a row in a command table reading `ad-jira transition` is naming the command,
    not invoking it. Neither should be parsed, and neither is a defect.
    """
    if "[" in command or "]" in command:
        return False                                    # optional-argument notation
    if any(ch in command for ch in "|<>") and "python -m agentdata" not in command:
        return False                                    # a pipeline or a redirect
    if command.endswith(("...", "…")):
        return False
    words = command.split()
    head = 3 if command.startswith("python -m agentdata") else 1
    arguments = words[head:]
    if not arguments:
        return False
    # A run of bare lowercase words is a command *path* -- `ad-pbip catalog describe` in a reference
    # table names the command. An invocation carries at least one flag, or a token that is plainly a
    # value: a path, a key=value, a quoted string, or something with a digit in it.
    def looks_like_a_value(token: str) -> bool:
        return (token.startswith("-")
                or any(ch in token for ch in "/=.\"'")
                or any(ch.isdigit() for ch in token))

    return any(looks_like_a_value(t) for t in arguments)


def command_lines() -> list[tuple[str, int, str]]:
    """(file, line number, command) for every runnable-looking line."""
    found = []
    for path in documents():
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            if NO_PARSE in line:
                continue
            candidates = COMMAND_LINE.findall(line)
            if not candidates and FENCED.match(line):
                candidates = [line.strip()]
            for command in candidates:
                command = strip_comment(command.strip().rstrip("`"))
                if not command or not _is_an_invocation(command):
                    continue
                found.append((rel, n, command))
    return found



CASES = command_lines()


def to_argv(command: str) -> list[str] | None:
    text = substitute(strip_comment(command))
    if text.startswith("python -m agentdata"):
        rest = text[len("python -m agentdata"):]
    elif text.startswith("ad-"):
        name, _, rest = text.partition(" ")
        rest = f" {name[3:]} {rest}"
    else:
        return None
    try:
        return shlex.split(rest, posix=True)
    except ValueError:
        return None


def parse_in_process(argv: list[str]) -> tuple[int, str]:
    """Parse one command line without spawning a process.

    There are ~150 of these; a subprocess each added a minute and a half to the suite for no extra
    signal, because parse-only mode never gets past `parse_args` anyway. stdout and stderr are
    captured so argparse's message is what the failure shows.
    """
    import contextlib
    import io

    from agentdata import __main__ as M

    out, err = io.StringIO(), io.StringIO()
    os.environ["AGENTDATA_PARSE_ONLY"] = "1"
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = M.main(argv)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 0
            except Exception as e:      # an import error is a defect too, and must be reported
                return 1, f"{type(e).__name__}: {e}"
    finally:
        os.environ.pop("AGENTDATA_PARSE_ONLY", None)
    return code or 0, (err.getvalue() or out.getvalue()).strip()


def test_there_are_command_lines_to_check():
    assert len(CASES) > 40, f"only {len(CASES)} command lines found; the extractor may be broken"


def test_the_no_parse_allow_list_stays_small():
    marked = sum(open(p, encoding="utf-8").read().count(NO_PARSE) for p in documents())
    print(f"\n{marked} line(s) marked {NO_PARSE}")
    assert marked <= 12, f"{marked} lines opt out of parsing; that is a lot of untested instructions"


@pytest.mark.parametrize("rel,line_no,command", CASES,
                         ids=[f"{c[0]}:{c[1]}" for c in CASES])
def test_every_documented_command_line_parses(rel, line_no, command):
    argv = to_argv(command)
    if argv is None or not argv:
        pytest.skip(f"not a parseable command line: {command!r}")

    code, message = parse_in_process(argv)
    if code == 0:
        return

    if any(needle in message for needle in NAMING_A_COMMAND):
        pytest.skip("names a command rather than invoking it")

    pytest.fail(
        f"{rel}:{line_no} names something that does not exist:\n  {command}\n  argv: {argv}\n"
        f"  {message[:400]}")


# ------------------------------------------------------------------------------ parse-only mode


def test_parse_only_covers_every_command():
    """Wired into `completion.autocomplete`, which every parser calls, so none can forget it."""
    from tests.test_contract import scripts  # noqa: F401  (import for the name only)


def test_parse_only_reads_nothing(tmp_path):
    """It must stop before config, network or files -- that is what makes it safe to run on docs."""
    from agentdata import proc

    real = os.path.join(os.path.expanduser("~"), ".agentdata", "config.json")
    before = os.path.getmtime(real) if os.path.exists(real) else None
    p = subprocess.run([sys.executable, "-m", "agentdata", "doctor", "--quiet"],
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env={**os.environ, "AGENTDATA_PARSE_ONLY": "1"})
    assert p.returncode == 0
    assert "parse_only: true" in p.stdout
    after = os.path.getmtime(real) if os.path.exists(real) else None
    assert before == after


# --------------------------------------------------------------------------- reference pointers


SECTION_POINTER = re.compile(r"`references/([\w\-./]+)`\s*§\s*([^\s`.,;]+)|§(?:<framework>|(\w[\w \-]*))")


def test_every_section_pointer_resolves():
    """`references/x.md` §Heading has to name a heading that is there (#24's section-scoped rule)."""
    problems = []
    for path in glob.glob(os.path.join(REPO_ROOT, "skills", "*", "SKILL.md")):
        skill_dir = os.path.dirname(path)
        text = open(path, encoding="utf-8").read()
        for ref in re.findall(r"`references/([\w\-./]+)`", text):
            ref_path = os.path.join(skill_dir, "references", ref)
            if not os.path.isfile(ref_path):
                problems.append(f"{os.path.basename(skill_dir)}: missing references/{ref}")
                continue
            if not ref.endswith(".md"):
                continue            # a JSON or CSV reference has no headings to point at
            body = open(ref_path, encoding="utf-8").read()
            headings = {h.strip().lower() for h in re.findall(r"(?m)^#{2,3}\s+(.+)$", body)}
            if not headings:
                problems.append(f"{ref}: a reference with no headings cannot be section-scoped")
                continue
            for pointer in re.findall(rf"`references/{re.escape(ref)}`\s*§\s*<?([\w \-]+)>?", text):
                needle = pointer.strip().lower()
                if needle in ("framework",):        # a placeholder for one of the sections
                    continue
                # "§Row limiting and §Dates" captures "Row limiting and " -- the heading is a
                # prefix of what was captured, not the other way round
                if not any(needle in h or h in needle for h in headings):
                    problems.append(f"{ref}: no heading matches §{pointer}")
    assert not problems, "\n  " + "\n  ".join(problems)


# --------------------------------------------------------------------------------- facts contract


def test_every_project_fact_the_code_reads_is_in_the_stub():
    stub = open(os.path.join(REPO_ROOT, "agentdata", "templates", "project-stub", "AGENTS.md"),
                encoding="utf-8").read()
    offered = set(re.findall(r"(?m)^-\s+(\w+):", stub))

    read = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "agentdata", "**", "*.py"), recursive=True):
        text = open(path, encoding="utf-8").read()
        read.update(re.findall(r'facts(?:\.get\(|\[)["\'](\w+)["\']', text))
        read.update(re.findall(r'project_facts\(\)(?:\.get\(|\[)["\'](\w+)["\']', text))

    missing = sorted(read - offered)
    assert not missing, (
        "the code reads project facts the stub never offers, so a project cannot supply them: "
        + ", ".join(missing))


def test_every_tool_key_and_phase_is_reachable():
    from agentdata import state

    assert "graph_approved" in state.TOOL_KEYS
    assert "optimizing" in state.PHASES
    stub = open(os.path.join(REPO_ROOT, "agentdata", "templates", "project-stub", "agent-state.json"),
                encoding="utf-8").read()
    assert "tools" in stub


# --------------------------------------------------------------------------------- router rows


def test_every_router_row_shares_a_word_with_the_skill_it_points_at():
    """Two-level routing only works if the row and the skill agree about what the skill is for."""
    router = open(os.path.join(REPO_ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    problems = []
    for line in router.splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*`([a-z0-9\-]+)`\s*\|$", line)
        if not m:
            continue
        triggers, skill = m.group(1), m.group(2)
        path = os.path.join(REPO_ROOT, "skills", skill, "SKILL.md")
        if not os.path.isfile(path):
            problems.append(f"router points at missing skill {skill}")
            continue
        description = re.search(r'(?m)^description:\s*"(.*)"', open(path, encoding="utf-8").read())
        text = (description.group(1) if description else "").lower()
        words = {w.strip(" `\"'").lower() for w in re.split(r"[,/|]", triggers) if len(w.strip()) > 3}
        if words and not any(w in text for phrase in words for w in phrase.split()):
            problems.append(f"{skill}: description shares no trigger word with its router row")
    assert not problems, "\n  " + "\n  ".join(problems)
