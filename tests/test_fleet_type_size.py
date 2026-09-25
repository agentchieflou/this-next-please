"""No word on the desk or the settings page is set under 11px (#326, HIG *Typography*).

`docs/plan-desk-refactor.md` (the HIG table) asks for "a minimum of 11 points", and its "Where it
lands" cell promised "the 10-point chips grow". At 8557b2b `app.css` still set 10px on thirteen
rules and 9px on the pin glyph, four of them muted labels as well, so both small and faint.

* statically: every `font-size`, and the size in every `font` shorthand, in `app.css` and in every
  skin's `skin.css` is 11px or more. `em`, `rem` and `%` count against a 16px root; a keyword size
  (`smaller`, `x-small`) fails, naming its selector. `inherit` and the other wide keywords set no
  size of their own, and pass;
* in a browser: the grown words still fit where they are set -- a rail's number, glyph and unread
  badge inside its 48px face, and a pane's chip and a ticket's status inside their own boxes -- at
  1400x900 and 700x900, on the plain look and on glass:smoke.
"""
from __future__ import annotations

import glob
import os
import re
import threading
import time

import pytest

from agentdata.fleet import board as B, events as E, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_events import fleet_home  # noqa: F401 - fixture
from test_fleet_skin_guard import rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
SHEETS = [os.path.join(STATIC, "app.css")] + sorted(glob.glob(os.path.join(STATIC, "skins", "*", "skin.css")))

#: The HIG floor, in CSS px.
FLOOR = 11.0
ROOT_PX = 16.0

#: A size with a unit this test can reckon in px.
SIZE = re.compile(r"^(\d*\.?\d+)(px|em|rem|%)$")
#: The absolute and relative size keywords: never allowed, since nothing pins what they come to.
KEYWORDS = {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large", "xxx-large",
            "smaller", "larger", "math"}
#: The wide keywords set no size of their own.
WIDE = {"inherit", "initial", "unset", "revert", "revert-layer"}
#: The `font` shorthand's system fonts: a size the platform picks.
SYSTEM = {"caption", "icon", "menu", "message-box", "small-caption", "status-bar"}


def _px(token: str) -> float | None:
    m = SIZE.match(token)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return n if unit == "px" else n * ROOT_PX / (100.0 if unit == "%" else 1.0)


def _shorthand_size(value: str) -> str | None:
    """The size in a `font` shorthand: the token before the family, `12px` in `600 12px/1 var(--mono)`.
    None when the shorthand is a wide keyword (it sets no size)."""
    value = re.sub(r"\s*!important\s*$", "", value.strip())
    if value in WIDE:
        return None
    for token in value.replace("/", " / ").split():
        if token == "/":
            break
        if SIZE.match(token) or token in KEYWORDS or token in SYSTEM:
            return token
    return value  # no size found: reported as it is


def small_sizes(css: str) -> list[str]:
    """Every declaration that sets a size under the floor, or one this test cannot reckon."""
    bad = []
    for selector, prop, value in rules(css):
        if prop == "font-size":
            token = re.sub(r"\s*!important\s*$", "", value.strip())
            if token in WIDE:
                continue
        elif prop == "font":
            token = _shorthand_size(value)
            if token is None:
                continue
        else:
            continue
        px = _px(token)
        if px is None or px < FLOOR:
            bad.append(f"{selector} {{ {prop}: {value} }}" + ("" if px is None else f" -> {px:g}px"))
    return bad


def test_the_size_reader_knows_a_small_size_when_it_sees_one():
    """The reader itself: a rule it passed would pass the guard too."""
    assert small_sizes(".a { font-size: 10px; }") == [".a { font-size: 10px } -> 10px"]
    assert small_sizes(".a { font: 600 10px/1 var(--mono); }") == [".a { font: 600 10px/1 var(--mono) } -> 10px"]
    assert small_sizes(".a { font-size: .6rem; }") == [".a { font-size: .6rem } -> 9.6px"]
    assert small_sizes(".a { font-size: 60%; }") == [".a { font-size: 60% } -> 9.6px"]
    assert small_sizes(".a { font-size: x-small; }") == [".a { font-size: x-small }"]
    assert small_sizes(".a { font: smaller var(--ui); }") == [".a { font: smaller var(--ui) }"]
    assert small_sizes("@media (max-width: 700px) { .a { font-size: 9px } }") == [".a { font-size: 9px } -> 9px"]
    assert small_sizes(".a { font: inherit; font-size: 11px; } .b { font: 12px/1.4 var(--ui) }") == []
    assert small_sizes(".a { font-size: .75em; }") == []


@pytest.mark.parametrize("sheet", SHEETS, ids=[os.path.relpath(s, STATIC) for s in SHEETS])
def test_no_font_size_under_11px(sheet):
    """HIG *Typography*: 11 points at least, for every word the page sets, on every look."""
    with open(sheet, encoding="utf-8") as fh:
        bad = small_sizes(fh.read())
    assert not bad, f"{os.path.relpath(sheet, STATIC)} sets text under {FLOOR:g}px:\n  " + "\n  ".join(bad)


