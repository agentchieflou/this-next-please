---
name: confluence-publish
description: "Use to write findings, runbooks, or work documentation to Confluence. Use after UAT findings exist, after a deploy, or when the user asks to document work. Deterministic extraction first, one narrow model pass, scripted publish."
---
# Confluence publish

Confluence does not render Markdown. `ad-confluence` converts it; you never write the page body yourself.

1. Source of truth is a Markdown file under `.agent/out/` (e.g. `<KEY>-uat-findings.md`). No file → go back to the skill that produced the data. Do not compose from memory.
2. Space + parent come from `AGENTS.md` (`confluence_space`, `confluence_parent`). Missing → `friction-log` type `missing-info`. STOP.
3. Missing sections (`Context`, `Method`, `Findings`, `Recommendation`, `Artifacts` with the `path`s) → add them **to the Markdown file**, ≤ 60 lines total. Never hand-write HTML: `ad-confluence` refuses a body it cannot parse, and `ad-pncli` refuses to post one that is still Markdown.
4. Build the body:

```
ad-confluence html .agent/out/<KEY>-uat-findings.md --out .agent/out/<KEY>-confluence.html
```

   Read `meta`. `title` is the file's first `#` heading, lifted out so the page does not repeat it — use that string in step 5, or pass `--title "<KEY> — <summary>"` to set it. `blocks` counts what was recognised: `paragraph` alone on a file with headings and bullets means the Markdown is malformed, so fix the source file. `ok: false` → print `hint`, fix the source, retry once, then `friction-log` type `tool-error`. STOP.
5. Dry run:

```
ad-pncli raw --body-file .agent/out/<KEY>-confluence.html confluence create-page --space <space> --parent <id> --title "<title>" --dry-run
```

   `--body-file` hands the file to pncli as one `--body <html>` argument. Never put the body on the command line yourself: quotes, newlines, `<`, `>` and `&` do not survive a shell, and a page is longer than a command line allows.
6. Read `"ok"`. `false` → print `meta.hint`, fix, retry once. Second failure → `friction-log` type `tool-error`. STOP.
7. `--space`, `--parent` and `--title` are not confirmed against this pncli build (only `create-page --body` is). An `unknown option` error → run `pncli confluence create-page --help` ONCE, use the names it lists, and report the working command so it can be pinned here. Never guess a second time.
8. Re-run without `--dry-run`. Capture the URL from the result. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
9. Comment on Jira: `ad-pncli raw jira <comment verb> --key <KEY> --body "Documented: <URL>"` (`--dry-run` first; pncli options are named, never positional).
10. `state-update`: `confluence_url`, `phase=documenting`. Hand off → `bitbucket-pr` if code changed, else `router`.
