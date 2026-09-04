"""Power BI Desktop screenshots and visual regression without the Bridge.

Captures Desktop canvas via Win32 PrintWindow (PW_RENDERFULLCONTENT), page navigation via UIA,
per-visual crop using PBIR positions, and pixel-level comparison against raw RGBA buffers.
All PowerShell fragments live in agentdata/pbip/win32.ps1.
"""
from __future__ import annotations
import csv
import glob
import json
import os
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from . import desktop as DT
from ..model import AgentTable

WIN32_PS1 = os.path.join(os.path.dirname(__file__), "win32.ps1")
Runner = Callable[[list[str], int], tuple[int, str, str]]


def default_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    return DT.default_run(args, timeout=timeout)


def _ps_cmd(action: str, **kwargs) -> list[str]:
    args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", WIN32_PS1, "-Action", action]
    for k, v in kwargs.items():
        if v is not None:
            args.extend([f"-{k}", str(v)])
    return args


def navigate_page(pid: int, page_name: str, run: Runner | None = None) -> dict:
    """Navigate Desktop to requested page name via UIAutomation or keyboard."""
    run = run or default_run
    cmd = _ps_cmd("NavigatePage", TargetPid=pid, PageName=page_name)
    rc, out, err = run(cmd, 15)
    if rc != 0 or not out.strip():
        return {"ok": False, "error": err.strip() or f"failed with rc {rc}"}
    try:
        return json.loads(out)
    except ValueError:
        return {"ok": False, "error": out.strip()}


def capture_window(pid: int, out_path: str, scale: int = 1, run: Runner | None = None) -> dict:
    """Capture Desktop window via PrintWindow (PW_RENDERFULLCONTENT)."""
    run = run or default_run
    cmd = _ps_cmd("CaptureWindow", TargetPid=pid, OutPath=os.path.abspath(out_path), Scale=scale)
    rc, out, err = run(cmd, 25)
    if rc != 0 or not out.strip():
        return {"ok": False, "error": err.strip() or f"failed with rc {rc}"}
    try:
        return json.loads(out)
    except ValueError:
        return {"ok": False, "error": out.strip()}


def crop_image(src_png: str, crop_out: str, x: int, y: int, w: int, h: int, run: Runner | None = None) -> dict:
    """Crop rectangular area from PNG and save as new PNG."""
    run = run or default_run
    cmd = _ps_cmd("CropImage", SrcPng=os.path.abspath(src_png), CropOut=os.path.abspath(crop_out),
                  CropX=x, CropY=y, CropW=w, CropH=h)
    rc, out, err = run(cmd, 15)
    if rc != 0 or not out.strip():
        return {"ok": False, "error": err.strip() or f"failed with rc {rc}"}
    try:
        return json.loads(out)
    except ValueError:
        return {"ok": False, "error": out.strip()}


def png_to_rgba(src_png: str, dst_rgba: str, run: Runner | None = None) -> tuple[int, int, bytes]:
    """Convert PNG to raw RGBA file (header: int32 w, int32 h, followed by pixel bytes)."""
    run = run or default_run
    cmd = _ps_cmd("PngToRgba", SrcPng=os.path.abspath(src_png), DstRgba=os.path.abspath(dst_rgba))
    rc, out, err = run(cmd, 20)
    if os.path.exists(dst_rgba):
        with open(dst_rgba, "rb") as f:
            data = f.read()
            if len(data) >= 8:
                w, h = struct.unpack("<ii", data[:8])
                return w, h, data[8:]
    if rc != 0:
        raise RuntimeError(err.strip() or f"PngToRgba failed with rc {rc}")
    raise FileNotFoundError(f"{dst_rgba} was not written")


