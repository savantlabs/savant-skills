# Alteryx Migration

Use this solution when the user uploads or names an Alteryx workflow (`.yxmd`, `.yxwz`, `.yxmc`, `.yxzp`), asks to migrate, convert, replicate, port or "move" an Alteryx workflow to Savant, asks what an Alteryx workflow does, wants a migration plan, SOP or checklist, or wants to check a migrated flow against Alteryx. Trigger even on "yxmd", "yxzp", "Designer workflow" or "we're replacing Alteryx".

It is a domain solution within Savvy: it owns the Alteryx intake, the tool-to-step mapping, the priority rules, and the **migration guide** it produces. Building the flow is Savvy's own **author** mode; validating and cutting over use **applier** and **inspect**. Do not improvise a separate build path.

Two Alteryx documents exist in Savvy. This one is for a **new** Savant flow built from an Alteryx workflow. Cleaning up a flow that was *already* converted (orphan nodes, Blend-plus-Stack leftovers, hanging previews) is `../../references/standards/alteryx-migration-cleanup.md`, reached through applier's edit path.

## What this solution produces

**One output: the migration guide** for a flow (`<flow>.migration-guide.md`, structure in `references/output-template.md`, filled example in `references/example-guide.md`). Page 1 of the guide is what most readers see: business description, coverage headline, P1 blockers, P2 decisions, progress line. Everything else is appendix. `references/priority-rules.md` decides what goes on page 1 — not judgment in the moment.

Alongside the guide, the solution hands author mode a **numbered step plan** (S1…Sn) and a naming contract, then records what author, applier and inspect found back into the guide.

## Workflow

### Phase 0 — Intake (one turn)

1. **Locate the file.** Use the Alteryx file the user attached or named: a local path in a terminal runtime, or the runtime's uploads folder in a desktop chat runtime. `.yxzp` is a zip; the parser unpacks it and treats bundled `.yxmc` as macros of the primary workflow. `.yxwz` is an analytic app; its interface tools (File Browse, Drop Down, Action, Tab…) map to how the dataset or a parameter gets supplied, not to steps.
2. **Parse.** Run the bundled inventory command (see the Toolchain section of `SKILL.md` for how to invoke `savant.py`):
   ```sh
   savant.py alteryx parse <file> --markdown "$(savant.py session tmp-path alteryx <stem>.inventory.md)"
   ```
   With no `--out` the JSON lands at `savant.py session tmp-path alteryx <stem>.inventory.json`; the command prints both paths and the coverage headline. Output: tools with config summaries and Savant mapping, connections, checkpoints with grain keys and priority, traps, dead-code findings, dependencies, coverage headline. If the command is missing, the toolchain isn't installed — say so and stop; never hand-build an inventory from the XML.
3. **Reply in business language:** what the workflow does (who runs it and when → inputs → rules → outputs → who uses them; the inventory's `notes` carry the workflow's own Text Box comments, often the owner and cadence), the tool table, the coverage headline **naming unsupported tools with their IDs**, and the P1 list. Before listing P1, check the current workspace read-only (MCP `search`/`locate`) for datasets or connections that already match the inputs; "dataset missing" is only P1 when nothing matches. Traps and dead code wait for the appendices.
4. **Ask the intake questions together** (tappable options where available): source (real connection / dummy or snapshot first); destination — name **each** Alteryx output (files, publishes, macros) and ask where each lands, so "both outputs" can never be ambiguous; behaviour (match Alteryx exactly — default — or apply P2 defaults); target workspace **and folder** (the workspace must come from the user's own words; author's create path resolves the folder id); documentation depth (state the default — a migration guide is governed documentation, so the flow is documented in detail — and let the user confirm or choose light; that confirmation is the `user_answer` evidence); and any grain keys the parser could not infer. If the named folder does not exist in the workspace, say so and ask whether to create it in the app or pick an existing one; Savvy never creates folders and never silently falls back to Home for a folder the user named.

### Phase 1 — Guide draft

Write the guide from the inventory with `references/output-template.md`:

- **What this workflow does** — first section, from step 3 above, plus one sentence on how the Savant flow will do it and any deliberate change.
- **Page 1** — coverage headline; P1 from `tools[].p1`, missing connections, unsupported outputs, code tools, loops, "baseline not captured", and one dataset-configuration row per Input tool taken from the inventory's `dataset_configs` (charset, delimiter, columns to keep as text, and the ready `suggested_command`; a `charset_note` is quoted in the row, and `p1: true` there means the code page has no Savant charset and the file must be converted first); P2 from cross-branch inconsistencies, integer truncation, sort-dependent aggregations, single-input substitutions, null/blank/case choices, tolerances — each with a default, ⚠ when the default changes Alteryx behaviour, and an *Applied in Savant flow* column (`yes` when the faithful build already implements it; `yes (faithful)` when the owner declined a ⚠ default and step 17 stays optional; `step 17` when a ⚠ default was accepted for after sign-off; `open` only when the value can only be read from the baseline).
- **Page 2** — the 17-step checklist from `references/checklist.md` with statuses and the runbook block.
- **Appendix A** — checkpoints of priority ≤ 2 from `checkpoints`, a "Deliberate non-matches" block, and how to capture the baseline (`references/validation.md`).
- **Appendix B** — the traceability map. Define the business rules R1…Rn **once**, in a list at the top of Appendix B (one per distinct data rule, not per tool), and use those same numbers everywhere else in the guide — Appendix A's row notes, P2 rows, step descriptions. Never renumber in another section. Number the Savant steps **S1…Sn in execution order** and use the same numbers as the prefix of each step name in the flow (`S4 · Keep one record per building per quarter`). One row per Alteryx tool or tool group; every Savant step appears; steps the solution adds (blank-safe keys, technical constants) get mapping `added`. The Note column carries the behaviour difference handled at that step — see the trap list below.
- **Appendix C** — P3 cleanups from `dead_code`.
- Macros per `references/macro-handling.md`: standard → built-in steps; custom `.yxmc` → inlined per call site (mapping `inlined macro`); iterative/batch → P1 with a redesign sketch; output macros → P1 unsupported destination.

Present the description, page 1 and the numbered step plan in chat; confirm P2 defaults and the folder before building. Publish the guide as a document the user keeps (Markdown artifact or file, per the interface).

### Phase 2 — Build (author mode)

Continue in `../../references/skills/author.md`. The guide **is** the confirmed plan: do not re-run author's plan-depth or process questions, and do not re-gate the build — the user approved page 1 and the step plan in Phase 1. Author's handoff file is still written and validated, filled from the guide:

| Guide element | `planner_to_builder` field |
|---|---|
| Business blocks (Appendix B groupings) | `workflow_plan_checkpoint.process_blocks[]` — block title = business block name; `business_purpose` = the rules the block applies; `business_steps` = the S-numbered steps in that block |
| S1…Sn step plan | `workflow_plan_checkpoint.process_steps[]` |
| P2 rows | `workflow_plan_checkpoint.material_decisions[]` — `rationale` is `user requested` when the owner chose it, `user approved assumption` when a default was accepted |
| Deliberate non-matches (Appendix A) | `workflow_plan_checkpoint.material_assumptions[]` |
| Intake answers on source and destination | `input_dataset_plan.sources[]`, `output_destination_plan.outputs[]` |
| Documentation depth | `process_metadata.documentation_mode` = `detail` (or `light` if the user chose it at intake), `process_metadata.documentation_mode_source` = `user_answer`, `documentation_mode_evidence` = the intake confirmation |

**Naming contract (build instruction).** Name every step `S<n> · <business action>` using the guide's numbers, and begin every description with the business action followed by the Alteryx tool IDs and rule numbers it replaces, e.g. "(rule R9, Alteryx Formula 49 + Select 41)". Group names match the guide's business blocks. This is the sanctioned migration exception to the label rules in `../../references/standards/node-documentation-rules.md`; the S-number is the join key between guide, flow and the conversation with the owner. Build the faithful flow first; ⚠ P2 changes are checklist step 17.

**Lessons from live migrations** (carry these into the build):

