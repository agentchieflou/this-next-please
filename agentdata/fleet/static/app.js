/* The multi-viewer's client. No framework and no build step on purpose: this file has to load
   inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
   fetched from the internet simply does not arrive.

   The page is a view. It never decides anything -- every state comes from /api/fleet and every
   button POSTs to the same function the CLI verb calls. */

"use strict";

/* `PARAMS`, `TOKEN`, `q`, `post`, `text`, `applyTheme` and `applySkin` come from common.js, which
   every page loads before its own script. */

/* ------------------------------------------------------------------ the records, typed (#236)

   What the desk moves, written down once where a checker can read it. `tsc` reads these comments
   against the code (`tsconfig.json`, docs/desk-types.md) and nothing compiles them, so the page is
   still exactly this file. Typed where plan-panes §G asked: the one door and the window's writes
   (#230), the row and its panes (#233), the widths and the gutters (#234). */

/** The desk every window on this server agrees on: `desk_state()` in serve.py. It reaches the page
 *  four ways -- the stream's `desk` frame, `/api/fleet`, `/api/desk` and a window write's own answer
 *  -- and all four come in through `acceptDesk`. Optional throughout, because the page also holds
 *  desks that are not the server's: the one it starts with, and the snapshot it draws while the
 *  first answer loads (#219), whose version is taken off so that answer wins.
 * @typedef {Object} DeskRecord
 * @property {number} [schema]            2 since #232
 * @property {string} [selected]          the project every window's inspector follows (#133)
 * @property {number} [version]           only ever rises; anything lower is dropped at the door
 * @property {string} [at]                when it last changed, UTC
 * @property {Arrangement} [arrangement]  one for the whole desk (#232)
 * @property {Object<string, WindowRecord>} [windows]  each window's own record, by its `?w=`
 * @property {Object<string, number>} [measure]  `ad-fleet probe` asking a window to measure (#247)
 */

/** The one arrangement (#232): the same agents in the same order on every screen. `size` is #217's
 *  footprint as an older build wrote it -- a bare number in an older file still -- read as the
 *  starting widths of a window that has none of its own, and never written (#234).
 * @typedef {Object} Arrangement
 * @property {string[]} [order]
 * @property {Object<string, {cols: number, rows: number} | number>} [size]
 * @property {string[]} [pinned]
 * @property {string[]} [hidden]
 */

/** One window's own record: `WINDOW_FIELDS` in serve.py (#172). `focus` and `held` are an older
 *  page's -- the needs-only filter the *needs me* preset replaced (#234) -- which the server keeps
 *  for it; this page neither reads nor writes them.
 * @typedef {Object} WindowRecord
 * @property {string} [open]              the one pane the keys and the composer address (#230)
 * @property {boolean} [focus]
 * @property {Object<string, number>} [read]  the last event read, by repository
 * @property {string} [seen]              when this window last looked; the away strip reads it
 * @property {string[]} [held]
 * @property {string} [section]           the sidebar's open section (#148)
 * @property {Widths} [widths]
 * @property {number} [widths_at]         the desk version the widths were written at: a write of
 *                                        widths heard before it is refused (`widths_stale`)
 */

/** A window's widths (#234): each pane's weight, by repository. 0 is a 48px rail, and a positive
 *  number that pane's share of what the rails leave.
 * @typedef {Object<string, number>} Widths
 */

/** What this page writes to its own record -- not the whole record. A field one arrangement wrote
 *  and another read was the snap-back (plan-panes ground rule 2), so writing `zoomed`, or the
 *  retired `focus`, is a type error here before it is a bug on the glass.
 * @typedef {Object} WindowWrite
 * @property {string} [open]
 * @property {Widths} [widths]
 * @property {Object<string, number>} [read]
 * @property {string} [seen]
 * @property {string} [section]
 */

/** A desk as it arrives: the record, and on an action's answer the envelope every POST carries,
 *  which `acceptDesk` takes off. A refusal is the envelope alone, with the server's words (#163).
 * @typedef {DeskRecord & {ok?: boolean, action?: string, error?: string, hint?: string,
 *                         code?: string}} DeskAnswer
 */

/** One agent's row, as `/api/fleet` sends it. Typed in the fields the typed part reads -- `project` is
 *  the project the checkout is one of (#175), `why` what it asks when it needs a person, `recent`
 *  the last events of its run -- and open for the rest, which the rest of the page reads as it
 *  always has. Open means a field this list does not name reads as `any`, not as an error: closing
 *  it is the widening's to do, not this slice's.
 * @typedef {{
 *   repo?: string, project?: string, path?: string, state?: string, needs_human?: boolean,
 *   why?: string, last_said?: string, last_event_age_s?: number,
 *   spend?: {total?: number, [field: string]: any}, recent?: Array<{seq: number}>,
 *   as_of?: {run: string, n: number},
 *   [field: string]: any
 * }} Row
 */

/** Which of the three widths a pane is drawing (plan-panes §The pane). `setTier` alone writes it.
 * @typedef {"rail" | "compact" | "full"} Tier
 */

/** The widths the tiers change at, in CSS pixels (#235): `fleet.tiers.*` as `settings.tiers()` reads
 *  them, on the theme payload. CI's numbers when the file sets none -- or sets four that do not go
 *  together, when `invalid` says why.
 * @typedef {Object} Tiers
 * @property {number} rail                the rail's width
 * @property {number} compact             compact from
 * @property {number} full                full from
 * @property {number} slack               how far past compact/full a pane goes before it changes
 * @property {string} invalid             why the file's four were not drawn, or ""
 */

/** A pane: one agent in the row, and its entry in `tiles` (#233). `el` is its `.tile`, made once by
 *  `makeTile` and patched after (#215), carrying `data-repo` and `data-tier`; `seq` is the last event
 *  drawn into its transcript, and `row` what it was last drawn from. `restored` marks a pane drawn
 *  from the window's snapshot, whose transcript its first real row brings (#347).
 * @typedef {Object} Pane
 * @property {HTMLElement} el
 * @property {number} seq
 * @property {Row} [row]
 * @property {boolean} [restored]
 */

/** @type {Map<string, Pane>} */
var tiles = new Map();          // repo name -> {el, seq}
var pendingRefresh = null;
var source = null;
var arrivedSinceLastPlace = false;   // a pane was made since the order was last put right (#233)

/* #232: one arrangement. The page used to be four, chosen by `?layout=` -- `column`, `grid`,
   `roles` and `screens` -- and all four wrote one window record, which is how a `zoomed` the grid
   left behind came to snap the column back to it (#230). The operator retired the choice
   (`docs/fleet-layouts.md` §The decision): one row of panes, one per agent (#233). An address
   from a bookmark or an older launcher still carries the parameters; the desk opens anyway,
   says once in the footer that they are ignored, and takes them off the address so a reload
   does not say it again. */
var RETIRED_PARAMS = ["layout", "view", "screen"];
var ignoredParams = RETIRED_PARAMS.filter(function (k) { return PARAMS.has(k); });
var W_NAME = PARAMS.get("w") || "main";
/* The anchor this page was OPENED with -- a toast's `#tile=luna` -- read before anything on it can
   write one of its own: opening an agent marks the address with `replaceState`, which is the same
   string the page would otherwise take for a toast's (#234). */
var BOOT_HASH = location.hash || "";

/** Everything the last `/api/desk` said, and in `desk.desk` the record every window agrees on.
 *  @type {{desk: DeskRecord, [answer: string]: any}} */
var desk = { projects: {}, offers: {}, unsorted: [], not_offered: [], folders: [],
             desk: { selected: "" } };
var pendingDesk = null;
/** @type {Object<string, number>} */
var readCursors = {};
var streamDead = false;
var awayShown = false;
var appliedInitialWindow = false;
/* Which agent this window has OPEN (#203) -- the pane in the row that has the width (#233) -- and
   the one it had before: `Esc` goes back to that rather than to nothing, because "show me the
   other one for a second" is the gesture the swap is for. Per window: the left monitor reads one
   agent while the centre reads another, and `selected` stays the one thing every window agrees
   on. */
var openTile = "";
var previousOpen = "";
/* This window's widths (#234): each pane's weight, 0 a rail and a positive number its share of
   what the rails leave -- or null while the window has never been given any, when the open pane and
   the pins share the row as they did before the gutters. Per window, like `openTile`, because two
   monitors can hold different widths over the same agents in the same order. */
/** @type {Widths | null} */
var myWidths = null;
/* Whether a drop opens the dispatch card (#164) or launches the way #98 did. The server's
   `fleet.preflight` decides; until the first `/api/fleet` answers, the card is the default,
   because showing a card and starting from it is the recoverable direction to be wrong in. */
var PREFLIGHT = true;

/* This window's own record -- which agent is open, what it has read. Posted and not waited on:
   the page has already drawn the change, and a window record that failed to save is a preference
   lost, not a wrong screen. A refusal is still said out loud (#219) rather than swallowed.

   One at a time, and in the order they were made (#230). Four clicks inside a frame were four posts
   in flight at once, and the server applied them in whatever order its threads took the lock: the
   page asked for alpha last and the record ended on delta. Until the last of them is answered,
   anything else the server sends describes the window as it was, and applying it put back the
   agent the operator had just clicked away from -- so `acceptDesk` leaves the window alone while
   `windowWrites` is above nought. Each answer is the desk as of its own write, and comes in through
   the one door like everything else. */
var windowWrites = 0;
/** @type {Promise<DeskAnswer | null | void>} */
var windowChain = Promise.resolve();

/** @param {WindowWrite} patch
 *  @returns {Promise<DeskAnswer | null | void>} the server's answer, or null when the post failed */
function saveWindow(patch) {
  /** @type {WindowWrite & {w: string, version?: number}} */
  var body = Object.assign({ w: W_NAME }, patch);
  windowWrites += 1;
  windowChain = windowChain.then(function () {
    /* Widths carry the version this page last heard (#234), read as the post goes rather than when
       the gesture was made: by then the answer to this page's previous write has come in through
       the door, so the server refuses only another page's widths under the same `?w=`, never this
       page's own. */
    if (body.widths !== undefined && desk.desk && desk.desk.version !== undefined) {
      body.version = desk.desk.version;
    }
    var mark = gesture("window");
    return post("window", body).then(function (r) {
      settle(mark);
      if (r && r.ok === false) say((r.error || "that could not be saved") +
                                   (r.hint ? " — " + r.hint : ""), 8);
      return r;
    });
  }).catch(function () { return null; }).then(function (r) {
    windowWrites -= 1;
    if (r && r.ok !== false && r.windows) acceptDesk(r);
    return r;
  });
  return windowChain;
}

/* The one door every desk payload comes in through (#230): the stream's `desk` frame, the
   `/api/fleet` answer, the fifteen-second `/api/desk` and a window write's own answer. Three of those
   used to assign `desk.desk` outright, so an answer computed before a click could land after the
   frame that carried it and roll the page back -- `version` from 5 to 3, and the agent the operator
   had just left open again. The version only ever rises, so an older payload is simply dropped;
   an equal one is the same desk. */
/** @param {DeskAnswer} payload
 *  @returns {boolean} whether it was taken */
function acceptDesk(payload) {
  if (!payload || typeof payload !== "object") return false;
  var have = desk.desk ? desk.desk.version : undefined;
  if (payload.version !== undefined && have !== undefined &&
      Number(payload.version) < Number(have)) return false;
  var next = Object.assign({}, payload);
  delete next.ok;
  delete next.action;
  // An arrangement write still in flight: the page's own arrangement is newer than this one.
  if (arrangeWrites && desk.desk && desk.desk.arrangement) next.arrangement = desk.desk.arrangement;
  desk.desk = next;
  var win = next.windows && next.windows[W_NAME];
  if (win && !windowWrites) applyWindow(win);
  if (next.measure && next.measure[W_NAME]) goProbe();
  return true;
}

function rehome() {
  /* `/open` forwards every param but `t`, so the host's shell and ink ride along from here once. */
  var more = new URLSearchParams();
  if (PARAMS.get("shell")) more.set("shell", PARAMS.get("shell"));
  if (PARAMS.get("ink")) more.set("ink", PARAMS.get("ink"));
  var rest = more.toString();
  window.location.href = "/open?w=" + encodeURIComponent(W_NAME) + (rest ? "&" + rest : "");
}

/* There used to be a `held` map here: the agents the operator had acted on, kept on the glass by
   focus mode after they stopped needing anybody, because a reply otherwise dimmed the very pane it
   was typed into. *needs me* is a preset now (#234) -- one write of widths, which nothing takes back
   when an agent stops needing you -- so there is no filter left for a pane to fall out of, and
   nothing to hold it in. */

/* The desk's answer to a 403 (common.js calls this): collect a fresh run token through `/open`,
   but only once the stream has already died -- a single refused POST against a live stream is not
   a restarted server, and rehoming on one would throw away whatever was being typed. */
onAuthLost = function () { if (streamDead) rehome(); };

function age(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return seconds + "s";
  if (seconds < 5400) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

/* How old an agent's last event is, said one way everywhere it is said (#204).

   `age()` below stops at hours, so the same agent read `6d` in its chip and `160h` in its tab --
   two numbers for one fact, on one tile, three centimetres apart. `age()` still dates DURATIONS
   (how long an approval has waited, how old a poll is); `agentAge` dates the agent, and the chip,
   the rail's label, the strip and the agent rail all read the same formatter. */
function agentAge(seconds) { return ageChip(seconds).text; }

/* The age that rides inside the state chip. "done" is not information; "done · 2d" is -- and the
   bucket labels this replaced ("today", "> 2d") could not tell a run that ended a minute ago from
   one that ended at breakfast. Anything past a day is marked stale as well as dated, because a
   colour alone is not a signal on a bad monitor at arm's length. */
function ageChip(seconds) {
  if (seconds == null || seconds < 0) return { text: "", stale: false };
  if (seconds < 90) return { text: seconds + "s", stale: false };
  if (seconds < 5400) return { text: Math.floor(seconds / 60) + "m", stale: false };
  if (seconds < 86400) return { text: Math.floor(seconds / 3600) + "h", stale: false };
  return { text: Math.floor(seconds / 86400) + "d", stale: true };
}

/* --------------------------------------------------------------------------- drawing one tile */

function line(ev) {
  var d = ev.data || {};
  switch (ev.kind) {
    case "assistant_text": return d.text || "";
    case "tool_call": return (d.tool || "tool") + " " + JSON.stringify(d.arguments || {}).slice(0, 160);
    case "tool_result": return d.ok ? "ok" : (d.message || d.error || "failed");
    case "denied": return "refused: " + (d.message || "a tool it may not run");
    case "friction": return "stopped: " + (d.unblock || d.file || "");
    case "phase_changed": return (d.from || "?") + " → " + (d.to || "?");
    case "question_opened": return d.question || "";
    case "needs_approval": return "waiting for you: " + (d.summary || d.kind || "");
    case "approval_resolved": return (d.decision || "") + " by " + (d.by || "you");
    case "cost": return d.premium_requests + " premium requests";
    case "exited": return "exit " + d.exit_code;
    case "error": return "exit " + d.exit_code;
    case "started": return "launched: " + (d.prompt || "");
    case "said": return "typed into the console: " + (d.text || "");
    /* #131 and #132 put the *project's* changes on the same stream as the agent's, so the
       transcript is one narrative rather than two panes the operator has to interleave. */
    case "project.ticket_changed": return (d.key || "") + " is " + (d.status || "") +
                                          (d.assignee ? " · " + d.assignee : "");
    case "project.refresh_finished": return "refresh " + (d.status || "") + " " + (d.end || "");
    case "project.pr_merged": return "PR merged: " + (d.url || "");
    case "inbox.attached": return (d.attached ? "attached " : "already there: ") +
                                  (d.name || "") + " → " + (d.dir || "");
    case "pr_open": return d.url || "";
    case "artifact": return (d.artifact && d.artifact.path) || "";
    case "session_id": return "";
    /* #402: from the Copilot SDK docs, not yet measured from the CLI. */
    case "subagent_started": return "sub-agent " + (d.name || d.agent || "") + " started";
    case "subagent_ended": return "sub-agent " + (d.agent || "") + (d.ok
      ? " finished" + (d.tools == null ? "" : " (" + d.tools + " tools)")
      : " failed: " + (d.error || ""));
    default: return JSON.stringify(d).slice(0, 160);
  }
}

var SHOWN = {
  started: 1, assistant_text: 1, tool_call: 1, tool_result: 1, denied: 1, friction: 1,
  phase_changed: 1, question_opened: 1, needs_approval: 1, approval_resolved: 1,
  exited: 1, error: 1, pr_open: 1, artifact: 1, said: 1,
  "project.ticket_changed": 1, "project.refresh_finished": 1, "project.pr_merged": 1,
  "inbox.attached": 1, subagent_started: 1, subagent_ended: 1
};

function append(el, ev) {
  appendTo(el.querySelector(".transcript"), ev);
}

/* One renderer for both lists. The read-only pane draws the same lines from the same fold as the
   live tile, because a session that looked different when you came back to it would read as a
   different session (#174). */
function appendTo(list, ev) {
  if (!SHOWN[ev.kind]) return;
  var body = line(ev);
  if (!body) return;
  var li = document.createElement("li");
  setClass(li, ev.kind);
  var k = document.createElement("span");
  setClass(k, "k");
  text(k, ev.kind.replace(/_/g, " "));
  var v = document.createElement("span");
  setClass(v, "v");
  text(v, body);                                  // textContent, never markup: this is agent output
  li.appendChild(k);
  li.appendChild(v);
  var wasAtBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) <= 40;
  list.appendChild(li);
  while (list.children.length > 200) list.removeChild(list.firstChild);
  if (wasAtBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

/** @param {Row} row  @param {number} index  @returns {HTMLElement} */
function makeTile(row, index) {
  var el = /** @type {HTMLElement} */ (/** @type {HTMLTemplateElement} */ (
    document.getElementById("tile")).content.firstElementChild.cloneNode(true));
  text(el.querySelector(".n"), index + 1);
  var repoEl = el.querySelector(".repo");
  text(repoEl, row.repo);
  attr(repoEl, "title", row.repo);
  setData(el, "repo", row.repo);

  var list = el.querySelector(".transcript");
  var repoName = row.repo;
  list.addEventListener("scroll", function () {
    try {
      sessionStorage.setItem("fleet.scroll." + repoName, String(list.scrollTop));
    } catch (e) {}
  });

  el.querySelector(".repo").addEventListener("click", function () { openAgent(row.repo); });
  el.addEventListener("dblclick", function () { openAgent(row.repo); });
  // Clicking anywhere on a tile *selects* the project for every window on this server (#133 layout
  // B), which is what makes the left monitor drive the centre one. Blowing a tile up is still the
  // repo name or a double click: one gesture per meaning.
  el.addEventListener("click", function (/** @type {MouseEvent & {target: Element}} */ e) {
    // Clicking a tile selects the project for every window on this server -- which is what makes
    // the left monitor drive the centre one. Pressing Send, or clicking into the reply box, is not
    // that gesture: it re-pointed three other screens as a side effect of typing.
    if (e.target.closest("button, input, select, textarea, a, details, summary")) return;
    choose(row.repo);
  });

  /* Drag to reorder, from the header only. A tile that is draggable edge to edge cannot have its
     transcript text selected -- every attempt to copy an error message starts a drag instead --
     and it offers no affordance for the gesture. The header carries `draggable` and the grip
     says so (HIG *Drag and drop*). Tickets dropped from the board still land on the whole tile. */
  /* #217: pointer events, not HTML5 drag. The old gesture could not show the tile moving -- the
     browser drew its own translucent copy and the tile stayed where it was -- and on a touchpad
     it needed a press-and-hold nobody discovers. `setPointerCapture` keeps every move coming to
     this handle even when the pointer has left it, which is what makes the tile stay under the
     cursor instead of being dropped the moment it overtakes the hand.

     Tickets from the board and files from the desktop still arrive by HTML5 drag; they are drops
     *onto* a tile, which is a different gesture with a different source. */
  var head = el.querySelector(".head");
  bindDragToReorder(head, el, row.repo);

  /* #233: the rail's face. A press swaps it with the pane that was open -- the column's gesture,
     kept because it is the one the operator already has -- and a drag moves it along the row, by
     the same binder the head uses. The face is one button, so it IS the handle (#217's rule), and
     the click a real drag ends in is swallowed there. */
  /** @type {HTMLElement} */
  var face = el.querySelector(".pane-rail");
  /* #234: Shift opens it BESIDE the pane that has the keys, splitting that pane's width -- which is
     how two are open without a drag. `Shift+Enter` is the same press from the keyboard; it is taken
     on the key, because whether the click a button synthesises for `Enter` carries the Shift is the
     engine's business. */
  face.addEventListener("click", function (e) {
    if (e.shiftKey) openBeside(railTarget(row.repo));
    else openPane(railTarget(row.repo), false, true);
  });
  face.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    openBeside(railTarget(row.repo));
  });
  bindDragToReorder(face, el, row.repo);

  /* #234: this pane's right-hand gutter -- the line between it and the next pane on the glass. */
  bindGutter(el.querySelector(".gutter"), el);

  el.addEventListener("dragover", function (e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    toggle(el, "drop-target", true);
  });

  el.addEventListener("dragleave", function () {
    el.classList.remove("drop-target", "drop-before", "drop-after");
  });

  el.addEventListener("drop", function (e) {
    e.preventDefault();
    // Reorder is the pointer drag's (#217); what arrives here is a ticket or a file.
    el.classList.remove("drop-target", "drop-before", "drop-after");

    // Files first (#166): the tile has promised a copy on `dragover` since #98, and until now that
    // promise was empty -- the outline appeared and nothing happened.
    if ((e.dataTransfer.files && e.dataTransfer.files.length) ||
        Array.prototype.some.call(e.dataTransfer.items || [], function (i) { return i.kind === "file"; })) {
      filesFromDrop(e.dataTransfer).then(function (files) {
        if (files.length) scopeDrop(el, row.repo, files);
      });
      return;
    }

    var key = (e.dataTransfer.getData("application/x-agentdata-ticket") || e.dataTransfer.getData("text/plain") || "").trim();
    if (key) takeTicket(key, row.repo);
  });

  /* The dispatch card's own three controls (#164). `Enter` in the brief box starts; `Esc` cancels,
     the way `Esc` leaves every other thing on this page. */
  /* One Send for every answer typed (#165): N answers cost one turn, not N. */
  el.querySelector(".asks-send").addEventListener("click", function () {
    var answers = [];
    Array.prototype.forEach.call(el.querySelectorAll(".asks-list .ask"), function (li) {
      var value = li.querySelector(".ask-answer").value.trim();
      if (value) answers.push({ id: li.dataset.qid, answer: value });
    });
    if (!answers.length) {
      text(el.querySelector(".asks-note"), "pick a choice or type an answer first");
      return;
    }
    text(el.querySelector(".asks-note"), "");
    action(el, "answer", { repo: row.repo, answers: answers }).then(function (r) {
      /* #249: a question the server says it passed on is answered, and says so until the agent
         records it and the fold drops it -- the one signal the paper skins strike the question
         by. The ids come back from the server, never from what was typed. */
      var done = (r && r.ok !== false && r.answered) || [];
      Array.prototype.forEach.call(el.querySelectorAll(".asks-list .ask"), function (li) {
        if (done.indexOf(li.dataset.qid) >= 0) toggle(li, "is-answered", true);
      });
    });
  });

  // hide, refresh and the model -- the three the band had, on the head, from the one binder (#205).
  // A rail has no head to put them on; `h`, `r` and `m` reach it from the keyboard instead.
  bindTools(el, row.repo);

  el.querySelector(".scope-close").addEventListener("click", function () {
    hide(el.querySelector(".scope"), true);
  });
  el.querySelector(".scope-tell").addEventListener("click", function () {
    action(el, "send", { repo: row.repo, message:
      "New files are in the scope under .agent/in/; read scope.toon before continuing." });
  });


  /* #206: one control. The pill says which session this transcript is; the menu behind it holds
     everything that changes which session that is. The rows are fetched on the open rather than on
     every poll -- nobody is reading them until they ask for them. */
  el.querySelector(".spill").addEventListener("click", function () { toggleMenu(el, row.repo); });
  el.querySelector(".sm-live").addEventListener("click", function () {
    closeMenu(el);
    if (viewing(el)) backToLive(el);
  });
  el.querySelector(".sm-new").addEventListener("click", function () {
    closeMenu(el);
    newSession(el, row.repo);
  });
  el.querySelector(".sm-console").addEventListener("click", function () {
    closeMenu(el);
    openConsole(el, row);
  });
  el.querySelector(".ro-resume").addEventListener("click", function () { resumeHere(el, row.repo); });
  el.querySelector(".ro-back").addEventListener("click", function () { backToLive(el); });

  /* Every drag gesture has a keyboard equivalent, and the footer key map lists them all. */
  el.addEventListener("keydown", function (e) {
    if (!e.altKey) return;
    // #217: shifted, because Alt+arrows has moved a tile since #5 and a learned gesture is not
    // something to take away for a new one. Since the gutters (#234) the shifted pair moves this
    // pane's right-hand gutter, as a drag of it would; up and down went with `rows`, because a pane
    // is always the row's full height.
    if (e.shiftKey) {
      if (e.key === "ArrowRight") { stepGutter(el, 1); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { stepGutter(el, -1); e.preventDefault(); }
      return;
    }
    if (e.key === "ArrowLeft") { moveTile(row.repo, -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { moveTile(row.repo, 1); e.preventDefault(); }
    else if (e.key === "Home") { toggleTilePin(row.repo); e.preventDefault(); }
    // The double-click on this pane's right-hand gutter: the two beside it, evened out (#234).
    else if (e.key === "Enter") { evenGutter(el); e.preventDefault(); }
    // The strip, without a mouse. `[` and `]` walk it; `N` is a clean session beside this one.
    else if (e.key === "[") { stepMenu(el, row.repo, -1); e.preventDefault(); }
    else if (e.key === "]") { stepMenu(el, row.repo, 1); e.preventDefault(); }
    else if (e.key === "n" || e.key === "N") { newSession(el, row.repo); e.preventDefault(); }
  });

  var pinBtn = el.querySelector(".pintoggle");
  if (pinBtn) {
    pinBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTilePin(row.repo);
    });
  }

  /* #217: maximise. Minimise is the hide button, which is the same gesture under the name
     everybody already knows; this is the other half of the pair, and it is `openAgent` -- which
     the desk has always had and only ever offered as a double click or the repository name. */
  var maxBtn = el.querySelector(".maxtoggle");
  if (maxBtn) {
    maxBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      openAgent(row.repo);
    });
  }

  /** @type {HTMLElement} */
  var adoptBtn = el.querySelector(".adopt");
  if (adoptBtn) {
    adoptBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var what = adoptBtn.dataset.what === "release" ? "release" : "adopt";
      action(el, what, { repo: row.repo, pid: Number(adoptBtn.dataset.pid || 0) });
    });
  }

  /** @type {HTMLInputElement} */
  var say = el.querySelector(".say");
  /** @type {HTMLButtonElement} */
  var sendBtn = el.querySelector(".send");
  sendBtn.addEventListener("click", function () {
    // A console is typed into, not sent to: `send` would be a second agent in one working tree.
    var forcing = sendBtn.dataset.force === "1";
    action(el, el.dataset.console ? "say" : "send",
           { repo: row.repo, message: say.value, force: forcing })
      .then(function (r) {
        if (r && r.ok) { say.value = ""; disarmSend(sendBtn); return; }
        /* The budget refusal reaches the operator at last (#213). It was enforced in `send` and
           the desk called `send` with no `force` at all, so an over-budget agent was simply
           unreachable from the page and `ad-fleet send --force` in a terminal was the only door.
           A second, deliberate press spends one more turn -- the pattern Reset already had. */
        if (r && r.code === "budget_exceeded" && !forcing) {
          setData(sendBtn, "force", "1");
          text(sendBtn, "Send anyway");
          attr(sendBtn, "title", "it is over its budget — press again to spend one more turn");
          return;
        }
        disarmSend(sendBtn);
      });
  });
  say.addEventListener("keydown", function (e) {
    if (e.key === "Enter") /** @type {HTMLElement} */ (el.querySelector(".send")).click();
  });
  el.querySelector(".start").addEventListener("click", function () {
    action(el, "start", { repo: row.repo, ticket: say.value.trim() || null });
  });
  el.querySelector(".stop").addEventListener("click", function () {
    action(el, "stop", { repo: row.repo });
  });

  /* Reset is stop-then-resume, which is what the operator was previously expected to spell as two
     commands in a terminal they had to go and find. `restart` is bounded by `fleet.max_restarts`
     and refuses past it -- correctly, since an agent that has died twice the same way will die a
     third time -- so the refusal is shown and the button becomes the second, deliberate press that
     spends the extra turn. Two clicks, never a silent `force`. */
  /** @type {HTMLButtonElement} */
  var resetBtn = el.querySelector(".reset");
  resetBtn.addEventListener("click", function () {
    var forcing = resetBtn.dataset.force === "1";
    action(el, "reset", { repo: row.repo, force: forcing }).then(function (r) {
      if (r && !r.ok && !forcing && /--force|worth another turn/.test(r.hint || "")) {
        setData(resetBtn, "force", "1");
        text(resetBtn, "Reset anyway");
        attr(resetBtn, "title", "it has already been restarted this many times — press again to spend one more");
        return;
      }
      setData(resetBtn, "force", "");
      text(resetBtn, "Reset");
      attr(resetBtn, "title", "unblock it: end the stuck process and resume the same session");
    });
  });
  el.querySelector(".approve").addEventListener("click", function () {
    action(el, "approve", { id: el.dataset.approval,
                            reason: /** @type {HTMLInputElement} */ (el.querySelector(".reason")).value });
  });
  el.querySelector(".deny").addEventListener("click", function () {
    var reason = /** @type {HTMLInputElement} */ (el.querySelector(".reason")).value.trim();
    if (!reason) { return fail(el, "a denial needs a reason: the agent quotes it and then stops"); }
    action(el, "deny", { id: el.dataset.approval, reason: reason });
  });
  return el;
}

