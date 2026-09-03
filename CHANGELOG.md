# Changelog

Read this before running `ad-update`: it says whether an update needs anything beyond the two standard commands
(a new optional dependency, a re-run of `ad-setup --patch`). Newest first. The top version here must match
`pyproject.toml`, and `ad-update --check` prints the version and commit you are actually running.

## 0.5.3 — 2026-09-03

**Setup UX: connect everything as fast as possible (Epic #14, sub-issues #21, #22, #23).**
- **Quick mode (`ad-setup --quick`, #21)**: middle ground between interactive and non-interactive setup. Accepts
  unambiguous detected facts (single ODBC DSN, tools found at standard paths, single workspace) without prompting,
  printing what was accepted to stderr. Passwords and ambiguous choices still prompt interactively. Check report
  indicates how many settings were auto-accepted.
- **Shareable team defaults (`ad-setup --export-defaults` / `--import`, #22)**: exports non-secret configuration
  without machine-specific verified stamps. `--import` loads defaults into the wizard without overwriting existing
  settings, combinable with `--quick` or `--patch`.
- **Parallel verification (#23)**: network verifications in `sources` (SELECT 1 + capability probes) and `powerbi`
  (XMLA smoke tests) now execute concurrently across environments and workspaces using bounded worker threads,
  substantially reducing wall-clock setup time while preserving exact reporting and deterministic timestamping.

## 0.5.2 — 2026-09-03

**`keyring` and `pyodbc` are now base dependencies.** Both lived behind per-connector extras (`teradata`,
`oracle`, `hive`, `impala`, `odbc`) plus a standalone `keyring` extra, so whether either was installed depended
on which one a user happened to pick at install time -- and `ad-setup` reaches for both regardless: keyring for
**any** password-auth source, pyodbc as soon as ODBC is offered as a connection mode for Teradata/Hive/Impala
(which the wizard can offer even on a bare install, if neither a native driver nor a working ODBC setup is
present). Pick an install command that skipped the right extra and the wizard died mid-run with `keyring is not
installed` on whichever step first tried to store a password -- occasional and confusing, because it depended on
a choice made several prompts earlier. (`pyodbc`'s own failure paths were already exception-guarded down to
`odbc.py`, so this one was a real gap, not a crash -- but the same "depends on which extra you picked" reasoning
applies, so it gets the same fix.)

Both now install with the package every time, regardless of extras. The old `[keyring]` and `[odbc]` extras are
kept as no-ops so an existing `pip install agentdata[keyring,odbc,...]` (this repo's own docs used to say to
type exactly that) still works rather than erroring on an unknown extra. The `ImportError` guards in
`agentdata/connectors/secrets.py` and `connectors/odbc.py` stay -- cheap insurance for a `--no-deps` or stripped
install -- but neither is the expected path anymore.

**Found and fixed while proving that: a broken keyring backend crashed the wizard and threw away everything
just answered for the current source, not only the password.** This is very likely the actual shape of the
report -- reproduced end to end, for real, through the CLI. Every guard in `secrets.py` was a bare
`except Exception:`, which does not catch everything a native extension can raise (a `PanicException` from a
Rust-backed dependency, reproduced here, subclasses only `BaseException`) -- so `has_password()`, `set_password()`
and `backend_name()` could all crash straight through, mid-question, with a raw traceback, before the step's
`C.put(...)`/`C.save(...)` ever ran. Answer every Teradata question including an LDAP/TD2 password on a machine
with a misbehaving keyring backend and **nothing** was saved -- not the password, not the host, not the mode. All
three now degrade to a clean `ConfigError` instead, and `ad-setup` catches it locally at the one call that can
actually fail (storing the password) and downgrades it to a `warn` row -- so the rest of the env's answers
(host, mode, logmech, user) are saved regardless of whether the credential store itself is working.

## 0.5.1 — 2026-09-03

Verified against a real Python 3.14.0rc2 interpreter (`uv python install 3.14`, every optional extra installed):
**246/246 tests pass, zero warnings.** `requires-python = ">=3.10"` needs no upper bound -- nothing in this repo
depended on anything 3.10-3.14 removed.

- The one thing 3.13+ flags: `re.split(pattern, val, 1)` -- a positional `maxsplit` -- is deprecated in favor of
  the keyword form. Fixed in `agentdata/config.py` (`AGENTS.md` fact parsing); it was the only call site and the
  only warning anywhere in the suite.
- Every compiled dependency (`pyodbc`, `oracledb`, `psutil`, `pandas`, `pyarrow`, `pyyaml`) already ships a cp314
  wheel; `pure-sasl` (impyla's Kerberos SASL, used by `ad-hive`/`ad-impala`) has no wheel on PyPI but is pure
  Python, so it builds from sdist in under a second -- no compiler needed, nothing to note for a user.
- CI now runs Python 3.14 on both Ubuntu and Windows (replacing the 3.12 Windows job -- Windows should track the
  version actually in use, same reasoning this file already applies to platform coverage), plus 3.10 (the floor)
  and 3.12 (today's common baseline) on Ubuntu.

## 0.5.0 — 2026-09-03

**This one needs `pip install`, not just `ad-update --skills`:** `rich` is a new dependency. `ad-update` (or
`pip install --force-reinstall "agentdata @ git+https://github.com/agentchieflou/this-next-please"`) pulls it in.
Every command still works without it -- the rendering falls back to the plain text it printed before.

- **The operator commands look like a tool now.** `ad-setup`, `ad-doctor`, `ad-update` and
  `python -m agentdata` render a rounded panel of facts, a real table with a status glyph (`✓ ok`, `! warn`,
  `✗ fail`) and word-wrapped hints, one label per group of rows, and section rules between wizard steps. Colour
  and glyph both carry the status, so a screenshot in black and white still reads.
- **Nothing an agent parses changed.** The pretty rendering is used only when a person is at the console:
  `color.enabled()` is already false whenever stdout is piped or captured, and `ui.on()` is false with it. Query
  results (`ad-td`, `ad-jira`, `ad-pbip`, `ad-uat`, `ad-dpm`, `ad-pncli`, ...) stay TOON even on a terminal,
  because `auto` cannot tell Luna's shell from a person's.
- Ask for a drawn result when you want to read one: `--pretty` on the query commands and `ad-view`, or
  `AGENTDATA_UI=rich` for everything. Numbers right-align, status words are coloured, and the sample size and
  `path` sit above it. `AGENTDATA_UI=plain` goes the other way -- TOON on a terminal, for pasting into a ticket.
- `AGENTDATA_WIDTH` pins the render width (screenshots, docs, tests). On a Windows console that cannot do VT,
  rich draws its ASCII box; everywhere else the Unicode one.

## 0.4.6 — 2026-09-03

- **Confluence pages are built, not written.** The page body was going up as raw Markdown, so a reader got
  `## mismatch` and `- L-1001` as literal text: Confluence renders Markdown as text, and asking the model to
  "write HTML" from a Markdown file produced Markdown with tags around it. `ad-confluence html <file.md>` now
  converts it — headings, nested lists, GFM tables with alignment, code blocks as the `code` macro with a CDATA
  body, links, autolinked URLs, bold/italic/strike, blockquotes, horizontal rules — escaping `&` `<` `>` and
  turning named HTML entities into characters, because storage format allows only the five XML ones. Every body
  is parsed as XML before it is returned, so a page is refused here with the text that broke it rather than by
  Confluence with a 400. `ad-confluence check <file>` validates a body that already exists.
- `ad-pncli raw --body-file` **refuses to post Markdown to Confluence**: a body with no markup at all but a
  `# heading`, a `- bullet` or a ``` fence is rejected, naming the construct and pointing at `ad-confluence html`.
  Only `confluence` commands are checked — a Jira comment may be plain text.
- **Jira transitions know that a Task is not a Story.** `bitbucket-pr` moved a ticket with a hard-coded
  `"In Review"`, which exists in a Story's workflow and often not in a Task's, in a command whose verb was a guess.
  `ad-jira transitions <KEY>` lists what *that* issue can do (id, name, target status, category, and the screen
  fields each demands); `ad-jira transition <KEY> --to <intent|name>` resolves an intent — `todo`, `in-progress`,
  `review`, `blocked`, `done` — against that list. `review` and `blocked` must match by name, so a Task with no
  review state is refused with what it *can* do instead of being parked in In Progress; `todo`, `in-progress` and
  `done` may also match by status category, so a workflow that spells them differently still resolves. Ambiguity
  is reported with the candidates, never broken by picking one.
- `--dry-run` resolves without moving; an issue already in the target status is a no-op, not a failure;
  transition screens are reported before the POST (`--resolution`, `--field NAME=VALUE`); the status is read back
  afterwards, so a post-function that undoes the move is caught; `--comment` is sent as ADF on Cloud and a plain
  string on Data Center; `--pin` remembers the resolved status per issue type in `jira.workflow.<type>.<intent>`.
- New skill `jira-transition`, wired into the router; `bitbucket-pr` delegates to it. `confluence-publish` calls
  `ad-confluence` and keeps its Markdown source as the thing it edits.

## 0.4.5 — 2026-09-03

- **confluence-publish now matches pncli.** The verb is `confluence create-page` and the body is passed **inline**
  (`--body <html>`), not `--body-file`; the skill still carried a `TODO(pin the verb)` placeholder and a markdown
  body. It now builds Confluence storage-format HTML and publishes with one pinned command.
- `ad-pncli raw --body-file <path>` reads a file and appends it as a single `--body <contents>` argument
  (`--body-arg` renames the option for a verb that calls it something else). No shell is involved, so quotes,
  newlines, `<`, `>` and `&` in a page survive intact, and a page longer than a command line still works. The echoed
  command summarises it as `<N chars from <file>>` instead of dumping the page into the agent's context.
- `--space`, `--parent` and `--title` are still unconfirmed against this pncli build: the skill says to run
  `pncli confluence create-page --help` once if one is rejected, and to report the names so they can be pinned.

## 0.4.4 — 2026-09-03

- **`ad-update` in a checkout is no longer an error.** It reported
  `error: this is a checkout / editable install`, `ok: false`, exit 2 — and refused the skills half too, which is
  independent and always valid. Now it updates the skills, skips only the CLI half (`skipped[1]: cli`), and exits 0:
  running from a clone is a state, not a failure. `--check` names which one (`git install`, `editable install`,
  `running from a checkout at <dir>`).
- `ad-update --pull` runs `git pull --ff-only` in that checkout instead of skipping; `ad-update --from-git` replaces a
  checkout or editable install with the published git install.

## 0.4.3 — 2026-09-03

Three fixes to the setup experience. No new dependencies.

- **Oracle thick mode could not authenticate.** Setting `client_lib` was read as "use external auth", so the wizard
  never asked for a username or password and the connector always passed `externalauth=True`. Authentication is now
  its own question (`password` / `kerberos` / `wallet`), independent of thick mode: thick + password works, and
  kerberos/wallet without a client lib is a named check failure instead of a connect-time error. Existing configs
  (a `client_lib` and nothing else) still mean Kerberos.
- **`ad-setup --patch` asked questions no answer could fix.** A row like `teradatasql not installed` carried the
  env's prompt keys, so --patch walked into that step and — with no terminal — died on the first prompt, which is why
  it looked like it only printed the doctor output. Rows fixed by an install or an ODBC DSN now carry no keys and are
  listed under `manual` with their hint. Scopes are also narrower (a missing service name asks one question), you can
  name a target (`ad-setup --patch sources.oracle.PROD.host`), the scan includes the online checks unless `--offline`,
  and a run with no terminal prints `needs_answers[]` and the `--set` line instead of failing on EOF.
- **Colour.** Status words, prompts and headings are coloured for a terminal, including PowerShell 5.1 (VT enabled
  through the console API — nothing to install), PyCharm and VS Code. Off automatically when piped, so TOON read by an
  agent is unchanged. `--color always|never`, `AGENTDATA_COLOR`, `NO_COLOR` and `FORCE_COLOR` all work.

## 0.4.2 — 2026-09-03

Oracle is configured by its parts. No new dependencies; existing Oracle settings keep working.

- `ad-setup` asks hostname, port, and service name (or SID) — the fields SQL Developer's Basic tab asks for —
  instead of one free-text "Easy Connect or TNS alias" string. Oracle has no ODBC DSN registry, so the parts had
  nowhere to come from. Choose the `tns` style to give an alias or a ready-made connect string instead.
- The connect string is composed at call time (`host:port/service`, or the `(DESCRIPTION=…(SID=…))` form), so
  `ORA_HOST_<ENV>`, `ORA_PORT_<ENV>`, `ORA_SERVICE_<ENV>` and `ORA_SID_<ENV>` now override individual parts.
- `ad-doctor` prints the composed target next to each Oracle env, and fails a host with no service name or SID by
  name instead of leaving it to fail at query time. `ad-setup --patch` repairs just that env.
- Oracle no longer offers the ODBC connection mode: an ODBC DSN handed to python-oracledb is read as a TNS alias.

## 0.4.1 — 2026-09-03

Review pass over everything merged in 0.4.0. No new dependencies; the standard update line is enough.

- **`python -m agentdata <cmd>` now exits with the command's code.** It always exited 0, so a refusal from
  `ad-dpm` or `ad-state` looked like success to any script gating on `$LASTEXITCODE` — on the very form the README
  recommends when the Scripts folder is off PATH.
- `ad-doctor` no longer reports a *working* pinned launcher as broken: it probes the path it resolved, not the bare
  name (a pinned launcher is usually not on PATH). It also honours `PNCLI_EXE`, which `ad-pncli` already did.
- `ad-setup --patch` can now repair a launcher that is found but will not start, not only a missing one.
- `ad-update` reports the mtime of the *newest* skill, not the alphabetically first — the evidence that
  `gh skill install` landed.
- Every DPM reader goes through `textio`, so a binding or manifest written by PowerShell redirection (UTF-16) loads.
- `ad-dpm inspect` cannot traceback on a damaged database, and one broken view no longer blinds the whole scan.
- `ad-dpm convert` refuses an existing handoff *before* hashing every source document.
- DPM producer paths: a document id that could name a file outside the run root is refused
  (`document-id-unsafe`), and a source document outside the run root is flagged (`source-outside-root`) instead of
  being silently accepted by a hint that claimed containment was checked.
- A pinned `.js` entry point runs through node, which is the escape hatch `proc`'s own refusal hint offers.
- CI: GitHub Actions runs the suite on Linux (3.10, 3.12) and Windows on every push and PR.

## 0.4.0 — 2026-09-02

New commands: `ad-update` (reinstall the CLI + skills, report the installed commit), `ad-state` (the only writer of
`.agent/state.json`), `ad-dpm` (DPM → consumer handoff contract), `ad-setup --patch`, `ad-pncli where`,
`ad-pncli jira get <KEY>`.

- **Update after installing this one.** The skills changed too (`session-bootstrap`, `state-update`, `friction-log`,
  `data-adapter`, `jira-triage`, new `dpm-consumer-integration`): run both halves, then start a new Copilot chat.
- No new dependencies. The standard `--force-reinstall --no-deps` update line is enough.
- Windows fixes from the laptop: npm-installed CLIs (`pncli.cmd`, `az.cmd`) are launched correctly, files written by
  PowerShell (UTF-8 BOM, UTF-16) are read everywhere, `az` is found in the Azure CLI install dir.
- `ad-setup --patch` re-asks only the settings behind failing checks. After updating, `ad-doctor` then
  `ad-setup --patch` is the fastest way back to green.
- `ad-doctor` now prints `version` and `commit` in its `meta`, so every session shows what it is running.

## 0.3.0 — 2026-09-02

Installable without a clone (`pip install "agentdata @ git+…"`), project stub ships in the wheel,
`python -m agentdata <command>` mirrors every console script, skill descriptions are strict YAML.

## 0.2.0 — 2026-09-01

`ad-setup`/`ad-doctor` wizard, SQL dialect lint, Jira changelog and sprint replay, PBIP projection/validator/editor,
Power BI Desktop discovery and DAX runner, UAT expect/plan/reconcile.
