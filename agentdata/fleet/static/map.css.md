# `map.css`

The reasoning that used to be this stylesheet's comments, moved out of the source by #523
(decisions 18 and 19 on #429). The source keeps its rules, and the server strips any comment from
what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

/map (#405): the fleet as an accessible tree, and the map's whole plain look.

Tokens only, no colour literals: the palette and the skin reach this page as they reach the
desk. The tree IS the page; `#mapstage` is where the scene (#409) will draw, and it is not shown
until `body.map-scene` says there is one. No word here is in `--muted`: secondary words are
`--text` at weight 400 and at least 12px, so every sentence reads at 4.5:1 on every palette.

### `#maptree [role="treeitem"]:focus-visible`

Above `#maptree [role="treeitem"]:focus-visible { outline: none; }`:

Focus is the outline on the words, never a state colour (the `app.css` `#tickets li` precedent).

### `body.map-scene #map`

Above `body.map-scene #map { flex-direction: row; }`:

With a scene (#409 sets `map-scene`): the tree is a 320px column and the stage the rest.

### `@media (max-width: 900px)`

Above `@media (max-width: 900px) {`:

PyCharm's tool window and VS Code's view (app.css's 900px breakpoint): the tree above the stage.
