import json, os
import pytest
from agentdata import config as C
from agentdata.setup import wizard as W
from agentdata.setup.steps import pncli_import, powerbi, project

PNCLI = {"jira": {"url": "https://acme.atlassian.net", "email": "me@acme.com", "token": "tok_1234567890abcdef"},
         "bitbucket": {"token": "bb_secret_value_123"}}


class FakeDet(W.Detectors):
    """No machine or network access. Tunable per test."""

    def __init__(self, pncli=PNCLI, tools=None, modules=(), dsns=None, whoami_error=None, smoke_error=None,
                 pncli_bin="C:/Users/me/AppData/Roaming/npm/pncli.cmd", pncli_rc=0):
        self.pncli, self.tools, self.modules = pncli, tools or {}, set(modules)
        self.pncli_bin, self.pncli_rc = pncli_bin, pncli_rc
        self.dsns = dsns or {}
        self.whoami_error, self.smoke_error = whoami_error, smoke_error
        self.passwords: dict = {}
        self.runs: list = []
        self.files: dict = {}

    def which(self, name):
        return self.tools.get(name)

    def launcher(self, name, exe=None):
        """pncli is an npm command shim on Windows (pncli.cmd -> node cli.js); never an .exe."""
        p = exe or self.pncli_bin if name == "pncli" else self.tools.get(name)
        if not p:
            return {"found": False, "name": name, "kind": "", "path": "", "tried": ["pncli on PATH + PATHEXT", "npm global prefix"]}
        return {"found": True, "name": name, "path": p, "kind": "npm shim", "tried": [], "rc": self.pncli_rc,
                "version": "pncli/1.4.0", "node": "C:/Program Files/nodejs/node.exe",
                "script": "C:/Users/me/AppData/Roaming/npm/node_modules/@kolatts/pncli/bin/cli.js"}

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
        # the steps pass the RESOLVED path now (C:/az.cmd), because the bare name cannot be started on Windows
        tool = os.path.basename(str(args[0])).split(".")[0].lower()
        if [tool, args[1]] == ["az", "account"]:
            return 0, json.dumps({"tenantId": "tenant-1"}), ""
        if [tool, args[1]] == ["az", "rest"]:
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
    assert cfg["pncli"]["exe"].endswith("pncli.cmd")   # the shim we proved starts is pinned; PATH changes cannot break it
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


def test_answers_file_with_bom_and_set_flags(cfg_path, tmp_path, capsys):
    """2026-09-02 laptop friction: Windows PowerShell 5.1 `Set-Content -Encoding utf8` adds a BOM; the loader crashed."""
    det = FakeDet()
    proj = tmp_path / "proj2"
    ans = tmp_path / "bom.json"
    ans.write_bytes(json.dumps({"project.jira_project": "BOMD"}).encode("utf-8-sig"))
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(proj), "--answers", str(ans),
                      "--set", "project.confluence_space=SPC"], det)
    assert rc == 0
    agents = det.files[str(proj / "AGENTS.md")]
    assert "- jira_project: BOMD" in agents and "- confluence_space: SPC" in agents
    proj3 = tmp_path / "proj3"
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(proj3), "--set", "project.jira_project=RDSD"], det)
    assert rc == 0 and "- jira_project: RDSD" in det.files[str(proj3 / "AGENTS.md")]
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xef\xbb\xbf{not json")
    capsys.readouterr()
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(tmp_path / "p4"), "--answers", str(bad)], det)
    out = capsys.readouterr().out
    assert rc == 2 and "ok: false" in out and "not valid JSON" in out and "--set" in out
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(tmp_path / "p5"), "--set", "project.jira_project"], det)
    assert rc == 2 and "key=value" in capsys.readouterr().out
    assert W.load_answers(None, ["a=true", "b=False", "c=x=y", " d = 1 "]) == {"a": True, "b": False, "c": "x=y", "d": "1"}
    assert W.load_answers(str(ans), ["project.jira_project=OVR"]) == {"project.jira_project": "OVR"}


