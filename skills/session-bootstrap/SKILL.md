---
name: session-bootstrap
description: Use as the FIRST action of every chat session, before anything else. Loads project identity, state, and confirms tools. Mandatory even for one-line requests.
---
# Session bootstrap

1. Read `AGENTS.md` at repo root. Read `.agent/state.json`. If missing → copy from `templates/project-stub/` in the installed skills repo, fill `project`, then continue.
2. Run `pncli --help` ONLY if `state.tools.pncli_verified` is not today's date. Record the date.
3. Run `ad-view --help`. If it fails → tell the user `pip install -e <this-next-please>` and STOP.
4. If `state.active_ticket` is set: run `ad-pncli jira search --jql "key = <ticket>"`. Print one line: `<ticket> · <status> · phase=<phase> · branch=<branch>`.
5. If `state.phase == "blocked"`: read the newest file in `.agent/friction/`, print its `## What would unblock me` section, ask the user for that input. STOP.
6. Invoke `router`.
