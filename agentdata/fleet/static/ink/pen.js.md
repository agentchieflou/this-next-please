# `ink/pen.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The ink layer's tools (#248): how each one lays a stroke down, and the shaders that make it look
like graphite, ballpoint, felt or highlighter rather than a line.

Ported from the operator-approved prototype (`notebook-three.html`, epic #246 Decision 1). Two
halves: `geometry()` is plain arithmetic -- resample the path, give it the tool's wobble, bow,
pressure and taper -- and `makePen(THREE)` turns that into three.js meshes, materials and the
small lit pencil (the hand) that travels along a stroke while it is drawn. three.js is handed in
by `layer.js`, which is the one module that imports it, from the vendored copy, with the token.

A tool is a `kind` for the shader and its physics: `w` the width, `press` and `pvar` the
pressure and how much it varies, `wob` and `lam` the wobble and its wavelength, `bow` how much a
long stroke sags, `pad` the antialiasing margin, `wmin` how thin light pressure goes, `tin` and
`tout` the taper at each end. Colour is not here: a palette colours the inks (`layer.js` reads
them from the page's custom properties at paint time), and a skin chooses the paper.

### `const ORDER`

Above `const ORDER = { 4: 1, 5: 2, 0: 2, 1: 3, 3: 3 };`:

What is drawn over what: the highlighter under everything, graphite and its scuffs above it, ink
on top.

## the arithmetic

### `export function geometry`

Above `export function geometry(path, tool, seed, tune) {`:

One path as the tool would lay it: the points it passes through (`P`), the distance along it at
each (`D`), its length, and the triangle strip the shader draws -- a quad per step with a round
cap at each end, carrying distance, side, half-width, width and pressure per vertex.

In `geometry`, above `const T = tune ? Object.assign({}, TOOLS[tool], tune) : TOOLS[tool];`:

A table may tune a tool's hand (#253): its numbers over the tool's own, for this stroke only.

## the shaders

### `const CLIP`

Above `` const CLIP = ` ``:

The clip: a mark on a line of a transcript that has scrolled out of its box must not be drawn
outside the box, so every mesh carries the rectangle its anchor can be seen in (the viewport, cut
down by every scrolling ancestor), in CSS pixels, and the fragment outside it is discarded.

### `const STROKE_FS`

Above `` const STROKE_FS = ` ``:

One shader, five tools. Graphite takes the paper's tooth, so a pencil line is grainy where the
paper is raised and pressure fills it in. Ballpoint is steady, skips a little under light
pressure and blobs now and then. Felt (the marker) bleeds outward the longer the ink has been on
the paper and pools where the nib stopped. The highlighter has ragged ends and streaks, and is
multiplied into a light paper or screened onto a dark one. The eraser leaves a faint scuff.
`uHead` is how far the pen has got; `uErase` how far back the eraser has taken it.

### `const PAPER_FS`

Above `` const PAPER_FS = ` ``:

A skin's paper, when it has one: its colour with the tooth a pencil catches on, lit from the top
left. The notebook (#249) adds its rules and margin here; slice B needs only enough paper for the
highlighter to have something to multiply into.

## the three.js half

### `export function makePen`

Above `export function makePen(THREE, shared) {`:

Everything that needs three.js, built once per layer. `shared` holds the uniforms every stroke
reads (the device pixel ratio and the viewport's height, for the clip), so a resize writes two
numbers rather than one per mesh.

In `makePen` › `blend`, beside `if (mode === 2) { mt.blendSrc = THREE.OneFactor; mt.blendDst = THREE.OneMinusSrcColorFac …`:

screen

In `makePen` › `blend`, beside `else { mt.blendSrc = THREE.DstColorFactor; mt.blendDst = THREE.ZeroFactor; }`:

multiply

In `makePen`, above `class Stroke {`:

One stroke of one mark: its geometry in the anchor's coordinates, drawn up to `head`.

In `makePen`, above `build(path, scene, colour, mode) {`:

(Re)build from a path. The same path is the same geometry, so a redraw with nothing new is
free; a changed one keeps how far along the pen had got, as a fraction.

In `makePen`, above `function paper(colour, dark) {`:

The paper, when a skin has one: a full-screen quad drawn first, opaque.

In `makePen`, above `function model(key, ink) {`:

The hand: a small lit pencil, pen, marker or highlighter that travels along the stroke being
drawn and lifts off at the end, with its shadow on the paper. Low-poly, one per lane. Coloured
by the tool's own ink, looked up by `tint` at paint time.

In `makePen` › `constructor`, beside `this.inks = inks;`:

tool name -> [r, g, b], read at paint time by the layer

In `makePen` › `model`, above `const kind = this.chalk ? "chalk" : T.model;`:

A stick of chalk (#387) is every tool's hand, the eraser's too: flipped below as the pencil is.
