export function marks(variant) {
  return [
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.ink-example .head", tool: variant === "red" ? "red" : "pen", shape: "underline" },
  ];
}

export const options = { hand: true, speed: 1 };

export const sampleGround = false;

function colour(THREE, rgb) {
  return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

export function ground({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.bg) }));
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.ground;
  scene.add(mesh);
}

export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const pts = [];
  for (let y = 28; y < h; y += 28) pts.push(new THREE.Vector3(0, -y, 0), new THREE.Vector3(w, -y, 0));
  const rules = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens.line) }));
  rules.renderOrder = api.order.paper;
  scene.add(rules);
}

export function frame({ THREE, scene, tokens, api }, el, box) {
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
let quads = [];

export function cue({ THREE, scene, tokens }, name, el, box, how) {
  played.push({ name, how, box });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(box.w, box.h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.accent), transparent: true }));
  mesh.position.set(box.x + box.w / 2, -box.y - box.h / 2, 0);
  scene.add(mesh);
  quads.push({ mesh, age: 0 });
}

export function tick() {
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
}

export function inspect() {
  return { cues: played.slice(), quads: quads.length };
}
