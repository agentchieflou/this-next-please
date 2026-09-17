"""Signing in once, and carrying that sign-in to every tool that reaches the XMLA endpoint.

`az login` fills the Azure CLI's own token cache, and nothing else reads it. Tabular Editor 2 and
DAX Studio are built on the Analysis Services client libraries (AMO, ADOMD.NET), which keep a
*separate* MSAL cache that only their own interactive sign-in fills. That is the blocker this module
removes: the agent ran `az login --allow-no-subscriptions`, every REST call worked, and the first
`TabularEditor.exe powerbi://...` still failed -- or sat behind a sign-in window nobody could see --
until somebody opened Tabular Editor by hand, connected, and so seeded the cache the CLI reads.

The fix is to stop depending on that cache. The Azure CLI mints an access token for the Power BI
service audience (`az account get-access-token --resource https://analysis.windows.net/powerbi/api`),
and the client libraries take an access token in the connection string -- `Password=<token>` with
an empty `User ID`, the same slot a service principal fills with `User ID=app:<id>@<tenant>`.
Tabular Editor 2 accepts a connection string wherever its command line takes a server name, so
every TE2 launch this package makes -- deploy, refresh, DMV, DAX through `ExecuteReader`, the
doctor's ping -- carries a fresh token and needs no cache. dscmd has no documented token switch, so
service-side DAX goes through Tabular Editor too; dscmd keeps the Desktop instance
(`localhost:<port>`, which needs no sign-in) and `.vpax`.

Two knobs, both in `~/.agentdata/config.json` (`ad-setup --only powerbi` asks them):

* `powerbi.auth.mode`: `token` (default) or `interactive` -- the pre-0.10 behaviour, for a machine
  where the token form turns out not to work. `AGENTDATA_PBI_AUTH` overrides it per shell.
* `powerbi.auth.auto_login`: `true` (default) runs `az login --allow-no-subscriptions` itself, once,
  when the CLI says it is signed out, and then retries. `AGENTDATA_AZ_LOGIN=0` turns that off (CI,
  a machine with no browser). `az login` is the one interactive process this package starts: it
  opens the default browser, or prints a device code when `powerbi.auth.device_code` is true.

The token is a credential. It lives in memory for one command, reaches the child in its argv, and
`redact()` strips it from everything that is logged or printed: the deploy log, the tail of a
failed launch, the `source` line of a result, the doctor row. Nothing here ever writes it to disk.
"""
from __future__ import annotations
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from typing import Any, Callable

from .. import config as C
from .. import proc
from .errors import FabricError

POWERBI_RESOURCE = "https://analysis.windows.net/powerbi/api"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
MODE_TOKEN, MODE_INTERACTIVE = "token", "interactive"
MODES = (MODE_TOKEN, MODE_INTERACTIVE)
MODE_ENV = "AGENTDATA_PBI_AUTH"
LOGIN_ENV = "AGENTDATA_AZ_LOGIN"
SERVICE_PREFIX = "powerbi://"
REDACTED = "[REDACTED]"
# `az login` waits for a person and a browser. Five minutes is someone finishing MFA, not a hang.
LOGIN_TIMEOUT = 300
PING_CSX = 'Info("tables=" + Model.Tables.Count.ToString());\n'

# What the Azure CLI says when there is nothing to mint a token from. Matched on the whole message,
# case-insensitively: the sentence has changed across CLI versions, the AADSTS family has not, and
# every one of these is fixed by a sign-in -- which is the only thing the match is used to decide.
_SIGNED_OUT = re.compile(r"az login|AADSTS\d+|not logged in|interactive authentication|no accounts? were found"
                         r"|refresh token has expired", re.I)
