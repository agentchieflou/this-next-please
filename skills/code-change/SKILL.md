---
name: code-change
description: "Use for a change to this repository's own code that no domain skill covers: fix a bug, patch a loader, add a flag, refactor a function, make it do X. Guard first, the smallest diff, tests before and after, commit on the ticket's branch."
---
# Code change

The fallback for ordinary code work. Domain skills come first — a measure is `tmdl-edit`, a slow path
is `perf-optimize` — and this skill is what is left: a named change to named code.

1. **Scope.** Name the file(s) and symbol(s) the change touches, and the behaviour that proves it is
   done, in one line each. Cannot name them from the request → `ad-state ask "<which file / what
   behaviour>" --want value`, `friction-log` type `missing-info`. STOP. A safe, reversible default
   settles it (a test file beside the module, an obvious name) → `ad-state ask "<assumption>"
   --assume "<default>"`, one line, CONTINUE.
2. **Branch** (AGENTS.md rule 16): `git for-each-ref refs/heads --format=%(refname:short)`. A branch
   carrying the ticket key exists → continue on it if it is checked out, else `ad-state ask` the
   operator to check it out. STOP. None → `git checkout -b feature/<KEY>-<slug≤4 words>`
   (untracked: `fix/<slug>`), then `ad-state set branch=<branch>`.
3. **Guard** (AGENTS.md rule 14): `ad-graph status`. Not `approved: current` → invoke `codebase-map`;
   STOP. Then `ad-test run --snapshot before`. A red suite before you touched anything →
   `friction-log` type `contract`; STOP. Zero tests collected is not green: `friction-log` type
   `contract` naming `test_cmd`; STOP.
4. **Edit** the named symbols only (`ad-state set phase=editing` first). The smallest change that does what step 1 says. Never change a
   public signature the request did not name, never touch a second module "while you are in there".
5. `ad-graph guard`. `ok: false` → `git checkout -- <file>`, print the refused rows. An uncovered node
   → hand off to `test-cover` for it, then come back here. STOP otherwise.
6. **Prove it.** `ad-test run --snapshot after`, then `ad-test run --compare <before.tsv> <after.tsv>`
   must be `ok: true`. Add or extend one test that fails without the change and passes with it. A
   regression → revert the edit, quote the row, STOP. Two failed attempts → `friction-log`; STOP.
7. Commit `fix: <KEY> <what>` or `feat: <KEY> <what>` (untracked: no key). `ad-state set
   phase=validating`. Print the files changed and the test that proves it. Hand off → `bitbucket-pr`.
