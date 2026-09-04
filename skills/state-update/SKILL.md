---
name: state-update
description: "Use immediately after any skill finishes a step, to record progress in .agent/state.json through ad-state. The ONLY skill allowed to write state.json. Also use when the user asks \"where was I\"."
---
# State update

1. `ad-state show` (or `python -m agentdata state show`). It prints the state and one line: `state: phase=<phase> ticket=<ticket>`.
2. `ad-state set <key=value ...> [--artifact <path>=<what>]... [--question "<text>"]... [--clear-questions] [--tool <key>=<YYYY-MM-DD>]`. Allowed:
   - `phase=idle | triaged | querying | validating | documenting | pr_open | blocked | done`
   - `active_ticket=`, `branch=`, `pr_url=`, `confluence_url=`: a string, or `null` to clear
   - `--artifact .agent/out/<file>=<what it is>` once per file produced this step (`--run-id <id>` from the TOON `meta`)
   - `--question "<what would unblock me>"` together with `phase=blocked`; `--clear-questions` once unblocked
   - `--tool doctor_verified=<date>` / `--tool pncli_verified=<date>`
   The command validates keys and phases, stamps `last_updated`, drops artifacts older than 7 days and writes UTF-8 without BOM.
3. `ok: false` → fix the key or value the `hint` names and re-run. Never write `.agent/state.json` any other way -- no editor, no `Set-Content`, no `ConvertTo-Json`. `ad-state` validates the phase and every key, and rejects one it does not know; a hand-written file reaches the next skill as a phase nothing understands.
4. Print the `state:` line the command printed. Return to `router`.
