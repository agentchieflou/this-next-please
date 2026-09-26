# `ink/ink.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

```text
The ink layer's front door (#248, slice B of the ink epic #246): the gate, `window.Ink`, and the
plain fallback. `docs/desk-ink.md` is the page this file implements.

Loaded by the desk as `<script type="module">` beside the classic `app.js`, after `common.js`,
whose globals (`PARAMS`, `q`) it uses. It is small on purpose, because every desk loads it and
most never draw: it decides whether this shell gets ink, and it is the only thing `app.js` will
ever see of the layer (`window.Ink`). The drawing half -- `layer.js`, `shapes.js`, `pen.js` and
the vendored three.js -- is fetched only when the gate says on AND a skin hands it a mark table,
and always through `import(q(...))`: a module specifier resolved against this file's URL does
not carry the run token, and every route on this server wants it (the reason `probe.js` does the
same).

THE GATE. The server writes what `/probe` measured in this shell onto the page it serves:
`<body data-ink-shell="pycharm" data-ink-probe="hardware">`, from `probe.classify()` of that
shell's record in `~/.agentdata/fleet/probes.json` (`unmeasured` when there is none). This file
decides nothing about renderers. Only `hardware` -- the one class `probe.works()` accepts --
turns ink on. Everything else is the plain fallback, `body.ink-off`: software, none, unknown,
incomplete, unmeasured. So do `?ink=off`, a shell that will not give a WebGL context after all,
three.js failing to load, and a lost context.

THE OVERRIDE. `?ink=on` turns ink on whatever the probe said. It exists so CI -- which draws in
SwiftShader, and so is always `software` -- can exercise the layer. It is an override, not a
measurement: it writes nothing to `probes.json` and never reaches `/api/probe`, and `Ink.verdict`
says `source: "override"` with the probe's own answer beside it.

THE FALLBACK. The same mark table, drawn as plain CSS: an outline is an outline, a highlight a
tinted background, a strike a line-through, a check or a bang a bar in the margin. One look
shared by every skin, with no animation. It is a constructed stylesheet (`adoptedStyleSheets`),
so it costs the page no DOM writes at all: the browser matches the selectors, and a mark comes
and goes with the class `app.js` sets.
```

```text
The tools a mark table may name, and the palette colour each is drawn in unless the skin names
one of its own as `--ink-<tool>`. A palette colours the inks; a skin chooses the paper. The
eraser is not here: it is how a pencil mark leaves, not a mark.
```

### `const ERASABLE`

Above `const ERASABLE = new Set(["pencil"]);`:

Pencil is erased when its mark goes; everything else is ink, and is struck through. A row may
say otherwise with `leaves` (#252): the paper grammar highlights an agent's name while it needs
you, and a name struck through when the question is answered reads as an agent that is gone --
the flaw both prototypes had. That row's highlight is erased, and the question is struck.

### `const PLAIN`

Above `const PLAIN = {`:

Each shape as the plain fallback draws it, `%c` standing for the tool's colour. Everything the
layer can draw is a row here: `layer.js` refuses to start if the two lists disagree.

### `const MARGIN`

Above `const MARGIN = new Set(["check", "bang", "cross"]);`:

The shapes whose plain look is a bar in the pane's margin, an inset shadow (#386).

### `const SPEED`

Beside `const PLAIN_TINT = 38;`:

percent of the ink in a plain highlight

### `const SNAPS`

Beside `const SPEED = [0.25, 4];`:

the range a table's `speed` is held to

Above `const SNAPS = new Set(["outline", "divider", "underline"]);`:

The shapes a row may rule onto a grid with `snap` (#253): the straight ones. A loop, an ellipse
or a tick drawn to a ruler is not a hand-drawn loop, ellipse or tick any more.

### `const TUNABLE`

Above `const TUNABLE = ["w", "press", "pvar", "wob", "lam", "bow", "wmin", "tin", "tout"];`:

A tool's physics a table may tune (#253), each a number: the graph paper's mechanical pencil is
the prototype's pencil made thin and even, with no taper. `kind`, `pad` and `model` are the
tool's identity, not its hand, and stay the layer's.

## the gate

## the table

### `function normalise`

Above `function normalise(table) {`:

A mark table, checked once here so that a mistake in a skin is an exception at the call that
made it, naming the row -- not a mark that silently never appears.

Above `if ((row.grow !== undefined || row.tip) && row.shape !== "underline") {`:

#249: an underline that grows with what arrives in its pane, a pen-tip dot at its end, and a
written word that is struck and written again when it changes. Each belongs to one shape.

Above `if (row.leaves != null && !LEAVES.includes(row.leaves)) {`:

Graph paper (#253) and the napkin (#252) each added `leaves`; this is the one check for both.

Above `leaves: row.leaves || (ERASABLE.has(row.tool) ? "erased" : "struck"),`:

How the mark goes: pencil is erased and ink struck, unless the row says otherwise -- the
paper grammar strikes the question and never the agent's name, so the name's highlight
is taken up rather than struck through (#252, #253).

Above `if (!TUNABLE.includes(k) || !Number.isFinite(v) || v < 0 || (k === "lam" && v === 0)) {`:

`lam` is a wavelength, and divides: it is the one that cannot be 0.

Above `const hand = table.hand === undefined || table.hand;`:

The hand (#387): on, off, or a stick of chalk in every hand, the eraser's included.

Above `series: table.series !== false,`:

The page's own trace rows (#257) follow the table, unless the skin plots the hour itself.

Above `fx: table.fx || null,`:

Effects (#370): `{cues, use}`, which has the layer fetch fx.js; none, and it is never asked for.

## the fallback

### `function plainCss`

Above `function plainCss(t) {`:

The same table as plain CSS, one rule per row, only ever under `body.ink-off`.

Above `if (MARGIN.has(row.shape)) {`:

A margin bar is an inset shadow, which would take the selection ring's place on a selected
pane: the ring is kept beside it, because a selected pane is still one pane (HIG *Focus*).

### `function plain`

Above `if (!css) {`:

```text
An engine without constructed stylesheets gets a <style> element: one DOM write, not per mark.
```

## the layer

### `let loading`

Beside `let layer = null;`:

the running layer, once `layer.js` has started

### `function turnOff`

Beside `let loading = null;`:

the promise of it

In `try { layer.stop(); } catch (e) { }`:

it is going anyway

### `function materials`

Above `function materials(hooks) {`:

The material hooks a skin brings, the ones that are functions -- `sampleGround` is a flag.

### `function apply`

Above `if (body && body.classList.contains("ink-off")) body.classList.remove("ink-off");`:

The server serves a skinned page `ink-off` (#345): legible until the ink is there. It goes
in the task that puts `#ink[data-skin]` on, the key app.css clears the panes on.

## the page's skin

### `const INKED`

Above `const INKED = new Set(String((body && body.dataset.inkSkins) || "").split(/\s+/).filter( …`:

```text
A skin draws with ink by shipping `static/ink/skins/<name>.js`: a module that exports its
`marks` (the table's rows, or a function of the variant that answers them), optional `options`
(`paper`, `hand`, `speed`), and optional material hooks the layer calls -- `ground`, `paper`,
`frame`, `tick`, `dispose` (docs/desk-ink.md §Writing a skin). The server lists those names on
<body> (`data-ink-skins`), and `applySkin` in common.js writes the chosen skin as
`body[data-skin]` and `[data-skin-variant]`, which is how skins.py and the settings page choose
one today. This follows those two attributes, fetches the module through `q()` like every
module here, and sets its table. Every shell fetches it, because the plain fallback draws the
marks too; only a shell the gate turned on runs its materials. A skin with no module sets
none, and asks for none.
```

### `let skinKey`

Beside `let fromSkin = false;`:

the table in force is the page's skin's, not a caller's

### `function fromModule`

Above `function fromModule(m, family, variant) {`:

The table a skin module describes, with its hooks beside it.

### `function follow`

Beside `if (skinKey !== key) return null;`:

the skin changed again while this one loaded

Above `console.error("ink: the " + family + " skin: " + String((e && e.message) || e));`:

A skin's own mistake: said where a skin author looks, and the page carries on without ink.

### `function setSkin`

Above `function setSkin(next, hooks) {`:

A caller's table (a test, a console) replaces the skin's until the skin changes again. `hooks`
is optional: anything shaped like a skin module's material hooks.

### `window.Ink = Object.freeze({`

Above `ready: Promise.resolve(Object.assign({}, verdict)),`:

Settled as soon as the page has read its gate, which is when this module runs.

Above `setSkin: setSkin,`:

The skin's mark table, or null for none. Answers how it is being drawn: `ink`, `plain` or
`none`. Throws, naming the row, on a table it cannot draw.

Above `refresh() { if (layer) layer.refresh(); },`:

Read the palette again, match the table against the page and measure every mark now.

Above `off(reason) { turnOff(reason || "turned off by the page"); },`:

Off for the rest of this page's life, with the reason `verdict.why` will give.

Above `inspect() {`:

What is on the paper, for tests and for a curious console: lanes, marks, frames.

Above `sample(box) { return layer ? layer.sample(box) : 0; },`:

How many pixels of ink are in a box of the viewport, read back from the frame just drawn.
