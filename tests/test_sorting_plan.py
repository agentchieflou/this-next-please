"""`ad-sort plan`: what it reads, what it refuses, and the one thing it must never do -- open a document.

The heap this exists for is a delivery folder in the DPM vertical: several hundred documents named however the sender
named them, sitting next to whatever else was in that share. The planner decides where each one goes *by its name*, and
the test that matters most here is `test_planning_never_opens_a_file`: "we only look at names" is a comment until
something fails when it stops being true.
"""
from __future__ import annotations
import builtins
import io
import json
import os
import sys

import pytest

from agentdata.sorting import SortError
from agentdata.sorting import apply as A
from agentdata.sorting import plan as P
from agentdata.sorting import rules as R


def heap_of(tmp_path, names, *, folder="heap") -> str:
    d = tmp_path / folder
    d.mkdir(parents=True, exist_ok=True)
    for name in names:
        (d / name).write_text("some bytes\n", encoding="utf-8")
    return str(d)


def ruleset(**over) -> dict:
    base = {"version": 1, "into": "sorted", "rules": [
        {"name": "loans", "match": {"glob": "*.pdf", "regex": r"^(?P<loan>\d{8})[-_ ]"}, "into": "loans/{loan}"},
        {"name": "sheets", "match": {"glob": "*.xlsx"}, "into": "sheets"},
    ]}
    base.update(over)
    return R.check(base)


def by_source(plan: dict) -> dict:
    return {r["source"]: r for r in plan["rows"]}


# ------------------------------------------------------------------------------- the safety rule


def test_planning_never_opens_a_file(tmp_path, monkeypatch):
    """A heap holds a bank statement and somebody's mailed `secrets.json` next to the documents the job is about.

    `plan` decides by name, so it must never read one. Recorded rather than asserted in a docstring, the same way
    `tests/test_fleet_inbox.py` records it for Downloads.
    """
    heap = heap_of(tmp_path, ["10000123-packet.pdf", "secrets.json", "statement.pdf", "q3.xlsx"])
    opened = []
    real_open = builtins.open

    def watched(path, *a, **k):
        if P.is_within(str(path), heap):
            opened.append(str(path))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", watched)
    plan = P.make(heap, ruleset(), dest=str(tmp_path / "filed"))

    assert plan["counts"]["file"] == 2
    assert not opened, f"the planner opened {opened} -- it decides by name and may read no document"


def test_every_entry_appears_in_the_plan(tmp_path):
    """Nothing is dropped from the listing. A heap where a file silently vanished is one nobody trusts again."""
    names = ["10000123-packet.pdf", "statement.pdf", "q3.xlsx", "notes.txt", "installer.exe"]
    plan = P.make(heap_of(tmp_path, names), ruleset(), dest=str(tmp_path / "filed"))
    assert sorted(by_source(plan)) == sorted(names)
    assert sum(plan["counts"].values()) == len(names)


def test_an_unclaimed_file_is_said_out_loud_and_never_filed_somewhere_plausible(tmp_path):
    plan = P.make(heap_of(tmp_path, ["notes.txt"]), ruleset(), dest=str(tmp_path / "filed"))
    row = by_source(plan)["notes.txt"]
    assert row["verdict"] == "unmatched" and row["destination"] == ""
    assert "no rule" in row["why"]


# ------------------------------------------------------------------------------------- refusals


def test_two_files_wanting_one_destination_is_a_collision_not_a_rename(tmp_path):
    """Appending `(2)` would be deciding which of two documents is the real one. It refuses instead."""
    rules = ruleset(rules=[{"name": "flat", "match": {"glob": "*.pdf"}, "into": "all", "rename": "one.pdf"}])
    plan = P.make(heap_of(tmp_path, ["a.pdf", "b.pdf"]), rules, dest=str(tmp_path / "filed"))
    assert plan["counts"] == {"file": 1, "unmatched": 0, "collision": 1, "skipped": 0}
    collided = next(r for r in plan["rows"] if r["verdict"] == "collision")
    assert "already filed there by this plan" in collided["why"]


def test_a_destination_already_on_disk_is_a_collision(tmp_path):
    filed = tmp_path / "filed" / "sorted" / "sheets"
    filed.mkdir(parents=True)
    (filed / "q3.xlsx").write_text("the one that is already there\n", encoding="utf-8")
    plan = P.make(heap_of(tmp_path, ["q3.xlsx"]), ruleset(), dest=str(tmp_path / "filed"))
    assert by_source(plan)["q3.xlsx"]["verdict"] == "collision"
    assert "already there on disk" in by_source(plan)["q3.xlsx"]["why"]


def test_filing_a_heap_into_itself_is_refused(tmp_path):
    heap = heap_of(tmp_path, ["a.pdf"])
    with pytest.raises(SortError) as e:
        P.make(heap, ruleset(), dest=os.path.join(heap, "out"))
    assert e.value.code == "destination_inside_heap"


