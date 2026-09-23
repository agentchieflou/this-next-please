/* The farmstead skin on three.js (#255, slice I of the ink epic #246).

   What was a stylesheet of data-URL tiles is drawn by the ink layer: the soil under the whole page,
   plank bands behind the header and the footer, and a lit wooden frame round every pane with its
   paper inside. The art is `static/skins/farmstead/sprites.svg`, the file the repo reviews, and
   nothing else: it is fetched once, each sprite is rasterised on its own grid (one texel per art
   pixel), and every enlargement is three.js's NearestFilter at a whole number of DEVICE pixels, so
   a pixel of the art is always a square block of the screen and never a blend of two. The colours
   are the art's own; what the palette and the weather change comes from the custom properties
   `skin.css` sets (`--farm-*`), read at paint time, never from a hex written here.

   THE CROP. Each pane carries the crop its chip carried (#157): seed, sprout, sun, bloom or wilted,
   from the classes `app.js` already sets -- the tile's `state-*`, which the fold derives from the
   agent's phase and turn, and `needs-human`. When the phase advances the crop GROWS a stage: the
   next stage is drawn up from the soil a row of art pixels at a time over the one before, and
   seed to bloom grows through the sprout. Drawn, never faded (plan-ink ground rule 1): no two
   stages are ever blended. Under reduced motion the stage is simply there.

   THE REST OF THE STATES are the mark table below, and docs/skin-farmstead.md has the grammar:
   the layer draws them in ink here and plain under `body.ink-off`, from the same rows.

   No static `import` (the run token), no page writes, and nothing decided here that the page's
   classes did not say. */

const SHEET = "/static/skins/farmstead/sprites.svg";
/* The sheet is rasterised at this multiple of its own grid: one texel per art pixel. The texture
   holds exactly the pixels in the file, and every enlargement after it is NearestFilter's. */
const RASTER = 1;
const CROPS = ["crop-seed", "crop-sprout", "crop-sun", "crop-bloom", "crop-wilted"];
const SPRITES = ["soil", "plank"].concat(CROPS);
/* How a crop grows. A change along this line is the phase advancing: one stage drawn per step. */
const GROWS = ["crop-seed", "crop-sprout", "crop-bloom"];
/* Rows of art a growing crop gains a second, and never fewer than one a frame: a stage is up in
   sixteen frames at most, whatever the frame rate (desk-ink.md: counted in frames). */
const ROWS_PER_S = 60;
/* How many CSS px one art pixel spans, before it is rounded down to whole device pixels. The
   soil and the bands keep the stylesheet's 2x (a 16px tile drawn at 32px); the frames and the
   crops are the art's own size. */
const SCALE = { soil: 2, band: 2, board: 1, crop: 1 };
/* The frame's boards are one plank thick (8 art px), half over the pane's transparent border and
   half into the gutter, and throw a shadow this many art px down and right. */
const SHADOW = 3;
/* Where the pieces go: under every mark (api.order), shadow first, crop last. */
const ORDER = { shadow: -13, paper: -12, board: -11, crop: -10 };

/* ------------------------------------------------------------------------ the mark table */

/* The state grammar (docs/skin-farmstead.md), every row a class `app.js` already sets. */
export function marks() {
  return [
    // needs you: the name highlighted, and the crop wilts (the material, below).
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
    // running: a pen line under the name while the sprout grows.
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
    // error: the head boxed in marker; the crop wilts and the frame is scorched.
    { selector: ".tile.state-error .head", tool: "marker", shape: "loop", pad: 2 },
    // done: a green tick in the margin, beside the bloom.
    { selector: ".tile.state-done .head", tool: "green", shape: "check" },
    // stale (#240): the session's "old skills" tag ringed in dashed pencil.
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", pad: 2, dash: true },
    // answered: the choice the operator picked is circled in pen, while the question is open.
    { selector: ".tile .asks:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: 2 },
    // a finding: the friction line in the transcript, ringed in red.
    { selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse", pad: 2 },
  ];
}

/* The same farm in every weather (skins.py): the variants differ in their materials, which are
   `skin.css`'s custom properties, and never in what a state looks like. */
export const options = { hand: true, speed: 1 };

export const sampleGround = false;

/* ------------------------------------------------------------------------- the sprite sheet */

let sheet = null;          // {textures, canvases, base, loaded, failed}
let made = 0, freed = 0;   // textures, for `inspect` and the dispose test
let lastApi = null;
let U = null;              // the uniforms every material here shares, updated in place
let look = "";             // the custom properties they were last read from
let bands = [];            // the header and footer bands, for `tick` to follow
const recs = new Map();    // pane -> its crop and frame
const waited = new WeakSet();

/* The most common opaque colour of a sprite: the colour a weather recolours from. */
function commonest(g, w, h) {
  const px = g.getImageData(0, 0, w, h).data;
  const n = new Map();
  let best = "", most = 0;
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] < 128) continue;
    const k = px[i] + "," + px[i + 1] + "," + px[i + 2];
    const c = (n.get(k) || 0) + 1;
    n.set(k, c);
    if (c > most) { most = c; best = k; }
  }
  return best ? best.split(",").map(v => Number(v) / 255) : [0.5, 0.5, 0.5];
}

