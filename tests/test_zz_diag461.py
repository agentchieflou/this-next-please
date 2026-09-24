"""DIAGNOSTIC ONLY, for #461 -- never to be merged. It runs the two scenarios of
tests/test_fleet_ink_rules.py that fail on the Windows 3.14 leg, three times each, records what the
layer and the page did, and fails on purpose so that the record reaches the CI log."""
from __future__ import annotations

import json

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import AT_REST, _open, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until_class
from test_fleet_ink_rules import BUILDS, CARD, LONG, MEASURE, SETTLE, SHORT, _desk, _look, _rules

#: Every box the long pane's transcript takes, sampled on each animation frame AND in a
#: ResizeObserver callback (after layout, where the layer's `now()` measures), with the build count
#: at that moment and where the sample came from.
WATCH2 = """(repo) => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`), pane = list.closest('.tile');
  const seen = window.__seen = [];
  const box = (src) => {
    if (window.__seen !== seen) return;
    const r = list.getBoundingClientRect(), p = pane.getBoundingClientRect();
    const s = p.width.toFixed(1) + 'x' + p.height.toFixed(1) + '@' + (r.top - p.top).toFixed(1) + '+' + r.height.toFixed(1);
    const b = window.__rules.inspect().builds;
    const last = seen[seen.length - 1];
    if (!last || last[1] !== s || last[2] !== b) seen.push([src, s, b, Math.round(performance.now()),
      pane.querySelector('.head').getBoundingClientRect().height.toFixed(1), pane.className]);
  };
  const ro = new ResizeObserver(() => box('ro'));
  for (const el of [list, pane, ...pane.children]) ro.observe(el);
  window.__ro = ro;
  const frame = () => { if (window.__seen !== seen) return; box('raf'); requestAnimationFrame(frame); };
  frame();
  new MutationObserver(() => box('mo')).observe(document.documentElement, { attributes: true });
}"""
STOP2 = "() => { const s = window.__seen; window.__seen = null; window.__ro.disconnect(); return s; }"

#: What is over the top of a transcript: every element in its pane whose box reaches into the
#: transcript's top 40px, and what is at a few points there.
OVER = """(repo) => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`), pane = list.closest('.tile');
  const b = list.getBoundingClientRect(), out = [];
  for (const el of pane.querySelectorAll('*')) {
    if (list.contains(el) || el === list) continue;
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.bottom > b.top && r.top < b.top + 40 && r.right > b.left && r.left < b.right)
      out.push([el.tagName.toLowerCase() + '.' + [...el.classList].join('.'), Math.round(r.top), Math.round(r.bottom),
                getComputedStyle(el).visibility]);
  }
  const at = [];
  for (const dy of [2, 10, 18, 26, 34]) {
    const e = document.elementFromPoint(b.left + b.width / 3, b.top + dy);
    at.push([dy, e ? e.tagName.toLowerCase() + '.' + [...e.classList].join('.') : null]);
  }
  const li = [...list.children].map(x => [Math.round(x.getBoundingClientRect().top), getComputedStyle(x).color,
    x.getAnimations({ subtree: true }).length]).filter(x => x[0] > b.top - 60 && x[0] < b.top + 60);
  return { box: [b.top, b.bottom], over: out, at, li, fonts: document.fonts.status,
           hand: getComputedStyle(pane).getPropertyValue('--hand') };
}"""


@pytest.mark.browser
def test_diag461(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path)
    server, token, port = _serve()
    record = []
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            record.append(["browser", browser.version])
            for attempt in range(3):
                page, errors, _ = _open(browser, port, token, "&ink=on", panes=2, width=1400, reduced=True)
                _look(page, "notebook:light")
                for repo in (LONG, SHORT):
                    m = page.evaluate(MEASURE, repo)
                    rules = _rules(page, m["box"])
                    bad = []
                    for g in m["lines"]:
                        third = (g["bottom"] - g["top"]) / 3
                        if [r for r in rules if g["top"] + third <= r + 0.5 <= g["bottom"] - third] \
                                or not [r for r in rules if 2 <= r - g["bottom"] <= 6]:
                            bad.append(g)
                    record.append(["rules", attempt, repo, m["box"], m["scroll"], rules[:12], bad[:3],
                                   page.evaluate(OVER, repo) if bad else None])
                for event, on in (
                        (("question_opened", {"question": "which window should this land in?", "id": f"q{attempt}",
                                              "blocking": True, "choices": ["left", "right"]}), True),
                        (("question_answered", {"id": f"q{attempt}", "question": "which window should this land in?"}), False)):
                    before = page.evaluate(BUILDS)
                    page.evaluate(WATCH2, LONG)
                    _emit(page, LONG, event)
                    _until_class(page, LONG, "needs-human", on)
                    page.wait_for_function(CARD, arg=[LONG, on], timeout=15000, polling=250)
                    page.evaluate(SETTLE, LONG)
                    page.wait_for_function(AT_REST, timeout=20000)
                    seen = page.evaluate(STOP2)
                    record.append(["card", attempt, on, page.evaluate(BUILDS) - before, seen])
                page.close()
            browser.close()
    finally:
        _stop(server)
    pytest.fail("DIAG461 " + "\nDIAG461 ".join(json.dumps(r) for r in record))
