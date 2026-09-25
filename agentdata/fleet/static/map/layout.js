/* The map's layout (#408, docs/fleet-map.md §Layout): where every project, lane, checkout, agent
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
   they are halves and quarters, which floating point adds exactly. */

const BASE = {
  island: 1,          // an island's width and depth: the map's unit
  islandH: 0.25,      // an island's height
  agent: 0.5,         // an agent's width, depth and height; it stands on its island
  floor: 1,           // one storey of a stack: an island, its agent and the air above it
  gap: 0.5,           // the air between two neighbours
  trunkW: 0.5,        // the trunk's width
  trunk: 2,           // the trunk's length before its first lane: the head, where the main checkout sits
  pitch: 0.75,        // along the trunk from one lane to the next, which is on the other side
  laneL: 3,           // an unmerged lane is long ...
  laneW: 0.375,       // ... and wide
  stubL: 0.75,        // a merged lane is a short ...
  stubW: 0.125,       // ... narrow stub touching the trunk
  lanes: 40,          // the lanes a district is sized for: the graph's cap
  gateW: 2,           // a project's node, the gate in front of its trunk's head: width,
  gateH: 0.25,        // height
  gateD: 0.5,         // and depth
  hub: 2,             // the server: width and depth,
  hubH: 1,            // and height
  node: 1,            // every other network node: width and depth,
  nodeH: 0.5,         // and height
  gutter: 2           // between two districts, and between the grid and the network
};

/* A district's footprint is fixed, sized for `lanes` lanes whatever its project holds today, so a
   project growing a branch never moves another. `trunk + lanes * pitch` is the longest trunk. */
export const DIMS = Object.freeze({
  ...BASE,
  districtW: 2 * Math.max(BASE.trunkW / 2 + Math.max(BASE.laneL, BASE.stubL) + BASE.island,
                          1.5 * BASE.island + BASE.gap, BASE.gateW / 2),
  districtD: BASE.gateD + BASE.gap + BASE.trunk + BASE.lanes * BASE.pitch + BASE.island
});

const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const word = v => (typeof v === "string" ? v : "");

/* An outline's entries that carry an id, sorted by it (code-unit order, never a locale's), each id
   once: the order an array arrives in never reaches the output. The tree's ids are unique. */
function entries(list) {
  const kept = (Array.isArray(list) ? list : []).filter(e => e && word(e.id));
  return kept.sort(byId).filter((e, i) => !i || kept[i - 1].id !== e.id);
}

function ids(list) {
  const kept = (Array.isArray(list) ? list : []).filter(word).sort();
  return kept.filter((s, i) => !i || kept[i - 1] !== s);
}

/* One project's district, its cell's back-left corner at (x0, z0). */
function district(p, x0, z0, put, road) {
  const D = DIMS, cx = x0 + D.districtW / 2;
  const head = z0 + D.districtD - D.gateD - D.gap;           // where the trunk starts
  put(p.id, "project", cx, D.gateH / 2, head + D.gap + D.gateD / 2, D.gateW, D.gateH, D.gateD);
  const def = word(p.default);
  const side = entries(p.branches).filter(b => b.id !== def);
  const end = head - D.trunk - side.length * D.pitch;        // one pitch past the last lane
  const stops = new Map();                                   // a lane's id -> where its checkouts stand
  if (def) {
    road(def, p.id, [cx, head], [cx, end], true, false);
    stops.set(def, [cx, end - D.island / 2]);
  }
  side.forEach((b, i) => {
    const s = i % 2 ? 1 : -1, z = head - D.trunk - i * D.pitch;   // left first, then right
    const x = cx + s * D.trunkW / 2, len = b.unmerged ? D.laneL : D.stubL;
    road(b.id, p.id, [x, z], [x + s * len, z], false, !!b.unmerged);
    stops.set(b.id, [x + s * (len + D.island / 2), z]);
  });
  // Checkouts that share a place stack there by name, a storey each, so none moves another.
  const storeys = new Map();
  const stand = (c, [x, z]) => {
    const key = x + "," + z, k = storeys.get(key) || 0, y = k * D.floor;
    storeys.set(key, k + 1);
    put(c.id, "island", x, y + D.islandH / 2, z, D.island, D.islandH, D.island);
    put(word(c.agent), "agent", x, y + D.islandH + D.agent / 2, z, D.agent, D.agent, D.agent);
  };
  const checkouts = entries(p.checkouts), main = checkouts.find(c => c.main), at = head - D.island / 2;
  checkouts.forEach(c => stand(c, c === main ? [cx, at] : stops.get(word(c.on)) || [cx + D.island + D.gap, at]));
}

