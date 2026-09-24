# What each engine does, and what happens where it does not

The desk has to load inside PyCharm's JCEF tool window and VS Code's Simple Browser as well as in
a real browser, behind a corporate proxy where nothing fetched from the internet arrives. Those two
shells are behind Chromium by a version or several, and neither of them is in this repository's CI.

So every platform feature the ownership epic leaned on answers two questions: **does this engine
have it**, and **what happens on the one that does not**. The second is the one that gets skipped,
so it is the one `tests/test_fleet_engines.py` asserts — by stubbing the feature away and checking
the page arrives at the same place.

A blank cell would be a claim nobody made and a reader would take as "fine". *Not yet measured* is
a smaller promise and a true one; a test refuses any cell that is neither.

## The rows

| Feature | Chromium 141 | Edge (current) | JCEF (PyCharm 2026.1) | Simple Browser (VS Code) |
| --- | --- | --- | --- | --- |
| `@starting-style` | works | not yet measured | not yet measured | not yet measured |
| `transition-behavior: allow-discrete` | works | not yet measured | not yet measured | not yet measured |
| `startViewTransition` | works | not yet measured | not yet measured | not yet measured |
| `linear() easing` | works | not yet measured | not yet measured | not yet measured |
| `pointer capture` | works | not yet measured | not yet measured | not yet measured |
| `ResizeObserver` | works | not yet measured | not yet measured | not yet measured |
| `container queries` | works | not yet measured | not yet measured | not yet measured |
| `OffscreenCanvas` | works | not yet measured | not yet measured | not yet measured |
| `HTML-in-canvas` | falls back — effects follow element rects and line boxes | not yet measured | not yet measured | not yet measured |
| `WebGL` | falls back — software (SwiftShader) | not yet measured | not yet measured | not yet measured |

The Chromium column is **measured, not remembered**: `test_the_chromium_column_is_what_chromium_
actually_does` probes each feature in the browser CI runs against and fails if this table and the
engine disagree. The userAgent it measured is
`HeadlessChrome/141.0.0.0`.

The WebGL row is the exception, and the reason is below: a context is not a verdict, so its cells
come from `/probe` rather than from `getContext`. CI's Chromium draws WebGL2 on SwiftShader, which
is software, so its cell says *falls back* — `test_the_webgl_row_is_what_the_probe_measured` holds
it there.

