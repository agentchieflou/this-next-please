# HANDOFF — for the Claude Code session that finishes this repo

Context: scaffold produced offline. Owner: Michael. Worker model in production: "Luna"
(GPT-5.x via Copilot in PyCharm, Windows). You are the architect/finisher.

## State of the scaffold
- [x] AGENTS.md, README, data-format-policy, project stub
- [x] `agentdata` package: AgentTable model, TOON encoder, policy engine, pncli + pandas connectors, `ad-*` CLI
- [~] Teradata/Oracle/Hive connectors: credential resolution stubbed with `TODO(data_czars)`
- [x] Skills: router, session-bootstrap, state-update, friction-log, data-adapter, jira-triage,
      teradata-query, hive-query, oracle-query, uat-jira-vs-teradata, bitbucket-pr, confluence-publish,
      pbi-deploy-te2, pbi-refresh-xmla (+refresh.csx), dax-studio-export, slurm-submit
- [ ] Wire `data_czars` keyring/Kerberos helpers into `agentdata/connectors/{teradata,oracle,hive}.py`
- [ ] Discover exact pncli verbs for confluence write + bitbucket pr create (`pncli confluence --help`, `pncli bitbucket --help`) and pin them into those two skills. `pncli jira search --jql "<JQL>"` is confirmed.
- [ ] Run `pytest tests/` and `gh skill publish --dry-run`
- [ ] Add `agentdata/connectors/spark.py` if a local Spark session exists on the laptop

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
