---
name: dpm-router
description: "Domain sub-router for document pipelines: DPM run handoff, field extraction, Content Understanding analyzers, organizing a folder of documents. Does no work itself."
---
# DPM router

1. Match the request to ONE row. First match wins. The contract row comes first: a run has to be taken in before anything is extracted from it.

| Request mentions | Invoke |
|---|---|
| DPM run, hand back / handoff, orchestrator.db, selection manifest, text_analysis, job manifest, OCR routing, native text, "take this run in" | `dpm-consumer-integration` |
| extract named fields from DPM documents ("pull the borrower and amount out of these"), per-job field list, review file | `dpm-field-extraction` |
| Content Understanding, Foundry analyzer, "use the AI model to read these documents", field extraction that label matching could not do | `content-understanding-extract` |
| sort / organize / file a folder of documents, "where should these go", a delivery to arrange before a run | `file-organize` |
| start / resume / stop / reconcile a DPM run, "is the run still going" | `run-control` |

2. Preconditions, each a command: `ad-dpm locate` answers for the run the request names (facts `dpm_run_root` or `dpm_runs_dir`); `refused: not_a_run_root` → the leaf skill's own step handles it, route anyway. A field list or a rule set is an **input**: none supplied and none agreed → the leaf skill asks, never guesses.
3. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
4. No match after reading the table twice → invoke `research-spike`. STOP.
