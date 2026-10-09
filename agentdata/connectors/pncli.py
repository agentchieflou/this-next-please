"""pncli as a library: classify an argv, run a read, extract its result list, name its columns.

pncli itself is used directly for everything it does (`docs/pncli-parts.md`). This module is what the fleet and
the `ad-*` extensions need from it in-process: the read/write split the fleet's shim gates on
(`fleet/pncli_gate.py`), the PR read of the fleet's poll, the issue read of a pre-flight, and the Jira column
names `ad-view` gives a saved `pncli jira search` / `pncli jira get-issue` answer.

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

# The column names a Jira read answers with (`connectors/jira_columns.py`): `ad-view` renders a saved
# `pncli jira search` / `pncli jira get-issue` answer with exactly these, and so do the in-process reads below.
from .jira_columns import JIRA_DEFAULT_FIELDS, JIRA_RENAME, ISSUE_RENAME, ISSUE_RENAME_BACK  # noqa: F401 (re-exported)
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


# Options known to take no value, so the token after one is not its value (#524). Anything else that
# starts with `-` and carries no `=` is assumed to take the next token: in doubt, that is a write.
_NO_VALUE = frozenset({"--help", "-h", "--dry-run", "--version"})


def has_flag(args: list[str], *names: str) -> bool:
    """Is one of `names` a flag in its own position? Not the value of the option before it
    (`--title -h`, `--title --dry-run`), and not after `--`. Without pncli's verb table, any option not
    in `_NO_VALUE` is taken to take a value. Shared by help (#524) and dry run (#525)."""
    value_next = False
    for a in args:
        if a == "--":
            return False
        if value_next:
            value_next = False
            continue
        if a in names:
            return True
        if a.startswith("-"):
            value_next = "=" not in a and a not in _NO_VALUE
    return False


def asks_for_help(args: list[str]) -> bool:
    """`--help` / `-h` as a flag of its own (#524)."""
    return has_flag(args, "--help", "-h")


def is_dry_run(args: list[str]) -> bool:
    """`--dry-run` as a flag of its own (#525): as an option's value pncli sends the real write."""
    return has_flag(args, "--dry-run")


def is_write(args: list[str]) -> bool:
    """Would running this change something on a system of record?

    `--dry-run` is not a write whatever the verb: pncli resolves and prints, and sends nothing. Nor is
    `--help` / `-h`: commander.js prints the help and exits before the action runs. Each counts only
    as a flag of its own (`has_flag`); as an option's value, or after `--`, it is not, and the verb
    still runs (#524, #525).
    """
    if is_dry_run(args) or asks_for_help(args):
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
                f"`pncli {' '.join(args[:2])} {opt} {value}`")
    m = _UNKNOWN.search(text)
    if m:
        return (f"pncli has no {m.group(1)} {m.group(3)!r}: run `pncli {args[0] if args else ''} --help` once, "
                "use a listed verb, and report it so the skill can pin it. Do not guess a second time.")
    return ""


# A fleet agent's PATH starts with the fleet's pncli shim (`fleet/pncli_gate.py`); `launch.child_env` names its
# directory here. Every launch from this package resolves the REAL pncli with that directory left out, so the
# gated extensions (`ad-confluence publish`, `ad-git pr`) are not refused by the shim, and the shim never runs itself.
SHIM_ENV = "AGENTDATA_PNCLI_SHIM"


def shim_dirs() -> list[str]:
    return [d for d in os.environ.get(SHIM_ENV, "").split(os.pathsep) if d.strip()]


def _in_shim_dir(path: str, dirs: list[str]) -> bool:
    here = os.path.normcase(os.path.abspath(os.path.dirname(path)))
    return any(here == os.path.normcase(os.path.abspath(d)) for d in dirs)


def search_path() -> str | None:
    """PATH without the shim's directory, or None (the plain PATH) when no shim is set."""
    dirs = shim_dirs()
    if not dirs:
        return None
    keep = [p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p.strip() and not any(os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(d))
                                     for d in dirs)]
    return os.pathsep.join(keep)


def exe(cfg: dict | None = None) -> str | None:
    """Pinned launcher path: PNCLI_EXE, else the `pncli.exe` config key. None = resolve `pncli` over PATH.
    A pin that points into the shim's directory is ignored: that is the gate, not pncli."""
    cfg = C.load() if cfg is None else cfg
    pinned = os.environ.get("PNCLI_EXE") or C.get(cfg, "pncli.exe") or None
    if pinned and shim_dirs() and _in_shim_dir(pinned, shim_dirs()):
        return None
    return pinned


def install_hint(cfg: dict | None = None) -> str:
    pkg = C.get(C.load() if cfg is None else cfg, "pncli.npm_package") or NPM_PACKAGE
    return (f"pncli is an npm package: install it with `npm install -g {pkg}` (it lands as pncli.cmd, never pncli.exe), "
            "or pin its path with PNCLI_EXE / `ad-setup --only pncli`. `ad-doctor --only pncli` shows what was tried.")


def where(cfg: dict | None = None) -> dict:
    """How `pncli` resolves on this machine: path, kind (executable / npm shim / cmd shim), node entry, version."""
    cfg = C.load() if cfg is None else cfg
    info = proc.resolve("pncli", exe=exe(cfg), path=search_path())
    if info["found"]:
        try:
            rc, out, err, _el = proc.run(["pncli", "--version"], exe=exe(cfg), timeout=60, path=search_path())
            line = (out or err).strip().splitlines()
            info["version"] = line[0][:60] if line else ""
            info["rc"] = rc
        except proc.ProcError as e:
            info["version"], info["rc"], info["error"] = "", -1, e.msg
    return info


