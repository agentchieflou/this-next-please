# The fleet's worklog

One page per checkout per day, folded from the agent's event stream, laid out like the fleet map, and mirrored
under the fleet directory. The design is [plan-onenote-worklog.md](plan-onenote-worklog.md) (the operator,
2026-10-09: *fleet agents write worklogs to OneNote in structured locations that resemble the fleet's
Monorepository nature*); this page is the contract for what is built: **W-1**, the local worklog, and **W-2**, the
wrap-up's preview. Nothing here writes to OneNote yet. The writers are W-3 (Graph, direct) and W-4 (the Power
Automate connector, relayed), and until one lands the wrap-up row says so rather than pretending.

## The shape

The fleet map ([fleet-map.md](fleet-map.md)) draws a project, the main checkout its worktrees hang from, and an
agent on each. The worklog is that tree with time added at the leaves, and the one string below is both the
OneNote address and the local path:

```
<project> / <repo> / <yyyy-mm> / <yyyy-mm-dd>

luna                               project         section group        ~/.agentdata/fleet/worklog/luna/
└─ luna-velocity                   checkout        section group        …/luna/luna-velocity/
   └─ 2026-10                      month           section              …/luna-velocity/2026-10/
      └─ 2026-10-10 · luna-velocity  day           page                 …/2026-10/2026-10-10.md (+ .html)
```

`worklog.layout(project, repo, day)` is the only place the shape lives. It answers `path`, the section-group
chain (`groups`), the month `section`, the page `title` (`<day> · <repo>`), and the project journal's section and
title (`Journal <yyyy-mm>`, `<day> · <project>`) for W-5. With `nested=False` it answers the connector's flat
layout instead: one section `<project> · <yyyy-mm>` at the notebook's top level, no groups, the same `path`.

**Names.** Graph refuses `? * / \ : < > | & # ' % ~` in a section or section-group name and caps it at 50
characters. `worklog.onenote_name` rewrites any string the same way every time: each forbidden character becomes
`-`; a name over 50 is cut to 43, a dash and six hex digits of the full name's digest, so the next day finds the
same group and two long names never collide. The project name is `Repo.project` (the repo's own name unless
`repo add --project` said otherwise), and the checkout name is the registered name.

**Pages stay flat.** A OneNote page's `level` and `order` are read-only in Graph, so there are no subpages; the
tree is section groups. A section's page count is capped (507 past it), which is why a month is a section.

## What a page says, and what it never says

A page is a view of `events.norm.jsonl` ([fleet-events.md](fleet-events.md)) for one repo between two `seq`
values: **facts only, no model turn, no new authority**. `worklog.fold(events, repo=, project=, day=, since=)` is
pure; `worklog.build(name, day=, since=)` reads the registered agent's stream (after `events.refresh`) and folds
it.

| Line | From | Shown as |
|---|---|---|
| Header | the model named in `assistant_text`, `spend.fold` (turns, premium requests that day), the seq range, the branch when the caller knows it | *luna-velocity · on feature/RDSD-101 · claude-haiku-4.5 · 6 turns · 2.1 premium requests · seq 214–260* |
| One heading per ticket touched | `ticket` on the events | `RDSD-101` |
| phases | `phase_changed` | *phases: triaged → 09:31 optimizing → 14:02 verifying* |
| what it made | `artifact` (path and `what`), `pr_open` | *09:04 made .agent/out/x.md — unused measures*; *PR <url>* |
| what it asked | `question_opened` / `question_answered` / `question_cleared`, `assume` | an open question is a `to-do` note tag, an answered or cleared one `to-do:completed`, an assumed one plain |
| approvals | `needs_approval` / `approval_resolved` | *09:05 git-push: push 3 — approved by operator* |
| friction | `friction` | a `blocker` or `friction` severity carries the `important` tag, a `nit` none |
| denials | `denied` | *1 tool call denied* |
| where it ended | `agentstate.derive` over the day's events | *ended needs human* with the `question` tag; `blocked` and `error` with `important` |
| the wrap-up comment | `agents/<name>/wrapup/comment.md`, when the wrap-up wrote one | quoted as written; it is the one piece of prose, and the operator already read and approved it (W-D3) |

Never on the page: `assistant_text`, `tool_call`, `tool_result`, `raw`, or any event of another day. The day is
the stream's own date (`ts[:10]`, UTC like every `ts`); W-D2, whether the operator's local day should replace it,
is open. `since` excludes events at or before a `seq`, which is what makes a second wrap-up on the same day an
append rather than a repeat.

