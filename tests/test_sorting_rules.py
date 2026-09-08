"""The rule set is an *input*. These tests are about what it refuses to accept, and when it says so.

Every refusal here happens at load time rather than at apply time, which is the whole point: a typo in `{borrwer}`
should be a sentence naming the rule, not a folder called `{borrwer}` full of documents.
"""
from __future__ import annotations
import pytest

from agentdata.sorting import SortError
from agentdata.sorting import rules as R


def rules(listed, **over):
    return {"version": 1, "rules": listed, **over}


def refusal(value) -> str:
    with pytest.raises(SortError) as e:
        R.check(value)
    return e.value.code


def test_the_starter_passes_its_own_check():
    checked = R.check(R.STARTER)
    assert [r["name"] for r in checked["rules"]] == [r["name"] for r in R.STARTER["rules"]]
    assert checked["into"] == "sorted"


def test_an_unknown_placeholder_is_caught_when_the_file_is_read():
    code = refusal(rules([{"name": "r", "match": {"glob": "*.pdf"}, "into": "x/{borrwer}"}]))
    assert code == "unknown_placeholder"


def test_a_named_group_supplies_its_own_placeholder():
    checked = R.check(rules([{"name": "r", "match": {"regex": r"(?P<borrower>\w+)"}, "into": "x/{borrower}"}]))
    assert checked["rules"][0]["into"] == "x/{borrower}"


def test_a_placeholder_in_rename_is_checked_too():
    assert refusal(rules([{"name": "r", "match": {"glob": "*.pdf"}, "into": "x", "rename": "{nope}.pdf"}])) \
        == "unknown_placeholder"


def test_a_rule_that_matches_nothing_is_refused():
    assert refusal(rules([{"name": "r", "match": {}, "into": "x"}])) == "bad_rules"


def test_a_rule_with_no_destination_is_refused():
    assert refusal(rules([{"name": "r", "match": {"glob": "*.pdf"}}])) == "bad_rules"


def test_a_regex_that_does_not_compile_says_so_against_the_rule_that_owns_it():
    with pytest.raises(SortError) as e:
        R.check(rules([{"name": "loans", "match": {"regex": "(unclosed"}, "into": "x"}]))
    assert e.value.code == "bad_rules" and "loans" in e.value.msg


def test_an_empty_rule_set_is_refused_rather_than_planning_a_heap_of_unmatched():
    assert refusal(rules([])) == "bad_rules"


def test_a_future_version_is_refused_rather_than_read_optimistically():
    assert refusal(rules([{"name": "r", "match": {"glob": "*"}, "into": "x"}], version=99)) \
        == "unsupported_rules_version"


def test_an_absolute_top_level_into_is_refused():
    assert refusal(rules([{"name": "r", "match": {"glob": "*"}, "into": "x"}], into="/etc")) == "absolute_into"


def test_matching_is_case_insensitive_on_the_glob_because_windows_is():
    rule = R.check(rules([{"name": "r", "match": {"glob": "*.PDF"}, "into": "x"}]))["rules"][0]
    assert R.matches(rule, "packet.pdf") == {}
    assert R.matches(rule, "packet.txt") is None


def test_a_rule_with_both_a_glob_and_a_regex_needs_both():
    rule = R.check(rules([{"name": "r", "match": {"glob": "*.pdf", "regex": r"^\d{8}"}, "into": "x"}]))["rules"][0]
    assert R.matches(rule, "10000123-a.pdf") == {}
    assert R.matches(rule, "10000123-a.txt") is None
    assert R.matches(rule, "letter.pdf") is None


def test_the_digest_ignores_key_order_so_a_reformatted_file_is_the_same_rules():
    a = R.check(rules([{"name": "r", "into": "x", "match": {"glob": "*.pdf"}}]))
    b = R.check(rules([{"match": {"glob": "*.pdf"}, "name": "r", "into": "x"}]))
    assert R.sha256(a) == R.sha256(b)


def test_a_missing_rules_file_names_the_command_that_starts_one(tmp_path):
    with pytest.raises(SortError) as e:
        R.load(str(tmp_path / "nope.json"))
    assert e.value.code == "rules_missing" and "ad-sort rules --write" in e.value.hint
