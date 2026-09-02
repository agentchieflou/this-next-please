"""Step 1: import pncli's global config (~/.pncli/config.json) by KEY NAME. Values are never stored here;
the Jira token is read from pncli's file at call time (connectors/jira_api.py) and never printed."""
from __future__ import annotations
import re
from ... import config as C
from ..wizard import Context, Step

DEFAULT_PNCLI_CONFIG = "~/.pncli/config.json"
NPM_PACKAGE = "@kolatts/pncli"   # laptop diagnosis 2026-09-02; override with the `pncli.npm_package` config key
_URL_KEY = re.compile(r"(url|base_?url|host|server|site)$", re.I)
_EMAIL_KEY = re.compile(r"(email|e_?mail|user(name)?|login|account)$", re.I)
_TOKEN_KEY = re.compile(r"(token|api_?token|pat|password|secret|api_?key)$", re.I)
_PRED = {"jira_url": lambda v: v.startswith("http") or "." in v,
         "jira_email": lambda v: "@" in v,
         "jira_token": lambda v: len(v) >= 8}
_RX = {"jira_url": _URL_KEY, "jira_email": _EMAIL_KEY, "jira_token": _TOKEN_KEY}


def propose(flat: dict) -> dict[str, str | None]:
    """Best-guess pncli key paths for url / email / token, by key name (+1 when the path mentions jira)."""
    best: dict[str, str | None] = {k: None for k in _RX}
    scores = {k: 0 for k in _RX}
    for path, val in flat.items():
        if not isinstance(val, str) or not val:
            continue
        last = path.rsplit(".", 1)[-1]
        for name, rx in _RX.items():
            if not rx.search(last):
                continue
            sc = 2 + (1 if "jira" in path.lower() else 0) + (1 if _PRED[name](val) else 0)
            if sc > scores[name]:
                scores[name], best[name] = sc, path
    return best


