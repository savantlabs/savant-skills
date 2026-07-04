# Canvas Layout Rules

## Objective

Use this to decide whether a Savant workflow diagram is understandable, trustworthy, and pleasant for a business user to scan.

This file is design guidance, not the geometry engine. Auto-layout and `savant.py validate workflow` own deterministic placement rules, spacing checks, group membership safety, and known layout defects — and they are the acceptance gate. The diagram is laid out entirely in the workflow JSON, so layout quality is judged from that JSON and its validation, not from a rendered view.

## Use When

- A skill creates, imports, wires, moves, groups, recolors, resizes, or organizes canvas nodes.
- The user asks whether a workflow diagram is readable, polished, or organized.
- `definition-of-done.md` requires layout quality to be verified.

## Default Action

1. Lay out the diagram with the builder/layout helpers (`Flow.group(...)`, auto-layout) as you generate or change the JSON — these encode the placement, spacing, grouping, and connector-corridor rules.
2. Run `savant.py validate workflow` and read its layout findings (the same checks `layout_metrics` measures: collisions, connectors routed through nodes/frames, bent single-in/out chains, inlet-order mismatches, terminal-output placement, canvas area).
3. Apply the design principles below to the JSON: business lanes, semantic stage grouping, side/exception branches below the main lane, clean connector corridors.
4. Fix every layout defect the validator reports before handing off; build and apply the smallest supported layout-only change. Ask only when the fix would change business logic, topology, group membership, colors, or text meaning.

Layout polish is always in scope for workflow creation/import. Do not ask for separate confirmation before improving the layout of a newly created workflow; the created workflow is not done until `validate workflow` reports a clean layout or a non-layout blocker is named. For edits to an existing workflow, layout polish is in scope only when the user asked for it or confirmed a layout-polish/optimization scope.

## Design Principles

The goal is not a perfectly uniform schematic. The goal is a process diagram that teaches the workflow at a glance.

