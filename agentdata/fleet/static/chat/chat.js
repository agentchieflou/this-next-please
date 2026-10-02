"use strict";

var W_NAME = PARAMS.get("w") || "chat";
var C_GLYPHS = {
  running: "▶", waiting_approval: "‖", needs_human: "!", blocked: "■",
  error: "✕", done: "✓", idle: "○", starting: "◌"
};
var C_SESSIONS_SHOWN = 5;
var C_PAGE = 200;
var C_TOOLS_KEY = "fleet.chat.tools";
var C_WIDE = window.matchMedia ? window.matchMedia("(min-width: 721px)") : null;

var cAgents = document.getElementById("chatagents");
var cLog = document.getElementById("chatlog");
var cScroll = document.getElementById("chatscroll");
var cEarlier = document.getElementById("chatearlier");
var cSaid = document.getElementById("chatsaid");
var cLive = document.getElementById("chatlive");
var cForm = document.getElementById("chatform");
var cEnded = document.getElementById("chatended");
var cApproval = document.getElementById("chatapproval");
var cAsks = document.getElementById("chatasks");
var cResume = /** @type {HTMLButtonElement} */ (document.getElementById("chatresume"));
var cSend = /** @type {HTMLButtonElement} */ (document.getElementById("chatsend"));
var cMessage = /** @type {HTMLTextAreaElement} */ (document.getElementById("chatmessage"));
var cReason = /** @type {HTMLInputElement} */ (document.getElementById("chatreason"));
var cFind = /** @type {HTMLInputElement} */ (document.getElementById("chatfind"));
var cTools = /** @type {HTMLInputElement} */ (document.getElementById("chattools"));

/**
 * @typedef {Object} Shown
 * @property {string} key
 * @property {number} seq
 * @property {number} cursor
 * @property {boolean} more
 * @property {boolean} foreign
 * @property {string} state
 * @property {string} at
 */

/** @type {{rows: Array<Object>, approvals: Array<Object>, sessions: Object<string, Array<Object>>, loadedFor: Object<string, string>, more: Object<string, boolean>, folded: Object<string, boolean>, repo: string, session: string, shown: Shown, force: boolean, fresh: string, resume: string, source: EventSource, cursors: Object<string, number>, timer: any, live: string, frames: number, ticks: number, refreshes: number, reading: number}} */
var cState = {
  rows: [], approvals: [], sessions: {}, loadedFor: {}, more: {}, folded: {},
  repo: "", session: "",
  shown: { key: "", seq: 0, cursor: 0, more: false, foreign: false, state: "", at: "" },
  force: false, fresh: "", resume: "",
  source: null, cursors: {}, timer: null, live: "", frames: 0, ticks: 0, refreshes: 0, reading: 0
};

attr(document.getElementById("todesk"), "href", pageUrl("/"));
attr(document.getElementById("tomap"), "href", pageUrl("/map"));
attr(document.getElementById("tosettings"), "href", pageUrl("/settings"));

/** @param {number} s @returns {string} */
function cAge(s) {
  if (s == null || s < 0) return "";
  if (s < 90) return "now";
  if (s < 5400) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

/** @param {string} ts @returns {Date|null} */
function cDate(ts) {
  if (!ts) return null;
  var s = String(ts);
  var d = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(s) ? s : s + "Z");
  return isNaN(d.getTime()) ? null : d;
}

/** @param {string} ts @returns {string} */
function cClock(ts) {
  var d = cDate(ts);
  return d ? ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2) : "";
}

/** @param {string} ts @returns {string} */
function cWhen(ts) {
  var d = cDate(ts);
  if (!d) return "";
  var now = new Date();
  var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (d.toDateString() === now.toDateString()) return "today " + cClock(ts);
  if (d.toDateString() === yesterday.toDateString()) return "yesterday " + cClock(ts);
  return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
}

/** @param {string} repo @returns {Object} */
function cRow(repo) {
  return cState.rows.filter(function (r) { return r.repo === repo; })[0] || null;
}

