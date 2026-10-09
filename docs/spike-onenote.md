# Spike: what can the fleet do with OneNote?

_Status: PLANNED (spike opened 2026-10-09 at the operator's request: "Open up a research spike onto what we can do
with OneNote"). This page is research only and nothing in it is built. It is a branch of the Microsoft 365 lane,
[plan-m365-bridge.md](plan-m365-bridge.md), and inherits that plan's rules. The facts below come from Microsoft's
documentation as of this date, and each one names its source. The doc pages are not the tenant, so every claim
about what **our** environment allows is marked **verify** until the M-0 sitting records it. This follows
[fleet-spike.md](fleet-spike.md)'s method: measured beats read._

## 1. The answer, first

OneNote is a good fit for **people's half of the loop**: meeting notes, runbooks someone keeps in a notebook,
whiteboard photos, a page the operator scrolls on the phone. It is a poor fit for **machine state**, which
SharePoint Lists already hold in the mobile lane. So the spike recommends three uses, ranked by what they cost
against what they return. It also names one use to refuse:

| # | Use | Direction | Path that works under the default rules | Worth it? |
|---|---|---|---|---|
| 1 | **A project notebook as ticket context.** Read a named section's pages into `.agent/in/<KEY>/context/` | in | relayed (Standard connector), or direct if the Graph token carries `Notes.Read` (**verify**) | **yes, first.** It is reads only, slots into M-A/M-B, and needs no new slice |
| 2 | **The fleet's log as a notebook page.** Append each `done`/`blocked`/`needs-you` to one page per project per day, with open asks as OneNote to-do tags | out | relayed `Update page content`, behind the gate | **yes, second.** It turns the operator's notebook into a reading surface that Copilot can reason over (§5) |
| 3 | **An "Agent inbox" section as intake.** A new page there becomes an `intake` record | in (loop) | relayed only: the connector's *When a new page is created in a section* trigger | **yes, but slow**. The trigger polls every 20 minutes, so this suits "when you get to it" requests, not urgent ones |
| ✗ | OneNote as the store for approvals, heartbeats or any record the laptop verifies | — | — | **no.** Pages are HTML that people edit. Lists are typed, filterable and already wired (`FleetOutboxToLists`) |

Two facts decide most of this:

- **The direct path is delegated only.** App-only access to the OneNote API ended on 2025-03-31.
- **The Standard OneNote (Business) connector can do every action listed above.** So the relayed path needs no
  Premium licence, and M365-D1's default ("no Premium") holds.

## 2. OneNote as an API: what Microsoft documents

| Fact | Consequence for us | Source |
|---|---|---|
| Graph OneNote roots: `/me/onenote`, `/users/{id}/onenote`, `/groups/{id}/onenote`, `/sites/{id}/onenote`; under each are `notebooks`, `sections`, `sectionGroups` and `pages` | A team notebook in a SharePoint site or a Microsoft 365 group can be read the same way as a personal notebook. The project notebook can belong to the team, not to the operator | Graph `onenote` resource type |
| **Delegated permissions only.** App-only support was retired on 2025-03-31. Scopes: `Notes.Read`, `Notes.Create`, `Notes.ReadWrite`, `Notes.Read.All`, `Notes.ReadWrite.All` | No daemon or service principal. A call is either the signed-in user's token or a flow running as the maker. This matches rule 1 of the M365 plan exactly | Graph permissions reference (Notes); OneNote app-only deprecation notice |
| `GET pages/{id}/content[?includeIDs=true]` returns the page as **HTML**. Images and files are `resources/{id}/$value` | Context arrives as HTML, so we need an HTML-to-text step before an agent reads it. `includeIDs=true` gives the `data-id` / generated ids a later PATCH can target | Graph *Get OneNote content and structure* |
| List pages **per section** (`sections/{id}/pages`): the default page size is 20, `$top` goes up to 100, and paging uses `@odata.nextLink`. Microsoft's best practice says not to call `/me/onenote/pages` across everything, because that returns 400 once there are too many sections | Address context **by section**, never "search all my notes". The verb takes a section id or URL | OneNote API best practices |
| `POST sections/{id}/pages` takes HTML or multipart. In multipart, `data-render-src` renders an attached PDF or a web page to images on the page, and OCR runs on images | We can publish a PDF report (the UAT table, a Power BI export) as page images the operator can read on the phone. The OCR claim is Microsoft's, **verify** | Graph *Create OneNote pages*; *Add images and files* |
| `PATCH pages/{id}/content` takes a JSON array of commands. `target` is `body`, `title`, `#<data-id>` or a generated id; `action` is `append`, `insert`, `prepend` or `replace`; `position` is `before` or `after` | A daily log is one page with one `div data-id="fleet-log"` that we **append** to. We never rewrite a page a person may have edited | Graph *Update OneNote page content* |
| Note tags are `data-tag="to-do"`, `"to-do:completed"`, `"important"`, `"question"` and others from a fixed set. Custom tags are not supported | An agent's open ask can show up as a to-do checkbox in the operator's notebook. Whether ticking the box can flow back to us is open; §7 **verify** | Graph *Use note tags* |
| A section holds a limited number of pages; over the limit returns **507**. A section name is at most 50 characters and some characters are forbidden | One page per day per project, rolled into a section per month: about 31 pages, far under the limit. Names are built by code, never typed | Graph OneNote error codes; create-section docs |
| Throttling: **120 requests/min and 400/hour per app per user**, 5 concurrent. Microsoft documents **no `Retry-After`** on a 429 | Budget 400 an hour, which is much tighter than the OneDrive lane. Back off with a fixed schedule, because there is no header to read. Batch appends: one PATCH per flush, not one per event | Graph OneNote throttling / best practices |
| Full-text search inside work notebooks: this spike found **no documented Graph route**. The Search API's entity types list `driveItem` (files and pages in SharePoint/OneDrive), not OneNote page content | "Find the note about X" is not a query we can send. The operator names a section, or the M-A search finds the `.one` file's notebook. **verify** at M-0 whether a `driveItem` search hits notebook content | Graph Search API, entity types |

### The OneNote (Business) connector, the relayed path

From the connector reference:

- **Licence and limits:**
  - Class is **Standard**, available in Power Automate, Power Apps, Logic Apps and Copilot Studio.
  - Throttling is **100 calls per 60 s per connection**.
  - Triggers poll every **1200 s**.
- **Actions:**
  - Create a page in Quick Notes
  - Create page in a section
  - Create section in a notebook
  - Delete a page
  - Get page content (not available in Power Apps)
  - Get pages for a specific section
  - Get recent notebooks
  - Get sections in notebook
  - Update page content (target, action, position, content: the same commands as Graph PATCH)
- **Triggers:**
  - When a new page is created in a section
  - When a new section is created
  - When a new section group is created
- **Known limits:**
  - The account needs SharePoint's **Use Remote Interfaces** ("UserRemoteAPIs") permission on the site that holds
    the notebook. This is the first row to **verify**.
  - The page title is set from the HTML `<title>`; there is no title parameter.
  - A section is given as its API URL, not its name.

## 3. Two paths, chosen by probe, as the plan already does

**Direct (M-A).** `az account get-access-token --resource-type ms-graph` already appears as row 3 of the plan's
§2. OneNote adds one question to that row: **do the token's `scp` claims include a `Notes.*` scope?** The Azure CLI
is a first-party client, and Microsoft fixes its pre-authorised Graph scopes; we cannot add one. So there are two
outcomes:

- **The claims include `Notes.Read`:** a `note` verb family on the planned `ad-m365` (below) is cheap.
- **They do not:** the only way to get the scope is our own Entra app registration with delegated `Notes.Read`.
  That is a new credential and a consent prompt, which is a decision for the operator (OneNote-D1, §8), not
  something a slice may assume.

**Relayed (M-B).** The flow `FleetContextFetch` gains a `source: onenote` branch:

1. Run *Get pages for a specific section* on the section named in the request.
2. Run *Get page content* on each of the top N pages.
3. Write the HTML files into the inbox under the request id.

This needs no Premium licence, no new credential and no socket. It costs one round trip, measured in minutes.

Either way the output lands in `.agent/in/<KEY>/context/onenote/<section>/<page-id>.html` plus a `.txt` beside it,
and the agent reads the `.txt`. AGENTS.md rule 3 holds, because the notebook's content belongs to that one ticket.

### The verbs, if direct works (proposed; read-only except the last)

| Proposed verb | Graph call | Lands in |
|---|---|---|
| `ad-m365 note books` | `GET me/onenote/notebooks?$select=id,displayName,links&$expand=sections($select=id,displayName)` | TOON: notebook, section, id |
| `ad-m365 note pages <section>` | `GET sections/{id}/pages?$select=id,title,lastModifiedDateTime&$top=100`, following `nextLink` | TOON: page id, title, modified |
| `ad-m365 note get <page> [--out]` | `GET pages/{id}/content` plus each `resources/{id}/$value` | `.agent/out/` HTML, text and images |
| `ad-m365 note append <page> <file.md>` | `PATCH pages/{id}/content` `[{target:"#fleet-log", action:"append", content:<html>}]` | **gated** as an `m365-publish` approval (M365-D6) |

The Markdown → HTML step should reuse `agentdata/confluence.py`'s parser (`to_storage` already walks headings,
lists, tables and code). OneNote needs a sibling emitter rather than a second converter, because OneNote's input
HTML has no Confluence macros: code becomes `<pre>`, and a panel becomes a bordered `<table>`. The rule "one
parser, two emitters" comes from AGENTS.md's *consume what exists*.