class PncliStep(Step):
    key = "pncli"
    title = "pncli import (Jira URL / email / token keys)"

    def detect(self, ctx: Context) -> dict:
        cfg_path = C.get(ctx.cfg, "pncli.config_path") or DEFAULT_PNCLI_CONFIG
        launcher = ctx.det.launcher("pncli", C.get(ctx.cfg, "pncli.exe") or None)
        found: dict = {"launcher": launcher, "bin": launcher.get("path") or None, "config_path": cfg_path,
                       "exists": ctx.det.exists(cfg_path), "flat": {}, "json_error": None,
                       "keys": dict(C.get(ctx.cfg, "pncli.keys", {}) or {})}
        if found["exists"]:
            try:
                found["flat"] = C.flatten(ctx.det.read_json(cfg_path))
            except Exception as e:  # noqa: BLE001
                found["json_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        found["proposal"] = propose(found["flat"])
        return found

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        lz = found.get("launcher") or {}
        pkg = C.get(ctx.cfg, "pncli.npm_package") or NPM_PACKAGE
        hint = (f"pncli is an npm package: `npm install -g {pkg}` installs it as pncli.cmd (there is no pncli.exe), "
                "or pin its path with PNCLI_EXE / ad-setup --only pncli. `ad-pncli where` shows what was tried.")
        if not lz.get("found"):
            ctx.add(k, "pncli launcher", "fail", lz.get("error") or "pncli not found on PATH, PATHEXT or the npm global prefix", hint)
        elif lz.get("rc") not in (0, None):
            ctx.add(k, "pncli launcher", "fail", f"{lz['path']} ({lz.get('kind')}) exits {lz.get('rc')} on --version", hint)
        else:
            detail = f"{lz['path']} ({lz.get('kind')})" + (f" · {lz['version']}" if lz.get("version") else "")
            ctx.add(k, "pncli launcher", "ok", detail + (f" · node {lz['node']}" if lz.get("node") else ""))
        p = C.display_path(C.expand(found["config_path"]))
        if not found["exists"]:
            ctx.add(k, "pncli config", "fail", f"missing {p}", "run `pncli config init`, then `ad-setup --only pncli`")
            return
        if found["json_error"]:
            ctx.add(k, "pncli config", "fail", f"{p}: {found['json_error']}", "pncli config must be JSON; fix it, then ad-setup --only pncli")
            return
        ctx.add(k, "pncli config", "ok", f"{p} ({len(found['flat'])} keys)")
        keys = found["keys"]
        if not keys.get("jira_token"):
            ctx.add(k, "jira token key", "fail", "no token key chosen", "ad-setup --only pncli")
            return
        for name in ("jira_url", "jira_email", "jira_token"):
            kp = keys.get(name)
            if not kp:
                ctx.add(k, name, "warn" if name == "jira_email" else "fail", "not configured", "ad-setup --only pncli")
            elif found["flat"].get(kp) not in (None, ""):
                ctx.add(k, name, "ok", f"key {kp}")
            else:
                ctx.add(k, name, "fail", f"key {kp} missing or empty in pncli config", "ad-setup --only pncli")
        v = C.get(ctx.cfg, "verified.jira")
        if v:
            ctx.add(k, "jira auth", "ok", f"verified {v} · {C.get(ctx.cfg, 'jira.flavor')}/{C.get(ctx.cfg, 'jira.auth')} v{C.get(ctx.cfg, 'jira.api')}")
        else:
            ctx.add(k, "jira auth", "warn", "token never verified", "ad-setup --only pncli (online) or ad-doctor --online")

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        path = ctx.ask.ask("pncli.config_path", "pncli config file", found["config_path"]) or found["config_path"]
        if path != found["config_path"]:
            C.put(cfg, "pncli.config_path", path)
            found = self.detect(ctx)
        if not found["exists"]:
            ctx.add(self.key, "pncli config", "fail", f"missing {C.display_path(C.expand(path))}",
                    "run `pncli config init`, then `ad-setup --only pncli`")
            return
        if found["json_error"]:
            ctx.add(self.key, "pncli config", "fail", found["json_error"], "pncli config must be JSON")
            return
        flat = found["flat"]
        ctx.say("  keys found (values masked where they look secret):")
        for kp in sorted(flat):
            shown = C.mask(flat[kp]) if C.looks_secret(kp) else str(flat[kp])[:60]
            ctx.say(f"    {kp} = {shown}")
        prop, keys = found["proposal"], found["keys"]
        chosen: dict[str, str | None] = {}
        labels = (("jira_url", "key holding the Jira base URL"),
                  ("jira_email", "key holding your Jira email / username (blank = none)"),
                  ("jira_token", "key holding the Jira API token / PAT"))
        for name, label in labels:
            ans = ctx.ask.ask(f"pncli.{name}_key", label, keys.get(name) or prop.get(name) or "")
            if ans and ans not in flat:
                ctx.add(self.key, name, "fail", f"{ans} is not a key in the pncli config", "ad-setup --only pncli and pick an existing key")
            chosen[name] = ans or None
        C.put(cfg, "pncli.config_path", path)
        C.put(cfg, "pncli.keys", {k: v for k, v in chosen.items() if v})
        lz = found.get("launcher") or {}
        if lz.get("found") and lz.get("kind") != "executable":
            C.put(cfg, "pncli.exe", lz["path"])      # pin the shim we proved starts, so PATH changes cannot break it
        url = flat.get(chosen["jira_url"]) if chosen["jira_url"] else None
        if isinstance(url, str) and url and not C.looks_secret(chosen["jira_url"] or ""):
            C.put(cfg, "jira.base_url", url.rstrip("/"))
        if not chosen["jira_token"]:
            ctx.add(self.key, "jira token key", "fail", "no token key chosen", "ad-setup --only pncli")
        else:
            ctx.add(self.key, "pncli import", "ok", "keys: " + ", ".join(f"{k}={v}" for k, v in chosen.items() if v))

    def verify(self, ctx: Context) -> None:
        if not C.get(ctx.cfg, "pncli.keys.jira_token") and not ctx.det.env("JIRA_TOKEN"):
            ctx.add(self.key, "jira auth", "skip", "no token key configured")
            return
        try:
            info = ctx.det.jira_whoami(ctx.cfg, redetect=True)
        except Exception as e:  # noqa: BLE001 - JiraError or network
            ctx.add(self.key, "jira auth", "fail", f"{type(e).__name__}: {str(e)[:160]}",
                    getattr(e, "hint", "") or "check VPN/proxy; ad-setup --only pncli")
            return
        who = info.get("display_name") or info.get("account") or "?"
        ctx.add(self.key, "jira auth", "ok", f"{info['flavor']}/{info['auth']} v{info['api']} as {who} ({info['token_source']})")
