# `skins/graph/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

```text
Graph paper (#253, slice G of the ink epic #246): a grid on the page's own 28px baseline, a
mechanical pencil, ruled strokes snapped to the grid, and each agent's trace plotted on it.

This file is the skin's layout, typography and colours -- and since #257 nothing it paints: the
drawing is `static/ink/skins/graph.js`, the paper and its grid in three.js, the mark table, and
the traces; under `body.ink-off` graph is the one plain look every skin shares. Every colour the
module uses is a custom property here, read at paint time (`tokens.css`), never a hex in the
script (desk-rendering rule 1):

  --paper        the stock
  --grid         a minor line, every 28px
  --grid-major   a major line, every fifth: 140px
  --ink-<tool>   the inks (docs/desk-ink.md §Tools), and --ink-trace for the plotted hour

skins.py declares the same numbers, and `tests/test_fleet_ink_graph.py` holds the two together
and runs `theme.check` on every ink against the paper.
```

### `body[data-skin="graph"][data-skin-variant="blueprint"]`

Above `body[data-skin="graph"][data-skin-variant="blueprint"] {`:

Blueprint: the same grid, white lines on a cyanotype. The highlighter screens onto it instead of
multiplying, which the layer decides from the paper's own luminance.

### `body[data-skin="graph"] #counts, body[data-skin="graph"] .tile .oldsession`

Above `body[data-skin="graph"] #counts,`:

The handwritten words: the header count and the margin note. A local hand, not a webfont: the
skin fetches nothing a desk that never chose it would not. Where the ink draws, the note is
pencil on the grid; plain, it is the page's own chip (#257: the plain look is every skin's).

### `body[data-skin="graph"]:not(.ink-off) .tile .trace`

Above `body[data-skin="graph"]:not(.ink-off) .tile .trace { opacity: 0; }`:

With ink on, the hour is plotted on the grid by the module (`series: false`), so the trace's own
drawing steps aside. Made clear, not hidden: it keeps its `role="img"` and its sentence, the
trace's text twin (#218), and a screen reader still reads it.

### `body[data-skin="graph"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`

Above `body[data-skin="graph"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { padding …`:

The ink's margin (#330): an open pane's left padding, where the done check and the error bang are
written (`shapes.js` `margin()`, anchored on the pane). 26px keeps the green check (to x+25.3)
off the pane number and the name. Keyed on the body's skin and not ink-off, as the legal pad keys
its 34px: a rule keyed on the ink canvas (`body:has(> #ink[data-skin])`) was left unapplied to the
panes by Chromium 153 after the layer set `data-skin`. Ink off keeps app.css's 10px.

### `body[data-skin="graph"]:not(.ink-off) header`

Above `body[data-skin="graph"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
