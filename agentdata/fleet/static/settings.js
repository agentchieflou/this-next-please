"use strict";

var backLink = document.getElementById("backbtn");
if (backLink) backLink.href = pageUrl("/");
var skillsLink = document.getElementById("skillsbtn");
if (skillsLink) skillsLink.href = pageUrl("/skills");

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
    var colourInput = document.getElementById("colour"), hexInput = document.getElementById("colour-hex");
    if (colourInput) colourInput.addEventListener("change", function () {
      choose(colourInput, { colour: String(colourInput.value || "").toUpperCase() });
    });
    if (hexInput) hexInput.addEventListener("change", function () {
      var said = String(hexInput.value || "").trim().replace(/^([0-9a-f]{6})$/i, "#$1").toUpperCase();
      if (/^#[0-9A-F]{6}$/.test(said)) choose(hexInput, { colour: said });
      else problem(hexInput, "six hex digits, as #3A7BD5");
    });
    var presets = document.getElementById("colour-presets");
    if (presets) {
      while (presets.firstChild) presets.removeChild(presets.firstChild);
      Object.keys(data.colour_presets || {}).forEach(function (name) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "segment preset";
        b.dataset.colour = data.colour_presets[name];
        b.style.borderLeft = "10px solid " + data.colour_presets[name];
        text(b, paletteTitle(name));
        b.title = name + " " + data.colour_presets[name] + " — a colour to start from";
        b.addEventListener("click", function () { choose(b, { colour: data.colour_presets[name] }); });
        presets.appendChild(b);
      });
    }
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
  if (found === name && name.indexOf("colors:") === 0) {
    var parts = name.split(":");
    found = "Colors · " + parts[1].charAt(0).toUpperCase() + parts[1].slice(1) + " #" + parts[2] + " (" + parts[3] + ")";
  }
  return found;
}

