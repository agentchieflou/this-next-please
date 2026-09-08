"""The #113 read-only probe, driven entirely from fakes.

What these tests can and cannot prove is worth writing down, because the issue's acceptance criteria
are output from a Windows laptop and this suite runs on Linux CI. They prove the *instrument*: every
row renders, a refused registry read is a row rather than a traceback, the two runs of an unchanged
machine diff to nothing, and the probe writes no file anywhere. They prove nothing at all about
where Python lives on the reporter's machine -- only `ad-pbip probe`, run there, answers that.
"""
from __future__ import annotations
import json
import os
import re
import sys

import pytest

from agentdata.pbip import probe as PB

PATH_VALUE = r"C:\Python312;C:\Python312\Scripts;C:\Windows\System32"
PRODUCT_JSON = {"EnableExternalTools": 1, "PSPath": "Microsoft.PowerShell.Core\\Registry::HKLM",
                "PSProvider": "Registry"}
POLICY_JSON = {"EnableExternalTools": 0, "PSChildName": "Power BI Desktop"}
_KEY = re.compile(r"-Path '(?P<hive>HK[LC][MU]):\\(?P<key>[^']+)'")


def fake_runner(*, where_python=r"C:\Python312\python.exe", where_py=r"C:\Windows\py.exe",
                help_rc=0, py_help_rc=1, path_value=PATH_VALUE, windows=((4242, "Sales - Power BI Desktop"),),
                registry=None, python_installs=r"C:\Python312\\", te2_version="2.25.1",
                deny=(), missing=()):
    """One runner standing in for cmd.exe and PowerShell, matching the way `tests/` fakes always do.

    `deny` and `missing` name registry keys (by their `HKLM:\\SOFTWARE\\...` path fragment) that
    answer with an access refusal or with nothing at all -- the two states a locked-down laptop is
    most likely to be in.
    """
    reg = {"product": PRODUCT_JSON, "policy": POLICY_JSON} if registry is None else registry

    def run(args, timeout=30):
        if args[0] == "cmd":
            command = args[-1]
            if command == "where python":
                return (0, where_python + "\n", "") if where_python else (1, "", "")
            if command == "where py":
                return (0, where_py + "\n", "") if where_py else (1, "", "")
            if command == "python -V":
                return 0, "Python 3.12.4\n", ""
            if command == "python -m agentdata --help":
                return (0, "usage: agentdata [-h] ...\n", "") if help_rc == 0 else (help_rc, "", "No module named agentdata")
            if command == "py -m agentdata --help":
                return (0, "usage: agentdata [-h] ...\n", "") if py_help_rc == 0 else (py_help_rc, "", "No module named agentdata")
            if command == "echo %PATH%":
                return 0, path_value + "\n", ""
            return 0, "", ""

        script = args[-1]
        if "PBIDesktop" in script:
            return 0, json.dumps([{"Id": pid, "MainWindowTitle": title} for pid, title in windows]), ""
        if "LanguageMode" in script:
            return 0, "ps 5.1.19041.4291 / FullLanguage\n", ""
        if "VersionInfo" in script:
            return (0, te2_version + "\n", "") if te2_version else (1, "", "not found")
        if "Get-ChildItem" in script:
            return 1, "", ""
        m = _KEY.search(script)
        if m:
            key = m.group("key")
            if any(frag in key for frag in deny):
                return 1, "", "Get-ItemProperty : Requested registry access is not allowed."
            if any(frag in key for frag in missing):
                return 0, "", ""
            if "PythonCore" in key:
                return (0, json.dumps({"(default)": python_installs, "PSProvider": "Registry"}), "") \
                    if python_installs else (0, "", "")
            if "Policies" in key:
                return 0, json.dumps(reg["policy"]), ""
            return 0, json.dumps(reg["product"]), ""
        return 0, "", ""

    return run


def by_name(rows):
    return {r["name"]: r for r in rows}


def snapshot(root):
    out = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(base, name)
            try:
                out[p] = os.path.getsize(p)
            except OSError:
                out[p] = -1
    return out


# ------------------------------------------------------------------------------- shape and safety


def test_every_row_has_the_same_four_keys_and_no_line_breaks():
    rows = PB.report(run=fake_runner())
    assert rows, "the report is never empty"
    for row in rows:
        assert list(row) == ["q", "name", "value", "reason"]
        assert row["q"] in ("Q1", "Q3", "Q4", "Q5")
        assert isinstance(row["value"], str) and isinstance(row["reason"], str)
        assert "\n" not in row["value"] and "\n" not in row["reason"]
        assert row["name"] and row["value"], f"{row['name']} must always say something"


