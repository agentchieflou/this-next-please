# Fleet spike: does `copilot -p` run Luna headless?

The go/no-go for epic #91 (issue #92). Everything below was **measured on a machine**, not read from
documentation; where a claim could not be measured here it says so and says who must measure it.

**Verdict: go, with conditions.** The mechanism works — a headless `copilot` process in a repo reads
that repo's `AGENTS.md`, emits a clean JSONL event stream with a turn boundary, a session id and a
cost, and honours a tool allow-list with prefix matching. Four of the epic's own assumptions were
wrong, and the conditions below are what falls out of that.

## What was measured, and where

| | |
|---|---|
| Machine | Windows 11, Git Bash (MINGW64) and PowerShell |
| `copilot` | GitHub Copilot CLI **1.0.81** |
| `gh` | 2.96.0 · node 21.7.3 · npm 10.5.0 |
| Model served | `claude-haiku-4.5` (auto-selected) |
| Billing unit | **premium requests** (`session.usage_checkpoint.totalPremiumRequests`, `result.usage.premiumRequests`) |

**This is not the corporate laptop.** Everything about the *tenant* — the MCP policy, the proxy,
custom agents, BYOK, rate limits — is unverified here and is listed under [What still needs the
corporate machine](#what-still-needs-the-corporate-machine). Nothing in this document should be read
as "the org allows it".

## Headless Luna works — proven, not argued

With the skills installed, a headless turn was given nothing but
`copilot -p "Invoke the skill session-bootstrap…"`. It:

1. invoked `skill: session-bootstrap` — **ok**
2. read `AGENTS.md` and `.agent/state.json`
3. ran `ad-doctor --quiet`
4. reported that `ad-doctor` is not on PATH and gave the module-form recovery, which is correct on
   this machine and is exactly what the new `console/scripts` doctor row says

Exit 0, **1 premium request**, no human. That is #92's step 3 acceptance criterion met: the skill was
followed, the toolchain was checked, and it stopped where the skill says to stop.

## Four assumptions in #91, re-examined

### 1. Skills: the epic was right, and `ad-update` was still wrong

**Corrected after installing them.** Copilot CLI 1.0.81 reads **both** `~/.copilot/skills` *and*
`~/.agents/skills`: `gh skill install … --scope user --agent github-copilot` writes to the former,
and one `copilot skill list` afterwards shows skills from both as "Personal". An earlier draft of
this document concluded that `~/.copilot/skills` "does not exist and is not read" — it did not exist
*on this machine*, because the skills had never been installed at user scope, and absence was read as
exclusion. The epic's premise stands.

The bug in `ad-update` was narrower than that draft claimed, and real:

* `SKILLS_CMD` did not pin `--agent`, and `gh skill install --help` says the default is
  `github-copilot` only *"when running non-interactively"* — so an interactive run could put the
  skills where the CLI never looks. It is pinned now.
* `SKILL_DIRS` did not list `~/.agents/skills` at all, which is a directory the CLI genuinely reads
  and which other agents share.

Before the install, `ad-update --check` reported `skills: 0` and `stale_skills: false` — the
staleness check is guarded on `skills["installed"]`, so it could never fire. Afterwards:
`skills_dir: ~/.copilot/skills`, `skills: 36`.

### 2. Without the skills installed, a headless copilot is not Luna

Before the install, asked to run a shell command, the model's *first* action was:

```json
{"type":"tool.execution_start","data":{"toolName":"skill","arguments":{"skill":"session-bootstrap"}}}
{"type":"tool.execution_complete","data":{"success":false,"error":{"code":"failure"}}}
```

It inferred `session-bootstrap` from `AGENTS.md` — which **is** loaded (`copilot plugins list` shows
`Instructions → Repository → AGENTS.md`) — and the skill was not installed. So "a headless `copilot`
in a project repo is the same Luna" holds *only after*
`gh skill install agentchieflou/this-next-please --all --scope user --agent github-copilot`. That is a
precondition, and `ad-doctor`/`ad-update` now report it truthfully.

### 3. The tool allow-list is not the `ad-*` family

#91 says each agent launches with "an explicit tool allow-list (the `ad-*` family,
`python -m agentdata`, `git` …)". Tools are named things like `powershell`, `bash`, `skill`, `write`;
a shell command is an *argument* to a shell tool. The accepted syntax is:

```
--allow-tool 'shell(git --version)'     # exact command
--allow-tool 'shell(git)'               # PREFIX — `git status --short` ran under this
--allow-tool skill                      # the skill tool itself must be allowed
```

