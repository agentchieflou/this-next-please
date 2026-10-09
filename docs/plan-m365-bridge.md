# Plan: the Microsoft 365 lane — Power Automate as the second relay, SharePoint and OneDrive as sources, and the loop between Microsoft agents and Copilot agents

_Status: PLANNED (proposed 2026-10-09), written at the operator's request the day 0.19.0 shipped (PR #657): "ground ourselves
in our advancements, but commit to continuing forward, to breaking down more walls". The occasion is the coming
onboarding onto a Power Automate workspace. Nothing here is built; every tenant fact is marked **verify** until a
sitting on the laptop records it, the way [plan-mobile.md](plan-mobile.md) and
[windows-verification.md](windows-verification.md) did for the first bridge._

## 1. Where we stand

The point of a plan written on a good day is to say exactly what the good day was, so the next one is measured
against it rather than remembered.

| Capability | State today | Measured by |
|---|---|---|
| The skill route network | 50 skills, 6 routers, 1 bounded spike; every leaf reachable from a router or a hand-off | `tests/test_skill_handoffs.py`; [plan-routing-expansion.md](plan-routing-expansion.md) §The network as it stands |
| The marketplace | every installed skill, its uses, repositories and success rate; a configurable source (GitHub, any git URL, a folder) synced and refreshed from `/skills` | [fleet-skills.md](fleet-skills.md); 0.19.0 |
| Jira, Confluence, Bitbucket | pncli directly for what it does; `ad-jira`, `ad-confluence publish` and `ad-git pr` extend it (history, workflow writes, gated page and PR writes); the token from the environment, pncli's config or the keyring | [pncli-parts.md](pncli-parts.md); 0.20.0 |
| Power BI | PBIP/TMDL projection, validator, authoring verbs, and since 0.19.0 any property patched and checked against Desktop 2.157's schema; the Desktop Bridge; service parity | [power-bi-agentic.md](power-bi-agentic.md); [pbir-authoring.md](pbir-authoring.md) |
| Documents | DPM hand-back, label extraction, Content Understanding analyzers (Foundry), folder sorting by plan | `dpm-router`; `agentdata/connectors/content_understanding.py` |
| The fleet | several headless Copilot agents, one per repository, one page; the approval gate; the normalized event stream; the Command Center; the handoff (`.agent/in/<KEY>/`) | [fleet.md](fleet.md); [fleet-approvals.md](fleet-approvals.md); [fleet-handoff.md](fleet-handoff.md) |
| **The first Microsoft 365 bridge** | the mobile lane: laptop → OneDrive-synced outbox → `FleetOutboxToLists` → five Lists → the FleetAgent canvas app → `FleetDecide` → OneDrive inbox → the laptop applies. Standard connectors only, no socket on the laptop, every record allow-listed and scrubbed, fail closed | [fleet-mobile.md](fleet-mobile.md); `agentdata/fleet/bridge.py`; `tests/test_fleet_bridge.py` |
| The suite | 4,892 tests in the inner loop, about 100 s on four cores; the browser tier sharded three ways | [testing-this-repo.md](testing-this-repo.md) |

Two sentences in this repository are the walls this plan is about, and both were written as *constraints*, not
complaints:

- `agentdata/fleet/catalogue.py`: *"The corporate policy disables MCP. A vector store only pays off if a model can
  query it, and the only query path a model has on this laptop is an `ad-*` command printing TOON."*
- [plan-routing-expansion.md](plan-routing-expansion.md) row 16: *"send a summary to the team", "post in Teams" —
  nothing, correctly: the fleet has no write path to mail or chat, and should not grow one from a skill.*

Both were right under the rules that held. The mobile lane already proved the way round them without breaking a
rule: the laptop never opens a socket; Microsoft 365 is the relay; a flow does on the tenant what the laptop may not;
the record on OneDrive is the API. **This plan is that shape, generalised**: from one app (approvals on a phone) to
every surface the workspace opens, and from one direction (decisions in) to both (context in, results out).

## 2. What the workspace is expected to open, and what to verify first

The onboarding is expected to bring a Power Automate environment of our own rather than the seeded personal one.
What that changes is a matter of fact on the tenant, not of design, so the first slice is a sitting that records it:

