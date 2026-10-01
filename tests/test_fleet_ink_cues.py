"""The cue contract (#373, epic #293): every skin module that ships cues keys them on the page's
own classes, and on elements the page does not rebuild. No browser.

A cue row (docs/desk-ink.md §Effects) is easy to key on something the page rebuilds or trims --
transcript lines past 200, the asks list on a signature change, notes past 50 -- or on a class
nobody sets. The layer checks a row's shape when the table is set; what it cannot know is where a
class comes from, or whether an element outlives a redraw. That is read here, from the sources:

* a module with `cues` also exports `cue` and `tick`;
* each row's `on` is `arrive` or `leave`, and its `cue` a short lower-case name;
* each cue name is in a table row of the skin's page, `docs/skin-<name>.md` (the example has none);
* each class a row names is one `app.js` or `index.html` sets, by the voxel test's logic; each
  `#id` is in `index.html`; the one attribute is `hidden` (the example's rows name test-only
  `ink-*` classes, as `TABLE` in test_fleet_ink.py does, so its classes are not held to this);
* a leave row's subject is never an element the page rebuilds or trims (`REBUILT`);
* an arrive row on a transcript line is only for a line that is news: `li.denied`, `li.friction`
  or `li.error`.

A module may also ship `expresses` (docs/desk-ink.md §The state grammar across skins): a strict
JSON literal, `{"*" | <variant>: {<grammar entry>: "<expression>"}}`, naming the entries of the
state grammar the genre draws with its own materials instead of a mark. It is read here as the
cues are (`expresses_of`), and held to: keys are `*` or a variant skins.py gives the skin, every
entry is one of the grammar's, and every expression name is in a table row of the skin's page.

The helpers (`cue_rows`, `mark_selectors`, `expresses_of`) are for the skin tests: the voxel and farmstead guards
count every `selector:` literal in their module, and a skin card that adds cues counts
`mark_selectors` instead.
"""
from __future__ import annotations
import json
import os
import re

import pytest

from agentdata.fleet import agentstate, skins as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
SKINS = os.path.join(STATIC, "ink", "skins")
DOCS = os.path.join(ROOT, "docs")

#: Subjects the page rebuilds or trims: a leave row on one would cue for a redraw, not a change.
#: `li` is every list line (transcript lines past 200, the asks on a signature change, notes past 50).
REBUILT = ("li", ".ask", ".session-row", ".sib-row", ".assumption", ".scope-row", ".rail-chip", ".cell")
#: The transcript lines that are news when they arrive, not history the page is replaying.
NEWS_LINES = ("denied", "friction", "error")
#: The one attribute a cue may key on: the render contract's `hide`.
ATTRIBUTES = ("hidden",)
CUE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
#: Skins whose rows name test-only classes and that have no page of their own.
EXEMPT = ("example.js",)
#: The state grammar's entries (`GRAMMAR` in tests/test_fleet_ink.py, the doc's table), the only
#: keys an `expresses` block may name.
ENTRIES = ("needs_name", "needs_q", "needs_card", "answered", "running", "error_bang", "error_box", "done")


class CueError(AssertionError):
    """A cue table this contract cannot read or does not allow, naming the file and the row."""


# ------------------------------------------------------------------------------------ reading


def _skip_string(src: str, i: int) -> int:
    """The index after the string literal that starts at `src[i]` (a quote or a backtick)."""
    quote, i = src[i], i + 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == quote:
            return i + 1
        i += 1
    raise CueError("an unterminated string")


def _match(src: str, i: int) -> int:
    """The index of the bracket that closes the one at `src[i]`, stepping over strings and
    comments."""
    pairs = {"[": "]", "{": "}", "(": ")"}
    stack = [pairs[src[i]]]
    i += 1
    while i < len(src):
        c = src[i]
        if c in "\"'`":
            i = _skip_string(src, i)
            continue
        if src.startswith("//", i):
            i = src.find("\n", i) if "\n" in src[i:] else len(src)
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end < 0:
                raise CueError("an unterminated comment")
            i = end + 2
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")]}":
            if not stack or stack.pop() != c:
                raise CueError(f"a mismatched {c!r}")
            if not stack:
                return i
        i += 1
    raise CueError("an unclosed bracket")


