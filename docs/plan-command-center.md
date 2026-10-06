# Plan: the Command Center — your open tickets with boundaries, seated at free agents, started at once

_Status: BUILT (2026-10-06) — the operator answered the four questions (§Decisions), and slices A–E are built
on this branch (§As built); of F, the docs are written, and the demo with a fake Jira and the laptop's measure
are not._

The operator, 2026-10-06:

> We can begin exploring the "Command Center", which will enhance the desk by allowing a user to 1) take all of the
> open Jira tickets assigned to a user and where applicable slate them to begin work. Command center should only be
> possible for Jira tickets that have Acceptance Criteria / Done state's so that an agent can have boundaries. It
> should never begin work on tickets that have short/generic descriptions or no descriptions at all. In the command
> center option, all agents start at the same time, but once that happens, they gate wherever they gate.

## Why this exists

Today a ticket reaches an agent one at a time: dragged from the board onto a tile, read on the dispatch card
(#164), started with a press. The morning is therefore a dozen drags and a dozen cards for work that was already
decided in Jira, when the operator was assigned it. The fresh day (#508) is the only "every agent at once" the desk
has, and it can only restart each agent on the ticket it already holds.

| What the operator wants | What the desk does today | Section |
|---|---|---|
| every open ticket assigned to me, in one place | the board lists them (`board.py`, `assignee = currentUser() AND statusCategory != Done`), one row each, with no description | §The slate |
| only tickets an agent can finish, because their done is written down | the pre-flight *guesses* criteria from the description and calls a ticket without them `thin`, a courtesy the card lets you start anyway (`preflight.py`) | §The gate |
| never a ticket whose description is short, generic or empty | the pre-flight counts words (`THIN_WORDS = 25`); nothing recognises a template or boilerplate | §The gate |
| each ticket to an agent that is free to take it | `board.suggest` names a checkout by the key's project, and none when two checkouts declare one | §The seating |
| all of them started at once | `supervisor.start` per ticket, from a card; the fresh day starts many, on their current tickets | §The start |
| then each stops where it stops | already so: questions, approvals, friction, budget gate a started agent on its own pane | §After the start |

## What is reused

- **The board** (`agentdata/fleet/board.py`): the JQL, the cache in `<fleet dir>/board.json`, `GET /api/board`, the
  credentials pncli already holds (`cli_jira._client`). The slate is the board's query; what grows is the fields it
  carries.
- **The pre-flight's two readings** (`agentdata/fleet/preflight.py`): `criteria_found` and the `description` row.
  The Command Center's gate is those two rows made strict, never the pre-flight's overall verdict, which also turns
  `thin` for a model, a history or a mention that have nothing to do with the ticket's boundaries.
- **The guard rails** (`supervisor.check_ticket`, `supervisor.start`): `cross_project`, `ticket_done`, `live_agent`,
  `mid_ticket`, `foreign_session`, `external_session`. A seat is a checkout `start` would accept.
- **The fresh day's shape** (`fresh.py` `plan_all` / `_plan_id` / `run_all`; the day strip in `index.html` /
  `app.js` `drawDayPlan` / `runDay`; `POST /api/fresh {all, dry_run}`): a preview that judges every row, a plan id
  that changes when the plan does, ticks the operator sets, one press, and each row reporting what happened to it.
  The Command Center is a third mode of that strip.
- **The dispatch card's prompt and brief** (`launch.DEFAULT_PROMPT`, `handoff.py`): what an agent is told when a
  ticket is given to it, unchanged.
- **Every gate after the start** (`agentstate.classify`, `ad-state ask`, `approval.require`, friction logs, the
  pane's asks and approval cards, notifications): nothing new.

## The Command Center, in four steps

### The slate

The board's query, with the fields the gate needs:

- `description`, flattened to text. On Cloud a description is Atlassian Document Format; the repo writes ADF
  (`jira_workflow.adf`) and reads none. A small ADF→text walk (paragraphs, headings, list items, task items, code)
  is part of slice A, and so is the plain description Data Center already returns.
- The **acceptance criteria field**, when the instance has one. Many Jira setups keep criteria in a custom field
  ("Acceptance Criteria", sometimes "Definition of Done"); `ad-jira fields --like acceptance` finds its id, and it
  is pinned the way Sprint and Story Points are (`ad-jira fields --pin`, a `fleet.jira.criteria_field` setting).
- `issuetype` and `status`, already fetched, now used: an Epic is not a unit of work an agent finishes, and a
  ticket already in progress may be in a person's hands (§Decisions, 3).

`board.normalize` keeps today's eight fields and gains `description` and `criteria`; the cache's validity grows
from "the JQL" to "the JQL and the fields", so pinning a field shows on the next read.

### The gate: boundaries, or it is not slated

A ticket is **ready** only when both hold, and **not ready** otherwise, with every reason that failed. Not ready is
never tickable: the operator's word was *never*, so this is a gate, not the pre-flight's courtesy.

1. **It has boundaries.** At least one acceptance criterion, read from:
   - the criteria field, when one is pinned and it is not empty; or
   - a section of the description headed *Acceptance Criteria*, *AC*, *Definition of Done*, *Done when* or
     *Success criteria*, with at least one item under it (a bullet, a number, a checkbox, a Given/When/Then); or
   - Given/When/Then lines anywhere in the description.

   Two bullets that happen to be in the description are **not** criteria (the pre-flight counts them today), and
   inline `AC: 1) …` is (the pre-flight misses it). `criteria_found` is tightened, with the fixtures that prove
   both, and the pre-flight's own row gets the fix too.
2. **Its description says what to do.** Outside the criteria, at least `fleet.command.min_words` words (40 by default, the
   operator's choice; the pre-flight's `THIN_WORDS` is 25), and none of these:
   - empty, or the summary repeated;
   - placeholder words standing in for a specification: *TBD*, *TODO*, *see title*, *as discussed*, *per
     conversation*, *details to follow*, *N/A* — when they are most of what is there;
   - a template with its headings and nothing under them (the project's own Jira template is read from the
     instance's most common empty headings, or listed in `fleet.command.template_headings`).

The gate is one pure function, `command.ready(ticket) -> {ready, criteria, words, reasons}`, so the desk, the CLI and
the tests read the same verdict. Its reasons are sentences the row prints, the pre-flight's way: *"no acceptance
criteria: the agent would have to invent what done means"*, *"14 words outside the criteria"*, *"the description is
the template's headings and nothing else"*.

### The seating: one ticket to one free agent

A ready ticket is seated at a checkout:

- **of its project** — the key's prefix against the registry's `jira_project`, as `board.suggest` does today;
- **that is free** — no live turn, no session someone else holds, no other active ticket mid-way, not over budget:
  `fresh.judge`'s reading and `supervisor.start`'s refusals, asked *before* the press, so a row never says "ready"
  and then fails;
- **one ticket each** — a checkout holds one agent and one agent works one ticket (the fleet's first rule). With
  more ready tickets than free checkouts of a project, the rest wait, in Jira's order (priority, then updated), and
  say so: *"waiting for a desk — every RDSD checkout has a ticket"* (§Decisions, 2).

A ticket another agent already holds (`active_ticket` on some checkout) is shown as *already with* that agent and
is not seated again.

### The start: one press, every chosen agent

The strip shows every assigned open ticket: ready ones ticked and seated, not-ready ones greyed with their reasons,
waiting ones with theirs. One button: **start N — about N premium turns**. The press posts the plan id and the ticked
`(ticket, checkout)` pairs; the server checks the plan has not changed, judges every pair again (a free checkout may
have been taken since), and starts them back to back — the same moment as far as anyone at the desk can tell (§Cost). Each row then says *started*, or the refusal that stopped it, and the others start
regardless: one refusal never holds back the rest.

### After the start

Nothing new. Each agent runs `session-bootstrap`, then `router`, then `jira-triage`, and gates where it gates: a
question (`ad-state ask`) on its pane's asks card, a Jira transition or a PR on its approval card, a friction log on
its why line, a budget on its Send. The desk's *needs me* preset gathers the ones that stopped. The Command Center
does not chase them; the panes are where the operator answers.

## On the desk

- The day menu gains **command center…** beside *start the day fresh* and the two sweeps; `?command=1` opens it
  (preview only), as `?fresh=1` opens the fresh day.
- The day strip's third mode (`dayKind`: `fresh`, `sweep`, `command`) and its pattern row: the tick, the key, the
  summary, the checkout it is seated at (a picker when the project has several free), the verdict
  (`ready`, `not ready`, `waiting`, `already with …`), the criteria count, the words, and the reasons.
- *start N* is disabled at N = 0; the strip says how many were not ready and why in one line above the rows.

## The server and the CLI

- `POST /api/command {dry_run: true}` → `{plan_id, rows: [{key, summary, verdict, reasons, criteria, words, repo,
  repos}], counts}`; `POST /api/command {plan_id, start: [{key, repo}]}` → each row's result and its pane's new
  row. Refusals: `preview_first`, `plan_changed`, `not_ready` (a ticket the gate refuses, however it was posted),
  `seat_taken`, `cross_project`, and every `supervisor.start` refusal by its own code.
- `ad-fleet command --dry-run` prints the plan; `ad-fleet command --confirm <plan_id>` starts it. The CLI and the
  page call the same two functions, `command.plan()` and `command.run()`.

## Slices

| Slice | What | Proof |
|---|---|---|
| A — the slate | the board carries `description` (ADF flattened) and the pinned criteria field; the cache keyed on the fields | `test_fleet_board.py` grows the row; ADF fixtures from a Cloud response; a Data Center fixture |
| B — the gate | `command.ready` and the tightened `criteria_found`; the reasons | a table of tickets that must pass and must fail: inline `AC:`, a DoD heading, Given/When/Then, two stray bullets, a template, *TBD*, the summary repeated |
| C — the seating | free checkouts per project, one ticket each, the waiting rule, *already with* | registries with one, two and three checkouts of a project; live, mid-ticket, foreign and over-budget agents |
| D — plan and run | `command.plan` / `command.run`, the route, the CLI, the plan id, the refusals | the fresh day's tests as the model: preview first, plan changed, one refusal among five starts |
| E — the strip | the day menu item, the third mode, the row, the start | a browser test on the demo fleet: three ready, two not ready, one waiting; *start 3* starts three panes |
| F — proof | docs (fleet-intake.md §The Command Center, refusals.md), the demo, the laptop's measure | the demo fleet with a fake Jira |

## As built (2026-10-06)

- **The slate is its own, not the board's.** `command.slate` asks the board's query (`fleet.jql`) with
  `description` and the criteria field, and caches the answer in `command.json` under its own key (the query,
  the pinned field, `fleet.board_ttl`). The board's row, its fields and its cache are unchanged, so nothing that
  reads the board pays for two more fields; `test_fleet_board.py` did not grow.
- **The gate is the Command Center's.** `command.ready` and `command.criteria`; the pre-flight's
  `criteria_found` is untouched, because the dispatch card's word count is a courtesy and stays one.
- **The criteria field is found by name** (*Acceptance Criteria*, *Definition of Done*) through `/field`, once a
  day, when `fleet.command.criteria_field` pins none; a pinned name or id wins.
- **The plan id** is a hash of every row's ticket, verdict, seat and tick: a slate or a seat that moved between
  the preview and the press refuses the press (`plan_changed`).
- **The proof** is `tests/test_fleet_command.py`: the gate's table (eleven tickets that must pass or fail), Cloud's
  and Data Center's text, the slate's one query and its cache, the seating, the start, the route and the CLI, and
  the day strip in a browser.

## Ground rules

- **Never an automatic start.** The operator presses *start*; nothing is slated at boot, on a timer, or when an
  agent finishes (the decisions in fleet.md §What it deliberately is not and fleet-intake.md §Not here stand).
- **The gate is a gate.** A not-ready ticket has no tick, and the server refuses it if it is posted anyway; the
  dispatch card stays the door for starting a thin ticket on purpose, one at a time, with a brief.
- **Jira is read, never written.** The Command Center transitions nothing; agents ask for their transitions as they
  do today (dry run, approval).
- **No new state machine.** A started agent is an agent: its pane, its gates, its spend.

## Build order

A, B and C are independent of the page and of each other's internals: B and C can be built against fixtures while
A is in review. D needs all three; E needs D.

## Decisions (the operator, 2026-10-06)

1. **Acceptance criteria: both.** The pinned criteria field when the instance has one, otherwise a section of the
   description headed *Acceptance Criteria* / *AC* / *Definition of Done* (and Given/When/Then anywhere).
2. **Seating: one each, the rest wait.** Each free checkout takes one ticket; the others say *waiting for a desk*,
   in Jira's priority order, and start on a later press.
3. **Open means To Do.** Only tickets not yet started are slated; *In Progress* ones are listed as *in progress —
   not slated*, since a person may hold them.
4. **Forty words.** A description needs 40 words outside its criteria (`fleet.command.min_words`, default 40), and
   must not be empty, the summary repeated, placeholders or a bare template.

## Cost

- **Premium turns:** one per started agent at the start, as the fresh day says (*about N premium turns*), and then
  whatever each agent spends until it gates.
- **Jira:** the board's one search, with two more fields; no per-ticket fetch (the pre-flight's per-issue `pncli`
  call is not used — it was one subprocess per ticket).
- **Time:** a preview is the board read plus one pass over the registry; a start is N `supervisor.start`s back to
  back. A `send` launches its process in about 20 ms on the laptop since #654; `start` writes a brief and a prompt
  first, and slice D measures it — the expectation is ten agents inside a second. Measured on the laptop
  (2026-10-06, ten checkouts, 27 tickets, a fake Jira and the launch faked): a preview in 8–15 ms, and the press
  re-plans and starts ten in 0.23 s, 23 ms each before its process; with the launch's ~20 ms each, about half a
  second for ten.
