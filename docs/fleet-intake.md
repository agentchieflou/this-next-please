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

## The dispatch card (#164)

A drop used to be a launch. It opens a **card** on the tile instead, and the start is the card's
button. The card is built by a pre-flight that runs on the server, **spends no premium request**,
and reads only what the fleet already holds or can fetch once:

| Row | Source | Says |
| --- | --- | --- |
| ticket, repo | `board.suggest`, `supervisor.check_ticket` | the existing guard rails, with their `code` |
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

## Configuration

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.jql` | `assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC` | which tickets the board shows |
| `fleet.jql_fields` | `key,summary,status,priority,issuetype,updated` | what it asks Jira for |
| `fleet.board_ttl` | `120` | seconds a fetched board is reused — and a pre-flight's issue read with it |
| `fleet.preflight` | `true` | a drop opens the dispatch card; `false` starts immediately, as it did before #164 |

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
