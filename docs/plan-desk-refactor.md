# Plan: the desk on Windows — the dashboard shows the run you are in, its tiles move, and it wears the terminal's theme

_Status: PLANNED (2026-09-09) — epic #145 (slices #146–#151, and the skin tier #154–#157), a refactor under #122 tied to the CLI
theming epic #135 (which gains five more palettes in #153). Nothing below is
built yet. Every design choice cites the section of Apple's Human Interface Guidelines it applies, and every
one is still judged on the real screens, the way #133 and #135 are judged._

## Why this exists

#133 shipped the three layouts and focus mode as one page under a query string, and left the decision to a
sitting on the laptop. The sitting happened on Windows, and three things were found before a layout could
even be judged:

| What the operator saw | What the code does | Section |
|---|---|---|
| The layout options can be selected, but the experience is poor | the picker is a `<select>` whose values are `grid\|agents\|0`; choosing one sets `location.search` and **reloads the page**, dropping the transcripts, the scroll positions and the open panels; twelve controls sit in one unlabelled row in the header, and four drawers (board, inbox, notifications, where) overlap each other at the same edge | §Chrome |
| The chat widgets cannot be moved around | tiles are appended in registry order and stay there; there is no drag, no resize and no pin — the only "move" is the `swap` select in the `screens` layout, and it is a full-page reload too | §Arrangement |
| The tiles do not load the current state; they show a cached or historical session | `fleet_snapshot()` folds the **whole** of `events.norm.jsonl` into one state and replays its last forty events as the transcript, with no run boundary; a tile therefore shows the last supervised run — a `done` chip and a "why" from two days ago — as if it were now, and a Copilot session the operator started in a terminal is invisible to it because `events.refresh()` only tails the supervisor's own `logs/events.jsonl` | §The run you are in |

A fourth finding is structural rather than visible: the dashboard has its **own** theme system —
`/api/themes` parses `themes/pycharm/*.icls` into seven CSS variables, and the choice is remembered in
`localStorage` per browser window — while #135 is building a `Theme` model for the terminal. Two palettes for
one desk is the second-source-of-truth problem again: the tile for `rdsd-pbi-reporting` and the terminal for
`rdsd-pbi-reporting` would say "where am I" in two different colours. §One palette makes them the same pixel.

**The purpose is the same as #135's: the human's attention.** Three questions a glance should answer — *where
am I*, *what is running*, *what needs me* — and the dashboard answers the second one wrongly today.

## What is reused

- `agentdata/fleet/serve.py`, `static/app.js`, `static/app.css`, `static/index.html` — the page stays one
  page with no framework, no build step and no CDN, because it has to load in PyCharm's JCEF tool window and
  VS Code's Simple Browser behind the corporate proxy ([fleet-ide.md](fleet-ide.md)). Everything below is a
  change to these four files and to the server functions behind them, not a rewrite.
- `events.norm.jsonl` is **additive only** and history is never rewritten ([fleet-events.md](fleet-events.md)).
  The `started` event already carries `resumed` and `session`; it is the run boundary this plan reads. Nothing
  is deleted to make the tile current.
- `agentstate.derive()` is the state. The fix for the stale tile is to fold *the current run* and to stamp the
  state with its age, not to invent a second fold in the page.
- `_selection` and `desk_state()` already hold the shared selection and the screen pinning and push them down
  the SSE stream as a `desk` event. The arrangement (order, size, pin) is more of the same state, held the same
  way — and persisted, which the selection is not.