def test_all_four_questions_are_answered():
    rows = PB.report(run=fake_runner())
    names = by_name(rows)
    assert {r["q"] for r in rows} == {"Q1", "Q3", "Q4", "Q5"}
    for expected in ("python.executable", "python.ctypes_user32", "where.python", "where.py",
                     "cmd.agentdata_help", "cmd.path", "powershell.mode", "registry.python.hklm",
                     "registry.python.hkcu", "verdict.launcher", "zorder.count", "verdict.zorder",
                     "te2.exe", "te2.custom_actions", "verdict.te2", "registry.product.hklm",
                     "registry.product.hkcu", "registry.policy.hklm", "registry.policy.hkcu"):
        assert expected in names, expected


def test_two_runs_of_an_unchanged_machine_diff_to_nothing():
    run = fake_runner()
    assert PB.report(run=run) == PB.report(run=run)


def test_the_probe_writes_nothing(tmp_path):
    local = tmp_path / "local"
    (local / "TabularEditor").mkdir(parents=True)
    (local / "TabularEditor" / "CustomActions.json").write_text("[]", encoding="utf-8")
    enforce = tmp_path / "Enforce"
    enforce.mkdir()
    before = snapshot(tmp_path)
    PB.report(run=fake_runner(), localappdata=str(local), enforce_root=str(enforce))
    assert snapshot(tmp_path) == before


def test_the_module_never_opens_a_file_for_writing():
    src = open(PB.__file__, encoding="utf-8").read()
    for forbidden in ("write_text(", "makedirs(", '"w"', "'w'", "shutil.copy"):
        assert forbidden not in src, f"a read-only probe must not contain {forbidden}"


# --------------------------------------------------------------------------------- Q1: the shape


def test_verdict_is_cmd_python_when_a_bare_python_answers():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["where.python"]["value"] == r"C:\Python312\python.exe"
    assert rows["cmd.agentdata_help"]["value"].startswith("answers:")
    assert rows["verdict.launcher"]["value"] == "cmd-python"
    assert "user-agnostic" in rows["verdict.launcher"]["reason"]


def test_verdict_is_cmd_py_when_only_the_launcher_is_on_path():
    rows = by_name(PB.report(run=fake_runner(where_python="", help_rc=1, py_help_rc=0)))
    assert rows["where.python"]["value"] == "not found"
    assert rows["where.python"]["reason"]
    assert rows["verdict.launcher"]["value"] == "cmd-py"


def test_a_venv_only_python_demands_a_per_user_launcher(monkeypatch, tmp_path):
    """The row that decides #114: a `python` that exists only because a venv is active is not an
    answer, because Desktop launches the tool with the user's PATH."""
    venv = tmp_path / "venv"
    (venv / "Scripts").mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python312"))
    rows = by_name(PB.report(run=fake_runner(where_python=str(venv / "Scripts" / "python.exe"))))
    assert rows["python.venv"]["value"].endswith("venv")
    assert rows["verdict.launcher"]["value"] == "per-user-launcher"
    assert "agentdata\\bin" in rows["verdict.launcher"]["reason"]


def test_a_python_that_cannot_import_agentdata_demands_a_per_user_launcher():
    rows = by_name(PB.report(run=fake_runner(help_rc=9009, py_help_rc=9009)))
    assert rows["verdict.launcher"]["value"] == "per-user-launcher"
    assert rows["cmd.agentdata_help"]["value"] == "no answer"
    assert "No module named agentdata" in rows["cmd.agentdata_help"]["reason"]


def test_no_cmd_at_all_is_unknown_not_a_guess():
    def dead(args, timeout=30):
        return 127, "", "cmd: executable not found -- install cmd and put it on PATH"

    rows = by_name(PB.report(run=dead))
    assert rows["verdict.launcher"]["value"] == "unknown"
    assert "fresh cmd.exe" in rows["verdict.launcher"]["reason"]


def test_the_launcher_dir_row_says_whether_it_is_on_path(tmp_path):
    local = tmp_path / "local"
    (local / "agentdata" / "bin").mkdir(parents=True)
    on = fake_runner(path_value=str(local / "agentdata" / "bin") + r";C:\Windows\System32")
    rows = by_name(PB.report(run=on, localappdata=str(local)))
    assert "exists" in rows["launcher.dir"]["value"] and "on PATH" in rows["launcher.dir"]["value"]

    rows = by_name(PB.report(run=fake_runner(), localappdata=str(tmp_path / "empty")))
    assert "missing" in rows["launcher.dir"]["value"] and "not on PATH" in rows["launcher.dir"]["value"]


