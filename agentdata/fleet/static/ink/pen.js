/* The ink layer's tools (#248): how each one lays a stroke down, and the shaders that make it look
   like graphite, ballpoint, felt or highlighter rather than a line.

   Ported from the operator-approved prototype (`notebook-three.html`, epic #246 Decision 1). Two
   halves: `geometry()` is plain arithmetic -- resample the path, give it the tool's wobble, bow,
   pressure and taper -- and `makePen(THREE)` turns that into three.js meshes, materials and the
   small lit pencil (the hand) that travels along a stroke while it is drawn. three.js is handed in
   by `layer.js`, which is the one module that imports it, from the vendored copy, with the token.

   A tool is a `kind` for the shader and its physics: `w` the width, `press` and `pvar` the
   pressure and how much it varies, `wob` and `lam` the wobble and its wavelength, `bow` how much a
   long stroke sags, `pad` the antialiasing margin, `wmin` how thin light pressure goes, `tin` and
   `tout` the taper at each end. Colour is not here: a palette colours the inks (`layer.js` reads
   them from the page's custom properties at paint time), and a skin chooses the paper. */

export const TOOLS = {
  pencil: { kind: 0, w: 1.9, press: 0.7, pvar: 0.28, wob: 0.85, lam: 70, bow: 0.006, pad: 1.4, wmin: 0.72, tin: 10, tout: 16, model: "pencil" },
  pen: { kind: 1, w: 1.45, press: 0.85, pvar: 0.15, wob: 0.4, lam: 110, bow: 0.004, pad: 1.3, wmin: 0.8, tin: 6, tout: 10, model: "pen" },
  red: { kind: 1, w: 1.8, press: 0.85, pvar: 0.15, wob: 0.5, lam: 100, bow: 0.004, pad: 1.3, wmin: 0.8, tin: 6, tout: 10, model: "pen" },
  green: { kind: 1, w: 2.6, press: 0.9, pvar: 0.12, wob: 0.35, lam: 90, bow: 0.003, pad: 1.4, wmin: 0.78, tin: 5, tout: 8, model: "pen" },
  marker: { kind: 3, w: 4.6, press: 0.9, pvar: 0.1, wob: 0.6, lam: 120, bow: 0.003, pad: 3.6, wmin: 0.86, tin: 5, tout: 6, model: "marker" },
  highlighter: { kind: 4, w: 18, press: 1, pvar: 0.05, wob: 0.5, lam: 150, bow: 0.002, pad: 3, wmin: 0.96, tin: 0, tout: 0, model: "highlighter" },
  eraser: { kind: 5, w: 14, press: 1, pvar: 0.2, wob: 0.8, lam: 40, bow: 0, pad: 2, wmin: 0.9, tin: 4, tout: 4, model: "eraser" },
};

/* What is drawn over what: the highlighter under everything, graphite and its scuffs above it, ink
   on top. */
const ORDER = { 4: 1, 5: 2, 0: 2, 1: 3, 3: 3 };

// ------------------------------------------------------------------------------ the arithmetic

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const sstep = x => x * x * (3 - 2 * x);

function hash1(n) {
  n |= 0;
  n = Math.imul(n ^ (n >>> 15), 0x2c1b3c6d);
  n = Math.imul(n ^ (n >>> 12), 0x297a2d39);
  n ^= n >>> 15;
  return (n >>> 0) / 4294967296;
}

function noise1(x, seed) {
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f), s = Math.imul(seed | 0, 668265263);
  const a = hash1(Math.imul(i, 374761393) + s), b = hash1(Math.imul(i + 1, 374761393) + s);
  return a + (b - a) * u;
}

function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function catmull(pts, n = 10) {
  if (pts.length < 3) return pts;
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    for (let k = 0; k < n; k++) {
      const t = k / n, t2 = t * t, t3 = t2 * t;
      const f = j => 0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 +
                            (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3);
      out.push([f(0), f(1)]);
    }
  }
  out.push(pts[pts.length - 1].slice());
  return out;
}

function resample(pts, step) {
  const out = [[pts[0][0], pts[0][1]]];
  let carry = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
    if (L < 1e-6) continue;
    let t = step - carry;
    while (t <= L) { out.push([a[0] + dx * t / L, a[1] + dy * t / L]); t += step; }
    carry = L - (t - step);
  }
  const last = pts[pts.length - 1], o = out[out.length - 1];
  if (Math.hypot(last[0] - o[0], last[1] - o[1]) > step * 0.3) out.push([last[0], last[1]]);
  else if (out.length > 1) out[out.length - 1] = [last[0], last[1]];
  else out.push([last[0] + 0.05, last[1]]);
  return out;
}

