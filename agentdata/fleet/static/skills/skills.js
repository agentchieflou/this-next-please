"use strict";

var skBack = document.getElementById("backbtn");
if (skBack) skBack.href = pageUrl("/settings");
var skDesk = document.getElementById("deskbtn");
if (skDesk) skDesk.href = pageUrl("/");
var skQuery = /** @type {HTMLInputElement} */ (document.getElementById("skillq"));
var skRows = document.getElementById("skillrows");
var skLine = document.getElementById("skillsline");
var skNone = document.getElementById("skillsnone");
var skHead = document.querySelector(".sk-head");
var skSrc = document.getElementById("sksrc");
var skSrcKind = document.getElementById("sksrckind");
var skSynced = document.getElementById("sksynced");
var skSync = /** @type {HTMLButtonElement} */ (document.getElementById("sksync"));
var skRefresh = /** @type {HTMLButtonElement} */ (document.getElementById("skrefresh"));
var skSettings = document.getElementById("sksettings");
var skSyncLine = document.getElementById("sksyncline");
var skNew = document.getElementById("sknew");
var skNewRows = document.getElementById("sknewrows");
if (skSettings) skSettings.href = pageUrl("/settings") + "#cfg-fleet-skills-source";

/**
 * @typedef {Object} SkillRepo
 * @property {string} repo
 * @property {number} uses
 * @property {string} last
 */
/**
 * @typedef {Object} SkillRow
 * @property {string} name
 * @property {string} description
 * @property {string} dir
 * @property {string} version
 * @property {string|null} installed
 * @property {string} shadowed_by
 * @property {boolean} missing
 * @property {boolean} unused
 * @property {boolean} ours
 * @property {number} uses
 * @property {number} ok
 * @property {number} failed
 * @property {string} first
 * @property {string} last
 * @property {Array<SkillRepo>} repos
 * @property {Array<string>} tickets
 * @property {{fleet: number, copilot: number}} sources
 */

var skState = {
  /** @type {Array<SkillRow>} */ rows: [],
  /** @type {Object} */ totals: null,
  /** @type {Object} */ source: null,
  /** @type {Object} */ sync: null,
  /** @type {Array<Object>} */ notInstalled: [],
  sort: "uses", dir: -1, q: "",
  /** @type {Object<string, boolean>} */ open: {},
  failed: false, busy: false, said: ""
};
var SK_POLL_MS = 30000;
var SK_SYNC_POLL_MS = 2000;
var SK_TOP = 3;

/** @param {SkillRow} r @returns {string} */
function skKey(r) { return r.shadowed_by ? r.name + "@" + r.dir : r.name; }

/** @param {string} iso @returns {string} */
function skAgo(iso) {
  if (!iso) return "never";
  var t = Date.parse(iso.length > 19 ? iso : iso + "Z");
  if (isNaN(t)) return iso;
  var s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  var d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : d + " days ago";
}

/** @param {Array<SkillRepo>} repos @returns {string} */
function skTop(repos) {
  if (!repos || !repos.length) return "";
  var names = repos.slice(0, SK_TOP).map(function (r) { return r.repo; }).join(", ");
  return repos.length > SK_TOP ? names + " +" + (repos.length - SK_TOP) : names;
}

/** @returns {Array<SkillRow>} */
function skSorted() {
  var q = skState.q.toLowerCase();
  var rows = skState.rows.filter(function (r) {
    return !q || (r.name + " " + r.description + " " + r.dir + " " + skTop(r.repos)).toLowerCase().indexOf(q) >= 0;
  });
  var key = skState.sort, dir = skState.dir;
  rows.sort(function (a, b) {
    var x, y;
    if (key === "name") { x = a.name; y = b.name; }
    else if (key === "last") { x = a.last || ""; y = b.last || ""; }
    else { x = a.uses; y = b.uses; }
    if (x < y) return -dir;
    if (x > y) return dir;
    return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
  });
  return rows;
}

/** @param {HTMLElement} li */
function skToggle(li) {
  var k = li.dataset.rowkey;
  skState.open[k] = !skState.open[k];
  drawSkills();
}

