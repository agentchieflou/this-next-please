"use strict";

var backLink = document.getElementById("backbtn");
if (backLink) backLink.href = pageUrl("/");

var pendingTheme = null;
var heardDuringWrite = null;
if (backLink) {
  backLink.addEventListener("click", function (e) {
    if (!pendingTheme || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    pendingTheme.then(go, go);
    function go() { location.href = backLink.href; }
  });
}

var savedTag = document.getElementById("saved");
var savedTimer = null;

function saidSaved(what) {
  if (!savedTag) return;
  text(savedTag, what || "saved");
  savedTag.hidden = false;
  if (savedTimer) clearTimeout(savedTimer);
  savedTimer = setTimeout(function () { savedTag.hidden = true; }, 1800);
}

function problem(el, message) {
  if (!el) return;
  el.classList.toggle("bad", !!message);
  el.title = message || "";
}

function loadThemes() {
  var lookSel = document.getElementById("look");
  var modeBtn = document.getElementById("mode");
  var followBtn = document.getElementById("mode-follow");
  return fetch(q("/api/themes")).then(function (r) { return r.json(); }).then(function (data) {
    while (lookSel.options.length) lookSel.remove(0);
    (data.genres || []).forEach(function (g) {
      var group = document.createElement("optgroup");
      group.label = g.title || g.name;
      (g.looks || []).forEach(function (l) {
        var option = document.createElement("option");
        option.value = l.value;
        text(option, l.title || l.value);
        option.title = (l.why || "") + sidesNote(l);
        group.appendChild(option);
      });
      lookSel.appendChild(group);
    });
    lookSel.addEventListener("change", function () { choose(lookSel, parseLook(lookSel.value)); });
    if (modeBtn) modeBtn.addEventListener("click", function () {
      choose(modeBtn, { mode: sideOn(themeNow) === "dark" ? "light" : "dark" });
    });
    if (followBtn) followBtn.addEventListener("click", function () {
      if ((themeNow && themeNow.mode) || "") choose(followBtn, { mode: "" });
    });
    themeData = data;
    if (themeNow) {
      reflectTheme(themeNow);
    } else if (data.current) {
      applyThemeState(data.current);
      reflectTheme(data.current);
    }
  }).catch(function () {});
}

var themeNow = null;
var themeData = null;
var themeSeq = 0;
var PALETTE_LOOK = "palette:";

function parseLook(value) {
  return { look: String(value || "") || PALETTE_LOOK + "none" };
}

function lookOf(cur) {
  if (cur && cur.look) return cur.look;
  if (cur && cur.skin && cur.skin !== "none") return cur.skin;
  return PALETTE_LOOK + ((cur && cur.theme) || "none");
}

function paletteCss(name) {
  var found = null;
  ((themeData && themeData.themes) || []).forEach(function (t) { if (t.name === name) found = t.css; });
  return found;
}

function lookRow(value) {
  var found = null;
  ((themeData && themeData.genres) || []).forEach(function (g) {
    (g.looks || []).forEach(function (l) { if (l.value === value) found = l; });
  });
  return found;
}

function sidesNote(l) {
  var sides = l.sides || {};
  var light = (sides.light || {}).base || "none", dark = (sides.dark || {}).base || "none";
  if (light === "none" && dark === "none") return "";
  return "  ·  light: " + light + "  ·  dark: " + dark;
}

function sideOn(cur) {
  var mode = (cur && cur.mode) || "";
  if (mode === "light" || mode === "dark") return mode;
  return DARK && DARK.matches ? "dark" : "light";
}

function looksOn(name) {
  var looks = [];
  ((themeData && themeData.genres) || []).forEach(function (g) {
    (g.looks || []).forEach(function (l) {
      if (!l.skin) return;
      var sides = l.sides || {};
      if ((sides.light && sides.light.base === name) || (sides.dark && sides.dark.base === name)) {
        looks.push((g.title || g.name) + " · " + l.title);
      }
    });
  });
  return looks;
}

function resolveLook(value, mode, pick) {
  var row = lookRow(value);
  if (!row) return null;
  var sides = {};
  ["light", "dark"].forEach(function (side) {
    var v = (row.sides || {})[side] || {};
    var base = v.base || "none";
    sides[side] = { variant: v.variant || "", skin: v.skin || "none", theme: base, css: paletteCss(base) || {} };
  });
  if (pick && !mode && row.own) mode = row.own;
  if (mode === "light" || mode === "dark") {
    return { look: value, mode: mode, skin: sides[mode].skin, theme: sides[mode].theme, css: sides[mode].css };
  }
  var family = row.skin ? row.skin + ":auto" : "none";
  return { look: value, mode: "", skin: family, theme: sides.dark.theme, css: sides.dark.css, auto: sides };
}

function lookTitle(value) {
  var found = "";
  ((themeData && themeData.genres) || []).forEach(function (g) {
    (g.looks || []).forEach(function (l) { if (l.value === value) found = (g.title || g.name) + " · " + l.title; });
  });
  return found;
}

function paletteTitle(name) {
  var found = name;
  ((themeData && themeData.themes) || []).forEach(function (t) { if (t.name === name) found = t.title || name; });
  if (found === name && name.indexOf("flip:") === 0) found = paletteTitle(name.slice(5)) + "'s other side";
  return found;
}

function looksLine(cur) {
  var value = lookOf(cur), side = sideOn(cur), mode = (cur && cur.mode) || "";
  var how = (mode ? "pinned to its " : "following the system, now its ") + side + " side";
  if (value === PALETTE_LOOK + "none") return "the system's own colours, and the plain page";
  var palette = (cur && cur.theme) || "none";
  var row = lookRow(value);
  if (row && (row.sides || {})[side]) palette = row.sides[side].base || palette;
  if (value.indexOf(PALETTE_LOOK) === 0) {
    var drawn = looksOn(palette);
    return "palette " + paletteTitle(palette) + " on the plain page, " + how + ", shared with this project's terminal" +
      (drawn.length ? " — also drawn by " + drawn.join(", ") : "");
  }
  return lookTitle(value) + ", " + how + " — palette " + paletteTitle(palette) + ", shared with this project's terminal";
}

function choose(control, body) {
  var was = themeNow;
  var mark = gesture(body.look ? "theme:look" : "theme:mode");
  var value = body.look || lookOf(was);
  var mode = body.mode !== undefined ? body.mode : ((was && was.mode) || "");
  var now = resolveLook(value, mode, !!body.look);
  if (now) {
    applyThemeState(now);
    reflectTheme(now);
  }
  settle(mark);
  problem(control, "");
  heardDuringWrite = null;
  body.seq = themeSeq = Math.max(Date.now(), themeSeq + 1);
  var write = pendingTheme = post("theme", body).then(function (res) {
    if (res && res.seq > themeSeq) themeSeq = res.seq;
    if (pendingTheme !== write) return;
    var heard = heardDuringWrite;
    heardDuringWrite = null;
    if (res && res.ok !== false) {
      applyThemeState(res);
      reflectTheme(res);
      problem(control, "");
      saidSaved();
      return;
    }
    putBack(heard || was);
    problem(control, ((res && res.error) || "refused") + (res && res.hint ? " — " + res.hint : ""));
  }, function () {
    if (pendingTheme !== write) return;
    var heard = heardDuringWrite;
    heardDuringWrite = null;
    putBack(heard || was);
    problem(control, "the server did not answer — nothing was saved");
  });
  write.then(function () { if (pendingTheme === write) pendingTheme = null; });
  return write;
}

function putBack(was) {
  if (!was) return;
  applyThemeState(was);
  reflectTheme(was);
}

function reflectTheme(cur) {
  if (!cur) return;
  themeNow = cur;
  if (cur.seq > themeSeq) themeSeq = cur.seq;
  var lookSel = document.getElementById("look");
  if (lookSel) {
    lookSel.value = lookOf(cur);
    if (lookSel.selectedIndex < 0) lookSel.value = PALETTE_LOOK + "none";
    [lookSel].forEach(function (sel) { if (sel && sel.selectedIndex < 0) sel.selectedIndex = 0; });
  }
  var side = sideOn(cur), mode = cur.mode || "";
  var modeBtn = document.getElementById("mode");
  if (modeBtn) {
    text(modeBtn, side === "dark" ? "Dark" : "Light");
    attr(modeBtn, "aria-checked", side === "dark" ? "true" : "false");
    modeBtn.classList.toggle("active", !!mode);
  }
  var followBtn = document.getElementById("mode-follow");
  if (followBtn) {
    attr(followBtn, "aria-pressed", mode ? "false" : "true");
    followBtn.classList.toggle("active", !mode);
  }
  if (themeData) text(document.getElementById("palette-looks"), looksLine(cur));
}

var modelList = null;
var modelListAsked = null;
var modelsHeard = "";
var modelSnap = null;
var fleetPicker = null;
var rowPickers = new WeakMap();
var landing = location.hash.indexOf("#model-") === 0;

function loadModelList() {
  return fetch(q("/api/models")).then(function (r) { return r.json(); }).then(function (data) {
    if (data && data.ok !== false) modelList = data;
  }).catch(function () {});
}

function modelEntry(id) {
  var found = null;
  ((modelList && modelList.models) || []).forEach(function (m) { if (m && m.id === id) found = m; });
  return found;
}

function modelLabel(id) {
  var m = modelEntry(id);
  return (m && m.label) || id;
}

function ago(iso) {
  var at = Date.parse(iso || "");
  if (isNaN(at)) return "";
  var min = Math.max(0, Math.round((Date.now() - at) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return min + " min ago";
  return min < 48 * 60 ? Math.round(min / 60) + "h ago" : Math.round(min / 1440) + " days ago";
}

function listLine(cat) {
  var meta = cat && cat.meta;
  if (!meta) return "";
  var line = meta.source === "shipped"
    ? "shipped list — copilot could not be asked" + (meta.why ? " (" + meta.why + ")" : "")
    : "list: copilot " + (meta.cli_version || "?") +
      (meta.fetched_at ? " · checked " + ago(meta.fetched_at) : "");
  return line + (meta.account ? " · account: " + meta.account : "");
}

function fleetDefault() {
  var f = (modelSnap && modelSnap.fleet) || {};
  return { model: String(f.model || ""), effort: String(f.effort || "") };
}

function inheritWords(opts) {
  var f = fleetDefault();
  opts.emptyLabel = "inherit · " + (f.model ? modelLabel(f.model) : "CLI default");
  opts.emptyTitle = f.model ? "no model of its own: the fleet-wide default, " + f.model
                            : "no model of its own: no --model is passed and the CLI chooses";
}

function renderModels(data) {
  modelSnap = data.model || {};
  drawModels();
  var note = document.getElementById("modelnote");
  if (note) {
    text(note, (modelSnap.repos || []).length
      ? "Model and effort inherit separately: each “inherit” follows the fleet-wide default above " +
        "for its own half, and “inherit both” clears a row. “CLI default” there passes no flag at all."
      : "No repositories are registered yet — `ad-fleet repo add <path>`.");
  }
}

function drawModels() {
  if (!modelSnap) return;
  var host = document.getElementById("fleetpicker");
  if (host && !fleetPicker) {
    fleetPicker = createModelPicker({ variant: "full", label: "every agent",
                                      emptyLabel: "CLI default",
                                      emptyTitle: "pass no --model; the CLI chooses",
                                      onPick: pickFleet });
    host.appendChild(fleetPicker);
  }
  if (fleetPicker) {
    drawModelPicker(fleetPicker, { catalogue: modelList || {}, current: fleetDefault() });
  }
  patchList(document.getElementById("modelrows"), modelSnap.repos || [],
            function (r) { return r.repo; }, modelRow, paintModelRow);
  text(document.getElementById("modellist"), listLine(modelList));
}

function modelRow(r) {
  var tr = document.createElement("tr");
  var p = { repo: r.repo, row: tr, full: null, fullOpts: null, expand: null };
  p.opts = { variant: "compact", label: r.repo, onPick: function (pick) { pickRepo(p, pick); },
             onMore: function () {
               if (p.expand && !p.expand.hidden) closeExpansion(p, true); else openExpansion(p, true);
             } };
  p.compact = createModelPicker(p.opts);
  p.both = document.createElement("button");
  p.both.type = "button";
  p.both.className = "linkbtn inherit-both";
  p.both.textContent = "inherit both";
  p.both.title = "clear this repository's model and effort: both follow the fleet's again";
  p.both.hidden = true;
  p.both.addEventListener("click", function () {
    saveModel({ models: [{ repo: p.repo, model: "", effort: "" }] }, "",
              { model: "", effort: "", toolbar: "both", droppedEffort: "" }, "", p);
  });
  tr.id = "model-" + r.repo;
  var name = document.createElement("td"), model = document.createElement("td");
  model.className = "modelcell";
  model.append(p.compact, p.both);
  tr.append(name, model, document.createElement("td"), document.createElement("td"));
  rowPickers.set(tr, p);
  return tr;
}

function paintModelRow(tr, r) {
  var p = rowPickers.get(tr), cells = tr.children, f = fleetDefault();
  if (!p) return;
  text(cells[0], r.repo);
  inheritWords(p.opts);
  if (p.fullOpts) inheritWords(p.fullOpts);
  var state = { catalogue: modelList || {}, current: { model: r.model || "", effort: r.effort || "" },
                inherited: { model: f.model, effort: f.effort }, actual: r.actual || "",
                quick: [f.model, r.actual || ""] };
  drawModelPicker(p.compact, state);
  if (p.full) drawModelPicker(p.full, state);
  hide(p.both, !r.model && !r.effort);
  attr(moreOf(p), "aria-expanded", p.expand && !p.expand.hidden ? "true" : "false");
  var effortFrom = r.effort_source && r.effort_source !== r.source && r.resolved_effort
    ? " · effort from " + r.effort_source : "";
  text(cells[2], r.source + effortFrom);
  attr(cells[2], "title", r.source === "cli-auto"
    ? "no model is configured, so no --model flag is passed and the CLI chooses" + effortFrom
    : "model resolved from " + r.source + effortFrom);
  text(cells[3], r.actual || "—");
  attr(cells[3], "title", r.actual ? "what the last turn actually ran on, from the event stream"
                                   : "no turn has reported a model for this repository yet");
}

function rowOf(repo) {
  var found = null;
  ((modelSnap && modelSnap.repos) || []).forEach(function (r) { if (r.repo === repo) found = r; });
  return found;
}

function moreOf(p) { return p.compact.querySelector("button.mp-more"); }

function focusPressed(root) {
  var b = root && (root.querySelector('.mp-models button.pill[aria-pressed="true"]') ||
                   root.querySelector(".mp-models button.pill"));
  if (b) b.focus();
}

function openExpansion(p, focus) {
  Array.prototype.forEach.call(document.querySelectorAll("#modelrows .mp-expand"), function (el) {
    var other = rowPickers.get(el.closest("tr"));
    if (other && other !== p) closeExpansion(other, false);
  });
  if (!p.full) {
    p.fullOpts = { variant: "full", label: p.repo, onPick: function (pick) { pickRepo(p, pick); } };
    p.full = createModelPicker(p.fullOpts);
    p.expand = document.createElement("div");
    p.expand.className = "mp-expand";
    p.expand.hidden = true;
    p.expand.appendChild(p.full);
    p.expand.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      e.stopPropagation();
      closeExpansion(p, true);
    });
    p.row.children[1].appendChild(p.expand);
  }
  hide(p.expand, false);
  var r = rowOf(p.repo);
  if (r) paintModelRow(p.row, r);
  if (focus) focusPressed(p.full);
}

function closeExpansion(p, focusMore) {
  if (!p.expand || p.expand.hidden) return;
  hide(p.expand, true);
  attr(moreOf(p), "aria-expanded", "false");
  if (focusMore && moreOf(p)) moreOf(p).focus();
}

function landOnRow() {
  if (!landing) return;
  landing = false;
  var repo;
  try { repo = decodeURIComponent(location.hash.slice(7)); } catch (e) { return; }
  var tr = document.getElementById("model-" + repo), p = tr && rowPickers.get(tr);
  if (!p) return;
  openExpansion(p, false);
  tr.scrollIntoView({ block: "center" });
  focusPressed(p.full);
}

function pickFleet(pick) {
  saveModel({ model: pick.model, effort: pick.effort }, pick.model, pick, "", null);
}

function pickRepo(p, pick) {
  var entry = pick.toolbar === "effort" ? { repo: p.repo, effort: pick.effort }
                                        : { repo: p.repo, model: pick.model };
  saveModel({ models: [entry] }, entry.model || "", pick, "", p);
}

function saveModel(body, model, pick, pinned, p) {
  var inside = !!(p && p.expand && p.expand.contains(document.activeElement));
  return post("settings", body).then(function (res) {
    if (res && res.ok === false) {
      refuse(p, res.error + (res.hint ? " — " + res.hint : ""));
      return;
    }
    problem(otherBox(p), "");
    return load().then(function () {
      return model && !modelEntry(model) ? loadModelList().then(drawModels) : null;
    }).then(function () {
      saidSaved(savedWords(model, pick, pinned));
      if (!p) return;
      closeExpansion(p, false);
      if (inside) focusPressed(p.compact);
    });
  }, function () { refuse(p, "the server did not answer — nothing was saved"); });
}

function otherBox(p) {
  var picker = p ? p.full : fleetPicker;
  return picker ? picker.querySelector("input.mp-other") : null;
}

function refuse(p, message) {
  if (p && (!p.expand || p.expand.hidden)) openExpansion(p, false);
  var box = otherBox(p);
  if (box && box.hidden) {
    var open = box.parentElement.querySelector("button.mp-otherbtn");
    if (open) open.click();
  }
  problem(box, message);
}

function savedWords(model, pick, pinned) {
  var m = model ? modelEntry(model) : null, said = [];
  if (m && m.offered === false) {
    var ver = ((modelList && modelList.meta) || {}).cli_version;
    said.push("not offered by copilot" + (ver ? " " + ver : "") + ", the turn may fail at start");
  }
  return "saved — " + (said.length ? said.join(" · ") : "takes effect on the next turn");
}

var modelRefresh = document.getElementById("modelrefresh");
if (modelRefresh) {
  modelRefresh.addEventListener("click", function () {
    post("models", { refresh: true }).then(function (res) {
      saidSaved(res && res.ok === false ? "not asked — " + (res.error || "refused")
                                        : "asking copilot for its model list");
    }, function () { saidSaved("the server did not answer — copilot was not asked"); });
  });
}

function controlFor(key, spec, current) {
  var el;
  if (spec.type === "bool") {
    el = document.createElement("input");
    el.type = "checkbox";
    el.checked = !!current;
  } else if (spec.type === "enum") {
    el = document.createElement("select");
    (spec.choices || []).forEach(function (c) {
      var option = document.createElement("option");
      option.value = c;
      text(option, c);
      el.appendChild(option);
    });
    el.value = String(current == null ? "" : current);
    if (el.selectedIndex < 0) el.selectedIndex = 0;
  } else {
    el = document.createElement("input");
    el.type = spec.type === "int" || spec.type === "float" ? "number" : "text";
    if (spec.type === "int") el.step = "1";
    if (spec.min != null) el.min = String(spec.min);
    if (spec.max != null) el.max = String(spec.max);
    el.value = current == null ? "" : String(current);
  }
  el.id = "cfg-" + key.replace(/\./g, "-");
  el.addEventListener("change", function () {
    var value = spec.type === "bool" ? el.checked : el.value;
    post("settings", { set: [{ key: key, value: value }] }).then(function (res) {
      if (res && res.ok === false) {
        problem(el, res.error + (res.hint ? " — " + res.hint : ""));
        return;
      }
      problem(el, "");
      saidSaved("saved — " + (spec.scope || "in effect"));
      load();
    });
  });
  return el;
}

var SECTIONS = { copilot: "cfgrows", appearance: "tierrows" };

function renderConfig(data) {
  var hosts = {};
  Object.keys(SECTIONS).forEach(function (name) {
    var el = document.getElementById(SECTIONS[name]);
    if (el) while (el.firstChild) el.removeChild(el.firstChild);
    hosts[name] = el;
  });
  (data.editable || []).forEach(function (spec) {
    var host = hosts[spec.section] || hosts.copilot;
    if (!host) return;
    var row = document.createElement("div");
    row.className = "setrow";
    var label = document.createElement("label");
    text(label, spec.label || spec.key);
    label.title = spec.key;
    var control = controlFor(spec.key, spec, (data.current || {})[spec.key]);
    label.htmlFor = control.id;
    row.appendChild(label);
    row.appendChild(control);
    var scope = document.createElement("span");
    scope.className = "when";
    text(scope, spec.scope || "");
    scope.title = "when a change here takes effect";
    row.appendChild(scope);
    var why = document.createElement("span");
    why.className = "why inline";
    text(why, spec.why || "");
    row.appendChild(why);
    host.appendChild(row);
  });
}

function renderTierNote(tiers) {
  var note = document.getElementById("tiernote");
  if (!note) return;
  var why = (tiers && tiers.invalid) || "";
  text(note, why ? "The desk is drawing at the defaults: " + why + "." : "");
  note.hidden = !why;
}

function renderPatterns(listId, countId, rows) {
  var list = document.getElementById(listId);
  var count = document.getElementById(countId);
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  (rows || []).forEach(function (r) {
    var li = document.createElement("li");
    var code = document.createElement("code");
    text(code, r.pattern);
    li.appendChild(code);
    var from = document.createElement("span");
    from.className = "from";
    text(from, r.source);
    from.title = r.source === "default"
      ? "shipped with agentdata"
      : "from ~/.agentdata/config.json";
    li.appendChild(from);
    list.appendChild(li);
  });
  if (count) text(count, "(" + (rows || []).length + ")");
}

function load() {
  if (!modelListAsked) modelListAsked = loadModelList();
  var settings = fetch(q("/api/settings")).then(function (r) { return r.json(); });
  return Promise.all([settings, modelListAsked])
    .then(function (got) {
      var data = got[0];
      if (!data || data.ok === false) return;
      renderModels(data);
      renderConfig(data);
      renderTierNote(data.tiers);
      renderPatterns("allowlist", "allowcount", (data.tools || {}).allow);
      renderPatterns("denylist", "denycount", (data.tools || {}).deny);
      landOnRow();
    }).catch(function () {});
}

function connectTheme() {
  try {
    var stream = new EventSource(q("/api/events", { frames: "theme" }));
    stream.addEventListener("theme", function (m) {
      try {
        var d = JSON.parse(m.data);
        if (pendingTheme) { heardDuringWrite = d; return; }
        applyThemeState(d);
        reflectTheme(d);
      } catch (e) {}
    });
    stream.addEventListener("models", function (m) {
      try {
        var d = JSON.parse(m.data);
        if (!d || !d.version || d.version === modelsHeard) return;
        modelsHeard = d.version;
        loadModelList().then(drawModels);
      } catch (e) {}
    });
  } catch (e) {}
}

loadThemes().then(function () { LOAD.settled = document.body.dataset.skin || ""; });
load();
connectTheme();
if (LOAD.on) {
  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem("fleet.load.from", "settings"); } catch (e) {}
  });
}
