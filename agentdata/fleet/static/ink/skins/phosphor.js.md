# `ink/skins/phosphor.js`

The reasoning for this file, kept beside it rather than in it (decisions 18 and 19 on #429). The
source keeps its code; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `##` heading is a section of the file. A `###` heading is the declaration or statement the notes
sit in or above, in source order. A builder who changes the code changes its note here.

### The file

```text
Phosphor (#394): a green screen, and the state grammar drawn on it by a thin, even beam. The page is
near-black glass with faint scanlines; every mark is the notebook's, traced at an even width.

THE DOM IS THE TRUTH. The mark table is the notebook's (static/ink/skins/notebook.js), rows and
selectors unchanged: every row is a class or an attribute app.js already sets. Nothing here decides
a state, and nothing here draws a letter: a `write` row uncovers the element's own text.

No colour is written in this file. The glass and the inks are custom properties in
static/skins/phosphor/skin.css (`--paper`, `--scan`, `--board-max` and `--ink-<tool>`), read
through `tokens` at paint time.
```

### `export function marks`

The notebook's rows, in the notebook's order (docs/skin-notebook.md explains each). The running
row keeps `grow` and `tip`: on this screen the tip is the beam's spot, resting at the end of the
line it is drawing.

### `const T`

The beam: one tune for every drawing tool. An even width (`w` 1.3), full pressure with no
variation, no wobble, no bow, and no taper at either end -- a trace, not a hand.

### `export const options`

`paper: "--paper"` tells the layer the stock is dark, so the highlighter screens onto it.
`hand: false`: nothing holds the beam, so no hand is drawn. `speed: 1.5`: a beam sweeps faster
than a pen writes. `tools` gives the pencil, the pen, red and green the beam's tune; the marker and
the highlighter keep the layer's own.

### `function rgbOf`

A custom property's colour as [r, g, b] in 0-1 sRGB, as `tokens.css` answers it: a hex, or rgb().

### `const GLASS_FS`

The glass, shaded in viewport pixels:

- near-black `--paper`, with a lit row in `--scan` every third pixel row: the scanlines, about
  1.18:1 on the paper;
- a faint static grain, a per-pixel hash of a few levels;
- a corner vignette that darkens by at most 20%;
- every channel clamped to [`--paper`, `--board-max`], so whatever the grain and the vignette do,
  the text is read on a colour inside the panel pair `skins.py` declares and `theme.check` holds.

Nothing in it moves: no flicker, no roll, no bloom and no loop of any kind (photosensitivity and the
render contract, docs/desk-ink.md).

### `export function paper`

The glass behind the panes, one quad the size of the viewport. The layer calls it when the skin
arrives, when the window is resized and when the palette changes, never per frame.
