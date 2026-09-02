"""Rule table for ad-sql-check. Each rule: regex on the stripped SQL (or raw when raw=True), severity E (blocks)
or W (meta.warnings), a one-line fix, and a doc anchor into the dialect reference shipped with the query skill.
Capability gates (`gate`) read the probes ad-setup recorded for the env; unknown capability -> warning."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any
from . import strip as S
from .. import toon

DIALECTS = ("teradata", "hive", "impala", "oracle")
DOC = {"teradata": "teradata-sql.md", "hive": "hive-impala-sql.md", "impala": "hive-impala-sql.md", "oracle": "oracle-sql.md"}
_F = re.I | re.M


@dataclass(frozen=True)
class Rule:
    id: str
    dialects: tuple[str, ...]
    severity: str          # "E" | "W"
    pattern: str
    message: str
    fix: str
    doc: str               # heading anchor in the dialect reference, e.g. "row-limiting"
    also: str | None = None    # second pattern that must ALSO match (anywhere)
    unless: str | None = None  # pattern whose presence suppresses the rule
    raw: bool = False          # match against the raw SQL (needed for /*+ hints */)
    gate: str | None = None    # "cap:<name>=false" | "cap:major<4" | "cap:tmode=TERA"
    severity_by: dict = field(default_factory=dict)  # dialect -> severity override


@dataclass
class Finding:
    severity: str  # error | warning
    line: int
    rule: str
    message: str
    fix: str
    doc: str

    def row(self) -> list:
        return [self.severity, self.line, self.rule, self.message, self.fix, self.doc]


HIVEIMP = ("hive", "impala")
RULES: list[Rule] = [
    # ---- common ----
    Rule("group_by_ordinal", DIALECTS, "W", r"\bGROUP\s+BY\s+\d+\b", "GROUP BY ordinal position",
         "repeat the full expression in GROUP BY (Oracle groups by the literal: ORA-00979)", "aggregation",
         severity_by={"oracle": "E"}),
    Rule("current_date_parens", ("teradata", "oracle"), "E", r"\bCURRENT_DATE\s*\(\s*\)",
         "CURRENT_DATE takes no parentheses here", "CURRENT_DATE (Oracle: SYSDATE / TRUNC(SYSDATE))", "dates"),
    # ---- teradata ----
    Rule("td_limit", ("teradata",), "E", r"\bLIMIT\s+\d+", "Teradata has no LIMIT (error 3706)",
         "SELECT TOP n ... | SAMPLE n | QUALIFY ROW_NUMBER() OVER (ORDER BY ...) <= n", "row-limiting"),
    Rule("td_fetch_first", ("teradata",), "E", r"\bFETCH\s+(FIRST|NEXT)\b", "FETCH FIRST is Oracle/ANSI, not Teradata",
         "SELECT TOP n ...", "row-limiting"),
    Rule("td_backtick", ("teradata",), "E", r"`", "backtick identifiers are Hive/Impala syntax",
         'quote identifiers with double quotes: "My Col"', "identifiers"),
    Rule("td_string_type", ("teradata",), "E", r"\bAS\s+STRING\b", "STRING is not a Teradata type",
         "CAST(x AS VARCHAR(n))", "types-and-division"),
    Rule("td_modulo", ("teradata",), "E", r"(?<![%'])%(?![%'])", "% is not an operator in Teradata",
         "MOD(a, b)", "types-and-division"),
    Rule("td_top_qualify", ("teradata",), "E", r"\bSELECT\s+(DISTINCT\s+)?TOP\s+\d+", "TOP cannot be combined with QUALIFY",
         "drop TOP and filter with QUALIFY ROW_NUMBER() OVER (...) <= n", "row-limiting", also=r"\bQUALIFY\b"),
    Rule("td_hint", ("teradata",), "E", r"/\*\+", "Teradata ignores /*+ optimizer hints */ and may reject them",
         "remove the hint", "gotchas", raw=True),
    Rule("td_dual", ("teradata",), "W", r"\bFROM\s+DUAL\b", "no DUAL table in Teradata",
         "drop FROM DUAL (SELECT 1 works alone)", "scalar-select"),
    Rule("td_hive_date_funcs", ("teradata",), "E", r"\b(date_add|datediff|date_format|from_unixtime|unix_timestamp|date_sub)\s*\(",
         "Hive/Impala date function in Teradata SQL", "d + n days | d1 - d2 (INTEGER days) | CAST(CAST(d AS FORMAT 'YYYY-MM-DD') AS VARCHAR(10))", "dates"),
    Rule("td_int_division", ("teradata",), "W", r"\bSUM\s*\([^()]*\)\s*/\s*COUNT\s*\(", "integer / integer truncates in Teradata",
         "CAST(SUM(x) AS DECIMAL(18,4)) / COUNT(*)", "types-and-division"),
    Rule("td_trunc_date", ("teradata",), "E", r"\bTRUNC\s*\(\s*[^,()]+,\s*'[A-Za-z]+'\s*\)", "TRUNC(date, unit) not available on this Teradata",
         "CAST(CAST(d AS FORMAT 'YYYY-MM') AS VARCHAR(7)) or EXTRACT(YEAR FROM d)/EXTRACT(MONTH FROM d)", "dates", gate="cap:trunc_date=false"),
    Rule("td_to_char", ("teradata",), "E", r"\bTO_CHAR\s*\(", "TO_CHAR not available on this Teradata",
         "CAST(CAST(d AS FORMAT 'YYYY-MM-DD') AS VARCHAR(10))", "dates", gate="cap:to_char=false"),
    Rule("td_listagg", ("teradata",), "E", r"\bLISTAGG\s*\(", "LISTAGG is not available on this Teradata",
         "TRIM(TRAILING ',' FROM (XMLAGG(TRIM(col) || ',' ORDER BY col) (VARCHAR(4000))))", "aggregation", gate="cap:listagg=false"),
    Rule("td_case_insensitive_eq", ("teradata",), "W", r"=\s*'[^']", "session runs in Teradata mode: string = is case-insensitive",
         "compare (col (CASESPECIFIC)) = 'x' or UPPER() both sides when case matters", "strings", gate="cap:tmode=TERA"),
    # ---- oracle ----
    Rule("ora_limit", ("oracle",), "E", r"\bLIMIT\s+\d+", "Oracle has no LIMIT (ORA-00933)",
         "ORDER BY ... FETCH FIRST n ROWS ONLY", "row-limiting"),
    Rule("ora_top", ("oracle",), "E", r"\bSELECT\s+(DISTINCT\s+)?TOP\s+\d+", "TOP is Teradata/SQL Server syntax",
         "FETCH FIRST n ROWS ONLY", "row-limiting"),
    Rule("ora_table_alias_as", ("oracle",), "E", r"\b(FROM|JOIN)\s+[\w.$\"]+\s+AS\s+\w+", "AS is not allowed on table aliases (ORA-00933)",
         "FROM table t (drop AS; column aliases may keep AS)", "identifiers"),
    Rule("ora_fromless_select", ("oracle",), "E", r"^\s*SELECT\b", "scalar SELECT needs FROM DUAL in Oracle 19c/21c",
         "SELECT ... FROM DUAL", "scalar-select", unless=r"\bFROM\b"),
    Rule("ora_rownum_orderby", ("oracle",), "W", r"\bROWNUM\b", "ROWNUM is assigned before ORDER BY runs: wrong rows, no error",
         "ORDER BY inside a subquery then ROWNUM outside, or FETCH FIRST n ROWS ONLY", "row-limiting", also=r"\bORDER\s+BY\b"),
    Rule("ora_empty_string_eq", ("oracle",), "W", r"(=|<>|!=)\s*''", "'' is NULL in Oracle: this predicate never matches",
         "col IS NULL / IS NOT NULL", "nulls"),
    Rule("ora_string_type", ("oracle",), "W", r"\bAS\s+(STRING|VARCHAR)\b", "use VARCHAR2 in Oracle",
         "CAST(x AS VARCHAR2(n))", "types-and-division"),
    Rule("ora_backtick", ("oracle",), "E", r"`", "backtick identifiers are Hive/Impala syntax",
         'unquoted identifiers (Oracle upper-cases them); "quoted" only when case matters', "identifiers"),
    Rule("ora_null_funcs", ("oracle",), "E", r"\b(IFNULL|ISNULL|ZEROIFNULL|NULLIFZERO)\s*\(", "not an Oracle function",
         "NVL(a, b) / COALESCE / NULLIF", "nulls"),
    Rule("ora_date_string_compare", ("oracle",), "W", r"\b\w*(DATE|_DT|_TS|TIME)\w*\s*(=|>=|<=|<|>|BETWEEN)\s*'§'",
         "string literal compared to a date column: implicit conversion (ORA-01861)", "TO_DATE('2025-01-31','YYYY-MM-DD') or DATE '2025-01-31'", "dates"),
    Rule("ora_hive_date_funcs", ("oracle",), "E", r"\b(date_add|datediff|date_format|from_unixtime|unix_timestamp)\s*\(",
         "Hive/Impala date function in Oracle SQL", "d + n | d1 - d2 (fractional days) | TO_CHAR(d,'YYYY-MM-DD') | TO_DATE()", "dates"),
    # ---- hive + impala ----
    Rule("hive_top", HIVEIMP, "E", r"\bSELECT\s+(DISTINCT\s+)?TOP\s+\d+", "TOP is not Hive/Impala syntax", "... LIMIT n", "row-limiting"),
    Rule("hive_fetch_first", HIVEIMP, "E", r"\bFETCH\s+(FIRST|NEXT)\b", "FETCH FIRST is not Hive/Impala syntax", "... LIMIT n", "row-limiting"),
    Rule("hive_sample", HIVEIMP, "E", r"\bSAMPLE\s+\d+", "SAMPLE is Teradata syntax", "LIMIT n (Hive: TABLESAMPLE)", "row-limiting"),
    Rule("hive_qualify", ("hive",), "E", r"\bQUALIFY\b", "QUALIFY needs Hive 4+",
         "SELECT * FROM (SELECT ..., ROW_NUMBER() OVER (...) rn FROM t) x WHERE rn = 1", "qualify", gate="cap:major<4"),
    Rule("imp_qualify", ("impala",), "E", r"\bQUALIFY\b", "Impala has no QUALIFY",
         "SELECT * FROM (SELECT ..., row_number() OVER (...) rn FROM t) x WHERE rn = 1", "qualify"),
    Rule("hive_limit_nonliteral", HIVEIMP, "E", r"\bLIMIT\s+(?![\d\s(]|ALL\b)", "LIMIT takes a literal number",
         "LIMIT 100", "row-limiting"),
    Rule("hive_double_quotes", HIVEIMP, "W", r'"', 'double quotes are string literals in Hive/Impala',
         "identifiers use backticks: `My Col`", "identifiers"),
    Rule("hive_dual", HIVEIMP, "W", r"\bFROM\s+DUAL\b", "no DUAL table", "drop FROM DUAL", "scalar-select"),
    Rule("hive_sysdate", HIVEIMP, "E", r"\bSYSDATE\b", "SYSDATE is Oracle", "current_timestamp() (Impala: now())", "dates"),
    Rule("hive_to_char", HIVEIMP, "E", r"\bTO_CHAR\s*\(", "TO_CHAR is Oracle/Teradata",
         "Hive: date_format(d,'yyyy-MM-dd') | Impala: from_timestamp(ts,'yyyy-MM-dd')", "dates"),
    Rule("hive_to_date_fmt", HIVEIMP, "E", r"\bTO_DATE\s*\([^,()]+,", "to_date() takes one argument in Hive/Impala",
         "Hive: from_unixtime(unix_timestamp(s,'yyyy-MM-dd')) | Impala: to_timestamp(s,'yyyy-MM-dd')", "dates"),
    Rule("hive_trunc_unit", ("hive",), "E", r"\bTRUNC\s*\([^,()]+,\s*'(?!(MM|MON|MONTH|Q|QUARTER|YEAR|YYYY|YY)')[A-Za-z]+'",
         "Hive trunc() supports only MONTH/QUARTER/YEAR units", "date_format(d,'yyyy-MM-dd') or to_date()", "dates"),
    Rule("hive_nvl_nary", ("hive",), "W", r"\bNVL\s*\([^()]*,[^()]*,", "n-ary NVL runs on Hive only (it is coalesce)",
         "COALESCE(a, b, c)", "nulls"),
    Rule("imp_nvl_nary", ("impala",), "E", r"\bNVL\s*\([^()]*,[^()]*,", "Impala NVL takes exactly two arguments",
         "COALESCE(a, b, c)", "nulls"),
    Rule("hive_listagg", HIVEIMP, "E", r"\bLISTAGG\s*\(", "LISTAGG is Oracle",
         "Hive: concat_ws(',', collect_list(x)) | Impala: group_concat(x, ',')", "aggregation"),
    Rule("hive_rownum", HIVEIMP, "E", r"\bROWNUM\b", "ROWNUM is Oracle", "row_number() OVER (...)", "row-limiting"),
    # ---- impala only ----
    Rule("imp_concat_pipes", ("impala",), "E", r"\|\|", "|| is LOGICAL OR in Impala, not concatenation",
         "concat(a, b) / concat_ws(sep, a, b)", "strings"),
    Rule("imp_lateral_view", ("impala",), "E", r"\bLATERAL\s+VIEW\b", "LATERAL VIEW is Hive-only",
         "join the complex-type column directly (FROM t, t.arr) or pre-flatten in Hive", "joins"),
    Rule("imp_collect", ("impala",), "E", r"\bcollect_(list|set)\s*\(", "collect_list/collect_set are Hive-only",
         "group_concat(x, ',')", "aggregation"),
    Rule("imp_date_format", ("impala",), "E", r"\bdate_format\s*\(", "date_format() is Hive-only",
         "from_timestamp(ts, 'yyyy-MM-dd')", "dates"),
    Rule("imp_date_trunc_order", ("impala",), "E", r"\bDATE_TRUNC\s*\(\s*[^'\s,()][^,()]*,\s*'", "DATE_TRUNC takes the unit FIRST",
         "DATE_TRUNC('MONTH', ts)", "dates"),
    Rule("imp_trunc_order", ("impala",), "E", r"\bTRUNC\s*\(\s*'[A-Za-z]+'\s*,", "TRUNC takes the timestamp FIRST",
         "TRUNC(ts, 'MM')", "dates"),
    Rule("imp_concat_null", ("impala",), "W", r"\bCONCAT\s*\(", "CONCAT returns NULL when any argument is NULL",
         "concat_ws(sep, ...) or nvl(x, '')", "strings"),
]


def _gate(rule: Rule, caps: dict) -> str | None:
    """Return effective severity or None to skip, given the env's recorded capabilities."""
    if not rule.gate:
        return rule.severity
    kind, expr = rule.gate.split(":", 1)
    if kind != "cap":
        return rule.severity
    if "=" in expr:
        name, want = expr.split("=", 1)
        val = caps.get(name)
        if val is None:
            return "W"  # unknown -> warn, never block
        if want.lower() == "false":
            return rule.severity if val is False else None
        return rule.severity if str(val).upper() == want.upper() else None
    if "<" in expr:
        name, lim = expr.split("<", 1)
        val = caps.get(name)
        if val is None:
            return "W"
        return rule.severity if int(val) < int(lim) else None
    return rule.severity