def _cue_block(src: str, where: str) -> tuple[int, int] | None:
    """Where `export const cues = [...]` or `export function cues(...) {...}` is: its span, or
    None for a module that ships no cues."""
    m = re.search(r"\bexport\s+const\s+cues\s*=\s*(?=\[)", src)
    if m:
        start = m.end()
    else:
        m = re.search(r"\bexport\s+function\s+cues\s*\(", src)
        if not m:
            if re.search(r"\bcues\b\s*[,}=]", src) and re.search(r"\bexport\b[^;\n]*\bcues\b", src):
                raise CueError(f"{where}: a `cues` export this contract cannot read")
            return None
        start = src.index("{", _match(src, m.end() - 1))
    try:
        return m.start(), _match(src, start) + 1
    except CueError as e:
        raise CueError(f"{where}: the cues block does not parse ({e})") from None


def _literal(row: str, key: str) -> str | None:
    m = re.search(rf'(?<![\w$]){key}\s*:\s*"((?:[^"\\]|\\.)*)"\s*(?=[,}}])', row)
    return m.group(1).replace('\\"', '"') if m else None


def cue_rows(path: str) -> list[dict]:
    """The rows of a skin module's `cues`, `[{"selector", "on", "cue"}, ...]`, in order: `[]` when
    it ships none. A block it cannot read, or a row whose `selector`, `on` or `cue` is not a plain
    string, raises `CueError` naming the file and the row."""
    where = os.path.basename(path)
    src = open(path, encoding="utf-8").read()
    span = _cue_block(src, where)
    if span is None:
        return []
    block = src[span[0]:span[1]]
    rows, i = [], block.index("[") if "[" in block else -1
    if i < 0:
        raise CueError(f"{where}: the cues block holds no array")
    while True:
        i = block.find("{", i + 1)
        if i < 0:
            break
        end = _match(block, i)
        text = block[i:end + 1]
        if "selector" in text:
            got = {k: _literal(text, k) for k in ("selector", "on", "cue")}
            missing = [k for k, v in got.items() if v is None]
            if missing:
                raise CueError(f"{where}: cue row {len(rows)} ({' '.join(text.split())}): "
                               f"{', '.join(missing)} is not a plain string")
            rows.append(got)
        i = end
    if not rows:
        raise CueError(f"{where}: the cues block has no row this contract can read")
    return rows


def expresses_of(path: str) -> dict[str, dict[str, str]]:
    """A skin module's `expresses`, `{"*" | variant: {entry: expression}}`: `{}` when it ships
    none. A block that is not a strict JSON object literal of that shape raises `CueError`."""
    where = os.path.basename(path)
    src = open(path, encoding="utf-8").read()
    m = re.search(r"\bexport\s+const\s+expresses\s*=\s*(?=\{)", src)
    if not m:
        if re.search(r"\bexpresses\b", src):
            raise CueError(f"{where}: an `expresses` that is not `export const expresses = {{...}}`")
        return {}
    try:
        block = src[m.end():_match(src, m.end()) + 1]
        got = json.loads(block)
    except (CueError, ValueError) as e:
        raise CueError(f"{where}: `expresses` is not a strict JSON object ({e})") from None
    if not isinstance(got, dict) or not got:
        raise CueError(f"{where}: `expresses` is an empty or non-object literal")
    for key, entries in got.items():
        if not isinstance(entries, dict) or not entries \
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in entries.items()):
            raise CueError(f"{where}: expresses[{key!r}] is not {{entry: expression}}")
    return got


def check_expresses(path: str, *, docs: str = DOCS) -> list[str]:
    """What is wrong with a module's `expresses`, one line per rule broken: `[]` when it keeps the
    contract or ships none."""
    name = os.path.basename(path)
    try:
        got = expresses_of(path)
    except CueError as e:
        return [str(e)]
    if not got:
        return []
    wrong = []
    variants = list(K.SKINS.get(name[:-3], {}).get("variants", {}))
    doc = os.path.join(docs, f"skin-{name[:-3]}.md")
    table = [ln for ln in (open(doc, encoding="utf-8").read() if os.path.exists(doc) else "").splitlines()
             if ln.lstrip().startswith("|")]
    for key, entries in got.items():
        if key != "*" and key not in variants:
            wrong.append(f"{name}: expresses[{key!r}] names no variant of the skin")
        for entry, expression in entries.items():
            at = f"{name}: expresses[{key!r}].{entry}"
            if entry not in ENTRIES:
                wrong.append(f"{at}: not an entry of the state grammar")
            if not CUE_NAME.match(expression):
                wrong.append(f"{at}: the expression name is not {CUE_NAME.pattern}")
            elif not any(re.search(rf"(?<![\w-]){re.escape(expression)}(?![\w-])", ln) for ln in table):
                wrong.append(f"{at}: {expression!r} is in no table row of docs/skin-{name[:-3]}.md")
    return wrong


