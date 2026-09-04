---
name: test-regress
description: "Use to prove a change broke nothing and actually made the code faster, by comparing test results and timings before and after with ad-diff. Returns a verdict; never edits anything."
---
# Test regress

The proof step. "Nothing broke" and "it is faster" are claims, and this skill turns both into
measurements compared mechanically (`AGENTS.md` rule 6 — never compare in your head).

This skill **never edits** a file and never re-runs a step "to see if it passes this time"
(`AGENTS.md` rule 11): the same command twice with the same arguments is a stop condition, not a
retry. It returns a verdict; the caller decides to commit or revert.

1. Input: a node id, and a worktree with the change already applied and stashable. Uncommitted
   changes must be the change under test and nothing else — `git status --porcelain` first, and if
   it lists anything unrelated, `friction-log` type `contract`; STOP.
2. Baseline. `git stash push --include-untracked`, then:
   - `ad-test run --snapshot before`
   - `ad-test bench --node <id> --label before`
   - `ad-test coverage`  (writes the before coverage; copy it to `.agent/out/coverage-before.json`)
   Then `git stash pop`. If any of the three fails, `git stash pop` anyway, `friction-log`; STOP —
   the worktree must come back exactly as it was found.
3. After. `ad-test run --snapshot after`, `ad-test bench --node <id> --label after`,
   `ad-test coverage`.
4. Gate 1 — nothing broke. `ad-test run --compare <before.tsv> <after.tsv>` must be `ok: true`:
   zero `regression` rows, and no test that vanished. Any regression → FAIL.
5. Gate 2 — nothing lost coverage. `ad-test coverage --diff .agent/out/coverage-before.json`: no
   node's `pct` may have dropped. Any negative `delta` → FAIL.
6. Gate 3 — it is actually faster. `ad-test bench --compare <before.tsv> <after.tsv>` must report
   `verdict: faster` **and** `meets_min_speedup: true` (`graph_min_speedup`, default 1.10). A
   `same` verdict means the change is inside the noise floor: that is not a win, it is a no-op.
7. Print exactly one line and hand back to the invoking skill:
   - `regress: ok speedup=<S>x tests=<passed>/<total>`
   - `regress: FAIL <reason>` — one of `regression <test>`, `coverage dropped <node>`,
     `slower`, `same (within noise floor)`.

On FAIL the caller reverts. Do not attempt a fix here, and do not soften a gate to pass.
