# The desk's components, and the contract every one of them keeps

The dashboard is one flat non-module script with no framework and no build step, and that is not
going to change: the page has to load inside PyCharm's JCEF tool window and VS Code's Simple
Browser behind a corporate proxy, where anything fetched from the internet simply does not arrive.

What *was* missing is this page. There was no statement of what a component is, what its parts are,
or who draws it — and the symptom was two functions painting the same tile's accent on two
different edges, one of which no rule gave a width to. The inventory below is checked by
`tests/test_fleet_components.py`: every `draw*` function in `static/` is named here, and every
component class named here exists in the markup or the stylesheet.

## The contract

Seven rules. They are not style; each one is a bug that happened.

1. **Created once, patched forever.** A component's element is made when its row first appears and
   written to on every draw after. `draw(el, row)` twice with the same row makes **no** DOM
   mutation — asserted with a `MutationObserver` at zero, per component. `place()` runs about two
   and a half times a second while an agent is talking; a page that rebuilt itself at that rate
   took the hover off whatever was under the cursor and the keyboard off whatever had just been
   reached.
2. **One owner per property.** No two functions write the same class, style or attribute on one
   element. The accent stripe is the bug this rule is named after: `drawTile` painted
   `border-left-color` and the `theme` stream handler painted `border-top-color`.

   Its sharper form: **a draw function rebuilding `class` must keep the classes it does not own.**
   `setOwned(el, owned, wanted)` is how. Both halves of this were found the hard way. `drawTile` dropped `is-selected`, `is-hidden`,
   `is-pinned` and `size-2` for `place()` to put straight back, which is two writes a pass and no
   idempotence; `drawBand` (the column's band, retired by #233) dropped `is-dragging`, and with it
   the `pointer-events: none` that makes `elementFromPoint` answer with what is *underneath* the
   band being dragged, so a draw landing mid-drag left the gesture hit-testing only itself and no
   drop target could light again. Neither shows on a fast machine, where the draw falls between the
   gestures.
3. **Listeners bound once.** A row's handlers are attached by `create`, never by `update`. A
   redraw that re-listened was a redraw that could double-fire.
4. **Lists are reconciled by key.** `patchList(parent, rows, keyOf, create, update)` in
   `common.js` is the only one. It creates what is new, writes what is present, removes what has
   gone, and fixes the order only when it is actually wrong — because `appendChild` blurs whatever
   it moves.
5. **A component reads its row, never another component's DOM.**
6. **Text through `text()`, markup through `<template>`.** `innerHTML` and `insertAdjacentHTML` are
   banned and tested. Every setter in `common.js` writes only when the value changes, which is what
   makes rule 1 cheap rather than careful.
7. **`place()` is idempotent.** A pass with nothing to change touches nothing.

## The setters

All in `common.js`, all guarded, all no-ops when the value is already right:

| Call | Writes |
| --- | --- |
| `text(el, value)` | `textContent` |
| `setClass(el, value)` | the whole `class` attribute |
| `toggle(el, name, on)` | one class |
| `attr(el, name, value)` | one attribute; `null`/`false`/`undefined` removes it |
| `hide(el, hidden)` | the `hidden` property |
| `style(el, prop, value)` | one custom or CSS property |
| `patchList(parent, rows, keyOf, create, update)` | a keyed list |

## The inventory

| Component | Parts, in DOM order | Drawn by | Styled in | States | Keys | Tested by |
| --- | --- | --- | --- | --- | --- | --- |
| toolbar | brand, live dot, `see` group, settings link, `needs me` group | — (static) | `.toolbar` | — | — | `test_fleet_desk_toolbar.py` |
| away strip | title, one line per repo, dismiss | `checkAway` | `.away-strip` | — | — | `test_fleet_desk_sessions_b.py` |
| row | the panes in the arrangement's order, then the rails of repositories that left | `place`, `reorderDomTiles`, the tier observer (`onRowResize`) | `#grid`, `.panes` | grouped (a project's checkouts share one rail) only when the rails do not fit | `j`, `k`, `1`–`9`, `Esc` | `test_fleet_column.py` |
| pane (rail, compact, full) | the rail's face; head, run line, session pill, cards, cells, transcript, composer | `drawTile`, `drawPaneRail` | `.tile`, `.pane-rail` | `data-tier` (`rail`, `compact`, `full`), `state-*`, `needs-human`, `held`, `is-solo`, `is-selected`, `is-hidden`, `is-grouped`, `is-quiet`, `is-pinned`, `is-dragging`, `size-2` | `Enter` on a rail, `h`, `r`, `m`, `a`, `Alt+←/→`, `Alt+Shift+arrows` | `test_fleet_column.py`, `test_fleet_window.py`, `test_fleet_desk_regressions.py` |
| activity trace | sixty bars, one a minute | `drawTrace` | `.trace` | red where a minute needed a person | — | `test_fleet_trace.py` |
| the ground | three blobs, drifting | `drawGround` | `#ground` | still under reduced motion or reduced transparency | — | `test_fleet_trace.py` |
| state chip | word, age | `drawTile` | `.chip` | the five status roles, `stale` | — | `test_fleet_desk_regressions.py` |
| session pill | label, menu | `drawSessionPill` | `.spill`, `.smenu` | `is-reading` | `Alt+[`, `Alt+]`, `Alt+N` | `test_fleet_desk_switcher.py` |
| runs list | one row per run | `drawRuns` | `.live-runs`, `.ss-runs` | — | — | `test_fleet_desk_switcher.py` |
| cells | spend, ticket, pr, refresh, git | `drawCells` | `.cell` | `grey`, `idle`, `warn`, `over` | git cell opens the branches pane | `test_fleet_spend.py`, `test_fleet_branches.py` |
| spend cell | label, value | `drawSpendCell` | `.cell.spend` | `warn`, `over` | — | `test_fleet_demo_meter.py` |
| asks card | head, one row per question, send | `drawAsks` | `.asks` | — | — | `test_fleet_handoff_ask.py` |
| scope report | one sentence | `drawScopeReport` | `.scopereport` | `outside` | — | `test_fleet_handoff_scope.py` |
| hidden count | one button: how many are put away, and the press that brings them back | `drawHiddenCount` | `.hiddencount` | — | — | `test_fleet_column.py`, `test_fleet_desk_hide.py` |
| gone rail | glyph, name; what restores it in the label | `drawGone` | `.gone-rail` | — | — | `test_fleet_desk_hide.py` |
| agent rail | one chip per checkout | `drawRail` | `.agentrail` | `is-candidate`, `is-dim` | `1`–`9` from a ticket row | `test_fleet_desk_rail.py` |
| board | search, ticket rows, history | `drawBoard` | `#tickets` | `dragging` | `b` | `test_fleet_desk_rail.py` |
| inbox | offered rows, refused rows | `drawTray` | `.tray` | — | `i` | `test_fleet_desk_actions.py` |
| where | hits | `drawHits` | `#hits` | — | `/` | `test_fleet_board_desk.py` |
| inspector | facts, rail, spend pane, branches pane, verify | `drawInspector` | `#inspectordetails` | — | — | `test_fleet_branches.py` |
| notice | one line | `drawNotice` | `#notice` | — | — | `test_fleet_desk_hide.py` |
| model card | facts, fields, save | `openModelCard` | `.modelcard` | — | `m` | `test_fleet_column.py` |
| settings page | appearance, models, Copilot, permissions | `settings.js` | `body.settings-page` | — | — | `test_fleet_settings_page.py` |