/** @param {Object} row @returns {string} */
function cCurrent(row) {
  return String((row && row.run && row.run.session) || "");
}

/** @returns {string} */
function cShownId() {
  return cState.session || cCurrent(cRow(cState.repo));
}

/** @param {Object} row @returns {boolean} */
function cIsLive(row) {
  return !!row && (!cState.session || cState.session === cCurrent(row));
}

/** @returns {string} */
function cKey() {
  return cState.repo ? cState.repo + "|" + cShownId() : "";
}

/** @param {Object} s @returns {string} */
function cTitle(s) {
  return s.title || s.ticket || (s.id ? "session " + String(s.id).slice(0, 8) : "a new session");
}

/** @param {Object} row @returns {Array<Object>} */
function cSessionsOf(row) {
  var cur = cCurrent(row);
  var run = row.run || {};
  var list = (cState.sessions[row.repo] || []).slice();
  if (cur && !list.some(function (s) { return s.id === cur; })) {
    list.push({ id: cur, title: run.session_title || "", ticket: run.ticket || row.ticket || "",
                last_seen: run.started || row.at || "" });
  }
  list.sort(function (a, b) {
    if (a.id === cur) return -1;
    if (b.id === cur) return 1;
    return String(b.last_seen || "").localeCompare(String(a.last_seen || ""));
  });
  if (!cur && run.live) list.unshift({ id: "", title: "", ticket: run.ticket || "", last_seen: run.started || "" });
  return list.map(function (s) {
    var current = s.id === cur;
    var chip = current ? (run.live ? "live" : "current")
      : s.left ? "left" : s.source === "console" ? "console" : s.source === "adopted" ? "your chat" : "earlier";
    return { repo: row.repo, id: s.id, title: cTitle(s), current: current, chip: chip,
             when: cWhen(s.last_seen || s.first_seen || "") };
  });
}

