/* The multi-viewer's client. No framework and no build step on purpose: this file has to load
   inside PyCharm's JCEF and VS Code's Simple Browser behind a corporate proxy, where anything
   fetched from the internet simply does not arrive.

   The page is a view. It never decides anything -- every state comes from /api/fleet and every
   button POSTs to the same function the CLI verb calls. */

"use strict";

var PARAMS = new URLSearchParams(location.search);
var TOKEN = PARAMS.get("t") || "";
var tiles = new Map();          // repo name -> {el, seq}
var focused = null;
var pendingRefresh = null;
var source = null;

/* #133: three arrangements of this one page, chosen by the URL, because a second HTML file is a
   second thing to keep in step and the friction being fixed is *tabs*. `grid` is every tile on one
   screen; `roles` is three windows -- board, agents, verify -- that agree on a selected project
   through the SSE stream; `screens` pins one project per monitor. `ad-fleet serve --layout` puts
   the parameter on the URL it prints, so the operator never has to type one. */
var LAYOUTS = ["grid", "roles", "screens"];
var VIEWS = ["board", "agents", "verify"];
var rawLayout = PARAMS.get("layout");
var unknownLayout = (rawLayout && LAYOUTS.indexOf(rawLayout) < 0) ? rawLayout : null;
var LAYOUT = unknownLayout ? "grid" : (rawLayout || "grid");
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
/* Whether a drop opens the dispatch card (#164) or launches the way #98 did. The server's
   `fleet.preflight` decides; until the first `/api/fleet` answers, the card is the default,
   because showing a card and starting from it is the recoverable direction to be wrong in. */
var PREFLIGHT = true;

function saveWindow(patch) {
  var body = Object.assign({ w: W_NAME }, patch);
  return post("window", body).catch(function () {});
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
  if (tiles.has(repo)) tiles.get(repo).el.classList.remove("held");
  saveWindow({ held: Array.from(held.keys()) });
  place();
}


function q(path, params) {
  var u = new URL(path, location.origin);
  u.searchParams.set("t", TOKEN);
  Object.keys(params || {}).forEach(function (k) { u.searchParams.set(k, params[k]); });
  return u.toString();
}

function post(action, body) {
  return fetch(q("/api/" + action), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  }).then(function (r) {
    if (r.status === 403 && streamDead) {
      rehome();
    }
    return r.json();
  });
}

function text(el, value) { el.textContent = value == null ? "" : String(value); }

