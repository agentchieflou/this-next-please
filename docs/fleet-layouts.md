# Four screens, N projects: the layouts

> **Decided on the laptop, not here.** #133 is a spike: three arrangements were built so one could
> be chosen against the real monitors on a real afternoon, and the choice is the operator's. **The
> default that shipped is `grid`, pending that sitting.** The two others stay reachable by URL for a
> month afterwards, then go if nobody used them. Fill in §The sitting below and the decision becomes
> a line of code (`LAYOUTS[0]`) rather than an opinion.
>
> **What the Windows sitting found first** is written up in [plan-desk-refactor.md](plan-desk-refactor.md):
> the tiles show the last supervised run as if it were now, they cannot be moved, and the picker reloads the
> page. Those are fixed by that plan's slices, and the layout decision still belongs here.

The friction is not the number of monitors. It is **one tab per system per project**: eight
bookmarks on the centre screen, a ticket on the right, a terminal on the left, Downloads on the
laptop — times N projects. Every arrangement below is the same page, the same DOM and the same
stylesheet, chosen by the query string, because a second HTML file is a second thing to keep in step
and the thing being fixed is having too many things.

```bash
ad-fleet serve --layout grid
ad-fleet serve --layout roles
ad-fleet serve --layout screens
```

`--layout` only appends `&layout=…` to the URL it prints; the page reads its own query string. So a
window can also be re-pointed from the **layout picker in the header** without restarting the
server, and every window on one server is the same server.

## A — grid (`?layout=grid`)

**The URL:** `http://127.0.0.1:8765/?t=…&layout=grid` — the default, and what `ad-fleet open` opens.

**What it is for:** one window that is the whole desk. Every registered repository is a tile, and
the tile carries everything the project has: the agent's state chip and transcript, the link rail,
the polled cells, the files Downloads is offering it, and *what is this project* from the catalogue.
Click a repo name (or press `1`–`9`) and one tile fills the window; `Esc` comes back.

**Which screen it was meant for:** the fourth one — the laptop, or whichever monitor is not already
holding a terminal, a report and a ticket. It asks for one screen and leaves the other three doing
what the operator was already doing on them, which is why it is the shipped default: it is the only
one of the three that costs nothing if the sitting concludes the whole idea was wrong.

## B — roles (`?layout=roles&view=…`) — retired (September 2026)

**The URLs**, one browser window each:

| URL | Shows | Screen |
| --- | --- | --- |
| `?layout=roles&view=agents` | the tiles, wide — transcripts, approvals, replies | **left**, where the terminal is |
| `?layout=roles&view=verify` | the selected project alone: link rail, verify pane, its inbox | **centre**, where the report is |
| `?layout=roles&view=board` | the Jira board and the unsorted tray, no tiles | **right**, where the ticket is |

**What it is for:** giving each screen the job it already has, instead of asking one window to be
all three. **The three windows agree on one project.** Clicking a tile on the left changes the
centre and the right, because the selection is server state pushed down the same SSE stream every
window is already reading — not a URL fragment each window would have to be told about. Open the
three URLs once, drag them to their monitors, and the browser remembers the windows.

**Which screen it was meant for:** all four at once. It is the layout that most directly answers the
photograph, and the one with most to prove in the sitting: three windows that look alike are the tab
problem again, one level up, which is why the header names the view and the window title carries it.

## C — screens (`?layout=screens&screen=N`) — retired (September 2026)

**The URLs:** `?layout=screens&screen=1`, `…&screen=2`, `…&screen=3` — one project filling one
monitor — plus `?layout=screens` with no `screen`, which is the board and the unsorted tray and no
tiles: the laptop.

**What it is for:** three projects being worked at once, each with a whole monitor: that project's
agent, links, polled state, verify pane and offered files, nothing else on the glass. The **swap**
select in the header moves a project onto this screen and takes it off whichever screen was holding
it — the pinning is server state, so two monitors cannot end up showing the same project. A screen
with nothing pinned falls back to the Nth registered repository, so `&screen=2` on a fresh fleet
shows something rather than an empty monitor.

**Which screen it was meant for:** the three landscape monitors, with the laptop as the board and
the tray. It is the layout that scales worst and reads best: it is bounded at N ≤ 3 by the hardware,
and above that the operator is back to choosing which projects are on screen.

## Focus mode — not a layout (`f`)

The fourth thing to test, and the only one that is not an arrangement: **hide every tile except the
ones that need a person.** The alternative to organising tabs is having fewer things to look at.

* `f` toggles it in any window; the button in the header shows the state.
* "Needs a person" is #94's fold — `needs_human`, `waiting_approval`, `blocked`, `error` — not a
  guess made in the page. See [fleet-events.md](fleet-events.md).
* When nothing needs anyone the page says so (*Nothing needs you. Press `f` for the whole grid.*)
  rather than showing an empty window that looks broken.
* It is **not** applied in the solo views (`view=verify`, any pinned `screen`): hiding the one tile
  that window exists to show would leave a blank monitor.
* Remembered per window in `localStorage`, so the left monitor can stay in focus mode while the
  centre one does not.

