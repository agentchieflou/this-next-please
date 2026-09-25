/* The settings page.

   A page and not a popover, because the palette stopped being the only thing here: the model each
   agent runs and the flags the Copilot CLI is launched with are settings too, and none of them fits
   behind a button on a toolbar that is meant to be about the agents.

   It shares `common.js` with the desk -- the token, `q`, `post`, `text`, and the two painters -- and
   `picker.js`, the model picker (#362), and nothing else. It deliberately does NOT load `app.js`:
   that file boots a desk (an EventSource feeding tiles, a fifteen-second `loadDesk`, a `place()`
   that rewrites `document.body` several times a second) and none of it has any business running
   under somebody editing a dropdown.

   It does open one EventSource of its own, for two frames. The `theme` frame is emitted whenever
   `config.json` changes, so a palette set from `ad-theme` in a terminal, or from another window,
   repaints this page instead of leaving its pickers saying something that is no longer true. That
   was bug #195 on the desk, and a settings page with no stream is where it would come back. The
   `models` frame says the model list changed (#361), and the model pickers are drawn again. */

"use strict";

/* Every link out of here has to carry the run token: `_authorized` reads it from the query string
   alone, so a static href in the markup is a 403 that looks like a dead button. */
var backLink = document.getElementById("backbtn");
if (backLink) backLink.href = pageUrl("/");

/* The last theme write still in flight (#346). Leaving before it has answered could land on a desk
   served the old skin, so a plain click waits for the answer -- either answer -- and then goes.
   `href` is read at click time, so #344's `pageUrl` is what is followed. No timer. */
var pendingTheme = null;
/* A `theme` frame heard while a write is in flight is the server's word from before that write (the
   stream's first frame can land after a pick on a slow start). It is kept, not painted: painted, it
   put the old theme back over the pick; kept, it is what a refusal goes back to. */
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

/* ------------------------------------------------------------------------------------- theming */

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
      // Its title, not its slug (#393). The tooltip adds what is drawn on it, as a supplement only:
      // it is hover-only, and never seen while a skin has the picker disabled -- `#palette-looks`
      // under the picker is where that is said.
      text(option, t.title || t.name);
      var looks = looksOn(data, t.name), why = (data.palette_only || {})[t.name];
      attr(option, "title", (t.why || t.title || t.name) + "  ·  " + (looks.length
        ? "drawn by " + looks.join(", ") : "palette only" + (why ? ": " + why : "")));
      themeSel.appendChild(option);
    });
    themeSel.addEventListener("change", function () { choose(themeSel, { theme: themeSel.value }); });

    /* One control, not two. A variant is not independent of its skin -- "Nether" means nothing on
       its own, and a second picker offering it beside Farmstead would be offering a combination
       that does not exist. Grouping them says the same thing the model does: pick a skin, and its
       ground comes with it. A skin with one variant lists as a single option. */
    while (skinSel.options.length > 1) skinSel.remove(1);
    (data.skins || []).forEach(function (k) {
      if (k.name === "none") return;
      var vs = k.variants || [];
      if (vs.length < 2) {
        var single = document.createElement("option");
        single.value = vs.length ? vs[0].full : k.name;
        text(single, k.title || k.name);
        single.title = (k.why || "") + (k.base ? "  ·  palette: " + k.base : "");
        skinSel.appendChild(single);
        return;
      }
      var group = document.createElement("optgroup");
      group.label = k.title || k.name;
      vs.forEach(function (v) {
        var option = document.createElement("option");
        option.value = v.full;
        text(option, v.title || v.name);
        option.title = (v.why || "") + "  ·  palette: " + v.base;
        group.appendChild(option);
      });
      skinSel.appendChild(group);
    });
    skinSel.addEventListener("change", function () { choose(skinSel, { skin: skinSel.value }); });
    themeData = data;
    // What is chosen, now that there is something to choose from. `themeNow` is whatever the
    // stream said while these options did not exist yet; it wins, because it is the later word,
    // and this answer paints nothing over it. Otherwise `current` is the stream's own payload
    // (#346), painted only when it carries css: a `current` without css is "not known", never
    // "no palette" -- read as the latter, it wiped the palette the stream had just applied.
    if (themeNow) {
      reflectTheme(themeNow);
    } else if (data.current) {
      if (data.current.css || data.current.theme === "none") {
        applyTheme(data.current.css, data.current.theme);
        applySkin(data.current.skin);
      }
      reflectTheme(data.current);
    }
  }).catch(function () { /* themes are decoration; the page works without them */ });
}

