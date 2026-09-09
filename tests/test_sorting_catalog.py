"""The per-source-system JSONL: what it is bound to, and what it refuses to assume.

Two things here are deliberate refusals rather than conveniences. `LIS` has no field map, because nobody has described
its records and a guess would file real documents under a field that may not mean what we think it means. And an
`IsCanView` this cannot parse is a refusal, because that flag decides a number somebody reports upward.
"""
from __future__ import annotations
import json

import pytest

from agentdata.sorting import SortError
from agentdata.sorting import catalog as C

ONE = {"LoanNumber": "1234567", "FileName": "a.pdf", "DocSubtypeName": "Note", "BusinessAreaName": "Servicing",
       "RepositoryDocName": "REPO-1", "RepoStorageDatetime": "2026-01-04", "Total Pages": 3,
       "FileSizeInBytes": 10, "FileDesc": "Promissory Note", "IsCanView": True, "IsTiff": False}


def jsonl(tmp_path, records, name="lss.jsonl") -> str:
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


def test_lss_and_imz_share_a_field_map_and_it_is_the_one_retrieval_writes():
    assert C.SOURCES["LSS"] is C.SOURCES["IMZ"]
    assert set(C.LSS_IMZ.values()) == {"FileName", "DocSubtypeName", "BusinessAreaName", "RepositoryDocName",
                                       "RepoStorageDatetime", "Total Pages", "FileSizeInBytes", "FileDesc",
                                       "IsCanView", "IsTiff"}


def test_lis_is_refused_rather_than_guessed(tmp_path):
    with pytest.raises(SortError) as e:
        C.read(jsonl(tmp_path, [ONE]), "LIS")
    assert e.value.code == "unmapped_source_system"
    assert "sample record" in e.value.hint


def test_an_unknown_source_system_lists_the_ones_that_exist(tmp_path):
    with pytest.raises(SortError) as e:
        C.read(jsonl(tmp_path, [ONE]), "MYSTERY")
    assert e.value.code == "unknown_source_system" and "LSS" in e.value.hint


def test_the_fields_the_structure_organises_by_come_through(tmp_path):
    row = C.read(jsonl(tmp_path, [ONE]), "LSS")["rows"][0]
    assert row["doc_subtype"] == "Note" and row["file_desc"] == "Promissory Note"
    assert row["loan_number"] == "1234567" and row["source_system"] == "LSS"
    assert row["can_view"] is True and row["is_tiff"] is False


@pytest.mark.parametrize("spelling,expected", [(True, True), ("Y", True), ("true", True), (1, True),
                                               (False, False), ("N", False), ("0", False), ("", False)])
def test_the_flags_are_read_in_the_spellings_a_source_system_might_use(tmp_path, spelling, expected):
    row = C.read(jsonl(tmp_path, [dict(ONE, IsCanView=spelling)]), "LSS")["rows"][0]
    assert row["can_view"] is expected


def test_a_flag_nobody_can_parse_is_a_refusal_not_a_falsy_default(tmp_path):
    """`IsCanView` decides a count somebody reports upward; quietly reading 'maybe' as false would understate it."""
    with pytest.raises(SortError) as e:
        C.read(jsonl(tmp_path, [dict(ONE, IsCanView="maybe")]), "LSS")
    assert e.value.code == "bad_catalog_value" and "IsCanView" in e.value.msg


def test_the_loan_field_is_found_among_the_names_it_might_have(tmp_path):
    for key in ("LoanNumber", "loan_number", "LoanNbr"):
        record = {k: v for k, v in ONE.items() if k != "LoanNumber"} | {key: "999"}
        assert C.read(jsonl(tmp_path, [record]), "LSS")["loan_field"] == key


def test_no_loan_field_says_what_it_looked_for_and_what_is_there(tmp_path):
    record = {k: v for k, v in ONE.items() if k != "LoanNumber"}
    with pytest.raises(SortError) as e:
        C.read(jsonl(tmp_path, [record]), "LSS")
    assert e.value.code == "loan_field_missing"
    assert "LoanNumber" in e.value.hint and "FileDesc" in e.value.hint
    assert "--loan-field" in e.value.hint


def test_an_explicit_loan_field_wins(tmp_path):
    record = dict(ONE, ServicingLoan="42")
    assert C.read(jsonl(tmp_path, [record]), "LSS", loan_field="ServicingLoan")["rows"][0]["loan_number"] == "42"


def test_an_unreadable_line_is_listed_rather_than_stopping_the_run(tmp_path):
    path = tmp_path / "lss.jsonl"
    path.write_text(json.dumps(ONE) + "\nnot json at all\n" + json.dumps(dict(ONE, FileName="b.pdf")) + "\n",
                    encoding="utf-8")
    result = C.read(str(path), "LSS")
    assert len(result["rows"]) == 2
    assert result["unusable"][0]["line"] == 2 and "not JSON" in result["unusable"][0]["why"]


def test_a_record_with_no_file_name_cannot_be_filed_and_says_so(tmp_path):
    result = C.read(jsonl(tmp_path, [dict(ONE, FileName="")]), "LSS")
    assert result["rows"] == [] and "file name" in result["unusable"][0]["why"]


def test_an_empty_catalogue_is_a_retrieval_answer_not_a_filing_one(tmp_path):
    with pytest.raises(SortError) as e:
        C.read(jsonl(tmp_path, []), "LSS")
    assert e.value.code == "catalog_empty"


def test_the_loan_population_reads_a_bare_list_or_a_csv_first_column(tmp_path):
    path = tmp_path / "loans.csv"
    path.write_text("loan_number\n1234567\n7654321,extra\n\n1234567\n", encoding="utf-8")
    assert C.loans_from(str(path)) == ["1234567", "7654321"]
