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

**Layer 1 — the launch allow-list (#93), for an agent set to `fleet.permissions: strict`.** Since
2026-10-02 the default is a Copilot window's tools (`--allow-all-tools`, [fleet.md](fleet.md)), and
for such an agent layer 2 is the boundary for every write made through an `ad-*` command. Under
`strict` the agent is started with an enumerated whitelist of
shell commands. `curl`, `Invoke-RestMethod` and `wget` are not on it, and are on the deny floor as
well. `toil` is on it, because toil is used directly for what it reads; in every mode its writes are
refused by the fleet's toil shim (below), so the agent cannot write to a system of record except
through an `ad-*` command.

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
| `ad-jira comment <KEY> --body …` | run without `--dry-run`; the operator approves the exact body (`kind: jira-comment`) | `--dry-run` (reads the issue, prints `chars`, `lines` and `first_line`, posts nothing) |
| `ad-jira create --summary …` | run without `--dry-run`; the operator approves the exact `POST /issue` body | `--dry-run` (resolves every field, posts nothing) |
| `ad-git push [--remote NAME]` | run without `--dry-run` and with commits ahead; the operator approves the plan (`kind: git-push`: branch, remote, target, ahead, subjects) | `--dry-run` (local refs only, contacts no remote); nothing ahead |
| `ad-confluence publish <file.md>` | run without `--dry-run`; the operator approves the plan (`kind: confluence-publish`: action, page id, title, space, parent, chars, and toil's exact command with the body summarised) | `--dry-run` (builds the body, resolves space, title and parent, runs nothing) |
| `ad-git pr` | run without `--dry-run`; the operator approves the plan (`kind: bitbucket-pr`: action, PR id, title, source, target, and toil's exact command) | `--dry-run` (local refs and config only, contacts nothing); `--draft` is refused `draft_unsupported`, because toil's PR verb has no draft |
| `toil <area> <command> …`, typed by a fleet agent | never waits: an argv carrying `--allow-write`, or a command that writes toil's own setup, is **refused** by the fleet's toil shim (`toil_write_in_fleet`, exit 2), with the extension that does it as the `hint` | everything else: the real toil runs with the same argv, its envelope and exit code untouched |

**Approval is not permission.** toil has its own write gate: a write needs `writes: true` on the connection,
which only a person sets, and `--allow-write` on the call; without them toil refuses with `WRITE_DISABLED` and
sends nothing. toil has no `--dry-run` -- a write without `--allow-write` is a refusal, not a preview -- so the
preview is the `ad-*` command's own `--dry-run`, and `--allow-write` is added only to the run the operator
approved, which then executes exactly the reviewed command. A connection stays read-only until a person turns
writes on, and the overlay reads that first: `ad-git pr` and `ad-confluence publish` ask `toil connections list` (local,
no network) before they plan, and refuse `toil_not_ready`, `no_connection` or `writes_off`, dry run included, so the
operator is never asked to approve a write toil would refuse. Should toil still refuse at run time, its
`WRITE_DISABLED` and fix are the answer, and nothing is retried.

**The fleet's toil shim.** `launch.child_env` writes `toil` (POSIX) and `toil.cmd` (Windows) into
`<fleet_dir>/bin/`, each running `python -m agentdata.fleet.toil_gate` with the agent's arguments, and
puts that directory first on the agent's PATH. A deny pattern could not do this job: a deny is a prefix,
and `--allow-write` can sit anywhere on the line. The shim resolves the real toil with its own directory
left out of the search, so it never runs itself, and neither do `ad-confluence publish`, `ad-git pr` or
`ad-jira`'s REST calls (which go through `toil jira api`). Outside a fleet it passes everything through.
Its classification is `agentdata/connectors/toil.is_write`:

* **`--allow-write` anywhere before `--`** (or `--allow-write=…`) is a write, even as some option's value. toil
  refuses a service write without it, so its absence is the proof of a read.
* **The commands that write toil's own setup without the flag** are writes: `connections` (all but `list` and
  `test`), `dossiers` (all but `list`, `show`, `context` and `check`), `skill`, `skills`, `setup`, `feedback`
  (it sends a public report) and `mcp` (a server is not an agent's to start).
* `--help` / `-h` never unlocks a write: `--allow-write` is looked at first.

The shim gates the command line. toil's MCP door is outside it: an MCP server a person registers with toil for an
agent lists write tools when writes are on for its connection, and nothing here intercepts them. That is why
`ad-doctor --only toil` reports every connection with writes on.

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

The four skills that perform writes each carry one line to this effect — `jira-transition` step 7,
`jira-create` step 3, `bitbucket-pr` step 6, `confluence-publish` steps 6 and 7.

## Where it lives on disk

Under `~/.agentdata/fleet/approvals/` (or `$AGENTDATA_FLEET_DIR`):

* `<id>.json` — the request: repo, ticket, kind, summary, the dry-run payload, when it was made, the
  waiting process's `pid`, and `digest`.
* `<id>.decision.json` — the answer: `approved` or `denied`, the reason, `by` (who), when, `digest` and
  `via` (`laptop` for the desk and the CLI; `wrapup` for a wrap-up's record). A decision that comes from the
  phone also carries `expires`; a laptop decision never does.

**The digest (#543).** `digest` is `sha256` over the canonical JSON (sorted keys, no spaces, UTF-8) of
exactly six request fields: `id`, `kind`, `summary`, `payload`, `created` and `pid`. `pid` is inside the hash and
never leaves the laptop; a decision made elsewhere echoes the digest instead. `approval.decide(..., digest=...)`
refuses a digest that is not the request's own with `digest_mismatch` and writes nothing. When a decision file
carries a digest that differs from the request's, the waiting agent is **refused** (`approval_denied`, reason
*the decision names a different request (digest mismatch)*), rather than released or left waiting on a decision
somebody made about something else. A decision with no `digest` (an older build) is read exactly as before.

An approval is answered once; a second `approve` is refused rather than silently ignored, because
the agent has already been told. Answered pairs older than 30 days are pruned. **Pending ones are
never pruned, however old** — an unanswered write is not litter.

Both decisions also land in the agent's event stream (`needs_approval`, then `approval_resolved`),
so the dashboard tile clears on its own. See [fleet-events.md](fleet-events.md).

## Configuration

| Key | Default | What it does |
| --- | --- | --- |
| `fleet.approval_timeout` | `1800` | seconds an agent waits at a write before refusing with `approval_timeout` |

## The operator's wrap-up

`ad-fleet wrapup <repo>` and the desk's *wrap up* (#503) run the same adapters as the module form,
with both fleet markers removed from the child's environment, so each adapter's own gate passes
through: **the confirm is the approval**, for exactly the ticked, dry-run-verified steps. Each
written step leaves one decided record, `by: operator` and `via: wrapup`, written decision first and
request second, so `ad-fleet approvals` and the `a` key never offer it. `ad-fleet approval <id>`
shows one in full, like any other.

## Still never

Merging a pull request and closing a ticket are never done on an agent's own initiative (`AGENTS.md`
rule 8), and neither is a gated kind: no approval request is ever filed for one, from the desk or the phone. When
the operator asks for a merge or a close in so many words, that is an instruction rule 8 says to carry out, not a
decision this gate takes. A wrap-up never offers a merge. It shows *done* unticked at end of project: a *done* row
the operator ticks is the operator's word, and the one way a ticket closes here. Approving arbitrary shell commands is also out of
scope: that is the allow-list's job, and "pause for every tool call" was declined deliberately —
an agent that asks about `git status` trains its operator to click yes without reading.
