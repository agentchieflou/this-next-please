r"""RDSD-22488's structure: canonical evidence per loan, disposable views beside it, and the counts somebody reports.

The model the ticket states is what these tests hold to: downloaded documents are **canonical evidence**, derived views
are **disposable navigation aids**. So the two properties worth failing a build over are that a view is a second name
for the evidence rather than a second copy of it (where the volume allows), and that deleting every view cannot touch a
document.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.sorting import SortError
from agentdata.sorting import catalog as C
from agentdata.sorting import dpm_layout as D
from agentdata.sorting import dpm_plan as DP
from agentdata.sorting import links as L

RECORDS = [
    {"LoanNumber": "1234567", "FileName": "a1.pdf", "DocSubtypeName": "Note", "BusinessAreaName": "Servicing",
     "RepositoryDocName": "REPO-0001", "RepoStorageDatetime": "2026-01-04T10:00:00", "Total Pages": 3,
     "FileSizeInBytes": 1024, "FileDesc": "Promissory Note", "IsCanView": True, "IsTiff": False},
    {"LoanNumber": "1234567", "FileName": "a2.tif", "DocSubtypeName": "Mortgage", "BusinessAreaName": "Servicing",
     "RepositoryDocName": "REPO-0002", "RepoStorageDatetime": "2026-01-04T10:05:00", "Total Pages": 12,
     "FileSizeInBytes": 9999, "FileDesc": "Security Instrument", "IsCanView": True, "IsTiff": True},
    {"LoanNumber": "7654321", "FileName": "b1.pdf", "DocSubtypeName": "Note", "BusinessAreaName": "Default",
     "RepositoryDocName": "REPO-0003", "RepoStorageDatetime": "2026-02-01T09:00:00", "Total Pages": 2,
     "FileSizeInBytes": 2048, "FileDesc": "Promissory Note", "IsCanView": False, "IsTiff": False},
]


def fixture(tmp_path, *, records=None, on_disk=("a1.pdf", "a2.tif", "b1.pdf"), system="LSS"):
    downloads = tmp_path / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    for name in on_disk:
        (downloads / name).write_text(f"bytes of {name}\n", encoding="utf-8")
    path = tmp_path / f"{system.lower()}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in (RECORDS if records is None else records)), encoding="utf-8")
    return str(downloads), C.read(str(path), system)


def planned(tmp_path, **over):
    downloads, cat = fixture(tmp_path, **over)
    return DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat])


def verdicts(plan):
    return {r["source"]: r["verdict"] for r in plan["rows"]}


# ------------------------------------------------------------------------------ the structure itself


def test_the_tree_is_the_one_the_ticket_draws(tmp_path):
    plan = planned(tmp_path)
    DP.apply(plan)
    root = tmp_path / "M" / "RDSD-22488"

    assert (root / "1234567" / "raw_docs" / "a1.pdf").is_file()
    assert (root / "1234567" / "metadata" / "document_manifest.csv").is_file()
    assert (root / "views" / "doc_type" / "Note" / "1234567" / "REPO-0001.pdf").is_file()
    assert (root / "views" / "file_description" / "Promissory Note" / "1234567" / "REPO-0001.pdf").is_file()


def test_a_view_is_a_second_name_for_the_evidence_not_a_second_copy(tmp_path):
    """The whole reason the ticket prefers hardlinks: a view costs no storage."""
    if not L.probe(str(tmp_path))["hardlinks"]:
        pytest.skip("this volume has no hardlinks; the copy fallback is covered by its own test")
    plan = planned(tmp_path)
    DP.apply(plan)
    root = tmp_path / "M" / "RDSD-22488"
    evidence = root / "1234567" / "raw_docs" / "a1.pdf"
    view = root / "views" / "doc_type" / "Note" / "1234567" / "REPO-0001.pdf"
    assert evidence.stat().st_ino == view.stat().st_ino


def test_deleting_every_view_cannot_touch_a_document(tmp_path):
    """"Disposable navigation aids" has to be literally true, or nobody will dare delete one."""
    import shutil

    plan = planned(tmp_path)
    DP.apply(plan)
    root = tmp_path / "M" / "RDSD-22488"
    before = {p.name: p.read_bytes() for p in (root / "1234567" / "raw_docs").iterdir()}

    shutil.rmtree(root / "views")

    assert {p.name: p.read_bytes() for p in (root / "1234567" / "raw_docs").iterdir()} == before


def test_a_view_leaf_keeps_the_extension_so_it_opens_on_a_double_click(tmp_path):
    """`REPO-0001` with no suffix is not browsable, and browsing is what a view is for."""
    assert D.reference(RECORDS[0] | {"file_name": "a1.pdf", "repo_doc_name": "REPO-0001"}).endswith(".pdf")


def test_the_view_axes_are_the_two_the_ticket_names(tmp_path):
    assert [folder for folder, _field in D.VIEW_AXES] == ["doc_type", "file_description"]


# ------------------------------------------------------------------------------------- traceability


def test_the_manifest_traces_each_filed_document_back_to_the_download(tmp_path):
    """Requirement 2 of the ticket, and the reason the manifest lives with the evidence rather than in `.agent/out`."""
    downloads, cat = fixture(tmp_path)
    plan = DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat])
    DP.apply(plan)

    rows = D.read_manifest(str(tmp_path / "M" / "RDSD-22488" / "1234567" / "metadata" / "document_manifest.csv"))
    a1 = next(r for r in rows if r["raw_doc"] == "a1.pdf")
    assert a1["source_path"].endswith("downloads/a1.pdf")
    assert a1["sha256"] and len(a1["sha256"]) == 64
    assert a1["source_system"] == "LSS"
    assert a1["doc_subtype"] == "Note" and a1["file_desc"] == "Promissory Note"
    assert a1["link_mode"] in (L.HARDLINK, L.COPY)


def test_the_manifest_records_which_mode_actually_placed_the_bytes(tmp_path):
    """A manifest that says `copy` where somebody budgeted `hardlink` is a forecast being wrong; one that does not say
    is an argument nobody can settle."""
    plan = planned(tmp_path)
    result = DP.apply(plan)
    rows = D.read_manifest(str(tmp_path / "M" / "RDSD-22488" / "1234567" / "metadata" / "document_manifest.csv"))
    assert {r["link_mode"] for r in rows} == {result["link_mode"]}


# --------------------------------------------------------------------------- reuse, gaps and strays


def test_a_second_run_files_nothing_again(tmp_path):
    """Requirement 4: reuse what was retrieved rather than repeating it."""
    downloads, cat = fixture(tmp_path)
    DP.apply(DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat]))

    again = DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat])

    assert again["counts"]["file"] == 0
    assert again["counts"]["already_filed"] == 3
    assert DP.apply(again)["filed"] == 0


def test_a_second_apply_does_not_duplicate_manifest_rows(tmp_path):
    downloads, cat = fixture(tmp_path)
    for _ in range(2):
        DP.apply(DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat]))
    rows = D.read_manifest(str(tmp_path / "M" / "RDSD-22488" / "1234567" / "metadata" / "document_manifest.csv"))
    assert [r["raw_doc"] for r in rows] == ["a1.pdf", "a2.tif"]


def test_a_catalogued_document_that_never_landed_is_a_retrieval_gap_not_a_filing_one(tmp_path):
    plan = planned(tmp_path, on_disk=("a1.pdf", "a2.tif"))
    assert verdicts(plan)["b1.pdf"] == "missing_from_disk"
    assert "not in the folder" in next(r["why"] for r in plan["rows"] if r["source"] == "b1.pdf")


def test_a_file_no_catalogue_names_is_reported_rather_than_dropped(tmp_path):
    plan = planned(tmp_path, on_disk=("a1.pdf", "a2.tif", "b1.pdf", "mystery.pdf"))
    assert verdicts(plan)["mystery.pdf"] == "unclassified"


def test_two_catalogue_rows_wanting_one_raw_doc_path_collide(tmp_path):
    twice = RECORDS + [dict(RECORDS[0], RepositoryDocName="REPO-9999")]
    plan = planned(tmp_path, records=twice)
    assert plan["counts"]["collision"] == 1


# ---------------------------------------------------------------------------------- administration


def test_the_counts_somebody_has_to_report(tmp_path):
    plan = planned(tmp_path)
    admin = plan["administration"]
    assert admin["loans"] == 2 and admin["documents"] == 3
    assert admin["not_viewable"] == 1                       # b1.pdf has IsCanView false
    assert admin["tiff_to_convert"] == 1                    # a2.tif
    assert admin["per_loan"]["7654321"]["not_viewable"] == 1


def test_loans_with_no_documents_needs_the_population_and_says_so_without_it(tmp_path):
    """A catalogue only records loans that produced something, so a loan that returned nothing is absent, not zero."""
    plan = planned(tmp_path)
    assert plan["administration"]["population_known"] is False
    assert "Not answerable from the catalogue alone" in D.admin_md("RDSD-22488", plan["administration"], [])


def test_with_the_population_the_empty_loans_are_named(tmp_path):
    downloads, cat = fixture(tmp_path)
    plan = DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat],
                   expected_loans=["1234567", "7654321", "9999999"])
    assert plan["administration"]["loans_with_no_documents"] == ["9999999"]


def test_tiff_documents_are_filed_and_queued_but_never_called_converted(tmp_path):
    plan = planned(tmp_path)
    DP.apply(plan)
    assert (tmp_path / "M" / "RDSD-22488" / "1234567" / "raw_docs" / "a2.tif").is_file()
    md = D.admin_md("RDSD-22488", plan["administration"], [r["record"] for r in plan["rows"] if r["record"]])
    assert "TIFF conversion queue (1)" in md
    assert "Nothing here has been converted" in md


# ---------------------------------------------------------------------------------------- refusals


def test_the_structure_may_not_live_inside_the_download_folder(tmp_path):
    downloads, cat = fixture(tmp_path)
    with pytest.raises(SortError) as e:
        DP.make(heap=downloads, root=os.path.join(downloads, "organised"), ticket="RDSD-22488", catalogs=[cat])
    assert e.value.code == "destination_inside_heap"


def test_a_plan_whose_downloads_changed_is_refused(tmp_path):
    downloads, cat = fixture(tmp_path)
    plan = DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="RDSD-22488", catalogs=[cat])
    open(os.path.join(downloads, "arrived-later.pdf"), "w", encoding="utf-8").write("new\n")
    with pytest.raises(SortError) as e:
        DP.apply(plan)
    assert e.value.code == "heap_changed"


def test_no_ticket_is_a_refusal_because_it_is_the_first_level(tmp_path):
    downloads, cat = fixture(tmp_path)
    with pytest.raises(SortError) as e:
        DP.make(heap=downloads, root=str(tmp_path / "M"), ticket="", catalogs=[cat])
    assert e.value.code == "no_ticket"
