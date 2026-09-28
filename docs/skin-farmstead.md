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
2. Each sprite's `<rect>`s are filled, in document order, into its own array **on the art's own grid**: one texel
   per art pixel (`RASTER = 1`), so the texture holds exactly the pixels the repo reviews. No browser rasterises it
   and there is no 2D context (#257).
3. Each array is a `DataTexture` with `NearestFilter` for both filters, no mipmaps, `flipY` off and no colour space,
   so the art's bytes are untouched. The shaders sample at texel centres too.

The sprites, and each one's size in art pixels:

| Sprite | Size | What it is |
| --- | --- | --- |
| `soil` | 16x16 | the ground under the page |
| `plank` | 16x8 | the header and footer bands, and every board of a frame |
| `crop-seed`, `crop-sprout`, `crop-sun`, `crop-bloom`, `crop-wilted` | 16x16 | the crop in the chip |
| `produce` | 8x8 | a root vegetable with its leaves |
| `cloud` | 16x8 | a rain cloud |
| `hen-a`, `hen-b` | 12x12 | a hen's two-frame run |
| `cat-sleep`, `cat-stretch` | 16x8 | a cat asleep, and waking |
| `crow` | 8x8 | a crow |

The last seven are the farm's effects' art (#380, drawn by #381 and #382); nothing draws them yet. They are original,
like the rest of the sheet.

The textures exist, blank, from the first hook, so a sprite's size cannot come from the fetched sheet: it is the
`SIZE` table in `farmstead.js` (16x16 for a sprite not in it), and nothing is re-created or resized after the fetch.
`SIZE` is the source: `test_every_sprite_is_the_size_the_loader_makes_it` holds every nested `<svg>`'s `width` and
`height` in `sprites.svg` to it. The art arrives in the textures when the sheet has been read, and the layer is asked
for a frame (`api.request()`). `dispose` frees all fourteen when the skin or its weather changes.

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
plain CSS under `body.ink-off`. The material is the skin's own response. The marks are the state grammar every skin
draws ([desk-ink.md](desk-ink.md) §The state grammar across skins, #334); the crops and the scorched frame are added,
never instead of a mark.

| State | The page's signal | Mark (tool, shape) | Material | Plain (`body.ink-off`) |
| --- | --- | --- | --- | --- |
| needs you | `.tile.needs-human` | highlighter, `lines` on the name (`.head .repo`) and on the open question (`.asks:not([hidden]) .ask:not([hidden]) .ask-q`); pencil, `loop` round each choice not yet picked (#334); marker, `loop` round the question card, `.tile.needs-human .asks:not([hidden])`, on its border (pad -3): the loudest pane (#335) | the crop wilts | a tinted name and question, outlined choices, the card outlined in the marker's colour, and the stylesheet's wilted chip glyph |
| running | `.tile.state-running` | pen, `underline` under the name | a sprout grows | an underlined name, the sprout glyph |
| error | `.tile.state-error` | marker, `loop` round the error's own words, `.tile.state-error .why` (pad 0, #335; it was round the pane at -7); red, `bang` in the pane's margin (#334) | the crop wilts, and the frame is scorched (its boards darkened, with an ember of `--human`) | a 2px outline round the why, and a bar in the pane's margin |
| done | `.tile:is(.state-done, .is-done)` | green, `check` in the pane's margin (#330) | the crop grows into a bloom | a bar in the pane's margin (the chip's own glyph says what the chip says) |
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
| `--ink-highlighter` | `#E2B45C` straw | `#816718` | `#D4A73D` |
| `--farm-rain` (a rain streak on the boards) | `#A9C4DC` | `#9DB8D6` | `#8FB0D8` |
| `--farm-firefly` (a glow on the soil) | — | `#D8F07A` | — |

`--farm-rain` and `--farm-firefly` are for the farm's effects (#380, drawn by #381 and #382); nothing reads them yet.
Each rain keeps 3:1 on the median plank texel of its weather, lit as the band shader lights it, and the firefly keeps
3:1 on the cave's soil (`test_the_rain_and_the_fireflies_read_on_what_they_are_drawn_over`).

A weather recolours a sprite by each texel's brightness against the sprite's commonest colour, which is how the
stylesheet's cave and rain tiles were drawn from the daylight ones. The palette's other inks are its own.

## Effects

A finished agent's crop is harvested, an agent that errors gets a shower down its frame, and a pane put away sends a
hen running along the footer to the hidden count (#381, epic #293). The farm's paper is light by day and dark in the
cave and the rain, so no one effect colour keeps text readable on all three: **nothing crosses the paper's text**, nor
the header's or the footer's. The cues are the module's `cues` table, matched by the layer from the page
([desk-ink.md](desk-ink.md) §Effects), and the module asks for the text helpers (`options.fx.text`, #375).

| Cue | Signal (on) | What plays | Where it draws | Duration | Reduced motion |
| --- | --- | --- | --- | --- | --- |
| harvest | `#grid > .tile:is(.state-done, .is-done)` (arrive) | once the crop is `crop-bloom` with nothing left to grow (up to 32 frames from a seed), 3 `produce` sprites (at `unitOf(api, 1)`) pop from the crop 120 ms apart, rise with a 2px drift left to the top board's inner edge, and sink into the board 2 art rows a frame | the pane's frame group at renderOrder -11.5: over the paper, under the board, so the board covers them as they sink | all gone 0.65 s after the bloom completes | nothing; the bloom is drawn at once |
| shower | `#grid > .tile.state-error` (arrive) | a `cloud` centred on the frame's top-left corner, where the top and left boards meet, and 12 streaks (1x3 art px in `--farm-rain`) falling down the **left board only** at 700 px/s, each ending at the bottom board. From 0.9 s to 1.2 s the cloud is drawn away bottom-up, a row at a time. The scorch (`uChar`) stays: it is the state | the pane's frame group at renderOrder -10.5: over the boards | 1.2 s | nothing; the scorch is drawn at once |
| hen | `#grid > .tile:not(.is-hidden)` (leave) | the hen appears in the footer band's free rows at the pane's left edge and runs along them, `hen-a`/`hen-b` every 80 ms, to the left edge of `#hiddencount` (a hide, with the count shown), where it is drawn away a column of art at a time over 4 frames; otherwise (a pane gone from the registry, whose gone rail is beside the panes, not in the footer) it runs off the nearest edge of the viewport | the effects group (`api.order.fx`), over the soil and the bands | the run 1.1 s, then 4 frames | nothing |

* **Where each piece sits in the draw order.** Every farm material is `transparent: true`, so a pane's meshes sort as
  one list by their own orders: shadow -13, paper -12, produce -11.5, board -11, shower -10.5, crop -10. three.js
  orders by the innermost group's `renderOrder` first, and the effects group (-5) draws under every pane's frame
  group, so an effect on a frame goes in that pane's own group (`rec.group`, set in `frame`). Transparent texels
  are discarded, as the crop's are; nothing is blended.
* **The footer's free rows.** The rows between the band's top and its first line of text, which the hen reads with
  the text helpers (#375): `api.fx.glyphs(footer)`, the glyph boxes that have a size. At 1600x900 that is
  858.2-871.2, room for the 12px hen. `api.fx.lines` is not used for this: its line boxes include the controls' own
  boxes (the `?` key's starts at 865.2), which would leave 7 rows. With fewer rows than the hen is tall, it does
  not run, and `skipped` counts it.
* **A grouped pane sends no hen.** A pane folded into its project's rail is `.is-grouped`, `display: none`, and still
  matches `:not(.is-hidden)`: its cue plays nothing.
* **Card closes play nothing in the farm.** There is nowhere to play them without crossing text.
* **Freed.** Every mesh an effect adds is removed and disposed when it ends; the textures are the shared sheet's.
  A `frame()` rebuild empties the pane's group, which ends any effect in it, and the module drops its state.
  `tick` answers true while an effect lives. A piece moves on the layer's `dt`, never less than a 60 Hz frame's worth.

`inspect().fx` is `{live, played: {harvest, shower, hen}, skipped, pieces: [{sprite, x, y, w, h}]}`, the pieces in
viewport px.

## `theme.check`: what the skin puts behind text

* **A pane's text is on `--farm-paper`**, which a test holds equal to the variant's `composited_panel`. So
  `theme.check(base, composited_panel=paper, inks=...)` is the check of what the operator reads, and the table's inks
  are checked on the same paper: pencil, pen, red, green, marker and highlighter. The palette's pencil is too faint on
  every one of the three papers, and the cave's highlighter washed its text out (4.20:1). Read through the layer's
  real blend (#329), the palette's amber left the name at 3.76:1 by day and the rainy day's at 4.49:1, and the cave's
  first override at 4.05:1; each weather has its own now. The overrides above are why all three pass.
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
* **The chip's glyph**: each `sprites.svg#crop-*` is exactly that sprite's colours at 16x16, each of the effects'
  sprites is its own colours inside its own size, and the sheet with no fragment draws nothing.
* **The sizes and the effects' colours**, without a browser: every nested `<svg>` in the sheet is the size `SIZE`
  makes its texture, and `--farm-rain` and `--farm-firefly` keep 3:1 on what they are drawn over.
* **The effects** (#381), folded into the grammar test: harvest from running and from idle, the shower, the hen and a
  grouped pane's hen, each played once, none on a reload; every piece recorded on every frame in the page, and none
  ever crossing a text line box of a visible pane, the header or the footer; each ends within its frames and leaves
  the GPU's geometry count where it found it, then the desk is idle. Reduced motion plays nothing and draws the bloom
  at once; `?ink=off` hides with no page error.
* **`theme.check`** pairs, the bounded catch-up in frames, the idle desk (zero writes, zero frames), and `dispose`
  freeing the textures (the renderer's own count).
