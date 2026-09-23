# Plan: panes — one arrangement, every agent its own column, every column resizable

_Status: PLANNED (2026-09-22) — epic #229 (slices #230–#236), under #91 (the fleet) and #122 (the desk). Written from the
operator's sentences of 22 September 2026, recorded verbatim in §Decisions, and from three investigations run the
same day. Each investigation reproduced its finding before anything here was written: the snap-back in headless
Chromium with the repo's own browser helpers, and the stale questions against a scratch fleet driven by `ad-state`
in a subprocess. This plan **supersedes Decision 1 of [plan-column.md](plan-column.md)** ("a column of bands … not
side-by-side strips"), which the operator says was a misreading. It also **retires the arrangement spike of
[fleet-layouts.md](fleet-layouts.md)** a few weeks before that page's own one-month deadline, on the operator's word.
Every platform feature named below is measured in Edge, PyCharm's JCEF window and VS Code's Simple Browser before
it is relied on, as every desk plan since #145 has required._

## Why this exists

Six sentences, read against the code:

| What the operator says | What the code does | Section |
|---|---|---|
| *When I click on another agent, it automatically snaps back to the one I was previously on* | `applyWindow` runs on every `desk` frame (`app.js:1502–1504`) and every `/api/fleet` answer (`app.js:1450–1452`). When `win.zoomed !== focused` (`app.js:1296–1297`) it calls `focus(win.zoomed)`. In the column, `focus` is `openAgent` → `openBand` (`app.js:1570–1571`), and `focused` is never set there, so a non-empty `zoomed` wins on **every** frame. `zoomed` is written by the grid's zoom (`app.js:1583`) and cleared only by `backAgent` (`app.js:1596`), which the column cannot reach. Any zoom from before `column` became the default this morning is still in `desk.json` under `windows.main.zoomed`. A click on B posts `open: B`. Within one 0.4 s tick (`serve.py:59`) the frame comes back carrying `open: B, zoomed: A`, and the page opens A. Reproduced: A → B at 0.11 s → A at 0.33 s, while the server says `open: B` | §Slice A |
| *agents are retaining historical questions that have already been answered … showing that we have 12 questions, but all of them have been answered* | The tile's count is `row.asked` (`app.js:488–495`), folded from the event stream (`agentstate.py:95–111`) and never checked against `state.json`. A question leaves the fold only on `question_answered`, which only `ad-state answer` produces. `--clear-questions` deliberately emits nothing (`events.py:292–294`), and the skills tell agents to use it (`state-update/SKILL.md:12`). `friction-log` and `codebase-map` still ask with bare `--question` strings that have no id, so no route can answer them. A console or adopted session is one run for its whole life, so every question it ever cleared stays in that fold. Reproduced exactly: twelve ask-and-clear cycles in one console-style run read `needs_human · 12 questions` while `state.json` has `open_questions: []` | §Slice B |
| *I meant each agent is a column, not each agent is stacked in one column. I'm thinking skinnier agents* | Every agent that is not open is a `.band` in `#column` (`drawColumn` `app.js:4037`, `drawBand` `app.js:4109`). That column is `clamp(260px, 24vw, 420px)` wide, and its bands share its height (`app.css:904–1000`). A band is a second component, not a tile, and has no width of its own | §The pane |
| *we don't have the ability to resize the active or the inactive agents dynamically … theoretically have all of them be active at once* | #217's footprint is integer spans, `size = {cols 1–4, rows 1–3}` (`serve.py:1001–1041`), snapped to `auto-fit` tracks measured from the grid. Bands cannot be resized at all. There is no divider between panes anywhere, and a pixel or fractional width is not representable | §Resizing |
| *I don't really know what purpose "roles" and "screens" are serving anymore … we only really need the "grid" option* | [fleet-layouts.md](fleet-layouts.md) §The sitting records **no photograph and no minutes** for `screens`, and no minutes for `roles`. Four arrangements share one window record: the grid writes `zoomed`, the column writes `open`, roles writes `view` and screens writes `screen`. The snap-back above is two of them disagreeing inside that one record | §One arrangement |
| *maybe we don't need "Rust," but we need typescript/javascript* | The page already is JavaScript: `app.js` is 4 520 lines of hand-written ES5-style script with no build step. Neither defect above is a type error. Both are two sources of truth disagreeing | §Where this plan pushes back |

**The purpose is the same as #122's and #200's: the operator's attention.** A glance should say *where is everyone*
and *who needs me*, and a click should stay where it was put.

## Where this plan pushes back, and what it does instead

1. **TypeScript.** The instinct is right: the fix belongs in the page and the server, not in a new runtime. But
   TypeScript as a language means a compile step, and the page's first rule is that it has none. The files ship as
   package data from a `pip install` of a git URL and load in JCEF and Simple Browser behind the corporate proxy
   ([fleet-dashboard.md](fleet-dashboard.md) §Why a web page). A compile step means either committing generated
   JavaScript beside its source or making every laptop build the page. What TypeScript would actually add here is
   **checking**, and checking needs no build. Slice G therefore puts `// @ts-check` and JSDoc types on the new pane
   code and on the desk-sync path, and runs `tsc --noEmit --checkJs` in CI as a dev-only check. It uses Node, which
   CI already runs for `node --check`. The shipped page stays byte-for-byte what is in the repo. The types would not
   have caught either defect above. What catches those is one record per window and one version check (§The
   model), and the regression tests in A and B.
2. **"Only grid".** One arrangement: agreed, and the snap-back is the strongest argument for it. But what the operator
   describes is not today's grid either. Today's grid is wrapping cards with a zoom and a dock underneath, and
   today's column is one open tile beside a stack of bands. The target is a **row of panes**, one per agent, each at
   full height with a width of its own. The nearest code is the column's `main`, which already lays open and pinned
   tiles side by side at full height (`openSet`, `app.js:3825`). The grid's wrap, zoom and dock retire, and so do the
   column's bands. The word `grid` survives as the name of the one arrangement, because that is the operator's word
   for it. `?layout=` stops meaning anything.
3. **"All of them active at once"** works as far as the screen allows, and no further. A tile is readable from about
   360 px, which is today's grid minimum (`app.css:298–311`). On a 1 920 px window that is five full tiles, not
   twelve. So "active" becomes a **width**, not a mode: every pane draws itself by how wide it is (§The pane). "All
   active" then means "all compact" on a crowded screen: still answerable, never broken. Twelve 360 px tiles on one
   monitor is a scroll bar, and a desk that scrolls sideways hides the agent that needs you. That case is §Open
   questions, not a default.
4. **`screens` had one real job**: two monitors reading two different agents. That job survives without the
   arrangement, because **widths belong to the window** (#172's record). The left monitor can hold alpha wide and
   the right one beta, while both show the same agents in the same order.
5. **Pin retires.** In the column, *pinned* meant "stays open beside the open one" (`openSet`). A pane that stays
   wide because it was dragged wide is the same thing, drawn by the hand instead of a button. The head gets one
   control lighter, which is #200's stated aim. Order stays: `Alt+Home` still moves a pane first.

## What is reused

- **The column's `main`** and `openSet` (`app.js:3825`): full-height tiles side by side, split evenly, at least 320 px
  (`tests/test_fleet_column.py:310`). The row of panes is this, with every agent in it.
- **#217's gesture plumbing** ([desk-window.md](desk-window.md)): pointer capture on lift, listeners on the document,
  `.is-dragging` taking no pointer events, no reorder mid-drag, `Esc` cancels, and a key for every gesture. Its
  integer snap to measured `auto-fit` tracks does **not** carry over, because there are no tracks to measure in a row
  whose widths are the operator's.
- **#219's instant path** ([desk-instant.md](desk-instant.md)): `arrangeNow` paints first, writes once, rolls back on
  refusal and offers undo in the footer, with gestures under 50 ms. A width is an arrangement write like an order is.
- **The ownership contract** ([desk-components.md](desk-components.md)): created once and patched after, `setOwned`,
  listeners bound on create, `patchList`, no `innerHTML`, and an idempotent `place()`. The pane is **one** component
  where there were two (tile and band), so one owner per property gets easier to keep, not harder.
- **Motion** ([desk-motion.md](desk-motion.md)): FLIP for reorders, `transitionLayout` for a swap, durations of
  320 ms or less, and nothing under reduced motion. A gutter drag has no motion of its own, because the hand is the
  motion.
- **`mergeDesk`'s version check** (`app.js:2861`). It exists already and guards one path out of four. §The model makes
  it the only door.
- **`isHidden()`** (`app.js:2465–2469`), which never hides an agent that needs a person. **The dock's project grouping**
  (`app.js:2723–2733`), for the case where even rails do not fit.
- **The run boundary** (`started`, [plan-desk-refactor.md](plan-desk-refactor.md) §The run you are in) and
  **`lifecycle.answers_prompt`**, the "Answers to your questions" text that session-bootstrap step 5 already turns
  into `ad-state answer`.
- The browser harness (#146), the page globals the regression tests call, the shuffled suite, the engine rows (#220),
  and the regression convention in [testing-this-repo.md](testing-this-repo.md) §The regression convention.

## Prior art, and what is different here

- **VS Code's editor groups and sashes.** Side-by-side panes, a draggable divider between any two, double-click to
  even them out, and a minimum width below which a group refuses to shrink. That is §Resizing almost exactly. The
  difference is that an editor group hides when it is too narrow, while a pane keeps saying who it is and whether
  it needs you (the rail).
- **Scrollable tiling window managers** (PaperWM, niri): one row of full-height columns, each with its own width, and
  focus moves along the row. What is different: the row fits the window unless even the rails cannot fit (§Open
  questions), because sideways scrolling is how an agent that needs you ends up off the glass.
- **Stage Manager** was plan-column's reference, and the swap on click keeps its muscle memory (§Resizing, *click a
  rail*). What changes is that the stack stands up: it becomes rails side by side, not bands on top of each other.

## The model: one record per window, one arrangement per desk

```
~/.agentdata/fleet/desk.json            schema: 2
  version                               the only-ever-rising counter every write bumps (unchanged)
  arrangement:  { order: [repo…], hidden: [repo…] }       one desk: shared by every window
  windows:
    <w>:  { open: repo,                                    the one pane the keys and the composer address
            widths: { repo: 0 | weight },                  0 = rail; weight = its share of what the rails leave
            read, seen, held, section }                    unchanged (#172)
```

- **`open` alone; `zoomed` goes.** Two fields that could disagree become one that cannot. That is the snap-back
  removed by construction, not patched. (An earlier draft named the survivor `focus`, but that name already means
  the needs-only filter on the window record, `applyWindow`'s `win.focus`. Found while building A.)
- **Widths are per window.** A laptop and a 4K monitor cannot share pixels, and §Where this plan pushes back item 4
  needs them apart. Order and hidden stay shared, because one desk means the same agents in the same order on every
  screen.
- **A weight, not pixels.** Resizing the window scales the wide panes and leaves the rails alone. `{alpha: 2, beta: 1}`
  means alpha gets two thirds of whatever the rails leave.
- **One door in.** Every desk payload the page receives goes through one function, `acceptDesk(payload)`: the SSE
  frame, the `/api/fleet` answer, the 15 s `loadDesk` and an action's own answer. It drops anything whose `version`
  is lower than the page's. Today three of those four paths replace `desk.desk` wholesale with no check
  (`app.js:1450`, `1502`, `2442`). One of the investigation's reproductions showed a delayed `/api/fleet` answer
  rolling the version back from 5 to 3.
- **A window is named for its host.** Every window with no `?w=` shares the `main` record today (`app.js:33`), so the
  PyCharm tool window and an Edge window follow each other's clicks. The shells ask for their own names:
  `/open?w=pycharm`, `/open?w=vscode`, and `/open?w=edge` from `ad-fleet open --in edge`. A plain browser tab stays
  `main`.
- **Migration** runs once, at load, and first keeps the old file as `desk.v1.json`. The order and hidden list come
  from `column` if that key exists, else from `grid`, because `ad-fleet hide` wrote to `grid` whatever the page
  showed (`cli_fleet.py:229`, `1530`). Each window keeps `open`, and `zoomed` is dropped. Widths start
  as the focused pane and every pinned pane at weight 1, and everything else at 0, which is today's column exactly.
  `size.cols` becomes the weight of any pane that was wider than one column. `layout`, `view`, `screen`,
  `screens` and `selected` go. `selected` goes only once C's inventory shows nothing but roles reads it.

## The pane: one component, three widths

Every agent is a `.tile`, always. What it draws is decided by its own width, in three tiers:

| Tier | Width | What the pane shows |
|---|---|---|
| **rail** | 48 px, fixed | the name set vertically, the state's glyph and colour (never colour alone), the unread count; the whole rail red when the agent needs a person; the age and last line in its `aria-label` and title |
| **compact** | 160 – 359 px | the head (name, state chip with age, ticket), the three tools (hide, refresh, model), the ask card with its answer box, the last lines of the transcript, the reply box |
| **full** | 360 px and up | everything a tile has today |

- **The tier is set in one place.** One `ResizeObserver` on the row writes `data-tier` on each pane, with 8 px of
  hysteresis so a pane at the boundary does not flicker between tiers. CSS keys on `[data-tier]`, and the draw
  functions skip what a tier does not show: a rail does not render a transcript. Container queries would do the CSS
  half. They are measured in F and used only if all three engines run them, and the attribute stays either way,
  because tests and draw code can read an attribute and cannot read a container query.
- **The numbers are starting values.** 360 is the grid's minimum today, and 48 is a 28 pt hit target plus padding. The
  laptop sets them in F.
- **A band is not drawn any more.** `drawColumn`, `drawBand` and `#column` retire, and a compact pane carries
  everything a band did (plan-column §The band). Hide, refresh and the model stay the same three buttons with the
  same keys (#205).
- **Hidden** leaves the row. The footer reads `2 hidden`, and a click brings them back. `isHidden()` keeps its rule:
  an agent that needs a person is on the glass whatever the arrangement says.

## Resizing

- **A gutter between every two panes.** A 1 px line with an 8 px hit area that overlaps the panes, so it costs no
  width. Dragging it moves width between **those two panes only**, and every other pane stays exactly where it is.
  That is the rule that makes a resize predictable.
- **Snaps while dragging**: the rail (below 120 px the pane settles to 48), the compact minimum, the full minimum, and
  an equal share with its neighbour. The drag itself is the preview. #217's ghost was needed because a span snaps
  on release and the hand could not see where it would land. A splitter draws the real layout under the hand, one
  `grid-template-columns` write per animation frame and nothing else: no `place()` and no redraw mid-drag. #217's
  "a draw in the middle of a drag no longer puts the gesture down" is the lesson this rule follows.
- **One write per gesture**, on release, through the instant path. That means optimistic, undo in the footer, and
  `Esc` mid-drag puts the widths back with nothing written.
- **Click a rail** and it takes the width of the pane you were on, which becomes a rail. This is today's column swap,
  so the gesture the operator already knows still works. **Shift-click** a rail opens it beside the focused pane,
  splitting that pane's width, which is how "two active" happens without a drag. **Double-click a gutter** evens out
  the two panes beside it.
- **Three presets**, in the header where the layout picker was, as one segmented control:

  | Preset | Key | Widths |
  |---|---|---|
  | **one** | `1` | the focused pane wide, every other a rail |
  | **all** | `=` | every visible pane an equal share. The tiers decide what that looks like on this screen |
  | **needs me** | `f` | every pane that needs a person compact or wider, everything else a rail. This replaces the needs-only filter and hides nothing (#207's second focus) |

  A preset is one arrangement write and can be undone like any other.
- **Keys.** `←` / `→` (and `j` / `k`) move focus along the row. `Alt+←` / `Alt+→` move the focused pane one slot, as
  today. `Alt+Shift+←` / `Alt+Shift+→` move its right gutter one step, as today's width keys do. `Enter` takes the
  focused rail wide, as in the swap. `h` hides.
- **Reduced motion**: the swap and the presets apply at once, and the gutter drag is unchanged because it was never an
  animation.

## One arrangement

- `LAYOUTS` goes (`app.js:24`, `serve.py:126`, `cli_fleet.py:632`), with it `VIEW`, `SCREEN`, the swap control, the
  four-segment picker, the `layout-*` body classes and every `LAYOUT === …` branch. The inventory counts about 40
  sites in `app.js` alone.
- A URL carrying `?layout=`, `&view=` or `&screen=` from a bookmark or an old launcher opens the desk with the
  parameter ignored and says so once in the footer. It never lands on a blank page. `ad-fleet serve --layout` and
  `ad-fleet hide --layout` are still accepted for one release, ignored, with a `note` in their `meta`, and then
  removed.
- [fleet-layouts.md](fleet-layouts.md) becomes the page that records the decision and the one arrangement, and its
  §The sitting keeps its history. [fleet-dashboard.md](fleet-dashboard.md) (lines 241–262), which still says grid is the
  default, is corrected in the same slice.

## The questions a tile shows

- **`state.json` is the record of what is open. The stream is the record of what happened.** The snapshot shows the
  questions in `state.json`'s `open_questions`, in the order and with the payload the fold has for them. It shows none
  that `state.json` has closed, however they were closed. This also heals every tile already stuck, with no new
  event needed. It does **not** add back a question `state.json` lists but the current run never opened. That
  is usually the one the operator has just answered from the tile, in the turn that records the answer, and
  drawing it again with an empty box asks them to answer it twice (#169). Found while building B.
- **A cleared question says so.** `events._question_events` emits `question_cleared {id, question}` for a key that
  left `open_questions` without reaching `answered_questions`. It is not an answer, so the existing test that
  "disappeared is not answered" holds. The fold treats it the way it treats `question_answered`, and rebuilds
  `Fold.questions` from `Fold.asked` after every question event, so the fallback text in `blocking_questions`
  (`agentstate.py:144`) can never outlive its record. The new kind is added to `KINDS` and to
  [fleet-events.md](fleet-events.md).
- **Every question has an id.** `friction-log` and `codebase-map` ask with `ad-state ask`, not
  `set --question`. `ad-state` normalises a bare string it finds into a record with an id when it next writes. That
  is the "strings normalised" step of [plan-handoff.md](plan-handoff.md) (line 341), which was never built.
- **Ids only ever rise.** `next_question_id` consults the open and answered lists (`state.py:71–78`), so a cleared
  `q1` frees `q1` for the next question. A `question_seq` in `state.json`, written by `ad-state` and nothing else,
  makes ids strictly increasing.
- **The answer card works on a console.** On a console or adopted row the card posts `answer`, which calls
  `supervisor.send`, which refuses a session the fleet did not start (`supervisor.py:510–517`). So the operator
  answers in the chat, the agent clears, and the tile keeps counting. On such a row the card sends the same
  `lifecycle.answers_prompt` text through `say` (`console.say_into`), the path the reply box already uses. Session
  bootstrap step 5 turns that text into `ad-state answer`, so the answer is recorded by the agent's own writer.

## Slices

### A #230 — the snap-back: one door for the desk, and a window named for its host

Ships alone, first, before any layout work. It is the defect the operator hits every minute.

- `applyWindow` ignores `zoomed` in the column. It is **not** cleared from the page: a grid window on the same
  record may be zoomed on purpose, and a test caught the clear un-zooming it. C removes the field.
- A window's own writes go one at a time, in the order they were made. Four opens in one frame reached the server
  in any order, and the record ended on the wrong agent. `test_fleet_motion.py` found this under parallel load.
- `acceptDesk(payload)` replaces the three unguarded assignments (`app.js:1450`, `1502`, `2442`) and drops anything
  older than the page's `version`.
- `openBand` and `backToPrevious` keep `#tile=` in step (`history.replaceState`), as `openAgent` does, so a reload
  cannot reopen the agent from before the click.
- The shells ask for `w=pycharm` and `w=vscode`. (`ad-fleet open --in edge` already takes `--window`; its default
  moves to `edge` with C.)
- **Tests**, browser, in `tests/test_fleet_column.py`:
  - a seeded `zoomed: alpha`, a click on beta, a wait of three ticks, then beta open on the page **and** `open: beta`
    on the server;
  - the same, with a second page on `layout=grid` zooming gamma;
  - `#tile=gamma`, a click on beta, a reload, and beta still open;
  - a delayed `/api/fleet` answer that does not roll `version` back;
  - four opens in one frame leaving the record on the last one.

  The operator's report became `tests/regressions/test_20260922_any_chrome_snapback.py`. The convention's name
  pattern allows a shell, not a browser, so the host is in the short name. **Built in #237.**

### B #231 — the questions: `state.json` decides what is open, and every close says so

- The snapshot reconciles against `state.json`. `question_cleared` is added. `Fold.questions` is rebuilt from
  `Fold.asked`. `question_seq` is added. Bare strings are normalised. The two skills move to `ad-state ask`. The
  console card routes through `say`.
- **Tests**, in `tests/test_fleet_handoff_ask.py` and `tests/test_state.py`:
  - ask, clear, then a fold after `turn_ended` that reads idle with 0 questions;
  - twelve bare `--question` ask-and-clear cycles in one console run, reading 0 (the operator's 12);
  - a cleared `q1` followed by a new ask that gets `q2`;
  - a console-row answer that reaches `say_into` with the answers prompt.

  The regression file for the 12 is `tests/regressions/test_20260922_any_answered_questions.py`. **Built in #237.**

### C #232 — one arrangement: `LAYOUTS` goes, `desk.json` schema 2, the migration

- Everything in §One arrangement and the migration in §The model. `open` stays and `zoomed` goes. The grid's
  zoom and dock and the column's bands are **not yet** removed, because D replaces them. C leaves the column's
  drawing as the one arrangement and deletes the other three.
- **Tests**: 4 roles/screens tests deleted (`test_fleet_board_desk.py:470, 607, 750`,
  `test_fleet_desk_regressions.py:321`), 18 rewritten (the inventory lists them), and the fixtures lose their
  `roles`/`screens` keys (14 files) and their `"screens": []` (24). The migration gets its own test from a real v1 file with a stale `zoomed`,
  a `grid`-only hidden list, pins and a `size.cols` of 2. `?layout=roles&view=board` opens the desk and says so
  once.

### D #233 — every agent a pane: the row, the three tiers, the band retired

- The row, `data-tier`, the rail's and compact tier's drawing, hidden in the footer, and `drawColumn`/`drawBand`/
  `#column` removed. The swap on click, still at today's widths, because resizing is E.
- **Tests**: the fixture desk with 3, 6 and 12 agents at 1 280, 1 920 and 2 560 px, asserting no horizontal scroll,
  each pane's tier, the red rail's colour and glyph, and an `aria-label` on every rail. The inventory in
  [desk-components.md](desk-components.md) loses *band* and gains *pane (rail, compact, full)*. A `MutationObserver`
  reads zero on an idle desk (ownership's proof).
- **Built (#233).** What building it decided, each undone by a sentence from the operator:
  - *Today's widths* are the migration's: the open pane and every pin share what the rails leave, by
    `size.cols` as a `flex-grow` weight, never under 160 px; everything else is a 48 px rail. A compact pane
    therefore appears when pins crowd the open one, or on a narrow window.
  - A pane is a rail until its tier is written: the draw skips the trace, cells, session menu and cards until
    the observer's first report, which lands before the first paint and draws the pane again at its width.
  - The compact tier also shows the **approval** card beside the question card, because both are the pane
    asking the operator something and neither should need a widen to answer; its reply row keeps Send and
    drops Start, Reset and Stop.
  - The rail's label carries the spend and the unread count as well as the age and the last line, because the
    band's chip carried the spend and a rail has nowhere else to say it.
  - The digits count **every** pane on the glass, the open one included, so a number never changes because
    another pane was opened; `j`/`k` walk the same stops.
  - *needs me* dims a quiet rail where it folded a band; it never quiets an open pane, and a toast's anchor no
    longer turns the mode off to reach a pane, because nothing is ever off the glass for it.
  - A reorder never changes which agent is open: with nothing opened yet, the open agent is only "the first in
    the order", and a rail can now be dropped before it, so `holdOpen()` writes it down first. Found while
    porting the column's drag test.
  - A repository that leaves the registry is a dashed rail after the row, not inside it, so the row holds
    panes and nothing else.
  - The column's head (*N others · M need you* and *go to the first*) went: the footer already counts who needs
    you, and a red rail is never off the glass to be jumped to.
  - Grouping triggers when the open panes at 160 px and every rail at 48 px would not fit the row; past that
    the row scrolls, the last resort §Open questions allows.

### E #234 — resizing: gutters, snaps, the three presets, and widths per window

- Everything in §Resizing. `POST /api/window {widths}` with the version check. The width keys move from spans to
  gutter steps. #217's `size` and `#rszghost` are removed. `.rsz-y` goes too: a pane is always full height, so there
  is no row to resize.
- **Tests**: a gutter drag moving width between exactly two panes; the snaps; `Esc` mid-drag writing nothing; one
  POST per gesture; undo; each preset; two windows holding different widths over the same order; frame time during a
  drag inside the existing budget (#220); every gesture done again from the keyboard.

### F #235 — proof: the engine rows, the numbers on the laptop, the docs

- Engine rows for `ResizeObserver`, container queries and pointer capture on the gutter in JCEF, Simple Browser and
  Edge. The laptop's tier thresholds, recorded beside CI's. [desk-window.md](desk-window.md) rewritten for panes and
  gutters, [fleet-layouts.md](fleet-layouts.md) closed. Plan-column's Decision 1 already links here.

### G #236 — types without a build

- A dev-only `tsconfig.json` at the repo root (`allowJs`, `checkJs`, `noEmit`, `strict` off to begin with), and
  `// @ts-check` with JSDoc typedefs for the desk record, the window record and a pane. It covers the files D and E
  create and the desk-sync path A touches, not all 4 520 lines on day one. `tsc --noEmit` runs in the existing CI
  Linux job, next to `node --check`. The page, its bytes and its no-build rule do not change. Widening the check to
  the rest of `app.js` is a follow-up that only this slice's own number can justify: how many real defects the
  check found in the typed part.

## Ground rules

1. **No framework, no build step, no CDN**, `innerHTML` still banned, and the payload budget holds. G checks and
   never compiles.
2. **One record per window, one door in.** No field may be written by one arrangement and read by another, because
   that is the snap-back. Every desk payload passes the version check.
3. **`state.json` is what is open.** No count on the desk comes from a fold alone.
4. **A drag draws nothing but widths.** No `place()`, no redraw and no reorder while a gutter is held.
5. **Every gesture has a key, and `Esc` cancels.**
6. **Nothing needing a person is ever off the glass.** Hidden, rail or preset, the red wins.
7. **Regression first.** A and B land their failing test before their fix.

## Build order

A, then B, both as soon as possible and independent of the rest. C after A, because C rewrites the record A guards.
D after C. E after D. F alongside E. G can start with D, on D's new files.

## Open questions, to be answered on the laptop and recorded in the slice

- ~~Which host were the snap-back and the 12 questions seen in?~~ **Answered:** Chrome, opened by
  `ad-fleet serve --open`, so one `main` window. The first cause, a stale `zoomed`, is enough on its own. (A, B)
- When even the rails do not fit (about 30 agents on a 1 440 px window), should a project's checkouts share one rail,
  as the dock grouped them, or should the row scroll with a red count at each edge? Default: group. (D)
  **D ships the default**; the laptop answers it (P8 in [windows-verification.md](windows-verification.md)).
- Are 48 / 160 / 360 px the right tier boundaries on the real monitors? (F)
- Should a click on a rail swap, as today, or open beside with swap on Shift? Default: swap, because it is the
  gesture the operator already has. (E)
- Should **all** be the default preset on a wide monitor and **one** on the laptop panel, with the window's width
  choosing? Default: no, the window keeps what it was last given. (E)

## Cost

No premium request anywhere. A and B are small and mostly Python on B's side. C is a net deletion. D replaces one
component with a variant of another. E is the largest slice, and it is where most of the new code is. G adds one dev
dependency (`typescript`, in the CI job only), which the VS Code shell's `package.json` already carries. CI time
rises by the fixture desk's nine screenshots and the drag traces, bounded to the browser job.

## Decisions — the operator's, 22 September 2026, recorded here so no code concludes what it did not

Their sentences, verbatim:

1. *"When I click on another agent, it automatically snaps back to the one I was previously on."*
2. *"Agents are retaining historical questions that have already been answered and presenting them as if they haven't
   been answered. One of our agents in fleet is showing that we have 12 questions, but all of them have been
   answered."*
3. *"When I said the inactive agents are taking up the rest of the space as columns, I meant each agent is a column,
   not each agent is stacked in one column. I'm thinking skinnier agents."* This supersedes
   [plan-column.md](plan-column.md) §Decisions 1.
4. *"We don't have the ability to resize the active or the inactive agents dynamically. This would be a major
   improvement for us because it could enable us to theoretically have all of them be active at once."*
5. *"I don't really know what purpose 'roles' and 'screens' are serving anymore. It almost feels like we only really
   need the 'grid' option, and just that its design features need to be hardened."*
6. *"All of these suggests that maybe we don't need 'Rust,' but we need typescript/javascript."* Answered in §Where this
   plan pushes back, item 1. Nothing in this plan concludes it beyond G.

What they asked for and did not decide is in §Open questions. The pushbacks in §Where this plan pushes back are
proposals, and each one is undone by a sentence from the operator.