function cumd(P) {
  const D = new Float32Array(P.length);
  for (let i = 1; i < P.length; i++) D[i] = D[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
  return D;
}

function normals(P) {
  const n = P.length, N = new Array(n);
  for (let i = 0; i < n; i++) {
    const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)];
    let tx = b[0] - a[0], ty = b[1] - a[1];
    const l = Math.hypot(tx, ty) || 1;
    tx /= l; ty /= l;
    N[i] = [-ty, tx];
  }
  return N;
}

/* One path as the tool would lay it: the points it passes through (`P`), the distance along it at
   each (`D`), its length, and the triangle strip the shader draws -- a quad per step with a round
   cap at each end, carrying distance, side, half-width, width and pressure per vertex. */
export function geometry(path, tool, seed, tune) {
  // A table may tune a tool's hand (#253): its numbers over the tool's own, for this stroke only.
  const T = tune ? Object.assign({}, TOOLS[tool], tune) : TOOLS[tool];
  let P = resample(path.smooth ? catmull(path.pts) : path.pts, 2);
  let D = cumd(P);
  const L0 = D[D.length - 1] || 1;
  const rnd = rng(seed + 17);
  const bow = path.nobow ? 0 : (rnd() - 0.5) * 2 * T.bow * L0;
  const wob = T.wob * (path.wob == null ? 1 : path.wob);
  let N = normals(P);
  P = P.map((q, i) => {
    const s = D[i];
    const o = wob * (noise1(s / T.lam, seed) * 2 - 1) + wob * 0.35 * (noise1(s / (T.lam * 0.27), seed + 11) * 2 - 1) +
              bow * Math.sin(Math.PI * s / L0);
    return [q[0] + N[i][0] * o, q[1] + N[i][1] * o];
  });
  D = cumd(P);
  N = normals(P);
  const n = P.length, L = D[n - 1], W = path.w || T.w, taper = L > 14;
  const press = new Float32Array(n), wid = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const s = D[i];
    let pr = T.press * (1 + T.pvar * (noise1(s / 55, seed + 3) * 2 - 1));
    if (taper && T.tin) pr *= 0.45 + 0.55 * sstep(clamp(s / T.tin, 0, 1));
    if (taper && T.tout) pr *= 0.5 + 0.5 * sstep(clamp((L - s) / T.tout, 0, 1));
    press[i] = pr;
    wid[i] = W * (T.wmin + (1 - T.wmin) * clamp(pr / T.press, 0, 1.2));
  }
  const m = n + 2, V = m * 2;
  const pos = new Float32Array(V * 3), aD = new Float32Array(V), aS = new Float32Array(V), aH = new Float32Array(V);
  const aW = new Float32Array(V), aP = new Float32Array(V), segD = new Float32Array(m);
  let maxHalf = 0;
  const put = (j, x, y, nx, ny, d, w, pr) => {
    const h = w * 0.5 + T.pad;
    if (h > maxHalf) maxHalf = h;
    segD[j] = d;
    for (let s = 0; s < 2; s++) {
      const sd = s ? 1 : -1, k = j * 2 + s;
      pos[k * 3] = x + nx * h * sd;
      pos[k * 3 + 1] = -(y + ny * h * sd);
      aD[k] = d; aS[k] = sd; aH[k] = h; aW[k] = w; aP[k] = pr;
    }
  };
  for (let i = 0; i < n; i++) put(i + 1, P[i][0], P[i][1], N[i][0], N[i][1], D[i], wid[i], press[i]);
  const h0 = wid[0] * 0.5 + T.pad, hn = wid[n - 1] * 0.5 + T.pad;
  put(0, P[0][0] - N[0][1] * h0, P[0][1] + N[0][0] * h0, N[0][0], N[0][1], -h0, wid[0], press[0]);
  put(m - 1, P[n - 1][0] + N[n - 1][1] * hn, P[n - 1][1] - N[n - 1][0] * hn, N[n - 1][0], N[n - 1][1], L + hn,
      wid[n - 1], press[n - 1]);
  const I = V > 65535 ? new Uint32Array((m - 1) * 6) : new Uint16Array((m - 1) * 6);
  for (let j = 0; j < m - 1; j++) {
    const a = j * 2, o = j * 6;
    I[o] = a; I[o + 1] = a + 1; I[o + 2] = a + 2; I[o + 3] = a + 1; I[o + 4] = a + 3; I[o + 5] = a + 2;
  }
  return { P, D, len: L, maxHalf, segD, index: I, attrs: { position: pos, aD, aS, aH, aW, aP } };
}

