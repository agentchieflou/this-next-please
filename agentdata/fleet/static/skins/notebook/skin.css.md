# `skins/notebook/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

The notebook (#249) and the night notebook (#250): the paper, its inks, and the page laid on it.

The drawing is the ink layer's (`static/ink/skins/notebook.js`, docs/desk-ink.md §The notebook);
this file holds what the module reads and the room the page leaves for what it draws: the colours
as custom properties, the margin, and the typography. Since #257 it paints nothing: under
`body.ink-off` the notebook is the one plain look every skin shares (app.css and the palette),
with the same mark table drawn plain in these inks. No colour lives in the module. The light
variant is `notebook:light` (the default, so a bare `notebook` is the same page), the dark one
`notebook:dark`, and the night-study page `notebook:lamplight` (#398); `skins.py` names each one's
palette, and `tests/test_fleet_ink_notebook.py` holds this file and `skins.py` to the same numbers. The words are the palette's own text, which
`theme.check` holds on each paper; a skin never recolours the palette.

The handwriting is a local cursive stack, not a web font: the desk fetches nothing it does not
need, and a vendored face would count against the payload budget (desk-engines.md) for a label
that reads the same in any hand. The prototype's Caveat is used where it is installed.

## the paper and the inks

### `body[data-skin="notebook"][data-skin-variant="lamplight"]`

Lamplight (#398, epic #294): warm charcoal stock on `eye-relief`, under a still pool of lamplight,
for hour six. `--lamp: 1` turns the module's lamp on and `--lamp-max` is its peak, which the module
clamps every channel to; so the paper is a pair in `skins.py`, `--paper` at its darker end and
`--lamp-max` at its lighter, and every number is checked at both. A variant without `--lamp` has no
lamp (the module reads it as 0).

The rule is 1.42:1 on the paper. The margin is a muted brick at 1.55:1, under #398's ceiling of
1.6:1: on this page it is decoration that defers to the words, not a red line. The red and the
pen are words as well as marks (a finding's note and the header's count, below), so each keeps
4.5:1 at the lamp's peak: the red is `#E8837A` (4.69:1 there; `#E07A6E` read 4.23:1). The
highlighter is the palette's gold taken down to `#7E6418`: the layer screens it onto dark stock,
and `#9C7C1E` screened left the text at 4.09:1 at the lamp's peak (`#7E6418`: 4.65:1).

## the page on it

Where the ink draws, a pane is a region of the page, not a card: app.css clears it, and this
leaves its left padding as the margin, where the check and the bang are written, left of the red
line. Its inner surfaces are clear too, so the ink drawn under them shows through; a menu that
opens over the page is a slip of the same paper, opaque.

### `body[data-skin="notebook"]:not(.ink-off) .tile .transcript`

Above `body[data-skin="notebook"]:not(.ink-off) .tile .transcript {`:

The transcript is written on the rules (#338): a row is the pitch, its rows end at its bottom,
where the module measures its rules from, and it scrolls in whole rows. The rules are its
dividers, so a row draws none.

### `body[data-skin="notebook"]:not(.ink-off) .tile .transcript > li > *`

Above `body[data-skin="notebook"]:not(.ink-off) .tile .transcript > li > * { position: relative …`:

Centred in its 28px, a 12px line would end 6px above the rule; 2px lower it sits on it. The row
clips what is moved, so the list scrolls no further than its last row's end.

### `body[data-skin="notebook"] .tile .head .repo`

Above `body[data-skin="notebook"] .tile .head .repo { font-family: var(--hand); font-size: 17px …`:

Handwritten: the name, the stale note, a finding's margin note and the header's count. Where the
ink draws, each is written in its tool's ink.

### `body[data-skin="notebook"]:not(.ink-off) .tile .transcript > li.friction > .k`

Above `body[data-skin="notebook"]:not(.ink-off) .tile .transcript > li.friction > .k { color: v …`:

A finding's token is highlighted, so it is written in the text's colour, which keeps 4.5:1 through it.

### `body[data-skin="notebook"] #bellcount`

Above `body[data-skin="notebook"] #bellcount {`:

The count is written, and the number it replaces is struck just to its left: room for it.

### `body[data-skin="notebook"]:not(.ink-off) header`

Above `body[data-skin="notebook"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
