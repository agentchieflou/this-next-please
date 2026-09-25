"""The map's layout module (#408, docs/fleet-map.md §Layout): `static/map/layout.js`.

`layout(outline)` places every project, lane, checkout, agent and network node from names and
structure alone. The first test reads the module's source for what a pure function may not reach
for. The second opens ONE Chromium page on `/map`, imports the module through `q()` as the scene
(#409) will, and runs every case in one `page.evaluate`, so a CI leg pays for one browser launch.
The only wait is on a condition (`window.FleetMap`).
"""
from __future__ import annotations

import gzip
import json
import os
import re

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _serve, _stop
from test_fleet_map import fleet_home  # noqa: F401 - fixture

LAYOUT = os.path.join(S.STATIC, "map", "layout.js")

#: What a pure function of the outline may not reach for (#408): dice, a clock, a global, the page.
BANNED = {
    "Math.random": r"\bMath\s*\.\s*random\b",
    "Date": r"\bDate\b",
    "performance": r"\bperformance\b",
    "globalThis": r"\bglobalThis\b",
    "a member of window or document": r"\b(window|document)\s*\.",
}
#: A colour written in a module: the regex of tests/test_fleet_ink_farmstead.py:121.
COLOUR = r"[\"'`]#[0-9A-Fa-f]{3,8}\b|\b0x[0-9A-Fa-f]{6}\b|\brgba?\(\s*\d"
#: What the module may weigh over the wire, inside `MAP_BUDGET` (tests/test_fleet_serve.py).
LAYOUT_BUDGET = 6 * 1024


def test_the_layout_module_is_arithmetic_and_nothing_else():
    body = open(LAYOUT, encoding="utf-8").read()
    for what, pattern in BANNED.items():
        assert not re.search(pattern, body), f"map/layout.js reaches for {what}"
    assert not re.search(COLOUR, body), "a colour written in map/layout.js"
    # The token rule of static/ink/ holds in static/map/ (tests/test_fleet_ink.py): no static
    # import, and anything imported carries the token.
    assert not re.search(r"(?m)^\s*import\s[^(]", body), "map/layout.js has a static import"
    for spec in re.findall(r"import\(([^)]*\))", body):
        assert spec.startswith("q("), f"map/layout.js imports {spec} without the token"
    assert re.search(r"(?m)^export const DIMS = ", body), "DIMS is not exported"
    assert re.search(r"(?m)^export function layout\(outline\) \{", body), "layout is not exported"
    sent = len(gzip.compress(body.encode("utf-8"), 6, mtime=0))
    print(f"\n  map/layout.js {sent} bytes gzipped")
    assert sent < LAYOUT_BUDGET, sent


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


