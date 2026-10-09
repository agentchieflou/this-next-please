# The skills marketplace

`/skills` (the *Skills* block on `/settings`, or `/open?page=skills`) answers one question the fleet
could not answer before: of every skill the operator has, which ones actually get used, by whom,
where, how recently, and do they work. The page is a reading of two things the fleet already had on
disk and never folded: what is installed, and the tool calls in every transcript.

## What the page shows

One row per skill, sorted by uses then name, filtered by the box in the toolbar (a substring over the
name, the description, the directory and the busiest repositories), and sorted again by pressing a
header (*name*, *uses*, *last used*; a second press flips it):

| Column | What it is |
| --- | --- |
| name | the skill's folder name, and its pills: **unused** (never called), **missing** (called, but no longer on the disk), **shadowed** (a second copy of the name in a later directory, which the CLI does not read) |
| what it does | the `description` in its front matter |
| uses | how many times an agent or a Copilot session called it |
| last used | relative; the ISO stamp (UTC) is the cell's title |
| repositories | the three busiest, then *+n*; every one with its count is the title |
| ok / failed | how its calls ended, joined to the call by its id; a call still running counts in neither |
| version | the first twelve hex digits of the SKILL.md's sha256, the same digest the fleet's install fingerprint takes (`fingerprint.py`); when it was installed is the title |
| installed in | the skills directory, `~`-shortened |

A row expands (click, Enter or Space) to its facts line (first and last use; how many calls were
fleet agents' and how many your own Copilot sessions'; when and where it was installed), a list of
every repository with its uses and when last, and the last twenty ticket keys the calls were made
under.

The page refreshes every 30 seconds while its tab is visible. It writes nothing: no button on it
changes a skill or a count.

## Where the numbers come from

### What is installed

`skills.installed()` reads every skills directory that exists, in the order the CLI reads them: the
project's `skills_dir` fact first, then `update.SKILL_DIRS` (`~/.copilot/skills`, `~/.agents/skills`,
`~/.config/copilot/skills`, `~/.claude/skills`). Every folder with a `SKILL.md` is a skill. The same
name in two directories is one skill shadowing another: the first directory wins and the later copy
is listed with `shadowed_by`, so a stale copy left behind by an older install is visible rather than
silently ignored. Read on every request, never cached: the page's poll is also the moment an
`ad-update` shows.

### How each is used: two sources, one ledger

A skill is run through the `skill` tool, and the tool call is in the transcript whichever way the
session ran:

* **Fleet agents.** Each agent's normalized stream, `<fleet dir>/agents/<name>/events.norm.jsonl`
  ([fleet-events.md](fleet-events.md)), carries a `tool_call` with `tool: "skill"` and
  `arguments.skill` naming the skill, then a `tool_result` with the same `id` saying whether it
  succeeded. The envelope's `repo` and `ticket` say where and under what.
* **Your own Copilot sessions.** Copilot writes every session, interactive or `-p`, to
  `~/.copilot/session-state/<id>/events.jsonl` (`COPILOT_SESSION_STATE` overrides the path, as it
  does for `sessions.py`, which reads the same files). The raw `tool.execution_start` and
  `tool.execution_complete` events are read the way `events.from_copilot` reads them, and the
  session's `workspace.yaml` names the working directory it ran in: its basename is the repository.

A session the fleet piped or adopted is in both places. It is counted once, as the fleet's: a session
file whose id a fleet agent is known by (the agent's `sessions.json`, its lock, or a `session_id` or
`started` event the fold has seen on its stream) is skipped on the Copilot side. Every other session
counts under the source `copilot`, and the row's expansion says how many of its calls were each.

**The streams rotate.** `lifecycle.rotate_all` rolls `events.norm.jsonl` aside at `fleet.log_mb`, and
`events.read` opens only the live file, so a count that lived in the stream would forget the morning
the way spend did before #210. The counts are therefore folded into a ledger, `<fleet dir>/skills.json`,
on `spend.json`'s pattern: written atomically (`.tmp` then `os.replace`), a cursor per agent, folded
on every `events.refresh` and in `rotate_all` *before* the roll. The Copilot side keeps a byte offset
and mtime per session file, so a poll reads only what Copilot appended, and a call whose result lands
in a later read is still joined: the open calls are kept in the ledger.

```json
{"schema": 1,
 "agents": {"<agent>": {"cursor": {"seq": 412}, "open": {"<call id>": "<skill>"}}},
 "copilot": {"<session id>": {"pos": 20480, "mtime": 1760000000.0, "open": {}, "repo": "luna"}},
 "fleet_sessions": {"<session id>": "<agent>"},
 "skills": {"<name>": {"uses": 9, "ok": 8, "failed": 1, "first": "2026-10-01T09:12:00",
                       "last": "2026-10-08T16:40:12",
                       "repos": {"luna": {"uses": 7, "last": "2026-10-08T16:40:12"}},
                       "tickets": ["RDSD-41", "RDSD-44"],
                       "sources": {"fleet": 8, "copilot": 1}}},
 "updated": "2026-10-08T16:40:30"}
```

