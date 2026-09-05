"""Properties of the wire format: any table, any cell, any stdout encoding.

TOON here is **encode-only** -- nothing in this repo parses it back, so `decode(encode(t)) == t` is
not a property that exists. What replaces it is a validator: `toon.validate()` is the reader, and
"everything the encoder emits is something the validator accepts" is the round trip we actually
have. TSV carries the real round trip, through `AgentTable.read_tsv`.

The generator found four defects on its first run; each is a named test below.
"""
from __future__ import annotations
import io
import os
import subprocess
import sys

import pytest

pytest.importorskip("hypothesis", reason="hypothesis is in the dev extra")
from hypothesis import example, given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from agentdata import toon  # noqa: E402
from agentdata.model import AgentTable  # noqa: E402
from props_profiles import load_profiles  # noqa: E402

load_profiles()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A name a caller might really pass: spaces, brackets, quotes, unicode, a leading digit.
NAME = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=12)
CELL = st.one_of(
    st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
            max_size=30),
    st.integers(min_value=-10**9, max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.booleans(),
    st.none(),
)
TABLES = st.builds(
    lambda cols, rows: (cols, [r[:len(cols)] + [""] * (len(cols) - len(r)) for r in rows]),
    st.lists(NAME, min_size=1, max_size=5, unique=True),
    st.lists(st.lists(CELL, min_size=1, max_size=5), max_size=6),
)


# ------------------------------------------------------------------- the encoder and its reader


@given(table=TABLES)
def test_encoded_toon_is_always_valid(table):
    columns, rows = table
    text = toon.table("t", columns, rows)
    text.encode("utf-8")                        # must always be encodable
    assert not toon.validate(text), toon.validate(text)


@given(cell=st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
                    max_size=40))
@example(cell="a,b")
@example(cell='has "quotes"')
@example(cell="line\nbreak")
@example(cell="tab\there")
@example(cell="form\x0cfeed")      # found by the generator: \f splits a line too
@example(cell="crlf\r\nhere")
def test_a_cell_containing_a_delimiter_survives_encoding(cell):
    text = toon.table("t", ["only"], [[cell]])
    assert not toon.validate(text), f"{cell!r} produced invalid TOON: {toon.validate(text)}"


@given(mapping=st.dictionaries(NAME, st.one_of(st.integers(), st.booleans(), st.text(max_size=20)),
                               min_size=1, max_size=6))
@example(mapping={":": 0})         # found by the generator: an unquoted key of `:` re-parses
@example(mapping={"a": "x\ny"})
def test_a_scalar_block_is_always_valid(mapping):
    text = toon.encode({"meta": mapping})
    assert not toon.validate(text), toon.validate(text)


@given(columns=st.lists(NAME, min_size=1, max_size=4, unique=True))
@example(columns=['"'])            # found by the generator: an unquoted column of `"` breaks the header
@example(columns=["a,b"])
@example(columns=["a}b"])
@example(columns=["0"])
def test_a_column_name_never_changes_the_header_shape(columns):
    text = toon.table("t", columns, [["v"] * len(columns)])
    problems = toon.validate(text)
    assert not problems, f"{columns!r}: {problems}"


@given(table=TABLES)
def test_the_declared_row_count_is_the_row_count(table):
    """The count in `name[N]` is the only thing a consumer can trust to stop reading."""
    columns, rows = table
    assert toon.table("t", columns, rows).splitlines()[0].startswith(f"t[{len(rows)}]")


def test_the_quoting_set_matches_splitlines():
    """`toon.LINE_BREAKS` must be exactly what Python splits on, not a remembered subset.

    A property test found a form feed in a cell: the encoder left it bare because only the newline
    and the carriage return were on the list, and every line-based reader downstream then saw two
    rows where one was written. Scanning the BMP keeps the list honest if a release adds one.
    """
    actual = {chr(c) for c in range(0x10000) if len(("x" + chr(c) + "x").splitlines()) > 1}
    assert set(toon.LINE_BREAKS) == actual


def test_a_null_in_a_one_column_table_is_still_a_row():
    """It encodes as an indented empty line; the validator used to skip it as blank."""
    text = toon.table("t", ["only"], [[None]])
    assert not toon.validate(text), toon.validate(text)


