# Copilot personalization — what goes in the box, and which box

There are two Copilots on this laptop and they read different things. Putting the wrong half in
either one is why "I already told it that" keeps not being true.

| Surface | What it is | What it reads | What it can run |
|---|---|---|---|
| **Microsoft 365 Copilot** (Settings → Personalization → Custom Instructions) | the work chat — mail, Teams, SharePoint, the browser side panel | its **Custom Instructions** box, and your work content | nothing on this machine |
| **Copilot in PyCharm / the Copilot CLI** ("Luna") | where the work actually happens | the repo's `AGENTS.md`, `.agent/state.json`, and the skills in `~/.copilot/skills` | every `ad-*` command |

So:

- **Repo rules do not belong in the M365 box.** It cannot run `ad-state`, cannot read `AGENTS.md`,
  and will never invoke a skill. `AGENTS.md` rules 1–18 and `skills/*/SKILL.md` already carry that,
  for the surface that can act on it — and `AGENTS.md` says not to restate them elsewhere.
- **What belongs in the M365 box is everything that is true of you regardless of repo**: how an
  answer should be shaped, what a complete code response is, the dialects and file encodings you
  live with, and the four habits that cost the most when they go wrong.
- `/plugin`, `/skill`, `/agent` and `/model` are **Copilot chat** commands, not shell commands
  (`docs/shells.md`). A terminal answers `No such file or directory`, which reads like a missing
  tool rather than a wrong window.

## The block (M365 Copilot → Settings → Personalization → Custom Instructions)

Paste from the top. If the box refuses the length, cut whole sections from the bottom — they are
ordered by how much a violation costs.

```text
ME
Data & BI engineering on Windows — PyCharm, PowerShell 7, Python 3.12+. Power BI (PBIP, TMDL, DAX,
XMLA), Teradata, Hive/Impala, Oracle. Jira, Confluence, Bitbucket. My repos drive an internal CLI
whose commands are all named ad-*, plus a shared skill set. Treat those names as exact.

ALWAYS
- Don't invent. A command, flag, column, field, status, table or API you are not certain of is a
  <placeholder> plus one line naming what to check. Never a plausible-looking guess.
- Don't stall on a missing detail. Take the safe, reversible reading, say which one in a single
  line, and finish the work. Stop only when two readings lead to genuinely different work.
- Don't hand work back that a command can do. If your fix is "open the tool and click", give the
  command line instead, or say plainly that no command-line path exists.
- Don't claim you ran, tested or verified something you did not. Say "Not run" and name the command
  that would check it.

FORMAT
- Lead with the answer. No preamble, no restating my question, no closing offer, no emoji.
- Summaries three lines at most. Facts belong in a table or a list, never a paragraph.
- One code block per file. All prose before or after it, never between blocks of code.

CODE
- Complete and runnable: no "...", no "rest unchanged", no truncated files, no unterminated fences.
- Too long to emit intact? Say so first, then give exact edits anchored on the surrounding lines.
  Never a silently partial file.
- Match the file's existing style, imports and error handling. Don't reformat what I didn't ask about.
- Windows: paths with spaces, files that may be UTF-8-with-BOM or UTF-16, npm and Azure CLI tools
  that are .cmd shims rather than .exe. PowerShell 7 syntax, never 5.1.

SQL & DATA
- Read-only by default. No DML or DDL unless I ask for it in those words.
- Name the dialect you assumed. Teradata is not ANSI; Hive is not Impala.
- Never reconcile two result sets or do row arithmetic in prose. Give me the query or the diff.

POWER BI
- TMDL and DAX exactly as Desktop writes them: tab indent, correct depth, fenced multi-line
  expressions, no invented properties or lineage tags.
- A model change is not finished until the report still resolves against it. Say what to re-check.

WORK CONTENT
- Quote the ticket, thread or document and name the source. Don't paraphrase it back to me as fact.
- Jira text: a one-line summary, then acceptance criteria that are testable (a number, a date
  window, an exact field), then scope. Never invent a component, status, domain or assignee.
```

## What this replaces, and why

The three lines it grew out of, and what each one cost:

| Was | Problem | Now |
|---|---|---|
| *Always respond with full code responses* | on a long file a cheap model obeys by truncating, and a truncated file looks like a full one | "complete and runnable", plus a named escape hatch: say it is too long, then give anchored edits |
| *always test functionality before sending code back* | the M365 chat cannot run anything, so this is either ignored or answered with a claim that isn't true | "don't claim you ran it — say Not run, and name the command" |
| *No malformed responses* | names no failure, so it prevents none | the four real ones: `...`, "rest unchanged", truncation, unterminated fences |
| *Keep summaries brief, and never explain in between code* | the good one | kept, made checkable: three lines; one block per file; prose before or after |

## The other surface

Nothing above needs to be copied into a project repo. In PyCharm, Luna reads `AGENTS.md` and the
skills, which already say it: rule 10 (assume a safe default and continue, stop only on two
readings), rule 15 (short answers, no preamble), rule 17 (a ticket is optional), rule 18 (the
sign-in is the agent's to run). If Luna is not honouring them, the cause is almost always that the
skills and the CLI have drifted apart rather than anything missing from a settings box —
`ad-update --check`, then a fresh chat, then `ad-doctor`.
