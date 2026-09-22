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
| toolbar | brand, live dot, `window` segments, `see` group, settings link, `needs me` group | — (static) | `.toolbar`, `.segmented` | — | — | `test_fleet_desk_toolbar.py` |
| away strip | title, one line per repo, dismiss | `checkAway` | `.away-strip` | — | — | `test_fleet_desk_sessions_b.py` |
| tile | head, run line, session pill, cards, cells, transcript, composer | `drawTile` | `.tile` | `state-*`, `needs-human`, `held`, `is-solo`, `is-selected`, `is-hidden`, `is-pinned`, `size-2` | `1`–`9`, `h`, `r`, `m`, `a` | `test_fleet_desk_regressions.py` |
| state chip | word, age | `drawTile` | `.chip` | the five status roles, `stale` | — | `test_fleet_desk_regressions.py` |
| session pill | label, menu | `drawSessionPill` | `.spill`, `.smenu` | `is-reading` | `Alt+[`, `Alt+]`, `Alt+N` | `test_fleet_desk_switcher.py` |
| runs list | one row per run | `drawRuns` | `.live-runs`, `.ss-runs` | — | — | `test_fleet_desk_switcher.py` |
| cells | spend, ticket, pr, refresh, git | `drawCells` | `.cell` | `grey`, `idle`, `warn`, `over` | git cell opens the branches pane | `test_fleet_spend.py`, `test_fleet_branches.py` |
| spend cell | label, value | `drawSpendCell` | `.cell.spend` | `warn`, `over` | — | `test_fleet_demo_meter.py` |
| asks card | head, one row per question, send | `drawAsks` | `.asks` | — | — | `test_fleet_handoff_ask.py` |
| scope report | one sentence | `drawScopeReport` | `.scopereport` | `outside` | — | `test_fleet_handoff_scope.py` |
| column | head, bands, foot | `drawColumn` | `.column` | — | `j`, `k`, `Enter`, `Esc` | `test_fleet_column.py` |
| band | head, chip, last line, tail, tools | `drawBand` | `.band` | `needs-human`, `departed`, `is-quiet` | `h`, `r`, `m` | `test_fleet_column.py` |
| dock | label, chips, show all | `drawDock` | `.dock` | — | — | `test_fleet_desk_hide.py` |
| dock chip | name, state, badge | `drawDock` | `.dock-chip` | `needs-human`, `departed` | — | `test_fleet_desk_hide.py` |
| agent rail | one chip per checkout | `drawRail` | `.agentrail` | `is-candidate`, `is-dim` | `1`–`9` from a ticket row | `test_fleet_desk_rail.py` |
| board | search, ticket rows, history | `drawBoard` | `#tickets` | `dragging` | `b` | `test_fleet_desk_rail.py` |
| inbox | offered rows, refused rows | `drawTray` | `.tray` | — | `i` | `test_fleet_desk_actions.py` |
| where | hits | `drawHits` | `#hits` | — | `/` | `test_fleet_board_desk.py` |
| inspector | facts, rail, spend pane, branches pane, verify | `drawInspector` | `#inspectordetails` | — | — | `test_fleet_branches.py` |
| swap | one option per project | `drawSwap` | `#swap` | — | — | `test_fleet_board_desk.py` |
| notice | one line | `drawNotice` | `#notice` | — | — | `test_fleet_desk_hide.py` |
| model card | facts, fields, save | `openModelCard` | `.modelcard` | — | `m` | `test_fleet_column.py` |
| settings page | appearance, models, Copilot, permissions | `settings.js` | `body.settings-page` | — | — | `test_fleet_settings_page.py` |

`drawer` is not a component: it is a one-line alias for `section("drawer", …)`, kept because the
rest of the file already calls it that.

## What is deliberately not here

No virtual DOM, no diffing library, no component base class. The page has one list shape — rows
keyed by repository, session id or pattern — and one DOM, so `patchList` is thirty lines and owned.
A framework would be a build step, and a build step is a thing that does not arrive behind the
proxy.
