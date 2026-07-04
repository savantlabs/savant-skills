---
registry_summary: "It's not a pseudo-node — it's not an independent component. This is what is produced from components that produce more than one output e.g. filter, blend etc."
---

# outlet (Split Output)

## Business purpose

A pseudo-node that represents one specific output branch of a parent node. Created automatically when a parent node has multiple outputs — specifically when `filter` has `useFalsePath: true` or when `blend` has unmatched outputs enabled. The outlet doesn't transform data; it's a wiring point for downstream nodes to connect to a specific branch (true path, false path, matched, unmatched-left, unmatched-right).

Users rarely author outlet nodes directly — they're a consequence of toggling parent-node settings. The canvas adds and removes them automatically.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/outlet.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

Builder note — the only rule when building: set the split on the **parent** (filter `false_path=True`; blend `left_unmatched=`/`right_unmatched=`) and wire each branch with the handle from `nb.filter_outlet(...)` / `nb.blend_outlet(...)`. Those return a wireable handle (`{parent}|i`); they do **not** create the outlet node, and you never hand-author one or wire a parent's embedded `out_1`/`out_2`. The toolchain synthesizes the canonical outlet children at finalize (`workflow.outlets.normalize_outlets`, run by `to_dict()` and `workflow polish`) from the parent's flags, so the structure is always correct. (The rest of this file is for *reading* outlets, not building them.)

## Invariants

- Outlet children exist only when the parent enables multi-output (filter `useFalsePath: true`, or blend `useLeftUnmatch`/`useRightUnmatch`). An outlet without the corresponding parent flag is invalid state.
- **When a split is enabled, the canonical shape is: the parent collapses to a single `out_0` that fans out to one `{parent}|i` outlet child per branch — the main/matched/True output is `{parent}|0`, the secondary outputs are `|1`/`|2`.** When no split is enabled, there is no outlet child at all — the parent's single output wires straight to the next node, exactly like any single-output tool. A `|0` outlet child on a tool with no split enabled is invalid; `normalize_outlets` collapses it back to a direct edge.
- `name` is determined by parent + index, not author-set — outlet renames via the pencil icon aren't supported the standard way.

## Interpretation

- An outlet's type is `"outlet"` and its id follows the `{parent}|{index}` pattern. Outlets appear in the node list alongside normal nodes.
- An outlet represents a specific branch of its parent's output. The outlet `{parent}|1` carries THAT branch's rows; once a split is enabled the primary output is itself an outlet child — `{parent}|0` ("True" on a filter, "Blended" on a blend) — and the parent node only fans its `out_0` to those children. So "what comes out of the False path" is the `|1` outlet's data, and "what comes out of the matched/True path" is the `|0` outlet's data — neither is read off the parent node directly.
- An outlet has no editable config of its own. Its only meaningful output is the rows that flowed down that branch.

## API edit support

_(Phase 3 — outlets are not independently editable. The API edit support lives on the parent node: toggling `useFalsePath` on a filter or `useLeftUnmatch` / `useRightUnmatch` on a blend adds or removes outlet children. See `filter.md` and `blend.md` for those recipes.)_

## Gotchas

- **Outlet indexing is positional and parent-flag-dependent.** On a blend with `useLeftUnmatch: true` only, `|1` is left-unmatched. With both flags on, `|1` is left-unmatched and `|2` is right-unmatched. Never assume `|1` means a specific branch without checking parent flags.
- **Outlets appear and disappear when parent flags toggle.** Snapshots that key on outlet presence must re-validate after any parent config change. See `filter.md` and `blend.md` for the specific toggle behaviors.
- **Outlets have zero configuration.** Don't treat them as regular nodes when writing inspector logic — skipping directly to the data preview is the right instinct.
