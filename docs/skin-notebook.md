# The notebook: the desk as a page, drawn in pencil, pen, marker and highlighter

_Slices C (#249) and D (#250) of the ink epic (#246, [plan-ink.md](plan-ink.md)). The first skin drawn by the ink
layer ([desk-ink.md](desk-ink.md)), and the reference every later paper skin's marks are measured against._

The operator chose the notebook from the three.js prototype (`notebook-three.html`, plan-ink Decision 1). Its tools and
their shaders were already the layer's (`pen.js`). This is the rest of it: the mark table, which is plan-ink's state
grammar, and the paper.

## Choosing it

`notebook` is a skin in `skins.py`, so the settings page offers it and `theme.skin` in the config chooses it, like
glass. It has two variants:

| Variant | Is | Palette (`base`) | Paper |
| --- | --- | --- | --- |
| `notebook:light` (the default, so a bare `notebook` is the same) | graph-ruled notebook: white stock, blue rules, a red margin | `eye-relief-day` | `#FBFBF6` |
| `notebook:dark` | night notebook: charcoal stock and gel inks, the highlighter screened | `dark` | `#1B1E25` |

**Dark is a variant, not a `notebook-dark` family.** Skins drive palettes (`skins.py`): a variant names the palette
it is drawn against, the way Voxel's Nether is red because its art is red. So one module draws both pages, the
settings page lists them together, and the palette follows the choice. The layer does not need telling which is
which: it reads the stock's luminance from `--paper`, and multiplies the highlighter into a light stock or screens it
onto a dark one.

## The files

| File | Holds |
| --- | --- |
| `static/ink/skins/notebook.js` | the mark table (below), the `paper` hook (a shader: the rules, fibre and a faint light falloff) and the `frame` hook (each pane's margin line). No colour and no markup (`tests/test_fleet_ink_notebook.py` holds both) |
| `static/skins/notebook/skin.css` | the colours as custom properties per variant, the handwritten labels, transparent panes so the paper and the ink show through, and the ruled page the plain fallback draws on |
| `skins.py` → `SKINS["notebook"]` | each variant's palette, its paper (the composited panel), its inks, and its own `text` and `muted`, which `theme.check` holds |

### The colours

A palette colours the UI, and the notebook chooses the paper and its inks. Every colour is a custom property on
`body[data-skin="notebook"]`, read by the module through `tokens.css(name)` at paint time, never written in it:

| Property | Light | Dark | Is |
| --- | --- | --- | --- |
| `--paper` | `#FBFBF6` | `#1B1E25` | the stock |
| `--rule` | `#B7CBE3` | `#2C3A50` | the ruled lines, 28px apart |
| `--margin` | `#E3908C` | `#6E3437` | each pane's margin line |
| `--ink-pencil` | `#50545C` | `#B5BAC4` | graphite |
| `--ink-pen` | `#22398F` | `#94B4FF` | ballpoint, gel ink by night |
| `--ink-red`, `--ink-marker` | `#C8352B` | `#FF6A5E` | the red pen and the marker |
| `--ink-green` | `#2E7A4D` | `#6FD39A` | the check |
| `--ink-highlighter` | `#F3DF4B` | `#E6D548` | multiplied by day, screened by night |
| `--text`, `--muted` | `#23262B`, `#6B7079` | `#E7E9EE`, `#9AA0AA` | the words written on the page |

`theme.check` gets every pair: each ink 3:1 on its paper, the text 4.5:1 on the paper and through the highlighter,
for the variant's palette and for the skin's own `text`. `tests/test_fleet_ink_notebook.py` also holds `skins.py` and
`skin.css` to the same numbers, so the declared and the painted colour cannot drift apart.

### The handwriting

The handwritten labels (an agent's name, the stale note, a finding's note, the header's count) use a **local cursive
stack**: Caveat where it is installed (the prototype's face), then Segoe Print, Bradley Hand, Chalkboard SE and the
system's `cursive`. No face is vendored. A web font would be fetched by every desk that chose the notebook and count
against the payload budget ([desk-engines.md](desk-engines.md)) for a label that reads the same in any hand.

## The state grammar

Every row is a class or an attribute `app.js` already sets. The skin never decides a state.

| State | Mark | Row (selector → tool, shape) |
| --- | --- | --- |
| idle | pencil outline, pencil underline under the name | `.tile.state-idle` → pencil `outline`; `.tile.state-idle .head .repo` → pencil `underline` |
| running | a pen underline that grows with the turn, and the pen-tip dot at its end | `.tile.state-running .head .repo` → pen `underline`, `grow: ".transcript > li"`, `step: 12`, `tip` |
| needs you | the highlighter on the name and on the question, pencil loops round the choices | `.tile.needs-human .head .repo`, `… .ask-q` and `… .approval .summary` → highlighter `lines`; `… .ask-choice` → pencil `loop` |
| answered | the question and its highlight struck in pen, and the chosen answer circled. Never the agent's name | `.ask.is-answered .ask-q` → pen `strike` (the highlight leaves by strike); the pressed `.ask-choice`, or the typed `.ask-answer` → pen `ellipse` |
| error | a red marker box round the pane, and a bang in the margin | `.tile.state-error` → marker `loop` and marker `bang` |
| done | a green check in the margin | `.tile.state-done` → green `check` |
| stale (#240) | a pencil margin note, *old skills — renew?*, with an arrow to the run line, and a dashed pencil outline | `.oldsession:not([hidden])` → pencil `write` and pencil `arrow` to `.runline`; `.tile:has(.oldsession:not([hidden]))` → pencil `outline`, `dash` |
| a finding | a red ellipse round the line, the highlighter on its token, and its own text as a margin note | `.transcript > li.friction` → red `ellipse`; its `.k` → highlighter `lines`; its `.v` → pencil `write` |
| the header count | handwritten; when it changes, the old number is struck and the new one written beside it | `#bellcount` → pen `write`, `rewrite` |

What each row maps onto, and the choices made where the plan left one open:

* **Running is the fold's `state-running`**, which the page shows only for a supervised agent. The line *grows with
  the turn*: a step for each transcript line that arrives while the mark is on the paper, up to the pane's edge. It
  is tied to what arrives, not to time, so a running agent that is quiet draws nothing and the idle-desk budget
  holds.
* **Answered is `is-answered`**, the one class the notebook added to the page (#249, its own commit): the question
  card marks the questions `/api/answer` says it passed on, until the agent records the answer and the fold drops
  them. Before it, the page had no signal between *sent* and *gone*. The circle is on the choice with
  `aria-pressed="true"`, which the card already set.
* **The version line is the run line** (`.runline`): the line under the head that says which run and which session
  this transcript is. The stale note is the chip's own words, `old skills` or `renew queued`, with *— renew?* after
  it in the stylesheet.
* **A finding is a recorded friction**, a transcript line of kind `friction`. The desk draws no other finding: a SQL
  check's findings reach it only as a tool result's text, with no class of their own.
* **The header's count is the unread count** (`#bellcount`), the one number in the page header. The count in the
  footer is not the header's.
* **No legend.** The page does not state the grammar in a line of its own. The marks are the states' own words
  underlined, highlighted or struck, and a legend would be one more line to read on every desk.

Three of these needed the layer to do something it did not: a line that grows, the pen's tip, and a word struck and
written again. They are general row fields, `grow`/`step`, `tip` and `rewrite` ([desk-ink.md](desk-ink.md) §A skin
is a mark table), added in their own commit.

## The paper

Under ink, the `paper` hook draws one full-screen quad behind everything: the stock's colour with a faint long fibre,
a rule every 28px (the page's baseline, which graph paper (#253) will share), printed a little unevenly, and a very
slight falloff of light from the top left. The `frame` hook draws each pane's margin line, 28px in from its left
edge. A rail has no margin, and its marks go down its middle. The panes are transparent (`skin.css`), so the rules and
the marks show through them. The check and the bang are written in the margin, left of the line.

## Without ink

A shell the gate turns off (software, nothing measured, `?ink=off`, a lost context) gets `body.ink-off`. The layer's
plain fallback draws **the same table** as CSS: an outline for an outline or a loop, a tint for the highlighter, a
line-through for a strike, a bar in the margin for a check or a bang. The notebook's stylesheet supplies the page it
is drawn on: the same rules on the same pitch as a printed background, and the margin as a 1px line in each pane. No
canvas is made and three.js is never fetched.

## Budgets

| What | Is |
| --- | --- |
| the module | 3.5 KB gzipped, fetched by the desk that chose the notebook, every shell (the fallback draws its marks too) |
| the stylesheet | 2.2 KB gzipped |
| the layer's additions (`grow`, `tip`, `rewrite`) | about 2 KB gzipped of the layer's modules, still under their 40 KB |
| an idle desk | zero DOM mutations and zero WebGL frames once the marks are drawn |
| catch-up | counted in frames, not milliseconds: within the frames a hand at the pen's speed needs, plus travel |

Building the idle-desk test found that **any** skin chosen through the config wrote to an idle page: `data-skin`,
`data-skin-variant` and `data-theme` on every snapshot, and the ground's retry setting `data-waiting` every 150ms for a
skin with no ground in its stylesheet. Both are fixed (#249, `tests/regressions/test_20260923_any_chrome_idle_skin_rewrites_itself.py`).

## Tests

`tests/test_fleet_ink_notebook.py`:

* **The skin:** offered by `skins.py` with a light and a dark variant; `skin.css` paints the numbers `skins.py`
  declares; `theme.check` holds every ink-on-paper pair; the module carries no colour, no markup and no static import.
* **The grammar in ink:** idle, running, error and done driven through the real server's fold, each drawn when the
  class arrives and erased or struck when it goes. The running line grows with the turn, and its tip is lifted
  before it is struck.
* **Needs you and answered:** the name and the question highlighted, the choices looped; answered, the question and
  its highlight struck, the choice circled, the loops erased, and the name never struck.
* **Stale, a finding and the count:** the note written with its arrow and dashed outline, and unwritten when the
  session is renewed; the finding's ellipse, highlight and note; the count's old number struck beside the new, one
  kept.
* **Reduced motion** draws at once with no hand. **Dark** screens its highlighter on charcoal stock.
* **Without ink**, the same table drawn plain on a ruled page, with no canvas and no layer fetched.
* **At rest:** an idle notebook is zero DOM mutations and zero WebGL frames, after catching up in a bounded number
  of frames.
