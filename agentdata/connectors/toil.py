"""toil as a library: classify an argv, run a command, read its envelope, name its columns.

toil (`@imagile-dev/toil`) is the service backend: Jira, Confluence, Bitbucket and the rest are reached through it,
and it is used directly for everything it does (`docs/toil-parts.md`). This module is what the `ad-*` extensions
and the fleet need from it in-process: the read/write split the fleet's shim gates on (`fleet/toil_gate.py`), the
envelope every command answers with, the PR read of the fleet's poll, the issue read of a pre-flight, the Jira
column names `ad-view` gives a saved `toil jira issue search` / `toil jira issue get` answer, and the transport
`jira_api` sends REST calls through so a token never leaves toil's credential store.

Every toil command prints ONE JSON envelope on stdout, `{ok, data, error, meta}`, and exits non-zero when `ok` is
false. `run()` returns the envelope and raises `ToilError` (a `proc.ProcError`) for a failed one, carrying toil's
own `error.code` and `error.fix`, which is always the more exact hint.

toil is an npm package, so on Windows it exists as `toil.cmd` (npm's command shim) and never as `toil.exe`: every
launch goes through `agentdata.proc`, which finds the shim (PATHEXT + the npm global prefix) and runs its Node entry
point directly, so a JQL with `>` is never re-parsed by cmd.exe. `TOIL_EXE` or the `toil.exe` config key pins a
launcher that is not on PATH, including a clone's `dist/toil.js` (run under `node`)."""
from __future__ import annotations
import json, os
from .. import config as C
from .. import proc
from ..model import AgentTable

NPM_PACKAGE = "@imagile-dev/toil"   # override with the `toil.npm_package` config key
MIN_NODE = "24.14"                  # toil's own engines floor; below it every command answers UNSUPPORTED_NODE

# The column names a Jira read answers with (`connectors/jira_columns.py`): `ad-view` renders a saved
# `toil jira issue search` / `toil jira issue get` answer with exactly these, and so do the in-process reads below.
from .jira_columns import JIRA_DEFAULT_FIELDS, JIRA_RENAME, ISSUE_RENAME, ISSUE_RENAME_BACK  # noqa: F401 (re-exported)
LIST_KEYS = ("issues", "results", "values", "items", "rows", "connections", "data")


class ToilError(proc.ProcError):
    """toil answered `ok: false`. `code` is toil's own error code (`AUTH`, `WRITE_DISABLED`, ...), `hint` its fix,
    and `detail["details"]` its details (an HTTP failure's `status` among them)."""


# ------------------------------------------------------------------ the read/write split

# toil's own write gate is the classification: a command that changes a system of record needs `--allow-write` on
# the call (and `writes: true` on the connection, set by a person), and without the flag toil refuses it with
# WRITE_DISABLED before anything is sent. So an argv carrying `--allow-write` anywhere is a write, whatever it
# means there -- in doubt, that is a write -- and an argv without one cannot change a service.
ALLOW_WRITE = "--allow-write"
# What toil writes WITHOUT `--allow-write` (`skills/toil/core.md`, **Exceptions**, and the local commands a person
# runs): its own config and dossiers, an agent's skills folder, a feedback report, an MCP server. None of them is an
# agent's to run in a fleet, so each counts as a write. `READ_ACTIONS` names the actions of those groups that only read.
LOCAL_WRITES = frozenset({"connections", "dossiers", "skill", "skills", "setup", "feedback", "mcp"})
READ_ACTIONS = {"connections": frozenset({"list", "test"}),
                "dossiers": frozenset({"list", "show", "context", "check"})}
# Global options that take a value, so the token after one is not the command (`toil --workspace x jira ...`).
_GLOBAL_VALUE = frozenset({"--config", "--output-file", "--workspace", "--select", "--output-format",
                           "--summary-file", "--connection", "--dossier", "--cwd"})


def _positional(args: list[str]) -> list[str]:
    """The bare tokens before `--`, skipping the value of a global option that takes one."""
    out: list[str] = []
    skip = False
    for a in args:
        if a == "--":
            break
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a in _GLOBAL_VALUE
            continue
        out.append(a)
    return out


def verb(args: list[str]) -> tuple:
    """The command path being asked for, as up to three bare tokens (`("jira", "issue", "get")`). Ids follow the
    path in toil (`jira issue get ABC-1`), so a caller that needs only the area reads `verb(args)[:1]`."""
    return tuple(_positional(args)[:3])


