"""The bridge's foundations: what the laptop's outbox and inbox on OneDrive stand on (#545, epic #538).

No record is written here. This module holds the settings reader, the folder rule, OneDrive-safe file
names, the canonical JSON every digest is taken over, and the scrubber every free-text field passes
through before it leaves the laptop. The exporter (#546), the applier (#547, #548), the thread (#550)
and the verbs (#552) build on it.

Settings
--------
Five keys, read the way `notify.settings()` reads `fleet.notify.*`:

* `fleet.mobile.enabled` (bool, `false`, read at start): the bridge runs at all.
* `fleet.mobile.folder` (str, no default, read at start): the bridge folder, e.g.
  `%OneDriveCommercial%/FleetAgent`, resolved through `config.expand` at read time.
* `fleet.mobile.operator` (UPN, none, read now): who may decide from the phone.
* `fleet.mobile.expire_s` (int, `900`, clamped to 60-3600, read now): how long a phone decision stays
  valid. A value that is not a number reads as 900 and is flagged `expire_invalid`, as
  `budget_invalid` flags an unreadable budget.
* `fleet.mobile.notify` (bool, `true`, read now): notifications go to the outbox too.

None of them is on the settings page (`settings.EDITABLE`): each moves a human checkpoint (who may
approve from outside the laptop, and where records leave it). `config.json` and `ad-setup` only. None
is a secret, so `config.save` stores them and no keyring entry is needed.

The folder is the one exception to "the fleet writes only under `~/.agentdata/fleet/`" (MOB-D22). It
is never defaulted (a default folder is a folder nobody chose), and it is refused inside any
registered checkout, where the outbox would sit in front of the agent, and under `fleet_dir()`.

What never leaves
-----------------
Records are allow-listed field by field by the exporter. The free text inside them (`says`,
`last_said`, a question, an approval `summary`) is the model's own prose and can quote a hostname, a
table or a row, so `Scrubber` removes, in order: credential shapes (`events.redact()`), every fact
value of every registered project except the `LINK_FACTS`, the desk's run token, every checkout path,
`fleet_dir()`, the home folder, the user and machine names, then UNC and drive-path shapes, and
dotted hostnames other than the hosts of `LINK_FACTS` URLs. `.agent/out/<dir>/<file>` is reduced to
`.agent/out/<file>`: the rows never leave (AGENTS.md rule 5), but the operator still learns which
file an approval sends. A deny-list built from the laptop's own facts first, then generic shapes,
because an allow-list cannot be applied to prose.
"""
from __future__ import annotations
import os
import re
from urllib.parse import urlparse

from .. import config as C
from .. import textio
from .approval import canonical                              # one definition: the bytes #543's digest hashes

__all__ = ["MOBILE_SCHEMA", "MOBILE_CONTRACT", "LIMITS", "BridgeError", "settings", "check_folder",
           "safe_file_name", "canonical", "Scrubber"]

MOBILE_SCHEMA = 1
MOBILE_CONTRACT = 1
TICK_S = 5.0
HEARTBEAT_S = 300
PRUNE_EVERY_S = 600
NAME_MAX = 120
PATH_WARN = 300
INBOX_MAX_BYTES = 16 * 1024

# Field caps of the outbox and inbox records (docs/plan-mobile.md, "The outbox records").
LIMITS = {"repo": 64, "project": 64, "ticket": 32, "says": 300, "last_said": 200, "q": 300, "choice": 80,
          "default": 80, "id": 96, "summary": 300, "reason": 500, "by": 254, "message": 4000, "answer": 1000,
          "title": 120, "body": 300, "preview_bytes": 8192, "preview_head": 2048}

EXPIRE_DEFAULT_S = 900
EXPIRE_MIN_S, EXPIRE_MAX_S = 60, 3600

# OneDrive for Business refuses these on top of Windows' own set.
_ONEDRIVE_EXTRA = "#%"


class BridgeError(Exception):
    """Refused, with a hint and a `code` (the `RegistryError` shape), printed through `_refuse`."""

    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code or "refused"


# ------------------------------------------------------------------------------ settings


def _cfg(cfg: dict | None, key: str, default):
    value = C.get(cfg if cfg is not None else C.load(), f"fleet.mobile.{key}")
    return default if value is None else value


