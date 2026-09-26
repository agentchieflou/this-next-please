# Plan: mobile — the fleet on the operator's phone and tablet, by a folder the laptop already syncs, a canvas app the tenant already licenses, and a desk that fits a 390 px glass

_Status: PLANNED (2026-09-26) — epics MOB-S, MOB-B, MOB-F, MOB-P, MOB-D and MOB-V (issue numbers are filled in by the
filing session), under #91 (the fleet) and #122 (the desk). Written from the operator's two statements of 2026-09-26,
recorded verbatim in §Why this exists, from six research notes under `research_notes/Mobile fleet scope/` read whole,
and from the earlier report [reports/Intune phone access to agents.md](../reports/Intune%20phone%20access%20to%20agents.md).
Every code fact is at `0b9ec72`, which is `main` in this checkout; the board's `main` has moved by train 10 (#523),
and where that matters (the payload budget) both numbers are given. Nothing here was run on the laptop, the tenant
or a phone: what only they can answer is §Open questions, and the sittings in MOB-V read *not yet measured* until they
are run, as every desk plan since #145 has required. The path was settled before this was written and is stated as a
position, with its reason, not as an option._

## Why this exists

Two statements, read against the code:

| What the operator says | What the code does | Section |
|---|---|---|
| *We Have the capability of setting up a Microsoft Power App that can reach out phone* | Nothing can reach the laptop. `build()` binds `127.0.0.1` only (`serve.py:18-20`); `_authorized` refuses any peer outside `LOOPBACK` and then compares `?t=` in constant time (`serve.py:2637-2642`); a test pins the bind with "A dashboard on 0.0.0.0 is a fleet anyone on the corporate network can drive" (`tests/test_fleet_serve.py:88-98`). Any tunnel or proxy on the laptop makes every request a loopback peer, and `/open` then hands the run token to whoever asks (`serve.py:2713-2726`; the report §A tunnel in front of today's dashboard). So the phone must reach something else, and the laptop must dial out | §The model |
| *write to an FleetAgent.xlsx file* | The fleet writes JSON under `~/.agentdata/fleet/` and nowhere else (`HANDOFF.md:34`; `docs/fleet.md:252`; `tests/test_fleet_e2e.py` walks four repositories to prove it). An approval is two files, `<id>.json` and `<id>.decision.json` (`approval.py:105-111`, `238-241`); a notification is a line in `notifications.jsonl` capped at 200 (`notify.py:141-148`). No workbook exists and no code opens one | §The model |
| *manage approvals and denials* | `require()` returns APPROVED on **any** decision file for its id with no check that it matches the request it wrote (`approval.py:121-132`); `by` is the deciding process's `USERNAME` (`approval.py:246-247`) and neither the web route (`serve.py:2176-2179`) nor the CLI (`cli_fleet.py:1761-1772`) passes another; the id carries 16 random bits (`approval.py:77-80`); there is no digest and no expiry. Today the whole proof of an approval is that the click happened on this machine. A phone breaks that premise | §Slices, MOB-S |
| *It can probably be extended in depth* | A reply is `act("answer")`, `act("say")` or `act("send")` (`serve.py:2040-2065`, `2139-2161`): `supervisor.send` refuses a console or adopted session, a turn in progress, an exhausted budget and a missing session (`supervisor.py:542-597`); `say` types one line into a fleet-opened console by pid (`supervisor.py:680-705`). An approve comment is stored as `reason` and reaches the agent nowhere: `approval_resolved` carries no `reason` (`approval.py:126-127`) and the gated commands read only `.ok` (`cli_jira.py:229-236`, `316-321`; `cli.py:141-146`) | §The model |
| *It is the path of least friction* | Every connector this path uses is Standard class under Microsoft 365 seeded rights (`powerapps_yaml.md` KQ11; `flows_and_onedrive_bridge.md` Q11). The earlier report's dream state needs a relay VM, an App Connector group, a ZPA segment, an access policy, Conditional Access and ZCC on the phone: twelve IT asks (report §What IT is asked for) | §Prior art |
| *we now need to fully scope out mobile compatibility with the fleet … in all formats (phone and tablet) so that things look right* | Measured at 390×844: the row overflows sideways, 466 px in a 390 px grid, 1,026 px after the `all` preset; the open pane is `compact` at 160 px; 24 of 30 visible targets are under 44 px; every input is 13 px. At 844×390 the reply row sits at y = 599 in a 390 px, non-scrolling `#grid`. At 820×1180 and 1180×820 the default desk works and `all` overflows (`desk_mobile_audit.md` §7 table, `shots/`). The causes are five lines: `body { height: 100vh }` (`app.css:87-95`), `#grid { overflow-x: auto; overflow-y: hidden }` (`app.css:332-340`), `touch-action: none` on heads and rails (`app.css:624`), a viewport meta of `width=device-width, initial-scale=1` and nothing else (`index.html:5`), and no `pointer: coarse` rule anywhere under `static/` | §The desk at phone and tablet widths |
| *For the Power App side, you can scope out all the YAML's needed to be fed to create the full Power App (don't cut corners here as making Power apps manually is stupidly annoying)* | A `.pa.yaml` is one document with five optional keys, `App`, `Screens`, `ComponentDefinitions`, `DataSources`, `EditorState`, and `additionalProperties: false` (`powerapps_yaml.md` KQ1). Code view pastes controls **and whole screens** since 3 March 2025 (KQ7). What cannot be YAML by Microsoft's own schema and plugin: data-source connections ("must be added through the Power Apps Studio interface", KQ6), the three display settings (KQ3) and the theme, which is a separate `Themes:` document pasted through the Themes pane (KQ4) | §The Power App |
| *take an already working product that is currently being improved* | `main` is at 202,333–202,537 B of a 204,800 B payload budget; decision 18 refuses to raise it and held #510 over by 2,642 B; #523 (decision 19) strips comments at serve time and brings the served figure to ~117–123 KB (`desk_mobile_audit.md` §5). `desk-page`, `settings-page` and `serve` are sequenced lanes, `ink-core` is exclusive, `ci` and `relay` are frozen (`.github/agent-lanes.json`) | §Build order |
| (the notifications the phone needs) | Only a desk's SSE stream sweeps: "With only such pages open nothing sweeps, as when no window is open" (`serve.py:2458-2462`; `docs/fleet-dashboard.md:533-538`). The moment a phone matters is exactly when no window is open. And the written decision is "Mobile is out" (`docs/fleet-notifications.md:137-138`) | §The model |

**The purpose is the same as #122's: the operator's attention, now away from the laptop.** A glance at the phone
should say *who needs me*, one tap should approve or deny exactly what the agent will send, and one line typed on the
phone should reach the agent. Nothing about the laptop's own security should change to get that.

## Where this plan pushes back, and what it does instead

1. **"Reach out phone."** The phone never reaches the laptop and the laptop never listens. The path is laptop →
   OneDrive-synced folder (outbox) → Power Automate flow → five Microsoft Lists → Power Apps canvas app → Power
   Automate flow `FleetDecide` → OneDrive inbox → the laptop applies. The phone talks to Microsoft 365, never to the
   laptop. The desk stays bound to `127.0.0.1` with its token model unchanged; nothing is tunnelled. The report's
   ZPA-published relay is *later* (it needs IT); Copilot CLI remote control is a side track for consoles only
   (MOB-V4); the Teams and Outlook loops are documented alternatives, not built.
2. **"An FleetAgent.xlsx file."** The store is five SharePoint lists, not the workbook. Excel Online (Business) has
   no automated row trigger, locks a file for up to 6 minutes after the connector touches it, warns against writing
   from two clients at once, caps a workbook at 25 MB, takes up to 30 s to show a write and lags on filtered reads
   (`flows_and_onedrive_bridge.md` Q3). A list gives server-stamped `Created By`, 600 calls per minute, an automated
   trigger and delegable filters. The workbook survives as **both** the "Create a list → From Excel" source and the
   Excel fallback store, so the operator's file exists and the choice is reversible (MOB-D12).
3. **"All the YAMLs."** Everything the schema can hold is written as YAML in `mobile/powerapp/src/`. The four things
   the schema cannot hold — connections, display settings, the theme, and the `@version` suffixes Studio assigns — get
   an exact click sheet in `mobile/powerapp/NOTES.md`, one line per click, and P1 replaces the sheet's guesses with
   what Studio returned. That is the corner YAML cannot cut, named rather than hidden.
4. **Approval integrity first.** Card S1 lands before any phone code: a `digest` on the request, `via`, `by`,
   `expires` on the decision, and the approve comment delivered to the agent. It helps the desk too: today a decision
   file binds to nothing the operator saw (the report §Conclusion).
5. **One app, Tablet format.** Not a phone app and a tablet app. Learn's own recommendation for an app that must
   serve phone, tablet and web is Tablet format with auto-layout containers and the three display settings off
   (`powerapps_yaml.md` KQ3; `mobile_ux_requirements.md` Power Apps Q1). Two apps would be two source trees kept in
   step by hand (MOB-D14).
6. **The desk is made to fit, not replaced.** A CSS stack mode at 640 px and under delivers glance, approve, answer
   and reply for 3–5 KB of stylesheet inside the existing components; a separate `/m` page is ~10.5 KB gzipped, a
   second copy of the desk's rules, and blocked by the budget until #523 merges (`desk_mobile_audit.md` §12). `/m`
   is the last desk card, not the first.
7. **The push says nothing.** The push `Message` is content-free ("An agent is waiting for your approval"); ids
   ride in `Parameters`. Power Apps mobile is not in Intune's table of apps that honour *Org data notifications*, so
   the OS shows whatever the flow sends (`notifications_intune_powerapps.md` KQ1, KQ2). `info` notifications are
   not relayed by default (MOB-D13).
8. **A heartbeat every 300 s, not 60 s, and every record immutable.** Each outbox file is one flow run of ~6
   Power Platform requests against a Microsoft 365-seeded owner's 6,000 requests per 24 h. At 60 s the heartbeat
   alone is 1,440 runs × 6 = 8,640 requests, over the budget; at 300 s it is 288 × 6 = 1,728
   (`flows_and_onedrive_bridge.md` Q11). And the OneDrive *created* trigger ignores modified and moved files (Q1),
   so a same-name rewrite would never reach the phone: every record is a new, uniquely named file.

## What is reused

- **`textio.write_text`** (`textio.py:218-238`): UTF-8 without BOM, LF, a `.tmp` sibling and `os.replace`, with the
  documented in-place fallback (`textio.py:182-215`). It is exactly the writer a synced folder wants, and `.tmp`
  files are not synced (`flows_and_onedrive_bridge.md` Q8). **`textio.read_json`** BOM-sniffs UTF-8/16/32 and falls
  through cp1252 (`textio.py:43-63`), which covers anything a flow or Notepad writes. **`textio.safe_name`**
  (`textio.py:127-139`) plus `#`/`%`/leading `~` for OneDrive.
- **`approval.decide` and `require()`** (`approval.py:121-132`, `219-243`): the phone's decision is applied by the
  same function the desk and the CLI call, with two new keyword arguments.
- **`act("answer")`'s branching** (`serve.py:2139-2161`): console live → `supervisor.say`, else `supervisor.send`,
  with `lifecycle.answers_prompt` (`lifecycle.py:47-59`). The phone's reply maps onto it verbatim.
- **`notify.deliver()`** as the channel point (`notify.py:254-276`): whichever caller swept, each item passes here
  once. **"Downgrade, never suppress"** (`notify.py:21-22`): quiet hours export the record with `quiet: true`.
- **`fleet_snapshot()`** (`serve.py:480-698`), the one read every desk window makes, never a second fold: the
  shells rule (`HANDOFF.md:35`; `tests/test_fleet_shells.py:83-98`).
- **The tile allow-list and its reason** (`serve.py:1763-1776`): "a Teradata hostname on a tile is a leak the moment
  the operator screenshots the dashboard. Not a `looks_secret()` call". `LINK_FACTS` (`catalogue.py:450-452`) and
  the leak test with its four `SITE_FACTS` (`tests/test_fleet_board_desk.py:46-49`, `138-169`, `186-194`).
- **`_refresh_models`** (`cli_fleet.py:1689-1695`): a per-server thread started from `cmd_serve` and
  `cmd_quickstart`, never from `S.build`, ending on `server.stopping`. The bridge thread is that pattern.
- **`Check.keys` and `ad-setup --patch`** (`setup/wizard.py:46-63`, `260-296`); the notify rows as the model for
  keyed doctor rows (`setup/steps/fleet.py:658-707`); the `scandir` probe because `os.access` lies about a redirected
  OneDrive folder (`setup/steps/fleet.py:148-166`).
