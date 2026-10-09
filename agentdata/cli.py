# PYTHON_ARGCOMPLETE_OK
"""ad-* entry points. Every command prints TOON (or JSON with --raw) and nothing else."""
from __future__ import annotations
import argparse, os, sys
from .textio import read_text
from .model import AgentTable
from .policy import render, render_nested, error
from . import completion
from . import toon
from . import ui
from . import version
from .config import ConfigError, capabilities, load as load_config, project_facts
from .console import utf8_stdout
from .sqlcheck import check as sql_check, to_toon as sql_findings_toon


def _sql_main(connector: str, prog: str) -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog=prog)
    version.add_version(ap)
    ap.add_argument("--env", default=None, help=f"env name (default: `{connector}_env` or `env` fact in AGENTS.md)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql")
    g.add_argument("--sql-file")
    ap.add_argument("--max-rows", type=int, default=5000)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--name", default=None)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--pretty", action="store_true", help="draw the result as a table for a person to read "
                                                          "(same as AGENTDATA_UI=rich); the default is TOON")
    completion.autocomplete(ap)
    a = ap.parse_args()
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
    sql = a.sql or read_text(a.sql_file)
    facts = project_facts()
    env = a.env or facts.get(f"{connector}_env") or (facts.get("env") if connector == "teradata" else None)
    if not env:
        print(error("no --env given", f"pass --env or set `{connector}_env` (teradata: `env`) in AGENTS.md", connector)); sys.exit(2)
    warnings: list[str] = []
    mode = os.environ.get("AGENTDATA_SQLCHECK", "block").lower()  # block | warn | off (operator escape, not for agents)
    if mode != "off":
        try:
            caps = capabilities(load_config(), connector, env)
        except ConfigError:
            caps = {}
        findings = sql_check(sql, connector, caps)
        errors = [f for f in findings if f.severity == "error"]
        if errors and mode == "block":
            print(sql_findings_toon(findings, connector, {"env": env, "action": "fix the SQL, then rerun"})); sys.exit(2)
        warnings = [f"L{f.line} {f.rule}: {f.message} -> {f.fix}" for f in findings]
    try:
        mod = __import__(f"agentdata.connectors.{connector}", fromlist=["query"])
        with ui.progress(f"Running query on {connector} ({env})..."):
            t = mod.query(sql, env, a.max_rows, a.timeout)
        if a.name:
            t.name = a.name
        print(render(t, raw=a.raw, extra={"warnings": warnings} if warnings else None))
    except PermissionError as e:
        print(error(str(e), "rewrite as a single SELECT", connector)); sys.exit(2)
    except ConfigError as e:
        print(error(str(e), e.hint or "ad-setup --only sources", connector)); sys.exit(2)
    except Exception as e:  # noqa: BLE001
        print(error(type(e).__name__ + ": " + str(e)[:300], "check env/TGT (klist) or wiring; ad-doctor --online", connector)); sys.exit(1)


def main_td(): _sql_main("teradata", "ad-td")
def main_ora(): _sql_main("oracle", "ad-ora")
def main_hive(): _sql_main("hive", "ad-hive")
def main_impala(): _sql_main("impala", "ad-impala")


def main_view() -> None:
    """Render a file on disk through the format policy: a TSV, a CSV export, or a JSON answer (pncli's)."""
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-view", description="ad-view <file.tsv|file.csv|file.json>: a TSV or CSV a "
                                 "script wrote, or the JSON a direct `pncli` read saved under .agent/out/, as TOON "
                                 "(full rows stay in the file on disk)")
    ap.add_argument("path"); ap.add_argument("--name", default=None)
    ap.add_argument("--fields", default=None, help="JSON only: comma-separated columns to keep (a Jira search or "
                                                   "issue: short names like status, assignee, description)")
    version.add_version(ap)
    ap.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    completion.autocomplete(ap)
    a = ap.parse_args()
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
    lower = a.path.lower()
    if lower.endswith(".json"):
        rc = _view_json(a.path, a.name, [f.strip() for f in a.fields.split(",") if f.strip()] if a.fields else None)
        if rc:
            sys.exit(rc)
        return
    if lower.endswith(".csv"):
        # A dscmd export (dax-studio-export): the same reading as `python -m agentdata.csv2toon`,
        # which a fleet agent may not run -- `ad-view` it may.
        from .pbip.dax import read_csv

        table = read_csv(a.path, a.name or "result")
        if table is None:
            print(error(f"empty csv: {a.path}", "the export wrote no header; run the query again", "ad-view"))
            sys.exit(1)
        print(render(table))
        return
    print(render(AgentTable.read_tsv(a.path, a.name or "result")))


