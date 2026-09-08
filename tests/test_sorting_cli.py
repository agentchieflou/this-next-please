"""`ad-sort` at the command line: exit codes, the files it writes, and the rule set as an input.

The exit codes are the contract a script reads: 0 filed something, 1 the heap is real but no rule claimed anything in
it, 2 refused. The middle one matters -- a heap nobody has written rules for looks exactly like a heap that is already
tidy unless the command says otherwise.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import cli_sort
from agentdata.sorting import rules as R

from test_sorting_plan import heap_of


def run(argv, capsys):
    code = cli_sort.main(argv)
    return code, capsys.readouterr().out


def starter(tmp_path) -> str:
    path = str(tmp_path / "rules.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(R.STARTER, f)
    return path


def test_rules_write_then_plan_then_apply_is_the_whole_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    heap = heap_of(tmp_path, ["10000123-packet.pdf", "notes.txt"])

    code, out = run(["rules", "--write", "rules.json"], capsys)
    assert code == 0 and "ad-sort rules" in out

    code, out = run(["plan", "--heap", heap, "--rules", "rules.json", "--dest", str(tmp_path / "filed")], capsys)
    assert code == 0
    assert "file: 1" in out and "unmatched: 1" in out
    plan_path = os.path.join(".agent", "out", "heap-sort-plan.json")
    assert os.path.exists(plan_path) and os.path.exists(os.path.join(".agent", "out", "heap-sort-plan.md"))
    assert not os.path.exists(tmp_path / "filed"), "plan writes its plan and nothing else"

    code, out = run(["apply", "--plan", plan_path], capsys)
    assert code == 0 and "copied: 1" in out
    assert os.path.exists(tmp_path / "filed" / "sorted" / "loans" / "10000123" / "10000123-packet.pdf")
    assert os.path.exists(os.path.join(".agent", "out", "heap-sort-receipt.md"))


def test_a_heap_no_rule_covers_exits_one_rather_than_looking_like_success(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    heap = heap_of(tmp_path, ["notes.txt", "readme.md"])
    code, out = run(["plan", "--heap", heap, "--rules", starter(tmp_path), "--dest", str(tmp_path / "filed")], capsys)
    assert code == 1
    assert "ok: false" in out and "no rule claimed anything" in out


def test_a_refusal_exits_two_and_names_itself(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out = run(["plan", "--heap", str(tmp_path / "nope"), "--rules", starter(tmp_path)], capsys)
    assert code == 2 and "refused: heap_missing" in out


def test_dry_run_checks_the_heap_and_copies_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    heap = heap_of(tmp_path, ["10000123-packet.pdf"])
    run(["plan", "--heap", heap, "--rules", starter(tmp_path), "--dest", str(tmp_path / "filed")], capsys)
    code, out = run(["apply", "--plan", os.path.join(".agent", "out", "heap-sort-plan.json"), "--dry-run"], capsys)
    assert code == 0 and "would_copy: 1" in out
    assert not os.path.exists(tmp_path / "filed")


def test_rules_with_neither_flag_says_which_one_it_wants(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out = run(["rules"], capsys)
    assert code == 2 and "--rules" in out and "--write" in out


def test_rules_does_not_overwrite_an_existing_file_without_force(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "rules.json"
    path.write_text("mine\n", encoding="utf-8")
    code, out = run(["rules", "--write", str(path)], capsys)
    assert code == 2 and "refused: rules_exist" in out
    assert path.read_text(encoding="utf-8") == "mine\n"
    assert run(["rules", "--write", str(path), "--force"], capsys)[0] == 0


def test_the_starter_rule_set_is_valid_and_plans_a_realistic_heap(tmp_path, capsys, monkeypatch):
    """The first thing a person runs must produce something that works on the shape it advertises."""
    monkeypatch.chdir(tmp_path)
    heap = heap_of(tmp_path, ["10000123-packet.pdf", "20260304-summary.xlsx", "contract.docx"])
    code, out = run(["plan", "--heap", heap, "--rules", starter(tmp_path), "--dest", str(tmp_path / "filed")], capsys)
    assert code == 0 and "file: 3" in out


def test_the_plan_records_the_rules_it_was_made_under(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    heap = heap_of(tmp_path, ["10000123-packet.pdf"])
    run(["plan", "--heap", heap, "--rules", starter(tmp_path), "--dest", str(tmp_path / "filed")], capsys)
    with open(os.path.join(".agent", "out", "heap-sort-plan.json"), encoding="utf-8") as f:
        plan = json.load(f)
    assert plan["rules_sha256"] == R.sha256(R.check(R.STARTER))
    assert plan["fingerprint"]["files"] == 1
