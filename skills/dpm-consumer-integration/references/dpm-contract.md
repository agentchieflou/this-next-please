# DPM → consumer handoff contract (v1)

Producer: the `DPM` repository writes a **run root** per run. Consumer: `data_remediation_foundry_DPM_fork` continues
from it (document grouping, OCR extraction, secondary validation, profiling, human review, mapping back to document
types). This document is the contract between them; `ad-dpm` (`agentdata/dpm/`) is its executable form.

## Guarantees and the mechanism behind each
| Guarantee | Mechanism |
|---|---|
| The run root is never written | `orchestrator.db` is opened `file:…?mode=ro&immutable=1` (no lock, no journal, no `-shm`); manifests are read once; a tree fingerprint (path, size, mtime of every file) is taken before and after every command and printed as `run_root_untouched` |
| Every reference resolves | `ad-dpm validate` re-resolves each selection item: canonical row, source file on disk, recomputed sha256, page range (and pages table when present), channel set, loan id, text_analysis output and its text files |
| Unsupported versions are refused | `PRAGMA user_version` / version table, `manifest_version` in each selection manifest, `schema_version` in each text_analysis output are compared to the binding's `supported` lists before any work; `refused: unsupported_version`, exit 2 |
| Artifacts only in the governed directory | `--artifact-dir` / `dpm_artifact_dir` must resolve inside `--consumer` and must not overlap the run root; anything else is `refused: artifact_dir_*` |
| Lineage is preserved | every job carries `lineage` (run id, selection manifest + item index, canonical table + rowid, document id, source sha256 + path, page, text_analysis file, text file); `ad-dpm lineage` re-verifies it later |
| Nothing is silently dropped | every selection item ends up either as jobs or in `excluded` with its bucket and reasons |

## Run root layout (binding `run_root`)
```
<run root>/                       one DPM run; the folder name is the fallback run id
  orchestrator.db                 SQLite: canonical manifests (documents, optional pages/channels/runs, version table)
  selections/*.json               selection manifests (also matched: selection_manifests/*.json, manifests/selection*.json, *.selection.json)
  text_analysis/<document_id>.json   one text_analysis output per document (placeholders: {document_id} {sha256})
  text_analysis/<document_id>/pNNNN.txt  native text files named by `text_path` (any path relative to the run root works)
  docs/...                        source documents, wherever `source_path` points (relative to the run root, or absolute)
```
Both markers (`orchestrator.db`, `text_analysis/`) must exist for a folder to be a run root. A `-wal` file next to the
database produces the warning `orchestrator-wal-pending`: ask DPM to checkpoint before handing over.

## Version markers
| Where | Key | Builtin supported |
|---|---|---|
| `orchestrator.db` | `PRAGMA user_version` and/or `schema_version.version` (last row) | `1` |
| each selection manifest | `manifest_version` | `1`, `1.0` |
| each text_analysis output | `schema_version` | `1`, `1.0` |

Missing marker = unsupported (refused) unless the binding sets `required: false` for that marker. Extending a
`supported` list is a contract decision for Michael and the DPM owners; the worker model files a friction log instead.

## Canonical manifest (`documents`, binding `canonical`)
| Concept | Column | Required | Used for |
|---|---|---|---|
| `document_id` | `document_id` | yes | identity; text_analysis file name; job ids |
| `loan_id` | `loan_id` | yes | must be present; must equal the selection's `loan_id` when given |
| `sha256` | `sha256` | yes | 64 lowercase hex; recomputed from the source file |
| `channel` | `channel` | yes | must be in the allowed set (`channels.allowed`, else `channels.channel` table, else unconstrained + warning) |
| `source_path` | `source_path` | yes | relative to the run root or absolute; must exist |
| `page_count` | `page_count` | no | falls back to the `pages` table, then to the text_analysis page list |
| `mime_type` | `mime_type` | no | OCR-ability; falls back to the file extension |
| `status` | `status` | no | one of `unsupported_statuses` (`unsupported`, `rejected`, `corrupt`, `failed`) → unsupported bucket |

Optional `pages(document_id, page_number)`: when present every selected page must have a row. Optional `runs.run_id`
(last row) is the run id; the folder name otherwise.

## Selection manifest (binding `selection.keys`)
```json
{"manifest_version": "1", "selection_id": "SEL-001", "run_id": "RUN-2026-09-02-001",
 "items": [{"document_id": "D1", "loan_id": "L1", "pages": [1, 2]}, {"sha256": "<64 hex>"}]}
```
`items[]` reference a document by `document_id` (preferred) or by `sha256` (must be unique in the canonical manifest).
`pages` absent, `"all"` or `[]` selects every page (`1..page_count`); otherwise positive integers. A `run_id` that
differs from the run's id makes every item of that manifest unresolved (`selection-run-mismatch`). Duplicate
`selection_id` across manifests → both unresolved.

