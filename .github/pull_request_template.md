Closes #

<!-- The handover note: rewrite it after every green step (docs/developing-with-agents.md §3-§4).
     The reviewer's verdict goes in a comment, not here. -->

<!-- handover:start -->
## Handover
| | |
|---|---|
| Issue / epic / wave / lane | #<n> · epic #<e> · wave <w> · lane `<lane>` |
| Branch · base | `gemini/<n>-<slug>` · `main` @ `<sha>` (last merge of main: `<sha>`) |
| Status | building / ready-for-review / stuck / blocked-on-operator / in-review / review-done |
| Held by | Gemini (<Antigravity 2.0, agy x.y.z or Jules>, <model>) or Opus 5.5 <low/medium> |
| Updated | <UTC time>, after commit `<sha>` |

### Acceptance criteria
- [ ] <criterion, copied from the issue> - `<command>` -> `<last line of output>` @ `<sha>`

### Done
1. <what> - `<sha>` - `<command>` -> `<result line>`

### Gates on the last commit
| Gate | Command | Result |
|---|---|---|
| named tests | python -m pytest -q <files> | |
| inner loop | python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow" | |
| browser files touched | python -m pytest -q -m browser <files> | |
| guards | python -m pytest -q tests/test_fleet_skin_guard.py tests/test_fleet_skins.py tests/test_fleet_components.py tests/test_entrypoints.py tests/test_suite_hygiene.py tests/test_agent_onramp.py | |
| shuffled | python -m pytest -q -p no:cacheprovider --shuffle-seed 1 <files> | |
| agent PR check | python .github/scripts/agent_pr_check.py --base origin/main | |

### Next
1. <file : symbol - what - the test that proves it>

### Files touched
- `<path>` - <why> [lane `<lane>`]

### Deviations from the issue
none

### Open questions
none

### Failures not caused by this branch
none

### Dead ends
none
<!-- handover:end -->
