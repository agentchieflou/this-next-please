"""Which model ids and effort levels the installed Copilot CLI accepts (#360).

Read from the CLI itself, with no login and no premium request: `copilot help config` lists the ids
its `model` setting takes (26 on 1.0.88, 28 on 1.0.81: the lists differ by build, and since CLI
0.0.421 `-p` errors on a model it cannot serve), and `copilot --help` lists the reasoning efforts,
in one of two formats. The answer is cached in `<fleet_dir>/models.json` with the CLI version it
came from, so a page never waits on a process: `catalogue(spawn=False)` reads the cache, else the
list shipped in `models_shipped.json`, and starts nothing.

The list is a suggestion, never a gate: nothing refuses a name it lacks. A configured or seen id the
build does not list is marked `offered: false` so a picker can say so, and the CLI stays the
validator at the agent's next turn.

A server asks the CLI on a thread of its own (#361): `start_refresh` once when `ad-fleet serve` or
`quickstart` starts and on `POST /api/models {refresh: true}`, one at a time per process, so a page
is never kept waiting on a process.

This module never imports `serve`: the caller passes the ids the stream has seen.
"""
from __future__ import annotations
import datetime as _dt
import hashlib
import json
import os
import re
import threading
import time

from .. import config as C
from .. import proc
from .. import textio
from .registry import fleet_dir

MODEL_KEY = re.compile(r"^\s+`model`:")
ITEM = re.compile(r'^\s+-\s+"([^"\s]+)"\s*$')
EFFORT = re.compile(r"--reasoning-effort <level>\s+[^\[(]*?(?:\[possible values:|\(choices:)\s*([^\])]*)[\])]")
COMPLETION = re.compile(r'--model\)[^;]*?compgen\s+-W\s+"([^"]*)"', re.S)
VERSION = re.compile(r"\d+\.\d+\.\d+")

# (key, title, id prefixes), in the order a picker shows them. The titles are an operator decision
# (#292 Decision, register #318): a relabel happens here and nowhere else.
GROUPS = (
    ("copilot", "Copilot", ("auto",)),
    ("openai", "OpenAI", ("gpt-", "o1", "o3", "o4", "codex")),
    ("anthropic", "Anthropic", ("claude-",)),
    ("google", "Google", ("gemini-",)),
    ("other", "Other", ()),
)
# CLI 1.0.64 added family aliases to the model setting; `help config` does not list them.
ALIASES = {"opus": "anthropic", "sonnet": "anthropic", "haiku": "anthropic", "gpt": "openai", "gemini": "google"}

SHIPPED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_shipped.json")
MAX_AGE_KEY = "fleet.model_list.max_age_h"      # never under fleet.models.*: model_for reads every key there as a repo
DEFAULT_MAX_AGE_H = 24
TIMEOUT = 60
STOPPED = "the server stopped before the CLI was asked"


# ------------------------------------------------------------------------------------ parsers


def parse_help_config(text: str) -> list[str]:
    """The ids under `model` in `copilot help config`, in the CLI's order."""
    out, inside = [], False
    for line in (text or "").splitlines():
        if MODEL_KEY.match(line):
            inside = True
            continue
        if inside:
            m = ITEM.match(line)
            if m:
                out.append(m.group(1))
                continue
            if (not line.strip() and out) or re.match(r"^\s+`", line):
                break
    return out


def parse_efforts(text: str) -> list[str]:
    """The levels `--reasoning-effort` takes, from either `--help` format (`[possible values: …]`
    on 1.0.88, `(choices: "…")` on 1.0.81)."""
    m = EFFORT.search(text or "")
    if not m:
        return []
    return [v.strip().strip('"') for v in " ".join(m.group(1).split()).split(",") if v.strip()]


def parse_completion(text: str) -> list[str]:
    """The ids after `--model)` in `copilot completion bash`, without `auto` (the catalogue adds it)."""
    m = COMPLETION.search(text or "")
    if not m:
        return []
    return [w for w in m.group(1).split() if w and w != "auto"]


