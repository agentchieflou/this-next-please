"""Step: the Jira credential fallback -- base URL, email, and the API token in the keyring -- and `jira auth`.

Every `ad-jira` verb reads its credentials at call time in one order (`connectors/jira_api.load_credentials`):
env (`JIRA_URL` / `JIRA_EMAIL` / `JIRA_TOKEN`), then pncli's own config by key name (the default, step `pncli`,
which runs first), then this step's answers (`jira.base_url`, `jira.email`, the token in the keyring under
`jira:default`). When pncli supplies the token this step stores nothing: its url, email and token rows are `info` (hidden by `ad-doctor --quiet`).
It is the fallback for a machine without pncli, and it owns the `jira auth` row whichever source answered.

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

    `token_source` is `env`, `pncli:<key>`, `keyring` or `""`, in the connector's order; the pncli answer is read
    from the file the way the connector reads it, so a key chosen in step `pncli` that no longer exists in the file
    reads as none.
    """
    cfg, det = ctx.cfg, ctx.det
    found = {"url": det.env("JIRA_URL") or C.get(cfg, "jira.base_url") or "",
             "url_source": "env" if det.env("JIRA_URL") else ("config" if C.get(cfg, "jira.base_url") else ""),
             "email": det.env("JIRA_EMAIL") or C.get(cfg, "jira.email") or "",
             "email_source": "env" if det.env("JIRA_EMAIL") else ("config" if C.get(cfg, "jira.email") else ""),
             "token_source": "", "keyring": det.has_password(J.SECRET_SOURCE, J.SECRET_ENV, J.SECRET_USER)}
    if any(det.env(n) for n in J.TOKEN_ENVS):
        found["token_source"] = "env"
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
        if not found["token_source"] and found["keyring"]:
            found["token_source"] = "keyring"
    return found


def has_credentials(ctx: Context) -> bool:
    f = credentials(ctx)
    return bool(f["token_source"] and f["url"])


class JiraStep(Step):
    key = "jira"
    title = "Jira (the fallback without pncli: base URL, email, API token in the keyring)"

    def detect(self, ctx: Context) -> dict:
        return credentials(ctx)

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        src = found["token_source"]
        if src.startswith("pncli:"):
            if not found["url"]:
                ctx.add(k, "jira url", "fail", "no Jira base URL: pncli's config has a token but no URL key was chosen",
                        "ad-setup --only pncli (choose the URL key), or set JIRA_URL", ("pncli.jira_url_key",))
            else:
                ctx.add(k, "jira url", "info", f"from pncli's config: {found['url']} ({found['url_source']})")
            ctx.add(k, "jira email", "info", f"from pncli's config: {found['email']} ({found['email_source']})"
                    if found["email"] else "from pncli's config: no email (a Data Center PAT needs none)")
            ctx.add(k, "jira token", "info", f"from pncli's config: key {src[6:]}")
            self._auth_row(ctx, src)
            return
        if found["url"]:
            ctx.add(k, "jira url", "ok", f"{found['url']} ({found['url_source']})")
        else:
            ctx.add(k, "jira url", "fail", "no Jira base URL", "ad-setup --only jira, or set JIRA_URL", ("jira.base_url",))
        if found["email"]:
            ctx.add(k, "jira email", "ok", f"{found['email']} ({found['email_source']})")
        else:
            ctx.add(k, "jira email", "warn", "no email: Cloud Basic auth needs one, a Data Center PAT does not",
                    "ad-setup --only jira, or set JIRA_EMAIL", ("jira.email",))
        if src:
            where = {"env": "JIRA_TOKEN", "keyring": f"keyring {J.SECRET_SOURCE}:{J.SECRET_ENV}"}.get(src, src)
            ctx.add(k, "jira token", "ok", where)
        else:
            ctx.add(k, "jira token", "fail", "no token: not in JIRA_TOKEN, no pncli key, not in the keyring",
                    "ad-setup --only pncli borrows it from pncli's config (`pncli config init` writes it); or set "
                    "JIRA_TOKEN; or, on a machine without pncli, ad-setup --only jira stores one in the keyring "
                    "(a token prompt needs a human at a real terminal)", ("jira.token",))
        self._auth_row(ctx, src)

    def _auth_row(self, ctx: Context, src: str) -> None:
        k = self.key
        v = C.get(ctx.cfg, "verified.jira")
        if v:
            fl = C.get(ctx.cfg, "jira.flavor")
            ctx.add(k, "jira auth", "ok", f"verified {v}" + (f" · {fl}/{C.get(ctx.cfg, 'jira.auth')} v{C.get(ctx.cfg, 'jira.api')}" if fl else ""))
        elif src:
            ctx.add(k, "jira auth", "warn", "token never verified", "ad-doctor --online (or ad-setup --only pncli,jira)",
                    ("jira.token",))
        else:
            ctx.add(k, "jira auth", "skip", "nothing to verify without a token")

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if found["token_source"].startswith("pncli:"):
            ctx.add(self.key, "jira token", "info", f"from pncli's config ({found['token_source'][6:]}); nothing stored")
            return
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
        label = "Jira API token / PAT (stored in keyring only)"
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
