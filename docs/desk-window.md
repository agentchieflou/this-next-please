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

## The footprint is two numbers

`size` in the arrangement is `{cols, rows}`.

```json
"arrangement": { "size": { "rdsd-pbi-reporting": { "cols": 2, "rows": 1 } } }
```

`size: 2` — which is what every `desk.json` written before this holds — reads as
`{"cols": 2, "rows": 1}` on both sides of the wire: `serve.size_cell` on the server and `sizeOf`
in `app.js`. The file itself is rewritten in the new shape the first time the arrangement changes,
so an old desk is migrated by being used rather than by a migration step nobody remembers to run.
`POST /api/arrange` takes either spelling.

Columns cap at 4 and rows at 3. Anything out of range, or unreadable, clamps to the default rather
than raising: an arrangement is a preference, and a preference that cannot be parsed is a tile at
its normal size, not a dashboard that will not draw.

On the page the two numbers are two custom properties. In the grid the stylesheet spanned tracks
on them (`grid-column: span var(--cols)`, `grid-row: span var(--rows)`); the row of panes (#233)
has no tracks and no rows, so what is left of the footprint is one number doing one job:

```css
.tile.is-solo { flex: var(--cols, 1) 1 0; min-width: 160px; }
```

`--cols` is an open pane's **weight** — how many shares of the width the rails leave it takes —
which is what plan-panes' migration says `size.cols` becomes. `--rows` is still written and read by
nothing: a pane is always the row's full height. Both go when the gutters' widths replace `size`
(#234). One owner for each property, which is rule 2 of the render contract. `.tile.size-2`
survives as a state marker — it is what "is this one widened" reads — and decides nothing.

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

## Resizing

From the keyboard: `Alt+Shift+arrows` step the two numbers and `Alt+Enter` toggles one column or
two. The two edges a tile could be pulled by, and the outline that showed where it would land, went
with the grid (#232): they snapped to the grid's `auto-fit` tracks, and the one arrangement has no
wrap of tracks to snap to. Resizing by hand comes back as the gutters between panes
([plan-panes.md](plan-panes.md) §Resizing, #234), which replace `size` too.

## Minimise and maximise

Both are gestures the desk already had, under names only this page used.

* **Minimise** is the hide button — `setHidden(repo, true)`, or `h` on a rail. The pane leaves the
  row and keeps its place in `order`, so reopening puts it back where it was, and the footer's
  `N hidden` is the one click that does (#233).
* **Maximise** is `openAgent(repo)`, and it takes the width toggle's place in the head.

The width toggle went because `Alt+Shift+arrows` answer that question with more than two answers,
and because adding two buttons to a head that was already crowded is the information overload this
epic exists to remove. `Alt+Enter` still toggles the width for anyone who learned it.

## Keys

| Keys | Does |
| --- | --- |
| `Alt+←` / `Alt+→` | move the pane one visible slot (on a rail as well) |
| `Alt+Shift+←` / `Alt+Shift+→` | an open pane's share of the width, one less / one more |
| `Alt+Shift+↑` / `Alt+Shift+↓` | `rows`, still written and read by nothing since #233 |
| `Alt+Home` | pin first |
| `Alt+Enter` | one share or two |
| `h` | minimise |
| `Enter` on a rail | maximise: the swap (#233) |

The resize is the shifted pair because `Alt+arrows` has moved a tile since #5, and a gesture
somebody has learned is not one to take away for a new one.

## Reduced motion

The drag still works; it simply does not settle. `transitionLayout` refuses to start a transition
under `prefers-reduced-motion: reduce`, and the drop applies the new order directly —
`docs/desk-motion.md` has the rest.

## What is deliberately not here

No overlap, no z-order, no free placement, and no drag inertia. The desk is one row of panes, and a
window that can be put anywhere is a window that can be put somewhere nobody can find it.
