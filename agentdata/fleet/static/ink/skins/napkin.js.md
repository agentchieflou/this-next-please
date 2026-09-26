# `ink/skins/napkin.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Napkin notes (#252, slice F of the ink epic #246): the desk written on a paper napkin.

The stock is quilted two-ply with no rules: a diamond quilting pressed into the paper, the second
ply showing where the seams are pressed through, and a fine dot emboss on each pillow. It is
drawn procedurally in the paper shader, so there is no texture to fetch. The felt tip (the
`marker`, which draws the error box) bleeds along that emboss: where its stroke crosses a seam
the ink wicks further into the paper than on a pillow, and it soaks in behind the pen as it goes.
A pane that has been idle a long time has a coffee ring under it.

The marks are the paper state grammar (plan-ink §The state grammar), and every row is a class
the page already sets. docs/skin-napkin.md maps each row onto its selector and says what the
page does not have yet (the turn's length, the count's old number).

What is drawn where:
* `paper` -- the quilted stock under the whole page. Its colours are `--paper` and
  `--paper-seam`, the darkest the shading ever goes (skins.py declares the pair, and the text's
  contrast is checked against it).
* `frame` -- per pane: the coffee ring, the felt tip's bleed and the running pen's tip. Each is
  built once per size and shown or hidden in `tick` from the page's classes and the ink layer's
  own marks, so a pane that changes state needs no new geometry.
* `tick` -- reads the page (never writes it) and `Ink.inspect()` (what is on the paper).

