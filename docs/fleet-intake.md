# Giving a ticket to an agent

Delegating specific Jira tickets to specific agents should not mean copying keys out of a browser.
The dashboard shows your own tickets, and a ticket goes to an agent by being dragged onto its tile.

```bash
ad-fleet board
```

```
meta:
  ok: true
  source: ad-fleet board
  tickets: 3
  jql: "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
  from: "cache, 41s old"
board[3]{key,status,type,summary,repo,why}:
  RDSD-101,In Progress,Story,Six measures are unused,luna,luna declares jira_project RDSD
  RDSD-118,To Do,Task,UAT refresh is slow,luna,luna declares jira_project RDSD
  DATAENG-9,To Do,Story,Somebody else's problem,-,`ad-fleet repo add <path>` for the DATAENG checkout
```

**No new credential.** This runs on the token pncli already stores, exactly as `ad-jira changelog`
does. A fleet that asked for a second login would not get used.

**Read-only, always.** Nothing in the intake path can transition, comment or assign. Only agents
write to Jira, and only through the approval gate ([fleet-approvals.md](fleet-approvals.md)).

## Which repo does a ticket belong to?

Every registered repository already declares its `jira_project` in `AGENTS.md`, and a Jira key
carries its project in front of the dash. That is the whole matching rule, and it gives three
answers — each of which the panel shows honestly rather than papering over:

| Case | What you see | Why |
| --- | --- | --- |
| one repo declares the project | `→ luna`, and a drag has an obvious home | unambiguous |
| several declare it | a **pick one** with a button per repo | guessing would eventually start the wrong checkout, and twenty minutes of an agent editing the wrong repository is expensive and quiet |
| none declares it | `` `ad-fleet repo add <path>` for the DATAENG checkout `` | the repository is not registered yet, which is a one-line fix worth naming |

## A prompt that belongs to no ticket yet

The board answers *which repo is this ticket's*. The other direction -- *which ticket is this prompt's* --
is the agent's question, and since 2026-10-03 it is computed rather than guessed: the router's step 3 runs
`ad-jira match "<the request>"` whenever a request names no key, **including when a ticket is already active**,
so a one-off prompt is never silently charged to the ticket that happened to be open.

```
ad-jira match "the committed points on the sprint chart look wrong again"
meta:
  ok: true
  verdict: match
  next: ask-and-continue
  ticket: RDSD-118
  active_ticket: RDSD-101
  why: RDSD-118 shares committed, point, sprint, chart (score 0.8)
  ask: ad-state ask "This reads like RDSD-118 (Committed points wrong on the sprint chart). Track it there?" --kind ticket --choice RDSD-118 --choice RDSD-101 --choice new --choice none --assume RDSD-118
candidates[2]{key,status,score,shared,summary}:
  RDSD-118,To Do,0.8,chart committed point sprint,Committed points wrong on the sprint chart
  RDSD-101,In Progress,0,-,Six measures are unused
```

