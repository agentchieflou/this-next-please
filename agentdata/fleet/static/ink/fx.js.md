# `ink/fx.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Ink effects (#370, epic #293): the seam every one-shot effect hangs on, and the cues (#372).
docs/desk-ink.md §Effects, §The files and §Budgets.

Its own module, fetched by the layer only for a table that has effects (a skin that exports
`cues`, or `options.fx`), so the four modules every drawing desk loads stay inside `INK_BUDGET`
and effect code is held to `FX_BUDGET` (§Budgets). It imports nothing: the layer hands it
three.js, the scene and the draw order (`attach(layer, spec)`), and it writes nothing to the
page. It reads the page: the rows' matches, their boxes, and the records of `<body>`'s class.
Its one touch on the page is `api.fx.animate` (#374): a Web Animations API animation on a pane,
transform or filter only, `fill: "none"`, which composites over the pane's own style, writes no
attribute, and is gone when it ends.

DRAW ORDER. The group sits at `api.order.fx` (-5). three.js r160 sorts first by the innermost
Group's `renderOrder`, and the pane groups `framePanes` makes keep 0, so an effect draws over
the back pass (ground, paper) and under every pane's frame and every mark, whatever
`api.order.frame` says. Within one list three.js draws every opaque object before any
transparent one, so an effect's materials are `transparent: true`, like the skins' own. An
effect that must sit on a pane's frame goes into that pane's frame group.

THE CUES (#372, §Effects). A skin's `cues` rows, `{selector, on: "arrive" | "leave", cue}`, are
matched with the table, and its `cue(ctx, name, el, box, how)` plays each new one. A cue is
news, never history: nothing on a table's first match, while `body.is-stale` or
`body.is-replaying` (#371) is set or on the first match after, for an arrival in a pane that
only just arrived, without a skin, or under reduced motion.

AT REST. `match` (after the table is matched), `measure` (after every mark is measured) and
`deliver` (in each frame, after `prepare`) run only on frames the layer draws. `deliver` asks
for the next while a cue waits or a child of the group lives: at rest, neither.
```

### `export function attached`

Above `export function attached() {`:

How many layers have effects attached: 0 after every detach path (a table without `fx`,
`Ink.setSkin(null)`, `Ink.off()`).

### `const NAME`

Beside `const LANE = ".tile[data-repo]";`:

a pane, as the layer names one

### `const ROWS, WAIT, PER_FRAME`

Above `const ROWS = 16, WAIT = 16, PER_FRAME = 4;`:

The caps: rows in a table, cues waiting, cues delivered a frame.

### `const PANE, MOVING`

Above `const PANE = "#grid > .tile[data-repo]";`:

What `animate` may move: a pane of the grid, and at most `MOVING` of them at once.

### `const GLYPHS, GLYPHS_CAP`

Above `const GLYPHS = 128, GLYPHS_CAP = 256;`:

`api.fx.glyphs(el, max)` (#375): `max` defaults to `GLYPHS` and is clamped to `GLYPHS_CAP`.
A letter's box is a Range read of its own: measured in CI's Chromium, 2,456 glyphs of a pane
took about 6.5 ms, so a skin reads a name or a line, never a pane or a transcript, and the cap
holds one read under a millisecond.

### `const BLANK`

Above `const BLANK = /\s/;`:

Whitespace has no letter to follow, so `glyphs` skips it: a space, a tab, a line break.

### `export const KINDS`

Above `export const KINDS = Object.freeze({`:

The kinds a skin may ask `animate` for (#374), each read and gone inside the 320 ms ceiling
(docs/desk-motion.md §Effects on the canvas): `hit` shakes the pane sideways, `pop` swells it by
1.5%, `flash` rings it twice with a drop shadow in its own text colour (two flashes at most, WCAG
2.3.1; the panel is opaque, so the halo falls outside the pane and never behind a word). Only
`transform` and `filter`: nothing that lays out or fades. `add` composites a transform over the
pane's own (`composite: "add"`), so a pane with a transform keeps it. Exported for the tests.

### `const REAP`

Above `const REAP = 90;`:

The net: a child of the group older than this is taken out. In frames, like every duration on
the canvas (docs/desk-motion.md): 1.5 s at 60 Hz. No shipped skin relies on it.

### `const OBSERVED`

Above `const OBSERVED = ["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant" …`:

What the layer observes for any table (layer.js `setTable`), besides what its mark rows name.

### `function linesIn`

Above `function linesIn(el) {`:

`api.fx.lines(el)` uncached (#375): one Range over the element's contents, its client rects
merged per line exactly as the layer's `linesOf` does for the `lines` shape (layer.js), a rect
under 2 px either way dropped, a rect joining a line when its middle is within
`max(4, 0.45 x its height)` of the line's. The boxes are in viewport CSS px, top to bottom,
not relative to the element: a cue's `box` is in the same space.

### `function glyphsIn`

Above `function glyphsIn(el, max) {`:

`api.fx.glyphs(el, max)` uncached (#375): a `TreeWalker` over the element's text nodes and
one Range, moved over each character in turn (a code point, so a surrogate pair is one
letter), up to `max` of them that are not whitespace. Each box is that one character's
`getBoundingClientRect()`, in viewport CSS px, with the character as `ch`.

### `function refusal`

Above `function refusal(cues, layer) {`:

Why a cue table cannot be played, naming the row, or "" when it can.

### `export function attach`

In `attach`, above `const refused = refusal(cues, L) || null;`:

A lazily fetched module cannot throw from `Ink.setSkin`: a bad row refuses the whole table,
and the marks draw on.

In `attach`, beside `const born = new Map();`:

a child of the group -> the frame it was first seen in

In `attach`, above `const mo = new MutationObserver(recs => {`:

`match` reads the body once a frame and would miss a class set and cleared between two; the
records, read after both toggles, do not. A read, never a write.

In `attach`, above `const moving = new Map(), animated = { hit: 0, pop: 0, flash: 0 }, told = new Set();`:

The panes `animate` is moving: pane -> its `Animation`. `told` holds the unknown kinds already
said in the console, once each.

In `attach`, above `const listen = on => {`:

The two listeners live only while an animation does: a focus arriving in a moving pane takes
it back (capture, so a focus inside the pane counts), and so does reduced motion turning on. At
rest there is no listener, no timer and no frame.

In `attach`, above `function still(el) {`:

Takes one pane's animation back, synchronously: out of the map, cancelled (the pane is as it
was, `getAnimations()` empty), and the layer told the pane moved, so it re-reads geometry for
`FOLLOW_MS` and the frame after measures the true box. `finish` and `cancel` both end here.

In `attach`, above `function animate(el, kind) {`:

`api.fx.animate(el, kind)` (#374): `true` if an animation started. Refused, `false` and counted
in `skipped`, when the element is not a connected pane with a box; under reduced motion
(`layer.instant()`); without a skin, or with the layer stopped (`body.ink-off`, `?ink=off`);
while the document is hidden; when the pane holds the focus; when a selection that is not
collapsed touches it (text being selected or read); when it already animates (its own
transition included); and when `MOVING` panes already move. An unknown kind is `false` too,
said once in the console and not counted. Calling `layer.onMove()` on start makes the layer
follow the pane for `FOLLOW_MS`: a WAAPI animation fires none of the transition or animation
events it listens for.

In `attach`, above `const read = new WeakMap();`:

What `lines` and `glyphs` last read, per element (#375): its key, `textContent.length` and the
element's own `width x height`, and each answer made under that key (`lines`, and `glyphs` per
cap). A new length or a new size drops them all, so an identical second call reads no Range at
all, and a changed name or a resized pane reads again. A `WeakMap`, so an element the page
drops takes its entry with it; nothing is scheduled and nothing is kept at rest. An element
that has left the page answers `[]`. Each call gets its own copy of the array; the boxes in it
are frozen.

In `attach`, above `const text = !!(spec && spec.use && spec.use.text === true);`:

`options.fx.text` (the table's `fx.use`, ink.js's `fromModule`): only a skin that asks for
the text helpers gets them, so an `api.fx` without them says the skin never asked.

In `attach`, above `api: Object.freeze(text ? { animate, lines, glyphs } : { animate }),`:

The helpers a skin's hooks reach as `api.fx`: `animate` (#374) always, `lines` and `glyphs`
(#375) under `options.fx.text`; #376 adds to it.

In `attach`, above `match() {`:

After the table is matched: what arrived and what left, since the last match.

In `attach` › `match`, above `const old = e.zeroAt && L.frames - e.zeroAt > 1;`:

Empty for more than a frame (a grouped pane, `display: none` a while) is empty. A hide
still has its box: `frame()` matches before it measures.

In `attach`, above `measure() {`:

After the marks are measured: each leave row's match keeps its last non-empty box, and an
empty measure (a pane the ResizeObserver sees just hidden, at 0x0) stamps it. Arrive rows
are never measured again.

In `attach`, above `deliver() {`:

In each frame: a moving pane that left the document is taken back, then at most `PER_FRAME`
cues to the skin, and the net.

In `attach` › `deliver`, beside `bin.add(child);`:

out of the group, and freed as the layer frees a group
