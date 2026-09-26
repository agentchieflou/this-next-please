# `app.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

The multi-viewer. Light and dark follow the system; the palettes override surface colours only
-- status colours never change, because a chip meaning "needs you" has to be the same red in
every theme or the colour stops being information. That is why a failed poll's greyed cell
(#131) uses --idle, not a lighter --muted: "this number is old" is a status. There is one
arrangement (#232) and one stylesheet, so nothing below can make a chip mean two things.

### `:root`

Above `--on-running: #111111;`:

The word on each state colour (#327): a chip's, a badge's, a rail glyph's. The first of
`--text`, `--bg`, white and #111111 that reads at 4.5:1 on it, as `theme.to_css` chooses for
every palette. White on --done is 3.57:1 here, so no word is white by default. The dark block
below needs none: the state colours are shared.

Above `--running-text: #2a68aa;`:

A word written IN a state colour (#328): the why line, "exit 2", "it asked you:". A state
colour is held to 3:1, a mark's floor, and a word needs 4.5:1, so the word is the state moved
toward `--text` until it reads on `--bg`, `--panel` and `--select` (`theme.role_text`, as
`theme.to_css` chooses it for every palette). Borders, outlines and discs keep the state. The
dark block below has its own: these read 2.3-3.2:1 on its grounds.

Above `--motion-fast: 120ms;`:

#216. The whole page's motion budget, in three numbers. Nothing on the desk may last longer
than `--motion-slow`, and a test over this file and every skin says so -- a duration nobody
bounded is how an interface comes to feel slow while every single animation looks fine on its
own. `--motion-fast` is for something under the cursor (a hover, a press), `--motion-base` for
something arriving or leaving, `--motion-slow` for a whole layout changing.

Above `--ease-spring: cubic-bezier(0.2, 0.9, 0.3, 1.2);`:

The spring is a fallback first: an engine that cannot parse `linear()` would otherwise drop
the declaration that uses it and fall back to `ease`, which overshoots nothing and reads as
mush. The `@supports` below upgrades it where the engine really has it.

### `@media (prefers-color-scheme: dark)`

In `:root:not([data-theme])`, above `--running-text: #5e9ada; --waiting-text: #cb8817; --human-text: #d67f8a;`:

The words in a state colour, chosen by the same rule on these grounds (#328).

### `[hidden]`

Above `[hidden] { display: none !important; }`:

The `hidden` attribute has to win, and until this rule it did not: every panel sets `display:
flex` and an id selector outranks the user-agent `[hidden]` rule, so a "closed" drawer stayed on
the glass swallowing the clicks meant for the tiles under it. `el.hidden = true` is how this
page closes everything, so it means what it says here or it means nothing.

### `.toolbar-group`

Beside `position: relative;`:

the look popover hangs off its group (#180)

### `.toolbar-group .glabel`

Above `.toolbar-group .glabel {`:

HIG *Toolbars*: a group of commands says what it is for. Twelve controls in one unlabelled row
is a settings panel, which is what the toolbar is not.

### `@media (max-width: 1100px)`

Above `@media (max-width: 1100px) { .toolbar-group .glabel { display: none; } }`:

Under about 1100px the group labels are the first thing that can go: the controls they name are
all titled and keyboard-reachable, and a wrapped toolbar is worse than an unlabelled one.

### `.popover`

Above `.popover {`:

#180: a popover is a panel hung off its button, in the same `--panel`, `--line` and radius.

### `#keymap`

Above `#keymap { flex-direction: row; flex-wrap: wrap; gap: 12px 28px; max-width: min(760px, 92 …`:

The key map: four short columns.

## scrollbars (#181)

### `body`

Above `body {`:

From the palette: two properties, overridden per skin on `body`; the legacy `::-webkit-scrollbar`
rules say the same colours for embedders that predate `scrollbar-color`.

### `*::-webkit-scrollbar-thumb`

Beside `border: 2px solid transparent; background-clip: padding-box;`:

a gutter, so it reads thin

## the grid, and one big tile

### `.away-strip`

Above `.away-strip {`:

HIG *Split views*: auxiliary content sits BESIDE the main content and does not cover it. The
panels used to be four fixed drawers at the same edge, overlapping each other and the grid.

### `#side > aside`

Above `#side > aside {`:

Each section fills the sidebar; `[hidden]` above is what keeps the other four out of the way.

### `@media (max-width: 900px)`

Above `@media (max-width: 900px) {`:

A narrow window -- JCEF's tool window, Simple Browser in a split -- cannot afford a column
beside the grid, so the sidebar goes back to being an overlay there and says so with a shadow.

## the row (#233)

The operator's sentence: *each agent is a column, not each agent is stacked in one column --
skinnier agents.* So every agent is a pane in one row, at full height, in the arrangement's
order. The wide ones share what the rails leave, each by its weight in this window's widths
(#234; a window with none yet widens its open pane and its pins), and every other one is a rail. Nothing here scrolls sideways in the ordinary case: a desk
that scrolls hides the agent that needs you, so when even the rails cannot fit, a project's
checkouts share one rail (`groupRails` in app.js) before the row is ever allowed to scroll.

`.panes` is the row and what follows it: the panes themselves in `main`, and the rails of
repositories that left the registry after them.

### `#grid`

Above `#grid {`:

```text
The desk's row. An id, never the bare element: /settings has a <main> of its own, and this rule
squeezed it to the window and clipped it (the settings page could not scroll).
```

Above `overflow-x: auto; overflow-y: hidden;`:

The last resort, never the design: past grouping, a row that still cannot fit scrolls rather
than crushing a rail under its 48px.

### `:root`

Above `:root { --rail: 48px; --compact-from: 160px; }`:

The left edge is the PROJECT's accent; the chip is the state. One stripe with two meanings is
how a four-monitor desk starts lying: the same red would say "this project" on one screen and
"this needs you" on the next. #150 fixed the roles, and the accent is the hex that project's
terminal is painted in.

Every pane is a rail until it has a width: 48px, which is a 28pt hit target and its padding. A
wide pane (`is-solo`) takes `--w` shares of the width the rails leave -- its weight in this
window's widths (#234), which the gutters, the presets and the swap write -- and never goes under
the compact tier's 160px. `flex-basis: 0` and `border-box` make a pane's width exactly its share
of the row, which is what lets a gutter move two panes and leave every other one to the pixel.
The width is decided HERE and nowhere else; what the pane draws is decided by the width
(`data-tier`), never the other way round, or a tier that changed the width would change the
tier. `position: relative` is what the drop line and the gutter hang from.

The rail's width and the compact floor are the operator's since #235 (`fleet.tiers.*`, set on the
settings page): `applyTiers` in app.js writes them on the root when they are not these, which are
CI's, so a desk on the defaults carries no inline style for them at all.

### `.tile.is-selected`

Above `.tile.is-selected { box-shadow: 0 0 0 2px var(--focus, var(--accent)); }`:

The selection is one, unmistakable, and never in a state colour (HIG *Focus and selection*).

### `.head`

Above `.head {`:

`overflow: hidden` is a guard, not a style: a head whose controls spill past the tile's right
edge lays them over the neighbouring tile, where they cannot be clicked and the neighbour
cannot be either. It bit once (#217) and it is one declaration to make it impossible.
Wraps rather than clips. The head carries seven controls and three pieces of identity, and on
a 360px track -- the grid's narrowest -- they do not all fit on one line however hard the
shrink rules below try. A second line is untidy; a maximise button the operator can see the
edge of and never press is broken. `overflow: hidden` stays as the last guard, so nothing can
lie over the neighbouring tile either way.

Above `flex: 0 0 auto;`:

A column flex item shrinks to its `min-height` unless told not to, so a head that wrapped to
two lines kept the height of one and hid the second behind the run line.

### `.tile`

Above `.tile { container-type: inline-size; }`:

Before it comes to wrapping. On a narrow tile the model's word goes first and the ticket key
second: both are two lines down on the run line and in the cells anyway, and a detail repeated
three times is not worth a second row of title bar. The tile is the container, so this is the
tile's own width and not the window's -- a 360px tile on a 4K glass needs it as much as one on
a laptop does.

### `.head .repo, .head .ticket, .head .bm-name`

Above `.head .repo, .head .ticket, .head .bm-name {`:

What gives when the head is narrower than its contents. `overflow: hidden` alone clipped
whatever came last, which on a 360px track was the maximise button -- a control the operator
could see the edge of and never press. The identity of the tile shrinks instead: the name to an
ellipsis, the ticket and the model's word likewise. The controls never shrink, because half a
button is worse than a shortened name.

### `.head .repo`

Above `.head .repo { flex: 0 0 auto; max-width: 40%; }`:

The name does not shrink: it is which agent this is, and `b…` answers nothing. What gives,
in order, is the model's word, then the ticket, then the state chip -- each of which is a
detail the tile repeats elsewhere.

### `.head .bm-name`

Above `.head .bm-name { flex: 0 3 auto; max-width: 124px; }`:

124px is the widest shipped label, `mai code 1.1 flash` (#492): 68px cut sol, terra and luna to
one letter. The word still gives way first when the head is short of room.

### `.bm-name.next`

Above `.bm-name.next { font-style: italic; text-decoration: underline dotted; text-underline-of …`:

#492: a model chosen for the next turn, not yet run. Not a colour: a dotted underline and a
slant, and the title says which turn it waits for.

### `.grip`

Above `.grip {`:

The drag handle. HIG *Drag and drop*: direct manipulation needs an affordance -- a tile that is
draggable everywhere and says so nowhere is a tile nobody drags (and one whose transcript text
can never be selected). Only the header carries `draggable`.

### `.runline`

Above `.runline {`:

Which run this transcript belongs to. Without it the tile shows a transcript with no era, which
is how a two-day-old run read as live.

## one session control (#206)

### `.sessionbar`

Above `.sessionbar { position: relative; margin: 4px 0 0; }`:

The strip here was four buttons of three different kinds and a second, inert *earlier* under the
transcript. It is one pill saying which session this transcript is, and one menu behind it
holding everything that changes which session that is.

### `.spill.is-reading`

Above `.spill.is-reading { color: var(--waiting-text); border-color: var(--waiting); }`:

Reading an earlier session is a state the tile is IN, so the control that put it there says so.

### `.sm-model`

Above `.sm-model { margin-left: .5em; }`:

#368: the model a new session or a console starts on, in the item's own words colour.

### `.live-runs, .ss-runs`

Above `.live-runs, .ss-runs {`:

A run is a transcript boundary, not a thing to open: opening one is opening its session, which
is the row above it. So the runs are rows and not buttons.

### `.readonly`

Above `.readonly {`:

The read-only pane. The reply box is not disabled, it is *gone*: a box you can type in that
cannot send is a worse answer than no box.

### `.chipage`

Above `.chipage { font-weight: 400; }`:

Every state carries its own age, inside the chip, because "done" without "2d" is the bug. It is
lighter by weight, never faded: the chip's word colour is chosen to read at 4.5:1 (#327).

### `.head .pintoggle, .head .maxtoggle, .head .hidetoggle, .head .refreshtoggle, . …`

Above `.head .pintoggle, .head .maxtoggle, .head .hidetoggle,`:

28px is the HIG desktop floor for a hit target; 20px was below it.

### `.head .pintoggle svg, .head .maxtoggle svg, .head .hidetoggle svg, .head .refr …`

Above `.head .pintoggle svg, .head .maxtoggle svg, .head .hidetoggle svg,`:

Every one of them, or the one left out paints its SVG with the default black fill (#180).

### `body.is-stale main`

Above `body.is-stale main { opacity: 0.72; }`:

#219: the desk the window last saw, while the one it has now is loading. Dimmed a little and
said out loud in the footer -- a stale desk that does not admit it is a desk that lies for a
second, and a second is long enough to act on. No spinner: the page has something to show, and
a spinner over real content is an apology for content nobody asked it to withhold.

### `.trace`

Above `.trace {`:

#218: the last hour, on the pane's title bar. It shrinks before anything else in the head does,
and goes altogether on a narrow pane, because an hour nobody can read the shape of is 64 pixels
of title bar spent on nothing.

### `.trace .tr-line`

Above `.trace .tr-line {`:

#257: the plain look, and the one every shell that does not draw ink shows -- the same hour the
ink layer draws, in the stylesheet's own colours, so a palette that changes repaints it with no
script. `preserveAspectRatio="none"` stretches a minute to whatever width the head gives it, and
a stroke that must not stretch with it says so.

### `body:has(> #ink[data-skin]) .trace > *`

Above `body:has(> #ink[data-skin]) .trace > * { visibility: hidden; }`:

Where a skin draws with ink, the ink layer draws the trace itself, from the series on the
element, and the SVG steps aside. It keeps its box and its words: only the drawing is the
layer's. A CSS skin's pane is opaque and would cover the layer's canvas, so there -- and in every
shell without ink -- the SVG is the trace.

### `@container (max-width: 560px)`

Above `@container (max-width: 560px) {`:

The head wraps before it shrinks -- that is what `flex-wrap` means -- so the trace has to be
gone by the width at which it would have caused the wrap, not by the width at which it stops
fitting. A compact pane and a rail do not draw it at all (#233).

### `#ink`

Above `#ink {`:

#248: the ink layer's one canvas, behind the page and in front of the stylesheet's own ground.
`static/ink/layer.js` puts it in wherever the gate says this shell draws ink, and from #257 it
draws the desk's own ground and traces there, whatever the skin.

### `body:has(> #ink[data-skin]) :is(header, footer, .tile, .approval, .asks, .ask- …`

Above `body:has(> #ink[data-skin]) :is(header, footer, .tile, .approval, .asks, .ask-choice, .d …`:

#257: where a skin draws with ink, the page stands aside for it -- once, here, for every skin.
The canvas is behind the page, so the skin's paper, frames and marks show only where nothing
opaque is over them: the panes, the header, the footer and the cards on a pane are clear, and
the pane keeps only its accent on the left (which project, #150) and the selection ring. Keyed on
the canvas being there with a table on it, not on `:not(.ink-off)`: between the gate saying on
and the layer arriving, a clear pane would have nothing behind it. Everywhere else -- every shell
the gate turned off, and every CSS skin -- is the one plain look above.

### `.is-dragging`

Above `.is-dragging {`:

Whatever is under the hand -- an open pane by its head, or a rail by its face. It is lifted out
of the flow's paint order and given no pointer events, so `elementFromPoint` answers with what
is *underneath* it rather than with the thing being dragged. Written for any host from the
start: a rule that named only `.tile` once left the column's drag with nothing to drop onto.

### `.tile .head, .pane-rail`

Above `.tile .head, .pane-rail { touch-action: none; user-select: none; -webkit-user-select: no …`:

A title bar is not text to be selected, and while it was the browser turned the second drag in
a row into a native drag of the selection the first one had made -- which arrives as
`pointercancel` and ends the gesture on the frame it began. `draggable` used to suppress this
as a side effect; saying it outright is what replaces it.

### `.tile.is-pinned .head .n::after`

Above `.tile.is-pinned .head .n::after { content: "\00a0\1F4CC"; font-size: 11px; }`:

A pinned tile says so on the tile, not only in the tint of a 28px button: the pin is why it is
first, and "why is this one at the top" is the question the tint could not answer.

### `.tile.drop-before, .tile.drop-after`

Above `.tile.drop-before, .tile.drop-after { position: relative; }`:

Where the tile will land, shown before the drop (HIG *Drag and drop*). An insertion line, not a
recolour of the neighbour's edge: the edges already carry the project accent, and a drop hint
that repaints them would say the project changed.

### `.tile.flip`

Above `.tile.flip { transition: transform var(--motion-base) var(--ease-out); }`:

A tile travelling to a new place in the order (#5). The class is added by `playFlip` only for the
one frame the tile is inverted, so a tile at rest carries no transition -- dragging one must stay
immediate. The global `prefers-reduced-motion` block below zeroes the duration, and the script
skips the measurement entirely, so a viewer who asked for less motion gets a plain reorder.

## the transcript

## the approval

## notifications (#97)

### `.drawer-head`

Above `.drawer-head { display: flex; align-items: center; gap: 8px; padding-bottom: 6px; }`:

One sidebar, five sections, one open at a time -- see `#side` below. These were five fixed
overlays at the same edge, stacked on each other and on the grid.

## the Jira board (#98)

## the project's own state and links (#131)

### `.cells`

Above `.cells { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }`:

The rail and the cells sit above the transcript because they answer the question that used to
cost a tab. A cell is value + age, always both: the value alone goes stale silently.

### `.cell.grey`

Above `.cell.grey { border-style: dashed; border-color: var(--idle); color: var(--idle-text); }`:

Grey, never wrong: the last value it actually had, how old that is, and the error in the tooltip.
Dashed as well as grey, because a colour alone is not a signal on a bad monitor at arm's length.

### `button.cell`

Above `button.cell { background: transparent; color: var(--text); cursor: pointer; text-align: …`:

The git cell is a button with a second line (#184), amber at `fleet.branches.warn`.

### `.cell.spend .val`

Above `.cell.spend .val { font-variant-numeric: tabular-nums; }`:

The spend cell (#211). Amber at four fifths, red at the line -- and never colour alone: each
carries the sentence that explains it in its title, and the value itself says `of 10`.

## what is this project (#130)

## the Downloads inbox (#132)

## who needs you (#133, #234)

The name of an agent that needs a person is in the status red wherever it is written. What used
to sit here was focus mode's -- a filter that dimmed every rail whose agent wanted nothing, and
`.held` to keep the one just answered from dimming under the reply. The *needs me* preset
replaced it (#234): a press that makes whoever needs you wide and the rest rails, and takes
nothing back when one of them stops needing you, so there is nothing left to hold.

### `.outside`

Above `.outside {`:

A session the fleet did not start (#2). An offer, not an alarm: nothing is wrong, the fleet has
simply noticed something it does not own. Once adopted the same strip stays, saying so, because
"this repo is being driven from another window" is the fact the tile exists to carry.

## the pane's three widths (#233)

One component, three widths. What a pane draws is decided by how wide it is, and the width by
the widths (above) -- `data-tier` is the one bridge, written by one `ResizeObserver` with 8px of
hysteresis between compact and full so a pane on that boundary does not flicker. The draw
functions skip what a tier does not show; the rules below take the rest off the glass.

rail     48px      the rail's face and nothing else
compact  160-359   the head (name, state chip with its age, ticket), the three tools, the cards
                   that ask the operator something, the last lines, the reply box
full     360+      everything a tile has

Those are CI's numbers and the defaults; `fleet.tiers.*` moves them (#235).

### `.tile[data-tier="rail"] > :not(.pane-rail):not(.gutter)`

Above `.tile[data-tier="rail"] > :not(.pane-rail):not(.gutter) { display: none !important; }`:

`!important` for the same reason `[hidden]` has it: a rail shows its face and nothing else, and
a state rule elsewhere that sets `display` on a part of the pane must not put it back inside a
48px strip (the hold note focus mode had was one). Its face -- and its gutter, which is how a
rail is pulled wide by hand (#234).

### `.pr-glyph`

Above `.pr-glyph {`:

The state's glyph, in the state's colour: the chip's palette, on a disc a rail can carry. The
glyph is the word for anyone who cannot tell the colours apart; the colour is the glance.

### `.pr-name`

Above `.pr-name {`:

The name down the rail's length. Clipped at the foot rather than wrapped: a name is read from
its start, and the whole of it is in the label.

### `.pane-rail.needs-human`

Above `.pane-rail.needs-human { background: var(--human); color: var(--on-human); }`:

The whole rail red when its agent needs a person -- the face is the rail, so the face is what is
red, and a skin that paints the tile's own background cannot take that away. The word is
`--on-human` on the status red (#327), with the glyph turned round: `!` in red on an
`--on-human` disc.

### `.tile[data-tier="compact"] :is(.grip, .head .trace, .pintoggle, .maxtoggle, .r …`

Above `.tile[data-tier="compact"] :is(.grip, .head .trace, .pintoggle, .maxtoggle, .runline,`:

Compact: what a band carried, and room to answer. The name takes the head's first line; the
chip, its age, the ticket and the three tools wrap under it.

### `.tile[data-tier="compact"] .head .spacer`

Above `.tile[data-tier="compact"] .head .spacer { flex-basis: 100%; }`:

The three tools on a line of their own, at the right, not wherever the wrap drops them.

### `.tile:not([data-tier="compact"]) .head .freshtoggle:not(.is-offer)`

Above `.tile:not([data-tier="compact"]) .head .freshtoggle:not(.is-offer) { display: none; }`:

Start fresh on every pane (#509, SESS-D6): compact hides the bottom row's Start, so its head's
*start fresh* shows whatever `offer` says; a full pane keeps #489's rule (stale, adopted, began
outside). The page draws the button whenever the row has a verdict, and a tier change is CSS.

### `.tile.is-hidden, .tile.is-grouped`

Above `.tile.is-hidden, .tile.is-grouped { display: none; }`:

Put away, and represented. A hidden pane leaves the row (the footer counts it); a checkout
grouped into its project's rail is on the glass as that rail.

## the gutters (#234)

A 1px line between two panes, in the middle of the row's 6px gap, and an 8px strip to take hold
of it by: the gap and the two pixels of the pane's own edge beside it, so it costs the row no
width. (Not the neighbour's edge: a pane is a stacking context -- `container-type` contains its
layout -- so the pane after it paints over anything this one hangs across it, and a strip that
reached in would lose that part to it.) It is the pane's own last child -- the pane on its left
owns it, which is what `Alt+Shift+←/→` on that pane moves -- and a rail keeps it, because a rail
can be pulled wide by it. The line lights under the hand, and while the hand has it the whole
page says `col-resize`, because the pointer leaves an 8px strip on the first pixel of travel.

### `.gone`

Above `.gone {`:

A repository that left the registry: a dashed rail after the row, naming what restores it.

### `.hiddencount, .undo`

Above `.hiddencount, .undo {`:

The footer's count of what is put away, and the one press that brings it all back -- and beside
it, the one press that takes the last change of widths back (#234).

## hide, refresh and the model (#205)

The same three controls on every pane that has a head, so the eye finds them in the same place
whichever one it is looking at -- and on a rail, the same three keys.

### `.head [aria-busy="true"]`

Above `.head [aria-busy="true"] { opacity: .5; }`:

An in-flight control is the control itself, dimmed -- never an overlay and never a spinner: the
page has one motion budget (#216) and a refresh is over before an animation would read as one.

### `.wordbtn`

Above `.wordbtn { font: 11px var(--mono); letter-spacing: .02em; white-space: nowrap;`:

The model button says a name rather than drawing a glyph: a model is a word, and an icon for one
would be an icon nobody can read. It ellipsises inside the head rather than running off it.

### `.wordbtn .bm-name`

Above `.wordbtn .bm-name {`:

The ellipsis has to be on the element that holds the text. It was on the button, whose centred
flex child was wider than it and overflowed both edges -- so a long model name ran off the side
of the card instead of being shortened inside it.

### `.modelcard`

Above `.modelcard {`:

The card behind the model button. Fixed, because it is one card for the page and it is moved to
whichever button opened it -- the same "moved, never copied" rule the dispatch card follows. It
scrolls inside itself (#366): the picker's pills are taller than a short window, and the arrows
and the wheel have to reach the effort toolbar at the bottom of it.

## #216: arriving, and going away again

### `.enters`

Above `.enters {`:

Every panel the desk shows and takes away, in one block. The pattern is the same for all of
them -- fade and settle by four pixels on the way in, the same in reverse on the way out -- so
there is one thing to learn rather than nine, which is the whole of the operator's "minimalist
interface navigation" note.

`transition-behavior: allow-discrete` is what lets `display` take part. Without it a panel
leaving is removed on the first frame and only its arrival is ever seen, which is the
half-animation that reads as a glitch. It is set as a longhand after the shorthand on purpose:
an engine that does not know the property ignores that one line, `display` is simply not
animated, and both directions are instant -- which is exactly the behaviour these panels had
before this rule existed.

### `@starting-style`

Above `@starting-style {`:

The arrival's starting point. A style that only exists for the frame before the element is
first painted: without it the browser has nothing to animate *from* and the panel simply
appears.

### `::view-transition-old(*), ::view-transition-new(*)`

Above `::view-transition-old(*), ::view-transition-new(*) {`:

A tile is a box of text, and a view transition animates *images* of the old and new states.
Scaling one to the other's size stretches the words, which is the giveaway that what is on the
screen is a picture of a tile rather than the tile. Both snapshots are pinned to their own size
at the top left instead, so what moves is the box and what cross-fades is text at the size it
was written.

### `@media (prefers-reduced-motion: reduce)`

Above `::view-transition-group(*), ::view-transition-old(*), ::view-transition-new(*) {`:

A view transition runs on pseudo-elements that `*` never matches, so the three rules above do
not reach it. `transitionLayout` refuses to start one under reduced motion as well; this is
the stylesheet saying the same thing for a transition begun from anywhere else.

## the inspector's project detail (#148)

### `.branches`

Above `.branches { display: flex; flex-direction: column; gap: 4px; font: 11px var(--mono); }`:

The branches pane (#184): unmerged first and marked, the ticket's own underlined.

### `#inspectordetails .frictionrow.quiet`

Above `#inspectordetails .frictionrow.quiet { border-left-color: var(--muted); }`:

#499: a row that does not block, and every row folded under *earlier friction*, is muted. Marks
are muted, never a status token (#339).

### `#inspectordetails details.more > summary, #inspectordetails details.branches-l …`

Above `#inspectordetails details.more > summary,`:

#504: the panel fits one screen. Everything but the rail, open friction, spend and the branches
folds under one closed *more*; a branch row is one line, its full meta in its title.

### `.wrapsheet`

Above `.wrapsheet {`:

#510: the wrap-up sheet, between the drawer head and the panel's details. A step's result is a
word and a glyph, never a status colour: the agent's colours stay the agent's (#339).

### `.day-rows .sweep-row`

Above `.day-rows .sweep-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; }`:

#512: the sweep in the day strip -- one row per agent, a cell per write drawn by the sheet's own
`wrapCell`. A repo with nothing to write, or a busy one, is one muted line.

## the dispatch card (#164)

A drop opens this instead of launching, in the approval card's shape: both are "the tile is
asking you something before anything irreversible happens", and one shape is learned once. The
accent is the focus colour, not a status one -- nothing here is an agent state, and the status
palette must keep meaning what it means (`docs/plan-desk-refactor.md` §One palette).

### `.verdict.v-ready`

Above `.verdict.v-ready { color: var(--done-text); border-color: var(--done); }`:

Never colour alone: each verdict carries its word, and the tint only reinforces it.

### `.dispatch-model`

Above `.dispatch-model { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: …`:

#368: "runs on" and the compact picker. Under an ink skin the card goes clear, so the picker
keeps a ground of its own and its pills stay legible; pressed still reads without the fill.

## the question card (#165)

The approval card's shape again: the tile is asking you something before anything irreversible
happens. It wears `--human` because an unanswered blocking question *is* "needs you" -- the same
red the chip uses, so the card and the chip agree at a glance.

### `.assumed`

Above `.assumed { list-style: none; margin: 6px 0 0; padding: 0; }`:

An assumption is not a state, so it is a quiet row rather than a card: the agent said what it
was doing and kept working, and the operator overturns it only if it is wrong.

## the scope card (#166)

The tile has drawn a dashed "copy" outline on any non-tile drag since #98; until #166 a dropped
file produced that outline and nothing else. This is what it produces now.

### `.sc-how`

Above `.sc-how {`:

`fingerprint` and `name` are not the same claim, and the weaker one says so.

### `.scopereport`

Above `.scopereport { color: var(--muted); margin: 2px 0; }`:

The scope report (#168): a sentence, not a state. `outside` is worth noticing and is never an
error -- an agent that had to go outside the scope to do the work was probably right to.

## the chip (#173)

A hidden pane keeps its slot and leaves the row; the footer counts it (#233, above). The chip is
the one the grid's dock drew (#232 retired the dock with the grid), and the agent rail wears it
now.

## the agent rail (#183): the dock's chip as a drop target,

candidates lit and the rest dimmed while a ticket is in flight; lit is also `aria-selected`.

### `#tickets li:focus-visible`

Above `#tickets li:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }`:

A ticket row takes the keyboard: `1`-`9` picks a rail chip, `Enter` its one candidate.

## fresh sessions (#240, #241)

### `.freshtoggle`

Above `.freshtoggle { white-space: nowrap; }`:

#489: start fresh. The head's button is a word button like the model's; the strip's second button
(*stop following it*) is the quieter one; a rail that offers it wears a dashed muted ring on its
glyph -- a mark, never a state colour (#339).

### `.pane-rail:is(.is-stale, .is-outside) > [aria-hidden="true"]`

Above `.pane-rail:is(.is-stale, .is-outside) > [aria-hidden="true"] { outline: 1px dashed var(- …`:

The glyph is the face's one `aria-hidden` part. Not named `.pr-glyph` here: every rule that is
names the glyph's colour pair (test_fleet_theme_tokens), and this one only draws a ring round it.

### `.day-strip`

Above `.day-strip {`:

A fresh day (#511): the renew strip's shape, in a strip of its own. A row is a checkbox, then the
repo, verdict, ticket, model, began, why and -- for one waiting on you -- its question and *answer*.
Words in `--text`; the why in `--muted` as renew's is, with the question beside it in `--text`.

## the model picker (#362)

`picker.js`, on the model card, /settings and the dispatch card. Tokens only, every selector under
`.mpick`, and no word in `--muted`, which is under 4.5:1 in nine palettes. Pressed is `--text` on
`--select` with a 2px `--accent` ring and a ✓: accent text on `--select` is 2.84:1 in sand, and the
ring is read against the card around the pill. A skin that clears button fills (the notebook)
leaves the ✓ and the ring, which is why they are there.

## the settings page (/settings)

### `.linkbtn`

Above `.linkbtn {`:

One stylesheet for both pages, so a palette and a skin reach the settings page for free -- the
custom properties, the dark-mode block and the focus ring are already defined above, and a second
file would be a second place for them to drift.

Sharing one stylesheet means sharing one namespace, so every rule below is scoped to
`body.settings-page`. Unscoped, `.why` and `.scope` here silently restyled the desk's tiles and
its file-scope panel, which already own those names -- a page that changes another page is
exactly what a second stylesheet would have been written to avoid. `.linkbtn` is deliberately the
one exception: it styles the control on the DESK's toolbar.

The toolbar control that used to be a popover button and is now a link to a page. Styled as the
buttons beside it rather than as a link, because it sits in a row of buttons and reads as one.

### `body.settings-page .why`

Above `body.settings-page .why { margin: 0; font-size: 12px; line-height: 1.5; color: var(--mut …`:

The explanations are the point of the page: a setting whose effect you have to guess is one you
will not touch. They are muted so they never compete with the controls.

### `body.settings-page .when`

Above `body.settings-page .when { font-size: 11px; color: var(--muted); white-space: nowrap; }`:

Not `.scope`: the desk's file-drop panel owns that name and gives it a box.

### `body.settings-page .setrow > .setlabel`

Above `body.settings-page .setrow > .setlabel {`:

The model block (#367): the fleet-wide picker beside its label, the line saying where the list
came from beside its refresh button, and a row's expansion under its compact picker, in the same
cell. The pills are the picker's own (#362); a row's words sit level with its first pills.
