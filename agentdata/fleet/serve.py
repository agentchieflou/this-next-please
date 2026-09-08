"""`ad-fleet serve`: the multi-viewer. One local page, one tile per agent, live.

The epic is named for YouTube's multi-view and this is that page: a grid of agent tiles, each a
live view of one repository's agent, any one of which can be blown up to fill the window and
dropped back again.

**Why a local web page and not a GUI.** The same artefact has to render in a PyCharm JCEF tool
window (#99), in VS Code's Simple Browser, and in Edge on a fourth monitor (#100) -- three
embedders that agree on exactly one thing, HTML. Those issues then only decide *where* it is shown.

**Zero new dependencies.** `http.server` and `ThreadingHTTPServer`, SSE over a plain chunked
response, hand-written HTML/CSS/JS shipped as package data. No bundler, no framework, no CDN --
JCEF and Simple Browser both sit behind the corporate proxy, so anything the page fetches from the
internet is a page that does not load at work.

**It is a view, not a second source of truth.** Every number comes from #94's normalized stream and
every button calls the same #93/#95 function the CLI verb calls. The server spawns nothing itself.

**Security is loopback plus a per-run token.** The socket binds 127.0.0.1 and nothing else, every
request must carry the token this run generated, and the token is not a cookie -- so another page
on the corporate network cannot drive the fleet even if it guesses the port.
"""
from __future__ import annotations
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import textio
from . import agentstate, approval, board as B, events as E, notify as N, supervisor
from .registry import Registry, RegistryError, fleet_dir

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SERVE_FILE = "serve.json"
HEARTBEAT_S = 15.0
TICK_S = 0.4                 # how often the stream looks for new events; a tile must feel live
NOTIFY_EVERY_S = 5.0         # how often the notification rules run; state changes are not frequent
MAX_BODY = 64 * 1024
# What a shell must speak to host this page. Bumped only when an embedder would have to change:
# a new route it must call, or a changed meaning for one it already calls.
CONTRACT = 1
LOOPBACK = ("127.0.0.1", "::1", "localhost")

# The page may load nothing but itself. Belt and braces with shipping no external references: if a
# later edit pastes in a CDN script tag, the browser refuses it and the test below catches it.
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'"


class ServeError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# --------------------------------------------------------------------------------- the API layer


def fleet_snapshot() -> dict:
    """Everything the page needs to draw itself from cold. Also the reconnect path.

    The row is built field by field rather than merged from `supervisor.status()` wholesale, because
    that dict also carries an `agent` word for the same idea as `state`. Two state words on one row
    is the second-source-of-truth problem in miniature: they would disagree eventually, and nobody
    would know which the tile was showing. The fold (#94) is the state; the supervisor supplies only
    what the fold cannot see -- where the checkout is, and which pid is holding it.
    """
    rows = []
    for row in supervisor.status():
        name = row["repo"]
        try:
            repo = Registry().get(name)
            E.refresh(name, repo.path, repo_state=repo.state())
        except (RegistryError, OSError):
            pass
        stream = E.read(name)
        derived = agentstate.derive(stream, live=bool(supervisor.live(name)))
        rows.append({"repo": name, "path": row.get("path", ""),
                     "jira_project": row.get("jira_project", ""),
                     "pid": row.get("pid", 0), "last_event_age_s": row.get("last_event_age_s", -1),
                     **derived,
                     "last_seq": stream[-1]["seq"] if stream else 0,
                     "needs_human": agentstate.needs_the_human(derived["state"]),
                     "recent": stream[-40:]})
    return {"repos": rows, "approvals": approval.pending(), "fleet_dir": fleet_dir(),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}


