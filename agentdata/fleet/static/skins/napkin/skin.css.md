# `skins/napkin/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

Napkin notes (#252, slice F of the ink epic #246): the desk written on a quilted paper napkin.

The ink layer draws this skin (`static/ink/skins/napkin.js`): the quilted stock, the marks of the
paper state grammar, the felt tip bleeding along the emboss and a coffee ring under a pane idle
a long time. Since #257 this file paints nothing: it holds the colours the module reads (a
palette colours the inks, a skin chooses the paper) and the typography. Under `body.ink-off` the
napkin is the one plain look every skin shares (app.css and the palette), with the same marks
drawn plain by the layer's fallback. The guard in `tests/test_fleet_skin_guard.py` holds the file
to layout, typography and tokens.

The numbers are not chosen by eye. `--paper`, `--paper-seam` and `--coffee` are the numbers
`skins.py` declares for each variant; the darkest panel the text is read on is the coffee's rim
over a seam, and `tests/test_fleet_napkin.py` reads this file to prove the two say the same
thing. Every ink here is checked against both ends by `theme.check` (`inks` in skins.py).

The handwriting is a local cursive stack: no font is fetched (plan-ink ground rule 3), and a
machine with none of these falls back to its own `cursive`.

## the variants

Diner is the default, and `data-skin-variant="diner"` says the same numbers again, so a bare
`napkin` in the config and a `napkin:diner` render alike.

### `body[data-skin="napkin"] .tile .head .repo, body[data-skin="napkin"] #bellcoun …`

Above `body[data-skin="napkin"] .tile .head .repo,`:

The name, the count and the margin note are handwritten; everything else keeps the page's face,
so a transcript still reads as one.

## with ink: the napkin shows

The paper is drawn behind the page. app.css clears the bars and the panes for every skin that
draws; the row between them is the napkin's to clear. Cards on a pane keep their own ground.

### `body[data-skin="napkin"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`

Above `body[data-skin="napkin"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { paddin …`:

The ink's margin (#330): an open pane's left padding, where the done check and the error bang are
written (`shapes.js` `margin()`, anchored on the pane). 26px keeps the green check (to x+25.3)
off the pane number and the name. Keyed on the body's skin and not ink-off, as the legal pad keys
its 34px: a rule keyed on the ink canvas (`body:has(> #ink[data-skin])`) was left unapplied to the
panes by Chromium 153 after the layer set `data-skin`. Ink off keeps app.css's 10px.

### `body[data-skin="napkin"]:not(.ink-off) header`

Above `body[data-skin="napkin"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