def mark_selectors(path: str) -> list[str]:
    """Every `selector: "..."` literal in a skin module outside its cues block: its mark rows."""
    src = open(path, encoding="utf-8").read()
    span = _cue_block(src, os.path.basename(path))
    if span:
        src = src[:span[0]] + src[span[1]:]
    return [s.replace('\\"', '"') for s in re.findall(r'selector: "((?:[^"\\]|\\.)*)"', src)]


def _compounds(selector: str) -> list[str]:
    """A selector's compound selectors, split at its combinators outside parentheses and brackets."""
    out, depth, cur = [], 0, ""
    for c in selector.strip():
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if depth == 0 and (c.isspace() or c in ">+~"):
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += c
    if cur:
        out.append(cur)
    return out


def _type_of(compound: str) -> str:
    m = re.match(r"[A-Za-z][\w-]*", compound)
    return m.group(0).lower() if m else ""


def _classes(sel: str) -> list[str]:
    return re.findall(r"\.([A-Za-z_][\w-]*)", sel)


# ------------------------------------------------------------------------------------ checking


def _page():
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    return app, html


def _class_is_set(cls: str, app: str, html: str) -> bool:
    """The voxel test's rule (tests/test_fleet_voxel_ink.py): a class the page sets."""
    if cls.startswith("state-"):
        return cls[6:] in agentstate.STATES and '"state-" + state' in app
    if cls in NEWS_LINES:
        shown = app[app.index("var SHOWN = {"):]
        shown = shown[:shown.index("};")]
        return bool(re.search(rf"\b{cls}: 1", shown)) and "setClass(li, ev.kind)" in app
    if cls == "stale":
        # The chip's only writer; it matches neither quoted pattern below.
        return '(ac.stale ? " stale" : "")' in app
    return (f'"{cls}"' in app or f'"{cls}' in app
            or bool(re.search(rf'class="[^"]*\b{re.escape(cls)}\b', html)))


def check(path: str, *, app: str | None = None, html: str | None = None,
          docs: str = DOCS, exempt: bool | None = None) -> list[str]:
    """What is wrong with a skin module's cue table, one line per rule broken, each naming the file
    and the row: `[]` when it keeps the contract or ships no cues."""
    if app is None or html is None:
        app, html = _page()
    name = os.path.basename(path)
    exempt = name in EXEMPT if exempt is None else exempt
    try:
        rows = cue_rows(path)
    except CueError as e:
        return [str(e)]
    if not rows:
        return []
    src = open(path, encoding="utf-8").read()
    wrong = []
    for hook in ("cue", "tick"):
        if not re.search(rf"\bexport\s+(?:function\s+{hook}\s*\(|const\s+{hook}\s*=)", src):
            wrong.append(f"{name}: exports `cues` but no `{hook}`")
    page = None
    if not exempt:
        doc = os.path.join(docs, f"skin-{name[:-3]}.md")
        page = open(doc, encoding="utf-8").read() if os.path.exists(doc) else ""
    for i, row in enumerate(rows):
        at = f"{name}: cue row {i} ({row['selector']!r}, {row['on']}, {row['cue']!r})"
        if row["on"] not in ("arrive", "leave"):
            wrong.append(f"{at}: `on` is arrive or leave")
        if not CUE_NAME.match(row["cue"]):
            wrong.append(f"{at}: the cue name is not {CUE_NAME.pattern}")
        if page is not None:
            table = [ln for ln in page.splitlines() if ln.lstrip().startswith("|")]
            if not any(re.search(rf"(?<![\w-]){re.escape(row['cue'])}(?![\w-])", ln) for ln in table):
                wrong.append(f"{at}: the cue is in no table row of docs/skin-{name[:-3]}.md")
        sel = row["selector"]
        if not exempt:
            for cls in _classes(sel):
                if not _class_is_set(cls, app, html):
                    wrong.append(f"{at}: .{cls} is a class nobody sets")
        for ident in re.findall(r"#([A-Za-z_][\w-]*)", sel):
            if not re.search(rf'\bid="{re.escape(ident)}"', html):
                wrong.append(f"{at}: #{ident} is not in index.html")
        for attr in re.findall(r"\[\s*([\w-]+)", sel):
            if attr not in ATTRIBUTES:
                wrong.append(f"{at}: [{attr}] is not an attribute a cue may key on (only hidden)")
        parts = _compounds(sel)
        subject = parts[-1] if parts else ""
        subject_classes = _classes(re.sub(r":not\([^)]*\)", "", subject))
        if row["on"] == "leave":
            rebuilt = [r for r in REBUILT
                       if (r == _type_of(subject)) or (r.startswith(".") and r[1:] in subject_classes)]
            if rebuilt:
                wrong.append(f"{at}: a leave row on {rebuilt[0]}, which the page rebuilds or trims")
        if row["on"] == "arrive" and _type_of(subject) == "li" \
                and any("transcript" in _classes(p) for p in parts[:-1]) \
                and not any(c in NEWS_LINES for c in subject_classes):
            wrong.append(f"{at}: an arrive row on a transcript line other than "
                         f"li.denied, li.friction or li.error")
    return wrong


