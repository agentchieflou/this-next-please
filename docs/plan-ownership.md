# Plan: ownership — every component stripped to its parts and owned, a render that patches and never rebuilds, motion with a budget, the tile as a window, rendering that earns its pixels, and an instant feel

_Status: PLANNED (2026-09-22) — epic #202 (slices #215–#220), under #91 (the fleet) and #122 (the desk), a
sibling of #145 (the desk on Windows), #154–#157 (the skins) and #179 (the sitting), and one of three plans written
from the same photograph as [plan-column.md](plan-column.md) (#200) and [plan-meter.md](plan-meter.md) (#201). The
operator's sentences are in §Decisions. The demo they pointed at (a post on x.com) could not be fetched from the
sandbox this plan was written in; instead of guessing at it, the operator was asked which of four lessons the desk
should take from it and chose all four — that answer, not the video, is what §The four lessons is built from. Every
platform feature named below is to be measured in Edge, PyCharm's JCEF window and VS Code's Simple Browser before
it is relied on, and every one ships with a fallback that is a page without the motion, never a broken page._

## Why this exists

The operator's sentence: *the premier interface functionality that separates a prototype from a real product … a lot
of this is handling animations and transitions well, as well as applying minimalist interface navigation.* And the
diagnosis: *some of our design failures are from not stripping down components to their bare parts and having full
ownership. We're not "templating" here.* Read against the code:

| What the operator says | What the code does | Section |
|---|---|---|
| *handling animations and transitions well* | the page's motion budget is **one** rule: `.tile.flip { transition: transform 260ms }` (`app.css:424`), played by `playFlip` (`app.js:2574–2599`) when tiles reorder. There is **no `@keyframes` anywhere** in `static/`, no `startViewTransition`, no `.animate(`. Every other change of state — a tile hiding, a panel opening, the dock appearing, a card arriving, a chip changing colour — is an instant `display: none` flip. The reduced-motion block (`app.css:697–703`) exists and has almost nothing to reduce | §Motion |
| *not stripping down components to their bare parts and having full ownership* | `app.js` is one flat non-module script of 3 082 lines and ~386 functions in the global scope, grouped by banner comments; there is no inventory of what a component is, what its parts are or who draws it. A tile's twenty controls are drawn by `drawTile` (`app.js:535–692`) and eight helpers with no stated contract between them. The one structural convention — a `<template>` with hidden pattern rows, kept in step with the script by `tests/test_fleet_serve.py:385–395` — is good and unnamed. The symptom: **two functions own the accent stripe** — `drawTile` paints `borderLeftColor` (`app.js:545`) and the `theme` SSE handler paints `borderTopColor` (`app.js:1105`), an edge no rule gives width to, so a live palette change leaves the stripe stale until the next `/api/fleet` | §Ownership |
| *a user isn't overwhelmed* | the page is drawn by **rebuilding**: `drawTile` reassigns `className` wholesale (`app.js:543`), destroys and rebuilds the state chip (`566–573`), the strip (`746–756`), the earlier-runs list (`667–674`); `drawCells` empties and recreates four cells with fresh listeners (`1988`); `drawDock` and `drawRail` rebuild every chip (`2713`, `1797`). `place()` (`2776–2814`) runs behind a 400 ms debounce on every SSE frame (`1058–1064`, `1082`, `1086`, `1329`) and on a 15 s interval (`1250`) — about 2.5 times a second while an agent is talking — and each pass tears down hover, focus and any transient state on every chip. The four real diffs in the file (`drawAsks`'s signature at `461`, `reorderDomTiles`'s `needsMove` at `2510`, `updateLayoutSegments`'s `built` at `2906`, the append-only transcript) are the exceptions that show the rule | §Instant |
| *INSANE things with pure JS* — fluid motion, a window manager, rich rendering, an instant feel | reorder is HTML5 drag-and-drop (`app.js:248–282`, no inertia, the ghost the browser draws); resize is a toggle between one and two columns (`size-2`, `app.js:2637`); nothing is drawn on a canvas; every click is a round trip — `action()` posts, awaits, then calls `refresh()` (`app.js:429–439`), so the page changes when the server answers and not when the hand moves. What is already right: no framework, no build step, no CDN, `innerHTML` banned and tested, 65 KB gzipped against a 200 KB budget, `<template>` cloning, `text()` everywhere | §The four lessons |

