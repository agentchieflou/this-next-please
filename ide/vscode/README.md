# agentdata fleet — VS Code shell

Hosts the `ad-fleet serve` dashboard in a view, keeps a status-bar count of agents needing you, and
turns the fleet's own notifications into VS Code ones.

**It is a shell.** There is no rule logic here. Which agents need a person, what to say about them
and when to stay quiet are decided by `agentdata/fleet/notify.py`; a second implementation in
TypeScript would eventually disagree with the tiles it sits next to, and nobody could tell which was
right. The only inbound things this extension acts on are `notify` frames and the contract number on
`/api/ping`.

## Install

Built as a `.vsix` by CI and attached to the release. Then:

```
code --install-extension agentdata-fleet.vsix
```

…or **Extensions → … → Install from VSIX**.

## Commands

| Command | Does |
| --- | --- |
| `Fleet: Open the dashboard` | attach to a running dashboard, or start one, and show it |
| `Fleet: Start an agent on a ticket` | the open folder if the fleet knows it, else pick |
| `Fleet: Reload the dashboard` | re-read `serve.json` and reconnect |

## Settings

| Key | Default | Does |
| --- | --- | --- |
| `fleet.port` | `8765` | port to start `ad-fleet serve` on when nothing is listening |
| `fleet.command` | *(empty)* | how to run the CLI; empty tries `ad-fleet` then `python -m agentdata fleet` |
| `fleet.notifications` | `true` | raise a VS Code notification when an agent needs you |

## Its relationship to the Agents Window

VS Code's own Agents Window (`code --agents`) can list external Copilot CLI sessions, which may
include the fleet's. Use that for reading one agent's transcript in depth, and this for watching
several and acting on them — only the dashboard has the approval gate and the Jira board.

See [`docs/fleet-ide.md`](../../docs/fleet-ide.md) for the contract any shell must follow.
