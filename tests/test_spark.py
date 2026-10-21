"""Spark through its Thrift Server: HiveServer2's protocol, so `connectors/hs2.py` dials it, with what Spark adds -- an
HTTP transport and a Kerberos service that is usually Hive's. Read-only like every engine here."""
from __future__ import annotations

import sys
import types

import pytest

from agentdata.connectors import hs2, spark


@pytest.fixture()
def dialled(monkeypatch):
    seen = {}
    fake = types.ModuleType("impala.dbapi")
    fake.connect = lambda **kw: seen.update(kw) or "con"
    monkeypatch.setitem(sys.modules, "impala", types.ModuleType("impala"))
    monkeypatch.setitem(sys.modules, "impala.dbapi", fake)
    return seen


def _cfg(**env):
    return {"sources": {"spark": {"envs": {"prod": {"host": "sts.corp.example", **env}}}}}


def test_binary_kerberos_defaults_to_port_10000_and_hives_service(dialled):
    assert hs2.connect("spark", "prod", _cfg()) == "con"
    assert dialled == {"host": "sts.corp.example", "port": 10000, "auth_mechanism": "GSSAPI", "use_ssl": False,
                       "kerberos_service_name": "hive"}


def test_http_transport_carries_its_path_and_a_named_service(dialled):
    hs2.connect("spark", "prod", _cfg(transport="http", port=10001, ssl=True, service_name="spark"))
    assert dialled["use_http_transport"] is True and dialled["http_path"] == "cliservice"
    assert dialled["port"] == 10001 and dialled["use_ssl"] is True and dialled["kerberos_service_name"] == "spark"
    hs2.connect("spark", "prod", _cfg(transport="http", http_path="gateway/default/spark"))
    assert dialled["http_path"] == "gateway/default/spark"


def test_a_write_never_reaches_the_server(dialled):
    with pytest.raises(PermissionError):
        spark.query("INSERT INTO t SELECT 1", "prod")
    assert dialled == {}, "refused before connecting"
