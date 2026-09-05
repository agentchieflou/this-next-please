# The dashboard, inside the tools you already have

A PyCharm plugin and a VS Code extension are two more things to build, sign, ship and update.
Before paying for that (#100), this is what the IDEs can do with **configuration only** — and,
just as importantly, what they cannot.

```bash
ad-fleet open --in edge
```

Starts a dashboard if none is running, then shows it. Every branch prints what it actually did,
including the ones that could only put the URL on the clipboard: an embedding story that quietly
does nothing is worse than one that says so.

| `--in` | What happens |
| --- | --- |
| `browser` *(default)* | the default browser |
| `edge` | Edge with `--app=<url> --new-window` — chromeless, for a spare monitor |
| `vscode` | URL to the clipboard, with the two-step instruction (see below) |
| `pycharm` | the same, or `--write-launcher DIR` for a file the IDE will open |

## The stable address

Every run of `ad-fleet serve` generates a fresh token, which is right for security and wrong for
embedding: a token cannot be written into a keybinding or an External Tool that has to keep
working tomorrow. So the server answers one more route:

```
http://127.0.0.1:8765/open   →  302  →  /?t=<this run's token>
```

Tokenless, loopback-only, and safe to write down, bookmark or bind to a key. It is not a hole: any
local process can already read `~/.agentdata/fleet/serve.json`, loopback is still enforced on every
request, and a cross-origin page that navigates a window there cannot read where it landed.

`GET /api/ping` is the other tokenless route. It answers `{"ok": true, "service": "ad-fleet"}` and
nothing else, so a launcher can tell "our dashboard is on 8765" from "something else is" before
deciding whether to start a second one.

## VS Code

**Measured, and it changes the plan: `code --command <id>` does not exist.** VS Code 1.129.1's CLI
offers `--goto`, `--diff`, `--merge`, `--add`, `--agents` and extension management, and nothing that
invokes a command by id. So *nothing outside the editor can open Simple Browser*. The plan for this
slice assumed otherwise; this is the correction.

What works, in order of how little typing it costs:

**A keybinding** — `Ctrl+K Ctrl+S` → the `{}` icon → add:

```json
{
  "key": "ctrl+alt+f",
  "command": "simpleBrowser.show",
  "args": "http://127.0.0.1:8765/open"
}
```

This is why `/open` exists. With a per-run token there is no line to write here at all.

**A task**, for the tasks menu rather than a key — `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "fleet: open",
      "type": "shell",
      "command": "ad-fleet open --in vscode",
      "presentation": { "reveal": "always", "panel": "shared" },
      "problemMatcher": []
    }
  ]
}
```

A task runs a *process*, so it cannot open Simple Browser either — it puts the URL on the clipboard
and prints the two steps. The keybinding above is the better answer; this is for a workspace where
sharing the task file is easier than asking everyone to edit their keybindings.

**By hand**: `Ctrl+Shift+P` → `Simple Browser: Show` → paste.

The dashboard is **workspace-independent**: one VS Code window on any folder can host all four
agents, because the page talks to `127.0.0.1` and not to the workspace.

### Simple Browser will accept the page

Two things would stop an iframe, and neither is present: the server sends no `X-Frame-Options`, and
its CSP has no `frame-ancestors`. A test asserts both, because adding either header later would
break this embedding silently and only for the people using it.

SSE works inside the webview — it is an ordinary `EventSource` over the same origin as the page.

### The Agents Window overlap — unverified

VS Code has an Agents Window (`code --agents`), and it can list external Copilot CLI sessions. If it
does, the fleet's agents appear **twice**: once as tiles here and once as sessions there.

Not verified on this machine — it needs a person with the window open and agents running. The
recommendation to test, when someone does: use the Agents Window for *reading one agent's
transcript in depth*, and the dashboard for *watching four and acting on them*, since only the
dashboard has the approval gate and the Jira board. If the duplication is noise, the setting to
look for is `chat.agentSessions.showExternal`.

## PyCharm

PyCharm cannot be told to open a URL from outside the IDE — there is no CLI switch for it. Three
routes were tried:

| Attempt | Result | Notes |
| --- | --- | --- |
| **(a) External Tool** running `ad-fleet open --in edge` | **works** for launching, but the page opens *outside* the IDE | shipped as `agentdata/templates/pycharm/agentdata.xml` |
| **(b) A local `fleet.html` opened with the built-in preview** | **unverified** | `ad-fleet open --in pycharm --write-launcher .agent` writes it; whether PyCharm's preview follows a `meta refresh` to `http://127.0.0.1` inside a tool window needs a person |
| **(c) A Run configuration opening the URL** | equivalent to (a) | no advantage over an External Tool |

**So v1's honest PyCharm answer is (a): the dashboard on another monitor, launched from PyCharm's
Tools menu.** It is not *inside* a tool window. If having it inside matters, that is #100 — and on
this evidence #100 is required rather than optional for PyCharm.

To install the External Tools, copy `agentdata/templates/pycharm/agentdata.xml` into PyCharm's
config `tools/` directory and restart:

```
%APPDATA%\JetBrains\<PyCharm version>\tools\agentdata.xml
```

They then appear under **Tools → External Tools → agentdata**: *fleet: open*, *fleet: launcher
here*, *fleet: status*.

### Versions

The plan named PyCharm 2026.1.4. This machine has 2021.2, 2023.2.1 and 2023.3 — External Tools and
the config path above are unchanged across all of them, but the built-in preview's behaviour is
not, so attempt (b) needs re-testing on whichever version the operator actually runs. JCEF
availability is in **Help → About**.

## The four-monitor layout

* **Monitors 1–2**: PyCharm on the repository being reviewed, and its terminal.
* **Monitor 3**: whatever the work needs — Power BI Desktop, a browser, Jira.
* **Monitor 4**: the dashboard, chromeless, from `ad-fleet open --in edge`. Toasts
  ([fleet-notifications.md](fleet-notifications.md)) then arrive in Action Center wherever the
  operator is looking.

Whether corporate policy allows Edge's `--app` window is **unverified** — if it is blocked, the
same URL in an ordinary Edge window differs only in the title bar.

## Shells

`ad-fleet open` behaves identically from PowerShell 5.1, pwsh 7, Git Bash and the PyCharm terminal:
it takes no shell-quoted arguments and touches no shell-specific path. Running it twice does not
open the dashboard twice — `/api/ping` is checked first, and an already-running server is reused.

## What a shell must do (#100)

Two thin shells now exist — `ide/jetbrains/` (a JCEF tool window) and `ide/vscode/` (a webview) —
and this is the contract they follow, so a third host (Visual Studio, a tray app, a phone) needs no
new server work.

1. **Find the dashboard.** Read `$AGENTDATA_FLEET_DIR/serve.json`, or `~/.agentdata/fleet/serve.json`.
   It holds `url`, `token` and `port`.
2. **Check it is alive**, because that file outlives the process it describes: `GET /api/ping` must
   answer `{"service": "ad-fleet"}`. No token needed.
3. **Start one if it is not.** `ad-fleet serve --port <n>`, falling back to
   `python -m agentdata fleet serve --port <n>` — the console scripts are frequently not on PATH,
   which is the most common way this package looks broken when it is merely unfound. Start it
   detached: closing the IDE must not take the dashboard down, because the other shells are
   attached to the same server.
4. **Host the URL** in whatever embedded browser the host has. Nothing else. The page is the UI.
5. **Subscribe to `GET /api/events?t=<token>`** and act on `event: notify` frames only. Each carries
   `{repo, severity, title, body, …}` already decided by the fleet's rules.
6. **Focus a tile with `#tile=<repo>`** — the same anchor the Windows toasts use, so there is one
   way to say "show me that one" and not two.
7. **Check `contract` on `/api/ping`** against your own and raise exactly one balloon on a mismatch.
   A shell built against an older contract mis-renders quietly, which is the kind of bug that gets
   blamed on the dashboard for a week.

**A shell contains no rule logic.** Which agents need a person, what to say and when to stay quiet
are `agentdata/fleet/notify.py`'s, and a second implementation in Kotlin or TypeScript would
eventually disagree with the tiles beside it. `tests/test_fleet_shells.py` asserts this rather than
leaving it to a review checklist: the shells may not name a state, a severity rule or a threshold.

### Building them

Neither is part of the Python wheel. CI builds both on every push:

| Artefact | Job | Verified |
| --- | --- | --- |
| `agentdata-fleet.vsix` | `ide · vscode extension` | compiles under `strict`, packages |
| `agentdata-fleet-*.zip` | `ide · jetbrains plugin` | builds on ubuntu **and** windows |

The JetBrains plugin builds against PyCharm Community 2024.2.5 with `sinceBuild = 232`
(PyCharm 2023.2) — it uses only long-stable platform API. `untilBuild` is `299.*` rather than open:
the plugin API's spelling for "no upper bound" moves between releases, and a far-future build number
means the same thing everywhere.

Both install **from disk**; there is no marketplace publishing and no signing budget assumed.
**Unverified:** whether corporate policy permits installing an unsigned plugin zip. If it does not,
that is a hard blocker for the JetBrains half and #99's External Tool remains the answer.

## What is not done here

JetBrains Gateway, remote development, and macOS/Linux IDE paths are out of scope. So is any UI in
either shell beyond hosting the page and one balloon type — the moment a shell grows its own view
of an agent, there are two answers to every question and no way to tell which is current.
