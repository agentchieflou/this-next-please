"""Live Jira against Jira-history-in-a-warehouse, in one command.

The skill that did this had nine steps, and step 2 was *write the SQL*. Every one of those steps
was mechanical -- pull the live side, write the history query, lint it, run it, diff on the key,
count the three classes, pick three examples, write the findings file -- and doing them by hand
meant doing them slightly differently each time, on a warehouse whose column names the author was
guessing at.

So this composes them, and leaves the two judgements that are actually judgements: *which* window
and JQL scope define the question (the ticket's acceptance criteria say, and `jira-triage` has
already read them), and what the differences mean once they are counted.

**Nothing here writes to Jira or to a warehouse.** One `SELECT`, linted by `ad-sql-check` before it
is sent, and the only file written is under `.agent/`.
"""
from __future__ import annotations
import os

from .. import config as C
from .. import textio
from ..model import AgentTable
from ..sqlcheck import check as sql_check
from . import jira_sql as Q

FINDINGS_MAX_LINES = 25
EXAMPLES = 3


class UatError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def facts_for(source: str, facts: dict | None = None) -> dict:
    """The names this query needs, from AGENTS.md, with the generic fact as the fallback.

    Per-source overrides exist because the same history lands in two warehouses under different
    names more often than not -- `jira_hist_table_hive` beside `jira_hist_table`.
    """
    facts = facts if facts is not None else C.project_facts()

    def fact(name: str, default: str = "") -> str:
        return str(facts.get(f"{name}_{source}") or facts.get(name) or default)

    return {"hist_table": fact("jira_hist_table"),
            "project": fact("jira_project"),
            "key_column": fact("jira_hist_key_column", "ISSUE_KEY"),
            "ts_column": fact("jira_hist_ts_column", "CHANGED_TS"),
            "project_column": fact("jira_hist_project_column", "PROJECT_KEY"),
            "env": fact(f"{source}_env") or str(facts.get("env") or "")}


def write_sql(*, ticket: str, source: str, end: str, fields: list[str], facts: dict,
              sql_dir: str = os.path.join(".agent", "sql")) -> dict:
    """Generate both queries, lint them, and refuse rather than hand a bad one to a warehouse."""
    names = facts_for(source, facts)
    if not names["hist_table"]:
        raise UatError("no Jira history table is configured",
                       f"add `jira_hist_table:` (or `jira_hist_table_{source}:`) to AGENTS.md")
    if not names["project"]:
        raise UatError("no Jira project key is configured", "add `jira_project:` to AGENTS.md")

    try:
        history = Q.history_sql(dialect=source, hist_table=names["hist_table"],
                                project=names["project"], end=end, ticket=ticket,
                                key_column=names["key_column"], ts_column=names["ts_column"],
                                project_column=names["project_column"], columns=fields)
        coverage = Q.coverage_sql(dialect=source, hist_table=names["hist_table"],
                                  project=names["project"], end=end, ticket=ticket,
                                  key_column=names["key_column"], ts_column=names["ts_column"],
                                  project_column=names["project_column"])
    except Q.SqlError as e:
        raise UatError(e.msg, e.hint) from None

    # The same linter the query commands run, on the way out rather than on the way in. A generator
    # that produced SQL its own project would refuse is worse than no generator: it moves the
    # failure to the warehouse, where the message is someone else's.
    findings = sql_check(history, source, {})
    errors = [f"L{f.line} {f.rule}: {f.message} -> {f.fix}" for f in findings if f.severity == "error"]
    if errors:
        raise UatError(f"the generated {source} SQL does not pass ad-sql-check: {errors[0]}",
                       "this is a bug in the generator, not in your configuration -- please report it "
                       "with the AGENTS.md facts used")

    os.makedirs(sql_dir, exist_ok=True)
    hist_path = textio.write_text(os.path.join(sql_dir, f"{ticket}-uat.sql"), history)
    cov_path = textio.write_text(os.path.join(sql_dir, f"{ticket}-uat-cov.sql"), coverage)
    return {"sql": hist_path, "coverage_sql": cov_path, "names": names,
            "warnings": [f"L{f.line} {f.rule}: {f.message}" for f in findings if f.severity != "error"]}