Every other row is measured the same way as well (#235): `/probe` asks it in the shell it runs in,
the desk keeps the answer, and `probe.feature_cell` turns it into this table's words.
`test_the_feature_rows_are_what_the_probe_recorded_in_this_engine` holds CI's own probe to this
column. The panes (#233–#234) added the `ResizeObserver` row and lean on two others. The tiers hang
on the one observer, the head of a pane sheds words by container query, and the gutter takes
pointer capture on the press. What each costs without it is below.
`test_the_gutter_keeps_the_pointer_when_the_hand_leaves_its_strip` measures the capture itself in
CI: every move is the gutter's while the hand is off its 8px strip, off the row and over the toolbar.

The other three columns are filled in on the laptop, from `ad-fleet engines` (its `engines` table
for WebGL, its `features` table for every other row), by §Ink and §Panes of the runbook in
[windows-verification.md](windows-verification.md). Until then they say what they are.

## WebGL, probed in each shell (#247)

The operator chose three.js as the desk's one renderer (epic #246). Whether a shell *has* WebGL
is the wrong question for that: SwiftShader has it, and draws a page of strokes correctly at
software speed. So WebGL is measured by drawing. `/probe` on the desk opens a context
(WebGL2, else WebGL1), loads the vendored three.js r160, draws a fixed scene of 480 pencil and ink
segments for three seconds, and posts what it saw to `POST /api/probe`. The desk keeps one record
per shell in `~/.agentdata/fleet/probes.json`. Nothing is copied out of a dev console:

```bash
ad-fleet probe --open pycharm     # the desk in PyCharm's tool window goes to the probe itself, and comes back
ad-fleet probe --open vscode      # the same for the Fleet view; Simple Browser takes the URL on the clipboard
ad-fleet probe --open edge
ad-fleet engines                  # this row, one line per column, read from the file -- and the
                                  # other rows (`features`) and the tier widths (`tiers`), #235
```

Each `--open` waits for the shell's own answer and prints it, from a desk running the installed code
(#242, as `ad-fleet open`). PyCharm's JCEF window and VS Code's view cannot be pointed at a URL from
outside, so the CLI asks the server (`POST /api/measure {w}`) and the desk already inside the IDE,
which sees the ask in its desk frame, takes it and goes to `/probe`. If the window is not open yet,
it goes when it is opened within ten minutes. The ask is held in the server's memory, never in
desk.json. A window takes it once, so two desks under one name never both go. The desk also waits
while a reply box or brief holds unsent text. The probe itself waits until its window is on screen.
`ad-fleet probe` with no flag lists every record.

**What a record holds** — facts only; the verdict is computed when it is read, so a pattern added
to the rule reclassifies every record already on disk:

| Field | What it is |
| --- | --- |
| `shell`, `at` | the `shell=` or `w=` the page was opened with, and when the desk received it (UTC) |
| `ua` | `navigator.userAgent` |
| `webgl` | `webgl2`, `webgl1` or `none` |
| `renderer`, `vendor` | the **unmasked** strings (`WEBGL_debug_renderer_info`), or empty when the browser will not unmask them: the masked one is `WebKit WebGL` or `Mozilla` everywhere and names no machine |
| `caveat` | the browser refused a context asked for with `failIfMajorPerformanceCaveat` |
| `three` | three.js's `REVISION` as loaded: `160` |
| `frames`, `p50_ms`, `p95_ms` | frame intervals from `requestAnimationFrame` over three seconds, nearest-rank. The first frame and the gap after it are left out, because both hold the shader compile and the readback |
| `first_stroke_ms`, `load_ms` | from the page's navigation start to the first frame whose pixels hold the scene (a band across the first line is read back, so the GPU has finished it), and to three.js imported |
| `drawn`, `hidden`, `error` | whether that first frame held any stroke at all; whether the window was hidden before it finished; what went wrong, in the browser's words |
| `features` | one yes or no for each other row of §The rows, asked before the scene is drawn (#235). Container queries are asked to *apply*: a rule inside `@container` has to reach an element, not only parse. A row not answered reads *not yet measured*, and the answers are read from a shell's newest post, finished or not, because a scene hidden halfway says nothing against them |

**The rule** — one function, `agentdata/fleet/probe.py` `classify()`, shared by the server's
answer to the page, both CLI verbs and the tests:

| Class | When | The WebGL cell |
| --- | --- | --- |
| `hardware` | a context that drew, with a named renderer that is not software | works |
| `software` | the unmasked renderer contains `SwiftShader`, `llvmpipe`, `lavapipe`, `softpipe`, `Microsoft Basic Render`, `Apple Software Renderer`, `Mesa OffScreen` or `software rasterizer` (case-insensitive), **or** `caveat` is true | falls back — software (…) |
| `none` | no context, or a first frame with no stroke in it | falls back — no WebGL |
| `incomplete` | the window was hidden while it drew, or it drew and then stopped: an `error` after the first frame, or fewer than 5 frames. It says nothing about the shell, so it **never replaces a record that finished**. It is kept as the shell's latest attempt, which `ad-fleet probe --open` reports | not yet measured — the probe did not finish (…) |
| `unknown` | a context that drew and would not name its renderer — not proven hardware | falls back — renderer unknown |

**A software renderer counts as falls back, not works.** And the rule for the rest of the epic
follows from it: **a shell whose probe says anything but `hardware` gets the plain fallback**
(the ink layer's `body.ink-off`, #248: the same marks as plain CSS borders and highlights). A skin ships switched on only
for shells whose cell here says *works*.

| Shell | Context | Renderer | Class | Frames p50 / p95 | First stroke |
| --- | --- | --- | --- | --- | --- |
| Chromium 141 (CI, headless) | WebGL2 | `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)` | software | printed by the test, not asserted | printed by the test |
| Edge (current) | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |
| JCEF (PyCharm 2026.1) | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |
| Simple Browser (VS Code) | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |

The three laptop rows are filled from `ad-fleet engines` by the runbook's §Ink (#247) in
[windows-verification.md](windows-verification.md), and stay *not yet measured* until then.

three.js is **vendored**, never fetched: `agentdata/fleet/static/vendor/three/three.module.min.js`
and its MIT `LICENSE`, from the npm tarball of `three@0.160.0`, pinned by sha256 in
`tests/test_fleet_probe.py` and kept byte-exact on Windows checkouts by `.gitattributes`. The
probe page imports it, and so does the desk's ink layer (#248, [desk-ink.md](desk-ink.md)), but
only on a shell whose record here says hardware (or a page opened with `?ink=on`, the test
override), and only once a skin draws with ink. There, since #257, it also draws every agent's trace,
which was one of the desk's two 2D canvases. Tests hold all three.

## What happens without each one

| Feature | Without it | Proven by |
| --- | --- | --- |
| `@starting-style` | A panel appears instead of fading in. Nothing is lost but the fade. | `test_fleet_motion.py` |
| `transition-behavior: allow-discrete` | The longhand is ignored, `display` is not animated, and a panel leaving is removed at once — which is exactly how these panels behaved before #216. | `test_fleet_motion.py` |
| `startViewTransition` | `transitionLayout` runs FLIP instead: measure, change, invert, release. The same gestures land identically, with every `view-transition-name` cleared. | `test_fleet_motion.py` |
| `linear() easing` | `--ease-spring` stays the `cubic-bezier` it is declared as first. The `@supports` block that upgrades it simply does not apply — which is why it is declared twice rather than once. | `test_fleet_motion.py` |
| `pointer capture` | `setPointerCapture` throws and is caught, in both drags that take it: the reorder drag on a pane's head or a rail's face (#217, captured on lift), and the gutter (#234, captured on the press). Both hear their move and release on the document rather than the handle, so both still track and a gutter still resizes. What is lost is the guarantee that events keep arriving after the pointer leaves the element: a touch or pen off the gutter's 8px strip, or a release outside an embedded window. And with no capture to take it, the release's click lands on the pane under the hand, which is why a gutter swallows the one click after a resize. | `test_fleet_window.py`, `test_fleet_gutters.py`, `test_fleet_engines.py` |
| `ResizeObserver` | The tiers (#233). No observer is made, and the same writer of `data-tier` is fed by a measurement of every pane after each layout pass, and a resize of the window asks for a pass. A pane still draws the tier its width says, a frame later than an observer would have said it. During a gutter drag the tier follows when the hand comes up rather than under it, because a layout pass waits for the hand. | `test_fleet_engines.py` |
| `container queries` | Not used for the tiers: `data-tier` is an attribute, which tests and the draw code can read and a container query is not (plan-panes §The pane). So a shell without them draws every tier the same. Inside a pane, the head keeps the model's word, the ticket and the chip's age under 500px, and the trace under 560px, and wraps to a second line rather than dropping them. `flex-wrap` is the fallback, and it is why the head has it. | `test_fleet_window.py` |
| `OffscreenCanvas` | Nothing of the desk's own is lost: the desk has no 2D canvas at all since #257, on or off the page. three.js asks a 1×1 one for a 2D context once, as its renderer starts, to learn whether it could resize a texture off the page. Without it three.js would use a page canvas for that, and the layer never hands it an image to resize. | `test_fleet_trace.py` |
| `HTML-in-canvas` | Nothing the desk has today is lost: no shell ships it, and the desk does not use it. Effects aim at element rects, line boxes and glyph boxes (#375) instead, read from the DOM. §Pixel-level HTML below says what it would take to use it. | `test_fleet_pixel_html.py`, `test_fleet_engines.py` |
| `WebGL` | Drawn by the ink layer (#248, [desk-ink.md](desk-ink.md)), and only on a shell whose probe says hardware (the table above). There it draws a skin's marks and materials (glass's ground among them), and every agent's trace beside them (#257). Every other shell gets the plain fallback (`body.ink-off`), and so do a shell nobody has measured, `?ink=off`, a shell that will not give a context, and a lost context. The trace is its own SVG, the ground is the palette's page (#257: a skin's stylesheet paints nothing), and a skin's mark table is drawn as plain borders and highlights. None of it animates, because a desk drawn at software speed is worse than a flat one. | `test_fleet_probe.py`, `test_fleet_ink.py`, `test_fleet_trace.py` |

`test_the_desk_arrives_at_the_same_place_with_every_fallback_taken` takes **all** of the fallbacks
at once — no view transitions, no pointer capture, no `linear()`, no container queries, no
`ResizeObserver` — which is the worst engine anybody will actually meet. The desk still hides a
tile, still reorders, still resizes by the gutter, still gives every pane the tier its width says,
and still draws its traces.

## Pixel-level HTML (#384)

The operator asked for "full html awareness on what seems to be a pixel level": effects that know
where the page's own words and pixels are. There are three ways to get the desk's HTML into the ink
layer's WebGL scene. `tests/test_fleet_pixel_html.py` measures all three in CI's Chromium, launched
with the one Blink flag that turns the first on, and prints its numbers every run.

| Route | What it is | Cost (Chromium 141 on SwiftShader) | Fidelity | Which shells have it |
| --- | --- | --- | --- | --- |
| HTML-in-Canvas | The WICG proposal: an element that is a child of a `<canvas layoutsubtree>` is uploaded as a WebGL texture by the browser's own painter | the upload about 8 ms for a 457×729 pane (the test) | exact: the browser paints it | none unflagged. Behind `--enable-blink-features=CanvasDrawElement`, Chromium 141 has `texElement2D/6` and Chromium 153 has `texElementImage2D/3`; the table's `HTML-in-canvas` row, per shell |
| SVG snapshot | A clone of the pane with its computed styles inlined, serialised into an SVG `foreignObject`, decoded as a `data:` image and uploaded with `texImage2D` | 21–45 ms for a 524×729 pane with only the styles that differ inlined (styles 8–15, serialise 4–5, decode 1.5–14, upload 6–17; measured 2026-09-23). About 400 ms when every computed property is inlined, as the test does | approximate: icons, pseudo-elements and scroll position come out wrong | every shell with WebGL |
| DOM-synced geometry | `Range.getClientRects()` for line boxes and one `Range` per character for glyph boxes, read from the live page | 183 line boxes for a full pane in 0.2 ms, and 2,456 glyph boxes in about 6.5 ms (2026-09-23). The test's short pane: 34 in 0.7 ms and 365 in 3 ms | boxes, not pixels: where the text is, not what it looks like | every shell |

All three keep the desk's rules:

- **No 2D context.** HTML-in-Canvas and the snapshot upload to a WebGL2 texture; the geometry is
  read from the DOM. The test watches every `getContext` and sees only `webgl2`. The probe row reads
  `WebGL2RenderingContext.prototype` and creates no context at all.
- **No `innerHTML`.** The snapshot is built with `cloneNode` and `XMLSerializer`, never by assigning
  markup. Comment nodes are dropped from the clone first, because a comment holding `--` is not
  valid XML and the image would not decode.
- **The CSP** (`serve.py`: `img-src 'self' data:`) already lets a `data:` image load. An SVG
  `foreignObject` image uploads to WebGL with no taint. HTML-in-Canvas needs no CSP change.
  Nothing is fetched from anywhere else.

**Refused:** html2canvas-style rasterisers (html2canvas, html-to-image, dom-to-image). Each paints
the page again on a 2D context, which the desk has not had since #257, and each is a dependency.

**Three generations of names.** The proposal has been `texElement2D` (Chromium 141 behind the
flag; six arguments, `target, level, internalformat, format, type, element`), `texElementImage2D`
(six arguments, the same order, for Chrome 138–149; three for 150+, `target, internalformat,
element`, where the format must be sized: `RGBA8`, not `RGBA`) and, in the current explainer,
`texElementSubImage2D` (`target, level, xoffset, yoffset, element`) with `content="drawable"`,
drawn inside the canvas's `paint` event once the element has a snapshot. The Chromium 153 on CI's
ubuntu legs has `texElementImage2D/3` behind the same flag, and refuses anything but a sized format
there (`Invalid internalformat. Must be one of RGBA8, SRGB8_ALPHA8, RGBA16F, or RGBA32F`). The flagged Chromium 141 also
has `HTMLCanvasElement.prototype.layoutSubtree` and a 2D `drawElement`, but no `requestPaint` or
`onpaint`. The origin trial is reported for M148–M151. The probe records whichever name it finds,
with its arity (`hic_api`, for example `texElement2D/6`), so each shell's record says which
generation it has.

**three.js.** The desk's three.js stays r160 (#247). r184's `HTMLTexture` would be the easy way in,
but r184's `build/three.module.min.js` statically imports `./three.core.min.js`. This server
refuses that request, because every route wants its `?t=` token and a static import cannot carry
one. Upgrading three.js is a plan of its own and not part of this gate.

### The gate

HTML-in-Canvas is adopted only when **all** of these hold:

1. It ships without a flag or an origin trial in the Chromium of at least 2 of the 4 shells, as
   `ad-fleet engines` prints their `HTML-in-canvas` row.
2. Its method name and arity are unchanged across two stable Chromium releases.
3. A Playwright check shows that drawable children keep hit testing and accessibility geometry.

Until then the verdict is **not yet**, and effects use DOM-synced geometry (#375). The desk never
moves its panes into a canvas without a plan of its own. No origin-trial token is committed, and
no shell is launched with a Chromium flag.

**Today's verdict: not yet.** No shell has it unflagged. CI's Chromium 141 has it only with the flag
(`texElement2D/6`, lit pixels read back, no `SecurityError`); the Chromium 153 on CI's ubuntu legs
has `texElementImage2D/3` behind the same flag, and `test_fleet_pixel_html.py` prints its upload. The laptop's shells are read by #383.

## What is *not* guarded by a fallback

Three things the page simply requires, because the shells have had them for years and the desk
cannot be written without them: `fetch`, `EventSource` and `<template>` + `cloneNode`. If one of
those is missing the page does not load, which is a failure nobody can mistake for a feature.

`innerHTML` and `insertAdjacentHTML` are *banned* rather than missing — see
[desk-components.md](desk-components.md).

## The numbers, and where they come from

| Measurement | Here | Asserted at |
| --- | --- | --- |
| frame time during a layout swap of five tiles at 1080p | 16.7 ms median, no `longtask` | no long task, main thread back inside 50 ms |
| the ground's drift, drawn by glass on the ink layer (#254, #257) | frames while it drifts, and none under reduced motion | frames counted, not milliseconds |
| the worst local gesture | ~6 ms | 50 ms |
| the static payload | 154 KB gzipped (489 KB on disk), the probe page's 6.3 KB and the ink layer's four modules (39 KB) included; three.js is not in it — 163 KB gzipped, fetched by `/probe` and by an ink layer that is drawing, never by a desk that is not | 200 KB |
| the WebGL probe, headless Chromium on SwiftShader, 1280×720 | 16.7 ms p50 and 33.4 ms p95 over ~130 frames (headless paces at 60 Hz); first stroke 265–320 ms | not asserted — software, and not what a GPU does |

Every one of those is printed by the test that measures it, so a CI run carries the numbers as
well as the verdict. `tests/test_fleet_motion.py`, `tests/test_fleet_trace.py`,
`tests/test_fleet_instant.py` and `tests/test_fleet_engines.py` are where they live.