var themeNow = null;                  // the last word on what this page is wearing, from either path
var themeData = null;                 // the `/api/themes` answer: every palette's css, every skin's base

function paletteCss(name) {
  var found = null;
  ((themeData && themeData.themes) || []).forEach(function (t) { if (t.name === name) found = t.css; });
  return found;
}

function skinBase(full) {
  var base = null;
  ((themeData && themeData.skins) || []).forEach(function (k) {
    if (k.name === full && k.base) base = k.base;
    (k.variants || []).forEach(function (v) { if (v.full === full) base = v.base; });
  });
  return base;
}

/* The looks drawn on a palette (#393), from an `/api/themes` answer: "Glass · Smoke" for every skin
   variant whose base it is, in the skin picker's order. None means the palette is the plain page
   only -- `palette_only` says why -- and it is still an ordinary palette to choose. */
function looksOn(data, name) {
  var looks = [];
  ((data && data.skins) || []).forEach(function (k) {
    (k.variants || []).forEach(function (v) { if (v.base === name) looks.push(lookName(k, v)); });
  });
  return looks;
}

function lookName(k, v) { return (k.title || k.name) + " · " + (v.title || v.name); }

/* The line under the palette picker: what is drawn on the palette, or, while a skin is on, the look
   the palette comes from -- words a keyboard, a touch screen and a disabled picker all show, which
   an option's tooltip is not. */
function looksLine(skin, palette) {
  if (skin && skin !== "none") {
    var from = skin;
    ((themeData && themeData.skins) || []).forEach(function (k) {
      (k.variants || []).forEach(function (v) {
        if (v.full === skin || (k.name === skin && v.name === k.default)) from = lookName(k, v);
      });
    });
    return "from " + from;
  }
  var looks = looksOn(themeData, palette);
  if (looks.length) return "drawn by " + looks.join(", ");
  var why = ((themeData && themeData.palette_only) || {})[palette];
  return "palette only: the plain page" + (why ? " — " + why : "");
}

/* Paint, post, reconcile (#346). A pick is painted in the task that made it, from the css the server
   already sent with `/api/themes` -- no palette maths here -- and only then posted. The answer is
   the stream's own payload: equal values write nothing; a refusal puts back what was worn before
   and says why on the control. */
function choose(select, body) {
  var themeSel = document.getElementById("theme");
  var was = themeNow;
  var mark;
  if ("skin" in body) {
    mark = gesture("theme:skin");
    var full = body.skin || "none";
    if (full === "none") {
      // The palette stays the one the skin brought: the server keeps it as the default.
      var keep = themeSel ? themeSel.value : "none";
      applySkin("none");
      reflectTheme({ theme: keep, skin: "none", css: paletteCss(keep) || {} });
    } else {
      var base = skinBase(full);
      var css = base ? paletteCss(base) : null;
      if (css) applyTheme(css, base);
      applySkin(full);
      reflectTheme({ theme: base || (themeSel && themeSel.value), skin: full, css: css || {} });
    }
  } else {
    mark = gesture("theme:palette");
    var name = body.theme || "none";
    var pcss = name === "none" ? null : paletteCss(name);
    if (pcss) applyTheme(pcss, name); else applyTheme(null, "none");
    reflectTheme({ theme: pcss ? name : "none", skin: "none", css: pcss || {} });
  }
  settle(mark);
  problem(select, "");
  heardDuringWrite = null;
  var write = pendingTheme = post("theme", body).then(function (res) {
    if (pendingTheme !== write) return;          // a later pick is in flight; its answer decides
    var heard = heardDuringWrite;
    heardDuringWrite = null;
    if (res && res.ok !== false) {
      if (res.css || res.theme === "none") applyTheme(res.css, res.theme);
      applySkin(res.skin);
      reflectTheme(res);
      problem(select, "");
      saidSaved();
      return;
    }
    putBack(heard || was);
    problem(select, ((res && res.error) || "refused") + (res && res.hint ? " — " + res.hint : ""));
  }, function () {
    if (pendingTheme !== write) return;
    var heard = heardDuringWrite;
    heardDuringWrite = null;
    putBack(heard || was);
    problem(select, "the server did not answer — nothing was saved");
  });
  write.then(function () { if (pendingTheme === write) pendingTheme = null; });
  return write;
}