def get_issue_from_payload(payload, fields: list[str] | None = None, source: str = "pncli jira get-issue") -> AgentTable:
    """One issue as pncli's `jira get-issue` answers it, with the issue columns (`ISSUE_RENAME`)."""
    recs = extract_records(payload)
    t = AgentTable.from_records(recs, name="issue", source=source,
                                fields=[ISSUE_RENAME_BACK.get(f, f) for f in fields] if fields else None, raw=payload)
    t.columns = [ISSUE_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    return t


def get_issue(key: str, fields: list[str] | None = None) -> AgentTable:
    """One issue. `jira get-issue --key <KEY>`: the verb and its named option are confirmed against pncli."""
    payload, el = run(["jira", "get-issue", "--key", key])
    t = get_issue_from_payload(payload, fields, source=f"pncli jira get-issue --key {key}")
    t.elapsed_s = el
    return t


def run(args: list[str], timeout: int = 120, cfg: dict | None = None) -> tuple[dict | list, float]:
    cfg = C.load() if cfg is None else cfg
    hint = install_hint(cfg)
    rc, out, err, el = proc.run(["pncli", *args], exe=exe(cfg), timeout=timeout, hint=hint, path=search_path())
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


def jira_search_from_payload(payload, fields: list[str] | None = None, max_results: int | None = None,
                             source: str = "pncli jira search") -> AgentTable:
    """A `jira search` answer with the search columns (`JIRA_RENAME`); short names like `status` are accepted."""
    recs = extract_records(payload)
    short = {v: k for k, v in JIRA_RENAME.items()}
    want = [short.get(f, f) for f in (fields or JIRA_DEFAULT_FIELDS)]
    t = AgentTable.from_records(recs, name="jira", source=source, fields=want, raw=payload)
    t.columns = [JIRA_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    t.truncated = max_results is not None and len(recs) >= max_results
    return t


def jira_search(jql: str, fields: list[str] | None = None, max_results: int = 500) -> AgentTable:
    payload, el = run(["jira", "search", "--jql", jql, "--max-results", str(max_results)])
    t = jira_search_from_payload(payload, fields, max_results, source=f"pncli jira search --jql {jql!r}")
    t.elapsed_s = el
    return t


def payload_kind(payload) -> str:
    """`search` for a Jira search answer (an `issues` list of issue objects), `issue` for one issue (an object
    with `key` and `fields`, or the same under `data` / `result`), else `""`."""
    if isinstance(payload, dict):
        issues = payload.get("issues")
        if isinstance(issues, list) and issues and all(isinstance(i, dict) and ("fields" in i or "key" in i)
                                                       for i in issues):
            return "search"
        if isinstance(payload.get("key"), str) and isinstance(payload.get("fields"), dict):
            return "issue"
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                inner = payload_kind(payload[k])
                if inner:
                    return inner
    return ""


# ------------------------------------------------------------------ pinned write verbs (the gated extensions)

# The write verbs `ad-confluence publish` and `ad-git pr` run are argv templates the operator pins once pncli's
# own `--help` has been read (`ad-setup --only pncli --non-interactive --set pncli.verbs.page_create="..."`). They
# are never guessed: an unset template is a `not_pinned` refusal, never a default.
VERBS = {
    "page_create": ("space", "title", "parent", "body"),
    "page_update": ("page_id", "title", "body", "version"),
    "pr_create": ("title", "source", "target", "description", "draft"),
    "pr_update": ("pr_id", "title", "source", "target", "description", "draft"),
}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def verb_template(name: str, cfg: dict | None = None) -> str:
    cfg = C.load() if cfg is None else cfg
    return str(C.get(cfg, f"pncli.verbs.{name}") or "").strip()


def template_argv(template: str, values: dict) -> list[str]:
    """A pinned template as argv. The template is split first and the values put in after, so a value -- a page
    body, a PR description -- is always ONE argv element and never re-split or re-quoted. A token that is only a
    placeholder whose value is empty is left out together with the option before it (`--parent {parent}`).
    Raises ValueError for an unknown placeholder or a template that does not split."""
    import shlex
    try:
        tokens = shlex.split(template, posix=True)
    except ValueError as e:
        raise ValueError(f"the template does not split: {e}") from None
    out: list[str] = []
    for tok in tokens:
        for name in _PLACEHOLDER.findall(tok):
            if name not in values:
                raise ValueError(f"unknown placeholder {{{name}}}; this template takes "
                                 + ", ".join("{" + k + "}" for k in values))
        whole = _PLACEHOLDER.fullmatch(tok)
        if whole and values[whole.group(1)] in (None, ""):
            if out and out[-1].startswith("-"):
                out.pop()
            continue
        out.append(_PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), tok))
    return out


def shown_argv(argv: list[str], long_values: dict) -> str:
    """The argv as one line for a person, each long value (a body) replaced by `<N chars>`."""
    hidden = {str(v): f"<{len(str(v))} chars>" for v in long_values.values() if v}
    return " ".join(["pncli", *(hidden.get(a, a) for a in argv)])


def find(payload, *keys: str) -> str:
    """The first non-empty scalar under any of `keys`, depth first (a write's answer: an id, a URL)."""
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v)
        for v in payload.values():
            got = find(v, *keys)
            if got:
                return got
    elif isinstance(payload, list):
        for v in payload:
            got = find(v, *keys)
            if got:
                return got
    return ""


def url_of(payload) -> str:
    """A write's answer as a link: `url`, `html_url` or `href`, or Confluence's `_links.base` + `_links.webui`."""
    direct = find(payload, "url", "html_url", "web_url", "href")
    if direct.startswith("http"):
        return direct
    base, webui = find(payload, "base"), find(payload, "webui")
    if base.startswith("http") and webui:
        return base.rstrip("/") + "/" + webui.lstrip("/")
    return direct
