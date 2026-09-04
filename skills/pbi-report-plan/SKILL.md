---
name: pbi-report-plan
description: "Plan Power BI report pages, audience intent, and locked layout spec with single-question inquiry rounds and human approval gate."
---

# pbi-report-plan: Report Planning & Spec Locking

Plan report structure from ticket requirements and semantic model before authoring.

## Planning Protocol
1. **Step 0 — Inspect Semantic Model (`pbip-projection`)**:
   - Run `ad-pbip project`.
   - Read `.agent/pbip/<name>/MODEL.md` (tables, measures, dependencies).
   - Never plan against a model you have not projected.
2. **Inquiry Rounds (Max 5 Rounds)**:
   - Check `.agent/state.json` and Jira context first for answers. Do not re-ask known facts.
   - Each round: ask **exactly one question, then STOP**. Wait for user response.
   - Round 1: Primary audience and decision objective (scan time: 5s executive vs 10m analytical).
   - Round 2: Page scope (executive summary, operational monitor, analytical canvas).
   - Round 3: Key metrics, grain, and date slicer defaults.
   - Round 4: Layout hierarchy and region priorities.
   - Round 5: Theme, color signature, and tone.
3. **Draft the Specification**:
   - Write `.agent/brief/<KEY>-report-spec.md` with frontmatter:
     - `ticket`, `pbip`, `model_sha` (from `meta.json`), `audience`, `pages[]`.
   - Embed the `design_brief:` YAML block containing:
     - `theme` (base and brand primary color).
     - `pages[]` with `title`, `canvas` (`width`, `height`), `layout_contract` (`grid`, `regions`, `placements`), and `space_audit`.
4. **Pre-flight Validation**:
   - Run `ad-pbip brief check .agent/brief/<KEY>-report-spec.md`.
   - If findings return errors: fix layout bounds, overlaps, or field names in the spec.
5. **Human Approval Gate**:
   - Output: `blocked — review .agent/brief/<KEY>-report-spec.md, then run ad-pbip brief approve .agent/brief/<KEY>-report-spec.md`.
   - **STOP**. Never proceed to authoring without `ad-pbip brief status` reporting `current`.
