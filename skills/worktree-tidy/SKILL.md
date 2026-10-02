---
name: worktree-tidy
description: "Use to clean up a dirty working tree: uncommitted changes, a dirty worktree, 'stash this', 'what do I do with these changes'. Surveys with ad-git tidy, recommends one option (most recent branch first; on a conflict, least tech debt), asks the operator, then applies it. Never discards."
---
# Worktree tidy

A dirty tree gets one decision: **commit** the changes on the branch they were made on, **branch**
them onto a new `wip/` branch, **stash** them, or **skip**. Nothing here discards work, and the
operator decides; the map's *clean up* guide is the same decision on a page.

1. `ad-git tidy --dry-run`. `dirty: false` → print `clean — nothing to tidy` and STOP. Read
   `recommended`, `why`, `options`, `plan_id`, and the `overlaps` table if there is one.
2. Ask, with the recommendation as the default — never apply on your own reading:
   `ad-state ask "<count> uncommitted files on <branch>: <why>" --choice commit --choice branch
   --choice stash --choice skip --default <recommended>`. Print the question in one line. STOP.
3. On the operator's answer (session-bootstrap records it): `ad-git tidy --apply <their choice>
   --plan <plan_id>` (add `--message "<msg>"` for commit or branch; Conventional Commits, AGENTS.md
   rule 9). In a fleet it waits on the approval gate.
   - `refused: changed` → the tree moved since the survey: back to step 1, once. A second
     `changed` → `friction-log` type `loop`. STOP.
   - `refused: protected_branch` → offer `branch` instead (step 2). `refused: commit_refused` →
     the repository's own commit hook said no: print its words, offer `stash` (step 2). Never
     `--no-verify`.
   - `refused: mid_operation` → a merge or rebase is half done: `ad-state ask "finish or abort the
     <operation> in a terminal?" --want access`. STOP.
4. Print what was done and its `undo` line. `state-update` with `branch=<branch>` when the choice
   was `branch`. Return to `router`.

Several dirty checkouts: take them **most recent first** (the map's guide orders them for you), one
decision each. Discarding changes is never offered here; if the operator wants that, it is theirs to
do in a terminal.