# --------------------------------------------------------------------------- the TSV round trip


# Module-scoped so it is not re-entered per hypothesis example, and so `write_tsv()` -- which takes
# no path, by design -- lands in a temporary directory rather than the checkout's `.agent/out`.
@pytest.fixture(scope="module", autouse=True)
def _out_dir(tmp_path_factory):
    import agentdata.model as M

    old, M.OUT_DIR = M.OUT_DIR, str(tmp_path_factory.mktemp("out"))
    yield
    M.OUT_DIR = old


@given(table=TABLES)
def test_tsv_round_trips_through_agent_table(table):
    """TSV is what `.agent/out/` holds, so this one really is a round trip -- write, read, compare.

    Empty and null are one value in a TSV: `write_tsv` writes `None` as an empty field and
    `_coerce` reads an empty field back as `None`. That is the format's rule, not a loss, so both
    sides are compared with the same spelling.
    """
    columns, rows = table
    text_rows = [["" if v is None else str(v) for v in r] for r in rows]
    path = AgentTable("t", list(columns), text_rows).write_tsv()
    back = AgentTable.read_tsv(path)
    assert back.columns == list(columns)
    assert [["" if v is None else str(v) for v in r] for r in back.rows] == text_rows


# --------------------------------------------------------- encoding it under a legacy code page


@given(cell=st.sampled_from(["→ · ≤", "café", "𝄞 clef", "ünïcödé", "ok"]))
def test_encoding_never_raises_under_a_legacy_stdout(cell, tmp_path):
    """`utf8_stdout()` exists so a cp1252 or cp437 console does not turn output into `?` or a
    UnicodeEncodeError. The property is that a representable character survives the trip."""
    script = tmp_path / "emit.py"
    script.write_text(
        "from agentdata import toon\n"
        "from agentdata.console import utf8_stdout\n"
        "utf8_stdout()\n"
        "print(toon.table('t', ['c'], [[%r]]))\n" % cell,
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONIOENCODING="cp1252", NO_COLOR="1")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, cwd=REPO_ROOT,
                         env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    text = out.stdout.decode("utf-8", "replace")
    assert cell.split()[0] in text, f"{cell!r} came back as {text!r}"
    assert not toon.validate(text), toon.validate(text)


# ------------------------------------------------------------------------------------ csv2toon


DSCMD_HEADERS = st.lists(st.sampled_from(["Sales[Amount]", "'Date'[Year]", "Bare", "Model[a b]"]),
                         min_size=1, max_size=4, unique=True)


@given(headers=DSCMD_HEADERS)
def test_csv2toon_reduces_dscmd_headers_to_bare_column_names(headers, tmp_path):
    """dscmd writes `Table[Column]`; `ad-pbip`'s DAX path strips it and this one has to agree, or
    the same query gives two different TSV headers depending on which command wrote it."""
    csv_path = tmp_path / "out.csv"
    csv_path.write_text(",".join(headers) + "\r\n" + ",".join(["1"] * len(headers)) + "\r\n",
                        encoding="utf-8-sig")
    out = subprocess.run([sys.executable, "-m", "agentdata.csv2toon", str(csv_path)],
                         capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert "[" not in out.stdout.splitlines()[0], out.stdout.splitlines()[0]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_csv2toon_reads_whichever_encoding_dscmd_wrote(encoding, tmp_path):
    csv_path = tmp_path / "out.csv"
    body = 'Sales[Amount],Sales[Note]\r\n1,"a,b"\r\n'
    with io.open(csv_path, "w", encoding=encoding, newline="") as f:
        f.write(body)
    out = subprocess.run([sys.executable, "-m", "agentdata.csv2toon", str(csv_path)],
                         capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert "Amount" in out.stdout and "Note" in out.stdout


def test_csv2toon_without_a_file_is_a_usage_error_not_a_crash():
    """It ran its whole body at import time, so `import agentdata.csv2toon` raised IndexError and
    `python -m agentdata.csv2toon` printed a traceback instead of usage."""
    import importlib

    importlib.import_module("agentdata.csv2toon")          # must not do anything on import
    out = subprocess.run([sys.executable, "-m", "agentdata.csv2toon"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 2, out.stderr
    assert "Traceback" not in out.stderr
    assert "usage:" in out.stderr