function disarmSend(button) {
  setData(button, "force", "");
  text(button, "Send");
  attr(button, "title", "");
}

function fail(el, message) {
  var p = el.querySelector(".err");
  text(p, message);
  hide(p, !message);
}

function action(el, what, body) {
  fail(el, "");
  var mark = gesture("action:" + what);
  return post(what, body).then(function (r) {
    if (!r.ok) fail(el, r.error + (r.hint ? " — " + r.hint : ""));
    /* The row came back with the answer (#219). A `send` used to cost two round trips -- the act,
       then a whole `/api/fleet` to find out what it did -- and the second one carried every tile
       on the desk so that one of them could be redrawn. An action that did not name a row (or an
       older server that does not send one) still falls back to the snapshot. */
    if (r.row) { patchRow(r.row); place(); }
    else refresh();
    settle(mark);
    return r;
  }).catch(function (e) { fail(el, String(e)); });
}

/* ------------------------------------------------------------------- the question card (#165)

   The agent's open questions, as records: choices as buttons, a box for anything else, one Send.
   Answering used to be a free-text reply the agent had no way to tie to what it asked, and which
   did not unblock it -- `open_questions` persisted until `--clear-questions`, which no skill ran on
   resume, so the next bootstrap stopped on the same block. */

function drawAsks(el, row) {
  var card = el.querySelector(".asks");
  var list = card.querySelector(".asks-list");
  var open = (row.asked || []).filter(function (q) { return q.blocking !== false; });
  var assumed = row.assumed || [];

  if (!open.length) {
    hide(card, true);
  } else {
    hide(card, false);
    text(card.querySelector(".asks-n"), open.length === 1 ? "1 question" : open.length + " questions");
    // Redraw only when the set changed: the operator may be mid-sentence in one of these boxes,
    // and a refresh every few seconds that threw the typing away would make the card unusable.
    var signature = open.map(function (q) { return q.id + ":" + q.q; }).join("|");
    if (list.dataset.signature !== signature) {
      setData(list, "signature", signature);
      var pattern = list.querySelector(".ask");
      while (list.children.length > 1) list.removeChild(list.lastChild);
      open.forEach(function (q) {
        var li = pattern.cloneNode(true);
        hide(li, false);
        setData(li, "qid", q.id || "");
        text(li.querySelector(".ask-q"), q.q || "");
        var picked = li.querySelector(".ask-answer");
        picked.placeholder = q.want === "file" ? "a path, or drop the file on this tile" : "your answer";
        var choices = li.querySelector(".ask-choices");
        (q.choices || []).forEach(function (choice) {
          var b = document.createElement("button");
          b.type = "button";
          setClass(b, "ask-choice");
          text(b, choice + (choice === q.default ? " (default)" : ""));
          attr(b, "aria-pressed", "false");
          b.addEventListener("click", function () {
            picked.value = choice;
            Array.prototype.forEach.call(choices.children, function (other) {
              attr(other, "aria-pressed", String(other === b));
            });
          });
          choices.appendChild(b);
        });
        list.appendChild(li);
      });
    }
  }

  var strip = el.querySelector(".assumed");
  if (!assumed.length) {
    hide(strip, true);
  } else {
    hide(strip, false);
    var shape = strip.querySelector(".assumption");
    while (strip.children.length > 1) strip.removeChild(strip.lastChild);
    assumed.forEach(function (q) {
      var li = shape.cloneNode(true);
      hide(li, false);
      text(li.querySelector(".assumption-what"), "assumed: " + (q.assume || q.default || q.q));
      li.querySelector(".overturn").addEventListener("click", function () {
        var say = el.querySelector(".say");
        say.value = "That assumption is wrong: " + (q.assume || q.q) + ". ";
        say.focus();
      });
      strip.appendChild(li);
    });
  }
}

/* What it edited against what it was given (#168). Advice to the model and a report to the human:
   nothing here refused an edit, and an agent that went outside the scope was probably right to --
   the operator simply wants to know. */
function drawScopeReport(el, row) {
  var strip = el.querySelector(".scopereport");
  var card = row.scope_report || {};
  if (!card.edited) { hide(strip, true); return; }
  hide(strip, false);
  var said = "edited " + card.edited;
  if (card.outside && card.outside.length) {
    said += " · " + card.outside.length + " outside the scope you gave it";
    setClass(strip, "scopereport outside");
    attr(strip, "title", card.outside.join("\n"));
  } else {
    said += " · all inside the scope you gave it";
    setClass(strip, "scopereport");
    attr(strip, "title", "");
  }
  text(strip, said);
}

/* The project's accent, on the tile's LEFT edge -- which project, never what state (#150).
   One owner (#215): `drawTile` painted `borderLeftColor` and the `theme` SSE handler painted
   the TOP one, an edge no rule gives a width to. So a palette changed in a terminal or on the
   settings page painted an invisible stripe and left the visible one stale until the next
   `/api/fleet`. Both call this now. */
function paintAccent(el, accent) {
  if (!el || !accent) return;
  style(el, "border-left-color", accent);
}

/* -------------------------------------------------------- #218: the shape of the hour, drawn */

/* The last hour, oldest on the left: one point a minute, its height the share of the busiest
   minute, and a tick through every minute that stopped for a person -- because "it asked me
   something" is not a quantity.

   Nothing is drawn that the row does not carry and nothing is drawn that the sentence does not
   say: the `aria-label` is the same hour in words, which is what makes this assertable and what
   makes it reach somebody who cannot see it.

   #257: there is no canvas. The trace is data on the page, written once here and read twice. The
   element carries the series (`data-ink-series`, heights 0-1, and `data-ink-ticks`, the minutes
   that needed somebody), which is what the ink layer draws in the pane's lane when this shell
   draws ink (docs/desk-ink.md §The page's own drawing). And its own SVG -- a polyline and a path of
   ticks, coloured by the stylesheet -- is the plain look every other shell shows, so a palette that
   changes repaints it with no script at all. Every write goes through `attr`, so a row that did not
   change writes nothing. */
var TRACE_H = 18;               // the viewBox's height: the trace's own CSS height, in px

function traceHeights(tr) {
  var counts = tr.n || [];
  var peak = tr.peak || 1;
  var out = [];
  for (var i = 0; i < counts.length; i++) {
    var n = counts[i] || 0;
    // A minute with something in it is never flat: a pixel above the floor is "it was awake".
    out.push(n > 0 ? Math.max(1 / (TRACE_H - 2), Math.min(1, n / peak)) : 0);
  }
  return out;
}

function drawTrace(el, row) {
  if (!el) return;
  var tr = row.trace || {};
  var needs = tr.needs || [];
  var says = tr.says || "nothing in the last hour";
  attr(el, "aria-label", says);
  // An SVG's tooltip is its <title> child, not a `title` attribute as the canvas's was.
  text(el.querySelector("title"), says);

  var heights = traceHeights(tr);
  var any = heights.some(function (h) { return h > 0; });
  var ticks = [];
  for (var i = 0; i < heights.length; i++) if (needs[i]) ticks.push(i);
  attr(el, "viewBox", "0 0 " + Math.max(1, heights.length) + " " + TRACE_H);
  attr(el, "data-ink-series", any ? heights.map(function (h) {
    return h ? String(Math.round(h * 1000) / 1000) : "0";
  }).join(" ") : "");
  attr(el, "data-ink-ticks", any ? ticks.join(" ") : "");
  /* The same hour as counts, for a skin that plots it on its own paper (#253, the graph paper): the
     peak, then a minute's count each, `!` on a minute that stopped for a person. */
  setData(el, "trace", (tr.peak || 1) + "|" + (tr.n || []).map(function (n, j) {
    return n + (needs[j] ? "!" : "");
  }).join(" "));

  // The plain look: the same numbers, in the SVG's own units (a minute wide, a pixel tall).
  var line = el.querySelector(".tr-line");
  var marks = el.querySelector(".tr-ticks");
  attr(line, "points", any ? heights.map(function (h, j) {
    var y = (TRACE_H - 1.5) - (h ? Math.max(1, h * (TRACE_H - 3)) : 0);
    return (j + 0.5) + "," + (Math.round(y * 100) / 100);
  }).join(" ") : "");
  attr(marks, "d", any ? ticks.map(function (j) { return "M" + (j + 0.5) + " " + TRACE_H + "V0"; }).join("") : "");
}

/* #218's ground -- the glass skin's three blobs, drifting a pixel a second -- is the ink layer's now
   (#257): it reads the stylesheet's gradients and draws them in its `ground` slot where this shell
   draws ink, and every other shell shows the stylesheet's own gradients, still. Nothing here draws
   it, and nothing here needs to know which skin has one. */

/* The two classes `drawTile` owns on a tile, and nothing else (#215, found by #220's demo).

   It used to rebuild the whole `class` attribute from `tile state-…`, which dropped every class
   somebody else owns -- `is-selected`, `is-hidden`, `is-pinned`, `size-2`, `needs-human` -- and
   `place()` put them straight back on the next line. Two writers, two writes, twenty times a
   redraw, and `draw(el, row)` twice with the same row was never the no-op the contract claims.
   The classes this function does not own are kept by construction rather than by being
   remembered. */
var TILE_OWNED = /^(tile|state-[A-Za-z_]+)$/;

/* Rebuild the classes one draw function owns, keeping every class it does not.

   What made it a rule rather than a habit: the column's band (#203, retired by #233) owned three
   classes and rewrote the attribute that also holds `is-dragging`, and `place()` runs about two
   and a half times a second. A draw landing in the middle of a drag took `is-dragging` off the
   band -- with it the `pointer-events: none` that makes `elementFromPoint` answer with what is
   *underneath* the thing being dragged -- so the gesture carried on finding only itself and no
   drop target ever lit. On a fast machine the drag finishes between two draws and it never
   happens. */
function setOwned(el, owned, wanted) {
  var kept = Array.prototype.filter.call(el.classList, function (name) {
    return !owned.test(name);
  });
  setClass(el, wanted.concat(kept).join(" "));
}

function setTileState(el, state) {
  setOwned(el, TILE_OWNED, ["tile", "state-" + state]);
}

/* The state a pane shows, which is not always the fold's. The server decides which agents are
   quiet enough to be called unsupervised (it is the only side that knows whether a process holds
   the checkout), and it sends the sentence ONLY for those -- so a pane that says "needs you" never
   also says "nothing is supervised". One function, because the chip and the rail both say it. */
function shownState(row) {
  var cold = row.supervised === false && !!row.not_supervised_sentence;
  return cold ? "idle" : (row.state || "");
}

/* #233: what this pane's width lets it show. A tier not written yet reads as a rail, because that
   is what every pane is until `place()` opens it: a pane is made 48px wide, and the observer's
   first report -- before anything is painted -- writes its real tier and draws it again at that
   width. A pane that is never laid out (hidden from the start) is never reported, and draws the
   rest of itself the frame it is shown. */
/** @param {HTMLElement} el  @returns {{wide: boolean, full: boolean}} */
function paneShows(el) {
  var tier = el.dataset.tier || "rail";
  return { wide: tier !== "rail", full: tier === "full" };
}

function drawTile(el, row, approvals) {
  /* Three things have to agree here or the tile lies: the chip, the sentence under it, and the
     age -- `shownState` is where the first two are decided. */
  var isSupervised = row.supervised !== false;
  var cold = !isSupervised && !!row.not_supervised_sentence;
  var displayState = shownState(row);
  /* The draw skips what this tier does not show (plan-panes §The pane): a rail paints no trace,
     no cells and no session menu, and a compact pane none of the three either. What every tier
     needs is drawn whatever the width -- above all `needs-human`, which `isHidden` reads to keep a
     demand on the glass. A change of tier draws the pane again, so what was skipped arrives. */
  var shows = paneShows(el);
  setTileState(el, displayState);
  paintAccent(el, row.accent);
  if (shows.full) drawTrace(el.querySelector(".trace"), row);
  // `needs-human` is the class *needs me* widens by (#234) and `isHidden` keeps on the glass, and it
  // comes from #94's fold rather than from anything this page works out for itself: the chip, the
  // toast and the preset must agree.
  toggle(el, "needs-human", !!row.needs_human);
  // Finished, in the fold's own word (#253). The chip cannot say it: the fold calls an agent done
  // only once nothing supervises it, and `shownState` draws every quiet unsupervised agent as
  // idle. So a paper skin's green check has this to key on, and it is the fold's, not the page's.
  toggle(el, "is-done", row.state === "done");
  // A rail's one stop for the keyboard is its face; the pane around it is not a second one.
  tabbable(el, shows.wide ? 0 : -1);
  // Every state carries its own age, in the chip, because a verdict with no date is the bug.
  var modelBtn = el.querySelector(".modeltoggle .bm-name");
  if (modelBtn) text(modelBtn, shortModel(row.actual || row.model));
  var modelHost = el.querySelector(".modeltoggle");
  if (modelHost) attr(modelHost, "title", modelTitle(row));
  var ac = ageChip(row.last_event_age_s);
  var chip = el.querySelector(".chip");
  setClass(chip, "chip " + displayState + (ac.stale ? " stale" : ""));
  // Two spans from the template, written rather than rebuilt: the chip was torn down and cloned
  // again on every draw, several times a second while an agent talks.
  text(chip.querySelector(".chipword"), displayState.replace(/_/g, " "));
  text(chip.querySelector(".chipage"), ac.text ? " · " + ac.text : "");
  attr(chip, "title", "state from the fold" + (ac.text ? ", last event " + ac.text + " ago" : ""));
  text(el.querySelector(".ticket"), row.ticket || row.jira_project || "");
  drawOldSession(el, row);

  text(el.querySelector(".why"), cold ? row.not_supervised_sentence : (row.why || ""));

  /* A session in this checkout that the fleet did not start (#2). Two states, never both: one it
     could take on, and one it already has. The `how` is shown rather than hidden because "we found
     the process and it is in that folder" and "that folder is being written to and a Copilot is
     running somewhere" are different claims, and the operator should be told which they have. */
  var outside = el.querySelector(".outside");
  if (outside) {
    var offer = row.adoptable;
    var adoptBtn = outside.querySelector(".adopt");
    if (row.external) {
      hide(outside, false);
      toggle(outside, "mine", true);
      text(outside.querySelector(".outsidewhy"),
           "a session outside the fleet is driving this repo" +
           (row.pid ? " (pid " + row.pid + ")" : "") +
           (row.external_how ? " — " + row.external_how : ""));
      text(adoptBtn, "hand it back");
      setData(adoptBtn, "what", "release");
      attr(adoptBtn, "title", "stop treating that session as this repo's current one");
    } else if (offer) {
      hide(outside, false);
      toggle(outside, "mine", false);
      text(outside.querySelector(".outsidewhy"),
           "something is working in this checkout that the fleet did not start" +
           (offer.pid ? " (pid " + offer.pid + ")" : "") +
           " — last wrote " + age(offer.active_age_s) + " ago, " + offer.how);
      text(adoptBtn, "adopt it");
      setData(adoptBtn, "what", "adopt");
      setData(adoptBtn, "pid", String(offer.pid || 0));
      attr(adoptBtn, "title", "make that session this repo's current one, instead of the last run the fleet started");
    } else {
      hide(outside, true);
    }
  }
  // An adopted session has no pipe to its stdin, so the controls that would write to it say so
  // rather than being offered and silently doing nothing.
  // A console the fleet opened holds the tile: the reply box types into it and the tab raises it.
  setData(el, "console", row.console ? String(row.console.pid || 0) : "");
  ["send", "start"].forEach(function (cls) {
    var btn = el.querySelector("." + cls);
    if (!btn) return;
    disable(btn, !!row.external);
    attr(btn, "title", row.external ? "type in that window — this session is not the fleet's to drive" : "");
  });

  // Which run this transcript belongs to. Without it, a two-day-old run reads as live.
  var run = row.run || {};
  // Which session the live tile is on, so the switcher can leave it out of *earlier* rather than
  // offering the operator the one they are already looking at (#174).
  setData(el, "session", run.session || "");
  var runline = el.querySelector(".runline");
  if (runline) {
    var bits = [];
    if (run.n) bits.push("run " + run.n);
    if (run.started) bits.push("started " + String(run.started).slice(11, 16));
    if (run.resumed) bits.push("resumed");
    if (run.session) {
      var sessLabel = run.session_title ? run.session_title : "session " + String(run.session).slice(0, 8);
      bits.push(sessLabel);
    }
    if (run.events_n) bits.push(run.events_n + " events");
    // The era, last, because it is the qualifier: which run, then whether it is still this one.
    if (!run.n) bits = ["no run yet"];
    else if (isSupervised) bits.push("live");
    else if (!run.since_start) bits.push("before this session");
    else bits.push("ended");
    text(runline, bits.join(" · "));
    attr(runline, "title", (run.session ? "session " + run.session + " (click to copy)\n" : "") + bits.join(" · "));
    toggle(runline, "cold", cold);
    if (run.session) {
      runline.onclick = function() {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(run.session);
        }
      };
      runline.style.cursor = "pointer";
    }
  }

  if (shows.full) drawSessionPill(el, row);

  /* The two cards that ask the operator something are on a compact pane as well as a full one:
     answering from a narrow pane is the point of it. A rail carries neither -- it is red, and the
     press that widens it is the way to them. */
  if (shows.wide) {
    var mine = approvals.filter(function (a) { return a.repo === row.repo; })[0];
    var card = el.querySelector(".approval");
    hide(card, !mine);
    if (mine) {
      setData(el, "approval", mine.id);
      text(el.querySelector(".kind"), mine.kind + "  ·  " + age(mine.waiting_s));
      text(el.querySelector(".summary"), mine.summary || "");
      text(el.querySelector(".payload"), JSON.stringify(mine.payload || {}, null, 2));
    }
    drawAsks(el, row);
  }
  if (shows.full) {
    drawScopeReport(el, row);
    drawCells(el, row.polls || {}, row);
  }
}

/* ------------------------------------------------------------------------- the switcher (#174) */

/* The earlier-run rows were text with no handler, and the only session-changing gesture in the
   whole page was *adopt* -- which then disabled Send. So a session you had finished with was a
   thing you could read about and not open, and *I started it in a terminal yesterday* had no
   answer at all.

   The strip is a tab view: the main tab is this checkout's live session, the tabs beside it are the
   project's other checkouts (#175 fills them in; before it, `siblings` is empty and the strip is
   one tab and *earlier*), then *earlier (n)* and *+ new*. Reading a session is a GET and nothing
   else -- choosing one must never spawn an agent -- and making one live again is a second,
   deliberate press, the way *Reset anyway* is. */

function viewing(el) {
  return el.dataset.viewing || "";
}

/* One sentence, in the words the page has: how it ended and when. The *refusal* to resume is the
   server's own sentence, never this one -- a second opinion about why something was refused is how
   an operator ends up with two explanations of one rule. */
function endedSentence(data) {
  var state = data.state || "ended";
  var when = whenIso(data.at);
  return "this session ended " + state + (when ? " · " + when : "");
}

function whenIso(ts) {
  if (!ts) return "";
  var t = new Date(ts).getTime();
  if (isNaN(t)) return "";
  return age(Math.max(0, Math.round((Date.now() - t) / 1000))) + " ago";
}

function drawSessionPill(el, row) {
  var pill = el.querySelector(".spill");
  if (!pill) return;
  var open = viewing(el);
  var run = row.run || {};

  /* One line, saying which session this transcript is. The run line under it still says which RUN,
     because those are two facts and the operator asked for neither of them twice. */
  var bits;
  if (open) bits = ["earlier session", el.dataset.endedState || "ended", el.dataset.endedWhen || ""];
  else bits = [el.dataset.console ? "console" : "session", row.state || "",
               row.last_event_age_s >= 0 ? agentAge(row.last_event_age_s) : ""];
  text(pill, bits.filter(Boolean).join(" · "));
  attr(pill, "title", open ? "reading an earlier session — the menu goes back to the live one"
                    : (run.session ? "session " + run.session : "this checkout's live session"));
  toggle(pill, "is-reading", !!open);

  text(el.querySelector(".sm-console"), row.console ? "show console" : "open in a console");

  var n = row.sessions_n || 0;
  var label = el.querySelector(".sm-earlier-label");
  hide(label, !n);
  text(label, "earlier (" + n + ")");

  // This session's own earlier runs, folded under it -- the inert list that used to sit below the
  // transcript as a second, adjacent *earlier* with different behaviour.
  drawRuns(el.querySelector(".live-runs"), runsFor(row, el.dataset.session || ""));

  // Sibling checkouts of the same project (#175). Empty until that slice lands, which is why the
  // menu has to read as finished with none of them rather than as a row of missing things.
  var sibs = row.siblings || [];
  var sibList = el.querySelector(".sib-list");
  var sibPattern = sibList.querySelector(".sib-row");
  hide(el.querySelector(".sm-sibs-label"), !sibs.length);
  while (sibList.children.length > 1) sibList.removeChild(sibList.lastChild);
  sibs.forEach(function (sib) {
    var li = sibPattern.cloneNode(true);
    hide(li, false);
    var button = li.querySelector(".sib-open");
    text(button, [sib.branch || sib.repo, sib.state, sib.age].filter(Boolean).join(" · "));
    attr(button, "title", "the same project, checked out at " + (sib.path || sib.repo));
    button.addEventListener("click", function () { closeMenu(el); openAgent(sib.repo); });
    sibList.appendChild(li);
  });
}

/* The runs of one session, newest last, as plain rows. A run is a transcript boundary, not a thing
   to open: opening one is opening its session, which is the row above it. */
function runsFor(row, session) {
  return (row.earlier || []).filter(function (r) {
    return !session || !r.session || r.session === session;
  });
}

function drawRuns(list, runs) {
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  hide(list, !runs.length);
  runs.forEach(function (r) {
    var li = document.createElement("li");
    text(li, "run " + r.n + " · " + (r.ticket ? r.ticket + " · " : "") + r.state +
             " (" + (r.started ? String(r.started).slice(11, 16) : "") +
             (r.ended ? "–" + String(r.ended).slice(11, 16) : "") + ")");
    list.appendChild(li);
  });
}

/* The menu: open, closed, and stepped through without a mouse. */
function menuOpen(el) {
  var menu = el.querySelector(".smenu");
  return !!menu && !menu.hidden;
}

function closeMenu(el) {
  var menu = el.querySelector(".smenu");
  if (!menu || menu.hidden) return false;
  hide(menu, true);
  attr(el.querySelector(".spill"), "aria-expanded", "false");
  return true;
}

function closeMenus() {
  var was = false;
  tiles.forEach(function (entry) { if (closeMenu(entry.el)) was = true; });
  return was;
}

function toggleMenu(el, repo) {
  if (menuOpen(el)) return closeMenu(el);
  closeMenus();
  var menu = el.querySelector(".smenu");
  hide(menu, false);
  attr(el.querySelector(".spill"), "aria-expanded", "true");
  loadSessions(el, repo);
  return true;
}

/* The rows on the open, not on every poll: a disk read and a fold nobody is reading until asked. */
function loadSessions(el, repo) {
  var list = el.querySelector(".sessions");
  fetch(q("/api/sessions", { repo: repo })).then(function (r) { return r.json(); })
    .then(function (data) {
      var pattern = list.querySelector(".session-row");
      while (list.children.length > 1) list.removeChild(list.lastChild);
      var rows = (data && data.sessions) || [];
      var current = (el.dataset.session || "");
      var entry = tiles.get(repo);
      var row = (entry && entry.row) || {};
      rows.filter(function (r) { return r.id !== current; }).forEach(function (r) {
        var li = pattern.cloneNode(true);
        hide(li, false);
        text(li.querySelector(".ss-title"), r.title || r.ticket || r.id.slice(0, 8));
        text(li.querySelector(".ss-chip"), r.ended || "");
        text(li.querySelector(".ss-when"), whenIso(r.last_seen));
        text(li.querySelector(".ss-cost"), r.cost ? Number(r.cost).toFixed(2) + " premium" : "");
        var button = li.querySelector(".ss-open");
        attr(button, "title",
             (el.dataset.console ? "the console still owns this; close it first — " : "")
             + "session " + r.id
             + ((r.sources || []).join(" → ") ? " · " + r.sources.join(" → ") : ""));
        button.addEventListener("click", function () { closeMenu(el); showSession(el, repo, r); });
        // Its runs, under it. One *earlier*, not two adjacent ones with different behaviour.
        drawRuns(li.querySelector(".ss-runs"), runsFor(row, r.id));
        list.appendChild(li);
      });
      if (!rows.length) {
        var empty = pattern.cloneNode(true);
        hide(empty, false);
        text(empty.querySelector(".ss-title"), "no earlier sessions in this checkout");
        disable(empty.querySelector(".ss-open"), true);
        list.appendChild(empty);
      }
    });
}

/* Read-only, from history. The live transcript is hidden rather than replaced, so it keeps filling
   behind this and going back is instant and whole rather than a reload with a hole in it. */
function showSession(el, repo, session) {
  fetch(q("/api/transcript", { repo: repo, session: session.id }))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data || !data.ok) return;
      setData(el, "viewing", session.id);
      var history = el.querySelector(".history");
      while (history.firstChild) history.removeChild(history.firstChild);
      (data.events || []).forEach(function (ev) { appendTo(history, ev); });
      hide(el.querySelector(".transcript"), true);
      hide(history, false);
      closeMenu(el);
      // What the pill says while this is open: how it ended, and when.
      setData(el, "endedState", (data && data.state) || "ended");
      setData(el, "endedWhen", whenIso(data && data.at));
      var pane = el.querySelector(".readonly");
      hide(pane, false);
      text(el.querySelector(".ro-what"),
           (session.title ? session.title + " — " : "") + endedSentence(data));
      var resume = el.querySelector(".ro-resume");
      text(resume, "Resume here");
      setData(resume, "armed", "");
      // Exact, not guessed (#191): said while this checkout's console is alive, not for every
      // session the store happens to know.
      text(el.querySelector(".ro-note"),
           el.dataset.console ? "the console still owns this — close it, then resume" : "");
      hide(el.querySelector(".row.bottom"), true);
      var entry = tiles.get(repo);
      if (entry && entry.row) drawSessionPill(el, entry.row);
    });
}

/* `Alt+[` and `Alt+]` walk the menu, opening it if it is shut. The items are real buttons in
   document order, so stepping is moving the keyboard to the next one -- there is no second model
   of "which item is selected" that could disagree with what is on the glass. */
function stepMenu(el, repo, dir) {
  if (!menuOpen(el)) {
    // Opening IS the first move: the keyboard lands on *this session*, and the next press walks.
    toggleMenu(el, repo);
    var first = el.querySelector(".smenu [role='menuitem']");
    if (first) first.focus();
    return;
  }
  var items = [].slice.call(el.querySelectorAll(".smenu [role='menuitem']"))
                 .filter(function (b) { return !b.disabled && b.offsetParent !== null; });
  if (!items.length) return;
  var here = items.indexOf(document.activeElement);
  var at = here < 0 ? (dir > 0 ? 0 : items.length - 1)
                    : (here + dir + items.length) % items.length;
  items[at].focus();
}

