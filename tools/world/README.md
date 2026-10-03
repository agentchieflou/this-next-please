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
