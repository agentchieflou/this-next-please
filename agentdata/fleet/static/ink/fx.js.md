# `ink/fx.js`

The reasoning that used to be this file's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries code, and inline `/** @type {X} */ (expr)`
casts where `tsc` needs them, and nothing else.

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
Ink effects (#370, epic #293): the seam every one-shot effect hangs on, and the cues (#372).
docs/desk-ink.md §Effects, §The files and §Budgets.

Its own module, fetched by the layer only for a table that has effects (a skin that exports
`cues`, or `options.fx`), so the four modules every drawing desk loads stay inside `INK_BUDGET`
and effect code is held to `FX_BUDGET` (§Budgets). It imports nothing: the layer hands it
three.js, the scene and the draw order (`attach(layer, spec)`), and it writes nothing to the
page. It reads the page: the rows' matches, their boxes, and the records of `<body>`'s class.

DRAW ORDER. The group sits at `api.order.fx` (-5). three.js r160 sorts first by the innermost
Group's `renderOrder`, and the pane groups `framePanes` makes keep 0, so an effect draws over
the back pass (ground, paper) and under every pane's frame and every mark, whatever
`api.order.frame` says. Within one list three.js draws every opaque object before any
transparent one, so an effect's materials are `transparent: true`, like the skins' own. An
effect that must sit on a pane's frame goes into that pane's frame group.

THE CUES (#372, §Effects). A skin's `cues` rows, `{selector, on: "arrive" | "leave", cue}`, are
matched with the table, and its `cue(ctx, name, el, box, how)` plays each new one. A cue is
news, never history: nothing on a table's first match, while `body.is-stale` or
`body.is-replaying` (#371) is set or on the first match after, for an arrival in a pane that
only just arrived, without a skin, or under reduced motion.

AT REST. `match` (after the table is matched), `measure` (after every mark is measured) and
`deliver` (in each frame, after `prepare`) run only on frames the layer draws. `deliver` asks
for the next while a cue waits or a child of the group lives: at rest, neither.
```

### `export function attached`

Above `export function attached() {`:

How many layers have effects attached: 0 after every detach path (a table without `fx`,
`Ink.setSkin(null)`, `Ink.off()`).

### `const NAME`

Beside `const LANE = ".tile[data-repo]";`:

a pane, as the layer names one

### `const ROWS, WAIT, PER_FRAME`

Above `const ROWS = 16, WAIT = 16, PER_FRAME = 4;`:

The caps: rows in a table, cues waiting, cues delivered a frame.

### `const REAP`

Above `const REAP = 90;`:

The net: a child of the group older than this is taken out. In frames, like every duration on
the canvas (docs/desk-motion.md): 1.5 s at 60 Hz. No shipped skin relies on it.

### `const OBSERVED`

Above `const OBSERVED = ["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant" …`:

What the layer observes for any table (layer.js `setTable`), besides what its mark rows name.

### `function refusal`

Above `function refusal(cues, layer) {`:

Why a cue table cannot be played, naming the row, or "" when it can.

### `export function attach`

In `attach`, above `const refused = refusal(cues, L) || null;`:

A lazily fetched module cannot throw from `Ink.setSkin`: a bad row refuses the whole table,
and the marks draw on.

In `attach`, beside `const born = new Map();`:

a child of the group -> the frame it was first seen in

In `attach`, above `const mo = new MutationObserver(recs => {`:

`match` reads the body once a frame and would miss a class set and cleared between two; the
records, read after both toggles, do not. A read, never a write.

In `attach`, above `api: Object.freeze({}),`:

The helpers a skin's hooks reach as `api.fx` (#375, #376 add to it).

In `attach`, above `match() {`:

After the table is matched: what arrived and what left, since the last match.

In `attach` › `match`, above `const old = e.zeroAt && L.frames - e.zeroAt > 1;`:

Empty for more than a frame (a grouped pane, `display: none` a while) is empty. A hide
still has its box: `frame()` matches before it measures.

In `attach`, above `measure() {`:

After the marks are measured: each leave row's match keeps its last non-empty box, and an
empty measure (a pane the ResizeObserver sees just hidden, at 0x0) stamps it. Arrive rows
are never measured again.

In `attach`, above `deliver() {`:

In each frame: at most `PER_FRAME` cues to the skin, and the net.

In `attach` › `deliver`, beside `bin.add(child);`:

out of the group, and freed as the layer frees a group