function backToLive(el) {
  setData(el, "viewing", "");
  hide(el.querySelector(".history"), true);
  hide(el.querySelector(".transcript"), false);
  hide(el.querySelector(".readonly"), true);
  hide(el.querySelector(".row.bottom"), false);
  var entry = tiles.get(el.dataset.repo);
  if (entry && entry.row) drawSessionPill(el, entry.row);
}

/* Making an earlier session the live one: it runs, or it is the supervisor's own refusal with the
   supervisor's own hint and a button that has become a second, deliberate press. */
function resumeHere(el, repo) {
  var button = el.querySelector(".ro-resume");
  var note = el.querySelector(".ro-note");
  var armed = button.dataset.armed === "1";
  post("start", { repo: repo, resume: viewing(el), force: armed }).then(function (r) {
    if (r && r.ok) {
      setData(button, "armed", "");
      backToLive(el);
      refresh();
      return;
    }
    text(note, [r && r.error, r && r.hint].filter(Boolean).join(" — "));
    // Both refusals a resume meets take a second press: something holds the checkout, or it is
    // mid-ticket on this session's own ticket (#191, what a closed console leaves). Never silent.
    if (r && (r.code === "live_agent" || r.code === "mid_ticket")) {
      setData(button, "armed", "1");
      text(button, r.code === "live_agent" ? "Stop and resume" : "Resume anyway");
    }
  });
}

/* One button, three verbs (#189/#190/#191): raise the console this tile has, continue this tile's
   session in one, or open a fresh one. Refusals land in the supervisor's own words. */
function openConsole(el, row) {
  if (el.dataset.console) return action(el, "focus", { repo: row.repo });
  var body = { repo: row.repo };
  if (row.ticket) body.ticket = row.ticket;
  if (el.dataset.session) body.resume = el.dataset.session;
  return action(el, "console", body).then(function (r) { if (r && r.ok) refresh(); return r; });
}

function newSession(el, repo) {
  var note = el.querySelector(".ro-note");
  post("start", { repo: repo, "new": true }).then(function (r) {
    if (r && r.ok) { backToLive(el); refresh(); return; }
    var said = [r && r.error, r && r.hint].filter(Boolean).join(" — ");
    if (!el.querySelector(".readonly").hidden) text(note, said);
    else { text(el.querySelector(".err"), said); hide(el.querySelector(".err"), false); }
  });
}

/* ------------------------------------------------------------------------------- the whole page */

function checkAway(prevSeen) {
  if (!prevSeen || awayShown) return;
  awayShown = true;
  fetch(q("/api/notifications", { limit: 50 })).then(function (r) {
    return r.json();
  }).then(function (data) {
    if (!data.ok || !data.notifications) return;
    var seenTime = new Date(prevSeen).getTime();
    if (isNaN(seenTime)) return;

    var byRepo = new Map();
    data.notifications.forEach(function (n) {
      if (!n.at || !n.repo) return;
      var nTime = new Date(n.at).getTime();
      if (nTime > seenTime) {
        byRepo.set(n.repo, n);
      }
    });

    var strip = document.getElementById("away-strip");
    var list = document.getElementById("away-lines");
    if (!strip || !list || byRepo.size === 0) return;

    while (list.firstChild) list.removeChild(list.firstChild);
    byRepo.forEach(function (item) {
      var li = document.createElement("li");
      setClass(li, "away-line");
      var repoSpan = document.createElement("span");
      setClass(repoSpan, "repo");
      text(repoSpan, item.repo + ":");
      var descSpan = document.createElement("span");
      setClass(descSpan, "desc");
      text(descSpan, item.body || item.title || item.state);
      var whenSpan = document.createElement("span");
      setClass(whenSpan, "when");
      text(whenSpan, " · " + (item.at ? String(item.at).slice(11, 19) : ""));
      li.appendChild(repoSpan);
      li.appendChild(descSpan);
      li.appendChild(whenSpan);
      li.addEventListener("click", function () {
        if (tiles.has(item.repo)) openAgent(item.repo);
      });
      list.appendChild(li);
    });
    hide(strip, false);
  }).catch(function () {});
}

var dismissBtn = document.getElementById("dismiss-away");
if (dismissBtn) {
  dismissBtn.addEventListener("click", function () {
    var strip = document.getElementById("away-strip");
    if (strip) hide(strip, true);
  });
}

/** @param {WindowRecord} win */
function applyWindow(win) {
  if (!win) return;
  if (!appliedInitialWindow) {
    appliedInitialWindow = true;
    if (win.seen) {
      checkAway(win.seen);
    }
    saveWindow({ seen: new Date().toISOString() });
  }
  /* What is open is `open` and nothing else (#230, #232). The grid's `zoomed` was a second field
     for the same fact, and the two disagreeing inside one record is what snapped a click back to
     the agent before it; the record no longer has one. */
  if (win.open !== undefined && win.open !== openTile) {
    openTile = String(win.open || "");
  }
  /* The widths are the record's too, including none (#234). `focus` and `held` are not read: the
     needs-only filter they served is the *needs me* preset now, one write of widths. */
  myWidths = ownWidths(win.widths);
  if (win.section && win.section !== lastSection) {
    section(win.section, true, true);
  }
  if (win.read && typeof win.read === "object") {
    Object.assign(readCursors, win.read);
  }
}

/* `ad-fleet probe --open pycharm` (#247). Nothing outside the IDE can point PyCharm's tool window
   or VS Code's view at a URL, so the CLI asks the server to have this window measure, the ask
   arrives with the desk, and the desk already inside the IDE goes to `/probe` by itself, carrying
   its own query string so the probe can bring it back. The desk loads no three.js: the probe page
   does, and only while it measures.

   The ask is the server's, in memory, and TAKEN rather than read (#261): the window goes only when
   `measure {take}` answers `go`, so a second desk under the same name, a snapshot drawn on reload
   or an ask from yesterday (the server drops them after ten minutes) goes nowhere. And not while
   the operator is typing: half a reply in a tile, or a brief in the dispatch card, would be lost to
   the navigation, so the desk says what it is waiting for and goes once those boxes are empty. */
var probing = false;
var probeWaiting = 0;

function unsentText() {
  /** @type {NodeListOf<HTMLInputElement | HTMLTextAreaElement>} */
  var boxes = document.querySelectorAll(".say, .brief");
  for (var i = 0; i < boxes.length; i++) {
    if (String(boxes[i].value || "").trim()) return true;
  }
  return false;
}

function goProbe() {
  if (probing) return;
  if (unsentText()) {
    if (!probeWaiting) {
      say("`ad-fleet probe` asked this window to go to the probe — it goes once what you are "
          + "typing is sent or cleared", 12);
      probeWaiting = setInterval(function () {
        if (unsentText()) return;
        clearInterval(probeWaiting);
        probeWaiting = 0;
        goProbe();
      }, 1000);
    }
    return;
  }
  probing = true;
  post("measure", { w: W_NAME, take: true }).then(function (r) {
    if (!r || !r.ok || !r.go) {
      probing = false;
      return;
    }
    var dest = new URL("/probe", location.origin);
    PARAMS.forEach(function (value, key) { dest.searchParams.set(key, value); });
    dest.searchParams.set("w", W_NAME);
    dest.searchParams.set("back", "1");
    location.assign(dest.toString());
  }).catch(function () { probing = false; });
}

/* The approvals from the last answer, kept so a redraw does not need a fetch to be honest. */
var lastApprovals = [];

/* Every tile drawn again from the row it already has, and one layout pass. No network: this is
   what a stream frame, a theme change or a mode toggle needs, and under the render contract
   (#215) it is free when nothing has changed. */
function redrawAll() {
  tiles.forEach(function (entry) {
    if (entry.row) drawTile(entry.el, entry.row, lastApprovals);
  });
  place();
}

/* Was this row read before the one the tile already has (#235)? The two roads race each other home:
   a snapshot the server read a moment before a hand-back landed after the hand-back's own answer and
   drew the adoption back, and nothing came to draw it again -- a released lock is not an event. The
   server numbers its reads, and a row from another run of it is a desk that restarted: taken. */
/** @param {Row | undefined} shown  @param {Row} row  @returns {boolean} */
function readBefore(shown, row) {
  var had = shown && shown.as_of, got = row.as_of;
  return !!(had && got && had.run === got.run && got.n < had.n);
}

/* One row onto its tile, making the tile if this is the first sight of it. Both an action's
   answer (#219) and a whole snapshot come through here, so a tile cannot be drawn one way by one
   path and another way by the other -- nor by the older of the two because it arrived second. */
/* A tile's transcript from a row's `recent` (its last forty), the cursor taken from each, then the
   scroll this window left it at. */
/** @param {Pane} entry  @param {Row} row */
function fillTranscript(entry, row) {
  (row.recent || []).forEach(function (ev) { append(entry.el, ev); entry.seq = ev.seq; });
  try {
    var savedScroll = sessionStorage.getItem("fleet.scroll." + row.repo);
    if (savedScroll !== null) {
      entry.el.querySelector(".transcript").scrollTop = Number(savedScroll);
    }
  } catch (e) {}
}

/** @param {Row} row  @param {number} [index]  @returns {Pane | null} */
function patchRow(row, index) {
  if (!row || !row.repo) return null;
  var entry = tiles.get(row.repo);
  if (entry && readBefore(entry.row, row)) return entry;
  if (!entry) {
    var el = makeTile(row, index || tiles.size);
    var grid = document.getElementById("grid");
    if (grid) grid.appendChild(el);
    watchPane(el);                               // #233: its width decides what it draws
    arrivedSinceLastPlace = true;                // and where it first lands is not a move
    entry = { el: el, seq: 0 };
    tiles.set(row.repo, entry);
    fillTranscript(entry, row);
  } else if (entry.restored) {
    // #347: drawn from the snapshot, which keeps no transcript. Its first real row fills it and
    // sets the cursor, so the stream resumes after that row instead of replaying from 0.
    entry.restored = false;
    fillTranscript(entry, row);
  }
  entry.row = row;
  departed.delete(row.repo);
  drawTile(entry.el, row, lastApprovals);
  return entry;
}

/* ------------------------------------------- #219: the desk that is already there, while it loads

   Stale, then right. The first `/api/fleet` on a nine-project fleet is a catalogue read, a fold
   per agent and a spend ledger per agent, and until it answered the window was an empty grid with
   a sentence about having no projects -- which is the wrong answer to "what is my fleet doing",
   given for a second, every time a window is reopened.

   So the last snapshot this window saw is kept and drawn first, marked as what it is, and the
   fetch that is already in flight replaces it. Without the transcripts: they are the big part of
   the payload, they are the part that goes stale fastest, and the first answer brings the last
   forty, and the stream resumes after them (#347). */
var SNAP_KEY = "fleet.snapshot." + W_NAME;
var SNAP_GOOD_FOR_MS = 5 * 60 * 1000;
var lastFleet = null;
/* How many `theme` events the stream has delivered (#437). A fleet answer's theme is the one saved
   when the server answered, so an answer asked before a theme change lands after the stream's
   event and would put the old skin back. `refresh` applies the answer's theme only when no theme
   event arrived while it was in flight. */
var themeEvents = 0;

/* The desk as this window last showed it: the newest desk it holds, with the agent it has open.
   The fleet's own answer is older than both the moment a click lands, and a snapshot kept from it
   reopened -- on the next load -- whichever agent was open when it was taken, then jumped to the
   right one when the fleet answered (#230). */
/** @param {DeskRecord | null} fallback  @returns {DeskRecord | null} */
function deskAsShown(fallback) {
  var d = desk.desk || fallback;
  if (!d) return null;
  d = JSON.parse(JSON.stringify(d));
  d.windows = d.windows || {};
  var mine = Object.assign({}, d.windows[W_NAME] || {});
  if (openTile) mine.open = openTile;
  // The widths it shows, for the same reason (#234): a gesture a moment before the reload is newer
  // than the last answer the fleet gave.
  if (myWidths) mine.widths = Object.assign({}, myWidths);
  else delete mine.widths;
  d.windows[W_NAME] = mine;
  return d;
}

function cacheSnapshot(data) {
  try {
    sessionStorage.setItem(SNAP_KEY, JSON.stringify({
      at: Date.now(),
      repos: (data.repos || []).map(function (row) {
        return Object.assign({}, row, { recent: [], earlier: [], run: null });
      }),
      approvals: data.approvals || [],
      desk: deskAsShown(data.desk || null),
      spend: data.spend || {},
    }));
  } catch (e) { /* a private window, or no room: the desk simply loads the slow way */ }
}

/* The tiers the server wrote on <html> (#345), `rail compact full slack`, or null on the defaults. */
/** @returns {Tiers | null} */
function servedTiers() {
  var said = document.documentElement.dataset.tiers;
  if (!said) return null;
  var n = said.split(" ").map(Number);
  return { rail: n[0], compact: n[1], full: n[2], slack: n[3], invalid: "" };
}

/* Back into a page the browser kept whole (bfcache): what it shows is from before it was left, and
   a theme chosen meanwhile reaches it only by asking again. */
window.addEventListener("pageshow", function (e) { if (e.persisted) refresh(); });

/* Taken again as the window goes -- a reload, a navigation, a closed tab -- so the next load draws
   what was on the screen, not what the last fleet answer said a click or two before. */
window.addEventListener("pagehide", function () { if (lastFleet) cacheSnapshot(lastFleet); });

function restoreCached() {
  var data = null;
  try {
    var raw = sessionStorage.getItem(SNAP_KEY);
    data = raw ? JSON.parse(raw) : null;
  } catch (e) { return false; }
  if (!data || !(data.repos || []).length) return false;
  // Five minutes. Past that the shape of the fleet has probably changed, and a wrong desk held
  // for a second is worse than an empty one -- the fetch is in flight either way.
  if (Date.now() - (data.at || 0) > SNAP_GOOD_FOR_MS) return false;
  // No theme and no tiers (#345): the served page already wears the chosen ones, and a snapshot's
  // were taken before the change that sent the operator here -- the skin just replaced.
  if (data.desk) {
    // Shown, not believed. Its version is the snapshot's, so it is dropped: the first real answer
    // has to win whatever number it carries, or a desk.json that started again from nought would
    // never be heard. The window's own open agent is what is drawn, as the real answer will.
    var shown = Object.assign({}, data.desk);
    delete shown.version;
    desk.desk = shown;
    var mine = shown.windows && shown.windows[W_NAME];
    if (mine && mine.open) openTile = String(mine.open);
    if (mine) myWidths = ownWidths(mine.widths);
  }
  lastApprovals = data.approvals || [];
  data.repos.forEach(function (row, i) {
    var e = patchRow(row, i);
    if (e) e.restored = true;                     // #347: its first real row brings the transcript
  });
  hide(document.getElementById("empty"), true);
  // Said, not hidden: the desk on the screen is the last one this window saw, and the operator is
  // told so rather than left to find out.
  toggle(document.body, "is-stale", true);
  place();
  return true;
}

function refresh() {
  if (pendingRefresh) return pendingRefresh;
  var themesAsked = themeEvents;
  pendingRefresh = fetch(q("/api/fleet")).then(function (r) {
    if (r.status === 403 && streamDead) {
      rehome();
      return { ok: false, repos: [] };
    }
    return r.json();
  }).then(function (data) {
    pendingRefresh = null;
    if (!data.ok) return;
    var grid = document.getElementById("grid");
    hide(document.getElementById("empty"), data.repos.length > 0);
    lastApprovals = data.approvals || [];
    data.repos.forEach(function (row, i) { patchRow(row, i); });
    tiles.forEach(function (entry, name) {
      if (!data.repos.some(function (r) { return r.repo === name; })) {
        // Removed from the registry. Its pane goes, but not silently: it leaves a rail naming the
        // command that restores it, because a transcript disappearing with no explanation is
        // exactly the "where did it go" #173 exists to answer.
        departed.set(name, { path: (entry.row && entry.row.path) || "<path>" });
        forgetPane(entry.el);
        entry.el.remove();
        tiles.delete(name);
      }
    });
    var need = data.repos.filter(function (r) { return r.needs_human; }).length;
    drawRenewStrip(data.repos, data.server);
    var fleetSpend = data.spend || {};
    var counts = document.getElementById("counts");
    text(counts,
         data.repos.length + " agents" + (need ? "  ·  " + need + " need you" : "") +
         (fleetSpend.all_time
            ? "  ·  " + fleetSpend.today + " premium today  ·  " + fleetSpend.all_time + " all time"
            : ""));
    attr(counts, "title", fleetSpend.all_time
      ? "summed from every agent's own ledger; a day is the operator's own, and a session that "
        + "runs over midnight is charged to each day only what it rose by"
      : "");
    // A budget nobody can read cannot be enforced, so it is off -- and said out loud rather than
    // swallowed into 0.0, which is what the old reader did (#213).
    if (fleetSpend.budget_invalid) {
      say("fleet.budget_per_agent is " + JSON.stringify(fleetSpend.budget_invalid) +
          ", which is not a number — the cap is off until it is one", 20);
    }
    if (data.desk) acceptDesk(data.desk);
    if (themeEvents !== themesAsked) delete data.theme;   // older than the stream's: not drawn, not cached
    if (data.theme) {
      applyTheme(data.theme.css, data.theme.theme);
      applySkin(data.theme.skin);
      applyTiers(data.theme.tiers);               // #235: the operator's tier boundaries
    }
    if (typeof data.preflight === "boolean") PREFLIGHT = data.preflight;
    toggle(document.body, "is-stale", false);
    lastFleet = data;
    cacheSnapshot(data);
    place();
    title(need);
    return data;
  }).catch(function () { pendingRefresh = null; });
  return pendingRefresh;
}

var refreshSoon = (function () {
  var timer = null;
  return function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; refresh(); }, 400);
  };
})();

function cursors() {
  var parts = [];
  tiles.forEach(function (entry, name) { parts.push(name + ":" + entry.seq); });
  return parts.join(",");
}

/* `body.is-replaying` (#371): the first pass after every open is history, not news. The server
   writes every event after each cursor in `since` and ends a pass that sent frames with `tick`; a
   repo missing from `since` starts at 0, and EventSource's own reconnect re-sends the original URL,
   whose `since` wins over Last-Event-ID, so it replays from the old cursors. A replayed `li.denied`
   looks exactly like a fresh one, so the page says which until the pass's `tick`. Set here and in
   `onopen` (the native reconnect calls only that); nothing styles it. */
function connect() {
  if (source) source.close();
  var link = document.getElementById("link");
  toggle(document.body, "is-replaying", true);
  source = new EventSource(q("/api/events", { since: cursors(), w: W_NAME, shell: PARAMS.get("shell") || "" }));
  source.addEventListener("agent", function (m) {
    var ev = JSON.parse(m.data);
    var entry = tiles.get(ev.repo);
    if (!entry) return refreshSoon();
    entry.seq = Math.max(entry.seq, ev.seq);
    append(entry.el, ev);
    refreshSoon();
  });
  source.addEventListener("notify", function (m) { arrived(JSON.parse(m.data)); });
  // A poll cell changed with no event to say so (#184): re-read.
  source.addEventListener("polls", function () { refreshSoon(); });
  // The shared selection (#133). Every window is sent the current one the moment it connects, so a
  // monitor that joined late never sits on a different project than the one beside it.
  source.addEventListener("desk", function (m) {
    acceptDesk(JSON.parse(m.data));
    place();
  });
  source.addEventListener("theme", function (m) {
    themeEvents++;
    try {
      var d = JSON.parse(m.data);
      applyTheme(d.css, d.theme);
      applySkin(d.skin);
      applyTiers(d.tiers);                        // #235: set on the settings page, in effect now
      if (d.accents) {
        Object.keys(d.accents).forEach(function (repo) {
          if (tiles.has(repo)) paintAccent(tiles.get(repo).el, d.accents[repo]);
        });
      }
      /* #218 repainted every trace here, because a canvas held pixels rather than rules. The trace
         is the stylesheet's colours now (#257) and the ink layer reads the palette at paint time,
         so a palette that changes needs nothing drawn again. */
    } catch (err) {}
  });
  source.addEventListener("tick", function () {
    toggle(document.body, "is-replaying", false);
    setClass(link, "dot live");
    text(link, "live");
  });
  source.onopen = function () {
    toggle(document.body, "is-replaying", true);
    streamDead = false; setClass(link, "dot live"); text(link, "live");
  };
  source.onerror = function () {
    streamDead = true;
    setClass(link, "dot lost");
    text(link, "reconnecting");
    // EventSource reconnects on its own, but the page must not trust what it drew in between.
    setTimeout(function () { refresh().then(connect); }, 2000);
  };
}

/* ------------------------------------------------------------------- opening one, and the keyboard */

/* ------------------------------------------------------- what the two focuses actually are (#207)

   `focus()` zoomed one tile and `focusMode()` filtered for the ones that need a person: two modes
   named alike, side by side. They are `openAgent` and the *needs me* preset now (#234) -- a press
   that widens whoever needs you, not a mode.

   Not literally `open`: a bare `function open()` in a non-module script replaces `window.open` for
   the whole page, and a name that shadows a platform function to read slightly better is a trade
   this page does not need to make. Nor `focus`, the old name, which stayed as an alias until the
   type check read it (#236: `Duplicate identifier 'focus'`). `var focus` in a non-module script IS
   `window.focus`, so a `window.focus()` from anything on the page opened nobody, shut the drawer and
   wrote this window's record twice. Nothing called the alias -- the shells open an agent with
   `#tile=`, and no test named it but to say it was there -- so it went. */
function openAgent(name, skipPost) {
  unread.delete(name);                       // looking at it is what "read" means
  var entry = tiles.get(name);
  if (entry && entry.seq) {
    readCursors[name] = entry.seq;
  }
  bell();
  drawer(false);
  markTile(name);
  /* There is no zoom to enter (#232): every agent is a pane in the row already (#233), so "focus
     this agent" and "open this agent" are the same gesture. Every caller -- a toast's anchor, a
     notification row, the away strip -- therefore lands on the right thing. */
  openPane(name, skipPost);
  if (!skipPost) saveWindow({ read: readCursors });
}

/* A toast launches `…/?t=…#tile=luna`, so the click lands on the agent that needs the operator
   rather than on "one of these four". Also fired on hashchange, because the window may already be
   open and the shell simply re-focuses it with a new hash. */
function followHash() {
  var m = /^#tile=(.+)$/.exec(location.hash || "");
  if (!m) return;
  var name = decodeURIComponent(m[1]);
  if (!tiles.has(name)) {
    // A toast for a repository with no tile used to do nothing at all: the window simply sat there
    // while the operator waited for something to happen (#173).
    say("no tile for '" + name + "' — is it still registered?");
    return;
  }
  // A hidden tile is reopened by an anchor rather than silently ignored, and the footer says so:
  // the toast said this agent needs somebody, and the operator asked to see it.
  if (isHidden(name)) {
    setHidden(name, false);
    say(name + " was hidden — reopened");
  }
  // Focus mode is left alone. It used to be turned off when it was what kept the agent off the
  // glass; since #233 it never keeps anything off the glass -- a quiet rail is dimmed, and an open
  // pane is never quiet -- so turning it off would only throw away the pass the operator was in.
  openAgent(name);
}

window.addEventListener("hashchange", followHash);

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    // The nearest open thing closes first, and nothing else: a popover (#180), then the card (#183).
    if (closeModelCard()) { e.stopImmediatePropagation(); return; }
    if (closeMenus()) { e.stopImmediatePropagation(); return; }
    if (closePopovers()) { e.stopImmediatePropagation(); return; }
    var card = document.getElementById("dispatch");
    if (card && !card.hidden) { closeDispatch(); e.stopImmediatePropagation(); return; }
    if (typing) /** @type {HTMLElement} */ (document.activeElement).blur();
    // There is no zoom to leave, so `Esc` is "show me the last one again" -- which is the other
    // half of the glance the swap is for.
    else backToPrevious();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[2-9]$/.test(e.key)) {
    // The number printed on a pane comes from the arrangement, so the key that opens it must too:
    // registry order meant the badge said 3 and pressing 3 opened something else. It counts the
    // panes on the glass, in the row's order -- every agent is one now (#233), the open one
    // included, so the number on a pane never changes because another one was opened.
    //
    // From 2: `1` is the *one* preset since the gutters (#234), the plan's key for it. The first
    // pane is `j` from nowhere, or `1` with the keyboard on it, which makes it the one wide pane.
    var pane = paneStops()[Number(e.key) - 1];
    /** @type {HTMLElement} */
    var tile = pane && pane.closest ? pane.closest(".tile") : null;
    if (tile && tile.dataset.repo) openPane(railTarget(tile.dataset.repo), false, true);
    return;
  }
  if (e.key === "j" || e.key === "k") {
    stepRow(e.key === "j" ? 1 : -1);
    e.preventDefault();
    return;
  }
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    // #234: the arrows walk the row as `j` and `k` do -- from a pane, or from nowhere. An arrow in
    // the sidebar or a menu is that control's own, and a shifted one is not this gesture.
    var at = document.activeElement;
    if (e.shiftKey || (at && at !== document.body && !(at.closest && at.closest("#grid")))) return;
    stepRow(e.key === "ArrowRight" ? 1 : -1);
    e.preventDefault();
    return;
  }
  if (e.key === "r" || e.key === "m") {
    // The pane the keyboard is on, rail or wide -- the same two keys on either, because a rail has
    // no head to carry the buttons and the keys are how it keeps them (#205, #233).
    /** @type {HTMLElement} */
    var host = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".tile") : null;
    var name = host ? host.dataset.repo : openName();
    if (!name) return;
    if (e.key === "r") doRefresh(name, host ? host.querySelector('[data-tool="refresh"]') : null);
    else openModelCard(name, host ? host.querySelector('[data-tool="model"]') : null);
    e.preventDefault();
    return;
  }
  if (e.key === "h") {
    // Hide the tile the operator is on. Every drag gesture has a keyboard equivalent, and so does
    // this one -- a desk that can only be arranged with a mouse cannot be arranged by someone typing.
    /** @type {HTMLElement} */
    var onTile = document.activeElement && document.activeElement.closest && document.activeElement.closest(".tile");
    if (onTile && onTile.dataset.repo) { setHidden(onTile.dataset.repo, true); return; }
  }
  if (e.key === "n") { section("drawer"); return; }
  if (e.key === "b") { section("board"); return; }
  if (e.key === "a") {
    // The open agent's write: the key used to follow the grid's zoom, which the column never set,
    // so in the column it approved nothing at all.
    var open = openName();
    var entry = open ? tiles.get(open) : null;
    if (entry && entry.el.dataset.approval &&
        !/** @type {HTMLElement} */ (entry.el.querySelector(".approval")).hidden) {
      /** @type {HTMLElement} */ (entry.el.querySelector(".approve")).click();
    }
  }
});

/* ------------------------------------------------------------------------------------- theming */

/* The pickers live on `/settings` now; what stays here is the desk repainting itself when somebody
   else moves them. The `theme` frame arrives on the stream whenever `config.json` changes, so a
   palette chosen on the settings page, in another window, or by `ad-theme set` in a terminal
   reaches this desk without a reload. `applyTheme` and `applySkin` are common.js's. */

/* The token is per run and `_authorized` reads it from the query string alone, so the settings
   link cannot be a static href in the markup -- it would 403 and read as a dead button, which is
   exactly what the operator reported. */
var setLink = /** @type {HTMLAnchorElement} */ (document.getElementById("setbtn"));
if (setLink) setLink.href = pageUrl("/settings");

refresh().then(function () {
  LOAD.settled = document.body.dataset.skin || "";   // the skin the first refresh settled on (#351)
  connect();
  loadNotifications();
  // The anchor is answered *after* the desk, not beside it: whether a tile is hidden is the
  // server's arrangement, and a `#tile=` that lands before that has loaded reads every tile as on
  // the glass -- so the one thing it was asked to do, reopen a tile that is not, it did not (#173).
  //
  // And only the anchor the page was opened with, and only if nothing has moved it since. The desk
  // read is the slow one -- a catalogue, a Downloads scandir -- and a pane pressed before it answers
  // marks the address itself: followed then, it opened that agent a second time through
  // `openAgent`, whose `drawer(false)` shut the sidebar the operator had opened meanwhile and wrote
  // `section`, `open` and `read` again (#234, three extra writes on the Windows leg).
  loadDesk().then(function () { if (BOOT_HASH && location.hash === BOOT_HASH) followHash(); });
});

