---
name: confluence-publish
description: "Use to write findings, runbooks, or work documentation to Confluence. Use after UAT findings exist, after a deploy, or when the user asks to document work. Deterministic extraction first, one narrow model pass, scripted publish."
---
# Confluence publish

1. Source of truth is a file under `.agent/out/` (e.g. `<KEY>-uat-findings.md`). No file → go back to the skill that produced the data. Do not compose from memory.
2. Space + parent come from `AGENTS.md` (`confluence_space`, `confluence_parent`). Missing → `friction-log` type `missing-info`. STOP.
3. Build the page body as **HTML** (Confluence storage format — `pncli` takes the body inline, not markdown). Title `<KEY> — <summary>`; sections `Context`, `Method`, `Findings`, `Recommendation`, `Artifacts` (list the `path`s). Save as `.agent/out/<KEY>-confluence.html`, ≤ 60 lines:

```html
<h2>Context</h2><p>…</p>
<h2>Findings</h2><ul><li>…</li></ul>
<h2>Artifacts</h2><ul><li><code>.agent/out/<KEY>-uat-findings.md</code></li></ul>
```

4. Dry run:

```
ad-pncli raw --body-file .agent/out/<KEY>-confluence.html confluence create-page --space <space> --parent <id> --title "<KEY> — <summary>" --dry-run
```

   `--body-file` reads that file and hands it to pncli as one `--body <html>` argument. Never put the HTML on the command line yourself: quotes, newlines, `<`, `>` and `&` do not survive a shell, and a page is longer than a command line allows.
5. Read `"ok"`. `false` → print `meta.hint`, fix, retry once. Second failure → `friction-log` type `tool-error`. STOP.
6. `--space`, `--parent` and `--title` are not confirmed against this pncli build (only `create-page --body` is). An `unknown option` error → run `pncli confluence create-page --help` ONCE, use the names it lists, and report the working command so it can be pinned here. Never guess a second time.
7. Re-run without `--dry-run`. Capture the URL from the result.
8. Comment on Jira: `ad-pncli raw jira <comment verb> --key <KEY> --body "Documented: <URL>"` (`--dry-run` first; pncli options are named, never positional).
9. `state-update`: `confluence_url`, `phase=documenting`. Hand off → `bitbucket-pr` if code changed, else `router`.