# ------------------------------------------------------------------------------------ the skins


def _shipping():
    return sorted(n for n in os.listdir(SKINS) if n.endswith(".js")
                  and cue_rows(os.path.join(SKINS, n)))


def test_every_skin_that_ships_cues_keeps_the_contract():
    """It passes with only the example shipping cues, and picks up voxel and farmstead the day
    they do: every module under static/ink/skins/ is read."""
    shipping = _shipping()
    assert "example.js" in shipping, shipping
    for name in shipping:
        assert check(os.path.join(SKINS, name)) == [], name


def test_every_skin_that_expresses_a_state_keeps_the_contract():
    """The gridiron and the rain express states (docs/desk-ink.md §The state grammar across skins);
    every module under static/ink/skins/ is read, so a new one is held the day it lands."""
    expressing = sorted(n for n in os.listdir(SKINS) if n.endswith(".js")
                        and expresses_of(os.path.join(SKINS, n)))
    assert expressing == ["gridiron.js", "weather.js"], expressing
    for name in expressing:
        assert check_expresses(os.path.join(SKINS, name)) == [], name
    assert set(expresses_of(os.path.join(SKINS, "gridiron.js"))) == {"*"}
    assert set(expresses_of(os.path.join(SKINS, "weather.js"))) == {"rainy", "showers"}, "the rain alone"


def test_the_expresses_contract_reads_a_strict_literal_and_holds_its_names(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "skin-sample.md").write_text("| sign | when |\n| --- | --- |\n| `flag` | needs you |\n",
                                                     encoding="utf-8")
    def wrong(body):
        path = tmp_path / "sample.js"
        path.write_text(body, encoding="utf-8")
        return check_expresses(str(path), docs=str(tmp_path / "docs"))
    assert wrong('export const expresses = { "*": { "needs_name": "flag" } };\n') == []
    assert wrong("export function marks() { return []; }\n") == []
    got = wrong('export const expresses = { "*": { "needs_name": "kite", "flags": "flag" }, "night": { "done": "flag" } };\n')
    assert any("'kite' is in no table row" in w for w in got), got
    assert any("flags: not an entry" in w for w in got), got
    assert any("names no variant" in w for w in got), got
    assert any("not a strict JSON object" in w for w in wrong('const x = 1;\nexport const expresses = { "*": { needs_name: "flag" } };\n'))
    assert any("not `export const expresses" in w for w in wrong("export function expresses() {}\n"))


def test_the_example_rows_are_the_three_from_372_and_its_marks_are_apart_from_them():
    path = os.path.join(SKINS, "example.js")
    assert cue_rows(path) == [
        {"selector": ".tile.ink-cue", "on": "arrive", "cue": "example"},
        {"selector": "#grid > .tile:not(.is-hidden)", "on": "leave", "cue": "example-leave"},
        {"selector": ".tile .transcript li.denied", "on": "arrive", "cue": "example-line"},
    ]
    assert mark_selectors(path) == [".tile.needs-human .repo", ".tile.ink-example .head"]