function putBack(was) {
  if (!was) return;
  if (was.css || was.theme === "none") applyTheme(was.css, was.theme);
  applySkin(was.skin);
  reflectTheme(was);
}

/* One place that puts the server's answer into the two controls, so a change made in the terminal
   or in another window shows up here rather than leaving the picker saying something else. */
function reflectTheme(cur) {
  if (!cur) return;
  themeNow = cur;
  var themeSel = document.getElementById("theme");
  var skinSel = document.getElementById("skin");
  if (themeSel && cur.theme) themeSel.value = cur.theme;
  if (skinSel) skinSel.value = cur.skin || "none";
  // A saved name that is no longer a palette leaves a select showing nothing at all, which is the
  // one thing a picker may never do: the operator cannot see what is on, or that anything is wrong.
  [themeSel, skinSel].forEach(function (sel) { if (sel && sel.selectedIndex < 0) sel.selectedIndex = 0; });
  /* While a skin is on, the palette is the skin's -- so the palette picker shows what is being
     rendered and says why it is not taking instructions, rather than accepting a choice the server
     would then override. Turning the skin off hands it back. */
  if (themeSel) {
    var bound = !!(cur.skin && cur.skin !== "none");
    if (bound && !themeSel.disabled && document.activeElement === themeSel && skinSel) skinSel.focus();
    themeSel.disabled = bound;
    themeSel.title = bound
      ? "the palette comes from the skin — choose “no skin” to pick one yourself"
      : "palette — shared with this project's terminal";
  }
  // What is drawn on it (#393), said here and so on every pick too: `choose` reflects a palette in
  // the task that picked it. Before `/api/themes` has answered there is nothing to say it from.
  if (themeData) text(document.getElementById("palette-looks"),
                      looksLine(cur.skin, themeSel ? themeSel.value : cur.theme));
}

/* -------------------------------------------------------------------------------------- models */

/* Pressed, not typed (#367). Which names the installed Copilot CLI takes is measured now: `GET
   /api/models` is what `copilot help config` listed (#360), cached, else the list this package ships,
   and a page never waits on the CLI for it. The list is a suggestion and never a gate: `other…` in
   a row's expansion is the one place a name is typed, a name the CLI does not offer is saved and the
   saved tag says so, and the CLI stays the validator at the agent's next turn.

   `picker.js` draws every picker here (#362): a full one for the fleet-wide default, and a compact
   one per repository, whose `more…` opens a full one in the same cell. The picker never posts; this
   page applies the inherit rule. Inherit is the entry removed, never kept as `{}`. And `model_for`
   reads a repository's entry as a whole, so an effort pressed on a repository with no entry pins the
   model it inherits along with it: alone, the effort would run on the CLI's model, not the fleet's. */
var modelList = null;                  // the `/api/models` answer every picker here is drawn from
var modelListAsked = null;             // its one fetch on load, which the first `load()` waits for
var modelsHeard = "";                  // the last `models` frame's `version` (#361)
var modelSnap = null;                  // the `model` block of the last `/api/settings`
var fleetPicker = null;
var rowPickers = new WeakMap();        // a row's <tr> -> its pickers, its expansion, their options
var landing = location.hash.indexOf("#model-") === 0;   // the model card's link, acted on once