- **Tell the business story.** A viewer should see the main input, main processing path, important side streams, branches, exceptions, and final outputs without narration.
- **Use semantic stages.** Groups should frame meaningful phases of work, not arbitrary rectangles around nearby nodes. Group titles, group descriptions, and node labels should read in business language — see `node-documentation-rules.md` ("Group Headers and Descriptions", "Step Labels"). Titles name the business object and action (not component words like join/filter/stack, and not vague stage names like "Match the records"); descriptions explain the logic and its exact thresholds.
- **Do not add structure for readability alone.** A clearer diagram is not a reason to split one capable step into several adjacent steps or keep a one-step group if that work naturally belongs to the surrounding business stage. Prefer fewer, stronger steps and groups by default; add extra stages only for real business boundaries, branches, reusable checkpoints, distinct operation types, or an explicit user request for readability-first separation.
- **Let layout express priority.** Primary paths, reference/support streams, exception paths, and outputs can have different visual treatment when it makes the story clearer.
- **Prefer clarity over cramped geometry, not over process simplicity.** Give the steps and groups that genuinely need to exist enough room to breathe. A slightly larger canvas is better than a cramped one, but extra nodes/groups are not a layout tool.
- **Use alignment as a tool, not a cage.** Rows, columns, and consistent spacing help users scan, but asymmetry is acceptable when it clarifies branching, review, or support paths.
- **Avoid false meaning.** Do not place independent inputs as if one feeds the other. Do not route connectors in ways that imply a dependency or sequence that is not real.
- **Make outputs easy to find.** Final delivery/output stages should read as the end of the process. The layout engine and validator enforce the common terminal-output placement rules; fix any reported issue rather than restating those rules here.
- **Arrange in 2D — don't force one horizontal row.** Be creative with placement. A workflow does not have to be a single left-to-right lane: drop secondary/side branches (QA, validation, reconciliation, exception handling) *below* the main lane, stack parallel terminal outputs vertically, and use rows when a flow is wide. The aim is the clearest story, not uniformity. The one firm constraint is the validator's: terminal output groups stay to the **right** of the final processing stage (any height is fine — just not horizontally *under* it).
- **Lane re-convergent taps.** When an early node feeds BOTH the main pipeline and a much-later consumer (an anti-join, an audit count, a validation tap), a straight connector from it will tunnel through every pipeline node between them — the worst readable-canvas defect (live incident 2026-06-10: 15 connectors through nodes; fixtures `tests/fixtures/layout/recon-tap-graph-*.json`). Give the late consumer its own lane **at least three empty lanes away** from the pipeline band so the connector leaves the band immediately and travels open space, and keep that lane's mid-span clear; node boxes are ~145px tall, so a one-lane offset does not clear them. `write_workflow` prints measured connector defects on every build — do not hand off while it reports any connector through a node or frame.
- **Neatness is a rule, not taste (2026-06-10 review).** Three deterministic expectations, measured as `bent_chain_edges` and `inlet_order_mismatches` in `layout_metrics.measure`: (1) a single-in/single-out chain connector runs STRAIGHT — adjacent chain nodes share a row, and a split's branch consumers align to their outlet's row with outlets spaced symmetrically; (2) a multi-input node's inlet order matches its sources' vertical order — when the top source feeds the bottom inlet the connectors cross at the junction for no reason, so swap rows (or inlets at build time); (3) no node ships with an unused output — if the output matters it feeds a destination, otherwise the node should not exist (build anti-joins as left join + null filter rather than leaving a dangling matched fork). These rank just below collision defects in the layout score and are acceptance criteria for the lane-solver milestone.
- **Wrap to keep connectors clear of nodes.** If a connector would route through or across other groups/nodes, that is a signal to re-arrange — wrap to a new row, or stack the far group vertically nearer its feeder — so the connector runs in open space. The deterministic auto-layout stacks extra terminal groups vertically, places multi-tap validation/review stages in a band below the main flow, and runs connector-corridor clearance passes (with a final de-overlap pass); the validator reports any connector that still routes through a node body or cuts through an unrelated stage frame. When the validator still reports a connector crossing nodes, use your judgment to move groups (including vertically) in the JSON and re-validate until it is clean.

## Colors

Group colors are **applied automatically on workflow creation** (the polish step fills a deterministic pastel per group). On an **edit**, do **not** add or change group colors without asking — a user editing an existing flow may not want their colors touched, so the editor leaves colors alone by default (`workflow edit --polish-colors` is opt-in). If color would help, propose it and let the user decide.

When choosing custom group colors, match the builder palette's strength: **~75–83% lightness with moderate saturation** (the `hsl(h, 35–62%, 75–83%)` range in `_GROUP_PALETTE`). The canvas renders group fills softened, so anything lighter (~85%+ lightness) comes out near-white and indistinguishable — verified live 2026-06-10: an 85–91%-lightness hex palette rendered invisible and had to be re-saved at palette strength. Keep hues distinct per group and stay within the palette-strength range so colors render visibly.

## Layout Review

Beyond the deterministic checks, apply these composition questions to the laid-out diagram (read from the workflow JSON / `workflow map`):

- Can a new user identify the workflow's main story from the stage groups and their order?
- Do groups, labels, and colors make the stages easier to understand?
- Does the layout imply any false dependency, sequence, or stage membership?
- Are connectors clear of unrelated nodes and stage frames (the validator measures this)?
- Are group headers and labels present and meaningful?
- Are outputs, review queues, and exceptions in distinct stages from preparation work?

Treat auto-layout as the first draft and this review as the second-pass composition check. When the diagram is not clearly organized, decide what the next pass should do in business terms — for example, "make statement purchases the upper lane and GL postings the lower lane," "move the matching stage down so both inputs enter cleanly," "swap the blend/input rows so source order matches input order," or "move a side validation branch below the main lane" — then apply it in the JSON and re-validate. Do this even when deterministic validation passes; the principles may point to a better arrangement than the solver inferred.

