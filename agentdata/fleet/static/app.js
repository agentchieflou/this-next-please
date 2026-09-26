"use strict";

/**
 * @typedef {Object} DeskRecord
 * @property {number} [schema]
 * @property {string} [selected]
 * @property {number} [version]
 * @property {string} [at]
 * @property {Arrangement} [arrangement]
 * @property {Object<string, WindowRecord>} [windows]
 * @property {Object<string, number>} [measure]
 */

/**
 * @typedef {Object} Arrangement
 * @property {string[]} [order]
 * @property {Object<string, {cols: number, rows: number} | number>} [size]
 * @property {string[]} [pinned]
 * @property {string[]} [hidden]
 */

/**
 * @typedef {Object} WindowRecord
 * @property {string} [open]
 * @property {boolean} [focus]
 * @property {Object<string, number>} [read]
 * @property {string} [seen]
 * @property {string[]} [held]
 * @property {string} [section]
 * @property {Widths} [widths]
 * @property {number} [widths_at]
 */

/** @typedef {Object<string, number>} Widths */

/**
 * @typedef {Object} WindowWrite
 * @property {string} [open]
 * @property {Widths} [widths]
 * @property {Object<string, number>} [read]
 * @property {string} [seen]
 * @property {string} [section]
 */

/**
 * @typedef {DeskRecord & {ok?: boolean, action?: string, error?: string, hint?: string, code?: string}} DeskAnswer
 */

/**
 * @typedef {{ repo?: string, project?: string, path?: string, state?: string, needs_human?: boolean, why?: string, last_said?: string, last_event_age_s?: number, spend?: {total?: number, [field: string]: any}, recent?: Array<{seq: number}>, as_of?: {run: string, n: number}, [field: string]: any }} Row
 */

/** @typedef {"rail" | "compact" | "full"} Tier */

/**
 * @typedef {Object} Tiers
 * @property {number} rail
 * @property {number} compact
 * @property {number} full
 * @property {number} slack
 * @property {string} invalid
 */

/**
 * @typedef {Object} Pane
 * @property {HTMLElement} el
 * @property {number} seq
 * @property {Row} [row]
 * @property {boolean} [restored]
 */

var tiles = /** @type {Map<string, Pane>} */ (new Map());
var pendingRefresh = null;
var source = null;
var arrivedSinceLastPlace = false;

var RETIRED_PARAMS = ["layout", "view", "screen"];
var ignoredParams = RETIRED_PARAMS.filter(function (k) { return PARAMS.has(k); });
var W_NAME = PARAMS.get("w") || "main";
var BOOT_HASH = location.hash || "";

var desk = /** @type {{desk: DeskRecord, [answer: string]: any}} */ ({ projects: {}, offers: {}, unsorted: [], not_offered: [], folders: [],
             desk: { selected: "" } });
var pendingDesk = null;
var readCursors = /** @type {Object<string, number>} */ ({});
var streamDead = false;
var awayShown = false;
var appliedInitialWindow = false;
var openTile = "";
var previousOpen = "";
var myWidths = /** @type {Widths | null} */ (null);
var PREFLIGHT = true;

var windowWrites = 0;
var windowChain = /** @type {Promise<DeskAnswer | null | void>} */ (Promise.resolve());

/**
 * @param {WindowWrite} patch
 * @returns {Promise<DeskAnswer | null | void>}
 */
function saveWindow(patch) {
  var body = /** @type {WindowWrite & {w: string, version?: number}} */ (Object.assign({ w: W_NAME }, patch));
  windowWrites += 1;
  windowChain = windowChain.then(function () {
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

/**
 * @param {DeskAnswer} payload
 * @returns {boolean}
 */
function acceptDesk(payload) {
  if (!payload || typeof payload !== "object") return false;
  var have = desk.desk ? desk.desk.version : undefined;
  if (payload.version !== undefined && have !== undefined &&
      Number(payload.version) < Number(have)) return false;
  var next = Object.assign({}, payload);
  delete next.ok;
  delete next.action;
  if (arrangeWrites && desk.desk && desk.desk.arrangement) next.arrangement = desk.desk.arrangement;
  desk.desk = next;
  var win = next.windows && next.windows[W_NAME];
  if (win && !windowWrites) applyWindow(win);
  if (next.measure && next.measure[W_NAME]) goProbe();
  return true;
}

function rehome() {
  var more = new URLSearchParams();
  if (PARAMS.get("shell")) more.set("shell", PARAMS.get("shell"));
  if (PARAMS.get("ink")) more.set("ink", PARAMS.get("ink"));
  var rest = more.toString();
  window.location.href = "/open?w=" + encodeURIComponent(W_NAME) + (rest ? "&" + rest : "");
}

onAuthLost = function () { if (streamDead) rehome(); };

function age(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return seconds + "s";
  if (seconds < 5400) return Math.floor(seconds / 60) + "m";
  return Math.floor(seconds / 3600) + "h";
}

function agentAge(seconds) { return ageChip(seconds).text; }

function ageChip(seconds) {
  if (seconds == null || seconds < 0) return { text: "", stale: false };
  if (seconds < 90) return { text: seconds + "s", stale: false };
  if (seconds < 5400) return { text: Math.floor(seconds / 60) + "m", stale: false };
  if (seconds < 86400) return { text: Math.floor(seconds / 3600) + "h", stale: false };
  return { text: Math.floor(seconds / 86400) + "d", stale: true };
}

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
    case "project.ticket_changed": return (d.key || "") + " is " + (d.status || "") +
                                          (d.assignee ? " · " + d.assignee : "");
    case "project.refresh_finished": return "refresh " + (d.status || "") + " " + (d.end || "");
    case "project.pr_merged": return "PR merged: " + (d.url || "");
    case "inbox.attached": return (d.attached ? "attached " : "already there: ") +
                                  (d.name || "") + " → " + (d.dir || "");
    case "pr_open": return d.url || "";
    case "artifact": return (d.artifact && d.artifact.path) || "";
    case "session_id": return "";
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
  text(v, body);
  li.appendChild(k);
  li.appendChild(v);
  var wasAtBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) <= 40;
  list.appendChild(li);
  while (list.children.length > 200) list.removeChild(list.firstChild);
  if (wasAtBottom) {
    list.scrollTop = list.scrollHeight;
  }
}

/**
 * @param {Row} row
 * @param {number} index
 * @returns {HTMLElement}
 */
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
  el.addEventListener("click", /** @type {(e: MouseEvent & {target: Element}) => void} */ (function (e) {
    if (e.target.closest("button, input, select, textarea, a, details, summary")) return;
    choose(row.repo);
  }));

  var head = el.querySelector(".head");
  bindDragToReorder(head, el, row.repo);

  var face = /** @type {HTMLElement} */ (el.querySelector(".pane-rail"));
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
    el.classList.remove("drop-target", "drop-before", "drop-after");

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
      var done = (r && r.ok !== false && r.answered) || [];
      Array.prototype.forEach.call(el.querySelectorAll(".asks-list .ask"), function (li) {
        if (done.indexOf(li.dataset.qid) >= 0) toggle(li, "is-answered", true);
      });
    });
  });

  bindTools(el, row.repo);

  el.querySelector(".scope-close").addEventListener("click", function () {
    hide(el.querySelector(".scope"), true);
  });
  el.querySelector(".scope-tell").addEventListener("click", function () {
    action(el, "send", { repo: row.repo, message:
      "New files are in the scope under .agent/in/; read scope.toon before continuing." });
  });


  el.querySelector(".spill").addEventListener("click", function () { toggleMenu(el, row.repo); });
  el.querySelector(".sm-live").addEventListener("click", function () {
    closeMenu(el);
    if (viewing(el)) backToLive(el);
  });
  var smNew = /** @type {HTMLElement} */ (el.querySelector(".sm-new"));
  smNew.addEventListener("click", function () {
    closeMenu(el);
    startFresh(el, row.repo, smNew);
  });
  ["freshtoggle", "fresh-strip"].forEach(function (cls) {
    var b = /** @type {HTMLElement} */ (el.querySelector("." + cls));
    if (b) b.addEventListener("click", function (e) { e.stopPropagation(); startFresh(el, row.repo, b); });
  });
  el.querySelector(".sm-console").addEventListener("click", function () {
    closeMenu(el);
    openConsole(el, row);
  });
  el.querySelector(".ro-resume").addEventListener("click", function () { resumeHere(el, row.repo); });
  el.querySelector(".ro-back").addEventListener("click", function () { backToLive(el); });

  el.addEventListener("keydown", function (e) {
    if (!e.altKey) return;
    if (e.shiftKey) {
      if (e.key === "ArrowRight") { stepGutter(el, 1); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { stepGutter(el, -1); e.preventDefault(); }
      return;
    }
    if (e.key === "ArrowLeft") { moveTile(row.repo, -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { moveTile(row.repo, 1); e.preventDefault(); }
    else if (e.key === "Home") { toggleTilePin(row.repo); e.preventDefault(); }
    else if (e.key === "Enter") { evenGutter(el); e.preventDefault(); }
    else if (e.key === "[") { stepMenu(el, row.repo, -1); e.preventDefault(); }
    else if (e.key === "]") { stepMenu(el, row.repo, 1); e.preventDefault(); }
    else if (e.key === "n" || e.key === "N") { startFresh(el, row.repo, null); e.preventDefault(); }
  });

  var pinBtn = el.querySelector(".pintoggle");
  if (pinBtn) {
    pinBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleTilePin(row.repo);
    });
  }

  var maxBtn = el.querySelector(".maxtoggle");
  if (maxBtn) {
    maxBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      openAgent(row.repo);
    });
  }

  var adoptBtn = /** @type {HTMLElement} */ (el.querySelector(".adopt"));
  if (adoptBtn) {
    adoptBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var what = adoptBtn.dataset.what === "release" ? "release" : "adopt";
      action(el, what, { repo: row.repo, pid: Number(adoptBtn.dataset.pid || 0) });
    });
  }

  var say = /** @type {HTMLInputElement} */ (el.querySelector(".say"));
  var sendBtn = /** @type {HTMLButtonElement} */ (el.querySelector(".send"));
  sendBtn.addEventListener("click", function () {
    var forcing = sendBtn.dataset.force === "1";
    action(el, el.dataset.console ? "say" : "send",
           { repo: row.repo, message: say.value, force: forcing })
      .then(function (r) {
        if (r && r.ok) { say.value = ""; disarmSend(sendBtn); drawStart(el, rowOf(row)); return; }
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
  var startBtn = /** @type {HTMLButtonElement} */ (el.querySelector(".start"));
  startBtn.addEventListener("click", function () {
    if (!say.value.trim()) startFresh(el, row.repo, startBtn);
    else action(el, "start", { repo: row.repo, ticket: say.value.trim() });
  });
  say.addEventListener("input", function () { drawStart(el, rowOf(row)); });
  el.querySelector(".stop").addEventListener("click", function () {
    action(el, "stop", { repo: row.repo });
  });

  var resetBtn = /** @type {HTMLButtonElement} */ (el.querySelector(".reset"));
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
    if (r.row) { patchRow(r.row); place(); }
    else refresh();
    settle(mark);
    return r;
  }).catch(function (e) { fail(el, String(e)); });
}

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
        drawStart(el, (tiles.get(el.dataset.repo || "") || {}).row);
        say.focus();
      });
      strip.appendChild(li);
    });
  }
}

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

function paintAccent(el, accent) {
  if (!el || !accent) return;
  style(el, "border-left-color", accent);
}

var TRACE_H = 18;

function traceHeights(tr) {
  var counts = tr.n || [];
  var peak = tr.peak || 1;
  var out = [];
  for (var i = 0; i < counts.length; i++) {
    var n = counts[i] || 0;
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
  setData(el, "trace", (tr.peak || 1) + "|" + (tr.n || []).map(function (n, j) {
    return n + (needs[j] ? "!" : "");
  }).join(" "));

  var line = el.querySelector(".tr-line");
  var marks = el.querySelector(".tr-ticks");
  attr(line, "points", any ? heights.map(function (h, j) {
    var y = (TRACE_H - 1.5) - (h ? Math.max(1, h * (TRACE_H - 3)) : 0);
    return (j + 0.5) + "," + (Math.round(y * 100) / 100);
  }).join(" ") : "");
  attr(marks, "d", any ? ticks.map(function (j) { return "M" + (j + 0.5) + " " + TRACE_H + "V0"; }).join("") : "");
}

var TILE_OWNED = /^(tile|state-[A-Za-z_]+)$/;

function setOwned(el, owned, wanted) {
  var kept = Array.prototype.filter.call(el.classList, function (name) {
    return !owned.test(name);
  });
  setClass(el, wanted.concat(kept).join(" "));
}

function setTileState(el, state) {
  setOwned(el, TILE_OWNED, ["tile", "state-" + state]);
}

function shownState(row) {
  var cold = row.supervised === false && !!row.not_supervised_sentence;
  return cold ? "idle" : (row.state || "");
}

/**
 * @param {HTMLElement} el
 * @returns {{wide: boolean, full: boolean}}
 */
function paneShows(el) {
  var tier = el.dataset.tier || "rail";
  return { wide: tier !== "rail", full: tier === "full" };
}

function drawTile(el, row, approvals) {
  var isSupervised = row.supervised !== false;
  var cold = !isSupervised && !!row.not_supervised_sentence;
  var displayState = shownState(row);
  var shows = paneShows(el);
  setTileState(el, displayState);
  paintAccent(el, row.accent);
  if (shows.full) drawTrace(el.querySelector(".trace"), row);
  toggle(el, "needs-human", !!row.needs_human);
  toggle(el, "is-done", row.state === "done");
  tabbable(el, shows.wide ? 0 : -1);
  var modelBtn = el.querySelector(".modeltoggle .bm-name");
  if (modelBtn) {
    var runs = chipModel(row);
    text(modelBtn, shortModel(runs.id));
    setClass(modelBtn, runs.next ? "bm-name next" : "bm-name");
    attr(modelBtn, "title", runs.next ? "from the next turn · the last turn ran " +
         (row.launched || "the CLI's own choice") : null);
  }
  var modelHost = el.querySelector(".modeltoggle");
  if (modelHost) attr(modelHost, "title", modelTitle(row));
  var ac = ageChip(row.last_event_age_s);
  var chip = el.querySelector(".chip");
  setClass(chip, "chip " + displayState + (ac.stale ? " stale" : ""));
  text(chip.querySelector(".chipword"), displayState.replace(/_/g, " "));
  text(chip.querySelector(".chipage"), ac.text ? " · " + ac.text : "");
  attr(chip, "title", "state from the fold" + (ac.text ? ", last event " + ac.text + " ago" : ""));
  text(el.querySelector(".ticket"), row.ticket || row.jira_project || "");
  drawOldSession(el, row);
  drawFresh(el, row);
  drawStart(el, row);

  text(el.querySelector(".why"), cold ? row.not_supervised_sentence : (row.why || ""));

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
      text(adoptBtn, "stop following it");
      setData(adoptBtn, "what", "release");
      toggle(adoptBtn, "quiet", true);
      attr(adoptBtn, "title", "the pane goes back to the fleet's own last run; your terminal chat is untouched");
    } else if (offer) {
      hide(outside, false);
      toggle(outside, "mine", false);
      text(outside.querySelector(".outsidewhy"),
           "something is working in this checkout that the fleet did not start" +
           (offer.pid ? " (pid " + offer.pid + ")" : "") +
           " — last wrote " + age(offer.active_age_s) + " ago, " + offer.how);
      text(adoptBtn, "adopt it");
      setData(adoptBtn, "what", "adopt");
      toggle(adoptBtn, "quiet", false);
      setData(adoptBtn, "pid", String(offer.pid || 0));
      attr(adoptBtn, "title", "make that session this repo's current one, instead of the last run the fleet started");
    } else {
      hide(outside, true);
    }
  }
  setData(el, "console", row.console ? String(row.console.pid || 0) : "");
  ["send", "start"].forEach(function (cls) {
    var btn = el.querySelector("." + cls);
    if (!btn) return;
    disable(btn, !!row.external);
    if (cls === "send") attr(btn, "title", row.external ? EXTERNAL_TITLE : "");
  });
  ["stop", "reset"].forEach(function (cls) {
    var btn = /** @type {HTMLButtonElement} */ (el.querySelector("." + cls));
    if (!btn) return;
    var was = btn.disabled;
    disable(btn, !!row.external);
    if (row.external) attr(btn, "title", "your own Copilot chat — close it in its window; start fresh leaves it");
    else if (was) attr(btn, "title", cls === "reset" ? "unblock it: end the stuck process and resume the same session" : null);
  });

  var run = row.run || {};
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

