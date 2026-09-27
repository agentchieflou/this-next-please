# The fleet on a phone: the mobile lane

The contract page for the mobile lane of [plan-mobile.md](plan-mobile.md): the path, the bridge folder, every record
the laptop writes and reads with its limits, the five lists, the `FleetDecide` flow, the settings, the verbs, the doctor
rows, the events and the refusals (#554, the plan's slice B10), then what IT is asked for (#571, slice V2). The code is
`agentdata/fleet/bridge.py`; where this page and the plan differ, this page is what the laptop does.
`tests/test_fleet_bridge.py::test_the_mobile_contract_documents_every_record_kind_every_setting_and_every_refusal_code`
reads this page for every record kind, `fleet.mobile.*` key, verb, `mobile.*` event and refusal code the code has.

## The path, and who talks to whom

```
LAPTOP (unchanged bind, unchanged token)            MICROSOFT 365                          PHONE / TABLET
the desk (serve) ── bridge thread, 5 s tick         OneDrive for Business                  Power Apps mobile (Intune APP)
  fleet_snapshot() ─► allow-list ─► scrub ─► outbox/ ─sync─► FleetAgent/outbox/* ─trigger─► FleetOutboxToLists (flow)
  approval.decide()  ◄── verify ◄── inbox/ ◄─sync─ FleetAgent/inbox/*  ◄─create─ FleetDecide (flow, Power Apps V2)
  supervisor.send|say()                                five lists ◄────────────────────── FleetAgent canvas app
                                                       push (Power Apps Notification V2) ─► the phone buzzes
```

The phone talks to Microsoft 365 and only to it. The laptop opens no socket and calls no host: its only network
traffic is the OneDrive sync client's, which already runs. The desk's bind, its run token and its two tokenless routes
are untouched ([fleet-dashboard.md](fleet-dashboard.md) §What is not here): the bridge is the one mobile path, and it
changes neither the bind nor the token model.

The loop is one function with two hosts (#550): a daemon thread of `ad-fleet serve` and `quickstart`, started after the
model refresh and stopped with the server, or `ad-fleet mobile watch` in the foreground on a laptop with no desk
running. Each pass, every `TICK_S` (5 s): the notification sweep (`serve.sweep_if_due`, shared with the desk's
streams), `export_once`, `apply_once`, and `prune` every 600 s. Each step is wrapped on its own, so a failure is a debug
line and the next step still runs. After a wall-clock jump (the laptop slept, or the clock was stepped back) one
heartbeat is written at once and nothing catches up.

## The bridge folder

`fleet.mobile.folder` has **no default** and is refused `mobile_folder_in_repo` inside any registered checkout, where
records would sit in front of the agent, or under the fleet directory. It is the one exception to "the fleet writes
only under `~/.agentdata/fleet/`" (`HANDOFF.md`, [fleet.md](fleet.md) §The repository belongs to the agent).
`config.expand` applies, so `%OneDriveCommercial%/FleetAgent` resolves when it is read.

```
<fleet.mobile.folder>/                       e.g. %OneDriveCommercial%/FleetAgent
  pairing.json                               ad-fleet mobile init, once: {schema, kind: "pairing", contract: 1, operator, laptop_id, expire_s, created}
  outbox/                                    the laptop writes; the phone side never writes here
    attention/<repo>-<seq>.json              one file per change of a repo's row digest
    approvals/<id>.json                      the request mirror, once
    approvals/<id>.decision.json             once, whichever side decided
    notifications/<at>-<repo>-<state>-<seq>.json
    heartbeat/<yyyymmdd-hhmm>.json           every 300 s
    results/<nonce>.result.json              the laptop's verdict on each phone decision or reply
  inbox/                                     FleetDecide writes; the laptop only moves what it applied or refused
    decision-<nonce>.json                    the name is advisory, the content authoritative
    reply-<nonce>.json
  processed/<name>, processed/<name>.result.json
  rejected/<name>,  rejected/<name>.why.json  {code, error, hint, at, nonce[, retried_s]}
```

Every name passes `bridge.safe_file_name`: `#` and `%` become `_`, a leading `~` is stripped, then `textio.safe_name`,
at most 120 characters, never empty. A path over 300 characters is a doctor `warn` (the OneDrive limit is 400 decoded
characters). Every write is `textio.write_json`: a `.tmp` sibling renamed into place, so the sync client never uploads
half a file. The laptop's own bookkeeping is `<fleet dir>/mobile.state.json` (the laptop id, the nonces seen, the
attention digests and sequence numbers, the approvals exported, the last export, inbox and heartbeat times), never in
the synced folder.

**Pruning**, every 600 s: after 24 hours, decided pairs (the request mirror with its decision), notifications,
results, heartbeats, and every attention file but each repo's newest; after 7 days, `processed/` and `rejected/`. A
request mirror with no decision beside it is never pruned, however old. Nonces are remembered for
`max(24 h, 2 × fleet.mobile.expire_s)`, and every `processed/` and `rejected/` sidecar names its nonce too, so the
replay guard outlives the state file.

## Why every record is immutable

The flow's trigger is OneDrive for Business **When a file is created (properties only)**. It sees a file once, does
not count a move as a new file, and the modified-file triggers can fire when nothing changed. So every record is a
new, uniquely named file that is never rewritten (MOB-D11): `attention/<repo>-<seq>.json` only when the row's digest
changes (the digest leaves out `digest`, `generated`, `seq` and `age_s`, which changes every second),
`heartbeat/<yyyymmdd-hhmm>.json` instead of one file replaced, and `results/<nonce>.result.json` per verdict.

## The outbox records

Every record is `schema: 1`, built key by key from `serve.fleet_snapshot()` or the approval files (an allow-list,
never a copy of a row with things taken out), and every free-text field is scrubbed (§What never leaves).

| kind | file | fields and limits |
|---|---|---|
| `attention` | `attention/<repo>-<seq>.json` | `repo ≤64, project ≤64, ticket ≤32` (a `KEY-123` shape or empty)`, state` (one of the fold's states)`, role ∈ running\|waiting\|human\|done\|idle, needs_human, says ≤300, last_said ≤200, age_s, at, generated, approvals` (≤8 ids of ≤96)`, approval_id` (the oldest)`, questions` (≤8 blocking ones: `{id ≤32, q ≤300, choices ≤8 × 80, want, default ≤80}`)`, run {n, origin, live, since_start, resumed}, model ≤64, spend {total, today, budget, turns, line ≤64}, supervised, external, digest, seq` — exactly `bridge.ATTENTION_KEYS`, the same rows `GET /api/attention` answers |
| `approval` | `approvals/<id>.json` | `id ≤96, repo ≤64, ticket ≤32, approval_kind, summary ≤300, payload_preview` (the payload redacted and scrubbed; over 8 KB canonical it becomes `{truncated, bytes, head ≤2 KB}`)`, payload_truncated, payload_bytes, digest` (64 hex, over the whole request)`, created, expires` (`created` + `fleet.approval_timeout`)`, waiting_s`. Never `pid`, never the raw `payload` |
| `decision` | `approvals/<id>.decision.json` | `id, decision, reason ≤500, by ≤254, via ∈ laptop\|mobile, decided, digest, late`, and `nonce` when `via` is `mobile`. Written once, whichever side decided |
| `notification` | `notifications/<at>-<repo>-<state>-<seq>.json` | `repo ≤64, ticket ≤32, state, severity ∈ action\|alert\|info, title ≤120, body ≤300` (scrubbed)`, seq, at, key = "<repo>:<state>", quiet, approval_id` (for `waiting_approval`). No URL, no tile link, no run token |
| `heartbeat` | `heartbeat/<yyyymmdd-hhmm>.json` | `at, every_s: 300, expire_s, contract: 1, operator, bridge` (`agentdata <version>`)`, laptop_id` (random hex, never a hostname or a pid)`, serve_up, desk_streams, counts {repos, needs_human, approvals_pending, notifications_24h, rejected_24h}, inbox_last_seen` |
| `result` | `results/<nonce>.result.json` | `nonce, kind_of ∈ decision\|reply, id` (a decision) or `repo` (a reply)`, ok, result ∈ applied\|rejected, code, error ≤500, hint ≤500, at`; a decision's `late`; a reply's `via ∈ say\|send`, `answered` (ids) and, after a `mid_turn` wait, `retried_s`. In the supervisor's or the bridge's own words |

`pairing.json` (the `pairing` record) is the one record outside `outbox/`: written once by `ad-fleet mobile init`, never
rewritten, and carrying no secret, only what the flow and the app need to know which laptop they talk to.

### What never leaves

Never exported, by construction: `path`, `pid`, `console`, `external_how`, `scope_report`, `trace`, `recent`, the
fleet directory, `server`, `theme`, `desk`, every `*_source` cell. The free text that does leave (`says`, `last_said`,
a question, a choice, an approval `summary`, the payload preview, a notification `body`, a reason) is the model's own
prose and can quote a hostname, a table or a row, so `bridge.Scrubber` removes, in order:

1. credential shapes (`events.redact()`);
2. every fact value of every registered project, except the link facts (`catalogue.LINK_FACTS`), as `<fact:key>`;
3. the desk's run token;
4. every checkout path, the fleet directory and the home folder, in every spelling, as `<path>`;
5. the user name and the machine name, as `<user>` and `<host>`;
6. UNC paths (`<unc>`) and drive paths (`<path>`);
7. `.agent/out/<dir>/<file>` reduced to `.agent/out/<file>`: the rows never leave (AGENTS.md rule 5), but the
   operator still learns which file an approval sends;
8. dotted hostnames other than the hosts of link-fact URLs, as `<host>`.

A deny-list built from the laptop's own facts first, then generic shapes, because an allow-list cannot be applied to
prose.

## The approval record

Every request carries `digest = sha256(canonical({id, kind, summary, payload, created, pid}))` (#543), and the
approval mirror carries it too. The phone sends the digest back; the laptop compares it with the request on disk, so
what the phone approves is the whole payload, never the preview. `approval.decide(..., by="mobile:<upn>",
digest=..., via="mobile", nonce=..., late=...)` writes the decision file with `digest`, `via` and `by`; a decision
naming another request's digest is refused, and an agent whose decision file carries a wrong digest is refused
`approval_denied` rather than released ([fleet-approvals.md](fleet-approvals.md)). `expires` lives on the phone's
decision (`issued` + at most `fleet.mobile.expire_s`), not on the request, whose window is `fleet.approval_timeout`; the
mirror's `expires` is that window's end. A decision applied after it is `late: true`: the agent had already timed out,
and the decision is recorded for the history.

## The inbox records, and the checks in order

`decision-<nonce>.json`: `{schema: 1, kind: "decision", nonce, issued, expires, by, id, digest, decision, reason,
device?}`. `reply-<nonce>.json`: `{schema: 1, kind: "reply", nonce, issued, expires, by, repo, message ≤4000 and/or
answers [≤8 × {id ≤32, answer ≤1000}], device? ≤64}`. A record is known by its `nonce`, never by its file name: the
sync client resurrects a file it was uploading and makes `<name>-<DEVICE>` copies, and either one is a replay.

Every `*.json` file in `inbox/` (not `~$` files), checked in this order; the first failure moves it to `rejected/`
with `<name>.why.json`, writes `results/<nonce>.result.json` when the nonce is readable, and emits `mobile.rejected`:

| check | code |
|---|---|
| the file is over 16 KB (`st_size`; it is never opened) | `mobile_too_large` |
| it is not JSON (`textio.read_json`: any BOM, cp1252) | `mobile_bad_json` |
| not an object, `schema` is not 1, or `kind` is not `decision` or `reply` | `mobile_bad_schema` |
| `nonce` is not 16-64 of `A-Z a-z 0-9 _ -`, or was already applied or refused | `mobile_replay` |
| `issued` is missing or more than 300 s ahead of the laptop | `mobile_bad_time` |
| not `now ≤ expires ≤ issued + fleet.mobile.expire_s` | `mobile_expired` |
| `by` is not `fleet.mobile.operator` (case-insensitive), or no operator is set | `mobile_wrong_operator` |
| a decision: no request with that `id` on this laptop | `mobile_unknown_id` |
| a decision: the request is already decided | `mobile_already_decided` |
| a decision: `digest` is not `approval.digest(request)` | `mobile_digest_mismatch` |
| a decision: `decision` is not `approved` or `denied`, or `reason`/`device` is not text | `mobile_bad_schema` |
| a decision: a denial with a blank reason | `mobile_reason_required` |
| a reply: `repo` is not registered on this laptop | `mobile_wrong_repo` |
| a reply: `message` over 4000, over 8 answers, a malformed answer, or nothing left to say | `mobile_bad_schema` |
| any file that fails unexpectedly the same way on two ticks | `mobile_unreadable` |

Only then does a decision reach `approval.decide()` (whose own refusals, a race lost after the checks, come back as
the matching `mobile_*` code), or a reply reach the supervisor. The nonce is recorded in the state file, the file moves
to `processed/` with its `<name>.result.json`, and the outbox gets `approvals/<id>.decision.json` or
`results/<nonce>.result.json`. **Every refusal fails closed:** no decision file is written, so the agent's own
`require()` loop times out and refuses the write. `force` is never read from the phone (MOB-D8).

**The UPN check is a misconfiguration guard, not authentication:** anyone who can write into the operator's OneDrive
folder can drop a decision with the right `by`, as [fleet-dashboard.md](fleet-dashboard.md) says of the loopback that
it is loopback security, not authentication; signed decisions are the plan's B12.

## Replies

A reply is the desk's `answer`, `say` and `send` verbatim. `answers` (the blank ones dropped, as the desk drops them)
become one `lifecycle.answers_prompt`; otherwise the stripped `message` is the text. A console the fleet opened is
typed into (`supervisor.say`, `via: say`); anything else is resumed headless (`supervisor.send`, `via: send`), never
with `force`. A `SupervisorError` is the verdict in its own words (`code`, `error`, `hint`), except `mid_turn`: the
phone cannot press Send again a minute later, so the file stays in `inbox/` and is tried every tick until its
`expires`, then refused `mid_turn` with `retried_s` (MOB-D7). The text reaches the agent exactly as typed; nothing of it
reaches the stream or the outbox (only the `answered` ids and a word count).

## Notifications

`notify.py`'s rules stay the only rules ([fleet-notifications.md](fleet-notifications.md)). `notify.send_mobile` is a
channel beside the toast inside `deliver()`: when `fleet.mobile.enabled` and `fleet.mobile.notify` are on, it writes one
`notification` record, and the drawer entry says `mobile: true`. It never raises. Quiet hours export the record with
`quiet: true`, and the flow decides not to push it. The push itself is content-free ("an agent needs you") and routes
by `screen`, `approvalId` and `repo`; the words appear only inside the app. **One sweep** (#549, MOB-D9): the desk's
streams and the bridge share one process-wide `sweep_if_due`, so the bridge sweeps when no window is open, and a desk
opened later finds those notifications in the drawer, not as fresh frames.

## The five lists and their columns

Five SharePoint lists (or, as the fallback, five tables in `FleetAgent.xlsx` on Excel Online), **all-text columns**:
ISO-8601 UTC timestamps, `true`/`false`, numbers as text, so one app serves both stores and every `Filter` on `=`
delegates. A single-line column holds 255 characters; the flow truncates `Summary`, `Reason` and `ResultText` in the row
while the files keep the whole text, and the long ones are *Multiple lines of text*.

| list | Title | columns | written by |
|---|---|---|---|
| `FleetAttention` | repo | `Project, Ticket, State, Role, NeedsHuman, Says` (multi)`, LastSaid, AgeSeconds, At, Generated, ApprovalId, ApprovalsJson, QuestionsJson` (multi)`, RunNumber, RunOrigin, RunLive, Model, SpendLine, SpendTotal, SpendToday, SpendBudget, Turns, Supervised, External, Digest, Seq` | `FleetOutboxToLists`, one row per repo, updated only when `Seq` is not older |
| `FleetApprovals` | approval id | `Repo, Ticket, ApprovalKind, Summary, PayloadPreview` (multi)`, PayloadTruncated, PayloadBytes, Digest, Created, Expires, WaitingSeconds, Status, DecidedBy, DecidedAt, Reason, Via, Late, Nonce, ResultCode, ResultText, SourceFile`; `Status ∈ pending\|sent\|approved\|denied\|rejected\|expired` | the flow (`pending` from the mirror, `approved`/`denied` from the decision mirror, `rejected` from a result, `expired` on `late`); `FleetDecide` sets `sent` |
| `FleetDecisions` | nonce | `Kind, ApprovalId, Repo, Decision, Reason, Message` (multi)`, AnswersJson` (multi)`, Digest, By, Device, Issued, Expires, InboxFile, Result, ResultCode, ResultText, ResultAt`; `Result ∈ sent\|applied\|rejected` | `FleetDecide` creates it `sent`; `FleetOutboxToLists` updates it from `results/` |
| `FleetNotifications` | key | `Repo, Ticket, State, Severity, TitleText, Body` (multi)`, At, Seq, Quiet, ApprovalId, SourceFile` | `FleetOutboxToLists`; its Catch scope adds one `alert` row per failed run |
| `FleetHeartbeat` | `laptop` | `At, EverySeconds, ExpireSeconds, Contract, Operator, Bridge, LaptopId, ServeUp, DeskStreams, Repos, NeedsHuman, ApprovalsPending, Notifications24h, Rejected24h, InboxLastSeen` | `FleetOutboxToLists`, one row updated |

Under Excel, a table has a single writer, so `FleetDecide` writes its own copy of `FleetDecisions` and the app reads
both. Every column's maximum and JSON source is in `mobile/data/README.md` §Columns per list (PR #535).

## `FleetDecide`, the only phone-to-laptop writer

A Power Automate flow with the **Power Apps (V2)** trigger and ten inputs, added in this order: `Kind` (`decision` or
`reply`), `ApprovalId`, `Repo`, `Decision` (`approved` or `denied`), `Reason` (required to deny), `Message`,
`AnswersJson` (`[{"id", "answer"}]`), `Digest` (64 lowercase hex), `ExpiresSeconds` (Number: the heartbeat's
`ExpireSeconds`, so the phone never claims longer than the laptop accepts; `0` means 900) and `Device`. Every input
but `ExpiresSeconds` is Text.

It validates the inputs, then composes `nonce` = `guid()` without dashes, `issued` = `utcNow()`, `expires` = `issued +
ExpiresSeconds`, and `by` = the `UserPrincipalName` of Office 365 Users **Get my profile (V2)**. That connection is
*Provided by run-only user*, so `by` is always the invoker's and never an input the app could fill. The flow creates
`inbox/decision-<nonce>.json` or `reply-<nonce>.json` with OneDrive **Create file**, adds the `FleetDecisions` row with
`Result = sent`, marks the `FleetApprovals` row `sent`, and answers **Respond to a PowerApp or flow** with four outputs:
`ok`, `nonce`, `inboxFile` and `error`. Its Catch scope answers `ok = false` with the error text, and a non-empty
`inboxFile` then means the file was written anyway. The build sheet is `mobile/flows/README.md` §Build sheet:
`FleetDecide` (PR #535).

## The contract, versioned

`contract/fleet-mobile.v1.schema.json` (JSON Schema draft 2020-12, #598) is this page as one file: every record above
by name in `$defs` (the outbox kinds, `pairing`, and the two inbox kinds `inbox_decision` and `inbox_reply`), `schema`
and `contract`, the `LIMITS` caps (`limits`, and each field's `maxLength`), the enums (states, roles, severities,
notification states, decisions), the five lists' columns and `FleetDecide`'s inputs and response. Its top-level
`contract` is `bridge.MOBILE_CONTRACT`; the heartbeat and pairing records carry the same number, so the app can say
"update the app". `contract/examples/` holds one record per kind (the flow samples of PR #535, moved there, plus the
pairing, a reply's result and the two inbox records); `contract/released/` holds the copy the last published tag
carries. After the split the phone side depends on this file, not on the Python package.

- **An additive change keeps the version**: a new optional field, a new enum value, a new record kind, a raised cap.
- **A breaking change raises `bridge.MOBILE_CONTRACT`** and moves the file to `fleet-mobile.v2.schema.json`: anything
  removed or tightened (a field, a kind, an enum value, a lower cap, a new required field, a narrower type, a new
  pattern).

`tests/test_mobile_contract.py` holds the laptop to it: the enums and caps equal their Python sources, every record the
bridge writes in its own tests validates as it is written (`tests/mobile_contract.py`), every example validates and
carries the producer's keys in the producer's order, and the breaking-change guard fails on anything removed or
tightened relative to `contract/released/` without a version bump.

## Settings

Five keys, none a secret, **none on the settings page** (`settings.EDITABLE`): each moves a human checkpoint (who may
approve from outside the laptop, and where records leave it), so they are set in `config.json` or with
`ad-setup --patch fleet.mobile`, which asks exactly these five ([setup.md](setup.md)).

| key | what | default | read |
|---|---|---|---|
| `fleet.mobile.enabled` | the bridge runs at all | `false` | at start |
| `fleet.mobile.folder` | the bridge folder, one OneDrive syncs, outside every checkout and the fleet directory | none, never defaulted | at start |
| `fleet.mobile.operator` | the UPN that may decide from the phone (`by`) | none | now |
| `fleet.mobile.expire_s` | how long a phone decision stays valid, clamped to 60-3600; not a number reads as 900 and the doctor warns | `900` | now |
| `fleet.mobile.notify` | the fleet's notifications go to the outbox too | `true` | now |

## Commands

`ad-fleet mobile status | init | export | apply | watch` ([fleet.md](fleet.md)); every refusal is exit 2 with its
code, through the fleet's `_refuse`.

- `ad-fleet mobile status`: the settings and folder facts (`folder_refused` names the code of a refused folder; a
  disabled bridge is described, not refused), the sync root, whether the folder is pinned, the last export and
  inbox times, whether serve and the bridge are running, then an `outbox{kind,files,newest}` table and the last 20
  `rejected{at,file,code}`. It reads only.
- `ad-fleet mobile init [--folder F] [--operator UPN]`: the eight directories and `pairing.json`, each only when
  missing (MOB-D6: `init`, not `pair`; no key exchange happens). `--folder` and `--operator` are saved only once the
  folder has passed the check.
- `ad-fleet mobile export [--dry-run]`: one export pass. `--dry-run` writes no record, no state and no event, and lists
  what it would write.
- `ad-fleet mobile apply [--dry-run]`: one pass over `inbox/`, one row per file (`applied`, `rejected`, `retried`).
  `--dry-run` runs every check and nothing else: no decision, no send, no move, no nonce recorded; the rows say
  `would_apply` or `would_reject`. A real `apply` beside a live `ad-fleet serve` is refused `mobile_serve_running`:
  two appliers could both send one reply.
- `ad-fleet mobile watch [--every S]`: the loop in the foreground, for a laptop with no desk running. Beside a live
  `ad-fleet serve`, which already runs it as a thread, it is refused `mobile_serve_running`: two sweepers would split
  `notify.state.json`'s one cursor.

## Doctor

Two rows ([fleet-lifecycle.md](fleet-lifecycle.md) §The doctor rows, [fleet.md](fleet.md)), from disk, file
attributes and the registry only, with no subprocess:

- `fleet/mobile`: `skip` when `fleet.mobile.enabled` is off; `fail` when the folder is unset, missing, cannot be listed,
  or inside a checkout or the fleet directory, or when its `inbox/` is online-only (hint `attrib +p "<folder>" /s /d`);
  `warn` when nothing says the folder syncs, the path is over 300 characters, the operator is not UPN-shaped,
  `expire_s` is not a number, or the folder outside `inbox/` is online-only; else `ok` with the five keys.
- `fleet/mobile traffic`: the last export, the last inbox file and the files rejected in 24 hours; `warn` when serve is
  up and nothing was exported for 5 minutes, or a file was rejected (the newest code in the hint).

## Events

Four kinds on the agent's stream ([fleet-events.md](fleet-events.md) §From the mobile bridge), additive: the fold
changes no state for any of them.

- `mobile.exported` `{id, digest, expires}`: a pending approval was mirrored, once per approval id.
- `mobile.decision` `{id, kind, decision, by, nonce, late}`: a phone decision was applied (`by` is `mobile:<upn>`).
- `mobile.rejected` `{nonce, kind, code, why}`: an inbox file was refused (`why` at most 200 characters, scrubbed), on
  the stream of the repo it names; a file naming none is in `rejected/` and the state file only.
- `mobile.reply` `{nonce, by, via, answered, words}`: a phone reply was said or sent; never the text.

## Refusals

Every row, and the test that proves it, is in [refusals.md](refusals.md) (Mobile inbox, Mobile bridge). The codes:

| code | where |
|---|---|
| `mobile_disabled`, `mobile_folder_unset`, `mobile_folder_in_repo` | the folder check before any pass, `init`, `export`, `apply` and `watch` (`test_fleet_bridge.py::test_a_folder_inside_a_registered_checkout_or_the_fleet_dir_is_refused_by_name`, `::test_a_folder_that_is_not_configured_is_refused_and_nothing_is_created`) |
| `mobile_serve_running` | `watch`, and a real `apply`, beside a live `ad-fleet serve` |
| `mobile_too_large`, `mobile_bad_json`, `mobile_bad_schema`, `mobile_replay`, `mobile_bad_time`, `mobile_expired`, `mobile_wrong_operator` | every inbox file (§The inbox records) |
| `mobile_unknown_id`, `mobile_already_decided`, `mobile_digest_mismatch`, `mobile_reason_required` | a decision; `digest_mismatch` is the gate's own code for the same fault ([fleet-approvals.md](fleet-approvals.md)) |
| `mobile_wrong_repo`, `mid_turn` | a reply; `mid_turn` only after the file waited out a turn until its `expires` |
| `mobile_unreadable` | a file that failed the same unexpected way on two ticks |

A reply the supervisor refuses keeps the supervisor's own code (`external_session`, `budget_exceeded`, ...).

## Staleness

The phone judges the laptop by its heartbeat alone: it is **not syncing** when `now - At > 3 × EverySeconds` on the
`FleetHeartbeat` row (15 minutes at the 300 s beat). A laptop that slept writes a heartbeat on its first pass awake,
so the rule clears as soon as that file has synced and the flow has updated the row.

## The IT ask

Nine asks, all of them standard Intune, Entra and Power Platform objects: no relay, no VM, no App Connector, no ZPA
segment, no custom connector and no Dataverse. The earlier report's relay needed twelve asks and a security review;
this lane replaces them (plan-mobile.md §Why this exists, *the path of least friction*). Each ask names the portal
path, the settings by the labels the portals print, the Microsoft Learn page it rests on, and why the fleet needs it.
IT decides every one of them; nothing here changes a policy.

**Licensing.** Microsoft Intune for the operator (the app protection policy, and *Available with or without
enrollment*); Microsoft Entra ID P1 for Conditional Access. No Power Apps premium on this path: every connector the app
and its flows use is a Standard connector under Microsoft 365 seeded rights. Premium becomes a question only if
Dataverse or a managed developer environment is ever used, and this lane uses neither.

**What a bystander sees.** The push on the lock screen is content-free by design: "an agent needs you", never a
repository, a ticket, a command or a payload. Intune's *Org data notifications* cannot redact a Power Apps push (ask 1),
so the fleet never puts anything in one that would need redacting. The words appear only inside the app, behind its
PIN.

### 1. App protection policy for Microsoft PowerApps (iOS/iPadOS, then Android)

- **Portal path.** Intune admin center > Apps > Protection > Create policy > iOS/iPadOS (then again for Android) >
  Apps > Select public apps > **Microsoft PowerApps**.
- **Settings.**
  - Data protection: *Send Org data to other apps* = **Policy managed apps**; *Restrict cut, copy, and paste between
    other apps* = **Policy managed apps with paste in**; *Encrypt Org data* = **Require**; *Restrict web content
    transfer with other apps* = **Microsoft Edge**; on Android *Screen capture and Google Assistant* = **Block**, on
    iOS *Screen capture* = **Block**.
  - *Org data notifications*: chosen knowingly, not by default. Power Apps mobile is not in the list of apps that
    honour it. On Android, **Block org data** on an app that does not support it means "notifications are blocked",
    so the phone gets no push at all; **Block** on an unsupported app means they are allowed. What #561 saw on an
    Android phone under *Block org data*: *not yet measured*. Until it is, the ask states the trade-off and leaves
    the value to IT: **Allow** on the Power Apps policy keeps the push, and the content-free push above is why that
    is safe; **Block org data** may silence every push on Android.
  - Access requirements: *PIN for access* = **Require**.
  - Conditional launch: *Jailbroken/rooted devices* = **Block access**; *Offline grace period* = **Wipe data**; *Min
    OS version* = the tenant's baseline.
- **Source.** [iOS app protection policy settings](https://learn.microsoft.com/intune/app-management/protection/ref-settings-ios);
  [Android app protection policy settings](https://learn.microsoft.com/intune/app-management/protection/ref-settings-android)
  (the *Org data notifications* row: "If not supported by the application, notifications are blocked");
  [Microsoft Intune protected apps](https://learn.microsoft.com/intune/app-management/ref-protected-apps) (Microsoft
  PowerApps: core settings, app configuration "No settings");
  [Data protection framework](https://learn.microsoft.com/intune/app-management/protection/data-protection-framework).
- **Why the fleet needs it.** The app shows approval summaries and what the agents said; the policy keeps them in a
  managed, PIN-locked, encrypted container and off screenshots.

### 2. App configuration for Power Apps on managed iOS devices

- **Portal path.** Intune admin center > Apps > Configuration > Create > Managed devices > iOS/iPadOS > targeted app
  **Power Apps** > Settings > *Use configuration designer*.
- **Settings.** Three String keys: `IntuneMAMUPN` set to Intune's user principal name token, `IntuneMAMOID` set to its
  user ID token, `IntuneMAMDeviceID` set to its device ID token, each in Intune's double-brace token syntax (the
  designer's own page spells them; this page does not, so nothing here reads as a literal value).
- **Source.** [Add app configuration policies for managed iOS/iPadOS devices](https://learn.microsoft.com/intune/app-management/configuration/configure-managed-ios);
  [How to create and assign app protection policies](https://learn.microsoft.com/intune/app-management/protection/create-policy)
  (§Device Management types; the 2409 release sends these three values automatically only to Excel, Outlook,
  PowerPoint, Teams and Word, not to Power Apps).
- **Why the fleet needs it.** On an enrolled iPhone, without `IntuneMAMUPN` the app is treated as unmanaged and the
  wrong policy, or none, reaches it.

### 3. Conditional Access for the phone

- **Portal path.** Microsoft Entra admin center > Entra ID > Conditional Access > Create new policy.
- **Settings.** Users: the operator (exclude the break-glass accounts). Target resources > Resources: **All resources
  (formerly 'All cloud apps')**, or the Power Platform audiences plus **Microsoft Flow Service**
  (`7df0a125-d3be-4c96-aa54-591f83ff541c`). Conditions > Device platforms: **iOS**, **Android**. Grant: **Require app
  protection policy** (and, for an enrolled phone, **Require device to be marked as compliant**) with **Require one of
  the selected controls**. *Enable policy*: **Report-only** first, then **On**. Not **Require approved client app**: its
  retirement moved from March to 30 June 2026, and since then policies that use it are read-only.
- **Source.** [Require approved client apps or app protection policy](https://learn.microsoft.com/entra/identity/conditional-access/policy-all-users-approved-app-or-app-protection);
  [Conditional Access: Grant](https://learn.microsoft.com/entra/identity/conditional-access/concept-conditional-access-grant);
  [Migrate approved client app to application protection policy](https://learn.microsoft.com/entra/identity/conditional-access/migrate-approved-client-app);
  [Configure identity and access management](https://learn.microsoft.com/power-platform/guidance/adoption/conditional-access)
  (Microsoft Flow Service is not in the **Office 365** target).
- **Why the fleet needs it.** The decision flow runs as the operator. If Microsoft Flow Service is left out while the
  apps are in, the app's call to the flow fails its token exchange and a tap on Approve does nothing.

### 4. The apps, published in Intune

- **Portal path.** Intune admin center > Apps > iOS/iPadOS (and Android) > Add.
- **Settings.** iOS store app **Power Apps** (App Store `id1047318566`, bundle `com.microsoft.msapps`); Managed Google
  Play **Power Apps** (`com.microsoft.msapps`); **Company Portal**; **Microsoft Authenticator**; **Microsoft Edge**.
  Assignment: **Required** for enrolled groups; **Available with or without enrollment** for a MAM-only phone.
- **Source.** [Add iOS store apps](https://learn.microsoft.com/intune/app-management/deployment/add-store-ios);
  [Add Android store apps](https://learn.microsoft.com/intune/app-management/deployment/add-store-android);
  [Assign apps to groups](https://learn.microsoft.com/intune/app-management/deployment/assign-groups);
  [Conditional Access: Grant](https://learn.microsoft.com/entra/identity/conditional-access/concept-conditional-access-grant)
  (the broker: Authenticator on iOS, Authenticator or Company Portal on Android).
- **Why the fleet needs it.** The policy protects only an app the phone has; the broker registers the device for
  Conditional Access; Edge is where the policy sends web links.

### 5. Environment and maker rights

- **Portal path.** Power Platform admin center > Manage > Environments; Power Apps > Apps > the app > Share.
- **Settings.** Which environment the app and its two flows live in (one user, confidential data: a named environment
  of the tenant's choosing, not a developer one); **Environment Maker** for the operator there; the app shared with the
  operator alone, permission **User**; sharing with *Everyone* off; the environment's sharing limits as IT sets them.
- **Source.** [Share a canvas app with your organization](https://learn.microsoft.com/power-apps/maker/canvas-apps/share-app);
  [Sharing limits in managed environments](https://learn.microsoft.com/power-platform/admin/managed-environment-sharing-limits);
  [Security roles and privileges](https://learn.microsoft.com/power-platform/admin/database-security) (Environment
  Maker).
- **Why the fleet needs it.** The operator imports the app and creates the flows; nobody else is meant to open it.

### 6. Data policy (DLP)

- **Portal path.** Power Platform admin center > Security > Data and privacy > Data policy (for the chosen
  environment, or the tenant policy that covers it).
- **Settings.** **Power Apps Notification** (v1 and v2), **SharePoint**, **OneDrive for Business**, **Microsoft 365
  Users** (the connector the plan calls Office 365 Users) and **Excel Online (Business)** in one group, **Business**.
  If an **advanced connector policy** (a strict allowlist) covers the environment, those connectors are on its
  allowlist, and no connector action control blocks the five actions the flows use.
- **Source.** [Connector classification](https://learn.microsoft.com/power-platform/admin/dlp-connector-classification)
  (all of these are in the list of connectors that can't be blocked by a classic data policy);
  [Advanced connector policies](https://learn.microsoft.com/power-platform/admin/advanced-connector-policies) (which
  can block them: a default-deny allowlist).
- **Why the fleet needs it.** A flow whose connectors sit in two groups is suspended; an allowlist without them stops
  the path without an error the phone can show.

### 7. Tenant isolation (a review item)

- **Portal path.** Power Platform admin center > Security > Identity and access > Tenant isolation.
- **Settings.** Confirm **Restrict cross-tenant connections** and its exceptions as they are. Nothing to change: the
  app, the flows, the lists and the OneDrive folder are all in the one tenant.
- **Source.** [Cross-tenant inbound and outbound restrictions](https://learn.microsoft.com/power-platform/admin/cross-tenant-restrictions).
- **Why the fleet needs it.** Only to have it on record that the path crosses no tenant boundary.

### 8. Zscaler (ZIA and ZCC)

- **Portal path.** ZIA admin portal > SSL inspection policy; ZCC app profile (and Intune, for a per-app VPN).
- **Settings.** SSL-inspection exemptions for Apple push, `*.push.apple.com` (Apple's `17.0.0.0/8`, TCP 5223, 443 and
  2197), and for Google push, `mtalk.google.com` and `fcm.googleapis.com` (TCP 5228–5230 and 443); the **Zscaler
  Recommended Exemptions** rule enabled; `*.wns.windows.com` bypassed for the laptop's OneDrive sync client; if the
  phone uses a per-app VPN on iOS, bound in the Power Apps assignment.
- **Source.** [Network endpoints for Microsoft Intune](https://learn.microsoft.com/intune/fundamentals/endpoints)
  (Apple and Firebase dependencies, which link to Apple's and Google's own port pages);
  [Configure the Jamf Cloud Connector](https://learn.microsoft.com/intune/device-security/conditional-access-integration/configure-jamf-cloud-connector)
  (the Apple `17.0.0.0/8` block over TCP 5223 and 443). The 2197 port and the FCM ports 5228–5230 are Apple's and
  Google's figures, taken from those linked pages: *unverified here*.
- **Why the fleet needs it.** An inspected push channel is a push that never arrives; the phone would learn about an
  approval only when the operator opened the app.

### 9. Teams, only if the Teams alert channel is ever used

- **Portal path.** Teams admin center > Teams apps > Manage apps; Intune admin center > Apps > Protection (the Teams
  policy).
- **Settings.** **Workflows** and **Approvals** allowed; the Teams app protection policy with *Org data notifications*
  = **Block org data**.
- **Source.** [Create flows in Microsoft Teams](https://learn.microsoft.com/power-automate/teams/teams-app-create);
  [Manage collaboration experiences in Teams for iOS and Android](https://learn.microsoft.com/intune/app-management/configuration/configure-teams-mobile).
- **Why the fleet needs it.** Not at all today: the push goes through Power Apps. This is the ask to make first if an
  alert ever goes through Teams instead.

### What Learn does not document

Marked as such, not asserted:

- **Power Apps mobile's Intune SDK version.** iOS *Screen capture* needs a minimum SDK; which one Power Apps ships is
  not on any Learn page: *unverified*.
- **The Conditional Access picker's display names** for the Power Platform audiences (the plan's list is by audience
  URL): *unverified*.
- **Zscaler's default exemption list.** help.zscaler.com did not render when the research was done, so whether the
  recommended exemptions already cover the push hosts is *unverified*.

## Runbook

What only the laptop, the tenant and a phone can answer is in
[windows-verification.md §Mobile](windows-verification.md#mobile-538-539-the-bridge-the-phone-and-the-tenant):
rows M1–M12, each *not yet measured* until the mobile sitting (#582) runs it. The round trip (M1) and push
latency (M10) set `fleet.mobile.expire_s` and the heartbeat; the snapshot's cost per tick (M5) decides
`TICK_S`.
