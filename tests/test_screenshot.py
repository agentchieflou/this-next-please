import json
import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agentdata.pbip import desktop as DT
from agentdata.pbip.screenshot import (
    compare_rgba_buffers,
    compare_images,
    find_visual_in_pbir,
    screenshot_session,
)
from agentdata.cli_pbip import build_parser


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample.pbip"


def test_find_visual_in_pbir_by_title():
    page, visual = find_visual_in_pbir(FIXTURE_DIR, "Broken table")
    assert page is not None
    assert visual is not None
    assert page["id"] == "page1"
    assert page["displayName"] == "Overview"
    assert page["width"] == 1280
    assert page["height"] == 720
    assert visual["id"] == "aaaaaaaaaaaaaaaaaaaa"
    assert visual["title"] == "Broken table"
    assert visual["position"]["x"] == 540
    assert visual["position"]["y"] == 20
    assert visual["position"]["width"] == 500
    assert visual["position"]["height"] == 300


def test_find_visual_in_pbir_by_id():
    page, visual = find_visual_in_pbir(FIXTURE_DIR, "aaaaaaaaaaaaaaaaaaaa")
    assert page is not None
    assert visual is not None
    assert visual["id"] == "aaaaaaaaaaaaaaaaaaaa"


def test_find_visual_in_pbir_page_filter():
    # Matches on page1
    page, visual = find_visual_in_pbir(FIXTURE_DIR, "Broken table", page_needle="Overview")
    assert page is not None
    assert visual is not None

    # Fails when filtering on page2
    page, visual = find_visual_in_pbir(FIXTURE_DIR, "Broken table", page_needle="page2")
    assert page is None
    assert visual is None


def test_find_visual_not_found():
    page, visual = find_visual_in_pbir(FIXTURE_DIR, "Non-existent Visual")
    assert page is None
    assert visual is None


def test_compare_images_identical():
    # 4x4 image, all black (0, 0, 0, 255)
    raw = bytearray([0, 0, 0, 255] * 16)
    res = compare_rgba_buffers(bytes(raw), bytes(raw), 4, 4, 4, 4, threshold=0.01)
    assert res["verdict"] == "same"
    assert res["diff_pixels"] == 0
    assert res["changed_pct"] == 0.0
    assert res["bbox"] is None


def test_compare_images_diff_and_threshold():
    # 10x10 image: 100 pixels
    raw_a = bytearray([0, 0, 0, 255] * 100)
    raw_b = bytearray([0, 0, 0, 255] * 100)
    # Modify 5 pixels at (2, 3), (2, 4), (2, 5), (3, 3), (3, 4)
    for x, y in [(2, 3), (2, 4), (2, 5), (3, 3), (3, 4)]:
        offset = (y * 10 + x) * 4
        raw_b[offset : offset + 4] = [255, 255, 255, 255]

    # Threshold 0.01 (1%) -> 5% changed is "changed"
    res_changed = compare_rgba_buffers(bytes(raw_a), bytes(raw_b), 10, 10, 10, 10, threshold=0.01)
    assert res_changed["verdict"] == "changed"
    assert res_changed["diff_pixels"] == 5
    assert res_changed["total_pixels"] == 100
    assert res_changed["changed_pct"] == 5.0
    assert res_changed["bbox"] == [2, 3, 3, 5]

    # Threshold 0.10 (10%) -> 5% changed is "same"
    res_same = compare_rgba_buffers(bytes(raw_a), bytes(raw_b), 10, 10, 10, 10, threshold=0.10)
    assert res_same["verdict"] == "same"
    assert res_same["diff_pixels"] == 5


def test_compare_images_with_mask():
    # 10x10 image: 100 pixels
    raw_a = bytearray([0, 0, 0, 255] * 100)
    raw_b = bytearray([0, 0, 0, 255] * 100)
    # Modify 4 pixels in box [2, 2, 3, 3]
    for y in range(2, 4):
        for x in range(2, 4):
            offset = (y * 10 + x) * 4
            raw_b[offset : offset + 4] = [255, 255, 255, 255]

    # Mask covering [2, 2, 4, 4] (x=2, y=2, w=2, h=2)
    masks = [(2, 2, 2, 2)]
    res = compare_rgba_buffers(bytes(raw_a), bytes(raw_b), 10, 10, 10, 10, masks=masks, threshold=0.01)
    assert res["verdict"] == "same"
    assert res["diff_pixels"] == 0
    assert res["total_pixels"] == 96  # 100 - 4 masked


def test_compare_images_size_mismatch():
    raw_a = bytearray([0, 0, 0, 255] * 16)
    raw_b = bytearray([0, 0, 0, 255] * 25)
    res = compare_rgba_buffers(bytes(raw_a), bytes(raw_b), 4, 4, 5, 5)
    assert res["verdict"] == "changed"
    assert "error" in res


def test_screenshot_session_mocked():
    mock_run = MagicMock()
    # Mock responses for win32.ps1 calls
    def fake_run(args, timeout=30):
        cmd = args[-1] if args else ""
        if "NavigatePage" in cmd:
            return 0, json.dumps({"ok": True, "page": "Overview"}), ""
        if "GetCanvasRect" in cmd:
            return 0, json.dumps({"ok": True, "x": 100, "y": 80, "width": 1280, "height": 720}), ""
        if "CaptureWindow" in cmd:
            return 0, json.dumps({"ok": True, "path": "test.png", "width": 1440, "height": 900}), ""
        if "CropImage" in cmd:
            return 0, json.dumps({"ok": True, "path": "test_crop.png", "width": 500, "height": 300}), ""
        return 0, json.dumps({"ok": True}), ""

    mock_run.side_effect = fake_run

    fake_inst = DT.Instance(
        pid=12345,
        port=1234,
        server="localhost:1234",
        workspace_dir=None,
        workspace_name=None,
        title="Sample - Power BI Desktop",
        file=str(FIXTURE_DIR),
        matched=str(FIXTURE_DIR),
        source="test",
        pages=[{"id": "page1", "displayName": "Overview", "order": 0, "active": True}],
        loaded=True,
    )

    with patch("agentdata.pbip.desktop.status", return_value=[fake_inst]), \
         tempfile.TemporaryDirectory() as tmp_dir:
        pages, visuals = screenshot_session(
            pid=12345,
            page="Overview",
            pbip_path=str(FIXTURE_DIR),
            visual="Broken table",
            out_dir=tmp_dir,
            run=mock_run,
        )
        assert len(pages) == 1
        page_row = pages[0]
        assert page_row["pid"] == 12345
        assert page_row["page"] == "page1"
        assert page_row["displayName"] == "Overview"
        assert "path" in page_row
        assert page_row["width"] == 1280
        assert len(visuals) == 1
        vis_row = visuals[0]
        assert vis_row["visual_id"] == "aaaaaaaaaaaaaaaaaaaa"
        assert vis_row["title"] == "Broken table"


def test_cli_screenshot_parser():
    parser = build_parser()
    args = parser.parse_args([
        "screenshot",
        "--pid", "12345",
        "--page", "Overview",
        "--visual", "Broken table",
        "--out", "out.png",
        "--compare", "before.png", "after.png",
        "--threshold", "0.02",
        "--mask", "10,20,100,50",
    ])
    assert args.pid == 12345
    assert args.page == "Overview"
    assert args.visual == "Broken table"
    assert args.out == "out.png"
    assert args.compare == ["before.png", "after.png"]
    assert args.threshold == 0.02
    assert args.mask == ["10,20,100,50"]
