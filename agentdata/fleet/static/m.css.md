# `m.css`

The reasoning for this stylesheet, kept out of the source (decisions 18 and 19 on #429). The source
keeps its rules, and the server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule or at-rule the notes sit in or above, by its selector or prelude, in
source order. A builder who changes a rule changes its note here.

### The file

/m (#581): the phone page's whole look, over `app.css` (the tokens, the buttons, the `.chip` state
grammar and `.ask-choice`/`.ask-answer`, which it reuses rather than restyles). It follows the
phone-and-portrait matrix (`mobile_ux_requirements.md` Web Q4): one column, `100dvh`, safe-area
padding, 44 px targets, 16 px inputs (so iOS does not zoom into a field), and the decision row
sticky. Tokens only, no colour literals: the palette and the skin reach this page through the
page dressing (`serve._page`) as they reach the desk. No word here is in `--muted`: secondary
words are `--text` at weight 400, so every sentence reads at 4.5:1 on every palette, as on /map.

### `body`

Above `body { height: auto; min-height: 100dvh; overflow-x: hidden; }`:

`app.css` pins the desk's body to the viewport; the phone page scrolls as a document instead, so
the list and an open agent's sheet are one scroll, and nothing is wider than the glass.

### `header`

Above `header { position: sticky; ... }`:

The live dot and "N need you" stay on screen while the list scrolls, below the notch.

### `#m button, #m input, .mfoot a`

Above `#m button, #m input, .mfoot a { min-height: 44px; font-size: 16px; }`:

The matrix's targets and fields, whatever the pointer says: `app.css`'s `(pointer: coarse)`
block does the same for the desk, but a tablet with a keyboard cover reports a fine pointer.

### `body.is-open #agents`

Above `body.is-open #agents { display: none; }`:

One open agent at a time, in place of the list; `back` gives the list back.

### `#agents .needs-human .pick`

Above `#agents .needs-human .pick { border-color: var(--human); border-left-width: 4px; }`:

The fold is the server's (`needs_human` on the attention row): the page only marks it, with the
desk's `--human` edge and the name underlined, never a state colour of its own.

### `#open .decide`

Above `#open .decide {`:

The decision row (approve, deny; answer; reply) is sticky at the bottom of its card, over the
home indicator, so the buttons are reachable however long the payload preview is.