## text_analysis output (binding `text_analysis.keys`)
```json
{"schema_version": "1", "document_id": "D1", "sha256": "<64 hex>", "unsupported": false,
 "pages": [{"page": 1, "has_native_text": true, "char_count": 512, "text_quality": 0.93, "text_path": "text_analysis/D1/p0001.txt"},
           {"page": 2, "has_native_text": false}]}
```
`document_id` / `sha256` inside the file, when present, must match the canonical row (`analysis-mismatch`). A truthy
`unsupported` puts the document in the unsupported bucket.

## Resolution rules (every failure is an `error` finding; the document goes to `unresolved`)
| kind | condition |
|---|---|
| `document-unknown` / `document-ambiguous` | item not in the canonical manifest / several rows share the sha256 and no `document_id` |
| `sha256-selection-mismatch` / `sha256-malformed` / `sha256-content-mismatch` | selection sha ≠ canonical / not 64 hex / file on disk hashes differently |
| `loan-missing` / `loan-mismatch` | no canonical loan id / selection loan id ≠ canonical |
| `channel-missing` / `channel-unknown` | no channel / not in the allowed set |
| `source-missing` | `source_path` empty or file absent |
| `page-count-missing` / `page-invalid` / `page-out-of-range` / `page-not-in-canonical` | no page count from any source / non-integer page / page > page_count / no row in `pages` |
| `analysis-missing` / `analysis-mismatch` / `analysis-page-missing` | no text_analysis file / it names another document / no entry for a selected page |
| `text-path-missing` / `text-missing` | page has native text but no `text_path` / the text file is absent or empty |
| `selection-run-mismatch` / `selection-duplicate-id` / `selection-id-missing` | manifest-level problems; every item of the manifest is unresolved |

Warnings (never block): `document-unsupported-status`, `document-unsupported-analysis`, `document-unsupported-type`
(unsupported bucket), `channels-unconstrained`, `selection-empty`, `orchestrator-wal-pending`.

## Route buckets (binding `partition`)
Precedence per selection item: **unresolved** (any error above) > **unsupported** (status / analysis flag / needs OCR
but the type is not OCR-able) > page routes for resolved documents:
- `native_text`: `has_native_text` and `char_count ≥ native_min_chars` (20) and `text_quality ≥ native_min_quality`
  (0.5, only checked when the key is present) and the text file exists and is non-empty;
- `ocr`: every other page of a resolved document. A document with at least one `ocr` page must be OCR-able
  (`mime_type` in `ocr_mime`, else extension in `ocr_extensions`), otherwise the whole document is `unsupported`.
Unsupported and unresolved are document-level buckets: no page of such a document is routed.

## Consumer job manifest (`job-manifest.json`, version 1)
```json
{"job_manifest_version": "1",
 "contract": {"name": "dpm-consumer-integration", "version": 1, "binding": "builtin", "binding_sha256": "…"},
 "producer": {"name": "DPM", "run_id": "…", "run_root": "…", "orchestrator_db": "orchestrator.db", "orchestrator_db_sha256": "…",
              "versions": {"orchestrator_user_version": 1, "orchestrator_schema_version": "1", "selection_manifest": ["1"], "text_analysis": ["1"]},
              "selection_manifests": ["selections/sel-001.json"], "channels": "table channels", "snapshot_sha256": "…", "snapshot_files": 23},
 "consumer": {"name": "data_remediation_foundry_DPM_fork", "root": "…", "artifact_dir": "…", "generated_at": "…Z", "generator": "agentdata ad-dpm convert 0.3.0"},
 "counts": {"selections": 2, "documents": 10, "pages_selected": 15, "resolved": 3, "unresolved": 5, "unsupported": 2, "native_text": 3, "ocr": 3, "errors": 5, "warnings": 2, "jobs": 6},
 "jobs": [{"job_id": "SEL-001:D1:p1", "route": "native_text", "selection_id": "SEL-001", "loan_id": "L1", "document_id": "D1", "sha256": "…",
           "page": 1, "page_count": 3, "source_path": "docs/L1/D1.pdf", "text_path": "text_analysis/D1/p0001.txt", "char_count": 512, "text_quality": 0.93,
           "lineage": {"producer": "DPM", "run_id": "…", "selection_manifest": "selections/sel-001.json", "selection_item": 0, "canonical_table": "documents",
                       "canonical_rowid": 1, "document_id": "D1", "source_sha256": "…", "source_path": "docs/L1/D1.pdf", "page": 1,
                       "text_analysis": "text_analysis/D1.json", "text_path": "text_analysis/D1/p0001.txt"}}],
 "excluded": [{"document_id": "D4", "sha256": "…", "loan_id": "L4", "selection_id": "SEL-001", "bucket": "unresolved",
               "reasons": ["sha256-content-mismatch"], "pages": [1], "source_path": "docs/L4/D4.pdf", "lineage": {"…": "same fields, page null"}}]}
```
Job ids are `<selection_id>:<document_id>:p<page>`; jobs are sorted by selection, document, page, so two runs of
`convert` on the same run root produce byte-identical manifests except `generated_at`. Paths are relative to
`producer.run_root`. Flat copies for scripts: `jobs.tsv`, `excluded.tsv`, `lineage.tsv`, `validation.tsv`.
`receipt.json` records the command, snapshot fingerprint, binding, counts and the sha256 of every artifact.

