"""Repo awareness: where setup runs (setup/scope.py), the AGENTS.md writer (facts.py) and the repo step that asks
which source environments and Power BI targets ONE repository uses (setup/steps/repo.py)."""
import json
import os

import pytest

from agentdata import config as C, facts as F, textio
from agentdata.setup import scope as S
from agentdata.setup import wizard as W
from agentdata.setup.steps import repo as R

STUB = os.path.join(os.path.dirname(W.__file__), "..", "templates", "project-stub", "AGENTS.md")


def _repo(path, agents=None):
    (path / ".git").mkdir(parents=True)
    if agents is not None:
        (path / "AGENTS.md").write_text(agents, encoding="utf-8")
    return path


def _stub():
    return textio.read_text(STUB)


# ------------------------------------------------------------------ scope


def test_scope_repo_folder_machine(tmp_path):
    work = tmp_path / "PycharmProjects"
    a, b = _repo(work / "alpha"), _repo(work / "beta")
    (work / "notes").mkdir()
    (work / ".hidden").mkdir()
    _repo(work / ".hidden" / "inner")

    folder = S.detect(str(work))
    assert folder.kind == "folder" and [os.path.basename(r) for r in folder.repos] == ["alpha", "beta"]
    assert folder.agents_md == "" and len(folder.writes()) == 2
    assert "machine-wide" in folder.summary() and "2 repos" in folder.summary()

    inside = S.detect(str(a / "src" if (a / "src").mkdir() is None else a))
    assert inside.kind == "repo" and inside.root == str(a) and inside.name == "alpha"
    assert inside.writes()[-1] == ("this repo", textio.norm_path(str(a / "AGENTS.md")))

    picked = S.detect(str(work), "beta")
    assert picked.kind == "repo" and picked.root == str(b)

    assert S.detect(str(tmp_path / "PycharmProjects" / "notes")).kind == "machine"


def test_scope_bad_repo_lists_the_folder(tmp_path):
    _repo(tmp_path / "alpha")
    with pytest.raises(C.ConfigError) as e:
        S.detect(str(tmp_path), "gamma")
    assert "not a git repository" in str(e.value) and "alpha" in e.value.hint


def test_repo_summary_flags_envs_the_machine_lacks(tmp_path):
    md = _stub().replace("<td_env_name>", "prod").replace("<hive_env_name>", "dev")
    root = _repo(tmp_path / "alpha", md)
    cfg = {"sources": {"teradata": {"envs": {"prod": {}}}}}
    got = S.repo_summary(str(root), cfg)
    assert got["sources"] == {"teradata": "prod", "hive": "dev"} and got["unknown"] == ["hive:dev"]
    assert got["pbi_targets"] == 0
    assert S.repo_summary(str(_repo(tmp_path / "bare")), cfg)["agents_md"] is False


# ------------------------------------------------------------------ facts


