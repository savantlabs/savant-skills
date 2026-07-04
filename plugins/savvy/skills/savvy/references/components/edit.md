---
registry_summary: "Column-level transformations: show, hide, reorder, or rename columns; add new columns from expressions;"
---

# edit (Transform)

## Business purpose

Column-level transformations. Adds new columns, replaces existing ones, hides or reorders columns, and changes data types. This is the workhorse node for reshaping a row without adding or removing rows — a row in is a row out; only the columns change. Supports three authoring modes depending on how the user wants to express the transform:

- **Savant Copilot** (UI only): user types a natural-language prompt and the product generates an expression. JSON mode value: `"copilot"`.
- **Formula**: user writes the expression directly. JSON mode value: `"expression"`. This is what the editor/builder should produce programmatically — no LLM round-trip needed.
- **Multi-Row**: structured window functions and aggregations (running totals, ranks, last-value-per-group). JSON mode value: `"builder"`.

Production exports are heavily weighted toward Formula/expression edits, but all three modes appear in real flows. Programmatic builders should still prefer `mode: "expression"` for deterministic row-level formulas and use `mode: "builder"` only for multi-row/window calculations. Do not generate `mode: "copilot"`; copied copilot edits can be inspected, but new generated JSON should contain the final expression directly.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/edit.json`. This file focuses on behavior and gotchas.

## Building a transform (use node_builders)

**Prefer ONE Transform over several nodes.** A single `edit_node` can add/compute columns, rename, retype, hide, and reorder all at once — including **mixing a multi-row window calc (`op_window`, builder mode) with row-level renames/hides in the same node** (verified live: a node doing `ROW_NUM` Rank + two renames + 12 `hiddenFields` + `orderedFields` ran clean). So don't chain an `edit` then an `adapter` to tidy a column set; one Transform does it. Reserve the **adapter** for a fixed target-schema mapping *contract* (canonical names + `dataType` + `required` + passthrough control), not presentation cleanup. When you document a multi-operation Transform, group the readout into the labeled sections defined in `../standards/node-documentation-rules.md` → Transform (New / calculated → Renamed / converted → Column order → Hidden), showing only the sections that apply.

`../scripts/workflow/builders.py` `edit_node()` composes many column operations into ONE node's `edits[]`:

```python
f.add(nb.edit_node("Shape",
    ops=[nb.op_arith("Net", "Gross", "sub", "Tax"),       # add/compute a column (action add_col)
         nb.op_rename("Cust", "Customer"),                  # rename in place (action replace, consumes Cust)
         nb.op_retype("Amount", "to_number"),               # retype in place
         nb.op_transform("GL Date", "PostDate",             # rename + cast in one op, consumes PostDate
                         "TO_DATE(`PostDate`)", "date")],
    drop=["Scratch Notes"],                                 # hide columns by NAME -> hiddenFields
    order=["Customer", "Amount", "Net"]))                   # arrange by NAME      -> orderedFields