def _view_json(path: str, name: str | None, fields: list[str] | None) -> int:
    """`ad-view <file.json>`: pncli's answer, saved by `pncli ... > .agent/out/<name>.json`, through the policy.

    A Jira search or a single issue gets the columns the in-process reads give (`pncli.jira_search_from_payload`,
    `pncli.get_issue_from_payload`); anything else is pncli's result list, normalized (`render_nested`)."""
    import json
    from .connectors import pncli as P
    source = f"ad-view {path}"
    try:
        text = read_text(path)
    except OSError as e:
        print(error(f"cannot read {path}: {e.strerror or e}", "save pncli's answer first: "
                    "pncli <product> <verb> --<option> <value> > .agent/out/<name>.json", "ad-view"))
        return 2
    try:
        payload = json.loads(text) if text.strip() else None
    except json.JSONDecodeError as e:
        print(error(f"{path} is not JSON ({e.msg}, line {e.lineno})", "pncli prints JSON on stdout; a usage error goes "
                    "to stderr and leaves this file empty or partial: run the pncli command again and read its message",
                    "ad-view"))
        return 1
    if payload is None:
        print(error(f"{path} is empty", "the pncli command printed nothing: run it again and read its message", "ad-view"))
        return 1
    if isinstance(payload, dict) and payload.get("ok") is False:
        print(error(str(payload.get("error") or payload.get("message") or "pncli error")[:300],
                    "pncli refused the command: fix its options (named, never positional) and run it again", "ad-view"))
        return 1
    kind = P.payload_kind(payload)
    if kind == "search":
        t = P.jira_search_from_payload(payload, fields, source=source)
    elif kind == "issue":
        t = P.get_issue_from_payload(payload, fields, source=source)
    else:
        print(render_nested(P.extract_records(payload), name=name or "pncli", source=source, raw_payload=payload))
        return 0
    if name:
        t.name = name
    print(render(t))
    return 0


def main_diff() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-diff", description="Compare two TSVs on a key. Output TOON, never in-context math.")
    version.add_version(ap)
    ap.add_argument("left"); ap.add_argument("right"); ap.add_argument("--key", required=True)
    ap.add_argument("--cols", default=None, help="comma list of columns to compare (default: shared)")
    ap.add_argument("--show", type=int, default=20)
    completion.autocomplete(ap)
    a = ap.parse_args()
    L, R = AgentTable.read_tsv(a.left, "left"), AgentTable.read_tsv(a.right, "right")
    if a.key not in L.columns or a.key not in R.columns:
        print(error(f"key {a.key} missing", f"left cols={L.columns[:8]} right cols={R.columns[:8]}", "ad-diff")); sys.exit(2)
    cols = a.cols.split(",") if a.cols else [c for c in L.columns if c in R.columns and c != a.key]
    li, ri = L.columns.index(a.key), R.columns.index(a.key)
    lm = {str(r[li]): r for r in L.rows}; rm = {str(r[ri]): r for r in R.rows}
    only_l = [k for k in lm if k not in rm]; only_r = [k for k in rm if k not in lm]
    changed = []
    for k in lm.keys() & rm.keys():
        for c in cols:
            lv, rv = lm[k][L.columns.index(c)], rm[k][R.columns.index(c)]
            if str(lv) != str(rv):
                changed.append({"key": k, "col": c, "left": lv, "right": rv})
    out = {"meta": {"ok": True, "left_rows": L.n, "right_rows": R.n, "matched": len(lm.keys() & rm.keys()),
                    "only_left": len(only_l), "only_right": len(only_r), "changed": len(changed), "cols": cols},
           "only_left": only_l[:a.show], "only_right": only_r[:a.show], "changed": changed[:a.show]}
    print(toon.encode(out))


if __name__ == "__main__":
    main_view()