Colours live in skin.css as custom properties and are read through `tokens.css()`. No hex
is written here (docs/desk-ink.md §Writing a skin, rule 3).
```

A finding: a transcript line the page marks `denied` or `friction`.

### `export function marks`

Above `export function marks() {`:

The same rows for both variants: a variant changes the stock and the inks, not the grammar.

In `marks`, above `{ selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -5 },`:

A mark round the pane keeps inside it (#332): a pad of 0 or less, so the stroke and half its
width are on the napkin, not over the pane's border and cut away by the layer's clip.
idle: a pencil outline, and the name underlined in pencil.

In `marks`, above `{ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },`:

running: the name underlined in pen. The pen's tip rests at the end of it (`frame`).

In `marks`, above `{ selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves …`:

needs you: the name and the question highlighted, the choices looped in pencil. The name's
highlight is erased when it is no longer needed: a name struck through reads as an agent
that has gone.

In `marks`, above `{ selector: ".tile .ask:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", …`:

answered: the chosen answer circled in pen. Its pencil loop is erased as the choice is made,
and the question's highlight is struck through in pen when the question goes -- which is
how the layer takes back any ink. The question is struck, never the agent's name.

In `marks`, above `{ selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },`:

error: the felt tip's box round the pane, and a bang in the margin.

In `marks`, above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green check in the margin. A quiet agent's chip says idle, so the fold's own word
arrives as `is-done` (#253); `state-done` is the chip's, while one is supervised.

In `marks`, above `{ selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },`:

stale (#240): the chip's own words written in pencil as a margin note, an arrow from it to
the run's line, and a dashed pencil outline round the pane.

In `marks`, above `{ selector: FOUND, tool: "red", shape: "ellipse", pad: -4 },`:

a finding: a transcript line the agent was refused or stopped on -- the lines the page
already marks as a problem (the legal pad reads them the same way, #251). A red ellipse
round the line, the highlighter on its kind, and its own words as a pencil note.

In `marks`, above `{ selector: "#bellcount", tool: "pen", shape: "write" },`:

the header count, handwritten: the unread count on the bell.

### `export const options`

Above `export const options = { paper: "--paper", hand: true, speed: 1 };`:

`--paper` is what the layer reads to decide light or dark (the highlighter multiplies into a
light napkin). The napkin's own `paper` hook draws the stock.

### `const IDLE`

Above `const IDLE = ".tile.state-idle";`:

A pane idle a long time: idle, and its chip's age says a day or more (`ageChip` in app.js marks
that `stale`). Both are classes the page already sets.

### `const ERROR_ROW`

Above `const ERROR_ROW = ".tile.state-error";`:

The felt tip's box and the running pen's line, as the mark table has them.

### `const SOAK_PX`

Above `const SOAK_PX = 180;`:

How far behind the pen the felt tip's ink has soaked all the way in, in px of pen travel, and
how long the last of it takes once the pen has lifted.

### `const RAIL_BELOW`

Above `const RAIL_BELOW = 90;`:

A pane narrower than this is a 48px rail (shapes.js says the same).

## colours

### `function parse`

Above `function parse(css, fallback) {`:

A custom property as [r, g, b, a] in 0-1 sRGB: `#rgb`, `#rrggbb`, `rgb()` or `rgba()`.

## shaders

### `const QUILT`

Above `` const QUILT = ` ``:

The quilt, shared by the paper and the felt tip's bleed so the ink runs down the very seams the
paper shows. `p` is in page px, y down. The quilting is a diamond lattice whose seams are
18.4px apart (26 / sqrt 2), the same spacing skin.css draws with `repeating-linear-gradient`.

### `const VS`

Above `` const VS = ` ``:

Every piece is a flat quad in the layer's camera (CSS px, y down drawn at -y). `vPage` is page
px, whichever group the quad is in; `vLocal` is its own group's px.

### `const PAPER_FS`

Above `` const PAPER_FS = ` ``:

The stock, lit from the top left like the layer's own paper. It never goes darker than
`--paper-seam`, which is the darkest end of the panel the text is checked against.

### `const RING_FS`

Above `` const RING_FS = ` ``:

A cup set down on the napkin, twice: a ring with a darker rim where the coffee dried, a faint
wash inside it, and part of a second rim a little off the first. Never more than `--coffee`'s
own alpha, which skins.py composites over the seam for the darkest panel.

### `const BLEED_FS`

Above `` const BLEED_FS = ` ``:

The felt tip soaking into the quilt along the loop the marker draws round a pane: shapes.js
\`loop\` at offset \`uO\` with corner radius \`uRad\`, begun at the top left and drawn clockwise.
\`uHead\` is how far along it the pen has drawn (px), \`uTail\` how far the last of it has soaked
once the pen lifted. Where the path crosses a seam the ink runs further.

## the pieces

### `const panes`

Above `const panes = new Map();`:

What each pane has, built by `frame` and shown by `tick`. Keyed by the pane, which the layer
hands to `frame` and never replaces while the pane is on the page.

### `const soaks`

Above `const soaks = new WeakMap();`:

The felt tip's soak per pane, kept across rebuilds so a resize does not soak it in again.

### `function quad`

Above `function quad(THREE, x0, y0, x1, y1, material, order) {`:

A quad over `[x0, y0]-[x1, y1]` in its group's px, y down.

### `export function paper`

Above `export function paper({ THREE, scene, tokens, api }) {`:

The quilted stock under the whole page.

### `function loopLength`

Above `function loopLength(w, h, o, rad) {`:

The length of the loop shapes.js draws round a box of `w` x `h` at offset `o`.

### `export function frame`

Above `export function frame({ THREE, scene, tokens, api }, el, box) {`:

One pane's pieces: the coffee ring, the felt tip's bleed along the error loop, and the pen's
tip. All hidden until `show` says the page has them.

In `frame`, above `const R = rail ? Math.max(12, box.w * 0.36) : Math.min(46, Math.max(24, Math.min(box.w, …`:

Where a cup was put down: on the open paper below the transcript's first lines and clear of
the reply row at the foot, a little further in on each pane so no two rings line up.

In `frame`, above `const o = 3 - 7, loop = loopLength(box.w, box.h, o, 7);`:

The error row's loop: pad -7, so shapes.js draws it 4px in with a 7px corner (#332).

### `function markOf`

Above `function markOf() {`:

What is on the paper now, by pane: the felt tip's loop and the running pen's underline.

### `function show`

Above `function show(rec, api, marks, dt) {`:

Each piece of one pane shown as the page and the paper have it. Answers whether it is still
soaking. Reads the page; never writes it.

Above `ring.visible = el.matches(IDLE) && !!el.querySelector(AGED);`:

A pane idle a long time has a coffee ring under it. A cup is set down, not drawn: it is there
the frame the pane has been idle a day, and gone the frame the agent wakes.

Above `let soaking = false;`:

The felt tip's bleed follows its loop, and stays with it once it is struck: ink that soaked in
does not come back out. It goes only with the mark.

Above `const line = at.line;`:

The running pen's tip rests at the end of its underline once the line is drawn, and stays when
the line is struck: it is ink.

Above `dot.position.set(line.box.x - r.left + line.box.w + 8, -(line.box.y - r.top + line.box.h …`:

shapes.js `underline`: from 3px before the text to 8px past it, 1px under it, rising 1.2px.

### `export function tick`

Above `export function tick({ api }, dt) {`:

On every frame the layer draws: the pieces follow the page's classes and the marks. Asks for
another frame only while the felt tip is still soaking in.

### `export function inspect`

Above `export function inspect() {`:

What this skin has on the paper, per pane, for tests and a curious console: which pieces show,
where the ring is (in the pane's px) and how far the felt tip has soaked. Reads; changes nothing.
