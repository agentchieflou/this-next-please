# `skins/circuit/skin.css`

The reasoning beside the circuit board's stylesheet (#396). The server strips any comment from what it serves
(`agentdata/fleet/strip.py`). A builder who changes a rule changes its note here.

### `body[data-skin="circuit"]`, `[data-skin-variant="matte"]`

`--paper` is the board's dark end and `--board-max` its light end, the pair `skins.py` declares as the variant's
`composited_panel`. `--weave` is the fibreglass the module weaves towards, between the two. `--copper` (#6B4A2A,
2.02:1 on the solder) is decoration only and never under a word. Each `--ink-<tool>` is the variant's ink in
`skins.py`; `tests/test_fleet_ink_circuit.py` reads them back.


### `body[data-skin="circuit"][data-skin-variant="silk"]`

The board's light side, on `overcast`: a white solder mask (`--paper`) whose weave lies between it
and `--board-max`, copper a shade darker than the dark boards' so it still reads on white, and
the inks darkened (the pen to 4.5:1 at both ends, since a silkscreen word is text). `color-scheme:
light` so the form controls follow.

### The stand-aside

As the notebook's: the panes square, their cards and controls clear, the margin the mark table's `check`, `bang`
and `cross` are drawn in (`--ink-margin`, 26px), and a compact head's room under the name.

### The words

The pane's name and number, the stale-session note and the header's count are in `--mono`, the silkscreen's
face. The note is written in pencil and the count in pen: each 4.5:1 at both ends of both boards. Red never colours
a word (3.72:1 on the solder's light end).
