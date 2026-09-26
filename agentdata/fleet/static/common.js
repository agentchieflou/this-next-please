"use strict";

var PARAMS = new URLSearchParams(location.search);
var TOKEN = PARAMS.get("t") || "";

function q(path, params) {
  var u = new URL(path, location.origin);
  u.searchParams.set("t", TOKEN);
  Object.keys(params || {}).forEach(function (k) { u.searchParams.set(k, params[k]); });
  return u.toString();
}

var CARRIED = ["w", "shell", "ink"];

function pageUrl(path, params) {
  var carry = {};
  CARRIED.forEach(function (k) { if (PARAMS.get(k)) carry[k] = PARAMS.get(k); });
  return q(path, Object.assign(carry, params || {}));
}

var onAuthLost = null;

function post(action, body) {
  return fetch(q("/api/" + action), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  }).then(function (r) {
    if (r.status === 403 && typeof onAuthLost === "function") onAuthLost();
    return r.json();
  });
}

function text(el, value) {
  if (!el) return;
  var want = value == null ? "" : String(value);
  if (el.textContent !== want) el.textContent = want;
}

function setClass(el, value) {
  if (el && el.className !== value) el.className = value;
}

function attr(el, name, value) {
  if (!el) return;
  if (value === null || value === false || value === undefined) {
    if (el.hasAttribute(name)) el.removeAttribute(name);
    return;
  }
  var want = String(value);
  if (el.getAttribute(name) !== want) el.setAttribute(name, want);
}

function toggle(el, name, on) {
  if (el && el.classList.contains(name) !== !!on) el.classList.toggle(name, !!on);
}

function hide(el, hidden) {
  if (el && el.hidden !== !!hidden) el.hidden = !!hidden;
}

function disable(el, on) {
  if (el && el.disabled !== !!on) el.disabled = !!on;
}

function setData(el, name, value) {
  if (!el) return;
  var want = value == null ? "" : String(value);
  if (el.dataset[name] !== want) el.dataset[name] = want;
}

function tabbable(el, index) {
  if (el && el.tabIndex !== index) el.tabIndex = index;
}

function style(el, prop, value) {
  if (el && el.style.getPropertyValue(prop) !== value) el.style.setProperty(prop, value);
}

function patchList(parent, rows, keyOf, create, update) {
  if (!parent) return [];
  var have = new Map();
  Array.prototype.forEach.call(parent.children, function (el) {
    var k = el.dataset ? el.dataset.rowkey : "";
    if (k) have.set(k, el);
  });

  var keys = [];
  var out = [];
  rows.forEach(function (row, i) {
    var key = String(keyOf(row, i));
    if (keys.indexOf(key) >= 0) throw new Error("patchList: two rows share the key " + key);
    keys.push(key);
    var el = have.get(key);
    if (!el) {
      el = create(row, key, i);
      el.dataset.rowkey = key;
      parent.appendChild(el);
      have.set(key, el);
    }
    if (update) update(el, row, i);
    out.push(el);
  });

  have.forEach(function (el, key) { if (keys.indexOf(key) < 0) el.remove(); });

  var inDom = Array.prototype.filter.call(parent.children, function (el) {
    return el.dataset && el.dataset.rowkey;
  });
  var wrong = inDom.length !== out.length ||
              inDom.some(function (el, i) { return el !== out[i]; });
  if (wrong) {
    var keyboard = /** @type {HTMLElement} */ (document.activeElement);
    out.forEach(function (el) { parent.appendChild(el); });
    if (keyboard && keyboard.isConnected && keyboard !== document.body) keyboard.focus();
  }
  return out;
}

function applyTheme(cssVars, themeName) {
  var root = document.documentElement;
  var tokens = ["--bg", "--text", "--panel", "--line", "--select", "--muted", "--accent",
                "--focus", "--running", "--waiting", "--human", "--done", "--idle",
                "--on-running", "--on-waiting", "--on-human", "--on-done", "--on-idle",
                "--running-text", "--waiting-text", "--human-text", "--done-text", "--idle-text"];
  if (cssVars && themeName && themeName !== "none") {
    tokens.forEach(function (k) {
      if (cssVars[k]) {
        if (root.style.getPropertyValue(k) !== cssVars[k]) root.style.setProperty(k, cssVars[k]);
      } else if (root.style.getPropertyValue(k)) {
        root.style.removeProperty(k);
      }
    });
    attr(root, "data-theme", "custom");
  } else {
    tokens.forEach(function (k) { if (root.style.getPropertyValue(k)) root.style.removeProperty(k); });
    attr(root, "data-theme", null);
  }
}

