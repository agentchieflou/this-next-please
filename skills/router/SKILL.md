---
name: router
description: "Use at the start of every task after session-bootstrap, and whenever you are unsure which skill applies. Reads .agent/state.json and picks exactly ONE next skill. Does no work itself."
---
# Router

1. Use the `phase`, `active_ticket` and `open_questions` `session-bootstrap` handed you **if it invoked you in this same turn**. Otherwise read `.agent/state.json` — on every later task in the session you must, because a skill has run since and state changes.
2. Run `ad-state blocking --ticket <the key this request names, else omit the flag>`. It lists only the questions that stop **this** ticket's work; questions parked on other tickets are counted, never shown, and never stop you.
   - `blocking: 0` → continue.
   - The user's message answers a listed question → `ad-state answer <id> "<their words>"`. It orders work that makes the question moot → `ad-state supersede <id> "<their instruction>"`. Either way, one line, then continue.
   - A listed question with `want: access` is an environment blocker: run the one command it names, once. It works now → `ad-state answer <id> "fixed: <command> ran <today>"`, continue. Still refused → as below.
   - Otherwise print `blocked — <id>: <question>` and STOP. Do not run `friction-log` again: the question was logged when it was asked.
3. Decide how this work is tracked before matching. The user picks per request; the project's `ticket_policy` fact sets the default.
   - The request names a ticket key, or `active_ticket` is set → that ticket. Nothing to do.
   - "new ticket", "open a ticket", "file this", "create a Jira" → invoke `jira-create` first; it hands back here.
   - "no ticket", "without a ticket", "just push it", or nothing said: `ticket_policy: required` → `ad-state ask "Which ticket — an existing key, or a new one?" --choice "<KEY>" --choice new`, then `friction-log` type `missing-info`. STOP. `optional` (the default when the fact is absent) → `ad-state ask "Track this under a ticket?" --choice existing --choice new --choice none --assume "none: untracked change, PR without a ticket"`, say so in one line, CONTINUE.
4. The request only starts the session ("start", "bootstrap", "initialize", "are you set up", a greeting) and names no work → print `ready — <the state: line>` and STOP. That is the end of the turn, not a friction.
5. Match the request to ONE row. First match wins. Rows in the project's own `AGENTS.md` `## Project routes` table (if any) come first; a row there that names a skill that is not installed is ignored.
   **Ours first.** A row here beats a skill another package installed (pncli's own, a vendor's), even one whose description fits better; inside a skill, a dedicated `ad-*` verb beats `ad-pncli raw`, and bare `pncli` is never run (a fleet denies it; it skips the approval gate).

| Request mentions | Invoke |
|---|---|
| start / launch / resume / restart / stop a run, run status, reconcile a run, workers, "is it still running" | `run-control` |
| a ticket key, "triage", "what's next", acceptance criteria | `jira-triage` |
| "new ticket", "open a ticket", "file this as a Jira" (no key named) | `jira-create` |
| UAT, remediation, "compare Jira to Teradata / Hadoop / Hive / Impala" (status/assignee lists) | `uat-jira-vs-source` |
| UAT across **two** warehouses at once, migration or cutover parity ("do Teradata and Hadoop agree") | `uat-jira-vs-warehouses` |
| sprint report, committed / completed points, changelog, field history, "when did … change" | `jira-changelog` |
| query, count, rows, table, SQL (Teradata) | `teradata-query` |
| Hive, Hadoop, Impala, Spark table | `hive-query` |
| Oracle | `oracle-query` |
| DPM run, hand back / handoff, orchestrator.db, selection manifest, text_analysis, job manifest, OCR routing, native text | `dpm-consumer-integration` |
| extract named fields from DPM documents ("pull the borrower and amount out of these"), per-job field list | `dpm-field-extraction` |
| Content Understanding, Foundry analyzer, "use the AI model to read these documents", field extraction that label matching could not do | `content-understanding-extract` |
| Power BI, PBIP, report, visual, model, DAX, measure, TMDL | `pbi-router` |
| sbatch, cluster job, schedule | `slurm-submit` |
| map the codebase, how does this repo work, what calls what, unfamiliar code | `codebase-map` |
| write tests for, cover, characterization test, no tests for | `test-cover` |
| did I break anything, is it faster, before and after, regression | `test-regress` |
| slow, make it faster, performance, optimize, hot path, N+1 | `perf-optimize` |
| PR, branch, push, commit | `bitbucket-pr` |
| Confluence, document, write-up, page | `confluence-publish` |
| move / transition / close / reopen a ticket, "mark it done", "put it in review" | `jira-transition` |
| sort / organize / file a folder of documents, "where should these go", a DPM document delivery to arrange | `file-organize` |
| progress saved?, "where was I" | `state-update` |

6. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
7. No row matched after reading the table twice: uncommitted changes to tidy ("clean up the worktree", "dirty tree", "stash this", "what do I do with these changes") → invoke `worktree-tidy`. A change to this repository's code (fix, patch, add a flag, refactor, "make it do X") → invoke `code-change`. A skill another package installed fits → invoke it and say `→ <skill> (not ours): <why>`. Anything else → `friction-log` with type `ambiguity`. STOP.
8. **Environment errors are not routing errors.** A command the host refused (permission denied, "not allowed", an approval declined), a launcher that does not start, or a broken install (a merge-conflict marker or `SyntaxError` inside an installed file) is never fixed by re-running a skill: `ad-state ask "<exact executable or permission> is blocked: <what a human must do>" --want access`, then `friction-log` type `tool-error`. STOP.

When this table outgrows itself — about 24 rows, checked by `tests/test_skills.py` — **split it, do not shorten the rows.** Add a domain sub-router and give this table one row pointing at it, the way `pbi-router` already holds the seven report skills behind a single Power BI row. The rows here are already terse; squeezing them further trades a legible table for a cryptic one while the growth continues, and first-match-wins turns a near-miss into the wrong skill.
