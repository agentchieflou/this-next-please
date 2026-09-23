# Instant

None of what this page describes was slow code. It was a page asking permission to draw what it
already knew.

* **Hiding a tile posted `arrange` and waited for the answer before anything moved.** On a local
  server that is thirty milliseconds; on a laptop with nine projects folding it is not, and either
  way it reads as a form rather than a desk.
* **Every action fetched the whole fleet afterwards.** Replying to one agent carried nine tiles
  across the wire so that one of them could be redrawn — and the reply the operator had just typed
  went through a second round trip before the tile agreed it had been sent.
* **A reopened window showed an empty grid** with a sentence about having no projects, for as long
  as the first fold took. That is the wrong answer to "what is my fleet doing", given confidently.

The order is paint, post, reconcile — and say so out loud when the server disagrees.

## Optimistic, with a way back

`arrangeNow(patch, apply, what)` is the only writer of the arrangement. Everything that moves a
tile goes through it: hide and show, move, drop, pin, resize, show-everything.

```js
var undo = apply();                 // write it into the local arrangement, keep the old one
transitionMove(function () { place(); });
post("arrange", patch).then(function (r) {
  if (r.ok) { mergeDesk(r); place(); return; }
  undo();                           // put it back
  place();
  say(r.error + (r.hint ? " — " + r.hint : ""), 10);
});
```

`apply` answers with the function that writes the old arrangement back. A refusal restores it *and*
says why, in the server's own words with the server's own hint — a tile that silently returns to
where it was is a page the operator stops trusting, which is worse than the refusal.

**Rearranging uses FLIP, never a view transition.** The distinction is not taste. FLIP moves the
very elements, so the change is in the DOM on the frame the gesture happened in and the animation
is a transform on top of it; `startViewTransition` morphs *pictures*, so it has to hold the old
frame for one more frame while it takes its snapshot. For "this tile is now over there" the first
is both faster to show and truer. Opening an agent, which replaces what is on the glass rather than
moving it, still takes the view transition — see `docs/desk-motion.md`.

## One round trip, not two

`ROW_ACTIONS` in `serve.py` names the seventeen actions that change one repository's row. The
endpoint answers each of them with that row:

```json
{"ok": true, "action": "send", "repo": "luna", "row": { ... }}
```

and `action()` patches from it:

```js
if (r.row) { patchRow(r.row); place(); }
else refresh();
```

`patchRow(row, index)` is lifted out of `refresh()`, so an action's answer and a whole snapshot take
the same path through the page and a tile cannot be drawn one way by one and another way by the
other. The `else` is not dead: `arrange` and `window` change the *arrangement* rather than a row —
that reaches every window down the stream — and an older server that does not send a row still
works.

## Stale, then right, and honest about which

The last snapshot this window saw is kept in `sessionStorage` and drawn first, and the fetch that is
already in flight replaces it. Without the transcripts: they are the big part of the payload, the
part that goes stale fastest, and the stream brings them back within the second anyway. Five
minutes old at most — past that the shape of the fleet has probably changed, and a wrong desk held
for a second is worse than an empty one.

The snapshot is taken again as the window goes (`pagehide`), with the desk the window holds and the
agent it has open. Taken only from the fleet's answers it was older than the last click, and a
reload reopened the agent from before it, then jumped when the fleet answered: #230's snap-back, on
the reload path. Its version is not believed, so the first real answer always wins.

While it is showing, `body.is-stale` dims the glass a little and the footer says *"the last view,
while this one loads"*. A stale desk that does not admit it is a desk that lies for a second, and a
second is long enough to act on.

`restoreCached()` is called at the very bottom of `app.js`, not beside the `refresh()` that starts the
fetch, because drawing a row touches module state — `departed`, the tiles map — that is `undefined`
until the script has finished evaluating.

## The budget

Every local gesture — one the page can answer out of what it already has — is marked at both ends
with `gesture(name)` and `settle(mark)`, so "instant" is a number somebody can read rather than an
adjective.

| Gesture | Marked |
| --- | --- |
| any action | `action:<what>` |
| any arrangement change | `arrange:hide` / `move` / `drop` / `pin` / `size` / `showall` |
| this window's record | `window` |
| opening an agent | `open:band` |

The budget is **50 ms**, asserted in a browser by `tests/test_fleet_instant.py`. The `open:band`
mark is closed *inside* the transition callback rather than around the call: the view-transition
path runs it on the frame after the browser has taken its snapshot, and a mark closed before the
work happened would report nought and mean nothing.

On this container the worst local gesture measures about 6 ms.

## No spinner

There is no spinner, loader, throbber or busy overlay anywhere on the desk, and no `aria-busy` or
`role="progressbar"` either — a test says so over the markup, the stylesheet and the scripts, with
comments stripped first so that this page's own explanation stays writable.

A spinner over real content is an apology for content nobody asked the page to withhold. Where
something genuinely is in flight, the control itself is the indicator: a Send that has been pressed
is dimmed and says *"Send anyway"* if the server refused it. Where the whole desk is loading, the
last one is on the screen, saying so.

## What is measured

`tests/test_fleet_instant.py`:

* hiding a tile paints inside the 50 ms budget against a server held for two seconds, and the POST
  has demonstrably not answered when it does;
* a refused `arrange` restores the previous arrangement and puts the refusal and its hint on the
  notice line;
* an action makes exactly one request and patches its tile from the answer — counted, with the
  stream closed and its timers drained, so what is counted is the gesture's decision and not the
  server's heartbeat;
* every marked gesture is inside the budget;
* a reopened window shows its three tiles immediately, marked stale, while a fleet held for a
  second and a half loads;
* and nothing on the page is a spinner.
