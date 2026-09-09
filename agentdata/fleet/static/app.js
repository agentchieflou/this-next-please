/* The multi-viewer's client. No framework and no build step on purpose: this file has to load
   inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
   fetched from the internet simply does not arrive.

   The page is a view. It never decides anything -- every state comes from /api/fleet and every
   button POSTs to the same function the CLI verb calls. */

"use strict";

var PARAMS = new URLSearchParams(location.search);
var TOKEN = PARAMS.get("t") || "";
var tiles = new Map();          // repo name -> {el, seq}
var focused = null;
var pendingRefresh = null;
var source = null;

/* #133: three arrangements of this one page, chosen by the URL, because a second HTML file is a
   second thing to keep in step and the friction being fixed is *tabs*. `grid` is every tile on one
   screen; `roles` is three windows -- board, agents, verify -- that agree on a selected project
   through the SSE stream; `screens` pins one project per monitor. `ad-fleet serve --layout` puts
   the parameter on the URL it prints, so the operator never has to type one. */
var LAYOUTS = ["grid", "roles", "screens"];
var VIEWS = ["board", "agents", "verify"];
var rawLayout = PARAMS.get("layout");
var unknownLayout = (rawLayout && LAYOUTS.indexOf(rawLayout) < 0) ? rawLayout : null;
var LAYOUT = unknownLayout ? "grid" : (rawLayout || "grid");
var VIEW = VIEWS.indexOf(PARAMS.get("view")) >= 0 ? PARAMS.get("view")
                                                  : (LAYOUT === "roles" ? "agents" : "");
var SCREEN = Math.max(0, Math.min(9, Number(PARAMS.get("screen")) || 0));

var desk = { projects: {}, offers: {}, unsorted: [], not_offered: [], folders: [],
             desk: { selected: "", screens: [] } };
var pendingDesk = null;
var needsOnly = false;

function q(path, params) {
  var u = new URL(path, location.origin);
  u.searchParams.set("t", TOKEN);
  Object.keys(params || {}).forEach(function (k) { u.searchParams.set(k, params[k]); });
  return u.toString();
}

function post(action, body) {
  return fetch(q("/api/" + action), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  }).then(function (r) { return r.json(); });
}

function text(el, value) { el.textContent = value == null ? "" : String(value); }

function age(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return seconds + "s";
  if (seconds < 5400) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

/* The age that rides inside the state chip. "done" is not information; "done · 2d" is -- and the
   bucket labels this replaced ("today", "> 2d") could not tell a run that ended a minute ago from
   one that ended at breakfast. Anything past a day is marked stale as well as dated, because a
   colour alone is not a signal on a bad monitor at arm's length. */
function ageChip(seconds) {
  if (seconds == null || seconds < 0) return { text: "", stale: false };
  if (seconds < 90) return { text: seconds + "s", stale: false };
  if (seconds < 5400) return { text: Math.floor(seconds / 60) + "m", stale: false };
  if (seconds < 86400) return { text: Math.floor(seconds / 3600) + "h", stale: false };
  return { text: Math.floor(seconds / 86400) + "d", stale: true };
}

/* --------------------------------------------------------------------------- drawing one tile */

function line(ev) {
  var d = ev.data || {};
  switch (ev.kind) {
    case "assistant_text": return d.text || "";
    case "tool_call": return (d.tool || "tool") + " " + JSON.stringify(d.arguments || {}).slice(0, 160);
    case "tool_result": return d.ok ? "ok" : (d.message || d.error || "failed");
    case "denied": return "refused: " + (d.message || "a tool it may not run");
    case "friction": return "stopped: " + (d.unblock || d.file || "");
    case "phase_changed": return (d.from || "?") + " → " + (d.to || "?");
    case "question_opened": return d.question || "";
    case "needs_approval": return "waiting for you: " + (d.summary || d.kind || "");
    case "approval_resolved": return (d.decision || "") + " by " + (d.by || "you");
    case "cost": return d.premium_requests + " premium requests";
    case "exited": return "exit " + d.exit_code;
    case "error": return "exit " + d.exit_code;
    case "started": return "launched: " + (d.prompt || "");
    /* #131 and #132 put the *project's* changes on the same stream as the agent's, so the
       transcript is one narrative rather than two panes the operator has to interleave. */
    case "project.ticket_changed": return (d.key || "") + " is " + (d.status || "") +
                                          (d.assignee ? " · " + d.assignee : "");
    case "project.refresh_finished": return "refresh " + (d.status || "") + " " + (d.end || "");
    case "project.pr_merged": return "PR merged: " + (d.url || "");
    case "inbox.attached": return (d.attached ? "attached " : "already there: ") +
                                  (d.name || "") + " → " + (d.dir || "");
    case "pr_open": return d.url || "";
    case "artifact": return (d.artifact && d.artifact.path) || "";
    case "session_id": return "";
    default: return JSON.stringify(d).slice(0, 160);
  }
}

var SHOWN = {
  started: 1, assistant_text: 1, tool_call: 1, tool_result: 1, denied: 1, friction: 1,
  phase_changed: 1, question_opened: 1, needs_approval: 1, approval_resolved: 1,
  exited: 1, error: 1, pr_open: 1, artifact: 1,
  "project.ticket_changed": 1, "project.refresh_finished": 1, "project.pr_merged": 1,
  "inbox.attached": 1
};

function append(el, ev) {
  if (!SHOWN[ev.kind]) return;
  var body = line(ev);
  if (!body) return;
  var list = el.querySelector(".transcript");
  var li = document.createElement("li");
  li.className = ev.kind;
  var k = document.createElement("span");
  k.className = "k";
  text(k, ev.kind.replace(/_/g, " "));
  var v = document.createElement("span");
  v.className = "v";
  text(v, body);                                  // textContent, never markup: this is agent output
  li.appendChild(k);
  li.appendChild(v);
  list.appendChild(li);
  while (list.children.length > 200) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

function makeTile(row, index) {
  var el = document.getElementById("tile").content.firstElementChild.cloneNode(true);
  text(el.querySelector(".n"), index + 1);
  var repoEl = el.querySelector(".repo");
  text(repoEl, row.repo);
  repoEl.title = row.repo;
  el.dataset.repo = row.repo;

  el.querySelector(".repo").addEventListener("click", function () { focus(row.repo); });
  el.addEventListener("dblclick", function () { focus(row.repo); });
  // Clicking anywhere on a tile *selects* the project for every window on this server (#133 layout
  // B), which is what makes the left monitor drive the centre one. Blowing a tile up is still the
  // repo name or a double click: one gesture per meaning.
  el.addEventListener("click", function (e) {
    // Clicking a tile selects the project for every window on this server -- which is what makes
    // the left monitor drive the centre one. Pressing Send, or clicking into the reply box, is not
    // that gesture: it re-pointed three other screens as a side effect of typing.
    if (e.target.closest("button, input, select, textarea, a, details, summary")) return;
    choose(row.repo);
  });

  /* Drag to reorder, from the header only. A tile that is draggable edge to edge cannot have its
     transcript text selected -- every attempt to copy an error message starts a drag instead --
     and it offers no affordance for the gesture. The header carries `draggable` and the grip
     says so (HIG *Drag and drop*). Tickets dropped from the board still land on the whole tile. */
  var head = el.querySelector(".head");
  head.addEventListener("dragstart", function (e) {
    if (e.target.closest("button, input, select")) { e.preventDefault(); return; }
    e.dataTransfer.setData("application/x-agentdata-tile", row.repo);
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("is-dragging");
  });
  var clearDrop = function () {
    el.classList.remove("is-dragging");
    document.querySelectorAll(".tile").forEach(function (t) {
      t.classList.remove("drop-before", "drop-after", "drop-target");
    });
  };
  head.addEventListener("dragend", clearDrop);
  // Esc cancels a drag in flight and leaves the order alone (HIG *Drag and drop*).
  el.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && el.classList.contains("is-dragging")) clearDrop();
  });

  el.addEventListener("dragover", function (e) {
    e.preventDefault();
    var isTileDrag = Array.from(e.dataTransfer.types || []).indexOf("application/x-agentdata-tile") >= 0;
    if (isTileDrag) {
      e.dataTransfer.dropEffect = "move";
      var rect = el.getBoundingClientRect();
      var before = (e.clientX - rect.left) < (rect.width / 2);
      el.classList.toggle("drop-before", before);
      el.classList.toggle("drop-after", !before);
    } else {
      e.dataTransfer.dropEffect = "copy";
      el.classList.add("drop-target");
    }
  });

  el.addEventListener("dragleave", function () {
    el.classList.remove("drop-target", "drop-before", "drop-after");
  });

  el.addEventListener("drop", function (e) {
    e.preventDefault();
    var isTileDrag = el.classList.contains("drop-before") || el.classList.contains("drop-after");
    var droppedRepo = e.dataTransfer.getData("application/x-agentdata-tile");
    var dropBefore = el.classList.contains("drop-before");
    el.classList.remove("drop-target", "drop-before", "drop-after");

    if (droppedRepo && droppedRepo !== row.repo) {
      var order = getEffectiveOrder();
      var fromIdx = order.indexOf(droppedRepo);
      if (fromIdx >= 0) order.splice(fromIdx, 1);
      var toIdx = order.indexOf(row.repo);
      if (!dropBefore) toIdx += 1;
      order.splice(toIdx, 0, droppedRepo);
      post("arrange", { layout: LAYOUT, order: order }).then(function (r) {
        if (r && r.ok) mergeDesk(r);
        reorderDomTiles();
      });
      reorderDomTiles();
      return;
    }

    var key = (e.dataTransfer.getData("text/plain") || "").trim();
    if (key) dispatch(key, row.repo);
  });

  /* Every drag gesture has a keyboard equivalent, and the footer key map lists all four. */
  el.addEventListener("keydown", function (e) {
    if (!e.altKey) return;
    if (e.key === "ArrowLeft") { moveTile(row.repo, -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { moveTile(row.repo, 1); e.preventDefault(); }
    else if (e.key === "Home") { toggleTilePin(row.repo); e.preventDefault(); }
    else if (e.key === "Enter") { toggleTileSize(row.repo); e.preventDefault(); }
  });

  var pinBtn = el.querySelector(".pintoggle");
  if (pinBtn) {
    pinBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTilePin(row.repo);
    });
  }

  var sizeBtn = el.querySelector(".sizetoggle");
  if (sizeBtn) {
    sizeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTileSize(row.repo);
    });
  }

  var say = el.querySelector(".say");
  el.querySelector(".send").addEventListener("click", function () {
    action(el, "send", { repo: row.repo, message: say.value }).then(function () { say.value = ""; });
  });
  say.addEventListener("keydown", function (e) {
    if (e.key === "Enter") el.querySelector(".send").click();
  });
  el.querySelector(".start").addEventListener("click", function () {
    action(el, "start", { repo: row.repo, ticket: say.value.trim() || null });
  });
  el.querySelector(".stop").addEventListener("click", function () {
    action(el, "stop", { repo: row.repo });
  });
  el.querySelector(".approve").addEventListener("click", function () {
    action(el, "approve", { id: el.dataset.approval, reason: el.querySelector(".reason").value });
  });
  el.querySelector(".deny").addEventListener("click", function () {
    var reason = el.querySelector(".reason").value.trim();
    if (!reason) { return fail(el, "a denial needs a reason: the agent quotes it and then stops"); }
    action(el, "deny", { id: el.dataset.approval, reason: reason });
  });
  return el;
}

