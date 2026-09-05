# The agent event contract

`~/.agentdata/fleet/<repo>/events.norm.jsonl` is the one thing every later slice reads. The
dashboard colours a tile from it, the notifier decides whether to interrupt you from it, the
approval gate records its decisions into it, and the weekly report counts from it. None of them
parse Copilot output, `state.json`, or friction files themselves.

That indirection is the point. The Copilot CLI is a third-party binary on a weekly release train;
when its JSONL changes, the change lands in one mapping function (`agentdata/fleet/events.py`)
rather than in four slices that each learned the shapes by hand.

Read it with:

```bash
ad-fleet events luna --since 40
```

## The envelope

Every line is one JSON object, one event, LF-terminated:

```json
{"schema": 1, "seq": 12, "ts": "2026-01-04T09:31:07", "repo": "luna", "ticket": "RDSD-118", "kind": "assistant_text", "data": {"text": "The measure is unused in every report page.", "model": "claude-haiku-4.5"}}
```

| field | meaning |
| --- | --- |
| `schema` | contract version. `1` today. Bumped only if a field's *meaning* changes, which is not planned. |
| `seq` | dense, 1-based, per repo. The cursor a reader stores. Never reused, never renumbered. |
| `ts` | UTC, second resolution, no zone suffix. For Copilot events it is the CLI's own timestamp with the `Z` stripped, so one clock runs the whole stream — stamping ours locally put 09:31 next to 05:08 on the same second of the same run. Order by `seq`, not by this. |
| `repo` | the registered name, not the path. |
| `ticket` | the active ticket at the time, or `""`. Stamped once, never back-filled. |
| `kind` | one of the catalogue below. |
| `data` | kind-specific, always an object, always redacted. |

### Three guarantees

**Additive only.** A kind may be added. A kind's meaning may not change and a field may not be
removed. Readers replay history, and history does not get rewritten.

**Idempotent.** `events.refresh()` records how far it has read into each source in
`events.cursor.json` — raw lines consumed, last `state.json` seen, friction files already turned
into events. Replaying the same inputs twice produces the same stream, not a doubled one. (The one
place this could have gone wrong is log rotation: when `supervisor._rotate` renames `events.jsonl`
to `.1`, the line counter is reset in the same breath, or the next refresh would skip the opening
lines of the new log.)

**Nothing credential-shaped.** `redact()` runs over every `data` payload before it is written, by
key (`token`, `password`, `api_key`, `client_secret`, …) and by value shape (`ghp_…`, `xoxb-…`, a
JWT). A tool result is arbitrary text from a command nobody here wrote, so the key alone is not
enough of a clue.

**Unknown kinds never raise.** A Copilot upgrade that adds an event type produces a `raw` event.
A reader that threw on an unfamiliar type would turn a routine `npm update` into a fleet outage.

## The catalogue

Three sources feed one stream.

### From the supervisor

**`started`** — `ad-fleet start` or `ad-fleet send` launched a process. The stream begins here, so
"never launched" is distinguishable from "launched and silent".

```json
{"schema": 1, "seq": 1, "ts": "2026-01-04T09:30:02", "repo": "luna", "ticket": "RDSD-118", "kind": "started", "data": {"pid": 24188, "prompt": "Work RDSD-118 end to end.", "resumed": false, "session": ""}}
```

### From the Copilot CLI's JSONL

