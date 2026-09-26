# `probe.js`

The reasoning that used to be this file's comments, moved out of the source by #523 (decisions
18 and 19 on #429). The source keeps its code and the JSDoc types `tsc` reads (docs/desk-types.md);
the server strips every comment from what it serves (`agentdata/fleet/strip.py`).

A `##` heading is a section of the file, as its banner comment named it. A `###` heading is the
declaration or statement the notes sit in or above, in source order, and each note says which
line of code it sat beside. A builder who changes the code changes its note here.

### The file

The WebGL probe (#247): what this shell really does with three.js, measured here and kept by the
desk, so the four columns of `docs/desk-engines.md` are filled from the shells themselves.

Loaded as a module after `common.js`, whose globals (`PARAMS`, `q`, `post`, `text`) it uses.
three.js comes in through `import()` rather than a static `import` for one reason: every route
on this server wants the run token, and a module specifier resolved against this file's URL does
not inherit its query string -- `q()` puts the token on, exactly as it does for every fetch.

It sends FACTS and decides nothing. Whether a renderer is hardware is `probe.classify` in
Python; the verdict shown at the end is the server's answer. It posts exactly once, on every
path -- a shell with no WebGL is an answer too, and the most important one to write down.

### `var WATCHDOG_MS`

Beside `var PER_ROW = 40;`:

12 x 40 = 480 segments: a page of handwriting, roughly

### `var HIC_API`

Beside `var FEATURES = {};`:

the table's other rows, asked first thing (#235)

### `function show`

Beside `var HIC_API = "";`:

the HTML-in-canvas upload found, as "name/arity" (#384)

### `function contextOf`

Above `function contextOf(canvas) {`:

The context, asked for the way the ink layer will ask: WebGL2 first, WebGL1 if not. The error
the browser gives with a refusal is kept, because "no WebGL" with no reason is a row nobody can
act on.

### `function named`

Above `function named(gl) {`:

The unmasked strings, or nothing. The masked `RENDERER` is "WebKit WebGL" in every Chromium and
"Mozilla" in a Firefox that resists fingerprinting, and says nothing about the machine -- so a
browser that will not unmask sends an empty string, which `probe.classify` calls `unknown`
rather than reading the mask as a GPU (#261).

### `function caveat`

Above `function caveat(kind) {`:

The browser's own opinion, as a second witness beside the string: a context asked for with
`failIfMajorPerformanceCaveat` is refused when it would be software. Not every engine says so --
headless Chromium on SwiftShader grants it -- which is why the string is the first witness.

### `function features`

Above `function features() {`:

The table's other rows (#235), asked the way `tests/test_fleet_engines.py` asks them of CI's
Chromium, so a shell's cells in docs/desk-engines.md are its own answers and not a paste out of a
dev console. Yes or no, and nothing more: what the desk does without one is the table's to say,
and `probe.feature_cell` says it. Asked before anything can fail, so a shell with no WebGL still
answers every row.

### `var HIC_NAMES`

Above `var HIC_NAMES = ["texElementImage2D", "texElementSubImage2D", "texElement2D"];`:

HTML-in-canvas (#384): whether WebGL can upload an element as a texture. The proposal has had
three generations of names, so any of them counts, and the one found is kept with its arity
(`texElement2D/6`) for docs/desk-engines.md §Pixel-level HTML. The prototype is read and nothing
more: no context is created here, and never a 2D one.

### `function containerQueries`

Above `function containerQueries() {`:

Not only "does it parse": a rule inside `@container` has to reach an element. The desk's head
sheds its words by container query, and a shell that understood the declaration and never
applied the rule would be a *works* that does not.

### `function strokes`

Above `function strokes() {`:

A fixed page of pencil strokes: the same 480 segments on every run in every shell, so two
shells' numbers are two measurements of one scene. No randomness anywhere.

### `function painted`

Above `function painted(gl) {`:

Whether the frame just rendered really holds the scene: a band of the drawing buffer across the
first line of strokes is read back and any pixel that is not paper counts. Called once, straight
after the first `render()`, while the buffer is still this frame's. `readPixels` waits for the
GPU, so this is also the moment the first stroke is on the canvas rather than merely asked for.

A band and not the buffer (#261): the whole of a 4K canvas at DPR 2 is 33 MB copied inside the
timed window, by an amount that differs per shell, and `first_stroke_ms` would be measuring the
copy. The first line sits at y 0.12 +- 0.017 of the page (GL's rows count up from the bottom).

### `function finish`

Above `function finish(facts) {`:

The one way out. Every path -- no context, three.js not loading, a lost context, a window
hidden while it drew, or three good seconds -- ends here, and here posts once. The way back is
shown before the post and taken after it whatever it answered (#261): a desk the CLI sent here
from inside an IDE has no address bar, and "not saved" with no link is a tool window lost.

### `function backLink`

Above `function backLink() {`:

When the desk sent this window here (`ad-fleet probe --open pycharm`), it goes back by itself
a few seconds after posting: a tool window left on a probe page is a desk the operator has lost.
The link is there either way. Through `/open`, which needs no token: a desk replaced while this
page drew (#242) is on the same port with a new one, and the old token would be refused.

### `function measure`

Above `function frame(now) {`:

Every frame draws the whole pencil page and the ink traced over it so far -- the pen reaches
the end of the page at three seconds. The first frame compiles the shaders and is read back,
so it is `first_stroke_ms` and not one of the intervals -- and neither is the gap after it,
which is that same compile and readback seen from the next frame (#261): with twenty frames,
a nearest-rank p95 would BE that stall. p50 and p95 are the frames after both.

Above `document.addEventListener("visibilitychange", function () {`:

A window hidden while it draws gets no animation frames at all. What it managed is posted
marked `hidden`, which the desk classifies `incomplete` and never writes over a measurement
that finished (#261); the watchdog is for frames that stop in a window still on screen.

### `function whenVisible`

Above `function whenVisible(go) {`:

Not before the window is on screen (#261). A VS Code view kept alive while hidden, or a PyCharm
tool window opened and put away, still gets the ask down the stream and comes here -- and a
hidden page gets no frames, so measuring it would post "no frames" as the shell's answer. It
waits, says so, and measures when it is looked at.
