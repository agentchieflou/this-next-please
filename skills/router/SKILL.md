---
name: router
description: "Use at the start of every task after session-bootstrap, and whenever you are unsure which skill applies. Reads .agent/state.json and picks exactly ONE next skill. Does no work itself."
---
# Router

1. Use the `phase`, `active_ticket` and `open_questions` `session-bootstrap` handed you **if it invoked you in this same turn**. Otherwise read `.agent/state.json` — on every later task in the session you must, because a skill has run since and state changes.
2. Run `ad-state blocking --ticket <the key this request names, else omit the flag>`. It lists only the questions that stop **this** ticket's work; questions parked on other tickets are counted, never shown, and never stop you.
   - `blocking: 0` → continue.
   - **The user's message is the reply** whenever it says anything about the work -- a choice, a value, "yes", "use UAT", "go ahead with X" -- even when it does not repeat the question. One question listed → `ad-state answer "<their words>"` (no id needed); several → `ad-state answer <id> "<their words>"` for each it addresses. "Continue" / "go on" and the question has a `default` → answer with the default. An instruction that makes it moot → `ad-state supersede <id> "<their instruction>"`. One line, then continue. Unsure whether it answers? It does: a wrong reading costs one correction, a wrong stop costs a turn.
   - The prompt says the answers are **already recorded** (the desk recorded them) → `blocking: 0` already; continue.
   - A listed question with `want: access` is an environment blocker: run the one command it names, once. It works now → `ad-state answer <id> "fixed: <command> ran <today>"`, continue. Still refused → as below.
   - Only a message that says nothing about the work (a greeting, "start", "status") → print `blocked — <id>: <question>` and STOP. Do not run `friction-log` again: the question was logged when it was asked.
3. Decide how this work is tracked before matching. The user picks per request; the project's `ticket_policy` fact sets the default; **the match is computed, never judged.**
   - "new ticket", "open a ticket", "file this", "create a Jira" → invoke `jira-create` first; it hands back here.
   - "no ticket", "without a ticket", "just push it" → `ad-state ask "Untracked, as asked?" --kind ticket --choice new --choice none --assume none`, one line, CONTINUE.
   - Otherwise run `ad-jira match "<the request, in its own words>"` -- **also when `active_ticket` is set**: a one-off prompt is not charged to a ticket it has nothing to do with. It reads your open tickets (the fleet's board, cached), scores them on shared words, and prints `verdict`, `candidates`, `next` and the one `ask` line. Do what `next` says, nothing else:
     `continue` (verdict `named` or `active`) → the ticket is the one named or the active one. `ask-and-continue` → run the printed `ask` exactly (`--kind ticket --assume <KEY>` records the match and sets `active_ticket`; `--assume none` makes the work untracked and leaves the reminder on the tile with the nearest keys and `new` as choices), say so in one line, CONTINUE. `ask-and-stop` (`ticket_policy: required`) → run the printed `ask`, `friction-log` type `missing-info`, STOP. `jira-create` (the operator answered `new`) → invoke `jira-create`; it hands back here.
   - `ad-jira match` answers `ok: false` (no token, Jira unreachable) → its `ask` line is the fallback: run it and follow its `next` the same way. Never guess a key yourself.
   - An answer to a ticket question is applied by `ad-state answer` itself (a key moves the work, `none` untracks it) and its `next` says `jira-create` when the operator chose `new`.
4. The request only starts the session ("start", "bootstrap", "initialize", "are you set up", a greeting) and names no work → print `ready — <the state: line>` and STOP. That is the end of the turn, not a friction.
5. Match the request to ONE row. First match wins. Rows in the project's own `AGENTS.md` `## Project routes` table (if any) come first; a row there that names a skill that is not installed is ignored.
   **Ours first.** A row here beats a skill another package installed (pncli's own, a vendor's), even one whose description fits better; inside a skill, a dedicated `ad-*` verb beats `ad-pncli raw`, and bare `pncli` is never run (a fleet denies it; it skips the approval gate).
   **A sub-router is one hop, not a detour.** A row that names `*-router` costs one more read and nothing else: it holds that domain's rows in the order they must be tried, and it ends in the same place this table does.

| Request mentions | Invoke |
|---|---|
| start / launch / resume / restart / stop a run, run status, reconcile a run, workers, "is it still running" | `run-control` |
| a ticket key, "triage", "what's next", acceptance criteria, "new ticket", "open a ticket", "file this as a Jira" | `jira-router` |
| UAT, remediation, "compare Jira to Teradata / Hadoop / Hive / Impala", migration or cutover parity, query, count, rows, table, SQL, Teradata, Hive, Hadoop, Impala, Spark, Oracle, diff two datasets | `data-router` |
| sprint report, committed / completed points, changelog, field history, "when did … change", move / transition / close / reopen a ticket, "mark it done", "put it in review" | `jira-router` |
| DPM run, hand back / handoff, orchestrator.db, selection manifest, job manifest, OCR routing, named fields out of documents, Content Understanding, Foundry analyzer, sort / organize / file a folder of documents | `dpm-router` |
| Power BI, PBIP, report, visual, model, DAX, measure, TMDL | `pbi-router` |
| map the codebase, how does this repo work, write tests for, cover, did I break anything, is it faster, regression, slow, optimize, hot path, fix, patch, add a flag, refactor, "make it do X", clean up the worktree, dirty tree, stash | `code-router` |
| sbatch, cluster job, schedule, nightly | `slurm-submit` |
| PR, branch, push, commit | `bitbucket-pr` |
| Confluence, document, write-up, page | `confluence-publish` |
| progress saved?, "where was I" | `state-update` |
| real work no row above names: investigate, spike, "figure out how", "is it possible to", "what would it take", a problem nobody has routed yet | `research-spike` |

6. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
7. No row matched after reading the table twice: a change to this repository's code (fix, patch, add a flag, refactor, "make it do X") or uncommitted changes to tidy → invoke `code-router` (its last rows are `worktree-tidy` and `code-change`). A skill another package installed fits → invoke it and say `→ <skill> (not ours): <why>`. Anything else that is still work → invoke `research-spike`: it spends a bounded look, writes what it found, and logs the gap for the architect. Only a request that is not work at all → `friction-log` with type `ambiguity`. STOP.
8. **Environment errors are not routing errors.** A command the host refused (permission denied, "not allowed", an approval declined), a launcher that does not start, or a broken install (a merge-conflict marker or `SyntaxError` inside an installed file) is never fixed by re-running a skill: `ad-state ask "<exact executable or permission> is blocked: <what a human must do>" --want access`, then `friction-log` type `tool-error`. STOP.

When this table outgrows itself — about 24 rows or 80 lines, checked by `tests/test_skills.py` — **split it, do not shorten the rows.** Add a domain sub-router and give this table one row pointing at it, the way `pbi-router` holds the Power BI skills and `jira-router`, `data-router`, `dpm-router` and `code-router` hold theirs. A sub-router has the same limits and the same fix. The rows here are already terse; squeezing them further trades a legible table for a cryptic one while the growth continues, and first-match-wins turns a near-miss into the wrong skill.