def test_python_install_hive_is_recorded_for_the_ticket():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["registry.python.hklm"]["value"] == r"C:\Python312\\"
    rows = by_name(PB.report(run=fake_runner(python_installs="")))
    assert rows["registry.python.hklm"]["value"] == "(no PythonCore key)"


def test_the_interpreter_running_the_probe_is_reported_truthfully():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["python.executable"]["value"].endswith(os.path.basename(sys.executable))
    if sys.platform != "win32":
        assert rows["python.ctypes_user32"]["value"] == "n/a"
        assert "not Windows" in rows["python.ctypes_user32"]["reason"]


# ---------------------------------------------------------------------------------- Q4: Z-order


def test_zorder_rows_come_from_winui_in_order():
    run = fake_runner(windows=((11, "Sales - Power BI Desktop"), (22, "Finance - Power BI Desktop")))
    rows = by_name(PB.report(run=run))
    assert rows["zorder.count"]["value"] == "2"
    assert rows["zorder.0"]["value"] == "pid 11  Sales - Power BI Desktop"
    assert rows["zorder.1"]["value"] == "pid 22  Finance - Power BI Desktop"
    # Off Windows the rows came through the process table, and the report says which measurement
    # answered rather than calling row 0 "the window on top". Claiming Z-order here would be the
    # probe fabricating the one fact only the laptop can supply.
    assert rows["zorder.source"]["value"] == "process-table"
    assert "NOT the window on top" in rows["zorder.0"]["reason"]


def test_the_probe_says_touched_last_only_when_enumwindows_answered(monkeypatch):
    """`verdict.zorder: yes` used to be printed on any Windows box with a window open.

    Including one whose `EnumWindows` call had just failed and fallen through to `Get-Process`, so
    the probe pasted into the issue asserted a Z-order nothing had measured.
    """
    monkeypatch.setattr(PB.winui, "desktop_windows_source",
                        lambda run=None: ([(11, "Sales - Power BI Desktop")], PB.winui.SOURCE_ENUM))
    monkeypatch.setattr(PB.sys, "platform", "win32")
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["zorder.source"]["value"] == "enum-windows"
    assert "touched last" in rows["zorder.0"]["reason"]
    assert rows["verdict.zorder"]["value"] == "yes"

    monkeypatch.setattr(PB.winui, "desktop_windows_source",
                        lambda run=None: ([(11, "Sales - Power BI Desktop")], PB.winui.SOURCE_TABLE))
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["zorder.source"]["value"] == "process-table"
    assert rows["verdict.zorder"]["value"] == "no"
    assert "no_zorder" in rows["verdict.zorder"]["reason"]


def test_a_browser_tab_named_power_bi_desktop_is_not_a_window():
    run = fake_runner(windows=((11, "Power BI Desktop documentation - Google Chrome"),))
    rows = by_name(PB.report(run=run))
    assert rows["zorder.count"]["value"] == "0"


def test_no_desktop_window_is_a_row_not_an_error():
    rows = by_name(PB.report(run=fake_runner(windows=())))
    assert rows["zorder.count"]["value"] == "0"
    assert rows["zorder.count"]["reason"]


@pytest.mark.skipif(sys.platform == "win32", reason="the honesty rule only applies off Windows")
def test_off_windows_the_zorder_verdict_refuses_to_claim_anything():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["verdict.zorder"]["value"] == "unknown"
    assert "only be measured on the laptop" in rows["verdict.zorder"]["reason"]
    assert "process table" in rows["zorder.count"]["reason"]


# ---------------------------------------------------------------------------- Q3: Tabular Editor


def test_te2_is_found_by_walking_the_developer_folder(tmp_path):
    enforce = tmp_path / "Enforce" / "TabularEditor2"
    enforce.mkdir(parents=True)
    (enforce / "TabularEditor.exe").write_bytes(b"MZ")
    rows = by_name(PB.report(run=fake_runner(), enforce_root=str(tmp_path / "Enforce")))
    assert rows["te2.exe"]["value"].endswith("TabularEditor2/TabularEditor.exe")
    assert rows["te2.version"]["value"] == "2.25.1"
    assert rows["verdict.te2"]["value"] == "machine side ready"


def test_no_te2_under_the_developer_folder_closes_the_optional_slice(tmp_path):
    (tmp_path / "Enforce").mkdir()
    rows = by_name(PB.report(run=fake_runner(), enforce_root=str(tmp_path / "Enforce")))
    assert rows["te2.exe"]["value"] == "not found"
    assert rows["te2.version"]["value"] == "n/a"
    assert rows["verdict.te2"]["value"] == "no"


