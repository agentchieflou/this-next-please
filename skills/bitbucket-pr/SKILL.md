---
name: bitbucket-pr
description: "Use when code or model changes are ready for review — to branch, commit, push, and open a Bitbucket pull request via pncli. Never merges."
---
# Open a PR (never merge)

1. `state.active_ticket` and `state.branch` must be set. Missing → `session-bootstrap`. STOP.
2. `git checkout -b <branch>` (or `git checkout <branch>` if it exists). `git status` — only intended files staged.
3. Commit: `<type>: <KEY> <what>` where type ∈ `feat|fix|docs|chore`. One commit per logical change.
4. `git push -u origin <branch>`.
5. Pinned PR verb: `TODO(HANDOFF: pin after pncli bitbucket --help)`. If unpinned, run `pncli bitbucket --help` once.
6. `pncli bitbucket <pr-create verb> --title "<KEY>: <summary>" --description-file .agent/out/<KEY>-pr.md --dry-run`. Read `"ok"`. False → `friction-log`.
7. Re-run without `--dry-run`. Capture PR URL.
8. Move the ticket: invoke `jira-transition` with `--to review --comment "PR: <URL>"`. It asks Jira what this
   issue type can do — a Task and a Story do not share a workflow, so never write a status name here.
9. `state-update`: `pr_url`, `phase=pr_open`. Print URL. STOP. A human merges.