`skills.rebuild()` throws the ledger away and folds every file on disk, each agent's rolled files
oldest first (`.N` descending, `.1` being the newest roll) then the live one, then the Copilot
sessions. Its answer equals the incremental ledger, which is the check on the design and what makes
the ledger a fold rather than a source: nothing in it is unrecoverable. A ledger that cannot be
read or written is one that gets rebuilt, never a page that will not draw.

### What *used* means

A use is one `skill` tool call, counted when it is made. *ok* and *failed* are counted when the
result lands; a call with no result yet (the agent is still in it, or the stream ended before it
answered) is a use with neither. The settings page's line counts a skill as *used in the last 30
days* when its last use is within that window.

## The marketplace source

`fleet.skills.source` (on `/settings`, under the Copilot block; `ad-setup` writes the same
`~/.agentdata/config.json`) names where the skills come from. Three shapes, told apart by
`skills.source_kind`:

| Shape | Looks like | Sync does | Refresh does |
| --- | --- | --- | --- |
| `github` | `owner/repo`, optionally `owner/repo@ref` | `gh skill install owner/repo --all --scope user --agent github-copilot`, the line `ad-update` runs (`update.skills_command`), with its *already installed → remove ours, retry* handling | `gh api repos/owner/repo/contents/skills` for the names (descriptions from a clone when one is there); without `gh`, a shallow clone over https |
| `git` | anything `git clone` takes: `https://…`, `ssh://…`, `git@host:…`, `file://…`, `….git`; `@ref` after the path picks a branch or tag | `git clone --depth 1 [--branch ref]` into `<fleet dir>/marketplace/<sha12 of the url>/`, or `git pull --ff-only` when the clone is there; then the copy below | the same clone or pull, read, nothing copied |
| `path` | a folder that exists (looked for first, so a relative `a/b` that exists is a folder) | the copy below, from `<folder>/skills/` when there is one, else the folder itself | the folder, read |

Anything else is refused on the settings page (`bad_source`) and by both verbs (`skills_bad_source`),
so a typo is never stored as a source nothing can sync from. The default is this repository.

**The copy.** Every `<name>/SKILL.md` the source offers goes to the first `SKILL_DIRS` entry that
exists (`~/.copilot/skills` first; it is created when none exists). A folder the sync installs
carries a `.marketplace` file holding the source string. A folder already there is replaced only
when it carries this source's marker; one without a marker (installed by hand, by `ad-update`, by
`gh`), or with another source's, is left as it is and named in the result's `skipped`. A folder with
this source's marker that the source no longer offers is removed: a sync mirrors its source. For a
GitHub source `gh` does the writing, and the folders it added or changed are given the marker
afterwards so the next sync recognises them.

**The result.** Before and after, the SKILL.md hashes in the target directory say what was `added`,
`updated`, `removed` or `unchanged` (the same digest the install fingerprint takes;
`fingerprint.changed` compares two recorded sets, not a before and an after, so the diff is taken
here). `commit` is the clone's head, or the GitHub branch's through `gh api`, when known. The result
is kept in the ledger as `sync` and shown on the page as *last synced <when> from <source> @
<commit>*; the catalogue a refresh read is kept as `catalog`, and the snapshot marks each installed
skill `available` and lists what is offered and not installed.

**One at a time.** A sync runs on a thread; `skills-sync` answers that it started, a second press
while it runs is refused `skills_sync_running`, and the page polls `/api/skills` every two seconds
until `sync.running` is false. A sync is capped at 120 s and a refresh at 30 s; every subprocess goes
through `agentdata/proc.py` (the Windows shims, `GIT_TERMINAL_PROMPT=0`), and every failure is a
result with `error` and `hint`, never a traceback.

**Offline.** A git or GitHub source that cannot be reached leaves what is installed as it was, keeps
the last clone and the last catalogue, and says so on the page. A `path` source needs no network at
all.

## Limits

* **Claude Code's transcripts are not read.** Only Copilot's two shapes (the fleet's normalized
  stream and Copilot's own session files) are. A skill run from Claude Code, or any other CLI,
  counts nothing until a reader for its transcript exists; guessing at a shape would count wrong
  rather than count nothing.
* A shadowed copy shows no uses of its own: the call names the skill, not the copy, and the copy
  the CLI ran is the winner's.
* The repository of a Copilot session is its working directory's basename. Two checkouts of one
  project under different folder names are two repositories here, as they are on the desk.
* The ledger is one file per fleet directory, written by whichever process folds. Two processes
  folding at once (the desk and a CLI) can lose a fold; the next `rebuild()` makes it whole.

## Routes

| Method | Path | What |
| --- | --- | --- |
| GET | `/skills` | the page |
| GET | `/api/skills` | `{ok, source, sync, catalog, not_installed, dirs, skills[], totals, ledger_updated}`; the shape is in [fleet-dashboard.md](fleet-dashboard.md) §Endpoints |
| POST | `/api/skills-sync` | start a sync of the stored source; `{started: true}`, or `skills_sync_running` / `skills_bad_source` |
| POST | `/api/skills-refresh` | read the catalogue and answer the snapshot; `skills_bad_source` / `skills_sync_failed` |

The list itself changes nothing: the only write is *sync*. Tested by `tests/test_fleet_skills.py` and, in a browser,
`tests/test_fleet_skills_page.py`.
