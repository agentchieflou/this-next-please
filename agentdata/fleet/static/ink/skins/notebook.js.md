# `ink/skins/notebook.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
The notebook (#249) and the night notebook (#250): the first skin drawn with ink, and the reference
every later paper skin's marks are measured against (plan-ink §C). The operator chose it from the
three.js prototype (`notebook-three.html`, epic #246 Decision 1); its tools and shaders are the
layer's `pen.js`, and this file is the rest of it -- the mark table, which is the state grammar,
and the paper.

ONE MODULE, TWO VARIANTS. `notebook:light` is white stock with blue rules and a red margin;
`notebook:dark` is charcoal stock with gel inks, and its highlighter is screened rather than
multiplied. The table is the same for both: what changes is the paper and the inks, and those are
custom properties in `static/skins/notebook/skin.css` (`--paper`, `--rule`, `--margin` and
`--ink-<tool>`), read here through `tokens` at paint time. No colour is written in this file, so a
variant, a palette or a scheme change repaints the page without it (desk-ink §Writing a skin, 3).

THE DOM IS THE TRUTH. Every row is a class or an attribute `app.js` already sets: `state-<state>`
and `needs-human` on the pane, the question card's rows and `aria-pressed` on its choices,
`is-answered` on a question the server passed on, `.oldsession` shown for a session on old skills
(#240), a transcript line's kind, and the header's unread count. Nothing here decides a state.
```

The state grammar (plan-ink §The state grammar), a row per mark. Rows are drawn in table order
within a pane, so the order below is the order a hand would work down a page.

### `export function marks`

In `marks`, above `{ selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3 },`:

idle: a pencil outline, and a pencil line under the name.

In `marks`, above `{ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline",`:

running: a pen line under the name that grows with the turn -- a step for every transcript
line that arrives while it works -- with the pen's tip resting at its end.

In `marks`, above `{ selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves …`:

needs you: the name and the question highlighted, pencil loops round the choices. The
approval card is the other way a pane asks, and its summary is its question. The name's
highlight is taken up when the agent no longer needs you, never struck: a line through an
agent's name reads as the agent crossed out (the graph paper's rule, #253).

In `marks`, above `{ selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },`:

answered: the question struck in pen (its highlight is struck by leaving, above), and the
answer circled -- the choice pressed, or the box when the answer was typed. Never the name.

In `marks`, above `{ selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },`:

error: a red marker box round the pane, and a bang in the margin.

In `marks`, above `{ selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },`:

done: a green check in the margin. `state-done` is the chip's word, which a pane the fleet
does not supervise shows as idle; `is-done` is the fold's own, and what a finished agent
carries (#253). A finished pane is idle and done, and has both marks.

In `marks`, above `{ selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },`:

stale (#240): a pencil note in the margin -- the chip's own words, handwritten -- an arrow
from it to the run line that says which session this is, and a dashed pencil outline.

In `marks`, above `{ selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },`:

a finding -- a friction the agent recorded: a red ellipse round the line, the highlighter on
its token, and its own text written in the margin.

In `marks`, above `{ selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },`:

the header's count, handwritten: when it changes the old number is struck and the new one
written beside it.

### `export const options`

Above `export const options = { paper: "--paper", hand: true, speed: 1 };`:

The paper is the skin's own (the `paper` hook); `--paper` is named too, so the layer knows how
light the stock is and multiplies the highlighter into it, or screens it onto the night page.

### `const PITCH`

Above `const PITCH = 28;`:

The rules' pitch: the page's 28px baseline, the one graph paper (#253) will share.

### `const MARGIN`

Above `const MARGIN = 28;`:

Where a pane's margin line runs, from its left edge: the check and the bang are written left of it.

### `function rgbOf`

Above `function rgbOf(tokens, name, fallback) {`:

A custom property's colour as [r, g, b] in 0-1 sRGB. The skin's colours are custom properties,
and `tokens.css` answers them as written: a hex, or rgb().

### `function stock`

Above `function stock(THREE, tokens, api, ruled, w, h) {`:

The stock: the paper's colour, its fibre and its light, ruled or not, `w` x `h` px. It is shaded
in viewport pixels, so a plain patch laid over the ruled sheet is the same sheet without rules.

### `export function paper`

Above `export function paper({ THREE, scene, tokens, api }) {`:

The stock behind the panes: the paper's colour, its rules, its fibre and its light.

### `let builds`

Above `let builds = 0;`:

How many times a pane's frame has been built, for `inspect`.

### `export function frame`

Above `export function frame({ THREE, scene, tokens, api }, el, box) {`:

One pane's margin: a red line down it, a little in from its left edge. A rail has no margin to
draw; its marks go down its middle. Under the transcript the rules are the transcript's own
(#338): the sheet's rules are covered with plain stock, and a rule is drawn every PITCH up from
the transcript's bottom edge, where its rows end, so each line of text sits on one.

### `export function inspect`

Above `export function inspect() {`:

What this skin draws of its own, for tests and a curious console: how many frames it has built.
