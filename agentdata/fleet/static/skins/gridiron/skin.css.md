# `skins/gridiron/skin.css`

The prose for this stylesheet (decisions 18 and 19 on #429): the source keeps its rules, and the
server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule the notes sit beside, by its selector, in source order. A builder who
changes a rule changes its note here.

### The file

The gridiron (docs/skin-gridiron.md): the field itself. Tokens, layout and typography only; the
drawing is `static/ink/skins/gridiron.js`. `skins.py` declares the same numbers and
`tests/test_fleet_ink_gridiron.py` holds the two together. The palette's own tokens are never set
here: the skin never recolours the palette (docs/themes.md).

### `body[data-skin="gridiron"]`

`--paper` is the turf's darker stripe and `--turf-max` its lighter one (`composited_panel` in
`skins.py`); the text and every ink are declared at both, so nothing the field paints may leave the
pair. `--yard` is the yard line, the pair's lighter end on the night field, so a line under a word
costs the word nothing. `--gi-first` and `--gi-scrimmage` are the first-down line and the line of
scrimmage: decoration the module draws between the transcript's rows, never an ink, never under a
word. The pitch and the gutter are the playbook's: 28px rows, a 36px margin for the flag, the ball
and the posts.

### `body[data-skin="gridiron"][data-skin-variant="daygame"]`

The light side, the pair the other way round: `--paper` is the lighter stripe and `--turf-max`
and `--yard` the darker. The lines are darker than the turf here, an amber first-down line and a
navy scrimmage, since a yellow does not hold on a pale green.

### `body[data-skin="gridiron"]:not(.ink-off) .tile[data-tier="compact"] .head`

A compact pane's head wraps the name onto a line of its own; 8px between its rows keeps the
scrimmage line under the head clear of the chip, as the playbook's compact head does.

### `body[data-skin="gridiron"]:not(.ink-off) .tile .transcript > li`

Every transcript line is one row of the pitch, so the first-down line advances one yard line per
turn line and never lands on a word's baseline.

### `body[data-skin="gridiron"]:not(.ink-off) .tile .transcript > li.friction > .v`

A finding's words are written in the pencil's chalk, 8.96:1 at the lighter stripe, where the pen's
yellow is decoration and the red would be 3.63:1. No text on the field is coloured in the pen or
the red.

### `body[data-skin="gridiron"]:not(.ink-off) #bellcount`

The header's count in the chalk, as the finding's words are.
