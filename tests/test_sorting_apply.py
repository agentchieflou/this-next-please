"""`ad-sort apply`: the human's half. It copies, it never moves, and it refuses a plan for a heap that has changed.

The split between `plan` and `apply` is the safety story of the whole tool, so these tests are mostly about what
`apply` declines to do. The one property worth stating in a sentence: after `apply`, the heap is byte-for-byte what it
was, whatever the rules said.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.sorting import SortError
from agentdata.sorting import apply as A
from agentdata.sorting import plan as P
from agentdata.sorting import rules as R

from test_sorting_plan import heap_of, ruleset


def planned(tmp_path, names, *, rules=None, dest="filed"):
    heap = heap_of(tmp_path, names)
    return heap, P.make(heap, rules or ruleset(), dest=str(tmp_path / dest))


def snapshot(root):
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(base, name)
            out[os.path.relpath(p, root)] = open(p, "rb").read()
    return out


def test_apply_copies_the_file_rows_and_leaves_the_heap_exactly_as_it_was(tmp_path):
    heap, plan = planned(tmp_path, ["10000123-a.pdf", "10000124-b.pdf", "q3.xlsx", "notes.txt"])
    before = snapshot(heap)

    result = A.run(plan)

    assert result["copied"] == 3 and result["failed"] == 0
    assert snapshot(heap) == before, "apply copies; the heap it read is still there afterwards"
    filed = snapshot(str(tmp_path / "filed"))
    assert sorted(filed) == sorted(os.path.join(*d.split("/")) for d in result["files"])
    assert set(filed.values()) == {b"some bytes\n"}


def test_the_unmatched_file_is_not_copied_anywhere(tmp_path):
    _heap, plan = planned(tmp_path, ["notes.txt", "10000123-a.pdf"])
    A.run(plan)
    assert "notes.txt" not in str(snapshot(str(tmp_path / "filed")))


def test_a_plan_whose_heap_changed_is_refused(tmp_path):
    """Applying a stale plan would file a heap nobody looked at. The fingerprint is what makes that mechanical."""
    heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    open(os.path.join(heap, "10000125-arrived-later.pdf"), "w", encoding="utf-8").write("new\n")
    with pytest.raises(SortError) as e:
        A.run(plan)
    assert e.value.code == "heap_changed"
    assert not os.path.exists(tmp_path / "filed"), "a refused apply copies nothing at all"


def test_editing_a_file_in_the_heap_also_invalidates_the_plan(tmp_path):
    heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    path = os.path.join(heap, "10000123-a.pdf")
    open(path, "w", encoding="utf-8").write("different bytes entirely\n")
    os.utime(path, (1_700_000_000, 1_700_000_000))
    with pytest.raises(SortError) as e:
        A.run(plan)
    assert e.value.code == "heap_changed"


def test_a_vanished_heap_says_so(tmp_path):
    heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    os.remove(os.path.join(heap, "10000123-a.pdf"))
    os.rmdir(heap)
    with pytest.raises(SortError) as e:
        A.run(plan)
    assert e.value.code == "heap_missing"


def test_apply_never_overwrites_a_file_that_appeared_between_the_two_commands(tmp_path):
    """The plan checked, and then time passed. This is the one thing that must never happen."""
    _heap, plan = planned(tmp_path, ["q3.xlsx"])
    target = tmp_path / "filed" / "sorted" / "sheets" / "q3.xlsx"
    target.parent.mkdir(parents=True)
    target.write_text("somebody else's q3\n", encoding="utf-8")

    result = A.run(plan)

    assert result["copied"] == 0 and result["existed"] == 1
    assert target.read_text(encoding="utf-8") == "somebody else's q3\n"


def test_apply_refuses_a_destination_override_that_lands_in_the_heap(tmp_path):
    heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    with pytest.raises(SortError) as e:
        A.run(plan, dest=os.path.join(heap, "inside"))
    assert e.value.code == "destination_inside_heap"


def test_check_ready_is_the_whole_of_dry_run_and_writes_nothing(tmp_path):
    heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    assert A.check_ready(plan).endswith("filed")
    assert not os.path.exists(tmp_path / "filed")


def test_the_receipt_says_what_was_copied_and_that_nothing_moved(tmp_path):
    _heap, plan = planned(tmp_path, ["10000123-a.pdf"])
    md = A.receipt_md(plan, A.run(plan))
    assert "## Copied (1)" in md
    assert "copies and never moves" in md
