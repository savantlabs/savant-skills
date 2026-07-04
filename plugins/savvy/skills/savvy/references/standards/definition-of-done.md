# Definition Of Done - Savant Workflow Skills

## Objective

Use this as the final claim gate before saying a Savant task is done, ready, verified, working, imported, fixed, deleted, or inspected.

## Use When

- A workflow skill is about to send a final completion response.
- The user asks whether something is done, ready, working, verified, clean, or production-ready.
- A Creator/import/full-delivery task needs validator-backed completion evidence.

## Default Action

- Map the user's request to the matching request type.
- Confirm the required evidence passed or explicitly state what was not run.
- Use the completion validator for create/import/full verified workflow claims.
- Run the completion gate as the last step before any unqualified done/ready/verified/working claim.
- Give qualified language when evidence is incomplete.
- Resolve upstream blockers before judging downstream outputs.
- Use the correct evidence surface: local JSON, imported recipe, affected settings/output, final output, or deletion read-after-check.

## Do Not

- Do not use unqualified completion language from JSON validity, save success, or preview refresh alone.
- Do not silently expand or shrink the user's requested scope.
- Do not leave scratch, failed, or duplicate flows in user-visible folders unless the user accepts them.

Detailed mechanics live in the skill, component, substrate, and validator docs. This file defines the finish line so skills do not invent their own.

## Completion Claim Gate

Use unqualified words like "done", "ready", "verified", or "working" only when the applicable evidence gate passes.

For create/import/full verified workflow delivery, write `completion_evidence.json` to the path from `savant.py session tmp-path <task-name> completion_evidence.json` and run:

```sh
savant.py validate stage --role creator --gate done <file> --claim done
```

If the completion validator fails, either run the missing checks or give a qualified answer that names what passed and what was not verified. Summarize the evidence for the user; do not paste the JSON unless asked.

Running `validate stage --role creator --gate done --claim done` is the mandatory final action before any unqualified done claim for create/import/full verified delivery; it is what enforces API availability and the required evidence checks.

Build-only work is not a completion-evidence scope. It is gated by workflow JSON validation.

## Validator-backed completion evidence rules

`savant.py validate stage --role creator --gate done` owns the machine-enforced contract. When writing `completion_evidence.json`, match these rules:

- `scope` must be `draft_import` or `full_verified_workflow`.
- `completion_claim` is `done` or `qualified`; `--claim` overrides the file. Unqualified completion is blocked when required checks are missing, failed, partial, or unknown.
- Required top-level fields: `task_type`, `scope`, `completion_claim`, `workflow_name`, `workflow_url`, and `checks`.
- Passing check statuses are `passed` and `not_required`. Non-passing statuses are `not_run`, `partial`, `failed`, or `unknown`.
- `draft_import` requires `workflow_created`.
- `full_verified_workflow` requires `workflow_created`, `validator_passed`, `pre_import_validator_passed`, `execution_completed`, `no_visible_errors`, `final_row_count_verified`, `checkpoint_counts_verified`, `business_logic_spot_checked`, `reference_outputs_reconciled`, `output_usability_reviewed`, and `descriptions_reviewed`.
- `execution_mode` is required for `full_verified_workflow`; `execution_mode` must be `analyze`, `test`, or `run`. Analyze is a real execution mode, not a reduced scope.
- Layout quality is not a completion-evidence check. It is verified separately by `savant.py validate workflow` (the deterministic layout checks on the JSON) before import/save — there is no rendered-canvas inspection.

## Done By Request Type

### Build-Only JSON

Done means the workflow file is complete, parseable, locally valid, and ready for import within the stated assumptions.

Required:

- The JSON follows Savant schema and local workflow patterns.
- `savant.py validate workflow` has no errors.
- Warnings are fixed or explained for the requested scope.
- Data-prep, filter/join/summarize, output, descriptions, and static layout rules were applied.
- Runtime assumptions are stated, including anything that must be bound or verified after import.

Do not claim it has run, produced outputs, or imported successfully.

### Draft Import

Done means the workflow was created in the intended workspace/folder and the imported structure is present.

Required:

- The intended destination was used.
- The imported workflow URL is known.
- The created recipe/shape matches the source JSON.

Do not claim business-data correctness, final output correctness, or full layout polish unless those checks also ran.

### Full Verified Workflow

Done means the workflow was created or updated, executed in the agreed mode, inspected, and shown to produce usable business outputs.

Required:

- Pre-import validation passed.
- The workflow exists in the intended workspace/folder.
- Execution completed in Analyze, Test, or Run mode.
- No active node errors or unresolved upstream errors remain.
- Final outputs and report-shaping steps have expected row counts.
- Key business logic was spot-checked at the right grain: joins, filters, summaries, amounts, FX, allocation, dates, dedupe, or the process-specific equivalents.
- Reference outputs reconcile when available; differences are classified as defects or documented process changes.
- Outputs are usable: expected destinations exist, final names and columns are business-friendly unless technical/source names were requested.
- Descriptions are present at the workflow, group, and step levels in Markdown, not HTML. Step descriptions follow `node-documentation-rules.md`: each one reads out the current node-specific configuration in business language, including formulas only for calculated fields or formula-based rules.
- Layout passed `savant.py validate workflow` (the deterministic layout checks per `canvas-layout-rules.md`).

