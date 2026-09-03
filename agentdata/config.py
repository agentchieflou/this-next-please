"""Global config (~/.agentdata/config.json) + project facts (AGENTS.md) + env overrides.

No secret ever lands here: save() refuses credential-looking keys. Tokens stay in pncli's own
config (read by dot-path at call time), passwords live in `keyring` (see connectors/secrets.py).
"""

from __future__ import annotations
import datetime as _dt
import json
import os
import re
from typing import Any
from . import textio

CONFIG_ENV = "AGENTDATA_CONFIG"
DEFAULT_PATH = "~/.agentdata/config.json"
VERSION = 1
SOURCES = ("teradata", "hive", "impala", "oracle")

_SECRET_KEY = re.compile(r"(?:^|_)(password|passwd|pwd|secret|token|api_?key|pat|client_secret)$", re.I)
_SECRET_EXEMPT = ("pncli.keys.",)  # values there are key *names* (dot-paths into pncli's config), not secrets

# env-var overrides per source; keeps the original connectors' variables working
_ENV_VARS: dict[str, dict[str, tuple[str, ...]]] = {
    "teradata": {"host": ("TD_HOST_{ENV}", "TD_HOST"), "user": ("TD_USER",), "logmech": ("TD_LOGMECH",),
                 "dsn": ("TD_DSN_{ENV}", "TD_DSN"), "tmode": ("TD_TMODE",)},
    "hive": {"host": ("HIVE_HOST_{ENV}", "HIVE_HOST"), "port": ("HIVE_PORT",), "user": ("HIVE_USER",),
             "dsn": ("HIVE_DSN_{ENV}", "HIVE_DSN"), "auth": ("HIVE_AUTH",)},
    "impala": {"host": ("IMPALA_HOST_{ENV}", "IMPALA_HOST"), "port": ("IMPALA_PORT",), "user": ("IMPALA_USER",),
               "dsn": ("IMPALA_DSN_{ENV}", "IMPALA_DSN"), "auth": ("IMPALA_AUTH",)},
    # Oracle has no DSN registry (no odbcad32 equivalent), so the parts are first-class: host, port, service/SID.
    "oracle": {"host": ("ORA_HOST_{ENV}", "ORA_HOST"), "port": ("ORA_PORT_{ENV}", "ORA_PORT"),
               "service_name": ("ORA_SERVICE_{ENV}", "ORA_SERVICE"), "sid": ("ORA_SID_{ENV}", "ORA_SID"),
               "dsn": ("ORA_DSN_{ENV}", "ORA_DSN"), "user": ("ORA_USER",), "client_lib": ("ORACLE_CLIENT_LIB",),
               "tns_admin": ("TNS_ADMIN",)},
}
_PRIMARY_KEY = {"teradata": "host", "hive": "host", "impala": "host", "oracle": "host"}


class ConfigError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


# ---------- paths ----------
def expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def display_path(p: str) -> str:
    return p.replace("\\", "/")


def path() -> str:
    return expand(os.environ.get(CONFIG_ENV) or DEFAULT_PATH)


# ---------- load / save ----------
def load(p: str | None = None) -> dict:
    p = p or path()
    if not os.path.exists(p):
        return {"version": VERSION}
    try:
        data = json.loads(textio.read_text(p))
    except json.JSONDecodeError as e:
        raise ConfigError(f"config is not valid JSON: {display_path(p)} ({e.msg}, line {e.lineno})",
                          hint="fix or delete the file, then run ad-setup") from None
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be an object: {display_path(p)}", hint="delete the file, run ad-setup")
    data.setdefault("version", VERSION)
    return data


def save(cfg: dict, p: str | None = None) -> str:
    """Atomic write (tmp + os.replace). Refuses credential-looking keys."""
    p = p or path()
    assert_no_secrets(cfg)
    cfg["version"] = VERSION
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return display_path(p)


