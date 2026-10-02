---
name: state-update
description: "Use immediately after any skill finishes a step, to record progress in .agent/state.json through ad-state. The ONLY skill allowed to write state.json. Also use when the user asks \"where was I\"."
---
# State update

1. `ad-state show` (or `python -m agentdata state show`). It prints the state and one line: `state: phase=<phase> ticket=<ticket>`.
   A launcher that does not start (*Unable to create process*, *not recognized*): use `python -m agentdata state …` for state for the rest of the session, and never run the broken launcher again (AGENTS.md rule 11). A write to Jira, Confluence or Bitbucket has no such fallback: `friction-log` (`tool-error`), then STOP.
2. `ad-state set <key=value ...> [--artifact <path>=<what>]... [--clear-questions] [--tool <key>=<YYYY-MM-DD>]`. Allowed:
   - `phase=idle | triaged | querying | optimizing | validating | documenting | pr_open | blocked | done | closed | merged`
   - `active_ticket=`, `branch=`, `pr_url=`, `confluence_url=`: a string, or `null` to clear
   - `--artifact .agent/out/<file>=<what it is>` once per file produced this step (`--run-id <id>` from the TOON `meta`)
   - to ask: `ad-state ask "<what would unblock me>"`, never `--question` (it sets `phase=blocked` and gives the question an id, scoped to the active ticket; `--ticket <KEY>` names another). `--assume "<default>"` states a default and continues; `--followup` records an optional question that never stops anyone; `--want access` when a human must fix the environment (a denied tool, a missing executable)
   - to close one: `ad-state answer <id> "<text>"` records the reply; `ad-state supersede <id> "<instruction>"` closes a question the operator's newer instruction made moot; `--clear-questions` only when every question no longer applies -- it is recorded as cleared, not answered
   - `ad-state blocking [--ticket <KEY>]` lists only what stops that ticket's work; questions on other tickets are parked, not lost
   - `--tool doctor_verified=<date>` / `--tool pncli_verified=<date>`
   The command validates keys and phases, stamps `last_updated`, drops artifacts older than 7 days and writes UTF-8 without BOM.
3. `ok: false` → fix the key or value the `hint` names and re-run. Never write `.agent/state.json` any other way -- no editor, no `Set-Content`, no `ConvertTo-Json`. `ad-state` validates the phase and every key, and rejects one it does not know; a hand-written file reaches the next skill as a phase nothing understands.
4. Print the `state:` line the command printed. Return to `router`.