/* One sprite of the sheet as its own SVG document, drawn by the browser into a canvas of the
   sprite's own grid. `shape-rendering: crispEdges` is the sheet's, so every rect lands on whole
   pixels and nothing is antialiased. */
function rasterise(doc, id, s) {
  const node = doc.getElementById(id) || doc.querySelector("[id=\"" + id + "\"]");
  if (!node) return Promise.reject(new Error("sprites.svg has no #" + id));
  const one = node.cloneNode(true);
  const cv = s.canvases[id];
  one.setAttribute("width", String(cv.width));
  one.setAttribute("height", String(cv.height));
  one.setAttribute("shape-rendering", doc.documentElement.getAttribute("shape-rendering") || "crispEdges");
  // A data: URL, because the desk's CSP allows images from itself and `data:` alone (serve.py).
  const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(one));
  const img = new Image();
  return new Promise((ok, no) => {
    img.onload = ok;
    img.onerror = () => no(new Error("#" + id + " would not rasterise"));
    img.src = url;
  }).then(() => {
    const g = cv.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingEnabled = false;
    g.clearRect(0, 0, cv.width, cv.height);
    g.drawImage(img, 0, 0, cv.width, cv.height);
    s.base[id] = commonest(g, cv.width, cv.height);
  });
}

/* The textures exist from the first call, blank, so every material can hold them at once; the art
   arrives in them when the sheet has been fetched and drawn, and the layer is asked for a frame. */
function load(THREE, api) {
  if (sheet) return sheet;
  const s = sheet = { textures: {}, canvases: {}, base: {}, loaded: false, failed: "",
                      nearest: THREE.NearestFilter };
  for (const id of SPRITES) {
    const cv = document.createElement("canvas");            // never on the page
    cv.width = 16 * RASTER;
    cv.height = (id === "plank" ? 8 : 16) * RASTER;
    s.canvases[id] = cv;
    const t = new THREE.CanvasTexture(cv);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.flipY = false;                                          // row 0 of the art is v = 0
    t.colorSpace = THREE.NoColorSpace;                        // the art's bytes, untouched
    s.textures[id] = t;
    made += 1;
  }
  fetch(q(SHEET)).then(r => {
    if (!r.ok) throw new Error("sprites.svg answered " + r.status);
    return r.text();
  }).then(text => {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("sprites.svg does not parse");
    return Promise.all(SPRITES.map(id => rasterise(doc, id, s)));
  }).then(() => {
    if (sheet !== s) return;                                  // the skin went while it loaded
    for (const t of Object.values(s.textures)) t.needsUpdate = true;
    s.loaded = true;
    if (U) {
      U.uSoilRef.value.fromArray(s.base.soil);
      U.uWoodRef.value.fromArray(s.base.plank);
    }
    api.request();
  }).catch(e => {
    s.failed = String((e && e.message) || e);
    console.error("ink: the farmstead skin: " + s.failed);
  });
  return s;
}

/* --------------------------------------------------------------------------- the materials */

const GLSL_COMMON = `
  vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
  vec3 toSrgb(vec3 c) { c = max(c, 0.0);
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
  float lum(vec3 lin) { return dot(lin, vec3(0.2126, 0.7152, 0.0722)); }
  // One texel of a sprite, at its centre: the texture is NearestFilter too, so this is the pixel
  // of the art and nothing between two. A weather recolours it by its brightness against the
  // sprite's commonest colour, which is how skin.css's cave and rain were drawn from daylight.
  vec3 art(sampler2D map, vec2 grid, vec2 texel, float recolour, vec3 base, vec3 ref) {
    vec2 t = mod(floor(texel), grid);
    vec3 c = toLin(texture2D(map, (t + 0.5) / grid).rgb);
    if (recolour > 0.5) c = toLin(base) * lum(c) / max(lum(toLin(ref)), 1e-4);
    return c;
  }`;

