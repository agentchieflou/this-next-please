---
name: slurm-submit
description: "Use to run or schedule a batch job on the PAE Slurm cluster via sbatch (scrontab is disabled). Use when a query or script exceeds laptop limits, or the user says schedule, nightly, cluster, sbatch."
---
# Slurm submit

1. Write `.agent/slurm/<KEY>-<job>.sh`:
```bash
#!/bin/bash
#SBATCH --job-name=<KEY>-<job> --time=00:30:00 --mem=8G --cpus-per-task=2
#SBATCH --output=.agent/slurm/logs/%x-%j.out
set -euo pipefail
kinit -k -t "$KEYTAB" "$PRINCIPAL" 2>/dev/null || true   # creds resolved on cluster, never in chat
python <script> "$@"
```
2. Recurring: last line `sbatch --begin=now+1day "$0"` (self-resubmit). State this in the Confluence page.
3. `ssh <pae_host> "cd <repo> && sbatch .agent/slurm/<KEY>-<job>.sh"`. Capture job id.
4. `ssh <pae_host> "squeue -j <id> -h -o '%T'"` once. Do not poll. Tell the user the job id.
5. `state-update` with job id under `artifacts`. Return to caller.
