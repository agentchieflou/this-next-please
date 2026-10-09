"""Step: Jira over REST -- base URL, email, and the API token in the keyring.

Every `ad-jira` verb reads its credentials at call time in one order (`connectors/jira_api.load_credentials`):
env (`JIRA_URL` / `JIRA_EMAIL` / `JIRA_TOKEN`), then this step's answers (`jira.base_url`, `jira.email`, the
token in the keyring under `jira:default`), then pncli's own config by key name (the optional backend, step
`pncli`). This step is the one that needs nothing installed: a Jira API token and a terminal.

Nothing secret goes to config. The token lands in the keyring, the same place and the same shape as a data
source's password; `config.assert_no_secrets` refuses it anywhere else.
"""
from __future__ import annotations

from ... import config as C
from ...connectors import jira_api as J
from ..wizard import Context, Step

DEFAULT_PNCLI_CONFIG = "~/.pncli/config.json"


def credentials(ctx: Context) -> dict:
    """Where the URL, the email and the token would come from, without sending anything.

    `token_source` is `env`, `keyring`, `pncli:<key>` or `""`; the pncli answer is read from the file the way
    the connector reads it, so a key chosen in step `pncli` that no longer exists in the file reads as none.
    """
    cfg, det = ctx.cfg, ctx.det
    found = {"url": det.env("JIRA_URL") or C.get(cfg, "jira.base_url") or "",
             "url_source": "env" if det.env("JIRA_URL") else ("config" if C.get(cfg, "jira.base_url") else ""),
             "email": det.env("JIRA_EMAIL") or C.get(cfg, "jira.email") or "",
             "email_source": "env" if det.env("JIRA_EMAIL") else ("config" if C.get(cfg, "jira.email") else ""),
             "token_source": "", "keyring": det.has_password(J.SECRET_SOURCE, J.SECRET_ENV, J.SECRET_USER)}
    if any(det.env(n) for n in J.TOKEN_ENVS):
        found["token_source"] = "env"
    elif found["keyring"]:
        found["token_source"] = "keyring"
    else:
        keys = C.get(cfg, "pncli.keys", {}) or {}
        path = C.get(cfg, "pncli.config_path") or DEFAULT_PNCLI_CONFIG
        tk = keys.get("jira_token")
        if tk and det.exists(path):
            try:
                flat = C.flatten(det.read_json(path))
            except Exception:  # noqa: BLE001 - a broken file is step pncli's row to report
                flat = {}
            if flat.get(tk) not in (None, ""):
                found["token_source"] = f"pncli:{tk}"
                if not found["url"] and keys.get("jira_url") and flat.get(keys["jira_url"]):
                    found["url"], found["url_source"] = str(flat[keys["jira_url"]]), "pncli"
                if not found["email"] and keys.get("jira_email") and flat.get(keys["jira_email"]):
                    found["email"], found["email_source"] = str(flat[keys["jira_email"]]), "pncli"
    return found


def has_credentials(ctx: Context) -> bool:
    f = credentials(ctx)
    return bool(f["token_source"] and f["url"])