// The desk half is answered on its own, slower clock: a catalogue read, a Downloads scandir and a
// `.agent/out/` stat per project is not something to do four times a second, and nothing on it is
// urgent -- what is urgent arrives on the stream.
setInterval(loadDesk, 15000);

/* ------------------------------------------------------------------------- notifications (#97) */

/* The chime is synthesised, not a bundled sound file. WebAudio is in every browser this page has
   to run in, it adds nothing to the payload and nothing to fetch, and a .wav shipped as package
   data is one more thing that can fail to install. Off by default: a sound the operator did not
   ask for is the fastest way to have every notification muted. */
function chime() {
  if (!chimeOn) return;
  try {
    var ctx = new (window.AudioContext || /** @type {any} */ (window).webkitAudioContext)();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.setValueAtTime(880, ctx.currentTime + 0.09);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.32);
    osc.onended = function () { try { ctx.close(); } catch (e) { /* already closed */ } };
  } catch (e) { /* no audio device, or autoplay refused until the page is clicked */ }
}

var unread = new Map();          // repo -> count, cleared when that tile is focused
var chimeOn = false;

function bell() {
  var total = 0;
  unread.forEach(function (n) { total += n; });
  var button = document.getElementById("bell");
  text(document.getElementById("bellcount"), total);
  toggle(button, "unread", total > 0);
  tiles.forEach(function (entry, name) {
    var badge = entry.el.querySelector(".badge");
    var n = unread.get(name) || 0;
    hide(badge, n === 0);
    text(badge, n);
    // The rail carries the same count, and says it in its name (#233).
    if (entry.row) drawPaneRail(entry.el, entry.row);
  });
  return total;
}

function noteRow(item) {
  var li = document.createElement("li");
  setClass(li, item.severity || "info");
  var t = document.createElement("span");
  setClass(t, "t");
  text(t, item.title);
  var b = document.createElement("span");
  setClass(b, "b");
  text(b, item.body || "");
  var when = document.createElement("span");
  setClass(when, "when");
  text(when, String(item.at || "").slice(11, 19) + (item.toasted ? "  ·  toasted" : "") +
             (item.quiet ? "  ·  quiet hours" : ""));
  li.appendChild(t);
  li.appendChild(b);
  li.appendChild(when);
  li.addEventListener("click", function () { if (tiles.has(item.repo)) openAgent(item.repo); });
  return li;
}

function addNote(item, atTop) {
  var list = document.getElementById("notes");
  var row = noteRow(item);
  if (atTop && list.firstChild) list.insertBefore(row, list.firstChild);
  else list.appendChild(row);
  while (list.children.length > 50) list.removeChild(list.lastChild);
  hide(document.getElementById("nonotes"), list.children.length > 0);
}

function arrived(item) {
  unread.set(item.repo, (unread.get(item.repo) || 0) + 1);
  addNote(item, true);
  bell();
  refreshSoon();
  if (item.severity !== "info") chime();
}

function loadNotifications() {
  return fetch(q("/api/notifications", { limit: 50 })).then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.ok) return;
      var list = document.getElementById("notes");
      while (list.firstChild) list.removeChild(list.firstChild);
      (data.notifications || []).slice().reverse().forEach(function (i) { addNote(i, false); });
      text(document.getElementById("toaststatus"), "toast: " + (data.toast || "?"));
      hide(document.getElementById("nonotes"), list.children.length > 0);
    }).catch(function () { /* the drawer is a convenience; the tiles are the truth */ });
}

/* ---------------------------------------------------------------- the sidebar (#148)

   Five panels used to be five fixed overlays at the same screen edge: they covered the grid, they
   covered each other, and because `[hidden]` lost to their `display: flex` a "closed" one went on
   eating the clicks meant for the tiles underneath it. They are now five sections of ONE sidebar
   beside the grid, exactly one open at a time, with a tab strip that says which. Each panel keeps
   the function name the rest of this file already calls. */

var SECTIONS = ["board", "unsorted", "drawer", "found", "inspector"];
var lastSection = "board";

function syncSide() {
  var open = SECTIONS.filter(function (id) {
    var n = document.getElementById(id);
    return n && !n.hidden;
  });
  hide(document.getElementById("side"), open.length === 0);
  attr(document.getElementById("sidetoggle"), "aria-pressed", String(open.length > 0));
  document.querySelectorAll(".side-tabs .segment").forEach(function (/** @type {HTMLElement} */ b) {
    var on = open.indexOf(b.dataset.section) >= 0;
    toggle(b, "active", on);
    attr(b, "aria-selected", String(on));
  });
  return open[0] || "";
}

/* `open` undefined toggles, true opens, false closes. Opening one closes the rest. */
function section(id, open, skipPost) {
  var el = document.getElementById(id);
  if (!el) return false;
  var want = open === undefined ? el.hidden : !!open;
  SECTIONS.forEach(function (s) {
    var n = document.getElementById(s);
    if (n) hide(n, !(s === id && want));
  });
  if (want) lastSection = id;
  syncSide();
  if (want) {
    if (id === "board") { loadBoard(false); loadHistory(); }
    if (id === "drawer") loadNotifications();
    if (id === "unsorted") loadDesk();
    if (id === "inspector") drawInspector(desk.desk.selected);
  }
  if (!skipPost) saveWindow({ section: want ? id : "" });
  return want;
}

function closeSide() {
  SECTIONS.forEach(function (id) {
    var n = document.getElementById(id);
    if (n) hide(n, true);
  });
  syncSide();
  saveWindow({ section: "" });
}

function drawer(open) { return section("drawer", open); }

document.getElementById("bell").addEventListener("click", function () { drawer(); });
document.getElementById("closedrawer").addEventListener("click", function () { drawer(false); });
document.getElementById("clearbell").addEventListener("click", function () {
  unread.clear();
  bell();
});
document.getElementById("chime").addEventListener("click", function () {
  chimeOn = !chimeOn;
  var button = document.getElementById("chime");
  attr(button, "aria-pressed", String(chimeOn));
  text(button, chimeOn ? "chime on" : "chime off");
  try { localStorage.setItem("fleet.chime", chimeOn ? "1" : "0"); } catch (e) { /* private window */ }
  if (chimeOn) chime();                      // and it plays once, so "on" is not taken on trust
});

try { chimeOn = localStorage.getItem("fleet.chime") === "1"; } catch (e) { chimeOn = false; }
attr(document.getElementById("chime"), "aria-pressed", String(chimeOn));
text(document.getElementById("chime"), chimeOn ? "chime on" : "chime off");

/* --------------------------------------------------------------------------- the Jira board (#98) */

/* Dispatching a ticket should not mean copying a key out of a browser. The panel is a view of the
   operator's own JQL; a ticket goes to an agent by being dragged onto its tile, or by clicking the
   button on the row when the repository is unambiguous.

   The suggestion is the server's, from each repo's declared `jira_project`. Three answers, and the
   panel shows all three honestly: one repo (drag has an obvious home), several (pick one — guessing
   would eventually start the wrong checkout), none (the repo is not registered, which is a one-line
   fix worth naming rather than a silent blank). */

var board = [];

function statusClass(row) {
  return "st " + (row.category || "");
}

function ticketRow(row) {
  var li = document.createElement("li");
  li.draggable = true;
  tabbable(li, 0);                                    // `1`-`9` from here picks a rail chip (#183)
  setData(li, "key", row.key);

  var head = document.createElement("div");
  var key = document.createElement("span");
  setClass(key, "key");
  text(key, row.key);
  var st = document.createElement("span");
  setClass(st, statusClass(row));
  text(st, row.status);
  head.appendChild(key);
  head.appendChild(st);

  var sum = document.createElement("span");
  setClass(sum, "sum");
  text(sum, row.summary);

  var to = document.createElement("span");
  setClass(to, "to");
  var s = row.suggested || {};
  text(to, s.repo ? "→ " + s.repo : (s.hint || s.why || ""));
  head.appendChild(document.createTextNode(" "));

  li.appendChild(head);
  li.appendChild(sum);
  li.appendChild(to);

  (s.repo ? [s.repo] : (s.candidates || [])).forEach(function (name) {
    var go = document.createElement("button");
    setClass(go, "go");
    text(go, "start on " + name);
    go.addEventListener("click", function (e) {
      e.stopPropagation();
      dispatch(row.key, name);
    });
    li.appendChild(go);
  });

  li.addEventListener("dragstart", function (e) {
    toggle(li, "dragging", true);
    e.dataTransfer.setData("application/x-agentdata-ticket", row.key);
    e.dataTransfer.setData("text/plain", row.key);
    e.dataTransfer.effectAllowed = "copy";
    railLight(row);
  });
  li.addEventListener("dragend", function () { toggle(li, "dragging", false); railLight(null); });
  return li;
}

/* -------------------------------------------------------------------- the scope, by hash (#166)

   A file dropped on a tile used to light the tile up and do nothing: `drop` read `text/plain` only.
   The page still never learns a path -- no browser gives one, in any of the three embedders this
   page has to render in -- so it does not ask for one. It computes git's own object name for the
   bytes and asks the server which of the checkout's files has it. Nothing but that hash leaves the
   page until the operator clicks *attach a copy*. */

var SCOPE_MAX_HASH = 64 * 1024 * 1024;   /* fleet.scope.max_hash_mb, from /api/fleet */
var SCOPE_MAX_FILES = 200;

/* SHA-1, because that is the hash git names objects with. `crypto.subtle` where the origin is a
   secure context -- loopback is one -- and this otherwise, because VS Code's Simple Browser renders
   the page inside a webview whose context we do not get to assume. No CDN: the page has no build
   step and nothing it fetches from the internet arrives behind the corporate proxy. */
function sha1Bytes(bytes) {
  var ml = bytes.length * 8;
  var withPad = new Uint8Array((((bytes.length + 8) >> 6) + 1) * 64);
  withPad.set(bytes);
  withPad[bytes.length] = 0x80;
  var view = new DataView(withPad.buffer);
  view.setUint32(withPad.length - 4, ml >>> 0, false);
  view.setUint32(withPad.length - 8, Math.floor(ml / 4294967296), false);

  var h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0];
  var w = new Int32Array(80);
  var rol = function (n, s) { return (n << s) | (n >>> (32 - s)); };
  for (var i = 0; i < withPad.length; i += 64) {
    for (var j = 0; j < 16; j++) w[j] = view.getInt32(i + j * 4, false);
    for (j = 16; j < 80; j++) w[j] = rol(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1);
    var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
    for (j = 0; j < 80; j++) {
      var f, k;
      if (j < 20) { f = (b & c) | (~b & d); k = 0x5A827999; }
      else if (j < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1; }
      else if (j < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC; }
      else { f = b ^ c ^ d; k = 0xCA62C1D6; }
      var t = (rol(a, 5) + f + e + k + w[j]) | 0;
      e = d; d = c; c = rol(b, 30); b = a; a = t;
    }
    h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0;
    h[3] = (h[3] + d) | 0; h[4] = (h[4] + e) | 0;
  }
  return h.map(function (n) { return ("00000000" + (n >>> 0).toString(16)).slice(-8); }).join("");
}

function blobSha(file) {
  return file.arrayBuffer().then(function (buffer) {
    var body = new Uint8Array(buffer);
    var header = new TextEncoder().encode("blob " + body.length + "\0");
    var joined = new Uint8Array(header.length + body.length);
    joined.set(header);
    joined.set(body, header.length);
    if (window.crypto && window.crypto.subtle && window.crypto.subtle.digest) {
      return window.crypto.subtle.digest("SHA-1", joined).then(function (digest) {
        return Array.prototype.map.call(new Uint8Array(digest), function (b) {
          return ("0" + b.toString(16)).slice(-2);
        }).join("");
      }).catch(function () { return sha1Bytes(joined); });
    }
    return sha1Bytes(joined);
  });
}

/* A dropped folder is the same trick over its files. `webkitGetAsEntry` is the only way to read
   one, and it is in every engine this page runs on. */
function filesFromDrop(dt) {
  var items = Array.prototype.slice.call(dt.items || []);
  var entries = items.map(function (i) { return i.webkitGetAsEntry && i.webkitGetAsEntry(); })
                     .filter(function (e) { return e && e.isDirectory; });
  if (!entries.length) return Promise.resolve(Array.prototype.slice.call(dt.files || []));

  var out = [];
  var walk = function (dir) {
    return new Promise(function (/** @type {(value?: any) => void} */ done) {
      dir.createReader().readEntries(function (children) {
        Promise.all(children.map(function (child) {
          if (out.length >= SCOPE_MAX_FILES) return Promise.resolve();
          if (child.isDirectory) return walk(child);
          return /** @type {Promise<void>} */ (
            new Promise(function (got) { child.file(function (f) { out.push(f); got(); }, got); }));
        })).then(done);
      }, function () { done(); });
    });
  };
  return Promise.all(entries.map(walk)).then(function () { return out.slice(0, SCOPE_MAX_FILES); });
}

function scopeDrop(el, repo, files) {
  var card = el.querySelector(".scope");
  var rows = card.querySelector(".scope-rows");
  var pattern = rows.querySelector(".scope-row");
  hide(card, false);
  text(card.querySelector(".scope-note"), "reading " + files.length + " file" + (files.length === 1 ? "" : "s") + "…");

  return Promise.all(files.map(function (f) {
    if (f.size > SCOPE_MAX_HASH) {
      // Too big to hash without freezing the tab. Name and size is the weaker claim, and it is
      // labelled as one wherever it is shown -- the way adoption labels its two.
      return Promise.resolve({ name: f.name, size: f.size, sha: "" });
    }
    return blobSha(f).then(function (sha) { return { name: f.name, size: f.size, sha: sha }; });
  })).then(function (asked) {
    return post("scope/resolve", { repo: repo, files: asked }).then(function (r) {
      while (rows.children.length > 1) rows.removeChild(rows.lastChild);
      if (!r || !r.ok) {
        text(card.querySelector(".scope-note"), (r && r.error) || "the scope could not be read");
        return r;
      }
      var resolved = [];
      (r.files || []).forEach(function (item, i) {
        var li = pattern.cloneNode(true);
        hide(li, false);
        setClass(li, "scope-row s-" + item.status);
        text(li.querySelector(".sc-name"), item.name);
        text(li.querySelector(".sc-path"), item.paths && item.paths.length ? item.paths[0] : "");
        text(li.querySelector(".sc-how"), item.how || "");
        text(li.querySelector(".sc-why"), item.why || "");
        if (item.status === "resolved") resolved.push(item.paths[0]);
        if (item.status === "ambiguous") {
          var pick = li.querySelector(".sc-pick");
          hide(pick, false);
          item.paths.forEach(function (p) {
            var o = document.createElement("option");
            o.value = p; text(o, p); pick.appendChild(o);
          });
          resolved.push(item.paths[0]);
          pick.addEventListener("change", function () {
            resolved[resolved.indexOf(li.dataset.chosen || item.paths[0])] = pick.value;
            setData(li, "chosen", pick.value);
          });
          setData(li, "chosen", item.paths[0]);
        }
        if (item.status === "unmatched") {
          // Not this repository's file. The only route that moves bytes, and only on this click.
          var attach = li.querySelector(".sc-attach");
          hide(attach, false);
          attach.addEventListener("click", function () {
            var f = files[i];
            f.arrayBuffer().then(function (buf) {
              var bin = "";
              var view = new Uint8Array(buf);
              for (var n = 0; n < view.length; n++) bin += String.fromCharCode(view[n]);
              return post("attach-bytes", { repo: repo, name: f.name, bytes: btoa(bin) });
            }).then(function (a) {
              text(li.querySelector(".sc-why"), a && a.ok ? "attached → " + a.dir : ((a && a.error) || "refused"));
              if (a && a.ok) hide(attach, true);
            });
          });
        }
        rows.appendChild(li);
      });
      if (!resolved.length) {
        text(card.querySelector(".scope-note"), "not a file of " + repo);
        return r;
      }
      return post("scope", { repo: repo, paths: resolved, why: "dropped on the tile" })
        .then(function (added) {
          text(card.querySelector(".scope-note"),
               added && added.ok
                 ? (added.queued ? "queued for its next turn" : "given to " + repo)
                 : ((added && added.error) || "the scope could not be written"));
          var tell = card.querySelector(".scope-tell");
          hide(tell, !(added && added.ok && added.queued === false));
          return added;
        });
    });
  }).catch(function () {
    text(card.querySelector(".scope-note"), "the files could not be read");
  });
}

/* ------------------------------------------------------------------ the dispatch card (#164)

   A drop used to be a launch. It opens this instead: the rows a person would have checked before
   delegating, gathered by a server-side pre-flight that spends no premium request, and one button.
   `fleet.preflight: false` restores #98's immediate start for anyone who preferred it. */

/* One card, two homes (#183): the pane's slot when the pane has room for it, else under the agent
   rail. Every agent is on the glass now (#233), but a rail is 48px of glass and a card is not
   drawn in one: a compact or full pane takes it, a rail sends it to the board. */
function onTheGlass(repo) {
  var entry = tiles.get(repo);
  return !!(entry && entry.el.offsetParent !== null && !entry.el.classList.contains("is-hidden") &&
            paneShows(entry.el).wide && entry.el.classList.contains("is-solo"));
}

function dispatchHome(repo) {
  if (onTheGlass(repo)) return tiles.get(repo).el.querySelector(".dispatch-slot");
  return document.getElementById("railslot");
}

function dispatchCard(key, repo) {
  var card = document.getElementById("dispatch");
  var rows = card.querySelector(".dispatch-rows");
  /** @type {HTMLTextAreaElement} */
  var brief = card.querySelector(".brief");
  var home = dispatchHome(repo);
  if (card.parentNode !== home) home.appendChild(card);       // moved, never copied
  if (home.id === "railslot") { boardPanel(true); }

  text(card.querySelector(".dispatch-key"), key + " → " + repo);
  text(card.querySelector(".verdict"), "reading…");
  setClass(card.querySelector(".verdict"), "verdict");
  while (rows.firstChild) rows.removeChild(rows.firstChild);
  brief.value = "";
  text(card.querySelector(".dispatch-note"), "");
  hide(card, false);
  setData(card, "key", key);
  setData(card, "repo", repo);

  fetch(q("/api/preflight", { key: key, repo: repo })).then(function (r) {
    return r.json();
  }).then(function (card_data) {
    if (card.dataset.key !== key) return;           // a second drop overtook this one
    var verdict = (card_data && card_data.verdict) || "unknown";
    var chip = card.querySelector(".verdict");
    text(chip, verdict);
    setClass(chip, "verdict v-" + verdict);
    (card_data.rows || []).forEach(function (r) {
      var li = document.createElement("li");
      setClass(li, "dispatch-row r-" + (r.verdict || "ready"));
      var n = document.createElement("span"); setClass(n, "dr-name"); text(n, r.row);
      var v = document.createElement("span"); setClass(v, "dr-value"); text(v, r.value);
      li.appendChild(n); li.appendChild(v);
      if (r.why) { var w = document.createElement("span"); setClass(w, "dr-why"); text(w, r.why); li.appendChild(w); }
      rows.appendChild(li);
    });
    // `thin` is the one verdict that asks for something: the brief box takes the focus and the
    // button says so. `blocked` still offers the press, because the refusal is the server's to
    // give in its own words and the operator may hold an override the card does not know about.
    var go = card.querySelector(".dispatch-go");
    text(go, verdict === "ready" ? "Start" : "Start anyway");
    text(card.querySelector(".dispatch-note"),
         verdict === "thin" ? "thin — a brief is what makes this worth a turn"
         : verdict === "unknown" ? "some rows could not be read; Start still works"
         : "");
    if (verdict === "thin" || verdict === "blocked") brief.focus();
  }).catch(function () {
    if (card.dataset.key !== key) return;
    text(card.querySelector(".verdict"), "unknown");
    text(card.querySelector(".dispatch-note"), "the pre-flight could not be read; Start still works");
  });
}

function closeDispatch() {
  var card = document.getElementById("dispatch");
  if (card) { hide(card, true); setData(card, "key", ""); setData(card, "repo", ""); }
}

/* A refusal lands where the operator is looking: the card's note, or the line under the rail. */
function said(repo, message) {
  var card = document.getElementById("dispatch");
  if (card && !card.hidden && card.dataset.repo === repo) {
    text(card.querySelector(".dispatch-note"), message);
  } else if (!onTheGlass(repo)) {
    var note = document.getElementById("railnote");
    text(note, message);
    hide(note, !message);
  }
}

function dispatch(key, repo, brief) {
  var entry = tiles.get(repo);
  var el = entry ? entry.el : document.body;
  var body = { repo: repo, ticket: key };
  if (brief) body.brief = brief;
  return action(el, "start", body).then(function (r) {
    if (r && r.ok) { boardPanel(false); closeDispatch(); said(repo, ""); openAgent(repo); }
    else if (r && !r.ok && (r.code === "cross_project" || /jira_project/.test(r.error || ""))) {
      // The one refusal worth offering an override for in the page: the operator can see both
      // projects on screen and is better placed than the guard to say it is deliberate.
      said(repo, r.error + (r.hint ? " — " + r.hint : ""));
      if (confirm(r.error + "\n\nStart it anyway?")) {
        var again = { repo: repo, ticket: key, cross_project: true };
        if (brief) again.brief = brief;
        action(el, "start", again).then(function (r2) {
          if (r2 && r2.ok) { closeDispatch(); said(repo, ""); }
          else if (r2) said(repo, r2.error + (r2.hint ? " — " + r2.hint : ""));
          return r2;
        });
      }
    } else if (r && !r.ok) {
      said(repo, r.error + (r.hint ? " — " + r.hint : ""));
    }
    return r;
  });
}

(function bindDispatchCard() {
  var card = document.getElementById("dispatch");
  if (!card) return;
  card.querySelector(".dispatch-close").addEventListener("click", function () { closeDispatch(); });
  card.querySelector(".dispatch-go").addEventListener("click", function () {
    dispatch(card.dataset.key || "", card.dataset.repo || "",
             /** @type {HTMLTextAreaElement} */ (card.querySelector(".brief")).value.trim());
  });
  card.querySelector(".brief").addEventListener("keydown", function (/** @type {KeyboardEvent} */ e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      /** @type {HTMLElement} */ (card.querySelector(".dispatch-go")).click();
      e.preventDefault();
    }
    else if (e.key === "Escape") { closeDispatch(); e.stopPropagation(); }
  });
})();

/* ------------------------------------------------------------------------ the agent rail (#183)
   One chip per checkout at the top of the board, each a drop target for the window with no tiles.
   A drag lights the candidates; a drop calls what a tile's drop calls; `1`-`9` is the same by key. */
var railDrag = null;                                   // the ticket row in flight, if any

function drawRail() {
  var list = document.getElementById("agentrail");
  if (!list) return;
  var pattern = list.querySelector(".rail-chip");
  var names = getEffectiveOrder().filter(function (name) { return tiles.has(name); });

  patchList(list, names, function (name) { return name; },
    function (name) {
      var li = /** @type {HTMLElement} */ (pattern.cloneNode(true));
      hide(li, false);
      setData(li, "repo", name);
      /** @type {HTMLElement} */
      var button = li.querySelector(".rail-open");
      attr(button, "aria-label", name);
      attr(button, "title", "drop a ticket here to start it on " + name);
      button.addEventListener("click", function () { openAgent(name); });
      button.addEventListener("dragover", function (e) {
        if (!ticketInFlight(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        toggle(button, "drop-target", true);
      });
      button.addEventListener("dragleave", function () { toggle(button, "drop-target", false); });
      button.addEventListener("drop", function (e) {
        e.preventDefault();
        toggle(button, "drop-target", false);
        var key = (e.dataTransfer.getData("application/x-agentdata-ticket") ||
                   e.dataTransfer.getData("text/plain") || "").trim();
        if (key) takeTicket(key, name);
      });
      return li;
    },
    function (li, name) {
      var entry = tiles.get(name);
      var row = (entry && entry.row) || {};
      setClass(li, "rail-chip" + (entry && entry.el.classList.contains("needs-human")
                                    ? " needs-human" : ""));
      text(li.querySelector(".dc-name"), name);
      text(li.querySelector(".dc-chip"),
           (row.state || "") + (row.at ? " · " + agentAge(ageOf(row)) : ""));
    });
  railLight(railDrag);
}

function ticketInFlight(e) {
  var types = Array.from((e.dataTransfer && e.dataTransfer.types) || []);
  return types.indexOf("application/x-agentdata-ticket") >= 0 || types.indexOf("text/plain") >= 0;
}

function takeTicket(key, repo) {
  if (PREFLIGHT) dispatchCard(key, repo); else dispatch(key, repo);
}

/* A dimmed chip still takes a drop; `cross_project` is the answer. */
function railLight(row) {
  railDrag = row;
  var s = (row && row.suggested) || {};
  var candidates = row ? (s.repo ? [s.repo] : (s.candidates || [])) : [];
  Array.prototype.forEach.call(document.querySelectorAll("#agentrail .rail-chip:not([hidden])"), function (li) {
    var lit = !!row && candidates.indexOf(li.dataset.repo) >= 0;
    toggle(li, "is-candidate", lit);
    toggle(li, "is-dim", !!row && !lit);
    attr(li.querySelector(".rail-open"), "aria-selected", String(lit));
  });
}

document.getElementById("tickets").addEventListener("keydown", function (
    /** @type {KeyboardEvent & {target: Element}} */ e) {
  /** @type {HTMLElement} */
  var li = e.target.closest && e.target.closest("li[data-key]");
  if (!li) return;
  var row = board.filter(function (r) { return r.key === li.dataset.key; })[0];
  if (!row) return;
  // Stops here: the page's own `1`-`9` zooms a tile, closing the board under the card.
  if (/^[1-9]$/.test(e.key)) {
    /** @type {NodeListOf<HTMLElement>} */
    var chips = document.querySelectorAll("#agentrail .rail-chip:not([hidden])");
    var chip = chips[Number(e.key) - 1];
    if (chip) { takeTicket(row.key, chip.dataset.repo); e.preventDefault(); e.stopPropagation(); }
  } else if (e.key === "Enter") {
    var s = row.suggested || {};
    var only = s.repo || ((s.candidates || []).length === 1 ? s.candidates[0] : "");
    if (only) { takeTicket(row.key, only); e.preventDefault(); e.stopPropagation(); }
  }
});

function drawBoard(rows) {
  var list = document.getElementById("tickets");
  var needle = (/** @type {HTMLInputElement} */ (document.getElementById("boardsearch")).value || "")
    .toLowerCase();
  // A redraw keeps the keyboard on its row (#183).
  var had = document.activeElement && list.contains(document.activeElement) ?
            /** @type {{dataset?: DOMStringMap}} */ (document.activeElement.closest("li[data-key]") || {})
              .dataset : null;
  while (list.firstChild) list.removeChild(list.firstChild);
  var shown = rows.filter(function (r) {
    return !needle || (r.key + " " + r.summary + " " + r.status).toLowerCase().indexOf(needle) >= 0;
  });
  shown.forEach(function (r) { list.appendChild(ticketRow(r)); });
  hide(document.getElementById("noboard"), shown.length > 0);
  if (had && had.key) {
    /** @type {HTMLElement} */
    var back = list.querySelector('li[data-key="' + had.key + '"]');
    if (back) back.focus();
  }
}

function loadBoard(refresh) {
  var err = document.getElementById("boarderr");
  return fetch(q("/api/board", refresh ? { refresh: "1" } : {}))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      hide(err, !!data.ok);
      if (!data.ok) {
        text(err, data.error + (data.hint ? " — " + data.hint : ""));
        return;
      }
      board = data.rows || [];
      text(document.getElementById("boardage"),
           data.cached ? "cached, " + age(data.age_s) + " old" : "from jira");
      drawBoard(board);
    }).catch(function (e) { hide(err, false); text(err, String(e)); });
}

