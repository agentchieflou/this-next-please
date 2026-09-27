"""Every agent a pane: the row, the three tiers, the band retired (issue #233, slice D of #229).

The operator's sentence (docs/plan-panes.md §Decisions 3): *I meant each agent is a column, not each
agent is stacked in one column. I'm thinking skinnier agents.* So every agent is a `.tile` in one
row, and what a pane draws is decided by its own width -- a 48px **rail**, a **compact** pane from
160px, a **full** one from 360px -- written as `data-tier` by one `ResizeObserver` with 8px of
hysteresis. What is asserted here:

* the fixture desk -- 3, 6 and 12 agents at 1280, 1920 and 2560px -- never scrolls sideways, every
  pane is in the tier its width says, the rail of an agent that needs a person is red AND wears a
  glyph, and every rail carries an `aria-label` with its age and its last line;
* a desk with nothing new to say makes no DOM mutation at all, over the whole document, while the
  stream runs and every draw path is driven by hand (the ownership proof);
* the tiers keep their 8px of slack, a pane that widens draws what its narrower tier skipped, and
  when even the rails do not fit a project's checkouts share one rail rather than the row scrolling.

The column's own tests are ported, not deleted: `tests/test_fleet_column.py` asserts the swap, the
keys, the hidden count and the red that nothing reorders, of the row.
"""
from __future__ import annotations
import os
import re
import threading
import time

import pytest

from agentdata import textio
from agentdata.fleet import approval, events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from desk_harness import close_pages
from test_fleet import make_project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")

RAIL_PX = 48
COMPACT_FROM = 160
FULL_FROM = 360


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _repos(tmp_path, names, *, needs=(), projects=None):
    """Agents that have each said one thing, and -- for `needs` -- asked one question."""
    for name in names:
        project = (projects or {}).get(name)
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name, project=project)
        events = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                  E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                  E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
        if name in needs:
            events.append(E.event(name, "question_opened",
                                  {"question": "which window should " + name + " land in?",
                                   "id": "q1", "blocking": True}, ticket="RDSD-1"))
        E.append(name, events)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _page(browser, port, token, width, height=900):
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
    # What is meant, not the first `.tile` in the DOM: an open pane that has its tier.
    page.wait_for_selector('.tile.is-solo[data-tier="full"], .tile.is-solo[data-tier="compact"]',
                           timeout=15000)
    return page, errors


# What a rail's face, a pane's tier and the row itself read as, in one pass.
READ_ROW = """() => {
  const probe = document.createElement('i');
  probe.style.color = 'var(--human)';
  document.body.appendChild(probe);
  const human = getComputedStyle(probe).color;
  probe.remove();
  const row = document.getElementById('grid');
  const glass = document.documentElement;
  const panes = [...row.querySelectorAll('.tile:not(.is-hidden):not(.is-grouped)')];
  return {
    human: human,
    scroll: { page: [glass.scrollWidth, glass.clientWidth],
              row: [row.scrollWidth, row.clientWidth] },
    panes: panes.map(t => {
      const face = t.querySelector('.pane-rail');
      const box = t.getBoundingClientRect();
      const shown = el => !!el && el.getBoundingClientRect().width > 0 &&
                          getComputedStyle(el).display !== 'none';
      return {
        repo: t.dataset.repo, tier: t.dataset.tier || '', open: t.classList.contains('is-solo'),
        width: box.width, left: box.left, right: box.right,
        face: {
          shown: shown(face), tag: face.tagName,
          red: face.classList.contains('needs-human'),
          background: getComputedStyle(face).backgroundColor,
          glyph: face.querySelector('.pr-glyph').textContent,
          name: face.querySelector('.pr-name').textContent,
          label: face.getAttribute('aria-label') || '',
          title: face.getAttribute('title') || '',
        },
        head: shown(t.querySelector('.head')),
        tools: [...t.querySelectorAll('.head [data-tool]')].filter(shown)
                 .map(b => b.dataset.tool),
        runline: shown(t.querySelector('.runline')),
        say: shown(t.querySelector('.say')),
        transcript: shown(t.querySelector('.transcript')),
      };
    }),
  };
}"""


