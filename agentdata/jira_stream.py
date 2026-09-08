r"""Writing a result to `.agent/out/` while it is still being fetched, so a run that dies has still delivered.

`AgentTable` keeps every row in memory and writes the file at the end. That is right for a query that returns
forty rows and wrong for the one that forced this module: `ad-jira changelog --jql "project = RDSD"` over five
thousand issues with deep histories built hundreds of thousands of dicts before the first byte reached disk, and
a 502 at minute fourteen -- or a Ctrl-C, or an exhausted request budget -- threw all of them away. The human
then paid for the same pull a second time. `TsvWriter` is the same file, written as the pages arrive: peak
memory is one page, and whatever was fetched before the failure is already on disk.

It carries the two numbers a caller would otherwise have to re-read the file to get. `.n` is the row count that
goes in `meta.rows`, and `.head` is the first ten rows -- exactly `policy.LARGE_SAMPLE` of them -- so
`policy.render_stream` can show the sample without opening what was just written.

The hard requirement is byte identity. A file written here and a file written by `AgentTable.write_tsv` for the
same rows and columns must not differ by one byte: the same csv dialect, the same tab, the same LF, the same
empty field for `None` and for a key the row does not have. Streaming is a decision about *when* the file is
written, never about what is in it, and the happy-path tests that compare changelog output file-for-file must
not be able to tell which path produced it. `tests/test_jira_stream.py` builds both and compares the bytes.
"""
from __future__ import annotations
import csv
from typing import Any, Iterable

from . import textio
from .model import AgentTable

# Every 1,000 rows the buffer goes to the kernel. Small enough that a killed run loses at most a page's tail,
# large enough that a 100,000-row pull is a hundred flushes rather than a syscall per row.
FLUSH_EVERY = 1000
# The sample rule 6 shows. Kept in step with `policy.LARGE_SAMPLE` by a test rather than by an import, because
# `policy` imports `model` and this module is meant to stay underneath both.
HEAD_ROWS = 10


def out_path(name: str) -> str:
    """The path `AgentTable.write_tsv()` would have chosen for a table of this name.

    This reaches through to `AgentTable._path`, a private method, on purpose. The convention it implements --
    `OUT_DIR`, the run id, the extension, and creating the directory -- belongs to the format policy, and a
    second copy of those rules here would be a second thing to keep in step: the first test that overrides
    `model.OUT_DIR`, or the first change to the run-id shape, would silently give two different answers for the
    same table and the streamed file would land somewhere the meta does not point. Borrowing the method costs
    one underscore and keeps one source of truth.
    """
    return textio.norm_path(AgentTable(name=name, columns=[], rows=[])._path("tsv"))


class TsvWriter:
    """A TSV opened once, appended to per page, and closed at the end.

    The header is written and flushed on open, so a file that exists is always a readable table -- an
    interrupted run leaves a short file, never a headerless one that `AgentTable.read_tsv` reads as columns of
    data.
    """

    def __init__(self, path: str, columns: Iterable[str]) -> None:
        self.path = textio.norm_path(path)
        self.columns = list(columns)
        self.n = 0
        self.head: list[list[Any]] = []
        # newline="" and lineterminator="\n" together are what stop Windows from writing CRLF; encoding is
        # explicit because a cp1252 default would fail on the first accented display name in an author column.
        self._fh = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._fh, delimiter="\t", lineterminator="\n")
        self._w.writerow(self.columns)
        self._fh.flush()

    def write(self, row: dict) -> None:
        """Append one row, taking the columns in order. A key the row does not carry is an empty field."""
        values = [row.get(c) for c in self.columns]
        if len(self.head) < HEAD_ROWS:
            self.head.append(list(values))
        self._w.writerow(["" if v is None else v for v in values])
        self.n += 1
        if self.n % FLUSH_EVERY == 0:
            self._fh.flush()

    def close(self) -> None:
        """Idempotent, because the caller closes in a `finally` and may already have closed on the way out."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "TsvWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
