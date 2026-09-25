"""The desk in a WebView2 window of its own, with no browser tab: the spike instrument for #354.

Every candidate host is Chromium loading the same URL, so this window exists to be measured against
Edge `--app` on the laptop, not argued about (#353). It is a host like the IDE shells
(docs/fleet-ide.md §What a shell must do): `current_desk` finds a current desk or starts one, and
the window hosts its URL under its own `w`. It decides nothing -- the page is the UI.

Outside the wheel, unsigned, unpackaged, and run only by its own command:

    python ide/desktop/fleet_window.py            # the desk, as w=desktop
    python ide/desktop/fleet_window.py --probe    # the WebGL probe, as shell `desktop`

pywebview is imported by `main()` alone, so nothing else ever needs it. README.md beside this file
says how to install it.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Before agentdata loads, so that its import counts too: the cold start #354 reads runs from here to
# the page's `origin_ms + first_paint_ms` (#351).
STARTED = time.time()

from agentdata import textio  # noqa: E402 -- after STARTED on purpose
from agentdata.fleet import opener, registry  # noqa: E402

WINDOW = "desktop"
GEOMETRY = ("x", "y", "width", "height")


def _geometry_file() -> str:
    return os.path.join(registry.fleet_dir(), "desktop.json")


def _saved_geometry() -> dict:
    """Where the window was when it last closed, as `create_window` keywords. `{}` the first time
    or when the file cannot be read, and pywebview then centres its own default size."""
    try:
        saved = textio.read_json(_geometry_file())
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    return {key: saved[key] for key in GEOMETRY if isinstance(saved.get(key), int)}


def _save_geometry(window) -> None:
    """The window's place and size as it closes. Returns None: a `closing` handler that returned
    False would keep the window open."""
    textio.write_json(_geometry_file(), {key: getattr(window, key) for key in GEOMETRY})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fleet_window", description="The desk in a WebView2 window (the #354 spike).")
    parser.add_argument("--probe", action="store_true",
                        help="host the WebGL probe as shell `desktop` instead of the desk")
    args = parser.parse_args(argv)
    try:
        import webview  # the spike's only dependency, never the wheel's
    except ImportError:
        print("hint: pip install pywebview (it needs the WebView2 Runtime): see ide/desktop/README.md")
        return 2

    record, how = opener.current_desk()
    if args.probe:
        url = opener.page_urls(record, "probe", {"shell": WINDOW})[0]
    else:
        url = opener.url_of(record, window=WINDOW)
    print(f"fleet window: time.time() at start = {STARTED!r} (desk: {how})", flush=True)

    # `text_select=True`: pywebview's default adds a `user-select: none` stylesheet to every page it
    # loads, so no text on the desk could be selected, and the page would be changed by its host.
    window = webview.create_window("fleet", url, text_select=True, **_saved_geometry())
    # Windows parks a minimised window at -32000, -32000: closed from there, the window keeps the
    # place it was last closed at rather than reopening off every screen.
    minimised: list[bool] = []
    window.events.minimized += lambda: minimised.append(True)
    window.events.restored += lambda: minimised.clear()
    window.events.maximized += lambda: minimised.clear()
    window.events.closing += lambda: None if minimised else _save_geometry(window)
    webview.start(gui="edgechromium")
    return 0


if __name__ == "__main__":
    sys.exit(main())
