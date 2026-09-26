const TOOLS = {
  pencil: "--muted",
  pen: "--accent",
  red: "--human",
  green: "--done",
  marker: "--human",
  highlighter: "--waiting",
};

const ERASABLE = new Set(["pencil"]);
const LEAVES = ["erased", "struck"];

const PLAIN = {
  outline: "outline: 1px solid %c; outline-offset: 2px;",
  divider: "box-shadow: inset 0 -1px 0 %c;",
  underline: "text-decoration-line: underline; text-decoration-color: %c; " +
             "text-decoration-thickness: 2px; text-underline-offset: 3px;",
  lines: "@tint",
  loop: "outline: 2px solid %c; outline-offset: 3px;",
  ellipse: "outline: 2px solid %c; outline-offset: 4px;",
  ring: "box-shadow: 0 0 0 2px %c; border-radius: 999px;",
  strike: "text-decoration-line: line-through; text-decoration-color: %c; text-decoration-thickness: 2px;",
  check: "box-shadow: inset 3px 0 0 %c;",
  bang: "box-shadow: inset 3px 0 0 %c;",
  cross: "box-shadow: inset 3px 0 0 %c;",
  arrow: "text-decoration-line: underline; text-decoration-style: dotted; text-decoration-color: %c;",
  write: "",
};

const MARGIN = new Set(["check", "bang", "cross"]);

const PLAIN_TINT = 38;
const SPEED = [0.25, 4];

const SNAPS = new Set(["outline", "divider", "underline"]);

const TUNABLE = ["w", "press", "pvar", "wob", "lam", "bow", "wmin", "tin", "tout"];

function colour(tool) {
  return "var(--ink-" + tool + ", var(" + TOOLS[tool] + "))";
}

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
    if (row.ink !== undefined && !Object.prototype.hasOwnProperty.call(TOOLS, row.ink)) {
      throw new TypeError(where + ": `ink` " + JSON.stringify(row.ink) + " is no tool (" + Object.keys(TOOLS).join(", ") + ")");
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
    if ((row.grow !== undefined || row.tip) && row.shape !== "underline") {
      throw new TypeError(where + ": `grow` and `tip` are an underline's");
    }
    if (row.cap !== undefined && (row.shape !== "underline" || row.tip || (row.cap !== "arrow" && row.cap !== "bar"))) {
      throw new TypeError(where + ": `cap` is an underline's ('arrow' or 'bar') and never with `tip`");
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
    if (row.snap != null && !(Number.isFinite(row.snap) && row.snap >= 4 && SNAPS.has(row.shape))) {
      throw new TypeError(where + ": `snap` is a grid pitch of 4px or more, for " + Array.from(SNAPS).join(", "));
    }
    if (row.leaves != null && !LEAVES.includes(row.leaves)) {
      throw new TypeError(where + ": `leaves` is " + LEAVES.map(function (w) { return JSON.stringify(w); }).join(" or "));
    }
    return {
      index: i,
      selector: row.selector.trim(),
      tool: row.tool,
      ink: row.ink || row.tool,
      shape: row.shape,
      to: typeof row.to === "string" ? row.to : "",
      pad: Number.isFinite(row.pad) ? row.pad : 0,
      dash: !!row.dash,
      grow: typeof row.grow === "string" ? row.grow : "",
      step: Number.isFinite(row.step) && row.step > 0 ? row.step : 10,
      tip: !!row.tip,
      cap: row.cap || "",
      rewrite: !!row.rewrite,
      snap: Number.isFinite(row.snap) ? row.snap : 0,
      leaves: row.leaves || (ERASABLE.has(row.tool) ? "erased" : "struck"),
    };
  });
  const tools = {};
  for (const [tool, tune] of Object.entries(table.tools && typeof table.tools === "object" ? table.tools : {})) {
    if (!Object.prototype.hasOwnProperty.call(TOOLS, tool) || !tune || typeof tune !== "object") {
      throw new TypeError("ink: tools: no tool " + JSON.stringify(tool) + " to tune (" + Object.keys(TOOLS).join(", ") + ")");
    }
    tools[tool] = {};
    for (const [k, v] of Object.entries(tune)) {
      if (!TUNABLE.includes(k) || !Number.isFinite(v) || v < 0 || (k === "lam" && v === 0)) {
        throw new TypeError("ink: tools." + tool + "." + k + ": a tool tunes " + TUNABLE.join(", ") +
                            ", each a number of 0 or more (`lam` more than 0)");
      }
      tools[tool][k] = v;
    }
  }
  const hand = table.hand === undefined || table.hand;
  if (hand !== true && hand !== false && hand !== "chalk") {
    throw new TypeError("ink: `hand` is true, false or 'chalk', not " + JSON.stringify(hand));
  }
  const speed = Number.isFinite(table.speed) ? Math.min(SPEED[1], Math.max(SPEED[0], table.speed)) : 1;
  return {
    name: String(table.name || "unnamed"),
    paper: typeof table.paper === "string" ? table.paper : "",
    hand,
    speed,
    tools,
    series: table.series !== false,
    marks,
    fx: table.fx || null,
  };
}

