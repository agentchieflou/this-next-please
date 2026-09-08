"""The two primitives that make the External Tools ribbon unnecessary (issue #116).

`winui.desktop_windows` answers "which document does the human mean" from Z-order, and
`dmv.catalogs` answers `%database%` from a DMV -- between them the ribbon has no payload left that
would justify the privileged write in epic #112.

Everything here runs on Linux CI: the ctypes path is Windows-only by construction, so the tests
drive the injected-`Runner` seam that `tests/test_desktop_session.py` established and check the
ctypes helper's parsing rules through the pure functions it shares.
"""
import json
import sys

import pytest

from agentdata.pbip import dmv as DMV
from agentdata.pbip import winui as W

# Captured at import, before the autouse fixture in conftest.py swaps it for one that labels the
# injected fake as the enumeration. This is the one test about the REAL preference order, so it
# needs the real function back.
_REAL_SOURCE = W.desktop_windows_source


# --- winui.title_is_desktop -------------------------------------------------------------------

def test_title_ends_with_is_matched_contains_is_not():
    assert W.title_is_desktop("Sample - Power BI Desktop") is True
    assert W.title_is_desktop("Q3 Sales v2 - Power BI Desktop ") is True
    # the failure this rule exists for: a browser tab that merely mentions Desktop mid-string
    assert W.title_is_desktop("Power BI Desktop documentation - Google Chrome") is False
    assert W.title_is_desktop("Power BI Desktop - Excel") is False
    assert W.title_is_desktop("") is False
    assert W.title_is_desktop(None) is False


# --- winui.desktop_windows via the injected Runner ---------------------------------------------

def fake_window_runner(rows):
    """A Runner shaped like `desktop.PBIDESKTOP_TITLES` output, in the order given."""
    def run(args, timeout=30):
        script = args[-1]
        if "PBIDesktop" in script:
            return 0, json.dumps([{"Id": pid, "MainWindowTitle": title,
                                   "Path": "C:\\Program Files\\Microsoft Power BI Desktop\\bin\\PBIDesktop.exe"}
                                  for pid, title in rows]), ""
        return 0, "", ""
    return run


def test_rows_parse_to_pid_title_in_order():
    runner = fake_window_runner([(4242, "Touched Last - Power BI Desktop"),
                                 (1717, "Older - Power BI Desktop")])
    got = W.desktop_windows(run=runner)
    assert got == [(4242, "Touched Last - Power BI Desktop"), (1717, "Older - Power BI Desktop")]
    # index 0 is the whole contract: it is what `handoff --active` hands to `status(pid)`
    assert got[0][0] == 4242


def test_non_desktop_titles_are_dropped():
    runner = fake_window_runner([
        (11, "Power BI Desktop documentation - Google Chrome"),
        (22, "Sales - Power BI Desktop"),
        (33, ""),
    ])
    assert W.desktop_windows(run=runner) == [(22, "Sales - Power BI Desktop")]


def test_one_row_per_pid():
    runner = fake_window_runner([(7, "Sales - Power BI Desktop"), (7, "Sales - Power BI Desktop")])
    assert W.desktop_windows(run=runner) == [(7, "Sales - Power BI Desktop")]


def test_no_desktop_open_is_an_empty_list_not_an_error():
    assert W.desktop_windows(run=fake_window_runner([])) == []


def test_unparsable_pid_is_skipped_not_raised():
    def run(args, timeout=30):
        return 0, json.dumps([{"Id": None, "MainWindowTitle": "Ghost - Power BI Desktop"},
                              {"Id": "9", "MainWindowTitle": "Nine - Power BI Desktop"}]), ""
    assert W.desktop_windows(run=run) == [(9, "Nine - Power BI Desktop")]


def test_runner_failure_is_an_empty_list():
    def run(args, timeout=30):
        return 127, "", "powershell not found"
    assert W.desktop_windows(run=run) == []


def test_session_fake_runner_shape_is_accepted():
    """The fake from tests/test_desktop_session.py drives this unchanged -- same seam, same rows."""
    from tests.test_desktop_session import fake_runner_session

    runner = fake_runner_session("C:\\ws", ppid=1234, title="Sample - Power BI Desktop")
    assert W.desktop_windows(run=runner) == [(1234, "Sample - Power BI Desktop")]