**Two emitters, one list of lines.** `render_md` writes the mirror's Markdown (note tags as `- [ ]`, `- [x]`,
`- **!**`, `- **?**`); `render_html` writes OneNote's input HTML: a `<title>`, one `<div data-id="wl-root">`, one
`<div data-id="wl-<ticket>">` per ticket so a later `append` can target it, OneNote's own note tags as `data-tag`
(custom tags are not supported, so only `to-do`, `to-do:completed`, `important`, `question` are used), everything
escaped by `confluence.esc`, because one escaper writes every page we send anywhere.

## The mirror

`ad-fleet worklog <repo> [--date YYYY-MM-DD] [--since N] [--write] [--markdown | --html]` prints the day as TOON
(`meta`: `repo, project, day, path, title, section, events, seq_from, seq_to, turns, premium, denied, state,
notebook`; `tickets[]`: per ticket the counts of phases, artifacts, PRs, open and answered asks, approvals, friction
and denials). `--write` also writes `<fleet dir>/worklog/<project>/<repo>/<yyyy-mm>/<yyyy-mm-dd>.md` and `.html`
and prints `local`. `--markdown` and `--html` print the page itself instead. The mirror is the whole day rewritten
from the stream, so it is idempotent and needs no cursor; it is the worklog even with no OneNote at all, and the
catalogue may index it later as its own allow-listed kind.

## The wrap-up row

The wrap-up ([fleet-dashboard.md](fleet-dashboard.md) §wrap up, #503) gains a step, `onenote`, between `page` and
`comment`, in one agent's sheet and in the sweep (#505, counted as *worklogs*). Its preview is real: it writes the
mirror and the HTML the writer would send (`agents/<name>/wrapup/onenote.html`), both under the fleet directory,
never in the checkout, and the row carries the address, the title, the seq range and the action:

| Row | When | Code | What it says |
|---|---|---|---|
| *worklog: create `<path>`* | no page of this day was written yet (the cursor has no seq for it) | | |
| *worklog: append `<path>`* | the cursor says a page was written and events came after its seq | | |
| *worklog: nothing new for `<path>`* | no event after the cursor | | |
| any of those, unticked | `fleet.onenote.notebook` is blank | `not_configured` | the worklog is local only; set the notebook's OneNote web URL on `/settings` |
| any of those, unticked | the notebook is set | `not_built` | the page is rendered; the writer is W-3 or W-4 |
| *worklog: failed* | the stream or the mirror could not be read or written | `worklog_failed` | the error |

The row is never `ok` and never ticked until a writer exists, so `run` never reaches it, and all three codes are
*quiet* (`wrapup.QUIET`): a repo whose other rows have nothing to write still reads *nothing to write*. Its id
hashes the stable payload (`path, title, seq_from, seq_to, action`), so a new event between the preview and the
confirm turns it `changed` like every other step. The cursor, `agents/<name>/worklog.cursor.json`
(`{"days": {"<day>": {"seq": N}}}`), is moved only by a writer, never by a preview.

## Settings

| Key | What | Default |
|---|---|---|
| `fleet.onenote.notebook` | the notebook the worklog pages go to, as its OneNote web URL (Graph's *get notebook from web URL* resolves it once; the fleet never creates a notebook) | blank: the worklog is local only |

## Refusals

| Where | When | Answer | Test |
|---|---|---|---|
| `ad-fleet worklog` | the repo is not registered | `refused: wrong_repo`, exit 2 | `test_fleet_worklog.py::test_the_cli_prints_toon_and_writes_only_when_asked` |
| `ad-fleet worklog`, `worklog.layout` | `--date` is not `YYYY-MM-DD` | `refused: bad_day`, exit 2 | the same, and `test_the_layout_is_the_fleet_map_with_time_at_the_leaves_and_one_path_string` |
| the wrap-up row | see the table above | `not_configured`, `not_built`, `worklog_failed`, never ticked | `test_the_wrapup_offers_the_worklog_row_unticked_with_the_reason_in_its_code` |

## What is deliberately not here

- **No OneNote write.** W-3 and W-4 of the plan; each needs the M-0 sitting of
  [plan-m365-bridge.md](plan-m365-bridge.md) first (a `Notes.*` scope in the Azure CLI's token, or the connector
  in the lane's DLP group).
- **No live appends during the day** (W-6, W-D5): the wrap-up is the moment.
- **No journal page yet** (W-5): `layout` already names it.
- **No local day** (W-D2): the page's day is the stream's UTC date until the operator says otherwise.
