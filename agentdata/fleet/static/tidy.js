"use strict";

var tidySays = document.getElementById("tidysays");
var tidySteps = document.getElementById("tidysteps");
var tidyCard = document.getElementById("tidycard");
var tidyDone = document.getElementById("tidydone");
var tidyApply = /** @type {HTMLButtonElement} */ (document.getElementById("tc-apply"));
var tidyLater = document.getElementById("tc-later");
var tidyMessage = /** @type {HTMLInputElement} */ (document.getElementById("tc-message"));
var tidyBranch = /** @type {HTMLInputElement} */ (document.getElementById("tc-branchname"));
var tidyResult = document.getElementById("tc-result");

/**
 * @typedef {Object} TidyTree
 * @property {string} repo
 * @property {string} branch
 * @property {number} step
 * @property {number} count
 * @property {string} plan_id
 * @property {string} recommended
 * @property {string} why
 * @property {string} message
 * @property {Array<Object>} options
 * @property {Array<Object>} files
 * @property {Array<Object>} overlaps
 * @property {Object} busy
 */

/** @type {Array<TidyTree>} */
var tidyTrees = [];
/** @type {Object<string, Object>} */
var tidyDid = {};
/** @type {Object<string, boolean>} */
var tidyLeft = {};
var tidyFirst = PARAMS.get("repo") || "";
/** @type {TidyTree | null} */
var tidyNow = null;
var tidyBusy = false;

var TIDY_DID = { commit: "committed", branch: "moved to a branch", stash: "stashed", skip: "left as it is",
                 nothing: "already clean" };

function tidyWord(tree) {
  var did = tidyDid[tree.repo];
  if (did) return TIDY_DID[did.did] || did.did;
  if (tidyLeft[tree.repo]) return "later";
  return tree.count + " uncommitted";
}

function tidyDrawSteps() {
  var rows = tidyTrees.map(function (t) { return t; });
  Object.keys(tidyDid).forEach(function (name) {
    if (!rows.some(function (t) { return t.repo === name; })) rows.push(/** @type {TidyTree} */ ({ repo: name, count: 0 }));
  });
  patchList(tidySteps, rows, function (t) { return t.repo; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("tidy-step"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (li, t) {
    text(li.querySelector(".ts-repo"), t.repo);
    text(li.querySelector(".ts-what"), tidyWord(t));
    toggle(li, "is-now", !!tidyNow && tidyNow.repo === t.repo);
    toggle(li, "is-done", !!tidyDid[t.repo]);
    attr(li, "aria-current", tidyNow && tidyNow.repo === t.repo ? "step" : null);
  });
}

function tidyNext() {
  var open = tidyTrees.filter(function (t) { return !tidyDid[t.repo] && !tidyLeft[t.repo]; });
  if (tidyFirst) {
    var wanted = open.filter(function (t) { return t.repo === tidyFirst; })[0];
    tidyFirst = "";
    if (wanted) return wanted;
  }
  return open[0] || null;
}

function tidyOption(o, tree) {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("tidy-option"));
  var label = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  var input = /** @type {HTMLInputElement} */ (label.querySelector("input"));
  input.value = o.choice;
  input.checked = o.choice === tree.recommended;
  text(label.querySelector(".tc-opt-label"), o.label);
  hide(label.querySelector(".tc-rec"), o.choice !== tree.recommended);
  attr(label, "title", o.undo ? "to undo it later: " + o.undo : null);
  input.addEventListener("change", tidyRows);
  return label;
}

function tidyChoice() {
  var on = /** @type {HTMLInputElement | null} */ (tidyCard.querySelector("input[name=tc-choice]:checked"));
  return on ? on.value : "";
}

function tidyRows() {
  var choice = tidyChoice();
  hide(document.getElementById("tc-msgrow"), choice !== "commit" && choice !== "branch");
  hide(document.getElementById("tc-branchrow"), choice !== "branch");
  text(tidyApply, choice === "skip" ? "leave it" : "do it");
}

function tidyLine(ul, words) {
  var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("tidy-line"));
  var li = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  text(li.querySelector("code"), words);
  ul.appendChild(li);
}

function tidyDebt(d) {
  var p = d.parts || {};
  return "debt " + d.score + " (behind " + p.behind + ", age " + p.age + ", carries " + p.carries
    + (p.untracked ? ", no ticket " + p.untracked : "") + (p.protected ? ", protected " + p.protected : "") + ")";
}

