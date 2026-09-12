# Plan: the sitting — five things a real day on the desk showed

_Status: IMPLEMENTED (2026-09-12) — epic #179 (slices #180–#185), under #91 (the fleet) and #122 (the desk), a
sibling of #145, #162 and #170. Built on branch `claude/adoring-gauss-bf40fr`; the laptop rows are in
[windows-verification.md](windows-verification.md) §The sitting. This is the first plan written from photographs of the
desk in use rather than from reading the code — the sitting [fleet-layouts.md](fleet-layouts.md) §The sitting
asked for, three phone photos of it, taken 11 September 2026 on the laptop in Edge. Every claim below is to be
measured on the same screens, in Edge, PyCharm's JCEF window and VS Code's Simple Browser, the way #145's were._

## Why this exists

The desk ran for a day with five agents on real tickets, and the operator sent three photographs: the grid in
`farmstead:daytime`, the grid with the sidebar open in `glass:smoke`, and the board window (`?layout=roles&view=board`)
in `glass:frost`. Read against the code, the photographs are five findings, each with a line that causes it:

| What the operator sees | What the code does | Section |
|---|---|---|
| The top bar is cluttered: eleven controls across two rows, the key map wrapped to two lines under the grid, and a blank (or black) square beside every pin | `index.html:10–46` puts the layout segments, the view segments, the swap select, search, the sidebar toggle, the palette picker, the skin picker, focus, chime and the bell in one toolbar; `index.html:163` is fourteen shortcuts in one `<span class="keys">`; `app.css:350` and `:356` give the pin and width buttons their stroke and omit `.hidetoggle`, so #173's eye icon paints with an SVG's default black fill | §The toolbar |
| Windows' grey scrollbars on every transcript, on the grid, and on the sidebar, whatever the theme | there is no `scrollbar` rule anywhere in `static/` — not in `app.css`, not in any skin; a page that repaints every other pixel from `--panel`/`--line`/`--muted` leaves the one control the OS draws to the OS | §Scrollbars |
| The glass skins are not glass: Smoke is a flat blue-grey, Frost is a flat cream | `skins/glass/skin.css:6–17` is one fill at `.55` alpha and `blur(16px)` over a ground with two faint radial washes at `.10`–`.15` alpha — there is nothing behind the panel bright or sharp enough for a blur to show, and a `.55` fill over a near-identical ground composites to a solid; the light variant is the same rule with paper under it | §Glass |
| In the board window there is nothing to drag a ticket onto — five *start on X* buttons per row, and a drop lands on nothing | `ticketRow` (`app.js:1557–1606`) makes a row draggable and the tile is the only drop target (`app.js:264–299`); `body.panels main { display: none }` (`app.css:642`) is the board window, where no tile exists; and `dispatchCard` (`app.js:1784–1786`) falls back to a bare `dispatch` when it finds no tile, so even the click path in that window skips #164's pre-flight card | §The rail |
| Nothing shows an agent's branches, so nobody can tell whether the work on a checkout is reaching `main` — and the agents do not know to care | the git cell (`poll.read_git`, `poll.py:619–643`) is one `git status --porcelain=v2 --branch`: the current branch, ahead/behind *its upstream*, dirty; the catalogue reads `.git/HEAD` and refuses to shell out by design (`catalogue.py:411–416`); the agents' allow-list (`launch.py:34–58`) permits `git status`, `diff`, `log`, `checkout -b`, `add`, `commit -m` and **not** `git branch`, so an agent cannot count its branches even when told to; `bitbucket-pr` step 2 is `git checkout -b <branch>` with no look at what is already there | §Branches |

A sixth finding is about the plan itself. [fleet-layouts.md](fleet-layouts.md) §The sitting asked for a photograph
per arrangement and a table nobody has filled in. These three photographs are the first of them, and slice F records
what they showed rather than leaving the table blank a second time.

**The purpose is the same as #122's, #145's, #162's and #170's: the human's attention.** Three questions a glance
should answer, and today two of them are answered by the OS's scrollbar and none by the toolbar: *what can I do
from here*, *which agent takes this ticket*, *is this checkout's work actually landing*.

## What is reused

- The toolbar's three labelled groups (`index.html:12–46`, HIG *Toolbars*), the segmented control, and the
  `@media (max-width: 1100px)` rule that already drops the group labels (`app.css:80`). The toolbar is restructured,
  not replaced.
