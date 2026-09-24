/* The settings page.

   A page and not a popover, because the palette stopped being the only thing here: the model each
   agent runs and the flags the Copilot CLI is launched with are settings too, and none of them fits
   behind a button on a toolbar that is meant to be about the agents.

   It shares `common.js` with the desk -- the token, `q`, `post`, `text`, and the two painters -- and
   nothing else. It deliberately does NOT load `app.js`: that file boots a desk (an EventSource
   feeding tiles, a fifteen-second `loadDesk`, a `place()` that rewrites `document.body` several
   times a second) and none of it has any business running under somebody editing a dropdown.

   It does open one EventSource of its own, for exactly one frame. The `theme` frame is emitted
   whenever `config.json` changes, so a palette set from `ad-theme` in a terminal, or from another
   window, repaints this page instead of leaving its pickers saying something that is no longer
   true. That was bug #195 on the desk, and a settings page with no stream is where it would come
   back. */

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
      text(option, t.name);
      option.title = t.why || t.title || t.name;
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
}

/* -------------------------------------------------------------------------------------- models */

/* Free text with suggestions, not a dropdown of model names. `--model` is on the measured list of
   flags this build has; WHICH names it accepts was never measured, and a hardcoded enum would be
   this repository inventing an answer it does not have. The suggestions are models the event
   stream has actually reported, so the list grows from what really ran. The CLI is the validator,
   at the next turn. */
function fillList(id, values) {
  var list = document.getElementById(id);
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  (values || []).forEach(function (v) {
    var option = document.createElement("option");
    option.value = v;
    list.appendChild(option);
  });
}

function cell(row, value, title) {
  var td = document.createElement("td");
  text(td, value);
  if (title) td.title = title;
  row.appendChild(td);
  return td;
}

function fieldCell(row, value, placeholder, onsave) {
  var td = document.createElement("td");
  var input = document.createElement("input");
  input.type = "text";
  input.value = value || "";
  input.placeholder = placeholder;
  input.addEventListener("change", function () { onsave(input.value, input); });
  td.appendChild(input);
  row.appendChild(td);
  return input;
}

function renderModels(data) {
  var body = document.getElementById("modelrows");
  if (!body) return;
  while (body.firstChild) body.removeChild(body.firstChild);

  var fleetModel = document.getElementById("fleetmodel");
  var fleetEffort = document.getElementById("fleeteffort");
  if (fleetModel) fleetModel.value = (data.model && data.model.fleet && data.model.fleet.model) || "";
  if (fleetEffort) fleetEffort.value = (data.model && data.model.fleet && data.model.fleet.effort) || "";

  fillList("modelnames", (data.model && data.model.seen) || []);
  fillList("effortnames", (data.model && data.model.efforts) || []);

  (data.model && data.model.repos || []).forEach(function (r) {
    var row = document.createElement("tr");
    cell(row, r.repo);
    fieldCell(row, r.model, "inherit", function (v, input) {
      saveModel(r.repo, { model: v }, input);
    });
    fieldCell(row, r.effort, "inherit", function (v, input) {
      saveModel(r.repo, { effort: v }, input);
    });
    cell(row, r.source, r.source === "cli-auto"
      ? "nothing is configured, so no --model flag is passed and the CLI chooses"
      : "resolved from " + r.source);
    /* Configured is not served. The tenant may pin a model, and a page that reported only what was
       asked for would show a setting that is not what ran. This column is what the stream said the
       last turn actually used. */
    cell(row, r.actual || "—", r.actual
      ? "what the last turn actually ran on, from the event stream"
      : "no turn has reported a model for this repository yet");
    body.appendChild(row);
  });

  var note = document.getElementById("modelnote");
  if (note) {
    text(note, (data.model && data.model.repos || []).length
      ? "A blank field inherits the fleet-wide default above; a blank default passes no flag at all."
      : "No repositories are registered yet — `ad-fleet repo add <path>`.");
  }
}

function saveModel(repo, patch, input) {
  return post("settings", { models: [{ repo: repo, model: patch.model, effort: patch.effort }] })
    .then(function (res) {
      if (res && res.ok === false) { problem(input, res.error + (res.hint ? " — " + res.hint : "")); return; }
      problem(input, "");
      saidSaved("saved — takes effect on the next turn");
      load();
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
  return fetch(q("/api/settings")).then(function (r) { return r.json(); }).then(function (data) {
    if (!data || data.ok === false) return;
    renderModels(data);
    renderConfig(data);
    renderTierNote(data.tiers);
    renderPatterns("allowlist", "allowcount", (data.tools || {}).allow);
    renderPatterns("denylist", "denycount", (data.tools || {}).deny);
  }).catch(function () { /* a settings page that cannot reach the server says nothing new */ });
}

/* One frame, one reason: `config.json` changed under us. Without it this page would keep showing
   the palette it was opened with while the desk beside it wore another. */
function connectTheme() {
  try {
    var stream = new EventSource(q("/api/events"));
    stream.addEventListener("theme", function (m) {
      try {
        var d = JSON.parse(m.data);
        if (pendingTheme) { heardDuringWrite = d; return; }
        applyTheme(d.css, d.theme);
        applySkin(d.skin);
        reflectTheme(d);
      } catch (e) { /* a frame we cannot read is not worth breaking the page over */ }
    });
  } catch (e) { /* no stream is a stale page, not a broken one */ }
}

loadThemes();
load();
connectTheme();
