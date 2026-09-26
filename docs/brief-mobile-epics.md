# Implementation brief: the mobile epics (#537 to #542)

_For the Gemini agents that build them, and the Opus 5.5 agents that review them and take over when a builder runs
out of context. Written 2026-09-26 against `main` at 0b9ec72, from [plan-mobile.md](plan-mobile.md), which is the
design record: what each card builds and why is there, with the contracts, the measured numbers and the decisions.
How to work is [developing-with-agents.md](developing-with-agents.md); this page is what to build and in what order.
Every card is self-contained: it names what to read first, what to build, its acceptance criteria and its tests._

## 0. Before the first line of code

1. `GEMINI.md`, then [developing-with-agents.md](developing-with-agents.md) (branches, the checkpoint ritual, the
   handover note, stop conditions, lanes, review).
2. Your card, then its epic. The epic's **Decisions** table and the register (#318, rows D69 to D93 in [its mobile comment](https://github.com/agentchieflou/this-next-please/issues/318#issuecomment-5849148701)) give the defaults
   you build on. [plan-mobile.md](plan-mobile.md) §The model holds the contracts every card on the laptop side keeps.
3. [testing-this-repo.md](testing-this-repo.md) for how the suite runs. For the tenant-side cards (the flows, the app,
   the lists), `mobile/README.md`, `mobile/flows/README.md` and `mobile/data/README.md` are the build sheets.

```bash
pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow"
python -m pytest -q tests/test_mobile_powerapp.py          # the mobile guard, plain tier
```

## 1. The non-negotiables

