"""The bridge: the laptop's outbox and inbox on OneDrive (epic #538).

The foundations (#545): the settings reader, the folder rule, OneDrive-safe file names, the canonical
JSON every digest is taken over, and the scrubber every free-text field passes through before it leaves
the laptop. The exporter (#546, at the end of this module): `export_once` writes the outbox from one
`fleet_snapshot()`, `write_result` is the verdict writer, `prune` keeps the folder small. The applier
(#547, #548), the thread (#550) and the verbs (#552) build on both.

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
dotted hostnames other than the hosts of `LINK_FACTS` URLs (a three-part version such as `0.17.0` is
not one). `.agent/out/<dir>/<file>` is reduced to `.agent/out/<file>`: the rows never leave (AGENTS.md
rule 5), but the operator still learns which file an approval sends. A deny-list built from the laptop's own facts first, then generic shapes,
because an allow-list cannot be applied to prose.
"""
from __future__ import annotations
import calendar as _calendar
import hashlib as _hashlib
import os
import re
import secrets as _secrets
import threading as _threading
import time as _time
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
# Three numbers are a version (`0.17.0`, `v1.4.10`), not a host: no DNS name ends in a numeric label, and
# an IPv4 address has four. Anything longer or with a letter after the `v` is still a `<host>`.
_VERSION = re.compile(r"v?\d+\.\d+\.\d+", re.I)
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
        out = _HOST.sub(lambda m: m.group(0) if m.group(0).lower() in self.link_hosts
                        or _VERSION.fullmatch(m.group(0)) else "<host>", out)
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


# ============================================================================== the exporter (#546)
#
# Every record the laptop puts in `<folder>/outbox/` is a new, uniquely named, immutable file (MOB-D11): the flow's
# trigger, *When a file is created*, never sees a same-name rewrite. Nothing here is read from anywhere but
# `serve.fleet_snapshot()` (the one fold every desk window reads) and the approval files, and every record is built
# key by key: an allow-list, never a copy of the row with things taken out.

OUTBOX = "outbox"
STATE_FILE = "mobile.state.json"
KEEP_OUTBOX_S = 24 * 3600
KEEP_MOVED_S = 7 * 24 * 3600
QUESTIONS_MAX = 8
CHOICES_MAX = 8
APPROVALS_MAX = 8
_TICKET = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")

ATTENTION_KEYS = frozenset((
    "schema", "kind", "repo", "project", "ticket", "state", "role", "needs_human", "says", "last_said", "age_s",
    "at", "generated", "approvals", "approval_id", "questions", "run", "model", "spend", "supervised", "external",
    "digest", "seq"))
# Left out of the digest: `generated` and `seq` are the file's own, and `age_s` grows by one every second, so a
# digest over it would change on every tick and write a file per tick for a row nothing happened to.
_NOT_DIGESTED = ("digest", "generated", "seq", "age_s")

_state_lock = _threading.Lock()

__all__ += ["ATTENTION_KEYS", "attention_row", "approval_record", "decision_mirror", "heartbeat_record",
            "write_result", "export_once", "prune", "read_state", "update_state", "outbox_dir"]


def _utc(t: float | None = None) -> str:
    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() if t is None else t))


