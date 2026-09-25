/* /map (#405): the fleet as an accessible tree -- the map's text twin and its whole plain look.

   A classic script like `settings.js`, loaded after `common.js`, whose token, `q`, `post`,
   `pageUrl`, `patchList` and setters it uses and nothing else. It reads `GET /api/map` once
   (docs/fleet-map.md §The graph) and draws it as a WAI-ARIA tree: projects, their checkouts
   (worktrees marked) and each checkout's agent, then the project's branches, then the network.
   The words are the graph's own `says`; the page adds no sentence of its own but the two group
   names. The scene (#409) is drawn from this tree later, and #406 keeps it live.

   The render contract holds here as on the desk: every write goes through the setters, so a draw
   with nothing new to say makes zero DOM mutations, and `aria-expanded` is written only when an
   item is created -- a redraw never undoes what the operator opened or closed. That choice lives
   in the DOM, in memory, and is not persisted. Nothing on /map ever removes `ink-off`. */

"use strict";

var mapTree = document.getElementById("maptree");
var mapSays = document.getElementById("mapsays");
var mapBack = document.getElementById("mapback");
attr(mapBack, "href", pageUrl("/"));

/* The item keeps a `ul` for the ids that hold others; everything else is a leaf. Decided by the
   id's kind, never by whether it has children today, so an item never has to change its shape. */
var MAP_BRANCHING = /^(p|c|bs):|^n:network$/;

function mapWord(value) {
  var s = String(value == null ? "" : value).toLowerCase();
  return /^[a-z0-9][a-z0-9_-]*$/.test(s) ? s : "";
}

function mapClasses(pairs) {
  return pairs.filter(function (p) { return p[1]; }).map(function (p) { return p[0]; }).join(" ");
}

function mapAgent(a) {
  return {
    id: a.id, say: a.says,
    cls: mapClasses([["kind-" + mapWord(a.kind), mapWord(a.kind)],
                     ["state-" + mapWord(a.state), mapWord(a.state)],
                     ["role-" + mapWord(a.role), mapWord(a.role)],
                     ["needs-human", a.needs_human], ["live", a.live], ["stale", a.stale]]),
    data: { subagents: String(a.subagents || 0) }
  };
}

function mapCheckout(c) {
  return {
    id: c.id, say: c.says,
    cls: mapClasses([["main", c.main], ["worktree", c.worktree_of || c.worktree_of_unregistered],
                     ["dirty", c.dirty]]),
    data: { name: c.repo, on: c.on || "" },
    kids: c.agent ? [mapAgent(c.agent)] : []
  };
}

function mapBranch(b) {
  return {
    id: b.id, say: b.says,
    cls: mapClasses([["unmerged", b.unmerged], ["is-current", (b.current_in || []).length],
                     ["carrying", b.carrying]])
  };
}

function mapNetwork(net) {
  var kids = [];
  function one(n, cls) { if (n && n.id) kids.push({ id: n.id, say: n.says, cls: cls || "" }); }
  one(net.server);
  (net.windows || []).forEach(function (w) { one(w, w.connected ? "connected" : ""); });
  (net.sources || []).forEach(function (s) {
    one(s, (s.cells || []).some(function (c) { return c && c.ok === false; }) ? "grey" : "");
  });
  one(net.approvals, net.approvals && net.approvals.pending > 0 ? "pending" : "");
  one(net.install);
  return { id: "n:network", say: net.says, cls: "", kids: kids };
}

/* The graph as the tree's rows: `{id, say, cls, data, kids}`, one level per `patchList`. */
function mapRows(graph) {
  var g = graph || {};
  var rows = (g.projects || []).map(function (p) {
    var kids = (g.checkouts || []).filter(function (c) { return "p:" + c.project === p.id; })
      .map(mapCheckout);
    if (p.branches_says) {
      kids.push({ id: "bs:" + p.name, say: p.branches_says, cls: "",
                  kids: (p.branches || []).map(mapBranch) });
    }
    return { id: p.id, say: p.says, cls: "", data: { name: p.name, "default": p["default"] || "" },
             kids: kids };
  });
  if (g.network) rows.push(mapNetwork(g.network));
  return rows;
}