function fail(el, message) {
  var p = el.querySelector(".err");
  text(p, message);
  p.hidden = !message;
}

function action(el, what, body) {
  fail(el, "");
  return post(what, body).then(function (r) {
    if (!r.ok) fail(el, r.error + (r.hint ? " — " + r.hint : ""));
    refresh();
    return r;
  }).catch(function (e) { fail(el, String(e)); });
}

function drawTile(el, row, approvals) {
  /* Three things have to agree here or the tile lies: the chip, the sentence under it, and the
     age. The server decides which agents are quiet enough to be called unsupervised (it is the
     only side that knows whether a process holds the checkout), and it sends the sentence ONLY
     for those -- so a tile that says "needs you" never also says "nothing is supervised". */
  var isSupervised = row.supervised !== false;
  var cold = !isSupervised && !!row.not_supervised_sentence;
  var displayState = cold ? "idle" : row.state;
  el.className = "tile state-" + displayState + (el.classList.contains("is-focused") ? " is-focused" : "");
  // The left edge is the project's accent -- which project, never what state (#150).
  if (row.accent) el.style.borderLeftColor = row.accent;
  // `needs-human` is the class focus mode filters on, and it comes from #94's fold rather than from
  // anything this page works out for itself: the chip, the toast and the filter must agree.
  el.classList.toggle("needs-human", !!row.needs_human);
  el.tabIndex = 0;
  // Every state carries its own age, in the chip, because a verdict with no date is the bug.
  var ac = ageChip(row.last_event_age_s);
  var chip = el.querySelector(".chip");
  chip.className = "chip " + displayState + (ac.stale ? " stale" : "");
  while (chip.firstChild) chip.removeChild(chip.firstChild);
  chip.appendChild(document.createTextNode(displayState.replace(/_/g, " ")));
  if (ac.text) {
    var span = document.createElement("span");
    span.className = "chipage";
    text(span, " · " + ac.text);
    chip.appendChild(span);
  }
  chip.title = "state from the fold" + (ac.text ? ", last event " + ac.text + " ago" : "");
  text(el.querySelector(".ticket"), row.ticket || row.jira_project || "");

  text(el.querySelector(".why"), cold ? row.not_supervised_sentence : (row.why || ""));

  // Which run this transcript belongs to. Without it, a two-day-old run reads as live.
  var run = row.run || {};
  var runline = el.querySelector(".runline");
  if (runline) {
    var bits = [];
    if (run.n) bits.push("run " + run.n);
    if (run.started) bits.push("started " + String(run.started).slice(11, 16));
    if (run.resumed) bits.push("resumed");
    if (run.session) bits.push("session " + String(run.session).slice(0, 8));
    if (run.events_n) bits.push(run.events_n + " events");
    // The era, last, because it is the qualifier: which run, then whether it is still this one.
    if (!run.n) bits = ["no run yet"];
    else if (isSupervised) bits.push("live");
    else if (!run.since_start) bits.push("before this session");
    else bits.push("ended");
    text(runline, bits.join(" · "));
    runline.title = bits.join(" · ");          // the line truncates; the whole of it stays reachable
    runline.classList.toggle("cold", cold);
  }

  var earlierEl = el.querySelector(".earlier");
  if (earlierEl) {
    var earlierRuns = row.earlier || [];
    if (earlierRuns.length > 0) {
      earlierEl.hidden = false;
      text(earlierEl.querySelector(".earlierhead"), "earlier runs (" + earlierRuns.length + ")");
      var listEl = earlierEl.querySelector(".earlierlist");
      while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
      earlierRuns.forEach(function (r) {
        var li = document.createElement("li");
        text(li, "Run #" + r.n + ": " + (r.ticket ? r.ticket + " · " : "") + r.state +
                 " (" + (r.started ? r.started.slice(11, 16) : "") +
                 (r.ended ? " – " + r.ended.slice(11, 16) : "") + ")");
        listEl.appendChild(li);
      });
    } else {
      earlierEl.hidden = true;
    }
  }

  var mine = approvals.filter(function (a) { return a.repo === row.repo; })[0];
  var card = el.querySelector(".approval");
  card.hidden = !mine;
  if (mine) {
    el.dataset.approval = mine.id;
    text(el.querySelector(".kind"), mine.kind + "  ·  " + age(mine.waiting_s));
    text(el.querySelector(".summary"), mine.summary || "");
    text(el.querySelector(".payload"), JSON.stringify(mine.payload || {}, null, 2));
  }
  drawCells(el, row.polls || {});
}

