# Plan: the routing network at 50,000 credits — a wider table, a bounded spike, and the routes we have not met yet

_Status: PLANNED (research session of 2026-10-03). §Done this PR is built; §Candidates is the research the operator
asked for, ranked and costed, with nothing in it started. Every number here that is not from the ledger is marked as a
guess, and §Measurements names the rows that turn each guess into a figure._

## Why this exists

The operator's words, 2026-10-03: *"The routing network we have done so far is pretty good. And in the last month
when we had 23,000 credits, we were able to get by using only 18,500. But now we have 50,000, which suggests that we
should be able to get by more fluidly in an auto balanced mode as opposed to an auto efficiency mode. But the issue is
we have some constraints currently that complicate that. One of those being that we have like a ceiling on our
[router] sessions of 60 lines. We probably need to expand that a bit so we can get more creative with the session
states. And then on top of that, we probably need to do a research session on expansion routes for our skill network
to start covering solutions for problems that we haven't come across yet."*

Read against the code, three constraints were holding the network at the shape a 23,000-credit month needed:

| Constraint | Where it was | What it did |
|---|---|---|
| The top router was one flat first-match table at **23 rows against a limit of 24**, and 52 lines against a warning at 60 (`tests/test_skills.py` `ROUTER_ROWS`, `ROUTER_LINES`) | `skills/router/SKILL.md` | No room for a row. Every uncovered request fell through step 7 to `friction-log` type `ambiguity` and the session stopped — the cheapest possible outcome, which is what a tight month wants and a wide one does not |
| `fleet.copilot.auto_tier` defaulted to `efficiency` (`launch.DEFAULT_AUTO_TIER`), and nothing read the allowance at all: the fleet knew a per-agent cap (`fleet.budget_per_agent`) and a per-day total, never a month against a grant | `agentdata/fleet/launch.py`, `lifecycle.py`, `spend.py` | `balance` could be set, but with no reserve the month could run dry on the 24th with no warning and no step-down |
| Eleven phases, of which seven are working states (`triaged`, `querying`, `optimizing`, `validating`, `documenting`, `pr_open`, `blocked`) | `agentdata/state.py` `PHASES` | A spike, a map, a test pass, a deploy and a report plan all showed on the tile as `triaged` or `querying`, so the desk could not say what the credits were buying |

## Done this PR

- **The top table is a domain index.** Twelve rows, every one a verb cluster or a sub-router; four domain routers
  (`jira-router`, `data-router`, `dpm-router`, `code-router`) hold the leaf rows the way `pbi-router` always has. The
  precedence the flat table relied on is kept and pinned: a run request before a ticket key, a ticket key before a
  query, a UAT before a sprint report (`tests/test_routing_friction.py`). Each sub-router has the same 24-row / 80-line
  limits and the same split rule, and each ends in `research-spike`.
