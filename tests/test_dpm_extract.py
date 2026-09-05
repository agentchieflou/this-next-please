"""Field extraction over DPM's routed text, with the field list supplied per job.

The design constraint worth testing hardest is the one that is easy to violate later: **no business
field name appears anywhere in `agentdata/dpm/`**. "Borrower name" is right for one job and wrong
for the next, and a built-in list is unmaintainable in a month — so the schema is an input, the way
`ad-uat expect` treats an expected-values document as a claim to test rather than a schema to
assume. There is a test that greps for it.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.dpm import DpmError
from agentdata.dpm import extract as EX

NATIVE = """LOAN APPLICATION

Borrower: Ada Lovelace
Co-borrower:
    Charles Babbage
Loan Amount: 125,000.00
Property Address: 12 Analytical Way, London
Prepared 2026-01-04
"""

AMBIGUOUS = """Page 1
Loan Amount: 125,000.00
...
Revised schedule
Loan Amount: 130,000.00
"""


def _job(job_id="SEL-1:D1:p1", route="native_text", text_path="t.txt", **kw):
    return {"job_id": job_id, "route": route, "selection_id": "SEL-1", "document_id": "D1",
            "sha256": "a" * 64, "page": 1, "text_path": text_path,
            "lineage": {"source_sha256": "a" * 64, "run_id": "RUN-9"}, **kw}


def _manifest(*jobs):
    return {"job_manifest_version": "1", "producer": {"run_id": "RUN-9"}, "jobs": list(jobs)}


def _schema(*fields):
    return EX.FieldSchema([{"name": n, "hint": h, "regex": False, "required": r}
                           for n, h, r in fields])


def _text(mapping):
    return lambda job: mapping.get(job["job_id"], "")


# --------------------------------------------------------------- nothing here knows a business


def test_no_business_field_name_is_built_into_the_module():
    """The whole shape of this slice. A built-in list would be right for one job and wrong for the
    next, and nobody would find out until a value was silently missing.

    Checked against the *code* -- string constants and identifiers -- and not the prose, because the
    module's own docstring names "borrower name" and "loan amount" precisely to say they must not be
    built in. A grep over the whole file would flag the explanation as the offence.
    """
    import ast

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "agentdata", "dpm")
    literals: list[str] = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(root, name), encoding="utf-8").read())
        # Identified structurally: a docstring is the first statement of a module, class or
        # function. Comparing against `ast.get_docstring` does not work -- it returns the cleaned,
        # dedented text, which never equals the node's own value.
        docstring_nodes = set()
        for holder in ast.walk(tree):
            if isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = (holder.body or [None])[0]
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstring_nodes.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    literals.append(node.value.lower())
            elif isinstance(node, ast.Name):
                literals.append(node.id.lower())
            elif isinstance(node, ast.arg):
                literals.append(node.arg.lower())

    code = "\n".join(literals)
    for business in ("borrower", "loan_amount", "loan amount", "policy number", "invoice",
                     "ssn", "account holder", "property address"):
        assert business not in code, f"{business!r} is hard-coded in agentdata/dpm/"


# ------------------------------------------------------------------------------ the schema


def test_a_schema_is_read_and_its_fields_kept_in_order(tmp_path):
    path = str(tmp_path / "fields.json")
    json.dump({"fields": [{"name": "a", "hint": "A:"}, {"name": "b", "hint": "B:", "required": True}]},
              open(path, "w", encoding="utf-8"))
    schema = EX.load_schema(path)
    assert schema.names == ["a", "b"] and schema.required() == ["b"]


@pytest.mark.parametrize("bad,expected", [
    ({}, "no `fields` list"),
    ({"fields": []}, "no `fields` list"),
    ({"fields": [{"hint": "A:"}]}, "no name"),
    ({"fields": [{"name": "a"}]}, "no hint"),
    ({"fields": [{"name": "a", "hint": "A:"}, {"name": "a", "hint": "B:"}]}, "twice"),
    ({"fields": [{"name": "a", "hint": "([", "regex": True}]}, "invalid regex"),
])
def test_a_broken_schema_is_refused_rather_than_quietly_finding_nothing(tmp_path, bad, expected):
    """A schema with a typo produces empty results, which read exactly like "the documents do not
    contain this" — the most expensive kind of wrong answer here."""
    path = str(tmp_path / "fields.json")
    json.dump(bad, open(path, "w", encoding="utf-8"))
    with pytest.raises(DpmError) as e:
        EX.load_schema(path)
    assert expected in str(e.value)


