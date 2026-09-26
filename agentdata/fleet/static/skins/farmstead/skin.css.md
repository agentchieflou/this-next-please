# `skins/farmstead/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

Farmstead skin: warm paper, wooden frames, and crop-stage status glyphs (#157, on three.js #255).

Since #257 this file paints nothing. Where the gate turns ink on, `static/ink/skins/farmstead.js`
draws the farm: the soil, the planks behind the header and the footer, a lit wooden frame and its
paper round every pane, and the crop in the chip -- all from `sprites.svg`, at whole device
pixels. Under `body.ink-off` farmstead is the one plain look every skin shares (app.css and the
palette), with its mark table drawn as plain CSS by the layer's fallback.

What is left: the module's inputs, read at paint time, and the room the page leaves for what it
draws. `--farm-paper` is what the pane's text is read on, so it is the variant's
`composited_panel` in skins.py (a test holds the two together). `--farm-soil` and `--farm-wood`
recolour the art for a weather; daylight leaves them unset and draws the art as it is.
`--farm-band-light` is low enough that the header's and footer's text keeps 4.5:1 on the
lightest plank (test_fleet_ink_farmstead), and `--farm-band-ink` is that text. The guard in
`tests/test_fleet_skin_guard.py` holds the file to layout, typography and tokens.

### `body[data-skin="farmstead"]`

Above `--farm-rain: #A9C4DC;`:

The effects' colours (#380), nothing draws them yet: the rain's streak on the boards, 3:1 on
the median lit plank of its weather (test_fleet_ink_farmstead). The cave adds its fireflies.

Above `--ink-pencil: #74695A;`:

The palette's pencil is too faint on this paper for a mark (3:1); a graphite with some soil in
it is not. The other inks are the palette's own.

## the three weathers (#4)

The same farm at a different hour: only the surfaces change, and the crop stages stay exactly as
they are, because a `done` that were a bloom in daylight and something else in the cave would be
a state the operator has to translate before they can read it. `daytime` is the block above.

### `body[data-skin="farmstead"][data-skin-variant="cave"]`

Above `body[data-skin="farmstead"][data-skin-variant="cave"] {`:

cave: lamplight underground

Above `--farm-firefly: #D8F07A;`:

A firefly's glow on the soil, 3:1 on --farm-soil.

Above `--ink-pencil: #968F82;`:

Lamplight: a paler pencil to be seen by, and a highlighter dark enough that the text read
through it keeps 4.5:1 (theme.check, test_fleet_ink_farmstead).

### `body[data-skin="farmstead"][data-skin-variant="rainy"]`

Above `body[data-skin="farmstead"][data-skin-variant="rainy"] {`:

rainy: a wet afternoon indoors

Above `--ink-pencil: #8A97AB;`:

A slate pencil: the palette's is lost on the night-blue paper (3:1).

## where the ink draws (#255)

The page stands aside for the canvas (app.css clears the panes, the header and the footer). What
is written on the planks is written in the band's own ink.

### `body[data-skin="farmstead"]:not(.ink-off) :is(header, footer) :is(button, inpu …`

Above `body[data-skin="farmstead"]:not(.ink-off) :is(header, footer) :is(button, input, select, …`:

A control is not written on the planks: it keeps the palette's own background, so it keeps the
palette's text as well. The band's near-white on a light button was 1.30:1 in daylight (#336).

### `body[data-skin="farmstead"]:not(.ink-off) header`

Above `body[data-skin="farmstead"]:not(.ink-off) header { will-change: transform; }`:

A clear header left Chromium compositing the canvas behind the page with a band missing along
the foot of the panes -- the drawing buffer was whole (read back), the screen was not. Its own
layer puts it right; the header holds no popover a stacking context could trap.

### `body[data-skin="farmstead"]:not(.ink-off) :is(.renew-strip, .away-strip)`

Above `body[data-skin="farmstead"]:not(.ink-off) :is(.renew-strip, .away-strip) { background: t …`:

The renew and away strips stand aside for the canvas like the panes (#337): opaque, they sat as
panels over the drawing. Keyed here, as every drawing skin keys it, not on `:has()` (#441).

### `body[data-skin="farmstead"]:not(.ink-off) .chip`

Above `body[data-skin="farmstead"]:not(.ink-off) .chip {`:

```text
The state as a crop stage, beside the chip's word and colour and never instead of them (#157):
the chip keeps a 24px box before its word, and the module draws the crop in it at twice the
art (#336), large enough to be read. The chip itself is clear, so the crop shows, and its word is
in the state's colour for words, `--<role>-text` (#328): read on the paper at 4.5:1, where the
state itself is held only to a mark's 3:1.
```

## the scrollbar (#181)

Wood, as the tokens app.css draws every thumb with.

### `body[data-skin="farmstead"]:not(.ink-off) .tile[data-tier]:not([data-tier="rai …`

Above `body[data-skin="farmstead"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { pad …`:

The ink's margin (#330): an open pane's left padding, where the done check and the error bang are
written (`shapes.js` `margin()`, anchored on the pane). 26px keeps the green check (to x+25.3)
off the pane number and the name. Keyed on the body's skin and not ink-off, as the legal pad keys
its 34px: a rule keyed on the ink canvas (`body:has(> #ink[data-skin])`) was left unapplied to the
panes by Chromium 153 after the layer set `data-skin`. Ink off keeps app.css's 10px.

### `body[data-skin="farmstead"]:not(.ink-off) .tile[data-tier="compact"] .head`

Above `body[data-skin="farmstead"]:not(.ink-off) .tile[data-tier="compact"] .head { row-gap: 8p …`:

The running pen under the name (#332): a compact pane's head wraps the name onto a line of its
own, and the line 2px below its foot needs more than app.css's 2px before the number and the
chip on the next line.
