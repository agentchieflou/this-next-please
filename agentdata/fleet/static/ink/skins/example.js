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
   * Put pieces under the marks: `api.order.ground`, `.paper` and `.frame` are the render orders. */

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

/* Every frame the layer draws, with the seconds since the last. Answer true to be given another:
   a ground that drifts would. Under reduced motion the answer is not honoured. */
export function tick() {
  return false;
}

/* The skin is going. The layer frees everything in the scenes it handed out; free what else the
   skin made (a render target, a texture). */
export function dispose() {}
