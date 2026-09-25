/* What both pages need, and neither owns.

   The desk (`app.js`) and the settings page (`settings.js`) are two pages, not two copies: each
   loads this file first and then its own. Plain non-module scripts share one global scope, so a
   name declared here is simply available in the other -- no build step, no imports, and nothing
   fetched from the internet, which is the constraint the desk has always had (it must load inside
   PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy).

   What lives here is what a SECOND page genuinely needs: the run token and the two functions that
   put it on every request, `pageUrl()` for the links between the pages (they keep the host's `w`,
   `shell` and `ink`), the one-line text setter, and the two painters that turn a palette and a
   skin into what you see. What deliberately does not: anything that assumes a desk.
   `rehome()` stays in `app.js` because it always rebuilds a destination through `/open`, which
   hard-codes `/?t=` -- sending it from here would bounce an operator off the settings page mid-edit. */

"use strict";

var PARAMS = new URLSearchParams(location.search);
var TOKEN = PARAMS.get("t") || "";

/* Every route but `/api/ping` and `/open` wants the token, and a relative URL in the markup does
   not inherit the query string the operator opened. So no fetch is written by hand: they all go
   through here. */
function q(path, params) {
  var u = new URL(path, location.origin);
  u.searchParams.set("t", TOKEN);
  Object.keys(params || {}).forEach(function (k) { u.searchParams.set(k, params[k]); });
  return u.toString();
}

var CARRIED = ["w", "shell", "ink"]; // the page's identity in its host; nothing else travels

function pageUrl(path, params) {
  var carry = {};
  CARRIED.forEach(function (k) { if (PARAMS.get(k)) carry[k] = PARAMS.get(k); });
  return q(path, Object.assign(carry, params || {}));
}

/* A 403 means this page is holding a token the server no longer has -- it was restarted, and the
   run token is per run. What to do about it differs per page, so the page says: the desk goes back
   through `/open` to collect a fresh one, and only once its stream has already died. A page that
   sets nothing simply gets the error, which is the safe direction to be wrong in. */
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

/* ------------------------------------------------------------------ the render contract (#215)

   Created once, patched forever. `place()` runs about two and a half times a second while an agent
   is talking, and a page that rewrote its own DOM on every pass took the hover off whatever was
   under the cursor and the keyboard off whatever had just been reached. Every setter below writes
   only when the value actually changes, so a draw with nothing to say is a draw that touches
   nothing -- which is what a `MutationObserver` at zero asserts, per component. */

function text(el, value) {
  if (!el) return;
  var want = value == null ? "" : String(value);
  if (el.textContent !== want) el.textContent = want;
}

function setClass(el, value) {
  if (el && el.className !== value) el.className = value;
}

/* `null`, `false` and `undefined` remove; everything else sets. Writing an attribute to the value
   it already has is still a mutation as far as the platform is concerned. */
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

/* One list reconciler for the whole page: chips, cells, sessions, bands, patterns, rows.

   Keyed, because the alternative -- tear the list down and clone it again -- is what destroyed the
   hover, the focus and any transient state on every one of them, several times a second. `create`
   makes a row's element the first time it is seen; `update` patches it every time after. Rows that
   go are removed; the order is fixed only when it is actually wrong, because `appendChild` blurs
   whatever it moves. */
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

/* A PALETTE is colour only, so it is 1:1 with the terminal: the same hex reaches this page's custom
   properties and the project's prompt and tab. Writing one goes to the server -- the same
   `~/.agentdata/config.json` that `ad-theme set` writes -- and never to `localStorage`, because a
   desk is four windows and a choice kept in one browser's storage is four different desks. */
function applyTheme(cssVars, themeName) {
  var root = document.documentElement;
  var tokens = ["--bg", "--text", "--panel", "--line", "--select", "--muted", "--accent",
                "--focus", "--running", "--waiting", "--human", "--done", "--idle",
                "--on-running", "--on-waiting", "--on-human", "--on-done", "--on-idle"];
  if (cssVars && themeName && themeName !== "none") {
    // Written only where it differs: every refresh applies the theme again, and an idle desk is
    // zero DOM mutations (the render contract) -- a write of the same value is still a mutation,
    // and it wakes everything that observes the root, the ink layer among them (#256).
    tokens.forEach(function (k) {
      if (cssVars[k]) {
        if (root.style.getPropertyValue(k) !== cssVars[k]) root.style.setProperty(k, cssVars[k]);
      } else if (root.style.getPropertyValue(k)) {
        root.style.removeProperty(k);
      }
    });
    // Written only when it changes (the render contract): every snapshot applies the theme again,
    // and an attribute set to the value it already has is still a mutation to every observer.
    attr(root, "data-theme", "custom");
  } else {
    tokens.forEach(function (k) { if (root.style.getPropertyValue(k)) root.style.removeProperty(k); });
    attr(root, "data-theme", null);
  }
}

/* A skin is one stylesheet; a VARIANT is that same stylesheet drawn against a different palette,
   selected by an attribute rather than by a second file. Nether and Overworld share every bevel and
   every sprite and differ in their colours, so shipping them as two stylesheets would be shipping
   the same art twice and letting the two copies drift. Switching variant therefore re-paints
   without a fetch, and only changing skin loads anything. */
