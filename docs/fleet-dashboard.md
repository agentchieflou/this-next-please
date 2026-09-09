# The multi-viewer

One local page, one tile per agent, live. The epic is named for YouTube's multi-view and this is
that page: a grid of agents, any one of which can be blown up to fill the window and dropped back.

```bash
ad-fleet serve --open
```

```
meta:
  ok: true
  source: ad-fleet serve
  url: "http://127.0.0.1:8765/?t=Yb3h…"
  port: 8765
  bound: 127.0.0.1 only
  note: "the token in the URL is required on every request; stop with Ctrl-C"
```

`--port 0` picks a free port. Either way the URL is written to
`~/.agentdata/fleet/serve.json`, so the IDE shells (#99, #100) can find the page without being told
where it is.

## Why a web page

The same artefact has to render in a PyCharm JCEF tool window, in VS Code's Simple Browser, and in
Edge on a fourth monitor. Those three embedders agree on exactly one thing, and it is HTML — so
#99 and #100 only have to decide *where* the page is shown, not build it again.

It is `http.server` and `ThreadingHTTPServer` from the standard library, SSE over a plain chunked
response, and hand-written HTML/CSS/JS shipped as package data. **No bundler, no framework, no
CDN**: JCEF and Simple Browser both sit behind the corporate proxy, so anything the page fetches
from the internet is a page that does not load at work — and it would look like a bug in the fleet
rather than in the markup. A test asserts the static files contain no external reference at all,
and the server sends `Content-Security-Policy: default-src 'self'` so the browser enforces it too.

The whole payload is about 20 kB.

## The URL and the token

The socket binds **127.0.0.1 and nothing else**. Every run generates a fresh token, and every
request — page, API and event stream — must carry it as `?t=…`. A request without it, or from a
non-loopback address, gets `403 not authorized` and is not told which of the two it got wrong.

The token is deliberately **not** a cookie. A cookie would be sent automatically by any page in the
browser, which is exactly what makes a local server on a known port drivable from a hostile tab;
a query parameter has to be known to be used.

This is loopback security, not authentication. It is the right size for a tool that runs on the
operator's own machine and is never reachable from another one. Remote access is out of scope.

## The page

| Part | What it shows |
| --- | --- |
| Tile header | number, repo name, state chip, ticket, age of the last event |
| Why line | the one sentence from the fold — the unblock sentence, the refused tool, the question |
| Cells | the **project's** own state, polled read-only: ticket, PR, refresh, git — each with its age |
| Link rail | ticket, board, report, dataset, workspace, repo, PR, Confluence page, local folder |
| Approval card | appears when that agent is waiting; the **dry-run payload in full**, Approve / Deny |
| Transcript | assistant text, tool calls, denials, phase changes — newest at the bottom |
| Tray | the files Downloads is offering this project: *attach* or *dismiss* |
| Verify | the newest `ad-uat` / `ad-pbip` summary the agent wrote to `.agent/out/`, beside the report link |
| About | *what is this project* — facts, open friction, PBIP models and reports, from the catalogue |
| Bottom row | reply box (→ `send`), Start (a ticket key in the same box), Stop |

The header carries the search box (`ad-fleet where` over the catalogue), the layout picker, the
theme, focus mode, the inbox tray and the Jira board. A cell that fails to poll goes **grey with the
error in a tooltip**, never wrong; a link with no fact behind it is absent, never broken.

The grid follows the number of registered repositories: four repos, four tiles. Click a repo name
(or double-click a tile) and it fills the window; `Esc` returns to the grid.

The default layout is `grid` (chosen in the four-screen sitting: [fleet-layouts.md](fleet-layouts.md)).
`roles` and `screens` are retired. An unknown `?layout=` falls back to `grid` with a notice in the
toolbar. Focus mode (`f`) filters to only agents that need human attention.

Chip colours are fixed across every theme, because a chip that means "needs you" has to be the same
red everywhere or the colour stops being information:

| Colour | State |
| --- | --- |
| blue | `running` |
| amber | `waiting_approval` |
| red | `needs_human`, `blocked`, `error` |
| green | `done` |
| grey | `starting`, `idle` |

### Keyboard

| Key | Does |
| --- | --- |
| `1`–`9` | focus that tile |
| `f` | focus mode: only the agents that need you |
| `/` | the search box — `where` over the catalogue |
| `i` | the inbox tray |
| `a` | approve the focused tile's pending write |
| `b` | the Jira board |
| `n` | notifications |
| `Esc` | back to the grid (or out of a text box) |

Deny has no shortcut on purpose: it needs a reason typed, and a one-key refusal with an empty
reason is the failure mode the gate was built to avoid.

## Themes

The dashboard shares its palettes 1:1 with the terminal: palettes come from `agentdata.theme` (#136, #150, #153),
rendered as CSS custom properties (`--bg`, `--text`, `--panel`, `--line`, `--select`, `--muted`, `--accent`,
`--focus`, `--running`, `--waiting`, `--human`, `--done`, `--idle`).

Theme choice is configured in `~/.agentdata/config.json` via `theme.default` (e.g. `ad-theme set greens --default`),
while each registered repository carries its project accent on its tile (`theme.projects.<name>`).
When `config.json` changes, `ad-fleet serve` broadcasts a `theme` SSE event, recolouring open windows
without a page reload. `none` follows system `prefers-color-scheme`.

## Endpoints

| Method | Path | What |
| --- | --- | --- |
| GET | `/` | the page |
| GET | `/static/…` | its two assets |
| GET | `/api/fleet` | every repo's state, the recent events, and the pending approvals |
| GET | `/api/events` | SSE; `?since=luna:12,other:4` resumes per agent |
| GET | `/api/themes` | the `.icls` palettes |
| GET | `/api/board` | your Jira tickets, and which repo each one belongs to |
| GET | `/api/history` | what was dispatched, how it ended, what it cost |
| GET | `/api/notifications` | what has been announced |
| GET | `/api/desk` | per project: links, polled cells, verify summaries, offered files, the selection |
| GET | `/api/show` | one project from the catalogue: facts, state, friction, PBIP |
| GET | `/api/inbox` | the tray: what Downloads is offering, and what is listed but not offered |
| GET | `/api/where` | the catalogue search behind the header's box |
| POST | `/api/start` | `{repo, ticket?, prompt?, force?}` |
| POST | `/api/send` | `{repo, message}` |
| POST | `/api/stop` | `{repo}` |
| POST | `/api/approve` | `{id, reason?}` |
| POST | `/api/deny` | `{id, reason}` |
| POST | `/api/select` | `{repo?, screens?}` — the project every window agrees on ([fleet-layouts.md](fleet-layouts.md)) |
| POST | `/api/attach` | `{id, repo}` — copies one Downloads file into `<repo>/.agent/in/<KEY>/` |
| POST | `/api/dismiss` | `{id}` — stop offering that file until it is downloaded again |

`select` and `dismiss` change nothing on disk inside a repository. `attach` is the single exception
in "the fleet never writes in a repository", and it is a click, a copy, and one `inbox.attached`
event.

Every POST calls the same function the matching `ad-fleet` verb calls, and a refusal comes back
with the same words and the same hint the CLI would print — `409` with `{ok: false, error, hint}`.
The page is a view: it decides nothing and spawns nothing.

### The stream

Resume cursors are **per agent** (`luna:12,other:4`), not one number. Each agent's `seq` is dense
and its own, so a shared cursor would replay one stream and skip another.

A `tick` event goes out at least every 15 seconds. It is not decoration: a proxy that sees no bytes
for a minute closes the connection, and the tiles then stop updating with nothing anywhere saying
why. On any disconnect the page reloads `/api/fleet` and redraws from scratch rather than trusting
what it drew before, then reopens the stream.

## What is not here

Authentication beyond the loopback token, and access from another machine — both out of scope, and
both would change what this is. Cost and budget are a strip in #101. Notifications when a tile turns
red are #97. Jira intake in the side panel is #98.

Screenshots from PyCharm and Edge belong with #99 and #100, where the embedding is what is being
shown; this page is the same page in all three.