# ------------------------------------------------------------------------------ the two sides


def live_side(jql: str, fields: list[str], max_results: int = 2000, client=None) -> AgentTable:
    """What Jira says now. The truth the warehouse is being checked against."""
    if client is None:
        from ..connectors import pncli

        client = pncli
    return client.jira_search(jql, ["key", *fields], max_results)


def history_side(sql_path: str, source: str, env: str, max_rows: int = 20000,
                 timeout: int = 300, runner=None) -> AgentTable:
    if runner is None:
        module = __import__(f"agentdata.connectors.{source}", fromlist=["query"])
        runner = module.query
    return runner(textio.read_text(sql_path), env, max_rows, timeout)


# ------------------------------------------------------------------------------ the comparison


def compare(live: AgentTable, hist: AgentTable, *, key: str = "key",
            cols: list[str] | None = None) -> dict:
    """`ad-diff`'s comparison, in process, so the classification can name examples from it.

    Deliberately the same three classes the skill has always defined -- `only_left` is missing from
    the warehouse, `only_right` is stale in it, `changed` is lag or a mapping bug -- because those
    are what the findings file has to say and what whoever reads it already knows.
    """
    if key not in live.columns:
        raise UatError(f"the live side has no {key!r} column", f"columns: {live.columns[:8]}")
    if key not in hist.columns:
        raise UatError(f"the history side has no {key!r} column",
                       f"columns: {hist.columns[:8]}. The generated SQL aliases it as \"key\"; a "
                       f"warehouse that lower-cases identifiers may need the alias adjusting")

    shared = [c for c in (cols or [c for c in live.columns if c != key]) if c in hist.columns]
    li, ri = live.columns.index(key), hist.columns.index(key)
    left = {str(r[li]): r for r in live.rows}
    right = {str(r[ri]): r for r in hist.rows}

    changed = []
    for k in sorted(left.keys() & right.keys()):
        for c in shared:
            lv = left[k][live.columns.index(c)]
            rv = right[k][hist.columns.index(c)]
            if _same(lv, rv):
                continue
            changed.append({"key": k, "col": c, "live": lv, "history": rv})
    return {"only_live": sorted(k for k in left if k not in right),
            "only_history": sorted(k for k in right if k not in left),
            "changed": changed, "matched": len(left.keys() & right.keys()),
            "compared": shared, "live_rows": live.n, "history_rows": hist.n}


def _same(a, b) -> bool:
    """Blank and null are the same absence on two sides that spell it differently."""
    if a is None or a == "":
        return b is None or b == ""
    return str(a).strip() == str(b).strip()


def truncation_warning(live: AgentTable, hist: AgentTable) -> str:
    """Step 3 of the old skill, kept because it is the one check that invalidates everything else.

    A truncated side makes every key beyond the cut look "missing from the warehouse", and the
    finding reads as a data problem when it is a `--max-results` problem.
    """
    if getattr(live, "truncated", False) or getattr(hist, "truncated", False):
        which = "live" if getattr(live, "truncated", False) else "history"
        return (f"the {which} side was truncated, so the counts below are not comparable: "
                f"narrow the window or raise the row limit and run it again")
    if live.n and hist.n:
        gap = abs(live.n - hist.n) / max(live.n, hist.n)
        if gap > 0.02:
            return (f"the two sides differ in size by {gap:.0%} ({live.n} live, {hist.n} history) -- "
                    f"check for truncation before reading anything into the classes")
    return ""


# ------------------------------------------------------------------------------ what to write