```

- **Add/compute columns**: `op_json_field`, `op_json_number`, `op_arith`, `op_avg`, `op_cast`, `op_date_diff`, `op_window` (action `add_col`). Use `op_date_diff("Ship Days", "Ship Date", "Order Date", unit="day")` for ``DATE_DIFF(`Ship Date`,`Order Date`,"day")``; first date is end/later, second is start/earlier.
- **Rename / retype / transform a column IN PLACE** — always a `replace` edit that *consumes* the source column. Use the most specific helper:
  - `op_rename(old, new)` — pure rename (value/type unchanged).
  - `op_retype(col, to_number|to_integer|to_text|to_date|to_datetime|to_boolean)` — cast in place, same name.
  - `op_transform(new, src, expression, dt)` — the general form: rename **and** cast **and** normalize in one op, consuming `src`. Folds the whole change into a single column: e.g. `op_transform("GL Date", "PostDate", "TO_DATE(`PostDate`)", "date")` or `op_transform("Vendor Key", "AI Answer", "UPPER(TRIM(`AI Answer`))")`. (`op_excel_serial_date` is the serial→date special case.)
- **Hide**: `drop=[...]` → `hiddenFields`. **Reorder**: `order=[...]` → `orderedFields` (reorders only — never drops; hide to remove). `orderedFields` is a **pin-to-front** list — list only the columns you want at the front, in order; every other column is appended after them in natural schema order. You do *not* enumerate the whole output. Both lists, and `replaceTgt`, take the column **display name** (see the id-vs-name rule below), not a derived id.
- Convenience: `modify={col: {"name": new, "dataType": dt}}` compiles to `op_rename`/`op_retype`.

**Rename/retype/transform IN PLACE — never add-a-column + hide-the-original.** A `replace` edit overwrites the source column's slot and renames it, keeping its position: one column in, one out, nothing hidden (the Edit launcher's REPLACE path does this server-side). Do **not** express a rename as an `add_col` of `new = old` followed by `drop=[old]` — that carries both the old and new column through the node, the hidden original leaks downstream as a stray `summarize`/`pivot` grouping key and as `(rhs)` clutter, and chained rename hops can collide and silently drop a column (see Gotchas). Do all renames/casts **once, at source-prep**, so downstream references clean names a single time; don't chain rename hops across nodes.

**Transform edits are ordered.** A later edit can reference a column created or replaced earlier in the same `edit_node` as long as the `edits[]` order follows the dependency order. Create prerequisite fields first, then later calculated fields that read them. Do not reference a field before the edit that creates it.

Verified live: a rename (`Country`→`Nation`) and a retype (`IdNum`→`integer`) both take effect in the output schema.

**Do NOT rename/retype via a `config.modify` map.** That key exists but is empty `{}` in real exports — Savant ignores it, so writing renames/retypes there is a silent no-op (this was a real builder bug). Renames and type changes are `replace` edits in `edits[]`. (Separately, *pattern-based* bulk rename/change-type/hide — match-by-prefix etc. — is a **Format** node feature: `config.steps` with `action` `rename`/`change_type`/`hide`, not the Transform node.)

## Invariants

- Programmatic generation should use `"expression"` for row-level formulas and `"builder"` only for confirmed multi-row/window calcs. Do not generate new `"copilot"` edits.
- `tgtCol.id` must be unique within the node's outputs. Two edits cannot target the same column id in the same edit node.
- Calculated edits in the same node may depend on earlier edits in that node. Keep `edits[]` in dependency order; a forward reference to a later edit's output is invalid.
- `action: "replace"` identifies the column to overwrite by `replaceTgt` — the source column's **name** (the runtime resolves it by name or id, `SparkUtils.findField`). If `replaceTgt` matches no upstream column the launcher fails with a clear "no field … in the input" error (it does *not* silently become an add). `op_rename`/`op_retype`/`op_transform` set `replaceTgt` for you.
- **Author the `expression` truth field only — never hand-build `pipeline`/`lookup`.** An expression-mode edit carries `mode`, `action`, `tgtCol`, and `expression` (plus `replaceTgt` for a replace). The runtime compiles the expression to a pipeline server-side when no pipeline is present (see `EditConfig` / `Edit.scala` `compileExpressionPipeline`), and the FE re-derives the display caches — the same contract the `EditNodeHydrater` follows. A hand-built pipeline can diverge from the expression and fail at runtime (e.g. `TO_DATE("2025-07-31")` mis-compiled to a step with empty `src_cols` → `IndexOutOfBounds` → "Internal system error"); let the authoritative compiler own it. `node_builders` emits truth-only; do not add `pipeline`, `lookup`, `transient_cols`, or `skipPreprocess` yourself.
- `hiddenFields` and `orderedFields` reference columns by **name** (real exports carry display names there, e.g. `hiddenFields: ["Response Body Split 2"]`). Renaming a column via `replace` does not auto-update these lists — if you rename then hide/reorder it in the same node, reference the **new** name.
- Builder-mode (`mode:"builder"`) window/aggregation calcs carry a `calc` tree, not an expression — that path is unchanged. `RANK` and `ROW_NUM` usually have null `arg` fields; do not invent a selected field for them.
- Builder-mode `LEAD` and `LAG` should include `params.offset` and should usually include deterministic `sorts`.

## API edit support

> **Status: edit-node config edits are supported through the deterministic regenerate-and-merge path — the same `node_builders` library the builder uses to author the node.**

An expression-mode edit carries only the `expression` truth field (plus `tgtCol`/`action`); the runtime and FE compile it to a pipeline, so there is no coupled `pipeline`/`lookup` to keep in sync. `edit_update(existing_node, ...)` regenerates the `edits[]` config and merges it onto the live recipe node, preserving its id, wiring, position, and any config fields the library does not model — and because `edits[]` is replaced wholesale, any stale hand-built `pipeline`/`lookup` from an older export is cleared on save. So the editor changes a Transform the same way the builder creates one. Do **not** use config-panel automation, CodeMirror event simulation, store dispatches, or Apply-button flows — those mutation paths are retired.

Editor flow for an edit-node change:

1. Read the live recipe node — you have its full current config, including fields we don't model.
2. Express the change in the `node_builders` vocabulary (`op_arith`, `op_cast`, `op_rename`, `op_retype`, `op_transform`, `op_window`, …; `drop` → `hiddenFields`, `order` → `orderedFields`, all by column name) and call `edit_update(node, ...)`.
3. Run the validator, then save through the normal snapshot → diff → confirm → save → re-fetch loop.
4. An edit changes data behavior, so verify the node's output after save. If it renamed/dropped/retyped a column, the output schema changed — reconcile downstream column references the same way dataset replacement does, and re-verify downstream.

The gotchas below are the rules `node_builders` already encodes; they remain the spec for any edit-node change.

## Gotchas

- **A Transform changes columns, not rows; verify the column math.** Row count does not change (a row in is a row out). Output column count = N (upstream) + count of `add_col` edits − count of `hiddenFields`, arranged by `orderedFields`. If the output column list doesn't match this, something's wrong — usually a `hiddenFields`/`orderedFields` entry whose name doesn't match a real column (so the hide/reorder no-ops), or a rename collision (see Gotchas). When an edit adds a column, inspecting a few of its values is the single most useful check that the transform produced what was expected.
- **Author the expression, not the pipeline.** The runtime compiles `expression` → pipeline server-side and the FE re-derives the display lookup, so an expression-mode edit ships `expression` only — no `pipeline`/`lookup`/`transient_cols`. Hand-building those is what caused the `TO_DATE(<const>)` → empty-`src_cols` → `IndexOutOfBounds` runtime failure; `node_builders` no longer emits them. The expression grammar authority is `savant-common/expr` — see `expression-language.md`.
- **Ordered calculated-column dependencies are supported.** A Transform with two `add_col` edits can have the second edit read the first new column when the first edit appears earlier in `edits[]`. Keep dependencies in order and verify the node output after save.
- **Copilot metadata can become stale.** `LLMData.prompt` and `LLMData.expression` are descriptive metadata. If an API recipe change ever updates the live transform, it must either regenerate or intentionally clear stale `LLMData` so the exported JSON does not describe one expression while executing another.
- **A replace renames in place; downstream references the new name.** A `replace` overwrites the source column's slot and gives it the new name (the runtime re-derives the id). After a rename, downstream `replaceTgt`/`hiddenFields`/`orderedFields`/expressions must use the **new** name. Don't try to preserve an old id — name is the reference everywhere.
- **`orderedFields` only reorders — it never drops. To remove a column, hide it with `hiddenFields`.** These are two separate Transform controls: `hiddenFields` is the show/hide multi-select ("columns to suppress in output"), and `orderedFields` is the drag-reorder list. `orderedFields` is a **pin-to-front** list, not an exhaustive output ordering: the launcher emits the listed fields first (in order), then appends every remaining column in natural schema order (`ordered ++ unordered`). So you list only the columns that matter at the front; the rest follow automatically and are **not** dropped. Listing only the columns you want to keep in `orderedFields` does **not** drop the rest. A real export with `orderedFields: ["content"]` can look like a drop, but only because that source had a single column to begin with. The failure this causes is silent and downstream: leaked raw columns (e.g. a per-row `id` or a raw JSON column) become extra grouping keys in a later `pivot`/`summarize`, so rows that should collapse to one per entity stay split — the schema still looks right while the row count silently collapses (often to 0 after a later "must have both X and Y" filter). To actually reduce the output to a fixed set, put every unwanted upstream column **name** in `hiddenFields` (and, if needed, `orderedFields` for arrangement) — or use `keep_only_columns`, which derives the hidden set from the upstream schema for you. Reference both lists by name, per the rule below.
- **Reference columns by NAME, not by a derived id.** Everywhere a Transform names a column — `replaceTgt`, `hiddenFields`, `orderedFields`, and field references inside an `expression` (backtick-quote names with spaces, e.g. `` `GL Post Date` ``) — use the **display name** the user sees. The runtime resolves these by name or id (`SparkUtils.findField`), and real exports store names there. The field **id** is an internal, parquet-friendly handle that is *not always* the normalized name: `Last Updated (UTC)` has the stored id `last_updated`, not `last_updated__utc_`. So a *derived* id can match neither the name nor the real id, and the hide/reorder/replace then **silently no-ops** — the failure mode behind leaked columns. `node_builders` emits names for you (the `tgtCol.id` it writes is cosmetic; the runtime re-derives the id of a new/renamed column from its name). The one case that needs care is a genuine duplicate-name collision from Blend: pass the **disambiguated display name** (`Amount (rhs)`), which is unique, rather than guessing an id like `amount_2`.
- **Chained rename hops can collide on one column and silently drop it.** Two renames that resolve to the same column — across nodes, or a `replace` whose new name collides with another existing column — don't error; the column is silently lost (a master report lost its `Description` column to a `Description → Report Description → Description` hop chain). Rename a column once, to a final unique name, at source-prep; don't rename back toward an upstream name later.
- **Don't carry an upstream column alongside the column derived from it.** If `Vendor Key` is just `AI Answer` normalized, *transform `AI Answer` in place* (`op_transform`) instead of adding `Vendor Key` and leaving `AI Answer` behind — the orphan leaks downstream as a stray grouping key and as output clutter.
