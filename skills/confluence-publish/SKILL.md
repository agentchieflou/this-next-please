---
name: confluence-publish
description: "Use to write findings, runbooks, or work documentation to Confluence. Use after UAT findings exist, after a deploy, or when the user asks to document work. Deterministic extraction first, one narrow model pass, scripted publish."
---
# Confluence publish

`ad-confluence publish` builds the page from Markdown and runs pncli's page verb behind the approval gate; `ad-doctor`
row `pncli / pncli launcher` must not be `fail`. Confluence does not render Markdown: you never write the page body yourself.

1. Source of truth is a Markdown file under `.agent/out/` (e.g. `<KEY>-uat-findings.md`). No file → go back to the skill that produced the data. Do not compose from memory.
2. Space + parent come from `AGENTS.md` (`confluence_space`, `confluence_parent`). Missing → `friction-log` type `missing-info`. STOP.
3. Write the page source to `.agent/out/<KEY>-confluence.md` (the wrap-up republishes from that file). Missing sections (`Context`, `Method`, `Findings`, `Recommendation`, `Artifacts` with the `path`s) → add them **to that Markdown file**, ≤ 60 lines total. Never hand-write HTML: `ad-confluence publish` refuses a source that is not Markdown.
4. Dry run:

```
ad-confluence publish .agent/out/<KEY>-confluence.md --dry-run
```

   The title is the file's first `#` heading (`--title "<KEY> — <summary>"` overrides it); the page this ticket already has (`state.confluence_url`) → add `--overwrite <page id>`. The body goes to pncli as one argument; never put it on a command line yourself.
5. Read `"ok"`, then `action`, `title`, `space`, `parent`, `warnings`. `refused: not_pinned` → the operator has not pinned pncli's page verb yet: print `hint` verbatim, `friction-log` type `missing-info`, STOP. Any other `false` → print `meta.hint`, fix the source, retry once. Second failure → `friction-log` type `tool-error`. STOP.
6. Re-run without `--dry-run`. Capture `url` from the result. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
7. Comment on Jira: `ad-jira comment <KEY> --body "Documented: <URL>" --dry-run`, read `"ok"`, then run the same without `--dry-run`. `refused: approval_timeout` or `approval_denied` → as step 6.
8. `state-update`: `confluence_url`, `phase=documenting`. Hand off → `bitbucket-pr` if code changed, else `router`.
