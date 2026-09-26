# Plan: fresh — every session knows what it was started on, and renewing the stale ones is one click

_Status: PLANNED (2026-09-22) — epic #238 (slices #239–#242), under #91 (the fleet). It comes before the notebook theme, because
the operator named it the precondition: *"The agents' staleness is a critical risk for this theme and at every turn
must be handled before our magnum opus design can be built."* The operator's answers are recorded in §Decisions._

## Why this exists

0.13.2 changed three skills (`state-update`, `friction-log`, `codebase-map`), and its changelog says *start a new
chat so the three changed skills are read*. Every agent already running kept following the old text: it would still
ask with `--question` and clear with `--clear-questions`. Those are the very habits that produced the 12 stale
questions of #231. Nothing in the fleet could say which agents those were.

| What the operator needs | What the code does today |
|---|---|
| to know which agents are running on an old install | `started` records `pid, prompt, summary, resumed, new, session` (`supervisor.py:_emit_started`) and nothing about the install. `update.stale()` compares the skills folder with the CLI on disk, for the machine as a whole, never per session |
| to start new sessions for them easily | `ad-fleet start <repo> --new` exists one repository at a time. Nothing does it for every stale agent, nothing waits for a turn to end, and nothing skips the agents waiting on a person |
| to know whether the desk itself is current | `ad-fleet serve` is a long-running process. After `ad-update` it keeps serving the code it loaded at start. `/api/ping` reports `version_string()`, which reads the *installed* metadata from disk, so it cannot tell that the running server is older than that |

**Why only the skills go stale.** A headless agent is a new `copilot -p … --resume <session>` process for every
turn. Every `ad-*` command it runs executes the installed code, so the CLI half is never stale inside a turn. What is
stale is the skill text loaded into the session when it began (README §Update: *skills are read when a chat
starts*). So a session is stale when the skills, or the CLI they were written against, changed after the session
began. Its turns do not go stale.

## The model

**The install fingerprint** (`agentdata/fleet/fingerprint.py`) is read from disk every time it is asked for, and
cached against the skills folder's newest mtime:

```
install: { version: "0.13.2", commit: "ca45368…", skills: "<sha12 of every SKILL.md, sorted by name>" }
```

The per-skill hashes are kept in `~/.agentdata/fleet/installs/<skills>.json`, which is written once for each skills
hash. That is how *which* skills changed can be named later, without carrying forty hashes in every event.

- **Recorded at every start.** `supervisor.start`, `supervisor.console` and `adopt.adopt` add `install` to the
  `started` event. An adopted session records `install: null`, because it began outside the fleet and nobody knows
  what it was started on.
- **A session's origin** is the `started` that began it: the latest `new` start, or, for a run that resumed an
  earlier session by id, the `new` start whose run first reported that session id.