def test_set_facts_in_place_keeps_comments(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text(_stub(), encoding="utf-8")
    done = F.set_facts(str(md), {"env": "prod", "hive_env": None, "brand_new": "x"})
    assert done == {"env": "changed", "hive_env": "same", "brand_new": "added"}
    text = md.read_text(encoding="utf-8")
    assert "- env: prod                        # ad-td --env" in text
    assert C.project_facts(str(md))["brand_new"] == "x"
    F.set_facts(str(md), {"env": None})
    assert "- env: <unset>" in md.read_text(encoding="utf-8") and "env" not in C.project_facts(str(md))


def test_targets_table_round_trip_and_mirror(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text(_stub() + "\n## Notes\nkeep me\n", encoding="utf-8")
    rows = [{"workspace": "Sales WS", "ws_id": "ws-1", "model": "Sales", "ds_id": "ds-1", "report": "Sales Report",
             "report_id": "r-1"},
            {"workspace": "Ops", "ws_id": "ws-2", "model": "Margin", "ds_id": "ds-2", "report": "", "report_id": ""}]
    F.set_targets(str(md), rows)
    assert F.pbi_targets(str(md)) == rows
    facts = C.project_facts(str(md))
    assert (facts["pbi_workspace"], facts["ws_id"], facts["pbi_model"], facts["ds_id"]) == ("Sales WS", "ws-1",
                                                                                              "Sales", "ds-1")
    assert facts["pbi_xmla"] == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20WS"
    assert "keep me" in md.read_text(encoding="utf-8")
    F.set_targets(str(md), rows[1:])                      # replaced, not appended
    assert F.pbi_targets(str(md)) == rows[1:] and md.read_text(encoding="utf-8").count(F.TARGETS_HEADING) == 1
    F.set_targets(str(md), [])
    assert F.TARGETS_HEADING not in md.read_text(encoding="utf-8") and F.pbi_targets(str(md)) == []


def test_targets_fall_back_to_single_facts(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text(_stub().replace("<Workspace Name>", "Old WS", 1).replace("<Model>", "Old"), encoding="utf-8")
    assert F.pbi_targets(str(md)) == [{"workspace": "Old WS", "ws_id": "", "model": "Old", "ds_id": "",
                                        "report": "", "report_id": ""}]


def test_unchanged_write_leaves_the_file(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text(_stub(), encoding="utf-8")
    os.utime(md, (1, 1))
    F.set_facts(str(md), {"hive_env": None})
    assert os.stat(md).st_mtime == 1


# ------------------------------------------------------------------ the repo step


class PbiDet(W.Detectors):
    """Answers `az rest` for workspaces, their semantic models and reports; nothing else on the machine."""

    def __init__(self):
        self.runs = []

    def which(self, name):
        return "C:/az.cmd" if name == "az" else None

    def run(self, args, timeout=120):
        self.runs.append(args)
        url = args[args.index("--url") + 1]
        if url == R.GROUPS_URL:
            value = [{"id": "ws-1", "name": "Sales WS"}, {"id": "ws-2", "name": "Ops"}]
        elif url.endswith("/ws-1/datasets"):
            value = [{"id": "ds-1", "name": "Sales"}, {"id": "ds-9", "name": "Margin"}]
        elif url.endswith("/ws-1/reports"):
            value = [{"id": "r-1", "name": "Sales Report", "datasetId": "ds-1"}]
        else:
            value = []
        return 0, json.dumps({"value": value}), ""


def _ctx(scope, answers, det=None, online=True):
    cfg = {"sources": {"teradata": {"envs": {"prod": {}, "uat": {}}}, "hive": {"envs": {"dev": {}}}}}
    return W.Context(cfg=cfg, det=det or PbiDet(), ask=W.AnswerPrompter(answers), online=online, interactive=False,
                     scope=scope)


def test_repo_step_writes_envs_and_targets(tmp_path):
    root = _repo(tmp_path / "PycharmProjects" / "sales-bi")
    ctx = _ctx(S.detect(str(root)), {"repo.create": True, "repo.env": "uat", "repo.hive_env": "",
                                     "repo.pbi.use": True, "repo.pbi.workspaces": "Sales WS",
                                     "repo.pbi.Sales WS.models": "Margin", "repo.pbi.Sales WS.reports": "1"})
    step = R.RepoStep()
    step.ask(ctx, step.detect(ctx))
    md = str(root / "AGENTS.md")
    facts = C.project_facts(md)
    assert facts["env"] == "uat" and "hive_env" not in facts
    assert os.path.exists(root / ".agent" / "state.json")
    assert F.pbi_targets(md) == [
        {"workspace": "Sales WS", "ws_id": "ws-1", "model": "Sales", "ds_id": "ds-1", "report": "Sales Report",
         "report_id": "r-1"},
        {"workspace": "Sales WS", "ws_id": "ws-1", "model": "Margin", "ds_id": "ds-9", "report": "", "report_id": ""}]
    assert ctx.facts["pbi_model"] == "Sales"
    ctx.checks.clear()                                    # and the doctor reads it back as all ok
    step.check(ctx, step.detect(ctx))
    assert [c.status for c in ctx.checks if c.name in ("teradata env", "power bi target")] == ["ok", "ok", "ok"]


def test_repo_step_refuses_an_env_the_machine_lacks(tmp_path):
    root = _repo(tmp_path / "r", _stub())
    ctx = _ctx(S.detect(str(root)), {"repo.env": "qa", "repo.pbi.use": False})
    step = R.RepoStep()
    step.ask(ctx, step.detect(ctx))
    assert "env" not in C.project_facts(str(root / "AGENTS.md"))
    bad = [c for c in ctx.checks if c.status == "fail"]
    assert bad and "qa" in bad[0].detail and bad[0].keys == ("repo.env",)


def test_repo_step_offline_keeps_typed_names(tmp_path):
    root = _repo(tmp_path / "r", _stub())
    ctx = _ctx(S.detect(str(root)), {"repo.pbi.use": True, "repo.pbi.workspaces": "Finance",
                                     "repo.pbi.Finance.models": "Budget", "repo.pbi.Finance.reports": ""},
               online=False)
    step = R.RepoStep()
    step.ask(ctx, step.detect(ctx))
    [t] = F.pbi_targets(str(root / "AGENTS.md"))
    assert (t["workspace"], t["model"], t["ds_id"]) == ("Finance", "Budget", "")
    ctx.checks.clear()
    step.check(ctx, step.detect(ctx))
    warn = [c for c in ctx.checks if c.name == "power bi target"]
    assert warn[0].status == "warn" and "ws_id" in warn[0].detail and ctx.det.runs == []


def test_folder_scope_lists_repos_and_writes_none(tmp_path):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha", _stub().replace("<td_env_name>", "prod"))
    _repo(work / "beta", _stub().replace("<hive_env_name>", "staging"))
    _repo(work / "gamma")
    ctx = _ctx(S.detect(str(work)), {})
    step = R.RepoStep()
    found = step.detect(ctx)
    step.check(ctx, found)
    rows = {c.name: c for c in ctx.checks}
    assert rows["repo alpha"].status == "info" and "teradata prod" in rows["repo alpha"].detail
    assert rows["repo beta"].status == "warn" and "hive:staging" in rows["repo beta"].detail
    assert rows["repo gamma"].hint == "ad-setup --repo gamma"
    step.ask(ctx, found)
    assert not (work / "gamma" / "AGENTS.md").exists()


def test_doctor_and_setup_name_the_scope(tmp_path, monkeypatch, capsys):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    monkeypatch.chdir(work)
    W.run_doctor(["--only", "repo"], PbiDet())
    out = capsys.readouterr().out
    assert "scope: folder" in out and "repo alpha" in out
    rc = W.run_setup(["--non-interactive", "--offline", "--repo", "alpha", "--set", "repo.pbi.use=false"], PbiDet())
    got = capsys.readouterr()
    out = got.out + got.err
    assert rc == 0, out
    assert "scope: repo" in got.out and "this repo: " + textio.norm_path(str(work / "alpha" / "AGENTS.md")) in out and os.path.exists(work / "alpha" / "AGENTS.md")
    assert W.run_setup(["--non-interactive", "--offline", "--repo", "nope"], PbiDet()) == 2
