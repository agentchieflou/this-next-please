# `skills.css`

The reasoning for this stylesheet, kept out of the source (decisions 18 and 19 on #429). The source
keeps its rules, and the server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule or at-rule the notes sit in or above, by its selector or prelude, in
source order. A builder who changes a rule changes its note here.

### The file

/skills, the skills marketplace, over `app.css`: the toolbar, `.linkbtn` and the tokens are the
desk's. Tokens only, no colour literals. Secondary words are `--muted`, as on the desk, which holds
4.5:1 on every palette; a word in a state colour is written in its `-text` token (#328).

### `.sk-head, .sk-row`

The header and every row share one grid, so the columns line up without a `<table>`: a table's rows
cannot be a `patchList` (an expansion would be a second `<tr>` without a key), and a list of `li`
holding a row and its fold can. The column widths are the content's: a name, the description taking
what is left, the numbers narrow.

### `.sk-sort`

The sortable headers are buttons dressed as the other headers; the pressed one is underlined and
carries an arrow from its `aria-sort`, so the order is read by a screen reader as it is seen.

### `.sk-row > *`

Every cell clips on one line with an ellipsis; the whole value is the cell's `title`, and the
expansion holds the lists in full.

### `.sk-pill`

The three pills, outlined and small: *unused* and *shadowed* quiet, *missing* in the needs-you
colour, because a skill an agent asked for that is no longer on the disk is the one row that needs
a hand.

### `@media (max-width: 900px)`

Under 900 px the description, version and directory columns go; under 560 px the repositories and
the ok / failed count too. Each is still in the row's expansion.
