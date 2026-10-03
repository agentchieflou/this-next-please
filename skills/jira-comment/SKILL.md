---
name: jira-comment
description: "Use to post a comment on a Jira issue without moving it — a finding, a question for the reporter, a status note, the path of an artifact. Dry-run first, one comment, never a transition."
---
# Comment on a Jira issue (never move it)

A comment is a write to a system of record (AGENTS.md rule 8): dry-run, read `"ok"`, then post. It is not a transition -- moving the issue is `jira-transition`'s, and a comment that *asks* the reporter something is still a comment, not a stop.

1. `state.active_ticket`, or the key the user named, is required. Missing → `session-bootstrap`. STOP.
2. Write the body to `.agent/out/<KEY>-comment.md`, ≤ 12 lines, plain text (Cloud renders it as ADF; no Markdown tables). Say what was found or asked, and name every `.agent/out/` path the reader will want. Never paste rows: more than 10 rows is a findings file, and the comment names it.
3. Dry run: `ad-jira comment <KEY> --body-file .agent/out/<KEY>-comment.md --dry-run`. Read `"ok"`. `refused:` → the `hint` names the fix (`not_found`, `jira auth`); `friction-log` type `tool-error`. STOP.
4. Post: the same command without `--dry-run`. In a fleet it waits on the approval gate; `approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id. Do not retry.
5. Print the comment id and the key in one line. `state-update` with `--artifact .agent/out/<KEY>-comment.md="comment posted on <KEY>"`. Return to `router`.
