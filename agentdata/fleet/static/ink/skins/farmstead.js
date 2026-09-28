const SHEET = "/static/skins/farmstead/sprites.svg";
const RASTER = 1;
const CROPS = ["crop-seed", "crop-sprout", "crop-sun", "crop-bloom", "crop-wilted"];
const PROPS = ["produce", "cloud", "hen-a", "hen-b", "cat-sleep", "cat-stretch", "crow"];
const SPRITES = ["soil", "plank"].concat(CROPS, PROPS);
const SIZE = { plank: [16, 8], produce: [8, 8], cloud: [16, 8], "hen-a": [12, 12], "hen-b": [12, 12],
               "cat-sleep": [16, 8], "cat-stretch": [16, 8], crow: [8, 8] };
const GROWS = ["crop-seed", "crop-sprout", "crop-bloom"];
const ROWS_PER_S = 60;
const SCALE = { soil: 2, band: 2, board: 1, crop: 2 };
const CROP_ART = [2, 14];
const CROP_BOX = 24;
const SHADOW = 3;
const ORDER = { shadow: -13, paper: -12, board: -11, crop: -10, produce: -11.5, shower: -10.5 };
const FRAME = 1 / 60;
const PRODUCE = 3;
const PRODUCE_GAP = 0.12;
const PRODUCE_RISE = 0.25;
const PRODUCE_DRIFT = 2;
const SINK_ROWS = 2;
const HARVEST_WAIT = 40;
const STREAKS = 12;
const STREAK_GAP = 0.05;
const RAIN = 700;
const RAIN_END = 1.15;
const CLOUD_GOES = 0.9;
const SHOWER = 1.2;
const HEN_RUN = 1.1;
const HEN_STEP = 0.08;
const HEN_GOES = 4;
const HEN_GLYPHS = 256;
const EGG_ORDER = -10.5;
const STRETCH = 0.15;
const CAT_GOES = 0.45;
const GLIDE = 0.25;
const FIREFLIES = 6;
const FLY_AMP = 6;
const FLY_STEP = 0.07;

export const RARE = { cat: 3, crow: 3 };

