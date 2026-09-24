# Rendering that earns its pixels

The rule this page exists to make checkable: **a picture on the desk has to say something the DOM
cannot, and it has to say it in words as well.** Everything below follows from that.

This is the page the ownership plan calls "the rules in themes.md". There is no `themes.md`; the
desk's documentation lives in this family — `desk-components.md` for what is drawn and who owns
it, `desk-motion.md` for how it moves, `desk-window.md` for how it is arranged, and this one for
what is painted rather than laid out.

**There is no 2D canvas on the desk (#257).** The trace and the ground were the two, and K of the
ink epic moved both to the ink layer ([desk-ink.md](desk-ink.md) §The page's own drawing). Nothing
under `static/` asks for a 2D context with `getContext`, and a test scans for one and watches the
page at run time. The one exception is the vendored three.js's own 1×1 feature probe, named there.

## The seven rules for a picture

1. **It reads the palette; it never carries one.** Every colour comes from a custom property: the
   trace's SVG is stroked in `var(--running)` and `var(--human)` by the stylesheet, and the ink
   layer reads the palette at paint time. A picture that holds its own hex stays the old colour
   when the operator changes theirs — which is the accent-stripe bug of #215 with a bitmap instead
   of a stylesheet.
2. **It follows the palette without being drawn again.** The SVG is rules, not pixels, so a
   palette that changes has already repainted it. The ink layer watches the palette and repaints
   its inks. Nothing in `app.js` has to remember to (it used to, for the canvas).
3. **It has a text twin.** `role="img"` and an `aria-label` carrying the same fact in a sentence.
   A picture a screen reader cannot read is a picture that is not there — and a sentence is also
   what a test can assert, which is why the trace's label is generated on the server beside the
   numbers rather than assembled in the page.
4. **It carries nothing the DOM lacks.** The trace draws `row.trace` and nothing else, written on
   the element as `data-ink-series` and `data-ink-ticks`, and the ink layer draws those. A picture
   that is the only place a fact appears is a fact half the fleet cannot reach.
5. **It is resolution-independent.** The SVG scales to whatever box the head gives it with
   `vector-effect: non-scaling-stroke`, and the ink layer draws at `devicePixelRatio` (to 2×). The
   old canvas had to size its own pixel grid to the screen; neither has a grid to get wrong.
6. **It costs what it claims to.** The ground drifts at one frame a second and none under reduced
   motion, counted in frames. The trace is written from a row the page already has, with `attr`,
   so a row that did not change writes nothing.
7. **No WebGL but the ink layer's, and only where it was measured.** `app.js` never touches
   WebGL. The ink layer (#248, [desk-ink.md](desk-ink.md)) is the one canvas on the desk, and it
   draws only on a shell whose WebGL probe said hardware ([desk-engines.md](desk-engines.md)).
   Every other shell gets the plain fallback, because a 3D ground that works on one of the four
   screens is worse than a flat one that works on all of them.
   Pixel-level HTML in WebGL (HTML-in-Canvas) waits for the gate in
   [desk-engines.md §Pixel-level HTML](desk-engines.md#pixel-level-html-384).

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

Drawn on a full pane's title bar (#233: a compact pane and a rail skip it, and the rail's label says
the state and its age in words). One point a minute on a single line, its height the share of the
busiest minute, and a minute that stopped for a person ticked full height in `--human` whatever
its count — *"it asked me something"* is not a quantity. A minute with anything in it is never
flat: one pixel above the floor is "it was awake", which is the difference between a quiet hour and
no hour at all.

**Where ink is drawn it is the ink layer's; everywhere else it is an SVG (#257).** `drawTrace`
writes the hour on the element twice from one set of numbers: as `data-ink-series` and
`data-ink-ticks`, which the ink layer draws in the pane's own lane as a pen line and red ticks, and
as the element's own `<polyline>` and `<path>`, which is the plain look. The SVG steps aside only
while a skin draws with ink, because a CSS skin's opaque pane would cover the layer's canvas (see
[desk-ink.md](desk-ink.md) §The page's own drawing). Plain, it is a polyline rather than sixty
bars because it is the same shape the pen draws, in two elements rather than sixty.

**The head carries it only where there is room.** `flex-wrap` wraps before it shrinks, so the
trace has to be gone by the width at which it *would* cause a wrap, not by the width at which it
stops fitting — a container query takes it off a pane under 560 px. (The column's bands carried
the same hour at full width for every agent at once; they went with #233, and a 48 px rail has no
width to draw an hour in.) A title bar that wrapped to two lines to fit a picture is a picture that
cost more than it is worth, and a test says so.

## The ground: drawn, so it can drift

The glass skin's ground is three saturated blobs. It is three `radial-gradient`s on `body` with
`background-attachment: fixed` — which cannot move, and a still image behind a frosted pane is the
thing that reads as a screenshot of an interface rather than an interface.

Where a shell draws ink, the glass skin's own ink module draws the same three blobs as a lit mesh
in the layer's `ground` slot and drifts them (#254, [skin-glass.md](skin-glass.md)). It was a canvas
of `app.js`'s, `#ground`, from #218, and #257 took it away. Slow enough that nobody can point at it;
enough that the room has a window in it.

* **The mesh has one owner.** `skin.css` declares the blobs as custom properties, `skins.py` holds
  the same numbers and a test reads them back; the ink module reads the properties at paint time.
* **It holds still when asked to.** `prefers-reduced-motion: reduce` stops the drift, and so does
  `prefers-reduced-transparency: reduce` — the second is the one people forget, and it is the
  setting somebody turns on *because* a moving translucent ground is what they cannot read over.

Every shell without ink shows the stylesheet's gradients themselves, standing still: the plain
fallback has no animation. Every skin with no gradients on `body` is untouched.

## What is measured

`tests/test_fleet_trace.py`:

* the fold — sixty buckets oldest first, what falls outside the hour stays outside it, the
  sentence in every plural it has;
* the row carries numbers and one sentence, under 700 bytes;
* there is no canvas in the markup, the trace has `role="img"` and a label, and neither `webgl`
  nor `getContext` is anywhere in `app.js`;
* nothing under `static/` (minus the vendored three.js) asks for a 2D context, and at run time no
  canvas on the page is asked for one, with ink on or off;
* in Chromium, the plain trace has a point a minute, raised for every minute with something in it,
  and exactly two ticks in the palette's own `--human`, and the series the ink layer reads is the
  same hour;
* changing the palette recolours it with nothing drawn again;
* with ink, the trace is a pen line and red ticks in its pane's lane, it follows its data and is
  erased when the hour empties, and the SVG steps aside;
* with ink, the ground is the layer's, three blobs, drifting at a frame a second and still under
  reduced motion; without ink, the stylesheet's gradients and the SVG are the page's own;
* and the trace never costs the head a second line, at five window widths.
