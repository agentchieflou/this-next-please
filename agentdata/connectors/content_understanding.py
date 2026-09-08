"""Azure AI Content Understanding: schema-driven field extraction from documents.

A Microsoft Foundry service that runs a server-side *analyzer* -- a field schema defined in the
portal or through the SDK's management calls -- over a document and returns each field with a
value, a confidence and a span back into the content. Mechanically the same shape `ad-dpm
extract-fields` already produces, which is why it plugs into that command's engine seam rather
than growing a second output format.

**Naming.** Microsoft is mid-rebrand from "Azure AI Foundry" to "Microsoft Foundry"; the SDK
distribution is `azure-ai-contentunderstanding` and the portal may say either. Both names refer to
the same resource here, and neither is a typo.

**The SDK, checked rather than assumed.** Written against `azure-ai-contentunderstanding` 1.1.0 as
actually published:

    ContentUnderstandingClient(endpoint, credential)      credential: AzureKeyCredential | TokenCredential
    .begin_analyze(analyzer_id, inputs=[AnalysisInput(url=...)], string_encoding=...)   -> poller
    .begin_analyze_binary(analyzer_id, binary_input=b"...", string_encoding=...)        -> poller
    .get_analyzer(analyzer_id) / .list_analyzers()

Two keywords are **required** and neither is documented as such: `string_encoding` on both analyze
calls, and `content_type` on `begin_analyze_binary` -- the operation does `kwargs.pop("content_type")`
with no default, so omitting it raises `KeyError` rather than sending a sensible header. That is the
kind of detail that is invisible until the first real request fails, and the reason this module was
written against the published package rather than from the REST documentation alone.

**Normalisation is separate from the SDK on purpose.** `fields_from_result` takes the plain JSON
shape the service returns, which is what the SDK deserialises and what a recorded fixture holds. So
the mapping -- the part with the decisions in it -- is testable without Azure, without credentials
and without the optional dependency installed.
"""
from __future__ import annotations
import os
from typing import Any

from .. import config as C

# The api-version this module's shapes were read against. Recorded so a future failure can be
# compared with something rather than guessed at.
API_VERSION = "2025-11-01"
SDK_DIST = "azure-ai-contentunderstanding"
EXTRA = "content-understanding"

# `codePoint` is the service default and the only one whose spans line up with Python string
# indices. `utf16` would be right for a .NET caller and wrong for every offset used here.
STRING_ENCODING = "codePoint"

# What `content_type` falls back to. The service sniffs the bytes when the header says nothing more
# specific, which is better than asserting a type this end guessed wrong.
OCTET_STREAM = "application/octet-stream"
TEXT_PLAIN = "text/plain"

DEFAULT_TIMEOUT_S = 300


class ContentUnderstandingError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# ------------------------------------------------------------------------------- settings


def settings(cfg: dict | None = None, *, endpoint: str | None = None,
             analyzer: str | None = None) -> dict:
    """Endpoint, auth mode and default analyzer, through the standard precedence.

    Flag, then environment, then config, then AGENTS.md -- the same order every other connector
    resolves, so a project fact and a laptop override behave the way they do everywhere else.

    A pure read: every setting defaults to empty rather than raising, so a caller that only wanted
    the auth mode does not fail over a missing endpoint. The refusals live where the setting is
    actually needed -- `client()` for the endpoint -- because that is where the message can say
    what the caller was trying to do.
    """
    cfg = C.load() if cfg is None else cfg
    facts = C.project_facts()
    resolved = {
        "endpoint": str(C.resolve("content_understanding_endpoint", flag=endpoint,
                                  env="CONTENT_UNDERSTANDING_ENDPOINT", cfg=cfg,
                                  cfg_path="content_understanding.endpoint", facts=facts,
                                  default="")).rstrip("/"),
        "analyzer": str(C.resolve("content_understanding_analyzer", flag=analyzer,
                                  env="CONTENT_UNDERSTANDING_ANALYZER", cfg=cfg,
                                  cfg_path="content_understanding.analyzer", facts=facts,
                                  default="")),
        "auth": str(C.get(cfg, "content_understanding.auth")
                    or facts.get("content_understanding_auth") or "entra"),
    }
    return resolved


SECRET_SOURCE = "content_understanding"
SECRET_ENV = "default"
SECRET_USER = "resource-key"


