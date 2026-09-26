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

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

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
def test_the_fixture_desk_fits_the_glass_in_every_tier(fleet_home, tmp_path, agents, width):
    """The acceptance criterion of #233, nine times over: no horizontal scroll, each pane in its
    tier, the red rail red and wearing its glyph, and an `aria-label` on every rail."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(agents)]
    red = names[-1]
    _repos(tmp_path, names, needs=(red,))
    S.arrange(order=names, pinned=PINS[agents])
    opened = set(PINS[agents]) | {"r00"}
    shots = os.environ.get("AGENTDATA_SHOTS") or str(tmp_path / "shots")
    os.makedirs(shots, exist_ok=True)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, width)
            page.wait_for_function(
                f"() => document.querySelectorAll('#grid .tile[data-tier]').length === {agents}",
                timeout=15000)
            page.wait_for_timeout(300)                  # a settled frame, not the first one
            out = page.evaluate(READ_ROW)
            page.screenshot(path=os.path.join(shots, f"panes-{agents}-{width}.png"))
            assert not errors, errors
            browser.close()
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
def test_an_idle_desk_makes_no_mutation_at_all(fleet_home, tmp_path):
    """The render contract's rule 1 over the whole document, not one component at a time: with
    nothing new to say, the stream running, and every draw path driven by hand -- the fleet
    answer, `place()`, every pane redrawn, the unread badges, the tier observer -- the page writes
    nothing. Two open panes, three rails (one red) and a hidden one are six chances for two owners
    to fight over one attribute on every pass.

    Idle means the same answer: `/api/fleet` is replayed byte for byte once the page has settled,
    because a live answer carries ages that are MEANT to change a chip once a second."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(6)]
    _repos(tmp_path, names, needs=("r04",))
    S.arrange(order=names, pinned=["r01"], hidden=["r05"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
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
            browser.close()
    finally:
        _stop(server)


# ---------------------------------------------------------------------- the tiers, closer


@pytest.mark.browser
def test_a_tier_is_left_only_eight_pixels_past_its_boundary(fleet_home, tmp_path):
    """The hysteresis, read off the one function that decides it: a pane sitting on 360 -- a
    window edge being dragged, a scrollbar coming and going -- does not redraw itself between two
    tiers on every frame.

    Only between compact and full since the gutters (#234). A pane is a 48px rail or at least 160px
    wide, so nothing sits on the rail's boundary to flicker across it; the slack that was there drew
    a rail pulled out to exactly the compact minimum as a rail's face 160px wide."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, ["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, 1280)
            got = page.evaluate("""() => ({
              fresh: [47, 48, 159, 160, 359, 360, 2000].map(w => paneTier(w, '')),
              fromCompact: [151, 152, 160, 359, 367, 368].map(w => paneTier(w, 'compact')),
              fromFull: [351, 352, 360].map(w => paneTier(w, 'full')),
              fromRail: [48, 167, 168, 400].map(w => paneTier(w, 'rail')),
            })""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert got["fresh"] == ["rail", "rail", "rail", "compact", "compact", "full", "full"]
    assert got["fromCompact"] == ["rail", "rail", "compact", "compact", "compact", "full"]
    assert got["fromFull"] == ["compact", "full", "full"]
    assert got["fromRail"] == ["rail", "compact", "compact", "full"]


@pytest.mark.browser
def test_a_pane_that_widens_draws_what_its_narrower_tier_skipped(fleet_home, tmp_path):
    """The draw skips what a tier does not show -- a compact pane paints no trace and builds no
    cells -- so a change of tier has to draw the pane again, in the same frame, or a pane made wide
    by a bigger window would sit there without its cells until the next event."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(6)]
    _repos(tmp_path, names)
    S.arrange(order=names, pinned=["r01", "r02"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
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
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert before["cells"] == 0, "a compact pane built cells it does not show"
    assert before["trace"] == "", "a compact pane painted a trace it does not show"
    assert after["trace"], "widened to full, the pane never drew its trace"
    assert after["runline"] != "none", after
    assert rails == [RAIL_PX] * 3, rails


@pytest.mark.browser
def test_a_pane_that_has_just_arrived_does_not_travel_into_its_slot(fleet_home, tmp_path):
    """Panes are made in the order `/api/fleet` lists them and then put in the arrangement's. In
    the column that first move happened to tiles nobody could see; in the row every agent is on the
    glass, so it played as a FLIP -- the rails shuffling into place for a fifth of a second on every
    load, and a press aimed at one in that time landing beside it (a test's drag did, one run in
    twenty under load). Where a pane first appears is not a move the operator made. A real move
    still travels."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "delta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=["gamma", "delta", "beta", "alpha"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
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
            browser.close()
    finally:
        _stop(server)
    assert arrived["order"] == ["gamma", "delta", "beta", "alpha"], arrived
    assert arrived["travelled"] == [], f"panes travelled into the slots they arrived in: {arrived}"
    assert moved, "a move the operator made no longer travels"


# ------------------------------------------------------------- when the rails do not fit


@pytest.mark.browser
def test_when_the_rails_do_not_fit_a_projects_checkouts_share_one(fleet_home, tmp_path):
    """plan-panes §Open questions, D's default: when even the rails do not fit, a project's
    checkouts share one rail -- as the dock grouped them (#175) -- rather than the row scrolling
    sideways, which is how the agent that needs you ends up off the glass. The shared rail is red
    when any of its checkouts needs a person, says which in its label, and a press on it opens
    that one."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(16)]
    projects = {name: "proj-%d" % (n % 4) for n, name in enumerate(names)}
    _repos(tmp_path, names, needs=("r06",), projects=projects)
    S.arrange(order=names)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
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
            browser.close()
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