def test_ctypes_path_is_windows_only(monkeypatch):
    """Off Windows there is no user32 to reach, so the Runner is the only implementation.

    Guarded on the platform, because on Windows the opposite is true *and is the point*: production
    passes `ctx.det.run`, a real bound method, so a rule like "an injected runner wins" would quietly
    downgrade a real laptop from Z-order to `Get-Process`. The preference order there is asserted by
    the next test. This one used to assert the Linux answer unconditionally and duly failed on the
    Windows runners.
    """
    if sys.platform == "win32":
        pytest.skip("ctypes is preferred on Windows; test_windows_platform_prefers_ctypes_and_falls_back covers it")
    calls = []
    monkeypatch.setattr(W, "_enum_ctypes", lambda: calls.append("ctypes") or [])
    W.desktop_windows(run=fake_window_runner([(5, "X - Power BI Desktop")]))
    assert calls == []


def test_windows_platform_prefers_ctypes_and_falls_back(monkeypatch):
    monkeypatch.setattr(W, "desktop_windows_source", _REAL_SOURCE)      # the real selection logic
    monkeypatch.setattr(W.sys, "platform", "win32")
    monkeypatch.setattr(W, "_enum_ctypes", lambda: [(1, "Top - Power BI Desktop")])
    assert W.desktop_windows() == [(1, "Top - Power BI Desktop")]

    def boom():
        raise OSError("user32 refused")

    monkeypatch.setattr(W, "_enum_ctypes", boom)
    # a user32 that will not answer degrades to the Runner rather than failing the command
    assert W.desktop_windows(run=fake_window_runner([(2, "Fallback - Power BI Desktop")])) == [
        (2, "Fallback - Power BI Desktop")]


def test_module_imports_and_exports_the_contract():
    assert callable(W.desktop_windows) and callable(W.title_is_desktop)
    assert W.TITLE_SUFFIX == "Power BI Desktop"


# --- dmv.catalogs -- `%database%` without the ribbon -------------------------------------------

def fake_dscmd_runner(rows):
    """dscmd writes the CSV at argv[2]; see `dax.run_dax`."""
    def run(args, timeout=30):
        out_csv = args[2]
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            f.write("[CATALOG_NAME]\n")
            for r in rows:
                f.write(f"{r}\n")
        return 0, "", ""
    return run


def fake_te2_runner(rows):
    """TE2 writes the CSV the generated .csx names; see `dmv.run_dmv_te2`."""
    def run(args, timeout=30):
        csx = args[args.index("-S") + 1]
        with open(csx, encoding="utf-8") as f:
            content = f.read()
        assert "DBSCHEMA_CATALOGS" in content
        out_csv = next(line.split('@"')[1].rstrip('";') for line in content.splitlines()
                       if 'var outFile = @"' in line)
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write('"CATALOG_NAME"\n')
            for r in rows:
                f.write(f'"{r}"\n')
        return 0, "OK", ""
    return run


def test_catalogs_via_dscmd(tmp_path):
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")
    got = DMV.catalogs("localhost:54321", dscmd_exe=str(dscmd),
                       run=fake_dscmd_runner(["a1b2c3d4-0000-4000-8000-000000000001"]))
    assert got == ["a1b2c3d4-0000-4000-8000-000000000001"]


def test_catalogs_via_te2_when_dscmd_missing(tmp_path):
    te2 = tmp_path / "TabularEditor.exe"
    te2.write_text("stub")
    got = DMV.catalogs("localhost:54321", dscmd_exe=str(tmp_path / "nope.exe"),
                       te2_exe=str(te2), run=fake_te2_runner(["Workspace-GUID"]))
    assert got == ["Workspace-GUID"]


def test_catalogs_desktop_has_exactly_one(tmp_path):
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")
    got = DMV.catalogs("localhost:54321", dscmd_exe=str(dscmd), run=fake_dscmd_runner(["only-one"]))
    assert len(got) == 1


def test_catalogs_skips_blank_and_duplicate_rows(tmp_path):
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")
    got = DMV.catalogs("localhost:54321", dscmd_exe=str(dscmd),
                       run=fake_dscmd_runner(["dupe", "", "dupe", "other"]))
    assert got == ["dupe", "other"]


def test_catalogs_with_neither_executor_returns_empty(tmp_path):
    """`database_source: none` is a warn line, not a failed handoff."""
    def run(args, timeout=30):
        raise AssertionError("nothing should be launched when no executor exists")

    assert DMV.catalogs("localhost:54321", dscmd_exe=None, te2_exe=None, run=run) == []


def test_catalogs_when_the_executor_fails_returns_empty(tmp_path):
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")

    def run(args, timeout=30):
        return 1, "", "connection refused"

    assert DMV.catalogs("localhost:54321", dscmd_exe=str(dscmd), run=run) == []


def test_catalogs_sql_is_the_documented_dmv():
    assert DMV.CATALOGS_SQL == "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