/** @returns {HTMLElement} */
function skCreate() {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("skillrow"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  var row = li.querySelector(".sk-row");
  row.addEventListener("click", function () { skToggle(li); });
  row.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); skToggle(li); }
  });
  return li;
}

/** @param {HTMLElement} li @param {SkillRow} r */
function drawSkillRepos(li, r) {
  patchList(li.querySelector(".sk-repolist"), r.repos || [], function (x) { return x.repo; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("skillrepo"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (el, x) {
    text(el.querySelector(".sk-r-name"), x.repo);
    text(el.querySelector(".sk-r-uses"), x.uses + (x.uses === 1 ? " use" : " uses"));
    text(el.querySelector(".sk-r-last"), skAgo(x.last));
    attr(el.querySelector(".sk-r-last"), "title", x.last || null);
  });
}

/** @param {HTMLElement} li @param {SkillRow} r */
function drawSkill(li, r) {
  var open = !!skState.open[skKey(r)];
  var row = li.querySelector(".sk-row");
  setClass(li, "sk" + (open ? " is-open" : "") + (r.unused ? " is-unused" : "") + (r.missing ? " is-missing" : ""));
  attr(row, "aria-expanded", open ? "true" : "false");
  text(li.querySelector(".sk-n"), r.name);
  hide(li.querySelector(".sk-unused"), !r.unused);
  hide(li.querySelector(".sk-missing"), !r.missing);
  var shadowed = li.querySelector(".sk-shadowed");
  hide(shadowed, !r.shadowed_by);
  attr(shadowed, "title", r.shadowed_by ? "not read: " + r.shadowed_by + " has a skill of this name first" : null);
  var desc = li.querySelector(".sk-desc");
  text(desc, r.missing ? "used, but no longer installed" : r.description);
  attr(desc, "title", r.description || null);
  text(li.querySelector(".sk-uses"), r.uses);
  var last = li.querySelector(".sk-last");
  text(last, skAgo(r.last));
  attr(last, "title", r.last || null);
  var repos = li.querySelector(".sk-repos");
  text(repos, skTop(r.repos));
  attr(repos, "title", (r.repos || []).map(function (x) { return x.repo + " (" + x.uses + ")"; }).join(", ") || null);
  text(li.querySelector(".sk-okf"), r.uses ? r.ok + " / " + r.failed : "");
  var ver = li.querySelector(".sk-ver");
  text(ver, r.version);
  attr(ver, "title", r.installed ? "installed " + r.installed : null);
  text(li.querySelector(".sk-dir"), r.dir);
  var more = li.querySelector(".sk-more");
  hide(more, !open);
  if (!open) return;
  var facts = [];
  if (r.uses) {
    facts.push("first used " + skAgo(r.first) + ", last " + skAgo(r.last));
    facts.push(r.sources.fleet + " by fleet agents, " + r.sources.copilot + " in your own Copilot sessions");
  } else facts.push(r.missing ? "" : "never used");
  if (r.installed) facts.push("installed " + skAgo(r.installed) + " in " + r.dir + (r.ours ? " (this project's)" : ""));
  text(li.querySelector(".sk-facts"), facts.filter(Boolean).join(" · "));
  drawSkillRepos(li, r);
  text(li.querySelector(".sk-tickets"), r.tickets && r.tickets.length ? "tickets: " + r.tickets.slice().reverse().join(", ") : "");
}

/** @param {Object} r @returns {string} */
function skSyncWords(r) {
  if (!r || !r.finished) return "";
  if (r.error) return "sync failed: " + r.error + (r.hint ? " \u2014 " + r.hint : "");
  var parts = [r.added.length + " added", r.updated.length + " updated", r.removed.length + " removed",
               r.unchanged.length + " unchanged"];
  if (r.skipped && r.skipped.length) parts.push(r.skipped.length + " left alone");
  return "synced " + skAgo(r.finished) + ": " + parts.join(", ");
}

function drawSource() {
  var src = skState.source, last = skState.sync;
  if (!src) return;
  text(skSrc, src.value);
  text(skSrcKind, src.kind || "not a marketplace");
  var running = !!(last && last.running);
  text(skSynced, running ? "syncing\u2026" : last && last.finished
    ? "last synced " + skAgo(last.finished) + " from " + last.source + (last.commit ? " @ " + last.commit : "")
      + (last.ok ? "" : " (failed)")
    : "never synced");
  attr(skSynced, "title", last && last.finished ? last.finished : null);
  disable(skSync, running || skState.busy || !src.kind);
  disable(skRefresh, running || skState.busy || !src.kind);
  text(skSyncLine, skState.said || (running ? "" : skSyncWords(last)));
  var rows = skState.notInstalled || [];
  hide(skNew, !rows.length);
  patchList(skNewRows, rows, function (x) { return x.name; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("sknewrow"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (el, x) {
    text(el.querySelector(".sk-n"), x.name);
    text(el.querySelector(".sk-desc"), x.description);
  });
}

function drawSkills() {
  drawSource();
  var rows = skSorted();
  patchList(skRows, rows, skKey, skCreate, drawSkill);
  hide(skNone, skState.rows.length > 0 || skState.failed);
  var t = skState.totals;
  if (skState.failed) text(skLine, "skills: unavailable");
  else if (t) {
    text(skLine, t.skills + " skills installed, " + t.used + " used, " + t.unused + " never" +
      (t.missing ? ", " + t.missing + " used but gone" : "") +
      " · " + t.uses + " uses in all" + (skState.q ? " · " + rows.length + " shown" : ""));
  }
  if (skHead) {
    Array.prototype.forEach.call(skHead.querySelectorAll(".sk-sort"), function (b) {
      var mine = b.dataset.sort === skState.sort;
      attr(b, "aria-sort", mine ? (skState.dir < 0 ? "descending" : "ascending") : null);
    });
  }
}

/** @param {Object} d */
function skTake(d) {
  skState.rows = d.skills || [];
  skState.totals = d.totals || null;
  skState.source = d.source || null;
  skState.sync = d.sync || null;
  skState.notInstalled = d.not_installed || [];
  skState.failed = false;
}

function skLoad() {
  return fetch(q("/api/skills")).then(function (r) { return r.json(); }).then(function (d) {
    if (!d || d.ok === false) throw new Error("no");
    skTake(d);
    drawSkills();
    if (d.sync && d.sync.running) setTimeout(skLoad, SK_SYNC_POLL_MS);
  }).catch(function () {
    skState.failed = true;
    drawSkills();
  });
}

/** @param {string} what */
function skPost(what) {
  skState.busy = true;
  skState.said = what === "skills-sync" ? "starting\u2026" : "reading the marketplace\u2026";
  drawSkills();
  return post(what, {}).then(function (res) {
    skState.busy = false;
    if (!res || res.ok === false) {
      skState.said = (res && res.error) || "no answer";
      drawSkills();
      return;
    }
    skState.said = "";
    if (res.skills) { skTake(res); drawSkills(); }
    else skLoad();
  });
}

if (skSync) skSync.addEventListener("click", function () { skPost("skills-sync"); });
if (skRefresh) skRefresh.addEventListener("click", function () { skPost("skills-refresh"); });

if (skHead) {
  skHead.addEventListener("click", function (e) {
    var b = /** @type {HTMLElement} */ (e.target).closest(".sk-sort");
    if (!b) return;
    var key = b.dataset.sort;
    if (skState.sort === key) skState.dir = -skState.dir;
    else { skState.sort = key; skState.dir = key === "name" ? 1 : -1; }
    drawSkills();
  });
}
if (skQuery) {
  skQuery.addEventListener("input", function () { skState.q = skQuery.value.trim(); drawSkills(); });
}
setInterval(function () { if (document.visibilityState === "visible") skLoad(); }, SK_POLL_MS);
document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") skLoad(); });
skLoad();

window.FleetSkills = Object.freeze({
  get rows() { return skState.rows; },
  get totals() { return skState.totals; },
  get sync() { return skState.sync; },
  load: skLoad,
  draw: drawSkills
});
