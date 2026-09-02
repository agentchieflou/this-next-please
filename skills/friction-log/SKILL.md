---
name: friction-log
description: "Use the moment you second-guess yourself, repeat a tool call, hit ambiguous acceptance criteria, or get two failures in a row. Writes a structured entry for an offline architect model and STOPS. Never try to fix instructions yourself."
---
# Friction log (then stop)

1. Create `.agent/friction/<UTC yyyymmddTHHMM>-<skill>.md` with exactly this template. Use your file-editing tool; from PowerShell write it with `[IO.File]::WriteAllText((Join-Path $PWD '.agent\friction\<name>.md'), $text)` (UTF-8 without BOM). Never `Set-Content -Encoding utf8`, `Out-File` or `>`: Windows PowerShell adds a BOM or writes UTF-16.

```markdown
---
project: <state.project>
ticket: <state.active_ticket>
skill_in_use: <skill name>
type: ambiguity | loop | contradiction | tool-error | missing-info | contract
severity: blocker | friction | nit
model: <your model id>
---
## What I was doing
<1 sentence>
## Where I got stuck
<2 sentences max. Quote the ambiguous text or the exact `error:` line if any.>
## What I tried
<bullets: tool calls with args, max 5>
## What would unblock me
<1 sentence — a concrete input from a human>
## Proposed skill/instruction fix
<1 sentence — which SKILL.md line should change and how>
```

2. `ad-state set phase=blocked --question "<the unblock sentence>"` (skill `state-update`).
3. Print: `blocked — <unblock sentence>`. STOP. Do not continue the task. Do not retry.
