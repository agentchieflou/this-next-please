# `m/m.js`

The reasoning for this file, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and JSDoc type tags; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order. A
builder who changes the code changes its note here.

### The file

/m (#581): the phone page. A classic script like `map/map.js`, loaded after `common.js`, whose
token, `q`, `post`, `pageUrl`, `patchList`, setters, `applyTheme` and `applySkin` it uses and
nothing else. It reads `GET /api/attention` (#559: the mobile bridge's allow-listed rows, never
`/api/fleet`'s) and, for the open agent's waiting approval, `GET /api/approval?id=`. It draws one
`li` per row, keyed by `repo` through `patchList`, and one open agent's sheet. It does four
things: `approve {id, reason}`, `deny {id, reason}`, `send {repo, message}` and
`answer {repo, answers}`, the bodies `serve.act` takes, through `post`. Every answer is written into
`#said` (`aria-live="polite"`) in the server's words: its `error` and `hint` for a refusal.

The render contract holds as on the desk: every write goes through the setters, so a refresh with
nothing new to say makes zero DOM mutations, and an idle page (no frame but `tick`) refreshes
nothing at all. The page shows the server's words and classes (`state`, `role`, `needs_human`)
and has no fold, chip grammar or state colour of its own. Not inked: `/m` is not in
`INKED_PAGES`, and `ink-off` stays on.

### `var W_NAME`

Above `var W_NAME = PARAMS.get("w") || "phone";`:

The window this page is, as its stream reports it (`live_entry`): `phone` unless the query says
otherwise (`/open?page=m&w=...` forwards `w`, `shell` and `ink`).

### `var M_GLYPHS`

Above `var M_GLYPHS = {`:

The chip's glyph per state: the same table as the desk's rail (`RAIL_GLYPHS` in `app.js`), and
`tests/test_fleet_components.py` holds the two equal, so the phone never grows a grammar of its
own.

### `var mState`

Above `var mState = { ... };`:

`rows` are the last attention rows; `open` the repo whose sheet is shown and `shown` the one whose
inputs were last cleared; `record` the open agent's approval as `/api/approval` gave it;
`cursors` each agent's last event seq, so a reconnect resumes (`since`) rather than replays;
`reading` counts the list reads in flight; `frames`, `ticks` and `refreshes` are for the tests
(`window.FleetPhone`).

### `function mAge`

Above `function mAge(s) {`:

The row's `age_s`, coarse: "now" under 90 s, then minutes, hours, days. It changes only when a
refresh brings a new row; nothing ticks it on the page.

### `function drawAgent`

Above `function drawAgent(li, row) {`:

One row: the name, the chip (`.chip <state>`, the desk's own rule in `app.css`) with its glyph
and word, the age, and `says`. `needs-human` from the row's `needs_human`, and `data-role` from its
`role`, for a skin.

### `function drawAgents`

Above `function drawAgents() {`:

The list and the header's count, "N need you".

### `function mRead`

Above `function mRead() {`:

The open agent's approval, fetched once per id: a refresh with the same `approval_id` does not
ask again, and an agent with none clears it.

### `function drawOpen`

Above `function drawOpen() {`:

The sheet for `mState.open`, or nothing. The reason and reply fields are cleared only when a
different agent is opened, never under the operator's thumb by a refresh.

### `function drawApproval`

Above `function drawApproval(a) {`:

The approval card: its summary and the scrubbed `payload_preview` (a truncated one is
`{truncated, bytes, head}`), and its id on the card for the two buttons.

### `function drawAsks`

Above `function drawAsks(row) {`:

The row's blocking questions (`questions`, at most the bridge's cap): each with its choices as
`.ask-choice` buttons, which fill its answer field, and the field itself. `answer` sends every
question's field in one body; the server drops the empty ones and refuses "nothing to answer" when
all are.

### `function mPost`

Above `function mPost(what, body) {`:

One verb: the live line says what is being asked, then the server's answer, and the list is
read again. A verb the server took clears its own field (the reason after a decision, the reply
after a send), so the next approval never inherits the last one's reason. A deny with no reason is
sent as it is, so the server's own refusal ("a denial needs a
reason") is what the operator reads.

### `function mSoon`

Above `function mSoon() {`:

Stream frames come in bursts (a replay, a turn's events); one refresh 400 ms after the first, as
/map does.

### `function mConnect`

Above `function mConnect() {`:

The desk's stream, as /map opens it: `page=m`, `notify=0` (only a desk's stream sweeps the
notifications), `w` and `shell`. `tick` marks it live; `onerror` says `reconnecting`, closes, and
after 2 s reads the list again and then reconnects, unless the page is hidden.

### `document.addEventListener("visibilitychange", ...)`

Above `document.addEventListener("visibilitychange", function () {`:

As the desk does since #579: a hidden page closes its stream, and a shown one reads the list once
and reconnects from its cursors.

### `window.FleetPhone`

Above `window.FleetPhone = Object.freeze({`:

For the tests: the window name, the rows, the open agent and the stream's counts. Read-only.