def has_flag(args: list[str], *names: str) -> bool:
    """Is one of `names` (or `name=value`) anywhere before `--`? Deliberately position-blind: `--allow-write` as
    some option's value is still counted, because the cost of a false yes is one refused read and the cost of a
    false no is a write sent unattended."""
    for a in args:
        if a == "--":
            return False
        if a in names or any(a.startswith(n + "=") for n in names):
            return True
    return False


def asks_for_help(args: list[str]) -> bool:
    return has_flag(args, "--help", "-h")


def is_write(args: list[str]) -> bool:
    """Would running this change something -- a system of record, or toil's own config, dossiers or skills?

    `--allow-write` anywhere is a write, after `--` too (`toil wait ... -- <command>`): toil refuses a write without
    it, so its absence is the proof of a read.
    `--help` / `-h` is never one: commander prints the help and exits before the action runs. The groups in
    `LOCAL_WRITES` write without the flag, so only their `READ_ACTIONS` are reads. `toil wait` refuses to wait on a
    write by itself, and a write inside it still carries `--allow-write`."""
    if any(a == ALLOW_WRITE or a.startswith(ALLOW_WRITE + "=") for a in args):
        return True
    if asks_for_help(args):
        return False
    path = _positional(args)
    if not path or path[0] not in LOCAL_WRITES:
        return False
    return len(path) < 2 or path[1] not in READ_ACTIONS.get(path[0], frozenset())


# ------------------------------------------------------------------ launching

# A fleet agent's PATH starts with the fleet's toil shim (`fleet/toil_gate.py`); `launch.child_env` names its
# directory here. Every launch from this package resolves the REAL toil with that directory left out, so the gated
# extensions (`ad-confluence publish`, `ad-git pr`, `ad-jira ...`) are not refused by the shim, and the shim never
# runs itself.
SHIM_ENV = "AGENTDATA_TOIL_SHIM"


def shim_dirs() -> list[str]:
    return [d for d in os.environ.get(SHIM_ENV, "").split(os.pathsep) if d.strip()]


