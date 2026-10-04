---
name: code-router
description: "Domain sub-router for work on a repository's own code: map it, cover it, change it, make it faster, prove nothing broke, tidy the worktree. Does no work itself."
---
# Code router

1. Match the request to ONE row. First match wins. The guard decides more than the words do: every editing row below runs behind `ad-graph guard` (AGENTS.md rule 14), and an unapproved graph sends you to the first row whichever row matched.

| Request mentions | Invoke |
|---|---|
| new to this repo, getting started, onboard, "what is this repository for", project context, refresh the getting-started page | `project-onboard` |
| map the codebase, how does this repo work, what calls what, unfamiliar code, "explain this module" | `codebase-map` |
| write tests for, cover, characterization test, no tests for, "pin the current behaviour" | `test-cover` |
| did I break anything, is it faster, before and after, regression, "prove it" | `test-regress` |
| slow, make it faster, performance, optimize, hot path, N+1 | `perf-optimize` |
| clean up the worktree, dirty tree, "stash this", "what do I do with these changes", uncommitted changes | `worktree-tidy` |
| fix, patch, add a flag, refactor, rename, "make it do X", a bug with a named symptom, a failing test to fix, update the README / docs / a docstring for a change, a change to named code | `code-change` |

2. Preconditions, each a command: `ad-graph status` says `approved: current` before any row but `codebase-map` and `worktree-tidy` edits anything -- the leaf skill checks it; never route around it. `ad-test run` must collect tests (`no_tests` is a `contract` friction, not a green suite).
3. **Domain first.** A request that names Power BI, DAX, a measure, a visual or a warehouse went past the top table's rows for them (a measure is `tmdl-edit`, a visual is `pbi-report-author`, a SQL file is a query skill): send it back → `router` rather than treating it as code.
4. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
5. No match after reading the table twice → invoke `research-spike`. STOP.
