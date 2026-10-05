# The world's asset tools

Offline tools that made the 3D world's (`/world`) files. Nothing here ships or runs at runtime: the
page loads what these wrote, from `agentdata/fleet/static/world/`. Kept so every file there can be
remade, checked or replaced, as the operator asked (2026-10-03).

Needs Node 22 or later. Install the pinned tools once, here:

    cd tools/world
    npm ci

`@gltf-transform/*` (MIT), `meshoptimizer` (MIT) and `sharp` (Apache-2.0) are development tools
only; the package has no runtime dependency on them.

## Poly Haven, CC0 (`cc0/`)

What `agentdata/fleet/static/world/cc0/` holds, and how it was made. Its `LICENSE` names every asset
and author. Run from `tools/world`; the raw downloads go anywhere outside the repository.

    node cc0/fetch.mjs textures /tmp/ph brick_wall_001 painted_plaster_wall concrete_slab_wall asphalt_02 concrete_pavement
    node cc0/fetch.mjs hdris    /tmp/ph potsdamer_platz hansaplatz
    node cc0/fetch.mjs models   /tmp/ph/models fire_hydrant metal_trash_can trashbag cardboard_box_01 utility_box_01 utility_box_02 exterior_aircon_unit concrete_road_barrier covered_car
    node cc0/tex.mjs   /tmp/ph        ../../agentdata/fleet/static/world/cc0 brick_wall_001 painted_plaster_wall concrete_slab_wall asphalt_02 concrete_pavement
    node cc0/hdr.mjs   /tmp/ph        ../../agentdata/fleet/static/world/cc0 potsdamer_platz hansaplatz
    node cc0/props.mjs /tmp/ph/models ../../agentdata/fleet/static/world/cc0

- `fetch.mjs` downloads each asset at 1k through Poly Haven's API and checks every file against the
  md5 the API publishes.
- `tex.mjs` writes each texture as WebP: colour and normal maps at 1024 px, the
  occlusion/roughness/metalness map at 512 px.
- `hdr.mjs` averages each sky down to 512 x 256 and writes it as uncompressed RGBE, which
  `world/assets.js` reads without decoding run-length encoding.
- `props.mjs` cuts each model to one variant (`SPECS`), bakes its transforms, decimates it with
  meshoptimizer to `tris`, stands it on y = 0, and packs its textures into the `.glb` as 512 px WebP,
  with separate (not interleaved) vertex attributes.

With the versions pinned in `package.json`, each output matches the committed file byte for byte.
A new asset needs a line in `world/assets.js` (`TEX`, `SKY` or `PROPS`) and one in the folder's
`LICENSE`: `tests/test_fleet_serve.py` fails until both are there, and holds the folder to its budget.

## People (`people/`)

What `agentdata/fleet/static/world/people/` holds: the player's character and the pedestrians, made
from MakeHuman's CC0 assets (Blender with MPFB 2, then `people/people.mjs`), on a path MetaHuman exports
from Unreal Engine drop into. `people/README.md` has the steps, the config and the MetaHuman case.

## Trees (`trees/`)

What `agentdata/fleet/static/world/trees/` holds: `trees.glb`, the street and plaza trees, grown from
nothing but the numbers in `trees/trees.py` (no photograph, scan or model goes in, so the file is the
repository's own, under its licence). Needs Blender 5.2 (headless) and, for the packing, Node 22 with
the pinned tools above. From the repository's root:

    blender --background --factory-startup --python tools/world/trees/trees.py -- /tmp/trees
    cd tools/world && node trees/trees.mjs /tmp/trees/raw ../../agentdata/fleet/static/world/trees

`trees.py` runs in stages (`leaves twigs bark trees`, all when none is named; `preview` renders the
trees side by side into `<dir>/preview.png` to look at):

- `leaves`: each species' leaf as an image (`SPECIES`): its half outline from the tip to the stalk's
  notch, smoothed with its lobes' tips kept sharp, teeth along the margin, primary and secondary veins,
  a top and an underside colour.
- `twigs`: clusters of twigs fanned off a short branchlet, the leaves on their stalks bent, folded,
  tilted and tinted one by one (`TWIG`), rendered from above with Cycles into a 2 x 2 atlas: colour
  (with the occlusion where leaves overlap), normals, occlusion and roughness.
- `bark`: tiling barks, London plane's (old bark flaking in patches off cream new bark) and linden's
  (fissured), with their normals.
- `trees`: each tree in `VARIANTS` (`TREES` holds a species' trunk, crown and limbs): a trunk with its
  root flare, scaffold limbs, branches and twigs grown to an irregular crown, twig cards spread evenly
  through the crown's outer shell and anchored to the nearest branch, the sky each card and branch
  sees baked into its vertex colour (Blender's BVH), and a far level of detail with fewer, larger
  cards. Written raw (`raw/trees.json`, `raw/trees.bin`), Z up.

`trees.mjs` packs it: a mesh a tree and level of detail (`<species>_<n>_lod<0|1>`), a bark and a
leaves primitive each, turned to glTF's Y up, normals and colours as normalised bytes, the leaves'
atlas at 1024 px and the barks at 512 px in WebP. `tests/test_fleet_serve.py` holds the folder to
its budget.

## Cars (`cars/`)

What `agentdata/fleet/static/world/cars/` holds: `cars.glb`, the traffic, lofted from nothing but the
numbers in `cars/cars.py` (after no maker's design). Needs Blender 5.2 (headless) and Node 22 with the
pinned tools above. From the repository's root:

    blender --background --factory-startup --python tools/world/cars/cars.py -- /tmp/cars
    cd tools/world && node cars/cars.mjs /tmp/cars/raw ../../agentdata/fleet/static/world/cars

`cars.py` builds each car in `CARS` twice (`lod` 0 near, 1 far): the body lofted through stations along
it (`stations`), sixteen points a half section (`Car.half`) from the underside's middle round the side
and over the top, from the profiles (top line, beltline, the top's half width, the underside, raised
over the arches), closed by rounded ends; then, cast onto it with Blender's BVH and lifted off it, the
glass (side windows round the B pillar, windscreen, rear window), the lamps in their housings, the
grille, intakes, plates, seams and pillars from the outlines in `ends`; mirrors; tyres and five-spoke
rims. `preview` renders one car (`CAR=sedan_lod0`) from four sides into `<dir>/view0..3.png`.

`cars.mjs` packs it: a mesh a car and level of detail (`<kind>_lod<0|1>`), near with body, glass, trim
and lamp primitives in that order, far with body and lamp; glTF's Y up, normals and colours as
normalised bytes, no textures.
