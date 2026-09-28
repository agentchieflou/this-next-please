# `skins/playbook/skin.css`

The prose for this stylesheet (decisions 18 and 19 on #429): the source keeps its rules, and the
server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule the notes sit beside, by its selector, in source order. A builder who
changes a rule changes its note here.

### The file

The playbook (#389): a coach's chalkboard. Tokens, layout and typography only; the drawing is
`static/ink/skins/playbook.js`. `skins.py` declares the same numbers and
`tests/test_fleet_ink_playbook.py` holds the two together. The palette's own tokens are never set
here: the skin never recolours the palette (docs/themes.md).

### `body[data-skin="playbook"]`

`--paper` is the board's darkest end and `--board-max` its lightest (`composited_panel` in
`skins.py`): the text's contrast is declared at `--board-max`, so nothing the board paints may be
lighter (#390). `--yard` is the faint yard line, 1.27:1 on the board. The hand is a local cursive
stack, no web font.

### `body[data-skin="playbook"]:not(.ink-off) .tile[data-tier="compact"] .head`

The O round the pane's number: a compact pane's head wraps the name onto a line of its own, and the
ring (3px out from the number's box, in the 2.8px chalk) needs more than app.css's 2px between the
head's rows, or it lands on the chip and the stale-session note (`test_fleet_ink_bounds.py` at
700px), as the legal pad's, the voxel's and the circuit board's compact heads do.

### `body[data-skin="playbook"]:not(.ink-off) .head .n`

The O the ink draws round the pane's number replaces the number's box.

### `body[data-skin="playbook"]:not(.ink-off) .tile .transcript > li.friction > .v`

A finding's words are written in the pencil's chalk: 7.92:1 at `--board-max`, where the pen's
orange would be 3.56:1 and the red 4.27:1. No text on the board is coloured in the pen or the red.

### `body[data-skin="playbook"]:not(.ink-off) #bellcount`

The header's count, in the pencil's chalk for the same reason.
