"""The recipes skills print, held to the CLI they name (friction scan 1.6 and §3 item 6).

`tests/test_skill_argv.py` already parses every documented `ad-*` line against argparse. What it
cannot see is the part argparse accepts and the command then refuses: `ad-state set` takes any
`key=value` and `--tool key=date`, and only `ad-state` itself knows which keys and phases exist --
the `tools.doctor_verified` mismatch was exactly that. And `pncli` is commander.js, where every
argument is a named option: `pncli jira get-issue RDSD-1` reads as plausible and fails, which is the
`--key` mismatch `jira-triage` hit.
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


def test_every_pncli_recipe_names_its_arguments():
    """pncli is commander.js: every argument is a named option, never positional. A skill line that
    passes a bare value after the verb is the `--key` mismatch waiting to happen again."""
    problems = []
    for where, text in spans(("pncli ",)):
        tokens = _command(text)
        if "--help" in tokens or len(tokens) < 3 or not re.fullmatch(r"[a-z][a-z-]*", tokens[1]):
            continue                                  # a help line, or prose such as `pncli / jira auth`
        rest, expecting_value = tokens[3:], False
        for token in rest:
            if token.startswith("-"):
                expecting_value = "=" not in token
                continue
            if expecting_value or token == "PLACEHOLDER":
                expecting_value = False
                continue
            problems.append(f"{where}: `{text}` passes {token!r} positionally; name it (`--key {token}`)")
            break
    assert not problems, "\n  " + "\n  ".join(problems)


def test_every_pncli_recipe_in_a_skill_is_a_read():
    """pncli is used directly for what it reads (docs/pncli-parts.md). A write is never a skill's recipe: in a
    fleet the shim refuses it (`fleet/pncli_gate.py`), and outside one it would skip the approval gate. Writes go
    through the gated extensions -- `ad-confluence publish`, `ad-git pr`, `ad-jira comment|transition|create`."""
    from agentdata.connectors import pncli as P

    problems, reads = [], 0
    for path in glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")) + \
            glob.glob(os.path.join(ROOT, "skills", "*", "references", "*.md")):
        for span in SPAN.findall(open(path, encoding="utf-8").read()):
            tokens = _command(span.strip())
            if len(tokens) < 2 or tokens[0] != "pncli" or not re.fullmatch(r"[a-z][a-z-]*", tokens[1]):
                continue
            if P.is_write(tokens[1:]):
                problems.append(f"{os.path.relpath(path, ROOT)}: `{span}` -- {' '.join(P.verb(tokens[1:]))} is not "
                                "in pncli.READ_VERBS; a write goes through its gated `ad-*` extension")
            else:
                reads += 1
    assert reads >= 5, "the recipes moved; this test reads them from the skills"
    assert not problems, "\n  " + "\n  ".join(problems)


def test_no_skill_or_doc_names_the_retired_pncli_wrapper():
    """0.20.0 retired the wrapper: pncli is used directly, and an `ad-*` command exists only where it extends it."""
    retired = "ad-" + "pncli"
    found = [os.path.relpath(path, ROOT) for path in documents() + [os.path.join(ROOT, "AGENTS.md")]
             if retired in open(path, encoding="utf-8").read()]
    assert not found, f"{retired} is gone: " + ", ".join(found)


def _command(text: str) -> list[str]:
    """A recipe's words up to a shell redirect or pipe: `pncli jira search --jql "<JQL>" > .agent/out/x.json`."""
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
