/* The multi-viewer's client. No framework and no build step on purpose: this file has to load
   inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
   fetched from the internet simply does not arrive.

   The page is a view. It never decides anything -- every state comes from /api/fleet and every
   button POSTs to the same function the CLI verb calls. */

"use strict";

/* `PARAMS`, `TOKEN`, `q`, `post`, `text`, `applyTheme` and `applySkin` come from common.js, which
   every page loads before its own script. */
var tiles = new Map();          // repo name -> {el, seq}
var focused = null;
var pendingRefresh = null;
var source = null;

/* #133, #203: four arrangements of this one page, chosen by the URL, because a second HTML file is
   a second thing to keep in step and the friction being fixed is *tabs*. `column` is one agent open
   and the rest as bands down the side, and it is the default the operator chose on the real screens
   (`docs/fleet-layouts.md` §The sitting); `grid` is every tile at once; `roles` is three windows --
   board, agents, verify -- that agree on a selected project through the SSE stream; `screens` pins
   one project per monitor. `ad-fleet serve --layout` puts the parameter on the URL it prints, so
   the operator never has to type one. */
var LAYOUTS = ["column", "grid", "roles", "screens"];
var VIEWS = ["board", "agents", "verify"];
var DEFAULT_LAYOUT = LAYOUTS[0];
var rawLayout = PARAMS.get("layout");
var unknownLayout = (rawLayout && LAYOUTS.indexOf(rawLayout) < 0) ? rawLayout : null;
var LAYOUT = unknownLayout ? DEFAULT_LAYOUT : (rawLayout || DEFAULT_LAYOUT);
var VIEW = VIEWS.indexOf(PARAMS.get("view")) >= 0 ? PARAMS.get("view")
                                                  : (LAYOUT === "roles" ? "agents" : "");
var SCREEN = Math.max(0, Math.min(9, Number(PARAMS.get("screen")) || 0));
var W_NAME = PARAMS.get("w") || "main";

var desk = { projects: {}, offers: {}, unsorted: [], not_offered: [], folders: [],
             desk: { selected: "", screens: [] } };
var pendingDesk = null;
var needsOnly = false;
var readCursors = {};
var streamDead = false;
var awayShown = false;
var appliedInitialWindow = false;
/* Which agent this window has OPEN in the column (#203), and the one it had before -- `Esc` goes
   back to that rather than to nothing, because "show me the other one for a second" is the gesture
   the column is for. Per window: the left monitor reads one agent while the centre reads another,
   and `selected` stays the one thing every window agrees on. */
var openTile = "";
var previousOpen = "";
/* Whether a drop opens the dispatch card (#164) or launches the way #98 did. The server's
   `fleet.preflight` decides; until the first `/api/fleet` answers, the card is the default,
   because showing a card and starting from it is the recoverable direction to be wrong in. */
var PREFLIGHT = true;

/* This window's own record -- which agent is open, what it has read. Posted and not waited on:
   the page has already drawn the change, and a window record that failed to save is a preference
   lost, not a wrong screen. A refusal is still said out loud (#219) rather than swallowed. */
function saveWindow(patch) {
  var body = Object.assign({ w: W_NAME }, patch);
  var mark = gesture("window");
  return post("window", body).then(function (r) {
    settle(mark);
    if (r && r.ok === false) say((r.error || "that could not be saved") +
                                 (r.hint ? " — " + r.hint : ""), 8);
    return r;
  }).catch(function () {});
}

function rehome() {
  var dest = "/open?w=" + encodeURIComponent(W_NAME) +
             "&layout=" + encodeURIComponent(LAYOUT) +
             "&view=" + encodeURIComponent(VIEW) +
             "&screen=" + encodeURIComponent(SCREEN);
  window.location.href = dest;
}

/* Repos the operator has acted on, and the word for what they did.
   Answering an agent is what stops it needing you, so in focus mode a reply hid the very tile it
   was typed into: the only visible outcome of pressing Send was that the thing vanished. These are
   held on screen until focus mode is left or the tile is released, so an action's result is
   something the operator can see rather than something they have to go and find. */
var held = new Map();           // repo -> what was done ("replied", "started", ...)

var HELD_WORDS = { send: "replied", start: "started", stop: "stopped",
                   reset: "reset", approve: "approved", deny: "denied" };

function hold(repo, what) {
  if (!repo || !HELD_WORDS[what]) return;
  held.set(repo, HELD_WORDS[what]);
  saveWindow({ held: Array.from(held.keys()) });
}

function release(repo) {
  held.delete(repo);
  if (tiles.has(repo)) toggle(tiles.get(repo).el, "held", false);
  saveWindow({ held: Array.from(held.keys()) });
  place();
}


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
   the band, the strip and the rail all call it. */
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
    default: return JSON.stringify(d).slice(0, 160);
  }
}