/* `outline`: {projects: [{id, default, branches: [{id, unmerged}], checkouts: [{id, main, on, agent}]}],
   network: {server, install, approvals, windows: [id], sources: [id], stale: [agent id]}}. Only these
   fields are read. Returns {nodes: {id: {x, y, z, w, h, d, kind}}, lanes: [{id, project, from: [x, z],
   to: [x, z], trunk, unmerged}], links: [[id, id]], bounds: {minX, maxX, minZ, maxZ}}: a node's x, y, z
   is its box's centre, and a lane's width is DIMS's (`trunkW`, `laneW`, `stubW`). */
export function layout(outline) {
  const D = DIMS, o = outline || {}, net = o.network || {};
  const placed = new Map(), lanes = [], roads = new Set(), links = [];
  const put = (id, kind, x, y, z, w, h, d) => {
    if (id && !placed.has(id)) placed.set(id, { x, y, z, w, h, d, kind });
  };
  const road = (id, project, from, to, trunk, unmerged) => {
    if (roads.has(id)) return;
    roads.add(id);
    lanes.push({ id, project, from, to, trunk, unmerged });
  };

  // Districts: by id on a grid of ceil(sqrt(n)) columns at a fixed pitch. The first row's heads
  // are at z = 0 and the rows go back from there, so a new row never moves the network.
  const projects = entries(o.projects), cols = Math.ceil(Math.sqrt(projects.length));
  const px = D.districtW + D.gutter, pz = D.districtD + D.gutter;
  projects.forEach((p, i) => district(p, (i % cols) * px, -Math.floor(i / cols) * pz - D.districtD, put, road));

  // The network, past the first row's heads: the hub behind the districts' centre, install and
  // approvals beside it, the windows in a row behind it, the sources down the grid's right edge.
  const gridW = projects.length ? cols * px - D.gutter : 0;
  const hx = gridW / 2, hz = D.gutter + D.hub / 2, step = D.node + D.gap;
  const beside = D.hub / 2 + D.gap + D.node / 2;
  const server = word(net.server), install = word(net.install), approvals = word(net.approvals);
  const windows = ids(net.windows), sources = ids(net.sources);
  const node = (id, kind, x, z) => put(id, kind, x, D.nodeH / 2, z, D.node, D.nodeH, D.node);
  put(server, "server", hx, D.hubH / 2, hz, D.hub, D.hubH, D.hub);
  node(install, "install", hx - beside, hz);
  node(approvals, "approvals", hx + beside, hz);
  windows.forEach((w, k) => node(w, "window", hx + (k - (windows.length - 1) / 2) * step, hz + beside));
  sources.forEach((s, k) => node(s, "source", gridW + D.gutter + D.node / 2, -D.node / 2 - k * step));

  // Links: the hub to each window, the install, approvals, each source and each district's head;
  // the install to each stale agent. Never the hub to an agent.
  const link = (a, b) => { if (placed.has(a) && placed.has(b)) links.push([a, b]); };
  if (server) {
    windows.forEach(w => link(server, w));
    link(server, install);
    link(server, approvals);
    sources.forEach(s => link(s, server));
    projects.forEach(p => link(server, p.id));
  }
  ids(net.stale).forEach(a => { if ((placed.get(a) || {}).kind === "agent") link(install, a); });

  // The bounds: every node's box and every lane at its width.
  let box = null;
  const grow = (x0, x1, z0, z1) => {
    box = box ? [Math.min(box[0], x0), Math.max(box[1], x1), Math.min(box[2], z0), Math.max(box[3], z1)]
              : [x0, x1, z0, z1];
  };
  placed.forEach(b => grow(b.x - b.w / 2, b.x + b.w / 2, b.z - b.d / 2, b.z + b.d / 2));
  lanes.forEach(l => {
    const r = (l.trunk ? D.trunkW : l.unmerged ? D.laneW : D.stubW) / 2;
    grow(Math.min(l.from[0], l.to[0]) - r, Math.max(l.from[0], l.to[0]) + r,
         Math.min(l.from[1], l.to[1]) - r, Math.max(l.from[1], l.to[1]) + r);
  });
  const [minX, maxX, minZ, maxZ] = box || [0, 0, 0, 0];
  return { nodes: Object.fromEntries(placed), lanes, links, bounds: { minX, maxX, minZ, maxZ } };
}
