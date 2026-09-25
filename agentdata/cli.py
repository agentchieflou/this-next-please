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


def main_pncli() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-pncli",
        description="ad-pncli jira search --jql '<JQL>' | ad-pncli jira get <KEY> | "
                    "ad-pncli jira comments <KEY> | "
                    "ad-pncli raw [--body-file page.html] <pncli args...> | ad-pncli where | "
                    "ad-pncli capture-help [--out FILE] (the operator's: every `pncli --help` the PR and "
                    "page commands need, redacted, in one file to attach)")
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("jira", help="search issues by JQL, or read one issue (pncli's named options are built here)")
    j.add_argument("verb", choices=["search", "get", "comments"]); j.add_argument("target", nargs="?", help="issue key for `get` / `comments`, JQL for `search`")
    j.add_argument("--jql", default=None); j.add_argument("--key", default=None, help="issue key for `get` / `comments`")
    j.add_argument("--fields", default=None); j.add_argument("--max-results", type=int, default=500)
    j.add_argument("--raw", action="store_true")
    r = sub.add_parser("raw", help="any pncli command; result list normalized by policy")
    r.add_argument("--body-file", help="read this file and append it as one argument (default `--body <contents>`): "
                                       "pncli takes an inline body, and a page of HTML cannot survive shell quoting")
    r.add_argument("--body-arg", default="--body", help="the option the body belongs to (default --body)")
    r.add_argument("pargs", nargs=argparse.REMAINDER); r.add_argument("--raw", action="store_true", dest="raw_out")
    sub.add_parser("where", help="how pncli resolves on this machine (path, npm shim, node entry, version)")
    ch = sub.add_parser("capture-help", help="the operator's, in their own terminal: run `pncli --help` for bitbucket, "
                        "confluence and jira and every verb they list, and write the answers, hosts and home redacted, "
                        "into one file to read and attach (WRAP-D6). Nothing but --help and --version is run")
    ch.add_argument("--out", default=None, help="the file to write (default: pncli-help-<version>-<yyyymmdd>.txt "
                                                "beside the config file)")
    ch.add_argument("--max", type=int, default=40, help="at most this many verb --help calls (default 40)")
    completion.autocomplete(ap)
    a = ap.parse_args()
    from . import confluence, proc     # deferred: only ad-pncli needs them
    from .connectors import pncli as P
    try:
        if a.cmd == "where":
            info = P.where()
            meta = {"ok": bool(info["found"]) and info.get("rc", 0) == 0, "source": "ad-pncli where", **{k: v for k, v in info.items() if k != "tried"}}
            if not meta["ok"]:
                meta["hint"] = P.install_hint()
            print(toon.encode({"meta": meta, "tried": info["tried"]}))
            sys.exit(0 if meta["ok"] else 1)
        if a.cmd == "capture-help":
            sys.exit(_capture_help(a, P))
        if a.cmd == "jira" and a.verb == "get":
            key = a.key or a.target
            if not key:
                print(error("no issue key", "ad-pncli jira get <KEY> (pncli's own option is --key; ad-pncli passes it for you)", "pncli")); sys.exit(2)
            print(render(P.get_issue(key, a.fields.split(",") if a.fields else None), raw=a.raw))
        elif a.cmd == "jira" and a.verb == "comments":
            key = a.key or a.target
            if not key:
                print(error("no issue key", "ad-pncli jira comments <KEY> (pncli's own option is --key; ad-pncli passes it for you)", "pncli")); sys.exit(2)
            print(render(P.get_comments(key), raw=a.raw))
        elif a.cmd == "jira":
            jql = a.jql or a.target
            if not jql:
                print(error("no JQL", 'ad-pncli jira search --jql "key = <KEY>"', "pncli")); sys.exit(2)
            t = P.jira_search(jql, a.fields.split(",") if a.fields else None, a.max_results)
            print(render(t, raw=a.raw))
        else:
            pargs = [x for x in a.pargs if x != "--raw"]  # REMAINDER swallows a trailing --raw
            raw_out = a.raw_out or len(pargs) != len(a.pargs)
            shown = list(pargs)
            if a.body_file:
                # the body goes across as ONE argv element: no shell, so quotes, newlines and < > in the HTML are safe
                body = read_text(a.body_file)
                why = confluence.looks_like_markdown(body) if "confluence" in pargs else ""
                if why:
                    print(error(f"{a.body_file} is Markdown, not Confluence storage format ({why})",
                                f"Confluence renders it literally; build the body first: ad-confluence html {a.body_file}", "pncli"))
                    sys.exit(2)
                pargs = [*pargs, a.body_arg, body]
                shown = [*shown, a.body_arg, f"<{len(body)} chars from {a.body_file}>"]
            if P.is_write(pargs):
                # Unattended, a write to a system of record waits for one operator click. In
                # PyCharm this returns before it touches the disk. What is shown for approval is
                # `shown`, never `pargs`: a Confluence body is thousands of characters and the
                # operator is deciding about the command, not reading the HTML.
                from .fleet import approval

                d = approval.require("pncli-write", "pncli " + " ".join(shown),
                                     {"command": " ".join(shown), "verb": " ".join(P.verb(pargs))})
                if not d.ok:
                    print(toon.encode({"meta": approval.refusal(d, "ad-pncli raw")}))
                    sys.exit(2)
            payload, el = P.run(pargs)
            source = "pncli " + " ".join(shown)
            if raw_out:
                print(render(AgentTable(name="pncli", columns=[], rows=[], source=source, raw=payload), raw=True))
            else:
                print(render_nested(P.extract_records(payload), name="pncli", source=source, raw_payload=payload))
    except proc.ProcError as e:
        meta = {"ok": False, "source": "ad-pncli", "error": e.msg, "hint": e.hint, "refused": e.code, **e.detail}
        print(toon.encode({"meta": meta})); sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(error(str(e)[:300], "run the same pncli command with --dry-run --pretty; `ad-pncli where` checks the launcher", "pncli")); sys.exit(1)


