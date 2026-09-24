# Graph paper: a 28px grid, a mechanical pencil, ruled marks and every agent's hour plotted

_Slice G (#253) of the ink epic (#246, [plan-ink.md](plan-ink.md)). A skin that draws with the ink
layer ([desk-ink.md](desk-ink.md)). Chosen like any skin: `theme.skin` is `graph` or
`graph:blueprint`, from the settings page or `POST /api/theme {skin}`._

| File | Is |
| --- | --- |
| `agentdata/fleet/static/ink/skins/graph.js` | the mark table, the pencil's tuning, the paper (`paper`), each pane's plotted hour (`frame`, `tick`) |
| `agentdata/fleet/static/skins/graph/skin.css` | every colour as a custom property and the handwritten words; nothing it paints (#257) |
| `agentdata/fleet/skins.py` (`graph`) | the variants, their base palettes, the paper, the heavy grid line and the inks `theme.check` holds |
| `tests/test_fleet_ink_graph.py` | everything on this page |

## The paper

A minor line every **28px** and a heavy line every fifth, **140px**, from the viewport's top-left.

* **28px is the page's own baseline.** It is the HIG hit target every control on the desk is at
  least as tall as (`app.css`: `min-height: 28px` on every button, chip and row), so a row of
  controls sits a square high.
* **A heavy line every fifth** is the engineering pad's count, and it is why the pad has one. Past
  four, minor squares in a row stop being countable at a glance; the heavy line is what makes
  "three squares" and "eight squares" readable without a ruler. Every tenth would leave 280px
  between heavy lines, wider than a compact pane, and so no heavy line inside most panes.
* With ink on, three.js draws the stock and both sets of lines (`paper`, called on arrival, on a
  resize and on a palette change). With ink off, graph is the one plain look every skin shares
  (#257): no grid, and the same marks drawn plain.
* With ink on, the panes, the header and the footer are **transparent** (app.css, for every skin
  whose canvas is on the page): they are regions ruled on the paper, not cards laid over it. The text is read on the paper (`composited_panel`), and where it crosses
  a heavy line it is read on that (`grid`, checked at 4.5:1 too).

| Variant | Base palette | Paper | Grid, heavy | Why |
| --- | --- | --- | --- | --- |
| `engineering` (default) | `eye-relief-day` | `#F3F6EC` | `#D3E0CC`, `#A8C3A0` | a green quad-ruled pad, graphite and a blue pen |
| `blueprint` | `blues` | `#123A66` | `#1E4C7E`, `#2F6096` | white lines on a cyanotype; the highlighter screens instead of multiplying |

## The tools

**The mechanical pencil** is the layer's pencil, tuned by the table's `tools`
([desk-ink.md](desk-ink.md) §A skin is a mark table): 1.05px wide, pressure that barely varies
(`pvar` 0.04, `wmin` 0.94), no wobble, no bow and **no taper** (`tin` and `tout` 0). A 0.5mm lead
does not thin at the ends the way a sharpened one does. Every other tool is the layer's own.

**Ruled strokes.** Outlines, dividers and underlines carry `snap: 28`, so the layer rules their
straight strokes onto the grid's lines, and keeps them in the pane and off its words (#331). An
outline's edges go onto a grid line inside the pane's padding band (between its border box and its
content box); the desk's panes have a band narrower than a square (9 to 13px against 28), so each
edge runs down its band's middle, ruled straight but off the grid, and its corners cross inside the
pane. An underline goes onto the first line in [its text's foot + 2, the next row's top - 2], where
its text's foot is the tallest box on the name's line (the chip and the age beside it); with no
line in that window it stays 2px under that foot, unruled. A divider goes to the nearest line. A
ruled stroke is drawn to a ruler, with no sag and no wander. Loops, ellipses, checks,
bangs and arrows stay hand-drawn: a tick drawn to a ruler is not a tick.

## The state grammar

plan-ink §The state grammar, mapped onto what `app.js` already sets. The skin decides no state.

| State | Where the page says it | Mark |
| --- | --- | --- |
| idle | `.tile.state-idle` | pencil outline, ruled; pencil underline under the name, ruled |
| running | `.tile.state-running` | pen underline under the name, ruled |
| needs you | `.tile.needs-human`; an open question in `.asks` | highlighter on the name and on the question, pencil loops round each choice |
| answered | a choice pressed (`.ask-choice[aria-pressed="true"]`) | the question's highlight leaves as ink does, **struck through in pen along the question**; the chosen answer circled in pen (its pencil loop is erased). When the agent no longer needs you, the name's highlight is **taken up** (`leaves: "erased"`), never struck through the name |
| error | `.tile.state-error` | red marker box round the pane, ruled; a bang in the margin |
| done | `.tile.is-done` | green check in the margin |
| stale (#240) | `.oldsession` shown | the chip written in pencil as the margin note, a pencil arrow to the run line, a dashed pencil outline, ruled |
| a finding | a skill's STOP in the transcript (`li.friction`) | red ellipse round the line, highlighter on its token, its own text written |
| the count | `#counts` | written by hand |
| the trace | `.trace[data-trace]` | a pencil axis, ruled, under the plotted hour |

What leaves, leaves by the layer's rule: pencil is erased, ink is struck, one struck mark kept per
row and element. Every mark is drawn plain under `body.ink-off` by the layer's fallback, from the
same table.

What the page did not say, and now does, each its own commit:

* **done.** The fold calls an agent `done` only once nothing supervises it, and `shownState` draws
  every quiet unsupervised agent as idle, so `state-done` never reached a tile. The pane carries
  `is-done` from the row's own `state` (`drawTile`). The chip still says idle, which is true, and
  the pencil of an idle pane stays with the check added to it.
* **the trace's hour.** `drawTrace` writes the data it paints as `data-trace` on the canvas.

Not drawn yet, because the layer has no mechanism for them and the notebook (C, #249) is building
it for every paper skin: the running underline **growing with the turn** and its **pen-tip dot**,
and the header count's **old number struck with the new one written beside it** (the count is
handwritten, and rewritten in place). They are B's "not in B" list, assigned to C. The graph
paper adopts them from C's shared grammar when it lands, rather than building them twice.

## The traces

`drawTrace` paints each agent's last hour on a 2D canvas in the pane's head. With this skin
drawing, the canvas is made **transparent**, not hidden: it keeps its `role="img"` and its
sentence, the trace's text twin (#218). The same hour is plotted by the skin as a graph line:

* from `data-trace` on the canvas, which is the page's own data (`peak|n n n!`);
* on the **grid line nearest the canvas's foot**, where the table rules a pencil axis (the
  divider row), across the canvas's width, a minute a step, the busiest minute as tall as the
  canvas;
* a minute that stopped for a person is a red tick up the square, in `--ink-red`;
* in the pane's frame group (`frame`), and plotted again in `tick` when the data, the canvas's
  place or the pane's place against the grid changes. `tick` runs only on frames the layer draws,
  and the axis row naming `[data-trace]` is what makes a new hour one of them. The skin never asks
  for a frame, so an idle desk draws none.

With ink off, the 2D canvas is the trace. K (#257) moves `drawTrace` into the layer for every
skin; until then this is the graph paper's own.

## Colours

Every colour is a custom property of `skin.css`, per variant, and the module reads them at paint
time (`tokens.css`), never as a hex: `--paper`, `--grid`, `--grid-major`, `--ink-<tool>` and
`--ink-trace`. `skins.py` carries the same numbers, and `theme.check` holds every ink on the paper
at 3:1 and the text through the highlighter at 4.5:1 (rule 5), plus the text on a heavy line. A
test reads the stylesheet back against `skins.py`.

## Fonts

None fetched. The handwritten words (the count, the stale note) use a local stack, `--hand`:
Segoe Print, Bradley Hand, Chalkboard SE, Comic Neue, Comic Sans MS, then `cursive`. So the skin
adds nothing to the payload budget ([desk-engines.md](desk-engines.md)) beyond its own two files,
which a desk fetches only when it chose the skin: the module 4.8 KB and the stylesheet 1.6 KB,
gzipped.

## Tests

`tests/test_fleet_ink_graph.py` drives real agent states (events the server folds, and a live lock
for running) rather than setting classes the page owns:

* each state's mark arrives when the page sets it and leaves by erase or strike; the question is
  struck and the name never is;
* ruled strokes lie on grid lines, or, for an outline, down its padding band's middle and, for an
  underline, under its row when no line fits (`Ink.inspect()` marks' `bounds`, #331); at 1400 and
  700px no outline leaves its pane or crosses the transcript, and the running underline crosses no
  word but its own (`tests/regressions/test_20260923_any_chrome_graph_outline_through_text.py`);
* the tuned pencil is thin, even and straight, and the layer refuses a `snap`, `leaves` or `tools`
  it cannot honour, naming the row;
* the hour is plotted on the axis's grid line from `data-trace`, again when it changes, with the
  canvas transparent and still its sentence;
* reduced motion draws and leaves at once;
* the plain fallback draws the same table on the CSS grid, with the 2D trace, fetching none of the
  layer;
* `theme.check` holds every ink, and the stylesheet paints the numbers `skins.py` checks;
* an idle graph desk is zero DOM mutations and zero WebGL frames, and its marks catch up in the
  frames a hand at the pen's speed needs.
