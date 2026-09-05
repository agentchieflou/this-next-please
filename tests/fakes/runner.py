"""What every fake tool actually runs: match the argv against a transcript and replay it.

One file for both platforms, so a Windows `.cmd` shim and a POSIX `sh` shim behave identically and
a test cannot pass on one OS for a reason that does not exist on the other.

Selection: `AGENTDATA_FAKE_CASE` names the transcript. Without it, the first transcript whose
`match` is a prefix of the argv wins. No match at all is exit **99** with the argv echoed — a test
then shows exactly what the code sent, instead of a silent success that proves nothing.

**Two kinds of transcript.** Most are `stdout` + `returncode`: the tool printed this, so the fake
prints this. The fake `copilot` needs more, because an agent is not a program that prints — it is a
program that *does things over time*, and the fleet's whole job is watching that happen. Those
transcripts carry `steps`, and a step either emits one JSONL event or runs a real `ad-*` command
and emits what happened. The state files the fleet then reads are real files, changed by the real
`ad-state`, and not a fixture somebody remembered to update.
"""
from __future__ import annotations
import json
import os
import shlex
import subprocess
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


# ------------------------------------------------------------------- an agent that does things


def _flag_values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag and i + 1 < len(argv)]


def _one(argv: list[str], flag: str, default: str = "") -> str:
    found = _flag_values(argv, flag)
    return found[0] if found else default


def permitted(command: str, allow: list[str], deny: list[str]) -> tuple[bool, str]:
    """The real CLI's rule, as the spike measured it: `shell(<prefix>)` is a PREFIX match.

    Deny wins, and is checked first -- which is what makes a deny useless as a safety net for a
    loose allow, since `shell(git push --force)` does not match `git push -u origin HEAD --force`.
    Reproducing that faithfully is the point: a fake that were *safer* than the real thing would
    hide the reason the fleet's allow-list has to be an enumerated whitelist.
    """
    def prefixes(patterns):
        out = []
        for p in patterns:
            p = p.strip()
            if p.startswith("shell(") and p.endswith(")"):
                out.append(p[len("shell("):-1])
        return out

    for prefix in prefixes(deny):
        if command.startswith(prefix):
            return False, f"denied by --deny-tool shell({prefix})"
    for prefix in prefixes(allow):
        if command.startswith(prefix):
            return True, ""
    return False, "no --allow-tool pattern permits this command"


def emit(event: dict) -> None:
    event.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def play(entry: dict, argv: list[str]) -> int:
    """Replay a transcript that *acts*: emit events, run commands, honour the permission flags."""
    allow = _flag_values(argv, "--allow-tool")
    deny = _flag_values(argv, "--deny-tool")
    resumed = bool(_flag_values(argv, "--resume"))
    session = _one(argv, "--resume") or entry.get("session") or "fake-session-1"
    steps = entry.get("resume_steps" if resumed and entry.get("resume_steps") else "steps") or []

    calls = 0
    for step in steps:
        if "sleep" in step:
            time.sleep(float(step["sleep"]))
        if "emit" in step:
            emit(dict(step["emit"]))
        if "stderr" in step:
            sys.stderr.write(step["stderr"])
            sys.stderr.flush()
        if step.get("write_friction"):
            _write_friction()
        if "run" in step:
            calls += 1
            calls_id = f"t{calls}"
            command = step["run"]
            emit({"type": "tool.execution_start",
                  "data": {"toolCallId": calls_id, "toolName": "shell",
                           "arguments": {"command": command}}})
            allowed, why = permitted(command, allow, deny)
            if not allowed:
                # Exactly the shape the spike recorded: the tool is attempted, refused, reported on
                # `tool.execution_complete`, and the turn still finishes 0. There is no permission
                # *request* event, which is why the fleet reads denials and not requests.
                emit({"type": "tool.execution_complete",
                      "data": {"toolCallId": calls_id, "success": False,
                               "error": {"code": "denied",
                                         "message": "Permission denied and could not request "
                                                    f"permission from user ({why})"}}})
                continue
            code, output = _run(command)
            emit({"type": "tool.execution_complete",
                  "data": {"toolCallId": calls_id, "success": code == 0,
                           "output": output[-400:],
                           **({} if code == 0 else
                              {"error": {"code": "failed", "message": output[-200:]}})}})
        if "exit" in step:
            break

    usage = entry.get("usage", {"premiumRequests": 1.0, "codeChanges": {"filesModified": []}})
    emit({"type": "result", "sessionId": session, "exitCode": int(entry.get("returncode", 0)),
          "usage": usage})
    _write_usage(argv, usage)
    return int(entry.get("returncode", 0))


def _run(command: str) -> tuple[int, str]:
    """Run a real `ad-*` command, so `state.json` really changes and the fleet sees a real file."""
    # POSIX splitting on both platforms: this is our own transcript text, not a Windows command
    # line. Windows rules would leave the quotes attached, so `--question "Which workspace?"` would
    # be stored with its quotation marks in it.
    argv = shlex.split(command, posix=True)
    env = dict(os.environ)
    if argv and argv[0].startswith("ad-"):
        # The console scripts are frequently not on PATH -- which is the whole reason the module
        # form exists -- and a fake that depended on them would fail for a reason unrelated to
        # anything it is testing.
        argv = [sys.executable, "-m", "agentdata", argv[0][3:]] + argv[1:]
        # ...and the module form needs the package to be importable from a *different* working
        # directory, which in a checkout without `pip install -e .` it is not. The repo root is
        # three levels up from this file; adding it when it really holds the package covers the
        # checkout and changes nothing for an installed one.
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isfile(os.path.join(root, "agentdata", "__init__.py")):
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120, env=env,
                              stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except Exception as e:                       # noqa: BLE001 - the fake reports, never crashes
        return 1, str(e)


FRICTION = """# Friction

## What happened

The acceptance criteria contradict each other: one says the UAT workspace, the other names PROD.

## What would unblock me

A decision on which workspace this ticket covers.
"""


def _write_friction() -> None:
    """What the `friction-log` skill writes when it gives up. A real file in the real place, so the
    fleet reads it the way it will in production rather than from a fixture."""
    directory = os.path.join(os.getcwd(), ".agent", "friction")
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, time.strftime("%Y%m%d") + "-jira-triage.md")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(FRICTION)
    except OSError:
        pass


def _write_usage(argv: list[str], usage: dict) -> None:
    path = _one(argv, "--usage-output-file")
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(usage, f)
    except OSError:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("fake runner: no tool name\n")
        return 99
    tool, argv = sys.argv[1], sys.argv[2:]
    case = os.environ.get("AGENTDATA_FAKE_CASE")

    for entry in load(tool, case):
        if not (case or matches(entry, argv)):
            continue
        if entry.get("delay"):
            time.sleep(float(entry["delay"]))
        if entry.get("steps") or entry.get("resume_steps"):
            return play(entry, argv)
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
