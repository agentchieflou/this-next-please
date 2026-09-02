"""ad-* entry points. Every command prints TOON (or JSON with --raw) and nothing else."""
from __future__ import annotations
import argparse, os, sys
from .textio import read_text
from .model import AgentTable
from .policy import render, render_nested, error
from . import toon
from .config import ConfigError, capabilities, load as load_config, project_facts
from .console import utf8_stdout
from .sqlcheck import check as sql_check, to_toon as sql_findings_toon


def _sql_main(connector: str, prog: str) -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--env", default=None, help=f"env name (default: `{connector}_env` or `env` fact in AGENTS.md)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql")
    g.add_argument("--sql-file")
    ap.add_argument("--max-rows", type=int, default=5000)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--name", default=None)
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()
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


def main_pncli() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-pncli",
        description="ad-pncli jira search --jql '<JQL>' [--fields key,status,...] | ad-pncli raw <pncli args...>")
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("jira"); j.add_argument("verb", choices=["search"]); j.add_argument("--jql", required=True)
    j.add_argument("--fields", default=None); j.add_argument("--max-results", type=int, default=500)
    j.add_argument("--raw", action="store_true")
    r = sub.add_parser("raw", help="any pncli command; result list normalized by policy")
    r.add_argument("pargs", nargs=argparse.REMAINDER); r.add_argument("--raw", action="store_true", dest="raw_out")
    sub.add_parser("where", help="how pncli resolves on this machine (path, npm shim, node entry, version)")
    a = ap.parse_args()
    from . import proc
    from . import toon
    from .connectors import pncli as P
    try:
        if a.cmd == "where":
            info = P.where()
            meta = {"ok": bool(info["found"]) and info.get("rc", 0) == 0, "source": "ad-pncli where", **{k: v for k, v in info.items() if k != "tried"}}
            if not meta["ok"]:
                meta["hint"] = P.install_hint()
            print(toon.encode({"meta": meta, "tried": info["tried"]}))
            sys.exit(0 if meta["ok"] else 1)
        if a.cmd == "jira":
            t = P.jira_search(a.jql, a.fields.split(",") if a.fields else None, a.max_results)
            print(render(t, raw=a.raw))
        else:
            pargs = [x for x in a.pargs if x != "--raw"]  # REMAINDER swallows a trailing --raw
            raw_out = a.raw_out or len(pargs) != len(a.pargs)
            payload, el = P.run(pargs)
            source = "pncli " + " ".join(pargs)
            if raw_out:
                print(render(AgentTable(name="pncli", columns=[], rows=[], source=source, raw=payload), raw=True))
            else:
                print(render_nested(P.extract_records(payload), name="pncli", source=source, raw_payload=payload))
    except proc.ProcError as e:
        meta = {"ok": False, "source": "ad-pncli", "error": e.msg, "hint": e.hint, "refused": e.code, **e.detail}
        print(toon.encode({"meta": meta})); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(error(str(e)[:300], "run the same pncli command with --dry-run --pretty; `ad-pncli where` checks the launcher", "pncli")); sys.exit(1)


def main_view() -> None:
    """Re-render a TSV on disk through the policy (e.g., after a script wrote it)."""
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-view"); ap.add_argument("path"); ap.add_argument("--name", default="result")
    a = ap.parse_args()
    print(render(AgentTable.read_tsv(a.path, a.name)))


def main_diff() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-diff", description="Compare two TSVs on a key. Output TOON, never in-context math.")
    ap.add_argument("left"); ap.add_argument("right"); ap.add_argument("--key", required=True)
    ap.add_argument("--cols", default=None, help="comma list of columns to compare (default: shared)")
    ap.add_argument("--show", type=int, default=20)
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
    main_pncli()
