---
name: friction-log
description: Use the moment you second-guess yourself, repeat a tool call, hit ambiguous acceptance criteria, or get two failures in a row. Writes a structured entry for an offline architect model and STOPS. Never try to fix instructions yourself.
---
# Friction log (then stop)

1. Create `.agent/friction/<UTC yyyymmddTHHMM>-<skill>.md` with exactly this template:

```markdown
---
project: <state.project>
ticket: <state.active_ticket>
skill_in_use: <skill name>
type: ambiguity | loop | contradiction | tool-error | missing-info
severity: blocker | friction | nit
model: <your model id>
---
## What I was doing
<1 sentence>
## Where I got stuck
<2 sentences max. Quote the ambiguous text if any.>
## What I tried
<bullets: tool calls with args, max 5>
## What would unblock me
<1 sentence — a concrete input from a human>
## Proposed skill/instruction fix
<1 sentence — which SKILL.md line should change and how>
```

2. Invoke `state-update`: `phase=blocked`, `open_questions=[<the unblock sentence>]`.
3. Print: `blocked — <unblock sentence>`. STOP. Do not continue the task. Do not retry.
