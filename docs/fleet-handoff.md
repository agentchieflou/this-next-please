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

`launch.DEFAULT_PROMPT` and any `fleet.prompt_template` support an optional `{handoff}` placeholder.
When the directory holds something, it expands to one sentence naming the directory and counting
what is in it:

```
 The operator left a brief and 2 files under .agent/in/RDSD-118/; read them before the ticket.
```

**A count and a directory, never the content.** The prompt stays one line, and a fleet that pasted
the brief into it would hand the agent a copy to trust instead of a file to read — the same reason
[fleet-intake.md](fleet-intake.md) gives for keeping acceptance criteria out of it.

When `.agent/in/<KEY>/` is empty, `{handoff}` expands to nothing, and a template written before the
placeholder existed keeps working unchanged — `_Blanks` makes an unknown field empty rather than an
exception, exactly as it does for `{summary}`.
