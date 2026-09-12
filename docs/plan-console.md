# Plan: the console — one session, two surfaces, one file

_Status: IMPLEMENTED (2026-09-12) — epic #187 (slices #188–#193), under #91 (the fleet) and #122 (the desk), a
sibling of #145, #162, #170 and #179. The operator's sentence that started it: "we really need to figure out how to
get a cmd.exe window carrying a session directly into our fleet window. It is a top priority to have that shared
session understanding be synchronous." Every claim about what a Copilot console writes to disk is a row in the
runbook ([windows-verification.md](windows-verification.md) §The console, C1–C8), all of them still_ not yet
measured _— the code is written so that either answer to each one works, and the two heuristics that stand in for
an unmeasured fact (the pending-prompt sentence, the idle window) say in the interface that they are guesses. One
thing is built differently from what is written below, deliberately: the helper reaches the console's input buffer
through `CONIN$` rather than `GetStdHandle(STD_INPUT_HANDLE)`, because it is spawned with its stdio redirected so
the caller can read its TOON, and `AttachConsole` does not re-point handles that were redirected — `GetStdHandle`
would hand back the pipe and the line would vanish silently, which is the failure this epic exists to remove._

## Why this exists

The operator works in a `cmd.exe` window. That is where the Copilot session is: the conversation, the tool calls,
the yes/no prompts, the model's text. The fleet's tile for that checkout is supposed to be the same session, and
today it is a rumour of it. Read against the code, the gap is four things, each with a line that causes it:

| What the operator sees | What the code does | Section |
|---|---|---|
| The tile for the checkout the console is working in shows a run the fleet started days ago, and says nothing is supervised | the fleet's own agents get their events because `supervisor._spawn` redirects `copilot`'s stdout into `~/.agentdata/fleet/agents/<name>/events.jsonl` (`supervisor.py:326-333`); a session in a console has no such pipe, so `events.refresh` (`events.py:557-594`) has nothing to fold but `.agent/state.json` diffs and friction files | §The file |
| After *adopt it*, the chip says `running` whatever the console is doing, the transcript is empty, and *Send* is disabled with *type in that window* | adoption writes the lock with `external: True` and one synthetic `started` event (`adopt.py:303-312`); `supervisor.live()` then makes `agentstate.derive` classify it as a turn in progress (`agentstate.py:154-155`); `send` is refused because "there is no pipe to its stdin" (`supervisor.py:484-491`) — which is true, and is not the only way to put a line into a console | §The reply |
| The offer to adopt appears late, or not at all, and names a `copilot` that may be in a different checkout | on Windows a process's working directory is not readable without native calls (`adopt.py:14-20`), so the evidence is `.agent/state.json` having been touched within 15 minutes (`FRESH_S`, `adopt.py:43`) and *any* `copilot` in the process table (`adopt.py:224-227`); a session that only reads and thinks writes no state file, and nothing pushes the offer to the page until a poll cell changes (`serve.py:1586-1592`) | §Adopt, made exact |
| Two agents can end up in one working tree: a console the operator opened never took a lock, so `start`/`resume` only refuse where a pid can be *named* in that checkout | `supervisor.py:423-442`, the #174 note: "the console window that owns it never took one"; the guard fires only for candidates with a pid (`:433`) | §The console the fleet opens |

This is also the question [plan-desk-refactor.md](plan-desk-refactor.md) §Open questions left open on 2026-09-09
— *"Can the fleet see a Copilot session the operator started in a terminal … and if so, is attaching to it a
supervisor verb?"* — and the one [fleet-dashboard.md](fleet-dashboard.md) §Sessions the fleet did not start answers
with *"you cannot drag the console window in"*. Both are right about the window. Neither looked at the file.

**The one fact everything rests on.** Copilot CLI writes every session — interactive or `-p` — to
`~/.copilot/session-state/<session-id>/events.jsonl` as it runs, alongside a `workspace.yaml` and the row in
`~/.copilot/session-store.db` that `sessions.read_store_sessions` already reads (`sessions.py:73-139`). Public
descriptions of the file call it "a streaming log of what happened in a session: user and assistant turns, tool
activity, model changes, hooks, and session lifecycle events, all with timestamps", with `user.message` and
`assistant.message` among its types; the Copilot SDK names the directory as `session.workspace_path`. That is the
same catalogue `docs/fleet-spike.md` §The JSONL event catalogue measured on stdout and `events.from_copilot`
(`events.py:144-193`) already folds — reached by a second path. **The fleet has been reading this stream all along;
it has only ever read it from the one pipe it owned.** Whether an interactive session's file is appended per event
or flushed at turn boundaries, and whether its `type` names are the ones the spike recorded, is row C1, measured
before slice A lands; the plan is written so that either answer works and the runbook says which it was.

**"Synchronous" means one number.** A line the console's Copilot writes reaches the tile inside the bar the desk
already keeps for its own agents: `FOLD_EVERY_S + TICK_S < 1.0` (`serve.py:65-75`, pinned by
`tests/test_fleet_board_desk.py:517`), plus the page's 400 ms debounce for the chip. Not "instant", not "on the next
poll": under a second, measured, in both directions — the console's turn on the tile, and a reply typed on the tile
in the console.

