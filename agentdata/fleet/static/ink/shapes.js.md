# `ink/shapes.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The ink layer's shapes (#248): where a mark's strokes go, computed from the page's own boxes.

Pure geometry. Nothing here reads the page or touches three.js: `layer.js` measures the anchor
(`getBoundingClientRect`, and a Range over its text for `lines`) and hands each function a box
in the anchor's OWN coordinates -- its top-left corner is 0,0 -- so a pane that moves under a
gutter drag moves its marks by moving their meshes, and only a pane that changes size rebuilds
them. Every function answers a list of paths, `{pts: [[x, y], ...]}` plus what the pen should
know about each (`w` a width of its own, `smooth` to curve through the points, `nobow` for a
stroke that must not sag, `wob` to scale the tool's wobble). An empty list means "nothing to
draw here", never an error: a box with no size is an element that is not on the glass.

The shapes are the prototype's (the operator-approved `notebook-three.html`), with the desk's
one special case written down rather than assumed: a box narrower than 90px is a pane's 48px
rail, and a margin mark goes down its middle rather than into a margin it has not got.

`PAGE_SHAPES` are the page's own (#257): a series drawn from its element's data rather than its
box alone, for the layer's own rows. A skin's table cannot name them.

### `export function rng`

Above `export function rng(seed) {`:

A seeded generator, so the same element's outline wobbles the same way on every redraw -- a mark
that re-rolled its hand on every resize would visibly crawl.

### `function loopPath`

Above `function loopPath(r, o, rad, over) {`:

One continuous stroke round a box, rounded at the corners and run a little past where it began,
the way a hand closes a loop.

### `function margin`

Above `function margin(r) {`:

The margin a check, a bang or a cross is written in: the left padding of a pane, or the middle of a rail.

### `export const SHAPES`

Above `export const SHAPES = {`:

Each shape: `(m) => paths`, where `m` is what `layer.js` measured -- `m.box` the anchor in its
own coordinates, `m.lines` its text's line boxes (for `lines`), `m.to` the target of an arrow,
`m.pad` the row's own padding, and `m.seed` this mark's seed.

Above `outline(m) {`:

Four pencil lines round the box, each overshooting its corner a little.

Above `divider(m) {`:

A rule across the foot of the box, stopping short of either side.

Above `underline(m) {`:

A line under the text, a hair past both ends of it. `m.grow` px more on the right when the row
grows (#249: the running agent's line lengthens with its turn), never past `m.limit`, and with
`m.tip` a pen-tip dot sitting at its end, or with `m.cap` an arrowhead or a bar (#385). It
sits 2px under `m.base`, the foot of the tallest box on its text's line (a chip beside a name),
so a line past the text's end passes under its neighbours' words; and never lower than 2px over
`m.floor`, the top of the next row (#331).

Above `lines(m) {`:

A highlighter pass along every line the text wraps to, as wide as the line is tall.

Above `loop(m) {`:

One rounded stroke round the box, closed past its start.

Above `ellipse(m) {`:

A loose ellipse round the box, drawn a little more than once round.

Above `ring(m) {`:

A tight O round a small box (a pane's number, #386), about 1.1 turns, spiralling out a hair:
it hugs the box, so it never reaches the name 8px beside it.

Above `strike(m) {`:

A line through the box: across the middle of a line of text, corner to corner of a tall box,
a short slash through a small one. Also how an ink mark leaves (`strikeOver`).

Above `check(m) {`:

A tick in the margin.

Above `bang(m) {`:

An exclamation mark in the margin: a stroke and a dot.

Above `cross(m) {`:

An X in the margin (#386): two 14px strokes, the second across the first.

Above `arrow(m) {`:

From the left of the box to the foot of its target (`to` in the row), curving on the way.

Above `write() {`:

The handwriting reveal is not strokes: `layer.js` uncovers the element's own text left to
right, with the pen travelling along it. It has no paths of its own.

### `export const PAGE_SHAPES`

Above `export const PAGE_SHAPES = {`:

The page's own shapes (#257), drawn by the layer's own rows and never named in a skin's table: a
series read from its element's data. `m.values` are its heights, oldest first, each a fraction of
the box (0 nothing, 1 the whole height); `m.ticks` are the slots a tick goes through.

Above `series(m) {`:

The hour as one line, left to right through every slot. A slot with anything in it is never
flat: a pixel above the floor is "it was awake", which is the difference between a quiet hour
and no hour at all (#218). No bow and little wobble, because this line is data.

Above `ticks(m) {`:

A stroke top to bottom through each slot that stopped for a person.

### `export function snap`

Above `export function snap(paths, shape, b, at, g, o = {}) {`:

Ruled strokes on a grid (#253, the graph paper): a row with `snap` has its straight strokes put
on the grid's lines, which are every `g` px of the viewport, where the skin's paper draws them.
`at` is where the anchor's top-left is on the viewport, so the paths -- in the anchor's own
coordinates -- are moved there, ruled, and moved back.

A divider moves across onto the nearest line. An outline keeps inside its box (#331): each edge
goes onto a line in the box's padding band -- `o.band`, the px between its border box and its
content box, left, top, right, bottom -- or, where that band is narrower than a square, down
the band's middle, unruled; every end moves with the box edge nearest it and stops at the
border box, so its corners still cross and nothing is drawn over the words or past the pane.
An underline goes to the first line in [`o.base` + 2, `o.floor` - 2] (its text's foot and the
next row's top, as `underline` has them), and stays where it is when there is none. A ruled
stroke does not sag or wander: it is drawn to a ruler.

### `export function strikeOver`

Above `export function strikeOver(boxes, highlighter, seed) {`:

How an ink mark leaves: struck through with one pen line. A highlighter's swipes are struck one
by one, along each; anything else is struck across the box its strokes cover together. `boxes`
are the strokes' own bounding boxes, in the anchor's coordinates.