/* -------------------------------------------------------------------------------- the whole page */

function refresh() {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = fetch(q("/api/fleet")).then(function (r) { return r.json(); }).then(function (data) {
    pendingRefresh = null;
    if (!data.ok) return;
    var grid = document.getElementById("grid");
    document.getElementById("empty").hidden = data.repos.length > 0;
    data.repos.forEach(function (row, i) {
      var entry = tiles.get(row.repo);
      if (!entry) {
        var el = makeTile(row, i);
        grid.appendChild(el);
        entry = { el: el, seq: 0 };
        tiles.set(row.repo, entry);
        (row.recent || []).forEach(function (ev) { append(el, ev); entry.seq = ev.seq; });
      }
      drawTile(entry.el, row, data.approvals || []);
    });
    tiles.forEach(function (entry, name) {
      if (!data.repos.some(function (r) { return r.repo === name; })) {
        entry.el.remove();
        tiles.delete(name);
      }
    });
    var need = data.repos.filter(function (r) { return r.needs_human; }).length;
    text(document.getElementById("counts"),
         data.repos.length + " agents" + (need ? "  ·  " + need + " need you" : ""));
    if (data.desk) desk.desk = data.desk;
    if (data.theme) {
      applyTheme(data.theme.css, data.theme.theme);
      applySkin(data.theme.skin);
      reflectTheme(data.theme);
    }
    place();
    title(need);
    return data;
  }).catch(function () { pendingRefresh = null; });
  return pendingRefresh;
}

var refreshSoon = (function () {
  var timer = null;
  return function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; refresh(); }, 400);
  };
})();

function cursors() {
  var parts = [];
  tiles.forEach(function (entry, name) { parts.push(name + ":" + entry.seq); });
  return parts.join(",");
}

function connect() {
  if (source) source.close();
  var link = document.getElementById("link");
  source = new EventSource(q("/api/events", { since: cursors() }));
  source.addEventListener("agent", function (m) {
    var ev = JSON.parse(m.data);
    var entry = tiles.get(ev.repo);
    if (!entry) return refreshSoon();
    entry.seq = Math.max(entry.seq, ev.seq);
    append(entry.el, ev);
    refreshSoon();
  });
  source.addEventListener("notify", function (m) { arrived(JSON.parse(m.data)); });
  // The shared selection (#133). Every window is sent the current one the moment it connects, so a
  // monitor that joined late never sits on a different project than the one beside it.
  source.addEventListener("desk", function (m) {
    desk.desk = JSON.parse(m.data);
    place();
    if (VIEW === "verify" || LAYOUT === "screens") deskSoon();
  });
  source.addEventListener("theme", function (m) {
    try {
      var d = JSON.parse(m.data);
      var select = document.getElementById("theme");
      if (select && d.theme) select.value = d.theme === "none" ? "" : d.theme;
      applyTheme(d.css, d.theme);
      applySkin(d.skin);
      reflectTheme(d);
      if (d.accents) {
        Object.keys(d.accents).forEach(function (repo) {
          if (tiles.has(repo)) {
            tiles.get(repo).el.style.borderTopColor = d.accents[repo];
          }
        });
      }
    } catch (err) {}
  });
  source.addEventListener("tick", function () {
    link.className = "dot live";
    text(link, "live");
  });
  source.onopen = function () { link.className = "dot live"; text(link, "live"); };
  source.onerror = function () {
    link.className = "dot lost";
    text(link, "reconnecting");
    // EventSource reconnects on its own, but the page must not trust what it drew in between.
    setTimeout(function () { refresh().then(connect); }, 2000);
  };
}

/* ------------------------------------------------------------------- focus mode and the keyboard */

function focus(name) {
  focused = name;
  document.body.classList.add("focused");
  document.getElementById("unfocus").hidden = false;
  tiles.forEach(function (entry, key) { entry.el.classList.toggle("is-focused", key === name); });
  unread.delete(name);                       // looking at it is what "read" means
  bell();
  drawer(false);
  if (location.hash !== "#tile=" + name) history.replaceState(null, "", "#tile=" + name);
}

function unfocus() {
  focused = null;
  document.body.classList.remove("focused");
  document.getElementById("unfocus").hidden = true;
  tiles.forEach(function (entry) { entry.el.classList.remove("is-focused"); });
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}

/* A toast launches `…/?t=…#tile=luna`, so the click lands on the agent that needs the operator
   rather than on "one of these four". Also fired on hashchange, because the window may already be
   open and the shell simply re-focuses it with a new hash. */
function followHash() {
  var m = /^#tile=(.+)$/.exec(location.hash || "");
  if (m && tiles.has(decodeURIComponent(m[1]))) focus(decodeURIComponent(m[1]));
}

window.addEventListener("hashchange", followHash);

document.getElementById("unfocus").addEventListener("click", unfocus);

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") { if (typing) document.activeElement.blur(); else unfocus(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[1-9]$/.test(e.key)) {
    // The number printed on a tile comes from the arrangement, so the key that focuses it must
    // too. Reading registry order here meant that the moment anything was moved or pinned, the
    // badge said 3 and pressing 3 focused something else.
    var name = getEffectiveOrder()[Number(e.key) - 1];
    if (name) focus(name);
    return;
  }
  if (e.key === "n") { section("drawer"); return; }
  if (e.key === "b") { section("board"); return; }
  if (e.key === "a") {
    var entry = focused ? tiles.get(focused) : null;
    if (entry && entry.el.dataset.approval && !entry.el.querySelector(".approval").hidden) {
      entry.el.querySelector(".approve").click();
    }
  }
});

/* ------------------------------------------------------------------------------------- theming */

function applyTheme(cssVars, themeName) {
  var root = document.documentElement;
  var tokens = ["--bg", "--text", "--panel", "--line", "--select", "--muted", "--accent",
                "--focus", "--running", "--waiting", "--human", "--done", "--idle"];
  if (cssVars && themeName && themeName !== "none") {
    tokens.forEach(function (k) {
      if (cssVars[k]) root.style.setProperty(k, cssVars[k]);
      else root.style.removeProperty(k);
    });
    root.setAttribute("data-theme", "custom");
  } else {
    tokens.forEach(function (k) { root.style.removeProperty(k); });
    root.removeAttribute("data-theme");
  }
}