- Keys that can be blank (Unique fields, Join keys, nullable group-by fields) need blank-safe key columns (`COALESCE(TO_TEXT(x), "")`) in source prep — a Savant match on NULL never matches, Alteryx's does. Found live: it silently lost 2 of 7 duplicate rows. This replaces the default `UPPER(TRIM(TO_TEXT(...)))` key normalisation for those keys when the guide says Alteryx compared them raw; record the choice as a P2 row.
- Dataset configuration is part of the migration and the toolchain does it at create time: run the inventory's `suggested_command` per input — `savant.py dataset create --file … --delimiter ';' --charset WINDOWS_1252 --column-type Customer_ID=string,Invoice_No=string`. `--charset` is the server's name (`UTF_8` or `WINDOWS_1252`; Alteryx code page 28591/1252 → `WINDOWS_1252`, 65001 → `UTF_8`, anything else → convert the file first) and `--column-type` fixes a column's logical type *before* inference so leading zeros survive. The same keys (`charset`, `types`) work per item in a `--manifest`. The command prints a warning if the stored type differs from what was declared; treat that warning as a P1 not yet resolved. Inference cannot be undone after creation, so never create the dataset without these flags and fix it later.
- The validator rejects two adjacent Transforms — fold LAG/window ops, coalesces and hides into one step. IF/CASE need literal branches; use `flag × value` or `COALESCE`.
- A node feeding two groups makes connectors cross a group frame; give each group its own small summarize/rank chain.
- The layout solver can take minutes on 15+ nodes; build without layout for schema checks, polish once at the end.
- Dummy data, when the real source isn't available: exact source column names and types, rows exercising every rule (each filter branch, a duplicate key, a blank key, a blank measure, a missing period, a dropped and a new entity, each special status). List which rows exercise which rule in Appendix A's Result column.

Creating the flow live is applier's create path, reached from author as usual. After import, run inspect in analyze mode, fetch the output rows, and record the spot checks in Appendix A and the checklist evidence. If a rebuild is needed, use applier's rebuild-in-place on the same flow, never a second import.

### Phase 3 — Validate and cut over

Follow `references/validation.md` for baseline capture and comparison, `references/checklist.md` for steps 9–17. Classify every difference as *intended* (cite the P2 row) or *defect* (name the S-step). Update the guide's checklist statuses and progress line as steps complete. A reconciliation flow that compares the Alteryx baseline export with the Savant output is an ordinary author build when the user asks for it.

## Trap list (for Appendix B notes and P2 rows)

Integer typing truncating decimals · FixedDecimal scale rounding · `!=`/`<>` dropping NULLs · Summarize First/Last depending on sort · Multi-Row first-row value · Cleanse macro options differing by branch · case-sensitive untrimmed join keys · blank keys (Alteryx equal, Savant never) · Unique *Duplicates* anchor = 2nd+ occurrences only · Append Fields cartesian · Union by position · string literal with embedded line break · Date vs DateTime compare · V_WString(254) truncation · Select `*Unknown` unchecked dropping new columns · CrossTab header sanitising · file encoding (code page ≠ 65001) · headerless input (positional Field_n) · dataset type inference stripping leading zeros (Select forcing text, id-like text inputs) · run-date dependency (`DateTimeToday()`/`Now()` — pin the as-of date to the baseline run date for the comparison). The parser detects most of these (`traps`); the guide states how each was handled at the S-step that handles it.

## Style

- Business language first; "step", "group", "match", "stack" — not node/blend/multi_stack.
- Be exact about what was verified: "built, not run", "verified on dummy data", "compared with baseline dated …" are three different claims.
- Deliberate non-matches are always listed under Appendix A, never hidden in prose.
- Never copy credentials, tokens or PAT names from macro parameters into a guide; the parser drops keys matching `password|token|secret`, and for output macros drops every free-text slot (keeping only URLs and drop-down choices). The guide must not reintroduce them from the XML. Non-secret settings the redaction removed (project, data source name) come from the tool annotation or the owner.

## Files

- `savant.py alteryx parse` (`../../scripts/alteryx/parse.py`) — inventory, checkpoints, traps, dead code, dependencies, coverage. Edit `references/tool-mapping.json` to extend tool coverage or P1 rules; unknown tools fall to `review` and surface as P1.
- `references/output-template.md`, `priority-rules.md`, `checklist.md`, `validation.md`, `macro-handling.md`
- `references/example-guide.md` — a fully populated guide on a fictional office-vacancy workflow

## Known limits

- About 60 Alteryx tools and 7 macro patterns are mapped; spatial, predictive, reporting and connector-specific tools fall to `review`.
- Grain-key inference propagates the nearest upstream Unique/Summarize grain along the driving (left) stream, falling back to Join keys only when no grain exists upstream; when none exists above an output the keys are empty and the intake asks for them.
- Bundled custom macros are classified but not yet expanded into the parent inventory; inline them by hand per `references/macro-handling.md`.
- Alteryx formulas are recorded verbatim; translating them into Savant expressions happens at build time.
