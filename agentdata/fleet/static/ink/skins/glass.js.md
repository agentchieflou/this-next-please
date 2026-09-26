# `ink/skins/glass.js`

The reasoning that used to be this file's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries code, and inline `/** @type {X} */ (expr)`
casts where `tsc` needs them, and nothing else.

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Glass on three.js (#254, slice H of the ink epic #246): a lit mesh ground, frosted panes that
sample it through a blur, lit glints and shadows, and the state grammar glass never had.

The CSS skin (`static/skins/glass/skin.css`) painted glass with `backdrop-filter` over three
radial gradients. That stylesheet stays, for layout and typography and for `body.ink-off`, where
it is still the whole look. With ink on, this module draws the material instead:

* THE GROUND is a mesh: a plane of a few hundred vertices whose height drifts on slow waves, lit
  from the top left like the pane's glint. The colour on it is the stylesheet's own mesh -- the
  same three blobs, the same places, the same falloff (`--glass-mesh-1..3`, read at paint time)
  -- so the frost composites to what skins.py declared. It drifts only when motion is allowed,
  at a rate the desk can afford (`GROUND_FPS`, backing off when a frame is dear), never faster
  than a wave you would notice from the corner of your eye.
* THE PANE is frosted: each `.tile` gets one mesh that reads the layer's ground texture
  (`sampleGround`) through a blur in its own fragment shader -- a gaussian disc of taps, the
  CSS `blur(18px)` -- saturated the way `saturate(140%)` is, and the variant's `--glass-fill`
  laid over it. Its edge, its top glint (brighter where the light is) and its shadow are drawn in
  the same pass. The page's `.tile` goes transparent (skin.css, ink on only), so what three.js
  drew is what the text is read on, and the contrast test reads it back from the frame.
* THE STATES. Glass has no paper, so it has no pencil. Its marks are the palette's inks on the
  frost -- a highlighter, a pen, a marker, the red and green pens -- from the mark table below,
  drawn and struck by the layer like every skin's. The pane itself answers too: its rim lights up
  in the state's colour, drawn round the pane from the top, and runs back the way it came when
  the state goes -- drawn, never faded, even for a material. A running agent's top glint travels.
  docs/skin-glass.md has the grammar as a table.

The rules this keeps (docs/desk-ink.md §Writing a skin): no static import; no class set and
nothing written to the page -- a pane's classes are read in `tick` and never decided here; every
colour from `tokens` and custom properties, none in this file; everything under `api.order`.
```

The mesh's geometry: where skin.css puts each blob, in viewport fractions, and its ellipse's
radii. The same three places in every variant (skin.css says so, and a test holds the two
together). A blob's colour stop is at 0% and it is gone at the end of its ray, as in the CSS: the
width #218's drawn ground always showed, which #257 made the stylesheet's own.

### `const DRIFT`

Above `const DRIFT = 0.035;`:

How far a blob's centre drifts, in viewport fractions, and how long one lap takes (s). Slow
enough that the ground is never the thing on the screen that moves.

### `const WAVE_H`

Above `const WAVE_H = 9;`:

The ground's waves: height in CSS px and wavelength. The slope they make is what the light
reads, so these set how lit the mesh looks -- and how far a pane's colour can move with it.

### `const LIGHT`

Above `const LIGHT = 0.3;`:

How much of the light's shading reaches the colour: a mesh you can see, a range that holds.

### `const GROUND_FPS`

Above `const GROUND_FPS = 30;`:

The frame rate the ground drifts at when motion is allowed, and the most it backs off to. A
frame that took long (software rendering, a busy page) stretches the gap to several times its
own cost, so the ground never takes more than a fraction of the page's time.

### `const BLUR`

Above `const BLUR = 18;`:

The pane: its CSS blur (a gaussian's sigma, px), saturation, and how far past its box the mesh
reaches for its shadow and its rim (px). CSS's `0 12px 32px` shadow.

### `const RIM_IN`

Above `const RIM_IN = 0.6;`:

A rim is drawn round the pane in this long (s), and runs back in this long.

### `const RUN_LAP`

Above `const RUN_LAP = 4.5;`:

A running agent's glint: one lap of the top edge in this long (s).

### `export function marks`

Above `export function marks() {`:

The mark table. Only classes and attributes app.js already sets (ground rule 2); docs/skin-glass.md
is the same table in prose. No pencil: graphite needs a paper's tooth, and glass has none.

In `marks`, above `{ selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },`:

needs you: the name, and every open question, under the highlighter

In `marks`, above `{ selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: …`:

answered: the choice picked, circled in pen (struck if another is picked)

In `marks`, above `{ selector: ".tile.state-running .chip", tool: "pen", shape: "underline" },`:

running: the chip underlined in pen

In `marks`, above `{ selector: ".tile.state-error", tool: "marker", shape: "bang" },`:

error (and blocked, which the page colours alike): a bang in the margin in marker

In `marks`, above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green tick in the margin. `is-done` is the fold's word for a finished agent nothing
supervises, whose chip says idle (#253, #333); the paper skins key on both.

In `marks`, above `{ selector: ".tile .scopereport.outside:not([hidden])", tool: "red", shape: "ellipse", p …`:

stale (#240): no mark. The note's own words say it; a dashed outline round it, even at pad 0,
ran over the chip's age above it in a compact pane (#332), and the words come first.
a finding: edits outside the scope it was given (#168), ringed in red

### `export const options`

Above `export const options = { hand: false, speed: 1 };`:

No lit pencil travels over glass: nothing here is written by hand.

### `export const sampleGround`

Above `export const sampleGround = true;`:

Frames get the ground as a texture: the frost is what is behind it, blurred.

## the state

### `let mesh`

Above `let mesh = null;`:

What `tick` animates, and what the tests read (`inspect`). Kept in the module for `tick` only
(rule 4), and let go in `dispose`.

### `const panes`

Beside `let mesh = null;`:

{u}: the ground's uniforms

### `let timer`

Beside `const panes = new Map();`:

.tile -> {el, u, rim, want, k}

### `let gap`

Beside `let timer = 0;`:

the ground's next frame, when motion is allowed

### `let asked`

Beside `let gap = 1000 / GROUND_FPS;`:

ms until it

### `let clock`

Beside `let asked = 0;`:

when that frame was asked for

### `let lastNow`

Beside `let clock = 0;`:

the ground's time (s): it moves only when motion is allowed

### `let frames`

Beside `let painted = "";`:

the custom properties the uniforms were last painted from

### `let requestFrame`

Beside `let frames = 0;`:

frames the ground was drawn on

### `let renderer`

Beside `let requestFrame = null;`:

api.request, for the timer

### `const PROPS`

Beside `let renderer = null;`:

api.renderer, for `inspect` alone

Above `const PROPS = ["--glass-mesh-1", "--glass-mesh-2", "--glass-mesh-3", "--glass-fill", "-- …`:

The glass custom properties this module reads, per variant (skin.css).

### `export function rgba`

Above `export function rgba(text, fallback) {`:

A CSS colour as [r, g, b, a] in 0-1: `rgb()`/`rgba()` with commas or spaces, or a hex. What a
custom property holds is the text it was given (with any var() resolved), so this is enough.

### `function paint`

Above `function paint(tokens) {`:

Every uniform that carries a colour, from the page as it is now. Called when a mesh is made and
whenever the properties change under it -- the stylesheet can arrive after the module does.

## the ground

### `function drift`

Above `function drift(u, t) {`:

Where each blob is at time `t`: its skin.css place, drifting on its own slow lap.

### `export function ground`

In `ground`, above `const link = document.head.querySelector("link[data-skin]");`:

The skin's stylesheet and this module are fetched at once, and either can land first. Until
the stylesheet has, there is no mesh to paint; when it does, one frame repaints (`tick` sees
the properties change). Nothing else would ask for that frame under reduced motion.

## the pane

### `export function frame`

Above `export function frame({ THREE, scene, tokens, api }, el, box) {`:

One pane's glass: frost, edge, glint, shadow and rim, in one mesh that reaches past the pane
for its shadow. Made again when the pane changes size; the rim's progress is the pane's, kept.

### `function rimOf`

Above `function rimOf(el) {`:

The state a pane's rim answers, read from the classes app.js set: needs you and error in the
human colour, done in green. Nothing else lights it.

### `function settle`

Above `function settle(p, tokens, reduced, dt) {`:

One pane's rim, advanced by `dt`: drawn in towards the state it should show, run back out of a
state it no longer has before the next is drawn. Answers whether it is still moving.

## the frame

### `export function tick`

In `tick`, above `if (!reduced && lastNow) clock += Math.min(1, Math.max(0, (now - lastNow) / 1000));`:

The ground's clock runs on the page's, and stands still under reduced motion.

In `tick`, above `const sig = PROPS.map(n => tokens.css(n)).join("|") + "|" + tokens.bg.join(",");`:

The stylesheet can land after the module: the colours follow it here, not on a reload.

In `tick`, above `if (!reduced && !timer) {`:

The ground drifts on a timer of its own, at the rate the page can afford: a frame that was
late by more than the gap it was given stretches the next gap to four times that cost.

In `tick`, above `return moving;`:

A rim being drawn wants every frame; the drift does not.

### `export function inspect`

Above `export function inspect() {`:

What the tests (and a curious console) read: the ground's clock and each pane's rim. The module
is the one `ink.js` imported, because the page imports it by the same URL.