function applySkin(skinName) {
  var link = document.head.querySelector("link[data-skin]");
  if (!skinName || skinName === "none") {
    if (link) link.remove();
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("data-skin", "true");
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  link.href = q("/static/skins/" + skinName + "/skin.css");
}

/* Two controls, two tiers, and the difference is the point (#150, #154).

   A PALETTE is colour only, so it is 1:1 with the terminal: the same hex reaches this page's custom
   properties and the project's prompt and tab, and choosing one here writes
   `~/.agentdata/config.json` -- the same file `ad-theme set` writes -- so every window on every
   screen and the terminal beside them move together. A SKIN is how the page is RENDERED, which a
   terminal cannot follow; it rides on a base palette and loads one extra stylesheet on demand.

   Both post to the server rather than to `localStorage`, because a desk is four windows and a
   choice kept in one browser's storage is four different desks. */
function loadThemes() {
  var themeSel = document.getElementById("theme");
  var skinSel = document.getElementById("skin");
  return fetch(q("/api/themes")).then(function (r) { return r.json(); }).then(function (data) {
    while (themeSel.options.length > 1) themeSel.remove(1);
    (data.themes || []).forEach(function (t) {
      if (t.name === "none") return;                 // "system" is already the first option
      var option = document.createElement("option");
      option.value = t.name;
      text(option, t.name);
      option.title = t.why || t.title || t.name;
      themeSel.appendChild(option);
    });
    themeSel.addEventListener("change", function () { post("theme", { theme: themeSel.value }); });

    while (skinSel.options.length > 1) skinSel.remove(1);
    (data.skins || []).forEach(function (k) {
      if (k.name === "none") return;
      var option = document.createElement("option");
      option.value = k.name;
      text(option, k.title || k.name);
      option.title = (k.why || "") + (k.base ? "  ·  palette: " + k.base : "");
      skinSel.appendChild(option);
    });
    skinSel.addEventListener("change", function () { post("theme", { skin: skinSel.value }); });
    reflectTheme(data.current || data.theme);
  }).catch(function () { /* themes are decoration; the page works without them */ });
}

/* One place that puts the server's answer into the two controls, so a change made in the terminal
   or in another window shows up here rather than leaving the picker saying something else. */
function reflectTheme(cur) {
  if (!cur) return;
  var themeSel = document.getElementById("theme");
  var skinSel = document.getElementById("skin");
  if (themeSel && cur.theme) themeSel.value = cur.theme;
  if (skinSel) skinSel.value = cur.skin || "none";
}

refresh().then(function () {
  connect();
  loadThemes();
  loadNotifications();
  loadDesk();
  followHash();
  if (LAYOUT === "roles" && VIEW === "board") boardPanel(true);
  if (LAYOUT === "screens" && !SCREEN) { boardPanel(true); trayPanel(true); }
});

// The desk half is answered on its own, slower clock: a catalogue read, a Downloads scandir and a
// `.agent/out/` stat per project is not something to do four times a second, and nothing on it is
// urgent -- what is urgent arrives on the stream.
setInterval(loadDesk, 15000);

/* ------------------------------------------------------------------------- notifications (#97) */

/* The chime is synthesised, not a bundled sound file. WebAudio is in every browser this page has
   to run in, it adds nothing to the payload and nothing to fetch, and a .wav shipped as package
   data is one more thing that can fail to install. Off by default: a sound the operator did not
   ask for is the fastest way to have every notification muted. */
function chime() {
  if (!chimeOn) return;
  try {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.09);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.32);
    osc.onended = function () { try { ctx.close(); } catch (e) { /* already closed */ } };
  } catch (e) { /* no audio device, or autoplay refused until the page is clicked */ }
}

var unread = new Map();          // repo -> count, cleared when that tile is focused
var chimeOn = false;

function bell() {
  var total = 0;
  unread.forEach(function (n) { total += n; });
  var button = document.getElementById("bell");
  text(document.getElementById("bellcount"), total);
  button.classList.toggle("unread", total > 0);
  tiles.forEach(function (entry, name) {
    var badge = entry.el.querySelector(".badge");
    var n = unread.get(name) || 0;
    badge.hidden = n === 0;
    text(badge, n);
  });
  return total;
}

function noteRow(item) {
  var li = document.createElement("li");
  li.className = item.severity || "info";
  var t = document.createElement("span");
  t.className = "t";
  text(t, item.title);
  var b = document.createElement("span");
  b.className = "b";
  text(b, item.body || "");
  var when = document.createElement("span");
  when.className = "when";
  text(when, String(item.at || "").slice(11, 19) + (item.toasted ? "  ·  toasted" : "") +
             (item.quiet ? "  ·  quiet hours" : ""));
  li.appendChild(t);
  li.appendChild(b);
  li.appendChild(when);
  li.addEventListener("click", function () { if (tiles.has(item.repo)) focus(item.repo); });
  return li;
}

function addNote(item, atTop) {
  var list = document.getElementById("notes");
  var row = noteRow(item);
  if (atTop && list.firstChild) list.insertBefore(row, list.firstChild);
  else list.appendChild(row);
  while (list.children.length > 50) list.removeChild(list.lastChild);
  document.getElementById("nonotes").hidden = list.children.length > 0;
}

function arrived(item) {
  unread.set(item.repo, (unread.get(item.repo) || 0) + 1);
  addNote(item, true);
  bell();
  refreshSoon();
  if (item.severity !== "info") chime();
}

function loadNotifications() {
  return fetch(q("/api/notifications", { limit: 50 })).then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok) return;
      var list = document.getElementById("notes");
      while (list.firstChild) list.removeChild(list.firstChild);
      (data.notifications || []).slice().reverse().forEach(function (i) { addNote(i, false); });
      text(document.getElementById("toaststatus"), "toast: " + (data.toast || "?"));
      document.getElementById("nonotes").hidden = list.children.length > 0;
    }).catch(function () { /* the drawer is a convenience; the tiles are the truth */ });
}

/* ---------------------------------------------------------------- the sidebar (#148)

   Five panels used to be five fixed overlays at the same screen edge: they covered the grid, they
   covered each other, and because `[hidden]` lost to their `display: flex` a "closed" one went on
   eating the clicks meant for the tiles underneath it. They are now five sections of ONE sidebar
   beside the grid, exactly one open at a time, with a tab strip that says which. Each panel keeps
   the function name the rest of this file already calls. */

var SECTIONS = ["board", "unsorted", "drawer", "found", "inspector"];
var lastSection = "board";

