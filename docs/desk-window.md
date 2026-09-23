# The tile as a window

The grid had HTML5 drag on a tile's head and one width toggle: one column or two. Three things
were wrong with that, and none of them is a matter of taste.

* **The gesture said nothing was happening.** The browser drew its own translucent copy of the
  tile and the tile itself stayed exactly where it was. Direct manipulation that does not move the
  thing is not direct manipulation.
* **On a trackpad it needed a press-and-hold** nobody discovers, because that is what HTML5 drag
  asks for when there is no mouse button held down over a `draggable` element.
* **A tile could be made wider and never taller.** `size: 2` was one number, and one number can
  only answer one question.

## A width is the window's, and a weight

What #217 called the footprint was `size: {cols, rows}` in the shared arrangement: a span of the
grid's tracks, two numbers where there had been one. The row of panes (#233) has no tracks to span
and no rows to span down, and the gutters (#234) replace it with **widths**, in each window's own
record:

```json
"windows": { "left": { "open": "alpha", "widths": { "alpha": 1.2, "beta": 0.8, "gamma": 0 } } }
```

* **0 is a rail**; any other number is that pane's **share** of what the rails leave. A weight
  rather than pixels, so a window made narrower scales the wide panes and leaves the rails alone.
* **Per window**, because a laptop and a 4K monitor cannot share pixels, and because the left
  monitor holding alpha wide while the right one holds beta is the one job `screens` had
  (plan-panes §Where this plan pushes back, item 4). The order and what is hidden stay the desk's.
* **A window with no widths** draws the row as it was before the gutters: the open pane and every
  pin wide, each at the `size.cols` an older build left it (plan-panes' migration: `size.cols`
  becomes the weight), and everything else a rail. Nothing is written to make that so; the first
  gesture that changes a width writes the whole row.
* **One writer on the page.** `paintWidths` writes `is-solo` (the pane has a width) and `--w` (its
  share), and the stylesheet reads nothing else:

  ```css
  .tile.is-solo { flex: var(--w, 1) 1 0; min-width: 160px; }
  ```

  `flex-basis: 0` and `border-box` make a pane's width its edges (padding and borders, which
  `flex-grow` does not share out) plus its share of the rest. A weight read off a width has the
  edges taken away first (`paneEdge`), which is what lets a gutter move two panes and leave every
  other one to the pixel.
* **One write** per gesture: `POST /api/window {w, widths, version}`. `version` is the desk version
  the page last heard, read as the post goes; a write of widths older than the ones the record
  holds -- another page under the same `?w=` moved them first -- is refused `widths_stale`, and the
  page puts its own back and reads the desk again. `widths` that are not repository-to-weight are
  refused `widths_shape`.

`size` is still read and kept by the server (`serve.size_cell`, both of its spellings, columns
capped at 4) because desk.json files written before this carry it; `POST /api/arrange` still takes
it, and no page sends it.

## Dragging

Pointer events, with capture. `bindDragToReorder(handle, host, name)`:

| | handle | host |
| --- | --- | --- |
| an open pane | `.head` — the title bar, with its grip | the pane |
| a rail | `.pane-rail` — the face, one button filling the rail | the pane |

The rule for what a press means: **a press on a control inside the handle belongs to that
control, unless the handle *is* the control.** A pane's head is a plain `div`, so every button in
it is somebody else's; a rail's face is one button, so a press anywhere on it is the rail's. (The
column's band, #203, was the same shape: one button filling the row. It went with #233.)

