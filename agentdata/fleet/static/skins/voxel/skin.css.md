# `skins/voxel/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

Voxel skin: bevelled slabs and pixel status blocks (#156, on three.js #256).

Since #257 this file paints nothing. Where the gate turns ink on, `static/ink/skins/voxel.js`
draws the world: the ground as a floor of voxels, every pane's frame as a lit slab -- the panel
the text is read on, its drop shadow, the accent strip as a column of cubes -- and a status stack
in the strip's sockets. Under `body.ink-off` voxel is the one plain look every skin shares
(app.css and the palette), with its mark table drawn as plain CSS by the layer's fallback.

What is left: the module's inputs, read at paint time, and the room the page leaves for what it
draws. The surfaces are the skin's, not the palette's, so they are named here once per world
(`--voxel-*`) and no colour is written in the script. `--voxel-panel` is the variant's
`composited_panel` in skins.py -- the slab's face is exactly it, and
`tests/test_fleet_voxel_ink.py` holds the two together. The guard in
`tests/test_fleet_skin_guard.py` holds the file to layout, typography and tokens.

A variant re-colours the surfaces and nothing else: the stacks mean the same thing in every
world (#4). `--voxel-band-ink` is what is written on the header and the footer, which the page
clears over the ground where the ink draws; it keeps 4.5:1 on the lightest voxel of its ground.

### `body[data-skin="voxel"]`

Above `--scroll-thumb: #3A3D40;`:

The scrollbar (#181): stone, as the tokens app.css draws every thumb with.

### `body[data-skin="voxel"][data-skin-variant="nether"]`

Above `body[data-skin="voxel"][data-skin-variant="nether"] {`:

nether: netherrack and firelight

### `body[data-skin="voxel"][data-skin-variant="end"]`

Above `body[data-skin="voxel"][data-skin-variant="end"] {`:

end: endstone and void

## where the ink draws (#256)

The page stands aside for the canvas (app.css clears the panes, the header and the footer). The
pane's left edge is the slab's strip, ten pixels of cubes: the page's own accent border is
cleared so it does not draw over them (over the page's inline accent, #215, hence the
`!important`). An open pane's content keeps the room the strip takes through app.css's ink
margin (26px, #330), where the check and the bang are written clear of the number and the name;
a rail keeps its 17px. What is written on the header and the footer is written in the band's ink.

### `body[data-skin="voxel"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`

Above `body[data-skin="voxel"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { padding …`:

An open pane: the ink's margin (#330), keyed on the body as the legal pad keys its 34px; see
skins/glass/skin.css for why not on the ink canvas.

### `body[data-skin="voxel"]:not(.ink-off) .tile[data-tier="compact"] .head`

Above `body[data-skin="voxel"]:not(.ink-off) .tile[data-tier="compact"] .head { row-gap: 8px; }`:

The needs-you underline (#332): a compact pane's head wraps the name onto a line of its own, and
the marker under it (2px below its foot, 4.6px wide) needs more than app.css's 2px before the
number and the chip on the next line; the stale outline keeps off the chip row the same way.

### `body[data-skin="voxel"]:not(.ink-off) header`

Above `body[data-skin="voxel"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