`drawer` is not a component: it is a one-line alias for `section("drawer", …)`, kept because the
rest of the file already calls it that. Nor is the **agent rail** (`drawRail`, `.agentrail`) the
pane's rail: it is the board's row of drop targets (#183), and it had the name first.

## The pane: one component, three widths (#233)

Every agent is a `.tile`, always, in one row (`main#grid`), and what it draws is decided by how
wide it is. There were two components for one agent — the tile when it was open and the column's
band when it was not — and one owner per property was twice as hard to keep. There is one now.

| Tier | Width | Shows |
| --- | --- | --- |
| `rail` | 48 px | the face (`.pane-rail`) and nothing else: the number, the state's glyph in its colour, the name down its length, the unread count; red when the agent needs a person. The age and the last line are its `aria-label` and `title` |
| `compact` | 160 – 359 px | the head (name, chip with its age, ticket, the three tools), the approval and question cards, the last lines, the reply box |
| `full` | 360 px and up | everything |

Who writes what, one owner each:

* **The width** is the stylesheet's, from two things `place()` writes: `is-solo` (open: it takes
  `--cols` shares of what the rails leave, never under 160 px) and nothing else (a 48 px rail).
  `--cols` and `--rows` are `reorderDomTiles`', as they were; `--rows` means nothing in a row and
  goes with the gutters (#234).
* **`data-tier`** has one writer, `setTier`, fed by one `ResizeObserver` on the row with 8 px of
  hysteresis. A pane that changes tier is drawn again from its row in the same frame. The tier
  never feeds back into the width, or a tier that changed the width would change the tier.
* **What is drawn at a tier** is `drawTile`'s: a rail skips the trace, the session menu, the
  cards, the scope report and the cells; a compact pane skips the trace, the menu, the scope report
  and the cells. `needs-human` is written at every tier, because `isHidden` reads it.
* **The face** is `drawPaneRail`'s — its whole `class`, its glyph, name, badge, label and title —
  and it reads the row, `unread` and the group it heads. `bell()` calls it when a count changes.
* **`is-grouped`, `is-quiet`, `is-selected`** are `place()`'s. A project's checkouts share one
  rail (`is-grouped` on all but the first) only when the rails do not fit (`groupRails`); a quiet
  rail is dimmed by *needs me*, never removed.
* **The row's order** is `reorderDomTiles`', which moves a pane only when the order is actually
  wrong and never while one is under the hand.

The proof is the same as every component's: a `MutationObserver` at zero, per component
(`tests/test_fleet_components.py`).

## How quickly it answers

`docs/desk-instant.md` has the order every gesture keeps — paint what is already known, post,
reconcile, and say so when the server disagrees — the one optimistic writer of the arrangement,
and the 50ms budget each local gesture is measured against.

## What is painted rather than laid out

`docs/desk-rendering.md` has the canvas rules and the two canvases that keep them: the activity
trace — an hour in sixty numbers, on a full pane's title bar — and the glass
skin's ground, drawn so that it can drift.

## The window gestures

`docs/desk-window.md` has the other half: an open pane is dragged by its head and a rail by its
face, and a pane's footprint is two numbers rather than one (until the gutters, #234).

## Motion

How a component *arrives* and how a layout change is animated is one page over, in
`docs/desk-motion.md`: three duration tokens with a budget a test enforces, `.enters` as the one
arrival pattern, and `transitionLayout(fn)` as the one door for anything that moves things.

## Which engines do what

`docs/desk-engines.md` has a row per platform feature this epic used — `@starting-style`,
`allow-discrete`, `startViewTransition`, `linear()`, pointer capture, container queries — against
Chromium, Edge, PyCharm's JCEF and VS Code's Simple Browser, each reading *works*, *falls back* or
*not yet measured*. The Chromium column is measured by a test rather than remembered, and every
fallback is proven by taking the feature away.

## What is deliberately not here

No virtual DOM, no diffing library, no component base class. The page has one list shape — rows
keyed by repository, session id or pattern — and one DOM, so `patchList` is thirty lines and owned.
A framework would be a build step, and a build step is a thing that does not arrive behind the
proxy.
