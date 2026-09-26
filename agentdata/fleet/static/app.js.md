# `app.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The multi-viewer's client. No framework and no build step on purpose: this file has to load
inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
fetched from the internet simply does not arrive.

The page is a view. It never decides anything -- every state comes from /api/fleet and every
button POSTs to the same function the CLI verb calls.

`PARAMS`, `TOKEN`, `q`, `post`, `text`, `applyTheme` and `applySkin` come from common.js, which
every page loads before its own script.

## the records, typed (#236)

What the desk moves, written down once where a checker can read it. `tsc` reads these comments
against the code (`tsconfig.json`, docs/desk-types.md) and nothing compiles them, so the page is
still exactly this file. Typed where plan-panes §G asked: the one door and the window's writes
(#230), the row and its panes (#233), the widths and the gutters (#234).

### `@typedef DeskRecord`

```js
/** The desk every window on this server agrees on: `desk_state()` in serve.py. It reaches the page
 *  four ways -- the stream's `desk` frame, `/api/fleet`, `/api/desk` and a window write's own answer
 *  -- and all four come in through `acceptDesk`. Optional throughout, because the page also holds
 *  desks that are not the server's: the one it starts with, and the snapshot it draws while the
 *  first answer loads (#219), whose version is taken off so that answer wins.
 * @typedef {Object} DeskRecord
 * @property {number} [schema]            2 since #232
 * @property {string} [selected]          the project every window's inspector follows (#133)
 * @property {number} [version]           only ever rises; anything lower is dropped at the door
 * @property {string} [at]                when it last changed, UTC
 * @property {Arrangement} [arrangement]  one for the whole desk (#232)
 * @property {Object<string, WindowRecord>} [windows]  each window's own record, by its `?w=`
 * @property {Object<string, number>} [measure]  `ad-fleet probe` asking a window to measure (#247)
 */
```

### `@typedef Arrangement`

```js
/** The one arrangement (#232): the same agents in the same order on every screen. `size` is #217's
 *  footprint as an older build wrote it -- a bare number in an older file still -- read as the
 *  starting widths of a window that has none of its own, and never written (#234).
 * @typedef {Object} Arrangement
 * @property {string[]} [order]
 * @property {Object<string, {cols: number, rows: number} | number>} [size]
 * @property {string[]} [pinned]
 * @property {string[]} [hidden]
 */
```

### `@typedef WindowRecord`

```js
/** One window's own record: `WINDOW_FIELDS` in serve.py (#172). `focus` and `held` are an older
 *  page's -- the needs-only filter the *needs me* preset replaced (#234) -- which the server keeps
 *  for it; this page neither reads nor writes them.
 * @typedef {Object} WindowRecord
 * @property {string} [open]              the one pane the keys and the composer address (#230)
 * @property {boolean} [focus]
 * @property {Object<string, number>} [read]  the last event read, by repository
 * @property {string} [seen]              when this window last looked; the away strip reads it
 * @property {string[]} [held]
 * @property {string} [section]           the sidebar's open section (#148)
 * @property {Widths} [widths]
 * @property {number} [widths_at]         the desk version the widths were written at: a write of
 *                                        widths heard before it is refused (`widths_stale`)
 */
```

### `@typedef Widths`

```js
/** A window's widths (#234): each pane's weight, by repository. 0 is a 48px rail, and a positive
 *  number that pane's share of what the rails leave.
 * @typedef {Object<string, number>} Widths
 */
```

### `@typedef WindowWrite`

```js
/** What this page writes to its own record -- not the whole record. A field one arrangement wrote
 *  and another read was the snap-back (plan-panes ground rule 2), so writing `zoomed`, or the
 *  retired `focus`, is a type error here before it is a bug on the glass.
 * @typedef {Object} WindowWrite
 * @property {string} [open]
 * @property {Widths} [widths]
 * @property {Object<string, number>} [read]
 * @property {string} [seen]
 * @property {string} [section]
 */
```

### `@typedef DeskAnswer`

```js
/** A desk as it arrives: the record, and on an action's answer the envelope every POST carries,
 *  which `acceptDesk` takes off. A refusal is the envelope alone, with the server's words (#163).
 * @typedef {DeskRecord & {ok?: boolean, action?: string, error?: string, hint?: string,
 *                         code?: string}} DeskAnswer
 */
```

### `@typedef Row`

```js
/** One agent's row, as `/api/fleet` sends it. Typed in the fields the typed part reads -- `project` is
 *  the project the checkout is one of (#175), `why` what it asks when it needs a person, `recent`
 *  the last events of its run -- and open for the rest, which the rest of the page reads as it
 *  always has. Open means a field this list does not name reads as `any`, not as an error: closing
 *  it is the widening's to do, not this slice's.
 * @typedef {{
 *   repo?: string, project?: string, path?: string, state?: string, needs_human?: boolean,
 *   why?: string, last_said?: string, last_event_age_s?: number,
 *   spend?: {total?: number, [field: string]: any}, recent?: Array<{seq: number}>,
 *   as_of?: {run: string, n: number},
 *   [field: string]: any
 * }} Row
 */
```

### `@typedef Tier`

```js
/** Which of the three widths a pane is drawing (plan-panes §The pane). `setTier` alone writes it.
 * @typedef {"rail" | "compact" | "full"} Tier
 */
```

### `@typedef Tiers`

```js
/** The widths the tiers change at, in CSS pixels (#235): `fleet.tiers.*` as `settings.tiers()` reads
 *  them, on the theme payload. CI's numbers when the file sets none -- or sets four that do not go
 *  together, when `invalid` says why.
 * @typedef {Object} Tiers
 * @property {number} rail                the rail's width
 * @property {number} compact             compact from
 * @property {number} full                full from
 * @property {number} slack               how far past compact/full a pane goes before it changes
 * @property {string} invalid             why the file's four were not drawn, or ""
 */
```

### `@typedef Pane`

```js
/** A pane: one agent in the row, and its entry in `tiles` (#233). `el` is its `.tile`, made once by
 *  `makeTile` and patched after (#215), carrying `data-repo` and `data-tier`; `seq` is the last event
 *  drawn into its transcript, and `row` what it was last drawn from. `restored` marks a pane drawn
 *  from the window's snapshot, whose transcript its first real row brings (#347).
 * @typedef {Object} Pane
 * @property {HTMLElement} el
 * @property {number} seq
 * @property {Row} [row]
 * @property {boolean} [restored]
 */
```

### `var pendingRefresh`

Beside `var tiles = new Map();`:

repo name -> {el, seq}

### `var RETIRED_PARAMS`

Beside `var arrivedSinceLastPlace = false;`:

a pane was made since the order was last put right (#233)

Above `var RETIRED_PARAMS = ["layout", "view", "screen"];`:

#232: one arrangement. The page used to be four, chosen by `?layout=` -- `column`, `grid`,
`roles` and `screens` -- and all four wrote one window record, which is how a `zoomed` the grid
left behind came to snap the column back to it (#230). The operator retired the choice
(`docs/fleet-layouts.md` §The decision): one row of panes, one per agent (#233). An address
from a bookmark or an older launcher still carries the parameters; the desk opens anyway,
says once in the footer that they are ignored, and takes them off the address so a reload
does not say it again.

### `var BOOT_HASH`

Above `var BOOT_HASH = location.hash || "";`:

The anchor this page was OPENED with -- a toast's `#tile=luna` -- read before anything on it can
write one of its own: opening an agent marks the address with `replaceState`, which is the same
string the page would otherwise take for a toast's (#234).

### `var desk`

Above `var desk = { projects: {}, offers: {}, unsorted: [], not_offered: [], folders: [],`:

```js
/** Everything the last `/api/desk` said, and in `desk.desk` the record every window agrees on.
 *  @type {{desk: DeskRecord, [answer: string]: any}} */
```

### `var openTile`

Above `var openTile = "";`:

Which agent this window has OPEN (#203) -- the pane in the row that has the width (#233) -- and
the one it had before: `Esc` goes back to that rather than to nothing, because "show me the
other one for a second" is the gesture the swap is for. Per window: the left monitor reads one
agent while the centre reads another, and `selected` stays the one thing every window agrees
on.

### `var myWidths`

Above `var myWidths = null;`:

This window's widths (#234): each pane's weight, 0 a rail and a positive number its share of
what the rails leave -- or null while the window has never been given any, when the open pane and
the pins share the row as they did before the gutters. Per window, like `openTile`, because two
monitors can hold different widths over the same agents in the same order.

### `var PREFLIGHT`

Above `var PREFLIGHT = true;`:

Whether a drop opens the dispatch card (#164) or launches the way #98 did. The server's
`fleet.preflight` decides; until the first `/api/fleet` answers, the card is the default,
because showing a card and starting from it is the recoverable direction to be wrong in.

### `var windowWrites`

Above `var windowWrites = 0;`:

This window's own record -- which agent is open, what it has read. Posted and not waited on:
the page has already drawn the change, and a window record that failed to save is a preference
lost, not a wrong screen. A refusal is still said out loud (#219) rather than swallowed.

One at a time, and in the order they were made (#230). Four clicks inside a frame were four posts
in flight at once, and the server applied them in whatever order its threads took the lock: the
page asked for alpha last and the record ended on delta. Until the last of them is answered,
anything else the server sends describes the window as it was, and applying it put back the
agent the operator had just clicked away from -- so `acceptDesk` leaves the window alone while
`windowWrites` is above nought. Each answer is the desk as of its own write, and comes in through
the one door like everything else.

### `function saveWindow`

Above `function saveWindow(patch) {`:

```js
/** @param {WindowWrite} patch
 *  @returns {Promise<DeskAnswer | null | void>} the server's answer, or null when the post failed */
```

Above `if (body.widths !== undefined && desk.desk && desk.desk.version !== undefined) {`:

Widths carry the version this page last heard (#234), read as the post goes rather than when
the gesture was made: by then the answer to this page's previous write has come in through
the door, so the server refuses only another page's widths under the same `?w=`, never this
page's own.

### `function acceptDesk`

Above `function acceptDesk(payload) {`:

The one door every desk payload comes in through (#230): the stream's `desk` frame, the
`/api/fleet` answer, the fifteen-second `/api/desk` and a window write's own answer. Three of those
used to assign `desk.desk` outright, so an answer computed before a click could land after the
frame that carried it and roll the page back -- `version` from 5 to 3, and the agent the operator
had just left open again. The version only ever rises, so an older payload is simply dropped;
an equal one is the same desk.

```js
/** @param {DeskAnswer} payload
 *  @returns {boolean} whether it was taken */
```

Above `if (arrangeWrites && desk.desk && desk.desk.arrangement) next.arrangement = desk.desk.ar …`:

An arrangement write still in flight: the page's own arrangement is newer than this one.

### `function rehome`

Above `var more = new URLSearchParams();`:

`/open` forwards every param but `t`, so the host's shell and ink ride along from here once.

### `onAuthLost = function () { if (streamDead) rehome(); };`

Above `onAuthLost = function () { if (streamDead) rehome(); };`:

There used to be a `held` map here: the agents the operator had acted on, kept on the glass by
focus mode after they stopped needing anybody, because a reply otherwise dimmed the very pane it
was typed into. *needs me* is a preset now (#234) -- one write of widths, which nothing takes back
when an agent stops needing you -- so there is no filter left for a pane to fall out of, and
nothing to hold it in.

The desk's answer to a 403 (common.js calls this): collect a fresh run token through `/open`,
but only once the stream has already died -- a single refused POST against a live stream is not
a restarted server, and rehoming on one would throw away whatever was being typed.

### `function agentAge`

Above `function agentAge(seconds) { return ageChip(seconds).text; }`:

How old an agent's last event is, said one way everywhere it is said (#204).

`age()` below stops at hours, so the same agent read `6d` in its chip and `160h` in its tab --
two numbers for one fact, on one tile, three centimetres apart. `age()` still dates DURATIONS
(how long an approval has waited, how old a poll is); `agentAge` dates the agent, and the chip,
the rail's label, the strip and the agent rail all read the same formatter.

### `function ageChip`

Above `function ageChip(seconds) {`:

The age that rides inside the state chip. "done" is not information; "done · 2d" is -- and the
bucket labels this replaced ("today", "> 2d") could not tell a run that ended a minute ago from
one that ended at breakfast. Anything past a day is marked stale as well as dated, because a
colour alone is not a signal on a bad monitor at arm's length.

## drawing one tile

### `function line`

Above `case "project.ticket_changed": return (d.key || "") + " is " + (d.status || "") +`:

#131 and #132 put the *project's* changes on the same stream as the agent's, so the
transcript is one narrative rather than two panes the operator has to interleave.

Above `case "subagent_started": return "sub-agent " + (d.name || d.agent || "") + " started";`:

#402: from the Copilot SDK docs, not yet measured from the CLI.

### `function appendTo`

Above `function appendTo(list, ev) {`:

One renderer for both lists. The read-only pane draws the same lines from the same fold as the
live tile, because a session that looked different when you came back to it would read as a
different session (#174).

Beside `text(v, body);`:

textContent, never markup: this is agent output

### `function makeTile`

Above `function makeTile(row, index) {`:

```js
/** @param {Row} row  @param {number} index  @returns {HTMLElement} */
```

Above `el.addEventListener("click", (function (e) {`:

Clicking anywhere on a tile *selects* the project for every window on this server (#133 layout
B), which is what makes the left monitor drive the centre one. Blowing a tile up is still the
repo name or a double click: one gesture per meaning.

Above `if (e.target.closest("button, input, select, textarea, a, details, summary")) return;`:

Clicking a tile selects the project for every window on this server -- which is what makes
the left monitor drive the centre one. Pressing Send, or clicking into the reply box, is not
that gesture: it re-pointed three other screens as a side effect of typing.

Above `var head = el.querySelector(".head");`:

Drag to reorder, from the header only. A tile that is draggable edge to edge cannot have its
transcript text selected -- every attempt to copy an error message starts a drag instead --
and it offers no affordance for the gesture. The header carries `draggable` and the grip
says so (HIG *Drag and drop*). Tickets dropped from the board still land on the whole tile.
#217: pointer events, not HTML5 drag. The old gesture could not show the tile moving -- the
browser drew its own translucent copy and the tile stayed where it was -- and on a touchpad
it needed a press-and-hold nobody discovers. `setPointerCapture` keeps every move coming to
this handle even when the pointer has left it, which is what makes the tile stay under the
cursor instead of being dropped the moment it overtakes the hand.

Tickets from the board and files from the desktop still arrive by HTML5 drag; they are drops
*onto* a tile, which is a different gesture with a different source.

Above `var face = el.querySelector(".pane-rail");`:

#233: the rail's face. A press swaps it with the pane that was open -- the column's gesture,
kept because it is the one the operator already has -- and a drag moves it along the row, by
the same binder the head uses. The face is one button, so it IS the handle (#217's rule), and
the click a real drag ends in is swallowed there.

Above `face.addEventListener("click", function (e) {`:

#234: Shift opens it BESIDE the pane that has the keys, splitting that pane's width -- which is
how two are open without a drag. `Shift+Enter` is the same press from the keyboard; it is taken
on the key, because whether the click a button synthesises for `Enter` carries the Shift is the
engine's business.

Above `bindGutter(el.querySelector(".gutter"), el);`:

#234: this pane's right-hand gutter -- the line between it and the next pane on the glass.

Above `el.classList.remove("drop-target", "drop-before", "drop-after");`:

Reorder is the pointer drag's (#217); what arrives here is a ticket or a file.

Above `if ((e.dataTransfer.files && e.dataTransfer.files.length) ||`:

Files first (#166): the tile has promised a copy on `dragover` since #98, and until now that
promise was empty -- the outline appeared and nothing happened.

Above `el.querySelector(".asks-send").addEventListener("click", function () {`:

The dispatch card's own three controls (#164). `Enter` in the brief box starts; `Esc` cancels,
the way `Esc` leaves every other thing on this page.
One Send for every answer typed (#165): N answers cost one turn, not N.

Above `var done = (r && r.ok !== false && r.answered) || [];`:

#249: a question the server says it passed on is answered, and says so until the agent
records it and the fold drops it -- the one signal the paper skins strike the question
by. The ids come back from the server, never from what was typed.

Above `bindTools(el, row.repo);`:

hide, refresh and the model -- the three the band had, on the head, from the one binder (#205).
A rail has no head to put them on; `h`, `r` and `m` reach it from the keyboard instead.

Above `el.querySelector(".spill").addEventListener("click", function () { toggleMenu(el, row.re …`:

#206: one control. The pill says which session this transcript is; the menu behind it holds
everything that changes which session that is. The rows are fetched on the open rather than on
every poll -- nobody is reading them until they ask for them.

Above `["freshtoggle", "fresh-strip"].forEach(function (cls) {`:

#489: the head's and the adopt strip's *start fresh*: the same action as the menu item's.

Above `el.addEventListener("keydown", function (e) {`:

Every drag gesture has a keyboard equivalent, and the footer key map lists them all.

Above `if (e.shiftKey) {`:

#217: shifted, because Alt+arrows has moved a tile since #5 and a learned gesture is not
something to take away for a new one. Since the gutters (#234) the shifted pair moves this
pane's right-hand gutter, as a drag of it would; up and down went with `rows`, because a pane
is always the row's full height.

Above `else if (e.key === "Enter") { evenGutter(el); e.preventDefault(); }`:

The double-click on this pane's right-hand gutter: the two beside it, evened out (#234).

Above `else if (e.key === "[") { stepMenu(el, row.repo, -1); e.preventDefault(); }`:

The strip, without a mouse. `[` and `]` walk it; `N` starts this pane fresh (#489), from a
rail as from a pane.

Above `var maxBtn = el.querySelector(".maxtoggle");`:

#217: maximise. Minimise is the hide button, which is the same gesture under the name
everybody already knows; this is the other half of the pair, and it is `openAgent` -- which
the desk has always had and only ever offered as a double click or the repository name.

Above `var forcing = sendBtn.dataset.force === "1";`:

A console is typed into, not sent to: `send` would be a second agent in one working tree.

Above `if (r && r.code === "budget_exceeded" && !forcing) {`:

The budget refusal reaches the operator at last (#213). It was enforced in `send` and
the desk called `send` with no `force` at all, so an over-budget agent was simply
unreachable from the page and `ad-fleet send --force` in a terminal was the only door.
A second, deliberate press spends one more turn -- the pattern Reset already had.

Above `var startBtn = el.querySelector(".start");`:

#509: with the box empty, Start is *Start fresh* -- #489's `startFresh`, arming this button on
`chat_open` -- so leaving yesterday's session is one visible press on every full pane. With text
in the box it is today's Start {ticket}; text that is not a key is the server's to refuse.

Above `var resetBtn = el.querySelector(".reset");`:

Reset is stop-then-resume, which is what the operator was previously expected to spell as two
commands in a terminal they had to go and find. `restart` is bounded by `fleet.max_restarts`
and refuses past it -- correctly, since an agent that has died twice the same way will die a
third time -- so the refusal is shown and the button becomes the second, deliberate press that
spends the extra turn. Two clicks, never a silent `force`.

### `function action`

Above `if (r.row) { patchRow(r.row); place(); }`:

The row came back with the answer (#219). A `send` used to cost two round trips -- the act,
then a whole `/api/fleet` to find out what it did -- and the second one carried every tile
on the desk so that one of them could be redrawn. An action that did not name a row (or an
older server that does not send one) still falls back to the snapshot.

## the question card (#165)

The agent's open questions, as records: choices as buttons, a box for anything else, one Send.
Answering used to be a free-text reply the agent had no way to tie to what it asked, and which
did not unblock it -- `open_questions` persisted until `--clear-questions`, which no skill ran on
resume, so the next bootstrap stopped on the same block.

### `function drawAsks`

Above `var signature = open.map(function (q) { return q.id + ":" + q.q; }).join("|");`:

Redraw only when the set changed: the operator may be mid-sentence in one of these boxes,
and a refresh every few seconds that threw the typing away would make the card unusable.

### `function drawScopeReport`

Above `function drawScopeReport(el, row) {`:

What it edited against what it was given (#168). Advice to the model and a report to the human:
nothing here refused an edit, and an agent that went outside the scope was probably right to --
the operator simply wants to know.

### `function paintAccent`

Above `function paintAccent(el, accent) {`:

The project's accent, on the tile's LEFT edge -- which project, never what state (#150).
One owner (#215): `drawTile` painted `borderLeftColor` and the `theme` SSE handler painted
the TOP one, an edge no rule gives a width to. So a palette changed in a terminal or on the
settings page painted an invisible stripe and left the visible one stale until the next
`/api/fleet`. Both call this now.

## #218: the shape of the hour, drawn

### `var TRACE_H`

Above `var TRACE_H = 18;`:

The last hour, oldest on the left: one point a minute, its height the share of the busiest
minute, and a tick through every minute that stopped for a person -- because "it asked me
something" is not a quantity.

Nothing is drawn that the row does not carry and nothing is drawn that the sentence does not
say: the `aria-label` is the same hour in words, which is what makes this assertable and what
makes it reach somebody who cannot see it.

#257: there is no canvas. The trace is data on the page, written once here and read twice. The
element carries the series (`data-ink-series`, heights 0-1, and `data-ink-ticks`, the minutes
that needed somebody), which is what the ink layer draws in the pane's lane when this shell
draws ink (docs/desk-ink.md §The page's own drawing). And its own SVG -- a polyline and a path of
ticks, coloured by the stylesheet -- is the plain look every other shell shows, so a palette that
changes repaints it with no script at all. Every write goes through `attr`, so a row that did not
change writes nothing.

### `function traceHeights`

Beside `var TRACE_H = 18;`:

the viewBox's height: the trace's own CSS height, in px

Above `out.push(n > 0 ? Math.max(1 / (TRACE_H - 2), Math.min(1, n / peak)) : 0);`:

A minute with something in it is never flat: a pixel above the floor is "it was awake".

### `function drawTrace`

Above `text(el.querySelector("title"), says);`:

```text
An SVG's tooltip is its <title> child, not a `title` attribute as the canvas's was.
```

Above `setData(el, "trace", (tr.peak || 1) + "|" + (tr.n || []).map(function (n, j) {`:

The same hour as counts, for a skin that plots it on its own paper (#253, the graph paper): the
peak, then a minute's count each, `!` on a minute that stopped for a person.

Above `var line = el.querySelector(".tr-line");`:

The plain look: the same numbers, in the SVG's own units (a minute wide, a pixel tall).

### `var TILE_OWNED`

Above `var TILE_OWNED = /^(tile|state-[A-Za-z_]+)$/;`:

#218's ground -- the glass skin's three blobs, drifting a pixel a second -- is the ink layer's now
(#257): it reads the stylesheet's gradients and draws them in its `ground` slot where this shell
draws ink, and every other shell shows the stylesheet's own gradients, still. Nothing here draws
it, and nothing here needs to know which skin has one.

The two classes `drawTile` owns on a tile, and nothing else (#215, found by #220's demo).

It used to rebuild the whole `class` attribute from `tile state-…`, which dropped every class
somebody else owns -- `is-selected`, `is-hidden`, `is-pinned`, `size-2`, `needs-human` -- and
`place()` put them straight back on the next line. Two writers, two writes, twenty times a
redraw, and `draw(el, row)` twice with the same row was never the no-op the contract claims.
The classes this function does not own are kept by construction rather than by being
remembered.

### `function setOwned`

Above `function setOwned(el, owned, wanted) {`:

Rebuild the classes one draw function owns, keeping every class it does not.

What made it a rule rather than a habit: the column's band (#203, retired by #233) owned three
classes and rewrote the attribute that also holds `is-dragging`, and `place()` runs about two
and a half times a second. A draw landing in the middle of a drag took `is-dragging` off the
band -- with it the `pointer-events: none` that makes `elementFromPoint` answer with what is
*underneath* the thing being dragged -- so the gesture carried on finding only itself and no
drop target ever lit. On a fast machine the drag finishes between two draws and it never
happens.

### `function shownState`

Above `function shownState(row) {`:

The state a pane shows, which is not always the fold's. The server decides which agents are
quiet enough to be called unsupervised (it is the only side that knows whether a process holds
the checkout), and it sends the sentence ONLY for those -- so a pane that says "needs you" never
also says "nothing is supervised". One function, because the chip and the rail both say it.

### `function paneShows`

Above `function paneShows(el) {`:

#233: what this pane's width lets it show. A tier not written yet reads as a rail, because that
is what every pane is until `place()` opens it: a pane is made 48px wide, and the observer's
first report -- before anything is painted -- writes its real tier and draws it again at that
width. A pane that is never laid out (hidden from the start) is never reported, and draws the
rest of itself the frame it is shown.

```js
/** @param {HTMLElement} el  @returns {{wide: boolean, full: boolean}} */
```

### `function drawTile`

Above `var isSupervised = row.supervised !== false;`:

Three things have to agree here or the tile lies: the chip, the sentence under it, and the
age -- `shownState` is where the first two are decided.

Above `var shows = paneShows(el);`:

The draw skips what this tier does not show (plan-panes §The pane): a rail paints no trace,
no cells and no session menu, and a compact pane none of the three either. What every tier
needs is drawn whatever the width -- above all `needs-human`, which `isHidden` reads to keep a
demand on the glass. A change of tier draws the pane again, so what was skipped arrives.

Above `toggle(el, "needs-human", !!row.needs_human);`:

`needs-human` is the class *needs me* widens by (#234) and `isHidden` keeps on the glass, and it
comes from #94's fold rather than from anything this page works out for itself: the chip, the
toast and the preset must agree.

Above `toggle(el, "is-done", row.state === "done");`:

Finished, in the fold's own word (#253). The chip cannot say it: the fold calls an agent done
only once nothing supervises it, and `shownState` draws every quiet unsupervised agent as
idle. So a paper skin's green check has this to key on, and it is the fold's, not the page's.

Above `tabbable(el, shows.wide ? 0 : -1);`:

A rail's one stop for the keyboard is its face; the pane around it is not a second one.

Above `var modelBtn = el.querySelector(".modeltoggle .bm-name");`:

Every state carries its own age, in the chip, because a verdict with no date is the bug.

Above `var runs = chipModel(row);`:

#492: what the next turn runs, marked `next` until a turn launches with it; never the last
reply's model over a switch the operator has just made.

Above `text(chip.querySelector(".chipword"), displayState.replace(/_/g, " "));`:

Two spans from the template, written rather than rebuilt: the chip was torn down and cloned
again on every draw, several times a second while an agent talks.

Above `var outside = el.querySelector(".outside");`:

A session in this checkout that the fleet did not start (#2). Two states, never both: one it
could take on, and one it already has. The `how` is shown rather than hidden because "we found
the process and it is in that folder" and "that folder is being written to and a Copilot is
running somewhere" are different claims, and the operator should be told which they have.

Above `text(adoptBtn, "stop following it");`:

#489 (SESS-D1): *start fresh* first; following it no more is the quieter second button.

Above `setData(el, "console", row.console ? String(row.console.pid || 0) : "");`:

An adopted session has no pipe to its stdin, so the controls that would write to it say so
rather than being offered and silently doing nothing.
A console the fleet opened holds the tile: the reply box types into it and the tab raises it.

Above `if (cls === "send") attr(btn, "title", row.external ? EXTERNAL_TITLE : "");`:

Start's label and title are `drawStart`'s (#509), written once per draw, not twice.

Above `["stop", "reset"].forEach(function (cls) {`:

Stop and Reset on the operator's own chat (#487, #489): the server refuses both, so the page
does not offer them. A console the fleet opened is not `external`, and keeps its buttons.

Above `var run = row.run || {};`:

Which run this transcript belongs to. Without it, a two-day-old run reads as live.

Above `setData(el, "session", run.session || "");`:

Which session the live tile is on, so the switcher can leave it out of *earlier* rather than
offering the operator the one they are already looking at (#174).

Above `if (!run.n) bits = ["no run yet"];`:

The era, last, because it is the qualifier: which run, then whether it is still this one.

Above `if (shows.wide) {`:

The two cards that ask the operator something are on a compact pane as well as a full one:
answering from a narrow pane is the point of it. A rail carries neither -- it is red, and the
press that widens it is the way to them.

## the switcher (#174)

### `function viewing`

Above `function viewing(el) {`:

The earlier-run rows were text with no handler, and the only session-changing gesture in the
whole page was *adopt* -- which then disabled Send. So a session you had finished with was a
thing you could read about and not open, and *I started it in a terminal yesterday* had no
answer at all.

The strip is a tab view: the main tab is this checkout's live session, the tabs beside it are the
project's other checkouts (#175 fills them in; before it, `siblings` is empty and the strip is
one tab and *earlier*), then *earlier (n)* and *+ new*. Reading a session is a GET and nothing
else -- choosing one must never spawn an agent -- and making one live again is a second,
deliberate press, the way *Reset anyway* is.

### `function endedSentence`

Above `function endedSentence(data) {`:

One sentence, in the words the page has: how it ended and when. The *refusal* to resume is the
server's own sentence, never this one -- a second opinion about why something was refused is how
an operator ends up with two explanations of one rule.

### `function drawSessionPill`

Above `var bits;`:

One line, saying which session this transcript is. The run line under it still says which RUN,
because those are two facts and the operator asked for neither of them twice.

Above `var startsOn = row.model ? shortModel(row.model) : "the CLI chooses";`:

#368: what a new session or a console starts on (`LAUNCH.model_for`), and why, beside each.

Above `drawRuns(el.querySelector(".live-runs"), runsFor(row, el.dataset.session || ""));`:

This session's own earlier runs, folded under it -- the inert list that used to sit below the
transcript as a second, adjacent *earlier* with different behaviour.

Above `var sibs = row.siblings || [];`:

Sibling checkouts of the same project (#175). Empty until that slice lands, which is why the
menu has to read as finished with none of them rather than as a row of missing things.

Above `patchList(sibList, sibs, function (sib) { return sib.repo; },`:

Patched, not rebuilt (#514), as the runs list is (#494): this runs on every row pass, and an
idle desk is zero DOM mutations. Keyed by the sibling's repo, which a registry name makes unique.
The hidden pattern row stays where it is: it has no `data-rowkey`, and `patchList` neither counts,
moves nor removes an unkeyed child. The click is bound once, when the row is made, and reads the
repo off the row, so it opens the checkout the row is for now, however often it is drawn.

### `function runsFor`

Above `function runsFor(row, session) {`:

The runs of one session, newest last, as plain rows. A run is a transcript boundary, not a thing
to open: opening one is opening its session, which is the row above it.

### `function drawRuns`

Above `function drawRuns(list, runs) {`:

Patched, not rebuilt: the session pill draws this on every row pass, and an idle desk is zero DOM
mutations (#494). Keyed by run number, which `split_runs` numbers 1..n down one stream, so no two
rows of one list share it; a run that arrives is one new row, and a row already there only has
its words written, which `text()` skips when they are the same.

### `function menuOpen`

Above `function menuOpen(el) {`:

The menu: open, closed, and stepped through without a mouse.

### `function loadSessions`

Above `function loadSessions(el, repo) {`:

The rows on the open, not on every poll: a disk read and a fold nobody is reading until asked.

Above `text(li.querySelector(".ss-src"), SESSION_SOURCE[r.source] || "");`:

Where it ran, in words, and whether a fresh start left it (#489): two rows that both
read `RDSD-118 · idle` are told apart without hovering.

Above `drawRuns(li.querySelector(".ss-runs"), runsFor(row, r.id));`:

Its runs, under it. One *earlier*, not two adjacent ones with different behaviour.

### `function showSession`

Above `function showSession(el, repo, session) {`:

Read-only, from history. The live transcript is hidden rather than replaced, so it keeps filling
behind this and going back is instant and whole rather than a reload with a hole in it.

Above `setData(el, "endedState", (data && data.state) || "ended");`:

What the pill says while this is open: how it ended, and when.

Above `text(el.querySelector(".ro-note"),`:

Exact, not guessed (#191): said while this checkout's console is alive, not for every
session the store happens to know.

### `function stepMenu`

Above `function stepMenu(el, repo, dir) {`:

`Alt+[` and `Alt+]` walk the menu, opening it if it is shut. The items are real buttons in
document order, so stepping is moving the keyboard to the next one -- there is no second model
of "which item is selected" that could disagree with what is on the glass.

Above `toggleMenu(el, repo);`:

Opening IS the first move: the keyboard lands on *this session*, and the next press walks.

### `function resumeHere`

Above `function resumeHere(el, repo) {`:

Making an earlier session the live one: it runs, or it is the supervisor's own refusal with the
supervisor's own hint and a button that has become a second, deliberate press.

Above `if (r && (r.code === "live_agent" || r.code === "mid_ticket")) {`:

Both refusals a resume meets take a second press: something holds the checkout, or it is
mid-ticket on this session's own ticket (#191, what a closed console leaves). Never silent.

### `function openConsole`

Above `function openConsole(el, row) {`:

One button, three verbs (#189/#190/#191): raise the console this tile has, continue this tile's
session in one, or open a fresh one. Refusals land in the supervisor's own words.

## start fresh (#488, #489)

One action, one word (SESS-D1): the session menu's item, the head's button, the adopt strip's
button and `Alt+N` all call this, and it posts the verb `ad-fleet fresh` calls. The server decides
(`row.fresh`); the page only says what it said. A chat that may still be open answers `chat_open`
with `second_press`: the pressed button then reads *start fresh — it is closed*, and the next
press says so (SESS-D2). Any other refusal arms nothing.

### `function freshShown`

Above `function freshShown(row) {`:

Does this pane offer *start fresh* on a full pane's head and mark its rail? #509 (SESS-D6: every
pane) widens only the head's button, and only on compact panes: `drawFresh` below.

### `function freshWords`

Above `function freshWords(row) {`:

What pressing it would do, in words: the ticket and model it starts on, and what it leaves.

### `function drawFresh`

Above `hide(head, !row.fresh);`:

#509: drawn whenever the row can say what a fresh start would do; `is-offer` is #489's rule, and
app.css hides a button without it on every pane but a compact one, where the bottom row's Start
is hidden. A change of tier costs no script.

Above `if (el.dataset.freshArmed && el.dataset.freshArmed !== (f.verdict || "")) disarmFresh(el);`:

An armed press lasts only as long as the verdict it answered, as *Reset anyway* does.

### `function rowOf`

Above `function rowOf(row) {`:

This pane's newest row, for a handler bound when the pane was built.

### `function beganWords`

Above `function beganWords(ts) {`:

When a session began, in the operator's day: `today 08:02`, `yesterday 17:40`, or a date.

Beside `var d = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(s) ? s : s + "Z");`:

the stream's clock is UTC

### `function startFreshWords`

Above `function startFreshWords(row) {`:

What the bottom row's *Start fresh* would do (#509): the ticket, the model, and the session left.

Above `var began = beganWords(run.session_began || run.started);`:

#499's `session_began` where the row carries it; the current run's start otherwise.

### `function drawStart`

Above `function drawStart(el, row) {`:

The bottom row's Start (#509). An empty box makes it *Start fresh*, titled with what that does, or
with why not; text makes it today's Start. Written on a draw and on the box's `input`, and only
when it changes, so an idle pane writes nothing.

Above `if (empty && el.dataset.freshArmed) label = "start fresh — it is closed";`:

A press armed on `chat_open` (#489) says so on every door until the verdict changes.

### `function startFresh`

Above `function startFresh(el, repo, button) {`:

```js
/** @param {HTMLElement} el  @param {string} repo  @param {HTMLElement|null} button */
```

In `tell`, above `if (rail) say(repo + ": " + words);`:

A rail has no visible `.err`: its answer goes in the footer. Every other width shows it.

## the whole page

### `function applyWindow`

Above `function applyWindow(win) {`:

```js
/** @param {WindowRecord} win */
```

Above `if (win.open !== undefined && win.open !== openTile) {`:

What is open is `open` and nothing else (#230, #232). The grid's `zoomed` was a second field
for the same fact, and the two disagreeing inside one record is what snapped a click back to
the agent before it; the record no longer has one.

Above `myWidths = ownWidths(win.widths);`:

The widths are the record's too, including none (#234). `focus` and `held` are not read: the
needs-only filter they served is the *needs me* preset now, one write of widths.

### `var probing`

Above `var probing = false;`:

`ad-fleet probe --open pycharm` (#247). Nothing outside the IDE can point PyCharm's tool window
or VS Code's view at a URL, so the CLI asks the server to have this window measure, the ask
arrives with the desk, and the desk already inside the IDE goes to `/probe` by itself, carrying
its own query string so the probe can bring it back. The desk loads no three.js: the probe page
does, and only while it measures.

The ask is the server's, in memory, and TAKEN rather than read (#261): the window goes only when
`measure {take}` answers `go`, so a second desk under the same name, a snapshot drawn on reload
or an ask from yesterday (the server drops them after ten minutes) goes nowhere. And not while
the operator is typing: half a reply in a tile, or a brief in the dispatch card, would be lost to
the navigation, so the desk says what it is waiting for and goes once those boxes are empty.

### `var lastApprovals`

Above `var lastApprovals = [];`:

The approvals from the last answer, kept so a redraw does not need a fetch to be honest.

### `function redrawAll`

Above `function redrawAll() {`:

Every tile drawn again from the row it already has, and one layout pass. No network: this is
what a stream frame, a theme change or a mode toggle needs, and under the render contract
(#215) it is free when nothing has changed.

### `function readBefore`

Above `function readBefore(shown, row) {`:

Was this row read before the one the tile already has (#235)? The two roads race each other home:
a snapshot the server read a moment before a hand-back landed after the hand-back's own answer and
drew the adoption back, and nothing came to draw it again -- a released lock is not an event. The
server numbers its reads, and a row from another run of it is a desk that restarted: taken.

```js
/** @param {Row | undefined} shown  @param {Row} row  @returns {boolean} */
```

### `function fillTranscript`

Above `function fillTranscript(entry, row) {`:

One row onto its tile, making the tile if this is the first sight of it. Both an action's
answer (#219) and a whole snapshot come through here, so a tile cannot be drawn one way by one
path and another way by the other -- nor by the older of the two because it arrived second.
A tile's transcript from a row's `recent` (its last forty), the cursor taken from each, then the
scroll this window left it at.

```js
/** @param {Pane} entry  @param {Row} row */
```

### `function patchRow`

Above `function patchRow(row, index) {`:

```js
/** @param {Row} row  @param {number} [index]  @returns {Pane | null} */
```

Beside `watchPane(el);`:

#233: its width decides what it draws

Beside `arrivedSinceLastPlace = true;`:

and where it first lands is not a move

Above `entry.restored = false;`:

#347: drawn from the snapshot, which keeps no transcript. Its first real row fills it and
sets the cursor, so the stream resumes after that row instead of replaying from 0.

## #219: the desk that is already there, while it loads

Stale, then right. The first `/api/fleet` on a nine-project fleet is a catalogue read, a fold
per agent and a spend ledger per agent, and until it answered the window was an empty grid with
a sentence about having no projects -- which is the wrong answer to "what is my fleet doing",
given for a second, every time a window is reopened.

So the last snapshot this window saw is kept and drawn first, marked as what it is, and the
fetch that is already in flight replaces it. Without the transcripts: they are the big part of
the payload, they are the part that goes stale fastest, and the first answer brings the last
forty, and the stream resumes after them (#347).

### `var themeEvents`

Above `var themeEvents = 0;`:

How many `theme` events the stream has delivered (#437). A fleet answer's theme is the one saved
when the server answered, so an answer asked before a theme change lands after the stream's
event and would put the old skin back. `refresh` applies the answer's theme only when no theme
event arrived while it was in flight.

### `function deskAsShown`

Above `function deskAsShown(fallback) {`:

The desk as this window last showed it: the newest desk it holds, with the agent it has open.
The fleet's own answer is older than both the moment a click lands, and a snapshot kept from it
reopened -- on the next load -- whichever agent was open when it was taken, then jumped to the
right one when the fleet answered (#230).

```js
/** @param {DeskRecord | null} fallback  @returns {DeskRecord | null} */
```

Above `if (myWidths) mine.widths = Object.assign({}, myWidths);`:

The widths it shows, for the same reason (#234): a gesture a moment before the reload is newer
than the last answer the fleet gave.

### `function cacheSnapshot`

In `} catch (e) { }`:

a private window, or no room: the desk simply loads the slow way

### `function servedTiers`

Above `function servedTiers() {`:

```text
The tiers the server wrote on <html> (#345), `rail compact full slack`, or null on the defaults.
```

```js
/** @returns {Tiers | null} */
```

### `window.addEventListener("pageshow", function (e) { if (e.persisted) re …`

Above `window.addEventListener("pageshow", function (e) { if (e.persisted) refresh(); });`:

Back into a page the browser kept whole (bfcache): what it shows is from before it was left, and
a theme chosen meanwhile reaches it only by asking again.

### `window.addEventListener("pagehide", function () { if (lastFleet) cache …`

Above `window.addEventListener("pagehide", function () { if (lastFleet) cacheSnapshot(lastFleet …`:

Taken again as the window goes -- a reload, a navigation, a closed tab -- so the next load draws
what was on the screen, not what the last fleet answer said a click or two before.

### `function restoreCached`

Above `if (Date.now() - (data.at || 0) > SNAP_GOOD_FOR_MS) return false;`:

Five minutes. Past that the shape of the fleet has probably changed, and a wrong desk held
for a second is worse than an empty one -- the fetch is in flight either way.

Above `if (data.desk) {`:

No theme and no tiers (#345): the served page already wears the chosen ones, and a snapshot's
were taken before the change that sent the operator here -- the skin just replaced.

Above `var shown = Object.assign({}, data.desk);`:

Shown, not believed. Its version is the snapshot's, so it is dropped: the first real answer
has to win whatever number it carries, or a desk.json that started again from nought would
never be heard. The window's own open agent is what is drawn, as the real answer will.

Beside `if (e) e.restored = true;`:

#347: its first real row brings the transcript

Above `toggle(document.body, "is-stale", true);`:

Said, not hidden: the desk on the screen is the last one this window saw, and the operator is
told so rather than left to find out.

### `function refresh`

Above `departed.set(name, { path: (entry.row && entry.row.path) || "<path>" });`:

Removed from the registry. Its pane goes, but not silently: it leaves a rail naming the
command that restores it, because a transcript disappearing with no explanation is
exactly the "where did it go" #173 exists to answer.

Above `if (fleetSpend.budget_invalid) {`:

A budget nobody can read cannot be enforced, so it is off -- and said out loud rather than
swallowed into 0.0, which is what the old reader did (#213).

Beside `if (themeEvents !== themesAsked) delete data.theme;`:

older than the stream's: not drawn, not cached

Beside `applyTiers(data.theme.tiers);`:

#235: the operator's tier boundaries

### `function connect`

Above `function connect() {`:

`body.is-replaying` (#371): the first pass after every open is history, not news. The server
writes every event after each cursor in `since` and ends a pass that sent frames with `tick`; a
repo missing from `since` starts at 0, and EventSource's own reconnect re-sends the original URL,
whose `since` wins over Last-Event-ID, so it replays from the old cursors. A replayed `li.denied`
looks exactly like a fresh one, so the page says which until the pass's `tick`. Set here and in
`onopen` (the native reconnect calls only that); nothing styles it.

Above `source.addEventListener("polls", function () { refreshSoon(); });`:

A poll cell changed with no event to say so (#184): re-read.

Above `source.addEventListener("desk", function (m) {`:

The shared selection (#133). Every window is sent the current one the moment it connects, so a
monitor that joined late never sits on a different project than the one beside it.

Beside `applyTiers(d.tiers);`:

#235: set on the settings page, in effect now

Above `} catch (err) {}`:

#218 repainted every trace here, because a canvas held pixels rather than rules. The trace
is the stylesheet's colours now (#257) and the ink layer reads the palette at paint time,
so a palette that changes needs nothing drawn again.

Above `source.addEventListener("models", function () {`:

The model list moved (#361): stale for the next open, and drawn again now only if the card is.

Above `source.addEventListener("wrapup", function (m) {`:

A wrap-up job moved (#503, #510): read it only when the sheet shows that repo.

In `source.onerror`, above `setTimeout(function () { refresh().then(connect); }, 2000);`:

EventSource reconnects on its own, but the page must not trust what it drew in between.

## opening one, and the keyboard

## what the two focuses actually are (#207)

`focus()` zoomed one tile and `focusMode()` filtered for the ones that need a person: two modes
named alike, side by side. They are `openAgent` and the *needs me* preset now (#234) -- a press
that widens whoever needs you, not a mode.

Not literally `open`: a bare `function open()` in a non-module script replaces `window.open` for
the whole page, and a name that shadows a platform function to read slightly better is a trade
this page does not need to make. Nor `focus`, the old name, which stayed as an alias until the
type check read it (#236: `Duplicate identifier 'focus'`). `var focus` in a non-module script IS
`window.focus`, so a `window.focus()` from anything on the page opened nobody, shut the drawer and
wrote this window's record twice. Nothing called the alias -- the shells open an agent with
`#tile=`, and no test named it but to say it was there -- so it went.

### `function openAgent`

Beside `unread.delete(name);`:

looking at it is what "read" means

Above `openPane(name, skipPost);`:

There is no zoom to enter (#232): every agent is a pane in the row already (#233), so "focus
this agent" and "open this agent" are the same gesture. Every caller -- a toast's anchor, a
notification row, the away strip -- therefore lands on the right thing.

### `function followHash`

Above `function followHash() {`:

A toast launches `…/?t=…#tile=luna`, so the click lands on the agent that needs the operator
rather than on "one of these four". Also fired on hashchange, because the window may already be
open and the shell simply re-focuses it with a new hash.

Above `say("no tile for '" + name + "' — is it still registered?");`:

A toast for a repository with no tile used to do nothing at all: the window simply sat there
while the operator waited for something to happen (#173).

Above `if (isHidden(name)) {`:

A hidden tile is reopened by an anchor rather than silently ignored, and the footer says so:
the toast said this agent needs somebody, and the operator asked to see it.

Above `openAgent(name);`:

Focus mode is left alone. It used to be turned off when it was what kept the agent off the
glass; since #233 it never keeps anything off the glass -- a quiet rail is dimmed, and an open
pane is never quiet -- so turning it off would only throw away the pass the operator was in.

### `document.addEventListener("keydown", function (e) {`

Above `if (closeModelCard()) { e.stopImmediatePropagation(); return; }`:

The nearest open thing closes first, and nothing else: a popover (#180), then the card (#183).

Above `else backToPrevious();`:

There is no zoom to leave, so `Esc` is "show me the last one again" -- which is the other
half of the glance the swap is for.

Above `var pane = paneStops()[Number(e.key) - 1];`:

The number printed on a pane comes from the arrangement, so the key that opens it must too:
registry order meant the badge said 3 and pressing 3 opened something else. It counts the
panes on the glass, in the row's order -- every agent is one now (#233), the open one
included, so the number on a pane never changes because another one was opened.

From 2: `1` is the *one* preset since the gutters (#234), the plan's key for it. The first
pane is `j` from nowhere, or `1` with the keyboard on it, which makes it the one wide pane.

Above `var at = document.activeElement;`:

#234: the arrows walk the row as `j` and `k` do -- from a pane, or from nowhere. An arrow in
the sidebar or a menu is that control's own, and a shifted one is not this gesture.

Above `var onPane = document.activeElement && document.activeElement.closest`:

#510: wrap up the pane the keyboard is on, rail or wide, as `r` and `m` act on it: the project
panel opens with the sheet, and the preview starts. Nothing is written until *write n*.

Above `var host = document.activeElement && document.activeElement.closest`:

The pane the keyboard is on, rail or wide -- the same two keys on either, because a rail has
no head to carry the buttons and the keys are how it keeps them (#205, #233).

Above `var onTile = document.activeElement && document.activeElement.closest && document.active …`:

Hide the tile the operator is on. Every drag gesture has a keyboard equivalent, and so does
this one -- a desk that can only be arranged with a mouse cannot be arranged by someone typing.

Above `var open = openName();`:

The open agent's write: the key used to follow the grid's zoom, which the column never set,
so in the column it approved nothing at all.

## theming

### `var setLink`

Above `var setLink = (document.getElementById("setbtn"));`:

The pickers live on `/settings` now; what stays here is the desk repainting itself when somebody
else moves them. The `theme` frame arrives on the stream whenever `config.json` changes, so a
palette chosen on the settings page, in another window, or by `ad-theme set` in a terminal
reaches this desk without a reload. `applyTheme` and `applySkin` are common.js's.

The token is per run and `_authorized` reads it from the query string alone, so the settings
link cannot be a static href in the markup -- it would 403 and read as a dead button, which is
exactly what the operator reported.

### `refresh().then(function () {`

Beside `if (mapLink) mapLink.href = pageUrl("/map");`:

#407: the map, in the window the desk is in

Beside `LOAD.settled = document.body.dataset.skin || "";`:

the skin the first refresh settled on (#351)

Above `loadDesk().then(function () { if (BOOT_HASH && location.hash === BOOT_HASH) followHash() …`:

The anchor is answered *after* the desk, not beside it: whether a tile is hidden is the
server's arrangement, and a `#tile=` that lands before that has loaded reads every tile as on
the glass -- so the one thing it was asked to do, reopen a tile that is not, it did not (#173).

And only the anchor the page was opened with, and only if nothing has moved it since. The desk
read is the slow one -- a catalogue, a Downloads scandir -- and a pane pressed before it answers
marks the address itself: followed then, it opened that agent a second time through
`openAgent`, whose `drawer(false)` shut the sidebar the operator had opened meanwhile and wrote
`section`, `open` and `read` again (#234, three extra writes on the Windows leg).

### `setInterval(loadDesk, 15000);`

Above `setInterval(loadDesk, 15000);`:

The desk half is answered on its own, slower clock: a catalogue read, a Downloads scandir and a
`.agent/out/` stat per project is not something to do four times a second, and nothing on it is
urgent -- what is urgent arrives on the stream.

## notifications (#97)

### `function chime`

Above `function chime() {`:

The chime is synthesised, not a bundled sound file. WebAudio is in every browser this page has
to run in, it adds nothing to the payload and nothing to fetch, and a .wav shipped as package
data is one more thing that can fail to install. Off by default: a sound the operator did not
ask for is the fastest way to have every notification muted.

In `osc.onended`, in `osc.onended = function () { try { ctx.close(); } catch (e) { } };`:

already closed

In `} catch (e) { }`:

no audio device, or autoplay refused until the page is clicked

### `var chimeOn`

Beside `var unread = new Map();`:

repo -> count, cleared when that tile is focused

### `function bell`

Above `if (entry.row) drawPaneRail(entry.el, entry.row);`:

The rail carries the same count, and says it in its name (#233).

### `function loadNotifications`

In `}).catch(function () { });`:

the drawer is a convenience; the tiles are the truth

## the sidebar (#148)

Five panels used to be five fixed overlays at the same screen edge: they covered the grid, they
covered each other, and because `[hidden]` lost to their `display: flex` a "closed" one went on
eating the clicks meant for the tiles underneath it. They are now five sections of ONE sidebar
beside the grid, exactly one open at a time, with a tab strip that says which. Each panel keeps
the function name the rest of this file already calls.

### `function section`

Above `function section(id, open, skipPost) {`:

`open` undefined toggles, true opens, false closes. Opening one closes the rest.

### `document.getElementById("chime").addEventListener("click", function () {`

In `try { localStorage.setItem("fleet.chime", chimeOn ? "1" : "0"); } catch (e) { }`:

private window

Beside `if (chimeOn) chime();`:

and it plays once, so "on" is not taken on trust

## the Jira board (#98)

### `var board`

Above `var board = [];`:

Dispatching a ticket should not mean copying a key out of a browser. The panel is a view of the
operator's own JQL; a ticket goes to an agent by being dragged onto its tile, or by clicking the
button on the row when the repository is unambiguous.

The suggestion is the server's, from each repo's declared `jira_project`. Three answers, and the
panel shows all three honestly: one repo (drag has an obvious home), several (pick one — guessing
would eventually start the wrong checkout), none (the repo is not registered, which is a one-line
fix worth naming rather than a silent blank).

### `function ticketRow`

Beside `tabbable(li, 0);`:

`1`-`9` from here picks a rail chip (#183)

## the scope, by hash (#166)

A file dropped on a tile used to light the tile up and do nothing: `drop` read `text/plain` only.
The page still never learns a path -- no browser gives one, in any of the three embedders this
page has to render in -- so it does not ask for one. It computes git's own object name for the
bytes and asks the server which of the checkout's files has it. Nothing but that hash leaves the
page until the operator clicks *attach a copy*.

### `var SCOPE_MAX_FILES`

Beside `var SCOPE_MAX_HASH = 64 * 1024 * 1024;`:

fleet.scope.max_hash_mb, from /api/fleet

### `function sha1Bytes`

Above `function sha1Bytes(bytes) {`:

SHA-1, because that is the hash git names objects with. `crypto.subtle` where the origin is a
secure context -- loopback is one -- and this otherwise, because VS Code's Simple Browser renders
the page inside a webview whose context we do not get to assume. No CDN: the page has no build
step and nothing it fetches from the internet arrives behind the corporate proxy.

### `function filesFromDrop`

Above `function filesFromDrop(dt) {`:

A dropped folder is the same trick over its files. `webkitGetAsEntry` is the only way to read
one, and it is in every engine this page runs on.

### `function scopeDrop`

Above `return Promise.resolve({ name: f.name, size: f.size, sha: "" });`:

Too big to hash without freezing the tab. Name and size is the weaker claim, and it is
labelled as one wherever it is shown -- the way adoption labels its two.

Above `var attach = li.querySelector(".sc-attach");`:

Not this repository's file. The only route that moves bytes, and only on this click.

## the dispatch card (#164)

A drop used to be a launch. It opens this instead: the rows a person would have checked before
delegating, gathered by a server-side pre-flight that spends no premium request, and one button.
`fleet.preflight: false` restores #98's immediate start for anyone who preferred it.

### `function onTheGlass`

Above `function onTheGlass(repo) {`:

One card, two homes (#183): the pane's slot when the pane has room for it, else under the agent
rail. Every agent is on the glass now (#233), but a rail is 48px of glass and a card is not
drawn in one: a compact or full pane takes it, a rail sends it to the board.

### `function dispatchCard`

Beside `if (card.parentNode !== home) home.appendChild(card);`:

moved, never copied

Beside `if (card.dataset.key !== key) return;`:

a second drop overtook this one

Above `paintVerdict(card, verdict);`:

`thin` is the one verdict that asks for something: the brief box takes the focus and the
button says so. `blocked` still offers the press, because the refusal is the server's to
give in its own words and the operator may hold an override the card does not know about.

Above `var thin = (card_data.rows || []).filter(function (r) { return r.verdict === "thin"; });`:

A card thin on the model alone (#368) asks for a model, not a brief: its why is the note,
and the keyboard goes to the pressed pill.

### `function dispatchRow`

Above `function dispatchRow(r) {`:

One pre-flight row. Its name and verdict ride on it as data, so the one row a press changes can
be found and drawn again, and the card's verdict read back from its rows.

### `function rereadDispatchModelRow`

Above `function rereadDispatchModelRow(repo) {`:

The card's `model` row after a press (#368, decision 15): read again on its own -- the config and
the cached model list, never Jira -- and drawn in place, with the verdict worked out again from
the rows by `preflight.verdict_for`'s table (a refusal, then an unread source, then thin).

### `var dispatchPicker`

Above `var dispatchPicker = null;`:

Which model the agent will start on (#368): the dispatch card's compact picker, made once
(bindDispatchCard) and drawn with the card's repository under the model card's rule (#366). A
press writes that repository's model -- this start and every later one, through the one writer
-- and `more…` is the model card, for what the compact picker leaves out.

### `function dispatchModelDrawn`

Above `function dispatchModelDrawn() {`:

Drawn now with the list the page has, and again once a list it lacked or that went stale is in.

### `function said`

Above `function said(repo, message) {`:

A refusal lands where the operator is looking: the card's note, or the line under the rail.

### `function dispatch`

Above `said(repo, r.error + (r.hint ? " — " + r.hint : ""));`:

The one refusal worth offering an override for in the page: the operator can see both
projects on screen and is better placed than the guard to say it is deliberate.

### the closure › `card.addEventListener("keydown", function (e) {`

Above `card.addEventListener("keydown", function (e) {`:

Every key but Escape stays in the card (#368), as in the model card (#366): on the glass it
sits in a pane's slot, where `h` would hide that pane, `a` approve its write and `j` walk the
row. Escape goes on to the document, which closes the nearest open thing.

## the agent rail (#183)

One chip per checkout at the top of the board, each a drop target for the window with no tiles.
A drag lights the candidates; a drop calls what a tile's drop calls; `1`-`9` is the same by key.

### `function drawRail`

Beside `var railDrag = null;`:

the ticket row in flight, if any

### `function railLight`

Above `function railLight(row) {`:

A dimmed chip still takes a drop; `cross_project` is the answer.

### `document.getElementById("tickets").addEventListener("keydown", /** @ty …`

Above `if (/^[1-9]$/.test(e.key)) {`:

Stops here: the page's own `1`-`9` zooms a tile, closing the board under the card.

### `function drawBoard`

Above `var had = document.activeElement && list.contains(document.activeElement) ?`:

A redraw keeps the keyboard on its row (#183).

### `function loadHistory`

In `}).catch(function () { });`:

the strip is a convenience

## the desk (#130 #131 #132 #133)

Everything below reads. The one exception is `attach`, which copies a file the operator clicked
into that repository's own `.agent/in/` -- the single write the epic allows outside
`~/.agentdata/fleet/`, and it happens because a person pressed a button.

All of it comes from one `/api/desk` on a slow clock rather than a fetch per tile: four screens
of tiles is four screens of requests otherwise, and none of this is urgent.

### `function registryChanged`

Above `function registryChanged(order) {`:

```js
/** @param {string[]} order */
```

### `function loadDesk`

Above `var incoming = data.desk;`:

Everything but the desk state is this answer's; the desk state goes through the door (#230).

Above `if (registryChanged(data.order)) refresh();`:

`ad-fleet repo add` and `repo rm` change which tiles exist and neither is an agent event,
so the stream never mentions it: the grid drew a repository that had left, or missed one that
had arrived, until a reload. The desk's slow clock carries the registry's list, so a
disagreement is what asks `/api/fleet` again (#173).

Above `drawInspector(desk.desk.selected);`:

The project's own detail is the inspector's, and the inspector draws the selected one.

## the project's live state

### `function drawCells`

Above `function drawCells(el, polls, row) {`:

A cell is value + age, and when the poll failed it is grey with the error in the tooltip and the
*last value it actually had* still on it. Blanking it would lose what was known; keeping it
without the age would make five-minute-old news look current. Grey, old and honest.

Beside `if (!value && !p.error) return;`:

nothing to ask about: no PR, no dataset

Above `patchList(box, want, function (item) { return item.cell; },`:

Keyed, and created once. The cells were emptied and rebuilt with fresh listeners on every
draw, which is several times a second while an agent talks -- so the git cell the operator was
about to click was a different element by the time they clicked it.

Above `var shape = box.querySelector(item.cell === "git" ? ".gitshape" : ".cellshape");`:

Cloned from the shape in the markup, and listened to once. The git cell is a button
(#184): the click opens the inspector's branches pane.

### `function drawSpendCell`

Above `function drawSpendCell(cell, row) {`:

What it has cost, against what (#211).

`premium_requests` has been on every row since #94 and was rendered nowhere; the dashboard's own
documentation said cost and budget were "a strip in #101", and #101 closed without one. This is
that strip, as a fifth cell beside the four the project is polled for -- and never colour alone:
amber and red each carry the sentence that explains them.

Above `said = row.repo + " has spent " + s.total + " of its " + s.budget +`:

The supervisor's own sentence, so the cell and the refusal say one thing.

## the branches pane (#184)

Read on the click, cached for the git interval, never on the poll.

### `var branchesWanted`

Beside `var branchesFor = {};`:

repo -> the last /api/branches answer

### `function openBranches`

Beside `var branchesWanted = "";`:

the repo whose pane was just asked for

### `function branchesPane`

Above `function branchesPane(name) {`:

#504: the summary and the carry line stay in sight; the list and the commits sit in a fold that is
open when the answer warns or the git cell asked for it, and otherwise as the operator left it.

### `function spendPane`

Above `function spendPane(name) {`:

The selected project's spend, in the inspector: what it has cost, by session and by day. A tile
is the AGENT and the inspector is the PROJECT (#148), and "what has this cost me" is a question
about the project -- which is why the number is a cell on the tile and the breakdown is here.

Above `var line = "spend " + s.total + " all time · " + s.today + " today · " + s.session + " t …`:

One line (#504); the turns, the mean and the CLI that prints the same ledger are its title.

### `function clip`

In `} catch (e) { }`:

Simple Browser has no clipboard permission; fall through

In `try { document.execCommand("copy"); } catch (e) { }`:

nothing else to try

## the Downloads inbox (#132)

### `function offerRow`

Above `where = document.createElement("select");`:

Unsorted: the operator picks the project. Nothing is guessed -- two repos that match the
name equally well is exactly why this tray exists.

## where (#130), search

### `function drawHits`

Above `function drawHits(data) {`:

The catalogue answers "which project owns Velocity" without opening a tab. It is the same
`Catalogue.where` the CLI verb calls, and it reads only what each repo publishes -- no source,
no notebooks, no exports, and nothing that was never indexed.

### `var findSoon` › `return function () {`

In `.then(drawHits).catch(function () { });`:

search is a convenience; the tiles are the truth

## the shared selection (#133)

### `function mergeDesk`

Above `function mergeDesk(answer) {`:

One selected project, shared by every window on this server. It is a POST and not a URL fragment
because the point is that the *other* windows hear about it: clicking a tile on the left monitor
is what changes the inspector on the centre one.
The desk state is merged, never replaced. `/api/select` once answered with the selection alone
and said nothing about the arrangement, so assigning its answer wholesale dropped `arrangement`
on the floor: clicking any tile un-widened every tile you had widened and unpinned every tile
you had pinned, until the next `/api/desk` poll fifteen seconds later put them back.
#219: an answer that is older than what this page already has is not an answer, it is an echo.
Five gestures in a second is five posts in flight, and they do not come back in the order they
went: a resize answered after the move that followed it put the tiles back in the order they
were in before the move. The desk carries a `version` that only ever rises, so the check is one
comparison and the losing answer is simply dropped -- the winning one already describes the
same arrangement. `selected` has no version of its own and is set locally, so it is merged
either way.

```js
/** @param {DeskAnswer} answer */
```

### `function choose`

Above `function choose(name) {`:

```js
/** @param {string} name  @returns {Promise<void>} */
```

### `var inspectorDrawn`

Above `var inspectorDrawn = "";`:

The selected project's own detail, in one place instead of repeated inside every tile: a tile is
the AGENT, the inspector is the PROJECT (#148). Visibility belongs to the sidebar, not here --
this only draws, so a redraw can never reopen a panel the operator just closed.

#504: it fits one screen. The rail, the friction that needs you now, one line of spend and the
branches come first; the facts, the missing keys, earlier friction, verify and the offered files
fold under one *more*. The desk's tick calls this every 15 seconds, so an unchanged project
returns before touching the DOM, and a rebuild keeps every fold as the operator left it.

### `var inspectorFolds`

Beside `var inspectorDrawn = "";`:

the signature the panel was last drawn from

### `function inspectorSees`

Beside `var inspectorFolds = {};`:

repo -> {fold class: open}, as the operator left them

Above `function inspectorSees(p) {`:

What the panel draws of a project, and nothing else: the project also carries the tile's poller
cells, whose ages move on every tick, and those must not rebuild a panel that does not show them.
The verify line's age is its words, so it redraws when the words change and not every second.

### `function inspectorFold`

Above `function inspectorFold(name, cls, openByDefault) {`:

A fold on the panel that remembers being opened or closed, across rebuilds and repos.

### `function drawInspector`

Beside `if (wrap && wrap.repo && name !== wrap.repo) closeWrapup();`:

the sheet is one repo's (#510)

Above `var links = (p.links || []);`:

Where this project lives -- the link rail, so a tab is opened to act and never to check.

Above `var wrapBtn = mk("button", "wrapup", "wrap up");`:

#510: the rail's last button previews every write for this agent; `w` on its pane does the same.

Above `var frictionOpen = p.friction_open || p.friction || [];`:

Friction (#499): the server decides what needs you now (open) and what folds under *earlier*;
the page draws it. An older server sends only `friction`, drawn as open. Dismissing a row never
answers its question -- the pane's question card does that -- and the file itself is kept.

Above `var spent = spendPane(name);`:

What this agent has cost (#212), as one line; the turns and the CLI that prints it are its title.
The same ledger `ad-fleet spend` prints, so the page and the CLI cannot disagree.

Above `body.appendChild(branchesPane(name));`:

The checkout's branches (#184): drawn from the last read, read on the click.

Above `var more = inspectorFold(name, "more", false);`:

Everything else folds under one *more*, closed until the operator opens it.

Above `var pairs = [`:

The ONE place on this page that renders a fact block, and it stays one on purpose.
`serve.tile_facts()` narrows `catalogue.LINK_FACTS` before any of it leaves the server,
because a fact block is hand-edited prose and a real one carries a warehouse hostname, a
`\\share\dpm\runs` path and a service account beside the Jira keys. A second loop over some
other payload's facts is how that filter gets bypassed by a change that looks like a feature.
If a panel ever needs a fact this loop does not show, widen `LINK_FACTS`; do not add a loop.
The project, its path and its branch are not repeated here: the drawer head, copy path's title
and the tile's git cell already say them (#504).

Above `var missing = p.missing_keys || [];`:

What is missing is named, so the operator knows which AGENTS.md key would fill the rail.

Above `var latest = ((p.verify || {}).latest) || {};`:

The newest thing the project's own agent verified, beside the report link.

## wrapping up an agent (#510)

The project panel's sheet: every write #503 plans for this agent, previewed by its adapter's own
dry-run, a tick per write, and one press -- *write n* -- that writes exactly the ticked ones
(WRAP-D4). The sheet is static markup, so the panel's rebuilds never touch it, and it is drawn
only from an answer or a `wrapup` frame: an idle desk with it open writes nothing.

The page posts `wrapup` from four places and no others: the sheet's open, its mode toggle, a
deliberate re-preview (a transition's name, *replace*, an edited comment, *preview again*) and
*write n*. Nothing is written that the sheet has not shown, a merge is never offered, and the
comment is a template (WRAP-D2) -- no model turn.

### `var wrapGo`

Beside `var wrapGo = new WeakMap();`:

a row's action button -> what it does now

### `function wrapSlot`

Above `function wrapSlot(row) {`:

The step a row writes, as its id's slot: `push`, `pr`, …, `transition-review`.

### `function wrapDone`

Above `function wrapDone(result) {`:

What a result's `done` reads as one word: written, failed, changed or skipped.

### `function wrapCell`

Above `function wrapCell(el, row, ticked, result, locked) {`:

One step's cell -- tick, glyph, step, summary, hint -- on an element cloned from `li.wrap-pattern`.
The sheet draws its rows with it, and the fleet sweep (#512) draws its cells with it too. A
result is words and a glyph, never a state colour: the agent's colours stay the agent's (#339).

### `function wrapActs`

Above `function wrapActs(el, row, result) {`:

The sheet's actions for one row: a transition's names, *open it* / *replace v<n>* on a page
someone edited, *replace the description* on a kept PR, *edit* on the comment, *preview again*
on a failed step. Every one that changes a write is a second preview (WRAP-D8), never a write.

### `function drawWrap`

Above `function drawWrap() {`:

The sheet as `wrap` says: the status line, the rows from the pattern row, the button's count.

### `function previewWrap`

Above `function previewWrap(extra) {`:

A fresh preview: this repo, this mode, and whatever the operator deliberately asked again with.

### `function writeWrap`

Above `function writeWrap() {`:

*Write n*: exactly the ticked ids of the preview on the sheet, and the edited comment with them.

### `function loadWrap`

Above `function loadWrap() {`:

The job as the server has it now, drawn: the frame says it moved, this reads what it is.

### `function openWrapup`

Above `function openWrapup(name) {`:

`w`, or *wrap up* on the rail: the project panel on this repo, the sheet, and a preview --
unless this repo's last job was written from another tab, whose results are drawn first.

### `function bindWrapSheet`

Above `wrap.comment = box.value;`:

An edit is checked again before it is sent: the comment's id hashes its text, so the preview
that *write n* confirms has to be the one that read this text.

### `function getArrangement`

Above `function getArrangement() {`:

The desk's one arrangement (#232) -- and a real object, not a copy of one.

It used to answer `{order: [], size: {}, pinned: []}` when the desk had not arrived yet, which
reads as harmless and is not: every optimistic write in `arrangeNow` mutates what it is given,
so before the first desk frame landed a hide, a move, a pin and a resize all wrote into a
throwaway and the tile did not move until the server answered. That is precisely the thing
#219 claims the page no longer does, and on a fast machine the desk has loaded before anyone
can click, so it only showed up on the slowest runner in CI. The record is created on the desk
instead; `mergeDesk` replaces it with the server's the moment one arrives.

```js
/** @returns {Arrangement} */
```

### `function getEffectiveOrder`

Above `function getEffectiveOrder() {`:

```js
/** @returns {string[]} */
```

### `function isHidden`

Above `function isHidden(name) {`:

Hidden, and never hiding what needs a person (#173).

A hidden tile keeps its slot in `order`, so reopening puts it back where it was. The one rule
that overrides the operator's own choice is the fold's: a tile that needs somebody is on the
glass whatever the arrangement says, because hiding a demand is how a demand gets missed.

```js
/** @param {string} name */
```

### `function visibleOrder`

Above `function visibleOrder() {`:

```js
/** @returns {string[]} */
```

### `var arrangeWrites`

Above `var arrangeWrites = 0;`:

#219. Every arrangement change goes the same way: paint it, post it, and put it back with the
server's own words on the notice line if it refuses. The paint is inside the frame the gesture
happened in -- a page that waits for a round trip before moving a tile is a page that feels
like a form, whatever the round trip costs -- and the `desk` frame that follows is what makes
every other window agree.

`patch` is what to send; `apply` writes it into the local arrangement and answers with a
function that writes the old one back.
The arrangement's writes, one at a time and in the order they were made -- the rule #230 gave
the window's (#233). Two resize keys pressed together were two posts in flight at once, each
carrying the whole footprint as it stood at its press; the server applied them in whatever
order its threads took the lock, and the older footprint could land last and come back on the
next frame. While any is in flight the page's own arrangement is the one it keeps: an answer
or a frame from before the last press describes a desk the operator has already left.

### `function arrangeNow`

Above `function arrangeNow(patch, apply, what) {`:

```js
/** @param {Arrangement} patch  what to post
 *  @param {() => (() => void) | void} apply  writes it into the page's arrangement, and answers
 *                                          with what puts the old one back
 *  @param {string} [what]  the gesture's name, for its timing mark (#219)
 *  @returns {Promise<DeskAnswer | void>} */
```

Beside `if (arrangeWrites === 1) { mergeDesk(r); place(); }`:

the last one's answer is the desk

Above `if (undo) undo();`:

Refused. The arrangement goes back to what it was and the refusal is said out loud,
because a tile that silently returns to where it was is a page the operator stops trusting.

### `function setHidden`

Above `function setHidden(name, hide) {`:

```js
/** @param {string} name  @param {boolean} hide */
```

### `function reorderDomTiles`

Above `function reorderDomTiles() {`:

Moving an element with `appendChild` takes the focus off it -- so a grid that re-appends every
tile on every draw (and the stream draws several times a second while an agent is talking) took
the focus off the tile the operator had just selected, and Alt+arrow reached nothing. The order
is therefore only touched when it is actually wrong, and the focus is put back when it is.

Above `var shown = visibleOrder().filter(function (n) { return !groupedAway(n); });`:

What is on the glass as a pane of its own: not hidden, and not folded into its project's rail.

Above `if (dragging) return;`:

#217: not while a tile is under the hand. A draw that reorders the DOM mid-drag is a tile
that jumps out from under the cursor, and the stream draws several times a second.

Above `var first = (needsMove && !arrivedSinceLastPlace && !reduceMotion() && !inViewTransition)`:

FLIP, first half: where every tile is *now*, before the DOM moves. A tile that reorders by
`appendChild` alone teleports, and a grid reshuffling while agents talk reads as flicker, not
movement -- the operator cannot see it is the same tile, lower down. Measured only when
something is moving, and not at all when the viewer has asked for less of it.

Nor when a pane has just arrived (#233). Panes are made in the order `/api/fleet` lists them
and then put in the arrangement's, and since every agent became a pane on the glass the first
of those moves was visible: the rails shuffled into place for a fifth of a second on every
load, and anything aimed at one in that time -- a click, a test's drag -- landed beside it.
Where a pane first appears is not a move the operator made.

Above `toggle(entry.el, "is-hidden", isHidden(name));`:

Hidden is a class rather than `el.hidden`, so the tile keeps its slot in `order` and
reopening puts it back where it was rather than at the end.

Above `var at = shown.indexOf(name);`:

The number is the key that opens it, so it counts what is on the glass -- on the head and
on the rail alike, one writer for both.

Above `var isPinned = pinned.indexOf(name) >= 0;`:

The width is not written here: it is `paintWidths`', one owner (#234). #217's `--cols`,
`--rows` and `size-2` went with the span they described.

## moving tiles, visibly (#5)

### `function measureTiles`

Above `function measureTiles() {`:

Only tiles that are actually laid out. One that is not open, or is put away, has a zero
rect, and animating from nowhere to somewhere is a tile flying in from the corner of the screen
for no reason the operator can see.

### `function playFlip`

Above `function playFlip(first) {`:

FLIP, second half: put each tile back where it was with a transform, then let it travel to where
the DOM has already placed it. The layout is never animated -- only the paint -- so the grid is
in its final state throughout, and a click during the movement lands on the tile the operator is
aiming at rather than on wherever it used to be.

Above `requestAnimationFrame(function () {`:

Two frames, not one: the inverted transform has to be painted before the transition is armed,
or the browser coalesces the two styles and nothing moves at all.

## #217: the tile as a window, with a pointer

### `var DRAG_SLOP`

Above `var DRAG_SLOP = 4;`:

Four pixels before anything moves. A click on the head selects the project, and a gesture that
began reordering on the first pixel of travel made that click a drag on any trackpad.

### `var dragging`

Above `var dragging = null;`:

True while a pointer drag is in flight, so `place()` can leave the order alone until the hand
comes off -- a draw that reorders the DOM underneath a moving tile is a tile that jumps out
from under the cursor.

### `function swallowNextClick`

Above `function swallowNextClick() {`:

The `click` a pointer press ends in, taken off the page once: after a drag, and after a drag put
down with `Esc`. It is dispatched in the same task as the `pointerup` that ends the press, so the
listener takes itself off on the next turn whether or not a click came.

### `function bindDragToReorder`

Above `function bindDragToReorder(handle, host, name) {`:

Reorder by pointer, on a handle. `host` is what moves and `name` is what it is called: a pane
passes itself and its head, and itself and its rail's face (#233). Both write the same `order`,
because both are the same arrangement seen from two widths.

Above `var ctrl = e.target.closest("button, input, select, textarea, a");`:

A press on a control inside the handle belongs to that control -- unless the handle *is*
the control, which is what a rail's face is: one button filling the rail. The head is a
plain `div`, so every button in it is somebody else's.

Beside `if (!siblings.length) return;`:

nothing to reorder past

Beside `var target = null;`:

{ el, before } while one is lit

Above `var down = getComputedStyle(host.parentNode).flexDirection === "column";`:

The axis the list runs along is the axis the halves are measured on, or "before" means the
wrong side of the wrong edge. Read from the list itself rather than from which kind of host
this is: the row runs across (#233), and the column of bands it replaced ran down.

Above `var lift = function () {`:

The capture is taken when the drag begins, not when the pointer goes down. While an element
holds the capture the browser retargets the compatibility mouse events to it as well, so
capturing on `pointerdown` sent the `click` that ends an ordinary press to the head rather
than to the repository name inside it -- and clicking the name, which is how a tile is
opened, silently stopped working.

In `lift`, above `try {`:

Belt as well as braces: a selection made anywhere else on the page is still a selection
the browser would rather drag than let this gesture have.

In `lift`, in `} catch (err) { }`:

no selection to clear

In `lift`, in `try { handle.setPointerCapture(e.pointerId); } catch (err) { }`:

synthetic pointer

In `clear`, in `try { handle.releasePointerCapture(e.pointerId); } catch (err) { }`:

already released

In `onMove`, above `var under = document.elementFromPoint(ev.clientX, ev.clientY);`:

The dragged host has no pointer events while it is lifted, so this answers with whatever
is underneath it rather than with itself.

In `onUp`, above `swallowNextClick();`:

A pointer drag still ends in a `click`, and on a head that click selects the project
while on a rail it opens the agent. Neither is what the hand just asked for, so the one
that follows a real drag is swallowed.

Above `var onKey = function (ev) {`:

Esc cancels a drag in flight and leaves the order alone (HIG *Drag and drop*). Captured on
the document, because the capture has taken the keyboard's usual route away.

The button is still down when Esc is pressed, and the release that follows is not a click
on what was being dragged either. It was taken for one: Chromium sends the `click` that ends
a captured press to the handle, and on a rail's face that opened the agent the operator had
just put down (#233). So the click after this press is swallowed as well.

Above `document.addEventListener("pointermove", onMove);`:

On the document, not on the handle. A head is twenty pixels tall and the pointer is off it
before it has travelled far enough to count as a drag, so a handle that listened to itself
heard the first move and none of the others -- and the capture that would have fixed that
is not taken until the drag has begun, which it never did.

### `function holdOpen`

Above `function holdOpen() {`:

A reorder never changes which agent is open (#233). Until something opens one, the open agent
is only "the first in the order" -- and in the row a rail can be dropped before the open pane,
or the open pane carried past a rail, so the reorder itself would change what is first and open
a different agent under the hand. The one on the glass is written down before the order moves:
here, and in this window's record, so a reload opens it too.

### `function dropTileBefore`

Above `function dropTileBefore(name, onto, before) {`:

Where a drop lands, in one place, so the pointer and the keyboard agree about what "before"
means. Optimistic: the order changes under the hand and the server's answer is what the next
draw reads.

## #216: one door for anything that moves things

### `var inViewTransition`

Above `var inViewTransition = false;`:

True only while the browser is running a view transition of its own, which is the one time
`reorderDomTiles` must *not* also play FLIP: two animations of the same move is a tile that
arrives, leaves and arrives again.

### `function tileTransitionName`

Above `function tileTransitionName(name) {`:

A view transition matches the old state to the new one by name, so the name has to be the same
name for the same tile on both sides of the change -- an index would make "the third tile"
morph into whatever is third afterwards, which is the opposite of the point. Registry names are
already close to a CSS identifier; anything else in one becomes a dash. Two repositories that
sanitise to one name make the browser skip the transition and apply the change with no
animation, which is a degradation rather than a break.

### `function transitionMove`

Above `function transitionMove(fn) {`:

Every change to where things are goes through here: opening a pane, going back, hiding a tile,
reordering the row. `startViewTransition` is the good path -- the browser holds the old frame,
applies the change and morphs between the two, so the layout is never in a half-state -- and
FLIP is the fallback for engines that do not have it, which is every engine the IDE shells ship
until they catch up with Chromium. Reduced motion takes neither: the change is applied and that
is the end of it.

`fn` must do the whole change synchronously. Anything asynchronous inside it happens after the
browser has already taken its "after" snapshot, and a morph to a state that has not arrived yet
is a flash of the wrong layout.
Rearranging is FLIP, always -- never a view transition. The distinction is not taste: FLIP
moves the very elements, so the change is in the DOM on the frame the gesture happened in and
the animation is a transform on top of it; `startViewTransition` morphs *pictures*, so it has
to hold the old frame for one more frame while it takes its snapshot. For "this tile is now
over there" the first is both faster to show and truer -- and #219's whole claim is that the
desk paints what it already knows without waiting for anything, the browser included.

### `function transitionLayout`

Above `try {`:

Reported, and then let the transition finish. A change that half-applied is still the
state the page is in, and aborting the transition on top of that leaves the old frame
painted over the new one -- a page that looks fine and is not.

Above `done();`:

A transition already running, or an engine that has the function and refuses the call: the
change still has to happen, and it happens now.

Above `if (running.updateCallbackDone) running.updateCallbackDone.catch(function () {});`:

A `ViewTransition` carries three promises and a superseded one rejects all of them. That is
not three pieces of news, it is one: the operator made a second gesture before the first had
finished animating, which is the most ordinary thing on this page. `finished` is the one that
is acted on; the other two are caught so that the second gesture is not an *unhandled*
rejection -- which reaches the console as `Transition was skipped. New ViewTransition
started`, and reached a browser test as a page error on the slower of the two CI runners.

### `function moveTile`

Above `function moveTile(repo, dir) {`:

Pinned tiles come first, always -- so a move has to happen inside the block the tile is in.
Reordering the flattened list and posting that did nothing whenever anything was pinned:
`getEffectiveOrder` puts the pinned names back in front on the very next draw, and the move the
operator just made was silently undone.

Above `var target = idx + dir;`:

One press, one *visible* slot. A hidden tile keeps its place in `order` -- that is how
reopening puts it back where it was -- so stepping by one index swapped the tile with
something nobody can see, and the key read as having done nothing at all (#173).

### `function toggleTilePin`

Above `function toggleTilePin(repo) {`:

The pin writes the local arrangement BEFORE the round trip, not only after it. Reading
`desk.desk` and posting without updating it meant two quick clicks both read the same state and
the second overwrote the first: pin two tiles in a second and one of them silently came back
unpinned. The returned promise is what lets a caller sequence them.

A pin is the order's "first" (`Alt+Home`). Until a window has widths of its own it is also open
beside the open pane, as it was in the column; once it has, what is wide is what the widths say
(#234) -- plan-panes' *Pin retires*: a pane that stays wide because it was dragged wide is the
same thing, drawn by the hand instead of a button.

## hide, refresh and the model (#205)

The same three, in the same order, with the same keys, on every pane. The operator's sentence
was *active and inactive both*, and a control that exists in one place and not the other is what
this slice was asked to stop. A pane with a head carries them as buttons; a rail, which has no
room for a head, keeps the keys (#233).

### `function shortModel`

Above `function shortModel(name) {`:

The model's name, first, then its version (decision 15, #492): `gpt-5.6-luna` is `luna 5.6` and
`claude-sonnet-5` is `sonnet 5`, where the old tail-first form cut sol, terra and luna to one
clipped letter. An id with no word of its own (`gpt-5.5`) is left as it is. Never a closed list,
so it only reorders what it is given. `models.label` is the same rule, and a test holds the two
to the same answers.

### `function chipModel`

Above `function chipModel(row) {`:

Which model the pane names (#492, decision 15). The configured one as soon as it differs from
the one the newest turn was launched with -- marked `next`, because a running turn is never
interrupted and the switch applies from the next one. Otherwise what that turn reports: when it
is not what it was launched with, the tenant pinned it. A row from before `started` carried its
model (`launched` null) cannot tell those apart, and names the configured model.

### `function modelTitle`

Above `function modelTitle(row) {`:

What the model button says when you hover it: the full ids, what runs and why. Written once, and
the model card reads the same facts.

Above `if (row.external || (row.run || {}).origin === "adopted") {`:

The operator's own chat (SESS-D4, #489): what it ran, and what start fresh would run instead,
so the model button and the fresh button cannot disagree silently.

Above `if (row.effort) {`:

Each half says where it came from when they differ (#493).

### `function doRefresh`

Above `function doRefresh(repo, button) {`:

Read what the next tick would read, now. It spends NO premium request: nothing is sent to the
agent, the stream is re-folded from disk and the four cells are the poll's own reads. The button
says so while it is in flight by being the thing that is busy -- no overlay, no spinner.

Above `if (r && r.row) { patchRow(r.row); place(); }`:

What it read, drawn now (#492): the row path `/api/fleet` takes, `as_of` and all, so a
snapshot begun before the re-read cannot draw over it.

### `var modelCatalogue, modelCatalogueStale`

Above `var modelCatalogue = null, modelCatalogueStale = true;`:

The list a picker offers (#361): `/api/models`, which reads the cache and never starts the CLI.
Asked for the first time the card opens, and again only once it is stale: a `models` frame says
the list moved, or a save named an id the list did not have.

### `function loadModelCatalogue`

Above `if (modelCatalogueAsk) return modelCatalogueStale ? modelCatalogueAsk.then(loadModelCata …`:

An ask in flight answers for the list as it was when it was sent; one gone stale since asks again.

### `function modelState`

Above `function modelState(row) {`:

The inherit rule every surface that sets a model shares (#366, #493). Model and effort are two
halves, each the repository's own or else the fleet's (decision 15): `current` is what the
repository holds of its own ("" for a half it inherits), `inherited` what the fleet would give
it, and the "" pill of each toolbar is named for what that half inherits.

### `function modelWrite`

Above `function modelWrite(repo, pick) {`:

What a press writes (#493): the half its toolbar sets, and only that half -- the other keeps
what the repository holds or inherits. A `""` pill clears its own half; `inherit both` (the
model card's) clears the whole entry, as `ad-fleet model --inherit` does.

### `function modelSaidAfter`

Above `function modelSaidAfter(lead, pick, write) {`:

What the note says after a write the server took. `lead` is the surface's own first words.

### `function refreshAfterNow`

Above `function refreshAfterNow() {`:

A refresh that reads the desk as it is now: one already in flight was asked before, so it is
waited out and asked again.

### `var modelPicker`

Above `var modelPicker = null;`:

The card's picker, made once (bindModelCard). Its options are kept because the "" pill's words
are the repository's: they are set before each draw.

### `var modelCardAnchor`

Beside `var modelCardOpener = null;`:

where the keyboard was when the card opened, and goes back to

### `function modelCardRepo`

Beside `var modelCardAnchor = null;`:

the model button it hangs off, whose aria-expanded says so

### `function writeModelFacts`

Above `function writeModelFacts(repo) {`:

Configured, and what the last turn actually ran on. Two facts, because a tenant may pin a model
and a card that showed only what was asked for would be showing a value that is not what ran.

### `function placeModelCard`

Above `if (!box.width && anchor.closest && anchor.closest(".tile")) {`:

`m` on a rail (#233): its model button is off the glass, so the card hangs off the rail.

Above `var top = box.bottom + 6;`:

Under the button when it fits; otherwise level with the top of what opened it -- a rail is
the height of the window, and hanging the card off its foot put the card's foot below the
glass. Taller than the window, it starts 8px down and scrolls inside itself.

### `function focusPressedPill`

Above `function focusPressedPill() {`:

The pressed model: the first pressed pill, since the model's toolbar comes before the effort's.

### `var modelFieldBad`

Above `var modelFieldBad = null;`:

A refused name that was typed in `other…` is said on its field as well as in the note (#366):
`.bad`, and the error as its title, until a write is taken or the card opens again. The field is
the one the keyboard was in when the name was entered: the page asks the picker nothing about
its own classes.

### `function openModelCard`

Above `if (drawModelCard()) { placeModelCard(anchor); focusPressedPill(); }`:

Draw, then place (the pills are most of its height), then the keyboard on the pressed pill.

### `function closeModelCard`

Above `function closeModelCard() {`:

Closed, and the keyboard goes back where it was -- to the tile, when the button it was on has no
box any more (a pane that became a rail while the card was open).

### `var modelWrites`

Above `var modelWrites = Promise.resolve();`:

One writer for this setting: the same action, the same function and the same refusals the
settings page gets, so two ways to set one thing do not become two rules about it. One write at
a time, each worked out from the row the last one left: a model and then an effort pressed
faster than the desk answers are still that model with that effort. A refusal of what was typed
in `other…` is said on the field as well as in the note.

### `function queueModelWrite`

Above `function queueModelWrite(repo, pick, lead, say, field) {`:

The one write every surface's press makes (the model card, the dispatch card), queued behind the
last. `say` puts words in the surface's note; `field` is `other…`'s, when the name was typed.

Above `(r.rows || []).forEach(function (row) { patchRow(row); });`:

The rows the write changed came back with it (#492): drawn now, so the pane's chip says
the new model within a frame of the save, before any refresh.

Beside `modelCatalogueStale = true;`:

the list learns an id from the config it names

Above `if (modelCardRepo() === repo) writeModelFacts(repo);`:

Every surface open on the repository draws what is now true of it.

### `function bindTools`

Above `function bindTools(root, repo) {`:

One binder, bound once when the pane is made (#205).

## the row (#233)

### `function openName`

Above `function openName() {`:

Which agent is open, decided once. The window's own choice wins; then, in a window with widths of
its own (#234), the first pane those widths make wide; then the selection every window shares, so
a fresh window opens on whatever the desk is already looking at; then the first pane. A hidden or
departed name never wins -- an arrangement that opened onto nothing would be the blank window
this layout exists to stop.

```js
/** @returns {string} */
```

Above `var pinned = (getArrangement().pinned) || [];`:

A pinned agent is on the glass already, and `getEffectiveOrder` puts the pins first -- so
falling back to "the first one" would mean that pinning one agent silently stopped anything
else from ever being open. The default is the first agent that is NOT pinned.

### `function markTile`

Above `function markTile(name) {`:

The address says which agent is open, so a reload opens that one (#230). The column's own
gestures never wrote it, and `followHash` on reload re-opened whichever agent the fragment still
named -- the one before the click -- and saved it over the server's record too.

```js
/** @param {string} name */
```

### `function openPane`

Above `function openPane(name, skipPost, pressed) {`:

Open one. It takes the width the open pane had, and that pane becomes a rail in its own slot --
the column's swap, kept because it is the gesture the operator already has. Nothing moves along
the row: the order is the operator's. What was open is remembered so `Esc` can go back. A pane
that already has a width is not swapped -- pressing it only gives it the keys.

In a window with widths of its own (#234) the swap is a write of them, in the same post as
`open`: one gesture, one write. A window that has never been given widths draws the open pane
and the pins wide by themselves, so there the swap is `open` alone, as it was.

The pane that already has the keys is not swapped with itself: an address naming it -- the
`#tile=` a reload answers, a toast for the agent already open -- changes no width, or a reload
would widen the open pane a drag had made a rail. `pressed` is a hand on its rail (a press, its
number, `Enter`), which does ask for it wide.

```js
/** @param {string} name
 *  @param {boolean} [skipPost]  the record already says so: draw it, write nothing
 *  @param {boolean} [pressed]   a hand on its rail, which does ask for it wide */
```

Beside `dropUndo();`:

`Esc` is this gesture's way back, not the footer

Above `var mark = gesture("open:pane");`:

Marked inside the callback, not around the call: the view-transition path runs it on the
frame after the browser has taken its snapshot, and a mark closed before the work happened
would report nought and mean nothing (#219).

### `function backToPrevious`

Above `function backToPrevious() {`:

```js
/** @returns {boolean} */
```

## the widths (#234)

A pane's width is a weight in its window's record: 0 is a rail, a positive number its share of
what the rails leave (plan-panes §The model). A weight and not pixels, so a window made narrower
scales the wide panes and leaves the rails alone. Every change of widths is one write, through
`widthsNow`; what the row looks like is `paintWidths`', and nothing else writes a pane's width.

### `@typedef Pixels`

```js
/** How wide each pane on the glass is, in CSS pixels, by repository: what a gesture measures, and
 *  what `widthsFromPixels` turns back into weights.
 * @typedef {Object<string, number>} Pixels
 */
```

### `@typedef WidthsBefore`

```js
/** What a change of widths leaves behind to put back: the widths the window had -- null, none of
 *  its own -- and the pane that had the keys.
 * @typedef {{widths: Widths | null, open: string}} WidthsBefore
 */
```

### `function ownWidths`

Above `function ownWidths(value) {`:

Read out of a record leniently -- anything that is not a number of nought or more is not a width
-- and an empty record is none at all: the window draws as it did before it was given any.

```js
/** @param {*} value  @returns {Widths | null} */
```

### `function legacyShare`

Above `function legacyShare(name) {`:

The share a pane had before the gutters: `size.cols` as an older build wrote it, which the plan's
migration makes the weight of a pane that was wider than one column. Read, never written.

```js
/** @param {string} name  @returns {number} */
```

### `function paneWeights`

Above `function paneWeights() {`:

Every pane on the glass by name, with its weight in this window. With widths of its own, those;
without, the open pane and every pin at the share they had, and every other pane a rail -- the
row as it was before the gutters. Never all rails: a row of 48px strips with nothing open is the
blank window this desk exists to stop, so if nothing has a share the open pane is given one.

```js
/** @returns {Widths} */
```

### `function wideNames`

Above `function wideNames(weights) {`:

```js
/** @param {Widths} weights  @returns {string[]} */
```

### `function evenShares`

Above `function evenShares(weights, names) {`:

Shares scaled so that they average one, to four places. A weight means something only beside
its neighbours', and `flex-grow` under a sum of one leaves part of the row empty; the same
arithmetic on the page and in what it writes is what lets a pass with nothing new touch nothing.

```js
/** @param {Widths} weights  @param {string[]} names  @returns {Widths} */
```

### `function paintWidths`

Above `function paintWidths(weights) {`:

The one writer of a pane's width: `is-solo` (it has one) and `--w` (its share), which is all the
stylesheet reads. Written from the record on every pass and from nothing else -- except the hand,
while a gutter is held, which this is not called during (`place` waits).

```js
/** @param {Widths} weights */
```

### `function widthsWith`

Above `function widthsWith(changes) {`:

What the window keeps after a gesture: the panes it changed as it left them, and every other as
it was -- a hidden pane shown again comes back at its own width.

```js
/** @param {Widths} changes  @returns {Widths} */
```

### `function paneEdge`

Above `function paneEdge() {`:

What a wide pane's own edges take of its width -- its padding and its borders -- which
`flex-grow` does not share out: a wide pane is its edges plus its share of what is left, so a
weight read off a width has them taken away first. Read off a wide pane, because a rail has no
padding; the same for every wide pane, since one rule draws them all.

```js
/** @returns {number} */
```

Beside `if (!wide) return 24;`:

the stylesheet's own 8px 10px and 3px + 1px

### `function weightOf`

Above `function weightOf(px, edge) {`:

The weight that draws a pane this many pixels wide, beside others drawn the same way.

```js
/** @param {number} px  @param {number} edge  @returns {number} */
```

### `function widthsFromPixels`

Above `function widthsFromPixels(px) {`:

The same, from the pixel width of every pane on the glass: a wide pane's weight is its width less
its edges, so the ones a gesture did not touch keep their width to the pixel.

```js
/** @param {Pixels} px  @returns {Widths} */
```

### `function measurePanes`

Above `function measurePanes() {`:

How wide every pane on the glass is now, by name.

```js
/** @returns {Pixels} */
```

### `function swappedWidths`

Above `function swappedWidths(was, name) {`:

The swap in widths: the pane pressed takes the width of the one that had the keys, which becomes
a rail. A pane already wide keeps its width; one pressed while the pane that had the keys is a
rail itself takes an even share of the row. Nothing, in a window with no widths of its own.

```js
/** @param {string} was  @param {string} name  @returns {Widths | null} */
```

### `function saveWidths`

Above `function saveWidths(patch, before) {`:

Save a window write that may carry widths, and when the server says another page under this
window's name moved them first, put this page's gesture back and read the desk again -- so the
next gesture starts from the widths that are really there.

```js
/** @param {WindowWrite} patch  @param {WidthsBefore} [before]
 *  @returns {Promise<DeskAnswer | null | void>} */
```

### `var UNDO_FOR_MS`

Above `var UNDO_FOR_MS = 12000;`:

Every other change of widths: painted now, written once, put back with the server's words if it
is refused -- #219's order, for this window's record -- and offered back from the footer, because
a drag that went wrong should cost one press to take back, not another drag. `open` moves the
keys as well, in the same write; `how` is "layout" for the presets and the undo, which are layout
changes and go through the one door for those (#216), and nothing for the hand's own gestures,
whose preview was the real layout already.

### `function widthsNow`

Beside `var keyHome = null;`:

the pane the keyboard was on when the widths last changed

Above `function widthsNow(next, what, open, how) {`:

```js
/** @param {Widths | null} next  null: none of its own, as before the gutters
 *  @param {string} what  the gesture, which the undo names
 *  @param {string} [open]  the pane the keys go to, in the same write
 *  @param {string} [how]  "layout" for a change that goes through the one door for those (#216)
 *  @returns {Promise<DeskAnswer | null | void>} */
```

### `function offerUndo`

Above `function offerUndo(before, what) {`:

```js
/** @param {WidthsBefore} before  @param {string} what */
```

### `function undoWidths`

Above `function undoWidths() {`:

The footer's one button for it (`u`): the widths, and the open pane if the gesture moved it, as
they were before the last change -- one more write, through the same door.

```js
/** @returns {boolean} */
```

## the three presets (#234)

One segmented control where the arrangement picker was, and three keys. Each is one write of this
window's widths, and the footer's undo puts it back. Presses, not modes: nothing here holds a
pane wide or narrow once the operator's hand moves a gutter, and *needs me* hides nothing -- it
replaces the needs-only filter, which only dimmed (#207's second focus).

### `function keyboardPane`

Above `function keyboardPane() {`:

```js
/** @returns {string} */
```

### `function needsPerson`

Above `function needsPerson(name) {`:

```js
/** @param {string} name  @returns {boolean} */
```

### `function applyPreset`

Above `function applyPreset(which) {`:

```js
/** @param {string} which  "one", "all" or "needs"  @returns {boolean} */
```

Above `if (!shown.length || gutterHeld) return false;`:

Not while a gutter is held: the hand's own write comes when it lets go, and would undo this.

Above `var one = keyboardPane() || openName();`:

The pane the keyboard is on, else the open one: wide, and every other a rail.

Above `shown.forEach(function (name) { next[name] = 1; });`:

An even share each; the tiers decide what that looks like on this glass.

Above `var here = openName();`:

The keys go with the width: to the pane that had them if it is one of these, else the first.

## the gutters (#234)

A 1px line between every two panes on the glass, with an 8px hit area laid over their edges, so
it costs no width. Dragging one moves width between the two panes beside it and nothing else:
every other pane stays exactly where it is, which is what makes a resize predictable. The drag
IS the preview -- #217's ghost was there because a span snapped on release and the hand could not
see where it would land -- so while it is held the page writes those two panes' widths, once a
frame, and nothing else: no `place()`, no redraw, no reorder (plan-panes ground rule 4). One write
when the hand comes up; `Esc` puts the widths back with nothing written.

### `var SNAP_PX`

Beside `var RAIL_SNAP_PX = 120;`:

a pane dragged under this settles to a rail

### `var GUTTER_STEP_PX`

Beside `var SNAP_PX = 8;`:

how near a snap takes the hand

### `var gutterHeld`

Beside `var GUTTER_STEP_PX = 40;`:

one press of Alt+Shift+arrow

### `@typedef GutterHold`

```js
/** A gutter under the hand: the two panes beside it, where the drag began (`x`, `a0`), the left
 *  pane's width now (`a`) and as last painted, what the two hold between them (`total`), every
 *  pane's width as the drag began (`px`), and the frame that will paint it.
 * @typedef {Object} GutterHold
 * @property {HTMLElement} left
 * @property {HTMLElement} right
 * @property {number} x
 * @property {number} a0
 * @property {number} total
 * @property {number} a
 * @property {number} painted
 * @property {Pixels} px
 * @property {number} edge     what a wide pane's padding and borders take (`paneEdge`)
 * @property {number} frame    the animation frame asked for, or 0
 * @property {boolean} lifted  whether the other wide panes were pinned to their pixels yet
 */
```

### `var placeWanted`

Beside `var gutterHeld = null;`:

the drag in flight

### `function onGlass`

Beside `var placeWanted = false;`:

a pass asked for while it was

Above `function onGlass(el) {`:

```js
/** @param {HTMLElement} el  @returns {boolean} */
```

### `function nextOnGlass`

Above `function nextOnGlass(el) {`:

```js
/** @param {HTMLElement} el  @returns {HTMLElement | null} */
```

### `function settlePair`

Above `function settlePair(a, total) {`:

Where the pair can come to rest, given how wide the two are together. The same rule on both
sides: a pane is a 48px rail or at least the compact minimum, and one pulled under 120px settles
to the rail. Two panes that together cannot hold two compact ones have two states, and the
nearer wins.

```js
/** @param {number} a  @param {number} total  @returns {number} */
```

Beside `if (total < RAIL_PX + TIER_COMPACT_FROM) return RAIL_PX;`:

two rails: nowhere to go

### `function snapPair`

Above `function snapPair(a, total) {`:

And while the hand is on it, the places worth landing on take it within 8px: either side at the
compact or the full minimum, and an even share with the neighbour.

```js
/** @param {number} a  @param {number} total  @returns {number} */
```

### `function stepPair`

Above `function stepPair(a, total, dir) {`:

One press: 40px, and out of a rail or into one in a single step, because a rail cannot be 88px
wide and a press that did nothing would read as a key that does not work.

```js
/** @param {number} a  @param {number} total  @param {number} dir  @returns {number} */
```

### `function paintHeldWidth`

Above `function paintHeldWidth(el, px, edge) {`:

One pane's width while the hand has it, in pixels. Every wide pane's share was made its width
less its edges when the drag began, so the shares add up to what the rails and the edges leave,
and a width written this way is the width drawn.

```js
/** @param {HTMLElement} el  @param {number} px  @param {number} edge */
```

### `function paintHeld`

Above `function paintHeld() {`:

The frame: the two panes' widths, and nothing else (#217's lesson -- a draw in the middle of a
drag no longer puts the gesture down).

### `function bindGutter`

Above `function bindGutter(gutter, el) {`:

```js
/** @param {HTMLElement} gutter  @param {HTMLElement} el */
```

Above `e.preventDefault();`:

No text selected across two panes, no focus moved, and nothing under the gutter told.

Above `try { gutter.setPointerCapture(e.pointerId); } catch (err) { }`:

Captured on the press: a gutter has no click of its own to lose to the capture, and the hand
leaves an 8px strip on the first pixel of travel.

In `try { gutter.setPointerCapture(e.pointerId); } catch (err) { }`:

synthetic pointer

In `finish`, in `try { gutter.releasePointerCapture(e.pointerId); } catch (err) { }`:

already released

Above `var onMove = function (ev) {`:

```js
/** @param {PointerEvent} ev */
```

Above `var onUp = function (ev) {`:

```js
/** @param {PointerEvent} ev */
```

In `onUp`, above `if (ev && typeof ev.clientX === "number") {`:

Where the hand came up, which is not always where the last move said it was: an engine
that coalesces moves to the frame can deliver the release before the move that got there,
and the width then lands one step short of the pointer (Windows CI on #270: 45.8px of a
50px drag, eleven of its twelve steps). The release carries the position; it is the one
that counts.

In `onUp`, beside `if (Math.abs(held.a - held.a0) < 0.5) { place(); return; }`:

a press is not a resize

In `onUp`, above `swallowNextClick();`:

The release's `click` lands on whatever the hand ended over once the capture is gone --
or, in an engine with no capture at all, on the pane under it -- and a pane's click
selects the project for every window. A resize is not that.

Above `var onKey = function (ev) {`:

`Esc` puts the widths back and writes nothing. Captured on the document, because the capture
has taken the keyboard's usual route away and the page's own `Esc` would go back a pane. The
button is still down, and the click its release ends in is not a click on a pane either
(#233's lesson from the reorder drag), so that one is swallowed too.

```js
/** @param {KeyboardEvent} ev */
```

Above `gutter.addEventListener("click", function (e) { e.stopPropagation(); });`:

The press and the release are the gutter's: not the pane's click (which selects the project for
every window) nor its double click (which opens it). Two clicks here even the pair out instead.

### `function evenGutter`

Above `function evenGutter(el) {`:

The double-click, and `Alt+Enter` on the pane to its left: the two panes beside a gutter get an
even share of what they hold between them. Two that cannot both be compact are left alone.

```js
/** @param {HTMLElement} el  @returns {boolean} */
```

### `function stepGutter`

Above `function stepGutter(el, dir) {`:

`Alt+Shift+←/→` on a pane: its right-hand gutter, one step (#217's width keys, now the gutter's).

```js
/** @param {HTMLElement} el  @param {number} dir  @returns {boolean} */
```

### `function openBeside`

Above `function openBeside(name) {`:

Shift and a rail: open it beside the pane that has the keys, the two splitting what that pane
had and the rail's own 48px, so nothing else in the row moves. The keys stay where they were. A
rail pressed while the pane with the keys is itself a rail is simply opened.

```js
/** @param {string} name */
```

### `function drawGutters`

Above `function drawGutters() {`:

Which gutters show: one on the right of every pane on the glass but the last. Written on every
pass, guarded, so a pass with nothing to change touches nothing.

### `var departed`

Above `var departed = new Map();`:

Repositories that left the registry. Their pane goes, but each leaves a rail naming the command
that restores it (#173), because a transcript disappearing with no explanation is exactly the
"where did it go" the row exists to answer.

### `function ageOf`

Above `function ageOf(row) {`:

```js
/** @param {Row} row  @returns {number} */
```

## the pane's three widths (#233)

One component, three widths (plan-panes §The pane). What a pane draws is decided by how wide it
is, and how wide it is by the arrangement: open panes share the row by weight, every other one is
a 48px rail. `data-tier` is the one bridge between the two, and it has one writer.

### `var TIER_COMPACT_FROM`

Above `var TIER_COMPACT_FROM = 160;`:

The boundaries, in CSS pixels of the pane's border box. These are CI's, and the defaults: 360 is
the grid's narrowest tile as it was, and 160 the narrowest a head and a reply box can share. The
operator's own come from `fleet.tiers.*` (#235) through `applyTiers` below. The rail's width is
`--rail` in app.css; `RAIL_PX` and the two after it mirror the stylesheet for the one sum that
decides whether the rails still fit (`groupRails`).

### `var TIER_DEFAULTS`

Above `var TIER_DEFAULTS = { rail: RAIL_PX, compact: TIER_COMPACT_FROM, full: TIER_FULL_FROM,`:

The four as the operator set them after trying them on the real monitors (#235): `fleet.tiers.*`
in config.json, from the settings page. They come with the theme -- `/api/fleet`, the stream's
`theme` frame when the file changes, and the snapshot a reload draws first -- so a change reaches
this desk on the next tick, with no reload and nothing written. The server has already refused
any four that do not go together, and sends CI's with `invalid` saying why when the file holds
one anyway, so all this checks is that it was handed numbers in order.

The stylesheet needs two of them -- the rail's width, and the floor a pane with a width never
goes under -- and they are written on the root only when they are not CI's, so a desk on the
defaults carries nothing for them. A boundary that moved under a pane that did not is a change
the observer never hears of, so every pane already measured has its tier taken again at the
width it has.

### `function applyTiers`

Above `function applyTiers(t) {`:

```js
/** @param {Tiers | null | undefined} t */
```

Beside `if (!entry.el.dataset.tier) return;`:

not measured yet: the observer's first report

### `function paneTier`

Above `function paneTier(width, was) {`:

Which tier a width is, remembering which one the pane was in. A pane leaves its tier only once
it is 8px past the boundary, so a pane sitting on 360 -- a window edge being dragged, a scrollbar
coming and going -- does not redraw itself between two tiers on every frame.

Not at the rail's boundary (#234). A pane is a 48px rail or at least 160px wide -- the
stylesheet's floor for a pane with a width, and the compact minimum a gutter settles on -- so
nothing ever sits on that boundary to flicker across it, and the slack that was there drew a rail
pulled out to exactly the compact minimum as a rail's face stretched 160px wide.

```js
/** @param {number} width  @param {Tier | ""} [was]  @returns {Tier} */
```

### `function setTier`

Above `function setTier(el, width) {`:

The one writer of `data-tier`. It answers whether the tier changed, because a change is a
redraw: a narrower tier skipped drawing what it does not show.

```js
/** @param {HTMLElement} el  @param {number} width  @returns {boolean} whether it changed */
```

### `function entryWidth`

Above `function entryWidth(entry) {`:

The border box, which is what the tiers are measured in and what `flex-basis` sets.

```js
/** @param {ResizeObserverEntry} entry  @returns {number} */
```

Beside `var first = (box && (box[0] || box));`:

a bare one, in old engines

### `function onRowResize`

Above `function onRowResize(entries) {`:

One observer on the row: the row itself, for whether every rail still fits, and every pane in
it, for its tier. A pane whose tier changed is drawn again from the row it already has, in the
same frame, so what the narrower tier skipped is there before anything is painted. A pane taken
off the glass -- hidden, or folded into its project's rail -- measures nought and keeps the tier
it had, rather than being called a rail it is not.

```js
/** @param {ResizeObserverEntry[]} entries */
```

Above `if (keyHome && redraw.indexOf(keyHome) >= 0) {`:

The keyboard stays on the pane it was on when a change of widths carries that pane across a
tier (#234). A rail's stop is its face and a wide pane's is the pane itself, so the face a
rail had goes `display: none` the frame it is widened -- and would take the keyboard with it,
leaving the next `Alt+Shift+→` addressed to nothing.

### `function watchPane`

Above `function watchPane(el) {`:

```js
/** @param {HTMLElement} el */
```

### `function forgetPane`

Above `function forgetPane(el) {`:

```js
/** @param {HTMLElement} el */
```

### `function measureRow`

Above `function measureRow() {`:

An engine with no `ResizeObserver` -- none of the three the desk runs in, as #235 will record,
but a page that cannot tell a pane's width must still draw one -- gets the same writer, fed by a
measurement after every layout pass and on every resize of the window.

## when even the rails do not fit (#233)

A project's checkouts share one rail -- but only when the row cannot hold every rail it has, at
about thirty agents on a 1440px window (plan-panes §Open questions; D's default is to group). It
is the answer that keeps every agent on the glass: a row that scrolled sideways would put the one
that needs you past its edge, and the dock grouped checkouts the same way (#175). The first
checkout of a project, in the row's order, is the head; the others fold into its rail. Past
grouping the row scrolls, which is the last resort and not the design.

### `var groupedInto`

Beside `var railGroups = new Map();`:

head -> [head, member...], only while grouping

### `function groupRails`

Beside `var groupedInto = new Map();`:

member -> head, for every member but the head

Above `function groupRails(shown, open) {`:

```js
/** @param {string[]} shown  @param {string[]} open */
```

Above `var need = ROW_PAD_PX + open.length * TIER_COMPACT_FROM + rails.length * RAIL_PX +`:

Measured against every rail, never the grouped count, so grouping cannot talk itself out of
being needed on the next pass and flicker.

### `function groupedAway`

Above `function groupedAway(name) {`:

```js
/** @param {string} name  @returns {boolean} */
```

### `function railTarget`

Above `function railTarget(name) {`:

Where a press on a rail goes: the agent itself -- or, on a project's shared rail, the first of
its checkouts that needs a person, then the first one. The red is why the operator pressed it.

```js
/** @param {string} name  @returns {string} */
```

## the rail (#233)

### `var RAIL_GLYPHS`

Above `var RAIL_GLYPHS = {`:

The glyph a rail wears for a state. Its shape says what its colour says, so neither is alone: a
colour is not a signal on a bad monitor at arm's length, and not at all to somebody who cannot
tell the two apart. A project's shared rail wears its count instead.

### `function railLine`

Above `function railLine(row) {`:

One agent, in the words a rail cannot fit: who, in what state, since when, what it has cost,
what is unread, and the last thing it said -- or, when it needs a person, what it is asking.

```js
/** @param {Row} row  @returns {string} */
```

Above `if (freshShown(row)) bits.push(row.fresh.because);`:

#489: why this pane offers *start fresh*, and the key that does it.

### `function drawPaneRail`

Above `function drawPaneRail(el, row) {`:

The rail's face: the name down its length, the state's glyph in the state's colour, the unread
count, and the whole of it red when the agent needs a person. The age and the last line are its
accessible name and its title. Drawn on every pass whatever the tier -- it is a handful of
guarded writes -- so a pane that narrows to a rail is already right. It owns the face's `class`
and nothing on the pane around it.

```js
/** @param {HTMLElement} el  @param {Row} row */
```

Above `var fresh = !members && freshShown(row) ? (row.fresh.because === "old skills" ? " is-sta …`:

A dashed muted ring on the glyph when this pane offers *start fresh* (#489): never a state colour.

## the whole window

### `function place`

Above `function place() {`:

The one function that decides what this window shows. The stylesheet is the layout, and there is
one arrangement (#232), so all this writes is how wide each pane is (#234), which one is
selected, which rails are folded into their project's, and which gutters show. What each pane
draws at its width is the observer's (#233).

Not while a gutter is held (#234): the hand is writing two panes' widths once a frame, and a pass
from the stream in the middle of that would put the record's widths back under it. The pass is
run when the hand comes up.

### `function drawHiddenCount`

Above `function drawHiddenCount() {`:

Where a hidden agent went (#233): it left the row, and the footer says how many have. One press
brings every one of them back, each to its own slot. An agent that needs a person is never
counted, because it is never put away (`isHidden`).

### `function drawGone`

Above `function drawGone() {`:

The rails of repositories that left the registry, after the row. Patched, never rebuilt, like
every list on this page.

### `var saidLine`

Above `var saidLine = "";`:

The footer's one line, and one owner (#173).

`place()` runs several times a second while the stream is talking, and it used to clear this
element on every draw -- so a message written by anything else lived a few milliseconds and the
operator never saw it. A line said here holds the footer for its few seconds, and the footer
goes quiet again when they pass.

### `function say`

Above `sayTimer = setTimeout(function () { sayTimer = null; drawNotice(); }, (seconds || 6) * 1 …`:

The stream usually redraws long before this, but a quiet fleet does not -- and a footer that
keeps saying "reopened" ten minutes later is worse than one that says nothing.

## fresh sessions (#240, #241)

Skills are read when a session begins, so an `ad-update` that changed one leaves every running
session on the old text. The server judges each row against what is installed now, on every
snapshot; the page only says so -- a chip on the tile, and a header button that previews what a
renew would do before anything runs.

### `function drawRowLines`

Above `function drawRowLines(server) {`:

The renew and day lines, from the rows the panes show, with every row that lands (#530). Drawn
only from a snapshot, the day line went a beat after an adopt's answer and moved the grid under
the next press; and a snapshot that `readBefore` kept off its pane still counted that pane.

### `function drawRenewStrip`

Above `function drawRenewStrip(rows, server) {`:

One line for as long as anything is stale; the preview only when asked for. Collapsed, the
sentence is the count; open, it is the plan's own summary, which the next frame must not undo.

Above `var oldDesk = !!(server && server.current === false);`:

The desk itself can be the stale thing (#242): a server started before `ad-update` goes on
serving the code it loaded. The server judges it; this only repeats the sentence.

### `function drawRenewPlan`

Above `var li = (strip.querySelector(".renew-pattern").cloneNode(true));`:

Cloned from the markup's own pattern row, so the two cannot disagree about the parts.

## a fresh day (#508, #511)

The morning: one line while idle panes with a ticket are on sessions that began before today, and
the preview of `ad-fleet fresh --all` behind it, `Shift+N` or the *day* menu. The preview is the
only thing any of them posts (`{all: true, dry_run: true}`), and `?fresh=1` is one more way to ask
for it -- an address can come from anywhere, so it never confirms anything (DAY-D4). Only `daygo`
posts `repos`: the ones ticked here.

### `function morningPanes`

Above `function morningPanes(rows) {`:

Idle panes with a ticket in progress, on sessions that began before today: what the line counts.

### `function drawDayOffer`

Above `function drawDayOffer(rows) {`:

The one-line offer, drawn only when its count changes: an idle desk writes nothing.

### `function countDay`

Above `function countDay() {`:

`#daygo` names what it spends: one premium turn per ticked agent (DAY-D2).

### `function dayModelTitle`

Above `function dayModelTitle(st) {`:

The model column in `modelTitle`'s words: the label, and where each half came from (#493).

### `function drawDayPlan`

Above `var li = (strip.querySelector(".day-pattern").cloneNode(true));`:

Cloned from the markup's pattern row, so the two cannot disagree about the parts.

Above `if (li.dataset.plan !== plan) { box.checked = tickable && !!r.ticked; setData(li, "plan" …`:

Ticked as the plan says, once per plan: a redraw never undoes the operator's own tick.

### `function previewFromAddress`

Above `function previewFromAddress() {`:

`?fresh=1` (`ad-fleet serve --open --fresh`, `open --fresh`): the preview, once, and the parameter
comes off the address so a reload does not open it again. It posts the preview and nothing else.

### the closure › `if (nope) nope.addEventListener("click", function () {`

In `try { localStorage.setItem(DAY_NOT_TODAY, localDay()); } catch (e) { }`:

a private window: just this page

### `function forgetRetiredParams`

Above `function forgetRetiredParams() {`:

An address that still chooses an arrangement (#232): a bookmark, an older launcher, or a shell
built before there was only one. The desk opens as it always does, the footer says once that
the parameters meant nothing, and they come off the address -- so a reload does not say it a
second time, and the address the operator copies says only true things.

### `function title`

Above `function title(need) {`:

The tab bar is the friction, so the window's own title says which agent it has open.
`document` is not an element, so `attr` threw here on every refresh (#262): the tab never said
who needs you, and `refresh()` ended in its own catch. The one write that is not an attribute,
done directly -- and only when it changes, as `attr` would have.

### `function paneStops`

Above `function paneStops() {`:

Where the keyboard stops along the row (#233): a rail's face, or an open pane itself. In the
row's order, and only what is on the glass, so `j` never lands on something nobody can see and
the digits count exactly the panes there are.

```js
/** @returns {HTMLElement[]} */
```

### `function stepRow`

Above `function stepRow(dir) {`:

`j` and `k` walk the row. A rail's stop is a real button, so `Enter` opens it, and there is no
second model of "which one is selected" to disagree with what is on the glass.

```js
/** @param {number} dir */
```

### `document.addEventListener("click", /** @type {(e: MouseEvent & {target …`

Above `if (e.target.closest && (e.target.closest(".smenu") || e.target.closest(".spill"))) retu …`:

One menu open at a time, and a click off it closes it -- the rule every popover here keeps.

### the closure › `document.getElementById("mc-inherit").addEventListener("click", functi …`

Above `document.getElementById("mc-inherit").addEventListener("click", function () {`:

Both halves back to the fleet's at once (#493): the whole entry goes.

### the closure › `card.addEventListener("keydown", function (e) {`

Above `card.addEventListener("keydown", function (e) {`:

Every key but Escape stays in the card (#366): `j` on a pill is not the desk's `j`, and `h` is
not a hide. Escape goes on to the document, which closes the nearest open thing -- this card.

### the closure › `document.addEventListener("click", /** @type {(e: MouseEvent & {target …`

Above `document.addEventListener("click", (function (e) {`:

A click anywhere else closes it, the way it closes a popover.

Above `if (e.target.closest && e.target.closest(".mp-more")) return;`:

`more…` on the dispatch card opens this card, and its click must not close it again (#368).

## the popovers: the key map behind `?`. The pickers that used to sit beside it are a page of

their own now (`/settings`), so this map has one entry -- and keeps its shape, because "one open
at a time" is the rule whatever is open.

### `function popover`

Above `var hadTheKeyboard = !!(document.activeElement && box.contains(document.activeElement));`:

Read before hiding: a hidden element cannot hold the focus.

Beside `button.focus();`:

the keyboard goes back where it came from

### `document.addEventListener("keydown", function (e) {`

Beside `if (e.key === "N" && e.shiftKey) { openDay(); return; }`:

#511: a fresh day, previewed

Above `if (e.key === "1") { applyPreset("one"); return; }`:

The three presets (#234), and the footer's undo of whichever widths changed last.

Beside `if (e.key === "g") { location.href = pageUrl("/map"); return; }`:

#407

### `var st`

Above `var st = servedTiers();`:

#219: the desk that was, while the desk that is loads. At the very bottom of the file and not
beside the `refresh()` that starts the fetch, because drawing a row touches module state --
`departed`, the tiles map -- that is declared further down and is `undefined` until the script
has finished evaluating. The fetch is already in flight either way; this only decides what is
on the screen while it is.

### `if (st) applyTiers(st);`

Beside `var st = servedTiers();`:

#345: the widths the server wrote, before a pane is drawn

### `forgetRetiredParams();`

Above `forgetRetiredParams();`:

Last for the same reason: `say` writes the footer's state, which is only set up once the script
has run past it.