def assert_no_secrets(obj: Any, trail: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{trail}.{k}" if trail else str(k)
            if any(here.startswith(x) for x in _SECRET_EXEMPT):
                continue
            if _SECRET_KEY.search(str(k)) and isinstance(v, str) and v.strip():
                raise ConfigError(f"refusing to store a credential-looking value at {here}",
                                  hint="secrets go to keyring or pncli's own config, never to agentdata config")
            assert_no_secrets(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_secrets(v, f"{trail}.{i}")


def looks_secret(key: str) -> bool:
    return bool(_SECRET_KEY.search(key.rsplit(".", 1)[-1]))


# ---------- dot paths ----------
def get(obj: Any, dotpath: str, default: Any = None) -> Any:
    cur = obj
    for part in dotpath.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def put(cfg: dict, dotpath: str, value: Any) -> None:
    parts = dotpath.split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """dot-path -> leaf value (lists indexed). Used to list which keys a foreign config has."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}.{i}"))
    else:
        out[prefix] = obj
    return out


def mask(value: Any) -> str:
    s = "" if value is None else str(value)
    if not s:
        return ""
    if len(s) <= 8:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def merge_defaults(target: dict, defaults: dict) -> None:
    """Recursively populate missing or empty keys in target from defaults.
    Never overwrites an existing non-empty value in target."""
    for k, v in defaults.items():
        if isinstance(v, dict):
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            merge_defaults(target[k], v)
        elif k not in target or target[k] in (None, "", [], {}):
            if isinstance(v, list):
                target[k] = list(v)
            elif isinstance(v, dict):
                target[k] = dict(v)
            else:
                target[k] = v


# ---------- verified stamps ----------
def today() -> str:
    return _dt.date.today().isoformat()


def stamp(cfg: dict, key: str) -> None:
    cfg.setdefault("verified", {})[key] = today()


# ---------- project facts (AGENTS.md) ----------
_FACT = re.compile(r"^\s*-\s*([A-Za-z_][\w\-]*)\s*:\s*(.*?)\s*$")


def project_facts(agents_md: str = "AGENTS.md") -> dict[str, str]:
    """Parse `- key: value   # comment` lines. `<placeholders>` and empty values are dropped."""
    facts: dict[str, str] = {}
    if not os.path.exists(agents_md):
        return facts
    for line in textio.read_text(agents_md).splitlines():
        m = _FACT.match(line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2)
        val = re.split(r"\s+#", val, maxsplit=1)[0].strip().strip("`").strip('"').strip("'")
        if not val or (val.startswith("<") and val.endswith(">")):
            continue
        facts[key] = val
    return facts


def resolve(name: str, *, flag: Any = None, env: str | None = None, cfg: dict | None = None,
            cfg_path: str | None = None, facts: dict | None = None, facts_key: str | None = None,
            default: Any = None, hint: str = "") -> Any:
    """Precedence: CLI flag -> env var -> config dot-path -> project facts -> default -> ConfigError."""
    if flag not in (None, ""):
        return flag
    if env and os.environ.get(env):
        return os.environ[env]
    if cfg is not None and cfg_path:
        v = get(cfg, cfg_path)
        if v not in (None, ""):
            return v
    if facts is not None and (facts_key or name) in facts:
        return facts[facts_key or name]
    if default is not None:
        return default
    raise ConfigError(f"missing setting: {name}", hint or f"pass --{name.replace('_', '-')} or run ad-setup")


# ---------- data sources ----------
def source_env(cfg: dict | None, source: str, env: str) -> dict:
    """sources.<source>.envs.<env> merged with env-var overrides. Never contains a password."""
    if source not in SOURCES:
        raise ConfigError(f"unknown source {source}", hint=f"one of {', '.join(SOURCES)}")
    cfg = cfg if cfg is not None else load()
    e = dict(get(cfg, f"sources.{source}.envs.{env}", {}) or {})
    for key, names in _ENV_VARS[source].items():
        for n in names:
            v = os.environ.get(n.replace("{ENV}", env.upper()))
            if v:
                e[key] = v
                break
    e.setdefault("mode", "odbc" if e.get("dsn") and not e.get("host") and source != "oracle" else "native")
    e["env"], e["source"] = env, source
    if source == "oracle":
        composed = oracle_dsn(e)
        if composed:
            e["dsn"] = composed
        elif e.get("host"):
            raise ConfigError(f"oracle env '{env}' has a host but no service name or SID",
                              hint="ad-setup --patch (or set ORA_SERVICE), the way SQL Developer asks for Service name")
    if not (e.get("host") or e.get("dsn")):
        var = _ENV_VARS[source][_PRIMARY_KEY[source]][0].replace("{ENV}", env.upper())
        raise ConfigError(f"no {source} connection configured for env '{env}'",
                          hint=f"ad-setup --only sources (or set {var})")
    return e


ORACLE_PORT = 1521


def oracle_dsn(e: dict) -> str:
    """The connect string oracledb wants, from whichever shape was configured.

    Oracle is the source with no ODBC DSN to point at, so a connection is Hostname + Port + Service name (or SID) —
    the four fields SQL Developer's Basic tab asks for. An explicit `dsn` (a TNS alias, or a connect string someone
    pasted) always wins; otherwise the parts are composed here so every caller sees one `dsn`."""
    if e.get("dsn"):
        return str(e["dsn"]).strip()
    host = str(e.get("host") or "").strip()
    if not host:
        return ""
    port = int(e.get("port") or ORACLE_PORT)
    service = str(e.get("service_name") or "").strip()
    if service:
        return f"{host}:{port}/{service}"                      # Easy Connect
    sid = str(e.get("sid") or "").strip()
    if sid:                                                    # SID has no Easy Connect form; this is makedsn's output
        return f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={host})(PORT={port}))(CONNECT_DATA=(SID={sid})))"
    return ""


def capabilities(cfg: dict | None, source: str, env: str) -> dict:
    cfg = cfg if cfg is not None else load()
    return dict(get(cfg, f"sources.{source}.envs.{env}.capabilities", {}) or {})
