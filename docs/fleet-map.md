# The fleet map

The fleet map is the fleet drawn as its structure rather than as tiles: each project, the main checkout its
worktrees hang from, each checkout's agent and who started it, and (later) branches and the network around them.
It is **read-only**: nothing on the map starts, stops or changes anything; the desk does that. Epic #295.

## The graph

`GET /api/map` (token required, like every route but `/api/ping` and `/open`) answers
`{ok: true, schema: 1, as_of, cursor, says, projects, checkouts, network, theme}` (`network`: §The network). It is a pure fold over the same snapshot
`/api/fleet` sends (`agentdata/fleet/fleetmap.py`, `graph(snapshot)`): no git call, no registry or `.agent/` read,
the same snapshot always gives an equal graph. It never carries a path and never carries event text. Twenty
checkouts fit in under 18 KiB.

| Key | What |
| --- | --- |
| `schema` | `1` |
| `as_of` | the rows' read order (`{run, n}`), `null` for an empty fleet |
| `cursor` | `luna:12,uat:4`: each checkout's last `seq`, what `/api/events?since=` takes |
| `says` | *3 projects, 5 checkouts, 4 agents working, 1 needs you*; zeros read *no projects*, *no agents working*, *nobody needs you*. "Working" is `state == "running"` only |
| `projects[]` | `{id: "p:<project>", name, root, says}` by name. `root` is `c:<repo>` of the checkout that is no one's worktree (first by name if several), `""` when every checkout is a worktree of an unregistered main |
| `checkouts[]` | `{id: "c:<repo>", repo, project, main, worktree_of, worktree_of_unregistered, branch, dirty, ahead, behind, says, agent}` by project, main first, then name. `main` is true on the project's root only. `worktree_of` is `c:<repo>` of the registered main it hangs from, else `""`; `worktree_of_unregistered` is true when git points at a main the fleet does not know. `branch`/`dirty`/`ahead`/`behind` come from the git poll, and are `""`/`false`/`0` before it ticks |
| `agent` | `{id: "a:<repo>", kind, live, state, role, needs_human, stale, renew_queued, ticket, phase, model, age_s, turns, sessions_n, subagents, says}`. `live` is the row's `supervised`; `role` is `STATE_ROLES[state]`; `subagents` is `0` until #402 |

**`kind`**, the first that applies (`fleetmap.KINDS`):

| Kind | When |
| --- | --- |
| `console` | a live console lock, or a run whose `started` event says `console` |
| `adopted` | a live adopted (external) lock, or a run whose `started` event says `adopted`/`external` |
| `adoptable` | an adoptable session sits in the checkout |
| `headless` | a run the fleet started (`copilot -p`), alive or finished |
| `none` | never a run |

The run's origin is `/api/fleet`'s `row.run.origin` (`serve.split_runs`), because a headless agent exits at the
end of every turn: liveness alone would read a finished agent that stopped with a question as "no session".

**`says`**. A checkout: *worktree luna-velocity on feature/RDSD-101-velocity, of luna*, then *uncommitted changes*,
*n ahead*, *n behind* when true. An agent: `<kind words> · [finished · ]<state words>[ · ticket]`, *finished* when
it is not live and a run exists, e.g. *background agent (headless) · running · RDSD-101*, *background agent
(headless) · finished · needs you*, *console agent · needs you*, *no session · idle*; then, when true, *· 2 sub-agents
(not yet measured)*, *· began on an older install*, *· renew queued*.

Built on the defaults for "the monorepo" (a project's root is its main checkout) and "background agents" (`headless`
is a run the fleet started, alive or finished). Another answer changes `kind_of` and its words.

## Branches

An agent is one working tree, so **its branch is that checkout's current branch**. The other branches belong to the
project: worktrees of one repository share `refs/heads`, so every checkout of a project lists the same local branches.
The map therefore draws **one branch list per project** (its lanes) and stands each checkout, and its agent, on one of
them. Nothing new is read for it: the git poll already runs the cheap branch read every 30 s (`read_branches(full=False)`:
the default branch, `for-each-ref`, `branch --no-merged`), and `_tick_git` now keeps its rows in a side cache on the
`Poller` (`Poller.branch_rows(name)`) instead of throwing them away. The cache sits beside the poll cells, not in the
git cell, because `polls` rides on every `/api/fleet` row; the git cell's fields are unchanged. Each entry is replaced
whole on every read, never mutated, so a map request on another thread sees one answer or the next.

`/api/map` reads that cache through `serve.current_poller()`, which never constructs a poller, so the map makes no git
call of its own and never starts polling.

