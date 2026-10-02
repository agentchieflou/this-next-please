# The notebook: the desk as a page, drawn in pencil, pen, marker and highlighter

_Slices C (#249) and D (#250) of the ink epic (#246, [plan-ink.md](plan-ink.md)). The first skin drawn by the ink
layer ([desk-ink.md](desk-ink.md)), and the reference every later paper skin's marks are measured against._

The operator chose the notebook from the three.js prototype (`notebook-three.html`, plan-ink Decision 1). Its tools and
their shaders were already the layer's (`pen.js`). This is the rest of it: the mark table, which is plan-ink's state
grammar, and the paper.

## Choosing it

`notebook` is a skin in `skins.py`, so the settings page offers it and `theme.skin` in the config chooses it, like
glass. It has three variants:

| Variant | Is | Palette (`base`) | Paper |
| --- | --- | --- | --- |
| `notebook:light` (the default, so a bare `notebook` is the same) | graph-ruled notebook: white stock, blue rules, a red margin | `eye-relief-day` | `#FBFBF6` |
| `notebook:dark` | night notebook: charcoal stock and gel inks, the highlighter screened | `dark` | `#1B1E25` |
| `notebook:lamplight` (#398) | night study: warm charcoal stock under a still pool of lamplight, for hour six | `eye-relief` | `#2E2B26` … `#38342D` (the lamp's peak) |

Light and dark are the skin's pair (`sides`); Lamplight is a flavour on the dark side, offered in the picker as
*Notebook · Lamplight*, whose light side is the pair's.

**Dark is a variant, not a `notebook-dark` family.** Skins drive palettes (`skins.py`): a variant names the palette
it is drawn against, the way Voxel's Nether is red because its art is red. So one module draws every page, the
settings page lists them together, and the palette follows the choice. The layer does not need telling which is
which: it reads the stock's luminance from `--paper`, and multiplies the highlighter into a light stock or screens it
onto a dark one.

## The files

| File | Holds |
| --- | --- |
| `static/ink/skins/notebook.js` | the mark table (below), the `paper` hook (a shader: the rules, fibre and a faint light falloff, and Lamplight's still pool of light) and the `frame` hook (each pane's margin line). No colour and no markup (`tests/test_fleet_ink_notebook.py` holds both) |
| `static/skins/notebook/skin.css` | the colours as custom properties per variant, the handwritten labels, and the pane's margin and clear surfaces where the ink draws; nothing it paints (#257) |
| `skins.py` → `SKINS["notebook"]` | each variant's palette, its paper (the composited panel) and its inks, which `theme.check` holds |

### The colours

A palette colours the UI, and the notebook chooses the paper and its inks. Every colour is a custom property on
`body[data-skin="notebook"]`, read by the module through `tokens.css(name)` at paint time, never written in it:

| Property | Light | Dark | Lamplight | Is |
| --- | --- | --- | --- | --- |
| `--paper` | `#FBFBF6` | `#1B1E25` | `#2E2B26` | the stock |
| `--rule` | `#B7CBE3` | `#2C3A50` | `#48423A` (1.42:1) | the ruled lines, 28px apart |
| `--margin` | `#E3908C` | `#6E3437` | `#6E3A2E` (1.55:1) | each pane's margin line; Lamplight's a muted brick that defers |
| `--ink-pencil` | `#50545C` | `#B5BAC4` | `#B3A992` | graphite |
| `--ink-pen` | `#22398F` | `#94B4FF` | `#C9A227` | ballpoint, gel ink by night, the palette's gold under the lamp |
| `--ink-red`, `--ink-marker` | `#C8352B` | `#FF6A5E` | `#E8837A` | the red pen and the marker |
| `--ink-green` | `#2E7A4D` | `#6FD39A` | `#6FBF80` | the check |
| `--ink-highlighter` | `#F3DF4B` | `#CEBF40` | `#7E6418` | multiplied by day, screened by night (#329: `#E6D548` screened left the text at 4.26:1; #398: `#9C7C1E` screened left it at 4.09:1 at the lamp's peak) |
| `--lamp` | — | — | `1` | the lamp's strength; unset is 0, no lamp |
| `--lamp-max` | — | — | `#38342D` | the lamp's peak, clamped per channel: the paper's lighter end |

`theme.check` gets every pair: each ink 3:1 on its paper, the text 4.5:1 on the paper and through the highlighter,
for the variant's palette, at both ends of a paper the lamp lights. The words are the palette's own `--text` and
`--muted` (#257: a skin never recolours the palette), which read at 11:1 and 6.7:1 on the day paper, 13:1 and 7:1 by
night, and 7.8:1 and 5.6:1 at the lamp's peak. Three inks are words too, not only marks: the stale note is written in
pencil, a finding's margin note in the red and the header's count in the pen (`color: var(--ink-<tool>)` in
`skin.css`), so each keeps 4.5:1 at every end of every variant's paper (Lamplight's red: 5.34 and 4.69:1; its first
choice, `#E07A6E`, read 4.23:1 at the lit end). `tests/test_fleet_ink_notebook.py` also holds `skins.py` and
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
| needs you | the highlighter on the name and on the question, pencil loops round the choices | `.tile.needs-human .head .repo` → highlighter `lines`, `leaves: "erased"` (the name's highlight is taken up, never struck); `… .ask-q` and `… .approval .summary` → highlighter `lines`; `… .ask-choice` → pencil `loop`; `.tile.needs-human .asks:not([hidden])` → marker `loop` round the question card (pad -3): the loudest pane (#335) |
| answered | the question and its highlight struck in pen, and the chosen answer circled. Never the agent's name | `.ask.is-answered .ask-q` → pen `strike` (the highlight leaves by strike); the pressed `.ask-choice`, or the typed `.ask-answer` → pen `ellipse` |
| error | a red marker loop round the error's own words, and a bang in the margin | `.tile.state-error .why` → marker `loop` (#335; it was round the pane) and `.tile.state-error` → marker `bang` |
| done | a green check in the margin | `.tile:is(.state-done, .is-done)` → green `check` (`is-done` is the fold's own word, set by `drawTile` (#253); an unsupervised pane's chip says idle) |
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

**The lamp (#398).** A variant that sets `--lamp` (Lamplight sets `1`) gets a still pool of light on its stock: the
shader's `uLamp` brightens the paper toward `--lamp-max`, most at 30% across and 20% down the viewport and fading to
nothing 60% of the viewport's longer side away, and clamps every channel at `--lamp-max`, so the paper is never lighter
than the end its text is checked at. It is shaded in viewport pixels like the rest of the stock, so the plain stock
laid under a transcript is lit the same, and the rules are printed over it unlit. It never moves: it does not follow
the selected pane and is not animated, so the paper is built once, reduced motion has nothing to hold still, and an
idle desk draws no frame. With `--lamp` unset (`uLamp` 0) the shader skips it and every other variant's paper is
what it was (`tests/test_fleet_ink_notebook.py` reads the light and dark papers back at the lamp's centre against
the values recorded before it).

**Under the transcript the rules are the transcript's own (#338).** Its rows were 25px and the rules 28px, so the
rules drifted through the middle of text lines, and a line through text reads as struck, the grammar's own sign for
"gone". Under ink, `skin.css` makes a transcript row the pitch (`line-height: var(--pitch)`, no vertical padding, no
divider: the rules are the dividers), sets each row's text 2px low so a line's glyphs end 4px above its rule, lays the
rows at the transcript's bottom (`margin-top: auto` on the first, `flex-basis: 0` so the transcript's box does not move
as its content grows), and snaps its scroll to whole rows (`scroll-snap-type: y mandatory`, `scroll-snap-align: end`).
The `frame` hook covers the transcript's box with the same stock without rules (the shader's `uRuled`), and draws a
rule every 28px up from the transcript's bottom edge. A card shown or hidden above the transcript moves it inside an
unchanged pane, so the layer's frame signature carries the transcript's box (desk-ink.md §Following the page). Outside
the transcript the page's rules stay where they are; graph paper's grid is not ruled this way. A row whose label wraps
(`assistant text` in its 96px column) is two rules tall. `?ink=off` keeps the plain 25px rows and their dividers.
`inspect()` answers `{builds}`, the number of `frame` calls so far; `tests/test_fleet_ink_rules.py` is the test.

## Without ink

A shell the gate turns off (software, nothing measured, `?ink=off`, a lost context) gets `body.ink-off`. The layer's
plain fallback draws **the same table** as CSS: an outline for an outline or a loop, a tint for the highlighter, a
line-through for a strike, a bar in the margin for a check or a bang. Since #257 it is drawn on the one plain look
every skin shares, the palette's own page: the rules and the margin are the module's alone, and the stylesheet prints
none. No canvas is made and three.js is never fetched.

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

* **The skin:** offered by `skins.py` with a light, a dark and a lamplight variant; `skin.css` paints the numbers
  `skins.py` declares, `--lamp-max` at a lit paper's lighter end; `theme.check` holds every ink-on-paper pair at
  every end of the paper; every ink that colours a word keeps 4.5:1 there; the module carries no colour, no markup
  and no static import.
* **The grammar in ink:** idle, running, error and done driven through the real server's fold, each drawn when the
  class arrives and erased or struck when it goes. The running line grows with the turn, and its tip is lifted
  before it is struck.
* **Needs you and answered:** the name and the question highlighted, the choices looped; answered, the question and
  its highlight struck, the choice circled, the loops erased, and the name never struck.
* **Stale, a finding and the count:** the note written with its arrow and dashed outline, and unwritten when the
  session is renewed; the finding's ellipse, highlight and note; the count's old number struck beside the new, one
  kept.
* **Reduced motion** draws at once with no hand. **Dark** screens its highlighter on charcoal stock.
* **Without ink**, the same table drawn plain on the one plain look, with no canvas and no layer fetched; Lamplight
  without ink is the plain `eye-relief` page: its ground, panel and words.
* **At rest:** an idle notebook is zero DOM mutations and zero WebGL frames, after catching up in a bounded number
  of frames. The same desk then reads the paper back from the canvas at the lamp's centre (`DRAWN`, 1000x620: x=300,
  between two rules nearest y=124, under no mark): light and dark as recorded before the lamp, Lamplight lit and
  within `#2E2B26`..`#38342D`, and idle again, zero mutations and zero frames.
