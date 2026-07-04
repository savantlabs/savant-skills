# Savant Workflow Author (author mode)

> **When this mode applies:** the user wants to build a new data-automation flow from a process they describe — "build me a workflow that…", "design a process to…", "turn these files into a Savant flow." Author owns two phases: (1) agree the business process in plain language and confirm it; (2) map the confirmed plan to standard Savant components and produce one validated workflow definition. Author itself is **offline and deterministic** (no live API, never imports or runs), but it is **not the end of the journey**: when the live API is available it hands the validated definition to **applier mode**, which creates and verifies the flow live — so the user gets a working flow, not a file. The workflow-definition artifact is internal plumbing; it surfaces to the user only when there's no live API or the user explicitly asks for the file.

## Goal

Author takes a user from "I have a process in my head (and maybe some files)" to **a working, verified flow in their Savant workspace**. It runs in two phases:

1. **Plan** — agree what the workflow should do in plain business terms: inputs, output, grain, source-of-truth rules, exception handling. Confirm it explicitly before building.
2. **Build** — map the confirmed plan to the fewest sensible Savant components, generate each node with the Builder API, assemble and group the flow, and write one validated workflow definition.

Author is **offline and deterministic**: it does not mint API credentials, import, run, or inspect anything live — that is **applier mode**. But the *user's* journey is continuous. The validated workflow definition Author produces is an **internal artifact**, not the user-facing deliverable: when the live API is available, the confirmed plan flows straight through Build into applier-create, and the flow is made real and verified without the user ever choosing "definition or live." Do **not** offer "do you want the JSON, or shall I create it live?" as a user choice — that internal seam stays hidden (see "Hand off to live creation" below). The workflow definition surfaces to the user **only** when the live API is unavailable (then the file *is* the deliverable) or the user explicitly asks to export/download/back it up.

Write all user-facing replies with the business-user response rules loaded at session start.

## Before You Start

`savant.py ...` is shorthand for the bundled toolchain; the parent `SKILL.md` Toolchain section explains how to locate and run it.

Author is offline, so it does not need API credentials. It still reads the shared capability snapshot to decide whether dataset *discovery* is available: resolve the path with `savant.py session tmp-path savant-capabilities.json`, read it, and use its `api_enabled` value. If the file is missing, refresh it with `savant.py capabilities --output-path <resolved-capability-path>`. When `api_enabled` is false, Author asks the user for Savant dataset ids instead of discovering them.

The internal commands this skill uses are: `savant.py source profile`, `savant.py handoff scaffold`, `savant.py validate stage`, `savant.py registry summary`, `savant.py docs handoff-pack`, and `savant.py docs builder-pack <components...> --no-frame`.

## State tracking — the two handoffs

Author tracks its own state in handoff files; the Plan→Build boundary is internal to this one skill, but the validators still gate each phase.

- **`planner_to_builder.handoff.json`** — Author's *internal* state tracker. It records known preferences/facts, answered/remaining questions, the confirmed source and output plans, and the confirmation evidence. The Plan phase fills it and passes the `--role planner` gates; the Build phase reads it and passes the `--role builder` precheck. It is no longer handed between skills — it is how the two phases of this skill agree.
- **`builder_to_creator.handoff.json`** — the **real** inter-skill contract. When the user wants the flow created in Savant, Author writes this handoff (workflow JSON path, optional schema-hints path, required tracking tag, requested scope) and passes it to **applier mode**.

Always use scaffolds; never hand-type the evidence skeleton from memory.

---

# Phase 1 — Plan

## Plan Procedure

1. **Create and confirm the plan.** Ask the needed business questions, resolve the input datasets, define the output, present the plan, and revise until the user explicitly approves it.
2. **Record Build-ready evidence.** Fill the `planner_to_builder.handoff.json` with the confirmed plan, source plans, output plan, and evidence. After the handoff is composed, re-read it against each `workflow_plan_checkpoint.material_decisions[]` entry and set `reflected_in_handoff: true` only when the handoff implements that approved decision and adds nothing material beyond the approved decisions. Then validate through the planner `done` gate before moving to Build.

## Conversation Rules