def test_doctor_fails_when_pncli_launcher_is_missing_or_broken(cfg_path, capsys):
    """2026-09-02 laptop friction: ad-pncli died with [WinError 2] while setup called pncli 'ok' — there is no pncli.exe."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    assert W.run_doctor(["--only", "pncli"], FakeDet(pncli_bin=None)) == 1
    out = capsys.readouterr().out
    assert "pncli launcher" in out and "npm install -g @kolatts/pncli" in out and "there is no pncli.exe" in out
    assert W.run_doctor(["--only", "pncli"], FakeDet(pncli_rc=9)) == 1
    out = capsys.readouterr().out
    assert "exits 9 on --version" in out
    assert W.run_doctor(["--only", "pncli"], FakeDet()) == 0
    assert "pncli.cmd (npm shim) · pncli/1.4.0" in capsys.readouterr().out


def _patch(det, extra=None, cfg=None):
    if cfg is not None:
        C.save(cfg)
    return W.run_setup(["--patch", "--non-interactive", "--offline", *(extra or [])], det)


def test_patch_reasks_only_the_failing_setting(cfg_path, capsys):
    """One wrong DSN must cost one env's questions, not the whole wizard."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02", "teradata:prod": "2026-09-02"},
            "sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "KRB5"},
                                              "uat": {"mode": "odbc", "dsn": "GONE", "logmech": "KRB5"}}}}})
    det = FakeDet(modules={"pyodbc", "teradatasql", "keyring"}, dsns={"TD_PROD": "Teradata"})
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "sources",
                      "--set", "sources.teradata.uat.dsn=TD_PROD"], det)
    out, _err = capsys.readouterr()
    assert rc == 0, out
    cfg = json.loads(cfg_path.read_text())
    envs = cfg["sources"]["teradata"]["envs"]
    assert envs["uat"]["dsn"] == "TD_PROD"                                          # repaired
    assert envs["prod"] == {"mode": "odbc", "dsn": "TD_PROD", "logmech": "KRB5"}    # untouched
    assert cfg["verified"]["teradata:prod"] == "2026-09-02"                         # a working env is not disturbed
    assert "was_failing: 1" in out
    asked = out.split("asked[")[1].split("\n")[0]
    assert "sources.teradata.uat." in asked and "teradata.prod" not in asked
    assert "GONE" in out and "sources/teradata:uat" in out                          # why it was re-asked, in the output


def test_patch_with_nothing_broken_asks_nothing(cfg_path, capsys):
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    assert W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli"], FakeDet()) == 0
    out = capsys.readouterr().out
    assert "repaired: 0" in out and "nothing to repair" in out and "--include-warnings" in out


def test_patch_repairs_a_missing_pncli_launcher(cfg_path, capsys, tmp_path):
    """Laptop case: pncli is not on PATH at all (npm shim, no pncli.exe). --patch asks for the one path."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    shim = tmp_path / "pncli.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli", "--set", f"pncli.exe={shim}"],
                     FakeDet(pncli_bin=None))
    out, _err = capsys.readouterr()
    assert "pncli/pncli launcher" in out and "not found on PATH" in out
    assert json.loads(cfg_path.read_text())["pncli"]["exe"] == str(shim).replace("\\", "/")
    assert rc == 0 and "ok: true" in out and "was_failing: 1" in out


def test_patch_repairs_a_wrong_az_path(cfg_path, capsys):
    """Laptop case: az lives at C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.cmd."""
    az = "C:/Program Files/Microsoft SDKs/Azure/CLI2/wbin/az.cmd"
    C.save({"powerbi": {"tools": {"az_exe": "C:/wrong/az.cmd"}}})
    det = FakeDet(tools={"az": None})
    det.files[C.expand(az)] = "@echo off"
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "powerbi", "--set", f"powerbi.az_exe={az}"], det)
    out, _err = capsys.readouterr()
    assert "powerbi/az_exe" in out and "C:/wrong/az.cmd" in out
    assert json.loads(cfg_path.read_text())["powerbi"]["tools"]["az_exe"] == az
    assert rc == 0 and "was_failing: 1" in out and "asked[1]: powerbi.az_exe" in out


def test_scoped_prompter_only_prompts_in_scope():
    inner = W.AnswerPrompter({"a.x": "asked", "b.y": "asked"})
    p = W.ScopedPrompter(inner, ["a."], {"a.": "a.x is wrong"})
    assert p.ask("a.x", "?", "current") == "asked" and p.asked == ["a.x"]
    assert p.ask("b.y", "?", "current") == "current"          # out of scope keeps the stored value
    assert p.confirm("b.z", "?", True) is True and p.confirm("b.z", "?", False) is False
    assert p.ask("b.w", "?", None, ["one", "two"]) == "one"
    assert p.asked == ["a.x"]