def _epoch(stamp: str) -> float | None:
    try:
        return float(_calendar.timegm(_time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError):
        return None


def _cap(value, limit: int) -> str:
    return str(value if value is not None else "")[:limit]


def outbox_dir(folder: str, *parts: str) -> str:
    return os.path.join(folder, OUTBOX, *parts)


def _attention_name(repo: str, seq: int) -> str:
    """`<repo>-<seq>.json`, the repo cut so the sequence number always survives the name limit."""
    return safe_file_name(safe_file_name(repo)[:NAME_MAX - 16] + f"-{int(seq)}") + ".json"


# ------------------------------------------------------------------------------ the state file


def _state_path() -> str:
    from .registry import fleet_dir

    return os.path.join(fleet_dir(), STATE_FILE)


def _fresh_state() -> dict:
    return {"schema": MOBILE_SCHEMA, "laptop_id": _secrets.token_hex(16), "processed": {}, "attention_digests": {},
            "attention_seq": {}, "exported": {}, "last_export": "", "last_inbox_seen": "", "last_heartbeat": "",
            "rejected_24h": 0, "failures": {}, "retrying": {}}


def _read_state_unlocked() -> dict:
    try:
        on_disk = textio.read_json(_state_path(), STATE_FILE)
    except (OSError, ValueError):
        on_disk = {}
    state = _fresh_state()
    if isinstance(on_disk, dict):
        state.update({k: v for k, v in on_disk.items() if k in state and isinstance(v, type(state[k]))})
    return state


def _write_state_unlocked(state: dict) -> None:
    from .registry import fleet_dir

    os.makedirs(fleet_dir(), exist_ok=True)
    textio.write_json(_state_path(), state)


def read_state() -> dict:
    """`<fleet_dir>/mobile.state.json`, with every key present. The laptop id is minted once and then kept."""
    with _state_lock:
        state = _read_state_unlocked()
        if not os.path.isfile(_state_path()):
            _write_state_unlocked(state)
        return state


def update_state(change) -> dict:
    """Read, `change(state)` in place, write: one read-modify-write under the lock. Returns the state written."""
    with _state_lock:
        state = _read_state_unlocked()
        change(state)
        _write_state_unlocked(state)
        return state


# ------------------------------------------------------------------------------ the records


def _spend_line(spend: dict) -> str:
    """The meter card's words (`drawSpendCell`): `<total> premium`, `of <budget>` only when there is one, turns."""
    bits = [f"{spend.get('total', 0)} premium"]
    if spend.get("budget"):
        bits.append(f"of {spend['budget']}")
    turns = int(spend.get("turns") or 0)
    if turns:
        bits.append(f"{turns} turn" + ("" if turns == 1 else "s"))
    return " · ".join(bits)[:64]


def _question(q: dict, scrub) -> dict:
    return {"id": _cap(q.get("id"), 32), "q": scrub(q.get("q"), LIMITS["q"]),
            "choices": [scrub(c, LIMITS["choice"]) for c in list(q.get("choices") or [])[:CHOICES_MAX]],
            "want": _cap(q.get("want") or "decision", 32), "default": scrub(q.get("default"), LIMITS["default"])}


def attention_digest(row: dict) -> str:
    return _hashlib.sha256(canonical({k: v for k, v in row.items() if k not in _NOT_DIGESTED})).hexdigest()


def attention_row(row: dict, scrub, approvals: list, seq: int = 0) -> dict:
    """One repo's attention record, built key by key from a `fleet_snapshot()` row: exactly `ATTENTION_KEYS`.

    `scrub` is a `Scrubber().scrub`. `approvals` is the snapshot's list (`approval.pending()`, oldest first); this
    repo's ids ride the row, at most eight. `needs_human` is the row's own, never worked out again here.
    """
    from .agentstate import STATE_ROLES, STATES

    repo = str(row.get("repo") or "")
    state = str(row.get("state") or "")
    state = state if state in STATES else "idle"
    ticket = str(row.get("ticket") or "")
    ids = [_cap(a.get("id"), LIMITS["id"]) for a in approvals or [] if str(a.get("repo") or "") == repo]
    ids = ids[:APPROVALS_MAX]
    run = row.get("run") or {}
    spend = row.get("spend") or {}
    spend_cell = {"total": spend.get("total", 0.0), "today": spend.get("today", 0.0),
                  "budget": spend.get("budget", 0.0), "turns": int(spend.get("turns") or 0)}
    spend_cell["line"] = _spend_line(spend_cell)
    out = {"schema": MOBILE_SCHEMA, "kind": "attention",
           "repo": _cap(repo, LIMITS["repo"]),
           "project": _cap(row.get("project") or repo, LIMITS["project"]),
           "ticket": ticket[:LIMITS["ticket"]] if _TICKET.match(ticket) else "",
           "state": state, "role": STATE_ROLES.get(state, "idle"),
           "needs_human": bool(row.get("needs_human")),
           "says": scrub(row.get("why"), LIMITS["says"]),
           "last_said": scrub(row.get("last_said"), LIMITS["last_said"]),
           "age_s": row.get("last_event_age_s", -1),
           "at": _cap(row.get("at"), 32),
           "approvals": ids, "approval_id": ids[0] if ids else "",
           "questions": [_question(q, scrub) for q in (row.get("asked") or [])
                         if q.get("blocking", True)][:QUESTIONS_MAX],
           "run": {"n": int(run.get("n") or 0), "origin": _cap(run.get("origin"), 32), "live": bool(run.get("live")),
                   "since_start": bool(run.get("since_start")), "resumed": bool(run.get("resumed"))},
           "model": _cap(row.get("actual") or row.get("model") or "cli-auto", 64),
           "spend": spend_cell,
           "supervised": bool(row.get("supervised")), "external": bool(row.get("external"))}
    out["digest"] = attention_digest(out)
    out["generated"] = _utc()
    out["seq"] = int(seq)
    return out


def approval_record(request: dict, scrub_obj, cfg: dict | None = None) -> dict:
    """The mirror of one pending request: a scrubbed preview of the payload and the digest of all of it.

    `scrub_obj` is a `Scrubber().scrub_obj` (a `Scrubber` is accepted too). A preview whose canonical form is over
    `LIMITS["preview_bytes"]` becomes `{truncated, bytes, head}`; the digest is `approval.digest(request)` either
    way, so what the phone approves is the whole payload, never the preview. Never `pid`, never `payload`.
    """
    from . import approval
    from .events import redact

    walk = scrub_obj.scrub_obj if isinstance(scrub_obj, Scrubber) else scrub_obj
    preview = walk(redact(request.get("payload")))
    raw = canonical(preview)
    truncated = len(raw) > LIMITS["preview_bytes"]
    if truncated:
        preview = {"truncated": True, "bytes": len(raw),
                   "head": raw[:LIMITS["preview_head"]].decode("utf-8", errors="ignore")}
    ticket = str(request.get("ticket") or "")
    created = _epoch(request.get("created", ""))
    timeout = approval.timeout_seconds(cfg)
    return {"schema": MOBILE_SCHEMA, "kind": "approval",
            "id": _cap(request.get("id"), LIMITS["id"]),
            "repo": _cap(request.get("repo"), LIMITS["repo"]),
            "ticket": ticket[:LIMITS["ticket"]] if _TICKET.match(ticket) else "",
            "approval_kind": _cap(request.get("kind"), 32),
            "summary": walk(str(request.get("summary") or ""), LIMITS["summary"]),
            "payload_preview": preview, "payload_truncated": truncated, "payload_bytes": len(raw),
            "digest": approval.digest(request),
            "created": _utc(created) if created is not None else "",
            "expires": _utc(created + timeout) if created is not None else "",
            "waiting_s": int(request.get("waiting_s") or 0)}


def decision_mirror(id: str, decision: dict, scrub=None) -> dict:
    """The laptop's decision file, as the phone may read it. `nonce` only when the phone decided."""
    scrub = scrub or Scrubber().scrub
    via = str(decision.get("via") or "laptop")
    # approval.decide stamps `decided` with no Z; the outbox writes every stamp in bridge._utc's form (#598).
    decided = _epoch(decision.get("decided", ""))
    out = {"schema": MOBILE_SCHEMA, "kind": "decision", "id": _cap(id, LIMITS["id"]),
           "decision": _cap(decision.get("decision"), 16),
           "reason": scrub(decision.get("reason"), LIMITS["reason"]),
           "by": scrub(decision.get("by"), LIMITS["by"]), "via": _cap(via, 16),
           "decided": _utc(decided) if decided is not None else "", "digest": _cap(decision.get("digest"), 64),
           "late": bool(decision.get("late"))}
    if via == "mobile":
        out["nonce"] = _cap(decision.get("nonce"), 64)
    return out


def _serve_up() -> bool:
    from .opener import serve_record
    from .supervisor import pid_alive

    try:
        pid = int(serve_record().get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return bool(pid) and pid_alive(pid)


def _desk_streams() -> int:
    import sys

    serve = sys.modules.get("agentdata.fleet.serve")
    try:
        return len(serve.live_windows()) if serve is not None else 0
    except Exception:                                  # noqa: BLE001 - a count, never a reason not to beat
        return 0


def heartbeat_record(cfg: dict | None, state: dict, counts: dict) -> dict:
    """`every_s: 300`, the contract, and who and what is beating: a random `laptop_id`, never a hostname or a pid."""
    from ..update import version

    s = settings(cfg)
    return {"schema": MOBILE_SCHEMA, "kind": "heartbeat", "at": _utc(), "every_s": HEARTBEAT_S,
            "expire_s": s["expire_s"], "contract": MOBILE_CONTRACT, "operator": _cap(s["operator"], LIMITS["by"]),
            "bridge": f"agentdata {version()}", "laptop_id": str(state.get("laptop_id") or ""),
            "serve_up": _serve_up(), "desk_streams": _desk_streams(),
            "counts": {k: int(counts.get(k) or 0) for k in ("repos", "needs_human", "approvals_pending",
                                                            "notifications_24h", "rejected_24h")},
            "inbox_last_seen": str(state.get("last_inbox_seen") or "")}


def write_result(folder: str, nonce: str, kind_of: str, ok: bool, *, id: str = "", repo: str = "", code: str = "",
                 error: str = "", hint: str = "", via: str = "", answered=None, late: bool | None = None,
                 retried_s: int | None = None) -> str:
    """`outbox/results/<nonce>.result.json`: the laptop's verdict on one phone decision or reply. #547 and #548 call it.

    The words are the supervisor's or the bridge's own; `via` (`say`|`send`), `answered` and `retried_s` (a reply
    refused `mid_turn` after its retries, #548) belong to replies, `late` to an applied decision (#547).
    """
    if kind_of not in ("decision", "reply"):
        raise BridgeError(f"{kind_of!r} is not a result kind", "decision | reply", code="bad_kind")
    record = {"schema": MOBILE_SCHEMA, "kind": "result", "nonce": _cap(nonce, 64), "kind_of": kind_of}
    if kind_of == "decision":
        record["id"] = _cap(id, LIMITS["id"])
    else:
        record["repo"] = _cap(repo, LIMITS["repo"])
    record.update({"ok": bool(ok), "result": "applied" if ok else "rejected", "code": _cap(code, 64),
                   "error": _cap(error, LIMITS["reason"]), "hint": _cap(hint, LIMITS["reason"])})
    if kind_of == "reply":
        record["via"] = via if via in ("say", "send") else ""
        record["answered"] = [_cap(a, 32) for a in (answered or [])]
        if retried_s is not None:
            record["retried_s"] = int(retried_s)
    elif late is not None:
        record["late"] = bool(late)
    record["at"] = _utc()
    return textio.write_json(outbox_dir(folder, "results", safe_file_name(f"{nonce}.result") + ".json"), record)


# ------------------------------------------------------------------------------ one pass


def _put(path: str, record: dict, written: list, hows: set) -> None:
    report: dict = {}
    textio.write_json(path, record, report=report)
    written.append(textio.norm_path(path))
    hows.add(report.get("how", ""))


def _notifications_24h(folder: str, now: float) -> int:
    directory = outbox_dir(folder, "notifications")
    try:
        return sum(1 for e in os.scandir(directory) if e.name.endswith(".json") and
                   now - e.stat().st_mtime < KEEP_OUTBOX_S)
    except OSError:
        return 0


def export_once(cfg: dict | None = None, snapshot: dict | None = None, *, now: float | None = None,
                dry_run: bool = False) -> dict:
    """One pass over the outbox: attention on a digest change, each pending approval once, each laptop decision once,
    a heartbeat every `HEARTBEAT_S`. Returns `{written: [paths], unchanged: n, how: [...], records: [{kind, repo,
    file}]}`, `how` being each write's `textio` report (`atomic` wherever `os.replace` worked). Refuses as
    `check_folder` does.

    `dry_run=True` (#552, `ad-fleet mobile export --dry-run`) computes the same pass and writes nothing: no record,
    no state, no event. `written` and `records` are what it would have written.
    """
    from . import approval
    from . import events as E

    folder = check_folder(cfg)
    if snapshot is None:
        from .serve import fleet_snapshot

        snapshot = fleet_snapshot()
    now = _time.time() if now is None else now
    scrubber = Scrubber()
    pending = list(snapshot.get("approvals") or [])
    written: list[str] = []
    hows: set[str] = set()
    unchanged = 0
    emits: list[tuple[str, str, dict]] = []
    records: list[dict] = []

    def put(path: str, record: dict, kind: str, repo: str = "") -> None:
        records.append({"kind": kind, "repo": repo, "file": textio.norm_path(os.path.relpath(path, folder))})
        if dry_run:
            written.append(textio.norm_path(path))
        else:
            _put(path, record, written, hows)

    def change(state: dict) -> None:
        nonlocal unchanged
        for row in snapshot.get("repos") or []:
            repo = str(row.get("repo") or "")
            if not repo:
                continue
            record = attention_row(row, scrubber.scrub, pending)
            if state["attention_digests"].get(repo) == record["digest"]:
                unchanged += 1
                continue
            seq = int(state["attention_seq"].get(repo) or 0) + 1
            record["seq"] = seq
            put(outbox_dir(folder, "attention", _attention_name(repo, seq)), record, "attention", repo)
            state["attention_digests"][repo], state["attention_seq"][repo] = record["digest"], seq

        for request in pending:
            id = str(request.get("id") or "")
            if not id or id in state["exported"]:
                unchanged += 1 if id else 0
                continue
            record = approval_record(request, scrubber, cfg)
            path = outbox_dir(folder, "approvals", safe_file_name(id) + ".json")
            if not os.path.exists(path):
                put(path, record, "approval", str(request.get("repo") or ""))
            state["exported"][id] = {"at": _utc(now), "decided": False}
            emits.append((str(request.get("repo") or ""), str(request.get("ticket") or ""),
                          {"id": id, "digest": record["digest"], "expires": record["expires"]}))

        for id, entry in state["exported"].items():
            if entry.get("decided"):
                continue
            decided = approval.read_decision(id)
            if not decided:
                continue
            path = outbox_dir(folder, "approvals", safe_file_name(id) + ".decision.json")
            if not os.path.exists(path):
                put(path, decision_mirror(id, decided, scrubber.scrub), "decision",
                    str(approval.read_request(id).get("repo") or ""))
            entry["decided"] = True

        last = _epoch(state.get("last_heartbeat") or "")
        if last is None or now - last >= HEARTBEAT_S:
            rows = snapshot.get("repos") or []
            counts = {"repos": len(rows), "needs_human": sum(1 for r in rows if r.get("needs_human")),
                      "approvals_pending": len(pending), "notifications_24h": _notifications_24h(folder, now),
                      "rejected_24h": state.get("rejected_24h", 0)}
            beat = heartbeat_record(cfg, state, counts)
            beat["at"] = _utc(now)
            put(outbox_dir(folder, "heartbeat", _time.strftime("%Y%m%d-%H%M", _time.gmtime(now)) + ".json"),
                beat, "heartbeat")
            state["last_heartbeat"] = _utc(now)
        state["last_export"] = _utc(now)

    if dry_run:
        with _state_lock:
            change(_read_state_unlocked())                 # a copy: nothing is written back
        return {"written": written, "unchanged": unchanged, "how": [], "records": records}
    update_state(change)
    # After the state is written, so a failed append can never export an approval twice.
    for repo, ticket, data in emits:
        if repo:
            try:
                E.append(repo, [E.event(repo, "mobile.exported", data, ticket=ticket)])
            except OSError:
                from ..log import debug_exc

                debug_exc("mobile.exported")
    return {"written": written, "unchanged": unchanged, "how": sorted(hows), "records": records}


# ------------------------------------------------------------------------------ pruning


def _older(path: str, cutoff: float) -> bool:
    try:
        return os.path.getmtime(path) < cutoff
    except OSError:
        return False


def _remove(path: str, removed: list) -> None:
    try:
        os.remove(path)
        removed.append(textio.norm_path(path))
    except OSError:
        pass


def _names(directory: str) -> list[str]:
    try:
        return sorted(os.listdir(directory))
    except OSError:
        return []


def prune(folder: str, state: dict, now: float | None = None) -> list[str]:
    """Keep the folder small. Returns the paths removed; `state` is changed in place and the caller writes it.

    After 24 h: decided pairs (the request mirror with its decision), notifications, results, heartbeats, and every
    attention file but each repo's newest. After 7 days: `processed/` and `rejected/`. A request mirror with no
    decision beside it is never touched, however old. Nonces are kept `max(24 h, 2 × expire_s)`.
    """
    now = _time.time() if now is None else now
    day = now - KEEP_OUTBOX_S
    removed: list[str] = []

    approvals = outbox_dir(folder, "approvals")
    for name in _names(approvals):
        if not name.endswith(".decision.json"):
            continue
        decision = os.path.join(approvals, name)
        if _older(decision, day):
            _remove(os.path.join(approvals, name[:-len(".decision.json")] + ".json"), removed)
            _remove(decision, removed)
            (state.get("exported") or {}).pop(name[:-len(".decision.json")], None)

    for sub in ("notifications", "results", "heartbeat"):
        directory = outbox_dir(folder, sub)
        for name in _names(directory):
            if _older(os.path.join(directory, name), day):
                _remove(os.path.join(directory, name), removed)

    attention = outbox_dir(folder, "attention")
    newest: dict[str, tuple[int, str]] = {}
    parsed = []
    for name in _names(attention):
        stem, _, seq = name[:-len(".json")].rpartition("-") if name.endswith(".json") else ("", "", "")
        if not stem or not seq.isdigit():
            continue
        parsed.append((stem, int(seq), name))
        if int(seq) > newest.get(stem, (-1, ""))[0]:
            newest[stem] = (int(seq), name)
    for stem, seq, name in parsed:
        if newest[stem][1] != name and _older(os.path.join(attention, name), day):
            _remove(os.path.join(attention, name), removed)

    for sub in ("processed", "rejected"):
        directory = os.path.join(folder, sub)
        for name in _names(directory):
            if _older(os.path.join(directory, name), now - KEEP_MOVED_S):
                _remove(os.path.join(directory, name), removed)

    keep = max(KEEP_OUTBOX_S, 2 * int(settings().get("expire_s") or EXPIRE_DEFAULT_S))
    processed = state.get("processed") or {}
    for nonce in [n for n, v in processed.items()
                  if (_epoch((v or {}).get("at", "")) or now) < now - keep]:
        processed.pop(nonce, None)
    return removed


# ============================================================================== the applier: decisions (#547)
#
# `inbox/` is a local write path: anyone who can write into the operator's OneDrive folder can drop a file there. So a
# phone's decision reaches `approval.decide()` only after every check below has passed, in this order, and every
# refusal leaves **no decision file**: the agent's own `require()` loop then times out and refuses the write. The
# operator check (`by` against `fleet.mobile.operator`) is a misconfiguration guard, not authentication; signed
# decisions are B12. A record is known by its `nonce`, never by its file name: the sync client resurrects a file it was
# mid-upload on and makes `<name>-<DEVICE>` copies, and either one is a replay.
#
# The checks, first failure wins, each a `mobile_*` code in `rejected/<name>.why.json`:
#   size > INBOX_MAX_BYTES (never parsed)            mobile_too_large
#   not JSON (`textio.read_json`: any BOM, cp1252)   mobile_bad_json
#   not an object, `schema != 1`, unknown `kind`     mobile_bad_schema
#   nonce malformed, or already seen                 mobile_replay
#   `issued` more than SKEW_S in the future          mobile_bad_time
#   not `now <= expires <= issued + expire_s`        mobile_expired
#   `by` is not the operator (case-insensitive)      mobile_wrong_operator
# and for a decision:
#   no such request on disk                          mobile_unknown_id
#   already decided                                  mobile_already_decided
#   `digest != approval.digest(request)`             mobile_digest_mismatch
#   `decision` not approved|denied, bad `device`     mobile_bad_schema
#   a denial with a blank reason                     mobile_reason_required
# `force` is never read (MOB-D8).

INBOX, PROCESSED, REJECTED = "inbox", "processed", "rejected"
SKEW_S = 300
WHY_MAX = 200
DEVICE_MAX = 64
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")
# An ApprovalError from `decide()` itself (a race lost after the checks passed) in the phone's vocabulary.
_DECIDE_CODES = {"not_waiting": "mobile_unknown_id", "already_decided": "mobile_already_decided",
                 "digest_mismatch": "mobile_digest_mismatch", "reason_required": "mobile_reason_required",
                 "bad_state": "mobile_bad_schema"}

__all__ += ["apply_once"]


class _Refused(Exception):
    def __init__(self, code: str, error: str, hint: str = "", retried_s: int | None = None):
        super().__init__(error)
        self.code, self.error, self.hint, self.retried_s = code, error, hint, retried_s


def _stamp(value) -> float | None:
    return _epoch(value) if isinstance(value, str) and _STAMP.match(value) else None


class _Pass:
    """What one `apply_once` knows: the folder, the settings, the time, and the nonces the sidecars name."""

    def __init__(self, cfg: dict | None, folder: str, now: float):
        self.cfg, self.folder, self.now = cfg, folder, now
        self.settings = settings(cfg)
        self._scrubber: Scrubber | None = None
        self._seen: set[str] | None = None
        self._repos: set[str] | None = None

    @property
    def scrubber(self) -> Scrubber:
        if self._scrubber is None:
            self._scrubber = Scrubber()
        return self._scrubber

    def seen(self) -> set[str]:
        """Every nonce a `processed/` or `rejected/` sidecar names: the replay guard that outlives the state file."""
        if self._seen is None:
            self._seen = set()
            for sub, suffix in ((PROCESSED, ".result.json"), (REJECTED, ".why.json")):
                directory = os.path.join(self.folder, sub)
                for name in _names(directory):
                    if name.endswith(suffix):
                        try:
                            nonce = textio.read_json(os.path.join(directory, name), "sidecar").get("nonce")
                        except (OSError, ValueError, AttributeError):
                            continue
                        if nonce:
                            self._seen.add(str(nonce))
        return self._seen

    def registered(self, repo: str) -> bool:
        if self._repos is None:
            from .registry import Registry

            try:
                self._repos = {r.name for r in Registry().sorted()}
            except Exception:                              # noqa: BLE001 - a missing registry names no repo
                self._repos = set()
        return repo in self._repos


def _move(src: str, dest: str) -> bool:
    """`os.replace`, retried as `textio._replace_with_retry` retries it (the sync client holds files briefly)."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(textio.REPLACE_ATTEMPTS):
        try:
            os.replace(textio.longpath(src), textio.longpath(dest))
            return True
        except PermissionError:
            _time.sleep(textio.REPLACE_BACKOFF * (attempt + 1))
        except OSError:
            break
    return False


def _nonce_of(record) -> str:
    nonce = record.get("nonce") if isinstance(record, dict) else None
    return nonce if isinstance(nonce, str) and _NONCE.match(nonce) else ""


def _repo_of(p: "_Pass", record) -> tuple[str, str]:
    """The repo (and ticket) a file names: a known approval's, else a registered repo it names itself, else none."""
    from . import approval

    if not isinstance(record, dict):
        return "", ""
    id = record.get("id")
    if isinstance(id, str) and _ID.match(id):
        request = approval.read_request(id)
        if request.get("repo"):
            return str(request["repo"]), str(request.get("ticket") or "")
    repo = record.get("repo")
    return (repo, "") if isinstance(repo, str) and repo and p.registered(repo) else ("", "")


def _emit(repo: str, kind: str, data: dict, ticket: str = "") -> None:
    """On the repo's own stream, as `say` does; a lock that cannot be taken writes nothing and changes nothing."""
    from . import events as E

    try:
        E.append(repo, [E.event(repo, kind, data, ticket=ticket)])
    except Exception:                                      # noqa: BLE001 - a breadcrumb never changes a verdict
        from ..log import debug_exc

        debug_exc(kind)


def _read(entry):
    """The file's JSON, `st_size` first: a file over the cap is never opened."""
    if entry.stat().st_size > INBOX_MAX_BYTES:
        raise _Refused("mobile_too_large", f"the file is over {INBOX_MAX_BYTES // 1024} KB and was not read",
                       "a phone record is a few hundred bytes; check what wrote it")
    try:
        return textio.read_json(entry.path, "inbox file")
    except ValueError:
        raise _Refused("mobile_bad_json", "the file is not JSON", "FleetDecide writes one JSON object") from None


def _check_common(p: _Pass, record, state: dict) -> dict:
    """Schema, nonce, time, expiry, operator: every inbox file, whatever its kind."""
    if not isinstance(record, dict):
        raise _Refused("mobile_bad_schema", "the file is not a JSON object", "FleetDecide writes one JSON object")
    if record.get("schema") != MOBILE_SCHEMA:
        raise _Refused("mobile_bad_schema", f"schema {record.get('schema')!r} is not {MOBILE_SCHEMA}",
                       "the flow and the laptop disagree on the contract; update the one that is behind")
    if record.get("kind") not in ("decision", "reply"):
        raise _Refused("mobile_bad_schema", f"kind {record.get('kind')!r} is not decision or reply",
                       "only FleetDecide writes into inbox/")
    nonce = _nonce_of(record)
    if not nonce:
        raise _Refused("mobile_replay", "the nonce is missing or malformed",
                       "a nonce is 16-64 letters, digits, - or _; FleetDecide mints one per press")
    if nonce in state["processed"] or nonce in p.seen():
        raise _Refused("mobile_replay", "this nonce was already applied or refused",
                       "a synced copy or a resurrected file; nothing to do")
    issued, expires = _stamp(record.get("issued")), _stamp(record.get("expires"))
    if issued is None or issued > p.now + SKEW_S:
        raise _Refused("mobile_bad_time", "`issued` is missing or in the future",
                       "check the phone's clock; issued may lead the laptop by at most 5 minutes")
    retrying = state["retrying"].get(nonce) if record["kind"] == "reply" else None
    if isinstance(retrying, dict) and expires is not None and p.now > expires:
        # MOB-D7: a reply that waited out a turn until `expires` is refused as what it met, not as expired.
        first = _epoch(str(retrying.get("first_seen") or "")) or p.now
        raise _Refused("mid_turn", str(retrying.get("error") or "mid-turn"), str(retrying.get("hint") or ""),
                       retried_s=int(p.now - first))
    if expires is None or not p.now <= expires <= issued + p.settings["expire_s"]:
        raise _Refused("mobile_expired", "the decision has expired, or expires later than fleet.mobile.expire_s allows",
                       "decide again from the phone")
    by, operator = record.get("by"), p.settings["operator"]
    if not operator or not isinstance(by, str) or by.casefold() != operator.casefold():
        raise _Refused("mobile_wrong_operator", "the file was not written by the configured operator",
                       "fleet.mobile.operator names who may decide from the phone; a misconfiguration guard, "
                       "not authentication" if operator else "set fleet.mobile.operator to your UPN")
    return record


def _check_decision(record: dict) -> tuple[dict, str, str, str]:
    """The request it answers, and its decision, reason and device, or a refusal. Nothing is written here."""
    from . import approval

    id = record.get("id")
    request = approval.read_request(id) if isinstance(id, str) and _ID.match(id) else {}
    if not request:
        raise _Refused("mobile_unknown_id", "no approval with that id is on this laptop",
                       "it was pruned, or the phone read another laptop's outbox")
    if approval.read_decision(id):
        raise _Refused("mobile_already_decided", f"{id} was already decided",
                       "an approval is answered once; the outbox has the decision")
    if record.get("digest") != approval.digest(request):
        raise _Refused("mobile_digest_mismatch", "the decision names a different request (digest mismatch)",
                       "the request on the laptop is not the one the phone showed; read it again")
    decision, reason, device = record.get("decision"), record.get("reason"), record.get("device", "")
    if decision not in (approval.APPROVED, approval.DENIED) or not isinstance(reason, (str, type(None))) \
            or not isinstance(device, (str, type(None))):
        raise _Refused("mobile_bad_schema", "decision must be approved or denied; reason and device are text",
                       "only FleetDecide writes into inbox/")
    reason = (reason or "")[:LIMITS["reason"]]
    if decision == approval.DENIED and not reason.strip():
        raise _Refused("mobile_reason_required", "a denial needs a reason",
                       "the agent quotes it; deny again with a reason")
    return request, decision, reason, (device or "")[:DEVICE_MAX]


def _apply_decision(p: _Pass, path: str, name: str, record: dict) -> None:
    from . import approval

    request, decision, reason, device = _check_decision(record)
    id, nonce, by = request["id"], record["nonce"], record["by"]
    created = _epoch(request.get("created", ""))
    late = created is not None and p.now > created + approval.timeout_seconds(p.cfg)
    try:
        decided = approval.decide(id, decision, reason=reason, by=f"mobile:{by}", digest=record["digest"],
                                  via="mobile", nonce=nonce, late=late)
    except approval.ApprovalError as e:
        raise _Refused(_DECIDE_CODES.get(e.code, "mobile_" + (e.code or "refused")), e.msg, e.hint) from None

    entry = {"at": _utc(p.now), "kind": "decision", "code": "", "name": name, "moved": False,
             "device": p.scrubber.scrub(device, DEVICE_MAX)}
    update_state(lambda s: s["processed"].__setitem__(nonce, entry))
    _emit(str(request.get("repo") or ""), "mobile.decision",
          {"id": id, "kind": "decision", "decision": decision, "by": f"mobile:{by}", "nonce": nonce, "late": late},
          str(request.get("ticket") or ""))
    _finish(p, path, name, nonce, ok=True, id=id, late=late)
    mirror = outbox_dir(p.folder, "approvals", safe_file_name(id) + ".decision.json")
    if not os.path.exists(mirror):
        textio.write_json(mirror, decision_mirror(id, decided, p.scrubber.scrub))

    def mirrored(s: dict) -> None:
        if id in s["exported"]:
            s["exported"][id]["decided"] = True
    update_state(mirrored)


def _finish(p: _Pass, path: str, name: str, nonce: str, *, ok: bool, id: str = "", late: bool | None = None,
            refused: _Refused | None = None, verdict: bool = True, kind_of: str = "decision", repo: str = "",
            via: str = "", answered=None) -> None:
    """Move the file to `processed/` or `rejected/` with its sidecar, and write the verdict (`verdict=False`: a
    replay's, whose first verdict stands). The caller records the nonce first, so a move that fails is retried on the
    next tick rather than read again as a new record."""
    sub = PROCESSED if ok else REJECTED
    if _move(path, os.path.join(p.folder, sub, name)) and nonce and verdict:
        update_state(lambda s: s["processed"].get(nonce, {}).__setitem__("moved", True))
    if ok and kind_of == "reply":
        result = write_result(p.folder, nonce, "reply", True, repo=repo, via=via, answered=answered)
        textio.write_json(os.path.join(p.folder, PROCESSED, name + ".result.json"), textio.read_json(result, "result"))
        return
    if ok:
        result = write_result(p.folder, nonce, "decision", True, id=id, late=late)
        textio.write_json(os.path.join(p.folder, PROCESSED, name + ".result.json"), textio.read_json(result, "result"))
        return
    why = {"code": refused.code, "error": refused.error, "hint": refused.hint, "at": _utc(p.now), "nonce": nonce}
    if refused.retried_s is not None:
        why["retried_s"] = refused.retried_s
    textio.write_json(os.path.join(p.folder, REJECTED, name + ".why.json"), why)
    if nonce and verdict:
        write_result(p.folder, nonce, kind_of, False, id=id, repo=repo, code=refused.code, error=refused.error,
                     hint=refused.hint, retried_s=refused.retried_s)


def _reject(p: _Pass, path: str, name: str, record, refused: _Refused) -> None:
    """To `rejected/` with `<name>.why.json`; a readable nonce gets its result and its place in the state file (a
    replay's does not: the first verdict stands); `mobile.rejected` on the stream of the repo the file names."""
    nonce = _nonce_of(record)
    kind = record.get("kind") if isinstance(record, dict) and record.get("kind") in ("decision", "reply") else ""
    replay = refused.code == "mobile_replay"
    id = record.get("id") if isinstance(record, dict) and isinstance(record.get("id"), str) else ""
    if nonce and not replay:
        entry = {"at": _utc(p.now), "kind": kind, "code": refused.code, "name": name, "moved": False}

        def refused_(s: dict) -> None:
            s["processed"][nonce] = entry
            s["retrying"].pop(nonce, None)
        update_state(refused_)
    named = record.get("repo") if isinstance(record, dict) and isinstance(record.get("repo"), str) else ""
    _finish(p, path, name, nonce, ok=False, id=id[:LIMITS["id"]], refused=refused, verdict=not replay,
            kind_of="reply" if kind == "reply" else "decision", repo=named)
    repo, ticket = _repo_of(p, record)
    if repo:
        _emit(repo, "mobile.rejected", {"nonce": nonce, "kind": kind, "code": refused.code,
                                        "why": p.scrubber.scrub(refused.error, WHY_MAX)}, ticket)


def _retry_move(p: _Pass, path: str, name: str, state: dict) -> bool:
    """A file whose nonce is recorded under this very name but whose move failed last tick: move it now."""
    if not any(v.get("name") == name and not v.get("moved") for v in state["processed"].values()
               if isinstance(v, dict)):
        return False
    try:
        record = textio.read_json(path, "inbox file") if os.path.getsize(path) <= INBOX_MAX_BYTES else {}
    except (OSError, ValueError):
        return False
    nonce = _nonce_of(record)
    entry = state["processed"].get(nonce) if nonce else None
    if not entry or entry.get("name") != name or entry.get("moved"):
        return False
    if _move(path, os.path.join(p.folder, PROCESSED if not entry.get("code") else REJECTED, name)):
        update_state(lambda s: s["processed"].get(nonce, {}).__setitem__("moved", True))
    return True


# ============================================================================== the applier: replies (#548)
#
# A reply is the desk's `act("answer" | "say" | "send")` verbatim (serve.py): `answers` become one
# `lifecycle.answers_prompt`, else the `message` is the text; a console the fleet opened is typed into
# (`supervisor.say`, one line), anything else is resumed headless (`supervisor.send`). After the common checks:
#   `repo` is not a registered name                                   mobile_wrong_repo
#   `message` not text <= 4000; `answers` not <= 8 `{id <= 32, answer <= 1000}`;
#   nothing left to say once blank answers are dropped (as the desk drops them)   mobile_bad_schema
# A `SupervisorError` is the verdict in its own words (`code`, `error`, `hint`, never re-interpreted), except
# `mid_turn`: the phone cannot press Send again a minute later, so the file stays in `inbox/` and is tried every tick
# until its `expires`, then refused `mid_turn` with `retried_s` (MOB-D7). `force` is never read (MOB-D8). The text
# goes to the agent exactly as typed; nothing of it reaches the stream or the outbox (`answered` ids, a word count).

MESSAGE_MAX = LIMITS["message"]
ANSWERS_MAX = 8
ANSWER_ID_MAX = 32
ANSWER_MAX = LIMITS["answer"]


def _check_reply(p: _Pass, record: dict) -> tuple[str, str, list[str]]:
    """The repo, the text the desk would send, and the answered ids, or a refusal. Nothing is written here."""
    repo = record.get("repo")
    if not isinstance(repo, str) or not repo or len(repo) > LIMITS["repo"] or not p.registered(repo):
        raise _Refused("mobile_wrong_repo", "the reply names no repository registered on this laptop",
                       "the phone read another laptop's outbox, or the repository was removed from the fleet")
    message, answers, device = record.get("message"), record.get("answers"), record.get("device", "")
    bad = _Refused("mobile_bad_schema", f"a reply is a message of at most {MESSAGE_MAX} characters and/or at most "
                   f"{ANSWERS_MAX} answers of {{id, answer}}, and says something",
                   "only FleetDecide writes into inbox/")
    if not isinstance(message, (str, type(None))) or len(message or "") > MESSAGE_MAX \
            or not isinstance(device, (str, type(None))):
        raise bad
    if not isinstance(answers, (list, type(None))) or len(answers or []) > ANSWERS_MAX:
        raise bad
    for a in answers or []:
        if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not isinstance(a.get("answer"), str) \
                or len(a["id"]) > ANSWER_ID_MAX or len(a["answer"]) > ANSWER_MAX:
            raise bad
    # `act("answer")`'s filter and `act("say" | "send")`'s strip, verbatim.
    pairs = [(a["id"], a["answer"]) for a in answers or [] if a["id"] and a["answer"].strip()]
    if pairs:
        from . import lifecycle

        return repo, lifecycle.answers_prompt(pairs), [qid for qid, _ in pairs]
    text = (message or "").strip()
    if not text:
        raise bad
    return repo, text, []


def _apply_reply(p: _Pass, path: str, name: str, record: dict) -> bool:
    """Say or send; True when applied, False when left in `inbox/` for the next tick (`mid_turn`)."""
    from . import supervisor

    repo, text, answered = _check_reply(p, record)
    nonce, by = record["nonce"], record["by"]
    cfg = p.cfg if p.cfg is not None else C.load()
    try:
        if supervisor.live(repo).get("kind") == "console":
            via = "say"
            supervisor.say(repo, text, cfg=cfg)
        else:
            via = "send"
            supervisor.send(repo, text, cfg=cfg)            # never force=True (MOB-D8)
    except supervisor.SupervisorError as e:
        if e.code != "mid_turn":
            raise _Refused(e.code or "refused", e.msg, e.hint) from None

        def waiting(s: dict) -> None:
            entry = s["retrying"].setdefault(nonce, {"first_seen": _utc(p.now), "tries": 0})
            entry.update(tries=int(entry.get("tries") or 0) + 1, error=e.msg, hint=e.hint, name=name)
        update_state(waiting)
        return False

    entry = {"at": _utc(p.now), "kind": "reply", "code": "", "name": name, "moved": False, "via": via,
             "device": p.scrubber.scrub(record.get("device") or "", DEVICE_MAX)}

    def applied(s: dict) -> None:
        s["processed"][nonce] = entry
        s["retrying"].pop(nonce, None)
    update_state(applied)
    _emit(repo, "mobile.reply", {"nonce": nonce, "by": f"mobile:{by}", "via": via, "answered": answered,
                                 "words": len(text.split())})
    _finish(p, path, name, nonce, ok=True, kind_of="reply", repo=repo, via=via, answered=answered)
    return True


def _rejected_24h(folder: str, now: float) -> int:
    directory = os.path.join(folder, REJECTED)
    return sum(1 for name in _names(directory)
               if name.endswith(".why.json") and not _older(os.path.join(directory, name), now - KEEP_OUTBOX_S))


def _row_of(p: _Pass, name: str, record, result: str, code: str = "") -> dict:
    """One `ad-fleet mobile apply` row: `{file, kind, repo, result, code}`."""
    kind = record.get("kind") if isinstance(record, dict) and record.get("kind") in ("decision", "reply") else ""
    return {"file": name, "kind": kind, "repo": _repo_of(p, record)[0], "result": result, "code": code}


def _dry_apply(p: _Pass, files: list, report: list) -> dict:
    """Every inbox file through the same checks as `apply_once`, deciding, sending, moving and recording nothing."""
    with _state_lock:
        state = _read_state_unlocked()                     # read_state() would write a missing state file
    counts = {"would_apply": 0, "would_reject": 0}
    for entry in files:
        record = None
        try:
            record = _read(entry)
            _check_common(p, record, state)
            if record["kind"] == "reply":
                _check_reply(p, record)
            else:
                _check_decision(record)
            row = _row_of(p, entry.name, record, "would_apply")
        except _Refused as refused:
            row = _row_of(p, entry.name, record, "would_reject", refused.code)
        except Exception:                                  # noqa: BLE001 - one bad file never stops the pass
            _log(f"mobile inbox {entry.name} (dry run)")
            row = _row_of(p, entry.name, record, "would_reject", "mobile_unreadable")
        counts[row["result"]] += 1
        report.append(row)
    return {"applied": 0, "rejected": 0, "retried": 0, **counts}


def apply_once(cfg: dict | None = None, *, now: float | None = None, dry_run: bool = False,
               report: list | None = None) -> dict:
    """One pass over `inbox/`: every `*.json` file checked, then applied or rejected. Returns `{applied, rejected,
    retried}`. A missing inbox is an empty one. Refuses as `check_folder` does.

    `retried` counts files left for the next tick: an unexpected failure (logged through `debug_exc`; the same one
    twice is `mobile_unreadable`), a move that did not happen, or a reply that met a turn in flight (`mid_turn`, tried
    again every tick until its `expires`, MOB-D7).

    `report`, when given, gets one `{file, kind, repo, result, code}` per file, `result` being `applied`, `rejected`
    or `retried`. `dry_run=True` (#552, `ad-fleet mobile apply --dry-run`) runs every check and nothing else: no
    decision, no send, no move, no nonce recorded, no state written; the rows say `would_apply` or `would_reject`
    and the counts gain `would_apply` and `would_reject`. A reply that would meet a turn in flight is `would_apply`:
    whether a turn is running is the moment's, not the file's.
    """
    folder = check_folder(cfg)
    p = _Pass(cfg, folder, _time.time() if now is None else now)
    counts = {"applied": 0, "rejected": 0, "retried": 0}
    rows = report if report is not None else []
    try:
        entries = sorted(os.scandir(textio.longpath(os.path.join(folder, INBOX))), key=lambda e: e.name)
    except OSError:
        entries = []
    files = [e for e in entries if e.name.endswith(".json") and not e.name.startswith("~$") and e.is_file()]
    if dry_run:
        return _dry_apply(p, files, rows)
    for entry in files:
        path, name = entry.path, entry.name
        state = read_state()
        record = None
        try:
            if _retry_move(p, path, name, state):
                counts["retried"] += 1
                rows.append(_row_of(p, name, {}, "retried"))
                continue
            try:
                record = _read(entry)
                _check_common(p, record, state)
                if record["kind"] == "reply":
                    applied = _apply_reply(p, path, name, record)
                    counts["applied" if applied else "retried"] += 1
                    rows.append(_row_of(p, name, record, "applied" if applied else "retried",
                                        "" if applied else "mid_turn"))
                else:
                    _apply_decision(p, path, name, record)
                    counts["applied"] += 1
                    rows.append(_row_of(p, name, record, "applied"))
            except _Refused as refused:
                _reject(p, path, name, record, refused)
                counts["rejected"] += 1
                rows.append(_row_of(p, name, record, "rejected", refused.code))
            if name in state["failures"]:
                update_state(lambda s: s["failures"].pop(name, None))
        except Exception as e:                             # noqa: BLE001 - one bad file never stops the pass
            from ..log import debug_exc

            debug_exc(f"mobile inbox {name}")
            # The state file's `failures` (name -> the failure it met last tick): the same one twice is unreadable.
            signature = f"{type(e).__name__}: {e}"[:LIMITS["reason"]]
            if state["failures"].get(name) == signature:
                update_state(lambda s: s["failures"].pop(name, None))
                try:
                    _reject(p, path, name, record or {}, _Refused("mobile_unreadable", signature,
                                                                  "it failed the same way twice; see the debug log"))
                    counts["rejected"] += 1
                    rows.append(_row_of(p, name, record, "rejected", "mobile_unreadable"))
                except Exception:                          # noqa: BLE001
                    debug_exc(f"mobile inbox {name} (reject)")
                    counts["retried"] += 1
                    rows.append(_row_of(p, name, record, "retried"))
            else:
                update_state(lambda s: s["failures"].__setitem__(name, signature))
                counts["retried"] += 1
                rows.append(_row_of(p, name, record, "retried"))

    def seen(s: dict) -> None:
        if files:
            s["last_inbox_seen"] = _utc(p.now)
        s["rejected_24h"] = _rejected_24h(folder, p.now)
    update_state(seen)
    return counts


# ============================================================================== the thread and `watch` (#550)
#
# One loop, two hosts (MOB-D5): a daemon thread of `ad-fleet serve` and `quickstart`, started by the CLI after
# `_refresh_models(server)` and ending with `server.stopping`, never by `serve.build()` (every browser test builds a
# server, and none of them may start the bridge); or `ad-fleet mobile watch` in the foreground, for a laptop with no
# desk running. Each pass, in order: the notification sweep (`serve.sweep_if_due("")`, the one sweep the desk's
# streams share, so there is one cursor however many sweep), `export_once` (which beats every `HEARTBEAT_S`),
# `apply_once`, and `prune` every `PRUNE_EVERY_S`. Each step is wrapped on its own: a failure is logged through
# `debug_exc` and the next step and the next pass still run. The tick is a constant, not a setting.
#
# The loop reads the config it was given, or `config.json` afresh on every pass when it was given none (the CLI's
# case), so `operator`, `expire_s` and `notify` are read now, as §Settings says.

BRIDGE_THREAD = "fleet-bridge"

__all__ += ["TICK_S", "BRIDGE_THREAD", "run_loop", "start"]


def _log(where: str) -> None:
    from ..log import debug_exc

    debug_exc(where)


def _jumped(stamps: dict, now: float) -> bool:
    """A wall-clock jump since the last pass: forward further than two minutes and a tick explain (the laptop slept,
    `lifecycle.slept`), or backward at all (the clock was stepped back)."""
    from .lifecycle import SLEEP_GAP_S

    last = stamps.get("wall")
    return last is not None and (now < last or now - last > SLEEP_GAP_S + stamps.get("tick", TICK_S))


def _one_pass(cfg: dict | None, stamps: dict, now: float) -> None:
    """One pass of the loop. `stamps` is the loop's own: `wall` (the last pass) and `prune` (the last prune).

    After a jump the heartbeat and prune stamps are reset rather than trusted: one heartbeat is written now (the phone
    learns the laptop is awake, and a clock stepped back cannot hold the next beat off for hours), and the next prune is
    a whole interval away. Nothing catches up, so a wake is never a burst.
    """
    if _jumped(stamps, now):
        try:
            update_state(lambda s: s.__setitem__("last_heartbeat", ""))
        except Exception:                                  # noqa: BLE001 - logged; the export still beats on time
            _log("bridge jump")
        stamps["prune"] = now
    stamps["wall"] = now
    try:
        from .serve import sweep_if_due

        sweep_if_due("")
    except Exception:                                      # noqa: BLE001 - one step never stops the next
        _log("bridge sweep")
    try:
        export_once(cfg, now=now)
    except Exception:                                      # noqa: BLE001 - one step never stops the next
        _log("bridge export")
    try:
        apply_once(cfg)
    except Exception:                                      # noqa: BLE001 - one step never stops the next
        _log("bridge apply")
    last = stamps.get("prune")
    if last is None or now - last >= PRUNE_EVERY_S:
        stamps["prune"] = now
        try:
            folder = check_folder(cfg)
            update_state(lambda s: prune(folder, s, now))
        except Exception:                                  # noqa: BLE001 - one step never stops the next
            _log("bridge prune")


def run_loop(stop: _threading.Event, cfg: dict | None = None, *, tick: float = TICK_S, once: bool = False) -> None:
    """Pass after pass until `stop` is set (within one `tick`), or once. Never raises."""
    stamps: dict = {"tick": float(tick)}
    while not stop.is_set():
        try:
            _one_pass(cfg, stamps, _time.time())
        except Exception:                                  # noqa: BLE001 - the loop outlives any one pass
            _log("bridge pass")
        if once or stop.wait(tick):
            return


def start(stop: _threading.Event, cfg: dict | None = None) -> _threading.Thread | None:
    """The bridge's daemon thread, started, or `None` when the bridge is off or its folder is refused.

    A refusal is logged through `debug_exc` and never raised: a misconfigured bridge never stops the desk from serving
    (`ad-doctor` and `ad-fleet mobile status` say why). `cfg=None` reads `config.json`, now and on every pass.
    """
    try:
        if not settings(cfg)["enabled"]:
            return None
        check_folder(cfg)
    except Exception:                                      # noqa: BLE001 - logged; the desk serves without it
        _log("bridge start")
        return None
    thread = _threading.Thread(target=run_loop, args=(stop, cfg), name=BRIDGE_THREAD, daemon=True)
    thread.start()
    return thread


# ============================================================================== the verbs' readers (#552)
#
# `ad-fleet mobile init` and `status` (cli_fleet.py prints them). `init`, not `pair` (MOB-D6): no key exchange happens,
# and `pairing.json` carries no secret, only what the flow and the app need to know which laptop they talk to.

TREE = ("outbox/attention", "outbox/approvals", "outbox/notifications", "outbox/heartbeat", "outbox/results",
        INBOX, PROCESSED, REJECTED)
PAIRING = "pairing.json"
OUTBOX_KINDS = ("attention", "approvals", "notifications", "heartbeat", "results")
REJECTED_SHOWN = 20
# `bridge_running`: a pass has exported within this long (the thread or `watch`, at the default tick).
RUNNING_WITHIN_S = 6 * TICK_S
_SYNC_ROOTS = ("OneDriveCommercial", "OneDrive", "OneDriveConsumer")
_FILE_ATTRIBUTE_PINNED = 0x00080000                        # "Always keep on this device" (MS-FSCC 2.6)

__all__ += ["TREE", "PAIRING", "init_tree", "status"]


def init_tree(cfg: dict | None = None) -> dict:
    """The folder's eight directories and `pairing.json`, each created only when missing. Refuses as `check_folder`
    does, before anything is created. Returns `{folder, pairing, made: [dirs], wrote: bool}`; a second run makes
    nothing and rewrites nothing, whatever the settings say now."""
    folder = check_folder(cfg)
    made = []
    for rel in TREE:
        path = os.path.join(folder, *rel.split("/"))
        if not os.path.isdir(path):
            os.makedirs(textio.longpath(path), exist_ok=True)
            made.append(rel)
    path = os.path.join(folder, PAIRING)
    if os.path.exists(path):
        try:
            record = textio.read_json(path, PAIRING)
        except (OSError, ValueError):
            record = {}
        return {"folder": folder, "pairing": record if isinstance(record, dict) else {}, "made": made, "wrote": False}
    s = settings(cfg)
    record = {"schema": MOBILE_SCHEMA, "kind": "pairing", "contract": MOBILE_CONTRACT,
              "operator": _cap(s["operator"], LIMITS["by"]), "laptop_id": str(read_state()["laptop_id"]),
              "expire_s": s["expire_s"], "created": _utc()}
    textio.write_json(path, record)
    return {"folder": folder, "pairing": record, "made": made, "wrote": True}


def _sync_root(folder: str) -> str:
    """The OneDrive root the folder sits under, from the sync client's own variables; `""` when none holds it.
    (`ad-doctor`'s row, #553, also asks the registry.)"""
    for var in _SYNC_ROOTS:
        root = os.environ.get(var, "")
        if root and _inside(folder, root):
            return textio.norm_path(root)
    return ""


def _pinned(folder: str) -> bool | None:
    """Is the folder "Always keep on this device"? `None` where the file system cannot say (off Windows)."""
    try:
        attrs = getattr(os.stat(textio.longpath(folder)), "st_file_attributes", None)
    except OSError:
        return None
    return None if attrs is None else bool(attrs & _FILE_ATTRIBUTE_PINNED)


def _newest(directory: str) -> tuple[int, float]:
    count, newest = 0, 0.0
    for name in _names(directory):
        if name.endswith(".json"):
            count += 1
            try:
                newest = max(newest, os.path.getmtime(os.path.join(directory, name)))
            except OSError:
                pass
    return count, newest


def status(cfg: dict | None = None, *, now: float | None = None) -> tuple[dict, list[dict], list[dict]]:
    """What `ad-fleet mobile status` prints: the settings and folder facts, the outbox's counts per kind, and the
    last `REJECTED_SHOWN` rejections. Reads only: a missing state file is not created. A disabled bridge is described,
    not refused; a refused folder is named by its code in `folder_refused`."""
    now = _time.time() if now is None else now
    s = settings(cfg)
    try:
        folder, refused = check_folder(cfg, need_enabled=False), ""
    except BridgeError as e:
        folder, refused = "", e.code
    with _state_lock:
        state = _read_state_unlocked()
    last_export = str(state.get("last_export") or "")
    exported = _epoch(last_export)
    meta = {"enabled": s["enabled"], "folder": folder or s["folder"], "folder_refused": refused,
            "sync_root": _sync_root(folder) if folder else "", "pinned": _pinned(folder) if folder else None,
            "operator": s["operator"], "expire_s": s["expire_s"], "notify": s["notify"],
            "last_export": last_export, "last_inbox": str(state.get("last_inbox_seen") or ""),
            "serve_up": _serve_up(),
            "bridge_running": s["enabled"] and exported is not None and 0 <= now - exported <= RUNNING_WITHIN_S}
    outbox, rejected = [], []
    if folder:
        for kind in OUTBOX_KINDS:
            count, newest = _newest(outbox_dir(folder, kind))
            outbox.append({"kind": kind, "files": count, "newest": _utc(newest) if newest else ""})
        directory = os.path.join(folder, REJECTED)
        whys = [n for n in _names(directory) if n.endswith(".why.json")]
        whys.sort(key=lambda n: os.path.getmtime(os.path.join(directory, n)) if os.path.exists(
            os.path.join(directory, n)) else 0.0, reverse=True)
        for name in whys[:REJECTED_SHOWN]:
            try:
                why = textio.read_json(os.path.join(directory, name), "sidecar")
            except (OSError, ValueError):
                why = {}
            why = why if isinstance(why, dict) else {}
            rejected.append({"at": str(why.get("at") or ""), "file": name[:-len(".why.json")],
                             "code": str(why.get("code") or "")})
    return meta, outbox, rejected