def _flag(cfg: dict | None, key: str, default: bool) -> bool:
    value = _cfg(cfg, key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def settings(cfg: dict | None = None) -> dict:
    """The five `fleet.mobile.*` keys, coerced. `folder` is expanded; it is not checked here."""
    if cfg is None:
        cfg = C.load()
    raw_expire = _cfg(cfg, "expire_s", EXPIRE_DEFAULT_S)
    try:
        expire, invalid = min(EXPIRE_MAX_S, max(EXPIRE_MIN_S, int(raw_expire))), False
    except (TypeError, ValueError):
        expire, invalid = EXPIRE_DEFAULT_S, True
    folder = str(_cfg(cfg, "folder", "") or "").strip()
    return {"enabled": _flag(cfg, "enabled", False),
            "folder": textio.norm_path(C.expand(folder)) if folder else "",
            "operator": str(_cfg(cfg, "operator", "") or "").strip(),
            "expire_s": expire, "expire_invalid": invalid,
            "notify": _flag(cfg, "notify", True)}


# ------------------------------------------------------------------------------ the folder


def _key(path: str) -> str:
    return os.path.normcase(textio.norm_path(os.path.abspath(path))).rstrip("/\\")


def _inside(child: str, parent: str) -> bool:
    c, p = _key(child), _key(parent)
    return bool(p) and (c == p or c.startswith(p + "/") or c.startswith(p + "\\"))


def check_folder(cfg: dict | None = None, registry=None, *, need_enabled: bool = True) -> str:
    """The resolved bridge folder, or a refusal. It creates nothing.

    `need_enabled=False` is for a reader that describes the folder while the bridge is off (the doctor).
    """
    from .registry import Registry, fleet_dir

    s = settings(cfg)
    if need_enabled and not s["enabled"]:
        raise BridgeError("the mobile bridge is off", "set fleet.mobile.enabled to true (ad-setup --patch fleet.mobile)",
                          code="mobile_disabled")
    folder = s["folder"]
    if not folder:
        raise BridgeError("no bridge folder is configured",
                          "set fleet.mobile.folder to a folder OneDrive syncs, e.g. %OneDriveCommercial%/FleetAgent; "
                          "it is never defaulted", code="mobile_folder_unset")
    resolved = textio.norm_path(os.path.abspath(folder))
    reg = registry if registry is not None else Registry()
    for repo in reg.sorted():
        if repo.path and _inside(resolved, repo.path):
            raise BridgeError(f"the bridge folder is inside the checkout of {repo.name}",
                              "choose a folder outside every registered checkout: records there would sit in "
                              "front of the agent", code="mobile_folder_in_repo")
    if _inside(resolved, fleet_dir()):
        raise BridgeError("the bridge folder is inside the fleet directory",
                          f"choose a folder outside {fleet_dir()}, one OneDrive syncs", code="mobile_folder_in_repo")
    return resolved


# ------------------------------------------------------------------------------ names


def safe_file_name(s: str) -> str:
    """A file name OneDrive for Business and Windows both accept, at most `NAME_MAX` characters, never empty."""
    name = "".join("_" if ch in _ONEDRIVE_EXTRA else ch for ch in str(s or "")).lstrip("~")
    name = textio.safe_name(name)[:NAME_MAX]
    name = textio.safe_name(name)[:NAME_MAX]           # a cut can leave a trailing dot or space
    return name or "_"


# ------------------------------------------------------------------------------ the scrubber

_UNC = re.compile(r"\\\\[^\s\"']+")
_DRIVE = re.compile(r"(?<![\w])[A-Za-z]:[\\/][^\s\"']+")      # not the `s:/` of `https://`
_AGENT_OUT = re.compile(r"\.agent[\\/]out[\\/](\S+)")
_HOST = re.compile(r"\b[\w-]+(?:\.[\w-]+){2,}\b")
_FACT_MIN = 4
_NAME_MIN = 3


class Scrubber:
    """Strips the laptop's own facts and every path shape from free text. Built once; `scrub` is cheap."""

    def __init__(self, registry=None):
        from . import catalogue as CAT
        from .registry import Registry, fleet_dir

        reg = registry if registry is not None else Registry()
        facts: list[tuple[str, str]] = []
        self.link_hosts: set[str] = set()
        paths: list[str] = []
        for repo in reg.sorted():
            if repo.path:
                paths.append(repo.path)
            for key, value in CAT._facts(repo.path).items():
                value = str(value)
                if key in CAT.LINK_FACTS:
                    host = urlparse(value).hostname if "://" in value else ""
                    if host:
                        self.link_hosts.add(host.lower())
                elif len(value) >= _FACT_MIN:
                    facts.append((key, value))
        # Longest first, so a value that contains another is replaced whole.
        self.facts = sorted(set(facts), key=lambda kv: -len(kv[1]))
        self.token = _serve_token(fleet_dir())
        paths += [fleet_dir(), os.path.expanduser("~")]
        spellings = set()
        for p in paths:
            if p and len(p.strip("/\\")) >= _NAME_MIN:
                spellings.update({p, textio.norm_path(p), textio.norm_path(p).replace("/", "\\")})
        self.paths = sorted(spellings, key=len, reverse=True)
        self.user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        self.host = os.environ.get("COMPUTERNAME") or ""

    def scrub(self, text, limit: int = 0) -> str:
        from .events import REDACTED, redact

        out = str(redact({"t": str(text if text is not None else "")})["t"])
        for key, value in self.facts:
            out = out.replace(value, f"<fact:{key}>")
        if self.token:
            out = out.replace(self.token, REDACTED)
        for p in self.paths:
            out = re.sub(re.escape(p), "<path>", out, flags=re.I)
        if len(self.user) >= _NAME_MIN:
            out = re.sub(rf"(?<![\w-]){re.escape(self.user)}(?![\w-])", "<user>", out, flags=re.I)
        if len(self.host) >= _NAME_MIN:
            out = re.sub(rf"(?<![\w-]){re.escape(self.host)}(?![\w-])", "<host>", out, flags=re.I)
        out = _UNC.sub("<unc>", out)
        out = _DRIVE.sub("<path>", out)
        out = _AGENT_OUT.sub(lambda m: ".agent/out/" + re.split(r"[\\/]", m.group(1))[-1], out)
        out = _HOST.sub(lambda m: m.group(0) if m.group(0).lower() in self.link_hosts else "<host>", out)
        if limit and len(out) > limit:
            out = out[:max(0, limit - 1)] + "…"
        return out

    def scrub_obj(self, obj, limit: int = 0):
        """Every string leaf of a dict or list, scrubbed; everything else as it was."""
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v, limit) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_obj(v, limit) for v in obj]
        if isinstance(obj, str):
            return self.scrub(obj, limit)
        return obj


def _serve_token(directory: str) -> str:
    try:
        return str(textio.read_json(os.path.join(directory, "serve.json"), "serve.json").get("token") or "")
    except (OSError, ValueError, AttributeError):
        return ""