function age(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return seconds + "s";
  if (seconds < 5400) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

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
  exited: 1, error: 1, pr_open: 1, artifact: 1,
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
  li.className = ev.kind;
  var k = document.createElement("span");
  k.className = "k";
  text(k, ev.kind.replace(/_/g, " "));
  var v = document.createElement("span");
  v.className = "v";
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
  repoEl.title = row.repo;
  el.dataset.repo = row.repo;

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
  var head = el.querySelector(".head");
  head.addEventListener("dragstart", function (e) {
    if (e.target.closest("button, input, select")) { e.preventDefault(); return; }
    e.dataTransfer.setData("application/x-agentdata-tile", row.repo);
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("is-dragging");
  });
  var clearDrop = function () {
    el.classList.remove("is-dragging");
    document.querySelectorAll(".tile").forEach(function (t) {
      t.classList.remove("drop-before", "drop-after", "drop-target");
    });
  };
  head.addEventListener("dragend", clearDrop);
  // Esc cancels a drag in flight and leaves the order alone (HIG *Drag and drop*).
  el.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && el.classList.contains("is-dragging")) clearDrop();
  });

  el.addEventListener("dragover", function (e) {
    e.preventDefault();
    var isTileDrag = Array.from(e.dataTransfer.types || []).indexOf("application/x-agentdata-tile") >= 0;
    if (isTileDrag) {
      e.dataTransfer.dropEffect = "move";
      var rect = el.getBoundingClientRect();
      var before = (e.clientX - rect.left) < (rect.width / 2);
      el.classList.toggle("drop-before", before);
      el.classList.toggle("drop-after", !before);
    } else {
      e.dataTransfer.dropEffect = "copy";
      el.classList.add("drop-target");
    }
  });

  el.addEventListener("dragleave", function () {
    el.classList.remove("drop-target", "drop-before", "drop-after");
  });

  el.addEventListener("drop", function (e) {
    e.preventDefault();
    var isTileDrag = el.classList.contains("drop-before") || el.classList.contains("drop-after");
    var droppedRepo = e.dataTransfer.getData("application/x-agentdata-tile");
    var dropBefore = el.classList.contains("drop-before");
    el.classList.remove("drop-target", "drop-before", "drop-after");

    if (droppedRepo && droppedRepo !== row.repo) {
      var order = getEffectiveOrder();
      var fromIdx = order.indexOf(droppedRepo);
      if (fromIdx >= 0) order.splice(fromIdx, 1);
      var toIdx = order.indexOf(row.repo);
      if (!dropBefore) toIdx += 1;
      order.splice(toIdx, 0, droppedRepo);
      post("arrange", { layout: LAYOUT, order: order }).then(function (r) {
        if (r && r.ok) mergeDesk(r);
        reorderDomTiles();
      });
      reorderDomTiles();
      return;
    }

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
    if (key) { if (PREFLIGHT) dispatchCard(key, row.repo); else dispatch(key, row.repo); }
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

  el.querySelector(".hidetoggle").addEventListener("click", function (e) {
    e.stopPropagation();
    setHidden(row.repo, true);
  });

  el.querySelector(".scope-close").addEventListener("click", function () {
    el.querySelector(".scope").hidden = true;
  });
  el.querySelector(".scope-tell").addEventListener("click", function () {
    action(el, "send", { repo: row.repo, message:
      "New files are in the scope under .agent/in/; read scope.toon before continuing." });
  });

  el.querySelector(".dispatch-close").addEventListener("click", function () { closeDispatch(el); });
  el.querySelector(".dispatch-go").addEventListener("click", function () {
    var card = el.querySelector(".dispatch");
    dispatch(card.dataset.key || "", row.repo, el.querySelector(".brief").value.trim());
  });
  el.querySelector(".brief").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { el.querySelector(".dispatch-go").click(); e.preventDefault(); }
    else if (e.key === "Escape") { closeDispatch(el); e.stopPropagation(); }
  });

  /* #174: the switcher's four buttons. The rows behind *earlier* are fetched on the click rather
     than on every poll -- nobody is reading them until they ask for them. */
  el.querySelector(".earlier-tab").addEventListener("click", function () {
    openSessions(el, row.repo);
  });
  el.querySelector(".main-tab").addEventListener("click", function () {
    el.querySelector(".sessions").hidden = true;
    el.querySelector(".earlier-tab").setAttribute("aria-expanded", "false");
    if (viewing(el)) backToLive(el);
  });
  el.querySelector(".new-tab").addEventListener("click", function () { newSession(el, row.repo); });
  el.querySelector(".ro-resume").addEventListener("click", function () { resumeHere(el, row.repo); });
  el.querySelector(".ro-back").addEventListener("click", function () { backToLive(el); });

  /* Every drag gesture has a keyboard equivalent, and the footer key map lists all four. */
  el.addEventListener("keydown", function (e) {
    if (!e.altKey) return;
    if (e.key === "ArrowLeft") { moveTile(row.repo, -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { moveTile(row.repo, 1); e.preventDefault(); }
    else if (e.key === "Home") { toggleTilePin(row.repo); e.preventDefault(); }
    else if (e.key === "Enter") { toggleTileSize(row.repo); e.preventDefault(); }
    // The strip, without a mouse. `[` and `]` walk it; `N` is a clean session beside this one.
    else if (e.key === "[") { stepStrip(el, -1); e.preventDefault(); }
    else if (e.key === "]") { stepStrip(el, 1); e.preventDefault(); }
    else if (e.key === "n" || e.key === "N") { newSession(el, row.repo); e.preventDefault(); }
  });

  var pinBtn = el.querySelector(".pintoggle");
  if (pinBtn) {
    pinBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTilePin(row.repo);
    });
  }

  var sizeBtn = el.querySelector(".sizetoggle");
  if (sizeBtn) {
    sizeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTileSize(row.repo);
    });
  }

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
  el.querySelector(".send").addEventListener("click", function () {
    action(el, "send", { repo: row.repo, message: say.value }).then(function () { say.value = ""; });
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
        resetBtn.dataset.force = "1";
        text(resetBtn, "Reset anyway");
        resetBtn.title = "it has already been restarted this many times — press again to spend one more";
        return;
      }
      resetBtn.dataset.force = "";
      text(resetBtn, "Reset");
      resetBtn.title = "unblock it: end the stuck process and resume the same session";
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

function fail(el, message) {
  var p = el.querySelector(".err");
  text(p, message);
  p.hidden = !message;
}

function action(el, what, body) {
  fail(el, "");
  return post(what, body).then(function (r) {
    if (!r.ok) fail(el, r.error + (r.hint ? " — " + r.hint : ""));
    // Only a *successful* action holds the tile. A refusal leaves the agent exactly as it was, so
    // the tile is still whatever focus mode already thought it was, and the error is on the tile.
    else hold((body && body.repo) || el.dataset.repo, what);
    refresh();
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
    card.hidden = true;
  } else {
    card.hidden = false;
    text(card.querySelector(".asks-n"), open.length === 1 ? "1 question" : open.length + " questions");
    // Redraw only when the set changed: the operator may be mid-sentence in one of these boxes,
    // and a refresh every few seconds that threw the typing away would make the card unusable.
    var signature = open.map(function (q) { return q.id + ":" + q.q; }).join("|");
    if (list.dataset.signature !== signature) {
      list.dataset.signature = signature;
      var pattern = list.querySelector(".ask");
      while (list.children.length > 1) list.removeChild(list.lastChild);
      open.forEach(function (q) {
        var li = pattern.cloneNode(true);
        li.hidden = false;
        li.dataset.qid = q.id || "";
        text(li.querySelector(".ask-q"), q.q || "");
        var picked = li.querySelector(".ask-answer");
        picked.placeholder = q.want === "file" ? "a path, or drop the file on this tile" : "your answer";
        var choices = li.querySelector(".ask-choices");
        (q.choices || []).forEach(function (choice) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "ask-choice";
          text(b, choice + (choice === q.default ? " (default)" : ""));
          b.setAttribute("aria-pressed", "false");
          b.addEventListener("click", function () {
            picked.value = choice;
            Array.prototype.forEach.call(choices.children, function (other) {
              other.setAttribute("aria-pressed", String(other === b));
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
    strip.hidden = true;
  } else {
    strip.hidden = false;
    var shape = strip.querySelector(".assumption");
    while (strip.children.length > 1) strip.removeChild(strip.lastChild);
    assumed.forEach(function (q) {
      var li = shape.cloneNode(true);
      li.hidden = false;
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
  if (!card.edited) { strip.hidden = true; return; }
  strip.hidden = false;
  var said = "edited " + card.edited;
  if (card.outside && card.outside.length) {
    said += " · " + card.outside.length + " outside the scope you gave it";
    strip.className = "scopereport outside";
    strip.title = card.outside.join("\n");
  } else {
    said += " · all inside the scope you gave it";
    strip.className = "scopereport";
    strip.title = "";
  }
  text(strip, said);
}

function drawTile(el, row, approvals) {
  /* Three things have to agree here or the tile lies: the chip, the sentence under it, and the
     age. The server decides which agents are quiet enough to be called unsupervised (it is the
     only side that knows whether a process holds the checkout), and it sends the sentence ONLY
     for those -- so a tile that says "needs you" never also says "nothing is supervised". */
  var isSupervised = row.supervised !== false;
  var cold = !isSupervised && !!row.not_supervised_sentence;
  var displayState = cold ? "idle" : row.state;
  el.className = "tile state-" + displayState + (el.classList.contains("is-focused") ? " is-focused" : "");
  // The left edge is the project's accent -- which project, never what state (#150).
  if (row.accent) el.style.borderLeftColor = row.accent;
  // `needs-human` is the class focus mode filters on, and it comes from #94's fold rather than from
  // anything this page works out for itself: the chip, the toast and the filter must agree.
  el.classList.toggle("needs-human", !!row.needs_human);
  /* The hold is NOT dropped when the agent needs the human. It was, briefly, and that only delayed
     the disappearance: pressing Send refreshes at once, and for the moment before the agent opens
     its turn it is still the blocked agent it was -- so the hold was deleted on that first refresh
     and the tile vanished a second later, when the turn started. An agent needing the human again
     is on screen on its own merit anyway; all the hold has to do is stop claiming the credit, which
     the stylesheet handles by showing the note only while the tile is not asking for anything. */
  el.classList.toggle("held", held.has(row.repo));
  var holdNote = el.querySelector(".holdnote");
  if (holdNote) {
    text(holdNote.querySelector(".holdwhy"),
         "held here because you " + (held.get(row.repo) || "acted") + " — it no longer needs you");
  }
  el.tabIndex = 0;
  // Every state carries its own age, in the chip, because a verdict with no date is the bug.
  var ac = ageChip(row.last_event_age_s);
  var chip = el.querySelector(".chip");
  chip.className = "chip " + displayState + (ac.stale ? " stale" : "");
  while (chip.firstChild) chip.removeChild(chip.firstChild);
  chip.appendChild(document.createTextNode(displayState.replace(/_/g, " ")));
  if (ac.text) {
    var span = document.createElement("span");
    span.className = "chipage";
    text(span, " · " + ac.text);
    chip.appendChild(span);
  }
  chip.title = "state from the fold" + (ac.text ? ", last event " + ac.text + " ago" : "");
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
      outside.hidden = false;
      outside.classList.add("mine");
      text(outside.querySelector(".outsidewhy"),
           "a session outside the fleet is driving this repo" +
           (row.pid ? " (pid " + row.pid + ")" : "") +
           (row.external_how ? " — " + row.external_how : ""));
      text(adoptBtn, "hand it back");
      adoptBtn.dataset.what = "release";
      adoptBtn.title = "stop treating that session as this repo's current one";
    } else if (offer) {
      outside.hidden = false;
      outside.classList.remove("mine");
      text(outside.querySelector(".outsidewhy"),
           "something is working in this checkout that the fleet did not start" +
           (offer.pid ? " (pid " + offer.pid + ")" : "") +
           " — last wrote " + age(offer.active_age_s) + " ago, " + offer.how);
      text(adoptBtn, "adopt it");
      adoptBtn.dataset.what = "adopt";
      adoptBtn.dataset.pid = String(offer.pid || 0);
      adoptBtn.title = "make that session this repo's current one, instead of the last run the fleet started";
    } else {
      outside.hidden = true;
    }
  }
  // An adopted session has no pipe to its stdin, so the controls that would write to it say so
  // rather than being offered and silently doing nothing.
  ["send", "start"].forEach(function (cls) {
    var btn = el.querySelector("." + cls);
    if (!btn) return;
    btn.disabled = !!row.external;
    btn.title = row.external ? "type in that window — this session is not the fleet's to drive" : "";
  });

  // Which run this transcript belongs to. Without it, a two-day-old run reads as live.
  var run = row.run || {};
  // Which session the live tile is on, so the switcher can leave it out of *earlier* rather than
  // offering the operator the one they are already looking at (#174).
  el.dataset.session = run.session || "";
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
    runline.title = (run.session ? "session " + run.session + " (click to copy)\n" : "") + bits.join(" · ");
    runline.classList.toggle("cold", cold);
    if (run.session) {
      runline.onclick = function() {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(run.session);
        }
      };
      runline.style.cursor = "pointer";
    }
  }

  drawStrip(el, row);

  var earlierEl = el.querySelector(".earlier");
  if (earlierEl) {
    var earlierRuns = row.earlier || [];
    if (earlierRuns.length > 0) {
      earlierEl.hidden = false;
      text(earlierEl.querySelector(".earlierhead"), "earlier runs (" + earlierRuns.length + ")");
      var listEl = earlierEl.querySelector(".earlierlist");
      while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
      earlierRuns.forEach(function (r) {
        var li = document.createElement("li");
        text(li, "Run #" + r.n + ": " + (r.ticket ? r.ticket + " · " : "") + r.state +
                 " (" + (r.started ? r.started.slice(11, 16) : "") +
                 (r.ended ? " – " + r.ended.slice(11, 16) : "") + ")");
        listEl.appendChild(li);
      });
    } else {
      earlierEl.hidden = true;
    }
  }

  var mine = approvals.filter(function (a) { return a.repo === row.repo; })[0];
  var card = el.querySelector(".approval");
  card.hidden = !mine;
  if (mine) {
    el.dataset.approval = mine.id;
    text(el.querySelector(".kind"), mine.kind + "  ·  " + age(mine.waiting_s));
    text(el.querySelector(".summary"), mine.summary || "");
    text(el.querySelector(".payload"), JSON.stringify(mine.payload || {}, null, 2));
  }
  drawAsks(el, row);
  drawScopeReport(el, row);
  drawCells(el, row.polls || {});
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

function drawStrip(el, row) {
  var strip = el.querySelector(".strip");
  if (!strip) return;
  var pattern = strip.querySelector(".sib-tab");
  var main = strip.querySelector(".main-tab");
  var earlierTab = strip.querySelector(".earlier-tab");
  var open = viewing(el);

  var run = row.run || {};
  var bits = ["main"];
  if (row.state) bits.push(row.state);
  if (row.last_event_age_s >= 0) bits.push(age(row.last_event_age_s));
  text(main, bits.join(" · "));
  main.title = run.session ? "session " + run.session : "this checkout's live session";
  main.setAttribute("aria-selected", String(!open));
  main.classList.toggle("is-on", !open);

  // Sibling checkouts of the same project (#175). Empty until that slice lands, which is why the
  // strip has to read as finished with one tab on it rather than as a row of missing things.
  while (strip.querySelectorAll(".sib-tab").length > 1) {
    strip.removeChild(strip.querySelectorAll(".sib-tab")[1]);
  }
  (row.siblings || []).forEach(function (sib) {
    var tab = pattern.cloneNode(true);
    tab.hidden = false;
    text(tab, [sib.branch || sib.repo, sib.state, sib.age].filter(Boolean).join(" · "));
    tab.title = "the same project, checked out at " + (sib.path || sib.repo);
    tab.addEventListener("click", function () { focus(sib.repo); });
    strip.insertBefore(tab, earlierTab);
  });

  var n = row.sessions_n || 0;
  earlierTab.hidden = !n;
  text(earlierTab, "earlier (" + n + ")");
  earlierTab.setAttribute("aria-selected", String(!!open));
  earlierTab.classList.toggle("is-on", !!open);
}

/* The rows, on the click rather than on every poll: this is a disk read and a fold, and nobody is
   looking at it until they ask. */
function openSessions(el, repo) {
  var list = el.querySelector(".sessions");
  var tab = el.querySelector(".earlier-tab");
  if (!list.hidden) { list.hidden = true; tab.setAttribute("aria-expanded", "false"); return; }
  fetch(q("/api/sessions", { repo: repo })).then(function (r) { return r.json(); })
    .then(function (data) {
      var pattern = list.querySelector(".session-row");
      while (list.children.length > 1) list.removeChild(list.lastChild);
      var rows = (data && data.sessions) || [];
      var current = (el.dataset.session || "");
      rows.filter(function (row) { return row.id !== current; }).forEach(function (row) {
        var li = pattern.cloneNode(true);
        li.hidden = false;
        text(li.querySelector(".ss-title"), row.title || row.ticket || row.id.slice(0, 8));
        text(li.querySelector(".ss-chip"), row.ended || "");
        text(li.querySelector(".ss-when"), whenIso(row.last_seen));
        text(li.querySelector(".ss-cost"),
             row.cost ? Number(row.cost).toFixed(2) + " premium" : "");
        var button = li.querySelector(".ss-open");
        button.title = (row.source === "store"
          ? "a console window may still own this; close it first — "
          : "") + "session " + row.id;
        button.addEventListener("click", function () { showSession(el, repo, row); });
        list.appendChild(li);
      });
      if (!rows.length) {
        var empty = pattern.cloneNode(true);
        empty.hidden = false;
        text(empty.querySelector(".ss-title"), "no earlier sessions in this checkout");
        empty.querySelector(".ss-open").disabled = true;
        list.appendChild(empty);
      }
      list.hidden = false;
      tab.setAttribute("aria-expanded", "true");
    });
}

/* Read-only, from history. The live transcript is hidden rather than replaced, so it keeps filling
   behind this and going back is instant and whole rather than a reload with a hole in it. */
function showSession(el, repo, session) {
  fetch(q("/api/transcript", { repo: repo, session: session.id }))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data || !data.ok) return;
      el.dataset.viewing = session.id;
      var history = el.querySelector(".history");
      while (history.firstChild) history.removeChild(history.firstChild);
      (data.events || []).forEach(function (ev) { appendTo(history, ev); });
      el.querySelector(".transcript").hidden = true;
      history.hidden = false;
      el.querySelector(".sessions").hidden = true;
      el.querySelector(".earlier-tab").setAttribute("aria-expanded", "false");
      var pane = el.querySelector(".readonly");
      pane.hidden = false;
      text(el.querySelector(".ro-what"),
           (session.title ? session.title + " — " : "") + endedSentence(data));
      var resume = el.querySelector(".ro-resume");
      text(resume, "Resume here");
      resume.dataset.armed = "";
      text(el.querySelector(".ro-note"),
           session.source === "store"
             ? "a console window may still own this; close it first"
             : "");
      el.querySelector(".row.bottom").hidden = true;
      var entry = tiles.get(repo);
      if (entry && entry.row) drawStrip(el, entry.row);
    });
}

/* `Alt+[` and `Alt+]` walk the strip. The tabs are real buttons in document order, so stepping is
   moving the keyboard to the next one and pressing it -- there is no second model of "which tab is
   selected" that could disagree with the one the page is showing. */
function stepStrip(el, dir) {
  var tabs = [].slice.call(el.querySelectorAll(".strip .tab"))
               .filter(function (t) { return !t.hidden; });
  if (!tabs.length) return;
  var here = tabs.indexOf(document.activeElement);
  if (here < 0) {
    here = tabs.indexOf(el.querySelector(".strip .tab.is-on"));
    if (here < 0) here = 0;
  }
  var next = tabs[(here + dir + tabs.length) % tabs.length];
  next.focus();
  next.click();
}

function backToLive(el) {
  el.dataset.viewing = "";
  el.querySelector(".history").hidden = true;
  el.querySelector(".transcript").hidden = false;
  el.querySelector(".readonly").hidden = true;
  el.querySelector(".row.bottom").hidden = false;
  var entry = tiles.get(el.dataset.repo);
  if (entry && entry.row) drawStrip(el, entry.row);
}

/* Making an earlier session the live one. When nothing is running it simply runs; when something
   is, it is the supervisor's own refusal with the supervisor's own hint, and the button becomes a
   second, deliberate press -- never a silent force, and never two agents in one working tree. */
function resumeHere(el, repo) {
  var button = el.querySelector(".ro-resume");
  var note = el.querySelector(".ro-note");
  var armed = button.dataset.armed === "1";
  post("start", { repo: repo, resume: viewing(el), force: armed }).then(function (r) {
    if (r && r.ok) {
      button.dataset.armed = "";
      backToLive(el);
      refresh();
      return;
    }
    text(note, [r && r.error, r && r.hint].filter(Boolean).join(" — "));
    if (r && r.code === "live_agent") {
      button.dataset.armed = "1";
      text(button, "Stop and resume");
    }
  });
}

function newSession(el, repo) {
  var note = el.querySelector(".ro-note");
  post("start", { repo: repo, "new": true }).then(function (r) {
    if (r && r.ok) { backToLive(el); refresh(); return; }
    var said = [r && r.error, r && r.hint].filter(Boolean).join(" — ");
    if (!el.querySelector(".readonly").hidden) text(note, said);
    else { text(el.querySelector(".err"), said); el.querySelector(".err").hidden = false; }
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
      li.className = "away-line";
      var repoSpan = document.createElement("span");
      repoSpan.className = "repo";
      text(repoSpan, item.repo + ":");
      var descSpan = document.createElement("span");
      descSpan.className = "desc";
      text(descSpan, item.body || item.title || item.state);
      var whenSpan = document.createElement("span");
      whenSpan.className = "when";
      text(whenSpan, " · " + (item.at ? String(item.at).slice(11, 19) : ""));
      li.appendChild(repoSpan);
      li.appendChild(descSpan);
      li.appendChild(whenSpan);
      li.addEventListener("click", function () {
        if (tiles.has(item.repo)) focus(item.repo);
      });
      list.appendChild(li);
    });
    strip.hidden = false;
  }).catch(function () {});
}

var dismissBtn = document.getElementById("dismiss-away");
if (dismissBtn) {
  dismissBtn.addEventListener("click", function () {
    var strip = document.getElementById("away-strip");
    if (strip) strip.hidden = true;
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
    document.getElementById("empty").hidden = data.repos.length > 0;
    data.repos.forEach(function (row, i) {
      var entry = tiles.get(row.repo);
      if (!entry) {
        var el = makeTile(row, i);
        grid.appendChild(el);
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
      drawTile(entry.el, row, data.approvals || []);
    });
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
    text(document.getElementById("counts"),
         data.repos.length + " agents" + (need ? "  ·  " + need + " need you" : "") +
         (needsOnly && held.size ? "  ·  " + held.size + " held" : ""));
    if (data.desk) {
      desk.desk = data.desk;
      if (data.desk.windows && data.desk.windows[W_NAME]) {
        applyWindow(data.desk.windows[W_NAME]);
      }
    }
    if (data.theme) {
      applyTheme(data.theme.css, data.theme.theme);
      applySkin(data.theme.skin);
      reflectTheme(data.theme);
    }
    if (typeof data.preflight === "boolean") PREFLIGHT = data.preflight;
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
      var select = document.getElementById("theme");
      if (select && d.theme) select.value = d.theme === "none" ? "" : d.theme;
      applyTheme(d.css, d.theme);
      applySkin(d.skin);
      reflectTheme(d);
      if (d.accents) {
        Object.keys(d.accents).forEach(function (repo) {
          if (tiles.has(repo)) {
            tiles.get(repo).el.style.borderTopColor = d.accents[repo];
          }
        });
      }
    } catch (err) {}
  });
  source.addEventListener("tick", function () {
    link.className = "dot live";
    text(link, "live");
  });
  source.onopen = function () { streamDead = false; link.className = "dot live"; text(link, "live"); };
  source.onerror = function () {
    streamDead = true;
    link.className = "dot lost";
    text(link, "reconnecting");
    // EventSource reconnects on its own, but the page must not trust what it drew in between.
    setTimeout(function () { refresh().then(connect); }, 2000);
  };
}

/* ------------------------------------------------------------------- focus mode and the keyboard */

function focus(name, skipPost) {
  focused = name;
  document.body.classList.add("focused");
  document.getElementById("unfocus").hidden = false;
  tiles.forEach(function (entry, key) { entry.el.classList.toggle("is-focused", key === name); });
  unread.delete(name);                       // looking at it is what "read" means
  var entry = tiles.get(name);
  if (entry && entry.seq) {
    readCursors[name] = entry.seq;
  }
  bell();
  drawer(false);
  if (location.hash !== "#tile=" + name) history.replaceState(null, "", "#tile=" + name);
  if (!skipPost) saveWindow({ zoomed: name, read: readCursors });
}

function unfocus(skipPost) {
  focused = null;
  document.body.classList.remove("focused");
  document.getElementById("unfocus").hidden = true;
  tiles.forEach(function (entry) { entry.el.classList.remove("is-focused"); });
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  if (!skipPost) saveWindow({ zoomed: "" });
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
  if (e.key === "Escape") { if (typing) document.activeElement.blur(); else unfocus(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[1-9]$/.test(e.key)) {
    // The number printed on a tile comes from the arrangement, so the key that focuses it must
    // too. Reading registry order here meant that the moment anything was moved or pinned, the
    // badge said 3 and pressing 3 focused something else. The *visible* order (#173), so a digit
    // can no longer zoom a tile that is not on the glass -- which blanked the window, because zoom
    // hides every other tile and focus mode was already hiding that one.
    var name = visibleOrder()[Number(e.key) - 1];
    if (!name) return;
    // Zooming a tile focus mode is quieting was a blank window: zoom hides every other tile and
    // the mode was already hiding this one. The operator pressed the number printed on that tile,
    // so the mode gives way rather than the window going dark -- the same answer `#tile=` gives.
    if (quieted(name)) focusMode(false);
    focus(name);
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

function applyTheme(cssVars, themeName) {
  var root = document.documentElement;
  var tokens = ["--bg", "--text", "--panel", "--line", "--select", "--muted", "--accent",
                "--focus", "--running", "--waiting", "--human", "--done", "--idle"];
  if (cssVars && themeName && themeName !== "none") {
    tokens.forEach(function (k) {
      if (cssVars[k]) root.style.setProperty(k, cssVars[k]);
      else root.style.removeProperty(k);
    });
    root.setAttribute("data-theme", "custom");
  } else {
    tokens.forEach(function (k) { root.style.removeProperty(k); });
    root.removeAttribute("data-theme");
  }
}

/* A skin is one stylesheet; a VARIANT is that same stylesheet drawn against a different palette,
   selected by an attribute rather than by a second file. Nether and Overworld share every bevel and
   every sprite and differ in their colours, so shipping them as two stylesheets would be shipping
   the same art twice and letting the two copies drift. Switching variant therefore re-paints
   without a fetch, and only changing skin loads anything. */
function applySkin(skinName) {
  var link = document.head.querySelector("link[data-skin]");
  var parts = String(skinName || "").split(":");
  var family = parts[0];
  var variant = parts[1] || "";
  if (!family || family === "none") {
    if (link) link.remove();
    document.body.removeAttribute("data-skin");
    document.body.removeAttribute("data-skin-variant");
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("data-skin", "true");
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  var href = q("/static/skins/" + family + "/skin.css");
  if (link.href !== href) link.href = href;   // re-assigning re-fetches and flashes the page
  document.body.setAttribute("data-skin", family);
  if (variant) document.body.setAttribute("data-skin-variant", variant);
  else document.body.removeAttribute("data-skin-variant");
}

/* Two controls, two tiers, and the difference is the point (#150, #154).

   A PALETTE is colour only, so it is 1:1 with the terminal: the same hex reaches this page's custom
   properties and the project's prompt and tab, and choosing one here writes
   `~/.agentdata/config.json` -- the same file `ad-theme set` writes -- so every window on every
   screen and the terminal beside them move together. A SKIN is how the page is RENDERED, which a
   terminal cannot follow; it rides on a base palette and loads one extra stylesheet on demand.

   Both post to the server rather than to `localStorage`, because a desk is four windows and a
   choice kept in one browser's storage is four different desks. */
function loadThemes() {
  var themeSel = document.getElementById("theme");
  var skinSel = document.getElementById("skin");
  return fetch(q("/api/themes")).then(function (r) { return r.json(); }).then(function (data) {
    while (themeSel.options.length > 1) themeSel.remove(1);
    (data.themes || []).forEach(function (t) {
      if (t.name === "none") return;                 // "system" is already the first option
      var option = document.createElement("option");
      option.value = t.name;
      text(option, t.name);
      option.title = t.why || t.title || t.name;
      themeSel.appendChild(option);
    });
    themeSel.addEventListener("change", function () { post("theme", { theme: themeSel.value }); });

    /* One control, not two. A variant is not independent of its skin -- "Nether" means nothing on
       its own, and a second picker offering it beside Farmstead would be offering a combination
       that does not exist. Grouping them says the same thing the model does: pick a skin, and its
       ground comes with it. A skin with one variant lists as a single option. */
    while (skinSel.options.length > 1) skinSel.remove(1);
    (data.skins || []).forEach(function (k) {
      if (k.name === "none") return;
      var vs = k.variants || [];
      if (vs.length < 2) {
        var single = document.createElement("option");
        single.value = vs.length ? vs[0].full : k.name;
        text(single, k.title || k.name);
        single.title = (k.why || "") + (k.base ? "  ·  palette: " + k.base : "");
        skinSel.appendChild(single);
        return;
      }
      var group = document.createElement("optgroup");
      group.label = k.title || k.name;
      vs.forEach(function (v) {
        var option = document.createElement("option");
        option.value = v.full;
        text(option, v.title || v.name);
        option.title = (v.why || "") + "  ·  palette: " + v.base;
        group.appendChild(option);
      });
      skinSel.appendChild(group);
    });
    skinSel.addEventListener("change", function () { post("theme", { skin: skinSel.value }); });
    reflectTheme(data.current || data.theme);
  }).catch(function () { /* themes are decoration; the page works without them */ });
}

/* One place that puts the server's answer into the two controls, so a change made in the terminal
   or in another window shows up here rather than leaving the picker saying something else. */
function reflectTheme(cur) {
  if (!cur) return;
  var themeSel = document.getElementById("theme");
  var skinSel = document.getElementById("skin");
  if (themeSel && cur.theme) themeSel.value = cur.theme;
  if (skinSel) skinSel.value = cur.skin || "none";
  /* While a skin is on, the palette is the skin's -- so the palette picker shows what is being
     rendered and says why it is not taking instructions, rather than accepting a choice the server
     would then override. Turning the skin off hands it back. */
  if (themeSel) {
    var bound = !!(cur.skin && cur.skin !== "none");
    themeSel.disabled = bound;
    themeSel.title = bound
      ? "the palette comes from the skin — choose “no skin” to pick one yourself"
      : "palette — shared with this project's terminal";
  }
}

refresh().then(function () {
  connect();
  loadThemes();
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
  button.classList.toggle("unread", total > 0);
  tiles.forEach(function (entry, name) {
    var badge = entry.el.querySelector(".badge");
    var n = unread.get(name) || 0;
    badge.hidden = n === 0;
    text(badge, n);
  });
  return total;
}

function noteRow(item) {
  var li = document.createElement("li");
  li.className = item.severity || "info";
  var t = document.createElement("span");
  t.className = "t";
  text(t, item.title);
  var b = document.createElement("span");
  b.className = "b";
  text(b, item.body || "");
  var when = document.createElement("span");
  when.className = "when";
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
  document.getElementById("nonotes").hidden = list.children.length > 0;
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
      document.getElementById("nonotes").hidden = list.children.length > 0;
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
  document.getElementById("side").hidden = open.length === 0;
  document.getElementById("sidetoggle").setAttribute("aria-pressed", String(open.length > 0));
  document.querySelectorAll(".side-tabs .segment").forEach(function (b) {
    var on = open.indexOf(b.dataset.section) >= 0;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
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
    if (n) n.hidden = !(s === id && want);
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
    if (n) n.hidden = true;
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
  button.setAttribute("aria-pressed", String(chimeOn));
  text(button, chimeOn ? "chime on" : "chime off");
  try { localStorage.setItem("fleet.chime", chimeOn ? "1" : "0"); } catch (e) { /* private window */ }
  if (chimeOn) chime();                      // and it plays once, so "on" is not taken on trust
});

try { chimeOn = localStorage.getItem("fleet.chime") === "1"; } catch (e) { chimeOn = false; }
document.getElementById("chime").setAttribute("aria-pressed", String(chimeOn));
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
  li.dataset.key = row.key;

  var head = document.createElement("div");
  var key = document.createElement("span");
  key.className = "key";
  text(key, row.key);
  var st = document.createElement("span");
  st.className = statusClass(row);
  text(st, row.status);
  head.appendChild(key);
  head.appendChild(st);

  var sum = document.createElement("span");
  sum.className = "sum";
  text(sum, row.summary);

  var to = document.createElement("span");
  to.className = "to";
  var s = row.suggested || {};
  text(to, s.repo ? "→ " + s.repo : (s.hint || s.why || ""));
  head.appendChild(document.createTextNode(" "));

  li.appendChild(head);
  li.appendChild(sum);
  li.appendChild(to);

  (s.repo ? [s.repo] : (s.candidates || [])).forEach(function (name) {
    var go = document.createElement("button");
    go.className = "go";
    text(go, "start on " + name);
    go.addEventListener("click", function (e) {
      e.stopPropagation();
      dispatch(row.key, name);
    });
    li.appendChild(go);
  });

  li.addEventListener("dragstart", function (e) {
    li.classList.add("dragging");
    e.dataTransfer.setData("application/x-agentdata-ticket", row.key);
    e.dataTransfer.setData("text/plain", row.key);
    e.dataTransfer.effectAllowed = "copy";
  });
  li.addEventListener("dragend", function () { li.classList.remove("dragging"); });
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
  card.hidden = false;
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
        li.hidden = false;
        li.className = "scope-row s-" + item.status;
        text(li.querySelector(".sc-name"), item.name);
        text(li.querySelector(".sc-path"), item.paths && item.paths.length ? item.paths[0] : "");
        text(li.querySelector(".sc-how"), item.how || "");
        text(li.querySelector(".sc-why"), item.why || "");
        if (item.status === "resolved") resolved.push(item.paths[0]);
        if (item.status === "ambiguous") {
          var pick = li.querySelector(".sc-pick");
          pick.hidden = false;
          item.paths.forEach(function (p) {
            var o = document.createElement("option");
            o.value = p; text(o, p); pick.appendChild(o);
          });
          resolved.push(item.paths[0]);
          pick.addEventListener("change", function () {
            resolved[resolved.indexOf(li.dataset.chosen || item.paths[0])] = pick.value;
            li.dataset.chosen = pick.value;
          });
          li.dataset.chosen = item.paths[0];
        }
        if (item.status === "unmatched") {
          // Not this repository's file. The only route that moves bytes, and only on this click.
          var attach = li.querySelector(".sc-attach");
          attach.hidden = false;
          attach.addEventListener("click", function () {
            var f = files[i];
            f.arrayBuffer().then(function (buf) {
              var bin = "";
              var view = new Uint8Array(buf);
              for (var n = 0; n < view.length; n++) bin += String.fromCharCode(view[n]);
              return post("attach-bytes", { repo: repo, name: f.name, bytes: btoa(bin) });
            }).then(function (a) {
              text(li.querySelector(".sc-why"), a && a.ok ? "attached → " + a.dir : ((a && a.error) || "refused"));
              if (a && a.ok) attach.hidden = true;
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
          tell.hidden = !(added && added.ok && added.queued === false);
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

function dispatchCard(key, repo) {
  var entry = tiles.get(repo);
  if (!entry) return dispatch(key, repo);
  var el = entry.el;
  var card = el.querySelector(".dispatch");
  var rows = card.querySelector(".dispatch-rows");
  var brief = card.querySelector(".brief");

  text(card.querySelector(".dispatch-key"), key + " → " + repo);
  text(card.querySelector(".verdict"), "reading…");
  card.querySelector(".verdict").className = "verdict";
  while (rows.firstChild) rows.removeChild(rows.firstChild);
  brief.value = "";
  card.hidden = false;
  card.dataset.key = key;

  fetch(q("/api/preflight", { key: key, repo: repo })).then(function (r) {
    return r.json();
  }).then(function (card_data) {
    if (card.dataset.key !== key) return;           // a second drop overtook this one
    var verdict = (card_data && card_data.verdict) || "unknown";
    var chip = card.querySelector(".verdict");
    text(chip, verdict);
    chip.className = "verdict v-" + verdict;
    (card_data.rows || []).forEach(function (r) {
      var li = document.createElement("li");
      li.className = "dispatch-row r-" + (r.verdict || "ready");
      var n = document.createElement("span"); n.className = "dr-name"; text(n, r.row);
      var v = document.createElement("span"); v.className = "dr-value"; text(v, r.value);
      li.appendChild(n); li.appendChild(v);
      if (r.why) { var w = document.createElement("span"); w.className = "dr-why"; text(w, r.why); li.appendChild(w); }
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

function closeDispatch(el) {
  var card = el.querySelector(".dispatch");
  if (card) { card.hidden = true; card.dataset.key = ""; }
}

function dispatch(key, repo, brief) {
  var entry = tiles.get(repo);
  var el = entry ? entry.el : document.body;
  var body = { repo: repo, ticket: key };
  if (brief) body.brief = brief;
  return action(el, "start", body).then(function (r) {
    if (r && r.ok) { boardPanel(false); closeDispatch(el); focus(repo); }
    else if (r && !r.ok && (r.code === "cross_project" || /jira_project/.test(r.error || ""))) {
      // The one refusal worth offering an override for in the page: the operator can see both
      // projects on screen and is better placed than the guard to say it is deliberate.
      if (confirm(r.error + "\n\nStart it anyway?")) {
        var again = { repo: repo, ticket: key, cross_project: true };
        if (brief) again.brief = brief;
        action(el, "start", again).then(function (r2) {
          if (r2 && r2.ok) closeDispatch(el);
          return r2;
        });
      }
    }
    return r;
  });
}

function drawBoard(rows) {
  var list = document.getElementById("tickets");
  var needle = (document.getElementById("boardsearch").value || "").toLowerCase();
  while (list.firstChild) list.removeChild(list.firstChild);
  var shown = rows.filter(function (r) {
    return !needle || (r.key + " " + r.summary + " " + r.status).toLowerCase().indexOf(needle) >= 0;
  });
  shown.forEach(function (r) { list.appendChild(ticketRow(r)); });
  document.getElementById("noboard").hidden = shown.length > 0;
}

function loadBoard(refresh) {
  var err = document.getElementById("boarderr");
  return fetch(q("/api/board", refresh ? { refresh: "1" } : {}))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      err.hidden = !!data.ok;
      if (!data.ok) {
        text(err, data.error + (data.hint ? " — " + data.hint : ""));
        return;
      }
      board = data.rows || [];
      text(document.getElementById("boardage"),
           data.cached ? "cached, " + age(data.age_s) + " old" : "from jira");
      drawBoard(board);
    }).catch(function (e) { err.hidden = false; text(err, String(e)); });
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
          if (cell[1]) td.className = cell[1];
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
    // `ad-fleet repo add` and `repo rm` in a terminal change which tiles exist, and neither is an
    // agent event -- so the stream never mentions it and the grid kept drawing a repository that
    // had left, or never drew one that had arrived, until somebody reloaded the page. The desk's
    // own slow clock already carries the registry's list, so a disagreement is what asks
    // `/api/fleet` again (#173).
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
function drawCells(el, polls) {
  var box = el.querySelector(".cells");
  while (box.firstChild) box.removeChild(box.firstChild);
  CELLS.forEach(function (name) {
    var p = polls[name];
    if (!p) return;
    var value = (p.value && p.value.text) || "";
    if (!value && !p.error) return;                 // nothing to ask about: no PR, no dataset
    var cell = document.createElement("span");
    cell.className = "cell" + (p.grey ? " grey" : "") + (value ? "" : " idle");
    cell.dataset.cell = name;
    var lab = document.createElement("span");
    lab.className = "lab";
    text(lab, name);
    var val = document.createElement("span");
    val.className = "val";
    text(val, value || "—");
    var old = document.createElement("span");
    old.className = "old";
    text(old, p.age_s ? age(Math.round(p.age_s)) : "");
    cell.appendChild(lab);
    cell.appendChild(val);
    cell.appendChild(old);
    cell.title = p.error ? p.error : (name + ", polled every " + p.interval + "s");
    box.appendChild(cell);
  });
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
  nm.className = "nm";
  text(nm, row.name);
  nm.title = row.path + "\n" + row.reason;
  var meta = document.createElement("span");
  meta.className = "meta";
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
    attach.title = "copy it into that repo's .agent/in/<KEY>/ and leave the original here";
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
    why.className = "why";
    text(why, row.reason);
    li.appendChild(why);
  }

  var no = document.createElement("button");
  text(no, "dismiss");
  no.title = "stop offering this file; a newer save of the same name comes back";
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
  document.getElementById("noloose").hidden = (desk.unsorted || []).length > 0;

  var rows = document.getElementById("refusedrows");
  while (rows.firstChild) rows.removeChild(rows.firstChild);
  (desk.not_offered || []).concat(desk.still_writing || []).forEach(function (row) {
    var li = document.createElement("li");
    var nm = document.createElement("span");
    nm.className = "nm";
    text(nm, row.name);
    var why = document.createElement("span");
    why.className = "why";
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
    p.className = "p";
    text(p, hit.project);
    var kind = document.createElement("span");
    kind.className = "kind";
    text(kind, hit.kind);
    var snip = document.createElement("span");
    snip.className = "snip";
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
  document.getElementById("nohits").hidden = (data.results || []).length > 0;
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
function mergeDesk(answer) {
  if (!answer) return;
  var next = Object.assign({}, desk.desk);
  ["selected", "screens", "version", "arrangement"].forEach(function (k) {
    if (answer[k] !== undefined) next[k] = answer[k];
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
  facts.className = "facts";
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
    k.className = "k";
    text(k, row[0]);
    var v = document.createElement("span");
    v.className = "v";
    text(v, row[1]);
    facts.appendChild(k);
    facts.appendChild(v);
  });
  body.appendChild(facts);

  // What is missing is named, so the operator knows which AGENTS.md key would fill the rail.
  var missing = p.missing_keys || [];
  if (missing.length) {
    var gap = document.createElement("p");
    gap.className = "muted";
    text(gap, "add to AGENTS.md for the rest of the rail: " + missing.join(", "));
    body.appendChild(gap);
  }

  // Open friction, and the models and reports the catalogue knows about.
  (p.friction || []).forEach(function (f) {
    var li = document.createElement("p");
    li.className = "frictionrow";
    text(li, [f.date, f.type, f.title].filter(Boolean).join("  ·  ") + (f.unblock ? "\n" + f.unblock : ""));
    body.appendChild(li);
  });

  // Where this project lives -- the link rail, so a tab is opened to act and never to check.
  var links = (p.links || []);
  if (links.length || p.path) {
    var rail = document.createElement("div");
    rail.className = "rail";
    links.forEach(function (row) {
      if (!row.url) return;
      var a = document.createElement("a");
      a.className = row.kind;
      a.href = row.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = row.url;
      text(a, row.name);
      rail.appendChild(a);
    });
    if (p.path) {
      var copy = document.createElement("button");
      text(copy, "copy path");
      copy.title = p.path;
      copy.addEventListener("click", function () {
        clip(p.path);
        text(copy, "copied");
        setTimeout(function () { text(copy, "copy path"); }, 1200);
      });
      rail.appendChild(copy);
    }
    body.appendChild(rail);
  }

  // The newest thing the project's own agent verified, beside the report link.
  var latest = ((p.verify || {}).latest) || {};
  if (latest.name) {
    var h = document.createElement("div");
    h.className = "muted";
    text(h, "verify · " + (latest.tool || "") + " · " + latest.name +
            (latest.age_s != null ? " · " + age(Math.round(latest.age_s)) : ""));
    var pre = document.createElement("pre");
    pre.className = "verifybody";
    text(pre, latest.excerpt || "");
    body.appendChild(h);
    body.appendChild(pre);
  }

  var offers = (desk.offers || {})[name] || [];
  if (offers.length) {
    var head = document.createElement("div");
    head.className = "muted";
    text(head, "Downloads is offering " + offers.length + " file" + (offers.length === 1 ? "" : "s"));
    var list = document.createElement("ol");
    list.className = "tray";
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

function setHidden(name, hide) {
  var curArr = getLayoutArrangement();
  var next = ((curArr.hidden) || []).slice();
  var at = next.indexOf(name);
  if (hide && at < 0) next.push(name);
  if (!hide && at >= 0) next.splice(at, 1);
  post("arrange", { layout: LAYOUT, hidden: next }).then(function (r) {
    if (r && r.ok) { mergeDesk(r); place(); }
  });
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

  var inDom = Array.prototype.map.call(grid.children, function (el) { return el.dataset.repo; });
  var needsMove = inDom.join("\u0000") !== order.filter(function (n) { return tiles.has(n); }).join("\u0000");
  var focused = document.activeElement;
  var refocus = needsMove && focused && focused.closest && focused.closest(".tile") ? focused : null;

  // FLIP, first half: where every tile is *now*, before the DOM moves. A tile that reorders by
  // `appendChild` alone teleports, and a grid that reshuffles itself while agents are talking reads
  // as flicker rather than as movement -- the operator cannot see that the tile they were reading
  // is the same tile, only lower down. Measured only when something is actually moving, and not at
  // all when the viewer has asked for less of it.
  var first = (needsMove && !reduceMotion()) ? measureTiles() : null;

  order.forEach(function (name, index) {
    var entry = tiles.get(name);
    if (entry && entry.el) {
      if (needsMove) grid.appendChild(entry.el);
      // Hidden is a class rather than `el.hidden`, so the tile keeps its slot in `order` and
      // reopening puts it back where it was rather than at the end.
      var off = shown.indexOf(name) < 0;
      entry.el.classList.toggle("is-hidden", off);
      // The number is the key that focuses it, so it counts what is on the glass.
      text(entry.el.querySelector(".n"), off ? "" : String(shown.indexOf(name) + 1));
      var sz = sizes[name] || 1;
      entry.el.classList.toggle("size-2", sz === 2);
      var szBtn = entry.el.querySelector(".sizetoggle");
      if (szBtn) {
        szBtn.classList.toggle("active", sz === 2);
        szBtn.setAttribute("aria-pressed", String(sz === 2));
        szBtn.title = sz === 2 ? "back to one column (Alt+Enter)" : "widen to two columns (Alt+Enter)";
      }
      var isPinned = pinned.indexOf(name) >= 0;
      entry.el.classList.toggle("is-pinned", isPinned);
      var pBtn = entry.el.querySelector(".pintoggle");
      if (pBtn) {
        pBtn.classList.toggle("active", isPinned);
        pBtn.setAttribute("aria-pressed", String(isPinned));
        pBtn.title = isPinned ? "unpin (Alt+Home)" : "pin this tile first (Alt+Home)";
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
    entry.el.classList.remove("flip");
    entry.el.style.transform = "translate(" + dx + "px, " + dy + "px)";
    moved.push(entry.el);
  });
  if (!moved.length) return;
  // Two frames, not one: the inverted transform has to be painted before the transition is armed,
  // or the browser coalesces the two styles and nothing moves at all.
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      moved.forEach(function (el) {
        el.classList.add("flip");
        el.style.transform = "";
      });
    });
  });
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

  var body = { layout: LAYOUT };
  if (inPinnedBlock) body.pinned = block;
  else body.order = block;
  // Optimistic, then confirmed: the tile moves under the hand, and the server's answer is what
  // the next draw reads.
  if (inPinnedBlock) arr.pinned = block; else arr.order = block;
  reorderDomTiles();
  post("arrange", body).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
}

function toggleTileSize(repo) {
  var curArr = getLayoutArrangement();
  var sizes = Object.assign({}, curArr.size || {});
  sizes[repo] = (sizes[repo] === 2) ? 1 : 2;
  curArr.size = sizes;
  reorderDomTiles();
  return post("arrange", { layout: LAYOUT, size: sizes }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
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
  curArr.pinned = pinned;
  reorderDomTiles();
  return post("arrange", { layout: LAYOUT, pinned: pinned }).then(function (r) {
    if (r && r.ok) mergeDesk(r);
    reorderDomTiles();
  });
}

/* Which project this window is showing, when it is showing exactly one. `screens` is the shared
   pinning; a screen with nothing pinned falls back to the Nth registered repo, so opening
   `?layout=screens&screen=2` on a fresh fleet shows something rather than an empty monitor. */
function solo() {
  var names = Array.from(tiles.keys());
  if (LAYOUT === "screens" && SCREEN) {
    var pinned = (desk.desk.screens || [])[SCREEN - 1];
    return pinned || names[SCREEN - 1] || "";
  }
  if (VIEW === "verify") return desk.desk.selected || names[0] || "";
  return "";
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

  while (list.children.length > 1) list.removeChild(list.lastChild);
  if (!off.length) { dock.hidden = true; return; }
  dock.hidden = false;
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
              gone: item.gone, name: item.name };
    groups.set(key, group);
    chips.push(group);
  });

  chips.forEach(function (item) {
    var li = pattern.cloneNode(true);
    li.hidden = false;
    var several = item.members.length > 1;
    var entry = tiles.get(item.name);
    var row = entry ? entry.row : null;
    var needs = item.members.some(function (name) {
      var e = tiles.get(name);
      return !!e && e.el.classList.contains("needs-human");
    });
    li.className = "dock-chip" + (needs ? " needs-human" : "") + (item.gone ? " departed" : "");
    text(li.querySelector(".dc-name"), several ? item.project : item.name);
    text(li.querySelector(".dc-chip"),
         several ? item.members.length + " checkouts"
                 : item.gone ? "removed from the registry"
                 : needs ? ((row && row.why) || "needs you")
                 : ((row && row.state ? row.state : "") + (row && row.at ? " · " + age(ageOf(row)) : "")));
    var badge = li.querySelector(".dc-badge");
    var unreadN = item.members.reduce(function (n, name) { return n + (unread.get(name) || 0); }, 0);
    badge.hidden = !unreadN;
    text(badge, String(unreadN));
    var button = li.querySelector(".dock-open");
    button.title = item.gone
      ? "`ad-fleet repo add " + item.gone.path + "` restores it"
      : several ? "show " + item.project + ": " + item.members.join(", ")
      : (needs ? (row && row.why) || "needs you" : "show " + item.name);
    button.addEventListener("click", function () {
      if (item.gone) return;
      if (item.why === "hidden") setHidden(item.name, false);
      else if (item.why === "quiet") focusMode(false);
      else unfocus();
      focus(item.name);
    });
    list.appendChild(li);
  });
}

function ageOf(row) {
  return row && typeof row.last_event_age_s === "number" ? row.last_event_age_s : 0;
}

function place() {
  var body = document.body;
  var one = solo();
  body.classList.remove("layout-grid", "layout-roles", "layout-screens",
                        "view-board", "view-agents", "view-verify", "solo", "panels");
  body.classList.add("layout-" + LAYOUT);
  if (VIEW) body.classList.add("view-" + VIEW);
  if (one) body.classList.add("solo");
  if ((LAYOUT === "roles" && VIEW === "board") || (LAYOUT === "screens" && !SCREEN)) {
    body.classList.add("panels");
  }
  body.classList.toggle("needs-only", needsOnly);
  tiles.forEach(function (entry, name) {
    entry.el.classList.toggle("is-solo", name === one);
    entry.el.classList.toggle("is-selected", name === desk.desk.selected);
  });
  reorderDomTiles();
  if (one) {
    // Opened once, not on every draw: a window that reopens a panel the operator just closed is
    // the kind of thing that gets a dashboard turned off.
    // A window showing exactly one project opens the inspector on it, once -- reopening a panel
    // the operator just closed is the kind of thing that gets a dashboard turned off.
    var entry = tiles.get(one);
    if (entry && entry.el.dataset.opened !== "1") {
      entry.el.dataset.opened = "1";
      section("inspector", true);
    }
  }
  var need = 0;
  tiles.forEach(function (entry) { if (entry.el.classList.contains("needs-human")) need += 1; });
  // "Nothing needs you" is only true of an EMPTY screen. Held tiles are still on it, so the prompt
  // to leave focus mode would be sitting under the very tiles it claims are not there.
  document.getElementById("nonefocus").hidden =
    !(needsOnly && !one && need === 0 && held.size === 0 && tiles.size > 0);
  drawNotice();
  drawSwap(one);
  drawDock();
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
    notice.hidden = false;
    return;
  }
  saidLine = "";
  if (unknownLayout) {
    text(notice, "unknown layout '" + unknownLayout + "' — showing grid");
    notice.hidden = false;
  } else {
    text(notice, "");
    notice.hidden = true;
  }
}

/* The tab bar is the friction, so the window's own title says which screen it is. */
function title(need) {
  var one = solo();
  document.title = (need ? "(" + need + ") " : "") + "fleet" +
                   (LAYOUT === "grid" ? "" : " · " + (VIEW || ("screen " + (SCREEN || "board")))) +
                   (one ? " · " + one : "");
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
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-checked", String(active));
  });

  var group = document.getElementById("viewgroup");
  var rows = VIEW_SEGMENTS[LAYOUT];
  group.hidden = !rows;
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
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-checked", String(on));
    });
    return;
  }
  group.dataset.built = want;
  while (group.firstChild) group.removeChild(group.firstChild);
  rows.forEach(function (row) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "segment";
    btn.setAttribute("role", "radio");
    btn.dataset.value = row[0];
    var mine = LAYOUT === "roles" ? (VIEW === row[0]) : (String(SCREEN || "") === row[0]);
    btn.classList.toggle("active", mine);
    btn.setAttribute("aria-checked", String(mine));
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
  LAYOUT = unknownLayout ? "grid" : (rawL || "grid");
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
  swap.hidden = !(LAYOUT === "screens" && SCREEN);
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
  document.getElementById("focus").setAttribute("aria-pressed", String(needsOnly));
  // Leaving focus mode is the operator saying they are done with this pass, so the tiles being
  // held for them are let go. Otherwise the next `f` would open on the last visit's leftovers.
  // The record is emptied in the *same* write as the mode, because the `desk` event this save
  // rides back down would otherwise re-hydrate the set through `applyWindow` -- which merges the
  // record's `held` additively, so a clear that is not posted is undone a tick later.
  var patch = { focus: needsOnly };
  if (!needsOnly) {
    held.clear();
    patch.held = [];
  }
  if (!skipPost) saveWindow(patch);
  place();
}

document.getElementById("showall").addEventListener("click", function () {
  post("arrange", { layout: LAYOUT, hidden: [] }).then(function (r) {
    if (r && r.ok) { mergeDesk(r); if (needsOnly) focusMode(false); else place(); }
  });
});

document.getElementById("focus").addEventListener("click", function () { focusMode(); });

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape" && !typing) { closeSide(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "f") { focusMode(); return; }
  if (e.key === "i") { section("unsorted"); return; }
  if (e.key === "/") { e.preventDefault(); document.getElementById("find").focus(); }
});
