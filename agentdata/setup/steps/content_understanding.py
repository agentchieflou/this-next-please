"""Step: Microsoft Foundry / Azure AI Content Understanding — endpoint, auth mode, default analyzer.

Only reached by projects that extract fields from documents, so every row here is `skip` until
somebody says the project uses it. That is deliberate: an unconfigured optional service is not a
broken install, and a `fail` row for it would push the rows that matter off a reader's screen.

Nothing secret goes to config. Entra ID (the default) stores nothing at all -- it reuses the `az`
sign-in the Power BI step already needs. Key auth puts the key in the keyring under
`content_understanding:default`, the same place and the same shape as a data source's password.
"""
from __future__ import annotations

from ... import config as C
from ...connectors import content_understanding as CU
from ..wizard import Context, Step

AUTH = ["entra", "key"]
# The two shapes Azure hands out for this resource. Checked as a suffix, not matched exactly: the
# region and resource name vary, and a `.cognitiveservices.` endpoint is the older but still valid
# form for a resource created before the Foundry rename.
ENDPOINT_HOSTS = (".services.ai.azure.com", ".cognitiveservices.azure.com", ".openai.azure.com")


def endpoint_trouble(endpoint: str) -> str:
    """Why this endpoint will not work, in a sentence, or "" if nothing is obviously wrong.

    A shape check, not a reachability check: `ad-doctor` is offline, and the failure this catches
    -- a portal *key* pasted where the endpoint goes, or a URL with the API path already on it --
    is the one that produces an authentication error rather than a URL error.
    """
    if not endpoint.startswith("https://"):
        return "not an https:// URL"
    host = endpoint.split("//", 1)[1].split("/", 1)[0].lower()
    if not any(host.endswith(suffix) for suffix in ENDPOINT_HOSTS):
        return f"host {host} is not an Azure AI endpoint"
    if endpoint.rstrip("/").count("/") > 2:
        return "it has a path: the SDK appends its own, so the endpoint stops at the host"
    return ""


