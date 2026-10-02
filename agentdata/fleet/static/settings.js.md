# `settings.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The settings page.

A page and not a popover, because the palette stopped being the only thing here: the model each
agent runs and the flags the Copilot CLI is launched with are settings too, and none of them fits
behind a button on a toolbar that is meant to be about the agents.

It shares `common.js` with the desk -- the token, `q`, `post`, `text`, and the two painters -- and
`picker.js`, the model picker (#362), and nothing else. It deliberately does NOT load `app.js`:
that file boots a desk (an EventSource feeding tiles, a fifteen-second `loadDesk`, a `place()`
that rewrites `document.body` several times a second) and none of it has any business running
under somebody editing a dropdown.

It does open one EventSource of its own, for two frames. The `theme` frame is emitted whenever
`config.json` changes, so a palette set from `ad-theme` in a terminal, or from another window,
repaints this page instead of leaving its pickers saying something that is no longer true. That
was bug #195 on the desk, and a settings page with no stream is where it would come back. The
`models` frame says the model list changed (#361), and the model pickers are drawn again.

Every link out of here has to carry the run token: `_authorized` reads it from the query string
alone, so a static href in the markup is a 403 that looks like a dead button.

### `var pendingTheme`

Above `var pendingTheme = null;`:

The last theme write still in flight (#346). Leaving before it has answered could land on a desk
served the old skin, so a plain click waits for the answer -- either answer -- and then goes.
`href` is read at click time, so #344's `pageUrl` is what is followed. No timer.

### `var heardDuringWrite`

Above `var heardDuringWrite = null;`:

A `theme` frame heard while a write is in flight is the server's word from before that write (the
stream's first frame can land after a pick on a slow start). It is kept, not painted: painted, it
put the old theme back over the pick; kept, it is what a refusal goes back to.

## theming

### `function loadThemes`

Fills the one picker from `/api/themes`: an `<optgroup>` per genre, an option per look with its
title as the text, its value as the value (`notebook`, `glass:azure`, `weather:rain`,
`palette:sand`), and a tooltip of its why and the palette on each side (`sidesNote`). Wires the
picker's `change` to `choose` with `{look}`, the side toggle `#mode` to `choose` with the other
side of the one in effect (`sideOn`), and `#mode-follow` to `choose` with `{mode: ""}` when a side
is pinned. Then reflects what is worn: `themeNow` if a frame has arrived while fetching (#195),
else the answer's `current`.

### `var themeData`

The `/api/themes` answer, kept for `paletteCss`, `lookRow` and the lines under the picker.

### `var themeSeq`

The highest pick number this page has sent or heard (#483): every pick is numbered above it.

### `function parseLook`

The body a look posts: `{look: value}`, the value the picker holds (`skins.parse_look` says the same).

### `function lookOf`

The picker value for a theme state: its `look` when the server says one, else the skin's full
name or `palette:<theme>` for a state written before looks existed.

### `function paletteCss`

A palette's tokens from `themeData.themes`, or null for a name it does not list (a generated
`flip:` or `colors:` palette: the server sends its tokens with the state, so the page never needs
them here).

### `function lookRow`

The genre row for a look value: its title, why, `skin`, `own` side and `sides` (variant, skin and
palette per side).

### `function sidesNote`

The tooltip's tail: the palette on each side, or nothing for the system's own colours.

### `function sideOn`

The side in effect: the pinned `mode`, else what `prefers-color-scheme` says now.

### `function resolveLook`

The page's copy of `skins.resolve`, so a pick paints before the server answers: the variant and
palette of the side in effect, or, while following the system, the `<skin>:auto` state with both
sides for `applyThemeState`. With `pick`, a fresh choice of a flavour or a palette pins its own
side (Nether is a night world); the toggle's own writes never pin.

### `function lookTitle`

"Genre · title" for a look value, from the data.

### `function looksOn`

"Genre · title" for each look with a side drawn on a palette (#393), for the line under a plain
look.

### `function paletteTitle`

A palette's title from the data; a `flip:` palette is named after the one it flips, and a
`colors:` palette after its mode, its colour and its side.

### `function isColors`

Whether a look value is the Colors genre's (`colors:<mode>`).

### `function looksLine`

The line under the picker: the look, how its side was chosen (pinned, or following the system and
which side that is now), the palette that side brings and that the terminal shares it; for a plain
look, the looks also drawn on that palette. `tests/test_fleet_settings_page.py` writes the same
line from the data.

### `function choose`

One pick, from the picker, the toggle, the colour input or a preset: paint it optimistically
(`resolveLook`), reflect it, then `post("theme", body)` numbered above `themeSeq`. A Colors look is
not painted ahead of the answer: its palette is built by the server from the colour, and the page
has no engine of its own; the controls reflect the pick and the answer paints it. On an answer that is not a refusal, apply and
reflect what the server resolved; on a refusal or no answer, put back what was worn (or what the
stream said meanwhile, `heardDuringWrite`) and say why on the control.

### `function reflectTheme`

Writes the state into the controls: the picker's value (`lookOf`, never blank), the toggle's word
(Light or Dark, the side in effect), its `aria-checked` and `active` (pinned), the Auto button's
`aria-pressed`, the colour row (shown for a Colors look, its picker and hex field set to the
colour in force) and the line under them.

## models

### `var modelList`

Above `var modelList = null;`:

Pressed, not typed (#367). Which names the installed Copilot CLI takes is measured now: `GET
/api/models` is what `copilot help config` listed (#360), cached, else the list this package ships,
and a page never waits on the CLI for it. The list is a suggestion and never a gate: `other…` in
a row's expansion is the one place a name is typed, a name the CLI does not offer is saved and the
saved tag says so, and the CLI stays the validator at the agent's next turn.

`picker.js` draws every picker here (#362): a full one for the fleet-wide default, and a compact
one per repository, whose `more…` opens a full one in the same cell. The picker never posts; this
page applies the inherit rule. Inherit is the entry removed, never kept as `{}`. And `model_for`
reads a repository's entry as a whole, so an effort pressed on a repository with no entry pins the
model it inherits along with it: alone, the effort would run on the CLI's model, not the fleet's.

### `var modelListAsked`

Beside `var modelList = null;`:

the `/api/models` answer every picker here is drawn from

### `var modelsHeard`

Beside `var modelListAsked = null;`:

its one fetch on load, which the first `load()` waits for

### `var modelSnap`

Beside `var modelsHeard = "";`:

the last `models` frame's `version` (#361)

### `var fleetPicker`

Beside `var modelSnap = null;`:

the `model` block of the last `/api/settings`

### `var landing`

Beside `var rowPickers = new WeakMap();`:

```text
a row's <tr> -> its pickers, its expansion, their options
```

### `function loadModelList`

Beside `var landing = location.hash.indexOf("#model-") === 0;`:

the model card's link, acted on once

In `}).catch(function () { });`:

no list: the pickers offer the default and `other…`

### `function listLine`

Above `function listLine(cat) {`:

The line over the table: where the list came from, and how old it is.

### `function inheritWords`

Above `function inheritWords(opts) {`:

A row's `inherit` pill says what it inherits. The picker reads its options at every draw.

### `function drawModels`

Above `function drawModels() {`:

Patched, never rebuilt: the keyboard, an open expansion and a half-typed `other…` survive every
`load()` after a save.

### `function modelRow`

Above `p.both = document.createElement("button");`:

Both halves back to the fleet's at once (#493): each toolbar's "" pill clears only its own.

### `function paintModelRow`

Above `var effortFrom = r.effort_source && r.effort_source !== r.source && r.resolved_effort`:

Each half says where it came from when the two differ (#493).

Above `text(cells[3], r.actual || "—");`:

Configured is not served. The tenant may pin a model, and a page that reported only what was
asked for would show a setting that is not what ran. This column is what the stream said the
last turn actually used.

### `function openExpansion`

Above `function openExpansion(p, focus) {`:

`more…`: a full picker for one row, inside that row's model cell -- never a sibling row, which a
keyed list strands on a reorder and orphans when its repository leaves. Built the first time and
kept; one is open at a time, and Escape or a pick closes it.

Above `p.expand.addEventListener("keydown", function (e) {`:

Escape is the host's (#362): it closes the expansion and gives the keyboard back to `more…`.

### `function landOnRow`

Above `function landOnRow() {`:

```text
The model card's link is `/settings#model-<repo>` (app.js): that row, scrolled to, opened, and the
keyboard on its pressed pill. Found by id, never by selector, so a dotted name is just a name.
```

### `function pickFleet`

Above `saveModel({ model: pick.model, effort: pick.effort }, pick.model, pick, "", null);`:

`~default` is `{model: "", effort: ""}`: no flag at all.

### `function pickRepo`

Above `function pickRepo(p, pick) {`:

A press writes the half its toolbar sets, and only that half (#493, decision 15): the other keeps
what the row holds or inherits, and a "" pill clears its own half.

### `function saveModel`

Above `function saveModel(body, model, pick, pinned, p) {`:

Post, then read the page back (the row is patched), then say what was saved. A pick made in an
expansion closes it and leaves the keyboard on the row's pressed pill, which is the one chosen.

Above `return model && !modelEntry(model) ? loadModelList().then(drawModels) : null;`:

A name the list did not have is in it now, as configured: asked again, it says whether
this CLI offers it.

### `function refuse`

Above `function refuse(p, message) {`:

A refusal is said on the `other…` box of the picker it came from (class `bad`, the reason as its
title), opened if it was not: a pill's id cannot be a second flag, so what refuses a pill is the
config file itself, and the box is where the row has room to say so.

### `if (modelRefresh) {`

Above `modelRefresh.addEventListener("click", function () {`:

The server asks on a thread of its own and answers at once (#361); a list that changed comes
back as a `models` frame.

## copilot

### `function controlFor`

Above `if (spec.min != null) el.min = String(spec.min);`:

The bounds the server refuses outside of, so the box's arrows stop where a refusal would start.

### `var SECTIONS`

Above `var SECTIONS = { copilot: "cfgrows", appearance: "tierrows" };`:

Each row lands in its section: the Copilot block, or -- for the pane's tiers (#235) -- under
Appearance, because they are how the desk is drawn.

### `function renderTierNote`

Above `function renderTierNote(tiers) {`:

What the desk is drawing with, when that is not what the boxes say: a four in the file that does
not go together -- a hand edit -- is drawn at CI's numbers, and this says why (#235).

## load

### `function load`

Above `if (!modelListAsked) modelListAsked = loadModelList();`:

The model list is asked for once (#367), and the first draw waits for it: every section comes
in one paint, and no picker is drawn empty and then again full.

Beside `landOnRow();`:

last: every section above the row is drawn

In `}).catch(function () { });`:

a settings page that cannot reach the server says nothing new

### `function connectTheme`

Above `function connectTheme() {`:

One frame, one reason: `config.json` changed under us. Without it this page would keep showing
the palette it was opened with while the desk beside it wore another.

Above `var stream = new EventSource(q("/api/events", { frames: "theme" }));`:

`frames=theme` (#348): this page listens for one frame, so it is sent no agent history.

In `} catch (e) { }`:

a frame we cannot read is not worth breaking the page over

Above `stream.addEventListener("models", function (m) {`:

The model list changed on disk (#361): a refresh from this page, another window or
`ad-fleet models --refresh`. Asked for again only when its `version` moved.

In `} catch (e) { }`:

as above

no stream is a stale page, not a broken one

### `loadThemes().then(function () { LOAD.settled = document.body.dataset.s …`

Above `loadThemes().then(function () { LOAD.settled = document.body.dataset.skin || ""; });`:

The skin the page settles on, for its load record (#351). Harmless when measuring is off.

### `if (LOAD.on) {`

Above `if (LOAD.on) {`:

While measuring is on (#351), the note that tells the desk this load came from here: a desk
opened from settings and a cold open both read `navigate`, and every page is `no-referrer`.

In `try { sessionStorage.setItem("fleet.load.from", "settings"); } catch (e) { }`:

not counted

### `var scope`

The agent the Copilot block and the permission lists are showing, from `?agent=<repo>` so a pane can
link straight to its own agent's settings. Empty is every agent. The page never decides what an agent
runs with: each agent's rows, their sources and its resolved allow/deny come back from
`settings_snapshot()["agents"]`, which reads them through `overrides.for_agent` exactly as a launch
does, so the page cannot show a value the launch would not use.

### `function scoped`

Every write the Copilot block makes carries `agent` when one is picked, so one control writes either
the fleet's value or that agent's, and the server's per-agent refusals (`not_per_agent`, `no_repo`)
answer a key that only means something fleet-wide.

### `function renderScope`

The picker's options are the registered agents. A picked agent that is no longer registered falls back
to every agent rather than drawing an empty block.

### `function renderConfig`

With an agent picked, only the settings an agent can have of its own are drawn, each with where its
value comes from and, when it is the agent's own, *use every agent's* to drop it. The appearance rows
stay fleet-wide (`fleetOnly`): they are how the desk is drawn, not how an agent is launched. With every
agent picked, a row that some agents override names them, because a fleet-wide change does not reach
those.

### `function listRow`

The list settings (`also allowed`, `also denied`, `extra directories`) are edited an entry at a time
and saved whole: the fleet's entries with every agent picked, the agent's own with one picked. The
fleet's entries still show under an agent, unremovable there, because they are on its launch too. A
broad entry (`powershell`, `bash`: every command that tool runs) is marked every time it is shown.

### `function renderCopilotConfig`

Copilot's own settings as the installed CLI documents them (`copilot help config`, cached by the model
refresh). A key a fleet setting covers is set per agent as a flag; every other one lives in
`~/.copilot/config.json`, which the operator's own chats share and the fleet never writes. Saying which
is which, key by key, is the answer to "my fleet settings and my Copilot settings are mashing up".

### `function draw`

One redraw of everything the scope changes, so picking an agent needs no second request: `lastData`
already holds every agent's view.
