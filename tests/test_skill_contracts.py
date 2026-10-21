"""The recipes skills print, held to the CLI they name (friction scan 1.6 and §3 item 6).

`tests/test_skill_argv.py` already parses every documented `ad-*` line against argparse. What it
cannot see is the part argparse accepts and the command then refuses: `ad-state set` takes any
`key=value` and `--tool key=date`, and only `ad-state` itself knows which keys and phases exist --
the `tools.doctor_verified` mismatch was exactly that. And a `toil` recipe has to name a command
toil has: `toil jira get-issue` reads as plausible and fails, which is the mismatch `jira-triage` hit
with pncli, toil's predecessor here.
"""
from __future__ import annotations
import glob
import os
import re
import shlex

from agentdata import state as S
from agentdata.setup import wizard as W

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPAN = re.compile(r"`([^`\n]+)`")
PLACEHOLDER = re.compile(r"<[^>]*>")


def documents() -> list[str]:
    paths = glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md"))
    paths += glob.glob(os.path.join(ROOT, "skills", "*", "references", "*.md"))
    paths += glob.glob(os.path.join(ROOT, "docs", "*.md")) + [os.path.join(ROOT, "README.md")]
    return sorted(paths)


def spans(prefixes: tuple[str, ...]) -> list[tuple[str, str]]:
    out = []
    for path in documents():
        for span in SPAN.findall(open(path, encoding="utf-8").read()):
            text = span.strip()
            if text.startswith(prefixes):
                out.append((os.path.relpath(path, ROOT), text))
    return out


def words(text: str) -> list[str]:
    try:
        return shlex.split(PLACEHOLDER.sub("PLACEHOLDER", text))
    except ValueError:
        return text.split()


def test_every_state_recipe_names_a_key_a_phase_and_a_tool_ad_state_accepts():
    recipes = spans(("ad-state set", "python -m agentdata state set"))
    assert len(recipes) >= 5, "the recipes moved; this test reads them from the skills and docs"
    keys = {"phase", *S.STRING_KEYS}
    problems = []
    for where, text in recipes:
        tokens = words(text)
        i = tokens.index("set") + 1
        while i < len(tokens):
            token = tokens[i]
            if token == "--tool" and i + 1 < len(tokens):
                key = tokens[i + 1].split("=", 1)[0]
                if "PLACEHOLDER" not in key and key not in S.TOOL_KEYS:
                    problems.append(f"{where}: `{text}` -- tools.{key} is not one of {', '.join(S.TOOL_KEYS)}")
                i += 2
                continue
            if token.startswith("-"):
                i += 2 if token in ("--artifact", "--question", "--input", "--run-id", "--file") else 1
                continue
            if "=" in token:
                key, _, value = token.partition("=")
                if "PLACEHOLDER" in key or key.startswith(("…", "...")):
                    pass
                elif key not in keys:
                    problems.append(f"{where}: `{text}` -- {key} is not a state key")
                elif key == "phase" and "PLACEHOLDER" not in value and "|" not in value \
                        and value.strip(".…") and value not in S.PHASES:
                    problems.append(f"{where}: `{text}` -- phase {value!r} is not one of the phases")
            i += 1
    assert not problems, "\n  " + "\n  ".join(problems)


def test_session_bootstrap_stamps_a_tool_key_ad_state_has():
    """The exact mismatch of 2026-09-02: bootstrap wrote `tools.doctor_verified` and the writer
    did not know the key."""
    boot = open(os.path.join(ROOT, "skills", "session-bootstrap", "SKILL.md"), encoding="utf-8").read()
    stamped = set(re.findall(r"--tool (\w+)=", boot))
    assert stamped and stamped <= set(S.TOOL_KEYS), stamped


# The toil commands the skills and docs teach, as `toil --help` lists them in 0.1.0-alpha.5. A recipe naming a path
# not here is a command an agent will type and toil will refuse; adding one is reading `toil <area> --help` first.
TOIL_COMMANDS = {
    ("jira", "issue"): {"get", "history", "search", "comments", "transitions", "fields", "attachments", "download",
                        "create", "update", "transition", "comment", "log-work", "label", "unlabel", "assign",
                        "link", "attach", "set-sprint", "schema"},
    ("jira", "sprint"): {"list"}, ("jira", "board"): {"list"},
    ("confluence", "page"): {"get", "find", "list", "children", "history", "search", "comments", "labels",
                             "attachments", "create", "update", "delete", "comment", "label", "unlabel", "attach"},
    ("bitbucket", "pr"): {"list", "get", "current", "comments", "diff", "files", "reviewers", "builds", "create",
                          "update", "merge", "decline", "comment", "approve"},
    ("connections",): {"list", "test", "add", "login", "remove", "default"},
}