function viewing(el) {
  return el.dataset.viewing || "";
}

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

  var bits;
  if (open) bits = ["earlier session", el.dataset.endedState || "ended", el.dataset.endedWhen || ""];
  else bits = [el.dataset.console ? "console" : "session", row.state || "",
               row.last_event_age_s >= 0 ? agentAge(row.last_event_age_s) : ""];
  text(pill, bits.filter(Boolean).join(" · "));
  attr(pill, "title", open ? "reading an earlier session — the menu goes back to the live one"
                    : (run.session ? "session " + run.session : "this checkout's live session"));
  toggle(pill, "is-reading", !!open);

  text(el.querySelector(".sm-console-label"), row.console ? "show console" : "open in a console");
  var startsOn = row.model ? shortModel(row.model) : "the CLI chooses";
  var startsWhy = "starts on " + (row.model || "whatever the CLI picks") + " (" +
                  (row.model_source || "cli-auto") + ")";
  Array.prototype.forEach.call(el.querySelectorAll(".sm-model"), function (m) {
    text(m, startsOn);
    attr(m, "title", startsWhy);
  });

  var n = row.sessions_n || 0;
  var label = el.querySelector(".sm-earlier-label");
  hide(label, !n);
  text(label, "earlier (" + n + ")");

  drawRuns(el.querySelector(".live-runs"), runsFor(row, el.dataset.session || ""));

  var sibs = row.siblings || [];
  var sibList = el.querySelector(".sib-list");
  hide(el.querySelector(".sm-sibs-label"), !sibs.length);
  patchList(sibList, sibs, function (sib) { return sib.repo; },
    function () {
      var pattern = sibList.querySelector(".sib-row:not([data-rowkey])");
      var li = /** @type {HTMLElement} */ (pattern.cloneNode(true));
      hide(li, false);
      li.querySelector(".sib-open").addEventListener("click", function () {
        closeMenu(el);
        openAgent(li.dataset.rowkey);
      });
      return li;
    },
    function (li, sib) {
      var button = li.querySelector(".sib-open");
      text(button, [sib.branch || sib.repo, sib.state, sib.age].filter(Boolean).join(" · "));
      attr(button, "title", "the same project, checked out at " + (sib.path || sib.repo));
    });
}

function runsFor(row, session) {
  return (row.earlier || []).filter(function (r) {
    return !session || !r.session || r.session === session;
  });
}

function drawRuns(list, runs) {
  if (!list) return;
  hide(list, !runs.length);
  patchList(list, runs, function (r) { return r.n; },
    function () { return document.createElement("li"); },
    function (li, r) {
      text(li, "run " + r.n + " · " + (r.ticket ? r.ticket + " · " : "") + r.state +
               " (" + (r.started ? String(r.started).slice(11, 16) : "") +
               (r.ended ? "–" + String(r.ended).slice(11, 16) : "") + ")");
    });
}

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
        text(li.querySelector(".ss-src"), SESSION_SOURCE[r.source] || "");
        text(li.querySelector(".ss-chip"), r.left ? "left · " + whenIso(r.left) : (r.ended || ""));
        text(li.querySelector(".ss-when"), whenIso(r.last_seen));
        text(li.querySelector(".ss-cost"), r.cost ? Number(r.cost).toFixed(2) + " premium" : "");
        var button = li.querySelector(".ss-open");
        attr(button, "title",
             (el.dataset.console ? "the console still owns this; close it first — " : "")
             + "session " + r.id
             + ((r.sources || []).join(" → ") ? " · " + r.sources.join(" → ") : ""));
        button.addEventListener("click", function () { closeMenu(el); showSession(el, repo, r); });
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
      setData(el, "endedState", (data && data.state) || "ended");
      setData(el, "endedWhen", whenIso(data && data.at));
      var pane = el.querySelector(".readonly");
      hide(pane, false);
      text(el.querySelector(".ro-what"),
           (session.title ? session.title + " — " : "") + endedSentence(data));
      var resume = el.querySelector(".ro-resume");
      text(resume, "Resume here");
      setData(resume, "armed", "");
      text(el.querySelector(".ro-note"),
           el.dataset.console ? "the console still owns this — close it, then resume" : "");
      hide(el.querySelector(".row.bottom"), true);
      var entry = tiles.get(repo);
      if (entry && entry.row) drawSessionPill(el, entry.row);
    });
}

function stepMenu(el, repo, dir) {
  if (!menuOpen(el)) {
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
    if (r && (r.code === "live_agent" || r.code === "mid_ticket")) {
      setData(button, "armed", "1");
      text(button, r.code === "live_agent" ? "Stop and resume" : "Resume anyway");
    }
  });
}

function openConsole(el, row) {
  if (el.dataset.console) return action(el, "focus", { repo: row.repo });
  var body = { repo: row.repo };
  if (row.ticket) body.ticket = row.ticket;
  if (el.dataset.session) body.resume = el.dataset.session;
  return action(el, "console", body).then(function (r) { if (r && r.ok) refresh(); return r; });
}

var SESSION_SOURCE = { adopted: "your chat", console: "console" };

function freshShown(row) {
  return !!(row && row.fresh && row.fresh.offer);
}

function freshWords(row) {
  var f = (row && row.fresh) || {};
  var st = f.starts || {};
  var on = (st.ticket ? "on " + st.ticket : "with no ticket") + " on " +
           (st.model_label || "the CLI's own choice") + " (" + (st.model_source || "cli-auto") + ")";
  return "a clean session " + on + "; this one stays under earlier (" + ((row.sessions_n || 0) + 1) + ")";
}

function drawFresh(el, row) {
  var f = row.fresh || {};
  var head = el.querySelector(".freshtoggle");
  hide(head, !row.fresh);
  toggle(head, "is-offer", freshShown(row));
  attr(head, "title", f.verdict && f.verdict !== "now" ? f.why : freshWords(row) + " — Alt+N");
  var strip = el.querySelector(".fresh-strip");
  hide(strip, !row.external);
  attr(strip, "title", freshWords(row));
  attr(el.querySelector(".sm-new"), "title", freshWords(row) + " (Alt+N)");
  if (el.dataset.freshArmed && el.dataset.freshArmed !== (f.verdict || "")) disarmFresh(el);
}

var EXTERNAL_TITLE = "type in that window — this session is not the fleet's to drive";

function rowOf(row) {
  var entry = tiles.get(row.repo);
  return (entry && entry.row) || row;
}

function beganWords(ts) {
  if (!ts) return "";
  var s = String(ts);
  var d = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(s) ? s : s + "Z");
  if (isNaN(d.getTime())) return "";
  var hm = ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  var now = new Date();
  var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "today " + hm;
  if (d.toDateString() === yesterday.toDateString()) return "yesterday " + hm;
  return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2) + " " + hm;
}

function startFreshWords(row) {
  var f = (row && row.fresh) || {};
  var st = f.starts || {};
  var run = (row && row.run) || {};
  var on = "a clean session on " + (st.ticket || "no ticket — session-bootstrap, then router") + " on " +
           (st.model_label || "the CLI's own choice");
  if (!(f.leaves && f.leaves.session)) return on;
  var began = beganWords(run.session_began || run.started);
  return on + "; this one" + (began ? " (began " + began + ")" : "") + " stays under earlier (" +
         (((row && row.sessions_n) || 0) + 1) + ")";
}

function drawStart(el, row) {
  var start = el.querySelector(".bottom .start");
  var box = /** @type {HTMLInputElement} */ (el.querySelector(".say"));
  if (!start || !box || !row) return;
  var empty = !box.value.trim();
  var label = empty ? "Start fresh" : "Start";
  if (empty && el.dataset.freshArmed) label = "start fresh — it is closed";
  text(start, label);
  var f = row.fresh || {};
  attr(start, "title", row.external ? EXTERNAL_TITLE : !empty ? "" :
       f.verdict && f.verdict !== "now" ? f.why : startFreshWords(row));
}

function disarmFresh(el) {
  setData(el, "freshArmed", "");
  [".freshtoggle", ".fresh-strip"].forEach(function (sel) { text(el.querySelector(sel), "start fresh"); });
  text(el.querySelector(".sm-new-label"), "start fresh");
}

/**
 * @param {HTMLElement} el
 * @param {string} repo
 * @param {HTMLElement|null} button
 */
function startFresh(el, repo, button) {
  var closed = !!el.dataset.freshArmed;
  var rail = !paneShows(el).wide;
  var tell = function (words) {
    if (rail) say(repo + ": " + words);
    else fail(el, words);
  };
  fail(el, "");
  return post("fresh", closed ? { repo: repo, closed: true } : { repo: repo }).then(function (r) {
    if (r && r.ok) {
      disarmFresh(el);
      if (viewing(el)) backToLive(el);
      if (r.row) { patchRow(r.row); place(); } else refresh();
      var left = (r.leaves || {});
      var n = ((r.row && r.row.sessions_n) || 0);
      say(repo + ": " + (left.session ? "left " + (left.title || left.session) +
                                        " — it is under earlier (" + n + ")" : "started fresh"));
      return r;
    }
    var words = [r && r.error, r && r.hint].filter(Boolean).join(" — ");
    if (r && r.second_press) {
      var entry = tiles.get(repo);
      setData(el, "freshArmed", ((entry && entry.row && entry.row.fresh) || {}).verdict || "second_press");
      if (button) text(button.querySelector(".sm-new-label") || button, "start fresh — it is closed");
      tell(rail ? words + " — press Alt+N again once it is closed" : words);
    } else {
      tell(words);
    }
    return r;
  }).catch(function (e) { tell(String(e)); });
}

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
  if (win.open !== undefined && win.open !== openTile) {
    openTile = String(win.open || "");
  }
  myWidths = ownWidths(win.widths);
  if (win.section && win.section !== lastSection) {
    section(win.section, true, true);
  }
  if (win.read && typeof win.read === "object") {
    Object.assign(readCursors, win.read);
  }
}

var probing = false;
var probeWaiting = 0;

function unsentText() {
  var boxes = /** @type {NodeListOf<HTMLInputElement | HTMLTextAreaElement>} */ (document.querySelectorAll(".say, .brief"));
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

var lastApprovals = [];

function redrawAll() {
  tiles.forEach(function (entry) {
    if (entry.row) drawTile(entry.el, entry.row, lastApprovals);
  });
  place();
}

/**
 * @param {Row | undefined} shown
 * @param {Row} row
 * @returns {boolean}
 */
function readBefore(shown, row) {
  var had = shown && shown.as_of, got = row.as_of;
  return !!(had && got && had.run === got.run && got.n < had.n);
}

/**
 * @param {Pane} entry
 * @param {Row} row
 */
function fillTranscript(entry, row) {
  (row.recent || []).forEach(function (ev) { append(entry.el, ev); entry.seq = ev.seq; });
  try {
    var savedScroll = sessionStorage.getItem("fleet.scroll." + row.repo);
    if (savedScroll !== null) {
      entry.el.querySelector(".transcript").scrollTop = Number(savedScroll);
    }
  } catch (e) {}
}

/**
 * @param {Row} row
 * @param {number} [index]
 * @returns {Pane | null}
 */
function patchRow(row, index) {
  if (!row || !row.repo) return null;
  var entry = tiles.get(row.repo);
  if (entry && readBefore(entry.row, row)) return entry;
  if (!entry) {
    var el = makeTile(row, index || tiles.size);
    var grid = document.getElementById("grid");
    if (grid) grid.appendChild(el);
    watchPane(el);
    arrivedSinceLastPlace = true;
    entry = { el: el, seq: 0 };
    tiles.set(row.repo, entry);
    fillTranscript(entry, row);
  } else if (entry.restored) {
    entry.restored = false;
    fillTranscript(entry, row);
  }
  entry.row = row;
  departed.delete(row.repo);
  drawTile(entry.el, row, lastApprovals);
  return entry;
}

var SNAP_KEY = "fleet.snapshot." + W_NAME;
var SNAP_GOOD_FOR_MS = 5 * 60 * 1000;
var lastFleet = null;
var themeEvents = 0;

/**
 * @param {DeskRecord | null} fallback
 * @returns {DeskRecord | null}
 */
function deskAsShown(fallback) {
  var d = desk.desk || fallback;
  if (!d) return null;
  d = JSON.parse(JSON.stringify(d));
  d.windows = d.windows || {};
  var mine = Object.assign({}, d.windows[W_NAME] || {});
  if (openTile) mine.open = openTile;
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
  } catch (e) {}
}

