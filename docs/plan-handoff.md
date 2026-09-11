# Plan: the handoff — a ticket dropped on a tile is picked up, questioned once, given its files, and worked

_Status: PLANNED (2026-09-11) — to be filed as an epic under #91 (the fleet) and #122 (the desk), a sibling of
#145. Nothing below is built. Slices A–G are written in the shape of the issues to file and carry no numbers yet.
Every browser claim is to be measured on the laptop in Edge, PyCharm's JCEF window and VS Code's Simple Browser,
the way #145's were, and every measurement is recorded in the slice that made it._

## Why this exists

#98 made a ticket draggable and #132 made a Downloads file attachable, and both stop at the agent's doorstep. Read
end to end, the handoff from the operator's desk to a headless agent has four gaps, and each is visible on the page
today:

| What the operator sees | What the code does | Section |
|---|---|---|
| A ticket dropped on a tile starts an agent whose first move is usually a full stop | the prompt is one line (`launch.DEFAULT_PROMPT`); `jira-triage` step 10 sends any untestable criterion to `friction-log`, which sets `phase=blocked --question` and STOPs; the operator's reply respawns the CLI with `--resume`, but `open_questions` persist until `--clear-questions` (`state.py`), which no skill runs on resume — so `session-bootstrap` step 11 and `router` step 8 stop again on the same block | §Pick-up, §The ask |
| The agent's question is one sentence in the tile's why-line, and the answer is a text box | a question is a free-text string in `open_questions`, or an `assistant_text` that happens to end in `?` (`agentstate._ASK_ENDINGS`); it has no id, no choices, no "I need a file", and no way to tie a reply to the question it answers; three questions in a bulleted list read as `idle` for twenty minutes | §The ask |
| A file dropped on a tile lights the tile up, and nothing happens | `dragover` sets `dropEffect = "copy"` and the dashed outline for anything that is not a tile drag; `drop` reads `text/plain` only; `static/` contains no `dataTransfer.files`, the server has no upload route, and `MAX_BODY` is 64 kB of JSON | §The scope |
| The context the operator already gave is never read | the inbox copies into `<repo>/.agent/in/<KEY>/` and asks `ad-state set --input`; no skill reads `inputs`; the agent cannot read Jira comments (`ad-pncli jira` accepts `search` and `get` only) or attachments; acceptance criteria are whatever happens to be inside `description` | §The scope, slice F |

A fifth finding is structural. Real file paths never reach the page in any embedder, by design: the browser withholds
them, the shells have no channel to the page (no `postMessage`, no `JBCefJSQuery`; the VS Code page is an iframe
inside the webview), and the only POST a shell builds is `{repo, ticket}`. Every "give the agent this file" design
that assumes a path is therefore a design for one host, and this desk has three.

**The purpose is the same as #122's and #145's: the human's attention.** Three questions a glance at a tile should
answer, and today it answers none of them: *is this ticket ready to hand over*, *what does the agent need from me*,
*what may it touch*.

## What is reused