Do not accept a speculative second pass just because it sounds plausible. Compare it against the current layout via `validate workflow` / `layout_metrics`: if the candidate fixes one crossover but introduces more route-through-node connectors, discard it and keep iterating. Within creation, or within a confirmed edit layout-polish scope, this iteration should be automatic and workflow-specific; do not ask the user to approve every node or group movement. Escalate only when the fix would change business meaning, rewrite the graph, move steps between semantic groups, change colors/text meaning, or choose among tradeoffs that require user preference.

If the user reports the layout is hard to read, treat that as evidence the finish pass failed and rework it.

## What To Leave To Deterministic Checks

Do not encode detailed spacing, port geometry, output placement, hidden-preview-panel avoidance, or group-membership mechanics in skill prose. Those belong in:

- `Flow.group(...)` and auto-layout for generated workflows.
- `savant.py validate workflow` for stable geometry and known defects.
- The Editor/API save path for supported layout changes.

When validation reports a layout warning or error, fix the workflow unless there is a clear, user-facing reason why the warning is acceptable.

## Group Composition

Use `Flow.group(...)` for generated workflows. It creates the group frame, header text, membership, color, and layout in the supported recipe shape.

For layout edits, treat a group as a semantic stage:

- Include the nodes that belong to that stage.
- Keep the title and description readable and in business language (see `node-documentation-rules.md`): the header names the business phase, the description states the logic and its thresholds. They render as canvas rich text, not Markdown.
- Keep children visually inside the group and below the header.
- Avoid making one catch-all group for the whole process.
- Remove or merge a group when consolidation leaves it without a distinct business phase, after surfacing that change to the user for live edits.

Do not hand-author low-level group membership fields unless the documented Editor path requires it.

**NEXT MILESTONE — generalized 2D room packing.** The fixed-asset user reference is now covered by two area checks: polish must preserve the hand-packed incoming layout at 1.0x, and the bare solver has its own ratio ceiling so engine progress toward that packing remains visible. That ceiling is measured against the shared validator/solver box model for headers, padding, and labels. `layout_metrics.score` includes `canvas_area` as the last tier after correctness/readability constraints. The broader solver model still primarily assigns dependency levels before packing rooms. Generalizing this means rooms become free rectangles packed under connector constraints so sequential rooms may share a column band when their interconnect allows, and rooms may stagger vertically to where their connectors arrive. Design that as a fresh packing stage; do not bolt more one-off moves onto the band model.

**Furniture belongs with its consumers.** The auto-layout solver may RELOCATE a source-prep stream into the stage that consumes it when that is its only consumer and it sits two or more stages away — this removes long connectors instead of routing them. Relocation changes what both groups MEAN, and this is ENFORCED, not advisory: `polish_recipe` reports every move machine-readably (`report["relocations"]`, `report["documentationRequired"]`), and the editor's `relocation_documentation_gate` BLOCKS any save that moves steps between groups without updating the affected groups' names/headers AND the workflow description in the same change (`--accept-stale-docs` exists for deliberate overrides). The applying session must therefore: (1) surface the moves to the user, (2) propose the updated group and workflow descriptions, and (3) ship layout + documentation as ONE save.

## Deterministic Layout Checks

Validation catches stable structural and geometry problems before import or save: collisions, connectors routed through nodes/frames, bent single-in/out chains, inlet-order mismatches, terminal-output placement, and canvas area. It is the layout acceptance gate.

Let code enforce mechanics and use the design principles above for composition — meaning-dependent judgment about whether the story reads, whether a branch is misplaced, or whether the diagram feels organized, all decided from the workflow JSON / `workflow map`. A good layout pass leaves behind either a clean `validate workflow` result or a clear next-pass direction that another session can follow.
