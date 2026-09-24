# Glass on three.js

_Slice H (#254) of the ink epic (#246, [plan-ink.md](plan-ink.md)). Built: `static/ink/skins/glass.js`, beside
`static/skins/glass/skin.css`, tested by `tests/test_fleet_ink_glass.py`. The layer it draws with is
[desk-ink.md](desk-ink.md)._

Glass was a CSS skin: `backdrop-filter` over three radial gradients (#155, #182). With ink on, three.js draws the
material instead. Since #257 the stylesheet paints none of it: it holds the numbers the module reads (fill, edge,
glint, shadow, mesh) as custom properties, and under `body.ink-off` glass is the one plain look every skin shares,
with its marks drawn plain. Every variant (smoke, azure, noir, frost) is drawn from the same numbers.

## The material

| Piece | With ink on (three.js) | Under `body.ink-off` (the plain look, #257) |
| --- | --- | --- |
| the ground | a **mesh**: a plane of a few hundred vertices whose height drifts on slow waves, lit from the top left. On it, the variant's three blobs at their skin.css places, radii and a falloff to the end of each ray (#257), from `--glass-mesh-1..3` | the palette's own page: no blobs |
| the pane | **frost**: one mesh per `.tile` reads the ground texture (`sampleGround`) through a gaussian blur in its fragment shader (sigma 18px, a centre tap and rings at one and two sigma), saturated by CSS `saturate(140%)`'s own matrix, with `--glass-fill` over it | the palette's opaque panel: no frost |
| the light | the edge hairline (`--glass-edge`); the top glint (`--glass-glint`), brighter towards the light; a faint sheen where the light falls; small specular glints on the mesh's waves | the page's own hairline border |
| the shadow | drawn outside the pane only, as CSS clips a `box-shadow`: `--glass-shadow`, 12px down, 32px soft | none |
| the cards on a pane | clear over the frost (app.css, for every skin that draws) | the page's own cards |
| header, footer | clear over the lit ground, written in `--glass-ink` | the page's own |
| sidebar, popovers | the page's own opaque panel | the page's own |

With ink on, `.tile` is transparent with no shadow and clear edges (app.css, for every skin whose canvas is on the
page), so what three.js drew is exactly what the text is read on. The left edge keeps its accent, because that is
which project, not decoration, and the selection ring stays.

**Motion.** The ground is a material, so it may move (ground rule 1 is about marks). It drifts only when motion is
allowed, on its own timer at up to 30 frames a second. A frame that is late stretches the next gap to four times the
lateness, up to 500ms, so a software renderer spends a fraction of the page's time on it, not all of it. Under
reduced motion the ground stands still, and an idle desk draws zero WebGL frames.

## The state grammar

Glass has no paper, so it has no pencil (graphite needs a paper's tooth). Its marks are the palette's inks on the
frost, drawn and struck by the layer like any skin's: **drawn, never faded**. The pane answers too. Its **rim** lights
in the state's colour, drawn clockwise round the pane from the top middle over 0.6s. When the state goes, the rim runs
back the way it came over 0.45s, even though it is a material. A new state's rim is drawn only once the old one has
run back. Under reduced motion both happen at once.

Every row is a class or attribute `app.js` already sets. Glass adds no state class.

| State | The page's class | Mark (the layer) | The pane |
| --- | --- | --- | --- |
| needs you | `.tile.needs-human` | highlighter `lines` on `.repo`, and on each open question (`.asks:not([hidden]) .ask:not([hidden]) .ask-q`) | rim in `--human` |
| answered | `.ask-choice[aria-pressed="true"]` | pen `loop` round the chosen answer. Choosing another strikes it and circles the new one | — |
| running | `.tile.state-running` | pen `underline` under the `.chip` | the top glint travels along the top edge in `--running`, a lap every 4.5s. Held still under reduced motion, it tints the glint |
| error, blocked | `.tile.state-error`, `.tile.state-blocked` | marker `bang` in the pane's margin (#330) | rim in `--human` |
| done | `.tile:is(.state-done, .is-done)`: the chip's word, or the fold's for a finished agent nothing supervises, whose chip says idle (#253, #333) | green `check` in the pane's margin (#330) | rim in `--done` |
| stale (#240) | `.tile .oldsession:not([hidden])` | pen `outline`, dashed | — |
| a finding | `.tile .scopereport.outside:not([hidden])`: edits outside the scope it was given (#168) | red `ellipse` round the report | — |

Where two rims apply, *needs you* and *error* come before *done*. A mark leaves by the layer's rules: ink is struck,
and the struck mark stays (one per row and element).

**The inks** are the palette's (`skins.GLASS_INKS`): pen `--accent`, red and marker `--human`, green `--done`,
highlighter `--waiting`. Azure is the exception: its warn yellow is too light to read the text through at the frost's
lightest point (4.29:1), so its highlighter is the accent's blue (4.76:1). skin.css says so as
`--ink-highlighter: var(--accent)`, and skins.py says so as `ink_tokens`. `theme.check` holds every ink on both ends of
every variant's frost: marks at 3:1, and text through the highlighter at 4.5:1.

## The contrast is measured from the frame

skins.py declares each variant's panel as a range (`composited_range` of its mesh and fill), and `theme.check` runs on
both ends. With ink on, `test_every_variant_is_drawn_by_the_layer_and_its_panel_is_measured_from_the_frame`
**reads the frame back**. It draws a frame for the purpose with `Ink.sample`, and in the same task reads the pixels
three.js drew behind every pane's transcript with `gl.readPixels`. It does this twice, with the ground drifted between.
Their darkest and lightest are what `theme.check` is run against, with the variant's inks. They also have to sit inside
the declared range (within 14 of luminance, for the blur at an edge and the light on the mesh) and to vary across it,
because a single colour is paint, not glass. Measured under SwiftShader:

| Variant | Measured | Declared |
| --- | --- | --- |
| smoke | `#171D25` … `#1A422B` | `#181D24` … `#273D57` |
| azure | `#0E2142` … `#153F5B` | `#11213B` … `#1D3F56` |
| noir | `#0A0A0A` … `#111C28` | `#0A0A0A` … `#202020` |
| frost | `#D5DAD6` … `#F5EEDA` | `#DED4B8` … `#F3EDDD` |

## What the module keeps

`frame` is called when a pane appears and when its size changes. `tick` reads each pane's classes and moves its rim
and glint uniforms, advances the ground's clock, and repaints the colours if skin.css landed after the module. It
never writes the page. The module keeps its panes, the ground's uniforms and the timer for `tick`, and `dispose` lets
all of them go. The ground's render target is the layer's (`sampleGround`), freed when the skin changes. The tests read
the module's state through its `inspect()` export, on the same instance `ink.js` imported.

## Tests

`tests/test_fleet_ink_glass.py` covers the following. The states come from `/api/fleet` rows the test changes, so
`app.js` sets every class itself.

* **Every variant is drawn by the layer**, with the panes transparent over it, and the panel is measured from the frame.
* **The frost samples the ground**: over a test ground split red and blue, each side shows through, and both show
  near the line, blurred.
* **The ground drifts only when motion is allowed**. An idle desk is zero DOM mutations either way, and zero WebGL
  frames under reduced motion.
* **Each state is marked and leaves struck**, the rims are right, and the running glint runs.
* **The rim is drawn round and runs back** over frames, and the ink settles within the layer's frame bound.
* **Under `body.ink-off`, every variant is the plain look** (#257): the palette's opaque panel, no frost, the same
  marks drawn plain, and three.js is never fetched.
* **`dispose` frees the ground's render target** when the skin changes.
* **The module keeps the skin rules**: no import, no colour in the module, no page write, and no class the page does
  not set.

`tests/test_fleet_skins.py` holds the stylesheet, skins.py and the module to one mesh and one set of inks.
`tests/regressions/test_20260923_any_idle_skinned_desk_writes.py` holds an idle skinned desk at zero mutations. That
bug was found here: the page rewrote the theme's attributes on every refresh.
