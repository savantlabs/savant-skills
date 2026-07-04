---
registry_summary: "Turns row values into columns and aggregates the matching values."
registry_details: "Supports aggregations such as totals, counts, averages, min/max, distinct counts, medians, and joined text."
---

# pivot (Pivot)

## Business purpose

Converts rows into columns — the inverse of unpivot. Takes a column's distinct values and spreads them into separate output columns, populating each with values from a second column (aggregated if multiple rows land in the same cell). The canonical use is "turn my `Month, Value` rows back into one column per month."

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/pivot.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

## Building a pivot (use node_builders)

Do not hand-author pivot JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.pivot(...)`:

```python
p = f.add(nb.pivot("By Month", pivot_field="Month", value_field="Amount", calc="AVG"))
f.wire(edit, p)  # feed only grouping key(s) + pivot field + value field
```

**Verified fact:** feed the pivot ONLY its grouping key(s) + the pivot field + the value field; drop every other passthrough column upstream with an `edit` (hiddenFields). At full data scale a pivot value can collide with a passthrough column name (e.g. a `timestamp` value spilled into a column vs an existing `timestamp` column) → "Pivot values conflict with existing column names" error. A 1k-row Analyze won't surface this; it's data-dependent.

## Invariants

- `pivotField` and `valueField` must reference real upstream columns, and must be different columns.

## Interpretation

- **Output columns:** (upstream columns minus pivot/value) + one per distinct value in `pivotField`. The output column headers reveal which distinct `pivotField` values were found.
- **Output rows:** typically fewer than input — rows collapse by the non-pivot key columns. If input has 12 months × 1000 customers = 12000 rows, output has 1000 rows × 12 month columns.
- **Verification check:** the sum of values along any pivot row in the output should match the sum of `valueField` for that non-pivot-key combination in the input (when `calc: SUM`), or the single value (when `calc: ANY`).

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `pivot_update(node, pivot_field, value_field, calc)`. A pivot's output columns are the distinct pivot-field values, so any change reshapes the schema: reconcile downstream references and verify after save.

## Gotchas

- **Output columns are data-dependent.** Downstream nodes that reference specific pivot-output columns by name break when upstream data adds or removes distinct values of `pivotField`. This is the same gotcha as `json` flatten.
- **`ANY` silently picks a row when cells have duplicates.** `ANY` is non-deterministic when a cell has multiple candidate values. If you want determinism, add an upstream dedupe with a clear sort order, or use an explicit agg like `MAX`.
- **Pivoting a high-cardinality column creates too many columns.** Pivoting on, say, `Customer ID` with 10,000 distinct values produces an unusable 10,000-column output. Consider grouping / bucketing first.
- **`valueField` type determines available aggregations.** Switching `valueField` from a numeric to a text column may leave `aggregation.calc` set to something invalid (e.g. `SUM`). The canvas doesn't always catch this.