- Translate internal labels into business language. Do not ask the user to choose `delivery_path`, `documentation_mode`, `questions_needed`, `ready`, source binding, or checkpoint fields.
- Ask one clear business question at a time.
- Ask only questions that affect the process plan or the build.
- Ask about input data only when the answer changes the process plan or the build.
- Treat owner, cadence, escalation, and approval facts as draft assumptions unless they affect the build or the user wants governed process documentation.
- Do not ask the user about Savant components or node choices; Author chooses those in the Build phase.

## Create and Confirm the Plan

- **Ask the plan-depth question first.** Find out whether the user wants a short working plan or a fuller process document. Documentation depth must come from a reusable preference or an explicit user answer. Do not infer it from a broad request to build or create a workflow.
- **Use the handoff as the state tracker.** Create `planner_to_builder.handoff.json`, record known preferences/facts, answered questions, remaining questions, source plans, output plan, and confirmation evidence there, then run `savant.py validate stage --role planner --gate precheck`. If it is still at `questions_needed`, ask the next required business question. Continue when it is `ready`.
- **Capture the business process.** Include workflow name, business outcome, source roles, output purpose, row grain, source-of-truth rules, exception/review flags, process steps, and business blocks. Business blocks become Builder group titles and `business_steps` seed the node labels Builder writes, so phrase them the way the user would. A good group title names the **business object and action** ("Match statement charges to GL postings", "Classify reconciled and exception items", "Produce reconciliation reports"); it avoids both technical component words (join, filter, transform, rank, stack, source, destination, node, schema) **and** vague generic stage names ("Match the records", "Classify the items", "Produce the outputs"). Each block's `business_purpose` becomes the group's on-canvas description, so write it as the **logic or reasoning** — the rule and its exact thresholds, not a step list — in 1–2 sentences (e.g. "Matches charges to GL postings when the vendor matches, the amount is within $0.01, and dates are within 5 days; if several qualify it keeps the closest and prevents reusing a line twice."). See `../../references/standards/node-documentation-rules.md` for the label and group-header standards.
- **Surface and confirm material decisions.** A material decision is any choice that changes what the workflow does to the data — AI use, fuzzy matching, normalization strategy, thresholds, fallback logic, ranking/tiebreaking, one-to-one match rules, source-of-truth precedence, exception categories, output grain, audit fields (see `../../references/standards/material-decisions.md`). Present every material decision to the user in business language as part of the plan; do not approve one thing and hand the Builder another. Record each in `workflow_plan_checkpoint.material_decisions[]` with its `decision`, a `rationale` for why it was made (e.g. `user requested`, `user approved assumption`, `complex text processing`), and `reflected_in_handoff` (left for the post-handoff self-review). AI use is one material decision among equals — disclose it plainly, never behind a vaguer term like "normalized." Decide AI vs deterministic *before* presenting the plan: prefer deterministic logic for limited, stable, definable rules (thresholds, date tolerances, formulas, known mappings, fixed categories) and AI for messy, meaning-based, or open-ended inputs. Use AI when Savant requires it to read unstructured documents (PDF statements, invoices, scanned forms) or when input variation is too broad for rules to be practical (vendor normalization, sentiment, free-text classification); for that second, *chosen* case the `rationale` must say what the AI does and why it beat the deterministic alternative.
- **Resolve the input datasets.** Read `../../references/substrate/dataset-substrate.md` for the exact dataset commands. Use `search(types=["source"])` to find existing datasets and turn a name into its id (filter hits by `namespace`); if a user-provided local file is missing from Savant, ask whether to create it with `savant.py dataset create` (creation needs `api_enabled`).
- **Profile supplied files before source planning.** When the user provides local CSV, Excel, or PDF files, run `savant.py source profile --file <path> [--file <path> ...] --output-path "$(savant.py session tmp-path "<task-name>" source-profile.json)" --brief-output-path "$(savant.py session tmp-path "<task-name>" source-profile-brief.json)"`. Record those paths in `input_dataset_plan.profile_evidence` with `local_files_provided: true`. Read the brief first for readiness, sources, date adapters, safe joins, derived-key hints, AI-review joins, and warnings; open the full profile only when you need detailed schema/sample evidence. Use observed schema, date hints, conservative `suggestedJoins`, PDF/binary-document marker, and warnings while filling source plans. Treat `derivedKeyHints` and `aiReviewJoinCandidates` as unconfirmed leads only; AI or the user must confirm them before the Build phase uses them as join keys. Do not manually rediscover columns or joins when this report already has the evidence. When no local files were supplied, set `local_files_provided: false`.
- **Delegate ambiguous file profiling through hints.** If the profile report has `status: "needs_ai_profile"` or `readyForSourcePlanning: false`, inspect only the named sheet/file ranges in `aiProfileRequests`, write a hints JSON under the task tmp directory, and rerun the profiler with `--hints-json <hints.json>`. Do not fill source plans from an ambiguous profile. Store the rerun report path in the handoff.
- **Build one valid source plan per input.** Do not invent dataset ids. Use local file/profile evidence when the user supplied files; do not reduce that case to `id_only`.
- **Define the output plan.** Confirm each final output separately, including its business purpose, final columns in order, row grain, required verification checks, and how the business user will use it. Generated workflows support **native Savant CSV** and **file destinations to a connected system** (OneDrive / Google Drive, CSV or Excel) — see `../../references/components/destination.md` and `../../references/substrate/system-substrate.md`. A file destination must bind to a system the user has already connected. For other destinations (S3, SharePoint, SFTP, Box, email), record a CSV fallback when the user asked for an unsupported destination.
- **Normalize obvious ambiguous percent metrics.** If the user writes a likely typo such as `Return date (%)` in a context that clearly asks for total items vs. returned items, record the output metric as `Return Rate (%)` and record the assumption in the plan. If the surrounding context does not make the denominator obvious, ask one short clarification instead of guessing.
- **Present and confirm the plan — this approval also authorizes go-live.** Show the plan in business language and revise until the user explicitly approves it. Frame the confirmation so approval covers building *and* creating it in their workspace — e.g. "Here's the plan… I'll build this and create it in your Savant workspace — go ahead?" Do not pose a separate "stop at the definition, or create it live?" choice. When the user approves, continue into Build and on into live creation (see "Hand off to live creation"). The user may still choose to stop at the plan if they say so; honor that, but don't prompt for it.