- The palette tokens `theme.to_css` renders (`theme.py:95–140`: `--bg`, `--panel`, `--line`, `--select`, `--muted`,
  `--accent`, `--focus` and the five status roles). A scrollbar is drawn from the same tokens as everything else.
- The skin contract (`skins.py:1–29`, [themes.md](themes.md) §The Skin Contract): a skin is one stylesheet over the
  same DOM, no rasters, a size budget, the accessibility fallbacks, and **every variant measured** against its
  composited panel by `tests/test_fleet_skins.py:72–90` and applied for real by `tests/test_fleet_desk_actions.py`.
  Glass is re-drawn inside that contract, and the measurement is what changes least.
- The dock chip (`index.html:66–76`, `drawDock`), which already draws *one checkout: name, state, age, badge* as a
  button. The board window's agent rail is that chip with a drop target on it.
- The tile's drop handler (`app.js:264–299`) and `dispatchCard` (`app.js:1784`): a drop on the rail calls the same
  function a drop on a tile calls, and the card it opens is #164's, unchanged.
- `board.suggest` (`board.py:148–174`): `repo`, `candidates`, or a hint. The rail highlights the candidates for the
  ticket in flight and dims the rest; the `start on X` buttons stay for the click path.
- The git poll cell: `poll.read_git` (`poll.py:619`), its 30-second cadence (`poll.py:72`), the `fleet.poll.git`
  config block (`poll.settings`), and the cell the page draws for it (`drawCells`, `app.js:1972`). Branches are more
  git, read the same way, shown in the same cell — and, like the dirty flag, **never an event** (`poll.py:391–392`:
  a toast every time the operator saves a file is the notification they would turn off first).
- The inspector (`drawInspector`, `app.js:2200`): "the tile is the agent; the sidebar is the project"
  ([fleet-dashboard.md](fleet-dashboard.md) §The page). A checkout's branches are the project's, so they open there.
- `AGENTS.md`'s stop conditions and `session-bootstrap` step 4, which already prints `branch=<branch>`; the caution
  is one more thing on that line and one more rule in that list.