## 4. The three uses in detail

### 4.1 Context in: the project notebook

The case: the runbook for the UAT refresh, the decisions from last Tuesday's stand-up and the screenshot of the
broken visual all live in a team notebook, not in Jira or Confluence. Today an agent cannot see them, and the
operator pastes them in. With this use:

- The project's `AGENTS.md` names the notebook and the sections an agent may read (`onenote_context_sections`).
  Following M365-D2's shape, the allow-list is empty by default.
- `context-fetch` (the M-A leaf) accepts `--kind page` and a section from that list. It fetches at most N pages,
  newest first, and cites each path it read (M365 plan, rule 5).
- Images on a page come down as files beside the text. Where the OCR claim holds, the page's HTML carries the
  recognised text in a `data-*` attribute. Microsoft documents this for images uploaded through the API, and we
  should **verify** whether it also covers images pasted in by a person on the phone.

The cost is cheap if direct, medium if relayed. The risk is low: the use is read-only, scoped by allow-list, and
lands in the ticket's folder.

### 4.2 Results out: the fleet log page

The case: the operator's day already happens partly in OneNote, so the fleet's account of the day can live there
too.

- **The page:** one page per project per day, `Fleet · <project> · <date>`, in a section `Fleet <yyyy-mm>`
  (13 characters, well under the 50-character limit).
