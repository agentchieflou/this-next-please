# `map/scene.js`

The reasoning for this file, kept out of its source (#523, decisions 18 and 19 on #429). The source
keeps its code and the JSDoc types; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration the notes are about, in source order. A builder who changes the
code changes its note here.

### The file

The map's scene (#409, docs/fleet-map.md §The scene): where the probe measured hardware WebGL (or
with `?ink=on`, the test override), `/map` draws its tree as a three.js scene. It is an ES module,
fetched by `map/map.js` through `q()` only when the gate is on, and it fetches three.js and
`map/layout.js` the same way, never with a static import: a module specifier resolves against the
importing file's URL, which does not carry the run token (docs/desk-ink.md §The files).

The scene reads the page, never the JSON (epic #295, ground rule 1): `outlineOf` reads the tree's
items, their classes and their `data-*`, `layout()` places them, and the scene draws what comes back.
It writes nothing to the page but its own canvas, which it appends once and removes when it stops.

There is no frame loop. A frame is asked for when something the picture depends on changed: the
tree, the stage's size, the palette. An idle map draws zero WebGL frames and makes zero DOM
mutations, and nothing on it moves (motion is #413's).

### `const KEYS`

The three instanced meshes: checkout islands, lanes (trunks, unmerged
lanes and merged stubs), and nodes (each project's gate and every network node). With the links'
one `LineSegments` that is four draw calls whatever the size of the fleet, which leaves two of the
map's six for #410's agents.

### `const TREE`

The attributes of the tree the outline is read from: an item's classes, a checkout's `data-on`,
every item's `data-node`, and a project's `data-default` and `data-name` (the trunk's id is
`b:<name>:<default>`). Plugins add theirs with `attrs`.

### `const PAGE`

What a palette change writes on `<html>`: `applyTheme` sets the tokens in its `style` and
`data-theme`; `class` as the ink layer watches it. `SKIN` is the skin on `<body>`.

### `const SHADE`

The vertex colour of each face of the unit box, in `BoxGeometry`'s face order (+x, -x, +y, -y, +z,
-z): the top is 1.0 and the sides 0.82 and 0.68, so an unlit material shows the boxes' form without
a light, and a top face renders exactly its instance colour -- which is what the tests read back.

### `const LIFT`

How thick a lane is: a road a sixteenth of an island's width high, under every island.

### `const PAD`

The margin round the fitted map, 8% of what it spans.

### `const WORDS`

A record whose target is inside an item's words (`.say`), its branch chip, or one of its buttons is
the page rewriting text, not structure, and wakes nothing. The issue names `.say`; the chip and the
buttons are words in the same sense.

### `const plugins`

The plugins `use()` was handed, kept by the module, so one handed over before `start` is attached
when the scene starts. `late` is the running scene's way to attach one handed over afterwards.

### `const clamp`

Copied from `ink/layer.js` with `parseColour`, which needs it.

### `function parseColour`

Copied verbatim from `ink/layer.js` (#409 Build 2), and a test holds the two equal
(`tests/test_fleet_map_scene.py`): the map reads the palette the way the desk's ink does, without a
2D context. The map does not load the layer, so it cannot import it.

### `function context`

Copied verbatim from `ink/layer.js`, held equal by the same test. The context is asked for before
three.js is fetched, the way the probe and the layer ask: a shell that will not give one turns the
scene off without fetching the library.

### `function luminance`

WCAG relative luminance, with `theme.rel_luminance`'s 0.03928 knee; `contrast` is the WCAG ratio.

### `function structural`

The one structural colour (#409 Build 5): `--text` mixed toward `--bg` at the largest share of
`--bg`, in hundredths, that keeps 3:1 on `--bg` (WCAG 1.4.11), each candidate rounded to a byte
first so the colour drawn is the colour measured. It is the shape of `theme._muted` (#325), at 3:1
for a mark rather than 4.6:1 for a word. `--panel` is about 1.1:1 on `--bg`, `--muted` is under 3:1
in most palettes, and `--accent` is `--running` on dark, so none of them can carry structure.
Trunks, lanes, stubs, islands, gates, network nodes and links are all this one ink: role colours
are reserved for agents (#410), and unmerged against merged is length and width only.

### `function hex`

A colour as `#rrggbb`, for `inspect`.

### `function tokens`

The palette, read on `document.body` when the scene paints: `css(name)` is the token as written,
trimmed; `rgb(name)` is it as `[r, g, b]` in 0-1 sRGB; `bg`, `panel`, `line`, `accent`, `muted` and
`text` are read at once, and `ink` is derived from them. A name may carry its `--` or not.

### `function outlineOf`

The tree (`#maptree`) as `layout()`'s outline (docs/fleet-map.md §Layout): a project is a root
`p:` item, its branches the `b:` items of its `bs:` group (a deleted, `gone` branch included, so
its lane keeps its place until the tree lets it go), its checkouts the `c:` items with `main`,
`data-on` and their `a:` item, and the network the children of `n:network`; `stale` is every `a:`
item with that class. Nothing is read from the JSON, so the scene carries nothing the tree lacks.

### `function block`

The unit box every instance is scaled from, with the face shading of `SHADE` as its `color`
attribute. Its groups are cleared: one material draws it in one call.

### `function instanced`

An `InstancedMesh` of `cap` instances with its `instanceColor` made up front, so the material is
compiled with instance colours from its first frame rather than recompiled when the first one is
set. Grown from `from`, it copies every matrix and colour, reserved ones included. Frustum culling
is off: an instanced mesh's bounding sphere is computed once, and would cull instances placed
after it.

### `function use`

Hands the scene a plugin (#409 Build 9): `{attach(ctx), rebuilt(prev, next, placed, laid),
recoloured(tokens), frame(dt), inspect(), attrs}`, every member optional. The later map cards
(#410-#414) each add one to `MAP_PLUGINS` in `map/map.js`, which hands them over before `start`.
One handed over while the scene runs is attached at once, its `attrs` join the observer, and it is
told of a rebuild on the next frame.

### `function start`

Context first, then three.js and the layout module in parallel, then the renderer, the four
meshes, and the observers. The canvas goes on the page and the first frame is asked for once the
tree has drawn (`host.ready`), so the first frame is the fleet rather than an empty stage. Resolves
to `{inspect, sample, screen, stop}`; `map/map.js` keeps `stop` and hands the rest to the page as
`FleetMap.scene`.

A lost context (`webglcontextlost`) calls `host.off`, which stops the scene and leaves the tree for
the page's life; a restored context is not taken back up, as on the desk.

In `start`, `kick`: the one place a frame is asked for, and only when none is pending, so anything
that happens before the next frame is drawn in that one frame.

In `start`, `call`: a plugin that throws is reported and skipped; the scene keeps drawing.

In `start`, `grow`: a mesh is replaced only when its instances outgrow its capacity, at twice the
size, and the new one takes the old one's material, matrices and colours. `ctx.meshes` is updated in
place, so a plugin that reads it after a rebuild has the current mesh.

In `start`, `reserve`: hands a plugin `n` instances of one mesh (by its key or the mesh itself),
kept across rebuilds. They sit before the scene's own, so their indices never move; they start
scaled to nothing, and the scene never colours or places them.

In `start`, `wire`: every link as a segment between the two boxes' centres, in one `LineSegments`
whose buffer grows like a mesh's.

In `start`, `rebuild`: the outline, its layout, and every instance placed. Agents are placed by the
layout but not drawn (#410 draws them). `placed` maps every drawn id to `{mesh, key, index}`;
`tops` holds the top centre of every box (agents included) for `screen`; `shapes` holds every box
for `fit`.

In `start`, `fit`: an isometric camera -- orthographic, looking down the (-1, -1, -1) diagonal at the
centre of `layout().bounds` -- whose frustum is fitted to every box the layout placed, projected
onto the camera's axes, plus `PAD`. Fitting the bounds' eight corners instead left a diagonal
layout a third of the stage, because the corners of an isometric box stand far outside what is
drawn inside it. It runs on every rebuild and every resize.

In `start`, `resize`: the drawing buffer is the stage's size at `devicePixelRatio`, capped at 2 as
the ink layer caps it; the canvas's CSS box is `map.css`'s.

In `start`, `draw`: one frame: what is dirty is made again (size, colours, outline), each plugin's
`frame(dt)` is called, and the scene is rendered once. A frame is asked for again only while a
plugin says it is busy. `performance.mark("map:first-draw")` on the first.

In `start`, the observers: the tree (child lists and `TREE`'s attributes, plus every plugin's
`attrs`), the stage's `ResizeObserver`, the palette's attributes on `<html>` and `<body>`,
`prefers-color-scheme`, and a capturing `load` listener for a stylesheet, which catches a skin's
`link[data-skin]` whenever it was created; a `resize` of the window matters only when the
device pixel ratio changed (a monitor with another scale), since the stage's own size is the
`ResizeObserver`'s.

In `start`, `inspect`: `{frames, samples, calls, triangles, nodes, busy, first_draw_ms, colours:
{ink, bg}, size, canvas, reserved, plugins}`, every plugin's `inspect()` merged under it. `frames`
counts the frames the scene drew on its own; `samples` the frames `sample` drew; `calls` and
`triangles` are the last frame's; `nodes` is every id drawn.

In `start`, `sample`: draws one frame now and, given viewport points, reads each one's pixel back
in the same task, before the browser can clear the drawing buffer.

In `start`, `screen`: an id's top centre on the viewport, in CSS px, or `null` for an id the scene
has not placed.

In `start`, `stop`: everything `start` listened to is let go, the renderer is disposed and its
context released, and the canvas leaves the page.
