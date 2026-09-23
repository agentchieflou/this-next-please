/* Graph paper (#253, slice G of the ink epic #246): a grid on the page's own 28px baseline, a
   mechanical pencil, ruled strokes snapped to the grid, and every agent's hour plotted on it.

   The pattern is `skins/example.js`, and docs/desk-ink.md §Writing a skin is the contract. Its
   rules, as this skin keeps them:

   * No static `import`: three.js is handed in, and nothing else is needed.
   * Every mark comes from a class or attribute the page already sets (the table below), and the
     skin never writes the page. The hooks draw into the scenes they are handed.
   * Every colour is a custom property of `static/skins/graph/skin.css`, read here through
     `tokens.css(name)` at paint time: `--paper`, `--grid`, `--grid-major`, `--ink-trace`. The inks
     are `--ink-<tool>`, which the layer reads itself.

   THE GRID. A minor line every 28px, the page's own baseline -- the HIG hit target every control
   on the desk is at least as tall as (app.css), so a row of buttons sits a square high -- and a
   major line every fifth, 140px. Five is the engineering pad's own count, and it is the one that
   lets an eye count squares: four or more minor squares in a row stop being countable at a
   glance, and the heavy line every fifth is what makes "three squares" and "eight squares"
   readable without a ruler. The lines start at the viewport's top-left, which is where the
   layer's ruled strokes (`snap`) find them.

   THE PENCIL. A mechanical pencil: the layer's pencil tuned thin (1.05px), even (almost no
   pressure variation), steady (no wobble, no bow) and without taper, because a 0.5mm lead does not
   thin at the ends the way a sharpened one does.

   THE TRACE. `drawTrace` in app.js paints each agent's last hour on a 2D canvas. With this skin
   drawing, that canvas steps aside (skin.css makes it transparent; it keeps its sentence for a
   screen reader) and the same hour is plotted here as a graph line, on the grid line under the
   canvas, from the data the page already has (`data-trace` on the canvas). A minute that stopped
   for a person is a red tick up the square. */

/* The page's baseline, and a major line every fifth. */
export const GRID = 28;
export const MAJOR = 5;

/* The ruled rows: outlines, dividers and underlines land on the grid. */
const RULED = { snap: GRID };

/* The mark table: the paper state grammar (plan-ink §The state grammar), mapped onto what the page
   already sets. `app.js` owns every one of these classes; the skin only reads them.

   | state          | where the page says it                                   |
   | idle           | `.tile.state-idle`                                       |
   | running        | `.tile.state-running`                                    |
   | needs you      | `.tile.needs-human`, and an open question in `.asks`      |
   | answered       | a choice pressed: `.ask-choice[aria-pressed="true"]`      |
   | error          | `.tile.state-error`                                      |
   | done           | `.tile.is-done`: the fold's word (the chip says idle)    |
   | stale (#240)   | `.oldsession` shown                                      |
   | a finding      | a skill's STOP in the transcript: `li.friction`          |
   | the count      | `#counts`                                                |
   | the trace      | `.trace[data-trace]`                                     | */
