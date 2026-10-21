"""Step: the Jira credential fallback -- base URL, email, and the API token in the keyring -- and `jira auth`.

Every `ad-jira` verb finds its credentials at call time in one order (`connectors/jira_api.load_credentials`):
env (`JIRA_URL` / `JIRA_EMAIL` / `JIRA_TOKEN`), then toil's Jira connection (the default, step `toil`, which runs
first; requests then go through `toil jira api` and the token never leaves toil), then this step's answers
(`jira.base_url`, `jira.email`, the token in the keyring under `jira:default`). When toil answers this step stores
nothing: its url, email and token rows are `info` (hidden by `ad-doctor --quiet`). It is the fallback for a machine
without toil, and it owns the `jira auth` row whichever source answered.

Nothing secret goes to config. The token lands in the keyring, the same place and the same shape as a data
source's password; `config.assert_no_secrets` refuses it anywhere else.
"""
from __future__ import annotations

from ... import config as C
from ...connectors import jira_api as J
from ..wizard import Context, Step



def credentials(ctx: Context) -> dict:
    """Where the URL, the email and the token would come from, without sending anything.

    `token_source` is `env`, `toil:<connection>`, `keyring` or `""`, in the connector's order; the toil answer is
    the connection the connector would pick from `toil connections list` (`toil.connection_for`).
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
        from ...connectors import toil as T
        conns = (det.toil(cfg) or {}).get("connections") or []
        c = next((x for x in (T.connection_for(a, conns, cfg) for a in J.TOIL_AREAS) if x), None)
        if c:
            found["token_source"] = f"toil:{c.get('name')}"
            found["url"], found["url_source"] = str(c.get("host") or c.get("name") or ""), "toil"
            found["area"] = str(c.get("area") or "")
        if not found["token_source"] and found["keyring"]:
            found["token_source"] = "keyring"
    return found


def has_credentials(ctx: Context) -> bool:
    f = credentials(ctx)
    return bool(f["token_source"] and f["url"])


class JiraStep(Step):
    key = "jira"
    title = "Jira (the fallback without toil: base URL, email, API token in the keyring)"

    def detect(self, ctx: Context) -> dict:
        return credentials(ctx)

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        src = found["token_source"]
        if src.startswith("toil:"):
            ctx.add(k, "jira url", "info", f"toil's connection {src[5:]}: {found['url']} ({found.get('area')})")
            ctx.add(k, "jira token", "info", f"in toil's credential store ({src[5:]}); nothing stored here")
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
            ctx.add(k, "jira token", "fail", "no token: not in JIRA_TOKEN, no Jira connection in toil, not in the keyring",
                    "set up toil's Jira connection (`toil connections add <name> --area jira`, then ad-setup --only "
                    "toil); or set JIRA_TOKEN; or, on a machine without toil, ad-setup --only jira stores one in the "
                    "keyring (a token prompt needs a human at a real terminal)", ("jira.token",))
        self._auth_row(ctx, src)

    def _auth_row(self, ctx: Context, src: str) -> None:
        k = self.key
        v = C.get(ctx.cfg, "verified.jira")
        if v:
            fl = C.get(ctx.cfg, "jira.flavor")
            ctx.add(k, "jira auth", "ok", f"verified {v}" + (f" · {fl}/{C.get(ctx.cfg, 'jira.auth')} v{C.get(ctx.cfg, 'jira.api')}" if fl else ""))
        elif src:
            ctx.add(k, "jira auth", "warn", "token never verified", "ad-doctor --online (or ad-setup --only toil,jira)",
                    ("jira.token",))
        else:
            ctx.add(k, "jira auth", "skip", "nothing to verify without a token")

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if found["token_source"].startswith("toil:"):
            ctx.add(self.key, "jira token", "info", f"toil's connection {found['token_source'][5:]}; nothing stored")
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
