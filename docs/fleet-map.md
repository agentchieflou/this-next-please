# The fleet map

The fleet map is the fleet drawn as its structure rather than as tiles: each project, the main checkout its
worktrees hang from, each checkout's agent and who started it, and (later) branches and the network around them.
It is **read-only**: nothing on the map starts, stops or changes anything; the desk does that. Epic #295.

## The graph

`GET /api/map` (token required, like every route but `/api/ping` and `/open`) answers
`{ok: true, schema: 1, as_of, cursor, says, projects, checkouts, theme}`. It is a pure fold over the same snapshot
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

(written by #404)

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
agent); `main`, `worktree`, `dirty` (a checkout); `unmerged`, `is-current` (a non-empty `current_in`), `carrying`,
`gone` (a branch; #406); `connected` (a window); `grey` (a source with any cell `ok: false`); `pending` (approvals above
0). A kind, state or role that is not a plain word is not written.

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

The map follows the fleet as it changes (`map/map.js`, #406), on a stream of its own; there is no
polling loop and nothing new on the server.

**The cursor.** After the first draw the page opens `GET /api/events?since=<graph.cursor>&w=<w>&page=map&notify=0`
(`shell` too when the page has one). `since` is the graph's `cursor`, so the stream starts after the events the
graph was folded from: it replays no agent's history, and a map opened on a busy fleet sees its first `agent` frame
only when something new happens. On a reconnect the cursor is the newest graph's.

**`notify=0`** (#356). The notification sweep's cursor is shared by every stream, so a stream that does not draw
`notify` frames would take the desk's and drop them. The map's stream never sweeps, and no `notify` frame reaches it.

**The throttle.** `agent`, `polls` and `desk` frames refetch `/api/map`, at most once per 400 ms: the first frame
arms a timer and later frames never push it back (the desk's `refreshSoon`). A trailing debounce would never fire
while a busy fleet streams agent frames. Nothing is refetched while `FleetMap.draw` holds the tree (`paused`). An
answer is drawn only when its `as_of` is newer than the drawn graph's (the same `run` and a larger `n`, or a new
`run`); an `as_of` of null is always taken. A `theme` frame paints at once (`applyTheme`, `applySkin`), and a graph
that was in flight when it came does not paint its older theme over it.

**The dot.** `#maplink` (`class="dot"`, after `#mapsays`) says the stream's state the way the desk's `#link` does:
*live* (`dot live`) on open and on every `tick`, *reconnecting* (`dot lost`) on an error. It is written through the
setters, so a `tick` on a live map is zero mutations. On an error the page closes the stream, and 2 s later refetches
the graph and reconnects from its cursor. Its words are `--text`, never `--muted`.

**Deleted branches.** When a graph drops a branch the previous graph had, its `b:<project>:<name>` item stays in the
`bs:` group, with class `gone` and the words *<name> · deleted*, until a later graph changes that project's branch
list again; then it goes. This keeps the tree saying what the scene shows (#413 strikes a deleted lane;
[desk-rendering.md](desk-rendering.md) rule 4). It is the only thing the tree carries from one graph to the next, and
like expansion it lives in memory and is not persisted. No per-event attribute (`data-seq` or the like) is written
into the tree.

**`FleetMap.stream`** is `{frames, state}`: the `agent` frames the stream has received, and `live` or `reconnecting`
(`""` before it first opens). For tests.

Tests: `tests/test_fleet_map_live.py` (2 plain tests, and 1 browser test that walks the cursor, the throttle, the
dot, expansion across refetches, a deleted branch, a `theme` frame and a stopped server on one page).

## Layout

`static/map/layout.js` (#408) says where everything on the map stands. It is an ES module of pure arithmetic:
no DOM, no three.js, no randomness, no clock, imported through `q()` like every module under `static/map/`.
`layout(outline)` depends only on names and structure. The same outline gives byte-identical `JSON.stringify`
output whatever order its arrays arrive in, keys it does not define (a state, a count, an age) change nothing,
and nothing is scaled by a count that changes with time (ahead counts, ages, event counts). The scene (#409)
builds the outline from the tree (§The page) and draws what comes back.

**The outline.** Only these fields are read:

```
{projects: [{id: "p:<project>", default: "b:<p>:<name>" | "",
             branches: [{id: "b:<p>:<name>", unmerged}],
             checkouts: [{id: "c:<repo>", main, on: "b:..." | "", agent: "a:<repo>" | ""}]}],
 network: {server, install, approvals: id | "", windows: [id], sources: [id], stale: [agent ids]}}
```

`network.stale` lists the `a:` items with class `stale`. The network, or any of its ids, may be absent (#404).

**What comes back**, in world units on the x-z ground, y up, where 1 unit is one island's width:

```
{nodes: {<id>: {x, y, z, w, h, d, kind}},          a box: its centre and its size
 lanes: [{id, project, from: [x, z], to: [x, z], trunk, unmerged}],
 links: [[idA, idB]],
 bounds: {minX, maxX, minZ, maxZ}}                 every box, and every lane at its width
```

`kind` is one of `project`, `island` (a checkout), `agent`, `server`, `window`, `source`, `install` and
`approvals`. Every id the outline names has a place: each branch (and the default) is a lane, and everything
else is a node. Nothing else is placed. A lane's width is not stored on the lane: it is `DIMS.trunkW`, `laneW`
or `stubW`.

**The rules.**

| What | Where |
| --- | --- |
| Districts | Projects by id on a grid of `ceil(sqrt(n))` columns, at a fixed pitch (`districtW` and `districtD`, each plus `gutter`) sized for the 40-lane cap, so a project growing a branch never moves another. The first row's heads are at z = 0; later rows are placed behind it (-z) |
| Gate | The project's node (`kind: project`), in front of its trunk's head |
| Trunk | The default branch: a road along -z from the head (lane `trunk: true`), `trunk` long plus one `pitch` for each other lane |
| Lanes | The other branches, by name, on alternating sides of the trunk (left first), one `pitch` apart, square to the trunk and touching it. An unmerged lane is `laneL` long and `laneW` wide; a merged one is a `stubL` by `stubW` stub. Both are fixed |
| Islands | The main checkout sits at the trunk's head (the first by id if several say `main`). Every other checkout stands at the far end of the lane it is `on`; on the default branch, that is past the trunk's end. A checkout `on` `""`, or on a lane its project lacks, stands beside the head, to the right. Checkouts that share a place stack there by id, one `floor` each, so none of them moves another |
| Agents | On their island, `y` above it |
| Network | Past the first row's heads: the hub behind the districts' centre, install (left) and approvals (right) beside it, the windows in a row behind it, and the sources in a column down the grid's right (+x) edge |
| Links | Hub to each window, hub to install, hub to approvals, each source to the hub, hub to each district's gate, and install to each agent in `network.stale`. There is no hub-to-agent link |

Every list is sorted by id before anything is placed, in plain code-unit order, never a locale's. The order an
array arrives in therefore never reaches the output.

**Why the network faces the heads.** The issue puts the hub "behind the districts' centre". It stands behind
the districts as seen from the lanes: past their heads, not past the far ends of their trunks. A district's
fixed cell stays empty past its last lane until the project has 40 lanes. A hub past the far ends would leave
that empty space between the hub and everything drawn: a one-project map would be about 40 units deep for 12
units of content, and every hub-to-head link would run the length of its district. With the hub past the heads,
links to the first row cross no district, and the bounds hug what exists. Moving it back is a sign change in
`layout()` (`hz`, the windows and the sources) and in the test's network rules.

**`DIMS`** holds every measure, frozen, so the laptop look (#415) retunes them in one place. They are halves and
quarters, which floating point adds exactly:

| Key | Value | What |
| --- | --- | --- |
| `island`, `islandH` | 1, 0.25 | An island's width and depth (the unit), and its height |
| `agent` | 0.5 | An agent's width, depth and height |
| `floor` | 1 | One storey of a stack: an island, its agent and the air above them |
| `gap` | 0.5 | The air between two neighbours |
| `trunkW`, `trunk` | 0.5, 2 | The trunk's width, and its length before its first lane (the head) |
| `pitch` | 0.75 | Along the trunk, from one lane to the next |
| `laneL`, `laneW` | 3, 0.375 | An unmerged lane's length and width |
| `stubL`, `stubW` | 0.75, 0.125 | A merged lane's length and width |
| `lanes` | 40 | The lanes a district is sized for (the graph's cap) |
| `gateW`, `gateH`, `gateD` | 2, 0.25, 0.5 | A project's gate |
| `hub`, `hubH` | 2, 1 | The server's width and depth, and its height |
| `node`, `nodeH` | 1, 0.5 | Every other network node |
| `gutter` | 2 | Between two districts, and between the grid and the network |
| `districtW`, `districtD` | 8.5, 34 | A district's fixed footprint, derived from the values above |

**No force-directed or physics layout.** A force layout animates until it settles and moves everything whenever
anything changes. That breaks the render contract, under which an idle map draws zero WebGL frames (§The scene),
and it makes motion (#413) impossible to reason about. Rules over names and structure give every node its place
at once, and a place changes only when the structure does.

Tests: `tests/test_fleet_map_layout.py` holds two tests. One reads the source in plain Python: no `Math.random`,
`Date`, `performance`, `globalThis`, `window.` or `document.` member, static import or colour literal, and under
6 KiB gzipped (inside `MAP_BUDGET`). The other is one browser test that opens `/map` once and runs every case in
a single `page.evaluate`.

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