function cCreateAgent() {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("chatagent"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  li.querySelector(".ca-head").addEventListener("click", function () { cOpen(li.dataset.rowkey, ""); });
  li.querySelector(".ca-fold").addEventListener("click", function () {
    var repo = li.dataset.rowkey;
    cState.folded[repo] = !cState.folded[repo];
    drawAgents();
  });
  li.querySelector(".ca-more").addEventListener("click", function () {
    var repo = li.dataset.rowkey;
    cState.more[repo] = !cState.more[repo];
    drawAgents();
  });
  li.querySelector(".ca-new").addEventListener("click", function () { cFresh(li.dataset.rowkey); });
  return li;
}

function cCreateSession() {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("chatsess"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  li.querySelector(".cs-open").addEventListener("click", function () {
    cOpen(li.dataset.repo, li.dataset.current === "1" ? "" : li.dataset.sid);
  });
  return li;
}

/** @param {HTMLElement} li @param {Object} s */
function drawSession(li, s) {
  setData(li, "repo", s.repo);
  setData(li, "sid", s.id);
  setData(li, "current", s.current ? "1" : "");
  var open = cState.repo === s.repo && (s.current ? !cState.session || cState.session === s.id : cState.session === s.id);
  setClass(li, "cs" + (s.current ? " is-current" : "") + (open ? " is-open" : ""));
  var button = li.querySelector(".cs-open");
  attr(button, "aria-current", open ? "true" : null);
  attr(button, "title", s.id ? "session " + s.id : "its new session, before Copilot has named it");
  text(li.querySelector(".cs-title"), s.title);
  text(li.querySelector(".cs-chip"), s.chip);
  text(li.querySelector(".cs-when"), s.when);
}

/** @param {HTMLElement} li @param {Object} row */
function drawAgent(li, row) {
  var state = String(row.state || "idle");
  setClass(li, "ca " + state + (row.needs_human ? " needs-human" : "") + (row.repo === cState.repo ? " is-open" : ""));
  var head = li.querySelector(".ca-head");
  attr(head, "title", row.why || "");
  attr(head, "aria-current", row.repo === cState.repo && !cState.session ? "true" : null);
  text(li.querySelector(".ca-glyph"), C_GLYPHS[state] || "·");
  text(li.querySelector(".ca-name"), row.repo);
  text(li.querySelector(".ca-age"), cAge(row.last_event_age_s));
  var badge = li.querySelector(".ca-badge");
  hide(badge, !row.needs_human);
  text(badge, "needs you");
  var folded = !!cState.folded[row.repo];
  attr(li.querySelector(".ca-fold"), "aria-expanded", folded ? "false" : "true");
  var all = cSessionsOf(row);
  var shown = cState.more[row.repo] ? all : all.slice(0, C_SESSIONS_SHOWN);
  var list = li.querySelector(".ca-sessions");
  hide(list, folded);
  hide(li.querySelector(".ca-foot"), folded);
  patchList(list, shown, function (s) { return s.id || "(new)"; }, cCreateSession, drawSession);
  var more = li.querySelector(".ca-more");
  hide(more, all.length <= C_SESSIONS_SHOWN);
  text(more, cState.more[row.repo] ? "fewer" : (all.length - C_SESSIONS_SHOWN) + " more");
  attr(li.querySelector(".ca-new"), "title", cState.fresh === row.repo ? "press again: its session is closed first"
    : "leave its current session under earlier and start a clean one");
}

function drawAgents() {
  var find = cFind.value.trim().toLowerCase();
  var rows = cState.rows.filter(function (r) { return !find || String(r.repo).toLowerCase().indexOf(find) >= 0; });
  patchList(cAgents, rows, function (r) { return r.repo; }, cCreateAgent, drawAgent);
  hide(document.getElementById("chatnone"), cState.rows.length > 0);
  var n = cState.rows.filter(function (r) { return r.needs_human; }).length;
  text(document.getElementById("chatneed"), n ? n + " need you" : "");
  var title = (n ? "(" + n + ") " : "") + "fleet · chat";
  if (document.title !== title) document.title = title;
}

/** @param {Object} ev @returns {{who: string, text: string, fail: boolean}|null} */
function chatLine(ev) {
  var d = ev.data || {};
  /** @param {string} who @param {string} words @param {boolean} [fail] */
  var say = function (who, words, fail) { return words ? { who: who, text: words, fail: !!fail } : null; };
  switch (ev.kind) {
    case "started":
      if (d.console) return say("note", "a console window opened on this session");
      if (d.resumed && d.prompt) return say("you", d.prompt);
      return say("note", (d.resumed ? "resumed" : "started") + (ev.ticket ? " on " + ev.ticket : "")
                 + (d.summary ? ": " + d.summary : ""));
    case "said": return say("you", d.text || "");
    case "assistant_text": return say("agent", d.text || "");
    case "tool_call": return say("tool", (d.tool || "tool") + " " + JSON.stringify(d.arguments || {}).slice(0, 240));
    case "tool_result": return d.ok === false ? say("tool", "✕ " + (d.message || d.error || "failed"), true) : null;
    case "denied": return say("note", "refused: " + (d.message || "a tool it may not run"), true);
    case "friction": return say("note", "stopped: " + (d.unblock || d.file || ""), true);
    case "question_opened": return say("ask", (d.question || d.q || "") +
                                       (d.choices && d.choices.length ? "\n" + d.choices.join(" · ") : ""));
    case "question_answered": return say("you", d.answer || "answered: " + (d.question || ""));
    case "question_cleared": return say("note", "question closed: " + (d.question || ""));
    case "needs_approval": return say("note", "waiting for your approval: " + (d.summary || d.kind || ""));
    case "approval_resolved": return say("note", (d.decision || "decided") + " by " + (d.by || "you"));
    case "phase_changed": return d.from && d.to ? say("note", d.from + " → " + d.to) : null;
    case "pr_open": return say("note", "PR: " + (d.url || ""));
    case "artifact": return say("note", "wrote " + ((d.artifact && d.artifact.path) || ""));
    case "exited": return d.exit_code ? say("note", "the turn ended with exit " + d.exit_code, true) : null;
    case "error": return say("note", "it failed: " + (d.message || "exit " + d.exit_code), true);
    case "subagent_started": return say("tool", "sub-agent " + (d.name || d.agent || "") + " started");
    case "subagent_ended": return say("tool", "sub-agent " + (d.agent || "") + (d.ok ? " finished" : " failed: " + (d.error || "")), !d.ok);
    case "project.ticket_changed": return say("note", (d.key || "") + " is " + (d.status || ""));
    case "project.pr_merged": return say("note", "PR merged: " + (d.url || ""));
    default: return null;
  }
}

/** @param {Object} ev @returns {HTMLElement|null} */
function chatItem(ev) {
  var said = chatLine(ev);
  if (!said) return null;
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("chatline"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  setClass(li, "cl cl-" + said.who + (said.fail ? " cl-fail" : ""));
  setData(li, "seq", ev.seq || 0);
  setData(li, "kind", ev.kind);
  text(li.querySelector(".cl-who"), said.who === "you" ? "you" : said.who === "ask" ? cState.repo + " asks" : cState.repo);
  text(li.querySelector(".cl-text"), said.text);
  text(li.querySelector(".cl-when"), cClock(ev.ts));
  attr(li.querySelector(".cl-when"), "title", ev.ts || null);
  return li;
}

/** @returns {boolean} */
function cAtBottom() {
  return cScroll.scrollHeight - cScroll.scrollTop - cScroll.clientHeight <= 40;
}

/** @param {Object} ev */
function chatAppend(ev) {
  if (ev.seq) cState.shown.seq = Math.max(cState.shown.seq, Number(ev.seq));
  var li = chatItem(ev);
  if (!li) return;
  var bottom = cAtBottom();
  cLog.appendChild(li);
  if (bottom) cScroll.scrollTop = cScroll.scrollHeight;
}

/** @param {Object} ev @returns {boolean} */
function cForeign(ev) {
  if (ev.kind !== "started") return false;
  var d = ev.data || {};
  var id = cShownId();
  return !!id && String(d.session || "") !== id;
}

/** @param {number} [before] */
function chatLoad(before) {
  var key = cKey();
  var id = cShownId();
  var row = cRow(cState.repo);
  if (!before) {
    while (cLog.firstChild) cLog.removeChild(cLog.firstChild);
    cState.shown = { key: key, seq: 0, cursor: 0, more: false, foreign: false, state: "", at: "" };
    hide(cEarlier, true);
  }
  if (!key) return Promise.resolve();
  if (!id) {
    ((row && row.recent) || []).forEach(chatAppend);
    cScroll.scrollTop = cScroll.scrollHeight;
    return Promise.resolve();
  }
  var params = /** @type {Object<string, any>} */ ({ repo: cState.repo, session: id, limit: C_PAGE });
  if (before) params.before = before;
  cState.reading++;
  var done = function () { cState.reading--; };
  return fetch(q("/api/transcript", params)).then(function (r) { return r.json(); }).then(function (data) {
    if (key !== cKey() || !data || !data.ok) return;
    var events = data.events || [];
    if (before) {
      var height = cScroll.scrollHeight;
      var first = cLog.firstChild;
      events.forEach(function (ev) {
        var li = chatItem(ev);
        if (li) cLog.insertBefore(li, first);
      });
      cScroll.scrollTop += cScroll.scrollHeight - height;
    } else {
      events.forEach(chatAppend);
      cScroll.scrollTop = cScroll.scrollHeight;
      cState.shown.state = data.state || "";
      cState.shown.at = data.at || "";
    }
    cState.shown.cursor = Number(data.cursor || 0);
    cState.shown.more = !!data.more;
    hide(cEarlier, !cState.shown.more);
    drawMain();
  }).then(done, function (e) { done(); text(cSaid, String(e)); });
}

/** @param {Object} row */
function drawAsks(row) {
  var open = cIsLive(row) ? (row.asked || []).filter(function (x) { return x.blocking !== false; }) : [];
  hide(cAsks, !open.length);
  text(document.getElementById("chatasksn"), open.length === 1 ? "it asks" : "it asks " + open.length + " things");
  hide(document.getElementById("chatanswer"), !open.some(function (x) { return !!x.id; }));
  patchList(document.getElementById("chatasklist"), open, function (x, i) { return x.id || "q" + i + ":" + (x.q || ""); }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("chatq"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (li, x) {
    setData(li, "qid", x.id || "");
    text(li.querySelector(".cq-q"), (x.q || "") + (x.id ? "" : " (reply below: it carries no id to answer)"));
    var input = /** @type {HTMLInputElement} */ (li.querySelector(".cq-answer"));
    hide(input, !x.id);
    attr(input, "placeholder", x["default"] ? "your answer (default: " + x["default"] + ")" : "your answer");
    patchList(li.querySelector(".cq-choices"), x.choices || [], function (c) { return c; }, function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ask-choice";
      b.addEventListener("click", function () {
        if (input.hidden) { cMessage.value = c; cMessage.focus(); return; }
        input.value = c;
        Array.prototype.forEach.call(b.parentNode.children, function (o) { attr(o, "aria-pressed", String(o === b)); });
      });
      return b;
    }, function (b, c) { text(b, c); attr(b, "aria-pressed", String(input.value === c)); });
  });
}

/** @param {Object} row */
function drawApproval(row) {
  var mine = cIsLive(row) ? cState.approvals.filter(function (a) { return a.repo === row.repo; }) : [];
  var a = mine[0];
  hide(cApproval, !a);
  if (!a) return;
  setData(cApproval, "id", a.id);
  text(document.getElementById("chatapprovalwhat"), [a.summary || a.kind || "a write", a.ticket].filter(Boolean).join(" · ")
       + (mine.length > 1 ? " (and " + (mine.length - 1) + " more)" : ""));
}

/** @param {Object} row @returns {string} */
function cVerb(row) {
  if (!cCurrent(row) && !(row.run && row.run.live)) return "start";
  return row.console ? "say" : "send";
}

/** @param {Object} row */
function drawCompose(row) {
  var live = cIsLive(row);
  hide(cForm, !live);
  hide(cEnded, live);
  if (!live) {
    var s = (cState.sessions[row.repo] || []).filter(function (x) { return x.id === cState.session; })[0] || { id: cState.session };
    text(document.getElementById("chatendedwhat"), cTitle(s) + " is not " + row.repo + "'s current session"
         + (s.last_seen ? "; it was last active " + cWhen(s.last_seen) : "")
         + ". Reading it changes nothing; Resume here makes it the live one again.");
    text(cResume, cState.resume === cState.session ? cResume.dataset.armedLabel || "Resume anyway" : "Resume here");
    return;
  }
  var verb = cVerb(row);
  disable(cSend, !!row.external);
  attr(cSend, "title", row.external ? "type in that window — this session is not the fleet's to drive" : null);
  text(cSend, verb === "start" ? "Start" : cState.force ? "Send anyway" : "Send");
  attr(cMessage, "placeholder", verb === "start" ? "a ticket key to start on, or empty for a clean session"
       : verb === "say" ? "type into its console window" : (row.run && row.run.live) ? "it is working; this goes in once the turn ends"
       : "reply");
}

function drawMain() {
  var row = cRow(cState.repo);
  toggle(document.body, "is-open", !!row);
  hide(document.getElementById("chatempty"), !!row);
  hide(cScroll, !row);
  hide(document.getElementById("chatstate"), !row);
  if (!row) {
    text(document.getElementById("chatname"), "pick a session");
    text(document.getElementById("chatsession"), "");
    text(document.getElementById("chatsays"), "");
    [cForm, cEnded, cApproval, cAsks].forEach(function (el) { hide(el, true); });
    return;
  }
  var live = cIsLive(row);
  var state = live ? String(row.state || "idle") : (cState.shown.state || "idle");
  var chip = document.getElementById("chatstate");
  setClass(chip, "chip " + state);
  text(chip, (C_GLYPHS[state] || "·") + " " + state.replace(/_/g, " "));
  text(document.getElementById("chatname"), row.repo);
  var id = cShownId();
  var s = (cState.sessions[row.repo] || []).filter(function (x) { return x.id === id; })[0] || { id: id, ticket: live ? row.ticket : "" };
  text(document.getElementById("chatsession"), cTitle(s) + (live ? (row.run && row.run.live ? " · live" : " · current") : " · earlier"));
  attr(document.getElementById("chatsession"), "title", id ? "session " + id : null);
  text(document.getElementById("chatsays"), live ? row.why || "" : "");
  toggle(cLog, "no-tools", !cTools.checked);
  drawApproval(row);
  drawAsks(row);
  drawCompose(row);
}

/** @param {string} repo @param {string} session */
function cOpen(repo, session) {
  var otherAgent = repo !== cState.repo;
  var moved = otherAgent || session !== cState.session;
  cState.repo = repo;
  cState.session = session;
  if (moved) {
    cState.force = false;
    cState.resume = "";
    text(cSaid, "");
  }
  if (otherAgent) cMessage.value = "";
  try {
    history.replaceState(null, "", "#" + encodeURIComponent(repo) + (session ? "/" + encodeURIComponent(session) : ""));
  } catch (e) {}
  drawAgents();
  drawMain();
  if (cState.shown.key !== cKey()) return chatLoad();
  return Promise.resolve();
}

/** @param {string} what @param {Object} body @returns {Promise<Object>} */
function cPost(what, body) {
  text(cSaid, what + "…");
  return post(what, body).then(function (r) {
    text(cSaid, r && r.ok ? "" : ((r && r.error) || "refused") + (r && r.hint ? " — " + r.hint : ""));
    cSoon();
    return r || {};
  }, function (e) { text(cSaid, String(e)); return {}; });
}

/** @param {string} repo */
function cFresh(repo) {
  var closed = cState.fresh === repo;
  return cPost("fresh", closed ? { repo: repo, closed: true } : { repo: repo }).then(function (r) {
    if (r.ok) {
      cState.fresh = "";
      var left = r.leaves || {};
      text(cSaid, left.session ? "left " + (left.title || left.session) + "; it stays under " + repo : "started fresh");
      cState.loadedFor[repo] = "";
      return cOpen(repo, "");
    }
    if (r.second_press) {
      cState.fresh = repo;
      text(cSaid, [r.error, r.hint].filter(Boolean).join(" — ") + " — press + new session again once it is closed");
    }
    drawAgents();
  });
}

function cSubmit() {
  var row = cRow(cState.repo);
  if (!row) return;
  var message = cMessage.value.trim();
  var verb = cVerb(row);
  if (verb === "start") {
    var started = message ? cPost("start", { repo: row.repo, ticket: message }) : cFresh(row.repo);
    return started.then(function (r) { if (r && r.ok) cMessage.value = ""; });
  }
  if (!message) { text(cSaid, "type a message first"); return; }
  var forcing = cState.force;
  disable(cSend, true);
  return cPost(verb, { repo: row.repo, message: message, force: forcing }).then(function (r) {
    disable(cSend, false);
    cState.force = !r.ok && r.code === "budget_exceeded" && !forcing;
    if (cState.force) text(cSaid, (r.error || "") + " — press Send anyway to spend one more turn");
    if (r.ok) cMessage.value = "";
    drawMain();
  });
}

cForm.addEventListener("submit", function (e) { e.preventDefault(); cSubmit(); });
cMessage.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); cSubmit(); }
});
cEarlier.addEventListener("click", function () { if (cState.shown.cursor) chatLoad(cState.shown.cursor); });
document.getElementById("chatback").addEventListener("click", function () {
  cState.repo = "";
  cState.session = "";
  try { history.replaceState(null, "", location.pathname + location.search); } catch (e) {}
  drawAgents();
  drawMain();
  chatLoad();
});
document.getElementById("chatcurrent").addEventListener("click", function () { cOpen(cState.repo, ""); });
cResume.addEventListener("click", function () {
  var repo = cState.repo;
  var session = cState.session;
  var armed = cState.resume === session;
  cPost("start", { repo: repo, resume: session, force: armed }).then(function (r) {
    if (r.ok) {
      cState.resume = "";
      cState.loadedFor[repo] = "";
      cOpen(repo, "");
      return;
    }
    if (r.code === "live_agent" || r.code === "mid_ticket") {
      cState.resume = session;
      setData(cResume, "armedLabel", r.code === "live_agent" ? "Stop and resume" : "Resume anyway");
      drawMain();
    }
  });
});
document.getElementById("chatapprove").addEventListener("click", function () {
  cPost("approve", { id: cApproval.dataset.id, reason: cReason.value.trim() }).then(function (r) { if (r.ok) cReason.value = ""; });
});
document.getElementById("chatdeny").addEventListener("click", function () {
  cPost("deny", { id: cApproval.dataset.id, reason: cReason.value.trim() }).then(function (r) { if (r.ok) cReason.value = ""; });
});
document.getElementById("chatanswer").addEventListener("click", function () {
  var answers = [];
  Array.prototype.forEach.call(document.getElementById("chatasklist").children, function (li) {
    var value = /** @type {HTMLInputElement} */ (li.querySelector(".cq-answer")).value.trim();
    if (value && li.dataset.qid) answers.push({ id: li.dataset.qid, answer: value });
  });
  if (!answers.length) { text(cSaid, "pick a choice or type an answer first"); return; }
  cPost("answer", { repo: cState.repo, answers: answers }).then(function (r) {
    if (!r.ok) return;
    Array.prototype.forEach.call(document.getElementById("chatasklist").querySelectorAll(".cq-answer"), function (i) { i.value = ""; });
  });
});
cFind.addEventListener("input", drawAgents);
cTools.addEventListener("change", function () {
  try { localStorage.setItem(C_TOOLS_KEY, cTools.checked ? "on" : "off"); } catch (e) {}
  toggle(cLog, "no-tools", !cTools.checked);
});
try { if (localStorage.getItem(C_TOOLS_KEY) === "off") cTools.checked = false; } catch (e) {}

