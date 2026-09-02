---
name: confluence-publish
description: "Use to write findings, runbooks, or work documentation to Confluence. Use after UAT findings exist, after a deploy, or when the user asks to document work. Deterministic extraction first, one narrow model pass, scripted publish."
---
# Confluence publish

1. Source of truth is a file under `.agent/out/` (e.g. `<KEY>-uat-findings.md`). No file → go back to the skill that produced the data. Do not compose from memory.
2. Build the page body: title `<KEY> — <summary>`; sections `Context`, `Method`, `Findings`, `Recommendation`, `Artifacts` (list `path`s). Save as `.agent/out/<KEY>-confluence.md`. ≤ 60 lines.
3. Space + parent come from `AGENTS.md` (`confluence_space`, `confluence_parent`). Missing → `friction-log` type `missing-info`. STOP.
4. Pinned verb: `TODO(HANDOFF: pin after pncli confluence --help)`. If unpinned, run `pncli confluence --help` once.
5. `pncli confluence <create-or-update verb> --space <space> --parent <id> --title "<title>" --body-file .agent/out/<KEY>-confluence.md --dry-run`. Read `"ok"`.
6. Execute. Capture URL. Comment on Jira: `pncli jira <comment verb> <KEY> "Documented: <URL>"` (`--dry-run` first).
7. `state-update`: `confluence_url`, `phase=documenting`. Hand off → `bitbucket-pr` if code changed, else `router`.
