"""Tolerant, line-preserving TMDL reader/writer.

TMDL facts encoded here (verified on Microsoft's sample PBIP and TMDL guidelines):
- one indentation unit per nesting level; Desktop writes one TAB (spaces are legal but must be consistent)
- `<type> <Name>` headers, `<type> <Name> = <expr>` for default properties (measure, partition, expression, calc column)
- `key: value` properties; boolean properties are bare keywords when true
- multi-line expressions: ``` fenced block after `=`, or a bare block indented deeper than the object's properties
  (Desktop: declaration depth + 2); `source =` / `extendedProperty X =` behave the same way
- `///` description lines above an object; `//` comments are not TMDL
- names with space . = : ' are single-quoted, in declarations and references
The writer never re-serializes untouched lines: it splices new/replacement blocks and keeps BOM + newline style.
"""
from __future__ import annotations
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Iterable

OBJECT_KEYWORDS = {
    "database", "model", "table", "column", "measure", "partition", "hierarchy", "level", "relationship", "role",
    "tablePermission", "perspective", "perspectiveTable", "perspectiveColumn", "perspectiveMeasure", "perspectiveHierarchy",
    "cultureInfo", "culture", "expression", "function", "annotation", "extendedProperty", "changedProperty",
    "dataAccessOptions", "calculationGroup", "calculationItem", "variation", "refreshPolicy", "linguisticMetadata",
    "queryGroup", "namedExpression", "translation", "roleMembership", "modelPermission",
}
EXPR_HEADERS = {"measure", "partition", "expression", "function", "column", "calculationItem", "tablePermission", "annotation", "extendedProperty", "changedProperty"}
REF_PROPS = {"sortByColumn", "fromColumn", "toColumn", "column", "defaultHierarchy", "defaultMember"}
NEEDS_QUOTE = re.compile(r"[\s.=:']")
_KW = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def split_header(content: str) -> tuple[str, str | None, bool, str | None] | None:
    """`kw [name] [= rest]` with the `=` found outside single quotes. None when the line is not a header."""
    in_q, idx = False, -1
    for i, ch in enumerate(content):
        if ch == "'":
            in_q = not in_q
        elif ch == "=" and not in_q:
            idx = i
            break
    left = content if idx < 0 else content[:idx]
    rest = None if idx < 0 else content[idx + 1:].strip()
    parts = left.strip().split(None, 1)
    if not parts or not _KW.match(parts[0]):
        return None
    name_tok = parts[1].strip() if len(parts) > 1 else None
    return parts[0], name_tok, idx >= 0, rest
_PROP = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9]*)\s*:\s*(?P<val>.*)$")
_FENCE = "```"


@dataclass
class Finding:
    severity: str  # error | warning
    file: str
    line: int
    rule: str
    message: str
    fix: str = ""

    def row(self) -> list:
        return [self.severity, self.file, self.line, self.rule, self.message, self.fix]


@dataclass
class Node:
    kind: str
    name: str | None
    line_start: int            # 1-based, header line (description lines are recorded separately)
    line_end: int              # exclusive: first line after the object (incl. trailing blank lines? no: last content line + 1)
    expr: str | None = None
    fenced: bool = False
    props: dict = field(default_factory=dict)      # key -> value (True for bare booleans)
    children: list["Node"] = field(default_factory=list)
    desc: list[str] = field(default_factory=list)  # /// lines (text without the marker)
    desc_start: int | None = None

    def child(self, kind: str, name: str | None = None) -> "Node | None":
        for c in self.children:
            if c.kind == kind and (name is None or c.name == name):
                return c
        return None

    def all(self, kind: str) -> list["Node"]:
        return [c for c in self.children if c.kind == kind]


