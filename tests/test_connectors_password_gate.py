"""A password-auth source with nothing in keyring must refuse before it ever dials out -- native mode already
did (both connectors), ODBC mode did not.

Reported: "{[Password]} from ODBC requires a human ad-setup --patch credential entry and should not be retried
non-interactively" -- and, separately, that Teradata's config choices were not saving like Oracle/Hive/Impala's
do. Both trace to the same gap: `teradata.py` and `hs2.py`'s ODBC branches built a connection string with
neither UID nor PWD when the password was missing and dialed out anyway, free to hang or show the driver's own
native credential prompt -- and `sources.py`'s `verify()` (called directly by the interactive `ad-setup` wizard,
right after `ask()`) had no pre-check for this at all, unlike `check()` (used by `ad-doctor`), which already did.
Hitting that live, mid-wizard, right after answering Teradata's questions, is indistinguishable from "ad-setup
isn't working for Teradata" even though the answers were already saved to disk before verify() ran.
"""
import pytest

from agentdata import config as C
from agentdata.config import ConfigError
from agentdata.setup import wizard as W
from agentdata.setup.steps import sources
from tests.test_setup import FakeDet, cfg_path  # noqa: F401 - cfg_path is a fixture, imported to be reused here


class FakeKeyring:
    """No password stored for anyone; records whether it was ever asked."""
    store: dict = {}

    @classmethod
    def get_password(cls, service, user):
        return cls.store.get((service, user))

    @classmethod
    def set_password(cls, service, user, password):
        cls.store[(service, user)] = password


@pytest.fixture(autouse=True)
def empty_keyring(monkeypatch):
    FakeKeyring.store = {}
    monkeypatch.setattr("agentdata.connectors.secrets._keyring", lambda: FakeKeyring)
    yield


def _refuses_before_dialing_out(monkeypatch, connect_module, call):
    """Patch the module-level odbc.connect() everywhere it could be imported from and assert it is never
    reached -- the guard must fire strictly before any network I/O, not just "eventually raise"."""
    def boom(*a, **kw):
        raise AssertionError("odbc.connect() was called: the password guard did not stop it")
    monkeypatch.setattr(connect_module, "connect", boom)
    with pytest.raises(ConfigError) as e:
        call()
    assert "no password in keyring" in str(e.value)
    assert "ad-setup --patch" in e.value.hint and "sources." in e.value.hint and ".password" in e.value.hint
    assert "non-interactively" in e.value.hint          # the exact framing: this cannot be a --set/AnswerPrompter fix


