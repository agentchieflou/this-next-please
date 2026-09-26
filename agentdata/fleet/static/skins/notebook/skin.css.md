# `skins/notebook/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries rules and nothing else.

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
`notebook:dark`; `skins.py` names each one's palette, and `tests/test_fleet_ink_notebook.py`
holds this file and `skins.py` to the same numbers. The words are the palette's own text, which
`theme.check` holds on each paper; a skin never recolours the palette.

The handwriting is a local cursive stack, not a web font: the desk fetches nothing it does not
need, and a vendored face would count against the payload budget (desk-engines.md) for a label
that reads the same in any hand. The prototype's Caveat is used where it is installed.

## the paper and the inks

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
