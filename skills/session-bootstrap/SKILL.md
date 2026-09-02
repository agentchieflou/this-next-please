---
name: session-bootstrap
description: "Use as the FIRST action of every chat session, before anything else. Loads project identity and state, and confirms the toolchain with ad-doctor. Mandatory even for one-line requests."
---
# Session bootstrap

1. Read `AGENTS.md` at repo root. Read `.agent/state.json`. If missing → run `ad-setup --project .` (writes both from the packaged project stub, filling the facts it knows), then continue.
2. Run `ad-doctor --quiet` ONLY if `state.tools.doctor_verified` is not today's date. Command not found → tell the user to install the CLI once per laptop with `pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"`, or to use `python -m agentdata doctor --quiet` if the Scripts folder is not on PATH. Never run `pip install` inside the project repo: it holds reports, not Python. STOP. `ok: false` → print every `fail` row as `<step>/<check>: <hint>` verbatim, tell the user to run the `ad-setup --only <step>` it names, STOP. Warnings do not stop you.
3. Record today's date in `state.tools.doctor_verified` via `state-update`.
4. If `state.active_ticket` is set: run `ad-pncli jira search --jql "key = <ticket>"`. Print one line: `<ticket> · <status> · phase=<phase> · branch=<branch>`.
5. If `state.phase == "blocked"`: read the newest file in `.agent/friction/`, print its `## What would unblock me` section, ask the user for that input. STOP.
6. Invoke `router`.
