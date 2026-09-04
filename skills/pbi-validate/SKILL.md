---
name: pbi-validate
description: "Use after any model (TMDL) or report (PBIR) edit and before deploy — proves the report still resolves against the model. Runs ad-pbip check (field references, names, structure), Tabular Editor for real TMDL/DAX errors, and, when Power BI Desktop is open, evaluates the affected visuals' DAX. Never deploy without it."
---
# Validate the model and the report together

Inputs: `pbip_path`, `te2_exe` (AGENTS.md or ad-setup). Prereq: the edit is committed (`git status --porcelain` empty).

1. Structure: `ad-pbip check` → every `error` row is a broken reference (visual field, filter, relationship, sort-by, hierarchy level, `ref table`) with `where` (file:line or visual id) and a `hint`. Fix in the file named; a field the report uses but the model lost → restore it or fix the visual JSON (rename only, same `name`/ids). Re-run until `errors: 0`.
2. Authoritative model check: `ad-pbip check --te2` (adds a Tabular Editor 2 build of the TMDL folder) and `ad-pbip model audit` (evaluates model best-practice rules; audit errors count as failures, warnings stay warnings). Fix errors in TMDL. Optional `--bpa` for best-practice warnings (do not fix warnings unless asked).
3. Live check when Desktop is open: `ad-pbip desktop status` lists running instances (`server: localhost:<port>`). Desktop does not hot-reload files — if the edit happened after Desktop opened the PBIP, reload it cleanly with `ad-pbip desktop reload --pid <pid>`, then `ad-pbip check --server localhost:<port>` (evaluates every measure the report uses) and, for each visual `ad-pbip refs --visual` listed for the changed objects, `ad-pbip visual-query --visual "<title>" --server localhost:<port>` — a DAX error or an empty result where rows are expected is a failure.
3b. Visual regression check: when visuals or themes are edited, capture before/after screenshots with `ad-pbip screenshot --pid <pid> --page "<page>" --out .agent/out/after.png --compare .agent/out/before.png --threshold 0.001` (or `--visual "<title>"`). Any visual regression beyond threshold is a failure.
3c. Service parity check: for deployed models, invoke `pbi-verify-service` (`ad-pbi verify --pbip <dir> --workspace <ws> --model <model>`) to assert service measure evaluation and Desktop-vs-service numerical parity.
3d. Native feature check: `ad-pbip check --features` (and with `--server localhost:<port>` when Desktop is open) lists native feature coverage. For features touched by the ticket (from `ad-pbip refs`), live check must report `ok`. Refuse handoff on any feature `fail`.
4. Regression on numbers: export before/after with `dax-studio-export` and `ad-diff` when the ticket changed logic, not just layout.
5. Any failing step twice → `friction-log` type `tool-error` with the failing row. Never edit the report JSON beyond renames to make a check pass.
6. All green → `ad-pbip project --force`, `state-update` `phase=validating`. Hand off → `pbi-deploy-te2` when the ticket deploys, else → `bitbucket-pr`.
