# Surviving a laptop

Four unattended agents on a machine that sleeps, locks, changes network and sits behind a proxy
fail in ways one attended chat never did — and every one of those failures is **quiet**. A killed
process raises nothing. A slept laptop looks exactly like four agents thinking hard. An expired
token looks like a turn that went badly. A log that has eaten the disk looks like nothing at all
until something unrelated breaks.

So this is mostly about *noticing*, and everything noticed is written as a normalized event
([fleet-events.md](fleet-events.md)) so the tiles, the notifications and the history all see it
without a second channel.

## A process that just stopped

The lock file outlives the process it names. A row that says `running` about a pid that is gone is
the one lie the whole fleet turns on, so anything that looks at agents reaps first — `ad-fleet
status`, the dashboard, `restart`.

Three outcomes, because they need three different responses:

| What was found | Event | Why it is not the others |
| --- | --- | --- |
| the stream already ends in `exited`/`error` | *nothing* | it reported its own ending; saying so twice is noise |
| stderr mentions an expired login | `error` + `question_opened` | it will fail identically on every retry |
| stderr has something else in it | `error` with the last 20 lines | there is a cause, and it is in those lines |
| no exit code and nothing on stderr | `exited` | the machine slept or the console closed — *not* a bug to hunt |

The stderr tail is redacted through the same rule the event stream uses. A crash dump is exactly
where a token ends up: a proxy failure prints the request, and the request carries the header.

## An expired Copilot login

Recognised from the CLI's own words, matched loosely because the wording moves between releases and
the *class* of failure is what matters. It produces **one** `question_opened` naming `copilot login`
and the restart command — and no retry, ever. Relaunching an agent whose token expired burns
premium requests in a loop and produces the same failure every time.

`ad-doctor` catches it before four agents are launched into it, as its own row: "installed" and
"logged in" fail differently and are fixed differently, so one row that conflated them would send
half the people to the wrong command.

## The laptop slept

Detected as a wall-clock jump larger than any poll interval could explain — two minutes. A turn can
legitimately take that long; an idle poll never can. Every running agent is then probed rather than
trusted, because sleep and "thinking hard" are indistinguishable from the outside and only one of
them means the processes are gone.

## Restarting

```bash
ad-fleet restart luna
```

Resumes the agent's **own session** with `--resume <session id>`, and tells it:

> You were interrupted. Read your own last messages, say in one line where you got to, and
> continue. Do not start the ticket again.

Not the original ticket prompt. The agent has already read the ticket, made a plan and possibly
edited files; beginning again repeats all of it at full price, and lays a second set of edits over
the first.

Bounded by `fleet.max_restarts` (default 1) **per session**. An agent that dies twice for the same
reason will die a third time, and an unbounded restart loop on a laptop is how a budget disappears
overnight. `--force` always buys one more, so a human decision is never blocked.

## The budget

`fleet.budget_per_agent` is off by default. Set it, and an agent that has spent that many premium
requests will not be sent another turn:

```
ok: false
error: luna has spent 12 of its 10 premium-request budget
hint: raise `fleet.budget_per_agent`, or pass --force for this one turn. `ad-fleet history` shows where it went
```

Checked **before** a turn is sent and never during one: stopping an agent halfway through a thought
leaves the repository in whatever state it had reached, and the money is spent either way.

The number is the CLI's own session total, taken as a high-water mark and never a sum — summing
checkpoints would multiply the bill, and a budget built on a multiplied bill stops an agent that
never overspent. `ad-fleet status` shows the total for the fleet and the budget each agent is
measured against.

## Logs

`events.jsonl`, `events.norm.jsonl` and `stderr.log` roll at `fleet.log_mb` (default 20) keeping
`fleet.log_keep` (default 5), `.1` newest. Only **between turns**: a rename under a live writer
fails on Windows and silently orphans the inode on POSIX.

When the raw log rolls, the cursor that counts how many of its lines have been read is reset in the
same breath — otherwise the next refresh skips the opening lines of the new file, which is where a
turn boundary and quite possibly a denial live.

```bash
ad-fleet gc --days 14
```

Removes **rotated** logs and answered approvals older than that, and nothing else. A live
`events.norm.jsonl` is never a candidate at any age: it is what `ad-fleet history` reads, and a
report that silently loses last month is worse than a directory that is slightly too big. A running
agent's directory is not touched at all.

## After an update

Skills load at session start. An agent that was already running when `ad-update` installed new ones
is still following last week's instructions, and nothing about its behaviour would say so — so
`ad-fleet status` says it, and names the fix: `ad-update --skills`, then `ad-fleet restart <repo>`.

## The doctor rows

```bash
ad-fleet doctor          # the same as `ad-doctor --only fleet`
```

| Row | Proves |
| --- | --- |
| `fleet/copilot` | the launcher **resolves and starts** — `copilot --version` — and how it compares to the build the spike measured |
| `fleet/login` | the CLI reports an authenticated user |
| `fleet/skills` | the skills directory has this repo's skills, and they are not older than the CLI |
| `fleet/dashboard` | `fleet.port` is free, or is already ours |
| `fleet/repos` | every registered repository still has `AGENTS.md` and `.agent/state.json` |
| `fleet/toast` | the `fleet-win` extra (warn only) |
| `fleet/rules` | the notification settings in force |

Every row proves something *starts* rather than that a file exists — `which` finding a file has
already been misleading in this repository once, when `pncli.cmd` was on PATH and the connector
still could not launch it.

**The whole step is skipped when no fleet is configured**, and prints one `skip` row saying so.
`ad-doctor --quiet` runs on every session start, and probing a CLI nobody has installed costs a
subprocess launch for an answer nobody wants. A registry with repositories in it, or
`fleet.enabled`, turns it on.

## Configuration

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.enabled` | *(off)* | turn the doctor rows on before any repository is registered |
| `fleet.port` | `8765` | where `ad-fleet serve` listens |
| `fleet.max_restarts` | `1` | restarts per session before a human has to say so |
| `fleet.budget_per_agent` | *(off)* | premium requests an agent may spend before it stops |
| `fleet.log_mb` | `20` | size at which a log rolls |
| `fleet.log_keep` | `5` | how many rolled copies survive |

## Not here

Scheduling agents overnight needs the auto-queue that was declined in #98. Running agents on
another machine is out of scope, and so is making the skills themselves cheaper — that is epic #15.
