# Plan: the fleet's worklog in OneNote, laid out like the fleet itself

_Status: PLANNED (proposed 2026-10-09). The operator picked use 2 of [spike-onenote.md](spike-onenote.md): "the idea of
having fleet agents write worklogs to OneNote in structured locations that resemble the fleet's Monorepository
nature". Nothing here is built yet. The Microsoft facts below are from Microsoft Learn and are cited in the spike;
anything about **our** tenant is marked **verify** until the M-0 sitting of
[plan-m365-bridge.md](plan-m365-bridge.md) records it._

## 1. The idea in one picture

The fleet map ([fleet-map.md](fleet-map.md)) already draws the fleet as a tree:

- a **project** (`p:<project>`), which is the repository its checkouts share;
- its **checkouts** (`c:<repo>`): the main checkout first, then each worktree hanging from it;
- on each checkout, one **agent** standing on a branch that carries a ticket.

The worklog notebook is that same tree, with time added at the leaves:

```
Fleet                                   notebook             the fleet (one per operator)
└─ luna                                 section group        p:luna — the project, the monorepo root
   ├─ Journal 2026-10                   section              the project's month
   │  └─ 2026-10-09 · luna              page                 the day across every checkout, one heading each
   ├─ luna                              section group        c:luna — the main checkout
   │  └─ 2026-10                        section              that checkout's month
   │     └─ 2026-10-09 · luna           page                 the agent's worklog for the day
   └─ luna-velocity                     section group        c:luna-velocity — a worktree (a lane)
      └─ 2026-10                        section
         └─ 2026-10-09 · luna-velocity  page
```

**The OneNote path and the local path are the same string**: `luna/luna-velocity/2026-10/2026-10-09`. The fleet
writes the worklog to disk first, at `~/.agentdata/fleet/worklog/<project>/<repo>/<yyyy-mm>/<yyyy-mm-dd>.md`, and
the notebook is a mirror of that tree. So the monorepo shape is a rule that one function enforces, not a habit
someone has to keep up.

Three things fix this shape:

- **Section groups nest; pages do not.** Graph creates section groups inside notebooks and inside other section
  groups (`Notes.Create`). A page's `level` and `order` are read-only, so an API cannot make subpages. That puts
  the tree in section groups and keeps pages flat.
- **A section holds a limited number of pages** (over the limit, Graph answers 507). The main checkout lives for
  years, so its days are split into a section per month. A month of working days is about 22 pages.
- **Worktrees come and go; their history stays.** When a worktree is removed, its section group stays as the record of that lane. The API cannot move a section group (sections only have *copy*),
  so nothing is archived automatically. The operator can drag old lanes into an `Archive` group by hand.

### Names