- The browser harness (#146), `tests/test_fleet_desk_regressions.py`'s page globals, the shuffled suite, and the
  laptop runbook's convention that every failure becomes a regression test named for its host.
- The HIG, cited the way #145 cites it: *Toolbars* (commands for the current context; settings live elsewhere),
  *Materials* (a translucent material blurs what is behind it and adapts to light and dark while keeping content
  legible), *Drag and drop* (every drop target is visible before the drop and every drag has a keyboard route),
  *Feedback* (say what changed and how old it is), *Color* (never colour alone).

## Prior art, and what is different here

| Product | Does | Does not |
|---|---|---|
| macOS and Windows 11 translucent materials; the CSS `backdrop-filter` pattern (a low-alpha fill, a blur-and-saturate, a one-pixel light edge, a colourful mesh behind) | real frost, over content that is worth blurring | run inside a contract that measures every panel's contrast against what is actually behind it, in Python, before a browser is opened |
| Every browser's `scrollbar-color` / `::-webkit-scrollbar` styling | thumb and track in the page's colours | change with a *skin* that repaints the page for a room, or stay honest about which embedders draw them |
| GitHub Desktop, GitKraken, VS Code's Git Graph and Source Control view | a branch list with ahead/behind and a commit graph | show it per *agent*, beside the ticket that agent is on, on a page three embedders render — or tell the agent itself how many branches it is about to add to |
| Jira's board, Linear's assign-by-drag | drag a ticket to a person | drag it to a *checkout*, run a pre-flight on it, and refuse in the supervisor's own words |

Three things none of them do, and this epic does:

1. **The chrome follows the theme all the way down** — scrollbars included — and every skin variant is still measured
   rather than eyeballed, glass most of all.
2. **The board window is a place a ticket can be handed over from**, with the same card, the same pre-flight and the
   same refusals as a tile, and a rail that says which agent could take it before the drop.
3. **Branch health is on the tile and in the agent's head at once**: the operator sees `7 branches · 3 never reached
   main` on the checkout, and the agent that would create the eighth has been told to look first.

## The toolbar

HIG *Toolbars*: a toolbar holds the commands for the current context; settings and rarely-changed choices live
somewhere a person goes on purpose. Today's bar holds both, and the second row (`needs me`) exists because the first
overflowed.

**What stays on the bar, in this order:** the brand and the live dot; the *window* group (layout segments, and the
view segments only when the layout has them); the *see* group cut to search and the sidebar toggle; the *needs me*
group (focus, chime, the bell). One row on a 1280-pixel laptop; the group labels already drop under 1100 pixels.

**What leaves it:**

- The palette and skin pickers become one *look* button opening a small popover with both, in the same order they
  are in today. They are chosen once a week, not once a minute, and two `<select>`s are the widest things on the
  bar. The popover is the segmented control's markup, not a new component: no framework, no build step.
- The key map leaves the footer. The footer keeps `5 agents · 4 need you` and the notice line — the two things that
  change — and gains a `?` button (and the `?` key) that opens the map as a popover grouped the way the toolbar is
  grouped: *tiles*, *sessions*, *the sidebar*, *the strip*. Fourteen shortcuts in one wrapped line are a reference
  card nobody can read; the same fourteen in four short columns are.
- The swap `<select>` (`index.html:23–24`) is drawn only in the `screens` layout; it already is, and stays.

**What is fixed on the way:** `.hidetoggle` joins the two rules at `app.css:350` and `:356` so the eye icon has a
stroke; the duplicated `#find` width (`app.css:77` and `:566`) becomes one rule; the toggles' hit target stays at the
28-pixel HIG floor. Every control keeps its `title`, its `aria-*` and its key, and every key stays where
[fleet-dashboard.md](fleet-dashboard.md) §Keyboard says it is.

## Scrollbars

Every scrollable thing on the page — `.transcript`, `.history`, `#grid`, `#side > aside`, `#hits`, `#tickets`,
`.sessions` — is drawn by the operating system today, which on Windows is a 17-pixel grey bar with arrows, over a
page that paints every other pixel from the palette.

**One rule, in the palette's tokens, in `app.css`:** `scrollbar-width: thin` and `scrollbar-color: <thumb> <track>`
on `*`, with the thumb from `--line` moved toward `--text` and the track transparent, so the bar reads as part of
the panel it scrolls. The legacy `::-webkit-scrollbar`, `::-webkit-scrollbar-thumb` and `-track` pseudo-elements are
written beside it for the embedders that predate the standard property — the two are not additive in Chromium
(when the legacy rules match, `scrollbar-color` is ignored), so both say the same colours and a test asserts they
do. Hover darkens the thumb toward `--muted`; the corner is the track.

**Each skin overrides the thumb, not the rule:** glass draws a translucent thumb with the panel's edge highlight;
voxel a chunky 12-pixel slab with the bevel its buttons have; farmstead a wood-toned one. The track is always the
surface underneath, so a skin's texture shows through it. `prefers-reduced-motion` needs nothing here; nothing
moves.

**What is measured:** `getComputedStyle(el).scrollbarColor` on a transcript equals the tokens the palette declares,
for every theme and every skin variant, in the browser harness — the same loop that already applies each variant
for real. Whether JCEF's and Simple Browser's Chromium honour `scrollbar-color` at all is a laptop row (F), and
the legacy pseudo-elements are the answer if they do not.

## Glass

Glassmorphism is four things, and the current skin has one of them: a translucent fill (it has that), **something
behind it worth blurring** (it does not — two washes at `.10`–`.15` alpha over a near-black ground are invisible
through a `.55` fill), **an edge that catches light** (a `.12` white border is a hairline, not an edge), and
**depth in layers** (every surface is one fill at one alpha, so a card on a tile on the ground is three copies of the
same colour). The screenshots show the result: Smoke is a flat `#1B222C` and Frost a flat `#EDE6D6`, which is exactly
what `skins.py:44–52` declares as the composited panel — the number is honest; the material is not there.

**What changes, inside the skin contract:**

- **The ground becomes a mesh.** Three to five large, soft, *saturated* blobs — the palette's accent, its `--running`
  and `--waiting` roles, tinted for the variant — at `.35`–`.5` alpha, overlapping, `background-attachment: fixed`,
  so the blur has colour to work with. Frost's are warm and pale; Noir's are near-white at low alpha so a black room
  stays a black room.
- **The fill drops to `.30`–`.40`, the blur becomes `blur(18px) saturate(140%)`,** and the panel's edge is drawn
  twice: a one-pixel outer border at `.18` white (Frost: `.10` black) and an inset top highlight at `.25`, which is
  the light catching the pane. The shadow lengthens and softens.
- **Layers.** The ground is layer 0. Tiles and the sidebar are layer 1 at the base alpha. Cards on a tile — the
  approval card, the asks, the dispatch card, the read-only pane — are layer 2, `.10` more opaque and one pixel
  brighter at the edge, so what is *on* the glass is distinguishable from the glass. The toolbar and footer are layer
  1. Nothing is layer 3.
- **The chips stay solid.** A status chip means the same thing in every world (`themes.md` §Available Skins), and a
  translucent `fail` is a `fail` somebody has to look at twice.
- **Reduced transparency** keeps the opaque fallback it has (`skin.css:34–40`); it is still the only skin the query
  applies to, and [themes.md](themes.md) still says which engines will never fire it.

**What the measurement becomes.** `skins.py`'s `composited_panel` is one colour because the ground was one colour.
Over a mesh, the panel composites to a *range*: what the text sits on over the darkest blob and over the lightest.
The contract becomes `composited_panel: {"darkest": …, "lightest": …}` (the old string still accepted, as both),
`theme.check` runs against both, and `test_fleet_desk_actions.py`'s real-browser comparison samples the panel at
the two probe points the variant names rather than one. The `!important` cascade in `skin.css` — every rule, so the
skin wins against `app.css` — is kept where it is needed and dropped where a more specific selector does the same,
so a later skin does not have to out-shout this one.

**Frost is the hard one** and is done last: a light glass over a light mesh has a smaller contrast budget than a
dark one, and 4.5:1 at the lightest probe point is the constraint the blob alphas are solved against, not a check
run afterwards.

## The rail: a ticket dragged to an agent from the board window

In the grid, a ticket goes to an agent by being dragged onto its tile. In the board window there are no tiles —
that is the point of the window — so the row offers a button per candidate and the drag goes nowhere. Two things
are wrong with that, and one of them is also wrong in the grid.

**The agent rail.** Along the top of the board section — in the sidebar's board tab and, full-width, in the board
window — one chip per registered checkout: the dock chip's markup (`.dock-chip`: name, state with age, badge),
each one a drop target. Drag a ticket over the rail and the candidates `board.suggest` names for that key light up
(`drop-target`, the same class the tile uses) and the others dim; drop on one and `dispatchCard(key, repo)` runs,
exactly as a drop on that agent's tile would. Drop on a non-candidate and it is the same drop a tile allows today —
the supervisor's `cross_project` refusal, with the page's one override (`app.js:1848–1858`). The `start on X`
buttons stay: a click and a drag are two routes to one function.

**The card gets a home where there is no tile.** `dispatchCard` returns `dispatch(key, repo)` when `tiles.get(repo)`
is empty (`app.js:1786`), which is every dispatch from the board window — so the window built for handing tickets
over is the one place the hand-over skips its pre-flight. The card's markup moves from the tile template to a
single element the page owns, drawn *in* the tile when there is one and *under the rail chip* when there is not;
`closeDispatch` and the `Esc`/`Enter` handling are unchanged. This is the one structural change in the slice, and
it is what makes the board window equal to the grid.

**Every drag has a key.** A ticket row takes focus; `1`–`9` picks the rail chip in that position, the way `1`–`9`
picks a tile on the glass; `Enter` on a row with one candidate is that candidate. The rail is `role="listbox"`, each
chip an option with the checkout's name as its accessible name.

**The rail is not a second dock.** It shows every checkout, on the glass or not — a hidden tile can still take a
ticket — and it says nothing about hidden or zoomed. A rail chip whose agent is live says `running · 4m` and drops
on it are the same refusal a live tile gives: one agent per working tree.

## Branches: every checkout's git history on the tile, and the caution the agents share

The operator's sentence is *"make sure they're not erroneously committing too much work on one work tree and then
not having everything actually hit main."* Read against the checkout, that is **stranded work**: local branches
with commits ahead of the default branch and no pull request — several per ticket, each holding part of the
change, none of them the one that will merge. The git cell cannot see it (`read_git` reads the current branch and
its upstream, nothing else), the catalogue will not shell out to see it, and the agent that creates the next branch
has never been asked to look.

**The read.** `poll.read_branches(repo)`, beside `read_git`: three local calls in the checkout —
`git symbolic-ref --short refs/remotes/origin/HEAD` for the default branch (falling back to `main`, then `master`,
whichever exists); `git for-each-ref refs/heads --format=<name, short sha, committer date, upstream track>` for the
list; `git branch --no-merged <default> --format=%(refname:short)` for the ones whose work has not reached it. For
each unmerged branch, one `git rev-list --count <default>..<branch>` — bounded, because a checkout with forty
unmerged branches is the finding, not a reason to make forty calls; the count stops at twenty and says *and more*.
Plus `git log --oneline -n 20 --decorate=short` on the current branch, for the history the operator asked to see.
Read-only, `--no-optional-locks`, thirty-second timeout, the way `read_git` already is. Run on the click and cached
for the git cell's interval, not on every poll: `for-each-ref` is cheap; `rev-list` twenty times a minute across
five checkouts is not.

**On the tile.** The git cell (`drawCells`, `app.js:1972`) becomes a button and gains a second line:
`feature/RDSD-22490 +2 dirty` over `7 branches · 3 never reached main`. At or above `fleet.branches.warn` (default
**6**, the operator's number) the cell goes amber — `--waiting`, the same role the approval card uses — and its
title says why. It is a poll cell, so it is grey with its error when git cannot be asked, and it is **never a
toast** (`poll.py:391–392`): the count changes when a person types `git checkout -b`, and a chime for that is a
chime nobody keeps.

**In the inspector.** Clicking the cell opens the sidebar's *project* section on a *branches* pane: the default
branch and how far the current one is from it; one row per local branch — name, last commit and its age, ahead of
default, upstream (or *none pushed*), the PR when this is the current branch (the PR cell already knows it), and
the ticket key the name carries; the unmerged rows first and marked; then the last twenty commits of the current
branch. A branch whose name carries the tile's active ticket is *this ticket's*; a second one with the same key is
the smell the operator is looking for, and the pane says so in one line: *two branches carry RDSD-22490; only one
can merge*. `ad-fleet branches <repo>` prints the same rows as TOON, from the same function.

**In the agent's head.** Three changes, each small:

1. `launch.DEFAULT_ALLOW` (`launch.py:34–58`) gains `shell(git branch --list)` and `shell(git for-each-ref)` — both
   read-only, both enumerated the way the list demands (`launch.py:30–33`: never a prefix that widens).
2. `session-bootstrap` step 4 prints `branch=<branch> · branches=<n> (<m> unmerged)` from `git branch --list` and
   `git branch --no-merged <default>`, so the count is in the transcript of every session from its first line.
3. A new `AGENTS.md` rule, numbered after the duplicated 14 is fixed: **before `git checkout -b`, look.** If a
   branch already carries this ticket's key, reuse it — a second branch per ticket is how work gets stranded. At
   `fleet.branches.warn` or more local branches, name the unmerged ones in one line, `ad-state ask` whether to
   continue on the existing branch or which of the stale ones the operator will delete (never the agent — a branch
   is the operator's to delete), and continue on the existing one when there is one. `bitbucket-pr` step 2 cites
   the rule and does the look before the checkout. *Cautious*, as asked, not stopped: a repository that legitimately
   holds nine branches still gets its PR; it gets it on the branch that already exists.

The fleet's count and the agent's count read the same refs, so they agree by construction; the number on the tile
is the number in the transcript.

## Where everything is written down

**`~/.agentdata/config.json`** — `fleet.branches.warn` (default 6); `fleet.poll.git` unchanged; `theme.skin`
unchanged. Nothing new inside a repository; the branches read opens nothing under `.agent/`.

**`skins.py`** — `composited_panel` may be a `{"darkest", "lightest"}` pair; a string still means both.

**The event contract** — no new kinds. A branch count is a poll cell, like the dirty flag, and never an event.

**The API** — `GET /api/branches?repo=` (the pane's rows; cached per the git interval); the `polls.git.value` cell
gains `branches`, `unmerged` and `warn`; `POST /api/start` is unchanged (the rail posts what the tile posts).

**The CLI** — `ad-fleet branches <repo>`; nothing else new. `ad-fleet start` is unchanged.

**The page globals** the regression tests call keep their names; the dispatch card's markup moves, its class names
do not.

## Slices

Sizes are relative to #173 (= 1). Each lands with its own rendered-page test and its own row in the runbook.

| Slice | Title | Size | Needs | Unlocks |
|---|---|---|---|---|
| A #180 | the toolbar, said less | ½ | — | F |
| B #181 | scrollbars that belong to the theme | ½ | — | C, F |
| C #182 | glass that is glass | 1½ | B | F |
| D #183 | the rail: a ticket to an agent from the board window | 1 | — | F |
| E #184 | branches on the tile, and the caution the agents share | 1½ | — | F |
| F #185 | proof, and the sitting's table filled in | ½ | all | — |

### A #180 — the toolbar, said less

**Context.** §The toolbar. Eleven controls in one bar that wraps to two rows; a fourteen-item key map that wraps to
two lines; #173's hide icon invisible because `.hidetoggle` is missing from `app.css:350` and `:356`.

**Build this.**
1. The *see* group cut to search and the sidebar toggle; the palette and skin `<select>`s move into a *look*
   popover opened by one button, built from the segmented control's markup, closed by `Esc` and by clicking away.
2. The key map leaves the footer for a `?` popover (and the `?` key), grouped *tiles · sessions · the sidebar · the
   strip*; the footer keeps the counts and the notice.
3. `.hidetoggle` joins the pin and width rules; the duplicated `#find` width becomes one rule; `title`, `aria-*`
   and every key unchanged.
4. [fleet-dashboard.md](fleet-dashboard.md) §The page and §Keyboard say where the pickers and the map went.

**Acceptance criteria.**
- [ ] At 1280×800 the toolbar is one row in every theme and every skin, in a rendered-page test that measures the
      header's height against one row of its controls.
- [ ] Every shortcut in the old footer map is in the popover, asserted by comparing the popover's `<kbd>` set to the
      keys `app.js` binds — the test that keeps the markup and the script in step already reads both files.
- [ ] The hide toggle's SVG computes to `stroke: currentColor` and `fill: none`, like the pin's.
- [ ] `tests/test_fleet_desk_regressions.py` passes unchanged; the page globals keep their names.

**Out of scope.** A settings page; changing what any control does; the sidebar's own tab strip.

### B #181 — scrollbars that belong to the theme

**Context.** §Scrollbars. No `scrollbar` rule exists in `static/`.

**Build this.**
1. `scrollbar-width: thin` and `scrollbar-color` from the palette tokens on every scrolling element, with the
   legacy `::-webkit-scrollbar*` rules saying the same colours beside them; hover state; the corner is the track.
2. One override per skin, thumb only: glass translucent with the edge highlight, voxel a bevelled slab, farmstead
   wood. The track always shows the surface beneath.
3. A note in [themes.md](themes.md) §The Skin Contract: a skin that repaints a surface repaints its scrollbar.

**Acceptance criteria.**
- [ ] For every palette and every skin variant, `getComputedStyle(transcript).scrollbarColor` equals the declared
      tokens, in the browser harness's existing per-variant loop.
- [ ] A test reads `app.css` and every `skin.css` and asserts the legacy rules and `scrollbar-color` name the same
      colours, so the two mechanisms cannot drift.
- [ ] The runbook row for JCEF and Simple Browser is filled in (F) or marked *not yet measured*.

**Out of scope.** Overlay (auto-hiding) scrollbars; scrollbars outside the page (the browser's own).

### C #182 — glass that is glass

**Context.** §Glass. One fill at `.55` over two invisible washes; no edge; no layers; Frost flat.

**Build this.**
1. The mesh ground per variant; the fill at `.30`–`.40` with `blur(18px) saturate(140%)`; the double-drawn edge;
   the longer shadow; layer 2 for cards on tiles; chips solid; the reduced-transparency fallback kept.
2. `composited_panel` as a `{darkest, lightest}` pair in `skins.py`, the old string accepted as both;
   `theme.check` against both; `test_fleet_desk_actions.py` sampling two probe points.
3. The `!important` cascade thinned to where it is needed; the stylesheet stays under the skin's size budget.
4. Frost last, its alphas solved against 4.5:1 at the lightest probe point.
5. [themes.md](themes.md) §Skins and their worlds re-measured: both composited colours per glass variant and the
   ratio at the worse one.

**Acceptance criteria.**
- [ ] Every glass variant passes `theme.check` at both probe points, and the real-browser comparison agrees with
      both declared colours to within the tolerance the existing test uses.
- [ ] A rendered-page test asserts a card on a tile computes to a different background than the tile, and the tile
      to a different one than the ground — the layers are measurable, not asserted by eye.
- [ ] `test_zero_raster_bitmaps_in_skins`, the size budget and the fallback tests still pass.
- [ ] The three photographs are re-taken on the laptop (F) and the operator says it is glass.

**Out of scope.** New variants; touching voxel or farmstead beyond their scrollbar thumb; animated blobs (motion
is a separate promise with its own fallback, and nothing here needs it).

### D #183 — the rail: a ticket to an agent from the board window

**Context.** §The rail. The board window has no drop target and its click path skips the pre-flight card
(`app.js:1786`).

**Build this.**
1. The agent rail at the top of the board section and the board window: one dock chip per checkout, each a drop
   target; candidates for the ticket in flight light up on `dragover`, the rest dim; drop calls `dispatchCard`.
2. The dispatch card becomes one page-owned element drawn in the tile or under the rail chip;
   `dispatchCard`'s no-tile fallback goes; `closeDispatch`, `Esc`, `Enter` unchanged.
3. Keyboard: a focused row plus `1`–`9` or `Enter`; `role="listbox"` with accessible names.
4. Refusals unchanged and in the supervisor's words: live agent, cross project (with the page's one override), a
   key that is not a key.
5. [fleet-dashboard.md](fleet-dashboard.md) §The page and [fleet-layouts.md](fleet-layouts.md) §B say the board
   window can hand a ticket over.

**Acceptance criteria.**
- [ ] In `?layout=roles&view=board`, a rendered-page test drags a ticket row onto a rail chip, reads the pre-flight
      card with its verdict, presses *Start*, and counts one `started` event on that checkout.
- [ ] The same drop on a chip whose agent is live reads the `live_agent` refusal verbatim and counts no `started`.
- [ ] A drop on a non-candidate reads the `cross_project` refusal and its override; declining it starts nothing.
- [ ] The whole gesture is repeated from the keyboard, and the grid's tile drop still passes its existing tests.

**Out of scope.** Dragging a ticket from the board to a *session* (the strip); reordering the rail; the rail as a
second dock.

### E #184 — branches on the tile, and the caution the agents share

**Context.** §Branches. `read_git` sees one branch; the allow-list forbids `git branch`; `bitbucket-pr` creates
without looking.

**Build this.**
1. `poll.read_branches`: default branch, `for-each-ref`, `--no-merged`, bounded `rev-list` counts, the last twenty
   commits; read-only, `--no-optional-locks`, on the click, cached per the git interval.
2. The git cell as a button with its second line, amber at `fleet.branches.warn` (default 6), grey with the error
   when git cannot be asked, never a toast.
3. The inspector's *branches* pane: rows as §Branches lists them, unmerged first, the *two branches carry this
   ticket* line; `GET /api/branches?repo=`; `ad-fleet branches <repo>` from the same function.
4. `launch.DEFAULT_ALLOW` gains `shell(git branch --list)` and `shell(git for-each-ref)`; `session-bootstrap`
   step 4 prints the count; the new `AGENTS.md` rule (and the duplicated 14 renumbered); `bitbucket-pr` step 2
   looks before it creates and reuses the ticket's branch.
5. The fake `copilot` learns a transcript that finds seven branches and reuses the ticket's own, so the caution is
   exercised on CI.

**Acceptance criteria.**
- [ ] A fixture checkout with seven local branches, three unmerged and two carrying one ticket key: the cell reads
      `7 branches · 3 never reached main`, is amber, and the pane lists the three first with the *two branches
      carry* line; `ad-fleet branches` prints the same rows.
- [ ] A fixture with two branches shows the count and is not amber; `fleet.branches.warn: 3` makes it amber.
- [ ] Counting `started` events and `git checkout -b` calls in the fake's transcript: the agent on the seven-branch
      fixture creates no branch and continues on the ticket's; on a clean fixture it creates one.
- [ ] `test_the_agent_may_not_read_the_fleet` (or its sibling) still proves the allow-list is enumerated: `git
      branch -D` and `git for-each-ref --format` with a write are not permitted.
- [ ] The three git calls on a checkout with forty branches finish inside the poll timeout, and the pane says
      *and more* past twenty.

**Out of scope.** Deleting or renaming a branch from the page (a branch is the operator's); a PR lookup per branch
(one Bitbucket call per branch is a budget the poll cannot spend — the current branch's PR is the one exact answer,
and *no upstream pushed* is the honest proxy for the rest); a commit graph.

### F #185 — proof, and the sitting's table filled in

**Context.** #102's and #176's shape, for this epic; and [fleet-layouts.md](fleet-layouts.md) §The sitting's table,
still blank.

**Build this.**
1. `docs/windows-verification.md` rows: the toolbar at 1280 in JCEF and Simple Browser; `scrollbar-color` in each
   embedder's Chromium; `backdrop-filter` in each, and the frame rate of a four-window desk with blur on; the rail
   drag in the board window on the right monitor; the branches pane on the operator's real checkouts, with their
   real counts — which is also how the default of 6 gets checked against the repositories it was chosen for.
2. The sitting's table in [fleet-layouts.md](fleet-layouts.md) filled in from the three photographs — arrangement,
   minutes, what was opened outside the desk — and the photographs described rather than committed: they carry a
   tenant's ticket keys and summaries, the same reason the fake `copilot`'s transcripts are synthesized.
3. The demo, on CI against the fake: the board window hands a ticket to a checkout with seven branches, the card
   says *ready*, the agent reuses the ticket's branch and says so, the tile's cell reads the count, and the
   inspector's pane names the unmerged three — in `glass:smoke`, with a scrollbar the test can read the colour of.

**Acceptance criteria.**
- [ ] The demo passes on Linux and Windows CI inside the two-minute Linux budget.
- [ ] Every runbook row carries a host and a date, or *not yet measured* — never blank.
- [ ] This plan's status line moves to IMPLEMENTED, at which point `tests/test_entrypoints.py` checks every command
      it names.

## Ground rules

1. **The page is a view.** The rail posts what the tile posts; the branches pane draws what `ad-fleet branches`
   prints; every refusal is the CLI's words and a `code`.
2. **Nothing is written inside a repository.** The branches read opens nothing under `.agent/` and runs no git
   command that writes; `--no-optional-locks` on every call.
3. **The allow-list is enumerated, never a prefix.** Two read-only git verbs are added by name; `shell(git)` is
   never.
4. **A branch is the operator's.** The page and the agent count, name and warn; neither deletes, renames or resets.
5. **Never colour alone.** Amber on the git cell carries a sentence; the rail's lit chips carry `aria-selected`.
6. **Every skin variant is measured, glass most of all** — against both ends of what is behind it, in Python first
   and in a real browser second.
7. **Every gesture has a key.** The rail, the popovers and the pane are reachable without a mouse.
8. **No framework, no build step, no CDN**; the page globals the regression tests call keep their names; the skin
   contract's size budget holds.
9. **Poll cells are not events.** A branch count, like a dirty tree, never chimes.
10. **Decided on the real screens.** The threshold of 6, the rail's edge, the mesh's colours: defaults ship, the
    sitting corrects, and the runbook records which.

## Build order

A and B in any order → C after B → D and E in any order, after A (the card's new home and the cell's button both
touch what A leaves on the tile) → F last. A alone already fixes the invisible hide icon; B alone already removes
the grey bars from every screenshot.

## Open questions, to be answered on the laptop and recorded in the slice

- Do PyCharm's JCEF Chromium and VS Code's Simple Browser honour `scrollbar-color`, or only the legacy
  pseudo-elements? (B)
- Does `backdrop-filter` with `saturate()` composite correctly in JCEF, and what does a four-window desk with blur
  cost in frame rate on the laptop's GPU? (C)
- Is 6 the right default for `fleet.branches.warn` on the operator's real repositories, or is the unmerged count
  the better trigger and the total merely context? (E)
- Should the rail live at the top of the board section or beside it in the board window, where the width is
  there? (D)
- Does the `?` key conflict with any embedder's own binding? (A)

## Cost

Everything here is free of premium requests: CSS, a drag target, three local git calls on a click. The branches
read is the only new work the server does — bounded to twenty `rev-list` calls per checkout per click, cached for
thirty seconds — and the agent's own look before `git checkout -b` is two git calls it was already allowed to
afford. What this epic saves is the expensive thing: a branch of work that never reaches `main` is a premium
request spent on nothing, and the tile now says so before the second one is opened.
