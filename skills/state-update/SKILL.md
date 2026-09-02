---
name: state-update
description: "Use immediately after any skill finishes a step, to record progress in .agent/state.json. The ONLY skill allowed to write state.json. Also use when the user asks \"where was I\"."
---
# State update

1. Read `.agent/state.json`.
2. Set fields that changed. Allowed keys and values:
   - `phase`: `idle | triaged | querying | validating | documenting | pr_open | blocked | done`
   - `active_ticket`, `branch`, `pr_url`, `confluence_url`: string or null
   - `artifacts`: append `{path, what, run_id}` for each `.agent/out/` file produced this step
   - `open_questions`: list of strings (empty unless blocked)
   - `last_updated`: ISO-8601 UTC now
3. Write the file. Keep it under 60 lines; drop `artifacts` older than 7 days.
4. Print one line: `state: phase=<phase> ticket=<ticket>`.
5. Return to `router`.
