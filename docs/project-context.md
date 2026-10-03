# Project context: the first session that sees a repository

The operator, 2026-10-03: *"the first time an agent sees a repository, no matter what the work is, that we have a way
for cheap to ingest that and create documentation from that so that a user could get started quickly."*

Two halves, split by cost. The **command** reads the tree and costs nothing: no model, no network, no credential, the
same `context.json` for the same tree. The **skill** spends one bounded pass on the sentences the command cannot
write, and hands back.

## `ad-context` — the facts

```
ad-context build [--root .] [--force]    .agent/context/{context.json, CONTEXT.md, meta.json}
ad-context status [--root .]             present? stale? (the file list or HEAD moved since the build)
ad-context show [--root .]               print CONTEXT.md
```

`build` is a file walk through the graph's own walker (`git ls-files`, the same excludes), a few regexes and three
`git` calls. It skips when the file list and HEAD are unchanged, and `--force` rebuilds. The page is built for a
reporting team's repositories as much as for a Python one: a checkout of PBIP, TMDL and SQL with no code still gets
a first page.

| Section of `CONTEXT.md` | From |
|---|---|
| What this is | the README's title and first paragraph |
| Layout | files per top-level directory, with the role of the ones whose name says it (`tests/`, `docs/`, `.github/`, …) |
| Languages | counts by extension |
| Where to start | `[project.scripts]`, `package.json` scripts, make targets, root scripts, `__main__`, containers, CI workflows |
| Tests | `agentdata/testing/detect.py`, the same detector `ad-test` runs |
| Data and reports | `.pbip` projects, TMDL model folders, SQL files and the tables they read most, notebooks, tabular files |
| Already written down | every page's title (two directory levels deep, twenty at most), and the convention files present |
| History | HEAD, the branch, local branch count, commits sampled and their span, the Jira keys the log and branches mention |
| Facts for AGENTS.md | `pbip_path`, `tmdl_path`, `test_cmd`, `jira_project`: recorded, detected, and whether they agree (fixtures under `tests/` are never proposed) |

Three `<!-- model -->` blocks sit in the page -- *What this is*, *Layout*, *First three things to do* -- exactly as
`.agent/graph/understanding.md` has them, and a rebuild keeps what was written between the markers.

## `project-onboard` — the sentences

`session-bootstrap` step 3 runs `ad-context status` every session and `build` when it is stale (seconds). The first
time -- `state.tools.context_built` unset -- it invokes `project-onboard` before the router, whatever the request
was. The skill reads `CONTEXT.md` and at most two files it names, fills the three blocks (two sentences on purpose,
one line per unnamed directory, three numbered commands copied from the page), writes
`.agent/context/GETTING-STARTED.md` (≤ 80 lines), stamps `context_built`, and offers once -- `ad-state ask … --assume
no`, so nothing stops -- to commit the page as `docs/getting-started.md` through `bitbucket-pr`. A `missing` or
`differs` row in the facts table is said in one line; the operator records the fact, never the agent.

Later asks ("what is this repository for", "getting started", "refresh the page") route through `code-router` to the
same skill. `codebase-map` is the deeper, code-only read behind `ad-graph approve`; this is the wide, shallow one
that runs before anything.

## Cost

The build: a file walk. On this repository, 1,115 files in under a second. The pass: one skill read, one page, two
files -- *cheap* in `docs/plan-routing-expansion.md`'s classes, and spent once per repository rather than once per
session, because `context_built` remembers it.

## Not here

- No model call in the command, ever. A sentence nobody can reproduce from the tree is the skill's, between markers.
- No write outside `.agent/` by the command, and by the skill only `docs/getting-started.md` on the operator's `yes`.
- No reading of file bodies beyond the README, packaging files, make targets, SQL `FROM`/`JOIN` names and page
  titles. The graph reads code; this does not.