## Validate the plan (planner gates)

```bash
HANDOFF="$(savant.py handoff scaffold planner-to-builder --task "<task-name>")"
savant.py validate stage --role planner --gate precheck "$HANDOFF"

savant.py docs handoff-pack --scope build_only
savant.py validate stage --role planner --gate done "$HANDOFF"
```

- `docs handoff-pack` is the compact contract for filling `builder_preflight`: source-plan object shape, output object shape, process-block shape, confirmation evidence, and scope-relevant metadata.
- Evidence that proves user choice must cite an explicit answer, approval, selection, choice, or provided value. Do not use broad phrases like "user asked to create" as approval evidence.
- When a required question is answered, keep the original item in `open_questions` and add the answer to `answered_questions`; the validators use both as the audit trail.
- Common preflight rules: `process_metadata.documentation_mode_source` must be exactly `user_answer` or `reusable_preference`; owner, cadence, escalation owners, and approval fields are required only for detail/governed handoffs or create/import scopes; every `workflow_plan_checkpoint.process_blocks[].title` must appear verbatim in `workflow_plan_checkpoint.plan_presented`; every `workflow_plan_checkpoint.material_decisions[]` entry needs a non-empty `decision` and `rationale`, and `reflected_in_handoff` must be `true`.

## Plan Formats

Present plans as business-readable Markdown. Do not use a Mermaid diagram, ASCII diagram, Savant canvas sketch, component list, or node-by-node implementation plan.

For a **short working plan**, include: process name; inputs and the business role of each input; output purpose, destination plan, final grain, and final columns when known; numbered business process steps; business blocks to preserve as groups; key assumptions or unresolved optional items; unsupported-destination fallback, if any; final confirmation question.

For a **fuller process document**, include everything in the short working plan plus relevant: owner, cadence, escalation, and approval expectations; operating details; success criteria; exception handling; roles and review steps; controls or audit evidence; maintenance expectations; training or handoff notes.

## Preference Memory

