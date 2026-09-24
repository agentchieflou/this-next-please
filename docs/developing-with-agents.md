# Developing this repository with agents: build, handover, review

This page is for the coding agents that build this repository (not for Luna, the agent this repository *ships*).
Written 2026-09-24 for the post-ink epics; the current brief is [brief-post-ink-epics.md](brief-post-ink-epics.md).
[brief-epics-162-170.md](brief-epics-162-170.md) is kept as history.

## 1. Who's who

| Role | Who | Does | Never |
|---|---|---|---|
| **Builder** | A Gemini agent: Antigravity 2.0 or `agy` on the operator's laptop, or Jules in the cloud | Builds one issue on one branch, keeps the handover note current, pushes the branch and posts a CAR line (§2) | Merges, closes issues, pushes to `main`, edits a frozen lane without the operator's linked approval |
| **Reviewer** | Opus 5.5 at low or medium effort | Reviews every PR against its issue (§8), fixes defects inside the issue's scope, and **takes over a slice whose builder ran out of context** (§9) on the same branch | Opens a second branch for the same issue, widens the scope, merges without the operator's standing word |
| **Operator** | The human | Answers the decisions register, runs the laptop sittings, merges | — |

**AGENTS.md is Luna's rulebook, not yours.** Every agent loads it automatically, and its rule 1 tells the reader to run
Luna's session skills: do not. Of its rules, these bind developers too: **8** (never merge a PR or close an issue on your
own initiative), **9** (Conventional Commits), **11** (the same tool call twice with the same arguments: stop), **12**
(nothing written outside your branch), **13** (a tool failing twice in a row: stop) and **16** (look before you branch).
The rest are Luna's. `GEMINI.md` at the root says the same in eight lines.

## 2. Branch and PR

- One issue is one branch, `gemini/<issue>-<slug>`, from `main`. The builder opens **no PR**: the branch is a car on
  the merge train below, and the train's one PR carries `Closes #<issue>`.
- One issue per conversation. Do not start a second issue in a session that built the first.
- Bring `main` in by merging `origin/main`. Never rebase a pushed branch, never force-push, never push to `main`.
- Never change `version` in `pyproject.toml` or add a heading to `CHANGELOG.md`: the release PR at the end of a wave
  does both (`tests/test_update.py` pins them together, and four ink PRs broke this rule).
- Resolve a conflict hunk by hunk. Never resolve one by taking a whole file (commit 869d9cd dropped `main`'s text that
  way). After every merge of `main`, re-run the doc guards: `tests/test_entrypoints.py`, `tests/test_fleet_components.py`,
  `tests/test_suite_hygiene.py`.
- A bug you find in a shared file that your issue does not own is its own issue: search `tests/regressions/` and the
  open PRs for the symptom first (the same idle-desk bug was fixed in five parallel branches during the ink epic).

### Merge train