export function marks() {
  return [
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-choice:not([aria-pressed=\"true\"])",
      tool: "pencil", shape: "loop" },
    { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
    { selector: ".tile.state-error .why", tool: "marker", shape: "loop", pad: 0 },
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", pad: 0, dash: true },
    { selector: ".tile .asks:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: 2 },
    { selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse", pad: 2 },
  ];
}

export const options = { hand: true, speed: 1, fx: { text: true } };

export const cues = [
  { selector: "#grid > .tile:is(.state-done, .is-done)", on: "arrive", cue: "harvest" },
  { selector: "#grid > .tile.state-error", on: "arrive", cue: "shower" },
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "hen" },
];

export const sampleGround = false;

let sheet = null;
let made = 0, freed = 0;
let lastApi = null;
let U = null;
let look = "";
let bands = [];
const recs = new Map();
const waited = new WeakSet();
let hens = [];
const played = { harvest: 0, shower: 0, hen: 0 };
let skipped = 0;
let gmade = 0, gfreed = 0;
let flies = null;

function commonest(px) {
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

function pixels(doc, id, s) {
  const node = doc.getElementById(id) || doc.querySelector("[id=\"" + id + "\"]");
  if (!node) throw new Error("sprites.svg has no #" + id);
  const [w, h] = s.sizes[id];
  const px = s.data[id];
  px.fill(0);
  for (const r of node.getElementsByTagName("rect")) {
    const hex = /^#([0-9a-f]{6})$/i.exec(r.getAttribute("fill") || "");
    if (!hex) throw new Error("#" + id + ": a rect whose fill is not #rrggbb");
    const n = parseInt(hex[1], 16), rgb = [n >> 16 & 255, n >> 8 & 255, n & 255];
    const x0 = Number(r.getAttribute("x") || 0), y0 = Number(r.getAttribute("y") || 0);
    const x1 = Math.min(w, x0 + Number(r.getAttribute("width") || 0));
    const y1 = Math.min(h, y0 + Number(r.getAttribute("height") || 0));
    for (let y = Math.max(0, y0); y < y1; y++) {
      for (let x = Math.max(0, x0); x < x1; x++) {
        const i = (y * w + x) * 4;
        px[i] = rgb[0]; px[i + 1] = rgb[1]; px[i + 2] = rgb[2]; px[i + 3] = 255;
      }
    }
  }
  s.base[id] = commonest(px);
}

function load(THREE, api) {
  if (sheet) return sheet;
  const s = sheet = { textures: {}, data: {}, sizes: {}, base: {}, loaded: false, failed: "",
                      nearest: THREE.NearestFilter };
  for (const id of SPRITES) {
    const [w, h] = (SIZE[id] || [16, 16]).map(n => n * RASTER);
    s.sizes[id] = [w, h];
    s.data[id] = new Uint8Array(w * h * 4);
    const t = new THREE.DataTexture(s.data[id], w, h, THREE.RGBAFormat);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.flipY = false;
    t.colorSpace = THREE.NoColorSpace;
    s.textures[id] = t;
    made += 1;
  }
  fetch(q(SHEET)).then(r => {
    if (!r.ok) throw new Error("sprites.svg answered " + r.status);
    return r.text();
  }).then(text => {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("sprites.svg does not parse");
    for (const id of SPRITES) pixels(doc, id, s);
    if (sheet !== s) return;
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

const FLAT_FRAG = GLSL_COMMON + `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform float uRecolour; uniform vec3 uBase;
  uniform vec3 uRef; uniform float uLight; uniform vec3 uSun;
  varying vec2 vArt;
  void main() {
    vec3 c = art(uMap, uGrid, vArt, uRecolour, uBase, uRef) * uLight * toLin(uSun);
    gl_FragColor = vec4(toSrgb(c), 1.0);
  }`;

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

const CROP_FRAG = `
  uniform sampler2D uOld; uniform sampler2D uNew; uniform float uRows;
  varying vec2 vArt;
  void main() {
    vec2 t = floor(vArt);
    vec4 c = (15.0 - t.y) < uRows ? texture2D(uNew, (t + 0.5) / 16.0) : texture2D(uOld, (t + 0.5) / 16.0);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb, 1.0);
  }`;

const SPRITE_FRAG = `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform vec2 uKeep;
  varying vec2 vArt;
  void main() {
    vec2 t = floor(vArt);
    if (t.x >= uKeep.x || t.y >= uKeep.y) discard;
    vec4 c = texture2D(uMap, (t + 0.5) / uGrid);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb, 1.0);
  }`;

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

function rgbOf(THREE, text) {
  const s = String(text || "").trim();
  if (!s) return null;
  const c = new THREE.Color();
  try { c.setStyle(s, THREE.SRGBColorSpace); } catch (e) { return null; }
  const o = { r: 0, g: 0, b: 0 };
  c.getRGB(o, THREE.SRGBColorSpace);
  return [o.r, o.g, o.b];
}

let rainCss = "";

function rainOf() {
  return rainCss;
}

function readLook(THREE, tokens) {
  const u = uniforms(THREE);
  const css = name => (tokens && typeof tokens.css === "function" ? tokens.css(name) : "");
  const sig = ["--farm-paper", "--farm-soil", "--farm-wood", "--farm-sun", "--farm-band-light",
               "--farm-ambient", "--farm-diffuse"].map(css).join("|") +
              "|" + String(tokens && tokens.human) + "|" + String(tokens && tokens.panel);
  rainCss = css("--farm-rain");
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

function unitOf(api, css) {
  const dpr = (api && api.viewport && api.viewport.dpr) || 1;
  return Math.max(1, Math.floor(css * dpr + 1e-6)) / dpr;
}

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
  fireflies(THREE, scene, tokens, api);
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  h ^= h >>> 13;
  return Math.imul(h, 2246822507) >>> 0;
}

function lucky(key, n) {
  return hash(key) % Math.max(1, Math.floor(Number(n)) || 1) === 0;
}

function fireflies(THREE, scene, tokens, api) {
  if (flies) gfreed += 1;
  flies = null;
  const col = rgbOf(THREE, tokens && typeof tokens.css === "function" ? tokens.css("--farm-firefly") : "");
  if (!col) return;
  const u = unitOf(api, 1), size = 2 * u, { w, h } = api.viewport, pad = FLY_AMP + size + 12;
  const covered = api.panes().map(p => p.box).concat(bands.map(b => {
    const r = b.el.getBoundingClientRect();
    return { x: r.left, y: r.top, w: r.width, h: r.height };
  }));
  const geometry = quadsGeometry(THREE, [[0, 0, size, size, 0, 0, 1, 1, 0]]);
  const material = shader(THREE, FILL_FRAG, { uColor: { value: new THREE.Vector3().fromArray(col) }, uAlpha: { value: 1 } });
  gmade += 1;
  flies = { geometry, material, list: [] };
  for (let i = 0; i < 600 && flies.list.length < FIREFLIES; i++) {
    const x = pad + (hash("fly:x" + i) / 4294967296) * Math.max(0, w - 2 * pad);
    const y = pad + (hash("fly:y" + i) / 4294967296) * Math.max(0, h - 2 * pad);
    if (covered.some(r => x > r.x - pad && x < r.x + r.w + pad && y > r.y - pad && y < r.y + r.h + pad)) continue;
    const m = mesh(THREE, geometry, material, api.order.paper + 0.5);
    scene.add(m);
    const n = flies.list.length;
    const f = { m, cx: x, cy: y, a: 1 + (n % 3), b: 2 + (n % 2), ph: n * 1.7, k: 0, x, y };
    flies.list.push(f);
    fly(f);
  }
}

function fly(f) {
  f.x = f.cx + FLY_AMP * Math.sin(f.a * f.k * FLY_STEP + f.ph);
  f.y = f.cy + FLY_AMP * Math.sin(f.b * f.k * FLY_STEP);
  at(f.m, f.x, f.y);
}

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

export function frame({ THREE, scene, tokens, api }, el, box) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  const u = unitOf(api, SCALE.board);
  const T = 8 * u, half = Math.round(4 * u * api.viewport.dpr) / api.viewport.dpr;
  const x0 = -half, y0 = -half, x1 = box.w + half, y1 = box.h + half;
  const L = (x1 - x0) / u;

  const off = SHADOW * u;
  scene.add(mesh(THREE, quadsGeometry(THREE, [[x0 + off, y0 + off, x1 + off, y1 + off, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: { value: new THREE.Vector3(0, 0, 0) }, uAlpha: { value: 0.32 } }),
                 ORDER.shadow));
  scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, box.w, box.h, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: U.uPaper, uAlpha: { value: 1 } }), ORDER.paper));
  const H = (y1 - y0 - 2 * T) / u;
  const boards = shader(THREE, BOARD_FRAG, {
    uMap: { value: s.textures.plank }, uGrid: { value: new THREE.Vector2(16, 8) },
    uRecolour: U.uWoodRecolour, uBase: U.uWoodBase, uRef: U.uWoodRef, uChar: { value: 0 },
  });
  scene.add(mesh(THREE, quadsGeometry(THREE, [
    [x0, y0, x1, y0 + T, 0, 0, L, 8, 0, false],
    [x1 - T, y0 + T, x1, y1 - T, 5, 8, 5 + H, 0, 1, true],
    [x0, y1 - T, x1, y1, 11, 8, 11 + L, 0, 2, false],
    [x0, y0 + T, x0 + T, y1 - T, 3, 0, 3 + H, 8, 3, true],
  ]), boards, ORDER.board));

  const rec = recs.get(el) || { el, repo: el.dataset.repo || "", shown: cropOf(el), queue: [], rows: 16,
                                 grows: 0, stage: GROWS.indexOf(cropOf(el)) };
  rec.repo = el.dataset.repo || rec.repo;
  rec.group = scene;
  forgetFx(rec);
  rec.eggs = rec.eggs || { cat: null, crow: null };
  for (const e of Object.values(rec.eggs)) if (e && e.mesh) { gfreed += 1; e.mesh = null; }
  const cu = unitOf(api, SCALE.crop);
  const crop = new THREE.ShaderMaterial({
    uniforms: { uOld: { value: s.textures[rec.shown] }, uNew: { value: s.textures[rec.shown] }, uRows: { value: 16 } },
    vertexShader: VERT, fragmentShader: CROP_FRAG, transparent: true, depthTest: false, depthWrite: false,
  });
  const [a0, a1] = CROP_ART, span = (a1 - a0) * cu;
  rec.crop = mesh(THREE, quadsGeometry(THREE, [[0, 0, span, span, a0, a0, a1, a1, 0]]), crop, ORDER.crop);
  rec.cropSize = span;
  rec.boards = boards;
  rec.box = { w: box.w, h: box.h };
  rec.frame = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, thick: T };
  rec.at = "";
  scene.add(rec.crop);
  recs.set(el, rec);
  place(rec, api);
  paint(rec);
  for (const kind of ["cat", "crow"]) {
    const e = rec.eggs[kind];
    if (!e || e.skip) continue;
    if (e.phase === "out") { rec.eggs[kind] = null; continue; }
    rec.eggs[kind] = eggOn(THREE, api, rec, kind, true);
  }
}

function cropOf(el) {
  const c = el.classList;
  if (c.contains("needs-human") || c.contains("state-needs_human") || c.contains("state-blocked") ||
      c.contains("state-error")) return "crop-wilted";
  if (c.contains("state-done") || c.contains("is-done")) return "crop-bloom";
  if (c.contains("state-waiting_approval")) return "crop-sun";
  if (c.contains("state-running")) return "crop-sprout";
  return "crop-seed";
}

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
  const x = snap(left + (CROP_BOX - rec.cropSize) / 2), y = snap(top + (inner - rec.cropSize) / 2);
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

function stepsTo(from, to) {
  const a = GROWS.indexOf(from), b = GROWS.indexOf(to);
  if (a >= 0 && b > a) return GROWS.slice(a + 1, b + 1);
  return [to];
}

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
  const step = Math.max(dt, FRAME);
  let live = false;
  for (const rec of recs.values()) {
    if (rec.harvest && harvest(THREE, api, rec, step)) live = true;
    if (rec.shower && shower(rec, step)) live = true;
  }
  hens = hens.filter(h => run(h, step, api));
  if (hens.length) live = true;
  const b = document.body.classList;
  const quick = instant || b.contains("is-stale") || b.contains("is-replaying");
  for (const rec of recs.values()) if (eggs(THREE, api, rec, step, quick)) live = true;
  if (flies && !instant) for (const f of flies.list) { f.k += 1; fly(f); }
  if (changed || live) api.request();
  return more || live;
}

function wants(rec) {
  const c = rec.el.classList, needs = c.contains("needs-human") || c.contains("state-needs_human");
  return {
    cat: !needs && !!rec.el.querySelector(".chip.stale") && lucky(rec.repo, RARE.cat),
    crow: !needs && (c.contains("state-done") || c.contains("is-done")) && lucky(rec.repo + ":crow", RARE.crow),
  };
}

function rest(api, rec, kind) {
  const u = unitOf(api, 1), f = rec.frame, T = f.thick;
  if (kind === "cat") return { x: f.x + f.w - T - 16 * u, y: f.y, w: 16 * u, h: T };
  const c = rec.crop && rec.crop.visible ? rec.crop.position.x + rec.cropSize / 2 - 4 * u : f.x + f.w / 2;
  return { x: Math.max(f.x + T, Math.min(f.x + f.w - T - 8 * u, c)), y: f.y, w: 8 * u, h: T };
}

function crosses(api, rec, r) {
  if (!api.fx || !api.fx.lines) return false;
  const head = rec.el.querySelector(".head");
  if (!head) return false;
  const p = rec.el.getBoundingClientRect(), x = p.left + r.x, y = p.top + r.y;
  return api.fx.lines(head).some(l => x < l.x + l.w && l.x < x + r.w && y < l.y + l.h && l.y < y + r.h);
}

function eggOn(THREE, api, rec, kind, quick) {
  const r = rest(api, rec, kind);
  if (crosses(api, rec, r)) { skipped += 1; return { kind, skip: true }; }
  const m = sprite(THREE, kind === "cat" ? "cat-sleep" : "crow", r.w, r.h, false);
  m.renderOrder = EGG_ORDER;
  rec.group.add(m);
  const e = { kind, mesh: m, rest: r, x: r.x, y: r.y, t: 0, phase: "rest" };
  if (kind === "crow" && !quick) { e.phase = "in"; e.x = rec.frame.x + rec.frame.w - rec.frame.thick - r.w; }
  at(m, e.x, e.y);
  return e;
}

function dropEgg(e) {
  if (e && e.mesh) drop(e.mesh);
  if (e) e.mesh = null;
}

function eggs(THREE, api, rec, dt, quick) {
  if (!rec.group || !rec.frame || !rec.eggs || !sheet || !sheet.loaded) return false;
  const w = wants(rec), first = !rec.hatched;
  rec.hatched = true;
  let moving = false;
  for (const kind of ["cat", "crow"]) {
    let e = rec.eggs[kind];
    if (w[kind] && (!e || e.phase === "out")) {
      dropEgg(e);
      e = rec.eggs[kind] = eggOn(THREE, api, rec, kind, quick || first);
    } else if (!w[kind] && e && e.phase !== "out") {
      if (quick || e.skip || !e.mesh) { dropEgg(e); rec.eggs[kind] = null; continue; }
      e.phase = "out";
      e.t = 0;
      if (kind === "cat") {
        drop(e.mesh);
        e.mesh = sprite(THREE, "cat-stretch", e.rest.w, e.rest.h, false);
        e.mesh.renderOrder = EGG_ORDER;
        rec.group.add(e.mesh);
      }
    }
    if (!e || e.skip || !e.mesh || e.phase === "rest") continue;
    e.t += dt;
    const f = rec.frame, end = f.x + f.w - f.thick - e.rest.w;
    if (e.phase === "in") {
      const k = Math.min(1, e.t / GLIDE);
      e.x = end + (e.rest.x - end) * k * (2 - k);
      if (k >= 1) e.phase = "rest";
    } else if (kind === "crow") {
      const k = Math.min(1, e.t / GLIDE);
      e.x = e.rest.x + (end - e.rest.x) * k * k;
      if (k >= 1) { dropEgg(e); rec.eggs[kind] = null; continue; }
    } else if (e.t > STRETCH) {
      const k = Math.min(1, (e.t - STRETCH) / (CAT_GOES - STRETCH - 2 * FRAME));
      e.x = e.rest.x + (f.x + f.w - e.rest.x) * k;
      if (k >= 1) { dropEgg(e); rec.eggs[kind] = null; continue; }
    }
    at(e.mesh, e.x, e.y);
    moving = true;
  }
  return moving;
}

function sprite(THREE, name, w, h, flip) {
  const [gw, gh] = sheet.sizes[name];
  const mat = new THREE.ShaderMaterial({
    uniforms: { uMap: { value: sheet.textures[name] }, uGrid: { value: new THREE.Vector2(gw, gh) },
                uKeep: { value: new THREE.Vector2(gw, gh) } },
    vertexShader: VERT, fragmentShader: SPRITE_FRAG, transparent: true, depthTest: false, depthWrite: false,
  });
  gmade += 1;
  return mesh(THREE, quadsGeometry(THREE, [[0, 0, w, h, flip ? gw : 0, 0, flip ? 0 : gw, gh, 0]]), mat, 0);
}

function drop(m) {
  if (!m) return;
  m.removeFromParent();
  m.geometry.dispose();
  m.material.dispose();
  gfreed += 1;
}

function forgetFx(rec) {
  if (rec.harvest) gfreed += rec.harvest.pieces.filter(q => q.mesh).length;
  if (rec.shower) gfreed += 1 + (rec.shower.cloud ? 1 : 0);
  rec.harvest = rec.shower = null;
}

function at(m, x, y) {
  m.position.set(x, -y, 0);
}

export function cue({ THREE, scene, api }, name, el, box, how) {
  lastApi = api;
  if (api.reduced || !sheet || !sheet.loaded || !U) return;
  const rec = recs.get(el);
  if (name === "harvest" && rec && rec.group) {
    endHarvest(rec);
    rec.harvest = { waited: 0, t: -1, pieces: [] };
    played.harvest += 1;
  } else if (name === "shower" && rec && rec.group) {
    showerOn(THREE, api, rec);
  } else if (name === "hen" && !el.classList.contains("is-grouped")) {
    henOn(THREE, scene, api, box, how);
  }
  api.request();
}

function endHarvest(rec) {
  if (rec.harvest) for (const q of rec.harvest.pieces) drop(q.mesh);
  rec.harvest = null;
}

function harvest(THREE, api, rec, dt) {
  const h = rec.harvest;
  if (h.t < 0) {
    if (rec.shown !== "crop-bloom" || rec.queue.length || !rec.crop) {
      h.waited += 1;
      if (h.waited > HARVEST_WAIT) endHarvest(rec);
      return !!rec.harvest;
    }
    const u = unitOf(api, 1), size = SIZE.produce[0] * u, c = rec.crop.position;
    const cx = c.x + rec.cropSize / 2, cy = -c.y + rec.cropSize / 2;
    const land = rec.frame.y + rec.frame.thick;
    for (let i = 0; i < PRODUCE; i++) {
      const m = sprite(THREE, "produce", size, size, false);
      m.renderOrder = ORDER.produce;
      m.visible = false;
      rec.group.add(m);
      h.pieces.push({ mesh: m, start: i * PRODUCE_GAP, x0: cx - size / 2, y0: cy - size / 2, y1: land,
                      size, row: size / SIZE.produce[1], sunk: 0 });
    }
    h.t = 0;
  }
  h.t += dt;
  for (const q of h.pieces) {
    if (!q.mesh || h.t < q.start) continue;
    const k = Math.min(1, (h.t - q.start) / PRODUCE_RISE), e = 1 - (1 - k) * (1 - k);
    q.x = q.x0 - PRODUCE_DRIFT * e;
    q.y = q.y0 + (q.y1 - q.y0) * e;
    if (k >= 1) {
      q.sunk += 1;
      q.y = q.y1 - SINK_ROWS * q.row * q.sunk;
      if (q.y + q.size <= q.y1) { drop(q.mesh); q.mesh = null; continue; }
    }
    q.mesh.visible = true;
    at(q.mesh, q.x, q.y);
  }
  h.pieces = h.pieces.filter(q => q.mesh);
  if (!h.pieces.length) rec.harvest = null;
  return !!rec.harvest;
}

function endShower(rec) {
  if (!rec.shower) return;
  drop(rec.shower.cloud);
  for (const q of rec.shower.streaks) q.mesh.removeFromParent();
  rec.shower.geometry.dispose();
  rec.shower.material.dispose();
  gfreed += 1;
  rec.shower = null;
}

function showerOn(THREE, api, rec) {
  endShower(rec);
  const u = unitOf(api, 1), f = rec.frame, T = f.thick;
  const [cw, ch] = SIZE.cloud;
  const cloud = sprite(THREE, "cloud", cw * u, ch * u, false);
  cloud.renderOrder = ORDER.shower;
  const cx = f.x + T / 2 - cw * u / 2, cy = f.y + T / 2 - ch * u / 2;
  at(cloud, cx, cy);
  rec.group.add(cloud);
  const colour = new THREE.Vector3().fromArray(rgbOf(THREE, rainOf()) || U.uPaper.value.toArray());
  const material = shader(THREE, FILL_FRAG, { uColor: { value: colour }, uAlpha: { value: 1 } });
  const w = u, h = 3 * u, geometry = quadsGeometry(THREE, [[0, 0, w, h, 0, 0, 1, 1, 0]]);
  gmade += 1;
  const top = cy + ch * u, bottom = f.y + f.h - T;
  const streaks = [];
  for (let i = 0; i < STREAKS; i++) {
    const m = mesh(THREE, geometry, material, ORDER.shower);
    m.visible = false;
    rec.group.add(m);
    const start = i * STREAK_GAP;
    streaks.push({ mesh: m, start, x: f.x + ((i % 4) + 0.5) * T / 4 - w / 2,
                   y0: Math.max(top, bottom - h - RAIN * (RAIN_END - start)), h, bottom });
  }
  rec.shower = { t: 0, cloud, cloudRows: ch, streaks, geometry, material, colour };
  played.shower += 1;
}

function shower(rec, dt) {
  const sh = rec.shower;
  sh.t += dt;
  if (sh.cloud) {
    const rows = sh.t < CLOUD_GOES ? sh.cloudRows : Math.ceil(sh.cloudRows * (1 - (sh.t - CLOUD_GOES) / (SHOWER - CLOUD_GOES)));
    if (rows <= 0) { drop(sh.cloud); sh.cloud = null; } else sh.cloud.material.uniforms.uKeep.value.y = rows;
  }
  for (const q of sh.streaks) {
    if (q.done || sh.t < q.start) continue;
    q.y = q.y0 + RAIN * (sh.t - q.start);
    if (q.y + q.h >= q.bottom) { q.done = true; q.mesh.removeFromParent(); continue; }
    q.mesh.visible = true;
    at(q.mesh, q.x, q.y);
  }
  if (sh.cloud || sh.streaks.some(q => !q.done)) return true;
  endShower(rec);
  return false;
}

function henOn(THREE, scene, api, box, how) {
  const footer = document.querySelector("body > footer"), f = footer && footer.getBoundingClientRect();
  if (!f || !f.height || !api.fx || !api.fx.glyphs) { skipped += 1; return; }
  const glyphs = api.fx.glyphs(footer, HEN_GLYPHS).filter(b => b.w > 0 && b.h > 0);
  const first = glyphs.length ? Math.min(...glyphs.map(b => b.y)) : f.bottom;
  const u = unitOf(api, 1), [gw, gh] = SIZE["hen-a"], w = gw * u, h = gh * u;
  if (first - f.top < h) { skipped += 1; return; }
  const vw = api.viewport.w;
  const count = document.getElementById("hiddencount"), c = count && !count.hidden ? count.getBoundingClientRect() : null;
  const home = how === "unmatched" && c && c.width ? c.left - w : null;
  const x0 = Math.max(0, Math.min(vw - w, box.x));
  const to = home !== null ? home : (x0 + w / 2 < vw / 2 ? -w : vw);
  const flip = to < x0;
  const hen = { x: x0, y: Math.max(f.top, first - h - 1), w, h, x0, to, flip, t: 0, gone: -1, home: home !== null, frames: [] };
  for (const name of ["hen-a", "hen-b"]) {
    const m = sprite(THREE, name, w, h, flip);
    m.renderOrder = api.order.fx;
    m.visible = false;
    scene.add(m);
    hen.frames.push(m);
  }
  hens.push(hen);
  played.hen += 1;
}

function run(hen, dt, api) {
  if (hen.gone >= 0) {
    hen.gone += 1;
    for (const m of hen.frames) m.material.uniforms.uKeep.value.x = SIZE["hen-a"][0] * (1 - hen.gone / HEN_GOES);
    if (hen.gone >= HEN_GOES) { hen.frames.forEach(drop); return false; }
    return true;
  }
  hen.t += dt;
  const k = Math.min(1, hen.t / HEN_RUN);
  hen.x = hen.x0 + (hen.to - hen.x0) * k;
  const shown = Math.floor(hen.t / HEN_STEP) % 2;
  hen.frames.forEach((m, i) => { m.visible = i === shown; at(m, hen.x, hen.y); });
  if (k < 1) return true;
  if (!hen.home) { hen.frames.forEach(drop); return false; }
  hen.gone = 0;
  return true;
}

export function dispose() {
  if (sheet) {
    for (const t of Object.values(sheet.textures)) { t.dispose(); freed += 1; }
  }
  sheet = null;
  U = null;
  look = "";
  bands = [];
  recs.clear();
  hens = [];
  flies = null;
  gmade = gfreed = 0;
}

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
    sizes: T ? Object.fromEntries(SPRITES.map(id => [id, sheet.sizes[id].slice()])) : {},
    gpuTextures: lastApi && lastApi.renderer ? lastApi.renderer.info.memory.textures : null,
    units: lastApi ? { soil: unitOf(lastApi, SCALE.soil), board: unitOf(lastApi, SCALE.board),
                       crop: unitOf(lastApi, SCALE.crop), dpr: lastApi.viewport.dpr } : null,
    bands: bands.map(b => ({ sel: b.sel, sig: b.sig })),
    panes,
    fx: fxOf(),
  };
}

