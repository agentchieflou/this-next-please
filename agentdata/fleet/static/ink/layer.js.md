# `ink/layer.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The ink layer (#248): one canvas behind the page, lanes of drawing, and marks derived from the
classes the page already sets. `ink.js` starts it once the gate says on and a skin has handed it
a mark table; `docs/desk-ink.md` is the page it implements.

THE DOM IS THE TRUTH (plan-ink ground rule 2). Nothing pushes a mark. A skin is a table -- when
this selector matches, this tool draws this shape -- and the layer watches the page: a
MutationObserver says *something changed* (and does nothing else, so a gesture's own frame is not
charged for the ink), and the next animation frame matches every row against the page. A match
that is new is a mark to draw; a match that has gone is a mark to erase (pencil) or strike
through (ink). The layer never decides a state and never writes one: its only write to the page
is the handwriting reveal's `clip-path`, on the element being written, while it is written.

DRAWN, NEVER FADED (ground rule 1). A mark arrives by being drawn, a stroke at a time at the
speed of a hand, and leaves by being erased or struck. With reduced motion every mark is drawn at
once and no hand travels.

LANES. One queue of drawing per agent's pane (`.tile[data-repo]`) plus one for everything
outside a pane (the header). Every lane advances on every frame, so two agents draw at once, and
within a lane one mark is finished before the next is begun, so one agent's marks never
interleave.

GEOMETRY. Each mark's strokes are built in its anchor's own coordinates and the mesh is put where
the anchor is. So a pane that moves -- a gutter drag, a scroll, a reorder -- moves its marks by
moving meshes, and only an anchor that changes size (or whose text wraps differently) rebuilds
its strokes. A ResizeObserver on every anchor and every lane's pane redraws inside the frame the
browser laid out, so the marks follow the gutter without the layer adding a DOM write to the
drag (plan-panes ground rule 4).

THE PAGE'S OWN DRAWING (#257). Every agent's trace is the desk's, not a skin's, and still comes
from the page: an element carrying its series (`data-ink-series`, and the minutes that stopped for
a person as `data-ink-ticks`), drawn as a mark in its pane's lane by two rows the layer owns,
`PAGE_ROWS`, after the skin's. They are drawn whenever a skin draws with ink, because that is when
the panes show the paper -- unless the skin plots the hour itself (`series: false`, the graph
paper). The canvas says which table it draws (`#ink[data-skin]`), and that is what the
stylesheet reads to let the trace's own SVG step aside.

### `const LANE`

Beside `const PEN = 900;`:

px a second at 1x: the prototype's pen speed

### `const DEG`

Beside `const DZ = 1600;`:

the hand's camera distance, in CSS px

### `const REVEAL_BLEED`

Beside `const FOLLOW_MS = 400;`:

how long a transition is followed: --motion-slow and a margin

### `const TOKENS`

Beside `const REVEAL_BLEED = 14;`:

a written line's ascenders and descenders, uncovered too

Above `const TOKENS = ["bg", "panel", "text", "line", "select", "muted", "accent", "focus", "ru …`:

The palette tokens a skin's hooks are handed, as [r, g, b] (the desk's thirteen, app.css).

### `const PAGE_ROWS`

Above `const PAGE_ROWS = [`:

The page's own rows (#257): a series is one line in pen across its element's box, and a minute
that stopped for a person a red tick through it. They are the layer's, not a skin's: drawn with
whatever table is in force, after its rows, and left on the paper when one table replaces
another. A series is not a state, so what goes is erased: its hour emptied, and there is nothing
to strike through.

### `function parseColour`

Above `function parseColour(css, THREE) {`:

A colour as the page writes one, to [r, g, b, a] in 0-1 sRGB, without a 2D context -- the desk
has none anywhere now (#257). A computed style is always `rgb()` or `rgba()`; a custom property
(a hex, a name) goes through three.js's own parser.

### `function context`

Above `function context(canvas) {`:

The context is asked for before three.js is fetched, the way the probe asks for it: a shell that
will not give one falls back without spending 163 KB on a library it cannot use.

### `class Layer`

In `constructor`, beside `this.clipped = new Set();`:

elements whose clip-path this layer wrote

In `constructor`, beside `this.inks = {};`:

tool -> [r, g, b], read from the page at paint time

In `constructor`, beside `this.mode = 0;`:

the highlighter's blend: 0 over nothing, 1 multiply, 2 screen

In `constructor`, beside `this.handModel = "";`:

the model key of the last hand shown (#387)

In `constructor`, beside `this.stale = true;`:

something on the paper changed since it was last drawn

In `constructor`, beside `this.fx = null;`:

fx.js, attached for a table that has effects (#370)

In `constructor`, above `this.back = new THREE.Scene();`:

A skin's materials (docs/desk-ink.md §Writing a skin): its ground and paper live in `back`,
drawn first, and -- when the skin asks to sample it -- into a texture its frames can read.

In `constructor`, above `this.pageRows = PAGE_ROWS.map((row, i) => Object.assign({ index: "page" + i, to: "", pad …`:

The page's own rows (#257), which a table that draws with ink is followed by.

In `constructor`, above `this.onLost = () => this.host.off("the WebGL context was lost");`:

On the page only while a table is set (`setTable`).

Above `setTable(t) {`:

------------------------------------------------------------------------ the table

In `setTable`, above `this.clear(!t);`:

One table replacing another leaves the page's own marks where they are; no table takes them.

In `setTable`, above `if (t && t.fx) import(q("/static/ink/fx.js")).then(m => {`:

Effects: their own module, fetched only by a skin that has them (docs/desk-ink.md §Budgets).

In `setTable`, above `this.rows = t ? t.marks.map(row => Object.assign({}, row, { live: new Map(), leaving: ne …`:

The skin's rows, then the page's own (#257): the traces, after the skin's marks in each lane.

In `setTable`, above `if (t) this.canvas.setAttribute("data-skin", t.name);`:

The layer's own element says which table it draws: the stylesheet lets a trace's SVG step
aside for the ink only then (app.css). Written once a table, never per frame.

In `setTable`, above `const attrs = new Set(["class", "id", "hidden", "data-tier", "data-skin", "data-skin-var …`:

The attributes the table's selectors can depend on, and the few this layer itself reads
(a skin changing, a pane hidden). Not `style`: the page writes it on every frame of a drag,
and the ResizeObserver already follows what it moves.

In `setTable`, above `this.render();`:

No table, no canvas: the page is as it was before a skin drew on it. The context lives on
for the next table.

Above `clear(all = true) {`:

Every mark off the paper at once, with no animation: the table changed, or the layer is going.
The page is left as it was found -- every clip this layer wrote is taken back. A table that
changes (`all` false) leaves the page's own marks where they are, mid-stroke or not (#257).

Above `own(m) {`:

A mark of the page's own rows (#257), not the skin's.

Above `makeApi() {`:

-------------------------------------------------------------- a skin's materials

What a skin's hooks are handed besides three.js, the scene and the camera: the viewport, the
page's state, and a way to ask for a frame. Read at call time, never kept stale.

In `makeApi`, above `get groundTexture() { return self.groundRT ? self.groundRT.texture : null; },`:

The ground and paper as a texture, for a skin that exports `sampleGround = true` -- a
frosted pane reads it at `gl_FragCoord.xy / groundSize`. Null otherwise.

In `makeApi`, above `order: Object.freeze({ ground: -30, paper: -20, frame: -10, fx: -5 }),`:

Where a skin's pieces go in the draw order: under every mark (§Writing a skin).

In `makeApi`, above `get fx() { return self.fx && self.fx.api; },`:

fx.js's helpers, once a table with effects has it attached; null otherwise (§Writing a skin).

In `makeApi`, above `panes() {`:

The panes, where they are now: `{el, repo, box: {x, y, w, h}}` in viewport CSS px.

In `makeApi`, above `request() { self.stale = true; self.backStale = true; self.kick(); },`:

Draw another frame: a hook changed something outside a call the layer made.

In `makeApi`, above `stroke(group, path, tool, opts = {}) {`:

A skin's material in a tool's own stroke (#388), from head 0: a shapes.js path in `group`'s
coordinates, `group` one a hook was handed or one under it. It dies with the group's
contents -- a resize, a palette change, the skin leaving -- and the skin draws it again in
its next call: it is never recoloured in place.

Above `hook(name, ...args) {`:

A skin's hook, called so that its mistake is the skin's: said once, where a skin author
looks, and the desk carries on drawing its marks.

In `enskin`, beside `strokes: new Set() };`:

its live material strokes (#388, `api.stroke`)

In `enskin`, beside `this.W = 0;`:

so `resize` sizes the texture

Above `kill(g) {`:

A skin's material strokes (#388) under `g`, or all of them, freed: each handle says `dead` and
touches nothing freed.

Above `empty(g) {`:

Everything in a group taken out and its GPU memory freed: a hook's call begins empty, and the
material strokes in it are dead.

Above `framePanes() {`:

The panes a skin frames: one group each, at the pane's top-left, made when the pane appears
and gone with it. Matched with the table, on the frame after the page changed.

Above `syncFrames() {`:

Each pane's frame where the pane is; built again only when its size, or its transcript's box, changed.

In `syncFrames`, above `const t = f.el.querySelector(".transcript"), q = t && t.getBoundingClientRect();`:

and where its transcript is: a card shown above it moves it in an unchanged pane (#338)

Above `watch(el) {`:

Observed once each: observing an element again re-reports its size, which is a redraw for
nothing.

Above `evaluate() {`:

Match every row against the page: new matches are drawn, lost ones leave.

In `evaluate`, above `leaving.leaveOp = null;`:

Back before the eraser reached it: the mark simply stays.

In `evaluate`, above `for (const m of Array.from(this.marks)) {`:

Marks whose paper has gone: an element that left the page takes its marks, struck or not,
with it. Nothing is left to draw them on.

Above `unqueue(m, op) {`:

Take an op back out of its lane, if the pen has not started it.

Above `clipOf(m) {`:

--------------------------------------------------------------------- the geometry

The rectangle an anchor can be seen in: the viewport, cut down by every ancestor that scrolls
and, in a pane's lane, by the pane's border box inset 1px, so no mark leaves its pane (#331).
The ancestors are found once per mark; their boxes are read every time.

Above `linesOf(el, r) {`:

The text's line boxes, in the anchor's coordinates: one per line it wraps to.

Above `sync(m) {`:

Where the mark is now, and -- when its size or text changed -- its strokes built again.
Answers whether anything about it changed, so a frame with nothing new draws nothing.

In `sync`, above `shape.tip = m.row.tip && m.state !== "leaving" && m.state !== "struck";`:

The pen's tip sits at the end while the mark is on the paper; a mark that is leaving has
had its pen lifted, and is struck or erased without it.

In `sync`, above `const series = m.el.getAttribute("data-ink-series") || "", ticks = m.el.getAttribute("da …`:

A series is read from its element each time it is measured, so the mark follows its
data the way it follows its box: new numbers are a new line, drawn whole where it stands.

In `sync`, above `const g = m.row && !m.strikeOf ? m.row.snap : 0;`:

A ruled mark sits on the viewport's grid, so where the anchor is against the grid is part
of its shape: a move by a whole square moves the mesh, anything else rules it again.

Above `under(m, r, s) {`:

Where an underline may go (#331), in the anchor's coordinates: `base` is the foot of the tallest
of its siblings on its line, and `floor` the top of the next row in its pane (none in the
header): the highest of the elements beside it that start below it, and of their words, whose
line box can stand above their element's box. Not the first in the markup: a wrapped header
puts the chip first but the taller `.oldsession` higher. Nor only those after it: the compact
tier's `order: -1` puts the name first and the pane number, before it in the markup, under it.
Read only, where `sync` already measures.

In `build`, above `const grows = !!(m.row && m.row.grow) && !m.leaveOp && (m.state === "drawn" || m.state = …`:

A growing line keeps what the pen has drawn, in px rather than as a fraction of a length that
has changed, and the pen goes back to draw on from there (#249).
A mark whose match has gone is leaving: it is struck or erased at the length it had, and grows
no more -- the refresh that takes its class away often brings the line that would grow it.

In `build`, above `if (m.state === "queued") st.setHead(0);`:

A mark already on the paper is redrawn whole at its new size; one not yet begun stays
blank until its turn.

In `build`, above `const keep = was && st.len > was.len ? Math.min(was.head, st.len) : (i === 0 ? st.len : …`:

Longer than it was: what was drawn stays drawn, the rest is the pen's to draw. A stroke that
is new or moved (the tip, at the new end) is drawn again from its start.

In `build`, above `if (more) this.push(m.lane, { t: "draw", m });`:

Drawn, or still drawing a stroke the pen has already left: the pen comes back for the rest.

Above `growth(m) {`:

How many of the row's `grow` matches have arrived in this mark's pane since it was made (#249).
Counted once each, as they arrive, so a list that drops its oldest line as it takes a new one
still counts the new one. The ones already there when the mark was made are its start.

Above `rewrite(m) {`:

A written word whose text changed after it was written (#249, the header's count): what it said
is kept on the paper beside it, as it looked, and struck through in pen; the new text is written
again by the reveal. One struck word is kept per row and element, like every struck mark.

In `rewrite`, above `if (m.state !== "drawn") return false;`:

Still being written, the reveal is uncovering the new text already.

Above `ghostOf(m, text) {`:

```text
The old text as it looked -- its own font and colour -- drawn once into a texture and set just
to the left of the element, a little apart, where a hand would have left it. Drawn by the
browser as an SVG `<text>`, never on a 2D canvas: the desk has none (#257). Its width is the
element's own text's, per letter, so the strike is laid before the image arrives; the image
lands in the texture a frame later.
```

In `ghostOf` › `img.onload`, above `if (this.stopped || rec.mesh !== mesh) return;`:

The ghost may have left the paper (its mesh freed) before its image arrived.

Above `rgb(css) {`:

----------------------------------------------------------------------- the palette

In `colours`, above `const tokens = { inks: this.inks, dark: this.dark, css: name => read(name) };`:

The palette as a skin's hooks read it: every token as [r, g, b] in 0-1, the inks, and the
raw custom property by name for anything else.

In `colours`, above `const papered = !!(paperCss || (this.skin && (this.skin.hooks.paper || this.skin.hooks.g …`:

Something opaque under the marks -- a paper, the skin's or the table's -- and the
highlighter multiplies into it (screens onto it when dark); over nothing it is a swipe.

In `colours`, above `this.skin.dirty = this.dirty.geom = true;`:

Every frame is made again too, in `syncFrames`, which a palette change alone did not reach (#388).

Above `instant() {`:

------------------------------------------------------------------------- the lanes

In `handOf`, above `L.hand.chalk = this.table.hand === "chalk";`:

A stick of chalk (#387) is taken up at the hand's next model, so a new table changes it there.

Above `run(L, dt) {`:

A lane runs `dt` seconds of its queue: segments are consumed in order, and a segment that
finishes early hands what is left of the frame to the next, so a fast hand is not slowed to
one stroke a frame.

In `compile`, above `const once = fn => ({ step: dt => { if (!m.dropped) fn(); return dt; } });`:

A mark can leave the page while its op runs; what the op does at its end is then not done.

In `compile`, above `if (m.leaveOp || m.state === "leaving" || m.state === "struck") return [];`:

A draw queued before the mark began to leave (a growing line's rest) is not drawn after it.

In `compile`, above `const row = m.row, old = row.history.get(m.el);`:

One struck mark kept per row and element: the history stays visible, and a state that
comes and goes all day does not stack a hundred strikes on one name.

Above `lift(m) {`:

A mark that is going stops being worked: its pen-tip dot (#249) is lifted before it is struck
or erased.

Above `world(m, p) {`:

A point of a mark's stroke on the viewport, or null for a mark that is not on the glass -- a
hidden pane's marks are finished at once, and no hand travels to where it is not.

Above `clip(m, f) {`:

The handwriting reveal: the element's own text uncovered left to right while the pen moves
along it -- the text is the page's, only its `clip-path` is this layer's, and only until the
line is written.

Above `kick() {`:

------------------------------------------------------------------------ the frame

Above `now() {`:

Inside the frame the browser just laid out (a ResizeObserver callback): measure and draw now,
so the marks are where the panes are on the frame that shows the panes.

In `now`, above `this.prepare();`:

Geometry only. Matching the table can make a mark, and a mark observes its element; an
observation begun inside the observer's own callback is a loop the browser reports as an
error. The table is matched on the next animation frame instead.

Above `prepare() {`:

Everything a frame needs measured before it is drawn. Anything that moved, was built again or
changed colour makes the frame stale; a frame that is not stale is not drawn at all.

In `prepare`, above `this.skin.dirty = false;`:

The ground and the paper, made again from nothing: on the skin's arrival, a resize, or a
palette change. Frames are made in `syncFrames`, per pane.

In `frame`, above `let ticking = false;`:

A skin's own animation. It asks for the next frame by answering true; under reduced motion
it is still called on the frames the layer draws, and is never given a loop of its own.

Above `refresh() {`:

---------------------------------------------------------------- what tests can see

In `inspect`, above `const len = m.strokes.reduce((a, s) => a + (s.dead ? 0 : s.len), 0);`:

The page's own marks (#257) are listed apart, so a skin's table reads as itself.

In `inspect`, above `bounds: m.strokes.filter(st => !st.dead).map(st => st.bbox()).filter(Boolean).map(b =>`:

Each stroke's extent on the viewport, so a test can see where the ink is (#253), as it is
drawn: cut to the mark's clip (#331). A stroke cut away whole has none.

Above `sample(box) {`:

How many pixels in a box of the viewport hold ink, read back from a frame drawn for the
purpose -- the drawing buffer is not kept between frames.

In `stop`, above `}`:

a lost context has nothing left to free