| Key | What |
| --- | --- |
| `project.default` | the default branch the poll found (`origin/HEAD`, else `main`, else `master`), `""` before a read |
| `project.branches[]` | `{id: "b:<project>:<name>", name, unmerged, ticket, age_s, carrying, current_in, says}`: the root checkout's rows, else the union by name over the project's checkouts; unmerged first, newest first, at most 40 |
| `unmerged` | the branch never reached the default branch (`git branch --no-merged`) |
| `age_s` | seconds from the branch's last commit to the poll's read |
| `current_in` | `c:<repo>` of every checkout standing on it: each checkout's cached `current`, else its git cell's `branch` |
| `carrying` | the name is in any of the project's checkouts' `carrying`: it carries that checkout's active ticket |
| `checkout.on`, `agent.on` | `b:<project>:<branch>` of the lane it stands on, `""` when its branch is not in the list (or nothing was read) |
| `agent.branch` | that lane's name, `""` with `on` |
| `project.branches_says` | *12 branches, 4 never reached main* (*40+* when the list was capped), or *branches not read yet (the git poll runs every 30 s)* when no checkout of it has been read; the project's `says` ends with it |
| `project.carry_lines` | `poll.carry_line` of each checkout whose read has two or more branches carrying its ticket, once per sentence: *two branches carry RDSD-101 (...); only one can merge* |

A branch's `says` is e.g. *feature/RDSD-101-velocity · never reached main · current in luna-velocity · carries
RDSD-101*; an agent's `says` gains *· on feature/RDSD-101-velocity*, and *· carries RDSD-101* when that branch is
`carrying`.