def _tier_of(width: float) -> str:
    return "full" if width >= FULL_FROM else "compact" if width >= COMPACT_FROM else "rail"


# ------------------------------------------------------------------------ the fixture desk


# Which agents are pinned open beside the open one, per desk size: enough for twelve agents at
# 1280px to put the open panes in the compact tier, and every other size in the full one.
PINS = {3: [], 6: ["r01"], 12: ["r01", "r02"]}


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 1920, 2560])
@pytest.mark.parametrize("agents", [3, 6, 12])
def test_the_fixture_desk_fits_the_glass_in_every_tier(fleet_home, tmp_path, agents, width, desk_browser):
    """The acceptance criterion of #233, nine times over: no horizontal scroll, each pane in its
    tier, the red rail red and wearing its glyph, and an `aria-label` on every rail."""
    names = ["r%02d" % n for n in range(agents)]
    red = names[-1]
    _repos(tmp_path, names, needs=(red,))
    S.arrange(order=names, pinned=PINS[agents])
    opened = set(PINS[agents]) | {"r00"}
    shots = os.environ.get("AGENTDATA_SHOTS") or str(tmp_path / "shots")
    os.makedirs(shots, exist_ok=True)

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _page(browser, port, token, width)
        page.wait_for_function(
            f"() => document.querySelectorAll('#grid .tile[data-tier]').length === {agents}",
            timeout=15000)
        page.wait_for_timeout(300)                  # a settled frame, not the first one
        out = page.evaluate(READ_ROW)
        page.screenshot(path=os.path.join(shots, f"panes-{agents}-{width}.png"))
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)

    # Nothing sideways: not the page, and not the row.
    assert out["scroll"]["page"][0] <= out["scroll"]["page"][1], out["scroll"]
    assert out["scroll"]["row"][0] <= out["scroll"]["row"][1] + 1, out["scroll"]

    panes = {p["repo"]: p for p in out["panes"]}
    assert sorted(panes) == names, "every agent is a pane on the glass"
    # Designed away from the boundaries, so the tier each pane is in is the tier its width says.
    want_open = "compact" if (agents, width) == (12, 1280) else "full"
    for name, pane in panes.items():
        assert pane["right"] <= width + 0.5 and pane["left"] >= -0.5, (name, pane)
        if name in opened:
            assert pane["open"] and pane["tier"] == want_open, (name, pane)
            assert pane["tier"] == _tier_of(pane["width"]), (name, pane)
            assert pane["head"] and pane["say"] and pane["transcript"], (name, pane)
            assert pane["tools"] == ["hide", "refresh", "model"], (name, pane)
            assert pane["runline"] is (want_open == "full"), (name, pane)
            assert not pane["face"]["shown"], "an open pane does not show a rail's face"
            continue
        assert not pane["open"] and pane["tier"] == "rail", (name, pane)
        assert round(pane["width"]) == RAIL_PX, (name, pane)
        face = pane["face"]
        assert face["shown"] and face["tag"] == "BUTTON", (name, face)
        assert not pane["head"] and not pane["transcript"], "a rail shows its face and nothing else"
        # Every rail names itself, dates itself, and says its last line -- to a screen reader in
        # its accessible name, and to a pointer in its title.
        assert face["label"].startswith(name + ": "), face
        assert " ago" in face["label"], face
        assert face["title"] == face["label"], face
        assert face["name"] == name, face
        if name == red:
            assert face["red"], face
            assert face["background"] == out["human"], "the whole rail red, in the status red"
            assert face["glyph"] == "!", "and a glyph, never the colour alone"
            assert "needs you" in face["label"], face
            assert "which window should %s land in?" % name in face["label"], face
        else:
            assert not face["red"] and face["background"] != out["human"], face
            assert face["glyph"] != "!", face
            assert "working on " + name in face["label"], face


# ------------------------------------------------------------------- the ownership proof


