"""Writing a repository's AGENTS.md facts, in place, and its Power BI targets table.

`config.project_facts` reads `- key: value   # comment` lines; this is the other half. A value is changed on its own
line with the comment kept, a new key goes at the end of `## Project facts`, a cleared key goes back to its
`<placeholder>` (so a skill still sees it as unset, and the line still says what it is for), and nothing else in the
file moves. Setup writes here for what belongs to ONE repository -- which environment of each source it reads, which
Power BI workspaces, semantic models and reports it changes -- and to the machine's config for the rest.

A repository may change several semantic models and reports, across workspaces. They are one row each in
`## Power BI targets`, a Markdown table a person can read and edit. The first row is also written to the single facts
(`pbi_workspace`, `ws_id`, `pbi_model`, `ds_id`, `pbi_xmla`) that every reader before this one uses, so nothing that
reads those changes.
"""
from __future__ import annotations

import os
import re
import urllib.parse

from . import textio

FACTS_HEADING = "## Project facts"
TARGETS_HEADING = "## Power BI targets"
TARGET_COLUMNS = ("workspace", "ws_id", "model", "ds_id", "report", "report_id")
# The single facts the first target mirrors, for every reader that predates the table.
PRIMARY = {"workspace": "pbi_workspace", "ws_id": "ws_id", "model": "pbi_model", "ds_id": "ds_id"}
_FACT_LINE = re.compile(r"^(\s*-\s*)([A-Za-z_][\w\-]*)(\s*:\s*)(.*?)(\s+#.*)?$")
_HEADING = re.compile(r"^#{1,6}\s")


def xmla_url(workspace: str) -> str:
    return "powerbi://api.powerbi.com/v1.0/myorg/" + urllib.parse.quote(workspace, safe="")


def _lines(path: str) -> list[str]:
    return textio.read_text(path).splitlines() if os.path.exists(path) else []


def _write(path: str, lines: list[str]) -> None:
    text = "\n".join(lines).rstrip("\n") + "\n"
    if os.path.exists(path) and textio.read_text(path).replace("\r\n", "\n") == text:
        return                                        # unchanged: leave the file (and its mtime) alone
    textio.write_text(path, text)


def _section(lines: list[str], heading: str) -> tuple[int, int]:
    """(first line, line after the last) of `heading`'s section, or (-1, -1)."""
    for i, line in enumerate(lines):
        if line.strip() == heading:
            j = i + 1
            while j < len(lines) and not _HEADING.match(lines[j]):
                j += 1
            return i, j
    return -1, -1


def set_facts(path: str, values: dict[str, str | None]) -> dict[str, str]:
    """Write `values` into AGENTS.md's facts; None clears a key back to `<unset>`. Returns {key: "changed" |
    "added" | "cleared" | "same"}. The file must exist: creating one is the project stub's job."""
    lines = _lines(path)
    done: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = _FACT_LINE.match(line)
        if not m or m.group(2).lower() not in values:
            continue
        key = m.group(2).lower()
        value = values[key]
        old = m.group(4).strip()
        new = "<unset>" if value in (None, "") else str(value)
        if old == new or (value in (None, "") and old.startswith("<")):
            done[key] = "same"
            continue
        lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{new}{m.group(5) or ''}"
        done[key] = "cleared" if value in (None, "") else "changed"
    missing = [k for k, v in values.items() if k not in done and v not in (None, "")]
    if missing:
        start, end = _section(lines, FACTS_HEADING)
        if start < 0:
            lines += ["", FACTS_HEADING]
            start, end = len(lines) - 1, len(lines)
        at = end
        while at > start + 1 and not lines[at - 1].strip():
            at -= 1                                   # after the last fact, before the blank line
        lines[at:at] = [f"- {k}: {values[k]}" for k in missing]
        done.update({k: "added" for k in missing})
    _write(path, lines)
    return done


def pbi_targets(path: str = "AGENTS.md", facts: dict | None = None) -> list[dict[str, str]]:
    """The repository's Power BI targets: the `## Power BI targets` rows, or -- with no table -- the one target the
    single facts describe, or []."""
    lines = _lines(path)
    start, end = _section(lines, TARGETS_HEADING)
    rows: list[dict[str, str]] = []
    if start >= 0:
        header: list[str] = []
        for line in lines[start + 1:end]:
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if not cells or set("".join(cells)) <= set("-: "):
                continue
            if not header:
                header = [c.lower() for c in cells]
                continue
            row = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
            row = {k: ("" if v in ("-", "") else v) for k, v in row.items()}
            if any(row.get(c) for c in ("workspace", "model", "report")):
                rows.append({c: row.get(c, "") for c in TARGET_COLUMNS})
        return rows
    if facts is None:
        from .config import project_facts
        facts = project_facts(path)
    single = {c: str(facts.get(f) or "") for c, f in PRIMARY.items()}
    if single["workspace"] or single["model"]:
        return [{**{c: "" for c in TARGET_COLUMNS}, **single}]
    return []


def render_targets(targets: list[dict[str, str]]) -> list[str]:
    head = "| " + " | ".join(TARGET_COLUMNS) + " |"
    rule = "|" + "|".join("---" for _ in TARGET_COLUMNS) + "|"
    body = ["| " + " | ".join(t.get(c) or "-" for c in TARGET_COLUMNS) + " |" for t in targets]
    return [TARGETS_HEADING,
            "One row per semantic model or report this repository changes. `ad-setup` in this repository (or `tnp` ->",
            "Power BI) writes it; the first row is also the single `pbi_*` facts above.",
            "",
            head, rule, *body]


def set_targets(path: str, targets: list[dict[str, str]]) -> None:
    """Replace the `## Power BI targets` section with `targets` (or remove it for none), and mirror the first row
    into the single facts."""
    lines = _lines(path)
    start, end = _section(lines, TARGETS_HEADING)
    block = render_targets(targets) if targets else []
    if start >= 0:
        lines[start:end] = block + ([""] if block and end < len(lines) else [])
    elif block:
        fstart, fend = _section(lines, FACTS_HEADING)
        at = fend if fstart >= 0 else len(lines)
        lines[at:at] = (["", *block, ""] if at < len(lines) else ["", *block])
    _write(path, lines)
    first = targets[0] if targets else {}
    values: dict[str, str | None] = {f: (first.get(c) or None) for c, f in PRIMARY.items()}
    values["pbi_xmla"] = xmla_url(first["workspace"]) if first.get("workspace") else None
    set_facts(path, values)