/** @param {Object} row @returns {string} */
function cSignature(row) {
  return cCurrent(row) + "|" + (row.sessions_n || 0);
}

/** @param {string} repo */
function cLoadSessions(repo) {
  var row = cRow(repo);
  cState.loadedFor[repo] = cSignature(row);
  return fetch(q("/api/sessions", { repo: repo })).then(function (r) { return r.json(); }).then(function (data) {
    if (!data || !data.ok) return;
    cState.sessions[repo] = data.sessions || [];
    drawAgents();
    if (repo === cState.repo) drawMain();
  }, function () { cState.loadedFor[repo] = ""; });
}

function cPick() {
  var hash = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  if (hash) {
    var at = hash.indexOf("/");
    var repo = at < 0 ? hash : hash.slice(0, at);
    if (cRow(repo)) return { repo: repo, session: at < 0 ? "" : hash.slice(at + 1) };
  }
  if (C_WIDE && !C_WIDE.matches) return null;
  var needs = cState.rows.filter(function (r) { return r.needs_human; })[0];
  var recent = cState.rows.slice().sort(function (a, b) {
    return (a.last_event_age_s == null ? 1e12 : a.last_event_age_s) - (b.last_event_age_s == null ? 1e12 : b.last_event_age_s);
  })[0];
  var first = needs || recent;
  return first ? { repo: first.repo, session: "" } : null;
}

