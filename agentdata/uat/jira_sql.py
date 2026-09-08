"""The Jira-history-in-a-warehouse query, generated per dialect rather than written out by hand.

The `uat-jira-vs-teradata` skill used to say, in step 2: *write `.agent/sql/<ticket>-uat.sql`
selecting the same grain (one row per issue key, latest status ≤ the window end)*. No template, no
generator — so the same query was composed from nothing on every ticket, and on a warehouse the
author had not used this month.

That is exactly the query where the three engines disagree, and where `ad-sql-check` already knows
they do:

* **Teradata** has `QUALIFY`, and refuses `TOP` in the same statement as it.
* **Hive** has `QUALIFY` only from 4.0, so anything older needs the windowed subquery.
* **Impala** has no `QUALIFY` at all.

So the shape has to change with the engine, not just the quoting — a generator that emitted one SQL
and let the linter complain would have moved the hand-authoring rather than removed it. What comes
out of here passes `ad-sql-check --dialect <engine>` on the engine it was asked for, and there is a
test per dialect that runs the real linter over the real output.

**Read-only, always.** One `SELECT`. The guardrail in `sqlcheck` is not bypassed anywhere here, and
`ad-uat jira-vs-source` runs the generated file through it before it reaches a warehouse.
"""
from __future__ import annotations
import re

DIALECTS = ("teradata", "hive", "impala", "oracle")

# The columns this grain needs, and the names they are given on the way out. `key` matches what
# `ad-pncli jira search` returns on the live side, so `ad-diff --key key` needs no renaming step.
DEFAULT_COLUMNS = ("status", "assignee")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)*$")


class SqlError(ValueError):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def _ident(value: str, what: str) -> str:
    """A table or column name that came from configuration, not from a user typing SQL.

    Refused rather than quoted: everything here is a project fact or a `--fields` list, and a value
    that is not an identifier means the fact is wrong. Quoting it would build a query that fails
    later, in the warehouse, with a worse message.
    """
    value = (value or "").strip()
    if not _IDENT.match(value):
        raise SqlError(f"{what} {value!r} is not a plain identifier",
                       "set it in AGENTS.md as `schema.table` or `column`, without quotes or SQL")
    return value


def _literal(value: str, what: str) -> str:
    """A value that goes inside quotes. Refuses anything that would end the quote.

    Not an escaping function on purpose: a project key with an apostrophe in it is a wrong fact,
    not a case to support, and an escaper here would be the one place in this repository that
    builds SQL out of arbitrary text.
    """
    value = (value or "").strip()
    if "'" in value or "\\" in value or ";" in value or "--" in value:
        raise SqlError(f"{what} {value!r} contains characters that cannot appear in a SQL literal",
                       "project keys and dates are plain text; fix the fact rather than escaping it")
    return value


def quoted(dialect: str, name: str) -> str:
    """An identifier alias, quoted the way this engine quotes identifiers.

    Not cosmetic. Double quotes are *string literals* in Hive and Impala, so `AS "key"` there names
    the column after a constant rather than aliasing it -- `ad-sql-check`'s `hive_double_quotes`
    rule caught this in the generator's own output, which is the whole reason the generated SQL is
    linted on the way out rather than trusted.

    The alias matters because `key` is what the live Jira side calls it, and `ad-diff --key key`
    compares the two by name.
    """
    return f"`{name}`" if dialect in ("hive", "impala") else f'"{name}"'


def _timestamp(dialect: str, day_end: str) -> str:
    """Midnight-inclusive end of the window, spelled the way each engine wants it.

    Oracle has no `TIMESTAMP '...'` literal in the ANSI spelling the others share; it wants
    `TO_TIMESTAMP`. Getting this wrong is a runtime error on the warehouse rather than a lint
    finding, which is the worst place to find out.
    """
    stamp = f"{_literal(day_end, 'window end')} 23:59:59"
    if dialect == "oracle":
        return f"TO_TIMESTAMP('{stamp}', 'YYYY-MM-DD HH24:MI:SS')"
    return f"TIMESTAMP '{stamp}'"


