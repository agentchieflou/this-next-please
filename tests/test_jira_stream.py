r"""What a streamed result has to prove before it is allowed to replace a materialised one.

Streaming changes *when* `.agent/out/<run>_<name>.tsv` is written, and nothing else. Every test here is one of
the ways that promise could quietly break: a csv dialect that differs by a carriage return, a `None` that
becomes the string "None" instead of an empty field, a file that lands somewhere `meta.path` does not point
because the path rules were copied instead of borrowed, a sample kept as text when the materialised path keeps
it as values, and a rule-6 render that a reader could tell apart from the one `policy.render()` emits. The
byte-for-byte comparisons are the point: the happy-path changelog tests compare output files, and they must not
start failing on the size of the result.
"""
from __future__ import annotations
import os
import re

import pytest

from agentdata import jira_stream as S
from agentdata import policy, textio, toon
from agentdata.jira_stream import TsvWriter, out_path
from agentdata.model import AgentTable

COLUMNS = ["key", "changelog_id", "created_utc", "author", "field", "from_str", "to_str"]
SOURCE = "ad-jira changelog RDSD-1 RDSD-2 RDSD-3 …"


@pytest.fixture(autouse=True)
def out_dir(tmp_path, monkeypatch):
    """`write_tsv()` and `out_path()` take no directory, by design -- point them both at a temp one."""
    import agentdata.model as M

    d = str(tmp_path / "out")
    monkeypatch.setattr(M, "OUT_DIR", d)
    return d


def rows(n, start=0):
    return [{"key": f"RDSD-{1 + (i + start) // 7}", "changelog_id": 90000 + i + start,
             "created_utc": f"2026-09-{1 + (i + start) % 28:02d}T10:00:00Z", "author": "Luna Marchetti",
             "field": "status", "from_str": "To Do", "to_str": "In Progress"} for i in range(n)]


def both_files(tmp_path, records, columns=COLUMNS):
    """The same rows down both paths: `AgentTable.write_tsv` and `TsvWriter`. Returns the two files' bytes."""
    t = AgentTable.from_records(records, name="changelog", fields=list(columns))
    materialised = t.write_tsv()
    streamed = str(tmp_path / "streamed.tsv")
    w = TsvWriter(streamed, columns)
    for r in records:
        w.write(r)
    w.close()
    with open(materialised, "rb") as f, open(streamed, "rb") as g:
        return f.read(), g.read()


# ------------------------------------------------------------------------------------ byte identity


def test_the_file_is_byte_identical_to_write_tsv(tmp_path):
    a, b = both_files(tmp_path, rows(250))
    assert a == b
    assert b.count(b"\n") == 251                      # header plus every row, LF only
    assert b"\r" not in b


def test_awkward_cells_are_quoted_the_same_way(tmp_path):
    """A tab, a newline, a quote and a comma inside a value: csv's problem, and it must be csv's answer both
    times. A hand-rolled `"\\t".join()` here would have written the tab straight through and split the row."""
    columns = ["a", "b", "c", "d", "e", "f"]
    records = [
        {"a": "has\ttab", "b": "has\nnewline", "c": 'has "quotes"', "d": "has,comma", "e": None, "f": ""},
        {"a": "café ünï", "b": 42, "c": 3.5, "d": True, "e": False, "f": 0},
        {"a": " padded ", "b": "007", "c": "line\r\nbreak", "d": "\t", "e": '"', "f": "→ · ≤"},
    ]
    a, b = both_files(tmp_path, records, columns)
    assert a == b


def test_none_and_a_missing_key_are_both_the_empty_field(tmp_path):
    """`row.get(c)` is what `AgentTable.from_records(fields=…)` does, so a row that never carried a column and
    a row that carried it as `None` land as the same empty field rather than as the string "None"."""
    records = [{"key": "RDSD-1", "changelog_id": 1}, dict(rows(1)[0], author=None, to_str=None)]
    a, b = both_files(tmp_path, records)
    assert a == b
    assert b"None" not in b


def test_the_columns_decide_the_order_not_the_dict(tmp_path):
    """Rows arrive from a JSON parser in whatever order the server used; the file's shape is the columns'."""
    records = [{"to_str": "Done", "key": "RDSD-9", "author": "Luna", "changelog_id": 3}]
    a, b = both_files(tmp_path, records)
    assert a == b
    assert b.splitlines()[1].startswith(b"RDSD-9\t3\t")