function loadHistory() {
  return fetch(q("/api/history", { since: "7d" })).then(function (r) { return r.json(); })
    .then(function (data) {
      var body = document.getElementById("runs");
      while (body.firstChild) body.removeChild(body.firstChild);
      (data.runs || []).slice().reverse().forEach(function (run) {
        var tr = document.createElement("tr");
        [[String(run.started).slice(5, 16), ""], [run.repo, ""], [run.ticket || "-", ""],
         [run.state, "state-" + run.state], [String(run.premium_requests), ""]].forEach(function (cell) {
          var td = document.createElement("td");
          if (cell[1]) setClass(td, cell[1]);
          text(td, cell[0]);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }).catch(function () { /* the strip is a convenience */ });
}

function boardPanel(open) { return section("board", open); }

document.querySelectorAll(".side-tabs .segment").forEach(function (/** @type {HTMLElement} */ b) {
  b.addEventListener("click", function () { section(b.dataset.section); });
});
document.getElementById("sidetoggle").addEventListener("click", function () {
  if (syncSide()) closeSide(); else section(lastSection, true);
});
document.getElementById("closeboard").addEventListener("click", function () { boardPanel(false); });
document.getElementById("boardrefresh").addEventListener("click", function () { loadBoard(true); });
document.getElementById("boardsearch").addEventListener("input", function () { drawBoard(board); });

/* ================================================================= the desk (#130 #131 #132 #133)

   Everything below reads. The one exception is `attach`, which copies a file the operator clicked
   into that repository's own `.agent/in/` -- the single write the epic allows outside
   `~/.agentdata/fleet/`, and it happens because a person pressed a button.

   All of it comes from one `/api/desk` on a slow clock rather than a fetch per tile: four screens
   of tiles is four screens of requests otherwise, and none of this is urgent. */

/** @param {string[]} order */
function registryChanged(order) {
  if (!Array.isArray(order)) return false;
  if (order.length !== tiles.size) return true;
  return order.some(function (name) { return !tiles.has(name); });
}

function loadDesk() {
  if (pendingDesk) return pendingDesk;
  pendingDesk = fetch(q("/api/desk")).then(function (r) { return r.json(); }).then(function (data) {
    pendingDesk = null;
    if (!data.ok) return;
    // Everything but the desk state is this answer's; the desk state goes through the door (#230).
    var incoming = data.desk;
    data.desk = desk.desk;
    desk = data;
    acceptDesk(incoming);
    // `ad-fleet repo add` and `repo rm` change which tiles exist and neither is an agent event,
    // so the stream never mentions it: the grid drew a repository that had left, or missed one that
    // had arrived, until a reload. The desk's slow clock carries the registry's list, so a
    // disagreement is what asks `/api/fleet` again (#173).
    if (registryChanged(data.order)) refresh();
    // The project's own detail is the inspector's, and the inspector draws the selected one.
    drawInspector(desk.desk.selected);
    drawTray();
    place();
    return data;
  }).catch(function () { pendingDesk = null; });
  return pendingDesk;
}

var deskSoon = (function () {
  var timer = null;
  return function () {
    if (timer) return;
    timer = setTimeout(function () { timer = null; loadDesk(); }, 300);
  };
})();

/* ------------------------------------------------------------------ the project's live state */

var CELLS = ["ticket", "pr", "refresh", "git"];

/* A cell is value + age, and when the poll failed it is grey with the error in the tooltip and the
   *last value it actually had* still on it. Blanking it would lose what was known; keeping it
   without the age would make five-minute-old news look current. Grey, old and honest. */
function drawCells(el, polls, row) {
  var box = el.querySelector(".cells");
  var want = [];
  var spend = (row || {}).spend;
  if (spend && (spend.total || spend.budget)) want.push({ cell: "spend", row: row || {} });
  CELLS.forEach(function (name) {
    var p = polls[name];
    if (!p) return;
    var value = (p.value && p.value.text) || "";
    if (!value && !p.error) return;                 // nothing to ask about: no PR, no dataset
    want.push({ cell: name, poll: p, value: value });
  });

  /* Keyed, and created once. The cells were emptied and rebuilt with fresh listeners on every
     draw, which is several times a second while an agent talks -- so the git cell the operator was
     about to click was a different element by the time they clicked it. */
  patchList(box, want, function (item) { return item.cell; },
    function (item) {
      // Cloned from the shape in the markup, and listened to once. The git cell is a button
      // (#184): the click opens the inspector's branches pane.
      var shape = box.querySelector(item.cell === "git" ? ".gitshape" : ".cellshape");
      var node = shape.cloneNode(true);
      hide(node, false);
      setClass(node, "cell");
      if (item.cell === "git") {
        node.addEventListener("click", function (e) {
          e.stopPropagation();
          openBranches(el.dataset.repo);
        });
      }
      setData(node, "cell", item.cell);
      text(node.querySelector(".lab"), item.cell);
      return node;
    },
    function (node, item) {
      if (item.cell === "spend") return drawSpendCell(node, item.row);
      var p = item.poll;
      setClass(node, "cell" + (p.grey ? " grey" : "") + (item.value ? "" : " idle"));
      text(node.querySelector(".val"), item.value || "—");
      text(node.querySelector(".old"), p.age_s ? age(Math.round(p.age_s)) : "");
      var title = p.error ? p.error : (item.cell + ", polled every " + p.interval + "s");
      if (item.cell === "git") {
        var v = p.value || {};
        text(node.querySelector(".val2"), v.line2 || "");
        if (v.warn && !p.grey) {
          toggle(node, "warn", true);
          title = v.line2 + " (" + v.warn_at + "+ is worth a look)" +
                  (v.carrying && v.carrying.length > 1
                     ? "; " + v.carrying.length + " carry the active ticket" : "") +
                  ". Click for the history.";
        } else {
          toggle(node, "warn", false);
          if (!p.error) title += " Click for the history.";
        }
      }
      attr(node, "title", title);
    });
}

/* What it has cost, against what (#211).

   `premium_requests` has been on every row since #94 and was rendered nowhere; the dashboard's own
   documentation said cost and budget were "a strip in #101", and #101 closed without one. This is
   that strip, as a fifth cell beside the four the project is polled for -- and never colour alone:
   amber and red each carry the sentence that explains them. */
function drawSpendCell(cell, row) {
  var s = row.spend;
  if (!s) return;
  var bits = [s.total + " premium"];
  if (s.budget) bits.push("of " + s.budget);
  if (s.turns) bits.push(s.turns + (s.turns === 1 ? " turn" : " turns"));
  var model = shortModel(row.actual || row.model);
  if (model) bits.push(model);

  setClass(cell, "cell spend");
  text(cell.querySelector(".val"), bits.join(" · "));
  var said = "this session " + s.session + " · today " + s.today +
             (s.sessions > 1 ? " · " + s.sessions + " sessions" : "");
  toggle(cell, "over", false);
  toggle(cell, "warn", false);
  if (s.budget && s.total >= s.budget) {
    toggle(cell, "over", true);
    // The supervisor's own sentence, so the cell and the refusal say one thing.
    said = row.repo + " has spent " + s.total + " of its " + s.budget +
           " premium-request budget — the next reply is refused until you raise it or press " +
           "Send anyway. " + said;
  } else if (s.budget && s.total >= s.budget * 0.8) {
    toggle(cell, "warn", true);
    var left = s.rate ? Math.max(0, Math.floor((s.budget - s.total) / s.rate)) : 0;
    said = s.total + " of " + s.budget + " — about " + left +
           " more turn" + (left === 1 ? "" : "s") + " at the MEAN of " + s.rate +
           " a turn, which is a mean and not a forecast. " + said;
  }
  attr(cell, "title", said);
}

/* ------------------------------------------------------------- the branches pane (#184)
   Read on the click, cached for the git interval, never on the poll. */
var branchesFor = {};                                   // repo -> the last /api/branches answer
var branchesWanted = "";                                // the repo whose pane was just asked for

function openBranches(name) {
  branchesWanted = name;
  choose(name).then(function () {
    section("inspector", true);
    loadBranches(name);
  });
}

function loadBranches(name, force) {
  branchesFor[name] = { ok: true, reading: true, branches: [] };
  drawInspector(name);
  return fetch(q("/api/branches", force ? { repo: name, refresh: "1" } : { repo: name })).then(function (r) {
    return r.json();
  }).then(function (answer) {
    branchesFor[name] = answer || { ok: false, error: "no answer" };
    if (desk.desk.selected === name) drawInspector(name);
    return answer;
  }).catch(function (e) {
    branchesFor[name] = { ok: false, error: String(e), branches: [] };
    if (desk.desk.selected === name) drawInspector(name);
  });
}

function mk(tag, cls, str) {
  var n = document.createElement(tag);
  if (cls) setClass(n, cls);
  if (str != null) text(n, str);
  return n;
}

function branchesPane(name) {
  var answer = branchesFor[name];
  var box = mk("div", "branches");
  var head = mk("div", "branches-head", "");
  head.appendChild(mk("strong", "", "branches"));
  var read = mk("button", "branches-read", "read");
  read.type = "button";
  read.addEventListener("click", function () { loadBranches(name, true); });
  head.appendChild(read);
  box.appendChild(head);
  if (!answer) {
    box.appendChild(mk("p", "muted", "every local branch, and which never reached the default: click the git cell, or read."));
    return box;
  }
  if (answer.reading) { box.appendChild(mk("p", "muted branches-note", "reading…")); return box; }
  if (!answer.ok) {
    box.appendChild(mk("p", "branches-note err", (answer.error || "git could not be asked") + (answer.hint ? " — " + answer.hint : "")));
    return box;
  }
  var current = (answer.branches || []).filter(function (b) { return b.current; })[0];
  box.appendChild(mk("p", "branches-sum" + (answer.warn ? " warn" : ""),
    answer.count + (answer.count === 1 ? " branch" : " branches") + " · " +
    (answer.unmerged ? answer.unmerged + " never reached " : "all reached ") + answer.default +
    " · on " + answer.current +
    (current && current.unmerged && current.ahead != null ? " (+" + current.ahead + " ahead of " + answer.default + ")" : "") +
    (answer.cached ? " · read " + age(Math.round(answer.age_s)) + " ago" : "")));
  if (answer.carry_line) box.appendChild(mk("p", "branches-carry", answer.carry_line));
  var list = mk("ol", "branchlist");
  (answer.branches || []).forEach(function (b) {
    var li = mk("li", "branchrow" + (b.unmerged ? " unmerged" : "") + (b.current ? " current" : "") +
                      (answer.ticket && b.ticket === answer.ticket ? " carries" : ""));
    li.appendChild(mk("span", "bname", b.name));
    var bits = [b.sha, b.age_s ? age(Math.round(b.age_s)) : ""];
    if (b.unmerged) bits.push(b.ahead != null ? "+" + b.ahead + " ahead" : "never reached " + answer.default);
    bits.push(b.upstream ? b.upstream + (b.track ? " " + b.track : "") : "none pushed");
    if (b.ticket) bits.push(b.ticket);
    if (b.current) bits.push("current");
    li.appendChild(mk("span", "bmeta", bits.filter(Boolean).join("  ·  ")));
    list.appendChild(li);
  });
  box.appendChild(list);
  if (answer.more) box.appendChild(mk("p", "muted branches-note", "and more: the count stops at twenty unmerged branches, which is the finding"));
  if ((answer.commits || []).length) {
    box.appendChild(mk("div", "muted", "the last " + answer.commits.length + " commits on " + answer.current));
    box.appendChild(mk("pre", "commits", answer.commits.join("\n")));
  }
  return box;
}

/* The selected project's spend, in the inspector: what it has cost, by session and by day. A tile
   is the AGENT and the inspector is the PROJECT (#148), and "what has this cost me" is a question
   about the project -- which is why the number is a cell on the tile and the breakdown is here. */
function spendPane(name) {
  var entry = tiles.get(name);
  var row = (entry && entry.row) || {};
  var s = row.spend;
  if (!s || (!s.total && !s.budget)) return null;

  var box = mk("div", "branches spendpane");
  var head = mk("div", "branches-head", "");
  head.appendChild(mk("strong", "", "spend"));
  head.appendChild(mk("span", "muted", "premium requests"));
  box.appendChild(head);

  var line = s.total + " all time · " + s.today + " today · " + s.session + " this session";
  if (s.budget) line += " · of " + s.budget;
  var sum = mk("p", "branches-sum" + (s.budget && s.total >= s.budget ? " warn" : ""), line);
  box.appendChild(sum);
  box.appendChild(mk("p", "muted",
    s.turns + (s.turns === 1 ? " turn" : " turns") +
    (s.rate ? ", a mean of " + s.rate + " a turn — a mean, not a forecast" : "") +
    (s.sessions > 1 ? " · " + s.sessions + " sessions" : "")));
  box.appendChild(mk("p", "muted", "`ad-fleet spend " + name +
                                   "` prints this, and `--rebuild` checks it against every log"));
  return box;
}

function clip(value) {
  try {
    if (navigator.clipboard) return navigator.clipboard.writeText(value);
  } catch (e) { /* Simple Browser has no clipboard permission; fall through */ }
  var box = document.createElement("textarea");
  box.value = value;
  document.body.appendChild(box);
  box.select();
  try { document.execCommand("copy"); } catch (e) { /* nothing else to try */ }
  document.body.removeChild(box);
}

/* ------------------------------------------------------------------ the Downloads inbox (#132) */

function offerRow(row, repo) {
  var li = document.createElement("li");
  var nm = document.createElement("span");
  setClass(nm, "nm");
  text(nm, row.name);
  attr(nm, "title", row.path + "\n" + row.reason);
  var meta = document.createElement("span");
  setClass(meta, "meta");
  text(meta, kb(row.size) + "  ·  " + age(Math.round(row.age_s)));
  li.appendChild(nm);
  li.appendChild(meta);

  if (row.offered) {
    var where = null;
    if (!repo) {
      // Unsorted: the operator picks the project. Nothing is guessed -- two repos that match the
      // name equally well is exactly why this tray exists.
      where = document.createElement("select");
      Array.from(tiles.keys()).forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        text(option, name);
        where.appendChild(option);
      });
      li.appendChild(where);
    }
    var attach = document.createElement("button");
    text(attach, "attach");
    attr(attach, "title", "copy it into that repo's .agent/in/<KEY>/ and leave the original here");
    attach.addEventListener("click", function (e) {
      e.stopPropagation();
      var target = repo || (where && where.value);
      if (!target) return;
      post("attach", { id: row.id, repo: target }).then(function (r) {
        var d = (r && r.data) ? r.data : r;
        var attached = r ? (r.attached !== undefined ? r.attached : (d && d.attached)) : false;
        var dir = r ? (r.dir || (d && d.dir) || "") : "";
        var why = r ? (r.why || (d && d.why) || "") : "";
        text(meta, r && r.ok ? (attached ? "attached → " + dir : (why || "already there"))
                        : (r ? (r.error || "refused") : "refused"));
        loadDesk();
      });
    });
    li.appendChild(attach);
  } else {
    var why = document.createElement("span");
    setClass(why, "why");
    text(why, row.reason);
    li.appendChild(why);
  }

  var no = document.createElement("button");
  text(no, "dismiss");
  attr(no, "title", "stop offering this file; a newer save of the same name comes back");
  no.addEventListener("click", function (e) {
    e.stopPropagation();
    post("dismiss", { id: row.id }).then(function () { loadDesk(); });
  });
  li.appendChild(no);
  return li;
}

function kb(bytes) {
  var n = Number(bytes) || 0;
  if (n < 1024) return n + " B";
  if (n < 1048576) return Math.round(n / 1024) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

function drawTray() {
  var loose = document.getElementById("loose");
  while (loose.firstChild) loose.removeChild(loose.firstChild);
  (desk.unsorted || []).forEach(function (row) { loose.appendChild(offerRow(row, "")); });
  hide(document.getElementById("noloose"), (desk.unsorted || []).length > 0);

  var rows = document.getElementById("refusedrows");
  while (rows.firstChild) rows.removeChild(rows.firstChild);
  (desk.not_offered || []).concat(desk.still_writing || []).forEach(function (row) {
    var li = document.createElement("li");
    var nm = document.createElement("span");
    setClass(nm, "nm");
    text(nm, row.name);
    var why = document.createElement("span");
    setClass(why, "why");
    text(why, row.reason);
    li.appendChild(nm);
    li.appendChild(why);
    rows.appendChild(li);
  });
  text(document.getElementById("folders"), (desk.folders || []).join("  ·  "));
}

function trayPanel(open) { return section("unsorted", open); }

document.getElementById("closetray").addEventListener("click", function () { trayPanel(false); });

/* ------------------------------------------------------------------------- where (#130), search */

/* The catalogue answers "which project owns Velocity" without opening a tab. It is the same
   `Catalogue.where` the CLI verb calls, and it reads only what each repo publishes -- no source,
   no notebooks, no exports, and nothing that was never indexed. */
function drawHits(data) {
  var list = document.getElementById("hits");
  while (list.firstChild) list.removeChild(list.firstChild);
  (data.results || []).forEach(function (hit) {
    var li = document.createElement("li");
    var p = document.createElement("span");
    setClass(p, "p");
    text(p, hit.project);
    var kind = document.createElement("span");
    setClass(kind, "kind");
    text(kind, hit.kind);
    var snip = document.createElement("span");
    setClass(snip, "snip");
    text(snip, (hit.title ? hit.title + " — " : "") + hit.snippet);
    li.appendChild(p);
    li.appendChild(kind);
    li.appendChild(snip);
    li.addEventListener("click", function () {
      choose(hit.project);
      foundPanel(false);
    });
    list.appendChild(li);
  });
  text(document.getElementById("foundhow"),
       data.ok ? ((data.results || []).length + " projects · " + (data.fts ? "fts5" : "like"))
               : (data.error + (data.hint ? " — " + data.hint : "")));
  hide(document.getElementById("nohits"), (data.results || []).length > 0);
}

var findSoon = (function () {
  var timer = null;
  return function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var needle = /** @type {HTMLInputElement} */ (document.getElementById("find")).value.trim();
      if (!needle) return foundPanel(false);
      foundPanel(true);
      fetch(q("/api/where", { q: needle, limit: 20 })).then(function (r) { return r.json(); })
        .then(drawHits).catch(function () { /* search is a convenience; the tiles are the truth */ });
    }, 250);
  };
})();

function foundPanel(open) { return section("found", !!open); }

document.getElementById("find").addEventListener("input", findSoon);
document.getElementById("closefound").addEventListener("click", function () { foundPanel(false); });

/* ---------------------------------------------------------------- the shared selection (#133) */

/* One selected project, shared by every window on this server. It is a POST and not a URL fragment
   because the point is that the *other* windows hear about it: clicking a tile on the left monitor
   is what changes the inspector on the centre one. */
/* The desk state is merged, never replaced. `/api/select` once answered with the selection alone
   and said nothing about the arrangement, so assigning its answer wholesale dropped `arrangement`
   on the floor: clicking any tile un-widened every tile you had widened and unpinned every tile
   you had pinned, until the next `/api/desk` poll fifteen seconds later put them back. */
/* #219: an answer that is older than what this page already has is not an answer, it is an echo.
   Five gestures in a second is five posts in flight, and they do not come back in the order they
   went: a resize answered after the move that followed it put the tiles back in the order they
   were in before the move. The desk carries a `version` that only ever rises, so the check is one
   comparison and the losing answer is simply dropped -- the winning one already describes the
   same arrangement. `selected` has no version of its own and is set locally, so it is merged
   either way. */
/** @param {DeskAnswer} answer */
function mergeDesk(answer) {
  if (!answer) return;
  var next = Object.assign({}, desk.desk);
  var stale = answer.version !== undefined && desk.desk.version !== undefined &&
              Number(answer.version) < Number(desk.desk.version);
  ["selected", "version", "arrangement"].forEach(function (k) {
    if (answer[k] === undefined) return;
    if (stale && k !== "selected") return;
    next[k] = answer[k];
  });
  desk.desk = next;
}

/** @param {string} name  @returns {Promise<void>} */
function choose(name) {
  if (desk.desk.selected === name) {
    drawInspector(name);
    return Promise.resolve();
  }
  mergeDesk({ selected: name });
  place();
  drawInspector(name);
  return post("select", { repo: name }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    place();
    drawInspector(name);
  });
}

/* The selected project's own detail, in one place instead of repeated inside every tile: a tile is
   the AGENT, the inspector is the PROJECT (#148). Visibility belongs to the sidebar, not here --
   this only draws, so a redraw can never reopen a panel the operator just closed. */
function drawInspector(name) {
  var el = document.getElementById("inspector");
  if (!el) return;
  var body0 = document.getElementById("inspectordetails");
  if (!name || !tiles.has(name)) {
    text(document.getElementById("inspectorrepo"), "");
    while (body0.firstChild) body0.removeChild(body0.firstChild);
    return;
  }
  text(document.getElementById("inspectorrepo"), name);
  var body = document.getElementById("inspectordetails");
  while (body.firstChild) body.removeChild(body.firstChild);

  var p = desk.projects[name] || {};
  var facts = document.createElement("div");
  setClass(facts, "facts");
  /* The ONE place on this page that renders a fact block, and it stays one on purpose.
     `serve.tile_facts()` narrows `catalogue.LINK_FACTS` before any of it leaves the server,
     because a fact block is hand-edited prose and a real one carries a warehouse hostname, a
     `\\share\dpm\runs` path and a service account beside the Jira keys. A second loop over some
     other payload's facts is how that filter gets bypassed by a change that looks like a feature.
     If a panel ever needs a fact this loop does not show, widen `LINK_FACTS`; do not add a loop. */
  var pairs = [
    ["project", name],
    ["path", p.path || "—"],
    ["branch", p.branch || "—"],
    ["jira", p.jira_project || "—"]
  ];
  var factsFromCatalogue = p.facts || {};
  Object.keys(factsFromCatalogue).forEach(function (k) {
    if (k !== "jira_project") pairs.push([k, factsFromCatalogue[k]]);
  });
  pairs.push(["indexed", p.indexed ? (p.last_indexed || "yes") : "not yet"]);
  pairs.forEach(function (row) {
    var k = document.createElement("span");
    setClass(k, "k");
    text(k, row[0]);
    var v = document.createElement("span");
    setClass(v, "v");
    text(v, row[1]);
    facts.appendChild(k);
    facts.appendChild(v);
  });
  body.appendChild(facts);

  // What is missing is named, so the operator knows which AGENTS.md key would fill the rail.
  var missing = p.missing_keys || [];
  if (missing.length) {
    var gap = document.createElement("p");
    setClass(gap, "muted");
    text(gap, "add to AGENTS.md for the rest of the rail: " + missing.join(", "));
    body.appendChild(gap);
  }

  // Open friction, and the models and reports the catalogue knows about.
  (p.friction || []).forEach(function (f) {
    var li = document.createElement("p");
    setClass(li, "frictionrow");
    text(li, [f.date, f.type, f.title].filter(Boolean).join("  ·  ") + (f.unblock ? "\n" + f.unblock : ""));
    body.appendChild(li);
  });

  // Where this project lives -- the link rail, so a tab is opened to act and never to check.
  var links = (p.links || []);
  if (links.length || p.path) {
    var rail = document.createElement("div");
    setClass(rail, "rail");
    links.forEach(function (row) {
      if (!row.url) return;
      var a = document.createElement("a");
      setClass(a, row.kind);
      a.href = row.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      attr(a, "title", row.url);
      text(a, row.name);
      rail.appendChild(a);
    });
    if (p.path) {
      var copy = document.createElement("button");
      text(copy, "copy path");
      attr(copy, "title", p.path);
      copy.addEventListener("click", function () {
        clip(p.path);
        text(copy, "copied");
        setTimeout(function () { text(copy, "copy path"); }, 1200);
      });
      rail.appendChild(copy);
    }
    body.appendChild(rail);
  }

  // What this agent has cost (#212): its sessions, its days, and the budget it is against. The
  // same ledger `ad-fleet spend` prints, so the page and the CLI cannot disagree.
  var spent = spendPane(name);
  if (spent) body.appendChild(spent);

  // The checkout's branches (#184): drawn from the last read, read on the click.
  body.appendChild(branchesPane(name));

  // The newest thing the project's own agent verified, beside the report link.
  var latest = ((p.verify || {}).latest) || {};
  if (latest.name) {
    var h = document.createElement("div");
    setClass(h, "muted");
    text(h, "verify · " + (latest.tool || "") + " · " + latest.name +
            (latest.age_s != null ? " · " + age(Math.round(latest.age_s)) : ""));
    var pre = document.createElement("pre");
    setClass(pre, "verifybody");
    text(pre, latest.excerpt || "");
    body.appendChild(h);
    body.appendChild(pre);
  }

  var offers = (desk.offers || {})[name] || [];
  if (offers.length) {
    var head = document.createElement("div");
    setClass(head, "muted");
    text(head, "Downloads is offering " + offers.length + " file" + (offers.length === 1 ? "" : "s"));
    var list = document.createElement("ol");
    setClass(list, "tray");
    offers.forEach(function (row) { list.appendChild(offerRow(row, name)); });
    body.appendChild(head);
    body.appendChild(list);
  }
}

document.getElementById("closeinspector").addEventListener("click", function () {
  section("inspector", false);
});

/* The desk's one arrangement (#232) -- and a real object, not a copy of one.

   It used to answer `{order: [], size: {}, pinned: []}` when the desk had not arrived yet, which
   reads as harmless and is not: every optimistic write in `arrangeNow` mutates what it is given,
   so before the first desk frame landed a hide, a move, a pin and a resize all wrote into a
   throwaway and the tile did not move until the server answered. That is precisely the thing
   #219 claims the page no longer does, and on a fast machine the desk has loaded before anyone
   can click, so it only showed up on the slowest runner in CI. The record is created on the desk
   instead; `mergeDesk` replaces it with the server's the moment one arrives. */
/** @returns {Arrangement} */
function getArrangement() {
  if (!desk.desk) desk.desk = {};
  if (!desk.desk.arrangement) {
    desk.desk.arrangement = { order: [], size: {}, pinned: [], hidden: [] };
  }
  return desk.desk.arrangement;
}

/** @returns {string[]} */
function getEffectiveOrder() {
  var curArr = getArrangement();
  var pinned = curArr.pinned || [];
  var order = (curArr.order || []).filter(function (n) { return tiles.has(n); });
  Array.from(tiles.keys()).forEach(function (n) {
    if (order.indexOf(n) < 0) order.push(n);
  });
  var result = [];
  pinned.forEach(function (p) { if (tiles.has(p)) result.push(p); });
  order.forEach(function (o) { if (result.indexOf(o) < 0) result.push(o); });
  return result;
}

/* Hidden, and never hiding what needs a person (#173).

   A hidden tile keeps its slot in `order`, so reopening puts it back where it was. The one rule
   that overrides the operator's own choice is the fold's: a tile that needs somebody is on the
   glass whatever the arrangement says, because hiding a demand is how a demand gets missed. */
/** @param {string} name */
function isHidden(name) {
  var entry = tiles.get(name);
  if (entry && entry.el.classList.contains("needs-human")) return false;
  return ((getArrangement().hidden) || []).indexOf(name) >= 0;
}

/** @returns {string[]} */
function visibleOrder() {
  return getEffectiveOrder().filter(function (n) { return !isHidden(n); });
}

/* #219. Every arrangement change goes the same way: paint it, post it, and put it back with the
   server's own words on the notice line if it refuses. The paint is inside the frame the gesture
   happened in -- a page that waits for a round trip before moving a tile is a page that feels
   like a form, whatever the round trip costs -- and the `desk` frame that follows is what makes
   every other window agree.

   `patch` is what to send; `apply` writes it into the local arrangement and answers with a
   function that writes the old one back. */
/* The arrangement's writes, one at a time and in the order they were made -- the rule #230 gave
   the window's (#233). Two resize keys pressed together were two posts in flight at once, each
   carrying the whole footprint as it stood at its press; the server applied them in whatever
   order its threads took the lock, and the older footprint could land last and come back on the
   next frame. While any is in flight the page's own arrangement is the one it keeps: an answer
   or a frame from before the last press describes a desk the operator has already left. */
var arrangeWrites = 0;
/** @type {Promise<DeskAnswer | void>} */
var arrangeChain = Promise.resolve();

/** @param {Arrangement} patch  what to post
 *  @param {() => (() => void) | void} apply  writes it into the page's arrangement, and answers
 *                                          with what puts the old one back
 *  @param {string} [what]  the gesture's name, for its timing mark (#219)
 *  @returns {Promise<DeskAnswer | void>} */
function arrangeNow(patch, apply, what) {
  var mark = gesture("arrange:" + (what || "change"));
  var undo = apply();
  transitionMove(function () { place(); });
  settle(mark);
  arrangeWrites += 1;
  arrangeChain = arrangeChain.then(function () {
    return post("arrange", patch).then(function (r) {
      if (r && r.ok) {
        if (arrangeWrites === 1) { mergeDesk(r); place(); }   // the last one's answer is the desk
        return r;
      }
      // Refused. The arrangement goes back to what it was and the refusal is said out loud,
      // because a tile that silently returns to where it was is a page the operator stops trusting.
      if (undo) undo();
      place();
      var why = (r && r.error) || "the server refused that arrangement";
      say(why + ((r && r.hint) ? " — " + r.hint : ""), 10);
      return r;
    }).catch(function (e) {
      if (undo) undo();
      place();
      say(String(e), 10);
    });
  }).then(function (r) {
    arrangeWrites -= 1;
    return r;
  });
  return arrangeChain;
}

