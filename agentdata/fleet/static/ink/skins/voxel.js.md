# `ink/skins/voxel.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Voxel on three.js (#256, slice J of the ink epic #246): the depth the CSS skin (#156) faked with
inset shadows and an SVG sprite, made real. `docs/skin-voxel.md` is the page this implements;
`static/skins/voxel/skin.css` keeps the surfaces this reads and the room the page leaves for what it
draws; under `body.ink-off` voxel is the one plain look every skin shares (#257).

WHAT IS DRAWN. Three materials, and so three draw calls, however many agents there are:

* the ground -- the dirt (netherrack, endstone) as a floor of 32px voxels, one instance each;
* the slabs -- each pane's frame: the panel block the text is read on (its face is exactly the
  variant's composited panel, `--voxel-panel`, so theme.check's pair is the rendered colour),
  its drop shadow, the accent strip down its left edge as a column of cubes, and the three
  sockets at the top of that strip the status stack sits in;
* the stacks -- per pane, a stack of up to three blocks in those sockets, showing the pane's
  state (§the grammar in docs/skin-voxel.md): running turns the top block a quarter at a time,
  needs you raises it, an error cracks it, done sets the stack full. A stale session leaves a
  pebble on top, and a finding in the transcript an ore fleck in the bottom block.

ONE DRAW CALL PER MATERIAL. Every voxel of a material is an instance of one InstancedMesh. A
pane's voxels are built in the pane's own coordinates and carry the pane's slot; where the pane
is now is a uniform (`uPane[slot]`), written in the mesh's `onBeforeRender` from the group the
layer put at the pane's top-left. So a gutter drag moves every slab by rewriting a few
uniforms, inside the frame the browser laid out (the layer's ResizeObserver path), and only a
pane that changes size rebuilds its instances -- in `frame`, which the layer calls then.

THE DOM IS THE TRUTH. The stack is read from classes `app.js` already sets: `state-<state>`
and `needs-human` on the pane, `.oldsession` not hidden, `.transcript li.friction` /
`li.denied`. Nothing here sets a class or writes the page.

DRAWN, NEVER FADED. Marks come from the table below and the layer draws them. The materials may
animate -- a block turning, rising, settling -- and under reduced motion they are simply where
they end up. An idle desk with no agent running asks for no frame at all.

No static import (the run token), no hex in this file (colours are `tokens`, or the skin's own
custom properties read through `tokens.css`), no markup.
```

------------------------------------------------------------------------------ the mark table

The state grammar's marks. Each row's selector is a class or attribute the page already sets.

### `const MARKS`

Above `{ selector: ".tile.needs-human .head .repo", tool: "marker", shape: "underline" },`:

needs you: the name underlined in marker. The stack's block rises too.

Above `{ selector: ".tile.state-error", tool: "red", shape: "bang" },`:

error: a bang in the pane's margin (#330). The stack's block cracks.

Above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green check in the pane's margin (#330). The stack is set full. `is-done` is the fold's word
for a finished agent nothing supervises, whose chip says idle (#253, #333).

Above `{ selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", dash: t …`:

stale (#240): the old-session chip outlined in dashed pencil. A pebble on the stack.

Above `{ selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "green", shape: "loop", pa …`:

answered: the choice pressed in the question card, looped in green.

Above `{ selector: ".tile .transcript li.friction .v, .tile .transcript li.denied .v", tool: "r …`:

a finding: the line where the agent stopped or was refused, underlined in red. Ore in the stack.

### `export function marks`

Above `export function marks() {`:

Every variant draws the same grammar: a state means the same thing in every world (#4).

## the sizes

### `const STRIP`

Beside `const GROUND = 32;`:

one ground voxel, the CSS skin's 8px art at 4x

### `const CELL`

Beside `const STRIP = 10;`:

the pane's left border, where the accent strip and the stack live

### `const SOCKETS`

Beside `const CELL = 10;`:

one stack block

### `const EDGE`

Beside `const SOCKETS = 3;`:

the stack's height, in blocks

### `const DROP`

Beside `const EDGE = 2;`:

the pane's other borders: the slab's bevel

### `const LIFT`

Beside `const DROP = 4;`:

the drop shadow under a pane

### `const TURN_EVERY`

Beside `const LIFT = 5;`:

how far "needs you" raises the top block

### `const TURN_FOR`

Beside `const TURN_EVERY = 3;`:

seconds between a running block's quarter turns

### `const SLOTS`

Beside `const TURN_FOR = 0.6;`:

seconds a quarter turn takes

### `const PER_STACK`

Beside `const SLOTS = 64;`:

panes a desk can frame at once; slot 0 is the page itself

### `const LIGHT`

Beside `const PER_STACK = 6;`:

blocks 0-2, the crack's other half, the pebble, the ore

Above `const LIGHT = (() => {`:

The one light: from the top left and in front, the direction the layer's own sun comes from.

## the one shader

A voxel is a box with a chamfered face: the face inset by `bevel`, four 45-degree bevels round
it, the sides and the back. Its size is per instance (`aSize`, `aBevel`) and built here in the
shader, so a bevel is the same number of pixels on a 10px cube and on a 900px panel. Shading is
relative to the face: a face turned square to the camera is exactly its colour, so the panel's
face is the colour theme.check measured; a bevel towards the light is lighter, one away darker.
Colours are passed through as the page's sRGB -- no colour-space conversion -- for that reason.

### `function template`

Above `function template(THREE) {`:

The template voxel: `position` is (x sign, y sign, ring) -- ring 0 the inset face, 1 the outer
rim at the bevel's foot, 2 the back -- and each face its own flat normal. Wound by checking each
quad against its normal on a reference box, so no face is culled by a slip of the pen.

Above `const c = (s, k) => [ax + bx * s, ay + by * s, k];`:

(ax, ay) is the side's outward direction, (bx, by) runs along it.

Beside `quad([c(-1, 0), c(1, 0), c(1, 1), c(-1, 1)], [ax * r2, ay * r2, r2]);`:

the bevel

Beside `quad([c(-1, 1), c(1, 1), c(1, 2), c(-1, 2)], [ax, ay, 0]);`:

the side

## colours

### `function parse`

Above `function parse(s) {`:

A colour the page wrote, `#rgb`, `#rrggbb` or `rgb(...)`, as [r, g, b] in 0-1; null if none.

### `function surfaces`

Above `function surfaces(tokens) {`:

The skin's own surfaces, from its stylesheet (`--voxel-*`), each falling back to a palette token
so a variant that forgot one still draws.

### `function jitter`

Above `function jitter(i, j) {`:

A voxel's shade among its neighbours: the texture the CSS art drew in four browns.

## the state

### `const S`

Beside `panes: new Map(),`:

pane element -> {el, group, slot, w, h, stack}

Beside `slots: new Array(SLOTS).fill(null),`:

slot -> pane element (slot 0 is the page)

Beside `uPane: [],`:

the uniform array, shared by the three materials

Beside `dirty: false,`:

the slabs' instances want building again

Beside `drawCalls: 0,`:

what the renderer counted in the last back pass

### `function mesh`

Above `function mesh(THREE, n, order) {`:

One InstancedMesh with room for `n` voxels, its per-voxel attributes beside the matrix.

Beside `m.frustumCulled = false;`:

the instances are placed in the shader

### `function writer`

Above `function writer(THREE, m) {`:

A writer over a mesh's instances, from index 0.

Above `put(slot, x, y, w, h, d, bevel, c, turn = 0, tilt = 0) {`:

A voxel `w` x `h` x `d` centred on (x, y) px down the page -- y is drawn at -y.

## the hooks

### `export function ground`

Above `export function ground(ctx) {`:

The floor: a voxel every 32px over the whole viewport, rebuilt on a resize or a palette change.

### `export function paper`

Above `export function paper(ctx) {`:

The slabs and the stacks: two meshes over the paper, filled from the panes the frames hook has
met. Called on the skin's arrival, a resize and a palette change; the panes are kept across.

In `paper`, above `S.slabs.onBeforeRender = place;`:

Where the panes are, written just before the slabs draw: the layer has put each pane's group
at its top-left by then, in this same frame.

In `paper`, above `S.stacks.onAfterRender = renderer => { S.drawCalls = renderer.info.render.calls; };`:

The renderer's own count of this back pass, taken after its last draw: the test's
"one draw call per material" reads the renderer, not this file's opinion of itself.

### `export function frame`

Above `export function frame(ctx, el, box) {`:

One pane's frame. Nothing is drawn into the pane's own group -- that would be a draw call per
pane -- it is remembered, and its voxels are built into the shared slabs.

In `frame`, beside `if (slot < 0) return;`:

more panes than slots: the rest are framed by CSS alone

### `export function tick`

Above `export function tick(ctx, dt) {`:

Every frame the layer draws: the stacks follow the page's classes, and a block that is turning,
rising or settling asks for the next frame.

## the slabs

### `function forget`

Above `function forget() {`:

Panes the layer has let go of: their groups are no longer on the paper.

### `function build`

Above `function build() {`:

Every pane's frame, in its own coordinates: its shadow, its panel, its sockets and its strip.

Above `const parent = S.slabs.parent, old = S.slabs;`:

A desk that grew past the room: a bigger mesh in the same place.

Beside `put.put(slot, w / 2, h / 2 + DROP, w, h, 6, 0, c.edge);`:

the shadow

Beside `put.put(slot, STRIP + (w - STRIP) / 2, h / 2, w - STRIP, h, 12, EDGE, c.panel);`:

the panel

Beside `for (let k = 0; k < SOCKETS; k++) {`:

the sockets

Beside `for (let k = 0; k < n; k++) {`:

the strip

### `function place`

Above `function place() {`:

The panes' offsets, from the groups the layer placed. Uniforms are uploaded after this, in the
draw it precedes, so the slabs are where the panes are on the frame that shows the panes.

## the stacks

A pane's stack, from its classes. `level` is how many blocks are in the sockets: one while it
is idle, two while a turn is in hand, three when it is done. The top block wears the state's
colour, and its response -- turned, raised, cracked -- is what reads at a glance.

### `function read`

Above `function read(p) {`:

What the page says of this pane now. True when anything changed.

Above `if (state === "idle" && el.classList.contains("is-done")) state = "done";`:

A finished agent nothing supervises: the chip says idle, the fold says done (#333).

### `function stacks`

Above `function stacks(dt, changed) {`:

Every stack's voxels, moved on by `dt`. True while a block is still on its way.

Beside `const v = 40 * dt;`:

px a second: a block, not a jump

Beside `const cy = k => (SOCKETS - 1 - k) * CELL + CELL / 2;`:

block k from the bottom

Above `put.put(slot, x - 2.6, y, CELL / 2 - 0.6, CELL, CELL, 1, tone, 0, 0.14);`:

Cracked: two halves, pulled a pixel apart and knocked off square.

Above `put.put(slot, x + 1, topY - CELL / 2 - 1.5, st.stale && p.w ? 4 : 0, 3, 4, 0.5, S.tokens …`:

Stale: a pebble on top. A finding: an ore fleck in the bottom block.

### `function schedule`

Above `function schedule() {`:

A running block turns a quarter every few seconds. Between turns the desk draws nothing: the
next turn is one timer, and a request for a frame when it comes -- never a loop.

## for the tests

What is on the paper, as the renderer and this module see it. The layer's `Ink.inspect()` shows
the marks; this shows the materials.