Offer to remember only stable planning preferences after the user chooses them, such as default documentation depth, approval handling, cadence handling, or preferred question style. Do not store workflow-specific facts such as dataset names, join keys, calculations, owners, or customer-specific escalation paths unless the user explicitly says they are reusable defaults.

Use native memory only when available and explicitly approved by the user. Do not create project-local memory files or hidden preference stores.

---

# Phase 2 — Build

Enter the Build phase only after the plan is confirmed and `planner_to_builder.handoff.json` passes `savant.py validate stage --role planner --gate done`. The Build phase never re-asks planning questions unless the plan is missing, inconsistent, or the user changes the process.

## Build Procedure

1. **Pre-check the plan.** Run `savant.py validate stage --role builder --gate precheck <planner_to_builder.handoff.json>` before generation. If it fails, return to the Plan phase with the gate error; for stale or missing structural fields, regenerate the handoff with `savant.py handoff scaffold planner-to-builder`, fill it with `savant.py docs handoff-pack --scope <requested_scope>`, and revalidate.
2. **Identify the component sequence.** Map the confirmed process blocks to the fewest sensible Savant components. Use `savant.py registry summary` when the component choice is unclear; it is the AI-facing component catalog.
3. **Identify each component's config.** Request one packet for all selected components: `savant.py docs builder-pack <components...> --no-frame`. Read the packet's Builder cookbook before opening any source code; it carries canonical snippets for common joins, derived keys, count flags, AI JSON extraction, and multi-output reports. The component sections tell you what the component does, which builder function to call, important config facts, invariants, gotchas, and what to do for components that should not be generated directly.
4. **Build each node with the Builder API.** Use the API signatures, constructor names, and build guidance returned by the step-3 builder packet. Do not hand-author JSON for components with constructors. If the packet says a component has no verified constructor or should not be authored directly, follow that guidance.
5. **Assemble the workflow.** Create `Flow(...)`, add source nodes from the source plans, add transformation nodes in business-process order, add destination nodes from the output plan, then link everything with `wire(...)`, `chain(...)`, `blend_outlet(...)`, or `filter_outlet(...)` so the workflow solves the planned business problem.
6. **Group and document.** Group nodes according to the plan's business blocks with `Flow.group(...)`; write workflow, group, and node descriptions/settings while building. Layout is automatic — the deterministic auto-layout positions and lanes the flow, and `write_workflow` prints a measured `layout:` line. Do **not** pre-read the layout rules as routine; read `../../references/standards/canvas-layout-rules.md` only when that line reports a connector-through-node/group or overlap defect to fix.
7. **Validate and write.** Save the final workflow with `nb.write_workflow(flow, planner_handoff=planner_to_builder_handoff_path, schema_hints=hints_if_needed)`, defaulting under `tmp/<ai-session-id>/<workflow-slug>/<Workflow Name>.json`. `write_workflow(...)` reruns the Builder precheck gate internally and refuses to emit JSON if the Planner handoff is missing or blocked. (For an already-materialized workflow JSON, `savant.py workflow polish <workflow.json>` re-runs the same layout/color mechanics.) Create `builder_to_creator.handoff.json` with `savant.py handoff scaffold builder-to-creator --task "<task-name>"`, record the workflow JSON path, optional schema hints path, required tracking tag, and requested scope in that handoff, then run `savant.py validate stage --role builder --gate done <builder_to_creator.handoff.json>`. Fix every validation error or warning before returning the artifact.

## Build Rules

