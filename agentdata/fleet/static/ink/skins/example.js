export function marks(variant) {
  return [
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.ink-example .head", tool: variant === "red" ? "red" : "pen", shape: "underline" },
  ];
}

/** @param {string=} variant */
export function options(variant) {
  return { hand: true, speed: 1,
           fx: variant === "text" ? { text: true } : variant === "pointer" ? { pointer: true } : undefined };
}

let handed = null;

export function helpers() {
  return (handed && handed.fx) || null;
}

export const sampleGround = false;

function colour(THREE, rgb) {
  return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

export function ground({ THREE, scene, tokens, api }) {
  handed = api;
  const { w, h } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.bg) }));
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.ground;
  scene.add(mesh);
}

let sheet = null, square = null;
const pointed = { at: null, draws: 0 };
const SQUARE = 12;

export function paper({ THREE, scene, tokens, api }) {
  handed = api;
  sheet = scene;
  const { w, h } = api.viewport;
  const pts = [];
  for (let y = 28; y < h; y += 28) pts.push(new THREE.Vector3(0, -y, 0), new THREE.Vector3(w, -y, 0));
  const rules = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens.line) }));
  rules.renderOrder = api.order.paper;
  scene.add(rules);
}

export function frame({ THREE, scene, tokens, api }, el, box) {
  handed = api;
  const corners = [[0, 0], [box.w, 0], [box.w, box.h], [0, box.h]].map(([x, y]) => new THREE.Vector3(x, -y, 0));
  const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(corners),
                                  new THREE.LineBasicMaterial({ color: colour(THREE, tokens.accent) }));
  line.renderOrder = api.order.frame;
  scene.add(line);
}

export const cues = [
  { selector: ".tile.ink-cue", on: "arrive", cue: "example" },
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "example-leave" },
  { selector: ".tile .transcript li.denied", on: "arrive", cue: "example-line" },
];

const LIFE = 20;
const played = [];
const read = [];
let quads = [];

export function cue({ THREE, scene, tokens, api }, name, el, box, how) {
  handed = api;
  played.push({ name, how, box });
  const pane = api.fx && api.fx.glyphs && el.closest(".tile"), repo = pane && pane.querySelector(".repo");
  if (repo) read.push({ repo: pane.dataset.repo, glyphs: api.fx.glyphs(repo) });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(box.w, box.h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.accent), transparent: true }));
  mesh.position.set(box.x + box.w / 2, -box.y - box.h / 2, 0);
  scene.add(mesh);
  quads.push({ mesh, age: 0 });
}

export function tick({ THREE, tokens, api }) {
  handed = api;
  if (api.fx && "pointer" in api.fx) {
    const p = api.fx.pointer;
    if (p && sheet && (!square || square.parent !== sheet)) {
      square = new THREE.Mesh(new THREE.PlaneGeometry(SQUARE, SQUARE),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.accent), transparent: true }));
      square.renderOrder = api.order.paper;
      sheet.add(square);
    }
    if (square) {
      square.visible = !!p;
      if (p) square.position.set(p.x, -p.y, 0);
    }
    pointed.at = p ? { x: p.x, y: p.y, repo: p.repo } : null;
    if (p) pointed.draws += 1;
  }
  for (const q of quads) {
    q.age += 1;
    q.mesh.scale.setScalar(1 - q.age / LIFE);
    if (q.age >= LIFE) {
      q.mesh.removeFromParent();
      q.mesh.geometry.dispose();
      q.mesh.material.dispose();
    }
  }
  quads = quads.filter(q => q.age < LIFE);
  return quads.length > 0;
}

export function dispose() {
  quads = [];
  if (square) {
    square.removeFromParent();
    square.geometry.dispose();
    square.material.dispose();
  }
  square = sheet = null;
  pointed.at = null;
}

export function inspect() {
  return { cues: played.slice(), quads: quads.length, text: read.slice(),
           pointer: { at: pointed.at, draws: pointed.draws, shown: !!(square && square.visible && square.parent) } };
}