function loadModelList() {
  return fetch(q("/api/models")).then(function (r) { return r.json(); }).then(function (data) {
    if (data && data.ok !== false) modelList = data;
  }).catch(function () { /* no list: the pickers offer the default and `other…` */ });
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

/* The line over the table: where the list came from, and how old it is. */
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

/* A row's `inherit` pill says what it inherits. The picker reads its options at every draw. */
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
      ? "“inherit” follows the fleet-wide default above; “CLI default” there passes no flag at all."
      : "No repositories are registered yet — `ad-fleet repo add <path>`.");
  }
}

/* Patched, never rebuilt: the keyboard, an open expansion and a half-typed `other…` survive every
   `load()` after a save. */
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
  tr.id = "model-" + r.repo;
  var name = document.createElement("td"), model = document.createElement("td");
  model.className = "modelcell";
  model.appendChild(p.compact);
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
  attr(moreOf(p), "aria-expanded", p.expand && !p.expand.hidden ? "true" : "false");
  text(cells[2], r.source);
  attr(cells[2], "title", r.source === "cli-auto"
    ? "nothing is configured, so no --model flag is passed and the CLI chooses"
    : "resolved from " + r.source);
  /* Configured is not served. The tenant may pin a model, and a page that reported only what was
     asked for would show a setting that is not what ran. This column is what the stream said the
     last turn actually used. */
  text(cells[3], r.actual || "—");
  attr(cells[3], "title", r.actual ? "what the last turn actually ran on, from the event stream"
                                   : "no turn has reported a model for this repository yet");
}

function rowOf(repo) {
  var found = null;
  ((modelSnap && modelSnap.repos) || []).forEach(function (r) { if (r.repo === repo) found = r; });
  return found;
}

function moreOf(p) { return p.compact.querySelector(".mp-more"); }

function focusPressed(root) {
  var b = root && (root.querySelector('.mp-models button.pill[aria-pressed="true"]') ||
                   root.querySelector(".mp-models button.pill"));
  if (b) b.focus();
}

/* `more…`: a full picker for one row, inside that row's model cell -- never a sibling row, which a
   keyed list strands on a reorder and orphans when its repository leaves. Built the first time and
   kept; one is open at a time, and Escape or a pick closes it. */
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
    // Escape is the host's (#362): it closes the expansion and gives the keyboard back to `more…`.
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

/* The model card's link is `/settings#model-<repo>` (app.js): that row, scrolled to, opened, and the
   keyboard on its pressed pill. Found by id, never by selector, so a dotted name is just a name. */
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
  // `~default` is `{model: "", effort: ""}`: no flag at all.
  saveModel({ model: pick.model, effort: pick.effort }, pick.model, pick, "", null);
}

function pickRepo(p, pick) {
  var r = rowOf(p.repo) || {};
  var entry = { repo: p.repo, model: pick.model, effort: pick.effort }, pinned = "";
  if (pick.toolbar === "effort" && !r.model && !r.effort) pinned = entry.model = fleetDefault().model;
  saveModel({ models: [entry] }, entry.model, pick, pinned, p);
}

/* Post, then read the page back (the row is patched), then say what was saved. A pick made in an
   expansion closes it and leaves the keyboard on the row's pressed pill, which is the one chosen. */
