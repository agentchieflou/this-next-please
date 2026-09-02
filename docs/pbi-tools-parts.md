# pbi-tools: what we learned from it and what we re-implemented

[pbi-tools](https://github.com/pbi-tools/pbi-tools) is licensed **AGPL-3.0-or-later** (same license for the Desktop and Core
editions; they are one code base). This repository does not vendor, copy, translate or invoke pbi-tools. We studied its
documentation and the Microsoft APIs it drives, and re-implemented the *behaviour* we need in Python under this repo's license.
Facts about Power BI Desktop and Analysis Services are not copyrightable; pbi-tools source was used only as a map of where to look.

## Re-implemented (logic, not code)
| pbi-tools | here | notes |
|---|---|---|
| `info` → `pbiSessions` | `ad-pbip desktop` (`agentdata/pbip/desktop.py`) | enumerate `msmdsrv.exe`, read `-s`/`-n` from its command line, `msmdsrv.port.txt` (UTF-16), parent `PBIDesktop.exe`, window title / open file; glob fallback |
| `launch-pbi` | `ad-pbip launch` | shell-open the `.pbip`; Desktop does not hot-reload files |
| `export-data` (live) | `ad-pbip visual-query`, `dax-studio-export` via dscmd | `EVALUATE` over `localhost:<port>`; `Table[Column]` headers reduced to bare names |
| PbixProj report normalization (sorted keys, volatile fields stripped, one file per visual) | `ad-pbip project` | PBIR is already exploded; we add the LLM projection: normalized JSON, TSVs, MODEL.md / REPORT.md / LINEAGE.md |
| `-modelSerialization Tmdl` (Microsoft `TmdlSerializer`) | Tabular Editor 2 `-B` / `-TMDL` through `ad-pbip check --te2` | never re-implemented; TE2 is installed |

## Deliberately not ported
- `extract` / `compile`: PBIX/PBIT only; pbi-tools cannot read PBIP at all, and Desktop opens PBIP natively.
- `deploy`: compiles a PBIX and calls the Imports API (report) or TOM over XMLA (model); TE2 covers the model (`pbi-deploy-te2`).
- `cache`, `git`, `init`, `extract -watch`: pbi-tools-internal or made moot by PBIP.

## Stretch (documented for later)
Deploying a PBIR report or TMDL model without Desktop via the Fabric item-definition API:
`POST /v1/workspaces/{ws}/reports` · `POST .../reports/{id}/getDefinition?format=PBIR` · `POST .../updateDefinition` (replaces the
whole definition — include every part, never `.platform`), same for `semanticModels` with `format=TMDL`; 202 + `Operation-Id` /
`Location` polling; tokens via `msal` against `https://api.fabric.microsoft.com/.default`.