- **`_emit`/`_refuse` and TOON** (`cli_fleet.py:37-52`); the `notify` verb's shape (`cli_fleet.py:2048-2052`).
- **The events contract** (`events.py:33-67`; `docs/fleet-events.md:38-39`): kinds are additive, every kind has a
  sample line, `data` is redacted (`events.py:187-190`). `Fold.add` ignores unknown kinds (`agentstate.py:64-159`).
- **The `w=` window record** (`serve.py:1592-1639`; `docs/desk-window.md:110-147`): `?w=phone` gets its own
  `open`/`widths`/`section` for free, and `pageUrl` carries `w`, `shell`, `ink` between pages (`common.js:18-37`).
- **The three-tier pane and `data-tier`** (`app.js:5053-5071`; `docs/desk-window.md:96-104`): a 374 px pane on a
  390 px phone is `full` by the rule that already exists. The head's container queries (`app.css:392-397`).
- **Pointer-event drags with `pointercancel`** (`app.js:3621-3744`, `4806-4824`), `transitionLayout`
  (`app.js:3825-3864`) and the 320 ms ceiling (`docs/desk-motion.md:13-36`).
- **The ink gate** (`ink.js:91-116`): `?ink=off` always off, `unmeasured` off, one more branch fits.
- **The 15 s SSE `tick`** (`serve.py:2608-2612`), the `pagehide` snapshot in `sessionStorage` and `restoreCached`
  (`app.js:1569-1634`), and the map's narrow test at 480×800 (`tests/test_fleet_map_page.py:257-284`).
- **The schema-checked YAML** of `powerapps_yaml.md` KQ12 — a responsive screen, a component with an Input and an
  Event, its instantiation, `App.StartScreen` on `Param("approvalId")` — is the seed of `mobile/powerapp/src/`.
- **The Power Apps (V2) trigger** with run-only user connections and **Office 365 Users "Get my profile (V2)"**
  (`flows_and_onedrive_bridge.md` Q6): server-side identity from the invoker's own connection.
- **The regression convention** (`docs/testing-this-repo.md:631`) and decision 13's fold rule (§Ground rules 2).

## Prior art, and what is different here

- **The earlier report** ([reports/Intune phone access to agents.md](../reports/Intune%20phone%20access%20to%20agents.md))
  scored fourteen paths and kept three: two loops that work now (a Teams card with a OneDrive return; an Outlook
  reply), one dream state (a ZPA-published relay), and a side track (Copilot CLI remote control, consoles only).
  Its stage 0, *harden the approval record in code*, is MOB-S unchanged. What is different now: the operator named
  Power Apps, so the phone surface is a canvas app instead of a Teams card. The OneDrive return leg is the same; the
  flow is the relay the report's stage 2 already assumed; and a canvas app gives what a card cannot — an attention
  list, a payload preview, history, and the laptop's verdict on each decision. The ZPA relay stays *later*: it needs
  a host, an App Connector group and a security review that this path does not.
- **Every vendor that solved "control my local agent from my phone"** — GitHub, Anthropic, OpenAI, Cursor — built an
  outbound-only relay with same-identity sign-in, admin opt-in and a narrow set of verbs (the report §Copilot CLI
  remote control). This is that shape with Microsoft 365 as the relay and no new service to stand up. The narrow
  verbs are the same four: read the attention list, read one approval, decide, reply.
- **A mail spool.** Immutable, uniquely named records written by rename into a directory; a reader that identifies
  a record by its content, never by its file name; processed and rejected boxes. That is the outbox and the inbox.
  What is different: a sync client in the middle that can resurrect a file it was mid-upload on and can make
  `<name>-<DEVICE>` conflict copies (`flows_and_onedrive_bridge.md` Q8), so the reader dedupes on a `nonce` and the
  folder converges.
- **Microsoft's Approvals app in Teams** is Microsoft's own replacement for approvals on a phone after the Power
  Automate mobile app's retirement on 31 August 2026 (`notifications_intune_powerapps.md` KQ4). It approves a
  request; it cannot bind the answer to a digest of what an agent will send, and it cannot carry the laptop's
  refusal back. Ours does both, and the retirement does not touch the Power Apps Notification V2 path
  (`flows_and_onedrive_bridge.md` Q12).
- **Phone tab bars and list-plus-detail tablets** (HIG tab bars; Material navigation bars; iPad Split View widths in
  `mobile_ux_requirements.md` Web Q4). The desk takes the shape and keeps one page, one stylesheet, one arrangement:
  the stack is a media query over the pane component that exists, not a second layout system.

## The model

### The path, and who talks to whom

```
LAPTOP (unchanged bind, unchanged token)                      MICROSOFT 365                              PHONE / TABLET
ad-fleet serve ── bridge thread, 5 s tick                      OneDrive for Business                     Power Apps mobile (Intune APP)
  fleet_snapshot() ─► allow-list ─► scrub ─► outbox/  ──sync──►  FleetAgent/outbox/*  ─trigger─►  FleetOutboxToLists (flow)
  approval.decide()  ◄── verify ◄── inbox/  ◄──sync──  FleetAgent/inbox/*   ◄─create─  FleetDecide (flow, Power Apps V2)
  supervisor.send|say()                                          five lists ◄──────────────────────  FleetAgent canvas app
                                                                 push (Power Apps Notification V2) ─►  the phone buzzes; Param() routes
```

The phone talks to Microsoft 365 and only to it. The laptop opens no socket and calls no host: its only network
traffic is the OneDrive sync client's, which already runs. `_authorized`, the bind and the two tokenless routes are
untouched; the count "two, and no more" (`tests/test_fleet_ide.py:106-113`) holds.

### The bridge folder

`fleet.mobile.folder` has **no default**, must be configured, and is refused with `mobile_folder_in_repo` inside any
registered checkout or under `fleet_dir()`. It is the one new exception to "the fleet writes only under
`~/.agentdata/fleet/`" (`HANDOFF.md:34`; `docs/fleet.md:252`), written into both sentences (MOB-D22). `config.expand`
applies (`config.py:54-55`), so `%OneDriveCommercial%/FleetAgent` resolves at read time.

```
<fleet.mobile.folder>/                       e.g. %OneDriveCommercial%/FleetAgent
  pairing.json                               written once by `ad-fleet mobile init`: {schema, kind: "pairing", contract: 1, operator, laptop_id, expire_s, created}
  outbox/                                    the laptop writes; the phone side never writes here
    attention/<repo>-<seq>.json              one file per change of a repo's row digest; never rewritten
    approvals/<id>.json                      the request mirror, once
    approvals/<id>.decision.json             once, whichever side decided; carries `nonce` when `via` is mobile
    notifications/<at>-<repo>-<state>-<seq>.json
    heartbeat/<yyyymmdd-hhmm>.json           every 300 s
    results/<nonce>.result.json              the laptop's verdict on each phone decision or reply
  inbox/                                     the phone side writes (FleetDecide); the laptop only removes what it applied or rejected
    decision-<nonce>.json                    name advisory; content authoritative
    reply-<nonce>.json
  processed/<name>, processed/<name>.result.json
  rejected/<name>,  rejected/<name>.why.json  {code, error, hint, at}
```

