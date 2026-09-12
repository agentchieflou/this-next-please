"""The console helper, faked (#190).

`supervisor.say` spawns `ad-fleet say-into <pid> <text>`; on CI there is no console to attach to, so
`fleet.console.helper` points here instead. It records the argv it was given -- which is what proves
the pid and the line reached the helper -- and, when told which session file the console would be
writing, appends the echo a real console produces. Nothing here touches the Win32 API; the real
attach is measured on the laptop (runbook rows C3 and C4).

Environment:
  AGENTDATA_FAKE_SAY_LOG   file to append one JSON line of argv to (required to record anything)
  AGENTDATA_FAKE_SAY_FILE  a session file to append the echoed line to, as the console would
  AGENTDATA_FAKE_SAY_FAIL  a refusal code; the helper prints the refusal as TOON and exits 3
"""
from __future__ import annotations
import json
import os
import sys


def main(argv: list[str]) -> int:
    verb = argv[0] if argv else ""
    log = os.environ.get("AGENTDATA_FAKE_SAY_LOG") or ""
    if log:
        with open(log, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"argv": list(argv)}) + "\n")

    failure = os.environ.get("AGENTDATA_FAKE_SAY_FAIL") or ""
    if failure:
        print("meta:")
        print("  ok: false")
        print(f"  source: ad-fleet {verb}")
        print(f'  error: "the console of pid {argv[1] if len(argv) > 1 else 0} took the attach '
              f'but not the line (win32 6)"')
        print('  hint: "type in that window instead; the tile will show what the session writes"')
        print(f"  refused: {failure}")
        print(f"  code: {failure}")
        print("  win32: 6")
        return 3

    if verb == "say-into":
        text = argv[2] if len(argv) > 2 else ""
        target = os.environ.get("AGENTDATA_FAKE_SAY_FILE") or ""
        if target:
            # What a console does with a typed line: it echoes it, and Copilot records the turn it
            # begins. The tile reads this file and nothing else (#188).
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({
                    "type": "assistant.turn_start", "id": "t", "parentId": None,
                    "timestamp": "2026-09-12T10:05:00Z", "data": {"turnId": "9"}}) + "\n")
                handle.write(json.dumps({
                    "type": "assistant.message", "id": "m", "parentId": None,
                    "timestamp": "2026-09-12T10:05:01Z",
                    "data": {"content": f"Heard: {text}", "model": "claude-haiku-4.5",
                             "toolRequests": []}}) + "\n")
        print("meta:")
        print("  ok: true")
        print("  source: ad-fleet say-into")
        print(f'  echoed: "{text}"')
        print("  events: 4")
        return 0

    print("meta:")
    print("  ok: true")
    print(f"  source: ad-fleet {verb}")
    print("  focused: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
