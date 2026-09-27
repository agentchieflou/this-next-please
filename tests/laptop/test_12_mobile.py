"""Section 12: the mobile bridge on the real laptop (#570; the runbook's §Mobile).

The rows a script can answer, M2, M5, M6, M7 and M12, run here in one function: the laptop tier counts
toward the slow-tier cap, and P-14 folds them into one. The phone and tenant rows (M1, M3, M4, M8-M11)
stay by hand. Each row appends one record to `.agent/out/verification-<ts>.toon` and prints it.

**Nothing here asserts a number.** Every row is evidence for the mobile sitting (#582), which decides
`fleet.mobile.expire_s`, `HEARTBEAT_S` and `TICK_S` from it; a first measurement is not a regression. A
row that cannot run on this machine (no bridge folder configured, not Windows) records why, with a
non-zero exit code, instead of skipping the rest.
"""
from __future__ import annotations
import os
import shutil
import statistics
import subprocess
import sys
import time

import pytest

# `real_home`: the rows read this laptop's own `fleet.mobile.folder` and write into its real bridge folder
# (M2's one export pass, M12's scratch subfolder), not the temporary home every other test gets.
pytestmark = [pytest.mark.laptop, pytest.mark.real_home]

SECTION = "test_12_mobile"
SNAPSHOT_TICKS = 6          # M5: six ticks, as the row asks
WRITES = 200                # M12
PINNED, UNPINNED, RECALL = 0x00080000, 0x00100000, 0x00400000


def _folder() -> tuple[str, str]:
    """The configured bridge folder, or "" and the refusal's words. Read as the doctor reads it (the bridge may be
    off while the sitting prepares); nothing is created."""
    from agentdata.fleet import bridge

    try:
        return bridge.check_folder(need_enabled=False), ""
    except bridge.BridgeError as e:
        return "", str(e)


def _m2(folder: str) -> dict:
    """One export pass, then every `.tmp` left anywhere under the folder. The web view is the operator's to read."""
    from agentdata.fleet import bridge

    result = bridge.export_once()
    left = [os.path.join(d, f) for d, _, files in os.walk(folder) for f in files if f.endswith(".tmp")]
    return {"written": len(result["written"]), "how": ",".join(result["how"]), "tmp_left": len(left),
            "look": "OneDrive activity centre: one upload per file; web view: no .tmp listed"}


def _m5() -> dict:
    from agentdata.fleet import bridge
    from agentdata.fleet.serve import fleet_snapshot

    costs, repos = [], 0
    for _ in range(SNAPSHOT_TICKS):
        started = time.perf_counter()
        repos = len(fleet_snapshot().get("repos") or [])
        costs.append((time.perf_counter() - started) * 1000)
    return {"agents": repos, "serve_up": bridge._serve_up(), "median_ms": round(statistics.median(costs), 1),
            "worst_ms": round(max(costs), 1), "decides": "TICK_S"}


def _m6(folder: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k.lower().startswith("onedrive")}
    user_folder = ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts\Business1") as key:
            user_folder = str(winreg.QueryValueEx(key, "UserFolder")[0])
    except OSError as e:
        user_folder = f"(unreadable: {e})"
    commercial = env.get("OneDriveCommercial") or env.get("ONEDRIVECOMMERCIAL") or ""

    def under(root: str) -> bool:
        return bool(root and folder) and os.path.normcase(folder).startswith(os.path.normcase(root))

    return {"env": ";".join(f"{k}={v}" for k, v in sorted(env.items())), "onedrive_commercial": commercial,
            "business1_user_folder": user_folder, "agree": bool(commercial) and commercial == user_folder,
            "folder_under_commercial": under(commercial), "folder_under_user_folder": under(user_folder)}


def _m7(folder: str) -> dict:
    inbox = os.path.join(folder, "inbox")
    attrs = os.stat(inbox).st_file_attributes
    p = subprocess.run(["attrib", inbox], capture_output=True, text=True, errors="replace")
    return {"inbox": inbox, "attributes": hex(attrs), "pinned": bool(attrs & PINNED),
            "unpinned": bool(attrs & UNPINNED), "recall_on_data_access": bool(attrs & RECALL),
            "attrib": (p.stdout or p.stderr).strip()}


def _m12(folder: str) -> dict:
    """200 writes into a subfolder of the bridge folder, outside `outbox/` so no flow reads them; removed after."""
    from agentdata import textio

    scratch = os.path.join(folder, "runbook-m12")
    os.makedirs(scratch, exist_ok=True)
    hows: dict[str, int] = {}
    try:
        for i in range(WRITES):
            report: dict = {}
            textio.write_text(os.path.join(scratch, f"write-{i % 20:02d}.json"), f'{{"i": {i}}}\n', report=report)
            hows[report.get("how", "")] = hows.get(report.get("how", ""), 0) + 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"writes": WRITES, "atomic": hows.get("atomic", 0), "in_place": hows.get("in-place", 0)}


def test_the_mobile_rows_a_script_can_answer(recorder):
    folder, why = _folder()
    rows = {
        "M2": (lambda: _m2(folder), bool(folder), why),
        "M5": (_m5, True, ""),
        "M6": (lambda: _m6(folder), os.name == "nt", "not Windows: no OneDrive sync client"),
        "M7": (lambda: _m7(folder), bool(folder) and os.name == "nt", why or "not Windows: no st_file_attributes"),
        "M12": (lambda: _m12(folder), bool(folder), why),
    }
    for step, (measure, can, reason) in rows.items():
        started = time.time()
        if not can:
            recorder.step(SECTION, step, "(not run)", 1, detail=reason, seconds=0)
            print(f"{step}: not run: {reason}")
            continue
        try:
            fields = measure()
            code, detail = 0, ""
        except Exception as e:                           # noqa: BLE001 - a row's failure is evidence, not a stop
            fields, code, detail = {}, 1, f"{type(e).__name__}: {e}"
        recorder.step(SECTION, step, f"{sys.executable} (in process)", code, detail=detail,
                      seconds=time.time() - started, **fields)
        print(f"{step}: {detail or fields}")
    assert {r["step"] for r in recorder.records if r["section"] == SECTION} == set(rows)
