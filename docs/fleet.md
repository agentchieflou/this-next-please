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

## The rules

**One agent per repository**, enforced by a lock rather than by hope — two `copilot` processes in
one checkout would both edit the same working tree and both believe they owned `.agent/state.json`.

**The repository belongs to the agent.** The fleet writes only under `~/.agentdata/fleet/`. Nothing
in `.agent/` is written by anything but the agent's own `ad-state`, and there is a test that walks
four repositories after a run to prove it.

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

And when a tile is wrong rather than the fleet:

| Tile says | Means | Do |
| --- | --- | --- |
| `error` | the last turn exited non-zero, or the process vanished | `ad-fleet logs <repo>`, then `ad-fleet restart <repo>` |
| `blocked` | a friction log, or `phase=blocked` | the *why* is the sentence to act on |
| `needs_human` | a refused tool, or it asked and stopped | `ad-fleet send <repo> "…"` |
| `waiting_approval` | a write is one click away | `ad-fleet approve <id>`, or the tile |
| `running` forever | it really is running | `ad-fleet logs <repo>`; `stop` if it is stuck |

## What it deliberately is not

It does not schedule work, pull the next ticket when an agent finishes, run agents on another
machine, or merge anything. It never merges a PR and never closes a ticket — those stay a person's,
whatever the agent concluded.
