# `map/layout.js`

The reasoning that used to be this file's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries code, and inline `/** @type {X} */ (expr)`
casts where `tsc` needs them, and nothing else.

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The map's layout (#408, docs/fleet-map.md §Layout): where every project, lane, checkout, agent
and network node of /map stands.

`layout(outline)` is pure arithmetic over names and structure. It reads no page, no three.js, no
dice and no clock, and it scales nothing by a count that changes with time (ahead counts, ages,
events), so a state change never moves anything, and one outline always gives the same places,
byte for byte, whatever order its arrays arrive in. The scene (#409) builds the outline from the
tree and draws what comes back. There is no force-directed or physics layout: it would animate
until it settled and move everything whenever anything changed, and an idle map draws no frames.

The ground is x-z with y up, and one unit is an island's width. Every district's head faces the
network: its trunk runs from the head along -z, and the hub stands behind the districts' centre
as the lanes see it, past the first row's heads (+z). A hub-to-head link then crosses no district
of that row, and the bounds hug what exists, for the far end of a district's fixed cell stays
empty until its project has that many lanes. The rows go back (-z), the sources down the grid's
right (+x) edge. Every measure is in `DIMS`, so the laptop look (#415) retunes them in one place;
they are halves and quarters, which floating point adds exactly.

### `const BASE`

Beside `island: 1,`:

an island's width and depth: the map's unit

Beside `islandH: 0.25,`:

an island's height

Beside `agent: 0.5,`:

an agent's width, depth and height; it stands on its island

Beside `floor: 1,`:

one storey of a stack: an island, its agent and the air above it

Beside `gap: 0.5,`:

the air between two neighbours

Beside `trunkW: 0.5,`:

the trunk's width

Beside `trunk: 2,`:

the trunk's length before its first lane: the head, where the main checkout sits

Beside `pitch: 0.75,`:

along the trunk from one lane to the next, which is on the other side

Beside `laneL: 3,`:

an unmerged lane is long ...

Beside `laneW: 0.375,`:

... and wide

Beside `stubL: 0.75,`:

a merged lane is a short ...

Beside `stubW: 0.125,`:

... narrow stub touching the trunk

Beside `lanes: 40,`:

the lanes a district is sized for: the graph's cap

Beside `gateW: 2,`:

a project's node, the gate in front of its trunk's head: width,

Beside `gateH: 0.25,`:

height

Beside `gateD: 0.5,`:

and depth

Beside `hub: 2,`:

the server: width and depth,

Beside `hubH: 1,`:

and height

Beside `node: 1,`:

every other network node: width and depth,

Beside `nodeH: 0.5,`:

and height

Beside `gutter: 2`:

between two districts, and between the grid and the network

### `export const DIMS`

Above `export const DIMS = Object.freeze({`:

A district's footprint is fixed, sized for `lanes` lanes whatever its project holds today, so a
project growing a branch never moves another. `trunk + lanes * pitch` is the longest trunk.

### `function entries`

Above `function entries(list) {`:

An outline's entries that carry an id, sorted by it (code-unit order, never a locale's), each id
once: the order an array arrives in never reaches the output. The tree's ids are unique.

### `function district`

Above `function district(p, x0, z0, put, road) {`:

One project's district, its cell's back-left corner at (x0, z0).

Beside `const head = z0 + D.districtD - D.gateD - D.gap;`:

where the trunk starts

Beside `const end = head - D.trunk - side.length * D.pitch;`:

one pitch past the last lane

Beside `const stops = new Map();`:

a lane's id -> where its checkouts stand

Beside `const s = i % 2 ? 1 : -1, z = head - D.trunk - i * D.pitch;`:

left first, then right

Above `const storeys = new Map();`:

Checkouts that share a place stack there by name, a storey each, so none moves another.

### `export function layout`

Above `export function layout(outline) {`:

`outline`: {projects: [{id, default, branches: [{id, unmerged}], checkouts: [{id, main, on, agent}]}],
network: {server, install, approvals, windows: [id], sources: [id], stale: [agent id]}}. Only these
fields are read. Returns {nodes: {id: {x, y, z, w, h, d, kind}}, lanes: [{id, project, from: [x, z],
to: [x, z], trunk, unmerged}], links: [[id, id]], bounds: {minX, maxX, minZ, maxZ}}: a node's x, y, z
is its box's centre, and a lane's width is DIMS's (`trunkW`, `laneW`, `stubW`).

In `layout`, above `const projects = entries(o.projects), cols = Math.ceil(Math.sqrt(projects.length));`:

Districts: by id on a grid of ceil(sqrt(n)) columns at a fixed pitch. The first row's heads
are at z = 0 and the rows go back from there, so a new row never moves the network.

In `layout`, above `const gridW = projects.length ? cols * px - D.gutter : 0;`:

The network, past the first row's heads: the hub behind the districts' centre, install and
approvals beside it, the windows in a row behind it, the sources down the grid's right edge.

In `layout`, above `const link = (a, b) => { if (placed.has(a) && placed.has(b)) links.push([a, b]); };`:

Links: the hub to each window, the install, approvals, each source and each district's head;
the install to each stale agent. Never the hub to an agent.

In `layout`, above `let box = null;`:

The bounds: every node's box and every lane at its width.
