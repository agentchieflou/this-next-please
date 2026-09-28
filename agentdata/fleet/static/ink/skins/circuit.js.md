# `ink/skins/circuit.js`

The reasoning beside the circuit board's module (#396). The source keeps its code; the server strips every
comment from what it serves (`agentdata/fleet/strip.py`). The skin itself is described in
[docs/skin-circuit.md](../../../../../docs/skin-circuit.md). A builder who changes the code changes its note here.

### `marks()`

The notebook's rows, the state grammar every skin keeps (docs/desk-ink.md §The state grammar across skins), plus
three of the board's own: pin 1 ringed on every pane but a rail's (`.head .n`), a red `cross` in the margin of a
blocked pane, and the idle and stale outlines ruled with `snap: 4`, a board's grid. The running underline's `tip`
is the via at the end of the trace the pen lays.

### `options()`

`tools.pencil` is graph paper's mechanical pencil (thin, even, no wobble, bow or taper): the silkscreen.

### `BOARD_FS`

The solder mask and a plain fibreglass weave, warp over weft every 3px. `min(c, mask + 0.03)` keeps the weave at
most 3% brighter than the mask per channel, and `min(..., uMax)` keeps it under `--board-max`, the panel's light
end, which `theme.check` holds. No colour is written here: the mask, the weave and the ceiling are `--paper`,
`--weave` and `--board-max`, read through `tokens.css` at paint time.

### `frame()`

A 6px copper pad at the pane's top-left (x 8, y 2), in the band above its margin and its words, and a 1.5px copper
trace from it along the top edge at y 5, to 10px short of the right edge. Both are in the pane's own group, so they
move with the pane in a gutter drag; the layer calls `frame` again when the pane's size changes. A rail (under
90px) gets neither. `--copper` is decoration only, never under a word.

### The signals (#397): `boardOf`, `lamp`, `soot`, `scorch`, `tick`

One record per pane (`boards`), made at its first `frame` call and kept across rebuilds: the lines seen (a `WeakSet`
seeded at first sight, so a pane's backlog is never pulsed), the pulses in flight, the LED and the scorch.
`frame` marks what died with the group (a pulse's mesh, the LED, the scorch's strokes) and `tick` or `signals`
draws them again. A pulse's position is only its elapsed time over `PULSE_S` (320 ms), from the trace's far end to
the pad; delivered, its mesh is freed. At most `IN_FLIGHT` (3) per pane. `document.body.matches(".is-stale,
.is-replaying")` counts an arrival without a pulse. The LED is two circles, the halo at a fixed alpha (never
animated), in `tokens.waiting` or `tokens.done`. The scorch is two `api.stroke` paths under the `.why`, in the marker
at low pressure (`SOOT`), its head advanced at `SPEED` px a second and erased the same way; at rest (`frame`) or
under reduced motion it is drawn whole at once. `tick` answers `true` only while a pulse travels or the scorch is
drawn or erased. Classes are read with `matches`, never `classList`, so the module holds to the no-write check.

### `inspect()`

By repo: each pane's `led`, `scorch` and delivered `pulses`, and an open pane's board in page coordinates: where its group is (`at`), its pad and its trace. `pulses` at the top: delivered, in flight, arrived and skipped. The tests compare it
with where the pane is during a gutter drag.