- The ticket drag-and-drop (#98) already proves HTML5 drag events work in Edge, JCEF and Simple Browser; tile
  reordering uses the same API.
- `agentdata/theme.py` (#136), `theme.check()` and `theme.projects.<name>` (#139) are the palette and the
  per-project mapping. This epic adds one more render of the same `Theme` — CSS custom properties — and
  removes the `.icls` parser from the server.
- The CI matrix already runs Windows (`.github/workflows/tests.yml`), and Chromium is the engine under Edge,
  JCEF and Simple Browser alike. #133's Playwright smoke never landed (`tests/test_fleet_serve.py` says so in
  its docstring); it lands here, dev-only.

## Apple's Human Interface Guidelines, applied on Windows

The HIG is the design reference because it is the most complete written statement of *why* an interface
choice is made, and every rule below is one a browser can render on any OS. What is **not** adopted is the
Mac chrome: title bars, traffic lights and the menu bar belong to Windows and to Edge, and the page does not
draw them. Each slice names the sections it applies.

| HIG section | The rule this plan takes from it | Where it lands |
|---|---|---|
| **Layout** | consistent margins and spacing on an 8-point grid; align content; adapt to the window's size rather than to a screen size; prioritise what matters at the top | every slice; the tile's header, cells, rail and transcript on one spacing scale |
| **Toolbars** | frequently used commands, grouped by meaning, with labels; never crowded; the toolbar is not a settings panel | the header becomes a toolbar of three groups: *which window*, *what to see*, *what needs me* |
| **Segmented controls / Pop-up buttons** | mutually exclusive modes are a segmented control; a long list is a pop-up button | the layout picker; the swap and theme pickers |
| **Sidebars / Split views** | auxiliary content lives in a sidebar that the main content sits beside, not a drawer that covers it; the sidebar remembers its width and whether it was open | board, inbox, notifications and *where* become one sidebar with four sections |
| **Windows and panels** | a window restores its state on relaunch; an inspector shows the selected item's details | the arrangement and the selection are restored from the server; the selected project has one inspector |
| **Drag and drop** | direct manipulation; show what will happen before it happens; Esc cancels; a keyboard equivalent always exists | tile reordering, resizing and pinning |
| **Feedback / Loading** | show content progressively; never present stale content as current; say what is loading and how old what is shown is | the run header on every tile, the age on every state, the "no run since" line |
| **Focus and selection** | the selected item is unmistakable and there is exactly one selection | `is-selected` gets a visible treatment that is not the state colour |
| **Color** | semantic colours; support light and dark; never rely on colour alone; text contrast ≥ 4.5:1 and UI contrast ≥ 3:1 | the token model in §One palette; every chip keeps its glyph; `theme.check()` becomes the CSS check too |
| **Typography** | the system font at readable sizes; a minimum of 11 points; monospaced only for what is monospaced | `Segoe UI` on Windows is already first in the stack after `-apple-system`; the 10-point chips grow |
| **Accessibility** | full keyboard operation; hit targets of at least 28 points on desktop; visible focus rings; `prefers-reduced-motion` honoured | the key map stays; buttons grow; reorder has a keyboard path; no animation that cannot be turned off |
| **Notifications** | already #97's — quiet hours, dedupe, one toast per state change | unchanged |

## The run you are in

A **run** is what one `started` event begins: a launch, a `restart`, or a `resume`. Today the tile folds all
runs into one and shows the tail of the last one. After this plan:

- `fleet_snapshot()` returns, per repo, `run: {n, started, resumed, session, ticket, live, events}` for the
  **current** run — the last `started` and everything after it — and `earlier: [{n, started, ended, state}]`
  as a summary of the runs before it. `recent` is the current run's events, not the last forty of history.
- The state chip is derived from the current run, with the fold's own `at` beside it as an age: `done · 2d`
  is honest; `done` alone was the bug. A repo with no run since `ad-fleet serve` started says so on the tile
  in a sentence (*last run ended 2 days ago; nothing is supervised now*) instead of wearing that run's chip
  as if it were live — HIG *Loading*: stale content is never presented as current.
- Earlier runs are one collapsed `details` per tile, opened on demand, and never replayed into the live
  transcript. History is still read, still additive, still never rewritten.
- A Copilot session the operator started **outside** the fleet is a transport question (#92's laptop half,
  `copilot --headless --port`), not a dashboard one. Until it is measured, the tile says the truth — *this
  agent is not supervised* — rather than showing the last supervised run in its place. The measurement is an
  open question below, and its answer is a slice under #91, not here.

## Arrangement

The arrangement is server state, like the selection, so four windows agree on it and a reload restores it:

```
~/.agentdata/fleet/desk.json
  selected, screens, version                # what `_selection` holds today, now persisted
  arrangement:
    grid:    { order: [repo…], size: {repo: 1|2}, pinned: [repo…] }
    roles:   { order: [...] }               # one arrangement per layout, because a wide tile on the
    screens: { order: [...] }               #   left monitor is not a wide tile on the laptop
```

`POST /api/arrange` is the one write; it rides the existing `desk` SSE event. Dragging a tile shows where it
will land before the drop; Esc cancels; `Alt+←/→` moves the focused tile without a mouse; a size toggle on
the tile's header switches one column and two; a pin keeps a tile first. Nothing is written outside
`~/.agentdata/fleet/`, and the page still decides nothing — it asks the server to record what the operator did.

## One palette, rendered once more

`theme.py` (#136) already renders a `Theme` as SGR, truecolor and a dict. This epic adds the fourth render,
`theme.css(t) -> dict[str, str]`, and the dashboard's tokens become a **stated mapping** from theme roles:

| CSS token | Theme role | The same role in the terminal |
|---|---|---|
| `--bg` | `ground` | OSC 11 / the conhost background |
| `--text` | `text` | OSC 10 / the foreground |
| `--panel` | `ground` moved 4% toward `text` (derived in code, not a fifth hex) | — |
| `--line` | `ground` moved 15% toward `text` | — |
| `--select` | `ground` moved 18% toward `accent` | — |
| `--muted` | `ansi.bright_black` | SGR 90, what `color.py` calls `grey` |
| `--accent` | `accent`, or the project's own under `theme.projects.<name>` (#139) | the prompt's project segment; the Windows Terminal `tabColor` |
| `--focus` | `cursor` | OSC 12 |
| `--running` | `status.info` | `color.STATUS["info"]` |
| `--waiting` | `status.warn` | `color.STATUS["warn"]` |
| `--human` | `status.fail` | `color.STATUS["fail"]` |
| `--done` | `status.ok` | `color.STATUS["ok"]` |
| `--idle` | `status.skip` | `color.STATUS["skip"]` |

**The status rule is restated, not broken.** `app.css` says "status colours never change", and it meant
*never change meaning*: a chip that says "needs you" is `status.fail` in every theme, and `state → role` is
a fixed table. What this plan changes is where the role's *value* comes from: the theme's `status` map, which
`theme.check()` has already proved is ≥ 3:1 against that ground and distinguishable from its neighbours.
That is the only way the tile and the terminal can be the same pixel — and it is why `reds` matters here as
much as in #136: on a `#400000` ground the hard-coded `#cc3344` chip disappears, and the theme's amber `fail`
does not. The glyph is always there (HIG *Color*: never colour alone).

The choice moves out of `localStorage` and into `~/.agentdata/config.json`: `theme.default` is the page's
theme, `theme.projects.<name>` is the tile's accent, `none` means *follow the system* (`prefers-color-scheme`,
today's behaviour). `ad-theme set` changes the file; the server notices on its slow clock and pushes a `theme`
event, so every window on every screen recolours with the terminal beside it. `/api/themes` serves the six
themes from `theme.py` and the `.icls` parser goes; `themes/pycharm/` stays what it is — editor schemes for
PyCharm — and a later slice of #135 may generate them from the same palette.

## The vertical: eleven palettes and three skins

The operator approved the mock-ups and asked for the theme list to go further. Eight more were named, and they
fall into two tiers that this plan keeps apart on purpose:

| Tier | What changes | 1:1 with the terminal? | Where it lives |
|---|---|---|---|
| **Palette** | colour only — one `Theme` constant | **yes**, by construction: the same hex reaches OSC 10/11, the prompt and `theme.css()` | #136's model; #153 adds `dark`, `vanta-black`, `matrix`, `blues`, `sand` |
| **Skin** | how the page is *rendered* — materials, tiled textures, sprites, a pixel font | **no**, and it says so: a skin rides on a base palette that the terminal gets; the material is the page's alone | #154 (the tier) and one slice per skin: #155 `glass`, #156 `voxel`, #157 `farmstead` |

Palettes are cheap and land under #136's check unchanged; the seeds and their contrast against the derived panel
and selection colours are in the canvas. Two are proof themes for the status rule beside `reds`: on `matrix`
`fail` is red because it is the one thing on the screen that is not green, and `vanta-black` is allowed a true
black ground only because its text is not pure white.

### Skins

A skin is **one more stylesheet over the same DOM**: the three skin boards in the canvas are the approved grid
with nothing but CSS and hand-drawn SVG swapped in, which is the test every skin has to keep passing — a skin
that needs a page change is not a skin. The contract, from #154:

- `theme.skin` in `~/.agentdata/config.json`, `none` by default; `/api/themes` lists skins with their `base`
  palette and byte size; the page adds one `<link>` to `/static/skins/<name>/skin.css` when a skin is chosen
  and nothing loads until then, so the base page keeps its 200 KB budget and each skin gets its own (150 KB,
  font included).
- **Textures and sprites are original, hand-authored `<rect>` pixel art committed to the repo**, never a bitmap
  copied from anywhere. The block-building and farming looks the operator asked for by name are *inspirations
  named in the skin's `why`*; their fonts, tilesets and sprites are their owners' and do not ship. A test
  refuses any raster in a skin directory.
- The status contract from #150 is untouched: role, colour and glyph. A skin only **adds** — a status block in
  `voxel`, a crop stage in `farmstead` — and never replaces the glyph (HIG *Color*: never colour alone).
- `theme.check()` grows a composited form: a skin declares the effective panel it produces (glass over ground,
  the slab texture's mean) and text, `muted` and every status role are checked against *that*.
- HIG *Materials* and *Accessibility* are the fallbacks: `prefers-reduced-transparency` turns a translucent
  panel opaque, `prefers-reduced-motion` stops any animation a skin adds, and motion is off by default anyway —
  a moving field beside a terminal is the attention cost this epic exists to remove.
- One OFL-licensed pixel font at most per skin, subset to Latin, with its `LICENSE` beside it; nothing under 11
  points; text shadows and ink colours are tuned for the texture (the first `voxel` pass put body text on the
  stone tile and it did not read — the slab is two close greys for that reason).

## Slices

| # | Slice | Fixes | HIG sections | After |
|---|---|---|---|---|
| A #146 | the browser harness: a Playwright smoke on CI, Chromium only, dev-only, that loads each layout, focus mode and the selected-project sync across two pages — #133's missing acceptance criterion — plus the Windows laptop rows | nothing yet; every later slice lands with a browser test | — | — |
| B #147 | the run you are in: run boundaries in `fleet_snapshot()`, the current run's transcript, the state stamped with its age, earlier runs folded, the "not supervised" sentence, `desk.json` persistence of the selection | stale tiles | Feedback, Loading, Windows (state restoration) | A |
| C #148 | the chrome: a toolbar of three groups, a segmented layout picker that switches with `pushState` and no reload, one sidebar with four sections instead of four drawers, one inspector for the selected project, hit targets and focus rings | poor experience of the options | Toolbars, Segmented controls, Sidebars, Split views, Focus and selection, Typography, Accessibility | A |
| D #149 | the arrangement: drag to reorder, size toggle, pin, keyboard equivalents, per-layout arrangement in `desk.json`, shared through the `desk` event | tiles cannot move | Drag and drop, Layout, Windows | B, C |
| E #150 | one palette: `theme.css()`, `/api/themes` from `theme.py`, the choice from `config.json`, the tile accent per project, the status chips on the theme's checked map, a `theme` SSE event, the contrast check run on every rendered token pair | two theme systems | Color | #136, #139, C |
| G #154 | the skin tier: `theme.skin`, on-demand skin stylesheets as package data, the pixel-art and licence rules, the composited contrast check, reduced-transparency and reduced-motion fallbacks | two theme tiers with no line between them | Materials, Color, Accessibility | E |
| H #155 | `glass`: translucent panels over a ground washed in the projects' own accents; opaque under reduced transparency | — | Materials | G |
| I #156 | `voxel`: 8-pixel tiles, bevelled slab controls, a status block per role, a hotbar key map; original art in the spirit of a block-building game | — | Color, Accessibility | G |
| J #157 | `farmstead`: paper and wood, the state as a crop stage beside the chip; original art in the spirit of a pixel farming game; motion off by default | — | Color, Accessibility | G |
| F #151 | retire the layouts the sitting did not choose: once #133 records the decision, the default moves in the three places the test keeps in step, the unused two are removed a month later, and `docs/fleet-layouts.md` becomes the record | — | — | #133's decision, D |

## Ground rules (inherited from #91, #122 and #135)

1. **The page is a view.** Every state comes from the server; every button calls the function the CLI verb
   calls. The arrangement and the theme choice are server state for that reason.
2. **No framework, no build step, no CDN, no CSS framework.** Playwright is a `dev` extra for CI and the
   laptop; it is never a runtime dependency and the wheel does not change.
3. **Nothing is written outside `~/.agentdata/fleet/` and `~/.agentdata/config.json`.** `desk.json` is the
   first, the theme choice is the second, and `.agent/` stays the agent's.
4. **History is additive and never rewritten.** The current run is a *view* of the stream, not a new file.
5. **Status colours never change meaning.** `state → role` is one table in one place; the role's value is
   the theme's, checked in code. The glyph is always present.
6. **An agent never sees a theme.** Nothing here touches stdout; `ad-fleet status` stays TOON.
7. **The HIG is cited, not copied.** Each slice names the sections it applies and the Mac chrome it does not.
8. **Decided on the real screens.** This epic does not choose the layout; #133 does. Slice F waits for it.
9. **Every laptop failure becomes a named regression test**, with the host (Edge, JCEF, Simple Browser) in
   its name, the way #67 and #137 name terminals.

## Build order

#146 (harness) → #147 (the run) → #148 (chrome) → #149 (arrangement) → #150 (one palette, after #136 and #139
exist; #153's five palettes ride in with it) → #154 (the skin tier) → #155 `glass` → #156 `voxel` → #157
`farmstead` → #151 (after #133's sitting is written up, whenever that is). B and C are independent of each other once A is in; D needs both.

## Open questions, to be answered on the laptop and recorded in the slice

- Does Edge's `--app` window (chromeless, [fleet-ide.md](fleet-ide.md)) survive corporate policy, and does
  the toolbar need to grow a title when it does not? (C)
- Can the fleet see a Copilot session the operator started in a terminal — `copilot --headless --port` on
  1.0.83 per #92 — and if so, is attaching to it a supervisor verb? Until then the tile says *not
  supervised*. (B reports; #91 decides)
- Does JCEF honour `prefers-color-scheme` from PyCharm's own theme, or does the tool window need the theme
  told to it? (E; the same question #137 asks of JediTerm)
- Which of `grid`, `roles` and `screens` did the sitting choose? (#133, then F)
