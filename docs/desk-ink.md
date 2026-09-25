# The ink layer: marks drawn on the desk by pencil, pen, marker and highlighter

_Slice B (#248) of the ink epic (#246, [plan-ink.md](plan-ink.md)). The layer is built, and the skins that draw with it
are listed in §Writing a skin. Since K (#257) every agent's **trace**, which was a 2D canvas, is data the layer draws
beside a skin's marks: see §The page's own drawing._

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
| `layer.js` | the canvas, the lanes, marks derived from the DOM, the geometry, the frame loop, and the page's own trace rows (#257) | only when the gate says on **and** a skin sets a table |
| `shapes.js` | each shape's paths, computed from a box. Pure arithmetic | with `layer.js` |
| `pen.js` | each tool's physics, the stroke meshes and their shader, the paper, the hand | with `layer.js` |
| `fx.js` | one-shot effects (#370, epic #293): one group in the scene at `api.order.fx`, the cues that play into it (#372, §Effects), and the helpers a skin reaches as `api.fx`. Imports nothing; handed three.js and the scene by the layer, it reads the page and writes nothing to it | by `layer.js`, only for a table with effects: a skin that exports `cues` or `options.fx`. Once a page, whichever tables follow |
| `skins/<name>.js` | a skin's module: its mark table and its materials (§Writing a skin). `skins/example.js` is the pattern, used by the tests | when that skin is chosen, by every shell (the fallback draws its marks too) |
| `../vendor/three/three.module.min.js` | three.js r160, vendored by #247 and pinned by sha256 | with `layer.js`, and never otherwise |

**Every import carries the token.** A module specifier is resolved against the importing file's URL, which does not
carry the run token, and every route on this server wants it. So no file in `ink/` imports statically. `ink.js`
imports `layer.js` with `import(q("/static/ink/layer.js"))`, and `layer.js` imports the other two and three.js the
same way, and `fx.js` when a table has effects. That is how `probe.js` imports three.js too. Only `ink/ink.js` is in the server's `ASSETS`, because it is
the only one a page names. `layer.js` is the one module on the desk that names three.js, and a test holds it there.

## `window.Ink`: all that `app.js` sees

`window.Ink` is frozen. `app.js` does not call it: what it hands the layer, it writes on the page, like the trace's
series (§The page's own drawing). `app.js` still never mentions WebGL, nor a 2D context (`tests/test_fleet_trace.py`).

| Member | Is |
| --- | --- |
| `Ink.ready` | a promise of the verdict. It is settled once the module has run, which is when the gate is decided |
| `Ink.enabled` | whether ink draws on this page: the gate said on and nothing has turned it off since |
| `Ink.verdict` | `{on, shell, probe, source, why}`. `source` is `probe`, `override` (`?ink=on`), `param` (`?ink=off`) or `runtime` (turned off after load) |
| `Ink.tools`, `Ink.shapes` | the names a mark table may use |
| `Ink.setSkin(table \| null, hooks?)` | a mark table, or none, and optionally a skin's material hooks. The desk's own skin sets itself (§Writing a skin), so this is for tests and the console. It replaces the skin's table until the skin changes again. Resolves to `{drawn: "ink" \| "plain" \| "none"}`. **Throws, naming the row**, on a table it cannot draw |
| `Ink.refresh()` | reads the palette again, matches the table against the page and measures every mark now |
| `Ink.off(reason)` | the plain fallback for the rest of this page's life |
| `Ink.inspect()` | what is on the paper: lanes, marks (state, how much is drawn, where, and each stroke's extent on the viewport as `bounds`), frames. The page's own traces are `layer.series`, apart from the skin's `marks` (#257). For tests and the console |
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
  hand: true,             // optional: true, false or 'chalk': the small lit hand that travels (default true)
  speed: 1,               // optional: the pen's speed, 0.25x to 4x (default 1)
  marks: [
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: 3 },
    { selector: ".tile.state-done", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".chip" },
  ],
});
```

| Field | Is |
| --- | --- |
| `selector` | any selector the page can match (checked when the table is set). Each element it matches gets one mark |
| `tool` | `pencil`, `pen`, `red`, `green`, `marker` or `highlighter`. The eraser is not a mark: it is how pencil leaves |
| `ink` | another tool whose ink the row draws in, with its own tool's hand and way of leaving: `{tool: 'pencil', ink: 'pen'}` is the pencil's grain in the pen's colour, and is erased. A tool's name, never a colour, so `theme.check`'s per-tool inks cover it; plain, it is the underline's colour too (optional, #385) |
| `shape` | one of the shapes below |
| `pad` | px the shape stands off its element (optional) |
| `dash` | a dashed stroke, for the stale pencil outline (optional; a dashed underline stays dashed plain) |
| `to` | an arrow's target: a selector, looked up in the arrow's own pane first, then the page |
| `grow` | an `underline` that lengthens: `step` px (default 10) for each element matching this selector that arrives in its pane after the mark was made, never past the pane's right edge. The pen draws on from where it stopped (#249: the running agent's line grows with its turn) |
| `step` | px an underline grows by, per arrival (optional) |
| `tip` | a pen-tip dot at the end of an `underline` while its mark is on the paper. It is lifted before the mark is struck or erased (#249) |
| `cap` | `'arrow'` (a route's head, two barbs) or `'bar'` (a block across it) at the end of an `underline`, which stays at the end while it grows. Never with `tip`. Plain, a capped underline is a plain underline (optional, #385) |
| `rewrite` | a `write` mark whose element's text changes after it was written keeps what it said beside it (to the left, in the element's own font and colour), strikes that through in pen, and writes the new text. One struck word is kept per row and element (#249: the header's count) |
| `snap` | a grid pitch in px (4 or more): the row's straight strokes are ruled onto a grid of that pitch from the viewport's top-left. An outline's edges go onto a grid line inside its box's padding band (between the border box and the content box), or down the band's middle where the band is narrower than the pitch, and its ends stop at the border box (#331); an underline goes to the first line in [its text's foot + 2, the next row's top - 2] and stays unruled when there is none (#331); a divider goes to the nearest. Only `outline`, `divider` and `underline` may snap (optional, #253) |
| `leaves` | `"erased"` or `"struck"`, over the tool's own way of leaving: the paper grammar takes up the highlight on an agent's name rather than striking the name (optional, #252, #253) |

A table may also tune a tool's hand for its own strokes with `tools: {<tool>: {...}}`, each a
number of 0 or more (`lam`, a wavelength, more than 0): `w`, `press`, `pvar`, `wob`, `lam`, `bow`, `wmin`, `tin`, `tout` (§Tools says
what each is). The graph paper's mechanical pencil is `tools: {pencil: {w: 1.05, pvar: 0.04, wob:
0, bow: 0, tin: 0, tout: 0, ...}}`. A tool's `kind`, `pad` and `model` are what it is, and stay
the layer's. A skin's module gives `tools` in its `options`. A `snap`, a `leaves` or a `tools`
entry the layer cannot honour is refused like a row it cannot draw.

A row the layer cannot draw is refused when the table is set. The exception names the row: `ink: mark 3
(.tile .repo): no tool "crayon" (pencil, pen, red, green, marker, highlighter)`. A refused table leaves the one in
force alone.

### Shapes

Shapes are computed from `getBoundingClientRect` in the element's own coordinates. A pane that moves, whether in a
gutter drag, a scroll or a reorder, moves its marks. Only a pane that changes size, or whose text wraps differently,
rebuilds them. A box under 90px wide is a pane's 48px rail, so a margin mark goes down its middle.

The margin is the pane's left padding (#330). A `check`, a `bang` or a `cross` row anchors on the pane (`.tile.state-error`,
never `.tile.state-error .head`), and `margin()` writes it 14px in from the pane's border box. Under ink, each skin that
draws gives an open pane a 26px left padding in its own sheet (`var(--ink-margin, 26px)`, keyed
`body[data-skin="<skin>"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"])`, the way the legal pad keys
its 34px; the notebook pads with its gutter), so the green check (to x+25.3) stays left of the pane number and the
name. A skin that adds a mark table adds that rule too. It is not keyed on the ink canvas: Chromium 153 left a
`.tile` rule keyed on `body:has(> #ink[data-skin])` unapplied after the layer set `data-skin` (a pane restyled
from scratch got 26px; one restyled in place kept 10px). Ink off keeps the 10px padding, and the fallback's bar is drawn inside the pane's 3px border.

**A skin's marks keep inside their pane and off other elements' words (#332).** The layer clips a pane's marks to
its border box inset 1px (#331), so a row that pads outward is cut away rather than drawn in the gutter:

* An `outline` or `loop` round the pane has a pad of 0 or less, so the stroke and half its width are on the pane:
  an idle outline -5 (the napkin, the legal pad), an error loop -7 (napkin, legal pad, notebook, farmstead), the
  stale outline round a pane -8 (napkin, notebook). A test reads every skin's table for it.
* A mark round something in the head is round that thing, never round the head: farmstead's error loop is round
  the pane, and a stale outline round `.oldsession` is on the note's own box (pad 0).
* A compact pane's head wraps the name onto a line of its own, 2px over the number and the chip. A skin that
  underlines the name gives that head room in its sheet (`row-gap: 8px`, layout, keyed
  `body[data-skin="<skin>"]:not(.ink-off) .tile[data-tier="compact"] .head`): voxel, farmstead and the legal pad.
  Glass underlines the chip, not the name, and draws no stale outline: round the note it still ran over the chip's
  age at 700px, and the note's own words say it.

`tests/test_fleet_ink_bounds.py` holds one look per module at 1400px and 700px, with a blocking question, a running
turn, an error and a stale done: no stroke more than 2px outside its pane, none outside the viewport, none cut away
whole by the pane's clip, no `outline`, `loop`, `ellipse`, `check`, `bang`, `arrow` or `divider` on another
element's words by 6 px² (a loop and an ellipse on their ring, an arrow on its curve), and no `underline` on any word
but its own. The full sweep, every variant, is #340's.

| Shape | Drawn | Plain fallback |
| --- | --- | --- |
| `outline` | four lines round the box, each overshooting its corner | `outline: 1px solid` |
| `divider` | a rule across the foot of the box | an inset bottom line |
| `underline` | a line under the text, a little past both ends: 2px under the tallest box on its text's line (the anchor's siblings whose height overlaps it, so a line past its end passes under a chip beside a name), and never lower than 2px over the next row's top: the highest of the elements after it in its pane that start below it, and of their words (#331) | `text-decoration: underline`, dashed when the row is (#385) |
| `lines` | a highlighter pass along every line the text wraps to, as wide as the line is tall | a tinted background (38% of the ink) |
| `loop` | one rounded stroke round the box, closed past its start | `outline: 2px solid` |
| `ellipse` | a loose ellipse, a little more than once round | `outline: 2px solid`, further out |
| `ring` | a tight O round a small box (a pane's number), 3px out from its longer side, about 1.1 turns, so it never reaches the name 8px beside it (#386) | a rounded 2px ring (`box-shadow: 0 0 0 2px`, `border-radius: 999px`) |
| `strike` | a line through: across a line of text, corner to corner of a tall box | `text-decoration: line-through` |
| `check` | a tick in the margin | a bar in the margin |
| `bang` | an exclamation mark in the margin | a bar in the margin |
| `cross` | an X in the margin, two 14px strokes, down the middle of a rail (#386) | a bar in the margin, beside a selected pane's focus ring |
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

**A hand is tinted by its ink.** The hand that travels a stroke is a low-poly model of its tool: the lit pencil
(turned over to its pink end for the eraser), the pen, the marker, the highlighter. Its body is coloured by the
tool's own ink at paint time, like the stroke. A table's `hand` is `true` (these), `false` (no hand) or `'chalk'`
(#387): a short worn stick of chalk in **every** hand, the pencil's, the pen's and the eraser's (flipped, as the
pencil is), coloured by the pencil's ink (`--ink-pencil`) and never by a hex, so a chalkboard's erasing never brings
the lit pencil back. Anything else is refused, naming `hand`. A new table's hand is taken up at a lane's next stroke.
`Ink.inspect().layer.handModel` is the model of the last hand shown (`'chalk'`, `'pencil'`, `'pen:pen'`,
`'eraser'`, ...), or `''` before one has been.

**A palette colours the inks, and a skin chooses the paper.** Colours are read from the page's custom properties at
paint time, on `body`, so a skin can override `--ink-pen` and a palette change repaints them. They are never carried
in the script ([desk-rendering.md](desk-rendering.md) rule 1).

## Writing a skin

A skin that draws with ink is **one module**, `agentdata/fleet/static/ink/skins/<name>.js`, beside the stylesheet
every skin already has, `static/skins/<name>/skin.css`, which holds its layout, its typography and the colours its
module reads, and nothing it paints (§What a skin's stylesheet holds). `<name>` is the skin's name in `skins.py`. That registers the skin, and so the settings page offers it
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
export const cues = [ /* rows: {selector, on: "arrive" | "leave", cue} */ ];      // or a function of the variant
export function cue({ THREE, scene, camera, tokens, api }, name, el, box, how) {}  // one cue (§Effects)
```

| Hook | Called | Its `scene` |
| --- | --- | --- |
| `ground` | when the skin arrives, on a resize, on a palette change | the ground group, drawn first (`api.order.ground`, -30), in the back pass |
| `paper` | the same | the paper group, over the ground (`api.order.paper`, -20), in the back pass. A skin with a `paper` hook replaces the flat `options.paper` |
| `frame` | for each pane (`.tile[data-repo]`) when it appears, whenever its **size** changes, and on a palette change (#388). It is not called for a move: its group is at the pane's top-left and moves with it | that pane's own group; `box` is `{x: 0, y: 0, w, h}`; `el` is the pane, to read and never write. The group is freed when the pane leaves |
| `tick` | on every frame the layer draws, with the seconds since the last. Answer `true` to be given another. Under reduced motion that answer is not honoured | none |
| `dispose` | when the skin is replaced or the layer stops | none |
| `cue` | once for each event a row of `cues` names, in the frame after it, at most four a frame; never under reduced motion (§Effects, #372) | the effects group (`api.order.fx`, -5), under every frame and mark; the skin frees what it adds, in `tick` |

What each hook is handed:

* **`THREE`** is three.js r160, the vendored copy.
* **`camera`** is the layer's orthographic camera in CSS px. x runs right, and a point `y` px down the page is drawn at
  `-y`, with z = 0.
* **`tokens`** is the palette as the page has it now. It holds `bg`, `panel`, `text`, `line`, `select`, `muted`,
  `accent`, `focus`, `running`, `waiting`, `human`, `done` and `idle`, each as `[r, g, b]` in 0–1 sRGB. It also holds
  `inks` (tool → `[r, g, b]`), `dark`, and `css(name)` for any other custom property.
* **`api`** gives `viewport` (`{w, h, dpr}`), `reduced`, `dark` and `renderer`, and `order` (`{ground: -30, paper:
  -20, frame: -10, fx: -5}`, all under every mark). `api.fx` is `fx.js`'s helpers once a table with effects has it
  attached, and null otherwise (#375 and #376 fill it). It also gives `panes()` (`[{el, repo, box}]` where the panes are now),
  `request()` (draw another frame) and `stroke()` (below). With `sampleGround`, `groundTexture` and `groundSize` let a frosted pane read
  what is behind it at `gl_FragCoord.xy / groundSize`.

**A material drawn with a tool's stroke (#388).** `api.stroke(group, path, tool, opts)` draws a skin's own piece
(goalposts, a ball, a scorch) stroke by stroke with a tool's physics and shader, the ones the marks beside it are
drawn with, rather than a flat quad of its own:

| Argument | Is |
| --- | --- |
| `group` | a group a hook was handed (a pane's `frame` group, the `paper` or the `ground` group), or one the skin added under it |
| `path` | a `shapes.js` path, `{pts, smooth?, w?, nobow?, wob?}`, in `group`'s coordinates, y down |
| `tool` | the tool whose width, grain, wobble and taper lay it down: one of `Ink.tools` |
| `opts` | `{ink?, seed?, tune?, dash?}`: `ink` the tool whose colour it is drawn in, as a row's `ink` (one of `Ink.tools`), `seed` its wobble (default 1), `tune` the tool's numbers for this stroke (as a table's `tools`), `dash` a dashed stroke |

A `tool` or an `ink` that is no tool throws a `TypeError` naming it, which the hook's call reports as the skin's error
(rule 8). The stroke starts at head 0, and `stroke()` answers a frozen handle: `len` in px, `dead`, `head(px)` (drawn
that far), `erase(px)` (taken up that far), `done(bool)`, and `dispose()`, which may be called twice. **Nothing ticks
by itself**: the skin advances `head` in `tick`, answers `true` only while something advances, and under `api.reduced`
sets `head(len)` at once. A material stroke has no hand, and is never faded: it arrives by `head` and leaves by `erase`
or with its group.

**It lives as long as its group.** A resize, a palette change or the skin leaving empties every group a hook was
handed, and every material stroke in it dies there: its handle says `dead: true` and touches nothing freed. The layer
never recolours one in place. The skin draws it again in its next `ground`, `paper` or `frame` call, in the ink the
page has then. `Ink.inspect().layer.skin.strokes` is how many are alive. A post drawn down each pane's right edge:

```js
let posts = [];                                            // what `tick` is still drawing
export function frame({ scene, api }, el, box) {           // a new pane, a new size or a new palette
  const h = api.stroke(scene, { pts: [[box.w - 30, 12], [box.w - 30, 60]], nobow: true }, "pencil", { ink: "pen" });
  posts.push({ h, at: 0 });
  api.request();                                           // a frame, so that `tick` starts drawing it
}
export function tick({ api }, dt) {
  posts = posts.filter(p => !p.h.dead && p.at < p.h.len); // drawn, or gone with its group
  for (const p of posts) p.h.head(p.at = api.reduced ? p.h.len : Math.min(p.h.len, p.at + 900 * dt));
  return posts.some(p => p.at < p.h.len);
}
```

**The rules a skin keeps.**

1. **No static `import`.** A module resolved against the file's URL does not carry the run token. three.js is handed
   in, and a skin needs nothing else.
2. **Marks come from classes the page already sets.** A skin never sets a class and never writes the page. Its hooks
   draw into the scene they are handed, and that is all they do (ground rule 2).
3. **Colours come from `tokens`, and never from a hex written in the module.** A palette change calls `ground` and
   `paper` again and rebuilds every frame. Inks come from `--ink-<tool>`, which the skin's `skin.css` may set.
4. **Every call to `ground`, `paper` or `frame` starts with an empty scene.** The layer frees the geometry and the
   materials that were in it, and a material stroke in it is dead (#388). Keep module-level references only for
   `tick`, and free anything else in `dispose`, such as a render target or a texture.
5. **Put the pieces under the marks**, with `api.order`. A mark is drawn at order 0 and above.
   What `fx: -5` really means: three.js r160 sorts first by the innermost Group's `renderOrder`, and each pane's own
   frame group (`framePanes`) keeps 0. So the effects group draws over the back pass (ground, paper) and under every
   pane's frame and every mark, whatever `api.order.frame` says. Within one list three.js draws every opaque object
   before any transparent one, so effect materials are `transparent: true`, like the skins' own. An effect that must
   sit on a pane's frame goes into that pane's frame group.
6. **Drawn, never faded** (ground rule 1). A skin animates its materials, never its marks. Under reduced motion,
   `tick` gets no loop of its own. A cue's effect ends by moving, shrinking or being covered, never by a fade
   (§Effects).
7. **The fallback is the page's.** The marks draw plain by themselves, and under `body.ink-off` every skin is the
   one plain look (§What a skin's stylesheet holds). Where the skin draws, the page stands aside for it by itself:
   `app.css` clears the panes, the header, the footer and the cards once a canvas with a table is on the page.
8. **A hook that throws is the skin's problem.** It is said once in the console and shows in
   `Ink.inspect().layer.skin.errors`, and the desk goes on drawing its marks.
9. **Test with `?ink=on`**, choosing the skin with `POST /api/theme {skin: "<name>"}` as the settings page does.
   `Ink.inspect()` shows the marks, and `.layer.skin` shows the hooks, the pieces and the frames.
   `tests/test_fleet_ink.py` has the pattern.

### The skins that draw with ink

| Skin | Module | Its page |
| --- | --- | --- |
| glass (#254) | `skins/glass.js` | [skin-glass.md](skin-glass.md): a lit mesh ground, frosted panes that sample it, and a state grammar of marks and lit rims |
| graph (#253) | `skins/graph.js` | [skin-graph.md](skin-graph.md): a 28px grid, a mechanical pencil (`tools`), ruled marks (`snap`), each agent's hour plotted |
| farmstead (#255) | `skins/farmstead.js` | [skin-farmstead.md](skin-farmstead.md): the sprite sheet as nearest-neighbour textures, lit wooden frames, and a crop that grows a stage per advance of the phase |
| legalpad (#251) | `skins/legalpad.js` | [§The legal pad](#the-legal-pad-251), below: canary stock, blue rules, a double red margin and a glued top, and an orange-pink highlighter |
| napkin (#252) | `skins/napkin.js` | [skin-napkin.md](skin-napkin.md): quilted two-ply, a felt tip that bleeds along the emboss, a coffee ring under a pane idle a long time |
| voxel (#256) | `skins/voxel.js` | [skin-voxel.md](skin-voxel.md): voxel ground, lit slabs and a status stack per pane, one draw call per material |
| notebook (`light`, `dark`, #249, #250) | `skins/notebook.js` | [skin-notebook.md](skin-notebook.md): the state grammar's reference marks, a ruled paper shader, a margin per pane |

## The legal pad (#251)

Slice E, a skin that ships with ink: "the yellow-page version" the operator asked for,
which is a yellow legal pad (plan-ink Decision 4). It is `legalpad` in `skins.py`, one variant
(`canary`, drawn against `eye-relief-day`), chosen on the settings page like any skin. Its module is
`static/ink/skins/legalpad.js` and its stylesheet `static/skins/legalpad/skin.css`.
`tests/test_fleet_ink_legalpad.py` is its test.

**The pad.** The `paper` hook draws the whole page as the pad: canary stock with a tooth (its own
small shader, the colour written as it is read), the gummed band across the top (10px, with the
ragged foot glue has where it soaked into the top sheet; the header's top border makes room for
it), and a blue rule every 28px from the first baseline under the header. The `frame` hook gives
each pane a hairline where its edge is and the double red margin, 25px and 29px in from its left
edge; a rail has no margin. The pane's own background, border and radius go, so the pad shows
through, and its text starts right of the margin (`padding-left: 34px`). The project's accent stays
on the left edge (#150).

**The rules under a transcript (#338)** are the transcript's, as on the notebook
([skin-notebook.md](skin-notebook.md) §The paper): a transcript row is 28px, the pad's pitch, with
no divider and its text 2px low, the rows end at the transcript's bottom and scroll in whole rows,
and the `frame` hook covers the transcript's box with plain canary and rules it every 28px up from
that bottom edge, so no rule runs through a line of text. The module's `inspect()` carries
`builds`, the number of `frame` calls so far.

**Its colours are custom properties on `<body>`, in `skin.css`,** read by the module through
`tokens.css(name)` at paint time and never written in the module:

| Property | Is | Value |
| --- | --- | --- |
| `--paper` | the canary stock, and `options.paper`, so the layer knows it is light and the highlighter multiplies | `#FCF3A6` |
| `--rule` | the blue rules and the panes' hairline | `#8FB1D8` |
| `--margin` | the double red margin | `#D8534C` |
| `--glue` | the gummed band | `#9C3B2E` |
| `--ink-pencil` | graphite: the palette's `--muted` is too faint on canary | `#5E5A52` |
| `--ink-pen` | a blue ballpoint, where the palette's accent is ochre | `#1F3F9A` |
| `--ink-highlighter` | **orange-pink**: the palette's amber would vanish into yellow | `#FF8FA3` |

Red, green and the marker keep the palette's own (`--human`, `--done`). Every one of the six inks
is declared beside the variant in `skins.py` (`inks`) and held to the canary by `theme.check` rule
5; a test holds `skins.py` and `skin.css` to the same numbers.

**The state grammar** (plan-ink §The state grammar) is the module's mark table. Every row reads a
class or an attribute the page already sets; the skin decides no state.

| State | Rows: selector → tool, shape | What sets it |
| --- | --- | --- |
| idle | `.tile.state-idle` → pencil outline (inside the pane); `.tile.state-idle .head .repo` → pencil underline | `drawTile`'s `state-*` |
| running | `.tile.state-running .head .repo` → pen underline; its tail and the pen-tip dot are the module's (below) | `drawTile` |
| needs you | `.tile.needs-human .head .repo` → highlighter; the open question's `.ask-q` → highlighter; each `.ask-choice` → pencil loop | `needs-human` (#94's fold), the question card (#165) |
| answered | the chosen `.ask-choice[aria-pressed="true"]` → pen ellipse. The question's highlight and the choices' loops leave: the highlight is struck in pen along its swipe (the question struck, never the name, whose highlight stays), and the loops are erased | `aria-pressed`, which the page sets when a choice is pressed; the question rows carry `:not(:has(… [aria-pressed="true"]))` |
| error | `.tile.state-error` → marker loop inside the pane, and a red bang in its margin | `drawTile` |
| done | `.tile:is(.state-done, .is-done)` → green check in the margin | `drawTile`: `is-done` is the fold's own word (#253) |
| stale (#240) | `.oldsession:not([hidden])` → pencil `write` (its own words, handwritten), a dashed pencil outline round it, and a pencil arrow to `.runline` | `drawOldSession` |
| a finding | `.transcript li.denied` or `li.friction` → red ellipse; its `.k` → highlighter; its `.v` → pencil `write` | the transcript's own line classes (`appendTo`) |
| the header count | `#bellcount` → pen `write`; a change is struck and rewritten by the module (below) | `bell()` |

Decisions the table carries, each undone by a sentence:

* **Answered is the operator's own press.** The card has no "answered" class, and once the answer
  reaches the agent the card is hidden, so a struck question would never be seen. What the page
  does have, the moment the operator chooses, is `aria-pressed` on the choice. An engine without
  `:has()` keeps the question highlighted until the card goes.
* **A finding is a transcript line the agent was refused or stopped on** (`denied`, `friction`).
  The desk has no findings markup of its own; these are the lines it already marks as a problem.
* **The stale note is the chip's own words** ("old skills", or "renew queued"), written in pencil
  where the chip is. The DOM keeps every word, so the grammar's *stale — renew?* is the page's
  sentence rather than one the skin makes up. The arrow points at the run line, which says which
  session and run the transcript is.
* **Done keys on `is-done` as well as `state-done`.** A pane the fleet does not supervise shows
  its chip as idle and a supervised one as running, so `state-done` is rare; `is-done`, which
  `drawTile` sets from the fold's own state (#253), is what a finished agent carries. A finished
  pane is idle *and* done, so it has both marks.
* **The question card and its choices are transparent in ink** (`app.css`, for every skin that
  draws): the canvas is behind the page, so a mark shows only where nothing opaque covers it.

**Two marks the layer has no shape for, drawn by the module** from the same classes, in its `tick`,
as ribbons of the pen's ink (plan-ink gives both to C; this is the skin-local copy that slice K
consolidates):

* *The running pen.* When a pane turns `state-running` and the layer has finished its underline, a
  tail runs on from the underline's end, one 6px step for each transcript line the turn writes (up
  to 132px), with the pen-tip dot at its end. It is at the underline's own height, which the layer
  places (#331: 2px under the tallest box on the name's line, never lower than 3.4px over the next
  row), so it passes under the chip, not through it, and it stops where the layer stops a line that
  grows, 14px short of the pane's right edge (#332). `inspect().panes[].tailBox` is the tail and its
  dot on the viewport. When the pane leaves `state-running` the tail is
  struck in pen, like the underline beside it. One struck tail is kept, until the next turn.
* *The header count.* When `#bellcount` changes, the old number is kept where it stood, beside the
  new one, drawn as a hand writes digits, and struck through in pen. The bell has room for it
  (`padding-left`), and one struck number is kept. The new number is the page's own text; writing
  it again with the reveal waits for the layer to re-run a `write` on a change of text.

Neither asks for a frame of its own except while its strike is being drawn, so an idle desk draws
nothing. Under reduced motion both are drawn at once. `inspect()`, exported by the module, says
what they are doing (the tests import the module by its URL, which is the instance the page runs).

**The plain look** (`body.ink-off`) is the one every skin shares since #257: the palette's page,
with the layer's fallback drawing the same table in the pad's inks. The canary, the rules, the
margin and the glue are the module's alone. Where the fallback's margin bar (an inset `box-shadow`)
lands on a selected pane, the fallback keeps the selection ring beside it, for every skin.

**Fonts.** None downloaded: the handwritten bits (the stale note, the count) use a local cursive
stack (`--hand`: Segoe Print, Bradley Hand, Chalkboard SE, Comic Neue, Comic Sans MS, `cursive`).

**Its weight.** The module is 7.0 KB gzipped and the stylesheet 1.9 KB, fetched only by a desk that
chose the skin, so neither is in the desk's static payload (desk-engines.md); `test_fleet_ink.py`
holds each skin module under 16 KB.

**One fix it needed from the page.** An idle desk with any skin but glass was never idle: every
`/api/fleet` wrote `data-theme`, `data-skin` and `data-skin-variant` again, and `startGround`'s
retry for glass's ground re-armed itself every 150ms for skins that have none. `applyTheme` and
`applySkin` now write through `attr` (a no-op when the value is right), and the retry is glass's
alone (`tests/regressions/test_20260923_any_skinned_desk_never_idle.py`).

## The page's own drawing (#257)

Two things on the desk were drawn on 2D canvases by `app.js`: every agent's **trace** (`drawTrace`) and the glass
skin's drifting **ground** (`drawGround`). K took both off them, so nothing on the page asks for a 2D context. The
ground is a skin's: where ink draws, glass's own `ground` hook (#254) is the lit mesh in the `ground` slot, and
everywhere else the stylesheet's gradients are the ground, standing still. The trace is the desk's, not a skin's, and
the layer draws it from the page.

**A series.** An element that carries its data is drawn as a mark:

```html
<svg class="trace" data-ink-series="0 0 .25 1 0.06 …" data-ink-ticks="14 18" role="img" aria-label="…">…</svg>
```

| Attribute | Is |
| --- | --- |
| `data-ink-series` | the heights, oldest first, each a fraction (0–1) of the element's box. Empty for nothing to draw |
| `data-ink-ticks` | the slots, counted from 0, that a tick goes through: here, the minutes that stopped for a person |

The layer owns two rows for it, after the skin's in each lane: `[data-ink-series]` is one line in **pen** through
every slot, and `[data-ink-ticks]` is a **red** stroke top to bottom through each tick. A slot with anything in it is
never flat, because a pixel above the floor means "it was awake". The shapes are `series` and `ticks`
(`shapes.PAGE_SHAPES`), and a skin's table cannot name them. The series is read each time the element is measured,
so new numbers are a new line, drawn whole where it stands, as a resize would be. A series is not a state, so what
goes is **erased** when its hour empties. There is nothing to strike through.

`app.js` writes the series with `attr` in `drawTrace`, beside the element's own SVG (a polyline and a path of
ticks, coloured by the stylesheet). That SVG is the plain look.

**Where it is drawn.** This canvas is behind the page, and a CSS skin's pane is opaque. So the page's rows are drawn
**only while a skin's table is in force**. That is when a skin makes its panes show the paper (§Writing a skin, rule
7). A skin that plots the hour itself says `series: false` in its `options`, and the rows are left out: the graph
paper (#253) plots it on its grid from `data-trace`, the counts `drawTrace` writes beside the series. The layer
says so on its own element, `#ink[data-skin="<table>"]`, and `app.css` lets the trace's SVG step aside
only then:

```css
body:has(> #ink[data-skin]) .trace > * { visibility: hidden; }
```

Everywhere else, including every shell the gate turned off and a CSS skin with ink on, the SVG is the trace. It
keeps its box and its words (`role="img"`, the sentence as its `aria-label`) either way. When phase 2 of K takes the
decoration out of the CSS skins, every pane shows the paper.

`Ink.inspect().layer.series` holds each trace mark, with its lane, tool, shape, state, how much is drawn, and the data
it was drawn from, apart from the skin's `marks`.

**The header's layer and the strips (#337).** Every skin that draws does two more things for the page, each in its
own sheet, keyed `body[data-skin="<skin>"]:not(.ink-off)`:

```css
body[data-skin="<skin>"]:not(.ink-off) header { will-change: transform; }
body[data-skin="<skin>"]:not(.ink-off) :is(.renew-strip, .away-strip) { background: transparent; box-shadow: none; }
```

- **The header gets its own compositor layer.** Without it, while the renew strip showed, Chromium composited the
  canvas with a band missing across the foot of the panes: the strip's rectangle mirrored, at about y 787-858 at
  1400x900. The drawing buffer read back whole. Farmstead had this fix first, for itself.
- **The renew and away strips stand aside for the canvas**, like the panes. Opaque, they sat as panels over the
  drawing. Each keeps its `border-bottom`, so it is still a strip.

These rules are in the skins' sheets, not in `app.css` on `body:has(> #ink[data-skin])`. Chromium 153 did not
re-apply a rule keyed that way to the page when it started matching late (#441, §Shapes). A skin that adds a mark
table adds both rules. `tests/test_fleet_ink_band.py` compares the foot of the panes with the canvas alone. It uses
a full-viewport screenshot, because a clipped screenshot was composited whole even while the screen showed the band.

**The one 2D context left is three.js's own.** `WebGLRenderer` asks a 1×1 `OffscreenCanvas` for one as it starts, to
learn whether it could resize a texture off the page. It never draws with it, and the vendored file is pinned by its
sha256. `tests/test_fleet_trace.py` holds the page to exactly that, at run time, and scans `static/` (minus
`vendor/`) for any other.

## What a skin's stylesheet holds (#257)

Three.js is the one platform: a skin that draws with ink draws everything it looks like in its module, and its
`skin.css` keeps what the page needs to lay its words out. `tests/test_fleet_skin_guard.py` reads every rule of the
stylesheet of every skin that ships a module and refuses the rest:

| A declaration | Allowed |
| --- | --- |
| a custom property (`--paper`, `--ink-pen`, `--glass-mesh-1`…): the colours and numbers the module reads | anywhere, **except** the palette's own eighteen tokens (`--bg`, `--panel`, `--text`…): a skin never recolours the palette, which it shares with the terminal |
| layout (`display`, `padding`, `margin`, `gap`, `width`, `flex`…) and typography (`font-*`, `line-height`, `letter-spacing`, `text-*`…) | anywhere |
| anything else: a background, a border, a shadow, a radius, a filter, an opacity, a colour | only where the skin's ink is on the page (a selector with `:not(.ink-off)`), and only to clear the page for the canvas or to name a token: `transparent`, `none`, `0` or `var(--…)`. Never a literal colour, never a `url()` |

So a skin stands aside for its canvas and never paints over it. **The plain look is the one CSS look left**: under
`body.ink-off` every skin is `app.css` and its variant's palette, with its mark table drawn as plain CSS by the
layer's fallback in the skin's own inks. `theme.check` holds every skin and palette pair both ways it can be drawn:
at the variant's composited paper (ink) and at the palette's own panel (plain), with the variant's inks
(`test_every_skin_and_palette_passes_theme_check_plain_and_in_ink`).

**What the page does for every skin that draws.** Once a canvas with a table is on the page
(`body:has(> #ink[data-skin])`), `app.css` clears the panes, the header, the footer and the cards on a pane, keeps
the pane's accent on its left and the selection ring, and lets the trace's SVG step aside when the layer draws the
trace. It is keyed on the canvas being there, not on `:not(.ink-off)`, so a clear pane always has something behind
it.

Every skin with a module is under the guard, and it reads each selector of a list on its own, so an ink-off selector cannot ride in beside an ink-on one.

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

## Effects (#372)

A skin can play a one-shot effect when something arrives on the desk or leaves it, and is handed the box the element
last had. It is one table for every skin, and like the marks it comes from the page: `fx.js` matches it with the table,
on the frame after the page changed, and nothing in `app.js` pushes a cue.

**The table.** A skin exports `cues`, an array or a function of the variant, and the hook that plays them:

```js
export const cues = [
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "example-leave" },   // a pane hidden or removed
  { selector: ".tile .transcript li.denied", on: "arrive", cue: "example-line" },     // a refusal, as it happens
];
export function cue({ THREE, scene, tokens, api }, name, el, box, how) {}
```

| Argument | Is |
| --- | --- |
| `name` | the row's `cue` |
| `el` | the element, to read and never write. For a leave it may have left the page |
| `box` | `{x, y, w, h}` in viewport CSS px: where the element is, for `arrive`; the last non-empty box it had, for `leave` |
| `how` | `"arrived"`, `"unmatched"` (still on the page, no longer matching) or `"removed"` (gone from the page) |
| `scene` (in the context) | the effects group at `api.order.fx` (-5): over the ground and the paper, under every pane's frame and every mark (§Writing a skin, rule 5). Its materials are `transparent: true`. An effect on a frame goes in that pane's frame group |

The skin frees what it adds, from `tick`, which answers `true` while an effect plays. `skins/example.js` has three
rows (the two above and `.tile.ink-cue`, a class only the tests set); its `cue` adds one quad in the palette's accent
that shrinks away over 20 frames, and its `inspect()` lists every cue it was handed.

**Checks, when the table is set.** At most 16 rows. Each selector parses, `on` is `arrive` or `leave`, `cue` is a name
(`/^[a-z][a-z0-9-]{0,23}$/`), and every `[attribute]` a selector names is one the layer observes: `class`, `id`,
`hidden`, `data-tier`, `data-skin`, `data-skin-variant`, `open`, and whatever the table's mark rows name. A cue on any
other attribute would never be matched when it changed. One bad row refuses the whole cue table, naming the row, as
`ink: cue 2 (#x): ...` in the console and in `Ink.inspect().layer.fx.refused`. The marks draw on: a module fetched
lazily cannot throw from `Ink.setSkin`.

**A cue is news, never history.** Nothing is cued:

* on a table's first match: what the page already showed is not an event (nor is anything on a reload);
* while `body.is-stale` or `body.is-replaying` (#371) is set, nor on the first match after either. `fx.js` reads the
  body once a frame, which would miss a replay said and unsaid between two frames, so it also observes `<body>`'s
  `class` with `attributeOldValue` and takes the records' word for it. That observer reads; it writes nothing;
* for an arrival inside a pane that only just arrived: a pane that arrives already matching cues nothing;
* without a skin, or under reduced motion (§Reduced motion). Nothing is queued then at all.

**The one-frame box.** The layer measures after it matches, so a hide still finds the box its pane had: `.is-hidden`
is `display: none` in the click's own task (app.css), and the ResizeObserver's next look sees the pane at 0x0. Each
time the marks are measured, `fx.js` measures its leave rows' matches again (never its arrive rows'); an empty measure
keeps the last box and stamps the frame. A box stamped more than one frame ago counts as empty. That matters for
`.tile.is-grouped`, which is `display: none` and still matches `:not(.is-hidden)`: hidden later, it has been 0x0 for
frames, so it cues nothing. Skins play nothing for `is-grouped`.

**Caps.** At most 16 cues wait (another is counted in `dropped`), at most 4 are delivered a frame, and the layer is
asked for another frame while more wait or a piece is still in the effects group. A piece older than 90 frames (1.5 s
at 60 Hz) is taken out, freed and counted in `reaped`. That is a safety net; no shipped skin relies on it.

**`Ink.inspect().layer.fx`** is `{loaded, rows, delivered, queued, dropped, armed, reaped, zero, children, refused}`:
`armed` says the next match may cue, `zero` counts leave-row matches whose box is stamped empty, and `children` counts
the effects group's pieces, none on an idle desk.

**The rule.** A cue is decoration. It never shows a state the page does not have, ends by moving, shrinking or being
covered and never by an alpha fade, draws nothing under reduced motion, and leaves an idle desk at zero frames. Its
durations are counted in frames and live in the skin module, under the canvas's ceiling
([desk-motion.md](desk-motion.md) §Effects on the canvas).

## Following the page

**The page arrives skinned and `ink-off` (#345).** The server writes the chosen skin on `<body>` (`data-skin`,
`data-skin-variant`) and, on a skinned page, `class="ink-off"`: the plain, legible look, because a skin's band text is
keyed on `:not(.ink-off)` and would be read against nothing until the canvas draws. ink.js keeps it where the gate is
off, and where the gate is on it removes it in the same task in which the layer first sets `#ink[data-skin]` (the key
app.css clears the panes on); `turnOff()` puts it back. The palette is on the first frame and the ink ground follows
when the layer draws.

The canvas is `position: fixed`, the size of the viewport, `z-index: -1` (behind the page, in front of the
stylesheet's own ground), with `pointer-events: none` and `aria-hidden`. It is the only canvas on the desk, and it is
on the page for as long as the layer runs.

| What moves | How the marks follow |
| --- | --- |
| a transcript's box inside its pane (a card shown above it) | a skin's `frame` hook is called again only when the frame's signature changes: the pane's width and height, and its `.transcript`'s top in the pane and height, each to 0.1px (#338), so a card shown or hidden above a transcript rebuilds the frame that rules it. A scroll moves no box and builds nothing |
| a gutter drag, a tier change, a pane appearing | a `ResizeObserver` on every anchor and every lane's pane. It re-measures and redraws **inside the frame the browser laid out**, so the marks are where the panes are on the frame that shows the panes. The layer adds no DOM write to the drag (plan-panes ground rule 4) |
| a window resize | the `resize` event resizes the canvas and re-measures |
| a scroll, a pane's transcript included | a capturing `scroll` listener re-measures. A mark is clipped to every scrolling ancestor, so a line scrolled out of a transcript takes its ellipse with it |
| any of these, in a pane | a mark in a pane's lane is also clipped to the pane's border box, inset 1px, where the other clips are taken: no mark is drawn past its pane, whatever its shape or `pad` says. The header's lane keeps the viewport. It is a safety net; the shapes keep their own geometry inside (#331) |
| a reorder (FLIP) or any transition | `transitionrun`/`animationstart` follows every frame for 400ms (`--motion-slow` and a margin) |
| fonts arriving | re-measures, because the text wrapped |
| the palette or the colour scheme | reads the inks again and repaints, and a skin's ground, paper and frames are made again (#388) |

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

## Loading (#349)

The modules used to arrive as a waterfall that began only once the page had run: ink.js imported the skin module, then
(with the gate on) `layer.js`, which imported three.js, `shapes.js` and `pen.js`. Going settings → desk with three
panes, `layer.js` was requested at 139 ms, three.js at 241 ms, and the first ink frame came at 344-423 ms.

The served desk now names them itself. `serve.ink_preload` adds a `<link rel="modulepreload">` to `/` (never to
/settings or /probe) when the served skin's family is in `ink_skins()`:

| Gate (`serve.ink_gate_on`, ink.js's precedence) | Preloaded |
| --- | --- |
| off: no probe, a probe that is not hardware, or `?ink=off` | `ink/skins/<name>.js`, which every shell imports, because the plain fallback draws its table too |
| on: `?ink=on`, or a hardware probe | that, and `ink/layer.js`, `ink/shapes.js`, `ink/pen.js`, `vendor/three/three.module.min.js` |

Each href is `/static/<path>?t=<token>`, the URL `q()` builds, so the module map dedupes and each module is still
fetched once. The links go ahead of the skin's stylesheet, which stays the last thing in `<head>` (#345), and the set
is in the gzip cache key. No ink module changed, so `INK_BUDGET` is untouched. Locally (Chromium 153, SwiftShader,
two panes, `voxel:nether`) every module is requested at about 16 ms, before `DOMContentLoaded`, and the first ink
frame came at 185 ms against 412 ms without the preload (`tests/test_fleet_ink_preload.py` prints it; CI has no
bound, because it renders in software).

## Budgets

| Budget | Is | Asserted by |
| --- | --- | --- |
| the static payload | 154 KB gzipped for the whole desk, the layer's four modules (43,848 bytes gzipped, LF, #388) included, against 200 KB. three.js (163 KB) is outside it: no desk fetches it unless the layer draws. So is a skin module (the example is 3 KB), which only the desk that chose it fetches | `test_fleet_serve.py`, `test_fleet_ink.py` (the modules alone under `INK_BUDGET`, 44 KiB) |
| `INK_BUDGET` | the four modules `ink.js`, `layer.js`, `shapes.js`, `pen.js`, gzip level 6 with `mtime=0`: 41,678 B at #331, 41,958 B at #385, 42,557 B at #370 (the effects seam), 42,847 B at #386 (`ring` and `cross`), 43,171 B at #387 (the chalk hand), 43,848 B at #388 (`api.stroke`, 626 B of it; 51 B are #332's underline floor). Raised once, from 40 KiB to 44 KiB, by #331 on the operator's answer in the decisions register (#318); every later card that grows the four fits under it, and one-shot effect code goes to the lazily fetched `ink/fx.js` (#370). The figure is for the modules as git stores them, LF: a checkout with `core.autocrlf=true` (Windows) is measured with its line endings normalised to LF before gzip, so CRLF bytes alone never fail it (operator decision, #331) | `test_fleet_ink.py` |
| `FX_BUDGET` | `fx.js`, lazily fetched, measured the same way, under 8 KiB (8,192 B): 1,089 B at #370, the seam alone; 3,694 B at #372 (the cues). Every later effects card (#374-#376) writes `fx.js` only, under it, and none raises `INK_BUDGET` | `test_fleet_ink.py` |
| a gesture | its 50ms, measured while every pane has a long mark drawing. The ink draws after the gesture, never inside it ([desk-instant.md](desk-instant.md)) | `test_fleet_ink.py` (`measured`) |
| ink's own catch-up | **counted in frames, not milliseconds** (ground rule 5), because CI renders in software. Marks are on the paper within the frames a hand at the pen's speed needs for their length at 60 Hz, plus travel. A slower frame moves the pen further, so it is never more. Under reduced motion it is one frame | `test_fleet_ink.py` |
| an idle desk | zero DOM mutations and zero WebGL frames with ink on the paper | `test_fleet_ink.py` |

Real-GPU frame times come from the probe on the laptop ([desk-engines.md](desk-engines.md) §WebGL), not from here.

## Reduced motion

`prefers-reduced-motion: reduce` draws every mark at once, erases and strikes at once, and shows no hand. The layer
reads it on every frame, so changing it takes effect without a reload. It plays no effect: `fx.js` queues no cue while
it holds (§Effects), so the end state is simply the page as it now is.

## `theme.check`, and ink on paper

`theme.check(t, composited_panel, skin, inks={tool: colour})` holds ink on paper to the same standard as text on a
panel. Every ink is a mark on the paper, so it needs **3:1** against it (WCAG 1.4.11, non-text contrast). The
highlighter is read *through*, so the text needs **4.5:1** on its tint (`theme.INK_TINT`, the plain fallback's 38%).
Rule 6 (#325) holds secondary text (`--muted`) to **4.5:1** on the target ground or composited panel, with a hint
naming the skin and both colours if refused.
`tests/test_fleet_skins.py` passes each variant's `inks`. No variant declares any in B, so this is the hook the paper
skins (#249–#253) fill in, with the composited-pane pairs of the three.js skins after them.

## What B does not do

These come later in the epic. The notebook's paper, its rules and margin, and the state grammar (plan-ink §The state
grammar) arrive in C. So do the running pen's dot and its underline growing with the turn, and the header count struck
and written again. The dark, legal-pad, napkin and graph-paper skins are D–G. Glass, farmstead and voxel on three.js
are H–J. Moving `drawGround` and `drawTrace` onto the layer was K's first phase (§The page's own drawing).

## Tests

`tests/test_fleet_ink.py` covers all of the following:

* **Payload:** three.js is fetched from the vendored copy with the token, once, and only when the gate is on and a
  table is set. There is one canvas.
* **Surface:** `window.Ink` is the whole surface, and a table it cannot draw is refused, naming the row (or
  `hand`).
* **The hand:** `hand: 'chalk'` is a stick of chalk while a pencil and a pen draw and while the eraser takes the
  pencil up; `hand: true` is the pencil, the pen and the eraser end as before; no hand under reduced motion.
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
* **Materials:** `api.stroke` draws a skin's material with a tool's stroke in another tool's ink, from head 0 and
  whole once the skin's `tick` has advanced it; it dies with its group on a palette change and a resize and is drawn
  again, the live strokes do not grow, replacing the skin frees its geometries, and an idle desk stays idle (#388).
* **At rest:** the desk with no skin using ink is unchanged, and so is an idle desk with ink on it.
* **Budgets:** catch-up is counted in frames, and a gesture keeps its budget while the ink draws.

`tests/test_fleet_ink_fx.py` covers the effects seam (#370): `fx.js` is never fetched for a table without `fx`,
fetched once with the token for one with it (not again when that table is set twice), leaves nothing attached after
a table without `fx`, `Ink.setSkin(null)` or `Ink.off()`, and an idle desk with it attached writes nothing and draws
nothing. The budgets and the listing of `static/ink/` (`MODULES`, `LAZY`) are in `test_fleet_ink.py`.

It also covers the cues (#372), through the real desk with the example skin chosen by the config: nothing on the first
match; a grouped pane hidden later cues nothing; a hide cues its leave row once, within 1px of the box the pane had
before the click; a removed pane cues `removed`; an arrival cues once per new match and nothing is written to the page
while it plays; a pane that arrives already matching, a forced replay and a replay said and unsaid inside one task cue
nothing; a live refusal cues exactly one; the idle loop after them all writes nothing, draws nothing and delivers
nothing; a bad row refuses its table while the marks draw on; reduced motion queues nothing; `?ink=off` fetches
nothing. **Cues stay disarmed until the stream's first pass has been drawn**, which `_open` does not wait for, so a
cue test calls `_armed(page)` after opening and after every reload: it waits on `ARMED`, `l.fx.armed` and no
`body.is-replaying`.

`tests/test_fleet_ink_bounds.py` covers where a skin's own marks land: inside their pane and off other elements'
words, on one look per module at 1400px and 700px, and every pane outline and loop padded inside it (#332).

`tests/test_fleet_trace.py` covers the page's own drawing: the trace drawn in its pane's lane from its series and
following its data, glass's ground drawn by the layer and still under reduced motion, the fallback's SVG and
gradients, and no 2D context, in the files or at run time.

`tests/test_fleet_probe.py` holds three.js to `layer.js` and `probe.js`.