def test_a_missing_schema_file_says_what_the_shape_is(tmp_path):
    with pytest.raises(DpmError) as e:
        EX.load_schema(str(tmp_path / "nope.json"))
    assert "fields" in e.value.hint


# ------------------------------------------------------------------------- the four outcomes


def test_a_field_present_once_is_found_with_its_value():
    got = EX.extract(manifest=_manifest(_job()),
                     schema=_schema(("address", "Property Address:", True)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    row = got["rows"][0]
    assert row["status"] == "found" and row["value"] == "12 Analytical Way, London"
    assert row["field"] == "address"


def test_a_hint_that_is_a_substring_of_another_label_is_ambiguous_not_silently_wrong():
    """Found by this file's own fixture, and worth keeping: `Borrower:` also matches inside
    `Co-borrower:`, so a naive search returns whichever came first and looks confident about it.
    Two different values under one hint is exactly what `ambiguous` is for."""
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("borrower", "Borrower:", True)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    row = got["rows"][0]
    assert row["status"] == "ambiguous"
    assert "Ada Lovelace" in row["detail"] and "Charles Babbage" in row["detail"]


def test_a_value_on_the_next_line_is_still_found():
    """A label at the end of its line is the ordinary layout in a form; treating it as absent would
    report half a document as missing."""
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("co", "Co-borrower:", False)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    assert got["rows"][0]["status"] == "found"
    assert got["rows"][0]["value"] == "Charles Babbage"


def test_a_field_that_is_not_there_is_not_found_and_says_what_it_looked_for():
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("policy", "Policy Number:", False)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    row = got["rows"][0]
    assert row["status"] == "not_found" and row["value"] == ""
    assert "Policy Number:" in row["detail"]


def test_two_different_values_under_one_label_are_ambiguous_not_a_guess():
    """The honest answer, and the one a reviewer can act on. Picking the first would be a silent
    decision about which figure is current."""
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("amount", "Loan Amount:", False)),
                     read_text=_text({"SEL-1:D1:p1": AMBIGUOUS}))
    row = got["rows"][0]
    assert row["status"] == "ambiguous"
    assert "125,000.00" in row["detail"] and "130,000.00" in row["detail"]


def test_the_same_value_twice_is_not_ambiguous():
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "Amount:", False)),
                     read_text=_text({"SEL-1:D1:p1": "Amount: 5\nAmount: 5\n"}))
    assert got["rows"][0]["status"] == "found" and got["rows"][0]["value"] == "5"


def test_a_native_route_with_no_text_is_its_own_status():
    """Different from "not found": the document was supposed to be readable and is not, which is a
    routing problem rather than a missing field."""
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "A:", False)),
                     read_text=_text({}))
    assert got["rows"][0]["status"] == "no_text"


# ------------------------------------------------------------------------------- OCR is not read


def test_an_ocr_document_is_flagged_and_never_extracted_from():
    """A value read from bad OCR looks exactly like a value read from good text. Bucketed the way
    `convert.py` buckets what it cannot route, rather than guessed at."""
    manifest = _manifest(_job(route="ocr", text_path=None))
    got = EX.extract(manifest=manifest, schema=_schema(("borrower", "Borrower:", True)),
                     read_text=lambda job: pytest.fail("it read the OCR text"))

    row = got["rows"][0]
    assert row["status"] == "needs_ocr_review" and row["value"] == ""
    assert "not verified" in row["detail"]
    assert got["counts"]["needs_ocr_review"] == 1


