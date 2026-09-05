"""Azure AI Content Understanding: the connector, the `ad-dpm` engine, `ad-foundry`, the setup step.

No Azure, no credentials, and no `azure-ai-contentunderstanding` installed. Two things are worth
testing here and neither needs the service:

**The argument shape.** `string_encoding` is a required keyword on both analyze calls, and
`content_type` is a required keyword on `begin_analyze_binary` — the operation does
`kwargs.pop("content_type")` with no default, so omitting it raises `KeyError` at the first real
request rather than sending a sensible header. Both were found by reading the published wheel, and
a fake SDK that records its kwargs is what keeps them from being dropped in a later refactor.

**The normalisation.** `fields_from_result` turns the service's nested shape into the flat rows
`ad-dpm extract-fields` already emits. That is where the decisions are, and a recorded fixture
exercises every one of them.

The fixtures under `tests/fixtures/content_understanding/` are the service's own JSON shape, which
is also what the SDK deserialises — so a test that passes against the fixture is testing the same
mapping a live call would go through.
"""
from __future__ import annotations

import json
import os

import pytest

from agentdata import cli_dpm, cli_foundry
from agentdata.connectors import content_understanding as CU
from agentdata.dpm import DpmError
from agentdata.dpm import engine_cu as ECU
from agentdata.dpm import extract as EX

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                        "content_understanding")


def fixture(name: str):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


RESULT = fixture("analysis-result.json")
ANALYZER = fixture("analyzer.json")
ANALYZERS = fixture("analyzers-list.json")


class FakePoller:
    def __init__(self, result):
        self._result = result

    def result(self, timeout=None):
        return self._result


class FakeSDK:
    """Records exactly what the connector asked the SDK for. That is the contract under test."""

    def __init__(self, result=None, analyzers=None, analyzer=None, boom: Exception | None = None):
        self.result = RESULT if result is None else result
        self.analyzers = ANALYZERS if analyzers is None else analyzers
        self.analyzer = ANALYZER if analyzer is None else analyzer
        self.boom = boom
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name, args, kwargs):
        self.calls.append((name, args, kwargs))
        if self.boom:
            raise self.boom

    def begin_analyze_binary(self, *args, **kwargs):
        self._record("begin_analyze_binary", args, kwargs)
        return FakePoller(self.result)

    def begin_analyze(self, *args, **kwargs):
        self._record("begin_analyze", args, kwargs)
        return FakePoller(self.result)

    def list_analyzers(self):
        self._record("list_analyzers", (), {})
        return self.analyzers

    def get_analyzer(self, analyzer_id):
        self._record("get_analyzer", (analyzer_id,), {})
        return self.analyzer


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch, tmp_path):
    """A developer's own laptop config must not decide what these tests see."""
    monkeypatch.setattr(CU.C, "load", lambda *a, **k: {})
    monkeypatch.setattr(CU.C, "project_facts", lambda *a, **k: {})
    for var in ("CONTENT_UNDERSTANDING_ENDPOINT", "CONTENT_UNDERSTANDING_ANALYZER",
                "CONTENT_UNDERSTANDING_KEY"):
        monkeypatch.delenv(var, raising=False)


# ------------------------------------------------------------------- the shape of the request


def test_a_local_file_goes_as_binary_with_both_required_keywords(tmp_path):
    """`string_encoding` and `content_type` are required keywords with no defaults. Dropping either
    is invisible until a live call fails, which is why it is pinned here."""
    doc = tmp_path / "application.pdf"
    doc.write_bytes(b"%PDF-1.7 not really a pdf")
    sdk = FakeSDK()

    CU.analyze(analyzer="loan-application-v2", path=str(doc), sdk=sdk)

    name, args, kwargs = sdk.calls[0]
    assert name == "begin_analyze_binary"
    assert args == ("loan-application-v2",)
    assert kwargs["binary_input"] == b"%PDF-1.7 not really a pdf"
    assert kwargs["string_encoding"] == "codePoint"
    assert kwargs["content_type"] == "application/pdf"      # from the filename, not asserted blind