/** @returns {Tiers | null} */
function servedTiers() {
  var said = document.documentElement.dataset.tiers;
  if (!said) return null;
  var n = said.split(" ").map(Number);
  return { rail: n[0], compact: n[1], full: n[2], slack: n[3], invalid: "" };
}

window.addEventListener("pageshow", function (e) { if (e.persisted) refresh(); });

window.addEventListener("pagehide", function () { if (lastFleet) cacheSnapshot(lastFleet); });

function restoreCached() {
  var data = null;
  try {
    var raw = sessionStorage.getItem(SNAP_KEY);
    data = raw ? JSON.parse(raw) : null;
  } catch (e) { return false; }
  if (!data || !(data.repos || []).length) return false;
  if (Date.now() - (data.at || 0) > SNAP_GOOD_FOR_MS) return false;
  if (data.desk) {
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
    if (e) e.restored = true;
  });
  hide(document.getElementById("empty"), true);
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
        departed.set(name, { path: (entry.row && entry.row.path) || "<path>" });
        forgetPane(entry.el);
        entry.el.remove();
        tiles.delete(name);
      }
    });
    var need = data.repos.filter(function (r) { return r.needs_human; }).length;
    drawRenewStrip(data.repos, data.server);
    drawDayOffer(data.repos);
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
    if (fleetSpend.budget_invalid) {
      say("fleet.budget_per_agent is " + JSON.stringify(fleetSpend.budget_invalid) +
          ", which is not a number — the cap is off until it is one", 20);
    }
    if (data.desk) acceptDesk(data.desk);
    if (themeEvents !== themesAsked) delete data.theme;
    if (data.theme) {
      applyTheme(data.theme.css, data.theme.theme);
      applySkin(data.theme.skin);
      applyTiers(data.theme.tiers);
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
  source.addEventListener("polls", function () { refreshSoon(); });
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
      applyTiers(d.tiers);
      if (d.accents) {
        Object.keys(d.accents).forEach(function (repo) {
          if (tiles.has(repo)) paintAccent(tiles.get(repo).el, d.accents[repo]);
        });
      }
    } catch (err) {}
  });
  source.addEventListener("models", function () {
    modelCatalogueStale = true;
    if (modelCardRepo() || dispatchRepo()) {
      loadModelCatalogue().then(function () { drawModelCard(); drawDispatchModel(); });
    }
  });
  source.addEventListener("wrapup", function (m) {
    try {
      var d = JSON.parse(m.data);
      if (wrapOpen() && d.repo === wrap.repo && (!wrap.job || d.job === wrap.job)) loadWrap();
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
    setTimeout(function () { refresh().then(connect); }, 2000);
  };
}

function openAgent(name, skipPost) {
  unread.delete(name);
  var entry = tiles.get(name);
  if (entry && entry.seq) {
    readCursors[name] = entry.seq;
  }
  bell();
  drawer(false);
  markTile(name);
  openPane(name, skipPost);
  if (!skipPost) saveWindow({ read: readCursors });
}

function followHash() {
  var m = /^#tile=(.+)$/.exec(location.hash || "");
  if (!m) return;
  var name = decodeURIComponent(m[1]);
  if (!tiles.has(name)) {
    say("no tile for '" + name + "' — is it still registered?");
    return;
  }
  if (isHidden(name)) {
    setHidden(name, false);
    say(name + " was hidden — reopened");
  }
  openAgent(name);
}

window.addEventListener("hashchange", followHash);

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape") {
    if (closeModelCard()) { e.stopImmediatePropagation(); return; }
    if (closeMenus()) { e.stopImmediatePropagation(); return; }
    if (closePopovers()) { e.stopImmediatePropagation(); return; }
    var card = document.getElementById("dispatch");
    if (card && !card.hidden) { closeDispatch(); e.stopImmediatePropagation(); return; }
    if (closeWrapup()) { e.stopImmediatePropagation(); return; }
    if (typing) /** @type {HTMLElement} */ (document.activeElement).blur();
    else backToPrevious();
    return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[2-9]$/.test(e.key)) {
    var pane = paneStops()[Number(e.key) - 1];
    var tile = /** @type {HTMLElement} */ (pane && pane.closest ? pane.closest(".tile") : null);
    if (tile && tile.dataset.repo) openPane(railTarget(tile.dataset.repo), false, true);
    return;
  }
  if (e.key === "j" || e.key === "k") {
    stepRow(e.key === "j" ? 1 : -1);
    e.preventDefault();
    return;
  }
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    var at = document.activeElement;
    if (e.shiftKey || (at && at !== document.body && !(at.closest && at.closest("#grid")))) return;
    stepRow(e.key === "ArrowRight" ? 1 : -1);
    e.preventDefault();
    return;
  }
  if (e.key === "w") {
    /** @type {HTMLElement} */
    var onPane = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".tile") : null;
    var wrapName = onPane ? onPane.dataset.repo : openName();
    if (!wrapName) return;
    openWrapup(wrapName);
    e.preventDefault();
    return;
  }
  if (e.key === "r" || e.key === "m") {
    var host = /** @type {HTMLElement} */ (document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".tile") : null);
    var name = host ? host.dataset.repo : openName();
    if (!name) return;
    if (e.key === "r") doRefresh(name, host ? host.querySelector('[data-tool="refresh"]') : null);
    else openModelCard(name, host ? host.querySelector('[data-tool="model"]') : null);
    e.preventDefault();
    return;
  }
  if (e.key === "h") {
    var onTile = /** @type {HTMLElement} */ (document.activeElement && document.activeElement.closest && document.activeElement.closest(".tile"));
    if (onTile && onTile.dataset.repo) { setHidden(onTile.dataset.repo, true); return; }
  }
  if (e.key === "n") { section("drawer"); return; }
  if (e.key === "b") { section("board"); return; }
  if (e.key === "a") {
    var open = openName();
    var entry = open ? tiles.get(open) : null;
    if (entry && entry.el.dataset.approval &&
        !/** @type {HTMLElement} */ (entry.el.querySelector(".approval")).hidden) {
      /** @type {HTMLElement} */ (entry.el.querySelector(".approve")).click();
    }
  }
});

var setLink = /** @type {HTMLAnchorElement} */ (document.getElementById("setbtn"));
if (setLink) setLink.href = pageUrl("/settings");
var mapLink = /** @type {HTMLAnchorElement} */ (document.getElementById("mapbtn"));
if (mapLink) mapLink.href = pageUrl("/map");

refresh().then(function () {
  LOAD.settled = document.body.dataset.skin || "";
  connect();
  loadNotifications();
  loadDesk().then(function () { if (BOOT_HASH && location.hash === BOOT_HASH) followHash(); });
});

setInterval(loadDesk, 15000);

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
    osc.onended = function () { try { ctx.close(); } catch (e) {} };
  } catch (e) {}
}

var unread = new Map();
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
    }).catch(function () {});
}

var SECTIONS = ["board", "unsorted", "drawer", "found", "inspector"];
var lastSection = "board";

function syncSide() {
  var open = SECTIONS.filter(function (id) {
    var n = document.getElementById(id);
    return n && !n.hidden;
  });
  hide(document.getElementById("side"), open.length === 0);
  attr(document.getElementById("sidetoggle"), "aria-pressed", String(open.length > 0));
  document.querySelectorAll(".side-tabs .segment").forEach(/** @type {(b: HTMLElement) => void} */ (function (b) {
    var on = open.indexOf(b.dataset.section) >= 0;
    toggle(b, "active", on);
    attr(b, "aria-selected", String(on));
  }));
  return open[0] || "";
}

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
  try { localStorage.setItem("fleet.chime", chimeOn ? "1" : "0"); } catch (e) {}
  if (chimeOn) chime();
});

try { chimeOn = localStorage.getItem("fleet.chime") === "1"; } catch (e) { chimeOn = false; }
attr(document.getElementById("chime"), "aria-pressed", String(chimeOn));
text(document.getElementById("chime"), chimeOn ? "chime on" : "chime off");

var board = [];

function statusClass(row) {
  return "st " + (row.category || "");
}

function ticketRow(row) {
  var li = document.createElement("li");
  li.draggable = true;
  tabbable(li, 0);
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

var SCOPE_MAX_HASH = 64 * 1024 * 1024;
var SCOPE_MAX_FILES = 200;

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

function filesFromDrop(dt) {
  var items = Array.prototype.slice.call(dt.items || []);
  var entries = items.map(function (i) { return i.webkitGetAsEntry && i.webkitGetAsEntry(); })
                     .filter(function (e) { return e && e.isDirectory; });
  if (!entries.length) return Promise.resolve(Array.prototype.slice.call(dt.files || []));

  var out = [];
  var walk = function (dir) {
    return new Promise(/** @type {(done: (value?: any) => void) => void} */ (function (done) {
      dir.createReader().readEntries(function (children) {
        Promise.all(children.map(function (child) {
          if (out.length >= SCOPE_MAX_FILES) return Promise.resolve();
          if (child.isDirectory) return walk(child);
          return /** @type {Promise<void>} */ (
            new Promise(function (got) { child.file(function (f) { out.push(f); got(); }, got); }));
        })).then(done);
      }, function () { done(); });
    }));
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
  var brief = /** @type {HTMLTextAreaElement} */ (card.querySelector(".brief"));
  var home = dispatchHome(repo);
  if (card.parentNode !== home) home.appendChild(card);
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
  dispatchModelDrawn();

  fetch(q("/api/preflight", { key: key, repo: repo })).then(function (r) {
    return r.json();
  }).then(function (card_data) {
    if (card.dataset.key !== key) return;
    var verdict = (card_data && card_data.verdict) || "unknown";
    (card_data.rows || []).forEach(function (r) { rows.appendChild(dispatchRow(r)); });
    paintVerdict(card, verdict);
    var thin = (card_data.rows || []).filter(function (r) { return r.verdict === "thin"; });
    var modelOnly = verdict === "thin" && thin.length === 1 && thin[0].row === "model";
    text(card.querySelector(".dispatch-note"),
         modelOnly ? thin[0].why
         : verdict === "thin" ? "thin — a brief is what makes this worth a turn"
         : verdict === "unknown" ? "some rows could not be read; Start still works"
         : "");
    if (modelOnly) {
      dispatchModelDrawn().then(function () {
        var on = card.dataset.key === key && dispatchPicker.querySelector('[aria-pressed="true"]');
        if (on) /** @type {HTMLElement} */ (on).focus();
      });
    } else if (verdict === "thin" || verdict === "blocked") brief.focus();
  }).catch(function () {
    if (card.dataset.key !== key) return;
    text(card.querySelector(".verdict"), "unknown");
    text(card.querySelector(".dispatch-note"), "the pre-flight could not be read; Start still works");
  });
}

function dispatchRow(r) {
  var li = document.createElement("li");
  setClass(li, "dispatch-row r-" + (r.verdict || "ready"));
  setData(li, "row", r.row);
  setData(li, "verdict", r.verdict || "ready");
  var n = document.createElement("span"); setClass(n, "dr-name"); text(n, r.row);
  var v = document.createElement("span"); setClass(v, "dr-value"); text(v, r.value);
  li.appendChild(n); li.appendChild(v);
  if (r.why) { var w = document.createElement("span"); setClass(w, "dr-why"); text(w, r.why); li.appendChild(w); }
  return li;
}

function paintVerdict(card, verdict) {
  var chip = card.querySelector(".verdict");
  text(chip, verdict);
  setClass(chip, "verdict v-" + verdict);
  text(card.querySelector(".dispatch-go"), verdict === "ready" ? "Start" : "Start anyway");
}

function rereadDispatchModelRow(repo) {
  var card = document.getElementById("dispatch");
  var key = card.dataset.key || "";
  if (!key || dispatchRepo() !== repo) return Promise.resolve();
  return fetch(q("/api/preflight", { key: key, repo: repo, row: "model" })).then(function (r) {
    return r.json();
  }).then(function (data) {
    var was = card.querySelector('.dispatch-row[data-row="model"]');
    if (!data || !data.row || !was || card.dataset.key !== key || dispatchRepo() !== repo) return;
    was.replaceWith(dispatchRow(data.row));
    var kinds = Array.prototype.map.call(card.querySelectorAll(".dispatch-row"), function (li) {
      return li.dataset.verdict;
    });
    paintVerdict(card, ["blocked", "unknown", "thin"].filter(function (k) {
      return kinds.indexOf(k) >= 0;
    })[0] || "ready");
  }).catch(function () {});
}

var dispatchPicker = null;
var dispatchPickerOpts = /** @type {ModelPickerOptions} */ (null);

function dispatchRepo() {
  var card = document.getElementById("dispatch");
  return card && !card.hidden ? card.dataset.repo || "" : "";
}

function drawDispatchModel() {
  var repo = dispatchRepo();
  if (!repo || !dispatchPicker || !modelCatalogue) return false;
  var entry = tiles.get(repo);
  var row = (entry && entry.row) || {};
  var state = modelState(row);
  dispatchPickerOpts.emptyLabel = state.emptyLabel;
  dispatchPickerOpts.emptyTitle = state.emptyTitle;
  drawModelPicker(dispatchPicker, { catalogue: modelCatalogue, current: state.current,
                                    inherited: state.inherited, actual: row.actual || "",
                                    quick: [row.fleet_model || "", row.actual || ""] });
  return true;
}

function dispatchModelDrawn() {
  var drawn = drawDispatchModel();
  if (modelCatalogue && !modelCatalogueStale) return Promise.resolve(drawn);
  return loadModelCatalogue().then(drawDispatchModel);
}

function pickDispatchModel(pick) {
  var repo = dispatchRepo();
  if (!repo || !pick) return;
  var note = document.getElementById("dispatch").querySelector(".dispatch-note");
  queueModelWrite(repo, pick, "model set for this and later turns", function (words) {
    if (dispatchRepo() === repo) text(note, words);
  }, null);
}

function closeDispatch() {
  var card = document.getElementById("dispatch");
  if (card) { hide(card, true); setData(card, "key", ""); setData(card, "repo", ""); }
}

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
  dispatchPickerOpts = { variant: "compact", label: "runs on", onPick: pickDispatchModel,
                         onMore: function () { openModelCard(card.dataset.repo || "", card); } };
  dispatchPicker = createModelPicker(dispatchPickerOpts);
  card.querySelector(".dispatch-model").appendChild(dispatchPicker);
  card.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") e.stopPropagation();
  });
  card.querySelector(".dispatch-close").addEventListener("click", function () { closeDispatch(); });
  card.querySelector(".dispatch-go").addEventListener("click", function () {
    dispatch(card.dataset.key || "", card.dataset.repo || "",
             /** @type {HTMLTextAreaElement} */ (card.querySelector(".brief")).value.trim());
  });
  card.querySelector(".brief").addEventListener("keydown", /** @type {(e: KeyboardEvent) => void} */ (function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      /** @type {HTMLElement} */ (card.querySelector(".dispatch-go")).click();
      e.preventDefault();
    }
    else if (e.key === "Escape") { closeDispatch(); e.stopPropagation(); }
  }));
})();

