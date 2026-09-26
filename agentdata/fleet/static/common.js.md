# `common.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

What both pages need, and neither owns.

The desk (`app.js`) and the settings page (`settings.js`) are two pages, not two copies: each
loads this file first and then its own. Plain non-module scripts share one global scope, so a
name declared here is simply available in the other -- no build step, no imports, and nothing
fetched from the internet, which is the constraint the desk has always had (it must load inside
PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy).

What lives here is what a SECOND page genuinely needs: the run token and the two functions that
put it on every request, `pageUrl()` for the links between the pages (they keep the host's `w`,
`shell` and `ink`), the one-line text setter, and the two painters that turn a palette and a
skin into what you see. What deliberately does not: anything that assumes a desk.
`rehome()` stays in `app.js` because it always rebuilds a destination through `/open`, which
hard-codes `/?t=` -- sending it from here would bounce an operator off the settings page mid-edit.

### `function q`

Above `function q(path, params) {`:

Every route but `/api/ping` and `/open` wants the token, and a relative URL in the markup does
not inherit the query string the operator opened. So no fetch is written by hand: they all go
through here.

### `function pageUrl`

Beside `var CARRIED = ["w", "shell", "ink"];`:

the page's identity in its host; nothing else travels

### `var onAuthLost`

Above `var onAuthLost = null;`:

A 403 means this page is holding a token the server no longer has -- it was restarted, and the
run token is per run. What to do about it differs per page, so the page says: the desk goes back
through `/open` to collect a fresh one, and only once its stream has already died. A page that
sets nothing simply gets the error, which is the safe direction to be wrong in.

## the render contract (#215)

Created once, patched forever. `place()` runs about two and a half times a second while an agent
is talking, and a page that rewrote its own DOM on every pass took the hover off whatever was
under the cursor and the keyboard off whatever had just been reached. Every setter below writes
only when the value actually changes, so a draw with nothing to say is a draw that touches
nothing -- which is what a `MutationObserver` at zero asserts, per component.

### `function attr`

Above `function attr(el, name, value) {`:

`null`, `false` and `undefined` remove; everything else sets. Writing an attribute to the value
it already has is still a mutation as far as the platform is concerned.

### `function patchList`

Above `function patchList(parent, rows, keyOf, create, update) {`:

One list reconciler for the whole page: chips, cells, sessions, bands, patterns, rows.

Keyed, because the alternative -- tear the list down and clone it again -- is what destroyed the
hover, the focus and any transient state on every one of them, several times a second. `create`
makes a row's element the first time it is seen; `update` patches it every time after. Rows that
go are removed; the order is fixed only when it is actually wrong, because `appendChild` blurs
whatever it moves.

### `function applyTheme`

Above `function applyTheme(cssVars, themeName) {`:

A PALETTE is colour only, so it is 1:1 with the terminal: the same hex reaches this page's custom
properties and the project's prompt and tab. Writing one goes to the server -- the same
`~/.agentdata/config.json` that `ad-theme set` writes -- and never to `localStorage`, because a
desk is four windows and a choice kept in one browser's storage is four different desks.

Above `tokens.forEach(function (k) {`:

