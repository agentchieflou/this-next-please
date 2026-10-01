# `skins/weather/skin.css`

The reasoning for this stylesheet, kept beside it rather than in it (decisions 18 and 19 on #429).
The source keeps its rules, and the server strips any comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the rule the notes sit in or above, by
its selector, in source order. A builder who changes a rule changes its note here.

### The file

The weather genre (docs/skin-weather.md): a sky per variant, drawn by `static/ink/skins/weather.js`,
and the pane a sheet of paper on it. This file paints nothing (#257): it holds each weather's colours
and numbers as custom properties, which the module reads through `tokens.css` at paint time and on
every tick, and the stand-aside the page needs where the ink is on. Under `body.ink-off` the weather
is the one plain look every skin shares, with the mark table drawn as plain CSS by the layer's
fallback. `tests/test_fleet_skin_guard.py` holds the file to custom properties, layout and clearing.

### `body[data-skin="weather"]`

The default variant, the rainy day, on `slate`. `--wx-kind` is the weather the module's sky shader
draws, 0 to 3 in the order rainy, sunny, cloudy, starry (`tests/test_fleet_ink_weather.py` holds
the number to the variant's place in `skins.py`). `--paper` is the pane's sheet, the dark end of
the panel pair in `skins.py`. `--wx-drop` at `--wx-drop-alpha` is a streak's core, and the paper
under it is the pair's light end, which the test recomputes. `--wx-flash` is the lightning.
`--wx-cloud` and `--wx-cloud-alpha` are the heavier band that drifts through the grey sky. Every
`--ink-<tool>` is the variant's ink in `skins.py`; the highlighter is the palette's amber darkened
until the name keeps 4.5:1 through it on the wet end.

### `body[data-skin="weather"][data-skin-variant="sunny"]`

The sunny day, on `sand`. `--wx-sun` is the disc, `--wx-ray` the rays at `--wx-ray-alpha`; the
sheet is opaque so the sun never reaches the words, and the panel is `--paper` alone.

### `body[data-skin="weather"][data-skin-variant="cloudy"]`

Cloudy, on `overcast`. `--wx-cloud` at `--wx-cloud-alpha` is the cover, `--wx-cloud-shade` its
underside. The panel is `--paper` alone.

### `body[data-skin="weather"][data-skin-variant="starry"]`

The starry night, on `vanta-black`. `--wx-star` is a star, `--wx-meteor` the meteor. The panel is
`--paper` alone.


### `body[data-skin="weather"][data-skin-variant="showers"]`

The rain's light side (the Rainy day look by day), on `overcast`: the same kind 0 sky in daylight
greys, and a streak that darkens the pale paper rather than lightening a dark one, so the pair's
dark end is the paper under a streak and its light end the paper.

### `body[data-skin="weather"][data-skin-variant="dusk"]`

The cloud's dark side (the Cloudy look at night), on `slate`: kind 2, cloud cover in the rainy
day's greys with its shade beneath, and the rainy day's inks.

### `body[data-skin="weather"]:not(.ink-off) :is(.renew-strip, .away-strip)`

The renew and away strips stand aside for the canvas like the panes (#337): opaque, they sat as
panels over the sky. Keyed here, as every drawing skin keys it, not on `:has()` (#441).

### `body[data-skin="weather"]:not(.ink-off) header`

Its own compositing layer, as the farmstead and the notebook have it: a clear header left Chromium
compositing the canvas behind the page with a band missing along the foot of the panes.

### `body[data-skin="weather"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`

The ink's margin (#330): an open pane's left padding, where the done check and the error bang are
written. 26px keeps the green check off the pane number and the name, as the farmstead keeps it.

### `body[data-skin="weather"]:not(.ink-off) .tile[data-tier="compact"] .head`

The running pen under the name (#332): a compact pane's head wraps the name onto a line of its own,
and the line 2px below its foot needs more than app.css's 2px before the number and the chip on the
next line.