def history_sql(*, dialect: str, hist_table: str, project: str, end: str, ticket: str,
                key_column: str = "ISSUE_KEY", ts_column: str = "CHANGED_TS",
                project_column: str = "PROJECT_KEY",
                columns: tuple[str, ...] | list[str] = DEFAULT_COLUMNS) -> str:
    """One row per issue key: its latest state at or before the window end.

    The grain the live side has, so `ad-diff --key key` compares like with like.
    """
    if dialect not in DIALECTS:
        raise SqlError(f"unknown dialect {dialect!r}", "one of " + " | ".join(DIALECTS))

    table = _ident(hist_table, "the Jira history table")
    key_col = _ident(key_column, "the key column")
    ts_col = _ident(ts_column, "the timestamp column")
    proj_col = _ident(project_column, "the project column")
    wanted = [_ident(c, "a column") for c in columns]
    if not wanted:
        raise SqlError("no columns to compare", "pass --fields status,assignee")

    project = _literal(project, "the Jira project key")
    cutoff = _timestamp(dialect, end)
    header = (f"-- {ticket}: Jira history as of {end}, one row per issue key.\n"
              f"-- Generated for {dialect} by `ad-uat jira-vs-source`. Column names come from\n"
              f"-- AGENTS.md (jira_hist_table and the *_column facts); correct them there, not here.\n")

    # Teradata and Oracle have QUALIFY. Impala has none. Hive has it only from 4.0 -- and it gets
    # the windowed form regardless, because the subquery is correct on *every* Hive and choosing by
    # version would mean probing a cluster to decide the text of a file. A generated query that is
    # right everywhere beats one that is prettier on new clusters and refused on old ones.
    alias = quoted(dialect, "key")
    if dialect in ("impala", "hive"):
        return header + _windowed(table, key_col, ts_col, proj_col, project, cutoff, wanted, alias)
    return header + _qualified(table, key_col, ts_col, proj_col, project, cutoff, wanted, alias)


def _qualified(table, key_col, ts_col, proj_col, project, cutoff, wanted, alias) -> str:
    selected = ",\n".join(f"       h.{c} AS {c}" for c in wanted)
    return (f"SELECT h.{key_col} AS {alias},\n"
            f"{selected}\n"
            f"FROM   {table} h\n"
            f"WHERE  h.{proj_col} = '{project}'\n"
            f"  AND  h.{ts_col} <= {cutoff}\n"
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY h.{key_col} "
            f"ORDER BY h.{ts_col} DESC) = 1\n")


def _windowed(table, key_col, ts_col, proj_col, project, cutoff, wanted, alias) -> str:
    """The same grain without `QUALIFY`, for Impala and for Hive before 4.0.

    Not a stylistic preference: `ad-sql-check` refuses `QUALIFY` on Impala outright and on Hive
    below 4, so the generator has to know the shape rather than emit one and hope.
    """
    inner = ",\n".join(f"              h.{c}" for c in wanted)
    outer = ",\n".join(f"       x.{c} AS {c}" for c in wanted)
    return (f"SELECT x.{key_col} AS {alias},\n"
            f"{outer}\n"
            f"FROM   (SELECT h.{key_col},\n"
            f"{inner},\n"
            f"              ROW_NUMBER() OVER (PARTITION BY h.{key_col} "
            f"ORDER BY h.{ts_col} DESC) AS rn\n"
            f"        FROM   {table} h\n"
            f"        WHERE  h.{proj_col} = '{project}'\n"
            f"          AND  h.{ts_col} <= {cutoff}) x\n"
            f"WHERE  x.rn = 1\n")


def coverage_sql(*, dialect: str, hist_table: str, project: str, end: str, ticket: str,
                 key_column: str = "ISSUE_KEY", ts_column: str = "CHANGED_TS",
                 project_column: str = "PROJECT_KEY") -> str:
    """How much history each key actually has -- what tells "the warehouse is stale" from "the
    warehouse never had it", which is a different finding and a different fix."""
    if dialect not in DIALECTS:
        raise SqlError(f"unknown dialect {dialect!r}", "one of " + " | ".join(DIALECTS))
    table = _ident(hist_table, "the Jira history table")
    key_col = _ident(key_column, "the key column")
    ts_col = _ident(ts_column, "the timestamp column")
    proj_col = _ident(project_column, "the project column")
    project = _literal(project, "the Jira project key")
    cutoff = _timestamp(dialect, end)
    return (f"-- {ticket}: history coverage per key, for `ad-uat reconcile --hist-coverage`.\n"
            f"SELECT h.{key_col} AS {quoted(dialect, 'key')},\n"
            f"       MIN(h.{ts_col}) AS first_ts,\n"
            f"       MAX(h.{ts_col}) AS last_ts,\n"
            f"       COUNT(*)        AS n_rows\n"
            f"FROM   {table} h\n"
            f"WHERE  h.{proj_col} = '{project}'\n"
            f"  AND  h.{ts_col} <= {cutoff}\n"
            f"GROUP BY h.{key_col}\n")
