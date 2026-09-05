# The approval gate

`AGENTS.md` rule 8 — run with `--dry-run`, read `"ok"`, then execute — assumes a human is reading
the chat between the two steps. Headless, nobody is.

So the rule becomes: **an agent runs unattended for everything read-only, and stops for one click
at every write to a system of record.** Reads are free because a wrong read costs nothing; a wrong
write to Jira, Confluence or Bitbucket is something a person has to go and undo.

```bash
ad-fleet approvals
```

```
approvals[1]{id,repo,ticket,kind,waiting,summary}:
  luna-jira-transition-20260905T101806-a52c,luna,RDSD-118,jira-transition,4m,"RDSD-118: In Progress -> In Review"
```

```bash
ad-fleet approval luna-jira-transition-20260905T101806-a52c
```

…prints the dry-run result in full, so what is approved is exactly what will be sent. Then one of:

```bash
ad-fleet approve luna-jira-transition-20260905T101806-a52c --comment "yes, and add the PR link"
```

```bash
ad-fleet deny luna-jira-transition-20260905T101806-a52c --reason "wrong ticket, this is RDSD-119"
```

A denial **requires** a reason. The agent quotes it into its friction log, and "denied" with no
reason gives whoever picks the ticket up nothing to act on.

## Two layers, and why neither is enough alone

**Layer 1 — the launch allow-list (#93).** The agent is started with an enumerated whitelist of
shell commands. `curl`, `Invoke-RestMethod`, `wget` and bare `pncli` are not on it, and are on the
deny floor as well, so the agent cannot reach a system of record except through an `ad-*` command.

**Layer 2 — the gate (this file).** The `ad-*` command that performs the write blocks until an
operator answers.

Layer 1 alone would be trusting a model's own permission classifier. The spike measured that
classifier refusing `apply_patch`, refusing `Set-Content`, and then **allowing** a .NET file-write
made from inside PowerShell — the model tried four spellings and the fourth went through
([fleet-spike.md](fleet-spike.md)). A boundary that can be talked around by rephrasing is not a
boundary.

Layer 2 alone would be trusting that the agent only ever writes through our commands. It is
enumerated permission that makes that true.

Anything that must be *refused* rather than merely un-allowed therefore belongs in the `ad-*`
command, where a refusal is a return value rather than a guess about a command string.

## What is gated

| Command | Gated when | Not gated |
| --- | --- | --- |
| `ad-jira transition <KEY> --to <intent>` | run without `--dry-run` | `--dry-run`; `ad-jira transitions`, `changelog`, and every other read |
| `ad-pncli raw <product> <verb> …` | the verb is not in the read allow-list below | any command carrying `--dry-run`; every verb in the list |
| `ad-pncli jira search` / `ad-pncli jira get` | never | these are reads by construction — they do not go through `raw` |

The pncli read allow-list is `agentdata/connectors/pncli.READ_VERBS`:

`jira search`, `jira get`, `jira get-issue`, `jira changelog`, `jira transitions`, `jira comments`,
`jira fields`, `jira list`, `confluence get-page`, `confluence search`, `confluence list-pages`,
`bitbucket get-pr`, `bitbucket list-prs`, `bitbucket diff`, `config get`, `config list`,
`config show` — plus the bare commands `help`, `version`, `where`.

**Everything else is treated as a write.** That direction is deliberate. A write verb missing from
a *write*-list would be sent unattended; a read verb missing from this list costs the operator one
extra click. It is also what makes the gate work on verbs nobody has pinned yet — the Bitbucket PR
verb and the Jira comment verb are both still `TODO(HANDOFF)` in their skills, and both are gated
today regardless of what they turn out to be called.

## What the agent sees

Outside a fleet — a person in PyCharm, a CI job, every existing test — `AGENTDATA_FLEET_AGENT` is
unset and `approval.require()` returns `approved` before it touches the disk. Behaviour is
byte-for-byte what it was.

Inside a fleet, three refusals, all with `ok: false` and exit 2:

| `refused` | Means | The agent's move |
| --- | --- | --- |
| `approval_denied` | an operator said no, and why | `friction-log` type `missing-info`, quoting the reason. Do not retry. |
| `approval_timeout` | nobody answered within `fleet.approval_timeout` (default 30 min) | same, quoting the approval id. Re-running the identical command is safe — nothing was sent. |
| `approval_unavailable` | the request could not be recorded at all | same. Nothing was sent. |

The third one is the fail-closed case: if the approvals directory cannot be written, the answer is
*refused*, never "proceed anyway". A gate that fails open on a full disk is not a gate, it is a
delay.

The three skills that perform writes each carry one line to this effect — `jira-transition` step 7,
`bitbucket-pr` step 7, `confluence-publish` step 8.

## Where it lives on disk

Under `~/.agentdata/fleet/approvals/` (or `$AGENTDATA_FLEET_DIR`):

* `<id>.json` — the request: repo, ticket, kind, summary, the dry-run payload, when it was made.
* `<id>.decision.json` — the answer: `approved` or `denied`, the reason, who, when.

An approval is answered once; a second `approve` is refused rather than silently ignored, because
the agent has already been told. Answered pairs older than 30 days are pruned. **Pending ones are
never pruned, however old** — an unanswered write is not litter.

Both decisions also land in the agent's event stream (`needs_approval`, then `approval_resolved`),
so the dashboard tile clears on its own. See [fleet-events.md](fleet-events.md).

## Configuration

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.approval_timeout` | `1800` | seconds an agent waits at a write before refusing with `approval_timeout` |

## Still never

Merging a pull request and closing a ticket are not gated actions — they are not done at all,
approval or no approval (`AGENTS.md` rule 8). Approving arbitrary shell commands is also out of
scope: that is the allow-list's job, and "pause for every tool call" was declined deliberately —
an agent that asks about `git status` trains its operator to click yes without reading.