/** @param {string} name  @param {boolean} hide */
function setHidden(name, hide) {
  var curArr = getArrangement();
  var was = (curArr.hidden || []).slice();
  var next = was.slice();
  var at = next.indexOf(name);
  if (hide && at < 0) next.push(name);
  if (!hide && at >= 0) next.splice(at, 1);
  return arrangeNow({ hidden: next }, function () {
    curArr.hidden = next;
    return function () { curArr.hidden = was; };
  }, hide ? "hide" : "show");
}

/* Moving an element with `appendChild` takes the focus off it -- so a grid that re-appends every
   tile on every draw (and the stream draws several times a second while an agent is talking) took
   the focus off the tile the operator had just selected, and Alt+arrow reached nothing. The order
   is therefore only touched when it is actually wrong, and the focus is put back when it is. */
function reorderDomTiles() {
  var grid = document.getElementById("grid");
  if (!grid) return;
  var order = getEffectiveOrder();
  var curArr = getArrangement();
  var pinned = curArr.pinned || [];
  // What is on the glass as a pane of its own: not hidden, and not folded into its project's rail.
  var shown = visibleOrder().filter(function (n) { return !groupedAway(n); });

  // #217: not while a tile is under the hand. A draw that reorders the DOM mid-drag is a tile
  // that jumps out from under the cursor, and the stream draws several times a second.
  if (dragging) return;

  var inDom = Array.prototype.map.call(grid.children, function (el) { return el.dataset.repo; });
  var needsMove = inDom.join("\u0000") !== order.filter(function (n) { return tiles.has(n); }).join("\u0000");
  var active = /** @type {HTMLElement} */ (document.activeElement);
  var refocus = needsMove && active && active.closest && active.closest(".tile") ? active : null;

  // FLIP, first half: where every tile is *now*, before the DOM moves. A tile that reorders by
  // `appendChild` alone teleports, and a grid reshuffling while agents talk reads as flicker, not
  // movement -- the operator cannot see it is the same tile, lower down. Measured only when
  // something is moving, and not at all when the viewer has asked for less of it.
  //
  // Nor when a pane has just arrived (#233). Panes are made in the order `/api/fleet` lists them
  // and then put in the arrangement's, and since every agent became a pane on the glass the first
  // of those moves was visible: the rails shuffled into place for a fifth of a second on every
  // load, and anything aimed at one in that time -- a click, a test's drag -- landed beside it.
  // Where a pane first appears is not a move the operator made.
  var first = (needsMove && !arrivedSinceLastPlace && !reduceMotion() && !inViewTransition)
    ? measureTiles() : null;
  arrivedSinceLastPlace = false;

  order.forEach(function (name, index) {
    var entry = tiles.get(name);
    if (entry && entry.el) {
      if (needsMove) grid.appendChild(entry.el);
      // Hidden is a class rather than `el.hidden`, so the tile keeps its slot in `order` and
      // reopening puts it back where it was rather than at the end.
      toggle(entry.el, "is-hidden", isHidden(name));
      // The number is the key that opens it, so it counts what is on the glass -- on the head and
      // on the rail alike, one writer for both.
      var at = shown.indexOf(name);
      text(entry.el.querySelector(".n"), at < 0 ? "" : String(at + 1));
      text(entry.el.querySelector(".pr-n"), at < 0 ? "" : String(at + 1));
      // The width is not written here: it is `paintWidths`', one owner (#234). #217's `--cols`,
      // `--rows` and `size-2` went with the span they described.
      var isPinned = pinned.indexOf(name) >= 0;
      toggle(entry.el, "is-pinned", isPinned);
      var pBtn = entry.el.querySelector(".pintoggle");
      if (pBtn) {
        toggle(pBtn, "active", isPinned);
        attr(pBtn, "aria-pressed", String(isPinned));
        attr(pBtn, "title", isPinned ? "unpin (Alt+Home)" : "pin this tile first (Alt+Home)");
      }
    }
  });
  if (first) playFlip(first);
  if (refocus) refocus.focus();
}

/* ------------------------------------------------------------------ moving tiles, visibly (#5) */

function reduceMotion() {
  return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

/* Only tiles that are actually laid out. One that is not open, or is put away, has a zero
   rect, and animating from nowhere to somewhere is a tile flying in from the corner of the screen
   for no reason the operator can see. */
function measureTiles() {
  var seen = new Map();
  tiles.forEach(function (entry, name) {
    var box = entry.el.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) seen.set(name, box);
  });
  return seen;
}

/* FLIP, second half: put each tile back where it was with a transform, then let it travel to where
   the DOM has already placed it. The layout is never animated -- only the paint -- so the grid is
   in its final state throughout, and a click during the movement lands on the tile the operator is
   aiming at rather than on wherever it used to be. */
function playFlip(first) {
  var moved = [];
  tiles.forEach(function (entry, name) {
    var was = first.get(name);
    if (!was) return;
    var now = entry.el.getBoundingClientRect();
    if (now.width <= 0) return;
    var dx = was.left - now.left;
    var dy = was.top - now.top;
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    toggle(entry.el, "flip", false);
    entry.el.style.transform = "translate(" + dx + "px, " + dy + "px)";
    moved.push(entry.el);
  });
  if (!moved.length) return;
  // Two frames, not one: the inverted transform has to be painted before the transition is armed,
  // or the browser coalesces the two styles and nothing moves at all.
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      moved.forEach(function (el) {
        toggle(el, "flip", true);
        el.style.transform = "";
      });
    });
  });
}

/* --------------------------------------------------- #217: the tile as a window, with a pointer */

/* Four pixels before anything moves. A click on the head selects the project, and a gesture that
   began reordering on the first pixel of travel made that click a drag on any trackpad. */
var DRAG_SLOP = 4;

/* True while a pointer drag is in flight, so `place()` can leave the order alone until the hand
   comes off -- a draw that reorders the DOM underneath a moving tile is a tile that jumps out
   from under the cursor. */
var dragging = null;

/* The `click` a pointer press ends in, taken off the page once: after a drag, and after a drag put
   down with `Esc`. It is dispatched in the same task as the `pointerup` that ends the press, so the
   listener takes itself off on the next turn whether or not a click came. */
function swallowNextClick() {
  var swallow = function (ev) {
    ev.stopPropagation();
    ev.preventDefault();
    document.removeEventListener("click", swallow, true);
  };
  document.addEventListener("click", swallow, true);
  setTimeout(function () { document.removeEventListener("click", swallow, true); }, 0);
}

/* Reorder by pointer, on a handle. `host` is what moves and `name` is what it is called: a pane
   passes itself and its head, and itself and its rail's face (#233). Both write the same `order`,
   because both are the same arrangement seen from two widths. */
function bindDragToReorder(handle, host, name) {
  handle.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    /* A press on a control inside the handle belongs to that control -- unless the handle *is*
       the control, which is what a rail's face is: one button filling the rail. The head is a
       plain `div`, so every button in it is somebody else's. */
    var ctrl = e.target.closest("button, input, select, textarea, a");
    if (ctrl && ctrl !== handle) return;
    var siblings = Array.prototype.filter.call(host.parentNode.children, function (n) {
      return n !== host && n.dataset && n.dataset.repo && !n.hidden;
    });
    if (!siblings.length) return;                // nothing to reorder past

    var from = { x: e.clientX, y: e.clientY };
    var started = false;
    var target = null;                           // { el, before } while one is lit
    /* The axis the list runs along is the axis the halves are measured on, or "before" means the
       wrong side of the wrong edge. Read from the list itself rather than from which kind of host
       this is: the row runs across (#233), and the column of bands it replaced ran down. */
    var down = getComputedStyle(host.parentNode).flexDirection === "column";

    /* The capture is taken when the drag begins, not when the pointer goes down. While an element
       holds the capture the browser retargets the compatibility mouse events to it as well, so
       capturing on `pointerdown` sent the `click` that ends an ordinary press to the head rather
       than to the repository name inside it -- and clicking the name, which is how a tile is
       opened, silently stopped working. */
    var lift = function () {
      started = true;
      dragging = name;
      // Belt as well as braces: a selection made anywhere else on the page is still a selection
      // the browser would rather drag than let this gesture have.
      try {
        var sel = window.getSelection();
        if (sel && !sel.isCollapsed) sel.removeAllRanges();
      } catch (err) { /* no selection to clear */ }
      toggle(host, "is-dragging", true);
      try { handle.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }
    };

    var clear = function () {
      dragging = null;
      toggle(host, "is-dragging", false);
      style(host, "transform", "");
      document.querySelectorAll(".drop-before, .drop-after").forEach(function (n) {
        n.classList.remove("drop-before", "drop-after");
      });
      target = null;
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onCancel);
      document.removeEventListener("keydown", onKey, true);
      try { handle.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
    };

    var onMove = function (ev) {
      var dx = ev.clientX - from.x;
      var dy = ev.clientY - from.y;
      if (!started && Math.abs(dx) + Math.abs(dy) < DRAG_SLOP) return;
      if (!started) lift();
      style(host, "transform", "translate(" + dx + "px, " + dy + "px)");

      // The dragged host has no pointer events while it is lifted, so this answers with whatever
      // is underneath it rather than with itself.
      var under = document.elementFromPoint(ev.clientX, ev.clientY);
      var over = under && under.closest ? under.closest("[data-repo]") : null;
      if (over === host) over = null;
      document.querySelectorAll(".drop-before, .drop-after").forEach(function (n) {
        n.classList.remove("drop-before", "drop-after");
      });
      if (over && over.parentNode === host.parentNode) {
        var box = over.getBoundingClientRect();
        var before = down ? (ev.clientY - box.top) < (box.height / 2)
                          : (ev.clientX - box.left) < (box.width / 2);
        toggle(over, before ? "drop-before" : "drop-after", true);
        target = { el: over, before: before };
      } else {
        target = null;
      }
    };

    var onUp = function () {
      var landed = target;
      var moved = started;
      clear();
      if (!moved) return;
      // A pointer drag still ends in a `click`, and on a head that click selects the project
      // while on a rail it opens the agent. Neither is what the hand just asked for, so the one
      // that follows a real drag is swallowed.
      swallowNextClick();
      if (landed) dropTileBefore(name, landed.el.dataset.repo, landed.before);
    };

    // Esc cancels a drag in flight and leaves the order alone (HIG *Drag and drop*). Captured on
    // the document, because the capture has taken the keyboard's usual route away.
    //
    // The button is still down when Esc is pressed, and the release that follows is not a click
    // on what was being dragged either. It was taken for one: Chromium sends the `click` that ends
    // a captured press to the handle, and on a rail's face that opened the agent the operator had
    // just put down (#233). So the click after this press is swallowed as well.
    var onKey = function (ev) {
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      ev.preventDefault();
      clear();
      var released = function () {
        document.removeEventListener("pointerup", released, true);
        document.removeEventListener("pointercancel", released, true);
        swallowNextClick();
      };
      document.addEventListener("pointerup", released, true);
      document.addEventListener("pointercancel", released, true);
    };
    var onCancel = function () { clear(); };

    /* On the document, not on the handle. A head is twenty pixels tall and the pointer is off it
       before it has travelled far enough to count as a drag, so a handle that listened to itself
       heard the first move and none of the others -- and the capture that would have fixed that
       is not taken until the drag has begun, which it never did. */
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onCancel);
    document.addEventListener("keydown", onKey, true);
  });
}

/* A reorder never changes which agent is open (#233). Until something opens one, the open agent
   is only "the first in the order" -- and in the row a rail can be dropped before the open pane,
   or the open pane carried past a rail, so the reorder itself would change what is first and open
   a different agent under the hand. The one on the glass is written down before the order moves:
   here, and in this window's record, so a reload opens it too. */
function holdOpen() {
  if (openTile) return;
  var one = openName();
  if (!one) return;
  openTile = one;
  saveWindow({ open: one });
}

/* Where a drop lands, in one place, so the pointer and the keyboard agree about what "before"
   means. Optimistic: the order changes under the hand and the server's answer is what the next
   draw reads. */
function dropTileBefore(name, onto, before) {
  if (!name || !onto || name === onto) return;
  holdOpen();
  var order = getEffectiveOrder();
  var from = order.indexOf(name);
  if (from >= 0) order.splice(from, 1);
  var at = order.indexOf(onto);
  if (at < 0) return;
  order.splice(before ? at : at + 1, 0, name);
  var arr = getArrangement();
  var was = (arr.order || []).slice();
  arrangeNow({ order: order }, function () {
    arr.order = order;
    return function () { arr.order = was; };
  }, "drop");
}

/* ------------------------------------------------- #216: one door for anything that moves things */

/* True only while the browser is running a view transition of its own, which is the one time
   `reorderDomTiles` must *not* also play FLIP: two animations of the same move is a tile that
   arrives, leaves and arrives again. */
var inViewTransition = false;

/* A view transition matches the old state to the new one by name, so the name has to be the same
   name for the same tile on both sides of the change -- an index would make "the third tile"
   morph into whatever is third afterwards, which is the opposite of the point. Registry names are
   already close to a CSS identifier; anything else in one becomes a dash. Two repositories that
   sanitise to one name make the browser skip the transition and apply the change with no
   animation, which is a degradation rather than a break. */
function tileTransitionName(name) {
  return "tile-" + String(name).replace(/[^A-Za-z0-9_-]/g, "-");
}

function nameTiles(on) {
  tiles.forEach(function (entry, name) {
    style(entry.el, "view-transition-name", on ? tileTransitionName(name) : "");
  });
}

/* Every change to where things are goes through here: opening a pane, going back, hiding a tile,
   reordering the row. `startViewTransition` is the good path -- the browser holds the old frame,
   applies the change and morphs between the two, so the layout is never in a half-state -- and
   FLIP is the fallback for engines that do not have it, which is every engine the IDE shells ship
   until they catch up with Chromium. Reduced motion takes neither: the change is applied and that
   is the end of it.

   `fn` must do the whole change synchronously. Anything asynchronous inside it happens after the
   browser has already taken its "after" snapshot, and a morph to a state that has not arrived yet
   is a flash of the wrong layout. */
/* Rearranging is FLIP, always -- never a view transition. The distinction is not taste: FLIP
   moves the very elements, so the change is in the DOM on the frame the gesture happened in and
   the animation is a transform on top of it; `startViewTransition` morphs *pictures*, so it has
   to hold the old frame for one more frame while it takes its snapshot. For "this tile is now
   over there" the first is both faster to show and truer -- and #219's whole claim is that the
   desk paints what it already knows without waiting for anything, the browser included. */
function transitionMove(fn) {
  if (reduceMotion()) { fn(); return; }
  var first = measureTiles();
  fn();
  playFlip(first);
}

function transitionLayout(fn) {
  if (reduceMotion() || typeof document.startViewTransition !== "function") {
    var first = reduceMotion() ? null : measureTiles();
    fn();
    if (first) playFlip(first);
    return;
  }
  nameTiles(true);
  inViewTransition = true;
  var done = function () { inViewTransition = false; nameTiles(false); };
  var running;
  try {
    running = document.startViewTransition(function () {
      /* Reported, and then let the transition finish. A change that half-applied is still the
         state the page is in, and aborting the transition on top of that leaves the old frame
         painted over the new one -- a page that looks fine and is not. */
      try {
        fn();
      } catch (bad) {
        if (typeof reportError === "function") reportError(bad);
        else setTimeout(function () { throw bad; });
      }
    });
  } catch (err) {
    // A transition already running, or an engine that has the function and refuses the call: the
    // change still has to happen, and it happens now.
    done();
    fn();
    return;
  }
  /* A `ViewTransition` carries three promises and a superseded one rejects all of them. That is
     not three pieces of news, it is one: the operator made a second gesture before the first had
     finished animating, which is the most ordinary thing on this page. `finished` is the one that
     is acted on; the other two are caught so that the second gesture is not an *unhandled*
     rejection -- which reaches the console as `Transition was skipped. New ViewTransition
     started`, and reached a browser test as a page error on the slower of the two CI runners. */
  if (running.updateCallbackDone) running.updateCallbackDone.catch(function () {});
  if (running.ready) running.ready.catch(function () {});
  running.finished.then(done, done);
}

/* Pinned tiles come first, always -- so a move has to happen inside the block the tile is in.
   Reordering the flattened list and posting that did nothing whenever anything was pinned:
   `getEffectiveOrder` puts the pinned names back in front on the very next draw, and the move the
   operator just made was silently undone. */
function moveTile(repo, dir) {
  var arr = getArrangement();
  var pinned = (arr.pinned || []).filter(function (n) { return tiles.has(n); });
  var inPinnedBlock = pinned.indexOf(repo) >= 0;
  var block = inPinnedBlock
    ? pinned
    : getEffectiveOrder().filter(function (n) { return pinned.indexOf(n) < 0; });

  var idx = block.indexOf(repo);
  if (idx < 0) return;
  // One press, one *visible* slot. A hidden tile keeps its place in `order` -- that is how
  // reopening puts it back where it was -- so stepping by one index swapped the tile with
  // something nobody can see, and the key read as having done nothing at all (#173).
  var target = idx + dir;
  while (target >= 0 && target < block.length && isHidden(block[target])) target += dir;
  if (target < 0 || target >= block.length) return;
  holdOpen();
  block.splice(idx, 1);
  block.splice(target, 0, repo);

  var body = {};
  if (inPinnedBlock) body.pinned = block; else body.order = block;
  var wasPinned = (arr.pinned || []).slice();
  var wasOrder = (arr.order || []).slice();
  arrangeNow(body, function () {
    if (inPinnedBlock) arr.pinned = block; else arr.order = block;
    return function () { arr.pinned = wasPinned; arr.order = wasOrder; };
  }, "move");
}

/* The pin writes the local arrangement BEFORE the round trip, not only after it. Reading
   `desk.desk` and posting without updating it meant two quick clicks both read the same state and
   the second overwrote the first: pin two tiles in a second and one of them silently came back
   unpinned. The returned promise is what lets a caller sequence them.

   A pin is the order's "first" (`Alt+Home`). Until a window has widths of its own it is also open
   beside the open pane, as it was in the column; once it has, what is wide is what the widths say
   (#234) -- plan-panes' *Pin retires*: a pane that stays wide because it was dragged wide is the
   same thing, drawn by the hand instead of a button. */
function toggleTilePin(repo) {
  var curArr = getArrangement();
  var pinned = (curArr.pinned || []).slice();
  var idx = pinned.indexOf(repo);
  if (idx >= 0) pinned.splice(idx, 1); else pinned.push(repo);
  var was = (curArr.pinned || []).slice();
  return arrangeNow({ pinned: pinned }, function () {
    curArr.pinned = pinned;
    return function () { curArr.pinned = was; };
  }, "pin");
}

/* ------------------------------------------------------- hide, refresh and the model (#205)

   The same three, in the same order, with the same keys, on every pane. The operator's sentence
   was *active and inactive both*, and a control that exists in one place and not the other is what
   this slice was asked to stop. A pane with a head carries them as buttons; a rail, which has no
   room for a head, keeps the keys (#233). */

/* The model name, short enough for a 28px button. Never a closed list -- which names this build
   accepts has never been measured -- so this only shortens what it is given. */
function shortModel(name) {
  var value = String(name || "").trim();
  if (!value) return "auto";
  return value.replace(/^claude-/, "").replace(/-\d{8}$/, "");
}

/* What the model button says when you hover it: what this agent is actually running, and what it
   was configured to run. Written once, and the model card reads the same two facts. */
function modelTitle(row) {
  row = row || {};
  return "runs " + (row.actual || row.model || "whatever the CLI picks") +
         (row.model ? " · configured " + row.model + " (" + (row.model_source || "") + ")"
                    : " · no --model flag is passed") + " — press m";
}

/* Read what the next tick would read, now. It spends NO premium request: nothing is sent to the
   agent, the stream is re-folded from disk and the four cells are the poll's own reads. The button
   says so while it is in flight by being the thing that is busy -- no overlay, no spinner. */
function doRefresh(repo, button) {
  if (!repo) return Promise.resolve();
  if (button) { disable(button, true); attr(button, "aria-busy", "true"); }
  return post("refresh", { repo: repo }).then(function (r) {
    if (r && !r.ok) say(r.error + (r.hint ? " — " + r.hint : ""));
    else refresh();
    return r;
  }).catch(function (e) { say(String(e)); }).then(function (r) {
    if (button) { disable(button, false); button.removeAttribute("aria-busy"); }
    return r;
  });
}

/* The settings page's `seen` list and its efforts, fetched once and kept: they are suggestions on
   a free-text field, so a stale one costs nothing and a fetch per click costs a round trip. */
var modelChoices = null;

function loadModelChoices() {
  if (modelChoices) return Promise.resolve(modelChoices);
  return fetch(q("/api/settings")).then(function (r) { return r.json(); })
    .then(function (data) {
      modelChoices = (data && data.model) || { seen: [], efforts: [] };
      return modelChoices;
    }).catch(function () { return { seen: [], efforts: [] }; });
}

function fillDatalist(id, values) {
  var list = document.getElementById(id);
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);
  (values || []).forEach(function (value) {
    var option = document.createElement("option");
    option.value = value;
    list.appendChild(option);
  });
}

/* Configured, and what the last turn actually ran on. Two facts, because a tenant may pin a model
   and a card that showed only what was asked for would be showing a value that is not what ran. */
function openModelCard(repo, anchor) {
  var card = document.getElementById("modelcard");
  var entry = tiles.get(repo);
  var row = (entry && entry.row) || {};
  if (!card) return;
  setData(card, "repo", repo);
  text(document.getElementById("mc-repo"), repo);
  text(document.getElementById("mc-configured"), row.model ? row.model : "the CLI chooses");
  text(document.getElementById("mc-source"), row.model_source || "cli-auto");
  text(document.getElementById("mc-actual"), row.actual || "no turn has run yet");
  text(document.getElementById("mc-actual-why"),
       row.actual && row.model && row.actual !== row.model ? "the tenant pinned it" : "");
  /** @type {HTMLInputElement} */ (document.getElementById("mc-model")).value = row.model || "";
  /** @type {HTMLInputElement} */ (document.getElementById("mc-effort")).value = row.effort || "";
  text(document.getElementById("mc-note"), "takes effect on the agent's next turn");
  var all = /** @type {HTMLAnchorElement} */ (document.getElementById("mc-all"));
  all.href = pageUrl("/settings") + "#model-" + encodeURIComponent(repo);

  loadModelChoices().then(function (choices) {
    fillDatalist("mc-models", choices.seen);
    fillDatalist("mc-efforts", choices.efforts);
  });

  hide(card, false);
  if (anchor && anchor.getBoundingClientRect) {
    var box = anchor.getBoundingClientRect();
    // `m` on a rail (#233): its model button is off the glass, so the card hangs off the rail.
    if (!box.width && anchor.closest && anchor.closest(".tile")) {
      box = anchor.closest(".tile").getBoundingClientRect();
    }
    var width = card.offsetWidth || 280;
    var height = card.offsetHeight || 240;
    /* Under the button when it fits; otherwise level with the top of what opened it -- a rail is
       the height of the window, and hanging the card off its foot put the card's save button
       below the glass. */
    var top = box.bottom + 6;
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, Math.min(box.top, window.innerHeight - height - 8));
    }
    card.style.top = top + "px";
    card.style.left = Math.max(8, Math.min(window.innerWidth - width - 8, box.left)) + "px";
  }
  document.getElementById("mc-model").focus();
}

function closeModelCard() {
  var card = document.getElementById("modelcard");
  if (card && !card.hidden) { hide(card, true); setData(card, "repo", ""); return true; }
  return false;
}

/* One writer for this setting: the same action, the same function and the same refusals the
   settings page gets, so two ways to set one thing do not become two rules about it. */
function saveModel() {
  var card = document.getElementById("modelcard");
  var repo = card.dataset.repo || "";
  if (!repo) return;
  var body = { models: [{ repo: repo,
                          model: /** @type {HTMLInputElement} */ (
                            document.getElementById("mc-model")).value.trim(),
                          effort: /** @type {HTMLInputElement} */ (
                            document.getElementById("mc-effort")).value.trim() }] };
  post("settings", body).then(function (r) {
    if (r && r.ok) {
      text(document.getElementById("mc-note"), "saved — it reaches the agent on its next turn");
      refresh();
      return;
    }
    text(document.getElementById("mc-note"), (r && r.error) + ((r && r.hint) ? " — " + r.hint : ""));
  });
}

/* One binder, bound once when the pane is made (#205). */
function bindTools(root, repo) {
  Array.prototype.forEach.call(root.querySelectorAll("[data-tool]"), function (button) {
    if (button.dataset.bound === "1") return;
    setData(button, "bound", "1");
    button.addEventListener("click", function (e) {
      e.stopPropagation();
      var what = button.dataset.tool;
      var name = (root.dataset && root.dataset.repo) || repo;
      if (what === "hide") setHidden(name, true);
      else if (what === "refresh") doRefresh(name, button);
      else if (what === "model") openModelCard(name, button);
    });
  });
}

/* ------------------------------------------------------------------------------ the row (#233) */

/* Which agent is open, decided once. The window's own choice wins; then, in a window with widths of
   its own (#234), the first pane those widths make wide; then the selection every window shares, so
   a fresh window opens on whatever the desk is already looking at; then the first pane. A hidden or
   departed name never wins -- an arrangement that opened onto nothing would be the blank window
   this layout exists to stop. */
/** @returns {string} */
function openName() {
  if (openTile && tiles.has(openTile) && !isHidden(openTile)) return openTile;
  var shown = visibleOrder();
  if (myWidths) {
    var wide = shown.filter(function (name) { return (myWidths[name] || 0) > 0; })[0];
    if (wide) return wide;
  }
  var sel = desk.desk.selected;
  if (sel && tiles.has(sel) && !isHidden(sel)) return sel;
  // A pinned agent is on the glass already, and `getEffectiveOrder` puts the pins first -- so
  // falling back to "the first one" would mean that pinning one agent silently stopped anything
  // else from ever being open. The default is the first agent that is NOT pinned.
  var pinned = (getArrangement().pinned) || [];
  var free = shown.filter(function (name) { return pinned.indexOf(name) < 0; });
  return free[0] || shown[0] || "";
}

/* The address says which agent is open, so a reload opens that one (#230). The column's own
   gestures never wrote it, and `followHash` on reload re-opened whichever agent the fragment still
   named -- the one before the click -- and saved it over the server's record too. */
/** @param {string} name */
function markTile(name) {
  if (name && location.hash !== "#tile=" + name) history.replaceState(null, "", "#tile=" + name);
}

/* Open one. It takes the width the open pane had, and that pane becomes a rail in its own slot --
   the column's swap, kept because it is the gesture the operator already has. Nothing moves along
   the row: the order is the operator's. What was open is remembered so `Esc` can go back. A pane
   that already has a width is not swapped -- pressing it only gives it the keys.

   In a window with widths of its own (#234) the swap is a write of them, in the same post as
   `open`: one gesture, one write. A window that has never been given widths draws the open pane
   and the pins wide by themselves, so there the swap is `open` alone, as it was.

   The pane that already has the keys is not swapped with itself: an address naming it -- the
   `#tile=` a reload answers, a toast for the agent already open -- changes no width, or a reload
   would widen the open pane a drag had made a rail. `pressed` is a hand on its rail (a press, its
   number, `Enter`), which does ask for it wide. */
/** @param {string} name
 *  @param {boolean} [skipPost]  the record already says so: draw it, write nothing
 *  @param {boolean} [pressed]   a hand on its rail, which does ask for it wide */
function openPane(name, skipPost, pressed) {
  if (!name || !tiles.has(name)) return;
  var was = openName();
  if (was && was !== name) previousOpen = was;
  var next = skipPost || (was === name && !pressed) ? null : swappedWidths(was, name);
  openTile = name;
  markTile(name);
  if (next) {
    myWidths = next;
    dropUndo();                 // `Esc` is this gesture's way back, not the footer
  }
  // Marked inside the callback, not around the call: the view-transition path runs it on the
  // frame after the browser has taken its snapshot, and a mark closed before the work happened
  // would report nought and mean nothing (#219).
  var mark = gesture("open:pane");
  transitionLayout(function () { choose(name); place(); settle(mark); });
  if (!skipPost) saveWidths(next ? { open: name, widths: next } : { open: name });
}