Measured shapes; the raw catalogue is in [fleet-spike.md](fleet-spike.md). Ephemeral events (token
deltas, the model's own bookkeeping) are dropped and produce nothing.

**`turn_started`** / **`turn_ended`** — the boundaries a turn counter and "is it mid-thought" read.

```json
{"schema": 1, "seq": 2, "ts": "2026-01-04T09:30:04", "repo": "luna", "ticket": "RDSD-118", "kind": "turn_started", "data": {"turn": "0"}}
{"schema": 1, "seq": 9, "ts": "2026-01-04T09:31:40", "repo": "luna", "ticket": "RDSD-118", "kind": "turn_ended", "data": {"turn": "0"}}
```

**`assistant_text`** — a durable message. This is the narrative a person actually reads.

```json
{"schema": 1, "seq": 8, "ts": "2026-01-04T09:31:07", "repo": "luna", "ticket": "RDSD-118", "kind": "assistant_text", "data": {"text": "Branch pushed. Shall I open the PR?", "model": "claude-haiku-4.5"}}
```

**`tool_call`** / **`tool_result`** — what the agent ran and how it went. `arguments` is kept
because "which command did it try" is the first question asked of a stuck agent.

```json
{"schema": 1, "seq": 4, "ts": "2026-01-04T09:30:31", "repo": "luna", "ticket": "RDSD-118", "kind": "tool_call", "data": {"tool": "powershell", "id": "t1", "arguments": {"command": "ad-graph unused --json"}}}
{"schema": 1, "seq": 5, "ts": "2026-01-04T09:30:36", "repo": "luna", "ticket": "RDSD-118", "kind": "tool_result", "data": {"id": "t1", "ok": true, "error": "", "message": ""}}
```

**`denied`** — the agent tried a tool it is not permitted to run. Emitted alongside the failing
`tool_result`, never instead of it.

```json
{"schema": 1, "seq": 6, "ts": "2026-01-04T09:30:52", "repo": "luna", "ticket": "RDSD-118", "kind": "denied", "data": {"id": "t2", "message": "Permission denied and could not request permission from user"}}
```

**`session_id`** — the id `--resume` takes, so `ad-fleet send` can continue the conversation.

```json
{"schema": 1, "seq": 10, "ts": "2026-01-04T09:31:41", "repo": "luna", "ticket": "RDSD-118", "kind": "session_id", "data": {"session": "1f0a6c2e-4d1b-4a70-9a2e-6c9d3f8b0e11"}}
```

**`cost`** — premium requests. The CLI reports the **session total so far**, not an increment, so a
reader takes the maximum and never a sum. Adding checkpoints up would multiply the bill.

```json
{"schema": 1, "seq": 11, "ts": "2026-01-04T09:31:41", "repo": "luna", "ticket": "RDSD-118", "kind": "cost", "data": {"premium_requests": 1.33}}
```

**`exited`** / **`error`** — the process finished. Exit 0 is `exited`; anything else is `error`.
Both carry the files the run modified, which is what a diff-before-you-trust view needs.

```json
{"schema": 1, "seq": 12, "ts": "2026-01-04T09:31:41", "repo": "luna", "ticket": "RDSD-118", "kind": "exited", "data": {"exit_code": 0, "files_modified": ["reports/sales.Report/definition/pages/p1.json"]}}
{"schema": 1, "seq": 13, "ts": "2026-01-04T09:44:02", "repo": "luna", "ticket": "RDSD-118", "kind": "error", "data": {"exit_code": 1, "files_modified": []}}
```

**`raw`** — an event kind this build of the fleet has not been taught. Kept whole, so a reader can
see what arrived and the mapping can be extended without losing the history in between.

```json
{"schema": 1, "seq": 14, "ts": "2026-01-04T09:44:03", "repo": "luna", "ticket": "", "kind": "raw", "data": {"type": "session.compaction_started", "data": {"reason": "context"}}}
```

### From `.agent/state.json`

`ad-state` remains the only writer of `state.json`; the fleet only ever reads it. When the agent was
launched by a supervisor — both `AGENTDATA_FLEET_AGENT` and `AGENTDATA_FLEET_DIR` are set in the
child — `ad-state` also appends the change here, so a phase change shows up immediately instead of
on the next poll. Outside a fleet nothing is written but `state.json` itself, and a failure to emit
never fails the save.

**`phase_changed`**

```json
{"schema": 1, "seq": 15, "ts": "2026-01-04T09:32:10", "repo": "luna", "ticket": "RDSD-118", "kind": "phase_changed", "data": {"from": "triaged", "to": "optimizing"}}
```

**`question_opened`** — one per question added to `open_questions`.

```json
{"schema": 1, "seq": 16, "ts": "2026-01-04T09:33:01", "repo": "luna", "ticket": "RDSD-118", "kind": "question_opened", "data": {"question": "Does RDSD-118 cover the UAT workspace too?"}}
```

**`artifact`** — something was produced worth looking at.

```json
{"schema": 1, "seq": 17, "ts": "2026-01-04T09:35:20", "repo": "luna", "ticket": "RDSD-118", "kind": "artifact", "data": {"artifact": {"path": ".agent/artifacts/unused-measures.md", "what": "unused measures", "run_id": "", "added": "2026-01-04"}}}
```

**`pr_open`** — `pr_url` was set. The moment a human is genuinely needed.

```json
{"schema": 1, "seq": 18, "ts": "2026-01-04T09:40:55", "repo": "luna", "ticket": "RDSD-118", "kind": "pr_open", "data": {"url": "https://github.com/example/luna/pull/42"}}
```

### From `.agent/friction/`

**`friction`** — a skill hit something it could not resolve and wrote a STOP. The *What would
unblock me* sentence is lifted out, because that sentence is the whole reason the operator is being
shown this tile. The file is read through `textio`, so one written with a BOM or in UTF-16 by an
older PowerShell is the same event as a clean one.

```json
{"schema": 1, "seq": 19, "ts": "2026-01-04T09:36:44", "repo": "luna", "ticket": "RDSD-118", "kind": "friction", "data": {"file": "C:/work/luna/.agent/friction/20260104-jira-triage.md", "skill": "20260104-jira-triage.md", "unblock": "A decision on whether RDSD-118 covers the UAT environment."}}
```

### Reserved for the approval gate (#95)

**`needs_approval`** and **`approval_resolved`** are folded by the state machine already, so when
the gate lands it is a new writer and nothing downstream changes.

```json
{"schema": 1, "seq": 20, "ts": "2026-01-04T09:38:00", "repo": "luna", "ticket": "RDSD-118", "kind": "needs_approval", "data": {"what": "ad-pbip apply", "diff": ".agent/pending/rdsd-118.diff"}}
{"schema": 1, "seq": 21, "ts": "2026-01-04T09:39:12", "repo": "luna", "ticket": "RDSD-118", "kind": "approval_resolved", "data": {"what": "ad-pbip apply", "decision": "approved", "by": "operator"}}
```

## The state a tile shows

`agentstate.derive()` folds the stream into one answer. Deterministic, in this order — the first
rule that matches wins:

| state | when | what the operator sees |
| --- | --- | --- |
| `running` | a process is live, or a turn is open | working |
| `error` | the last turn exited non-zero | it fell over |
| `waiting_approval` | an unresolved `needs_approval` | one click needed |
| `blocked` | a `friction` event, or phase `blocked` | the unblock sentence |
| `needs_human` | a `denied`, an open question, or an assistant message ending in a question | what it asked |
| `done` | phase is `pr_open`, `done`, `closed` or `merged` | finished |
| `starting` | no events yet | just launched |
| `idle` | anything else | last turn ended clean |

Ordering is deliberate. An agent that is both blocked and has an open question is **blocked**,
because the friction log says what would unblock it and the question does not.

`needs_the_human()` is the single predicate the notifier and the dashboard badge share:
`waiting_approval`, `needs_human`, `blocked`, `error`.

## What is deliberately not here

**There is no permission-request event.** The plan for this slice assumed one. The spike found the
CLI does not emit anything of the kind: it attempts the tool, refuses it internally, reports
`error.code == "denied"` on `tool.execution_complete`, and the turn still exits 0. So `denied` is
the signal — and it is a better one, because it names the tool the agent wanted rather than a
generic prompt. Anything that waits for a request event will wait forever.

**No `needs_human` event.** That is a derived *state*, not a fact anyone observed. Emitting it as an
event would create a second source of truth that could disagree with the fold.

**No cost increments.** Only session totals, for the reason above.
