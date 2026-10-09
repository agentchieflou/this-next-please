---
name: bitbucket-pr
description: "Use when code or model changes are ready for review — to branch, commit, push, and open a Bitbucket pull request with ad-git pr. Works with or without a ticket. Never merges."
---
# Open a PR (never merge)

`ad-git pr` runs pncli's PR verb behind the approval gate; `ad-doctor` row `pncli / pncli launcher` must not be `fail`.
1. `state.branch` must be set. `state.active_ticket` too, unless the work is **untracked**: the `ticket_policy` fact is `optional` (or absent) and the router recorded the `none` assumption. Both missing → `session-bootstrap`. STOP.
2. Look before you branch (AGENTS.md rule 16): `git for-each-ref refs/heads --format=%(refname:short)`. A branch carrying `<KEY>` already exists → it is this ticket's: continue on it when it is the current branch, else `ad-state ask` the operator to check it out and STOP -- never a second branch per ticket. None → `git checkout -b <branch>`; untracked work branches as `<type>/<slug≤4 words>` (`chore/rename-margin-measure`). Six or more local branches (`fleet.branches.warn`) → `git branch --no-merged <default>`, name them in one line, `ad-state ask --assume "continue on <branch>"`, and continue. `git status` — only intended files staged.
3. Commit: `<type>: <KEY> <what>` where type ∈ `feat|fix|docs|chore`; untracked work: `<type>: <what>`. One commit per logical change.
4. Push: `ad-git push --dry-run`, read `"ok"` (it names the branch, target and commits; a `refused` code says why not), then `ad-git push`. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`, as step 6. Never raw `git push`.
5. `ad-git pr --title "<KEY>: <summary>" --dry-run` (a draft; `--ready` when the operator asked for review now; `--overwrite <PR id>` when `state.pr_url` names this branch's PR). Untracked: `--title "<summary>"`. Read `"ok"`, then `action`, `source`, `target`, `draft`. `refused: not_pinned` → the operator has not pinned pncli's PR verb yet: print `hint` verbatim, `friction-log` type `missing-info`, STOP. Any other `false` → `friction-log`. Never a pncli write yourself: a fleet refuses it, and only `ad-git pr` passes the approval gate.
6. Re-run without `--dry-run`. Capture `url`. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
7. Move the ticket: invoke `jira-transition` with `--to review --comment "PR: <URL>"`. It asks Jira what this
   issue type can do — a Task and a Story do not share a workflow, so never write a status name here.
   Untracked work has no ticket to move: skip this step and say so in one line.
8. `state-update`: `pr_url`, `phase=pr_open`. Print URL. STOP. A human merges.
