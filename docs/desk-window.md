# The row: panes, rails and gutters

The desk is **one row of panes**, one per agent, each the row's full height and as wide as this
window has made it ([plan-panes.md](plan-panes.md), #233–#235). A pane draws itself by its width: a
48 px **rail** that says who it is and whether it needs you, a **compact** pane you can answer from,
or a **full** one with everything a tile has. Width moves between two panes at the **gutter** between
them, and three **presets** set every width at once. This page is how the row is arranged by hand,
and where the numbers that decide it are set. What a pane shows at each width, the head, the cells
and the transcript, is in [fleet-dashboard.md](fleet-dashboard.md) §The row, and how it moves is in
[desk-motion.md](desk-motion.md).

## The row

* **Every agent is a pane**, the same component whatever its width (`.tile`, #233). The band the
  column drew and the grid's cards went with the one arrangement (#232, [fleet-layouts.md](fleet-layouts.md)).
* **The order and what is hidden are the desk's**, shared by every window
  (`arrangement: {order, hidden, pinned}`). **Which pane is open and the widths are the window's**
  (`windows.<w>`, named by `?w=`), so the laptop panel and a 4K monitor hold different widths over
  the same agents in the same order (§A width is the window's, and a weight).
* **A pane with no width is a rail.** The open pane and any pane given a width share what the rails
  leave, by weight.
* **Hidden leaves the row**, and the footer says `N hidden`; a press on that brings every one back
  to its own slot. An agent that needs a person is on the glass whatever `hidden` says.
* **A repository that left the registry** is a dashed rail after the row, naming the
  `ad-fleet repo add` that brings it back. The row holds panes and nothing else.
* **When even the rails do not fit** (about thirty agents on a 1 440 px window), a project's
  checkouts share one rail, named for the project and red if any of them needs you; a press on it
  opens the one that needs you. Only past that does the row scroll sideways, which is the last
  resort and not the design (plan-panes §Open questions).

## The tiers

What a pane draws is decided by its width, and its width by the widths. `data-tier` is the one
bridge between the two, and it has one writer.

| Tier | Width | What the pane shows |
| --- | --- | --- |
| **rail** | the rail's width | its number, the name down its length, the state's glyph in the state's colour (never colour alone), the unread count. The whole rail is red, with `!`, when the agent needs a person. Its state, age, spend, unread count and last line (or its question) are its accessible name and its tooltip |
| **compact** | from *compact from* | the head (name, state chip with its age, ticket), the three tools (hide, refresh, which model), the question and approval cards, the last lines of the transcript, and the reply box with *Send* |
| **full** | from *full from* | everything a tile has |

### The numbers, and where they are set

| Tier | Setting | CI (Chromium 141, headless) | Laptop (the operator's monitors) |
| --- | --- | --- | --- |
| **rail** | `fleet.tiers.rail_px`, 32–96 | 48 px | _not yet measured_ |
| **compact from** | `fleet.tiers.compact_px`, 120–720 | 160 px | _not yet measured_ |
| **full from** | `fleet.tiers.full_px`, 200–1600 | 360 px | _not yet measured_ |
| **slack** | `fleet.tiers.slack_px`, 0–24 | 8 px | _not yet measured_ |

The **CI column** is the numbers every browser test in the suite draws against
(`test_fleet_panes.py`, `test_fleet_gutters.py`, `test_fleet_tiers.py`), and they are the defaults:
48 px is a 28 pt hit target and its padding, 160 px the narrowest a head and a reply box can share,
and 360 px the grid's narrowest tile as it was. A test holds this column to the settings table, the
page's constants and the stylesheet's root, so the five places cannot drift apart.

The **laptop column** is the operator's, and it stays *not yet measured* until runbook steps P15 and
P16 in [windows-verification.md](windows-verification.md) §Panes (#235) have been run on the real
monitors. Keeping the defaults is an answer too, and is recorded as the same numbers.

**Where they are set:** the settings page, under *Appearance*, beside the palette, because they are
how the desk is drawn. They are written to `~/.agentdata/config.json` as `fleet.tiers.*` and read
nowhere else. A change is **in effect now**: the numbers ride on the theme payload (`/api/fleet`, the
stream's `theme` frame when the file changes, and the snapshot a reload draws first), so every open
desk takes the new numbers on its next tick, with no reload and nothing written. `ad-fleet engines`
prints the numbers in effect, in its `tiers` table.

**What is refused**, with the fix in the hint and the file left as it was:

* a value outside its bounds (`out_of_range`). Under 32 px a rail is not a thing to press. A compact
  tier under 120 px could never be landed on, because a pane pulled under 120 px settles back to the
  rail. And more than 24 px of slack is a hand's breadth of the wrong tier;
* four that do not go together (`bad_tiers`): *compact from* less than 64 px past the rail (a wide
  rail, not a compact pane), or *full from* less than 80 px past *compact from* (a compact tier with
  no room to land in: a key step is 40 px, and the snaps take the hand within 8 px). Two values
  that only go together can be written in one batch, and one at a time the hint names the order.

A four that does not go together can still reach the file by hand. It is **not drawn**: the desk
draws CI's numbers and says once in the footer why, the settings page says the same under the
boxes, and `ad-fleet engines` prints it as `tiers_invalid`.

### How the tier is set

* **One `ResizeObserver`** on the row watches the row and every pane in it, and one function,
  `setTier`, writes `data-tier`. The stylesheet keys on the attribute and never sets a width from
  it. If it did, a tier that changed a width would change the tier. The draw functions skip what a
  tier does not show: a rail does not render a transcript. A pane whose tier changed is drawn again
  in the same frame, so what the narrower tier skipped is there before anything is painted.
* **The slack is only between compact and full.** A pane leaves either of those tiers only once it
  is *slack* past the boundary, so a pane sitting on it (a window edge being dragged, a scrollbar
  coming and going) does not flicker. There is no slack at the rail's boundary, because nothing
  sits on it: a pane is a rail or at least *compact from* wide, and the stylesheet's floor for a
  pane with a width is the same number. The slack that used to be there drew a rail pulled out to
  exactly 160 px as a rail's face stretched across it
  (`tests/regressions/test_20260923_any_rail_widened_to_the_compact_minimum.py`).
* **Container queries are not used for the tiers.** Tests and the draw code can read an attribute
  and cannot read a container query (plan-panes §The pane). They still shed the model's word, the
  ticket, the chip's age and the trace from a *full* pane's head under 500–560 px, and without them
  the head wraps to a second line instead.
* **In an engine with no `ResizeObserver`** the same writer is fed by a measurement after every
  layout pass and on every resize of the window, so a pane still gets its tier from its width.
* **When the numbers change**, every pane already measured has its tier taken again at the width it
  has. A boundary that moved under a pane that did not is a change the observer never hears of.
  The rail's width and the compact floor are the stylesheet's `--rail` and `--compact-from`,
  written on the root only when they are not CI's.

[desk-engines.md](desk-engines.md) has the `ResizeObserver`, container query and pointer capture
rows for each shell, and what happens in the one that lacks them.

## A width is the window's, and a weight

What #217 called the footprint was `size: {cols, rows}` in the shared arrangement, a span of the
grid's tracks. The row has no tracks to span and no rows to span down. The gutters (#234) replaced
it with **widths**, in each window's own record:

```json
"windows": { "left": { "open": "alpha", "widths": { "alpha": 1.2, "beta": 0.8, "gamma": 0 } } }
```

* **0 is a rail.** Any other number is that pane's **share** of what the rails leave. It is a weight
  and not pixels, so a window made narrower scales the wide panes and leaves the rails alone.
* **Per window**, because a laptop and a 4K monitor cannot share pixels. The left monitor holding
  alpha wide while the right one holds beta is also the one job `screens` had (plan-panes §Where
  this plan pushes back, item 4). The order and what is hidden stay the desk's.
* **A window with no widths** draws the row as it was before the gutters: the open pane and every
  pin wide, each at the `size.cols` an older build left it (plan-panes' migration: `size.cols`
  becomes the weight), and everything else a rail. Nothing is written to make that so. The first
  gesture that changes a width writes the whole row.
* **One writer on the page.** `paintWidths` writes `is-solo` (the pane has a width) and `--w` (its
  share), and the stylesheet reads nothing else:

  ```css
  .tile.is-solo { flex: var(--w, 1) 1 0; min-width: var(--compact-from); }
  ```

  `flex-basis: 0` and `border-box` make a pane's width its edges (padding and borders, which
  `flex-grow` does not share out) plus its share of the rest. A weight read off a width has the
  edges taken away first (`paneEdge`), which is what lets a gutter move two panes and leave every
  other one to the pixel.
* **One write** per gesture: `POST /api/window {w, widths, version}`. `version` is the desk version
  the page last heard, read as the post goes. A write of widths older than the ones the record
  holds is refused `widths_stale`: another page under the same `?w=` moved them first. The page
  then puts its own back and reads the desk again. `widths` that are not repository-to-weight are
  refused `widths_shape`.

`size` is still read and kept by the server (`serve.size_cell`, both of its spellings, columns
capped at 4) because desk.json files written before this carry it. `POST /api/arrange` still takes
it, and no page sends it.

## The gutters

A gutter between every two panes on the glass: a 1 px line in the row's 6 px gap, and an 8 px strip
laid over the pane's right-hand edge to take hold of, so it costs the row no width. It is the pane's
own last child (the pane on its left owns it), and `drawGutters` shows it on every pane but the last.
A rail keeps its gutter, because a rail is pulled wide by one.

* **Dragging it moves width between those two panes and nothing else.** Every other pane keeps its
  left edge and its width, to the pixel. That is the rule that makes a resize predictable.
* **The snaps**, while the hand is on it. A pane pulled under 120 px settles to a rail. A pane with
  a width is never under *compact from*. Within 8 px, either side at *compact from* or *full from*,
  or an even share with the neighbour, takes the hand. `snapPair` is the one function, and the keys
  go through the same floors (`settlePair`). The numbers are the ones in §The tiers, so a laptop
  that moved them snaps to its own.
* **The drag is the preview.** #217's ghost was there because a span snapped on release and the
  hand could not see where it would land. A gutter draws the real layout under the hand. When it is
  first moved, every wide pane's share is made its width less its edges, and then each animation
  frame writes the two panes' shares and nothing else (`paintHeld`, marked `gutter:frame`). There is
  no `place()` (it waits while a gutter is held and runs when the hand comes up), no redraw and no
  reorder. #217's lesson was that a draw in the middle of a drag puts the gesture down.
* **Pointer capture on the press.** A gutter has no click of its own to lose to the capture (the
  reason the reorder drag captures only on lift), and the hand leaves an 8 px strip on the first
  pixel of travel. With the capture, every move is the gutter's until the hand comes up, even off
  the row altogether (`test_fleet_engines.py` measures it in CI's Chromium). The move and release
  are heard on the document as well, so an engine without `setPointerCapture` resizes just the
  same. While one is held the whole page says `col-resize`.
* **One write, on release,** through `widthsNow`. The widths are painted already, posted once, put
  back with the server's words if the write is refused, and offered back from the footer (`undo`,
  or `u`, for twelve seconds). The release is where the hand came up, not where the last move said:
  an engine that coalesces moves can deliver the release first (#270). The `click` that ends it is
  swallowed, because a pane's click selects the project for every window. **`Esc`** with the button
  still down puts every width back and writes nothing. It is not also the page's own `Esc`, which
  would go back a pane.
* **A double click** evens the two panes beside it. Its two presses write nothing of their own, and
  neither selects the project nor opens the pane, which is what a click and a double click on a
  pane mean.

## Opening one, and opening one beside

* **A press on a rail** swaps it in. It takes the width of the pane that had the keys, which becomes
  a rail in its own slot. This is the column's gesture, kept because the operator already has it. In
  a window with widths it is one write of `open` and the widths together. `Enter` on a rail's face
  is the same press, and `Esc` goes back.
* **Shift and a rail** opens it beside the pane that has the keys. The two split what that pane had
  and the rail's own width, so nothing else in the row moves, and the keys stay where they were.
  `Shift+Enter` on a rail's face is the same. It does not move the rail next to the pane with the
  keys, because the order is every window's and the widths are one window's.

## The presets

One segmented control in the header, where the arrangement picker was:

| Preset | Key | Widths |
| --- | --- | --- |
| **one** | `1` | the pane the keyboard is on, or else the open one, wide; every other a rail |
| **all** | `=` | an even share each. The tiers decide what that looks like on this glass: three panes on the laptop panel are compact, the same three on a 2 560 px monitor are full |
| **needs me** | `f` | every agent that needs a person wide, the rest rails, and the keys moved to one of them |

Each is one write, undoable from the footer, and applies at once under reduced motion. They are
presses, not modes. *needs me* replaced the needs-only filter (#207's second focus), which dimmed the
quiet rails and kept a `held` list so the agent just answered would not dim under the reply. A preset
takes nothing back when an agent stops needing you, so neither is left. With nobody needing you it
writes nothing and says so, because a row of rails and nothing open is the blank window the desk
exists to stop.

## Dragging a pane to another slot

Pointer events, with capture. `bindDragToReorder(handle, host, name)`:

| | handle | host |
| --- | --- | --- |
| an open pane | `.head`, the title bar, with its grip | the pane |
| a rail | `.pane-rail`, the face, one button filling the rail | the pane |

The rule for what a press means: **a press on a control inside the handle belongs to that
control, unless the handle *is* the control.** A pane's head is a plain `div`, so every button in
it is somebody else's. A rail's face is one button, so a press anywhere on it is the rail's.

Four pixels of travel before anything moves: a click on the head still selects the project, and a
click on a rail still swaps it in. Then the host is translated under the cursor, and whatever is
under the pointer is lit `drop-before` or `drop-after`, measured across the row. `Esc` cancels and
the arrangement is untouched. The drop is optimistic: the order changes under the hand and the
server's answer is what the next draw reads. A reorder never changes which agent is open. Until
something opens one, the open agent is only "the first in the order", so `holdOpen()` writes it down
before the order moves (#233).

Five details are each a bug that happened:

1. **The capture is taken on lift, not on `pointerdown`.** While an element holds the pointer
   capture the browser retargets the compatibility mouse events to it as well. Capturing early sent
   the `click` that ends an ordinary press to the head rather than to the repository name inside
   it, and clicking the name, which is how a tile is opened, silently stopped working.
2. **The move and up listeners are on the document.** A head is twenty pixels tall and the pointer
   is off it before it has travelled far enough to count as a drag, so a handle that listened to
   itself heard the first move and none of the others.
3. **The title bar is not selectable.** `draggable="true"` used to suppress text selection as a
   side effect. Without it the first drag selected text from one tile to another, and the second
   drag in a row became a native drag of that selection, which arrives as `pointercancel` and
   ends the gesture on the frame it began.
4. **`.is-dragging` gets `pointer-events: none`,** for any host and not only a tile, so
   `elementFromPoint` answers with what is underneath rather than with the thing being dragged.
5. **A draw does not reorder the DOM while a drag is in flight.** The stream draws several times a
   second, and a reorder mid-drag is a tile that jumps out from under the cursor.

The click that ends a real drag is swallowed once, because on a head it would select the project
and on a rail it would open the agent, and neither is what the hand just asked for. So is the one
that ends a drag put down with `Esc`: the button is still held when `Esc` is pressed, Chromium sends
the release's `click` to the handle, and on a rail that opened the agent the operator had just
cancelled moving (#233, `tests/regressions/test_20260923_any_escape_drag_opens_rail.py`).

## Minimise and maximise

Both are gestures the desk already had.

* **Minimise** is the hide button: `setHidden(repo, true)`, or `h` on a rail. The pane leaves the
  row and keeps its place in `order`, so reopening puts it back where it was, and the footer's
  `N hidden` is the one click that does (#233).
* **Maximise** is `openAgent(repo)`, and it takes the old width toggle's place in the head.

The width toggle went because the gutters answer that question with more than two answers, and
because adding two buttons to a head that was already crowded is the information overload this
epic exists to remove. `Alt+Enter` evens the pane with the one on its right (#234): the double click
on the gutter between them.

## Keys

| Keys | Does |
| --- | --- |
| `←` / `→`, `j` / `k` | along the row: the keyboard to the next pane |
| `Alt+←` / `Alt+→` | move the pane one visible slot (on a rail as well) |
| `Alt+Shift+←` / `Alt+Shift+→` | the gutter on the pane's right, one step: 40 px, and out of a rail or into one in a single press |
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
took it, as the plan keyed *one*. The digits open panes from `2`. The first pane is `j` from nowhere,
or `1` with the keyboard on it, which makes it the one wide pane. The rest of the keyboard is in
[fleet-dashboard.md](fleet-dashboard.md) §Keyboard.

## Reduced motion

The drag still works; it simply does not settle. `transitionLayout` refuses to start a transition
under `prefers-reduced-motion: reduce`, and the drop applies the new order directly
([desk-motion.md](desk-motion.md) has the rest). The swap and the presets apply at once. The gutter
drag is unchanged, because it was never an animation.

## What is deliberately not here

No overlap, no z-order, no free placement, and no drag inertia. The desk is one row of panes, and a
window that can be put anywhere is a window that can be put somewhere nobody can find it.

## Before the row: the tile as a window (#217)

This page began as #217's, when the desk was a grid of cards. The grid had HTML5 drag on a tile's
head and one width toggle, one column or two, and three things were wrong with that:

* **The gesture said nothing was happening.** The browser drew its own translucent copy of the
  tile, and the tile itself stayed exactly where it was.
* **On a trackpad it needed a press-and-hold** nobody discovers, because that is what HTML5 drag
  asks for when there is no mouse button held down over a `draggable` element.
* **A tile could be made wider and never taller.** `size: 2` was one number, and one number can
  only answer one question.

#217 answered them with the pointer drag above, which the row kept, and with a footprint of two
numbers, `size: {cols, rows}`, snapped by resize edges to the grid's measured `auto-fit` tracks. The
row (#233) had no tracks to snap to and no rows to span down, so the edges, the ghost that showed
where a span would land, and `size` as something a page writes went with the gutters (#234).
