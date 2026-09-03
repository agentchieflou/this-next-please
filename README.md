# this-next-please — Copilot orchestration for Luna

[![tests](https://github.com/agentchieflou/this-next-please/actions/workflows/tests.yml/badge.svg)](https://github.com/agentchieflou/this-next-please/actions/workflows/tests.yml)

Shared skills + credential-blind data adapter so a cheap Copilot model can run
several large projects at once without hand-maintained AGENTS.md sprawl.

## Install and update (once per laptop — never inside a project repo)

Two pieces, installed separately, and **both must move together**: the `ad-*` CLI (pip, from GitHub) and the skills
(`gh skill install`, into `~/.copilot/skills`). Updating one and not the other is the most common breakage — a skill
tells Luna to run a command the CLI does not have yet.

### Update — this repo changes often, so this is the part to know

```powershell
ad-update            # reinstall the CLI from GitHub + reinstall every skill, then tell you what changed
ad-update --check    # what you have right now: version, commit, skills dir, whether the skills look stale. Runs nothing.
```

Then **start a new Copilot chat** (skills are read when a chat starts) and run `ad-doctor` — followed by
`ad-setup --patch` if it reports anything. [`CHANGELOG.md`](CHANGELOG.md) says what changed and whether an
update needs anything beyond these two commands.

If `ad-update` does not exist yet — you are on a build from before it was added — run the two commands by hand, once:

```powershell
python -m pip install --force-reinstall --no-deps "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"
gh skill install agentchieflou/this-next-please --all --scope user
```

`--force-reinstall` is not optional: **pip will not reinstall a git URL whose version has not changed**, and the
version does not change on every commit, so a plain `pip install` prints *"Requirement already satisfied"* and you
keep the old code. `--no-deps` stops the update from re-downloading `teradatasql` and friends every time; use the
extras form instead when the release notes say a new optional dependency is needed:
`python -m pip install --force-reinstall "agentdata[teradata,odbc] @ git+https://github.com/agentchieflou/this-next-please.git"`.

### Did the update take?

```powershell
ad-update --check
```
- `version` / `commit` — the exact commit pip recorded for this install (from the `direct_url.json` metadata pip
  writes for git installs). Compare it with the newest commit on `main`. `ad-doctor` prints both in its `meta` too,
  so every session shows what it is running.
- `python` — the interpreter that owns the install. If that is not the Python you type `python` for, that mismatch is
  why an update "did not take": run the update with **that** interpreter, or use `python -m agentdata <command>`.
- `install` — how this copy got here: a *git install* (what a laptop should have), an *editable install*, or *running
  from a checkout*. For the last two, `ad-update` updates the skills and **skips the CLI half**: pip must not fight a
  clone you are editing. That is a skip, not a failure — `skipped[1]: cli`, and the row says what to run.
  `ad-update --pull` does `git pull --ff-only` in that clone instead; `ad-update --from-git` leaves the clone behind
  and installs the published version over it.
- `skills` / `skills_newest` / `stale_skills: true` — the skills are older than the CLI; run the `gh skill install`
  line and start a new chat.
- `gh skill install` refusing because a skill already exists → delete that folder under the printed `skills_dir` and
  re-run; `ad-update --check` shows the new timestamp.

### First install

```powershell
# 1. the skills  ->  ~/.copilot/skills, for every repo you work in
gh skill install agentchieflou/this-next-please --all --scope user

# 2. the ad-* CLI  ->  a normal Python tool, installed straight from GitHub (no clone needed)
pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"
#    with the extras you actually use:
#    pip install "agentdata[teradata,odbc,impala,oracle,pbi,uat] @ git+https://github.com/agentchieflou/this-next-please.git"

pncli config init      # if not done (pncli keeps the Jira token; we only borrow it by key name)
ad-setup               # guided: pncli import, data sources, Power BI tools/workspaces
ad-doctor              # any time: offline health check (session-bootstrap runs it)
ad-setup --patch       # after any fail row: re-asks ONLY the settings behind it, nothing else
```

**Skip the skill picker.** Without `--all`, `gh skill install` opens an interactive list whose first row is a
search box: pressing Enter there re-enters search instead of paging, so you have to arrow down one row before the
list will move. `--all` installs every skill and never shows the picker. `--scope user` puts them in your home
directory so they apply in every project repo (`--scope project`, the default, writes only into the current repo).
`--all` needs a recent `gh` (check with `gh --version`; it landed in cli/cli#13471). On an older CLI, either update it
or name the skills you want: `gh skill install agentchieflou/this-next-please router --scope user`, repeated per skill.

**Project repos install nothing.** `rdsd-pbi-reporting` and friends hold PBIP folders, TMDL and SQL — not Python.
Running `pip install -e ".[dev]"` there fails with *"neither 'setup.py' nor 'pyproject.toml' found"*, and that is
correct: the CLI is laptop-wide, like `git` or `pncli`. Per project you only run `ad-setup --project .`.

**If `ad-setup` is "not recognized as the name of a cmdlet"**, pip printed *Defaulting to user installation* and put the
console scripts in a folder Windows does not have on PATH. Either add it —
`python -c "import sysconfig;print(sysconfig.get_path('scripts','nt_user'))"` — or use the module form, which always
works and takes the same arguments: `python -m agentdata update`, `python -m agentdata setup`,
`python -m agentdata doctor`, `python -m agentdata pbip check`, `python -m agentdata --help`.

## Per project
```powershell
cd C:\repos\rdsd-pbi-reporting
ad-setup --project .        # writes AGENTS.md + .agent/state.json from the packaged stub, fills the facts it knows
#   Luna's form (no stdin): ad-setup --only project --non-interactive --offline --project . --set project.jira_project=RDSD
ad-state show               # session state; `ad-state set phase=… active_ticket=…` is the only way state.json is written
ad-doctor                   # what is broken · ad-setup --patch re-asks ONLY the settings behind the fail rows
ad-setup --patch sources.oracle   # or name a target: re-ask exactly that, without waiting for a check to fail
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
| `agentdata/textio.py` | reads files other tools wrote (UTF-8 BOM, UTF-16, cp1252 — what Windows PowerShell and Notepad produce); writes UTF-8 without BOM |
| `agentdata/proc.py` | starts other programs on Windows: PATHEXT + npm global prefix resolution, npm `.cmd` shims run as `node <script>` (no cmd.exe re-parsing) |
| `agentdata/update.py` | `ad-update`: reinstall the CLI + skills, and report the exact commit installed |
| `CHANGELOG.md` | what each version changed, and whether picking it up needs more than the two update commands |
| `agentdata/state.py` | `ad-state`: the only writer of `.agent/state.json` (validated keys and phases, clean encoding) |
| `agentdata/setup/` | `ad-setup` wizard and `ad-doctor` (step registry: pncli, sources, powerbi, project) |
| `agentdata/connectors/` | teradata / hive / impala / oracle (native or ODBC DSN), pncli, jira_api (Jira REST on pncli's token), keyring wrapper, probes |
| `agentdata/sqlcheck/` | dialect pre-flight lint (`ad-sql-check`, auto inside the query commands) |
| `agentdata/pbip/` | PBIP tooling: TMDL parser/lint/editor, PBIR loader, projection, model↔report validator, Desktop discovery, DAX runner (`ad-pbip`) |
| `agentdata/ui.py` | how the CLI looks to a person: panels, tables and status glyphs via `rich`, and off whenever a machine might be reading |
| `agentdata/confluence.py` | `ad-confluence`: Markdown → Confluence storage format (XHTML, code macro, entities), XML-validated before it is published |
| `agentdata/jira_workflow.py` | `ad-jira transition`: resolves "review"/"done" against the transitions Jira offers THIS issue — a Task and a Story have different workflows |
| `agentdata/uat/` | sprint replay, expected-value loader, tiered reconciliation (`ad-jira sprint-replay`, `ad-uat`) |
| `agentdata/dpm/` | DPM → consumer handoff contract: read-only run root, reference resolution, versioned refusals, job manifest with lineage (`ad-dpm`) |
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
