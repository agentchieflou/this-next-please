---
name: research-spike
description: "Use when the request is real work and no routing row names it: a bounded investigation that writes what exists, what it would take, and which route should own it. Spends a fixed budget, then logs the coverage gap for the architect. Never ships the work itself."
---
# Research spike (bounded, then log the gap)

A spike is what a wider credit allowance buys: instead of stopping at `friction-log` the moment a request has no row, spend a **bounded** look and leave a page behind that makes the next route obvious. It is still not a licence to improvise the work. The output is a file and a friction entry, never a change to anything.

**The budget is the skill.** At most **12 tool calls** and **2 files written**, both under `.agent/`. Count them. The thirteenth call is AGENTS.md rule 11 territory: stop and write up what you have.

1. Restate the request in one line: *what* is asked, *for whom*, and the words in it no routing row names. `ad-state set phase=researching` (skill `state-update`).
2. Look for prior art, cheapest first, and stop as soon as one answers:
   - this project's `AGENTS.md` facts and `## Project routes`, and `.agent/in/<active_ticket>/brief.md` if it exists -- the operator may already have said how;
   - `ad-jira search --jql "project = <jira_project> AND text ~ \"<two or three of the request's own words>\" ORDER BY updated DESC" --fields key,status,summary` -- somebody may have done this before;
   - `ad-graph summary` when the request is about this repository's code (read-only; never `ad-graph approve`);
   - at most **3 files**, each ≤ 200 lines, named by what the steps above pointed at. No browsing.
3. Write `.agent/out/spike-<slug ≤ 4 words>.md`, ≤ 60 lines, with exactly these sections: `## Request` (step 1), `## What exists` (what step 2 found, with paths and keys), `## Options` (≤ 3, one line each: the route, the first command, and its cost class -- *cheap*: reads and one `ad-*` command; *medium*: a query or a projection; *dear*: a model run, a deploy, anything with an approval gate), `## Recommended route` (ONE of: an installed skill that now clearly fits; a `## Project routes` row to add, written out; a new skill to propose, with its name, its trigger words and its first three steps), `## Not done` (what this spike deliberately did not do).
4. `ad-state set --artifact .agent/out/spike-<slug>.md="spike: <request in ≤ 6 words>"`.
5. Decide, once:
   - An installed skill now clearly fits → print `→ <skill>: found by spike` and invoke it. One hop; a second spike on the same request is rule 11.
   - A `## Project routes` row would route it next time → `ad-state ask "Add this route to AGENTS.md: | <words> | \`<skill>\` |" --assume "proposed in the spike file, not written"`, then `friction-log` type `coverage-gap` quoting the row. STOP.
   - It needs a skill nobody has written → `friction-log` type `coverage-gap` with the proposed skill from the file as its *Proposed skill/instruction fix*. STOP.
6. Never: write outside `.agent/`; run a write to Jira, Confluence, Bitbucket or a warehouse; run a tool twice with the same arguments; start the work the spike recommends.