function applySkin(skinName) {
  var link = /** @type {HTMLLinkElement} */ (document.head.querySelector("link[data-skin]"));
  var parts = String(skinName || "").split(":");
  var family = parts[0];
  var variant = parts[1] || "";
  if (!family || family === "none") {
    if (link) link.remove();
    attr(document.body, "data-skin", null);
    attr(document.body, "data-skin-variant", null);
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("data-skin", "true");
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  var href = q("/static/skins/" + family + "/skin.css");
  if (link.href !== href) link.href = href;
  attr(document.body, "data-skin", family);
  attr(document.body, "data-skin-variant", variant || null);
}

function gesture(name) {
  var mark = name + ":" + (Date.now() % 100000);
  try { performance.mark(mark + ":start"); } catch (e) {}
  return mark;
}

function settle(mark) {
  if (!mark) return 0;
  try {
    performance.mark(mark + ":end");
    var m = performance.measure(mark, mark + ":start", mark + ":end");
    return m ? m.duration : 0;
  } catch (e) {
    return 0;
  }
}

var LOAD = { on: false, page: null, settled: "", queued: "" };

(function measureLoad() {
  try {
    LOAD.on = document.documentElement.getAttribute("data-measure") === "loads";
  } catch (e) { return; }
  if (!LOAD.on) return;
  var path = location.pathname.replace(/\/+$/, "") || "/";
  LOAD.page = path === "/" ? "desk" : path === "/settings" ? "settings" : null;
  if (!LOAD.page) return;

  var desk = LOAD.page === "desk";
  var rec = { page: LOAD.page, from: "" };
  if (desk) {
    try {
      if (sessionStorage.getItem("fleet.load.from") !== null) rec.from = "settings";
      sessionStorage.removeItem("fleet.load.from");
    } catch (e) {}
  }

  var sent = false;
  var later = null;
  function ms(n) { return Math.round(n * 10) / 10; }
  function observe(type, each) {
    try {
      var types = PerformanceObserver.supportedEntryTypes || [];
      if (types.indexOf(type) < 0) return null;
      var seen = new PerformanceObserver(function (list) { list.getEntries().forEach(each); });
      seen.observe({ type: type, buffered: true });
      return seen;
    } catch (e) { return null; }
  }
  function isFleet(entry) {
    try { return new URL(entry.name).pathname === "/api/fleet"; } catch (x) { return false; }
  }
  observe("paint", function (entry) { if (entry.name === "first-paint") queue(); });
  var longest = 0;
  function task(entry) { longest = Math.max(longest, entry.duration); }
  var tasks = observe("longtask", function (entry) {
    var was = longest;
    task(entry);
    if (longest > was) queue();
  });
  var fleetSeen = !desk;
  if (desk) observe("resource", function (entry) {
    if (!fleetSeen && isFleet(entry)) { fleetSeen = true; queue(); }
  });
  var skinFirst = null;
  try {
    requestAnimationFrame(function () {
      try { skinFirst = document.body.dataset.skin || ""; } catch (e) { skinFirst = ""; }
      queue();
    });
  } catch (e) {}
  var settled = LOAD.settled;
  try {
    Object.defineProperty(LOAD, "settled", {
      enumerable: true,
      get: function () { return settled; },
      set: function (value) { settled = value; queue(); }
    });
  } catch (e) {}

  var inkDone = !desk;
  var inkFrom = 0;
  function lookForInk() {
    if (inkDone) return;
    try {
      if (!inkFrom) inkFrom = performance.now();
      if (performance.now() - inkFrom > 10000) { inkDone = true; return; }
      var ink = window["Ink"];
      if (!ink || typeof ink.inspect !== "function") ink = null;
      if (ink && !ink.enabled) { inkDone = true; return; }
      var canvas = document.querySelector("#ink");
      if (ink && canvas && canvas.hasAttribute("data-skin")) {
        var seen = ink.inspect();
        if (!seen || !seen.verdict || !seen.verdict.on || !seen.layer) { inkDone = true; return; }
        if (seen.layer.renders >= 1) {
          rec.ink_first_frame_ms = ms(performance.now());
          inkDone = true;
          queue();
          return;
        }
      }
      requestAnimationFrame(lookForInk);
    } catch (e) { inkDone = true; }
  }
  lookForInk();

  function record() {
    rec.shell = PARAMS.get("shell") || PARAMS.get("w") || "browser";
    var nav = /** @type {PerformanceNavigationTiming} */ (performance.getEntriesByType("navigation")[0]);
    rec.how = nav ? nav.type : "";
    rec.origin_ms = ms(performance.timeOrigin);
    var paint = performance.getEntriesByType("paint").filter(function (e) {
      return e.name === "first-paint";
    })[0];
    if (paint) rec.first_paint_ms = ms(paint.startTime);
    if (tasks) {
      tasks.takeRecords().forEach(task);
      rec.longest_task_ms = ms(longest);
    }
    if (desk) {
      var fleet = performance.getEntriesByType("resource").filter(isFleet)[0];
      if (fleet) rec.fleet_ms = ms(/** @type {PerformanceResourceTiming} */ (fleet).responseEnd);
    }
    rec.skin_first = skinFirst === null ? "" : skinFirst;
    rec.skin_settled = LOAD.settled || "";
    rec.ua = String(navigator.userAgent || "").slice(0, 200);
    return JSON.stringify(rec);
  }

  function queue() {
    if (sent || typeof window["fetchLater"] !== "function") return;
    try {
      var body = record();
      var next = new AbortController();
      window["fetchLater"](q("/api/load"), { method: "POST", body: body, signal: next.signal });
      if (later) later.abort();
      later = next;
      LOAD.queued = body;
    } catch (e) {}
  }

  window.addEventListener("pagehide", function () {
    inkDone = true;
    if (sent) return;
    sent = true;
    try {
      var body = record();
      if (navigator.sendBeacon(q("/api/load"), new Blob([body], { type: "text/plain" })) && later) {
        later.abort();
        later = null;
        LOAD.queued = "";
      }
    } catch (e) {}
  });
  queue();
})();