def parse_version(text: str) -> str:
    """`1.0.88` from `GitHub Copilot CLI 1.0.88.`; the doctor has its own copy (#358)."""
    m = VERSION.search(text or "")
    return m.group(0) if m else ""


# A family word the name follows, dropped from a label (`claude-`), or kept only when nothing else
# names the model (`gpt-5.5`, `gemini-…` without a word). A version is digits, or `k` and digits.
_FAMILY = re.compile(r"^(claude|gpt|gemini)-")
_VERSION = re.compile(r"^k?\d+(\.\d+)*$")


def label(model_id: str) -> str:
    """What a pill and the pane's chip say (decision 15, #492): the name first, then the version.

    `claude-sonnet-5` -> `sonnet 5`, `gpt-5.6-luna` -> `luna 5.6`, `claude-opus-4.8-fast` ->
    `opus 4.8 fast`, `claude-opus-4.8-20260101` -> `opus 4.8`. An id with no word of its own besides
    its family stays as it is (`gpt-5.5`), and so does one with no version (`opus`, `auto`). The
    desk's `shortModel` is this rule's twin, and the two are checked against each other.
    """
    whole = re.sub(r"-\d{8}$", "", str(model_id or "").strip())
    parts = _FAMILY.sub("", whole).split("-")
    at = next((i for i, p in enumerate(parts) if _VERSION.match(p)), -1)
    words = [p for p in parts if p and not _VERSION.match(p)]
    if at < 0 or not words:
        return re.sub(r"^claude-", "", whole)
    if at == 0:
        # The name after the version (`5.6-luna`) comes first: `luna 5.6`.
        return " ".join([parts[at + 1]] + parts[:at + 1] + parts[at + 2:]) if at + 1 < len(parts) else whole
    return " ".join(parts)


def group_of(model_id: str) -> str:
    if model_id in ALIASES:
        return ALIASES[model_id]
    if model_id == "":
        return "copilot"
    for key, _title, prefixes in GROUPS:
        if any(model_id.startswith(p) for p in prefixes):
            return key
    return "other"


# ------------------------------------------------------------------------------------ discovery


def _run(argv: list[str], timeout: int, stop: threading.Event | None = None) -> str:
    if stop is not None and stop.is_set():
        # A server going away starts nothing more (#361): its refresh is not worth a process.
        raise proc.ProcError("stopped", STOPPED)
    code, out, err, _ = proc.run(argv, timeout=timeout, hint="install the Copilot CLI, or leave the model to it")
    return (out or "") + ("\n" + err if err and code != 0 else "")


def discover_help(timeout: int = TIMEOUT, *, cli_version: str | None = None,
                  stop: threading.Event | None = None) -> dict:
    """Ask the installed CLI. Never raises: a start failure or timeout is `{"ok": False, "why": …}`.
    Once `stop` is set, nothing more is started."""
    try:
        version = (cli_version if cli_version is not None
                   else parse_version(_run(["copilot", "--version"], timeout, stop)))
        ids, source = parse_help_config(_run(["copilot", "help", "config"], timeout, stop)), "help"
        efforts = parse_efforts(_run(["copilot", "--help"], timeout, stop))
        if not ids:
            ids, source = parse_completion(_run(["copilot", "completion", "bash"], timeout, stop)), "completion"
    except proc.ProcError as e:
        return {"ok": False, "why": e.msg, "code": e.code}
    if not ids:
        return {"ok": False, "why": "copilot help config and completion bash listed no models", "code": "no_models"}
    return {"ok": True, "source": source, "cli_version": version, "models": ids, "efforts": efforts}


# ------------------------------------------------------------------------------------ the cache


def cache_file() -> str:
    return textio.norm_path(os.path.join(fleet_dir(), "models.json"))


def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("models"), list) else None


def load_cache() -> dict | None:
    return _read(cache_file())


