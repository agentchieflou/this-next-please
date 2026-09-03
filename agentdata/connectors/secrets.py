"""keyring wrapper. Service names are `<source>:<env>`. Nothing here ever prints a value."""
from __future__ import annotations
from ..config import ConfigError
from ..install import install_cmd


def service(source: str, env: str) -> str:
    return f"{source}:{env}"


def _keyring():
    try:
        import keyring  # a base dependency; this stays defensive for an install that skipped deps (--no-deps, a stripped venv)
    except ImportError:
        raise ConfigError("keyring is not installed", hint=install_cmd()) from None
    return keyring


def _guard(fn, what: str):
    """A broken backend (locked store, no D-Bus session, a native extension ABI mismatch, ...) must not crash
    the caller. `except Exception` is not enough: a native extension can panic as a bare `BaseException`
    (pyo3's `PanicException` does not subclass `Exception`), which is exactly the shape a wizard mid-question
    must survive -- the answers already given are worth more than a perfect keyring write."""
    try:
        return fn()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # noqa: BLE001 - deliberately broader than Exception; see above
        raise ConfigError(f"keyring backend failed on {what} ({type(e).__name__}: {str(e)[:160]})",
                          hint="ad-doctor's keyring row names the backend; a locked store or a broken native "
                               "extension needs fixing outside agentdata") from None


def get_password(source: str, env: str, user: str) -> str | None:
    return _guard(lambda: _keyring().get_password(service(source, env), user), "read")


def set_password(source: str, env: str, user: str, password: str) -> None:
    _guard(lambda: _keyring().set_password(service(source, env), user, password), "write")


def has_password(source: str, env: str, user: str) -> bool:
    try:
        return bool(get_password(source, env, user))
    except ConfigError:
        return False


def backend_name() -> str:
    try:
        return type(_guard(lambda: _keyring().get_keyring(), "backend detection")).__name__
    except ConfigError as e:
        return f"unavailable ({e})"
