/* The ink layer's front door (#248, slice B of the ink epic #246): the gate, `window.Ink`, and the
   plain fallback. `docs/desk-ink.md` is the page this file implements.

   Loaded by the desk as `<script type="module">` beside the classic `app.js`, after `common.js`,
   whose globals (`PARAMS`, `q`) it uses. It is small on purpose, because every desk loads it and
   most never draw: it decides whether this shell gets ink, and it is the only thing `app.js` will
   ever see of the layer (`window.Ink`). The drawing half -- `layer.js`, `shapes.js`, `pen.js` and
   the vendored three.js -- is fetched only when the gate says on AND a skin hands it a mark table,
   and always through `import(q(...))`: a module specifier resolved against this file's URL does
   not carry the run token, and every route on this server wants it (the reason `probe.js` does the
   same).

   THE GATE. The server writes what `/probe` measured in this shell onto the page it serves:
   `<body data-ink-shell="pycharm" data-ink-probe="hardware">`, from `probe.classify()` of that
   shell's record in `~/.agentdata/fleet/probes.json` (`unmeasured` when there is none). This file
   decides nothing about renderers. Only `hardware` -- the one class `probe.works()` accepts --
   turns ink on. Everything else is the plain fallback, `body.ink-off`: software, none, unknown,
   incomplete, unmeasured. So do `?ink=off`, a shell that will not give a WebGL context after all,
   three.js failing to load, and a lost context.

   THE OVERRIDE. `?ink=on` turns ink on whatever the probe said. It exists so CI -- which draws in
   SwiftShader, and so is always `software` -- can exercise the layer. It is an override, not a
   measurement: it writes nothing to `probes.json` and never reaches `/api/probe`, and `Ink.verdict`
   says `source: "override"` with the probe's own answer beside it.

   THE FALLBACK. The same mark table, drawn as plain CSS: an outline is an outline, a highlight a
   tinted background, a strike a line-through, a check or a bang a bar in the margin. One look
   shared by every skin, with no animation. It is a constructed stylesheet (`adoptedStyleSheets`),
   so it costs the page no DOM writes at all: the browser matches the selectors, and a mark comes
   and goes with the class `app.js` sets. */

/* The tools a mark table may name, and the palette colour each is drawn in unless the skin names
   one of its own as `--ink-<tool>`. A palette colours the inks; a skin chooses the paper. The
   eraser is not here: it is how a pencil mark leaves, not a mark. */
const TOOLS = {
  pencil: "--muted",
  pen: "--accent",
  red: "--human",
  green: "--done",
  marker: "--human",
  highlighter: "--waiting",
};

/* Pencil is erased when its mark goes; everything else is ink, and is struck through. */
const ERASABLE = new Set(["pencil"]);

/* Each shape as the plain fallback draws it, `%c` standing for the tool's colour. Everything the
   layer can draw is a row here: `layer.js` refuses to start if the two lists disagree. */
const PLAIN = {
  outline: "outline: 1px solid %c; outline-offset: 2px;",
  divider: "box-shadow: inset 0 -1px 0 %c;",
  underline: "text-decoration-line: underline; text-decoration-color: %c; " +
             "text-decoration-thickness: 2px; text-underline-offset: 3px;",
  lines: "@tint",
  loop: "outline: 2px solid %c; outline-offset: 3px;",
  ellipse: "outline: 2px solid %c; outline-offset: 4px;",
  strike: "text-decoration-line: line-through; text-decoration-color: %c; text-decoration-thickness: 2px;",
  check: "box-shadow: inset 3px 0 0 %c;",
  bang: "box-shadow: inset 3px 0 0 %c;",
  arrow: "text-decoration-line: underline; text-decoration-style: dotted; text-decoration-color: %c;",
  write: "",
};

const PLAIN_TINT = 38;           // percent of the ink in a plain highlight
const SPEED = [0.25, 4];         // the range a table's `speed` is held to

function colour(tool) {
  return "var(--ink-" + tool + ", var(" + TOOLS[tool] + "))";
}

// -------------------------------------------------------------------------------- the gate

const body = document.body;
const facts = {
  shell: (body && body.dataset.inkShell) || "",
  probe: (body && body.dataset.inkProbe) || "unmeasured",
};
const asked = String(PARAMS.get("ink") || "").toLowerCase();

