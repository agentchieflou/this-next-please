---
name: run-control
description: "Use to check, start, launch, resume, restart, stop or reconcile a long-running job or run the project owns (a DPM run, a batch, workers), with the project's own run commands. Status first, one control action, then proof that it took."
---
# Run control

Operational requests — *is it still running*, *resume the run*, *restart the workers*, *reconcile run
RUN-12* — are not UAT and not a ticket triage. This skill runs the project's own commands for them,
named in `AGENTS.md`, and never improvises one.

Inputs: the project facts `run_status`, `run_launch`, `run_resume`, `run_stop`, `run_reconcile` (each a
command line with `{run}` where the run id goes), and the run id the user named (`dpm_run_root` /
`dpm_runs_dir` say where runs live). The fact for the requested action missing → `ad-state ask "Which
command <action>s a run here?" --want value`, `friction-log` type `missing-info`. STOP.

1. **Status first, always.** Run `run_status` for the run. It is read-only, so it needs no word from
   anyone. Print one line: `run <id> · <state> · <pid or worker count> · last activity <time>`.
   A status request ends here: STOP.
2. **The action is the operator's word.** Launch, resume, restart, stop and reconcile change something
   real: run them only when this request asks for exactly that action on exactly that run. A request
   that only implies it ("it looks stuck") → `ad-state ask "<action> run <id>?" --choice yes --choice no`.
   STOP.
3. **Refuse a second copy.** Status says the run is already running → never launch or resume on top
   of it; print the status line and STOP. A stop request on a run that is not running is already done:
   say so, STOP.
4. **One invocation.** Run the action's command once. If it documents `--dry-run`, run that first and
   read it. Never retry the same command (AGENTS.md rule 11). A host refusal or a launcher that does
   not start is an environment error (router step 8), not a reason to try another spelling.
5. **Prove it took.** Exit 0 is not success. Run `run_status` again and compare it with step 1:
   a new pid or run id, a heartbeat or row count that moved, or the state you asked for. Unchanged
   after the command's own wait → the outcome is `indeterminate`: say exactly that, quote both status
   lines, `ad-state ask "Run <id> did not change after <action>: check it?" --want decision`. STOP.
   Never call an unproven action done.
6. **Writes the run makes are the run's.** A manifest or ledger the run writes (an `M:` drive file,
   `orchestrator.db`) is never edited by hand here, not even to "fix" a half-written one. A torn or
   missing manifest after a stop → `friction-log` type `contract` naming the file. STOP.
7. `state-update` with `--artifact` for any status file the commands wrote under `.agent/out/`. Print
   the before and after status lines. Hand off → `dpm-consumer-integration` when the user asked to use
   the run's output, else STOP.