Prefix matching was measured: with `--allow-tool 'shell(git)'`, `git status --short` executed
successfully. So `fleet.allow_tools` in #93 is a list of `shell(<prefix>)` patterns plus the
non-shell tool names, e.g.

```
shell(ad-)   shell(python -m agentdata)   shell(git)   skill
```

`--allow-all-tools` is documented as *"required for non-interactive mode"*, but that is not true when
explicit `--allow-tool` patterns are supplied — the runs below used no `--allow-all*` flag.

### 4. A denied tool is not a failed turn, and there is no permission-request event

#92 asks whether a permission request "surfaces as an event or just ends the turn". It does
**neither**. With `--no-ask-user` and no allow-list, the tool is attempted and comes back:

```json
{"type":"tool.execution_complete","data":{"success":false,
 "error":{"message":"Permission denied and could not request permission from user","code":"denied"},
 "toolTelemetry":{"properties":{"shell_error_category":"permission_denied"}}}}
```

…and the turn runs to completion with **`exitCode: 0`**. The model narrates the denial and stops.

**Consequence for #95:** "the agent is waiting for me" cannot be detected from the exit code or from
a permission event, because neither exists. It must be derived from
`tool.execution_complete` where `data.error.code == "denied"`. That is a deterministic rule, which is
what #94 asked for — it is just not the rule the epic expected.

## The permission model is a whitelist, and it leaks

The sharpest safety finding, and it is not what the epic assumed. Run with **no allow-list at all**
and asked to create a file, the agent:

| Attempt | Verdict |
|---|---|
| `apply_patch` (the CLI's own write tool) | **denied** |
| `powershell: Set-Content -Path .\probe.txt -Value hello` | **denied** |
| `powershell: Get-Location`, `Get-ChildItem` | allowed |
| `powershell:` a .NET file-write call, made from inside PowerShell | **allowed — and the file was written** |

Three things follow, and every later slice depends on them.

1. **"No allow-list" is not "no permissions".** Some commands run by default; the CLI classifies
   them. A fleet that omits `--allow-tool` is not running a sandboxed agent.
2. **The classifier can be talked around.** It denied two spellings of "write a file" and permitted a
   third that does the same thing. This is not a bug to route around — it is the reason a deny-list
   can never be a boundary.
3. **The model iterates through denials.** It did not stop at the first refusal; it tried four
   further spellings until one passed. Anything designed as "deny the dangerous thing" is designed
   against an adversary that retries.

So the fleet's containment is the **allow-list, kept tight** — an enumerated whitelist of command
prefixes narrow enough that no dangerous continuation can be appended — and the deny-list is a
second line for near-miss spellings, never the boundary. `agentdata/fleet/launch.py` is written that
way and says so.

**And for #95:** the approval gate cannot rest on the CLI's permission system. A write to a system of
record must be gated by the `ad-*` command that performs it, which is what epic #91 already
specifies — "an approval decision is the `ok`/`refused` TOON a gated `ad-*` command returns". This
measurement is why that is the only design that can work, rather than one of two options.

## The JSONL event catalogue

`--output-format json` emits one JSON object per line. Every event carries
`{type, id, parentId, timestamp, data}`; the noisy ones additionally carry `"ephemeral": true`.

**`ephemeral` is the discriminator #94 needs.** Dropping ephemeral events leaves exactly the
durable narrative:

| Event | Carries |
|---|---|
| `user.message` | the prompt |
| `assistant.turn_start` / `assistant.turn_end` | `turnId` — the turn boundary |
| `assistant.message` | `content` (assistant text), `toolRequests[]`, `model`, `messageId` |
| `tool.execution_start` | `toolName`, `arguments`, `toolCallId` — **not ephemeral** |
| `tool.execution_complete` | `success`, `error.code` (`denied` / `failure`), `toolTelemetry` |
| `session.usage_checkpoint` | `totalPremiumRequests`, `totalNanoAiu`, cache state |
| `result` | `sessionId`, `exitCode`, `usage.premiumRequests`, durations, `codeChanges.filesModified` |

`result` alone answers three of #92's acceptance criteria: the turn boundary, the cost, and the
`sessionId` that `--resume` takes.

Ephemeral kinds seen (safe to drop): `assistant.reasoning_delta`, `assistant.message_delta`,
`assistant.tool_call_delta`, `model.*` (twelve kinds), `session.mcp_server_status_changed`,
`session.mcp_servers_loaded`, `session.tools_updated`, `session.background_tasks_changed`,
`assistant.idle`.

## Cost

| Turn | Premium requests |
|---|---|
| Trivial reply, no tools | **0.33** |
| One shell tool, denied | **0.33** |
| One shell tool, allowed (3 model calls) | **1.00** |

Four agents doing real work will not be cheap; #101's budget should be expressed in premium requests
and read from `result.usage.premiumRequests`, which is exact and per-turn.

## Flags, as this build actually names them

`--headless --port` **does not exist**, in either spelling #91 guessed. What exists:

- `--acp` — "Start as Agent Client Protocol server". This is the server mode; the SDK path in #92
  step 7 must be evaluated against `--acp`, not `--headless`.
- `-p/--prompt`, `--output-format json`, `--resume`, `--continue`, `--session-id`, `--no-ask-user`,
  `--log-dir`, `--log-level`, `--add-dir`, `-C <dir>`, `--allow-tool`, `--deny-tool`,
  `--available-tools`, `--excluded-tools`, `--max-ai-credits`, `--usage-output-file`,
  `--agent`, `--plugin-dir`, `--autopilot`, `--model`, `--effort`.
- **`--usage-output-file <file>`** writes final usage as JSON — a simpler cost hook than parsing the
  stream, worth using in #93.
- **`--disable-builtin-mcps`** — the CLI ships a built-in `github-mcp-server`. #91's "no MCP
  anywhere" rule therefore needs an *action*, not just an absence: the fleet should launch with
  `--disable-builtin-mcps`, and the supervisor's status output should say so.

## MCP on this machine

`copilot mcp list` answers cleanly: *"No MCP servers configured"*, exit 0 — that is **unconfigured,
not refused**. The org policy #91 records ("MCP disabled, confirmed by the repo owner") could not be
observed here, and a fleet must not read "no servers configured" as "policy refusal". Whatever the
corporate tenant does, the built-in `github-mcp-server` above means the epic's rule needs the
explicit disable flag regardless.

## What still needs the corporate machine

None of this blocks the epic; all of it must be filled in before #95, #100 and #101 design against it.

- [ ] **The org-policy table.** MCP (expected: refused), custom agents (`--agent`), plugins,
      autopilot, BYOK, `--acp`, server mode — each `allowed | refused | unknown` with the message
      quoted. Nothing here was observed on the corporate tenant.
- [ ] **The proxy.** `copilot login` and a turn from behind the corporate proxy.
- [ ] **A real triage.** #92 step 4 — `copilot -p "Triage <KEY>" --resume <id>` reaching
      `jira-triage` step 7 with `phase=triaged` in `state.json`, from PowerShell *and* Git Bash. It
      needs a repo (`rdsd-pbi-reporting`) and a low-stakes ticket key that only the operator can pick.
- [ ] **Two agents at once**, in two repos, sharing `~/.copilot/session-store.db` — does `--resume`
      pick the right session per repo, and does the tenant rate-limit?
- [ ] **The SDK trial** against `--acp`, if policy allows server mode.
- [x] ~~Skills installed~~ — done, 2026-09-05. `gh skill install agentchieflou/this-next-please
      --all --scope user --agent github-copilot` wrote 36 skills to `~/.copilot/skills`, and a
      headless turn then ran `session-bootstrap` end to end (see the top of this document).

## Transport decision

**JSONL over subprocess**, provisionally, and the reasons are now evidence rather than preference:

- The event stream already carries everything #94 needs, including the two things the SDK was hoped
  to add: a typed turn boundary (`assistant.turn_end`, plus `result`) and the tool-denial signal.
- There is no permission *callback* to gain, because there is no permission *request* — the CLI
  denies and narrates. An SDK handler would have nothing to answer.
- `--acp` is the only server mode, and whether the tenant allows it is unknown. JSONL needs nothing
  beyond the `copilot` binary that is already installed and licensed.

Revisit only if the corporate policy table shows something JSONL cannot reach.

## Conditions on the "go"

1. Skills must be installed to `~/.agents/skills` before any agent is expected to behave like Luna.
   `ad-update` now looks there and installs there.
2. The supervisor (#93) launches each agent with `--disable-builtin-mcps`, an explicit
   `shell(...)` allow-list, and
   `--no-ask-user`; never `--allow-all-tools` or `--yolo`.
3. "Needs the human" is derived from `tool.execution_complete` with `error.code == "denied"`, not
   from exit codes.
4. The corporate-machine checklist above is completed before #95 and #101 are built.
