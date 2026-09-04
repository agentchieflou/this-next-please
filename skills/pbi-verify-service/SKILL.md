---
name: pbi-verify-service
description: "Use to verify deployed Power BI semantic model measures over XMLA and assert Desktop-vs-service numerical parity."
---
# Deployed Model and Service Parity Verification

Verify that every measure used by report visuals computes correctly on the service, and compare numbers against local Power BI Desktop.

Inputs: `pbip` path, `workspace` (name or ID), `model` name, optional `--pid <pid>`.

## Workflow

1. **Run service verification and parity check**:
   `ad-pbi verify --pbip <pbip_dir> --workspace <workspace> --model <model> [--pid <pid>]`
   - Scans the PBIR report to identify all measures referenced across visual fields.
   - Evaluates each measure over the service XMLA endpoint.
   - If Desktop is running (or `--pid` provided), evaluates the exact same measures against `localhost:<port>`.
   - Diffs the result sets and checks for numerical parity.

2. **Inspect parity output**:
   - `parity: ok`: Numbers match across all evaluated measures.
   - `parity: mismatch`: One or more measures differ between Desktop and service.

3. **Handle mismatches**:
   - Review the `measures` table showing differing rows between service and Desktop.
   - Common causes:
     1. Service data refresh is older or newer than Desktop imported data.
     2. Row-Level Security (RLS) or object permissions active on the service.
     3. Power Query parameters differ between service and Desktop environments.
   - If unexpected discrepancy: invoke `friction-log` with the comparison table. STOP.

4. **Completion**:
   - All measures verified → `state-update` `phase=done`. Hand off → `router` (or `uat-report-visual`).