@dataclass
class TmdlFile:
    path: str
    lines: list[str]
    newline: str = "\n"
    bom: bool = False
    indent_char: str = "\t"
    indent_size: int = 1
    trailing_newline: bool = True
    nodes: list[Node] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.newline.join(self.lines) + (self.newline if self.lines and self.trailing_newline else "")

    def indent(self, level: int) -> str:
        return self.indent_char * (self.indent_size * level)

    def find(self, kind: str, name: str | None = None) -> Node | None:
        for n in self.nodes:
            if n.kind == kind and (name is None or n.name == name):
                return n
        return None


# ---------- names ----------
def unquote(name: str | None) -> str | None:
    if name is None:
        return None
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "'\"":
        return name[1:-1].replace("''", "'") if name[0] == "'" else name[1:-1]
    return name


def quote_name(name: str) -> str:
    return "'" + name.replace("'", "''") + "'" if (not name or NEEDS_QUOTE.search(name)) else name


_DAX_LABEL = re.compile(r"^('(?:[^']|'')+'|[^\[\]'.]+)\[([^\]]+)\]$")


def split_ref(ref: str) -> tuple[str | None, str]:
    """TMDL `Sales.'Order Date'` / `'My Table'.Col` / `Col`, or DAX `'Sales'[Quantity]` / `Sales[Quantity]` -> (table|None, column)."""
    ref = ref.strip()
    m = _DAX_LABEL.match(ref)
    if m:
        return unquote(m.group(1)), m.group(2)
    if ref.startswith("'"):
        m = re.match(r"^'((?:[^']|'')*)'(?:\.(.*))?$", ref)
        if m:
            return (unquote("'" + m.group(1) + "'"), unquote(m.group(2)) or "") if m.group(2) is not None else (None, unquote(ref))
    if "." in ref:
        t, c = ref.split(".", 1)
        return unquote(t), unquote(c) or ""
    return None, unquote(ref) or ""


# ---------- reading ----------
def read_file(path: str) -> TmdlFile:
    with open(path, "rb") as f:
        data = f.read()
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data[3:].decode("utf-8") if bom else data.decode("utf-8")
    return parse_text(text, path, bom=bom)


def parse_text(text: str, path: str = "<text>", bom: bool = False) -> TmdlFile:
    newline = "\r\n" if "\r\n" in text else "\n"
    raw_lines = text.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in raw_lines]
    if lines and lines[-1] == "":
        lines = lines[:-1]  # trailing newline -> implicit
        had_trailing_nl = True
    else:
        had_trailing_nl = not text or text.endswith("\n")
    tf = TmdlFile(path=path, lines=lines, newline=newline, bom=bom, trailing_newline=bool(had_trailing_nl))
    tf.findings = []
    tabs = any(ln.startswith("\t") for ln in lines)
    spaces = any(re.match(r"^ +\S", ln) for ln in lines)
    if tabs and spaces:
        tf.findings.append(Finding("error", path, next(i + 1 for i, ln in enumerate(lines) if re.match(r"^ +\S", ln)),
                                   "mixed_indent", "file mixes tabs and spaces for indentation", "use tabs (Power BI Desktop style) everywhere"))
    if spaces and not tabs:
        tf.indent_char = " "
        sizes = [len(ln) - len(ln.lstrip(" ")) for ln in lines if re.match(r"^ +\S", ln)]
        tf.indent_size = min(sizes) if sizes else 4
    if bom:
        tf.findings.append(Finding("warning", path, 1, "bom", "file starts with a UTF-8 BOM (Desktop writes none)", "save as UTF-8 without BOM"))
    if "\r\n" in text and re.search(r"(?<!\r)\n", text):
        tf.findings.append(Finding("warning", path, 1, "mixed_newlines", "file mixes CRLF and LF", "normalize to one newline style"))
    if not had_trailing_nl and lines:
        tf.findings.append(Finding("warning", path, len(lines), "missing_trailing_newline", "no newline at end of file", "add a final newline"))
    for i, ln in enumerate(lines):
        if ln.strip().startswith("//") and not ln.strip().startswith("///"):
            tf.findings.append(Finding("error", path, i + 1, "double_slash_comment", "`//` comments are not TMDL (only inside DAX/M blocks)", "use `///` description lines above the object, or delete"))
    parser = _Parser(tf)
    tf.nodes = parser.parse()
    if os.path.basename(path).lower() == "database.tmdl":
        first = next((ln for ln in lines if ln.strip()), "")
        if not first.startswith("database"):
            tf.findings.append(Finding("error", path, 1, "database_decl", "database.tmdl must start with a `database <name>` declaration", "add `database <Name>` as the first line"))
    return tf