def _key(cfg: dict | None = None) -> str:
    """The resource key, from the keyring, keyed the way every other credential here is.

    Never from config: `config.assert_no_secrets` refuses to store one, and this is that same rule
    seen from the other side. The environment variable is the one-session escape hatch the other
    connectors also offer.
    """
    from . import secrets

    return (os.environ.get("CONTENT_UNDERSTANDING_KEY")
            or secrets.get_password(SECRET_SOURCE, SECRET_ENV, SECRET_USER) or "")


def credential(cfg: dict | None = None):
    """An `AzureKeyCredential` or an Entra token credential.

    Entra is the default because it is what the Power BI step already uses on this laptop -- the
    same `az`-backed identity, so an operator who can reach a workspace can reach this without a
    second secret to rotate.
    """
    s = settings(cfg)
    if s["auth"] == "key":
        key = _key(cfg)
        if not key:
            raise ContentUnderstandingError(
                "no Content Understanding key is stored",
                "`ad-setup --only content_understanding` stores it in the keyring, or set "
                "CONTENT_UNDERSTANDING_KEY for one session")
        try:
            from azure.core.credentials import AzureKeyCredential
        except ImportError:
            raise _not_installed() from None
        return AzureKeyCredential(key)

    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        raise ContentUnderstandingError(
            "Entra ID auth needs `azure-identity`",
            f'pip install "agentdata[{EXTRA}]", then `az login` if you are not already signed in'
        ) from None
    return DefaultAzureCredential()


def _not_installed() -> ContentUnderstandingError:
    return ContentUnderstandingError(
        f"the {SDK_DIST} SDK is not installed",
        f'pip install "agentdata[{EXTRA}]" -- it is an optional extra, like teradata and oracle, '
        f"because most installs never call this service")


def client(cfg: dict | None = None, *, endpoint: str | None = None):
    """A `ContentUnderstandingClient`. Import is deferred so the package stays optional."""
    s = settings(cfg, endpoint=endpoint)
    if not s["endpoint"]:
        raise ContentUnderstandingError(
            "no Content Understanding endpoint is configured",
            "add `content_understanding_endpoint:` to AGENTS.md, or run "
            "`ad-setup --only content_understanding`")
    try:
        from azure.ai.contentunderstanding import ContentUnderstandingClient
    except ImportError:
        raise _not_installed() from None
    return ContentUnderstandingClient(endpoint=s["endpoint"], credential=credential(cfg))


# ------------------------------------------------------------------------------- the calls


def guess_mime(path: str) -> str:
    """The document's MIME type, or the generic one. `begin_analyze_binary` demands a content type
    and the service uses it to pick a parser, so a wrong guess reads as an unsupported document
    rather than as a bad header."""
    import mimetypes

    return mimetypes.guess_type(path)[0] or OCTET_STREAM


def analyze(*, analyzer: str, path: str | None = None, url: str | None = None,
            data: bytes | None = None, mime_type: str = "",
            cfg: dict | None = None, timeout: int = DEFAULT_TIMEOUT_S, sdk=None) -> dict:
    """Run an analyzer over one document and return the raw result as a plain dict.

    Exactly one of `path`, `url` or `data`. `data` is how the DPM engine sends text a run has
    already extracted, so a document is fetched from disk once by the converter rather than twice.

    `sdk` is injectable so the tests exercise this without the package, without credentials and
    without a network -- what is worth testing here is the argument shape and the normalisation,
    and neither needs Azure.
    """
    given = [name for name, value in (("path", path), ("url", url), ("data", data)) if value]
    if len(given) != 1:
        raise ContentUnderstandingError(
            f"give exactly one of a file path, a URL or bytes (got {len(given)})",
            "--file <path> for a local document, --url for one the service can fetch")
    service = sdk or client(cfg)
    try:
        if url:
            from azure.ai.contentunderstanding.models import AnalysisInput

            poller = service.begin_analyze(analyzer, inputs=[AnalysisInput(url=url)],
                                           string_encoding=STRING_ENCODING)
        else:
            if path:
                with open(path, "rb") as f:
                    data = f.read()
                mime_type = mime_type or guess_mime(path)
            poller = service.begin_analyze_binary(analyzer, binary_input=data,
                                                  string_encoding=STRING_ENCODING,
                                                  content_type=mime_type or OCTET_STREAM)
    except ContentUnderstandingError:
        raise
    except ImportError:
        raise _not_installed() from None
    except Exception as e:                       # noqa: BLE001 - the service's own words are the hint
        raise ContentUnderstandingError(f"the analyze call failed: {str(e)[:200]}",
                                        "`ad-foundry analyzers get <id>` checks the analyzer "
                                        "exists and the credential reaches it") from None

    try:
        result = poller.result(timeout=timeout) if _takes_timeout(poller) else poller.result()
    except Exception as e:                       # noqa: BLE001
        raise ContentUnderstandingError(f"the analysis did not finish: {str(e)[:200]}",
                                        "large documents take minutes; raise --timeout") from None
    return as_dict(result)


