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

Above `function loadThemes() {`:

Two controls, two tiers, and the difference is the point (#150, #154).

A PALETTE is colour only, so it is 1:1 with the terminal: the same hex reaches this page's custom
properties and the project's prompt and tab, and choosing one here writes
`~/.agentdata/config.json` -- the same file `ad-theme set` writes -- so every window on every
screen and the terminal beside them move together. A SKIN is how the page is RENDERED, which a
terminal cannot follow; it rides on a base palette and loads one extra stylesheet on demand.

Both post to the server rather than to `localStorage`, because a desk is four windows and a
choice kept in one browser's storage is four different desks.

Beside `if (t.name === "none") return;`:

"system" is already the first option

Above `text(option, t.title || t.name);`:

Its title, not its slug (#393). The tooltip adds what is drawn on it, as a supplement only:
it is hover-only, and never seen while a skin has the picker disabled -- `#palette-looks`
under the picker is where that is said.

Above `while (skinSel.options.length > 1) skinSel.remove(1);`:

One control, not two. A variant is not independent of its skin -- "Nether" means nothing on
its own, and a second picker offering it beside Farmstead would be offering a combination
that does not exist. Grouping them says the same thing the model does: pick a skin, and its
ground comes with it. A skin with one variant lists as a single option.

Above `if (themeNow) {`:

What is chosen, now that there is something to choose from. `themeNow` is whatever the
stream said while these options did not exist yet; it wins, because it is the later word,
and this answer paints nothing over it. Otherwise `current` is the stream's own payload
(#346), painted only when it carries css: a `current` without css is "not known", never
"no palette" -- read as the latter, it wiped the palette the stream had just applied.

In `}).catch(function () { });`:

themes are decoration; the page works without them

### `var themeData`

Beside `var themeNow = null;`:

the last word on what this page is wearing, from either path

### `function paletteCss`

Beside `var themeData = null;`:

the `/api/themes` answer: every palette's css, every skin's base

### `function looksOn`

Above `function looksOn(data, name) {`:

The looks drawn on a palette (#393), from an `/api/themes` answer: "Glass · Smoke" for every skin
variant whose base it is, in the skin picker's order. None means the palette is the plain page
only -- `palette_only` says why -- and it is still an ordinary palette to choose.

### `function looksLine`

Above `function looksLine(skin, palette) {`:

The line under the palette picker: what is drawn on the palette, or, while a skin is on, the look
the palette comes from -- words a keyboard, a touch screen and a disabled picker all show, which
an option's tooltip is not.

### `function choose`

Above `function choose(select, body) {`:

Paint, post, reconcile (#346). A pick is painted in the task that made it, from the css the server
already sent with `/api/themes` -- no palette maths here -- and only then posted. The answer is
the stream's own payload: equal values write nothing; a refusal puts back what was worn before
and says why on the control.

Above `var keep = themeSel ? themeSel.value : "none";`:

The palette stays the one the skin brought: the server keeps it as the default.

Beside `if (pendingTheme !== write) return;`:

a later pick is in flight; its answer decides

### `function reflectTheme`

Above `function reflectTheme(cur) {`:

One place that puts the server's answer into the two controls, so a change made in the terminal
or in another window shows up here rather than leaving the picker saying something else.

Above `[themeSel, skinSel].forEach(function (sel) { if (sel && sel.selectedIndex < 0) sel.selec …`:

A saved name that is no longer a palette leaves a select showing nothing at all, which is the
one thing a picker may never do: the operator cannot see what is on, or that anything is wrong.

Above `if (themeSel) {`:

While a skin is on, the palette is the skin's -- so the palette picker shows what is being
rendered and says why it is not taking instructions, rather than accepting a choice the server
would then override. Turning the skin off hands it back.

Above `if (themeData) text(document.getElementById("palette-looks"),`:

What is drawn on it (#393), said here and so on every pick too: `choose` reflects a palette in
the task that picked it. Before `/api/themes` has answered there is nothing to say it from.

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
