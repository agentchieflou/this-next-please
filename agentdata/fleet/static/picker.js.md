# `picker.js`

The reasoning that used to be this file's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries code, and inline `/** @type {X} */ (expr)`
casts where `tsc` needs them, and nothing else. Its types are in [`picker.js.d.ts`](picker.js.d.ts).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The model picker (#362): the one component every place that sets a model or an effort adopts --
the model card, `m` on a rail, /settings and the dispatch card (#366-#368).

Provider-grouped pills that are pressed, never typed: `other…` is the one escape hatch, for a new
or BYOK name. A toolbar for the model and, in the full picker, one for the effort, each a single
tab stop that the arrows walk. Nothing is said by colour alone: pressed is a ✓ and a 2px ring as
well as `--select`, because `--accent` text on `--select` reads 2.84:1 in sand; a pill the account
cannot use carries ⊘ and a dashed edge and tells a screen reader why.

It never posts. `onPick` hands the host `{model, effort, toolbar, droppedEffort}` and the host
applies the inherit rule (#366). A draw writes only through common.js's `patchList`, `text`,
`attr`, `setClass` and `setData`, so a draw with nothing new to say changes nothing and an idle
card is an idle page (docs/desk-components.md). A classic script loaded after `common.js`: it
declares the two functions at the bottom and `mpImpl`, and no other name, because every global
here is shared with `app.js` and `settings.js`.

### `@typedef ModelEntry`

```js
/**
 * One entry of `/api/models` (`models.catalogue`).
 * @typedef {Object} ModelEntry
 * @property {string} id
 * @property {string} [label]
 * @property {string} [group]
 * @property {boolean} [offered]
 * @property {boolean} [available]
 * @property {string} [why_unavailable]
 * @property {number} [multiplier]
 * @property {string[]} [efforts]
 */
```

### `@typedef ModelPick`

```js
/**
 * What a press reports. `droppedEffort` is always "" since #493: an effort survives a model switch
 * (decision 15), and a model that lists efforts without it marks that pill ⊘ instead.
 * @typedef {Object} ModelPick
 * @property {string} model
 * @property {string} effort
 * @property {"model" | "effort"} toolbar
 * @property {string} droppedEffort
 */
```

### `@typedef ModelPickerOptions`

```js
/**
 * @typedef {Object} ModelPickerOptions
 * @property {"full" | "compact"} [variant]
 * @property {string} [label]
 * @property {string} [emptyLabel]
 * @property {string} [emptyTitle]
 * @property {(pick: ModelPick) => void} [onPick]
 * @property {(anchor: HTMLElement) => void} [onMore]
 */
```

### `@typedef ModelPickerState`

```js
/**
 * @typedef {Object} ModelPickerState
 * @property {{models?: ModelEntry[], groups?: {key: string, title: string}[], efforts?: string[],
 *             meta?: {cli_version?: string}}} catalogue
 * @property {{model: string, effort: string}} current
 * @property {{model: string, effort: string, source?: string} | null} [inherited]
 * @property {string} [actual]
 * @property {string[]} [quick]
 */
```

### `var mpImpl` › `var own`

Beside `var seq = 0;`:

ids for what the groups and pills point at

### `var mpImpl` › `function make`

Above `function make(tag, cls, words) {`:

```js
/** @return {HTMLElement} */
```

### `var mpImpl` › `function pill`

Above `function pill() {`:

The mark, the label, the note, what only a screen reader hears, and the reason a pill that
cannot be picked points `aria-describedby` at (hidden from the name, which it would repeat).

### `var mpImpl` › `function rove`

Above `function rove(bar, to) {`:

One tab stop per toolbar: the pill the keyboard is on, else the pressed one, else the first.

### `var mpImpl` › `function pickModel`

Above `function pickModel(me, id) {`:

```js
/** @return {ModelPick} */
```

Above `return { model: id, effort: me.cur.effort, toolbar: "model", droppedEffort: "" };`:

The effort stays (#493, decision 15): a model and an effort are set, and inherited, apart.

### `var mpImpl` › `function build`

Above `function build(opts) {`:

```js
/** @param {ModelPickerOptions} opts */
```

Beside `e.stopPropagation();`:

the button's own click picks, once

Beside `default: return;`:

Escape among them: it is the host's

### `var mpImpl` › `function draw`

Above `function draw(root, state) {`:

```js
/**
 * @param {HTMLElement} root
 * @param {ModelPickerState} state
 */
```

Above `var byId = me.byId = new Map();`:

Every id once, `""` (inherit) always there, and a current id the catalogue lacks shown in
the last group rather than lost.

Above `var inhEffort = inh ? String(inh.effort || "") : "";`:

The effort, a half of its own (#493, decision 15): "" is no effort of this host's own -- the
inherited one when there is one, named on the pill -- then the catalogue's levels. Settable
whatever the model, "CLI chooses" included. A model that lists its own levels and not one
of these marks that pill ⊘ and says so, rather than dropping the effort.

### `function createModelPicker`

Above `function createModelPicker(opts) {`:

```js
/**
 * One picker, built once and bound once.
 * @param {ModelPickerOptions} opts
 * @return {HTMLElement}
 */
```

### `function drawModelPicker`

Above `function drawModelPicker(el, state) {`:

```js
/**
 * Draw `state` into a picker. An equal state makes no mutation.
 * @param {HTMLElement} el
 * @param {ModelPickerState} state
 */
```
