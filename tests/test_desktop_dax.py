import json, os, sys
import pytest
from agentdata.pbip import dax as D
from agentdata.pbip import desktop as DT
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sample.pbip")


def make_ws(tmp_path, port=54321):
    ws = tmp_path / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces" / "guid1" / "Data"
    ws.mkdir(parents=True)
    (ws / "msmdsrv.port.txt").write_bytes(str(port).encode("utf-16"))  # BOM + UTF-16, like Desktop
    return ws


def fake_run_factory(ws, ppid=4242, title="Sample - Power BI Desktop"):
    def run(args, timeout=30):
        script = args[-1]
        if "msmdsrv.exe" in script:
            return 0, json.dumps({"ProcessId": 999, "ParentProcessId": ppid, "CommandLine": f'"C:\\PBI\\msmdsrv.exe" -s "{ws}" -n "AnalysisServicesWorkspace_abc" -c 1'}), ""
        if "PBIDesktop" in script:
            return 0, json.dumps([{"Id": ppid, "MainWindowTitle": title}]), ""
        return 1, "", "unknown"
    return run


def test_discover_via_cim(tmp_path):
    ws = make_ws(tmp_path)
    inst = DT.discover(run=fake_run_factory(str(ws)), candidates=[str(tmp_path / "repo" / "Sample.pbip")])
    assert len(inst) == 1
    i = inst[0]
    assert i.port == 54321 and i.server == "localhost:54321" and i.pid == 4242 and i.workspace_name == "AnalysisServicesWorkspace_abc"
    assert i.title == "Sample - Power BI Desktop" and i.matched.endswith("Sample.pbip") and i.source == "cim"


def test_discover_glob_fallback(tmp_path):
    make_ws(tmp_path, 60001)
    inst = DT.discover(run=lambda a, t=30: (1, "", "no powershell"), localappdata=str(tmp_path))
    assert len(inst) == 1 and inst[0].port == 60001 and inst[0].source == "glob" and inst[0].pid is None


def test_parse_helpers():
    assert DT.parse_cmdline('msmdsrv.exe -s "C:\\Users\\me\\App Data\\Data" -n WS1') == {"s": "C:\\Users\\me\\App Data\\Data", "n": "WS1"}
    assert DT.title_name("Sales Report - Power BI Desktop") == "Sales Report" and DT.title_name("Notepad") is None
    assert DT.match_file("sales", ["C:/r/Sales.pbip"]) == "C:/r/Sales.pbip" and DT.match_file("x", ["C:/r/Sales.pbip"]) is None
    assert DT.read_port(None) is None


def test_literals_and_headers():
    assert D.literal("'Done'") == '"Done"' and D.literal("2026L") == "2026" and D.literal("12.5D") == "12.5"
    assert D.literal("null") == "BLANK()" and D.literal("true") == "TRUE"
    assert D.literal("datetime'2025-01-31T00:00:00'") == "DATE(2025,1,31)" and D.literal("datetime'2025-01-31T10:30:00'") == "DATE(2025,1,31) + TIME(10,30,0)"
    assert D.clean_header("Sales[Margin]") == "Margin" and D.clean_header("[Value]") == "Value" and D.clean_header("plain") == "plain"


def test_visual_query_from_fixture():
    model, report, _ = N.load_all(FIX)
    idx = N.ModelIndex(model, report)
    bar = next(v for v in report.pages[0].visuals if v.id == "f1a2b3c4d5e6f7a8b9c0")
    dax, notes = D.visual_query(bar, idx, extra_filters=list(report.filters))
    assert "SUMMARIZECOLUMNS(" in dax and "'Calendar'[Year]" in dax and '"Margin", [Margin]' in dax and "TOPN(500" in dax
    assert "TREATAS({2026}, 'Calendar'[Year])" in dax and notes == []
    detail = report.pages[1].visuals[0]
    dax2, notes2 = D.visual_query(detail, idx, extra_filters=list(report.pages[1].filters))
    assert "'Calendar'[Year]" in dax2 and '"Sum of Quantity", CALCULATE(SUM(\'Sales\'[Quantity]))' in dax2
    assert "TREATAS({\"Done\"}, 'Sales'[Status])" in dax2 and notes2 == []
    assert "[Margin]" not in dax2.split("EVALUATE")[1]  # conditional-format measure is not a projection


def test_run_dax_with_fake_dscmd(tmp_path):
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")
    calls = []

    def run(args, timeout=300):
        calls.append(args)
        out_csv = args[2]
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write("Calendar[Year],[Margin]\n2025,10.5\n2026,20\n")
        return 0, "", ""

    t = D.run_dax("EVALUATE ROW(1)", "localhost:1", str(dscmd), run=run, name="v")
    assert t.columns == ["Year", "Margin"] and t.rows == [[2025, 10.5], [2026, 20]] and "-f" in calls[0]
    D.run_dax("EVALUATE ROW(1)", "localhost:1", str(dscmd), database="db", run=run, file_flag=False)
    assert "-q" in calls[1] and "-d" in calls[1]
    with pytest.raises(D.DaxError):
        D.run_dax("x", "localhost:1", str(dscmd), run=lambda a, t=300: (1, "", "Connection refused"))
    with pytest.raises(D.DaxError):
        D.run_dax("x", "localhost:1", str(tmp_path / "missing.exe"))


def test_cli_visual_query_dry_run_and_desktop(monkeypatch, capsys, tmp_path):
    from agentdata import cli_pbip
    monkeypatch.setattr("agentdata.model.OUT_DIR", str(tmp_path))
    monkeypatch.setattr("agentdata.cli_pbip.OUT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "visual-query", FIX, "--visual", "Margin by Year", "--dry-run"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    out = capsys.readouterr().out
    assert ei.value.code == 0 and "SUMMARIZECOLUMNS" in out and "dax_path" in out
    monkeypatch.setattr(DT, "discover", lambda **kw: [])
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "desktop"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    assert ei.value.code == 0 and "instances: 0" in capsys.readouterr().out
