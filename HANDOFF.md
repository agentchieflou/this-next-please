# HANDOFF — for the Claude Code session that finishes this repo

> **2026-10-09 checkpoint:** 0.19.0 (PR #657) shipped PBIR patching for Desktop 2.157, pncli as an optional backend with
> Jira over REST, the skills marketplace with a configurable source, and the world parked (its assets and knowledge
> moved to `agentchieflou/play-sports`, Track R). The next phase is the Microsoft 365 lane, `docs/plan-m365-bridge.md`:
> the coming Power Automate workspace as a second relay (the mobile lane's shape, generalised), SharePoint and OneDrive
> as on-demand context into `.agent/in/<KEY>/context/`, results out behind the approval gate, and the loop between
> triggered Microsoft agents and the fleet's Copilot agents. Slice M-0, the tenant sitting (§2 of the plan), comes first;
> nothing else starts without it. The same day 0.20.0 settled pncli (the operator's decision): pncli is required again
> and used directly, the wrapper and the duplicate REST reads are retired, and an `ad-*` command exists only where it
> extends pncli -- `ad-jira`, `ad-confluence publish`, `ad-git pr`, and the fleet's shim that refuses a pncli write.
>
> **2026-09-02 checkpoint:** the approved design for the next phase (Power BI PBIP/TMDL pipeline, `ad-setup` wizard, SQL dialect guardrails, Jira changelog + sprint replay, visual-level UAT) lives in `docs/plan-luna-pipeline.md`. Implement it in the slice order given there; slice 1 (`agentdata/config.py` + `ad-setup`/`ad-doctor`) comes first. All six slices are built (setup wizard, SQL guardrails, Jira changelog + sprint replay, PBIP projection/validator/editor, Desktop + DAX runner, UAT engine). Next: run `docs/windows-verification.md` on the laptop; each pasted failure becomes a fix PR with a reproducing test. Domain workflow skills started with `dpm-consumer-integration` (`agentdata/dpm/`, `ad-dpm`): the DPM → data_remediation_foundry_DPM_fork handoff contract; its builtin binding encodes assumptions listed in `skills/dpm-consumer-integration/references/dpm-contract.md` that must be confirmed against the real hand-back document.

Context: scaffold produced offline. Owner: Michael. Worker model in production: "Luna"
(GPT-5.x via Copilot in PyCharm, Windows). You are the architect/finisher.

## State of the scaffold
- [x] AGENTS.md, README, data-format-policy, project stub
- [x] `agentdata` package: AgentTable model, TOON encoder, policy engine, pncli + pandas connectors, `ad-*` CLI
- [x] Teradata/Oracle/Hive/Impala connectors: settings from `~/.agentdata/config.json` (ad-setup) or env vars; passwords via keyring; native or ODBC DSN
- [x] Skills: router, session-bootstrap, state-update, friction-log, data-adapter, jira-triage,
      teradata-query, hive-query, oracle-query, uat-jira-vs-source, bitbucket-pr, confluence-publish,
      pbi-deploy-te2, pbi-refresh-xmla (+refresh.csx), dax-studio-export, slurm-submit
- [x] `ad-setup` / `ad-doctor` (agentdata/setup/): pncli (required) and its config by key name, Jira's keyring fallback, data sources with SELECT 1 + capability probes, Power BI tools/workspaces, project stub
- [ ] Pin pncli's two write verbs on the laptop: read `pncli bitbucket --help` and `pncli confluence create-page --help`, then `ad-setup --only pncli --non-interactive --set pncli.verbs.pr_create="..."` (and `page_create`; `pr_update` / `page_update` for an update), and attach both help texts to #506. Until then `ad-git pr` and `ad-confluence publish` answer `not_pinned`, and the wrap-up says so. pncli is used directly for everything it does and an `ad-*` command exists only where it extends it (`docs/pncli-parts.md`, 0.20.0): `pncli jira search --jql "<JQL>"` and `pncli jira get-issue --key <KEY>` (confirmed on the laptop) are saved under `.agent/out/` and read with `ad-view`. `pncli confluence create-page --body <html>` is confirmed — the body is INLINE, so `ad-confluence publish` builds it from Markdown and hands it across as one argv element; `--space` / `--parent` / `--title` are still unconfirmed, which is why the template is the operator's. Jira transitions, comments and creates never need a pncli verb: `ad-jira` posts them over REST, gated. pncli is commander.js: **every argument is a named option, never positional**.
- [ ] Run `gh skill publish --dry-run` (pytest is green per slice)
- [ ] Confirm on the laptop, with `ad-pbi auth --probe`: Tabular Editor 2 accepts the token-carrying connection string
      (`Provider=MSOLAP;Data Source=powerbi://…;User ID=;Password=<token>`) as the server argument for both the load
      position and `-D`. That is what the Analysis Services client libraries document for an access token and what
      TE2's docs say about "server name or connection string"; it is built from those docs, not from a run. If the
      probe fails only in token mode (`AGENTDATA_PBI_AUTH=interactive ad-pbi auth --probe` passes after a manual TE2
      sign-in), the fix is one function, `agentdata/pbi/auth.connection_string` -- the `-L "" <token>` form is the
      fallback to try. Also record whether this build of `dscmd.exe` has any token/user/password switch
      (`dscmd csv --help`): if it does, service DAX can go back to dscmd behind `powerbi.tools.dscmd_caps`.
- [ ] Add `agentdata/connectors/spark.py` if a local Spark session exists on the laptop
- [ ] Stretch: Fabric item-definition deploy of PBIR/TMDL (docs/pbi-tools-parts.md), rename propagation TMDL↔PBIR (`ad-pbip rename`)

## Windows facts learned on the laptop (do not regress)
- Files written by Windows PowerShell 5.1 carry a UTF-8 BOM (`Set-Content -Encoding utf8`) or are UTF-16 (`>`): read every external file through `agentdata/textio.py`.
- npm-installed CLIs (pncli, az) exist only as `.cmd` shims. Never hand a bare name to `subprocess`; go through `agentdata/proc.py`.
- A cmd.exe command line must reach Windows as a STRING. As a list it goes through `list2cmdline`, which backslash-escapes the quotes, and cmd.exe answers "The filename, directory name, or volume label syntax is incorrect".
- Every failing check names the prompt keys that fix it (`Check.keys`), which is what makes `ad-setup --patch` surgical. Add keys to any new check.
- The fleet writes only under `~/.agentdata/fleet/` — except `fleet.mobile.folder`, which the operator names explicitly and which is never a repository (docs/fleet-mobile.md), and the cleanup guide, which on the operator's press commits, branches or stashes a dirty tree (never discards, never `.agent/`, never while its agent runs a turn; docs/fleet-map.md §Cleaning up dirty trees). A repository's `.agent/` is the agent's, and only `ad-state` writes `state.json` — `tests/test_fleet_e2e.py` walks four repositories after a run to prove it.
- A fleet shell (`ide/`) contains no rule logic. What a state means and when to interrupt someone are the server's; `tests/test_fleet_shells.py` enforces it.
- A new command needs three things or CI fails it: a `[project.scripts]` entry, a row in `__main__.COMMANDS` pointing at the same function, and an int return (never a bare `sys.exit` in the module form's path). `tests/test_entrypoints.py` also refuses any `ad-*` name mentioned in a skill or doc that is not installed.
- A doctor row must prove a tool *starts*, not that a file exists: `which` found `pncli.cmd` while the connector could not launch it.

## Rules for you
1. Keep every SKILL.md < 120 lines. If it grows, split into a new skill.
2. No hedging language in skills. Imperative, numbered, explicit STOP/handoff at end.
3. Do not change the format policy thresholds without writing the reason in `docs/data-format-policy.md` changelog.
4. Never put a credential in any file. Connectors resolve creds at runtime only.
5. After each task: commit, push to `agentchieflou/this-next-please`.
6. A coding agent developing this repository (not Luna) follows `docs/developing-with-agents.md` and `GEMINI.md`: one issue, one branch, one draft PR with the handover note.

## First commands
```bash
pip install -e ".[dev]"
pytest -q -n auto -m "not browser and not measured and not scale and not slow"   # the inner loop
pncli config init                                                                 # pncli's own config, once (npm install -g @kolatts/pncli first)
ad-setup --only pncli                                                             # its launcher, and the key names ad-jira borrows the token by
pncli --help; pncli confluence --help; pncli bitbucket --help                     # the verbs to pin for ad-confluence publish and ad-git pr
```