# -------------------------------------------------------------------------------------- flushing


def test_the_header_is_on_disk_before_the_first_row(tmp_path):
    """A run killed during page 1 must leave a readable table, not a headerless file whose first history entry
    `read_tsv` would take for the column names."""
    p = str(tmp_path / "h.tsv")
    w = TsvWriter(p, COLUMNS)
    with open(p, "rb") as f:
        assert f.read() == ("\t".join(COLUMNS) + "\n").encode()
    w.close()


def test_a_thousand_rows_are_on_disk_without_a_close(tmp_path):
    """The flush is what makes an interrupted run worth keeping: nothing here calls `close()`, and the pages
    that were fetched are still readable."""
    p = str(tmp_path / "f.tsv")
    w = TsvWriter(p, COLUMNS)
    for r in rows(S.FLUSH_EVERY):
        w.write(r)
    back = AgentTable.read_tsv(p)
    assert back.columns == COLUMNS
    assert back.n == S.FLUSH_EVERY
    w.close()


def test_close_writes_the_tail_and_can_be_called_twice(tmp_path):
    """The caller closes in a `finally` after a `KeyboardInterrupt` may already have closed."""
    p = str(tmp_path / "t.tsv")
    w = TsvWriter(p, COLUMNS)
    for r in rows(S.FLUSH_EVERY + 7):
        w.write(r)
    w.close()
    w.close()
    assert AgentTable.read_tsv(p).n == S.FLUSH_EVERY + 7


def test_the_writer_works_as_a_context_manager(tmp_path):
    p = str(tmp_path / "c.tsv")
    with TsvWriter(p, COLUMNS) as w:
        w.write(rows(1)[0])
    assert AgentTable.read_tsv(p).n == 1


# ------------------------------------------------------------------------------- what it remembers


def test_n_and_head_are_kept_so_nothing_reads_the_file_back(tmp_path):
    records = rows(37)
    with TsvWriter(str(tmp_path / "n.tsv"), COLUMNS) as w:
        for r in records:
            w.write(r)
        assert w.n == 37
        assert len(w.head) == S.HEAD_ROWS
        assert w.head == [[r[c] for c in COLUMNS] for r in records[:S.HEAD_ROWS]]


def test_head_holds_the_same_values_the_materialised_sample_would(tmp_path):
    """Rule 6 renders `t.rows[:10]`, which are values -- ints stay ints and `None` stays `None`. `head` keeps
    them the same way, so the rendered sample cannot differ from the materialised one by a quoting rule."""
    records = [dict(rows(1)[0], author=None, changelog_id=90001)]
    t = AgentTable.from_records(records, name="changelog", fields=COLUMNS)
    with TsvWriter(str(tmp_path / "s.tsv"), COLUMNS) as w:
        w.write(records[0])
    assert w.head == t.rows
    assert w.head[0][COLUMNS.index("author")] is None


def test_head_stops_at_the_sample_size_the_policy_shows(tmp_path):
    """`head` exists to feed rule 6; keeping more rows than rule 6 shows would be memory for nothing."""
    assert S.HEAD_ROWS == policy.LARGE_SAMPLE
    with TsvWriter(str(tmp_path / "b.tsv"), COLUMNS) as w:
        for r in rows(5000):
            w.write(r)
    assert len(w.head) == policy.LARGE_SAMPLE
    assert w.n == 5000


# ------------------------------------------------------------------------------------- the path


def test_out_path_is_the_path_write_tsv_would_have_chosen(out_dir):
    """Borrowed from `AgentTable._path`, not reimplemented -- the two must not be able to disagree."""
    mine = out_path("changelog")
    theirs = AgentTable("changelog", [], []).write_tsv()
    assert os.path.dirname(mine) == os.path.dirname(theirs) == textio.norm_path(out_dir)
    assert re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{4}_changelog\.tsv", os.path.basename(mine))
    assert re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{4}_changelog\.tsv", os.path.basename(theirs))


def test_out_path_creates_the_directory_and_is_openable(out_dir):
    assert not os.path.isdir(out_dir)
    p = out_path("changelog")
    assert os.path.isdir(out_dir)
    TsvWriter(p, COLUMNS).close()
    assert os.path.isfile(p)


