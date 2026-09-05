"""Run a pncli command, extract its result list, normalize. pncli always emits JSON; we never show it raw by default.

pncli is distributed as an npm package, so on Windows it exists as `pncli.cmd` (npm's command shim) and never as
`pncli.exe`: launching the bare name fails with `[WinError 2] The system cannot find the file specified`. All
resolution and launching therefore goes through `agentdata.proc`, which finds the shim (PATHEXT + the npm global
prefix) and runs its Node entry point directly, so an argument like `updated >= '2026-01-01'` is never re-parsed by
cmd.exe. `pncli.exe` in the config (or PNCLI_EXE) pins an explicit path."""
from __future__ import annotations
import json, os, re
from .. import config as C
from .. import proc
from ..model import AgentTable

NPM_PACKAGE = "@kolatts/pncli"      # laptop diagnosis 2026-09-02; override with the `pncli.npm_package` config key

JIRA_DEFAULT_FIELDS = ["key", "fields.status.name", "fields.assignee.displayName", "fields.priority.name",
                       "fields.updated", "fields.summary"]
JIRA_RENAME = {"fields.status.name": "status", "fields.assignee.displayName": "assignee",
               "fields.priority.name": "priority", "fields.updated": "updated", "fields.summary": "summary"}
ISSUE_RENAME = dict(JIRA_RENAME, **{"fields.description": "description", "fields.issuetype.name": "issuetype",
                                    "fields.resolution.name": "resolution", "fields.labels": "labels"})
ISSUE_RENAME_BACK = {v: k for k, v in ISSUE_RENAME.items()}
LIST_KEYS = ("issues", "results", "values", "items", "data")
# pncli is a commander.js CLI: every argument is a NAMED option (`--key RDSD-1`), never a positional. Its usage
# errors say so exactly, so turn them into the command the caller should have run instead of a generic hint.
_MISSING_OPT = re.compile(r"required option '(--[\w-]+)(?:\s+<([^>]*)>)?' not specified", re.I)
_UNKNOWN = re.compile(r"unknown (command|option) '?(--)?([\w-]+)'?", re.I)


# Which pncli commands only read. Everything else is treated as a write and goes through the fleet
# approval gate (`agentdata/fleet/approval.py`), because the alternative fails in the wrong
# direction: a write verb missing from a *write* list would be sent unattended, whereas a read verb
# missing from this list only costs the operator one extra click. That asymmetry is the whole design
# -- and it is what makes the gate survive an unpinned verb name (the Bitbucket PR verb and the Jira
# comment verb are both still `TODO(HANDOFF)` in their skills).
READ_VERBS = frozenset({
    ("jira", "search"), ("jira", "get"), ("jira", "get-issue"), ("jira", "changelog"),
    ("jira", "transitions"), ("jira", "comments"), ("jira", "fields"), ("jira", "list"),
    ("confluence", "get-page"), ("confluence", "search"), ("confluence", "list-pages"),
    ("bitbucket", "get-pr"), ("bitbucket", "list-prs"), ("bitbucket", "diff"),
    ("config", "get"), ("config", "list"), ("config", "show"),
})
# Single-token commands that cannot write. Flags never appear here: `verb()` strips them, so
# `--help` and `--version` produce an empty path and are read by construction.
READ_COMMANDS = frozenset({"help", "version", "where"})


def verb(args: list[str]) -> tuple:
    """The command being asked for, as (product, verb) -- flags and their values ignored.

    pncli is commander.js: every argument is a *named* option, so the bare tokens are exactly the
    command path and nothing else can be mistaken for one.
    """
    return tuple(a for a in args if not a.startswith("-"))[:2]


def is_write(args: list[str]) -> bool:
    """Would running this change something on a system of record?

    `--dry-run` is not a write whatever the verb: pncli resolves and prints, and sends nothing.
    """
    if any(a == "--dry-run" for a in args):
        return False
    path = verb(args)
    if not path:
        return False
    if len(path) == 1:
        return path[0] not in READ_COMMANDS
    return path not in READ_VERBS


