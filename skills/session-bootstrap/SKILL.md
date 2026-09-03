---
name: session-bootstrap
description: "Use as the FIRST action of every chat session, before anything else. Loads project identity and state, and confirms the toolchain with ad-doctor. Mandatory even for one-line requests."
---
# Session bootstrap

1. Read `AGENTS.md` at repo root and `.agent/state.json`. Either missing → run exactly `ad-setup --only project --non-interactive --offline --project . --set project.jira_project=<KEY>` (`<KEY>`: the Jira project key the user named, else ask; add `--set project.confluence_space=<SPACE>` when known). `--set` answers prompts inline: never write an answers file (a PowerShell-written file may carry a BOM or be UTF-16). Then continue.
2. Run `ad-doctor --quiet` ONLY if `state.tools.doctor_verified` is not today's date. Command not found → tell the user to install the CLI once per laptop with `pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"`, or to use `python -m agentdata doctor --quiet` if the Scripts folder is not on PATH. Never run `pip install` inside the project repo: it holds reports, not Python. STOP. `ok: false` → print every `fail` row as `<step>/<check>: <hint>` verbatim, tell the user to run `ad-setup --patch` (it re-asks only the settings behind those rows), STOP. Warnings do not stop you.
3. `ad-state set --tool doctor_verified=<today YYYY-MM-DD>` (skill `state-update`; it is the only way state.json is written).
4. If `state.active_ticket` is set: run `ad-pncli jira search --jql "key = <ticket>"`. Print one line: `<ticket> · <status> · phase=<phase> · branch=<branch>`.
5. If `state.phase == "blocked"`: read the newest file in `.agent/friction/`, print its `## What would unblock me` section, ask the user for that input. STOP.
6. Invoke `router`.