function syncSide() {
  var open = SECTIONS.filter(function (id) {
    var n = document.getElementById(id);
    return n && !n.hidden;
  });
  document.getElementById("side").hidden = open.length === 0;
  document.getElementById("sidetoggle").setAttribute("aria-pressed", String(open.length > 0));
  document.querySelectorAll(".side-tabs .segment").forEach(function (b) {
    var on = open.indexOf(b.dataset.section) >= 0;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  return open[0] || "";
}

/* `open` undefined toggles, true opens, false closes. Opening one closes the rest. */
function section(id, open) {
  var el = document.getElementById(id);
  if (!el) return false;
  var want = open === undefined ? el.hidden : !!open;
  SECTIONS.forEach(function (s) {
    var n = document.getElementById(s);
    if (n) n.hidden = !(s === id && want);
  });
  if (want) lastSection = id;
  syncSide();
  if (want) {
    if (id === "board") { loadBoard(false); loadHistory(); }
    if (id === "drawer") loadNotifications();
    if (id === "unsorted") loadDesk();
    if (id === "inspector") drawInspector(desk.desk.selected);
  }
  return want;
}

function closeSide() {
  SECTIONS.forEach(function (id) {
    var n = document.getElementById(id);
    if (n) n.hidden = true;
  });
  syncSide();
}

function drawer(open) { return section("drawer", open); }

document.getElementById("bell").addEventListener("click", function () { drawer(); });
document.getElementById("closedrawer").addEventListener("click", function () { drawer(false); });
document.getElementById("clearbell").addEventListener("click", function () {
  unread.clear();
  bell();
});
document.getElementById("chime").addEventListener("click", function () {
  chimeOn = !chimeOn;
  var button = document.getElementById("chime");
  button.setAttribute("aria-pressed", String(chimeOn));
  text(button, chimeOn ? "chime on" : "chime off");
  try { localStorage.setItem("fleet.chime", chimeOn ? "1" : "0"); } catch (e) { /* private window */ }
  if (chimeOn) chime();                      // and it plays once, so "on" is not taken on trust
});

try { chimeOn = localStorage.getItem("fleet.chime") === "1"; } catch (e) { chimeOn = false; }
document.getElementById("chime").setAttribute("aria-pressed", String(chimeOn));
text(document.getElementById("chime"), chimeOn ? "chime on" : "chime off");

/* --------------------------------------------------------------------------- the Jira board (#98) */

/* Dispatching a ticket should not mean copying a key out of a browser. The panel is a view of the
   operator's own JQL; a ticket goes to an agent by being dragged onto its tile, or by clicking the
   button on the row when the repository is unambiguous.

   The suggestion is the server's, from each repo's declared `jira_project`. Three answers, and the
   panel shows all three honestly: one repo (drag has an obvious home), several (pick one — guessing
   would eventually start the wrong checkout), none (the repo is not registered, which is a one-line
   fix worth naming rather than a silent blank). */

var board = [];

function statusClass(row) {
  return "st " + (row.category || "");
}

function ticketRow(row) {
  var li = document.createElement("li");
  li.draggable = true;
  li.dataset.key = row.key;

  var head = document.createElement("div");
  var key = document.createElement("span");
  key.className = "key";
  text(key, row.key);
  var st = document.createElement("span");
  st.className = statusClass(row);
  text(st, row.status);
  head.appendChild(key);
  head.appendChild(st);

  var sum = document.createElement("span");
  sum.className = "sum";
  text(sum, row.summary);

  var to = document.createElement("span");
  to.className = "to";
  var s = row.suggested || {};
  text(to, s.repo ? "→ " + s.repo : (s.hint || s.why || ""));
  head.appendChild(document.createTextNode(" "));

  li.appendChild(head);
  li.appendChild(sum);
  li.appendChild(to);

  (s.repo ? [s.repo] : (s.candidates || [])).forEach(function (name) {
    var go = document.createElement("button");
    go.className = "go";
    text(go, "start on " + name);
    go.addEventListener("click", function (e) {
      e.stopPropagation();
      dispatch(row.key, name);
    });
    li.appendChild(go);
  });

  li.addEventListener("dragstart", function (e) {
    li.classList.add("dragging");
    e.dataTransfer.setData("text/plain", row.key);
    e.dataTransfer.effectAllowed = "copy";
  });
  li.addEventListener("dragend", function () { li.classList.remove("dragging"); });
  return li;
}

function dispatch(key, repo) {
  var entry = tiles.get(repo);
  var el = entry ? entry.el : document.body;
  return action(el, "start", { repo: repo, ticket: key }).then(function (r) {
    if (r && r.ok) { boardPanel(false); focus(repo); }
    else if (r && !r.ok && /jira_project/.test(r.error || "")) {
      // The one refusal worth offering an override for in the page: the operator can see both
      // projects on screen and is better placed than the guard to say it is deliberate.
      if (confirm(r.error + "\n\nStart it anyway?")) {
        action(el, "start", { repo: repo, ticket: key, cross_project: true });
      }
    }
    return r;
  });
}

function drawBoard(rows) {
  var list = document.getElementById("tickets");
  var needle = (document.getElementById("boardsearch").value || "").toLowerCase();
  while (list.firstChild) list.removeChild(list.firstChild);
  var shown = rows.filter(function (r) {
    return !needle || (r.key + " " + r.summary + " " + r.status).toLowerCase().indexOf(needle) >= 0;
  });
  shown.forEach(function (r) { list.appendChild(ticketRow(r)); });
  document.getElementById("noboard").hidden = shown.length > 0;
}

function loadBoard(refresh) {
  var err = document.getElementById("boarderr");
  return fetch(q("/api/board", refresh ? { refresh: "1" } : {}))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      err.hidden = !!data.ok;
      if (!data.ok) {
        text(err, data.error + (data.hint ? " — " + data.hint : ""));
        return;
      }
      board = data.rows || [];
      text(document.getElementById("boardage"),
           data.cached ? "cached, " + age(data.age_s) + " old" : "from jira");
      drawBoard(board);
    }).catch(function (e) { err.hidden = false; text(err, String(e)); });
}

function loadHistory() {
  return fetch(q("/api/history", { since: "7d" })).then(function (r) { return r.json(); })
    .then(function (data) {
      var body = document.getElementById("runs");
      while (body.firstChild) body.removeChild(body.firstChild);
      (data.runs || []).slice().reverse().forEach(function (run) {
        var tr = document.createElement("tr");
        [[String(run.started).slice(5, 16), ""], [run.repo, ""], [run.ticket || "-", ""],
         [run.state, "state-" + run.state], [String(run.premium_requests), ""]].forEach(function (cell) {
          var td = document.createElement("td");
          if (cell[1]) td.className = cell[1];
          text(td, cell[0]);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }).catch(function () { /* the strip is a convenience */ });
}

function boardPanel(open) { return section("board", open); }

document.querySelectorAll(".side-tabs .segment").forEach(function (b) {
  b.addEventListener("click", function () { section(b.dataset.section); });
});
document.getElementById("sidetoggle").addEventListener("click", function () {
  if (syncSide()) closeSide(); else section(lastSection, true);
});
document.getElementById("closeboard").addEventListener("click", function () { boardPanel(false); });
document.getElementById("boardrefresh").addEventListener("click", function () { loadBoard(true); });
document.getElementById("boardsearch").addEventListener("input", function () { drawBoard(board); });

/* ================================================================= the desk (#130 #131 #132 #133)

   Everything below reads. The one exception is `attach`, which copies a file the operator clicked
   into that repository's own `.agent/in/` -- the single write the epic allows outside
   `~/.agentdata/fleet/`, and it happens because a person pressed a button.

   All of it comes from one `/api/desk` on a slow clock rather than a fetch per tile: four screens
   of tiles is four screens of requests otherwise, and none of this is urgent. */

function loadDesk() {
  if (pendingDesk) return pendingDesk;
  pendingDesk = fetch(q("/api/desk")).then(function (r) { return r.json(); }).then(function (data) {
    pendingDesk = null;
    if (!data.ok) return;
    desk = data;
    // The project's own detail is the inspector's, and the inspector draws the selected one.
    drawInspector(desk.desk.selected);
    drawTray();
    place();
    return data;
  }).catch(function () { pendingDesk = null; });
  return pendingDesk;
}

var deskSoon = (function () {
  var timer = null;
  return function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; loadDesk(); }, 300);
  };
})();

/* ------------------------------------------------------------------ the project's live state */

var CELLS = ["ticket", "pr", "refresh", "git"];

/* A cell is value + age, and when the poll failed it is grey with the error in the tooltip and the
   *last value it actually had* still on it. Blanking it would lose what was known; keeping it
   without the age would make five-minute-old news look current. Grey, old and honest. */
function drawCells(el, polls) {
  var box = el.querySelector(".cells");
  while (box.firstChild) box.removeChild(box.firstChild);
  CELLS.forEach(function (name) {
    var p = polls[name];
    if (!p) return;
    var value = (p.value && p.value.text) || "";
    if (!value && !p.error) return;                 // nothing to ask about: no PR, no dataset
    var cell = document.createElement("span");
    cell.className = "cell" + (p.grey ? " grey" : "") + (value ? "" : " idle");
    cell.dataset.cell = name;
    var lab = document.createElement("span");
    lab.className = "lab";
    text(lab, name);
    var val = document.createElement("span");
    val.className = "val";
    text(val, value || "—");
    var old = document.createElement("span");
    old.className = "old";
    text(old, p.age_s ? age(Math.round(p.age_s)) : "");
    cell.appendChild(lab);
    cell.appendChild(val);
    cell.appendChild(old);
    cell.title = p.error ? p.error : (name + ", polled every " + p.interval + "s");
    box.appendChild(cell);
  });
}

function clip(value) {
  try {
    if (navigator.clipboard) return navigator.clipboard.writeText(value);
  } catch (e) { /* Simple Browser has no clipboard permission; fall through */ }
  var box = document.createElement("textarea");
  box.value = value;
  document.body.appendChild(box);
  box.select();
  try { document.execCommand("copy"); } catch (e) { /* nothing else to try */ }
  document.body.removeChild(box);
}

/* ------------------------------------------------------------------ the Downloads inbox (#132) */

function offerRow(row, repo) {
  var li = document.createElement("li");
  var nm = document.createElement("span");
  nm.className = "nm";
  text(nm, row.name);
  nm.title = row.path + "\n" + row.reason;
  var meta = document.createElement("span");
  meta.className = "meta";
  text(meta, kb(row.size) + "  ·  " + age(Math.round(row.age_s)));
  li.appendChild(nm);
  li.appendChild(meta);

  if (row.offered) {
    var where = null;
    if (!repo) {
      // Unsorted: the operator picks the project. Nothing is guessed -- two repos that match the
      // name equally well is exactly why this tray exists.
      where = document.createElement("select");
      Array.from(tiles.keys()).forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        text(option, name);
        where.appendChild(option);
      });
      li.appendChild(where);
    }
    var attach = document.createElement("button");
    text(attach, "attach");
    attach.title = "copy it into that repo's .agent/in/<KEY>/ and leave the original here";
    attach.addEventListener("click", function (e) {
      e.stopPropagation();
      var target = repo || (where && where.value);
      if (!target) return;
      post("attach", { id: row.id, repo: target }).then(function (r) {
        text(meta, r.ok ? (r.attached ? "attached → " + r.dir : (r.why || "already there"))
                        : (r.error || "refused"));
        loadDesk();
      });
    });
    li.appendChild(attach);
  } else {
    var why = document.createElement("span");
    why.className = "why";
    text(why, row.reason);
    li.appendChild(why);
  }

  var no = document.createElement("button");
  text(no, "dismiss");
  no.title = "stop offering this file; a newer save of the same name comes back";
  no.addEventListener("click", function (e) {
    e.stopPropagation();
    post("dismiss", { id: row.id }).then(function () { loadDesk(); });
  });
  li.appendChild(no);
  return li;
}

