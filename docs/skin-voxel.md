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
| stacks | one `InstancedMesh` in the paper group, over the slabs | six per pane: three blocks, a crack's second half, a pebble, an ore fleck; then the effect pool's pieces (§Effects), up to 192 |

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

The effect pool (#377) lives in the stacks mesh: its room grows by `FX_CAP` (192) instances, and a
piece is written after the stacks by the same writer, on slot 0 (page coordinates). The ground flash
rewrites the ground mesh's own colours. Nothing an effect draws goes in the effects group, so a blast
is still three draw calls.

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
| needs you | `.tile.needs-human` | the top block rises 5px out of its socket | `.tile.needs-human .head .repo`: highlighter, lines; and each open question, `.tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q`: highlighter, lines (#334); and the question card, `.tile.needs-human .asks:not([hidden])`: marker, loop on its border (pad -3), the loudest pane (#335) |
| running | `.tile.state-running` | two blocks; the top one turns a quarter every 3s | `.tile.state-running .head .repo`: pen, underline (#334) |
| error | `.tile.state-error` | the top block cracks into two halves, knocked off square | `.tile.state-error .why`: marker, loop round the error's own words (pad 0, #335; it was round the pane); and `.tile.state-error`: red, bang in the pane's margin (#330) |
| done | `:is(.state-done, .is-done)`: the chip's word, or the fold's for a finished agent nothing supervises, whose chip says idle (#253, #333) | the stack is set full, three blocks, flush | `.tile:is(.state-done, .is-done)`: green, check in the pane's margin (#330) |
| stale (#240) | `.oldsession` not `hidden` | a pebble on top of the stack | `.tile .oldsession:not([hidden])`: pencil, dashed outline |
| answered | the choice's `aria-pressed="true"` in the question card | the risen block settles as `needs-human` goes | `.tile .ask-choice[aria-pressed="true"]`: pen, loop (#334; green is done's) |
| finding | a transcript line `li.friction` or `li.denied` | an ore fleck in the bottom block | `.tile .transcript li.friction .v, .tile .transcript li.denied .v`: red, underline |

These are the state grammar every skin draws ([desk-ink.md](desk-ink.md) §The state grammar across
skins, #334); the blocks are the material voxel adds, never instead of a row. The highlighter and
the pen are each world's own (`--ink-highlighter`, `--ink-pen` in skin.css, `inks` in skins.py):
the name keeps 4.5:1 through the highlighter on the slab, and the pen is the world's running blue.

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

**The end states are still.** The crack, the ore fleck and the full stack are what an error, a finding
and a finish leave. The hits and rewards in §Effects (#378) play on the way in and are gone by 0.8 s;
an agent that stays errored has a static crack, never a "damaged" loop.

## Effects

A pane put away bursts into blocks that fly to where it went, as a minimised window goes to the Dock
(#377, epic #293). The cues are the module's `cues` table, matched by the layer from the page
([desk-ink.md](desk-ink.md) §Effects); `cue` plays them into the pool and `tick` moves them.

| Cue | Selector, on | What plays | Duration | Reduced motion | Where it draws | Colours a piece may wear |
| --- | --- | --- | --- | --- | --- | --- |
| blast | `#grid > .tile:not(.is-hidden)`, leave: `h`, the hide button, or gone from the registry | the pane's last box cut into chunks of side `max(12, ceil(sqrt(w*h/140)))`, at most 140; they swell 2 frames (x1.04), burst out from the centre at 260-620 px/s (200 px/s more upward), spin about z, fall at 1800 px/s², and from 0.18 s shrink to 6px over 3 frames and home on `dest` with a critically damped spring (ω 14). A piece within 8px of `dest` pops (2 frames). `dest` is the centre of `#hiddencount` for a hide, or of the pane's `#gone .gone-rail` for a removal, read every frame; with none, the pieces fall off the bottom. The ground under the box flashes (below) | ends by 0.8 s | nothing: the slab goes at once | the stacks mesh (paper + 1), and the ground mesh | the ring in `--voxel-edge`, the rest `--voxel-panel` x0.84, x0.92 or x1.0 |
| place | `#grid > .tile:not(.is-hidden)`, arrive: brought back from the hidden count | 8 six-pixel pieces fly from `#hiddencount` (from the pane's centre if the count is hidden) into the pane's three sockets and pop on arrival | ends by 0.35 s | nothing | the stacks mesh | `--voxel-edge` |
| hurt | `#grid > .tile.state-error`, arrive: the pane errors | the pane's strip cubes and sockets wear `--human` 0-90 ms and 180-270 ms (two flashes, never more: WCAG 2.3.1, on a 10px strip only); the stack knocks 3px left and eases back over 150 ms; the pane shakes 3px for 240 ms through `api.fx.animate(el, "hit")` (#374), which a pane holding focus or a selection declines, and then the blink plays alone. The crack is the end state | ends by 0.27 s | nothing: the crack at once | the slabs mesh (strip and sockets), the stacks mesh | `--human` |
| graze | `.tile .transcript li.denied`, `li.friction`, `li.error`, or `.tile .err:not([hidden])`, arrive: a refused, stopped or failed line, or the operator's own refused action | the strip cubes within ±16px of the line's vertical centre (clamped to the pane) wear `--human` for 90 ms, once; 3 four-pixel chips pop off the strip there, fall 30px and pop | ends by 0.4 s | nothing | the slabs mesh, the stacks mesh | the chips `--voxel-edge`; the blink `--human` |
| reward | `#grid > .tile:is(.state-done, .is-done)`, arrive: the agent finished | 5 orbs (4px, bevel 0) climb the strip from the pane's bottom quarter to the top socket, 60 ms apart, 0.25 s each, and pop on arrival; then 3 hearts (a 5x4 grid of 2px cubes each) rise 12px from the socket and pop by 0.75 s | ends by 0.75 s | nothing: the stack full at once | the stacks mesh | `--done` only: never `--human`, `--waiting` or `--idle` |
| break | `#modelcard`, `#dispatch`, `#keymap`, `#side` or a pane's `.scope`, each `:not([hidden])`, leave: a card or panel closed | 12-24 flat chips, 6-10px, fall from the lower half of the box, spin, and pop | ends by 0.5 s | nothing | the stacks mesh | `--voxel-edge`, or `--voxel-panel` x0.84..1.0 |

* **Hits and rewards stay in the strip.** Every hurt, graze and reward piece is in its pane's strip
  column (`x` in `[pane.x, pane.x + 14]`) or at most 14px above the pane's top, so none is behind text.
  A rail (`w < 90`) or a pane without a slot gets nothing. `--human` is at least 5.3:1 on
  `--voxel-edge` in every world (Overworld 5.34, Nether 13.41, End 5.93).
* **One graze per pane per 5 s.** An agent stuck retrying refused calls does not blink its strip
  continuously: ten refusals in a burst graze once. A hurt plays only on the arrival of `state-error`.
  Nothing already so when the page loads plays, nor after a reload: the layer arms its cues after its
  first match.
* **A grouped pane plays nothing.** A pane folded into its project's rail is `.is-grouped`,
  `display: none`, and still matches `:not(.is-hidden)`; a `blast` or `place` cue for it is dropped.
  `.smenu` has no row: it closes on every pick.
* **At most two blasts at once.** A third plays as a `break`. The pool holds 192 pieces; an exhausted
  pool pops its oldest.
* **The ground flash.** Ground voxels whose centre is inside the box, and outside the header and the
  footer, go to `--voxel-ground` x1.25 for 2 frames, then x0.6, and heal ring by ring from the outside
  back to their own shade by 0.8 s. x1.25 keeps Overworld's `--text` at 5.01:1 (x1.35 would leave
  4.51:1).
* **Why the pieces wear only the panel and the edge.** They fly under the page's words (the canvas is
  behind the page). On the ground Overworld's `--muted` falls to 1.97:1 and `--human` to 2.56:1, so no
  piece is ever the ground's colour. Every colour a piece may wear keeps each word colour at 4.5:1, or
  at the panel's own figure where that is lower.
* **Flat and drawn, never faded.** Every piece has bevel 0, so a face square to the camera is exactly its
  colour; it spins about z only; it ends by moving, shrinking or popping, never by alpha.
* **Frames.** A piece moves on the layer's `dt`, never less than a 60 Hz frame's worth, so each effect
  ends within `ceil(0.8 * 60) + 4` layer frames of its cue. `tick` answers true while a piece or a
  flashed voxel lives; the durations are constants in `voxel.js`, never in `skin.css`.

`inspect().fx` is `{live, played: {blast, break, place, hurt, graze, reward}, shook, ends: {near, far},
flashes, dest, pieces}`: `shook` counts the hurts whose pane `api.fx.animate` shook, `ends` counts a
blast's pieces that popped within 12px of their `dest` and elsewhere, and `pieces` is up to 64
`{kind, repo, x, y, s, c, bevel, spin}`. Each of `inspect().panes` carries `blink` (0, or the 1 or 2
flashes of the blink playing) and `knock` (px), and `inspect().tones` the four state colours the hits
and rewards are held to.

## Colours

No colour is written in the module. The palette's tokens colour the stack and the inks. The skin's own
surfaces are custom properties set in `skin.css` for each world and read through `tokens.css`:

| Property | Overworld | Nether | The End |
| --- | --- | --- | --- |
| `--voxel-ground` | `#5A3D28` | `#6B2A22` | `#2A2136` |
| `--voxel-panel` | `#1E221E` | `#2A1512` | `#16121C` |
| `--voxel-edge` | `#111111` | `#1A0907` | `#0B0810` |
| `--ink-highlighter` | `#BF9637` | `#FAA355` | `#C59020` |
| `--ink-pen` | `#5EF0FF` | `#79C0FF` | `#58A6FF` |

`--voxel-panel` is the variant's `composited_panel` in `skins.py`. It is exactly what the slab puts
behind the text, because a face square to the light is drawn in its own colour, and passed through as
sRGB. So the pair `theme.check` measures is the pair drawn. The inks the table uses (marker and red
`--human`, green `--done`, pencil `--muted`) are declared per variant as `inks` in `skins.py`, and each
must reach 3:1 on the panel. The highlighter and the pen (#334) are the world's own literals, the same in
`skins.py` and `skin.css`: the pen reaches 3:1, and the text keeps 4.5:1 through the highlighter as the
layer screens it onto the slab (`theme.highlight_under`) and through the plain fallback's 38% tint.

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
* Every colour an effect piece may wear, and the ground's flash, keeps every word readable (plain).
* Folded into the grammar test (#377): a hide plays one blast whose pieces all end within 12px of the
  hidden count; a grouped pane plays nothing; a removal flies to its gone rail; Escape on the model
  card plays one break; "show all" one place per pane. Each ends within `ceil(0.8 * 60) + 4` frames,
  in three draw calls, with flat pieces in the allowed colours and the geometry count unchanged; then
  the desk is idle. Reduced motion bursts nothing; `?ink=off` hides with no page error.
* Folded into `tests/test_fleet_ink.py`'s gesture-budget test (`measured`): the gestures, taken while a
  blast's pieces are in flight, stay inside `LOCAL_BUDGET_MS`.
