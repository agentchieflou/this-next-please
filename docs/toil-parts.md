# toil: the service backend, used directly, extended where it stops

[toil](https://github.com/imagile-dev/toil) (`@imagile-dev/toil`, an npm package by Imagile) is one CLI over Jira,
Confluence, Bitbucket and the rest of an enterprise's tools, answering every command with one JSON envelope
(`{ok, data, error, meta}`). Since 0.22.0 it is this repository's service backend, in the place pncli held (pncli's
account is at the end). Nothing of toil is vendored, copied or translated here; it is installed with npm and run as
itself.

**The rule** is the one pncli had (the operator, 2026-10-09): use the tool directly when possible, and build on top
of it only when necessary. So an `ad-*` command exists only where it adds something toil does not do. toil is
required (`ad-doctor` fails without it), and it is used directly for everything it does. There is no general
`ad-*` pass-through over toil: 0.20.0 retired the pncli wrapper for exactly that reason.

## What we use directly
| Need | Command | then |
|---|---|---|
| Jira rows | `toil jira issue search --jql "<JQL>" --limit 500 > .agent/out/<name>.json` | `ad-view .agent/out/<name>.json` |
| One issue | `toil jira issue get <KEY> > .agent/out/<KEY>.json` | `ad-view .agent/out/<KEY>.json` |
| Its comments | `toil jira issue comments <KEY> > .agent/out/<KEY>-comments.json` | `ad-view .agent/out/<KEY>-comments.json` |
| A Confluence page, a Bitbucket PR | `toil confluence page get <id>`, `toil bitbucket pr get <id>`, saved under `.agent/out/` | `ad-view` it |
| Its usage | `toil <area> --help`, `toil <area> <resource> --help` | |

`ad-view <file.json>` is the data format rule without a wrapper: toil prints an envelope, the file keeps every row on
disk, and `ad-view` renders its `data` through the format policy as TOON (`docs/data-format-policy.md`). A Jira
search or a single issue gets the Jira columns below; anything else is the envelope's result list, normalized. A
failed envelope prints toil's own `error.code`, message and `fix`; `meta.warnings` and the next page's cursor stay on
the rendered meta, so a partial answer never reads as a whole one. The fleet reads the same way in-process
(`connectors/toil.py`: the PR read of the poll, the issue read of a pre-flight, the UAT live side).

## What we extend, and where
| Extension | Why toil alone is not enough | Where |
|---|---|---|
| `ad-jira changelog`, `sprint-replay`, `cache` | toil's `jira issue history` reads one issue's history, and warns when Data Center truncated it; the history *analysis* -- changelog normalization, budgets, resume, a cache, sprint replay, points and status reconstruction -- is ours. Its REST calls go through `toil jira api` | `agentdata/cli_jira.py`, `jira_api.py` |
| `ad-jira transition --to <intent>`, `transitions` | asks the issue type's own workflow what a transition means and shows it before posting; `--dry-run` first, gated | `agentdata/jira_workflow.py` |
| `ad-jira comment`, `ad-jira create` | gated writes; `create` fills the project's `jira_*` facts from `AGENTS.md` | `agentdata/cli_jira.py`, `jira_create.py` |
| `ad-jira match`, `whoami`, `fields`, `statuses`, `sprints` | ticket matching, the Sprint and Story Points field ids | `agentdata/cli_jira.py` |
| `ad-confluence publish <file.md>` | builds storage format from Markdown, resolves space, title and parent from the project's facts, and runs `toil confluence page create` / `page update <id>` with the body on stdin, behind the approval gate (`confluence-publish`) | `agentdata/cli_confluence.py` |
| `ad-git pr` | the PR for the current branch, never from a protected branch or a detached head, through `toil bitbucket pr create` / `update <id>`, behind the approval gate (`bitbucket-pr`) | `agentdata/cli_git.py` |
| the fleet's toil shim | a fleet agent runs `toil` directly; the shim first on its PATH runs a read and refuses a write (`toil_write_in_fleet`), naming the extension | `agentdata/fleet/toil_gate.py` |

## The behavioural differences, and how each is held
**Approval is not permission.** toil gates a write itself: `writes: true` on the connection, set by a person, and
`--allow-write` on the call; without either it answers `WRITE_DISABLED` and sends nothing. toil has **no
`--dry-run`**: a write without `--allow-write` is a refusal, not a preview. So the preview stays the overlay's -- every
`ad-*` write's own `--dry-run` prints the exact toil command it would run -- and `--allow-write` is added only to the
run the operator approved, which executes exactly the reviewed command, connection named. A connection stays read-only
until a person turns writes on, and the overlay reads that before it plans (`toil.write_target`, from `toil connections
list`): no toil, no connection, or writes off is refused (`toil_not_ready`, `no_connection`, `writes_off`), dry run
included, so nobody approves a write toil would refuse. A Cloud connection (`bitbucket-cloud`, `confluence-cloud`) is
written through its own area.

**What counts as a write.** `toil.is_write` is `--allow-write` anywhere on the line (toil refuses a service write
without it, so its absence proves a read), plus the commands that write toil's own setup without the flag:
`connections` (but `list`, `test`), `dossiers` (but `list`, `show`, `context`, `check`), `skill`, `skills`, `setup`,
`feedback`, `mcp`. The shim gates the command line only; an MCP server a person registers with toil is outside it,
which is why the doctor reports every connection with writes on.

