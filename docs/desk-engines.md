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
| `container queries` | works | not yet measured | not yet measured | not yet measured |
| `OffscreenCanvas` | works | not yet measured | not yet measured | not yet measured |
| `WebGL` | falls back — software (SwiftShader) | not yet measured | not yet measured | not yet measured |

The Chromium column is **measured, not remembered**: `test_the_chromium_column_is_what_chromium_
actually_does` probes each feature in the browser CI runs against and fails if this table and the
engine disagree. The userAgent it measured is
`HeadlessChrome/141.0.0.0`.

The WebGL row is the exception, and the reason is below: a context is not a verdict, so its cells
come from `/probe` rather than from `getContext`. CI's Chromium draws WebGL2 on SwiftShader, which
is software, so its cell says *falls back* — `test_the_webgl_row_is_what_the_probe_measured` holds
it there.

The other three columns are filled in on the laptop, by the runbook in
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
ad-fleet engines                  # this row, one line per column, read from the file
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
override), and only once a skin draws with ink. No shipped skin does yet, so no desk fetches it
today. Tests hold all three.

## What happens without each one

| Feature | Without it | Proven by |
| --- | --- | --- |
| `@starting-style` | A panel appears instead of fading in. Nothing is lost but the fade. | `test_fleet_motion.py` |
| `transition-behavior: allow-discrete` | The longhand is ignored, `display` is not animated, and a panel leaving is removed at once — which is exactly how these panels behaved before #216. | `test_fleet_motion.py` |
| `startViewTransition` | `transitionLayout` runs FLIP instead: measure, change, invert, release. The same gestures land identically, with every `view-transition-name` cleared. | `test_fleet_motion.py` |
| `linear() easing` | `--ease-spring` stays the `cubic-bezier` it is declared as first. The `@supports` block that upgrades it simply does not apply — which is why it is declared twice rather than once. | `test_fleet_motion.py` |
| `pointer capture` | `setPointerCapture` throws and is caught; the move and up listeners are on the document rather than the handle, so the drag still tracks. Touch and pen lose the guarantee that events keep arriving after the pointer leaves the element. | `test_fleet_window.py` |
| `container queries` | The head keeps the model's word, the ticket and the chip's age on a narrow tile, and wraps to a second line rather than dropping them. `flex-wrap` is the fallback, and it is why the head has it. | `test_fleet_window.py` |
| `OffscreenCanvas` | Not used. The trace and the ground are small enough to draw on the main thread — 0.10 ms a repaint for the ground — and a worker would be a second place that has to know the palette. | — |
| `WebGL` | Drawn on the desk only by the notebook skin (#249, [skin-notebook.md](skin-notebook.md)), through the ink layer (#248, [desk-ink.md](desk-ink.md)), which is gated. A shell whose probe says anything but hardware gets the plain fallback (`body.ink-off`). So do a shell nobody has measured, `?ink=off`, a shell that will not give a context and a lost context: the same mark table as plain borders and highlights, with no animation, because a desk drawn at software speed is worse than a flat one. | `test_fleet_probe.py`, `test_fleet_ink.py` |

`test_the_desk_arrives_at_the_same_place_with_every_fallback_taken` takes **all** of the fallbacks
at once — no view transitions, no pointer capture, no `linear()`, no container queries — which is
the worst engine anybody will actually meet. The desk still hides a tile, still reorders, still
resizes and still draws its traces.

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
| the ground's repaint | 0.10 ms median | 4 ms |
| the worst local gesture | ~6 ms | 50 ms |
| the static payload | 154 KB gzipped (487 KB on disk), the probe page's 6.3 KB and the ink layer's four modules (37 KB) included; three.js is not in it — 163 KB gzipped, fetched by `/probe` and by an ink layer that is drawing, never by a desk that is not. Nor is a skin's module or stylesheet, fetched only by the desk that chose it (the notebook's: 3.5 KB and 2.2 KB) | 200 KB |
| the WebGL probe, headless Chromium on SwiftShader, 1280×720 | 16.7 ms p50 and 33.4 ms p95 over ~130 frames (headless paces at 60 Hz); first stroke 265–320 ms | not asserted — software, and not what a GPU does |

Every one of those is printed by the test that measures it, so a CI run carries the numbers as
well as the verdict. `tests/test_fleet_motion.py`, `tests/test_fleet_trace.py`,
`tests/test_fleet_instant.py` and `tests/test_fleet_engines.py` are where they live.