def test_the_default_destination_is_beside_the_heap_not_inside_it(tmp_path):
    heap = heap_of(tmp_path, ["10000123-a.pdf"])
    plan = P.make(heap, ruleset())
    assert not P.is_within(plan["dest"], heap), plan["dest"]
    assert os.path.basename(plan["dest"]) == "heap-sorted"


def test_a_rule_may_only_file_downwards(tmp_path):
    rules = ruleset(rules=[{"name": "up", "match": {"glob": "*.pdf"}, "into": "../elsewhere"}])
    with pytest.raises(SortError) as e:
        P.make(heap_of(tmp_path, ["a.pdf"]), rules, dest=str(tmp_path / "filed"))
    assert e.value.code == "escaping_destination"


def test_a_missing_heap_says_so_rather_than_planning_nothing(tmp_path):
    with pytest.raises(SortError) as e:
        P.make(str(tmp_path / "nope"), ruleset())
    assert e.value.code == "heap_missing"


# ------------------------------------------------------------------------- what is skipped, and why


def test_a_directory_a_partial_download_and_an_oversized_file_are_skipped_with_reasons(tmp_path, monkeypatch):
    heap = heap_of(tmp_path, ["a.pdf", "big.pdf", "half.pdf.crdownload"])
    (tmp_path / "heap" / "subfolder").mkdir()
    monkeypatch.setattr(P, "SIZE_CAP", 4)                    # "some bytes\n" is over it
    plan = P.make(heap, ruleset(), dest=str(tmp_path / "filed"))
    rows = by_source(plan)
    assert rows["subfolder"]["verdict"] == "skipped" and "directory" in rows["subfolder"]["why"]
    assert rows["half.pdf.crdownload"]["verdict"] == "skipped" and "still being written" in rows["half.pdf.crdownload"]["why"]
    assert rows["big.pdf"]["verdict"] == "skipped" and "over the" in rows["big.pdf"]["why"]


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege the runners may not have")
def test_a_link_leading_out_of_the_heap_is_skipped_and_says_where_it_leads(tmp_path):
    """`stat` and `copy2` both follow a link, so the row would describe one file and copy another."""
    outside = tmp_path / "outside.pdf"
    outside.write_text("not part of this delivery\n", encoding="utf-8")
    heap = heap_of(tmp_path, ["10000123-real.pdf"])
    os.symlink(str(outside), os.path.join(heap, "10000124-link.pdf"))
    row = by_source(P.make(heap, ruleset(), dest=str(tmp_path / "filed")))["10000124-link.pdf"]
    assert row["verdict"] == "skipped" and "leading outside the heap" in row["why"]


# ------------------------------------------------------------------------------- naming and fields


def test_captured_groups_and_date_parts_reach_the_destination(tmp_path):
    rules = ruleset(rules=[{"name": "loans",
                            "match": {"glob": "*.pdf", "regex": r"^(?P<loan>\d{8})"},
                            "into": "loans/{loan}/{year}", "rename": "{loan}{ext}"}])
    heap = heap_of(tmp_path, ["10000123-packet.pdf"])
    os.utime(os.path.join(heap, "10000123-packet.pdf"), (1_772_000_000, 1_772_000_000))
    plan = P.make(heap, rules, dest=str(tmp_path / "filed"))
    destination = by_source(plan)["10000123-packet.pdf"]["destination"]
    assert destination.startswith("sorted/loans/10000123/20")
    assert destination.endswith("/10000123.pdf")


def test_first_matching_rule_wins_so_the_file_order_is_the_precedence(tmp_path):
    rules = ruleset(rules=[{"name": "first", "match": {"glob": "*.pdf"}, "into": "one"},
                           {"name": "second", "match": {"glob": "*.pdf"}, "into": "two"}])
    plan = P.make(heap_of(tmp_path, ["a.pdf"]), rules, dest=str(tmp_path / "filed"))
    assert by_source(plan)["a.pdf"]["rule"] == "first"


def test_a_capture_containing_a_separator_cannot_dig_a_new_folder(tmp_path):
    """A filename is attacker-adjacent input: a captured value is a name, never a path."""
    rules = ruleset(rules=[{"name": "cap", "match": {"glob": "*.pdf", "regex": r"^(?P<who>.+)-packet"},
                            "into": "by/{who}"}])
    plan = P.make(heap_of(tmp_path, ["a..b-packet.pdf"]), rules, dest=str(tmp_path / "filed"))
    assert by_source(plan)["a..b-packet.pdf"]["destination"] == "sorted/by/a..b/a..b-packet.pdf"


def test_the_review_names_every_verdict_that_occurred(tmp_path):
    plan = P.make(heap_of(tmp_path, ["10000123-a.pdf", "notes.txt"]), ruleset(), dest=str(tmp_path / "filed"))
    md = P.review_md(plan)
    assert "## file (1)" in md and "## unmatched (1)" in md
    assert "Nothing has been copied" in md
