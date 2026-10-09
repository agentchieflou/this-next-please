# pncli: used directly, extended where it stops, and credited

[pncli](https://www.npmjs.com/package/@kolatts/pncli) (`@kolatts/pncli`, an npm package by another team) is a
commander.js CLI over Jira, Confluence and Bitbucket. It was the first tool in this ecosystem to give an agent **one
command line over all three**, with every argument a named option, and this repository's first Jira path was built on
it. Nothing of pncli is vendored, copied or translated here; it is installed with npm and run as itself.

**The rule (the operator, 2026-10-09):** *"We still want to keep leveraging pncli, but we don't need an [`ad-` wrapper of pncli]. We
should just use pncli directly when possible, and only build on top of it when necessary."* So an `ad-*` command
exists only where it adds something pncli does not do. pncli is required (`ad-doctor` fails without it), and it is
used directly for everything it does.

## What we use directly
| Need | Command | then |
|---|---|---|
| Jira rows | `pncli jira search --jql "<JQL>" --max-results 500 > .agent/out/<name>.json` | `ad-view .agent/out/<name>.json` |
| One issue | `pncli jira get-issue --key <KEY> > .agent/out/<KEY>.json` | `ad-view .agent/out/<KEY>.json` |
| Its comments | `pncli jira comments --key <KEY> > .agent/out/<KEY>-comments.json` | `ad-view .agent/out/<KEY>-comments.json` |
| A Confluence page, a Bitbucket PR or diff | pncli's own read verbs (`confluence get-page`, `bitbucket get-pr`, …) saved under `.agent/out/` | `ad-view` it |
| Its usage | `pncli <product> --help`, `pncli <product> <verb> --help` | |

`ad-view <file.json>` is the data format rule without a wrapper: pncli prints JSON, the file keeps every row on disk,
and `ad-view` renders it through the format policy as TOON (`docs/data-format-policy.md`). A Jira search or a single
issue gets the Jira columns below; anything else is pncli's result list, normalized. The fleet reads the same way
in-process (`connectors/pncli.py`: the PR read of the poll, the issue read of a pre-flight, the UAT live side).

## What we extend, and where
| Extension | Why pncli alone is not enough | Where |
|---|---|---|
| `ad-jira changelog`, `sprint-replay`, `cache` | pncli has no history: budgets, resume and a cache for the questions the current state cannot answer | `agentdata/cli_jira.py`, `jira_api.py` |
| `ad-jira transition --to <intent>`, `transitions` | asks the issue type's own workflow what a transition means before posting it; `--dry-run` first, gated | `agentdata/jira_workflow.py` |
| `ad-jira comment`, `ad-jira create` | gated writes; `create` fills the project's `jira_*` facts from `AGENTS.md` | `agentdata/cli_jira.py`, `jira_create.py` |
| `ad-jira match`, `whoami`, `fields`, `statuses`, `sprints` | ticket matching, flavor detection, the Sprint and Story Points field ids | `agentdata/cli_jira.py` |
| `ad-confluence publish <file.md>` | builds storage format from Markdown, resolves space, title and parent from the project's facts, and runs pncli's page verb with the body as **one** argv element, behind the approval gate (`confluence-publish`) | `agentdata/cli_confluence.py` |
| `ad-git pr` | the PR for the current branch, never from a protected branch or a detached head, through pncli's PR verb, behind the approval gate (`bitbucket-pr`) | `agentdata/cli_git.py` |
| the fleet's pncli shim | a fleet agent runs `pncli` directly; the shim first on its PATH runs a read and refuses a write (`pncli_write_in_fleet`), naming the extension | `agentdata/fleet/pncli_gate.py` |

The two write extensions run whatever verb the operator pinned from pncli's own help, never a guessed one:
`pncli.verbs.page_create`, `page_update`, `pr_create` and `pr_update` are argv templates with `{placeholders}`,
set with `ad-setup --only pncli --non-interactive --set pncli.verbs.page_create="confluence create-page --space {space}
--title {title} --body {body}"`. Unset, each answers `refused: not_pinned` with the help to read.

## What pncli taught us (and we kept)
| pncli taught us | where it lives here now |
|---|---|
| **Every argument is a named option, never positional.** `get-issue RDSD-1` with the key bare reads as plausible and fails; `get-issue --key RDSD-1` works. Every pncli recipe in a skill names its arguments | `tests/test_skill_contracts.py::test_every_pncli_recipe_names_its_arguments`, `connectors/pncli.usage_hint` (turns pncli's `required option '--x'` error into the exact re-run) |
| **A read/write split by verb.** pncli's verbs partition cleanly into reads and writes. A verb missing from the read list costs one refused read; a verb missing from a write list would be sent unattended -- so the list is of reads | `READ_VERBS` / `is_write` in `agentdata/connectors/pncli.py`, the fleet's shim, `tests/test_skill_contracts.py::test_every_pncli_recipe_in_a_skill_is_a_read` |
| **An npm CLI is a `.cmd` shim on Windows, never an `.exe`.** `CreateProcess` only appends `.exe`, so the bare name died with `[WinError 2]` while the doctor said "ok". The fix -- resolve PATHEXT and the npm global prefix, unwrap the shim to `node <script>` so a JQL with `>` is never re-parsed by cmd.exe, and make a doctor row prove a launcher *starts* -- now protects every subprocess in this package (`az.cmd` included) | `agentdata/proc.py`, `Detectors.launcher`, `docs/windows-verification.md` |
| **An inline page body.** `pncli confluence create-page --body <html>` takes the whole page as one argument, which no shell can carry; `ad-confluence publish` hands it across as one argv element and builds it from Markdown so a page is never posted as Markdown | `agentdata/cli_confluence.py`, `connectors/pncli.template_argv` |
| **Borrow a token by key name, never by value.** `ad-setup --only pncli` stores the *dot-path* of the token inside `~/.pncli/config.json`, and `ad-jira` reads the value at call time | `pncli.keys.*`, `jira_api.load_credentials` (env, then pncli's config, then the keyring fallback), `config._SECRET_EXEMPT` |
| **One TSV header for an issue.** `fields.status.name` is too long to type back into a JQL; pncli's flattened-then-shortened columns (`status`, `assignee`, `priority`, `updated`, `summary`) are what `ad-view` prints for a saved search or issue | `agentdata/connectors/jira_columns.py` |

## What we retired, and why
| Retired | Why | Instead |
|---|---|---|
| The pncli wrapper command (its `jira search`, `get` and `comments`, `raw`, `help`, `where`, `capture-help`), 0.20.0 | it wrapped what pncli already does; its one real job, the format rule, is `ad-view`'s | pncli directly, then `ad-view`; `pncli <product> --help`; `ad-doctor --only pncli` |
| Its `raw --body-file` page write | the write belongs in a gated extension that builds the body itself | `ad-confluence publish` |
| Its help capture for the operator | pinning a verb is reading one `--help` and setting one template | `pncli <product> --help`, then `ad-setup --set pncli.verbs.*` |
| `ad-jira search`, `get`, `comments` over REST (0.19.0) | duplicate reads of pncli's own verbs | `pncli jira search`, `get-issue`, `comments`, then `ad-view` |
| `pncli` on the fleet's deny floor | a deny is a prefix: it either blocks every read or misses a write nobody listed | `shell(pncli)` allowed; the shim gates writes |
| The `pncli-write` approval kind | no pncli write is made unattended any more | `confluence-publish`, `bitbucket-pr` |

## Installing pncli
```
npm install -g @kolatts/pncli      # lands as pncli.cmd on Windows -- there is no pncli.exe
pncli config init                  # pncli's own config, ~/.pncli/config.json
ad-setup --only pncli              # pin the launcher it proved starts; pick the key names (values are never copied)
ad-doctor --only pncli             # every row ok
```
`pncli.exe` / `PNCLI_EXE` pin a launcher that is not on PATH. A machine that cannot have pncli still gets Jira's
extensions from `ad-setup --only jira` (a token in the keyring, the fallback), and `ad-doctor` says pncli is missing.
