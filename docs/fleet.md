# The fleet

Several headless agents, one per repository, watched from one window.

The problem it solves is narrow and real: four tickets in four checkouts used to mean four PyCharm
windows and four chats, and the operator's actual job — *which of these needs me right now?* — was
the one thing none of them answered. The fleet answers that, and does nothing else.

```bash
ad-fleet repo add C:/repos/rdsd-pbi-reporting
ad-fleet repo add C:/repos/rdsd-uat
ad-fleet serve --open

ad-fleet start rdsd-pbi-reporting RDSD-101
ad-fleet status
```

## The daily loop

0. **Start the day** (#508): `ad-fleet fresh --all --dry-run` lists every agent — ticked (a ticket in
   progress, idle, not waiting on you: a clean session on its ticket and configured model), tickable
   (no ticket or a finished one: a keyless session, with `--keyless`), and the rest with the reason
   (mid-turn, needs you with its question, a console, your own chat, already on today's session).
   Then `ad-fleet fresh --all --confirm <plan_id>` starts exactly the ticked rows, one premium turn
   each. The day boundary is when a session began, never when its current run did. On the desk
   (#511): `ad-fleet serve --open --fresh` opens on the same preview, the morning line or `Shift+N`
   opens it, and *start N fresh* confirms the ticked rows. `--fresh` itself launches nothing.
1. **`ad-fleet open`** (or `serve --open`) — the dashboard, one tile per registered repository.
2. **Press `b`** for your Jira board. Drag a ticket onto a tile, or click *start on `<repo>`*.
3. **Work on something else.** A tile turns amber when an agent wants to write to Jira, red when it
   needs you, green when it is done. A toast arrives for the first two.
4. **Answer.** Approve the write from the tile; type a reply to the agent that asked a question;
   read the unblock sentence from the one that stopped.
5. **End the day:** `ad-fleet wrapup --all --day --dry-run`, then `--confirm <plan_id>` — every
   agent's Jira, Bitbucket and Confluence writes in one table, written on one confirm (#505).
   On the desk (#512): the *day* menu's *end of day…* opens the same table in the day strip, and
   *write N* confirms the ticked cells. `ad-fleet history` says what was dispatched, how it ended,
   and what it cost.

Everything in that loop is also a command, because a fleet you can only drive through a page is a
fleet you cannot script: `approvals`, `approve`, `deny`, `send`, `restart`, `renew`, `stop`, `board`,
`history`, `notify`, `gc`, `doctor`.

## After an update: fresh sessions

Skills are read when a session begins, so after `ad-update` changes one, every agent already running
still follows the old text. Every start records what it began on (#239). The desk compares that with
what is installed on every tick, and shows *old skills* on each stale tile, with a strip under the
toolbar for as long as any are stale (#240).

```bash
ad-fleet renew --dry-run     # which sessions are stale, why, and what renewing would do
ad-fleet renew               # stale only, when idle: fresh sessions on the same tickets
```

A renew starts a fresh session on the repository's active ticket, and `.agent/state.json` says where
the work stopped. It never renews an agent that is waiting on you. A running agent is renewed when
its turn ends, by the desk, so keep one open. Not `restart`: that resumes the same session, and the
same session keeps the skills it already read.

**One pane, fresh (#488).** Renew takes every stale agent and never an adopted one. To leave *one*
checkout's session -- stale, your own terminal chat the fleet adopted, or one that began outside the
fleet and went quiet -- for a clean one:

```bash
ad-fleet fresh luna --dry-run   # what it leaves, what it starts (ticket, model), and whether it can now
ad-fleet fresh luna             # one call: a clean --new session on the active ticket and the configured model
ad-fleet fresh luna --closed    # the second press, once your own chat there is closed
```

It leaves the current session listed, marked `left`, under *earlier (n)* on the pane and in
`ad-fleet sessions luna`; nothing is deleted, and Copilot's own files are never written. The fresh
session is never a `--resume`: it runs on `fleet.models.<repo>` / `fleet.model` (what the pane's model
button names), on the active ticket -- none once the phase is terminal -- with a sentence saying which
session it left. It refuses `mid_turn` while a fleet turn runs (press again when it ends; nothing is
queued), `console_window` on a console the fleet opened, `needs_you` while a question is open, and
`foreign_session` beside a Copilot it can name by pid -- the fleet never ends your chat. When your
own chat may still be open but has no pid (an adopted lock that is still live, or a session file
written within `fleet.console.idle_s`), the first call refuses `chat_open`; close the chat, then
`--closed` stops following it and starts the clean session. `--closed` is not `--force`: on `start`,
`--force` replaces a live agent. On the desk it is the pane's own **start fresh** (its head, its
session menu, or `Alt`+`N`), beside the header's renew (#489).

A Copilot CLI update can also drop a model an agent is configured with: see **After a CLI update**
under "Which model an agent runs" below.

## Wrapping up an agent

One agent's Jira ticket, Bitbucket branch and PR, and Confluence page, previewed and written in one
press, with no model turn (#503):

```bash
ad-fleet wrapup luna --dry-run              # end of day: every write previewed, nothing written
ad-fleet wrapup luna --project --dry-run    # end of project
ad-fleet wrapup luna --confirm <plan_id>    # write the ticked ok steps of exactly that preview
```

Each step runs its own adapter with `--dry-run`, in the checkout: `ad-git push`, `ad-pncli bitbucket
pr`, `ad-confluence publish`, `ad-jira comment`, `ad-jira transition`. The confirm writes the ticked
ones in that order, and only when a fresh preview has the same `plan_id`; a step whose preview
changed answers `changed` and is not written, and a failed step skips the steps that wait on it.

| Step | End of day (`--day`, the default) | End of project (`--project`) |
|---|---|---|
| push | ticked when the branch has unpushed commits | same |
| pr | a draft when commits exist; otherwise update the open PR | create or update, ready for review |
| page | update a page this tool published; never create | create or update `.agent/out/<KEY>-confluence.md` |
| comment | a progress comment, when anything changed since the last wrap-up | a final summary comment |
| transition | *to do → in progress* when commits exist | *review* ticked with a PR; *done* shown unticked |
| merge | never offered | never offered |

The comment is a template filled from the checkout (branch, phase, commits since the last wrap-up,
PR, page, open questions, artifacts), written to `<fleet dir>/agents/<repo>/wrapup/comment.md`;
`--comment-file` replaces it, and the preview runs again on the replacement. `--to` picks another
transition. A page or PR description edited since this tool wrote it is never replaced by default:
`--overwrite-page <version>` or `--overwrite-pr <hash>` previews again with the replacement.

Untracked work gets push and PR rows and no Jira rows. A checkout on a protected branch or a
detached HEAD has no push or PR that can run. A busy agent (mid-turn, a console, your own chat)
gets every row skipped, and nothing is queued. Until #506 and #507 pin the PR and page verbs, those
rows read `not_pinned`. The confirm is the approval: each written step leaves one record
`by: operator`, `via: wrapup` (see [fleet-approvals.md](fleet-approvals.md)), and one line in
`<fleet dir>/agents/<repo>/wrapup.jsonl`. The fleet never writes the checkout.

**On the desk** (#510): `w` on the agent's pane, or *wrap up* at the end of its project panel's rail,
opens the same preview as a sheet on the panel, set to end of project. Each write is a row with a
tick; *write n* writes exactly the ticked ones, and each row then says *written*, *failed*, *changed*
or *skipped*. *Edit* on the comment row shows the template's text; an edit is previewed again before
it can be sent. The desk never waits on Jira or Bitbucket: the rows arrive as the job reads them.

**The sweep** (#505) is the same preview for every registered agent, or for the ones you name:

```bash
ad-fleet wrapup --all --dry-run                 # end of day across the fleet: one table, totals, a plan_id
ad-fleet wrapup --all --project --dry-run       # end of project across the fleet
ad-fleet wrapup luna sol --dry-run              # just those
ad-fleet wrapup --all --confirm <plan_id>       # write every ticked ok step, repo by repo
```

End of day is the sweep's default (the operator's pairing: *clean sweep* with *end of day*), and
`--project` must be named. The preview reads three agents at a time, each agent's steps one after
another, and prints one row per agent (`planned`, `busy` with its hint, or *nothing to write*), one row
per step, and the totals by kind — pushes, PRs, pages, comments, transitions — with `not_pinned`
counted apart. The confirm needs the fleet `plan_id`, which hashes every agent's own; a fleet that
changed since the preview is refused `plan_changed`. Each agent is then written through the same
path as one agent's wrap-up, so its fresh dry-runs, ids, order and records all hold, and one
agent's failure never stops another's. A busy agent is skipped with a hint and never queued (DAY-D3).

## More than one project: the desk

Everything above is per repository. The desk (#122) is the same fleet pointed at the folder every
project already lives under — `C:/Users/you/PycharmProjects` on the laptop — so that the first
question of the morning, *which repo, which ticket, which report*, is answered without opening a
tab.

```bash
ad-fleet quickstart C:/Users/you/PycharmProjects
```

That is scan → index → poll → inbox → serve, in that order, with the clock running; each step is
also its own verb ([setup.md](setup.md) §Several projects at once). The scan **proposes** and you
confirm each one — it hands the human a list, never an agent a folder — and registration goes
through the same `repo add` a hand-typed path would.

### The catalogue

`ad-fleet index` reads what every registered repository already publishes into one local SQLite
file. `ad-fleet where "velocity"` then says which project mentions it, and `ad-fleet show <project>`
prints that project's facts, state, open friction, PBIP models and reports, and its links.
`ad-fleet friction <repo>` prints the panel's friction: open, earlier, and why (#499); `--dismiss NAME`
and `--earlier` hide rows on the panel through the same call the page makes, and keep the files.

**What it indexes** — an allow-list of repo-relative *names*, per registered repo:

| Kind | File |
| --- | --- |
| `agents` | `AGENTS.md` — the facts block and the headings |
| `state` | `.agent/state.json` |
| `friction` | `.agent/friction/*.md` — title, type, date, first paragraph |
| `pbip_model` / `pbip_report` / `pbip_lineage` | `.agent/pbip/<name>/MODEL.md`, `REPORT.md`, `LINEAGE.md` |
| `pbip_meta` | `.agent/pbip/<name>/meta.json` |
| `git` | `.git/HEAD` and `.git/refs/heads/<branch>` — the branch name and when it last moved |

**What it never indexes.** Source trees, notebooks, SQL, exports, anything under `.agent/out/`, and
above all `.env`, `secrets*`, `localSettings.json` or `~/.pncli/config.json`. Those are not skipped
by a rule that could be relaxed: `catalogue.allows()` refuses every name it does not list, every
read goes through it, and a path outside the allow-list is never constructed in the first place.
Adding a kind is a change to that function plus a test, never a config knob. A doc that *looks* like
it carries a credential (the patterns `config.save()` already refuses — token, password, secret,
`Bearer `) is refused outright and reported by file and pattern, never by line.

**Where the file lives.** `~/.agentdata/fleet/catalogue.sqlite`, beside everything else the fleet
remembers, and outside every repository. It is a **cache**: every byte in it was read from a file
still on the disk, so deleting it costs one `ad-fleet index --rebuild` and nothing else. Search is
SQLite FTS5 where the interpreter has it and a plain `LIKE` scan where it does not; `ad-doctor` says
which, every time, because "search found nothing" and "search is running on the fallback" look
identical from a result set.

**This is deliberately not a RAG, and that is the point.** The obvious version of this feature is to
give an agent the parent folder and embed everything in it; three constraints say no, and each one
is already a rule here. AGENTS.md rule 3 — an agent never reads a second project's `.agent/` — is
broken by a folder-wide agent on its first `ls`; the thing that may read across projects is the
supervisor, a plain Python process the human runs, never a model. The corporate policy disables MCP,
so no model could query a vector store anyway: the only query path a model has on this laptop is an
`ad-*` command printing TOON — and `ad-fleet` is on the agent's deny-list, so that path is shut. And
what actually answers "which project owns Velocity, what ticket is it on, what did it last get
stuck on" is the
small structured credential-free material above — indexing the source trees answers nothing more and
is where the volume and the credential risk live. `ad-fleet where` is the same leverage with none of
the embedding, the chunking, or the "what did it index" question.

An agent sees the catalogue only as a summary of **its own** repository, pasted into the first
prompt `ad-fleet start` composes. No command run inside a repository can query the catalogue: there
is no per-repo verb for it, and `ad-fleet` is the only one that reads it.

### The tile is the project's home

With those facts indexed, each tile carries the project's own state beside the agent's: the ticket,
the board, the report, the dataset, the workspace, the repository, the open PR, the Confluence page
and the local folder as links, and their live state polled read-only on a per-source timer (Jira
60 s, PR 120 s, Power BI 300 s, git 30 s). A cell shows value and age (`Done · 4m`) and goes **grey,
not wrong**, when a poll fails. The git cell also counts the checkout's local branches and which of
them never reached the default (`7 branches · 3 never reached main`), goes amber at
`fleet.branches.warn` (default 6), and opens the inspector's branches pane on a click; `ad-fleet
branches <repo>` prints the same rows (#184). A missing fact means the link is absent and `ad-fleet doctor` names
the `AGENTS.md` key to add — never a broken URL that opens an error page.

Polling is honest about its cost: `ad-fleet status --polls` prints today's request count per source,
the Jira poll is **one JQL for every tile**, and it stands down rather than starving a running
`ad-jira changelog` of its request budget. `fleet.poll.jira: false` turns one source off;
`fleet.poll.enabled: false` turns the lot off.

### Downloads is an inbox

`ad-fleet inbox` lists what the browser saved into Downloads and which project each file belongs to,
matched **on the file name alone** — a ticket key, or a project name. Nothing there is opened:
Downloads holds bank statements and installers next to the Jira exports, and a watcher that read a
file to decide where it belongs would be reading all of them. Attach copies one file into
`<repo>/.agent/in/<KEY>/` and leaves the original where it is; that copy is the *only* write the
fleet makes inside a repository, it happens only on a click, and it is logged as `inbox.attached`.

## The rules

**Which model an agent runs** is `fleet.model` (and `fleet.effort`) for the whole fleet, overridden
per repository by `fleet.models.<repo> = {"model": …, "effort": …}` — set from `/settings`, or in
`~/.agentdata/config.json`. Left unset, no `--model` flag is passed at all and the Copilot CLI
selects one itself, which is the only no-model behaviour anyone has measured. A change applies to
the agent's **next** turn: the command line is fixed when the process starts.
`ad-fleet status --show-launch` prints a `models` table with one row per registered repository and
the source each value resolved from — `fleet.models.<repo>`, `fleet.model`, or `cli-auto`.

Nothing validates a model *name*: `--model` is on the measured list of flags this build has, but
which names it accepts has never been measured, so the CLI is the validator and the settings page
suggests only models the event stream has really reported. What *is* refused, at the keystroke, is a
value carrying whitespace or a leading dash — `--model "x --allow-all-tools"` is one argument to a
person and two to a command line, and the allow-list check never sees it.

**Where the list comes from** (#360). The model ids a picker offers are read from the installed
Copilot CLI, with no login and no premium request: `copilot help config` lists the ids its `model`
setting takes (26 on 1.0.88, 28 on 1.0.81 — builds differ), falling back to `copilot completion bash`
when that lists none, and `copilot --help` lists the reasoning efforts. The answer is cached in
`<fleet dir>/models.json` with the CLI version it came from, and asked again when it is older than
`fleet.model_list.max_age_h` (default 24) or the CLI's `--version` changed. With no CLI and no
cache, the list shipped with this package (`agentdata/fleet/models_shipped.json`, 1.0.88) is shown,
marked stale. Since CLI 1.0.64 the setting also takes the family aliases `opus`, `sonnet`, `haiku`,
`gpt` and `gemini`, which `help config` omits; they count as offered. A configured or seen id the
build does not list is marked `offered: false` — a warning, never a refusal. Entries are grouped
Copilot, OpenAI, Anthropic, Google, Other. `ad-fleet models [--refresh]` prints the catalogue as
TOON (`models` with `id,group,label,via,offered`, and `efforts`); a page request never starts the
CLI.

**When it refreshes** (#361). When `ad-fleet serve` or `ad-fleet quickstart` starts a server, the
CLI is asked once, on a thread of its own: the cache is kept while it is fresh and from the
installed `--version`, and asked again otherwise. On demand, `POST /api/models {refresh: true}`
asks again whatever the cache says. Either way the page is answered at once and never waits on the
CLI; one refresh runs at a time, and an ask during one joins it. A refresh ends with its server:
once the server is stopping it starts no process and writes nothing. A list that changed reaches
every open page as one `models` stream frame ([fleet-dashboard.md](fleet-dashboard.md) §The
stream), and `/settings` offers the catalogue's efforts.

**On the settings page** (#367). `/settings` sets both by pressing, not typing. **every agent** is
the whole catalogue as pills, grouped by provider, with the efforts under it; **CLI default** passes
no flag at all. Each repository's row has a short picker: **inherit**, which names the default it
follows, clears the row's model; the fleet default and the model the last turn ran on are one press
away; **more…** opens the whole catalogue inside the row, where **other…** takes a name the list
lacks (saved, and the saved tag says when this CLI does not offer it), and the efforts, whose
**inherit** (or **default**) clears the row's effort. **inherit both** removes the whole entry. The
resolved-from column names where each half comes from when they differ. **refresh the list** asks the CLI again; the line beside it
names the copilot the list came from and how long ago it was checked, or says the shipped list is
shown because copilot could not be asked. The model card's **all models · settings** link lands on
its repository's row, opened, with the keyboard on the pressed pill.

**From the terminal** (#363). `ad-fleet model <repo>` prints the repository's model, effort, the
source it resolved from and the model its last turn actually ran on, then the catalogue as a
`models` table (`id,group,label,offered,pressed`) with `*` on the configured id, or on the CLI
default when it inherits. It reads the cache and never starts copilot; `ad-fleet models --refresh`
asks the CLI. `ad-fleet model <repo> <name> [--effort <level>]` sets it, `--inherit` removes the
entry, and `ad-fleet model --fleet [<name>] [--effort <level>]` shows or sets the fleet default --
through the settings page's writer, with its refusals (`bad_model`, exit 2, nothing written) and an
unregistered repository refused. `--effort` alone sets the effort alone. A name the catalogue does
not list is saved with a warning, never refused.

**Model and effort inherit separately** (#493, decision 15). A repository's model is its own, else
`fleet.model`, else none (the CLI chooses); its effort, independently, its own, else `fleet.effort`,
else none. So an entry holding only an effort goes with the fleet's model, and one holding only a
model goes with the fleet's effort; `--show-launch` and `ad-fleet model` print where each half came
from (`source`, `effort_source`). An effort survives a model switch: it is never reset because the
model changed, and an effort can be set while the model is the CLI's choice. If the CLI refuses the
pair at start -- the turn ends before its first reply -- the pane says which effort ran on which
model, and `m` opens the card to pick another.

**After a CLI update** (#365). Run `ad-doctor --only fleet` and read its `models` row: it names
the list's source, its CLI version and age, and warns once per configured model the new build no
longer offers (since CLI 0.0.421 a turn on such a model fails to start). The fix it names is
`ad-fleet model <repo> --inherit` or another pick on `/settings`; the doctor changes nothing itself.

**A console the fleet opens** (`ad-fleet console <repo> [KEY]`, #189) is the operator's own
`cmd.exe` running Copilot in that checkout with a session id the fleet chose; the tile reads the
same session from Copilot's own file for it (#188), and the lock is taken with the window's pid.

**Typing into it** (`ad-fleet say <repo> "<text>"`, #190) is how a console's session is answered:
`send` would be a second agent in that working tree, so `say` spawns a helper that attaches to the
window and types the line, and the console echoes it. `ad-fleet show-console <repo>` brings the
window to the front. Neither ever interrupts the session or answers a prompt for you — a `y/n` in a
console is the operator's, and the tile says where to find it.

**One agent per registered working tree**, enforced by a lock rather than by hope — two `copilot`
processes in one checkout would both edit the same working tree and both believe they owned
`.agent/state.json`. A working tree, not a repository: two `git worktree` checkouts of one
repository are two agents, two locks, two branches and two event streams. What says they are the
same piece of work is one field, `project`, which defaults to the checkout's own name — so every
registry written before it groups each repository as its own project by definition.

`ad-fleet repo add <path>` of a worktree follows its `.git` file's one `gitdir:` line back to the
main checkout, and if *that* checkout is registered, registers this one as `<project>-<folder>` with
the same `project`. It is the only place that pointer is ever followed, it is followed at a person's
explicit add, and the answer is written down so nothing at runtime follows it again — the scan's
rule stands: an unattended walk reads no second repository's internals. `--project <name>` says it
by hand; `ad-fleet repo list` prints the column.

Two checkouts of one project share a colour (in the terminal hook and on the tiles), are hidden and
pinned as one on the desk, sit beside each other as tabs on each other's tile, and a Downloads file
naming a ticket goes to the checkout that is *on* that ticket rather than to the unsorted tray. The
fleet never creates a checkout: `git worktree add` is the operator's, in git or the IDE.

`ad-fleet repo rm` leaves the agent's own directory behind — it holds the stream `ad-fleet history`
reads and the sessions that could still be resumed — and now says where it is. `ad-fleet gc` takes
it once everything in it is past the cutoff.

**The repository belongs to the agent.** The fleet writes only under `~/.agentdata/fleet/`. Nothing
in `.agent/` is written by anything but the agent's own `ad-state`, and there is a test that walks
four repositories after a run to prove it. The one documented exception is the inbox's *attach*
above: a click, a copy into `.agent/in/<KEY>/`, an event — and the `inputs` line it produces is
still asked of `ad-state` rather than written behind its back.

**Reads run unattended; writes wait for a click.** Every write to Jira, Confluence or Bitbucket
stops at [the approval gate](fleet-approvals.md) and shows you the dry-run payload first.

**The agent may run what it was allowed to run, and nothing else** — an enumerated whitelist, not a
deny-list. The spike measured Copilot's own permission classifier refusing three spellings of a
file write and allowing the fourth, which is why the boundary lives in our commands. Git stops at
`git commit -m`; the one push is `shell(ad-git push)`, which refuses a force, a refspec, a protected
branch and an unconfigured remote itself and waits on the gate. `shell(git push)` stays denied.
Two module forms are on the list, `python -m agentdata state` and `python -m agentdata doctor` (#500), so an
agent whose launcher will not start can still record that it is stuck. The write adapters (jira,
pncli, confluence, git) have none: the `python` on PATH may be another install, one without the
approval gate. `fleet`, `update` and `setup` stay denied.

**Nothing is announced twice, and nothing routine is announced at all.** Four agents working
normally produce zero notifications; see [fleet-notifications.md](fleet-notifications.md).

## Where everything is written down

| Document | What it settles |
| --- | --- |
| [fleet-spike.md](fleet-spike.md) | what the Copilot CLI actually does, measured |
| [fleet-events.md](fleet-events.md) | the event contract every other slice reads |
| [fleet-approvals.md](fleet-approvals.md) | what is gated, and the two layers behind it |
| [fleet-dashboard.md](fleet-dashboard.md) | the page, its endpoints, the token model |
| [fleet-map.md](fleet-map.md) | the fleet map: `GET /api/map`, the graph of projects, checkouts and agents, and the page that draws it |
| [fleet-notifications.md](fleet-notifications.md) | when you are interrupted, and when you are not |
| [fleet-intake.md](fleet-intake.md) | the Jira board and the start guard rails |
| [fleet-layouts.md](fleet-layouts.md) | the one arrangement and how four became one, `desk.json` schema 2 and its migration, a window's widths, hiding |
| [fleet-ide.md](fleet-ide.md) | the dashboard inside PyCharm and VS Code |
| [desk-engines.md](desk-engines.md) | what each shell's engine does, and WebGL measured in each one: `ad-fleet probe --open pycharm`, then `ad-fleet engines` (#247) |
| [fleet-lifecycle.md](fleet-lifecycle.md) | crashes, restarts, budgets, logs, the doctor rows |

## When something is wrong

Start with `ad-fleet doctor`. Every row names its own fix.

| Row | Means | Do |
| --- | --- | --- |
| `fleet/copilot` **fail** | the CLI will not start | `npm install -g @github/copilot` |
| `fleet/login` **fail** | the token expired | `copilot login`, then `ad-fleet restart <repo>` |
| `fleet/skills` **fail** | no skills installed | the agent has no router and will improvise — install them |
| `fleet/skills` **warn** | skills older than the CLI | `ad-update --skills`, then restart running agents |
| `fleet/dashboard` **warn** | the port is taken | `ad-fleet serve --port 0`, or set `fleet.port` |
| `fleet/repos` **warn** | a checkout moved or was cleaned | `ad-setup --project .` there, or `ad-fleet repo rm` |
| `fleet/toast` **warn** | no Windows toasts | optional: `pip install "agentdata[fleet-win]"` |
| `fleet/parent folder` **warn** | a checkout, or the drive under it, is not where the registry says | reconnect the drive, or `ad-fleet repo add --scan` again; nothing is removed for you |
| `fleet/catalogue` **warn** | never built, stale by more than a day, or unreadable | `ad-fleet index` — or delete the file and `ad-fleet index --rebuild`; it is a cache |
| `fleet/facts` **warn** | a project cannot build every tile link | the row names the `AGENTS.md` key per project; `ad-fleet show <project>` lists them |
| `fleet/inbox` **warn** | no Downloads folder, or it cannot be listed | `ad-fleet inbox --folder <path>`, or `fleet.inbox.folders` in the config |
| `fleet/token budget` **warn** | N tiles are polling one Jira token near its limit | slow or stop a source: `fleet.poll.jira: {"interval": 300}` or `false` |

And when a tile is wrong rather than the fleet:

| Tile says | Means | Do |
| --- | --- | --- |
| `error` | the last turn exited non-zero, or the process vanished | `ad-fleet logs <repo>`, then `ad-fleet restart <repo>` |
| `blocked` | a friction log, or `phase=blocked` | the *why* is the sentence to act on |
| `needs_human` | a refused tool, or it asked and stopped | answer it: `ad-fleet answer <repo> <id> "…"`, or `ad-fleet send <repo> "…"` |
| `waiting_approval` | a write is one click away | `ad-fleet approve <id>`, or the tile |
| `running` forever | it really is running | `ad-fleet logs <repo>`; `stop` if it is stuck |

## What it deliberately is not

It does not schedule work, pull the next ticket when an agent finishes, run agents on another
machine, or merge anything. It never merges a PR and never closes a ticket — those stay a person's,
whatever the agent concluded.
