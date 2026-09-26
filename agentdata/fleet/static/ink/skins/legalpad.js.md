# `ink/skins/legalpad.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
The legal pad (#251, slice E of the ink epic #246): "the yellow-page version" the operator asked
for, which is a yellow legal pad (plan-ink Decision 4). Canary stock, blue rules on the page's
28px baseline, a double red margin down every pane, and the gummed band a pad is bound by across
the top of the page. The highlighter is orange-pink, because the palette's amber highlighter
vanishes into canary.

docs/desk-ink.md §The legal pad is the page this implements, and §Writing a skin the contract it
keeps: no static import (three.js is handed in), colours only from the page's custom properties
(`--paper`, `--rule`, `--margin`, `--glue` and `--ink-<tool>`, all in this skin's own skin.css),
and nothing written to the page. `skin.css` is also the look `body.ink-off` falls back to.

THE STATE GRAMMAR (plan-ink §The state grammar) is the table in `marks`, one or more rows per
state, every selector a class or attribute app.js already sets. Two of the grammar's marks are
not rows, because the layer has no shape for them yet, and are drawn here instead, from the same
classes (plan-ink says C builds them; this is the skin-local copy slice K consolidates):
* the running pen's tail: the underline grows with the turn -- one step per transcript line the
  turn adds -- and the pen-tip dot sits at its end. When the turn ends it is struck, in pen, with
  the underline it grew from;
* the header count: when the number changes, the old one is struck where it stood, beside the
  new one.
```

### `const GLUE`

Beside `const BASE = 28;`:

the page's baseline: one rule every 28px

### `const MARGIN`

Beside `const GLUE = 10;`:

the gummed band across the top of the page, in px

### `const RAIL`

Beside `const MARGIN = [25, 29];`:

the double red margin, px in from a pane's left edge

### `const GROW`

Beside `const RAIL = 90;`:

under this a pane is its 48px rail (shapes.js), with no margin

### `const TAIL_MAX`

Beside `const GROW = 6;`:

px the running pen's tail grows by, for each line of the turn

### `const STRIKE_S`

Beside `const TAIL_MAX = 132;`:

and the furthest it reaches past the name

### `const RUNNING`

Beside `const STRIKE_S = 0.22;`:

seconds a strike through the tail or the count takes to draw

### `const HAS`

Above `const HAS = (() => {`:

The selectors that read a pressed choice. `:has` is how "a choice was made" reaches the question
above it; an engine without it keeps the question highlighted until the card goes.

### `export function marks`

Above `export function marks() {`:

The grammar, row by row. Rows are queued in this order in each pane's lane.

In `marks`, above `{ selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -5 },`:

idle: a pencil outline round the pane and a pencil line under its name.

In `marks`, above `{ selector: RUNNING, tool: "pen", shape: "underline" },`:

running: a pen line under the name (its tail and the pen-tip dot are `tick`'s).

In `marks`, above `{ selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },`:

needs you: the name and the question highlighted, and a pencil loop round each choice.

In `marks`, above `{ selector: '.tile .ask:not([hidden]) .ask-choice[aria-pressed="true"]', tool: "pen", sh …`:

answered: the choice made is circled in pen. The question's highlight leaving is the layer's
strike, in pen, along each swipe -- the question struck, never the agent's name.

In `marks`, above `{ selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },`:

error: a red marker box inside the pane, and a bang in its margin.

In `marks`, above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green check in the margin. `is-done` is the fold's own word (#253): the chip shows a
finished, unsupervised agent as idle, so `state-done` alone is almost never on the page.

In `marks`, above `{ selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },`:

stale (#240): the chip's own words as a pencil note, a dashed pencil outline round it, and an
arrow to the run line -- the line that says which session and run this transcript is.

In `marks`, above `{ selector: FOUND, tool: "red", shape: "ellipse", pad: -4 },`:

a finding: a transcript line the agent was refused or stopped on, ringed in red, its kind
highlighted, and its own text written out.

In `marks`, above `{ selector: "#bellcount", tool: "pen", shape: "write" },`:

the header count, handwritten (a change is struck and rewritten by `tick`).

### `export const options`

Above `export const options = { paper: "--paper", hand: true, speed: 1 };`:

`--paper` is what the layer reads to know the stock is light, so the highlighter multiplies.

## drawing kit

### `function rng`

Above `function rng(seed) {`:

A seeded generator, so the glue's ragged edge is the same edge on every redraw.

### `function srgb`

Above `function srgb(THREE, tokens, name, fallback) {`:

One of this skin's custom properties as [r, g, b] in 0-1 sRGB, else a palette token (already
that). Colours are read from the page at paint time, never written here (desk-ink.md rule 3).

In `try { return new THREE.Color().setStyle(css).getRGB({}, THREE.SRGBColorSpace); } catch ( …`:

below

### `function flat`

Above `function flat(THREE, c) {`:

Both sides: a ribbon's quads wind whichever way its polyline turns.

### `function ribbon`

Above `function ribbon(THREE, pts, w) {`:

A polyline as a ribbon of quads, `w` px wide, in page coordinates (y down) -- the layer's camera
draws a point `y` px down the page at -y.

### `const STOCK_VS`

Above `const STOCK_VS = "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(p …`:

The stock: canary, with the tooth a pencil catches on. Colour in sRGB, written as it is read.

## the paper

### `export function paper`

Beside `let paperScene = null;`:

kept for `tick`: the struck count is drawn on the paper

Above `export function paper({ THREE, scene, tokens, api }) {`:

The page is the pad: canary stock, the gummed band across its top, and a blue rule every 28px
below the header. Called when the skin arrives, on a resize and on a palette change.

In `paper`, above `const c = srgb(THREE, tokens, "--paper", tokens.bg);`:

The uniform is the property's sRGB, written as it is read: the shader does no conversion.

In `paper`, above `const r = rng(251), foot = [];`:

The gummed band, with the ragged foot glue has where it soaked into the top sheet.

In `paper`, above `const head = document.querySelector("header");`:

The rules, from the first baseline under the header to the foot of the page.

In `paper`, above `if (!(tokens.css("--paper") || "").trim()) waitForSheet();`:

The skin's stylesheet can arrive after the module: the paper is drawn again when it does.

## the panes

### `let builds`

Beside `const panes = new Map();`:

pane -> its group and its running pen, for `tick`

### `export function frame`

Beside `let builds = 0;`:

frames built so far, for `inspect`

Above `export function frame({ THREE, scene, tokens, api }, el, box) {`:

One pane's sheet: a hairline where its edge is, and the double red margin down its left. Under
the transcript the rules are the transcript's own (#338): the page's rules are covered with plain
stock, and a rule is drawn every BASE up from the transcript's bottom edge, where its rows end.

## the running pen

### `function lastLine`

Above `function lastLine(el) {`:

The last line of a pane's transcript: where the turn has got to.

### `function linesSince`

Above `function linesSince(el, since) {`:

Lines added to the transcript since `since`, walking back from the end.

### `function underlined`

Above `function underlined(repo) {`:

Whether the layer has drawn this pane's running underline yet: the tail begins where the pen
finished it, never before.

### `function tailY`

Above `function tailY(repo, rr, pane) {`:

The height, on the viewport, of the layer's underline under the name (layer.js `under`, shapes.js
`underline`, #331): 2px under the tallest box on the name's line, and never lower than 3.4px over
the next row -- the first box below the name, or its words, which can stand higher. Read only.

### `function runningPen`

Above `function runningPen(THREE, tokens, api, el, p, dt) {`:

One pane's tail and pen-tip dot: answers whether it wants another frame.

Above `run.waited += dt;`:

A pen that never arrives (a table changed under it) is not waited on for ever.

Beside `if (!run.shown) return on;`:

the pen is still on its way: look again

Above `const y = visible ? tailY(repo, rr, el) - pr.top + 1.2 : 0;`:

Where the layer's underline ends (shapes.js `underline`, placed by #331): the tail goes on from
there, at that height, and stops where the layer stops a line that grows: 14px short of the
pane's right edge (#332). It used to sit 2.2px under the name's own box, through the chip.

Above `run.box = visible ? { x: pr.left + x0 - 0.9, y: pr.top + y - 1.3, w: len + 3.8, h: 3.8 } …`:

The ink's extent on the viewport: the line (1.45px wide) and the dot (r 1.9) at its end.

## the header count

### `const DIGITS`

Above `const DIGITS = {`:

Digits as a hand writes them, in a 5 x 9 box: the struck count is drawn, not typeset.

### `function headerCount`

Above `function headerCount(THREE, tokens, api, dt) {`:

The count in the header, watched: when it changes, the old number is kept where the hand wrote
it, beside the new one, and struck through in pen. One struck number is kept, like one struck
mark per element in the layer.

## the frame

### `export function tick`

Above `export function tick({ THREE, tokens, api }, dt) {`:

Every frame the layer draws: the running pens and the header count follow the page. Another
frame only while a strike is being drawn -- an idle desk draws nothing.

### `export function inspect`

Above `export function inspect() {`:

What this skin draws of its own, for tests and a curious console -- the same module the page
loaded, imported again by its URL: each pane's running pen, and the struck header count.

In `inspect`, above `tailBox: p.run && p.run.shown && p.run.box ? Object.assign({}, p.run.box) : null,`:

The tail and its dot on the viewport (#332), while the pen is on the page.

### `export function dispose`

Above `export function dispose() {`:

The skin is going: the layer frees what is in its scenes; forget what this module kept.
