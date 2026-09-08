---
name: content-understanding-extract
description: "Use to extract document fields with an Azure AI Content Understanding (Microsoft Foundry) analyzer — when an analyzer already defines the field schema, or when label-matching has failed. Inspect analyzers, try one on a document, then run it over a DPM manifest. Never reports a service failure as a missing field."
---
# Content Understanding: analyzer-driven field extraction

Prereq: the service is configured (`ad-doctor` shows `content_understanding` rows, not `skip`) **and** an analyzer exists. Not configured → `ad-setup --only content_understanding`. No analyzer → `friction-log` type `missing-info`: analyzers are authored in the Foundry portal, not here. STOP.

**The one thing that is different from `dpm-field-extraction`.** There, the field list is your input and `hint` is the label to search for. Here **the analyzer holds the schema** and your `hint` is ignored. So the two schemas can disagree while everything still "works", and the result reads as `not_found` on every row — which looks exactly like "the documents do not contain these fields". Check the two lists against each other **before** the run, at step 1. This is the failure mode of this skill.

## 1. See what the resource has, and what one analyzer declares

```
ad-foundry analyzers list
ad-foundry analyzers get <analyzer_id>
```

`fields: 0` means a content-only analyzer: it extracts text and layout but declares no field schema, so field extraction against it finds nothing. That is a wrong-analyzer answer, not an empty-document one.

## 2. Try it on one real document before running a batch

```
ad-foundry analyze --file <path> --analyzer <analyzer_id> --out .agent/out/<name>-raw.json
```

Read the `confidence` column. A value with low confidence is a value a reviewer must confirm, not a value to report. `--out` keeps the raw result: cite that path when a value is questioned.

## 3. Run it over a DPM manifest

Same command, same schema file, same output as `dpm-field-extraction` — only the engine differs:

```
ad-dpm extract-fields --manifest <governed-dir>/<run_id>/job-manifest.json \
  --schema .agent/in/<run_id>-fields.json --engine azure-content-understanding
```

- `--analyzer <id>` overrides the configured default. `--min-confidence 0.5` lowers the floor below which a value is reported `ambiguous` rather than `found` (default 0.7).
- Field names match across casing and separators: `loan_amount` in your schema matches `LoanAmount` in the analyzer.
- A `not_found` row's `detail` names the fields the analyzer **did** return. If that list is nothing like your schema, you have the wrong analyzer — stop and fix that, do not report absent fields.

## 4. Read the counts the same way

`found` · `ambiguous` (here: below the confidence floor) · `not_found` · `no_text` · `needs_ocr_review`.

`needs_ocr_review` is still decided before this engine runs: OCR-routed documents are **not sent to the service** and are **not extracted from**. Never report them as missing.

## 5. Refusals are refusals, never empty results

`refused: content_understanding_failed` means the service said nothing about the document. Report it as a run that did not happen. Never let it become "the field was not found" — that is a claim about the document that nobody made. `refused: no_analyzer` → step 1.

## 6. Finish

`state-update`: artifacts (the review file, and any `--out` raw result). Hand off → `dpm-field-extraction` when the same run should also be read with plain label matching for comparison; else `router`.

## Costs and privacy — say these out loud before a batch

Every document is a billable request and **leaves the machine**. `ad-dpm extract-fields` sends one request per document, not per field. If the documents are sensitive, that is a decision for the requester, not for you: `friction-log` type `missing-info` and STOP.

§ Endpoint, auth, analyzers, the result shape, and what the SDK actually requires: `references/content-understanding.md`.
