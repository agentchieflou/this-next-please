---
name: perf-optimize
description: "Use to make code faster: one covered finding at a time, inside an approved graph, behind the guard, proven faster by test-regress. Reverts anything it cannot prove."
---
# Perf optimize

Make the code faster — but only after a human has approved the understanding, only inside code tests
cover, and only when the numbers say it worked. Every gate below is a command that returns `ok`, not
a promise you make to yourself.

`ad-graph approve` is the human's and you must **never approve yourself**. **No `--allow`, ever** — that override
belongs to a human too. Anything you cannot prove, you revert.

1. `ad-graph status`. Not `approved: current` → invoke `codebase-map`; STOP.
2. `ad-test run`. Red suite → `friction-log` type `contract`; STOP. You cannot tell what you broke
   if it was already broken. Then `ad-test coverage`, so `covered` is measured and not stale.
3. `ad-graph findings --covered-only --top 5`. Pick **one** row: highest `leverage`, `confidence`
   at least `med`. Print it. Empty list → print the top three `ad-graph findings --kind
   untested-hub` rows and hand off to `test-cover`; STOP. Nothing uncovered may be touched here.
4. `ad-test bench --node <id> --label before`. Keep the path it prints; that is the baseline.
5. `ad-state set phase=optimizing`. Read the node with `ad-graph node <id>` and read only its
   `where` range plus its direct callees. Make the **smallest** change that removes the pattern the
   finding's `hint` names — the fix patterns are the table in `docs/code-graph.md` §Checks. Never
   change a public signature. Never touch a second node while you are in there.
6. `ad-graph guard`. `ok: false` → `git checkout -- <file>`, print the refused rows, STOP.
7. Invoke `test-regress`. It must print `regress: ok`. Anything else → revert the change and STOP,
   quoting its numbers. A `same` verdict is inside the noise floor: that is a no-op, not a win.
8. Commit on the ticket branch: `perf: <KEY> <node> <what> (<before_ms>→<after_ms>)`.
   `ad-state set phase=validating`. Then either return to step 3 for the next finding, or hand off
   to `bitbucket-pr` when the ticket is done. **Five findings per session maximum**, then report and
   STOP.

If a gate refuses twice for the same node, stop working on that node and say so. Lowering a
threshold, deleting a test, or widening a selector to get past a gate is the one thing this skill
must never do.
