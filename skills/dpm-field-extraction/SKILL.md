---
name: dpm-field-extraction
description: "Use to pull named field values (borrower, amount, dates — whatever the job defines) out of documents a DPM run has already routed, using a per-job field schema. Produces a review file with full DPM lineage. Never extracts from OCR-routed documents without saying so."
---
# DPM: field extraction

Prereq: a DPM job manifest exists (`ad-dpm convert` wrote it) **and** the requester has supplied, or agreed, the list of fields. No field list → `friction-log` type `missing-info`. STOP — guessing a field list is how the wrong values get into a report.

The field list is an **input**, never built in. It is a small JSON file per job:

```json
{"fields": [
  {"name": "borrower_name", "hint": "Borrower:", "required": true},
  {"name": "loan_amount",   "hint": "Loan Amount:", "required": true},
  {"name": "policy_no",     "hint": "Policy (No|Number)[.:]", "regex": true}
]}
```

1. Save it as `.agent/in/<run_id>-fields.json`. `hint` is the label to search near; `regex: true` makes it a pattern. `required` only affects `--strict`.
2. Run it:

```
ad-dpm extract-fields --manifest <governed-dir>/<run_id>/job-manifest.json --schema .agent/in/<run_id>-fields.json
```

3. Read `meta`. The counts are the whole picture:
   - `found` — one value, one place.
   - `ambiguous` — the label appears more than once with **different** values. Not a guess to accept: open the review file and check those documents by hand.
   - `not_found` — the label is not in the text. Check the hint against a real document before concluding the field is absent; a wrong hint and a missing field look identical.
   - `no_text` — routed as native text but the text is empty. That is a routing problem, not a missing field: report it to DPM.
   - `needs_ocr_review` — **not extracted at all.** The document is OCR-routed and its text quality is unverified. Never report these as missing: say they were not read.
4. `missing_required` in `meta` → a required field no document yielded. Say so plainly in the handover; do not substitute a value from anywhere else.
5. The review file is `.agent/out/<run_id>-field-extraction.md`. Cite its path. Never restate rows in chat.
6. `state-update`: artifacts. Hand off → `dpm-consumer-integration` when the values feed the consumer, else `router`. When `not_found` dominates because the documents have no consistent labels to search near, hand off → `content-understanding-extract`: an analyzer holds its own schema and does not need one.
7. Never write to the DPM run root — the command fingerprints it before and after and fails if anything changed. Never edit the manifest to make a field resolve.
8. Every row carries the document id, page and source sha256 from DPM's own lineage. If a value is questioned, that is what answers it — never construct a second provenance trail.

§ The manifest and its lineage fields: `skills/dpm-consumer-integration/references/dpm-contract.md`.