def compare_rgba_buffers(raw_a: bytes, raw_b: bytes, w_a: int, h_a: int, w_b: int, h_b: int,
                         threshold: float = 0.5,
                         masks: list[tuple[int, int, int, int]] | None = None) -> dict:
    """Compare two raw RGBA pixel buffers."""
    masks = masks or []
    if (w_a, h_a) != (w_b, h_b):
        return {
            "changed_pct": 100.0,
            "bbox": [0, 0, max(w_a, w_b), max(h_a, h_b)],
            "verdict": "changed",
            "diff_pixels": max(w_a * h_a, w_b * h_b),
            "total_pixels": max(w_a * h_a, w_b * h_b),
            "error": f"Image size mismatch: {w_a}x{h_a} vs {w_b}x{h_b}",
        }

    diff_count = 0
    masked_count = 0
    min_x, min_y = w_a, h_a
    max_x, max_y = -1, -1

    for y in range(h_a):
        for x in range(w_a):
            # Check mask bounds: (x, y, w, h)
            is_masked = False
            for mx, my, mw, mh in masks:
                if mx <= x < mx + mw and my <= y < my + mh:
                    is_masked = True
                    break
            if is_masked:
                masked_count += 1
                continue

            offset = (y * w_a + x) * 4
            if offset + 4 <= len(raw_a) and offset + 4 <= len(raw_b):
                b1, g1, r1, _a1 = raw_a[offset:offset + 4]
                b2, g2, r2, _a2 = raw_b[offset:offset + 4]
                if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) > 30:
                    diff_count += 1
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y

    total_pixels = (w_a * h_a) - masked_count
    changed_pct = (diff_count / total_pixels * 100.0) if total_pixels > 0 else 0.0
    verdict = "changed" if (changed_pct / 100.0) > threshold else "same"
    bbox = [min_x, min_y, max_x, max_y] if diff_count > 0 else None

    return {
        "changed_pct": round(changed_pct, 2),
        "bbox": bbox,
        "verdict": verdict,
        "diff_pixels": diff_count,
        "total_pixels": total_pixels,
    }


def compare_images(img_a: str, img_b: str, threshold: float = 0.5,
                   masks: list[tuple[int, int, int, int]] | None = None,
                   run: Runner | None = None) -> dict:
    """Pixel-difference ratio and changed-region bounding box between two images."""
    tmp_a = img_a + ".rgba"
    tmp_b = img_b + ".rgba"
    masks = masks or []

    try:
        w_a, h_a, raw_a = png_to_rgba(img_a, tmp_a, run=run)
        w_b, h_b, raw_b = png_to_rgba(img_b, tmp_b, run=run)
    finally:
        if os.path.exists(tmp_a):
            try:
                os.remove(tmp_a)
            except OSError:
                pass
        if os.path.exists(tmp_b):
            try:
                os.remove(tmp_b)
            except OSError:
                pass

    return compare_rgba_buffers(raw_a, raw_b, w_a, h_a, w_b, h_b, threshold=threshold, masks=masks)


