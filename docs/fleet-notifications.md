# Being told, without being pestered

Epic #91's acceptance is that the operator is *told, in one window, when an agent has a status
update*. The hard part is not delivery. It is restraint.

Four agents emitting a toast per tool call is worse than no toasts at all, because the operator
learns to dismiss them without reading — and then misses the one that mattered. So the design goal
here is not "notify about everything", it is **four agents working normally should produce nothing**.
There is a test that asserts exactly that, over ten rounds of ordinary work.

## Three rules

**Notify on transitions, never on events.** A toast per `tool_call` is noise; a toast every time
anyone looks at the current state is worse, because it repeats for as long as the agent stays
stuck. A state *change* happens once, when it happens. That is `agentstate.transitions`, which folds
with exactly the same rules the tile is coloured by — a second implementation would eventually
disagree with the first about whether an agent needs the human, which is the only question the fleet
exists to answer.

**Nothing fires twice.** Each notification carries a `<repo>:<state>` key with a cooldown, kept on
disk, so a restarted dashboard does not re-announce what was already dismissed. And a repository
seen for the first time records where its stream is and announces nothing: opening the dashboard on
four agents that have been running for an hour must not produce an hour of toasts.

**Quiet hours downgrade, never suppress.** Out of hours the toast is withheld and the badge is still
recorded, so the morning shows what happened rather than hiding it.

## What is worth interrupting for

| State | Severity | Reads as | Why it is worth a person |
| --- | --- | --- | --- |
| `waiting_approval` | action | *needs approval* | a write to Jira, Confluence or Bitbucket is one click away (#95) |
| `needs_human` | action | *needs you* | a tool was refused, or the agent asked a question and stopped |
| `blocked` | action | *blocked* | a skill wrote a friction log; the body is the unblock sentence |
| `error` | alert | *fell over* | the last turn exited non-zero |
| `done` | info | *finished* | the phase reached `pr_open`, `done`, `closed` or `merged` |
| `idle_stalled` | info | *stopped without finishing* | nothing for `idle_minutes` while a ticket is still open |

Everything else — `running`, `starting`, and `idle` before it has stalled — never notifies. A test
asserts those three are absent from the rules, and that every rule names a state the fold can
actually return: a rule keyed on a state that cannot happen is a rule that never fires, and nobody
finds out for months.

`idle_stalled` is the only rule that is not a transition. It exists because *nothing happened* is
precisely the case nothing else would report.

## The channels

### The dashboard

Always on. Per-tile unread badge, cleared when you focus that tile — looking at it is what "read"
means. A count in the browser tab title (`(2) fleet`), a bell in the header, and a drawer (`n`)
listing the last 50 with click-to-jump.

The **chime** is off by default and synthesised in the browser with WebAudio rather than shipped as
a `.wav`: it adds nothing to the payload, there is nothing to fetch, and a sound file is one more
thing that can fail to install. It plays once when you switch it on, so "on" is not taken on trust.
Only `action` and `alert` chime; `info` does not.

### Windows toasts

Optional, because WinRT is Windows-only and the fleet has to run without it:

```bash
pip install "agentdata[fleet-win]"
```

The toast reads `luna · RDSD-101 — needs approval`, and **clicking it opens the dashboard focused on
that tile** (`…/?t=…#tile=luna`). With four agents, "something needs you" without saying which is a
notification that costs time rather than saving it.

Without the extra, everything else still works and `ad-fleet status` says so:

```
toast: unavailable (pip install "agentdata[fleet-win]")
```

`ad-setup` carries the same row under `fleet`, naming `fleet.notify.toast` so `ad-setup --patch`
can act on it.

A toast that fails never takes the fleet with it — a notifier that can crash the event stream is
worse than one that stays quiet, and the dashboard carries the same information either way.

**Not yet verified on a managed laptop.** Corporate policy (Focus Assist, or a notification GPO)
can refuse toasts from an app that registers itself at runtime. If that turns out to be the case
here, the fallbacks in order of preference are: a shortcut with an explicit AppUserModelID installed
by `ad-setup`; `winotify` driving PowerShell's own toast API; a tray icon. The dashboard channel is
unaffected either way, which is why it is the one that is always on.

## The commands

```bash
ad-fleet notify tail
```

Prints what *would* fire right now, changing nothing — no toast, no drawer entry, and no cooldown
spent. This is how a rule gets tuned against a real captured stream instead of by starting four
agents and waiting for one to get stuck.

```bash
ad-fleet notify test
```

Fires one of each severity through every configured channel, so the drawer and Action Center can be
seen working before anything depends on them.

```bash
ad-fleet notify
```

The last 50, as the drawer shows them.

## Configuration

All under `fleet.notify.*`, and `ad-setup --patch fleet.notify` re-asks exactly these:

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.notify.dashboard` | `true` | record notifications for the badge and the drawer |
| `fleet.notify.toast` | `true` | Windows Action Center toasts, when the extra is installed |
| `fleet.notify.chime` | `false` | the default for the page's sound toggle |
| `fleet.notify.cooldown` | `300` | seconds before the same agent may raise the same state again |
| `fleet.notify.idle_minutes` | `20` | how long an agent may sit on an open ticket before it is reported |
| `fleet.notify.quiet_hours` | *(off)* | e.g. `18:00-08:00`; wraps midnight |

## Where it lives on disk

Under `~/.agentdata/fleet/` (or `$AGENTDATA_FLEET_DIR`):

* `notifications.jsonl` — the drawer. Capped at 200 and rewritten, not appended: it is a drawer, not
  an audit log. `events.norm.jsonl` is the record ([fleet-events.md](fleet-events.md)).
* `notify.state.json` — how far into each agent's stream the notifier has read, and when each key
  last fired. This is what makes restarts quiet.

## Not here

Email, Teams and Slack — a fleet that emails you is a fleet you stop reading. Native IDE balloons
belong to #100, where the shells live. Mobile is out.
