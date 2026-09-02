import json, os
import pytest
from agentdata import config as C
from agentdata.setup import wizard as W
from agentdata.setup.steps import pncli_import, powerbi, project

PNCLI = {"jira": {"url": "https://acme.atlassian.net", "email": "me@acme.com", "token": "tok_1234567890abcdef"},
         "bitbucket": {"token": "bb_secret_value_123"}}


class FakeDet(W.Detectors):
    """No machine or network access. Tunable per test."""

    def __init__(self, pncli=PNCLI, tools=None, modules=(), dsns=None, whoami_error=None, smoke_error=None):
        self.pncli, self.tools, self.modules = pncli, tools or {}, set(modules)
        self.dsns = dsns or {}
        self.whoami_error, self.smoke_error = whoami_error, smoke_error
        self.passwords: dict = {}
        self.runs: list = []
        self.files: dict = {}

    def which(self, name):
        return self.tools.get(name)

    def exists(self, p):
        p = C.expand(p or "")
        return p.endswith("config.json") and self.pncli is not None or p in self.tools.values() or p in self.files \
            or os.path.exists(p)

    def read_json(self, p):
        if self.pncli is None:
            raise FileNotFoundError(p)
        if self.pncli == "bad":
            raise json.JSONDecodeError("bad", "x", 0)
        return self.pncli

    def read_text(self, p):
        return self.files.get(C.expand(p)) or open(C.expand(p), encoding="utf-8").read()

    def write_text(self, p, text):
        self.files[C.expand(p)] = text

    def glob(self, pattern, root="."):
        return [k for k in self.files if k.endswith(".pbip")]

    def run(self, args, timeout=120):
        self.runs.append(args)
        if args[:2] == ["az", "account"]:
            return 0, json.dumps({"tenantId": "tenant-1"}), ""
        if args[:2] == ["az", "rest"]:
            return 0, json.dumps({"value": [{"id": "ws-1", "name": "Sales Workspace"}, {"id": "ws-2", "name": "Ops"}]}), ""
        if args[1:3] == ["csv", "--help"]:
            return 0, "Usage: dscmd csv <output> -s --server -d --database -f --file", ""
        return 0, "tables=3", ""

    def module(self, name):
        return name in self.modules

    def odbc_drivers(self):
        return ["Teradata Database ODBC Driver 20.00"]

    def odbc_dsns(self):
        return dict(self.dsns)

    def keyring_backend(self):
        return "FakeKeyring"

    def has_password(self, source, env, user):
        return (source, env, user) in self.passwords

    def set_password(self, source, env, user, password):
        self.passwords[(source, env, user)] = password

    def smoke(self, source, env, cfg):
        if self.smoke_error:
            raise RuntimeError(self.smoke_error)
        return {"ok": True, "elapsed_s": 0.1, "capabilities": {"trunc_date": True, "tmode": "ANSI"}}

    def jira_whoami(self, cfg, redetect=False):
        if self.whoami_error:
            raise RuntimeError(self.whoami_error)
        C.put(cfg, "jira.flavor", "cloud"); C.put(cfg, "jira.auth", "basic"); C.put(cfg, "jira.api", "3")
        C.stamp(cfg, "jira")
        return {"base_url": "https://acme.atlassian.net", "flavor": "cloud", "auth": "basic", "api": "3",
                "token_source": "pncli:jira.token", "display_name": "Me", "account": "acc"}

    def getuser(self):
        return "luna"

    def python_bits(self):
        return 64


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "agentdata.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    monkeypatch.chdir(tmp_path)
    return p


def test_propose_keys_and_masking():
    prop = pncli_import.propose(C.flatten(PNCLI))
    assert prop == {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}


