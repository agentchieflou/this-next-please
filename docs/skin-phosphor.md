# Phosphor: a green screen, scanlines and a beam that draws

_#394, epic #294 (every palette gets a look). A skin that draws with the ink layer
([desk-ink.md](desk-ink.md)). Chosen like any skin: `theme.skin` is `phosphor` (or `phosphor:green`),
from the settings page or `POST /api/theme {skin}`. It is drawn on the `matrix` palette ("phosphor on
black; the falling code screen", [themes.md](themes.md) §The Gallery), which before it was drawn only
as Voxel · Overworld._

| File | Is |
| --- | --- |
| `agentdata/fleet/static/ink/skins/phosphor.js` | the mark table (the notebook's), the beam's tuning, the glass (`paper`) |
| `agentdata/fleet/static/skins/phosphor/skin.css` | the glass and every ink as custom properties, and the stand-aside; nothing it paints (#257) |
| `agentdata/fleet/skins.py` (`phosphor`) | the variant, its base palette, the glass's two ends and the inks `theme.check` holds |
| `tests/test_fleet_ink_phosphor.py` | everything on this page |

## The glass

With ink on, three.js shades one quad the size of the viewport (`paper`, called on arrival, on a
resize and on a palette change, never per frame):

* near-black glass, `--paper` `#010603`;
* a lit row every third pixel row in `--scan` `#0A1F10`: the scanlines, 1.18:1 on the glass;
* a corner vignette darkening by at most 20%, and a faint static grain;
* every channel clamped to [`--paper`, `--board-max`], so every pixel of the glass is between the two
  colours of the panel pair, `#010603` … `#0A1F10`, which `theme.check` holds at both ends. A browser
  test reads the canvas back under the transcripts and finds every point inside that range (±1).

Nothing on it moves. No flicker, roll, bloom pulse or loop of any kind: that is a photosensitivity
rule as well as the render contract (an idle desk makes zero WebGL frames).

The panes, the header and the footer stand aside for the canvas as they do on the notebook: a pane
is a region of the glass, not a card. The words stay in the desk's `--mono`, in the palette's own
text colour; no handwriting and no web font. The DOM keeps every word: no letter is drawn.

## The beam

The mark table is the notebook's, rows and selectors unchanged ([skin-notebook.md](skin-notebook.md),
[desk-ink.md](desk-ink.md) §The state grammar across skins). What changes is how it is drawn:

* **One tune for every drawing tool** (`options.tools`: the pencil, the pen, red and green): 1.3px
  wide, full pressure with no variation, no wobble, no bow and no taper. A trace, not a hand.
* **No hand** (`hand: false`): nothing holds the beam.
* **Speed 1.5**: a beam sweeps faster than a pen writes.
* **The running line's tip** is the beam's spot, resting at the end of the line it is drawing.

Reduced motion draws every mark at once, as on every skin.

## The inks

| Tool | Ink | On `#010603` / `#0A1F10` |
| --- | --- | --- |
| text (the palette's) | `#3DF07A` | 13.56 / 11.46 |
| pencil | `#3FA866` | 6.81 / 5.76 |
| pen | `#00FF41` | 14.95 / 12.64 |
| red, marker | `#FF3B3B` | 5.78 / 4.88 |
| green | `#A8FFC0` | 17.24 / 14.58 |
| highlighter | `#CCA13B` | the text through it: 5.96 / 4.73 (screened) |

The palette's `--muted` (`#2CAD57`, #325) keeps 4.5:1 at both ends. The pencil colours the stale
note, red a finding's text and the pen the header's count; each is 4.5:1 or more at both ends.

The highlighter is the palette's amber (`--waiting` `#E3B341`) a shade darker. Screened onto the
glass at the layer's strength (`theme.highlight_under`), `#E3B341` leaves the text 4.21:1 on the
scanline end; `#CCA13B`, the same hue, keeps 4.73:1 there and 6.04:1 plain.

## Without ink

With `?ink=off`, or wherever WebGL is not measured as hardware, the page is the palette's own plain
look (`body.ink-off`): its ground, its panel, no canvas and no three.js, and the same mark table drawn
as the layer's plain CSS.

## Names

The look recalls a film's green screen. Its strings and its art use names of our own (#318): the
module, the stylesheet, their notes, and the skin's and variant's titles and whys match none of the
film's names, its people or its studio, and the palette's slug appears only as the variant's `base`
in `skins.py`. `tests/test_fleet_ink_phosphor.py` checks it.