- **Create sources and destinations from the handoff objects.** To create a source unit, pass the current flow and the full source object from the handoff to `source_unit_from_plan(flow, source_plan)`. To create a destination node, pass the full output object to `destination_from_plan(...)`. Do not unpack source/destination fields by hand unless the packet says the constructor cannot support the case.
- **Preserve one destination per planned output.** Each `output_destination_plan.outputs[]` entry carries its own expected grain, expected columns, and verification checks. Build and name destinations so the applier can verify each output separately; do not collapse multiple planned outputs into one destination unless the user approved that change.
- **Let source profiling evidence flow through the library.** File/spreadsheet sources get profiling evidence automatically from `dataset.observed_schema` and optional `dataset.row_count`; never hand-inject source `fields` or `rowCount`.
- **Optimize the process shape by default.** Build the fewest, strongest steps and groups that do the work; do not add nodes or groups for readability alone. Builder validation blocks strict adjacent Transform/filter pairs that should be one step — merge them before handoff. Add a separate step or group only for a real business boundary, a branch, a reused/checkpointed result, a distinct operation type, or an explicit user request.
- **Use multi-operation components instead of extra nodes.** Some components can do several related operations at once. For example, one `edit` node can rename columns, reorder columns, hide columns, and add calculated columns; one `filter` node can hold multiple conditions. Transform edits are ordered, so a later calculated column may reference a column created or replaced earlier in the same Transform when the `ops` list is in dependency order. Use separate Transform nodes only when the business process is clearer as separate steps, a result is reused across branches, or the split materially helps review.
- **Filter and trim as early as business-safe.** Push filters and column trims toward the source — as soon as the rows/columns are not needed downstream — so later steps operate on the smallest correct dataset.
- **Do data prep at the first stable point.** Clean names, types, dates, amounts, and join/group keys immediately after the adapter/extraction/parser and before filters, joins, summaries, pivots, or destinations, so later steps operate on consistent fields. Normalize join keys per `../../references/standards/data-prep-normalization.md` (default `UPPER(TRIM(TO_TEXT(...)))`); do not defer cleanup that the source already makes possible.
- **Trim columns when the business need is known.** When the output plan declares expected columns, add a `keep_only_columns(flow, upstream, "Keep ... columns", expected_columns, ...)` Transform before the destination or before the shared branch feeding multiple destinations. When a wide source carries fields that are clearly not needed for any downstream logic, audit trail, or output, trim them earlier too. Do not rely on `order=` alone; `orderedFields` reorders but does not drop. Leaking extra passthrough columns to a destination is a workflow quality defect because it can break the output contract, slow previews/runs, and make the delivered file harder to review.
- **Describe and label everything, following `../../references/standards/node-documentation-rules.md`.** Always include a workflow description, a label and description for every node, and both a header and description for every group. Each node **label** is a short business-action phrase a reader understands before opening the step ("Find possible GL matches", "Choose best GL match", "Keep final one-to-one matches"), not a component name (Transform, Filter, Blend, Stack, Output). Each node **description** is a node-type-specific readout of its configuration in business language (formulas only for calculated fields/formula rules). Write the workflow description as ONE paragraph of business summary — `write_workflow` appends the approved plan body automatically and refuses to emit a workflow whose description does not include it; do not paste the plan in yourself or overwrite the appended `## Process` section.
  - **Node and workflow descriptions are Markdown** (the Description panel renders Markdown — `**bold**`, `*`/`-` bullets, headings, backtick `code`; HTML there shows as literal text). Builder done-validation promotes missing descriptions and node-documentation gaps to errors.
  - **Group headers and descriptions are canvas rich text, NOT Markdown.** Pass them as `header=`/`description=` to `Flow.group(...)` as plain business text; `**bold**` would render literally as asterisks. Use real line breaks (`\n` in the description) to separate dense clauses — Builder renders each line on its own — and numeric thresholds (`$0.01`, `5 days`, `5%`) are emphasized automatically. Do not hand-write HTML; the builder produces it.
- **Save the final workflow with `nb.write_workflow(flow, planner_handoff=planner_to_builder_handoff_path)`.** This reruns the Builder precheck gate, validates the workflow, and avoids manual JSON-writing mistakes. If AI output schema hints are needed, pass them as `schema_hints=...`; the library writes the `<workflow>.schema-hints.json` sidecar next to the workflow for copy-paste re-validation.

## Component Build Checks

Apply these checks while building the selected components:

- Do not hardcode aggregate denominators; compute needed totals dynamically upstream.
- Keep dependent Transform calculations in dependency order within the same `edit_node`: create or replace the prerequisite column first, then create the later column that references it. Do not reference a field before the edit that creates it.
- After left joins or optional enrichments, build count-style measures as row-level 0/1 indicators with `op_count_if(...)`, then `SUM` those indicators in `summarize`. If a nullable numeric field should aggregate as zero, first create a cleaned field with `op_default_constant(..., 0, dt="number")`.
- Before `pivot`, drop passthrough fields that should not become grouping keys.
- Before every destination with a known expected schema, verify the upstream schema with `flow.schema_at(...)` and use `keep_only_columns(...)` unless the upstream schema already exactly matches the output contract. If validation reports columns outside both `orderedFields` and `hiddenFields`, fix the workflow; do not explain it away for final outputs.
- Use `sample` with `groupBy` only when the business wants top-N per group, not top-N overall.
- Normalize join/group keys with a typed cast (`op_retype`/`op_cast` or an adapter `dataType`) before joining or summarizing; for string keys, prefer `op_normalized_join_key` (`UPPER(TRIM(TO_TEXT(...)))`) in source prep so both sides match deterministically.
- No node may ship with an unused output. If an output matters it feeds a destination; otherwise the node should not exist. Build an anti-join as a left join + null filter, not an inner join with a dangling unmatched fork.
- Multi-output tools are one rule: set the split flag on the **parent** (filter `false_path=True`; blend `left_unmatched=`/`right_unmatched=`) and wire each branch with the `filter_outlet(...)` / `blend_outlet(...)` handle. Do **not** author `{parent}|i` outlet nodes or wire a parent's `out_1`; a single-output tool (inner-join blend) wires straight from the parent. The toolchain builds the outlet children at finalize, so the structure is always correct.
- Wire a multi-input node's inlet order to match its sources' vertical order, so connectors enter without crossing at the junction.
- After a Blend, reference duplicate right-side fields by Savant's resolved names **on the main joined output**: non-key duplicates become `Field (rhs)` with exact live ids like `Field_2`; same-named right join keys are suppressed for inner joins and retained as `Field (rhs)` for left/right/full main outputs. Prefer display-name expressions such as `Field (rhs)`. In `hiddenFields`/`orderedFields`, use that exact display name (`Field (rhs)`), not a normalized guess like `field_2`. The unmatched-left and unmatched-right forks keep each side's original field names (no `(lhs)`/`(rhs)`) — only one side's columns are present, so no collision can occur there.
- Preserve business-friendly column display names such as `Document Date` and `Grand Total`; reference columns by that **name** everywhere — `hiddenFields`, `orderedFields`, `replaceTgt`, and expression refs — since the runtime resolves by name and real exports store names. Do not convert display names to underscore variants as a workaround: a derived id can mismatch the column's real internal id (e.g. `Last Updated (UTC)` → id `last_updated`) and silently no-op. The Builder API fills the one genuine id field, `tgtCol.id`, for you.
- Use current component names from `registry summary` / `builder-pack`; `join`, `stack`, and `transform` map to `blend`, `multi_stack`, and `edit`. `service` is legacy; follow the packet guidance and prefer `apiService` or `gen_ai` for new workflows.
- Recheck output grain before enrichment, summaries, and destinations.
- For `vision`, `gen_ai`, or `fuzzy_match` outputs referenced downstream, declare expected columns with `node_builders.schema_hints((ai_node, ["Column"]))` and pass them to `nb.write_workflow(..., planner_handoff=planner_to_builder_handoff_path, schema_hints=hints)`; attach hints to the AI node, not the upstream source and not a downstream JSON flatten node. For `gen_ai_json_flatten(...)`, use `node_builders.gen_ai_node_for_json_flatten(flow, flatten_handle)` to get the AI node id for hints. `--schema-hints` takes the sidecar file path, not inline JSON.
- For GenAI prompts that return JSON to be flattened, use `node_builders.gen_ai_json_flatten(...)` so the `gen_ai -> json(flatten)` wiring and generated-output field name are handled by the library.
- Before a `gen_ai` step reads optional text from a left join or other optional enrichment, add a small Transform that defaults missing text to an explicit neutral placeholder such as `No review provided.` and make the prompt state how to handle that placeholder. Do not feed raw nullable review/comment fields directly from a Blend into AI sentiment or classification.
- Build AI nodes (`gen_ai`, `vision`, `fuzzy_match`) only through the builder — never copy their config from an existing workflow export. The connector is derived from `providerId`; a copied `type`/`connector` key silently drops the whole node on import, and a `providerId` from another workspace does too. The validator errors on both before import, but the builder avoids them by construction.