## `ad-dpm lineage`
Re-opens the run root named in the manifest (or `--run-root`), checks `orchestrator.db` sha256, and per job: selection
manifest present, source file present and (unless `--no-hash`) identical, native text file present. `broken > 0` means
the producer side moved after the handoff: re-run `convert --force` once DPM confirms the run is final.

## Refusal codes (`meta.refused`, exit 2)
| code | meaning | do |
|---|---|---|
| `not_a_run_root`, `runs_dir_missing`, `run_not_found`, `usage` | the folder is not a run root / cannot be found | `ad-dpm inspect`; check facts |
| `unsupported_version` | orchestrator / manifest / text_analysis version outside `supported`, or missing | friction-log to Michael + DPM owners; never edit `supported` |
| `binding_mismatch` | a bound table/column does not exist | `ad-dpm inspect` → rebind names only |
| `binding_invalid`, `binding_missing`, `file_exists` | binding file problems | fix the file; unknown keys are refused on purpose |
| `orchestrator_unreadable`, `manifest_invalid` | damaged producer output | report to DPM; never repair files in the run root |
| `artifact_dir_outside_consumer`, `artifact_dir_touches_run_root`, `consumer_root_missing` | governed-directory rule | fix `dpm_artifact_dir` / `--consumer` |
| `artifacts_exist` | a handoff for this run id exists | `--force` only when replacing it is intended |
| `run_root_changed` | the run changed while being read | the run is not final; ask DPM, retry later |
| `unresolved_references` | `--strict` and errors exist | run `validate`, report, or drop `--strict` |

## Rebinding (what may change without a contract discussion)
Names only: table and column names, manifest key names, file globs, the text_analysis file pattern, thresholds in
`partition`, the allowed channel list. `ad-dpm binding --write dpm-binding.json` writes the builtin binding; keep only
the keys you change (unknown keys are refused). Point the `dpm_binding` fact at the file (relative to the consumer
root). The manifest and receipt carry `binding_sha256`, so a rebinding is visible in every handoff.

## Assumptions to confirm against the hand-back document
The builtin binding encodes this contract; confirm each line against DPM's own hand-back document and rebind where DPM
differs: (1) the run root markers are `orchestrator.db` + `text_analysis/`; (2) the canonical document manifest is the
`documents` table with the columns above; (3) selection manifests are JSON files under `selections/` with
`selection_id`, `items[]`, `manifest_version`; (4) text_analysis outputs are one JSON per document keyed by
`document_id` with a `pages[]` list carrying `has_native_text`, `char_count`, `text_quality`, `text_path`;
(5) the version markers and the accepted values; (6) the thresholds that make native text reusable; (7) the consumer's
governed artifact directory (`dpm_artifact_dir`) and whether it is versioned in git.

## Settings
`--run-root` / `DPM_RUN_ROOT` / `dpm.run_root` / fact `dpm_run_root`; `--runs-dir` (+ `--run-id` or `--latest`) /
`DPM_RUNS_DIR` / `dpm.runs_dir` / fact `dpm_runs_dir`; `--artifact-dir` / `DPM_ARTIFACT_DIR` / `dpm.artifact_dir` / fact
`dpm_artifact_dir` (no default: undocumented governed directories are a STOP); `--binding` / `DPM_BINDING` / `dpm.binding`
/ fact `dpm_binding`; `--consumer` (default: current directory).
