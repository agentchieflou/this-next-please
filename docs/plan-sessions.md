# Plan: sessions — the desk remembers where every agent is, and every session is a thing you can find again

_Status: IMPLEMENTED (2026-09-11) — epic #170 (slices #171–#176), under #91 (the fleet) and #122 (the desk), a
sibling of #145 and #162. Every slice is built and covered, including the demo
(`tests/test_fleet_demo_sessions.py`). Every page claim below is still to be **measured** on the laptop in Edge,
PyCharm's JCEF window and VS Code's Simple Browser, the way #145's were: the rows are in
[windows-verification.md](windows-verification.md#the-handoff-162-and-sessions-170-what-only-the-laptop-can-answer),
each one marked *not yet measured* until a host and a date are written against it._

## Why this exists

The operator's sentence is *"users lose track of their agent windows"*. Read against the code, it is five findings,
each with a line that causes it:

| What the operator sees | What the code does | Section |
|---|---|---|
| A tile they were reading is gone, and nothing says where | zoom hides every other tile (`app.css` `body.focused .tile:not(.is-focused)`), focus mode hides every quiet tile and is sticky per window in `localStorage`, a solo window hides everything but one project, the laptop view hides the grid; `1`–`9` reads the *unfiltered* order, so zooming a tile focus mode is hiding blanks the window — and a Windows toast's `#tile=` anchor can do the same, or, for a tile that does not exist, nothing at all | §Hide and reopen |
| Closing the dashboard and opening it again loses the desk | `serve.run()`'s `finally` calls `reset()`, which blanks the selection and every layout's arrangement **and saves that to `desk.json`** — a clean `Ctrl-C` erases the desk while a hard kill keeps it; every run mints a new token so every open tab's URL dies; held tiles, unread counts, the open sidebar section and the zoom live in page memory | §The desk comes back |
| Yesterday's session cannot be found, let alone reopened | the session id is read only from the live raw `events.jsonl` (`supervisor.session_id`); rotation destroys it and `send` then refuses *no session to continue*; a fresh `start` writes no session into the lock, so a `send` after a start that died before its first `result` resumes **yesterday's** session; `ad-fleet status` and `history` do not show the id; the tile truncates it to eight characters; earlier runs carry no id; nothing lists sessions and no verb accepts one | §A session is a thing |
| There is no way to start a new session beside the old one, or to go back to an old one | `start` refuses on a live agent and `--force` *replaces*; `launch_command` knows only `--resume <the one id>`; `--continue` and `--session-id` are listed in [fleet-spike.md](fleet-spike.md) and used nowhere; the earlier-run rows are text with no handler | §The switcher |
| A second checkout of the same repository is a stranger to the first | the registry keys everything on `name`, locates by `path`, and has no notion of a git repository; a worktree scans as an unrelated project with a blank branch (the catalogue never follows a `gitdir:` pointer, by design), gets its own colour, and makes every Downloads file for that Jira project `unsorted` because two entries now declare it | §Checkouts |

Four more things are structural rather than visible. `serve.split_runs` says a run begins at every `started`
event; `board.history` says only at one that is not `resumed` — the tile and the report disagree about what a run
is. `lifecycle.slept()` has one caller, a test. Adoption never learns the foreign session's id, so an adopted
session can never be resumed by the fleet. And Copilot's own session store — `~/.copilot/session-store.db`, which
holds every session on the machine — is never read.

**The purpose is the same as #122's, #145's and #162's: the human's attention.** Three questions a glance should
answer, and today the desk answers none of them: *where is the agent I was reading*, *what happened while I was
away*, *how do I get back to yesterday*.

## What is reused

- `events.norm.jsonl` already carries `session_id` and `started` (`resumed`, `session`) events. A session index
  is a fold of the stream — like the state, like the catalogue — rebuildable from what is on disk, never the
  source of truth.
- `desk.json` and the `desk` SSE event already hold the arrangement per layout and the selection. Hidden tiles and
  window records are more of the same state, held the same way, pushed the same way.
- `supervisor.restart` already launches `--resume <session>`. Resuming a *chosen* session is the same argv with a
  chosen id; `send` is unchanged.
- The lock stays what it is: one live agent per registered working tree. A session is a record; an agent is a
  process. Nothing here runs two processes in one checkout.
- `adopt.py`'s discovery and the outside strip; `/open`, the tokenless redirect; the `#tile=` anchor the toasts
  use; `notifications.jsonl` and `notify.state.json`, which already record what happened while nobody was looking.
- The registry (`name`, `path`, `jira_project`); `Repo.extra` exists and is splatted on save — it only has to be
  read back.
- `poll.read_git` shells out to `git status --porcelain=v2 --branch` in the checkout, so it is already correct
  for a worktree; it becomes the one reader of the branch.
- The browser harness (#146) and `tests/test_fleet_desk_regressions.py`, whose page globals — `toggleTileSize`,
  `toggleTilePin`, `moveTile`, `choose`, `getEffectiveOrder`, `getLayoutArrangement` — are a public API this plan
  keeps.
- The HIG, cited the way #145 cites it: *Windows* (a window restores its state on relaunch), *Tab views* (one
  content area, peers as tabs, the selected one unmistakable), *Sidebars*, *Notifications* (never hide what needs
  a person), *Feedback* (say what changed and how old it is), *Accessibility* (every gesture has a key).

## Prior art, and what is different here

| Product | Does | Does not |
|---|---|---|
| Copilot CLI | `--continue`, a `--resume` picker, `--resume <id>`; `/session delete`, `/session prune`; every session in `~/.copilot/session-store.db` (`sessions`, `turns`, `checkpoints`, `session_files`, `session_refs`) and `~/.copilot/session-state/` | know which sessions belong to which checkout on a desk, tie one to a ticket and how it ended, or show two at once |
| VS Code's Agent Sessions view | lists local and Copilot CLI sessions (`chat.agentSessions.showExternal`), one worktree per parallel session | leave the editor window; one repository per window |
| Claude Code (`--resume`, `--continue`, the desktop app's session list), Cursor's agents sidebar, Conductor-style "one worktree per agent, one tab each" | a session list and a tab per agent, inside one product on one repository | run on a page three embedders render, across N checkouts, with the outcome, cost and ticket on each row |

Three things none of them do, and this epic does:

1. **The desk comes back the way it was left**, per window, with a line saying what happened while it was away.
2. **A hidden tile is never a lost tile.** Hidden, zoomed, solo or focused, the fold's *needs you* always reaches
   the glass, and every tile that is not on the glass is one click from it.
3. **A session is a record with a ticket and an ending**, listed per checkout — the fleet's own, the adopted, and
   the ones Copilot's store knows about — and any of them is one click from being the tile's current session,
   under the same one-agent-per-working-tree rule as today.

## The model

```
project      the git repository                           a name and a colour; jira_project
  checkout   a working tree the fleet registered (path)   one lock; at most one live agent
    session  a Copilot conversation id, resumable         many per checkout; one is current
      run    what one `started` begins                    the transcript boundary
```

A tile is a checkout's current session. Its tab strip is the checkout's sibling checkouts (for a project with
worktrees) and, folded behind *earlier (n)*, the checkout's other sessions. Today's model is the same picture with
one row per level: one project per checkout, one session per checkout, and the tile showing whichever run came
last.

## A session is a thing

`~/.agentdata/fleet/agents/<name>/sessions.json` is a fold of `events.norm.jsonl` — every `session_id` and
`started` event, every `exited`/`error` after it — into one row per session:

```
sessions[3]{id,title,ticket,first_seen,last_seen,runs,ended,cost,source}:
  1f0a6c2e-…,"RDSD-118 UAT refresh is slow",RDSD-118,2026-09-10T14:02,2026-09-10T17:40,3,done,4.33,fleet
  7f3a9b10-…,"RDSD-101 Six measures are unused",RDSD-101,2026-09-09T09:14,2026-09-09T11:02,1,blocked,1.00,fleet
  c81d…,"(console) copilot in this checkout",,2026-09-11T08:50,2026-09-11T09:20,,,store
```

It is rebuilt by `ad-fleet sessions <repo> --rebuild` and never edited by hand; a `title` set by
`ad-fleet sessions rename` is the one field that is not derived, kept beside the fold, never in history.

**The id is read from the normalized stream**, not the raw log, so rotation stops losing it. A fresh `start`
records `session: ""` in the lock and stamps `started` with `new: true`, so a `send` after a start that died before
its first `result` can no longer resume the previous conversation. `earlier[]` carries `session`; `ad-fleet status`
and `history` gain a `session` column; the run line shows the session's *title* and keeps the full id under the
cursor and on a *copy* button. `split_runs` and `board.history` read one `runs.py`, which names both things they
were each half-describing: a **run** begins at every `started`; a **dispatch** is a run whose `started` is not
`resumed`. The tile counts runs; the report counts dispatches; both say which.

**Resuming a chosen session** is `ad-fleet start <repo> --resume <id>`; **a clean one beside it** is
`ad-fleet start <repo> --new` — the previous session stays listed and resumable. `restart` and `reset` are
`--resume <current>` as today. `--continue` is deliberately not used: the fleet always knows which id it means.

**Copilot's store, read and never written.** When `~/.copilot/session-store.db` is readable, sessions whose
`repository` (and working directory, if the schema carries one — an open question) match a registered checkout
appear with `source: store` and the weaker label the outside strip already uses for its inferred claim. A doctor
row, `fleet/session store`, says `ok`, `warn: not readable`, or `skip: none`, because *no sessions found* and *the
store is not being read* look identical from a list. The store's schema is measured on the laptop before a line of
SQL is committed, and the reader opens it read-only with a copy-on-read fallback for a locked file. This is also how
**adoption learns the foreign session's id**: an adopted session gains `session` in its lock and its `started`
event, and once the console that owns it is gone, *Resume here* makes it the fleet's — which is the answer to
*I started it in a terminal yesterday*.

`lifecycle.slept()` is wired into the poller: a wall-clock jump probes every live pid, and a run that ended that
way ends with `exited` whose `why` says *the laptop slept*, so the tile offers *resume* instead of wearing a chip
from before the nap.

## The desk comes back

**`reset()` stops erasing the desk.** It was written for a fleet moving under a live process (tests), and it
also runs in `run()`'s `finally`. It splits: *drop the handles* runs on shutdown; *forget the desk* runs only when
the fleet directory changes. `desk.json` on a clean shutdown is `desk.json` on the next start, and a test drives
the shutdown path, which no test does today.

**A window has a name.** `?w=<name>` in the URL — `main` when absent — and a record on the server:

```
~/.agentdata/fleet/desk.json
  selected, screens, version, arrangement        # what #149 persisted, unchanged
  windows:
    main:  { layout, view, screen, focus, zoomed, section, held: [...], read: {repo: seq}, seen: ts }
    left:  { ... }
```

`POST /api/window {w, …}` is the one write; it rides the `desk` event. Focus mode, the zoomed tile, the open
sidebar section, the held set and the read-up-to cursor move from page memory and `localStorage` to the window's
record — the per-window *rule* from [fleet-layouts.md](fleet-layouts.md) stays; only the storage moves, so
`--port 0` and a new token no longer reset them. `/open?w=left` is the tokenless bookmark per window,
`ad-fleet open --window left` opens one, `ad-fleet open --all` opens every window the desk remembers. When the
stream dies and the next request answers `403` — the server restarted and the token changed — the page navigates
itself through `/open` carrying `w`, `layout`, `view` and `screen`, so a tab left open overnight comes back
instead of dying on a token.

**Since you were away.** Each window records `seen` when it last drew. On the next draw it shows one line per
tile that changed since — *luna: asked a question · 2h ago*, *rdsd-uat: finished · PR open* — from
`agentstate.transitions` and `notifications.jsonl`, the same rules the notifier fired on, so the strip cannot
disagree with the badges. Dismissable, and the tab title keeps its count.

**A reload keeps what a person would expect it to keep:** the zoomed tile, the open section, the held tiles, the
unread counts, and the transcript scroll position when the operator had scrolled up (a new event no longer yanks
the pane to the bottom while someone is reading — HIG *Feedback*). What it still loses is what it should: the
text in a reply box and an armed *Reset anyway*.

## Hide and reopen, and never hide what needs you

**`hidden` joins `order`, `size` and `pinned`** in `arrangement[layout]`, server state shared across windows the
way the rest of the arrangement is (the sitting may decide it should be per window; §Open questions). A tile is
hidden from its header button or with `h` on the focused tile; its slot in `order` is kept, so reopening puts it
back where it was.

**The dock.** A strip along the bottom of the grid — collapsed to a count when empty — holds one chip per tile
that is not on the glass: its name, its state chip with the age, its unread badge. A click reopens it in place;
*show all* reopens every hidden tile; the strip is keyboard-reachable and each chip is a button. The dock is also
where the two silent things become visible: a repository that left the registry keeps a chip for a day (*luna was
removed from the registry · `ad-fleet repo add` restores it*) instead of vanishing with its transcript, and a
newly registered one is announced there (*new: rdsd-uat · show*) instead of appearing below the fold. While a tile
is zoomed, the dock shows the other tiles, so nine agents becoming one is nine agents becoming one and eight
chips.

**Never hide what needs a person.** The rule is one predicate, `needs_the_human`, applied in one place:

| The tile is | And the fold says it needs you | So |
|---|---|---|
| hidden | yes | its dock chip goes red with the why line; it chimes as usual; in focus mode it is *shown*, with a note like the held note — *hidden, shown because it needs you* |
| off the glass because another tile is zoomed | yes | its chip goes red in the dock; `Esc` still returns to the grid |
| in a solo window | — | unchanged; a solo window exists to show one tile |
| the target of a `#tile=` anchor and hidden | — | the anchor **reopens** it and says so in the footer |
| the target of a `#tile=` anchor and unregistered | — | the footer says *no tile for `<repo>`* instead of nothing |

`1`–`9` and `Alt+←/→` read the *visible* order, so a digit can no longer zoom a tile focus mode is hiding, and the
number on a tile is still the key that focuses it. Leaving focus mode no longer clears the held set — the held set
is the operator's working set, and it lives in the window record now.

## The switcher: the main tab and the ones beside it

Under the run line, a **tab strip** (HIG *Tab views*):

```
[ main · running · 4m ]  [ feature/RDSD-118 · needs you · 20m ]  [ earlier (3) ▾ ]  [ + new ]
```

- The **main tab** is this checkout's current session — where the transcript, the reply box and the cards are.
- The tabs beside it are the project's **other checkouts** (§Checkouts), each with its own chip and age, because
  each has its own agent. Clicking one selects that checkout's tile; the strip stays, so the way back is one
  click and never `Esc`.
- **earlier (n)** opens this checkout's other sessions from `sessions.json`: title, ticket, how it ended, when,
  cost, `source`. Choosing one shows its transcript **read-only** from history (`GET /api/transcript?repo=&session=`
  — the same fold the tile uses, over the whole stream, paged), with the reply box replaced by one sentence and one
  button: *this session ended blocked on Tuesday · **Resume here***.
- **Resume here** is `start --resume <id>`. When nothing is live it just runs. When an agent is live it is the
  existing refusal with its hint, and the button becomes the two-press *Stop and resume*, the way *Reset anyway*
  is a second, deliberate press. Never two agents in one working tree, and never a silent force.
- **+ new** is `start --new`: a clean session in this checkout with the ticket box optional; with a ticket, the
  dispatch card from #164 applies as it would to a drop.
- `Alt+[` / `Alt+]` move along the strip; `Alt+N` is *new*; every tab is a button with the session's title as its
  accessible name.

A `store` session behaves the same way with one more sentence: *a console window may still own this; close it
first* — and *Resume here* is refused while that checkout has a live pid the fleet did not start, with the adopt
strip's own words.

## Checkouts of one project

The registry gains one field, `project`, defaulting to `name` so every existing registry is unchanged by
definition. **`Repo.extra` round-trips first** — `load()` drops unknown keys today, so nothing can be added until
it does.

`ad-fleet repo add <path>` of a directory whose `.git` is a *file* reads its one `gitdir:` line, walks back to the
main checkout and, if that checkout is registered, defaults `project` to its name and `name` to
`<project>-<basename>`. This is the only place a `gitdir:` pointer is ever followed — at an explicit human `add`,
once, with the resolved main path kept in `extra` so nothing at runtime follows it again. `scan.py`'s rule stands:
an unattended walk reads no second repository's internals. The scan does say what it found — *a worktree of
`proj`; would be registered as a checkout of it* — in the one line the human decides on, and `worktree_of` joins
the scan columns.

**The fleet never creates a checkout.** `git worktree add` is the operator's, in git or the IDE; the scan finds
it, the registry groups it.

One branch, from one reader: `show_for` takes the branch from the poll's git cell, which shells out in the
checkout and is already worktree-correct, so the catalogue's `_inside` wall — realpath every read, refuse anything
outside the repository — is not touched for the sake of one string.

One colour per project (`theme.projects.<project>` before `<name>`, seeded by the project; the shell hooks emit
longest path first so a nested worktree is not shadowed by its parent) and one inbox answer per project (a tie
between two checkouts of one project resolves to the one whose `active_ticket` matches, then to the primary,
instead of `unsorted`). `repo rm` names the agent directory it leaves behind so `gc` can take it.

`docs/fleet.md`'s *one agent per repository* becomes *one agent per registered working tree*, which is what the
lock has always meant.

## Where everything is written down

**`desk.json`** (all under `~/.agentdata/fleet/`, nothing inside a repository):

| Key | New or grown | Holds |
|---|---|---|
| `arrangement[layout].hidden` | new | the tiles off the glass, per layout |
| `windows[name]` | new | `layout, view, screen, focus, zoomed, section, held, read, seen` |
| `selected, screens, arrangement.order/size/pinned` | unchanged | #149's state |

**`agents/<name>/sessions.json`** — new; a fold, rebuildable; `title` the one non-derived field.

**`registry.json`** — `project` on each entry (defaults to `name`); `extra.worktree_of` when known; `extra`
read back.

**The event contract** — no new kinds; two grown, additively, at schema `1`:

| Kind | Grows | Why |
|---|---|---|
| `started` | `new: true` for `--new`; `session` on an adopted start when the store supplies it | the index needs the boundary and the id |
| `exited` | `why: "the laptop slept"` | the sleep case was silent |

**The API:** `GET /api/sessions?repo=`, `GET /api/transcript?repo=&session=`, `POST /api/window`,
`POST /api/start {…, resume?, new?}`, `GET /open?w=`; `arrange` accepts `hidden`. Every one is an `ad-fleet` verb
first: `sessions [--rebuild] [rename <id> "<title>"]`, `start --resume <id> | --new`, `open --window <w> | --all`,
`hide <repo>` / `unhide <repo>`.

## Slices

| # | Slice | Fixes | Needs | After |
|---|---|---|---|---|
| A #171 | a session is a record: `sessions.json`, the id from the normalized stream, `--resume <id>` and `--new`, one run definition, the store reader behind a doctor row, sleep wired in | yesterday's session unfindable; `send` resuming the wrong conversation | — | — |
| B #172 | the desk comes back: `reset()` split, window records, `/open?w=`, the page re-homing itself, *since you were away* | a clean shutdown erasing the desk; tabs dying on a token; memory-only state | — | — |
| C #173 | hide and reopen: `hidden`, the dock, never hide what needs you, anchors that say something, visible-order keys | tiles lost to zoom, focus, solo and the registry | B | B |
| D #174 | the switcher: the tab strip, read-only history, *Resume here*, *+ new*, the keys | no way beside or back | A, C | A, C |
| E #175 | checkouts of one project: `project` in the registry, the worktree add, the scan line, one branch, one colour, one inbox answer, the sibling tabs | a worktree as a stranger | A, D | A, D |
| F #176 | proof: the shutdown and restore tests, a fake-copilot session round trip, the laptop rows, the demo | — | all | all |

### A #171 — a session is a record

**Context.** §A session is a thing. Today the resumable id is read from the live raw log only (`supervisor.session_id`),
rotation loses it, a fresh `start` does not reset it, earlier runs carry no id, `status` and `history` do not show
it, two modules disagree about what a run is, adoption never learns the foreign id, and the store is never read.

**Build this.**
1. `fleet/sessions.py`: the fold into `sessions.json`, `ad-fleet sessions <repo> [--rebuild] [rename <id> "<title>"]`,
   `GET /api/sessions?repo=`; `title` kept beside the fold; every other field derived.
2. `session_id()` from the normalized stream; `session: ""` in a fresh start's lock; `new: true` on its
   `started`; a regression test for *send after a dead start resumed yesterday's session*.
3. `fleet/runs.py` with *run* and *dispatch*, read by `split_runs` and `board.history`; `earlier[]` carries
   `session`; `status` and `history` gain the column; the run line shows the title and copies the id.
4. `start --resume <id>` and `start --new` in `supervisor.start`, `launch_command` and the CLI; `--continue` and
   `--session-id` stay unused and the plan says why.
5. The store reader: read-only, copy-on-read when locked, schema measured first; rows with `source: store` matched
   by `repository` (and cwd when the schema has it); the `fleet/session store` doctor row; adoption's lock and
   `started` gain `session` when the store supplies it.
6. `lifecycle.slept()` wired into the poller; the `exited` with `why`.

**Acceptance criteria.**
- [ ] A stream with three sessions folds into three rows with the right `ended` and `cost` (the high-water mark,
      never a sum), and `--rebuild` from the same stream is byte-identical.
- [ ] A rotated raw log no longer makes `send` refuse; a start that dies before its first `result` followed by a
      `send` refuses with *no session to continue* instead of resuming the old one.
- [ ] `ad-fleet history` and the tile agree on what they count and say which word they are counting.
- [ ] With no store on the machine every test passes and the doctor row says `skip`; with a fixture store, a
      console session in a registered checkout appears with `source: store` and the weaker label.
- [ ] A wall-clock jump of three minutes with a dead pid produces one `exited` whose `why` names sleep, and no
      `error`.

**Out of scope.** Any page change beyond the run line; writing to the store, ever; `/session prune` on the
operator's behalf.

### B #172 — the desk comes back

**Context.** §The desk comes back. `reset()` erases `desk.json` on a clean shutdown; the token is per run; focus
mode and chime are in `localStorage`; the zoom is a hash; held, unread and the open section are page memory.

**Build this.**
1. Split `reset()`: `drop_handles()` on shutdown, `forget_desk()` only when the fleet directory moves; a test that
   runs `serve.run()` to its `finally` and reads `desk.json` afterwards.
2. `?w=<name>`, `windows[name]` in `desk.json`, `POST /api/window`, the `desk` event carrying windows; focus,
   zoomed, section, held and read-up-to move into the record; `localStorage` keeps only the chime.
3. `/open?w=`, `ad-fleet open --window <w>` and `--all`; the page re-homes itself through `/open` on the first
   `403` after a dead stream, keeping `w`, `layout`, `view` and `screen`.
4. *Since you were away*: `seen` per window; the strip from `agentstate.transitions` and `notifications.jsonl`
   since then; dismissable; the title count unchanged.
5. The transcript pane stops force-scrolling while the operator has scrolled up; the position is kept across a
   reload.

**Acceptance criteria.**
- [ ] `ad-fleet serve`, arrange, select, hide, `Ctrl-C`, `ad-fleet serve` again: a rendered-page test reads the same
      arrangement and selection, and the same zoomed tile in the same named window.
- [ ] Two windows named `left` and `main` keep different focus-mode states across a server restart on a new port.
- [ ] A tab open across a server restart draws the new run's tiles without a hand-typed URL.
- [ ] A window reopened after two tiles changed state shows two *since you were away* lines and no more.
- [ ] `test_fleet_shells.py` still passes: the shells learn `?w=` as a pass-through and nothing else.

**Out of scope.** Restoring window *placement* on the monitors (the OS's and the browser's, per
[fleet-layouts.md](fleet-layouts.md)); a per-window token.

### C #173 — hide and reopen, and never hide what needs you

**Context.** §Hide and reopen. There is no hide, no reopen, no list of what is off the glass; five `display:none`
rules and one `.remove()` take tiles away as side effects of modes.

**Build this.**
1. `hidden` in `arrangement[layout]`, `POST /api/arrange` accepting it, `ad-fleet hide <repo>` / `unhide <repo>`;
   the header button and `h`; the slot in `order` kept.
2. The dock: chips with state, age and badge; click to reopen; *show all*; keyboard-reachable; collapsed to a
   count when empty; the zoomed case shows the others; registry departures and arrivals announced there.
3. The *never hide* table: red chips, chime, shown-in-focus-mode with the note, anchors that reopen or say *no
   tile*; `1`–`9` and `Alt+←/→` over the visible order; leaving focus mode keeps the held set.
4. The tile numbers stop renumbering on reorder within a sitting (the number is the key; a key that changes under
   the hand is not a key) — measured on the laptop before it is changed, because #149 chose the current rule.

**Acceptance criteria.**
- [ ] A rendered-page test hides a tile, reloads, reads it in the dock with its chip, reopens it, and reads it in
      its old slot.
- [ ] A hidden tile whose fixture turns `needs_human` shows a red dock chip with the why line, and in focus mode is
      on the glass with the note.
- [ ] Zooming a tile focus mode hides no longer blanks the window: a test presses a digit for such a tile and reads
      a non-empty grid.
- [ ] `#tile=` for a hidden tile reopens it; for an unregistered name the footer says so; neither is silent.
- [ ] Removing a repository from the registry while the page is open leaves a dock chip that names the command to
      restore it.

**Out of scope.** Moving a tile between windows (the `screens` swap is that already); the sitting's per-window
question, recorded but not decided here.

### D #174 — the switcher

**Context.** §The switcher. The earlier-run rows are text with no handler; the only session-changing gesture is
adopt, which then disables Send.

**Build this.**
1. The tab strip under the run line: the main tab, sibling checkouts (E supplies them; before E the strip has one
   tab and *earlier*), *earlier (n)*, *+ new*; every tab a button.
2. `GET /api/transcript?repo=&session=`, paged, the same fold; the read-only pane with its one sentence and one
   button.
3. *Resume here* → `start --resume <id>`; live agent → the refusal with its hint and the two-press *Stop and
   resume*; a `store` session refused while a foreign pid is live, in the adopt strip's words.
4. *+ new* → `start --new`; with a ticket, #164's card.
5. `Alt+[`, `Alt+]`, `Alt+N`; accessible names from the session titles.

**Acceptance criteria.**
- [ ] A fake-copilot transcript: session 1 ends blocked; *+ new* starts session 2; *earlier* shows session 1 with
      its ending; *Resume here* on it refuses while 2 is live and succeeds after *Stop and resume*, and the
      resumed process is launched with `--resume <session 1>`.
- [ ] Choosing an earlier session never spawns anything — asserted by counting `started` events.
- [ ] The strip is operable end to end without a mouse in a rendered-page test.
- [ ] The public page globals the regression tests call are unchanged.

**Out of scope.** Editing a session's transcript; deleting a session (that is Copilot's `/session delete`, and
the fleet's index only forgets on `--rebuild`).

### E #175 — checkouts of one project

**Context.** §Checkouts. Two worktrees register as two strangers with the same links, blank branches, two colours
and an inbox that gives up.

**Build this.**
1. `Repo.extra` read back by `load()`; `project` on the record defaulting to `name`; `extra.worktree_of`.
2. `repo add` follows the `gitdir:` line once, at the human's add; `--project <name>` to say it by hand; the scan's
   `worktree_of` column and its *why* line.
3. `show_for` takes the branch from the poll's git cell; the catalogue's wall is untouched.
4. `desk_snapshot` and `supervisor.status` carry `project`; the page groups a project's checkouts as sibling tabs
   on one tile, pinned, hidden and ordered as one; the dock chip is the project's.
5. `theme.projects.<project>` before `<name>`, seeded by the project; hook rules longest path first.
6. `inbox._match` resolves a tie inside one project by `active_ticket`, then the primary, never `unsorted`.
7. `repo rm` names the orphan agent directory; `gc` takes it; `docs/fleet.md` says *one agent per registered
   working tree*.

**Acceptance criteria.**
- [ ] A registry written by the previous release loads with `project == name` for every entry and saves back
      byte-identical.
- [ ] `repo add` of a fixture worktree registers it as `proj-<basename>` with `project: proj`; the scan's line says
      *a worktree of proj*.
- [ ] `/api/show` for the worktree carries its own branch; `ad-fleet where` no longer prints a blank one.
- [ ] Two checkouts of one project share a colour in the terminal hook and on the tiles; a nested worktree gets its
      own, not its parent's.
- [ ] A Downloads file naming the project's Jira key is offered to the checkout whose `active_ticket` matches, and
      is not `unsorted`.
- [ ] Both checkouts run agents at once, with two locks, and `tests/test_fleet_e2e.py`'s walk still finds nothing
      written outside `.agent/`.

**Out of scope.** Creating worktrees; a `project` that spans two *repositories*; per-project approval or budget
(each agent keeps its own).

### F #176 — proof

**Context.** #102's shape, for this epic.

**Build this.**
1. The fake `copilot` learns to answer `--resume <id>` with a `result` carrying that id and `--new` with a fresh
   one, and to write rows a fixture store can hold.
2. `docs/windows-verification.md` rows for every laptop measurement A–E named: the store's schema and whether it
   carries a working directory, two agents sharing the store, `--resume` from a different cwd, JCEF and Simple
   Browser keeping `?w=`, the nested-worktree colour, the tile-number rule.
3. The demo, on CI against the fake: two checkouts of one project registered, one hidden, the desk closed with
   `Ctrl-C` and reopened by name, the hidden tile turning red in the dock and reopening from a toast anchor, an
   earlier session resumed by *Stop and resume*, and the *since you were away* strip naming every change.

**Acceptance criteria.**
- [ ] The demo passes on Linux and Windows CI with the browser installed, inside the suite's two-minute Linux
      budget.
- [ ] Every open question below is answered in the runbook with the host and the date, or marked *not yet
      measured*.
- [ ] This plan's status line moves to IMPLEMENTED, at which point `tests/test_entrypoints.py` checks every command
      it names.

## Ground rules

1. **The page is a view.** Every strip and chip is server state; every button calls the function an `ad-fleet`
   verb calls; every refusal is the CLI's words and a `code`.
2. **One live agent per registered working tree, still.** A session is a record; an agent is a process. Nothing
   here runs two processes in one checkout, and every *resume* onto a live checkout is a refusal first and a
   deliberate second press.
3. **Never hide what needs a person.** Hidden, zoomed, solo or focused, `needs_the_human` reaches the glass, and
   the rule lives in one predicate.
4. **History is additive and never rewritten.** `sessions.json` is a fold, rebuildable, never the source; a title
   is the one field beside it.
5. **Copilot's store is read, never written**, behind a doctor row; a missing or locked store changes nothing.
6. **A window's identity is a name in its URL and a record on the server.** The token stays per run; `/open`
   carries the name.
7. **Nothing is written inside a repository.** Every file this plan adds is under `~/.agentdata/fleet/`.
8. **No framework, no build step, no CDN**; the page globals the tests call keep their names.
9. **Decided on the real screens.** Per-window or shared `hidden`, the dock's edge, the tile-number rule: defaults
   ship, the sitting corrects, and no code concludes what the sitting has not.
10. **Every laptop failure becomes a named regression test**, with the host in its name.

## Build order

#171 and #172 in any order → #173 after #172 → #174 after #171 and #173 → #175 after #171 and #174 → #176 last,
though every slice lands with its own rendered-page test. #171 alone already fixes the wrong-session `send`; #172
alone already makes a clean shutdown keep the desk.

## Open questions, to be answered on the laptop and recorded in the slice

- Does `sessions` in `~/.copilot/session-store.db` carry a working directory, or only `repository`? Does
  `--resume <id>` from a different directory than the session's work? (A) — **half answered.** The
  console epic's `sessions.session_files` (#192) reads the working directory from either shape:
  `workspace.yaml` beside the session log, or the store's `cwd` column where the schema has one, and
  it says which it used. Whether `--resume <id>` with `-C <repo>` keeps the session's own working
  directory is runbook row C5 in [windows-verification.md](windows-verification.md), not yet
  measured; every caller in the fleet passes `-C` with the checkout it means, so either answer is
  survivable.
- Two fleets' agents sharing one store — [fleet-spike.md](fleet-spike.md)'s open question, still open. (A)
- Do JCEF and Simple Browser hand the page its own `?w=` back after the IDE restores the tool window? (B)
- `hidden` per window or per layout — the sitting decides; per layout ships. (C)
- Should the tile number stay put on reorder — #149 chose renumbering so the badge matches the key; C measures
  whether a stable name reads better on the real screens. (C)
- On Windows, where a process's working directory is not readable without native calls, does the store's row give
  adoption an exact match instead of *inferred from recent activity*? (A, D)

## Cost

Listing, hiding, reopening, switching the *view* and coming back cost nothing: they are reads of files the fleet
already writes. Resuming a session is one turn — at least a third of a premium request by
[fleet-spike.md](fleet-spike.md)'s measurement — and *+ new* is a first turn at full price, which is why the
strip shows how each earlier session ended before offering to resume it.
