---
name: pbi-observe
description: "Use to observe live Power BI models over the Analysis Services port: query traces, DMVs, and page-cost benchmarking. Diagnoses slow visuals, query performance, and memory usage before and after edits."
---
# Observe the live model over Analysis Services

Inputs: `pid` or `server` (AGENTS.md, `.agent/desktop.json`, or `ad-pbip desktop status`), optional `page` or visual.

1. Pick the right tool for the question:
   - "Why is this page slow?": `ad-pbip page-cost --pid <pid> --page "<page>"` — navigates, captures traces, and reports query time per visual and page total.
   - "Which query did this visual run?": `ad-pbip trace report <trace.jsonl>` or run `ad-pbip visual-query --visual "<title>"` for isolated evaluation.
   - "What are the dependencies?": `ad-pbip dmv deps` (or `ad-pbip refs --live`).
   - "How much memory/storage does this table or column use?": `ad-pbip dmv segments`.
   - "What active sessions are connected?": `ad-pbip dmv sessions`.

2. Active query tracing:
   - Start: `ad-pbip trace start --pid <pid> --seconds 60 --out .agent/out/trace.jsonl`.
   - Perform actions in Desktop (click slicers, change pages, refresh visual).
   - Report: `ad-pbip trace report .agent/out/trace.jsonl`. Correlates queries to visuals and categorizes engine mode (`vertipaq`, `directquery`, `formula`).

3. Verification of DAX optimizations:
   - Measure baseline: `ad-pbip page-cost --pid <pid> --page "<page>" > .agent/out/before-cost.tsv`.
   - Apply measure or relationship edit.
   - Measure after: `ad-pbip page-cost --pid <pid> --page "<page>" > .agent/out/after-cost.tsv`.
   - Prove improvement: `ad-diff .agent/out/before-cost.tsv .agent/out/after-cost.tsv`. Never claim optimization without quantified latency delta.

4. Stop conditions:
   - Trace or DMV script exits non-zero twice in a row → invoke `friction-log` with type `tool-error`. STOP.
   - `.agent/desktop.json` is missing → have the PBIP opened in Desktop first, then read the `external_tools` row of `ad-pbip capabilities` and ask for the one gesture its `via` names: `ribbon:machine`, press *External Tools → agentdata*; `te2:local`, in Tabular Editor pick the instance, then *Hand off to agentdata*; `zorder`, click the window you mean and run `ad-pbip handoff --active`; `file`, name the document with `ad-pbip handoff --file <name>`. STOP.
