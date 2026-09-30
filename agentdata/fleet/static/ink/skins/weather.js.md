# `ink/skins/weather.js`

The reasoning for this file, kept beside it rather than in it (decisions 18 and 19 on #429). The
source keeps its code; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the declaration or statement the notes
sit in or above, in source order. A builder who changes the code changes its note here.

### The file

```text
The weather genre (docs/skin-weather.md): a sky per variant, and the pane a sheet of paper on it.
Where the notebook moves with a hand, the weather moves with a sky: rain that falls across the
panes, the sun's rays turning, cloud cover drifting, stars that twinkle and a meteor now and then.
It is the one genre that moves while it is on (docs/themes.md §Genres), and it holds still under
reduced motion.

THE DOM IS THE TRUTH. The mark table is the state grammar's rows (desk-ink.md), every row a class
or an attribute app.js already sets. Nothing here decides a state, and nothing here draws a
letter: a `write` row uncovers the element's own text.

No colour is written in this file. Every colour and number is a custom property in
static/skins/weather/skin.css (`--paper`, `--wx-*` and `--ink-<tool>`), read through `tokens` at
paint time and on every tick, so a variant change repaints without a rebuild.
```

### `export function marks`

The grammar's rows, drawn without a hand. The idle pane keeps a dashed pencil outline (the sheet
has no rules to say where a pane ends); the running name is underlined in pen with `grow` and
`tip`, the line growing per transcript line; an error's reason is outlined, not looped, since a
sheet on a sky reads better squared; its bang is red. Everything else is the notebook's row.

### `const EVEN`, `export const options`

One tune for the drawing tools: full, even pressure, a little wobble so a line is not ruled, no bow,
no taper. `hand: false` -- the weather has no hand, which is the point of the genre -- and `speed`
1.4, a shade quicker than the notebook. `paper: "--paper"` tells the layer the marks are read on
the sheet, so its blend mode is multiply on the light weathers and screen on the dark ones; the
`paper` hook below keeps the layer's own flat paper off.

### `export const cues`

Two moments (docs/skin-weather.md §The moments): lightning when a pane arrives in error, a clearing
when one arrives done. Both arrive-only; the desk's leave is nothing to the weather.

### `const FLASH_S`, `CLEAR_S`, `METEOR_EVERY`, `KINDS`

The two cues fall back over 320 ms, the event budget. A meteor every nine seconds, the cycle the
shader hashes its start from. `KINDS` is the order `--wx-kind` numbers the weathers in, held to
`skins.py` by the test.

### `function rgbOf`, `function numOf`

A custom property as three 0-1 channels, or as a number, with a fallback: the same reader every
paper skin carries.

### `const NOISE`, `const VERT`

The hash, value noise and five-octave fbm every weather is made of, shared by both shaders, and the
one vertex shader.

### `const SKY_FS`

The sky: a top-to-bottom gradient and, by `uKind`, the weather in it. 0: a heavier cloud band in the
grey, and the lightning `uFlash` mixed toward `uFlashC`, stronger at the top. 1: the sun's disc at
(0.86, 0.14) of the viewport and rays that are the product of two slow sines of the angle about it,
brightened by `uClear` when the clearing cue plays. 2: cloud cover from fbm drifting at nine pixels
a second, shaded along its underside by a second sample. 3: one star in about every fourth 22px
cell, placed by hash within it, twinkling at its own rate, and a meteor whose start is hashed from
the nine-second cycle, its tail behind it, gone in 0.7 s.

### `const RAIN_FS`

Three sheets of streaks (`sheet`): a column width, a fall speed, a streak length and a lean per
sheet, each column's phase and gap hashed from its index and the sheet's seed, and a third of the
columns empty. The alpha is capped at `uDropA` and the colour is `uDrop`, mixed toward the flash
while lightning plays; the flash also lifts the whole sheet by 0.12. Drawn on `gl_FragCoord`, so a
quad anywhere on the page shows the same rain as the sheet under it.

### `const W`

The module's state: the sky mesh, the rain sheet, the rain's shared uniforms, the rain quads over
the panes, the clock, the tick and frame counts, the two cues' levels, and what has played.

### `function rainUniforms`, `function rainMaterial`

One uniforms object every rain material shares. The layer disposes a pane's group with its
materials when the pane is rebuilt (`layer.js` `empty`), so a material is never shared between the
sheet and a pane's quad -- only what it reads, which disposing a material leaves alone.

### `function remember`, `function kindOf`, `function look`, `function timing`

`remember` keeps the tokens and the api for the tick. `look` reads every `--wx-*` into the sky's
uniforms and the rain's, shows the rain sheet and the pane quads on the rainy day only, and drops
the quads of panes the layer has removed. `timing` writes the clock and the cues' levels.

### `export function ground`

The sky, one quad the size of the viewport at `order.ground`.

### `export function paper`

The rain sheet between the panes, at `order.fx`. Defining this hook is also what keeps the layer's
own flat paper off the sky: a table with `paper` and no `paper` hook is given one.

### `export function frame`

Each pane: a rim one pixel out in `--wx-rim`, the sheet in `--paper` over it, and a rain quad the
pane's size over the sheet, visible on the rainy day, since the layer paints every frame after the
paper and the rain has to fall across the sheet, not under it.

### `export function cue`

Counts the cue, then, unless reduced motion holds the sky still, sets the flash (the rainy day
only) or the clearing (the sunny day only) and asks for a frame.

### `export function tick`

Advances the clock by the frame's time (capped at 100 ms, as the layer caps it), lets the two cues
fall back, re-reads the look in case the variant changed, writes the uniforms, asks for a frame and
answers `true` for another -- `false` under reduced motion, where the clock stays at zero and the
weather is drawn once and still.

### `export function dispose`, `export function inspect`

Forget the meshes and the uniforms; say the kind, the clock, the counts, the cues' levels, whether
the rain sheet and how many pane quads are showing, and what has played, for the tests.
