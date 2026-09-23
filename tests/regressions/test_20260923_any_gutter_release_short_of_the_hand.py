"""2026-09-23, the Windows 3.14 leg of #270: a gutter drag landed one step short of the pointer.

Symptom (`windows · python 3.14`, tests/test_fleet_gutters.py):

    assert _near(after["alpha"]["width"], before["alpha"]["width"] + 50, 1.5), (before, after)
    E   assert False
    E    +  where False = _near(503.15625, (457.328125 + 50), 1.5)

45.83px of a 50px drag is eleven of its twelve 4.17px steps. The gutter took its width from the last
`pointermove` it had seen and ignored where the `pointerup` happened -- and an engine that coalesces
moves to the animation frame can deliver the release before the move that got there. The width is
now where the hand came up.

The release is dispatched here with no move in front of it, which is that ordering made
deterministic: the hand is carried 20px for real, then comes up 50px from where it went down.

Issue: https://github.com/agentchieflou/this-next-please/issues/234
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import (_gutter_point, _near, _own_desk_globals, _page,  # noqa: F401
                                _read_settled, _repos, _serve, _stop, _widths_posts,
                                fleet_home)


@pytest.mark.browser
def test_a_gutter_released_past_its_last_move_lands_where_the_hand_came_up(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            before = _read_settled(page)
            posts.clear()
            x, y = _gutter_point(page, "alpha")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + 20, y, steps=2)
            page.wait_for_function(
                "(want) => gutterHeld && Math.abs(gutterHeld.a - gutterHeld.a0 - want) < 0.5", arg=20,
                timeout=8000)
            # The release, 30px further on than any move the page has heard of.
            page.evaluate("""([x, y]) => document.dispatchEvent(new PointerEvent('pointerup', {
                               bubbles: true, clientX: x, clientY: y, pointerId: 1, button: 0 }))""",
                          [x + 50, y])
            page.wait_for_function("() => !gutterHeld && windowWrites === 0", timeout=8000)
            page.mouse.up()
            after = _read_settled(page)
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _near(after["alpha"]["width"], before["alpha"]["width"] + 50, 1.5), (before, after)
    assert _near(after["gamma"]["left"], before["gamma"]["left"]), "only the pair moved"
    assert len(_widths_posts(sent)) == 1, sent