**No ahead counts on the map.** How far each branch is from the default is a `rev-list --count` per branch, which is
too costly for a 30 s poll across every checkout; it stays on the click (`GET /api/branches`, the inspector's pane).
Ten projects of forty branches and twenty checkouts answer in under 160 KB.

Built on the default for "branches per agent": an agent's branch is its checkout's current branch, on the lanes of
the project's local branches (one list, at most 40, unmerged first); ticket carriers marked.

## The network

"Our network", read locally (#404): what this desk server knows about itself and about what it talks to. `GET
/api/map` adds `network` beside the graph; `fleetmap.graph(snapshot, network=)` draws it from the snapshot and from
`serve.map_network(port)`'s raw facts (`{port, version, live, counts, settings}`), and without those facts the graph
has no `network`. Twenty checkouts' network (four sources of twenty cells, three windows) is under 8 KiB, on top of
the graph's 18.

| Key | What |
| --- | --- |
| `server` | `{id: "n:server", port, version, current, says}`: this process, its port and `version_string()`; `current` is `/api/fleet`'s `server.current` (is the running desk the installed one) |
| `windows[]` | `{id: "w:<name>", name, shell, pages, connected, since, says}` by name: the union of the desk's window records (`desk.json`, names only) and the streams open now; a name that is not one (`SKIN_FAMILY`) reads `main`, for a record as for a stream. `pages` is the pages a window has a stream open on (`desk`, `settings`, `map`), `[]` when none; `since` is the oldest open stream's UTC stamp |
| `sources[]` | `{id: "s:<jira\|pr\|powerbi\|git>", name, on, requests, errors, stood_down, cells, says}` in `poll.SOURCES` order. `on` is `fleet.poll.*`; the counts are today's `Poller.counts()` (`0` when nothing polls); `cells` is `[{checkout: "c:<repo>", ok, age_s}]`, one per checkout with a cell, `ok` being `not grey` |
| `approvals` | `{id: "n:approvals", pending, says}`: the requests waiting at the approval gate |
| `install` | `{id: "n:install", version, commit, stale_agents, says}` from `server.installed`; every agent whose `stale` is true is in `stale_agents` and gains `stale_of: "n:install"` |
| `says` | *the desk server, 2 windows open, 4 sources, 1 approval waiting*; zeros read *no windows open*, *no sources*, *no approvals waiting*. Sources counts the ones that are on |

The graph's own `says` gains *, 2 windows open* and, for each source with grey cells, *, Power BI unreachable for 2
checkouts*. A source says *Power BI · unreachable for 2 checkouts · 14 requests today · 2 errors*, *Jira · off*, or
*git · not polled yet* before the first tick; a window *window left · pycharm · open on desk, map* or *window right ·
not open*.

**Who is listening.** `serve._live` holds one entry per open `/api/events` stream, `{w, page, shell, since, last}`,
added before the stream starts and removed in its `finally`; `live_windows()` hands out copies. `w` and `page` are
kept only when they are names (`SKIN_FAMILY`), else `main` and `settings` (for `frames=theme`) or `desk`; `shell` is
`ink_facts`' (`shell=`, else `w=`). `last` is stamped on every frame written. It is in memory only: a connect or a
disconnect writes nothing, to `desk.json` or anywhere. **The honest bound:** a closed tab is noticed on its stream's
next write, which is at once when anything happens (an event, a poll, the desk) and at most `HEARTBEAT_S` (15 s) when
nothing does.

**What it is not.** No other machine: the fleet runs nothing remotely ([fleet.md](fleet.md) §What it deliberately is
not). No MCP (disabled by policy). No proxy, no pings, no outbound probe and no polling of its own: the sources are
what the poll already counted, and `/api/map` never creates a `Poller` (`current_poller()`). Nothing in `network`
carries a token, a URL, a filesystem path or an error text; a cell is `ok` and `age_s`, no more.

## The page

`GET /map` (`static/map.html`, `map.css`, `map/map.js`; `/open?page=map` lands there) is the fleet as a WAI-ARIA
tree, readable at any width and keyboard-first. The tree is the map's text twin and its whole plain look
([desk-rendering.md](desk-rendering.md) rules 3-4): the scene (#409) is drawn from it and carries nothing it lacks,
and #406 keeps it live. The page reads `GET /api/map` once, paints its theme (`applyTheme`, `applySkin`, which write
only on change), draws, and puts the graph's `says` in `#mapsays` (`aria-live="polite"`). Its `<body>` is
`class="ink-off"` for the page's whole life, and carries the desk's ink gate facts (`data-ink-shell`,
`data-ink-probe`, `data-ink-skins`: `serve.INKED_PAGES`) for the scene; nothing on /map ever removes `ink-off`.

**The tree.** One `li[role=treeitem]` per node, `data-node` its id, its words in `.say` (the node's `says`):

```
ul#maptree
  li p:<project>              data-name, data-default
    li c:<repo>               data-name, data-on       (main first, then worktrees)
      li a:<repo>             data-subagents
    li bs:<project>           text: branches_says; only when the project has it; starts collapsed
      li b:<project>:<name>
  li n:network                text: network.says; last; only when the graph has a network (#404)
    li n:server, li w:*, li s:*, li n:approvals, li n:install
```

`bs:<project>` and `n:network` are ids the page makes; every other id is the graph's. What is absent from the graph
(branches before #403 reads them, the network before #404) is not drawn.

**Classes**, from a closed list: `kind-<kind>`, `state-<state>`, `role-<role>`, `needs-human`, `live`, `stale` (an
agent); `main`, `worktree`, `dirty` (a checkout); `unmerged`, `is-current` (a non-empty `current_in`), `carrying` (a
branch); `connected` (a window); `grey` (a source with any cell `ok: false`); `pending` (approvals above 0). A kind,
state or role that is not a plain word is not written.

**Expansion.** `aria-expanded` is written only when an item is created: projects, checkouts and `n:network` open,
`bs:` closed. A redraw never undoes what the operator opened or closed; the choice is held in the DOM, in memory,
and not persisted. `#maptree [aria-expanded="false"] > ul` is not shown. Clicking an item's words toggles it.

**Keys** (the WAI-ARIA tree pattern): ↓ ↑ move through the visible items; → opens a closed item, else moves to its
first child; ← closes an open item, else moves to its parent; Home and End. One item is in the tab order (roving
`tabindex`): the last one reached, else the first. Enter on a checkout or an agent posts `window {w, open: <repo>}`
and lands on the desk, `w`, `shell` and `ink` kept (`pageUrl("/")`); `#mapback` goes there too.

**Focus** is a 2px `--focus` outline on the item's `.say`, never a state colour. No tree or header word is in
`--muted`: every one reads at 4.5:1 on the default and `sand` palettes (measured, computed, by the tests).

**Layout.** Plain, the tree is the page and `#mapstage` is not shown. With `body.map-scene` (#409 sets it) the tree
is a 320 px column and `#mapstage` fills the rest; at 900 px and below (a PyCharm tool window or a VS Code view) the
tree stacks above the stage at full width and the stage is `min(55vh, 480px)` tall.

**`window.FleetMap`** (frozen): `ready` resolves after the first draw; `draw(graph)` draws a graph of the caller's
and sets `paused`, which the page's own drawing (and #406's refetch) honours; `graph` is the last graph drawn;
`scene` is `null` until #409.

Tests: `tests/test_fleet_map_page.py` (5 browser tests, one Chromium for the module), plus the budgets and hooks in
`test_fleet_serve.py`, the gate in `test_fleet_ink.py` and the inventory in `test_fleet_components.py`.

## Staying live

(written by #406)

## Layout

(written by #408)

## The scene

(written by #409)

## Agents

(written by #410)

## Moving around

(written by #411)

## Focus and picking

(written by #412)

## Motion

(written by #413)

## Skins

(written by #414)

## Budgets

`map.html` and `map.css` sit in `static/` beside the desk's files, inside the desk's 200 KiB, and are held to 4 KiB
gzipped together. The map's scripts, `static/map/**/*.js` outside `map/skins/`, have `MAP_BUDGET` = 32 KiB gzipped
of their own (`tests/test_fleet_serve.py`), outside the desk's: a desk never fetches them. `INK_BUDGET` is untouched.
`map/map.js` is a classic script (checked by `node --check` as `.js`); every other `map/**/*.js` is checked as a module.

## Measured

(written by #415)