- The ticket drag (#98): `app.js` `ticketRow` → `dispatch()` → `POST /api/start` → `supervisor.start`, with the
  guard rails in one place so the CLI and the page share them. The drop target, the tile, stays; what it accepts
  grows.
- The inbox's constitution (#132, `inbox.py`): a copy, never a move; only into `<repo>/.agent/in/<KEY>/`; only on a
  click; always an `inbox.attached` event; the `inputs` line *asked of* `ad-state`, never written. Every write this
  plan makes inside a repository follows those five rules and lands in that one directory.
- `open_questions` and `--question` already exist in `state.py`, `question_opened` is already a kind, and
  `agentstate.classify` already ranks a question below a friction log and above a `?`. The ask becomes a record
  by growing those, not by adding a second channel — [fleet-events.md](fleet-events.md) rules out a `needs_human`
  *event*, and this plan keeps that rule.
- `supervisor.send` is already "spawn the CLI again with `--resume <session>` and the message as `-p`". An answer is
  a `send` with a shape.
- `git` is on the agent's allow-list and `.git/HEAD` is already read by the catalogue. A file is identified by what
  git already knows about it — a blob hash — so no new index is built and nothing ignored by git can ever match.
- `ad-graph refs` answers "what does touching this reach" per repo; the scope card only *shows* that answer.
- `events.exited.files_modified` already says what a run edited; the scope report is a comparison, not a new event.
- The shells' contract ([fleet-ide.md](fleet-ide.md) §What a shell must do) and `tests/test_fleet_shells.py`: a
  shell relays and contains no rule. A path channel is one more numbered step of that contract, tested the same way.
- The browser harness (#146) and `tests/test_fleet_desk_regressions.py`: every slice here lands with a test on the
  rendered page, because a drop handler is exactly the kind of thing a source-text assertion cannot see.

## Prior art, and what is different here

At the time of writing, every product the operator may also have on the laptop does part of this, and each does it
inside its own window:

| Product | Does | Does not |
|---|---|---|
| GitHub Copilot coding agent ("assign to Copilot" on an issue; Copilot for Jira) | an issue assigned to Copilot becomes a PR from a hosted runner | run locally, take a local file, or pre-flight the issue; [fleet-intake.md](fleet-intake.md) already notes it is a different product from this one |
| Copilot Chat in VS Code, Copilot CLI | drag a file from the Explorer into the chat; `#file`; `@path` in a prompt | reach a second checkout, or a page outside VS Code |
| Cursor, Claude Code, JetBrains AI Assistant / Junie | `@file` mentions, attach from the editor's own tree, background agents started from Slack or Linear | the same: one checkout per window, and the context channel lives inside that product's chat; a cloud agent cannot be handed a local file at all |
| Atlassian Rovo Dev, Linear agents | assign an issue to an agent inside the tracker | anything local; the tracker is the only context channel, and nothing narrows scope |

Three things none of them do, and this epic does, stated at their actual size:

1. **Pre-flight before a model is paid.** A thin ticket is found by the desk from what it already has — the ticket,
   the catalogue, the history, the checkout — and the operator is asked for a brief *before* the first premium
   request, not after the agent stops on it.
2. **A question is a record, not a sentence.** It has an id, choices, a default, a "what I want" and a blocking
   flag; the tile renders it as a card the way it renders an approval; several are answered in one resume.
3. **A file is identified without a path.** A dropped file is resolved to a checkout by content, in a page that Edge,
   JCEF and Simple Browser render identically; the IDE shells add a path channel where they have one, and the
   server decides in both cases. Nothing but a hash leaves the browser until the operator clicks.

## The handoff, in three acts

### Pick-up: the dispatch card

Today a drop is a `POST /api/start`. After this plan a drop opens a **dispatch card** on the tile — the same place
the approval card appears — and the start is the card's button. The card is built by a **pre-flight** that runs on
the server, spends no premium request, and reads only what the fleet already holds or can fetch once:

| Row | Source | Says |
|---|---|---|
| key, repo match, Done | `board.suggest`, `supervisor.check_ticket` (unchanged) | the existing refusals, with a structured `code` |
| description | one `ad-pncli jira get <KEY>` per drop, cached for `fleet.board_ttl` | `412 words` / `two lines` / `empty` |
| acceptance criteria | a heuristic over the description — numbered or checkbox list, "AC", *Given/When/Then* — or a field pinned by `ad-jira fields --pin acceptance_criteria` | `4 found` / `none found` |
| comments, attachments | counts from the same fetch, when pncli returns them (open question) | `3 comments, the last by you yesterday` — the place a human has often already answered |
| names it mentions | capitalised and quoted names in summary and description, looked up with the catalogue's `where` | `mentions Velocity — luna's MODEL.md declares it`; and when the match is in a *different* repo than the tile, that is said |
| history | `board.history` for this key | `dispatched twice; ended blocked both times: "a decision on whether RDSD-118 covers UAT"` |
| what is already here | `<repo>/.agent/in/<KEY>/`, `state.inputs`, a `feature/<KEY>-*` branch | `2 files attached on Tuesday` / `a branch exists from a previous attempt` |

The verdict is one of three words. **ready** — the button says *Start*. **thin** — a short or empty description,
no criteria found, or a history that ended blocked; the brief box is focused and the button says *Start anyway*.
**blocked** — one of the existing refusals, unchanged. Being unable to reach Jira still never blocks a start: the
rows go grey with the error in a tooltip, the verdict reads *unknown*, and *Start* is enabled — the pre-flight is a
courtesy, exactly as the Done check is.

**The brief.** The card's text box is the operator's own words, and they are new information that exists nowhere
else — not a stale copy of Jira. On *Start* they are written to `<repo>/.agent/in/<KEY>/brief.md` with `by`, `at`
and `ticket` in front matter, recorded as a `handoff.brief` event, and the `inputs` line is asked of `ad-state` the
way attach asks it. Files dropped on the card go through §The scope. Then the agent is spawned. All of it is
`ad-fleet start <repo> <KEY> --brief "…"` or `--brief-file <path>`, because a fleet you can only drive through a
page is a fleet you cannot script, and `ad-fleet preflight <KEY> [--repo <name>]` prints the card as TOON.

**The prompt stays one line and never carries ticket text.** `DEFAULT_PROMPT` gains a `{handoff}` placeholder,
optional like `{summary}`:

```
Ticket RDSD-118: UAT refresh is slow. The operator left a brief and 3 files under .agent/in/RDSD-118/; read them
before the ticket. Invoke skill session-bootstrap, then router.
```

`jira-triage` still does the reading through `ad-pncli`. `fleet.preflight: false` restores #98's immediate start
for anyone who preferred it. Keyboard: the drop opens the card, `Enter` starts, `Esc` cancels; *pick one* (several
repos declare the project) is the same card with a repo segment at the top.

### The ask: a question is a record

`ad-state ask` is the agent's one way to ask, and it writes a record where `--question` wrote a string:

```
ad-state ask "Does RDSD-118 cover the UAT workspace too?" --choice yes --choice "no, production only" --default yes
ad-state ask "Which export is the baseline?" --want file
ad-state ask "Assuming the window is the last full sprint" --assume "last full sprint"
```

`open_questions[]` entries become `{id, q, choices, default, want, about, blocking, asked}`; a plain string is still
accepted and normalised, so nothing an existing skill writes breaks. Without `--assume` the question is **blocking**:
the phase becomes `blocked` and the phase it came from is kept as `blocked_from`. With `--assume` it is
**non-blocking**: the agent states its default, continues, and the tile shows the assumption as an amber *assumed*
row the operator can overturn at any time. That is the difference between *stop* and *urge*, and it is the agent's
to choose per question under one rule: two readings that lead to different work block; a safe, reversible default
does not.

`--want file` says the question is answered by a thing, not a decision. The card renders a drop zone for it; a file
dropped there is resolved by §The scope and its repo-relative path becomes the answer.

**Answering.** The card lists every open question on the tile — choices as buttons, a text box, the drop zone —
with one *Send*. `POST /api/answer {repo, answers: [{id, answer}]}` is `ad-fleet answer <repo> <id> "<text>"`; both
call one function that composes the resume:

```
Answers to your questions — q3: yes; q4: .agent/in/RDSD-118/velocity-2026-08.xlsx. Record each with
`ad-state answer`, then continue the ticket from where you stopped.
```

One respawn carries every answer, because each `--resume` is at least a third of a premium request and the notifier's
rule — nothing routine is announced twice — is also the right rule for what the operator is asked to type. The
`started` event carries `answers: [ids]`; a `question_answered {id, answer, by}` event is written for the tile and
for `ad-fleet history`. `ad-state answer <id> "<text>"` marks the record answered, and when no blocking question is
left and the phase is `blocked`, returns it to `blocked_from` — which is what makes a reply unblock, and it is still
`ad-state` and nobody else writing `state.json`.

**What the fold changes, and what it does not.** `question_opened.data` grows `id, choices, default, want,
blocking` — additive, schema `1`. `question_answered` is a new kind. A blocking unanswered question is
`needs_human`, below a friction log as today; a non-blocking one changes no state. `friction-log` stays the record of
a real STOP, and its `severity` now reaches the fold: a `nit` no longer stops an agent as hard as a `blocker`. There
is still no `needs_human` event and no rule in the shells.

**The skills.** `jira-triage` step 10 becomes a clarify step — an untestable criterion with two readings is a
blocking `ask` with the readings as choices, a missing detail with a safe default is `--assume`, and `friction-log`
follows only the blocking case. `jira-triage` step 8 reads the comments (`ad-pncli jira comments`, already a read
verb, gains its `choices` entry in `cli.py`) because that is where a human has usually already answered.
`session-bootstrap` step 11 reads the records: with answers in the resume prompt it records them and continues; with
none it prints them and STOPs. `router` step 8 routes to `friction-log` only on a *blocking unanswered* question.
The `?` heuristic stays as the last resort it already is.

**AGENTS.md rule 10** — *acceptance criteria ambiguous → friction-log, then STOP* — is the canonical rule this act
refines, into "two readings that lead to different work → a blocking `ask`; a safe default → `--assume` and
continue". That is a change to the canonical rules and therefore the operator's decision, recorded in the slice
that makes it.

### The scope: a file is identified without a path

A file dropped on a tile means *this is what the ticket is about; start here*. Three hosts, two channels, one server
rule.

**In the page — Edge, JCEF and Simple Browser alike.** The page never learns a path, so it does not ask for one. For
each dropped file it computes git's own blob hash — SHA-1 over `blob <size>\0` and the bytes, with `crypto.subtle`
where the origin is a secure context (loopback is) and a sixty-line SHA-1 in `app.js` where it is not; no CDN — and
posts `{repo, files: [{name, size, sha}]}` to `POST /api/scope/resolve`. The server lists candidates by basename
among `git ls-files` and `git ls-files --others --exclude-standard` in that checkout — tracked and untracked, never
ignored, which is how `.env` cannot match by construction — hashes each candidate's working-tree bytes, and answers
`resolved`, `ambiguous` (the same content in two places: a pick) or `unmatched`. A resolved file is added to the
scope; nothing but a hash has left the browser. An unmatched file is not this repository's: the card says so and
offers *attach a copy into .agent/in/<KEY>/*, which on a click uploads the bytes (`POST /api/attach-bytes`,
`fleet.attach.max_mb` default 10, the one route with a larger body cap, the same `safe_name`, the same
`inbox.attached` event with `source: "drop"`) and follows the inbox's rules to the letter. A file above
`fleet.scope.max_hash_mb` (default 64) is not hashed — a two-gigabyte PBIX would freeze the page — and is offered a
name-only match instead, labelled `how: name` because it is the weaker claim, the way adoption labels its two. A
dropped folder is the same trick over its files, walked with `webkitGetAsEntry`, capped at 200, resolved by majority
to a directory row.

**From the IDE — where a path exists.** PyCharm: a Swing drop target on the tool-window panel; `FileCopyPasteUtil`
reads both the OS file list and the Project tree's own flavour. VS Code: an *explorer/context* and *editor/title*
command, *Fleet: give to the agent*, with the selected URIs; and, if the laptop confirms it, Shift-drop onto the
webview (VS Code re-enables the drop with Shift held since June 2024) and a `text/uri-list` drop on the extension's
own Fleet view. Each posts `{paths}` to `POST /api/scope` — no `repo`, no rule: the server maps every path to the
registered checkout that contains it (`norm_path`, real path, prefix), refuses one that is in no checkout, refuses
`.agent/out/` and the names the catalogue refuses, and answers `409 scope_wrong_repo` with a hint when a path from
repo A lands on tile B. `docs/fleet-ide.md` gains step 8 and `tests/test_fleet_shells.py` pins it: a shell may not
name a file type, a size, or a repository rule.

**What the agent receives.** `<repo>/.agent/in/<KEY>/scope.toon`, appended by the fleet under the inbox's rules and
recorded as a `scope.added` event:

```
scope[3]{path,why,by,at,how}:
  models/RDSD.SemanticModel/definition/tables/Velocity.tmdl,dropped on the tile,operator,2026-09-11T09:14,fingerprint
  reports/UAT.Report/definition/pages/p3.json,"answer to q4",operator,2026-09-11T09:20,ide
  .agent/in/RDSD-118/velocity-2026-08.xlsx,attached copy,operator,2026-09-11T09:20,attach
```

`session-bootstrap` reads it with the brief: *these first; `ad-graph refs` to widen; say when you go outside*.
`--add-dir` is unchanged, because the files are in the checkout it already has. Whether `@path` references work
under `-p` is an open question; if they do, `fleet.prompt_at_refs` appends them for up to eight files, and the prompt
is still one line.

**Scope is advice to the model and a report to the human.** The tile's scope card shows the files given, and when a
graph exists, the files they reach (`ad-graph refs`, greyed with a hint when there is no graph) — a preview, never a
change. A drop on a *running* tile is queued (`scope.added` while `running`), the card says *queued for its next
turn*, and the next resume mentions it; on an idle or waiting tile the card offers *tell it now*, which is a `send`.
At `exited` or `error`, `files_modified` is compared with the scope and the tile says `edited 2 · 1 outside the
scope you gave it`; `ad-fleet history` grows the same column. That is the diff-before-you-trust signal, from events
that already exist.

## Where everything is written down

**Inside a repository — one directory, every write an event, every write a click or a start:**

| Path | Written by | Event |
|---|---|---|
| `.agent/in/<KEY>/brief.md` | `start --brief`, the card | `handoff.brief` |
| `.agent/in/<KEY>/scope.toon` | `POST /api/scope`, the IDE shells, a `--want file` answer | `scope.added` |
| `.agent/in/<KEY>/<file>` | the inbox (#132), `attach-bytes` | `inbox.attached` |
| `.agent/state.json` | **`ad-state` only** — `inputs` asked, `open_questions` by `ask` / `answer` | `question_opened`, `question_answered`, `phase_changed` |

**The event contract — additive, schema stays `1`:**

| Kind | New or grown | Data |
|---|---|---|
| `question_opened` | grows | `id, choices, default, want, blocking` beside `question` |
| `question_answered` | new | `id, answer, by` |
| `handoff.brief` | new | `path, words, by` |
| `scope.added` | new | `paths, how, by, queued` |
| `started` | grows | `answers: [ids]`, `scope: n` |
| `friction` | grows | `severity` |

**The API:** `POST /api/answer`, `POST /api/scope`, `POST /api/scope/resolve`, `POST /api/attach-bytes`,
`GET /api/preflight?key=&repo=`; and every 409 carries a `code` beside `error` and `hint`, so the page stops
recognising a refusal by regex over its prose (`dispatch()` matches `/jira_project/` today).

## Slices

| # | Slice | Fixes | Needs | After |
|---|---|---|---|---|
| A | the handoff contract: the codes, the kinds, the directory, the doc, and the hygiene the pick-up guard depends on | the regex on prose; the attach response the page misreads; two `TERMINAL_PHASES` that disagree | — | — |
| B | pick-up: the pre-flight, the dispatch card, the brief | an agent whose first move is a stop | A | A |
| C | the ask: `ad-state ask` / `answer`, the question card, one resume for N answers, the skill steps | a reply that does not unblock; a question that is a sentence | A | A |
| D | scope in the page: resolve a dropped file by fingerprint, `scope.toon`, the scope card, attach a copy | a drop that lights up and does nothing | A | A |
| E | scope from the IDE: the path channel in both shells, `POST /api/scope`, contract step 8 | no channel from a host that has a path | D | D |
| F | the agent honours the scope: the skill steps, the comments read, widening by graph, the queue, the report | context written and never read | C, D | C, D |
| G | proof: the drop harness, a fake-copilot question round trip, the laptop rows, the demo | — | all | all |

### A — the handoff contract

**Context.** Three seams every later slice lands on are soft today. `dispatch()` in `app.js` offers the cross-project
override by matching `/jira_project/` against the refusal's prose; rewording `supervisor.check_ticket` silently
removes the override. `/api/attach` answers with the event object, whose `attached`, `dir` and `why` sit under
`data`, and `app.js` reads them flat — so a successful attach renders *already there*. `agentstate.TERMINAL_PHASES`
says `pr_open` is done and `supervisor.TERMINAL_PHASES` says it is mid-ticket; `closed` and `merged` are in both and
in neither `state.PHASES`; `optimizing` is in `state.PHASES` and missing from `state-update`'s list.

**Build this.**
1. Every 409 body carries `code` (`cross_project`, `ticket_done`, `live_agent`, `mid_ticket`, `wrong_repo`,
   `scope_wrong_repo`, …) beside `error` and `hint`; `dispatch()` switches on it; the CLI prints it as `refused:`.
2. The ticket drag sets `application/x-agentdata-ticket` and keeps `text/plain` as the fallback for a key typed
   or dragged from elsewhere, mirroring `application/x-agentdata-tile`.
3. The event kinds and fields in §Where everything is written down, reserved in `events.KINDS` and documented in
   [fleet-events.md](fleet-events.md); readers of the old shapes are unchanged.
4. `docs/fleet-handoff.md`: the `.agent/in/<KEY>/` layout, the five rules it inherits from the inbox, and the
   `{handoff}` placeholder.
5. Fix the attach response; one `TERMINAL_PHASES` in `agentstate`, imported by the supervisor, with `closed` and
   `merged` either added to `state.PHASES` or removed from both; `optimizing` in the skill's list.
6. `ad-pncli jira comments <KEY>` — the verb is already in `READ_VERBS`; it gains its `choices` entry.
7. Playwright helpers that build a `DataTransfer` with files in page context and dispatch `drop` on a tile, so D
   and E have a harness on day one.

**Acceptance criteria.**
- [ ] A rendered-page test proves the cross-project override still appears after the refusal text is reworded.
- [ ] A rendered-page test proves a successful attach reads *attached → …*, and fails against the previous commit.
- [ ] One test asserts the two terminal-phase tuples are one object, and `ad-state` accepts every phase either names.
- [ ] `tests/test_fleet_events.py` proves every new kind is redacted and resumable by `seq`, and that an older
      fold ignores it rather than raising — the kinds are additive, the fields optional.
- [ ] `docs/refusals.md` rows for every new `code`, each naming its test.

**Out of scope.** Any card, any drop of a file, any skill change beyond the phase list.

### B — pick-up: the pre-flight, the dispatch card, the brief

**Context.** §Pick-up. A drop today is a start; after this it is a card whose button is the start.

**Build this.**
1. `fleet/preflight.py`: the rows in §Pick-up, each `{row, value, age, verdict, why}`, cache-first, one Jira fetch
   per key per `fleet.board_ttl`, grey rather than wrong when Jira is unreachable; `GET /api/preflight` and
   `ad-fleet preflight <KEY> [--repo]` print the same TOON.
2. The verdict rule — `ready | thin | blocked | unknown` — in one function with one table, tested by example.
3. The dispatch card on the tile: rows, verdict, the brief box, a drop zone (D wires it), *Start* / *Start anyway*,
   `Enter` and `Esc`, the repo segment when several repos declare the project; `fleet.preflight: false` skips it.
4. `start --brief` / `--brief-file`: write `brief.md`, emit `handoff.brief`, ask `ad-state set --input`, then spawn;
   a failure to write the brief refuses the start rather than launching without it.
5. `{handoff}` in `DEFAULT_PROMPT`, optional, naming the directory and the counts; `fleet.prompt_template` files
   written before it still work.
6. The catalogue lookup of mentioned names, saying when the match is in another repo than the tile.

**Acceptance criteria.**
- [ ] A ticket with a two-line description and no criteria renders *thin* with the brief box focused; one with four
      numbered criteria renders *ready*; a Done ticket renders the existing refusal with its `code`.
- [ ] `ad-fleet preflight` on a key Jira cannot serve prints `unknown` rows with the error, exit 0, and
      `ad-fleet start` still launches.
- [ ] A start with a brief produces `brief.md`, one `handoff.brief` event, an `inputs` line in `state.json` written
      by `ad-state`, and a `started` event whose prompt names the directory — in that order, proven by the event
      stream.
- [ ] Four tiles and an open board for ten minutes issue no more Jira requests than #98's test allows plus one
      `get` per dropped key.
- [ ] A rendered-page test drops a ticket and reads the card's verdict text.

**Out of scope.** Reading attachments from Jira (open question); any change to what `jira-triage` reads; auto-start
on *ready* (declined: the card is the operator's decision, however short).

### C — the ask

**Context.** §The ask. Today the agent can stop, and only stop; a reply does not unblock; a question is a sentence.

**Build this.**
1. `ad-state ask` and `ad-state answer` with the flags in §The ask; `open_questions` entries as records, strings
   normalised; `blocked_from` kept and restored; `--clear-questions` unchanged for a human who wants it.
2. `question_opened` grows, `question_answered` is emitted from the state diff exactly as `question_opened` is.
3. The fold: blocking → `needs_human` as today; non-blocking → no state, an *assumed* row; `friction.severity` read
   from the front matter and `nit` not folded as `blocked`.
4. The question card on the tile: every open question, choices as buttons, a text box, the drop zone for
   `--want file` (D wires it), one *Send*; `POST /api/answer` and `ad-fleet answer`, one resume for N answers, the
   resume text in one function beside `lifecycle.RESUME_PROMPT`.
5. Skill steps: `jira-triage` 8 (comments) and 10 (clarify), `session-bootstrap` 11, `router` 8; the friction
   template's `severity` line becomes required.
6. The AGENTS.md rule 10 refinement, as a proposal in the slice for the operator to accept or decline; the skills
   are written so that either answer leaves them consistent.

**Acceptance criteria.**
- [ ] A fake-copilot transcript in which the agent runs `ad-state ask --choice a --choice b`, stops, is answered
      from the tile, and on resume records the answer and reaches `phase=triaged` — the round trip that fails today.
- [ ] Three questions asked in one stop produce one card, one *Send*, one `started` event with three ids.
- [ ] An `--assume` question leaves the tile `running`, shows the assumption, and overturning it later resumes the
      agent with the correction.
- [ ] A `nit` friction log does not turn the tile red; a `blocker` does; both are events.
- [ ] `tests/test_skills.py` proves every skill still stays under 120 lines and that no skill ends a turn on an
      unanswered question without having printed it.

**Out of scope.** A question the *fleet* asks the agent; multiple-choice with free-text "other" beyond the text box
that is already there; Windows toast content beyond the existing title and body.

### D — scope in the page: a dropped file, resolved by fingerprint

**Context.** §The scope, first channel. The tile already promises a copy on `dragover`; this makes it true.

**Build this.**
1. `drop` on a tile branches on `dataTransfer.files` before the ticket branch; the blob hash in the page with
   `crypto.subtle` and the plain-JS fallback; the size cap; the folder walk with its cap.
2. `POST /api/scope/resolve`: candidates by basename from `git ls-files` and `--others --exclude-standard`, hashed on
   the server, `resolved | ambiguous | unmatched` per file; never a path outside the checkout; never an ignored
   file.
3. `POST /api/scope {repo, paths, why, how}`: append to `scope.toon` under the inbox's rules, emit `scope.added`,
   ask `ad-state set --input`; queue when the tile is `running`.
4. The scope card on the tile: the files, `how` per row, *tell it now* when idle, the pick for `ambiguous`, the
   *attach a copy* offer for `unmatched`.
5. `POST /api/attach-bytes`: the one route with a larger body, `fleet.attach.max_mb`, the same destination rule,
   `safe_name` and event as the inbox, `source: "drop"`; only from the card's button.

**Acceptance criteria.**
- [ ] A rendered-page test drops a file whose bytes equal a tracked file's and reads its repo-relative path on the
      scope card; drops the same bytes with a different name and still resolves; drops unrelated bytes and reads
      *not a file of <repo>*.
- [ ] A file that is git-ignored in the checkout never resolves, even when its bytes are dropped.
- [ ] Nothing but the hash request leaves the page until *attach a copy* is clicked — asserted by counting requests.
- [ ] A drop on a running tile is queued and appears in the next `started` event's prompt.
- [ ] The three hosts each get a laptop row: Edge, JCEF, Simple Browser; `crypto.subtle` availability recorded per
      host.

**Out of scope.** Paths from the IDE (E); anything the agent does with the scope (F); moving a file.

### E — scope from the IDE: the path channel in both shells

**Context.** §The scope, second channel. A shell has a path and no channel; it gets the channel and no rule.

**Build this.**
1. PyCharm: a drop target on the tool-window panel accepting the OS file list and the Project tree's flavour; on
   drop, `POST /api/scope {paths}` with the token from `serve.json`; the outcome shown by the page, not by the plugin.
2. VS Code: the *explorer/context* and *editor/title/context* command with the selected URIs; the Shift-drop and the
   Fleet-view `text/uri-list` drop measured on the laptop and kept only if they deliver URIs.
3. `POST /api/scope` without `repo`: the containing registered checkout, real-path resolved; `scope_wrong_repo`
   when the page's selected tile is another repo; the catalogue's refused names refused here too.
4. `docs/fleet-ide.md` step 8; `tests/test_fleet_shells.py` asserts a shell posts paths and nothing else — no
   extension list, no size, no repo name.

**Acceptance criteria.**
- [ ] Both shells build on CI as today; the JetBrains zip and the vsix carry the new command and nothing else new.
- [ ] A path outside every registered checkout is refused with its `code`; a path in repo A while tile B is
      selected is refused with the hint naming A.
- [ ] `test_fleet_shells.py` fails on a shell that names `.tmdl`, `25 MB` or a repo name.
- [ ] Laptop rows: Project-tree drag into the JCEF tool window (does CEF swallow it, or does the Swing target see
      it), Shift-drop into the webview, Explorer drop onto the Fleet view.

**Out of scope.** A second view of an agent in either shell; a JS bridge between host and page (the server is the
bridge); macOS and Linux IDE paths.

### F — the agent honours the scope

**Context.** §The scope, what the agent receives. The plumbing reaches the doorstep today and no skill opens the door.

**Build this.**
1. `session-bootstrap`: read `.agent/in/<ticket>/` — the brief, `scope.toon`, the attached files — via `ad-state
   show`; print one line saying what was found; hand it to `router` beside `phase` and `open_questions`.
2. `jira-triage`: the scope is *where to start*; `ad-graph refs` to widen when a graph exists; an edit outside the
   scope is announced in one line before it is made.
3. The scope report: `files_modified` against `scope.toon` at `exited` / `error`, on the tile and as a `history`
   column.
4. The widening preview on the scope card, greyed with the `codebase-map` hint when no graph exists.
5. `fleet.prompt_at_refs`, if the `@path` open question is answered yes.

**Acceptance criteria.**
- [ ] A fake-copilot transcript in which the agent's first tool call after bootstrap reads `scope.toon`, and its
      first edit is a file in it.
- [ ] A run that edits a file outside the scope ends with the tile reading `1 outside the scope you gave it`, from
      events alone.
- [ ] `ad-fleet history` for a scripted day shows the scope column and agrees with the event store.
- [ ] Every skill touched stays under 120 lines (`tests/test_skills.py`).

**Out of scope.** Enforcing the scope (the guard's job is coverage, not scope; a hard fence would be a fourth
refusal nobody asked for); a ticket→file edge in the graph (open question; the scope *is* that edge, written by a
person).

### G — proof

**Context.** #102's shape, for this epic: a fake `copilot` on CI, the laptop runbook, and a definition-of-done demo.

**Build this.**
1. The fake `copilot` learns a question round trip and a scoped edit; transcripts `captured` on the laptop where
   possible, `synthesized` and labelled where not.
2. `docs/windows-verification.md` rows for every laptop measurement named in A–F, each pasted failure becoming a
   `tests/regressions/` file naming the host.
3. The demo, scripted and run on CI against the fake: a thin ticket is dropped, the card says *thin* and why, a
   brief and two files are given, the agent asks one blocking question with two choices and assumes one detail,
   the question is answered from the tile in one *Send*, the agent works, and the tile ends with a scope report of
   `edited 2 · 0 outside`.

**Acceptance criteria.**
- [ ] The demo passes on Linux and Windows CI with the browser installed, and the suite stays inside the
      two-minute Linux budget [testing-this-repo.md](testing-this-repo.md) sets.
- [ ] Every open question below is answered in the runbook with the host and the date, or marked *not yet
      measured* — never absent.

## Ground rules

1. **The page is a view.** Every card is state from the server; every button calls the function the `ad-fleet`
   verb calls; every refusal is the CLI's words and a `code`.
2. **The prompt is one line and never carries ticket text.** `{handoff}` names a directory and counts; the agent
   reads the ticket through `ad-pncli` as it does today.
3. **The fleet writes in a repository under `.agent/in/<KEY>/` and nowhere else**, only on a click or a start, and
   every such write is an event. `ad-state` remains the only writer of `state.json`; the fleet asks.
4. **Nothing leaves the browser but a hash until the operator clicks.** A file's bytes travel only through
   *attach a copy*, and only into `.agent/in/<KEY>/`.
5. **Questions are records; states are derived.** There is still no `needs_human` event. The fold's order is
   unchanged; the kinds grow additively at schema `1`.
6. **Shells relay; the server decides.** A shell posts paths and shows the page; it names no file type, size,
   state or rule, and `test_fleet_shells.py` says so.
7. **Scope is advice to the model and a report to the human.** Nothing here adds a refusal to an agent's edit.
8. **No framework, no build step, no CDN.** The SHA-1 fallback is sixty lines in `app.js`; the wheel does not
   change; Playwright stays a `dev` extra.
9. **Reads run unattended; writes wait for a click.** The pre-flight is read-only; the approval gate is untouched.
10. **Every laptop failure becomes a named regression test**, with the host in its name.

## Build order

A → then B, C and D in any order, in parallel if hands allow → E after D → F after C and D → G last, though every
slice lands with its own browser test. B and C are independent of D; a card without a drop zone is still a card.

## Open questions, to be answered on the laptop and recorded in the slice

- Does `@path` in a `-p` prompt attach the file under Copilot CLI's current build, or is it interactive-only? (F)
- Does `pncli jira get-issue` return comment and attachment counts, and can the stored token fetch an attachment
  through REST the way `ad-jira transition` reaches Jira — an `ad-jira attachments <KEY> --into .agent/in/<KEY>/`
  would make the ticket's own files part of the scope? (B, F)
- In VS Code's Simple Browser, is the loopback page a secure context for `crypto.subtle` inside the webview's
  iframe, or does the fallback carry every drop there? (D)
- With Shift held, does an Explorer drop into the webview deliver `text/uri-list` to the DOM, and does a
  `TreeDragAndDropController` on the Fleet view receive it? (E)
- Does a Project-tree drag reach a Swing drop target on the JCEF component, or does CEF take it — in which case
  the channel is `CefDragHandler` and `CefDragData.getFileNames()`? (E)
- Does Edge's `--app` window accept an Explorer drop under corporate policy? (D)
- Should the scope become an edge in `ad-graph` — a ticket node with `scopes` edges — so `ad-graph refs RDSD-118`
  answers from the graph? Declined for now; `scope.toon` is that edge, written by a person. (F)

## Cost

The pre-flight costs no premium request. Each answer round is one resume — at least a third of a premium request
by [fleet-spike.md](fleet-spike.md)'s measurement — which is why answers are batched and why a `nit` no longer
buys one. A drop costs one hash in the page and a few `git` reads on the server; nothing is embedded, indexed or
uploaded unless the operator clicks *attach a copy*.
