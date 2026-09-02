---
name: uat-report-visual
description: Use when a business user says the numbers on a Power BI chart are wrong and hands over a document or CSV of expected values — "the committed points on the sprint chart don't match", "this table should show 42". Reproduces the visual on every tier (live Jira > Jira history in Teradata > Power BI), classifies each difference, and writes the findings. Never argues from memory or from one tier.
---
# UAT of a report visual from a document

Inputs: ticket key, the document/CSV (copy into `.agent/in/`), the chart (title, page or visual id), optionally the table/measure. Prereq: `pbip-projection` ran; `ad-doctor` ok. Missing the chart or the document → `friction-log` type `missing-info`. STOP.

1. Recipe: `ad-uat plan --visual "<chart title>" --ticket <KEY> --expected .agent/in/<file> --window <start>,<end>`. Read `measures` (with their column dependencies), `sources` (warehouse objects behind the visual) and `steps`. It wrote `.agent/sql/<KEY>-uat-hist.sql` and `-cov.sql`: open them once and fix column names to the real history table (`jira_hist_table` fact) — the templates assume `PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS, STORY_POINTS`.
2. Expected: `ad-uat expect .agent/in/<file>` → note `path` and `grain` (key, metrics). The document is a **claim to test**, never a tier.
3. Tier 3 (Power BI): Desktop open → `ad-pbip desktop` for the port → `ad-pbip visual-query --visual "<title>" --server localhost:<port>`; or the service via `dax-studio-export`. Note `path`. A DAX error here is itself a finding (report broken).
4. Tier 2 (warehouse): `ad-td --sql-file .agent/sql/<KEY>-uat-hist.sql --name hist` and `... -cov.sql --name cov`. Follow `teradata-query` rules (lint findings, warnings).
5. Tier 1 (live Jira): points/sprint questions → `jira-changelog` (`ad-jira sprint-replay`, its per-issue rows are the truth for committed/completed); otherwise `ad-pncli jira search` with the same JQL scope and window.
6. `ad-uat reconcile --expected <e.tsv> --jira <j.tsv> --hist <h.tsv> --pbi <p.tsv> --key <grain key> --cols <metrics> --window <start>,<end> --hist-coverage <cov.tsv> --ticket <KEY>`. Grains must match: aggregate a finer tier with a ≤10-line script (`agentdata.AgentTable.read_tsv`) before reconciling; never compare by eye.
7. Read `counts`. `history-gap` = the warehouse cannot reproduce Jira (missing rows / null points) — report it, never "fix" data to match. `report-bug` → hand off `tmdl-edit`. `expectation-wrong` → answer the requester with the reproduced numbers and which tier produced them. `unexplained` → supply what the note asks for and re-run.
8. Findings file is `.agent/out/<KEY>-uat-findings.md` (written by the command; do not rewrite it, append a `## Context` paragraph at most). `state-update`: `phase=documenting`, artifacts. Hand off → `confluence-publish`.

References: `references/uat-method.md` (tiers, classification rules, grain matching, the inconsistency the user asked for), `references/uat-sql-templates.md` (history-as-of, coverage, points-as-of SQL for Teradata).
