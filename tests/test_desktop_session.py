import json
import os
import sys
import pytest
from agentdata.pbip import desktop as DT
from agentdata import cli_pbip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sample.pbip")


def make_ws(tmp_path, port=54321):
    ws = tmp_path / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces" / "guid1" / "Data"
    ws.mkdir(parents=True)
    (ws / "msmdsrv.port.txt").write_bytes(str(port).encode("utf-16"))
    return ws


def fake_runner_session(ws, ppid=4242, title="Sample - Power BI Desktop", close_state="exited"):
    def run(args, timeout=30):
        script = args[-1]
        if "CloseMainWindow" in script:
            return 0, close_state, ""
        if "msmdsrv.exe" in script:
            return 0, json.dumps({"ProcessId": 999, "ParentProcessId": ppid, "CommandLine": f'"C:\\PBI\\msmdsrv.exe" -s "{ws}" -n "AnalysisServicesWorkspace_abc" -c 1'}), ""
        if "PBIDesktop" in script:
            return 0, json.dumps([{"Id": ppid, "MainWindowTitle": title, "Path": "C:\\Program Files\\Microsoft Power BI Desktop\\bin\\PBIDesktop.exe", "Version": "2.138.1004.0"}]), ""
        if "UIAutomationClient" in script and "AutomationElement" in script:
            return 0, "True", ""
        if "WaitForInputIdle" in script:
            return 0, "True", ""
        if "Get-Process -Id" in script:
            return 0, json.dumps({"Id": ppid}), ""
        if "Win32_Process" in script and "ExecutablePath" in script:
            return 0, json.dumps({"ExecutablePath": "C:\\Program Files\\Microsoft Power BI Desktop\\bin\\PBIDesktop.exe"}), ""
        return 0, "", ""
    return run


def test_status_with_pages_and_version(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234, title="Sample - Power BI Desktop")
    insts = DT.status(candidates=[FIX], run=runner)
    assert len(insts) == 1
    i = insts[0]
    assert i.pid == 1234
    assert i.port == 54321
    assert i.loaded is True
    assert i.desktop_version == "2.138.1004.0"
    assert i.install == "msi"
    assert len(i.pages) == 2
    assert i.pages[0]["id"] == "page1" and i.pages[0]["active"] is True
    assert i.pages[1]["id"] == "page2" and i.pages[1]["active"] is False


def test_status_pid_filter(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234)
    assert len(DT.status(pid=1234, candidates=[FIX], run=runner)) == 1
    assert len(DT.status(pid=9999, candidates=[FIX], run=runner)) == 0


def test_probe_unsaved_title_marker():
    assert DT.probe_unsaved(1234, title="*Sales - Power BI Desktop") == "true"
    assert DT.probe_unsaved(1234, title="Sales* - Power BI Desktop") == "true"


def test_probe_unsaved_uia_fallback():
    def fake_run(args, timeout=30):
        if "Save" in args[-1]:
            return 0, "False", ""
        return 0, "", ""
    assert DT.probe_unsaved(1234, title="Sales - Power BI Desktop", run=fake_run) == "false"


def test_close_clean(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234, close_state="exited")
    res = DT.close(1234, run=runner)
    assert res["ok"] is True
    assert res["closed"] is True


def test_close_unsaved_prompt_refuses_default(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234, close_state="save_prompt")
    res = DT.close(1234, run=runner)
    assert res["ok"] is False
    assert res["fail"] == "unsaved_changes"
    assert "--save or --discard" in res["hint"]


def test_close_unsaved_prompt_save_and_discard(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234, close_state="save_prompt")
    res_save = DT.close(1234, save=True, run=runner)
    assert res_save["ok"] is True and res_save["action"] == "saved_and_closed"

    res_discard = DT.close(1234, discard=True, run=runner)
    assert res_discard["ok"] is True and res_discard["action"] == "discarded_and_closed"


def test_open_and_wait_immediate(monkeypatch):
    monkeypatch.setattr(DT, "launch", lambda p, exe=None: {"launched": p, "via": "mock"})
    res = DT.open_and_wait(FIX, wait_secs=0)
    assert res["ok"] is True and res["wait"] == 0


def test_open_and_wait_polls(monkeypatch, tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234)
    monkeypatch.setattr(DT, "launch", lambda p, exe=None: {"launched": p, "via": "mock"})
    res = DT.open_and_wait(FIX, wait_secs=5, run=runner)
    assert res["ok"] is True
    assert res["pid"] == 1234 and res["port"] == 54321


def test_reload_native(monkeypatch, tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234)
    monkeypatch.setattr(DT, "launch", lambda p, exe=None: {"launched": p, "via": "mock"})
    res = DT.reload(1234, candidates=[FIX], run=runner)
    assert res["ok"] is True
    assert res["reloaded_via"] == "native"
    assert res["pid"] == 1234


def test_capabilities_probes(tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234)
    caps = DT.capabilities(pid=1234, run=runner)
    assert len(caps) == 9
    names = [c["capability"] for c in caps]
    assert names == ["as_port", "xmla_local", "external_tools", "uia", "printwindow", "bridge_pipe", "bridge_manifest", "developer_visual", "pbiviz"]
    as_port_cap = next(c for c in caps if c["capability"] == "as_port")
    assert as_port_cap["available"] is True
    assert "54321" in as_port_cap["evidence"]


def test_cli_desktop_subcommands(capsys, monkeypatch, tmp_path):
    ws = make_ws(tmp_path, port=54321)
    runner = fake_runner_session(str(ws), ppid=1234)
    monkeypatch.setattr(DT, "default_run", runner)
    monkeypatch.setattr(DT, "launch", lambda p, exe=None: {"launched": p, "via": "mock"})

    # 1. ad-pbip desktop status
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "desktop", "status", "--pid", "1234"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    assert ei.value.code == 0
    assert "desktop" in capsys.readouterr().out

    # 2. ad-pbip capabilities
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "capabilities", "--pid", "1234"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    assert ei.value.code == 0
    out_caps = capsys.readouterr().out
    assert "capabilities" in out_caps and "as_port" in out_caps

    # 3. ad-pbip desktop close with unsaved refusal
    runner_unsaved = fake_runner_session(str(ws), ppid=1234, close_state="save_prompt")
    monkeypatch.setattr(DT, "default_run", runner_unsaved)
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "desktop", "close", "--pid", "1234"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    assert ei.value.code == 1
    assert "unsaved_changes" in capsys.readouterr().out
