# `skins/glass/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

```text
Glass skin: HIG *Materials* -- a translucent material blurs what is behind it and adapts to
light and dark while keeping content legible (#155, #182, #254).

Since #257 this file paints nothing. `static/ink/skins/glass.js` draws the glass where the ink
layer draws: the ground as a lit mesh of three blobs, every pane as frost over it with its edge,
glint and shadow, and a rim for its state. Under `body.ink-off` glass is the one plain look every
skin shares (app.css and the palette), with glass's mark table drawn as plain CSS.

What is left here are the numbers the module reads at paint time -- the variant's fill, edge,
glint, shadow and mesh -- as custom properties on <body>, never a hex in the script. They are
the numbers `skins.py` declares as each variant's `mesh` and `fill`: `skins.composited_range`
turns those into the darkest and lightest colour a pane composites to, `theme.check` is run at
both ends, and `tests/test_fleet_skins.py` reads this file back to prove the two agree. The
guard in `tests/test_fleet_skin_guard.py` holds the file to layout, typography and tokens.

The default is Smoke, and `data-skin-variant="smoke"` says the same numbers again below, so a
bare `glass` in the config and a `glass:smoke` render alike.
```

### `body[data-skin="glass"]`

Above `--glass-mesh-1: rgba(88, 166, 255, 0.35);`:

The three blobs, at the same three places in every variant (the module's `MESH`): each its
colour at its peak alpha, fading to nothing at the end of its ray.

### `body[data-skin="glass"]:not(.ink-off) header, body[data-skin="glass"]:not(.ink …`

Above `body[data-skin="glass"]:not(.ink-off) header, body[data-skin="glass"]:not(.ink-off) foot …`:

The header and the footer are clear over the lit ground where the ink draws (app.css), so what
is written on them is written in the variant's own ink, pale on the dark grounds and dark on
frost.

## the colour variants (#4, #182)

One frost, four grounds. A variant is its mesh -- three blobs, colour and peak alpha, at the
same three places -- its fill, and the ink written on it. The `rgba()` numbers here are the ones
`skins.py` declares; `tests/test_fleet_skins.py` reads them back.

### `body[data-skin-variant="smoke"]`

Above `body[data-skin-variant="smoke"] {`:

smoke: neutral graphite behind the frost — over dark (#14171A); composites #181D24 … #273D57

### `body[data-skin-variant="azure"]`

Above `body[data-skin-variant="azure"] {`:

azure: cold blue depth, the darkest of the three — over blues (#0B1B33); composites #11213B … #1D3F56

Above `--ink-highlighter: var(--accent);`:

The one variant whose warn colour is too light to read the text through at its lightest
point (4.29:1): its highlighter is the accent's blue (4.76:1). Glass's inks are declared in
skins.py (`inks`) and checked there.

### `body[data-skin-variant="noir"]`

Above `body[data-skin-variant="noir"] {`:

noir: near-black, for a room with the lights off — over vanta-black (#000000): near-white blobs at
low alpha, so a black room stays a black room; composites #0A0A0A … #202020

### `body[data-skin-variant="frost"]`

Above `body[data-skin-variant="frost"] {`:

frost: the light one: warm paper under the same frost — over eye-relief-day (#F2ECDC); composites
#DED4B8 … #F3EDDD. The light variant is the hard one: a light pane over a light mesh has the
smaller contrast budget, and its blob alphas were solved against 4.5:1 at the darkest point.
Its edge is dark and its glint bright, because hairlines drawn for a dark ground read as smears
on paper.

## the scrollbar (#181)

The thumb's colour, as the tokens app.css draws every thumb with: pale on the dark grounds, dark
on frost.

### `body[data-skin="glass"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`

Above `body[data-skin="glass"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { padding …`:

The ink's margin (#330): an open pane's left padding, where the done check and the error bang are
written (`shapes.js` `margin()`, anchored on the pane). 26px keeps the green check (to x+25.3)
off the pane number and the name. Keyed on the body's skin and not ink-off, as the legal pad keys
its 34px: a rule keyed on the ink canvas (`body:has(> #ink[data-skin])`) was left unapplied to the
panes by Chromium 153 after the layer set `data-skin`. Ink off keeps app.css's 10px.

### `body[data-skin="glass"]:not(.ink-off) header`

Above `body[data-skin="glass"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