def findings_md(*, ticket: str, source: str, jql: str, window: tuple[str, str], result: dict,
                sql_path: str, warning: str = "") -> str:
    """The contract the skill has always had: counts, classification, three examples, a
    recommendation, and under 25 lines. Short because it is read, not skimmed."""
    start, end = window
    only_live, only_hist, changed = result["only_live"], result["only_history"], result["changed"]
    lines = [f"# {ticket}: live Jira vs {source} history",
             "",
             f"Window {start} to {end}. Scope `{jql}`. Query `{sql_path}`.",
             f"{result['live_rows']} live rows, {result['history_rows']} history rows, "
             f"{result['matched']} keys on both sides.",
             ""]
    if warning:
        lines += [f"**{warning}**", ""]
    lines += ["| Class | Count | Means |",
              "| --- | --- | --- |",
              f"| only in Jira | {len(only_live)} | missing from the warehouse |",
              f"| only in {source} | {len(only_hist)} | stale in the warehouse |",
              f"| different | {len(changed)} | load lag, or a mapping bug |",
              ""]

    examples = ([f"- `{k}` is in Jira and not in {source}" for k in only_live[:EXAMPLES]]
                + [f"- `{k}` is in {source} and not in Jira" for k in only_hist[:EXAMPLES]]
                + [f"- `{c['key']}` {c['col']}: Jira `{c['live']}`, {source} `{c['history']}`"
                   for c in changed[:EXAMPLES]])
    if examples:
        lines += ["## Examples", *examples[:EXAMPLES * 2], ""]

    lines += ["## Recommendation", _recommend(source, result, warning)]
    return "\n".join(lines[:FINDINGS_MAX_LINES]) + "\n"


def _recommend(source: str, result: dict, warning: str) -> str:
    if warning:
        return ("Re-run with a narrower window before drawing a conclusion; these counts are not "
                "trustworthy while one side is truncated.")
    only_live, only_hist, changed = result["only_live"], result["only_history"], result["changed"]
    if not (only_live or only_hist or changed):
        return f"The two sides agree on every key and column compared. No action."
    parts = []
    if only_live:
        parts.append(f"{len(only_live)} key(s) have not reached {source}: check the load's watermark")
    if only_hist:
        parts.append(f"{len(only_hist)} key(s) are in {source} and not in the live scope: either the "
                     f"JQL is narrower than the load, or they were deleted in Jira")
    if changed:
        parts.append(f"{len(changed)} value(s) differ: compare the changed keys' timestamps against "
                     f"the load window to tell lag from a mapping bug")
    return ". ".join(parts) + "."


# ------------------------------------------------------------------------------------ the run


def run(*, ticket: str, source: str, jql: str, window: tuple[str, str], fields: list[str],
        facts: dict | None = None, sql_dir: str = os.path.join(".agent", "sql"),
        out_dir: str = os.path.join(".agent", "out"), plan_only: bool = False,
        jira_client=None, sql_runner=None, max_results: int = 2000) -> dict:
    """The whole reconciliation. `plan_only` stops after the SQL is written and linted."""
    if source not in Q.DIALECTS:
        raise UatError(f"unknown source {source!r}", "one of " + " | ".join(Q.DIALECTS))
    start, end = window
    facts = facts if facts is not None else C.project_facts()
    written = write_sql(ticket=ticket, source=source, end=end, fields=fields, facts=facts,
                        sql_dir=sql_dir)

    plan = {"ok": True, "ticket": ticket, "source": source, "jql": jql,
            "window": f"{start},{end}", "sql": written["sql"],
            "coverage_sql": written["coverage_sql"], "warnings": written["warnings"]}
    if plan_only:
        plan["next"] = (f"review the column names in {written['sql']}, then run the same command "
                        f"without --plan-only")
        return plan

    env = written["names"]["env"]
    if not env:
        raise UatError(f"no {source} environment is configured",
                       f"add `{source}_env:` to AGENTS.md, or pass --env")

    live = live_side(jql, fields, max_results, jira_client)
    hist = history_side(written["sql"], source, env, runner=sql_runner)
    result = compare(live, hist, cols=fields)
    warning = truncation_warning(live, hist)

    os.makedirs(out_dir, exist_ok=True)
    body = findings_md(ticket=ticket, source=source, jql=jql, window=(start, end), result=result,
                       sql_path=written["sql"], warning=warning)
    findings_path = textio.write_text(os.path.join(out_dir, f"{ticket}-uat-findings.md"), body)

    return {**plan, "live_rows": result["live_rows"], "history_rows": result["history_rows"],
            "matched": result["matched"], "only_live": len(result["only_live"]),
            "only_history": len(result["only_history"]), "changed": len(result["changed"]),
            "compared": result["compared"], "findings": findings_path,
            "truncation_warning": warning, "result": result}