def _same_dir(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def search_path() -> str | None:
    """PATH without the shim's directory, or None (the plain PATH) when no shim is set."""
    dirs = shim_dirs()
    if not dirs:
        return None
    keep = [p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p.strip() and not any(_same_dir(p, d) for d in dirs)]
    return os.pathsep.join(keep)


def exe(cfg: dict | None = None) -> str | None:
    """Pinned launcher path: TOIL_EXE, else the `toil.exe` config key. None = resolve `toil` over PATH.
    A pin that points into the shim's directory is ignored: that is the gate, not toil."""
    cfg = C.load() if cfg is None else cfg
    pinned = os.environ.get("TOIL_EXE") or C.get(cfg, "toil.exe") or None
    if pinned and any(_same_dir(os.path.dirname(pinned), d) for d in shim_dirs()):
        return None
    return pinned


def install_hint(cfg: dict | None = None) -> str:
    pkg = C.get(C.load() if cfg is None else cfg, "toil.npm_package") or NPM_PACKAGE
    return (f"toil is an npm package and needs Node {MIN_NODE}+: install it with `npm install -g {pkg}` (it lands as "
            "toil.cmd on Windows, never toil.exe), or pin a launcher -- a clone's dist/toil.js works -- with TOIL_EXE "
            "/ `ad-setup --only toil`. `ad-doctor --only toil` shows what was tried.")


def where(cfg: dict | None = None) -> dict:
    """How `toil` resolves on this machine: path, kind (executable / npm shim / node script), and `toil version`'s
    own answer (`version`, `node`, `contract`), or the error it gave (an old Node answers UNSUPPORTED_NODE)."""
    cfg = C.load() if cfg is None else cfg
    info = proc.resolve("toil", exe=exe(cfg), path=search_path())
    if info["found"]:
        try:
            env = version(cfg)
            data = env.get("data") or {}
            info.update(version=str(data.get("version") or ""), node=info.get("node") or "",
                        node_version=str(data.get("node") or ""), contract=data.get("contractVersion"), rc=0)
        except ToilError as e:
            info.update(version="", rc=1, error=e.msg, code=e.code, fix=e.hint)
        except proc.ProcError as e:
            info.update(version="", rc=-1, error=e.msg)
    return info


def _decode(text: str) -> dict | None:
    """The envelope in toil's stdout. Progress goes to stderr, so stdout is one JSON object; a stray line before it
    (a Node warning) is skipped rather than failing the read."""
    text = text.strip()
    if not text:
        return None
    try:
        got = json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{"ok"')
        if start < 0:
            return None
        try:
            got = json.loads(text[start:])
        except json.JSONDecodeError:
            return None
    return got if isinstance(got, dict) and "ok" in got else None


def raise_for(envelope: dict, args: list[str]) -> None:
    """A failed envelope as `ToilError`: toil's code, message and fix, with its details kept."""
    if envelope.get("ok") is not False:
        return
    err = envelope.get("error") or {}
    code = str(err.get("code") or "toil_error")
    fix = str(err.get("fix") or "")
    if code == "WRITE_DISABLED" and not fix:
        fix = "a person turns writes on for the connection (`toil` menu, or TOIL_<AREA>_WRITES=true)"
    raise ToilError(code, str(err.get("message") or "toil refused the command")[:500],
                    fix or "read toil's message; `ad-doctor --only toil` checks the launcher and the connections",
                    {"details": err.get("details"), "command": " ".join(verb(args))})


def run(args: list[str], timeout: int = 120, cfg: dict | None = None, *, stdin_text: str | None = None,
        cwd: str | None = None) -> tuple[dict, float]:
    """(envelope, elapsed). Raises `ToilError` for `ok: false` and `proc.ProcError` when toil cannot start or
    prints no envelope. `stdin_text` is the body a `--body-file -` reads."""
    cfg = C.load() if cfg is None else cfg
    rc, out, err, el = proc.run(["toil", *args], exe=exe(cfg), timeout=timeout, hint=install_hint(cfg),
                                path=search_path(), stdin_text=stdin_text, cwd=cwd)
    envelope = _decode(out)
    if envelope is None:
        tail = (err or out).strip().splitlines()
        raise proc.ProcError("bad_output", f"toil exited {rc} without an envelope: "
                             + (tail[-1][:200] if tail else "(no output)"),
                             "run the same toil command yourself to see its output; `toil <area> --help` lists "
                             "the commands", {"exit_code": rc})
    raise_for(envelope, args)
    return envelope, el


def version(cfg: dict | None = None) -> dict:
    return run(["version"], timeout=60, cfg=cfg)[0]


def data_of(envelope):
    """`data` from an envelope; anything that is not one is returned as it is (a bare JSON answer)."""
    if isinstance(envelope, dict) and "ok" in envelope and "data" in envelope and "meta" in envelope:
        return envelope["data"]
    return envelope


def is_envelope(payload) -> bool:
    return isinstance(payload, dict) and "ok" in payload and "data" in payload and "meta" in payload


# ------------------------------------------------------------------ connections

def connections(cfg: dict | None = None) -> list[dict]:
    """`toil connections list`: name, area, host, writes, isDefault, definedIn -- never a secret."""
    env, _el = run(["connections", "list"], timeout=60, cfg=cfg)
    return list((env.get("data") or {}).get("connections") or [])


def connection_for(area: str, conns: list[dict], cfg: dict | None = None) -> dict | None:
    """The connection a call to `area` uses: the one pinned in `toil.connections.<area>`, else the area's default,
    else its only one. None when the area has none, or several and none is the default."""
    cfg = C.load() if cfg is None else cfg
    pinned = str(C.get(cfg, f"toil.connections.{area}") or "").strip()
    mine = [c for c in conns if c.get("area") == area]
    if pinned:
        return next((c for c in mine if c.get("name") == pinned), None)
    default = [c for c in mine if c.get("isDefault")]
    if default:
        return default[0]
    return mine[0] if len(mine) == 1 else None


def write_target(areas: tuple[str, ...], cfg: dict | None = None) -> tuple[dict | None, str, str]:
    """(connection, refusal code, hint) for a write the overlay is about to plan in one of `areas` (the Data Center
    area first, then Cloud). Reads `toil connections list` -- local, no network -- so a write toil would refuse is
    refused here, before an operator is asked to approve it:

    * `toil_not_ready`: toil cannot answer (not installed, Node too old);
    * `no_connection`: no connection in any of `areas`, or several and none the default;
    * `writes_off`: the connection exists and writes are off -- a person's switch, which no approval here flips.

    The code is "" when the write can run; the connection is returned whenever one was found."""
    cfg = C.load() if cfg is None else cfg
    try:
        conns = connections(cfg)
    except proc.ProcError as e:
        return None, "toil_not_ready", f"{e.msg} -- {e.hint or install_hint(cfg)}"
    found = next((c for c in (connection_for(a, conns, cfg) for a in areas) if c), None)
    if found is None:
        return None, "no_connection", (f"toil has no {areas[0]} connection to write through: a person adds one "
                                       f"(`toil connections add <name> --area {areas[0]}`), then `ad-doctor --only toil`")
    if not found.get("writes"):
        return found, "writes_off", (f"writes are off on toil's connection {found.get('name')}: a person turns them on "
                                     f"(the `toil` menu, or {'TOIL_' + str(found.get('area')).upper().replace('-', '_')}"
                                     "_WRITES=true); the approval here does not")
    return found, "", ""


def connection_args(area: str, cfg: dict | None = None) -> list[str]:
    """`--connection <name>` when the operator pinned one for `area`, else nothing (toil picks its default)."""
    cfg = C.load() if cfg is None else cfg
    pinned = str(C.get(cfg, f"toil.connections.{area}") or "").strip()
    return ["--connection", pinned] if pinned else []


# ------------------------------------------------------------------ records and columns

def extract_records(payload) -> list:
    """The result list in a toil envelope (its `data`), or in a bare JSON answer."""
    payload = data_of(payload)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                inner = extract_records(payload[k])
                if inner:
                    return inner
        for k in LIST_KEYS:
            if isinstance(payload.get(k), list):
                return payload[k]
        return [payload]
    return []


def get_issue_from_payload(payload, fields: list[str] | None = None, source: str = "toil jira issue get") -> AgentTable:
    """One issue as `toil jira issue get` answers it, with the issue columns (`ISSUE_RENAME`)."""
    recs = extract_records(payload)
    t = AgentTable.from_records(recs, name="issue", source=source,
                                fields=[ISSUE_RENAME_BACK.get(f, f) for f in fields] if fields else None, raw=payload)
    t.columns = [ISSUE_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    return t


def get_issue(key: str, fields: list[str] | None = None, cfg: dict | None = None) -> AgentTable:
    """One issue: `toil jira issue get <KEY>`."""
    cfg = C.load() if cfg is None else cfg
    envelope, el = run(["jira", "issue", "get", key, *connection_args("jira", cfg)], cfg=cfg)
    t = get_issue_from_payload(envelope, fields, source=f"toil jira issue get {key}")
    t.elapsed_s = el
    return t


def jira_search_from_payload(payload, fields: list[str] | None = None, max_results: int | None = None,
                             source: str = "toil jira issue search") -> AgentTable:
    """A Jira search answer with the search columns (`JIRA_RENAME`); short names like `status` are accepted."""
    recs = extract_records(payload)
    short = {v: k for k, v in JIRA_RENAME.items()}
    want = [short.get(f, f) for f in (fields or JIRA_DEFAULT_FIELDS)]
    t = AgentTable.from_records(recs, name="jira", source=source, fields=want, raw=payload)
    t.columns = [JIRA_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    page = ((payload.get("meta") or {}).get("page") or {}) if is_envelope(payload) else {}
    t.truncated = bool(page.get("nextCursor")) or (max_results is not None and len(recs) >= max_results)
    return t


def jira_search(jql: str, fields: list[str] | None = None, max_results: int = 500,
                cfg: dict | None = None) -> AgentTable:
    """`toil jira issue search --jql <JQL> --limit <N>`: one page of at most `max_results`, `truncated` when more."""
    cfg = C.load() if cfg is None else cfg
    envelope, el = run(["jira", "issue", "search", "--jql", jql, "--limit", str(max_results),
                        *connection_args("jira", cfg)], cfg=cfg)
    t = jira_search_from_payload(envelope, fields, max_results, source=f"toil jira issue search --jql {jql!r}")
    t.elapsed_s = el
    return t


def payload_kind(payload) -> str:
    """`search` for a Jira search answer (an `issues` list of issue objects), `issue` for one issue (an object
    with `key` and `fields`), else `""`. A toil envelope is read through its `data`."""
    payload = data_of(payload)
    if isinstance(payload, dict):
        issues = payload.get("issues")
        if isinstance(issues, list) and issues and all(isinstance(i, dict) and ("fields" in i or "key" in i)
                                                       for i in issues):
            return "search"
        if isinstance(payload.get("key"), str) and isinstance(payload.get("fields"), dict):
            return "issue"
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                inner = payload_kind(payload[k])
                if inner:
                    return inner
    return ""


# ------------------------------------------------------------------ a write's argv and answer

def shown_argv(argv: list[str], stdin_chars: int | None = None) -> str:
    """The argv as one line for a person; a body handed over on stdin (`--body-file -`) as `< <N chars>`."""
    import shlex
    line = " ".join(["toil", *(shlex.quote(a) for a in argv)])
    return line + (f" < <{stdin_chars} chars>" if stdin_chars is not None else "")


def find(payload, *keys: str) -> str:
    """The first non-empty scalar under any of `keys`, depth first (a write's answer: an id, a URL)."""
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
                return str(v)
        for v in payload.values():
            got = find(v, *keys)
            if got:
                return got
    elif isinstance(payload, list):
        for v in payload:
            got = find(v, *keys)
            if got:
                return got
    return ""


def url_of(payload) -> str:
    """A write's answer as a link: `url`, `html_url`, `href` (Bitbucket's `links.self[].href`), or Confluence's
    `_links.base` + `_links.webui`."""
    payload = data_of(payload)
    direct = find(payload, "url", "html_url", "web_url", "href")
    if direct.startswith("http"):
        return direct
    base, webui = find(payload, "base"), find(payload, "webui")
    if base.startswith("http") and webui:
        return base.rstrip("/") + "/" + webui.lstrip("/")
    return direct


# ------------------------------------------------------------------ REST through `toil <area> api`

class _Answer:
    """The part of an `http.client.HTTPResponse` a urllib caller reads: `status`, `headers`, `read()`."""

    def __init__(self, status: int, body: bytes):
        import email.message
        self.status, self._body = status, body
        self.headers = email.message.Message()        # toil keeps the service's headers; none reach us

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class ApiOpener:
    """A `urllib.request.urlopen` stand-in that sends each request through `toil <area> api <METHOD> <path>`, so
    the credential stays in toil's store and goes only to the connection's host. Drop-in for a client written
    against urllib (`jira_api.Jira(opener=...)`): its retry, budget and paging logic is unchanged.

    * The URL's path and query are sent relative to the connection's base URL (toil keeps any context path); the
      scheme and host of the URL are the caller's label and are not used.
    * GET and HEAD are reads. Any other method carries `--allow-write`, because toil gates every non-GET verb --
      a POST that only asks a question (Jira Cloud's bulk changelog) included. Whether the WRITE may happen is
      decided before this, by the overlay's dry-run and approval; toil then still needs `writes: true` on the
      connection, which only a person sets, and answers WRITE_DISABLED without it.
    * A JSON body goes over stdin (`--body-file -`), never as an argument.
    * toil's HTTP failures come back as `urllib.error.HTTPError` with the service's status, a timeout or network
      failure as an `OSError`, so the caller's classification of what to retry still holds. A failure that is not
      the service's answer (WRITE_DISABLED, NOT_CONFIGURED, AUTH without a status) raises `ToilError` itself.
    """

    def __init__(self, area: str, connection: str = "", cfg: dict | None = None, timeout_cap: int = 300):
        self.area, self.connection, self.cfg, self.timeout_cap = area, connection, cfg, timeout_cap

    def argv(self, method: str, url: str, has_body: bool) -> list[str]:
        import urllib.parse
        parts = urllib.parse.urlsplit(url)
        path = parts.path.lstrip("/")             # Git Bash rewrites a leading `/rest/...`; toil takes it bare too
        argv = [self.area, "api", method.upper(), path]
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            argv += ["--query", f"{k}={v}"]
        if has_body:
            argv += ["--body-file", "-", "--content-type", "application/json"]
        if method.upper() not in ("GET", "HEAD"):
            argv.append(ALLOW_WRITE)
        if self.connection:
            argv += ["--connection", self.connection]
        return argv

    def __call__(self, req, timeout: float | None = None, context=None):
        import urllib.error
        method = req.get_method()
        body = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else req.data
        argv = self.argv(method, req.full_url, body is not None)
        limit = int(min(max(timeout or 60, 1) * 2 + 30, self.timeout_cap))
        try:
            envelope, _el = run(argv, timeout=limit, cfg=self.cfg, stdin_text=body)
        except ToilError as e:
            details = (e.detail or {}).get("details") or {}
            status = details.get("status") if isinstance(details, dict) else None
            if e.code in ("NETWORK",):
                raise ConnectionResetError(f"{e.msg} ({e.hint})") from None
            if e.code == "TIMEOUT":
                raise TimeoutError(e.msg) from None
            if isinstance(status, int) and status >= 400:
                import email.message
                import io
                hdrs = email.message.Message()
                wait = details.get("retryAfterSeconds")
                if wait is not None:
                    hdrs["Retry-After"] = str(wait)
                raw = json.dumps({"errorMessages": [e.msg]}).encode()
                raise urllib.error.HTTPError(req.full_url, status, e.msg, hdrs, io.BytesIO(raw)) from None
            raise
        except proc.ProcError as e:
            if e.code == "timeout":
                raise TimeoutError(e.msg) from None
            raise
        data = envelope.get("data")
        status = int(((envelope.get("meta") or {}).get("response") or {}).get("status") or 200)
        if data is None:
            return _Answer(status, b"")
        raw = data if isinstance(data, str) else json.dumps(data)
        return _Answer(status, raw.encode("utf-8"))
