# Motion on the desk, and the budget it is kept inside

Before this, the desk had exactly one animation: the FLIP that carries a tile to its new place when
the grid reorders. Nine panels — the dock, the model card, the session menu, the away strip, the
notice, the asks card, the scope report, the approval card — appeared and vanished between one
frame and the next. Nothing was wrong with any of them individually. What was missing was the
thing the operator named: *"a lot of this is handling animations and transitions well"*.

The failure mode of taking that as licence is an interface where every animation looks fine on its
own and the whole thing feels slow. So the motion has a budget, and `tests/test_fleet_motion.py` is
what stops the budget being a comment.

## The three numbers

On `:root` in `app.css`, and nowhere else — a duration written into a rule is a duration nobody can
change from one place.

| Token | Value | For |
| --- | --- | --- |
| `--motion-fast` | 120 ms | something under the cursor: a hover, a press |
| `--motion-base` | 220 ms | something arriving or leaving |
| `--motion-slow` | 320 ms | a whole layout changing — and the ceiling for everything |

| Token | For |
| --- | --- |
| `--ease-out` | `cubic-bezier(0.2, 0.7, 0.3, 1)` — the default; fast out of the gate, settled at the end |
| `--ease-spring` | a small overshoot, for something that lands rather than stops |

`--ease-spring` is declared twice: a `cubic-bezier` first, then a `linear()` inside
`@supports (animation-timing-function: linear(0, 1))`. An engine that cannot parse `linear()` would
otherwise drop the whole declaration and fall back to `ease`, which overshoots nothing — the
fallback is the point of the pair, not decoration.

**The budget is asserted.** No duration anywhere in `static/` — `app.css` and every skin — may
exceed 320 ms. Nothing may repeat for ever except `.dot`, which says the event stream is alive and
is alive for as long as the stream is.

## Arriving and going away: one pattern, nine panels

```css
.enters {
  opacity: 1; translate: 0 0;
  transition: opacity var(--motion-base) var(--ease-out),
              translate var(--motion-base) var(--ease-out),
              display var(--motion-base);
  transition-behavior: allow-discrete;
}
.enters[hidden] { opacity: 0; translate: 0 -4px; }
@starting-style { .enters:not([hidden]) { opacity: 0; translate: 0 -4px; } }
```

Three things are doing work here and each is load-bearing:

* **`@starting-style`** gives the browser a state to animate *from*. Without it there is no "before"
  for an element that was `display: none`, and the panel simply appears.
* **`transition-behavior: allow-discrete`** lets `display` take part, so a panel that is leaving is
  still painted while it goes. Without it the leave is removed on the first frame and only the
  arrival is ever seen — the half-animation that reads as a glitch.
* **The longhand after the shorthand** is deliberate. An engine that does not know
  `transition-behavior` ignores that one line, `display` is not animated, and both directions are
  instant: exactly the behaviour these panels had before the rule existed.

The class is on the element in `index.html`, so the pattern is greppable from the markup and the
test can check that every panel the inventory lists carries it.

## One door for anything that moves things

`transitionLayout(fn)` in `app.js`. Opening a band, going back, hiding or showing a tile, and the
grid's zoom in and out all go through it — five gestures, one place that decides how a layout
change looks.

1. **Reduced motion** takes neither path. The change is applied and that is the end of it.
2. **`document.startViewTransition(fn)`** where the engine has it. The browser holds the last frame,
   runs `fn`, and morphs between the two states, so the layout is never caught half-applied. Each
   tile is given a `view-transition-name` derived from its repository name for the duration and has
   it cleared afterwards, so the same tile is matched to itself across the change rather than "the
   third tile" being morphed into whatever ends up third.
3. **FLIP** everywhere else, which is every IDE shell until it catches up with Chromium. Measure,
   change, invert, release — the existing `measureTiles`/`playFlip` pair, unchanged.

`fn` must apply the whole change synchronously: anything asynchronous inside it happens after the
browser has taken its "after" snapshot, and a morph to a state that has not arrived is a flash of
the wrong layout.

A superseded transition is ordinary, not an error. Two gestures inside one animation is the most
normal thing on this page, and the browser rejects **all three** of the first transition's
promises to say so. `finished` is the one that is acted on; `updateCallbackDone` and `ready` are
caught, because an unhandled rejection reaches the console as *"Transition was skipped. New
ViewTransition started"* — which is how this was found, as a page error on the slower of the two
CI runners.

Two edges are handled rather than assumed:

* `reorderDomTiles` does not play FLIP while a view transition is running (`inViewTransition`), or
  the same move is animated twice and the tile arrives, leaves and arrives again.
* Two repositories whose names sanitise to one CSS identifier make the browser skip the transition
  and apply the change with no animation. That is a degradation, not a break.

### The snapshots are images

```css
::view-transition-old(*), ::view-transition-new(*) { object-fit: none; object-position: top left; }
```

A tile is a box of text and a view transition animates *pictures* of the old and new states.
Scaling one picture to the other's size stretches the words, which is the giveaway that what is on
the screen is a photograph of a tile rather than the tile. Pinned to their own size at the top left,
what moves is the box and what cross-fades is text at the size it was written.

## Reduced motion

The universal block has been there since the beginning:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; … }
}
```

It does not reach a view transition. `*` matches no `::view-transition-*` pseudo-element, so those
are named explicitly in the same block. `transitionLayout` also refuses to start one — the
stylesheet says the same thing for a transition begun from anywhere else.

## What is measured, and where

`tests/test_fleet_motion.py`:

* the three tokens exist, are ordered, and the ceiling is the budget;
* no duration in any stylesheet exceeds it, and nothing but `.dot` repeats for ever;
* the reduced-motion block reaches the pseudo-elements;
* every panel in the inventory carries `.enters`;
* in Chromium, opening the session menu runs `opacity` and `translate` for `--motion-base` and
  nothing at all under `prefers-reduced-motion: reduce`; hiding it leaves the panel painted on the
  next frame rather than gone before it could be seen going;
* with `startViewTransition` deleted, the same gesture runs FLIP and the page lands identically —
  same open tile, same bands, and every `view-transition-name` cleared;
* a swap of five tiles at 1080p records **no `longtask`** and hands the main thread back inside
  50 ms.

That last one is a floor on what this code decides rather than on what the runner does. A headless
runner throttles `requestAnimationFrame` to whatever it likes — sixty-six millisecond gaps with the
page doing nothing — so a frame-rate assertion there would measure the runner. The frame gaps are
printed alongside the assertion, because the number is worth having in the job output even where it
cannot be asserted. On this container the swap runs at a 16.7 ms median with the call itself holding
the thread for 1.4 ms.
