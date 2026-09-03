"""DPM -> consumer handoff contract: run root read-only, every reference resolved, versions refused, artifacts governed."""
import hashlib
import json
import os
import sqlite3

import pytest

from agentdata import cli_dpm
from agentdata.dpm import DpmError
from agentdata.dpm import binding as B
from agentdata.dpm import convert as CV
from agentdata.dpm import describe as DS
from agentdata.dpm import guard as G
from agentdata.dpm import validate as V
from agentdata.dpm.run import Run

RUN_ID = "RUN-2026-09-02-001"
# id, loan, channel, relpath, pages, mime, status
DOCS = [
    ("D1", "L1", "email", "docs/L1/D1.pdf", 3, "application/pdf", "ok"),
    ("D2", "L2", "scan", "docs/L2/D2.tif", 1, "image/tiff", "ok"),
    ("D3", "L3", "upload", "docs/L3/D3.xlsx", 2, "application/vnd.ms-excel", "ok"),      # needs OCR, not OCR-able -> unsupported
    ("D4", "L4", "email", "docs/L4/D4.pdf", 1, "application/pdf", "ok"),                # canonical sha256 is stale -> unresolved
    ("D5", "L5", "fax", "docs/L5/D5.pdf", 2, "application/pdf", "ok"),                  # channel not allowed -> unresolved
    ("D6", "L6", "email", "docs/L6/D6.pdf", 1, "application/pdf", "corrupt"),           # status -> unsupported
    ("D7", "L7", "upload", "docs/L7/D7.docx", 2, None, "ok"),                           # all pages native -> resolved, no OCR
]
# doc -> page -> (has_native_text, char_count, text_quality or None, text file present)
ANALYSIS = {
    "D1": {1: (True, 500, 0.9, True), 2: (False, 0, None, False), 3: (True, 5, 0.9, True)},
    "D2": {1: (False, 0, None, False)},
    "D3": {1: (False, 0, None, False), 2: (False, 0, None, False)},
    "D4": {1: (True, 300, 0.8, True)},
    "D5": {1: (True, 300, 0.8, True), 2: (False, 0, None, False)},
    "D6": {1: (False, 0, None, False)},
    "D7": {1: (True, 900, 0.95, True), 2: (True, 800, None, True)},
}


