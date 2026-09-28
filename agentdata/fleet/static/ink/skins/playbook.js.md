# `ink/skins/playbook.js`

The prose for this module (decisions 18 and 19 on #429): the source keeps its code only, and the
server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the declaration the notes sit in or
above, in source order. A builder who changes the code changes its note here.

### The file

The playbook (#389, epic #294): a coach's chalkboard. Every agent is an O, its turn a route in
orange chalk, and the state grammar is written in football notation. The board's colours are
custom properties in `static/skins/playbook/skin.css` (`--paper`, `--board-max`, `--yard` and
`--ink-<tool>`), read through `tokens` at paint time; no colour is written here
(docs/desk-ink.md §Writing a skin, rule 3). Nothing in this file or its stylesheet names a team
or a league (#318's names decision; `tests/test_fleet_ink_playbook.py` guards it).

docs/skin-playbook.md is the skin's page: the grammar table, the colours and their ratios.

### `export function marks`

Every row is a class `app.js` already sets (`setTileState`, `needs-human`, `is-done`), in the
order a hand works down a pane:

- **The player and the line of scrimmage.** An open pane's number gets a pencil O (`ring`), and
  its head a pencil line under it (`divider`). A rail (`data-tier="rail"`) has neither: its
  number is its whole face.
- **In the huddle** (idle): the notebook's two idle rows, in pencil.
- **The route** (running): a chalk line under the name in the pen's orange (`tool: "pencil"`,
  `ink: "pen"`: the chalk's stroke, the route's colour), growing a step per transcript line and
  ending in an arrowhead.
- **The option route** (waiting_approval): the same route, dashed.
- **Stopped at the line** (blocked): a red route ending in a bar, and a red X in the margin.
- **The flag and the call** (needs you, answered): the notebook's rows. Its pen rows (the struck
  question, the circled answer) are the pencil's chalk in the pen's ink, so they are erased like
  chalk when they go, never struck.
- **The fumble** (error): the notebook's marker loop round the why and its bang.
- **Touchdown** (done): the green check.
- **An audible, the film, the scoreboard** (stale, a finding, the header's count): the notebook's
  rows, the count written in the pen's ink with the pencil's chalk.

### `export function options`

A function of the variant (#392). The chalkboard: `paper: "--paper"` tells the layer the board is
dark, so the highlighter screens; `hand: "chalk"` puts a stick of chalk in every hand (#387); and
the pencil's tuning (`CHALK`) is the chalk the research probe drew on this ground, a wider, grainier,
less even stroke with short tapers. The play sheet: the default pencil and hand on light stock,
where the highlighter multiplies.

### `const PAPER_FS`

The board (#390, docs/skin-playbook.md §The board): the slate's grain and haze, three to five eraser
ghosts drawn toward `--board-max`, a yard line every five baselines from the first under the header,
and hash marks at one and two thirds of the width. The last line clamps every channel to
[`--paper`, `--board-max`]: the text's contrast is declared at the board's lightest end, so nothing
may be painted lighter.

### `export function paper`

On a light board (`tokens.dark` false: the play sheet, #392) the stock is print-paper fibre, with
no eraser ghosts, clamped per channel to [`--yard`, `--paper`]; the yard lines and hash marks are
the same.

Built when the skin arrives, on a resize and on a palette change (layer.js `prepare`), never per
frame: the board is static. The ghosts are seeded from the viewport's size, so a rebuild at the same
size draws the same board. Colours come from the stylesheet through `rgbOf`, as the notebook reads
its paper.

### `export function inspect`

`builds` counts the `paper` calls; `ghosts` and `top` say where the board put its smudges and its
first yard line, for the readback test.

## the moments (#391)

docs/skin-playbook.md §The moments is the full account. A record per pane (`recs`, keyed by the
pane, dropped once it leaves the page) holds what is shown for `needs-human`, done and
`state-error`, and each material's progress; `frame` rebuilds the materials at that progress,
since a resize or a palette change empties the group and kills the old strokes.

### `function chalk`

The hatch and the moments' strokes take the chalk's tuning on the dark board and the default
pencil on the play sheet.

### `function settle`

A new record starts at rest in its pane's current state: nothing is thrown on load.

### `function start`

A change seen in `tick` animates, unless motion is reduced, the desk is a restored cached one
(`body.is-stale`) or the pane is a rail: then it goes straight to rest.

### `export function tick`

Answers `true` only while something flies, hops or draws, so an idle board draws no frame.

### `export function dispose`

The groups are the layer's to free; the skin only forgets its records.