**The purpose is the same as the other two plans': the human's attention** — and here, their trust that the thing
under their hand is solid. A prototype flickers, rebuilds under the cursor and moves when the server says so; a
product moves when the hand does and holds still when it should.

## What is reused

- **Everything the page already refuses**: no framework, no build step, no CDN (`tests/test_fleet_serve.py:276–284`,
  CSP `default-src 'self'`); no `innerHTML` or `insertAdjacentHTML` (`:362–367`, `test_fleet_board_desk.py:825–828`);
  the 200 KB gzipped budget (`:287–303`); `node --check` and the markup/script hook agreement (`:385–395`). Ownership
  is more of this discipline, named, not a new one.
- **`<template id="tile">` and the hidden pattern rows** (`index.html:220–366`, `:251–252`, `:319–320`), `cloneNode`
  once per repo (`app.js:178`), the `tiles` Map (`app.js:1007–1025`), `text()` (`common.js:47`), `mk()`
  (`app.js:2060–2065`). The inventory names what these already are.
- **The four diffs that exist** — `drawAsks`'s signature guard, `reorderDomTiles`'s `needsMove`, the segments'
  `built`, the append-only transcript — as the pattern every other draw function adopts.
- **FLIP** (`measureTiles`, `playFlip`, `reduceMotion`, `app.js:2554–2599`) as the fallback where view transitions
  are not measured to work.
- **The reduced-motion block** (`app.css:697–703`) and the skin contract's rule that a skin introducing movement
  stops it under reduced motion ([themes.md](themes.md) §Accessibility Fallbacks).
- **The arrangement** (`order`, `size`, `pinned`, `hidden`; `POST /api/arrange`) and the `desk` SSE frame that keeps
  four windows agreeing (`app.js:1094`). Optimism is applied to it, not around it.
- **The palette tokens** (`app.css:7–24`) and `theme.to_css`: anything drawn on a canvas reads its colours from the
  same tokens the DOM does, and the skin check (`tests/test_fleet_skins.py`) measures it the same way.
