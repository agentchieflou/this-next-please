# The world's people pipeline

`people.mjs` turns character exports into the files `agentdata/fleet/static/world/people/` holds:
`<id>.glb` for the player's character and `<id>_crowd.glb` for the pedestrians. It is how the CC0
stand-in was made, and it is how MetaHuman exports go in.

Needs Node 22 and the pinned tools (`npm ci` in `tools/world`, see `../README.md`). From `tools/world`:

    node people/people.mjs <config.json> [only-this-output-id]

## What it does

For each character, in order:

1. Reads each source (`.glb` or `.gltf`; several files merge, e.g. a MetaHuman's body, face and hair
   cards) and skins every vertex to the rest pose in world space, so exporter conventions (mesh node
   transforms, inverse bind matrices) all come out the same. Meshes without a skin (hair cards, glasses
   exported as static meshes) are bound to `attach` (default `head`).
2. Finds the world frame: metres (an export over 20 units tall is taken as centimetres, or set
   `scale`), Y up (`"up": "z"` for a Z-up file), facing -Z (from the feet: `foot_l` to `ball_l`; or
   set `facing`), feet on y = 0, pelvis over the origin.
3. Keeps the Unreal Engine body bones (`pelvis`, `spine_01`..`spine_05`, `neck_01`, `neck_02`, `head`,
   `clavicle/upperarm/lowerarm/hand_l/r`, `thigh/calf/foot/ball_l/r`, and the 30 finger bones for the
   hero) and gives every other bone's weight (MetaHuman's ~800 `FACIAL_*` bones, twist, corrective and
   metacarpal bones) to its nearest kept parent, four influences per vertex. `rename` maps other names.
4. Sorts primitives into roles by material name, then node/mesh name (`ROLE_RULES`; `roles` in the
   config prepends rules): skin, eyes, brows, lashes, hair, beard, glasses, top, bottom, shoes, outfit
   (split into top and bottom by the bones each piece moves with), other, or drop (MetaHuman's eye
   occlusion, tear line, eye shell, cartilage, teeth and tongue are dropped).
5. Adds a morph target per `variants` entry (the same character exported with another body; the vertex
   counts must match) with its joint and head-anchor offsets.
6. Drops glasses' lenses, decimates each role to `tris`, quantises (`KHR_mesh_quantization`), and turns
   every tintable colour map (skin, top, bottom, hair, brows, lashes, beard) into a detail map with its
   mean colour normalised, so the world can dye it; WebP at `texture` sizes (`EXT_texture_webp`).
7. Crowd outputs: every character at each `lods` entry, one primitive each, one atlas texture for all,
   and a `_ROLE` vertex attribute (0 skin, 1 top, 2 bottom, 3 hair, 4 shoes, 5 other) for per-pedestrian
   tints.

Hair, beard and glasses primitives carry a `style` (the node name after its role prefix, e.g.
`hair.afro01` is style `afro01`); `people.json` maps the picker's values to those styles.

## Config

`standin.config.json` here is the stand-in's; a MetaHuman set looks like this:

```json
{
  "out": "out",
  "outputs": [
    { "id": "metahuman_ada", "kind": "hero",
      "sources": ["mh/ada_body_LOD1.glb", "mh/ada_face_LOD2.glb", "mh/ada_hair_cards_LOD2.glb"],
      "tris": {"skin": 14000, "outfit": 9000, "shoes": 2000, "hair": 6000, "beard": 2000, "glasses": 1000},
      "texture": {"skin": 1024, "top": 1024, "bottom": 1024, "hair": 1024, "shoes": 512, "eyes": 256,
                  "brows": 256, "lashes": 256, "beard": 512, "glasses": 256},
      "normals": ["skin", "outfit", "shoes"], "normalSize": 1024 },
    { "id": "metahuman_crowd", "kind": "crowd",
      "characters": [{"name": "ada", "sources": ["mh/ada_body_LOD3.glb", "mh/ada_face_LOD5.glb", "mh/ada_hair_cards_LOD5.glb"]},
                     {"name": "bo",  "sources": ["mh/bo_body_LOD3.glb",  "mh/bo_face_LOD5.glb",  "mh/bo_hair_cards_LOD5.glb"]}],
      "tile": {"skin": 512, "top": 512, "bottom": 512, "hair": 256, "shoes": 256, "eyes": 64},
      "lods": [{"tris": {"skin": 2500, "outfit": 1800, "shoes": 300, "hair": 900}},
               {"tris": {"skin": 700, "outfit": 500, "shoes": 80, "hair": 250}, "skip": ["eyes"], "error": 0.08}] }
  ]
}
```

Then edit `agentdata/fleet/static/world/people/people.json`: `hero` lists the hero files (each with
`fits`, e.g. `{"figure": "curved", "age": "older"}`, so the picker's look chooses the closest export),
`crowd` the crowd files, `hair`/`face`/`glasses` map picker values to styles, `morphs` maps figure,
build and age values to morph weights (empty for exports without variants), and `clips.idle` may name an
animation clip in the hero file. Add every new file to the folder's `LICENSE`; the test
`test_the_worlds_people_are_the_ones_it_loads_credited_and_bounded` holds the folder to the manifest,
the LICENSE and 5 MiB.

## The stand-in

How `standin.glb` and `standin_crowd.glb` were made, from MakeHuman's CC0 assets (credited in
`agentdata/fleet/static/world/people/LICENSE`, with each download's sha256). The raw files are not
committed: `dl/`, `bvenv/`, `raw/` and `out/` here are ignored by git.

1. Download MPFB 2 and the CC0 asset packs into `dl/`:

       mkdir -p dl
       curl -sSL -o dl/mpfb2-20260911.zip https://files.makehumancommunity.org/plugins/mpfb2-20260911.zip
       for p in makehuman_system_assets bodyparts05 glasses01 hair01; do
         curl -sSL -o dl/${p}_cc0.zip https://files.makehumancommunity.org/asset_packs/$p/${p}_cc0.zip
       done
       sha256sum dl/*.zip    # compare with the people folder's LICENSE

2. Blender as a Python module, 4.5, in `bvenv/` (Python 3.11): `python3.11 -m venv bvenv`, then
   `bvenv/bin/pip install "bpy==4.5.*" numpy`.
3. `bvenv/bin/python install_mpfb.py` installs MPFB into that Blender and prints its user data folder.
   Unzip each `*_cc0.zip` there (the packs' folders: clothes, eyebrows, eyelashes, eyes, hair, skins).
4. `python3 specs.py` writes each character's spec (the hero and its five body variants, five
   pedestrians) to `raw/` and runs `mh_make.py` on it, which builds the character with MPFB, rigs it
   with the game-engine rig (Unreal Engine bone names) and exports `raw/<name>.glb`.
5. From `tools/world`: `node people/people.mjs people/standin.config.json`, then copy
   `people/out/*.glb` to `agentdata/fleet/static/world/people/`.