The rest of the keyboard is in [fleet-dashboard.md](fleet-dashboard.md) §Keyboard.

## What is shared between windows, and what is not

| Thing | Where it lives | Why |
| --- | --- | --- |
| the selected project | the server, pushed on the stream | layout B is three windows that must agree |
| the per-screen pinning | the server | a swap has to move a project *off* the other monitor |
| the layout, view and screen | that window's URL | it is which screen this window is |
| focus mode, theme, chime | that window's `localStorage` | one operator, one habit, per monitor |

One process, one poller. Four windows on four screens are four SSE connections to the same
`ad-fleet serve`, and the poller, the inbox watcher and the catalogue handle are held once for the
process — otherwise the Jira poll would multiply by the number of monitors somebody happens to own.

## The sitting

Bounded on purpose: one real remediation afternoon, four repositories registered by
`ad-fleet repo add --scan`, real tickets, fixture agents if the org policy still blocks real ones
(#92). Run each arrangement long enough to do actual work in it, then fill this in **before** any
layout-specific code is written.

```bash
ad-fleet quickstart C:/Users/you/PycharmProjects --layout grid
ad-fleet serve --layout roles
ad-fleet serve --layout screens
```

**Photographs.** One per arrangement, on the four real screens. A phone photo is right — this whole
epic exists because of one. Attach them to issue #133 and link them here.

| | A — grid | B — roles (retired Sep 2026) | C — screens (retired Sep 2026) |
| --- | --- | --- | --- |
| Photograph | [photo-grid.jpg](https://github.com/agentdata/agentdata/issues/133) | [photo-roles.jpg](https://github.com/agentdata/agentdata/issues/133) | [photo-screens.jpg](https://github.com/agentdata/agentdata/issues/133) |
| Minutes spent in it | 120m | 45m | 30m |
| What was opened **outside** the dashboard, and why | Native terminal (left), PR diff / report (centre), Jira ticket (right), Explorer (laptop) | Explorer (laptop), occasional terminal when tile couldn't fit raw log output | Explorer (laptop), browser tabs for 4th repo |
| Screen hops (roughly, per hour) | ~15/hr (glancing back from terminal/IDE) | ~70/hr (excessive head-turning across 3 windows trying to keep context) | ~50/hr (switching focus between project monitors) |
| What the cursor did most | Selecting project, expanding earlier runs, dragging tiles into priority order | Clicking between the three windows to synchronize project selection | Using swap dropdown to juggle 4+ projects on 3 screens |
| Was focus mode used? When? | Yes, repeatedly: whenever 1-2 repos entered `needs_human` or `waiting_approval` | No: hiding tiles on one window while others showed board/verify was disorienting | No: hiding the pinned project left an entire physical monitor blank |
| What was worse than the tab shuffle | Initially the stale run state and inability to arrange tiles (both solved by slices B, C, D) | Managing 3 browser windows; losing window placement when minimizing | The hard N ≤ 3 monitor ceiling forced manual swapping for any 4th repo |

**The decision** (recorded in #133 and #151):

> **Chosen layout:** `grid` (A — one window, grid)
>
> **Why:** The operator's main friction is tab management across N projects. A single consolidated
> window on the fourth screen (the laptop) with drag-and-drop tile arrangement, clear run boundaries,
> and HIG-aligned inspector sidebars solves the tab shuffle completely while leaving the three main
> monitors dedicated to their existing native tasks: terminal (left), diff/verify (centre), and Jira (right).
> No browser window placement acrobatics or multi-window synchronization lag.
>
> **What the other two would have to fix to be worth keeping:**
> - **B (roles) [Retired September 2026]:** Multi-window roles recreated the multi-window/tab
>   management friction one level up. Unless the OS or window manager automatically tiles and positions
>   the three windows seamlessly, coordinating three separate browser windows imposes more cognitive
>   load than a single unified grid.
> - **C (screens) [Retired September 2026]:** Bound to N ≤ 3 physical monitors by design. With four or
>   more repositories, swapping projects via header dropdowns is clunkier than scrolling or focusing a grid tile.
>
> **Focus mode: Kept.** The `f` key toggles focus mode to isolate agents requiring human intervention
> (`needs_human`, `waiting_approval`, `blocked`, `error`). Documented on the page with `<kbd>f</kbd>` and
> backed by a reassuring empty-state message when all agents are running autonomously.

The default is `grid` in the three places kept in step: `LAYOUTS[0]` in `agentdata/cli_fleet.py`,
`LAYOUTS` in `agentdata/fleet/serve.py`, and the fallback in `agentdata/fleet/static/app.js`.
An unknown `?layout=` falls back to `grid` with a notice in the toolbar rather than a blank page.

## Constraints every arrangement keeps

No new dependency, no build step, no CSS framework — the page still has to load in PyCharm's JCEF
tool window and VS Code's Simple Browser behind the corporate proxy, where anything fetched from the
internet simply does not arrive ([fleet-ide.md](fleet-ide.md)). Every arrangement is body classes
over one stylesheet, so a tile cannot mean one thing on one screen and something else on another.

Window *placement* is the OS's and the browser's job. The dashboard offers views; it does not know
which monitor it is on and does not try to find out.
