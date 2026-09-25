"""2026-09-23, /settings on any machine: the Browns palette looked gone.

Symptom, in the operator's words:

    The NFL Browns theme (that currently seems to have dropped off)

Nothing had deleted it: `nfl-browns` was still in `theme.BUILTINS`. But no skin variant was drawn on
the palette, so no skin ever brought it; the palette picker is locked while a skin is on (ae20235),
so from a skinned page it could not be chosen at all; and with no skin on, its option read the raw
slug `nfl-browns`, with the palette's reason only in a hover tooltip. Nothing on the page tied a
palette to the looks drawn on it, or said that a palette with none could still be chosen.

Issue: https://github.com/agentchieflou/this-next-please/issues/393
"""
from __future__ import annotations

from agentdata import theme
from agentdata.fleet import serve as S, skins


def test_browns_is_a_palette_the_page_offers_by_its_title_and_can_reach():
    assert "nfl-browns" in theme.BUILTINS

    offered = {t["name"]: t for t in S.themes()}
    assert "nfl-browns" in offered, sorted(offered)
    # The names decision (#318): the palette keeps its shipped title; only the display moved to it.
    assert offered["nfl-browns"]["title"] == theme.BUILTINS["nfl-browns"].title == "NFL Browns"

    drawn = {spec["base"] for _, _, spec in skins.every_variant()}
    assert "nfl-browns" in drawn or getattr(skins, "PALETTE_ONLY", {}).get("nfl-browns"), (
        "nfl-browns is drawn by no variant and not listed in skins.PALETTE_ONLY with a reason")
