# `tidy.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads (docs/desk-types.md); the server strips every comment from
what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

/tidy, the cleanup guide (operator request, 2026-10). The map's *clean up* opens it in a window of its
own. It reads `GET /api/tidy` -- every dirty working tree, the most recent first, each with the options
the server offers, the one it recommends and why (`agentdata/fleet/cleanup.py`, `agentdata/fleet/tidy.py`) --
and walks them one at a time: the guide says what it found and what it would do, the recommendation is
pre-selected, and nothing changes until the operator presses *do it*. That press is `POST /api/tidy`
with the `plan_id` of the survey on screen, so a tree that moved since is refused `changed` and shown
again as it is now, never acted on blind.

A classic script after `common.js`, whose `q`, `post`, `patchList` and setters it uses. No `innerHTML`:
every row is a template filled through `textContent`.

### `var tidyDid`

What was done to each tree this sitting, kept on the page so the last card can list it with its undo
command. The server journals the same in `<fleet dir>/cleanup.jsonl`; this is only the summary.

### `var tidyLeft`

Trees the operator chose to come back to (*next tree*). Cleared by *look again*, which surveys
everything afresh.

### `var tidyFirst`

`?repo=` from the map's per-checkout *clean up*: that tree is decided first, whatever its place in the
newest-first order; the rest follow in order.

### `function tidyNext`

The next tree nobody has decided or left for later, in the server's order: the most recent first.

### `function tidyDraw`

One card for the tree being decided: what it is, the guide's sentence (the server's `why`), the files,
where they also change and how much tech debt each home carries, and the options. The commit message
and branch name are only shown for the options that use them.

### `function tidyShow`

After every press the whole list is surveyed again, because deciding one tree changes the overlaps,
and so the recommendations, of its siblings.

### `function tidyGo`

The one write. A refusal is said on the card in the server's words; `changed` reloads, so the card
always shows the tree as it is.

### `function tidyDebt`

One home's debt as a line: the score and the parts it is made of, the same parts `tidy.debt` adds up,
so the recommendation can be checked by eye. The tree's own line comes first, then each home it shares
files with.