def _capture_help(a, P) -> int:
    """`ad-pncli capture-help` (#498): the laptop's pncli help, redacted, in one file the operator attaches."""
    import time
    from . import config as C, textio
    from .fleet import approval
    if approval.in_fleet():
        print(toon.encode({"meta": {"ok": False, "source": "ad-pncli capture-help", "refused": "operator_only",
                                    "error": "capture-help is the operator's: it writes a file for the operator to read and attach",
                                    "hint": "run `ad-pncli capture-help` in your own terminal, not from a fleet agent"}}))
        return 2
    cfg = load_config()
    got = P.capture_help(max_verbs=max(0, a.max), cfg=cfg)
    if not got["started"]:
        first = got["calls"][0]
        print(error(f"pncli did not start: {first['out']}", got["hint"], "ad-pncli capture-help"))
        return 1
    hosts, home = P.redaction_hosts(cfg), os.path.expanduser("~")
    counts: dict[str, int] = {}
    blocks = []
    for c in got["calls"]:
        text, n = P.redact(c["out"], hosts, home)
        for k, v in n.items():
            counts[k] = counts.get(k, 0) + v
        blocks.append(f"==== {' '.join(c['argv'])} | exit {c['rc']} | {c['ms']} ms\n{text.rstrip()}\n")
    captured = sum(1 for c in got["calls"] if c["rc"] == 0)
    failed = len(got["calls"]) - captured
    redacted = ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())) or "nothing matched"
    day = time.strftime("%Y%m%d")
    out = a.out or os.path.join(os.path.dirname(C.path()), f"pncli-help-{got['version']}-{day}.txt")
    head = [f"# pncli help capture: pncli {got['version']}, {time.strftime('%Y-%m-%d %H:%M')} (ad-pncli capture-help, #498)",
            "# redacted: the configured Jira, Confluence and Bitbucket hosts as <jira-host>, <confluence-host> and "
            "<bitbucket-host>; any other http(s) host as <host>; the home directory as <home>",
            f"# redacted here: {redacted}",
            f"# calls: {len(got['calls'])}, exit 0: {captured}, failed: {failed}"
            + (f", verbs left out by --max: {got['left_out']}" if got.get("left_out") else ""),
            "# read it before you attach it: this repository is public", ""]
    textio.write_text(out, "\n".join(head) + "\n" + "\n".join(blocks))
    meta = {"ok": True, "source": "ad-pncli capture-help", "file": C.display_path(out), "captured": captured,
            "failed": failed, "redacted": redacted, "left_out": got.get("left_out", 0),
            "next": "read it, then attach it to the issue for `ad-pncli bitbucket pr` (#506)"}
    print(toon.encode({"meta": meta}))
    return 0


def main_view() -> None:
    """Re-render a TSV on disk through the policy (e.g., after a script wrote it)."""
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-view"); ap.add_argument("path"); ap.add_argument("--name", default="result")
    version.add_version(ap)
    ap.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    completion.autocomplete(ap)
    a = ap.parse_args()
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
    print(render(AgentTable.read_tsv(a.path, a.name)))


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
    main_pncli()
