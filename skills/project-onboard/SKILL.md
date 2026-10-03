---
name: project-onboard
description: "Use the first time an agent sees a repository (session-bootstrap invokes it), or when asked what a repository is for, how to get started, or to refresh the getting-started page. One bounded pass over ad-context's facts; writes the page under .agent/ and offers to commit it. Never reads the tree itself."
---
# Project onboard (one cheap pass, then hand back)

`ad-context build` has already read the tree: inventory, entrypoints, tests, reports and SQL, pages, git, and the
`AGENTS.md` facts it can propose. Your job is the sentences a person needs and the command cannot write. **The
budget is the page**: read `.agent/context/CONTEXT.md` and at most **2 files** it names (the README, one more),
each ≤ 200 lines. Never walk the tree, never run `ad-graph build` here (that is `codebase-map`, behind approval).

1. `ad-context status`. `stale: true` → `ad-context build`. Read `.agent/context/CONTEXT.md`. `ad-state set phase=researching`.
2. Fill the three `<!-- model -->` blocks **in that file**, nothing outside them, from the facts on the page:
   - *What this is*: two sentences -- what the repository is for, and who uses what it produces. From the README's own words; when the README says nothing, say so and name the strongest fact (a PBIP, the SQL tables, the console scripts).
   - *Layout*: one line per directory whose Role is blank, `dir/` -- what lives there, from its name and file counts. Unsure → `(unclear)`; never invent.
   - *First three things to do*: three numbered commands **copied from the page** (the test command, an entrypoint, `ad-pbip project` when a PBIP is listed, `ad-doctor`), each with what it proves.
3. Write `.agent/context/GETTING-STARTED.md`, ≤ 80 lines: the title, *What this is*, *Layout* (the table plus your lines), *Where to start*, *Tests*, *Data and reports*, *Already written down*, *First three things to do*. Copy the page's facts; do not restate what the README already says beyond the two sentences.
4. The `Facts for AGENTS.md` table has `missing` or `differs` rows → say so in one line naming each fact and its detected value. The operator records them (`ad-setup --patch` or an edit of `AGENTS.md`); never edit `AGENTS.md` yourself. No `AGENTS.md` at all → `session-bootstrap` step 1 already ran `ad-setup`; nothing more here.
5. `ad-state set --tool context_built=<today> --artifact .agent/context/GETTING-STARTED.md="getting started, from ad-context"`.
6. Offer the page, once, without stopping: `ad-state ask "Commit .agent/context/GETTING-STARTED.md as docs/getting-started.md?" --choice yes --choice no --assume no`. The operator answers `yes` (now or from the tile) → copy it to `docs/getting-started.md` on the current branch, commit `docs: getting started (ad-context)`, hand off → `bitbucket-pr`. Otherwise it stays under `.agent/`, where the next session reads it.
7. Print one line: `onboarded: <n> files · <languages> · tests: <cmd or none> · page: .agent/context/GETTING-STARTED.md`. Return to `router` (or to `session-bootstrap`, which invoked you on first sight).

Refreshing: the same steps. `ad-context build` keeps your sentences between the markers across a rebuild, so a refresh after the tree moved rewrites only what changed.
