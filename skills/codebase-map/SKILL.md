---
name: codebase-map
description: "Use to map an unfamiliar codebase, understand modules, hubs, entrypoints, and side effects. Generates understanding.md for human approval."
---
# Codebase map

Map the codebase using deterministic graph facts and synthesize an understanding document for human review.

CRITICAL: **never run `ad-graph approve` yourself**. Approval is reserved strictly for a human in an interactive terminal.

1. Run `ad-graph build` to ensure the code graph in `.agent/graph/` is fresh and matches current files on disk.
2. Run `ad-graph summary` to inspect overall directory structure, entrypoints, hubs, and potential cycles.
3. Run `ad-graph explain` to generate or refresh `.agent/graph/understanding.md` with factual skeletons.
4. For each Module row in `.agent/graph/understanding.md`, read at most the hub symbols' source via `ad-graph node <hub>` plus a bounded line slice of its `where` location. Write **one sentence** describing the role of that module and hub inside the `<!-- model --> ... <!-- /model -->` markers. Never restate facts the skeleton already carries.
5. Identify every place the graph reports `unresolved:` or `extractor: generic`, and record it under `## Open questions` as specific items the human reviewer must confirm.
6. Run `ad-state set phase=blocked --question "Review .agent/graph/understanding.md and run ad-graph approve"`.
7. Print `blocked — review .agent/graph/understanding.md, then run ad-graph approve`.
8. STOP.