function applySkin(skinName) {
  /** @type {HTMLLinkElement} */
  var link = document.head.querySelector("link[data-skin]");
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
  if (link.href !== href) link.href = href;   // re-assigning re-fetches and flashes the page
  // Written only when they change (the render contract's `attr`): every `/api/fleet` answer
  // carries the theme, and a desk that rewrote the same three attributes on each was an idle desk
  // making DOM mutations -- and an ink layer, which follows them, repainting for nothing (#254).
  attr(document.body, "data-skin", family);
  attr(document.body, "data-skin-variant", variant || null);
}

/* ------------------------------------------------------------ #219: how long a gesture took

   Every local gesture -- one the page can answer out of what it already has -- is marked at both
   ends, so "instant" is a number somebody can read rather than an adjective. The budget is 50ms,
   and `tests/test_fleet_instant.py` asserts it in a browser; the runbook records the laptop's.

   Wrapped, because `performance.mark` throws on a name it has already seen in some engines and a
   page that will not draw because it could not time itself is the worst possible trade. */
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

/* ------------------------------------------------------------ #351: how long a load took

   While the operator has switched measuring on (`fleet.loads.enabled`, #350), the server serves
   the desk and /settings with `data-measure="loads"` on <html>, and each such document posts ONE
   record of its own load as it goes (`pagehide`), which `ad-fleet engines` prints as the `loads`
   table. With the attribute absent -- the default, and always on /probe -- nothing here registers,
   observes or touches storage. Everything is read, nothing is written to the page: the paint and
   long-task times come from PerformanceObserver, and the ink's first frame from the counter the
   layer already keeps (`Ink.inspect().layer.renders`), because no entry type sees a WebGL frame.

   `from` is the note /settings leaves in sessionStorage as it goes: every page is served
   `Referrer-Policy: no-referrer` and a navigation entry reads `navigate` both for a cold open and
   for settings -> desk, so the page says where it came from. Every read is wrapped: a page that
   cannot time itself still works. */
var LOAD = { on: false, page: null, settled: "" };

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
    } catch (e) { /* no storage: a cold open, as far as the table can tell */ }
  }

  function ms(n) { return Math.round(n * 10) / 10; }
  function observe(type, each) {
    try {
      var types = PerformanceObserver.supportedEntryTypes || [];
      if (types.indexOf(type) < 0) return false;
      new PerformanceObserver(function (list) { list.getEntries().forEach(each); })
        .observe({ type: type, buffered: true });
      return true;
    } catch (e) { return false; }
  }
  observe("paint", function (entry) {
    if (entry.name === "first-paint") rec.first_paint_ms = ms(entry.startTime);
  });
  var longest = 0;
  var tasks = observe("longtask", function (entry) { longest = Math.max(longest, entry.duration); });
  var skinFirst = null;
  try {
    requestAnimationFrame(function () {
      try { skinFirst = document.body.dataset.skin || ""; } catch (e) { skinFirst = ""; }
    });
  } catch (e) { /* no frames, no first skin */ }

  /* The ink's first frame: read-only, each frame, until the layer has drawn once. It stops, leaving
     the field out, when the verdict is off or there is no layer, after 10 s, or at pagehide. It
     never writes to the page and never asks the layer to draw. */
  var inkDone = !desk;
  var inkFrom = 0;
  function lookForInk() {
    if (inkDone) return;
    try {
      if (!inkFrom) inkFrom = performance.now();
      if (performance.now() - inkFrom > 10000) { inkDone = true; return; }
      // Until ink.js has run, `window.Ink` is Chromium's own `Ink` interface (the delegated ink
      // trail API), a function with no `inspect`: the layer's front door is the one that has it.
      var ink = window["Ink"];
      if (!ink || typeof ink.inspect !== "function") ink = null;
      if (ink && !ink.enabled) { inkDone = true; return; }
      // The layer's canvas, which the layer adds (layer.js); it is in no page's markup.
      var canvas = document.querySelector("#ink");
      if (ink && canvas && canvas.hasAttribute("data-skin")) {
        var seen = ink.inspect();
        if (!seen || !seen.verdict || !seen.verdict.on || !seen.layer) { inkDone = true; return; }
        if (seen.layer.renders >= 1) {
          rec.ink_first_frame_ms = ms(performance.now());
          inkDone = true;
          return;
        }
      }
      requestAnimationFrame(lookForInk);
    } catch (e) { inkDone = true; }
  }
  lookForInk();

  var sent = false;
  window.addEventListener("pagehide", function () {
    inkDone = true;
    if (sent) return;
    sent = true;
    try {
      rec.shell = PARAMS.get("shell") || PARAMS.get("w") || "browser";
      var nav = /** @type {PerformanceNavigationTiming} */ (performance.getEntriesByType("navigation")[0]);
      rec.how = nav ? nav.type : "";
      rec.origin_ms = ms(performance.timeOrigin);
      if (tasks) rec.longest_task_ms = ms(longest);
      if (desk) {
        var fleet = performance.getEntriesByType("resource").filter(function (e) {
          try { return new URL(e.name).pathname === "/api/fleet"; } catch (x) { return false; }
        })[0];
        if (fleet) rec.fleet_ms = ms(/** @type {PerformanceResourceTiming} */ (fleet).responseEnd);
      }
      rec.skin_first = skinFirst === null ? "" : skinFirst;
      rec.skin_settled = LOAD.settled || "";
      rec.ua = String(navigator.userAgent || "").slice(0, 200);
      navigator.sendBeacon(q("/api/load"), new Blob([JSON.stringify(rec)], { type: "text/plain" }));
    } catch (e) { /* a load that cannot be sent is a load not counted, never a broken page */ }
  });
})();
