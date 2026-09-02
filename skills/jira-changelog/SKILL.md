---
name: jira-changelog
description: Use for field history, sprint reports, committed vs completed points, "when did X change", or anything current Jira values cannot answer. Uses ad-jira (Jira REST reusing the pncli token). For current-state lists use ad-pncli jira search instead.
---
# Jira changelog and sprint replay

Prereq: `ad-doctor` row `pncli / jira auth` is not `fail`. Failing → print its hint, STOP.

1. Once per Jira instance: `ad-jira fields --like sprint` and `ad-jira fields --like point`; then `ad-jira fields --pin` (stores the Sprint and Story Points field ids in the global config). Two plausible point fields with different meanings → `friction-log` type `missing-info`. STOP.
2. Field history: `ad-jira changelog <KEY> [<KEY>…] --fields status,Sprint,"Story Points" [--since 2025-01-01]`, or `--jql "<JQL>"` instead of keys. Columns: key, changelog_id, created_utc, author, field, field_id, from_id, from_str, to_id, to_str. Use `*_id` for Sprint and status (stable ids), `*_str` for points.
3. Sprint numbers: `ad-jira sprints --board <jira_board_id> --state closed` to find the id, then
   `ad-jira sprint-replay --sprint <id> --board <jira_board_id> --jql "project = <KEY> AND updated >= '<sprint start - 1d>'"`.
   The `--jql` widening is required to see punted issues: JQL `sprint = <id>` no longer matches issues removed from the sprint.
4. Read `summary`: `committed_points` (estimate at sprint start), `completed_points` (credited at close by default; pass `--points-at commit` only when the ticket says so, and state the choice in findings), `added`, `punted`, `re_estimated`, `estimated_mid_sprint`, `carried_over`, `reopened`, `completed_in_another_sprint`. `provisional: true` means the sprint is still active.
5. Cross-check only when asked: `--compare-sprintreport`. A non-zero delta lists `keys_only_in_report` / `keys_only_in_replay`; Jira's Sprint Report is a hint, the replay rows are the evidence.
6. `rule: 6` → script over `path`, never read rows. `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`.
7. `state-update` with the paths. Hand off → `uat-report-visual` when comparing to a report, `confluence-publish` when documenting, else `router`.

Reference: `references/jira-changelog.md` (endpoints, response shapes, Sprint field semantics, replay rules, Cloud vs Data Center, limits).
