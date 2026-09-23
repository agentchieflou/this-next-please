# The ink layer: marks drawn on the desk by pencil, pen, marker and highlighter

_Slice B (#248) of the ink epic (#246, [plan-ink.md](plan-ink.md)). The layer is built, and **nothing on the desk
uses it yet**: no shipped skin hands it a mark table, so the desk looks exactly as it did. The notebook (#249) is the
first skin that will._

The operator chose three.js as the desk's one renderer (plan-ink Decision 1), and the theme's rule is that a mark is
**drawn on the fly** by a writing tool. It never fades. A pencil mark that goes is erased, and an ink mark that goes
is struck through. This page is how that is built: one canvas behind the page, a queue of drawing per agent, and marks
that come from the classes `app.js` already sets. The layer never decides a state.

**The DOM keeps the words and the controls.** Every label, transcript line, button and reply box is still page text,
under the render contract ([desk-components.md](desk-components.md)). The ink layer draws what is decoration. In B that
means the marks. Paper, frames and the ground arrive with the skins.

## The files

Everything is in `agentdata/fleet/static/ink/`. There is no build step and nothing comes from a CDN.

| File | What it is | Fetched |
| --- | --- | --- |
| `ink.js` | the front door: the gate, `window.Ink`, the table's validation, the plain fallback | by every desk, as `<script type="module">` beside `app.js` |
| `layer.js` | the canvas, the lanes, marks derived from the DOM, the geometry, the frame loop | only when the gate says on **and** a skin sets a table |
| `shapes.js` | each shape's paths, computed from a box. Pure arithmetic | with `layer.js` |
| `pen.js` | each tool's physics, the stroke meshes and their shader, the paper, the hand | with `layer.js` |
| `skins/<name>.js` | a skin's module: its mark table and its materials (§Writing a skin). `skins/example.js` is the pattern, used by the tests | when that skin is chosen, by every shell (the fallback draws its marks too) |
| `../vendor/three/three.module.min.js` | three.js r160, vendored by #247 and pinned by sha256 | with `layer.js`, and never otherwise |

**Every import carries the token.** A module specifier is resolved against the importing file's URL, which does not
carry the run token, and every route on this server wants it. So no file in `ink/` imports statically. `ink.js`
imports `layer.js` with `import(q("/static/ink/layer.js"))`, and `layer.js` imports the other two and three.js the
same way. That is how `probe.js` imports three.js too. Only `ink/ink.js` is in the server's `ASSETS`, because it is
the only one a page names. `layer.js` is the one module on the desk that names three.js, and a test holds it there.

## `window.Ink`: all that `app.js` sees

`window.Ink` is frozen. `app.js` does not call it yet, because no skin uses ink, and `app.js` still never mentions
WebGL (`tests/test_fleet_trace.py`).

| Member | Is |
| --- | --- |
| `Ink.ready` | a promise of the verdict. It is settled once the module has run, which is when the gate is decided |
| `Ink.enabled` | whether ink draws on this page: the gate said on and nothing has turned it off since |
| `Ink.verdict` | `{on, shell, probe, source, why}`. `source` is `probe`, `override` (`?ink=on`), `param` (`?ink=off`) or `runtime` (turned off after load) |
| `Ink.tools`, `Ink.shapes` | the names a mark table may use |
| `Ink.setSkin(table \| null, hooks?)` | a mark table, or none, and optionally a skin's material hooks. The desk's own skin sets itself (§Writing a skin), so this is for tests and the console. It replaces the skin's table until the skin changes again. Resolves to `{drawn: "ink" \| "plain" \| "none"}`. **Throws, naming the row**, on a table it cannot draw |
| `Ink.refresh()` | reads the palette again, matches the table against the page and measures every mark now |
| `Ink.off(reason)` | the plain fallback for the rest of this page's life |
| `Ink.inspect()` | what is on the paper: lanes, marks (state, how much is drawn, where), frames. For tests and the console |
| `Ink.sample(box)` | how many pixels of a viewport box hold ink, read back from a frame drawn for the purpose. For tests |

## The gate: hardware WebGL, measured, and nothing else

A shell gets ink only if its `/probe` record says `hardware`. That is `probe.works()`, the rule
[desk-engines.md](desk-engines.md) §WebGL states. Every other answer gets the plain fallback: software, no WebGL, an
unnamed renderer, a probe that did not finish, or no probe at all.

**The server writes what the probe measured onto the page, and decides nothing.** When `/` is served,
`serve.ink_facts` names the window's shell the way `probe.js` filed it: `shell=`, else `w=`, else `browser`. It looks
up that shell's record in `~/.agentdata/fleet/probes.json` and writes two words on `<body>`:

```html
<body data-ink-shell="pycharm" data-ink-probe="hardware">
```

A third attribute, `data-ink-skins`, lists the skins that ship a module (§Writing a skin). `data-ink-probe` is
`probe.classify()` of the record, or `unmeasured` when there is none (`probe.ink_gate`). A name
that is not a shell name is a shell nobody has measured. The words are on the page before any script runs, so the gate
is decided the moment `ink.js` does. There is no second request, and nothing is drawn first and taken back. The
compressed page is cached per shell and class.

| The page is opened… | Probe says | `Ink.enabled` | `body.ink-off` |
| --- | --- | --- | --- |
| in a shell measured as hardware | `hardware` | yes | no |
| in a shell measured as software (SwiftShader, llvmpipe, Basic Render…) | `software` | no | yes |
| with no WebGL | `none` | no | yes |
| where the renderer would not name itself | `unknown` | no | yes |
| where the probe did not finish | `incomplete` | no | yes |
| where nothing has measured yet | `unmeasured` | no | yes |
| with `?ink=off` | anything | no | yes |
| with `?ink=on` | anything | yes, `source: "override"` | no |

The gate can also fail after load. The layer asks for a WebGL context (WebGL2, then WebGL1) **before** it fetches
three.js, the way the probe does. A shell that will not give one falls back, and three.js is never fetched. If
three.js will not load, or the GPU takes the context back (`webglcontextlost`), the layer turns off for the rest of
the page's life. The canvas goes, `body.ink-off` comes, and the table in force is drawn plain at once. A restored
context is not taken back up: the gate is decided per page.

A shell is measured under its own name: `ad-fleet probe --open pycharm`, `vscode`, `edge` or `browser`. A window
opened under another name, such as `ad-fleet open --in edge --window left`, is looked up under that name. Add `shell=edge`
to its address to read Edge's record.

### The test override: `?ink=on`

CI draws in SwiftShader, which the probe classifies as `software`, so without an override the layer could never be
tested there. `?ink=on` turns ink on whatever the probe said. **It is an override, not a measurement**:

* it writes nothing to `probes.json` and never reaches `/api/probe`;
* `Ink.verdict.source` says `override`, and `why` gives the probe's own answer beside it: *forced on by ?ink=on: a
  test override, not a measurement (the probe says software for chromium)*;
* `ad-fleet engines` and the WebGL row of [desk-engines.md](desk-engines.md) are untouched by it.

`?ink=off` is the other way round: the fallback, whatever the probe said. Both pass through `/open`, like every other
parameter.

## A skin is a mark table

A mark table says: **when this selector matches, this tool draws this shape around it.** The layer watches the page
and draws the table's marks. So a tile's truth stays in the classes `app.js` sets, and no skin can show a state the
page does not have.

```js
Ink.setSkin({
  name: "notebook",
  paper: "--bg",          // optional: a colour, or a custom property, drawn behind the marks
  hand: true,             // optional: the small lit pencil that travels (default true)
  speed: 1,               // optional: the pen's speed, 0.25x to 4x (default 1)
  marks: [
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: 3 },
    { selector: ".tile.state-done .head", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".chip" },
  ],
});
```

| Field | Is |
| --- | --- |
| `selector` | any selector the page can match (checked when the table is set). Each element it matches gets one mark |
| `tool` | `pencil`, `pen`, `red`, `green`, `marker` or `highlighter`. The eraser is not a mark: it is how pencil leaves |
| `shape` | one of the shapes below |
| `pad` | px the shape stands off its element (optional) |
| `dash` | a dashed stroke, for the stale pencil outline (optional) |
| `to` | an arrow's target: a selector, looked up in the arrow's own pane first, then the page |

A row the layer cannot draw is refused when the table is set. The exception names the row: `ink: mark 3
(.tile .repo): no tool "crayon" (pencil, pen, red, green, marker, highlighter)`. A refused table leaves the one in
force alone.

### Shapes

Shapes are computed from `getBoundingClientRect` in the element's own coordinates. A pane that moves, whether in a
gutter drag, a scroll or a reorder, moves its marks. Only a pane that changes size, or whose text wraps differently,
rebuilds them. A box under 90px wide is a pane's 48px rail, so a margin mark goes down its middle.

| Shape | Drawn | Plain fallback |
| --- | --- | --- |
| `outline` | four lines round the box, each overshooting its corner | `outline: 1px solid` |
| `divider` | a rule across the foot of the box | an inset bottom line |
| `underline` | a line under the text, a little past both ends | `text-decoration: underline` |
| `lines` | a highlighter pass along every line the text wraps to, as wide as the line is tall | a tinted background (38% of the ink) |
| `loop` | one rounded stroke round the box, closed past its start | `outline: 2px solid` |
| `ellipse` | a loose ellipse, a little more than once round | `outline: 2px solid`, further out |
| `strike` | a line through: across a line of text, corner to corner of a tall box | `text-decoration: line-through` |
| `check` | a tick in the margin | a bar in the margin |
| `bang` | an exclamation mark in the margin | a bar in the margin |
| `arrow` | a curve from the box to its `to` target, with a head | a dotted underline |
| `write` | the handwriting reveal: the element's **own text** uncovered left to right as the pen moves along it | the text, as it is |

### Tools

Tools are the prototype's (`notebook-three.html`, the page the operator chose). Each has a width, a pressure and how
much it varies, a wobble and its wavelength, a bow on long strokes, and a taper at each end. Each also has its own
shader.

| Tool | Width | Shader | Ink, unless the skin sets `--ink-<tool>` | Leaves by |
| --- | --- | --- | --- | --- |
| `pencil` | 1.9 | graphite: takes the paper's tooth, and pressure fills it in | `--muted` | being erased |
| `pen` | 1.45 | ballpoint: steady, skips under light pressure, blobs now and then | `--accent` | a strike |
| `red` | 1.8 | ballpoint | `--human` | a strike |
| `green` | 2.6 | ballpoint | `--done` | a strike |
| `marker` | 4.6 | felt: bleeds outward the longer it has been down, and pools where the nib stopped | `--human` | a strike |
| `highlighter` | 18 | ragged ends and streaks, **multiplied** into a light paper and **screened** onto a dark one (a translucent swipe where the skin has no paper) | `--waiting` | a strike along each swipe |
| `eraser` | 14 | a faint scuff where it passed | the pencil's | — |

**A palette colours the inks, and a skin chooses the paper.** Colours are read from the page's custom properties at
paint time, on `body`, so a skin can override `--ink-pen` and a palette change repaints them. They are never carried
in the script ([desk-rendering.md](desk-rendering.md) rule 1).

## Writing a skin

A skin that draws with ink is **one module**, `agentdata/fleet/static/ink/skins/<name>.js`, beside the stylesheet
every skin already has, `static/skins/<name>/skin.css`, which holds its layout, its typography and its look under
`body.ink-off`. `<name>` is the skin's name in `skins.py`. That registers the skin, and so the settings page offers it
and `theme.skin` in the config chooses it, the way `glass` is chosen today. `static/ink/skins/example.js` is the
working pattern to copy, and the tests draw with it. It is not in `skins.py`, so nobody can choose it.

**How it is chosen.** The server lists every `static/ink/skins/*.js` on the desk's `<body>` (`data-ink-skins`). The
chosen skin reaches the page as `applySkin("<name>:<variant>")`, which writes `body[data-skin]` and
`[data-skin-variant]`. `ink.js` follows those two attributes. When they name a listed skin, it fetches the module
with `import(q(...))` and sets its table. Every shell fetches the module, because the plain fallback draws the marks
too. Only a shell the gate turned on runs its materials. Choosing another skin, or none, takes the marks and the
materials off the paper, and the canvas with them.

**The module exports** (every export optional except `marks`):

```js
export function marks(variant) { return [ /* rows: {selector, tool, shape, pad?, dash?, to?} */ ]; }  // or: export const marks = [...]
export const options = { paper: "--bg", hand: true, speed: 1 };                                        // or a function of the variant
export const sampleGround = false;           // true: frames get the ground and paper as a texture

export function ground({ THREE, scene, camera, tokens, api }) {}    // the whole page's background
export function paper({ THREE, scene, camera, tokens, api }) {}     // the stock behind the panes
export function frame({ THREE, scene, camera, tokens, api }, el, box) {}   // one pane's frame
export function tick({ THREE, camera, tokens, api }, dt, now) {}   // per frame; answer true for another
export function dispose({ THREE, camera, tokens, api }) {}          // the skin is going
```

| Hook | Called | Its `scene` |
| --- | --- | --- |
| `ground` | when the skin arrives, on a resize, on a palette change | the ground group, drawn first (`api.order.ground`, -30), in the back pass |
| `paper` | the same | the paper group, over the ground (`api.order.paper`, -20), in the back pass. A skin with a `paper` hook replaces the flat `options.paper` |
| `frame` | for each pane (`.tile[data-repo]`) when it appears and whenever its **size** changes. It is not called for a move: its group is at the pane's top-left and moves with it | that pane's own group; `box` is `{x: 0, y: 0, w, h}`; `el` is the pane, to read and never write. The group is freed when the pane leaves |
| `tick` | on every frame the layer draws, with the seconds since the last. Answer `true` to be given another. Under reduced motion that answer is not honoured | none |
| `dispose` | when the skin is replaced or the layer stops | none |

What each hook is handed:

* **`THREE`** is three.js r160, the vendored copy.
* **`camera`** is the layer's orthographic camera in CSS px. x runs right, and a point `y` px down the page is drawn at
  `-y`, with z = 0.
* **`tokens`** is the palette as the page has it now. It holds `bg`, `panel`, `text`, `line`, `select`, `muted`,
  `accent`, `focus`, `running`, `waiting`, `human`, `done` and `idle`, each as `[r, g, b]` in 0–1 sRGB. It also holds
  `inks` (tool → `[r, g, b]`), `dark`, and `css(name)` for any other custom property.
* **`api`** gives `viewport` (`{w, h, dpr}`), `reduced`, `dark` and `renderer`, and `order` (`{ground: -30, paper:
  -20, frame: -10}`, all under every mark). It also gives `panes()` (`[{el, repo, box}]` where the panes are now) and
  `request()` (draw another frame). With `sampleGround`, `groundTexture` and `groundSize` let a frosted pane read
  what is behind it at `gl_FragCoord.xy / groundSize`.

**The rules a skin keeps.**

1. **No static `import`.** A module resolved against the file's URL does not carry the run token. three.js is handed
   in, and a skin needs nothing else.
2. **Marks come from classes the page already sets.** A skin never sets a class and never writes the page. Its hooks
   draw into the scene they are handed, and that is all they do (ground rule 2).
3. **Colours come from `tokens`, and never from a hex written in the module.** A palette change calls `ground` and
   `paper` again and rebuilds every frame. Inks come from `--ink-<tool>`, which the skin's `skin.css` may set.
4. **Every call to `ground`, `paper` or `frame` starts with an empty scene.** The layer frees the geometry and the
   materials that were in it. Keep module-level references only for `tick`, and free anything else in `dispose`, such
   as a render target or a texture.
5. **Put the pieces under the marks**, with `api.order`. A mark is drawn at order 0 and above.
6. **Drawn, never faded** (ground rule 1). A skin animates its materials, never its marks. Under reduced motion,
   `tick` gets no loop of its own.
7. **The fallback is CSS.** The marks draw plain by themselves. What a skin's paper or ground looks like with
   `body.ink-off` is its `skin.css`'s business. So is making the panes transparent (`body[data-skin="<name>"]:not(.ink-off)
   .tile { background: transparent }`) where the paper should show through.
8. **A hook that throws is the skin's problem.** It is said once in the console and shows in
   `Ink.inspect().layer.skin.errors`, and the desk goes on drawing its marks.
9. **Test with `?ink=on`**, choosing the skin with `POST /api/theme {skin: "<name>"}` as the settings page does.
   `Ink.inspect()` shows the marks, and `.layer.skin` shows the hooks, the pieces and the frames.
   `tests/test_fleet_ink.py` has the pattern.

### The skins that draw with ink

| Skin | Module | Its page |
| --- | --- | --- |
| glass (#254) | `skins/glass.js` | [skin-glass.md](skin-glass.md): a lit mesh ground, frosted panes that sample it, and a state grammar of marks and lit rims |

## Lanes

There is one queue of drawing per agent's pane (`.tile[data-repo]`), and one for everything outside a pane: the header
lane. Every lane advances on every frame, so **two agents draw at once**. Within a lane, a mark is finished before the
next is begun, so **one agent's marks never interleave**. Rows are queued in table order. Each lane has its own hand,
which travels to the next stroke, draws it, and lifts off when the lane is empty.

## Marks come from the page, never pushed

The layer is **derived from the DOM**, which is ground rule 2. A `MutationObserver` on the page's classes (and on
whatever attributes the table's selectors name) only notes *something changed*. The work happens on the next
animation frame, so a gesture's own frame is not charged for the ink. That frame matches every row against the page:

* **A new match** is a mark, queued in its pane's lane and drawn a stroke at a time at 900 px/s, faster in the middle of
  a stroke than at its ends.
* **A match that has gone** leaves. A pencil mark is erased: the eraser runs back along each stroke. An ink mark is
  struck through with one pen line, and the struck mark stays. That is ground rule 1: drawn, never faded.
* **A match that comes back before its eraser started** simply stays. A mark that goes before its pen started is never
  drawn.
* **One struck mark is kept per row and element.** The history stays visible, and a state that comes and goes all day
  does not stack a hundred strikes on one name.
* **An element that leaves the page takes its marks with it**, struck or not. There is no paper left to draw them on.
* **A mark whose pane is hidden or a rail** is finished at once, and no hand travels to where it is not.

The handwriting reveal is **the one write the layer makes to the page**. It sets the `clip-path` of the element being
written, and only while it is written. The element is covered from the moment it matches until its turn in the lane,
then uncovered, then left with no style at all. An erased pencil note is covered again. A table that is taken away, or
a layer that stops, takes back every clip it wrote.

## Following the page

The canvas is `position: fixed`, the size of the viewport, `z-index: -1` (behind the page, and after `#ground`, so in
front of it), with `pointer-events: none` and `aria-hidden`. It is the only canvas the layer makes.

| What moves | How the marks follow |
| --- | --- |
| a gutter drag, a tier change, a pane appearing | a `ResizeObserver` on every anchor and every lane's pane. It re-measures and redraws **inside the frame the browser laid out**, so the marks are where the panes are on the frame that shows the panes. The layer adds no DOM write to the drag (plan-panes ground rule 4) |
| a window resize | the `resize` event resizes the canvas and re-measures |
| a scroll, a pane's transcript included | a capturing `scroll` listener re-measures. A mark is clipped to every scrolling ancestor, so a line scrolled out of a transcript takes its ellipse with it |
| a reorder (FLIP) or any transition | `transitionrun`/`animationstart` follows every frame for 400ms (`--motion-slow` and a margin) |
| fonts arriving | re-measures, because the text wrapped |
| the palette or the colour scheme | reads the inks again and repaints |

**A frame with nothing new draws nothing.** An idle desk with ink on it is still zero DOM mutations and zero WebGL
frames.

## The plain fallback

This is plan-ink Decision 3: no WebGL gets the same page with plain borders and highlights, and no animation. With the
layer off, the **same mark table** becomes a constructed stylesheet (`document.adoptedStyleSheets`). There is one rule
per row, and only under `body.ink-off`:

```css
body.ink-off :is(.tile.needs-human .repo) { background-color: color-mix(in srgb, var(--ink-highlighter, var(--waiting)) 38%, transparent); }
```

The browser matches the selectors itself. A mark comes and goes with the class `app.js` sets, and the fallback writes
nothing to the page to do it. It is one look shared by every skin, a degraded mode of the one platform rather than a
second one (see the shapes table). An engine without constructed stylesheets gets one `<style data-ink="plain">` in the
head instead.

## Budgets

| Budget | Is | Asserted by |
| --- | --- | --- |
| the static payload | 141 KB gzipped for the whole desk, the layer's four modules (29 KB) included, against 200 KB. three.js (163 KB) is outside it: no desk fetches it unless the layer draws | `test_fleet_serve.py`, `test_fleet_ink.py` (the modules alone under 40 KB) |
| a gesture | its 50ms, measured while every pane has a long mark drawing. The ink draws after the gesture, never inside it ([desk-instant.md](desk-instant.md)) | `test_fleet_ink.py` (`measured`) |
| ink's own catch-up | **counted in frames, not milliseconds** (ground rule 5), because CI renders in software. Marks are on the paper within the frames a hand at the pen's speed needs for their length at 60 Hz, plus travel. A slower frame moves the pen further, so it is never more. Under reduced motion it is one frame | `test_fleet_ink.py` |
| an idle desk | zero DOM mutations and zero WebGL frames with ink on the paper | `test_fleet_ink.py` |

Real-GPU frame times come from the probe on the laptop ([desk-engines.md](desk-engines.md) §WebGL), not from here.

## Reduced motion

`prefers-reduced-motion: reduce` draws every mark at once, erases and strikes at once, and shows no hand. The layer
reads it on every frame, so changing it takes effect without a reload.

## `theme.check`, and ink on paper

`theme.check(t, composited_panel, skin, inks={tool: colour})` holds ink on paper to the same standard as text on a
panel. Every ink is a mark on the paper, so it needs **3:1** against it (WCAG 1.4.11, non-text contrast). The
highlighter is read *through*, so the text needs **4.5:1** on its tint (`theme.INK_TINT`, the plain fallback's 38%).
`tests/test_fleet_skins.py` passes each variant's `inks`. No variant declares any in B, so this is the hook the paper
skins (#249–#253) fill in, with the composited-pane pairs of the three.js skins after them.

## What B does not do

These come later in the epic. The notebook's paper, its rules and margin, and the state grammar (plan-ink §The state
grammar) arrive in C. So do the running pen's dot and its underline growing with the turn, and the header count struck
and written again. The dark, legal-pad, napkin and graph-paper skins are D–G. Glass, farmstead and voxel on three.js
are H–J. Moving `drawGround` and `drawTrace` onto the layer is K.

## Tests

`tests/test_fleet_ink.py` covers all of the following:

* **Payload:** three.js is fetched from the vendored copy with the token, once, and only when the gate is on and a
  table is set. There is one canvas.
* **Surface:** `window.Ink` is the whole surface, and a table it cannot draw is refused, naming the row.
* **Marks:** a mark is drawn when its class appears, and erased or struck when it goes.
* **Lanes:** two panes draw at once, and one pane's marks never interleave.
* **Following:** marks follow a gutter drag in the frame that moves the panes, with no DOM write from the layer, and
  they follow a window resize.
* **Motion:** reduced motion draws at once.
* **The gate:** hardware turns ink on, and every other class, `?ink=off`, a lost context and a missing context turn it
  off.
* **Fallback:** it draws the same table as CSS, with no DOM writes.
* **Skins:** a skin module is fetched with the token when the config chooses it. Its marks are drawn per variant,
  in ink or plain, and its ground, paper and frames run. A hook that throws is the skin's own problem, and
  `sampleGround` hands frames the ground as a texture.
* **At rest:** the desk with no skin using ink is unchanged, and so is an idle desk with ink on it.
* **Budgets:** catch-up is counted in frames, and a gesture keeps its budget while the ink draws.

`tests/test_fleet_probe.py` holds three.js to `layer.js` and `probe.js`.
