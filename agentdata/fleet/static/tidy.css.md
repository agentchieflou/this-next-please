# `tidy.css`

The reasoning for this stylesheet, kept out of the source (decisions 18 and 19 on #429). The source
keeps its rules, and the server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule or at-rule the notes sit in or above, by its selector or prelude, in
source order. A builder who changes a rule changes its note here.

### The file

/tidy, the cleanup guide the map pops out (operator request, 2026-10): one column of one decision
at a time, over `app.css` (its tokens, its toolbar, `.linkbtn`). Tokens only, no colour literals, so
the palette and the skin reach it through the page dressing (`serve._page`) as they reach the map.
No word is in `--muted`: secondary words are `--text` at weight 400, so every sentence reads at
4.5:1 on every palette, as on /map and /m.

### `#tidysteps li.is-now`

The tree being decided now: the accent border and weight, never a state colour, because a step is
not a state. A handled tree is dashed rather than struck: what was done is still a fact to read.

### `#tc-options`

The options are radio buttons in one fieldset, one of them pre-selected: the recommendation is the
default, and changing it is one press, which is what "decisive, with a human in the loop" means.

### `.tc-rec`

The *recommended* mark beside the option the guide chose, outlined in the accent like the step it
belongs to.

### `.tc-go`

The one button that changes anything on this page. Bordered in the accent so it is the loudest thing
on the card, and disabled while a press is being answered, so a double press is one decision.

### `@media (pointer: coarse)`

44 px targets and a 16 px input on a touch screen, as on /m.

### `.tc-label`

The heading over the overlap list: what the list is and which way the comparison goes (lower debt
keeps the work), so the numbers under it read as an argument rather than as data.