Four pixels of travel before anything moves — a click on the head still selects the project, and
a click on a rail still swaps it in — and then the host is translated under the cursor and
whatever is under the pointer is lit `drop-before` or `drop-after`, measured along the axis the
list runs on: across, because there is one row. `Esc` cancels and the arrangement is untouched.
The drop is optimistic: the order changes under the hand and the server's answer is what the next
draw reads. A reorder never changes which agent is open: until something opens one, the open
agent is only "the first in the order", so `holdOpen()` writes it down before the order moves
(#233 — a rail can be dropped before the open pane now, which the column never allowed).

Five details are each a bug that happened:

1. **The capture is taken on lift, not on `pointerdown`.** While an element holds the pointer
   capture the browser retargets the compatibility mouse events to it as well, so capturing early
   sent the `click` that ends an ordinary press to the head rather than to the repository name
   inside it — and clicking the name, which is how a tile is opened, silently stopped working.
2. **The move and up listeners are on the document.** A head is twenty pixels tall and the pointer
   is off it before it has travelled far enough to count as a drag, so a handle that listened to
   itself heard the first move and none of the others.
3. **The title bar is not selectable.** `draggable="true"` used to suppress text selection as a
   side effect. Without it the first drag selected text from one tile to another, and the second
   drag in a row became a native drag of that selection — which arrives as `pointercancel` and
   ends the gesture on the frame it began.
4. **`.is-dragging` gets `pointer-events: none`,** for any host and not only a tile, so
   `elementFromPoint` answers with what is underneath rather than with the thing being dragged.
5. **A draw does not reorder the DOM while a drag is in flight.** The stream draws several times a
   second; a reorder mid-drag is a tile that jumps out from under the cursor.

The click that ends a real drag is swallowed once, because on a head it would select the project
and on a rail it would open the agent — neither of which is what the hand just asked for. So is the
one that ends a drag put down with `Esc`: the button is still held when `Esc` is pressed, Chromium
sends the release's `click` to the handle, and on a rail that opened the agent the operator had just
cancelled moving (#233, `tests/regressions/test_20260923_any_escape_drag_opens_rail.py`).

## Resizing: the gutters (#234)

A gutter between every two panes on the glass: a 1px line in the row's 6px gap, and an 8px strip
laid over the pane's right-hand edge to take hold of, so it costs the row no width. It is the pane's
own last child -- the pane on its left owns it -- and `drawGutters` shows it on every pane but the
last. A rail keeps its gutter, because a rail is pulled wide by one.

* **Dragging it moves width between those two panes and nothing else.** Every other pane keeps its
  left edge and its width, to the pixel. That is the rule that makes a resize predictable.
* **The snaps**, while the hand is on it: a pane pulled under 120px settles to a 48px rail; a pane
  with a width is never under the compact minimum, 160px; and within 8px, either side at 160 or at
  the full minimum (360px), or an even share with the neighbour, takes the hand. `snapPair` is the
  one function, and the keys go through the same floors (`settlePair`).
* **The drag is the preview.** #217's ghost was there because a span snapped on release and the
  hand could not see where it would land. A gutter draws the real layout under the hand: when it is
  first moved, every wide pane's share is made its width less its edges, and then each animation
  frame writes the two panes' shares and nothing else (`paintHeld`, marked `gutter:frame`). No
  `place()` -- it waits while a gutter is held and runs when the hand comes up -- no redraw and no
  reorder: #217's "a draw in the middle of a drag no longer puts the gesture down" is the lesson.
* **Pointer capture on the press.** A gutter has no click of its own to lose to the capture (the
  reason the reorder drag captures only on lift), and the hand leaves an 8px strip on the first
  pixel of travel. The move and release are heard on the document as well, so an engine without
  `setPointerCapture` resizes just the same. While one is held the whole page says `col-resize`.
* **One write, on release,** through `widthsNow`: painted already, posted once, put back with the
  server's words if it is refused, and offered back from the footer (`undo`, or `u`, for twelve
  seconds). **`Esc`** with the button still down puts every width back and writes nothing -- and is
  not also the page's own `Esc`, which would go back a pane.
* **A double click** evens the two panes beside it. Its two presses write nothing of their own, and
  neither selects the project nor opens the pane, which is what a click and a double click on a
  pane mean.

The tier a pane draws at follows its width through the one observer (#233). Its slack is only
between compact and full: a pane is a 48px rail or at least 160px wide, so nothing sits on the
rail's boundary, and the slack that was there drew a rail pulled out to exactly 160px as a rail's
face stretched across it.

## Opening one, and opening one beside

* **A press on a rail** swaps it in: it takes the width of the pane that had the keys, which becomes
  a rail in its own slot -- the column's gesture, kept because the operator already has it. In a
  window with widths it is one write of `open` and the widths together. `Enter` on a rail's face is
  the same press, and `Esc` goes back.
* **Shift and a rail** opens it beside the pane that has the keys: the two split what that pane had
  and the rail's own 48px, so nothing else in the row moves, and the keys stay where they were.
  `Shift+Enter` on a rail's face is the same.

## The presets

One segmented control in the header, where the arrangement picker was: **one** (`1`) -- the pane the
keyboard is on, or else the open one, wide and every other a rail; **all** (`=`) -- an even share
each, and the tiers decide what that looks like on this glass; **needs me** (`f`) -- every agent that
needs a person wide, the rest rails, and the keys moved to one of them. Each is one write, undoable
from the footer, and applies at once under reduced motion. They are presses, not modes: *needs me*
replaced the needs-only filter (#207's second focus), which dimmed the quiet rails and kept a
`held` list so the agent just answered would not dim under the reply. A preset takes nothing back
when an agent stops needing you, so neither is left. With nobody needing you it writes nothing and
says so, because a row of rails and nothing open is the blank window the desk exists to stop.

## Minimise and maximise

Both are gestures the desk already had, under names only this page used.

* **Minimise** is the hide button — `setHidden(repo, true)`, or `h` on a rail. The pane leaves the
  row and keeps its place in `order`, so reopening puts it back where it was, and the footer's
  `N hidden` is the one click that does (#233).
* **Maximise** is `openAgent(repo)`, and it takes the width toggle's place in the head.

The width toggle went because the gutters answer that question with more than two answers, and
because adding two buttons to a head that was already crowded is the information overload this
epic exists to remove. `Alt+Enter` evens the pane with the one on its right now (#234): the
double click on the gutter between them.

## Keys

| Keys | Does |
| --- | --- |
| `←` / `→`, `j` / `k` | along the row: the keyboard to the next pane |
| `Alt+←` / `Alt+→` | move the pane one visible slot (on a rail as well) |
| `Alt+Shift+←` / `Alt+Shift+→` | the gutter on the pane's right, one step: 40px, and out of a rail or into one in a single press |
| `Alt+Enter` | the double click: the pane and the one on its right, evened |
| `Alt+Home` | pin first |
| `h` | minimise |
| `Enter` on a rail | maximise: the swap (#233) |
| `Shift+Enter` on a rail | open it beside the pane with the keys |
| `1`, `=`, `f` | the presets: one, all, needs me |
| `2`–`9` | open the pane with that number |
| `u` | take the last change of widths back |
| `Esc` | put a drag down, the gutter's or the reorder's, with nothing written |

The resize is the shifted pair because `Alt+arrows` has moved a tile since #5, and a gesture
somebody has learned is not one to take away for a new one. `Alt+Shift+↑` / `Alt+Shift+↓` went with
`rows`: a pane is always the row's full height. `1` was the first pane's number until the presets
took it, the plan's key for *one*; the digits open panes from `2`, and the first is `j` from nowhere
or `1` with the keyboard on it, which makes it the one wide pane.

## Reduced motion

The drag still works; it simply does not settle. `transitionLayout` refuses to start a transition
under `prefers-reduced-motion: reduce`, and the drop applies the new order directly —
`docs/desk-motion.md` has the rest. The swap and the presets apply at once; the gutter drag is
unchanged, because it was never an animation.

## What is deliberately not here

No overlap, no z-order, no free placement, and no drag inertia. The desk is one row of panes, and a
window that can be put anywhere is a window that can be put somewhere nobody can find it.
