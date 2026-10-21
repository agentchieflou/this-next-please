"""`tnp`: the menu over setup (agentdata/tnp), the JDBC URL reader its walkthrough uses (setup/jdbc.py), and the
guide it shares with docs/tnp.md."""
import io
import os

import pytest

from agentdata import color, config as C, facts as F, textio
from agentdata.setup import jdbc
from agentdata.setup import wizard as W
from agentdata.tnp import app as A, brand as B, guide as G
from tests.test_setup import FakeDet

STUB = os.path.join(os.path.dirname(W.__file__), "..", "templates", "project-stub", "AGENTS.md")
DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "tnp.md")


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    p = tmp_path / "agentdata.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    return p


def _repo(path, agents=True):
    (path / ".git").mkdir(parents=True)
    if agents:
        (path / "AGENTS.md").write_text(textio.read_text(STUB), encoding="utf-8")
    return path


def _app(cwd, keys, answers=None, det=None, repo=None):
    out = io.StringIO()
    app = A.App(det=det or FakeDet(modules=("impala", "teradatasql", "keyring")),
                prompter=W.AnswerPrompter(answers or {}), keys=iter(keys), out=out, cwd=str(cwd), repo=repo)
    return app, out


# ------------------------------------------------------------------ home


def test_home_says_where_it_is_and_what_it_writes(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "beta", agents=False)
    app, out = _app(work, ["q"])
    assert app.run() == 0
    text = out.getvalue()
    assert B.WORDMARK[0].rstrip() in text and "this-next-please" in text
    assert "folder of 2 repos — a machine-wide setup" in text
    assert "Writes     machine config: " + C.display_path(C.path()) in text
    assert "Repos in this folder" in text and "▸ 1  Test connections" in text
    assert "toil 3 connections" in text


def test_home_in_a_repo_names_its_agents_md(tmp_path, cfg_file):
    root = _repo(tmp_path / "sales-bi")
    app, out = _app(root / ".git", ["down", "down", "q"])
    app.run()
    text = out.getvalue()
    assert "Scope      repo sales-bi" in text and "this repo: " + textio.norm_path(str(root / "AGENTS.md")) in text
    assert "This repo" in text


def test_menu_arrows_wrap_and_digits_jump(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["up", "enter"])                   # up from 1 wraps to Quit
    assert app.run() == 0
    app, out = _app(tmp_path, ["7", "4", "q", "q"])                # Help -> Commands
    app.run()
    assert "ad-setup --repo <name>" in out.getvalue()