def act(what: str, body: dict) -> dict:
    """One action. The same function the CLI verb calls, so the two cannot drift apart."""
    repo = str(body.get("repo") or "")
    if what == "start":
        from .. import config as C

        lock = supervisor.start(repo, key=body.get("ticket") or None,
                                prompt=body.get("prompt") or None,
                                force=bool(body.get("force")), cfg=C.load(),
                                cross_project=bool(body.get("cross_project")),
                                board_rows=(B.read_cache() or {}).get("rows") or [])
        return {"repo": repo, "pid": lock["pid"], "ticket": lock.get("ticket", ""),
                "summary": lock.get("summary", "")}
    if what == "send":
        from .. import config as C

        message = str(body.get("message") or "").strip()
        if not message:
            raise ServeError("nothing to send", "type a message first")
        lock = supervisor.send(repo, message, cfg=C.load())
        return {"repo": repo, "pid": lock["pid"]}
    if what == "stop":
        return supervisor.stop(repo)
    if what in ("approve", "deny"):
        id = str(body.get("id") or "")
        state = approval.APPROVED if what == "approve" else approval.DENIED
        return approval.decide(id, state, reason=str(body.get("reason") or ""))
    raise ServeError(f"unknown action {what!r}", "start | send | stop | approve | deny")


def _sweep(url: str) -> list[dict]:
    """Run the notification rules. Never raises: a notifier that can kill the event stream is worse
    than one that stays quiet, and the tiles carry the same information either way."""
    try:
        from .. import config as C

        return N.sweep(cfg=C.load(), url=url)
    except Exception:                        # noqa: BLE001 - see the docstring
        from ..log import debug_exc

        debug_exc("fleet notify sweep")
        return []


def _cursors(raw: str) -> dict:
    """`luna:12,other:4` -> {'luna': 12, 'other': 4}. The SSE resume point, per agent.

    One number across every agent would be wrong: each agent's `seq` is dense and its own, so a
    shared cursor replays one stream and skips another.
    """
    out = {}
    for part in (raw or "").split(","):
        name, _, seq = part.partition(":")
        if name.strip() and seq.strip().isdigit():
            out[name.strip()] = int(seq)
    return out


def stream_events(cursors: dict, stop: threading.Event, write, *, heartbeat: float = HEARTBEAT_S,
                  tick: float = TICK_S, once: bool = False, url: str = "",
                  notify_every: float = NOTIFY_EVERY_S) -> None:
    """Multiplex every agent's new events onto one SSE connection until the client goes away.

    `write` raises when the socket closes, which is how this ends -- a browser tab being shut is
    the normal case, not an error.

    The notification sweep (#97) rides on the same loop but at its own, slower cadence: the rules
    are about state *changes*, which do not happen four times a second, and each sweep writes the
    dedupe ledger to disk.
    """
    last_beat = 0.0
    last_sweep = 0.0
    while not stop.is_set():
        if time.time() - last_sweep >= notify_every:
            last_sweep = time.time()
            for item in _sweep(url):
                write(f"event: notify\ndata: {json.dumps(item, ensure_ascii=False)}\n\n")
        try:
            names = [r.name for r in Registry().sorted()]
        except RegistryError:
            names = []
        sent = False
        for name in names:
            try:
                repo = Registry().get(name)
                E.refresh(name, repo.path, repo_state=repo.state())
            except (RegistryError, OSError):
                pass
            for ev in E.read(name, since=cursors.get(name, 0)):
                cursors[name] = ev["seq"]
                write(f"id: {name}:{ev['seq']}\nevent: agent\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n")
                sent = True
        if sent or time.time() - last_beat > heartbeat:
            # The heartbeat is not decoration: a proxy that sees no bytes for a minute closes the
            # connection, and the tiles then quietly stop updating with no error anywhere.
            write(f"event: tick\ndata: {json.dumps({'at': time.strftime('%H:%M:%S')})}\n\n")
            last_beat = time.time()
        if once:
            return
        stop.wait(tick)


# ------------------------------------------------------------------------------------ the server


