"""Capture a real tool's output as a transcript.

    python tests/fakes/record.py pip --case winerror5 -- install --force-reinstall agentdata

Run it on the machine where the interesting thing happens — usually the laptop, where the tool is
actually installed and actually fails. The result is checked in with the date it was captured, and
`source: captured` distinguishes it from one written from a screenshot.

A transcript that was invented rather than captured proves the code handles a shape nobody has seen.
The `source` field is there so a reader can tell which they are looking at.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool", help="the tool being recorded: pip, gh, az, te2, dscmd, powershell, pncli")
    ap.add_argument("--case", required=True, help="a short name for this outcome, e.g. winerror5")
    ap.add_argument("--note", default="", help="one line saying what makes this case interesting")
    ap.add_argument("--shell", default="", help="which shell it was run from, if that matters")
    ap.add_argument("--exe", default="", help="the executable, when it is not the tool's own name")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="everything after `--` is passed to the tool")
    a = ap.parse_args()

    args = a.args[1:] if a.args and a.args[0] == "--" else a.args
    exe = a.exe or shutil.which(a.tool)
    if not exe:
        print(f"{a.tool} is not on PATH; pass --exe", file=sys.stderr)
        return 2

    print(f"running: {exe} {' '.join(args)}", file=sys.stderr)
    p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")

    entry = {
        "source": "captured",
        "captured": datetime.date.today().isoformat(),
        "note": a.note,
        "shell": a.shell,
        "argv": [a.tool, *args],
        "match": args[:2],
        "returncode": p.returncode,
        "stdout": p.stdout,
        "stderr": p.stderr,
    }
    directory = os.path.join(HERE, a.tool, "transcripts")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{a.case}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entry, f, indent=2)
        f.write("\n")
    print(f"wrote {os.path.relpath(path)} (exit {p.returncode})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