| Object | Name | Rule |
| --- | --- | --- |
| notebook | `fleet.onenote.notebook` (a setting: its web URL, read once with Graph's *get notebook from web URL*) | the operator creates it; the fleet never creates a notebook |
| project group | `Registry.project` (defaults to the repo name, [fleet-map.md](fleet-map.md)) | ≤ 50 characters, none of `? * / \ : < > \| & # ' % ~`, unique within its level |
| checkout group | the registered repo name | same rule. Registry names are already unique, so the level stays unique |
| month section | `yyyy-mm` | 7 characters |
| journal section | `Journal yyyy-mm` | 15 characters |
| page | `<yyyy-mm-dd> · <repo>`, set from the HTML `<title>` | no length rule for titles. The connector also takes the title only from `<title>` |

A name that breaks the rule is rewritten by one function (`worklog.onenote_name`): each forbidden character
becomes `-`, and a name over 50 characters is cut to 43 plus `-` and a 6-hex digest of the full name. The same
name always maps to the same result, so the next day finds the same group.

## 2. What a page says

The source is the agent's event stream, `~/.agentdata/fleet/<repo>/events.norm.jsonl`
([fleet-events.md](fleet-events.md)). It is already redacted, already in sequence order, and it is already the
one input every other reader uses. A worklog is one more fold over it: **no model turn and no new authority**. The
day page is a view of the stream for one repo between two `seq` values, which is why it can be rebuilt, compared
and tested.

| Block | Built from | Shown as |
| --- | --- | --- |
| Header | the fleet map row: project, checkout, branch, agent kind and model, `turns`, `sessions_n` | one line, e.g. *luna-velocity · on feature/RDSD-101-velocity · background agent · 6 turns* |
| One heading per ticket touched that day | `ticket` on the events | `RDSD-101`, linked to Jira when `jira.base_url` is set |
| Phases | `phase_changed` | *09:31 triaged → optimizing → 14:02 verifying* |
| What it made | `artifact`, `pr_open` | file names under `.agent/out/` (names only, never contents) and the PR link |
| What it asked | `question_opened` / `question_answered` | a question still open carries `data-tag="to-do"`, an answered one `to-do:completed` |
| Approvals | `needs_approval` / `approval_resolved` | *git-push approved by operator via desk 11:20* |
| Where it ended | the last state (`STATE_ROLES`) | `blocked` or `error` with `data-tag="important"`; `needs_human` with `question` |
| Cost and friction | `cost`, `denied`, `friction` | one line of counts |
| The day's summary | the wrapup's Jira comment text (`agent_dir/wrapup/comment.md`), when the wrapup wrote one | quoted as written; the operator already edited and approved it |

The page never carries `assistant_text`, tool calls or tool results. They are the model's working, they are
large, and a tool result is text from a command nobody here wrote. The worklog is the record of **what happened**,
and the stream keeps the rest for anyone who needs it (`ad-fleet events`). This boundary is decision W-D3.

Each page has one root `<div data-id="wl-root">` and one `<div data-id="wl-<ticket>">` per ticket, so a later
write can `append` to the right place.

## 3. When it is written: the wrapup first

The wrapup ([wrapup.py](../agentdata/fleet/wrapup.py), #503) already does the end-of-day pass: *preview every write,
then write exactly the ticked ones, in order*. The worklog becomes one more step there, `onenote`, beside
`git push`, `git pr`, `confluence publish` and `jira comment`. It follows the same rules:

- **Previewed.** `plan` renders the page into `agent_dir/wrapup/onenote.html` and dry-runs the adapter. The row
  shows the path (`luna/luna-velocity/2026-10/2026-10-09`), the page title and what will change: *creates the
  page*, or *appends seq 214–260*.
- **Ticked.** In the wrapup, the operator's confirm is the approval (WRAP-D4). It is recorded `by: operator`,
  `via: wrapup`, so no new approval kind is needed.
- **Re-planned at run time.** The step id hashes repo, date and the seq range. If an event arrives between the
  plan and the run, the step reads `changed`, as every other step does.
- **Append-only, from a cursor.** `agent_dir/worklog.cursor.json` records the last `seq` written per page. A
  second wrapup on the same day appends an *update hh:mm* block holding only what came after that seq. The fleet
  never `replace`s anything, so text a person typed on the page is never touched, wherever they typed it.
- **The project journal.** The sweep ([#505](https://github.com/agentchieflou/this-next-please/issues/505)) runs the
  wrapup per agent and then appends one heading per checkout to `Journal yyyy-mm / <date> · <project>`. Each
  heading carries a three-line summary and the checkout page's `oneNoteWebUrl`. That journal page is the one a
  Copilot Notebook should reference (spike §5).
- **Project mode** (`MODES = ("day", "project")`) ends a lane: it writes a closing block, *lane closed: PR merged
  / abandoned, n days, tickets*, on the last day page of that worktree.

Live appends during the day (spike §4.2: every `done`, `blocked`, `needs-you`, batched every 10 minutes) are a
later slice (W-6). They are a gated write outside the wrapup, so they need the M-C publish path and its own
approval kind. The wrapup costs nothing new and covers the operator's actual habit of reading at the end of the day.

## 4. Two writers, one layout function

| | Direct (Graph) | Relayed (Power Automate) |
| --- | --- | --- |
| Needs | a Graph token with `Notes.Create` (or `Notes.ReadWrite`) from the Azure CLI sign-in. **verify** at M-0. Otherwise our own Entra app, which is OneNote-D1 | the Standard OneNote (Business) connector in the lane's DLP group, and "Use Remote Interfaces" on the notebook's site (**verify**) |
| Builds the tree | yes. `ensure_path` lists children by name and creates what is missing: a section group in a notebook or in a section group, then a section in a section group | **no.** The connector has no action that creates a section group, and *Create section in a notebook* creates at the notebook's top level |
| Layout | the nested tree in §1 | **flattened**: a section `<project> · <yyyy-mm>` at the top of the notebook, with pages `<date> · <repo>`. The journal becomes the page `<date> · <project>` in that section |
| Writes | `POST sections/{id}/pages` (HTML), then `PATCH pages/{id}/content` with `append` to `#wl-root` | outbox record `publish` of kind `onenote-worklog` `{path, title, html, seq_from, seq_to, digest}`; `FleetPublish` (M-C) runs *Create page in a section* or *Update page content* and writes back a `publish-result` with the page's web URL |
| Calls, per checkout per day | first of the month: up to 4 lists and 3 creates; any other day: 1 page create, 1 journal append | 1 flow run, 2–3 connector calls |

Both writers call one function, `worklog.layout(project, repo, date, nested: bool)`, to get the same path and
names. The local mirror in §1 always uses the nested form. If only the relayed path is open, the notebook's tree
is shallower but the names still read as the tree. If the direct path opens later, a one-off
`ad-m365 note migrate` could copy each flat section into its nested place with Graph's `copyToSectionGroup`; that
is a sitting's job, not a slice's.

Budget: ten checkouts cost under 60 Graph calls a day, against Microsoft's 400 per hour per user. A 429 comes with
no `Retry-After`, so the writer waits 60 s, then 300 s, then gives up with a `throttled` row in the wrapup. A 507
is `section_full` and is never retried.

## 5. Slices

| Slice | What | Needs the tenant? | Proven by |
| --- | --- | --- | --- |
| **W-1** The local worklog — **built** (0.21.0, [fleet-worklog.md](fleet-worklog.md)) | `agentdata/fleet/worklog.py`: `fold(repo, date, seq_from)` → a day model; `render_md` and `render_onenote_html` (one model, two emitters, using `confluence.py`'s escaping); `layout` and `onenote_name`; `ad-fleet worklog <repo> [--date] [--write]` prints TOON and writes the mirror tree | **no** | fixture streams → golden Markdown/HTML; name rules (forbidden characters, 50-character cut, digest stability); a day across midnight; rotation of `events.jsonl` does not split a page |
| **W-2** The wrapup step, dry-run — **built** (0.21.0) | `onenote` in the step list: preview path, title and seq range; `not_configured` until `fleet.onenote.notebook` is set; the cursor | no | the wrapup tests' existing harness: plan, `changed` on a new event, append-only on a second run |
| **W-3** The direct writer | `ad-m365 note ensure-path\|create\|append`, through `agentdata/proc.py` and the Azure CLI token | M-0: `Notes.Create` in the token | a recorded Graph fixture; one sitting that writes a real day page |
| **W-4** The relayed writer | the `onenote-worklog` record and the `FleetPublish` OneNote branch; flat layout | M-0: connector rows; M-C | `test_fleet_bridge.py`-style record tests; one sitting |
| **W-5** The journal and the Copilot Notebook | the sweep's journal append; a Copilot Notebook that references the journal pages | W-3 or W-4; Copilot seats (**verify**) | the operator asks the notebook *what did the agents do on luna this week* and records the answer |
| **W-6** Live appends | the 10-minute batch during the day, as an M-C publish with its own approval kind | M-C | approval-integrity tests (#537 digest, `via`, `by`) |

W-1 and W-2 can be built now. They are useful on their own: the local tree is the end-of-day worklog even with no
OneNote, and the catalogue can index it for `ad-fleet where` as a new allow-listed kind, `worklog`.

## 6. Decisions for the operator

| | Question | Default until answered |
| --- | --- | --- |
| W-D1 | Where does the notebook live: the operator's OneDrive (only you see it) or a team site (the team reads the agents' days)? | your OneDrive. A team notebook is a sharing decision, made per project later |
| W-D2 | Whose "day"? | the laptop's local date. A page is the operator's working day, not a UTC one |
| W-D3 | Facts only, or also the agent's own prose (its last `assistant_text` of each turn)? | facts plus the wrapup comment you approved. No raw model text |
| W-D4 | If only the relayed path opens, accept the flat layout, or register an app to get the nested one (OneNote-D1)? | accept flat. The names still read as the tree |
| W-D5 | Live appends during the day (W-6), or wrapup only? | wrapup only |
