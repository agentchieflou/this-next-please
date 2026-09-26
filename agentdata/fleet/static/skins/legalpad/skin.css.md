# `skins/legalpad/skin.css`

The reasoning that used to be this stylesheet's comments, moved out of the served source by #523
(decision 18 on #429): a file the desk serves carries rules and nothing else.

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
rule or at-rule the notes sit in or above, by its selector or prelude, in source order, and each
note says which line it sat beside. A builder who changes a rule changes its note here.

### The file

```text
The legal pad skin (#251, slice E of the ink epic #246): a yellow legal pad -- canary stock, blue
rules on the page's 28px baseline, a double red margin down every pane and the gummed band a pad
is bound by across the top. Effective composited panel: #FCF3A6, the canary itself.

The pad is drawn by the ink layer (`static/ink/skins/legalpad.js`), which reads every colour it
uses from the custom properties below at paint time. This file keeps three jobs:
* the colours, as custom properties on <body>: the stock, its rules, its margin and its glue,
  and the inks a palette would otherwise choose where they would not read on canary -- above all
  the highlighter, orange-pink rather than the palette's amber (`skins.py` declares the same
  numbers, and `theme.check` holds every one of them to the paper);
* the layout the pad needs: the pane's text starts right of its margin, and the header sits
  below the glue;
* the typography: a hand for what the page writes by hand.
Since #257 it paints nothing: under `body.ink-off` the legal pad is the one plain look every skin
shares (app.css and the palette), with its mark table drawn as plain CSS by the layer's fallback
in these same inks.
```

### `body[data-skin="legalpad"]`

Above `--hand: "Segoe Print", "Bradley Hand", "Chalkboard SE", "Comic Neue", "Comic Sans MS", c …`:

A hand, where the page writes one: a local cursive face, never a download.

### `body[data-skin="legalpad"]:not(.ink-off) header`

Above `body[data-skin="legalpad"]:not(.ink-off) header { margin-top: 10px; }`:

The header sits under the glue, which the layer draws across the top 10px.

### `body[data-skin="legalpad"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail …`

Above `body[data-skin="legalpad"]:not(.ink-off) .tile[data-tier]:not([data-tier="rail"]) { padd …`:

A pane is a sheet of the pad: its text starts right of the double red margin the layer draws. A
rail has no margin.

### `body[data-skin="legalpad"]:not(.ink-off) .tile[data-tier="compact"] .head`

Above `body[data-skin="legalpad"]:not(.ink-off) .tile[data-tier="compact"] .head { row-gap: 8px …`:

The running pen and its tail under the name (#332): a compact pane's head wraps the name onto a
line of its own, and the line 2px below its foot needs more than app.css's 2px before the number
and the chip on the next line; the stale outline keeps off the chip row the same way.

### `body[data-skin="legalpad"]:not(.ink-off) .tile .transcript`

Above `body[data-skin="legalpad"]:not(.ink-off) .tile .transcript {`:

The transcript is written on the rules (#338): a row is the pad's 28px, its rows end at its
bottom, where the module measures its rules from, and it scrolls in whole rows. The rules are
its dividers, so a row draws none.

### `body[data-skin="legalpad"]:not(.ink-off) .tile .transcript > li > *`

Above `body[data-skin="legalpad"]:not(.ink-off) .tile .transcript > li > * { position: relative …`:

Centred in its 28px, a 12px line would end 6px above the rule; 2px lower it sits on it. The row
clips what is moved, so the list scrolls no further than its last row's end.

### `body[data-skin="legalpad"] .oldsession, body[data-skin="legalpad"] #bellcount`

Above `body[data-skin="legalpad"] .oldsession,`:

Handwritten: the stale note and the header count.

### `body[data-skin="legalpad"]:not(.ink-off) #bell`

Above `body[data-skin="legalpad"]:not(.ink-off) #bell { background: transparent; padding-left: …`:

Room beside the count for the number it replaces, which the layer keeps there, struck.

### `body[data-skin="legalpad"]:not(.ink-off) header`

Above `body[data-skin="legalpad"]:not(.ink-off) header { will-change: transform; }`:

The page's own drawing (#337, docs/desk-ink.md): the clear header gets its own compositor layer
-- without it Chromium showed the canvas with a band missing along the foot of the panes, the
renew strip's rectangle mirrored -- and the renew and away strips stand aside for the canvas
like the panes. Keyed here, not on `body:has(> #ink[data-skin])`, which Chromium 153 does not
re-apply when it starts matching late (#441).