def test_a_mixed_manifest_extracts_the_native_and_flags_the_ocr():
    manifest = _manifest(_job("SEL-1:D1:p1"), _job("SEL-1:D2:p1", route="ocr", text_path=None))
    got = EX.extract(manifest=manifest, schema=_schema(("address", "Property Address:", True)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    statuses = {r["job_id"]: r["status"] for r in got["rows"]}
    assert statuses == {"SEL-1:D1:p1": "found", "SEL-1:D2:p1": "needs_ocr_review"}


# ------------------------------------------------------------------------------- provenance


def test_every_row_carries_dpms_own_lineage_and_not_a_second_one():
    """A parallel provenance mechanism would be a second answer to "where did this come from", and
    the DPM contract exists so there is exactly one."""
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "Property Address:", False)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    row = got["rows"][0]
    assert row["document_id"] == "D1" and row["page"] == 1
    assert row["sha256"] == "a" * 64
    assert row["job_id"] == "SEL-1:D1:p1"
    assert set(EX.RESULT_COLS) <= set(row), "a column the CLI prints is missing from the row"


def test_the_run_root_is_verified_untouched(tmp_path):
    """The invariant every `ad-dpm` command upholds, using the same guard rather than a new one."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "orchestrator.db").write_text("x", encoding="utf-8")

    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "Borrower:", False)),
                     run_root=str(root), read_text=_text({"SEL-1:D1:p1": NATIVE}))
    assert got["rows"]


def test_a_run_root_that_changes_underneath_is_an_error(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "orchestrator.db").write_text("x", encoding="utf-8")

    def meddle(job):
        (root / "sneaky.txt").write_text("something else is writing", encoding="utf-8")
        return NATIVE

    with pytest.raises(DpmError) as e:
        EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "Borrower:", False)),
                   run_root=str(root), read_text=meddle)
    assert "changed while reading" in str(e.value)


# ------------------------------------------------------------------------------ the engine seam


def test_the_engine_is_a_real_interface_another_module_can_add_to():
    """#31 plugs in here with the same schema in and the same rows out, so nothing downstream has
    to know which engine ran. A flag over one code path would not have allowed that."""
    class Fake(EX.Engine):
        name = "fake-for-a-test"

        def find(self, text, field):
            return "found", "from the fake engine", "always"

    EX.register(Fake)
    try:
        got = EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "Borrower:", False)),
                         engine_name="fake-for-a-test", read_text=_text({"SEL-1:D1:p1": NATIVE}))
        assert got["rows"][0]["value"] == "from the fake engine"
        assert got["rows"][0]["engine"] == "fake-for-a-test"
        assert got["engine"] == "fake-for-a-test"
    finally:
        EX.ENGINES.pop("fake-for-a-test", None)


def test_an_unknown_engine_names_the_ones_that_exist():
    with pytest.raises(DpmError) as e:
        EX.extract(manifest=_manifest(_job()), schema=_schema(("a", "A:", False)),
                   engine_name="magic")
    assert "simple" in e.value.hint


def test_the_ocr_rule_belongs_to_the_caller_not_the_engine():
    """An engine never sees an OCR document at all, so a future engine cannot accidentally opt in
    to guessing from unverified text."""
    seen = []

    class Watching(EX.Engine):
        name = "watching"

        def find(self, text, field):
            seen.append(text)
            return "not_found", "", ""

    EX.register(Watching)
    try:
        EX.extract(manifest=_manifest(_job(route="ocr", text_path="t.txt")),
                   schema=_schema(("a", "A:", False)), engine_name="watching",
                   read_text=_text({"SEL-1:D1:p1": NATIVE}))
        assert seen == [], "the engine was handed OCR text"
    finally:
        EX.ENGINES.pop("watching", None)


# -------------------------------------------------------------------------- required fields


def test_a_required_field_no_document_yielded_is_called_out():
    got = EX.extract(manifest=_manifest(_job()),
                     schema=_schema(("address", "Property Address:", True), ("policy", "Policy:", True)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    missing = [m["field"] for m in got["missing_required"]]
    assert missing == ["policy"], "a required field found nowhere is the reviewer's first question"


def test_an_optional_field_found_nowhere_is_not_a_problem():
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("policy", "Policy:", False)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    assert got["missing_required"] == []


# ------------------------------------------------------------------------------ the review file


def test_the_review_file_tells_a_reviewer_what_to_check_by_hand():
    got = EX.extract(manifest=_manifest(_job("SEL-1:D1:p1"), _job("SEL-1:D2:p1", route="ocr")),
                     schema=_schema(("amount", "Loan Amount:", True)),
                     read_text=_text({"SEL-1:D1:p1": AMBIGUOUS}))
    body = EX.review_md(got, "RUN-9")

    assert "# RUN-9: field extraction" in body
    assert "ambiguous" in body and "check these by hand" in body.lower()
    assert "not extracted" in body.lower(), "the OCR bucket has to be visible, not just counted"
    assert "text quality is unverified" in body
    assert "D1" in body and "p1" in body, "an ambiguous value must be citable"
    assert "Provenance" in body


def test_the_review_file_says_when_a_required_field_is_missing_everywhere():
    got = EX.extract(manifest=_manifest(_job()), schema=_schema(("policy", "Policy:", True)),
                     read_text=_text({"SEL-1:D1:p1": NATIVE}))
    body = EX.review_md(got, "RUN-9")
    assert "Required fields no document yielded" in body and "`policy`" in body


# ------------------------------------------------------------------------------- the command


def test_the_command_writes_the_review_and_reports_the_counts(tmp_path, monkeypatch, capsys):
    from agentdata import cli_dpm

    monkeypatch.chdir(tmp_path)
    text = tmp_path / "d1.txt"
    text.write_text(NATIVE, encoding="utf-8")
    manifest = tmp_path / "job-manifest.json"
    json.dump(_manifest(_job(text_path=str(text))), open(manifest, "w", encoding="utf-8"))
    schema = tmp_path / "fields.json"
    json.dump({"fields": [{"name": "address", "hint": "Property Address:", "required": True}]},
              open(schema, "w", encoding="utf-8"))

    assert cli_dpm.main(["extract-fields", "--manifest", str(manifest), "--schema", str(schema)]) == 0
    out = capsys.readouterr().out
    assert "found: 1" in out and "engine: simple" in out
    assert os.path.isfile(os.path.join(".agent", "out", "RUN-9-field-extraction.md"))


def test_strict_fails_on_a_missing_required_field_and_not_on_ambiguity(tmp_path, monkeypatch, capsys):
    """`--strict` is about a job that cannot proceed, not about a value a reviewer must confirm."""
    from agentdata import cli_dpm

    monkeypatch.chdir(tmp_path)
    text = tmp_path / "d1.txt"
    text.write_text(AMBIGUOUS, encoding="utf-8")
    manifest = tmp_path / "m.json"
    json.dump(_manifest(_job(text_path=str(text))), open(manifest, "w", encoding="utf-8"))

    ambiguous_only = tmp_path / "a.json"
    json.dump({"fields": [{"name": "amount", "hint": "Loan Amount:", "required": False}]},
              open(ambiguous_only, "w", encoding="utf-8"))
    assert cli_dpm.main(["extract-fields", "--manifest", str(manifest),
                         "--schema", str(ambiguous_only), "--strict"]) == 0
    capsys.readouterr()

    missing = tmp_path / "b.json"
    json.dump({"fields": [{"name": "policy", "hint": "Policy:", "required": True}]},
              open(missing, "w", encoding="utf-8"))
    assert cli_dpm.main(["extract-fields", "--manifest", str(manifest),
                         "--schema", str(missing), "--strict"]) == 1
    assert "missing_required: policy" in capsys.readouterr().out


def test_a_file_that_is_not_a_job_manifest_says_so(tmp_path):
    from agentdata import cli_dpm

    path = tmp_path / "not-a-manifest.json"
    json.dump({"hello": "world"}, open(path, "w", encoding="utf-8"))
    schema = tmp_path / "f.json"
    json.dump({"fields": [{"name": "a", "hint": "A:"}]}, open(schema, "w", encoding="utf-8"))

    assert cli_dpm.main(["extract-fields", "--manifest", str(path), "--schema", str(schema)]) == 2


# --------------------------------------------------------------------------------- the skill


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_skill_exists_and_keeps_the_disciplines_every_dpm_skill_has():
    body = open(os.path.join(ROOT, "skills", "dpm-field-extraction", "SKILL.md"),
                encoding="utf-8").read()
    assert "ad-dpm extract-fields" in body
    assert "needs_ocr_review" in body, "the OCR bucket is the thing a reviewer must not miss"
    assert "friction-log" in body and "state-update" in body
    assert "never" in body.lower() and "run root" in body.lower()
    assert len(body.splitlines()) < 120

    router = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    assert "`dpm-field-extraction`" in router