var railDrag = null;

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
      var button = /** @type {HTMLElement} */ (li.querySelector(".rail-open"));
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

document.getElementById("tickets").addEventListener("keydown", /** @type {(e: KeyboardEvent & {target: Element}) => void} */ (function (e) {
  var li = /** @type {HTMLElement} */ (e.target.closest && e.target.closest("li[data-key]"));
  if (!li) return;
  var row = board.filter(function (r) { return r.key === li.dataset.key; })[0];
  if (!row) return;
  if (/^[1-9]$/.test(e.key)) {
    var chips = /** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll("#agentrail .rail-chip:not([hidden])"));
    var chip = chips[Number(e.key) - 1];
    if (chip) { takeTicket(row.key, chip.dataset.repo); e.preventDefault(); e.stopPropagation(); }
  } else if (e.key === "Enter") {
    var s = row.suggested || {};
    var only = s.repo || ((s.candidates || []).length === 1 ? s.candidates[0] : "");
    if (only) { takeTicket(row.key, only); e.preventDefault(); e.stopPropagation(); }
  }
}));

function drawBoard(rows) {
  var list = document.getElementById("tickets");
  var needle = (/** @type {HTMLInputElement} */ (document.getElementById("boardsearch")).value || "")
    .toLowerCase();
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
    var back = /** @type {HTMLElement} */ (list.querySelector('li[data-key="' + had.key + '"]'));
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
    }).catch(function () {});
}

function boardPanel(open) { return section("board", open); }

document.querySelectorAll(".side-tabs .segment").forEach(/** @type {(b: HTMLElement) => void} */ (function (b) {
  b.addEventListener("click", function () { section(b.dataset.section); });
}));
document.getElementById("sidetoggle").addEventListener("click", function () {
  if (syncSide()) closeSide(); else section(lastSection, true);
});
document.getElementById("closeboard").addEventListener("click", function () { boardPanel(false); });
document.getElementById("boardrefresh").addEventListener("click", function () { loadBoard(true); });
document.getElementById("boardsearch").addEventListener("input", function () { drawBoard(board); });

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
    var incoming = data.desk;
    data.desk = desk.desk;
    desk = data;
    acceptDesk(incoming);
    if (registryChanged(data.order)) refresh();
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

var CELLS = ["ticket", "pr", "refresh", "git"];

function drawCells(el, polls, row) {
  var box = el.querySelector(".cells");
  var want = [];
  var spend = (row || {}).spend;
  if (spend && (spend.total || spend.budget)) want.push({ cell: "spend", row: row || {} });
  CELLS.forEach(function (name) {
    var p = polls[name];
    if (!p) return;
    var value = (p.value && p.value.text) || "";
    if (!value && !p.error) return;
    want.push({ cell: name, poll: p, value: value });
  });

  patchList(box, want, function (item) { return item.cell; },
    function (item) {
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

function drawSpendCell(cell, row) {
  var s = row.spend;
  if (!s) return;
  var bits = [s.total + " premium"];
  if (s.budget) bits.push("of " + s.budget);
  if (s.turns) bits.push(s.turns + (s.turns === 1 ? " turn" : " turns"));
  var model = shortModel(chipModel(row).id);
  if (model) bits.push(model);

  setClass(cell, "cell spend");
  text(cell.querySelector(".val"), bits.join(" · "));
  var said = "this session " + s.session + " · today " + s.today +
             (s.sessions > 1 ? " · " + s.sessions + " sessions" : "");
  toggle(cell, "over", false);
  toggle(cell, "warn", false);
  if (s.budget && s.total >= s.budget) {
    toggle(cell, "over", true);
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

var branchesFor = {};
var branchesWanted = "";

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
  attr(read, "title", "every local branch, and which never reached the default");
  read.addEventListener("click", function () { loadBranches(name, true); });
  head.appendChild(read);
  box.appendChild(head);
  if (!answer) return box;
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
  var asked = branchesWanted === name;
  if (asked) branchesWanted = "";
  var fold = inspectorFold(name, "branches-list", answer.warn);
  if (asked) fold.open = true;
  fold.appendChild(mk("summary", "muted", (answer.branches || []).length + " listed" +
                                           ((answer.commits || []).length ? " · the last commits" : "")));
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
    var meta = mk("span", "bmeta", bits.filter(Boolean).join("  ·  "));
    attr(meta, "title", meta.textContent);
    li.appendChild(meta);
    list.appendChild(li);
  });
  fold.appendChild(list);
  if (answer.more) fold.appendChild(mk("p", "muted branches-note", "and more: the count stops at twenty unmerged branches, which is the finding"));
  if ((answer.commits || []).length) {
    fold.appendChild(mk("div", "muted", "the last " + answer.commits.length + " commits on " + answer.current));
    fold.appendChild(mk("pre", "commits", answer.commits.join("\n")));
  }
  box.appendChild(fold);
  return box;
}

function spendPane(name) {
  var entry = tiles.get(name);
  var row = (entry && entry.row) || {};
  var s = row.spend;
  if (!s || (!s.total && !s.budget)) return null;

  var line = "spend " + s.total + " all time · " + s.today + " today · " + s.session + " this session";
  if (s.budget) line += " · of " + s.budget;
  var sum = mk("p", "spendline" + (s.budget && s.total >= s.budget ? " warn" : ""), line);
  attr(sum, "title", "premium requests · " +
    s.turns + (s.turns === 1 ? " turn" : " turns") +
    (s.rate ? ", a mean of " + s.rate + " a turn — a mean, not a forecast" : "") +
    (s.sessions > 1 ? " · " + s.sessions + " sessions" : "") +
    "\n`ad-fleet spend " + name + "` prints this, and `--rebuild` checks it against every log");
  return sum;
}

function clip(value) {
  try {
    if (navigator.clipboard) return navigator.clipboard.writeText(value);
  } catch (e) {}
  var box = document.createElement("textarea");
  box.value = value;
  document.body.appendChild(box);
  box.select();
  try { document.execCommand("copy"); } catch (e) {}
  document.body.removeChild(box);
}

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
        .then(drawHits).catch(function () {});
    }, 250);
  };
})();

function foundPanel(open) { return section("found", !!open); }

document.getElementById("find").addEventListener("input", findSoon);
document.getElementById("closefound").addEventListener("click", function () { foundPanel(false); });

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

/**
 * @param {string} name
 * @returns {Promise<void>}
 */
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

var inspectorDrawn = "";
var inspectorFolds = {};

function inspectorSees(p) {
  var latest = ((p.verify || {}).latest) || {};
  return [p.links, p.path, p.facts, p.jira_project, p.indexed, p.last_indexed, p.missing_keys,
          p.friction_open, p.friction, p.friction_earlier,
          latest.name ? [latest.tool, latest.name, latest.excerpt,
                         latest.age_s != null ? age(Math.round(latest.age_s)) : null] : null];
}

function inspectorFold(name, cls, openByDefault) {
  var folds = inspectorFolds[name] || (inspectorFolds[name] = {});
  var d = mk("details", cls);
  d.open = folds[cls] !== undefined ? folds[cls] : !!openByDefault;
  d.addEventListener("toggle", function () { folds[cls] = d.open; });
  return d;
}

function drawInspector(name) {
  var el = document.getElementById("inspector");
  if (!el) return;
  if (wrap && wrap.repo && name !== wrap.repo) closeWrapup();
  var body0 = document.getElementById("inspectordetails");
  if (!name || !tiles.has(name)) {
    inspectorDrawn = "";
    text(document.getElementById("inspectorrepo"), "");
    while (body0.firstChild) body0.removeChild(body0.firstChild);
    return;
  }
  var entry = tiles.get(name);
  var drawn = JSON.stringify([name, inspectorSees(desk.projects[name] || {}), ((entry && entry.row) || {}).spend || null,
                              branchesFor[name] || null, (desk.offers || {})[name] || null]);
  if (drawn === inspectorDrawn && body0.firstChild) return;
  inspectorDrawn = drawn;
  text(document.getElementById("inspectorrepo"), name);
  var body = document.getElementById("inspectordetails");
  while (body.firstChild) body.removeChild(body.firstChild);

  var p = desk.projects[name] || {};

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
    var wrapBtn = mk("button", "wrapup", "wrap up");
    attr(wrapBtn, "type", "button");
    attr(wrapBtn, "title", "preview what would be written to Jira, Bitbucket and Confluence (w)");
    wrapBtn.addEventListener("click", function () { openWrapup(name); });
    rail.appendChild(wrapBtn);
    body.appendChild(rail);
  }

  var frictionOpen = p.friction_open || p.friction || [];
  var frictionEarlier = p.friction_earlier || [];
  var dismissFriction = function (payload) {
    post("friction", payload).then(function (out) {
      if (out && out.project) desk.projects[name] = out.project;
      drawInspector(name);
    });
  };
  var frictionRow = function (f) {
    var li = document.createElement("div");
    setClass(li, "frictionrow" + (f.blocking === false ? " quiet" : ""));
    var what = document.createElement("span");
    text(what, [f.date, f.type, f.title].filter(Boolean).join("  ·  ") + (f.unblock ? "\n" + f.unblock : ""));
    li.appendChild(what);
    if (f.asked) {
      var still = document.createElement("a");
      setClass(still, "frictionasked");
      still.href = "#";
      text(still, "still asked — answer it on the pane");
      still.addEventListener("click", function (e) { e.preventDefault(); openPane(name); });
      li.appendChild(still);
    }
    if (f.name) {
      var drop = document.createElement("button");
      text(drop, "dismiss");
      attr(drop, "title", "hide this row on the panel; the file is kept and no question is answered");
      drop.addEventListener("click", function () { dismissFriction({ repo: name, dismiss: [f.name] }); });
      li.appendChild(drop);
    }
    return li;
  };
  frictionOpen.forEach(function (f) { body.appendChild(frictionRow(f)); });

  var spent = spendPane(name);
  if (spent) body.appendChild(spent);

  body.appendChild(branchesPane(name));

  var more = inspectorFold(name, "more", false);
  var summaryBits = ["facts"];
  var moreSummary = mk("summary", "", "");
  more.appendChild(moreSummary);

  var facts = document.createElement("div");
  setClass(facts, "facts");
  var pairs = [
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
  more.appendChild(facts);

  var missing = p.missing_keys || [];
  if (missing.length) {
    var gapLine = "add to AGENTS.md for the rest of the rail: " + missing.join(", ");
    var gap = mk("p", "muted missing", gapLine);
    attr(gap, "title", gapLine);
    more.appendChild(gap);
  }

  if (frictionEarlier.length) {
    summaryBits.push(frictionEarlier.length + " earlier friction");
    var fold = inspectorFold(name, "friction-earlier", false);
    var summary = document.createElement("summary");
    text(summary, "earlier friction (" + frictionEarlier.length + ")");
    fold.appendChild(summary);
    var all = document.createElement("button");
    text(all, "dismiss all");
    attr(all, "title", "hide every earlier row; the files are kept");
    all.addEventListener("click", function () { dismissFriction({ repo: name, earlier: true }); });
    fold.appendChild(all);
    frictionEarlier.forEach(function (f) { fold.appendChild(frictionRow(f)); });
    more.appendChild(fold);
  }

  var latest = ((p.verify || {}).latest) || {};
  if (latest.name) {
    summaryBits.push("verify");
    var h = document.createElement("div");
    setClass(h, "muted");
    text(h, "verify · " + (latest.tool || "") + " · " + latest.name +
            (latest.age_s != null ? " · " + age(Math.round(latest.age_s)) : ""));
    var pre = document.createElement("pre");
    setClass(pre, "verifybody");
    text(pre, latest.excerpt || "");
    more.appendChild(h);
    more.appendChild(pre);
  }

  var offers = (desk.offers || {})[name] || [];
  if (offers.length) {
    summaryBits.push(offers.length + " offered");
    var head = document.createElement("div");
    setClass(head, "muted");
    text(head, "Downloads is offering " + offers.length + " file" + (offers.length === 1 ? "" : "s"));
    var list = document.createElement("ol");
    setClass(list, "tray");
    offers.forEach(function (row) { list.appendChild(offerRow(row, name)); });
    more.appendChild(head);
    more.appendChild(list);
  }
  text(moreSummary, "more — " + summaryBits.join(" · "));
  body.appendChild(more);
}

document.getElementById("closeinspector").addEventListener("click", function () {
  section("inspector", false);
});

var WRAP_STEPS = "push · pr · page · comment · transition";
var WRAP_GLYPH = { written: "✓", failed: "✗", changed: "↻", skipped: "–" };
var wrap = { repo: "", mode: "project", job: "", state: "", rows: [], results: {}, ticks: {}, comment: null,
             editing: false, extra: {} };

var wrapGo = new WeakMap();

function wrapSheet() { return /** @type {HTMLElement} */ (document.querySelector("#inspector .wrapsheet")); }

function wrapOpen() { var s = wrapSheet(); return !!s && !s.hidden; }

function wrapSlot(row) { return String(row.id || row.step || "").split(":")[0]; }

function wrapDone(result) {
  var d = String((result && result.done) || "");
  return d.indexOf("skipped") === 0 ? "skipped" : d;
}