function kb(bytes) {
  var n = Number(bytes) || 0;
  if (n < 1024) return n + " B";
  if (n < 1048576) return Math.round(n / 1024) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

function drawTray() {
  var loose = document.getElementById("loose");
  while (loose.firstChild) loose.removeChild(loose.firstChild);
  (desk.unsorted || []).forEach(function (row) { loose.appendChild(offerRow(row, "")); });
  document.getElementById("noloose").hidden = (desk.unsorted || []).length > 0;

  var rows = document.getElementById("refusedrows");
  while (rows.firstChild) rows.removeChild(rows.firstChild);
  (desk.not_offered || []).concat(desk.still_writing || []).forEach(function (row) {
    var li = document.createElement("li");
    var nm = document.createElement("span");
    nm.className = "nm";
    text(nm, row.name);
    var why = document.createElement("span");
    why.className = "why";
    text(why, row.reason);
    li.appendChild(nm);
    li.appendChild(why);
    rows.appendChild(li);
  });
  text(document.getElementById("folders"), (desk.folders || []).join("  ·  "));
}

function trayPanel(open) { return section("unsorted", open); }

document.getElementById("closetray").addEventListener("click", function () { trayPanel(false); });

/* ------------------------------------------------------------------------- where (#130), search */

/* The catalogue answers "which project owns Velocity" without opening a tab. It is the same
   `Catalogue.where` the CLI verb calls, and it reads only what each repo publishes -- no source,
   no notebooks, no exports, and nothing that was never indexed. */
function drawHits(data) {
  var list = document.getElementById("hits");
  while (list.firstChild) list.removeChild(list.firstChild);
  (data.results || []).forEach(function (hit) {
    var li = document.createElement("li");
    var p = document.createElement("span");
    p.className = "p";
    text(p, hit.project);
    var kind = document.createElement("span");
    kind.className = "kind";
    text(kind, hit.kind);
    var snip = document.createElement("span");
    snip.className = "snip";
    text(snip, (hit.title ? hit.title + " — " : "") + hit.snippet);
    li.appendChild(p);
    li.appendChild(kind);
    li.appendChild(snip);
    li.addEventListener("click", function () {
      choose(hit.project);
      if (tiles.has(hit.project) && LAYOUT === "grid") focus(hit.project);
      foundPanel(false);
    });
    list.appendChild(li);
  });
  text(document.getElementById("foundhow"),
       data.ok ? ((data.results || []).length + " projects · " + (data.fts ? "fts5" : "like"))
               : (data.error + (data.hint ? " — " + data.hint : "")));
  document.getElementById("nohits").hidden = (data.results || []).length > 0;
}

var findSoon = (function () {
  var timer = null;
  return function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var needle = document.getElementById("find").value.trim();
      if (!needle) return foundPanel(false);
      foundPanel(true);
      fetch(q("/api/where", { q: needle, limit: 20 })).then(function (r) { return r.json(); })
        .then(drawHits).catch(function () { /* search is a convenience; the tiles are the truth */ });
    }, 250);
  };
})();

function foundPanel(open) { return section("found", !!open); }

document.getElementById("find").addEventListener("input", findSoon);
document.getElementById("closefound").addEventListener("click", function () { foundPanel(false); });

/* ------------------------------------------------------------------------- the layouts (#133) */

/* One selected project, shared by every window on this server. It is a POST and not a URL fragment
   because the point is that the *other* windows hear about it: clicking a tile on the left monitor
   is what changes the centre one. */
/* The desk state is merged, never replaced. `/api/select` answers with the selection and the
   screen pinning and says nothing about the arrangement, so assigning its answer wholesale dropped
   `arrangement` on the floor: clicking any tile un-widened every tile you had widened and unpinned
   every tile you had pinned, until the next `/api/desk` poll fifteen seconds later put them back. */
function mergeDesk(answer) {
  if (!answer) return;
  var next = Object.assign({}, desk.desk);
  ["selected", "screens", "version", "arrangement"].forEach(function (k) {
    if (answer[k] !== undefined) next[k] = answer[k];
  });
  desk.desk = next;
}

function choose(name) {
  if (desk.desk.selected === name) {
    drawInspector(name);
    return Promise.resolve();
  }
  mergeDesk({ selected: name });
  place();
  drawInspector(name);
  return post("select", { repo: name }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    place();
    drawInspector(name);
  });
}

/* The selected project's own detail, in one place instead of repeated inside every tile: a tile is
   the AGENT, the inspector is the PROJECT (#148). Visibility belongs to the sidebar, not here --
   this only draws, so a redraw can never reopen a panel the operator just closed. */
