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
| Fleet | a repository already has a live agent | `refused: live_agent`, exit 2, naming the running ticket | `test_fleet.py::test_a_second_start_is_refused_while_an_agent_is_live` |
| Fleet | `ad-fleet stop` on a console the fleet opened (#189) | `refused: console_window`, exit 2 — close that window; the fleet opened it and does not close it | `test_fleet_console.py::test_the_console_the_fleet_opens_takes_the_lock_and_the_tile_reads_it_live` |
| Fleet | `ad-fleet stop` / `reset`, the page's Stop / Reset, or `start --force` on an adopted session, whether or not its pid is known (#487) | `refused: external_session`, exit 2 — close it in its own window, or `ad-fleet release <repo>` to stop following it; nothing is signalled | `test_fleet_desk_actions.py::test_stop_and_reset_never_end_a_chat_the_fleet_did_not_start` |
| Fleet | `ad-fleet start` (new, ticket or resume), `restart` or `console` over an adopted session (#487) | `refused: external_session`, exit 2 — the same hint, which names neither `send` nor `stop` | `test_fleet_desk_actions.py::test_stop_and_reset_never_end_a_chat_the_fleet_did_not_start` |
| Fleet | any start (new, ticket, resume or bare) or console where a Copilot the fleet did not start is named by pid in the checkout; the fleet's own pid and session never count (#487) | `refused: foreign_session`, exit 2, in the adopt strip's words — close that window, or `ad-fleet adopt <repo>`; nothing launched | `test_fleet_desk_actions.py::test_every_start_refuses_beside_a_chat_it_can_name` |
| Fleet | `ad-fleet fresh` / *start fresh* while the operator's own chat may still be open but has no pid: an adopted lock still live, or a session file written within `fleet.console.idle_s` (#488, SESS-D2) | `refused: chat_open`, exit 2 (409 with `second_press: true`) — close it there, then `ad-fleet fresh <repo> --closed`; nothing released or launched | `test_fleet_fresh.py::test_a_second_press_releases_and_starts_but_never_over_a_named_pid` |
| Fleet | `ad-fleet fresh` while the agent's question is open, its phase is `blocked`, or it needs you (#488) | `refused: needs_you`, exit 2 — answer it first; a fresh session would bury the question | `test_fleet_fresh.py::test_every_fresh_verdict` |
| Fleet | `ad-fleet fresh` while a fleet turn is running (#488, SESS-D5) | `refused: mid_turn`, exit 2 — a session changes between turns; press again when it ends, nothing is queued | `test_fleet_fresh.py::test_every_fresh_verdict` |
| Fleet | `ad-fleet fresh` with no repository and no `--all` (#508) | `refused: no_repo`, exit 2 — *name a repo, or pass --all* (`stop`'s words), so a typo never sweeps the fleet | `test_fleet_fresh.py::test_the_cli_needs_a_confirm_and_refuses_a_bare_fresh_and_a_fleet_wide_closed` |
| Fleet | `ad-fleet fresh --all --closed` (#508) | `refused: closed_is_per_pane`, exit 2 — close your own chat, then `ad-fleet fresh <repo> --closed`; a fresh day never acts on your own chat | `test_fleet_fresh.py::test_the_cli_needs_a_confirm_and_refuses_a_bare_fresh_and_a_fleet_wide_closed` |
| Fleet | `ad-fleet fresh --all` without `--confirm`, `POST /api/fresh {all: true}` without `repos`, or `fresh.run_all` with nothing ticked (#508) | `refused: preview_first`, exit 2 / 409 — the CLI prints the plan and *confirm with `--confirm <plan_id>`*; the API says *preview first: {all: true, dry_run: true}, then post the repos you ticked*. Nothing launches | `test_fleet_fresh.py::test_the_api_answers_what_the_cli_answers_for_a_fresh_day` |
| Fleet | `ad-fleet fresh --all --confirm <plan_id>` when a plan taken now has another id (#508) | `refused: plan_changed`, exit 2, with the new plan's table and id; nothing launches | `test_fleet_fresh.py::test_the_cli_needs_a_confirm_and_refuses_a_bare_fresh_and_a_fleet_wide_closed` |
| Fleet | `--confirm` or `--keyless` on a one-repository `ad-fleet fresh` (#508) | `refused: not_a_sweep`, exit 2 — they belong to a fresh day: `--all`, or two or more repositories | `test_fleet_fresh.py` |
| Fleet | a fresh day's row for the operator's own chat: adopted or external, live or gone quiet (#508) | `skipped: your_own_chat` — a sweep never acts on it; start fresh on its pane (Alt+N) when you are done with it. `adopt.release` is never reached | `test_fleet_fresh.py::test_the_sweep_never_touches_the_operators_own_chat` |
| Fleet | a fresh day's row whose session began today and has its session id (#508) | `skipped: fresh_today` — already on today's session (began HH:MM). A fresh start today that died before its id is `now` again | `test_fleet_fresh.py::test_a_fresh_day_is_idempotent_within_the_day` |
| Fleet | a fresh day's `now` row with no ticket in progress, or a finished one (#508, DAY-D1) | `keyless`, unticked — a keyless session runs session-bootstrap, then router; `--keyless` (or *tick every idle agent*) ticks it | `test_fleet_fresh.py::test_a_fresh_day_plans_every_agent_and_launches_nothing` |
| Fleet | `ad-fleet fresh` on a console the fleet opened (#488) | `refused: console_window`, exit 2 — close that window; `ad-fleet console <repo> --new` opens a fresh one | `test_fleet_fresh.py::test_every_fresh_verdict` |
| Fleet | `ad-fleet fresh` beside a Copilot named by pid, adopted or not; `--closed` never overrides it (#488, SESS-D3) | `refused: foreign_session`, exit 2 — close it in its own window; the fleet does not end it | `test_fleet_fresh.py::test_every_fresh_verdict` |
| Fleet | `ad-fleet stop <repo>` is refused (#487) | exit 2 with `error`, `hint` and `code`; `--all` keeps one row per repo, with a `hint` column | `test_fleet_desk_actions.py::test_a_refused_stop_exits_2_with_its_hint` |
| Fleet | `ad-fleet console` on a machine with no terminal emulator (#189) | `refused: no_console_host`, exit 2 — the console is for the laptop; `fleet.console.host: fake` runs it with no window | `test_fleet_console.py::test_a_machine_with_no_terminal_refuses_to_open_a_console` |
| Fleet | `ad-fleet say` where no agent is live (#190) | `refused: no_agent`, exit 2 — `ad-fleet console <repo>` opens one | `test_fleet_console.py::test_say_is_refused_where_there_is_no_console_to_type_into` |
| Fleet | `ad-fleet say` on a session the fleet started headless (#190) | `refused: not_a_console`, exit 2 — `ad-fleet send` continues it the way it was started | `test_fleet_console.py::test_say_is_refused_where_there_is_no_console_to_type_into` |
| Fleet | `ad-fleet say` on an adopted console no process was named for (#190) | `refused: external_session`, exit 2 — type in that window; `ad-fleet release` hands it back | `test_fleet_console.py::test_say_is_refused_where_there_is_no_console_to_type_into` |
| Fleet | the console helper cannot attach to the window, or it takes the attach and not the line (#190) | `refused: console_unreachable`, exit 2 — the helper's own sentence and Win32 number, verbatim | `test_fleet_console.py::test_a_helper_failure_reaches_the_tile_in_the_helpers_own_words` |
| Fleet | `ad-fleet say-into` / `focus-console` where there is no Win32 console API (#190) | `refused: unsupported_host`, exit 2 — the console is for the laptop | `test_fleet_console.py::test_on_posix_the_helper_says_the_console_is_a_windows_thing` |
| Fleet | `ad-fleet say` with nothing but whitespace or newlines to type (#190) | `refused: empty_message`, exit 2 — a reply with newlines would be several commands to a console | `test_fleet_console.py::test_one_line_is_one_line_whatever_was_pasted_into_the_box` |
| Fleet | the repository is mid-ticket in a non-terminal phase | `refused: mid_ticket`, exit 2, naming the ticket and phase | `test_fleet.py::test_starting_a_different_ticket_mid_ticket_is_refused_without_force` |
| Fleet | `ad-fleet start <repo> <text>`, `POST /api/start`, or the page's Start with text in the reply box that `board.KEY` does not match (as typed or in capitals), on any pane (#509) | `refused: not_a_ticket`, exit 2 — *{text} is not a ticket key*; type a key such as RDSD-123, or empty the box and press Start fresh; Send sends text to the agent. Checked before the ticket, so nothing launches | `test_fleet_desk_switcher.py::test_start_refuses_text_that_is_not_a_ticket_key` |
| Fleet | ticket project does not match repository's declared jira_project | `refused: cross_project`, exit 2, naming both projects | `test_fleet.py::test_cross_project_ticket_is_refused` |
| Fleet | ticket is in a Done statusCategory on the board | `refused: ticket_done`, exit 2, naming the status | `test_fleet.py::test_done_ticket_is_refused` |
| Fleet | named repository is not registered in the fleet | `refused: wrong_repo`, exit 2, listing registered | `test_fleet.py::test_an_unknown_repo_names_the_ones_that_exist` |
| Fleet | configuration asks for `--allow-all` or `--yolo` | `refused`, exit 2, naming the pattern | `test_fleet.py::test_a_config_that_asks_for_blanket_permission_is_refused_by_name` |
| Handoff | a brief is empty, or past `BRIEF_CAP` | `refused: brief_empty` / `brief_too_long`, exit 2; nothing started | `test_fleet_handoff_pickup.py::test_an_empty_or_enormous_brief_is_refused_with_a_code` |
| Handoff | `--brief` and `--brief-file` both given | `refused: brief_ambiguous`, exit 2 | `test_fleet_handoff_pickup.py::test_a_start_with_a_brief_writes_it_then_asks_ad_state_then_starts` |
| Handoff | a scope path is `.agent/out/` or credential-shaped | `refused: scope_refused`, exit 2, naming the path | `test_fleet_handoff_scope.py::test_the_agents_own_output_and_anything_credential_shaped_are_refused` |
| Handoff | a scope or resolve names an unregistered repository | `refused: wrong_repo`, exit 2 | `test_fleet_handoff_scope.py::test_an_unregistered_repo_is_refused_with_a_code` |
| Handoff | an uploaded copy is over `fleet.attach.max_mb` | `refused`, exit 2, naming the cap and the alternative | `test_fleet_handoff_scope.py::test_attach_bytes_lands_in_agent_in_and_is_capped` |
| Handoff | a shell posts a path in no registered checkout | `refused: wrong_repo`, naming `ad-fleet repo add` | `test_fleet_handoff_scope.py::test_a_path_outside_every_checkout_is_refused_with_its_code` |
| Handoff | a shell posts paths of a checkout other than the selected tile | `refused: scope_wrong_repo`, naming the owner | `test_fleet_handoff_scope.py::test_files_of_another_checkout_than_the_selected_tile_are_refused_by_name` |
| Ask | `ad-state answer` names an id that is not open | `refused`, exit 2, listing the open ids | `test_fleet_handoff_ask.py::test_ad_state_ask_and_answer_round_trip_from_a_terminal` |
| Page loads | `POST /api/load` with a known field it cannot take: a bad `page`, `from` or `how`, a duration outside 0-600000 ms, an `origin_ms` more than 24 h off, a `ua` over 200 characters, a bad skin word or shell (#350) | `refused: load_shape`, 409 with `error` and `hint`; nothing written | `test_fleet_loads.py::test_a_load_of_the_wrong_shape_is_refused_as_load_shape` |
| Desktop window | `python ide/desktop/fleet_window.py` where pywebview cannot be imported (#353: the spike, outside the wheel) | one `hint:` line naming `pip install pywebview`, exit 2; no desk started, no window | `test_fleet_shells.py::test_the_desktop_window_without_pywebview_says_how_to_get_it` |
| Settings page | a key outside the enumerated `settings.EDITABLE` table | `refused: unknown_key`, 409, nothing written | `test_fleet_settings_api.py::test_a_key_outside_the_table_is_refused_and_nothing_is_written` |
| Settings page | a value the key's type cannot take, including an empty number | `refused: bad_type`, 409; the config file is byte-identical | `test_fleet_settings_api.py::test_a_wrong_value_is_refused_rather_than_coerced` |
| Settings page | a model or effort carrying whitespace or a leading dash, which would become a second flag | `refused: bad_model`, 409, nothing written | `test_fleet_settings_api.py::test_a_model_that_would_become_a_second_flag_is_refused` |
| Settings page | a per-repo model with no repository named | `refused: no_repo`, 409 | `test_fleet_settings_api.py::test_a_repo_that_is_not_named_is_refused` |
| Fleet CLI | `ad-fleet model` with a value that would become a second flag | `refused: bad_model`, exit 2, nothing written | `test_fleet_model_cli.py::test_a_model_that_would_become_a_second_flag_is_refused_at_the_terminal` |
| Settings page | a number outside the bounds its key declares, e.g. a tier width (#235) | `refused: out_of_range`, 409, with why the bound is there in the hint; the config file is byte-identical | `test_fleet_tiers.py::test_a_value_outside_its_bounds_is_refused_with_a_hint` |
| Settings page | tier widths that do not go together: *compact from* under the rail + 64px, or *full from* under *compact from* + 80px (#235) | `refused: bad_tiers`, 409, the hint naming the value that would fit; the config file is byte-identical | `test_fleet_tiers.py::test_boundaries_that_do_not_go_together_are_refused_with_the_fix` |
| Desk | `refresh` pressed twice inside two seconds on one checkout | `refused: refresh_busy`, 409; it re-reads what the tick reads, so the second press has nothing new to tell | `test_fleet_column.py::test_refresh_is_free_and_refuses_a_second_press_inside_two_seconds` |
| Settings page | `fleet.budget_per_agent` set to a value that is not a whole number of premium requests | `refused: bad_type`, 409; the config file is byte-identical. Its old reader coerced this to `0.0`, which turns the cap OFF | `test_fleet_spend.py::test_the_settings_page_refuses_the_budget_it_cannot_read` |
| Desk | *Send* on an agent that is over `fleet.budget_per_agent` | `refused: budget_exceeded`, in the supervisor's own words; *Send anyway* is a second, deliberate press that spends one more turn | `test_fleet_spend.py::test_send_is_refused_over_budget_and_the_second_press_spends_one_more_turn` |
| Launch | `fleet.model` / `fleet.effort` is more than one argument | `LaunchError` before the argv is built | `test_fleet.py::test_a_model_value_that_would_become_a_second_flag_is_refused` |
| Approval gate | an operator denied the write | `refused: approval_denied`, exit 2, quoting the reason | `test_fleet_approval.py::test_ad_jira_transition_refuses_on_a_denial_and_never_posts` |
| Approval gate | `ad-jira create` inside a fleet, denied | `refused: approval_denied`, exit 2, nothing posted | `test_jira_create.py::test_the_gate_holds_the_post_and_a_denial_never_creates` |
| Jira create | a `--field` or `jira_fields` name Jira does not have, a pair without `=`, or no project | `ok: false`, exit 2, the `available` names / the `jira_project` hint; nothing posted | `test_jira_create.py::test_an_unknown_field_is_refused_with_the_nearest_names_and_no_post` |
| Jira create | a value the field's type cannot take, or `me` with nobody signed in | `CreateError` before the POST | `test_jira_create.py::test_refusals_happen_before_anything_is_sent` |
| XMLA sign-in | `powerbi.auth.mode` is not `token` or `interactive` | `ConfigError` listing both | `test_pbi_auth.py::test_env_overrides_win_and_a_typo_is_refused_not_defaulted` |
| XMLA sign-in | the Azure CLI is signed out and auto-login is off (`AGENTDATA_AZ_LOGIN=0`, `powerbi.auth.auto_login: false`) | `not_signed_in`, exit 1, naming `ad-pbi auth`; no browser opened | `test_pbi_auth.py::test_ensure_token_with_auto_login_off_reports_instead_of_opening_a_browser` |
| XMLA sign-in | `az` cannot be found | `az_not_found` naming the install path | `test_pbi_auth.py::test_a_missing_az_is_a_named_refusal_with_the_install_path` |
| DAX | `ad-pbi dax` given text that is not a query, or both/neither of `--file` and `--query` | `ok: false`, exit 2 | `test_pbi_auth.py::test_ad_pbi_dax_refuses_a_query_that_is_not_a_query` |
| Approval gate | nobody answered within `fleet.approval_timeout` | `refused: approval_timeout`, exit 2, naming `ad-fleet approve <id>` | `test_fleet_approval.py::test_a_timeout_says_how_to_release_it_and_that_re_running_is_safe` |
| Approval gate | the request could not be recorded, so it fails closed | `refused: approval_unavailable`, exit 2, nothing sent | `test_fleet_approval.py::test_the_gate_fails_closed_when_it_cannot_record_the_request` |
| Approval gate | a denial carries no reason, or an approval is answered twice | `ApprovalError`, exit 2 | `test_fleet_approval.py::test_a_denial_without_a_reason_is_refused` |
| DPM | the artifact directory is outside the governed tree | `error`, exit 2 | `test_dpm.py::test_convert_refuses_paths_outside_governed_dir` |
| DPM extract | the field schema is malformed (no fields, a duplicate name, a non-list) | `DpmError`, exit 2, naming the defect | `test_dpm_extract.py::test_a_broken_schema_is_refused_rather_than_quietly_finding_nothing` |
| DPM extract | a document's route is OCR | `needs_ocr_review`; the text is never read for values | `test_dpm_extract.py::test_an_ocr_document_is_flagged_and_never_extracted_from` |
| DPM extract | an engine option is misspelled | `DpmError` naming the accepted options | `test_content_understanding.py::test_a_misspelled_engine_option_refuses_instead_of_being_ignored` |
| Content Understanding | no endpoint in AGENTS.md, config or `--endpoint` | `ContentUnderstandingError` naming the fact and `ad-setup --only content_understanding` | `test_content_understanding.py::test_the_endpoint_refusal_names_the_two_ways_to_fix_it` |
| Content Understanding | no analyzer in AGENTS.md, config or `--analyzer` | `error`, exit 2, the two ways to supply one | `test_content_understanding.py::test_ad_foundry_analyze_with_no_analyzer_anywhere_refuses_with_exit_2` |
| Content Understanding | key auth with nothing in the keyring | `ContentUnderstandingError` before the SDK is imported | `test_content_understanding.py::test_key_auth_with_nothing_in_the_keyring_refuses_before_reaching_the_sdk` |
| Content Understanding | `ad-foundry analyze` gets both or neither of `--file` / `--url` | `error`, exit 2 | `test_content_understanding.py::test_exactly_one_input_or_it_refuses` |
| Content Understanding | the service fails or cannot be reached | `content_understanding_failed`, never `not_found` | `test_content_understanding.py::test_ad_foundry_reports_a_service_failure_as_a_refusal_not_a_traceback` |
| UAT SQL | a table name is not a plain identifier, or a literal could close its own quote | `ValueError`; nothing is quoted around it | `test_uat_jira_vs_source.py::test_a_table_name_that_is_not_an_identifier_is_refused_not_quoted` |
| Install | a hint would tell a project repo to `pip install -e` | refused at the source | `test_install.py::test_runtime_hints_never_tell_a_project_repo_to_pip_install_dash_e` |
| Power BI handoff | two Desktop documents are open and neither `--active` nor `--file` says which | `refused: ambiguous`, exit 2, the Z-ordered list and both flags | `test_pbip_handoff_cli.py::test_two_instances_and_no_flag_is_a_refusal_that_prints_both_and_both_flags` |
| Power BI handoff | `--file <name>` matches no open document | `refused: no_match`, exit 2, listing what is open | `test_pbip_handoff_cli.py::test_a_file_that_matches_nothing_lists_what_is_open` |
| Power BI handoff | nothing is open to hand over | `refused: no_instance`, exit 1, naming `ad-pbip launch` | `test_pbip_handoff_cli.py::test_nothing_open_is_a_refusal_with_nothing_to_hand_off` |
| Power BI handoff | the document has no Analysis Services port yet | `refused: no_port`, exit 1, "wait and run it again" | `test_handoff_transports.py::test_a_document_whose_port_file_is_missing_refuses_instead_of_guessing` |
| Power BI handoff | `--active` on Windows and `user32.EnumWindows` did not answer | `refused: no_zorder`, exit 2, naming `--file` | `test_handoff_transports.py::test_active_refuses_on_windows_when_enumwindows_did_not_answer` |
| Power BI handoff | the ribbon or TE2 click resolves no project, so the cwd is not the user's | `refused: no_project`, exit 2, naming `ad-setup --project` | `test_external_tool_agnostic.py::test_handoff_refuses_rather_than_writing_into_whatever_cwd_it_was_launched_from` |
| Power BI handoff | `--active`/`--file` mixed with `--server`/`--database` | `error`, exit 2 | `test_pbip_handoff_cli.py::test_the_two_directions_cannot_be_mixed` |
| Power BI handoff | `--database` without `--server` | `error`, exit 2 | `test_pbip_handoff_cli.py::test_a_database_with_no_server_is_a_refusal` |
| Power BI ribbon | no bare `python`/`py` on the user's PATH reaches agentdata from a fresh `cmd.exe` | `refused: per_user_launcher`, exit 2, naming `--launcher`; nothing packaged | `test_external_tool_agnostic.py::test_a_venv_python_is_refused_rather_than_shipped_to_it` |
| Power BI ribbon | the machine's External Tools folder does not exist | refused, hint naming `--package`; the folder is never created | `test_external_tool_agnostic.py::test_register_tool_never_creates_the_machine_folder` |
| Power BI ribbon | the folder exists and refuses the write | refused, hint naming `--package` and the `Copy-Item` line, never elevation | `test_external_tool_agnostic.py::test_register_tool_hint_points_at_the_package_not_at_elevation` |
| Power BI ribbon | a launcher name contains `%` | `ValueError` naming cmd.exe's expansion rule | `test_external_tool_agnostic.py::test_launcher_with_percent_is_refused` |
| Power BI TE2 | `CustomActions.json` does not parse | `refused`, exit 1, file left byte-for-byte alone | `test_pbip_handoff_cli.py::test_te2_refuses_a_malformed_actions_file_rather_than_rewriting_it` |
| Power BI TE2 | `--remove` without `--te2` | `error`, exit 2 | `test_pbip_handoff_cli.py::test_remove_without_te2_is_a_refusal` |
| Power BI TE2 | an unknown `te2_action` mode | `ValueError` naming `process` and `file` | `test_external_tool_agnostic.py::test_te2_unknown_mode_names_the_two` |

## Debugging a swallowed exception

Most `except Exception` handlers here are right — a missing optional tool, a console API that is not
present, a config file someone deleted. When one swallows something unexpected the symptom arrives
later as an empty result, so:

```bash
AGENTDATA_DEBUG=1 ad-doctor            # appends tracebacks to .agent/out/agentdata-debug.log
```

`agentdata/log.py:debug_exc()` costs nothing when the flag is unset and never raises — a logger that
can fail inside an exception handler is a new bug in the same place.