# Every case, in the page. Each returns what Python asserts on: the JSON of two layouts that must be
# byte-identical, the ids that moved between two layouts, or a list of the rules a layout broke.
CASES = r"""async () => {
  const L = await import(q("/static/map/layout.js"));
  const D = L.DIMS, J = JSON.stringify, copy = v => JSON.parse(J(v));
  const pad = i => String(i).padStart(2, "0"), EPS = 1e-9;

  /* n projects of b branches each, the first (`main`) their default -- or, with `beside`, 40 branches
     and a default the capped list left out: the most lanes a district holds. Each project has its
     main checkout, worktrees on an unmerged lane, a merged lane and the trunk, two on no lane, and
     an agent on every checkout but the last. */
  function outline(n, b, beside) {
    const projects = [];
    for (let i = 0; i < n; i++) {
      const p = "p" + pad(i), def = b || beside ? `b:${p}:main` : "";
      const names = [...Array(beside ? 40 : b).keys()].map(k => (k || beside ? "feature/f" + pad(k) : "main"));
      const branches = names.map((name, k) => ({ id: `b:${p}:${name}`, unmerged: k % 3 === 1 }));
      const side = branches.filter(x => x.id !== def), first = list => (list.length ? list[0].id : "");
      projects.push({ id: `p:${p}`, default: def, branches, checkouts: [
        { id: `c:${p}`, main: true, on: def, agent: `a:${p}` },
        { id: `c:${p}-a`, main: false, on: first(side.filter(x => x.unmerged)), agent: `a:${p}-a` },
        { id: `c:${p}-b`, main: false, on: first(side.filter(x => !x.unmerged)), agent: `a:${p}-b` },
        { id: `c:${p}-c`, main: false, on: def, agent: `a:${p}-c` },
        { id: `c:${p}-d`, main: false, on: "", agent: `a:${p}-d` },
        { id: `c:${p}-e`, main: false, on: "", agent: "" }] });
    }
    return { projects, network: {
      server: "n:server", install: "n:install", approvals: "n:approvals",
      windows: ["w:main", "w:side", "w:pycharm"], sources: ["s:jira", "s:bitbucket", "s:teradata"],
      stale: n ? ["a:p00-a"] : [] } };
  }

  /* What an outline names: each node id's kind and project, and the lane ids. */
  function named(o) {
    const kinds = {}, owner = {}, lanes = [];
    for (const p of o.projects || []) {
      kinds[p.id] = "project"; owner[p.id] = p.id;
      for (const c of p.checkouts) {
        kinds[c.id] = "island"; owner[c.id] = p.id;
        if (c.agent) { kinds[c.agent] = "agent"; owner[c.agent] = p.id; }
      }
      for (const b of p.branches) lanes.push(b.id);
      if (p.default && !lanes.includes(p.default)) lanes.push(p.default);
    }
    const net = o.network || {};
    for (const k of ["server", "install", "approvals"]) if (net[k]) kinds[net[k]] = k;
    for (const w of net.windows || []) kinds[w] = "window";
    for (const s of net.sources || []) kinds[s] = "source";
    return { kinds, owner, lanes: lanes.sort() };
  }

  const wide = l => (l.trunk ? D.trunkW : l.unmerged ? D.laneW : D.stubW) / 2;
  const laneRect = l => (l.from[1] === l.to[1]
    ? [Math.min(l.from[0], l.to[0]), Math.max(l.from[0], l.to[0]), l.from[1] - wide(l), l.from[1] + wide(l)]
    : [l.from[0] - wide(l), l.from[0] + wide(l), Math.min(l.from[1], l.to[1]), Math.max(l.from[1], l.to[1])]);
  const rect = b => [b.x - b.w / 2, b.x + b.w / 2, b.z - b.d / 2, b.z + b.d / 2];
  const union = (a, b) => (a ? [Math.min(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.max(a[3], b[3])] : b);
  const cross = (a, b) => a[0] < b[1] - EPS && b[0] < a[1] - EPS && a[2] < b[3] - EPS && b[2] < a[3] - EPS;
  const solid = (a, b) => cross(rect(a), rect(b)) && a.y - a.h / 2 < b.y + b.h / 2 - EPS && b.y - b.h / 2 < a.y + a.h / 2 - EPS;

  /* Each district's footprint: everything of its project, nodes and lanes. */
  function footprints(o, got) {
    const owner = named(o).owner, foot = {};
    for (const [id, b] of Object.entries(got.nodes)) if (owner[id]) foot[owner[id]] = union(foot[owner[id]], rect(b));
    for (const l of got.lanes) foot[l.project] = union(foot[l.project], laneRect(l));
    return foot;
  }

  /* The rules every layout keeps: every id placed as its kind and nothing else placed, no two
     districts' footprints overlapping, no network node in a district, no two nodes sharing space,
     and everything inside the bounds. */
  function broken(o, got) {
    const out = [], want = named(o);
    for (const [id, kind] of Object.entries(want.kinds)) {
      if (!got.nodes[id]) out.push(`no node for ${id}`);
      else if (got.nodes[id].kind !== kind) out.push(`${id} is a ${got.nodes[id].kind}, not a ${kind}`);
    }
    for (const id of Object.keys(got.nodes)) if (!want.kinds[id]) out.push(`a node for ${id}, which the outline does not name`);
    const lanes = got.lanes.map(l => l.id).sort();
    if (J(lanes) !== J(want.lanes)) out.push(`lanes ${J(lanes)}, not ${J(want.lanes)}`);
    const foot = footprints(o, got), ps = Object.keys(foot).sort();
    ps.forEach((a, i) => ps.slice(i + 1).forEach(b => { if (cross(foot[a], foot[b])) out.push(`districts ${a} and ${b} overlap`); }));
    const all = Object.entries(got.nodes);
    for (const [id, b] of all) if (!want.owner[id]) for (const p of ps) if (cross(rect(b), foot[p])) out.push(`${id} stands in ${p}`);
    all.forEach(([a, x], i) => all.slice(i + 1).forEach(([b, y]) => { if (solid(x, y)) out.push(`${a} and ${b} share space`); }));
    const bb = got.bounds;
    const outside = r => r[0] < bb.minX - EPS || r[1] > bb.maxX + EPS || r[2] < bb.minZ - EPS || r[3] > bb.maxZ + EPS;
    for (const [id, b] of all) if (outside(rect(b))) out.push(`${id} is outside the bounds`);
    for (const l of got.lanes) if (outside(laneRect(l))) out.push(`lane ${l.id} is outside the bounds`);
    return out;
  }

  /* The ids whose node differs between two layouts. */
  const moved = (a, b) => [...new Set([...Object.keys(a.nodes), ...Object.keys(b.nodes)])]
    .filter(id => J(a.nodes[id]) !== J(b.nodes[id])).sort();

  /* The outline with every array reordered by f. */
  function reorder(o, f) {
    const c = copy(o);
    c.projects = f(c.projects.map(p => Object.assign(p, { branches: f(p.branches), checkouts: f(p.checkouts) })));
    for (const k of ["windows", "sources", "stale"]) c.network[k] = f(c.network[k]);
    return c;
  }

  const got = {};

  // The same outline, twice and reordered: byte-identical; and the outline is left as it was.
  const o = outline(7, 9);
  o.network.stale.push("a:p03-b");
  const before = J(o), first = J(L.layout(o));
  got.determinism = { first, again: J(L.layout(o)), untouched: J(o) === before,
                      reversed: J(L.layout(reorder(o, a => a.slice().reverse()))),
                      rotated: J(L.layout(reorder(o, a => a.slice(1).concat(a.slice(0, 1))))) };

  // Keys the outline does not define (a state, a count, an age) change nothing.
  const noisy = copy(o), junk = { state: "running", count: 7, age: 3600, says: "anything", ahead: 12 };
  for (const p of noisy.projects) {
    Object.assign(p, junk);
    p.branches.forEach(b => Object.assign(b, junk));
    p.checkouts.forEach(c => Object.assign(c, junk, { dirty: true, branch: "feature/x", live: true }));
  }
  Object.assign(noisy.network, junk);
  Object.assign(noisy, junk);
  got.extra = J(L.layout(noisy));

  // 1 to 20 projects of 0, 1 and 40 branches, and of 40 lanes beside their default.
  const seen = [];
  for (let n = 1; n <= 20; n++) {
    for (const [b, beside, what] of [[0, false, "0 branches"], [1, false, "1 branch"], [40, false, "40 branches"],
                                    [0, true, "40 lanes and the default"]]) {
      const oo = outline(n, b, beside);
      for (const p of broken(oo, L.layout(oo))) seen.push(`${n} projects of ${what}: ${p}`);
    }
  }
  got.grid = { count: seen.length, first: seen.slice(0, 12) };

  // An empty outline, one with no network yet (#404), one with no projects.
  const lone = { projects: outline(2, 3).projects }, net = { projects: [], network: outline(0, 0).network };
  got.edges = { empty: J(L.layout({})), missing: J(L.layout(undefined)),
                lone: broken(lone, L.layout(lone)), net: broken(net, L.layout(net)) };

  // A branch added to any one project moves nothing of any other, the network included.
  const five = outline(5, 9), owner = named(five).owner;
  got.grow = five.projects.map((p, i) => {
    const more = copy(five);
    more.projects[i].branches.push({ id: `b:${p.id.slice(2)}:aaa-first`, unmerged: true });
    const A = L.layout(five), B = L.layout(more), other = l => l.project !== p.id;
    return { project: p.id, outside: moved(A, B).filter(id => owner[id] !== p.id),
             inside: moved(A, B).filter(id => owner[id] === p.id).length,
             lanes: J(A.lanes.filter(other)) === J(B.lanes.filter(other)), links: J(A.links) === J(B.links),
             added: B.lanes.filter(l => !A.lanes.some(k => k.id === l.id)).map(l => [l.id, l.project]) };
  });

  // A checkout moved to another lane (one unmerged, one merged, nobody on either) moves alone.
  const three = outline(3, 9), X = L.layout(three);
  got.move = ["b:p01:feature/f04", "b:p01:feature/f03"].map(lane => {
    const m = copy(three);
    m.projects[1].checkouts.find(c => c.id === "c:p01-a").on = lane;
    const Y = L.layout(m);
    return { lane, moved: moved(X, Y), lanes: J(X.lanes) === J(Y.lanes), links: J(X.links) === J(Y.links) };
  });

  // An agent marked stale gains one install link, and nothing moves.
  const fresh = L.layout(three), staled = copy(three);
  staled.network.stale.push("a:p02-d");
  const S = L.layout(staled), has = (list, k) => list.some(j => J(j) === J(k));
  got.stale = { added: S.links.filter(k => !has(fresh.links, k)), kept: fresh.links.every(k => has(S.links, k)),
                grew: S.links.length - fresh.links.length, moved: moved(fresh, S),
                lanes: J(fresh.lanes) === J(S.lanes), bounds: J(fresh.bounds) === J(S.bounds) };

  // The rules of §Layout, on a 2x2 grid whose p:p01 has its main checkout on a feature lane (it
  // still sits at the head) and two worktrees on one lane.
  const r = outline(4, 9), p1 = r.projects[1];
  p1.checkouts[0].on = "b:p01:feature/f05";
  p1.checkouts.push({ id: "c:p01-f", main: false, on: "b:p01:feature/f01", agent: "a:p01-f" });
  const R = L.layout(r), N = R.nodes, rules = [], rule = (ok, what) => { if (!ok) rules.push(what); };
  const lanes = R.lanes.filter(l => l.project === "p:p01"), trunks = lanes.filter(l => l.trunk);
  const side = lanes.filter(l => !l.trunk), t = trunks[0] || { from: [0, 0], to: [0, 0] }, tx = t.from[0];
  rule(trunks.length === 1 && t.id === p1.default && t.unmerged === false, `one trunk, the default: ${J(trunks)}`);
  rule(t.from[0] === t.to[0] && t.to[1] < t.from[1], `the trunk runs along -z from the head: ${J(t)}`);
  rule(J(side.map(l => l.id)) === J(p1.branches.map(b => b.id).filter(id => id !== p1.default).sort()),
       `the other lanes, sorted by name: ${J(side.map(l => l.id))}`);
  side.forEach((l, i) => {
    const b = p1.branches.find(x => x.id === l.id), s = Math.sign(l.from[0] - tx);
    rule(l.unmerged === b.unmerged && l.trunk === false, `${l.id} is unmerged as its branch is`);
    rule(l.from[1] === l.to[1] && Math.abs(l.from[0] - tx) === D.trunkW / 2, `${l.id} leaves the trunk square: ${J(l)}`);
    rule(Math.sign(l.to[0] - l.from[0]) === s && Math.abs(l.to[0] - l.from[0]) === (b.unmerged ? D.laneL : D.stubL),
         `${l.id} is ${b.unmerged ? "long" : "a stub"}: ${J(l)}`);
    rule(l.from[1] < t.from[1] && l.from[1] > t.to[1], `${l.id} joins the trunk between its ends`);
    if (i) {
      rule(s === -Math.sign(side[i - 1].from[0] - tx), `${l.id} is on the other side from ${side[i - 1].id}`);
      rule(side[i - 1].from[1] - l.from[1] === D.pitch, `${l.id} is one pitch behind ${side[i - 1].id}`);
    }
  });
  rule(D.laneL > D.stubL && D.laneW > D.stubW, "an unmerged lane is longer and wider than a stub");
  const lane = id => lanes.find(l => l.id === id), atEnd = (c, l) => {
    const s = Math.sign(l.to[0] - l.from[0]);
    return N[c].z === l.to[1] && (N[c].x - l.to[0]) * s === N[c].w / 2;
  };
  rule(N["c:p01"].x === tx && N["c:p01"].z < t.from[1] && N["c:p01"].z > t.from[1] - D.trunk,
       `the main checkout sits at the trunk's head: ${J(N["c:p01"])}`);
  rule(atEnd("c:p01-a", lane("b:p01:feature/f01")) && atEnd("c:p01-b", lane("b:p01:feature/f02")),
       "a worktree stands at the far end of its lane");
  rule(N["c:p01-c"].x === tx && N["c:p01-c"].z === t.to[1] - N["c:p01-c"].d / 2,
       `a worktree on the default stands at the trunk's far end: ${J(N["c:p01-c"])}`);
  const stack = (a, b) => N[a].x === N[b].x && N[a].z === N[b].z && N[a].y < N[b].y;
  rule(stack("c:p01-a", "c:p01-f"), "two worktrees on one lane stack there by name");
  rule(stack("c:p01-d", "c:p01-e") && N["c:p01-d"].z === N["c:p01"].z && N["c:p01-d"].x !== tx,
       "a checkout on no lane stands beside the trunk's head, stacked by name");
  for (const c of r.projects.flatMap(p => p.checkouts)) {
    if (!c.agent) continue;
    const a = N[c.agent], i = N[c.id];
    rule(a.x === i.x && a.z === i.z && a.y - a.h / 2 === i.y + i.h / 2, `${c.agent} stands on ${c.id}`);
  }
  // The heads face the network: a district's gate is its front (+z), and the hub stands past the
  // first row's gates, behind the districts' centre as the lanes see it.
  const feet = footprints(r, R), foot = Object.values(feet), gates = r.projects.map(p => N[p.id].x);
  for (const p of r.projects) rule(N[p.id].z + N[p.id].d / 2 === feet[p.id][3], `${p.id}'s gate is its district's front`);
  const hub = N["n:server"], cx = (Math.min(...gates) + Math.max(...gates)) / 2;
  rule(hub.x === cx && hub.z - hub.d / 2 > Math.max(...foot.map(f => f[3])), `the hub stands behind the districts' centre: ${J(hub)}`);
  const ws = r.network.windows.slice().sort().map(w => N[w]), ss = r.network.sources.slice().sort().map(s => N[s]);
  rule(ws.every(w => w.z === ws[0].z && w.z - w.d / 2 > hub.z + hub.d / 2), "the windows stand in a row behind the hub");
  rule(ws.every((w, i) => !i || w.x > ws[i - 1].x) && ws.reduce((s, w) => s + w.x, 0) / ws.length === hub.x,
       "the row is in name order and centred on the hub");
  rule(ss.every((s, i) => s.x === ss[0].x && (!i || s.z < ss[i - 1].z)) && ss[0].x - ss[0].w / 2 > Math.max(...foot.map(f => f[1])),
       "the sources stand in a column, in name order, down the grid's right edge");
  for (const k of ["n:install", "n:approvals"]) {
    rule(N[k].z === hub.z && Math.abs(N[k].x - hub.x) > hub.w / 2, `${k} stands beside the hub`);
  }
  const want = [...r.network.windows.map(w => ["n:server", w]), ["n:server", "n:install"], ["n:server", "n:approvals"],
                ...r.network.sources.map(s => [s, "n:server"]), ...r.projects.map(p => ["n:server", p.id]),
                ...r.network.stale.map(a => ["n:install", a])];
  rule(J(R.links.map(k => J(k)).sort()) === J(want.map(k => J(k)).sort()), `the links: ${J(R.links)}`);
  rule(!R.links.some(k => k.includes("n:server") && k.some(id => id.startsWith("a:"))), "no hub-agent link");
  rule(broken(r, R).length === 0, `the grid's rules: ${J(broken(r, R))}`);
  got.rules = rules;
  return got;
}"""