function wrapCell(el, row, ticked, result, locked) {
  var box = /** @type {HTMLInputElement} */ (el.querySelector(".wrap-tick"));
  if (box.checked !== !!ticked) box.checked = !!ticked;
  disable(box, !row.ok || !!locked);
  setData(el, "id", row.id);
  setData(el, "step", row.step);
  setData(el, "code", row.code || "");
  var done = wrapDone(result);
  setData(el, "done", done);
  text(el.querySelector(".wrap-glyph"), done ? (WRAP_GLYPH[done] || "·") : "");
  text(el.querySelector(".wrap-step"), row.step);
  text(el.querySelector(".wrap-sum"), row.summary || "");
  var hint = "";
  if (done === "written") hint = "written";
  else if (done === "failed") hint = "failed — " + [result.error, result.hint].filter(Boolean).join(" — ");
  else if (done === "changed") hint = "changed — nothing was written; " + (result.hint || "preview again");
  else if (done === "skipped") hint = String(result.done) + (result.hint ? " — " + result.hint : "");
  else if (!row.ok) hint = (row.code ? row.code + " — " : "") + (row.hint || "");
  else hint = [row.needs && row.needs.length && ticked ? "after " + row.needs.join(" · ") : "", row.hint]
    .filter(Boolean).join(" — ");
  text(el.querySelector(".wrap-hint"), hint);
  attr(el.querySelector(".wrap-hint"), "title", hint || null);
}

function wrapTicked(row) {
  var slot = wrapSlot(row);
  return row.ok && (wrap.ticks[slot] !== undefined ? wrap.ticks[slot] : !!row.ticked);
}

function wrapTickedIds() {
  return wrap.rows.filter(wrapTicked).map(function (r) { return r.id; });
}

function wrapActs(el, row, result) {
  var act = el.querySelector(".wrap-act");
  var want = [];
  var done = wrapDone(result);
  var locked = wrap.state === "reading" || wrap.state === "writing";
  if (done === "written" && result.url) {
    want.push({ key: "url", link: result.url, label: "open it" });
  } else if (done === "failed" || done === "changed") {
    want.push({ key: "again", label: "preview again", go: function () { previewWrap({}); } });
  } else if (!done) {
    var p = row.payload || {};
    if (row.step === "transition" && (row.available || []).length) {
      row.available.forEach(function (name) {
        want.push({ key: "to:" + name, label: name, go: function () { previewWrap({ to: name }); } });
      });
    }
    if (row.step === "page" && (row.code === "page_edited" || row.code === "page_not_ours" || p.edited)) {
      var live = row.live || p.version;
      if (p.url) want.push({ key: "open", link: p.url, label: "open it" });
      if (live) want.push({ key: "replace", label: "replace v" + live,
                            go: function () { previewWrap({ overwrite: { page: live } }); } });
    }
    if (row.step === "pr" && p.description === "kept" && p.live_hash) {
      want.push({ key: "replace", label: "replace the description",
                  go: function () { previewWrap({ overwrite: { pr: p.live_hash } }); } });
    }
    if (row.step === "comment" && row.ok) {
      want.push({ key: "edit", label: wrap.editing ? "done" : "edit", go: function () {
        wrap.editing = !wrap.editing;
        var box = /** @type {HTMLTextAreaElement} */ (wrapSheet().querySelector(".wrap-comment"));
        if (wrap.editing && wrap.comment == null) box.value = String(p.body || "");
        hide(box, !wrap.editing);
        if (wrap.editing) box.focus();
        drawWrap();
      } });
    }
  }
  patchList(act, want, function (w) { return w.key; }, function (w) {
    var n = w.link ? mk("a", "wrap-link") : mk("button", "wrap-btn");
    if (w.link) { n.target = "_blank"; n.rel = "noopener noreferrer"; }
    else { attr(n, "type", "button"); n.addEventListener("click", function () { var go = wrapGo.get(n); if (go) go(); }); }
    return n;
  }, function (n, w) {
    text(n, w.label);
    if (w.link) { if (n.getAttribute("href") !== w.link) n.setAttribute("href", w.link); }
    else { wrapGo.set(n, w.go); disable(n, locked); }
  });
}

function drawWrap() {
  var sheet = wrapSheet();
  if (!sheet) return;
  sheet.querySelectorAll(".wrap-modes [data-mode]").forEach(function (b) {
    var on = b.getAttribute("data-mode") === wrap.mode;
    toggle(b, "active", on);
    attr(b, "aria-pressed", String(on));
    disable(b, wrap.state === "reading" || wrap.state === "writing");
  });
  var status = wrap.status || "";
  if (!status) {
    if (wrap.state === "reading") status = "reading " + WRAP_STEPS + "…";
    else if (wrap.state === "writing") status = "writing…";
  }
  text(sheet.querySelector(".wrap-status"), status);
  var locked = wrap.state !== "planned";
  patchList(sheet.querySelector(".wrap-rows"), wrap.rows, wrapSlot, function () {
    var li = /** @type {HTMLElement} */ (sheet.querySelector(".wrap-pattern").cloneNode(true));
    li.classList.remove("wrap-pattern");
    li.hidden = false;
    var box = /** @type {HTMLInputElement} */ (li.querySelector(".wrap-tick"));
    box.addEventListener("change", function () {
      wrap.ticks[li.dataset.rowkey] = box.checked;
      drawWrap();
    });
    return li;
  }, function (li, row) {
    var result = wrap.results[wrapSlot(row)];
    wrapCell(li, row, wrapTicked(row), result, locked);
    if (row.step === "comment" && wrap.comment != null && !result) {
      text(li.querySelector(".wrap-hint"), "edited — checked again before it is sent");
    }
    wrapActs(li, row, result);
  });
  var n = wrapTickedIds().length;
  var go = /** @type {HTMLButtonElement} */ (sheet.querySelector(".wrap-go"));
  text(go, "write " + n);
  attr(go, "title", n ? "write exactly the " + n + " ticked, previewed step" + (n === 1 ? "" : "s") +
                        " — pressing is the approval for each (WRAP-D4)" : null);
  disable(go, locked || !n || wrap.editing);
}

function previewWrap(extra) {
  if (!wrap.repo) return Promise.resolve(null);
  wrap.extra = Object.assign({}, wrap.extra, extra || {});
  wrap.state = "reading";
  wrap.status = "";
  wrap.results = {};
  var body = { repo: wrap.repo, mode: wrap.mode, dry_run: true };
  if (wrap.extra.to) body.to = wrap.extra.to;
  if (wrap.extra.overwrite) body.overwrite = wrap.extra.overwrite;
  if (wrap.comment != null) body.comment = wrap.comment;
  drawWrap();
  var repo = wrap.repo;
  return post("wrapup", body).then(function (r) {
    if (repo !== wrap.repo) return r;
    if (!r || !r.ok) {
      wrap.state = "";
      wrap.status = (r && r.error ? r.error + (r.hint ? " — " + r.hint : "") : "the preview was refused");
      drawWrap();
      return r;
    }
    wrap.job = r.job;
    return loadWrap();
  });
}

function writeWrap() {
  var steps = wrapTickedIds();
  if (!wrap.job || wrap.state !== "planned" || !steps.length) return Promise.resolve(null);
  var body = { repo: wrap.repo, job: wrap.job, steps: steps };
  if (wrap.comment != null) body.comment = wrap.comment;
  wrap.state = "writing";
  drawWrap();
  return post("wrapup", body).then(function (r) {
    if (!r || !r.ok) {
      wrap.state = "planned";
      wrap.status = (r && r.error ? r.error + (r.hint ? " — " + r.hint : "") : "the write was refused");
      drawWrap();
      return r;
    }
    return loadWrap();
  });
}

function loadWrap() {
  var repo = wrap.repo;
  if (!repo) return Promise.resolve(null);
  return fetch(q("/api/wrapup", { repo: repo })).then(function (r) { return r.json(); }).then(function (job) {
    if (repo !== wrap.repo || !job || !job.ok) return job;
    acceptWrap(job);
    return job;
  }).catch(function () { return null; });
}

function acceptWrap(job) {
  var mine = !wrap.job || job.job === wrap.job;
  if (!mine) return;
  var before = wrap.state;
  wrap.state = job.state || "";
  var plan = job.plan || {};
  if (plan.rows) wrap.rows = plan.rows;
  wrap.results = {};
  (job.results || []).forEach(function (r) { wrap.results[wrapSlot(r)] = r; });
  wrap.status = "";
  if (job.error) {
    wrap.status = job.error + (job.hint ? " — " + job.hint : "");
  } else if (wrap.state === "planned") {
    var notes = (plan.notes || []).join(" · ");
    wrap.status = (wrap.mode === "day" ? "end of day" : "end of project") + " · " + wrap.rows.length +
                  " step" + (wrap.rows.length === 1 ? "" : "s") + " previewed, nothing written yet" +
                  (notes ? " · " + notes : "");
  } else if (wrap.state === "done") {
    var counts = { written: 0, failed: 0, changed: 0, skipped: 0 };
    (job.results || []).forEach(function (r) { var d = wrapDone(r); if (d in counts) counts[d]++; });
    var line = Object.keys(counts).filter(function (k) { return counts[k]; })
      .map(function (k) { return counts[k] + " " + k; }).join(", ") || "nothing written";
    wrap.status = line + " · " + String(job.at || "").slice(11, 16);
    if (before === "writing") say(wrap.repo + " wrap-up: " + line);
  }
  drawWrap();
}

function openWrapup(name) {
  if (!name) return;
  var same = wrap.repo === name && wrapOpen();
  choose(name);
  section("inspector", true);
  hide(wrapSheet(), false);
  if (same) return;
  wrap = { repo: name, mode: "project", job: "", state: "", rows: [], results: {}, ticks: {}, comment: null,
           editing: false, extra: {} };
  var box = /** @type {HTMLTextAreaElement} */ (wrapSheet().querySelector(".wrap-comment"));
  box.value = "";
  hide(box, true);
  drawWrap();
  fetch(q("/api/wrapup", { repo: name })).then(function (r) { return r.json(); }).catch(function () { return {}; })
    .then(function (job) {
      if (wrap.repo !== name) return;
      if (job && (job.state === "writing" || job.state === "done") && (job.results || job.state === "writing")) {
        wrap.job = job.job;
        wrap.mode = job.mode || wrap.mode;
        acceptWrap(job);
        if (wrap.state === "done") wrap.status = "last wrap-up, " + String(job.at || "").replace("T", " ") +
                                                 ": " + wrap.status.split(" · ")[0] + " · preview again for a new one";
        drawWrap();
        return;
      }
      previewWrap({});
    });
}

function closeWrapup() {
  if (!wrapOpen()) return false;
  hide(wrapSheet(), true);
  wrap.repo = "";
  return true;
}

function bindWrapSheet() {
  var sheet = wrapSheet();
  if (!sheet) return;
  sheet.querySelectorAll(".wrap-modes [data-mode]").forEach(function (b) {
    b.addEventListener("click", function () {
      var mode = b.getAttribute("data-mode") || "project";
      if (mode === wrap.mode && wrap.state === "planned") return;
      wrap.mode = mode;
      wrap.ticks = {};
      wrap.extra = {};
      previewWrap({});
    });
  });
  var box = /** @type {HTMLTextAreaElement} */ (sheet.querySelector(".wrap-comment"));
  box.addEventListener("change", function () {
    wrap.comment = box.value;
    wrap.editing = false;
    hide(box, true);
    previewWrap({});
  });
  sheet.querySelector(".wrap-go").addEventListener("click", function () { writeWrap(); });
  sheet.querySelector(".wrap-cancel").addEventListener("click", function () { closeWrapup(); });
}
bindWrapSheet();

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

var arrangeWrites = 0;
var arrangeChain = /** @type {Promise<DeskAnswer | void>} */ (Promise.resolve());

/**
 * @param {Arrangement} patch
 * @param {() => (() => void) | void} apply
 * @param {string} [what]
 * @returns {Promise<DeskAnswer | void>}
 */
function arrangeNow(patch, apply, what) {
  var mark = gesture("arrange:" + (what || "change"));
  var undo = apply();
  transitionMove(function () { place(); });
  settle(mark);
  arrangeWrites += 1;
  arrangeChain = arrangeChain.then(function () {
    return post("arrange", patch).then(function (r) {
      if (r && r.ok) {
        if (arrangeWrites === 1) { mergeDesk(r); place(); }
        return r;
      }
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

/**
 * @param {string} name
 * @param {boolean} hide
 */
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

function reorderDomTiles() {
  var grid = document.getElementById("grid");
  if (!grid) return;
  var order = getEffectiveOrder();
  var curArr = getArrangement();
  var pinned = curArr.pinned || [];
  var shown = visibleOrder().filter(function (n) { return !groupedAway(n); });

  if (dragging) return;

  var inDom = Array.prototype.map.call(grid.children, function (el) { return el.dataset.repo; });
  var needsMove = inDom.join("\u0000") !== order.filter(function (n) { return tiles.has(n); }).join("\u0000");
  var active = /** @type {HTMLElement} */ (document.activeElement);
  var refocus = needsMove && active && active.closest && active.closest(".tile") ? active : null;

  var first = (needsMove && !arrivedSinceLastPlace && !reduceMotion() && !inViewTransition)
    ? measureTiles() : null;
  arrivedSinceLastPlace = false;

  order.forEach(function (name, index) {
    var entry = tiles.get(name);
    if (entry && entry.el) {
      if (needsMove) grid.appendChild(entry.el);
      toggle(entry.el, "is-hidden", isHidden(name));
      var at = shown.indexOf(name);
      text(entry.el.querySelector(".n"), at < 0 ? "" : String(at + 1));
      text(entry.el.querySelector(".pr-n"), at < 0 ? "" : String(at + 1));
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

function reduceMotion() {
  return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function measureTiles() {
  var seen = new Map();
  tiles.forEach(function (entry, name) {
    var box = entry.el.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) seen.set(name, box);
  });
  return seen;
}

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
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      moved.forEach(function (el) {
        toggle(el, "flip", true);
        el.style.transform = "";
      });
    });
  });
}

var DRAG_SLOP = 4;

var dragging = null;

function swallowNextClick() {
  var swallow = function (ev) {
    ev.stopPropagation();
    ev.preventDefault();
    document.removeEventListener("click", swallow, true);
  };
  document.addEventListener("click", swallow, true);
  setTimeout(function () { document.removeEventListener("click", swallow, true); }, 0);
}

function bindDragToReorder(handle, host, name) {
  handle.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    var ctrl = e.target.closest("button, input, select, textarea, a");
    if (ctrl && ctrl !== handle) return;
    var siblings = Array.prototype.filter.call(host.parentNode.children, function (n) {
      return n !== host && n.dataset && n.dataset.repo && !n.hidden;
    });
    if (!siblings.length) return;

    var from = { x: e.clientX, y: e.clientY };
    var started = false;
    var target = null;
    var down = getComputedStyle(host.parentNode).flexDirection === "column";

    var lift = function () {
      started = true;
      dragging = name;
      try {
        var sel = window.getSelection();
        if (sel && !sel.isCollapsed) sel.removeAllRanges();
      } catch (err) {}
      toggle(host, "is-dragging", true);
      try { handle.setPointerCapture(e.pointerId); } catch (err) {}
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
      try { handle.releasePointerCapture(e.pointerId); } catch (err) {}
    };

    var onMove = function (ev) {
      var dx = ev.clientX - from.x;
      var dy = ev.clientY - from.y;
      if (!started && Math.abs(dx) + Math.abs(dy) < DRAG_SLOP) return;
      if (!started) lift();
      style(host, "transform", "translate(" + dx + "px, " + dy + "px)");

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
      swallowNextClick();
      if (landed) dropTileBefore(name, landed.el.dataset.repo, landed.before);
    };

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

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onCancel);
    document.addEventListener("keydown", onKey, true);
  });
}

function holdOpen() {
  if (openTile) return;
  var one = openName();
  if (!one) return;
  openTile = one;
  saveWindow({ open: one });
}

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

var inViewTransition = false;

function tileTransitionName(name) {
  return "tile-" + String(name).replace(/[^A-Za-z0-9_-]/g, "-");
}

function nameTiles(on) {
  tiles.forEach(function (entry, name) {
    style(entry.el, "view-transition-name", on ? tileTransitionName(name) : "");
  });
}

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
      try {
        fn();
      } catch (bad) {
        if (typeof reportError === "function") reportError(bad);
        else setTimeout(function () { throw bad; });
      }
    });
  } catch (err) {
    done();
    fn();
    return;
  }
  if (running.updateCallbackDone) running.updateCallbackDone.catch(function () {});
  if (running.ready) running.ready.catch(function () {});
  running.finished.then(done, done);
}