def _takes_timeout(poller) -> bool:
    import inspect

    try:
        return "timeout" in inspect.signature(poller.result).parameters
    except (TypeError, ValueError):
        return False


def as_dict(result: Any) -> dict:
    """The SDK's models are mappings; a recorded fixture is already one. Both end up here."""
    if isinstance(result, dict):
        return result
    for method in ("as_dict", "to_dict"):
        if hasattr(result, method):
            return getattr(result, method)()
    try:
        return dict(result)
    except (TypeError, ValueError):
        raise ContentUnderstandingError("the SDK returned a result this build cannot read",
                                        f"written against {SDK_DIST} 1.1.0; check the installed "
                                        f"version") from None


def list_analyzers(cfg: dict | None = None, *, sdk=None) -> list[dict]:
    service = sdk or client(cfg)
    try:
        return [as_dict(a) for a in service.list_analyzers()]
    except Exception as e:                       # noqa: BLE001
        raise ContentUnderstandingError(f"cannot list analyzers: {str(e)[:200]}",
                                        "check the endpoint and that the credential has "
                                        "Cognitive Services access on the resource") from None


def get_analyzer(analyzer_id: str, cfg: dict | None = None, *, sdk=None) -> dict:
    service = sdk or client(cfg)
    try:
        return as_dict(service.get_analyzer(analyzer_id))
    except Exception as e:                       # noqa: BLE001
        raise ContentUnderstandingError(f"cannot read analyzer {analyzer_id!r}: {str(e)[:200]}",
                                        "`ad-foundry analyzers list` shows what exists") from None


# ------------------------------------------------------------------------- the normalisation


# What the service calls a value, per field type: `valueString`, `valueNumber`, and so on. Read by
# prefix rather than by an exhaustive list, so a field type added later still yields its value
# instead of silently reading as empty.
VALUE_PREFIX = "value"


def field_value(field: dict) -> Any:
    """The value out of one `ContentField`, whatever its type."""
    if not isinstance(field, dict):
        return None
    for key, value in field.items():
        if key.startswith(VALUE_PREFIX) and key != VALUE_PREFIX and value is not None:
            return value
    return field.get(VALUE_PREFIX)


def fields_from_result(result: dict) -> list[dict]:
    """One row per extracted field: name, value, confidence, and where it came from.

    Flat on purpose. The service nests fields under each content item, and a caller comparing
    documents wants rows -- the same shape `ad-dpm extract-fields` emits, so an engine built on
    this needs no second mapping.
    """
    rows = []
    for index, content in enumerate(result.get("contents") or []):
        if not isinstance(content, dict):
            continue
        fields = content.get("fields") or {}
        for name, field in sorted(fields.items()):
            if not isinstance(field, dict):
                continue
            spans = field.get("spans") or []
            rows.append({
                "field": name,
                "value": field_value(field),
                "type": field.get("type", ""),
                "confidence": field.get("confidence"),
                "content_index": index,
                "content_path": content.get("path") or "",
                "mime_type": content.get("mimeType") or content.get("mime_type") or "",
                "offset": (spans[0] or {}).get("offset") if spans else None,
                "length": (spans[0] or {}).get("length") if spans else None,
            })
    return rows


def _message(warning: Any) -> str:
    """One warning's text, whatever shape it arrived in.

    `AnalysisResult.warnings` is typed `list[ODataV4Format]`, which is an object rather than a
    mapping -- so a warning is the one field here that can arrive as something `.get` does not
    work on. Warnings are rare, diagnostic, and never worth crashing a run that otherwise
    succeeded, so this reads whichever shape turned up and gives up quietly.
    """
    if isinstance(warning, dict):
        return str(warning.get("message") or warning.get("code") or "")
    return str(getattr(warning, "message", "") or getattr(warning, "code", "") or "")


def result_meta(result: dict) -> dict:
    warnings = result.get("warnings") or []
    return {"analyzer": result.get("analyzerId") or result.get("analyzer_id") or "",
            "api_version": result.get("apiVersion") or result.get("api_version") or "",
            "contents": len(result.get("contents") or []),
            "warnings": len(warnings),
            "warning": _message(warnings[0]) if warnings else ""}
