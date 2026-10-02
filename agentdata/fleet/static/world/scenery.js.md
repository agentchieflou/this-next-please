# `world/scenery.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

The world's place: the ground, the city, the sky and the plaza's street furniture. The operator,
2026-10-02: *"We need to improve the asset quality of our 3d world."*

A classic script loaded before `world/world.js` and `world/bots.js`. It defines one global,
`WorldScenery`, and needs nothing else from the page: `world.js` hands it the three.js module it
imported. Every asset is made here from three.js's own primitives and a few lines of shader: no model
file, no texture, nothing fetched, no package. Detail comes from geometry merged into one draw call
per material and from the fragment shader, never from more objects, so the scene's draw calls stay
what they were whatever the fleet's size.

### `var NOISE`

A hash, value noise and a three-octave fbm in GLSL, shared by the ground (asphalt grain, puddles),
the city (which window is lit) and the sky (clouds). `ws` prefixes every name so the chunks three.js
splices around them cannot collide with them.

### `var FACADES`

Eight facade colours: concrete, sandstone, slate, brick. Grey alone read as a placeholder; eight
muted colours read as a street.

### `var u`

The uniforms the scene shares, as objects, so the material patched in `onBeforeCompile` reads the
same value `world.js` writes: the time (ripples), the night (lit windows), how wet the ground is,
the plaza's radius and the share of windows lit.

### `function rnd`

A repeatable random number from a seed: the city and the trees are the same on every load and every
machine, so a screenshot today matches one tomorrow.

### `function piece`

One part of a merged model: a primitive, made non-indexed, moved, scaled, turned and painted with a
vertex colour. A lamp is nine pieces, a bench eleven, a robot twenty; each still costs nothing in
draw calls, because its pieces are merged.

### `function merge`

Pieces into one `BufferGeometry`: position, normal, colour and any extra attribute they all carry
(`aWin`). Merging is what keeps the detail free in draw calls.

### `function ground`

One plane, one `MeshStandardMaterial`, patched rather than replaced, so it keeps three.js's lights,
fog and the sky's reflection (`scene.environment`). In the fragment shader:
- inside the plaza, paving laid in rings (more stones per ring further out), with grout, each stone
  its own shade; at the centre a dark disc with a brass compass star and ring;
- outside it, asphalt with grain;
- puddles everywhere: darker and nearly mirror smooth (roughness 0.03), where the reflection shows;
- ripples on the normal, stronger in the puddles, moving with `uTime`.

No texture: a texture is a fetch or a 2D canvas, and the page has neither (#257).

### `function block`

One box of a building as wall quads and a roof, with `aWin` per vertex: metres along the wall,
height, a seed, and whether it is a wall (a roof has no windows). The wall's winding faces outward,
so the back faces are culled and a tower is solid from every side.

### `function city`

44 buildings in a ring from 62 m to 120 m, far enough into the fog to be a skyline, near enough to
read as buildings: a parapet, on more than half a setback tier with its own parapet, and some a
rooftop box. One merged mesh, one draw call.

The windows are the shader: a grid of 2.6 by 3.3 m cells, a shopfront on the ground floor, glass
that varies window to window. By night some windows are lit, chosen per window by hash, warm or
cool, at a few brightnesses (`uLit` is the share). The grid is antialiased with `fwidth`, and a
window too small to draw fades to its average, so far towers shimmer neither in motion nor in
SwiftShader. `derivatives` is the extension WebGL1 needs for `fwidth`. A lit window adds back
part of its light after the fog, so the city still glows through the rain at night.

### `function sky`

A sphere drawn from inside, before everything, without depth: the gradient from horizon to zenith,
two layers of fbm cloud (bright by day, dark by night), and by night a warm glow at the horizon, a
city's light on low cloud.

### `function lamp`

A street lamp in cast iron: a base, a pole, a collar, an arm with a scroll under it, a lantern (cap,
finial, gallery) and its glass. The glass goes to its own list, an unlit mesh, so it glows at night
without a light of its own.

### `function bench`

Three seat slats and two back slats in wood, on two iron frames.

### `function tree`

A stone planter with soil, a trunk with a branch and four blobs of foliage, each a little
different in size and green. Low-poly icosahedra: it reads as a tree in the rain without a leaf
texture.

### `function plaza`

The plaza's furniture, built for its edge: a kerb, eight lamps just outside it facing in, a bench
between each pair, and a tree behind each bench. It is made again only when the edge moves (the
circle grows with the fleet), never per frame. It returns where the lamps' glass is (the glows, the
point lights and the rain's light use it) and each object's footprint, `[x, z, radius]`, so you
walk around a bench or a tree rather than through it.

### `function glows`

A soft halo around each lamp's glass at night: a quad turned to the camera in the vertex shader,
eight instances, one draw call, added to what is behind it. Hidden by day.

### `function placeGlows`

The halos where the plaza's lamps are.
