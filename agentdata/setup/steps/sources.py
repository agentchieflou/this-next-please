"""Step 2: data sources — Teradata, Hive, Impala, Oracle. Native driver or ODBC DSN per env, SELECT 1 smoke test,
capability probes (consumed by ad-sql-check). Passwords go to keyring under `<source>:<env>`, never to config."""
from __future__ import annotations
import json
from ... import config as C
from ...install import install_cmd
from ..wizard import Context, Step

LABEL = {"teradata": "Teradata", "hive": "Hive (HiveServer2)", "impala": "Impala", "oracle": "Oracle"}
ORA_STYLES = ["basic", "tns"]      # basic = hostname + port + service/SID (SQL Developer's Basic tab); tns = alias
ORA_IDENT = ["service", "sid"]
# Thick mode (client_lib) and authentication are INDEPENDENT: thick is also how you reach an old server or a wallet,
# and it still takes a username and password. Only kerberos/wallet skip the credential prompts.
ORA_AUTH = ["password", "kerberos", "wallet"]
MODULE = {"teradata": "teradatasql", "hive": "impala", "impala": "impala", "oracle": "oracledb"}
DEFAULT_PORT = {"hive": 10000, "impala": 21050}
TD_LOGMECH = ["KRB5", "TDNEGO", "LDAP", "TD2"]
HS2_AUTH = ["GSSAPI", "PLAIN", "LDAP", "NOSASL"]


def ora_auth(e: dict) -> str:
    """password | kerberos | wallet. Configs written before this question existed meant Kerberos by setting client_lib."""
    a = str(e.get("auth") or "").strip().lower()
    if a in ORA_AUTH:
        return a
    return "kerberos" if (e.get("client_lib") or e.get("thick")) else "password"


def needs_password(source: str, e: dict) -> bool:
    if source == "teradata":
        return str(e.get("logmech", "")).upper() in ("LDAP", "TD2")
    if source in ("hive", "impala"):
        return str(e.get("auth", "GSSAPI")).upper() in ("PLAIN", "LDAP")
    if source == "oracle":
        return ora_auth(e) == "password"
    return False


def _password_row(ctx: Context, key: str, tag: str, s: str, env: str, user: str) -> None:
    """One shared row for `check()` and `verify()`: a password-auth source with nothing in keyring is never
    worth a live connection attempt -- ad-doctor and ad-setup's own verify step are always non-interactive, so
    they must say "a human needs to run --patch" instead of dialing out with no credential and hitting
    whatever the driver does about that (hang, its own native prompt, a cryptic error)."""
    ctx.add(key, tag, "fail", f"no password in keyring for {tag} user {user}",
            f"ad-setup --patch sources.{s}.{env}.password -- a password prompt needs a human at a real "
            "terminal; it cannot be answered non-interactively",
            (f"sources.{s}.{env}.user", f"sources.{s}.{env}.keep_password", f"sources.{s}.{env}.password"))