class _Parser:
    def __init__(self, tf: TmdlFile):
        self.tf = tf
        self.lines = tf.lines
        self.n = len(self.lines)

    def level(self, ln: str) -> int:
        stripped = ln.lstrip("\t ")
        ws = ln[: len(ln) - len(stripped)]
        if self.tf.indent_char == "\t":
            return len(ws.replace(" ", ""))  # stray spaces already flagged
        return len(ws) // max(1, self.tf.indent_size)

    def parse(self) -> list[Node]:
        nodes, i = [], 0
        pending_desc: list[str] = []
        desc_start = None
        while i < self.n:
            ln = self.lines[i]
            if not ln.strip():
                i += 1
                continue
            if ln.strip().startswith("///"):
                if not pending_desc:
                    desc_start = i + 1
                pending_desc.append(ln.strip()[3:].strip())
                i += 1
                continue
            if ln.strip().startswith("//"):
                i += 1  # already reported as double_slash_comment
                continue
            node, i = self.parse_object(i, 0)
            if node is None:
                i += 1
                continue
            if pending_desc:
                node.desc, node.desc_start = pending_desc, desc_start
                pending_desc, desc_start = [], None
            nodes.append(node)
        return nodes

    def parse_object(self, i: int, lvl: int) -> tuple[Node | None, int]:
        ln = self.lines[i]
        content = ln.strip()
        h = split_header(content)
        if not h:
            self.tf.findings.append(Finding("error", self.tf.path, i + 1, "unparsable_line", f"cannot parse: {content[:60]}", "check indentation and quoting"))
            return None, i + 1
        kw, name_tok, has_eq, rest = h
        if kw == "ref":
            parts = content.split(None, 2)
            node = Node("ref", unquote(parts[2]) if len(parts) > 2 else None, i + 1, i + 2, props={"refType": parts[1] if len(parts) > 1 else ""})
            return node, i + 1
        name = unquote(name_tok) if name_tok is not None else None
        if name_tok and not name_tok.startswith(("'", '"')) and NEEDS_QUOTE.search(name_tok.strip()) and kw in OBJECT_KEYWORDS:
            self.tf.findings.append(Finding("error", self.tf.path, i + 1, "unquoted_name", f"{kw} name {name_tok.strip()!r} must be single-quoted (contains space or . = : ')",
                                            f"{kw} {quote_name(name_tok.strip())}"))
        node = Node(kw, name, i + 1, i + 1)
        j = i + 1
        if has_eq:
            if rest and rest != _FENCE:
                node.expr = rest
            else:
                node.fenced = rest == _FENCE
                node.expr, j = self.read_expr(j, lvl, node.fenced, i + 1)
        # children: properties / nested objects at lvl+1
        while j < self.n:
            cl = self.lines[j]
            if not cl.strip():
                j += 1
                continue
            clvl = self.level(cl)
            if clvl <= lvl:
                break
            c = cl.strip()
            if c.startswith("//") and not c.startswith("///"):
                j += 1
                continue
            if c.startswith("///"):
                # description of a child object: collect then parse the child
                desc, ds = [], j + 1
                while j < self.n and self.lines[j].strip().startswith("///"):
                    desc.append(self.lines[j].strip()[3:].strip())
                    j += 1
                if j < self.n and self.level(self.lines[j]) == lvl + 1:
                    child, j = self.parse_object(j, lvl + 1)
                    if child:
                        child.desc, child.desc_start = desc, ds
                        node.children.append(child)
                continue
            if clvl > lvl + 1:
                self.tf.findings.append(Finding("error", self.tf.path, j + 1, "indent_jump",
                                                f"line is indented {clvl - lvl} levels under `{kw} {name or ''}`; expression continuations belong right after `=`",
                                                "indent properties one level under the object; put multi-line expressions in a ``` block"))
                j += 1
                continue
            pm = _PROP.match(c)
            hm = split_header(c)
            if pm:  # `key: value` is always a property, even when the key doubles as an object keyword (culture:, column:)
                node.props[pm.group("key")] = pm.group("val").strip()
                j += 1
            elif hm and hm[0] in OBJECT_KEYWORDS:
                child, j = self.parse_object(j, lvl + 1)
                if child:
                    node.children.append(child)
            elif re.match(r"^[A-Za-z][A-Za-z0-9]*$", c):
                node.props[c] = True
                j += 1
            elif re.match(r"^[A-Za-z][A-Za-z0-9]*\s*=\s*$", c) or re.match(r"^[A-Za-z][A-Za-z0-9]*\s*=\s*```$", c):
                key = c.split("=")[0].strip()
                fenced = c.rstrip().endswith(_FENCE)
                expr, j = self.read_expr(j + 1, lvl, fenced, j + 1)  # body sits at parent level + 2
                child = Node(key, None, j, j, expr=expr, fenced=fenced)
                node.children.append(child)
                node.props[key] = expr
            elif re.match(r"^[A-Za-z][A-Za-z0-9]*\s*=", c):
                key, val = c.split("=", 1)
                node.props[key.strip()] = val.strip()
                j += 1
            else:
                self.tf.findings.append(Finding("error", self.tf.path, j + 1, "continuation_indent",
                                                f"`{c[:40]}` is not a property; if it continues an expression it must be indented deeper than the properties",
                                                "indent expression lines two levels under the declaration, or wrap the expression in ``` fences"))
                j += 1
        node.line_end = j
        # trim trailing blank lines from the span
        while node.line_end > node.line_start and not self.lines[node.line_end - 1].strip():
            node.line_end -= 1
        return node, j

    def read_expr(self, j: int, lvl: int, fenced: bool, header_line: int) -> tuple[str, int]:
        body: list[str] = []
        if fenced:
            while j < self.n:
                if self.lines[j].strip() == _FENCE:
                    return _dedent(body), j + 1
                body.append(self.lines[j])
                j += 1
            self.tf.findings.append(Finding("error", self.tf.path, header_line, "unterminated_fence", "``` block is never closed", "add a closing ``` line"))
            return _dedent(body), j
        while j < self.n:
            ln = self.lines[j]
            if not ln.strip():
                body.append("")
                j += 1
                continue
            if self.level(ln) >= lvl + 2:
                body.append(ln)
                j += 1
                continue
            break
        while body and body[-1] == "":
            body.pop()
        return _dedent(body), j