def test_wordmark_is_teal_into_blue(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    color.set_enabled(True)
    try:
        line = B.gradient("████")
        assert "38;2;%d;%d;%d" % B.TEAL in line and "38;2;%d;%d;%d" % B.BLUE in line
        monkeypatch.delenv("COLORTERM")
        monkeypatch.delenv("WT_SESSION", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        assert "38;5;" in B.gradient("██")
    finally:
        color.set_enabled(False)
    assert B.gradient("██") == "██"


# ------------------------------------------------------------------ adding a connection


def test_add_spark_from_a_jdbc_url_tests_it_and_offers_the_repo(tmp_path, cfg_file):
    root = _repo(tmp_path / "sales-bi")
    det = FakeDet(modules=("impala", "keyring"))
    app, out = _app(root, ["2", "5", "1", "enter", "q", "q", "q"], det=det,
                    answers={"tnp.spark.name": "prod", "tnp.spark.jdbc": jdbc.EXAMPLE["spark"]})
    assert app.run() == 0
    e = C.load()["sources"]["spark"]["envs"]["prod"]
    assert (e["host"], e["port"], e["transport"], e["http_path"], e["auth"], e["service_name"]) == (
        "sparkts.corp.example", 10001, "http", "cliservice", "GSSAPI", "hive")
    assert C.project_facts(str(root / "AGENTS.md"))["spark_env"] == "prod"
    text = out.getvalue()
    assert "TNP › Data sources › Spark (Thrift Server) › Add a connection" in text
    assert "From the URL: host sparkts.corp.example" in text and "spark:prod  answered" in text
    assert 'ad-spark --env prod "SELECT 1"' in text
    assert C.get_leaf(C.load(), "verified", "spark:prod")


def test_add_teradata_by_hand_and_a_failing_test_explains(tmp_path, cfg_file):
    det = FakeDet(modules=("teradatasql", "keyring"), smoke_error="[Error 8017] logon failed")
    app, out = _app(tmp_path, ["2", "1", "1", "enter", "q", "q", "q"], det=det,
                    answers={"tnp.teradata.name": "uat", "sources.teradata.uat.host": "tduat.corp",
                             "sources.teradata.uat.logmech": "KRB5"})
    app.run()
    assert C.load()["sources"]["teradata"]["envs"]["uat"]["host"] == "tduat.corp"
    text = out.getvalue()
    assert "1. environment name" in text and "8017 / logon failed" in text
    assert "this repo" not in text.split("Add a connection")[-1].split("Each step")[0]   # no repo here: not offered


def test_bad_jdbc_url_is_said_and_skipped(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["2", "4", "1", "enter", "q", "q", "q"],
                    answers={"tnp.oracle.name": "ORA1", "tnp.oracle.jdbc": "jdbc:hive2://x:1/",
                             "sources.oracle.ORA1.host": "ora", "sources.oracle.ORA1.service_name": "SVC"})
    app.run()
    assert "is not a oracle connection" in out.getvalue()
    assert C.load()["sources"]["oracle"]["envs"]["ORA1"]["service_name"] == "SVC"


# ------------------------------------------------------------------ repos and Power BI


def test_folder_repo_setup_writes_only_that_repo(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "beta", agents=False)
    C.save({"sources": {"hive": {"envs": {"dev": {"host": "h"}}}}})
    app, out = _app(work, ["4", "2", "enter", "q", "q"], answers={"repo.create": True, "repo.hive_env": "dev",
                                                                 "repo.pbi.use": False})
    app.run()
    assert C.project_facts(str(work / "beta" / "AGENTS.md"))["hive_env"] == "dev"
    assert "hive_env" not in C.project_facts(str(work / "alpha" / "AGENTS.md"))
    text = out.getvalue()
    assert "TNP › Repos in this folder › beta" in text and "ad-setup --repo beta" in text


def test_power_bi_for_a_repo_in_the_folder(tmp_path, cfg_file):
    from tests.test_repo_scope import PbiDet

    class Det(FakeDet):
        run = PbiDet.run

        def which(self, name):
            return "C:/az.cmd" if name == "az" else None

    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "sales-bi")
    app, out = _app(work, ["3", "2", "2", "enter", "q", "q"], det=Det(),
                    answers={"repo.pbi.use": True, "repo.pbi.workspaces": "1,2",
                             "repo.pbi.Sales WS.models": "Margin", "repo.pbi.Sales WS.reports": "Sales Report",
                             "repo.pbi.Ops.models": "", "repo.pbi.Ops.reports": ""})
    app.run()
    rows = F.pbi_targets(str(work / "sales-bi" / "AGENTS.md"))
    assert [(r["workspace"], r["model"], r["report"]) for r in rows] == [("Sales WS", "Sales", "Sales Report"),
                                                                        ("Sales WS", "Margin", "")]
    assert "1. Sales WS / Sales / Sales Report" in out.getvalue()
    assert F.pbi_targets(str(work / "alpha" / "AGENTS.md")) == []


def test_main_print_and_bad_repo(tmp_path, cfg_file, monkeypatch, capsys):
    from agentdata import tnp
    monkeypatch.chdir(tmp_path)
    assert tnp.main(["--print", "--color", "never"]) == 0
    assert "machine — no repo here" in capsys.readouterr().out
    assert tnp.main(["--repo", "nope"]) == 2
    assert "not a git repository" in capsys.readouterr().err


# ------------------------------------------------------------------ JDBC URLs


@pytest.mark.parametrize("source,url,want", [
    ("teradata", jdbc.EXAMPLE["teradata"], {"host": "tdprod.corp.example", "logmech": "KRB5", "tmode": "ANSI"}),
    ("hive", jdbc.EXAMPLE["hive"], {"host": "hive.corp.example", "port": 10000, "auth": "GSSAPI"}),
    ("hive", "jdbc:hive2://h:10000/db;user=me;ssl=true", {"host": "h", "auth": "LDAP", "user": "me", "ssl": True}),
    ("impala", jdbc.EXAMPLE["impala"], {"host": "impala.corp.example", "port": 21050, "auth": "GSSAPI"}),
    ("impala", "jdbc:impala://h:21050;AuthMech=3;UID=me", {"host": "h", "auth": "LDAP", "user": "me"}),
    ("oracle", jdbc.EXAMPLE["oracle"], {"style": "basic", "host": "ora.corp.example", "port": 1521,
                                        "service_name": "SALESPRD"}),
    ("oracle", "jdbc:oracle:thin:@ora:1521:ORCL", {"style": "basic", "sid": "ORCL"}),
    ("oracle", "jdbc:oracle:thin:@//ora/SVC", {"host": "ora", "port": 1521, "service_name": "SVC"}),
    ("oracle", "jdbc:oracle:thin:@OIMPROD1_ROSVC", {"style": "tns", "dsn": "OIMPROD1_ROSVC"}),
    ("oracle", "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(HOST=h)))", {"style": "tns"}),
    ("spark", jdbc.EXAMPLE["spark"], {"transport": "http", "http_path": "cliservice", "port": 10001,
                                      "service_name": "hive"}),
    ("spark", "jdbc:hive2://s:10000/default;transportMode=binary", {"transport": "binary", "port": 10000}),
])
def test_jdbc_parse(source, url, want):
    got = jdbc.parse(source, url)
    assert {k: got.get(k) for k in want} == want and got["mode"] == "native"
    if source in ("hive", "impala"):
        assert "transport" not in got


@pytest.mark.parametrize("source,url", [("hive", "hive2://h"), ("teradata", "jdbc:oracle:thin:@x"),
                                        ("oracle", "jdbc:oracle:thin:nohost")])
def test_jdbc_parse_refuses(source, url):
    with pytest.raises(ValueError):
        jdbc.parse(source, url)


# ------------------------------------------------------------------ the guide and its doc


def test_doc_walks_through_every_connection():
    doc = textio.read_text(DOC)
    from agentdata.setup.steps.sources import LABEL
    for s, g in G.SOURCES.items():
        assert f"## {LABEL[s]}" in doc, s
        assert g["test"] in doc, s
        assert jdbc.EXAMPLE[s] in doc, s
    for what, _ in G.WHERE:
        assert what in doc
    for cmd, _ in G.CHEATSHEET:
        assert f"`{cmd}`" in doc
