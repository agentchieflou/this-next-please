"""Sitting: B — scrollbars that belong to the theme (issue #181).

No `scrollbar` rule existed anywhere in `static/`, so the one control the operating system draws
was drawn by the operating system -- on Windows a 17-pixel grey bar with arrows -- over a page that
repaints every other pixel from the palette. Two custom properties now carry the thumb, mixed from
`--line` and `--text`, written into both `scrollbar-color` and the legacy `::-webkit-scrollbar`
rules; a skin overrides the thumb and only the thumb.
"""
from __future__ import annotations
import os
import re
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S, skins as K
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
SKINS_DIR = os.path.join(STATIC, "skins")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


# --------------------------------------------------------------------------- the two mechanisms


def test_the_standard_property_and_the_legacy_rules_say_the_same_colours():
    """Acceptance criterion. Chromium prefers the legacy pseudo-elements when both match, so a
    thumb changed in one place and not the other would be a scrollbar that looks right in one
    embedder and wrong in the next. Both are written in the same two properties, and this reads
    them back."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()

    standard = re.findall(r"scrollbar-color:\s*([^;]+);", css)
    assert standard == ["var(--scroll-thumb) var(--scroll-track)"], standard

    thumbs = re.findall(r"::-webkit-scrollbar-thumb\s*\{([^}]*)\}", css)
    assert thumbs, "no legacy thumb rule for the embedders that predate scrollbar-color"
    assert all("var(--scroll-thumb)" in body for body in thumbs if "hover" not in body), thumbs

    tracks = re.findall(r"::-webkit-scrollbar-(?:track|corner)[^{]*\{([^}]*)\}", css)
    assert tracks and all("var(--scroll-track)" in body for body in tracks), tracks

    # The colours are mixed from the palette, not typed in: every palette gets a thumb of its own.
    assert re.search(r"--scroll-thumb:\s*color-mix\(in srgb, var\(--line\)", css)


def test_a_skin_overrides_the_thumb_and_never_the_rule():
    """A skin repaints its scrollbar by setting the thumb token on `body[data-skin]`. It never
    writes `scrollbar-color` itself -- that is how the two mechanisms would start to disagree."""
    for name in ("glass", "voxel", "farmstead"):
        css = open(os.path.join(SKINS_DIR, name, "skin.css"), encoding="utf-8").read()
        assert re.search(r'body\[data-skin="%s"\][^{]*\{[^}]*--scroll-thumb:' % name, css), \
            f"{name} does not paint its scrollbar"
        assert "scrollbar-color" not in css, f"{name} declares scrollbar-color of its own"
        for body in re.findall(r"::-webkit-scrollbar-thumb[^{]*\{([^}]*)\}", css):
            assert not re.search(r"(^|[^-])background\s*:", body), \
                f"{name}'s legacy thumb sets a background literal instead of the token: {body}"


# ---------------------------------------------------------------------------- rendered, measured


def _repos(tmp_path, *names):
    for name in names:
        path = make_project(tmp_path / name, ticket="RDSD-1")
        Registry().add(path, name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


@pytest.mark.browser
def test_the_transcript_scrollbar_computes_to_the_palette_in_every_look(fleet_home, tmp_path):
    """Acceptance criterion. `getComputedStyle(transcript).scrollbarColor` equals the declared
    thumb -- resolved through a probe element so the comparison is between two computed colours
    and not between a string and a `color-mix()` -- for `none` and for every skin variant, in the
    same loop that already applies each variant for real."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")
    looks = ["none"] + [f"{skin}:{variant}" for skin, variant, _spec in K.every_variant()]

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            seen = {}
            for look in looks:
                page.evaluate("(name) => post('theme', { skin: name })", look)
                page.wait_for_timeout(450)
                got = page.evaluate("""() => {
                    const probe = document.createElement('i');
                    probe.style.color = 'var(--scroll-thumb)';
                    document.body.appendChild(probe);
                    const thumb = getComputedStyle(probe).color;
                    probe.remove();
                    const t = document.querySelector('.tile .transcript');
                    return { thumb, bar: getComputedStyle(t).scrollbarColor,
                             width: getComputedStyle(t).scrollbarWidth };
                }""")
                assert got["bar"].startswith(got["thumb"]), (look, got)
                assert got["bar"].endswith("rgba(0, 0, 0, 0)"), (look, "the track is the surface beneath", got)
                assert got["width"] == "thin", (look, got)
                seen[look] = got["thumb"]

            # A skin's thumb is its own, and a palette's is mixed from that palette: the looks
            # do not all resolve to one colour.
            assert len(set(seen.values())) > 1, seen
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
