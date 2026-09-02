"""Step 2: data sources — Teradata, Hive, Impala, Oracle. Native driver or ODBC DSN per env, SELECT 1 smoke test,
capability probes (consumed by ad-sql-check). Passwords go to keyring under `<source>:<env>`, never to config."""
from __future__ import annotations
import json
from ... import config as C
from ...install import install_cmd
from ..wizard import Context, Step

LABEL = {"teradata": "Teradata", "hive": "Hive (HiveServer2)", "impala": "Impala", "oracle": "Oracle"}
MODULE = {"teradata": "teradatasql", "hive": "impala", "impala": "impala", "oracle": "oracledb"}
DEFAULT_PORT = {"hive": 10000, "impala": 21050}
TD_LOGMECH = ["KRB5", "TDNEGO", "LDAP", "TD2"]
HS2_AUTH = ["GSSAPI", "PLAIN", "LDAP", "NOSASL"]


def needs_password(source: str, e: dict) -> bool:
    if source == "teradata":
        return str(e.get("logmech", "")).upper() in ("LDAP", "TD2")
    if source in ("hive", "impala"):
        return str(e.get("auth", "GSSAPI")).upper() in ("PLAIN", "LDAP")
    if source == "oracle":
        return not (e.get("client_lib") or e.get("thick"))
    return False


def uses_kerberos(source: str, e: dict) -> bool:
    if source == "teradata":
        return str(e.get("logmech", "KRB5")).upper() in ("KRB5", "TDNEGO")
    if source in ("hive", "impala"):
        return str(e.get("auth", "GSSAPI")).upper() == "GSSAPI"
    return bool(e.get("client_lib") or e.get("thick"))


