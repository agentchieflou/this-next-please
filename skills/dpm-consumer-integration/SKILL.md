---
name: dpm-consumer-integration
description: "Use when a DPM run (\"hand back\", handoff, a run root holding orchestrator.db, selection manifests and text_analysis outputs) must be taken into data_remediation_foundry_DPM_fork: locate and validate the run, resolve every reference, convert it into the consumer job manifest (native-text pages, OCR pages, unsupported and unresolved documents) with source-to-consumer lineage. Owns the producer→consumer contract. Never writes the DPM run root."
---
# DPM consumer integration (producer `DPM` → consumer `data_remediation_foundry_DPM_fork`)

Run every command from the consumer repo root. Inputs are `AGENTS.md` facts: `dpm_run_root` or `dpm_runs_dir`, `dpm_artifact_dir` (the consumer's governed artifact directory, relative to its root), optional `dpm_binding`.

The contract, mechanized by `ad-dpm`: the run root is read and never written (SQLite opened immutable, tree fingerprint before/after every command); every reference must resolve (source document, page number, sha256, channel, loan id, selection id, text_analysis output); an unsupported producer schema or manifest version is refused before any work; artifacts are written only beneath `dpm_artifact_dir`; every job carries its lineage.

1. Facts. `dpm_artifact_dir` missing → find the governed directory in the consumer repo's own docs (README, CONTRIBUTING, `docs/`), add the fact, commit it. Not documented → `friction-log` (type `ambiguity`: "which directory is governed for DPM handoff artifacts?"). STOP.
2. `ad-dpm locate` (`--run-root <dir>`, or `--runs-dir <dir> --run-id <id>`, or `--latest`). Read `meta`:
   - `refused: unsupported_version` → never touch a `supported` list in the binding. `friction-log` (type `contract`) with the `error` line, addressed to Michael / the DPM owners. STOP.
   - `refused: not_a_run_root` or `binding_mismatch` → step 3.
   - `ok: true` → step 4.
3. `ad-dpm inspect --run-root <dir>`. Each `binding` row with `status: missing` is a name DPM uses differently; `candidates` lists what exists. `ad-dpm binding --write dpm-binding.json`, change only those concepts, set the `dpm_binding` fact to the file, re-run `locate`. A rebinding is a contract change: commit the file and show its diff in the PR. Still `missing` after one rebinding → `friction-log`. STOP.
4. `ad-dpm validate`. Every `error` row is a reference that does not resolve. Never fix one: do not edit the run root, a selection manifest, a text_analysis file or the channel set; they go verbatim into the handoff note (step 7). `warning` rows are unsupported documents or an unconstrained channel set: information, not work.
5. `ad-dpm convert`. `--strict` when the consumer job must not start with unresolved documents; `--force` only to replace a previous handoff for the same run id. Read `meta.path`, the counts, the `excluded` table. Artifacts under `<dpm_artifact_dir>/<run_id>/`: `job-manifest.json` (jobs with `route` native_text|ocr and `lineage`), `jobs.tsv`, `excluded.tsv` (bucket + reasons), `validation.tsv`, `lineage.tsv`, `receipt.json`. Never edit them by hand.
6. `ad-dpm lineage --manifest <path>` before the consumer pipeline reads the manifest and again before human review. `broken > 0` → the producer side moved under the manifest: report it; re-run `convert --force` only after DPM confirms the run is final. Never patch the manifest.
7. Handoff note `.agent/out/<run_id>-dpm-handoff.md` (≤ 30 lines): run id, counts, every unresolved document with its reason, every unsupported document, binding label + sha256, receipt path. This is what DPM and the reviewer read.
8. `state-update` with the artifact paths. Hand off → `bitbucket-pr` (commit the artifacts only if the consumer repo versions its governed directory; never commit source documents), `friction-log` when any command refused twice.

Rules
- `meta.ok: false` with `refused:` is a contract stop, not an error to work around. Two refusals in a row → `friction-log`. STOP.
- `run_root_untouched: false` in any output → stop everything, `friction-log` (type `bug`), do not hand the manifest over.
- Precedence for every setting: flag → env (`DPM_RUN_ROOT`, `DPM_RUNS_DIR`, `DPM_ARTIFACT_DIR`, `DPM_BINDING`) → `~/.agentdata/config.json` (`dpm.*`) → `AGENTS.md` facts.
- Output rows follow the format policy: full findings live in the TSV `meta.path` names; script over them, never read `job-manifest.json` into context.

Reference: `references/dpm-contract.md` (run-root layout, version markers, resolution rules, route buckets, job manifest schema, lineage fields, refusal codes, rebinding, the assumptions to confirm against the hand-back document).
