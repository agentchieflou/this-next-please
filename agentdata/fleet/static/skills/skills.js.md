# `skills/skills.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads (docs/desk-types.md); the server strips every comment from
what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

/skills, the skills marketplace (operator request, 2026-10): every skill the operator has, how often
each has been used, in which repositories, when last, and whether it worked. Reached from
`/settings` (its *Skills* block), or pasted as `/open?page=skills`. It reads one route,
`GET /api/skills` (`agentdata/fleet/skills.py`, docs/fleet-skills.md), and writes nothing: the page is
a reading of the ledger, never a hand on it.

A classic script after `common.js`, whose `q`, `pageUrl`, `patchList` and setters it uses. No
`innerHTML`: every row is a template filled through `textContent`. Drawn under the desk's contract
(docs/desk-components.md): a row is created once and patched on every draw, and a second draw of the
same rows makes no DOM mutation, which `tests/test_fleet_skills_page.py` holds with a
`MutationObserver`.

### `var skBack`

The two doors out carry the window's own query (`pageUrl`), as every page's links do: the token
lives in the query string, and a relative `href` would lose it.

### `var skState`

`rows` is the server's answer as it came; the view (the filter `q`, the `sort` key and its `dir`,
which rows are `open`) lives here and is applied on every draw, so a poll that brings new numbers
keeps what the operator opened and typed. `failed` is the last fetch's verdict: the line reads
*skills: unavailable* and the rows that were drawn stay, because an answer that stops coming is not a
reason to blank what was read.

### `function skKey`

A skill's name is its key, except a shadowed copy (a second directory holding the same name), which
is keyed by its directory as well, so two rows never share a key: `patchList` throws on that.

### `function skAgo`

The relative time the row shows; the ISO stamp goes in the cell's `title`. The ledger's stamps are
UTC without a zone suffix (`events.stamp`), so a `Z` is put on before `Date.parse`.

### `function skTop`

The three busiest repositories and *+n*; the whole list, with counts, is the cell's `title` and the
row's expansion.

### `function skSorted`

The filter is a substring over the name, the description, the directory and the busiest
repositories, so typing a repository's name finds what was used there. The sort is by the pressed
header, with the name as the tie-break, so the order is stable between polls and a row never jumps
for a tie.

### `function skCreate`

A row's listeners are bound here, once (contract rule 3). The row is a `role=button` with its own
tab stop, so the keyboard expands it as the mouse does.

### `function drawSkillRepos`

The expansion's repositories, keyed by name through `patchList`, each with its uses and when last.

### `function drawSkill`

One row, written through the setters: the name and its pills (*unused* for no use at all, *missing*
for a skill the ledger knows and the disk no longer has, *shadowed* for a copy the CLI does not read),
the description, the uses, when last (relative, the ISO stamp as the title), the busiest
repositories, ok / failed, the version (the SKILL.md's hash, the install time as its title) and where
it is installed. The expansion is drawn only while it is open, so a closed row costs a draw nothing.

### `function drawSkills`

The list through `patchList`, the totals line, and `aria-sort` on the pressed header, every write
guarded, so the 30-second poll that finds nothing new touches nothing (contract rule 7).

### `function skLoad`

One fetch; a failure is said on the line and never thrown.

### `setInterval(function () { if (document.visibilityState === "visible") skLoad(); }, SK_POLL_MS);`

Refreshed every 30 seconds while the tab is visible, and once more when it becomes visible again:
the ledger is folded on the server's own tick, and this page only needs to catch up with it.

### `window.FleetSkills = Object.freeze({`

The page's test handle: the rows and totals as read, and `load` and `draw` to call.