def test_an_unknown_extension_falls_back_to_octet_stream_rather_than_guessing(tmp_path):
    doc = tmp_path / "scan.weird"
    doc.write_bytes(b"\x00\x01")
    sdk = FakeSDK()
    CU.analyze(analyzer="a", path=str(doc), sdk=sdk)
    assert sdk.calls[0][2]["content_type"] == CU.OCTET_STREAM


def test_bytes_go_as_the_mime_type_the_caller_named():
    """The DPM engine sends text a run already extracted; it says so rather than letting the
    service sniff bytes that no longer look like the original document."""
    sdk = FakeSDK()
    CU.analyze(analyzer="a", data=b"Borrower: Ada", mime_type=CU.TEXT_PLAIN, sdk=sdk)
    kwargs = sdk.calls[0][2]
    assert kwargs["binary_input"] == b"Borrower: Ada"
    assert kwargs["content_type"] == "text/plain"


def test_a_url_goes_through_begin_analyze_and_never_reads_the_disk(monkeypatch):
    """A URL the service fetches itself is a different call with a different body. The SDK model is
    imported lazily, so this test stands in for it rather than installing the package."""
    seen = {}

    class AnalysisInput:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(__import__("sys").modules, "azure",
                        type(__import__("sys"))("azure"))
    models = type(__import__("sys"))("azure.ai.contentunderstanding.models")
    models.AnalysisInput = AnalysisInput
    monkeypatch.setitem(__import__("sys").modules,
                        "azure.ai.contentunderstanding.models", models)
    monkeypatch.setitem(__import__("sys").modules, "azure.ai",
                        type(__import__("sys"))("azure.ai"))
    monkeypatch.setitem(__import__("sys").modules, "azure.ai.contentunderstanding",
                        type(__import__("sys"))("azure.ai.contentunderstanding"))

    sdk = FakeSDK()
    CU.analyze(analyzer="a", url="https://example.invalid/doc.pdf", sdk=sdk)
    name, args, kwargs = sdk.calls[0]
    assert name == "begin_analyze" and seen == {"url": "https://example.invalid/doc.pdf"}
    assert kwargs["string_encoding"] == "codePoint"


@pytest.mark.parametrize("kw", [{}, {"path": "a.pdf", "url": "https://x/y"},
                                {"path": "a.pdf", "data": b"x"}])
def test_exactly_one_input_or_it_refuses(kw):
    with pytest.raises(CU.ContentUnderstandingError) as e:
        CU.analyze(analyzer="a", sdk=FakeSDK(), **kw)
    assert "exactly one" in e.value.msg


def test_a_service_failure_carries_the_services_own_words_and_a_next_step():
    sdk = FakeSDK(boom=RuntimeError("(NotFound) Analyzer 'typo-v1' was not found"))
    with pytest.raises(CU.ContentUnderstandingError) as e:
        CU.analyze(analyzer="typo-v1", data=b"x", sdk=sdk)
    assert "was not found" in e.value.msg
    assert "ad-foundry analyzers get" in e.value.hint


# ----------------------------------------------------------------------- the normalisation


def test_every_field_type_yields_its_value():
    rows = {r["field"]: r for r in CU.fields_from_result(RESULT)}
    assert rows["BorrowerName"]["value"] == "Ada Lovelace"
    assert rows["LoanAmount"]["value"] == 125000.0
    assert rows["ApplicationDate"]["value"] == "2026-01-04"


def test_a_field_type_this_build_has_never_seen_still_yields_its_value():
    """Read by the `value` prefix rather than an exhaustive list of known types: a field type Azure
    adds later reads as its value instead of silently reading as empty, which would be indexed as
    "the document does not contain this"."""
    assert CU.field_value({"type": "geolocation", "valueGeolocation": {"lat": 51.5}}) == {"lat": 51.5}


def test_spans_and_provenance_travel_with_the_row():
    row = next(r for r in CU.fields_from_result(RESULT) if r["field"] == "LoanAmount")
    assert (row["offset"], row["length"]) == (60, 10)
    assert row["content_path"] == "page-1" and row["mime_type"] == "application/pdf"
    assert row["content_index"] == 0