Written only where it differs: every refresh applies the theme again, and an idle desk is
zero DOM mutations (the render contract) -- a write of the same value is still a mutation,
and it wakes everything that observes the root, the ink layer among them (#256).

Above `attr(root, "data-theme", "custom");`:

Written only when it changes (the render contract): every snapshot applies the theme again,
and an attribute set to the value it already has is still a mutation to every observer.

### `function applySkin`

Above `function applySkin(skinName) {`:

A skin is one stylesheet; a VARIANT is that same stylesheet drawn against a different palette,
selected by an attribute rather than by a second file. Nether and Overworld share every bevel and
every sprite and differ in their colours, so shipping them as two stylesheets would be shipping
the same art twice and letting the two copies drift. Switching variant therefore re-paints
without a fetch, and only changing skin loads anything.

Beside `if (link.href !== href) link.href = href;`:

re-assigning re-fetches and flashes the page

Above `attr(document.body, "data-skin", family);`:

Written only when they change (the render contract's `attr`): every `/api/fleet` answer
carries the theme, and a desk that rewrote the same three attributes on each was an idle desk
making DOM mutations -- and an ink layer, which follows them, repainting for nothing (#254).

## #219: how long a gesture took

Every local gesture -- one the page can answer out of what it already has -- is marked at both
ends, so "instant" is a number somebody can read rather than an adjective. The budget is 50ms,
and `tests/test_fleet_instant.py` asserts it in a browser; the runbook records the laptop's.

Wrapped, because `performance.mark` throws on a name it has already seen in some engines and a
page that will not draw because it could not time itself is the worst possible trade.

## #351: how long a load took

```text
While the operator has switched measuring on (`fleet.loads.enabled`, #350), the server serves
the desk and /settings with `data-measure="loads"` on <html>, and each such document posts ONE
record of its own load as it goes (`pagehide`), which `ad-fleet engines` prints as the `loads`
table. With the attribute absent -- the default, and always on /probe -- nothing here registers,
observes or touches storage. Everything is read, nothing is written to the page: the paint time
comes from the performance timeline and the long tasks from PerformanceObserver, and the ink's
first frame from the counter the layer already keeps (`Ink.inspect().layer.renders`), because no
entry type sees a WebGL frame.

`from` is the note /settings leaves in sessionStorage as it goes: every page is served
`Referrer-Policy: no-referrer` and a navigation entry reads `navigate` both for a cold open and
for settings -> desk, so the page says where it came from. Every read is wrapped: a page that
cannot time itself still works.

A close does not always run `pagehide` (#481). Chrome gives a closing page's unload handlers
500 ms (`kUnloadTimeout`, render_frame_host_impl.cc) and closes it without them after that, so a
page still busy when it is closed -- the slow load this table exists to see -- would post
nothing. Where the engine has `fetchLater` (Chromium 135+), the record is also queued with it,
queued again each time a measurement lands, and cancelled once pagehide's beacon is on its way;
the browser sends a copy still queued when the document goes. One record either way.
`LOAD.queued` is that copy's body, "" where there is none.
```

### the closure › `if (desk) {`

In `} catch (e) { }`:

no storage: a cold open, as far as the table can tell

### the closure › `function ms`

Beside `var later = null;`:

the AbortController of the copy queued with fetchLater

### the closure › `observe("paint", function (entry) { if (entry.name === "first-paint") …`

Above `observe("paint", function (entry) { if (entry.name === "first-paint") queue(); });`:

A cue to queue the record again, no more: the paint is read from the timeline as the record is
written, so one the browser has reported is in it before this callback has had its turn.

### the closure › `try {`

In `} catch (e) { }`:

no frames, no first skin

### the closure › `var settled`

Above `var settled = LOAD.settled;`:

The desk and /settings say they have settled by setting `LOAD.settled`: queue again then.

### the closure › `try {`

In `} catch (e) { }`:

a plain field: the other measurements still queue it again

### the closure › `var inkDone`

Above `var inkDone = !desk;`:

The ink's first frame: read-only, each frame, until the layer has drawn once. It stops, leaving
the field out, when the verdict is off or there is no layer, after 10 s, or at pagehide. It
never writes to the page and never asks the layer to draw.

### the closure › `function lookForInk`

Above `var ink = window["Ink"];`:

Until ink.js has run, `window.Ink` is Chromium's own `Ink` interface (the delegated ink
trail API), a function with no `inspect`: the layer's front door is the one that has it.

Above `var canvas = document.querySelector("#ink");`:

The layer's canvas, which the layer adds (layer.js); it is in no page's markup.

### the closure › `function record`

Above `function record() {`:

The record as it stands now, as the body both senders post.

Above `var paint = performance.getEntriesByType("paint").filter(function (e) {`:

Chromium reports a first paint only once its frame has been presented, which under load is
hundreds of ms after the frame itself; a page gone before then has none to send.

Beside `tasks.takeRecords().forEach(task);`:

timed by the browser, not yet handed to the callback

### the closure › `function queue`

Above `function queue() {`:

Queue the record as it stands with fetchLater, and cancel the copy queued before it.

In `} catch (e) { }`:

refused (its quota, a permissions policy): the copy already queued stands

### the closure › `window.addEventListener("pagehide", function () {`

Above `if (navigator.sendBeacon(q("/api/load"), new Blob([body], { type: "text/plain" })) && la …`:

The beacon on its way, the queued copy is cancelled and never sent: one record, not two.

In `} catch (e) { }`:

a load that cannot be sent is a load not counted, never a broken page