function drawInspector(name) {
  var el = document.getElementById("inspector");
  if (!el) return;
  var body0 = document.getElementById("inspectordetails");
  if (!name || !tiles.has(name)) {
    text(document.getElementById("inspectorrepo"), "");
    while (body0.firstChild) body0.removeChild(body0.firstChild);
    return;
  }
  text(document.getElementById("inspectorrepo"), name);
  var body = document.getElementById("inspectordetails");
  while (body.firstChild) body.removeChild(body.firstChild);

  var p = desk.projects[name] || {};
  var facts = document.createElement("div");
  facts.className = "facts";
  /* The ONE place on this page that renders a fact block, and it stays one on purpose.
     `serve.tile_facts()` narrows `catalogue.LINK_FACTS` before any of it leaves the server,
     because a fact block is hand-edited prose and a real one carries a warehouse hostname, a
     `\\share\dpm\runs` path and a service account beside the Jira keys. A second loop over some
     other payload's facts is how that filter gets bypassed by a change that looks like a feature.
     If a panel ever needs a fact this loop does not show, widen `LINK_FACTS`; do not add a loop. */
  var pairs = [
    ["project", name],
    ["path", p.path || "—"],
    ["branch", p.branch || "—"],
    ["jira", p.jira_project || "—"]
  ];
  var factsFromCatalogue = p.facts || {};
  Object.keys(factsFromCatalogue).forEach(function (k) {
    if (k !== "jira_project") pairs.push([k, factsFromCatalogue[k]]);
  });
  pairs.push(["indexed", p.indexed ? (p.last_indexed || "yes") : "not yet"]);
  pairs.forEach(function (row) {
    var k = document.createElement("span");
    k.className = "k";
    text(k, row[0]);
    var v = document.createElement("span");
    v.className = "v";
    text(v, row[1]);
    facts.appendChild(k);
    facts.appendChild(v);
  });
  body.appendChild(facts);

  // What is missing is named, so the operator knows which AGENTS.md key would fill the rail.
  var missing = p.missing_keys || [];
  if (missing.length) {
    var gap = document.createElement("p");
    gap.className = "muted";
    text(gap, "add to AGENTS.md for the rest of the rail: " + missing.join(", "));
    body.appendChild(gap);
  }

  // Open friction, and the models and reports the catalogue knows about.
  (p.friction || []).forEach(function (f) {
    var li = document.createElement("p");
    li.className = "frictionrow";
    text(li, [f.date, f.type, f.title].filter(Boolean).join("  ·  ") + (f.unblock ? "\n" + f.unblock : ""));
    body.appendChild(li);
  });

  // Where this project lives -- the link rail, so a tab is opened to act and never to check.
  var links = (p.links || []);
  if (links.length || p.path) {
    var rail = document.createElement("div");
    rail.className = "rail";
    links.forEach(function (row) {
      if (!row.url) return;
      var a = document.createElement("a");
      a.className = row.kind;
      a.href = row.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = row.url;
      text(a, row.name);
      rail.appendChild(a);
    });
    if (p.path) {
      var copy = document.createElement("button");
      text(copy, "copy path");
      copy.title = p.path;
      copy.addEventListener("click", function () {
        clip(p.path);
        text(copy, "copied");
        setTimeout(function () { text(copy, "copy path"); }, 1200);
      });
      rail.appendChild(copy);
    }
    body.appendChild(rail);
  }

  // The newest thing the project's own agent verified, beside the report link.
  var latest = ((p.verify || {}).latest) || {};
  if (latest.name) {
    var h = document.createElement("div");
    h.className = "muted";
    text(h, "verify · " + (latest.tool || "") + " · " + latest.name +
            (latest.age_s != null ? " · " + age(Math.round(latest.age_s)) : ""));
    var pre = document.createElement("pre");
    pre.className = "verifybody";
    text(pre, latest.excerpt || "");
    body.appendChild(h);
    body.appendChild(pre);
  }

  var offers = (desk.offers || {})[name] || [];
  if (offers.length) {
    var head = document.createElement("div");
    head.className = "muted";
    text(head, "Downloads is offering " + offers.length + " file" + (offers.length === 1 ? "" : "s"));
    var list = document.createElement("ol");
    list.className = "tray";
    offers.forEach(function (row) { list.appendChild(offerRow(row, name)); });
    body.appendChild(head);
    body.appendChild(list);
  }
}

document.getElementById("closeinspector").addEventListener("click", function () {
  section("inspector", false);
});

function getLayoutArrangement() {
  var arr = (desk.desk && desk.desk.arrangement) || {};
  return arr[LAYOUT] || { order: [], size: {}, pinned: [] };
}

function getEffectiveOrder() {
  var curArr = getLayoutArrangement();
  var pinned = curArr.pinned || [];
  var order = (curArr.order || []).filter(function (n) { return tiles.has(n); });
  Array.from(tiles.keys()).forEach(function (n) {
    if (order.indexOf(n) < 0) order.push(n);
  });
  var result = [];
  pinned.forEach(function (p) { if (tiles.has(p)) result.push(p); });
  order.forEach(function (o) { if (result.indexOf(o) < 0) result.push(o); });
  return result;
}

/* Moving an element with `appendChild` takes the focus off it -- so a grid that re-appends every
   tile on every draw (and the stream draws several times a second while an agent is talking) took
   the focus off the tile the operator had just selected, and Alt+arrow reached nothing. The order
   is therefore only touched when it is actually wrong, and the focus is put back when it is. */
function reorderDomTiles() {
  var grid = document.getElementById("grid");
  if (!grid) return;
  var order = getEffectiveOrder();
  var curArr = getLayoutArrangement();
  var sizes = curArr.size || {};
  var pinned = curArr.pinned || [];

  var inDom = Array.prototype.map.call(grid.children, function (el) { return el.dataset.repo; });
  var needsMove = inDom.join("\u0000") !== order.filter(function (n) { return tiles.has(n); }).join("\u0000");
  var focused = document.activeElement;
  var refocus = needsMove && focused && focused.closest && focused.closest(".tile") ? focused : null;

  order.forEach(function (name, index) {
    var entry = tiles.get(name);
    if (entry && entry.el) {
      if (needsMove) grid.appendChild(entry.el);
      text(entry.el.querySelector(".n"), index + 1);
      var sz = sizes[name] || 1;
      entry.el.classList.toggle("size-2", sz === 2);
      var szBtn = entry.el.querySelector(".sizetoggle");
      if (szBtn) {
        szBtn.classList.toggle("active", sz === 2);
        szBtn.setAttribute("aria-pressed", String(sz === 2));
        szBtn.title = sz === 2 ? "back to one column (Alt+Enter)" : "widen to two columns (Alt+Enter)";
      }
      var isPinned = pinned.indexOf(name) >= 0;
      entry.el.classList.toggle("is-pinned", isPinned);
      var pBtn = entry.el.querySelector(".pintoggle");
      if (pBtn) {
        pBtn.classList.toggle("active", isPinned);
        pBtn.setAttribute("aria-pressed", String(isPinned));
        pBtn.title = isPinned ? "unpin (Alt+Home)" : "pin this tile first (Alt+Home)";
      }
    }
  });
  if (refocus) refocus.focus();
}

/* Pinned tiles come first, always -- so a move has to happen inside the block the tile is in.
   Reordering the flattened list and posting that did nothing whenever anything was pinned:
   `getEffectiveOrder` puts the pinned names back in front on the very next draw, and the move the
   operator just made was silently undone. */
function moveTile(repo, dir) {
  var arr = getLayoutArrangement();
  var pinned = (arr.pinned || []).filter(function (n) { return tiles.has(n); });
  var inPinnedBlock = pinned.indexOf(repo) >= 0;
  var block = inPinnedBlock
    ? pinned
    : getEffectiveOrder().filter(function (n) { return pinned.indexOf(n) < 0; });

  var idx = block.indexOf(repo);
  var target = idx + dir;
  if (idx < 0 || target < 0 || target >= block.length) return;
  block.splice(idx, 1);
  block.splice(target, 0, repo);

  var body = { layout: LAYOUT };
  if (inPinnedBlock) body.pinned = block;
  else body.order = block;
  // Optimistic, then confirmed: the tile moves under the hand, and the server's answer is what
  // the next draw reads.
  if (inPinnedBlock) arr.pinned = block; else arr.order = block;
  reorderDomTiles();
  post("arrange", body).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
}

