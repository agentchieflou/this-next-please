---
name: file-organize
description: "Use when a folder of files has to be organized — a delivery of documents to sort before a DPM run, a heap with no structure, 'where should these go', 'file these by loan number'. Plans the arrangement and writes it down; never copies or moves anything itself."
---
# Organizing a folder of files

You plan. A person applies. That split is the whole skill: `ad-sort plan` writes a plan and touches nothing else, and
`ad-sort apply` is the command whoever owns the heap runs after reading it. Do not run `apply`.

Prereq: a **rule set**, and it is an input like a DPM field list — supplied or agreed by whoever owns the folder. No
rule set and no agreement on one → `friction-log` type `missing-info`. STOP. Guessing where somebody's documents go is
how a loan packet ends up under the wrong borrower.

1. Look at the real names first. `ad-sort plan` on any heap lists every file, so run it once with a starter rule set to
   see what is actually in there:

```
ad-sort rules --write .agent/in/<name>-rules.json
ad-sort plan --heap <folder> --rules .agent/in/<name>-rules.json
```

2. Edit the rule set against those names and propose it to the requester. One rule is `match` (a `glob` on the name, a
   `regex`, or both), `into` (the folder), and an optional `rename`. Named groups in the regex become placeholders, so
   `(?P<loan>\d{8})` lets `into` be `loans/{loan}`. Also available: `{stem}`, `{ext}`, `{original}`, `{year}`,
   `{month}`, `{day}`. **First matching rule wins** — the order in the file is the precedence.
3. Re-plan and read `meta`. The counts are the whole picture:
   - `file` — a rule claimed it and the destination is free. Only these are ever copied.
   - `unmatched` — no rule claims that name. Not a failure. It is the list to take back to the requester; do not invent
     a rule to make the number zero.
   - `collision` — two files want one destination, or something is already there. **Never resolve this by adding a
     suffix.** Which of two documents is the real one is not yours to decide; report them.
   - `skipped` — a directory, a partial download, a link leading out of the folder, or a file over the size cap, each
     with its reason.
4. Exit codes: `0` something would be filed, `1` the folder is real but no rule claimed anything in it (say so — a heap
   nobody has written rules for looks exactly like a tidy one), `2` refused, and `meta.refused` names which refusal.
5. The plan is `.agent/out/<heap>-sort-plan.json` and the page to read is `.agent/out/<heap>-sort-plan.md`. Cite those
   paths. Never restate the rows in chat.
6. Hand the apply line to the person, do not run it:

```
ad-sort apply --plan .agent/out/<heap>-sort-plan.json --dry-run
ad-sort apply --plan .agent/out/<heap>-sort-plan.json
```

   It copies and never moves, so the folder they showed you is still there afterwards. It refuses a plan whose folder
   has changed since — if they come back with `heap_changed`, re-plan, do not tell them to force it.
7. **Never plan a DPM run root as the destination, and never as the heap.** The run root is read-only and fingerprinted;
   `ad-dpm` fails if anything under it changed. Sort the delivery *before* it becomes a run, or sort a copy.
8. `state-update`: artifacts. Hand off → `dpm-consumer-integration` when the sorted folder is what a run will read,
   else `router`.

## The DPM remediation structure (RDSD-22488)

A delivery of retrieved documents does **not** use a rule set — the structure is prescribed and the fields come from
retrieval's own JSONL, one per source system. Use these instead:

```
ad-sort probe --at <the volume the structure lives on>
ad-sort dpm-plan --heap <downloads> --root <M:/.../DPMRemediationDOCS> --ticket RDSD-nnnnn                  --catalog LSS=<lss.jsonl> [--catalog IMZ=<imz.jsonl>] [--loans <population>]
```

* Verdicts here are `file`, `already_filed` (this loan's manifest has it — retrieval is never repeated),
  `missing_from_disk` (**a retrieval gap, report it as one**), `collision`, and `unclassified` (a file no catalogue
  names, so nothing knows its loan or its type).
* `--loans` is what makes "which loans returned nothing" answerable. Without it the report says it cannot say, and you
  must repeat that rather than reporting zero.
* `IsTiff` documents are filed as they are and **queued** for PDF conversion. They are not converted. Never describe
  them as converted.
* `IsCanView` false is counted per loan for the administrative report. Those documents are still filed — they are
  evidence that a retrieval happened.
* **LIS has no field map.** `ad-sort dpm-plan --catalog LIS=…` refuses. Get a sample record to whoever maintains
  `agentdata/sorting/catalog.py`; do not map it yourself from a filename.
* The apply line is still a person's, and views are hardlinks where the volume allows: `ad-sort probe` answers that
  before anyone commits to a storage budget.

§ The rule-set shape, the DPM structure and every refusal: `docs/sorting.md`.
