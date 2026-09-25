/* The model picker (#362): the one component every place that sets a model or an effort adopts --
   the model card, `m` on a rail, /settings and the dispatch card (#366-#368).

   Provider-grouped pills that are pressed, never typed: `other…` is the one escape hatch, for a new
   or BYOK name. A toolbar for the model and, in the full picker, one for the effort, each a single
   tab stop that the arrows walk. Nothing is said by colour alone: pressed is a ✓ and a 2px ring as
   well as `--select`, because `--accent` text on `--select` reads 2.84:1 in sand; a pill the account
   cannot use carries ⊘ and a dashed edge and tells a screen reader why.

   It never posts. `onPick` hands the host `{model, effort, toolbar, droppedEffort}` and the host
   applies the inherit rule (#366). A draw writes only through common.js's `patchList`, `text`,
   `attr`, `setClass` and `setData`, so a draw with nothing new to say changes nothing and an idle
   card is an idle page (docs/desk-components.md). A classic script loaded after `common.js`: it
   declares the two functions at the bottom and `mpImpl`, and no other name, because every global
   here is shared with `app.js` and `settings.js`. */

"use strict";

/**
 * One entry of `/api/models` (`models.catalogue`).
 * @typedef {Object} ModelEntry
 * @property {string} id
 * @property {string} [label]
 * @property {string} [group]
 * @property {boolean} [offered]
 * @property {boolean} [available]
 * @property {string} [why_unavailable]
 * @property {number} [multiplier]
 * @property {string[]} [efforts]
 */

/**
 * What a press reports. `droppedEffort` is always "" since #493: an effort survives a model switch
 * (decision 15), and a model that lists efforts without it marks that pill ⊘ instead.
 * @typedef {Object} ModelPick
 * @property {string} model
 * @property {string} effort
 * @property {"model" | "effort"} toolbar
 * @property {string} droppedEffort
 */

/**
 * @typedef {Object} ModelPickerOptions
 * @property {"full" | "compact"} [variant]
 * @property {string} [label]
 * @property {string} [emptyLabel]
 * @property {string} [emptyTitle]
 * @property {(pick: ModelPick) => void} [onPick]
 * @property {(anchor: HTMLElement) => void} [onMore]
 */

/**
 * @typedef {Object} ModelPickerState
 * @property {{models?: ModelEntry[], groups?: {key: string, title: string}[], efforts?: string[],
 *             meta?: {cli_version?: string}}} catalogue
 * @property {{model: string, effort: string}} current
 * @property {{model: string, effort: string, source?: string} | null} [inherited]
 * @property {string} [actual]
 * @property {string[]} [quick]
 */