def test_a_field_with_no_span_is_a_row_with_no_offset_not_a_dropped_row():
    row = next(r for r in CU.fields_from_result(RESULT) if r["field"] == "CoBorrowerName")
    assert row["offset"] is None and row["value"] == ""


def test_rows_come_out_in_a_stable_order():
    """Two runs over the same document must diff cleanly; dict order from the service does not."""
    assert [r["field"] for r in CU.fields_from_result(RESULT)] == sorted(
        RESULT["contents"][0]["fields"])


def test_result_meta_surfaces_a_warning_rather_than_leaving_it_in_the_raw_json():
    warned = json.loads(json.dumps(RESULT))
    warned["warnings"] = [{"code": "Truncated", "message": "only the first 50 pages were analyzed"}]
    meta = CU.result_meta(warned)
    assert meta["warnings"] == 1 and "first 50 pages" in meta["warning"]
    assert meta["analyzer"] == "loan-application-v2" and meta["contents"] == 1


def test_a_warning_that_is_an_object_rather_than_a_dict_still_reads():
    """`AnalysisResult.warnings` is typed `list[ODataV4Format]` -- an object, not a mapping. A
    warning is rare and diagnostic, and must never crash a run that otherwise succeeded."""
    class ODataV4Format:
        code, message = "Truncated", "only the first 50 pages were analyzed"

    meta = CU.result_meta({"contents": [], "warnings": [ODataV4Format()]})
    assert meta["warning"] == "only the first 50 pages were analyzed"
    assert CU.result_meta({"contents": [], "warnings": [object()]})["warning"] == ""


def test_as_dict_takes_the_sdks_model_or_a_plain_mapping():
    class Model:
        def as_dict(self):
            return {"analyzerId": "x"}

    assert CU.as_dict(Model()) == {"analyzerId": "x"}
    assert CU.as_dict({"analyzerId": "y"})["analyzerId"] == "y"


# -------------------------------------------------------------------------- settings and auth


def test_settings_reads_rather_than_refuses(monkeypatch):
    """A caller that only wanted the auth mode must not fail over a missing endpoint."""
    assert CU.settings() == {"endpoint": "", "analyzer": "", "auth": "entra"}
    monkeypatch.setenv("CONTENT_UNDERSTANDING_ENDPOINT", "https://r.services.ai.azure.com/")
    assert CU.settings()["endpoint"] == "https://r.services.ai.azure.com"   # the trailing / goes


def test_the_endpoint_refusal_names_the_two_ways_to_fix_it():
    with pytest.raises(CU.ContentUnderstandingError) as e:
        CU.client()
    assert "endpoint" in e.value.msg and "ad-setup" in e.value.hint


def test_key_auth_with_nothing_in_the_keyring_refuses_before_reaching_the_sdk(monkeypatch):
    monkeypatch.setattr(CU.C, "load", lambda *a, **k: {"content_understanding": {"auth": "key"}})
    monkeypatch.setattr(CU, "_key", lambda cfg=None: "")
    with pytest.raises(CU.ContentUnderstandingError) as e:
        CU.credential()
    assert "keyring" in e.value.hint and "CONTENT_UNDERSTANDING_KEY" in e.value.hint


def test_the_key_is_read_from_the_keyring_and_never_from_config(monkeypatch):
    """`config.assert_no_secrets` refuses to store one; this is that rule from the other side."""
    from agentdata.connectors import secrets

    monkeypatch.setattr(secrets, "get_password",
                        lambda source, env, user: "from-keyring"
                        if (source, env, user) == (CU.SECRET_SOURCE, CU.SECRET_ENV, CU.SECRET_USER)
                        else "")
    assert CU._key() == "from-keyring"
    monkeypatch.setenv("CONTENT_UNDERSTANDING_KEY", "one-session")
    assert CU._key() == "one-session"              # the documented escape hatch wins