class SourcesStep(Step):
    key = "sources"
    title = "data sources (Teradata / Hive / Impala / Oracle)"

    def detect(self, ctx: Context) -> dict:
        det = ctx.det
        has_pyodbc = det.module("pyodbc")
        return {"modules": {s: det.module(MODULE[s]) for s in C.SOURCES}, "pyodbc": has_pyodbc,
                "drivers": det.odbc_drivers() if has_pyodbc else [], "dsns": det.odbc_dsns() if has_pyodbc else {},
                "keyring": det.module("keyring"), "klist": bool(det.which("klist")), "bits": det.python_bits(),
                "envs": {s: dict(C.get(ctx.cfg, f"sources.{s}.envs", {}) or {}) for s in C.SOURCES}}

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        any_env = kerberos = False
        for s in C.SOURCES:
            for env, e in found["envs"][s].items():
                any_env = True
                tag, mode = f"{s}:{env}", e.get("mode", "native")
                kerberos = kerberos or uses_kerberos(s, e)
                if mode == "odbc":
                    if not found["pyodbc"]:
                        ctx.add(k, tag, "fail", "mode odbc but pyodbc is missing", install_cmd("odbc"))
                        continue
                    if e.get("dsn") not in found["dsns"]:
                        ctx.add(k, tag, "fail", f"DSN '{e.get('dsn')}' not visible to this {found['bits']}-bit Python",
                                "create it in C:/Windows/System32/odbcad32.exe (64-bit) or fix the dsn (ad-setup --only sources)")
                        continue
                elif not found["modules"][s]:
                    ctx.add(k, tag, "fail", f"{MODULE[s]} not installed", install_cmd(s))
                    continue
                if needs_password(s, e):
                    if not found["keyring"]:
                        ctx.add(k, tag, "fail", "password auth but keyring is missing", install_cmd("keyring"))
                        continue
                    user = e.get("user") or ctx.det.getuser()
                    if not ctx.det.has_password(s, env, user):
                        ctx.add(k, tag, "fail", f"no password in keyring for {tag} user {user}", "ad-setup --only sources")
                        continue
                v = C.get(ctx.cfg, f"verified.{tag}")
                ctx.add(k, tag, "ok" if v else "warn", f"{mode} · verified {v}" if v else f"{mode} · never verified",
                        "" if v else "ad-doctor --online or ad-setup --only sources")
        if not any_env:
            ctx.add(k, "sources", "warn", "no data sources configured", "ad-setup --only sources")
        if kerberos and not found["klist"]:
            ctx.add(k, "kerberos", "warn", "klist not on PATH (no Kerberos tools found)",
                    "Kerberos logons need a TGT; install MIT Kerberos, or switch the env to LDAP/TD2 with a keyring password")

    def ask(self, ctx: Context, found: dict) -> None:
        det = ctx.det
        if found["pyodbc"]:
            ctx.say(f"  ODBC ({found['bits']}-bit Python): {len(found['drivers'])} drivers · DSNs: {', '.join(found['dsns']) or 'none'}")
        for s in C.SOURCES:
            existing = found["envs"][s]
            if not ctx.ask.confirm(f"sources.{s}.use", f"Use {LABEL[s]}?", bool(existing) or found["modules"][s]):
                continue
            raw = ctx.ask.ask(f"sources.{s}.envs", f"[{s}] environment names (comma-separated)", ",".join(existing) or "prod")
            envs = [x.strip() for x in raw.split(",") if x.strip()] or ["prod"]
            for env in envs:
                e = dict(existing.get(env, {}))
                e.pop("env", None)
                e.pop("source", None)
                tag = f"{s}:{env}"
                modes = ([("native")] if found["modules"][s] else []) + (["odbc"] if found["pyodbc"] and found["dsns"] else [])
                modes = modes or ["native", "odbc"]
                mode = ctx.ask.ask(f"sources.{s}.{env}.mode", f"[{tag}] connection mode", e.get("mode") or modes[0], modes) or modes[0]
                e["mode"] = mode
                if mode == "odbc":
                    names = list(found["dsns"])
                    for i, d in enumerate(names, 1):
                        ctx.say(f"    {i}. {d} ({found['dsns'][d]})")
                    ans = ctx.ask.ask(f"sources.{s}.{env}.dsn", f"[{tag}] DSN name or number", e.get("dsn") or "")
                    if ans.isdigit() and 1 <= int(ans) <= len(names):
                        ans = names[int(ans) - 1]
                    e["dsn"] = ans
                    e.pop("host", None)
                    if s == "teradata":
                        e["logmech"] = ctx.ask.ask(f"sources.{s}.{env}.logmech", f"[{tag}] logon mechanism", e.get("logmech") or "KRB5", TD_LOGMECH) or "KRB5"
                    elif s in ("hive", "impala"):
                        e["auth"] = ctx.ask.ask(f"sources.{s}.{env}.auth", f"[{tag}] auth mechanism", e.get("auth") or "GSSAPI", HS2_AUTH) or "GSSAPI"
                elif s == "oracle":
                    e["dsn"] = ctx.ask.ask(f"sources.{s}.{env}.dsn", f"[{tag}] Easy Connect (host:1521/service) or TNS alias", e.get("dsn") or "")
                    for opt, label in (("tns_admin", "TNS_ADMIN directory (blank = none)"),
                                       ("client_lib", "Oracle client lib dir for Kerberos (blank = thin mode + password)")):
                        v = ctx.ask.ask(f"sources.{s}.{env}.{opt}", f"[{tag}] {label}", e.get(opt) or "")
                        if v:
                            e[opt] = v
                        else:
                            e.pop(opt, None)
                else:
                    e["host"] = ctx.ask.ask(f"sources.{s}.{env}.host", f"[{tag}] host", e.get("host") or "")
                    e.pop("dsn", None)
                    if s in ("hive", "impala"):
                        port = ctx.ask.ask(f"sources.{s}.{env}.port", f"[{tag}] port", str(e.get("port") or DEFAULT_PORT[s]))
                        e["port"] = int(port) if str(port).isdigit() else DEFAULT_PORT[s]
                        e["auth"] = ctx.ask.ask(f"sources.{s}.{env}.auth", f"[{tag}] auth mechanism", e.get("auth") or "GSSAPI", HS2_AUTH) or "GSSAPI"
                        e["ssl"] = ctx.ask.confirm(f"sources.{s}.{env}.ssl", f"[{tag}] TLS?", bool(e.get("ssl", False)))
                    else:
                        e["logmech"] = ctx.ask.ask(f"sources.{s}.{env}.logmech", f"[{tag}] logon mechanism", e.get("logmech") or "KRB5", TD_LOGMECH) or "KRB5"
                        tm = ctx.ask.ask(f"sources.{s}.{env}.tmode", f"[{tag}] transaction mode ANSI/TERA (blank = server default)", e.get("tmode") or "")
                        if tm:
                            e["tmode"] = tm.upper()
                        else:
                            e.pop("tmode", None)
                if needs_password(s, e):
                    user = ctx.ask.ask(f"sources.{s}.{env}.user", f"[{tag}] user", e.get("user") or det.getuser())
                    e["user"] = user
                    if det.has_password(s, env, user) and ctx.ask.confirm(f"sources.{s}.{env}.keep_password", f"[{tag}] keep the password already in keyring?", True):
                        pass
                    elif ctx.interactive:
                        pw = ctx.ask.ask(f"sources.{s}.{env}.password", f"[{tag}] password (stored in keyring only)", secret=True)
                        if pw:
                            det.set_password(s, env, user, pw)
                    else:
                        ctx.add(self.key, tag, "warn", "password auth configured but no keyring entry",
                                "run interactive `ad-setup --only sources` once to store it")
                C.put(ctx.cfg, f"sources.{s}.envs.{env}", e)
            envs_cfg = C.get(ctx.cfg, f"sources.{s}.envs") or {}
            for old in list(envs_cfg):
                if old not in envs:
                    envs_cfg.pop(old, None)

    def verify(self, ctx: Context) -> None:
        for s in C.SOURCES:
            for env, e in (C.get(ctx.cfg, f"sources.{s}.envs", {}) or {}).items():
                tag = f"{s}:{env}"
                try:
                    r = ctx.det.smoke(s, env, ctx.cfg)
                except Exception as ex:  # noqa: BLE001
                    ctx.add(self.key, tag, "fail", f"{type(ex).__name__}: {str(ex)[:160]}",
                            getattr(ex, "hint", "") or "check host/DSN, VPN, TGT (klist), keyring password; ad-setup --only sources")
                    continue
                caps = r.get("capabilities", {}) or {}
                e["capabilities"] = caps
                C.put(ctx.cfg, f"sources.{s}.envs.{env}", e)
                C.stamp(ctx.cfg, tag)
                ctx.add(self.key, tag, "ok", f"SELECT 1 ok in {r.get('elapsed_s')}s · caps {json.dumps(caps, sort_keys=True)}"[:200])