function cRefresh() {
  cState.refreshes++;
  cState.reading++;
  var done = function () { cState.reading--; };
  return fetch(q("/api/fleet")).then(function (r) { return r.json(); }).then(function (f) {
    if (!f || !f.ok) return;
    var was = cKey();
    cState.rows = f.repos || [];
    cState.approvals = f.approvals || [];
    cState.rows.forEach(function (row) {
      if (cState.cursors[row.repo] == null && row.last_seq) cState.cursors[row.repo] = Number(row.last_seq);
      if (cState.loadedFor[row.repo] !== cSignature(row)) cLoadSessions(row.repo);
    });
    if (cState.repo && !cRow(cState.repo)) { cState.repo = ""; cState.session = ""; }
    if (!cState.repo && cState.refreshes === 1) {
      var pick = cPick();
      if (pick) { cState.repo = pick.repo; cState.session = pick.session; }
    }
    drawAgents();
    drawMain();
    if (cKey() !== was || cState.shown.key !== cKey()) return chatLoad();
  }).then(done, function (e) { done(); throw e; });
}

function cSoon() {
  if (cState.timer) return;
  cState.timer = setTimeout(function () {
    cState.timer = null;
    cRefresh().catch(function () {});
  }, 400);
}

/** @param {string} state */
function cLiveAs(state) {
  cState.live = state;
  setClass(cLive, state === "live" ? "dot live" : "dot lost");
  text(cLive, state);
}