function fxOf() {
  const pieces = [];
  const put = (name, m, x, y, w, h, el) => {
    if (!m || !m.visible || !m.parent) return;
    const p = el ? el.getBoundingClientRect() : { left: 0, top: 0 };
    pieces.push({ sprite: name, x: p.left + x, y: p.top + y, w, h });
  };
  let live = hens.length;
  for (const rec of recs.values()) {
    const g = rec.group && rec.group.visible ? rec.el : null;
    if (rec.harvest) {
      live += 1;
      for (const q of rec.harvest.pieces) if (g) put("produce", q.mesh, q.x, q.y, q.size, q.size, g);
    }
    if (rec.shower) {
      live += 1;
      const sh = rec.shower, c = sh.cloud;
      const u = unitOf(lastApi, 1);
      if (c && g) put("cloud", c, c.position.x, -c.position.y, SIZE.cloud[0] * u, c.material.uniforms.uKeep.value.y * u, g);
      for (const q of sh.streaks) if (!q.done && g) put("rain", q.mesh, q.x, q.y, u, q.h, g);
    }
  }
  for (const hen of hens) {
    hen.frames.forEach((m, i) => put(i ? "hen-b" : "hen-a", m, hen.x, hen.y, hen.w, hen.h, null));
  }
  const eggs = { cat: [], crow: [], fireflies: flies ? flies.list.map(f => ({ x: f.x, y: f.y })) : [], rects: [] };
  for (const rec of recs.values()) {
    for (const e of Object.values(rec.eggs || {})) {
      if (!e || !e.mesh || !e.mesh.parent) continue;
      eggs[e.kind].push(rec.repo);
      if (e.phase !== "rest") live += 1;
      const p = rec.el.getBoundingClientRect();
      eggs.rects.push({ kind: e.kind, repo: rec.repo, phase: e.phase, x: p.left + e.x, y: p.top + e.y, w: e.rest.w, h: e.rest.h });
    }
  }
  return { live, played: Object.assign({}, played), skipped, geometries: gmade - gfreed, pieces, eggs };
}
