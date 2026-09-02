# this-next-please — Copilot orchestration for Luna

Shared skills + credential-blind data adapter so a cheap Copilot model can run
several large projects at once without hand-maintained AGENTS.md sprawl.

## Install (once per laptop)
```powershell
gh skill install agentchieflou/this-next-please        # skills -> ~/.copilot/skills
pip install -e ".[dev]"                                 # agentdata CLI (ad-*); add extras you need: .[teradata,odbc,impala,oracle]
pncli config init                                       # if not done (pncli keeps the Jira token; we only borrow it)
ad-setup                                                # guided: pncli import, data sources, Power BI tools/workspaces
ad-doctor                                               # any time: offline health check (session-bootstrap runs it)
```
`ad-setup` writes `~/.agentdata/config.json` (never a secret: passwords go to `keyring`, the Jira token stays in pncli's
file and is read by key name at call time). Re-run it any time; current values are the defaults. See `docs/setup.md`.

## Per project
```powershell
ad-setup --project C:\repos\MyReport        # writes AGENTS.md + .agent/state.json from templates/project-stub/, fills known facts
```
- `AGENTS.md`  — ~25 lines of project facts, points at the installed skills
- `.agent/state.json` — machine-owned project state

## Layout
| Path | Role |
|---|---|
| `AGENTS.md` | canonical rules (short). Read HANDOFF.md first if you are Claude Code. |
| `skills/*/SKILL.md` | one job each; router dispatches to exactly one. `skills/*/references/` hold the long reference docs. |
| `agentdata/` | connector adapter: sources -> AgentTable -> TOON / TSV / JSON |
| `agentdata/config.py` | global config + project facts; every CLI resolves settings flag → env var → config → AGENTS.md |
| `agentdata/setup/` | `ad-setup` wizard and `ad-doctor` (step registry: pncli, sources, powerbi, project) |
| `agentdata/connectors/` | teradata / hive / impala / oracle (native or ODBC DSN), pncli, jira_api, keyring wrapper, probes |
| `docs/data-format-policy.md` | the determinant: which format, when |
| `docs/setup.md` | what the wizard configures, env overrides, Windows notes |
| `docs/plan-luna-pipeline.md` | approved design for the Power BI / UAT / SQL-guardrail phase (in progress) |
| `prompts/remediate-from-friction.prompt.md` | offline frontier-model repair loop |
| `templates/project-stub/` | what each project checkout adds |

## Data format contract (short form)
Full data always goes to disk (`.agent/out/`). Context gets TOON: inline if
small, header+sample+stats if medium, schema+sample if large. JSON only for
`--raw` debugging. See `docs/data-format-policy.md`.
