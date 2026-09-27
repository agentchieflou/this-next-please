"use strict";

var W_NAME = PARAMS.get("w") || "phone";
var M_GLYPHS = {
  running: "▶", waiting_approval: "‖", needs_human: "!", blocked: "■",
  error: "✕", done: "✓", idle: "○", starting: "◌"
};

var mAgents = document.getElementById("agents");
var mOpenEl = document.getElementById("open");
var mLive = document.getElementById("mlive");
var mNeed = document.getElementById("mneed");
var mSaid = document.getElementById("said");
var mReason = /** @type {HTMLInputElement} */ (document.getElementById("reason"));
var mMessage = /** @type {HTMLInputElement} */ (document.getElementById("message"));
var mApproval = document.getElementById("approval");
var mAsks = document.getElementById("asks");

/** @type {{rows: Array<Object>, open: string, shown: string, record: Object, source: EventSource, cursors: Object, timer: any, live: string, frames: number, ticks: number, refreshes: number, reading: number}} */
var mState = { rows: [], open: "", shown: "", record: null, source: null, cursors: {}, timer: null,
               live: "", frames: 0, ticks: 0, refreshes: 0, reading: 0 };

attr(document.getElementById("todesk"), "href", pageUrl("/"));
attr(document.getElementById("tosettings"), "href", pageUrl("/settings"));