- **Creating it:** the first event of the day creates the page with a single `<div data-id="fleet-log">`.
- **Each flush:** every following flush is one `append` to that div. A flush is batched, at most one per 10
  minutes per project, so a busy day stays under 400 calls an hour with room to spare.
- **What a line holds:** one line per `done`, `blocked` or `needs-you`, carrying the ticket key, the one-line
  summary and the link the stream already carries.
- **Open asks:** a `needs-you` line is written with `data-tag="to-do"`.
- **What is never written:** credentials, paths outside the project, or anything the bridge's scrubber would
  refuse. The same scrubber and the same allow-list apply.

This is an `m365-publish` write, so it goes through dry-run, the gate and then the record. Under M365-D2 the
target is a named section per project.

One deliberate limit: we **only append**. A page that people annotate is theirs, and `replace` on a page we did not
create in that same run is refused by the verb, not by convention.

### 4.3 Intake: the Agent inbox section

The case: someone snaps a whiteboard on the phone, or types "can an agent look at why the KPI card is blank", into
a section called **Agent inbox**. OneNote on the phone already supports multimodal capture, so a photo becomes a
page.

- **Starting the flow:** `FleetIntake` (M-D) adds the trigger *When a new page is created in a section*.
- **The record:** it writes an `intake` record carrying the source `onenote`, the page URL, the author, the text
  and the images copied into the inbox.
- **Seating the work:** the applier then seats it like any other intake (`ad-jira match`, then a ticket).
- **The answer:** it goes back as an `append` to **that page**, under a `data-id="fleet-reply"` div, so the person
  who asked in OneNote sees the answer in OneNote.

The latency is the cost. Microsoft documents a 1200 s poll, so the expected wait is about 10 minutes and the worst
case about 20 before anything starts. That is why this use comes third, and why M365-D3 keeps it off until a
project names the section.

## 5. Copilot in OneNote: the reasoning surface we do not build

Microsoft's release notes from this year describe Copilot Notebooks:

- reached OneNote on the web in July;
- gained Teams meetings as references in August;
- were redesigned in the Microsoft 365 Copilot app in September;
- now include mind maps;
- also come with Copilot quick actions in OneNote (Rewrite, Summarize, Create To-Dos).

Separately, the *Work IQ* REST endpoint is pitched as the way agents and workflows reach the same grounding. This
spike did not test it, and it should be **verified** before anything leans on it.

What this means for us is a cheap win, not a build: **if the fleet log pages exist (use 2), a Copilot Notebook that
references them, the project notebook and the week's meetings can answer "what did the agents do on the
dashboard this week, and what did we decide about it?"** That question has to cross three surfaces, and no tool of
ours crosses them. The fleet's half is only §4.2: write good pages. The other half is Microsoft's, licensed or not
(**verify**: does the tenant have Microsoft 365 Copilot seats, and do Copilot Notebooks accept a OneNote page as a
reference?).

This is the most direct form of the operator's "on the fly RAG with frontier model capabilities". The retrieval
runs on the tenant, over content the fleet wrote and people annotated, and nothing on the laptop indexes anything.

## 6. Constraints we would design to

