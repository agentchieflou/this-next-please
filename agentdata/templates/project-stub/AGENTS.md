# Project: <PROJECT_KEY>
Canonical rules: installed `this-next-please` skills. Do not restate them here.
First action every session: skill `session-bootstrap`.
State: `.agent/state.json` (machine-owned; only `state-update` writes it).

## Project facts (fill in; skills read these keys; `ad-setup --project .` fills what it knows)
- jira_project: <RDSD>
- jira_url: <https://jira.example.com>   # the browse/ base the fleet tile links a ticket to
- jira_board_id: <board id>                 # ad-jira sprints --board
- ticket_policy: optional                   # optional: a request may run without a ticket (the router says so in one line); required: every request needs a key or `jira-create`
- jira_issue_type: Task                     # ad-jira create: the default issue type
- jira_components: <Component A, Component B>   # ad-jira create: component names, comma-separated
- jira_labels: <label-a, label-b>           # ad-jira create: labels, comma-separated
- jira_fields: <Primary Domain=Data; Team=BI Platform>   # ad-jira create: any field by name, `;`-separated; resolved against Jira at run time
- jira_parent: <RDSD-100>                   # ad-jira create: the epic / parent every new ticket hangs under
- jira_assignee: <me>                       # ad-jira create: me, an accountId (Cloud) or a username (DC); blank = unassigned
- jira_hist_table: <DB.JIRA_ISSUE_HISTORY>  # Teradata: PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS, STORY_POINTS
- jira_sprint_table: <DB.JIRA_SPRINT>
- env: <td_env_name>                        # ad-td --env
- hive_env: <hive_env_name>                 # ad-hive --env
- impala_env: <impala_env_name>             # ad-impala --env
- oracle_env: <oracle_env_name>             # ad-ora --env
- confluence_base: <https://confluence.example.com>   # the wiki base the tile links a page to
- confluence_space: <SPACE>
- bitbucket_repo: <project/repo>            # the tile's repo and open-PR links
- confluence_parent: <page id>
- te2_exe: C:/Tools/TabularEditor/TabularEditor.exe
- dscmd_exe: C:/Tools/DaxStudio/dscmd.exe
- pbip_path: <reports/Report.pbip>          # ad-pbip <cmd> <pbip-dir> defaults to its folder
- tmdl_path: <Model.SemanticModel/definition>   # folder that contains model.tmdl
- pbi_workspace: <Workspace Name>
- pbi_xmla: <powerbi://api.powerbi.com/v1.0/myorg/Workspace%20Name>   # percent-encoded; written by ad-setup
- pbi_model: <Model>
- ws_id: <workspace guid>
- ds_id: <dataset guid>
- deploy_roles: false
- pbi_custom_visuals: <unknown>             # what the tenant renders for this report's VIEWERS: allowed | certified-only | org-only (Fabric tenant settings "Allow visuals created using the Power BI SDK", "Add and use certified visuals only"). Unrecorded, ad-pbip check and ad-pbi publish pass nothing from a file or AppSource
- pbi_certified_visuals: deneb7E15AEF80B9E4D4F8E12924291ECE89A   # AppSource visuals whose Microsoft-certified badge was checked, by GUID, comma-separated; a certified-only tenant passes only these. Preset: Deneb, certified as of 2026-09
- pbi_org_visuals: <Deneb>                  # organizational-store visuals viewers can use, comma-separated (Desktop: Visualizations pane → … → Get more visuals → My organization)
- dpm_run_root: <\\share\dpm\runs\RUN-id>     # ad-dpm: one DPM run root (orchestrator.db + text_analysis/)
- dpm_runs_dir: <\\share\dpm\runs>            # ad-dpm --run-id / --latest picks under this folder
- dpm_artifact_dir: <artifacts/dpm>            # consumer's governed artifact directory, relative to this repo; ad-dpm writes only here
- dpm_binding: <dpm-binding.json>               # optional: names DPM uses differently (ad-dpm binding --write)
- content_understanding_endpoint: <https://<resource>.services.ai.azure.com>  # optional: Azure AI Content Understanding (ad-foundry, ad-dpm extract-fields --engine azure-content-understanding)
- content_understanding_analyzer: <analyzer-id>   # optional: the analyzer whose field schema the job uses
- content_understanding_auth: entra                # optional: entra (default) or key; the key itself lives in keyring, never here
- test_cmd: <pytest -q>                      # ad-test: blank = auto-detect the runner
- graph_min_coverage: <0.8>                 # ad-graph findings/guard: per-node coverage a change must clear
- graph_min_speedup: <1.10>                 # test-regress: speedup a change must clear to count
- skills_dir: <~/.copilot/skills>
- pae_host: <host>

## Definition of done
state.json updated · findings file in .agent/out/ · Confluence page · PR open · Jira "In Review".