It reads the same board this page shows (the fleet's cache, the operator's own open tickets, narrowed to the
project's `jira_project`), scores each on word overlap with the summary (`agentdata/jira_match.py`), and prints
the one `ad-state ask --kind ticket` line the router runs. The verdicts: `named` (a key in the prompt), `active`
(the open ticket fits as well as anything), `match` (assumed, and shown on the tile with the runner-up keys as
choices, because re-scoping is reversible), `weak` / `none` (untracked under `ticket_policy: optional`, with the
reminder on the tile; a stop under `required`), and `create` (the operator answered `new`: the next turn is
`jira-create`, which builds the ticket from the project's `jira_*` facts so it lands on this board).

**The answer is the move.** `ad-state answer <id> RDSD-118` sets `active_ticket` itself; `none` untracks the work;
`new` is reported as `next: jira-create`. Nothing here writes to Jira: the only write is the ticket the operator
asked for, through `jira-create`'s dry run and the approval gate.

**Unticketed work, fleet-wide.** `ad-fleet board` adds an `untracked` table -- every registered checkout's open
ticket question, with the keys it offered -- so the operator sees from one page which agents are working on
something no ticket owns, and answers from the tile.

## The dispatch card (#164)

A drop used to be a launch. It opens a **card** on the tile instead, and the start is the card's
button. The card is built by a pre-flight that runs on the server, **spends no premium request**,
and reads only what the fleet already holds or can fetch once:

| Row | Source | Says |
| --- | --- | --- |
| ticket, repo | `board.suggest`, `supervisor.check_ticket` | the existing guard rails, with their `code` |
| model | `launch.model_for` and the cached model list (`models.json`, never the CLI) | `opus-5 · fleet.models.luna`, `the CLI chooses · cli-auto`; `thin` when the installed CLI's list no longer offers it (#368) |
| description | one `ad-pncli jira get <KEY>`, cached for `fleet.board_ttl` | `412 words` / `4 words` / `empty` |
| criteria | a heuristic over the description — numbered, checkbox, an *Acceptance Criteria* heading, or *Given/When/Then* | `3 found` / `none found` |
| comments, attachments | counts from the same read | where a human has often already answered |
| mentions | the names it mentions, through the catalogue | `Velocity — luna declares it`, and when the match is in **another** repo, that |
| history | `ad-fleet history` for this key | `dispatched 2 times; ended blocked` |
| here | `.agent/in/<KEY>/`, and a `feature/<KEY>-*` branch | `2 files already attached` |

The verdict is one of four words, from one table in one function — the first rule that matches wins,
and a refusal outranks an unreadable source, which outranks a judgement:

| Verdict | Means | The button |
| --- | --- | --- |
| `ready` | nothing to flag | *Start* |
| `thin` | short or empty description, no criteria found, or a history that ended blocked | *Start anyway*, with the brief box focused |
| `blocked` | one of the guard rails above would refuse | *Start anyway* — the refusal is still the server's to give |
| `unknown` | a source could not be read | *Start anyway* — the pre-flight is a courtesy |

**Being unable to reach Jira never blocks a start**, exactly as the Done check never has: the rows
go grey with the error in their `why`, the verdict reads `unknown`, and the button still works.

**Runs on** (#368). Under the rows the card says which model the agent will start on, as pills:
the one in force, *inherit*, the fleet's default and the model the last turn ran on, and `more…`,
which opens the model card for everything else. A press writes the repository's model — this start
and every later one, through the settings page's own writer — and the note says so, and the card's
`model` row is read again on its own (never a Jira read), so it is current at once. The `model`
row is `thin` only when the cached list marks the model as not offered by the installed CLI (since
CLI 0.0.421 a turn on such a model fails at start); when it is the only thin row, the note says why
and the keyboard goes to the pressed pill rather than the brief. It never blocks a start. Every key
but `Esc` stays in the card, so a pane's `h`, `a` and `j` do not act while the card has the keyboard.

```bash
ad-fleet preflight RDSD-118 --repo luna
```

prints the same card as TOON, and exits 0 whatever the verdict — a verdict is an answer, not a
refusal. `fleet.preflight: false` restores the immediate start this section replaced.

### The brief

The card's text box is the operator's own words, and they are new information that exists nowhere
else — not a stale copy of Jira. On *Start* they are written to `.agent/in/<KEY>/brief.md` with
`by`, `at` and `ticket` in front matter, recorded as a `handoff.brief` event, and the `inputs` line
is *asked* of `ad-state` the way [the inbox asks it](fleet.md). Then the agent is spawned.

```bash
ad-fleet start luna RDSD-118 --brief "the window is the last full sprint; ignore UAT"
ad-fleet start luna RDSD-118 --brief-file .agent/notes/rdsd-118.md
```

**A brief that cannot be written refuses the start.** The operator has just typed the one thing
nothing else in the system knows; launching an agent that was promised it and will not find it is
worse than not launching. See [fleet-handoff.md](fleet-handoff.md) for the directory's five rules.

## The panel

Press `b`. Search filters by key, summary or status. Then either:

* **drag a ticket onto a tile** — any tile, including one whose project does not match; this opens
  the dispatch card above, the guard rails below still apply, and the page offers the cross-project
  override once rather than silently applying it;
* **click "start on `<repo>`"** on the row, which appears once per candidate repository.

`refresh` asks Jira now instead of using the cache — the same as `ad-fleet board --refresh`.

A collapsible strip underneath shows what was dispatched in the last seven days — the same data as
`ad-fleet history`.

## The guard rails

They live in `ad-fleet start`, so the CLI and the page share them rather than each having their own
idea of what is safe:

| Refused when | Override |
| --- | --- |
| the repository already has a live agent | `--force` (which replaces it, never runs a second one) |
| `state.json` holds a different `active_ticket` in a non-terminal phase | `--force` |
| the key's project is not the repository's `jira_project` | `--cross-project` |
| the board says the ticket is already Done | `--force` |

The last two are new here, and each prevents something quiet:

* **Wrong project.** Starting the RDSD checkout on a DATAENG ticket produces an agent that branches,
  reads and edits the wrong repository for twenty minutes before anyone notices.
* **A finished ticket.** An agent given a Done ticket has nothing to do and will invent something,
  because "there is nothing here" is not an answer a router is built to give.

**Being unable to reach Jira never blocks a start.** The Done check reads the board only if it is
already cached; the project check needs nothing but the key and `AGENTS.md`. The board feeds a
courtesy, not a gate.

## What the agent is told

```
Ticket RDSD-101: Six measures are unused. Invoke skill session-bootstrap, then router.
```

The key and one line, and deliberately nothing more. `jira-triage` does the reading through
`ad-pncli`, as its SKILL.md says; a fleet that pasted acceptance criteria into the prompt would hand
the agent a second, staler copy of the ticket to trust. The summary is fetched once, at dispatch,
and written into the `started` event so a tile can show it without another Jira call.

A `fleet.prompt_template` written before `{summary}` existed still works — the placeholder is
optional, and losing the summary is a smaller harm than refusing to launch over a config file
somebody wrote three months ago.

## What I dispatched

```bash
ad-fleet history --since 7d
```

Key, repo, when it started, how it ended, how many turns, what it cost. Read from the event store
([fleet-events.md](fleet-events.md)) and nothing else, so it agrees with the tiles by construction
rather than by a second bookkeeping file somebody has to remember to write.

A run with no `exited` event is still a run — it was killed, and hiding it would hide exactly the
interesting case. A `started` event marked `resumed` is **not** a new dispatch: `ad-fleet send`
emits one too, and counting it would double every ticket in the report the moment anyone talked to
an agent.

## The Command Center

The operator, 2026-10-06: *"take all of the open Jira tickets assigned to a user and where applicable slate
them to begin work ... only ... tickets that have Acceptance Criteria / Done state's so that an agent can have
boundaries ... never ... short/generic descriptions or no descriptions at all ... all agents start at the same
time, but once that happens, they gate wherever they gate."* The design and its four decisions are in
[plan-command-center.md](plan-command-center.md).

The desk's *day* menu → **command center…** (or `ad-fleet command --dry-run`, or `?command=1` on the desk's
address) previews every open ticket the board's query returns (`fleet.jql`), each with a verdict:

| Verdict | What it means |
|---|---|
| `ready` | it has acceptance criteria and at least `fleet.command.min_words` (40) words of description outside them, and a free checkout of its project: ticked, and seated there |
| `not_ready` | no criteria, too few words, the summary over again, placeholders (*TBD*, *as discussed*) or a template's headings with nothing under them: never tickable, and the reason is on the row |
| `waiting` | ready, but every checkout of its project has a ticket: it starts on a later press |
| `held` | a checkout already has it as its active ticket |
| `in_progress` | In Progress in Jira: a person may hold it, so it is not slated |
| `not_work` | an epic, or a status that is not To Do |
| `no_checkout` | no registered checkout declares its project |

Criteria are read from the instance's *Acceptance Criteria* (or *Definition of Done*) field when it has one —
`fleet.command.criteria_field` pins a field by id or name — and otherwise from the description: a section
headed *Acceptance Criteria*, *AC*, *Definition of Done*, *Done when* or *Success criteria*, an inline
`AC: 1) … 2) …`, or Given/When/Then lines. Cloud's rich text and Data Center's wiki markup are both read.

A free checkout is one `start` would take a new ticket in without `--force`, and not over its budget. Ready
tickets are seated in priority order, one to a checkout. **start N — about N premium turns** starts every
ticked pair back to back; a plan that moved since the preview is refused (`plan_changed`), and a ticket or a
seat that no longer qualifies is refused on its own row while the others start. Then each agent runs as if it
had been dragged onto its pane: its questions, approvals and friction show there.

The Command Center reads Jira and never writes it, and nothing is slated without the press.

## Configuration

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.jql` | `assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC` | which tickets the board shows |
| `fleet.jql_fields` | `key,summary,status,priority,issuetype,updated` | what it asks Jira for |
| `fleet.board_ttl` | `120` | seconds a fetched board is reused — and a pre-flight's issue read with it |
| `fleet.preflight` | `true` | a drop opens the dispatch card; `false` starts immediately, as it did before #164 |
| `fleet.command.min_words` | `40` | words of description outside the criteria the Command Center's gate asks for |
| `fleet.command.criteria_field` | none | the field the criteria are kept in, by id or name (a comma between several); none looks for *Acceptance Criteria* or *Definition of Done*, once a day |

The TTL is not a detail. The board is a *view of a queue*, not a live feed: a ticket that appeared
thirty seconds ago is not urgent, and a search per tile per tick is how a shared Jira instance
starts rate-limiting the whole team. Five callers asking every five seconds for ten minutes is 600
requests; with the default TTL it is **five**, and there is a test that counts them.

A bad JQL comes back with Jira's own error text as the hint — "the query failed" tells nobody which
clause they mistyped.

## Not here

Auto-pulling the next ticket when an agent finishes: declined for now. The manual path comes first,
and the event store makes it a small follow-up when it is wanted. Writing to Jira from the panel:
only agents write, through the gate. Jira Cloud's own "Copilot for Jira" assignment is a different
product — it runs GitHub's hosted agent, not this one.