def test_a_module_without_cues_has_no_rows_and_all_its_selectors_are_marks():
    for name in sorted(os.listdir(SKINS)):
        if not name.endswith(".js") or name in _shipping():
            continue
        path = os.path.join(SKINS, name)
        src = open(path, encoding="utf-8").read()
        assert cue_rows(path) == [], name
        assert mark_selectors(path) == [s.replace('\\"', '"') for s in
                                        re.findall(r'selector: "((?:[^"\\]|\\.)*)"', src)], name


# ------------------------------------------------------------------------ each rule, on a sample


GOOD = '''export function marks() { return [{ selector: ".tile.needs-human .repo", tool: "pen", shape: "ring" }]; }
export const cues = [
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "gone" },
  { selector: ".tile .transcript li.denied", on: "arrive", cue: "refused" },
];
export function cue() {}
export function tick() { return false; }
'''
DOC = "# A sample\n\n| cue | when |\n| --- | --- |\n| `gone` | a pane leaves |\n| `refused` | a refusal |\n"


def _sample(tmp_path, cues=None, *, doc=DOC, module=None):
    """`check` of a sample module, `GOOD` with its cues block replaced by `cues`, or `module`."""
    if module is None:
        module = GOOD if cues is None else (GOOD[:GOOD.index("export const cues")] + cues
                                            + GOOD[GOOD.index("export function cue()"):])
    (tmp_path / "skins").mkdir(exist_ok=True)
    path = tmp_path / "skins" / "sample.js"
    path.write_text(module, encoding="utf-8")
    if doc is not None:
        (tmp_path / "skin-sample.md").write_text(doc, encoding="utf-8")
    return check(str(path), docs=str(tmp_path))


def _one(tmp_path, row, doc=None):
    cues = f"export const cues = [\n  {row},\n];\n"
    name = re.search(r'cue: "([^"]*)"', row)
    doc = doc if doc is not None else DOC + (f"| `{name.group(1)}` | x |\n" if name else "")
    return _sample(tmp_path, cues, doc=doc)


def test_the_sample_that_keeps_every_rule_passes(tmp_path):
    assert _sample(tmp_path) == []


def test_a_leave_row_on_a_transcript_line_fails_naming_the_file_and_the_row(tmp_path):
    got = _one(tmp_path, '{ selector: ".tile .transcript li", on: "leave", cue: "line-gone" }')
    assert any(w.startswith("sample.js: cue row 0 ('.tile .transcript li', leave, 'line-gone')")
               and "a leave row on li" in w for w in got), got
    for rebuilt in (".ask", ".session-row", ".sib-row", ".assumption", ".scope-row", ".rail-chip", ".cell"):
        got = _one(tmp_path, f'{{ selector: ".tile {rebuilt}", on: "leave", cue: "x" }}')
        assert any(f"a leave row on {rebuilt}" in w for w in got), (rebuilt, got)


def test_a_class_nobody_sets_fails(tmp_path):
    got = _one(tmp_path, '{ selector: ".tile.is-on-fire", on: "arrive", cue: "fire" }')
    assert got == ["sample.js: cue row 0 ('.tile.is-on-fire', arrive, 'fire'): "
                   ".is-on-fire is a class nobody sets"], got


def test_an_attribute_other_than_hidden_fails(tmp_path):
    got = _one(tmp_path, '{ selector: ".tile[aria-busy]", on: "arrive", cue: "busy" }')
    assert got == ["sample.js: cue row 0 ('.tile[aria-busy]', arrive, 'busy'): "
                   "[aria-busy] is not an attribute a cue may key on (only hidden)"], got
    assert _one(tmp_path, '{ selector: ".tile[hidden]", on: "arrive", cue: "hid" }') == []


