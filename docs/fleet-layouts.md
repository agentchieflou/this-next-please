# One arrangement: the layouts, and how there came to be one

> **Decided, 2026-09-22: one arrangement.** #133 built three arrangements so one could be chosen against the
> real monitors, and #200 added a fourth, `column`, which the operator chose that morning. Later the same day
> the operator retired the choice itself, in these words:
>
> *"I don't really know what purpose 'roles' and 'screens' are serving anymore. It almost feels like we only
> really need the 'grid' option, and just that its design features need to be hardened."*
>
> [plan-panes.md](plan-panes.md) (#229) is the plan that followed, and its slice C (#232) is what landed here:
> **the page has one arrangement**, `LAYOUTS` is gone from all three places that kept it, and the picker in
> the header went with it. Slice D (#233) then drew the one arrangement as the operator meant it: every
> agent a pane in one row. §The sitting below keeps the history of how the choice was made.

## What the one arrangement is

What the operator called *the grid* is not the grid that shipped — wrapping cards with a zoom and a dock
under them — and it is not the column either. It is **a row of panes**, one per agent, each at full height
with a width of its own ([plan-panes.md](plan-panes.md) §Where this plan pushes back, item 2), and since
slice D (#233) that is what the page draws: the open agent and every pinned one share the width, every other
agent is a 48 px **rail**, and each pane draws itself by its own width — rail, compact or full.
[fleet-dashboard.md](fleet-dashboard.md) §The row has the rest. Resizing it by hand is slice E (#234).

Before D it was the column's drawing (#203): one agent open at full height, pinned agents open beside it, and
every other checkout a **band** in a column down the side. The bands, the column and `drawColumn`/`drawBand`
went with D, and a compact pane carries what a band did. Slice C took the other three arrangements away
first, so that D replaced one drawing rather than four:

* **the grid's zoom** (`zoomed`, `body.focused`, *back to grid*) went. In the column, opening an agent is
  what zooming was, and a `zoomed` left in the window record is what snapped a click back to the agent
  before it (#230).
* **the dock** (#173) went. It answered *where did that tile go* for the grid; in the row a hidden agent
  leaves the row and the footer counts it (one press brings it back), and one that left the registry is a
  rail saying how to bring it back.
* **the resize edges** of #217 went. They snapped a tile to the grid's `auto-fit` tracks, and there is no
  wrap of tracks left to snap to. The gutters between panes replaced them and `size` both (#234): a
  pane's width is a weight in its window's own record, and `Alt+Shift+←/→` moves a gutter.
* **roles** and **screens** went, with the `window` segments in the header, the second segment that named
  which window of a set this was, and the swap select.

The needs-only filter (`f`) stayed through C and D: it was not an arrangement. E made it the *needs me*
preset (#234) -- one write of the window's widths, every agent that needs a person wide and the rest
rails -- which hides nothing and dims nothing.

## An address or a flag from before

Nothing that used to work lands on a blank page.

* `?layout=`, `&view=` or `&screen=` in an address — a bookmark, an older launcher, an IDE shell built before
  this — opens the desk as it always opens. The footer says once that the parameter is ignored, and the
  page takes it off the address, so a reload does not say it again and the address the operator copies says
  only true things.
* `ad-fleet serve --layout …`, `ad-fleet quickstart … --layout …` and `ad-fleet hide|unhide --layout …` are
  still accepted, for one release, and change nothing. The `note` in their `meta` says so. The release after
  removes the flag.
* `ad-fleet open --in edge` opens the window named `edge` unless `--window` names another, so an Edge window
  on a fourth monitor has a record of its own instead of following every click in the browser tab (#230).

## `desk.json`, schema 2

```
~/.agentdata/fleet/desk.json            "schema": 2
  version                               the only-ever-rising counter every write bumps
  selected                              the project the inspector follows, shared by every window
  arrangement:  { order, hidden, pinned, size }       ONE record, shared by every window
  windows:
    <w>:  { open, focus, read, seen, held, section }  one per window (#172)
```

Schema 1 had one arrangement per layout under `arrangement.column`, `.grid`, `.roles` and `.screens`, a
`screens` list for the per-monitor pinning, and `layout`, `view`, `screen` and `zoomed` in every window record.
Those are the fields four arrangements wrote into one record, and two of them disagreeing is the snap-back.

**The migration** runs by itself, once, the first time the server reads a `desk.json` with no `"schema": 2`
in it:

1. The file is copied, byte for byte, to `desk.v1.json` beside it, in the fleet directory. If that copy
   cannot be written, `desk.json` is not rewritten by the migration.
2. The arrangement comes from `arrangement.column` if the old file has one, else from `arrangement.grid`,
   because `ad-fleet hide` wrote to `grid` whatever the page showed. `order`, `hidden`, `pinned` and `size`
   come across as they were, `size: 2` read as `{cols: 2, rows: 1}` the way it always has been.
3. Each window keeps `open`, `focus`, `read`, `seen`, `held` and `section`. `zoomed`, `layout`, `view` and
   `screen` are dropped. `zoomed` is **not** turned into `open`: it is the stale field the snap-back came
   from.
4. `screens` is dropped. `selected` stays, because the inspector reads it.
5. `version` rises by one and `desk.json` is written as schema 2.

To go back to a build from before #232, stop the server and put `desk.v1.json` back as `desk.json`.

## Focus mode — not a layout (`f`)

**Show only the agents that need a person.** The alternative to organising tabs is having fewer things to
look at.

* `f` toggles it; the button in the header shows the state. It is remembered in the window's record, so the
  left monitor can stay in it while the centre one does not.
* "Needs a person" is #94's fold — `needs_human`, `waiting_approval`, `blocked`, `error` — not a guess made
  in the page. See [fleet-events.md](fleet-events.md).
* It quiets the row rather than emptying it: a rail whose agent wants nothing dims, still named, still
  counted and one press away (it folded a band to a sliver in the column). It never quiets an open pane,
  which is the window.
* An agent the operator has just acted on is **held** through the pass, so a reply does not dim the rail it
  was typed into.

The rest of the keyboard is in [fleet-dashboard.md](fleet-dashboard.md) §Keyboard.

## Hidden tiles — the operator's own arrangement (`h`) (#173)

Focus mode decides for you; **hiding** is you deciding. `hidden` is a list beside `order`, `size` and
`pinned` in the one `arrangement`, so it is the server's and every window on this fleet agrees on it — an
agent put away on the laptop is put away on the wall screen too, and it is still put away tomorrow.

* `h` hides the agent the keyboard is on, a rail as well; the hide button on an open pane's head does the
  same with a mouse.
  `ad-fleet hide <repo>` and `ad-fleet unhide <repo>` do it from a terminal, and print the list.
* A hidden agent **keeps its slot in `order`**, so reopening it puts it back between the two it was between
  rather than at the end.
* **An agent that needs a person is on the glass whatever `hidden` says.** Hiding a demand is how a demand
  gets missed, and it is the one rule the operator's own arrangement does not get to override.
* A hidden agent leaves the row, and the footer says how many are hidden; a press on that empties the list.
* `#tile=<repo>` — the anchor the Windows toasts and both IDE shells use — reopens a hidden agent and says so
  in the footer.

`hidden` and `pinned` are per **project**: two `git worktree` checkouts of one repository are one piece of
work, and putting half of it away — or pinning half of it first — is an arrangement nobody asked for.
Expanded on the server, so `ad-fleet hide` and every open window agree by construction, and a name the
registry no longer knows keeps its place rather than being dropped from the desk.

## What is shared between windows, and what is not

| Thing | Where it lives | Why |
| --- | --- | --- |
| the selected project | the server, pushed on the stream | the inspector on every screen follows it |
| the arrangement: order, hidden, pinned (and an older build's `size`, only read) | the server | one desk: the same agents in the same order on every screen |
| which agent is open, the widths, what was read | the window's record on the server (`?w=`) | the left monitor reads one agent while the centre reads another, and holds its own widths over the same order (#234) |
| theme, chime | that browser's `localStorage` | one operator, one habit |

A window is named by `?w=`. A plain browser tab is `main`; the PyCharm tool window asks for `pycharm`, the VS
Code view for `vscode`, and `ad-fleet open --in edge` for `edge`, so the shells do not follow each other's
clicks (#230).

One process, one poller. Four windows on four screens are four SSE connections to the same
`ad-fleet serve`, and the poller, the inbox watcher and the catalogue handle are held once for the
process — otherwise the Jira poll would multiply by the number of monitors somebody happens to own.

## What there was before: four arrangements (#133, #200)

The friction #133 set out to fix is not the number of monitors. It is **one tab per system per project**:
eight bookmarks on the centre screen, a ticket on the right, a terminal on the left, Downloads on the laptop —
times N projects. Every arrangement was the same page, the same DOM and the same stylesheet, chosen by
`?layout=`, and `ad-fleet serve --layout grid` put the parameter on the URL it printed.

* **A — grid** (`?layout=grid`): every registered repository a tile, wrapping; a repo name or `1`–`9`
  zoomed one to fill the window and `Esc` came back; a dock of chips under the tiles for whatever was off
  the glass. It shipped as the default pending the sitting.
* **B — roles** (`?layout=roles&view=agents|verify|board`): three windows, one per monitor, agreeing on one
  selected project through the stream — the tiles on the left, the selected project's links and verify pane
  in the centre, the Jira board and the tray on the right.
* **C — screens** (`?layout=screens&screen=N`): one project filling each monitor, with a swap select that
  moved a project off whichever screen held it; `screens` with no number was the laptop's board and tray.
* **D — column** (`?layout=column`, #200): one tile open at full height and every other checkout a band in
  a column beside it. The operator chose it on 2026-09-22, and it is the drawing the one arrangement kept.

## The sitting

Kept as it was written, as the record of how the first choice was made. The commands in it predate the
one arrangement: they still run, and `--layout` in them is now ignored with a note.

Bounded on purpose: one real remediation afternoon, four repositories registered by
`ad-fleet repo add --scan`, real tickets, fixture agents if the org policy still blocks real ones
(#92). Run each arrangement long enough to do actual work in it, then fill this in **before** any
layout-specific code is written.

```bash
ad-fleet quickstart C:/Users/you/PycharmProjects --layout grid
ad-fleet serve --layout roles
ad-fleet serve --layout screens
```

**Photographs.** One per arrangement, on the four real screens. A phone photo is right — this whole
epic exists because of one. Attach them to issue #133 and link them here.

| | A — grid | B — roles | C — screens | D — column |
| --- | --- | --- | --- | --- |
| Photograph | two, 2026-09-11, described below (#179) | one, 2026-09-11, described below (#179) | _none yet_ | one, 2026-09-22, described below (#200) — of the grid, and what it asked for |
| Minutes spent in it | _not recorded_ | _not recorded_ | | _not recorded_ |
| What was opened **outside** the dashboard, and why | _not recorded_ | _not recorded_ | | _not recorded_ |
| Screen hops (roughly, per hour) | _not recorded_ | _not recorded_ | | _not recorded_ |
| What the cursor did most | _not recorded_ | _not recorded_ | | _not recorded_ |
| Was focus mode used? When? | _not recorded_ | _not recorded_ | | _not recorded_ |
| What was worse than the tab shuffle | _not recorded_ | _not recorded_ | | _not recorded_ |

**The photographs of 2026-09-11** (#179) are described rather than committed: they carry a tenant's
ticket keys and summaries, the same reason the fake `copilot`'s transcripts are synthesized. They
were phone photographs of the live desk with five agents on real tickets, and they are what
[plan-sitting.md](plan-sitting.md) was written from:

- **A, the grid in `farmstead:daytime`:** five tiles across one window; the toolbar wrapped to two
  rows and the key map to two lines under the grid; a blank square beside every pin (the hide
  toggle); Windows' grey scrollbars on every transcript.
- **A, the grid with the sidebar open in `glass:smoke`:** the same grid with the project section
  open; the panes a flat blue-grey with nothing behind them for a blur to show.
- **B, the board window (`?layout=roles&view=board`) in `glass:frost`:** the Jira board alone, five
  *start on X* buttons per row and nothing to drag a ticket onto; the panes a flat cream.

**The photograph of 2026-09-22** (#200) is described rather than committed, for the same reason: it
carries a tenant's ticket keys and repository names. It is a phone photograph of the live desk in Chrome on
the laptop, in a dark pixel-block skin, five agents on real tickets:

- **A, the grid with one tile open and four in the dock:** the open tile at the left third of the window — an
  adopted console session (*a session outside the fleet is driving this repo — matched by session file*), a
  turn in progress, an amber git cell reading *7 branches · 5 never reached master*, tool calls scrolling; the
  other two thirds of the window black but for the dock's four chips, each a full-width bar because its ask
  text is long, under *4 not on the glass* and above *show all*; the footer *5 agents · 3 need you*. The
  operator's sentences about it are in [plan-column.md](plan-column.md) §Why this exists and §Decisions.

The rows above that say _not recorded_ are the operator's to fill on the real screens; a
photograph shows an arrangement, not the minutes spent in it or the tabs opened beside it. Slice
F of #179 records what the photographs showed and no more.

The `column` rows are _not recorded_ rather than _not built yet_ since #208: the arrangement
exists and the default has moved, and what is still owed is an afternoon spent in it. The
questions it is expected to answer are the open ones in [plan-column.md](plan-column.md)
§Open questions -- the column's width, the band's minimum, and whether a band that turns red
should rise to the top or keep its slot, which ships as *keep its slot*.

**The decision** (write it here and in #133, with the reasons, before changing the default):

> _Chosen layout:_ **`column`** — a fourth arrangement, not one of the three built for #133. Decided by the
> operator on 2026-09-22 from the photograph described above, in conversation, and confirmed when asked
> whether that message was the decision this page reserves for them: *yes, column is the default*, grid still
> reachable by URL. Recorded here and in #133 before any layout code, as this page requires.
>
> _Why:_ the operator's words — *I would much rather prefer non-open sessions to show vertically rather than
> horizontally. Each slice that isn't being actively looked at should auto size to take up the page so there
> isn't so much negative space.* Asked what "vertically" meant — a column of bands, side-by-side strips or a
> left rail — the answer was **a column of bands** that stack beside the open tile and share the full page
> height.
>
> _What the other two would have to fix to be worth keeping:_ not recorded — the operator was asked only
> about the column. The grid's own findings are on the record (nothing sizes to the viewport; the dock has no
> flex basis) in [plan-column.md](plan-column.md) §Why this exists; `roles` and `screens` were not discussed.
>
> _Focus mode: kept / dropped, and why:_ kept, as *needs me*; in the column it folds a quiet band to a sliver
> rather than hiding it, and the zoom becomes *open* ([plan-column.md](plan-column.md) slice E). Not the
> operator's words — a plan default the sitting corrects.

> **Nothing above has been filled in yet, and no code may act as though it had.** On 2026-09-08 an
> agent wrote a decision into this page — a chosen layout, minute counts, screen-hop rates,
> photograph links and the operator's reasons — none of which came from a sitting that ever
> happened. It was reverted on 2026-09-09. This issue's rule is the reason it exists: the decision
> is made on the real screens, by the operator, and recorded here and in #133 **before** any
> layout-specific code. An agent may build the arrangements; it may not conclude which one won.

The second decision of that day — that there is no choice to make, and one arrangement — is at the top of
this page, in the operator's words, and it is what #232 built. There is no `LAYOUTS[0]` to move any more:
the three lists a test used to keep in step are gone, and so is the default they named.

## Constraints the arrangement keeps

No new dependency, no build step, no CSS framework — the page still has to load in PyCharm's JCEF
tool window and VS Code's Simple Browser behind the corporate proxy, where anything fetched from the
internet simply does not arrive ([fleet-ide.md](fleet-ide.md)). There is one arrangement and one
stylesheet, so a tile cannot mean one thing on one screen and something else on another.

Window *placement* is the OS's and the browser's job. The dashboard offers views; it does not know
which monitor it is on and does not try to find out.