/** @returns {boolean} */
function backToPrevious() {
  if (!previousOpen || !tiles.has(previousOpen)) return false;
  var going = previousOpen;
  var leaving = openName();
  previousOpen = leaving;
  var next = swappedWidths(leaving, going);
  openTile = going;
  markTile(going);
  if (next) { myWidths = next; dropUndo(); }
  transitionLayout(function () { choose(going); place(); });
  saveWidths(next ? { open: going, widths: next } : { open: going });
  return true;
}

/* ------------------------------------------------------------------------ the widths (#234)

   A pane's width is a weight in its window's record: 0 is a rail, a positive number its share of
   what the rails leave (plan-panes §The model). A weight and not pixels, so a window made narrower
   scales the wide panes and leaves the rails alone. Every change of widths is one write, through
   `widthsNow`; what the row looks like is `paintWidths`', and nothing else writes a pane's width. */

/** How wide each pane on the glass is, in CSS pixels, by repository: what a gesture measures, and
 *  what `widthsFromPixels` turns back into weights.
 * @typedef {Object<string, number>} Pixels
 */

/** What a change of widths leaves behind to put back: the widths the window had -- null, none of
 *  its own -- and the pane that had the keys.
 * @typedef {{widths: Widths | null, open: string}} WidthsBefore
 */

/* Read out of a record leniently -- anything that is not a number of nought or more is not a width
   -- and an empty record is none at all: the window draws as it did before it was given any. */
/** @param {*} value  @returns {Widths | null} */
function ownWidths(value) {
  if (!value || typeof value !== "object") return null;
  var out = {};
  var any = false;
  Object.keys(value).forEach(function (name) {
    var n = Number(value[name]);
    if (isFinite(n) && n >= 0) { out[name] = n; any = true; }
  });
  return any ? out : null;
}

/* The share a pane had before the gutters: `size.cols` as an older build wrote it, which the plan's
   migration makes the weight of a pane that was wider than one column. Read, never written. */
/** @param {string} name  @returns {number} */
function legacyShare(name) {
  var v = (getArrangement().size || {})[name];
  var cols = v && typeof v === "object" ? v.cols : v;
  return Math.max(1, Math.min(4, Math.round(Number(cols) || 1)));
}

/* Every pane on the glass by name, with its weight in this window. With widths of its own, those;
   without, the open pane and every pin at the share they had, and every other pane a rail -- the
   row as it was before the gutters. Never all rails: a row of 48px strips with nothing open is the
   blank window this desk exists to stop, so if nothing has a share the open pane is given one. */
/** @returns {Widths} */
function paneWeights() {
  var shown = visibleOrder();
  var out = {};
  var any = false;
  var pinned = myWidths ? [] : (getArrangement().pinned || []);
  var one = myWidths ? "" : openName();
  shown.forEach(function (name) {
    var w = myWidths ? (myWidths[name] || 0)
                     : (name === one || pinned.indexOf(name) >= 0 ? legacyShare(name) : 0);
    out[name] = w;
    if (w > 0) any = true;
  });
  if (!any && shown.length) out[openName() || shown[0]] = 1;
  return out;
}

/** @param {Widths} weights  @returns {string[]} */
function wideNames(weights) {
  return visibleOrder().filter(function (name) { return (weights[name] || 0) > 0; });
}

/* Shares scaled so that they average one, to four places. A weight means something only beside
   its neighbours', and `flex-grow` under a sum of one leaves part of the row empty; the same
   arithmetic on the page and in what it writes is what lets a pass with nothing new touch nothing. */
/** @param {Widths} weights  @param {string[]} names  @returns {Widths} */
function evenShares(weights, names) {
  var sum = 0;
  var n = 0;
  names.forEach(function (name) {
    var w = weights[name] || 0;
    if (w > 0) { sum += w; n += 1; }
  });
  var k = n && sum > 0 ? n / sum : 1;
  var out = {};
  Object.keys(weights).forEach(function (name) {
    var w = Number(weights[name]) || 0;
    out[name] = w > 0 ? Math.round(w * k * 10000) / 10000 : 0;
  });
  return out;
}

/* The one writer of a pane's width: `is-solo` (it has one) and `--w` (its share), which is all the
   stylesheet reads. Written from the record on every pass and from nothing else -- except the hand,
   while a gutter is held, which this is not called during (`place` waits). */
/** @param {Widths} weights */
function paintWidths(weights) {
  var wide = wideNames(weights).filter(function (name) { return !groupedAway(name); });
  var shares = evenShares(weights, wide);
  tiles.forEach(function (entry, name) {
    var w = wide.indexOf(name) >= 0 ? shares[name] : 0;
    toggle(entry.el, "is-solo", w > 0);
    style(entry.el, "--w", w > 0 ? String(w) : "");
  });
}

/* What the window keeps after a gesture: the panes it changed as it left them, and every other as
   it was -- a hidden pane shown again comes back at its own width. */
/** @param {Widths} changes  @returns {Widths} */
function widthsWith(changes) {
  var out = Object.assign({}, myWidths || paneWeights());
  Object.keys(changes).forEach(function (name) { out[name] = changes[name]; });
  return evenShares(out, visibleOrder());
}

/* What a wide pane's own edges take of its width -- its padding and its borders -- which
   `flex-grow` does not share out: a wide pane is its edges plus its share of what is left, so a
   weight read off a width has them taken away first. Read off a wide pane, because a rail has no
   padding; the same for every wide pane, since one rule draws them all. */
/** @returns {number} */
function paneEdge() {
  var wide = document.querySelector('#grid .tile.is-solo:not([data-tier="rail"])');
  if (!wide) return 24;                      // the stylesheet's own 8px 10px and 3px + 1px
  var cs = getComputedStyle(wide);
  return (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0) +
         (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
}

/* The weight that draws a pane this many pixels wide, beside others drawn the same way. */
/** @param {number} px  @param {number} edge  @returns {number} */
function weightOf(px, edge) {
  return Math.max(1, px - edge);
}

/* The same, from the pixel width of every pane on the glass: a wide pane's weight is its width less
   its edges, so the ones a gesture did not touch keep their width to the pixel. */
/** @param {Pixels} px  @returns {Widths} */
function widthsFromPixels(px) {
  var edge = paneEdge();
  var changes = {};
  Object.keys(px).forEach(function (name) {
    changes[name] = px[name] > RAIL_PX + 0.5 ? weightOf(px[name], edge) : 0;
  });
  return widthsWith(changes);
}

/* How wide every pane on the glass is now, by name. */
/** @returns {Pixels} */
function measurePanes() {
  var out = {};
  Array.prototype.forEach.call(
    document.querySelectorAll("#grid .tile:not(.is-hidden):not(.is-grouped)"),
    function (el) { out[el.dataset.repo] = el.getBoundingClientRect().width; });
  return out;
}

/* The swap in widths: the pane pressed takes the width of the one that had the keys, which becomes
   a rail. A pane already wide keeps its width; one pressed while the pane that had the keys is a
   rail itself takes an even share of the row. Nothing, in a window with no widths of its own. */
/** @param {string} was  @param {string} name  @returns {Widths | null} */
function swappedWidths(was, name) {
  if (!myWidths) return null;
  var weights = paneWeights();
  if ((weights[name] || 0) > 0) return null;
  var give = was && was !== name ? (weights[was] || 0) : 0;
  var changes = {};
  if (give > 0) {
    changes[was] = 0;
    changes[name] = give;
  } else {
    var wide = wideNames(weights);
    changes[name] = wide.length ? wide.reduce(function (s, n) { return s + weights[n]; }, 0) /
                                  wide.length : 1;
  }
  return widthsWith(changes);
}

/* Save a window write that may carry widths, and when the server says another page under this
   window's name moved them first, put this page's gesture back and read the desk again -- so the
   next gesture starts from the widths that are really there. */
/** @param {WindowWrite} patch  @param {WidthsBefore} [before]
 *  @returns {Promise<DeskAnswer | null | void>} */
function saveWidths(patch, before) {
  return saveWindow(patch).then(function (r) {
    if (r && r.ok === false && patch.widths !== undefined) {
      if (before) {
        myWidths = before.widths;
        openTile = before.open;
      }
      dropUndo();
      place();
      loadDesk();
    }
    return r;
  });
}

/* Every other change of widths: painted now, written once, put back with the server's words if it
   is refused -- #219's order, for this window's record -- and offered back from the footer, because
   a drag that went wrong should cost one press to take back, not another drag. `open` moves the
   keys as well, in the same write; `how` is "layout" for the presets and the undo, which are layout
   changes and go through the one door for those (#216), and nothing for the hand's own gestures,
   whose preview was the real layout already. */
var UNDO_FOR_MS = 12000;
/** @type {(WidthsBefore & {what: string, until: number}) | null} */
var undoOffer = null;
var undoTimer = 0;
/** @type {HTMLElement | null} */
var keyHome = null;                 // the pane the keyboard was on when the widths last changed

/** @param {Widths | null} next  null: none of its own, as before the gutters
 *  @param {string} what  the gesture, which the undo names
 *  @param {string} [open]  the pane the keys go to, in the same write
 *  @param {string} [how]  "layout" for a change that goes through the one door for those (#216)
 *  @returns {Promise<DeskAnswer | null | void>} */
function widthsNow(next, what, open, how) {
  var mark = gesture("widths:" + what);
  var before = { widths: myWidths ? Object.assign({}, myWidths) : null, open: openTile };
  var had = document.activeElement;
  keyHome = had && had.closest ? had.closest("#grid .tile") : null;
  myWidths = next;
  if (open !== undefined && open !== openTile) {
    var was = openName();
    if (open && was && was !== open) previousOpen = was;
    openTile = open;
    if (open) markTile(open);
  }
  if (what === "undo") dropUndo();
  else offerUndo(before, what);
  var paint = function () { place(); settle(mark); };
  if (how === "layout") transitionLayout(paint);
  else paint();
  var patch = { widths: next || {} };
  if (open !== undefined && open !== before.open) patch.open = open;
  return saveWidths(patch, before);
}

var UNDO_WORDS = { drag: "the resize", step: "the resize", even: "the even split",
                   beside: "open beside", one: "one", all: "all", needs: "needs me" };

/** @param {WidthsBefore} before  @param {string} what */
function offerUndo(before, what) {
  undoOffer = { widths: before.widths, open: before.open, what: what,
                until: Date.now() + UNDO_FOR_MS };
  if (undoTimer) clearTimeout(undoTimer);
  undoTimer = setTimeout(function () { undoTimer = 0; drawUndo(); }, UNDO_FOR_MS + 50);
  drawUndo();
}

function dropUndo() {
  undoOffer = null;
  drawUndo();
}

/* The footer's one button for it (`u`): the widths, and the open pane if the gesture moved it, as
   they were before the last change -- one more write, through the same door. */
/** @returns {boolean} */
function undoWidths() {
  if (!undoOffer || Date.now() > undoOffer.until) return false;
  var back = undoOffer;
  widthsNow(back.widths, "undo", back.open !== openTile ? back.open : undefined, "layout");
  return true;
}

function drawUndo() {
  var button = document.getElementById("undo");
  if (!button) return;
  var on = !!undoOffer && Date.now() < undoOffer.until;
  hide(button, !on);
  text(button, on ? "undo " + (UNDO_WORDS[undoOffer.what] || "the widths") : "");
}

/* ------------------------------------------------------------------ the three presets (#234)

   One segmented control where the arrangement picker was, and three keys. Each is one write of this
   window's widths, and the footer's undo puts it back. Presses, not modes: nothing here holds a
   pane wide or narrow once the operator's hand moves a gutter, and *needs me* hides nothing -- it
   replaces the needs-only filter, which only dimmed (#207's second focus). */
/** @returns {string} */
function keyboardPane() {
  var at = document.activeElement;
  /** @type {HTMLElement} */
  var host = at && at.closest ? at.closest("#grid .tile") : null;
  return host && host.dataset.repo && !isHidden(host.dataset.repo) ? host.dataset.repo : "";
}

/** @param {string} name  @returns {boolean} */
function needsPerson(name) {
  var entry = tiles.get(name);
  return !!entry && entry.el.classList.contains("needs-human");
}

/** @param {string} which  "one", "all" or "needs"  @returns {boolean} */
function applyPreset(which) {
  var shown = visibleOrder();
  // Not while a gutter is held: the hand's own write comes when it lets go, and would undo this.
  if (!shown.length || gutterHeld) return false;
  var next = {};
  var open;
  if (which === "one") {
    // The pane the keyboard is on, else the open one: wide, and every other a rail.
    var one = keyboardPane() || openName();
    shown.forEach(function (name) { next[name] = name === one ? 1 : 0; });
    open = one;
  } else if (which === "all") {
    // An even share each; the tiers decide what that looks like on this glass.
    shown.forEach(function (name) { next[name] = 1; });
  } else if (which === "needs") {
    var red = shown.filter(needsPerson);
    if (!red.length) {
      say("nothing needs you — the widths are as they were", 6);
      return false;
    }
    shown.forEach(function (name) { next[name] = red.indexOf(name) >= 0 ? 1 : 0; });
    // The keys go with the width: to the pane that had them if it is one of these, else the first.
    var here = openName();
    open = red.indexOf(here) >= 0 ? here : red[0];
  } else {
    return false;
  }
  widthsNow(widthsWith(next), which, open, "layout");
  return true;
}

Array.prototype.forEach.call(document.querySelectorAll("[data-preset]"), function (button) {
  button.addEventListener("click", function () { applyPreset(button.dataset.preset); });
});

(function bindUndo() {
  var button = document.getElementById("undo");
  if (button) button.addEventListener("click", function () { undoWidths(); });
})();

/* ------------------------------------------------------------------------ the gutters (#234)

   A 1px line between every two panes on the glass, with an 8px hit area laid over their edges, so
   it costs no width. Dragging one moves width between the two panes beside it and nothing else:
   every other pane stays exactly where it is, which is what makes a resize predictable. The drag
   IS the preview -- #217's ghost was there because a span snapped on release and the hand could not
   see where it would land -- so while it is held the page writes those two panes' widths, once a
   frame, and nothing else: no `place()`, no redraw, no reorder (plan-panes ground rule 4). One write
   when the hand comes up; `Esc` puts the widths back with nothing written. */
var RAIL_SNAP_PX = 120;       // a pane dragged under this settles to a rail
var SNAP_PX = 8;              // how near a snap takes the hand
var GUTTER_STEP_PX = 40;      // one press of Alt+Shift+arrow

/** A gutter under the hand: the two panes beside it, where the drag began (`x`, `a0`), the left
 *  pane's width now (`a`) and as last painted, what the two hold between them (`total`), every
 *  pane's width as the drag began (`px`), and the frame that will paint it.
 * @typedef {Object} GutterHold
 * @property {HTMLElement} left
 * @property {HTMLElement} right
 * @property {number} x
 * @property {number} a0
 * @property {number} total
 * @property {number} a
 * @property {number} painted
 * @property {Pixels} px
 * @property {number} edge     what a wide pane's padding and borders take (`paneEdge`)
 * @property {number} frame    the animation frame asked for, or 0
 * @property {boolean} lifted  whether the other wide panes were pinned to their pixels yet
 */
/** @type {GutterHold | null} */
var gutterHeld = null;        // the drag in flight
var placeWanted = false;      // a pass asked for while it was

/** @param {HTMLElement} el  @returns {boolean} */
function onGlass(el) {
  return !!(el && el.dataset && el.dataset.repo && tiles.has(el.dataset.repo) &&
            !el.classList.contains("is-hidden") && !el.classList.contains("is-grouped"));
}

/** @param {HTMLElement} el  @returns {HTMLElement | null} */
function nextOnGlass(el) {
  var n = el ? /** @type {HTMLElement} */ (el.nextElementSibling) : null;
  while (n && !onGlass(n)) n = /** @type {HTMLElement} */ (n.nextElementSibling);
  return n;
}

/* Where the pair can come to rest, given how wide the two are together. The same rule on both
   sides: a pane is a 48px rail or at least the compact minimum, and one pulled under 120px settles
   to the rail. Two panes that together cannot hold two compact ones have two states, and the
   nearer wins. */
/** @param {number} a  @param {number} total  @returns {number} */
function settlePair(a, total) {
  if (total < RAIL_PX + TIER_COMPACT_FROM) return RAIL_PX;          // two rails: nowhere to go
  a = Math.max(RAIL_PX, Math.min(total - RAIL_PX, a));
  if (a < RAIL_SNAP_PX) return RAIL_PX;
  if (total - a < RAIL_SNAP_PX) return total - RAIL_PX;
  if (total < 2 * TIER_COMPACT_FROM) return a < total / 2 ? RAIL_PX : total - RAIL_PX;
  return Math.max(TIER_COMPACT_FROM, Math.min(total - TIER_COMPACT_FROM, a));
}

/* And while the hand is on it, the places worth landing on take it within 8px: either side at the
   compact or the full minimum, and an even share with the neighbour. */
/** @param {number} a  @param {number} total  @returns {number} */
function snapPair(a, total) {
  var stops = [TIER_COMPACT_FROM, TIER_FULL_FROM, total / 2,
               total - TIER_FULL_FROM, total - TIER_COMPACT_FROM];
  var near = null;
  stops.forEach(function (stop) {
    var d = Math.abs(a - stop);
    if (d <= SNAP_PX && (near === null || d < Math.abs(a - near))) near = stop;
  });
  return settlePair(near === null ? a : near, total);
}

/* One press: 40px, and out of a rail or into one in a single step, because a rail cannot be 88px
   wide and a press that did nothing would read as a key that does not work. */
/** @param {number} a  @param {number} total  @param {number} dir  @returns {number} */
function stepPair(a, total, dir) {
  var b = total - a;
  var want = a + dir * GUTTER_STEP_PX;
  if (dir > 0 && a <= RAIL_PX + 0.5) want = TIER_COMPACT_FROM;
  else if (dir < 0 && a <= TIER_COMPACT_FROM + 0.5) want = RAIL_PX;
  else if (dir > 0 && b <= TIER_COMPACT_FROM + 0.5) want = total - RAIL_PX;
  else if (dir < 0 && b <= RAIL_PX + 0.5) want = total - TIER_COMPACT_FROM;
  return settlePair(want, total);
}

/* One pane's width while the hand has it, in pixels. Every wide pane's share was made its width
   less its edges when the drag began, so the shares add up to what the rails and the edges leave,
   and a width written this way is the width drawn. */
/** @param {HTMLElement} el  @param {number} px  @param {number} edge */
function paintHeldWidth(el, px, edge) {
  var wide = px > RAIL_PX + 0.5;
  toggle(el, "is-solo", wide);
  style(el, "--w", wide ? String(Math.round(weightOf(px, edge) * 100) / 100) : "");
}

/* The frame: the two panes' widths, and nothing else (#217's lesson -- a draw in the middle of a
   drag no longer puts the gesture down). */
function paintHeld() {
  var held = gutterHeld;
  if (!held) return;
  held.frame = 0;
  if (held.a === held.painted) return;
  var mark = gesture("gutter:frame");
  if (!held.lifted) {
    held.lifted = true;
    Object.keys(held.px).forEach(function (name) {
      var entry = tiles.get(name);
      if (entry && entry.el.classList.contains("is-solo")) {
        paintHeldWidth(entry.el, held.px[name], held.edge);
      }
    });
  }
  paintHeldWidth(held.left, held.a, held.edge);
  paintHeldWidth(held.right, held.total - held.a, held.edge);
  held.painted = held.a;
  settle(mark);
}

/** @param {HTMLElement} gutter  @param {HTMLElement} el */
function bindGutter(gutter, el) {
  if (!gutter) return;
  gutter.addEventListener("pointerdown", function (e) {
    if (e.button !== 0 || gutterHeld || dragging) return;
    var right = nextOnGlass(el);
    if (!right || !onGlass(el)) return;
    // No text selected across two panes, no focus moved, and nothing under the gutter told.
    e.preventDefault();
    e.stopPropagation();
    var px = measurePanes();
    var a0 = px[el.dataset.repo];
    var held = { left: el, right: right, x: e.clientX, a0: a0, total: a0 + px[right.dataset.repo],
                 a: a0, painted: a0, px: px, edge: paneEdge(), frame: 0, lifted: false };
    gutterHeld = held;
    toggle(gutter, "is-held", true);
    toggle(document.body, "is-resizing", true);
    // Captured on the press: a gutter has no click of its own to lose to the capture, and the hand
    // leaves an 8px strip on the first pixel of travel.
    try { gutter.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }

    var finish = function () {
      if (held.frame) cancelAnimationFrame(held.frame);
      held.frame = 0;
      gutterHeld = null;
      placeWanted = false;
      toggle(gutter, "is-held", false);
      toggle(document.body, "is-resizing", false);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onCancel);
      document.removeEventListener("keydown", onKey, true);
      try { gutter.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
    };
    /** @param {PointerEvent} ev */
    var onMove = function (ev) {
      var a = snapPair(held.a0 + (ev.clientX - held.x), held.total);
      if (a === held.a) return;
      held.a = a;
      if (!held.frame) held.frame = requestAnimationFrame(paintHeld);
    };
    /** @param {PointerEvent} ev */
    var onUp = function (ev) {
      // Where the hand came up, which is not always where the last move said it was: an engine
      // that coalesces moves to the frame can deliver the release before the move that got there,
      // and the width then lands one step short of the pointer (Windows CI on #270: 45.8px of a
      // 50px drag, eleven of its twelve steps). The release carries the position; it is the one
      // that counts.
      if (ev && typeof ev.clientX === "number") {
        held.a = snapPair(held.a0 + (ev.clientX - held.x), held.total);
      }
      finish();
      if (Math.abs(held.a - held.a0) < 0.5) { place(); return; }   // a press is not a resize
      // The release's `click` lands on whatever the hand ended over once the capture is gone --
      // or, in an engine with no capture at all, on the pane under it -- and a pane's click
      // selects the project for every window. A resize is not that.
      swallowNextClick();
      held.px[held.left.dataset.repo] = held.a;
      held.px[held.right.dataset.repo] = held.total - held.a;
      widthsNow(widthsFromPixels(held.px), "drag");
    };
    // `Esc` puts the widths back and writes nothing. Captured on the document, because the capture
    // has taken the keyboard's usual route away and the page's own `Esc` would go back a pane. The
    // button is still down, and the click its release ends in is not a click on a pane either
    // (#233's lesson from the reorder drag), so that one is swallowed too.
    /** @param {KeyboardEvent} ev */
    var onKey = function (ev) {
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      ev.preventDefault();
      finish();
      place();
      var released = function () {
        document.removeEventListener("pointerup", released, true);
        document.removeEventListener("pointercancel", released, true);
        swallowNextClick();
      };
      document.addEventListener("pointerup", released, true);
      document.addEventListener("pointercancel", released, true);
    };
    var onCancel = function () { finish(); place(); };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onCancel);
    document.addEventListener("keydown", onKey, true);
  });
  // The press and the release are the gutter's: not the pane's click (which selects the project for
  // every window) nor its double click (which opens it). Two clicks here even the pair out instead.
  gutter.addEventListener("click", function (e) { e.stopPropagation(); });
  gutter.addEventListener("dblclick", function (e) {
    e.stopPropagation();
    e.preventDefault();
    evenGutter(el);
  });
}

/* The double-click, and `Alt+Enter` on the pane to its left: the two panes beside a gutter get an
   even share of what they hold between them. Two that cannot both be compact are left alone. */
/** @param {HTMLElement} el  @returns {boolean} */
function evenGutter(el) {
  var right = onGlass(el) && !gutterHeld ? nextOnGlass(el) : null;
  if (!right) return false;
  var px = measurePanes();
  var a0 = px[el.dataset.repo];
  var total = a0 + px[right.dataset.repo];
  if (total < 2 * TIER_COMPACT_FROM) return false;
  var a = settlePair(total / 2, total);
  if (Math.abs(a - a0) < 0.5) return false;
  px[el.dataset.repo] = a;
  px[right.dataset.repo] = total - a;
  widthsNow(widthsFromPixels(px), "even");
  return true;
}

/* `Alt+Shift+←/→` on a pane: its right-hand gutter, one step (#217's width keys, now the gutter's). */
/** @param {HTMLElement} el  @param {number} dir  @returns {boolean} */
function stepGutter(el, dir) {
  var right = onGlass(el) && !gutterHeld ? nextOnGlass(el) : null;
  if (!right) return false;
  var px = measurePanes();
  var a0 = px[el.dataset.repo];
  var total = a0 + px[right.dataset.repo];
  var a = stepPair(a0, total, dir);
  if (Math.abs(a - a0) < 0.5) return false;
  px[el.dataset.repo] = a;
  px[right.dataset.repo] = total - a;
  widthsNow(widthsFromPixels(px), "step");
  return true;
}

/* Shift and a rail: open it beside the pane that has the keys, the two splitting what that pane
   had and the rail's own 48px, so nothing else in the row moves. The keys stay where they were. A
   rail pressed while the pane with the keys is itself a rail is simply opened. */
/** @param {string} name */
function openBeside(name) {
  if (!name || !tiles.has(name) || gutterHeld) return;
  var host = openName();
  var weights = paneWeights();
  var hostEntry = host ? tiles.get(host) : null;
  if (!hostEntry || host === name || !((weights[host] || 0) > 0) || (weights[name] || 0) > 0 ||
      !onGlass(tiles.get(name).el)) {
    openPane(name, false, true);
    return;
  }
  var px = measurePanes();
  var share = (px[host] + RAIL_PX) / 2;
  px[host] = share;
  px[name] = share;
  widthsNow(widthsFromPixels(px), "beside", undefined, "layout");
}

/* Which gutters show: one on the right of every pane on the glass but the last. Written on every
   pass, guarded, so a pass with nothing to change touches nothing. */
function drawGutters() {
  var grid = document.getElementById("grid");
  if (!grid) return;
  var panes = Array.prototype.filter.call(grid.children, onGlass);
  tiles.forEach(function (entry) {
    var gutter = entry.el.querySelector(".gutter");
    var at = panes.indexOf(entry.el);
    hide(gutter, at < 0 || at === panes.length - 1);
  });
}

/* Repositories that left the registry. Their pane goes, but each leaves a rail naming the command
   that restores it (#173), because a transcript disappearing with no explanation is exactly the
   "where did it go" the row exists to answer. */
/** @type {Map<string, {path: string}>} */
var departed = new Map();

/** @param {Row} row  @returns {number} */
function ageOf(row) {
  return row && typeof row.last_event_age_s === "number" ? row.last_event_age_s : 0;
}

/* ------------------------------------------------------------- the pane's three widths (#233)

   One component, three widths (plan-panes §The pane). What a pane draws is decided by how wide it
   is, and how wide it is by the arrangement: open panes share the row by weight, every other one is
   a 48px rail. `data-tier` is the one bridge between the two, and it has one writer. */

/* The boundaries, in CSS pixels of the pane's border box. These are CI's, and the defaults: 360 is
   the grid's narrowest tile as it was, and 160 the narrowest a head and a reply box can share. The
   operator's own come from `fleet.tiers.*` (#235) through `applyTiers` below. The rail's width is
   `--rail` in app.css; `RAIL_PX` and the two after it mirror the stylesheet for the one sum that
   decides whether the rails still fit (`groupRails`). */
var TIER_COMPACT_FROM = 160;
var TIER_FULL_FROM = 360;
var TIER_SLACK = 8;
var RAIL_PX = 48;
var ROW_GAP_PX = 6;
var ROW_PAD_PX = 16;

/* The four as the operator set them after trying them on the real monitors (#235): `fleet.tiers.*`
   in config.json, from the settings page. They come with the theme -- `/api/fleet`, the stream's
   `theme` frame when the file changes, and the snapshot a reload draws first -- so a change reaches
   this desk on the next tick, with no reload and nothing written. The server has already refused
   any four that do not go together, and sends CI's with `invalid` saying why when the file holds
   one anyway, so all this checks is that it was handed numbers in order.

   The stylesheet needs two of them -- the rail's width, and the floor a pane with a width never
   goes under -- and they are written on the root only when they are not CI's, so a desk on the
   defaults carries nothing for them. A boundary that moved under a pane that did not is a change
   the observer never hears of, so every pane already measured has its tier taken again at the
   width it has. */
