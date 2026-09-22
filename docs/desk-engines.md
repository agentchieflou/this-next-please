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
| `WebGL` | works | n/a — not used | n/a — not used | n/a — not used |

The Chromium column is **measured, not remembered**: `test_the_chromium_column_is_what_chromium_
actually_does` probes each feature in the browser CI runs against and fails if this table and the
engine disagree. The userAgent it measured is
`HeadlessChrome/141.0.0.0`.

The other three columns are filled in on the laptop, by the runbook in
[windows-verification.md](windows-verification.md). Until then they say what they are.

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
| `WebGL` | Not used, and will not be until these rows say all four shells run it. A 3D ground that works on one of the four screens is worse than a flat one that works on all of them. | — |

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
| the static payload | 96.6 KB gzipped (321 KB on disk) | 200 KB |

Every one of those is printed by the test that measures it, so a CI run carries the numbers as
well as the verdict. `tests/test_fleet_motion.py`, `tests/test_fleet_trace.py` and
`tests/test_fleet_instant.py` are where they live.
