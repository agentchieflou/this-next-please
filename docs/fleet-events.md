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
`events.cursor.json` — a byte offset into each raw log, last `state.json` seen, friction files
already turned into events. Replaying the same inputs twice produces the same stream, not a doubled
one. (The one place this could have gone wrong is log rotation: when `supervisor._rotate` renames
`events.jsonl` to `.1`, the offset is reset in the same breath, or the next refresh would skip the
opening lines of the new log.) A cursor written before #188 counted lines; it is read once as an
offset, and a half-written last line is left for the next tick.

**Two raw sources, one catalogue (#188).** The fleet's own agents write their JSONL to the pipe
the supervisor redirected, `~/.agentdata/fleet/agents/<name>/events.jsonl`. A session in a console
the fleet did not pipe is read from Copilot's own file for it,
`~/.copilot/session-state/<id>/events.jsonl` (`COPILOT_SESSION_STATE` overrides the directory),
named by the lock — `kind: "console"` with a `session`, or an adopted lock's `session_file`. Both
go through `from_copilot` on the same fold tick, from their own offsets; a new session is a new
file and starts its offset over. Copilot's directory is read and never written.

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
"never launched" is distinguishable from "launched and silent". Grown at schema 1 with `new: true`
for unresumed/fresh starts, `session` populated on adopted starts when supplied by the store, and
optional `answers: [ids]` and `scope: n` from the handoff pipeline (#162).

```json
{"schema": 1, "seq": 1, "ts": "2026-01-04T09:30:02", "repo": "luna", "ticket": "RDSD-118", "kind": "started", "data": {"pid": 24188, "prompt": "Work RDSD-118 end to end.", "resumed": false, "new": true, "session": "", "answers": ["q1"], "scope": 3}}
```

**`said`** — `ad-fleet say` typed a line into the console the fleet opened for this checkout (#190).
The fleet's own act, recorded the way `started` records opening the window: the console echoes this
exact line, and whatever the session makes of it arrives on the same stream from Copilot's own file.
There is no second transcript.

```json
{"schema": 1, "seq": 12, "ts": "2026-01-04T09:32:10", "repo": "luna", "ticket": "RDSD-118", "kind": "said", "data": {"text": "use the staging connection string", "session": "0f1e2d3c", "pid": 24188}}
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
`exited` also carries `why` (e.g. `"the laptop slept"` when a process terminated during sleep).

```json
{"schema": 1, "seq": 12, "ts": "2026-01-04T09:31:41", "repo": "luna", "ticket": "RDSD-118", "kind": "exited", "data": {"exit_code": 0, "files_modified": ["reports/sales.Report/definition/pages/p1.json"], "why": ""}}
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

**`question_opened`** — one per question added to `open_questions`. Grown at schema 1 with
optional `id, choices, default, want, blocking, assume` beside `question`.

`question` keeps meaning exactly what it always meant — the sentence a person reads — so a reader
written before #165 keeps working. `id` is what an answer names; `choices` and `default` are what
the card offers; `want` is `decision | file | value`, which is how the card knows whether to show a
drop zone; and `blocking` is the difference between *stop* and *urge*. A question carrying `assume`
is one the agent stated and continued on, and it changes no state at all.

```json
{"schema": 1, "seq": 16, "ts": "2026-01-04T09:33:01", "repo": "luna", "ticket": "RDSD-118", "kind": "question_opened", "data": {"question": "Does RDSD-118 cover the UAT workspace too?", "id": "q1", "choices": ["yes", "no, production only"], "default": "yes", "want": "decision", "blocking": true, "assume": ""}}
```

**`question_answered`** — the operator answered one, and the agent may continue.

Emitted from the state diff exactly as `question_opened` is: `ad-state answer` moves the record out
of `open_questions` into `answered_questions`, which is where the answer's own text lives. A
question that merely *disappeared* — `--clear-questions`, or a human deciding it no longer applies
— is not an answer and is not reported as one.

```json
{"schema": 1, "seq": 17, "ts": "2026-01-04T09:41:12", "repo": "luna", "ticket": "RDSD-118", "kind": "question_answered", "data": {"id": "q1", "question": "Does RDSD-118 cover the UAT workspace too?", "answer": "yes, and the UAT workspace too", "by": "operator"}}
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
older PowerShell is the same event as a clean one. Grown at schema 1 with optional `severity: "blocker" | "friction" | "nit"`, which was in the
template from the beginning and read by nothing — so a `nit` somebody left for later stopped an
agent exactly as hard as a contradiction. The fold reads it now: `nit` does not fold as `blocked`;
`blocker`, `friction` and an absent line do, so an older file keeps behaving as it did.

```json
{"schema": 1, "seq": 19, "ts": "2026-01-04T09:36:44", "repo": "luna", "ticket": "RDSD-118", "kind": "friction", "data": {"file": "C:/work/luna/.agent/friction/20260104-jira-triage.md", "skill": "20260104-jira-triage.md", "unblock": "A decision on whether RDSD-118 covers the UAT environment.", "severity": "blocker"}}
```

### Reserved for the approval gate (#95)

**`needs_approval`** and **`approval_resolved`** are folded by the state machine already, so when
the gate lands it is a new writer and nothing downstream changes.

```json
{"schema": 1, "seq": 20, "ts": "2026-01-04T09:38:00", "repo": "luna", "ticket": "RDSD-118", "kind": "needs_approval", "data": {"what": "ad-pbip apply", "diff": ".agent/pending/rdsd-118.diff"}}
{"schema": 1, "seq": 21, "ts": "2026-01-04T09:39:12", "repo": "luna", "ticket": "RDSD-118", "kind": "approval_resolved", "data": {"what": "ad-pbip apply", "decision": "approved", "by": "operator"}}
```

### From the project's own systems (#131), and from the Downloads inbox (#132)

The four kinds above this line describe what the *agent* is doing. These describe what the
*project* is doing, polled read-only by the supervisor through the same `ad-*` paths a human would
run, and they exist so that a tab is opened to act and never to check. They travel the same stream
for one reason: #97's notification rules, its dedupe and its quiet hours already work on this
contract, so "the refresh you were waiting on finished" needs no second notification path.

**`project.ticket_changed`** — the ticket moved in Jira. One event per real change; polling it again
produces nothing.

**`project.refresh_finished`** — a dataset refresh ended. This is the toast that removes the
centre-monitor tab.

**`project.pr_merged`** — the pull request the tile links to was merged.

**`inbox.attached`** — a file the human clicked was copied into `<repo>/.agent/in/<KEY>/`. The one
write the fleet makes inside a repository's `.agent/`, and the reason it is an event is that it must
be as visible as everything else the operator did not type themselves.

```json
{"schema": 1, "seq": 22, "ts": "2026-01-04T09:41:30", "repo": "luna", "ticket": "RDSD-118", "kind": "project.ticket_changed", "data": {"key": "RDSD-118", "from": "In Progress", "to": "In Review", "assignee": "operator"}}
{"schema": 1, "seq": 23, "ts": "2026-01-04T09:42:05", "repo": "luna", "ticket": "RDSD-118", "kind": "project.refresh_finished", "data": {"dataset": "RDSD Crew Level Reporting", "status": "Completed", "ended": "2026-01-04T09:41:58"}}
{"schema": 1, "seq": 24, "ts": "2026-01-04T09:44:12", "repo": "luna", "ticket": "RDSD-118", "kind": "project.pr_merged", "data": {"url": "https://github.com/example/luna/pull/42", "by": "reviewer"}}
{"schema": 1, "seq": 25, "ts": "2026-01-04T09:45:01", "repo": "luna", "ticket": "RDSD-118", "kind": "inbox.attached", "data": {"name": "RDSD-118-export.md", "dest": ".agent/in/RDSD-118/RDSD-118-export.md", "from": "C:/Users/operator/Downloads/RDSD-118-export.md"}}
```

### From the handoff pipeline (#162)

**`question_answered`** — an operator answered an open question (`ad-fleet answer` or the tile's question card).
Carries `id, answer, by`.

```json
{"schema": 1, "seq": 26, "ts": "2026-01-04T09:45:10", "repo": "luna", "ticket": "RDSD-118", "kind": "question_answered", "data": {"id": "q1", "answer": "prod", "by": "operator"}}
```

**`handoff.brief`** — operator provided a brief at dispatch (`start --brief` or the pre-flight card).
Carries `path, words, by`.

```json
{"schema": 1, "seq": 27, "ts": "2026-01-04T09:45:15", "repo": "luna", "ticket": "RDSD-118", "kind": "handoff.brief", "data": {"path": ".agent/in/RDSD-118/brief.md", "words": 42, "by": "operator"}}
```

**`scope.added`** — file paths were added to the ticket scope (`POST /api/scope` or IDE shell).
Carries `paths, how, by, queued`.

```json
{"schema": 1, "seq": 28, "ts": "2026-01-04T09:45:20", "repo": "luna", "ticket": "RDSD-118", "kind": "scope.added", "data": {"paths": ["models/RDSD.SemanticModel/definition/tables/Velocity.tmdl"], "how": "fingerprint", "by": "operator", "queued": false}}
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
