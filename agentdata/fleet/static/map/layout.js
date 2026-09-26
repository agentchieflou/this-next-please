const BASE = {
  island: 1,
  islandH: 0.25,
  agent: 0.5,
  floor: 1,
  gap: 0.5,
  trunkW: 0.5,
  trunk: 2,
  pitch: 0.75,
  laneL: 3,
  laneW: 0.375,
  stubL: 0.75,
  stubW: 0.125,
  lanes: 40,
  gateW: 2,
  gateH: 0.25,
  gateD: 0.5,
  hub: 2,
  hubH: 1,
  node: 1,
  nodeH: 0.5,
  gutter: 2
};

export const DIMS = Object.freeze({
  ...BASE,
  districtW: 2 * Math.max(BASE.trunkW / 2 + Math.max(BASE.laneL, BASE.stubL) + BASE.island,
                          1.5 * BASE.island + BASE.gap, BASE.gateW / 2),
  districtD: BASE.gateD + BASE.gap + BASE.trunk + BASE.lanes * BASE.pitch + BASE.island
});

const byId = (a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
const word = v => (typeof v === "string" ? v : "");

function entries(list) {
  const kept = (Array.isArray(list) ? list : []).filter(e => e && word(e.id));
  return kept.sort(byId).filter((e, i) => !i || kept[i - 1].id !== e.id);
}

function ids(list) {
  const kept = (Array.isArray(list) ? list : []).filter(word).sort();
  return kept.filter((s, i) => !i || kept[i - 1] !== s);
}

function district(p, x0, z0, put, road) {
  const D = DIMS, cx = x0 + D.districtW / 2;
  const head = z0 + D.districtD - D.gateD - D.gap;
  put(p.id, "project", cx, D.gateH / 2, head + D.gap + D.gateD / 2, D.gateW, D.gateH, D.gateD);
  const def = word(p.default);
  const side = entries(p.branches).filter(b => b.id !== def);
  const end = head - D.trunk - side.length * D.pitch;
  const stops = new Map();
  if (def) {
    road(def, p.id, [cx, head], [cx, end], true, false);
    stops.set(def, [cx, end - D.island / 2]);
  }
  side.forEach((b, i) => {
    const s = i % 2 ? 1 : -1, z = head - D.trunk - i * D.pitch;
    const x = cx + s * D.trunkW / 2, len = b.unmerged ? D.laneL : D.stubL;
    road(b.id, p.id, [x, z], [x + s * len, z], false, !!b.unmerged);
    stops.set(b.id, [x + s * (len + D.island / 2), z]);
  });
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

  const projects = entries(o.projects), cols = Math.ceil(Math.sqrt(projects.length));
  const px = D.districtW + D.gutter, pz = D.districtD + D.gutter;
  projects.forEach((p, i) => district(p, (i % cols) * px, -Math.floor(i / cols) * pz - D.districtD, put, road));

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

  const link = (a, b) => { if (placed.has(a) && placed.has(b)) links.push([a, b]); };
  if (server) {
    windows.forEach(w => link(server, w));
    link(server, install);
    link(server, approvals);
    sources.forEach(s => link(s, server));
    projects.forEach(p => link(server, p.id));
  }
  ids(net.stale).forEach(a => { if ((placed.get(a) || {}).kind === "agent") link(install, a); });

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