def test_a_cue_name_missing_from_the_skins_doc_fails(tmp_path):
    got = _one(tmp_path, '{ selector: ".tile.state-done", on: "arrive", cue: "done" }', doc=DOC)
    assert got == ["sample.js: cue row 0 ('.tile.state-done', arrive, 'done'): "
                   "the cue is in no table row of docs/skin-sample.md"], got
    # Prose outside a table does not count, and neither does a longer name in a row.
    got = _one(tmp_path, '{ selector: ".tile.state-done", on: "arrive", cue: "done" }',
               doc=DOC + "\nThe `done` cue.\n| `done-ish` | x |\n")
    assert len(got) == 1 and "no table row" in got[0], got


def test_a_malformed_cues_block_fails(tmp_path):
    got = _sample(tmp_path, module=GOOD.replace('cue: "refused" },\n];', 'cue: "refused" },\n'))
    assert len(got) == 1 and got[0].startswith("sample.js: the cues block does not parse"), got
    got = _sample(tmp_path, module=GOOD.replace('cue: "gone"', "cue: NAME"))
    assert got == ['sample.js: cue row 0 ({ selector: "#grid > .tile:not(.is-hidden)", on: "leave", '
                   'cue: NAME }): cue is not a plain string'], got
    got = _sample(tmp_path, module="export const cues = CUES;\nexport function cue() {}\nexport function tick() {}\n")
    assert got == ["sample.js: a `cues` export this contract cannot read"], got


def test_a_cue_function_of_the_variant_is_read_like_the_array(tmp_path):
    module = GOOD.replace("export const cues = [", "export function cues(variant) {\n  return [").replace(
        '"refused" },\n];', '"refused" },\n  ];\n}')
    assert _sample(tmp_path, module=module) == []


def test_the_other_rules_each_fail_on_their_own_row(tmp_path):
    cases = {
        '{ selector: ".tile.state-done", on: "hover", cue: "done" }': "`on` is arrive or leave",
        '{ selector: ".tile.state-done", on: "arrive", cue: "Done!" }': "the cue name is not",
        '{ selector: "#nowhere .tile", on: "arrive", cue: "done" }': "#nowhere is not in index.html",
        '{ selector: ".tile .transcript li.tool_call", on: "arrive", cue: "done" }':
            "an arrive row on a transcript line other than li.denied, li.friction or li.error",
        '{ selector: ".tile.state-sleeping", on: "arrive", cue: "done" }': ".state-sleeping is a class nobody sets",
    }
    for row, rule in cases.items():
        got = _one(tmp_path, row, doc=DOC + "| `done` | x |\n| `Done!` | x |\n")
        assert len(got) == 1 and got[0].startswith("sample.js: cue row 0 (") and rule in got[0], (row, got)
    for line in ("denied", "friction", "error"):
        assert _one(tmp_path, f'{{ selector: ".tile .transcript li.{line}", on: "arrive", cue: "news" }}') == []
    got = _sample(tmp_path, module=GOOD.replace("export function tick() { return false; }\n", ""))
    assert got == ["sample.js: exports `cues` but no `tick`"], got


def test_a_cue_on_the_stale_chip_passes_the_class_origin_rule(tmp_path):
    assert _one(tmp_path, '{ selector: ".tile .chip.stale", on: "arrive", cue: "stale" }') == []
    # Only because the chip's one writer is there to point at.
    app, html = _page()
    path = tmp_path / "skins" / "sample.js"
    assert any(".stale is a class nobody sets" in w for w in
               check(str(path), app=app.replace('(ac.stale ? " stale" : "")', "(x)"), html=html,
                     docs=str(tmp_path))), "stale accepted without its writer"


def test_the_contract_is_named_in_the_ink_docs():
    assert "tests/test_fleet_ink_cues.py" in open(os.path.join(DOCS, "desk-ink.md"), encoding="utf-8").read()
    assert "tests/test_fleet_ink_cues.py" in open(os.path.join(DOCS, "testing-this-repo.md"),
                                                  encoding="utf-8").read()


@pytest.mark.parametrize("sel,want", [
    ("#grid > .tile:not(.is-hidden)", ["#grid", ".tile:not(.is-hidden)"]),
    (".tile .transcript li.denied", [".tile", ".transcript", "li.denied"]),
    (".a[data-x='a b'] + .b ~ .c", [".a[data-x='a b']", ".b", ".c"]),
])
def test_a_selector_splits_at_its_combinators_only(sel, want):
    assert _compounds(sel) == want
