"""`ad-uat rollup` and `ad-view <file>.csv`: the UAT steps a fleet agent could not take.

Operator report, 2026-10-02: a Jira to Power BI UAT could not be finished from the desk. Two of its
steps needed a tool a headless turn is never given -- "aggregate a finer tier with a ≤10-line script"
needed `write` and `python`, and viewing a dscmd export needed `python -m agentdata.csv2toon`. Both
are commands now, on the allow-list already (`shell(ad-uat)`, `shell(ad-view)`).
"""
from __future__ import annotations
import os
import subprocess
import sys

from agentdata.fleet import launch as L
from agentdata.model import AgentTable
from agentdata.uat import rollup as RU

from subproc import agentdata_env


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "agentdata", *args], capture_output=True, text=True,
                          encoding="utf-8", env=agentdata_env(), cwd=cwd, timeout=60)


def test_rollup_sums_and_counts_by_the_grain_in_order_of_first_appearance():
    fine = AgentTable("hist", ["sprint", "key", "points"],
                      [["S2", "A-3", None], ["S1", "A-1", 3], ["S1", "A-2", 5], ["S2", "A-4", 2.5]])
    out = RU.rollup(fine, ["sprint"], ["points"], "issues")
    assert out.columns == ["sprint", "points", "issues"]
    assert out.rows == [["S2", 2.5, 2], ["S1", 8, 2]], "a blank is skipped, never a zero"


def test_rollup_refuses_a_text_column_and_a_missing_one_by_name():
    t = AgentTable("hist", ["sprint", "key"], [["S1", "A-1"]])
    for by, sums, said in ((["sprint"], ["key"], "not a number"), (["sprint"], ["points"], "no column points"),
                           ([], ["key"], "nothing to group by")):
        try:
            RU.rollup(t, by, sums)
        except RU.RollupError as e:
            assert said in e.msg, e.msg
        else:
            raise AssertionError(f"{by} {sums} was not refused")


def test_the_command_writes_the_tsv_reconcile_reads(tmp_path):
    src = tmp_path / "hist.tsv"
    src.write_text("sprint\tkey\tpoints\nS1\tA-1\t3\nS1\tA-2\t5\nS2\tA-3\t2\n", encoding="utf-8")
    out = tmp_path / "hist-by-sprint.tsv"
    done = _run("uat", "rollup", str(src), "--by", "sprint", "--sum", "points", "--out", str(out))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "rows_in: 3" in done.stdout and "rows_out: 2" in done.stdout
    back = AgentTable.read_tsv(str(out))
    assert back.columns == ["sprint", "points"] and back.rows == [["S1", 8], ["S2", 2]]
    refused = _run("uat", "rollup", str(src), "--by", "sprint", "--sum", "key")
    assert refused.returncode == 2 and "refused: bad_columns" in refused.stdout


def test_a_dscmd_export_rolls_up_and_views_with_its_headers_cleaned(tmp_path):
    csv_path = tmp_path / "pbi.csv"
    csv_path.write_bytes("'Sprint'[Name],[Committed Points]\nS1,8\nS2,2\nS1,1\n".encode("utf-16"))
    viewed = _run("view", str(csv_path))
    assert viewed.returncode == 0 and "{Name,Committed Points}" in viewed.stdout, viewed.stdout
    done = _run("uat", "rollup", str(csv_path), "--by", "Name", "--sum", "Committed Points",
                "--out", str(tmp_path / "pbi-by-sprint.tsv"))
    assert done.returncode == 0, done.stdout
    assert AgentTable.read_tsv(str(tmp_path / "pbi-by-sprint.tsv")).rows == [["S1", 9], ["S2", 2]]
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    refused = _run("view", str(empty))
    assert refused.returncode == 1 and "empty csv" in refused.stdout, refused.stdout


def test_both_are_on_the_fleets_shipped_allow_list_and_python_is_not():
    for command in ("ad-uat rollup x.tsv --by key", "ad-view x.csv"):
        assert any(command.startswith(p[len("shell("):-1]) for p in L.DEFAULT_ALLOW if p.startswith("shell(")), command
    assert not any("python .agent".startswith(p[len("shell("):-1]) for p in L.DEFAULT_ALLOW if p.startswith("shell("))


def test_the_uat_skills_no_longer_ask_for_a_script_or_python():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    visual = open(os.path.join(root, "skills", "uat-report-visual", "SKILL.md"), encoding="utf-8").read()
    dax = open(os.path.join(root, "skills", "dax-studio-export", "SKILL.md"), encoding="utf-8").read()
    assert "ad-uat rollup" in visual and "≤10-line script" not in visual
    assert "python -m agentdata.csv2toon" not in dax and "ad-view" in dax


def test_ad_pbip_dax_runs_any_query_on_desktop_and_writes_the_tsv(tmp_path, monkeypatch, capsys):
    """dax-studio-export step 3 ran `dscmd` itself and read the CSV with `python`; in a fleet both were
    refused. `ad-pbip dax` is the same dscmd call behind an allowed command."""
    import pytest

    from agentdata import cli_pbip
    from agentdata.pbip import dax as D

    seen = []

    def fake_run_dax(dax, server, dscmd, database=None, **kw):
        seen.append((dax, server, database))
        return AgentTable(kw.get("name") or "dax", ["Name", "Committed Points"], [["S1", 9], ["S2", 2]])

    monkeypatch.setattr(D, "run_dax", fake_run_dax)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "pbi.tsv"
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "dax", "--server", "localhost:5123", "--query",
                                      "EVALUATE TOPN(500, 'Sprint')", "--out", str(out)])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    printed = capsys.readouterr().out
    assert ei.value.code == 0, printed
    assert seen == [("EVALUATE TOPN(500, 'Sprint')", "localhost:5123", None)]
    assert AgentTable.read_tsv(str(out)).rows == [["S1", 9], ["S2", 2]]
    for argv in (["--server", "localhost:1", "--query", "TOPN(5, 'Sprint')"],
                 ["--server", "localhost:1"],
                 ["--server", "localhost:1", "--query", "EVALUATE x", "--file", "q.dax"]):
        monkeypatch.setattr(sys, "argv", ["ad-pbip", "dax", *argv])
        with pytest.raises(SystemExit) as ei:
            cli_pbip.main()
        assert ei.value.code == 2, argv
    assert len(seen) == 1, "a refused query never reaches dscmd"
