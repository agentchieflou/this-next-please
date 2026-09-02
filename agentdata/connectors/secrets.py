"""keyring wrapper. Service names are `<source>:<env>`. Nothing here ever prints a value."""
from __future__ import annotations
from ..config import ConfigError
from ..install import install_cmd


def service(source: str, env: str) -> str:
    return f"{source}:{env}"


def _keyring():
    try:
        import keyring  # optional dep
    except ImportError:
        raise ConfigError("keyring is not installed", hint=install_cmd("keyring")) from None
    return keyring


def get_password(source: str, env: str, user: str) -> str | None:
    return _keyring().get_password(service(source, env), user)


def set_password(source: str, env: str, user: str, password: str) -> None:
    _keyring().set_password(service(source, env), user, password)


def has_password(source: str, env: str, user: str) -> bool:
    try:
        return bool(get_password(source, env, user))
    except Exception:  # noqa: BLE001 - no backend, locked store, ...
        return False


def backend_name() -> str:
    try:
        return type(_keyring().get_keyring()).__name__
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({type(e).__name__})"