function toggleTileSize(repo) {
  var curArr = getLayoutArrangement();
  var sizes = Object.assign({}, curArr.size || {});
  sizes[repo] = (sizes[repo] === 2) ? 1 : 2;
  curArr.size = sizes;
  reorderDomTiles();
  return post("arrange", { layout: LAYOUT, size: sizes }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
}

/* Both toggles write the local arrangement BEFORE the round trip, not only after it. Reading
   `desk.desk` and posting without updating it meant two quick clicks both read the same state and
   the second overwrote the first: pin two tiles in a second and one of them silently came back
   unpinned. The returned promise is what lets a caller sequence them. */
function toggleTilePin(repo) {
  var curArr = getLayoutArrangement();
  var pinned = (curArr.pinned || []).slice();
  var idx = pinned.indexOf(repo);
  if (idx >= 0) pinned.splice(idx, 1); else pinned.push(repo);
  curArr.pinned = pinned;
  reorderDomTiles();
  return post("arrange", { layout: LAYOUT, pinned: pinned }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
}

/* Which project this window is showing, when it is showing exactly one. `screens` is the shared
   pinning; a screen with nothing pinned falls back to the Nth registered repo, so opening
   `?layout=screens&screen=2` on a fresh fleet shows something rather than an empty monitor. */
function solo() {
  var names = Array.from(tiles.keys());
  if (LAYOUT === "screens" && SCREEN) {
    var pinned = (desk.desk.screens || [])[SCREEN - 1];
    return pinned || names[SCREEN - 1] || "";
  }
  if (VIEW === "verify") return desk.desk.selected || names[0] || "";
  return "";
}

/* The one function that decides what this window shows. Body classes only: the stylesheet is the
   layout, and every arrangement is the same DOM, so a tile cannot mean one thing on one screen and
   something else on another. */
function place() {
  var body = document.body;
  var one = solo();
  body.classList.remove("layout-grid", "layout-roles", "layout-screens",
                        "view-board", "view-agents", "view-verify", "solo", "panels");
  body.classList.add("layout-" + LAYOUT);
  if (VIEW) body.classList.add("view-" + VIEW);
  if (one) body.classList.add("solo");
  if ((LAYOUT === "roles" && VIEW === "board") || (LAYOUT === "screens" && !SCREEN)) {
    body.classList.add("panels");
  }
  body.classList.toggle("needs-only", needsOnly);
  tiles.forEach(function (entry, name) {
    entry.el.classList.toggle("is-solo", name === one);
    entry.el.classList.toggle("is-selected", name === desk.desk.selected);
  });
  reorderDomTiles();
  if (one) {
    // Opened once, not on every draw: a window that reopens a panel the operator just closed is
    // the kind of thing that gets a dashboard turned off.
    // A window showing exactly one project opens the inspector on it, once -- reopening a panel
    // the operator just closed is the kind of thing that gets a dashboard turned off.
    var entry = tiles.get(one);
    if (entry && entry.el.dataset.opened !== "1") {
      entry.el.dataset.opened = "1";
      section("inspector", true);
    }
  }
  var need = 0;
  tiles.forEach(function (entry) { if (entry.el.classList.contains("needs-human")) need += 1; });
  document.getElementById("nonefocus").hidden = !(needsOnly && !one && need === 0 && tiles.size > 0);
  var notice = document.getElementById("notice");
  if (unknownLayout) {
    text(notice, "unknown layout '" + unknownLayout + "' — showing grid");
    notice.hidden = false;
  } else {
    text(notice, "");
    notice.hidden = true;
  }
  drawSwap(one);
}

/* The tab bar is the friction, so the window's own title says which screen it is. */
function title(need) {
  var one = solo();
  document.title = (need ? "(" + need + ") " : "") + "fleet" +
                   (LAYOUT === "grid" ? "" : " · " + (VIEW || ("screen " + (SCREEN || "board")))) +
                   (one ? " · " + one : "");
}

function go(params) {
  var u = new URLSearchParams(location.search);
  Object.keys(params).forEach(function (k) {
    if (params[k]) u.set(k, params[k]); else u.delete(k);
  });
  var rawL = u.get("layout");
  unknownLayout = (rawL && LAYOUTS.indexOf(rawL) < 0) ? rawL : null;
  LAYOUT = unknownLayout ? "grid" : (rawL || "grid");
  VIEW = VIEWS.indexOf(u.get("view")) >= 0 ? u.get("view") : (LAYOUT === "roles" ? "agents" : "");
  SCREEN = Math.max(0, Math.min(9, Number(u.get("screen")) || 0));
  var qs = u.toString();
  var newUrl = location.pathname + (qs ? "?" + qs : "");
  history.pushState({}, "", newUrl);
  updateLayoutSegments();
  place();
}

/* One control per meaning (HIG *Segmented controls*). The first segment is the arrangement; the
   second says WHICH window of that arrangement this one is, and only exists for the arrangements
   that come as a set. There used to be a second, duplicate <select> alongside this, offering the
   same eight choices in a different vocabulary. */
var VIEW_SEGMENTS = {
  roles: [["agents", "agents"], ["verify", "verify"], ["board", "board"]],
  screens: [["", "laptop"], ["1", "screen 1"], ["2", "screen 2"], ["3", "screen 3"]]
};

function updateLayoutSegments() {
  document.querySelectorAll("#layoutgroup .segment").forEach(function (btn) {
    var active = btn.dataset.layout === LAYOUT;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-checked", String(active));
  });

  var group = document.getElementById("viewgroup");
  var rows = VIEW_SEGMENTS[LAYOUT];
  group.hidden = !rows;
  while (group.firstChild) group.removeChild(group.firstChild);
  if (!rows) return;
  rows.forEach(function (row) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "segment";
    var mine = LAYOUT === "roles" ? (VIEW === row[0]) : (String(SCREEN || "") === row[0]);
    btn.classList.toggle("active", mine);
    btn.setAttribute("aria-checked", String(mine));
    text(btn, row[1]);
    btn.addEventListener("click", function () {
      if (LAYOUT === "roles") go({ layout: "roles", view: row[0], screen: "" });
      else go({ layout: "screens", view: "", screen: row[0] });
    });
    group.appendChild(btn);
  });
}

window.addEventListener("popstate", function () {
  var u = new URLSearchParams(location.search);
  var rawL = u.get("layout");
  unknownLayout = (rawL && LAYOUTS.indexOf(rawL) < 0) ? rawL : null;
  LAYOUT = unknownLayout ? "grid" : (rawL || "grid");
  VIEW = VIEWS.indexOf(u.get("view")) >= 0 ? u.get("view") : (LAYOUT === "roles" ? "agents" : "");
  SCREEN = Math.max(0, Math.min(9, Number(u.get("screen")) || 0));
  updateLayoutSegments();
  place();
});

(function layoutPicker() {
  document.querySelectorAll("#layoutgroup .segment").forEach(function (btn) {
    btn.addEventListener("click", function () {
      go({ layout: btn.dataset.layout, view: "", screen: "" });
    });
  });
  updateLayoutSegments();
})();

/* Layout C's swap. The pinning is server state, so moving a project onto this monitor takes it off
   whichever one was holding it -- otherwise two screens end up showing the same thing. */
function drawSwap(one) {
  var swap = document.getElementById("swap");
  swap.hidden = !(LAYOUT === "screens" && SCREEN);
  if (swap.hidden) return;
  var names = Array.from(tiles.keys());
  while (swap.firstChild) swap.removeChild(swap.firstChild);
  names.forEach(function (name) {
    var option = document.createElement("option");
    option.value = name;
    text(option, "screen " + SCREEN + ": " + name);
    swap.appendChild(option);
  });
  swap.value = one;
}

document.getElementById("swap").addEventListener("change", function () {
  var swap = document.getElementById("swap");
  var names = Array.from(tiles.keys());
  var screens = (desk.desk.screens || []).slice();
  while (screens.length < Math.max(SCREEN, names.length)) screens.push(names[screens.length] || "");
  var wanted = swap.value;
  var here = screens[SCREEN - 1];
  var was = screens.indexOf(wanted);
  if (was >= 0) screens[was] = here;                  // a swap, not an overwrite
  screens[SCREEN - 1] = wanted;
  post("select", { screens: screens }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    place();
  });
});

/* ------------------------------------------------------------------------------- focus mode */

/* The fourth thing #133 asks for, and the only one that is not a layout: hide every tile except
   the ones #94 says need a person. The alternative to arranging tabs is having fewer to look at.
   Toggled with `f`, remembered per window, and printed in the footer's key map. */
function focusMode(on) {
  needsOnly = on === undefined ? !needsOnly : !!on;
  document.getElementById("focus").setAttribute("aria-pressed", String(needsOnly));
  try { localStorage.setItem("fleet.needsonly", needsOnly ? "1" : "0"); } catch (e) { /* private */ }
  place();
}

document.getElementById("focus").addEventListener("click", function () { focusMode(); });

try { needsOnly = localStorage.getItem("fleet.needsonly") === "1"; } catch (e) { needsOnly = false; }
document.getElementById("focus").setAttribute("aria-pressed", String(needsOnly));

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape" && !typing) { closeSide(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "f") { focusMode(); return; }
  if (e.key === "i") { section("unsorted"); return; }
  if (e.key === "/") { e.preventDefault(); document.getElementById("find").focus(); }
});