export function marks() {
  const stale = ".oldsession:not([hidden])";
  const open = ".asks:not([hidden]) .ask:not([hidden])";
  return [
    // idle: a pencil outline round the pane and a pencil underline under the name. A stale pane's
    // outline is the dashed one below instead.
    Object.assign({ selector: `.tile.state-idle:not(:has(${stale}))`, tool: "pencil", shape: "outline" }, RULED),
    Object.assign({ selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" }, RULED),
    // running: a pen underline under the name.
    Object.assign({ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" }, RULED),
    // needs you: the name highlighted, and the question, and pencil loops round its choices. The
    // name's highlight is taken up when the agent no longer needs you: the grammar strikes the
    // question, never the agent's name.
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: `.tile ${open}:not(:has(.ask-choice[aria-pressed="true"])) .ask-q`, tool: "highlighter", shape: "lines" },
    { selector: `.tile ${open} .ask-choice[aria-pressed="false"]`, tool: "pencil", shape: "loop" },
    // answered: the question's highlight leaves the way ink does, struck through in pen along the
    // question -- and the chosen answer is circled.
    { selector: `.tile ${open} .ask-choice[aria-pressed="true"]`, tool: "pen", shape: "ellipse" },
    // error: a red marker box round the pane, ruled, and a bang in the margin.
    Object.assign({ selector: ".tile.state-error", tool: "marker", shape: "outline" }, RULED),
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    // done: a green check in the margin. The fold's own `done`: an agent nothing supervises is
    // drawn as idle by the chip, so its pencil stays and the check is added to it.
    { selector: ".tile.is-done", tool: "green", shape: "check" },
    // stale (#240): the chip written in pencil as a margin note, an arrow from it to the run line,
    // and a dashed pencil outline.
    { selector: `.tile ${stale}`, tool: "pencil", shape: "write" },
    { selector: `.tile ${stale}`, tool: "pencil", shape: "arrow", to: ".runline" },
    Object.assign({ selector: `.tile:has(${stale})`, tool: "pencil", shape: "outline", dash: true }, RULED),
    // a finding: a red ellipse round the line, the highlighter on its token, and its own text
    // written as the note.
    { selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse" },
    { selector: ".tile .transcript li.friction .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript li.friction .v", tool: "red", shape: "write" },
    // the count: handwritten.
    { selector: "footer #counts", tool: "pen", shape: "write" },
    // the trace: its axis, ruled in pencil on the grid line under the canvas. The row also names
    // `data-trace`, which is how the layer knows to look again when the hour changes.
    Object.assign({ selector: ".tile .head .trace[data-trace]", tool: "pencil", shape: "divider" }, RULED),
  ];
}

export function options() {
  return {
    paper: "--paper",
    hand: true,
    speed: 1,
    tools: { pencil: { w: 1.05, press: 0.9, pvar: 0.04, wob: 0, bow: 0, wmin: 0.94, tin: 0, tout: 0 } },
    // The hour is plotted on the grid by `frame` below, so the layer's own trace rows (#257) are off.
    series: false,
  };
}

/* A custom property as a three.js colour; the palette's muted token if the stylesheet has not
   arrived yet, so nothing here is ever a colour of its own. */
function colour(THREE, tokens, name, fallback) {
  const css = tokens.css(name) || fallback;
  const c = new THREE.Color();
  if (css) return c.setStyle(css, THREE.SRGBColorSpace);
  const m = tokens.muted;
  return c.setRGB(m[0], m[1], m[2], THREE.SRGBColorSpace);
}

/* Lines at `every` px across a w x h box, leaving out every `skip`th: the minor lines leave room
   for the major ones rather than being drawn twice under them. */
function rules(THREE, w, h, every, skip) {
  const pts = [];
  for (let i = 1, x = every; x < w; i++, x += every) {
    if (skip && i % skip === 0) continue;
    pts.push(new THREE.Vector3(x + 0.5, 0, 0), new THREE.Vector3(x + 0.5, -h, 0));
  }
  for (let i = 1, y = every; y < h; i++, y += every) {
    if (skip && i % skip === 0) continue;
    pts.push(new THREE.Vector3(0, -(y + 0.5), 0), new THREE.Vector3(w, -(y + 0.5), 0));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

/* The stock and its grid, under everything. Called when the skin arrives, on a resize and on a
   palette change, each time into an empty scene. */
export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const stock = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                               new THREE.MeshBasicMaterial({ color: colour(THREE, tokens, "--paper") }));
  stock.position.set(w / 2, -h / 2, 0);
  stock.renderOrder = api.order.paper;
  const minor = new THREE.LineSegments(rules(THREE, w, h, GRID, MAJOR),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--grid") }));
  minor.renderOrder = api.order.paper + 1;
  const major = new THREE.LineSegments(rules(THREE, w, h, GRID * MAJOR, 0),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--grid-major") }));
  major.renderOrder = api.order.paper + 2;
  scene.add(stock, minor, major);
}

// ------------------------------------------------------------------------------------ the traces

/* One plot per pane, kept for `tick` (the one thing a skin may keep between calls): the pane's
   group, what was plotted into it, and the signature it was plotted from. */
const plots = new Map();

/* The hour as `drawTrace` has it: `peak|n n n!` -- the busiest minute, then a count a minute, with
   `!` on a minute that stopped for a person. */
function hourOf(canvas) {
  const raw = canvas && canvas.dataset ? canvas.dataset.trace : "";
  if (!raw) return null;
  const [peak, list] = raw.split("|");
  const minutes = (list || "").split(" ").filter(Boolean).map(s => ({ n: parseFloat(s) || 0, needs: s.endsWith("!") }));
  return { peak: Math.max(1, parseFloat(peak) || 1), minutes };
}

function unplot(p) {
  for (const o of p.objs) {
    p.group.remove(o);
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  }
  p.objs = [];
}

/* Plot one pane's hour, if anything about it changed: its data, where the canvas is in the pane,
   where the pane is against the grid, or the colours. The baseline is the grid line nearest the
   foot of the canvas, where the pencil axis is ruled; a minute is a step along it, and the busiest
   minute is as tall as the canvas. */
function plot(THREE, tokens, p) {
  const el = p.el;
  const canvas = el.querySelector(".head .trace");
  const hour = hourOf(canvas);
  const pr = el.getBoundingClientRect();
  const cr = canvas ? canvas.getBoundingClientRect() : null;
  const sig = !hour || !cr || !cr.width || !cr.height ? "none"
    : [canvas.dataset.trace, (cr.left - pr.left).toFixed(1), (cr.top - pr.top).toFixed(1), cr.width.toFixed(1),
       cr.height.toFixed(1), ((pr.left % GRID) + GRID) % GRID, ((pr.top % GRID) + GRID) % GRID,
       tokens.css("--ink-trace"), tokens.css("--ink-red")].join("|");
  if (sig === p.sig) return false;
  p.sig = sig;
  unplot(p);
  p.at = null;
  if (sig === "none" || !hour.minutes.length) return true;
  const base = Math.round(cr.bottom / GRID) * GRID - pr.top;     // pane coordinates, y down
  const x0 = cr.left - pr.left, step = cr.width / hour.minutes.length, tall = cr.height;
  const line = [], needs = [];
  hour.minutes.forEach((m, i) => {
    const x = x0 + (i + 0.5) * step;
    line.push(new THREE.Vector3(x, -(base - Math.min(1, m.n / hour.peak) * tall), 0));
    if (m.needs) needs.push(new THREE.Vector3(x, -base, 0), new THREE.Vector3(x, -(base - tall), 0));
  });
  const trace = new THREE.Line(new THREE.BufferGeometry().setFromPoints(line),
                               new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--ink-trace", tokens.css("--ink-pen")) }));
  p.objs.push(trace);
  if (needs.length) {
    p.objs.push(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(needs),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--ink-red") })));
  }
  for (const o of p.objs) {
    o.renderOrder = p.order;
    p.group.add(o);
  }
  p.at = { trace: canvas.dataset.trace, base: base + pr.top, points: line.map(v => [v.x + pr.left, pr.top - v.y]),
           needs: needs.length / 2 };
  return true;
}

/* What is plotted where, on the viewport: each pane's baseline, its points and how many minutes
   stopped for a person. For the tests (`tests/test_fleet_ink_graph.py`), which import this module
   with the token and so read the very instance the layer runs. */
export function plotted() {
  return Array.from(plots.values()).filter(p => p.at && p.el.isConnected)
    .map(p => Object.assign({ repo: p.el.dataset.repo }, p.at));
}

/* A pane's frame: its hour, plotted. Called when the pane appears and when its size changes, into
   an empty group that moves with the pane. */
export function frame({ THREE, scene, tokens, api }, el) {
  const p = { el, group: scene, objs: [], sig: "", order: api.order.frame, at: null };
  plots.set(el, p);
  plot(THREE, tokens, p);
}

/* Every frame the layer draws -- which it does when the page changes, `data-trace` included --
   plot again whatever changed (the layer draws the frame after this), and forget panes that have
   gone. It never asks for a frame of its own: an idle desk draws nothing. */
export function tick({ THREE, tokens }) {
  for (const [el, p] of Array.from(plots)) {
    if (!el.isConnected || !p.group.parent) {
      plots.delete(el);
      continue;
    }
    plot(THREE, tokens, p);
  }
  return false;
}

export function dispose() {
  plots.clear();
}
