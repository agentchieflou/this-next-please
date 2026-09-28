# The circuit board: solder mask, silkscreen and copper

_#396 of the epic "Every palette gets a look" (#294). A skin that draws with the ink layer
([desk-ink.md](desk-ink.md)). Chosen like any skin: `theme.skin` is `circuit` or `circuit:matte`, from the settings
page or `POST /api/theme {skin}`._

`greens` ("calm and go; a leaf-green desk") was the last built-in palette with no look. It is drawn as a circuit
board: each agent a component on the board, with a copper pad and a trace, its number ringed as pin 1, and the state
grammar in silkscreen and copper. A board is on theme for a developer tool, and it is a different green from the
farmstead's growth.

| File | Is |
| --- | --- |
| `agentdata/fleet/static/ink/skins/circuit.js` | the mark table, the thin even pencil (`tools`), the board (`paper`), each pane's pad and trace (`frame`) |
| `agentdata/fleet/static/skins/circuit/skin.css` | every colour as a custom property, the words in `--mono`, and the page standing aside; nothing it paints (#257) |
| `agentdata/fleet/skins.py` (`circuit`) | the variants, their base palettes, the board's two ends and the inks `theme.check` holds |
| `tests/test_fleet_ink_circuit.py` | everything on this page |

## The variants

| Variant | Base palette | Board (`--paper` … `--board-max`) | Why |
| --- | --- | --- | --- |
| `solder` (default) | `greens` | `#0D2618` … `#1C3A28` | green solder mask, white silkscreen and bare copper |
| `matte` | `vanta-black` | `#0A0A0A` … `#1A1A1A` | a matte-black board, for a room with the lights off |

Both are dark, so `circuit:auto` means `solder`, as it does on any skin with no light and dark pair.

## The board

* **Solder mask** (`paper`): the mask colour, `--paper`, with a fine **fibreglass weave** under it: a plain weave,
  warp over weft every 3px, towards `--weave`. The weave is at most 3% brighter than the mask per channel and is
  clamped per channel to `--board-max`, so the board is never lighter than the panel's light end, which
  `theme.check` holds. A test reads the board back behind every transcript and finds it inside
  [`--paper`, `--board-max`].
* **A pad and a trace per pane** (`frame`): a 6px copper pad at the pane's top-left, in the gutter above the
  margin, and a 1.5px copper trace from it along the pane's top edge to 10px short of its right edge. Both are in
  the pane's own box and its own frame group, so they move with the pane under a gutter drag and are rebuilt when
  its size changes (`layer.js` `syncFrames`). A rail (under 90px) has neither.
* **Copper is decoration only.** `--copper` is `#6B4A2A`, 2.02:1 on the solder mask: it is never under a word, so
  no word is read on it, and no check holds it. A test reads every pixel inside every word of every pane and finds
  none of it copper.

## The state grammar

The notebook's rows ([skin-notebook.md](skin-notebook.md)), in the board's inks, with these changes:

| Row | Drawn |
| --- | --- |
| `.tile:not([data-tier='rail']) .head .n` | pin 1: a pencil `ring` round the pane's number |
| `.tile.state-idle`, the stale outline | ruled with `snap: 4`, onto the board's 4px grid |
| `.tile.state-running .head .repo` | a pen underline that grows with the turn (`grow`), ending in a via (`tip`) |
| `.tile.state-blocked` | a red `cross` in the margin |
| `.tile.state-error` | the grammar's marker loop round the `.why` and a marker bang |

**The pencil is the silkscreen**: thin and even, like graph paper's mechanical pencil (`tools.pencil`: 1.05px,
no wobble, no bow, no taper). Pencil still leaves by being erased, and pen, red, green and marker by a strike.

## The inks

| Tool | `solder` | `matte` |
| --- | --- | --- |
| pencil | `#E4EDE6` | `#D8D8D8` |
| pen | `#D9A066` | `#D9A066` |
| red, marker | `#F85149` | `#F85149` |
| green | `#7EE787` | `#3FB950` |
| highlighter | `#B7851E` | `#B7851E` |

Each is 3:1 or more at both ends of its board, and the text keeps 4.5:1 through the highlighter's screen at both
ends. The highlighter is the palette's amber `#D29922` darkened to `#B7851E`: through the screen `theme.check`
models (`highlight_under`), `#D29922` leaves the text at 4.15:1 on the solder's light end and 4.33:1 on the matte's.

**Words written in an ink** (the stale-session note in pencil, the header's count in pen) use only an ink that is
4.5:1 at both ends of both boards. Red is not one: it is 3.72:1 on the solder's light end, so it marks and never
colours a word.

## Plain

Under `body.ink-off` the board is the one plain look every skin shares (#257): the palette's own page, with the same
mark table drawn as CSS in the board's inks, and no canvas.
