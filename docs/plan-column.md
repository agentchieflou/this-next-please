# Plan: the column — one tile open, every other session a band in a column that fills the page

_Status: IMPLEMENTED (2026-09-22) — epic #200 (slices #203–#208), under #91 (the fleet) and #122 (the desk), a
sibling of #145, #162, #170, #179 and #187, and one of three plans written from the same photograph: this one, the
meter ([plan-meter.md](plan-meter.md), #201) and ownership ([plan-ownership.md](plan-ownership.md), #202). Written from
one phone photograph of the desk in use, taken 22 September 2026 in Chrome on the laptop, and from the operator's
sentences about it — the ones that are decisions are recorded verbatim in §Decisions, and this plan does not
conclude anything they did not. Every claim below is to be measured on the same screens, in Edge, PyCharm's JCEF
window and VS Code's Simple Browser, the way #145's and #179's were._

## Why this exists

The desk ran with five agents on real tickets and the operator sent one photograph and six sentences. The photograph:
one tile open at the left third of the window — an adopted console session, a turn in progress, an amber git cell
reading *7 branches · 5 never reached master*, tool calls scrolling; the other two thirds of the window black but for
four dock chips, each a full-width bar because its ask text is long, under a label reading *4 not on the glass* and
above a *show all* button; the footer reading *5 agents · 3 need you*. Read against the code, the sentences are five
findings, each with a line that causes it:

| What the operator says | What the code does | Section |
|---|---|---|
| *I would much rather prefer non-open sessions to show vertically rather than horizontally* | the sessions that are not open are the **dock** (#173): pills in a wrapping row (`app.css:862–870`, `flex-wrap: wrap` twice). Its comment and its `border-top` say it *sits under the grid* (`app.css:858–860`), but `.workspace` is a flex **row** (`app.css:244`) and `.dock` has no `flex` rule, so it is laid out *beside* the grid with a basis of its own content — and a chip carrying a long ask widens the dock at the grid's expense. In the photograph the one open tile is a third of the window and the dock's four chips have the rest | §The arrangement |
| *Each slice that isn't being actively looked at should auto size to take up the page so there isn't so much negative space* | nothing on the page sizes to the viewport: `main` is `repeat(auto-fit, minmax(360px, 1fr))` with `align-content: start` (`app.css:275–283`), a tile is `min-height: 240px; max-height: 60vh` (`app.css:292`), and `grid-auto-rows` appears nowhere. `body { height: 100vh }` (`app.css:48`) is the only viewport anchor, and it scrolls `main`. Two tiles on a tall monitor leave the lower sixty percent empty; four chips leave two thirds black | §The arrangement |
| *we'll need buttons to hide, refresh, and check current model settings for each agent (active and inactive both need these buttons)* | the tile's header has pin, hide and width (`index.html:230–241`) and no refresh; the model is on no tile — the `/api/fleet` row carries no `model`, `effort` or `model_source` (`serve.py:451–484`) and `app.js` renders none (its three `model` hits are comments); the settings page alone shows it (`settings.html:52–56`, #199). A dock chip has **no buttons at all**: one click reopens (`app.js:2746–2755`), and it carries the ask text only when its agent is red (`app.js:2747–2751`, asserted by `tests/test_fleet_desk_hide.py:284–316`) — an idle hidden agent's last question is unrecoverable from the dock | §The band, §The buttons |
| *The bar with main, earlier, new, and console is a little clunky … it is not intuitive what I'm supposed to do with all of these buttons* | the strip (`drawStrip`, `app.js:727–763`; markup `index.html:249–260`) is four tabs of three different kinds: a label that is not a tab (*main* — its click is `backToLive()`), a list opener (*earlier (n)* → `GET /api/sessions`), and two verbs (*+ new* → `POST /api/start {new}`, *console* → `POST /api/console`). Under it, `earlier runs (25)` (`index.html:351–354`) is a second *earlier* whose rows are inert text (`app.js:668–674`). The same tile reads `6d` in its chip (`ageChip`, `app.js:98–104`) and `160h` in its tab (`age`, `app.js:87–92`). The strip is torn down and rebuilt on every `/api/fleet` answer (`app.js:746–756`) | §One session control |
| *it almost feels like information overload … minimalist interface navigation so that a user isn't overwhelmed* | a tile is twenty controls in DOM order (§What is reused lists them); the toolbar's *focus* is `focusMode()` (`app.js:3000`, the needs-only filter) while *back to grid* is `unfocus()` (`app.js:1143`), which exits `focus()` (`app.js:1127`, the zoom) — two modes named alike, and the button undoes the other one; the `[hidden]` rule, `.is-hidden`, `body.focused`, `body.needs-only` and `body.solo` are five ways a tile leaves the glass (`app.css:39, 284, 642, 676, 861`) | §The two focuses |

**The purpose is the same as #122's, #145's, #162's, #170's and #179's: the human's attention.** Three questions a
glance should answer, and today the photograph answers one of them with a black rectangle: *where is everyone*,
*what does this one need from me*, *what is it running on*.

## What is reused

- **The arrangement** in `desk.json` (#149, #173): `order`, `size`, `pinned`, `hidden` per layout; `visibleOrder()`
  (`app.js:2471`), `isHidden()` (`app.js:2465–2469`, which never hides an agent that needs a person whatever the
  arrangement says), `setHidden()` → `POST /api/arrange` (`app.js:2485–2494`). The column is one more arrangement
  over the same record, not a second record.
- **The dock's rows** — `drawDock()` (`app.js:2692–2770`): the grouping of a project's checkouts into one chip by
  `project + why` (`app.js:2723–2733`), the `departed` map for a repository that left the registry (`app.js:2690`,
  `1026–1035`) and its `ad-fleet repo add <path>` title, the unread badge summed per group. The band is that row,
  drawn taller.
- **`#tile=<repo>`** — `followHash()` (`app.js:1155–1176`): reopens a hidden tile and says so in the footer, says
  *no tile for 'x'* for an unregistered one. In the column an anchor opens the band's tile.
- **`place()`** (`app.js:2776–2814`) as the one layout pass, and [fleet-layouts.md](fleet-layouts.md) §Constraints:
  every arrangement is body classes over one stylesheet. The column adds `layout-column` and nothing else to the DOM
  that the dock did not already hold.
- **The tile template** (`<template id="tile">`, `index.html:220–366`) and its twenty controls, in order: the head
  (grip, number, name, state chip with age, ticket, badge, pin, hide, width), the run line, the strip, the sessions
  list, the hold note, the outside strip, the why line, the scope report, the dispatch slot, the scope card, the
  cells, the approval card, the asks card, the assumptions, the transcript, the history, the read-only bar, earlier
  runs, the composer (Send, Start, Reset, Stop), the error line. Every one keeps its handler; this plan moves four
  of them behind one control and adds two.
- **The window record** (#172): `/api/window`, `applyWindow()` (`app.js:962–969`), `held`, `seen`. Which tile a
  window has open is one more field on it.
- **`served_model`**, **`settings_snapshot`** and **`set_model`** (#199; `serve.py:2109–2165`, `settings.py:180–205`),
  `check_model_value` (`launch.py:198–220`), and the settings page's own model row (`settings.js:174–213`). The model
  card on a tile writes the key the settings page writes and refuses what it refuses.
- **`events.refresh`** (`events.py:597`) and the poll cells (`poll.read_git`, `poll.py:628`; `poll.settings`,
  `poll.py:151`): a refresh button calls what the tick calls, now.
- **The HIG**, cited the way #145 and #179 cite it: *Sidebars / Split views* (auxiliary content the main content sits
  beside, remembering its width), *Pop-up buttons* (a long list behind one control), *Toolbars* (commands for the
  current context, nothing else), *Focus and selection* (exactly one selection, unmistakable).
- The browser harness (#146), the page globals `tests/test_fleet_desk_regressions.py` calls, the shuffled suite,
  the regression convention in [testing-this-repo.md](testing-this-repo.md) §The regression convention, and the
  laptop runbook's rule that every failure becomes a test named for its host.
- The reduced-motion block (`app.css:697–703`) — any movement the column introduces is under it by construction;
  the motion itself is [plan-ownership.md](plan-ownership.md) §Motion.

## Prior art, and what is different here

- **Vertical tabs** (Edge, 2021; Firefox, 2025) are the operator's sentence made literal: a tab strip turned on its
  side so every title is readable and a tab grows when there are few. What is different: a band is not a tab —
  it carries the agent's state, its age, its last line and three buttons, and it is red when the agent needs a person.
- **Stage Manager** (macOS 13): one window at work, the others as a stack at the side that is always visible and
  sized to fit, and a click swaps them. The column is that stack, and the swap is the one motion this plan asks
  [plan-ownership.md](plan-ownership.md) for.
- **A chat client's conversation list**: newest or loudest first, unread counts, one open. What is different: the
  order is the operator's arrangement, and nothing reorders itself — see §Open questions for the one exception.
- **The dock** (#173) is the thing the column replaces in this arrangement. Its rules travel: never hide what needs a
  person; a chip knows why its tile left and undoes the right thing; a project's checkouts leave and return as one;
  a departed repository says so. Grid, roles and screens keep the dock as it is.

## The arrangement: `column`

```
window
  open tile   (one; or every pinned tile, side by side)   the transcript, the composer, the cards — full height
  column      (every checkout that is not open)           one band per checkout, sharing the column's full height
    band      name · state chip · age · the last line · hide · refresh · model · unread
```

- **`?layout=column`** — `body.layout-column`. `main` holds the open tile(s) at `grid-template-columns: 1fr` (or one
  column per pinned tile); the tile drops its `max-height` and its transcript takes the remaining height
  (`flex: 1 1 auto; min-height: 0`), so the open tile fills the page too. `#column` is the dock's element with the
  dock's data, given `flex: 0 0 clamp(280px, 24vw, 440px)` — the sidebar's own width rule (`app.css:246`) — and
  `flex-direction: column`. In this arrangement the dock is not drawn: one thing, not two.
- **Sizing is the operator's sentence, made a rule**: every band is `flex: 1 1 0` with a minimum, so N bands share
  the column's whole height and none of it is empty. The minimum is by content: a quiet band (name, chip, age, one
  line) is 56 px; a band whose agent needs a person is the height of its ask, in full, never clipped. When N bands'
  minimums exceed the column, the column scrolls and its head says so (`12 sessions · 3 need you`). A window with
  one checkout has no column, and its one tile fills the page.
- **Which tile is open** is the window's — one more field on the window record (#172), defaulting to the selected
  project, so the left monitor can read one agent while the centre reads another; `selected` stays shared and stays
  what the inspector shows. Clicking a band opens its tile and the tile that was open becomes a band in its slot.
  A pinned tile is always open: pins split `main` evenly, which is what pinning meant in the grid too.
- **Hidden** is the same set (`arrangement.column.hidden`): a hidden checkout leaves the column as it leaves the
  grid, and the column's foot counts it — `2 hidden · show all` — so a band never disappears without a number.
- **Under 900 px** the column lies down: the same bands as a horizontal strip above the tile, one line each, which
  is the dock as it was meant to be and the laptop's narrow view.
- **Grid, roles and screens stay reachable by URL**, unchanged; the default moves to `column` in the three places the
  test keeps in step (`LAYOUTS[0]` in `cli_fleet.py:540`, `serve.py:123`, `app.js:22`) — §Decisions records why
  this plan may do what [fleet-layouts.md](fleet-layouts.md) forbids an agent to do on its own.
- **Keys**: `1`–`9` open the Nth band in the visible order (today they zoom the Nth tile — the same gesture, one
  arrangement further); `j`/`k` move along the column, `Enter` opens, `h` hides, `r` refreshes, `m` opens the model
  card; `Esc` returns to the previously open tile. Every key is in [fleet-dashboard.md](fleet-dashboard.md) §Keyboard
  and every gesture has one.

## The band

In DOM order: the number (its key), the name (or the project's name with `· 2 checkouts`), the state chip with its
age in **one** formatter (`6d`, not `160h`), the **last line**, the three buttons, the unread badge.

The last line is the answer to *what does this one need from me* and it is on **every** band, not only red ones:
the agent's `why` when it needs a person (the question, the refused tool, the blocking sentence), else the first
eighty characters of the last assistant line, else `state · age`. Today the chip carries the why only when red
(`app.js:2747–2751`); an idle agent that asked something an hour ago and gave up is invisible in the dock, and the
photograph's *idle · 3m* chip is that agent.

A band whose agent needs a person is red the way its tile and its chip are (`app.css:880`), chimes the way they
would, and shows its ask in full. It **keeps its slot** in the arrangement — nothing reorders itself under the
operator's hand — and the column's head reads `3 need you` with a jump to the first. §Open questions names the
alternative.

A band for a repository that left the registry is dashed and offers the `ad-fleet repo add <path>` that brings it
back (`app.js:2757–2758`), exactly as its chip did.

## The buttons, on the band and on the tile

The same three, in the same order, with the same keys, on both — the operator's sentence is *active and inactive
both*, and a control that exists in one place and not the other is the thing this plan is asked to stop doing.

- **hide** — the eye (`index.html:234–237`), `setHidden(repo, true)`, unchanged. On a band it hides the band; the
  foot counts it.
- **refresh** — `POST /api/refresh {repo}`: the server runs `events.refresh(name, path)` and this repository's poll
  cells (`ticket`, `pr`, `refresh`, `git`) now, re-reads `served_model`, and answers the fresh row. It **spends no
  premium request** — nothing is sent to the agent, and a test counts `send` events to prove it. A press inside two
  seconds of the last is refused with `refresh_busy` and the button says so; the icon turns for the request's
  duration only, and under reduced motion it does not turn, it says *…*. §Decisions records that this is what
  *refresh* means.
- **model** — a button reading the short model name (`opus-5`; `auto` when no flag is passed) that opens a card on
  the tile or the band, the settings page's row said in one place:

  ```
  configured   claude-opus-5           fleet.models.rdsd-pbi-reporting
  last turn    claude-haiku-4.5        the tenant pinned it
  Copilot    (inherit)  (auto)
  Anthropic  (✓ opus-5)  (sonnet-5)  (haiku-4.5) …        other…
  effort     (default)  (low)  (medium)  (✓ high) …
  saved — reaches the agent on its next turn               all models · settings
  ```

  Since #366 the model and the effort are each **one press** on the shared picker (`picker.js`, #362) over the
  list the installed CLI offers (`/api/models`, #361): no text box but `other…`, and no save button. A press posts
  the `settings` action with `models: [{repo, model, effort}]` — the key the settings page writes
  (`settings.set_model`), with the same refusals (`bad_model`, `no_repo`) in the same words. `inherit` removes the
  whole entry; an effort pressed while inheriting pins the inherited model and says so; a name the CLI does not
  offer is saved with a warning. `m` opens it from a rail, every key but `Esc` stays in the card, and `Esc` gives
  the keyboard back to where it was. *all models · settings* is `q("/settings")` anchored at the row. The card
  needs `model`, `effort`, `model_source` and `actual` on the `/api/fleet` row, which [plan-meter.md](plan-meter.md)
  slice C adds; §Build order says which lands first.

## One session control

The strip's four tabs become **one pill** under the head, reading what the run line and the main tab read between
them: `session · running · 6d`; `console · running · 6d` when a console holds the tile (`el.dataset.console`);
`earlier session · ended blocked · Tue` while reading history. Pressing it opens one menu (the `.popover` component
#180 built, not a new one):

```
this session                       ← back to live (backToLive)
earlier  (3)
  RDSD-118 · ended blocked · Tue · 4.3 premium      open · resume here
  RDSD-112 · finished · Mon · 1.0 premium           open
+ new session                Alt+N
open in a console            (or: show console)
2 checkouts ›                (sibling tabs, #175, when there are any)
```

*earlier runs (25)* folds into the same list: a run is shown under its session, so there is one *earlier* and not
two adjacent ones with different behaviour (`index.html:254` vs `:351`). *Resume here* keeps its refusal and its
deliberate second press (`app.js:863–882`); *open* never spawns anything (`tests/test_fleet_desk_switcher.py:229–276`
stays green). `Alt+[` / `Alt+]` step through the menu's sessions as they stepped through tabs. The run line
(`run 3 · started 14:02 · resumed · session 7f3a · 41 events · live`) stays, because it is the one line that says
which transcript this is.

The pill is drawn by patching its text, not by tearing the strip down each tick (`app.js:746–756`) — the general
rule is [plan-ownership.md](plan-ownership.md) slice A, and this control lands under it or lands its own patch first.

## The two focuses, and the toolbar in the column

`focus()` (zoom one tile, `body.focused`) and `focusMode()` (show only what needs a person, `body.needs-only`) become
what they are: **open** and **needs me**. In the column, opening *is* the zoom, so there is no *back to grid* — `Esc`
returns to the previously open tile, and the button is drawn only in grid, roles and screens where zoom still
exists. *needs me* stops hiding: in the column a band whose agent needs nobody folds to a 28 px sliver (name and
chip, still counted, still clickable) rather than `display: none`, so the mode narrows the column without emptying
it. The code renames `focus`/`unfocus` to `open`/`back` and keeps the old names as aliases, because the page globals
the regression tests call keep their names.

The toolbar is what #180 left: brand and the live dot; *window* (now `column | grid | roles | screens`); search and
the sidebar toggle; *needs me* (the mode, the chime, the bell); *settings* (#199). Nothing is added; *back to grid*
leaves it in the column.

## Where everything is written down

- [fleet-layouts.md](fleet-layouts.md) gains §D — `column`, and §The sitting's decision block is filled in with the
  operator's own words (§Decisions), by this plan's pull request, before any layout code — the order that page
  requires.
- [fleet-dashboard.md](fleet-dashboard.md): §The page's tile table gains the pill, the refresh and the model card;
  §The dock becomes §The column, and says the dock survives in the other three arrangements; §Keyboard gains
  `j k Enter r m` and loses nothing; §Endpoints gains `POST /api/refresh`.
- [windows-verification.md](windows-verification.md) gains the rows slice F names.
- [refusals.md](refusals.md) gains `refresh_busy`, and the model card's refusals point at #199's rows.

## Slices

### A #203 — the arrangement: `column`, the default, and the page filled to its edges

**Context.** §The arrangement. Today's four arrangements are body classes in `place()` (`app.js:2776–2814`) over one
stylesheet, and the dock is a flex sibling of the grid with no basis (`app.css:244`, `862`). Nothing sizes to the
viewport (`app.css:275–296`).

**Build this.**
1. `column` joins `LAYOUTS` in the three places the test keeps in step (`cli_fleet.py:540`, `serve.py:123`,
   `app.js:22`), **first**, and becomes `LAYOUTS[0]` in the same change — §Decisions is the record the layouts page
   requires, and this slice's pull request carries the filled-in decision block with it.
2. `body.layout-column`: `main` at one column (one per pinned tile), the open tile at full height with its transcript
   taking the remainder; `#column` is the dock's element given the sidebar's width rule and a vertical axis; the
   dock is not drawn in this arrangement.
3. Bands share the column's height (`flex: 1 1 0`) down to a per-band minimum by content; past that the column
   scrolls and its head says how many and how many need a person.
4. Which tile is open is a field on the window record (`/api/window`), defaulting to `selected`; a band's click
   opens it and the previous open tile takes the band's slot; pinned tiles are always open.
5. Under 900 px the column lies down into a horizontal strip above the tile.
6. `1`–`9`, `j`/`k`, `Enter`, `Esc` as §The arrangement says; the key map popover (#180) gains them.

**Acceptance criteria.**
- [ ] A rendered-page test at three viewport heights (720, 1080, 1440) with five fixture agents: the column's bands
      sum to the column's height within a pixel, the open tile's bottom edge is the page's, and no band is clipped
      below its minimum — the same test with twelve agents shows the column scrolling and the head counting.
- [ ] A page with one checkout draws no column and a tile that fills the page.
- [ ] `?layout=grid`, `roles` and `screens` render exactly as before this slice — the existing desk tests pass
      untouched but for the default they assume.
- [ ] Two windows with different open tiles agree on `selected`; a restart brings each back with its own open tile.
- [ ] The public page globals the regression tests call are unchanged.

**Out of scope.** The band's contents beyond name, chip and age (B); the buttons (C); any motion for the swap
([plan-ownership.md](plan-ownership.md) B).

### B #204 — the band: the last line on every one, red kept in its slot, hidden counted, one age

**Context.** §The band. The dock chip carries the ask only when red (`app.js:2747–2751`); two age formatters
disagree (`app.js:87–104`); a hidden tile is a chip that vanishes when hidden again.

**Build this.**
1. The band's anatomy in DOM order: number, name (project with `· n checkouts` when grouped), state chip with age,
   last line, the buttons' slot (empty until C), unread badge. One age formatter for chip, band, pill and rail —
   `ageChip`'s days everywhere, `age` retired.
2. The last line: `why` when the agent needs a person, else the last assistant line's first eighty characters, else
   `state · age`. `/api/fleet` rows already carry `why`; the last assistant line is one more field from the fold.
3. A band that needs a person: red, chimes as the tile would, shows its ask in full, keeps its slot; the column's
   head reads `n need you` and jumps to the first on click.
4. The foot: `n hidden · show all`; a departed repository's band is dashed with the `repo add` title.
5. The band is drawn by **patching** — text and classes set on an element that persists across ticks, listeners
   bound once — never by `replaceChildren` on every `place()` (`app.js:2713`). If [plan-ownership.md](plan-ownership.md)
   A has landed, use its helper; if not, this slice lands the column's own patch and A generalises it.

**Acceptance criteria.**
- [ ] A fixture agent that asked a question and went idle: its band shows the question; the same agent in the grid's
      dock still shows `idle · 3m` (the dock is unchanged).
- [ ] The band's element identity survives twenty `place()` calls (same node, same listeners) — asserted with a
      marker property set before and read after.
- [ ] A hidden band is counted at the foot; *show all* empties `hidden` in one press, as the dock's did.
- [ ] The chip and the band read the same age for the same agent at 6 days.
- [ ] Reduced motion: no movement anywhere in the column.

**Out of scope.** Reordering red bands to the top (§Open questions); the buttons (C).

### C #205 — hide, refresh and the model on every band and every tile, the same three, the same keys

**Context.** §The buttons. Hide exists on the tile only; refresh exists nowhere; the model is on the settings page
only. [plan-meter.md](plan-meter.md) C puts `model`, `effort`, `model_source` and `actual` on the `/api/fleet` row.

**Build this.**
1. `POST /api/refresh {repo}` → `events.refresh` + this repository's poll cells now + `served_model`, answering the
   fresh row; `refresh_busy` inside two seconds; **no `send`**. `ad-fleet refresh <repo>` is the same function from
   the CLI, so the page is a view of a verb.
2. The three buttons on the tile head (beside pin and width) and on the band, in the same order, `h` `r` `m`, each
   with a `title`, an `aria-label` and a 28 px hit target.
3. The model card: configured (with its source), last turn's model, a field over the `seen` datalist, an effort
   select, *save* → `settings {models: [...]}`, *all models · settings* → `q("/settings")#model-<repo>`; the card
   says *takes effect on the agent's next turn*. Refusals are the settings page's, in its words. (Built so; #366
   replaced the field, the select and *save* with the one-press picker, §The buttons.)
4. If meter C has not landed, this slice adds the four fields to the row (they are `LAUNCH.model_for` and
   `served_model`, already written) and meter C becomes the ledger only.

**Acceptance criteria.**
- [ ] Pressing refresh on a fixture agent whose git cell changed on disk updates the cell before the next tick, and
      the count of `send`/`said` events is unchanged — asserted.
- [ ] A second press inside two seconds is refused with `refresh_busy` and the button says so; a press after two
      seconds is not.
- [ ] Saving `claude-opus-5 · high` from a band's card writes `fleet.models.<repo>` with a dot-bearing repo name
      intact (`C.get_leaf`), and the settings page's row reads it back; saving `x --allow-all-tools` is refused with
      `bad_model` on the card.
- [ ] The card is reachable with `m` and operable without a mouse; the three buttons exist on the band and the
      tile with the same order and titles — one test over both.
- [ ] `ad-fleet refresh <repo>` prints the row `POST /api/refresh` answers.

**Out of scope.** Model validation beyond `check_model_value` (never measured); a refresh that nudges the agent
(§Decisions: refresh is free).

### D #206 — one session control: the strip becomes a pill and a menu, and there is one *earlier*

**Context.** §One session control. `drawStrip` (`app.js:727–763`), the markup at `index.html:249–260`, the inert
`earlier runs` at `index.html:351–354`, `openSessions`/`showSession` (`app.js:766–832`), `newSession` (`894`),
`openConsole` (`886`), `stepStrip` (`837`).

**Build this.**
1. The pill under the head: `session · <state> · <age>`, `console · …`, `earlier session · <how it ended> · <when>`;
   its text is patched, not rebuilt.
2. The menu, in the `.popover` component: *this session*; *earlier (n)* with one row per session — title, how it
   ended, when, cost — and the session's runs under it; *+ new session*; *open in a console* / *show console*;
   the sibling checkouts as a group when there are any. Every item keeps the handler its tab had.
3. `earlier runs` leaves the tile; its rows appear under their session in the menu with the state each ended in.
4. `Alt+[` / `Alt+]` / `Alt+N` unchanged in effect; the menu is operable without a mouse; `Esc` closes it.
5. The strip's markup, `drawStrip` and the `.tab` CSS go; `tests/test_fleet_desk_switcher.py` is ported to the
   menu, every assertion kept.

**Acceptance criteria.**
- [ ] The switcher tests pass against the menu with their assertions unchanged in meaning: an earlier session opens
      read-only and spawns nothing; *Resume here* refuses on a live agent and succeeds after the second press with
      `--resume <id>`; *+ new* starts a clean session.
- [ ] A tile with one session and no siblings shows the pill and nothing else where the strip was.
- [ ] `earlier runs` is absent from the DOM; every run is reachable under its session in the menu.
- [ ] The page's static payload stays under its budget and grows by no more than the menu's markup.

**Out of scope.** Sibling checkouts' own behaviour (#175); editing or deleting sessions.

### E #207 — the two focuses become *open* and *needs me*, and the toolbar in the column says less

**Context.** §The two focuses. `focus()` (`app.js:1127`), `unfocus()` (`1143`), `focusMode()` (`3000`),
`body.needs-only` (`app.css:642`), `body.focused` (`app.css:284–285`).

**Build this.**
1. `open(name)` / `back()` replace `focus()` / `unfocus()`, with the old names kept as aliases; in the column,
   `open` is the arrangement's own gesture and `back` returns to the previously open tile.
2. *needs me* in the column folds a band whose agent needs nobody to a 28 px sliver rather than hiding it; in the
   other arrangements it behaves as today.
3. *back to grid* is drawn only where zoom exists (grid, roles, screens).
4. The key map popover names the column's keys; `docs/fleet-dashboard.md` §Keyboard is the one list.

**Acceptance criteria.**
- [ ] In the column, *needs me* with two red agents of five leaves five bands in the DOM, two full and three folded,
      and the head reads `2 need you`.
- [ ] `focus`, `unfocus` and `focusMode` still exist as globals and do what the regression tests expect in the grid.
- [ ] `#unfocus` is absent from the column's toolbar and present in the grid's.
- [ ] The toolbar is one row at 1280 px in the column, in Edge, JCEF and Simple Browser (laptop row).

**Out of scope.** Any new toolbar control.

### F #208 — proof: the fixture desk at three heights, the laptop rows, and the layouts page's decision recorded

**Context.** [fleet-layouts.md](fleet-layouts.md) §The sitting asked for a photograph per arrangement and a table;
#179's F recorded the first three. This slice records the fourth and the decision, and proves the column on CI.

**Build this.**
1. A CI demo: five fixture agents (one running, one waiting for approval, one with a question, one idle, one
   departed) in `column` at 1080 px — a screenshot per skin variant, the bands filling the column, the red band's
   ask in full, the foot counting one hidden.
2. The laptop rows in [windows-verification.md](windows-verification.md): the column in Edge, JCEF and Simple
   Browser at 1280 and at the centre monitor's height; the swap; the model card's `save`; refresh's two-second
   refusal; `1`–`9`.
3. [fleet-layouts.md](fleet-layouts.md) §The sitting: the 2026-09-22 photograph described (no ticket keys, no tenant
   names), the `column` column in the table, and the decision block as this plan's §Decisions has it — checked
   against what the pull request that opened A already wrote, and corrected only by the operator.
4. [fleet-dashboard.md](fleet-dashboard.md) §The column, §Keyboard, §Endpoints; [refusals.md](refusals.md) rows;
   `CHANGELOG.md`.

**Acceptance criteria.**
- [ ] The demo runs on CI in the browser job and its screenshots are attached to the epic.
- [ ] Every laptop row is either filled in or reads _not yet measured_ — never a value nobody measured.
- [ ] `tests/test_entrypoints.py` accepts `ad-fleet refresh`; the refusal registry's count is updated.

**Out of scope.** Removing grid, roles or screens — a month after the default moves, as the layouts page says.

## Ground rules

1. **The page is a view.** A band draws what `/api/fleet` says; refresh calls what the tick calls; the model card
   writes what the settings page writes; every refusal is the CLI's words and a `code`.
2. **One arrangement, one record.** The column reads `order`, `pinned`, `hidden` from the arrangement every other
   layout reads; a window's open tile is a field on the window record and nowhere else.
3. **Never hide what needs a person, and never bury it either.** Red bands are full-height and counted at the head;
   *needs me* folds and never removes.
4. **Nothing reorders itself under the operator's hand.** The order is theirs; the one exception is an open question,
   not a default.
5. **Refresh spends nothing.** No `send`, no `say`, no premium request; a test counts.
6. **Same buttons, same order, same keys, on band and tile.** One test asserts both.
7. **Patched, never rebuilt.** A band's node persists across ticks; the pill's text is set, the strip is not redrawn.
8. **No framework, no build step, no CDN**; the payload budget holds; the page globals the regression tests call
   keep their names (aliases are allowed, renames are not).
9. **Every gesture has a key**, listed in one place.
10. **Decided on the real screens** — but the operator has already decided the arrangement (§Decisions); what the
    sitting corrects is the widths, the minimums and the folded height, and the runbook records which.

## Build order

A first — it is the arrangement everything else lands in. Then B (the band's contents), then C (the buttons; it
needs the four model fields on the row and adds them if [plan-meter.md](plan-meter.md) C has not). D and E in any
order after A. F last. [plan-ownership.md](plan-ownership.md) A (the render contract) before B is the better order;
if it has not landed, B patches the column on its own and A generalises it.

Across the three plans: ownership A → column A, B → meter A–C and column C → column D, E → ownership B–E → the three
F's, each with its own rendered-page tests along the way.

## Open questions, to be answered on the laptop and recorded in the slice

- Should a band whose agent starts needing a person **rise to the top** of the column, or keep its slot with the
  head's `n need you` jumping to it? Default: keep the slot. (B)
- Is 24 vw the right column width on the centre monitor, and does it want to be draggable the way the sidebar's is
  not? (A)
- Does the folded sliver in *needs me* read as *still here* or as *gone*, on the real screens? (E)
- Does a pinned tile beside the open one earn its half of `main`, or should pins in the column mean *always at the
  top of the column* instead? (A)
- Is two seconds the right floor for refresh, or should it be the tick's own cadence? (C)

## Cost

Everything here is free of premium requests: CSS, a field on the window record, a verb that re-reads files the
tick already reads. Refresh is bounded to what one tick costs for one repository, no more often than every two
seconds, and never a `send`. What this plan saves is attention: the black two thirds of the photograph is where the
three questions were not being answered, and a band that shows an idle agent's question is a premium request not
spent asking it again.

## Decisions — the operator's, 22 September 2026, recorded here so no code concludes what it did not

Asked, and answered in one conversation, before a line of this plan was written:

1. **What "show vertically" means** — *a column of bands*: inactive sessions stack top-to-bottom beside the open
   tile; each band grows to share the full page height; a click expands it in place. (Not side-by-side strips, not
   a left rail.) **Superseded the same day:** the operator meant side-by-side columns, one per agent. See
   [plan-panes.md](plan-panes.md) §Decisions 3.
2. **The default arrangement** — asked whether the message counted as the decision [fleet-layouts.md](fleet-layouts.md)
   reserves for the operator, on the real screens: *yes, column is the default*, grid still reachable by URL. The
   layouts page's decision block is filled in from this and from the photograph, and nothing else.
3. **The strip** — *one session control*: a pill reading `session · running · 6d` that opens a menu with earlier
   sessions, `+ new` and the console; transcript and composer stay where they are.
4. **The model button** — *a popover that changes it in place*: configured and last-run models, a field, a link to
   the settings row; it writes the key settings writes.
5. **Refresh** — *re-read now, free*: re-fold the stream and re-poll the cells immediately, no premium request. (Not
   a nudge to the agent.)

Two of the five are the layouts page's own questions; three are this plan's. What is still open is in §Open
questions, and the sitting answers those.
