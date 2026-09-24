# Voxel on three.js

_Slice J (#256) of the ink epic (#246, [plan-ink.md](plan-ink.md)), built on the ink layer
([desk-ink.md](desk-ink.md) §Writing a skin). The voxel skin (#156) drew chunky bevelled slabs and pixel
status blocks in CSS and SVG, and faked their depth with inset shadows. On three.js the depth is real._

## What draws what

| | Where the gate is on (`?ink=on`, or a shell the probe measured as hardware) | `body.ink-off` |
| --- | --- | --- |
| the ground | voxels, 32px each, in `--voxel-ground` with a shade per voxel | the palette's ground (the plain look, #257) |
| a pane's frame | a lit slab: the panel block, its drop shadow, the accent strip as a column of cubes, three sockets at its top | the palette's panel and the page's accent border |
| a pane's state | its status stack, in the sockets (§The grammar) | the chip's word and colour |
| the marks | drawn by the layer, from the table in `voxel.js` | the same table, drawn plain by the layer's CSS fallback |
| words, controls, layout, typography | the page, always | the page, always |

The module is `agentdata/fleet/static/ink/skins/voxel.js`. The stylesheet,
`static/skins/voxel/skin.css`, paints nothing since #257 ([desk-ink.md](desk-ink.md) §What a skin's
stylesheet holds): it names the surfaces per world (`--voxel-*`), which the module reads, and where the
ink draws it clears the pane's accent border for the strip and keeps the strip's room, and writes the
header and the footer in the band's ink over the ground. Under `body.ink-off` voxel is the one plain
look every skin shares, and the CSS dirt, bevels and sprite sheet are gone.

Every variant draws: Overworld, Nether and The End. A variant changes the surfaces and nothing else, so
a state means the same thing in every world (#4).

## One draw call per material

There are three materials, and so three draw calls, whether one agent is on the desk or twenty.

| Material | Mesh | Instances |
| --- | --- | --- |
| ground | one `InstancedMesh` in the layer's ground group | one per 32px of the viewport |
| slabs | one `InstancedMesh` in the paper group | per pane: shadow, panel, three sockets, one cube per 10px of the strip |
| stacks | one `InstancedMesh` in the paper group, over the slabs | six per pane: three blocks, a crack's second half, a pebble, an ore fleck |

All three share one shader. A voxel is a box with a chamfered face, sized per instance in the shader,
so a bevel is the same number of pixels on a 10px cube and on a 900px panel. It is lit by **one
light**, from the top left and in front, which is the direction of the layer's own sun. Shading is
relative to the face: a face square to the camera is exactly its colour. A bevel towards the light is
lighter, and one away from it is darker.

**How the slabs follow the panes without a draw call per pane.** Each pane's voxels are built in the
pane's own coordinates and carry the pane's slot. Where the pane is now is a uniform, `uPane[slot]`.
The slab mesh's `onBeforeRender` writes it from the group the layer placed at the pane's top-left in
the same frame. So a gutter drag rewrites a few uniforms inside the frame the browser laid out, and
only a pane that changes size rebuilds its instances. The layer calls `frame` for that pane, and the
skin draws nothing into the pane's own group, because that would cost a draw call per pane. A desk
frames up to 63 panes this way. Past that, the rest keep their CSS frame.

`inspect()`, exported by the module, reports the renderer's own count of the back pass
(`renderer.info.render.calls`, read after the last voxel is drawn) as `drawCalls`. The tests assert
that this is 3.

## The grammar

The stack sits in the three sockets at the top of each pane's accent strip. How many blocks fill it
is the pane's progress: one while it is idle, two while a turn is in hand, and three when it is done.
The top block wears the state's colour (`--running`, `--waiting`, `--human`, `--done` or `--idle`),
and its response is what reads at a glance. Every response and every mark comes from a class or
attribute `app.js` already sets. The skin adds no state class and never writes the page.

| State | The page says | Voxel response | Mark (tool, shape) |
| --- | --- | --- | --- |
| needs you | `.tile.needs-human` | the top block rises 5px out of its socket | `.tile.needs-human .head .repo`: marker, underline |
| running | `.tile.state-running` | two blocks; the top one turns a quarter every 3s | none: the turning block is the running pen |
| error | `.tile.state-error` | the top block cracks into two halves, knocked off square | `.tile.state-error`: red, bang in the pane's margin (#330) |
| done | `:is(.state-done, .is-done)`: the chip's word, or the fold's for a finished agent nothing supervises, whose chip says idle (#253, #333) | the stack is set full, three blocks, flush | `.tile:is(.state-done, .is-done)`: green, check in the pane's margin (#330) |
| stale (#240) | `.oldsession` not `hidden` | a pebble on top of the stack | `.tile .oldsession:not([hidden])`: pencil, dashed outline |
| answered | the choice's `aria-pressed="true"` in the question card | the risen block settles as `needs-human` goes | `.tile .ask-choice[aria-pressed="true"]`: green, loop |
| finding | a transcript line `li.friction` or `li.denied` | an ore fleck in the bottom block | `.tile .transcript li.friction .v, .tile .transcript li.denied .v`: red, underline |

An error is a state that needs you (`agentstate.needs_the_human`), so its cracked block also rises.
Every other state (idle, starting, waiting for approval, blocked) is a stack in its colour and nothing
more.

**Drawn, never faded.** The marks are the layer's. A pencil mark that goes is erased, and an ink mark
that goes is struck. The blocks are materials, and they move: a block rises at 40px/s, a quarter turn
takes 0.6s, and a crack is immediate. Under reduced motion every block is where it ends up, and no block
turns.

**An idle desk draws nothing.** A running block's next quarter turn is one timer and one
`api.request()`. There is no animation loop, so a desk with no agent running asks for no frame at all.
A finding stays for as long as its line is in the transcript.

## Colours

No colour is written in the module. The palette's tokens colour the stack and the inks. The skin's own
surfaces are custom properties set in `skin.css` for each world and read through `tokens.css`:

| Property | Overworld | Nether | The End |
| --- | --- | --- | --- |
| `--voxel-ground` | `#5A3D28` | `#6B2A22` | `#2A2136` |
| `--voxel-panel` | `#1E221E` | `#2A1512` | `#16121C` |
| `--voxel-edge` | `#111111` | `#1A0907` | `#0B0810` |

`--voxel-panel` is the variant's `composited_panel` in `skins.py`. It is exactly what the slab puts
behind the text, because a face square to the light is drawn in its own colour, and passed through as
sRGB. So the pair `theme.check` measures is the pair drawn. The inks the table uses (marker and red
`--human`, green `--done`, pencil `--muted`) are declared per variant as `inks` in `skins.py`, and each
must reach 3:1 on the panel.

## Tests

`tests/test_fleet_voxel_ink.py`. The states in its browser tests are real. The server's fold is told
what each agent is, so the page draws them the way it would draw a real agent, and no test sets a class
`app.js` owns.

* Every variant is drawn by the layer with `?ink=on`, and drawn plain with it off: the palette's
  panel, no texture and no sprite, and the same table as CSS.
* There is one draw call per material, counted by the renderer, at one agent and at twenty.
* Each state's response and mark appears and leaves as the grammar says.
* The slabs follow a gutter drag in the frame that moves the panes, with no DOM write.
* `theme.check` holds the slab face and every ink, and every class the skin reads is one the page sets.
* An idle voxel desk makes zero DOM mutations and zero WebGL frames.
* The voxels settle within a bounded number of frames, and in one under reduced motion.
* `dispose` frees the geometry when the skin changes.