const VERT = `
  attribute vec2 aArt;
  attribute float aSide;
  varying vec2 vArt;
  varying float vSide;
  void main() {
    vArt = aArt;
    vSide = aSide;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

/* The soil, and the bands: flat, lit by the band light (none for the soil). */
const FLAT_FRAG = GLSL_COMMON + `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform float uRecolour; uniform vec3 uBase;
  uniform vec3 uRef; uniform float uLight; uniform vec3 uSun;
  varying vec2 vArt;
  void main() {
    vec3 c = art(uMap, uGrid, vArt, uRecolour, uBase, uRef) * uLight * toLin(uSun);
    gl_FragColor = vec4(toSrgb(c), 1.0);
  }`;

/* The frame's boards. Each is a plank laid along its side, outer edge on row 0 of the art (its
   highlight) and inner edge on row 7 (its shadow), and bevelled: a board faces a little outward
   at its outer edge and a little inward at its inner one, a row of art at a time, so the light
   from the top left falls on the top and left boards and leaves the bottom and right in shade --
   in steps, as a pixel artist would shade it. `uChar` scorches it (a pane in error). */
const BOARD_FRAG = GLSL_COMMON + `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform float uRecolour; uniform vec3 uBase;
  uniform vec3 uRef; uniform vec3 uSun; uniform float uAmbient; uniform float uDiffuse;
  uniform vec3 uLightDir; uniform float uChar; uniform vec3 uEmber;
  varying vec2 vArt; varying float vSide;
  void main() {
    float row = clamp(floor(vArt.y), 0.0, uGrid.y - 1.0);
    vec3 c = art(uMap, uGrid, vec2(vArt.x, row), uRecolour, uBase, uRef);
    vec2 out2 = vSide < 0.5 ? vec2(0.0, 1.0) : vSide < 1.5 ? vec2(1.0, 0.0)
              : vSide < 2.5 ? vec2(0.0, -1.0) : vec2(-1.0, 0.0);
    float tilt = mix(0.55, -0.55, (row + 0.5) / uGrid.y);
    vec3 n = normalize(vec3(out2 * tilt, 1.0));
    float lit = uAmbient + uDiffuse * max(dot(n, normalize(uLightDir)), 0.0);
    c *= lit * toLin(uSun);
    c = mix(c, c * 0.22 + toLin(uEmber) * 0.05, uChar);
    gl_FragColor = vec4(toSrgb(c), 1.0);
  }`;

/* A crop: the stage it had below `uRows` rows from the soil, the stage it is growing into at and
   under them. Transparent art is not drawn at all (no alpha to blend, so nothing is faded). */
const CROP_FRAG = `
  uniform sampler2D uOld; uniform sampler2D uNew; uniform float uRows;
  varying vec2 vArt;
  void main() {
    vec2 t = floor(vArt);
    vec4 c = (15.0 - t.y) < uRows ? texture2D(uNew, (t + 0.5) / 16.0) : texture2D(uOld, (t + 0.5) / 16.0);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb, 1.0);
  }`;

/* A flat colour, as the page's own sRGB: the paper under the pane, and the shadow. */
const FILL_FRAG = `
  uniform vec3 uColor; uniform float uAlpha;
  void main() { gl_FragColor = vec4(uColor, uAlpha); }`;

function uniforms(THREE) {
  if (U) return U;
  const v3 = () => ({ value: new THREE.Vector3(1, 1, 1) });
  U = {
    uSun: v3(), uEmber: v3(), uPaper: v3(), uShade: v3(),
    uSoilBase: v3(), uSoilRef: v3(), uSoilRecolour: { value: 0 },
    uWoodBase: v3(), uWoodRef: v3(), uWoodRecolour: { value: 0 },
    uBandLight: { value: 1 }, uAmbient: { value: 0.45 }, uDiffuse: { value: 0.62 },
    uLightDir: { value: new THREE.Vector3(-0.45, 0.55, 0.9) },
  };
  if (sheet && sheet.loaded) {
    U.uSoilRef.value.fromArray(sheet.base.soil);
    U.uWoodRef.value.fromArray(sheet.base.plank);
  }
  return U;
}

/* A custom property as [r, g, b] in 0-1 sRGB, or null when the skin does not set it. */
function rgbOf(THREE, text) {
  const s = String(text || "").trim();
  if (!s) return null;
  const c = new THREE.Color();
  try { c.setStyle(s, THREE.SRGBColorSpace); } catch (e) { return null; }
  const o = { r: 0, g: 0, b: 0 };
  c.getRGB(o, THREE.SRGBColorSpace);           // the page's own sRGB, as the layer's tokens are
  return [o.r, o.g, o.b];
}

/* The materials' inputs, from the palette and `skin.css`. Read on every hook: the stylesheet can
   land after the skin's first frame, and a palette or a weather changes them in place. */
function readLook(THREE, tokens) {
  const u = uniforms(THREE);
  const css = name => (tokens && typeof tokens.css === "function" ? tokens.css(name) : "");
  const sig = ["--farm-paper", "--farm-soil", "--farm-wood", "--farm-sun", "--farm-band-light",
               "--farm-ambient", "--farm-diffuse"].map(css).join("|") +
              "|" + String(tokens && tokens.human) + "|" + String(tokens && tokens.panel);
  if (sig === look) return false;
  look = sig;
  const paper = rgbOf(THREE, css("--farm-paper")) || (tokens && tokens.panel) || [1, 1, 1];
  u.uPaper.value.fromArray(paper);
  u.uSun.value.fromArray(rgbOf(THREE, css("--farm-sun")) || [1, 1, 1]);
  u.uEmber.value.fromArray((tokens && tokens.human) || [1, 0.3, 0.2]);
  const soil = rgbOf(THREE, css("--farm-soil"));
  u.uSoilRecolour.value = soil ? 1 : 0;
  if (soil) u.uSoilBase.value.fromArray(soil);
  const wood = rgbOf(THREE, css("--farm-wood"));
  u.uWoodRecolour.value = wood ? 1 : 0;
  if (wood) u.uWoodBase.value.fromArray(wood);
  const num = (name, dflt) => { const n = parseFloat(css(name)); return Number.isFinite(n) ? n : dflt; };
  u.uBandLight.value = num("--farm-band-light", 1);
  u.uAmbient.value = num("--farm-ambient", 0.45);
  u.uDiffuse.value = num("--farm-diffuse", 0.62);
  return true;
}

/* A stylesheet that is still loading is followed to its end, once: its custom properties are the
   materials' inputs, and a link that lands late would otherwise leave the daylight farm drawn
   under a cave's panes until something else asked for a frame. */
function awaitSheet() {
  const link = document.head && document.head.querySelector("link[data-skin]");
  if (!link || link.sheet || waited.has(link)) return;
  waited.add(link);
  link.addEventListener("load", () => { if (lastApi) lastApi.request(); }, { once: true });
}

function shader(THREE, frag, own) {
  return new THREE.ShaderMaterial({
    uniforms: Object.assign({}, U, own || {}), vertexShader: VERT, fragmentShader: frag,
    transparent: true, depthTest: false, depthWrite: false,
  });
}

/* How many CSS px one art pixel spans at `css` px, on whole device pixels -- never larger than
   the design, and never less than one device pixel. */
function unitOf(api, css) {
  const dpr = (api && api.viewport && api.viewport.dpr) || 1;
  return Math.max(1, Math.floor(css * dpr + 1e-6)) / dpr;
}

/* A quad, or several, as geometry: `quads` is [[x0, y0, x1, y1, a0x, a0y, a1x, a1y, side]] in CSS
   px (y down) and art px, with the art coordinates given at the two corners and each axis mapped
   linearly between them. `swap` puts the plank's length down a vertical board. */
function quadsGeometry(THREE, quads) {
  const pos = [], artc = [], side = [], idx = [];
  for (const [x0, y0, x1, y1, ax0, ay0, ax1, ay1, s, swap] of quads) {
    const base = pos.length / 3;
    const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
    for (const [x, y] of corners) {
      pos.push(x, -y, 0);
      const fx = x1 === x0 ? 0 : (x - x0) / (x1 - x0), fy = y1 === y0 ? 0 : (y - y0) / (y1 - y0);
      if (swap) artc.push(ax0 + (ax1 - ax0) * fy, ay0 + (ay1 - ay0) * fx);
      else artc.push(ax0 + (ax1 - ax0) * fx, ay0 + (ay1 - ay0) * fy);
      side.push(s || 0);
    }
    // Counter-clockwise as the camera sees it (y is flipped), so the face is towards it.
    idx.push(base, base + 2, base + 1, base, base + 3, base + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aArt", new THREE.Float32BufferAttribute(artc, 2));
  g.setAttribute("aSide", new THREE.Float32BufferAttribute(side, 1));
  g.setIndex(idx);
  return g;
}

function mesh(THREE, geometry, material, order) {
  const m = new THREE.Mesh(geometry, material);
  m.renderOrder = order;
  m.frustumCulled = false;
  return m;
}

/* ------------------------------------------------------------------------- the hooks */

/* The soil, tiled from the top-left of the viewport at the stylesheet's 2x. */
export function ground({ THREE, scene, tokens, api }) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  awaitSheet();
  const { w, h } = api.viewport;
  const u = unitOf(api, SCALE.soil);
  const mat = shader(THREE, FLAT_FRAG, {
    uMap: { value: s.textures.soil }, uGrid: { value: new THREE.Vector2(16, 16) },
    uRecolour: U.uSoilRecolour, uBase: U.uSoilBase, uRef: U.uSoilRef, uLight: { value: 1 },
  });
  scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, w, h, 0, 0, w / u, h / u, 0]]), mat, api.order.ground));
}

/* The header and the footer, laid with planks and lit flat by the band light, which skin.css
   sets low enough for their text to read on the lightest plank (theme.check, test_fleet_ink_farmstead). */
export function paper({ THREE, scene, tokens, api }) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  bands = [];
  for (const sel of ["body > header", "body > footer"]) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const mat = shader(THREE, FLAT_FRAG, {
      uMap: { value: s.textures.plank }, uGrid: { value: new THREE.Vector2(16, 8) },
      uRecolour: U.uWoodRecolour, uBase: U.uWoodBase, uRef: U.uWoodRef, uLight: U.uBandLight,
    });
    const m = mesh(THREE, quadsGeometry(THREE, [[0, 0, 1, 1, 0, 0, 1, 1, 0]]), mat, api.order.paper);
    scene.add(m);
    const band = { sel, el, mesh: m, sig: "" };
    bands.push(band);
    placeBand(THREE, api, band);
  }
}

/* A band where its element is now: the plank's rows run from the band's top edge. */
function placeBand(THREE, api, band) {
  const r = band.el.getBoundingClientRect();
  const u = unitOf(api, SCALE.band);
  const sig = [r.left, r.top, r.width, r.height, u].map(v => v.toFixed(2)).join(",");
  if (sig === band.sig) return false;
  band.sig = sig;
  const g = band.mesh.geometry;
  const x0 = r.left, y0 = r.top, x1 = r.right, y1 = r.bottom;
  const p = g.getAttribute("position"), a = g.getAttribute("aArt");
  const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  corners.forEach(([x, y], i) => {
    p.setXYZ(i, x, -y, 0);
    a.setXY(i, x / u, (y - y0) / u);
  });
  p.needsUpdate = a.needsUpdate = true;
  band.mesh.visible = r.width > 0 && r.height > 0;
  return true;
}

/* One pane: its shadow on the soil, its paper, four lit boards, and its crop. The group is at
   the pane's top-left and moves with it; this is called again only when the pane's size does. */
export function frame({ THREE, scene, tokens, api }, el, box) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  const u = unitOf(api, SCALE.board);
  const T = 8 * u, half = Math.round(4 * u * api.viewport.dpr) / api.viewport.dpr;
  const x0 = -half, y0 = -half, x1 = box.w + half, y1 = box.h + half;
  const L = (x1 - x0) / u;

  // Its shadow, cast down and right onto the soil -- pixel-hard, like the art.
  const off = SHADOW * u;
  scene.add(mesh(THREE, quadsGeometry(THREE, [[x0 + off, y0 + off, x1 + off, y1 + off, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: { value: new THREE.Vector3(0, 0, 0) }, uAlpha: { value: 0.32 } }),
                 ORDER.shadow));
  // Its paper: what the pane's text is read on (skins.py's composited panel, theme.check).
  scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, box.w, box.h, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: U.uPaper, uAlpha: { value: 1 } }), ORDER.paper));
  // Four boards: the top and bottom run the full width, the sides fit between them.
  const H = (y1 - y0 - 2 * T) / u;
  const boards = shader(THREE, BOARD_FRAG, {
    uMap: { value: s.textures.plank }, uGrid: { value: new THREE.Vector2(16, 8) },
    uRecolour: U.uWoodRecolour, uBase: U.uWoodBase, uRef: U.uWoodRef, uChar: { value: 0 },
  });
  scene.add(mesh(THREE, quadsGeometry(THREE, [
    [x0, y0, x1, y0 + T, 0, 0, L, 8, 0, false],                    // top: outer edge up
    [x1 - T, y0 + T, x1, y1 - T, 5, 8, 5 + H, 0, 1, true],         // right: outer edge right
    [x0, y1 - T, x1, y1, 11, 8, 11 + L, 0, 2, false],              // bottom: outer edge down
    [x0, y0 + T, x0 + T, y1 - T, 3, 0, 3 + H, 8, 3, true],         // left: outer edge left
  ]), boards, ORDER.board));

  // The crop, in the chip's own place (skin.css leaves the chip's glyph box empty under ink).
  const rec = recs.get(el) || { el, repo: el.dataset.repo || "", shown: cropOf(el), queue: [], rows: 16,
                                 grows: 0, stage: GROWS.indexOf(cropOf(el)) };
  rec.repo = el.dataset.repo || rec.repo;
  const cu = unitOf(api, SCALE.crop);
  const crop = new THREE.ShaderMaterial({
    uniforms: { uOld: { value: s.textures[rec.shown] }, uNew: { value: s.textures[rec.shown] }, uRows: { value: 16 } },
    vertexShader: VERT, fragmentShader: CROP_FRAG, transparent: true, depthTest: false, depthWrite: false,
  });
  rec.crop = mesh(THREE, quadsGeometry(THREE, [[0, 0, 16 * cu, 16 * cu, 0, 0, 16, 16, 0]]), crop, ORDER.crop);
  rec.cropSize = 16 * cu;
  rec.boards = boards;
  rec.box = { w: box.w, h: box.h };
  rec.frame = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, thick: T };
  rec.at = "";
  scene.add(rec.crop);
  recs.set(el, rec);
  place(rec, api);
  paint(rec);
}

/* Which crop the pane's classes say: the chip's own sprite (skin.css, #157). */
function cropOf(el) {
  const c = el.classList;
  if (c.contains("needs-human") || c.contains("state-needs_human") || c.contains("state-blocked") ||
      c.contains("state-error")) return "crop-wilted";
  if (c.contains("state-done")) return "crop-bloom";
  if (c.contains("state-waiting_approval")) return "crop-sun";
  if (c.contains("state-running")) return "crop-sprout";
  return "crop-seed";
}

/* The crop over the chip's glyph box: the chip's content box, left edge, centred on its height,
   snapped to whole device pixels on the page (the group is at the pane's fractional top-left). */
function place(rec, api) {
  const chip = rec.el.querySelector(".head .chip");
  const m = rec.crop;
  if (!chip || !m) return false;
  const r = chip.getBoundingClientRect();
  const p = rec.el.getBoundingClientRect();
  const sig = [r.left, r.top, r.width, r.height, p.left, p.top].map(v => v.toFixed(2)).join(",");
  if (sig === rec.at) return false;
  rec.at = sig;
  const visible = r.width > 0 && r.height > 0 && p.width > 0;
  m.visible = visible;
  if (!visible) return true;
  const cs = getComputedStyle(chip);
  const px = n => parseFloat(n) || 0;
  const dpr = api.viewport.dpr || 1;
  const snap = v => Math.round(v * dpr) / dpr;
  const left = r.left + px(cs.borderLeftWidth) + px(cs.paddingLeft);
  const top = r.top + px(cs.borderTopWidth) + px(cs.paddingTop);
  const inner = r.height - px(cs.borderTopWidth) - px(cs.borderBottomWidth) - px(cs.paddingTop) - px(cs.paddingBottom);
  const x = snap(left + (16 - rec.cropSize) / 2), y = snap(top + (inner - rec.cropSize) / 2);
  m.position.set(x - p.left, -(y - p.top), 0);
  rec.cropAt = { x, y, size: rec.cropSize };
  return true;
}

function paint(rec) {
  const s = sheet;
  if (!s || !rec.crop) return;
  const u = rec.crop.material.uniforms;
  const growing = rec.queue.length ? rec.queue[0] : rec.shown;
  u.uOld.value = s.textures[rec.shown];
  u.uNew.value = s.textures[growing];
  u.uRows.value = rec.queue.length ? Math.min(16, Math.floor(rec.rows)) : 16;
  rec.boards.uniforms.uChar.value = rec.el.classList.contains("state-error") ? 1 : 0;
}

/* What a crop must grow through to reach `to`: one stage at a time along GROWS when the phase
   advances; anything else (a wilt, the sun, a crop replanted) is drawn in one pass. */
function stepsTo(from, to) {
  const a = GROWS.indexOf(from), b = GROWS.indexOf(to);
  if (a >= 0 && b > a) return GROWS.slice(a + 1, b + 1);
  return [to];
}

/* Every frame the layer draws: the crops that must grow, the bands that moved, the materials'
   inputs. Answers true while a crop is still growing. */
export function tick({ THREE, tokens, api }, dt) {
  lastApi = api;
  if (!U) return false;
  let changed = readLook(THREE, tokens);
  for (const band of bands) if (band.el.isConnected && placeBand(THREE, api, band)) changed = true;
  let more = false;
  const instant = !!api.reduced;
  for (const [el, rec] of Array.from(recs)) {
    if (!el.isConnected) { recs.delete(el); continue; }
    const want = cropOf(el);
    const last = rec.queue.length ? rec.queue[rec.queue.length - 1] : rec.shown;
    if (want !== last) {
      if (!rec.queue.length) rec.rows = 0;
      let prev = last;
      for (const step of stepsTo(last, want)) {
        // A stage grown: the phase advanced along the crop's own line, never a wilt or a sun.
        if (GROWS.indexOf(prev) >= 0 && GROWS.indexOf(step) > GROWS.indexOf(prev)) rec.grows += 1;
        rec.queue.push(step);
        prev = step;
      }
    }
    if (rec.queue.length) {
      rec.rows = instant ? 16 : rec.rows + Math.max(1, dt * ROWS_PER_S);
      while (rec.queue.length && rec.rows >= 16) {
        rec.shown = rec.queue.shift();
        rec.rows = rec.queue.length ? (instant ? 16 : 0) : 16;
      }
      if (rec.queue.length) more = true;
      changed = true;
    }
    rec.stage = GROWS.indexOf(rec.shown);
    if (place(rec, api)) changed = true;
    paint(rec);
  }
  if (changed) api.request();
  return more;
}

/* The skin is going: the layer frees what is in its scenes, and the textures are freed here. */
export function dispose() {
  if (sheet) {
    for (const t of Object.values(sheet.textures)) { t.dispose(); freed += 1; }
  }
  sheet = null;
  U = null;
  look = "";
  bands = [];
  recs.clear();
}

/* For the tests and a curious console: what this skin has on the paper. */
export function inspect() {
  const T = sheet && Object.values(sheet.textures);
  const panes = {};
  for (const rec of recs.values()) {
    panes[rec.repo] = {
      shown: rec.shown, growing: rec.queue.slice(), rows: rec.queue.length ? Math.floor(rec.rows) : 16,
      stage: GROWS.indexOf(rec.shown), grows: rec.grows, crop: rec.cropAt || null,
      visible: !!(rec.crop && rec.crop.visible), box: rec.box, frame: rec.frame,
      scorched: !!(rec.boards && rec.boards.uniforms.uChar.value),
    };
  }
  return {
    loaded: !!(sheet && sheet.loaded), failed: sheet ? sheet.failed : "", raster: RASTER,
    textures: made - freed, made, freed,
    nearest: !!T && T.every(t => t.magFilter === sheet.nearest && t.minFilter === sheet.nearest &&
                                 !t.generateMipmaps),
    sizes: T ? Object.fromEntries(SPRITES.map(id => [id, [sheet.canvases[id].width, sheet.canvases[id].height]])) : {},
    gpuTextures: lastApi && lastApi.renderer ? lastApi.renderer.info.memory.textures : null,
    units: lastApi ? { soil: unitOf(lastApi, SCALE.soil), board: unitOf(lastApi, SCALE.board),
                       crop: unitOf(lastApi, SCALE.crop), dpr: lastApi.viewport.dpr } : null,
    bands: bands.map(b => ({ sel: b.sel, sig: b.sig })),
    panes,
  };
}
