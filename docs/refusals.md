# Refusals

Every place an `ad-*` command says no, what makes it say no, and the test that proves it.

A refusal is a feature: it is how this package keeps an agent from doing something the user would
have to undo. The value of the registry is that a refusal cannot quietly stop working — a rule
nobody tests is a rule that will be removed by the next person who finds it inconvenient.

`tests/test_refusals.py` reads this file: every row must name a test that exists, and the count of
refusal call sites in `agentdata/` is pinned, so a new one has to be added here deliberately.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | it worked |
| 1 | it failed for a reason outside our control (a tool exited non-zero, a file was missing) |
| 2 | **refused**, or a usage error: the caller asked for something we will not do |
| 3 | the data needed does not exist yet (no graph, no coverage) — run the command that makes it |

## The registry

| Area | Refuses when | Emits | Test |
|---|---|---|---|
| SQL guardrail | the statement is not read-only (DML/DDL, including inside a CTE, after a `;`, or behind a comment) | `error`, exit 2 | `test_refusals.py::test_dml_is_refused_however_it_is_hidden` |
| SQL guardrail | the text still holds an unexpanded `$env:X`, `%X%` or `${X}` | `error` naming the shell rule, exit 2 | `test_shell_argv.py::test_sql_check_refuses_an_unexpanded_variable` |
| State | the phase is not one of `PHASES` | `StateError` listing them | `test_refusals.py::test_an_unknown_phase_is_refused_and_the_message_lists_the_real_ones` |
| State | the key is not a known state or tool key | `StateError` listing the allowed keys | `test_refusals.py::test_an_unknown_state_key_is_refused` |
| Config | a value looks like a credential | `ConfigError`, nothing written | `test_refusals.py::test_a_token_looking_config_value_is_refused` |
| Confluence | the body is Markdown rather than storage format | `error` naming `ad-confluence html`, exit 2 | `test_proc.py::test_raw_refuses_to_post_markdown_to_confluence` |
| pncli | an argument cannot survive cmd.exe and there is no Node entry point | `refused: cmd_unsafe_argument` | `test_fakes.py::test_a_multiline_body_is_refused_through_a_cmd_shim` |
| pncli | the launcher is not on PATH, PATHEXT or the npm prefix | `ProcError not_found` naming the npm package | `test_fakes.py::test_a_missing_pncli_names_the_npm_package` |
| Graph approval | `ad-graph approve` has no terminal | exit 3, `hint`, nothing written | `test_graph_explain.py::test_approve_refuses_without_a_terminal_and_writes_nothing` |
| Graph guard | the graph is unapproved or stale | exit 1, hint naming `codebase-map` | `test_graph_guard.py::test_a_missing_approval_refuses_everything` |
| Graph guard | the changed node is not covered by tests | exit 1, hint naming `test-cover` | `test_graph_guard.py::test_editing_an_uncovered_function_is_refused_and_names_test_cover` |
| Graph guard | a changed line has never executed | exit 1, hint listing the lines | `test_graph_guard.py::test_changing_a_line_the_tests_never_run_is_refused_inside_a_covered_node` |
| Graph guard | a test was deleted, renamed or shrank | exit 1, "never remove or weaken a test" | `test_graph_guard.py::test_deleting_a_test_is_refused` |
| Graph guard | `--tests-only` and a non-test file is in the diff | exit 1 | `test_graph_guard.py::test_tests_only_refuses_a_source_file_in_the_same_diff` |
| Graph guard | `--allow` without a terminal | exit 3, nothing recorded | `test_graph_guard.py::test_allow_requires_a_terminal_and_records_nothing` |
| Graph guard | `--install-hook` over someone else's hook | exit 2, hint | `test_graph_guard.py::test_install_hook_never_overwrites_someone_elses_hook` |
| Graph export | the output path is outside `.agent/graph/` | exit 1 | `test_graph_query.py::test_query_commands_on_fixture` |
| Graph findings | an unknown `--kind` | exit 2, lists the kinds | `test_graph_findings.py::test_cli_rejects_an_unknown_kind` |
| Setup | no input on stdin and not `--non-interactive` | exit 2, hint naming `--set` | `test_contract.py::test_no_arguments_is_help_or_usage_never_a_crash` |
| Help | an unknown flag rather than a command name | exit 2 | `test_contract.py::test_an_unknown_flag_is_a_usage_error_not_a_crash` |
| Update | the skills half would delete a folder that is not ours | left alone, reported | `test_update_windows.py::test_only_our_own_skills_are_removed` |
| Update | the CLI half is asked for through the `ad-update` launcher on Windows | `refused`, exit 2, naming the module form | `test_lifecycle.py::test_the_install_and_update_lifecycle` |
| Fleet | a folder has no `AGENTS.md` or `.agent/state.json` | `refused`, exit 2, naming `ad-setup --project .` | `test_fleet.py::test_a_folder_that_is_not_a_project_is_refused` |
| Fleet | a repository already has a live agent | `refused`, exit 2, naming the running ticket | `test_fleet.py::test_a_second_start_is_refused_while_an_agent_is_live` |
| Fleet | the repository is mid-ticket in a non-terminal phase | `refused`, exit 2, naming the ticket and phase | `test_fleet.py::test_starting_a_different_ticket_mid_ticket_is_refused_without_force` |
| Fleet | configuration asks for `--allow-all` or `--yolo` | `refused`, exit 2, naming the pattern | `test_fleet.py::test_a_config_that_asks_for_blanket_permission_is_refused_by_name` |
| DPM | the artifact directory is outside the governed tree | `error`, exit 2 | `test_dpm.py::test_convert_refuses_paths_outside_governed_dir` |
| Install | a hint would tell a project repo to `pip install -e` | refused at the source | `test_install.py::test_runtime_hints_never_tell_a_project_repo_to_pip_install_dash_e` |

## Debugging a swallowed exception

Most `except Exception` handlers here are right — a missing optional tool, a console API that is not
present, a config file someone deleted. When one swallows something unexpected the symptom arrives
later as an empty result, so:

```bash
AGENTDATA_DEBUG=1 ad-doctor            # appends tracebacks to .agent/out/agentdata-debug.log
```

`agentdata/log.py:debug_exc()` costs nothing when the flag is unset and never raises — a logger that
can fail inside an exception handler is a new bug in the same place.