def test_setup_non_interactive_writes_config_without_secrets(cfg_path, capsys):
    det = FakeDet(tools={"TabularEditor.exe": "C:/TE/TabularEditor.exe", "dscmd.exe": "C:/DS/dscmd.exe", "az": "C:/az.cmd"},
                  modules={"teradatasql", "keyring", "pyodbc"}, dsns={"TD_PROD": "Teradata"})
    det.passwords[("teradata", "uat", "luna")] = "pw"
    answers = {"sources.teradata.use": True, "sources.teradata.envs": "prod,uat",
               "sources.teradata.prod.mode": "native", "sources.teradata.prod.host": "td.acme", "sources.teradata.prod.logmech": "KRB5",
               "sources.teradata.uat.mode": "odbc", "sources.teradata.uat.dsn": "1", "sources.teradata.uat.logmech": "LDAP",
               "sources.hive.use": False, "sources.impala.use": False, "sources.oracle.use": False,
               "powerbi.use": True, "powerbi.workspaces.configure": True, "powerbi.workspaces.select": "1",
               "powerbi.workspace.Sales Workspace.models": "Sales Model", "project.generate": False}
    (cfg_path.parent / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    rc = W.run_setup(["--non-interactive", "--answers", str(cfg_path.parent / "answers.json")], det)
    out = capsys.readouterr()
    cfg = json.loads(cfg_path.read_text())
    assert rc == 0, out.out
    assert cfg["pncli"]["keys"] == {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}
    assert cfg["jira"]["base_url"] == "https://acme.atlassian.net" and cfg["jira"]["flavor"] == "cloud"
    td = cfg["sources"]["teradata"]["envs"]
    assert td["prod"]["host"] == "td.acme" and td["prod"]["capabilities"]["tmode"] == "ANSI"
    assert td["uat"]["mode"] == "odbc" and td["uat"]["dsn"] == "TD_PROD" and td["uat"]["user"] == "luna"
    ws = cfg["powerbi"]["workspaces"][0]
    assert ws["xmla"] == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace" and ws["id"] == "ws-1" and ws["models"] == ["Sales Model"]
    assert cfg["powerbi"]["tools"]["dscmd_caps"]["file_flag"] is True
    assert set(cfg["verified"]) >= {"jira", "teradata:prod", "teradata:uat", "powerbi:xmla:Sales Workspace"}
    text = json.dumps(cfg) + out.out + out.err
    assert "tok_1234567890abcdef" not in text and "bb_secret_value_123" not in text and "pw" not in json.dumps(cfg)
    assert "meta:" in out.out and "ok: true" in out.out
    # idempotent re-run
    assert W.run_setup(["--non-interactive", "--answers", str(cfg_path.parent / "answers.json")], det) == 0
    assert json.loads(cfg_path.read_text())["sources"] == cfg["sources"]


def test_answers_file_rejects_passwords(cfg_path):
    with pytest.raises(C.ConfigError):
        W.AnswerPrompter({"sources.teradata.prod.password": "x"})


def test_doctor_fails_without_pncli_config(cfg_path, capsys):
    rc = W.run_doctor(["--only", "pncli"], FakeDet(pncli=None))
    out = capsys.readouterr().out
    assert rc == 1 and "ok: false" in out and "pncli config init" in out


def test_doctor_ok_and_quiet(cfg_path, capsys):
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    det = FakeDet(tools={"pncli": "/usr/bin/pncli"})
    assert W.run_doctor(["--only", "pncli"], det) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "jira auth" in out
    assert W.run_doctor(["--only", "pncli", "--quiet"], det) == 0
    assert "checks[0]" in capsys.readouterr().out


def test_doctor_online_verifies_and_reports_failure(cfg_path, capsys):
    C.save({"pncli": {"keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}}})
    rc = W.run_doctor(["--only", "pncli", "--online"], FakeDet(whoami_error="401 nope"))
    out = capsys.readouterr().out
    assert rc == 1 and "401 nope" in out
    assert W.run_doctor(["--only", "pncli", "--online"], FakeDet()) == 0
    assert json.loads(cfg_path.read_text())["verified"]["jira"]


def test_sources_doctor_flags_missing_dsn_and_driver(cfg_path, capsys):
    C.save({"sources": {"teradata": {"envs": {"a": {"mode": "odbc", "dsn": "GONE"}, "b": {"mode": "native", "host": "h"}}}}})
    rc = W.run_doctor(["--only", "sources"], FakeDet(modules={"pyodbc"}))
    out = capsys.readouterr().out
    assert rc == 1
    assert "GONE" in out and "odbcad32" in out
    assert ".[teradata]" in out  # TOON escapes the double quotes in the hint


def test_unknown_step(cfg_path, capsys):
    assert W.run_doctor(["--only", "nope"], FakeDet()) == 2
    assert "unknown step" in capsys.readouterr().out


def test_project_stub_fill_and_generation(cfg_path, tmp_path):
    tpl = "# Project: <PROJECT_KEY>\n- env: <td_env_name>              # ad-td --env\n- pbi_xmla: <x>\n- keep: <k>\n"
    filled = project.fill(tpl, {"env": "prod", "pbi_xmla": "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace"})
    assert "- env: prod              # ad-td --env" in filled and "- keep: <k>" in filled and "powerbi://" in filled
    C.save({"sources": {"teradata": {"envs": {"prod": {"host": "h"}}}},
            "powerbi": {"tools": {"te2_exe": "C:/TE/TabularEditor.exe"},
                        "workspaces": [{"name": "Sales Workspace", "id": "ws-1", "xmla": powerbi.xmla_url("Sales Workspace"), "models": ["Sales"]}]}})
    det = FakeDet()
    proj = tmp_path / "proj"
    det.files[str(proj / "reports" / "Sales.pbip")] = "{}"
    rc = W.run_setup(["--non-interactive", "--project", str(proj), "--offline", "--answers",
                      str(_answers(tmp_path, {"project.jira_project": "RDSD"}))], det)
    assert rc == 0
    agents = det.files[str(proj / "AGENTS.md")]
    assert "- jira_project: RDSD" in agents and "- env: prod" in agents and "- pbi_model: Sales" in agents
    assert "- pbip_path: reports/Sales.pbip" in agents and "Sales%20Workspace" in agents and "- ws_id: ws-1" in agents
    assert json.loads(det.files[str(proj / ".agent" / "state.json")])["project"] == "RDSD"
    assert ".agent/out/" in det.files[str(proj / ".gitignore")]


def _answers(tmp_path, d):
    p = tmp_path / "ans.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_xmla_url_percent_encodes():
    assert powerbi.xmla_url("Sales Workspace/EMEA") == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace%2FEMEA"