def test_a_missing_sdk_says_which_extra_installs_it():
    err = CU._not_installed()
    assert CU.SDK_DIST in err.msg and f'agentdata[{CU.EXTRA}]' in err.hint


# ------------------------------------------------------------------------------ the engine


def _engine(sdk, **options):
    engine = ECU.ContentUnderstandingEngine(analyzer="loan-application-v2", **options)
    engine._cu = lambda: _StubCU(sdk)
    return engine


class _StubCU:
    """The connector with its SDK pinned: everything else — normalisation, errors — is the real thing."""

    ContentUnderstandingError = CU.ContentUnderstandingError
    TEXT_PLAIN = CU.TEXT_PLAIN
    fields_from_result = staticmethod(CU.fields_from_result)
    settings = staticmethod(CU.settings)

    def __init__(self, sdk):
        self._sdk = sdk

    def analyze(self, **kw):
        return CU.analyze(sdk=self._sdk, **kw)


SCHEMA = EX.FieldSchema([
    {"name": "borrower_name", "hint": "Borrower:", "regex": False, "required": True},
    {"name": "loan_amount", "hint": "Loan Amount:", "regex": False},
    {"name": "application_date", "hint": "Prepared", "regex": False},
    {"name": "underwriter", "hint": "Underwriter:", "regex": False},
])


def test_one_document_costs_one_request_however_many_fields_the_schema_has():
    sdk = FakeSDK()
    engine = _engine(sdk)
    for field in SCHEMA.fields:
        engine.find("Borrower: Ada Lovelace", field)
    assert len(sdk.calls) == 1, "the analysis is cached on the text, not repeated per field"


def test_field_names_match_across_casing_and_separators():
    """The job schema is written by whoever runs the job and the analyzer schema by whoever built
    the analyzer. `loan_amount` and `LoanAmount` are not a real disagreement."""
    status, value, _ = _engine(FakeSDK()).find("x", {"name": "loan_amount", "hint": "?"})
    assert (status, value) == ("found", "125000.0")


def test_a_low_confidence_value_is_ambiguous_so_a_reviewer_confirms_it():
    status, value, detail = _engine(FakeSDK()).find("x", {"name": "ApplicationDate", "hint": "?"})
    assert status == "ambiguous" and value == "2026-01-04"
    assert "0.41" in detail and "0.70" in detail


def test_the_floor_is_configurable_because_what_counts_as_low_depends_on_the_analyzer():
    status, _, _ = _engine(FakeSDK(), min_confidence=0.3).find(
        "x", {"name": "ApplicationDate", "hint": "?"})
    assert status == "found"


def test_a_field_the_analyzer_returned_empty_is_not_found_not_a_blank_found_row():
    status, value, detail = _engine(FakeSDK()).find("x", {"name": "CoBorrowerName", "hint": "?"})
    assert (status, value) == ("not_found", "")
    assert "no value" in detail


def test_a_schema_mismatch_names_the_fields_the_analyzer_actually_returned():
    """Otherwise every row reads `not_found` and the reviewer concludes the documents lack the
    field — the exact wrong conclusion `load_schema` refuses to allow for a typo."""
    status, _, detail = _engine(FakeSDK()).find("x", {"name": "underwriter", "hint": "?"})
    assert status == "not_found"
    assert "no field matching 'underwriter'" in detail
    assert "BorrowerName" in detail and "LoanAmount" in detail


def test_an_analyzer_that_returned_nothing_says_it_may_be_the_wrong_analyzer():
    empty = {"analyzerId": "content-only", "contents": [{"kind": "document", "fields": {}}]}
    _, _, detail = _engine(FakeSDK(result=empty)).find("x", {"name": "anything", "hint": "?"})
    assert "no fields at all" in detail and "may not be the analyzer" in detail


def test_empty_text_is_no_text_and_never_reaches_the_service():
    sdk = FakeSDK()
    status, _, _ = _engine(sdk).find("   \n ", {"name": "borrower_name", "hint": "?"})
    assert status == "no_text" and sdk.calls == []