@pytest.mark.browser
def test_an_idle_desk_makes_no_mutation_at_all(fleet_home, tmp_path, desk_browser):
    """The render contract's rule 1 over the whole document, not one component at a time: with
    nothing new to say, the stream running, and every draw path driven by hand -- the fleet
    answer, `place()`, every pane redrawn, the unread badges, the tier observer -- the page writes
    nothing. Two open panes, three rails (one red) and a hidden one are six chances for two owners
    to fight over one attribute on every pass.

    Idle means the same answer: `/api/fleet` is replayed byte for byte once the page has settled,
    because a live answer carries ages that are MEANT to change a chip once a second."""
    names = ["r%02d" % n for n in range(6)]
    _repos(tmp_path, names, needs=("r04",))
    S.arrange(order=names, pinned=["r01"], hidden=["r05"])

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _page(browser, port, token, 1920, 1000)
        page.wait_for_selector('#grid .tile.needs-human[data-tier="rail"]', timeout=15000)
        page.wait_for_function(
            "() => document.getElementById('hiddencount').textContent === '1 hidden'",
            timeout=15000)
        page.wait_for_timeout(400)
        count = page.evaluate("""async () => {
          const real = window.fetch.bind(window);
          const body = await (await real(q('/api/fleet'))).text();
          window.fetch = function (url, opts) {
            if (String(url).indexOf('/api/fleet') >= 0) {
              return Promise.resolve(new Response(body, {
                status: 200, headers: { 'Content-Type': 'application/json' } }));
            }
            return real(url, opts);
          };
          const pause = ms => new Promise(done => setTimeout(done, ms));
          const frame = () => new Promise(done => requestAnimationFrame(() => done()));
          // One pass of every path first: the replayed answer may carry an age that moved
          // since the last live one, and a badge nobody has counted yet is written the first
          // time it is -- both news. Everything after this pass is not.
          await refresh();
          place();
          redrawAll();
          bell();
          await frame(); await frame(); await pause(200);

          let n = 0;
          const seen = [];
          const obs = new MutationObserver(records => {
            n += records.length;
            records.slice(0, 5).forEach(r => seen.push(
              r.type + ' ' + (r.attributeName || '') + ' ' +
              (r.target.className || r.target.nodeName)));
          });
          obs.observe(document.documentElement, { subtree: true, childList: true,
                                                  attributes: true, characterData: true });
          for (let i = 0; i < 8; i++) {
            await refresh();
            place();
            redrawAll();
            bell();
            await frame();
            await pause(150);
          }
          obs.takeRecords().forEach(() => { n += 1; });
          obs.disconnect();
          return { n: n, seen: seen };
        }""")
        assert not errors, errors
        assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
        close_pages(browser)
    finally:
        _stop(server)


# ---------------------------------------------------------------------- the tiers, closer


@pytest.mark.browser
def test_a_tier_is_left_only_eight_pixels_past_its_boundary(fleet_home, tmp_path, desk_browser):
    """The hysteresis, read off the one function that decides it: a pane sitting on 360 -- a
    window edge being dragged, a scrollbar coming and going -- does not redraw itself between two
    tiers on every frame.

    Only between compact and full since the gutters (#234). A pane is a 48px rail or at least 160px
    wide, so nothing sits on the rail's boundary to flicker across it; the slack that was there drew
    a rail pulled out to exactly the compact minimum as a rail's face 160px wide."""
    _repos(tmp_path, ["alpha", "beta"])

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _page(browser, port, token, 1280)
        got = page.evaluate("""() => ({
          fresh: [47, 48, 159, 160, 359, 360, 2000].map(w => paneTier(w, '')),
          fromCompact: [151, 152, 160, 359, 367, 368].map(w => paneTier(w, 'compact')),
          fromFull: [351, 352, 360].map(w => paneTier(w, 'full')),
          fromRail: [48, 167, 168, 400].map(w => paneTier(w, 'rail')),
        })""")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert got["fresh"] == ["rail", "rail", "rail", "compact", "compact", "full", "full"]
    assert got["fromCompact"] == ["rail", "rail", "compact", "compact", "compact", "full"]
    assert got["fromFull"] == ["compact", "full", "full"]
    assert got["fromRail"] == ["rail", "compact", "compact", "full"]


# The desktop's own scale, read with a mouse (#574: the coarse block must not move it).
FINE_SCALE = """() => {
  const g = (el) => getComputedStyle(el);
  return { button: g(document.querySelector('.tile.is-solo .row.bottom .send')).minHeight,
           segment: g(document.querySelector('.segment')).minHeight,
           body: g(document.body).fontSize,
           gutter: g(document.querySelector('.gutter')).width };
}"""