function saveModel(body, model, pick, pinned, p) {
  var inside = !!(p && p.expand && p.expand.contains(document.activeElement));
  return post("settings", body).then(function (res) {
    if (res && res.ok === false) {
      refuse(p, res.error + (res.hint ? " — " + res.hint : ""));
      return;
    }
    problem(otherBox(p), "");
    return load().then(function () {
      // A name the list did not have is in it now, as configured: asked again, it says whether
      // this CLI offers it.
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
  return picker ? picker.querySelector(".mp-other") : null;
}

/* A refusal is said on the `other…` box of the picker it came from (class `bad`, the reason as its
   title), opened if it was not: a pill's id cannot be a second flag, so what refuses a pill is the
   config file itself, and the box is where the row has room to say so. */
function refuse(p, message) {
  if (p && (!p.expand || p.expand.hidden)) openExpansion(p, false);
  var box = otherBox(p);
  if (box && box.hidden) {
    var open = box.parentElement.querySelector(".mp-otherbtn");
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
  if (pinned) said.push("model pinned to " + modelLabel(pinned) + " so the effort can apply");
  if (pick.droppedEffort) {
    said.push("effort reset to default: " + modelLabel(pick.model) + " does not take " +
              pick.droppedEffort);
  }
  return "saved — " + (said.length ? said.join(" · ") : "takes effect on the next turn");
}

var modelRefresh = document.getElementById("modelrefresh");
if (modelRefresh) {
  // The server asks on a thread of its own and answers at once (#361); a list that changed comes
  // back as a `models` frame.
  modelRefresh.addEventListener("click", function () {
    post("models", { refresh: true }).then(function (res) {
      saidSaved(res && res.ok === false ? "not asked — " + (res.error || "refused")
                                        : "asking copilot for its model list");
    }, function () { saidSaved("the server did not answer — copilot was not asked"); });
  });
}

/* ------------------------------------------------------------------------------------- copilot */

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
    // The bounds the server refuses outside of, so the box's arrows stop where a refusal would start.
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

/* Each row lands in its section: the Copilot block, or -- for the pane's tiers (#235) -- under
   Appearance, because they are how the desk is drawn. */
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

/* What the desk is drawing with, when that is not what the boxes say: a four in the file that does
   not go together -- a hand edit -- is drawn at CI's numbers, and this says why (#235). */
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

/* ---------------------------------------------------------------------------------------- load */

function load() {
  // The model list is asked for once (#367), and the first draw waits for it: every section comes
  // in one paint, and no picker is drawn empty and then again full.
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
      landOnRow();                       // last: every section above the row is drawn
    }).catch(function () { /* a settings page that cannot reach the server says nothing new */ });
}

/* One frame, one reason: `config.json` changed under us. Without it this page would keep showing
   the palette it was opened with while the desk beside it wore another. */
function connectTheme() {
  try {
    // `frames=theme` (#348): this page listens for one frame, so it is sent no agent history.
    var stream = new EventSource(q("/api/events", { frames: "theme" }));
    stream.addEventListener("theme", function (m) {
      try {
        var d = JSON.parse(m.data);
        if (pendingTheme) { heardDuringWrite = d; return; }
        applyTheme(d.css, d.theme);
        applySkin(d.skin);
        reflectTheme(d);
      } catch (e) { /* a frame we cannot read is not worth breaking the page over */ }
    });
    // The model list changed on disk (#361): a refresh from this page, another window or
    // `ad-fleet models --refresh`. Asked for again only when its `version` moved.
    stream.addEventListener("models", function (m) {
      try {
        var d = JSON.parse(m.data);
        if (!d || !d.version || d.version === modelsHeard) return;
        modelsHeard = d.version;
        loadModelList().then(drawModels);
      } catch (e) { /* as above */ }
    });
  } catch (e) { /* no stream is a stale page, not a broken one */ }
}

// The skin the page settles on, for its load record (#351). Harmless when measuring is off.
loadThemes().then(function () { LOAD.settled = document.body.dataset.skin || ""; });
load();
connectTheme();
// While measuring is on (#351), the note that tells the desk this load came from here: a desk
// opened from settings and a cold open both read `navigate`, and every page is `no-referrer`.
if (LOAD.on) {
  window.addEventListener("pagehide", function () {
    try { sessionStorage.setItem("fleet.load.from", "settings"); } catch (e) { /* not counted */ }
  });
}
