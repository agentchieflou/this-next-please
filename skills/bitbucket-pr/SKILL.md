---
name: bitbucket-pr
description: "Use when code or model changes are ready for review — to branch, commit, push, and open a Bitbucket pull request with ad-git pr. Works with or without a ticket. Never merges."
---
# Open a PR (never merge)

`ad-git pr` runs toil's `bitbucket pr create|update` behind the approval gate -- or `github pr create|update` when the remote is on toil's GitHub connection's host; `ad-doctor` rows `toil / toil launcher` and that provider's connection must not be `fail`.
1. `state.branch` must be set. `state.active_ticket` too, unless the work is **untracked**: the `ticket_policy` fact is `optional` (or absent) and the router recorded the `none` assumption. Both missing → `session-bootstrap`. STOP.
2. Look before you branch (AGENTS.md rule 16): `git for-each-ref refs/heads --format=%(refname:short)`. A branch carrying `<KEY>` already exists → it is this ticket's: continue on it when it is the current branch, else `ad-state ask` the operator to check it out and STOP -- never a second branch per ticket. None → `git checkout -b <branch>`; untracked work branches as `<type>/<slug≤4 words>` (`chore/rename-margin-measure`). Six or more local branches (`fleet.branches.warn`) → `git branch --no-merged <default>`, name them in one line, `ad-state ask --assume "continue on <branch>"`, and continue. `git status` — only intended files staged.
3. Commit: `<type>: <KEY> <what>` where type ∈ `feat|fix|docs|chore`; untracked work: `<type>: <what>`. One commit per logical change.
4. Push: `ad-git push --dry-run`, read `"ok"` (it names the branch, target and commits; a `refused` code says why not), then `ad-git push`. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`, as step 6. Never raw `git push`.
5. `ad-git pr --title "<KEY>: <summary>" --dry-run` (`--overwrite <PR id>` when `state.pr_url` names this branch's PR). On Bitbucket the PR opens ready for review: toil's Bitbucket PR verb has no draft, and `--draft` is refused (`draft_unsupported`); on GitHub, `--draft` when the work is not ready for review. Untracked: `--title "<summary>"`. Read `"ok"`, then `provider`, `action`, `source`, `target`, `connection`, `command`. `refused: writes_off`, `no_connection` or `toil_not_ready` → toil cannot write it yet, a person's setup: print `hint` verbatim, `friction-log` type `missing-info`, STOP. Any other `false` → `friction-log`. Never a toil write yourself (`--allow-write`): a fleet refuses it, and only `ad-git pr` passes the approval gate.
6. Re-run without `--dry-run`. Capture `url`. `refused: approval_timeout` or `approval_denied` → `friction-log` type `missing-info` quoting the `approval` id and the `hint`. `refused: WRITE_DISABLED` → toil turned the write down after all (writes switched off since the dry run): print `hint` verbatim, `friction-log` type `missing-info`, STOP. Do not retry.
7. Move the ticket: invoke `jira-transition` with `--to review --comment "PR: <URL>"`. It asks Jira what this
   issue type can do — a Task and a Story do not share a workflow, so never write a status name here.
   Untracked work has no ticket to move: skip this step and say so in one line.
8. `state-update`: `pr_url`, `phase=pr_open`. Print URL. STOP. A human merges.