**Credentials move by supported setup, never by copied JSON.** toil keeps a token in the OS credential store (or a
`TOIL_*` variable) and refuses a plaintext one in its config. This package never reads it: `ad-jira`'s REST calls are
sent *through* toil (`toil jira api <METHOD> <path>`, `connectors/toil.ApiOpener`), so the token stays with the
connection and its host. The order is env (`JIRA_TOKEN`), then toil's Jira connection, then the keyring fallback of
`ad-setup --only jira`. A connection is set up by a person (`toil connections add`, or the menu a bare `toil` opens);
`ad-setup --only toil` only pins the launcher and, when an area has several, which connection is whose.

**The envelope is not the contract.** toil's `--output-format toon` puts TOON text inside the envelope's `data`, and
some consumers want bare TSV paths and stable columns. So `ad-*` contracts are kept, never toil's stdout forwarded:
`ad-view` normalizes an envelope into the table and artifact contract, and every in-process read raises a failed
envelope as `ToilError` with toil's code and fix.

**Pagination and history completeness.** `toil jira issue search` without `--limit` pages through everything; with it,
`meta.page.nextCursor` says there is more, and `ad-view` keeps it as `next_cursor`. `toil jira issue history` can be
truncated on Data Center (`JIRA_CHANGELOG_TRUNCATED`): a successful read is not a complete history, which is why
`ad-jira changelog` keeps its own paging, budgets and resume.

**Arguments are positional again.** pncli named every argument (`--key RDSD-1`); toil takes ids positionally
(`toil jira issue get RDSD-1`) and everything else as a flag. The skills' recipes are checked against the commands
toil has (`tests/test_skill_contracts.py`).

**The PR provider is the remote's host.** `ad-git pr` writes through the toil connection on the host of the branch's
remote: `github pr create|update` for GitHub or Enterprise Server (toil's `api.github.com` stands for `github.com`),
`bitbucket pr create|update` otherwise. toil's `bitbucket pr create` has no draft flag, so on Bitbucket a PR opens
ready for review and `--draft` is refused (`draft_unsupported`) rather than quietly ignored; GitHub's takes `--draft`.
End of day in the fleet's wrap-up leaves a PR create unticked and says why. The fleet's PR cell reads either kind of
link (`/pull-requests/<n>`, `/pull/<n>`), and a GitHub PR closed with `merged: true` is `MERGED`.

**Node 24.14+.** toil needs it, and answers `UNSUPPORTED_NODE` below it; the doctor's launcher row proves `toil
version` answers, not that a file exists.

## What pncli taught us (and we kept)
| pncli taught us | where it lives here now |
|---|---|
| **A read/write split behind an approval gate.** pncli's verbs partitioned into reads and writes, and a write went through a gated extension | `toil.is_write`, the fleet's shim, the `ad-*` approval gate (`docs/fleet-approvals.md`) |
| **An npm CLI is a `.cmd` shim on Windows, never an `.exe`.** `CreateProcess` only appends `.exe`, so the bare name died with `[WinError 2]` while the doctor said "ok". The fix -- resolve PATHEXT and the npm global prefix, unwrap the shim to `node <script>` so a JQL with `>` is never re-parsed by cmd.exe, and make a doctor row prove a launcher *starts* -- protects every subprocess here, toil's included | `agentdata/proc.py`, `docs/windows-verification.md` |
| **A page body never travels on a command line.** pncli took it inline as one argument; toil reads it from `--body-file -`, so it goes on stdin and survives even a plain `.cmd` shim | `agentdata/cli_confluence.py`, `proc.run(stdin_text=...)` |
| **One TSV header for an issue.** pncli's flattened-then-shortened columns (`status`, `assignee`, `priority`, `updated`, `summary`) are what `ad-view` prints for a saved search or issue | `agentdata/connectors/jira_columns.py` |

## What we retired with pncli (0.22.0), and why
| Retired | Why | Instead |
|---|---|---|
| `connectors/pncli.py`, its launcher pin (`pncli.exe`, `PNCLI_EXE`) and npm-package check | toil is the backend | `connectors/toil.py`; `toil.exe`, `TOIL_EXE` |
| Borrowing the Jira token from `~/.pncli/config.json` by key name (`pncli.keys.*`) | a secret read out of another tool's file; toil refuses plaintext secrets and keeps them in the OS store | requests go through `toil jira api`; the `pncli` config section is reported and removed by `ad-setup --only toil` |
| The pinned write-verb templates (`pncli.verbs.page_create`, `pr_create`, ...) and `refused: not_pinned` | toil's verbs are fixed and documented | `toil confluence page create` / `update`, `toil bitbucket pr create` / `update` |
| The fleet's pncli shim (`fleet/pncli_gate.py`, `pncli_write_in_fleet`) | the gate follows the tool | `fleet/toil_gate.py`, `toil_write_in_fleet`; a stale `pncli` shim is removed from the fleet's bin |
| `tools.pncli_verified` | | `tools.toil_verified` |

Earlier, 0.20.0 retired the pncli wrapper command and 0.19.0 the `ad-jira search|get|comments` REST
reads, both as duplicates of the tool's own verbs. History and changelog entries keep their names.

## Installing toil
```
npm install -g @imagile-dev/toil   # needs Node 24.14+; lands as toil.cmd on Windows -- there is no toil.exe
toil                               # a person adds the Jira, Confluence and Bitbucket connections (tokens to the OS store)
ad-setup --only toil               # pin the launcher it proved starts; pick a connection where an area has several
ad-doctor --only toil              # every row ok; --online runs `toil connections test` for each
```
`toil.exe` / `TOIL_EXE` pin a launcher that is not on PATH, including a clone's `dist/toil.js` (run under `node`). A
machine that cannot have toil still gets Jira's extensions from `ad-setup --only jira` (a token in the keyring, the
fallback), and `ad-doctor` says toil is missing.