- **`ROUTER_LINES` 60 → 80.** The row limit did not move: width is what makes a first-match table unreliable, and
  the split is what buys width. Lines buy a precondition sentence per table (`ad-pbi auth --probe` before a deploy,
  `ad-doctor`'s source row before a query, read-only before any warehouse row), which is the "more creative" the
  operator asked for, written where the decision is made.
- **`research-spike`**: the route for real work no row names. At most 12 tool calls and 2 files, cheapest sources
  first (the project's facts and brief, a Jira text search for prior art, `ad-graph summary`, three files), a page in
  `.agent/out/spike-<slug>.md` with the options costed and ONE recommended route, then either one hop to the skill
  that now fits or a `friction-log` of the new type `coverage-gap` carrying the row or skill to add. The architect
  pass (`prompts/remediate-from-friction.prompt.md` step 7) clusters those by recommended route.
- **Six working phases** — `researching`, `planning`, `mapping`, `editing`, `testing`, `deploying` — set as the step
  starts by the skills that own them. The terminal set the fleet reads (`agentstate.TERMINAL_PHASES`) is unchanged.
- **`balance` is the default tier, with a reserve.** `fleet.credits.allowance` and `fleet.credits.reserve` (20%) on the
  settings page; `credits.py` sums the month from the day rows every ledger already keeps; inside the reserve every
  `start`, `send` and `restart` carries `efficiency` instead, and `ad-fleet status` prints `credits: reserve` with the
  sentence that says why. Nothing new stops: the per-agent budget is still the only stop (decision of 2026-09-22,
  *meter first, caps later*, kept).
- **`jira-comment`**: the one route a flat table had no room for although its verb (`ad-jira comment`) shipped in
  0.17. Posting a finding on the ticket is a comment, not a transition, and it was being routed to `jira-transition`
  or stopped.

## The credit model, and what the headroom buys

The unit is premium requests, the only cost the fleet measures (`plan-meter.md` §What is reused). The ledger
attributes every rise to a day; the month is the sum of a month's days; nothing is estimated.

| | September 2026 (measured) | October 2026 (the plan) |
|---|---|---|
| Allowance | 23,000 | 50,000 |
| Spent | 18,500 (80%) | — |
| Tier | `efficiency` | `balance`; `efficiency` inside the reserve |
| Reserve | none | 10,000 (20%) — `balance` runs on the first 40,000 |
| Per working day (22 days), all agents | ~840 | ~2,270 allowance; ~1,820 before the reserve |

What `balance` costs per turn against `efficiency` is **not measured** — it is M5 below, and the first week of
October on the new default is the measurement. Until it is, the plan's only arithmetic is the reserve: at
September's rate the month ends at 18,500, well inside; at twice that rate (a guess at `balance`) it ends at 37,000,
still inside; at 2.7× the reserve bites on the 24th and the last four days run on `efficiency`. The reserve is the
guard against the guess being wrong, and it is a step-down, so a wrong guess costs quality on the last days of the
month and never a stopped ticket.

**Where the headroom goes, in order of what it is worth:**

1. A bounded spike instead of a stop (`research-spike`): one session that would have ended at `friction-log` now
   ends with a page and a route. Cost class *medium* (≤ 12 calls); worth it on every uncovered request, because the
   alternative is a human re-prompt.
2. The sub-router hop: one more skill read per task (~60 lines). Cost class *cheap*; the price of a table with room.
3. The precondition sentences in each table: a `--probe` or a doctor row read before a leaf skill is entered, rather
   than a leaf skill failing on step 4. Cheap, and it saves the dear turn that follows a failed deploy.
4. The phases: free. The tile says what the spend is buying, which is the reassurance `plan-meter.md` was written for.

## The network as it stands

49 skills, 6 routers, 1 spike. Every leaf is reachable from a router or a hand-off (`tests/test_skill_handoffs.py`).

| Domain | Router | Leaves | Rows with room for more |
|---|---|---|---|
| Operations | `router` row 1 | `run-control` | — |
| Jira | `jira-router` | `jira-triage`, `jira-create`, `jira-changelog`, `jira-transition`, `jira-comment`, (`uat-report-visual`) | 17 |
| Warehouses and UAT | `data-router` | `uat-jira-vs-warehouses`, `uat-jira-vs-source`, `teradata-query`, `hive-query`, `oracle-query`, `data-adapter`, (`slurm-submit`) | 17 |
| Documents | `dpm-router` | `dpm-consumer-integration`, `dpm-field-extraction`, `content-understanding-extract`, `file-organize`, (`run-control`) | 19 |
| Power BI | `pbi-router` | 15 leaves | 9 |
| Code | `code-router` | `codebase-map`, `test-cover`, `test-regress`, `perf-optimize`, `worktree-tidy`, `code-change` | 18 |
| Delivery | `router` rows | `slurm-submit`, `bitbucket-pr`, `confluence-publish`, `state-update` | 12 |

## Candidates — the routes we have not met yet

The method: every verb the `ad-*` CLI already has was listed (`ad-jira`, `ad-pbi`, `ad-uat`, `ad-git`,
`ad-graph`, `ad-test`, `ad-sort`, `ad-dpm`, `ad-foundry`, `ad-confluence`, `ad-fleet`; pncli's own read verbs, run
directly since 0.20.0), every router row was read
against the requests a BI reporting team sends an agent in a week, and every request that today lands in step 7,
in `friction-log`, or in the *wrong* row was written down. Then each was given a trigger phrase, an owner, a cost
class (*cheap*: reads and one `ad-*` command; *medium*: a query, a projection or a spike; *dear*: a model run, a
deploy, a write behind the approval gate) and a rank, by how often the team will say it.

| # | Request, in the team's words | Today | Proposed owner | Cost | Posture |
|---|---|---|---|---|---|
| 1 | "what does the runbook page say", "read the Confluence page on X", "is there a page about" | **mis-routed**: the `Confluence, document, page` row sends a *read* to `confluence-publish`, a writer | `confluence-read` (new), a skill row only: `pncli confluence get-page` directly, saved to `.agent/out/` and read with `ad-view`; no new verb; never edits | cheap | either |
| 2 | "review this PR", "what do you think of these changes", "did they handle X" | nothing; `bitbucket-pr` opens PRs and nothing reads one | `pr-review` (new): read-only; `git diff <base>...<head>`, `ad-graph refs` on the touched symbols, `ad-test run` on the branch, a findings file; never a comment on the PR without the operator's word | medium | balanced preferred |
| 3 | "profile this table", "what's in column X", "null rate", "distinct values", "how far back does it go" | an ad-hoc `teradata-query`; the SQL is written by the model each time and often wrong on the engine | `data-profile` (new): generated per engine the way `ad-uat` generates reconciliation SQL; counts, nulls, min/max, top-20 values, one TOON | medium | either |
| 4 | "put it in a spreadsheet", "export this to Excel", "a CSV for the business" | nothing; TOON and TSV are the only outputs, `openpyxl` is already the `uat` extra | `tabular-export` (new) or a verb on `ad-view`: TOON/TSV → `.xlsx`/`.csv` under `.agent/out/`, deterministic, no model pass | cheap | either |
| 5 | "why did the refresh fail last night", "the job died", "what happened at 02:00" | `run-control` for a run, `pbi-refresh-xmla` for a refresh, nothing joins them to a timeline | `incident-triage` (new): reads `ad-fleet history`, the run's status command, the refresh's last status, writes a timeline with the first failing step; proposes, never restarts | medium | balanced preferred |
| 6 | "what changed since last week", "who touched this file", "when did this break" | nothing; `codebase-map` builds a graph, not a history | `repo-history` (new): `git log --since` / `git log -S` / `git blame -L`, bounded, a one-page answer | cheap | either |
| 7 | "where does this column come from", "which tables feed this view", "what breaks if we drop X" | nothing for warehouses; `pbip-projection` answers it for a model | `warehouse-lineage` (new): the engine's catalog views (`DBC.TablesV`, `ALL_DEPENDENCIES`, `SHOW CREATE`) through the query skills, a lineage page | medium | either |
| 8 | "review this SQL", "is this query right", "will this be slow" | `ad-sql-check` lints inside the query skills; no route for SQL the user hands over | a row in `data-router` → the engine's query skill with `--dry-run`-style lint only; a skill only if EXPLAIN is wanted | cheap | either |
| 9 | "my setup is broken", "doctor says fail", "ad-td is not recognized" | router step 8: `--want access`, stop | `setup-repair` (new): runs `ad-doctor --quiet`, maps every fail row to the exact `ad-setup --patch <target>` line, prints them; never runs the wizard (it waits on a keyboard) | cheap | either |
| 10 | "move all the tickets in the sprint to done", "label these", "bulk" | `jira-transition`, one at a time, one approval each | `jira-bulk` (new) over `ad-jira transition` with a key list: one dry-run table, one approval, N moves; refuses more than 25 without `--yes-really` | dear | either |
| 11 | "write the release notes for the sprint", "what shipped" | the chain `jira-changelog` → `confluence-publish` works if the user asks twice | a `## Project routes` row per project, not a skill: the chain exists; the row names it | medium | either |
| 12 | "run this analysis in a notebook", "pandas over the extract", "a quick chart of" | nothing; the `pandas` extra exists and no skill uses it | `notebook-run` (new): a bounded Python run over `.agent/out/` files, output under `.agent/out/`, no network, no warehouse; `dataviz` rules for a chart | medium | balanced preferred |
| 13 | "the dataflow", "the pipeline", "the lakehouse table" (Fabric items that are not a report or a model) | `pbi-router` has no row; a spike | `fabric-items` (new) under `pbi-router`, once `ad-pbi ls --kind` lists them; read-only first | medium | either |
| 14 | "who uses this report", "usage of the dashboard" | nothing; `pbi-observe` is performance | `pbi-usage` (new) under `pbi-router`, if the tenant exposes activity events to `ad-pbi` | medium | either |
| 15 | "I can't see workspace X", "need access to" | router step 8 | a `--want access` with the exact scope is already the right outcome; a skill would add nothing | — | — |
| 16 | "send a summary to the team", "email the findings", "post in Teams" | nothing, correctly: the fleet has no write path to mail or chat, and should not grow one from a skill | `friction-log` type `contract`, by name, so the stop is deliberate rather than a mis-route | — | — |

Rows 1 and 2 are the two **mis-routes** the scan found: both exist today as a wrong row or a missing one and both
have cheap, read-only owners. Rows 3–6 are the cheap-and-frequent band. Rows 7–14 wait on a verb or a tenant fact
(the Confluence page verb, Fabric item kinds, activity events) and on friction counts. Rows 15 and 16 are the two
where the research says *do not build*: the existing outcome is the right one and only needs to be reached by
name.

## Measurements — before any candidate is built

Each row is a `docs/windows-verification.md` sitting; the first four are the October-on-`balance` measurement.

| | Measure | How | Decides |
|---|---|---|---|
| M5 | premium requests per turn on `balance` vs September's `efficiency`, same ticket shapes | `ad-fleet spend --since 7d` after the first week; `per_turn` in the ledger | whether the 20% reserve is right, and whether `balance` is affordable at all |
| M6 | the cost of one `research-spike` | the spike sessions' `premium` in `sessions.json`, first ten | whether 12 calls is the right bound |
| M7 | the cost of the sub-router hop | `turns` and `premium` on tickets whose first skill is a sub-router vs those whose first skill is a leaf | nothing to change unless it is more than a few percent |
| M8 | the day the reserve bites, if it does | `credits_why` in `ad-fleet status`, daily | the reserve percent for November |
| M9 | the friction files of type `coverage-gap`, by recommended route | the architect pass, step 7 | which candidate is built first |

## Slices

### A — this PR: the index, the spike, the phases, the reserve, `jira-comment`
Built. Acceptance: `tests/test_skills.py`, `tests/test_skill_handoffs.py`, `tests/test_routing_friction.py`,
`tests/test_fleet_credits.py`, `tests/test_state.py` green; `ad-fleet status` prints `credits:`; every sub-router
is a row of the top table and ends in `research-spike`.

### B — one week on `balance`: M5–M8
Nothing to build. The operator sets `fleet.credits.allowance` to 50000 on `/settings`; a week later
`ad-fleet spend` answers M5 and this page's September/October table gets its October column.

### C — the two mis-routes: `confluence-read` and `pr-review`
Each ≤ 40 lines, read-only, one row in its router. `confluence-read` is `pncli confluence get-page`
directly plus `ad-view` (0.20.0); `pr-review` needs no new verb either.

### D — the cheap band: `data-profile`, `tabular-export`, `incident-triage`, `repo-history`, `setup-repair`
In the order M9 ranks them. Each is a row in a sub-router that has 17–19 rows of room, so none forces a split.

### E — the rest, by friction count
Rows 7–14, each when M9 shows two `coverage-gap` entries recommending it, or its verb lands.

## Decisions for the operator

1. **The reserve.** 20% is a guess at a safe floor; M5 and M8 replace it. Is a step-down enough, or should the
   reserve also deny `start` of a *new* ticket (the stop `plan-meter.md` §Caps declined on 2026-09-22)?
2. **An explicit `intelligence`.** Today the reserve steps every tier down, including one the operator set by hand
   for one agent. Should a per-agent `fleet.agents.<repo>.copilot.auto_tier` be exempt?
3. **Spikes under a ticket.** A spike's cost lands on the active ticket's agent. Should `research-spike` refuse when
   that agent is within two turns of its `fleet.budget_per_agent`?
4. **Slice C's order.** `confluence-read` first (cheaper, more frequent) or `pr-review` first (the one with no
   dependency)?

## Where everything is written down

- `skills/router/SKILL.md` and the five sub-routers: the tables and their preconditions.
- `skills/research-spike/SKILL.md`: the budget, the page, the two endings.
- `agentdata/fleet/credits.py`, [fleet-lifecycle.md](fleet-lifecycle.md) §The budget, [setup.md](setup.md) §The
  fleet's settings page: the allowance, the reserve, the status line.
- `agentdata/state.py` `PHASES` and `skills/state-update/SKILL.md`: the working phases.
- `prompts/remediate-from-friction.prompt.md` step 7: what the architect does with a `coverage-gap`.
