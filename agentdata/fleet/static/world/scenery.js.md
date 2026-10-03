# `world/scenery.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

The sky and the plaza's own furniture. A classic script loaded after `world/kit.js` (its noise,
`piece` and `merge`) and before `world/world.js`. It defines one global, `WorldScenery`. The ground,
the streets and the city moved to `world/city.js`, what stands on the streets to `world/street.js`.

### `var NOISE`

The kit's noise (`WorldKit.NOISE`), for the sky's clouds.

### `function sky`

A sphere drawn from inside, before everything, without depth: the gradient from horizon to zenith,
two layers of fbm cloud (bright by day, dark by night), and by night a warm glow at the horizon, a
city's light on low cloud. The wet ground's environment map is rendered from it (`vReflect`).

### `function lamp`

A street lamp in cast iron: a base, a pole, a collar, an arm with a scroll under it, a lantern (cap,
finial, gallery) and its glass. The glass goes to its own list, an unlit mesh, so it glows at night
without a light of its own; the light it casts is one of the kit's lights (`vPlaza`).

### `function bench`

Three seat slats and two back slats in wood, on two iron frames.

### `function tree`

A stone planter with soil, a trunk and a branch; the crown is leaf cards (`WorldKit.canopy`), as on
the streets.

### `function plaza`

The plaza's furniture, built for its edge: a low kerb round the agents' circle, eight lamps just
outside it facing in, a bench between each pair, and a tree behind each bench. It is made again only
when the edge moves (the circle grows with the fleet), never per frame. It returns where the lamps'
glass is (the halos and the lights use it) and each object's footprint, `[x, z, radius]`, so you
walk around a bench or a tree rather than through it.

### `function glows`

A soft halo around each lamp at night: a quad turned to the camera in the vertex shader, one draw
call for as many lamps as it is given (the plaza's eight, the streets' many), added to what is behind
it. Hidden by day.

### `function placeGlows`

The halos where the lamps are.