def test_the_custom_actions_file_is_listed_by_name(tmp_path):
    local = tmp_path / "local"
    (local / "TabularEditor").mkdir(parents=True)
    (local / "TabularEditor" / "CustomActions.json").write_text(
        json.dumps([{"Name": "Hand off to agentdata"}, {"Name": "Zzz"}]), encoding="utf-8")
    rows = by_name(PB.report(run=fake_runner(), localappdata=str(local)))
    assert rows["te2.custom_actions"]["value"] == "2 action(s): Hand off to agentdata, Zzz"
    assert "CustomActions.json" in rows["te2.localappdata_dir"]["value"]


def test_a_malformed_custom_actions_file_is_reported_as_the_refusal_state(tmp_path):
    local = tmp_path / "local"
    (local / "TabularEditor").mkdir(parents=True)
    (local / "TabularEditor" / "CustomActions.json").write_text("[{oops", encoding="utf-8")
    rows = by_name(PB.report(run=fake_runner(), localappdata=str(local)))
    assert rows["te2.custom_actions"]["value"] == "unparseable"
    assert "drops ALL custom actions" in rows["te2.custom_actions"]["reason"]


def test_a_missing_tabular_editor_folder_is_not_a_failure(tmp_path):
    rows = by_name(PB.report(run=fake_runner(), localappdata=str(tmp_path / "local")))
    assert rows["te2.localappdata_dir"]["value"].endswith("(missing)")
    assert rows["te2.custom_actions"]["value"] == "missing"


def test_the_two_answers_only_a_person_can_give_are_printed_as_instructions():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["te2.local_instance"]["value"] == PB.HUMAN
    assert "Local instance" in rows["te2.local_instance"]["reason"]
    assert rows["te2.save_as_custom_action"]["value"] == PB.HUMAN
    assert "Save as Custom Action" in rows["te2.save_as_custom_action"]["reason"]


# ---------------------------------------------------------------------------------- Q5: registry


def test_both_hives_of_both_keys_are_read():
    rows = by_name(PB.report(run=fake_runner()))
    assert rows["registry.product.hklm"]["value"] == "EnableExternalTools=1"
    assert rows["registry.policy.hkcu"]["value"] == "EnableExternalTools=0"
    for name in ("registry.product.hklm", "registry.product.hkcu",
                 "registry.policy.hklm", "registry.policy.hkcu"):
        assert "PSPath" not in rows[name]["value"], "PowerShell's provider noise is not evidence"


def test_a_refused_registry_read_is_a_row_not_a_traceback():
    rows = by_name(PB.report(run=fake_runner(deny=("Policies",))))
    for name in ("registry.policy.hklm", "registry.policy.hkcu"):
        assert rows[name]["value"] == "access denied"
        assert "not allowed" in rows[name]["reason"]
    assert rows["registry.product.hklm"]["value"] == "EnableExternalTools=1"


def test_a_key_that_is_not_there_says_so():
    rows = by_name(PB.report(run=fake_runner(missing=("Policies",))))
    assert rows["registry.policy.hklm"]["value"] == "(key not present)"
    assert rows["registry.policy.hklm"]["reason"] == ""


def test_registry_values_are_sorted_so_two_runs_diff_to_nothing():
    reg = {"product": {"Zebra": 1, "Alpha": 2, "PSDrive": "HKLM"}, "policy": {}}
    rows = by_name(PB.report(run=fake_runner(registry=reg)))
    assert rows["registry.product.hklm"]["value"] == "Alpha=2; Zebra=1"
    assert rows["registry.policy.hklm"]["value"] == "(no values)"


def test_read_key_without_a_runner_off_windows_is_a_reason_not_a_crash():
    if sys.platform == "win32":
        pytest.skip("winreg answers on the laptop")
    value, reason = PB.read_key("HKLM", PB.POLICY_KEY, run=None, native=True)
    assert value == "unreadable" and "winreg" in reason


# ------------------------------------------------------------------------- the default launcher


def test_default_run_turns_a_missing_program_into_a_row_with_a_hint():
    code, out, err = PB.default_run(["ad-definitely-not-a-real-program", "--help"], timeout=5)
    assert code == 127 and out == ""
    assert "not found" in err and "PATH" in err


def test_the_whole_report_runs_off_windows_with_no_runner_at_all():
    """No fakes, no Windows: every external read fails, and every failure is still a row."""
    if sys.platform == "win32":
        pytest.skip("this is the CI machine's path, not the laptop's")
    rows = PB.report()
    names = by_name(rows)
    assert names["verdict.launcher"]["value"] == "unknown"
    assert all(row["value"] for row in rows)