_PASSWORD = re.compile(r"(Password\s*=\s*)([^;\s\"']+)", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")


class AuthError(FabricError):
    """A sign-in problem, named so a caller can tell *signed out* (a login fixes it) from *broken*."""


# ---------------------------------------------------------------------------------------- settings
def settings(cfg: dict | None = None) -> dict:
    """`{mode, auto_login, device_code, tenant, az}` with the env overrides applied.

    A mode that is not one of `MODES` is refused rather than defaulted: a typo in the config that
    silently meant `token` would make `interactive` impossible to switch on when it is needed.
    """
    cfg = cfg if cfg is not None else C.load()
    mode = str(os.environ.get(MODE_ENV) or C.get(cfg, "powerbi.auth.mode") or MODE_TOKEN).strip().lower()
    if mode not in MODES:
        raise C.ConfigError(f"powerbi.auth.mode is {mode!r}", hint="one of " + " | ".join(MODES) + " (ad-setup --patch)")
    env_login = os.environ.get(LOGIN_ENV)
    if env_login is not None:
        auto_login = env_login.strip().lower() not in ("0", "false", "no", "off", "")
    else:
        configured = C.get(cfg, "powerbi.auth.auto_login")
        auto_login = True if configured is None else bool(configured)
    return {"mode": mode, "auto_login": auto_login,
            "device_code": bool(C.get(cfg, "powerbi.auth.device_code")),
            "tenant": C.get(cfg, "powerbi.tenant_id") or None,
            "az": C.get(cfg, "powerbi.tools.az_exe") or "az"}


def xmla_url(workspace: str) -> str:
    """`powerbi://api.powerbi.com/v1.0/myorg/<name>`, RFC 3986 percent-encoded (spaces -> %20)."""
    return SERVICE_PREFIX + "api.powerbi.com/v1.0/myorg/" + urllib.parse.quote(workspace, safe="")


def is_service(server: str) -> bool:
    """A Power BI service XMLA address, as a URL or already inside a connection string."""
    s = (server or "").strip().lower()
    return s.startswith(SERVICE_PREFIX) or f"data source={SERVICE_PREFIX}" in s


def token_route(server: str, cfg: dict | None = None) -> bool:
    """Does a query against `server` carry an az token (service address, token mode)? A Desktop
    instance (`localhost:<port>`) never does: it has no sign-in at all."""
    return is_service(server) and settings(cfg)["mode"] == MODE_TOKEN


def signed_out(text: str) -> bool:
    return bool(_SIGNED_OUT.search(text or ""))


# --------------------------------------------------------------------------------------- redaction
def redact(text: str, *secrets: str) -> str:
    """`text` with every token removed: the ones the caller names, any `Password=` value, any JWT."""
    out = "" if text is None else str(text)
    for s in secrets:
        if s:
            out = out.replace(s, REDACTED)
    out = _PASSWORD.sub(lambda m: m.group(1) + REDACTED, out)
    return _JWT.sub(REDACTED, out)


def display(cmd: list[str]) -> str:
    """A command line safe to log: every argument redacted, joined with spaces."""
    return " ".join(redact(str(a)) for a in cmd)


# ------------------------------------------------------------------------------------ the Azure CLI
def _run(runner: Callable | None, cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """One az call through whichever runner the caller injected. Runners here answer with three or
    four values (`proc.run` adds the elapsed time); only the first three matter."""
    try:
        res = (runner or proc.run)(cmd, timeout=timeout)
    except proc.ProcError as e:
        code = "az_not_found" if e.code == "not_found" else "az_failed"
        raise AuthError(code, f"{cmd[0]}: {e.msg}",
                        e.hint or "install the Azure CLI, or `ad-setup --patch` and give powerbi.tools.az_exe "
                                  r"(usually C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd)") from None
    return int(res[0]), str(res[1] or ""), str(res[2] or "")


def account(*, az: str | None = None, runner: Callable | None = None, cfg: dict | None = None) -> dict | None:
    """`az account show`: who is signed in, or None for a signed-out CLI. Never raises for signed-out."""
    rc, out, _err = _run(runner, [az or settings(cfg)["az"], "account", "show", "-o", "json"], 60)
    if rc != 0:
        return None
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def get_token(resource: str = POWERBI_RESOURCE, *, az: str | None = None, tenant: str | None = None,
              runner: Callable | None = None, cfg: dict | None = None) -> dict:
    """`az account get-access-token` for one audience. `{token, expires_on, tenant, resource}`.

    Raises `AuthError("not_signed_in")` when a sign-in would fix it and `auth_failed` otherwise. The
    message never carries the token; the failure text is redacted before it is kept.
    """
    s = settings(cfg)
    az = az or s["az"]
    tenant = tenant if tenant is not None else s["tenant"]
    cmd = [az, "account", "get-access-token", "--resource", resource, "-o", "json"]
    if tenant:
        cmd.extend(["--tenant", str(tenant)])
    rc, out, err = _run(runner, cmd, 60)
    if rc != 0:
        text = redact((err or out).strip())
        if signed_out(text):
            raise AuthError("not_signed_in", f"the Azure CLI is signed out: {text[-160:]}",
                            "run `ad-pbi auth` (it signs in for you), or `az login --allow-no-subscriptions`")
        raise AuthError("auth_failed", f"az could not mint a token for {resource}: {text[-200:]}",
                        "check powerbi.tenant_id (ad-setup --patch), or `ad-pbi auth --login` to sign in again")
    try:
        data = json.loads(out or "{}")
    except ValueError:
        raise AuthError("auth_failed", "malformed token response from az", "`ad-pbi auth --login`") from None
    token = data.get("accessToken") if isinstance(data, dict) else None
    if not token:
        raise AuthError("auth_failed", "az answered without an accessToken", "`ad-pbi auth --login`")
    return {"token": str(token), "expires_on": str(data.get("expiresOn") or data.get("expires_on") or ""),
            "tenant": str(data.get("tenant") or tenant or ""), "resource": resource}


def _interactive(argv: list[str]) -> int:
    """Start `az login` with the console it needs. Its stdout is sent to stderr: stdout is the TOON
    channel of whichever `ad-*` command is running, and a JSON account list in the middle of it
    would corrupt the parse. The sign-in prompt and the device code go to stderr anyway."""
    try:
        err_fd: int | None = sys.stderr.fileno()
    except (AttributeError, ValueError, io.UnsupportedOperation):
        err_fd = None
    try:
        return int(subprocess.call(proc.command(argv), stdout=err_fd, timeout=LOGIN_TIMEOUT, env=proc.child_env()))
    except subprocess.TimeoutExpired:
        return 124
    except (proc.ProcError, FileNotFoundError, OSError):
        return 127


def login_argv(*, az: str | None = None, tenant: str | None = None, device_code: bool | None = None,
               cfg: dict | None = None) -> list[str]:
    """The exact `az login` line: `--allow-no-subscriptions` always (a Power BI user rarely owns an
    Azure subscription, and without the flag the sign-in is thrown away), the tenant when one is
    configured, `-o none` so no account list lands on any channel."""
    s = settings(cfg)
    argv = [az or s["az"], "login", "--allow-no-subscriptions", "-o", "none"]
    t = tenant if tenant is not None else s["tenant"]
    if t:
        argv.extend(["--tenant", str(t)])
    if s["device_code"] if device_code is None else device_code:
        argv.append("--use-device-code")
    return argv


def login(*, az: str | None = None, tenant: str | None = None, device_code: bool | None = None,
          cfg: dict | None = None, run_interactive: Callable[[list[str]], int] | None = None) -> int:
    """`az login --allow-no-subscriptions`, in the person's browser or with a device code. Exit code."""
    return int((run_interactive or _interactive)(login_argv(az=az, tenant=tenant, device_code=device_code, cfg=cfg)))


def ensure_token(resource: str = POWERBI_RESOURCE, *, cfg: dict | None = None, az: str | None = None,
                 tenant: str | None = None, runner: Callable | None = None, auto_login: bool | None = None,
                 run_interactive: Callable[[list[str]], int] | None = None) -> dict:
    """A token for `resource`, signing in first when the CLI is signed out and auto-login is on.

    One sign-in, one retry. A second failure is reported, never looped: a browser window that
    keeps reopening is the failure mode this exists to prevent.
    """
    s = settings(cfg)
    try:
        return get_token(resource, az=az, tenant=tenant, runner=runner, cfg=cfg)
    except AuthError as e:
        if e.code != "not_signed_in" or not (s["auto_login"] if auto_login is None else auto_login):
            raise
    rc = login(az=az, tenant=tenant, cfg=cfg, run_interactive=run_interactive)
    if rc != 0:
        raise AuthError("login_failed", f"az login exited {rc}",
                        "run `az login --allow-no-subscriptions` in a terminal and read what it says; set "
                        "powerbi.auth.device_code=true when no browser can open on this machine")
    tok = get_token(resource, az=az, tenant=tenant, runner=runner, cfg=cfg)
    tok["logged_in"] = True
    return tok


# ------------------------------------------------------------------------------ what TE2 is handed
def connection_string(xmla: str, token: str) -> str:
    """The AMO/ADOMD form of "this token, not a cached sign-in": empty `User ID`, the token as `Password`."""
    return f"Provider=MSOLAP;Data Source={xmla};User ID=;Password={token}"


def xmla_source(xmla: str, *, cfg: dict | None = None, runner: Callable | None = None, mode: str | None = None,
                auto_login: bool | None = None, run_interactive: Callable[[list[str]], int] | None = None) -> str:
    """What to hand Tabular Editor where it wants a server.

    Token mode and a service URL: a connection string carrying a fresh az token. Anything else --
    interactive mode, a Desktop `localhost:<port>`, a string that is already a connection string --
    comes back untouched, so a caller can pass every server through here without thinking.
    """
    cfg = cfg if cfg is not None else C.load()
    if (mode or settings(cfg)["mode"]) != MODE_TOKEN or not is_service(xmla) or "=" in xmla:
        return xmla
    tok = ensure_token(POWERBI_RESOURCE, cfg=cfg, runner=runner, auto_login=auto_login, run_interactive=run_interactive)
    return connection_string(xmla, tok["token"])


def describe(*, cfg: dict | None = None, runner: Callable | None = None, mint: bool = True) -> dict:
    """The auth row, for `ad-pbi auth` and the doctor: mode, sign-in state, whether a Power BI token
    can be minted right now and when it expires. Never the token itself."""
    cfg = cfg if cfg is not None else C.load()
    s = settings(cfg)
    row: dict[str, Any] = {"mode": s["mode"], "auto_login": s["auto_login"], "az": s["az"], "tenant": s["tenant"] or ""}
    try:
        acct = account(az=s["az"], runner=runner, cfg=cfg)
    except AuthError as e:
        row.update({"signed_in": False, "token": e.code, "error": e.msg, "hint": e.hint})
        return row
    row["signed_in"] = acct is not None
    if acct:
        row["account"] = str((acct.get("user") or {}).get("name") or acct.get("name") or "")
        row["tenant"] = str(acct.get("tenantId") or row["tenant"])
    if mint:
        try:
            tok = get_token(POWERBI_RESOURCE, az=s["az"], runner=runner, cfg=cfg)
            row["token"] = "ok"
            row["expires_on"] = tok["expires_on"]
        except AuthError as e:
            row.update({"token": e.code, "error": e.msg, "hint": e.hint})
    return row


def probe(xmla: str, model: str, *, te2: str | None = None, cfg: dict | None = None,
          runner: Callable | None = None, timeout: int = 180, auto_login: bool | None = None) -> dict:
    """Prove the XMLA endpoint answers Tabular Editor with this sign-in: one `-S` script that counts
    the tables and saves nothing. The whole reason a person used to open Tabular Editor by hand."""
    cfg = cfg if cfg is not None else C.load()
    te2 = te2 or C.get(cfg, "powerbi.tools.te2_exe") or proc.which("TabularEditor.exe")
    if not te2:
        return {"ok": False, "code": "no_te2", "error": "no TabularEditor.exe to probe with",
                "hint": "ad-setup --patch (powerbi.te2_exe)"}
    try:
        source = xmla_source(xmla, cfg=cfg, runner=runner, auto_login=auto_login)
    except AuthError as e:
        return {"ok": False, "code": e.code, "error": e.msg, "hint": e.hint}
    with tempfile.TemporaryDirectory() as td:
        csx = os.path.join(td, "ping.csx")
        with open(csx, "w", encoding="utf-8") as f:
            f.write(PING_CSX)
        rc, out, err = _run(runner, [te2, source, model, "-S", csx], timeout)
    detail = redact(((out or "") + (err or "")).strip()[-200:])
    row = {"ok": rc == 0, "rc": rc, "mode": settings(cfg)["mode"], "detail": detail}
    if rc != 0:
        row["hint"] = ("XMLA read needs Premium/PPU with the endpoint enabled and this account on the workspace; "
                       "AGENTDATA_PBI_AUTH=interactive re-runs it the old way, to tell a token problem from a permission one")
    return row