| Question | Why it matters | How to find out (**verify**) |
|---|---|---|
| Which connector classes the environment licenses: Standard only, or Premium (HTTP, custom connectors, HTTP with Microsoft Entra ID) | Premium is the difference between "a flow does it for us" and "the laptop can call a flow or Graph directly" | the environment's licence page; make one flow with an HTTP action and see whether it saves |
| Whether the environment's DLP policy keeps SharePoint, OneDrive, Teams, Outlook, Power BI, GitHub and HTTP in one business group | the mobile lane needed six connectors in one group; this lane needs more | the DLP policy as shown in the admin centre, or the first flow that refuses to save |
| Whether `az account get-access-token --resource-type ms-graph` returns a token for the signed-in user | `ad-pbi` already signs in through the Azure CLI; a Graph token the same way would give the laptop a *direct* read path for SharePoint and OneDrive (Files.Read, Sites.Read.All) with no new credential and no socket the policy does not already allow | run it; record the scopes in the token |
| Whether Copilot Studio is licensed, and whether its agents may call flows and be triggered by Teams, SharePoint and Outlook events | this is the "triggered, scoped MS agent" half of the loop | the maker portal; make one agent with one trigger |
| Whether the GitHub connector in Power Automate is permitted, and against which account | the other half of the loop: a flow that can open an issue, comment on a PR or dispatch a workflow | the connector list; one flow that reads this repository's open PRs |
| Flow run quotas and the OneDrive connector's call limits for the environment | the mobile lane budgets about 4,000 OneDrive calls a day at the laptop's cadence; a context lane adds more | the environment's capacity page |
| Round-trip time through OneDrive sync and a flow trigger | the mobile runbook's M1 row, still *not yet measured* | [windows-verification.md](windows-verification.md) §Mobile, M1 |

Nothing below is built before this table has a date and a host against every row.

## 3. The model: three paths and one rule

The rule is the mobile lane's: **the laptop never opens a socket to anything but what the policy already allows
(the Azure CLI's sign-in, the OneDrive sync client); Microsoft 365 is the relay; every record is allow-listed,
scrubbed, immutable and uniquely named; every write to a system of record is behind the approval gate; a flow
that cannot verify a record writes nothing.** What is new is what travels.

### 3a. Context in — "on the fly RAG" without a vector store

The agent asks, in the words of the ticket, for what the tenant knows: *"the runbook for the UAT refresh"*, *"the
contract this DPM run came from"*, *"last quarter's deck on committed points"*. Two routes answer, chosen by probe:

- **Direct**, when the Graph token works (§2 row 3): a new command `ad-m365` with read verbs only —
  `search --q <words> [--site <url>] [--kind docx,pptx,pdf,page]`, `drive ls <path>`, `drive get <item> --out`,
  `sp list <site> <list>`, `page get <url>` — through Microsoft Graph, through `agentdata/proc.py` and `textio`,
  into `.agent/out/` as files and TOON. Cheap (reads, one command), fast (seconds).
- **Relayed**, when it does not: the agent writes a `context-request` record to the outbox (query, site, kinds,
  the ticket, a digest); the flow `FleetContextFetch` runs the search on the tenant, copies the top N files into the
  bridge folder's inbox under the request's id, and writes a `context-result` record naming them; the laptop's
  applier moves what it verifies into `.agent/in/<KEY>/context/`. Medium (one round trip; minutes).

Either way the files land where the handoff already puts the operator's attachments
([fleet-handoff.md](fleet-handoff.md) §Attached files), so **AGENTS.md rule 3 holds**: the context belongs to the
ticket's repository and nothing else reads it. Then the pieces that exist do the rest: Content Understanding or
label extraction pulls the named fields out of a contract (`dpm-router`), `ad-view` projects a workbook, the
catalogue indexes the result for the operator's `ad-fleet where` (a new allow-listed kind, `context`, with the same
credential refusal as every other kind). The "RAG" is the ticket's own folder, read by the agent that owns the
ticket, fetched on demand with a frontier model's judgement of what to ask for. That is the retrieval the
catalogue's docstring said could not be had; it can, because the laptop is not the one searching.

### 3b. Results out — reversing row 16, with the gate

A finding, a UAT table, a page of release notes, a screenshot of the fixed visual: today it reaches a person
through Jira and Confluence only. The outbox gains `publish` records: *post this Markdown as a Teams message in
channel X*, *send this summary to these people*, *put this file in this SharePoint library*, *update this row in
this List*. The flow `FleetPublish` does the write on the tenant, under the maker's identity, and writes a
`publish-result` record back (the message id, the item URL) so the agent can cite it. Every `publish` is a
`confluence-publish`-class approval: dry-run first, the operator's click, then the record. Row 16's refusal becomes a
route, and nothing the fleet never had (a mail credential, a Teams token) is added to the laptop.

### 3c. The loop — triggered Microsoft agents and Copilot agents, both ways