**The purpose is the same as #122's, #145's, #162's, #170's and #179's: the human's attention.** One conversation,
two windows that show it, and neither of them lying about the other.

## What is reused

- The event contract and the fold: `events.from_copilot` (`events.py:144-193`), `KINDS` (`events.py:37-59`,
  additive only), the write lock (`events.py:402-497`), the cursor file with its `raw_lines` (`events.py:557-594`),
  `agentstate.derive`, `split_runs`, and the SSE loop's cadence (`serve.py:56-75`, `stream_events`
  `serve.py:1515-1619`). A console's session is folded by the same function on the same tick; the only new thing is
  where the raw lines come from.
- The lock, one agent per working tree: `supervisor.write_lock`/`live` (`supervisor.py:41-61`, `107-128`), the
  `external` branch that defers to `adopt.still_there` (`:120-127`), `pid_alive` (`:64-104`), `lifecycle.reap`. A
  console session holds the lock the way a fleet session does — with a pid this time.
- `launch_command` (`launch.py:208-245`): the flags the fleet already passes — `--add-dir`, `--log-dir`,
  `--log-level`, `--allow-tool`/`--deny-tool`, `--resume` — and the ones `docs/fleet-spike.md:189-203` measured
  and the fleet does not yet use: `--session-id`, `-C <dir>`. The console gets the enumerated allow-list the
  headless agent gets (`launch.py:34-68`); a console session is not an excuse for `--allow-all`
  (`FORBIDDEN_FLAGS`, `launch.py:107-108`).
- `proc.command`/`prepare` (`proc.py:143-196`): the `.cmd` shim unwrapped to `node.exe <index.js>`; a console runs
  the same resolved command, inside `cmd.exe` this time.
- `opener.start_server` (`opener.py:92-116`), the one place the package already reasons about consoles
  (`DETACHED_PROCESS` for the server); `CREATE_NEW_PROCESS_GROUP` in `_spawn` (`supervisor.py:319-324`).
- `adopt.py` — its claim model (`matched by working directory` / `inferred from recent activity`, `adopt.py:11-20`),
  `candidates` (`adopt.py:194-237`), the outside strip (`index.html:274-275`, `app.js:592-624`) and the two words
  on its button. A third claim is added between the two and the strip prints it.
- `sessions.read_store_sessions` (`sessions.py:73-139`) and its copy-on-read, read-only connection
  (`sessions.py:47-70`); `fold_stream`'s `source` (`sessions.py:211-212`) gains a value; the switcher (#174:
  `drawStrip`, `openSessions`, `showSession`, `resumeHere`, `app.js:737-893`) gains one button and one sentence.
- The refusal vocabulary: `live_agent`, `external_session`, `mid_turn`, `foreign_session` — and the rule that every
  refusal is the CLI's words and a `code` (`docs/refusals.md`).
- The fake `copilot` and its transcripts (`tests/fakes/runner.py`, `tests/fakes/copilot/transcripts/`): the fake
  learns to write `session-state/<id>/events.jsonl` under a fake home, so the console path is exercised on CI the
  way the headless path is.
- The browser harness, the shuffled suite, and the laptop runbook's convention: every failure becomes a regression
  test named for its host, every host claim is a row.
- The HIG, cited the way #145 cites it: *Windows* (a window is the operator's; a second surface for the same content
  must not fight the first for it), *Feedback* (say what changed and how old it is), *Accessibility* (every gesture
  has a key).

## Prior art, and what is different here

| Product | Does | Does not |
|---|---|---|
| Copilot CLI | writes every session to `~/.copilot/session-state/<id>/events.jsonl` and `session-store.db`; `--session-id`, `--resume <id>`, `--continue`, `-C <dir>`; `--acp` server mode | let a second process attach to an interactive session, or show two sessions side by side |
| Copilot SDK (`RuntimeConnection.for_uri`, `resume_session(id)`, `session.on(...)`) | drives a CLI it starts in server mode over JSON-RPC, streams events, handles permission requests in code | connect to a session in a terminal — server mode *is* the session's only surface, which is the opposite of what the operator asked for |
| Agent Eye (`ghcpCliDashboard`) | reads `session-state/<id>/events.jsonl` and `session-store.db` live, finds running `copilot` processes, focuses the terminal window from the dashboard | open the console for you, type into it, tie the session to a checkout's lock, or refuse a second agent in one working tree |
| VS Code's Agent Sessions view (`chat.agentSessions.showExternal`, `docs/fleet-ide.md:95-104`) | lists external Copilot CLI sessions | leave the editor; one repository per window |
| tmux / screen / `script` | attach a second terminal to a running session, log its bytes | exist on Windows in a form `cmd.exe` uses; and bytes on a screen are not events |
| Windows Terminal, conhost | host the console; the console API (`AttachConsole`, `WriteConsoleInput`, `GetConsoleWindow`) lets another process put input records into a console it did not create | offer any way to read a console's *conversation* — only its screen buffer, which the fleet does not want |

Three things none of them do, and this epic does:

1. **One session, two surfaces.** The console and the tile show the same session id, read from the same file. A turn
   typed in the console is on the tile inside a second; a reply typed on the tile lands in the console's input
   buffer; closing the console and pressing *Resume here* continues the same conversation headless, and *open in
   a console* on a headless tile continues it in `cmd.exe`.
