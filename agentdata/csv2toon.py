"""`python -m agentdata.csv2toon FILE.csv` -> TOON through the format policy.

This is what `skills/dax-studio-export` tells an agent to run on a dscmd export, so it has to agree
with the `ad-pbip` DAX path on two things a CSV from a Windows tool gets wrong:

* **the encoding.** dscmd writes UTF-8 with a BOM on one machine and UTF-16 LE on another, depending
  on how it was invoked. Reading through `textio` means the same file works either way, instead of
  a `UnicodeDecodeError` a long way from the cause.
* **the headers.** A DAX result names its columns `Table[Column]`; both paths reduce that to the
  bare column name with `dax.clean_header`, so the TSV a skill writes has the same header whichever
  route produced it.
"""
from __future__ import annotations
import csv
import io
import sys

from . import textio
from .model import AgentTable, _coerce
from .pbip.dax import clean_header
from .policy import render


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] in ("-h", "--help"):
        usage = "usage: python -m agentdata.csv2toon FILE.csv"
        print(usage, file=sys.stderr if len(args) != 1 else sys.stdout)
        return 2 if len(args) != 1 else 0

    path = args[0]
    rows = list(csv.reader(io.StringIO(textio.read_text(path), newline="")))
    if not rows:
        print(f"empty csv: {path}", file=sys.stderr)
        return 1
    cols = [clean_header(h) for h in rows[0]]
    table = AgentTable("dax", cols, [[_coerce(v) for v in r] for r in rows[1:]], source=path)
    print(render(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
