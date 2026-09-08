"""What every fake tool actually runs: match the argv against a transcript and replay it.

One file for both platforms, so a Windows `.cmd` shim and a POSIX `sh` shim behave identically and
a test cannot pass on one OS for a reason that does not exist on the other.

Selection: `AGENTDATA_FAKE_CASE` names the transcript. Without it, the first transcript whose
`match` is a prefix of the argv wins. No match at all is exit **99** with the argv echoed — a test
then shows exactly what the code sent, instead of a silent success that proves nothing.
"""
from __future__ import annotations
import json
import os
import sys
import time


def load(tool: str, case: str | None) -> list[dict]:
    root = os.environ.get("AGENTDATA_FAKE_DIR") or os.path.dirname(os.path.abspath(__file__))
    directory = os.path.join(root, tool, "transcripts")
    if not os.path.isdir(directory):
        return []
    names = [f"{case}.json"] if case else sorted(os.listdir(directory))
    out = []
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def matches(entry: dict, argv: list[str]) -> bool:
    """A transcript's `match` is a list of tokens that must all appear, in order, in the argv."""
    wanted = entry.get("match")
    if wanted is None:
        wanted = [a for a in (entry.get("argv") or [])[1:]]
    index = 0
    for token in wanted:
        while index < len(argv) and argv[index] != token:
            index += 1
        if index == len(argv):
            return False
        index += 1
    return True


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("fake runner: no tool name\n")
        return 99
    tool, argv = sys.argv[1], sys.argv[2:]
    case = os.environ.get("AGENTDATA_FAKE_CASE")

    for entry in load(tool, case):
        if case or matches(entry, argv):
            if entry.get("delay"):
                time.sleep(float(entry["delay"]))
            sys.stdout.write(entry.get("stdout", ""))
            sys.stderr.write(entry.get("stderr", ""))
            return int(entry.get("returncode", 0))

    sys.stderr.write(
        f"fake {tool}: no transcript matches this argv.\n"
        f"  argv: {argv}\n"
        f"  case: {case or '(none; matching by argv)'}\n"
        "Capture one with `python tests/fakes/record.py <tool> -- <args>`.\n"
    )
    return 99


if __name__ == "__main__":
    sys.exit(main())
