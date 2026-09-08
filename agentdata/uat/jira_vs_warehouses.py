"""Live Jira against two warehouse histories, and the two warehouses against each other.

Not the single-engine reconciliation run twice. The business question behind this one is *migration
parity* -- has the move from one platform to the other reproduced the data -- and that is a
comparison neither single run can make: each would report "this warehouse disagrees with Jira" and
neither would notice that the two warehouses disagree with each other, which is the finding that
names the migration rather than the load.

So the third comparison is a class of its own (`warehouse-drift`), and it is checked *before* the
Jira comparisons: reporting drift as "hist disagrees with Jira" would name one platform and hide
that the other one differs too.
"""
from __future__ import annotations
import os

from .. import config as C
from .. import textio
from ..model import AgentTable
from . import jira_sql as Q
from . import jira_vs_source as JV
from . import reconcile as R


def run(*, ticket: str, sources: list[str], jql: str, window: tuple[str, str], fields: list[str],
        facts: dict | None = None, sql_dir: str = os.path.join(".agent", "sql"),
        out_dir: str = os.path.join(".agent", "out"), plan_only: bool = False,
        jira_client=None, sql_runners: dict | None = None, max_results: int = 2000,
        tol: float = 0.0) -> dict:
    """Generate both queries, run both sides plus live Jira, and reconcile all three."""
    for source in sources:
        if source not in Q.DIALECTS:
            raise JV.UatError(f"unknown source {source!r}", "one of " + " | ".join(Q.DIALECTS))
    first, second = sources
    start, end = window
    facts = facts if facts is not None else C.project_facts()

    written = {}
    for source in sources:
        # One file per engine, named by engine: two files called `<ticket>-uat.sql` would overwrite
        # each other, and the whole point here is having both to compare.
        written[source] = JV.write_sql(ticket=f"{ticket}-{source}", source=source, end=end,
                                       fields=fields, facts=facts, sql_dir=sql_dir)

    plan = {"ok": True, "ticket": ticket, "sources": sources, "jql": jql,
            "window": f"{start},{end}",
            "sql": ", ".join(written[s]["sql"] for s in sources),
            "warnings": [w for s in sources for w in written[s]["warnings"]]}
    if plan_only:
        plan["next"] = ("review the column names in both files -- the two warehouses rarely use the "
                        "same ones -- then run the same command without --plan-only")
        return plan

    live = JV.live_side(jql, fields, max_results, jira_client)
    histories = {}
    for source in sources:
        env = written[source]["names"]["env"]
        if not env:
            raise JV.UatError(f"no {source} environment is configured",
                              f"add `{source}_env:` to AGENTS.md")
        runner = (sql_runners or {}).get(source)
        histories[source] = JV.history_side(written[source]["sql"], source, env, runner=runner)

    result = R.reconcile(expected=None, jira=live, hist=histories[first],
                         hist2=histories[second], hist2_name=second, pbi=None,
                         key="key", cols=fields, window=window, tol=tol)

    warnings = []
    for source in sources:
        warning = JV.truncation_warning(live, histories[source])
        if warning:
            warnings.append(f"{source}: {warning}")

    os.makedirs(out_dir, exist_ok=True)
    body = findings_md(ticket=ticket, sources=sources, jql=jql, window=window, result=result,
                       live=live, histories=histories, sql=written, warnings=warnings)
    path = textio.write_text(os.path.join(out_dir, f"{ticket}-uat-findings.md"), body)

    return {**plan, "counts": result["counts"], "findings": path,
            "live_rows": live.n, "matched": result["keys_total"],
            "history_rows": {s: histories[s].n for s in sources},
            "warnings": warnings, "result": result}


def findings_md(*, ticket: str, sources: list[str], jql: str, window: tuple[str, str],
                result: dict, live: AgentTable, histories: dict, sql: dict,
                warnings: list[str], max_lines: int = 40) -> str:
    """The existing findings contract, plus a section that answers the migration question directly.

    Separated on purpose: "do the two platforms agree" is the question that was asked, and burying
    it among the per-warehouse classes would mean reading the whole file to find the answer.
    """
    first, second = sources
    start, end = window
    counts = result["counts"]
    drift = [f for f in result["findings"] if f["class"] == "warehouse-drift"]

    lines = [f"# {ticket}: live Jira vs {first} and {second}", "",
             f"Window {start} to {end}. Scope `{jql}`.",
             f"{live.n} live rows · {first} {histories[first].n} · {second} {histories[second].n} · "
             f"{result['keys_total']} keys compared on {', '.join(result['cols'])}.", ""]
    for warning in warnings:
        lines.append(f"**{warning}**")
    if warnings:
        lines.append("")

    lines += [f"## Do {first} and {second} agree?", ""]
    if drift:
        lines += [f"**No — {len(drift)} value(s) differ between the two warehouses.** That is a "
                  f"migration finding: whatever either platform says about Jira, they do not say "
                  f"the same thing as each other.", ""]
        for f in drift[:3]:
            lines.append(f"- `{f['key']}` {f['col']}: {first} `{_show(f['hist'])}`, "
                         f"{second} `{_show(f['hist2'])}` — {f['note']}")
        lines.append("")
    else:
        lines += [f"Yes — every compared value is identical in {first} and {second}.", ""]

    lines += ["## Against live Jira", "",
              "counts: " + (" · ".join(f"{c} {n}" for c, n in counts.items() if n and c != "ok")
                            or "every comparison agrees"), ""]
    for name in ("history-gap", "lag", "mapping-bug", "missing"):
        rows = [f for f in result["findings"] if f["class"] == name]
        if not rows:
            continue
        lines.append(f"- **{name}** ({len(rows)}): {R.DEFINITION[name]}")
        lines.append(f"  - e.g. `{rows[0]['key']}` {rows[0]['col']}: {rows[0]['note']}")

    lines += ["", "## Recommendation"]
    present = [c for c in R.CLASSES if counts.get(c)]
    lines += [f"- {c}: {R.RECOMMENDATION[c]}" for c in present] or ["- no action"]
    lines += ["", f"Queries: {sql[first]['sql']} · {sql[second]['sql']}"]
    return "\n".join(lines[:max_lines]).rstrip() + "\n"


def _show(value) -> str:
    return "–" if value is None else str(value)
