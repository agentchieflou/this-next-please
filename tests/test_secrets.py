"""The keyring wrapper must survive a broken backend, not just a missing package.

Real bug: `pyo3_runtime.PanicException` (what a native-extension ABI mismatch inside keyring's dependency chain
raises) does not subclass `Exception` -- only `BaseException`. Every guard in this module used to be a bare
`except Exception:`, so a broken backend crashed straight through `has_password()`/`set_password()`/
`backend_name()` with a raw traceback, mid-wizard, discarding whatever the wizard step had not saved yet.
"""
import pytest

from agentdata.config import ConfigError
from agentdata.connectors import secrets as S


class Panics:
    """Not a subclass of Exception -- the same shape as pyo3's PanicException. `except Exception:` must not
    catch this; that is the entire point of the bug."""
    class Boom(BaseException):
        pass

    @staticmethod
    def get_password(service, user):
        raise Panics.Boom("native extension panicked")

    @staticmethod
    def set_password(service, user, password):
        raise Panics.Boom("native extension panicked")

    @staticmethod
    def get_keyring():
        raise Panics.Boom("native extension panicked")


def _use(monkeypatch, module) -> None:
    monkeypatch.setattr(S, "_keyring", lambda: module)


def test_a_baseexception_from_the_backend_becomes_a_clean_configerror(monkeypatch):
    _use(monkeypatch, Panics)
    with pytest.raises(ConfigError) as e:
        S.set_password("teradata", "prod", "jsmith", "hunter2")
    assert "keyring backend failed on write" in str(e.value) and "Boom" in str(e.value)
    with pytest.raises(ConfigError):
        S.get_password("teradata", "prod", "jsmith")


def test_has_password_and_backend_name_degrade_instead_of_crashing(monkeypatch):
    _use(monkeypatch, Panics)
    assert S.has_password("teradata", "prod", "jsmith") is False       # not True, not a raised BaseException
    assert S.backend_name().startswith("unavailable (")


def test_keyboard_interrupt_and_system_exit_are_never_swallowed(monkeypatch):
    class Rude:
        @staticmethod
        def set_password(service, user, password):
            raise KeyboardInterrupt()
    _use(monkeypatch, Rude)
    with pytest.raises(KeyboardInterrupt):
        S.set_password("teradata", "prod", "jsmith", "hunter2")


def test_a_working_backend_is_unaffected(monkeypatch):
    store = {}

    class Working:
        @staticmethod
        def set_password(service, user, password):
            store[(service, user)] = password

        @staticmethod
        def get_password(service, user):
            return store.get((service, user))

        @staticmethod
        def get_keyring():
            return "RealBackend"

    _use(monkeypatch, Working)
    S.set_password("teradata", "prod", "jsmith", "hunter2")
    assert S.has_password("teradata", "prod", "jsmith") is True
    assert S.get_password("teradata", "prod", "jsmith") == "hunter2"
    assert S.backend_name() == "str"                    # type(...).__name__ of the string "RealBackend"


def test_service_name_shape():
    assert S.service("teradata", "prod") == "teradata:prod"