- **The HIG**, as #145 cites it: *Motion* (motion is purposeful, brief, and can be turned off; it never delays the
  user), *Feedback* (immediate acknowledgement of every action), *Drag and drop* (direct manipulation; show what
  will happen; Esc cancels; a keyboard equivalent always exists), *Windows* (a window's size and position are the
  person's, and are restored). What is not adopted, again: windows that cover content — #148 removed the drawers
  for that reason and the column keeps the sidebar beside the grid.
- **The browser harness** (#146), Playwright's CDP session for tracing, the page globals, the shuffled suite, the
  regression convention, the laptop runbook.

## Prior art, and what is different here

- **The demo the operator pointed at** — unread here, so unquoted. What was asked and answered: fluid motion, a
  window manager, rich rendering, an instant feel — all four. §The four lessons takes each and says what it is on
  a desk of five agents behind a corporate proxy, in three browsers the operator does not choose.
- **Keyed reconciliation** as every UI library does it — a list of rows, a key per row, create the missing, patch the
  present, remove the gone. What is different: thirty lines in `common.js`, owned, with no virtual DOM, because the
  page has one list shape (rows keyed by repo, session id or pattern) and one DOM.
- **FLIP** (Paul Lewis, 2015) is already here; **view transitions** are the platform's own FLIP for whole layouts.
  What is different: both are behind one function, and which one runs is a measurement, not a preference.
- **`@starting-style` and `transition-behavior: allow-discrete`** are how the platform animates `display: none` to
  visible without JavaScript. What is different: the page has a dozen `display` toggles and one place they are
  written.
- **A window manager** — drag, resize, snap, minimise, maximise. What is different: no overlap, no z-order, no free
  placement. The grid's tracks and the column's slots are the only places a tile can be; a window manager here is
  direct manipulation of the arrangement the page already has.

## Ownership: the inventory and the render contract

`docs/desk-components.md` — one table, kept in step by a test. For every component: its name; its parts in DOM
order; its **one** draw function; its stylesheet block; its states (the classes it may carry); its keys; its
tests. The components: toolbar, footer, away strip, tile (head, run line, pill, cells, cards, transcript, composer),
band, column, dock, rail, chip, cell, card (approval, ask, scope, dispatch, model), pill, menu (`.popover`),
sidebar, inspector, transcript row, notice.

The contract every `draw` function keeps:

1. **Created once, patched forever.** A component's element is created when its row first appears and patched on
   every draw after; `draw(el, row)` with the same row makes **no** DOM mutation — asserted with a `MutationObserver`
   in a rendered-page test, per component, at zero.
2. **One owner per property.** No two functions write the same class, style or attribute on one element. The accent
   stripe is the first bug this rule fixes.
3. **Listeners bound once**, on the component's root, by delegation; a redraw never re-attaches.
4. **Lists are reconciled by key** — `patchList(parent, rows, key, create, update)` in `common.js`, the one helper,
   about thirty lines, with a test of its own. Chips, cells, tabs, sessions, asks, bands, rail chips, notifications.
5. **A component reads its row, never another component's DOM.**
6. **Text through `text()`**, markup through `<template>` — unchanged.
7. **`place()` is idempotent and cheap**: a pass with nothing to change touches nothing, and is asserted to.

## Motion with a budget

Tokens on `:root`, beside the palette's: `--motion-fast: 120ms; --motion-base: 200ms; --motion-slow: 320ms;
--ease-out: cubic-bezier(.2,.7,.3,1); --ease-spring: linear(…)` — the spring as a `linear()` easing curve, so it is
CSS and needs no script. The rules:

- **Enter and leave animate** — every `display` toggle on the page goes through one pattern: `@starting-style` for
  the entry, `transition-behavior: allow-discrete` for the exit, opacity and a few pixels of translate, `--motion-base`.
  Bands folding, cards arriving, the menu opening, the away strip, the dock, a tile hiding.
- **Layout changes are one transition** — opening a band (the swap), hiding, reordering, the layout picker: behind
  `transitionLayout(fn)`, which uses `document.startViewTransition` where it is measured to work and FLIP where it is
  not. The transcript **never** moves: text a person is reading holds still.
- **Drag follows the hand** — pointer events with `setPointerCapture`, the dragged element under the cursor at
  `transform` only, a short settle on release; never the browser's drag ghost. Whether release carries inertia is an
  open question, not a default.
- **The budget**: no transition or animation over `--motion-slow`; nothing infinite but the live dot; every motion
  under the reduced-motion block; a test reads every stylesheet and asserts all three. A frame-time floor on CI —
  a swap of five tiles at 1080 px drops no frame below 50 fps in Chromium 141 under CDP tracing — with the laptop's
  own number recorded beside it.
- **Platform**: the tests drive Chromium 141 (Playwright 1.63), where `@starting-style`, `allow-discrete`, same-document
  view transitions, `linear()`, pointer capture and the `popover` attribute all exist. JCEF and Simple Browser are
  **not measured**, and [themes.md](themes.md) §Accessibility Fallbacks already records one query Chromium shipped
  late. Every feature is used behind a check and falls back to no motion, and slice F's rows say which engine has
  which.

## The four lessons

**Fluid motion** is §Motion: enter, leave, swap, drag, each brief and each under a budget.

**A window manager** — the tile as a window: **drag** to reorder with the pointer (grid and column); **resize** from
its right and bottom edges with the pointer, snapping to the grid's tracks (one, two, three columns) and to the
page's thirds in height, and `size` in the arrangement becomes `{cols, rows}` (migrated from `size: 2`, which reads
as `{cols: 2, rows: 1}`); **minimise** is hide, and the column or the dock is where it went; **maximise** is open;
**a title bar** is the head, the same component on a tile, a band and the inspector, so the eye finds the same thing
in the same place; **Esc** closes what is open, in order (menu, card, then back); `Alt+arrows` resize from the
keyboard. What a window manager also does and this does not: overlap, z-order, free placement — a window covering
content is the drawer #148 removed, and the HIG's *Sidebars* rule stands.

**Rich rendering** — where the DOM cannot draw it and the pixels say something: an **activity trace** on every tile
and band, a `<canvas>` strip of the last hour — one mark per event (assistant text, tool call, denial, a cost rise),
red where the agent needed a person — drawn once per tick from the fold, its colours the palette's tokens, its text
twin an `aria-label` reading *41 events in the last hour, needed you twice*; the **ground** under the glass skin as
a canvas that drifts a pixel a second and holds still under reduced motion; the **live dot**'s pulse. The rules: no
WebGL and no shader until JCEF and Simple Browser are measured to run one; every canvas has a text alternative
carrying the same information; a canvas never carries information the DOM lacks; the payload budget holds.

**An instant feel** is §Instant.

## Instant

- **Optimistic arrangement.** `arrange` (order, size, pin, hidden), `window` (open, held) and hide apply to the page
  before the POST and are rolled back on a refusal with the refusal's words on the notice line. The `desk` frame
  that follows confirms or corrects; four windows still agree because the server is still the record.
- **An action answers with its row.** `act()` returns the affected row (as `settings` already returns the snapshot),
  and the page patches from the answer instead of a second `/api/fleet` — one round trip becomes none visible.
- **Stale while revalidating.** On reconnect after `onerror` (`app.js:1116–1122`) the page draws from the last
  snapshot it has, immediately, then patches when `/api/fleet` answers; the reconnecting dot is the only sign.
- **No spinner, anywhere.** An in-flight state is the control itself — the refresh icon turning, a pill dimmed, a
  button with its label changed — never an overlay, never a modal. If something is genuinely loading, its age says
  so, as the HIG's *Feedback* rule already has every cell do.
- **A latency budget**: input to paint within 50 ms for every local gesture (open, hide, pin, resize, menu),
  measured with `performance.mark` pairs the page leaves in place and read by the browser tests; 100 ms for a
  gesture that must ask the server, with the optimistic paint inside the first 50.

## Where everything is written down

- `docs/desk-components.md` — new, the inventory, kept in step by a test that finds every `draw*` function and
  every component class named in it.
- [fleet-dashboard.md](fleet-dashboard.md): §Motion (new), §The page's table gains the trace and the resize edges,
  §Keyboard gains `Alt+arrows`.
- [testing-this-repo.md](testing-this-repo.md) §The browser tests: the idempotence, motion-budget, frame-time and
  latency guards, and how to read a CDP trace the CI job attaches.
- [themes.md](themes.md) §The Skin Contract: a canvas reads the tokens; the ground's drift is under reduced motion.
- [windows-verification.md](windows-verification.md): the engine rows.

## Slices

### A #215 — the inventory and the render contract: `desk-components.md`, `patchList`, every draw idempotent, one owner per property

**Context.** §Ownership. `drawTile` (`app.js:535–692`), `drawCells` (`1986`), `drawStrip` (`727`), `drawDock` (`2692`),
`drawRail` (`1797`), the accent bug (`app.js:545` vs `1105`), the four existing diffs.

**Build this.**
1. `docs/desk-components.md` with every component's row; a test that every `draw*` in `app.js` and `settings.js`
   is named there and every component class it names exists in the markup or the CSS.
2. `patchList` in `common.js`, thirty lines, its own unit test in the browser (create, update, remove, reorder, key
   collision refused).
3. Every list on the page reconciled through it: chips, cells, tabs, sessions, asks, assumptions, rail chips,
   notification rows, the earlier list. Every `draw` patches: `className` toggled per class, the chip's children
   kept, the run line's text set only when changed.
4. Listeners by delegation on each component's root; `drawDock`, `drawRail`, `drawCells` attach nothing on redraw.
5. The accent stripe has one owner; the `theme` handler calls it.
6. `place()` with nothing changed makes no DOM mutation — a `MutationObserver` test over twenty passes.

**Acceptance criteria.**
- [ ] For every component in the inventory, `draw(el, row)` twice with the same row records zero mutations.
- [ ] A hovered dock chip keeps `:hover` and a focused cell keeps focus across ten SSE frames.
- [ ] A `theme` frame repaints the left stripe and nothing else on the tile.
- [ ] The static payload does not grow by more than `patchList`'s size; `node --check` and the hook test pass.
- [ ] `tests/test_fleet_desk_regressions.py`'s globals are unchanged.

**Out of scope.** Any motion (B); any new control.

### B #216 — motion with a budget: tokens, enter and leave, one layout transition with a FLIP fallback, and the frame-time floor

**Context.** §Motion. `app.css:424` (the one transition), `app.css:697–703` (reduced motion), `playFlip`
(`app.js:2574–2599`).

**Build this.**
1. The motion tokens on `:root`; the reduced-motion block unchanged in effect and asserted to cover every new rule.
2. Enter and leave through `@starting-style` + `allow-discrete` for every `display` toggle the inventory lists, one
   CSS pattern, opacity and translate, `--motion-base`.
3. `transitionLayout(fn)`: `startViewTransition` when `document.startViewTransition` exists and the engine is on the
   measured list, FLIP otherwise; open, hide, reorder and the layout picker go through it. The transcript is
   excluded by `view-transition-name: none`.
4. The budget test: every `transition-duration` and `animation-duration` in `static/` ≤ 320 ms; no
   `animation-iteration-count: infinite` outside `.dot`; every rule reachable from the reduced-motion block.
5. Frame-time on CI: a CDP trace of the swap with five fixture tiles at 1080 px; the floor at 50 fps; the number
   attached to the job.

**Acceptance criteria.**
- [ ] Hiding a tile, opening a band and opening the menu each produce a transition of `--motion-base` in Chromium 141
      and none under `prefers-reduced-motion: reduce` — asserted with `getAnimations()`.
- [ ] With `startViewTransition` stubbed away, the same gestures run FLIP and the page is identical after.
- [ ] The budget test passes over `app.css` and every skin.
- [ ] The trace shows no frame over 20 ms during the swap on CI.

**Out of scope.** Drag (C); canvas (D).

### C #217 — the tile as a window: pointer drag, resize from the edges with snap, `size {cols, rows}`, minimise and maximise mapped, keys

**Context.** §The four lessons, *a window manager*. `app.js:248–282` (HTML5 drag), `toggleTileSize`
(`app.js:2637–2647`), `.tile.size-2` (`app.css:398`), the arrangement's `size`.

**Build this.**
1. Pointer drag with capture for reorder in the grid and the column; the dragged element at `transform` under the
   cursor; drop targets lit as the rail's are; `Esc` cancels; keyboard reorder unchanged.
2. Resize handles on the right and bottom edges; snap to the grid's tracks and to thirds of the page height; a
   ghost outline shows the snap before release (HIG *Drag and drop*: show what will happen).
3. `size: {cols, rows}` in the arrangement, `size: 2` read as `{cols: 2, rows: 1}`; `POST /api/arrange` accepts
   both; `desk.json` migrates on first write.
4. Minimise is `setHidden`; maximise is `open`; the head is the one title-bar component on tile, band and inspector.
5. `Alt+arrows` resize; the key map popover says so.

**Acceptance criteria.**
- [ ] Dragging tile 3 over tile 1's slot and releasing reorders the arrangement and every other window agrees
      through the `desk` frame; `Esc` mid-drag leaves the order unchanged.
- [ ] Resizing from the right edge to the second track writes `{cols: 2, rows: 1}`; an old `size: 2` in `desk.json`
      reads the same.
- [ ] Every pointer gesture has a keyboard equivalent and the test drives both.
- [ ] Reduced motion: the drag still works, without the settle.

**Out of scope.** Overlap, z-order, free placement; drag inertia (§Open questions).

### D #218 — rendering that earns its pixels: the activity trace on every tile and band, the ground's drift, text twins, no WebGL until measured

**Context.** §The four lessons, *rich rendering*. The fold (`agentstate.py`), the palette tokens, the glass skin's
ground (`skins/glass/skin.css`), the 200 KB budget.

**Build this.**
1. `/api/fleet` rows gain `trace`: the last hour's events bucketed by minute with kind counts and a needs-human
   flag — sixty small integers, no transcript text.
2. The trace canvas on the tile (in the head, beside the chip) and the band, drawn once per tick from the row,
   colours from the tokens, `aria-label` with the sentence; `devicePixelRatio`-aware; redrawn on `theme`.
3. The glass ground as a canvas drifting a pixel a second, still under reduced motion and under reduced
   transparency; the other skins unchanged.
4. The rules in [themes.md](themes.md): a canvas reads tokens, has a text twin, carries nothing the DOM lacks; no
   WebGL until slice F's rows say the engines run it.

**Acceptance criteria.**
- [ ] A fixture agent with forty events in the last hour and two red minutes: the trace has forty marks and two red
      ones, counted by reading the canvas back, and its label says *40 events in the last hour, needed you twice*.
- [ ] The trace repaints when the palette changes and its colours equal the tokens' computed values.
- [ ] The glass ground makes no frame over 4 ms of script on CI and does not move under reduced motion.
- [ ] The payload stays under budget; no skin exceeds its own.

**Out of scope.** Charts of spend ([plan-meter.md](plan-meter.md) draws a number); any 3D.

### E #219 — instant: optimistic arrangement with rollback, actions that answer with their row, stale-while-revalidate, a latency budget, and no spinner

**Context.** §Instant. `action()` (`app.js:429–439`), `refresh()` (`1051`), `onerror` (`1116–1122`), `act()`
(`serve.py:1366`).

**Build this.**
1. Optimistic `arrange`, `window` and hide: apply, post, roll back on a refusal with its words on the notice line;
   the `desk` frame reconciles.
2. `act()` answers with the affected row for every action that changes one; the page patches from it and the
   `refresh()` after every action (`app.js:436`) goes.
3. Reconnect draws the last snapshot first, then patches.
4. `performance.mark` pairs around every local gesture; a browser test asserts the 50 ms budget per gesture on CI
   and the runbook records the laptop's.
5. A test that no element on the page has a class or role naming a spinner, loader or overlay.

**Acceptance criteria.**
- [ ] Hiding a tile paints inside one frame and before the POST resolves — asserted by delaying the server.
- [ ] A refused `arrange` (the server answers a `code`) restores the previous arrangement and shows the refusal.
- [ ] After `send`, the tile's row is patched from the answer with no second `/api/fleet` request — counted.
- [ ] Every local gesture's mark pair is under 50 ms on CI.

**Out of scope.** Changing what any action does on the server.

### F #220 — proof: the engine rows for every platform feature, frame time and latency in CI, and the inventory complete

**Context.** §Motion's platform note; [windows-verification.md](windows-verification.md).

**Build this.**
1. Engine rows: `@starting-style`, `allow-discrete`, `startViewTransition`, `linear()`, pointer capture, `popover`,
   `OffscreenCanvas`, WebGL — in Edge, JCEF (PyCharm 2026.1) and Simple Browser — each *works · falls back · not
   yet measured*, and the fallback proven by the same test with the feature stubbed away.
2. The CI browser job attaches the CDP trace and the latency marks; the numbers are in the epic.
3. `desk-components.md` complete: every component, every test named.
4. Docs as §Where everything is written down; `CHANGELOG.md`.

**Acceptance criteria.**
- [ ] Every engine row is filled in or reads _not yet measured_.
- [ ] The inventory test passes and names no component without a test.
- [ ] The definition-of-done demo: five fixture agents, a swap, a resize, a hide and a reconnect, recorded as a
      short video by Playwright and attached to the epic.

**Out of scope.** Anything the rows say is not measured.

## Ground rules

1. **No framework, no build step, no CDN**; `innerHTML` stays banned; the payload budget holds. Ownership is
   discipline, not dependency.
2. **Created once, patched forever; one owner per property; listeners bound once.** A `MutationObserver` at zero is
   the proof.
3. **Every motion is brief, purposeful and optional**: ≤ 320 ms, under reduced motion, never on text being read.
4. **Measured, with a fallback that is the page without the motion.** No feature is relied on that the three engines
   have not been seen to run; the fallback is tested by stubbing the feature away.
5. **Nothing overlaps content.** No z-order, no free placement; the sidebar sits beside, the menu is the one popover.
6. **Every canvas has a text twin** and reads the palette's tokens.
7. **The server is still the record.** Optimism paints first and rolls back; four windows agree through the `desk`
   frame as before.
8. **Every gesture has a key**, and `Esc` always means *close what is open*.
9. **The page globals the regression tests call keep their names**; the fake `copilot` stays the only agent CI runs.
10. **Numbers, not adjectives**: frame time, latency, payload — each a test with a floor, and the laptop's number
    written beside CI's.

## Build order

A first, and before [plan-column.md](plan-column.md) B and [plan-meter.md](plan-meter.md) C if the schedule allows —
it is the contract those draw under. B after A. C after column A (the column is where drag and resize land). D after
A and B. E after A. F last, though every slice lands with its own rendered-page test.

## Open questions, to be answered on the laptop and recorded in the slice

- Do JCEF (PyCharm 2026.1) and Simple Browser run `startViewTransition`, `@starting-style` and `linear()`? (B, F)
- Should the column's swap be a view transition (whole-layout crossfade) or FLIP (the two tiles trade places)? (B)
- Does drag inertia on release feel like a product or like a toy on the real screens? Default: no inertia, a short
  settle. (C)
- Is the activity trace legible at a band's height and worth its 24 px on a 360 px tile? (D)
- Should resize snap to thirds of the page or to the grid's row height once the column sets one? (C)
- What is the laptop's actual frame time for a swap under the glass skin's blur — #179 asked this and it is still
  _not yet measured_. (B)

## Cost

No premium request anywhere. CPU goes down: a page that patches does less than one that rebuilds 2.5 times a second.
CI time goes up by the traces, bounded to the browser job. The thing this plan spends is discipline, and the thing it
buys is the operator's sentence in reverse: a real product, not a prototype.

## Decisions — the operator's, 22 September 2026

- The diagnosis, verbatim: *some of our design failures are from not stripping down components to their bare parts and
  having full ownership. We're not "templating" here.* §Ownership is that made a contract and a test.
- Asked which lessons the desk should take from the demo the sandbox could not reach — fluid motion, a window
  manager, rich rendering, an instant feel — the operator chose **all four**. Each is a section and a slice.
- The other two plans' decisions (the column as the default; the meter first) shape where this plan's motion and
  windows land, and are recorded there.