def test_a_service_failure_stops_the_run_rather_than_reading_as_not_found():
    """A service that could not be reached has said nothing about the document. A `not_found` row
    would be a claim about the document that nobody made."""
    sdk = FakeSDK(boom=RuntimeError("(Unauthorized) the credential has no access"))
    with pytest.raises(DpmError) as e:
        _engine(sdk).find("Borrower: Ada", {"name": "borrower_name", "hint": "?"})
    assert e.value.code == "content_understanding_failed"
    assert "no access" in e.value.msg


def test_no_analyzer_configured_refuses_with_the_two_ways_to_supply_one():
    engine = ECU.ContentUnderstandingEngine()
    engine._cu = lambda: _StubCU(FakeSDK())
    with pytest.raises(DpmError) as e:
        engine.find("Borrower: Ada", {"name": "borrower_name", "hint": "?"})
    assert e.value.code == "no_analyzer"
    assert "--analyzer" in e.value.hint and "ad-foundry analyzers list" in e.value.hint


# ------------------------------------------------------------------- the seam it plugs into


def test_the_engine_is_registered_without_anything_importing_its_module():
    """`--engine azure-content-understanding` has to work from any entry point, and `extract.py`
    must not import the connector eagerly."""
    assert "azure-content-understanding" in EX.names()
    assert isinstance(EX.engine_for("azure-content-understanding"), ECU.ContentUnderstandingEngine)


def test_a_misspelled_engine_option_refuses_instead_of_being_ignored():
    """Silently ignoring it is how a run ends up using a default nobody chose."""
    with pytest.raises(DpmError) as e:
        EX.engine_for("azure-content-understanding", {"analzyer": "loan-application-v2"})
    assert e.value.code == "unknown_engine_option" and "analzyer" in e.value.msg
    with pytest.raises(DpmError) as e:
        EX.engine_for("simple", {"analyzer": "x"})
    assert "no options" in e.value.hint


def test_a_non_numeric_confidence_floor_refuses():
    with pytest.raises(DpmError) as e:
        EX.engine_for("azure-content-understanding", {"min_confidence": "high"})
    assert e.value.code == "bad_engine_option"


def test_ocr_routed_jobs_never_reach_this_engine(monkeypatch, tmp_path):
    """The bucket is decided in `extract()`, before an engine is asked anything. A remote engine
    that saw them would bill for text whose quality nobody has verified."""
    sdk = FakeSDK()
    engine = _engine(sdk)
    monkeypatch.setattr(EX, "engine_for", lambda name, options=None: engine)
    manifest = {"job_manifest_version": "1", "producer": {"run_id": "R"}, "jobs": [
        {"job_id": "J1", "route": "ocr", "document_id": "D1", "page": 1, "sha256": "a" * 64,
         "text_path": str(tmp_path / "t.txt")}]}
    result = EX.extract(manifest=manifest, schema=SCHEMA,
                        engine_name="azure-content-understanding")
    assert result["counts"]["needs_ocr_review"] == len(SCHEMA.fields)
    assert sdk.calls == []


def test_the_rows_are_the_same_shape_the_simple_engine_produces(monkeypatch, tmp_path):
    """The whole point of the seam: nothing downstream knows which engine ran."""
    text = tmp_path / "t.txt"
    text.write_text("Borrower: Ada Lovelace\nLoan Amount: 125,000.00\n", encoding="utf-8")
    manifest = {"job_manifest_version": "1", "producer": {"run_id": "R"}, "jobs": [
        {"job_id": "J1", "route": "native_text", "document_id": "D1", "page": 1,
         "sha256": "a" * 64, "text_path": str(text)}]}

    simple = EX.extract(manifest=manifest, schema=SCHEMA, engine_name="simple")
    monkeypatch.setattr(EX, "engine_for", lambda name, options=None: _engine(FakeSDK()))
    azure = EX.extract(manifest=manifest, schema=SCHEMA,
                       engine_name="azure-content-understanding")

    assert [sorted(r) for r in simple["rows"]] == [sorted(r) for r in azure["rows"]]
    assert set(r["status"] for r in azure["rows"]) <= set(EX.STATUSES)
    assert EX.review_md(azure, "R").startswith("# R: field extraction")


