# The handoff: `.agent/in/<KEY>/`

The handoff is the channel through which an operator gives an agent what it needs to work a
ticket — a brief, a set of scope files, and attached reference documents — before or during a run.

Every piece of context lives inside the repository in one place:

```
<repo>/.agent/in/<KEY>/
  ├── brief.md        # the operator's own brief for this run
  ├── scope.toon      # table of files the agent is expected to inspect or edit
  └── <files>...      # copies of reference spreadsheets, exports, or extracts
```

## The five rules

Inherited directly from the inbox constitution (`agentdata/fleet/inbox.py`, #132). Every tool,
route, and shell that touches `.agent/in/` obeys all five:

1. **A copy, never a move.** The original file on disk (e.g. in `Downloads/`) remains untouched.
2. **Only into `<repo>/.agent/in/<KEY>/`.** Writes never land outside this folder or in arbitrary paths of the repo.
3. **Only on an explicit operator action.** A start button click, an attach button click, or a CLI command with explicit arguments. Never background crawling or speculative copying.
4. **Always an event.** Every addition emits a normalized event into the stream (`handoff.brief`, `scope.added`, or `inbox.attached`).
5. **`ad-state` is the only writer of `state.json`.** New files ask `ad-state set --input` to record them. No fleet code or shell writes `.agent/state.json` directly.

## Directory contents

### `brief.md`
Created when an agent is started with `--brief "<text>"` or when a dispatch card provides a brief.
Emits `handoff.brief {path, words, by}`.

### `scope.toon`
Contains the bounded list of files for the ticket in TOON tabular format:
```
scope[3]{path,why,by,at,how}:
  models/RDSD.SemanticModel/definition/tables/Velocity.tmdl,dropped on the tile,operator,2026-09-11T09:14,fingerprint
  reports/UAT.Report/definition/pages/p3.json,"answer to q4",operator,2026-09-11T09:20,ide
  .agent/in/RDSD-118/velocity-2026-08.xlsx,attached copy,operator,2026-09-11T09:20,attach
```
Emits `scope.added {paths, how, by, queued}`.

### Attached files
Files attached from the Downloads inbox (#132) or dropped on the tile and attached via `POST /api/attach-bytes`.
Emits `inbox.attached {name, dir, file, source, size}`.

## The `{handoff}` placeholder

`launch.DEFAULT_PROMPT` and custom `fleet.prompt_template` templates support an optional `{handoff}` placeholder.
When present, it expands to a concise sentence naming the handoff folder and what is in it:
`Context files and scope are available in .agent/in/<KEY>/ (brief.md, N scope files, M attached files). Read these first.`
If `.agent/in/<KEY>/` has no files, `{handoff}` expands to empty string, ensuring full backwards compatibility.
