"""`_pyodbc()`'s two ImportError shapes.

Real bug found while proving `pyodbc` safe as a base dependency: on a Linux box with the wheel installed but no
system ODBC driver manager, `import pyodbc` raises `ImportError: libodbc.so.2: cannot open shared object file`
-- a real package, a missing native library. The old code called that "pyodbc is not installed" and pointed at
`pip install`, which cannot fix a missing system library. The two cases now get distinct, actionable hints.
"""
import pytest

from agentdata.config import ConfigError
from agentdata.connectors import odbc as O


def _break_import(monkeypatch, message: str) -> None:
    real = __import__

    def fail(name, *a, **kw):
        if name == "pyodbc":
            raise ImportError(message)
        return real(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", fail)


def test_genuinely_missing_says_not_installed_and_points_at_a_plain_reinstall(monkeypatch):
    _break_import(monkeypatch, "No module named 'pyodbc'")
    with pytest.raises(ConfigError) as e:
        O._pyodbc()
    assert str(e.value) == "pyodbc is not installed"
    assert e.value.hint.startswith("pip install")
    assert "[odbc]" not in e.value.hint          # that extra is a no-op now; the base install already carries it


def test_installed_but_the_native_driver_manager_is_missing_says_so(monkeypatch):
    _break_import(monkeypatch, "libodbc.so.2: cannot open shared object file: No such file or directory")
    with pytest.raises(ConfigError) as e:
        O._pyodbc()
    assert "installed but its ODBC driver manager did not load" in str(e.value)
    assert "libodbc.so.2" in str(e.value)                       # the original OS error, not swallowed
    assert "unixodbc" in e.value.hint.lower() and "pip install" not in e.value.hint.lower()


def test_both_shapes_degrade_the_same_way_for_every_caller(monkeypatch):
    """drivers() / data_sources() / available() must not care which shape it was -- either way there is no
    usable ODBC today, so the wizard's DSN picker should just be empty, not raise."""
    for message in ("No module named 'pyodbc'", "libodbc.so.2: cannot open shared object file"):
        _break_import(monkeypatch, message)
        assert O.available() is False
        assert O.drivers() == []
        assert O.data_sources() == {}


def test_a_working_pyodbc_is_unaffected(monkeypatch):
    calls = []

    class FakePyodbc:
        @staticmethod
        def drivers():
            calls.append("drivers")
            return ["Teradata Database ODBC Driver 20.00"]

    real = __import__

    def ok(name, *a, **kw):
        if name == "pyodbc":
            return FakePyodbc
        return real(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", ok)
    assert O.available() is True
    assert O.drivers() == ["Teradata Database ODBC Driver 20.00"]
    assert calls == ["drivers"]