def find_visual_in_pbir(report_dir: str | Path, visual_needle: str, page_needle: str | None = None) -> tuple[dict | None, dict | None]:
    """Find visual and its page in PBIR on disk, returning (page_dict, visual_dict)."""
    p = Path(report_dir)
    if (p / "definition").is_dir():
        defn = str(p / "definition")
    elif p.is_file() and p.suffix.lower() == ".pbip":
        stem = p.stem
        rep = p.parent / f"{stem}.Report"
        defn = str(rep / "definition") if (rep / "definition").is_dir() else str(p.parent / "definition")
    elif p.is_dir():
        reports = list(p.glob("*.Report/definition"))
        if reports:
            defn = str(reports[0])
        else:
            defn = str(p / "definition")
    else:
        defn = str(p / "definition")

    pages_dir = os.path.join(defn, "pages")
    needle = visual_needle.lower()
    page_sub = page_needle.lower() if page_needle else None

    for pd in sorted(glob.glob(os.path.join(pages_dir, "*"))):
        if not os.path.isdir(pd):
            continue
        pid = os.path.basename(pd)
        pj_path = os.path.join(pd, "page.json")
        pdata = {}
        if os.path.exists(pj_path):
            with open(pj_path, encoding="utf-8-sig") as f:
                pdata = json.load(f)
        pname = pdata.get("displayName") or pid
        if page_sub and pid.lower() != page_sub and pname.lower() != page_sub:
            continue

        for vd in sorted(glob.glob(os.path.join(pd, "visuals", "*"))):
            vj_path = os.path.join(vd, "visual.json")
            if not os.path.exists(vj_path):
                continue
            with open(vj_path, encoding="utf-8-sig") as f:
                vdata = json.load(f)
            vid = vdata.get("name") or os.path.basename(vd)
            vis = vdata.get("visual") or {}
            title = None
            try:
                title_obj = (vis.get("visualContainerObjects") or {}).get("title") or []
                for t in title_obj:
                    lit = (((t.get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal") or {}
                    if lit.get("Value"):
                        title = str(lit["Value"]).strip("'")
            except Exception:
                pass

            if vid.lower() == needle or (title and title.lower() == needle) or (title and needle in title.lower()):
                page_info = {
                    "id": pid,
                    "displayName": pname,
                    "width": pdata.get("width", 1280),
                    "height": pdata.get("height", 720),
                }
                visual_info = {
                    "id": vid,
                    "title": title or vid,
                    "type": vis.get("visualType", "unknown"),
                    "position": vdata.get("position", {"x": 0, "y": 0, "width": 100, "height": 100}),
                }
                return page_info, visual_info
    return None, None


def screenshot_session(pid: int, page: str | None = None, all_pages: bool = False,
                       scale: int = 1, visual: str | None = None, settle_s: float = 0.5,
                       out_dir: str | None = None, pbip_path: str | None = None,
                       run: Runner | None = None) -> tuple[list[dict], list[dict]]:
    """Execute screenshot flow for instance: captures requested or all pages, crops visual if requested."""
    run = run or default_run
    insts = DT.status(pid=pid, candidates=[pbip_path] if pbip_path else None, run=run)
    inst = insts[0] if insts else None
    pages = inst.pages if inst else []

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = out_dir or os.path.join(".agent", "out", "shots", ts)
    os.makedirs(out_dir, exist_ok=True)

    # Determine pages to capture
    to_capture = []
    if all_pages:
        to_capture = pages
    elif page:
        needle = page.lower()
        matched = [p for p in pages if p["id"].lower() == needle or p["displayName"].lower() == needle]
        to_capture = matched if matched else [{"id": page, "displayName": page, "order": 0, "active": True}]
    elif pages:
        # Default: active page or first page
        active = next((p for p in pages if p.get("active")), pages[0])
        to_capture = [active]
    else:
        to_capture = [{"id": "page1", "displayName": "Page 1", "order": 0, "active": True}]

    page_rows = []
    visual_rows = []

    for p in to_capture:
        p_id = p["id"]
        p_name = p.get("displayName", p_id)
        # Navigate if needed
        navigate_page(pid, p_name, run=run)
        if settle_s > 0:
            time.sleep(settle_s)

        out_path = os.path.join(out_dir, f"{p_id}.png").replace("\\", "/")
        t0 = time.perf_counter()
        cap_res = capture_window(pid, out_path, scale=scale, run=run)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        w = cap_res.get("width", 1280)
        h = cap_res.get("height", 720)
        dpi = cap_res.get("dpi", 96)
        via = cap_res.get("via", "printwindow")

        page_rows.append({
            "pid": pid,
            "page": p_id,
            "displayName": p_name,
            "path": out_path,
            "width": w,
            "height": h,
            "dpi": dpi,
            "settle_ms": elapsed_ms,
            "via": via,
        })

        # Visual crop if requested
        if visual and inst and (inst.file or inst.matched):
            target_file = inst.file or inst.matched
            p_info, v_info = find_visual_in_pbir(target_file, visual, page_needle=p_id)
            if p_info and v_info:
                    pos = v_info["position"]
                    page_w = p_info["width"]
                    page_h = p_info["height"]
                    scale_x = w / page_w
                    scale_y = h / page_h
                    cx = int(pos.get("x", 0) * scale_x)
                    cy = int(pos.get("y", 0) * scale_y)
                    cw = int(pos.get("width", 100) * scale_x)
                    ch = int(pos.get("height", 100) * scale_y)

                    crop_path = os.path.join(out_dir, f"{v_info['id']}.png").replace("\\", "/")
                    crop_image(out_path, crop_path, cx, cy, cw, ch, run=run)
                    visual_rows.append({
                        "visual_id": v_info["id"],
                        "title": v_info["title"],
                        "type": v_info["type"],
                        "page": p_id,
                        "bbox": f"[{cx},{cy},{cx+cw},{cy+ch}]",
                        "path": crop_path,
                    })

    if visual_rows:
        tsv_path = os.path.join(out_dir, "visuals.tsv")
        t = AgentTable.from_records(visual_rows, name="visuals", source="ad-pbip screenshot")
        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(t.columns)
            for r in t.rows:
                w.writerow(["" if v is None else v for v in r])

    return page_rows, visual_rows