def shipped() -> dict:
    return _read(SHIPPED_FILE) or {"models": [], "efforts": [], "cli_version": "", "as_of": ""}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_h(cache: dict) -> float:
    try:
        t = _dt.datetime.strptime(str(cache.get("fetched_at", "")), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return float("inf")
    t = t.replace(tzinfo=_dt.timezone.utc)
    return (_dt.datetime.now(_dt.timezone.utc) - t).total_seconds() / 3600.0


def max_age_h(cfg: dict | None) -> float:
    value = C.get(cfg or {}, MAX_AGE_KEY)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(DEFAULT_MAX_AGE_H)
    return value if value > 0 else float(DEFAULT_MAX_AGE_H)


def refresh(cfg: dict | None = None, *, cli_version: str | None = None, path: str | None = None,
            stop: threading.Event | None = None) -> dict:
    """Ask the CLI and write the cache. A failed ask keeps the old cache and records `why` in it.

    Returns the cache now on disk, or `{"failed": True, "why": …}` when the ask failed and there
    was none. Raises OSError only when the cache cannot be written. `path` is the cache file,
    `cache_file()` by default. Once `stop` is set nothing is written: the cache on disk is
    returned as it was.
    """
    path = path or cache_file()
    got = discover_help(cli_version=cli_version, stop=stop)
    if stop is not None and stop.is_set():
        return _read(path) or {"failed": True, "why": STOPPED}
    if got["ok"]:
        cache = {"source": got["source"], "cli_version": got["cli_version"], "fetched_at": _now(),
                 "models": got["models"], "efforts": got["efforts"], "why": ""}
        textio.write_json(path, cache)
        return cache
    cache = _read(path)
    if cache is None:
        return {"failed": True, "why": got["why"]}
    cache["why"] = got["why"]
    textio.write_json(path, cache)
    return cache


def _configured(cfg: dict) -> list[str]:
    out = [str(C.get(cfg, "fleet.model") or "").strip()]
    per_repo = C.get(cfg, "fleet.models") or {}
    if isinstance(per_repo, dict):
        for entry in per_repo.values():
            if isinstance(entry, dict):
                out.append(str(entry.get("model") or "").strip())
    return [m for m in out if m]


def catalogue(cfg: dict | None = None, *, seen=(), spawn: bool = False, cli_version: str | None = None,
              path: str | None = None, stop: threading.Event | None = None) -> dict:
    """`{models, groups, efforts, meta}` for a picker.

    `spawn=False` starts no process: the cache, else the shipped list marked stale. `spawn=True`
    refreshes when the cache is missing or older than `fleet.model_list.max_age_h`; otherwise it
    compares the CLI version (`cli_version`, else one `copilot --version`) with the cached one and
    refreshes only when they differ. `path` and `stop` are `refresh`'s.
    """
    cfg = cfg if cfg is not None else {}
    path = path or cache_file()
    limit = max_age_h(cfg)
    cache, why, write_error = _read(path), "", ""
    if spawn:
        try:
            if cache is None or _age_h(cache) > limit:
                cache = refresh(cfg, cli_version=cli_version, path=path, stop=stop)
            else:
                version = cli_version
                if version is None:
                    try:
                        version = parse_version(_run(["copilot", "--version"], TIMEOUT, stop))
                    except proc.ProcError as e:
                        version, why = "", e.msg
                if version and version != cache.get("cli_version"):
                    cache = refresh(cfg, cli_version=version, path=path, stop=stop)
        except OSError as e:
            write_error = f"cannot write {path}: {e.strerror or e}"
            cache = _read(path)
        if cache is not None and cache.get("failed"):
            why, cache = cache["why"], None

    if cache is not None:
        source, base = cache.get("source") or "help", cache
        why = why or cache.get("why", "")
        stale = _age_h(cache) > limit
        fetched_at = cache.get("fetched_at", "")
    else:
        source, base, stale = "shipped", shipped(), True
        fetched_at = base.get("as_of", "")
    listed = [str(m) for m in base.get("models") or []]
    efforts = [str(e) for e in (base.get("efforts") or shipped().get("efforts") or [])]

    entries: dict[str, dict] = {}

    def add(model_id: str, via: str):
        model_id = str(model_id or "").strip()
        if model_id == "" and via not in ("builtin",):
            return
        e = entries.get(model_id)
        if e is None:
            e = entries[model_id] = {"id": model_id, "label": "CLI default" if model_id == "" else label(model_id),
                                     "group": group_of(model_id), "via": [], "offered": True}
        if via not in e["via"]:
            e["via"].append(via)

    add("", "builtin")
    add("auto", "builtin")
    for m in listed:
        add(m, "shipped" if source == "shipped" else "cli")
    for m in seen or ():
        add(m, "seen")
    for m in _configured(cfg):
        add(m, "config")
    known = set(listed) | {"", "auto"}
    for e in entries.values():
        if e["id"] in known:
            continue
        if e["id"] in ALIASES:
            e["via"].append("alias")
        elif source != "shipped":
            e["offered"] = False

    meta = {"source": source, "cli_version": base.get("cli_version", ""), "fetched_at": fetched_at,
            "max_age_h": int(limit) if limit.is_integer() else limit, "stale": stale, "why": why, "file": path}
    if write_error:
        meta["write_error"] = write_error
    return {"models": list(entries.values()),
            "groups": [{"key": k, "title": t} for k, t, _ in GROUPS],
            "efforts": efforts, "meta": meta}


def digest(cat: dict) -> str:
    """A `models` stream frame's `version` (#361): each entry's id and whether the CLI offers it,
    and the efforts. A refresh that found the same list keeps it; `fetched_at` is not in it."""
    rows = [[m.get("id", ""), bool(m.get("offered"))] for m in cat.get("models") or []]
    blob = json.dumps(rows + [str(e) for e in cat.get("efforts") or []], ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()   # noqa: S324 - a change marker, not a credential


# ------------------------------------------------------------------------------------ the refresh thread


#: One refresh at a time in this process (#361), and no module state to hold it: the running thread
#: is the state, found by this name in `threading.enumerate()`, so nothing is left for a test (or a
#: server that stops and starts again) to reset.
REFRESH_THREAD = "models-refresh"
# Held while one call looks for a running refresh and starts its own, so two calls never both start.
_REFRESH_LOCK = threading.Lock()


def _running() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == REFRESH_THREAD and t.is_alive()]


def _refresh_thread(cfg: dict, path: str, stop: threading.Event | None, force: bool) -> None:
    try:
        if stop is not None and stop.is_set():
            return
        if force:
            refresh(cfg, path=path, stop=stop)
        else:
            catalogue(cfg, spawn=True, path=path, stop=stop)
    except Exception:                        # noqa: BLE001 - a refresh must never take its server down
        from ..log import debug_exc

        debug_exc("fleet models refresh")


def start_refresh(stop: threading.Event | None = None, *, force: bool = False) -> bool:
    """Ask the CLI on a daemon thread and return at once: True when this call started it, False when
    a refresh was already running, which this call joins instead of starting a second.

    `force=True` asks whatever the cache says (`refresh`); otherwise the cache is kept while it is
    fresh and from the installed `--version` (`catalogue(spawn=True)`). The cache path and the
    config are read here, when the refresh starts, never later: a test whose fleet directory has
    been put back cannot have a late write land in the next test's, or in the real home. Once
    `stop` (the server's `stopping`) is set, nothing more is started and nothing is written.
    """
    with _REFRESH_LOCK:
        if _running():
            return False
        try:
            cfg = C.load()
        except (C.ConfigError, OSError):
            cfg = {}
        # `start()` returns once the thread is alive, so the next call under the lock sees it.
        threading.Thread(target=_refresh_thread, args=(cfg, cache_file(), stop, force),
                         name=REFRESH_THREAD, daemon=True).start()
    return True


def refreshing() -> bool:
    """True while a refresh is running in this process."""
    return bool(_running())


def wait_refresh(timeout: float) -> bool:
    """True once no refresh is running; False at the deadline, with one still running."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        running = _running()
        if not running:
            return True
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        running[0].join(left)