The two halves exist separately. The fleet starts a GitHub Copilot CLI agent on a ticket and watches it; a
Copilot Studio agent or a plain flow can be triggered by a Teams message, a SharePoint upload or an email and can
call flows. Closing the loop is two record kinds and one flow each way:

- **In**: a trigger on the tenant (a message in a channel, a file dropped in a library, a form submitted, a mail
  with a subject pattern) runs `FleetIntake`: it writes an `intake` record (source, actor, text, links, attachments
  copied into the inbox). The laptop's applier turns it into what the Command Center already seats: a ticket
  (`ad-jira match`, then `jira-create` when nothing matches and the project allows it) with a brief and its
  attachments, at a free agent of the right repository. The agent's first question, if it has one, goes **out** as
  an `ask` on the outbox, which the mobile lane already relays to the phone, and which `FleetPublish` can relay to
  the Teams thread the request came from.
- **Out**: `done`, `blocked` and `needs-you` on the stream become `publish` records to the same thread or the same
  List row, so the person who asked in Teams sees the answer in Teams. The agent on the tenant side, if there is
  one, reads the List row like any other state and can continue its own flow.

What the laptop gains from this is exactly nothing new to defend: the same bind, the same token, the same
allow-list, two more record kinds in `docs/fleet-mobile.md`'s table. What the operator gains is that the three
places work arrives (a Jira ticket, a Teams message, a document in SharePoint) all end at an agent with the right
context, and the answer goes back where the question was asked.

## 4. The route network: what grows

A sub-router and its leaves, in the order the friction counts will most likely want them. Every leaf is `< 120`
lines, imperative, ends in a STOP or a hand-off, and names its `ad-doctor` precondition row.

| Router row (in `router`) | Sub-router | Leaf | Cost | Depends on |
|---|---|---|---|---|
| SharePoint, OneDrive, Teams, Outlook, "find the document", "what does the policy / runbook / deck say", "the file in the library", a flow, Power Automate | `m365-router` (new) | | | §2 |
| | | `context-fetch`: search, fetch, land in `.agent/in/<KEY>/context/`, cite paths; never summarises what it did not fetch | cheap (direct) / medium (relayed) | 3a |
| | | `sharepoint-read`: one library or page by URL, to `.agent/out/`; read-only | cheap | 3a |
| | | `m365-publish`: Teams message, mail, library upload, List row; dry-run, approval, record, the result URL in the hand-off line | dear (gated write) | 3b |
| | | `flow-run`: start a named flow with a record, wait for its result record, report; never a flow this project's `AGENTS.md` does not name | medium | 3c |
| | | `intake-triage`: what `jira-triage` is for a Jira key, for an `intake` record: who asked, where, what they attached, which ticket it is or becomes | medium | 3c |
| Confluence, "what does the page say" (row 1 of the routing plan, still mis-routed) | `m365-router` or the existing row | `confluence-read`: `pncli confluence get-page` to `.agent/out/`, read with `ad-view` | cheap | pncli |
| "who uses this report", "the dataflow", "the lakehouse table" (rows 13–14) | `pbi-router` | `pbi-usage`, `fabric-items`: through the Power BI connector or `ad-pbi` once the tenant exposes the items | medium | tenant facts |

Everything the marketplace shipped in 0.19.0 is what makes this shippable: the new skills arrive by `sync` from the
configured source, the ledger says which of them get used and where, and a skill nobody runs is a row to retire.

## 5. Slices

| Slice | What | Cost class | Gate |
|---|---|---|---|
| **M-0** The sitting | every row of §2 answered on the tenant, recorded in [windows-verification.md](windows-verification.md) §Microsoft 365; `ad-doctor` gains `m365 / graph token` (ok, skip, or fail with the scope it lacks) | one sitting | nothing else starts without it |
| **M-A** Context in, direct | `ad-m365 search|drive|sp|page` (read-only), the `context` kind in the handoff and the catalogue, `context-fetch` and `sharepoint-read`, `m365-router` | medium | M-0 says the Graph token works |
| **M-B** Context in, relayed | `context-request`/`context-result` records, `FleetContextFetch`, the applier; the same two skills, routed by the doctor row | medium | M-0 says the connectors are there; M-A's skills exist |
| **M-C** Results out | `publish`/`publish-result` records, `FleetPublish`, `m365-publish` behind the gate; row 16 rewritten as a route | dear | the approval-integrity seams of #537 (digest, `via`, `by`) |
| **M-D** The loop in | `intake` records, `FleetIntake` (Teams, SharePoint, Outlook, Forms triggers), the applier → Command Center seating, `intake-triage` | medium | M-C (the first answer goes back the same way) |
| **M-E** The loop out | `done`/`blocked`/`needs-you` → `publish` to the originating thread or row; a Copilot Studio agent, if licensed, reading the Lists | medium | M-D |
| **M-F** The rest of the routing plan's shelf | `confluence-read`, `pbi-usage`, `fabric-items` as the tenant permits | cheap–medium | their verbs |

