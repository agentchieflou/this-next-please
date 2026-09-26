# `ink/skins/farmstead.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The farmstead skin on three.js (#255, slice I of the ink epic #246).

What was a stylesheet of data-URL tiles is drawn by the ink layer: the soil under the whole page,
plank bands behind the header and the footer, and a lit wooden frame round every pane with its
paper inside. The art is `static/skins/farmstead/sprites.svg`, the file the repo reviews, and
nothing else: it is fetched once, each sprite is read from its rects onto its own grid (one texel
per art pixel, #257: no 2D context), and every enlargement is three.js's NearestFilter at a whole number of DEVICE pixels, so
a pixel of the art is always a square block of the screen and never a blend of two. The colours
are the art's own; what the palette and the weather change comes from the custom properties
`skin.css` sets (`--farm-*`), read at paint time, never from a hex written here.

THE CROP. Each pane carries the crop its chip carried (#157): seed, sprout, sun, bloom or wilted,
from the classes `app.js` already sets -- the tile's `state-*`, which the fold derives from the
agent's phase and turn, `is-done` (the fold's own done, #253), and `needs-human`. When the
phase advances the crop GROWS a stage: the next stage is drawn up from the soil a row of art
pixels at a time over the one before, and seed to bloom grows through the sprout. Drawn, never faded (plan-ink ground rule 1): no two
stages are ever blended. Under reduced motion the stage is simply there.

THE REST OF THE STATES are the mark table below, and docs/skin-farmstead.md has the grammar:
the layer draws them in ink here and plain under `body.ink-off`, from the same rows.

No static `import` (the run token), no page writes, and nothing decided here that the page's
classes did not say.

### `const RASTER`

Above `const RASTER = 1;`:

The sheet is read at this multiple of its own grid: one texel per art pixel. The texture
holds exactly the pixels in the file, and every enlargement after it is NearestFilter's.

### `const PROPS`

Above `const PROPS = ["produce", "cloud", "hen-a", "hen-b", "cat-sleep", "cat-stretch", "crow"];`:

The art the farm's effects draw with (#380), not crops and never grown: nothing draws it yet.

### `const SIZE`

Above `const SIZE = { plank: [16, 8], produce: [8, 8], cloud: [16, 8], "hen-a": [12, 12], "hen- …`:

```text
Each sprite's size in art px; 16x16 when it is not here. load() makes every texture before the
sheet is fetched, so a size cannot come from the svg: this table is the source, and a static test
holds every nested <svg>'s width and height in sprites.svg to it.
```

### `const GROWS`

Above `const GROWS = ["crop-seed", "crop-sprout", "crop-bloom"];`:

How a crop grows. A change along this line is the phase advancing: one stage drawn per step.

### `const ROWS_PER_S`

Above `const ROWS_PER_S = 60;`:

Rows of art a growing crop gains a second, and never fewer than one a frame: a stage is up in
sixteen frames at most, whatever the frame rate (desk-ink.md: counted in frames).

### `const SCALE`

Above `const SCALE = { soil: 2, band: 2, board: 1, crop: 2 };`:

How many CSS px one art pixel spans, before it is rounded down to whole device pixels. The
soil and the bands keep the stylesheet's 2x (a 16px tile drawn at 32px), and so does the crop,
large enough to be read as the state's second carrier (#336); the frames are the art's own size.

### `const CROP_ART`

Above `const CROP_ART = [2, 14];`:

The crop is the sprite's central 12x12 art pixels, 2 to 14 each way: every crop's art lies
inside it (a static test holds that), and at twice the art that is the chip's 24px glyph box.

### `const SHADOW`

Above `const SHADOW = 3;`:

The frame's boards are one plank thick (8 art px), half over the pane's transparent border and
half into the gutter, and throw a shadow this many art px down and right.

### `const ORDER`

Above `const ORDER = { shadow: -13, paper: -12, board: -11, crop: -10 };`:

Where the pieces go: under every mark (api.order), shadow first, crop last.

## the mark table

### `export function marks`

Above `export function marks() {`:

The state grammar (docs/skin-farmstead.md), every row a class `app.js` already sets.

In `marks`, above `{ selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },`:

needs you: the name highlighted, and the crop wilts (the material, below).

In `marks`, above `{ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },`:

running: a pen line under the name while the sprout grows.

In `marks`, above `{ selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },`:

error: the pane boxed in marker, inside its frame (#332: round the head, the loop crossed the
chip row and the words under it); the crop wilts and the frame is scorched.

In `marks`, above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green tick in the margin, beside the bloom -- the chip's `done` (a supervised
agent) or the fold's own (`is-done`, #253: the chip draws a finished, unsupervised agent
as idle, and this is how the page still says it finished).

