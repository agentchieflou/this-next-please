# `ink/skins/phosphor.js`

The reasoning for this file, kept beside it rather than in it (decisions 18 and 19 on #429). The
source keeps its code; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the declaration or statement the notes
sit in or above, in source order. A builder who changes the code changes its note here.

### The file

```text
Phosphor (#394): a green screen, and the state grammar drawn on it by a thin, even beam. The page is
near-black glass with faint scanlines; every mark is the notebook's, traced at an even width.

The rain (#395): each transcript line that arrives in a running pane drops one glyph down the
pane's margin into a stack, and a finished turn drains it. It moves only when something happens.

THE DOM IS THE TRUTH. The mark table is the notebook's (static/ink/skins/notebook.js), rows and
selectors unchanged: every row is a class or an attribute app.js already sets. Nothing here decides
a state, and nothing here draws a letter: a `write` row uncovers the element's own text.

No colour is written in this file. The glass and the inks are custom properties in
static/skins/phosphor/skin.css (`--paper`, `--scan`, `--board-max` and `--ink-<tool>`), read
through `tokens` at paint time.
```

### `export function marks`

The notebook's rows, in the notebook's order (docs/skin-notebook.md explains each). The running
row keeps `grow` and `tip`: on this screen the tip is the beam's spot, resting at the end of the
line it is drawing.

### `const T`

The beam: one tune for every drawing tool. An even width (`w` 1.3), full pressure with no
variation, no wobble, no bow, and no taper at either end -- a trace, not a hand.

### `export const options`

`paper: "--paper"` tells the layer the stock is dark, so the highlighter screens onto it.
`hand: false`: nothing holds the beam, so no hand is drawn. `speed: 1.5`: a beam sweeps faster
than a pen writes. `tools` gives the pencil, the pen, red and green the beam's tune; the marker and
the highlighter keep the layer's own.

### `function rgbOf`

A custom property's colour as [r, g, b] in 0-1 sRGB, as `tokens.css` answers it: a hex, or rgb().

### `const GLASS_FS`

The glass, shaded in viewport pixels:

- near-black `--paper`, with a lit row in `--scan` every third pixel row: the scanlines, about
  1.18:1 on the paper;
- a faint static grain, a per-pixel hash of a few levels;
- a corner vignette that darkens by at most 20%;
- every channel clamped to [`--paper`, `--board-max`], so whatever the grain and the vignette do,
  the text is read on a colour inside the panel pair `skins.py` declares and `theme.check` holds.

Nothing in it moves: no flicker, no roll, no bloom and no loop of any kind (photosensitivity and the
render contract, docs/desk-ink.md).

### `const RAIL_BELOW`

The rain's numbers (docs/skin-phosphor.md §The rain):

- `RAIL_BELOW`: a pane narrower than this is a rail, and rains nothing.
- `GUTTER`: the pane's left margin, skin.css's `--gutter`; the column runs down its middle
  (`COL_X`), a glyph's cell `CELL_W` x `CELL_H`.
- `HEADROOM`: the stack stops this far short of the pane's top; `FOOT`: it stands this far off
  the bottom.
- `FALL_MIN` and `SLOWEST`: a fall is at least 900 px/s, and fast enough to land within 320 ms
  (`--motion-slow`); a drain takes 320 ms too.
- `TEAR_FOR` and `TEAR`: the error's tear, 120 ms (`--motion-fast`) at 4px; `BAND` and `BAND_X`:
  the error's band, 2px, inset in the margin.
- `SLOTS`: panes the rain's one mesh can place; `MAX`: glyphs it can hold.

### `const RAIN_VS`

One instance per glyph (or band): its rect in its pane's coordinates, its colour, its pane's slot
and its seed. The pane's offset is `uPane[slot]`, set before each render from the pane's group; a
pane not on the page is sent off screen.

### `const RAIN_FS`

A glyph: a 5x7 grid of dots inside its 7x10px cell, each lit when a hash of the dot and the
glyph's seed is under 0.4, so about 40% of them -- a pattern, never a letter. A seed below 0 is the
error's band, filled.

### `const R`

The module's state: the rain's mesh and the tokens last read, whether motion is reduced, a record
per pane (a `Map` keyed by the pane, freed once it is disconnected) with its slot in `uPane`, the
draw calls the rain last took, how many times `paper` ran, and the lines that arrived while the
page was stale or replaying (`quiet`).

### `function hushed`

True while the page shows a snapshot (`is-stale`) or the stream replays a backlog (`is-replaying`):
arrivals then settle at once.

### `function watch`

A line's arrival is noted when it happens, not at the next frame: the stream's tick can clear
`is-replaying` in the task after the last replayed line, before the layer draws again. One
`MutationObserver`, on each pane's transcript, writing nothing.

### `function seedOf`

A glyph's seed: an FNV hash of the pane's slot, its repo and the glyph's number.

### `function capOf`

How many glyphs a pane's stack holds: its height less `HEADROOM`, in cells; a rail's is 0.

### `function place`

Before each render, every pane's offset from its group's position, as the voxel skin places its
slabs.

### `function fill`

The rain's instances, rewritten from the records: each glyph at its slot, or where it is falling;
in `--done` while the pane is done, else `--accent`; the column shifted while it tears; and the band
under the head while the pane is in error. The mesh is hidden when there is nothing to draw.

### `function rain`

The rain's one `InstancedMesh`, one draw call for every pane. `onBeforeRender` places the panes and
notes the renderer's call count; `onAfterRender` takes the difference, the rain's own draw calls.

### `export function paper`

The glass behind the panes, one quad the size of the viewport, and the rain's mesh beside it at
`api.order.paper + 1`, refilled from the records. The layer calls it when the skin arrives, when
the window is resized and when the palette changes, never per frame.

### `export function frame`

A pane's record, made the first time the pane is seen, with the lines present then as seen; and
its group, size and the foot of its head, remembered. It makes nothing.

### `function forget`

A record whose pane has left the page is freed, and its slot with it.

### `function step`

One pane, one frame: new lines while running queue a glyph each (settled at once when hushed,
quiet or reduced); the cap erases the oldest; each falling glyph moves by elapsed time; a pane
neither running nor done drains its stack by elapsed time, at least one a frame; an error's arrival
starts the tear, which ends after `TEAR_FOR`. Answers whether anything it draws changed.

### `export function tick`

Every pane's step, then one refill if anything changed. It answers `true` only while a glyph falls,
a stack drains or a tear runs: a settled screen costs no frame.

### `export function dispose`

When another skin is chosen: the records, the slots and the observer go.

### `export function inspect`

What the rain holds, for tests and a curious console: per pane, its settled and falling counts,
whether it drains, tears or shows the band; the rain's draw calls; how many times `paper` ran.