# Every control a finger can reach in the open pane, the header and the footer, and every field.
COARSE_TARGETS = """() => {
  const seen = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const small = [];
  let n = 0;
  for (const root of [document.querySelector('.tile.is-solo'), document.querySelector('header'),
                      document.querySelector('footer')])
    for (const el of root.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')) {
      if (!seen(el)) continue;
      n += 1;
      const r = el.getBoundingClientRect();
      if (r.width < 44 || r.height < 44)
        small.push(`${root.tagName.toLowerCase()} ${el.className || el.id || el.tagName} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  const fonts = [...document.querySelectorAll('input, textarea, select')]
    .map((el) => [el.className || el.id || el.tagName, getComputedStyle(el).fontSize])
    .filter(([, size]) => size !== '16px');
  return { seen: n, small, fonts };
}"""

# The approval card's decision row, before and after its payload scrolls.
DECISION_ROW = """() => {
  const pane = document.querySelector('.tile.is-solo');
  const card = pane.querySelector('.approval'), row = card.querySelector('.row'), pre = card.querySelector('pre');
  const read = () => { const p = pane.getBoundingClientRect();
    return { row: row.getBoundingClientRect().toJSON(), pane: p.toJSON(),
             foot: Math.min(p.bottom, window.innerHeight),
             kids: [...row.children].map((k) => k.getBoundingClientRect().toJSON()) }; };
  const before = read();
  pre.scrollTop = pre.scrollHeight;
  return { before, after: read(), scrolled: pre.scrollTop };
}"""

# The open pane scrolls inside itself in the stack (#575): the decision row stays on the glass
# whichever end of the pane is showing.
PANE_SCROLL = """() => {
  const pane = document.querySelector('.tile.is-solo[data-repo="r01"]'), row = pane.querySelector('.approval .row');
  const read = () => { const p = pane.getBoundingClientRect(), r = row.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, paneTop: p.top, foot: Math.min(p.bottom, window.innerHeight) }; };
  pane.scrollTop = 0;
  const top = read();
  pane.scrollTop = pane.scrollHeight;
  const end = read();
  const scrolled = pane.scrollTop;
  pane.scrollTop = 0;
  return { top, end, scrolled, overflowY: getComputedStyle(pane).overflowY };
}"""

# The stack at 640 px and under (#575): the row wrapped, the open pane over a bottom bar of rails.
STACK = """() => {
  const grid = document.getElementById('grid'), g = grid.getBoundingClientRect(), cs = getComputedStyle(grid);
  const seen = [...grid.querySelectorAll('.tile')].filter((t) => t.offsetParent !== null);
  const box = (t) => t.getBoundingClientRect();
  const open = seen.filter((t) => t.classList.contains('is-solo'));
  const bar = seen.filter((t) => !t.classList.contains('is-solo'));
  const bottom = document.querySelector('.tile.is-solo .row.bottom').getBoundingClientRect();
  return { wrap: cs.flexWrap, sw: grid.scrollWidth, cw: grid.clientWidth, sh: grid.scrollHeight, ch: grid.clientHeight,
           foot: g.bottom - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth),
           open: open.map((t) => ({ repo: t.dataset.repo, tier: t.dataset.tier, width: box(t).width, y: box(t).y })),
           bar: bar.map((t) => ({ repo: t.dataset.repo, tier: t.dataset.tier, bottom: box(t).bottom, y: box(t).y })),
           reply: { top: bottom.top, bottom: bottom.bottom }, vh: window.innerHeight,
           page: document.scrollingElement.scrollTop };
}"""

# A phone on its side (#575): the open pane scrolled to its end shows the reply row on the screen.
SIDEWAYS = """() => {
  const pane = [...document.querySelectorAll('.tile.is-solo')].find((t) => t.offsetParent !== null);
  pane.scrollTop = pane.scrollHeight;
  const r = pane.querySelector('.row.bottom').getBoundingClientRect();
  const out = { wrap: getComputedStyle(document.getElementById('grid')).flexWrap, top: r.top, bottom: r.bottom,
                vh: window.innerHeight, page: document.scrollingElement.scrollTop, scrolled: pane.scrollTop };
  pane.scrollTop = 0;
  return out;
}"""