// ------------------------------------------------------------------------------- the shaders

const NOISE = `
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vn(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1.0, 0.0)), u.x), mix(h21(i + vec2(0.0, 1.0)), h21(i + vec2(1.0, 1.0)), u.x), u.y); }
float tooth(vec2 p){ return vn(p * 0.55) * 0.5 + vn(p * 1.37 + 17.0) * 0.3 + vn(p * 3.1 + 41.0) * 0.2; }
`;

/* The clip: a mark on a line of a transcript that has scrolled out of its box must not be drawn
   outside the box, so every mesh carries the rectangle its anchor can be seen in (the viewport, cut
   down by every scrolling ancestor), in CSS pixels, and the fragment outside it is discarded. */
const CLIP = `
uniform vec4 uClip; uniform float uDpr; uniform float uViewH;
bool clipped(){ vec2 c = vec2(gl_FragCoord.x / uDpr, uViewH - gl_FragCoord.y / uDpr);
  return c.x < uClip.x || c.y < uClip.y || c.x > uClip.z || c.y > uClip.w; }
`;

const STROKE_VS = `
attribute float aD; attribute float aS; attribute float aH; attribute float aW; attribute float aP;
varying float vD; varying float vS; varying float vH; varying float vW; varying float vP; varying vec2 vPos;
void main(){ vD = aD; vS = aS; vH = aH; vW = aW; vP = aP; vPos = vec2(position.x, -position.y);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

/* One shader, five tools. Graphite takes the paper's tooth, so a pencil line is grainy where the
   paper is raised and pressure fills it in. Ballpoint is steady, skips a little under light
   pressure and blobs now and then. Felt (the marker) bleeds outward the longer the ink has been on
   the paper and pools where the nib stopped. The highlighter has ragged ends and streaks, and is
   multiplied into a light paper or screened onto a dark one. The eraser leaves a faint scuff.
   `uHead` is how far the pen has got; `uErase` how far back the eraser has taken it. */
const STROKE_FS = `
uniform vec3 uColor; uniform float uKind; uniform float uHead; uniform float uLen; uniform float uErase; uniform float uSeed;
uniform float uDash; uniform float uMode; uniform float uAlpha; uniform float uDone;
varying float vD; varying float vS; varying float vH; varying float vW; varying float vP; varying vec2 vPos;
${NOISE}
${CLIP}
void main(){
  if (clipped()) discard;
  float d = abs(vS) * vH;
  float r = vW * 0.5;
  float fw = max(fwidth(d), 0.25);
  if (uDash > 0.5) {
    float kd = floor(vD / 15.0);
    if (mod(vD, 15.0) > 7.5 + h21(vec2(kd, uSeed)) * 3.5) discard;
  }
  if (uKind > 3.5 && uKind < 4.5) {
    float slant = vS * r * 0.5;
    float rag = (vn(vec2(vS * 4.0 + uSeed, uSeed * 0.37)) - 0.5) * 5.0;
    if (vD < slant + rag + 1.0) discard;
    if (vD > min(uHead, uLen - 1.0) + slant + rag) discard;
    float en = (vn(vec2(vD * 0.08, sign(vS) * 3.1 + uSeed)) - 0.5) * 2.4;
    float cov = 1.0 - smoothstep(r + en - 1.2, r + en + 0.4, d);
    float streak = 0.84 + 0.16 * vn(vec2(vD * 0.015, vS * 7.0 + uSeed));
    float rim = 1.0 + 0.16 * smoothstep(0.5, 0.95, d / max(r, 1.0));
    float ha = clamp(cov * streak * rim, 0.0, 1.0) * uAlpha;
    if (vD > uErase) ha *= 0.08;
    if (ha < 0.004) discard;
    if (uMode > 1.5) gl_FragColor = vec4(uColor * ha * 0.42, 1.0);
    else if (uMode > 0.5) gl_FragColor = vec4(mix(vec3(1.0), uColor, ha * 0.68), 1.0);
    else gl_FragColor = vec4(uColor, ha * 0.42);
    return;
  }
  float over = vD - uHead;
  float q = d;
  if (over > 0.0) q = length(vec2(over, d));
  else if (vD < 0.0) q = length(vec2(vD, d));
  vec3 col = uColor; float a = 0.0;
  if (uKind < 0.5) {
    float t = tooth(vPos);
    float g = vn(vPos * 1.9 + uSeed);
    float dep = smoothstep(0.26, 0.7, t * 0.7 + g * 0.3 + vP * 0.32 - 0.12);
    float cov = 1.0 - smoothstep(r - fw * 0.6, r + fw, q);
    a = cov * (1.0 - 0.3 * smoothstep(0.0, r, q)) * dep * (0.45 + 0.6 * vP);
  } else if (uKind < 1.5) {
    float n = vn(vec2(vD * 0.3, vS * 1.7 + uSeed));
    float e = r + (n - 0.5) * 0.3;
    float cov = 1.0 - smoothstep(e - fw * 0.6, e + fw * 0.6, q);
    float skip = (1.0 - smoothstep(0.02, 0.15, vn(vec2(vD * 0.06, uSeed + 5.0)))) * (1.0 - smoothstep(0.7, 1.0, vP));
    float bl = step(0.955, h21(vec2(floor(vD / 29.0), uSeed))) * (1.0 - smoothstep(0.0, 3.0, abs(mod(vD, 29.0) - 14.0)));
    a = cov * (0.86 + 0.14 * n) * (1.0 - 0.5 * skip);
    col = uColor * (1.0 - 0.28 * bl);
  } else if (uKind < 3.5) {
    float behind = uDone > 0.5 ? 999.0 : uHead - vD;
    float bleed = clamp(behind / 140.0, 0.0, 1.0);
    float fib = vn(vec2(vD * 0.5, sign(vS) * 7.3 + uSeed));
    float fib2 = vn(vec2(vD * 1.7, sign(vS) * 3.1 + uSeed * 2.0));
    float e = r + bleed * (0.25 + 1.6 * fib * fib2);
    float cov = 1.0 - smoothstep(e - fw, e + fw * 0.5, q);
    float core = 1.0 - smoothstep(r * 0.55, r + 0.2, q);
    float pool = max(1.0 - smoothstep(0.0, 8.0, vD), 1.0 - smoothstep(0.0, 8.0, uLen - vD));
    a = cov * mix(0.5, 0.92, core) * (0.88 + 0.12 * vn(vPos * 0.7));
    col = mix(uColor, uColor * 0.7, pool * 0.8);
  } else {
    float cov = 1.0 - smoothstep(r * 0.4, r + fw, q);
    a = cov * 0.085 * (0.35 + vn(vPos * vec2(0.09, 0.35) + uSeed));
  }
  if (vD > uErase) a *= 0.09 * (0.5 + vn(vPos * 0.21 + uSeed));
  a *= uAlpha;
  if (a < 0.003) discard;
  gl_FragColor = vec4(col, a);
}`;

const PAPER_VS = `void main(){ gl_Position = vec4(position.xy * 2.0, 0.0, 1.0); }`;

/* A skin's paper, when it has one: its colour with the tooth a pencil catches on, lit from the top
   left. The notebook (#249) adds its rules and margin here; slice B needs only enough paper for the
   highlighter to have something to multiply into. */
const PAPER_FS = `
uniform vec3 uPaper; uniform float uDark; uniform float uDpr;
${NOISE}
void main(){
  vec2 p = gl_FragCoord.xy / uDpr;
  float t = tooth(p);
  float hx = tooth(p + vec2(0.8, 0.0)) - t;
  float hy = tooth(p + vec2(0.0, 0.8)) - t;
  vec3 n = normalize(vec3(-hx * 5.0, hy * 5.0, 1.0));
  vec3 L = normalize(vec3(-0.45, 0.55, 0.9));
  float lit = dot(n, L) - L.z;
  float k = uDark > 0.5 ? 0.6 : 1.0;
  vec3 c = uPaper + lit * 0.09 * k;
  c *= 1.0 - (t - 0.5) * 0.025 * k;
  gl_FragColor = vec4(c, 1.0);
}`;

const QUAD_VS = `varying vec2 vPos; varying vec2 vUv; void main(){ vec4 w = modelMatrix * vec4(position, 1.0); vPos = vec2(w.x, -w.y); vUv = uv; gl_Position = projectionMatrix * viewMatrix * w; }`;
const SHADOW_FS = `uniform vec2 uA; uniform vec2 uB; uniform vec2 uR; uniform vec2 uBl; uniform float uAl; varying vec2 vPos; varying vec2 vUv;
void main(){ vec2 pa = vPos - uA, ba = uB - uA; float h = clamp(dot(pa, ba) / max(dot(ba, ba), 0.001), 0.0, 1.0);
  float d = length(pa - ba * h); float r = mix(uR.x, uR.y, h); float bl = mix(uBl.x, uBl.y, h);
  float a = (1.0 - smoothstep(r - bl, r + bl, d)) * uAl * mix(1.0, 0.45, h); if (a < 0.003) discard; gl_FragColor = vec4(0.0, 0.0, 0.0, a); }`;

const DEG = Math.PI / 180;

// --------------------------------------------------------------------------- the three.js half

/* Everything that needs three.js, built once per layer. `shared` holds the uniforms every stroke
   reads (the device pixel ratio and the viewport's height, for the clip), so a resize writes two
   numbers rather than one per mesh. */
export function makePen(THREE, shared) {
  const QUAD = new THREE.PlaneGeometry(1, 1);

  function blend(mt, kind, mode) {
    if (kind !== 4 || mode === 0) {
      mt.blending = THREE.NormalBlending;
      return;
    }
    mt.blending = THREE.CustomBlending;
    mt.blendEquation = THREE.AddEquation;
    if (mode === 2) { mt.blendSrc = THREE.OneFactor; mt.blendDst = THREE.OneMinusSrcColorFactor; }  // screen
    else { mt.blendSrc = THREE.DstColorFactor; mt.blendDst = THREE.ZeroFactor; }                    // multiply
  }

  /* One stroke of one mark: its geometry in the anchor's coordinates, drawn up to `head`. */
  class Stroke {
    constructor(tool, seed, dash, tune) {
      this.tool = tool;
      this.T = TOOLS[tool];
      this.tune = tune || null;
      this.seed = seed;
      this.dash = !!dash;
      this.head = 0;
      this.erase = Infinity;
      this.len = 0;
      this.sig = "";
      this.mesh = null;
      this.mat = null;
      this.P = null;
      this.D = null;
      this.segD = null;
      this.idx = 0;
      this.maxHalf = 0;
      this.done = false;
      this.dead = false;
    }

    /* (Re)build from a path. The same path is the same geometry, so a redraw with nothing new is
       free; a changed one keeps how far along the pen had got, as a fraction. */
    build(path, scene, colour, mode) {
      if (!path || !path.pts || path.pts.length < 2) {
        this.dead = true;
        if (this.mesh) this.mesh.visible = false;
        return;
      }
      const sig = path.pts.map(q => q[0].toFixed(1) + "," + q[1].toFixed(1)).join(" ") + "|" + (path.w || 0).toFixed(1);
      if (sig === this.sig && !this.dead) return;
      const full = this.len > 0 && this.head >= this.len - 0.05;
      const hf = this.len ? this.head / this.len : 0;
      const ef = this.erase === Infinity ? null : (this.erase < 0 ? -1 : this.erase / (this.len || 1));
      this.sig = sig;
      this.dead = false;
      const g = geometry(path, this.tool, this.seed, this.tune);
      this.P = g.P; this.D = g.D; this.len = g.len; this.maxHalf = g.maxHalf; this.segD = g.segD; this.idx = g.index.length;
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(g.attrs.position, 3));
      for (const k of ["aD", "aS", "aH", "aW", "aP"]) geo.setAttribute(k, new THREE.BufferAttribute(g.attrs[k], 1));
      geo.setIndex(new THREE.BufferAttribute(g.index, 1));
      if (!this.mesh) {
        this.mat = new THREE.ShaderMaterial({
          vertexShader: STROKE_VS, fragmentShader: STROKE_FS, transparent: true, depthTest: false, depthWrite: false,
          uniforms: {
            uColor: { value: new THREE.Vector3(...colour) }, uKind: { value: this.T.kind }, uHead: { value: 0 },
            uLen: { value: 1 }, uErase: { value: 1e9 }, uSeed: { value: this.seed % 997 },
            uDash: { value: this.dash ? 1 : 0 }, uMode: { value: mode }, uAlpha: { value: 1 }, uDone: { value: 0 },
            uClip: { value: new THREE.Vector4(-1e5, -1e5, 1e5, 1e5) }, uDpr: shared.uDpr, uViewH: shared.uViewH,
          },
        });
        this.mat.extensions = { derivatives: true };
        blend(this.mat, this.T.kind, mode);
        this.mesh = new THREE.Mesh(geo, this.mat);
        this.mesh.frustumCulled = false;
        this.mesh.renderOrder = ORDER[this.T.kind] ?? 3;
        scene.add(this.mesh);
      } else {
        this.mesh.geometry.dispose();
        this.mesh.geometry = geo;
      }
      this.mesh.visible = true;
      this.mat.uniforms.uLen.value = this.len;
      this.mat.uniforms.uDone.value = this.done ? 1 : 0;
      this.setHead(full || this.done ? this.len : hf * this.len);
      if (ef !== null) this.setErase(ef < 0 ? -1e5 : ef * this.len);
    }

    setHead(h) {
      this.head = h;
      if (!this.mat || !this.segD) return;
      this.mat.uniforms.uHead.value = h;
      let c = 0;
      if (h > 0) {
        const lim = h + this.maxHalf + 2, S = this.segD;
        let lo = 0, hi = S.length - 1;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (S[mid] > lim) hi = mid; else lo = mid + 1; }
        c = Math.min(this.idx, lo * 6);
      }
      this.mesh.geometry.setDrawRange(0, c);
    }

    setErase(e) {
      this.erase = e;
      if (this.mat) this.mat.uniforms.uErase.value = e === Infinity ? 1e9 : e;
    }

    setDone(v) {
      this.done = v;
      if (this.mat) this.mat.uniforms.uDone.value = v ? 1 : 0;
    }

    colour(rgb, mode) {
      if (!this.mat) return;
      this.mat.uniforms.uColor.value.set(...rgb);
      this.mat.uniforms.uMode.value = mode;
      blend(this.mat, this.T.kind, mode);
    }

    place(x, y, clip, visible) {
      if (!this.mesh) return;
      this.mesh.position.set(x, -y, 0);
      this.mat.uniforms.uClip.value.set(clip[0], clip[1], clip[2], clip[3]);
      this.mesh.visible = visible && !this.dead;
    }

    pointAt(s) {
      const D = this.D, P = this.P;
      if (!D) return [0, 0];
      s = clamp(s, 0, this.len);
      let lo = 0, hi = D.length - 1;
      while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (D[mid] <= s) lo = mid; else hi = mid; }
      const t = D[hi] > D[lo] ? (s - D[lo]) / (D[hi] - D[lo]) : 0;
      return [P[lo][0] + (P[hi][0] - P[lo][0]) * t, P[lo][1] + (P[hi][1] - P[lo][1]) * t];
    }

    bbox() {
      if (!this.P || this.dead) return null;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const q of this.P) {
        if (q[0] < x0) x0 = q[0];
        if (q[0] > x1) x1 = q[0];
        if (q[1] < y0) y0 = q[1];
        if (q[1] > y1) y1 = q[1];
      }
      return { x: x0, y: y0, r: x1, b: y1, w: x1 - x0, h: y1 - y0 };
    }

    dispose(scene) {
      this.dead = true;
      if (this.mesh) {
        scene.remove(this.mesh);
        this.mesh.geometry.dispose();
        this.mat.dispose();
        this.mesh = null;
        this.mat = null;
      }
    }
  }

  /* The paper, when a skin has one: a full-screen quad drawn first, opaque. */
  function paper(colour, dark) {
    const mesh = new THREE.Mesh(QUAD, new THREE.ShaderMaterial({
      vertexShader: PAPER_VS, fragmentShader: PAPER_FS, depthTest: false, depthWrite: false,
      uniforms: { uPaper: { value: new THREE.Vector3(...colour) }, uDark: { value: dark ? 1 : 0 }, uDpr: shared.uDpr },
    }));
    mesh.material.extensions = { derivatives: true };
    mesh.frustumCulled = false;
    mesh.renderOrder = -10;
    return mesh;
  }

  function quad(fs, uniforms, order, scene) {
    const m = new THREE.Mesh(QUAD, new THREE.ShaderMaterial({ vertexShader: QUAD_VS, fragmentShader: fs, uniforms,
                                                              transparent: true, depthTest: false, depthWrite: false }));
    m.renderOrder = order;
    m.frustumCulled = false;
    m.visible = false;
    scene.add(m);
    return m;
  }

  /* The hand: a small lit pencil, pen, marker or highlighter that travels along the stroke being
     drawn and lifts off at the end, with its shadow on the paper. Low-poly, one per lane. Coloured
     by the tool's own ink, looked up by `tint` at paint time. */
  function model(key, ink) {
    const g = new THREE.Group();
    const part = (geo, colour, y, o = {}) => {
      const mt = new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: o.shin ?? 28,
                                               specular: new THREE.Color(o.spec ?? 0x2a2a2a),
                                               flatShading: !!o.flat, transparent: true });
      if (typeof colour === "string") mt.userData.ink = colour; else mt.color.setHex(colour);
      const me = new THREE.Mesh(geo, mt);
      me.position.set(o.x || 0, y, o.z || 0);
      if (o.sz) me.scale.z = o.sz;
      g.add(me);
      return me;
    };
    const Cy = (a, b, h, s = 16) => new THREE.CylinderGeometry(a, b, h, s);
    if (key === "pencil" || key === "eraser") {
      part(Cy(0.95, 0, 3.2, 6), 0x34363b, 1.6, { flat: true, shin: 70 });
      part(Cy(4.2, 0.95, 11, 6), 0xe4c9a2, 8.7, { flat: true });
      part(Cy(4.2, 4.2, 90, 6), "pencil", 59.2, { flat: true, shin: 40 });
      part(Cy(4.4, 4.4, 7, 18), 0xcbc5b3, 107.7, { shin: 90, spec: 0x777777 });
      part(Cy(4.15, 4.15, 7, 18), 0xe39c96, 114.7);
      g.userData.len = 118.2;
    } else if (key === "pen") {
      part(Cy(0.8, 0, 2.2, 10), 0xd5d8de, 1.1, { shin: 90, spec: 0x888888 });
      part(Cy(2.3, 0.8, 7), 0xd5d8de, 5.7, { shin: 90, spec: 0x888888 });
      part(Cy(3.5, 2.3, 14, 18), 0x2b2f37, 16.2);
      part(Cy(3.5, 3.5, 78, 18), ink, 62.2, { shin: 60, spec: 0x555555 });
      part(Cy(3, 3.5, 8, 18), ink, 105.2);
      part(new THREE.BoxGeometry(1.4, 30, 1.6), 0xd5d8de, 88, { z: 3.9, shin: 90 });
      g.userData.len = 109.2;
    } else if (key === "marker") {
      part(Cy(2.6, 0.9, 6, 14), ink, 3);
      part(Cy(6, 3.2, 8, 20), 0x2b2f37, 10);
      part(Cy(6, 6, 76, 20), 0xeceae4, 52, { shin: 40 });
      part(Cy(6.15, 6.15, 10, 20), ink, 40);
      part(Cy(5.6, 6, 9, 20), ink, 94.5);
      g.userData.len = 99;
    } else {
      part(Cy(3.4, 1.1, 7, 4), ink, 3.5, { flat: true });
      part(Cy(6.5, 4.2, 8, 8), ink, 11, { flat: true });
      part(Cy(7.5, 7.5, 70, 8), ink, 50, { sz: 0.62, flat: true, shin: 50 });
      part(Cy(7, 7.5, 9, 8), 0x2b2f37, 89.5, { sz: 0.62, flat: true });
      g.userData.len = 94;
    }
    return g;
  }

  class Hand {
    constructor(toolScene, scene, inks) {
      this.inks = inks;               // tool name -> [r, g, b], read at paint time by the layer
      this.g = new THREE.Group();
      this.inner = new THREE.Group();
      this.g.add(this.inner);
      this.g.visible = false;
      toolScene.add(this.g);
      this.models = {};
      this.cur = "";
      this.vis = false;
      this.tip = [0, 0];
      this.z = 0; this.zT = 0; this.alpha = 0; this.aT = 0; this.lift = -1; this.roll = 0;
      this.ph = Math.random() * 9;
      this.len = 110;
      this.mats = [];
      this.dir = new THREE.Vector3();
      this.up = new THREE.Vector3(0, 1, 0);
      this.dark = false;
      this.shadow = quad(SHADOW_FS, { uA: { value: new THREE.Vector2() }, uB: { value: new THREE.Vector2() },
                                      uR: { value: new THREE.Vector2() }, uBl: { value: new THREE.Vector2() },
                                      uAl: { value: 0 } }, 6, scene);
    }

    model(tool) {
      const T = TOOLS[tool] || TOOLS.pen;
      const key = T.model + (T.model === "pen" ? ":" + tool : "");
      if (!this.models[key]) {
        const m = model(T.model, tool);
        this.models[key] = m;
        this.inner.add(m);
        this.tint(m);
      }
      for (const k in this.models) this.models[k].visible = k === key;
      const m = this.models[key];
      if (tool === "eraser") { m.rotation.z = Math.PI; m.position.y = m.userData.len; }
      else { m.rotation.z = 0; m.position.y = 0; }
      this.cur = tool;
      this.len = m.userData.len;
      this.mats = [];
      m.traverse(o => { if (o.material) this.mats.push(o.material); });
    }

    tint(only) {
      const each = only ? [only] : Object.values(this.models);
      for (const g of each) {
        g.traverse(o => {
          const ink = o.material && o.material.userData.ink;
          if (ink && this.inks[ink]) o.material.color.setRGB(...this.inks[ink], THREE.SRGBColorSpace);
        });
      }
    }

    appear(tool, at) {
      this.model(tool);
      this.tip = [at[0], at[1]];
      this.z = 18; this.zT = 0; this.alpha = 0; this.aT = 1; this.lift = -1;
      this.vis = true;
      this.g.visible = true;
    }

    follow(pt) {
      this.roll += Math.hypot(pt[0] - this.tip[0], pt[1] - this.tip[1]) * 0.012;
      this.tip = pt;
      this.zT = 0;
      this.aT = 1;
    }

    hide() {
      this.vis = false;
      this.g.visible = false;
      this.shadow.visible = false;
      this.lift = -1;
    }

    startLift() {
      this.lift = 0;
      this.lz = this.z;
      this.lt = this.tip.slice();
      this.la = this.alpha;
    }

    update(dt, now) {
      if (!this.vis) return;
      if (this.lift >= 0) {
        this.lift += dt;
        const k = Math.min(1, this.lift / 0.45), e = 1 - (1 - k) ** 3;
        this.z = this.lz + 64 * e;
        this.tip = [this.lt[0] + 16 * e, this.lt[1] - 20 * e];
        this.alpha = this.la * (1 - k);
        if (k >= 1) { this.hide(); return; }
      } else {
        this.z += (this.zT - this.z) * Math.min(1, dt * 22);
        this.alpha += (this.aT - this.alpha) * Math.min(1, dt * 14);
      }
      const t = now / 1000, er = this.cur === "eraser", hl = this.cur === "highlighter";
      const tilt = (hl ? 42 : er ? 38 : 50) * DEG, az = (hl ? 64 : 57) * DEG + Math.sin(t * 1.7 + this.ph) * 4 * DEG;
      this.dir.set(Math.cos(az) * Math.sin(tilt), Math.sin(az) * Math.sin(tilt), Math.cos(tilt));
      this.g.quaternion.setFromUnitVectors(this.up, this.dir);
      this.inner.rotation.y = this.roll + Math.sin(t * 2.3 + this.ph) * 0.12;
      this.g.position.set(this.tip[0], -this.tip[1], this.z);
      for (const m of this.mats) m.opacity = this.alpha;
      const Lx = 0.42, Ly = 0.52, z = this.z, len = this.len;
      const tx = this.tip[0] + this.dir.x * len, ty = this.tip[1] - this.dir.y * len, tz = z + this.dir.z * len;
      const A = [this.tip[0] + Lx * z, this.tip[1] + Ly * z], B = [tx + Lx * tz, ty + Ly * tz];
      const sh = this.shadow, u = sh.material.uniforms;
      u.uA.value.set(A[0], A[1]);
      u.uB.value.set(B[0], B[1]);
      u.uR.value.set(1.4 + z * 0.05, 4.5);
      u.uBl.value.set(1.2 + z * 0.12, 9);
      u.uAl.value = (this.dark ? 0.5 : 0.2) * this.alpha;
      sh.position.set((A[0] + B[0]) / 2, -(A[1] + B[1]) / 2, 0);
      sh.scale.set(Math.abs(B[0] - A[0]) + 44, Math.abs(B[1] - A[1]) + 44, 1);
      sh.visible = true;
    }
  }

  return { Stroke, Hand, paper, blend };
}
