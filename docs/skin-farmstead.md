# Farmstead on three.js

_Slice I (#255) of the ink epic (#246, [plan-ink.md](plan-ink.md)). The farmstead skin (#157) was a stylesheet of
data-URL tiles. Where the gate turns ink on, the ink layer ([desk-ink.md](desk-ink.md)) draws it: the soil, the planks,
a lit wooden frame round every pane, and a crop that grows a stage when the agent's phase advances. Under
`body.ink-off` it is the stylesheet's farm, as it always was, with the same marks drawn plain._

The module is `agentdata/fleet/static/ink/skins/farmstead.js`. Its inputs are in `static/skins/farmstead/skin.css`,
and its tests are in `tests/test_fleet_ink_farmstead.py`.

## What is drawn, and what the page keeps

The DOM keeps every word and every control. With ink on, `skin.css` clears the backgrounds of the header, the footer,
the panes and the state chip, and the transparent borders on the top, right and bottom of the panes. The canvas behind
the page shows through. The accent stripe down a pane's left edge is the pane's own, and it stays.

**Which text wears the band ink.** The words written straight on the planks do: the title (`header
h1`), the group labels (`.glabel`), the stream's dot (`.dot`), the footer's counts (`#counts`) and the
key map's own text (`footer .keys`), in `--farm-band-ink` or `--farm-band-ink-soft`. A control does
not (#336): every `button`, `input`, `select` and `kbd` in the header and the footer keeps the
palette's own background, so it keeps the palette's `--text` as well. The band's near-white had
cascaded into them and read at 1.30:1 on daylight's light buttons, and 1.22:1 on the `?` key; each
reads at 4.5:1 or better now, in every weather.

| Piece | Hook | Drawn from | Scale (CSS px per art pixel) |
| --- | --- | --- | --- |
| the soil, under the whole page | `ground` | `sprites.svg#soil`, tiled from the viewport's top-left | 2, as the stylesheet drew it |
| the header and footer bands | `paper` | `sprites.svg#plank`, lit flat by `--farm-band-light` | 2 |
| a pane's shadow on the soil | `frame` | flat black at 32%, 3 art pixels down and right | 1 |
| a pane's paper | `frame` | `--farm-paper`, the variant's composited panel | — |
| a pane's frame | `frame` | four `plank` boards, one plank (8 art pixels) thick, half over the pane's border and half into the gutter, lit | 1 |
| a pane's crop | `frame`, then `tick` | the central 12x12 art pixels of the `crop-*` sprite the chip carried, over the chip's 24px glyph box | 2 |

**Every scale is a whole number of device pixels.** A scale is rounded down to whole device pixels (`unitOf`), so at a
device pixel ratio of 1.25 the soil is 2 device pixels a texel and the crop is 19.2 CSS px. An art pixel is always a
square block of the screen. A crop's position is snapped to the device grid as well.

## The art, as textures

There is no texture helper in the layer, so the loader is in the skin module:

1. `sprites.svg` is fetched once, through `q()`, and parsed with `DOMParser`.
2. Each sprite (`soil`, `plank`, and the five `crop-*`) is serialised as its own SVG document with the sheet's
   `shape-rendering: crispEdges`. It is drawn by an `Image` into a canvas **on the art's own grid**: one texel per
   art pixel (`RASTER = 1`, the smallest whole multiple), so the texture holds exactly the pixels the repo reviews.
   The image is a `data:` URL, because the desk's CSP allows images from itself and `data:` alone.
3. Each canvas is a `CanvasTexture` with `NearestFilter` for both filters, no mipmaps, `flipY` off and no colour
   space, so the art's bytes are untouched. The shaders sample at texel centres too.

The textures exist, blank, from the first hook. The art arrives in them when the sheet has been drawn, and the layer
is asked for a frame (`api.request()`). `dispose` frees all seven when the skin or its weather changes.

## The frames are lit

Each board is a plank laid along its side. Its outer edge is row 0 of the art (the plank's highlight) and its inner
edge is row 7 (its shadow). A board is bevelled a row of art at a time, facing a little outward at its outer edge and a
little inward at its inner one. The light comes from the top left (the layer's own sun, `(-0.45, 0.55, 0.9)`), so the
top and left boards are lit and the bottom and right are in shade. The steps are a row of art pixels wide, as a pixel
artist would shade it. Ambient and diffuse come from `--farm-ambient` and `--farm-diffuse`, and the light's colour from
`--farm-sun`.

A frame is built at its pane's size. The layer moves its group with the pane, and calls `frame` again when the pane's
size changes, inside the frame the browser laid out. So a gutter drag rebuilds it with no DOM write.

## The crop grows a stage when the phase advances

**Its size.** The crop is the state's second carrier, beside the chip's word (HIG *Color*: never colour
alone), so it is drawn large enough to be read (#336). A crop sprite is 16x16 art pixels with the art
itself 6 to 12 across and a 2-pixel margin round it, so the chip draws the central 12x12 (art 2 to
14 each way) at twice the art: 24 CSS px in a 24px glyph box at a device pixel ratio of 1, and 19.2
CSS px at 1.25, two whole device pixels an art pixel. A static test holds every `crop-*` rect inside
that window, so no leaf is ever clipped.

**The DOM signal is the tile's `state-*` class** (`setTileState` in `app.js`), which the fold derives from the agent's
phase and its turn, together with `needs-human` and `is-done`. `is-done` is the fold's own *done*: the fold calls an
agent done only once nothing supervises it, and the chip draws every quiet unsupervised agent as idle, so the page
says it finished with this class (#253). There is no phase attribute on the page, and the skin adds none. The
crop is the chip's own sprite (#157):

| The tile's classes | Crop |
| --- | --- |
| `state-idle`, `state-starting` | seed |
| `state-running` | sprout |
| `state-waiting_approval` | sun |
| `state-done`, `is-done` | bloom |
| `needs-human`, `state-needs_human`, `state-blocked`, `state-error` | wilted |

**Seed, sprout, bloom** is the crop's growth. A change along that line is the phase advancing, and it grows the crop by
**one stage for each step**, so seed to bloom grows through the sprout. A stage is drawn up from the soil **a row of art
pixels at a time**, over the stage before it: rows below the line are the new stage, and rows above it are the old
one. There are 60 rows a second and never fewer than one a frame, so a stage is up in 16 frames at most. No two stages
are ever blended (drawn, never faded). A wilt, the sun, or a crop replanted after a new run is drawn the same way but
does not count as growth. Under reduced motion the stage is simply there.

## The state grammar

Every row comes from a class `app.js` already sets. The mark is the layer's, from the table, drawn in ink here and as
plain CSS under `body.ink-off`. The material is the skin's own response.

| State | The page's signal | Mark (tool, shape) | Material | Plain (`body.ink-off`) |
| --- | --- | --- | --- | --- |
| needs you | `.tile.needs-human` | highlighter, `lines` on the name (`.head .repo`) | the crop wilts | a tinted name, and the stylesheet's wilted chip glyph |
| running | `.tile.state-running` | pen, `underline` under the name | a sprout grows | an underlined name, the sprout glyph |
| error | `.tile.state-error` | marker, `loop` round the head | the crop wilts, and the frame is scorched (its boards darkened, with an ember of `--human`) | a 2px outline round the head |
| done | `.tile:is(.state-done, .is-done)` | green, `check` in the margin of the head | the crop grows into a bloom | a bar in the head's margin (the chip's own glyph says what the chip says) |
| stale (#240) | `.tile .oldsession:not([hidden])` | pencil, dashed `outline` round the *old skills* tag | — | a 1px outline |
| answered | `.tile .asks:not([hidden]) .ask-choice[aria-pressed="true"]` | pen, `loop` round the chosen answer | — | a 2px outline |
| finding | `.tile .transcript li.friction` | red, `ellipse` round the friction line | — | a 2px outline |

When a state goes, its pencil is erased and its ink is struck, as the layer does for every skin. A friction line is
history and stays in the transcript, so its ring stays with it.

## The weathers

The variants in `skins.py` are the same farm at a different hour. They differ in their materials and never in what a
state looks like. The module has no colour of its own. It reads these custom properties from `skin.css` at paint time,
and again on every frame it draws, because the stylesheet can land after the skin's first frame:

| Property | Daytime | Cave | Rainy |
| --- | --- | --- | --- |
| `--farm-paper` (= `composited_panel`) | `#E8DDC3` | `#33302A` | `#16243D` |
| `--farm-soil` (recolours the soil) | — (the art as it is) | `#46423A` | `#27364F` |
| `--farm-wood` (recolours the planks) | — | `#4A4438` | `#243349` |
| `--farm-sun` (the light's colour) | `#FFF4E0` | `#FFD9A8` lamplight | `#D2DEF2` |
| `--farm-band-light` | 0.55 | 0.9 | 0.9 |
| `--ink-pencil` | `#74695A` | `#968F82` | `#8A97AB` |
| `--ink-highlighter` | the palette's | `#A8861F` | the palette's |

A weather recolours a sprite by each texel's brightness against the sprite's commonest colour, which is how the
stylesheet's cave and rain tiles were drawn from the daylight ones. The palette's other inks are its own.

## `theme.check`: what the skin puts behind text

* **A pane's text is on `--farm-paper`**, which a test holds equal to the variant's `composited_panel`. So
  `theme.check(base, composited_panel=paper, inks=...)` is the check of what the operator reads, and the table's inks
  are checked on the same paper: pencil, pen, red, green, marker and highlighter. The palette's pencil is too faint on
  every one of the three papers, and the cave's highlighter washed its text out (4.20:1). The overrides above are why
  all three pass.
* **The header's and footer's text is on the lit plank.** Every texel of the plank, recoloured for the weather and lit
  as the shader lights it, keeps 4.5:1 under each colour `skin.css` writes the bands' text in. That is what sets the
  daylight band light at 0.55.

## Three things the page needed

* **An idle desk with a skin wrote to the page.** Every refresh applies the palette and the skin again, and
  `applyTheme` and `applySkin` set their attributes whether or not they had changed. `startGround` also waited again
  for a skin's stylesheet on every pass. The ink layer follows `data-skin`, so it drew a frame each time. They write
  only a change now (the graph paper slice, #253, landed the same fix), and
  `tests/regressions/test_20260923_any_idle_desk_with_a_skin_writes.py` holds it for farmstead and voxel.
* **The chip's glyph was the whole sheet.** Under `body.ink-off` the chip carries `url("sprites.svg#crop-*")`. Every
  sprite in the sheet sits at 0,0, and nothing hid the others, so the glyph was all seven drawn over each other and
  squeezed into 16px. The sheet is a stack now: its root is 16x16, its sprites are hidden, and `:target` shows the
  one a fragment names. With no fragment it shows nothing. The ink loader reads each sprite out on its own, so it
  is unaffected. Voxel's sheet had the same fault, worse: its last block (idle) covered the rest, so every voxel chip
  said idle. It is a stack too, and
  `tests/regressions/test_20260923_any_chip_glyph_drew_the_whole_sheet.py` reads every glyph any stylesheet names.
* **A clear header needs its own layer.** With the header's background cleared, Chromium composited the canvas with a
  band missing along the foot of the panes. The drawing buffer was whole (read back); the screen was not. The rule
  `will-change: transform` on the header puts it right. The header holds no popover that a stacking context could
  trap.

## Tests

`tests/test_fleet_ink_farmstead.py` covers the following:

* **Every variant**, in ink with `?ink=on` (ground, bands, a frame per pane, the paper as the composited panel, the
  chip's glyph box left empty) and plain with the gate off (the stylesheet's farm, the marks as CSS).
* **Crisp pixels at a whole number of device pixels**: at a device pixel ratio of 2, each crop art pixel and
  each soil pixel is a 4x4 block. Each block is one colour, and every colour is the art's or the paper's.
* **Readable**: every header and footer control at 4.5:1 on its own background in every weather, and
  the crop 19 CSS px or more at a device pixel ratio of 1 and 1.25, inside the chip's glyph box (#336).
* **Frames follow a gutter drag**: the board is where the pane now ends, and paper fills what it grew into.
* **A crop grows exactly one stage** per advance, row by row, and at once under reduced motion. A finished agent
  (`is-done`, from a real `phase_changed` to done) is ticked and grows its seed to a bloom through the sprout.
* **The grammar**: each state's mark and material appear from the fold's own events, and leave struck when a new run
  begins.
* **The chip's glyph**: each `sprites.svg#crop-*` is exactly that sprite's colours at 16x16, and the sheet with no
  fragment draws nothing.
* **`theme.check`** pairs, the bounded catch-up in frames, the idle desk (zero writes, zero frames), and `dispose`
  freeing the textures (the renderer's own count).
