# `ad-sort`: organizing a folder of files

Sorting *files into folders*, not rows in a table. It exists because of a real refusal: an agent in the DPM vertical was
asked to organize a delivery of documents, had no sanctioned way to do it — canonical rule 12 makes writing outside
`.agent/` a stop condition — and correctly stopped. This is the sanctioned way, and it keeps rule 12 rather than
carving an exception in it: the command an agent runs writes nothing but its own plan.

| Command | Who runs it | What it touches |
| --- | --- | --- |
| `ad-sort rules --write <path>` | either | writes a starter rule set to edit |
| `ad-sort plan --heap <folder> --rules <file>` | the agent | writes `.agent/out/<heap>-sort-plan.{json,md}`. Nothing else. |
| `ad-sort apply --plan <file>` | **a person** | copies the planned files. Never moves. |

## The rule set is an input

Nothing here invents a rule. The file is supplied or agreed by whoever owns the folder, the same way a DPM field list
is, because where somebody's documents belong is not a thing to infer from their filenames.

```json
{
  "version": 1,
  "into": "sorted",
  "rules": [
    {"name": "loan-packets",
     "match": {"glob": "*.pdf", "regex": "^(?P<loan>\\d{8})[-_ ]"},
     "into": "loans/{loan}"},
    {"name": "spreadsheets-by-month",
     "match": {"glob": "*.xlsx"},
     "into": "spreadsheets/{year}-{month}",
     "rename": "{year}-{month}-{day}-{stem}{ext}"}
  ]
}
```

* `match.glob` is matched against the file's name, case-insensitively because Windows is. `match.regex` is *searched*
  in it, Python syntax. A rule with both must satisfy both.
* **First matching rule wins.** The order in the file is the precedence — stated rather than sorted by specificity,
  because a person reading a plan has to be able to predict it.
* `into` and `rename` may use any named group of that rule's regex, plus `{stem}`, `{ext}`, `{ext_nodot}`,
  `{original}`, and the file's mtime as `{year}`, `{month}`, `{day}`. An unknown placeholder is refused **when the file
  is read**, not discovered later as a folder called `{borrwer}`.
* `into` may only file downwards. A `..` in a destination is `escaping_destination`, and a captured value is passed
  through the same name-safety filter every other output path in this repo uses, so a filename cannot dig a new folder.

## The four verdicts

Every entry in the folder gets exactly one, and every entry appears — a listing where a file silently vanished is one
nobody trusts again.

| Verdict | Means | What `apply` does |
| --- | --- | --- |
| `file` | a rule claimed it, the destination is free | copies it |
| `unmatched` | no rule claims that name | nothing |
| `collision` | two files want one destination, or something is already there | nothing |
| `skipped` | a directory, a partial download, a link out of the folder, or over the size cap — with the reason | nothing |

`collision` is never resolved by appending `(2)`. Which of two documents is the real one is not a decision a planner
gets to make, so it is reported and left.

## What `plan` may not do

**It never opens a file.** It reads names, sizes and mtimes through `os.scandir` and decides by name.
`tests/test_sorting_plan.py::test_planning_never_opens_a_file` records every `open()` a plan performs and fails if
there is one — the same guard `ad-fleet inbox` has on Downloads, for the same reason. A delivery folder holds a bank
statement and somebody's mailed `secrets.json` next to the documents the job is about, and a planner that read a file
to decide where it belongs would be reading all of them.

## What `apply` may not do

* **It copies. It never moves.** The folder it read is still there afterwards, so a wrong rule set costs disk and not
  documents, and a second `plan` of that folder still describes the same folder. Moving is a different tool with a
  different safety story — a journal and an undo — and is deliberately not this one.
* **It refuses a stale plan.** The plan carries a fingerprint of the folder; if a file has arrived, gone or changed
  since, `apply` exits `heap_changed` and copies nothing at all. Re-plan and read the new plan. There is no `--force`,
  because the thing being forced would be filing a folder nobody looked at.
* **It never overwrites.** The destination is re-checked at copy time, because the plan checked and then time passed.
  Anything already there is left alone and counted as `already_there`.
* **It never files into the folder it read.** That would put the plan's own inputs under its own output, and the next
  plan would describe the copies. The default destination is `<folder>-sorted`, beside it.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | something would be filed, or was |
| 1 | the folder is real but no rule claimed anything in it |
| 2 | refused; `meta.refused` names which |

`1` is the one worth wiring into a script. A heap nobody has written rules for looks exactly like a heap that is
already tidy, and that is the difference between the two.

## DPM

A DPM run root is read-only and fingerprinted — `ad-dpm` fails if anything beneath it changed — so **never sort into
one and never sort one**. Sort the delivery before it becomes a run, or sort a copy. The skill (`file-organize`) says
this too; it is the one way to use this tool that breaks something else.