/** @type {{rail: number, compact: number, full: number, slack: number}} */
var TIER_DEFAULTS = { rail: RAIL_PX, compact: TIER_COMPACT_FROM, full: TIER_FULL_FROM,
                      slack: TIER_SLACK };
var tiersSaid = "";

/** @param {Tiers | null | undefined} t */
function applyTiers(t) {
  if (!t) return;
  var rail = Number(t.rail), compact = Number(t.compact), full = Number(t.full);
  var slack = Number(t.slack);
  if (!(rail > 0 && compact > rail && full > compact && slack >= 0)) return;
  if (t.invalid && t.invalid !== tiersSaid) {
    say("fleet.tiers: " + t.invalid + " — the panes are drawn at the defaults", 20);
  }
  tiersSaid = t.invalid || "";
  if (rail === RAIL_PX && compact === TIER_COMPACT_FROM && full === TIER_FULL_FROM &&
      slack === TIER_SLACK) return;
  RAIL_PX = rail;
  TIER_COMPACT_FROM = compact;
  TIER_FULL_FROM = full;
  TIER_SLACK = slack;
  var root = document.documentElement;
  style(root, "--rail", rail === TIER_DEFAULTS.rail ? "" : rail + "px");
  style(root, "--compact-from", compact === TIER_DEFAULTS.compact ? "" : compact + "px");
  tiles.forEach(function (entry) {
    if (!entry.el.dataset.tier) return;           // not measured yet: the observer's first report
    var width = entry.el.getBoundingClientRect().width;
    if (width > 0 && setTier(entry.el, width) && entry.row) {
      drawTile(entry.el, entry.row, lastApprovals);
    }
  });
  placeSoon();
}

/* Which tier a width is, remembering which one the pane was in. A pane leaves its tier only once
   it is 8px past the boundary, so a pane sitting on 360 -- a window edge being dragged, a scrollbar
   coming and going -- does not redraw itself between two tiers on every frame.

   Not at the rail's boundary (#234). A pane is a 48px rail or at least 160px wide -- the
   stylesheet's floor for a pane with a width, and the compact minimum a gutter settles on -- so
   nothing ever sits on that boundary to flicker across it, and the slack that was there drew a rail
   pulled out to exactly the compact minimum as a rail's face stretched 160px wide. */
/** @param {number} width  @param {Tier | ""} [was]  @returns {Tier} */
function paneTier(width, was) {
  /** @type {Tier} */
  var raw = width >= TIER_FULL_FROM ? "full" : width >= TIER_COMPACT_FROM ? "compact" : "rail";
  if (!was || raw === was || raw === "rail" || was === "rail") return raw;
  var lo = was === "full" ? TIER_FULL_FROM : TIER_COMPACT_FROM;
  var hi = was === "compact" ? TIER_FULL_FROM : Infinity;
  return (width >= lo - TIER_SLACK && width < hi + TIER_SLACK) ? was : raw;
}

/* The one writer of `data-tier`. It answers whether the tier changed, because a change is a
   redraw: a narrower tier skipped drawing what it does not show. */
/** @param {HTMLElement} el  @param {number} width  @returns {boolean} whether it changed */
function setTier(el, width) {
  var was = /** @type {Tier | ""} */ (el.dataset.tier || "");
  var tier = paneTier(width, was);
  if (tier === was) return false;
  attr(el, "data-tier", tier);
  return true;
}

/** @type {ResizeObserver | null} */
var rowObserver = null;
var rowWidth = 0;
var rowSoon = 0;

/* The border box, which is what the tiers are measured in and what `flex-basis` sets. */
/** @param {ResizeObserverEntry} entry  @returns {number} */
function entryWidth(entry) {
  var box = entry.borderBoxSize;
  var first = /** @type {ResizeObserverSize} */ (box && (box[0] || box));  // a bare one, in old engines
  if (first && typeof first.inlineSize === "number") return first.inlineSize;
  return entry.target.getBoundingClientRect().width;
}

/* One observer on the row: the row itself, for whether every rail still fits, and every pane in
   it, for its tier. A pane whose tier changed is drawn again from the row it already has, in the
   same frame, so what the narrower tier skipped is there before anything is painted. A pane taken
   off the glass -- hidden, or folded into its project's rail -- measures nought and keeps the tier
   it had, rather than being called a rail it is not. */
/** @param {ResizeObserverEntry[]} entries */
function onRowResize(entries) {
  var redraw = [];
  entries.forEach(function (entry) {
    var el = /** @type {HTMLElement} */ (entry.target);
    var width = entryWidth(entry);
    if (el.id === "grid") {
      if (Math.round(width) !== Math.round(rowWidth)) { rowWidth = width; placeSoon(); }
      return;
    }
    if (width > 0 && setTier(el, width)) redraw.push(el);
  });
  redraw.forEach(function (el) {
    var entry = tiles.get(el.dataset.repo);
    if (entry && entry.el === el && entry.row) drawTile(el, entry.row, lastApprovals);
  });
  /* The keyboard stays on the pane it was on when a change of widths carries that pane across a
     tier (#234). A rail's stop is its face and a wide pane's is the pane itself, so the face a
     rail had goes `display: none` the frame it is widened -- and would take the keyboard with it,
     leaving the next `Alt+Shift+→` addressed to nothing. */
  if (keyHome && redraw.indexOf(keyHome) >= 0) {
    var home = keyHome;
    keyHome = null;
    /** @type {HTMLElement} */
    var stop = home.dataset.tier === "rail" ? home.querySelector(".pane-rail") : home;
    var at = /** @type {HTMLElement} */ (document.activeElement);
    var kept = at && at !== document.body && home.contains(at) && at.offsetParent !== null;
    if (stop && !kept) stop.focus({ preventScroll: true });
  }
}

function startRowObserver() {
  if (rowObserver || typeof ResizeObserver !== "function") return;
  var grid = document.getElementById("grid");
  if (!grid) return;
  rowObserver = new ResizeObserver(onRowResize);
  rowObserver.observe(grid, { box: "border-box" });
  tiles.forEach(function (entry) { rowObserver.observe(entry.el, { box: "border-box" }); });
}

/** @param {HTMLElement} el */
function watchPane(el) {
  startRowObserver();
  if (rowObserver) rowObserver.observe(el, { box: "border-box" });
}

/** @param {HTMLElement} el */
function forgetPane(el) {
  if (rowObserver) rowObserver.unobserve(el);
}

/* An engine with no `ResizeObserver` -- none of the three the desk runs in, as #235 will record,
   but a page that cannot tell a pane's width must still draw one -- gets the same writer, fed by a
   measurement after every layout pass and on every resize of the window. */
function measureRow() {
  if (rowObserver || typeof ResizeObserver === "function") return;
  var grid = document.getElementById("grid");
  if (!grid) return;
  rowWidth = grid.getBoundingClientRect().width;
  tiles.forEach(function (entry) {
    var width = entry.el.getBoundingClientRect().width;
    if (width > 0 && setTier(entry.el, width) && entry.row) {
      drawTile(entry.el, entry.row, lastApprovals);
    }
  });
}

function placeSoon() {
  if (rowSoon) return;
  rowSoon = requestAnimationFrame(function () { rowSoon = 0; place(); });
}

window.addEventListener("resize", function () {
  if (typeof ResizeObserver !== "function") placeSoon();
});

/* ------------------------------------------------------- when even the rails do not fit (#233)

   A project's checkouts share one rail -- but only when the row cannot hold every rail it has, at
   about thirty agents on a 1440px window (plan-panes §Open questions; D's default is to group). It
   is the answer that keeps every agent on the glass: a row that scrolled sideways would put the one
   that needs you past its edge, and the dock grouped checkouts the same way (#175). The first
   checkout of a project, in the row's order, is the head; the others fold into its rail. Past
   grouping the row scrolls, which is the last resort and not the design. */
/** @type {Map<string, string[]>} */
var railGroups = new Map();           // head -> [head, member...], only while grouping
/** @type {Map<string, string>} */
var groupedInto = new Map();          // member -> head, for every member but the head

/** @param {string[]} shown  @param {string[]} open */
function groupRails(shown, open) {
  railGroups = new Map();
  groupedInto = new Map();
  var rails = shown.filter(function (name) { return open.indexOf(name) < 0; });
  // Measured against every rail, never the grouped count, so grouping cannot talk itself out of
  // being needed on the next pass and flicker.
  var need = ROW_PAD_PX + open.length * TIER_COMPACT_FROM + rails.length * RAIL_PX +
             Math.max(0, shown.length - 1) * ROW_GAP_PX;
  if (!rowWidth || need <= rowWidth) return;
  var byProject = new Map();
  rails.forEach(function (name) {
    var entry = tiles.get(name);
    var project = (entry && entry.row && entry.row.project) || name;
    var head = byProject.get(project);
    if (!head) {
      byProject.set(project, name);
      railGroups.set(name, [name]);
      return;
    }
    railGroups.get(head).push(name);
    groupedInto.set(name, head);
  });
  railGroups.forEach(function (members, head) {
    if (members.length < 2) railGroups.delete(head);
  });
}

/** @param {string} name  @returns {boolean} */
function groupedAway(name) {
  return groupedInto.has(name);
}

/* Where a press on a rail goes: the agent itself -- or, on a project's shared rail, the first of
   its checkouts that needs a person, then the first one. The red is why the operator pressed it. */
/** @param {string} name  @returns {string} */
function railTarget(name) {
  var members = railGroups.get(name);
  if (!members) return name;
  var red = members.filter(function (member) {
    var entry = tiles.get(member);
    return !!entry && entry.el.classList.contains("needs-human");
  })[0];
  return red || name;
}

/* ------------------------------------------------------------------------------ the rail (#233) */

/* The glyph a rail wears for a state. Its shape says what its colour says, so neither is alone: a
   colour is not a signal on a bad monitor at arm's length, and not at all to somebody who cannot
   tell the two apart. A project's shared rail wears its count instead. */
var RAIL_GLYPHS = {
  running: "▶", waiting_approval: "‖", needs_human: "!", blocked: "■",
  error: "✕", done: "✓", idle: "○", starting: "◌"
};

/* One agent, in the words a rail cannot fit: who, in what state, since when, what it has cost,
   what is unread, and the last thing it said -- or, when it needs a person, what it is asking. */
/** @param {Row} row  @returns {string} */
function railLine(row) {
  var ac = ageChip(row.last_event_age_s);
  var bits = [row.needs_human ? "needs you" : (shownState(row).replace(/_/g, " ") || "no run yet")];
  if (ac.text) bits.push(ac.text + " ago");
  var spend = row.spend || {};
  if (spend.total) bits.push(spend.total + " premium");
  var n = unread.get(row.repo) || 0;
  if (n) bits.push(n + " unread");
  var said = row.needs_human ? String(row.why || "") : String(row.last_said || "").slice(0, 160);
  return row.repo + ": " + bits.join(" · ") + (said ? " — " + said : "");
}

/* The rail's face: the name down its length, the state's glyph in the state's colour, the unread
   count, and the whole of it red when the agent needs a person. The age and the last line are its
   accessible name and its title. Drawn on every pass whatever the tier -- it is a handful of
   guarded writes -- so a pane that narrows to a rail is already right. It owns the face's `class`
   and nothing on the pane around it. */
/** @param {HTMLElement} el  @param {Row} row */
function drawPaneRail(el, row) {
  var face = el.querySelector(".pane-rail");
  if (!face || !row) return;
  var members = railGroups.get(row.repo);
  var rows = members ? members.map(function (name) {
    var entry = tiles.get(name);
    return (entry && entry.row) || { repo: name };
  }) : [row];
  var asking = rows.filter(function (r) { return !!r.needs_human; });
  var red = asking.length > 0;
  var state = members ? "group" : shownState(row);
  setClass(face, "pane-rail st-" + (red ? "needs_human" : state) + (red ? " needs-human" : ""));
  text(face.querySelector(".pr-glyph"),
       red ? "!" : members ? String(members.length) : (RAIL_GLYPHS[state] || "·"));
  text(face.querySelector(".pr-name"), members ? (row.project || row.repo) : row.repo);
  var unreadN = rows.reduce(function (n, r) { return n + (unread.get(r.repo) || 0); }, 0);
  var badge = face.querySelector(".pr-badge");
  hide(badge, !unreadN);
  text(badge, unreadN ? String(unreadN) : "");
  var lines = rows.map(railLine);
  var needing = asking.length + " " + (asking.length === 1 ? "needs" : "need") + " you";
  var head = members ? (row.project || row.repo) + ", " + members.length + " checkouts" +
                       (red ? ", " + needing : "") : "";
  attr(face, "aria-label", members ? head + ". " + lines.join(". ") : lines[0]);
  attr(face, "title", members ? head + "\n" + lines.join("\n") : lines[0]);
}

/* -------------------------------------------------------------------------- the whole window */

/* The one function that decides what this window shows. The stylesheet is the layout, and there is
   one arrangement (#232), so all this writes is how wide each pane is (#234), which one is
   selected, which rails are folded into their project's, and which gutters show. What each pane
   draws at its width is the observer's (#233).

   Not while a gutter is held (#234): the hand is writing two panes' widths once a frame, and a pass
   from the stream in the middle of that would put the record's widths back under it. The pass is
   run when the hand comes up. */
function place() {
  if (gutterHeld) { placeWanted = true; return; }
  var weights = paneWeights();
  groupRails(visibleOrder(), wideNames(weights));
  tiles.forEach(function (entry, name) {
    toggle(entry.el, "is-selected", name === desk.desk.selected);
    toggle(entry.el, "is-grouped", groupedAway(name));
  });
  paintWidths(weights);
  reorderDomTiles();
  drawGutters();
  tiles.forEach(function (entry) { if (entry.row) drawPaneRail(entry.el, entry.row); });
  drawNotice();
  drawUndo();
  drawHiddenCount();
  drawGone();
  drawRail();
  measureRow();
}

/* Where a hidden agent went (#233): it left the row, and the footer says how many have. One press
   brings every one of them back, each to its own slot. An agent that needs a person is never
   counted, because it is never put away (`isHidden`). */
function drawHiddenCount() {
  var n = getEffectiveOrder().filter(function (name) { return isHidden(name); }).length;
  var button = document.getElementById("hiddencount");
  text(button, n ? n + " hidden" : "");
  hide(button, !n);
}

/* The rails of repositories that left the registry, after the row. Patched, never rebuilt, like
   every list on this page. */
function drawGone() {
  var list = document.getElementById("gone");
  if (!list) return;
  var pattern = list.querySelector(".gone-rail");
  var rows = [];
  departed.forEach(function (gone, name) { rows.push({ name: name, path: gone.path }); });
  patchList(list, rows, function (item) { return item.name; },
    function () {
      var li = pattern.cloneNode(true);
      hide(li, false);
      return li;
    },
    function (li, item) {
      setData(li, "repo", item.name);
      text(li.querySelector(".pr-name"), item.name);
      var said = item.name + ": removed from the registry — `ad-fleet repo add " + item.path +
                 "` restores it";
      attr(li, "aria-label", said);
      attr(li, "title", said);
    });
  hide(list, !rows.length);
}

/* The footer's one line, and one owner (#173).

   `place()` runs several times a second while the stream is talking, and it used to clear this
   element on every draw -- so a message written by anything else lived a few milliseconds and the
   operator never saw it. A line said here holds the footer for its few seconds, and the footer
   goes quiet again when they pass. */
var saidLine = "";
var saidUntil = 0;
var sayTimer = null;

function say(message, seconds) {
  saidLine = message;
  saidUntil = Date.now() + (seconds || 6) * 1000;
  if (sayTimer) clearTimeout(sayTimer);
  // The stream usually redraws long before this, but a quiet fleet does not -- and a footer that
  // keeps saying "reopened" ten minutes later is worse than one that says nothing.
  sayTimer = setTimeout(function () { sayTimer = null; drawNotice(); }, (seconds || 6) * 1000 + 50);
  drawNotice();
}

function drawNotice() {
  var notice = document.getElementById("notice");
  if (saidLine && Date.now() < saidUntil) {
    text(notice, saidLine);
    hide(notice, false);
    return;
  }
  saidLine = "";
  text(notice, "");
  hide(notice, true);
}

/* ------------------------------------------------------------------ fresh sessions (#240, #241)

   Skills are read when a session begins, so an `ad-update` that changed one leaves every running
   session on the old text. The server judges each row against what is installed now, on every
   snapshot; the page only says so -- a chip on the tile, and a header button that previews what a
   renew would do before anything runs. */
function drawOldSession(el, row) {
  var old = el.querySelector(".oldsession");
  if (!old) return;
  var sv = row.stale || {};
  hide(old, !sv.stale);
  text(old, row.renew_queued ? "renew queued" : "old skills");
  attr(old, "title", sv.stale
    ? (sv.reason || "began on older skills") +
      (row.renew_queued ? " — renewed when this turn ends" : " — renew stale sessions from the header")
    : "");
}

function renewStrip() { return document.getElementById("renew-strip"); }
var renewOpen = false;

/* One line for as long as anything is stale; the preview only when asked for. Collapsed, the
   sentence is the count; open, it is the plan's own summary, which the next frame must not undo. */
function drawRenewStrip(rows, server) {
  var strip = renewStrip();
  if (!strip) return;
  var n = (rows || []).filter(function (r) { return r.stale && r.stale.stale; }).length;
  // The desk itself can be the stale thing (#242): a server started before `ad-update` goes on
  // serving the code it loaded. The server judges it; this only repeats the sentence.
  var oldDesk = !!(server && server.current === false);
  var deskLine = strip.querySelector(".renew-desk");
  hide(deskLine, !oldDesk);
  text(deskLine, oldDesk ? server.reason : "");
  hide(strip, n === 0 && !oldDesk && !renewOpen);
  hide(strip.querySelector(".renew-sum"), n === 0 && !renewOpen);
  hide(document.getElementById("renew"), n === 0 || renewOpen);
  if (renewOpen) return;
  text(strip.querySelector(".renew-sum"), n === 1
    ? "1 session began on skills or a CLI that have since changed"
    : n + " sessions began on skills or a CLI that have since changed");
}

function openRenew() {
  var strip = renewStrip();
  if (!strip) return;
  renewOpen = true;
  var sum = strip.querySelector(".renew-sum");
  text(sum, "checking which sessions are stale…");
  /** @type {HTMLButtonElement} */ (document.getElementById("renewgo")).disabled = true;
  hide(strip, false);
  hide(sum, false);
  hide(document.getElementById("renew"), true);
  hide(strip.querySelector(".renew-rows"), false);
  hide(strip.querySelector(".renew-actions"), false);
  post("renew", { dry_run: true }).then(function (r) {
    if (!r || r.ok === false) {
      text(sum, ((r && r.error) || "the preview could not be read") + (r && r.hint ? " — " + r.hint : ""));
      return;
    }
    drawRenewPlan(r);
  }).catch(function () { text(sum, "the preview could not be read"); });
}

function drawRenewPlan(p) {
  var strip = renewStrip();
  var rows = (p.rows || []).filter(function (r) { return r.stale || r.unknown; });
  patchList(strip.querySelector(".renew-rows"), rows, function (r) { return r.repo; },
    function () {
      // Cloned from the markup's own pattern row, so the two cannot disagree about the parts.
      var li = /** @type {HTMLElement} */ (strip.querySelector(".renew-pattern").cloneNode(true));
      li.classList.remove("renew-pattern");
      li.hidden = false;
      return li;
    },
    function (li, r) {
      text(li.querySelector(".renew-repo"), r.repo);
      text(li.querySelector(".renew-verdict"), r.verdict === "skipped" ? "skipped" : r.verdict);
      text(li.querySelector(".renew-why"), (r.reason ? r.reason + " — " : "") + (r.why || ""));
      setClass(li, "renew-row verdict-" + String(r.verdict).replace(/ /g, "-"));
    });
  var going = (p.now || 0) + (p.at_turn_end || 0);
  text(strip.querySelector(".renew-sum"), going
    ? going + " fresh session" + (going === 1 ? "" : "s") + ": " + (p.now || 0) + " now, " +
      (p.at_turn_end || 0) + " when their turn ends — about " + (p.premium_turns || 0) +
      " premium turn" + (p.premium_turns === 1 ? "" : "s") + " between them"
    : "nothing to renew: every stale session is waiting on you, is a console, or is done");
  var go = /** @type {HTMLButtonElement} */ (document.getElementById("renewgo"));
  go.disabled = going === 0;
  text(go, going ? "renew " + going : "renew");
}

function closeRenew() {
  var strip = renewStrip();
  if (!strip) return;
  renewOpen = false;
  hide(strip.querySelector(".renew-rows"), true);
  hide(strip.querySelector(".renew-actions"), true);
  hide(document.getElementById("renew"), false);
  refresh();
}

function runRenew() {
  var go = /** @type {HTMLButtonElement} */ (document.getElementById("renewgo"));
  go.disabled = true;
  post("renew", { dry_run: false }).then(function (r) {
    closeRenew();
    if (!r || r.ok === false) {
      say((r && r.error) || "the renew could not be started", 10);
      return;
    }
    var started = (r.rows || []).filter(function (x) { return x.done === "started"; }).length;
    var queued = (r.rows || []).filter(function (x) { return x.done === "queued"; }).length;
    var refused = (r.rows || []).filter(function (x) { return x.done === "refused"; });
    say(started + " fresh session" + (started === 1 ? "" : "s") + " started, " + queued + " queued" +
        (refused.length ? " — refused: " + refused.map(function (x) {
          return x.repo + " (" + (x.error || "refused") + ")"; }).join(", ") : ""), 12);
    refresh();
  }).catch(function () { go.disabled = false; });
}

(function bindRenew() {
  var btn = document.getElementById("renew");
  if (btn) btn.addEventListener("click", openRenew);
  var go = document.getElementById("renewgo");
  if (go) go.addEventListener("click", runRenew);
  var cancel = document.getElementById("renewcancel");
  if (cancel) cancel.addEventListener("click", closeRenew);
  var strip = renewStrip();
  if (strip) strip.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.stopPropagation(); closeRenew(); }
  });
})();

/* An address that still chooses an arrangement (#232): a bookmark, an older launcher, or a shell
   built before there was only one. The desk opens as it always does, the footer says once that
   the parameters meant nothing, and they come off the address -- so a reload does not say it a
   second time, and the address the operator copies says only true things. */
function forgetRetiredParams() {
  if (!ignoredParams.length) return;
  var u = new URLSearchParams(location.search);
  ignoredParams.forEach(function (k) { u.delete(k); });
  var qs = u.toString();
  history.replaceState(history.state, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  say(ignoredParams.map(function (k) { return k + "="; }).join(" and ") +
      " in the address " + (ignoredParams.length === 1 ? "is" : "are") +
      " ignored — the desk has one arrangement now", 12);
}

/* The tab bar is the friction, so the window's own title says which agent it has open. */
/* `document` is not an element, so `attr` threw here on every refresh (#262): the tab never said
   who needs you, and `refresh()` ended in its own catch. The one write that is not an attribute,
   done directly -- and only when it changes, as `attr` would have. */
function title(need) {
  var one = openName();
  var want = (need ? "(" + need + ") " : "") + "fleet" + (one ? " · " + one : "");
  if (document.title !== want) document.title = want;
}

/* Where the keyboard stops along the row (#233): a rail's face, or an open pane itself. In the
   row's order, and only what is on the glass, so `j` never lands on something nobody can see and
   the digits count exactly the panes there are. */
/** @returns {HTMLElement[]} */
function paneStops() {
  return Array.prototype.map.call(
    document.querySelectorAll("#grid .tile:not(.is-hidden):not(.is-grouped)"),
    function (el) { return el.dataset.tier === "rail" ? el.querySelector(".pane-rail") : el; });
}

/* `j` and `k` walk the row. A rail's stop is a real button, so `Enter` opens it, and there is no
   second model of "which one is selected" to disagree with what is on the glass. */
/** @param {number} dir */
function stepRow(dir) {
  var stops = paneStops();
  if (!stops.length) return;
  var active = document.activeElement;
  var here = -1;
  stops.forEach(function (stop, i) {
    if (stop === active || (active && stop.contains(active))) here = i;
  });
  var at = here < 0 ? (dir > 0 ? 0 : stops.length - 1)
                    : (here + dir + stops.length) % stops.length;
  stops[at].focus();
}

document.addEventListener("click", function (/** @type {MouseEvent & {target: Element}} */ e) {
  // One menu open at a time, and a click off it closes it -- the rule every popover here keeps.
  if (e.target.closest && (e.target.closest(".smenu") || e.target.closest(".spill"))) return;
  closeMenus();
});

(function bindModelCard() {
  var card = document.getElementById("modelcard");
  if (!card) return;
  document.getElementById("mc-close").addEventListener("click", closeModelCard);
  document.getElementById("mc-save").addEventListener("click", saveModel);
  card.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { saveModel(); e.preventDefault(); }
  });
  // A click anywhere else closes it, the way it closes a popover.
  document.addEventListener("click", function (/** @type {MouseEvent & {target: Element}} */ e) {
    if (card.hidden) return;
    if (card.contains(e.target)) return;
    if (e.target.closest && e.target.closest('[data-tool="model"]')) return;
    closeModelCard();
  });
})();

function showEverything() {
  var curArr = getArrangement();
  var was = (curArr.hidden || []).slice();
  return arrangeNow({ hidden: [] }, function () {
    curArr.hidden = [];
    return function () { curArr.hidden = was; };
  }, "showall");
}

document.getElementById("hiddencount").addEventListener("click", showEverything);

/* ---- the popovers: the key map behind `?`. The pickers that used to sit beside it are a page of
   their own now (`/settings`), so this map has one entry -- and keeps its shape, because "one open
   at a time" is the rule whatever is open. */
var POPOVERS = { keymap: "keysbtn" };

function popover(id, open) {
  var box = document.getElementById(id);
  var button = document.getElementById(POPOVERS[id]);
  if (!box || !button) return false;
  var want = open === undefined ? box.hidden : !!open;
  // Read before hiding: a hidden element cannot hold the focus.
  var hadTheKeyboard = !!(document.activeElement && box.contains(document.activeElement));
  Object.keys(POPOVERS).forEach(function (other) {
    var o = document.getElementById(other);
    var ob = document.getElementById(POPOVERS[other]);
    var on = other === id && want;
    if (o) hide(o, !on);
    if (ob) attr(ob, "aria-expanded", String(on));
  });
  if (want) {
    /** @type {HTMLElement} */
    var first = box.querySelector("select:not(:disabled), button:not(:disabled), input:not(:disabled), [tabindex]");
    if (first) first.focus();
  } else if (hadTheKeyboard) {
    button.focus();                           // the keyboard goes back where it came from
  }
  return want;
}

function closePopovers() {
  var was = false;
  Object.keys(POPOVERS).forEach(function (id) {
    var box = document.getElementById(id);
    if (box && !box.hidden) { popover(id, false); was = true; }
  });
  return was;
}

Object.keys(POPOVERS).forEach(function (id) {
  var button = document.getElementById(POPOVERS[id]);
  if (button) button.addEventListener("click", function () { popover(id); });
});
document.addEventListener("click", function (/** @type {MouseEvent & {target: Element}} */ e) {
  Object.keys(POPOVERS).forEach(function (id) {
    var box = document.getElementById(id);
    var button = document.getElementById(POPOVERS[id]);
    if (box && !box.hidden && !box.contains(e.target) && !(button && button.contains(e.target))) {
      popover(id, false);
    }
  });
});

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape" && !typing) { closeSide(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  // The three presets (#234), and the footer's undo of whichever widths changed last.
  if (e.key === "1") { applyPreset("one"); return; }
  if (e.key === "=") { applyPreset("all"); return; }
  if (e.key === "f") { applyPreset("needs"); return; }
  if (e.key === "u") { undoWidths(); return; }
  if (e.key === "i") { section("unsorted"); return; }
  if (e.key === "?") { popover("keymap"); return; }
  if (e.key === "/") { e.preventDefault(); document.getElementById("find").focus(); }
});


/* #219: the desk that was, while the desk that is loads. At the very bottom of the file and not
   beside the `refresh()` that starts the fetch, because drawing a row touches module state --
   `departed`, the tiles map -- that is declared further down and is `undefined` until the script
   has finished evaluating. The fetch is already in flight either way; this only decides what is
   on the screen while it is. */
var st = servedTiers();          // #345: the widths the server wrote, before a pane is drawn
if (st) applyTiers(st);
restoreCached();
// Last for the same reason: `say` writes the footer's state, which is only set up once the script
// has run past it.
forgetRetiredParams();