## The tracking tag

The generated workflow carries a Savvy tracking tag recording the Savvy version that created it, e.g. `Savvy v0.0.1`. The builder sets this automatically — `nb.Flow(name)` defaults its tag to the canonical version (from `capabilities.tracking_tag`), and `compile`/`write_workflow` validate against that same versioned tag — so you don't pass `--required-tag` by hand. Keep exactly one Savvy-family tag on the flow. The applier's Editor refreshes this tag on any later edit.

---

## Hand off to live creation

Once the workflow definition validates and `builder_to_creator.handoff.json` passes the builder `done` gate, the default next step — when the live API is available — is to **continue into applier-create**, not to stop and hand the user a file. The plan the user already approved authorized this (see "Present and confirm the plan"); applier-create treats that approval as its create authorization and does **not** re-ask "do you want to create this?" as a fresh gate. Pass the `builder_to_creator.handoff.json` to **applier mode** and let it import, verify, and report the live flow URL.

Decide whether to continue or stop by `api_enabled` and explicit user intent:

- **`api_enabled: true` (the normal case):** continue into applier-create automatically. The user gets a working, verified flow in their workspace — the workflow definition is never mentioned.
- **`api_enabled: false`:** the workspace can't be reached, so the file genuinely *is* the deliverable. *This is the one place Author surfaces the artifact to the user* — explain plainly: "I can't reach your Savant workspace right now, so here's the workflow file to import yourself," give the path, and point them at the in-app import.
- **User explicitly asked to stop at the plan, or to just get the file / a backup:** honor it. Hand over the definition (or stop at the plan) without pushing to live.

Never frame the offline-vs-live boundary as a user choice in the normal `api_enabled: true` path.

## Done

- **Plan only:** done when the user confirms the process plan and `planner_to_builder.handoff.json` passes `savant.py validate stage --role planner --gate done`. (Use only when the user chose to stop at the plan.)
- **Full author (normal path):** Author produces a validated workflow definition from a passing plan (`savant.py validate stage --role builder --gate done <builder_to_creator.handoff.json>` passes), then hands off to **applier mode**, which creates and verifies the flow live. Done means the flow is real and verified in the user's workspace — not merely that a definition was written.
- **Full author (no live API):** when `api_enabled` is false, done is the validated definition plus a clear explanation that the user must import it themselves, with the file path.

Live import, run, visual verification, and "make it real in Savant" belong to **applier mode**; Author hands off to it rather than stopping at a file.

## Working with other Savant skills

- **applier mode** is the live counterpart: hand it the `builder_to_creator.handoff.json` to import the generated JSON into a Savant folder, verify it renders and runs, and (for an existing flow) edit in place. Author never imports or runs anything itself.
- **inspect mode** answers targeted questions about an existing flow's behavior; when the user points at a flow URL and asks what a node does, that is Inspector, not Author.
- **inspect mode** reads, exports, and explains an existing flow (JSON export + business summary, plus node-level inspection); useful when the user wants to rebuild from an existing flow (inspector export → author → applier).
- The **`../../references/components/` library** holds per-type build guidance. Read `{type}.md` before authoring a node of an unfamiliar component type, and consult the matching `../../references/registry/components/{type}.json` for enum/required-field facts.

## What not to do

- **Don't go live *yourself*.** Author is offline: no credentials, no import, no run, no inspection. Making the flow real is applier mode's job — but the default *is* to continue there (hand off the `builder_to_creator.handoff.json`), not to stop at a file. Author runs offline; the journey does not.
- **Don't surface the workflow definition as a user choice.** In the normal `api_enabled: true` path, never ask "do you want the JSON, or shall I create it live?" — continue into live creation. Surface the file only when the API is unavailable or the user explicitly asks for it.
- **Don't ask the user to choose components.** Plan in business language; choose components in the Build phase.
- **Don't invent dataset ids** or reduce a user-supplied-file source to `id_only`.
- **Don't hand-author JSON** for components that have a Builder constructor.
- **Don't persist a workflow without a passing plan.** `write_workflow` reruns the Builder precheck gate by design; do not route around it.
- **Don't infer documentation depth** from a broad "build me a workflow" request — it must come from a user answer or a reusable preference.