function isColors(value) {
  return String(value || "").indexOf("colors:") === 0;
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
  if (now && !isColors(value)) {
    applyThemeState(now);
    reflectTheme(now);
  } else if (now) {
    reflectTheme({ look: value, mode: now.mode, colour: body.colour || (was && was.colour),
                   theme: was && was.theme, skin: was && was.skin, css: was && was.css });
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
  var row = document.getElementById("colour-row");
  if (row) {
    row.hidden = !isColors(lookOf(cur));
    var colour = String(cur.colour || (themeData && themeData.colour) || "#3A7BD5").toUpperCase();
    var colourInput = document.getElementById("colour"), hexInput = document.getElementById("colour-hex");
    if (colourInput && colourInput.value.toUpperCase() !== colour) colourInput.value = colour;
    if (hexInput && hexInput.value.toUpperCase() !== colour) { hexInput.value = colour; problem(hexInput, ""); }
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

var scope = new URLSearchParams(location.search).get("agent") || "";
var lastData = null;
var SOURCE_WORDS = { agent: "this agent", fleet: "every agent", "default": "default" };

function scoped(body) {
  if (scope) body.agent = scope;
  return body;
}

function controlFor(key, spec, current, fleetOnly) {
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
    var body = { set: [{ key: key, value: value }] };
    post("settings", fleetOnly ? body : scoped(body)).then(function (res) {
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

function agentView(data) {
  return scope ? (data.agents || []).filter(function (a) { return a.repo === scope; })[0] || null : null;
}

function renderScope(data) {
  var sel = document.getElementById("scope");
  var note = document.getElementById("scopenote");
  if (!sel) return;
  var names = (data.agents || []).map(function (a) { return a.repo; });
  if (scope && names.indexOf(scope) < 0) scope = "";
  while (sel.options.length > 1) sel.remove(1);
  names.forEach(function (name) {
    var option = document.createElement("option");
    option.value = name;
    text(option, name);
    sel.appendChild(option);
  });
  sel.value = scope;
  var mine = agentView(data);
  var own = mine ? mine.rows.filter(function (r) { return r.source === "agent"; }).length : 0;
  text(note, mine ? (own ? own + " of its own; the rest are every agent's" : "nothing of its own yet: every row is every agent's")
                  : "pick an agent to see and change what it alone is launched with");
}

function sourceChip(source, title) {
  var chip = document.createElement("span");
  chip.className = "source source-" + source;
  text(chip, SOURCE_WORDS[source] || source);
  chip.title = title || "";
  return chip;
}

function inheritButton(keys, what) {
  var b = document.createElement("button");
  b.type = "button";
  b.className = "inherit";
  text(b, "use every agent's");
  b.title = "drop " + scope + "'s own " + what + "; it follows every agent's again";
  b.addEventListener("click", function () {
    post("settings", { agent: scope, inherit: keys }).then(function (res) {
      if (res && res.ok === false) { saidSaved("not saved — " + (res.error || "refused")); return; }
      saidSaved("saved — " + scope + " follows every agent");
      load();
    });
  });
  return b;
}

function configRow(host, spec, current, extra, fleetOnly) {
  var row = document.createElement("div");
  row.className = "setrow";
  var label = document.createElement("label");
  text(label, spec.label || spec.key);
  label.title = spec.key;
  var control = controlFor(spec.key, spec, current, fleetOnly);
  label.htmlFor = control.id;
  row.appendChild(label);
  row.appendChild(control);
  (extra || []).forEach(function (el) { row.appendChild(el); });
  var when = document.createElement("span");
  when.className = "when";
  text(when, spec.scope || "");
  when.title = "when a change here takes effect";
  row.appendChild(when);
  var why = document.createElement("span");
  why.className = "why inline";
  text(why, spec.why || "");
  row.appendChild(why);
  host.appendChild(row);
}

function renderConfig(data) {
  var hosts = {};
  Object.keys(SECTIONS).forEach(function (name) {
    var el = document.getElementById(SECTIONS[name]);
    if (el) while (el.firstChild) el.removeChild(el.firstChild);
    hosts[name] = el;
  });
  var mine = agentView(data);
  var specs = {};
  (data.editable || []).forEach(function (spec) { specs[spec.key] = spec; });
  if (mine) {
    (data.editable || []).filter(function (spec) { return spec.section !== "copilot"; }).forEach(function (spec) {
      var host = hosts[spec.section];
      if (host) configRow(host, spec, (data.current || {})[spec.key], [], true);
    });
    mine.rows.forEach(function (r) {
      var spec = specs[r.key];
      if (!spec || !hosts.copilot) return;
      var extra = [sourceChip(r.source, r.source === "agent" ? "every agent's: " + String(r.fleet) : "")];
      if (r.source === "agent") extra.push(inheritButton([r.key], spec.label));
      configRow(hosts.copilot, spec, r.value, extra);
    });
    return;
  }
  (data.editable || []).forEach(function (spec) {
    var host = hosts[spec.section] || hosts.copilot;
    if (!host) return;
    var extra = [];
    if ((spec.overridden_by || []).length) {
      extra.push(sourceChip("agent", "these agents set their own: " + spec.overridden_by.join(", ")));
      text(extra[0], "own value: " + spec.overridden_by.join(", "));
    }
    configRow(host, spec, (data.current || {})[spec.key], extra);
  });
}

function listRow(host, spec, rows) {
  var row = document.createElement("div");
  row.className = "setrow listrow";
  row.id = "list-" + spec.key.replace(/\./g, "-");
  var label = document.createElement("label");
  text(label, spec.label);
  label.title = spec.key;
  var input = document.createElement("input");
  input.type = "text";
  input.id = row.id + "-add";
  input.placeholder = spec.item === "dir" ? "an absolute folder" : "powershell, or shell(<command>)";
  label.htmlFor = input.id;
  var own = rows.filter(function (r) { return scope ? r.source === "agent" : r.source === "fleet"; })
                .map(function (r) { return r.item; });
  var save = function (items, said) {
    var body = scoped({ lists: [{ key: spec.key, items: items }] });
    post("settings", body).then(function (res) {
      if (res && res.ok === false) {
        problem(input, res.error + (res.hint ? " — " + res.hint : ""));
        return;
      }
      problem(input, "");
      input.value = "";
      saidSaved("saved — " + said + ", " + (spec.scope || "next turn"));
      load();
    });
  };
  var add = document.createElement("button");
  add.type = "button";
  add.className = "addone";
  text(add, "add");
  add.addEventListener("click", function () {
    if (!input.value.trim()) return;
    save(own.concat([input.value.trim()]), (scope ? scope + " " : "every agent ") + "also gets " + input.value.trim());
  });
  input.addEventListener("keydown", function (e) { if (e.key === "Enter") add.click(); });
  row.appendChild(label);
  row.appendChild(input);
  row.appendChild(add);
  var chips = document.createElement("ul");
  chips.className = "chips";
  rows.forEach(function (r) {
    var li = document.createElement("li");
    li.className = "chip" + (r.broad ? " broad" : "");
    var code = document.createElement("code");
    text(code, r.item);
    li.appendChild(code);
    li.appendChild(sourceChip(r.source, ""));
    if (r.broad) li.title = "broad: every command this tool can run (the deny floor still applies)";
    var mineToo = scope ? r.source === "agent" : r.source === "fleet";
    if (mineToo) {
      var x = document.createElement("button");
      x.type = "button";
      x.className = "dropone";
      text(x, "remove");
      x.title = "remove " + r.item;
      x.addEventListener("click", function () {
        save(own.filter(function (i) { return i !== r.item; }), r.item + " removed");
      });
      li.appendChild(x);
    }
    chips.appendChild(li);
  });
  row.appendChild(chips);
  var why = document.createElement("span");
  why.className = "why inline";
  text(why, spec.why || "");
  row.appendChild(why);
  host.appendChild(row);
}

function renderLists(data) {
  var host = document.getElementById("listrows");
  if (!host) return;
  while (host.firstChild) host.removeChild(host.firstChild);
  var mine = agentView(data);
  (data.lists || []).forEach(function (spec) {
    listRow(host, spec, mine ? (mine.lists[spec.key] || []) : (spec.rows || []));
  });
}

/**
 * @param {Object} body
 * @param {HTMLElement} note
 */
function copilotPost(body, note) {
  return post("copilot", body).then(function (res) {
    if (res && res.ok === false) {
      text(note, (res.error || "refused") + (res.hint ? " — " + res.hint : ""));
      return res;
    }
    text(note, "");
    saidSaved("saved to Copilot's own file");
    load();
    return res;
  });
}

/** @param {Object} r */
function shownValue(r) {
  if (r.value == null) return "";
  if (r.type === "list") return (r.value || []).join(", ");
  return typeof r.value === "string" ? r.value : JSON.stringify(r.value);
}

/** @param {Object} r  @param {HTMLElement} note */
function globalControl(r, note) {
  var el = document.createElement("input");
  el.id = "cg-" + r.key.replace(/\./g, "-");
  if (r.type === "bool") {
    el.type = "checkbox";
    el.checked = r.value === true;
    el.addEventListener("change", function () {
      copilotPost({ scope: "global", key: r.key, value: el.checked }, note);
    });
    return el;
  }
  el.type = "text";
  el.value = shownValue(r);
  el.placeholder = r.set ? "" : "not set";
  el.addEventListener("change", function () {
    copilotPost(el.value.trim() === "" ? { scope: "global", unset: r.key }
                                       : { scope: "global", key: r.key, value: el.value }, note);
  });
  return el;
}

function renderCopilotGlobal(data) {
  var g = data.copilot_global || {};
  var body = document.getElementById("cgrows");
  var note = /** @type {HTMLElement} */ (document.getElementById("cgnote"));
  if (!body) return;
  var rows = g.rows || [];
  text(document.getElementById("cgpath"), g.path || "~/.copilot/settings.json");
  text(document.getElementById("cgcount"), g.error ? "(unreadable)"
    : "(" + rows.filter(function (r) { return r.set; }).length + " set)");
  text(note, g.error ? g.error + (g.hint ? " — " + g.hint : "") : "");
  while (body.firstChild) body.removeChild(body.firstChild);
  rows.forEach(function (r) {
    var tr = document.createElement("tr");
    var key = document.createElement("td");
    var code = document.createElement("code");
    text(code, r.key);
    key.appendChild(code);
    var value = document.createElement("td");
    value.appendChild(globalControl(r, note));
    var about = document.createElement("td");
    text(about, r.about || "");
    var act = document.createElement("td");
    if (r.set) {
      var unset = document.createElement("button");
      unset.type = "button";
      unset.className = "dropone";
      text(unset, "unset");
      unset.title = "/config unset " + r.key;
      unset.addEventListener("click", function () { copilotPost({ scope: "global", unset: r.key }, note); });
      act.appendChild(unset);
    }
    tr.appendChild(key);
    tr.appendChild(value);
    tr.appendChild(about);
    tr.appendChild(act);
    body.appendChild(tr);
  });
}

/** @param {Object} a */
function approvalWords(a) {
  return [a.kind].concat(a.commandIdentifiers || []).join(" ");
}

function renderCopilotRepo(data) {
  var block = document.getElementById("crblock");
  var r = scope ? (data.copilot_repos || {})[scope] : null;
  hide(block, !r);
  if (!r) return;
  var note = /** @type {HTMLElement} */ (document.getElementById("crnote"));
  text(document.getElementById("crname"), scope);
  text(document.getElementById("crloc"), r.location || "?");
  text(document.getElementById("crpath"), r.path || "~/.copilot/permissions-config.json");
  text(note, r.error ? r.error + (r.hint ? " — " + r.hint : "") : "");
  var list = document.getElementById("crapprovals");
  while (list.firstChild) list.removeChild(list.firstChild);
  (r.tool_approvals || []).forEach(function (a) {
    var li = document.createElement("li");
    var code = document.createElement("code");
    text(code, approvalWords(a));
    li.appendChild(code);
    var drop = document.createElement("button");
    drop.type = "button";
    drop.className = "dropone";
    text(drop, "remove");
    drop.addEventListener("click", function () {
      copilotPost({ scope: "repo", repo: scope, remove: a }, note);
    });
    li.appendChild(drop);
    list.appendChild(li);
  });
  if (!(r.tool_approvals || []).length) {
    var none = document.createElement("li");
    text(none, "no approvals saved for this repository yet");
    list.appendChild(none);
  }
  var dirs = /** @type {HTMLTextAreaElement} */ (document.getElementById("crdirs"));
  if (document.activeElement !== dirs) dirs.value = (r.allowed_directories || []).join("\n");
}

function wireCopilot() {
  var cgNote = /** @type {HTMLElement} */ (document.getElementById("cgnote"));
  var crNote = /** @type {HTMLElement} */ (document.getElementById("crnote"));
  var key = /** @type {HTMLInputElement} */ (document.getElementById("cgkey"));
  var value = /** @type {HTMLInputElement} */ (document.getElementById("cgvalue"));
  var kind = /** @type {HTMLSelectElement} */ (document.getElementById("crkind"));
  var ids = /** @type {HTMLInputElement} */ (document.getElementById("crids"));
  var dirs = /** @type {HTMLTextAreaElement} */ (document.getElementById("crdirs"));
  if (!key) return;
  document.getElementById("cgset").addEventListener("click", function () {
    copilotPost({ scope: "global", key: key.value, value: value.value }, cgNote).then(function (res) {
      if (res && res.ok !== false) { key.value = ""; value.value = ""; }
    });
  });
  kind.addEventListener("change", function () { hide(ids, kind.value !== "commands"); });
  document.getElementById("cradd").addEventListener("click", function () {
    copilotPost({ scope: "repo", repo: scope, add: { kind: kind.value, identifiers: ids.value } }, crNote)
      .then(function (res) { if (res && res.ok !== false) ids.value = ""; });
  });
  document.getElementById("crdirsave").addEventListener("click", function () {
    copilotPost({ scope: "repo", repo: scope, directories: dirs.value.split("\n") }, crNote);
  });
}

function draw(data) {
  renderScope(data);
  renderConfig(data);
  renderLists(data);
  renderCopilotGlobal(data);
  renderCopilotRepo(data);
  var mine = agentView(data);
  var tools = (mine ? mine.tools : data.tools) || {};
  var allow = tools.allow || [];
  if (tools.permissions === "all") {
    allow = [{ pattern: "every tool a Copilot window would ask about", source: "all", broad: true }]
      .concat(allow);
  } else if (tools.permissions === "repo") {
    allow = [{ pattern: "what this repository's Copilot approvals allow", source: "repo" }].concat(allow);
  }
  renderPatterns("allowlist", "allowcount", allow);
  renderPatterns("denylist", "denycount", tools.deny);
}

var scopeSel = document.getElementById("scope");
if (scopeSel) {
  scopeSel.addEventListener("change", function () {
    scope = scopeSel.value;
    var u = new URL(location.href);
    if (scope) u.searchParams.set("agent", scope); else u.searchParams.delete("agent");
    history.replaceState(null, "", u.toString());
    if (lastData) draw(lastData);
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
    from.title = r.source === "all" ? "tool access is all: the agent runs with --allow-all-tools"
      : r.source === "repo" ? "tool access is repo: Copilot's own approvals for this repository's Git root"
      : r.source === "default" ? "shipped with agentdata"
      : r.source === "added" ? "also allowed or denied for every agent, from this page"
      : r.source === "agent" ? "this agent's own, from this page"
      : "from ~/.agentdata/config.json";
    if (r.broad) {
      li.className = "broad";
      li.title = "broad: every command this tool can run";
    }
    li.appendChild(from);
    list.appendChild(li);
  });
  if (count) text(count, "(" + (rows || []).length + ")");
}

function loadSkillsLine() {
  var line = document.getElementById("skillsline");
  if (!line) return Promise.resolve();
  return fetch(q("/api/skills")).then(function (r) { return r.json(); }).then(function (d) {
    var t = d && d.ok !== false && d.totals;
    if (!t) throw new Error("no");
    text(line, t.skills + (t.skills === 1 ? " skill" : " skills") + " installed, " + t.used_recently +
      " used in the last " + t.recent_days + " days \u2014 open the marketplace to see which, where and when.");
  }).catch(function () { text(line, "skills: unavailable"); });
}

function load() {
  if (!modelListAsked) modelListAsked = loadModelList();
  var settings = fetch(q("/api/settings")).then(function (r) { return r.json(); });
  loadSkillsLine();
  return Promise.all([settings, modelListAsked])
    .then(function (got) {
      var data = got[0];
      if (!data || data.ok === false) return;
      lastData = data;
      renderModels(data);
      draw(data);
      renderTierNote(data.tiers);
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
wireCopilot();
load();
connectTheme();
if (LOAD.on) {
  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem("fleet.load.from", "settings"); } catch (e) {}
  });
}