OneNote rides these slices rather than adding one: the research is in [spike-onenote.md](spike-onenote.md)
(context from a named section, a fleet log page appended behind the gate, an Agent inbox section as intake, and
Copilot Notebooks as the reasoning surface we write for but do not build).

Each slice follows the mobile lane's method: the contract page first (`docs/fleet-m365.md`, a sibling of
[fleet-mobile.md](fleet-mobile.md), read by a test for every record kind, setting, verb, event and refusal code),
then the laptop side with its tests, then the tenant side as a sitting that records what it saw.

## 6. Ground rules that do not move

1. No socket from the laptop beyond the Azure CLI's sign-in and the OneDrive sync client. A Graph call rides the
   same token path `ad-pbi` already uses; if the token is refused, the relayed path is the path.
2. Reads first, writes last, and every write behind the approval gate with a digest, `via` and `by`.
3. Rule 3 holds: context lands in the ticket's `.agent/in/<KEY>/`, never in a shared store an agent can read
   across projects. The catalogue indexes it for the human only.
4. Allow-listed, scrubbed, immutable, uniquely named records; fail closed; no decision or publish on an
   unverifiable record. The record formats live in one contract page, read by one test.
5. Nothing fetched is summarised unseen: a skill cites the path it read, or says it did not read it.
6. The budget is measured, not estimated: flow runs, connector calls and premium requests per ticket go on the
   meter ([plan-meter.md](plan-meter.md)) before any slice after M-A is cut.
7. Premium is a decision for the operator, named in §7, never assumed by a slice.

## 7. Decisions for the operator

| | Question | Default until answered |
|---|---|---|
| M365-D1 | Pay for Premium connectors (HTTP, custom) if the environment does not include them? | no: build the relayed path first; the direct path exists only where the Graph token already works |
| M365-D2 | Which Teams channels and SharePoint libraries may `FleetPublish` write to? | a named allow-list per project in `AGENTS.md` (`m365_publish_targets`); none by default |
| M365-D3 | Which triggers may start work (`FleetIntake`)? | one channel and one library per project, named in `AGENTS.md`; mail and Forms off until asked |
| M365-D4 | A Copilot Studio agent at all, or flows only? | flows only until the licence is confirmed; the record kinds are the same either way |
| M365-D5 | May context fetched for a ticket be indexed by the catalogue for `ad-fleet where`? | yes, with the credential refusal; the operator can turn the kind off per project |
| M365-D6 | Does the `confluence-publish` approval kind cover `publish`, or does it get its own kind? | its own kind, `m365-publish`, so the phone can show it in its own words |

## 8. What is left to improve on, honestly

The operator's question was *"what's there left to improve on here?"*. Beyond this lane:

- **The two mis-routes are still mis-routed** (`confluence-read`, `pr-review`): cheap, read-only, and waiting on a
  verb or a client that nobody has written.
- **Confluence and Bitbucket use pncli, as intended.** 0.20.0 settled it: pncli is used directly for what it does,
  and the writes it cannot gate are extensions (`ad-confluence publish`, `ad-git pr`) waiting only on the operator
  pinning the two verbs from `pncli <product> --help`.
- **The marketplace's GitHub sync and catalogue were tested with folder and local-git sources only**; the first
  real `gh skill install` from `/skills` is a sitting.
- **The ledger reads Copilot's sessions and the fleet's streams, not Claude Code's transcripts**; a second source
  is a day's work and a fairer count.
- **On the world**: agents-as-people and placement by state now need the operator's own people folder; nothing is
  lost, but nothing there is maintained either. play-sports' Track R is where that thread continues.
- **The play-sports runner has not picked up a job since its PR opened**; CI there is a claim until it does.
- **Measurement debt**: the routing plan's M5–M8 (what `balance` costs per turn) and the mobile lane's M1–M6 are
  still *not yet measured*, and this plan adds a column of its own. A sitting that clears them is worth more than
  any slice above.

The commitment is the one the catalogue's docstring made in the other direction: write the constraint down, build
to it, and when the constraint moves, say so in the same file and move with it.