function moveTile(repo, dir) {
  var arr = getArrangement();
  var pinned = (arr.pinned || []).filter(function (n) { return tiles.has(n); });
  var inPinnedBlock = pinned.indexOf(repo) >= 0;
  var block = inPinnedBlock
    ? pinned
    : getEffectiveOrder().filter(function (n) { return pinned.indexOf(n) < 0; });

  var idx = block.indexOf(repo);
  if (idx < 0) return;
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

function shortModel(name) {
  var whole = String(name || "").trim().replace(/-\d{8}$/, "");
  if (!whole) return "auto";
  var parts = whole.replace(/^(claude|gpt|gemini)-/, "").split("-");
  var version = /^k?\d+(\.\d+)*$/;
  var at = -1;
  for (var i = 0; i < parts.length && at < 0; i++) if (version.test(parts[i])) at = i;
  var words = parts.filter(function (p) { return p && !version.test(p); });
  if (at < 0 || !words.length) return whole.replace(/^claude-/, "");
  if (at === 0) return [parts[1]].concat(parts.slice(0, 1), parts.slice(2)).join(" ");
  return parts.join(" ");
}

function chipModel(row) {
  row = row || {};
  var model = String(row.model || ""), actual = String(row.actual || "");
  var turn = String(row.turn_model || "");
  if (row.launched === null || row.launched === undefined) {
    return { id: model || actual, next: false, pinned: false };
  }
  var launched = String(row.launched);
  if (model !== launched) return { id: model, next: true, pinned: false };
  if (turn && launched && turn !== launched) return { id: turn, next: false, pinned: true };
  return { id: turn || model || actual, next: false, pinned: false };
}

function modelTitle(row) {
  row = row || {};
  var chip = chipModel(row);
  if (row.external || (row.run || {}).origin === "adopted") {
    var starts = ((row.fresh || {}).starts) || {};
    return "your chat ran " + (row.actual || "a model this machine was not told") + "; start fresh starts on " +
           (row.model || "whatever the CLI picks") + " (" + (row.model_source || starts.model_source || "cli-auto") +
           ") — press m";
  }
  var why = row.model ? " (" + (row.model_source || "") + ")" : " (no --model flag is passed)";
  if (row.effort) {
    why += " · effort " + row.effort + (row.effort_source && row.effort_source !== row.model_source
                                        ? " (" + row.effort_source + ")" : "");
  }
  if (chip.next) {
    return "from the next turn: " + (row.model || "whatever the CLI picks") + why +
           " · the last turn ran " + (row.launched || "the CLI's own choice") + " — press m";
  }
  if (chip.pinned) {
    return "runs " + chip.id + " · the tenant pinned it: configured " + row.model + why + " — press m";
  }
  return "runs " + (chip.id || "whatever the CLI picks") +
         (row.model ? " · configured " + row.model + why : " · no --model flag is passed") + " — press m";
}

function doRefresh(repo, button) {
  if (!repo) return Promise.resolve();
  if (button) { disable(button, true); attr(button, "aria-busy", "true"); }
  return post("refresh", { repo: repo }).then(function (r) {
    if (r && !r.ok) say(r.error + (r.hint ? " — " + r.hint : ""));
    else {
      if (r && r.row) { patchRow(r.row); place(); }
      refresh();
    }
    return r;
  }).catch(function (e) { say(String(e)); }).then(function (r) {
    if (button) { disable(button, false); button.removeAttribute("aria-busy"); }
    return r;
  });
}

var modelCatalogue = null, modelCatalogueStale = true;
var modelCatalogueAsk = null;

function loadModelCatalogue() {
  if (modelCatalogueAsk) return modelCatalogueStale ? modelCatalogueAsk.then(loadModelCatalogue) : modelCatalogueAsk;
  if (modelCatalogue && !modelCatalogueStale) return Promise.resolve(modelCatalogue);
  modelCatalogueStale = false;
  modelCatalogueAsk = fetch(q("/api/models")).then(function (r) { return r.json(); })
    .then(function (data) {
      if (data && Array.isArray(data.models)) modelCatalogue = data;
      else modelCatalogueStale = true;
    }).catch(function () { modelCatalogueStale = true; })
    .then(function () { modelCatalogueAsk = null; return modelCatalogue; });
  return modelCatalogueAsk;
}

function modelState(row) {
  row = row || {};
  var own = function (source) { return String(source || "").indexOf("fleet.models.") === 0; };
  var fleetModel = String(row.fleet_model || ""), fleetEffort = String(row.fleet_effort || "");
  var model = own(row.model_source) ? String(row.model || "") : "";
  var effort = own(row.effort_source) ? String(row.effort || "") : "";
  return { current: { model: model, effort: effort },
           inherited: { model: fleetModel, effort: fleetEffort, source: String(row.model_source || "") },
           emptyLabel: "inherit · " + (fleetModel ? shortModel(fleetModel) : "CLI default"),
           emptyTitle: (model ? "clear this repository's model: " : "no model of its own: ") +
                       (fleetModel ? "it follows fleet.model, " + fleetModel
                                   : "no --model is passed and the CLI chooses") };
}

function modelWrite(repo, pick) {
  if (pick.toolbar === "both") return { item: { repo: repo, model: "", effort: "" } };
  if (pick.toolbar === "effort") return { item: { repo: repo, effort: pick.effort } };
  return { item: { repo: repo, model: pick.model } };
}

function modelSaidAfter(lead, pick, write) {
  var said = [lead];
  var id = write.item.model;
  var listed = id && modelCatalogue ? modelCatalogue.models.filter(function (m) { return m.id === id; })[0] : null;
  if (listed && listed.offered === false) {
    var ver = modelCatalogue.meta && modelCatalogue.meta.cli_version;
    said.push("not offered by copilot" + (ver ? " " + ver : "") + " — the turn may fail at start");
  }
  return said.join(" · ");
}

function refreshAfterNow() {
  return (pendingRefresh || Promise.resolve()).then(function () { return refresh(); });
}

var modelPicker = null;
var modelPickerOpts = /** @type {ModelPickerOptions} */ (null);
var modelCardOpener = /** @type {HTMLElement} */ (null);
var modelCardAnchor = /** @type {HTMLElement} */ (null);

function modelCardRepo() {
  var card = document.getElementById("modelcard");
  return card && !card.hidden ? card.dataset.repo || "" : "";
}

function writeModelFacts(repo) {
  var entry = tiles.get(repo);
  var row = (entry && entry.row) || {};
  text(document.getElementById("mc-repo"), repo);
  text(document.getElementById("mc-configured"), row.model ? row.model : "the CLI chooses");
  text(document.getElementById("mc-source"), (row.model_source || "cli-auto") +
       (row.effort ? " · effort " + row.effort + " from " + (row.effort_source || "cli-auto") : ""));
  text(document.getElementById("mc-actual"), row.actual || "no turn has run yet");
  text(document.getElementById("mc-actual-why"),
       row.actual && row.model && row.actual !== row.model ? "the tenant pinned it" : "");
}

function drawModelCard() {
  var repo = modelCardRepo();
  if (!repo || !modelPicker || !modelCatalogue) return false;
  var entry = tiles.get(repo);
  var row = (entry && entry.row) || {};
  var state = modelState(row);
  modelPickerOpts.emptyLabel = state.emptyLabel;
  modelPickerOpts.emptyTitle = state.emptyTitle;
  drawModelPicker(modelPicker, { catalogue: modelCatalogue, current: state.current,
                                 inherited: state.inherited, actual: row.actual || "" });
  hide(document.getElementById("mc-inherit"), !state.current.model && !state.current.effort);
  return true;
}

function placeModelCard(anchor) {
  var card = document.getElementById("modelcard");
  if (!anchor || !anchor.getBoundingClientRect) return;
  var box = anchor.getBoundingClientRect();
  if (!box.width && anchor.closest && anchor.closest(".tile")) {
    box = anchor.closest(".tile").getBoundingClientRect();
  }
  var width = card.offsetWidth || 280;
  var height = card.offsetHeight || 240;
  var top = box.bottom + 6;
  if (top + height > window.innerHeight - 8) {
    top = Math.max(8, Math.min(box.top, window.innerHeight - height - 8));
  }
  card.style.top = top + "px";
  card.style.left = Math.max(8, Math.min(window.innerWidth - width - 8, box.left)) + "px";
}

function focusPressedPill() {
  var on = modelPicker && modelPicker.querySelector('[aria-pressed="true"]');
  if (on) /** @type {HTMLElement} */ (on).focus();
}

var modelFieldBad = null;

function typedField(picker) {
  var at = document.activeElement;
  return at && at.tagName === "INPUT" && picker && picker.contains(at) ? /** @type {HTMLElement} */ (at) : null;
}

function sayOnModelField(field, why) {
  if (modelFieldBad && modelFieldBad !== field) {
    toggle(modelFieldBad, "bad", false);
    attr(modelFieldBad, "title", null);
  }
  modelFieldBad = why ? field : null;
  if (field) { toggle(field, "bad", !!why); attr(field, "title", why || null); }
}

function openModelCard(repo, anchor) {
  var card = document.getElementById("modelcard");
  if (!card) return;
  if (!card.contains(document.activeElement)) {
    modelCardOpener = /** @type {HTMLElement} */ (document.activeElement);
  }
  if (modelCardAnchor && modelCardAnchor !== anchor) attr(modelCardAnchor, "aria-expanded", "false");
  modelCardAnchor = anchor && anchor.classList && anchor.classList.contains("modeltoggle") ? anchor : null;
  if (modelCardAnchor) attr(modelCardAnchor, "aria-expanded", "true");
  setData(card, "repo", repo);
  writeModelFacts(repo);
  text(document.getElementById("mc-note"), "takes effect on the agent's next turn");
  sayOnModelField(null, "");
  var all = /** @type {HTMLAnchorElement} */ (document.getElementById("mc-all"));
  all.href = pageUrl("/settings") + "#model-" + encodeURIComponent(repo);

  hide(card, false);
  if (drawModelCard()) { placeModelCard(anchor); focusPressedPill(); }
  if (!modelCatalogue || modelCatalogueStale) {
    loadModelCatalogue().then(function () {
      if (modelCardRepo() !== repo || !drawModelCard()) return;
      placeModelCard(anchor);
      if (!card.contains(document.activeElement)) focusPressedPill();
    });
  }
}

function closeModelCard() {
  var card = document.getElementById("modelcard");
  if (!card || card.hidden) return false;
  var inside = card.contains(document.activeElement);
  hide(card, true);
  setData(card, "repo", "");
  if (modelCardAnchor) attr(modelCardAnchor, "aria-expanded", "false");
  var back = modelCardOpener;
  modelCardOpener = null;
  modelCardAnchor = null;
  if (inside && back && back.isConnected && back.focus) {
    var box = back.getBoundingClientRect();
    if (!box.width && !box.height && back.closest) back = /** @type {HTMLElement} */ (back.closest(".tile")) || back;
    back.focus();
  }
  return true;
}

var modelWrites = Promise.resolve();

function pickModel(pick) {
  var repo = modelCardRepo();
  if (!repo || !pick) return;
  var note = document.getElementById("mc-note");
  queueModelWrite(repo, pick, "saved — reaches the agent on its next turn", function (words) {
    if (modelCardRepo() === repo) text(note, words);
  }, typedField(modelPicker));
}

function queueModelWrite(repo, pick, lead, say, field) {
  modelWrites = modelWrites.then(function () {
    var write = modelWrite(repo, pick);
    return post("settings", { models: [write.item] }).then(function (r) {
      if (!r || !r.ok) {
        var why = (r && r.error) || "not saved";
        say(why + ((r && r.hint) ? " — " + r.hint : ""));
        if (field) sayOnModelField(field, why);
        return;
      }
      sayOnModelField(null, "");
      (r.rows || []).forEach(function (row) { patchRow(row); });
      if (r.rows && r.rows.length) place();
      var id = write.item.model;
      if (id && !(modelCatalogue && modelCatalogue.models.some(function (m) { return m.id === id; }))) {
        modelCatalogueStale = true;
      }
      return Promise.all([loadModelCatalogue(), refreshAfterNow()]).then(function () {
        say(modelSaidAfter(lead, pick, write));
        if (modelCardRepo() === repo) writeModelFacts(repo);
        drawModelCard();
        drawDispatchModel();
        return rereadDispatchModelRow(repo);
      });
    }).catch(function (e) { say(String(e)); });
  });
}

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
  var pinned = (getArrangement().pinned) || [];
  var free = shown.filter(function (name) { return pinned.indexOf(name) < 0; });
  return free[0] || shown[0] || "";
}

