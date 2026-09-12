# The multi-viewer

One local page, one tile per agent, live. The epic is named for YouTube's multi-view and this is
that page: a grid of agents, any one of which can be blown up to fill the window and dropped back.

```bash
ad-fleet serve --open
```

```
meta:
  ok: true
  source: ad-fleet serve
  url: "http://127.0.0.1:8765/?t=Yb3h…"
  port: 8765
  bound: 127.0.0.1 only
  note: "the token in the URL is required on every request; stop with Ctrl-C"
```

`--port 0` picks a free port. Either way the URL is written to
`~/.agentdata/fleet/serve.json`, so the IDE shells (#99, #100) can find the page without being told
where it is.

## Why a web page

The same artefact has to render in a PyCharm JCEF tool window, in VS Code's Simple Browser, and in
Edge on a fourth monitor. Those three embedders agree on exactly one thing, and it is HTML — so
#99 and #100 only have to decide *where* the page is shown, not build it again.

It is `http.server` and `ThreadingHTTPServer` from the standard library, SSE over a plain chunked
response, and hand-written HTML/CSS/JS shipped as package data. **No bundler, no framework, no
CDN**: JCEF and Simple Browser both sit behind the corporate proxy, so anything the page fetches
from the internet is a page that does not load at work — and it would look like a bug in the fleet
rather than in the markup. A test asserts the static files contain no external reference at all,
and the server sends `Content-Security-Policy: default-src 'self'` so the browser enforces it too.

The whole payload is about 20 kB.

## The URL and the token

The socket binds **127.0.0.1 and nothing else**. Every run generates a fresh token, and every
request — page, API and event stream — must carry it as `?t=…`. A request without it, or from a
non-loopback address, gets `403 not authorized` and is not told which of the two it got wrong.

The token is deliberately **not** a cookie. A cookie would be sent automatically by any page in the
browser, which is exactly what makes a local server on a known port drivable from a hostile tab;
a query parameter has to be known to be used.

This is loopback security, not authentication. It is the right size for a tool that runs on the
operator's own machine and is never reachable from another one. Remote access is out of scope.

## The page

**A tile is the agent. The sidebar is the project.** They used to be one thing, and a tile carrying
its own link rail, verify pane, file tray and fact block left no room for the transcript.

| On a tile | What it shows |
| --- | --- |
| Header | drag handle, number, repo name, **state chip with its age**, ticket, pin, width |
| Run line | which run this transcript belongs to: `run 3 · started 14:02 · resumed · session 7f3a · 41 events · live` |
| Why line | the one sentence from the fold — the unblock sentence, the refused tool, the question |
| Cells | the **project's** own state, polled read-only: ticket, PR, refresh, git — each with its age; the git cell counts the branches and opens the inspector's branches pane (#184) |
| Approval card | appears when that agent is waiting; the **dry-run payload in full**, Approve / Deny |
| Transcript | assistant text, tool calls, denials, phase changes — the current run only |
| Earlier runs | one collapsed row per earlier run with the state it ended in; never replayed as live |
| Outside strip | a session in this checkout the fleet did not start: what it is, how sure we are, and *adopt it* |
| Held note | in focus mode only, on a tile you acted on: why it is still here, and *let it go* |
| Bottom row | reply box (→ `send`), Start (a ticket key in the same box), **Reset**, Stop |

The **sidebar** sits beside the grid and holds five sections, one open at a time: the Jira **board**
(`b`), the Downloads **inbox** (`i`), **alerts** (`n`), **where** (`/`, `ad-fleet where` over the
catalogue), and **project** — the selected project's link rail, verify pane, facts, open friction
and offered files. Every window on this server agrees on which project is selected, so clicking a
tile on the left monitor changes the inspector on the centre one.

A **console** the fleet opens (#189) is a session the operator drives in their own `cmd.exe` window,
started by `ad-fleet console <repo> [KEY]` with a session id the fleet chose. The lock is taken the
way `start` takes it, with the window's pid, so one agent per working tree holds for consoles too;
the tile reads the session from Copilot's own file for it (`~/.copilot/session-state/<id>/events.jsonl`,
#188) on the same tick as its own logs — a line the console's Copilot writes is on the tile inside a
second. *Stop* refuses with *close that window*: the fleet opened it and does not close it; when the
window closes, the run ends with *the console closed* and *Resume here* continues it headless.

The tile's reply box **types into that window** rather than starting a second agent beside it (#190).
`send` is another `copilot -p --resume` process, which in a checkout that already has a console is
exactly the thing one-agent-per-working-tree exists to refuse; `ad-fleet say <repo> "<text>"` and
`POST /api/say` instead spawn a short-lived helper that attaches to the console by pid and writes the
line as key events, followed by Enter. The console echoes it, the fleet records what it typed as a
`said` event, and what the session makes of it comes back through Copilot's own file — one line, one
record of it. While a console holds the tile, the *console* tab reads **show console** and raises
that window (`ad-fleet show-console <repo>`, `POST /api/focus`); a window the operator cannot find is
no better than a session they cannot see. The helper never sends a Ctrl-C and never answers a
prompt: a console sitting on one tool call for `fleet.console.prompt_s` (default 20 s) says *waiting
for you, in the console?* beside its chip, with the question mark, because the CLI writes no
permission-request event and time is the only evidence there is.

The **project** section carries a **branches** pane (#184): the default branch and the current one's
distance from it, one row per local branch — name, last commit and its age, ahead of the default,
upstream or *none pushed*, the ticket key the name carries — the ones that never reached the
default first and marked, then the last twenty commits of the current branch. A branch whose name
carries the tile's active ticket is that ticket's; a second one with the same key is the smell the
operator asked to see, and the pane says so in one line: *two branches carry RDSD-22490; only one
can merge*. The pane is read on the click and cached for the git cell's interval, never on the poll.
On the tile, the git cell is the button that opens it and carries the count on its second line:
`7 branches · 3 never reached main`, amber at `fleet.branches.warn` (default 6), grey with the error
when git cannot be asked, and never a toast. `ad-fleet branches <repo>` prints the same rows.

At the top of the board is the **agent rail** (#183): one chip per registered checkout — the dock's
chip, name and state and age — each a drop target. A ticket dragged over it lights the candidates
`board.suggest` names for that key and dims the rest; a drop calls exactly what a drop on the tile
calls, so the board window (`?layout=roles&view=board`, where there are no tiles) hands a ticket
over with the same pre-flight card and the same refusals in the supervisor's words. The card is one
element the page owns, drawn in the tile when the tile is on the glass and under the rail when it
is not — it used to draw inside a hidden tile, so the window built for handing tickets over was the
one place the hand-over skipped its pre-flight. A ticket row takes the keyboard: `1`–`9` picks the
rail chip in that position, `Enter` the row's one candidate.

The **toolbar** is three labelled groups and one row: *window* (the layout segments, and which window
of that set this one is), *see* (search, the sidebar, and a *look* button), and *needs me* (focus
mode, chime, the bell). The palette and skin pickers are behind *look* (#180): they are chosen once
a week, not once a minute, and two `<select>`s were the widest things on the bar — HIG *Toolbars*
keeps the commands for the current context on the bar and puts a choice that rarely changes
somewhere a person goes on purpose. The footer keeps the two things that change — the counts and
the notice — and a `?` button (or the `?` key) opens the key map in four short columns. A cell that
fails to poll goes **grey with the error in a tooltip**, never wrong; a link with no fact behind it
is absent, never broken.

The grid follows the number of registered repositories: four repos, four tiles. Click a repo name
(or double-click a tile) and it fills the window; `Esc` returns to the grid. Tiles that change place
**travel** there rather than jumping, so you can see that the tile you were reading is the same one,
lower down; only the paint moves, so the grid is in its final state throughout and a click during the
movement lands where you aimed it. `prefers-reduced-motion` turns it off.

### Reset, and why it is one button

`Reset` is `stop` and then `restart` — end whatever is holding the checkout, then resume *the same
session*, so the agent keeps the ticket it has read and the plan it has made. It exists because the
two commands were the answer and nobody could find the question: an agent stops answering in a
console window, and neither `ad-fleet stop` nor `ad-fleet start` is named after that. Both halves may
still refuse. A process that outlives the kill keeps its lock and nothing is started beside it — two
agents in one working tree is what the lock exists to prevent — and `fleet.max_restarts` refuses past
its limit, at which point the button reads *Reset anyway* and one more press spends the extra turn.
Never a silent force.

### Held tiles

Focus mode shows the agents the fold says need a person. Answering one is exactly what stops it
needing you, so a reply used to hide the tile it was typed into: the action's only visible outcome
was that the thing you were working on vanished. A tile you have acted on is **held** — still on
screen, dimmed, saying which action held it — until you release it or leave focus mode. A held tile
that goes back to needing somebody drops the note and reads as a normal demand again; it never takes
the credit for a question it did not answer.

### The switcher — the main tab and the ones beside it (#174)

The earlier-run rows were text with no handler, and the only session-changing gesture in the whole
page was *adopt* — which then disabled Send. A session you had finished with was something you
could read about and not open, and *I started it in a terminal yesterday* had no answer at all.

Under the run line there is a **tab strip**:

```
[ main · running · 4m ]  [ feature/RDSD-118 · needs you · 20m ]  [ earlier (3) ]  [ + new ]
```

* The **main tab** is this checkout's live session — where the transcript, the reply box and the
  cards are.
* The tabs beside it are the project's **other checkouts** (#175), each with its own agent, its own
  branch and its own chip — a tile is still one working tree. Clicking one selects that checkout's
  tile; the strip stays, so the way back is one click and never `Esc`.
* **earlier (n)** lists this checkout's other sessions — title, how it ended, when, what it cost.
  The count comes off the event stream the tile already has, not off `sessions.json`, which exists
  only once somebody has rebuilt it; a tab reading *earlier (0)* over three real sessions would be
  worse than no tab.
* Choosing one shows its transcript **read-only** from history (`GET /api/transcript`), with the
  reply box *gone* rather than disabled — a box you can type in that cannot send is a worse answer
  than no box — replaced by one sentence and one button: *this session ended blocked · 2 days ago ·
  **Resume here***. The live transcript is hidden, never thrown away, so going back is instant and
  whole.
* **Resume here** is `start --resume <id>`. With nothing live it runs. With an agent live, or with
  the checkout mid-ticket on this session's own ticket — which is exactly what a console that has
  been working leaves behind — it is the supervisor's own refusal and its own hint, and the button
  becomes the two-press *Stop and resume* or *Resume anyway*, the way *Reset anyway* is a second,
  deliberate press. Never two agents in one working tree, and never a silent force.
* **+ new** is `start --new`: a clean session in this checkout, the previous one still listed and
  still resumable.
* The **console** tab is one button and three verbs (#189–#191). With no console here it opens one
  and hands it *this tile's session*, so a session the fleet started headless carries on in the
  operator's own window under the same id — the transcript continues because `--resume` is
  Copilot's own continuation, not a replay. Inside a turn it refuses with `mid_turn`: a session
  moves surfaces between turns, and stopping one halfway leaves the working tree wherever the
  thought had reached. With a console already here the same button reads **show console** and
  raises that window. When it closes, the run ends with *the console closed* and *Resume here*
  brings the session back headless. Each row in *earlier* names the surfaces its session has been
  held by, in order (`console → fleet`), and the read-only pane says *the console still owns this*
  only while this checkout's console is actually alive.
* `Alt`+`[` / `Alt`+`]` walk the strip and `Alt`+`N` is *new*. Every tab is a real button, so the
  strip is reachable by Tab as well.

A session is **not** a contiguous slice of the stream — `--resume` opens a new run on the same
conversation, and runs of another session can sit between them — so a transcript is gathered by the
id its runs carry, never by position.

Resuming is refused outright where a process the fleet did not start can be **named** in that
checkout, in the adopt strip's own words. Only where it can be named: *this folder was written to
in the last quarter of an hour* is evidence of somebody saving a file, and refusing every resume on
that would refuse nearly all of them.

### The dock — where a tile went (#173)

Five `display:none` rules and one `.remove()` used to take a tile off the glass as a side effect of
a mode — zoom, focus mode, a solo window, the laptop's narrow view, and a repository leaving the
registry — and nothing anywhere said where it had gone. The operator's own answer was to reload the
page and hope.

The **dock** is a strip along the bottom with one chip per tile that is not on the glass. Each chip
says the repo name, the state the tile was in and how old it is, and how many transcript lines have
arrived since you last looked. One click puts it back, and the chip knows *why* it went, so it
undoes the right thing: a hidden tile is unhidden, one quieted by focus mode leaves focus mode, one
zoomed past unzooms. A chip for a repository that has **left the registry** says so and offers the
`ad-fleet repo add <path>` that would bring it back, rather than the tile simply being gone.

A project's checkouts are hidden and pinned as one, so they leave the glass together and come back
as **one chip** saying how many it brings — two chips for one piece of work would be two things to
click for one decision.

A chip whose agent **needs a person** is red and chimes like the tile would — but that case should
not arise from hiding, because a tile that needs somebody is on the glass whatever the arrangement
says. *Show all* empties `hidden` in one press.

`#tile=<repo>` — the anchor the Windows toasts and both IDE shells use — **reopens** a hidden tile
rather than quietly doing nothing, and the footer says it did. An anchor naming a repository with no
tile now says *no tile for 'x' — is it still registered?*; it used to do nothing at all, which read
as the dashboard having hung.

### Sessions the fleet did not start

A `copilot` running in a console window is an agent working in a registered checkout that the fleet
knows nothing about, so the tile drew the last run *the fleet* started and said nothing was
supervised. The page finds those and offers to **adopt** one, which makes it that repository's
current run.

You cannot drag the console window in — a window drag carries no process identity, and a dropped
folder's real path is deliberately withheld from web pages — so the portal finds the session instead.
On POSIX it matches a process to a checkout by its working directory and says `matched by working
directory`. On Windows a working directory is not readable without native calls this package will not
make, so the evidence is the checkout itself: `.agent/state.json` has exactly one writer, and a state
file touched in the last few minutes is a session somebody is having right now. That reads `inferred
from recent activity`, and it is labelled differently because it is a weaker claim.

A third claim sits between the two (#192): **matched by session file** — Copilot's own file for a
session whose working directory is this checkout (`~/.copilot/session-state/<id>/events.jsonl`,
placed by its `workspace.yaml` or by the store's `cwd` column, whichever the machine carries) was
written within the last `fleet.console.idle_s` seconds (default 90). It names the session, so it
outranks the folder's timestamp; it names no pid, so it is outranked by a process matched to the
folder. Adopting such a session makes the tile tail that file: the transcript, the turns and the
cost an adopted session never had, and liveness is the file's own quiet, not the state file's.

Adoption **supersedes; it does not supervise.** The fleet did not start that process, has no pipe to
its stdin and may not know its pid, so Send and Start are disabled and say where to type instead of
being offered and quietly doing nothing. One checkout still holds one agent: a repo the fleet is
already running an agent in cannot adopt a second. *Hand it back* releases it, and only ever removes
a lock the fleet did not create.

The same page has three arrangements and a focus mode, chosen by the query string —
`ad-fleet serve --layout grid|roles|screens`. Which one is the default is **still being decided on
the real screens**: [fleet-layouts.md](fleet-layouts.md). `grid` ships as the default pending that
sitting; an unknown `?layout=` falls back to it with a notice in the footer.

Chip colours are fixed across every theme, because a chip that means "needs you" has to be the same
red everywhere or the colour stops being information:

| Colour | State |
| --- | --- |
| blue | `running` |
| amber | `waiting_approval` |
| red | `needs_human`, `blocked`, `error` |
| green | `done` |
| grey | `starting`, `idle` |

### Keyboard

| Key | Does |
| --- | --- |
| `?` | the key map — this table, in four columns, behind the footer's `?` button |
| `1`–`9` | focus that tile — counting what is **on the glass** |
| `f` | focus mode: only the agents that need you |
| `h` | hide the tile the keyboard is on; its chip is in the dock |
| `Alt`+`[` / `Alt`+`]` | walk the tile's session strip |
| `Alt`+`N` | a clean session in this checkout, beside the one it is on |
| `/` | the search box — `where` over the catalogue |
| `i` | the sidebar's inbox |
| `a` | approve the focused tile's pending write |
| `b` | the sidebar's Jira board |
| `n` | the sidebar's alerts |
| `Alt`+`←` / `Alt`+`→` | move the focused tile one slot |
| `Alt`+`Home` | pin the focused tile first |
| `Alt`+`Enter` | one column or two |
| `Esc` | close a popover, the sidebar, or back to the grid (or out of a text box) — the nearest open thing first |

The number on a tile is the key that focuses it, and it follows the arrangement: move a tile and its
number moves with it, and a tile that is off the glass has no number at all — a digit that zoomed a
tile a mode was already hiding left a blank window, because zoom hides every other tile. Every drag gesture has a keyboard equivalent, because a desk that can only be
arranged with a mouse cannot be arranged by someone who is typing.

Deny has no shortcut on purpose: it needs a reason typed, and a one-key refusal with an empty
reason is the failure mode the gate was built to avoid.

## Themes

The dashboard shares its palettes 1:1 with the terminal: palettes come from `agentdata.theme` (#136, #150, #153),
rendered as CSS custom properties (`--bg`, `--text`, `--panel`, `--line`, `--select`, `--muted`, `--accent`,
`--focus`, `--running`, `--waiting`, `--human`, `--done`, `--idle`).

Theme choice is configured in `~/.agentdata/config.json` via `theme.default` (e.g. `ad-theme set greens --default`),
while each registered repository carries its project accent on its tile (`theme.projects.<name>`).
When `config.json` changes, `ad-fleet serve` broadcasts a `theme` SSE event, recolouring open windows
without a page reload. `none` follows system `prefers-color-scheme`.

## Endpoints

| Method | Path | What |
| --- | --- | --- |
| GET | `/` | the page |
| GET | `/static/…` | its two assets |
| GET | `/api/fleet` | every repo's state, the recent events, and the pending approvals |
| GET | `/api/events` | SSE; `?since=luna:12,other:4` resumes per agent |
| GET | `/api/themes` | the `.icls` palettes |
| GET | `/api/board` | your Jira tickets, and which repo each one belongs to |
| GET | `/api/history` | what was dispatched, how it ended, what it cost |
| GET | `/api/notifications` | what has been announced |
| GET | `/api/desk` | per project: links, polled cells, verify summaries, offered files, the selection |
| GET | `/api/show` | one project from the catalogue: facts, state, friction, PBIP |
| GET | `/api/inbox` | the tray: what Downloads is offering, and what is listed but not offered |
| GET | `/api/where` | the catalogue search behind the header's box |
| POST | `/api/start` | `{repo, ticket?, prompt?, force?}` |
| POST | `/api/send` | `{repo, message}` |
| POST | `/api/stop` | `{repo}` |
| POST | `/api/reset` | `{repo, force?}` — stop, then resume the same session |
| POST | `/api/adopt` | `{repo, pid?}` — take on a session the fleet did not start |
| POST | `/api/release` | `{repo}` — hand an adopted session back |
| POST | `/api/approve` | `{id, reason?}` |
| POST | `/api/deny` | `{id, reason}` |
| POST | `/api/select` | `{repo?, screens?}` — the project every window agrees on ([fleet-layouts.md](fleet-layouts.md)) |
| POST | `/api/arrange` | `{layout, order?, size?, pinned?, hidden?}` — the desk, shared by every window (#173) |
| POST | `/api/attach` | `{id, repo}` — copies one Downloads file into `<repo>/.agent/in/<KEY>/` |
| POST | `/api/answer` | `{repo, answers: [{id, answer}]}` — every answer in one resume (#165) |
| POST | `/api/scope/resolve` | `{repo, files: [{name, size, sha}]}` — which of this checkout's files these are (#166) |
| POST | `/api/scope` | `{repo, paths, why, how}` — append them to `.agent/in/<KEY>/scope.toon` |
| POST | `/api/attach-bytes` | `{repo, name, bytes}` — the one route that carries bytes, on a click |
| GET | `/api/sessions` | `?repo=` — this checkout's sessions, folded from the stream on the click |
| GET | `/api/transcript` | `?repo=&session=&limit=&before=` — one session's lines, read-only, paged from the end (#174) |
| GET | `/api/preflight` | `?key=&repo=` — the dispatch card's rows and verdict (#164) |
| POST | `/api/console` | `{repo, ticket?, resume?, new?}` — open a real console running Copilot in that checkout with a session id the fleet chose; the tile reads the session from Copilot's own file (#188, #189) |
| POST | `/api/say` | `{repo, message}` — type one line into the console the fleet opened for that checkout, through a helper that attaches by pid; refused for anything that is not a console (#190) |
| POST | `/api/focus` | `{repo}` — bring that checkout's console window to the front (#190) |
| GET | `/api/branches` | `?repo=&refresh=` — every local branch of one checkout, which never reached the default, the last twenty commits; read on the click, cached for the git interval (#184) |
| POST | `/api/dismiss` | `{id}` — stop offering that file until it is downloaded again |

`select` and `dismiss` change nothing on disk inside a repository. `attach` is the single exception
in "the fleet never writes in a repository", and it is a click, a copy, and one `inbox.attached`
event.

Every POST calls the same function the matching `ad-fleet` verb calls, and a refusal comes back
with the same words and the same hint the CLI would print — `409` with `{ok: false, error, hint}`.
The page is a view: it decides nothing and spawns nothing.

### The stream

Resume cursors are **per agent** (`luna:12,other:4`), not one number. Each agent's `seq` is dense
and its own, so a shared cursor would replay one stream and skip another.

A `polls` event names a checkout whose cells changed with no agent event to say so — the git cell
never has one (#184) — and the page re-reads `/api/fleet`, the snapshot it draws cells from.

A `tick` event goes out at least every 15 seconds. It is not decoration: a proxy that sees no bytes
for a minute closes the connection, and the tiles then stop updating with nothing anywhere saying
why. On any disconnect the page reloads `/api/fleet` and redraws from scratch rather than trusting
what it drew before, then reopens the stream.

## What is not here

Authentication beyond the loopback token, and access from another machine — both out of scope, and
both would change what this is. Cost and budget are a strip in #101. Notifications when a tile turns
red are #97. Jira intake in the side panel is #98.

Screenshots from PyCharm and Edge belong with #99 and #100, where the embedding is what is being
shown; this page is the same page in all three.