function tidyClear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function tidyDraw() {
  tidyDrawSteps();
  if (!tidyNow) {
    hide(tidyCard, true);
    tidyDrawDone();
    return;
  }
  var t = tidyNow;
  hide(tidyDone, true);
  hide(tidyCard, false);
  text(document.getElementById("tc-step"), "Tree " + t.step + " of " + tidyTrees.length + ":");
  text(document.getElementById("tc-repo"), t.repo);
  text(document.getElementById("tc-branch"), t.branch || "a detached HEAD");
  text(document.getElementById("tc-says"),
       t.count + " uncommitted file" + (t.count === 1 ? "" : "s") + ". " + t.why + ".");
  text(document.getElementById("tc-filesn"), "the files (" + t.count + ")");
  var files = document.getElementById("tc-filelist");
  tidyClear(files);
  (t.files || []).forEach(function (f) { tidyLine(files, f.state + "  " + f.path); });
  var overlaps = document.getElementById("tc-overlaps");
  tidyClear(overlaps);
  var shared = (t.overlaps || []).length > 0;
  if (shared && t.debt) tidyLine(overlaps, "here, " + (t.branch || "a detached HEAD") + ": " + tidyDebt(t.debt));
  (t.overlaps || []).forEach(function (o) {
    tidyLine(overlaps, o.where + ": " + o.shared + " shared file" + (o.shared === 1 ? "" : "s")
             + " · " + tidyDebt(o.debt));
  });
  hide(overlaps, !shared);
  hide(document.getElementById("tc-overlapsn"), !shared);
  var options = document.getElementById("tc-options");
  Array.prototype.slice.call(options.querySelectorAll(".tc-opt")).forEach(function (el) { options.removeChild(el); });
  (t.options || []).forEach(function (o) { options.appendChild(tidyOption(o, t)); });
  tidyMessage.value = t.message || "";
  var branchOption = (t.options || []).filter(function (o) { return o.choice === "branch"; })[0];
  tidyBranch.value = branchOption ? branchOption.branch : "";
  text(tidyResult, t.busy && t.busy.kind ? "its agent is running: this tree waits until its turn ends" : "");
  disable(tidyApply, false);
  tidyRows();
}

function tidyDrawDone() {
  hide(tidyDone, false);
  var names = Object.keys(tidyDid);
  var later = tidyTrees.filter(function (t) { return tidyLeft[t.repo] && !tidyDid[t.repo]; });
  text(document.getElementById("td-head"),
       !tidyTrees.length && !names.length ? "Every working tree is clean."
         : "Done: " + names.length + " tree" + (names.length === 1 ? "" : "s") + " handled"
           + (later.length ? ", " + later.length + " left for later" : "") + ".");
  var list = document.getElementById("td-list");
  tidyClear(list);
  names.forEach(function (name) {
    var d = tidyDid[name];
    tidyLine(list, name + ": " + (TIDY_DID[d.did] || d.did)
             + (d.commit ? " " + d.commit : "") + (d.branch && d.did === "branch" ? " on " + d.branch : "")
             + (d.undo ? "  · undo: " + d.undo : ""));
  });
}

function tidyShow(data) {
  tidyTrees = (data && data.trees) || [];
  text(tidySays, (data && data.says) || "");
  var still = tidyNow && tidyTrees.filter(function (t) { return t.repo === tidyNow.repo && !tidyDid[t.repo]; })[0];
  tidyNow = still || tidyNext();
  tidyDraw();
}

function tidyLoad() {
  return fetch(q("/api/tidy")).then(function (r) { return r.json(); }).then(tidyShow, function () {
    text(tidySays, "the trees could not be read; look again in a moment");
  });
}

function tidyGo() {
  if (!tidyNow || tidyBusy) return;
  var t = tidyNow;
  var choice = tidyChoice();
  if (!choice) return;
  tidyBusy = true;
  disable(tidyApply, true);
  text(tidyResult, "working on " + t.repo + "…");
  post("tidy", { repo: t.repo, plan_id: t.plan_id, choice: choice, message: tidyMessage.value,
                 branch: tidyBranch.value }).then(function (r) {
    tidyBusy = false;
    if (!r || r.ok === false) {
      disable(tidyApply, false);
      var said = (r && r.error ? r.error : "refused") + (r && r.hint ? " — " + r.hint : "");
      text(tidyResult, said);
      if (r && r.code === "changed") return tidyLoad().then(function () { text(tidyResult, said); });
      return null;
    }
    tidyDid[t.repo] = r.done;
    tidyNow = null;
    return tidyLoad();
  }, function () {
    tidyBusy = false;
    disable(tidyApply, false);
    text(tidyResult, "the server did not answer; nothing is known to have changed — look again");
  });
}

tidyApply.addEventListener("click", tidyGo);
tidyLater.addEventListener("click", function () {
  if (!tidyNow) return;
  tidyLeft[tidyNow.repo] = true;
  tidyNow = tidyNext();
  tidyDraw();
});
document.getElementById("tidyagain").addEventListener("click", function () {
  tidyLeft = {};
  tidyLoad();
});

tidyLoad();
