---
name: bitbucket-pr
description: "Use when code or model changes are ready for review — to branch, commit, push, and open a Bitbucket pull request via pncli. Works with or without a ticket. Never merges."
---
# Open a PR (never merge)

1. `state.branch` must be set. `state.active_ticket` too, unless the work is **untracked**: the `ticket_policy` fact is `optional` (or absent) and the router recorded the `none` assumption. Both missing → `session-bootstrap`. STOP.
2. Look before you branch (AGENTS.md rule 16): `git for-each-ref refs/heads --format=%(refname:short)`. A branch carrying `<KEY>` already exists → it is this ticket's: continue on it when it is the current branch, else `ad-state ask` the operator to check it out and STOP -- never a second branch per ticket. None → `git checkout -b <branch>`; untracked work branches as `<type>/<slug≤4 words>` (`chore/rename-margin-measure`). Six or more local branches (`fleet.branches.warn`) → `git branch --no-merged <default>`, name them in one line, `ad-state ask --assume "continue on <branch>"`, and continue. `git status` — only intended files staged.
3. Commit: `<type>: <KEY> <what>` where type ∈ `feat|fix|docs|chore`; untracked work: `<type>: <what>`. One commit per logical change.
4. `git push -u origin <branch>`.
5. Pinned PR verb: `TODO(HANDOFF: pin after pncli bitbucket --help)`; the operator captures it with `ad-pncli capture-help` (#498) in their own terminal. If unpinned, run `pncli bitbucket --help` once.
6. `pncli bitbucket <pr-create verb> --title "<KEY>: <summary>" --description-file .agent/out/<KEY>-pr.md --dry-run`. Untracked: `--title "<summary>"`, the file is `.agent/out/pr.md`, and its first line says `No ticket: <why in ≤ 12 words>`. Read `"ok"`. False → `friction-log`.
7. Re-run without `--dry-run`. Capture PR URL. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
8. Move the ticket: invoke `jira-transition` with `--to review --comment "PR: <URL>"`. It asks Jira what this
   issue type can do — a Task and a Story do not share a workflow, so never write a status name here.
   Untracked work has no ticket to move: skip this step and say so in one line.
9. `state-update`: `pr_url`, `phase=pr_open`. Print URL. STOP. A human merges.