function cSince() {
  return Object.keys(cState.cursors).map(function (k) { return k + ":" + cState.cursors[k]; }).join(",");
}

function cConnect() {
  if (cState.source) cState.source.close();
  var params = { since: cSince(), w: W_NAME, page: "chat", notify: "0" };
  if (PARAMS.get("shell")) params.shell = PARAMS.get("shell");
  var source = cState.source = new EventSource(q("/api/events", params));
  source.addEventListener("agent", function (m) {
    var at = String(/** @type {MessageEvent} */ (m).lastEventId || "").split(":");
    if (at.length === 2) cState.cursors[at[0]] = Number(at[1]);
    cState.frames++;
    try {
      var ev = JSON.parse(/** @type {MessageEvent} */ (m).data);
      if (ev.repo === cState.repo && cState.shown.key === cKey() && cIsLive(cRow(cState.repo))
          && Number(ev.seq || 0) > cState.shown.seq) {
        if (cForeign(ev)) cState.shown.foreign = true;
        if (!cState.shown.foreign) chatAppend(ev);
      }
    } catch (err) {}
    cSoon();
  });
  source.addEventListener("polls", cSoon);
  source.addEventListener("desk", cSoon);
  source.addEventListener("theme", function (m) {
    try { applyThemeState(JSON.parse(/** @type {MessageEvent} */ (m).data)); } catch (err) {}
  });
  source.addEventListener("tick", function () { cState.ticks++; cLiveAs("live"); });
  source.onopen = function () { cLiveAs("live"); };
  source.onerror = function () {
    cLiveAs("reconnecting");
    source.close();
    if (cState.source !== source) return;
    cState.source = null;
    setTimeout(function () {
      var again = function () { if (!cState.source && !document.hidden) cConnect(); };
      cRefresh().then(again, again);
    }, 2000);
  };
}

window.addEventListener("hashchange", function () {
  var pick = cPick();
  if (pick && (pick.repo !== cState.repo || pick.session !== cState.session)) cOpen(pick.repo, pick.session);
});

document.addEventListener("visibilitychange", function () {
  if (cState.source) { cState.source.close(); cState.source = null; }
  if (document.visibilityState === "visible") cRefresh().then(cConnect, cConnect);
});

cRefresh().then(cConnect, function () {
  text(cSaid, "the fleet could not be read; reload to try again");
});

window.FleetChat = Object.freeze({
  get w() { return W_NAME; },
  get rows() { return cState.rows; },
  get open() { return { repo: cState.repo, session: cState.session, shown: cShownId() }; },
  get sessions() { return cState.sessions; },
  get stream() {
    return { frames: cState.frames, ticks: cState.ticks, state: cState.live, refreshes: cState.refreshes,
             busy: !!cState.timer || cState.reading > 0 };
  }
});