def uses_kerberos(source: str, e: dict) -> bool:
    if source == "teradata":
        return str(e.get("logmech", "KRB5")).upper() in ("KRB5", "TDNEGO")
    if source in ("hive", "impala"):
        return str(e.get("auth", "GSSAPI")).upper() == "GSSAPI"
    return ora_auth(e) == "kerberos"


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
                        ctx.add(k, tag, "fail", "mode odbc but pyodbc is missing", install_cmd())          # install, not an answer
                        continue
                    if e.get("dsn") not in found["dsns"]:
                        ctx.add(k, tag, "fail", f"DSN '{e.get('dsn')}' not visible to this {found['bits']}-bit Python",
                                "create it in C:/Windows/System32/odbcad32.exe (64-bit) or fix the dsn (ad-setup --patch)",
                                (f"sources.{s}.{env}.dsn",))
                        continue
                elif not found["modules"][s]:
                    ctx.add(k, tag, "fail", f"{MODULE[s]} not installed", install_cmd(s))                    # install, not an answer
                    continue
                if s == "oracle" and ora_auth(e) != "password" and not (e.get("client_lib") or e.get("thick")):
                    ctx.add(k, tag, "fail", f"{ora_auth(e)} auth needs the Oracle client (thick mode) but no client_lib is set",
                            "give the Instant Client lib dir (…/instantclient_XX), or switch auth to password: ad-setup --patch",
                            (f"sources.{s}.{env}.auth", f"sources.{s}.{env}.client_lib"))
                    continue
                if s == "oracle" and not C.oracle_dsn(e):
                    if e.get("host"):        # only the identifier is missing: ask for that, not the whole connection
                        missing, keys = "service name or SID", (f"sources.{s}.{env}.identifier", f"sources.{s}.{env}.service_name",
                                                                f"sources.{s}.{env}.sid")
                    else:
                        missing, keys = "hostname (or a TNS alias)", (f"sources.{s}.{env}.style", f"sources.{s}.{env}.host",
                                                                      f"sources.{s}.{env}.port", f"sources.{s}.{env}.identifier",
                                                                      f"sources.{s}.{env}.service_name", f"sources.{s}.{env}.sid",
                                                                      f"sources.{s}.{env}.dsn")
                    ctx.add(k, tag, "fail", f"incomplete Oracle connection: no {missing}",
                            "Oracle has no ODBC DSN: it needs hostname + port + service name. `ad-setup --patch`", keys)
                    continue
                if needs_password(s, e):
                    if not found["keyring"]:
                        ctx.add(k, tag, "fail", "password auth but keyring is missing", install_cmd())  # install, not an answer
                        continue
                    user = e.get("user") or ctx.det.getuser()
                    if not ctx.det.has_password(s, env, user):
                        _password_row(ctx, k, tag, s, env, user)
                        continue
                v = C.get(ctx.cfg, f"verified.{tag}")
                target = f" · {C.oracle_dsn(e)}" if s == "oracle" else ""
                ctx.add(k, tag, "ok" if v else "warn", (f"{mode} · verified {v}" if v else f"{mode} · never verified") + target,
                        "" if v else "ad-doctor --online or ad-setup --patch", (f"sources.{s}.{env}.",))
        if not any_env:
            ctx.add(k, "sources", "warn", "no data sources configured", "ad-setup --only sources", ("sources.",))
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
            label = "connection names, e.g. OIMPROD1_ROSVC" if s == "oracle" else "environment names"
            raw = ctx.ask.ask(f"sources.{s}.envs", f"[{s}] {label} (comma-separated)", ",".join(existing) or "prod")
            envs = [x.strip() for x in raw.split(",") if x.strip()] or ["prod"]
            for env in envs:
                e = dict(existing.get(env, {}))
                e.pop("env", None)
                e.pop("source", None)
                tag = f"{s}:{env}"
                if s == "oracle":
                    mode = "native"          # python-oracledb only; an ODBC DSN here would be read as a TNS alias
                else:
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
                    # Oracle has no ODBC DSN to pick from, so ask for the parts SQL Developer's Basic tab asks for
                    style = ctx.ask.ask(f"sources.{s}.{env}.style", f"[{tag}] connection style",
                                        e.get("style") or ("tns" if e.get("dsn") and not e.get("host") else "basic"),
                                        ORA_STYLES) or "basic"
                    e["style"] = style
                    if style == "basic":
                        e["host"] = ctx.ask.ask(f"sources.{s}.{env}.host", f"[{tag}] hostname", e.get("host") or "")
                        port = ctx.ask.ask(f"sources.{s}.{env}.port", f"[{tag}] port", str(e.get("port") or C.ORACLE_PORT))
                        e["port"] = int(port) if str(port).isdigit() else C.ORACLE_PORT
                        which = ctx.ask.ask(f"sources.{s}.{env}.identifier", f"[{tag}] identified by",
                                            "sid" if e.get("sid") and not e.get("service_name") else "service", ORA_IDENT) or "service"
                        if which == "service":
                            e["service_name"] = ctx.ask.ask(f"sources.{s}.{env}.service_name", f"[{tag}] service name", e.get("service_name") or "")
                            e.pop("sid", None)
                        else:
                            e["sid"] = ctx.ask.ask(f"sources.{s}.{env}.sid", f"[{tag}] SID", e.get("sid") or "")
                            e.pop("service_name", None)
                        e.pop("dsn", None)                      # composed from the parts (config.oracle_dsn)
                    else:
                        e["dsn"] = ctx.ask.ask(f"sources.{s}.{env}.dsn", f"[{tag}] TNS alias or connect string (host:1521/service)",
                                               e.get("dsn") or "")
                        for k in ("host", "port", "service_name", "sid"):
                            e.pop(k, None)
                    auth = ctx.ask.ask(f"sources.{s}.{env}.auth", f"[{tag}] authentication", ora_auth(e), ORA_AUTH) or "password"
                    e["auth"] = auth
                    lib_label = ("Oracle Instant Client lib dir (REQUIRED for %s)" % auth if auth != "password"
                                 else "Oracle Instant Client lib dir (blank = thin mode, which is fine with a password)")
                    for opt, label in (("tns_admin", "TNS_ADMIN directory (blank = none)"), ("client_lib", lib_label)):
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
                            try:
                                det.set_password(s, env, user, pw)
                            except C.ConfigError as ex:
                                # a broken keyring backend must not throw away the rest of this env's answers
                                ctx.add(self.key, tag, "warn", str(ex), ex.hint)
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
                if needs_password(s, e):
                    user = e.get("user") or ctx.det.getuser()
                    if not ctx.det.has_password(s, env, user):
                        # this is what check()/ad-doctor already do; verify() is called directly by ad-setup's
                        # own wizard right after ask() and had NO such guard, so declining (or losing) the
                        # password there went straight to smoke() -- a live connection with no credential
                        _password_row(ctx, self.key, tag, s, env, user)
                        continue
                try:
                    r = ctx.det.smoke(s, env, ctx.cfg)
                except Exception as ex:  # noqa: BLE001
                    ctx.add(self.key, tag, "fail", f"{type(ex).__name__}: {str(ex)[:160]}",
                            getattr(ex, "hint", "") or "check host/DSN, VPN, TGT (klist), keyring password; `ad-setup --patch` re-asks just this env",
                            (f"sources.{s}.{env}.",))
                    continue
                caps = r.get("capabilities", {}) or {}
                e["capabilities"] = caps
                C.put(ctx.cfg, f"sources.{s}.envs.{env}", e)
                C.stamp(ctx.cfg, tag)
                ctx.add(self.key, tag, "ok", f"SELECT 1 ok in {r.get('elapsed_s')}s · caps {json.dumps(caps, sort_keys=True)}"[:200])