class ContentUnderstandingStep(Step):
    key = "content_understanding"
    title = "Content Understanding (Microsoft Foundry document field extraction)"

    def detect(self, ctx: Context) -> dict:
        cfg = ctx.cfg
        return {"use": bool(C.get(cfg, "content_understanding.use")),
                "endpoint": str(C.get(cfg, "content_understanding.endpoint")
                                or ctx.facts.get("content_understanding_endpoint") or ""),
                "analyzer": str(C.get(cfg, "content_understanding.analyzer")
                                or ctx.facts.get("content_understanding_analyzer") or ""),
                "auth": str(C.get(cfg, "content_understanding.auth")
                            or ctx.facts.get("content_understanding_auth") or "entra"),
                "sdk": ctx.det.module("azure.ai.contentunderstanding"),
                "identity": ctx.det.module("azure.identity"),
                "user": ctx.det.getuser()}

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        if not (found["use"] or found["endpoint"]):
            ctx.add(k, "content_understanding", "skip",
                    "not configured (only needed for `ad-dpm extract-fields --engine "
                    "azure-content-understanding`)",
                    "ad-setup --only content_understanding", ("content_understanding.use",))
            return

        endpoint, keys = found["endpoint"], ("content_understanding.endpoint",)
        if not endpoint:
            ctx.add(k, "endpoint", "fail", "in use but no endpoint is configured",
                    "ad-setup --only content_understanding", keys)
        elif endpoint_trouble(endpoint):
            ctx.add(k, "endpoint", "fail", f"{endpoint}: {endpoint_trouble(endpoint)}",
                    "the endpoint is the resource host, e.g. "
                    "https://<resource>.services.ai.azure.com (ad-setup --patch)", keys)
        else:
            ctx.add(k, "endpoint", "ok", endpoint)

        if not found["sdk"]:
            # An install, not an answer: no amount of --patch fixes a missing package.
            ctx.add(k, "sdk", "fail", f"{CU.SDK_DIST} is not installed",
                    f'pip install "agentdata[{CU.EXTRA}]"')
        else:
            ctx.add(k, "sdk", "ok", CU.SDK_DIST)

        auth = found["auth"]
        auth_keys = ("content_understanding.auth",)
        if auth == "key":
            if ctx.det.has_password(CU.SECRET_SOURCE, CU.SECRET_ENV, CU.SECRET_USER):
                ctx.add(k, "auth", "ok", f"key · keyring {CU.SECRET_SOURCE}:{CU.SECRET_ENV}")
            else:
                ctx.add(k, "auth", "fail", "key auth but nothing in the keyring",
                        "ad-setup --patch content_understanding.key -- a key prompt needs a human "
                        "at a real terminal; it cannot be answered non-interactively",
                        auth_keys + ("content_understanding.key",))
        elif not found["identity"]:
            ctx.add(k, "auth", "fail", "Entra ID auth but azure-identity is not installed",
                    f'pip install "agentdata[{CU.EXTRA}]"', auth_keys)
        else:
            ctx.add(k, "auth", "ok", "entra · the same az sign-in Power BI uses")

        analyzer = found["analyzer"]
        if analyzer:
            v = C.get_leaf(ctx.cfg, "verified", f"content_understanding:{analyzer}")
            ctx.add(k, "analyzer", "ok" if v else "warn",
                    f"{analyzer}" + (f" · verified {v}" if v else " · never verified"),
                    "" if v else "ad-doctor --online, or `ad-foundry analyzers get " + analyzer + "`",
                    ("content_understanding.analyzer",))
        else:
            # Not a failure: a project can pick the analyzer per run with `--analyzer`, and a
            # default that is wrong for half the jobs is worse than none.
            ctx.add(k, "analyzer", "warn", "no default analyzer",
                    "set one, or pass --analyzer per run", ("content_understanding.analyzer",))

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if not ctx.ask.confirm("content_understanding.use",
                               "Extract document fields with Azure AI Content Understanding?",
                               bool(found["use"] or found["endpoint"])):
            C.put(cfg, "content_understanding.use", False)
            return
        C.put(cfg, "content_understanding.use", True)

        endpoint = ctx.ask.ask("content_understanding.endpoint",
                               "Foundry resource endpoint (https://<resource>.services.ai.azure.com)",
                               found["endpoint"], confident=bool(found["endpoint"]))
        if endpoint:
            C.put(cfg, "content_understanding.endpoint", endpoint.rstrip("/"))
            trouble = endpoint_trouble(endpoint.rstrip("/"))
            if trouble:
                ctx.add(self.key, "endpoint", "warn", f"{endpoint}: {trouble}",
                        "check it in the portal (ad-setup --patch)",
                        ("content_understanding.endpoint",))

        auth = ctx.ask.ask("content_understanding.auth",
                           "auth: entra (az sign-in, nothing stored) or key", found["auth"], AUTH)
        C.put(cfg, "content_understanding.auth", auth if auth in AUTH else "entra")
        if auth == "key":
            have = ctx.det.has_password(CU.SECRET_SOURCE, CU.SECRET_ENV, CU.SECRET_USER)
            if have and ctx.ask.confirm("content_understanding.keep_key",
                                        "keep the key already in the keyring?", True, confident=True):
                pass
            elif ctx.interactive:
                key = ctx.ask.ask("content_understanding.key",
                                  "resource key (stored in keyring only)", secret=True)
                if key:
                    try:
                        ctx.det.set_password(CU.SECRET_SOURCE, CU.SECRET_ENV, CU.SECRET_USER, key)
                    except C.ConfigError as e:
                        # a broken keyring backend must not throw away the rest of these answers
                        ctx.add(self.key, "auth", "warn", str(e), e.hint)
            else:
                ctx.add(self.key, "auth", "warn", "key auth configured but no keyring entry",
                        "run interactive `ad-setup --only content_understanding` once to store it")

        analyzer = ctx.ask.ask("content_understanding.analyzer",
                               "default analyzer id (blank = pass --analyzer per run)",
                               found["analyzer"], confident=bool(found["analyzer"]))
        if analyzer:
            C.put(cfg, "content_understanding.analyzer", analyzer)
        else:
            (C.get(cfg, "content_understanding") or {}).pop("analyzer", None)

    def verify(self, ctx: Context) -> None:
        """Online only: does the configured analyzer exist, and can this credential read it?

        `get_analyzer` rather than an analysis: it is the cheapest call that proves all four things
        at once -- endpoint, credential, permission, and that the analyzer id is real -- and it
        sends no document anywhere.
        """
        if not ctx.online or not C.get(ctx.cfg, "content_understanding.use"):
            return
        analyzer = str(C.get(ctx.cfg, "content_understanding.analyzer") or "")
        if not analyzer:
            ctx.add(self.key, "analyzer", "skip", "no default analyzer to verify")
            return
        try:
            found = CU.get_analyzer(analyzer, ctx.cfg)
        except CU.ContentUnderstandingError as e:
            ctx.add(self.key, "analyzer", "fail", e.msg, e.hint,
                    ("content_understanding.endpoint", "content_understanding.analyzer"))
            return
        schema = (found.get("fieldSchema") or found.get("field_schema") or {})
        fields = schema.get("fields") or {}
        C.stamp(ctx.cfg, f"content_understanding:{analyzer}")
        ctx.add(self.key, "analyzer", "ok", f"{analyzer} · {len(fields)} field(s) declared")