class Handler(BaseHTTPRequestHandler):
    server_version = "ad-fleet"
    sys_version = ""
    token = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):       # noqa: A003 - stdlib's name
        """Silence. The console running the server is the operator's, not a request log."""

    # ------------------------------------------------------------------ plumbing

    def _authorized(self, query: dict) -> bool:
        host = (self.client_address[0] or "").strip("[]")
        if host not in LOOPBACK:
            return False
        given = (query.get("t") or [""])[0]
        return bool(self.token) and hmac.compare_digest(given, self.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _refuse(self, code: int, error: str, hint: str = "") -> None:
        self._json({"ok": False, "error": error, "hint": hint}, code)

    # ---------------------------------------------------------------------- GET

    def do_GET(self) -> None:                # noqa: N802 - stdlib's name
        url = urlparse(self.path)
        query = parse_qs(url.query)
        route = url.path.rstrip("/") or "/"

        # Two routes answer without the token, and both are loopback-only like everything else.
        #
        # `/api/ping` says only that ad-fleet is listening. A launcher has to know that before it
        # decides whether to start a second server, and it holds no token to ask with.
        #
        # `/open` redirects to the real, tokened URL. A per-run token cannot be written into a VS
        # Code keybinding or a PyCharm External Tool, so without this there is no stable address to
        # embed anywhere -- and #99's whole premise is embedding with nothing installed. It is not
        # a hole: any local process can already read `~/.agentdata/fleet/serve.json`, and a
        # cross-origin page that navigates a window here cannot read where it landed.
        if route in ("/api/ping", "/open") and (self.client_address[0] or "").strip("[]") in LOOPBACK:
            if route == "/api/ping":
                from ..version import version_string

                # The shells (#100) check this against their own and raise one balloon on a
                # mismatch. It rides on `ping` rather than a route of its own because a shell that
                # is already asking "are you there" should not need a second round trip to find out
                # "and are we the same age".
                return self._json({"ok": True, "service": "ad-fleet",
                                   "port": self.server.server_address[1],
                                   "version": version_string().split()[1],
                                   "contract": CONTRACT})
            self.send_response(302)
            self.send_header("Location", f"/?t={self.token}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        if not self._authorized(query):
            # Deliberately the same answer for a bad token and a non-loopback caller: neither is
            # told which of the two it got wrong.
            return self._refuse(403, "not authorized",
                                "open the URL `ad-fleet serve` printed, token and all")
        if route == "/":
            return self._static("index.html")
        if route == "/api/fleet":
            return self._json({"ok": True, **fleet_snapshot()})
        if route == "/api/themes":
            return self._json({"ok": True, "themes": themes()})
        if route == "/api/board":
            from .. import config as C

            force = (query.get("refresh") or [""])[0] in ("1", "true", "yes")
            try:
                data = B.board(cfg=C.load(), force=force)
            except B.BoardError as e:
                # 200 with ok:false, not a 5xx: the panel has to render the reason, and a bad JQL
                # is the operator's typo rather than a server fault.
                return self._json({"ok": False, "error": e.msg, "hint": e.hint, "rows": []})
            return self._json({"ok": True, "jql": data["jql"], "cached": data["cached"],
                               "age_s": data["age_s"],
                               "rows": B.with_suggestions(data["rows"])})
        if route == "/api/history":
            since = (query.get("since") or ["7d"])[0]
            return self._json({"ok": True, "since": since,
                               "runs": B.history(since=B.since_seconds(since))})
        if route == "/api/notifications":
            try:
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            from .. import config as C

            return self._json({"ok": True, "notifications": N.read_log(limit),
                               "toast": N.toast_status(C.load()),
                               "settings": N.settings(C.load())})
        if route == "/api/events":
            return self._sse(query)
        if route.startswith("/static/"):
            return self._static(route[len("/static/"):])
        return self._refuse(404, f"no route {route}")

    def _static(self, name: str) -> None:
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._refuse(404, f"no file {name}")
        with open(path, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype)

    def _sse(self, query: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        cursors = _cursors((query.get("since") or [""])[0] or self.headers.get("Last-Event-ID", ""))

        def write(chunk: str) -> None:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()

        url = f"http://127.0.0.1:{self.server.server_address[1]}/?t={self.token}"
        try:
            stream_events(cursors, getattr(self.server, "stopping", threading.Event()), write,
                          url=url)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                              # the tab was closed. Not an error.
        self.close_connection = True

    # --------------------------------------------------------------------- POST

    def do_POST(self) -> None:               # noqa: N802 - stdlib's name
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorized(query):
            return self._refuse(403, "not authorized", "open the URL `ad-fleet serve` printed")
        route = url.path.rstrip("/")
        if not route.startswith("/api/"):
            return self._refuse(404, f"no route {route}")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._refuse(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._refuse(400, "body is not JSON")
        if not isinstance(body, dict):
            return self._refuse(400, "body must be a JSON object")
        what = route[len("/api/"):]
        try:
            return self._json({"ok": True, "action": what, **act(what, body)})
        except (ServeError, RegistryError, supervisor.SupervisorError,
                approval.ApprovalError) as e:
            # The same refusal the CLI gives, with the same hint. One vocabulary.
            return self._refuse(409, e.msg, getattr(e, "hint", ""))
        except Exception as e:               # noqa: BLE001 - a button must never 500 silently
            from ..log import debug_exc

            debug_exc("fleet serve action")
            return self._refuse(500, str(e)[:300], "check the console running `ad-fleet serve`")


# ------------------------------------------------------------------------------------- the theme


def themes() -> list[dict]:
    """The PyCharm `.icls` palettes, so the tool window can match the editor beside it.

    Status colours are deliberately NOT themed: a chip that means "needs you" must be the same red
    in every palette, or the colour stops being information.
    """
    import xml.etree.ElementTree as ET

    root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "themes", "pycharm")
    keys = {"bg": "CONSOLE_BACKGROUND_KEY", "panel": "CARET_ROW_COLOR", "text": "CARET_COLOR",
            "muted": "ANNOTATIONS_COLOR", "accent": "DOC_COMMENT_LINK", "line": "DOC_COMMENT_GUIDE",
            "select": "SELECTION_BACKGROUND"}
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not name.endswith(".icls"):
            continue
        try:
            tree = ET.parse(os.path.join(root, name))
        except (ET.ParseError, OSError):
            continue
        found = {o.get("name"): o.get("value") for o in tree.iter("option") if o.get("value")}
        palette = {k: "#" + found[v] for k, v in keys.items() if found.get(v)}
        if len(palette) == len(keys):
            out.append({"name": os.path.splitext(name)[0], "colors": palette})
    return out


# -------------------------------------------------------------------------------- starting it up


def serve_file() -> str:
    return os.path.join(fleet_dir(), SERVE_FILE)


def build(port: int = 8765, *, token: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    """Bind and return the server, without serving. `port=0` picks a free one."""
    handler = type("BoundHandler", (Handler,), {"token": token or secrets.token_urlsafe(24)})

    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR permits two *live* sockets on one port, so a second
        # `ad-fleet serve --port 8765` would bind happily and the two would split requests at
        # random. On POSIX the same flag only shortens TIME_WAIT, which is worth keeping.
        allow_reuse_address = os.name != "nt"

    try:
        server = Server(("127.0.0.1", port), handler)
    except OSError as e:
        raise ServeError(f"cannot bind 127.0.0.1:{port} ({e})",
                         "something else is on that port; `ad-fleet serve --port 0` picks a free one") from None
    server.daemon_threads = True             # Ctrl-C must not wait on an open SSE connection
    server.stopping = threading.Event()
    return server, handler.token


def url_for(server: ThreadingHTTPServer, token: str) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/?t={token}"


def record(server: ThreadingHTTPServer, token: str) -> str:
    """Write where the page is, so the IDE shells (#99, #100) can find it without being told."""
    return textio.write_json(serve_file(), {"url": url_for(server, token), "token": token,
                                            "port": server.server_address[1], "pid": os.getpid(),
                                            "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())})


def forget() -> None:
    try:
        os.remove(serve_file())
    except OSError:
        pass


def run(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        forget()