def _w(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def content(did: str) -> bytes:
    return f"{did} binary content ".encode() * 200


def canonical_sha(did: str) -> str:
    return _sha(content(did)) if did != "D4" else _sha(b"stale")


def make_run(root, *, run_id=RUN_ID, user_version=1, schema_version="1", manifest_version="1", analysis_version="1",
             with_channels=True, with_pages=True) -> str:
    os.makedirs(root, exist_ok=True)
    for did, _loan, _ch, rel, _pages, _mime, _status in DOCS:
        _w(os.path.join(root, rel), content(did))
    db = sqlite3.connect(os.path.join(root, "orchestrator.db"))
    db.execute(f"PRAGMA user_version = {user_version}")
    db.execute("CREATE TABLE runs (run_id TEXT, started_at TEXT)")
    db.execute("INSERT INTO runs VALUES (?, ?)", (run_id, "2026-09-02T10:00:00Z"))
    if schema_version is not None:
        db.execute("CREATE TABLE schema_version (version TEXT, applied_at TEXT)")
        db.execute("INSERT INTO schema_version VALUES (?, ?)", (schema_version, "2026-09-01"))
    db.execute("CREATE TABLE documents (document_id TEXT PRIMARY KEY, loan_id TEXT, sha256 TEXT, channel TEXT, source_path TEXT, "
               "page_count INTEGER, mime_type TEXT, status TEXT)")
    for did, loan, ch, rel, pages, mime, status in DOCS:
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)", (did, loan, canonical_sha(did), ch, rel, pages, mime, status))
    if with_channels:
        db.execute("CREATE TABLE channels (channel TEXT, description TEXT)")
        db.executemany("INSERT INTO channels VALUES (?, ?)", [("email", ""), ("scan", ""), ("upload", ""), ("sftp", "")])
    if with_pages:
        db.execute("CREATE TABLE pages (document_id TEXT, page_number INTEGER, width INTEGER)")
        for did, _loan, _ch, _rel, pages, _mime, _status in DOCS:
            db.executemany("INSERT INTO pages VALUES (?, ?, ?)", [(did, p, 612) for p in range(1, pages + 1)])
    db.commit()
    db.close()
    for did, _loan, _ch, _rel, _pages, _mime, _status in DOCS:
        entries = []
        for p, (native, chars, quality, has_file) in ANALYSIS[did].items():
            e = {"page": p, "has_native_text": native, "char_count": chars}
            if quality is not None:
                e["text_quality"] = quality
            if native:
                tp = f"text_analysis/{did}/p{p:04d}.txt"
                e["text_path"] = tp
                if has_file:
                    _w(os.path.join(root, tp), (f"native text of {did} page {p} " * max(1, chars // 20)).encode())
            entries.append(e)
        doc = {"schema_version": analysis_version, "document_id": did, "sha256": canonical_sha(did), "pages": entries}
        if analysis_version is None:
            del doc["schema_version"]
        _w(os.path.join(root, "text_analysis", f"{did}.json"), json.dumps(doc, indent=1).encode())
    sel1 = {"manifest_version": manifest_version, "selection_id": "SEL-001", "run_id": run_id,
            "items": [{"document_id": "D1", "loan_id": "L1"}, {"document_id": "D2", "loan_id": "L2", "pages": "all"}, {"document_id": "D3"},
                      {"document_id": "D4"}, {"document_id": "D5"}, {"document_id": "D6"}, {"document_id": "D7", "pages": [1, 2]}]}
    sel2 = {"manifest_version": manifest_version, "selection_id": "SEL-002",
            "items": [{"document_id": "D1", "pages": [1, 4]}, {"document_id": "D9"}, {"sha256": canonical_sha("D2"), "loan_id": "WRONG"}]}
    for name, s in (("sel-001", sel1), ("sel-002", sel2)):
        if manifest_version is None:
            s.pop("manifest_version")
        _w(os.path.join(root, "selections", f"{name}.json"), json.dumps(s, indent=1).encode())
    return root


EXPECTED_COUNTS = {"selections": 2, "documents": 10, "pages_selected": 15, "resolved": 3, "unresolved": 5, "unsupported": 2,
                   "native_text": 3, "ocr": 3, "errors": 5, "warnings": 2}


@pytest.fixture
def run_root(tmp_path):
    return make_run(str(tmp_path / "runs" / RUN_ID))


@pytest.fixture
def consumer(tmp_path):
    c = tmp_path / "consumer"
    (c / ".git").mkdir(parents=True)
    return str(c)


def _run(root) -> Run:
    return Run.locate(B.builtin(), run_root=root)


# ---------- locate / versions ----------
def test_locate_markers_run_id_and_versions(run_root, tmp_path):
    run = _run(run_root)
    assert run.run_id() == RUN_ID
    assert run.check_versions() == {"orchestrator_user_version": 1, "orchestrator_schema_version": "1"}
    assert [os.path.basename(p) for p in run.selection_paths()] == ["sel-001.json", "sel-002.json"]
    with pytest.raises(DpmError) as e:
        Run.locate(B.builtin(), run_root=str(tmp_path))
    assert e.value.code == "not_a_run_root" and "orchestrator.db" in e.value.msg
    runs = str(tmp_path / "runs")
    assert Run.locate(B.builtin(), runs_dir=runs, latest=True).root == run_root
    assert Run.locate(B.builtin(), runs_dir=runs, run_id=RUN_ID).root == run_root
    with pytest.raises(DpmError) as e:
        Run.locate(B.builtin(), runs_dir=runs, run_id="nope")
    assert e.value.code == "run_not_found"


def test_unsupported_or_missing_versions_refuse(tmp_path):
    with pytest.raises(DpmError) as e:
        _run(make_run(str(tmp_path / "r1"), user_version=2)).check_versions()
    assert e.value.code == "unsupported_version" and "'2'" in e.value.msg
    with pytest.raises(DpmError) as e:
        _run(make_run(str(tmp_path / "r2"), user_version=0, schema_version=None)).check_versions()
    assert e.value.code == "unsupported_version" and "no schema version marker" in e.value.msg
    with pytest.raises(DpmError) as e:
        _run(make_run(str(tmp_path / "r3"), manifest_version="2")).selections()
    assert e.value.code == "unsupported_version" and "sel-001.json" in e.value.msg
    r4 = make_run(str(tmp_path / "r4"), analysis_version=None)
    with pytest.raises(DpmError) as e:
        V.validate(_run(r4))
    assert e.value.code == "unsupported_version" and "schema_version" in e.value.msg
    b = B.builtin()
    b["versions"]["text_analysis"]["required"] = False
    assert V.validate(Run.locate(b, run_root=r4)).counts() == EXPECTED_COUNTS


# ---------- validate ----------
def test_validate_buckets_and_findings(run_root):
    res = V.validate(_run(run_root))
    assert res.counts() == EXPECTED_COUNTS
    errors = {(f.object, f.kind) for f in res.findings if f.severity == "error"}
    assert errors == {("D4", "sha256-content-mismatch"), ("D5", "channel-unknown"), ("D1", "page-out-of-range"),
                      ("D9", "document-unknown"), ("D2", "loan-mismatch")}
    warnings = {(f.object, f.kind) for f in res.findings if f.severity == "warning"}
    assert warnings == {("D3", "document-unsupported-type"), ("D6", "document-unsupported-status")}
    assert all(f.hint for f in res.findings)
    d1 = next(d for d in res.docs if d.document_id == "D1" and d.selection_id == "SEL-001")
    assert d1.bucket == "resolved" and d1.pages == [1, 2, 3] and d1.hash_verified and d1.canonical_rowid == 1
    assert d1.page_info[1]["text_rel"] == "text_analysis/D1/p0001.txt"
    assert [V.native_reusable(d1.page_info[p], res.partition) for p in (1, 2, 3)] == [True, False, False]
    by_sha = next(d for d in res.docs if d.selection_id == "SEL-002" and d.document_id == "D2")
    assert by_sha.unresolved == ["loan-mismatch"] and by_sha.loan_id == "L2"
    assert res.channels_source == "table channels"


def test_validate_reads_only(run_root):
    before = G.snapshot(run_root)
    run = _run(run_root)
    V.validate(run)
    run.close()
    assert G.snapshot(run_root)["sha256"] == before["sha256"] and G.diff(before, G.snapshot(run_root)) == []
    assert not any(f.endswith(("-journal", "-wal", "-shm")) for f in os.listdir(run_root))


def test_channels_unconstrained_and_pages_table_optional(tmp_path):
    root = make_run(str(tmp_path / "r"), with_channels=False, with_pages=False)
    res = V.validate(_run(root))
    kinds = [f.kind for f in res.findings if f.severity == "warning"]
    assert "channels-unconstrained" in kinds and res.channels_source == "unconstrained"
    c = res.counts()
    assert c["unresolved"] == 4 and c["resolved"] == 4    # D5 (fax) now resolves
    b = B.builtin()
    b["channels"]["allowed"] = ["email", "scan", "upload"]
    assert V.validate(Run.locate(b, run_root=root)).counts()["unresolved"] == 5


# ---------- convert / artifacts / lineage ----------
def _convert(run_root, consumer, *extra):
    return cli_dpm.main(["convert", "--run-root", run_root, "--consumer", consumer, "--artifact-dir", "artifacts/dpm", *extra])


def test_convert_manifest_lineage_and_artifacts(run_root, consumer, capsys):
    before = G.snapshot(run_root)
    assert _convert(run_root, consumer) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "run_root_untouched: true" in out and "native_text: 3" in out and "unresolved: 5" in out
    out_dir = os.path.join(consumer, "artifacts", "dpm", RUN_ID)
    assert sorted(os.listdir(out_dir)) == sorted(CV.FILES)
    m = json.load(open(os.path.join(out_dir, "job-manifest.json"), encoding="utf-8"))
    assert m["job_manifest_version"] == "1" and m["contract"]["binding"] == "builtin" and len(m["contract"]["binding_sha256"]) == 64
    assert m["counts"]["jobs"] == 6 and m["counts"]["native_text"] == 3 and m["counts"]["ocr"] == 3
    assert [j["job_id"] for j in m["jobs"]] == ["SEL-001:D1:p1", "SEL-001:D1:p2", "SEL-001:D1:p3", "SEL-001:D2:p1", "SEL-001:D7:p1", "SEL-001:D7:p2"]
    j = m["jobs"][0]
    assert j["route"] == "native_text" and j["text_path"] == "text_analysis/D1/p0001.txt" and j["loan_id"] == "L1"
    assert j["lineage"] == {"producer": "DPM", "run_id": RUN_ID, "selection_manifest": "selections/sel-001.json", "selection_item": 0,
                            "canonical_table": "documents", "canonical_rowid": 1, "document_id": "D1", "source_sha256": canonical_sha("D1"),
                            "source_path": "docs/L1/D1.pdf", "page": 1, "text_analysis": "text_analysis/D1.json", "text_path": "text_analysis/D1/p0001.txt"}
    assert m["jobs"][1]["route"] == "ocr" and m["jobs"][1]["text_path"] is None
    ex = {(x["selection_id"], x["document_id"] or x["sha256"][:8]): (x["bucket"], x["reasons"]) for x in m["excluded"]}
    assert ex[("SEL-001", "D3")] == ("unsupported", ["document-unsupported-type"])
    assert ex[("SEL-001", "D4")] == ("unresolved", ["sha256-content-mismatch"])
    assert ex[("SEL-002", "D9")] == ("unresolved", ["document-unknown"])
    assert m["producer"]["versions"] == {"orchestrator_user_version": 1, "orchestrator_schema_version": "1", "selection_manifest": ["1"], "text_analysis": ["1"]}
    assert m["producer"]["snapshot_sha256"] == before["sha256"] and m["producer"]["orchestrator_db_sha256"] == G.file_sha256(os.path.join(run_root, "orchestrator.db"))
    receipt = json.load(open(os.path.join(out_dir, "receipt.json"), encoding="utf-8"))
    for f in receipt["files"]:
        if f["path"] != "receipt.json":
            assert G.file_sha256(os.path.join(out_dir, f["path"])) == f["sha256"]
    assert receipt["replaced"] == [] and receipt["snapshot_before"] == before["sha256"]
    lines = open(os.path.join(out_dir, "jobs.tsv"), encoding="utf-8").read().splitlines()
    assert lines[0].split("\t") == CV.JOB_COLS and len(lines) == 7
    val = open(os.path.join(out_dir, "validation.tsv"), encoding="utf-8").read().splitlines()
    assert len(val) == 1 + EXPECTED_COUNTS["errors"] + EXPECTED_COUNTS["warnings"]
    assert G.snapshot(run_root)["sha256"] == before["sha256"]
    # a second handoff for the same run id must be explicit
    assert _convert(run_root, consumer) == 2
    assert "refused: artifacts_exist" in capsys.readouterr().out
    assert _convert(run_root, consumer, "--force") == 0
    assert json.load(open(os.path.join(out_dir, "receipt.json"), encoding="utf-8"))["replaced"] == list(CV.FILES)


def test_convert_refuses_paths_outside_governed_dir(run_root, consumer, capsys):
    rc = cli_dpm.main(["convert", "--run-root", run_root, "--consumer", consumer, "--artifact-dir", "../elsewhere"])
    assert rc == 2 and "refused: artifact_dir_outside_consumer" in capsys.readouterr().out
    runs_dir = os.path.dirname(run_root)
    rc = cli_dpm.main(["convert", "--run-root", run_root, "--consumer", runs_dir, "--artifact-dir", os.path.join(RUN_ID, "handoff")])
    assert rc == 2 and "refused: artifact_dir_touches_run_root" in capsys.readouterr().out
    assert not os.path.exists(os.path.join(run_root, "handoff"))


def test_convert_needs_artifact_dir_fact_and_strict(run_root, consumer, capsys, monkeypatch):
    monkeypatch.chdir(consumer)
    assert cli_dpm.main(["convert", "--run-root", run_root]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "dpm_artifact_dir" in out
    assert cli_dpm.main(["convert", "--run-root", run_root, "--artifact-dir", "artifacts", "--strict"]) == 2
    assert "refused: unresolved_references" in capsys.readouterr().out
    assert not os.path.exists(os.path.join(consumer, "artifacts"))


def test_lineage_verify_detects_producer_drift(run_root, consumer, capsys):
    assert _convert(run_root, consumer) == 0
    capsys.readouterr()
    manifest = os.path.join(consumer, "artifacts", "dpm", RUN_ID, "job-manifest.json")
    assert cli_dpm.main(["lineage", "--manifest", manifest]) == 0
    assert "broken: 0" in capsys.readouterr().out
    assert cli_dpm.main(["lineage", "--manifest", manifest, "--job", "SEL-001:D7:p2"]) == 0
    out = capsys.readouterr().out
    assert "status: ok" in out and "text_path: text_analysis/D7/p0002.txt" in out
    _w(os.path.join(run_root, "docs", "L1", "D1.pdf"), b"tampered")
    os.remove(os.path.join(run_root, "text_analysis", "D7", "p0002.txt"))
    assert cli_dpm.main(["lineage", "--manifest", manifest]) == 1
    out = capsys.readouterr().out
    assert "broken: 4" in out and "source sha256 changed" in out and "native text missing" in out
    assert cli_dpm.main(["lineage", "--manifest", manifest, "--job", "nope"]) == 2


# ---------- binding ----------
def test_binding_override_rebinding_and_typos(tmp_path, consumer, capsys):
    root = make_run(str(tmp_path / "r"))
    db = sqlite3.connect(os.path.join(root, "orchestrator.db"))
    db.execute("ALTER TABLE documents RENAME COLUMN sha256 TO content_hash")
    db.commit()
    db.close()
    with pytest.raises(DpmError) as e:
        _run(root).canonical_documents()
    assert e.value.code == "binding_mismatch" and "sha256->sha256" in e.value.msg
    d = DS.describe(_run(root))
    row = next(r for r in d["binding"] if r["concept"] == "canonical.columns.sha256")
    assert row["status"] == "missing" and "content_hash" in row["candidates"] and d["binding_ok"] is False
    assert cli_dpm.main(["inspect", "--run-root", root]) == 1
    out = capsys.readouterr().out
    assert "binding_ok: false" in out and "content_hash" in out
    bpath = os.path.join(consumer, "dpm-binding.json")
    with open(bpath, "w", encoding="utf-8") as f:
        json.dump({"binding_version": 1, "canonical": {"columns": {"sha256": "content_hash"}}}, f)
    b, label = B.load(bpath)
    assert label.endswith("dpm-binding.json") and b["canonical"]["columns"]["sha256"] == "content_hash" and B.sha256(b) != B.sha256(B.builtin())
    assert V.validate(Run.locate(b, run_root=root)).counts() == EXPECTED_COUNTS
    assert cli_dpm.main(["validate", "--run-root", root, "--consumer", consumer, "--binding", "dpm-binding.json"]) == 1   # 5 reference errors
    out = capsys.readouterr().out
    assert "binding: " in out and "errors: 5" in out and "run_root_untouched: true" in out
    with open(bpath, "w", encoding="utf-8") as f:
        json.dump({"canonical": {"colums": {"sha256": "content_hash"}}}, f)
    with pytest.raises(DpmError) as e:
        B.load(bpath)
    assert e.value.code == "binding_invalid" and "canonical.colums" in e.value.msg
    assert cli_dpm.main(["binding", "--write", "b2.json", "--consumer", consumer]) == 0
    assert json.load(open(os.path.join(consumer, "b2.json"), encoding="utf-8")) == B.builtin()
    assert cli_dpm.main(["binding", "--write", "b2.json", "--consumer", consumer]) == 2


def test_inspect_happy_path_and_facts(run_root, consumer, capsys, monkeypatch):
    assert cli_dpm.main(["inspect", "--run-root", run_root]) == 0
    out = capsys.readouterr().out
    assert "binding_ok: true" in out and "supported_version: true" in out and "documents,7," in out and "sel-001.json" in out
    with open(os.path.join(consumer, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write(f"- dpm_run_root: {run_root}\n- dpm_artifact_dir: handoff/dpm\n")
    monkeypatch.chdir(consumer)
    assert cli_dpm.main(["locate"]) == 0
    out = capsys.readouterr().out
    assert f"run_id: {RUN_ID}" in out and "canonical_documents: 7" in out and "selection_manifests: 2" in out
    assert cli_dpm.main(["convert"]) == 0
    assert os.path.isfile(os.path.join(consumer, "handoff", "dpm", RUN_ID, "job-manifest.json"))
    from agentdata.__main__ import COMMANDS
    assert COMMANDS["dpm"][0] == "agentdata.cli_dpm"


def test_every_dpm_reader_accepts_what_powershell_writes(run_root, consumer, tmp_path):
    """`ad-dpm binding --show > dpm-binding.json` in PowerShell 5.1 writes UTF-16: every reader must cope."""
    b16 = tmp_path / "b16.json"
    b16.write_bytes(b"\xff\xfe" + json.dumps({"canonical": {"columns": {"sha256": "sha256"}}}).encode("utf-16-le"))
    assert B.load(str(b16))[0]["canonical"]["columns"]["sha256"] == "sha256"
    sel = os.path.join(run_root, "selections", "sel-001.json")
    raw = open(sel, encoding="utf-8").read()
    open(sel, "wb").write(raw.encode("utf-8-sig"))                       # Set-Content -Encoding utf8
    ana = os.path.join(run_root, "text_analysis", "D1.json")
    raw_ana = open(ana, encoding="utf-8").read()
    open(ana, "wb").write(b"\xff\xfe" + raw_ana.encode("utf-16-le"))          # PowerShell `>` redirection
    assert V.validate(_run(run_root)).counts() == EXPECTED_COUNTS
    assert _convert(run_root, consumer) == 0
    m = os.path.join(consumer, "artifacts", "dpm", RUN_ID, "job-manifest.json")
    raw_m = open(m, encoding="utf-8").read()
    open(m, "wb").write(b"\xef\xbb\xbf" + raw_m.encode("utf-8"))
    assert CV.verify(CV.load_manifest(m))["ok"] is True


def test_inspect_never_tracebacks_on_a_damaged_database(run_root, capsys):
    db = sqlite3.connect(os.path.join(run_root, "orchestrator.db"))
    db.execute("CREATE TABLE tmp (x TEXT)")
    db.execute("CREATE VIEW broken AS SELECT * FROM tmp")
    db.execute("DROP TABLE tmp")
    db.commit()
    db.close()
    rc = cli_dpm.main(["inspect", "--run-root", run_root])              # the command documented as never refusing
    out = capsys.readouterr().out
    assert rc in (0, 1) and "problems" in out and "no such table" in out and "broken,-1," in out


def test_convert_refuses_an_existing_handoff_before_hashing_anything(run_root, consumer, capsys, monkeypatch):
    assert _convert(run_root, consumer) == 0
    capsys.readouterr()
    monkeypatch.setattr(G, "file_sha256", lambda p: pytest.fail(f"hashed {p} before refusing"))
    assert _convert(run_root, consumer) == 2
    assert "refused: artifacts_exist" in capsys.readouterr().out


def test_producer_paths_are_checked_for_traversal_and_containment(tmp_path, capsys):
    root = make_run(str(tmp_path / "r"))
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(content("D1"))
    db = sqlite3.connect(os.path.join(root, "orchestrator.db"))
    db.execute("UPDATE documents SET source_path = ? WHERE document_id = 'D1'", (str(outside),))
    db.execute("UPDATE documents SET document_id = '../evil' WHERE document_id = 'D2'")
    db.commit()
    db.close()
    res = V.validate(_run(root))
    kinds = {(f.object, f.kind) for f in res.findings}
    assert ("D1", "source-outside-root") in kinds                        # warning: outside the snapshot
    assert ("../evil", "document-id-unsafe") in kinds                    # error: the id is used to name files
    d2 = next(d for d in res.docs if d.document_id == "../evil")
    assert d2.unresolved == ["document-id-unsafe"] and d2.analysis_rel is None
    assert V.unsafe_id("a/b") and V.unsafe_id("..") and V.unsafe_id("") and not V.unsafe_id("D-1.pdf")
    d1 = next(d for d in res.docs if d.document_id == "D1" and d.selection_id == "SEL-001")
    assert d1.bucket == "resolved" and d1.hash_verified                  # still usable, but flagged
