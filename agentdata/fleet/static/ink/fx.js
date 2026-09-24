/* Ink effects (#370, epic #293): the seam every one-shot effect hangs on. docs/desk-ink.md §The files.

   Its own module, fetched by the layer only for a table that has effects (a skin that exports
   `cues`, or `options.fx`), so the four modules every drawing desk loads stay inside `INK_BUDGET`
   and effect code is held to `FX_BUDGET` (§Budgets). It imports nothing: the layer hands it
   three.js, the scene and the draw order (`attach(layer, spec)`), and it writes nothing to the
   page.

   DRAW ORDER. The group sits at `api.order.fx` (-5). three.js r160 sorts first by the innermost
   Group's `renderOrder`, and the pane groups `framePanes` makes keep 0, so an effect draws over
   the back pass (ground, paper) and under every pane's frame and every mark, whatever
   `api.order.frame` says. Within one list three.js draws every opaque object before any
   transparent one, so an effect's materials are `transparent: true`, like the skins' own. An
   effect that must sit on a pane's frame goes into that pane's frame group.

   AT REST. `match` (after the table is matched), `measure` (after every mark is measured) and
   `deliver` (in each frame, after `prepare`) are called only on frames the layer already draws;
   they never ask for one of their own here. #372 fills them. */

let live = 0;

/* How many layers have effects attached: 0 after every detach path (a table without `fx`,
   `Ink.setSkin(null)`, `Ink.off()`). */
export function attached() {
  return live;
}

export function attach(layer, spec) {
  const group = new layer.THREE.Group();
  group.renderOrder = layer.api.order.fx;
  layer.scene.add(group);
  live += 1;
  let gone = false;
  return {
    /* The helpers a skin's hooks reach as `api.fx` (#375, #376 add to it). */
    api: Object.freeze({}),
    match() {},
    measure() {},
    deliver() {},
    detach() {
      if (gone) return null;
      gone = true;
      layer.empty(group);
      layer.scene.remove(group);
      live -= 1;
      return null;
    },
    inspect() {
      return { loaded: true, rows: 0, children: group.children.length };
    },
  };
}