/** @param {string} name */
function markTile(name) {
  if (name && location.hash !== "#tile=" + name) history.replaceState(null, "", "#tile=" + name);
}

/**
 * @param {string} name
 * @param {boolean} [skipPost]
 * @param {boolean} [pressed]
 */
function openPane(name, skipPost, pressed) {
  if (!name || !tiles.has(name)) return;
  var was = openName();
  if (was && was !== name) previousOpen = was;
  var next = skipPost || (was === name && !pressed) ? null : swappedWidths(was, name);
  openTile = name;
  markTile(name);
  if (next) {
    myWidths = next;
    dropUndo();
  }
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

/** @typedef {Object<string, number>} Pixels */

/** @typedef {{widths: Widths | null, open: string}} WidthsBefore */

/**
 * @param {*} value
 * @returns {Widths | null}
 */
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

/**
 * @param {string} name
 * @returns {number}
 */
function legacyShare(name) {
  var v = (getArrangement().size || {})[name];
  var cols = v && typeof v === "object" ? v.cols : v;
  return Math.max(1, Math.min(4, Math.round(Number(cols) || 1)));
}

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

/**
 * @param {Widths} weights
 * @returns {string[]}
 */
function wideNames(weights) {
  return visibleOrder().filter(function (name) { return (weights[name] || 0) > 0; });
}

/**
 * @param {Widths} weights
 * @param {string[]} names
 * @returns {Widths}
 */
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

/**
 * @param {Widths} changes
 * @returns {Widths}
 */
function widthsWith(changes) {
  var out = Object.assign({}, myWidths || paneWeights());
  Object.keys(changes).forEach(function (name) { out[name] = changes[name]; });
  return evenShares(out, visibleOrder());
}

/** @returns {number} */
function paneEdge() {
  var wide = document.querySelector('#grid .tile.is-solo:not([data-tier="rail"])');
  if (!wide) return 24;
  var cs = getComputedStyle(wide);
  return (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0) +
         (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
}

/**
 * @param {number} px
 * @param {number} edge
 * @returns {number}
 */
function weightOf(px, edge) {
  return Math.max(1, px - edge);
}

/**
 * @param {Pixels} px
 * @returns {Widths}
 */
function widthsFromPixels(px) {
  var edge = paneEdge();
  var changes = {};
  Object.keys(px).forEach(function (name) {
    changes[name] = px[name] > RAIL_PX + 0.5 ? weightOf(px[name], edge) : 0;
  });
  return widthsWith(changes);
}

/** @returns {Pixels} */
function measurePanes() {
  var out = {};
  Array.prototype.forEach.call(
    document.querySelectorAll("#grid .tile:not(.is-hidden):not(.is-grouped)"),
    function (el) { out[el.dataset.repo] = el.getBoundingClientRect().width; });
  return out;
}

/**
 * @param {string} was
 * @param {string} name
 * @returns {Widths | null}
 */
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

/**
 * @param {WindowWrite} patch
 * @param {WidthsBefore} [before]
 * @returns {Promise<DeskAnswer | null | void>}
 */
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

var UNDO_FOR_MS = 12000;
var undoOffer = /** @type {(WidthsBefore & {what: string, until: number}) | null} */ (null);
var undoTimer = 0;
var keyHome = /** @type {HTMLElement | null} */ (null);

/**
 * @param {Widths | null} next
 * @param {string} what
 * @param {string} [open]
 * @param {string} [how]
 * @returns {Promise<DeskAnswer | null | void>}
 */
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

/**
 * @param {WidthsBefore} before
 * @param {string} what
 */
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

/** @returns {string} */
function keyboardPane() {
  var at = document.activeElement;
  var host = /** @type {HTMLElement} */ (at && at.closest ? at.closest("#grid .tile") : null);
  return host && host.dataset.repo && !isHidden(host.dataset.repo) ? host.dataset.repo : "";
}

/**
 * @param {string} name
 * @returns {boolean}
 */
function needsPerson(name) {
  var entry = tiles.get(name);
  return !!entry && entry.el.classList.contains("needs-human");
}

/**
 * @param {string} which
 * @returns {boolean}
 */
function applyPreset(which) {
  var shown = visibleOrder();
  if (!shown.length || gutterHeld) return false;
  var next = {};
  var open;
  if (which === "one") {
    var one = keyboardPane() || openName();
    shown.forEach(function (name) { next[name] = name === one ? 1 : 0; });
    open = one;
  } else if (which === "all") {
    shown.forEach(function (name) { next[name] = 1; });
  } else if (which === "needs") {
    var red = shown.filter(needsPerson);
    if (!red.length) {
      say("nothing needs you — the widths are as they were", 6);
      return false;
    }
    shown.forEach(function (name) { next[name] = red.indexOf(name) >= 0 ? 1 : 0; });
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

var RAIL_SNAP_PX = 120;
var SNAP_PX = 8;
var GUTTER_STEP_PX = 40;

/**
 * @typedef {Object} GutterHold
 * @property {HTMLElement} left
 * @property {HTMLElement} right
 * @property {number} x
 * @property {number} a0
 * @property {number} total
 * @property {number} a
 * @property {number} painted
 * @property {Pixels} px
 * @property {number} edge
 * @property {number} frame
 * @property {boolean} lifted
 */
var gutterHeld = /** @type {GutterHold | null} */ (null);
var placeWanted = false;

/**
 * @param {HTMLElement} el
 * @returns {boolean}
 */
function onGlass(el) {
  return !!(el && el.dataset && el.dataset.repo && tiles.has(el.dataset.repo) &&
            !el.classList.contains("is-hidden") && !el.classList.contains("is-grouped"));
}

/**
 * @param {HTMLElement} el
 * @returns {HTMLElement | null}
 */
function nextOnGlass(el) {
  var n = el ? /** @type {HTMLElement} */ (el.nextElementSibling) : null;
  while (n && !onGlass(n)) n = /** @type {HTMLElement} */ (n.nextElementSibling);
  return n;
}

/**
 * @param {number} a
 * @param {number} total
 * @returns {number}
 */
function settlePair(a, total) {
  if (total < RAIL_PX + TIER_COMPACT_FROM) return RAIL_PX;
  a = Math.max(RAIL_PX, Math.min(total - RAIL_PX, a));
  if (a < RAIL_SNAP_PX) return RAIL_PX;
  if (total - a < RAIL_SNAP_PX) return total - RAIL_PX;
  if (total < 2 * TIER_COMPACT_FROM) return a < total / 2 ? RAIL_PX : total - RAIL_PX;
  return Math.max(TIER_COMPACT_FROM, Math.min(total - TIER_COMPACT_FROM, a));
}

/**
 * @param {number} a
 * @param {number} total
 * @returns {number}
 */
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

/**
 * @param {number} a
 * @param {number} total
 * @param {number} dir
 * @returns {number}
 */
function stepPair(a, total, dir) {
  var b = total - a;
  var want = a + dir * GUTTER_STEP_PX;
  if (dir > 0 && a <= RAIL_PX + 0.5) want = TIER_COMPACT_FROM;
  else if (dir < 0 && a <= TIER_COMPACT_FROM + 0.5) want = RAIL_PX;
  else if (dir > 0 && b <= TIER_COMPACT_FROM + 0.5) want = total - RAIL_PX;
  else if (dir < 0 && b <= RAIL_PX + 0.5) want = total - TIER_COMPACT_FROM;
  return settlePair(want, total);
}

/**
 * @param {HTMLElement} el
 * @param {number} px
 * @param {number} edge
 */
function paintHeldWidth(el, px, edge) {
  var wide = px > RAIL_PX + 0.5;
  toggle(el, "is-solo", wide);
  style(el, "--w", wide ? String(Math.round(weightOf(px, edge) * 100) / 100) : "");
}

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

/**
 * @param {HTMLElement} gutter
 * @param {HTMLElement} el
 */
function bindGutter(gutter, el) {
  if (!gutter) return;
  gutter.addEventListener("pointerdown", function (e) {
    if (e.button !== 0 || gutterHeld || dragging) return;
    var right = nextOnGlass(el);
    if (!right || !onGlass(el)) return;
    e.preventDefault();
    e.stopPropagation();
    var px = measurePanes();
    var a0 = px[el.dataset.repo];
    var held = { left: el, right: right, x: e.clientX, a0: a0, total: a0 + px[right.dataset.repo],
                 a: a0, painted: a0, px: px, edge: paneEdge(), frame: 0, lifted: false };
    gutterHeld = held;
    toggle(gutter, "is-held", true);
    toggle(document.body, "is-resizing", true);
    try { gutter.setPointerCapture(e.pointerId); } catch (err) {}

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
      try { gutter.releasePointerCapture(e.pointerId); } catch (err) {}
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
      if (ev && typeof ev.clientX === "number") {
        held.a = snapPair(held.a0 + (ev.clientX - held.x), held.total);
      }
      finish();
      if (Math.abs(held.a - held.a0) < 0.5) { place(); return; }
      swallowNextClick();
      held.px[held.left.dataset.repo] = held.a;
      held.px[held.right.dataset.repo] = held.total - held.a;
      widthsNow(widthsFromPixels(held.px), "drag");
    };
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
  gutter.addEventListener("click", function (e) { e.stopPropagation(); });
  gutter.addEventListener("dblclick", function (e) {
    e.stopPropagation();
    e.preventDefault();
    evenGutter(el);
  });
}

/**
 * @param {HTMLElement} el
 * @returns {boolean}
 */
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

/**
 * @param {HTMLElement} el
 * @param {number} dir
 * @returns {boolean}
 */
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

var departed = /** @type {Map<string, {path: string}>} */ (new Map());

/**
 * @param {Row} row
 * @returns {number}
 */
function ageOf(row) {
  return row && typeof row.last_event_age_s === "number" ? row.last_event_age_s : 0;
}

var TIER_COMPACT_FROM = 160;
var TIER_FULL_FROM = 360;
var TIER_SLACK = 8;
var RAIL_PX = 48;
var ROW_GAP_PX = 6;
var ROW_PAD_PX = 16;

var TIER_DEFAULTS = /** @type {{rail: number, compact: number, full: number, slack: number}} */ ({ rail: RAIL_PX, compact: TIER_COMPACT_FROM, full: TIER_FULL_FROM,
                      slack: TIER_SLACK });
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
    if (!entry.el.dataset.tier) return;
    var width = entry.el.getBoundingClientRect().width;
    if (width > 0 && setTier(entry.el, width) && entry.row) {
      drawTile(entry.el, entry.row, lastApprovals);
    }
  });
  placeSoon();
}

/**
 * @param {number} width
 * @param {Tier | ""} [was]
 * @returns {Tier}
 */
function paneTier(width, was) {
  var raw = /** @type {Tier} */ (width >= TIER_FULL_FROM ? "full" : width >= TIER_COMPACT_FROM ? "compact" : "rail");
  if (!was || raw === was || raw === "rail" || was === "rail") return raw;
  var lo = was === "full" ? TIER_FULL_FROM : TIER_COMPACT_FROM;
  var hi = was === "compact" ? TIER_FULL_FROM : Infinity;
  return (width >= lo - TIER_SLACK && width < hi + TIER_SLACK) ? was : raw;
}

/**
 * @param {HTMLElement} el
 * @param {number} width
 * @returns {boolean}
 */
function setTier(el, width) {
  var was = /** @type {Tier | ""} */ (el.dataset.tier || "");
  var tier = paneTier(width, was);
  if (tier === was) return false;
  attr(el, "data-tier", tier);
  return true;
}

var rowObserver = /** @type {ResizeObserver | null} */ (null);
var rowWidth = 0;
var rowSoon = 0;

/**
 * @param {ResizeObserverEntry} entry
 * @returns {number}
 */
function entryWidth(entry) {
  var box = entry.borderBoxSize;
  var first = /** @type {ResizeObserverSize} */ (box && (box[0] || box));
  if (first && typeof first.inlineSize === "number") return first.inlineSize;
  return entry.target.getBoundingClientRect().width;
}

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
  if (keyHome && redraw.indexOf(keyHome) >= 0) {
    var home = keyHome;
    keyHome = null;
    var stop = /** @type {HTMLElement} */ (home.dataset.tier === "rail" ? home.querySelector(".pane-rail") : home);
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

var railGroups = /** @type {Map<string, string[]>} */ (new Map());
var groupedInto = /** @type {Map<string, string>} */ (new Map());

/**
 * @param {string[]} shown
 * @param {string[]} open
 */
function groupRails(shown, open) {
  railGroups = new Map();
  groupedInto = new Map();
  var rails = shown.filter(function (name) { return open.indexOf(name) < 0; });
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

/**
 * @param {string} name
 * @returns {boolean}
 */
function groupedAway(name) {
  return groupedInto.has(name);
}

/**
 * @param {string} name
 * @returns {string}
 */
function railTarget(name) {
  var members = railGroups.get(name);
  if (!members) return name;
  var red = members.filter(function (member) {
    var entry = tiles.get(member);
    return !!entry && entry.el.classList.contains("needs-human");
  })[0];
  return red || name;
}

var RAIL_GLYPHS = {
  running: "▶", waiting_approval: "‖", needs_human: "!", blocked: "■",
  error: "✕", done: "✓", idle: "○", starting: "◌"
};

/**
 * @param {Row} row
 * @returns {string}
 */
function railLine(row) {
  var ac = ageChip(row.last_event_age_s);
  var bits = [row.needs_human ? "needs you" : (shownState(row).replace(/_/g, " ") || "no run yet")];
  if (ac.text) bits.push(ac.text + " ago");
  var spend = row.spend || {};
  if (spend.total) bits.push(spend.total + " premium");
  var n = unread.get(row.repo) || 0;
  if (n) bits.push(n + " unread");
  if (freshShown(row)) bits.push(row.fresh.because);
  var said = row.needs_human ? String(row.why || "") : String(row.last_said || "").slice(0, 160);
  return row.repo + ": " + bits.join(" · ") + (said ? " — " + said : "") +
         (freshShown(row) ? " — Alt+N starts fresh" : "");
}

/**
 * @param {HTMLElement} el
 * @param {Row} row
 */
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
  var fresh = !members && freshShown(row) ? (row.fresh.because === "old skills" ? " is-stale" : " is-outside") : "";
  setClass(face, "pane-rail st-" + (red ? "needs_human" : state) + (red ? " needs-human" : "") + fresh);
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

function drawHiddenCount() {
  var n = getEffectiveOrder().filter(function (name) { return isHidden(name); }).length;
  var button = document.getElementById("hiddencount");
  text(button, n ? n + " hidden" : "");
  hide(button, !n);
}

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

var saidLine = "";
var saidUntil = 0;
var sayTimer = null;

function say(message, seconds) {
  saidLine = message;
  saidUntil = Date.now() + (seconds || 6) * 1000;
  if (sayTimer) clearTimeout(sayTimer);
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

function drawOldSession(el, row) {
  var old = el.querySelector(".oldsession");
  if (!old) return;
  var sv = row.stale || {};
  hide(old, !sv.stale);
  text(old, row.renew_queued ? "renew queued" : "old skills");
  attr(old, "title", sv.stale
    ? (sv.reason || "began on older skills") +
      (row.renew_queued ? " — renewed when this turn ends"
                        : " — start fresh (Alt+N), or renew every stale session from the header")
    : "");
}

function renewStrip() { return document.getElementById("renew-strip"); }
var renewOpen = false;

function drawRenewStrip(rows, server) {
  var strip = renewStrip();
  if (!strip) return;
  var n = (rows || []).filter(function (r) { return r.stale && r.stale.stale; }).length;
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
    : "nothing to renew: every stale session is waiting on you, is a console, is done, or began outside the fleet");
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

function dayStrip() { return document.getElementById("day-strip"); }
var dayOpen = false;
var dayOfferN = -1;
var DAY_NOT_TODAY = "fleet.day.not-today";

function localDay() {
  var d = new Date();
  return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
}

function dayDismissed() {
  try { return localStorage.getItem(DAY_NOT_TODAY) === localDay(); } catch (e) { return false; }
}

function morningPanes(rows) {
  return (rows || []).filter(function (r) {
    var f = r.fresh || {};
    var run = r.run || {};
    return run.before_today === true && f.verdict === "now" && !!(f.starts || {}).ticket &&
           !r.external && run.origin !== "adopted";
  }).length;
}

function drawDayOffer(rows) {
  var strip = dayStrip();
  if (!strip) return;
  var n = dayDismissed() ? 0 : morningPanes(rows);
  if (n === dayOfferN) return;
  dayOfferN = n;
  text(strip.querySelector(".day-offer-words"), n === 1
    ? "1 pane is on a session that began before today —"
    : n + " panes are on sessions that began before today —");
  hide(strip.querySelector(".day-offer"), n === 0 || dayOpen);
  hide(strip, n === 0 && !dayOpen);
}

function dayGo() { return /** @type {HTMLButtonElement} */ (document.getElementById("daygo")); }

function countDay() {
  var strip = dayStrip();
  var n = strip ? strip.querySelectorAll(".day-rows li:not(.day-pattern) .day-tick:checked:not(:disabled)").length : 0;
  var go = dayGo();
  disable(go, n === 0);
  text(go, "start " + n + " fresh — about " + n + " premium turn" + (n === 1 ? "" : "s"));
}

function openDay() {
  var strip = dayStrip();
  if (!strip) return Promise.resolve();
  closePopovers();
  dayOpen = true;
  var sum = strip.querySelector(".day-sum");
  hide(strip, false);
  hide(strip.querySelector(".day-offer"), true);
  hide(sum, false);
  text(sum, "checking every agent…");
  disable(dayGo(), true);
  hide(strip.querySelector(".day-rows"), false);
  hide(strip.querySelector(".day-actions"), false);
  return post("fresh", { all: true, dry_run: true }).then(function (r) {
    if (!r || r.ok === false) {
      text(sum, ((r && r.error) || "the preview could not be read") + (r && r.hint ? " — " + r.hint : ""));
      return;
    }
    if (dayOpen) drawDayPlan(r);
  }).catch(function () { text(sum, "the preview could not be read"); });
}

function dayModelTitle(st) {
  return (st.model ? "configured " + st.model + " (" + (st.model_source || "") + ")"
                   : "no --model flag is passed (" + (st.model_source || "cli-auto") + ")") +
         (st.effort ? " · effort " + st.effort + (st.effort_source && st.effort_source !== st.model_source
                                                 ? " (" + st.effort_source + ")" : "") : "");
}

function drawDayPlan(p) {
  var strip = dayStrip();
  var list = strip.querySelector(".day-rows");
  var plan = String(p.plan_id || "");
  patchList(list, p.rows || [], function (r) { return r.repo; },
    function () {
      var li = /** @type {HTMLElement} */ (strip.querySelector(".day-pattern").cloneNode(true));
      li.classList.remove("day-pattern");
      li.hidden = false;
      li.querySelector(".day-answer").addEventListener("click", function () {
        var name = li.dataset.rowkey || "";
        openPane(name);
        var entry = tiles.get(name);
        var ask = /** @type {HTMLElement} */ (entry && entry.el.querySelector(".asks:not([hidden]) textarea, .asks:not([hidden]) input, .asks:not([hidden]) button"));
        if (ask) ask.focus();
      });
      return li;
    },
    function (li, r) {
      var st = r.starts || {};
      var box = /** @type {HTMLInputElement} */ (li.querySelector(".day-tick"));
      var tickable = r.verdict === "now";
      disable(box, !tickable);
      if (li.dataset.plan !== plan) { box.checked = tickable && !!r.ticked; setData(li, "plan", plan); }
      attr(box, "aria-label", "start " + r.repo + " fresh");
      setData(li, "keyless", r.keyless ? "1" : "");
      text(li.querySelector(".day-repo"), r.repo);
      text(li.querySelector(".day-verdict"), r.code || r.verdict);
      text(li.querySelector(".day-ticket"), st.ticket || "no ticket");
      var model = li.querySelector(".day-model");
      text(model, shortModel(st.model) + " · " + (st.model_source || "cli-auto"));
      attr(model, "title", dayModelTitle(st));
      text(li.querySelector(".day-began"), r.began ? "began " + beganWords(r.began) : "");
      text(li.querySelector(".day-why"), r.why || "");
      var q = (r.question || {}).q || "";
      text(li.querySelector(".day-question"), q ? "“" + q + "”" : "");
      hide(li.querySelector(".day-answer"), r.code !== "needs_you");
      setClass(li, "fresh-row day-row verdict-" + String(r.code || r.verdict).replace(/_/g, "-"));
    });
  hide(strip.querySelector(".day-keyless"), !(p.keyless > 0));
  text(strip.querySelector(".day-sum"), (p.ticked || 0) + " of " + (p.rows || []).length +
       " agents would start on a clean session — the others say why" +
       (p.keyless ? "; " + p.keyless + " with no ticket can be ticked" : ""));
  countDay();
}

function closeDay() {
  var strip = dayStrip();
  if (!strip) return;
  dayOpen = false;
  hide(strip.querySelector(".day-sum"), true);
  hide(strip.querySelector(".day-rows"), true);
  hide(strip.querySelector(".day-keyless"), true);
  hide(strip.querySelector(".day-actions"), true);
  dayOfferN = -1;
  drawDayOffer(lastFleet ? lastFleet.repos : []);
}

function runDay() {
  var strip = dayStrip();
  var go = dayGo();
  var repos = [];
  strip.querySelectorAll(".day-rows li:not(.day-pattern)").forEach(/** @type {(li: HTMLElement) => void} */ (function (li) {
    var box = /** @type {HTMLInputElement} */ (li.querySelector(".day-tick"));
    if (box.checked && !box.disabled) repos.push(li.dataset.rowkey);
  }));
  if (!repos.length) return;
  disable(go, true);
  var sum = strip.querySelector(".day-sum");
  post("fresh", { all: true, repos: repos }).then(function (r) {
    if (!r || r.ok === false) {
      text(sum, ((r && r.error) || "the fresh day could not be started") + (r && r.hint ? " — " + r.hint : ""));
      countDay();
      return;
    }
    var said = [];
    (r.rows || []).forEach(function (x) {
      var li = strip.querySelector('.day-rows li[data-rowkey="' + x.repo + '"]');
      if (li && x.done !== "skipped") {
        text(li.querySelector(".day-verdict"), x.done === "started" ? "started" : x.done + ": " + (x.code || x.verdict));
        if (x.done !== "started") text(li.querySelector(".day-why"), x.why || "");
        disable(li.querySelector(".day-tick"), true);
        setClass(li, "fresh-row day-row done-" + x.done);
      }
      if (x.row && x.row.repo) patchRow(x.row);
      if (x.done === "started") {
        var left = (x.leaves || {}).session;
        said.push(x.repo + ": started fresh on " + ((x.starts || {}).ticket || "no ticket") +
                  (left ? ", left " + ((x.leaves || {}).title || left) : ""));
      }
    });
    place();
    text(sum, (r.started || 0) + " started" + (r.changed ? ", " + r.changed + " changed since the preview" : ""));
    if (said.length) say(said.join(" · "), 12);
    countDay();
  }).catch(function () { countDay(); });
}

function previewFromAddress() {
  if (PARAMS.get("fresh") !== "1") return;
  var u = new URLSearchParams(location.search);
  u.delete("fresh");
  var qs = u.toString();
  history.replaceState(history.state, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  openDay();
}

(function bindDay() {
  var strip = dayStrip();
  if (!strip) return;
  var fresh = document.getElementById("dayfresh");
  if (fresh) fresh.addEventListener("click", function () { openDay(); });
  var offer = document.getElementById("dayoffer");
  if (offer) offer.addEventListener("click", function () { openDay(); });
  var nope = document.getElementById("daynottoday");
  if (nope) nope.addEventListener("click", function () {
    try { localStorage.setItem(DAY_NOT_TODAY, localDay()); } catch (e) {}
    dayOfferN = -1;
    hide(strip.querySelector(".day-offer"), true);
    hide(strip, !dayOpen);
  });
  dayGo().addEventListener("click", runDay);
  var cancel = document.getElementById("daycancel");
  if (cancel) cancel.addEventListener("click", closeDay);
  var all = /** @type {HTMLInputElement} */ (document.getElementById("daykeyless"));
  if (all) all.addEventListener("change", function () {
    strip.querySelectorAll('.day-rows li[data-keyless="1"] .day-tick').forEach(function (b) {
      /** @type {HTMLInputElement} */ (b).checked = all.checked;
    });
    countDay();
  });
  strip.querySelector(".day-rows").addEventListener("change", countDay);
  strip.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.stopPropagation(); closeDay(); }
  });
})();

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

function title(need) {
  var one = openName();
  var want = (need ? "(" + need + ") " : "") + "fleet" + (one ? " · " + one : "");
  if (document.title !== want) document.title = want;
}

/** @returns {HTMLElement[]} */
function paneStops() {
  return Array.prototype.map.call(
    document.querySelectorAll("#grid .tile:not(.is-hidden):not(.is-grouped)"),
    function (el) { return el.dataset.tier === "rail" ? el.querySelector(".pane-rail") : el; });
}

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

document.addEventListener("click", /** @type {(e: MouseEvent & {target: Element}) => void} */ (function (e) {
  if (e.target.closest && (e.target.closest(".smenu") || e.target.closest(".spill"))) return;
  closeMenus();
}));

(function bindModelCard() {
  var card = document.getElementById("modelcard");
  if (!card) return;
  modelPickerOpts = { variant: "full", label: "model", onPick: pickModel };
  modelPicker = createModelPicker(modelPickerOpts);
  card.querySelector(".mc-picker").appendChild(modelPicker);
  document.getElementById("mc-inherit").addEventListener("click", function () {
    pickModel({ model: "", effort: "", toolbar: "both", droppedEffort: "" });
  });
  document.getElementById("mc-close").addEventListener("click", closeModelCard);
  card.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") e.stopPropagation();
  });
  document.addEventListener("click", /** @type {(e: MouseEvent & {target: Element}) => void} */ (function (e) {
    if (card.hidden) return;
    if (card.contains(e.target)) return;
    if (e.target.closest && e.target.closest('[data-tool="model"]')) return;
    if (e.target.closest && e.target.closest(".mp-more")) return;
    closeModelCard();
  }));
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

var POPOVERS = { keymap: "keysbtn", daymenu: "daybtn" };

function popover(id, open) {
  var box = document.getElementById(id);
  var button = document.getElementById(POPOVERS[id]);
  if (!box || !button) return false;
  var want = open === undefined ? box.hidden : !!open;
  var hadTheKeyboard = !!(document.activeElement && box.contains(document.activeElement));
  Object.keys(POPOVERS).forEach(function (other) {
    var o = document.getElementById(other);
    var ob = document.getElementById(POPOVERS[other]);
    var on = other === id && want;
    if (o) hide(o, !on);
    if (ob) attr(ob, "aria-expanded", String(on));
  });
  if (want) {
    var first = /** @type {HTMLElement} */ (box.querySelector("select:not(:disabled), button:not(:disabled), input:not(:disabled), [tabindex]"));
    if (first) first.focus();
  } else if (hadTheKeyboard) {
    button.focus();
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
document.addEventListener("click", /** @type {(e: MouseEvent & {target: Element}) => void} */ (function (e) {
  Object.keys(POPOVERS).forEach(function (id) {
    var box = document.getElementById(id);
    var button = document.getElementById(POPOVERS[id]);
    if (box && !box.hidden && !box.contains(e.target) && !(button && button.contains(e.target))) {
      popover(id, false);
    }
  });
}));

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "Escape" && !typing) { if (dayOpen) { closeDay(); return; } closeSide(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "N" && e.shiftKey) { openDay(); return; }
  if (e.key === "1") { applyPreset("one"); return; }
  if (e.key === "=") { applyPreset("all"); return; }
  if (e.key === "f") { applyPreset("needs"); return; }
  if (e.key === "u") { undoWidths(); return; }
  if (e.key === "i") { section("unsorted"); return; }
  if (e.key === "?") { popover("keymap"); return; }
  if (e.key === "g") { location.href = pageUrl("/map"); return; }
  if (e.key === "/") { e.preventDefault(); document.getElementById("find").focus(); }
});


var st = servedTiers();
if (st) applyTiers(st);
restoreCached();
forgetRetiredParams();
previewFromAddress();