const verdict = { on: false, shell: facts.shell, probe: facts.probe, source: "probe", why: "" };
if (asked === "off") {
  verdict.source = "param";
  verdict.why = "?ink=off";
} else if (asked === "on") {
  verdict.on = true;
  verdict.source = "override";
  verdict.why = "forced on by ?ink=on: a test override, not a measurement (the probe says " +
                facts.probe + " for " + (facts.shell || "this shell") + ")";
} else if (facts.probe === "hardware") {
  verdict.on = true;
  verdict.why = "the probe measured hardware WebGL in " + facts.shell;
} else {
  verdict.why = facts.probe === "unmeasured"
    ? "nothing has measured WebGL in " + (facts.shell || "this shell") + " yet (`ad-fleet probe --open " +
      (facts.shell || "browser") + "`)"
    : "the probe measured " + facts.probe + " for " + facts.shell;
}
if (!verdict.on && body) body.classList.add("ink-off");

// ----------------------------------------------------------------------------- the table

/* A mark table, checked once here so that a mistake in a skin is an exception at the call that
   made it, naming the row -- not a mark that silently never appears. */
function normalise(table) {
  if (!table || typeof table !== "object") throw new TypeError("ink: a mark table is an object");
  const rows = Array.isArray(table.marks) ? table.marks : [];
  const marks = rows.map((row, i) => {
    const where = "ink: mark " + i + (row && row.selector ? " (" + row.selector + ")" : "");
    if (!row || typeof row.selector !== "string" || !row.selector.trim()) {
      throw new TypeError(where + " has no selector");
    }
    try {
      document.querySelector(row.selector);
    } catch (e) {
      throw new SyntaxError(where + ": not a selector the page can match");
    }
    if (!Object.prototype.hasOwnProperty.call(TOOLS, row.tool)) {
      throw new TypeError(where + ": no tool " + JSON.stringify(row.tool) + " (" + Object.keys(TOOLS).join(", ") + ")");
    }
    if (!Object.prototype.hasOwnProperty.call(PLAIN, row.shape)) {
      throw new TypeError(where + ": no shape " + JSON.stringify(row.shape) + " (" + Object.keys(PLAIN).join(", ") + ")");
    }
    if (row.shape === "arrow" && typeof row.to !== "string") {
      throw new TypeError(where + ": an arrow needs `to`, the selector it points at");
    }
    if (typeof row.to === "string") {
      try {
        document.querySelector(row.to);
      } catch (e) {
        throw new SyntaxError(where + ": `to` is not a selector the page can match");
      }
    }
    // #249: an underline that grows with what arrives in its pane, a pen-tip dot at its end, and a
    // written word that is struck and written again when it changes. Each belongs to one shape.
    if ((row.grow !== undefined || row.tip) && row.shape !== "underline") {
      throw new TypeError(where + ": `grow` and `tip` are an underline's");
    }
    if (row.grow !== undefined) {
      try {
        document.querySelector(row.grow);
      } catch (e) {
        throw new SyntaxError(where + ": `grow` is not a selector the page can match");
      }
    }
    if (row.rewrite && row.shape !== "write") {
      throw new TypeError(where + ": `rewrite` is a written mark's");
    }
    return {
      index: i,
      selector: row.selector.trim(),
      tool: row.tool,
      shape: row.shape,
      to: typeof row.to === "string" ? row.to : "",
      pad: Number.isFinite(row.pad) ? row.pad : 0,
      dash: !!row.dash,
      grow: typeof row.grow === "string" ? row.grow : "",
      step: Number.isFinite(row.step) && row.step > 0 ? row.step : 10,
      tip: !!row.tip,
      rewrite: !!row.rewrite,
      leaves: ERASABLE.has(row.tool) ? "erased" : "struck",
    };
  });
  const speed = Number.isFinite(table.speed) ? Math.min(SPEED[1], Math.max(SPEED[0], table.speed)) : 1;
  return {
    name: String(table.name || "unnamed"),
    paper: typeof table.paper === "string" ? table.paper : "",
    hand: table.hand !== false,
    speed,
    marks,
  };
}

// --------------------------------------------------------------------------- the fallback