- **Stale** means the origin's `install` differs from the current one, in the skills hash or in the CLI version or
  commit. It is derived on every snapshot, so it is checked **at every turn**, at every tick of the desk. The reason
  names what differs, for example *started on 0.13.1 · installed 0.13.2 · skills changed: state-update,
  friction-log, codebase-map*. An origin with no `install` counts as stale ("started before the fleet recorded
  installs"), because the install that records them is newer by definition. An adopted session is *unknown*: it is
  shown, and never renewed.

**Renew** is `ad-fleet renew`, and the desk's **Renew stale (n)** calls the same function:

1. **Preview first.** Every registered agent is listed with its verdict and what renewing would do:
   - *now*: idle, stale, has a ticket in progress;
   - *at the end of this turn*: running;
   - *skipped*, with the reason: needs you; a console (type in that window, or close it and
     `ad-fleet console <repo> --new`); adopted; done; not stale.

   The preview also counts the premium requests it will spend, one first turn per renewed agent. `--dry-run` stops
   here, and the desk shows this list before its confirm button.
2. **Stale only, when idle.** An idle agent gets `supervisor.start(name, key=<active ticket>, new=True)` with a
   prompt that says why: *a fresh session on the updated skills, to continue `<ticket>` from `.agent/state.json`*.
   Session bootstrap then reads the state, so the work continues where it stopped. A running agent gets
   `agents/<name>/renew.json`, and the desk's tick carries it out when the turn ends. Anything that needs a person
   is never renewed: renewing would bury the question, and the question is the point.
3. **The budget holds.** Renew goes through `start`'s own guards: the lock, the mid-ticket check and the per-agent
   budget. A refusal is reported per agent in the preview's words, never swallowed.

**Leaving one session (#488).** Renew stays *stale only, when idle*, and never takes an adopted session. Fresh is
the one-pane door the operator presses: `ad-fleet fresh <repo>` (and `POST /api/fresh`) plans, then starts one
clean `--new` session on the active ticket and the configured model, whatever the pane's session was -- stale, an
adopted terminal chat, or one that began outside the fleet and went quiet. The session left is marked `left` on its
row in `sessions.json` (the new one says `after` it), from a `leaves` field on the fresh `started`; nothing is
deleted. The verdicts, first match wins: `mid_turn`, `console_window`, `needs_you`, `foreign_session` (never
overridden), `second_press` (`chat_open`: a chat that may still be open, which a deliberate `--closed` gets past),
then `now`. `row.fresh` carries the same verdict for the pane, judged from the snapshot's own listing.

**A fresh day (#508).** A fresh day is `fresh` over the fleet: `ad-fleet fresh --all` (or two or more names, or
`POST /api/fresh {all: true}`) previews every agent from one process listing, and `--confirm <plan_id>` starts
exactly the ticked rows that are still `now`, each re-planned just before its launch. Renew stays stale-only. Three
checks only a sweep makes: `your_own_chat` first (an adopted or external session is never acted on, not even one
that went quiet), `fresh_today` after a `now` (the session began after today's local midnight and has a session
id), and `keyless` (no ticket in progress: tickable, unticked unless `--keyless`). The day boundary is when the
*session* began -- the `started` that is not a resume, or is `new` or adopted -- never when the current run did,
so a Send this morning on yesterday's session leaves it yesterday's. `split_runs` derives `before_today` from it.

**The desk itself.** `serve` captures the fingerprint it was *loaded* with at import time. `/api/ping` answers
`loaded` beside `installed`, and the page shows one line when they differ: *the desk is running 0.13.1 ·
installed 0.13.2 · restart*. `ad-fleet open` and both IDE shells treat an out-of-date desk like a missing one:
they stop it and start the installed one, then say so. So "start the fleet" always ends on a current desk.

## Slices

- **A #239 — the fingerprint, recorded at every start.** `fingerprint.py`, `install` on `started` from all three
  starters, the per-skill index, and the origin helper.
  Tests: a changed `SKILL.md` changes the hash and is named; an origin across resume, resume-by-id and legacy
  streams; an adopted session is unknown.
- **B #240 — stale on every row, at every turn.** `row.stale {stale, unknown, reason, skills_changed, began, now}` in
  `fleet_snapshot`, a *stale* chip on the tile (a pencil note in the notebook theme later), a column in
  `ad-fleet status`, and a line in the doctor's fleet rows when any agent is stale.
  Tests: the snapshot marks exactly the agents whose origin differs, and a browser test shows the chip and its
  reason.
- **C #241 — renew.** `ad-fleet renew [<repo>…] [--dry-run]`, the preview rows, idle agents now, running agents
  queued and carried out by the desk tick at turn end, skip reasons, `POST /api/renew`, and the header button with
  its preview.
  Tests: every verdict; a queued renew fires once when the turn ends and never while a person is needed; a budget
  refusal is reported; the page previews before it posts.
- **D #242 — a current desk.** The loaded fingerprint, `/api/ping {loaded, installed}`, the page's line, and
  `ad-fleet open` and the shells replacing an out-of-date server.
  Tests: a ping from an older server is replaced, and a current one is kept.

Build order: A, then B, then C, then D. A, B and C land together in one PR, because A alone changes nothing
anyone can see and B alone names a problem with no way to act on it. D is its own PR. All of them land
before the notebook theme.

## Ground rules

1. **The skills hash is content, not mtime.** `ad-update` reinstalls every skill and rewrites every mtime, so an
   mtime would mark every agent stale after every update, changed skills or not.
2. **Stale is derived, never stored.** It is a fold over `started` events against the fingerprint on disk.
   Nothing writes "stale" anywhere, so nothing can disagree with it.
3. **Renew never decides for a person.** Needs-you is skipped, consoles and adopted sessions are the operator's,
   and the preview comes before any spend.
4. **The fleet still writes only under `~/.agentdata/fleet/`.** A repository's `.agent/` stays the agent's.

## Decisions — the operator's, 22 September 2026

1. *"We need to be able to start the fleet and very easily start new sessions across all active agents. The
   agents' staleness is a critical risk for this theme and at every turn must be handled before our magnum opus
   design can be built."*
2. What stale means: **old skills or CLI**, meaning the session started before the latest `ad-update`. Old context,
   old tile data and old branch were offered and not chosen.
3. What renew does: **stale only, when idle**. It lists which agents are stale and why before anything runs, waits
   for a running turn to finish, skips agents waiting on a person, then starts a fresh session on the same ticket.
