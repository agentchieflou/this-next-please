# pncli: the inspiration, what we learned from it, and what we re-implemented

[pncli](https://www.npmjs.com/package/@kolatts/pncli) (`@kolatts/pncli`, an npm package by another team) is a
commander.js CLI over Jira, Confluence and Bitbucket. It was the first tool in this ecosystem to give an agent **one
command line over all three**, with every argument a named option, and this repository's first Jira path was built on
it: `ad-pncli` wrapped its verbs, `ad-setup --only pncli` borrowed its token, and `ad-doctor` failed without it. Since
the `jira` setup step and `ad-jira search|get|comments`, pncli is an **optional backend**: REST is the default for Jira,
and pncli is still the only path to a Confluence page or a Bitbucket PR. This page records what pncli taught us, so the
credit stays attached to the code that carries it. Nothing of pncli is vendored, copied or translated here; it is run
as an external program when it is installed, and only then.

## What we learned from it (and kept)
| pncli taught us | where it lives here now |
|---|---|
| **Every argument is a named option, never positional.** `get-issue RDSD-1` with the key bare reads as plausible and fails; `get-issue --key RDSD-1` works. The rule became a repo-wide contract: a wrapped verb takes its arguments by name, and a skill never writes a pncli recipe by hand | `HANDOFF.md`, `tests/test_skill_contracts.py::test_every_pncli_recipe_names_its_arguments`, `connectors/pncli.usage_hint` (turns pncli's `required option '--x'` error into the exact re-run) |
| **A read/write split by verb, behind one gate.** pncli's verbs partition cleanly into reads and writes, which is what let the fleet allow `ad-pncli` as a whole and gate only the writes -- a verb missing from the read list costs one click, a verb missing from a write list would be sent unattended | `READ_VERBS` / `is_write` in `agentdata/connectors/pncli.py`, `fleet/approval.py` (`pncli-write`); `ad-jira`'s own writes (`transition`, `comment`, `create`) go through the same gate |
| **An npm CLI is a `.cmd` shim on Windows, never an `.exe`.** `CreateProcess` only appends `.exe`, so the bare name died with `[WinError 2]` while the doctor said "ok". The fix -- resolve PATHEXT and the npm global prefix, unwrap the shim to `node <script>` so a JQL with `>` is never re-parsed by cmd.exe, and make a doctor row prove a launcher *starts* -- now protects every subprocess in this package (`az.cmd` included) | `agentdata/proc.py`, `Detectors.launcher`, `ad-pncli where`, `docs/windows-verification.md` |
| **An inline page body.** `pncli confluence create-page --body <html>` takes the whole page as one argument, which no shell can carry; `ad-pncli raw --body-file` hands the file across as one argv element and refuses a body that is still Markdown | `agentdata/cli.py` (`main_pncli`, `--body-file`), `ad-confluence html`, skill `confluence-publish` |
| **Borrow a token by key name, never by value.** `ad-setup --only pncli` stores the *dot-path* of the token inside `~/.pncli/config.json`, and the connector reads the value at call time. The same shape is why the `jira` step stores nothing but a keyring reference and why `config.assert_no_secrets` exists | `pncli.keys.*`, `jira_api.load_credentials` (pncli is its last fallback), `config._SECRET_EXEMPT` |
| **One TSV header for an issue.** `fields.status.name` is too long to type back into a JQL; pncli's flattened-then-shortened columns (`status`, `assignee`, `priority`, `updated`, `summary`) are the ones `ad-jira` prints too, so a skill written against either backend keeps working | `agentdata/connectors/jira_columns.py` |

## Re-implemented here over REST
| pncli verb | here | notes |
|---|---|---|
| `jira search --jql` | `ad-jira search --jql <JQL> [--fields …] [--max-results N]` | same columns; `meta.truncated` past `--max-results`, as pncli's was |
| `jira get-issue --key` | `ad-jira get <KEY> [--fields …]` | one row; the description as plain text (ADF decoded on Cloud), comments and attachments as counts |
| `jira comments --key` | `ad-jira comments <KEY>` | oldest first, bodies as plain text |
| `jira transitions` / a transition | `ad-jira transitions <KEY>`, `ad-jira transition <KEY> --to <intent>` | REST asks the issue type's workflow; `--dry-run` first, gated in a fleet |
| a comment | `ad-jira comment <KEY> …` | ADF on Cloud, plain on Data Center; never replayed |
| create an issue | `ad-jira create …` | the project's defaults from `AGENTS.md`, `--dry-run` first |
| changelog (pncli has none) | `ad-jira changelog`, `ad-jira sprint-replay` | the history the current state cannot give: budgets, resume, cache |
| the token | `ad-setup --only jira` (keyring) · `JIRA_TOKEN` · pncli's file last | `ad-jira whoami` shows `token_source`, never the token |

## Still delegated to pncli (the optional backend)
- `confluence create-page` -- through `ad-pncli raw --body-file <file.html> confluence create-page …` (skill `confluence-publish`).
- Bitbucket pull requests -- through `ad-pncli raw bitbucket …` (skill `bitbucket-pr`; the verb is pinned from `ad-pncli capture-help`).
- Any other Confluence or Bitbucket read -- `ad-pncli raw …`, `ad-pncli help <product>` for its usage.

There is no Confluence or Bitbucket REST client here yet; when one lands, these move to the table above.

## Deliberately not ported
- pncli's own config file and `pncli config init`: a second credential store would be one too many. The `jira` step keeps the token in the keyring, beside every other secret here, and reads pncli's file only as a fallback.
- Its raw JSON output as a default: every `ad-*` command answers through the format policy (TOON, a TSV past the threshold) so an agent never pages a payload into its context.
- Its Jira write verbs: writes here must pass the approval gate with a dry run first, and REST lets `ad-jira` ask the workflow what a transition means before posting it.

## Installing pncli as the optional backend
```
npm install -g @kolatts/pncli      # lands as pncli.cmd on Windows -- there is no pncli.exe
pncli config init                  # pncli's own config, ~/.pncli/config.json
ad-setup --only pncli              # pin the launcher it proved starts; pick the key names (values are never copied)
ad-doctor --only pncli             # all ok with pncli installed; skip rows without it
```
`pncli.required: true` in `~/.agentdata/config.json` makes a missing launcher a `fail` row again, for an install that
publishes pages or opens PRs. `pncli.exe` / `PNCLI_EXE` pin a launcher that is not on PATH.
