---
name: test-cover
description: "Use to write characterization tests that pin an uncovered node's current behavior, so the guard will allow a later change. Touches test files only; never edits a source file."
---
# Test cover

Pin what a node does today so a later change has to prove it did not break it. The code is assumed
correct as-is: a golden test that fails later means behavior changed, not that the test is wrong.

This skill writes **test files only**. It must **never edit a source file**. `ad-graph guard
--tests-only` proves that mechanically in step 6.

1. Input: one node id, from `perf-optimize` or from the user. Run `ad-graph status`. Not
   `approved: current` → invoke `codebase-map`; STOP. Tests must pin behavior a human has read.
2. `ad-graph node <id>` — read `where`, `callers`, `tests`, and every `io`-tagged callee.
   `ad-test coverage --node <id>` — read `pct` and the `missing` lines. Those lines are the target.
3. Gather inputs, cheapest source first, and stop at the first that yields two:
   1. `ad-graph refs <id>` — each row carries the call site's `where`. Read **only those lines** and
      take the literal arguments the callers already pass.
   2. Examples in the node's own docstring.
   3. Fixtures already under the repo's test directory for the same module.
   **Never invent** domain data, and never reach a real source (`AGENTS.md` rule 4): stub every
   `io`-tagged callee from step 2. No inputs found → `friction-log` type `missing-info` asking the
   human for two representative inputs; STOP.
4. `ad-test detect` — use the runner and the naming the graph already indexes as `test` nodes. Read
   `references/characterization.md` §<framework> for that runner's shape, stubbing, probe and
   pitfalls. Write **one** test file: one test per input, asserting the exact current result. Get
   each expected value from a probe run, never by predicting it — the probe pattern is in the
   reference.
5. `ad-test run --select <id>` → every new test passes. `ad-test coverage --node <id>` → `missing`
   is shorter and `pct` ≥ `graph_min_coverage`. Short of it → add inputs that reach the lines still
   listed. Two rounds maximum, then `friction-log` with the remaining `where` rows; STOP.
6. `ad-graph guard --tests-only` → `ok: true`. Refused → `git checkout -- .`, delete the files you
   added, `friction-log` type `contract`; STOP. A refusal here means a source file changed.
7. Commit `test: <KEY> characterize <node> (<n> cases, <pct>%)`. Run `ad-graph build` so the new
   test nodes and coverage edges exist. Hand off: back to `perf-optimize` if it invoked you, else
   `bitbucket-pr`.

A bug you notice while characterizing is a ticket, not a side effect. Record it under
`## Open questions` in `.agent/graph/understanding.md` and pin the buggy behavior as it is.
