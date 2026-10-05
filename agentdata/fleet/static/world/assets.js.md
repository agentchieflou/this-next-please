# `world/assets.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

The world's real-world assets: photo textures, scanned props and photographed skies from Poly Haven,
all CC0. The operator, 2026-10-03: *"If it is open source and safe, you may use Poly Haven assets to
improve the character and environment quality. I explicitly authorize this."* What a code-built city
cannot fake is the surface of things: brick that is brick, asphalt with its cracks and patches, a
dented bin. Those are photographs and scans, and Poly Haven gives them away without conditions.

They live in `static/world/cc0/`, credited one by one in its `LICENSE`, made small for a browser
before they were committed (see that file). They come from the machine the page runs on, through
`q()` with the token like every other file. Nothing is fetched from the internet. Poly Haven has no
people, so the characters are still the page's own.

A classic script after `world/kit.js` (its `lit`). It defines one global, `WorldAssets`.

### `var TEX`

The photo textures, each with the size in metres it covers, as Poly Haven measured it: the building
materials (`brick`, `stucco`, `concrete`) and the ground's (`asphalt`, `sidewalk`), and a gain on
its colour. Each replaces the `WorldBake` material of the same name. The gains are for the ground:
both photos were taken dry and in sun, and a city in the rain has darker asphalt and greyer paving. The rest (stone, granite, metal, roof, wood, leaves) stay
baked: trims, kerbs and the plaza's radial paving take a texture without joints of its own.

### `var SKY`

The day and night skies, each with the factor that brings its light to this world's exposure. The
night sky's lamps are many thousands of times its sky, and a reflection of one is a firefly: `dome`
also caps what any direction gives.

### `var PROPS`

The scanned props, each a `.glb`: one variant of each asset, decimated to between 600 and 3,200
triangles.

### `function image`

A texture as an image the page decodes off the main thread. The CSP allows images from the page's own
origin, which these are.

### `function rgbe`

A sky: Radiance RGBE, as written into `cc0/` without run-length encoding, so after its header the file
is the pixels, four bytes each. Anything else is refused rather than half-read.

### `function gltf`

A binary glTF read as it lies: JSON and binary chunks, accessors (interleaved ones copied out,
normalised integers made floats, as `KHR_mesh_quantization` writes them), and images decoded with
`createImageBitmap`, once each however many materials share them.

### `function glb`

A model: binary glTF as written for this page (one mesh, a material with colour, normal and
ambient-occlusion/roughness/metalness textures, WebP images inside the file). Attributes are read as
they lie, or copied out when a buffer interleaves them. The images are decoded with
`createImageBitmap`, which does not go through a URL (the CSP allows no `blob:` image), unflipped as
glTF lays them out, and without colour conversion: a normal map is data, not a picture.

### `function figure`

A character from `static/world/people/`: its skins (joints with their parents and rest transforms, the
pipeline's extras: morph joint offsets, head anchors), its skinned primitives with their roles, tones,
morph targets and maps (colour, normal, and the packed occlusion-roughness map when there is one), whether
the part is tinted (`tint`), and its animation clips. Built for the world's people pipeline's output.

### `function people`

The manifest, `people/people.json`, and every hero and crowd file it names. A set with a file missing
is no set: the world keeps its procedural people rather than half a crowd.

### `function load`

Everything at once, in parallel; whatever fails is left out, and the world uses its own procedural
version of that thing (`WorldBake`'s materials, the sky shader, the street's hydrants and bins). The
promise never rejects.

### `function texture`

A photo texture, tiled at its real size: `repeat` is one over the metres it covers, which is how the
city's materials already read their UVs (in metres).

### `function data`

A sky's RGBE bytes as a texture, read by the nearest texel: the exponent cannot be interpolated.

### `function dome`

The sphere `vReflect` renders into the environment map: both skies, blended by the daylight. The
shader decodes RGBE and filters it itself (four texels, wrapped across the seam), so it needs no float
textures and works on WebGL1.

### `function bitmap`

A model's texture. glTF's images are not flipped.

### `function scans`

Each prop's geometry and material, made once. The material is `MeshStandardMaterial` with the scan's
colour, normal and roughness/metalness maps, through the kit's lights and rain (`WorldKit.lit`), so a
hydrant under a sodium lamp turns orange and darkens in the rain. The scans' red channel is not used
as occlusion: several assets leave it empty, which would black out all indirect light.