2. **The console is the fleet's to open, never to own.** `ad-fleet console <repo>` opens a real `cmd.exe` running
   Copilot with a session id the fleet chose, so the tile knows the session before the first keystroke and the lock
   is taken on the operator's behalf — one agent per working tree holds for consoles too. The window is the
   operator's: the fleet never closes it and never sends it a Ctrl-C.
3. **Adoption reads the session, not the folder's timestamp.** A console the operator opened themselves is found by
   the session file whose working directory is the checkout and whose log is being written now — *matched by
   session file* — and adopting it tails that file, so the adopted tile gets the transcript, the turns and the cost
   it never had.

## The file: the console's session on the tile, synchronously

`~/.copilot/session-state/<id>/events.jsonl` becomes a second raw source for `events.refresh`. Today `_refresh`
reads one raw path — the supervisor's stdout redirect — into a `raw_lines` cursor (`events.py:557-594`). It gains
a second: when the lock names a `session` and no fleet process owns the stream (`kind: "console"`, or an adopted
session that names a session file), the raw path is Copilot's own file, with its own cursor (`console_lines` in
`events.cursor.json`, reset by `reset_raw_cursor` the way the rotated log's is, `events.py:105-116`). The lines go
through `from_copilot` unchanged: `assistant.message` → `assistant_text`, `tool.execution_start` → `tool_call`,
`tool.execution_complete` with `error.code == "denied"` → `denied`, `session.usage_checkpoint` → `cost`,
`assistant.turn_start`/`turn_end` → the turn boundaries the chip is derived from. Nothing new is invented; what
the interactive file carries that the headless stream does not (C1 and C2 decide: a user turn, a permission prompt
answered in the console) is folded as `raw` until it is measured and given a kind — additively, `SCHEMA` unchanged.

**Where the file is.** `sessions.session_state_path(id)` = `$COPILOT_SESSION_STATE/<id>/events.jsonl`, defaulting
to `~/.copilot/session-state/<id>/events.jsonl`, the same override pattern `COPILOT_SESSION_STORE` uses
(`sessions.py:20-22`). Read-only, by the same rule as the store: the fleet opens the file for reading and writes
nothing under `~/.copilot/`, ever.

**The cadence is the one the desk has.** The fold slot is claimed at most every `FOLD_EVERY_S = 0.5` and checked
every `TICK_S = 0.4` (`serve.py:65-75`); the console's file is read on the same tick as the fleet's own logs, by
the same `E.refresh`, so a line written by Copilot is an SSE `agent` frame inside 0.9 s and on the chip inside 1.3
s — the number `tests/test_fleet_board_desk.py:517` already pins. No file watcher, no thread per session: a
`stat()` per tick per console session is the cost, and the file is read from its cursor, not from the top
(`_refresh` re-reads the whole raw file today, `events.py:559-561`; slice A changes that to a byte offset for both
sources, because a console session's file grows for hours).

**What "live" means for a console.** `supervisor.live()` for a `kind: "console"` lock is `pid_alive(pid)` on the
console's own process — the fleet started `cmd.exe`, so it has a pid to ask about (`supervisor.py:64-104`). When
the window closes, the pid dies, `lifecycle.reap` writes `exited` with `why: "the console closed"`, and the
session is what #171 made every session: a record with a ticket and an ending, resumable by *Resume here*.

## The console the fleet opens

`ad-fleet console <repo> [--ticket KEY] [--resume <id>] [--new]`, `POST /api/console`, and a *console* button on
the tile's main tab beside *+ new* (#174's strip, `index.html:251-259`):

