"""Throwaway (#603): the harness's pattern without the suite -- does Chromium's connect get WSAENOBUFS?

Per iteration: a new ThreadingHTTPServer on port 0 (a new port, as each desk is), a new browser context,
a page that loads 12 module scripts and opens an EventSource (as the desk does), wait for all of it,
close the context, stop the server. VARIANT picks what changes:
  shared     one Chromium for every iteration (the harness since #303)
  recycle    a new Chromium every 25 iterations
  fresh      a new Chromium every iteration (before #299)
  close      one Chromium, and the server answers `Connection: close`
Counts page loads, failed requests by error text, and time."""
import collections
import http.server
import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright

VARIANT = os.environ.get("VARIANT", "shared")
SECONDS = float(os.environ.get("SECONDS_BUDGET", "600"))
MODS = 12
BODY = {f"/m{i}.js": (f"export const v{i} = {i};\n" + "// pad\n" * (200 * (i + 1))).encode() for i in range(MODS)}
INDEX = ("<!doctype html><script type=module>"
         + "".join(f"import {{ v{i} }} from './m{i}.js';" for i in range(MODS))
         + "window.done = true; new EventSource('/sse');</script>").encode()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while not self.server.stopping.is_set():
                    self.wfile.write(b": tick\n\n")
                    self.wfile.flush()
                    self.server.stopping.wait(0.2)
            except OSError:
                pass
            self.close_connection = True
            return
        body = INDEX if self.path == "/" else BODY.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/" else "text/javascript")
        self.send_header("Content-Length", str(len(body)))
        if VARIANT == "close":
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


def serve():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    s.daemon_threads = True
    s.stopping = threading.Event()
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return s


def main():
    failed = collections.Counter()
    loads = errors = 0
    t0 = time.time()
    with sync_playwright() as p:
        browser = None
        i = 0
        while time.time() - t0 < SECONDS:
            if browser is None or (VARIANT == "recycle" and i % 25 == 0) or VARIANT == "fresh":
                if browser is not None:
                    browser.close()
                browser = p.chromium.launch(headless=True, **({"executable_path": os.environ["AGENTDATA_CHROMIUM"]} if os.environ.get("AGENTDATA_CHROMIUM") else {}))
            i += 1
            s = serve()
            ctx = browser.new_context()
            page = ctx.new_page()
            page.on("requestfailed", lambda r: failed.update([str(r.failure)]))
            try:
                page.goto(f"http://127.0.0.1:{s.server_address[1]}/", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_function("() => window.done === true", timeout=15000)
                loads += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                failed.update([str(e).splitlines()[0][:100]])
            ctx.close()
            s.stopping.set()
            s.shutdown()
            s.server_close()
        if browser is not None:
            browser.close()
    print(f"{VARIANT}: {i} iterations in {time.time() - t0:.0f}s, {loads} loads, {errors} errors; failed: {dict(failed)}")


main()
