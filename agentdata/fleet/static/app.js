/* The multi-viewer's client. No framework and no build step on purpose: this file has to load
   inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
   fetched from the internet simply does not arrive.

   The page is a view. It never decides anything -- every state comes from /api/fleet and every
   button POSTs to the same function the CLI verb calls. */

"use strict";

var TOKEN = new URLSearchParams(location.search).get("t") || "";
var tiles = new Map();          // repo name -> {el, seq}
var focused = null;
var pendingRefresh = null;
var source = null;

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
    case "pr_open": return d.url || "";
    case "artifact": return (d.artifact && d.artifact.path) || "";
    case "session_id": return "";
    default: return JSON.stringify(d).slice(0, 160);
  }
}

var SHOWN = {
  started: 1, assistant_text: 1, tool_call: 1, tool_result: 1, denied: 1, friction: 1,
  phase_changed: 1, question_opened: 1, needs_approval: 1, approval_resolved: 1,
  exited: 1, error: 1, pr_open: 1, artifact: 1
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
  text(el.querySelector(".repo"), row.repo);
  el.dataset.repo = row.repo;

  el.querySelector(".repo").addEventListener("click", function () { focus(row.repo); });
  el.addEventListener("dblclick", function () { focus(row.repo); });

  // A ticket dropped on a tile is a dispatch. `preventDefault` on dragover is what makes an
  // element a drop target at all -- without it the browser refuses the drop and nothing happens,
  // silently, which looks exactly like a broken feature.
  el.addEventListener("dragover", function (e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    el.classList.add("drop-target");
  });
  el.addEventListener("dragleave", function () { el.classList.remove("drop-target"); });
  el.addEventListener("drop", function (e) {
    e.preventDefault();
    el.classList.remove("drop-target");
    var key = (e.dataTransfer.getData("text/plain") || "").trim();
    if (key) dispatch(key, row.repo);
  });

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
  el.className = "tile state-" + row.state + (el.classList.contains("is-focused") ? " is-focused" : "");
  el.tabIndex = 0;
  var chip = el.querySelector(".chip");
  chip.className = "chip " + row.state;
  text(chip, row.state.replace(/_/g, " "));
  text(el.querySelector(".ticket"), row.ticket || row.jira_project || "");
  text(el.querySelector(".why"), row.why || "");
  text(el.querySelector(".age"), row.last_event_age_s >= 0 ? age(row.last_event_age_s) : "");

  var mine = approvals.filter(function (a) { return a.repo === row.repo; })[0];
  var card = el.querySelector(".approval");
  card.hidden = !mine;
  if (mine) {
    el.dataset.approval = mine.id;
    text(el.querySelector(".kind"), mine.kind + "  ·  " + age(mine.waiting_s));
    text(el.querySelector(".summary"), mine.summary || "");
    text(el.querySelector(".payload"), JSON.stringify(mine.payload || {}, null, 2));
  }
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
    document.title = (need ? "(" + need + ") " : "") + "fleet";
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
    var names = Array.from(tiles.keys());
    var name = names[Number(e.key) - 1];
    if (name) focus(name);
    return;
  }
  if (e.key === "n") { drawer(); return; }
  if (e.key === "b") { boardPanel(); return; }
  if (e.key === "a") {
    var entry = focused ? tiles.get(focused) : null;
    if (entry && entry.el.dataset.approval && !entry.el.querySelector(".approval").hidden) {
      entry.el.querySelector(".approve").click();
    }
  }
});

/* ------------------------------------------------------------------------------------- theming */

function applyTheme(colors) {
  var root = document.documentElement;
  ["bg", "panel", "text", "muted", "accent", "line", "select"].forEach(function (k) {
    if (colors && colors[k]) root.style.setProperty("--" + k, colors[k]);
    else root.style.removeProperty("--" + k);
  });
  if (colors) root.setAttribute("data-theme", "custom");
  else root.removeAttribute("data-theme");
}

function loadThemes() {
  var select = document.getElementById("theme");
  return fetch(q("/api/themes")).then(function (r) { return r.json(); }).then(function (data) {
    (data.themes || []).forEach(function (t) {
      var option = document.createElement("option");
      option.value = t.name;
      text(option, t.name);
      select.appendChild(option);
    });
    var saved = null;
    try { saved = localStorage.getItem("fleet.theme"); } catch (e) { saved = null; }
    select.value = saved && Array.prototype.some.call(select.options, function (o) {
      return o.value === saved;
    }) ? saved : "";
    select.addEventListener("change", function () {
      var chosen = (data.themes || []).filter(function (t) { return t.name === select.value; })[0];
      applyTheme(chosen ? chosen.colors : null);
      try { localStorage.setItem("fleet.theme", select.value); } catch (e) { /* private window */ }
    });
    select.dispatchEvent(new Event("change"));
  }).catch(function () { /* themes are decoration; the page works without them */ });
}

refresh().then(function () {
  connect();
  loadThemes();
  loadNotifications();
  followHash();
});

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

function drawer(open) {
  var el = document.getElementById("drawer");
  el.hidden = open === undefined ? !el.hidden : !open;
  if (!el.hidden) loadNotifications();
}

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

function boardPanel(open) {
  var el = document.getElementById("board");
  el.hidden = open === undefined ? !el.hidden : !open;
  if (!el.hidden) { loadBoard(false); loadHistory(); }
}

document.getElementById("boardtoggle").addEventListener("click", function () { boardPanel(); });
document.getElementById("closeboard").addEventListener("click", function () { boardPanel(false); });
document.getElementById("boardrefresh").addEventListener("click", function () { loadBoard(true); });
document.getElementById("boardsearch").addEventListener("input", function () { drawBoard(board); });
