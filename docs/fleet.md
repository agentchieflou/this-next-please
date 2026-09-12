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

1. **`ad-fleet open`** (or `serve --open`) — the dashboard, one tile per registered repository.
2. **Press `b`** for your Jira board. Drag a ticket onto a tile, or click *start on `<repo>`*.
3. **Work on something else.** A tile turns amber when an agent wants to write to Jira, red when it
   needs you, green when it is done. A toast arrives for the first two.
4. **Answer.** Approve the write from the tile; type a reply to the agent that asked a question;
   read the unblock sentence from the one that stopped.
5. **`ad-fleet history`** at the end of the day: what was dispatched, how it ended, what it cost.

Everything in that loop is also a command, because a fleet you can only drive through a page is a
fleet you cannot script: `approvals`, `approve`, `deny`, `send`, `restart`, `stop`, `board`,
`history`, `notify`, `gc`, `doctor`.

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

**A console the fleet opens** (`ad-fleet console <repo> [KEY]`, #189) is the operator's own
`cmd.exe` running Copilot in that checkout with a session id the fleet chose; the tile reads the
same session from Copilot's own file for it (#188), and the lock is taken with the window's pid.

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
file write and allowing the fourth, which is why the boundary lives in our commands.

**Nothing is announced twice, and nothing routine is announced at all.** Four agents working
normally produce zero notifications; see [fleet-notifications.md](fleet-notifications.md).

## Where everything is written down

| Document | What it settles |
| --- | --- |
| [fleet-spike.md](fleet-spike.md) | what the Copilot CLI actually does, measured |
| [fleet-events.md](fleet-events.md) | the event contract every other slice reads |
| [fleet-approvals.md](fleet-approvals.md) | what is gated, and the two layers behind it |
| [fleet-dashboard.md](fleet-dashboard.md) | the page, its endpoints, the token model |
| [fleet-notifications.md](fleet-notifications.md) | when you are interrupted, and when you are not |
| [fleet-intake.md](fleet-intake.md) | the Jira board and the start guard rails |
| [fleet-layouts.md](fleet-layouts.md) | the three layouts, focus mode, and the sitting that picks one |
| [fleet-ide.md](fleet-ide.md) | the dashboard inside PyCharm and VS Code |
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