Every name passes `bridge.safe_file_name`: `textio.safe_name`, then `#` and `%` to `_`, a leading `~` stripped, 120
characters; a path over 300 characters is a doctor `warn` (the 400-character decoded-path limit with headroom,
`laptop_bridge_design.md` Q4). Every write is `textio.write_json`, so the `.tmp` sibling is never synced and the
rename lands as one complete file (`flows_and_onedrive_bridge.md` Q8; whether the sync client uploads a renamed,
never-synced `.tmp` as a create is V1's first row). Pruning: decided pairs, notifications, results, superseded
attention files and heartbeats after 24 h; `processed/` and `rejected/` after 7 days; a pending request never.

### Why every record is immutable and uniquely named

The OneDrive for Business trigger the flow uses is **When a file is created (properties only)** (`OnNewFilesV2`): it
returns metadata batched 1–100 with Split On, takes a trigger condition, and "Files moved within OneDrive are not
considered new files"; the modified-file triggers are heuristic and "can occasionally fire the trigger when no
noticeable change has occurred" (`flows_and_onedrive_bridge.md` Q1). So a *created* trigger must see everything, and
it sees a file once. Hence `attention/<repo>-<seq>.json` written only when the row's digest changes,
`heartbeat/<yyyymmdd-hhmm>.json` instead of a same-name replace, and `results/<nonce>.result.json` as a new file per
verdict. The laptop's bridge design (`laptop_bridge_design.md` Q4) had `attention/<repo>.json` rewritten in place and
`heartbeat.json` replaced every 60 s; this plan changes both for the reasons above and in §Pushback 8.

### The outbox records (all `schema: 1`, allow-listed, scrubbed; limits in `laptop_bridge_design.md` Q2, Q4)

| kind | file | fields |
|---|---|---|
| `attention` | `attention/<repo>-<seq>.json` | `repo ≤64, project ≤64, ticket ≤32, state ∈ STATES, role ∈ running\|waiting\|human\|done\|idle, needs_human, says ≤300, last_said ≤200, age_s, at, generated, approvals[≤8], approval_id, questions[≤8: {id, q ≤300, choices ≤8×80, want, default ≤80}], run {n, origin, live, since_start, resumed}, model ≤64, spend {total, today, budget, turns, line ≤64}, supervised, external, digest, seq` |
| `approval` | `approvals/<id>.json` | `id ≤96, repo, ticket, approval_kind (jira-transition\|jira-create\|pncli-write), summary ≤300, payload_preview (≤8 KB, else {truncated, bytes, head}), digest (64 hex), created, expires = created + fleet.approval_timeout, waiting_s` — never `pid`, never the full `payload` |
| `decision` | `approvals/<id>.decision.json` | `id, decision, reason ≤500, by ≤254, via ∈ laptop\|mobile, decided, digest, late, nonce (when via is mobile)` |
| `notification` | `notifications/<at>-<repo>-<state>-<seq>.json` | `repo, ticket, state, severity ∈ action\|alert\|info, title ≤120, body ≤300, seq, at, key = "<repo>:<state>:<seq>", quiet, approval_id` — **no URL** (the toast's carries the run token, `notify.py:244`) |
| `heartbeat` | `heartbeat/<yyyymmdd-hhmm>.json` | `at, every_s: 300, expire_s, contract: 1, operator, bridge (version string), laptop_id (random hex, never the hostname), serve_up, desk_streams, counts {repos, needs_human, approvals_pending, notifications_24h, rejected_24h}, inbox_last_seen` |
| `result` | `results/<nonce>.result.json` | `nonce, kind ∈ decision\|reply, id or repo, ok, result ∈ applied\|rejected, code, error, hint, via ∈ say\|send (replies), answered [ids], at` — in the supervisor's or the bridge's own words |

Never exported, by construction and by test: `path`, `pid`, `console`, `external_how`, `scope_report`, `trace`,
`recent`, `fleet_dir`, `server`, `theme`, `desk`, every `*_source` cell (`laptop_bridge_design.md` Q2). The scrubber is
`events.redact()` first, then every non-`LINK_FACTS` fact value of every registered project, then the run token, every
`repo.path`, `fleet_dir()`, `~`, `USERNAME`, `COMPUTERNAME`, then UNC and drive-path shapes and hostnames, and
`.agent/out/<dir>/<file>` reduced to its basename (AGENTS.md rule 5: the rows never leave; the operator still learns
*which* file an approval sends).

### The approval record after S1

`require()` writes `digest = sha256(canonical({id, kind, summary, payload, created, pid}))` into the request
(`approval.py:105-111`) and keeps it in a local. On a decision file carrying a `digest` that differs, it returns
**DENIED** with `reason = "the decision names a different request (digest mismatch)"` and emits `approval_resolved`
(MOB-D1). A decision with no `digest` — the desk, the CLI, an older build — is accepted as today, byte for byte.
`decide(id, state, *, reason="", by="", digest="", via="laptop")` compares a given digest with the request on disk and
refuses `digest_mismatch`; the decision file gains `digest` and `via`; the bridge passes `by = "mobile:<upn>"`.
`approval_resolved` gains `reason`, and each gated caller puts `meta["approval_note"] = decision.reason` after `.ok`
(`cli_jira.py:232-238`, `317-325`; `cli.py:143-151`), so `ad-fleet approve --comment`'s help text ("a note the agent
can quote", `cli_fleet.py:1976-1979`) becomes true. `expires` lives on the *decision* (issued/expires from the phone),
not on the request, whose window is already `approval_timeout`.

### The inbox records, and the checks in order

`decision-<nonce>.json`: `{schema: 1, kind: "decision", nonce, issued, expires, by, id, digest, decision, reason, device?}`.
`reply-<nonce>.json`: `{schema: 1, kind: "reply", nonce, issued, expires, by, repo, message ≤4000 | answers [{id, answer ≤1000}] ≤8, device?}`.
Checks, first failure to `rejected/` with its code in the sidecar: size ≤ 16 KB (`mobile_too_large`, read `st_size`
first); `read_json` (`mobile_bad_json`); `schema == 1` (`mobile_bad_schema`); `nonce` `^[A-Za-z0-9_-]{16,64}$` and
unused (`mobile_replay`); `issued ≤ now + 300` (`mobile_bad_time`); `now ≤ expires ≤ issued + fleet.mobile.expire_s`
(`mobile_expired`); `by.casefold() == fleet.mobile.operator.casefold()` (`mobile_wrong_operator`); the id is a request
on disk (`mobile_unknown_id`), undecided (`mobile_already_decided`); `digest == approval.digest(request)`
(`mobile_digest_mismatch`); a denial has a reason (`mobile_reason_required`); a reply names a registered repo
(`mobile_wrong_repo`). Then, and only then, `approval.decide(..., by=f"mobile:{by}", digest=digest, via="mobile")` or
the `act("answer")` mapping; the nonce is recorded in `<fleet_dir>/mobile.state.json`; the file moves to `processed/`;
the outbox gets `<id>.decision.json` or `results/<nonce>.result.json`. **Fail-closed, tested:** after every refusal,
`approval.read_decision(id)` is still `{}`, so the agent's own `require()` loop times out and refuses the write.
`force` is never honoured from the phone (MOB-D8). A `mid_turn` refusal is retried every tick until `expires`, then
refused as `mid_turn` with `retried_s` in the result (MOB-D7). The UPN check is a **misconfiguration guard, not
authentication**: anyone who can write into the operator's OneDrive folder can drop a decision, and
`docs/fleet-mobile.md` says so in one sentence, the way `docs/fleet-dashboard.md:65-66` says "loopback security, not
authentication". HMAC-signed decisions are B12.

### The five lists

Five SharePoint lists with **all-text columns**: ISO-8601 UTC timestamps, `true`/`false`, numbers as text. One YAML
then serves SharePoint and the Excel fallback (Excel exposes every column as a string,
`powerapps_yaml.md` KQ9), every `Filter` on `=` delegates, and ISO text sorts chronologically with `SortByColumns`
(KQ9). Every list is the flow's to write and the app's to read, with the two exceptions marked.

| list | Title | columns | written by |
|---|---|---|---|
| `FleetAttention` | repo | `Title, Project, Ticket, State, Role, NeedsHuman, Says, LastSaid, AgeSeconds, At, Generated, ApprovalId, ApprovalsJson, QuestionsJson, RunNumber, RunOrigin, RunLive, Model, SpendLine, SpendTotal, SpendToday, SpendBudget, Turns, Supervised, External, Digest, Seq` | `FleetOutboxToLists`: one row per repo, updated when `Seq` rises |
| `FleetApprovals` | approval id | `Title, Repo, Ticket, ApprovalKind, Summary, PayloadPreview, PayloadTruncated, PayloadBytes, Digest, Created, Expires, WaitingSeconds, Status, DecidedBy, DecidedAt, Reason, Via, Late, Nonce, ResultCode, ResultText, SourceFile`; `Status ∈ pending\|sent\|approved\|denied\|rejected\|expired` | the flow (`pending` on the mirror; `approved`/`denied` on the decision mirror; `rejected` on a result; `expired` on `late: true`); `FleetDecide` sets `sent` |
| `FleetDecisions` | nonce | `Title, Kind, ApprovalId, Repo, Decision, Reason, Message, AnswersJson, Digest, By, Device, Issued, Expires, InboxFile, Result, ResultCode, ResultText, ResultAt`; `Result ∈ sent\|applied\|rejected` | `FleetDecide` creates with `sent`; the flow updates from `results/` |
| `FleetNotifications` | key | `Title, Repo, Ticket, State, Severity, TitleText, Body, At, Seq, Quiet, ApprovalId, SourceFile` | the flow |
| `FleetHeartbeat` | `"laptop"` | `Title, At, EverySeconds, ExpireSeconds, Contract, Operator, Bridge, LaptopId, ServeUp, DeskStreams, Repos, NeedsHuman, ApprovalsPending, Notifications24h, Rejected24h, InboxLastSeen` | the flow, one row updated |

`mobile/data/FleetAgent.xlsx` holds the five tables with these headers and three fictional sample rows each, and is
both the "Create a list → From Excel" source and the Excel Online (Business) fallback store. Under Excel the single-writer rule (`Excel Online
(Business)` connector reference, `flows_and_onedrive_bridge.md` Q3) means **two copies**: one written by
`FleetOutboxToLists`, one by `FleetDecide`; the app reads both. A `FleetNotifications` row is about 0.5 KB, so a
year at 200 a day is ~36 MB, over the 25 MB cap: one more reason Excel is the fallback (MOB-D12).

### `FleetDecide`, the only phone→laptop writer

Power Apps (V2) trigger, inputs `Kind, ApprovalId, Repo, Decision, Reason, Message, AnswersJson, Digest,
ExpiresSeconds (Number), Device`; every other input Text. Identity comes from Office 365 Users **Get my profile (V2)**
on the **invoker's** connection (the flow's connections are *Provided by run-only user*), never from an input the app
could fill. The flow composes the inbox record (`nonce` = `guid()`, `issued` = `utcNow()`, `expires` = `issued +
ExpiresSeconds`, `by` = the profile's `UserPrincipalName`), creates `FleetAgent/inbox/decision-<nonce>.json` or
`reply-<nonce>.json` with OneDrive **Create file**, creates the `FleetDecisions` row with `Result = sent`, patches
`FleetApprovals.Status = sent`, and answers **Respond to a PowerApp or flow** `{ok, nonce, inboxFile, error}` inside
the 120 s inbound limit; a Catch scope answers `ok = false` with the error text. Power Apps-triggered flows run at
the Medium profile and are charged to the invoker, who is the operator (`flows_and_onedrive_bridge.md` Q6).
`ExpiresSeconds` is what the app read from `FleetHeartbeat.ExpireSeconds`, so the phone never claims longer than the
laptop will accept.

### `FleetOutboxToLists`

Trigger **When a file is created (properties only)** on `FleetAgent/outbox`, *Include subfolders* = Yes, trigger
condition `@endswith(triggerOutputs()?['body/Name'], '.json')`, Split On; **Get file content** by `Id`; **Parse JSON**
from the samples in `mobile/powerapp/sample/`; **Switch** on `kind`; an idempotency **Get items** on `Title` (and
`Seq`/`Nonce`) before every **Create item**/**Update item**; for a `notification` with `quiet = false` and `severity ∈
action|alert`, **Send push notification V2** with a content-free `Message` and `Parameters {"screen", "approvalId",
"repo"}`; the Catch scope appends one `alert` row to `FleetNotifications` (the app's Alerts tab shows it) and **never
writes under `outbox/`**, which is the laptop's.
Retry policy `None` on the row writes: dedupe first, because "at-least-once" is by design (Q2). If *Include
subfolders* does not see every subfolder, F2 builds one trigger per subfolder (§Open questions). About 6 requests per
run; per day, ≈ 288 heartbeats + attention changes + approvals + notifications + results ≈ 4,000 against 6,000 (Q11);
the arithmetic is recorded in `mobile/flows/README.md` at F2.

### Notifications

`notify.py`'s rules stay the only rules (`RULES`, `notify.py:43-51`; cooldown `203-214`; quiet hours `85-100`). The
bridge's `send_mobile(item, cfg)` is a channel beside `send_toast` inside `deliver()`, never raises, and writes one
notification file; `item["mobile"]` is recorded on the drawer entry as `toasted` is. The flow relays what the record
says: `quiet` and `severity`. One process-wide sweep (`sweep_if_due`, lane `serve`) replaces each stream's private
`last_sweep` (`serve.py:2470`, `2545-2548`) so the bridge sweeps when no window is open; a desk opened later finds
what accumulated in the drawer, not as fresh `notify` frames — the #356 paragraph changes (MOB-D9). On the phone,
Power Apps mobile does not honour Intune's *Org data notifications*; iOS falls back to *allowed*, Android under
*Block org data* to *blocked*, which may mean **no** pushes on an Android phone under the Intune data-protection
baseline (`notifications_intune_powerapps.md` KQ2). That is a runbook row (V1) and an IT-ask line (V2), not a design
assumption.

### Settings, verbs, events, doctor

- `fleet.mobile.enabled` (bool, `false`, RESTART), `fleet.mobile.folder` (str, none, RESTART), `fleet.mobile.operator`
  (UPN, none, NOW), `fleet.mobile.expire_s` (int, `900`, 60–3600, NOW), `fleet.mobile.notify` (bool, `true`, NOW).
  None joins `EDITABLE`: each moves a human checkpoint, the reason `settings.py:28-37` keeps `console.helper` and
  `preflight` off the page. `ad-setup --patch fleet.mobile` re-asks exactly these five. No secret anywhere.
- `ad-fleet mobile status | init | export | apply | watch` (`laptop_bridge_design.md` Q7): `init` writes the tree and
  `pairing.json` (MOB-D6); `export --dry-run` and `apply --dry-run` change nothing on disk; `watch` is the standalone
  loop and refuses `mobile_serve_running` beside a live `serve`, because two sweepers split `notify.state.json`'s one
  cursor. Refusals are `BridgeError(msg, hint, code)` through `_refuse`, exit 2, rows in `docs/refusals.md`.
- Events on the agent's stream: `mobile.exported {id, digest, expires}` (per approval, not per attention row),
  `mobile.decision {id, kind, decision, by, nonce, late}`, `mobile.reply {nonce, by, via, answered, words}`,
  `mobile.rejected {nonce, kind, code, why}`. Additive; no state changes.
- Doctor rows `fleet/mobile` and `fleet/mobile traffic` (`laptop_bridge_design.md` Q6): `skip` when off naming the
  key; `fail` when the folder is unset, missing, unlistable, in a repo, or online-only (`st_file_attributes &
  (0x00100000 | 0x00400000)`) with the hint `attrib +p "<folder>" /s /d`; `warn` when the sync root cannot be told,
  the operator is not UPN-shaped, `expire_s` is invalid, or the path is over 300 characters (MOB-D4). No subprocess.

## The Power App

One canvas app, **FleetAgent**, Tablet format, responsive: Scale to fit off, Lock aspect ratio off, Lock orientation
off, `App.MinScreenWidth = 320`, `App.MinScreenHeight = 480`, `App.SizeBreakpoints` at its tablet default
`[600, 900, 1200]`, every screen one scrolling AutoLayout root sized `Parent.Width`/`Parent.Height`
(`mobile_ux_requirements.md` AC-PA1–PA3; `powerapps_yaml.md` KQ3). Modern controls and themes on. The app **decides
nothing**: it renders `State` and `Says` verbatim, colours by `Role`, shows the laptop's `ResultText` and the flow's
`error` in their own words, and never recomputes `NeedsHuman`. The shells rule (`tests/test_fleet_shells.py:83-135`)
extends to it in spirit, checked by `tests/test_mobile_powerapp.py` (the shells test does not scan `mobile/`).

### The tree

```
mobile/
  README.md                                the tree, the order to build in, the import sheets
  powerapp/
    src/App.pa.yaml                        StartScreen on Param("screen")/Param("approvalId")/Param("repo"), BackEnabled, OnError, Formulas
    src/Screens/HomeScreen.pa.yaml         who needs you: a tab list (Attention · Approvals · Alerts · History) over four galleries;
                                           a detail pane beside the list at ≥ 900 px; the one 60 s refresh Timer
    src/Screens/AgentScreen.pa.yaml        one agent: state, says, last said, run, model, spend, questions; Reply; the approval waiting
    src/Screens/ApprovalScreen.pa.yaml     one approval: kind, summary, preview (monospace, scrolling), digest, expiry, status; Approve… / Deny…
    src/Screens/DecideScreen.pa.yaml       the reason box and the one Send button (a screen, not an overlay: overlays are not accessible)
    src/Screens/ReplyScreen.pa.yaml        the reply box; Send calls FleetDecide.Run("reply", …)
    src/Screens/SettingsScreen.pa.yaml     signed-in user, the laptop's operator and the mismatch warning, heartbeat, contract, version
    src/Components/FleetHeader.pa.yaml     Inputs: Title, Status, ShowBack, ShowSettings; Events: OnBack, OnRefresh, OnSettings
    src/Components/KeyValueRow.pa.yaml     Inputs: Label, Value, Wrap
    src/Components/EmptyState.pa.yaml      Input: Message
    src/_EditorState.pa.yaml               ScreensOrder, ComponentDefinitionsOrder
    themes/FleetTheme.yaml                 a `Themes:` document pasted through the Themes pane (not schema-valid inside .pa.yaml)
    sample/*.json                          3–5 fictional rows per list, to seed a first look and to generate the Parse JSON schema
    schema/pa.schema.yaml                  the v3.0 schema, byte-identical to PowerApps-Tooling's copy (MIT; see LICENSE-NOTE.md)
    NOTES.md                               every choice made where the research left something UNVERIFIED, for P1 to settle in Studio
  flows/
    FleetOutboxToLists.definition.json     the exported Workflows JSON, reviewed in the repo
    FleetDecide.definition.json
    solution/                              the unmanaged solution zip's contents after F4
    README.md                              build sheets, the import sheet, request-budget arithmetic
  data/
    FleetAgent.xlsx                        five tables, the list source and the Excel fallback
    make_workbook.py                       builds the workbook from the column tables (run by hand; CI reads the tables only)
    README.md                              list creation from Excel; the single-writer rule; the two-copy fallback
```

`mobile/**` and `tests/test_mobile_powerapp.py` form a proposed `mobile` lane (exclusive, one PR at a time).
`.github/agent-lanes.json` is frozen (`relay`), so until the operator approves that edit the tree is one exclusive
lane by convention (MOB-D21).

### Screens and formulas

| screen | at `Parent.Size = ScreenSize.Small` | at `≥ ScreenSize.Large` (900 px) | the formulas that matter |
|---|---|---|---|
| Home | one column: `FleetHeader`, a warning banner (operator mismatch, laptop not syncing), a Tab list (`Attention` · `Approvals` · `Alerts` · `History`), one Gallery per tab (plain controls in the rows: a component cannot sit inside a gallery), an `EmptyState` per gallery; a tap on a row navigates | the list at 420 px beside a detail pane of `KeyValueRow`s with *Open agent* and *Open approval* | Attention: `SortByColumns(FleetAttention, "NeedsHuman", SortOrder.Descending)` (a second sort column only if it delegates); Approvals: `PendingApprovals` newest first; Alerts: `FleetNotifications` newest 50; History: `Status <> "pending"`; `TemplateSize ≥ 88`; a `Badge` per row coloured by `Role`; the one 60 s `Timer` refreshing the five lists |
| Agent | `KeyValueRow`s: project, ticket, state (a `Badge`), needs you, says, last said, age, run, model, spend, supervised/external in the server's words; the questions (`ParseJSON(QuestionsJson)` if it renders, else the JSON as text); *Reply*; *Approval waiting* when `ApprovalId` is set | the same | *Reply* is disabled with the server's sentence when `External = "true"`; entered by deep link, the row is `DeepLinkAgent` |
| Approval | kind, repo · ticket, summary, created, expires and "N min left" (`DateDiff`, no ticking timer), `PayloadPreview` in a scrolling monospace block, "N bytes not shown; the digest covers all of it" when `PayloadTruncated = "true"`, the digest's first 12 characters, the status line; *Approve…* and *Deny…* at 52 px | the same | both buttons `DisplayMode.Disabled` unless `Status = "pending"` and `DateTimeValue(Expires) > Now()` |
| Decide | a recap (kind, summary, repo · ticket, digest prefix), the reason box (required to deny), one *Send approval* / *Send denial* button, *Cancel*, a spinner while `busy` | the same | `IfError(With({r: FleetDecide.Run("decision", row.Title, row.Repo, decideChoice, Trim(txtReason.Text), "", "", row.Digest, ExpireSeconds, Host.OSType)}, If(r.ok, Notify(…); Refresh(FleetApprovals); Navigate(HomeScreen), Notify("Not sent: " & r.error, NotificationType.Error))), Notify("Not sent: " & FirstError.Message, NotificationType.Error))` |
| Reply | the agent's recap, the message box, *Send reply* | the same | `FleetDecide.Run("reply", "", row.Title, "", "", Trim(txtMessage.Text), "", "", ExpireSeconds, Host.OSType)` under the same `IfError`; the laptop's verdict appears under History |
| Settings | signed in as `User().Email`, the laptop's `Operator` and the mismatch warning, heartbeat age, bridge version, contract, counts, app version, `Host.OSType`, `Connection.Connected`, *Refresh everything*, an About line ("this app decides nothing") | — | `Refresh(FleetAttention); Refresh(FleetApprovals); …` |

`App.StartScreen: =If(Param("screen") = "approval" && !IsBlank(Param("approvalId")), ApprovalScreen, Param("screen") = "agent" && !IsBlank(Param("repo")), AgentScreen, HomeScreen)`;
`App.BackEnabled: =true`; `App.OnStart` empty; `App.Formulas` holds `Operator`, `Heartbeat = LookUp(FleetHeartbeat, Title = "laptop")`,
`HeartbeatAgeSeconds`, `LaptopStale`, `OperatorMismatch`, `ExpireSeconds = Coalesce(Value(Heartbeat.ExpireSeconds), 900)`,
`PendingApprovals`, `PendingCount`, `NeedsYou`, `DeepLinkApproval`, `DeepLinkAgent`, `IsPhone`, `IsWide`, `AppVersion`; one
60 s Timer, on the home screen, calls `Refresh` on the five lists (MOB-D16), because `Param` does not refresh while the
app runs and a push tap on an open app needs `restartApp=true` in the deep link (`flows_and_onedrive_bridge.md` Q5). No `SaveData` (`notifications_intune_powerapps.md` KQ7). `Host.OSType` is
recorded as `Device`, never branched on. Colours come from `App.Theme.Colors.*` via `FleetTheme`, seeded from the
desk's default palette (`app.css:22-41`), and every state carries an icon and a word. Every property value begins
with `=`; every value containing `: ` is quoted; multi-line formulas are `|-` block scalars; no `@version` suffix is
written by hand — P1 copies the exact `Control:` values Studio returns and uses each identically on every instance of
its type (`powerapps_yaml.md` KQ2).

### What YAML cannot hold, and the click sheet that holds it

`mobile/README.md` is the click sheet, one line per click: the five data sources added through **Data → Add data**
(the SharePoint site and the five lists, or the workbook's tables); **Settings → Display** with the three switches
off; **Settings → Updates** with modern controls and themes and enhanced component properties on, Delayed load on,
Keep recently visited screens in memory on, Preload app on (`mobile_ux_requirements.md` AC-PD4); **Themes → Add a
theme → Paste theme** with `themes/FleetTheme.yaml`; the Power Automate pane adding `FleetDecide`; the paste order for
`src/` through Code view — the components first (`EmptyState`, `KeyValueRow`, `FleetHeader`), then the screens in the
order that makes every reference resolve (`SettingsScreen`, `ReplyScreen`, `DecideScreen`, `ApprovalScreen`,
`AgentScreen`, `HomeScreen`) — and then the App object's four properties typed into the formula bar, because Code view
cannot paste the App object (`powerapps_yaml.md` KQ7); or `compile_canvas` through the Canvas Authoring MCP server
when the tenant allows coauthoring. The push connection is the flows', not the app's: the app sends no push. P8 turns
what Studio taught into checks.

## The desk at phone and tablet widths

Numbers first, all measured (`desk_mobile_audit.md` §7, six agents, one pending approval, one open question):

| viewport | header | open pane | transcript | reply row top | `#grid` scroll / client | after `all` | targets < 44 px |
|---|---|---|---|---|---|---|---|
| 390×844 | 113 px | compact, 160 px | 110 px | 731 of 844 | **466 / 390** | **1026 / 390** | 24 of 30 |
| 844×390 | 78 px | full, 558 px | **1 px** | **599 of 390** | 844 / 844 | **1026 / 844** | 32 of 38 |
| 820×1180 | 78 px | full, 534 px | 481 px | 1092 of 1180 | 820 / 820 | **1026 / 820** | 32 of 38 |
| 1180×820 | 43 px | full, 894 px | 231 px | 732 of 820 | 1180 / 1180 | 1180 / 1180 | 32 of 38 |

The phone fails structurally: five 48 px rails and one 160 px pane cannot share 390 px, and `groupRails` folds only
checkouts of one project (`app.js:5182-5207`). Landscape fails on height: `#grid` never scrolls vertically. Tablets
work in the default preset and fail on `all`, touch targets and the missing touch twin of Shift-click.

**The stack, at ≤ 640 px (MOB-D17), stylesheet plus four guarded JS writes, inside the render contract:**

- Foundations on all four pages: `viewport-fit=cover, interactive-widget=resizes-content`; `body { height: 100vh; height: 100dvh }`;
  `footer { padding-bottom: calc(6px + env(safe-area-inset-bottom)) }`; `.modelcard { max-height: calc(100dvh - 16px) }`;
  `kbd` hidden at ≤ 640 px (55 hints in `index.html`). Safari has not shipped `interactive-widget`
  (`mobile_ux_requirements.md` AC-V4), so the reply row is a flex child inside a pane that scrolls, never
  `position: fixed`.
- `@media (pointer: coarse)`: 44 px minimum on buttons, segments, tabs, pills, list rows and the head's tools; 16 px
  on `input, textarea, select` (iOS zooms under 16 px); the gutter's hit strip 20 px, widened inward; sticky
  Approve/Deny/Send rows inside the approval and question cards (`position: sticky; bottom: 0`); `.tile .head,
  .pane-rail { touch-action: pan-y }` in place of `none`, so a finger can scroll where it could only drag.
- The row becomes a stack: `#grid { flex-wrap: wrap; overflow: hidden auto }`; the open pane `flex: 1 1 100%; order: -1`
  and fills the glass; rails `flex: 1 1 var(--rail); height: 56px; order: 1` with `.pane-rail` horizontal and
  `.pr-name` horizontal, so they wrap onto one bottom line and read as a tab bar. The tiers stay right by their own
  rule: a bar rail is ~60–78 px, under `--compact-from`; the open pane is 374 px at 390, `full`. `groupRails` gets a
  one-line guard that reads the bar's capacity instead of the row's. `all` stacks wide panes vertically and the grid
  scrolls; `.gutter` and `.grip` are hidden.
- The toolbar is two rows: brand · dot · presets · bell, then find · sidebar · map · settings; the chime moves out of
  the row.
- The sidebar is a full-width sheet with a scrim (`#side::before`, `rgba(0,0,0,.3)`) and one listener: a click on the
  scrim calls `closeSide()`. It is dead today on every fresh window (S4) and must be fixed first.
- Under a coarse pointer in the stack, `bindDragToReorder` returns on `pointerdown`; reorder stays on `Alt+arrows`,
  and every rail is one tap away, so `backToPrevious` needs no twin (MOB-D20).

**Tablets keep the row** (744–834 portrait, 1024–1366 landscape): cap the `all` preset to the panes that fit at
`--compact-from` and say so ("all that fit: 4 of 6"), one undoable write; a 400 ms **long-press on a rail** calls
`openBeside`, the touch twin of Shift-click; double-tap on a gutter evens it (`dblclick` already does,
`app.js:4894-4898`); the sidebar overlay `min(480px, 60vw)` so the row stays visible beside it; the coarse-pointer
block applies. The `w=phone`/`w=tablet` records cost no server work (`serve.py:1592-1639`), and both names join
`IDE_WINDOWS` (`opener.py:38`) so `ad-fleet open --all` skips them (MOB-D23).

**Ink is off on a coarse pointer** by a gate rule in `ink.js` (`ink.js:99-115`): `matchMedia("(pointer: coarse) and
(max-width: 900px)")` with `source: "narrow"`, because the canvas is rebuilt on every `resize` (`layer.js:1245-1256`)
and a mobile URL bar fires those repeatedly; three.js is 163 KB. It is `ink-core` (exclusive) and lands after #523;
until then the phone and tablet links carry `ink=off`, which `pageUrl` preserves (MOB-D19).

**`/m`, the small phone page, is the last desk card** and waits for #523 (MOB-D18): `m.html + m.css + m.js` ≈ 10.5 KB
gzipped against 11,315 B of headroom at `0b9ec72` and ~2.4 KB on today's `main` (`desk_mobile_audit.md` §12). It reads
S3's `GET /api/attention` and `GET /api/approval?id=`, streams `/api/events`, and posts `approve`, `deny`, `send`,
`answer` — for a tablet on the laptop's own localhost, or for the day the ZPA relay exists.

**Tests fold** (decision 13): `tests/test_fleet_panes.py::test_…widths_move_between_tiers…` gains 390×844, 844×390
and 820×1180 steps; `tests/test_fleet_map_page.py`'s narrow test gains a `has_touch` context and a `page.tap`;
`tests/test_fleet_settings_page.py::test_the_page_renders_every_section_and_can_get_back` gains a 390 px pass;
`tests/test_fleet_desk_switcher.py` or `tests/test_fleet_board_desk.py` gains the tap-then-toggle reproduction of the
sidebar trap; `tests/test_fleet_gutters.py::test_every_gesture_again_from_the_keyboard` gains the long-press twin, and
its idle-desk mutation test runs once at 390 px. Plain guards: `update_window` creates `section: ""`
(`tests/test_fleet_window.py`); `app.css` contains `100dvh`, `env(safe-area-inset-bottom)`, a `(pointer: coarse)` block
with `min-height: 44px` and `font-size: 16px`, and no `touch-action: none` on `.tile .head`; `index.html`'s meta
carries `viewport-fit=cover` (`tests/test_fleet_desk_regressions.py`/`tests/test_fleet_theme_tokens.py` style);
`tests/test_fleet_motion.py` already scans every duration. Emulation is
`browser.new_context(viewport=…, device_scale_factor=3, is_mobile=True, has_touch=True)` — unused today, available in
the pinned Playwright. Every card reports the served payload and "+0 browser tests" in its CAR line.

## Where everything is written down

| doc | what it will hold |
|---|---|
| `docs/fleet-mobile.md` (new) | the path and who talks to whom; the folder layout; every outbox and inbox contract with limits; the five lists and their columns; `FleetDecide`'s inputs and outputs; the settings table; the doctor rows; the verbs; the `mobile_*` refusal codes; "the UPN check is a misconfiguration guard, not authentication"; the heartbeat staleness rule (3 × `EverySeconds`); the IT ask (V2); links to the runbook rows |
| `mobile/README.md`, `mobile/powerapp/NOTES.md`, `mobile/flows/README.md`, `mobile/data/README.md` | the tree and build order; the Studio click sheet; the two build sheets, the import sheet and the request-budget arithmetic; list creation from the workbook and the single-writer rule |
| `docs/fleet-approvals.md` | `digest`, `via`, `by`, `expires`, the files on disk after S1 (:100-118); the rule-8 drift at :120-125 corrected to "neither is a gated kind" |
| `docs/fleet-events.md` | the four `mobile.*` kinds with sample lines; `approval_resolved.reason`; the two samples at :266-267 corrected to `{id, kind, summary}` and `{id, kind, decision, by, reason}` |
| `docs/fleet-notifications.md` | §Not here rewritten: mobile via the bridge is in, Email/Teams/Slack still out (MOB-D10); the config table unchanged |
| `docs/fleet-dashboard.md` | §The URL and the token gains the Host allow-list; the #356 paragraph (:533-538) gains the bridge's sweep; §What is not here (:547-548) rewritten (MOB-D10); `/api/attention`, `/api/approval`, gzip of `/api/fleet`, and `/m` in the routes the docs test checks (`tests/test_fleet_serve.py:637-644`) |
| `docs/fleet.md`, `docs/fleet-lifecycle.md`, `docs/setup.md` | the verb list (:28-30) gains `mobile`; the doctor tables (`fleet.md:288-300`, `fleet-lifecycle.md:130-138`) gain two rows; :252 gains the exception; the five keys |
| `docs/refusals.md` (`shared-docs`, rows only) | one row per `mobile_*` code and `digest_mismatch`, each naming a test that exists |
| `docs/desk-window.md`, `docs/desk-components.md` (`shared-docs`), `docs/desk-ink.md`, `docs/fleet-ide.md` | the stack, the bar, the sheet, the touch twins and the keys table (:274-296); inventory rows for the bar and the scrim; the `narrow` gate source; `phone`/`tablet` in `IDE_WINDOWS`, the `ink=off` convention, and :178-180 corrected ("a phone needs no new server work" is true of the window record and false of reachability) |
| `docs/windows-verification.md` | a §Mobile section, every row *not yet measured* until V3 |
| `docs/testing-this-repo.md` (`shared-docs`) | the `mobile` guard's row and the folded browser checks |
| `HANDOFF.md:34` | "— except `fleet.mobile.folder`, which the operator names explicitly and which is never a repository" |
| `.github/agent-lanes.json` (`relay`, frozen) | the `mobile` lane, when approved |

## Slices

Cards are written as in [plan-meter.md](plan-meter.md): scope, lanes and hunks, acceptance, tests, depends on, and the
decision each builds on. The bridge cards keep the detail of `laptop_bridge_design.md` Q12; the desk cards keep
`desk_mobile_audit.md` §15. Every card is one issue, one branch, and reads the named ranges only (§6 of
[developing-with-agents.md](developing-with-agents.md)).

### MOB-S — Approval integrity and the server's remote-ready seams

**S1 — Approval digest, `via`, `by`, `expires`, and the comment that reaches the agent** (S). `approval.digest(record)`
over exactly `{id, kind, summary, payload, created, pid}` with `bridge.canonical` (sorted keys, no spaces, UTF-8);
`require()` writes `digest` into the request and refuses a wrong-digest decision as DENIED; `decide(digest="",
via="laptop")` with `ApprovalError.code`; the decision file gains `digest` and `via`; `approval_resolved` gains
`reason`; `meta["approval_note"]` in the three gated callers; the two samples in `docs/fleet-events.md:266-267`
corrected. Lanes: none (`approval.py`, `cli_jira.py`, `cli.py`, `docs/fleet-approvals.md`, `docs/fleet-events.md`).
Hunks: `require()` (`approval.py:105-132`), `decide()` (`:219-243`), `refusal()` (`:135-149`); `cli_jira.py:232-238`,
`317-325`; `cli.py:143-151`. Acceptance: a decision carrying the request's digest releases the agent; one carrying
another request's digest leaves it refused with `approval_denied` and nothing posted; a decision without a digest
behaves byte for byte as before; `ad-fleet approve --comment` text appears in `ad-jira transition`'s meta; the digest
computed from a re-read pretty file equals the canonical one. Tests: the seven "Digest" tests of
`laptop_bridge_design.md` Q9 in `tests/test_fleet_approval.py` and `tests/test_fleet_events.py`. Depends on: none.
Decision: MOB-D1.

**S2 — A Host-header allow-list on every request, `/open` and `/api/ping` included** (S). `_authorized` checks peer
IP and token only (`serve.py:2637-2642`); `/open` answers `302 /?t=<token>` to any loopback caller (`:2713-2726`) on
two assumptions (`:2687-2691`); the server reads no `Host` (report §A tunnel). A hostile page whose name re-resolves
to `127.0.0.1` becomes same-origin and reads the token from `response.url`. The fix: every request's `Host` must be
`127.0.0.1:<port>`, `localhost:<port>` or `[::1]:<port>`, else `403`, before any route, the tokenless two included.
Lane: `serve`. Hunk: `_authorized` and the `/open`, `/api/ping` branches. Acceptance: a request with `Host:
evil.example:<port>` from a loopback peer gets `403` on `/`, `/open` and `/api/ping`; the three shells and
`ad-fleet open` still open; `tests/test_fleet_ide.py:106-113`'s "Two, and no more" count is unchanged. Tests: plain, in
`tests/test_fleet_serve.py` beside the bind test (`:88-98`) and `tests/test_fleet_ide.py`. Depends on: none.
Decision: MOB-D2.

**S3 — `GET /api/attention` and `GET /api/approval?id=`** (S). Two slim routes: the allow-listed attention rows
(`bridge.attention_row()` over `fleet_snapshot()`, the same function the outbox uses, so one allow-list serves both)
and one approval with `payload_preview`, `digest`, `expires`. For `/m` and any host; `docs/fleet-ide.md` gains them.
Lane: `serve` (the GET table, `serve.py:2735-2896`); `bridge.py` (after B3). Acceptance: `set(row) == ATTENTION_KEYS`
for every row; the four `SITE_FACTS` never appear in either answer; the routes need the token. Tests: plain, in
`tests/test_fleet_serve.py` and `tests/test_fleet_board_desk.py`'s route walk (`:186-194`). Depends on: B3.

**S4 — Fresh window: the sidebar toggle works** (S). `update_window` creates a record with `section: "tickets"`
(`serve.py:1631`); `applyWindow` calls `section("tickets", true, true)` (`app.js:1404-1406`), which hides every real
section and sets `lastSection` to a dead id (`app.js:2078-2096`); the toolbar button then reopens nothing forever
(`app.js:2751-2753`). Reproduced twice at every viewport; a keyboard user presses `b`, a phone user has no other door.
Fix: `applyWindow` ignores a `section` not in `SECTIONS`; the server default becomes `""`. Lanes: `desk-page`,
`serve`. Acceptance: on a fresh `w=`, tap a rail, click `#sidetoggle`, `#side` is shown; the record's `section` is
`""` or a member of `SECTIONS`; the map's `Enter` path (`map.js:193`) no longer traps. Tests: the tap-then-toggle
check folded into `tests/test_fleet_desk_switcher.py` or `tests/test_fleet_board_desk.py`; one plain test on
`update_window` in `tests/test_fleet_window.py`. Depends on: none. Independent of mobile; ships first.

### MOB-B — The bridge: the laptop's outbox and inbox on OneDrive

**B2 — `bridge.py` foundations: settings, the folder rule, OneDrive-safe names, canonical JSON, the scrubber** (M).
`settings(cfg)` mirroring `notify.settings()` (`notify.py:57-82`); `check_folder()` refusing unset, in-repo and
under-`fleet_dir()` folders; `safe_file_name()`; `canonical()`; `Scrubber` (redact → site facts → laptop identity →
shapes → truncate); `MOBILE_SCHEMA = 1`; `BridgeError(msg, hint, code)`; `settings.py:28-39`'s docstring gains the
`fleet.mobile.*` bullet. Lanes: none (new file; `settings.py` docstring). Acceptance: the four `SITE_FACTS`, the serve
token, a UNC path, a drive path and `.agent/out/x/y.tsv` never survive the scrubber, `y.tsv` does; `#`, `%`, a leading
`~` and reserved device names never appear in a produced name; a folder inside a registered checkout is refused with
`mobile_folder_in_repo`; no folder is created when the setting is absent. Tests: "Scrubber, names, folder" in
`tests/test_fleet_bridge.py`. Depends on: none. Decision: MOB-D22; hostnames scrubbed by shape keep URLs whose host is
a `LINK_FACTS` value.

**B3 — The exporter: attention, approvals, heartbeat, results, pruning** (M). `attention_row()` with `ATTENTION_KEYS`;
`export_once(cfg)`; digests in `mobile.state.json`; `attention/<repo>-<seq>.json` only on a digest change;
`approvals/<id>.json` with `payload_preview` and `expires`; `<id>.decision.json` when the laptop decides;
`heartbeat/<yyyymmdd-hhmm>.json` every 300 s; `results/<nonce>.result.json` (the writer B4/B5 call); pruning; the
`mobile.exported` event. Lanes: none. Hunks: `serve.py:319-402`, `480-698` read only; `approval.py:180-209`;
`spend.py:367-377`; `agentstate.py:331-345`. Acceptance: two repos, one waiting on an approval → two attention files,
one approval mirror, one heartbeat; `set(row) == ATTENTION_KEYS`; a second export within the minute writes nothing; a
row change writes a new `-<seq>` file and never rewrites the old one; deciding on the laptop produces the decision
mirror within one tick; a concurrent reader parsing every file during 200 writes never sees a partial file or a
`.tmp`; the heartbeat names no hostname and no pid. Tests: "Exporter" in `tests/test_fleet_bridge.py`. Depends on:
S1, B2. Decision: MOB-D11; the 8 KB preview cap.

**B4 — The applier: decisions** (M). `apply_once(cfg)`: `os.scandir` over `inbox/`, the size check, `read_json`, the
ordered checks of §The model, `decide(..., by=f"mobile:{upn}", digest=, via="mobile")`, the nonce store, moves and
sidecars, `results/<nonce>.result.json`, `mobile.decision`/`mobile.rejected`, `late`. Lanes: none. Acceptance: each
refusal (digest, expired, operator, replay under a conflict-copy name, unknown id, already decided, too large, bad
JSON, reason required) lands in `rejected/` with its code and **no decision file exists afterwards**; a BOM'd and a
UTF-16 file apply; a matching decision releases a waiting `require()` with `by: mobile:<upn>`; a dead or absent inbox
yields TIMEOUT and `refused: approval_timeout`; a late decision on a timed-out request is recorded `late: true`.
Tests: "Applier: decisions" in `tests/test_fleet_bridge.py`. Depends on: S1, B2. Decision: MOB-D3.

**B5 — The applier: replies** (M). The `reply` kind mapped verbatim from `act("answer"|"say"|"send")`; the result in
the supervisor's own words; `mid_turn` retried until `expires`; `force` ignored; `mobile.reply`. Lanes: none. Hunks:
`serve.py:2040-2065`, `2139-2161` read; `supervisor.py:110-131`, `542-597`, `680-705`. Acceptance: console → `say`,
headless → `send`, answers → one `answers_prompt`; `external_session`, `budget_exceeded` and `no_session` produce a
`rejected/` file whose sidecar equals the `SupervisorError` fields; a reply during a turn is applied when the turn
ends or refused as `mid_turn` at `expires` with `retried_s`; a `force` in the file changes nothing. Tests: "Applier:
replies". Depends on: B2, B4. Decisions: MOB-D7, MOB-D8.

**B6 — The notification channel and one process-wide sweep** (S, lane `serve`). `notify.send_mobile(item, cfg)`
called from `deliver()` (`notify.py:254-276`), never raising, `item["mobile"]`; `serve.sweep_if_due(url)` with
`_SWEEP_LOCK` and `_last_sweep_at`; `stream_events` calls it in place of its own `last_sweep` (`serve.py:2470`,
`2545-2548`); the bridge thread calls it with `url=""`. Acceptance: a transition reaches the outbox exactly once with
two desk streams and the bridge running; quiet hours export `quiet: true`; the file carries no URL and no token; with
`fleet.mobile.notify: false` nothing is written; two callers inside one interval sweep once. Tests: "Channel and
sweep" in `tests/test_fleet_notify.py` and `tests/test_fleet_bridge.py`. Depends on: B2, B3. Decision: MOB-D9.

**B7 — The bridge thread in `ad-fleet serve`/`quickstart`, and `ad-fleet mobile watch`** (S). `bridge.start(stop, cfg)
-> Thread | None` (5 s tick: `sweep_if_due`, `export_once`, `apply_once`; 300 s heartbeat; 600 s prune; every pass
wrapped and never raising) called after `_refresh_models(server)` at `cli_fleet.py:1157` and `:1714`; the `watch` loop
refusing `mobile_serve_running` by `serve.json`'s pid and `supervisor.pid_alive`. Acceptance: `S.build()` starts no
thread; `cmd_serve` starts one only when enabled; the thread ends within a tick of `server.stopping`; `watch` refuses
beside a live serve and runs alone. Tests: "Thread and watch". Depends on: B3–B6. Decision: MOB-D5.

**B8 — `ad-fleet mobile status | init | export | apply`** (S). The subparser beside `notify` (`cli_fleet.py:2048-2058`)
and handlers beside `:1640`; `--dry-run` on export and apply; TOON through `_emit`/`_refuse`/`toon.table`.
Acceptance: `status` prints TOON that `toon.validate` accepts with the folder facts; `export --dry-run` and `apply
--dry-run` leave the tree byte-identical; `init` creates the tree and `pairing.json` and refuses a repo folder;
`tests/test_entrypoints.py` accepts every verb (`mobile` is a sub-verb of an installed script). Tests:
`tests/test_fleet_bridge_cli.py`. Depends on: B3, B4. Decision: MOB-D6.

**B9 — Setup and doctor: `fleet/mobile`, `fleet/mobile traffic`, `ad-setup --patch fleet.mobile`** (M).
`FleetStep._mobile()` from disk, attributes and `winreg` only; the two rows with the key rules of §The model; five
`ask()` questions after the notify block (`setup/steps/fleet.py:683-707`). Acceptance: `skip` when off naming the key;
`fail` when the folder is missing, in a repo, or online-only (attributes monkeypatched) with the `attrib +p` hint;
`warn` when the sync root cannot be told; `--patch fleet.mobile` asks exactly the five keys; `ad-doctor --quiet`
spawns nothing new. Tests: `tests/test_fleet_bridge_doctor.py`, mirroring `tests/test_setup.py:289`, `:470` and
`tests/test_fleet_notify.py:371`. Depends on: B2. Decision: MOB-D4.

**B10 — Events and docs: the four `mobile.*` kinds, `docs/fleet-mobile.md`, every contract row** (S). `KINDS` += 4
with sample lines; `docs/fleet-mobile.md`; the edits of §Where everything is written down that belong to the bridge;
`docs/refusals.md` rows (`shared-docs`) and `REFUSAL_SITE_COUNT` if needed (`tests/test_refusals.py:79`); the rule-8
drift at `docs/fleet-approvals.md:120-125`; `HANDOFF.md:34`. Acceptance: `tests/test_fleet_events.py`,
`tests/test_refusals.py`, `tests/test_entrypoints.py` and `tests/test_fleet_notify.py`'s contract test are green; a
new contract test reads `docs/fleet-mobile.md` and finds every record kind, setting, verb and refusal code; every
`mobile_*` code names a test that exists. Depends on: B1–B9. Decision: MOB-D10.

**Follow-ups.** **B11** — `/settings` shows `fleet.mobile.*` read-only, as `tools` is shown (lanes `serve`,
`settings-page`). **B12** — signed decisions: `FleetDecide` signs `{id, digest, decision, nonce, issued, expires, by}`
with an HMAC key in Azure Key Vault and the laptop verifies with the same key in keyring under `fleet:mobile`; closes
the local-forger gap of `laptop_bridge_design.md` Q13 at the price of one secret and one premium-tier action, so it
waits on a licensing answer.

### MOB-F — Flows: outbox to lists, and the decision flow

**F1 — The five lists from the workbook, environment variables, connections** (S; a tenant sitting). Run
`make_workbook.py`; create the five lists with "Create a list → From Excel" (every column single-line text, `Title`
as given); create the solution with environment variables for the site URL, the five list names, the outbox folder
id, the app id and the recipient; create the four connections (OneDrive for Business, SharePoint, Power Apps
Notification V2, Office 365 Users). Lane: `mobile`. Acceptance: the five lists exist with
exactly the columns of §The model, in that order; `tests/test_mobile_powerapp.py` holds the column tables in
`make_workbook.py` equal to the plan's; the DLP check of `notifications_intune_powerapps.md` KQ8 item 6 is recorded
(all six connectors in one group). Depends on: B3 (the sample records). Decision: MOB-D12.

**F2 — Build `FleetOutboxToLists`** (M; on the tenant). From the build sheet in `mobile/flows/README.md`, every kind
verified with a sample file dropped into `outbox/`. Acceptance: each of the six kinds produces or updates the right
row once, and a second copy of the same file changes nothing; *Include subfolders* is proven to see every subfolder,
or one trigger per subfolder is built and the sheet says so; a `notification` with `severity = action` and `quiet =
false` sends a push whose `Message` contains no repo, ticket or text and whose `Parameters` carry `approvalId`;
`quiet = true` and `info` send nothing; the request-budget arithmetic (requests per run per kind, runs per day at the
laptop's cadences) is recorded against 6,000 per 24 h; the trigger's polling interval is read from Code view and
recorded. Depends on: F1. Decisions: MOB-D11, MOB-D13.

**F3 — Build `FleetDecide`; run-only connections; the response contract; a round trip** (M; on the tenant and the
laptop). Acceptance: the flow's connections are *Provided by run-only user* and the inbox record's `by` equals the
signed-in operator's UPN, not an input; `ok, nonce, inboxFile, error` come back inside 120 s; a decision from a test
button lands in `inbox/` and `ad-fleet mobile apply --dry-run` on the laptop validates it with no refusal; a denial
without a reason is refused by the app before the flow runs; `FleetDecisions` gets its `sent` row and
`FleetApprovals.Status` reads `sent`. Depends on: B4, F1. Decision: MOB-D3.

**F4 — Export the unmanaged solution and prove the import sheet** (S). Export to `mobile/flows/solution/`; the
Workflows JSON reviewed in the repo; environment-variable values removed before export so import prompts for them;
the import sheet followed once on a scratch environment or by a second import after deletion. Acceptance: the zip has
`solution.xml`, `customizations.xml`, `[Content_Types].xml` at its root and one `Workflows/*.json` per flow; both
flows turn on after import with connections mapped; `tests/test_mobile_powerapp.py` parses both definitions and pins
the connector id set recorded here. Depends on: F2, F3.

**F5 — Pushes and deep links on the real phone** (S; a phone sitting). iOS and Android; `Open app = Yes` with
`Parameters`; the `ms-apps:///providers/Microsoft.PowerApps/apps/<appID>?tenantId=…&environmentId=…&restartApp=true`
fallback link recorded in `docs/fleet-mobile.md` for a Teams or Outlook message; the *Block org data* behaviour on
Android recorded. Acceptance: a push arrives on
each OS and a tap opens `ApprovalScreen` with `Param("approvalId")` set; a tap while the app is already open is
recorded (refreshes or not); under the tenant's APP with *Org data notifications* as set, Android's outcome (delivered
or blocked) is written into `docs/fleet-mobile.md` and the runbook; the deep link opens the app, not Edge, or the
device setting that fixes it is recorded. Depends on: F2, P1.

**F6 — The Excel fallback, proven once or dropped** (S). Two workbook copies, one per writer; the app pointed at the
tables; a round trip. Acceptance: one approval decided through the Excel path; the 6-minute lock and the 30 s
propagation observed and recorded; if it fails, `docs/fleet-mobile.md` says lists are the only store and the workbook
is the list source only. Depends on: F3. Decision: MOB-D12.

### MOB-P — The Power App: FleetAgent on phone and tablet

**P1 — Paste the sources into Studio, resolve compile errors and version suffixes, publish v0.1, re-export** (M; on
the tenant). `NOTES.md` first (data sources, display settings, theme, updates), then `App.pa.yaml`, the components,
the screens, through Code view or `compile_canvas`; every `Control:` value replaced with what Studio returned, on
every instance of a type; publish; copy every screen and component back from Code view so the repo mirrors the app.
Lane: `mobile`. Acceptance: every file in `src/` compiles with zero errors; the `Control:` values in the repo are
Studio's; `ParseJSON(QuestionsJson)` renders a question's choices, or `NOTES.md` records why not and what replaced
it; the app opens on the phone from Power Apps mobile and on the laptop in a browser; `tests/test_mobile_powerapp.py`
passes on the re-exported files. Depends on: F1, F3. Decisions: MOB-D14, MOB-D16.

**P2 — The phone pass** (S; a phone sitting). 390×844 and 844×390 on the real phone: every tappable control ≥ 44 px
(48 on Small), text ≥ 16, no sideways scroll on any screen, the reply and reason boxes not hidden by the keyboard
(a scrolling Vertical container with the input near the top; `mobile_ux_requirements.md` AC-PB3), the payload block
scrolling on its own. Acceptance: screenshots of every screen in both orientations attached to the epic; the four
AC-PB1–PB4 rows ticked with what was seen; landscape does not force a page scroll. Depends on: P1.

**P3 — The tablet pass** (S; a tablet sitting). 820×1180 and 1180×820: the two-pane home at ≥ 900 px, a live rotation
with no clipped control, the detail pane hosting Agent and Approval. Acceptance: screenshots in both orientations;
`Parent.Size` flips between `Medium` and `Large` on rotation and the layout follows without a reload. Depends on: P1.
Decision: MOB-D15.

**P4 — Approvals end to end** (M). Approve and deny from the phone → the laptop applies → `FleetApprovals.Status`
and `FleetDecisions.Result` reflect it within one poll; a request past `Expires` is greyed with the sentence; the
buttons disable while a run is in flight and after a decision; a rejected decision (wrong digest, forced on the
laptop side) shows the laptop's `ResultText` verbatim under History and on the card. Acceptance: ten round trips
timed and recorded (the numbers feed V3); `Status` walks `pending → sent → approved|denied`; `rejected` shows the
laptop's words; nothing on the phone can act on an approval twice. Depends on: P1, F2, F3, B4.

**P5 — Replies and question answers reach the agent** (S). A reply to a headless agent arrives by `send`; a reply
to a console by `say`; answers travel as one `answers_prompt`; the result shows under History with `via`. Acceptance:
the agent's stream carries `mobile.reply`; `external = "true"` disables Send with the server's sentence; a `mid_turn`
reply is applied after the turn ends or the History row reads `mid_turn` with `retried_s`. Depends on: P1, B5.

**P6 — Notifications and deep links in the app** (S). `Param` routing in `StartScreen`, the `restartApp` link, the
Alerts tab, the 60 s refresh, `App.BackEnabled`. Acceptance: a push tap lands on the right approval; the Alerts tab
matches `FleetNotifications`; the Android back gesture returns to the list; opening from the All apps list lands on
Home. Depends on: P1, F5.

**P7 — Accessibility and theme** (S). The Accessibility checker at zero errors and zero warnings; `AccessibleLabel`
on every interactive control; `TabIndex` 0 or −1; a `Live = Polite` label for outcomes; contrast 4.5:1 for text and
3:1 for large text and icons in `FleetTheme`; no overlay dialogs (a separate screen or inline); status conveyed by
icon and word; the Intune APP behaviours (PIN, copy/paste, screenshot on Android, offline grace) exercised and
recorded. Acceptance: the checker's screenshot at zero; the contrast pairs listed in `NOTES.md`; the APP outcomes
recorded in `docs/fleet-mobile.md`. Depends on: P1.

**P8 — The CI guard extended with what Studio taught, and `NOTES.md` resolved** (S). `tests/test_mobile_powerapp.py`
gains: one `@version` per control type across `src/`; the `Font` property in the form Studio emitted; no `Sort` on
a non-text column; every list column named in a formula exists in the column tables; the `sample/` records' keys map
onto the columns by the table in `docs/fleet-mobile.md`; the shells rule in spirit (no literal comparison against
`agentstate.STATES` minus the common words, none of `cooldown`, `quiet_hours`, `idle_minutes`, `needs_the_human`).
`NOTES.md` loses every "verify in Studio" line. Acceptance: the guard is plain-tier and runs in the inner loop; each
new check fails on a deliberately broken fixture. Depends on: P1–P7.

### MOB-D — The desk at phone and tablet widths

The audit's ten cards, in its order and with its lanes (`desk_mobile_audit.md` §15). Every card reports the served
payload and "+0 browser tests" in its CAR line. D2–D10 wait for #523 on `main` (the budget).

**D1 — Fresh window: the sidebar toggle works.** Built as **S4**; kept here so the audit's order survives. Lanes
`desk-page`, `serve`. P0.

**D2 — Viewport foundations** (S; `desk-page`, `settings-page` for the meta, `map.html` in no lane). The meta on four
pages; the `100vh → 100dvh` chain; safe-area padding on the footer; `.modelcard` on `100dvh`; `kbd` hidden ≤ 640;
`touch-action: pan-y` on `.tile .head, .pane-rail`. Acceptance: plain CSS and markup guards for each string; the
gutter drag still captures (`tests/test_fleet_gutters.py`); nothing changes at 1280 px and above. Depends on: #523.

**D3 — Coarse-pointer targets and type** (S; `desk-page`). The `@media (pointer: coarse)` block: 44 px on controls,
tabs, pills, rows and head tools; 16 px inputs; the 20 px inward gutter strip; sticky decision rows in `.approval` and
`.asks`; `.approval .row { flex-wrap: wrap }` at ≤ 640. Acceptance: under `has_touch` at 390 px every visible
`button, a[href], input, select, textarea, [tabindex="0"]` measures ≥ 44 px; at 1400×900 with a fine pointer the
desktop's 28 px/13 px scale is unchanged. Tests: folded into `tests/test_fleet_panes.py`'s resize test. Depends on:
D2.

**D4 — The stack: the phone layout of the row** (M; `desk-page`, `shared-docs`). The ≤ 640 rules of §The desk; the
`groupRails` capacity guard; the two-row toolbar; `.tile { overflow-y: auto }`; the inventory row. Acceptance: at
390×844 `#grid.scrollWidth <= clientWidth`, the open pane ≥ 360 px and `data-tier="full"`, every rail's bottom edge at
the grid's foot, `.bottom` inside the viewport; at 844×390 `.bottom` visible; at 820×1180 the row is unchanged from
today; the idle desk makes zero DOM mutations at 390 px; a `MutationObserver` reads zero. Tests: the three viewport
steps in `tests/test_fleet_panes.py`; the idle-desk test of `tests/test_fleet_gutters.py:1094` at 390. Depends on: D2,
D3. Decision: MOB-D17.

**D5 — The sidebar as a sheet** (S; `desk-page`). Full-width `#side` with the scrim; a click on the scrim closes;
`min(480px, 60vw)` on tablets. Acceptance: a tap outside the sheet closes it at 390 px; `Esc` still closes; the row
stays visible beside the sheet at 820 px. Tests: folded into the switcher/board test of S4. Depends on: S4, D2.

**D6 — Touch twins** (M; `desk-page`, `shared-docs`). No drag-reorder under a coarse pointer in the stack; the 400 ms
long-press on a rail = `openBeside`; double-tap on a gutter documented; the keys table and `docs/desk-window.md` rows.
Acceptance: a long-press on a rail at 1180×820 with `has_touch` opens it beside and posts one window write; a 4 px
finger drift on a rail at 390 px starts no reorder; every gesture still has a key. Tests: folded into
`tests/test_fleet_gutters.py::test_every_gesture_again_from_the_keyboard`. Depends on: D4. Decision: MOB-D20.

**D7 — `/map` by touch and `/settings` at 390** (S; map in no lane, `settings-page`). A tap on a checkout's or
agent's `.say` opens it as `Enter` does (`map.js:198-227`); 44 px rows under a coarse pointer; settings rows wrap at
≤ 640 (`app.css:1364-1374`, `1389-1392`, `1408-1409`). Acceptance: `page.tap` on a checkout posts `window {w, open}`
and navigates; `.say` ≥ 44 px under `has_touch`; `/settings` at 390 px has `scrollWidth == clientWidth`. Tests: folded
into `tests/test_fleet_map_page.py:257-284` and `tests/test_fleet_settings_page.py:157`. Depends on: D2.

**D8 — Background and bandwidth** (S; `desk-page`, `serve`). `visibilitychange → refresh() + connect()` beside the
`pageshow` path (`app.js:1594`), closing the old `EventSource` first, because iOS 18 closes a backgrounded stream
without firing `error` (`mobile_ux_requirements.md` AC-S1); gzip `/api/fleet` and `/api/desk` when asked and over
8 KB (`serve.py:2644-2667`; measured 73,960 B → 3,778 B for six agents); a docs row. Acceptance: a hidden-then-visible
page reconnects with its cursor and re-fetches once; `/api/fleet` with `Accept-Encoding: gzip` comes back encoded
over 8 KB and plain under; the loopback poll's CPU is unchanged for a client that does not ask. Tests: plain in
`tests/test_fleet_serve.py`; the reconnect folded into an existing stream test. Depends on: none.

**D9 — Ink off on small screens** (S; docs + `opener.py` now, `ink-core` after #523). Now: `phone` and `tablet` in
`IDE_WINDOWS`, the `ink=off` convention in `docs/fleet-ide.md` and the phone/tablet links. After #523: the gate rule
at `ink.js:99-115` with `source: "narrow"`, inside `INK_BUDGET` (`tests/test_fleet_ink.py:45-67`). Acceptance: a page
opened with `is_mobile` and `has_touch` at 390 px draws no canvas and its verdict reads `narrow`; `?ink=on` still
forces it on; the ink budget test is green. Tests: folded into `tests/test_fleet_ink.py`'s `?ink=off` test. Depends
on: #523 for the gate. Decisions: MOB-D19, MOB-D23.

**D10 — `/m`, the phone page** (M; `serve`, new files under `static/m/`, `shared-docs`). `m.html`, `m.css`, `m.js`
(≈ 250 lines: `refresh()` from `/api/attention`, `connect()` on `/api/events` with `tick`/`onerror` as the desk does,
four POSTs); the `PAGES`/`ASSETS` entries (`serve.py:97-98`, `112-113`); a `PAGE_SCRIPTS` row
(`tests/test_fleet_serve.py:537-540`); its own `M_BUDGET` row like `MAP_BUDGET` (`:415-434`); `w=phone` as its default
window; the inventory rows. Acceptance: the page lists agents, opens one, approves, denies, answers and replies, with
no `innerHTML`, no CDN and every hook present; the desk's budget test is green with the served figure reported; the
components inventory names every `draw*` function. Tests: folded into `tests/test_fleet_serve.py`'s guards and one
existing browser test's viewport step. Depends on: S3, D2–D8, #523. Decision: MOB-D18.

### MOB-V — Verification, docs and the IT ask

**V1 — `docs/windows-verification.md` §Mobile** (S). Rows, each *not yet measured* until run: ten OneDrive round
trips timed laptop → phone → laptop; whether a renamed `.tmp` uploads as a create; `say` while the desktop is locked;
the sync client on a locked desktop (files still upload?); `fleet_snapshot()` cost per bridge tick with no desk open;
`%OneDriveCommercial%` and `HKCU\Software\Microsoft\OneDrive\Accounts\Business1\UserFolder` on this laptop;
`st_file_attributes` on a pinned folder; a push on Android under *Block org data*; deep links under the MDM; push
latency; whether ~30 pending changes per poll bite on a fleet restart. Acceptance: every row has a command or a
gesture, an expected line, and *not yet measured*. Depends on: B7, F2.

**V2 — The IT ask for this lane** (S). In `docs/fleet-mobile.md`, from `notifications_intune_powerapps.md` KQ8: the
APP for Microsoft PowerApps on iOS and Android with the exact setting names (*Send Org data to other apps = Policy
managed apps*, *Restrict cut, copy and paste = Policy managed with paste in*, *Encrypt Org data = Require*, *Restrict
web content transfer with other apps = Microsoft Edge*, *Screen capture = Block*, *PIN for access = Require*,
*Jailbroken/rooted devices = Block access*, *Offline grace period = Wipe data*, *Org data notifications* chosen
knowingly); the iOS managed-devices app configuration with `IntuneMAMUPN`/`IntuneMAMOID`; Conditional Access on *All
resources* with *Require app protection policy* or a compliant device and *Require one of the selected controls*,
Microsoft Flow Service `7df0a125-d3be-4c96-aa54-591f83ff541c` included; Company Portal and Authenticator as required
apps; the DLP check (six connectors in one group; no Advanced connector policy allowlist without them); the
environment and sharing (one user, *User* permission, *Share with Everyone* off); Zscaler SSL-inspection exemptions
for `*.push.apple.com` and `mtalk.google.com`/`fcm.googleapis.com`. Acceptance: nine asks, each with its portal path
and its Learn source; the licensing line (Intune, Entra P1). Depends on: none.

**V3 — The mobile sitting** (M; phone, tablet, laptop). Every V1 row run; photographs into `docs/fleet-mobile.md`; a
go/no-go on push reliability per OS; the round-trip numbers set `fleet.mobile.expire_s`'s default and the heartbeat
interval, and are written beside the defaults. Acceptance: no row reads *not yet measured*; `expire_s` and the
heartbeat are confirmed or changed with the number that changed them; the desk's phone and tablet screenshots from
the real devices sit beside CI's. Depends on: everything above.

**V4 — The Copilot CLI remote-control side track** (S). Record the tenant's "Store local sessions in the Cloud"
policy and the `remoteControl` managed setting; if "View and control" is on, a `fleet.console.remote` opt-in (config
and `ad-setup` only, RESTART) that appends `--remote` to `console_command` (`launch.py:338-368`); never for headless
agents (`-p` is excluded; `launch.py:294-297`). Acceptance: with the setting off nothing changes; with it on a console
launch carries `--remote` and the docs say the approval gate is not surfaced there. Depends on: none. Decision:
MOB-D25.

## Ground rules

1. **The desk's render contract holds**: created once, patched forever, no `innerHTML`, no CDN, no build step, every
   hook present (`docs/desk-components.md:13-59`; `tests/test_fleet_components.py:77-131`;
   `tests/test_fleet_serve.py:371-383`, `505-555`).
2. **Decision 13**: new browser checks fold into existing browser tests, and the slow tiers stay under a tenth of the
   suite (`tests/test_suite_hygiene.py:354-368`). CSS and serve rules get plain guards.
3. **The payload budget is decision 18's and 19's**: the served figure under 200 KiB, never raised; the ink files
   under `INK_BUDGET` (`tests/test_fleet_serve.py:386-412`; `tests/test_fleet_ink.py:45-67`).
4. **The fleet writes only under `~/.agentdata/fleet/` and the configured bridge folder**, which is never a
   repository (`HANDOFF.md:34`; `docs/fleet.md:252`; `tests/test_fleet_e2e.py`; `test_a_folder_inside_a_registered_checkout_or_the_fleet_dir_is_refused_by_name`).
5. **AGENTS.md rule 5**: `.agent/out` rows never leave the laptop; payload previews are redacted and scrubbed and
   `.agent/out` paths reduced to basenames (the scrubber test). **Rule 8**: nothing on the phone can merge a PR or
   close a ticket; neither is a gated kind (`docs/fleet-approvals.md:57-65`).
6. **Shells decide nothing**: the Power App colours by `Role`, shows `State` and `Says` verbatim and errors in the
   supervisor's words; `/m` the same (`tests/test_fleet_shells.py:83-135`; `tests/test_mobile_powerapp.py`).
7. **Every outbox record is allow-listed and scrubbed**: never the run token, a hostname, a path, `USERNAME` or
   `COMPUTERNAME` (`test_the_outbox_payload_never_contains_the_run_token_a_site_hostname_a_unc_path_or_a_raw_agent_out_path`).
8. **Fail closed**: no decision file on any refusal, and the agent's own timeout refuses the write
   (`test_a_digest_mismatch_is_refused_and_no_decision_file_is_written`; `approval.py:112-117`).
9. **Nothing is tunnelled**: the bind, the token and the two tokenless routes are unchanged
   (`tests/test_fleet_serve.py:88-98`; `tests/test_fleet_ide.py:106-113`).
10. **One issue = one branch, Conventional Commits, no `version` or `CHANGELOG` change, builders never merge**
    (`docs/developing-with-agents.md` §2; `tests/test_update.py`; AGENTS.md rules 8 and 9).
11. **Windows facts**: every external file through `textio` (`HANDOFF.md:30`; `tests/test_textio.py:32`); every
    subprocess through `proc` — the bridge spawns none (`HANDOFF.md:31`).
12. **One writer per workbook** when Excel is used (the connector reference, `flows_and_onedrive_bridge.md` Q3), and
    one sweeper per laptop (`mobile_serve_running`).
13. **Measured before relied on**: every phone and tablet claim that headless Chromium cannot prove is a runbook row
    and reads *not yet measured* until V3.

## Build order

- **Wave 0.** S1 and B2, in parallel (no lane between them), and S4 (a `serve` car). Gate: the seven digest tests and
  the scrubber's leak test green; the sidebar trap reproduced then fixed.
- **Wave 1.** B3, then B4 and B5. Gate: the fail-closed matrix green; a matching decision releases `require()`.
- **Wave 2.** B6 (the `serve` car of its train; one per train) and B7, with S2 as the next `serve` car. Gate: a
  transition reaches the outbox exactly once under two streams and the bridge; `S.build()` starts no thread.
- **Wave 3.** B8, B9, B10 on the laptop side, with F1, F2, F3 and P1 in parallel on the tenant (they need B3's sample
  records and B4's `apply --dry-run`). S3 rides here as a `serve` car. Gate: `ad-fleet mobile apply --dry-run`
  accepts a file `FleetDecide` wrote; every `mobile_*` code has its row.
- **Wave 4.** F4, F5, F6; P2–P8; V1, V2, V4.
- **The desk**, after #523 merges on `main`, in the audit's merge order: D2, D3, D4, D5, D6, D7, D8 (D8 can go
  earlier, it is budget-neutral), D9's gate rule, then D10 last.
- **V3 at the end**, once F5 and P4 have numbers.

## Open questions, to be answered on the laptop and the phone

Everything the notes mark **UNVERIFIED**, each with the sitting that answers it:

- OneDrive round-trip latency laptop → cloud → phone → cloud → laptop; the notes estimate ~2 min best, 5–10 min
  typical, unbounded when sync pauses on a metered network or battery saver (`flows_and_onedrive_bridge.md` Q7). Sets
  `expire_s` and the heartbeat. (V1, V3)
- Whether the sync client uploads a file renamed from a never-synced `.tmp` as a create, or whether a staging folder
  is needed (Q8). (V1)
- Whether `say`'s `WriteConsoleInputW` works while the desktop is locked, which decides whether a phone reply ever
  reaches a *console* session while the operator is away (`laptop_bridge_design.md` Q4 gap). (V1)
- Whether the sync client keeps uploading on a locked desktop, and whether `ad-fleet serve` keeps ticking. (V1)
- A push on Android under an APP with *Org data notifications = Block org data*: delivered or blocked
  (`notifications_intune_powerapps.md` KQ2). (F5)
- `%OneDriveCommercial%` and the `Accounts\Business1\UserFolder` registry value, neither found on Learn
  (`laptop_bridge_design.md` Q6); the doctor row degrades to `warn` when both are absent. (V1)
- Studio's `@version` suffixes for `GroupContainer`, `Gallery`, `Badge` and the classic family
  (`powerapps_yaml.md` KQ2). (P1)
- Whether `ParseJSON` over `QuestionsJson` renders choices inside a Gallery template, or the questions need a flat
  `Q1…Q8` column set. (P1)
- The `Font` property's form on modern controls as Studio emits it (KQ2's February 2026 renames). (P1, P8)
- Whether *Include subfolders* on the OneDrive trigger sees every subfolder of `outbox/`, or five triggers are needed
  (`flows_and_onedrive_bridge.md` Q1). (F2)
- Whether the ~30-pending-changes-per-poll issue bites on a fleet restart that rewrites every attention row at once
  (Q1). (V1)
- Power Apps mobile's Intune SDK version, and so whether iOS *Screen capture = Block* has any effect
  (`notifications_intune_powerapps.md` KQ1, KQ7). (P7, V2)
- OneDrive **Create file**'s behaviour on a name collision (Q1 gap); the plan never relies on overwrite. (F3)
- `fleet_snapshot()`'s cost from a bridge tick with no desk open (`laptop_bridge_design.md` Q2 gap). (V1)
- iOS Safari with the keyboard open, input zoom, `contextmenu` and a real finger on the desk, which headless Chromium
  cannot emulate (`desk_mobile_audit.md` §8 gaps). (V3)
- Whether a tap on a tile should keep selecting for every window (`choose()` → `/api/select`, `app.js:383-392`) on a
  phone. Default: keep (MOB-D24). (V3)

## Cost

**Forty cards and two follow-ups**: S 4, B 9 (+ B11, B12), F 6, P 8, D 9 new (D1 is S4), V 4. No premium request
anywhere: every connector is Standard under Microsoft 365 seeded rights, the agents are untouched, and B12's Key Vault
is the one premium-tier item, held back. **Budgets touched**: the served payload (193,485 B of 204,800 at `0b9ec72`;
`main` at ~202.3–202.5 KB with decision 18 refusing to raise it; ~117–123 KB after #523), which is why D2–D10 wait;
`INK_BUDGET` (43,848 of 45,056 B; 1,208 B of headroom for D9's ~200 B gate rule, or after #523); the slow-tier cap of
10 % (every browser check folds; `tests/test_mobile_powerapp.py` is plain); the flow owner's 6,000 requests per 24 h
(≈ 4,000 at the laptop's cadences; the heartbeat at 300 s is what keeps it there); the OneDrive connector's 100 calls
per minute; the 25 MB Excel cap (the fallback only). **On the laptop**: one `fleet_snapshot()` per 5 s tick, unmeasured
(V1); one JSON file per change; a 300 s heartbeat upload. **CI**: +0 browser tests; one plain guard file. **Sittings**:
one tenant sitting (F1–F3), one phone sitting (F5, P2, P4, P6), one tablet sitting (P3), and the mobile sitting (V3)
that closes the runbook. **The desk's stylesheet**: 3–5 KB gzipped for D2–D6; `/m` ≈ 10.5 KB.

## Decisions for the operator

| id | question | default the builders use | reversible? | blocks |
|---|---|---|---|---|
| MOB-D1 | a decision whose `digest` differs from the request: DENIED and stop the agent, or ignore and keep waiting? | DENIED, `reason` "the decision names a different request (digest mismatch)" | yes, one branch in `require()` | S1 |
| MOB-D2 | the Host allow-list on every request, `/open` and `/api/ping` included, allowing `127.0.0.1`, `localhost` and `[::1]` with the port? | yes, all three, every route | yes | S2 |
| MOB-D3 | `fleet.mobile.expire_s` default 900 s, bounds 60–3600? | 900, 60–3600 | yes, a number | B4, F3 |
| MOB-D4 | a pinned (Always available) `inbox/`: doctor `fail`, or `warn`? | `fail` for `inbox/`, `warn` for the rest | yes | B9 |
| MOB-D5 | the bridge as a thread in `ad-fleet serve`/`quickstart`, with `watch` as the fallback, or `watch` only? | thread in serve; `watch` refuses beside a live serve | yes, with effort: the loop is one function either way | B7 |
| MOB-D6 | the verb is `init`, not `pair` (no key exchange happens)? | `init` | before B10 ships; a rename after | B8 |
| MOB-D7 | a phone reply during a turn is retried every tick until `expires`, which the desk does not do? | yes, with `retried_s` in the result | yes | B5 |
| MOB-D8 | `force` (the budget override) is never honoured from the phone? | never | yes, not recommended | B5 |
| MOB-D9 | the #356 change: a desk opened after the bridge swept shows the drawer, not fresh `notify` frames? | yes | yes, revert to per-stream sweeps | B6 |
| MOB-D10 | rewrite "Mobile is out" (`docs/fleet-notifications.md:137-138`) and "access from another machine — out of scope" (`docs/fleet-dashboard.md:547-548`) to say the bridge is the one mobile path and changes neither the bind nor the token model? | yes, both sentences | yes, docs | B10 |
| MOB-D11 | a heartbeat every 300 s as an immutable dated file, and every other record immutable and uniquely named? | yes | yes, a constant and a naming rule | B3, F2 |
| MOB-D12 | SharePoint lists as the store, the workbook as the list source and the Excel fallback? | lists; Excel proven once in F6 or dropped | yes: one YAML serves both | F1, F6 |
| MOB-D13 | relay `info` notifications to the phone? | no: `action` and `alert` only | yes, a Switch case | F2 |
| MOB-D14 | one Tablet-format responsive app, or a phone app and a tablet app? | one app | no: a second app is a second source tree | P1 |
| MOB-D15 | the two-pane threshold at 900 px (`ScreenSize.Medium` at the tablet defaults)? | 900 | yes | P3 |
| MOB-D16 | one 60 s auto-refresh Timer, on the home screen? | 60 s, one Timer | yes | P1 |
| MOB-D17 | the stack breakpoint at 640 px (the key map's existing breakpoint)? | 640 | yes | D4 |
| MOB-D18 | `/m` at all, and only after #523? | yes, last, after #523 | yes, an order | D10 |
| MOB-D19 | ink off on a coarse pointer under 900 px by a gate rule, the `ink=off` convention until #523? | yes, both halves | yes | D9 |
| MOB-D20 | touch drag-reorder replaced by the tap path in the stack (reorder stays on `Alt+arrows`)? | yes | yes | D6 |
| MOB-D21 | a `mobile` lane (`mobile/**`, `tests/test_mobile_powerapp.py`) in the frozen `.github/agent-lanes.json`? | proposed; the tree is one exclusive lane by convention until approved | yes | nothing; needs the `relay` edit |
| MOB-D22 | `fleet.mobile.folder` as the one exception to "the fleet writes only under `~/.agentdata/fleet/`", never defaulted, refused in any checkout? | yes, written into `HANDOFF.md:34` and `docs/fleet.md:252` | only by removing the bridge | B2 |
| MOB-D23 | `phone` and `tablet` join `IDE_WINDOWS` so `ad-fleet open --all` skips them? | yes | yes | D9 |
| MOB-D24 | a tap on a tile keeps selecting for every window (`choose()`), so a phone glance re-points the laptop's inspector? | keep | yes | D4, V3 |
| MOB-D25 | `fleet.console.remote` (adds `--remote` to console launches) if the tenant's policy is "View and control"? | off; opt-in; never for headless agents | yes | V4 |

The operator's sentences are in §Why this exists, verbatim. What they asked for and did not decide is this table and
§Open questions; every pushback in §Where this plan pushes back is a proposal, undone by a sentence from the operator.