class JiraStep(Step):
    key = "jira"
    title = "Jira (REST: base URL, email, API token in the keyring)"

    def detect(self, ctx: Context) -> dict:
        return credentials(ctx)

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        if found["url"]:
            ctx.add(k, "jira url", "ok", f"{found['url']} ({found['url_source']})")
        else:
            ctx.add(k, "jira url", "fail", "no Jira base URL", "ad-setup --only jira, or set JIRA_URL", ("jira.base_url",))
        if found["email"]:
            ctx.add(k, "jira email", "ok", f"{found['email']} ({found['email_source']})")
        else:
            ctx.add(k, "jira email", "warn", "no email: Cloud Basic auth needs one, a Data Center PAT does not",
                    "ad-setup --only jira, or set JIRA_EMAIL", ("jira.email",))
        src = found["token_source"]
        if src:
            where = {"env": "JIRA_TOKEN", "keyring": f"keyring {J.SECRET_SOURCE}:{J.SECRET_ENV}"}.get(src, src)
            ctx.add(k, "jira token", "ok", where)
        else:
            ctx.add(k, "jira token", "fail", "no token: not in JIRA_TOKEN, not in the keyring, no pncli key",
                    "ad-setup --only jira stores one in the keyring (a token prompt needs a human at a real "
                    "terminal); or set JIRA_TOKEN; or, with pncli installed, ad-setup --only pncli", ("jira.token",))
        v = C.get(ctx.cfg, "verified.jira")
        if v:
            fl = C.get(ctx.cfg, "jira.flavor")
            ctx.add(k, "jira auth", "ok", f"verified {v}" + (f" · {fl}/{C.get(ctx.cfg, 'jira.auth')} v{C.get(ctx.cfg, 'jira.api')}" if fl else ""))
        elif src:
            ctx.add(k, "jira auth", "warn", "token never verified", "ad-setup --only jira (online) or ad-doctor --online",
                    ("jira.token",))
        else:
            ctx.add(k, "jira auth", "skip", "nothing to verify without a token")

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        url = ctx.ask.ask("jira.base_url", "Jira base URL (https://<site>.atlassian.net, or your Data Center host)",
                          found["url"], confident=bool(found["url"]))
        if url:
            url = url.strip()
            if not url.startswith("http"):
                url = "https://" + url
            C.put(cfg, "jira.base_url", url.rstrip("/"))
        email_ = ctx.ask.ask("jira.email", "Jira email / username (blank for a Data Center PAT)", found["email"],
                             confident=bool(found["email"]))
        if email_:
            C.put(cfg, "jira.email", email_.strip())
        elif C.get(cfg, "jira.email"):
            (C.get(cfg, "jira") or {}).pop("email", None)
        src = found["token_source"]
        if src == "env":
            ctx.add(self.key, "jira token", "ok", "JIRA_TOKEN is set for this session; nothing stored")
            return
        if src == "keyring" and ctx.ask.confirm("jira.keep_token", "keep the API token already in the keyring?", True,
                                                confident=True):
            return
        if not ctx.interactive:
            if not src:
                ctx.add(self.key, "jira token", "warn", "no token stored and none can be stored non-interactively",
                        "run interactive `ad-setup --only jira` once, or set JIRA_TOKEN")
            return
        label = "Jira API token / PAT (stored in keyring only" + ("; blank keeps using pncli's)" if src.startswith("pncli") else ")")
        token = ctx.ask.ask("jira.token", label, secret=True)
        if token:
            try:
                ctx.det.set_password(J.SECRET_SOURCE, J.SECRET_ENV, J.SECRET_USER, token.strip())
                C.get(cfg, "verified", {}).pop("jira", None)   # a new token is unverified until /myself says otherwise
            except C.ConfigError as e:
                # a broken keyring backend must not throw away the URL and email just given
                ctx.add(self.key, "jira token", "warn", str(e), e.hint)

    def verify(self, ctx: Context) -> None:
        """Online only: `/myself` through the same path every `ad-jira` verb takes, and the flavor is remembered."""
        if not ctx.online:
            return
        if not has_credentials(ctx):
            ctx.add(self.key, "jira auth", "skip", "no token to verify")
            return
        try:
            info = ctx.det.jira_whoami(ctx.cfg, redetect=True)
        except Exception as e:  # noqa: BLE001 - JiraError or network
            ctx.add(self.key, "jira auth", "fail", f"{type(e).__name__}: {str(e)[:160]}",
                    getattr(e, "hint", "") or "check VPN/proxy; ad-setup --patch", ("jira.token", "jira.base_url"))
            return
        who = info.get("display_name") or info.get("account") or "?"
        ctx.add(self.key, "jira auth", "ok", f"{info['flavor']}/{info['auth']} v{info['api']} as {who} ({info['token_source']})")