def test_out_path_follows_an_overridden_out_dir(tmp_path, monkeypatch):
    """A test or `AGENTDATA_OUT` moves `.agent/out`; a copied rule here would keep writing to the old one."""
    import agentdata.model as M

    monkeypatch.setattr(M, "OUT_DIR", str(tmp_path / "elsewhere"))
    assert os.path.dirname(out_path("changelog")) == textio.norm_path(str(tmp_path / "elsewhere"))


def test_the_writer_reports_the_normalised_path_meta_uses(tmp_path):
    """`meta.path` is compared across runs, so one spelling: the one `write_tsv()` returns."""
    p = os.path.join(str(tmp_path), "sub", "x.tsv")
    os.makedirs(os.path.dirname(p))
    w = TsvWriter(p, COLUMNS)
    w.close()
    assert w.path == textio.norm_path(p)


# ------------------------------------------------------------------------------- render_stream


def materialised_and_streamed(n=600, extra=None):
    """The same result rendered both ways, onto the same path, so only the mechanism differs."""
    records = rows(n)
    t = AgentTable.from_records(records, name="changelog", source=SOURCE, fields=COLUMNS)
    path = t.write_tsv()
    mat = policy.render(t)
    stream = policy.render_stream("changelog", SOURCE, COLUMNS, path, t.n, t.rows[:policy.LARGE_SAMPLE], extra)
    return t, mat, stream


def test_a_streamed_rule_6_reads_exactly_like_a_materialised_one():
    """The whole contract in one assertion: same meta keys in the same order, same 10-row sample, same action
    line, same path. The only difference is the stats block a streamed result cannot compute without the second
    pass over the file that streaming exists to avoid."""
    t, mat, stream = materialised_and_streamed()
    stats_block = toon.encode(t.stats(), key="stats")
    assert mat.endswith("\n" + stats_block)
    expected = mat[: -(len(stats_block) + 1)].split("\n")
    i = next(n for n, line in enumerate(expected) if line.startswith("  action:"))
    expected.insert(i + 1, "  stats: omitted (streamed)")
    assert stream == "\n".join(expected)
    assert "rule: 6" in stream


def test_the_omission_is_stated_rather_than_left_out():
    """A missing `stats` would read as "this result had nothing worth summarising"; it says why instead."""
    _, _, stream = materialised_and_streamed()
    assert "  stats: omitted (streamed)" in stream
    assert "\nstats:" not in stream


def test_meta_rows_is_the_file_not_the_sample():
    _, _, stream = materialised_and_streamed(n=600)
    assert "  rows: 600" in stream
    assert "  shown: 10" in stream


def test_render_stream_never_opens_the_file(tmp_path):
    """It is handed a count and a sample precisely so it does not re-read what was just written -- and it must
    still render when the file is gone, because the caller may be reporting an interrupted run."""
    gone = str(tmp_path / "not-there.tsv")
    sample = [[r[c] for c in COLUMNS] for r in rows(3)]
    out = policy.render_stream("changelog", SOURCE, COLUMNS, gone, 12345, sample)
    assert f"path: {gone}" in out
    assert "  rows: 12345" in out
    assert "  shown: 3" in out
    assert not os.path.exists(gone)


def test_extra_keys_land_at_the_end_of_meta_where_a_partial_run_puts_them():
    """`cmd_changelog` reports an interrupted pull through `extra`; those keys must not displace the rule-6
    ones a reader looks for first."""
    partial = {"partial": True, "reason": "budget", "rows_written": 600, "issues_complete": 84}
    _, _, stream = materialised_and_streamed(extra=partial)
    lines = stream.split("\n")
    body = next(n for n, line in enumerate(lines) if line.startswith("changelog["))   # the sample table
    keys = [line.strip().split(":")[0] for line in lines[1:body]]
    assert keys == ["ok", "rule", "source", "rows", "cols", "truncated", "elapsed_s", "path", "shown", "action",
                    "stats", "partial", "reason", "rows_written", "issues_complete"]
    assert "  partial: true" in stream


def test_the_encoded_output_is_valid_toon():
    _, _, stream = materialised_and_streamed()
    assert not toon.validate(stream), toon.validate(stream)
