"""Sorting an inbound heap of documents into a structure, as a plan a human reads before anything moves.

The friction this answers, in the DPM vertical: a delivery folder arrives with four hundred documents in it, named
however the sender named them, and the run cannot be routed until they are in a shape somebody agreed on. The agent had
no sanctioned way to do that -- canonical rule 12 makes writing outside `.agent/` a stop condition, correctly -- so it
did the right thing and stopped. This package is the sanctioned way, and it keeps the rule rather than carving an
exception in it.

Three invariants, each of them mechanical rather than a promise in a docstring:

- **`plan` writes nothing but its own plan file.** It reads names, sizes and mtimes through `os.scandir`, and never
  opens a candidate. `tests/test_sorting_plan.py` records every `open()` a plan performs and fails if there is one, for
  the same reason `ad-fleet inbox` does: a heap holds a bank statement and a mailed `secrets.json` next to the documents
  the job is about, and a planner that read a file to decide where it belongs would be reading all of them.
- **Nothing is guessed.** The rules are an input, the way a DPM field schema is: a file the requester supplies or agrees
  to. A file no rule claims is `unmatched` with that said out loud, never filed somewhere plausible.
- **Every entry appears in the plan.** Matched, unmatched, or refused with its reason -- a heap where `setup.exe`
  silently vanished from a listing is a heap whose listing nobody can trust again.

`apply` is a separate command, and it is the human's. It copies and never moves, so the heap it read is still there
afterwards; it re-fingerprints the heap first and refuses a plan written against a different one.
"""
from __future__ import annotations


class SortError(Exception):
    """A refusal or a hard failure. `code` is machine-readable and is printed as `meta.refused`."""

    def __init__(self, code: str, msg: str, hint: str = ""):
        super().__init__(msg)
        self.code, self.msg, self.hint = code, msg, hint
