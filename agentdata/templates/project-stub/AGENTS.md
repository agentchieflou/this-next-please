# Project: <PROJECT_KEY>
Canonical rules: installed `this-next-please` skills. Do not restate them here.
First action every session: skill `session-bootstrap`.
State: `.agent/state.json` (machine-owned; only `state-update` writes it).

## Project facts (fill in; skills read these keys; `ad-setup --project .` fills what it knows)
- jira_project: <RDSD>
- jira_board_id: <board id>                 # ad-jira sprints --board
- jira_hist_table: <DB.JIRA_ISSUE_HISTORY>  # Teradata: PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS, STORY_POINTS
- jira_sprint_table: <DB.JIRA_SPRINT>
- env: <td_env_name>                        # ad-td --env
- hive_env: <hive_env_name>                 # ad-hive --env
- impala_env: <impala_env_name>             # ad-impala --env
- oracle_env: <oracle_env_name>             # ad-ora --env
- confluence_space: <SPACE>
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
- dpm_run_root: <\\share\dpm\runs\RUN-id>     # ad-dpm: one DPM run root (orchestrator.db + text_analysis/)
- dpm_runs_dir: <\\share\dpm\runs>            # ad-dpm --run-id / --latest picks under this folder
- dpm_artifact_dir: <artifacts/dpm>            # consumer's governed artifact directory, relative to this repo; ad-dpm writes only here
- dpm_binding: <dpm-binding.json>               # optional: names DPM uses differently (ad-dpm binding --write)
- graph_min_coverage: <0.8>                 # ad-graph findings/guard: per-node coverage a change must clear
- skills_dir: <~/.copilot/skills>
- pae_host: <host>

## Definition of done
state.json updated · findings file in .agent/out/ · Confluence page · PR open · Jira "In Review".