@pytest.mark.browser
def test_the_layout_places_the_fleet_by_its_names_and_structure_alone(browser, fleet_home):
    server, token, port = _serve()
    page = None
    try:
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/map?t={token}", wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.FleetMap", timeout=15000)
        got = page.evaluate(CASES)

        det = got["determinism"]
        placed = json.loads(det["first"])
        assert len(placed["nodes"]) == 7 * 12 + 9 and len(placed["lanes"]) == 7 * 9, placed
        assert det["again"] == det["first"], "the same outline gave two layouts"
        assert det["reversed"] == det["first"], "reversing the outline's arrays moved something"
        assert det["rotated"] == det["first"], "rotating the outline's arrays moved something"
        assert det["untouched"], "layout() changed the outline it was given"
        assert got["extra"] == det["first"], "a key the outline does not define moved something"

        assert got["grid"]["count"] == 0, got["grid"]
        edges = got["edges"]
        assert edges["empty"] == edges["missing"] == json.dumps(
            {"nodes": {}, "lanes": [], "links": [], "bounds": {"minX": 0, "maxX": 0, "minZ": 0, "maxZ": 0}},
            separators=(",", ":")), edges
        assert edges["lone"] == [] and edges["net"] == [], edges

        for case in got["grow"]:
            slug = case["project"][2:]
            assert case["outside"] == [], case
            assert case["lanes"] and case["links"], case
            assert case["added"] == [[f"b:{slug}:aaa-first", case["project"]]], case
            assert case["inside"] > 0, case          # its own lanes re-sorted: the worktrees on them moved

        for case in got["move"]:
            assert case["moved"] == ["a:p01-a", "c:p01-a"], case
            assert case["lanes"] and case["links"], case

        stale = got["stale"]
        assert stale["added"] == [["n:install", "a:p02-d"]] and stale["grew"] == 1 and stale["kept"], stale
        assert stale["moved"] == [] and stale["lanes"] and stale["bounds"], stale

        assert got["rules"] == [], got["rules"]
        assert not errors, errors
    finally:
        if page is not None:
            page.close()
        _stop(server)