def _dedent(body: list[str]) -> str:
    non_blank = [ln for ln in body if ln.strip()]
    if not non_blank:
        return ""
    common = min(len(ln) - len(ln.lstrip("\t ")) for ln in non_blank)
    return "\n".join(ln[common:] if ln.strip() else "" for ln in body)


# ---------- lint (file level) ----------
def lint_file(tf: TmdlFile) -> list[Finding]:
    out = list(tf.findings)
    for node in _walk(tf.nodes):
        for key in REF_PROPS & set(node.props):
            val = node.props[key]
            if isinstance(val, str) and _unquoted_special(val):
                out.append(Finding("error", tf.path, node.line_start, "unquoted_ref",
                                   f"{key}: {val} references a name with spaces/specials without quotes", f"{key}: {_quote_ref(val)}"))
    return out


def _unquoted_special(ref: str) -> bool:
    parts = re.split(r"\.(?=(?:[^']*'[^']*')*[^']*$)", ref)  # split on dots outside quotes
    for p in parts:
        p = p.strip()
        if p.startswith("'") and p.endswith("'"):
            continue
        if re.search(r"[\s=:']", p):
            return True
    return False


def _quote_ref(ref: str) -> str:
    t, c = split_ref(ref)
    return (quote_name(t) + "." if t else "") + quote_name(c)