def check(sql: str, dialect: str, caps: dict | None = None) -> list[Finding]:
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect}; one of {', '.join(DIALECTS)}")
    caps = caps or {}
    stripped = S.strip(sql)
    findings: list[Finding] = []
    for rule in RULES:
        if dialect not in rule.dialects:
            continue
        sev = _gate(rule, caps)
        if sev is None:
            continue
        sev = rule.severity_by.get(dialect, sev)
        text = sql if rule.raw else stripped
        if rule.also and not re.search(rule.also, text, _F):
            continue
        if rule.unless and re.search(rule.unless, text, _F):
            continue
        m = re.search(rule.pattern, text, _F)
        if not m:
            continue
        msg = rule.message + (" (capability unknown: run ad-doctor --online)" if rule.gate and sev == "W" and rule.severity == "E" else "")
        findings.append(Finding("error" if sev == "E" else "warning", S.line_of(text, m.start()), rule.id, msg, rule.fix,
                                f"{DOC[dialect]}#{rule.doc}"))
    findings.sort(key=lambda f: (0 if f.severity == "error" else 1, f.line))
    return findings


def to_toon(findings: list[Finding], dialect: str, extra: dict | None = None) -> str:
    errors = sum(1 for f in findings if f.severity == "error")
    meta: dict[str, Any] = {"ok": errors == 0, "source": "ad-sql-check", "dialect": dialect, "errors": errors,
                            "warnings": len(findings) - errors}
    if errors:
        meta["hint"] = findings[0].fix
    if extra:
        meta.update(extra)
    body = toon.table("findings", ["severity", "line", "rule", "message", "fix", "doc"], [f.row() for f in findings])
    return "\n".join([toon.encode(meta, key="meta"), body])


def anchors_for(dialect: str) -> set[str]:
    return {r.doc for r in RULES if dialect in r.dialects}
