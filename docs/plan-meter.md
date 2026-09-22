# Plan: the meter — every tile says what its agent has spent, against what, on which model; and the caps come later, named

_Status: IMPLEMENTED (2026-09-22) — epic #201 (slices #209–#214), under #91 (the fleet) and #122 (the desk), a
sibling of #101 (whose cost strip never shipped), #170 and #179, and one of three plans written from the same
photograph as [plan-column.md](plan-column.md) (#200) and [plan-ownership.md](plan-ownership.md) (#202). The
operator's sentence is recorded in §Decisions; the one decision that shapes this plan — **meter first, caps later** —
was asked for and given before it was written. Every number this plan puts on a tile is to be checked against the
laptop's real `~/.copilot` and a real tenant, the way #92 checked the spike's._

## Why this exists

The operator's sentence: *what we're missing right now is the reliability and reassurance that a user won't blow
through their tokens.* Read against the code, the reassurance is missing for reasons that are not one bug:

| What the operator needs | What the code does | Section |
|---|---|---|
| To see, on the tile, what this agent has spent | `premium_requests` and `turns` are in every `/api/fleet` row (`serve.py:483` spreads the fold) and **`app.js` renders neither**. The only cost pixels on the page are the *earlier sessions* list (`app.js:782–783`), the history strip (`app.js:1913`) and a transcript line for a `cost` event (`app.js:120`). [fleet-dashboard.md](fleet-dashboard.md) §What is not here says *cost and budget are a strip in #101*; #101 closed without one | §The meter |
| To see it against a budget | `fleet.budget_per_agent` is off by default (`lifecycle.py:225`), enforced in **one** place — `supervisor.send()` (`supervisor.py:506–514`, *before the turn, never during one*) — and not in `start`, `restart`, `console` or `reset`. The desk calls `send` with no `force` (`serve.py:1406–1413`) and has no `budget_exceeded` branch, so an over-budget agent is simply unreachable from the page; `ad-fleet send --force` (`cli_fleet.py:1446`) is the only door | §The refusal |
| One number that means one thing | `agentstate.Fold` takes the **max** of `cost` events (`agentstate.py:118`, per [fleet-events.md](fleet-events.md) §cost: *the CLI reports the session total so far … a reader takes the maximum and never a sum*); `supervisor.agent_state()` takes a **sum** of raw `result.usage.premiumRequests` (`supervisor.py:261–263`). `ad-fleet status` prints the sum; the tile, history, sessions and the budget use the max. Same column name, two arithmetics, two files. `turns` is split the same way (`supervisor.py:276` vs `agentstate.py:77`). And whether `result.usage.premiumRequests` is a turn's or a session's is **unmeasured**: the spike says *exact and per-turn* (`fleet-spike.md:187`), the events page says session total, `events.py:238–240` folds both into one kind, and the fake transcript (`tests/fakes/copilot/transcripts/triage-ok.json`) makes them equal | §One arithmetic |
| A number that does not vanish | `lifecycle.rotate_all` rotates `events.norm.jsonl` with the raw log (`lifecycle.py:284`) and `events.read()` opens only the live file (`events.py:577–594`), so at `fleet.log_mb` (20 MB) an agent's `spent()` drops to zero, the budget re-opens, and `ad-fleet history` forgets — which `lifecycle.gc`'s own docstring says cannot happen (`lifecycle.py:298–300`: *the live `events.norm.jsonl` is not a candidate at any age: it is what `ad-fleet history` reads*) | §The ledger |
| A fleet total, and *today* | `ad-fleet status`'s `spent_today` is the sum of every agent's **lifetime** high-water mark (`cli_fleet.py:432–436`); nothing records a day. The only per-day counter in the system, `poll.json` (`poll.py:234–246`), counts Jira, Bitbucket and Power BI HTTP requests | §The fleet total |
| The cheap hook the spike found | `--usage-output-file` is passed on every launch (`launch.py:297–299`; `supervisor.py:28, 472, 526, 707`) and **`usage.json` has zero readers**; the spike called it *a simpler cost hook than parsing the stream* (`fleet-spike.md:199–200`). `session.usage_checkpoint.totalNanoAiu` is measured (`fleet-spike.md:167`) and dropped (`events.py:232–233`) | §One arithmetic |
| To see which model is spending it | the lock records `model`, `effort`, `model_source` on every launch (`supervisor.py:481, 532, 713, 780`) and `serve.served_model` reads the model the last turn ran on (`serve.py:2109–2124`); the settings page shows both (#199) and **the tile shows neither** — the `/api/fleet` row has no model field at all (`serve.py:451–484`) | §The meter |
| A budget that can be set without a trap | `fleet.budget_per_agent` is kept **off** the settings page because its reader turns a typo into `0.0`, which turns the cap off (`lifecycle.py:78–86`; `settings.py:11–13` calls it *the cautionary tale*) | §The refusal |

What is deliberately **not** here is any new stop. The operator was asked whether the guarantee should be hard caps
and a meter, a meter first, or a wider per-agent cap; the answer was *meter first, caps later* — show spend, budget
and model on every tile plus a fleet total, keep today's per-agent cap as it is, no new stops yet. §Caps, later
names the stops this plan does not build and the measurement each one needs first, so the plan that builds them
starts from data rather than from this plan's guesses.

**The purpose is the human's attention, and their trust.** Two questions a glance should answer: *what has this cost
me*, *what will it cost me if I do nothing*. Today the first is answered on a settings page and a CLI table that
disagree, and the second is answered by nothing.

## What is reused

- **The billing unit** is premium requests, and only that — the one thing about cost the spike measured
  (`fleet-spike.md:19`, `:167–168`, `:180–187`). No tokens, no dollars: the CLI reports neither and this plan invents
  neither.
- **The `cost` event** (`events.py:232–245`, [fleet-events.md](fleet-events.md) §cost) and the fold's high-water mark
  (`agentstate.py:116–120`). The rule *per session, take the max* stays; what changes is what is done across
  sessions and across days.
- **`lifecycle.spent` / `over_budget`** (`lifecycle.py:218–235`) and `supervisor.send`'s refusal in its exact words
  (`supervisor.py:508–512`: *luna has spent 12 of its 10 premium-request budget · raise `fleet.budget_per_agent`, or
  pass --force for this one turn*). The desk shows these words; it does not write new ones.
- **`sessions.json`** (#171; `sessions.py:250–345`): one row per session with `cost` as a max. The ledger is that
  fold, made rotation-proof and given a day axis.
- **The lock's `model`, `effort`, `model_source`** (#199) and `served_model`, `settings_snapshot` (`serve.py:2106–2165`).
- **The cells row** (`drawCells`, `app.js:1986–2030`): ticket, PR, refresh, git, each with an age. The meter is the
  fifth cell, drawn the same way.
- **The footer** (`#counts`, `index.html:188`): `5 agents · 3 need you`. The fleet total is one more clause.
- **The two-press pattern** — *Reset anyway* (`app.js:393–407`, [fleet-dashboard.md](fleet-dashboard.md) §Reset):
  a refusal first, a deliberate second press. *Send anyway* is the same pattern on the same button.
- **The settings table's rule** (`settings.py:110–146`): a wrong value is refused, never coerced — `bad_type`, never
  `0.0`.
- **`ad-fleet history`** (`board.history`, `board.py:203–260`) and `ad-fleet status --show-launch`'s `models` table
  (`cli_fleet.py:387–415`): the CLI prints what the tile shows, from the same function.
- **The fake `copilot`** (`tests/fakes/copilot/`) and its transcripts with `session.usage_checkpoint` and
  `result.usage` rows (`triage-ok.json:9–16, 50, 74`); the laptop runbook's convention.
- **The HIG** *Feedback*: never present stale content as current; say how old what is shown is. A spend without its
  age is a guess dressed as a fact.

## Prior art, and what is different here

- **A fuel gauge**: one needle, one reserve mark, one warning light that comes on before the tank is empty. The meter
  is that on every tile — a number, the budget it is against, amber at four fifths.
- **Cost lines in coding agents** — a session-cost command in a terminal agent, a usage page in an IDE — show a
  session's total on demand. What is different: the fleet runs five sessions at once, unattended, and the number has
  to be on the glass without asking, per agent and summed.
- **The spike's own rule** (`fleet-spike.md:186–187`): *#101's budget should be expressed in premium requests and read
  from `result.usage.premiumRequests`, which is exact and per-turn.* This plan keeps the unit and measures the claim.

## One arithmetic

The rule, written once in a new `agentdata/fleet/spend.py` and read by everything that prints a number:

```
per session      the high-water mark of every cost event that names it          (max — checkpoints are totals)
per agent        the sum over its sessions                                      (sessions do not overlap)
per day          the sum of the rises: when a session's mark goes from a to b,  (attributed to the day it rose)
                 b − a is spent on the day the event carrying b was written
per fleet        the sum over agents, for a day or all time
```

Two things this needs that the stream does not carry today:

- **The `cost` event says where it came from.** `data.source: "checkpoint" | "result"` — additive, schema 1
  unchanged. Until the laptop answers M1 below, the fold uses checkpoints for the mark and treats `result` as a
  checkpoint too (today's behaviour); the day M1 says `result.usage` is per-turn, the rule flips for `result` rows
  and nothing already written has to be re-parsed.
- **`usage.json` is read**, once, when the process exits: its final usage is compared with the last checkpoint and a
  mismatch is a doctor row (*the CLI's final usage and its last checkpoint disagree by 0.33 — see M1*), never a
  silent choice.

`supervisor.agent_state`'s sum over raw `result` events (`supervisor.py:261–263`) goes; `ad-fleet status`,
`ad-fleet history`, `sessions.json`, the tile and the budget read `spend.py`. `turns` becomes one count the same way
(`turn_ended` in the normalized stream, `agentstate.py:77`). `totalNanoAiu` is kept on the event as `nano_aiu` and
shown nowhere until somebody says what it is.

## The ledger

`~/.agentdata/fleet/agents/<name>/spend.json` — a fold of the normalized stream that is written **before** rotation
and carried forward across it:

```json
{"schema": 1,
 "sessions": {"1f0a…": {"first": "2026-09-22T09:31", "last": "2026-09-22T11:02", "premium": 4.33, "turns": 12,
                        "model": "claude-haiku-4.5", "ticket": "RDSD-118", "ended": "blocked"}},
 "days":     {"2026-09-22": {"premium": 4.33, "turns": 12}},
 "cursor":   {"seq": 2210, "file": "events.norm.jsonl"}}
```

- Updated on every `events.refresh` (`events.py:597`) from the cursor forward, so it costs one read of what the tick
  already reads. `lifecycle.rotate_all` calls it first, then rotates; the ledger's cursor moves to the new file.
- **Rebuildable, never the source**: `ad-fleet spend <repo> --rebuild` folds every `events.norm.jsonl*` on disk, oldest
  first, and the result must equal the incremental ledger — a test asserts it, including across a rotation that
  falls in the middle of a session.
- `lifecycle.spent()` reads the ledger; the budget stops re-opening at 20 MB. `gc` leaves `spend.json` alone at any
  age; its docstring becomes true.
- Nothing in a repository's `.agent/` — the fleet writes only under `~/.agentdata/fleet/`.

## The meter

On the tile, a fifth cell beside ticket, PR, refresh and git — drawn by `drawCells`, aged like them:

```
spend   4.3 premium · of 10 · 12 turns · opus-5      (2m)
```

- `4.3` is the agent's total across its sessions; hovering says *this session 1.3 · today 4.3*.
- `of 10` only when a budget is set; at four fifths the cell is amber with a sentence (*8.1 of 10 — two more turns
  at this rate*, where *this rate* is the mean of the last three turns and is said to be a mean); at the budget it
  is red with the refusal's own words. Never colour alone.
- `opus-5` is the model button [plan-column.md](plan-column.md) C puts on every tile and band — the short name of
  the model the last turn actually ran on, or the configured one with a dot when no turn has run yet; the card
  behind it is that plan's.
- On a band, the number alone after the age: `idle · 3m · 4.3`.

The `/api/fleet` row gains `spend: {session, total, today, budget, turns, rate, age_s}` and `model`, `effort`,
`model_source`, `actual` — the four the settings page already computes per repository (`serve.py:2127–2165`), now on
the tile's row so the page has one source for both.

## The fleet total

The footer reads `5 agents · 3 need you · 12.3 premium today · 41.0 all time`, from the ledgers summed. The
inspector's *project* section gains a **spend** pane — sessions with their cost and how they ended, days with their
totals, the budget — and `ad-fleet spend [repo] [--since 7d]` prints the same table from the same function.
`ad-fleet status` keeps its columns and its `spent_today` becomes what its name says; `spent_total` joins it.

The age is on every number: the footer's total is as old as the oldest ledger it summed, and says so on hover.

## The refusal reaches the desk, and the budget reaches settings

- `POST /api/send` and the answer path (`serve.py:1466–1481`) accept `force`. A `budget_exceeded` answer is drawn on
  the tile's error line in the CLI's words, and *Send* re-arms as **Send anyway** — the second, deliberate press the
  Reset button already has — sending `force: true` for that one turn, the way `ad-fleet send --force` does. The
  cap is unchanged; it is visible and passable from the desk instead of invisible and absolute.
- `fleet.budget_per_agent` joins the settings table: `int`, default `0` (off), scope *in effect now*, why *premium
  requests an agent may spend before its next reply is refused; 0 is off*. The table's `coerce` refuses `""`,
  `"ten"` and `-1` with `bad_type`, so the box cannot turn the cap off by accident — the reason it was kept off the
  page is the rule the page enforces.
- The reader stops swallowing: a non-numeric value in the file is `budget_invalid` — an `ad-doctor` row, a red
  budget cell reading *budget "ten" is not a number — treated as off*, and the same sentence in `ad-fleet status`.
  Off, but loudly.

## Caps, later — named here so the next plan starts from measurements

None of these is built by this plan. Each is listed with the one thing that must be measured on the laptop before it
is designed; slice F makes those measurements while it has the fake and the tenant in front of it.

**Nothing below is built. Each row's measurement is a row in `docs/windows-verification.md`
(M1–M4), and the epic that builds these caps is written from those rows rather than from this
table's guesses.**

| Cap | What it would do | What must be measured first |
|---|---|---|
| `--max-ai-credits` per launch | the CLI's own per-session ceiling, on the measured flag list (`fleet-spike.md:197`) and passed nowhere | its unit (premium requests? AIU?), what the CLI emits when it is hit (a `result` with an exit code? an error event?), and whether a `--resume` inherits it (M2) |
| a turn watchdog | `fleet.turn_max_minutes`: a turn open longer than this is stopped and notified (today a turn can run forever — `grep timeout` finds nothing but subprocess limits) | how long a legitimate long turn is on the operator's real tickets, from the ledger's `turn_ended − turn_started` (M3) |
| a fleet-wide daily budget | `fleet.budget_per_day`: refuse `start`, `send`, `restart` when the fleet's day total is at the line | whether the tenant rate-limits five agents before any fleet budget would (`fleet-spike.md:225`, unchecked) (M4) |
| the cap on every door | `over_budget` checked in `start`, `restart` and `console`, not only `send` | nothing — it is a design choice the operator declined for now (§Decisions) |

## Where everything is written down

- [fleet-lifecycle.md](fleet-lifecycle.md) §The budget: the ledger, one arithmetic, *Send anyway*, `budget_invalid`.
- [fleet-events.md](fleet-events.md) §cost: `source`, `nano_aiu`, and the rule across sessions and days.
- [fleet-dashboard.md](fleet-dashboard.md): the spend cell in §The page's table, the footer, the spend pane, and §What
  is not here loses its *strip in #101* line.
- [setup.md](setup.md) §The settings page: the budget row. [refusals.md](refusals.md): `budget_invalid`, and
  `budget_exceeded`'s row gains *Send anyway*.
- [fleet-spike.md](fleet-spike.md): M1–M4 as rows under the tenant table, filled in or _not yet measured_.

## Slices

### A #209 — one arithmetic: `spend.py`, the `cost` event's source, `usage.json` read, and `status` agreeing with the tile

**Context.** §One arithmetic. `agentstate.py:118` (max), `supervisor.py:261–263` (sum), `events.py:232–245`
(both sources into one kind), `supervisor.py:28` (`usage.json`, unread), `fleet-spike.md:187` vs
[fleet-events.md](fleet-events.md) §cost.

**Build this.**
1. `agentdata/fleet/spend.py`: `fold(events) -> {sessions, days}` with the four-line rule; `for_agent(name)`,
   `for_fleet()`; pure functions over event rows, no I/O in the rule.
2. `events.from_copilot` tags every `cost` with `source` and keeps `nano_aiu`; the events page says so.
3. `usage.json` read on `exited`/`error`, compared with the last checkpoint; a mismatch is an `ad-doctor` row and a
   `friction`-kind note, never a silent pick.
4. `supervisor.agent_state`, `cli_fleet` `status` and `history`, `sessions.py` and `lifecycle.spent` read `spend.py`;
   the raw-`result` sum and the second `turns` count go.
5. M1 in the runbook: a resumed session's second `result.usage.premiumRequests` on the laptop, per-turn or total,
   with the fake updated to whichever it is.

**Acceptance criteria.**
- [ ] A fake transcript with three checkpoints (1.0, 1.33, 2.0) and a `result` of 2.0 folds to `premium: 2.0`,
      not 6.33 — and the same transcript replayed as two sessions folds to 4.0.
- [ ] `ad-fleet status` and `/api/fleet` print the same `premium_requests` and `turns` for the same fixture agent —
      one test reads both.
- [ ] A `usage.json` disagreeing with the last checkpoint by 0.33 produces a doctor row naming M1.
- [ ] `spend.fold` is property-tested: any interleaving of checkpoints for two sessions folds to the same totals.

**Out of scope.** The ledger on disk (B); any UI (C, D).

### B #210 — the ledger: `spend.json` written before rotation, rebuildable, and a budget that survives 20 MB

**Context.** §The ledger. `lifecycle.py:284` rotates the normalized stream; `events.py:577–594` reads the live file
only; `lifecycle.py:298–300` promises otherwise.

**Build this.**
1. `spend.json` per agent with the schema in §The ledger, updated from the cursor on every `events.refresh`.
2. `lifecycle.rotate_all` updates the ledger first; the cursor names the file it is on; `gc` never touches it.
3. `ad-fleet spend <repo> [--rebuild]`: the ledger's table, or a rebuild from every `events.norm.jsonl*` oldest-first
   that must equal the incremental one.
4. `lifecycle.spent()` reads the ledger; `over_budget` is unchanged in meaning and now true across rotations.

**Acceptance criteria.**
- [ ] A fixture agent spends 6.0, the log rotates mid-session, it spends 2.0 more: `spent()` is 8.0, `--rebuild`
      is 8.0, and `ad-fleet history` still lists the first dispatch.
- [ ] A budget of 7 refuses the next `send` after that rotation — today it would not.
- [ ] The ledger is never written inside a repository; `tests/test_fleet_e2e.py`'s walk still finds nothing new.
- [ ] Rotation under a live writer still refuses (`lifecycle.py:279–280`); the ledger is not the exception.

**Out of scope.** Copilot's own `session-store.db` totals (read, never written, and not a cost source).

### C #211 — the meter on the tile and the band: the spend cell, the model on the row, amber at four fifths

**Context.** §The meter. `drawCells` (`app.js:1986–2030`), the row (`serve.py:451–484`), `settings_snapshot`
(`serve.py:2127–2165`), [plan-column.md](plan-column.md) C's model card.

**Build this.**
1. The `/api/fleet` row gains `spend` and the four model fields, computed by the functions the settings page uses.
2. The fifth cell: `spend · 4.3 premium · of 10 · 12 turns · opus-5 · (2m)`; hover text with session and today;
   amber at 80 % with the sentence and its stated mean; red at 100 % with the refusal's words. The model short name
   is the button from column C, or a plain label until C lands.
3. On the band, the number after the age.
4. `ad-fleet status` gains `model` and `actual` columns beside `premium_requests` and `budget`.

**Acceptance criteria.**
- [ ] A fixture agent at 8.1 of 10 shows an amber cell whose text contains *of 10* and *mean*; at 10.0 the cell is
      red and contains the words of `supervisor.send`'s refusal; with no budget the cell has no *of*.
- [ ] The cell's age advances with the ledger's, not the page's.
- [ ] The band's number equals the cell's for the same agent.
- [ ] Contrast of the amber and red cells against every skin variant passes the check `tests/test_fleet_skins.py`
      applies to chips.

**Out of scope.** The model card itself (column C); rate prediction beyond a stated mean of three turns.

### D #212 — the fleet total: the footer, the spend pane, `ad-fleet spend`, and `spent_today` made true

**Context.** §The fleet total. `cli_fleet.py:432–436`, `#counts` (`index.html:188`), the inspector (`drawInspector`,
`app.js:2200`).

**Build this.**
1. `spend.for_fleet()`: today and all time, and the oldest ledger age summed over.
2. The footer clause `12.3 premium today · 41.0 all time`, aged on hover; `notify` and quiet hours untouched.
3. The inspector's *spend* pane for the selected project: sessions (cost, ended, when), days, the budget line.
4. `ad-fleet spend` with no repo: one row per agent plus the fleet line; `--since 7d`; `ad-fleet status`'s
   `spent_today` reads the ledger and `spent_total` joins it.

**Acceptance criteria.**
- [ ] Two fixture agents at 4.0 and 8.3 with ledgers dated today: the footer reads `12.3 premium today`; with one
      ledger dated yesterday it reads `8.3 premium today · 12.3 all time`.
- [ ] `ad-fleet spend` and the pane print the same rows from the same function — one test reads both.
- [ ] The footer is still one line at 1280 px (laptop row).

**Out of scope.** Charts. A number and its age are the meter; a sparkline is [plan-ownership.md](plan-ownership.md) D's
to earn.

### E #213 — the refusal reaches the desk, and the budget reaches settings without its trap

**Context.** §The refusal. `serve.py:1406–1413` (no `force`), `app.js:393–407` (*Reset anyway*), `settings.py:11–13`
and `lifecycle.py:78–86` (the trap), `supervisor.py:508–512` (the words).

**Build this.**
1. `force` on `POST /api/send` and the answer path; `budget_exceeded` drawn on the error line; *Send* re-arms as
   *Send anyway* for one press, then disarms.
2. `fleet.budget_per_agent` in `settings.EDITABLE` as an `int` with its why; the page's Copilot block shows it.
3. `lifecycle.settings` refuses a non-numeric budget with `budget_invalid` instead of `0.0`: a doctor row, a red
   cell, a status column reading *invalid "ten" — off*.
4. The refusal registry gains both rows; `tests/test_refusals.py`'s pin moves.

**Acceptance criteria.**
- [ ] An over-budget fixture agent: *Send* is refused with the CLI's words on the tile; the second press sends with
      `force` and the turn runs; the third press is refused again.
- [ ] Typing `ten` into the settings box is refused with `bad_type` and the file is unchanged; writing `"ten"` into
      the file by hand yields `budget_invalid` in `ad-doctor` and a red cell, and `over_budget` reports the budget as
      off.
- [ ] `ad-fleet send --force` and *Send anyway* run the same function with the same argument.

**Out of scope.** Checking the budget on `start`, `restart` or `console` (§Caps, later — declined for now).

### F #214 — proof, the laptop measurements M1–M4, and the caps table filled in for the plan that builds them

**Context.** §Caps, later. The fake `copilot`, the runbook, `fleet-spike.md`'s tenant table.

**Build this.**
1. Fake transcripts: checkpoints across a resume; a rotation mid-session; a `usage.json` that disagrees; a
   `--max-ai-credits` run if M2 finds the CLI emits something at the cap.
2. Laptop rows M1 (per-turn or total), M2 (`--max-ai-credits`'s unit and behaviour), M3 (the longest legitimate turn
   over a real day, from the ledger), M4 (whether five agents are rate-limited by the tenant) — filled in or _not
   yet measured_.
3. The definition-of-done demo on CI: five fixture agents, one over budget, one at four fifths, the footer summing,
   `ad-fleet spend` matching the page.
4. Docs as §Where everything is written down; `CHANGELOG.md`.

**Acceptance criteria.**
- [ ] The demo runs in the browser job and its screenshot is attached to the epic.
- [ ] §Caps, later has a measurement or _not yet measured_ in every row, and no design.
- [ ] `tests/test_entrypoints.py` accepts `ad-fleet spend`.

**Out of scope.** Building any cap.

## Ground rules

1. **One unit, one rule, one reader.** Premium requests; per session max, across sessions sum, per day the rises;
   `spend.py` is the only arithmetic and every printer calls it.
2. **The CLI's words.** A refusal on the desk is `supervisor.send`'s sentence and code, not a paraphrase.
3. **No new stop.** The cap is where it was and means what it meant; this plan makes it visible and passable, and
   §Caps, later is a table, not a design.
4. **Never `0.0` for a typo.** A wrong budget is refused at the page and shouted from the file.
5. **Additive events.** `source` and `nano_aiu` join `cost`; schema 1 is unchanged; nothing already written is
   re-parsed to mean something new.
6. **The ledger is a fold, rebuildable, never the source**; it lives under `~/.agentdata/fleet/` and nowhere in a
   repository.
7. **Every number carries its age**, and a stale number says so.
8. **Never colour alone.** Amber and red carry a sentence.
9. **Measured before designed.** M1–M4 are rows, filled in on the laptop, and the caps plan is written from them.
10. **Read, never written**: `usage.json` and Copilot's store are inputs.

## Build order

A → B → C → D → E → F, strictly: the arithmetic before the ledger, the ledger before any number is drawn, the
number before the refusal that cites it. C is also what [plan-column.md](plan-column.md) C needs on the row; if
column C lands first it adds the four model fields and this C adds `spend` only.

## Open questions, to be answered on the laptop and recorded in the slice

- Is `result.usage.premiumRequests` a turn's or a session's? (M1, A) The rule is written to flip on the answer.
- What does `--max-ai-credits` count, and what does the CLI do at the line? (M2, F)
- Is a mean of the last three turns a fair *rate*, or does the operator want the last turn alone? (C)
- Does the tenant rate-limit before any fleet budget would? (M4, F)
- Should *today* be the operator's local day or UTC? Default: local, the machine's — the ledger stores UTC and
  the printer decides. (D)

## Cost

The plan spends nothing: a fold over files the tick already reads, one JSON per agent, one more cell and one more
clause. What it saves is the thing the operator named: a premium request spent while nobody could see the last one
being spent. The first day the meter runs is also M3's measurement, so the caps plan is one sitting away rather
than one guess away.

## Decisions — the operator's, 22 September 2026

Asked: *what should "a user won't blow through their tokens" actually guarantee?* — hard caps and a meter; meter first,
caps later; or per-agent only. Answered: **meter first, caps later** — *show spend, budget and model on every tile
plus a fleet total; keep today's per-agent cap as it is; no new stops yet.* This plan is that answer, and §Caps,
later is the shelf the rest is put on, labelled.