def _walk(nodes: Iterable[Node]):
    for n in nodes:
        yield n
        yield from _walk(n.children)


# ---------- model folder ----------
def model_files(definition_dir: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(definition_dir):
        for f in sorted(files):
            if f.lower().endswith(".tmdl"):
                out.append(os.path.join(root, f))
    return sorted(out)


def read_model(definition_dir: str) -> dict[str, TmdlFile]:
    return {p: read_file(p) for p in model_files(definition_dir)}


# ---------- writing ----------
def write_file(tf: TmdlFile) -> None:
    data = tf.text.encode("utf-8")
    with open(tf.path, "wb") as f:
        if tf.bom:
            f.write(b"\xef\xbb\xbf")
        f.write(data)


def measure_block(tf: TmdlFile, table_level: int, name: str, expr: str, props: dict | None = None,
                  description: str | None = None, lineage_tag: bool = False) -> list[str]:
    """Lines for a measure object nested under a table (Desktop layout: props at +1, fenced body at +2)."""
    ind1, ind2, ind3 = tf.indent(table_level + 1), tf.indent(table_level + 2), tf.indent(table_level + 3)
    lines: list[str] = []
    if description:
        for d in description.splitlines():
            lines.append(f"{ind1}/// {d}".rstrip())
    expr_lines = [ln.rstrip() for ln in expr.strip("\n").splitlines()]
    if len(expr_lines) == 1 and _FENCE not in expr_lines[0]:
        lines.append(f"{ind1}measure {quote_name(name)} = {expr_lines[0].strip()}")
    else:  # Desktop layout: fenced body and closing fence two levels under the properties' level
        lines.append(f"{ind1}measure {quote_name(name)} = {_FENCE}")
        lines.extend(f"{ind3}{ln}" if ln.strip() else "" for ln in expr_lines)
        lines.append(f"{ind3}{_FENCE}")
    for k, v in (props or {}).items():
        if v is None or v == "":
            continue
        lines.append(f"{ind2}{k}" if v is True else f"{ind2}{k}: {v}")
    if lineage_tag:
        lines.append(f"{ind2}lineageTag: {uuid.uuid4()}")
    return lines


def upsert_measure(tf: TmdlFile, table: Node, name: str, expr: str, props: dict | None = None,
                   description: str | None = None, lineage_tag: bool = False) -> tuple[str, int]:
    """Replace an existing measure block or insert a new one after the table's last measure (else before the
    first column, else at the end of the table). Returns (action, 1-based line of the header)."""
    table_level = 0
    existing = table.child("measure", name)
    block = measure_block(tf, table_level, name, expr, props, description, lineage_tag)
    if existing:
        start = (existing.desc_start or existing.line_start) - 1
        end = existing.line_end
        if not lineage_tag and existing.props.get("lineageTag") and not any(ln.strip().startswith("lineageTag:") for ln in block):
            block.append(f"{tf.indent(table_level + 2)}lineageTag: {existing.props['lineageTag']}")  # keep the existing tag
        tf.lines[start:end] = block
        return "updated", start + 1 + (len(description.splitlines()) if description else 0)
    measures = table.all("measure")
    if measures:
        at = max(m.line_end for m in measures)
    else:
        cols = table.all("column")
        at = (min((c.desc_start or c.line_start) for c in cols) - 1) if cols else table.line_end
    insert = block + [""] if at < len(tf.lines) and tf.lines[at:at + 1] != [""] else block
    if at > 0 and tf.lines[at - 1].strip() != "":
        insert = [""] + insert
    tf.lines[at:at] = insert
    return "added", at + 1 + (1 if insert and insert[0] == "" else 0) + (len(description.splitlines()) if description else 0)