def usage_hint(text: str, args: list[str]) -> str:
    """Turn pncli's own usage error into the exact fix. Returns '' when the output is not a usage error."""
    m = _MISSING_OPT.search(text)
    if m:
        opt, placeholder = m.group(1), (m.group(2) or "value")
        positionals = [a for a in args[2:] if not a.startswith("-")]
        value = positionals[0] if positionals else "<" + placeholder + ">"
        seen = f" (you passed {positionals[0]!r} positionally)" if positionals else ""
        return (f"pncli options are named, never positional{seen}: re-run with `{opt} {value}`, e.g. "
                f"`ad-pncli raw {' '.join(args[:2])} {opt} {value}`")
    m = _UNKNOWN.search(text)
    if m:
        return (f"pncli has no {m.group(1)} {m.group(3)!r}: run `pncli {args[0] if args else ''} --help` once, "
                "use a listed verb, and report it so the skill can pin it. Do not guess a second time.")
    return ""


def exe(cfg: dict | None = None) -> str | None:
    """Pinned launcher path: PNCLI_EXE, else the `pncli.exe` config key. None = resolve `pncli` over PATH."""
    cfg = C.load() if cfg is None else cfg
    return os.environ.get("PNCLI_EXE") or C.get(cfg, "pncli.exe") or None


def install_hint(cfg: dict | None = None) -> str:
    pkg = C.get(C.load() if cfg is None else cfg, "pncli.npm_package") or NPM_PACKAGE
    return (f"pncli is an npm package: install it with `npm install -g {pkg}` (it lands as pncli.cmd, never pncli.exe), "
            "or pin its path with PNCLI_EXE / `ad-setup --only pncli`. `ad-pncli where` shows what was tried.")


def where(cfg: dict | None = None) -> dict:
    """How `pncli` resolves on this machine: path, kind (executable / npm shim / cmd shim), node entry, version."""
    cfg = C.load() if cfg is None else cfg
    info = proc.resolve("pncli", exe=exe(cfg))
    if info["found"]:
        try:
            rc, out, err, _el = proc.run(["pncli", "--version"], exe=exe(cfg), timeout=60)
            line = (out or err).strip().splitlines()
            info["version"] = line[0][:60] if line else ""
            info["rc"] = rc
        except proc.ProcError as e:
            info["version"], info["rc"], info["error"] = "", -1, e.msg
    return info


def get_issue(key: str, fields: list[str] | None = None) -> AgentTable:
    """One issue. `jira get-issue --key <KEY>`: the verb and its named option are confirmed against pncli."""
    payload, el = run(["jira", "get-issue", "--key", key])
    recs = extract_records(payload)
    t = AgentTable.from_records(recs, name="issue", source=f"pncli jira get-issue --key {key}",
                                fields=[ISSUE_RENAME_BACK.get(f, f) for f in fields] if fields else None, raw=payload)
    t.columns = [ISSUE_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    t.elapsed_s = el
    return t


def run(args: list[str], timeout: int = 120, cfg: dict | None = None) -> tuple[dict | list, float]:
    cfg = C.load() if cfg is None else cfg
    hint = install_hint(cfg)
    rc, out, err, el = proc.run(["pncli", *args], exe=exe(cfg), timeout=timeout, hint=hint)
    text = out.strip() or err.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise proc.ProcError("bad_output", f"pncli exited {rc} without JSON: {text[:200] or '(no output)'}",
                             usage_hint(text, args) or "run the same pncli command yourself to see its output; add --dry-run --pretty",
                             {"exit_code": rc}) from None
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise proc.ProcError("pncli_error", str(payload.get("error") or payload.get("message") or "pncli error")[:300],
                             "fix the command or the Jira query; `ad-doctor --only pncli` checks the token", {"exit_code": rc})
    return payload, el


def extract_records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                inner = extract_records(payload[k])
                if inner:
                    return inner
        for k in LIST_KEYS:
            if isinstance(payload.get(k), list):
                return payload[k]
        return [payload]
    return []


def jira_search(jql: str, fields: list[str] | None = None, max_results: int = 500) -> AgentTable:
    payload, el = run(["jira", "search", "--jql", jql, "--max-results", str(max_results)])
    recs = extract_records(payload)
    want = fields or JIRA_DEFAULT_FIELDS
    # allow short names
    short = {v: k for k, v in JIRA_RENAME.items()}
    want = [short.get(f, f) for f in want]
    t = AgentTable.from_records(recs, name="jira", source=f"pncli jira search --jql {jql!r}", fields=want, raw=payload)
    t.columns = [JIRA_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    t.elapsed_s = el
    t.truncated = len(recs) >= max_results
    return t