def test_every_toil_recipe_names_a_command_toil_has():
    """A skill line naming a toil command toil does not have is the `get-issue` mismatch waiting to happen again.
    Ids are positional in toil (`toil jira issue get RDSD-1`), so only the command path is checked."""
    problems = []
    for where, text in spans(("toil ",)):
        tokens = _command(text)
        if "--help" in tokens or len(tokens) < 3 or not re.fullmatch(r"[a-z][a-z-]*", tokens[1]):
            continue                                  # a help line, or prose such as `toil / toil launcher`
        path = tuple(tokens[1:3])
        for group, actions in TOIL_COMMANDS.items():
            if tuple(tokens[1:1 + len(group)]) == group and len(tokens) > len(group) + 1:
                action = tokens[1 + len(group)]
                if action != "PLACEHOLDER" and action not in actions:
                    problems.append(f"{where}: `{text}` -- toil {' '.join(group)} has no {action!r}")
        if path == ("jira", "get-issue") or path == ("jira", "search"):
            problems.append(f"{where}: `{text}` is pncli's spelling; toil's is `toil jira issue get|search`")
    assert not problems, "\n  " + "\n  ".join(problems)


def test_every_toil_recipe_in_a_skill_is_a_read():
    """toil is used directly for what it reads (docs/toil-parts.md). A write is never a skill's recipe: in a
    fleet the shim refuses it (`fleet/toil_gate.py`), and outside one it would skip the approval gate. Writes go
    through the gated extensions -- `ad-confluence publish`, `ad-git pr`, `ad-jira comment|transition|create`."""
    from agentdata.connectors import toil as T

    problems, reads = [], 0
    for path in glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")) + \
            glob.glob(os.path.join(ROOT, "skills", "*", "references", "*.md")):
        for span in SPAN.findall(open(path, encoding="utf-8").read()):
            tokens = _command(span.strip())
            if len(tokens) < 2 or tokens[0] != "toil" or not re.fullmatch(r"[a-z][a-z-]*", tokens[1]):
                continue
            if T.is_write(tokens[1:]):
                problems.append(f"{os.path.relpath(path, ROOT)}: `{span}` -- {' '.join(T.verb(tokens[1:]))} writes; "
                                "a write goes through its gated `ad-*` extension")
            else:
                reads += 1
    assert reads >= 5, "the recipes moved; this test reads them from the skills"
    assert not problems, "\n  " + "\n  ".join(problems)


def test_no_skill_teaches_pncli():
    """0.22.0 replaced pncli with toil as the service backend. History may name it; a skill may not run it."""
    found = []
    for path in glob.glob(os.path.join(ROOT, "skills", "**", "*.md"), recursive=True) + \
            [os.path.join(ROOT, "AGENTS.md")]:
        if "pncli" in open(path, encoding="utf-8").read():
            found.append(os.path.relpath(path, ROOT))
    current = ("README.md", "docs/setup.md", "docs/data-format-policy.md", "docs/fleet-approvals.md",
               "docs/toil-parts.md", "docs/fleet.md", "docs/fleet-intake.md")   # plans and history may quote it
    found += [f"{where}: `{text}`" for where, text in spans(("pncli ",)) if where.replace(os.sep, "/") in current]
    assert not found, "pncli is retired: " + ", ".join(found)


def test_no_skill_or_doc_names_the_retired_pncli_wrapper():
    """0.20.0 retired the wrapper, and 0.22.0 pncli itself; an `ad-toil` pass-through would repeat that mistake."""
    for retired in ("ad-" + "pncli", "ad-" + "toil"):
        found = [os.path.relpath(path, ROOT) for path in documents() + [os.path.join(ROOT, "AGENTS.md")]
                 if retired in open(path, encoding="utf-8").read()]
        assert not found, f"{retired} is not a command: " + ", ".join(found)


def _command(text: str) -> list[str]:
    """A recipe's words up to a shell redirect or pipe: `toil jira issue search --jql "<JQL>" > .agent/out/x.json`."""
    out = []
    for token in words(text):
        if token in (">", ">>", "|", "2>&1") or token.startswith((">", "|")):
            break
        if token not in ("…", "..."):
            out.append(token)
    return out


def test_an_answers_file_in_any_encoding_powershell_writes_is_read(tmp_path):
    """BOM tolerance (§3 item 6): `Set-Content -Encoding utf8` adds a BOM (pinned since 2026-09-02 in
    test_setup.py), and Windows PowerShell 5.1's `>` writes UTF-16."""
    import json

    for encoding in ("utf-8-sig", "utf-16"):
        path = tmp_path / f"answers-{encoding}.json"
        path.write_bytes(json.dumps({"project.jira_project": "RDSD"}).encode(encoding))
        assert W.load_answers(str(path), []) == {"project.jira_project": "RDSD"}, encoding
