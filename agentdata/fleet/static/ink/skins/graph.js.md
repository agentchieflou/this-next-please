# `ink/skins/graph.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Graph paper (#253, slice G of the ink epic #246): a grid on the page's own 28px baseline, a
mechanical pencil, ruled strokes snapped to the grid, and every agent's hour plotted on it.

The pattern is `skins/example.js`, and docs/desk-ink.md §Writing a skin is the contract. Its
rules, as this skin keeps them:

* No static `import`: three.js is handed in, and nothing else is needed.
* Every mark comes from a class or attribute the page already sets (the table below), and the
  skin never writes the page. The hooks draw into the scenes they are handed.
* Every colour is a custom property of `static/skins/graph/skin.css`, read here through
  `tokens.css(name)` at paint time: `--paper`, `--grid`, `--grid-major`, `--ink-trace`. The inks
  are `--ink-<tool>`, which the layer reads itself.

THE GRID. A minor line every 28px, the page's own baseline -- the HIG hit target every control
on the desk is at least as tall as (app.css), so a row of buttons sits a square high -- and a
major line every fifth, 140px. Five is the engineering pad's own count, and it is the one that
lets an eye count squares: four or more minor squares in a row stop being countable at a
glance, and the heavy line every fifth is what makes "three squares" and "eight squares"
readable without a ruler. The lines start at the viewport's top-left, which is where the
layer's ruled strokes (`snap`) find them.

THE PENCIL. A mechanical pencil: the layer's pencil tuned thin (1.05px), even (almost no
pressure variation), steady (no wobble, no bow) and without taper, because a 0.5mm lead does not
thin at the ends the way a sharpened one does.

THE TRACE. `drawTrace` in app.js paints each agent's last hour on a 2D canvas. With this skin
drawing, that canvas steps aside (skin.css makes it transparent; it keeps its sentence for a
screen reader) and the same hour is plotted here as a graph line, on the grid line under the
canvas, from the data the page already has (`data-trace` on the canvas). A minute that stopped
for a person is a red tick up the square.
```

The page's baseline, and a major line every fifth.

### `const RULED`

Above `const RULED = { snap: GRID };`:

The ruled rows: outlines, dividers and underlines land on the grid.

### `export function marks`

Above `export function marks() {`:

The mark table: the paper state grammar (plan-ink §The state grammar), mapped onto what the page
already sets. `app.js` owns every one of these classes; the skin only reads them.

| state          | where the page says it                                   |
| idle           | `.tile.state-idle`                                       |
| running        | `.tile.state-running`                                    |
| needs you      | `.tile.needs-human`, and an open question in `.asks`      |
| answered       | a choice pressed: `.ask-choice[aria-pressed="true"]`      |
| error          | `.tile.state-error`                                      |
| done           | `.tile.is-done`: the fold's word (the chip says idle)    |
| stale (#240)   | `.oldsession` shown                                      |
| a finding      | a skill's STOP in the transcript: `li.friction`          |
| the count      | `#counts`                                                |
| the trace      | `.trace[data-trace]`                                     |

In `marks`, above `` Object.assign({ selector: `.tile.state-idle:not(:has(${stale}))`, tool: "pencil", shape: … ``:

idle: a pencil outline round the pane and a pencil underline under the name. A stale pane's
outline is the dashed one below instead.

In `marks`, above `Object.assign({ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underl …`:

running: a pen underline under the name.

In `marks`, above `{ selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves …`:

needs you: the name highlighted, and the question, and pencil loops round its choices. The
name's highlight is taken up when the agent no longer needs you: the grammar strikes the
question, never the agent's name.

In `marks`, above `` { selector: `.tile ${open} .ask-choice[aria-pressed="true"]`, tool: "pen", shape: "ellip … ``:

answered: the question's highlight leaves the way ink does, struck through in pen along the
question -- and the chosen answer is circled.

In `marks`, above `Object.assign({ selector: ".tile.state-error", tool: "marker", shape: "outline" }, RULED),`:

error: a red marker box round the pane, ruled, and a bang in the margin.

In `marks`, above `{ selector: ".tile.is-done", tool: "green", shape: "check" },`:

done: a green check in the margin. The fold's own `done`: an agent nothing supervises is
drawn as idle by the chip, so its pencil stays and the check is added to it.

In `marks`, above `` { selector: `.tile ${stale}`, tool: "pencil", shape: "write" }, ``:

stale (#240): the chip written in pencil as a margin note, an arrow from it to the run line,
and a dashed pencil outline.

In `marks`, above `{ selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse" },`:

a finding: a red ellipse round the line, the highlighter on its token, and its own text
written as the note.

In `marks`, above `{ selector: "footer #counts", tool: "pen", shape: "write" },`:

the count: handwritten.

In `marks`, above `Object.assign({ selector: ".tile .head .trace[data-trace]", tool: "pencil", shape: "divi …`:

the trace: its axis, ruled in pencil on the grid line under the canvas. The row also names
`data-trace`, which is how the layer knows to look again when the hour changes.

### `export function options`

In `options`, above `series: false,`:

The hour is plotted on the grid by `frame` below, so the layer's own trace rows (#257) are off.

### `function colour`

Above `function colour(THREE, tokens, name, fallback) {`:

A custom property as a three.js colour; the palette's muted token if the stylesheet has not
arrived yet, so nothing here is ever a colour of its own.

### `function rules`

Above `function rules(THREE, w, h, every, skip) {`:

Lines at `every` px across a w x h box, leaving out every `skip`th: the minor lines leave room
for the major ones rather than being drawn twice under them.

### `export function paper`

Above `export function paper({ THREE, scene, tokens, api }) {`:

The stock and its grid, under everything. Called when the skin arrives, on a resize and on a
palette change, each time into an empty scene.

## the traces

### `const plots`

Above `const plots = new Map();`:

One plot per pane, kept for `tick` (the one thing a skin may keep between calls): the pane's
group, what was plotted into it, and the signature it was plotted from.

### `function hourOf`

Above `function hourOf(canvas) {`:

The hour as `drawTrace` has it: `peak|n n n!` -- the busiest minute, then a count a minute, with
`!` on a minute that stopped for a person.

### `function plot`

Above `function plot(THREE, tokens, p) {`:

Plot one pane's hour, if anything about it changed: its data, where the canvas is in the pane,
where the pane is against the grid, or the colours. The baseline is the grid line nearest the
foot of the canvas, where the pencil axis is ruled; a minute is a step along it, and the busiest
minute is as tall as the canvas.

Beside `const base = Math.round(cr.bottom / GRID) * GRID - pr.top;`:

pane coordinates, y down

### `export function plotted`

Above `export function plotted() {`:

What is plotted where, on the viewport: each pane's baseline, its points and how many minutes
stopped for a person. For the tests (`tests/test_fleet_ink_graph.py`), which import this module
with the token and so read the very instance the layer runs.

### `export function frame`

Above `export function frame({ THREE, scene, tokens, api }, el) {`:

A pane's frame: its hour, plotted. Called when the pane appears and when its size changes, into
an empty group that moves with the pane.

### `export function tick`

Above `export function tick({ THREE, tokens }) {`:

Every frame the layer draws -- which it does when the page changes, `data-trace` included --
plot again whatever changed (the layer draws the frame after this), and forget panes that have
gone. It never asks for a frame of its own: an idle desk draws nothing.