let plainSheet = null;
let plainStyle = null;

/* The same table as plain CSS, one rule per row, only ever under `body.ink-off`. */
function plainCss(t) {
  const out = ["/* ink: the plain fallback for the " + t.name + " table (#248) */"];
  for (const row of t.marks) {
    const sel = "body.ink-off :is(" + row.selector + ")";
    const look = PLAIN[row.shape];
    if (!look) continue;
    const c = colour(row.tool);
    if (look === "@tint") {
      out.push(sel + " { box-decoration-break: clone; -webkit-box-decoration-break: clone; }");
      out.push("@supports (color: color-mix(in srgb, red 50%, transparent)) { " + sel +
               " { background-color: color-mix(in srgb, " + c + " " + PLAIN_TINT + "%, transparent); } }");
    } else {
      out.push(sel + " { " + look.split("%c").join(c) + " }");
    }
  }
  return out.join("\n");
}

function plain(t) {
  const css = t && t.marks.length ? plainCss(t) : "";
  const canAdopt = "adoptedStyleSheets" in document && typeof CSSStyleSheet === "function";
  if (canAdopt) {
    if (!css) {
      if (plainSheet) document.adoptedStyleSheets = document.adoptedStyleSheets.filter(s => s !== plainSheet);
      plainSheet = null;
      return;
    }
    if (!plainSheet) {
      plainSheet = new CSSStyleSheet();
      document.adoptedStyleSheets = document.adoptedStyleSheets.concat([plainSheet]);
    }
    plainSheet.replaceSync(css);
    return;
  }
  // An engine without constructed stylesheets gets a <style> element: one DOM write, not per mark.
  if (!css) {
    if (plainStyle) plainStyle.remove();
    plainStyle = null;
    return;
  }
  if (!plainStyle) {
    plainStyle = document.createElement("style");
    plainStyle.setAttribute("data-ink", "plain");
    document.head.appendChild(plainStyle);
  }
  if (plainStyle.textContent !== css) plainStyle.textContent = css;
}

// ------------------------------------------------------------------------------ the layer

let table = null;
let layer = null;          // the running layer, once `layer.js` has started
let loading = null;        // the promise of it

function turnOff(reason) {
  const was = verdict.on;
  verdict.on = false;
  if (was) {
    verdict.source = "runtime";
    verdict.why = String(reason || "turned off");
  }
  if (body) body.classList.add("ink-off");
  if (layer) {
    try { layer.stop(); } catch (e) { /* it is going anyway */ }
  }
  layer = null;
  plain(table);
}

function start() {
  if (!loading) {
    const host = { verdict: verdict, tools: TOOLS, shapes: Object.keys(PLAIN), off: turnOff };
    loading = import(q("/static/ink/layer.js")).then(m => m.start(host)).then(running => {
      if (!verdict.on) {
        running.stop();
        return null;
      }
      layer = running;
      return running;
    });
    loading.catch(e => turnOff("the ink layer could not start: " + String((e && e.message) || e)));
  }
  return loading;
}

/* The material hooks a skin brings, the ones that are functions -- `sampleGround` is a flag. */
function materials(hooks) {
  const out = {};
  if (!hooks) return null;
  for (const name of HOOKS) if (typeof hooks[name] === "function") out[name] = hooks[name];
  out.sampleGround = hooks.sampleGround === true;
  return Object.keys(out).length > 1 || out.sampleGround ? out : null;
}

function apply(next, hooks, variant) {
  const t = next ? normalise(next) : null;
  if (t) {
    t.hooks = materials(hooks);
    t.variant = variant || "";
  }
  table = t;
  if (!verdict.on) {
    plain(table);
    return Promise.resolve({ drawn: table && table.marks.length ? "plain" : "none", verdict: Object.assign({}, verdict) });
  }
  plain(null);
  if (!table || (!table.marks.length && !table.hooks)) {
    if (layer) layer.setTable(null);
    return Promise.resolve({ drawn: "none", verdict: Object.assign({}, verdict) });
  }
  const wanted = table;
  return start().then(running => {
    if (running && verdict.on && table === wanted) running.setTable(wanted);
    return { drawn: running && verdict.on ? "ink" : "plain", verdict: Object.assign({}, verdict) };
  }, () => ({ drawn: "plain", verdict: Object.assign({}, verdict) }));
}