1. Mint the session id (`uuid4`) unless resuming; refuse if the checkout has a live agent (`live_agent`, the
   supervisor's words) unless the caller is the tile's *open in a console* on that same session, which stops the
   headless process at a turn boundary first (`mid_turn` refuses inside one, as today, `supervisor.py:478-524`).
2. Take the lock the supervisor takes, with two more fields: `kind: "console"` and the console host's `pid`;
   `session` is the minted id; `launch` is the argv. Append the `started` event with `data.console: true` and the
   session, so the run boundary exists before the first line of the file does.
3. Launch: on Windows, `cmd.exe /k "title <repo> · <ticket> & <resolved copilot argv>"` with
   `CREATE_NEW_CONSOLE`, `cwd=repo.path`, the argv being `launch_command`'s without `-p`, `--output-format json`
   and `--no-ask-user` — the interactive session asks the operator, that is the point — plus `--session-id <id>`
   (or `--resume <id>`), `-C <repo>`, the same `--add-dir`, `--log-dir`, `--allow-tool`/`--deny-tool`. Where
   `wt.exe` is on PATH and `fleet.console.host` says `wt`, the same command line goes through `wt -d <repo>`; the
   default is `cmd` because the pid the fleet holds must be the window's, and Windows Terminal reparents
   (C4 measures what `GetConsoleWindow` returns under it). On POSIX the same verb runs `x-terminal-emulator -e` when
   one exists and otherwise refuses with `no_console_host` — the epic is for the laptop, and CI proves the parts
   that are not a window.
4. The console wears the project's palette the way the operator's own consoles do: `theme.apply_conhost`
   (`theme.py:548-549`, the Win32 console API through `ctypes`, which `ad-theme apply` already uses on a bare
   `cmd.exe`) for conhost, the Windows Terminal fragment and the Clink hook ([themes.md](themes.md) §One theme
   per project) where those hosts are in play — the same functions, not a second colour table. The tab title is
   what the directory hooks already write: `<project> · <ticket> · <phase>` (OSC 2).

The tile then draws the console's session from its file (§The file), the chip from its turn boundaries, the cost
from its checkpoints, and the switcher's main tab reads `console · running · 4s`. *Send* on that tile is §The
reply. *Stop* is refused with one sentence — *close that window; the fleet opened it and does not close it* — and
`ad-fleet stop` says the same. The lock is released when the window's pid is gone, never by the fleet killing it.

**Two agents in one working tree, closed for good.** A console the fleet opened holds the lock, so `start`,
`send` and *Resume here* refuse with `live_agent` and name the console; the #174 gap closes for every console the
fleet opened, and §Adopt, made exact narrows it for the ones it did not.

## The reply: typing into the console from the tile

The fleet's `send` is "another `copilot -p <message> --resume <session>` process" (`supervisor.py:478-524`); for a
console session that would be a second agent in the working tree, so it is refused today and stays refused. What a
console *does* accept is input records in its input buffer, from any process the Windows console API lets attach:
`FreeConsole()`, `AttachConsole(pid)`, `WriteConsoleInputW(<the console's own `CONIN$` handle>, <the text as key
events, then Enter>)`, `FreeConsole()`. The package already speaks to the Win32 console through `ctypes` —
`theme.apply_conhost` recolours a bare `cmd.exe` with `SetConsoleScreenBufferInfoEx` (`theme.py:548-549`) — so
this is three more calls behind one function, not a new kind of dependency. That is `ad-fleet say <repo>
"<text>"`, and it is what the tile's reply box posts for a `kind: "console"` session:

- **A helper process, not the server.** `ad-fleet serve` may or may not have a console of its own (`opener.py:103`
  detaches it; `ad-fleet serve` from a shell does not), and a process has one console at a time; attaching from the
  server would race two tiles. `say` spawns `python -m agentdata fleet say-into <pid> <text>` with
  `CREATE_NO_WINDOW`, which attaches, writes, detaches and exits 0 — or exits with `console_unreachable` and the
  Win32 error, which the tile prints verbatim. `ctypes` only: `tests/test_console_host.py:224` bans `pywin32` and
  `winpty` and the plan keeps it that way.
- **What is typed is what was sent.** The text is written as one line followed by Enter; the console echoes it, the
  operator sees exactly what the tile sent, and the session's own file carries it as the user turn the tile then
  draws. There is no second channel to keep in step.
- **Focus follows a reply.** After a successful `say`, and as the fallback when `say` is refused, the tile offers
  *show the console*: `SetForegroundWindow` on the console's window — `GetConsoleWindow()` while attached for
  conhost; the hosting terminal's window for Windows Terminal (C4). A window the operator cannot find is the
  #133 tab shuffle again, in reverse.
- **Never a Ctrl-C.** `GenerateConsoleCtrlEvent` is not called by anything in this epic. Interrupting the operator's
  console is the operator's.

A permission prompt in the console (`y/n`) is not answered from the tile in this epic (C2 measures what the file
shows while one is pending); the tile says *the console is asking you something* and offers *show the console*.
`ad-state ask` questions are answered as today, through `answer` — that path writes `.agent/state.json` and needs
no console at all.

## One session, either surface

The session id is the join. Both surfaces write to Copilot's store and file under that id, and the fleet's stream
records which surface held it when:

- **Headless → console.** *open in a console* on a tile whose session the fleet started: stop the headless process
  at a turn boundary (`mid_turn` refuses inside one), `ad-fleet console <repo> --resume <id>`, the lock changes
  `kind`, the stream gets a `started` with `console: true, resumed: true`. The transcript continues from the same
  file the headless run wrote — Copilot's, not the fleet's — because `--resume` is Copilot's own continuation.
- **Console → headless.** The window closes; the reaper writes `exited`; *Resume here* (#174) does what it does
  today, `--resume <id>`, and the lock is a fleet lock again. The read-only pane's sentence for a `store` session,
  *a console window may still own this; close it first* (`app.js:836-839`), becomes exact: it is shown only while
  the console's pid is alive.
- **The session index** (#171, `sessions.py:169-257`) gains `source: "console"`; `rebuild_sessions` still appends
  store rows the stream does not know, and a console the fleet opened is never one of those, because the stream
  knew it first.
- **Cost.** `session.usage_checkpoint` lines in the console's file carry `totalPremiumRequests`; the high-water-mark
  rule (`sessions.py:220-227`) holds across surfaces because the checkpoint is Copilot's running total for the
  session, whichever surface spent it. `--usage-output-file` is not passed to a console (there is no final usage
  until the operator leaves).

## Adopt, made exact

For a console the operator opened themselves — no `--session-id` from the fleet, no lock — `adopt.candidates` gains
a third kind of evidence between the two it has (`adopt.py:217-232`): a session under `session-state/` whose
working directory is the checkout and whose `events.jsonl` was written within the last few seconds. Where that
working directory is read from is what S1 measures — `workspace.yaml` beside the log, or the store's `cwd` column
(`sessions.py:95-102` already selects it when the schema has it) — and the code takes either. The row's `how` reads
**matched by session file**: stronger than *inferred from recent activity* (it names the session and the
checkout), weaker than *matched by working directory* (no pid), and the strip prints it as it prints the other two.

Adopting such a session writes the lock with `kind: "console"`, `pid: 0`, the session id, and the file path — and
from that moment the tile tails the file (§The file). `still_there` (`adopt.py:343-358`) for it is the file's own
mtime within `fleet.console.idle_s` (default 90 s: a model thinking writes deltas; a person reading writes nothing,
so the number is the longest quiet the runbook observes plus margin), not the 15-minute `FRESH_S` of the state
file. `send` on an adopted console is `say`, if a pid can be named for it (`_windows_processes` lists them,
`adopt.py:88-122`; matching a pid to a session is C6) and refused with the same sentence as today if not.

`adopt.discover` (`adopt.py:240-262`) has no callers and goes.

## Where everything is written down

**`~/.agentdata/config.json`** — `fleet.console.host` (`cmd` | `wt`, default `cmd`); `fleet.console.idle_s`
(default 90); `fleet.console.prompt_s` (default 20); `fleet.console.palette` (default true); `fleet.console.helper`
(the argv the helpers are spawned behind, for CI); `COPILOT_SESSION_STATE` honoured as an environment override,
like `COPILOT_SESSION_STORE`.

**`~/.copilot/`** — read, never written. The store and the session files are Copilot's.

**The lock** (`~/.agentdata/fleet/agents/<name>/LOCK`) — `kind: "console"`, `session`, `pid` (the console host's,
or 0 for an adopted one), `session_file`. Fleet locks are unchanged.

**The event contract** — one new kind, `said`: what the fleet typed into a console it opened, the fleet's own act
the way `started` is, and the exact line the console echoes. Everything else is additive. `started.data` gains `console: true`; `exited.data.why` says
`"the console closed"`, the sentence [fleet-lifecycle.md](fleet-lifecycle.md) §A process that just stopped already
uses for it. What an interactive file carries that the headless stream does not is folded as `raw` until C1/C2
name it, then added — `SCHEMA` unchanged, additive only, per `events.py:1-19`.

**The cursor** (`events.cursor.json`) — `console_lines`, and byte offsets for both raw sources.

**The API** — `POST /api/console {repo, ticket?, resume?, new?}`; `POST /api/say {repo, message}`;
`POST /api/focus {repo}`; `POST /api/adopt` unchanged in shape, its row gains `session_file`.

**The CLI** — `ad-fleet console <repo>`, `ad-fleet say <repo> "<text>"`, `ad-fleet show-console <repo>`, and the
two helpers those spawn, `ad-fleet say-into <pid> <text>` and `ad-fleet focus-console <pid>`. The helpers take a
pid rather than a repository because attaching to a console is process-wide: they are what runs in the short-lived
process, and `fleet.console.helper` replaces the interpreter in front of them, which is how CI drives the whole
path with no console anywhere.

**The refusals** — `no_console_host`, `not_a_console`, `console_unreachable`, `unsupported_host`, each a row in
[refusals.md](refusals.md) naming its test, the way `tests/test_refusals.py` pins the count. `live_agent`,
`mid_turn`, `external_session` and `foreign_session` keep their words.

**The page** — one button on the strip, one sentence on the strip's tab, one more `how` on the outside strip, the
reply box routed by `kind`; class names and the page globals the regression tests call keep their names.

## Slices

Sizes are relative to #173 (= 1). Each lands with its own test against the fake and its own rows in the runbook.

| Slice | Title | Size | Needs | Unlocks |
|---|---|---|---|---|
| A #188 | the file: a console's session folded on the desk's own tick | 1½ | — | B, D, E |
| B #189 | the console the fleet opens, and the lock it takes | 1½ | A | C, D |
| C #190 | the reply: typing into the console from the tile | 1 | B | F |
| D #191 | one session, either surface | 1 | A, B | F |
| E #192 | adopt, made exact | 1 | A | F |
| F #193 | proof: the demo, the runbook rows, the fake that writes a session file | ½ | all | — |

### A #188 — the file: a console's session folded on the desk's own tick

**Context.** §The file. `events._refresh` (`events.py:557-594`) reads one raw path, the supervisor's stdout
redirect, into a `raw_lines` cursor, and re-reads the whole file each fold. Copilot writes every session to
`~/.copilot/session-state/<id>/events.jsonl`; the fleet has never read it.

**Build this.**
1. `sessions.session_state_dir()` and `session_state_path(id)`, defaulting to `~/.copilot/session-state`,
   overridable by `COPILOT_SESSION_STATE`; read-only by construction (open for reading; never `os.makedirs`,
   never a write, and a test that greps the module for both).
2. `events._refresh` reads from **byte offsets** for both raw sources (`raw_offset`, `console_offset` in the
   cursor; the old `raw_lines` is honoured once and converted), tolerates a partial last line (a writer mid-line
   is left for the next tick), and takes the console source from the lock: `kind == "console"` or an adopted
   `session_file`.
3. `from_copilot` unchanged; unknown durable types fold as `raw` with their `type` kept in `data`, so C1/C2 can
   read them off the stream and name them additively later.
4. The fake `copilot` (`tests/fakes/runner.py`) writes what it emits to `$COPILOT_SESSION_STATE/<session>/
   events.jsonl` as well as stdout when the environment names the directory, so CI has a session file that is
   written the way Copilot's is — line by line, over time (`sleep` steps exist already).
5. `docs/fleet-events.md` says where the second raw source is and that it is read from a byte offset.

**Acceptance criteria.**
- [ ] A test appends one line to a fixture `session-state/<id>/events.jsonl` while the server is up and reads it
      as an SSE `agent` frame inside `FOLD_EVERY_S + TICK_S`, the bar `tests/test_fleet_board_desk.py:517` keeps.
- [ ] A 50 MB fixture file is folded from its offset: the second fold reads only the bytes appended since the first
      (counted through a monkeypatched `open`), and a half-written last line is neither folded nor lost.
- [ ] `~/.copilot/` is never written: a test runs every fold and adoption path against a read-only fixture home
      and asserts nothing under it changed (mtime and listing), and a source test finds no write call in
      `sessions.py`'s session-state functions.
- [ ] The fake's session file and its stdout carry the same events in the same order.

**Out of scope.** Reading `session-store.db` for anything new (E does the matching); a file watcher.

### B #189 — the console the fleet opens, and the lock it takes

**Context.** §The console the fleet opens. Nothing in the package opens a console window (`opener.py` detaches the
server; `_spawn` inherits whatever console it has, `supervisor.py:319-324`); a console the operator opens never takes
a lock (`supervisor.py:423-442`).

**Build this.**
1. `supervisor.console(name, *, key=None, resume=None, new=False, cfg=None)`: the refusals `start` has
   (`check_ticket`, `live_agent`, `foreign_session`), the session id (`uuid4` or the resumed one), the lock with
   `kind: "console"`, `session`, `pid`, `launch`; the `started` event with `console: true`; then the launch.
2. `launch.console_command(...)`: `launch_command`'s argv without `-p`, `--output-format json` and
   `--no-ask-user`; plus `--session-id <id>` or `--resume <id>`, `-C <repo>`; the allow- and deny-lists unchanged.
   `FORBIDDEN_FLAGS` refused by name, as today.
3. The window: `cmd.exe /k "title <repo> · <ticket> & <argv>"` with `CREATE_NEW_CONSOLE` and `cwd=repo.path`;
   `fleet.console.host: wt` routes the same line through `wt -d <repo>`; POSIX uses `x-terminal-emulator -e` when
   present, else refuses `no_console_host`. The palette hook from `docs/shells.md` runs first, so the window is the
   project's colour.
4. `live()` for a `kind: "console"` lock is `pid_alive(pid)`; `lifecycle.reap` writes `exited` with
   `why: "the console closed"`; `stop` refuses with *close that window*; `send` routes to C (until C lands,
   it refuses with today's sentence).
5. `POST /api/console`, `ad-fleet console <repo> [--ticket] [--resume] [--new]`, the *console* button on the
   strip's main tab (`index.html:251-259`, `drawStrip` `app.js:737-773`), and `docs/fleet-dashboard.md` §The
   switcher says what it does.

**Acceptance criteria.**
- [ ] With a fake host (`fleet.console.host: fake` in tests: the fake `copilot` run directly, no window), `ad-fleet
      console luna --ticket RDSD-7` takes the lock with `kind: console` and a pid, appends `started` with
      `console: true`, and the tile reads the fake's session file live: the transcript, the turn, the cost.
- [ ] While it is live, `ad-fleet start luna`, `ad-fleet send luna "…"` and *Resume here* refuse with `live_agent`
      naming the console; `ad-fleet stop luna` refuses with *close that window* and kills nothing.
- [ ] Killing the fake host's pid ends the run: `exited` with the console sentence, the lock gone, `sessions.json`
      showing the session with `source: console` and an ending.
- [ ] `console_command`'s argv carries no `-p`, no `--no-ask-user`, no `--output-format`, the enumerated
      allow-list, `--session-id <uuid>`, and `-C <repo>`; a config asking for `--allow-all` is refused by name.

**Out of scope.** Choosing the terminal emulator beyond `cmd`/`wt`; a console for a checkout with no ticket
(allowed — `--ticket` is optional, as `start`'s key is).

### C #190 — the reply: typing into the console from the tile

**Context.** §The reply. `send` is a second `copilot -p --resume` process (`supervisor.py:478-524`), refused for a
session the fleet did not start because "there is no pipe to its stdin" (`:484-491`). A console accepts input
records from a process that attaches to it.

**Build this.**
1. `agentdata/fleet/console.py`: `say_into(pid, text)` on Windows via `ctypes` — `FreeConsole`, `AttachConsole`,
   `WriteConsoleInputW` (key down/up per character, then Enter), `FreeConsole`; every failure is
   `ConsoleError(code="console_unreachable", win32=<n>)`. On POSIX it raises `unsupported_host`. No `pywin32`,
   no `winpty` (`tests/test_console_host.py:224`).
2. `ad-fleet say-into <pid> <text>`: the helper, module-only, exit 0 or the refusal as TOON; spawned by `say` with
   `CREATE_NO_WINDOW` and never from the server's own process.
3. `supervisor.say(name, text)`: refuses unless the lock is `kind: "console"` with a pid; runs the helper; returns
   `{ok, echoed: text}` or the helper's refusal verbatim. `POST /api/say`, `ad-fleet say <repo> "<text>"`; the
   tile's reply box posts `say` for a console lock and `send` otherwise (`app.js:625-632`).
4. `focus_console(pid)`: `SetForegroundWindow` on `GetConsoleWindow()` while attached, or on the hosting terminal's
   window when C4 says how; *show the console* on the tile after a reply and as the fallback sentence when `say`
   is refused.
5. The tile's chip while the console has a pending prompt: `waiting for you, in the console`, from what C2 finds in
   the file; until then, the sentence appears when a `tool_call` has had no result for `fleet.console.prompt_s`
   (default 20 s) — a heuristic, labelled as one, replaced by the measured event.

**Acceptance criteria.**
- [ ] On CI, `say` against a `kind: console` lock spawns the helper with the pid and the text (a fake helper
      records its argv), and the tile shows the text as the session's next user turn once the fake's file carries
      it; `say` against a fleet lock is refused with `not_a_console`, and against no lock with `no_agent`.
- [ ] A helper failure (`console_unreachable`, a Win32 code) reaches the tile verbatim with *show the console*
      beside it, and the reply box keeps the text.
- [ ] Laptop rows C3 and C4 pass on conhost and on Windows Terminal, or the runbook records which one fails and why,
      before this slice is called done.

**Out of scope.** Answering a `y/n` permission prompt from the tile; sending Ctrl-C; reading the console's screen
buffer.

### D #191 — one session, either surface

**Context.** §One session, either surface. #174's switcher has *Resume here* and *+ new* (`app.js:876-893`,
`resumeHere`); a `store` session's sentence *a console window may still own this* is a guess (`app.js:836-839`).

**Build this.**
1. *open in a console* on the main tab of a fleet-started session: `stop` at a turn boundary (`mid_turn` refuses
   inside one and the button says so), then `console(name, resume=<id>)`; the stream gets `started` with
   `console: true, resumed: true`.
2. *Resume here* on a session whose console closed: unchanged in code, one more sentence in the pane while the
   console's pid is alive (`the console still owns this — close it, then resume`), exact instead of guessed.
3. `fold_stream` sets `source: "console"` from `started.data.console`; `sessions.json` rows carry it; the switcher's
   tab reads `console` while a console holds the session.
4. `docs/fleet-dashboard.md` §The switcher and `docs/plan-sessions.md`'s open question about resuming from a
   different directory get their answer (S3, measured in F).

**Acceptance criteria.**
- [ ] A test starts a fake headless session, presses *open in a console* (fake host), and finds one lock with
      `kind: console` and the same session id, a `started` with `resumed: true`, and the transcript continuing —
      the fake's `resume_steps` on the same session file.
- [ ] Killing the fake host and pressing *Resume here* starts one headless `--resume <id>` and no more; the run
      line reads `resumed`; `sessions.json` shows one session, two runs, sources `console` then `fleet`.
- [ ] *open in a console* inside a turn is refused with `mid_turn` and starts nothing.

**Out of scope.** Two consoles on one session; moving a session between checkouts.

### E #192 — adopt, made exact

**Context.** §Adopt, made exact. `adopt.candidates` (`adopt.py:194-237`) has two kinds of evidence and, on
Windows, attributes any `copilot` in the process table to any checkout written to recently (`:224-227`); an adopted
tile has no transcript (`adopt.py:22-27`).

**Build this.**
1. `sessions.session_files(repo_path)`: the session directories under `session-state/` whose working directory is
   the checkout — from `workspace.yaml` beside the log or from the store's `cwd` column, whichever S1 finds; the
   function takes either and says which it used — sorted by the log's mtime.
2. `candidates` adds `how: "matched by session file"` with `session` and `session_file` when such a file was
   written within `fleet.console.idle_s`; it outranks *inferred from recent activity* and is outranked by *matched
   by working directory*. The strip prints it (`app.js:613-616`).
3. `adopt(name, session=...)` writes `kind: "console"`, `pid: 0` (or the pid a matching `_windows_processes` row
   gives, C6), `session`, `session_file`; `still_there` for it is the file's mtime within `idle_s`; the tile tails
   the file from adoption on (slice A's source).
4. `discover` removed; `release` unchanged.
5. Runbook S1 gets its answer written into the code path and `docs/fleet-dashboard.md` §Sessions the fleet did not
   start says the third claim.

**Acceptance criteria.**
- [ ] With a fixture `session-state` naming the checkout (both schema shapes tested: `workspace.yaml` with a
      working directory, and a store row with `cwd`), the outside strip offers the session as *matched by session
      file* within one fold of the file being written, and never offers a `copilot` running in another checkout.
- [ ] Adopting it makes the tile show the session's transcript, turns and cost from the file; `still_there` is
      false `idle_s` after the last line and the tile says so.
- [ ] A checkout merely saved to (state file touched, no session file) is still offered as *inferred from recent
      activity*, unchanged.

**Out of scope.** Adopting a session whose working directory is not a registered checkout; adopting two.

### F #193 — proof: the demo, the runbook rows, the fake that writes a session file

**Context.** #102's, #176's and #185's shape: the epic is done when the fake proves it on CI and the laptop rows say
what only the laptop can.

**Build this.**
1. `tests/test_fleet_demo_console.py` (`-m slow`): a console session (fake host) on a checkout, the tile reading
   its file live, a reply through `say` (fake helper) appearing as the next user turn, the window closing, *Resume
   here* continuing it headless — counted in `started`, `exited` and one `--resume`.
2. `docs/windows-verification.md` §The console: rows C1–C8, all *not yet measured*: C1 the interactive file is
   appended per event with the spike's type names; C2 what a pending `y/n` and an `ask_user` look like in it; C3
   `say-into` on conhost; C4 `say-into` and focus under Windows Terminal; C5 `--session-id` on a fresh session and
   `--resume` with `-C` from another directory (S3); C6 a `session-state` id matched to a `copilot` pid; C7 the
   console wears the project's palette; C8 two consoles on one checkout — the second refused by the lock, and what
   adopt says about one the operator opened beside a fleet one.
3. This plan's status line to IMPLEMENTED; `docs/fleet-dashboard.md` §Endpoints and `docs/fleet.md` name the two
   verbs.

**Acceptance criteria.**
- [ ] The demo passes on Linux and Windows CI inside the slow job's budget.
- [ ] Every runbook row carries a host and a date, or *not yet measured* — never blank.
- [ ] `tests/test_entrypoints.py` checks every command this plan names once its status is IMPLEMENTED.

## Ground rules

1. **One session, one file.** The tile never invents a second record of a console's session; it reads Copilot's
   own, from an offset, on the desk's tick. Every line the tile shows is a line the console can show.
2. **`~/.copilot/` is read and never written.** The store, the session files, the workspace metadata: opened for
   reading, by a function a test greps for writes.
3. **The console is the operator's window.** The fleet opens it, names it, focuses it, and types into it what the
   operator typed on the tile; it never closes it, never sends it a Ctrl-C, never answers its prompts.
4. **One agent per working tree, consoles included.** A console the fleet opened holds the lock with its pid; an
   adopted one holds it on the session file's evidence; `start`, `send` and *Resume here* refuse in the supervisor's
   words while either does.
5. **Every refusal is the CLI's words and a `code`**, and every claim about a session says how sure it is:
   *matched by working directory*, *matched by session file*, *inferred from recent activity*.
6. **No native dependencies.** `ctypes` on Windows for three console calls, behind one function; `pywin32` and
   `winpty` stay banned.
7. **Synchronous is a number, kept by a test.** `FOLD_EVERY_S + TICK_S < 1.0` covers the console's file too.
8. **Additive events, unchanged schema.** New durable types from the interactive file fold as `raw` until measured,
   then get a kind; `SCHEMA` does not move.
9. **The page is a view.** Every button is a verb: `console`, `say`, `adopt`, `start --resume`.
10. **Measured on the laptop.** Eight rows, in the runbook, before the epic is called done; every one that fails
    becomes a regression test named for its host.

## Build order

A first (everything reads through it) → B → C and D in any order, after B → E after A, any time → F last. A alone
already gives an adopted session its transcript once E names the file; B alone already closes the #174 gap for
consoles the fleet opens.

## Open questions, to be answered on the laptop and recorded in the slice

- Is an interactive session's `events.jsonl` appended per event, or flushed at turn boundaries — and are its `type`
  names the spike's? (A, C1)
- What does the file carry while the console waits on a `y/n` permission or an `ask_user`? Is there an event to
  derive *waiting for you, in the console* from, or only silence? (C, C2)
- Does `AttachConsole` + `WriteConsoleInputW` reach a Copilot session under Windows Terminal as it does under
  conhost, and what does `GetConsoleWindow` return there? (C, C3–C4)
- Does `--session-id` create a session with that id on a fresh start, and does `--resume` with `-C <repo>` keep the
  session's working directory? (B, D, C5/S3)
- Which file carries the session's working directory — `workspace.yaml` or the store's `cwd` — and can a
  `session-state` id be matched to a `copilot` pid on Windows without native calls? (E, S1, C6)
- Does `cmd.exe /k` started by the fleet pick up the project's palette from the shell hook? (B, C7)
- What is the longest quiet a thinking model leaves in the file — the number `fleet.console.idle_s` defaults from?
  (E, C1)

## Cost

Reading a console's session costs one `stat()` per tick per console and nothing in premium requests: the file is
written by a session the operator is already paying for. Opening a console costs what the operator's own console
costs. Typing a reply from the tile costs one short-lived helper process. What this epic removes is the expensive
thing: a session the operator is watching in one window and the fleet is guessing at in another, which is a
premium request spent twice — once by the model, once by the person reconciling two pictures of it.