var SHOWN = {
  started: 1, assistant_text: 1, tool_call: 1, tool_result: 1, denied: 1, friction: 1,
  phase_changed: 1, question_opened: 1, needs_approval: 1, approval_resolved: 1,
  exited: 1, error: 1, pr_open: 1, artifact: 1, said: 1,
  "project.ticket_changed": 1, "project.refresh_finished": 1, "project.pr_merged": 1,
  "inbox.attached": 1
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

function makeTile(row, index) {
  var el = document.getElementById("tile").content.firstElementChild.cloneNode(true);
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

  el.querySelector(".repo").addEventListener("click", function () { focus(row.repo); });
  el.addEventListener("dblclick", function () { focus(row.repo); });
  // Clicking anywhere on a tile *selects* the project for every window on this server (#133 layout
  // B), which is what makes the left monitor drive the centre one. Blowing a tile up is still the
  // repo name or a double click: one gesture per meaning.
  el.addEventListener("click", function (e) {
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
    action(el, "answer", { repo: row.repo, answers: answers });
  });

  // hide, refresh and the model -- the band's three, on the tile, from the one binder (#205).
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

  /* Every drag gesture has a keyboard equivalent, and the footer key map lists all four. */
  el.addEventListener("keydown", function (e) {
    if (!e.altKey) return;
    // #217: shifted, because Alt+arrows has moved a tile since #5 and a learned gesture is not
    // something to take away for a new one.
    if (e.shiftKey) {
      if (e.key === "ArrowRight") { resizeTile(row.repo, 1, 0); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { resizeTile(row.repo, -1, 0); e.preventDefault(); }
      else if (e.key === "ArrowDown") { resizeTile(row.repo, 0, 1); e.preventDefault(); }
      else if (e.key === "ArrowUp") { resizeTile(row.repo, 0, -1); e.preventDefault(); }
      return;
    }
    if (e.key === "ArrowLeft") { moveTile(row.repo, -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { moveTile(row.repo, 1); e.preventDefault(); }
    else if (e.key === "Home") { toggleTilePin(row.repo); e.preventDefault(); }
    else if (e.key === "Enter") { toggleTileSize(row.repo); e.preventDefault(); }
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

  bindResizeEdges(el, row.repo);

  var adoptBtn = el.querySelector(".adopt");
  if (adoptBtn) {
    adoptBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var what = adoptBtn.dataset.what === "release" ? "release" : "adopt";
      action(el, what, { repo: row.repo, pid: Number(adoptBtn.dataset.pid || 0) });
    });
  }

  var releaseBtn = el.querySelector(".release");
  if (releaseBtn) {
    releaseBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      release(row.repo);
    });
  }

  var say = el.querySelector(".say");
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
    if (e.key === "Enter") el.querySelector(".send").click();
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
    action(el, "approve", { id: el.dataset.approval, reason: el.querySelector(".reason").value });
  });
  el.querySelector(".deny").addEventListener("click", function () {
    var reason = el.querySelector(".reason").value.trim();
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
    // Only a *successful* action holds the tile. A refusal leaves the agent exactly as it was, so
    // the tile is still whatever focus mode already thought it was, and the error is on the tile.
    else hold((body && body.repo) || el.dataset.repo, what);
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

/* Every colour a canvas uses is read from the stylesheet at paint time, never written here. A
   canvas that carries its own palette is a canvas that stays the old colour when the operator
   changes theirs -- and the accent stripe (#215) is the whole reason this page has a rule about
   two owners of one colour. Cached per token per skin, because `getComputedStyle` on every bar of
   every tile several times a minute is a layout read nobody needs. */
var tokenCache = {};

function token(name, fallback) {
  var key = (document.body.dataset.skin || "none") + ":" +
            (document.body.dataset.skinVariant || "") + ":" + name;
  if (tokenCache[key] === undefined) {
    var got = getComputedStyle(document.documentElement).getPropertyValue(name);
    tokenCache[key] = (got || "").trim() || fallback;
  }
  return tokenCache[key];
}

function forgetTokens() { tokenCache = {}; }

/* The last hour, oldest on the left. One bar a minute, its height the share of the busiest
   minute; a minute that stopped for a person is drawn in the human colour whatever its height,
   because "it asked me something" is not a quantity.

   Nothing is drawn that the row does not carry and nothing is drawn that the sentence does not
   say: the `aria-label` is the same hour in words, which is what makes this assertable and what
   makes it reach somebody who cannot see it. */
function drawTrace(canvas, row) {
  if (!canvas || !canvas.getContext) return;
  var tr = row.trace || {};
  var counts = tr.n || [];
  var needs = tr.needs || [];
  attr(canvas, "aria-label", tr.says || "nothing in the last hour");
  attr(canvas, "title", tr.says || "nothing in the last hour");

  /* A canvas has two sizes: the box the page lays out and the grid of pixels it owns. On a 2x
     screen they are not the same number, and a canvas that ignores the difference draws a blurred
     copy of itself. */
  var dpr = window.devicePixelRatio || 1;
  var box = canvas.getBoundingClientRect();
  var w = Math.max(1, Math.round((box.width || canvas.width) * dpr));
  var h = Math.max(1, Math.round((box.height || canvas.height) * dpr));
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;

  var ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (!counts.length) return;

  var peak = tr.peak || 1;
  var slot = w / counts.length;
  var bar = Math.max(1, Math.floor(slot) - (slot > 2 ? 1 : 0));
  var quiet = token("--idle", "#7c8794");
  var busy = token("--running", "#2f7fd4");
  var human = token("--human", "#cc3344");
  for (var i = 0; i < counts.length; i++) {
    var n = counts[i];
    var red = !!needs[i];
    if (!n && !red) continue;
    // A minute with something in it is never invisible: one pixel is "it was awake", which is the
    // difference between a quiet hour and no hour at all.
    var tall = red ? h : Math.max(1, Math.round((n / peak) * h));
    ctx.fillStyle = red ? human : (n > peak / 2 ? busy : quiet);
    ctx.fillRect(Math.round(i * slot), h - tall, bar, tall);
  }
}

/* ------------------------------------------------------------- #218: the ground, and its drift */

/* The mesh the glass skin declares: three blobs, read out of the computed stylesheet rather than
   written here a second time. `skins.py` and `skin.css` already keep one copy of those numbers
   between them and a test reads them back; a third copy in this file is the two-owners bug with
   a longer fuse. What comes back is Chromium's normalised form of each `radial-gradient`, which
   is where the ellipse's size, its place and its colour all are. */
var groundMesh = null;

function groundColours() {
  groundMesh = null;
  if ((document.body.dataset.skin || "") !== "glass") return null;
  // Read before the class that blanks it: the gradients are the source, and a source that has
  // been turned off reads as `none`.
  var was = document.body.classList.contains("has-ground");
  if (was) toggle(document.body, "has-ground", false);
  var image = getComputedStyle(document.body).backgroundImage || "";
  if (was) toggle(document.body, "has-ground", true);

  var blobs = [];
  var re = /radial-gradient\(([^()]*?)(?:ellipse\s*)?([\d.]+)%\s+([\d.]+)%\s+at\s+([\d.]+)%\s+([\d.]+)%,\s*(rgba?\([^)]*\))/g;
  var m;
  while ((m = re.exec(image)) !== null) {
    blobs.push({ rx: parseFloat(m[2]) / 100, ry: parseFloat(m[3]) / 100,
                 x: parseFloat(m[4]) / 100, y: parseFloat(m[5]) / 100, colour: m[6] });
  }
  groundMesh = blobs.length ? blobs : null;
  return groundMesh;
}

/* A pixel a second, which is why this repaints once a second and not sixty times. Drift that
   nobody can point at is the difference between a still image and a room with a window in it;
   drift anybody can point at is a page that will not sit still to be read. */
var GROUND_DRIFT_PX = 1;
var GROUND_CYCLE_S = 120;
var groundAt = 0;
var groundTimer = 0;

function groundStill() {
  return reduceMotion() ||
         !!(window.matchMedia && window.matchMedia("(prefers-reduced-transparency: reduce)").matches);
}

function drawGround() {
  var canvas = document.getElementById("ground");
  if (!canvas || !canvas.getContext) return;
  var mesh = groundMesh || groundColours();
  if (!mesh) {
    hide(canvas, true);
    toggle(document.body, "has-ground", false);
    return;
  }
  toggle(document.body, "has-ground", true);
  hide(canvas, false);

  /* Half resolution on purpose. The ground is three soft blobs with no edge in them, so the
     pixels nobody can distinguish are pixels nobody should pay for -- and this is the one canvas
     that covers the whole window. */
  var scale = 0.5;
  var w = Math.max(1, Math.round(window.innerWidth * scale));
  var h = Math.max(1, Math.round(window.innerHeight * scale));
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;

  var ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  /* A slow circle rather than a line: a blob that drifts in one direction leaves the window and
     the ground goes flat. The radius is whatever makes the path a pixel a second over the cycle,
     and it starts at zero offset -- the first frame is exactly where the stylesheet put the
     blobs, which is what the glass skin's contrast range was solved against. */
  var t = (groundAt % GROUND_CYCLE_S) / GROUND_CYCLE_S;
  var radius = (GROUND_DRIFT_PX * GROUND_CYCLE_S) / (Math.PI * 2);
  var driftX = Math.sin(t * Math.PI * 2) * radius * scale;
  var driftY = (1 - Math.cos(t * Math.PI * 2)) * radius * 0.66 * scale;
  mesh.forEach(function (blob, i) {
    var cx = blob.x * w + driftX * (i % 2 ? -1 : 1);
    var cy = blob.y * h + driftY * (i === 1 ? -1 : 1);
    var r = Math.max(blob.rx * w, blob.ry * h);
    var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, blob.colour);
    grad.addColorStop(1, transparent(blob.colour));
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  });
}

/* The same colour at zero alpha. `rgba(r, g, b, 0)` is what the stylesheet's own outer stop is,
   and a gradient that ends at a different hue has a visible ring in it. */
function transparent(colour) {
  var nums = String(colour).replace(/^rgba?\(|\)$/g, "").split(",");
  return "rgba(" + (nums[0] || 0).trim() + ", " + (nums[1] || 0).trim() + ", " +
         (nums[2] || 0).trim() + ", 0)";
}

function startGround() {
  if (groundTimer) { clearInterval(groundTimer); groundTimer = 0; }
  groundColours();
  drawGround();

  /* A skin's stylesheet is fetched *after* `applySkin` sets the link's href, so the first read of
     the mesh can land before there is anything to read -- and a ground that gave up on that first
     read stayed blank for the whole session. One retry, when the sheet is really there, and a
     timed one behind it for the case where the link was already loaded. */
  if (!groundMesh && (document.body.dataset.skin || "")) {
    var link = document.head.querySelector("link[data-skin]");
    if (link && !link.dataset.waiting) {
      link.dataset.waiting = "1";
      link.addEventListener("load", function () {
        delete link.dataset.waiting;
        startGround();
      }, { once: true });
      setTimeout(function () {
        if (!groundMesh && link.dataset.waiting) {
          delete link.dataset.waiting;
          startGround();
        }
      }, 150);
    }
    return;
  }
  // Still under reduced motion, and still when the viewer has asked for less transparency -- the
  // second is the one people forget, and it is the setting somebody turns on *because* a moving
  // translucent ground is what they cannot read over.
  if (groundMesh && !groundStill()) {
    groundTimer = setInterval(function () { groundAt += 1; drawGround(); }, 1000);
  }
}

/* The two classes `drawTile` owns on a tile, and nothing else (#215, found by #220's demo).

   It used to rebuild the whole `class` attribute from `tile state-…`, which dropped every class
   somebody else owns -- `is-selected`, `is-hidden`, `is-pinned`, `size-2`, `needs-human` -- and
   `place()` put them straight back on the next line. Two writers, two writes, twenty times a
   redraw, and `draw(el, row)` twice with the same row was never the no-op the contract claims.
   The same shape as `place()`'s own body-class write, for the same reason: the classes this
   function does not own are kept by construction rather than by being remembered. */
var TILE_OWNED = /^(tile|state-[A-Za-z_]+)$/;

function setTileState(el, state) {
  var kept = Array.prototype.filter.call(el.classList, function (name) {
    return !TILE_OWNED.test(name);
  });
  setClass(el, ["tile", "state-" + state].concat(kept).join(" "));
}

function drawTile(el, row, approvals) {
  /* Three things have to agree here or the tile lies: the chip, the sentence under it, and the
     age. The server decides which agents are quiet enough to be called unsupervised (it is the
     only side that knows whether a process holds the checkout), and it sends the sentence ONLY
     for those -- so a tile that says "needs you" never also says "nothing is supervised". */
  var isSupervised = row.supervised !== false;
  var cold = !isSupervised && !!row.not_supervised_sentence;
  var displayState = cold ? "idle" : row.state;
  setTileState(el, displayState);
  paintAccent(el, row.accent);
  drawTrace(el.querySelector(".trace"), row);
  // `needs-human` is the class focus mode filters on, and it comes from #94's fold rather than from
  // anything this page works out for itself: the chip, the toast and the filter must agree.
  toggle(el, "needs-human", !!row.needs_human);
  /* The hold is NOT dropped when the agent needs the human. It was, briefly, and that only delayed
     the disappearance: pressing Send refreshes at once, and for the moment before the agent opens
     its turn it is still the blocked agent it was -- so the hold was deleted on that first refresh
     and the tile vanished a second later, when the turn started. An agent needing the human again
     is on screen on its own merit anyway; all the hold has to do is stop claiming the credit, which
     the stylesheet handles by showing the note only while the tile is not asking for anything. */
  toggle(el, "held", held.has(row.repo));
  var holdNote = el.querySelector(".holdnote");
  if (holdNote) {
    text(holdNote.querySelector(".holdwhy"),
         "held here because you " + (held.get(row.repo) || "acted") + " — it no longer needs you");
  }
  tabbable(el, 0);
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

  drawSessionPill(el, row);

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
  drawScopeReport(el, row);
  drawCells(el, row.polls || {}, row);
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
    button.addEventListener("click", function () { closeMenu(el); focus(sib.repo); });
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
        if (tiles.has(item.repo)) focus(item.repo);
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

function applyWindow(win) {
  if (!win) return;
  if (!appliedInitialWindow) {
    appliedInitialWindow = true;
    if (win.seen) {
      checkAway(win.seen);
    }
    saveWindow({ seen: new Date().toISOString(), layout: LAYOUT, view: VIEW, screen: SCREEN });
  }
  if (win.focus !== undefined && win.focus !== needsOnly) {
    focusMode(win.focus, true);
  }
  if (win.open !== undefined && win.open !== openTile) {
    openTile = String(win.open || "");
  }
  if (win.zoomed !== undefined && win.zoomed !== focused) {
    if (win.zoomed && tiles.has(win.zoomed)) {
      focus(win.zoomed, true);
    } else if (!win.zoomed && focused) {
      unfocus(true);
    }
  }
  if (win.section && win.section !== lastSection) {
    section(win.section, true, true);
  }
  if (Array.isArray(win.held)) {
    win.held.forEach(function (repo) {
      if (!held.has(repo)) held.set(repo, "held");
    });
  }
  if (win.read && typeof win.read === "object") {
    Object.assign(readCursors, win.read);
  }
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

/* One row onto its tile, making the tile if this is the first sight of it. Both an action's
   answer (#219) and a whole snapshot come through here, so a tile cannot be drawn one way by one
   path and another way by the other. */
function patchRow(row, index) {
  if (!row || !row.repo) return null;
  var entry = tiles.get(row.repo);
  if (!entry) {
    var el = makeTile(row, index || tiles.size);
    var grid = document.getElementById("grid");
    if (grid) grid.appendChild(el);
    entry = { el: el, seq: 0 };
    tiles.set(row.repo, entry);
    (row.recent || []).forEach(function (ev) { append(el, ev); entry.seq = ev.seq; });
    try {
      var savedScroll = sessionStorage.getItem("fleet.scroll." + row.repo);
      if (savedScroll !== null) {
        entry.el.querySelector(".transcript").scrollTop = Number(savedScroll);
      }
    } catch (e) {}
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
   the payload, they are the part that goes stale fastest, and the stream brings them back within
   the second anyway. */
var SNAP_KEY = "fleet.snapshot." + W_NAME;
var SNAP_GOOD_FOR_MS = 5 * 60 * 1000;

function cacheSnapshot(data) {
  try {
    sessionStorage.setItem(SNAP_KEY, JSON.stringify({
      at: Date.now(),
      repos: (data.repos || []).map(function (row) {
        return Object.assign({}, row, { recent: [], earlier: [], run: null });
      }),
      approvals: data.approvals || [],
      desk: data.desk || null,
      spend: data.spend || {},
      theme: data.theme || null,
    }));
  } catch (e) { /* a private window, or no room: the desk simply loads the slow way */ }
}

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
  if (data.theme) { applyTheme(data.theme.css, data.theme.theme); applySkin(data.theme.skin); }
  if (data.desk) desk.desk = data.desk;
  lastApprovals = data.approvals || [];
  data.repos.forEach(function (row, i) { patchRow(row, i); });
  hide(document.getElementById("empty"), true);
  // Said, not hidden: the desk on the screen is the last one this window saw, and the operator is
  // told so rather than left to find out.
  toggle(document.body, "is-stale", true);
  place();
  return true;
}

function refresh() {
  if (pendingRefresh) return pendingRefresh;
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
        // Removed from the registry. Its tile goes, but not silently: it keeps a dock chip naming
        // the command that restores it, because a transcript disappearing with no explanation is
        // exactly the "where did it go" this slice exists to answer.
        departed.set(name, { path: (entry.row && entry.row.path) || "<path>" });
        entry.el.remove();
        tiles.delete(name);
      }
    });
    var need = data.repos.filter(function (r) { return r.needs_human; }).length;
    var fleetSpend = data.spend || {};
    var counts = document.getElementById("counts");
    text(counts,
         data.repos.length + " agents" + (need ? "  ·  " + need + " need you" : "") +
         (needsOnly && held.size ? "  ·  " + held.size + " held" : "") +
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
    if (data.desk) {
      desk.desk = data.desk;
      if (data.desk.windows && data.desk.windows[W_NAME]) {
        applyWindow(data.desk.windows[W_NAME]);
      }
    }
    if (data.theme) {
      applyTheme(data.theme.css, data.theme.theme);
      applySkin(data.theme.skin);
      startGround();                              // #218: the ground follows the skin
    }
    if (typeof data.preflight === "boolean") PREFLIGHT = data.preflight;
    toggle(document.body, "is-stale", false);
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

function connect() {
  if (source) source.close();
  var link = document.getElementById("link");
  source = new EventSource(q("/api/events", { since: cursors() }));
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
    desk.desk = JSON.parse(m.data);
    if (desk.desk.windows && desk.desk.windows[W_NAME]) {
      applyWindow(desk.desk.windows[W_NAME]);
    }
    place();
    if (VIEW === "verify" || LAYOUT === "screens") deskSoon();
  });
  source.addEventListener("theme", function (m) {
    try {
      var d = JSON.parse(m.data);
      applyTheme(d.css, d.theme);
      applySkin(d.skin);
      if (d.accents) {
        Object.keys(d.accents).forEach(function (repo) {
          if (tiles.has(repo)) paintAccent(tiles.get(repo).el, d.accents[repo]);
        });
      }
      /* #218: a canvas holds pixels, not rules, so a palette that changed under it leaves it the
         old colour until something repaints. The cache of token values goes with the palette and
         every trace is drawn again from the row it already has. */
      forgetTokens();
      startGround();
      tiles.forEach(function (entry) { drawTrace(entry.el.querySelector(".trace"), entry.row); });
      document.querySelectorAll("#bands .band").forEach(function (li) {
        var entry = tiles.get(li.dataset.repo);
        if (entry) drawTrace(li.querySelector(".b-trace"), entry.row);
      });
    } catch (err) {}
  });
  source.addEventListener("tick", function () {
    setClass(link, "dot live");
    text(link, "live");
  });
  source.onopen = function () { streamDead = false; setClass(link, "dot live"); text(link, "live"); };
  source.onerror = function () {
    streamDead = true;
    setClass(link, "dot lost");
    text(link, "reconnecting");
    // EventSource reconnects on its own, but the page must not trust what it drew in between.
    setTimeout(function () { refresh().then(connect); }, 2000);
  };
}

/* ------------------------------------------------------------------- focus mode and the keyboard */

/* ------------------------------------------------------- what the two focuses actually are (#207)

   `focus()` zoomed one tile and `focusMode()` filtered for the ones that need a person: two modes
   named alike, side by side, and the toolbar's *back to grid* undid only the first. They are
   `openAgent` and *needs me* now, with the old names kept as aliases because the page globals the
   regression tests call keep their names.

   Not literally `open`: a bare `function open()` in a non-module script replaces `window.open` for
   the whole page, and a name that shadows a platform function to read slightly better is a trade
   this page does not need to make. */
function openAgent(name, skipPost) {
  unread.delete(name);                       // looking at it is what "read" means
  var entry = tiles.get(name);
  if (entry && entry.seq) {
    readCursors[name] = entry.seq;
  }
  bell();
  drawer(false);
  if (location.hash !== "#tile=" + name) history.replaceState(null, "", "#tile=" + name);
  /* In the column there is no zoom to enter: everything that is not open is a band already, so
     "focus this agent" and "open this agent" are the same gesture. Every caller -- a toast's
     anchor, a notification row, a search hit, the away strip -- therefore lands on the right thing
     without knowing which arrangement it is in. */
  if (LAYOUT === "column") {
    openBand(name, skipPost);
    if (!skipPost) saveWindow({ read: readCursors });
    return;
  }
  var mark = gesture("open:zoom");
  transitionLayout(function () {
    focused = name;
    toggle(document.body, "focused", true);
    hide(document.getElementById("unfocus"), false);
    tiles.forEach(function (entry2, key) { toggle(entry2.el, "is-focused", key === name); });
    settle(mark);
  });
  if (!skipPost) saveWindow({ zoomed: name, read: readCursors });
}

/* Out of the zoom, where there is one. In the column there is nothing to leave -- everything that
   is not open is a band already -- so `Esc` there is `backToPrevious()` instead. */
function backAgent(skipPost) {
  transitionLayout(function () {
    focused = null;
    toggle(document.body, "focused", false);
    hide(document.getElementById("unfocus"), true);
    tiles.forEach(function (entry) { toggle(entry.el, "is-focused", false); });
  });
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  if (!skipPost) saveWindow({ zoomed: "" });
}

/* The names the rest of this file, the IDE shells and the regression tests already use. */
var focus = openAgent;
var unfocus = backAgent;

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
  // Only if the mode is what is keeping it off the glass. An anchor almost always names a tile
  // that needs somebody -- which focus mode is showing already -- and turning the mode off to
  // reach a tile that was never hidden throws away the pass the operator was in the middle of.
  if (quieted(name)) focusMode(false);
  focus(name);
}

window.addEventListener("hashchange", followHash);

document.getElementById("unfocus").addEventListener("click", unfocus);

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    // The nearest open thing closes first, and nothing else: a popover (#180), then the card (#183).
    if (closeModelCard()) { e.stopImmediatePropagation(); return; }
    if (closeMenus()) { e.stopImmediatePropagation(); return; }
    if (closePopovers()) { e.stopImmediatePropagation(); return; }
    var card = document.getElementById("dispatch");
    if (card && !card.hidden) { closeDispatch(); e.stopImmediatePropagation(); return; }
    if (typing) document.activeElement.blur();
    // In the column there is no zoom to leave, so `Esc` is "show me the last one again" -- which is
    // the other half of the glance the column is for.
    else if (LAYOUT === "column") backToPrevious();
    else unfocus();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[1-9]$/.test(e.key)) {
    if (LAYOUT === "column") {
      // The same rule as below, one arrangement further on: the digit is the number printed on the
      // band, so it counts BANDS and not tiles -- the open agent has no number, because it is
      // already open.
      var band = document.querySelectorAll("#bands .band:not([hidden])")[Number(e.key) - 1];
      if (band && band.dataset.repo) openBand(band.dataset.repo);
      return;
    }
    // The number printed on a tile comes from the arrangement, so the key that focuses it must
    // too: registry order meant the badge said 3 and pressing 3 focused something else. The
    // *visible* order (#173), so a digit cannot zoom a tile that is not on the glass -- which
    // blanked the window, zoom hiding every other tile and focus mode already hiding that one.
    var name = visibleOrder()[Number(e.key) - 1];
    if (!name) return;
    // Zooming a tile focus mode is quieting was a blank window: zoom hides every other tile and
    // the mode was already hiding this one. The operator pressed the number printed on that tile,
    // so the mode gives way rather than the window going dark -- the same answer `#tile=` gives.
    if (quieted(name)) focusMode(false);
    focus(name);
    return;
  }
  if ((e.key === "j" || e.key === "k") && LAYOUT === "column") {
    stepColumn(e.key === "j" ? 1 : -1);
    e.preventDefault();
    return;
  }
  if (e.key === "r" || e.key === "m") {
    // The band or the tile the keyboard is on -- the same two keys on either, because the three
    // controls are the same three on either.
    var host = document.activeElement && document.activeElement.closest
      ? (document.activeElement.closest(".band") || document.activeElement.closest(".tile")) : null;
    var name = host ? host.dataset.repo : (LAYOUT === "column" ? openName() : focused);
    if (!name) return;
    if (e.key === "r") doRefresh(name, host ? host.querySelector('[data-tool="refresh"]') : null);
    else openModelCard(name, host ? host.querySelector('[data-tool="model"]') : null);
    e.preventDefault();
    return;
  }
  if (e.key === "h") {
    // Hide the tile the operator is on. Every drag gesture has a keyboard equivalent, and so does
    // this one -- a desk that can only be arranged with a mouse cannot be arranged by someone typing.
    var onTile = document.activeElement && document.activeElement.closest && document.activeElement.closest(".tile");
    if (onTile && onTile.dataset.repo) { setHidden(onTile.dataset.repo, true); return; }
  }
  if (e.key === "n") { section("drawer"); return; }
  if (e.key === "b") { section("board"); return; }
  if (e.key === "a") {
    var entry = focused ? tiles.get(focused) : null;
    if (entry && entry.el.dataset.approval && !entry.el.querySelector(".approval").hidden) {
      entry.el.querySelector(".approve").click();
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
var setLink = document.getElementById("setbtn");
if (setLink) setLink.href = q("/settings");

refresh().then(function () {
  connect();
  loadNotifications();
  // The anchor is answered *after* the desk, not beside it: whether a tile is hidden is the
  // server's arrangement, and a `#tile=` that lands before that has loaded reads every tile as on
  // the glass -- so the one thing it was asked to do, reopen a tile that is not, it did not (#173).
  loadDesk().then(followHash);
  if (LAYOUT === "roles" && VIEW === "board") boardPanel(true);
  if (LAYOUT === "screens" && !SCREEN) { boardPanel(true); trayPanel(true); }
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
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
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
  li.addEventListener("click", function () { if (tiles.has(item.repo)) focus(item.repo); });
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
  document.querySelectorAll(".side-tabs .segment").forEach(function (b) {
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
    return new Promise(function (done) {
      dir.createReader().readEntries(function (children) {
        Promise.all(children.map(function (child) {
          if (out.length >= SCOPE_MAX_FILES) return Promise.resolve();
          if (child.isDirectory) return walk(child);
          return new Promise(function (got) { child.file(function (f) { out.push(f); got(); }, got); });
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

/* One card, two homes (#183): the tile's slot when the tile is on the glass, else under the rail. */
function onTheGlass(repo) {
  var entry = tiles.get(repo);
  return !!(entry && entry.el.offsetParent !== null && !entry.el.classList.contains("is-hidden"));
}

function dispatchHome(repo) {
  if (onTheGlass(repo)) return tiles.get(repo).el.querySelector(".dispatch-slot");
  return document.getElementById("railslot");
}

function dispatchCard(key, repo) {
  var card = document.getElementById("dispatch");
  var rows = card.querySelector(".dispatch-rows");
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
    if (r && r.ok) { boardPanel(false); closeDispatch(); said(repo, ""); focus(repo); }
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
    dispatch(card.dataset.key || "", card.dataset.repo || "", card.querySelector(".brief").value.trim());
  });
  card.querySelector(".brief").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { card.querySelector(".dispatch-go").click(); e.preventDefault(); }
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
      var li = pattern.cloneNode(true);
      hide(li, false);
      setData(li, "repo", name);
      var button = li.querySelector(".rail-open");
      attr(button, "aria-label", name);
      attr(button, "title", "drop a ticket here to start it on " + name);
      button.addEventListener("click", function () { focus(name); });
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

document.getElementById("tickets").addEventListener("keydown", function (e) {
  var li = e.target.closest && e.target.closest("li[data-key]");
  if (!li) return;
  var row = board.filter(function (r) { return r.key === li.dataset.key; })[0];
  if (!row) return;
  // Stops here: the page's own `1`-`9` zooms a tile, closing the board under the card.
  if (/^[1-9]$/.test(e.key)) {
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
  var needle = (document.getElementById("boardsearch").value || "").toLowerCase();
  // A redraw keeps the keyboard on its row (#183).
  var had = document.activeElement && list.contains(document.activeElement) ?
            (document.activeElement.closest("li[data-key]") || {}).dataset : null;
  while (list.firstChild) list.removeChild(list.firstChild);
  var shown = rows.filter(function (r) {
    return !needle || (r.key + " " + r.summary + " " + r.status).toLowerCase().indexOf(needle) >= 0;
  });
  shown.forEach(function (r) { list.appendChild(ticketRow(r)); });
  hide(document.getElementById("noboard"), shown.length > 0);
  if (had && had.key) {
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

document.querySelectorAll(".side-tabs .segment").forEach(function (b) {
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
    desk = data;
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
      if (tiles.has(hit.project) && LAYOUT === "grid") focus(hit.project);
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
      var needle = document.getElementById("find").value.trim();
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

/* ------------------------------------------------------------------------- the layouts (#133) */

/* One selected project, shared by every window on this server. It is a POST and not a URL fragment
   because the point is that the *other* windows hear about it: clicking a tile on the left monitor
   is what changes the centre one. */
/* The desk state is merged, never replaced. `/api/select` answers with the selection and the
   screen pinning and says nothing about the arrangement, so assigning its answer wholesale dropped
   `arrangement` on the floor: clicking any tile un-widened every tile you had widened and unpinned
   every tile you had pinned, until the next `/api/desk` poll fifteen seconds later put them back. */
/* #219: an answer that is older than what this page already has is not an answer, it is an echo.
   Five gestures in a second is five posts in flight, and they do not come back in the order they
   went: a resize answered after the move that followed it put the tiles back in the order they
   were in before the move. The desk carries a `version` that only ever rises, so the check is one
   comparison and the losing answer is simply dropped -- the winning one already describes the
   same arrangement. `selected` has no version of its own and is set locally, so it is merged
   either way. */
function mergeDesk(answer) {
  if (!answer) return;
  var next = Object.assign({}, desk.desk);
  var stale = answer.version !== undefined && desk.desk.version !== undefined &&
              Number(answer.version) < Number(desk.desk.version);
  ["selected", "screens", "version", "arrangement"].forEach(function (k) {
    if (answer[k] === undefined) return;
    if (stale && k !== "selected") return;
    next[k] = answer[k];
  });
  desk.desk = next;
}

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

function getLayoutArrangement() {
  var arr = (desk.desk && desk.desk.arrangement) || {};
  return arr[LAYOUT] || { order: [], size: {}, pinned: [] };
}

function getEffectiveOrder() {
  var curArr = getLayoutArrangement();
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
function isHidden(name) {
  var entry = tiles.get(name);
  if (entry && entry.el.classList.contains("needs-human")) return false;
  return ((getLayoutArrangement().hidden) || []).indexOf(name) >= 0;
}

function visibleOrder() {
  return getEffectiveOrder().filter(function (n) { return !isHidden(n); });
}

/* Focus mode is not part of the arrangement -- it quiets tiles with a class while `hidden` stays
   where the operator put it -- so this is "a mode is keeping it off the glass right now" and
   `isHidden` is "the operator put it away". A tile being held is one the operator asked to keep
   through the pass, so the mode is not quieting that one. */
function quieted(name) {
  if (!needsOnly) return false;
  var entry = tiles.get(name);
  return !!entry && !entry.el.classList.contains("needs-human") && !held.has(name);
}

/* #219. Every arrangement change goes the same way: paint it, post it, and put it back with the
   server's own words on the notice line if it refuses. The paint is inside the frame the gesture
   happened in -- a page that waits for a round trip before moving a tile is a page that feels
   like a form, whatever the round trip costs -- and the `desk` frame that follows is what makes
   every other window agree.

   `patch` is what to send; `apply` writes it into the local arrangement and answers with a
   function that writes the old one back. */
function arrangeNow(patch, apply, what) {
  var mark = gesture("arrange:" + (what || "change"));
  var undo = apply();
  transitionMove(function () { place(); });
  settle(mark);
  return post("arrange", Object.assign({ layout: LAYOUT }, patch)).then(function (r) {
    if (r && r.ok) { mergeDesk(r); place(); return r; }
    // Refused. The arrangement goes back to what it was and the refusal is said out loud, because
    // a tile that silently returns to where it was is a page the operator stops trusting.
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
}

function setHidden(name, hide) {
  var curArr = getLayoutArrangement();
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
  var curArr = getLayoutArrangement();
  var sizes = curArr.size || {};
  var pinned = curArr.pinned || [];
  var shown = visibleOrder();

  // #217: not while a tile is under the hand. A draw that reorders the DOM mid-drag is a tile
  // that jumps out from under the cursor, and the stream draws several times a second.
  if (dragging) return;

  var inDom = Array.prototype.map.call(grid.children, function (el) { return el.dataset.repo; });
  var needsMove = inDom.join("\u0000") !== order.filter(function (n) { return tiles.has(n); }).join("\u0000");
  var focused = document.activeElement;
  var refocus = needsMove && focused && focused.closest && focused.closest(".tile") ? focused : null;

  // FLIP, first half: where every tile is *now*, before the DOM moves. A tile that reorders by
  // `appendChild` alone teleports, and a grid reshuffling while agents talk reads as flicker, not
  // movement -- the operator cannot see it is the same tile, lower down. Measured only when
  // something is moving, and not at all when the viewer has asked for less of it.
  var first = (needsMove && !reduceMotion() && !inViewTransition) ? measureTiles() : null;

  order.forEach(function (name, index) {
    var entry = tiles.get(name);
    if (entry && entry.el) {
      if (needsMove) grid.appendChild(entry.el);
      // Hidden is a class rather than `el.hidden`, so the tile keeps its slot in `order` and
      // reopening puts it back where it was rather than at the end.
      var off = shown.indexOf(name) < 0;
      toggle(entry.el, "is-hidden", off);
      // The number is the key that focuses it, so it counts what is on the glass.
      text(entry.el.querySelector(".n"), off ? "" : String(shown.indexOf(name) + 1));
      var sz = sizeOf(sizes, name);
      // One owner for the footprint: two custom properties the stylesheet spans on. `size-2`
      // stays as a state marker for anything that reads "is this one widened", but it is no
      // longer what makes the tile wide -- a class and an inline style both setting
      // `grid-column` is the two-owners bug the contract is named after.
      style(entry.el, "--cols", String(sz.cols));
      style(entry.el, "--rows", String(sz.rows));
      toggle(entry.el, "size-2", sz.cols === 2);
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

/* Only tiles that are actually laid out. A hidden one -- focus mode, or a solo view -- has a zero
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

/* Reorder by pointer, on a handle. `host` is what moves and `name` is what it is called; the grid
   passes a tile and its head, the column a band and its own. Both write the same `order`, because
   both are the same arrangement seen from two sides. */
function bindDragToReorder(handle, host, name) {
  handle.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    /* A press on a control inside the handle belongs to that control -- unless the handle *is*
       the control, which is what a band is: one button filling the row, with its three tools
       beside it rather than in it. The tile's handle is a plain head, so every button in it is
       somebody else's. */
    var ctrl = e.target.closest("button, input, select, textarea, a");
    if (ctrl && ctrl !== handle) return;
    var siblings = Array.prototype.filter.call(host.parentNode.children, function (n) {
      return n !== host && n.dataset && n.dataset.repo && !n.hidden;
    });
    if (!siblings.length) return;                // nothing to reorder past

    var from = { x: e.clientX, y: e.clientY };
    var started = false;
    var target = null;                           // { el, before } while one is lit

    /* The capture is taken when the drag begins, not when the pointer goes down. While an element
       holds the capture the browser retargets the compatibility mouse events to it as well, so
       capturing on `pointerdown` sent the `click` that ends an ordinary press to the head rather
       than to the repository name inside it -- and clicking the name, which is how a tile is
       zoomed, silently stopped working. */
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
        // Across in the grid, down in the column: the axis the list runs along is the axis the
        // halves are measured on, or "before" means the wrong side of the wrong edge.
        var down = LAYOUT === "column";
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
      // A pointer drag still ends in a `click`, and on a tile head that click selects the project
      // while on a band it opens the agent. Neither is what the hand just asked for, so the one
      // that follows a real drag is swallowed and the listener takes itself off again.
      var swallow = function (ev) {
        ev.stopPropagation();
        ev.preventDefault();
        document.removeEventListener("click", swallow, true);
      };
      document.addEventListener("click", swallow, true);
      setTimeout(function () { document.removeEventListener("click", swallow, true); }, 0);
      if (landed) dropTileBefore(name, landed.el.dataset.repo, landed.before);
    };

    // Esc cancels a drag in flight and leaves the order alone (HIG *Drag and drop*). Captured on
    // the document, because the capture has taken the keyboard's usual route away.
    var onKey = function (ev) {
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      ev.preventDefault();
      clear();
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

/* Where a drop lands, in one place, so the pointer and the keyboard agree about what "before"
   means. Optimistic: the order changes under the hand and the server's answer is what the next
   draw reads. */
function dropTileBefore(name, onto, before) {
  if (!name || !onto || name === onto) return;
  var order = getEffectiveOrder();
  var from = order.indexOf(name);
  if (from >= 0) order.splice(from, 1);
  var at = order.indexOf(onto);
  if (at < 0) return;
  order.splice(before ? at : at + 1, 0, name);
  var arr = getLayoutArrangement();
  var was = (arr.order || []).slice();
  arrangeNow({ order: order }, function () {
    arr.order = order;
    return function () { arr.order = was; };
  }, "drop");
}

/* The grid's own tracks, measured rather than assumed. `auto-fit` means the number of columns is
   whatever the window is wide enough for, so "one track" is a number only the browser knows. */
function gridTracks() {
  var grid = document.getElementById("grid");
  if (!grid) return [];
  var cols = getComputedStyle(grid).gridTemplateColumns || "";
  return cols.split(" ").map(parseFloat).filter(function (n) { return n > 0; });
}

/* Resize from the right and the bottom edge, with the snap shown before the hand comes up. */
function bindResizeEdges(el, name) {
  el.querySelectorAll(".rsz").forEach(function (grip) {
    var axis = grip.dataset.edge === "y" ? "rows" : "cols";
    grip.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      var was = sizeOf(getLayoutArrangement().size, name);
      var box = el.getBoundingClientRect();
      var tracks = gridTracks();
      var track = tracks.length ? tracks[0] : box.width;
      var third = window.innerHeight / 3;
      var want = { cols: was.cols, rows: was.rows };
      toggle(grip, "is-resizing", true);
      try { grip.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer */ }

      var onMove = function (ev) {
        if (axis === "cols") {
          var wide = ev.clientX - box.left;
          want.cols = clampSpan(Math.round(wide / (track + 10)), Math.max(1, tracks.length));
        } else {
          var tall = ev.clientY - box.top;
          want.rows = clampSpan(Math.round(tall / third), SIZE_MAX_ROWS);
        }
        showResizeGhost(box, want, track, third);
      };
      var finish = function (apply) {
        hideResizeGhost();
        toggle(grip, "is-resizing", false);
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        document.removeEventListener("pointercancel", onCancel);
        document.removeEventListener("keydown", onKey, true);
        try { grip.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
        if (apply) transitionLayout(function () { setTileSize(name, want.cols, want.rows); });
      };
      var onUp = function () { finish(true); };
      var onCancel = function () { finish(false); };
      var onKey = function (ev) {
        if (ev.key !== "Escape") return;
        ev.stopPropagation();
        ev.preventDefault();
        finish(false);
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
      document.addEventListener("pointercancel", onCancel);
      document.addEventListener("keydown", onKey, true);
      showResizeGhost(box, want, track, third);
    });
  });
}

/* What will happen, drawn where it will happen. One element for the page: there is only ever one
   gesture in flight, and a ghost per tile is a ghost that gets left behind. */
function showResizeGhost(box, want, track, third) {
  var ghost = document.getElementById("rszghost");
  if (!ghost) return;
  var width = want.cols * track + (want.cols - 1) * 10;
  var height = Math.max(box.height, want.rows * third);
  style(ghost, "left", Math.round(box.left) + "px");
  style(ghost, "top", Math.round(box.top) + "px");
  style(ghost, "width", Math.round(width) + "px");
  style(ghost, "height", Math.round(height) + "px");
  text(ghost.querySelector(".rsz-says"),
       want.cols + " \u00d7 " + want.rows + (want.cols === 1 && want.rows === 1 ? "" : ""));
  hide(ghost, false);
}

function hideResizeGhost() {
  var ghost = document.getElementById("rszghost");
  if (ghost) hide(ghost, true);
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

/* Every change to where things are goes through here: opening a band, going back, hiding a tile,
   reordering the grid. `startViewTransition` is the good path -- the browser holds the old frame,
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
  var arr = getLayoutArrangement();
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

/* #217. A tile's footprint is two numbers now. `size: 2` is what every arrangement written
   before this holds -- one number meaning two columns wide -- and it reads as `{cols: 2, rows: 1}`
   here exactly as it does on the server, so a desk saved by an older build opens with its tiles
   the width they were left. */
var SIZE_MAX_COLS = 4;
var SIZE_MAX_ROWS = 3;

function sizeOf(sizes, name) {
  var v = (sizes || {})[name];
  if (v && typeof v === "object") {
    return { cols: clampSpan(v.cols, SIZE_MAX_COLS), rows: clampSpan(v.rows, SIZE_MAX_ROWS) };
  }
  return { cols: clampSpan(v, SIZE_MAX_COLS), rows: 1 };
}

function clampSpan(value, most) {
  var n = Math.round(Number(value) || 1);
  return Math.max(1, Math.min(most, n));
}

/* Both writers go through here: the button, the keys and the edge handle all mean "this tile is
   this many tracks wide and this many tall", and there is one place that says what that costs. */
function setTileSize(repo, cols, rows) {
  var curArr = getLayoutArrangement();
  var sizes = Object.assign({}, curArr.size || {});
  var want = { cols: clampSpan(cols, SIZE_MAX_COLS), rows: clampSpan(rows, SIZE_MAX_ROWS) };
  var now = sizeOf(sizes, repo);
  if (now.cols === want.cols && now.rows === want.rows) return Promise.resolve();
  sizes[repo] = want;
  // Optimistic, then confirmed -- the tile changes under the hand and the server's answer is what
  // the next draw reads. Two quick presses both read the local arrangement, so neither is lost.
  var was = Object.assign({}, curArr.size || {});
  return arrangeNow({ size: sizes }, function () {
    curArr.size = sizes;
    return function () { curArr.size = was; };
  }, "size");
}

function toggleTileSize(repo) {
  var now = sizeOf(getLayoutArrangement().size, repo);
  return setTileSize(repo, now.cols > 1 ? 1 : 2, now.rows);
}

/* Alt+Shift+arrows. Alt+arrows already moves a tile and has since #5, so resizing takes the
   shifted pair rather than stealing a gesture the operator has learned. */
function resizeTile(repo, dCols, dRows) {
  var now = sizeOf(getLayoutArrangement().size, repo);
  return setTileSize(repo, now.cols + dCols, now.rows + dRows);
}

/* Both toggles write the local arrangement BEFORE the round trip, not only after it. Reading
   `desk.desk` and posting without updating it meant two quick clicks both read the same state and
   the second overwrote the first: pin two tiles in a second and one of them silently came back
   unpinned. The returned promise is what lets a caller sequence them. */
function toggleTilePin(repo) {
  var curArr = getLayoutArrangement();
  var pinned = (curArr.pinned || []).slice();
  var idx = pinned.indexOf(repo);
  if (idx >= 0) pinned.splice(idx, 1); else pinned.push(repo);
  var was = (curArr.pinned || []).slice();
  return arrangeNow({ pinned: pinned }, function () {
    curArr.pinned = pinned;
    return function () { curArr.pinned = was; };
  }, "pin");
}

/* Which project this window is showing, when it is showing exactly one. `screens` is the shared
   pinning; a screen with nothing pinned falls back to the Nth registered repo, so opening
   `?layout=screens&screen=2` on a fresh fleet shows something rather than an empty monitor. */
function solo() {
  var names = Array.from(tiles.keys());
  if (LAYOUT === "column") return openName();
  if (LAYOUT === "screens" && SCREEN) {
    var pinned = (desk.desk.screens || [])[SCREEN - 1];
    return pinned || names[SCREEN - 1] || "";
  }
  if (VIEW === "verify") return desk.desk.selected || names[0] || "";
  return "";
}

/* ------------------------------------------------------- hide, refresh and the model (#205)

   The same three, in the same order, with the same keys, on the band and on the tile. The
   operator's sentence was *active and inactive both*, and a control that exists in one place and
   not the other is what this slice was asked to stop. */

/* The model name, short enough for a 28px button. Never a closed list -- which names this build
   accepts has never been measured -- so this only shortens what it is given. */
function shortModel(name) {
  var value = String(name || "").trim();
  if (!value) return "auto";
  return value.replace(/^claude-/, "").replace(/-\d{8}$/, "");
}

/* What the model button says when you hover it, on the band and on the tile alike: what this agent
   is actually running, and what it was configured to run. Written once so the two cannot drift. */
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
  document.getElementById("mc-model").value = row.model || "";
  document.getElementById("mc-effort").value = row.effort || "";
  text(document.getElementById("mc-note"), "takes effect on the agent's next turn");
  var all = document.getElementById("mc-all");
  all.href = q("/settings") + "#model-" + encodeURIComponent(repo);

  loadModelChoices().then(function (choices) {
    fillDatalist("mc-models", choices.seen);
    fillDatalist("mc-efforts", choices.efforts);
  });

  hide(card, false);
  if (anchor && anchor.getBoundingClientRect) {
    var box = anchor.getBoundingClientRect();
    var width = card.offsetWidth || 280;
    card.style.top = Math.min(window.innerHeight - 40, box.bottom + 6) + "px";
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
                          model: document.getElementById("mc-model").value.trim(),
                          effort: document.getElementById("mc-effort").value.trim() }] };
  post("settings", body).then(function (r) {
    if (r && r.ok) {
      text(document.getElementById("mc-note"), "saved — it reaches the agent on its next turn");
      refresh();
      return;
    }
    text(document.getElementById("mc-note"), (r && r.error) + ((r && r.hint) ? " — " + r.hint : ""));
  });
}

/* One binder for both surfaces, so the band and the tile cannot drift apart. */
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

/* -------------------------------------------------------------------------- the column (#203) */

/* Which agent is open, decided once. The window's own choice wins; then the selection every window
   shares, so a fresh window opens on whatever the desk is already looking at; then the first band.
   A hidden or departed name never wins -- an arrangement that opened onto nothing would be the
   blank window this layout exists to stop. */
function openName() {
  if (openTile && tiles.has(openTile) && !isHidden(openTile)) return openTile;
  var sel = desk.desk.selected;
  if (sel && tiles.has(sel) && !isHidden(sel)) return sel;
  var shown = visibleOrder();
  // A pinned agent is on the glass already, and `getEffectiveOrder` puts the pins first -- so
  // falling back to "the first one" would mean that pinning one agent silently stopped anything
  // else from ever being open. The default is the first agent that is NOT pinned.
  var pinned = (getLayoutArrangement().pinned) || [];
  var free = shown.filter(function (name) { return pinned.indexOf(name) < 0; });
  return free[0] || shown[0] || "";
}

/* Everything filling the glass. A pinned tile is always open -- that is what pinning meant in the
   grid too, and pins split `main` evenly -- so the set is the pins plus the one open agent. */
function openSet() {
  var out = [];
  if (LAYOUT !== "column") {
    var one = solo();
    return one ? [one] : [];
  }
  var shown = visibleOrder();
  ((getLayoutArrangement().pinned) || []).forEach(function (name) {
    if (shown.indexOf(name) >= 0 && out.indexOf(name) < 0) out.push(name);
  });
  var open = openName();
  if (open && out.indexOf(open) < 0) out.push(open);
  return out;
}

/* Open one, and remember what was open before it so `Esc` can go back. A pinned tile is already on
   the glass, so clicking its band is not a swap -- it simply selects it. */
function openBand(name, skipPost) {
  if (!name || !tiles.has(name)) return;
  var was = openName();
  if (was && was !== name) previousOpen = was;
  openTile = name;
  // Marked inside the callback, not around the call: the view-transition path runs it on the
  // frame after the browser has taken its snapshot, and a mark closed before the work happened
  // would report nought and mean nothing (#219).
  var mark = gesture("open:band");
  transitionLayout(function () { choose(name); place(); settle(mark); });
  if (!skipPost) saveWindow({ open: name });
}

function backToPrevious() {
  if (!previousOpen || !tiles.has(previousOpen)) return false;
  var going = previousOpen;
  previousOpen = openName();
  openTile = going;
  transitionLayout(function () { choose(going); place(); });
  saveWindow({ open: going });
  return true;
}

/* The one function that decides what this window shows. Body classes only: the stylesheet is the
   layout, and every arrangement is the same DOM, so a tile cannot mean one thing on one screen and
   something else on another. */
/* The dock (#173): one chip per tile that is not on the glass.

   Five `display:none` rules and one `.remove()` used to take tiles away as side effects of modes --
   zoom, focus mode, a solo window, the laptop view, and a repository leaving the registry -- and
   nothing said where they went. Everything off the glass is a chip here, and a chip is one click
   from being back. A chip that needs a person is red and chimes like the tile would: hiding a
   demand is how a demand gets missed, which is the one rule the operator's own choice cannot
   override. */
var departed = new Map();      /* repos that left the registry, kept a day so their tile is not just gone */

function drawDock() {
  var dock = document.getElementById("dock");
  // In the column the dock's job is the column's (#203): everything not open is a band already, so
  // drawing both would be two answers to one question and two places to click.
  if (LAYOUT === "column") { hide(dock, true); return; }
  var list = dock.querySelector(".dock-chips");
  var pattern = list.querySelector(".dock-chip");
  var zoomed = document.body.classList.contains("focused");
  var shown = visibleOrder();

  var off = [];
  getEffectiveOrder().forEach(function (name) {
    var entry = tiles.get(name);
    if (!entry) return;
    if (zoomed) {
      // While one tile fills the window, the other eight are the ones you cannot see.
      if (!entry.el.classList.contains("is-focused")) off.push({ name: name, why: "zoomed past" });
      return;
    }
    if (shown.indexOf(name) < 0) off.push({ name: name, why: "hidden" });
    else if (quieted(name)) off.push({ name: name, why: "quiet" });
  });
  departed.forEach(function (row, name) { off.push({ name: name, why: "removed", gone: row }); });

  if (!off.length) { hide(dock, true); return; }
  hide(dock, false);
  text(dock.querySelector(".dock-label"), off.length + " not on the glass");

  // One chip per project (#175). A project's checkouts are hidden and pinned as one, so they leave
  // the glass together, and two chips for one piece of work is two things to click for one
  // decision. The chip says how many come back, so nobody is surprised by the second tile.
  var chips = [];
  var groups = new Map();
  off.forEach(function (item) {
    var entry = tiles.get(item.name);
    var project = (entry && entry.row && entry.row.project) || item.name;
    var key = project + "\u0000" + item.why;
    var group = groups.get(key);
    if (group) { group.members.push(item.name); return; }
    group = { project: project, members: [item.name], why: item.why,
              gone: item.gone, name: item.name, key: key };
    groups.set(key, group);
    chips.push(group);
  });

  /* Keyed and created once (#215). Every chip was cloned from the pattern and re-listened on every
     draw -- about two and a half times a second while an agent talks -- so a chip could not be
     hovered, focused or clicked reliably, and any transient state on it was gone by the next pass. */
  patchList(list, chips, function (item) { return item.key; },
    function () {
      var li = pattern.cloneNode(true);
      hide(li, false);
      li.querySelector(".dock-open").addEventListener("click", function () {
        var item = li._item;
        if (!item || item.gone) return;
        if (item.why === "hidden") setHidden(item.name, false);
        else if (item.why === "quiet") focusMode(false);
        else backAgent();
        focus(item.name);
      });
      return li;
    },
    function (li, item) {
      li._item = item;
      var several = item.members.length > 1;
      var entry = tiles.get(item.name);
      var row = entry ? entry.row : null;
      var needs = item.members.some(function (name) {
        var e = tiles.get(name);
        return !!e && e.el.classList.contains("needs-human");
      });
      setClass(li, "dock-chip" + (needs ? " needs-human" : "") + (item.gone ? " departed" : ""));
      text(li.querySelector(".dc-name"), several ? item.project : item.name);
      text(li.querySelector(".dc-chip"),
           several ? item.members.length + " checkouts"
                   : item.gone ? "removed from the registry"
                   : needs ? ((row && row.why) || "needs you")
                   : ((row && row.state ? row.state : "") +
                      (row && row.at ? " · " + agentAge(ageOf(row)) : "")));
      var badge = li.querySelector(".dc-badge");
      var unreadN = item.members.reduce(function (n, name) { return n + (unread.get(name) || 0); }, 0);
      hide(badge, !unreadN);
      text(badge, String(unreadN));
      attr(li.querySelector(".dock-open"), "title", item.gone
        ? "`ad-fleet repo add " + item.gone.path + "` restores it"
        : several ? "show " + item.project + ": " + item.members.join(", ")
        : (needs ? (row && row.why) || "needs you" : "show " + item.name));
    });
}

function ageOf(row) {
  return row && typeof row.last_event_age_s === "number" ? row.last_event_age_s : 0;
}

/* Every class `place()` owns. Declared once so that what it sets and what it clears cannot drift
   apart -- which is what `test_fleet_board_desk.py` has always been asserting, and what it reads
   now instead of a `classList.remove` call. */
var BODY_LAYOUT_CLASSES = ["layout-column", "layout-grid", "layout-roles", "layout-screens",
                           "view-board", "view-agents", "view-verify", "solo", "panels"];

function place() {
  var body = document.body;
  var one = solo();
  var open = openSet();
  /* One write, not nine (#215). This was a `remove` of all nine followed by up to four `add`s,
     and every one of them writes `class` whether or not anything changed -- so `place()` could
     never be the no-op the render contract asks for. The classes the page owns for OTHER reasons
     (`focused`, `needs-only`) are kept by construction rather than by being left out of a list. */
  var wanted = Array.prototype.filter.call(body.classList, function (name) {
    return BODY_LAYOUT_CLASSES.indexOf(name) < 0;
  });
  wanted.push("layout-" + LAYOUT);
  if (VIEW) wanted.push("view-" + VIEW);
  if (one) wanted.push("solo");
  if ((LAYOUT === "roles" && VIEW === "board") || (LAYOUT === "screens" && !SCREEN)) {
    wanted.push("panels");
  }
  setClass(body, wanted.join(" "));
  toggle(body, "needs-only", needsOnly);
  // There is no zoom in the column, so the button that leaves one is not drawn there. `Esc` goes
  // back to the agent that was open before, which is the gesture that arrangement actually has.
  var backBtn = document.getElementById("unfocus");
  if (backBtn) hide(backBtn, (LAYOUT === "column") || !focused);
  tiles.forEach(function (entry, name) {
    toggle(entry.el, "is-solo", open.indexOf(name) >= 0);
    toggle(entry.el, "is-selected", name === desk.desk.selected);
  });
  reorderDomTiles();
  // The column is not a window showing one project the way `verify` and `screens` are: it is the
  // whole fleet with one agent open, so it must not open the sidebar on load the way they do.
  if (one && LAYOUT !== "column") {
    // Opened once, not on every draw: a window that reopens a panel the operator just closed is
    // the kind of thing that gets a dashboard turned off.
    // A window showing exactly one project opens the inspector on it, once -- reopening a panel
    // the operator just closed is the kind of thing that gets a dashboard turned off.
    var entry = tiles.get(one);
    if (entry && entry.el.dataset.opened !== "1") {
      setData(entry.el, "opened", "1");
      section("inspector", true);
    }
  }
  var need = 0;
  tiles.forEach(function (entry) { if (entry.el.classList.contains("needs-human")) need += 1; });
  // "Nothing needs you" is only true of an EMPTY screen. Held tiles are still on it, so the prompt
  // to leave focus mode would be sitting under the very tiles it claims are not there.
  hide(document.getElementById("nonefocus"),
       !(needsOnly && !one && need === 0 && held.size === 0 && tiles.size > 0));
  drawNotice();
  drawSwap(one);
  drawColumn();
  drawDock();
  drawRail();
}

/* The column's bands (#203).

   Every checkout that is not open, one band each, sharing the column's whole height. The dock is
   the same data for a different question -- *where did that tile go* -- so the two are never drawn
   together: in this arrangement the column is the dock, and `drawDock` returns early. */
function drawColumn() {
  var box = document.getElementById("column");
  if (!box) return;
  if (LAYOUT !== "column") { hide(box, true); return; }
  var list = document.getElementById("bands");
  var pattern = list.querySelector(".band");
  var open = openSet();
  var shown = visibleOrder();
  var rows = shown.filter(function (name) { return open.indexOf(name) < 0; });

  // A project's checkouts are one band, the way they are one dock chip (#175): two rows for one
  // piece of work is two things to read for one decision.
  var groups = [];
  var byProject = new Map();
  rows.forEach(function (name) {
    var entry = tiles.get(name);
    var project = (entry && entry.row && entry.row.project) || name;
    var group = byProject.get(project);
    if (group) { group.members.push(name); return; }
    group = { project: project, name: name, members: [name] };
    byProject.set(project, group);
    groups.push(group);
  });
  departed.forEach(function (gone, name) {
    groups.push({ project: name, name: name, members: [name], gone: gone });
  });

  /* Patched, never rebuilt. `place()` runs about two and a half times a second while an agent is
     talking, and a column that tore its rows down and cloned them again on every pass would take
     the hover off the band under the cursor and the keyboard off the one `j` had just reached --
     which is the whole of #215's render contract, arriving here first because the column is where
     it is felt. The node for a repository is created once and kept. */
  var need = 0;
  patchList(list, groups, function (item) { return item.name; },
    function (item) {
      var li = pattern.cloneNode(true);
      hide(li, false);
      // #217: the band's own button is its title bar -- it fills the row, and the three tools
      // sit beside it rather than inside it. Bound once, on create, like every other listener
      // the contract allows.
      setData(li, "repo", item.name);
      bindDragToReorder(li.querySelector(".band-open"), li, item.name);
      return li;
    },
    function (li, item, index) {
      setData(li, "repo", item.name);
      drawBand(li, item, index);
      /* *needs me* narrows the column; it does not empty it. A quiet band folds to a sliver --
         still named, still counted, still one click away -- because a mode that removed nine rows
         of ten would be the "where did it go" the column exists to answer, one level up. */
      toggle(li, "is-quiet", needsOnly && !li.classList.contains("needs-human") &&
                             !held.has(item.name));
      if (li.classList.contains("needs-human")) need += 1;
    });

  var hiddenNames = getEffectiveOrder().filter(function (name) { return isHidden(name); });
  text(document.getElementById("column-count"),
       groups.length ? groups.length + (groups.length === 1 ? " other" : " others") +
                       (need ? " · " + need + " need you" : "")
                     : "");
  var jump = document.getElementById("column-jump");
  hide(jump, !need);
  text(jump, "go to the first");
  text(document.getElementById("column-hidden"),
       hiddenNames.length ? hiddenNames.length + " hidden" : "");
  hide(document.getElementById("column-showall"), !hiddenNames.length);
  hide(box, !(groups.length || hiddenNames.length));
}

/* One band: who it is, what state it is in, and -- on every band, not only a red one -- what it
   last said. The dock could fit a state and an age, which is how an agent that asked a question an
   hour ago and went quiet became unreadable from it: `idle · 3m` and nothing else. */
function drawBand(li, item, index) {
  var entry = tiles.get(item.name);
  var row = (entry && entry.row) || {};
  var several = item.members.length > 1;
  var needs = item.members.some(function (name) {
    var e = tiles.get(name);
    return !!e && e.el.classList.contains("needs-human");
  });
  setClass(li, "band" + (needs ? " needs-human" : "") + (item.gone ? " departed" : ""));
  text(li.querySelector(".b-n"), String(index + 1));
  text(li.querySelector(".b-name"), several ? item.project : item.name);
  var ac = ageChip(row.last_event_age_s);
  var spend = row.spend || {};
  text(li.querySelector(".b-chip"),
       item.gone ? "removed from the registry"
                 : several ? item.members.length + " checkouts"
                 : (row.state || "") + (ac.text ? " · " + ac.text : "") +
                   (spend.total ? " · " + spend.total : ""));
  var badge = li.querySelector(".b-badge");
  var unreadN = item.members.reduce(function (n, name) { return n + (unread.get(name) || 0); }, 0);
  hide(badge, !unreadN);
  text(badge, String(unreadN));

  // The last line. `why` when it wants something -- in full, because an ask the operator cannot
  // read is an ask they have to open the tile for -- then the last thing it actually said, then
  // the state. Never blank: a band with nothing on it is a band nobody can triage from.
  var said = "";
  if (item.gone) said = "";
  else if (needs) said = (row.why || "needs you");
  else if (row.last_said) said = String(row.last_said).slice(0, 80);
  else said = (row.state || "") + (ac.text ? " · " + ac.text : "");
  var last = li.querySelector(".b-last");
  text(last, said);
  hide(last, !said);

  // The same hour, on the row where nine of them are being scanned at once (#218).
  drawTrace(li.querySelector(".b-trace"), row);

  /* The tail: what it has been doing, in as many lines as the band has room for. The band shares
     the column's height, so with three agents it is tall -- and a tall row showing one sentence is
     the negative space this arrangement was asked to remove, moved inside the row. The events are
     the ones the row already carries for the transcript, so this costs the page nothing. */
  var tail = li.querySelector(".b-tail");
  var recent = item.gone ? [] : (row.recent || []);
  var shown = recent.filter(function (ev) { return SHOWN[ev.kind] && line(ev); });
  // The line above already IS the newest assistant line, so the tail starts under it rather than
  // opening with the same sentence twice.
  if (said && shown.length && line(shown[shown.length - 1]) === said) shown.pop();
  // Keyed on the event's own sequence number, so a tail that has not changed is not rewritten --
  // and one that has gains a row rather than being built again from nothing.
  patchList(tail, shown.slice(-6), function (ev) { return String(ev.seq || ev.ts || ""); },
    function () { return document.createElement("li"); },
    function (node, ev) { text(node, line(ev)); });
  hide(tail, !tail.children.length);

  var modelName = li.querySelector(".bm-name");
  if (modelName) text(modelName, shortModel(row.actual || row.model));
  var modelBtn = li.querySelector('[data-tool="model"]');
  if (modelBtn) attr(modelBtn, "title", modelTitle(row));
  var tools = li.querySelector(".band-tools");
  if (tools) {
    hide(tools, !!item.gone);          // nothing to hide, refresh or configure about a departed one
    bindTools(li, item.name);
  }

  var button = li.querySelector(".band-open");
  attr(button, "title", item.gone
    ? "`ad-fleet repo add " + item.gone.path + "` restores it"
    : several ? "open " + item.project + ": " + item.members.join(", ")
    : (needs ? (row.why || "needs you") : "open " + item.name));
  button.onclick = function () { if (!item.gone) openBand(item.name); };
}

/* The footer's one line, and one owner (#173).

   `place()` runs several times a second while the stream is talking, and it used to clear this
   element on every draw -- so a message written by anything else lived a few milliseconds and the
   operator never saw it. A line said here holds the footer for its few seconds; the layout's own
   standing warning takes it back when they pass. */
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
  if (unknownLayout) {
    text(notice, "unknown layout '" + unknownLayout + "' — showing " + DEFAULT_LAYOUT);
    hide(notice, false);
  } else {
    text(notice, "");
    hide(notice, true);
  }
}

/* The tab bar is the friction, so the window's own title says which screen it is. */
function title(need) {
  var one = solo();
  attr(document, "title", (need ? "(" + need + ") " : "") + "fleet" +
                   (LAYOUT === "grid" ? "" : " · " + (VIEW || ("screen " + (SCREEN || "board")))) +
                   (one ? " · " + one : ""));
}

function go(params) {
  var u = new URLSearchParams(location.search);
  Object.keys(params).forEach(function (k) {
    if (params[k]) u.set(k, params[k]); else u.delete(k);
  });
  readLocation(u);
  // The URL is the window's identity, so it has to say only true things: a `view` left over from
  // `roles` on a `screens` URL put `view-verify` and `layout-screens` on the body together and
  // titled the window "fleet - verify" when it was a screen.
  if (LAYOUT !== "roles") u.delete("view"); else u.set("view", VIEW);
  if (LAYOUT !== "screens" || !SCREEN) u.delete("screen");
  var qs = u.toString();
  var newUrl = location.pathname + (qs ? "?" + qs : "");
  history.pushState({}, "", newUrl);
  updateLayoutSegments();
  place();
}

/* One control per meaning (HIG *Segmented controls*). The first segment is the arrangement; the
   second says WHICH window of that arrangement this one is, and only exists for the arrangements
   that come as a set. There used to be a second, duplicate <select> alongside this, offering the
   same eight choices in a different vocabulary. */
var VIEW_SEGMENTS = {
  roles: [["agents", "agents"], ["verify", "verify"], ["board", "board"]],
  screens: [["", "laptop"], ["1", "screen 1"], ["2", "screen 2"], ["3", "screen 3"]]
};

function updateLayoutSegments() {
  document.querySelectorAll("#layoutgroup .segment").forEach(function (btn) {
    var active = btn.dataset.layout === LAYOUT;
    toggle(btn, "active", active);
    attr(btn, "aria-checked", String(active));
  });

  var group = document.getElementById("viewgroup");
  var rows = VIEW_SEGMENTS[LAYOUT];
  hide(group, !rows);
  if (!rows) {
    while (group.firstChild) group.removeChild(group.firstChild);
    return;
  }
  // Rebuilt only when the set of choices actually changes. Tearing these down on every draw
  // destroyed the button the operator had just clicked, which drops the focus to `<body>` -- the
  // same trap `reorderDomTiles` documents for tiles.
  var want = LAYOUT + ":" + rows.map(function (r) { return r[0]; }).join(",");
  if (group.dataset.built === want) {
    Array.prototype.forEach.call(group.children, function (btn) {
      var on = LAYOUT === "roles" ? (VIEW === btn.dataset.value)
                                  : (String(SCREEN || "") === btn.dataset.value);
      toggle(btn, "active", on);
      attr(btn, "aria-checked", String(on));
    });
    return;
  }
  setData(group, "built", want);
  while (group.firstChild) group.removeChild(group.firstChild);
  rows.forEach(function (row) {
    var btn = document.createElement("button");
    btn.type = "button";
    setClass(btn, "segment");
    attr(btn, "role", "radio");
    setData(btn, "value", row[0]);
    var mine = LAYOUT === "roles" ? (VIEW === row[0]) : (String(SCREEN || "") === row[0]);
    toggle(btn, "active", mine);
    attr(btn, "aria-checked", String(mine));
    text(btn, row[1]);
    btn.addEventListener("click", function () {
      if (LAYOUT === "roles") go({ layout: "roles", view: row[0], screen: "" });
      else go({ layout: "screens", view: "", screen: row[0] });
    });
    group.appendChild(btn);
  });
}

/* Which window this is, read from the query string. `go()` and the back button both come through
   here so the two cannot drift apart. A `view` is only meaningful under `roles` and a `screen` only
   under `screens`; anything else is dropped rather than carried into a layout it means nothing in. */
function readLocation(u) {
  var rawL = u.get("layout");
  unknownLayout = (rawL && LAYOUTS.indexOf(rawL) < 0) ? rawL : null;
  LAYOUT = unknownLayout ? DEFAULT_LAYOUT : (rawL || DEFAULT_LAYOUT);
  VIEW = LAYOUT !== "roles" ? ""
       : (VIEWS.indexOf(u.get("view")) >= 0 ? u.get("view") : "agents");
  SCREEN = LAYOUT !== "screens" ? 0 : Math.max(0, Math.min(9, Number(u.get("screen")) || 0));
}

window.addEventListener("popstate", function () {
  readLocation(new URLSearchParams(location.search));
  updateLayoutSegments();
  place();
});

(function layoutPicker() {
  document.querySelectorAll("#layoutgroup .segment").forEach(function (btn) {
    btn.addEventListener("click", function () {
      go({ layout: btn.dataset.layout, view: "", screen: "" });
    });
  });
  updateLayoutSegments();
})();

/* Layout C's swap. The pinning is server state, so moving a project onto this monitor takes it off
   whichever one was holding it -- otherwise two screens end up showing the same thing. */
function drawSwap(one) {
  var swap = document.getElementById("swap");
  hide(swap, !(LAYOUT === "screens" && SCREEN));
  if (swap.hidden) return;
  var names = Array.from(tiles.keys());
  while (swap.firstChild) swap.removeChild(swap.firstChild);
  names.forEach(function (name) {
    var option = document.createElement("option");
    option.value = name;
    text(option, "screen " + SCREEN + ": " + name);
    swap.appendChild(option);
  });
  swap.value = one;
}

document.getElementById("swap").addEventListener("change", function () {
  var swap = document.getElementById("swap");
  var names = Array.from(tiles.keys());
  var screens = (desk.desk.screens || []).slice();
  while (screens.length < Math.max(SCREEN, names.length)) screens.push(names[screens.length] || "");
  var wanted = swap.value;
  var here = screens[SCREEN - 1];
  var was = screens.indexOf(wanted);
  if (was >= 0) screens[was] = here;                  // a swap, not an overwrite
  screens[SCREEN - 1] = wanted;
  post("select", { screens: screens }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    place();
  });
});

/* ------------------------------------------------------------------------------- focus mode */

/* The fourth thing #133 asks for, and the only one that is not a layout: hide every tile except
   the ones #94 says need a person. The alternative to arranging tabs is having fewer to look at.
   Toggled with `f`, remembered per window, and printed in the footer's key map. */
function focusMode(on, skipPost) {
  needsOnly = on === undefined ? !needsOnly : !!on;
  attr(document.getElementById("focus"), "aria-pressed", String(needsOnly));
  // Leaving focus mode lets go of the tiles held for it; otherwise the next `f` opens on the last
  // visit's leftovers. Emptied in the *same* write as the mode: the `desk` event this rides back
  // down re-hydrates `held` additively through `applyWindow`, so a clear not posted is undone.
  var patch = { focus: needsOnly };
  if (!needsOnly) {
    held.clear();
    patch.held = [];
  }
  if (!skipPost) saveWindow(patch);
  place();
}

/* `j` and `k` walk the bands; the button they land on is a real button, so `Enter` opens it and
   there is no second model of "which band is selected" to disagree with what is on the glass. */
function stepColumn(dir) {
  var buttons = [].slice.call(document.querySelectorAll("#bands .band:not([hidden]) .band-open"));
  if (!buttons.length) return;
  var here = buttons.indexOf(document.activeElement);
  var at = here < 0 ? (dir > 0 ? 0 : buttons.length - 1)
                    : (here + dir + buttons.length) % buttons.length;
  buttons[at].focus();
}

document.addEventListener("click", function (e) {
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
  document.addEventListener("click", function (e) {
    if (card.hidden) return;
    if (card.contains(e.target)) return;
    if (e.target.closest && e.target.closest('[data-tool="model"]')) return;
    closeModelCard();
  });
})();

function showEverything() {
  var curArr = getLayoutArrangement();
  var was = (curArr.hidden || []).slice();
  return arrangeNow({ hidden: [] }, function () {
    curArr.hidden = [];
    return function () { curArr.hidden = was; };
  }, "showall").then(function (r) {
    if (r && r.ok && needsOnly) focusMode(false);
    return r;
  });
}

document.getElementById("column-showall").addEventListener("click", showEverything);

document.getElementById("column-jump").addEventListener("click", function () {
  var first = document.querySelector("#bands .band.needs-human:not([hidden]) .band-open");
  if (first) first.focus();
});

document.getElementById("showall").addEventListener("click", showEverything);

document.getElementById("focus").addEventListener("click", function () { focusMode(); });

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
document.addEventListener("click", function (e) {
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
  if (e.key === "f") { focusMode(); return; }
  if (e.key === "i") { section("unsorted"); return; }
  if (e.key === "?") { popover("keymap"); return; }
  if (e.key === "/") { e.preventDefault(); document.getElementById("find").focus(); }
});

/* #218: the ground is the size of the window, so it is redrawn when the window is a different
   size. Debounced by a frame, because a drag of the window edge is a hundred resize events and
   three blobs repainted a hundred times is the one canvas on this page that could cost anything. */
var groundResize = 0;
window.addEventListener("resize", function () {
  if (groundResize) return;
  groundResize = requestAnimationFrame(function () {
    groundResize = 0;
    drawGround();
  });
});
startGround();

/* #219: the desk that was, while the desk that is loads. At the very bottom of the file and not
   beside the `refresh()` that starts the fetch, because drawing a row touches module state --
   `departed`, the tiles map -- that is declared further down and is `undefined` until the script
   has finished evaluating. The fetch is already in flight either way; this only decides what is
   on the screen while it is. */
restoreCached();
