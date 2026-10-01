# `ink/skins/gridiron.js`

The reasoning for this file, kept beside it rather than in it (decisions 18 and 19 on #429). The
source keeps its code; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the declaration or statement the notes
sit in or above, in source order. A builder who changes the code changes its note here.

### The file

```text
The gridiron (docs/skin-gridiron.md): the field itself. The page is turf with yard lines and hash
marks, every pane a stretch of it, and the football genre's states are the field's own signs
rather than the notebook's marks: a line of scrimmage under the head while the play is live, a
first-down line that advances a yard line per transcript line while the agent runs, a penalty flag
when it needs you, a fumble on an error, goalposts and end-zone hatching on a done. The playbook
draws the same three moments in chalk; here they are drawn with the default pencil, on turf.

THE DOM IS THE TRUTH. Every state read here is a class app.js already sets, and the transcript's
line count is read off the pane, never kept. Nothing here decides a state, and nothing here draws
a letter.

No colour is written in this file. Every colour is a custom property in
static/skins/gridiron/skin.css (`--paper`, `--turf-max`, `--yard`, `--gi-first`, `--gi-scrimmage`
and `--ink-<tool>`), read through `tokens` when the field is built.
```

### `export const expresses`

The genre's own signs, one per entry of the state grammar (docs/desk-ink.md §The state grammar
across skins): a strict JSON literal, read by `tests/test_fleet_ink_cues.py` (`expresses_of`) as
`cue_rows` reads the cues, and by the grammar test's `GRAMMAR_CHECK`, which passes an entry a
module expresses. `"*"` is every variant. Each name is a row of docs/skin-gridiron.md's expressions
table.

### `const EXPRESSED`, `export function marks`

The rows the field expresses, kept for the plain page: under `body.ink-off` (no canvas, no
materials) the plain sheet is the only carrier, so `marks` hands it the whole grammar; with the ink
on, the rows the field draws as flag, drive, fumble and touchdown are left out, or the field would
carry both. `marks` reads the body once, when the look is applied; the layer asks again when it
falls back to plain at runtime (`ink.js` `turnOff`).

### `const EVEN`, `export const options`

Field paint, not a hand: even pressure, a little wobble, no bow, no taper, a shade quicker than the
notebook. `paper: "--paper"` tells the layer which way the highlighter blends on each side.

### `const PAPER_FS`, `export function paper`

The whole page as one quad at `order.paper`: mown stripes every 140px (five 28px rows, one yard
line to the next) alternating between `--paper` and `--turf-max`, a blade-level grain, a yard line
in `--yard` at each stripe edge and 10px hash marks every 28px at a third and two thirds of the
width, all from the first row under the header; every pixel clamped per channel to the pair, so a
word never meets a colour `theme.check` did not see. `uLo`/`uHi` are the pair's per-channel
minimum and maximum, which is the same clamp on either side.

### `const RAIL_BELOW` … `const BALL`

The moments' numbers, the playbook's: a rail under 90px wide gets none of them; strokes draw at
900 px/s and the first-down line advances at 240 px/s; the flag's throw, the ball's hops, and each
piece's place in the 36px gutter.

### `function scrimmageOf`, `function goal`

The line of scrimmage sits 6px under the pane's head, never above the first row nor below the
pane's last 8px. The first-down line's goal is one row per transcript line past it, capped by the
pane's height.

### `function fresh`, `function settle`

One record per pane, started at its pane's state with every material at rest: nothing is thrown,
drawn or advanced on load. `drive` holds what the lines show: whether the play is live, the line
count, where the first-down line is and where it is going.

### `function bar`, `function build`

The pane's materials: the flag, the posts, the hatch and the ball as the playbook builds them (drawn
with the default pencil, not chalk), and three bars: a one-pixel sideline in `--yard` down the
pane's left edge, the line of scrimmage in `--gi-scrimmage` and the first-down line in
`--gi-first`, each two pixels tall across the pane's width. Bars are `MeshBasicMaterial` planes,
hidden until `show` decides.

### `function show`

Places everything from the record: the flag along its arc, the posts and hatch to their progress,
the ball to its hop, the scrimmage line at the head's foot while the play is live, and the
first-down line at scrimmage plus the drive's progress while the agent runs.

### `function start`, `function advance`, `export function tick`

`start` reads the pane's classes and its line count and turns each change into motion (or, when
reduced, stale or a rail, into rest); the drive's goal is recomputed on every tick, since lines
arrive without a class changing. `advance` moves everything a frame and says whether more is
coming. `tick` answers `true` only while something flies, hops, draws or advances.

### `export function inspect`

Per pane: the flag's state, the posts' and hatch's progress, the ball's state, the throws and hops,
the scrimmage line's y and the first-down line's y within the pane (or null when hidden), the
drive's numbers, and the boxes the playbook's tests read; plus `builds`, the field's first row,
the live strokes and the renderer's geometry count.
