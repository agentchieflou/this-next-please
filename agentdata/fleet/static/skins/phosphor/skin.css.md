# `skins/phosphor/skin.css`

The reasoning for this stylesheet, kept beside it rather than in it (decisions 18 and 19 on #429).
The source keeps its rules, and the server strips any comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the rule the notes sit in or above, by
its selector, in source order. A builder who changes a rule changes its note here.

### The file

Phosphor (#394): the glass, its inks, and the page laid on it. The drawing is the ink layer's
(`static/ink/skins/phosphor.js`, docs/skin-phosphor.md); this file holds what the module reads and
the room the page leaves for what it draws. Under `body.ink-off` it paints nothing: the page is the
palette's own plain look, with the same mark table drawn plain.

The words stay in the desk's `--mono`: no handwriting, and no web font.

### `body[data-skin="phosphor"]`

`--paper` and `--scan` are the glass's two colours, the two ends of the composited panel in
`skins.py`; `--board-max` is the brightest the glass is ever shaded (the scanline). The inks are the
ones `skins.py` declares, and `tests/test_fleet_ink_phosphor.py` holds the two to one number.
`--gutter` is the pane's left margin, where the check and the bang are drawn.

### `body[data-skin="phosphor"]:not(.ink-off) .tile`

The stand-aside, as the notebook's: where the beam draws, a pane is a region of the glass, not a
card. Its inner surfaces are clear, so the glass shows through; a menu that opens over the page is
opaque glass. The borders that stay are in the scanline colour.

### `body[data-skin="phosphor"]:not(.ink-off) .tile .oldsession`

A word coloured with an ink: the stale note in the pencil's green, the finding's text in red and the
header's count in the pen's green. Each keeps 4.5:1 at both ends of the glass (the test checks every
`color: var(--ink-<tool>)` here). A finding's token is highlighted, so it is written in the text's
colour, which keeps 4.5:1 through the highlighter.

### `body[data-skin="phosphor"]:not(.ink-off) header`

The header gets its own compositor layer, and the renew and away strips stand aside for the canvas
like the panes (docs/desk-ink.md §The page's own drawing).