// ------------------------------------------------------------------------ the page's skin

/* A skin draws with ink by shipping `static/ink/skins/<name>.js`: a module that exports its
   `marks` (the table's rows, or a function of the variant that answers them), optional `options`
   (`paper`, `hand`, `speed`), and optional material hooks the layer calls -- `ground`, `paper`,
   `frame`, `tick`, `dispose` (docs/desk-ink.md §Writing a skin). The server lists those names on
   <body> (`data-ink-skins`), and `applySkin` in common.js writes the chosen skin as
   `body[data-skin]` and `[data-skin-variant]`, which is how skins.py and the settings page choose
   one today. This follows those two attributes, fetches the module through `q()` like every
   module here, and sets its table. Every shell fetches it, because the plain fallback draws the
   marks too; only a shell the gate turned on runs its materials. A skin with no module sets
   none, and asks for none. */
const INKED = new Set(String((body && body.dataset.inkSkins) || "").split(/\s+/).filter(Boolean));
const FAMILY = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const HOOKS = ["ground", "paper", "frame", "tick", "dispose"];
let fromSkin = false;          // the table in force is the page's skin's, not a caller's
let skinKey = "";

function valueOf(x, variant) {
  return typeof x === "function" ? x(variant) : x;
}

/* The table a skin module describes, with its hooks beside it. */
function fromModule(m, family, variant) {
  const o = valueOf(m.options, variant) || {};
  return {
    table: { name: family + (variant ? ":" + variant : ""), paper: o.paper, hand: o.hand, speed: o.speed,
             marks: valueOf(m.marks, variant) || [] },
    hooks: m,
  };
}

function follow() {
  const family = (body && body.dataset.skin) || "";
  const variant = (body && body.dataset.skinVariant) || "";
  const key = family + ":" + variant;
  if (key === skinKey) return;
  skinKey = key;
  if (!INKED.has(family) || !FAMILY.test(family)) {
    if (fromSkin) {
      fromSkin = false;
      apply(null);
    }
    return;
  }
  import(q("/static/ink/skins/" + family + ".js")).then(m => {
    if (skinKey !== key) return null;           // the skin changed again while this one loaded
    const made = fromModule(m, family, variant);
    fromSkin = true;
    return apply(made.table, made.hooks, variant);
  }).catch(e => {
    // A skin's own mistake: said where a skin author looks, and the page carries on without ink.
    console.error("ink: the " + family + " skin: " + String((e && e.message) || e));
  });
}

if (body) {
  new MutationObserver(follow).observe(body, { attributes: true, attributeFilter: ["data-skin", "data-skin-variant"] });
  follow();
}

/* A caller's table (a test, a console) replaces the skin's until the skin changes again. `hooks`
   is optional: anything shaped like a skin module's material hooks. */
function setSkin(next, hooks) {
  fromSkin = false;
  return apply(next, hooks);
}

window.Ink = Object.freeze({
  /* Settled as soon as the page has read its gate, which is when this module runs. */
  ready: Promise.resolve(Object.assign({}, verdict)),
  get enabled() { return verdict.on; },
  get verdict() { return Object.assign({}, verdict); },
  get tools() { return Object.keys(TOOLS); },
  get shapes() { return Object.keys(PLAIN); },
  /* The skin's mark table, or null for none. Answers how it is being drawn: `ink`, `plain` or
     `none`. Throws, naming the row, on a table it cannot draw. */
  setSkin: setSkin,
  /* Read the palette again, match the table against the page and measure every mark now. */
  refresh() { if (layer) layer.refresh(); },
  /* Off for the rest of this page's life, with the reason `verdict.why` will give. */
  off(reason) { turnOff(reason || "turned off by the page"); },
  /* What is on the paper, for tests and for a curious console: lanes, marks, frames. */
  inspect() {
    return { verdict: Object.assign({}, verdict), table: table ? table.name : null,
             plain: !!(plainSheet || plainStyle), layer: layer ? layer.inspect() : null };
  },
  /* How many pixels of ink are in a box of the viewport, read back from the frame just drawn. */
  sample(box) { return layer ? layer.sample(box) : 0; },
});