# ================================================================================ in a browser

NAMES = ("alpha", "beta", "gamma", "delta", "epsilon")
RAILED = ("delta", "epsilon")


def _desk(tmp_path):
    """Five agents, three of them panes with a width and two of them rails, and a board with a
    ticket in progress on it (the board cache is the seam: Jira is never reached)."""
    for name in NAMES:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    S.arrange(order=list(NAMES))
    S.update_window("main", open="alpha", widths={n: (0 if n in RAILED else 1) for n in NAMES})
    B.write_cache({"jql": B.DEFAULT_JQL, "fetched_at": time.time(), "rows": [
        {"key": "RDSD-118", "summary": "UAT refresh is slow", "status": "In Progress",
         "category": "indeterminate"},
        {"key": "RDSD-119", "summary": "Retire the old export", "status": "To Do", "category": "new"}]})


def _serve():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


#: The rails' faces: each part's right edge against the face's, and whether it shows.
RAIL_FACES = """() => [...document.querySelectorAll('#grid .tile[data-tier="rail"] .pane-rail')].map(f => {
  const face = f.getBoundingClientRect();
  const part = sel => { const el = f.querySelector(sel), r = el.getBoundingClientRect();
    return { right: r.right, left: r.left, shown: r.width > 0 && getComputedStyle(el).display !== 'none',
             text: el.textContent }; };
  return { repo: f.closest('.tile').dataset.repo, left: face.left, right: face.right,
           n: part('.pr-n'), glyph: part('.pr-glyph'), badge: part('.pr-badge') };
})"""

#: Words that must not overflow their own box: a pane's chip and a ticket's status.
OVERFLOW = """sel => [...document.querySelectorAll(sel)].filter(el => el.getClientRects().length)
  .map(el => ({ what: sel, text: el.textContent.trim(), scroll: el.scrollWidth, client: el.clientWidth,
                size: parseFloat(getComputedStyle(el).fontSize) }))"""


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["none", "glass:smoke"])
@pytest.mark.parametrize("width", [1400, 700])
def test_the_grown_words_still_fit_the_rail_the_chip_and_the_board(fleet_home, tmp_path, width, skin):
    """At 11px the rail's number, its state glyph and its unread badge stay inside the 48px face,
    and a pane's chip and a ticket's status are not clipped by their own box."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile[data-tier="rail"]').length >= 2
                     && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
                     && !document.body.classList.contains('is-stale')""", timeout=15000)
            if skin != "none":
                page.evaluate("s => post('theme', { skin: s })", skin)
                family, variant = skin.split(":")
                page.wait_for_function(
                    """([f, v]) => document.body.dataset.skin === f && document.body.dataset.skinVariant === v
                         && !!(document.head.querySelector('link[data-skin]') || {}).sheet""",
                    arg=[family, variant], timeout=15000)
            # Unread notes on the rails, so each badge shows a two-digit count: its widest.
            page.evaluate("""names => names.forEach(repo => { for (let i = 0; i < 12; i++)
                arrived({ repo, severity: 'info', title: 'note', body: '', at: '' }); })""", list(RAILED))
            page.wait_for_function(
                """names => names.every(r => {
                     const b = document.querySelector(`.tile[data-repo="${r}"] .pr-badge`);
                     return b && !b.hidden && b.textContent === '12'; })""", arg=list(RAILED), timeout=15000)
            faces = page.evaluate(RAIL_FACES)
            chips = page.evaluate(OVERFLOW, "#grid .tile .head .chip")
            page.evaluate("() => boardPanel(true)")
            page.wait_for_selector("#tickets li[data-key='RDSD-118'] .st", timeout=15000)
            statuses = page.evaluate(OVERFLOW, "#tickets .st")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    railed = {f["repo"]: f for f in faces}
    assert set(RAILED) <= set(railed), faces
    for f in faces:
        for part in ("n", "glyph", "badge"):
            got = f[part]
            if not got["shown"]:
                continue
            assert got["left"] >= f["left"] - 0.5 and got["right"] <= f["right"] + 0.5, \
                f"{skin} at {width}px: the rail {f['repo']}'s .pr-{part} '{got['text']}' leaves its face: {got} vs {f}"
    for repo in RAILED:
        assert railed[repo]["badge"]["shown"] and railed[repo]["n"]["shown"], railed[repo]
    assert chips, "no chip on the glass"
    assert {s["text"] for s in statuses} >= {"In Progress", "To Do"}, statuses
    for word in chips + statuses:
        assert word["size"] >= FLOOR, f"{skin} at {width}px: {word}"
        assert word["scroll"] <= word["client"], f"{skin} at {width}px: clipped in its own box: {word}"
