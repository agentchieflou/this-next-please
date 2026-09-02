# HANDOFF — for the Claude Code session that finishes this repo

> **2026-09-02 checkpoint:** the approved design for the next phase (Power BI PBIP/TMDL pipeline, `ad-setup` wizard, SQL dialect guardrails, Jira changelog + sprint replay, visual-level UAT) lives in `docs/plan-luna-pipeline.md`. Implement it in the slice order given there; slice 1 (`agentdata/config.py` + `ad-setup`/`ad-doctor`) comes first. All six slices are built (setup wizard, SQL guardrails, Jira changelog + sprint replay, PBIP projection/validator/editor, Desktop + DAX runner, UAT engine). Next: run `docs/windows-verification.md` on the laptop; each pasted failure becomes a fix PR with a reproducing test. Domain workflow skills started with `dpm-consumer-integration` (`agentdata/dpm/`, `ad-dpm`): the DPM → data_remediation_foundry_DPM_fork handoff contract; its builtin binding encodes assumptions listed in `skills/dpm-consumer-integration/references/dpm-contract.md` that must be confirmed against the real hand-back document.

Context: scaffold produced offline. Owner: Michael. Worker model in production: "Luna"
(GPT-5.x via Copilot in PyCharm, Windows). You are the architect/finisher.

## State of the scaffold
- [x] AGENTS.md, README, data-format-policy, project stub
- [x] `agentdata` package: AgentTable model, TOON encoder, policy engine, pncli + pandas connectors, `ad-*` CLI
- [x] Teradata/Oracle/Hive/Impala connectors: settings from `~/.agentdata/config.json` (ad-setup) or env vars; passwords via keyring; native or ODBC DSN
- [x] Skills: router, session-bootstrap, state-update, friction-log, data-adapter, jira-triage,
      teradata-query, hive-query, oracle-query, uat-jira-vs-teradata, bitbucket-pr, confluence-publish,
      pbi-deploy-te2, pbi-refresh-xmla (+refresh.csx), dax-studio-export, slurm-submit
- [x] `ad-setup` / `ad-doctor` (agentdata/setup/): pncli import, data sources with SELECT 1 + capability probes, Power BI tools/workspaces, project stub
- [ ] Discover exact pncli verbs for confluence write + bitbucket pr create (`pncli confluence --help`, `pncli bitbucket --help`) and pin them into those two skills. `pncli jira search --jql "<JQL>"` is confirmed.
- [ ] Run `gh skill publish --dry-run` (pytest is green per slice)
- [ ] Add `agentdata/connectors/spark.py` if a local Spark session exists on the laptop
- [ ] Stretch: Fabric item-definition deploy of PBIR/TMDL (docs/pbi-tools-parts.md), rename propagation TMDL↔PBIR (`ad-pbip rename`)

## Rules for you
1. Keep every SKILL.md < 120 lines. If it grows, split into a new skill.
2. No hedging language in skills. Imperative, numbered, explicit STOP/handoff at end.
3. Do not change the format policy thresholds without writing the reason in `docs/data-format-policy.md` changelog.
4. Never put a credential in any file. Connectors resolve creds at runtime only.
5. After each task: commit, push to `agentchieflou/this-next-please`.

## First commands
```bash
pip install -e ".[dev]" && pytest -q
pncli --help; pncli confluence --help; pncli bitbucket --help
```
