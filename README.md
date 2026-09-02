# this-next-please — Copilot orchestration for Luna

Shared skills + credential-blind data adapter so a cheap Copilot model can run
several large projects at once without hand-maintained AGENTS.md sprawl.

## Install (once per laptop — never inside a project repo)

Two independent pieces, neither of which belongs to your report repos:

```powershell
# 1. the skills  ->  ~/.copilot/skills
gh skill install agentchieflou/this-next-please

# 2. the ad-* CLI  ->  a normal Python tool, installed straight from GitHub (no clone needed)
pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"
#    with the extras you actually use:
#    pip install "agentdata[teradata,odbc,impala,oracle,keyring,pbi,uat] @ git+https://github.com/agentchieflou/this-next-please.git"

pncli config init      # if not done (pncli keeps the Jira token; we only borrow it by key name)
ad-setup               # guided: pncli import, data sources, Power BI tools/workspaces
ad-doctor              # any time: offline health check (session-bootstrap runs it)
```

**Project repos install nothing.** `rdsd-pbi-reporting` and friends hold PBIP folders, TMDL and SQL — not Python.
Running `pip install -e ".[dev]"` there fails with *"neither 'setup.py' nor 'pyproject.toml' found"*, and that is
correct: the CLI is laptop-wide, like `git` or `pncli`. Per project you only run `ad-setup --project .`.

**If `ad-setup` is "not recognized as the name of a cmdlet"**, pip printed *Defaulting to user installation* and put the
console scripts in a folder Windows does not have on PATH. Either add it —
`python -c "import sysconfig;print(sysconfig.get_path('scripts','nt_user'))"` — or use the module form, which always
works and takes the same arguments: `python -m agentdata setup`, `python -m agentdata doctor`,
`python -m agentdata pbip check`, `python -m agentdata jira whoami`, `python -m agentdata --help`.

## Per project
```powershell
cd C:\repos\rdsd-pbi-reporting
ad-setup --project .        # writes AGENTS.md + .agent/state.json from the packaged stub, fills the facts it knows
```
- `AGENTS.md`  — ~25 lines of project facts, points at the installed skills
- `.agent/state.json` — machine-owned project state

## Developing this repo
```powershell
git clone https://github.com/agentchieflou/this-next-please.git
cd this-next-please
pip install -e ".[dev]"     # only here does `pip install -e` make sense
python -m pytest -q
```

## Layout
| Path | Role |
|---|---|
| `AGENTS.md` | canonical rules (short). Read HANDOFF.md first if you are Claude Code. |
| `skills/*/SKILL.md` | one job each; router dispatches to exactly one. `skills/*/references/` hold the long reference docs. |
| `agentdata/` | connector adapter: sources -> AgentTable -> TOON / TSV / JSON |
| `agentdata/config.py` | global config + project facts; every CLI resolves settings flag → env var → config → AGENTS.md |
| `agentdata/setup/` | `ad-setup` wizard and `ad-doctor` (step registry: pncli, sources, powerbi, project) |
| `agentdata/connectors/` | teradata / hive / impala / oracle (native or ODBC DSN), pncli, jira_api (Jira REST on pncli's token), keyring wrapper, probes |
| `agentdata/sqlcheck/` | dialect pre-flight lint (`ad-sql-check`, auto inside the query commands) |
| `agentdata/pbip/` | PBIP tooling: TMDL parser/lint/editor, PBIR loader, projection, model↔report validator, Desktop discovery, DAX runner (`ad-pbip`) |
| `agentdata/uat/` | sprint replay, expected-value loader, tiered reconciliation (`ad-jira sprint-replay`, `ad-uat`) |
| `docs/pbi-tools-parts.md` | what was learned from pbi-tools (AGPL) and re-implemented as behaviour |
| `docs/data-format-policy.md` | the determinant: which format, when |
| `docs/setup.md` | what the wizard configures, env overrides, Windows notes |
| `docs/windows-verification.md` | laptop-only verification runbook (pncli, Jira, drivers, TE2, dscmd, Desktop) with paste-back instructions |
| `docs/plan-luna-pipeline.md` | approved design for the Power BI / UAT / SQL-guardrail phase (implemented) |
| `prompts/remediate-from-friction.prompt.md` | offline frontier-model repair loop |
| `agentdata/templates/project-stub/` | the project stub `ad-setup --project` writes (ships in the wheel) |

## Data format contract (short form)
Full data always goes to disk (`.agent/out/`). Context gets TOON: inline if
small, header+sample+stats if medium, schema+sample if large. JSON only for
`--raw` debugging. See `docs/data-format-policy.md`.
