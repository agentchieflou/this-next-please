---
name: friction-log
description: "Use the moment you second-guess yourself, repeat a tool call, hit ambiguous acceptance criteria, or get two failures in a row. Writes a structured entry for an offline architect model and STOPS. Never try to fix instructions yourself."
---
# Friction log (then stop)

1. Create `.agent/friction/<UTC yyyymmddTHHMM>-<skill>.md` with exactly this template. Use your file-editing tool, or your shell's ordinary write -- pwsh `Set-Content` / `Out-File` / `>` and bash `printf > f` all produce UTF-8 without a BOM.

```markdown
---
project: <state.project>
ticket: <state.active_ticket>
skill_in_use: <skill name>
type: ambiguity | loop | contradiction | tool-error | missing-info | contract
severity: blocker | friction | nit      # REQUIRED. `nit` does not stop the agent; the other two do.
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

2. `ad-state ask "<the unblock sentence>"` (skill `state-update`). It sets `phase=blocked` and gives the question an id the operator can answer.
   If an `ad-*` launcher does not start (*Unable to create process*, *not recognized*), use `python -m agentdata state ask …` instead, and do not run the broken launcher again. For a write to Jira, Confluence or Bitbucket, do not look for another way: the type is `tool-error`, and the unblock sentence names the doctor's fix (`python -m agentdata doctor`, its `launchers` row) and says the operator's `ad-fleet wrapup <repo>` can make the write meanwhile.
3. Print: `blocked — <unblock sentence>`. STOP. Do not continue the task. Do not retry.
