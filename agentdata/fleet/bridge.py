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
dotted hostnames other than the hosts of `LINK_FACTS` URLs. `.agent/out/<dir>/<file>` is reduced to
`.agent/out/<file>`: the rows never leave (AGENTS.md rule 5), but the operator still learns which
file an approval sends. A deny-list built from the laptop's own facts first, then generic shapes,
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
            "rejected_24h": 0}


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
    out = {"schema": MOBILE_SCHEMA, "kind": "decision", "id": _cap(id, LIMITS["id"]),
           "decision": _cap(decision.get("decision"), 16),
           "reason": scrub(decision.get("reason"), LIMITS["reason"]),
           "by": scrub(decision.get("by"), LIMITS["by"]), "via": _cap(via, 16),
           "decided": _cap(decision.get("decided"), 32), "digest": _cap(decision.get("digest"), 64),
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
                 error: str = "", hint: str = "", via: str = "", answered=None) -> str:
    """`outbox/results/<nonce>.result.json`: the laptop's verdict on one phone decision or reply. #547 and #548 call it.

    The words are the supervisor's or the bridge's own; `via` (`say`|`send`) and `answered` belong to replies.
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


def export_once(cfg: dict | None = None, snapshot: dict | None = None, *, now: float | None = None) -> dict:
    """One pass over the outbox: attention on a digest change, each pending approval once, each laptop decision once,
    a heartbeat every `HEARTBEAT_S`. Returns `{written: [paths], unchanged: n, how: [...]}`, `how` being each
    write's `textio` report (`atomic` wherever `os.replace` worked). Refuses as `check_folder` does.
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
            _put(outbox_dir(folder, "attention", _attention_name(repo, seq)), record, written, hows)
            state["attention_digests"][repo], state["attention_seq"][repo] = record["digest"], seq

        for request in pending:
            id = str(request.get("id") or "")
            if not id or id in state["exported"]:
                unchanged += 1 if id else 0
                continue
            record = approval_record(request, scrubber, cfg)
            path = outbox_dir(folder, "approvals", safe_file_name(id) + ".json")
            if not os.path.exists(path):
                _put(path, record, written, hows)
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
                _put(path, decision_mirror(id, decided, scrubber.scrub), written, hows)
            entry["decided"] = True

        last = _epoch(state.get("last_heartbeat") or "")
        if last is None or now - last >= HEARTBEAT_S:
            rows = snapshot.get("repos") or []
            counts = {"repos": len(rows), "needs_human": sum(1 for r in rows if r.get("needs_human")),
                      "approvals_pending": len(pending), "notifications_24h": _notifications_24h(folder, now),
                      "rejected_24h": state.get("rejected_24h", 0)}
            beat = heartbeat_record(cfg, state, counts)
            beat["at"] = _utc(now)
            _put(outbox_dir(folder, "heartbeat", _time.strftime("%Y%m%d-%H%M", _time.gmtime(now)) + ".json"),
                 beat, written, hows)
            state["last_heartbeat"] = _utc(now)
        state["last_export"] = _utc(now)

    update_state(change)
    # After the state is written, so a failed append can never export an approval twice.
    for repo, ticket, data in emits:
        if repo:
            try:
                E.append(repo, [E.event(repo, "mobile.exported", data, ticket=ticket)])
            except OSError:
                from ..log import debug_exc

                debug_exc("mobile.exported")
    return {"written": written, "unchanged": unchanged, "how": sorted(hows)}


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
