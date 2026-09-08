"""Properties of the two PBIP parsers: TMDL text and the PBIR field-reference walk.

Both are *editors* -- `ad-pbip` parses a file, changes one measure, and writes the rest back. So the
property that matters is not "the parser understands TMDL", it is **the parser does not quietly
rewrite the parts it was not asked to touch**: a tab-indented file must not come back with spaces,
a CRLF file must not come back LF, a `///` description must not move, and a quoted name with a dot
in it must not lose its quotes. Anything else shows up in someone's `git diff` as a hundred changed
lines around the one they meant.

For PBIR the same idea one level up: re-serialising a report's JSON with its keys in a different
order is a no-op to Power BI, and it has to be a no-op to the reference walk too, or a lineage
answer depends on how a file happened to be written.
"""
from __future__ import annotations
import json
import os
import shutil

import pytest

pytest.importorskip("hypothesis", reason="hypothesis is in the dev extra")
from hypothesis import example, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from agentdata.pbip import pbir as P  # noqa: E402
from agentdata.pbip import tmdl as T  # noqa: E402
from props_profiles import load_profiles  # noqa: E402

load_profiles()

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
MODEL_DIR = os.path.join(FIXTURES, "pbip", "native", "Native.SemanticModel", "definition")


def _tmdl_files() -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(MODEL_DIR):
        out += [os.path.join(dirpath, f) for f in sorted(filenames) if f.endswith(".tmdl")]
    return sorted(out)


# --------------------------------------------------------------------------- TMDL, the fixtures


@pytest.mark.skipif(not os.path.isdir(MODEL_DIR), reason="the PBIP fixture is not present")
@pytest.mark.parametrize("path", _tmdl_files() or ["<none>"], ids=os.path.basename)
def test_every_fixture_file_is_a_fixed_point(path):
    """Parse, serialise, parse again: the second text must equal the first, byte for byte."""
    if path == "<none>":
        pytest.skip("no fixture files")
    first = T.read_file(path)
    again = T.parse_text(first.text, path, bom=first.bom)
    assert again.text == first.text
    assert (again.newline, again.indent_char, again.indent_size) == \
           (first.newline, first.indent_char, first.indent_size)


@pytest.mark.skipif(not os.path.isdir(MODEL_DIR), reason="the PBIP fixture is not present")
@pytest.mark.parametrize("path", _tmdl_files() or ["<none>"], ids=os.path.basename)
def test_reading_a_fixture_file_reproduces_it_exactly(path):
    """The read-write cycle `ad-pbip` performs on a file it does not edit."""
    if path == "<none>":
        pytest.skip("no fixture files")
    with open(path, "rb") as f:
        raw = f.read()
    tf = T.read_file(path)
    rebuilt = (b"\xef\xbb\xbf" if tf.bom else b"") + tf.text.encode("utf-8")
    assert rebuilt == raw


# ------------------------------------------------------------------------ TMDL, generated files


NAME = st.sampled_from(["Sales", "'Total Sales'", "'A.B'", "'has space'", "'it''s'", "'x=y'", "'a:b'"])
PROP = st.sampled_from(["lineageTag: 1", "formatString: 0", "isHidden", "dataType: string",
                        "summarizeBy: none"])
DESC = st.sampled_from(["/// a description", "/// with 'quotes' and = signs", ""])


@st.composite
def tmdl_text(draw):
    """A small TMDL file in one of the shapes Desktop and a human each produce."""
    indent = draw(st.sampled_from(["\t", "    ", "  "]))
    newline = draw(st.sampled_from(["\n", "\r\n"]))
    trailing = draw(st.booleans())
    table = draw(NAME)
    lines = [f"table {table}"]
    for _ in range(draw(st.integers(min_value=1, max_value=4))):
        desc = draw(DESC)
        if desc:
            lines.append(indent + desc)
        kind = draw(st.sampled_from(["measure", "column"]))
        member = draw(NAME)
        if kind == "measure":
            lines.append(f"{indent}measure {member} = SUM ( Sales[Quantity] )")
        else:
            lines.append(f"{indent}column {member}")
        for _ in range(draw(st.integers(min_value=0, max_value=2))):
            lines.append(indent * 2 + draw(PROP))
        lines.append("")
    text = newline.join(lines)
    return text + (newline if trailing else "")


@given(text=tmdl_text())
@example(text="table T\n\tmeasure M = 1\n")
@example(text="table T\r\n\tmeasure M = 1\r\n")
@example(text="table 'A.B'\n\tcolumn 'it''s'\n")
@settings(max_examples=100)
def test_parse_then_serialise_is_a_fixed_point(text):
    once = T.parse_text(text, "tables/T.tmdl")
    twice = T.parse_text(once.text, "tables/T.tmdl")
    assert twice.text == once.text, "a second pass changed the file"


@given(text=tmdl_text())
def test_the_indent_and_newline_a_file_arrived_with_are_the_ones_it_leaves_with(text):
    tf = T.parse_text(text, "tables/T.tmdl")
    assert tf.newline in tf.text or "\n" not in tf.text
    if "\r\n" in text:
        assert tf.newline == "\r\n", "a CRLF file must not come back LF"
    if text.startswith("table") and "\n\t" in text:
        assert tf.indent_char == "\t", "a tab-indented file must not come back with spaces"


@given(text=tmdl_text())
def test_a_quoted_name_keeps_its_quotes(text):
    """`'A.B'` unquoted is two names. `quote_name` and `unquote` have to be inverses."""
    tf = T.parse_text(text, "tables/T.tmdl")
    for node in tf.nodes:
        if node.name:
            assert T.unquote(T.quote_name(node.name)) == node.name


@given(name=st.sampled_from(["Sales", "A.B", "has space", "it's", "x=y", "a:b", "Total Sales"]))
def test_quote_name_and_unquote_are_inverses(name):
    assert T.unquote(T.quote_name(name)) == name


# --------------------------------------------------------------------------------------- PBIR


def _report_dir() -> str:
    return os.path.join(FIXTURES, "pbip", "native")


@pytest.mark.skipif(not os.path.isdir(os.path.join(FIXTURES, "pbip", "native")),
                    reason="the PBIP fixture is not present")
def test_the_reference_walk_is_blind_to_key_order(tmp_path):
    """Re-serialising every JSON file with sorted keys must find the same references.

    Power BI Desktop and pbi-tools write the same report with different key order; a lineage answer
    that depends on which wrote it is not an answer.
    """
    src = _report_dir()
    dst = str(tmp_path / "native")
    shutil.copytree(src, dst)

    before = P.load_report(dst)
    before_refs = sorted(r.label() for _v, r in before.all_refs())

    for dirpath, _dirnames, filenames in os.walk(dst):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, sort_keys=True, indent=1)

    after = P.load_report(dst)
    after_refs = sorted(r.label() for _v, r in after.all_refs())
    assert after_refs == before_refs
    assert before_refs, "the fixture should contain at least one field reference"


@given(entity=st.text(alphabet="abcXY ._'", min_size=1, max_size=10),
       prop=st.text(alphabet="abcXY ._'", min_size=1, max_size=10))
def test_a_field_reference_label_never_loses_its_entity(entity, prop):
    """`label` is what the TSV shows and what a person greps for."""
    ref = P.FieldRef(kind="column", entity=entity, prop=prop, file="f", path="$")
    assert entity in ref.label() and prop in ref.label()
