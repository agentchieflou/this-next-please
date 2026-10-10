# npm in this repository: a dev manifest, a lockfile, and nothing that ships

`package.json` at the root is **dev-only**. It pins the desk's type checker and the npm package the vendored
three.js is copied from, and it makes `ide/vscode` a workspace so the repository has one lockfile. Nothing in
it reaches the wheel, the page or the laptop at runtime: the desk is still hand-written files served from
`agentdata/fleet/static/` and the page still fetches nothing from the internet
([fleet-dashboard.md](fleet-dashboard.md): no bundler, no framework, no CDN). The spike that proposed this is
[spike-tools-and-fleet-improvements.md](spike-tools-and-fleet-improvements.md) §3a and the operator's npm facts in
[windows-verification.md](windows-verification.md) §0a.

## What it gives

| | Before | Now |
|---|---|---|
| The desk's compiler | `npx --yes -p typescript@7.0.2`, fetched ad hoc; the extension on `^5.4` | one `typescript` 7.0.2 in the lockfile; `npm run types` for the desk, `npm run compile -w ide/vscode` for the extension, the same binary |
| The vendored three.js | a file copied by hand, "pinned by sha256" in a test | `three@0.160.0` in the lockfile; `npm run vendor` copies `build/three.module.min.js` and `LICENSE` into `static/vendor/three/` and writes `VENDORED.json`; `npm run vendor:check` fails CI if the served file is not that package's build, byte for byte. An upgrade is a one-line bump, a re-vendor and a diff |
| Vetting | whatever `npx` fetched that day | the lockfile: every package, version and integrity hash in one reviewed file, and `tests/test_desk_types.py::test_the_lockfile_is_the_vetting_list_and_every_pin_is_exact` holds it to the names in `VETTED` |
| Bumps | by hand | Dependabot (`.github/dependabot.yml`), weekly, two PRs at most, TypeScript and its types grouped |
| On the laptop | the type check ran only in CI | `npm ci` once, through the proxy's route, then `npm run types` and `npm run vendor:check` before a push |

## The vetting list

What `npm ci` installs, and nothing else. A new name is a review, then a line in `VETTED` in
`tests/test_desk_types.py`, then the lockfile.

| Package | Why | Depends on |
|---|---|---|
| `typescript` 7.0.2 | the desk's and the extension's compiler | `@typescript/typescript-<platform>` binaries, one per platform; npm installs the matching one |
| `three` 0.160.0 | the source of the vendored file; never imported by anything that runs | nothing |
| `@types/node`, `@types/vscode` | the extension's types (its own `devDependencies`) | `undici-types` (from `@types/node`) |
| `@vscode/vsce` | packages the `.vsix`; CI only, through `npx`, not in the lockfile | — |

## Commands

```
npm ci --no-audit --no-fund        # the lockfile, exactly; never `npm install` in CI
npm run types                      # tsc --noEmit over the desk (docs/desk-types.md)
npm run vendor:check               # the served three.js is three@<lockfile>'s build
npm run vendor                     # re-copy it after bumping `three`; commit what it writes
npm run compile -w ide/vscode      # the extension, under strict
```

Without the install, the desk's check still runs as `npx --yes -p typescript@7.0.2 tsc -p tsconfig.json`; the
test falls back to that spelling when `node_modules/.bin/tsc` is absent.

## On the laptop

Node.js is installed and `npm install` reaches the registry only through the route Playwright's install uses;
every npm package is vetted before it is installed ([windows-verification.md](windows-verification.md) §0a). So:
`npm ci` is run once, through that route, and the lockfile is what was vetted. Nothing else on the laptop
changes: `ad-update` installs the wheel as before, and the page serves the committed vendored file.

## What this is not

- **Not a bundler.** Nothing is built into the served files; `tsc` emits nothing for the desk (`noEmit`).
- **Not a runtime dependency.** A laptop with no `node_modules` runs the fleet exactly as before.
- **Not a publish.** `private: true`; the package has no registry and no version of its own. Publishing the
  extension to a marketplace, or anything else to npm, is a separate decision
  ([spike-tools-and-fleet-improvements.md](spike-tools-and-fleet-improvements.md) §4, and the spike's note that
  `agentdata` itself never goes to npm).
- **Not `@types/three`, yet.** Typing the three.js-importing desk files (TOOLS-D8) is the next step; it is one
  more name in the vetting list now, not a stub.
