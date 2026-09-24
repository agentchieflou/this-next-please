# GEMINI.md: for the agents that develop this repository

You are a **developer** of this repository. `AGENTS.md` beside this file is the rulebook this repository ships to
Luna, the agent it builds: do **not** run its session skills (`session-bootstrap`, `router`) and do not run
`ad-state` in this checkout. Of its rules, 8, 9, 11, 12, 13 and 16 bind you too: never merge or close on your own
initiative; Conventional Commits; stop on a repeated call or a repeated failure; write nothing outside your branch;
look before you branch.

## Read, in this order
1. Your issue. It names what to read first, what to build, the acceptance criteria and the tests.
2. `docs/developing-with-agents.md`: branches, the checkpoint ritual, the handover note, stop conditions, lanes.
3. The brief your issue's epic names (`docs/brief-post-ink-epics.md`) and the plan section your issue names.
4. `docs/testing-this-repo.md` for how the suite runs.

Never read `agentdata/fleet/static/app.js` (~61k tokens) or `agentdata/fleet/serve.py` (~36k) whole:
`grep -n` the symbol and read about 80 lines around it.

## Branch, PR, checkpoint
- One issue, one branch `gemini/<issue>-<slug>` from `main`. **Open no PR**: your branch is a car on the merge train
  (decision 7), and the conductor's one train PR carries `Closes #<issue>` for every car.
- After every acceptance criterion goes green: run the named tests, commit only what you meant, push, and post the
  handover note as a comment on the issue (`gh issue comment <n> --body-file <file outside the checkout>`).
- When the inner loop and your browser files (twice) are green, post `CAR #<n> <branch> @ <sha>: locally green` on
  #429. A red car is pulled out of the train and comes back to you.
- **The handover note is your memory.** If you cannot recall what you did, re-read it and
  `git log --oneline origin/main..HEAD` before any edit.

## Never
Merge; push to `main`; force-push; rebase a pushed branch; change `version` or `CHANGELOG.md`; delete, skip, xfail,
deselect, loosen or flat-wait a test (`wait_for_timeout`, `sleep`); raise a budget; edit a frozen lane (`ci`,
`relay`) without the operator's linked approval; add a dependency; use `innerHTML`, a CDN or a build step; resolve a
conflict by taking a whole file.

## Stop
Set the note's Status and end the session when: you cannot reconcile the note with the commits; you read the same
file three times or ran the same command twice with the same result (`stuck`); a test is red after two fixes
(`stuck`); the issue needs a frozen lane, a budget, a dependency or a test change other than adding tests, or two
readings lead to different work (`blocked-on-operator`). A safe, reversible default is not a stop: assume it and write
it under Open questions.

## Environment
```bash
pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow"   # the inner loop
python -m pytest -q -m browser <files>                                                      # the browser files you touched
```
Prefer Linux or WSL2 for the inner loop. On Windows, run fleet test files serially, never `-n auto` (#227).
