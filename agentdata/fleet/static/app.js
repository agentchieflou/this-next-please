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
}

function unfocus() {
  focused = null;
  document.body.classList.remove("focused");
  document.getElementById("unfocus").hidden = true;
  tiles.forEach(function (entry) { entry.el.classList.remove("is-focused"); });
}

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

refresh().then(function () { connect(); loadThemes(); });