function mapCreate(row) {
  var branching = MAP_BRANCHING.test(row.id);
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById(branching ? "map-item" : "map-leaf"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  li.tabIndex = -1;
  // The one place `aria-expanded` is written by a draw: `bs:` starts closed, the rest open.
  if (branching) li.setAttribute("aria-expanded", row.id.indexOf("bs:") === 0 ? "false" : "true");
  return li;
}

function mapUpdate(li, row) {
  setData(li, "node", row.id);
  text(li.querySelector(".say"), row.say);
  setClass(li, row.cls || "");
  var data = row.data || {};
  ["name", "on", "default", "subagents"].forEach(function (k) {
    if (k in data) setData(li, k, data[k]); else attr(li, "data-" + k, null);
  });
  var group = li.querySelector(":scope > ul");
  if (group) mapLevel(group, row.kids || []);
}

function mapLevel(ul, rows) {
  patchList(ul, rows, function (r) { return r.id; }, mapCreate, mapUpdate);
}

/* The item Tab lands on: the last one the operator reached, else the first. */
var mapCurrent = null;

function mapItems() {
  return Array.prototype.filter.call(mapTree.querySelectorAll('[role="treeitem"]'), function (li) {
    for (var up = li.parentElement.closest('[role="treeitem"]'); up;
         up = up.parentElement.closest('[role="treeitem"]')) {
      if (up.getAttribute("aria-expanded") === "false") return false;
    }
    return true;
  });
}

function mapRove() {
  var items = mapItems();
  if (!mapCurrent || items.indexOf(mapCurrent) < 0) mapCurrent = items[0] || null;
  Array.prototype.forEach.call(mapTree.querySelectorAll('[role="treeitem"]'), function (li) {
    tabbable(li, li === mapCurrent ? 0 : -1);
  });
}

function drawMapTree(root, graph) {
  mapLevel(root, mapRows(graph));
  mapRove();
}

function mapGo(li) {
  if (!li) return;
  mapCurrent = li;
  mapRove();
  li.focus();
}

function mapExpand(li, open) {
  if (!li.hasAttribute("aria-expanded")) return;
  attr(li, "aria-expanded", open ? "true" : "false");
  mapRove();
}

function mapOpen(li) {
  var id = li.dataset.node || "";
  if (!/^[ca]:/.test(id)) return;
  post("window", { w: PARAMS.get("w") || "main", open: id.slice(2) }).then(function () {
    location.href = pageUrl("/");
  });
}

mapTree.addEventListener("keydown", function (e) {
  var li = /** @type {HTMLElement} */ (e.target).closest('[role="treeitem"]');
  if (!li) return;
  var items = mapItems();
  var i = items.indexOf(li);
  var open = li.getAttribute("aria-expanded");
  var handled = true;
  if (e.key === "ArrowDown") mapGo(items[i + 1]);
  else if (e.key === "ArrowUp") mapGo(items[i - 1]);
  else if (e.key === "Home") mapGo(items[0]);
  else if (e.key === "End") mapGo(items[items.length - 1]);
  else if (e.key === "ArrowRight") {
    if (open === "false") mapExpand(li, true);
    else if (open === "true") mapGo(li.querySelector(':scope > ul > [role="treeitem"]'));
  } else if (e.key === "ArrowLeft") {
    if (open === "true") mapExpand(li, false);
    else mapGo(li.parentElement.closest('[role="treeitem"]'));
  } else if (e.key === "Enter") mapOpen(li);
  else handled = false;
  if (handled) e.preventDefault();
});

mapTree.addEventListener("click", function (e) {
  var li = /** @type {HTMLElement} */ (e.target).closest('[role="treeitem"]');
  if (!li) return;
  if (/** @type {HTMLElement} */ (e.target).closest(".say") && li.hasAttribute("aria-expanded")) {
    mapExpand(li, li.getAttribute("aria-expanded") === "false");
  }
  mapGo(li);
});

/* ---------------------------------------------------------------------------- load and handle */

var mapState = { graph: null, paused: false };
var mapReady;
var mapReadyPromise = new Promise(function (resolve) { mapReady = resolve; });

function mapShow(graph) {
  mapState.graph = graph;
  drawMapTree(mapTree, graph);
  text(mapSays, graph && graph.says);
  mapReady();
}

fetch(q("/api/map")).then(function (r) { return r.json(); }).then(function (graph) {
  var t = graph && graph.theme;
  if (t) {
    applyTheme(t.css, t.theme);
    applySkin(t.skin);
  }
  if (!mapState.paused) mapShow(graph);
}).catch(function () {
  if (!mapState.paused) mapShow({ says: "the map could not be read; reload to try again" });
});

/* What a test, #406's refetch and #409's scene hold on to. `draw` feeds the tree a graph of the
   caller's and pauses the page's own drawing, so a refetch never overwrites it. */
window.FleetMap = Object.freeze({
  ready: mapReadyPromise,
  draw: function (graph) {
    mapState.paused = true;
    mapShow(graph);
  },
  get graph() { return mapState.graph; },
  get paused() { return mapState.paused; },
  get scene() { return null; }
});
