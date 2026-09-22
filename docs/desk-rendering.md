# Rendering that earns its pixels

The rule this page exists to make checkable: **a canvas on the desk has to say something the DOM
cannot, and it has to say it in words as well.** Everything below follows from that.

This is the page the ownership plan calls "the rules in themes.md". There is no `themes.md`; the
desk's documentation lives in this family — `desk-components.md` for what is drawn and who owns
it, `desk-motion.md` for how it moves, `desk-window.md` for how it is arranged, and this one for
what is painted rather than laid out.

## The seven rules for a canvas

1. **It reads the palette; it never carries one.** Every colour comes from a custom property at
   paint time, through `token(name, fallback)`. A canvas that holds its own hex stays the old
   colour when the operator changes theirs — which is the accent-stripe bug of #215 with a bitmap
   instead of a stylesheet.
2. **It repaints when the palette changes.** The `theme` stream frame clears the token cache and
   draws every trace again. A picture is pixels, not rules: nothing else will do it.
3. **It has a text twin.** `role="img"` and an `aria-label` carrying the same fact in a sentence.
   A picture a screen reader cannot read is a picture that is not there — and a sentence is also
   what a test can assert, which is why the trace's label is generated on the server beside the
   numbers rather than assembled in the page.
4. **It carries nothing the DOM lacks.** The trace draws `row.trace` and nothing else. A canvas
   that is the only place a fact appears is a fact half the fleet cannot reach.
5. **It is `devicePixelRatio`-aware.** A canvas has two sizes — the box the page lays out and the
   grid of pixels it owns — and on a 2× screen they are not the same number. A canvas that
   ignores the difference draws a blurred copy of itself.
6. **It costs what it claims to.** The ground repaints once a second and is asserted under 4 ms of
   script; the trace is drawn from a row the page already has.
7. **No WebGL.** Not until slice F's engine rows say PyCharm's JCEF and VS Code's Simple Browser
   run it behind a corporate proxy. A 3D ground that works on one of the four screens is worse
   than a flat one that works on all of them.

## The trace: an hour in sixty numbers

A tile says what an agent is doing *now*, and carries the last forty events for its transcript.
What it could not say is the shape of the hour — whether this quiet minute follows fifty busy ones
or four hundred quiet ones, and whether the operator has already been asked something in that
time. Those are the two questions somebody scanning nine tiles is actually asking, and
`idle · 3m` answers neither.

`agentdata/fleet/trace.py` folds the stream into sixty buckets, one a minute, oldest first:

| Field | Is |
| --- | --- |
| `n` | sixty counts, one a minute |
| `needs` | sixty flags: 1 where a minute held a `question_opened`, `denied` or `error` |
| `total`, `needed`, `said`, `peak` | the hour's totals |
| `says` | the sentence — *"40 events in the last hour, needed you twice"* |

Small integers and one sentence, about 400 bytes.

**Folded from the tail, not the head.** This runs on every row of every snapshot, several times a
second, and an agent that has been going all day has tens of thousands of events; parsing every
stamp in all of them to find the last sixty minutes would be the most expensive thing the server
does. The scan runs backwards and stops once the stream is properly out of the window — `64`
consecutive older events, not one, because arrival order is not quite timestamp order and a
replayed log can step backwards for a handful of rows. The stamp itself is *sliced* rather than
parsed: `events.stamp()` writes exactly `YYYY-MM-DDTHH:MM:SS`, and `int()` on seven slices is the
same answer as `strptime` for a tenth of the cost, with the parser kept as the fallback for
anything that does not fit the shape. A day's stream of 40,000 events folds in 0.2 ms, and a test
holds it there. No text from the transcript ever leaves here:
the trace is on every row of every window several times a minute, and a transcript on that path is
the payload problem this repository keeps having, one field further along. The bucket edges are
whole minutes back from now, so a bar does not change width as the second hand moves — only the
whole row shifts when a minute turns over.

Drawn on the tile's title bar and on every band. One bar a minute, its height the share of the
busiest minute, and a minute that stopped for a person drawn full height in `--human` whatever its
count — *"it asked me something"* is not a quantity. A minute with anything in it is never
invisible: one pixel is "it was awake", which is the difference between a quiet hour and no hour
at all.

**The head carries it only where there is room.** `flex-wrap` wraps before it shrinks, so the
trace has to be gone by the width at which it *would* cause a wrap, not by the width at which it
stops fitting — a container query takes it off a tile under 560 px. Below that the column's bands
carry the same hour at full width, for every agent at once. A title bar that wrapped to two lines
to fit a picture is a picture that cost more than it is worth, and a test says so.

## The ground: drawn, so it can drift

The glass skin's ground is three saturated blobs. It was three `radial-gradient`s on `body` with
`background-attachment: fixed` — which cannot move, and a still image behind a frosted pane is the
thing that reads as a screenshot of an interface rather than an interface.

`#ground` is a canvas, fixed behind everything, painting the same three blobs and drifting a pixel
a second around a two-minute circle. Slow enough that nobody can point at it; enough that the room
has a window in it.

Three things about it are deliberate:

* **The mesh is read out of the stylesheet, not written here.** `groundColours()` parses
  `getComputedStyle(body).backgroundImage` — Chromium's normalised form of each gradient, which is
  where the ellipse's size, its place and its colour all are. `skins.py` and `skin.css` already
  keep one copy of those numbers between them and a test reads them back; a third copy in `app.js`
  would be the two-owners bug with a longer fuse. The read happens *before* the class that blanks
  the gradients, because a source that has been turned off reads as `none`.
* **It paints at half resolution.** Three soft blobs with no edge in them: the pixels nobody can
  distinguish are pixels nobody should pay for, and this is the one canvas that covers the whole
  window.
* **It holds still when asked to.** `prefers-reduced-motion: reduce` stops the drift, and so does
  `prefers-reduced-transparency: reduce` — the second is the one people forget, and it is the
  setting somebody turns on *because* a moving translucent ground is what they cannot read over.

Every other skin is untouched: no mesh, no canvas, and `body` keeps whatever background it had.

## What is measured

`tests/test_fleet_trace.py`:

* the fold — sixty buckets oldest first, what falls outside the hour stays outside it, the
  sentence in every plural it has;
* the row carries numbers and one sentence, under 700 bytes;
* every canvas in the markup has `role="img"` and a label (or is `aria-hidden`, which the ground
  is — it says nothing, so it says so), and no `webgl` anywhere in `app.js`;
* in Chromium, the drawn trace has a mark for every minute with something in it and exactly two
  full-height marks in the palette's own `--human`, read back off the canvas with `getImageData`;
* changing the palette repaints it to the colour the stylesheet now has;
* the ground reads three blobs, the gradients are blanked so nothing paints twice, the drift timer
  is off under reduced motion, and a repaint's median is under 4 ms;
* and the trace never costs the head a second line, at five window widths.
