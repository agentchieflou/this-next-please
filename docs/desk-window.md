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
"grid": { "size": { "rdsd-pbi-reporting": { "cols": 2, "rows": 1 } } }
```

`size: 2` — which is what every `desk.json` written before this holds — reads as
`{"cols": 2, "rows": 1}` on both sides of the wire: `serve.size_cell` on the server and `sizeOf`
in `app.js`. The file itself is rewritten in the new shape the first time the arrangement changes,
so an old desk is migrated by being used rather than by a migration step nobody remembers to run.
`POST /api/arrange` takes either spelling.

Columns cap at 4 and rows at 3. Anything out of range, or unreadable, clamps to the default rather
than raising: an arrangement is a preference, and a preference that cannot be parsed is a tile at
its normal size, not a dashboard that will not draw.

On the page the two numbers are two custom properties, and the stylesheet spans on them:

```css
.tile { grid-column: span var(--cols, 1); grid-row: span var(--rows, 1); }
```

One owner for each property, which is rule 2 of the render contract. `.tile.size-2` survives as a
state marker — it is what "is this one widened" reads — and no longer decides anything.

`main` gained `grid-auto-rows: minmax(240px, auto)`, because implicit rows had no size of their
own and a tile asked to span two of them spanned two rows as tall as their content: it was not
taller. A tile's ceiling is `calc(30vh * (rows + 1))`, so one row is the 60vh it has always been
and each further row is another third of the page.

## Dragging

Pointer events, with capture. `bindDragToReorder(handle, host, name)`:

| | handle | host |
| --- | --- | --- |
| grid | `.head` — the title bar, with its grip | the tile |
| column | `.band-open` — the button that fills the row | the band |

The rule for what a press means: **a press on a control inside the handle belongs to that
control, unless the handle *is* the control.** A tile's head is a plain `div`, so every button in
it is somebody else's; a band is one button filling the row with its three tools beside it rather
than inside it, so a press anywhere in it is the band's.

Four pixels of travel before anything moves — a click on the head still selects the project — and
then the host is translated under the cursor and whatever is under the pointer is lit `drop-before`
or `drop-after`. `Esc` cancels and the arrangement is untouched. The drop is optimistic: the order
changes under the hand and the server's answer is what the next draw reads.

Five details are each a bug that happened:

1. **The capture is taken on lift, not on `pointerdown`.** While an element holds the pointer
   capture the browser retargets the compatibility mouse events to it as well, so capturing early
   sent the `click` that ends an ordinary press to the head rather than to the repository name
   inside it — and clicking the name, which is how a tile is zoomed, silently stopped working.
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
and on a band it would open the agent — neither of which is what the hand just asked for.

## Resizing

Two edges: `.rsz-x` on the right for columns, `.rsz-y` on the bottom for rows. They start below the
head, because the head's own controls reach the right edge and a resize strip over them is a
maximise button that cannot be clicked — a window is resized from its body edge and moved by its
title bar, and that is the distinction.

Columns snap to the grid's own tracks, measured from `getComputedStyle(grid).gridTemplateColumns`
rather than assumed: `auto-fit` means the number of columns is whatever the window is wide enough
for. Rows snap to thirds of the page height.

`#rszghost` shows what will happen before the hand comes up (HIG *Drag and drop*): one outline for
the whole page, sized to the projected footprint and labelled with the two numbers. One element,
because there is only ever one gesture in flight and a ghost per tile is a ghost that gets left
behind. `Esc` abandons the resize with nothing written.

## Minimise and maximise

Both are gestures the desk already had, under names only this page used.

* **Minimise** is the hide button — `setHidden(repo, true)`. The tile keeps its place in `order`,
  so reopening puts it back where it was, and the dock or the column is one click away.
* **Maximise** is `openAgent(repo)`, and it takes the width toggle's place in the head.

The width toggle went because the edge handles and `Alt+Shift+arrows` answer that question with
more than two answers, and because adding two buttons to a head that was already crowded is the
information overload this epic exists to remove. `Alt+Enter` still toggles the width for anyone who
learned it.

## Keys

| Keys | Does |
| --- | --- |
| `Alt+←` / `Alt+→` | move the tile one visible slot |
| `Alt+Shift+←` / `Alt+Shift+→` | one column narrower / wider |
| `Alt+Shift+↑` / `Alt+Shift+↓` | one row shorter / taller |
| `Alt+Home` | pin first |
| `Alt+Enter` | one column or two |
| `h` | minimise |
| `Enter` | maximise |

The resize is the shifted pair because `Alt+arrows` has moved a tile since #5, and a gesture
somebody has learned is not one to take away for a new one.

## Reduced motion

The drag still works; it simply does not settle. `transitionLayout` refuses to start a transition
under `prefers-reduced-motion: reduce`, and the drop applies the new order directly —
`docs/desk-motion.md` has the rest.

## What is deliberately not here

No overlap, no z-order, no free placement, and no drag inertia. The desk is a grid and a column,
and a window that can be put anywhere is a window that can be put somewhere nobody can find it.
