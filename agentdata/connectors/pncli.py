"""Run a pncli command, extract its result list, normalize. pncli always emits JSON; we never show it raw by default.

pncli is distributed as an npm package, so on Windows it exists as `pncli.cmd` (npm's command shim) and never as
`pncli.exe`: launching the bare name fails with `[WinError 2] The system cannot find the file specified`. All
resolution and launching therefore goes through `agentdata.proc`, which finds the shim (PATHEXT + the npm global
prefix) and runs its Node entry point directly, so an argument like `updated >= '2026-01-01'` is never re-parsed by
cmd.exe. `pncli.exe` in the config (or PNCLI_EXE) pins an explicit path."""
from __future__ import annotations
import json, os
from .. import config as C
from .. import proc
from ..model import AgentTable

NPM_PACKAGE = "@kolatts/pncli"      # laptop diagnosis 2026-09-02; override with the `pncli.npm_package` config key

JIRA_DEFAULT_FIELDS = ["key", "fields.status.name", "fields.assignee.displayName", "fields.priority.name",
                       "fields.updated", "fields.summary"]
JIRA_RENAME = {"fields.status.name": "status", "fields.assignee.displayName": "assignee",
               "fields.priority.name": "priority", "fields.updated": "updated", "fields.summary": "summary"}
LIST_KEYS = ("issues", "results", "values", "items", "data")


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


def run(args: list[str], timeout: int = 120, cfg: dict | None = None) -> tuple[dict | list, float]:
    cfg = C.load() if cfg is None else cfg
    hint = install_hint(cfg)
    rc, out, err, el = proc.run(["pncli", *args], exe=exe(cfg), timeout=timeout, hint=hint)
    text = out.strip() or err.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise proc.ProcError("bad_output", f"pncli exited {rc} without JSON: {text[:200] or '(no output)'}",
                             "run the same pncli command yourself to see its output; add --dry-run --pretty",
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