In `marks`, above `{ selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", pad: 0, …`:

stale (#240): the session's "old skills" tag ringed in dashed pencil.

In `marks`, above `{ selector: ".tile .asks:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", …`:

answered: the choice the operator picked is circled in pen, while the question is open.

In `marks`, above `{ selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse", pad: 2 },`:

a finding: the friction line in the transcript, ringed in red.

### `export const options`

Above `export const options = { hand: true, speed: 1 };`:

The same farm in every weather (skins.py): the variants differ in their materials, which are
`skin.css`'s custom properties, and never in what a state looks like.

## the sprite sheet

### `let made, freed`

Beside `let sheet = null;`:

{textures, data, sizes, base, loaded, failed}

### `let lastApi`

Beside `let made = 0, freed = 0;`:

textures, for `inspect` and the dispose test

### `let look`

Beside `let U = null;`:

the uniforms every material here shares, updated in place

### `let bands`

Beside `let look = "";`:

the custom properties they were last read from

### `const recs`

Beside `let bands = [];`:

the header and footer bands, for `tick` to follow

### `const waited`

Beside `const recs = new Map();`:

pane -> its crop and frame

### `function commonest`

Above `function commonest(px) {`:

The most common opaque colour of a sprite: the colour a weather recolours from.

### `function pixels`

Above `function pixels(doc, id, s) {`:

```text
One sprite of the sheet as its own pixels. The art is `<rect>`s on a whole-pixel grid and
nothing else (`test_fleet_skins` holds the sheet to that), so each rect is filled into the
sprite's grid in document order, the way the SVG paints it -- no browser rasterising, and no 2D
context: the desk has none anywhere (#257). Row 0 of the array is the art's top row.
```

### `function load`

Above `function load(THREE, api) {`:

The textures exist from the first call, blank, so every material can hold them at once; the art
arrives in them when the sheet has been fetched and read, and the layer is asked for a frame.

Beside `t.flipY = false;`:

row 0 of the art is v = 0

Beside `t.colorSpace = THREE.NoColorSpace;`:

the art's bytes, untouched

Beside `if (sheet !== s) return;`:

the skin went while it loaded

## the materials

### `const FLAT_FRAG`

Above `` const FLAT_FRAG = GLSL_COMMON + ` ``:

The soil, and the bands: flat, lit by the band light (none for the soil).

### `const BOARD_FRAG`

Above `` const BOARD_FRAG = GLSL_COMMON + ` ``:

The frame's boards. Each is a plank laid along its side, outer edge on row 0 of the art (its
highlight) and inner edge on row 7 (its shadow), and bevelled: a board faces a little outward
at its outer edge and a little inward at its inner one, a row of art at a time, so the light
from the top left falls on the top and left boards and leaves the bottom and right in shade --
in steps, as a pixel artist would shade it. `uChar` scorches it (a pane in error).

### `const CROP_FRAG`

Above `` const CROP_FRAG = ` ``:

A crop: the stage it had below `uRows` rows from the soil, the stage it is growing into at and
under them. Transparent art is not drawn at all (no alpha to blend, so nothing is faded).

### `const FILL_FRAG`

Above `` const FILL_FRAG = ` ``:

A flat colour, as the page's own sRGB: the paper under the pane, and the shadow.

### `function rgbOf`

Above `function rgbOf(THREE, text) {`:

A custom property as [r, g, b] in 0-1 sRGB, or null when the skin does not set it.

Beside `c.getRGB(o, THREE.SRGBColorSpace);`:

the page's own sRGB, as the layer's tokens are

### `function readLook`

Above `function readLook(THREE, tokens) {`:

The materials' inputs, from the palette and `skin.css`. Read on every hook: the stylesheet can
land after the skin's first frame, and a palette or a weather changes them in place.

### `function awaitSheet`

Above `function awaitSheet() {`:

A stylesheet that is still loading is followed to its end, once: its custom properties are the
materials' inputs, and a link that lands late would otherwise leave the daylight farm drawn
under a cave's panes until something else asked for a frame.

### `function unitOf`

Above `function unitOf(api, css) {`:

How many CSS px one art pixel spans at `css` px, on whole device pixels -- never larger than
the design, and never less than one device pixel.

### `function quadsGeometry`

Above `function quadsGeometry(THREE, quads) {`:

A quad, or several, as geometry: `quads` is [[x0, y0, x1, y1, a0x, a0y, a1x, a1y, side]] in CSS
px (y down) and art px, with the art coordinates given at the two corners and each axis mapped
linearly between them. `swap` puts the plank's length down a vertical board.

Above `idx.push(base, base + 2, base + 1, base, base + 3, base + 2);`:

Counter-clockwise as the camera sees it (y is flipped), so the face is towards it.

## the hooks

### `export function ground`

Above `export function ground({ THREE, scene, tokens, api }) {`:

The soil, tiled from the top-left of the viewport at the stylesheet's 2x.

### `export function paper`

Above `export function paper({ THREE, scene, tokens, api }) {`:

The header and the footer, laid with planks and lit flat by the band light, which skin.css
sets low enough for their text to read on the lightest plank (theme.check, test_fleet_ink_farmstead).

### `function placeBand`

Above `function placeBand(THREE, api, band) {`:

A band where its element is now: the plank's rows run from the band's top edge.

### `export function frame`

Above `export function frame({ THREE, scene, tokens, api }, el, box) {`:

One pane: its shadow on the soil, its paper, four lit boards, and its crop. The group is at
the pane's top-left and moves with it; this is called again only when the pane's size does.

In `frame`, above `const off = SHADOW * u;`:

Its shadow, cast down and right onto the soil -- pixel-hard, like the art.

In `frame`, above `scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, box.w, box.h, 0, 0, 1, 1, 0]]),`:

Its paper: what the pane's text is read on (skins.py's composited panel, theme.check).

In `frame`, above `const H = (y1 - y0 - 2 * T) / u;`:

Four boards: the top and bottom run the full width, the sides fit between them.

In `frame`, beside `[x0, y0, x1, y0 + T, 0, 0, L, 8, 0, false],`:

top: outer edge up

In `frame`, beside `[x1 - T, y0 + T, x1, y1 - T, 5, 8, 5 + H, 0, 1, true],`:

right: outer edge right

In `frame`, beside `[x0, y1 - T, x1, y1, 11, 8, 11 + L, 0, 2, false],`:

bottom: outer edge down

In `frame`, beside `[x0, y0 + T, x0 + T, y1 - T, 3, 0, 3 + H, 8, 3, true],`:

left: outer edge left

In `frame`, above `const rec = recs.get(el) || { el, repo: el.dataset.repo || "", shown: cropOf(el), queue: …`:

The crop, in the chip's own place (skin.css leaves the chip's glyph box empty under ink).

### `function cropOf`

Above `function cropOf(el) {`:

Which crop the pane's classes say: the chip's own sprite (skin.css, #157).

### `function place`

Above `function place(rec, api) {`:

The crop over the chip's glyph box: the chip's content box, left edge, centred on its height,
snapped to whole device pixels on the page (the group is at the pane's fractional top-left).

### `function stepsTo`

Above `function stepsTo(from, to) {`:

What a crop must grow through to reach `to`: one stage at a time along GROWS when the phase
advances; anything else (a wilt, the sun, a crop replanted) is drawn in one pass.

### `export function tick`

Above `export function tick({ THREE, tokens, api }, dt) {`:

Every frame the layer draws: the crops that must grow, the bands that moved, the materials'
inputs. Answers true while a crop is still growing.

In `tick`, above `if (GROWS.indexOf(prev) >= 0 && GROWS.indexOf(step) > GROWS.indexOf(prev)) rec.grows += 1;`:

A stage grown: the phase advanced along the crop's own line, never a wilt or a sun.

### `export function dispose`

Above `export function dispose() {`:

The skin is going: the layer frees what is in its scenes, and the textures are freed here.

### `export function inspect`

Above `export function inspect() {`:

For the tests and a curious console: what this skin has on the paper.
