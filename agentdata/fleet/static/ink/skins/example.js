/* The example skin (#248): the pattern every ink skin copies, and the one the tests draw with.

   It is not in skins.py, so nobody can choose it in the settings; a test puts it on the page with
   `applySkin("example")` or `applySkin("example:red")`. A real skin is the same file under its own
   name -- `static/ink/skins/<name>.js`, where `<name>` is its name in skins.py -- beside its
   `static/skins/<name>/skin.css` for layout, typography and the look `body.ink-off` falls back to.
   docs/desk-ink.md §Writing a skin is the contract; the rules that matter most:

   * No static `import`: a module resolved against this file's URL does not carry the run token.
     three.js is handed in, as `THREE`, and nothing else is needed.
   * Marks come from classes the page already sets. A skin never sets one, and never writes the
     page: its hooks draw into the scene they are handed, and that is all.
   * Colours come from `tokens` -- the palette as [r, g, b] -- so a palette change repaints the
     skin. The layer calls `ground` and `paper` again when it does, and on a resize.
   * Every call to `ground`, `paper` and `frame` begins with an empty scene, and the layer frees
     what was in it. Keep references in the module only for `tick`.
   * Put pieces under the marks: `api.order.ground`, `.paper` and `.frame` are the render orders.
   * A one-shot effect is a cue (docs/desk-ink.md §Effects): a row of `cues` says when, from the
     page's classes, and `cue` plays it. It is decoration: it ends by moving, shrinking or being
     covered, never by a fade, and leaves an idle desk at zero frames. */

/* The mark table's rows, or a function of the variant that answers them. */
export function marks(variant) {
  return [
    // A real selector: the agent that needs you has its name highlighted.
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    // A class only the tests set, so a test can draw on demand.
    { selector: ".tile.ink-example .head", tool: variant === "red" ? "red" : "pen", shape: "underline" },
  ];
}

/* The table's options: `paper` (a colour or a custom property the layer paints flat when the skin
   has no `paper` hook), `hand` (the travelling pencil; default true), `speed` (0.25x to 4x). */
export const options = { hand: true, speed: 1 };

/* Whether frames get the ground and paper as a texture (`api.groundTexture`), for a frosted pane
   that samples what is behind it. It costs a second draw of the ground whenever it changes. */
export const sampleGround = false;

function colour(THREE, rgb) {
  return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

/* The whole page's background, behind everything: here, the palette's ground, flat. Called when
   the skin arrives, on a resize and on a palette change. `camera` is the layer's: CSS px, x to
   the right and y down the page drawn at -y. */
export function ground({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.bg) }));
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.ground;
  scene.add(mesh);
}

/* The stock behind the panes, over the ground: here, a rule every 28px in the palette's line. */
export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const pts = [];
  for (let y = 28; y < h; y += 28) pts.push(new THREE.Vector3(0, -y, 0), new THREE.Vector3(w, -y, 0));
  const rules = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens.line) }));
  rules.renderOrder = api.order.paper;
  scene.add(rules);
}

/* One pane's frame. `scene` is that pane's own group, already at its top-left, so `box` is the
   pane in its own coordinates ({x: 0, y: 0, w, h}); it moves with the pane without a call, and is
   made again only when the pane changes size. `el` is the pane (`.tile`), to read, never write. */
export function frame({ THREE, scene, tokens, api }, el, box) {
  const corners = [[0, 0], [box.w, 0], [box.w, box.h], [0, box.h]].map(([x, y]) => new THREE.Vector3(x, -y, 0));
  const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(corners),
                                  new THREE.LineBasicMaterial({ color: colour(THREE, tokens.accent) }));
  line.renderOrder = api.order.frame;
  scene.add(line);
}

/* The cue table (#372): the layer fetches `ink/fx.js` for a skin that has one. A row plays its cue
   once for each new match (`arrive`) or each match that goes (`leave`), never for what the page
   already showed or is replaying. `.tile.ink-cue` is a class only the tests set; a grouped pane
   matches the leave row too, and plays nothing when it is hidden later. */
export const cues = [
  { selector: ".tile.ink-cue", on: "arrive", cue: "example" },
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "example-leave" },
  { selector: ".tile .transcript li.denied", on: "arrive", cue: "example-line" },
];

/* How long a quad plays, in frames: a third of a second at 60 Hz. */
const LIFE = 20;
const played = [];                     // every cue this page played, for `inspect`
let quads = [];                        // the quads `tick` is still playing

/* One cue. `scene` is the effects group, under every frame and mark; `box` is where the element is
   (`arrive`) or last was (`leave`), in viewport CSS px; `how` is "arrived", "unmatched" or
   "removed". Never called under reduced motion. What it adds, `tick` frees. */
export function cue({ THREE, scene, tokens }, name, el, box, how) {
  played.push({ name, how, box });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(box.w, box.h),
                              new THREE.MeshBasicMaterial({ color: colour(THREE, tokens.accent), transparent: true }));
  mesh.position.set(box.x + box.w / 2, -box.y - box.h / 2, 0);
  scene.add(mesh);
  quads.push({ mesh, age: 0 });
}

/* Every frame the layer draws, with the seconds since the last. Answer true to be given another:
   a ground that drifts would, and so does a quad still playing -- it shrinks away, and is freed
   after `LIFE` frames. Under reduced motion the answer is not honoured. */
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

/* The skin is going. The layer frees everything in the scenes it handed out, the effects group's
   quads included; free what else the skin made (a render target, a texture). */
export function dispose() {
  quads = [];
}

/* For the tests: every cue played on this page (`{name, how, box}`), and the quads still playing. */
export function inspect() {
  return { cues: played.slice(), quads: quads.length };
}
