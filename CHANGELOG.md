# Changelog

Read this before running `ad-update`: it says whether an update needs anything beyond the two standard commands
(a new optional dependency, a re-run of `ad-setup --patch`). Newest first. The top version here must match
`pyproject.toml`, and `ad-update --check` prints the version and commit you are actually running.

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