### Edit Or Fix

Done means the intended change landed on the intended existing workflow and was verified at the level the change can affect.

Required:

- The target workflow and target step/group/path were unambiguous.
- The saved state matches the proposed change.
- Verification used the right evidence: settings diff, preview refresh, affected row count, downstream checkpoint, destination output, or the deterministic layout metrics for layout changes.
- Affected downstream steps were inspected or re-run when data behavior changed.
- Any step whose configuration changed has a refreshed description, or the existing description was checked and still accurately explains the current settings.
- Business-meaning changes were confirmed or stated.
- Layout edits passed the deterministic layout metrics (`canvas-layout-rules.md`).
- Alteryx migration cleanup followed the migration cleanup standard when that was the requested edit type.

A narrow edit does not require full workflow verification unless the edit can affect final outputs or the user asked for full verification.

### Delete

Done means the specific workflow was deleted and the absence was verified.

Required:

- The user confirmed deletion in chat for the specific workflow.
- The target was identified by URL or flow id, not name alone.
- Savant's deletion action completed.
- A refresh/read-after-delete no longer returns the workflow as present.

Do not claim a backup/export exists unless the user asked for one and it was created.

### Inspect Or Debug

Done means the user's specific question was answered from relevant evidence.

Required:

- The answer is grounded in the appropriate source: workflow structure, settings, preview data, row counts, run state, schedule state, output sample, or error detail.
- Diagnosis is separated from remediation.
- Any uncertainty or missing evidence is stated.

Do not claim the workflow was fixed, cleaned, production-ready, or fully verified unless the corresponding edit/import/full-verification path also ran.

### Explain Or Q&A

Done means the answer directly addresses the question without implying work that did not happen.

Required:

- Use available workflow, folder, skill, or product evidence when applicable.
- Distinguish "instructions exist" from "validated by a clean run."
- State limits when the answer depends on live workspace data that was not inspected.

## Layout Done

Layout done applies when the request includes creation, import quality, layout, grouping, readability, polish, or any claim that the process diagram is understandable to a new user.

The diagram is laid out entirely in the workflow JSON, so layout quality is judged from that JSON and its validation — there is no rendered-canvas inspection.

Required:

- Use `canvas-layout-rules.md` as the layout source of truth (lanes, semantic stage grouping, side/exception branches, clean connector corridors).
- Run `savant.py validate workflow` before import or local delivery and resolve its layout findings (collisions, connectors through nodes/frames, bent chains, inlet-order mismatches, terminal-output placement, canvas area) unless a concrete, user-facing reason makes a warning acceptable.
- Apply any layout fix in the JSON and re-validate until the layout checks are clean.

Layout done does not imply data logic, execution, or destinations were verified unless those checks also ran.

## Delivery Hygiene

When working in a user-visible folder, optimize for one clean final deliverable.

- For local files, "workspace folder" means the file must be accessible from the current workspace, not that generated artifacts belong in the repository root or durable project directories. Use the session-scoped workspace tmp path for generated local outputs unless the user explicitly names a durable output path.
- Get permission for the full delivery loop when it is not already clear: generate locally, import, execute, inspect, safely fix the same workflow, and verify.
- Iterate locally first. Use a disposable scratch flow only when live execution evidence is needed before final delivery.
- Import into the target folder only when the workflow is intended to be the deliverable.
- Fix safe layout or presentation issues on the same workflow instead of creating duplicates.
- Create a new user-visible version only when the fix cannot be made safely in place. If that happens, identify the final workflow and offer cleanup of obsolete copies.

## Alteryx Migration Cleanup Done

This applies when cleaning, optimizing, or standardizing a Savant workflow converted from Alteryx.

Required:

- Migration signals were identified using `alteryx-migration-cleanup.md`; broad cleanup was confirmed when not explicit.
- A rollback/export snapshot was captured before changes.
- Unsupported hidden or migration-only config fields were removed, or none were found.
- Disconnected nodes, dangling paths, and no-op artifacts were removed or preserved with a business reason.
- Column pruning was pushed as early as safe, including source field selection on wide schemas; shared-usage risk was checked.
- Savant-native replacements were verified against row counts, schema, and sample rows.
- Blend/Stack simplification proved row preservation before dropping unmatched rows or switching to an inner join.
- Final output row count, schema, and key business fields were preserved unless the user approved a change.
- Layout passed the deterministic layout checks (`savant.py validate workflow`) when visual/layout cleanup was in scope.
