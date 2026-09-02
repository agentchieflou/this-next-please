import json, os
import pytest
from agentdata import config as C


def test_get_put_flatten_mask():
    cfg = {}
    C.put(cfg, "a.b.c", 1)
    C.put(cfg, "a.list", [{"x": "y"}])
    assert C.get(cfg, "a.b.c") == 1 and C.get(cfg, "a.list.0.x") == "y" and C.get(cfg, "a.nope", 5) == 5
    assert C.flatten(cfg) == {"a.b.c": 1, "a.list.0.x": "y"}
    assert C.mask("abcdefghijkl") == "ab********kl" and C.mask("short") == "*****" and C.mask(None) == ""
    assert C.looks_secret("jira.api_token") and C.looks_secret("PASSWORD") and not C.looks_secret("jira.url")


def test_load_missing_and_bad_json(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    assert C.path() == str(p) and C.load() == {"version": C.VERSION}
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(C.ConfigError) as ei:
        C.load()
    assert "ad-setup" in ei.value.hint


def test_save_atomic_and_refuses_secrets(tmp_path, monkeypatch):
    p = tmp_path / "sub" / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    cfg = {"pncli": {"keys": {"jira_token": "jira.token"}}, "jira": {"base_url": "https://x.atlassian.net"}}
    out = C.save(cfg)
    assert out.endswith("cfg.json") and not (tmp_path / "sub" / "cfg.json.tmp").exists()
    assert json.loads(p.read_text())["jira"]["base_url"] == "https://x.atlassian.net"
    with pytest.raises(C.ConfigError):
        C.save({"jira": {"token": "abc123secret"}})
    with pytest.raises(C.ConfigError):
        C.save({"sources": {"teradata": {"envs": {"prod": {"password": "pw"}}}}})
    C.save({"sources": {"teradata": {"envs": {"prod": {"password": ""}}}}})  # empty is fine


def test_project_facts(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text("# P\n- env: prod              # ad-td --env\n- te2_exe: C:/Tools/TE/TabularEditor.exe\n"
                  "- pbi_workspace: <Workspace Name>\n- empty:\n- Jira_Project: RDSD\nnot a fact\n", encoding="utf-8")
    f = C.project_facts(str(md))
    assert f == {"env": "prod", "te2_exe": "C:/Tools/TE/TabularEditor.exe", "jira_project": "RDSD"}
    assert C.project_facts(str(tmp_path / "missing.md")) == {}


def test_resolve_precedence(monkeypatch):
    cfg = {"x": {"y": "from_cfg"}}
    facts = {"name": "from_facts"}
    monkeypatch.delenv("AD_TEST_X", raising=False)
    assert C.resolve("name", flag="flag", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "flag"
    monkeypatch.setenv("AD_TEST_X", "from_env")
    assert C.resolve("name", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "from_env"
    monkeypatch.delenv("AD_TEST_X")
    assert C.resolve("name", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "from_cfg"
    assert C.resolve("name", cfg=cfg, cfg_path="x.zz", facts=facts) == "from_facts"
    assert C.resolve("name", default="d") == "d"
    with pytest.raises(C.ConfigError):
        C.resolve("name")


def test_source_env_and_env_override(monkeypatch):
    cfg = {"sources": {"teradata": {"envs": {"prod": {"host": "td.example", "logmech": "KRB5",
                                                       "capabilities": {"trunc_date": True}}}}}}
    for v in ("TD_HOST_PROD", "TD_HOST", "TD_USER"):
        monkeypatch.delenv(v, raising=False)
    e = C.source_env(cfg, "teradata", "prod")
    assert e["host"] == "td.example" and e["mode"] == "native" and e["env"] == "prod"
    monkeypatch.setenv("TD_HOST_PROD", "override.example")
    assert C.source_env(cfg, "teradata", "prod")["host"] == "override.example"
    with pytest.raises(C.ConfigError) as ei:
        C.source_env(cfg, "teradata", "uat")
    assert "TD_HOST_UAT" in ei.value.hint and "ad-setup" in ei.value.hint
    assert C.capabilities(cfg, "teradata", "prod") == {"trunc_date": True}
    dsn_only = {"sources": {"hive": {"envs": {"p": {"dsn": "HiveDSN"}}}}}
    assert C.source_env(dsn_only, "hive", "p")["mode"] == "odbc"
    with pytest.raises(C.ConfigError):
        C.source_env(cfg, "spark", "prod")


def test_facts_and_config_tolerate_powershell_encodings(tmp_path, monkeypatch):
    p = tmp_path / "AGENTS.md"
    p.write_bytes("- jira_project: RDSD\r\n- env: prod   # ad-td --env\r\n- pbip_path: <x>\r\n".encode("utf-8-sig"))
    assert C.project_facts(str(p)) == {"jira_project": "RDSD", "env": "prod"}
    cfgp = tmp_path / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(cfgp))
    cfgp.write_bytes(b"\xff\xfe" + json.dumps({"version": C.VERSION, "a": 1}).encode("utf-16-le"))
    assert C.load()["a"] == 1
    cfgp.write_bytes(b"\xef\xbb\xbf{not json")
    with pytest.raises(C.ConfigError) as ei:
        C.load()
    assert "not valid JSON" in str(ei.value)
