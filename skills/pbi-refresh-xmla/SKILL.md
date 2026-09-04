---
name: pbi-refresh-xmla
description: "Use to refresh a deployed Power BI semantic model (full, table, or partition) through the XMLA endpoint and poll completion status."
---
# Refresh via TE2 script and REST polling

Refresh a deployed model and poll until completion.

1. **Determine scope**:
   `full` | `table:<name>` | `partition:<table>/<partition>`. Default: `full`.

2. **Execute refresh with polling**:
   `ad-pbi refresh --workspace <workspace> --model <model> [--scope <scope>] --wait`
   - Submits refresh via TOM `refresh.csx` script over XMLA.
   - Polls refresh history REST endpoint, emitting progress to stderr.
   - Outputs duration and completion status upon success.

3. **Handle failures**:
   - If refresh fails, `ad-pbi` extracts `error_code`, `table`, `partition`, `message`, and `hint` from `serviceExceptionJson`.
   - Invoke `friction-log` with the structured failure row. STOP.

4. **Verify parity**:
   - Exit 0 → `state-update` `phase=validating`. Hand off → `pbi-verify-service`.
