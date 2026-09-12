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

## B — roles (`?layout=roles&view=…`)

**The URLs**, one browser window each:

| URL | Shows | Screen |
| --- | --- | --- |
| `?layout=roles&view=agents` | the tiles, wide — transcripts, approvals, replies | **left**, where the terminal is |
| `?layout=roles&view=verify` | the selected project alone: link rail, verify pane, its inbox | **centre**, where the report is |
| `?layout=roles&view=board` | the Jira board and the unsorted tray, no tiles — and the agent rail, so a ticket is handed over from here too (#183) | **right**, where the ticket is |

**What it is for:** giving each screen the job it already has, instead of asking one window to be
all three. **The three windows agree on one project.** Clicking a tile on the left changes the
centre and the right, because the selection is server state pushed down the same SSE stream every
window is already reading — not a URL fragment each window would have to be told about. Open the
three URLs once, drag them to their monitors, and the browser remembers the windows.

**Which screen it was meant for:** all four at once. It is the layout that most directly answers the
photograph, and the one with most to prove in the sitting: three windows that look alike are the tab
problem again, one level up, which is why the header names the view and the window title carries it.

## C — screens (`?layout=screens&screen=N`)

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

## Hidden tiles — the operator's own arrangement (`h`) (#173)

Focus mode decides for you; **hiding** is you deciding. `hidden` is a list beside `order`, `size`
and `pinned` in `arrangement[layout]`, so it is the server's and every window on this fleet agrees
on it — a tile put away on the laptop is put away on the wall screen too, and it is still put away
tomorrow.

* `h` hides the tile the keyboard is on; the `−` on its header does the same with a mouse.
  `ad-fleet hide <repo>` and `ad-fleet unhide <repo>` do it from a terminal, and print the list.
* A hidden tile **keeps its slot in `order`**, so reopening it puts it back between the two tiles it
  was between rather than at the end.
* **A tile that needs a person is on the glass whatever `hidden` says.** Hiding a demand is how a
  demand gets missed, and it is the one rule the operator's own arrangement does not get to
  override. The fold decides "needs a person", not the page.
* `1`–`9` count what is on the glass, so a digit can no longer zoom a tile no mode is showing —
  which used to leave a blank window, because zoom hides every other tile and a mode was already
  hiding that one. Pressing the number printed on a tile focus mode is quieting leaves focus mode
  rather than going dark.
* `hidden` is additive: an arrangement written before this slice has no such key, and loads.

`hidden` and `pinned` are per **project**: two `git worktree` checkouts of one repository are one
piece of work, and putting half of it away — or pinning half of it first — is an arrangement nobody
asked for. Expanded on the server, so `ad-fleet hide` and every open window agree by construction,
and a name the registry no longer knows keeps its place rather than being dropped from the desk.

Nothing is taken away silently. Everything off the glass — hidden, quieted by focus mode, zoomed
past, or a repository that has left the registry — is a **chip in the dock** along the bottom, and a
chip is one click from being back. See [fleet-dashboard.md](fleet-dashboard.md) §The dock.

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

| | A — grid | B — roles | C — screens |
| --- | --- | --- | --- |
| Photograph | _(link)_ | _(link)_ | _(link)_ |
| Minutes spent in it | | | |
| What was opened **outside** the dashboard, and why | | | |
| Screen hops (roughly, per hour) | | | |
| What the cursor did most | | | |
| Was focus mode used? When? | | | |
| What was worse than the tab shuffle | | | |

**The decision** (write it here and in #133, with the reasons, before changing the default):

> _Chosen layout:_
>
> _Why:_
>
> _What the other two would have to fix to be worth keeping:_
>
> _Focus mode: kept / dropped, and why:_

> **Nothing above has been filled in yet, and no code may act as though it had.** On 2026-09-08 an
> agent wrote a decision into this page — a chosen layout, minute counts, screen-hop rates,
> photograph links and the operator's reasons — none of which came from a sitting that ever
> happened. It was reverted on 2026-09-09. This issue's rule is the reason it exists: the decision
> is made on the real screens, by the operator, and recorded here and in #133 **before** any
> layout-specific code. An agent may build the arrangements; it may not conclude which one won.

An unknown `?layout=` falls back to the default with a notice in the footer rather than a blank
page — that much is a behaviour, and it does not depend on the sitting.

Then the default moves in three places that a test already keeps in step: `LAYOUTS` in
`agentdata/cli_fleet.py` (the `--layout` default is `LAYOUTS[0]`), `LAYOUTS` in
`agentdata/fleet/serve.py`, and the fallback a window with no `?layout=` takes in
`agentdata/fleet/static/app.js`. Update the default named in this page and in
[fleet-dashboard.md](fleet-dashboard.md), then open the follow-up issue that removes the unused two
a month later.

## Constraints every arrangement keeps

No new dependency, no build step, no CSS framework — the page still has to load in PyCharm's JCEF
tool window and VS Code's Simple Browser behind the corporate proxy, where anything fetched from the
internet simply does not arrive ([fleet-ide.md](fleet-ide.md)). Every arrangement is body classes
over one stylesheet, so a tile cannot mean one thing on one screen and something else on another.

Window *placement* is the OS's and the browser's job. The dashboard offers views; it does not know
which monitor it is on and does not try to find out.
