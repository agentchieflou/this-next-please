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
| Approval card | appears when that agent is waiting; the **dry-run payload in full**, Approve / Deny |
| Transcript | assistant text, tool calls, denials, phase changes — newest at the bottom |
| Bottom row | reply box (→ `send`), Start (a ticket key in the same box), Stop |

The grid follows the number of registered repositories: four repos, four tiles. Click a repo name
(or double-click a tile) and it fills the window; `Esc` returns to the grid.

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
| `a` | approve the focused tile's pending write |
| `Esc` | back to the grid (or out of a text box) |

Deny has no shortcut on purpose: it needs a reason typed, and a one-key refusal with an empty
reason is the failure mode the gate was built to avoid.

## Themes

Light and dark follow `prefers-color-scheme`. The three PyCharm palettes in `themes/pycharm/` are
also offered, parsed from the `.icls` files themselves so there is one source of truth for a
colour, and the choice is remembered per browser. They change the surface colours only.

## Endpoints

| Method | Path | What |
| --- | --- | --- |
| GET | `/` | the page |
| GET | `/static/…` | its two assets |
| GET | `/api/fleet` | every repo's state, the recent events, and the pending approvals |
| GET | `/api/events` | SSE; `?since=luna:12,other:4` resumes per agent |
| GET | `/api/themes` | the `.icls` palettes |
| POST | `/api/start` | `{repo, ticket?, prompt?, force?}` |
| POST | `/api/send` | `{repo, message}` |
| POST | `/api/stop` | `{repo}` |
| POST | `/api/approve` | `{id, reason?}` |
| POST | `/api/deny` | `{id, reason}` |

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
