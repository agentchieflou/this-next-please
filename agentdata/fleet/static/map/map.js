/* /map (#405): the fleet as an accessible tree -- the map's text twin and its whole plain look.

   A classic script like `settings.js`, loaded after `common.js`, whose token, `q`, `post`,
   `pageUrl`, `patchList` and setters it uses and nothing else. It reads `GET /api/map` once
   (docs/fleet-map.md §The graph) and draws it as a WAI-ARIA tree: projects, their checkouts
   (worktrees marked) and each checkout's agent, then the project's branches, then the network.
   The words are the graph's own `says`; the page adds no sentence of its own but the two group
   names. The scene (#409) is drawn from this tree later. It stays live (#406): its own stream
   from the graph's cursor, a throttled refetch, a live dot, and deleted branches kept as words.

   The render contract holds here as on the desk: every write goes through the setters, so a draw
   with nothing new to say makes zero DOM mutations, and `aria-expanded` is written only when an
   item is created -- a redraw never undoes what the operator opened or closed. That choice lives
   in the DOM, in memory, and is not persisted. Nothing on /map ever removes `ink-off`. */

"use strict";

var mapTree = document.getElementById("maptree");
var mapSays = document.getElementById("mapsays");
var mapBack = document.getElementById("mapback");
var mapLink = document.getElementById("maplink");
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
      var gone = (mapLanes[p.name] || { gone: [] }).gone.map(function (l) {
        return { id: l.id, say: l.name + " \u00b7 deleted", cls: "gone" };
      });
      kids.push({ id: "bs:" + p.name, say: p.branches_says, cls: "",
                  kids: (p.branches || []).map(mapBranch).concat(gone) });
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

/* Deleted branches (#406). A branch the previous graph had and this one lacks keeps its item, as
   `gone` and *<name> · deleted*, so the scene (#413 strikes its lane) never shows a fact the words
   lack. It stays until a later graph changes that project's branch list again. This is the only
   thing the tree carries from one graph to the next; it lives in memory and is not persisted. */
var mapLanes = {};

function mapKeepGone(graph) {
  var next = {};
  ((graph && graph.projects) || []).forEach(function (p) {
    if (!p.branches_says) return;
    var head = "b:" + p.name + ":";
    var lanes = (p.branches || []).map(function (b) {
      return { id: b.id, name: b.name || String(b.id).slice(head.length) };
    });
    var ids = lanes.map(function (l) { return l.id; });
    var was = mapLanes[p.name];
    next[p.name] = {
      sig: ids.join("\n"), lanes: lanes,
      gone: !was ? [] : was.sig === ids.join("\n") ? was.gone
        : was.lanes.filter(function (l) { return ids.indexOf(l.id) < 0; })
    };
  });
  mapLanes = next;
}

function drawMapTree(root, graph) {
  mapKeepGone(graph);
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

var mapState = { graph: null, paused: false, cursor: null, frames: 0, live: "", themes: 0,
                 source: null, timer: null };
var mapReady;
var mapReadyPromise = new Promise(function (resolve) { mapReady = resolve; });

function mapShow(graph) {
  mapState.graph = graph;
  drawMapTree(mapTree, graph);
  text(mapSays, graph && graph.says);
  mapReady();
}

function mapTheme(t) {
  if (!t) return;
  applyTheme(t.css, t.theme);
  applySkin(t.skin);
}

/* An answer is kept only when it is newer than the one drawn: the same `run` and a larger `n`, or
   a new `run` (a restarted server). An `as_of` of null (an empty fleet) is always taken. */
function mapNewer(next, now) {
  var a = next && next.as_of, b = now && now.as_of;
  if (!a || !b) return true;
  return a.run !== b.run || a.n > b.n;
}

/* One `/api/map`. Its theme is not painted when a `theme` frame arrived while it was in flight:
   that frame is newer than the answer. */
function mapFetch() {
  var asked = mapState.themes;
  return fetch(q("/api/map")).then(function (r) { return r.json(); }).then(function (graph) {
    if (!mapNewer(graph, mapState.graph)) return;
    if (asked === mapState.themes) mapTheme(graph && graph.theme);
    if (graph && typeof graph.cursor === "string") mapState.cursor = graph.cursor;
    if (!mapState.paused) mapShow(graph);
  });
}

/* A throttle, like the desk's `refreshSoon`: armed by the first frame and never pushed back by
   later ones, so a busy fleet still refetches every 400 ms (a trailing debounce would never fire
   while agents stream). Nothing is refetched while a caller's graph holds the tree. */
function mapSoon() {
  if (mapState.timer || mapState.paused) return;
  mapState.timer = setTimeout(function () {
    mapState.timer = null;
    if (!mapState.paused) mapFetch().catch(function () {});
  }, 400);
}

function mapLive(state) {
  mapState.live = state;
  setClass(mapLink, state === "live" ? "dot live" : "dot lost");
  text(mapLink, state);
}

/* The map's own stream, from the graph's cursor so it replays nothing already drawn, and with
   `notify=0` (#356) so it never takes the desk's notifications. */
function mapConnect() {
  if (mapState.source) mapState.source.close();
  var params = { since: mapState.cursor || "", w: PARAMS.get("w") || "main", page: "map",
                 notify: "0" };
  if (PARAMS.get("shell")) params.shell = PARAMS.get("shell");
  var source = mapState.source = new EventSource(q("/api/events", params));
  source.addEventListener("agent", function () { mapState.frames++; mapSoon(); });
  source.addEventListener("polls", mapSoon);
  source.addEventListener("desk", mapSoon);
  source.addEventListener("theme", function (m) {
    mapState.themes++;
    try { mapTheme(JSON.parse(m.data)); } catch (err) {}
  });
  source.addEventListener("tick", function () { mapLive("live"); });
  source.onopen = function () { mapLive("live"); };
  source.onerror = function () {
    mapLive("reconnecting");
    source.close();
    if (mapState.source !== source) return;
    mapState.source = null;
    // What was drawn in between cannot be trusted: re-read it, then resume from its cursor.
    setTimeout(function () {
      var again = function () { if (!mapState.source) mapConnect(); };
      (mapState.paused ? Promise.resolve() : mapFetch()).then(again, again);
    }, 2000);
  };
}

mapFetch().then(mapConnect, function () {
  if (!mapState.paused) mapShow({ says: "the map could not be read; reload to try again" });
});

/* What a test and #409's scene hold on to. `draw` feeds the tree a graph of the caller's and
   pauses the page's own drawing, so a refetch never overwrites it. `stream` is the live loop's
   count of `agent` frames and its state (`live`, `reconnecting`, or "" before it opens). */
window.FleetMap = Object.freeze({
  ready: mapReadyPromise,
  draw: function (graph) {
    mapState.paused = true;
    mapShow(graph);
  },
  get graph() { return mapState.graph; },
  get paused() { return mapState.paused; },
  get stream() { return { frames: mapState.frames, state: mapState.live }; },
  get scene() { return null; }
});
