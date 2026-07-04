# Planner -> Builder Handoff Map

Template note: intentionally exempt from the full template; this is a compact field map.

Use this to translate a validated Planner handoff into Builder inputs without re-planning. Route back to Planner only if the handoff is missing, inconsistent, or changed by the user.

Planner writes the handoff with `savant.py handoff scaffold planner-to-builder --task "<task-name>"`; Builder reads the printed session-scoped path as the business contract for JSON generation.

The **exact evidence shape** is owned by the handoff scaffold and stage gate, not this prose file. Use the compact handoff packet while filling the handoff so agents do not need to read validator source for array-item rules:

```bash
savant.py docs handoff-pack --scope build_only
HANDOFF="$(savant.py handoff scaffold planner-to-builder --task "<task-name>")"
savant.py validate stage --role planner --gate done "$HANDOFF"
```

Scaffold the boilerplate, fill it using the handoff packet, then validate. Do not hand-type the evidence skeleton from memory; the handoff scaffold is the current validator contract.

## Builder Consumption Map

- `input_dataset_plan.sources` -> source units. Each source follows the source-plan contract in `../scripts/contracts/source_plan.py`: workflow intent plus a nested dataset binding/profile. Builder does no discovery, binding, or schema inference.
- `output_destination_plan.outputs` -> destination plan. Each output follows the output-destination contract in `../scripts/contracts/output_destination.py`. Builder generates only supported destinations through `destination_from_plan(...)` and follows any confirmed CSV fallback.
- `process_metadata` -> workflow descriptions, delivery notes, controls, review/escalation context, and operating notes where relevant.
- `workflow_plan_checkpoint.process_blocks` -> visual groups in order. Block titles become group titles (business object + action, not component words or vague stage names); `business_purpose` becomes the group's on-canvas description (the logic and its exact thresholds, 1–2 sentences); `business_steps` guide node decomposition and seed each node's business-action label. Builder applies the label/header standards in `../../references/standards/node-documentation-rules.md` — group headers/descriptions render as canvas rich text, not Markdown.
- `workflow_plan_checkpoint.material_assumptions` -> behavior notes in workflow/node descriptions or delivery notes when they affect interpretation.

Both `light` and `detail` documentation modes are valid because they share this handoff. `detail` can enrich descriptions, controls, audit notes, and review outputs, and it requires governance metadata. For `build_only` + `light`, owner, cadence, escalation, and approval metadata may remain unfilled unless the process itself needs them.

Builder must not re-ask planning questions already confirmed here unless the handoff is missing, internally inconsistent, or the user changes the requested process.