Decision 7 ([#429](https://github.com/agentchieflou/this-next-please/issues/429#issuecomment-5823490430)) replaced one PR per issue with a train.

- **Builder.** Test locally (the inner loop, plus the browser files you touched, twice), post the handover note as a
  comment on the issue, push the branch, and post `CAR #<n> <branch> @ <sha>: locally green` on the board (#429).
- **Conductor** (the review orchestrator). Reviews each car's diff before boarding it (§8). Every 1-2 hours it builds
  `train/<N>` from `main`, merges each boarded car with `git merge --no-ff` (never a rebase), runs the full local
  suite once, and opens **one** PR to `main` whose body lists `Closes #a`, `Closes #b`, ... for every car. When CI is
  green it posts `READY-TO-MERGE #<train PR>`.
- **A red car is pulled out.** If the train goes red, the conductor rebuilds it without the car that caused it; the car
  goes back to its builder and the rest ship.
- **Merger.** Merges the train PR with a merge commit, never squash, so a car's own open PR (if any) shows as merged,
  then closes every listed issue still open. One car on ink-core per train.

## 3. The checkpoint ritual

After **every** acceptance criterion goes green, in this order, every time:

1. Run the issue's named tests.
2. Commit only the files you meant to change, with a Conventional Commit message.
3. `git push origin HEAD`. Open no PR (§2, Merge train).
4. Post the handover note as a comment on the issue, headed `Handover`:
   `gh issue comment <n> --body-file <a file outside the checkout>`. Post a fresh one each time; the newest wins.

Never write the note to a file inside the checkout: a Markdown file under `.agent/` is scanned by the docs guard,
and anything else gets committed. Your tool's own plan and walkthrough files stay on your machine, where the reviewer
cannot see them. **The pushed branch and the issue's handover comment are the only memory that survives you.**

## 4. The handover note

`.github/pull_request_template.md` carries this block. Keep it between the markers; the headings are checked by
`tests/test_agent_onramp.py`.

<!-- handover:start -->
```
## Handover
| | |
|---|---|
| Issue / epic / wave / lane | #<n> · epic #<e> · wave <w> · lane `<lane>` |
| Branch · base | `gemini/<n>-<slug>` · `main` @ `<sha>` (last merge of main: `<sha>`) |
| Status | building / ready-for-review / stuck / blocked-on-operator / in-review / review-done |
| Held by | Gemini (<Antigravity 2.0, agy x.y.z or Jules>, <model>) or Opus 5.5 <low/medium> |
| Updated | <UTC time>, after commit `<sha>` |

### Acceptance criteria
- [x] <criterion, copied from the issue> - `<command>` -> `<last line of output>` @ `<sha>`
- [ ] <criterion>

### Done
1. <what> - `<sha>` - `<command>` -> `<result line>`

### Gates on the last commit
| Gate | Command | Result |
|---|---|---|
| named tests | python -m pytest -q <files> | |
| inner loop | python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow" | |
| browser files touched | python -m pytest -q -m browser <files> | |
| guards | python -m pytest -q tests/test_fleet_skin_guard.py tests/test_fleet_skins.py tests/test_fleet_components.py tests/test_entrypoints.py tests/test_suite_hygiene.py tests/test_agent_onramp.py | |
| shuffled | python -m pytest -q -p no:cacheprovider --shuffle-seed 1 <files> | |
| agent PR check | python .github/scripts/agent_pr_check.py --base origin/main | |

### Next
1. <file : symbol - what - the test that proves it> (the first line is the very next action, startable cold)

### Files touched
- `<path>` - <why> [lane `<lane>`]

### Deviations from the issue
none

### Open questions
none

### Failures not caused by this branch
none

### Dead ends
none
```
<!-- handover:end -->

Rules for the note:
- Tick a criterion only with the command and its last output line. "Should pass" is not evidence.
- **Next** always has a first line someone can start cold: a file, a symbol, what to change, and the test that proves it.
- **Open questions**: two readings of a criterion that lead to different work are written out, `(a)` and `(b)`, with
  the one you assumed and how to undo it.
- **Failures not caused by this branch**: the test id, its output line, and the command showing it fails on `main` too.
- **Dead ends**: what you tried and why it failed, so nobody tries it again.
- It is called a *handover* note on purpose: *handoff* is a product feature here (docs/fleet-handoff.md).

## 5. Stop conditions

On each of these, set the note's Status, push, and end the session:

| Condition | Status |
|---|---|
| You cannot recall what you did (your context was summarised): re-read the note, `git log --oneline origin/main..HEAD` and the issue **before any edit**. If they do not agree, stop. | `stuck` |
| You have read the same file three times, or run the same command twice with the same result | `stuck` |
| The same test is red after two fix attempts | `stuck`, with the output |
| The issue needs a frozen lane (§7), a budget change, a new dependency, or a test change other than adding tests | `blocked-on-operator` |
| Two readings of a criterion lead to different work | `blocked-on-operator`, both readings written out |
| Every criterion is ticked with evidence and every gate is green | `ready-for-review` |

A missing detail that a safe, reversible default settles (the decisions register gives most of them) is not a stop:
assume it, write it under Open questions with how to undo it, and continue.

## 6. Context budget

Gemini's usable memory is about 140-150k tokens before a lossy summary (antigravity-cli issue #878; the Gemini CLI
`historyWindow.maxTokens` default is 150,000), and there is no manual compaction. Plan a slice to finish in about
100k tokens. What the hotspot files cost to read whole:

| File | Tokens, read whole |
|---|---|
| `agentdata/fleet/static/app.js` | ~61k: **never read it whole** |
| `agentdata/fleet/serve.py` | ~36k: **never read it whole** |
| `agentdata/fleet/static/app.css` | ~17k |
| `tests/test_fleet_ink.py` | ~16k |
| `agentdata/fleet/static/ink/layer.js` | ~15k |
| `docs/desk-ink.md` | ~11k |

Find a symbol with `grep -n` and read about 80 lines around it. Every issue's **Read first** section names the ranges.

## 7. Lanes

A lane is a set of files one PR at a time should own. Lanes are what let several builders work in one wave without
fixing the same hunk twice.

| Lane | Files | Rule |
|---|---|---|
| `ci` | `.github/workflows/tests.yml`, `tests/conftest.py`, `[tool.pytest.ini_options]` in `pyproject.toml` | **Frozen**: a PR that edits it links the operator's approving comment |
| `relay` | `GEMINI.md`, `AGENTS.md`, this page, `.github/pull_request_template.md`, `.github/agent-lanes.json`, `.github/scripts/agent_pr_check.py`, `tests/test_agent_onramp.py`, `tests/test_agent_pr_check.py` | **Frozen**, as `ci` |
| `version` | `version` in `pyproject.toml`, `CHANGELOG.md` headings | Release PR only |
| `ink-core` | `static/ink/ink.js`, `layer.js`, `shapes.js`, `pen.js`, `fx.js` | One PR open at a time; the budget rule is in the decisions register |
| `desk-page` | `static/app.js`, `static/app.css`, `static/index.html`, `static/common.js` | Parallel only in the merge order the brief names |
| `settings-page` | `static/settings.html`, `static/settings.js` | As `desk-page` |
| `serve` | `agentdata/fleet/serve.py` | As `desk-page` |
| `theme` | `agentdata/theme.py`, `agentdata/fleet/skins.py` | As `desk-page` |
| `skin:<name>` | `static/ink/skins/<name>.js`, `static/skins/<name>/`, `tests/test_fleet_ink_<name>.py` | One PR per skin at a time |
| `shared-docs` | `docs/desk-components.md`, `docs/testing-this-repo.md`, `docs/themes.md`, `docs/refusals.md` | Insert your row beside its relative; never rewrite another issue's row or paragraph |

The lanes are recorded as data in `.github/agent-lanes.json` and checked by `.github/scripts/agent_pr_check.py`
(#324), and the reviewer runs that check first: `python .github/scripts/agent_pr_check.py --base origin/main`, with
`--lane <name>` for each lane the issue names and `--allow <lane>` for a frozen lane the operator approved (the PR links
the approving comment). docs/testing-this-repo.md says what it refuses.

## 8. Review (Opus 5.5)

Effort: **low** for an S issue outside every hotspot lane; **medium** for M issues, any hotspot lane, any visual
change, and any takeover. Each issue carries a `review:low` or `review:medium` label.

- **R0 Pick up.** Read the note and the issue. `git fetch origin && git switch <branch>`, then
  `git log --oneline origin/main..HEAD`. If a commit is newer than the note's Updated line, rebuild the note from the
  commits first. Set Status `in-review` and Held by Opus.
- **R1 Scope.** Compare `git diff --stat origin/main...HEAD` with the issue's Build and Out of scope. Hunks outside the
  named symbols in a hotspot file (reformatting, renames, drive-by edits) are reverted.
- **R2 Test integrity.** In `git diff origin/main...HEAD -- tests/`: no deleted or renamed test, no new skip, skipif,
  xfail or deselection, no loosened constant, tolerance or budget, no new flat wait (`wait_for_timeout`, `sleep`).
  Every new test fails on `main`: run it in `git worktree add <tmp> origin/main` and record the result.
- **R3 Run.** The named tests; the inner loop; `-m browser` for the browser files touched, twice; the guards (skin
  guard, skins and `theme.check`, components, entrypoints, hygiene, refusals, onramp); one shuffled seed.
- **R4 Render contract and ink rules** (visual issues). A test with the feature on asserts an idle desk makes zero DOM
  mutations and zero WebGL frames. Skin modules write nothing to the page (grep the diff under `static/ink/skins` for
  `classList`, `setAttribute`, `.style`, `append`). No colour literals in modules. Marks are drawn, never faded. A
  reduced-motion test and a `?ink=off` test exist.
- **R5 Look at it.** Render at 1400x900: a light variant, a dark variant, reduced motion, `?ink=off`. Read the
  screenshots. Check the HIG basics (docs/plan-desk-refactor.md): the pane that needs the operator is the loudest,
  text reads at 4.5:1, focus is visible and is not a state colour, nothing is drawn over words, motion is brief.
- **R6 Docs.** The feature's page, its inventory row, the plan's "Built (#n)" note, `docs/refusals.md`, and
  `docs/windows-verification.md` rows marked "not yet measured". No version or CHANGELOG change.
- **R7 Git.** Conventional Commits, the branch name, `Closes #n`, `main` merged in, never rebased.
- **R8 Fix or bounce.** Fix defects inside the issue's scope with `fix(review): ...` commits. Anything beyond the scope
  becomes a new-issue proposal in the verdict. A frozen-lane need goes to the operator.
- **R9 Verdict.** Set the note to `review-done` or `blocked-on-operator`. Post one comment: the verdict, the commands
  run with their last lines, what you changed, what is left, and the merge-order note. Mark the PR ready for review
  only on `review-done`. Never merge unless the operator's standing instruction for the wave says so.

## 9. Pass-back: when the builder runs out

The slice goes to an Opus reviewer, who continues **on the same branch and PR**, when:

- the note says `ready-for-review` or `stuck`;
- a `building` PR has had no push for 3 hours;
- the same CI job is red twice after the builder's fixes; or
- the builder's session ended (context exhausted, quota, or a crash) without setting a Status.

The reviewer does R0, finishes the remaining criteria (the note's **Next** is the plan), then reviews its own work
at medium effort against R1-R9, and says in the verdict which commits are its own. `blocked-on-operator` goes to the
operator first, not to a reviewer.

## 10. Merge (the operator)

1. Merge only a PR whose verdict comment says `review-done` and whose checks are green. A merge over a red check
   happens only at the operator's word for that PR, and its merge message names the check and links a flake issue.
2. Within a wave, merge in the brief's order. After each merge, the next PR in the same lane merges `origin/main` in
   and re-runs its named tests.
3. Use a merge commit (the repository's convention), never squash: a train PR must keep its cars' commits. `Closes #n` closes the issue; the operator closes epics.
4. At the end of each wave, a reviewer opens the release PR: version and CHANGELOG, written from the PRs' notes.
5. The operator may delegate a wave: "merge wave N in the brief's order when review-done and green". The reviewer then
   merges and reports one line per merge.

## 11. Tool setup (September 2026)

- **Antigravity 2.0 / `agy`** on the Windows laptop: one worktree per issue, outside the main checkout (Gemini CLI's
  `.gemini/worktrees/` is ignored by git and by the repo-walking guards if you use it). Terminal execution policy
  **Auto**, or **Off** with an allow-list; never **Turbo**. Deny `git push --force`, `git reset --hard`,
  `gh pr merge` and recursive deletes. `gh` signed in.
- **Jules** in the cloud reads `AGENTS.md` only: paste the brief's preamble into the task. Setup script:
  `pip install -e ".[dev]" && python -m playwright install --with-deps chromium`.
- **Gemini CLI** was retired on 18 June 2026 except for Code Assist Standard and Enterprise; if you use it, it reads
  `GEMINI.md` by default.
- **Windows**: run the named test files serially, never `-n auto` for fleet tests (#227), and expect runs 1.5-3x
  slower than Linux. Prefer WSL2 or Linux for the inner loop; run browser files on Windows before review when the
  issue touches a shell.

## 12. Briefs

| Brief | Epics | State |
|---|---|---|
| [brief-post-ink-epics.md](brief-post-ink-epics.md) | testing, relay, HIG, theme switch, models, effects, legacy looks, fleet map | current |
| [brief-epics-162-170.md](brief-epics-162-170.md) | #162, #170 | history |