def test_teradata_odbc_refuses_a_missing_password_before_dialing_out(monkeypatch):
    from agentdata.connectors import odbc, teradata
    cfg = {"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "jsmith"}}}}}
    _refuses_before_dialing_out(monkeypatch, odbc, lambda: teradata.connect("prod", cfg))


def test_teradata_odbc_with_krb5_needs_no_password_and_is_unaffected(monkeypatch):
    from agentdata.connectors import odbc, teradata
    monkeypatch.setattr(odbc, "connect", lambda conn_str, timeout=None: conn_str)
    cfg = {"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "KRB5", "user": "jsmith"}}}}}
    assert teradata.connect("prod", cfg) == "DSN=TD_PROD;"      # no UID/PWD: none needed, none asked for


@pytest.mark.parametrize("source", ["hive", "impala"])
def test_hs2_odbc_refuses_a_missing_password_before_dialing_out(monkeypatch, source):
    from agentdata.connectors import hs2, odbc
    cfg = {"sources": {source: {"envs": {"prod": {"mode": "odbc", "dsn": "HS2_PROD", "auth": "LDAP", "user": "jsmith"}}}}}
    _refuses_before_dialing_out(monkeypatch, odbc, lambda: hs2.connect(source, "prod", cfg))


def test_hs2_odbc_with_gssapi_needs_no_password_and_is_unaffected(monkeypatch):
    from agentdata.connectors import hs2, odbc
    monkeypatch.setattr(odbc, "connect", lambda conn_str, timeout=None: conn_str)
    cfg = {"sources": {"hive": {"envs": {"prod": {"mode": "odbc", "dsn": "HS2_PROD", "auth": "GSSAPI", "user": "jsmith"}}}}}
    assert hs2.connect("hive", "prod", cfg) == "DSN=HS2_PROD;"


def test_a_stored_password_reaches_the_connection_string_unchanged(monkeypatch):
    from agentdata.connectors import odbc, secrets, teradata
    secrets.set_password("teradata", "prod", "jsmith", "hunter2")
    monkeypatch.setattr(odbc, "connect", lambda conn_str, timeout=None: conn_str)
    cfg = {"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "jsmith"}}}}}
    assert teradata.connect("prod", cfg) == "DSN=TD_PROD;UID=jsmith;PWD=hunter2;"


def test_verify_never_calls_smoke_when_the_password_is_known_missing(cfg_path, capsys):
    """The load-bearing fix: `ad-setup`'s own wizard calls verify() directly after ask(), with no `check()` in
    between -- this is the only guard standing between "declined the password prompt" and a live connection
    attempt with none. `check()` (ad-doctor) already had this; verify() did not."""
    C.save({"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "jsmith"}}}}})
    det = FakeDet(modules={"pyodbc", "teradatasql"}, dsns={"TD_PROD": "Teradata"})
    calls = []
    real_smoke = det.smoke
    det.smoke = lambda *a, **kw: (calls.append(a), real_smoke(*a, **kw))[1]
    ctx = W.Context(cfg=C.load(), det=det, ask=W.AnswerPrompter({}), online=True, facts={})
    sources.SourcesStep().verify(ctx)
    assert calls == []                                            # never dialed out
    row = ctx.checks[0]
    assert row.status == "fail" and "no password in keyring" in row.detail
    assert row.keys == ("sources.teradata.prod.user", "sources.teradata.prod.keep_password", "sources.teradata.prod.password")


def test_verify_still_probes_normally_once_a_password_exists(cfg_path):
    C.save({"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "jsmith"}}}}})
    det = FakeDet(modules={"pyodbc", "teradatasql"}, dsns={"TD_PROD": "Teradata"})
    det.passwords[("teradata", "prod", "jsmith")] = "hunter2"
    calls = []
    real_smoke = det.smoke
    det.smoke = lambda *a, **kw: (calls.append(a), real_smoke(*a, **kw))[1]
    ctx = W.Context(cfg=C.load(), det=det, ask=W.AnswerPrompter({}), online=True, facts={})
    sources.SourcesStep().verify(ctx)
    assert len(calls) == 1                                        # a real probe, because there IS a credential
    assert ctx.checks[0].status == "ok"


def test_full_setup_run_saves_teradata_even_when_verify_would_have_no_password(cfg_path, capsys, monkeypatch):
    """End to end through run_setup(): the exact reported shape -- answer Teradata's ODBC/LDAP questions,
    decline the password (non-interactive: it cannot be given), and confirm the config still lands, with a
    clean fail row instead of a live connection attempt."""
    monkeypatch.setattr(W, "has_tty", lambda: True)
    det = FakeDet(modules={"pyodbc"}, dsns={"TD_PROD": "Teradata"})
    rc = W.run_setup(["--only", "sources", "--non-interactive",
                      "--set", "sources.teradata.use=true", "--set", "sources.teradata.envs=prod",
                      "--set", "sources.teradata.prod.mode=odbc", "--set", "sources.teradata.prod.dsn=TD_PROD",
                      "--set", "sources.teradata.prod.logmech=LDAP"], det)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "no password in keyring" in out and "sources.teradata.prod.password" in out
    env = C.load()["sources"]["teradata"]["envs"]["prod"]
    assert env == {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "luna"}  # saved despite the verify failure


def test_check_and_verify_report_the_missing_password_identically(cfg_path, capsys):
    """check() (ad-doctor) already had this guard; verify() (ad-setup's own wizard) did not. Both now go
    through the same row builder, so ad-doctor and a live ad-setup run say exactly the same thing."""
    C.save({"sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "LDAP", "user": "jsmith"}}}}})
    det = FakeDet(modules={"pyodbc", "teradatasql", "keyring"}, dsns={"TD_PROD": "Teradata"})
    assert W.run_doctor(["--only", "sources"], det) == 1
    doctor_out = capsys.readouterr().out
    assert "no password in keyring for teradata:prod user jsmith" in doctor_out
    assert "ad-setup --patch sources.teradata.prod.password" in doctor_out
    assert "non-interactively" in doctor_out

    ctx = W.Context(cfg=C.load(), det=det, ask=W.AnswerPrompter({}), online=True, facts={})
    sources.SourcesStep().verify(ctx)
    assert ctx.checks[0].detail == "no password in keyring for teradata:prod user jsmith"
    assert ctx.checks[0].hint == ("ad-setup --patch sources.teradata.prod.password -- a password prompt needs a "
                                  "human at a real terminal; it cannot be answered non-interactively")