@pytest.mark.browser
def test_a_pane_that_widens_draws_what_its_narrower_tier_skipped(fleet_home, tmp_path, desk_browser):
    """The draw skips what a tier does not show -- a compact pane paints no trace and builds no
    cells -- so a change of tier has to draw the pane again, in the same frame, or a pane made wide
    by a bigger window would sit there without its cells until the next event.

    And a finger (#574): at 390x844 under a coarse pointer every control in the open pane, the
    header and the footer is 44 px both ways and every field is set at 16 px (iOS zooms the page
    into a field under 16 px); the approval card's Approve, reason and Deny wrap to three full
    lines that stay at the pane's foot while the payload scrolls. At 1400x900 with a mouse the
    desktop's 28 px / 13 px scale is what it was.

    And the stack (#575): at 390x844 the row wraps, the open pane is full and fills the glass, and
    the five rails are one bottom bar on the grid's foot; the decision row stays on the glass as the
    pane scrolls. At 844x390 the pane scrolls to its reply row, at 820x1180 the row is the row, and
    `all` at 390 stacks the panes and the grid scrolls down."""
    names = ["r%02d" % n for n in range(6)]
    _repos(tmp_path, names)
    S.arrange(order=names, pinned=["r01", "r02"])

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _page(browser, port, token, 900)
        page.wait_for_selector('.tile[data-repo="r00"][data-tier="compact"]', timeout=15000)
        page.wait_for_timeout(300)
        before = page.evaluate("""() => {
          const t = document.querySelector('.tile[data-repo="r00"]');
          return { cells: t.querySelectorAll('.cells .cell').length,
                   trace: t.querySelector('.trace').getAttribute('aria-label') || '' };
        }""")
        page.set_viewport_size({"width": 1920, "height": 900})
        page.wait_for_selector('.tile[data-repo="r00"][data-tier="full"]', timeout=5000)
        after = page.evaluate("""() => {
          const t = document.querySelector('.tile[data-repo="r00"]');
          return { trace: t.querySelector('.trace').getAttribute('aria-label') || '',
                   runline: getComputedStyle(t.querySelector('.runline')).display };
        }""")
        # And back: the rails stay rails whatever the window does, and nothing scrolls.
        page.set_viewport_size({"width": 900, "height": 900})
        page.wait_for_selector('.tile[data-repo="r00"][data-tier="compact"]', timeout=5000)
        rails = page.evaluate("""() => [...document.querySelectorAll(
          '#grid .tile[data-tier="rail"]')].map(t => Math.round(t.getBoundingClientRect().width))""")
        page.set_viewport_size({"width": 1400, "height": 900})
        page.wait_for_selector(".gutter", state="attached", timeout=5000)
        mouse = page.evaluate(FINE_SCALE)
        assert not errors, errors

        # A pending approval on the open pane, then the same desk on a phone.
        os.makedirs(approval.approvals_dir(), exist_ok=True)
        rid = approval.new_id("r01", "jira-transition")
        textio.write_json(os.path.join(approval.approvals_dir(), rid + ".json"), {
            "id": rid, "repo": "r01", "ticket": "RDSD-1", "kind": "jira-transition",
            "summary": "RDSD-1: In Progress -> In Review",
            "payload": {"lines": ["line %d of the dry run" % n for n in range(80)]},
            "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "pid": os.getpid()})
        phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                                    is_mobile=True, has_touch=True)
        m = phone.new_page()
        m.on("pageerror", lambda e: errors.append(str(e)))
        m.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        m.wait_for_selector('.tile.is-solo[data-repo="r01"] .approval:not([hidden])', timeout=15000)
        finger = m.evaluate(COARSE_TARGETS)
        card = m.evaluate(DECISION_ROW)
        scroll = m.evaluate(PANE_SCROLL)

        # #575: the stack. Unpinned, one pane is open and the other five are the bottom bar.
        S.arrange(order=names, pinned=[])
        m.wait_for_function("() => document.querySelectorAll('#grid .tile.is-solo').length === 1",
                            timeout=10000)
        m.wait_for_function("""() => [...document.querySelectorAll('#grid .tile')]
                                 .every((t) => t.dataset.tier === (t.classList.contains('is-solo') ? 'full' : 'rail'))""",
                            timeout=10000)
        stack = m.evaluate(STACK)
        m.set_viewport_size({"width": 844, "height": 390})
        m.wait_for_function("() => getComputedStyle(document.getElementById('grid')).flexWrap === 'nowrap'",
                            timeout=5000)
        m.wait_for_timeout(300)
        sideways = m.evaluate(SIDEWAYS)
        m.set_viewport_size({"width": 820, "height": 1180})
        m.wait_for_selector('#grid .tile.is-solo[data-tier="full"]', timeout=5000)
        m.wait_for_timeout(300)
        tablet = m.evaluate(STACK)
        # #577: `all` on the tablet widens only the panes that fit, rails the rest and says
        # so, in one write that `u` takes back in one press. The pane you are in stays wide
        # even when it is last in the row (decision 22).
        m.locator('.tile[data-repo="r05"] .pane-rail').tap()
        m.wait_for_function("() => openName() === 'r05' && windowWrites === 0", timeout=10000)
        posts = []
        m.on("request", lambda r: posts.append(r.url + " " + (r.post_data or "")) if r.method == "POST" else None)
        m.locator("#preset-all").tap()
        m.wait_for_function("() => /^all that fit: \\d+ of 6$/.test(document.getElementById('notice').textContent)"
                            " && windowWrites === 0 && !inViewTransition && [...document.querySelectorAll('#grid .tile')]"
                            ".every((t) => !t.style.transform && t.getAnimations().length === 0)", timeout=10000)
        capped = m.evaluate(STACK)
        capped["said"] = m.evaluate("() => document.getElementById('notice').textContent")
        capped["posts"] = list(posts)
        m.keyboard.press("u")
        m.wait_for_function("() => document.querySelectorAll('#grid .tile.is-solo').length === 1"
                            " && windowWrites === 0", timeout=10000)
        capped["undone"] = list(posts)
        m.set_viewport_size({"width": 390, "height": 844})
        m.wait_for_function("() => getComputedStyle(document.getElementById('grid')).flexWrap === 'wrap'",
                            timeout=5000)
        m.locator("#preset-all").tap()
        m.wait_for_function("() => document.querySelectorAll('#grid .tile.is-solo').length === 6",
                            timeout=10000)
        m.wait_for_timeout(300)
        spread = m.evaluate(STACK)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert before["cells"] == 0, "a compact pane built cells it does not show"
    assert before["trace"] == "", "a compact pane painted a trace it does not show"
    assert after["trace"], "widened to full, the pane never drew its trace"
    assert after["runline"] != "none", after
    assert rails == [RAIL_PX] * 3, rails

    assert mouse == {"button": "28px", "segment": "24px", "body": "13px", "gutter": "8px"}, mouse
    assert finger["seen"] > 10, finger
    assert not finger["small"], f"under 44 px at 390 under a finger: {finger['small']}"
    assert not finger["fonts"], f"fields under 16 px (iOS zooms into them): {finger['fonts']}"
    kids, row = card["before"]["kids"], card["before"]["row"]
    assert len(kids) == 3 and all(abs(k["width"] - row["width"]) <= 1 for k in kids), card
    assert kids[0]["bottom"] <= kids[1]["top"] and kids[1]["bottom"] <= kids[2]["top"], card
    assert card["scrolled"] > 0, "the payload never scrolled"
    for step in ("before", "after"):
        seen = card[step]
        assert seen["row"]["top"] >= seen["pane"]["top"] and seen["row"]["bottom"] <= seen["foot"] + 1, (step, card)
    # Re-measured in the stack (#575), where the pane itself scrolls: the row stays on the glass at
    # either end of it.
    assert scroll["overflowY"] == "auto", scroll
    for end in ("top", "end"):
        seen = scroll[end]
        assert seen["top"] >= seen["paneTop"] and seen["bottom"] <= seen["foot"] + 1, (end, scroll)

    # 390x844: nothing sideways, the open pane full and >= 360 px, every rail a rail on the grid's
    # foot, the reply row on the screen.
    assert stack["wrap"] == "wrap" and stack["sw"] <= stack["cw"], stack
    assert len(stack["open"]) == 1 and stack["open"][0]["tier"] == "full" and stack["open"][0]["width"] >= 360, stack
    assert len(stack["bar"]) == 5 and all(r["tier"] == "rail" for r in stack["bar"]), stack
    assert all(abs(r["bottom"] - stack["foot"]) <= 1 for r in stack["bar"]), stack
    assert 0 <= stack["reply"]["top"] and stack["reply"]["bottom"] <= stack["vh"], stack
    # 844x390: the row, and the reply row reached by scrolling the pane, not the page.
    assert sideways["wrap"] == "nowrap" and sideways["page"] == 0, sideways
    assert 0 <= sideways["top"] and sideways["bottom"] <= sideways["vh"], sideways
    # 820x1180: the row as it was, one full pane and the rails on one line.
    assert tablet["wrap"] == "nowrap" and len(tablet["open"]) == 1 and tablet["open"][0]["tier"] == "full", tablet
    assert len({round(t["y"]) for t in tablet["open"] + tablet["bar"]}) == 1, tablet
    assert all(r["tier"] == "rail" for r in tablet["bar"]), tablet
    # `all` at 820x1180 (#577): the panes that fit at the compact minimum, the rest rails, nothing
    # sideways, one write, and `u` one more.
    fit = int(capped["said"].split(": ")[1].split(" of ")[0])
    assert 1 < fit < 6 and capped["wrap"] == "nowrap" and capped["sw"] <= capped["cw"], capped
    assert len(capped["open"]) == fit and all(t["width"] >= 160 for t in capped["open"]), capped
    assert [t["repo"] for t in capped["open"]] == names[:fit - 1] + ["r05"], capped
    assert len(capped["bar"]) == 6 - fit and all(r["tier"] == "rail" for r in capped["bar"]), capped
    writes = [u for u in capped["posts"] if '"widths"' in u]
    assert len(writes) == 1 and all("/api/window" in u for u in capped["posts"]), capped
    assert len([u for u in capped["undone"] if '"widths"' in u]) == 2, capped
    # `all` at 390: the panes stack and the grid scrolls down, never sideways.
    assert len(spread["open"]) == 6 and spread["sw"] <= spread["cw"] and spread["sh"] > spread["ch"], spread


@pytest.mark.browser
def test_a_pane_that_has_just_arrived_does_not_travel_into_its_slot(fleet_home, tmp_path, desk_browser):
    """Panes are made in the order `/api/fleet` lists them and then put in the arrangement's. In
    the column that first move happened to tiles nobody could see; in the row every agent is on the
    glass, so it played as a FLIP -- the rails shuffling into place for a fifth of a second on every
    load, and a press aimed at one in that time landing beside it (a test's drag did, one run in
    twenty under load). Where a pane first appears is not a move the operator made. A real move
    still travels."""
    names = ["alpha", "beta", "delta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=["gamma", "delta", "beta", "alpha"])

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _page(browser, port, token, 1400)
        page.wait_for_function(
            "() => document.querySelectorAll('#grid .tile[data-tier]').length === 4",
            timeout=15000)
        arrived = page.evaluate("""() => ({
          order: [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo),
          travelled: [...document.querySelectorAll('#grid .tile')]
                       .filter(t => t.classList.contains('flip') || t.style.transform)
                       .map(t => t.dataset.repo),
        })""")
        moved = page.evaluate("""() => {
          moveTile('delta', 1);
          return [...document.querySelectorAll('#grid .tile')]
                   .filter(t => t.style.transform).map(t => t.dataset.repo);
        }""")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert arrived["order"] == ["gamma", "delta", "beta", "alpha"], arrived
    assert arrived["travelled"] == [], f"panes travelled into the slots they arrived in: {arrived}"
    assert moved, "a move the operator made no longer travels"


# ------------------------------------------------------------- when the rails do not fit


@pytest.mark.browser
def test_when_the_rails_do_not_fit_a_projects_checkouts_share_one(fleet_home, tmp_path, desk_browser):
    """plan-panes §Open questions, D's default: when even the rails do not fit, a project's
    checkouts share one rail -- as the dock grouped them (#175) -- rather than the row scrolling
    sideways, which is how the agent that needs you ends up off the glass. The shared rail is red
    when any of its checkouts needs a person, says which in its label, and a press on it opens
    that one."""
    names = ["r%02d" % n for n in range(16)]
    projects = {name: "proj-%d" % (n % 4) for n, name in enumerate(names)}
    _repos(tmp_path, names, needs=("r06",), projects=projects)
    S.arrange(order=names)

    server, token, port = _serve()
    try:
        browser = desk_browser
        # Sixteen rails and an open pane need about 1 000px; this window has 800.
        page, errors = _page(browser, port, token, 800)
        page.wait_for_function(
            "() => document.querySelectorAll('#grid .tile.is-grouped').length > 0",
            timeout=15000)
        page.wait_for_timeout(300)
        out = page.evaluate(READ_ROW)
        red = page.evaluate("""() => {
          const face = document.querySelector('#grid .pane-rail.needs-human');
          return { repo: face.closest('.tile').dataset.repo,
                   label: face.getAttribute('aria-label') };
        }""")
        page.click(f'.tile[data-repo="{red["repo"]}"] .pane-rail')
        page.wait_for_selector('.tile[data-repo="r06"].is-solo[data-tier="full"]',
                               timeout=5000)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)

    assert out["scroll"]["page"][0] <= out["scroll"]["page"][1], out["scroll"]
    assert out["scroll"]["row"][0] <= out["scroll"]["row"][1] + 1, out["scroll"]
    rails = [p for p in out["panes"] if p["tier"] == "rail"]
    # r00 is open; its project's other three share a rail, and so do each other project's four.
    assert len(rails) == 4, [p["repo"] for p in out["panes"]]
    for pane in rails:
        assert round(pane["width"]) == RAIL_PX, pane
        assert re.search(r"proj-\d, [34] checkouts", pane["face"]["label"]), pane["face"]
        assert pane["face"]["glyph"] in ("!", "3", "4"), pane["face"]
    assert red["repo"] == "r02", "the shared rail is the project's first checkout in the row"
    assert "proj-2, 4 checkouts, 1 needs you" in red["label"], red
    assert "r06: needs you" in red["label"], red


# --------------------------------------------------------------------------- the source


def test_one_observer_and_one_writer_decide_the_tier():
    """The tier is set in one place (plan-panes §The pane): one `ResizeObserver` on the row, and
    one function that writes `data-tier`. The stylesheet keys on the attribute and never sets a
    width from it, or a tier that changed the width would change the tier."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert js.count("new ResizeObserver(") == 1
    assert js.count('attr(el, "data-tier"') == 1
    assert 'data-tier="' not in html, "the tier is measured, never written into the markup"
    for number in ("var TIER_COMPACT_FROM = 160;", "var TIER_FULL_FROM = 360;",
                   "var TIER_SLACK = 8;", "var RAIL_PX = 48;"):
        assert number in js, number
    assert "--rail: 48px;" in css
    # The rules whose subject is the pane itself -- what is INSIDE a pane may be laid out by tier.
    for rule in re.findall(r'\.tile\[data-tier="[a-z]+"\](?:\.[\w-]+)*\s*\{([^}]*)\}', css):
        assert not re.search(r"(?<![-\w])(width|flex|flex-basis|min-width|max-width)\s*:", rule), \
            f"a tier sets a pane's width: {rule.strip()}"
    # And the band is gone: no component, no draw function, no column.
    for gone in ("function drawColumn(", "function drawBand(", "#bands", "band-open"):
        assert gone not in js, gone
    for gone in ('id="column"', 'id="bands"', 'class="band"'):
        assert gone not in html, gone
    for gone in (".column {", ".band {", ".bands {"):
        assert gone not in css, gone


def test_the_rail_says_its_state_with_a_glyph_for_every_state():
    """Never colour alone: every state the fold can report has a glyph as well as a colour."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    block = js[js.index("var RAIL_GLYPHS = {"):]
    block = block[:block.index("};")]
    for state in ("running", "waiting_approval", "needs_human", "blocked", "error", "done",
                  "idle", "starting"):
        assert state + ":" in block, state
    assert 'red ? "!"' in js, "the rail that needs a person wears `!`"
