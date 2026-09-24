# The fleet map

The fleet map is the fleet drawn as its structure rather than as tiles: each project, the main checkout its
worktrees hang from, each checkout's agent and who started it, and (later) branches and the network around them.
It is **read-only**: nothing on the map starts, stops or changes anything; the desk does that. Epic #295.

## The graph

`GET /api/map` (token required, like every route but `/api/ping` and `/open`) answers
`{ok: true, schema: 1, as_of, cursor, says, projects, checkouts, theme}`. It is a pure fold over the same snapshot
`/api/fleet` sends (`agentdata/fleet/fleetmap.py`, `graph(snapshot)`): no git call, no registry or `.agent/` read,
the same snapshot always gives an equal graph. It never carries a path and never carries event text. Twenty
checkouts fit in under 16 KiB.

| Key | What |
| --- | --- |
| `schema` | `1` |
| `as_of` | the rows' read order (`{run, n}`), `null` for an empty fleet |
| `cursor` | `luna:12,uat:4`: each checkout's last `seq`, what `/api/events?since=` takes |
| `says` | *3 projects, 5 checkouts, 4 agents working, 1 needs you*; zeros read *no projects*, *no agents working*, *nobody needs you*. "Working" is `state == "running"` only |
| `projects[]` | `{id: "p:<project>", name, root, says}` by name. `root` is `c:<repo>` of the checkout that is no one's worktree (first by name if several), `""` when every checkout is a worktree of an unregistered main |
| `checkouts[]` | `{id: "c:<repo>", repo, project, main, worktree_of, worktree_of_unregistered, branch, dirty, ahead, behind, says, agent}` by project, main first, then name. `main` is true on the project's root only. `worktree_of` is `c:<repo>` of the registered main it hangs from, else `""`; `worktree_of_unregistered` is true when git points at a main the fleet does not know. `branch`/`dirty`/`ahead`/`behind` come from the git poll, and are `""`/`false`/`0` before it ticks |
| `agent` | `{id: "a:<repo>", kind, live, state, role, needs_human, stale, renew_queued, ticket, phase, model, age_s, turns, sessions_n, subagents, says}`. `live` is the row's `supervised`; `role` is `STATE_ROLES[state]`; `subagents` is `0` until #402 |

**`kind`**, the first that applies (`fleetmap.KINDS`):

| Kind | When |
| --- | --- |
| `console` | a live console lock, or a run whose `started` event says `console` |
| `adopted` | a live adopted (external) lock, or a run whose `started` event says `adopted`/`external` |
| `adoptable` | an adoptable session sits in the checkout |
| `headless` | a run the fleet started (`copilot -p`), alive or finished |
| `none` | never a run |

The run's origin is `/api/fleet`'s `row.run.origin` (`serve.split_runs`), because a headless agent exits at the
end of every turn: liveness alone would read a finished agent that stopped with a question as "no session".

**`says`**. A checkout: *worktree luna-velocity on feature/RDSD-101-velocity, of luna*, then *uncommitted changes*,
*n ahead*, *n behind* when true. An agent: `<kind words> · [finished · ]<state words>[ · ticket]`, *finished* when
it is not live and a run exists, e.g. *background agent (headless) · running · RDSD-101*, *background agent
(headless) · finished · needs you*, *console agent · needs you*, *no session · idle*; then, when true, *· 2 sub-agents
(not yet measured)*, *· began on an older install*, *· renew queued*.

Built on the defaults for "the monorepo" (a project's root is its main checkout) and "background agents" (`headless`
is a run the fleet started, alive or finished). Another answer changes `kind_of` and its words.

## Branches

(written by #403)

## The network

(written by #404)

## The page

(written by #405)

## Staying live

(written by #406)

## Layout

(written by #408)

## The scene

(written by #409)

## Agents

(written by #410)

## Moving around

(written by #411)

## Focus and picking

(written by #412)

## Motion

(written by #413)

## Skins

(written by #414)

## Budgets

(written by #405)

## Measured

(written by #415)
