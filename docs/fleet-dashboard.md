# The multi-viewer

One local page, one pane per agent, live. The epic is named for YouTube's multi-view and this is
that page: every agent a pane in one row at full height, the open one wide and every other one a
narrow rail beside it that says who it is and whether it needs you, any one of which is one click
from being the open one.

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

The page is **served compressed** (#195): the HTML, the stylesheet and the script go out gzipped to
any client that asks for it, cached per file so the work is done once rather than once per window,
and a client that cannot take it gets the same bytes uncompressed. About 200 kB on disk becomes
about 58 kB over the wire.

That is also what the payload budget measures now. It used to count bytes on disk, which made every
comment in the page cost against a number that exists to keep the page quick to open — and the page
is mostly prose, because the comments are where this project keeps its design record. The number an
operator waits on is what crosses the wire, so that is the number the test asserts (200 kB), with
the on-disk figure reported beside it so a file that doubles is still visible. On loopback the
saving is nothing and the CPU is real, which is why the API's JSON is *not* compressed: the desk
polls it four times a second, and nobody waits on that. The page is for the case where the server
is not loopback — a forwarded port, a phone on the LAN, a remote desktop.

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
| Header | drag handle, number, repo name, **state chip with its age**, ticket, pin, **hide, refresh, model**, maximise |
| Run line | which run this transcript belongs to: `run 3 · started 14:02 · resumed · session 7f3a · 41 events · live` |
| Session pill | which **session** this transcript is — `session · running · 6d` — and the one menu that changes which one it is: this session, the earlier ones with how each ended and what it cost, `+ new session`, the console, and the project's other checkouts (#206) |
| Why line | the one sentence from the fold — the unblock sentence, the refused tool, the question |
| Cells | the **project's** own state, polled read-only: ticket, PR, refresh, git — each with its age; the git cell counts the branches and opens the inspector's branches pane (#184). Beside them, **spend**: what this agent has cost, against its budget, with the model the last turn ran on (#211) |
| Approval card | appears when that agent is waiting; the **dry-run payload in full**, Approve / Deny |
| Transcript | assistant text, tool calls, denials, phase changes — the current run only |
| Earlier runs | folded under their session in the pill's menu — one *earlier*, not two adjacent ones (#206) |
| Outside strip | a session in this checkout the fleet did not start: what it is, how sure we are, and *adopt it* |
| Bottom row | reply box (→ `send`), Start (a ticket key in the same box), **Reset**, Stop. Over budget, *Send* re-arms as **Send anyway**: one more turn, on a second and deliberate press (#213) |

The **sidebar** sits beside the glass and holds five sections, one open at a time: the Jira **board**
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

The window dresses itself: `cmd.exe /k` names it after the checkout and its ticket, runs `ad-theme
apply` so it wears that project's palette the way any other terminal does, and then starts the
session. `fleet.console.palette: false` leaves the console in whatever colours the shell gave it.

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

At the top of the board is the **agent rail** (#183): one chip per registered checkout — name,
state and age, the chip the grid's dock used to draw — each a drop target. A ticket dragged over it lights the candidates
`board.suggest` names for that key and dims the rest; a drop calls exactly what a drop on the tile
calls, so a ticket handed to an agent that is a rail, not the open pane, gets the same pre-flight
card and the same refusals in the supervisor's words. The card is one element the page owns, drawn
in the pane when the pane is open (compact or full) and under the agent rail when it is a 48 px
rail with no room for it (#233) — it used to draw
inside a hidden tile, so the board window (`roles`, before #232) was the one place the hand-over
skipped its pre-flight. A ticket row takes the keyboard: `1`–`9` picks the
rail chip in that position, `Enter` the row's one candidate.

The **toolbar** is three labelled groups and one row: *widths* (the three presets, #234), *see*
(search, the sidebar, and a *settings* link) and *alerts* (chime, the bell). A group named *window*
chose between the arrangements, and went with them (#232); the presets stand where it was. Settings are a **page**, `/settings`, not a popover: the palette was never
the only one, and the model each agent runs and the flags the Copilot CLI is launched with have no
business behind a button on a bar that is about the agents. The link's `href` is built at runtime
because the run token lives in the query string and `_authorized` reads it from nowhere else — a
static `href="/settings"` is a 403 that reads exactly like a dead button.

The page has four blocks: **Appearance** (palette and skin), **Model per agent**, **Copilot** (the
launch and notification settings the server enumerates), and **What an agent may run** — the
resolved allow and deny lists, read-only, each pattern labelled with whether it shipped or was
configured. It is read-only on purpose: `fleet.allow_tools` *replaces* the default rather than
adding to it, so a list saved from a page would become the whole boundary, and an operator who
saved one would silently stop receiving any command a later version adds.

What the page is *wearing* is answered by the server: `GET /api/themes` returns the palettes, the
skins, and which of them is `current`, because a page that can only fill the pickers and not set
them opens reading *system · no skin* over whatever the config says — which it did, on every
window, until #195. The settings page carries its own EventSource for the `theme` frame alone, so a
palette set by `ad-theme` in a terminal, or on the desk in another window, repaints it instead of
leaving its pickers quietly lying. The footer keeps the two things that change — the counts and
the notice — and a `?` button (or the `?` key) opens the key map in four short columns. A cell that
fails to poll goes **grey with the error in a tooltip**, never wrong; a link with no fact behind it
is absent, never broken.

The desk follows the number of registered repositories: four repos, one open pane and three rails.
Click a rail (or press the number printed on it) and that agent is the open one, in its own slot,
while the one you were reading becomes a rail in its; `Esc` goes back to the one before. Panes that
change place **travel** there rather than jumping, so you can see that the one you were reading is
the same one, further along; only the paint moves, so the layout is in its final state throughout
and a click during the movement lands where you aimed it. `prefers-reduced-motion` turns it off.

### Reset, and why it is one button

`Reset` is `stop` and then `restart` — end whatever is holding the checkout, then resume *the same
session*, so the agent keeps the ticket it has read and the plan it has made. It exists because the
two commands were the answer and nobody could find the question: an agent stops answering in a
console window, and neither `ad-fleet stop` nor `ad-fleet start` is named after that. Both halves may
still refuse. A process that outlives the kill keeps its lock and nothing is started beside it — two
agents in one working tree is what the lock exists to prevent — and `fleet.max_restarts` refuses past
its limit, at which point the button reads *Reset anyway* and one more press spends the extra turn.
Never a silent force.

### Held tiles, and why there are none now

Focus mode showed the agents the fold says need a person. Answering one is exactly what stops it
needing you, so a reply used to hide the tile it was typed into: the action's only visible outcome
was that the thing you were working on vanished. A tile you had acted on was **held** — still on
screen, dimmed, saying which action held it — until you released it or left focus mode.

Focus mode is the *needs me* preset since #234: one write of this window's widths that makes every
agent needing a person wide and the rest rails. Nothing takes a width back when an agent stops
needing you, so the agent you just answered keeps its pane and there is nothing to hold.

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

### The row — every agent a pane (#233)

The one arrangement ([fleet-layouts.md](fleet-layouts.md)). It was one of four, chosen by `?layout=`,
until the operator retired the choice on 22 September 2026 (#232) — and with the same sentence
corrected the column that had been the default: *each agent is a column, not each agent is stacked in
one column — skinnier agents* ([plan-panes.md](plan-panes.md)). So every agent is a **pane** in one
row, at full height, in the arrangement's order. The wide ones share the width, each by its weight in
this window's **widths** (#234); every other one is a **rail**. Nothing scrolls sideways: a desk that
scrolls hides the agent that needs you.

A pane draws itself by how wide it is, in three tiers:

| Tier | Width | What it shows |
| --- | --- | --- |
| rail | 48 px | its number, the state's glyph in the state's colour, the name down its length, the unread count — and the whole rail red, with `!`, when the agent needs a person. Its age and last line are its accessible name and its tooltip |
| compact | 160 – 359 px | the head (name, state chip with its age, ticket, and the three tools: hide, refresh, which model), the approval and question cards, the last lines of the transcript, the reply box |
| full | 360 px and up | everything a tile has |

The tier is written as `data-tier` by one `ResizeObserver` on the row, with 8 px of slack between
compact and full so a pane on that boundary does not flicker (a pane is a 48 px rail or at least
160 px, so nothing sits on the rail's), and the numbers are starting values the laptop sets in #235.
Three panes beside each other on a laptop panel are compact; the same desk on a 2 560 px monitor is
three full ones.

**Resizing is the gutters (#234).** Between every two panes is a 1 px line with an 8 px hit area over
their edge: dragging it moves width between those two panes and nothing else, snapping to a rail
under 120 px, never under the compact minimum, and to the full minimum or an even share within 8 px.
The drag is the preview; one write when the hand comes up, `Esc` puts it back with nothing written, a
double click evens the pair, and the footer's *undo* (`u`) takes the last change back. Widths are the
window's own — `POST /api/window {widths}` — so two monitors hold different widths over the same agents
in the same order. A window that has never been given widths draws the open pane and every pin wide, at
the `size.cols` an older build left them. [desk-window.md](desk-window.md) has the whole of it.

Clicking a rail opens it: it takes the width the open pane had, in its own slot, and the pane that was
open becomes a rail in its own — nothing moves along the row. `Esc` goes back. **Shift**-click opens it
beside the open pane instead, the two splitting that pane's width. Which agent is open is the window's
own (`?w=`), so the left monitor can read one while the centre reads another, and `selected` — what the
inspector follows — stays the one thing every window agrees on. A rail has no head, so its three tools
are keys: `h`, `r` and `m` act on the rail the keyboard is on.

Three **presets** stand in the header where the arrangement picker was: *one* (`1`) — the pane the
keyboard is on wide and every other a rail; *all* (`=`) — an even share each; *needs me* (`f`) — every
agent that needs a person wide, the rest rails. Each is one write, and undoable.

When even the rails do not fit — about thirty agents on a 1 440 px window — a project's checkouts share
one rail, named for the project, red if any of them needs a person, and a press on it opens that one.
Only past that does the row scroll.

*needs me* narrows the row rather than emptying it: an agent that wants nothing is a rail, still named,
still counted and still one press away. It hides nothing, and with nobody needing you it changes
nothing and says so.

An address from before #232 — `?layout=`, `&view=` or `&screen=` from a bookmark or an older
launcher — opens the desk as any other does, and the footer says once that the parameter is
ignored.

### Where a tile went (#173)

Five `display:none` rules and one `.remove()` used to take a tile off the glass as a side effect of
a mode — zoom, focus mode, a solo window, the laptop's narrow view, and a repository leaving the
registry — and nothing anywhere said where it had gone. The operator's own answer was to reload the
page and hope.

#173 answered it with a dock of chips under the grid. The dock went with the grid (#232), the
column's foot that answered it next went with the column (#233), and the row answers it now:

* An agent you **hid** leaves the row, and the footer reads `N hidden`; a press on that empties
  `hidden`. A hidden agent keeps its slot, so it comes back where it was.
* An agent that **needs a person** is a red rail whatever the arrangement says — hiding a demand is
  how a demand gets missed.
* A repository that has **left the registry** is a dashed rail after the row, whose label offers the
  `ad-fleet repo add <path>` that would bring it back, rather than the pane simply being gone.
* A project's checkouts are hidden and pinned as one. Each is its own pane — one agent, one working
  tree — until the rails do not fit, when they share one rail.

`#tile=<repo>` — the anchor the Windows toasts and both IDE shells use — **reopens** a hidden tile
rather than quietly doing nothing, and the footer says it did. An anchor naming a repository with no
tile now says *no tile for 'x' — is it still registered?*; it used to do nothing at all, which read
as the dashboard having hung. An anchor a page was opened with is answered once the desk has loaded,
and only if nothing on the page has moved it meanwhile: opening an agent writes `#tile=` itself, and
following the page's own mark reopened that agent and shut the sidebar (#234).

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

The page has one arrangement, the row above, and each window's widths over it. `ad-fleet serve` still accepts
`--layout` for one release and ignores it, with a `note` saying so; how the four arrangements of
#133 and #200 came down to one is in [fleet-layouts.md](fleet-layouts.md).

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
| `2`–`9` | open that one — the number printed on the pane, counting the panes **on the glass** (`1` is the *one* preset, #234) |
| `←` / `→`, `j` / `k` | walk the row: the open pane, then each rail; `Enter` on a rail opens it, `Shift`+`Enter` opens it beside |
| `1` | *one*: the pane the keyboard is on wide, every other a rail |
| `=` | *all*: every pane on the glass an even share |
| `u` | take the last change of widths back |
| `r` | re-read the agent the keyboard is on — a rail as well — now; spends no premium request |
| `m` | which model that agent runs, and which one its last turn actually ran on |
| `f` | *needs me*: every agent that needs a person wide, the rest rails; nothing hidden |
| `h` | hide the agent the keyboard is on; the footer counts it |
| `Alt`+`[` / `Alt`+`]` | walk the tile's session menu, opening it on the first press |
| `Alt`+`N` | a clean session in this checkout, beside the one it is on |
| `/` | the search box — `where` over the catalogue |
| `i` | the sidebar's inbox |
| `a` | approve the open agent's pending write |
| `b` | the sidebar's Jira board |
| `n` | the sidebar's alerts |
| `Alt`+`←` / `Alt`+`→` | move the focused pane one slot |
| `Alt`+`Shift`+`←` / `Alt`+`Shift`+`→` | the gutter on the focused pane's right, one step (#234) |
| `Alt`+`Home` | pin the focused pane first |
| `Alt`+`Enter` | the focused pane and the one on its right, evened — the gutter's double click |
| `Esc` | put down a drag with nothing written; close a popover or the sidebar, or go back to the agent that was open before (or out of a text box) — the nearest open thing first |

The number on a pane is the key that opens it, and it follows the arrangement: move a pane and its
number moves with it, and an agent that is off the glass (hidden, or folded into its project's rail)
has no number at all — a digit that zoomed a tile a mode was already hiding once left a blank window,
because the grid's zoom hid every other tile.
Every drag gesture has a keyboard equivalent, because a desk that can only be arranged with a mouse
cannot be arranged by someone who is typing.

Deny has no shortcut on purpose: it needs a reason typed, and a one-key refusal with an empty
reason is the failure mode the gate was built to avoid.

## Motion, and the rest of how it behaves

The desk's behaviour has seven pages of its own, because it is a page with a contract rather than a
screen with some CSS on it:

| Page | Is |
| --- | --- |
| [desk-components.md](desk-components.md) | every component, who draws it, and the seven rules each one keeps — created once and patched forever, one owner per property, listeners bound once, lists reconciled by key |
| [desk-motion.md](desk-motion.md) | three duration tokens and a 320 ms ceiling a test enforces; `.enters` as the one arrival pattern; `transitionLayout` as the one door for a layout change |
| [desk-window.md](desk-window.md) | the tile as a window: pointer drag, the gutters and their snaps, a window's widths, the presets, minimise and maximise |
| [desk-rendering.md](desk-rendering.md) | what a canvas on this page may do; the activity trace; the glass ground that drifts |
| [desk-instant.md](desk-instant.md) | paint, post, reconcile; the optimistic arrangement and its way back; the 50 ms budget per gesture; why there is no spinner |
| [desk-engines.md](desk-engines.md) | what each engine does with each platform feature, and what happens on the ones that have not got it |
| [desk-ink.md](desk-ink.md) | the ink layer (#248): `window.Ink`, a mark table per skin, lanes, the tools, the gate the WebGL probe sets, `?ink=on` for tests, and the plain fallback. No skin uses it yet |

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
| GET | `/` | the desk. Its `<body>` carries `data-ink-shell`, `data-ink-probe` and `data-ink-skins` (the skins that ship an ink module): the window's shell (`shell=`, else `w=`, else `browser`) and the class its `/probe` record has, or `unmeasured` — the ink layer's gate ([desk-ink.md](desk-ink.md)). `?ink=on` forces the layer on for tests; `?ink=off` forces the plain fallback |
| GET | `/settings` | the settings page: appearance, the model per agent, the Copilot launch settings |
| GET | `/probe` | the WebGL probe (#247): three seconds of three.js strokes in whatever shell opened it, posted once to `/api/probe` ([desk-engines.md](desk-engines.md) §WebGL, probed in each shell). The desk loads three.js too, but only through the ink layer, only when this gate says on, and only once a skin draws |
| GET | `/static/…` | the pages' assets: `app.css`, `common.js`, `app.js`, `settings.js`, `probe.js`, the ink layer's `ink/ink.js` (and, imported by it with the token, `ink/layer.js`, `ink/shapes.js`, `ink/pen.js` and the chosen skin's `ink/skins/<name>.js`), and the vendored `vendor/three/three.module.min.js` (r160, MIT) |
| POST | `/api/probe` | `{shell, ua, webgl, renderer, vendor, caveat, three, intervals, first_stroke_ms, load_ms, drawn, error}` — facts only; one record per shell in `~/.agentdata/fleet/probes.json`, answered with the class and the WebGL cell `probe.classify` gives it. `409 probe_shell` / `probe_shape` for a record it cannot read. A probe that did not finish (`incomplete`) is kept as the shell's latest attempt and answered `kept: true` when a finished record stands |
| POST | `/api/window` | `{w, …}` — one window's own record. `{w, widths, version}` sets its widths (#234): repository → weight, `0` a rail; `version` is the desk version the page last heard, and a write older than the widths the record holds is refused `409 widths_stale`. Anything but repository → a number of nought or more is `409 widths_shape` |
| POST | `/api/measure` | `{w}` asks that desk window to go to `/probe` (`ad-fleet probe --open pycharm`). The ask is held in memory for ten minutes and shows in the desk frame's `measure`. `{w, take: true}` is the window claiming it, answered `go: true` once |
| GET | `/api/fleet` | every repo's state, its model and the one its last turn ran on, the recent events, and the pending approvals |
| POST | `/api/act` `refresh` | re-read one checkout now: re-fold its stream, poll its four cells, answer the fresh row. Spends no premium request; refuses `refresh_busy` inside two seconds (#205) |
| GET | `/api/events` | SSE; `?since=luna:12,other:4` resumes per agent |
| GET | `/api/themes` | the `.icls` palettes, the skins, and `current` — which palette and skin the desk is wearing now (#195) |
| GET | `/api/settings` | the editable keys with their type, default and effect-scope; what each is set to; the model per repository; the resolved tool lists |
| POST | `/api/settings` | write an enumerated key, a per-repo model, or the fleet-wide default |
| POST | `/api/theme` | set the palette or the skin |
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
| POST | `/api/select` | `{repo}` — the project every window agrees on ([fleet-layouts.md](fleet-layouts.md)) |
| POST | `/api/arrange` | `{order?, size?, pinned?, hidden?}` — the desk's one arrangement, shared by every window (#173, #232). `size` is read and kept for desk files an older build wrote, and no page sends it since the widths (#234) |
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
both would change what this is. Notifications when a tile turns red are #97. Jira intake in the side
panel is #98.

Cost and budget **are** here now (#201): a cell on every full pane, a number in every rail's label, the fleet's
own total in the footer, and a breakdown in the inspector. What is deliberately *not* here is any
new stop — the per-agent cap is exactly where it was and means what it meant. The caps that were
considered and deferred, each with the one measurement it needs first, are in
[plan-meter.md](plan-meter.md) §Caps, later.

Screenshots from PyCharm and Edge belong with #99 and #100, where the embedding is what is being
shown; this page is the same page in all three.
