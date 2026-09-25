# Implementation brief: the post-ink epics (#288 to #295)

_For the Gemini agents that build them, and the Opus 5.5 agents that review them and take over when a builder runs
out of context. Written 2026-09-24 against `main` at 8557b2b (the ink epic #246 complete: every skin is drawn by
three.js, and a skin's stylesheet paints nothing). How to work is [developing-with-agents.md](developing-with-agents.md);
this page is what to build and in what order. Every issue is self-contained: it names what to read first, what to
build, its acceptance criteria and its tests._

## 0. Before the first line of code

1. `GEMINI.md`, then [developing-with-agents.md](developing-with-agents.md) (branches, the checkpoint ritual, the
   handover note, stop conditions, lanes, review).
2. Your issue, then its epic. The epic's **Decisions** table and the register (#318) give the defaults you build on.
3. [testing-this-repo.md](testing-this-repo.md) for how the suite runs, and the plan or skin page your issue names.

```bash
pip install -e ".[dev]"             # an uninstalled checkout fails 73 subprocess tests (#297 fixes the message)
python -m playwright install chromium
python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow"
python -m pytest -q -m browser <the browser files you touched>
```

**Known noise, until the testing epic lands.** CI's ubuntu legs skip every browser test (the isolated `HOME` hides
Playwright's browsers: #296), so only `windows · python 3.14` runs them; run the browser files you touched locally,
twice, and paste the lines into the handover note. Fourteen terminal-output tests need `rich` installed. The Windows
3.14 job runs serially and sits near its 25-minute cap (#227, #311).

## 1. The non-negotiables

| Rule | Enforced by |
|---|---|
| Never skip, xfail, deselect, quarantine or loosen a test; wait on conditions, never flat timeouts | review R2; the ratchet in #306 |
| The render contract: an idle desk makes zero DOM mutations and zero WebGL frames; DOM writes only through `attr`/`text`/`setData`/`setClass` | the idle tests in each `tests/test_fleet_ink_*.py` |
| A skin module draws from classes the page already sets, writes nothing to the page, has no colour literals; marks are drawn, never faded; reduced motion shows the end state | `tests/test_fleet_ink.py`, the per-skin tests, [desk-ink.md](desk-ink.md) |
| A skin's `skin.css` holds only tokens, layout and typography | `tests/test_fleet_skin_guard.py` |
| Text reads at 4.5:1 and marks at 3:1 on every paper (`theme.check`) | `tests/test_fleet_skins.py`, the HIG guards #340 and #341 |
| No `innerHTML`, no CDN, no build step, no new dependency; three.js r160 stays vendored and pinned | `tests/test_fleet_serve.py`, review |
| The payload budgets: the page under 200 KiB gzipped; the four always-fetched ink modules under `INK_BUDGET` (raised once, to 44 KiB, by #331 on the register's answer); effect code in the lazily fetched `ink/fx.js` under 8 KiB (#370) | `tests/test_fleet_serve.py`, `tests/test_fleet_ink.py` |
| Subprocesses go through `agentdata/proc.py`; a refusal is exit 2 with a hint and a row in `docs/refusals.md` | `tests/test_proc.py`, `tests/test_refusals.py` |
| A failure seen on a real machine becomes `tests/regressions/test_<yyyymmdd>_<host>_<short>.py`, with `Symptom` and the issue URL | `tests/regressions/test_convention.py` |
| Conventional Commits; one issue, one branch; no version or CHANGELOG change | review R7; `tests/test_update.py` |
| The merge train (decision 7): a builder pushes its branch and posts a CAR line, opens no PR; the conductor merges cars `--no-ff` into `train/<N>` and opens one PR with every `Closes #n`, merged with a merge commit | the conductor; [developing-with-agents.md](developing-with-agents.md) §2 |
| `ci` and `relay` are frozen lanes: edit them only with the operator's approval linked in the PR | review R1; #324 once it lands |

## 2. Decisions already made

- **Three.js is the one renderer**; the plain fallback (`body.ink-off`) is the only CSS look (#246, done).
- **Gemini builds every card; Opus 5.5 reviews every PR** and continues a slice on the same branch when its builder
  runs out of context. A card's `review:low` or `review:medium` label sets the reviewer's effort.
- **The Windows 3.14 waiver was for K (#275) alone.** Every pytest job is required in practice; a merge over red
  happens only at the operator's word for that PR, naming the check and linking a flake issue (#316).
- **The theme flash is fixed at its causes first** (#344 to #349: the served HTML carries no theme, the page
  repaints the previous theme's cached snapshot, the settings page wipes its tokens, a restored desk replays its
  stream), **and the native desktop window is still built and measured** (#353, #354), because the operator gave
  permission for it. The measurement decides whether it becomes the default.
- **Effects may animate the page itself**, through one sanctioned, transient writer in the ink layer (#374). Nothing
  is written at rest, and nothing animates under reduced motion.
- **The merge train replaces one PR per issue** (decision 7, [#429](https://github.com/agentchieflou/this-next-please/issues/429#issuecomment-5823490430)): a red car is pulled out and the rest ship.
- **Operator decisions live in one register, #318.** A reversible row runs on its default until answered; an
  irreversible row waits.

## 3. The epics

| Epic | Cards | What it delivers |
|---|---|---|
| #288 Testing structure | #296 to #317 | Linux runs the browser tier; one owner for the desk's process state (#227); a shared browser harness; condition waits and a ratchet; Windows in 20-minute shards |
| #289 Agent relay | #318 to #324 | This brief, the protocol, `GEMINI.md`, the PR template (all in PR #287); the decisions register; lanes as data and a PR check |
| #290 HIG pass on the ink skins | #325 to #343 | One `css()` and a legible `--muted`; chips and status text at 4.5:1; marks kept off words and inside panes; one state grammar; the waiting pane loudest; two automated HIG guards |
| #291 Theme switches that stick | #344 to #356 | The right skin on the first frame in every page and host; a measured WebView2 desktop window with a go/no-go gate |
| #292 Models are chosen, not typed | #357 to #369 | The settings page scrolls again; a model catalogue from the installed Copilot CLI; one provider-grouped pill picker on every surface |
| #293 Ink effects and HTML-aware ink | #370 to #384 | A lazily fetched `fx.js`; cues when things arrive and leave; the page animated in place; voxel blasts, hits and easter eggs; farmstead harvests and easter eggs; line, glyph and pointer awareness; the HTML-in-Canvas spike |
| #294 Every palette gets a look | #385 to #400 | The Playbook skin on the Browns palette (a coach's chalkboard in X's and O's), Browns back in the picker at once (#393), Phosphor, Circuit board, a lamplight notebook |
| #295 The fleet map | #401 to #415 | `/api/map`; the fleet as an accessible tree; a three.js scene of projects, branches per agent, worktrees, agents and the network, live from the stream |

## 4. The waves

A card opens only when every card it depends on has merged. A wave is the set of cards whose dependencies are all in
earlier waves; the operator sets how many builders run at once (register, relay epic). **Start the pilot first.**

**Pilot.** #359 (the fake `copilot` answers `--version` and `help config`) runs alone, end to end: a Gemini build, the
handover note, an Opus review, the operator's merge. Only then do the other wave-1 cards open.

| Wave | Cards | Gate before the next wave |
|---|---|---|
| 0 | #319 #320 #321 #322 #323 (PR #287) | PR #287 merged; the operator has read the register (#318) |
| 1 | #296 #297 #298 #314 #316 #317 · #324 · #325 #326 #330 #331 #333 #336 #337 #338 · #344 #345 #350 · #357 #358 #359 · #385 · #401 #402 | CI green with the ubuntu legs running the browser tier (#296) |
| 2 | #299 #309 · #327 #332 · #346 #347 #349 #352 · #360 · #370 #380 #384 · #386 · #403 #405 | The desk harness (#299) on `main` |
| 3 | #300 #301 #302 #307 #308 #310 · #328 · #348 #351 · #361 #362 #363 · #371 · #387 #393 · #407 #408 | Browns is back in the picker (#393) |
| 4 | #303 #311 #312 · #329 #339 #342 · #353 #356 · #364 #365 #366 #367 · #372 · #388 #389 #396 #399 · #409 | Windows runs in 20-minute shards (#311) |
| 5 | #304 #315 · #334 · #354 (laptop) · #368 · #373 #374 · #390 #394 #397 #398 · #404 #406 #410 | The go/no-go on the desktop window (#354) |
| 6 | #305 · #335 #340 · #355 · #369 (laptop) · #375 #377 · #391 #395 · #411 #413 #414 | HIG guard 1 (#340) green on every skin |
| 7 | #306 · #341 · #376 #378 #381 · #392 · #412 | The ratchet (#306) on `main` |
| 8 | #313 · #343 (laptop) · #379 #382 · #400 (laptop) · #415 (laptop) | The laptop sittings |
| 9 | #383 (laptop) | Every epic's definition of done |

**Laptop sittings.** The operator's cards batch into three sittings: after wave 5 (#354, the desktop window against
Edge `--app`); after wave 6-8 (#369 models, #343 HIG, #400 Playbook); after wave 9 (#415 map, #383 effects).

## 5. Shared files: who merges first

Cards in the same wave that edit the same hotspot merge in this order; each later PR merges `origin/main` and re-runs
its named tests before review.

- **Ink core** (`ink/layer.js`, `ink/ink.js`, the budget): #331 (raises `INK_BUDGET` to 44 KiB) → #385 → #338 → #345
  → #370 → #386 → #387 → #388. One ink-core PR is open at a time.
- **`static/app.css`, wave 1**: #357 (settings scroll, the smallest) → #325 → #326 → #330 → #337.
- **`serve.py`**: wave 1 #345 → #350 → #401; wave 2 #346 → #349 → #403 → #405; wave 3 #348 → #351 → #361 → #362 →
  #328 → #393.
- **`tests/conftest.py`** (frozen `ci` lane): #296 → #297 → #298 → #317 → #299 → #309 → #308 → #310.
- **`skins.py` / `theme.py`**: #325 → #345 → #327 → #346 → #328 → #393 → #329 → #339 → #342 → #389 → #396 → #399.
- **`.github/workflows/tests.yml`**: #311 → #312 → #313.

## 6. When a builder runs out

The pass-back rules are [developing-with-agents.md §9](developing-with-agents.md): `ready-for-review`, `stuck`, three
hours without a push, the same job red twice, or a session that ended without a Status. The Opus reviewer continues
on the same branch from the handover note's **Next**, then reviews its own commits at medium effort.

## 7. Preamble for Jules (it reads only AGENTS.md)

Paste this at the top of every Jules task:

> You are a developer of this repository, not Luna: do not run the session skills AGENTS.md names. Read `GEMINI.md`,
> `docs/developing-with-agents.md` and `docs/brief-post-ink-epics.md`, then build issue #<n> only, on branch
> `gemini/<n>-<slug>`, as a draft PR whose body starts `Closes #<n>` and carries the handover note from
> `.github/pull_request_template.md`. Never merge, never skip or loosen a test, never change the version.