/** @param {number} s @returns {string} */
function mAge(s) {
  if (s == null || s < 0) return "";
  if (s < 90) return "now";
  if (s < 5400) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

/** @param {string} repo @returns {Object} */
function mRow(repo) {
  return mState.rows.filter(function (r) { return r.repo === repo; })[0] || null;
}

function mCreateAgent() {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("magent"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  li.querySelector(".pick").addEventListener("click", function () { mShow(li.dataset.rowkey); });
  return li;
}

/** @param {HTMLElement} li @param {Object} row */
function drawAgent(li, row) {
  var state = String(row.state || "idle");
  toggle(li, "needs-human", !!row.needs_human);
  toggle(li, "is-open", row.repo === mState.open);
  setData(li, "role", row.role || "");
  text(li.querySelector(".name"), row.repo);
  var chip = li.querySelector(".chip");
  setClass(chip, "chip " + state);
  text(chip, (M_GLYPHS[state] || "·") + " " + state.replace(/_/g, " "));
  text(li.querySelector(".age"), mAge(row.age_s));
  text(li.querySelector(".says"), row.says || "");
}

function drawAgents() {
  patchList(mAgents, mState.rows, function (r) { return r.repo; }, mCreateAgent, drawAgent);
  var n = mState.rows.filter(function (r) { return r.needs_human; }).length;
  text(mNeed, n ? n + " need you" : "nobody needs you");
}

/** @param {string} repo */
function mShow(repo) {
  mState.open = repo;
  drawAgents();
  return mRead().then(drawOpen);
}

function mRead() {
  var row = mRow(mState.open);
  var id = row && row.approval_id;
  if (!id) { mState.record = null; return Promise.resolve(); }
  if (mState.record && mState.record.id === id) return Promise.resolve();
  return fetch(q("/api/approval", { id: id })).then(function (r) { return r.json(); }).then(function (a) {
    mState.record = a && a.ok ? a : null;
  }, function () { mState.record = null; });
}

function drawOpen() {
  var row = mRow(mState.open);
  hide(mOpenEl, !row);
  toggle(document.body, "is-open", !!row);
  if (!row) return;
  if (mState.shown !== row.repo) {
    mState.shown = row.repo;
    mReason.value = "";
    mMessage.value = "";
  }
  text(document.getElementById("oname"), row.repo);
  text(mOpenEl.querySelector(".says"), row.says || "");
  text(mOpenEl.querySelector(".lastsaid"), row.last_said || "");
  drawApproval(mState.record);
  drawAsks(row);
}

/** @param {Object} a */
function drawApproval(a) {
  hide(mApproval, !a);
  if (!a) return;
  setData(mApproval, "id", a.id);
  text(mApproval.querySelector(".summary"), a.summary || a.approval_kind || "");
  var p = a.payload_preview;
  text(mApproval.querySelector(".payload"), typeof p === "string" ? p : JSON.stringify(p, null, 2));
}

/** @param {Object} row */
function drawAsks(row) {
  var asks = row.questions || [];
  hide(mAsks, !asks.length);
  patchList(document.getElementById("asklist"), asks, function (x) { return x.id; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("mask"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (li, x) {
    text(li.querySelector(".q"), x.q);
    var input = /** @type {HTMLInputElement} */ (li.querySelector(".ask-answer"));
    attr(input, "placeholder", x["default"] || "your answer");
    patchList(li.querySelector(".ask-choices"), x.choices || [], function (c) { return c; }, function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ask-choice";
      b.addEventListener("click", function () { input.value = c; });
      return b;
    }, function (b, c) { text(b, c); });
  });
}

/** @param {string} what @param {Object} body */
function mPost(what, body) {
  text(mSaid, what + "…");
  return post(what, body).then(function (r) {
    text(mSaid, r.ok ? [r.action, r.decision || r.repo || r.id].filter(Boolean).join(" · ")
                     : r.error + (r.hint ? " — " + r.hint : ""));
    if (r.ok) {
      mState.record = null;
      if (what === "send") mMessage.value = "";
      else if (what !== "answer") mReason.value = "";
    }
    return mRefresh();
  }, function (e) { text(mSaid, String(e)); });
}

document.getElementById("approve").addEventListener("click", function () {
  mPost("approve", { id: mApproval.dataset.id, reason: mReason.value });
});
document.getElementById("deny").addEventListener("click", function () {
  mPost("deny", { id: mApproval.dataset.id, reason: mReason.value.trim() });
});
document.getElementById("send").addEventListener("click", function () {
  mPost("send", { repo: mState.open, message: mMessage.value });
});
document.getElementById("answer").addEventListener("click", function () {
  var answers = Array.prototype.map.call(document.getElementById("asklist").children, function (li) {
    return { id: li.dataset.rowkey, answer: /** @type {HTMLInputElement} */ (li.querySelector(".ask-answer")).value };
  });
  mPost("answer", { repo: mState.open, answers: answers });
});
document.getElementById("back").addEventListener("click", function () { mState.open = ""; drawAgents(); drawOpen(); });

function mRefresh() {
  mState.refreshes++;
  mState.reading++;
  var done = function () { mState.reading--; };
  return fetch(q("/api/attention")).then(function (r) { return r.json(); }).then(function (a) {
    if (!a || !a.ok) return;
    mState.rows = a.rows || [];
    if (mState.open && !mRow(mState.open)) mState.open = "";
    drawAgents();
    return mRead().then(drawOpen);
  }).then(done, function (e) { done(); throw e; });
}

function mSoon() {
  if (mState.timer) return;
  mState.timer = setTimeout(function () {
    mState.timer = null;
    mRefresh().catch(function () {});
  }, 400);
}

/** @param {string} state */
function mLiveAs(state) {
  mState.live = state;
  setClass(mLive, state === "live" ? "dot live" : "dot lost");
  text(mLive, state);
}

function mSince() {
  return Object.keys(mState.cursors).map(function (k) { return k + ":" + mState.cursors[k]; }).join(",");
}

function mConnect() {
  if (mState.source) mState.source.close();
  var params = { since: mSince(), w: W_NAME, page: "m", notify: "0" };
  if (PARAMS.get("shell")) params.shell = PARAMS.get("shell");
  var source = mState.source = new EventSource(q("/api/events", params));
  source.addEventListener("agent", function (m) {
    var at = String(/** @type {MessageEvent} */ (m).lastEventId || "").split(":");
    if (at.length === 2) mState.cursors[at[0]] = Number(at[1]);
    mState.frames++;
    mSoon();
  });
  source.addEventListener("polls", mSoon);
  source.addEventListener("desk", mSoon);
  source.addEventListener("theme", function (m) {
    try {
      var t = JSON.parse(/** @type {MessageEvent} */ (m).data);
      applyTheme(t.css, t.theme);
      applySkin(t.skin);
    } catch (err) {}
  });
  source.addEventListener("tick", function () { mState.ticks++; mLiveAs("live"); });
  source.onopen = function () { mLiveAs("live"); };
  source.onerror = function () {
    mLiveAs("reconnecting");
    source.close();
    if (mState.source !== source) return;
    mState.source = null;
    setTimeout(function () {
      var again = function () { if (!mState.source && !document.hidden) mConnect(); };
      mRefresh().then(again, again);
    }, 2000);
  };
}

document.addEventListener("visibilitychange", function () {
  if (mState.source) { mState.source.close(); mState.source = null; }
  if (document.visibilityState === "visible") mRefresh().then(mConnect, mConnect);
});

mRefresh().then(mConnect, function () {
  text(mSaid, "the fleet could not be read; reload to try again");
});

window.FleetPhone = Object.freeze({
  get w() { return W_NAME; },
  get rows() { return mState.rows; },
  get open() { return mState.open; },
  get stream() {
    return { frames: mState.frames, ticks: mState.ticks, state: mState.live, refreshes: mState.refreshes,
             busy: !!mState.timer || mState.reading > 0 };
  }
});
