"""2026-09-23, the desk in Chrome under a skin: the agent that needs you is the hardest name to read.

Symptom (measured in headless Chromium at 8557b2b, the name's colour against the pixels under it):

    glass smoke / azure / noir / frost 1.67 / 1.68 / 2.17 / 2.10; notebook dark 1.72;
    farmstead daytime / cave / rainy 2.11 / 2.03 / 1.89; graph blueprint 1.68

and, with the name in `--text` instead of red, still under 4.5:1 through the swipe: glass smoke
4.10, notebook dark 4.26, farmstead rainy 4.49. `theme.check` rule 5 passed every one, because it
read the text through a 38% tint of the ink while the layer screens the highlighter onto a dark
ground at 0.42 and multiplies it into a light one at 0.68.

Issue: https://github.com/agentchieflou/this-next-please/issues/329
"""
from __future__ import annotations
import os

import pytest

from agentdata import theme
from agentdata.fleet import skins

CSS = os.path.join(os.path.dirname(skins.__file__), "static", "skins")


@pytest.mark.parametrize("full", ["glass:smoke", "notebook:dark", "farmstead:rainy"])
def test_the_name_reads_at_4_5_through_the_highlighter(full):
    skin, variant = full.split(":")
    spec = skins.SKINS[skin]["variants"][variant]
    palette = theme.get(spec["base"])
    paper = spec["composited_panel"] if skin == "notebook" else None
    dark = theme.is_dark(paper or palette.ground)
    ink = spec["inks"]["highlighter"]
    for panel in skins.composited_panels(spec):
        assert theme.contrast_ratio(palette.text, theme.highlight_under(panel, ink, dark)) >= 4.5, (full, panel, ink)
        theme.check(palette, composited_panel=panel, skin=full, inks={"highlighter": ink}, dark=dark)
    # The page draws the same ink: skin.css says it as the variant's `--ink-highlighter`.
    assert f"--ink-highlighter: {ink};" in open(os.path.join(CSS, skin, "skin.css"), encoding="utf-8").read()
