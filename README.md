# this-next-please — Copilot orchestration for Luna

Shared skills + credential-blind data adapter so a cheap Copilot model can run
several large projects at once without hand-maintained AGENTS.md sprawl.

## Install (once per laptop)
```powershell
gh skill install agentchieflou/this-next-please        # skills -> ~/.copilot/skills
pip install -e .                                        # agentdata CLI (ad-*)
pncli config init                                        # if not done
```

## Per project (2 files, copy from templates/project-stub/)
- `AGENTS.md`  — ~15 lines, points at the installed skills
- `.agent/state.json` — machine-owned project state

## Layout
| Path | Role |
|---|---|
| `AGENTS.md` | canonical rules (short). Read HANDOFF.md first if you are Claude Code. |
| `skills/*/SKILL.md` | one job each; router dispatches to exactly one |
| `agentdata/` | connector adapter: sources -> AgentTable -> TOON / TSV / JSON |
| `docs/data-format-policy.md` | the determinant: which format, when |
| `prompts/remediate-from-friction.prompt.md` | offline frontier-model repair loop |
| `templates/project-stub/` | what each project checkout adds |

## Data format contract (short form)
Full data always goes to disk (`.agent/out/`). Context gets TOON: inline if
small, header+sample+stats if medium, schema+sample if large. JSON only for
`--raw` debugging. See `docs/data-format-policy.md`.