# ------------------------------------------------------------------------------ ad-foundry


def _fake_client(sdk, monkeypatch):
    monkeypatch.setattr(cli_foundry.CU, "client", lambda *a, **k: sdk)


def test_ad_foundry_analyze_prints_a_row_per_field(monkeypatch, capsys, tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    _fake_client(FakeSDK(), monkeypatch)
    rc = cli_foundry.main(["analyze", "--file", str(doc), "--analyzer", "loan-application-v2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "analyzer: loan-application-v2" in out and "fields: 4" in out
    assert "BorrowerName" in out and "Ada Lovelace" in out


def test_ad_foundry_analyze_can_record_the_raw_result_which_is_what_a_fixture_is(monkeypatch,
                                                                                 capsys, tmp_path):
    doc, raw = tmp_path / "a.pdf", tmp_path / "raw.json"
    doc.write_bytes(b"%PDF")
    _fake_client(FakeSDK(), monkeypatch)
    cli_foundry.main(["analyze", "--file", str(doc), "--analyzer", "x", "--out", str(raw)])
    assert json.loads(raw.read_text(encoding="utf-8"))["analyzerId"] == "loan-application-v2"


def test_ad_foundry_analyze_with_no_analyzer_anywhere_refuses_with_exit_2(monkeypatch, capsys,
                                                                         tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    _fake_client(FakeSDK(), monkeypatch)
    assert cli_foundry.main(["analyze", "--file", str(doc)]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "ad-foundry analyzers list" in out


def test_ad_foundry_analyze_asks_what_to_read_before_which_analyzer(capsys):
    """With no arguments at all, "you did not say what to read" is the more immediate problem; a
    missing analyzer is a setup answer rather than a typing one."""
    assert cli_foundry.main(["analyze"]) == 2
    assert "exactly one of --file and --url" in capsys.readouterr().out


def test_ad_foundry_analyzers_list(monkeypatch, capsys):
    _fake_client(FakeSDK(), monkeypatch)
    assert cli_foundry.main(["analyzers", "list"]) == 0
    out = capsys.readouterr().out
    assert "analyzers: 2" in out and "prebuilt-documentAnalyzer" in out


def test_ad_foundry_analyzers_get_prints_the_declared_field_schema(monkeypatch, capsys):
    _fake_client(FakeSDK(), monkeypatch)
    assert cli_foundry.main(["analyzers", "get", "loan-application-v2"]) == 0
    out = capsys.readouterr().out
    assert "fields: 4" in out and "BorrowerName" in out and "Requested principal" in out


def test_ad_foundry_says_when_an_analyzer_declares_no_fields(monkeypatch, capsys):
    content_only = {"analyzerId": "prebuilt-documentAnalyzer", "status": "ready"}
    _fake_client(FakeSDK(analyzer=content_only), monkeypatch)
    cli_foundry.main(["analyzers", "get", "prebuilt-documentAnalyzer"])
    assert "extracts content only" in capsys.readouterr().out


def test_ad_foundry_reports_a_service_failure_as_a_refusal_not_a_traceback(monkeypatch, capsys):
    _fake_client(FakeSDK(boom=RuntimeError("(Forbidden) no Cognitive Services access")), monkeypatch)
    assert cli_foundry.main(["analyzers", "list"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "Cognitive Services access" in out


# --------------------------------------------------------------------------- ad-dpm wiring


def test_ad_dpm_passes_the_analyzer_and_floor_through_to_the_engine(monkeypatch, tmp_path, capsys):
    text = tmp_path / "t.txt"
    text.write_text("Borrower: Ada Lovelace\n", encoding="utf-8")
    manifest = tmp_path / "job-manifest.json"
    manifest.write_text(json.dumps({"job_manifest_version": "1", "producer": {"run_id": "R"},
                                    "jobs": [{"job_id": "J1", "route": "native_text",
                                              "document_id": "D1", "page": 1, "sha256": "a" * 64,
                                              "text_path": str(text)}]}), encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"fields": [{"name": "loan_amount", "hint": "Loan Amount:"}]}),
                      encoding="utf-8")

    seen = {}

    def fake_engine_for(name, options=None):
        seen["name"], seen["options"] = name, options
        return _engine(FakeSDK())

    monkeypatch.setattr(cli_dpm.EX, "engine_for", fake_engine_for)
    rc = cli_dpm.main(["extract-fields", "--manifest", str(manifest), "--schema", str(schema),
                       "--engine", "azure-content-understanding", "--analyzer", "loan-v9",
                       "--min-confidence", "0.5", "--no-review"])
    assert rc == 0
    assert seen["name"] == "azure-content-understanding"
    assert seen["options"] == {"analyzer": "loan-v9", "min_confidence": 0.5}
    assert "125000.0" in capsys.readouterr().out


def test_ad_dpm_passes_no_options_when_none_were_given(monkeypatch, tmp_path):
    """An engine's own default is a decision it documents; `cli_dpm` must not overwrite it with None."""
    text = tmp_path / "t.txt"
    text.write_text("Loan Amount: 1\n", encoding="utf-8")
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"job_manifest_version": "1", "producer": {"run_id": "R"},
                                    "jobs": [{"job_id": "J1", "route": "native_text",
                                              "document_id": "D1", "page": 1, "sha256": "a" * 64,
                                              "text_path": str(text)}]}), encoding="utf-8")
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps({"fields": [{"name": "loan_amount", "hint": "Loan Amount:"}]}),
                      encoding="utf-8")
    seen = {}
    monkeypatch.setattr(cli_dpm.EX, "engine_for",
                        lambda name, options=None: seen.setdefault("options", options)
                        or EX.SimpleEngine())
    cli_dpm.main(["extract-fields", "--manifest", str(manifest), "--schema", str(schema),
                  "--no-review"])
    assert seen["options"] == {}


# --------------------------------------------------------------------------- the setup step


@pytest.mark.parametrize("endpoint,trouble", [
    ("https://r.services.ai.azure.com", ""),
    ("https://r.cognitiveservices.azure.com", ""),
    ("abc123def456", "not an https"),                                   # a key pasted here
    ("https://r.services.ai.azure.com/contentunderstanding", "path"),   # the SDK appends its own
    ("https://example.com", "not an Azure AI endpoint"),
])
def test_the_endpoint_check_catches_what_a_person_actually_pastes(endpoint, trouble):
    from agentdata.setup.steps import content_understanding as STEP

    assert trouble in STEP.endpoint_trouble(endpoint)


def test_an_unconfigured_service_is_skipped_not_failed():
    """A `fail` row for an optional service nobody uses pushes the rows that matter off the screen."""
    from agentdata.setup.steps import content_understanding as STEP
    from agentdata.setup import wizard as W

    ctx = W.Context(cfg={}, det=None, ask=None, facts={}, online=False, interactive=False)
    step = STEP.ContentUnderstandingStep()
    step.check(ctx, {"use": False, "endpoint": "", "analyzer": "", "auth": "entra",
                     "sdk": False, "identity": False, "user": "x"})
    assert [c.status for c in ctx.checks] == ["skip"]


def test_a_configured_service_with_a_missing_package_says_install_not_patch():
    from agentdata.setup.steps import content_understanding as STEP
    from agentdata.setup import wizard as W

    ctx = W.Context(cfg={}, det=None, ask=None, facts={}, online=False, interactive=False)
    STEP.ContentUnderstandingStep().check(
        ctx, {"use": True, "endpoint": "https://r.services.ai.azure.com", "analyzer": "",
              "auth": "entra", "sdk": False, "identity": False, "user": "x"})
    rows = {c.name: c for c in ctx.checks}
    assert rows["sdk"].status == "fail" and "pip install" in rows["sdk"].hint
    assert rows["auth"].status == "fail" and "azure-identity" in rows["auth"].detail
    assert rows["analyzer"].status == "warn"        # a per-run --analyzer is a legitimate choice