let plainSheet = null;
let plainStyle = null;

function plainCss(t) {
  const out = ["/* ink: the plain fallback for the " + t.name + " table (#248) */"];
  for (const row of t.marks) {
    const sel = "body.ink-off :is(" + row.selector + ")";
    const look = PLAIN[row.shape];
    if (!look) continue;
    const c = colour(row.ink);
    if (look === "@tint") {
      out.push(sel + " { box-decoration-break: clone; -webkit-box-decoration-break: clone; }");
      out.push("@supports (color: color-mix(in srgb, red 50%, transparent)) { " + sel +
               " { background-color: color-mix(in srgb, " + c + " " + PLAIN_TINT + "%, transparent); } }");
    } else {
      let rule = look.split("%c").join(c);
      if (row.shape === "underline" && row.dash) rule += " text-decoration-style: dashed;";
      out.push(sel + " { " + rule + " }");
      if (MARGIN.has(row.shape)) {
        out.push("body.ink-off :is(" + row.selector + ").is-selected { box-shadow: inset 3px 0 0 " + c +
                 ", 0 0 0 2px var(--focus, var(--accent)); }");
      }
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

let table = null;
let layer = null;
let loading = null;

function turnOff(reason) {
  const was = verdict.on;
  verdict.on = false;
  if (was) {
    verdict.source = "runtime";
    verdict.why = String(reason || "turned off");
  }
  if (body) body.classList.add("ink-off");
  if (layer) {
    try { layer.stop(); } catch (e) {}
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
    if (running && verdict.on && table === wanted) {
      running.setTable(wanted);
      if (body && body.classList.contains("ink-off")) body.classList.remove("ink-off");
    }
    return { drawn: running && verdict.on ? "ink" : "plain", verdict: Object.assign({}, verdict) };
  }, () => ({ drawn: "plain", verdict: Object.assign({}, verdict) }));
}

const INKED = new Set(String((body && body.dataset.inkSkins) || "").split(/\s+/).filter(Boolean));
const FAMILY = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const HOOKS = ["ground", "paper", "frame", "tick", "dispose", "cue"];
let fromSkin = false;
let skinKey = "";

function valueOf(x, variant) {
  return typeof x === "function" ? x(variant) : x;
}

function fromModule(m, family, variant) {
  const o = valueOf(m.options, variant) || {};
  return {
    table: { name: family + (variant ? ":" + variant : ""), paper: o.paper, hand: o.hand, speed: o.speed,
             tools: o.tools, series: o.series, marks: valueOf(m.marks, variant) || [],
             fx: m.cues || o.fx ? { cues: valueOf(m.cues, variant), use: o.fx } : null },
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
    if (skinKey !== key) return null;
    const made = fromModule(m, family, variant);
    fromSkin = true;
    return apply(made.table, made.hooks, variant);
  }).catch(e => {
    console.error("ink: the " + family + " skin: " + String((e && e.message) || e));
  });
}

if (body) {
  new MutationObserver(follow).observe(body, { attributes: true, attributeFilter: ["data-skin", "data-skin-variant"] });
  follow();
}

function setSkin(next, hooks) {
  fromSkin = false;
  return apply(next, hooks);
}

window.Ink = Object.freeze({
  ready: Promise.resolve(Object.assign({}, verdict)),
  get enabled() { return verdict.on; },
  get verdict() { return Object.assign({}, verdict); },
  get tools() { return Object.keys(TOOLS); },
  get shapes() { return Object.keys(PLAIN); },
  setSkin: setSkin,
  refresh() { if (layer) layer.refresh(); },
  off(reason) { turnOff(reason || "turned off by the page"); },
  inspect() {
    return { verdict: Object.assign({}, verdict), table: table ? table.name : null,
             plain: !!(plainSheet || plainStyle), layer: layer ? layer.inspect() : null };
  },
  sample(box) { return layer ? layer.sample(box) : 0; },
});