| Rule | Enforced by |
|---|---|
| Nothing is tunnelled: the bind, the token and the two tokenless routes are unchanged; the phone talks to Microsoft 365, never to the laptop | `tests/test_fleet_serve.py:88-98`; `tests/test_fleet_ide.py:106-113`; review |
| Fail closed: on any refusal no decision file is written, and the agent's own `approval_timeout` refuses the write | the refusal matrix in `tests/test_fleet_bridge.py` (#547) |
| Every outbox record is allow-listed and scrubbed: never the run token, a hostname, a path, `USERNAME` or `COMPUTERNAME`; `.agent/out` paths reduced to basenames | the scrubber test (#545); the leak test pattern of `tests/test_fleet_board_desk.py:138-169` |
| Every outbox record is immutable and uniquely named; the heartbeat is a dated file every 300 s | #546's tests; MOB-D11 |
| The fleet writes only under `~/.agentdata/fleet/` and the configured bridge folder, which has no default and is never a repository | `tests/test_fleet_e2e.py`; #545's folder test; MOB-D22 |
| The bridge spawns no subprocess and calls no host; every external file goes through `textio` | `HANDOFF.md:30-31`; review |
| Shells decide nothing: the Power App colours by `Role` and shows `State`, `Says` and every error verbatim; `/m` the same | `tests/test_fleet_shells.py:83-135`; `tests/test_mobile_powerapp.py` |
| The desk's render contract, no `innerHTML`, no CDN, no build step, no new dependency; the served payload under 200 KiB (decisions 18 and 19), the ink files under `INK_BUDGET` | `tests/test_fleet_serve.py`; `tests/test_fleet_ink.py`; `tests/test_fleet_components.py` |
| Decision 13: new browser checks fold into existing browser tests; CSS and serve rules get plain guards | review R2; `tests/test_suite_hygiene.py` |
| Never skip, xfail, deselect, quarantine or loosen a test; wait on conditions, never flat timeouts | review R2 |
| Conventional Commits; one issue, one branch; no `version` or `CHANGELOG` change; builders never merge | review R7; `tests/test_update.py`; AGENTS.md rules 8 and 9 |
| The merge train (decision 7): a builder pushes its branch and posts a CAR line on #429, opens no PR | [developing-with-agents.md](developing-with-agents.md) §2 |
| `ci` and `relay` are frozen lanes; the `mobile` lane is proposed and, until approved, `mobile/**` plus `tests/test_mobile_powerapp.py` is one exclusive tree by convention | `.github/agent-lanes.json`; MOB-D21 |
| A tenant-side card (the flows, the app, the lists, a phone or tablet pass) records what it saw in the docs it names, and a claim headless Chromium cannot prove reads *not yet measured* until #582 | review R6; `docs/windows-verification.md` §Mobile |

## 2. Decisions already made

- **The path** (plan §Pushback 1): laptop → OneDrive-synced folder → `FleetOutboxToLists` → five Microsoft Lists →
  the FleetAgent canvas app → `FleetDecide` → OneDrive inbox → the laptop applies. The ZPA relay of
  `reports/Intune phone access to agents.md` is later; Copilot CLI remote control is consoles only (#572); the
  Teams and Outlook loops are documented alternatives, not built.
- **Approval integrity first** (#543): a `digest` on every request, `via` and `by` on every decision, the approve
  comment delivered to the agent. It lands before any bridge code and helps the desk too.
- **Five lists, all-text columns** (MOB-D12): the workbook `mobile/data/FleetAgent.xlsx` is the "Create a list → From
  Excel" source and the Excel fallback, proven once in #562 or dropped.
- **One Tablet-format app** (MOB-D14, the one irreversible row): not a phone app and a tablet app.
- **The push says nothing** (plan §Pushback 7): a content-free `Message`, the ids in `Parameters`; `info`
  notifications are not relayed (MOB-D13).
- **The desk is made to fit, not replaced** (MOB-D17, MOB-D18): the stack at 640 px and under; `/m` last, after #523.
- **Operator decisions live in the register #318** (rows D69 to D93, in its mobile comment, mirror the epics' tables). A reversible row runs on
  its default until answered; MOB-D14 waits.

## 3. The epics

| Epic | Cards | What it delivers |
|---|---|---|
| #537 Approval integrity and the server's remote-ready seams | #543, #551, #559, #544 | a digest on every approval; a Host allow-list on every request; `GET /api/attention` and `GET /api/approval`; the fresh-window sidebar trap fixed |
| #538 The bridge: the laptop's outbox and inbox on OneDrive | #545 to #554 | `bridge.py`: the scrubber, the exporter, the two appliers, the notification channel and one process-wide sweep, the thread in `ad-fleet serve`, `ad-fleet mobile …`, the doctor rows, the events and `docs/fleet-mobile.md` |
| #539 Flows: outbox to lists, and the decision flow | #555 to #562 | the five lists; `FleetOutboxToLists`; `FleetDecide`; the exported solution; pushes and deep links on the real phone; the Excel fallback proven or dropped |
| #540 The Power App: FleetAgent on phone and tablet | #558 to #569 | the sources in Studio and back; the phone and tablet passes; approvals, replies and notifications end to end; accessibility and the theme; the guard extended |
| #541 The desk at phone and tablet widths | #573 to #581 | viewport foundations; coarse-pointer targets; the stack; the sidebar sheet; touch twins; `/map` and `/settings` by touch; background and bandwidth; ink off on small screens; `/m` |
| #542 Verification, docs and the IT ask | #570 to #572 | the runbook rows; the IT ask; the mobile sitting; the Copilot remote-control side track |

## 4. The waves

A card opens only when every card it depends on has merged. A wave is the set of cards whose dependencies are all in
earlier waves; the operator sets how many builders run at once. Tenant-side cards (F, P) run on the tenant and the
phone, not in CI, and record what they saw.

| Wave | Cards | Gate before the next wave |
|---|---|---|
| 0 | #543 · #544 · #545 | the seven digest tests and the scrubber's leak test green; the sidebar trap reproduced, then fixed |
| 1 | #546 · then #547 and #548 | the fail-closed matrix green; a matching decision releases `require()` |
| 2 | #549 · #550 · #551 | a transition reaches the outbox exactly once under two streams and the bridge; `S.build()` starts no thread |
| 3 | #552 · #553 · #554 · #559 · on the tenant: #555 · #556 · #557 · #558 | the dry run of `ad-fleet mobile apply` (#552) accepts a file `FleetDecide` wrote; every `mobile_*` code has its row |
| 4 | #560 · #561 · #562 · #563 to #569 · #570 · #571 · #572 | the phone and tablet passes recorded; the runbook rows written |
| desk (after #523 on `main`) | #573 → #574 → #575 → #576 → #577 → #578 · #579 (budget-neutral, may go earlier) · #580 · then #581 | the served payload reported on every CAR line; +0 browser tests |
| last | #582 | no runbook row reads *not yet measured*; `expire_s` and the heartbeat confirmed or changed with the number |

**Sittings.** One tenant sitting (#555, #556, #557), one phone sitting (#561, #563,
#565, #567), one tablet sitting (#564), and the mobile sitting (#582) that closes the runbook.

## 5. Shared files: who merges first

Cards in the same wave that edit the same hotspot merge in this order; each later car merges `origin/main` and re-runs
its named tests before review.

- **`serve.py`** (sequenced, one car per train): #544 → #549 → #551 → #559 → #579 →
  #581.
- **`approval.py`**: #543 alone; #546, #547 read it and add nothing.
- **`notify.py`**: #549 alone.
- **`cli_fleet.py`**: #550 → #552.
- **`setup/steps/fleet.py`**: #553 alone.
- **`static/app.css`, `static/app.js`, `static/index.html`** (`desk-page`): #544 → #573 → #574 →
  #575 → #576 → #577 → #578 → #579; all after #523.
- **`static/ink/ink.js`** (`ink-core`, exclusive): #580's gate rule alone, after #523.
- **`mobile/**`** (the proposed `mobile` lane, exclusive): #555 → #556 → #557 → #558 → the rest
  of F and P one at a time.
- **`docs/refusals.md`, `docs/desk-components.md`, `docs/testing-this-repo.md`** (`shared-docs`): rows only, beside
  their relatives.
- **`docs/fleet-mobile.md`**: #554 creates it; #571 adds §The IT ask; later cards append.

## 6. When a builder runs out

The pass-back rules are [developing-with-agents.md §9](developing-with-agents.md): `ready-for-review`, `stuck`, three
hours without a push, the same job red twice, or a session that ended without a Status. The Opus reviewer continues
on the same branch from the handover note's **Next**, then reviews its own commits at medium effort.

## 7. Preamble for Jules (it reads only AGENTS.md)

Paste this at the top of every Jules task:

> You are a developer of this repository, not Luna: do not run the session skills AGENTS.md names. Read `GEMINI.md`,
> `docs/developing-with-agents.md`, `docs/plan-mobile.md` and `docs/brief-mobile-epics.md`, then build issue #<n>
> only, on branch `gemini/<n>-<slug>`, and post the handover note from `.github/pull_request_template.md` as a comment
> on the issue. Never merge, never skip or loosen a test, never change the version.