var mpImpl = (function () {
  var seq = 0;                       // ids for what the groups and pills point at
  /** @type {WeakMap<HTMLElement, any>} */
  var own = new WeakMap();

  /** @return {HTMLElement} */
  function make(tag, cls, words) {
    var e = document.createElement(tag);
    e.className = cls;
    if (words) e.textContent = words;
    return e;
  }

  function uid(kind) {
    seq += 1;
    return "mp-" + kind + seq;
  }

  function button(cls, words) {
    var b = /** @type {HTMLButtonElement} */ (make("button", cls, words));
    b.type = "button";
    return b;
  }

  function strings(list) {
    var out = [];
    (Array.isArray(list) ? list : []).forEach(function (v) {
      if (typeof v === "string" && v && out.indexOf(v) < 0) out.push(v);
    });
    return out;
  }

  // The mark, the label, the note, what only a screen reader hears, and the reason a pill that
  // cannot be picked points `aria-describedby` at (hidden from the name, which it would repeat).
  function pill() {
    var b = button("pill"), why = make("span", "sr pill-why");
    var mark = make("span", "pill-mark");
    mark.setAttribute("aria-hidden", "true");
    why.id = uid("why");
    why.setAttribute("aria-hidden", "true");
    b.append(mark, make("span", "pill-label"), make("span", "pill-note"), make("span", "sr pill-sr"), why);
    return b;
  }

  function paint(b, p) {
    var k = b.children;
    attr(b, "aria-pressed", p.pressed ? "true" : "false");
    attr(b, "aria-disabled", p.off ? "true" : null);
    attr(b, "aria-describedby", p.off ? p.describe || k[4].id : null);
    attr(b, "title", p.title || null);
    text(k[0], (p.pressed ? "✓" : "") + (p.unavailable ? "⊘" : "") + (p.unoffered ? "⚠" : "") +
               (p.actual ? "•" : ""));
    text(k[1], p.label);
    text(k[2], p.note || "");
    text(k[3], (p.actual ? " (the last turn ran on this)" : "") +
               (p.unoffered ? " (not offered by this CLI)" : ""));
    text(k[4], p.why || "");
  }

  function model(me, b, m) {
    var id = m.id, unav = m.available === false, unoff = m.offered === false;
    paint(b, {
      pressed: id === me.cur.model, off: unav, unavailable: unav, unoffered: unoff,
      actual: id !== "" && id === me.actual,
      label: id === "" ? me.opts.emptyLabel || m.label || "default" : m.label || id,
      note: typeof m.multiplier === "number" ? "×" + m.multiplier : "",
      title: id === "" ? me.opts.emptyTitle
        : unoff ? "not offered by copilot" + (me.ver ? " " + me.ver : "")
        : unav ? m.why_unavailable : id,
      why: unav ? m.why_unavailable || "not available to this account" : ""
    });
    setData(b, "model", id);
  }

  function keyOf(m) { return m.id === "" ? "~default" : m.id; }

  function pillsOf(bar) {
    return Array.prototype.slice.call(bar.querySelectorAll("button.pill"));
  }

  // One tab stop per toolbar: the pill the keyboard is on, else the pressed one, else the first.
  function rove(bar, to) {
    var pills = pillsOf(bar);
    if (!to) {
      to = pills.indexOf(document.activeElement) >= 0 ? document.activeElement : pills.filter(
        function (p) { return p.getAttribute("aria-pressed") === "true"; })[0] || pills[0];
    }
    pills.forEach(function (p) { attr(p, "tabindex", p === to ? "0" : "-1"); });
  }

  /** @return {ModelPick} */
  function pickModel(me, id) {
    // The effort stays (#493, decision 15): a model and an effort are set, and inherited, apart.
    return { model: id, effort: me.cur.effort, toolbar: "model", droppedEffort: "" };
  }

  function fire(me, pick) {
    if (typeof me.opts.onPick === "function") me.opts.onPick(pick);
  }

  /** @param {ModelPickerOptions} opts */
  function build(opts) {
    opts = opts || {};
    var root = make("div", "mpick"), models = make("div", "mp-models");
    var me = { opts: opts, models: models, open: false, cur: { model: "", effort: "" },
               byId: new Map(), actual: "", ver: "", other: null, effort: null, why: null };
    root.dataset.variant = opts.variant === "compact" ? "compact" : "full";
    models.setAttribute("role", "toolbar");
    models.setAttribute("aria-label", opts.label || "model");
    root.append(models);
    if (opts.variant !== "compact") {
      var other = me.other = /** @type {HTMLInputElement} */ (make("input", "mp-other"));
      other.type = "text";
      other.id = uid("other");
      other.hidden = true;
      other.autocomplete = "off";
      other.spellcheck = false;
      other.setAttribute("aria-label", "another model id");
      me.effort = make("div", "mp-effort");
      me.effort.setAttribute("role", "toolbar");
      me.effort.setAttribute("aria-label", (opts.label ? opts.label + ": " : "") + "effort");
      me.why = make("span", "mp-effort-why",
                    "effort follows the inherited model; press a model to set one");
      me.why.id = uid("ewhy");
      me.why.hidden = true;
      root.append(other, me.effort, me.why);
    }
    own.set(root, me);

    root.addEventListener("keydown", function (/** @type {KeyboardEvent} */ e) {
      var t = /** @type {HTMLElement} */ (e.target);
      if (t.tagName === "INPUT") {
        var id = t === me.other ? me.other.value.trim() : "";
        if (e.key === "Enter" && !e.isComposing && id) {
          e.preventDefault();
          e.stopPropagation();
          fire(me, pickModel(me, id));
        }
        return;
      }
      var bar = t.classList.contains("pill") ? t.closest("[role=toolbar]") : null;
      if (!bar || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "Enter" || e.key === " ") {
        e.stopPropagation();           // the button's own click picks, once
        return;
      }
      var pills = pillsOf(bar), i = pills.indexOf(t), n = pills.length;
      switch (e.key) {
        case "ArrowRight": case "ArrowDown": i += 1; break;
        case "ArrowLeft": case "ArrowUp": i -= 1; break;
        case "Home": i = 0; break;
        case "End": i = n - 1; break;
        default: return;               // Escape among them: it is the host's
      }
      e.preventDefault();
      e.stopPropagation();
      var to = pills[(i + n) % n];
      rove(bar, to);
      to.focus();
    });

    root.addEventListener("focusin", function (e) {
      var t = /** @type {HTMLElement} */ (e.target);
      var bar = t.classList.contains("pill") ? t.closest("[role=toolbar]") : null;
      if (bar) rove(bar, t);
    });

    root.addEventListener("click", function (e) {
      var b = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (e.target).closest("button.pill"));
      if (!b || b.getAttribute("aria-disabled") === "true") return;
      if (b.classList.contains("mp-otherbtn")) {
        me.open = true;
        attr(b, "aria-expanded", "true");
        attr(me.other, "hidden", null);
        me.other.focus();
      } else if (b.classList.contains("mp-more")) {
        if (typeof opts.onMore === "function") opts.onMore(b);
      } else if (b.closest(".mp-effort")) {
        fire(me, { model: me.cur.model, effort: b.dataset.effort || "", toolbar: "effort",
                   droppedEffort: "" });
      } else {
        fire(me, pickModel(me, b.dataset.model || ""));
      }
    });
    return root;
  }

  /**
   * @param {HTMLElement} root
   * @param {ModelPickerState} state
   */
  function draw(root, state) {
    var me = own.get(root);
    if (!me) return;
    var s = state || /** @type {ModelPickerState} */ ({});
    var cat = s.catalogue || {}, cur = s.current || { model: "", effort: "" };
    var inh = s.inherited || null;
    me.cur = { model: String(cur.model || ""), effort: String(cur.effort || "") };
    me.actual = String(s.actual || "");
    me.ver = String(cat.meta && cat.meta.cli_version || "");

    // Every id once, `""` (inherit) always there, and a current id the catalogue lacks shown in
    // the last group rather than lost.
    var byId = me.byId = new Map();
    byId.set("", { id: "" });
    (Array.isArray(cat.models) ? cat.models : []).forEach(function (m) {
      if (m && typeof m.id === "string" && (m.id === "" || !byId.has(m.id))) byId.set(m.id, m);
    });
    if (!byId.has(me.cur.model)) byId.set(me.cur.model, { id: me.cur.model });

    if (root.dataset.variant === "compact") {
      var shown = [byId.get("")];
      if (me.cur.model) shown.unshift(byId.get(me.cur.model));
      strings(s.quick).filter(function (id) {
        return shown.indexOf(byId.get(id)) < 0;
      }).slice(0, 2).forEach(function (id) { shown.push(byId.get(id) || { id: id }); });
      patchList(me.models, shown.concat([{ id: "~more" }]), function (m) {
        return m.id === "~more" ? m.id : keyOf(m);
      }, function (m) {
        return m.id === "~more" ? button("pill mp-more", "more…") : pill();
      }, function (b, m) {
        if (m.id !== "~more") model(me, b, m);
      });
      rove(me.models, null);
      return;
    }

    var groups = [], at = Object.create(null);
    (Array.isArray(cat.groups) && cat.groups.length ? cat.groups : [{ key: "", title: "models" }])
      .forEach(function (g) {
        if (at[g.key]) return;
        at[g.key] = { key: "g:" + g.key, title: g.title, pills: [] };
        groups.push(at[g.key]);
      });
    byId.forEach(function (m) {
      var g = at[m.group] || (m.id === "" ? groups[0] : groups[groups.length - 1]);
      if (m.id === "") g.pills.unshift(m); else g.pills.push(m);
    });
    var rows = groups.filter(function (g) { return g.pills.length; }).concat([{ key: "~other" }]);
    patchList(me.models, rows, function (r) { return r.key; }, function (r) {
      if (r.key === "~other") {
        var b = button("pill mp-otherbtn", "other…");
        b.setAttribute("aria-controls", me.other.id);
        return b;
      }
      var g = make("div", "mp-group"), label = make("span", "mp-glabel");
      label.id = uid("group");
      g.setAttribute("role", "group");
      g.setAttribute("aria-labelledby", label.id);
      g.append(label);
      return g;
    }, function (g, r) {
      if (r.key === "~other") {
        attr(g, "aria-expanded", me.open ? "true" : "false");
        return;
      }
      text(g.firstElementChild, r.title);
      patchList(g, r.pills, keyOf, pill, function (b, m) { model(me, b, m); });
    });
    attr(me.other, "hidden", me.open ? null : "");

    // The effort, a half of its own (#493, decision 15): "" is no effort of this host's own -- the
    // inherited one when there is one, named on the pill -- then the catalogue's levels. Settable
    // whatever the model, "CLI chooses" included. A model that lists its own levels and not one
    // of these marks that pill ⊘ and says so, rather than dropping the effort.
    var inhEffort = inh ? String(inh.effort || "") : "";
    var shape = byId.get(me.cur.model || (inh ? String(inh.model || "") : "")) || {};
    var takes = Array.isArray(shape.efforts) ? shape.efforts : null;
    var levels = [""].concat(strings(cat.efforts));
    patchList(me.effort, levels, function (e) { return e || "~default"; }, pill, function (b, e) {
      var untaken = !!e && !!takes && takes.indexOf(e) < 0;
      paint(b, { pressed: e === me.cur.effort, unavailable: untaken,
                 label: e || (inhEffort ? "inherit · " + inhEffort : "default"),
                 title: untaken ? (shape.label || shape.id) + " does not list " + e +
                                  "; the CLI may refuse the pair at start" : "" });
      setData(b, "effort", e);
    });
    attr(me.why, "hidden", "");
    rove(me.models, null);
    rove(me.effort, null);
  }

  return { build: build, draw: draw };
})();

/**
 * One picker, built once and bound once.
 * @param {ModelPickerOptions} opts
 * @return {HTMLElement}
 */
function createModelPicker(opts) {
  return mpImpl.build(opts);
}

/**
 * Draw `state` into a picker. An equal state makes no mutation.
 * @param {HTMLElement} el
 * @param {ModelPickerState} state
 */
function drawModelPicker(el, state) {
  mpImpl.draw(el, state);
}
