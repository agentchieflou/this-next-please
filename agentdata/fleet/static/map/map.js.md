# `map/map.js`

The reasoning that used to be this file's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries code, and inline `/** @type {X} */ (expr)`
casts where `tsc` needs them, and nothing else.

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

/map (#405): the fleet as an accessible tree -- the map's text twin and its whole plain look.

A classic script like `settings.js`, loaded after `common.js`, whose token, `q`, `post`,
`pageUrl`, `patchList` and setters it uses and nothing else. It reads `GET /api/map` once
(docs/fleet-map.md §The graph) and draws it as a WAI-ARIA tree: projects, their checkouts
(worktrees marked) and each checkout's agent, then the project's branches, then the network.
The words are the graph's own `says`; the page adds no sentence of its own but the two group
names. The scene (#409) is drawn from this tree later. It stays live (#406): its own stream
from the graph's cursor, a throttled refetch, a live dot, and deleted branches kept as words.

The render contract holds here as on the desk: every write goes through the setters, so a draw
with nothing new to say makes zero DOM mutations, and `aria-expanded` is written only when an
item is created -- a redraw never undoes what the operator opened or closed. That choice lives
in the DOM, in memory, and is not persisted. Nothing on /map ever removes `ink-off`.

### `var MAP_BRANCHING`

Above `var MAP_BRANCHING = /^(p|c|bs):|^n:network$/;`:

The item keeps a `ul` for the ids that hold others; everything else is a leaf. Decided by the
id's kind, never by whether it has children today, so an item never has to change its shape.

### `function mapRows`

Above `function mapRows(graph) {`:

The graph as the tree's rows: `{id, say, cls, data, kids}`, one level per `patchList`.

### `function mapCreate`

Above `if (branching) li.setAttribute("aria-expanded", row.id.indexOf("bs:") === 0 ? "false" : …`:

The one place `aria-expanded` is written by a draw: `bs:` starts closed, the rest open.

### `var mapCurrent`

Above `var mapCurrent = null;`:

The item Tab lands on: the last one the operator reached, else the first.

### `var mapLanes`

Above `var mapLanes = {};`:

```text
Deleted branches (#406). A branch the previous graph had and this one lacks keeps its item, as
`gone` and *<name> · deleted*, so the scene (#413 strikes its lane) never shows a fact the words
lack. It stays until a later graph changes that project's branch list again. This is the only
thing the tree carries from one graph to the next; it lives in memory and is not persisted.
```

## load and handle

### `function mapNewer`

Above `function mapNewer(next, now) {`:

An answer is kept only when it is newer than the one drawn: the same `run` and a larger `n`, or
a new `run` (a restarted server). An `as_of` of null (an empty fleet) is always taken.

### `function mapFetch`

Above `function mapFetch() {`:

One `/api/map`. Its theme is not painted when a `theme` frame arrived while it was in flight:
that frame is newer than the answer.

### `function mapSoon`

Above `function mapSoon() {`:

A throttle, like the desk's `refreshSoon`: armed by the first frame and never pushed back by
later ones, so a busy fleet still refetches every 400 ms (a trailing debounce would never fire
while agents stream). Nothing is refetched while a caller's graph holds the tree.

### `function mapConnect`

Above `function mapConnect() {`:

The map's own stream, from the graph's cursor so it replays nothing already drawn, and with
`notify=0` (#356) so it never takes the desk's notifications.

In `source.onerror`, above `setTimeout(function () {`:

What was drawn in between cannot be trusted: re-read it, then resume from its cursor.

### `window.FleetMap = Object.freeze({`

Above `window.FleetMap = Object.freeze({`:

What a test and #409's scene hold on to. `draw` feeds the tree a graph of the caller's and
pauses the page's own drawing, so a refetch never overwrites it. `stream` is the live loop's
count of `agent` frames and its state (`live`, `reconnecting`, or "" before it opens).