| Constraint | Design answer |
|---|---|
| Delegated only; no app-only access | Direct uses the operator's own token. Relayed runs as the flow maker. Nothing runs as a service |
| 400 requests/hour per user; no `Retry-After` | Batch appends (≤ 6/hour/project). Reads are capped at N pages per request. Back off on 429 with a fixed 60 s / 300 s / give up, and record a `throttled` refusal |
| Connector: 100 calls/60 s; triggers poll every 1200 s | Fine for appends and context, slow for intake (§4.3). Budget it on the meter ([plan-meter.md](plan-meter.md)) as the plan's rule 6 asks |
| Pages are HTML that people edit | Append only, inside our own `data-id` div. Never `replace` |
| Section page limit (507) | Rotate the section monthly. Treat a 507 as a refusal (`section_full`), never as a retry |
| "Use Remote Interfaces" on the site | The first M-0 row. Without it the relayed path is closed on that site |
| Custom note tags unsupported | Use `to-do`, `important` and `question` only, mapped from `needs-you`, `blocked` and `ask` |
| No documented full-text search over work notebooks | Address by section. "Find" stays the SharePoint search's job (M-A) |

## 7. Questions for the M-0 sitting (rows to add to the plan's §2)

| Question | How to find out |
|---|---|
| Does the Azure CLI's Graph token carry any `Notes.*` scope? | decode the `scp` claim of `az account get-access-token --resource-type ms-graph`; then `az rest --url https://graph.microsoft.com/v1.0/me/onenote/notebooks` |
| Is the OneNote (Business) connector in the same DLP business group as SharePoint and OneDrive? | add it to the mobile lane's test flow and save |
| Does the maker account have "Use Remote Interfaces" on the team site that holds the project notebook? | one *Get sections in notebook* run against that notebook |
| Trigger latency, measured: from the moment a page is created in Agent inbox to the moment the flow starts | five pages, timestamps both ends, record min/median/max (a new `M7` row in [windows-verification.md](windows-verification.md)) |
| Does *Update page content* append land within a second, and does it disturb a page someone else has open? | append while the page is open on the phone |
| Does ticking a to-do tag show up in the page HTML that *Get page content* returns (`data-tag="to-do:completed"`)? | tick one and read the page back. If it does, a ticked ask could become an answer: a later slice, not this one |
| Is OCR text present in the HTML of a page with a photo taken on the phone? | photograph a whiteboard into Agent inbox; read the page |
| Microsoft 365 Copilot seats, and Copilot Notebooks referencing OneNote pages | the operator's own Copilot app |

## 8. Decisions for the operator

| | Question | Default until answered |
|---|---|---|
| OneNote-D1 | If the Azure CLI's token lacks `Notes.Read`, register our own Entra app (delegated `Notes.Read`, maybe `Notes.ReadWrite`)? | **no.** Use the relayed path. An app registration is a new credential |
| OneNote-D2 | Which notebook sections may agents read, and which may the fleet write to? | none. Named per project in `AGENTS.md` (`onenote_context_sections`, `onenote_log_section`) |
| OneNote-D3 | Turn on the Agent inbox intake? | off until a project names the section (follows M365-D3) |
| OneNote-D4 | One log page per project per day, or one per day for all projects? | per project. Rule 3, and a Copilot Notebook can reference several pages |

## 9. How it maps onto the M365 plan

No new slice. OneNote rides the ones already planned:

| Slice | OneNote's part |
|---|---|
| M-0 | the eight rows in §7 |
| M-A | `ad-m365 note books\|pages\|get` if the token allows; `context-fetch --kind page` |
| M-B | `FleetContextFetch`'s `source: onenote` branch |
| M-C | `m365-publish`'s `onenote-append` target; the log page (§4.2); `confluence.py`'s parser gains a OneNote emitter |
| M-D | `FleetIntake`'s OneNote trigger; the reply-on-the-page path (§4.3) |
| M-E | the log page *is* the loop-out record, for anyone who reads OneNote rather than Teams |

Skills: none new. `context-fetch`, `m365-publish` and `intake-triage` gain a OneNote case each, and `m365-router`
gains "OneNote", "my notes", "the notebook" and "the stand-up notes" as phrases. A dedicated `onenote-*` leaf would
duplicate those leaves; if its friction count ever argues otherwise, the marketplace ledger will show it.

## 10. Sources (Microsoft Learn, read 2026-10-09)

- Graph: `onenote` resource type; Notes permissions; OneNote API overview; app-only authentication deprecation.
- Graph: get page content and structure; create pages; update page content; use note tags; add images and files.
- Graph: OneNote best practices; error codes; throttling.
- Graph: Search API overview (entity types).
- Connector reference: OneNote (Business).
- Microsoft 365 / OneNote release notes, July–September 2026 (Copilot Notebooks; multimodal capture; Work IQ).
