---
registry_summary: "Groups rows and calculates totals, counts, averages, min/max, distinct counts, or joined text per group."
registry_details: "Also supports first/last values, medians, mode, standard deviation, and variance."
---

# summarize

## Business purpose

`GROUP BY` with aggregations. Collapses multiple rows into one per group, producing aggregate values like sums, counts, averages, or joined distinct strings. The canonical use is "for each entity / region / month, what's the total / count / last value." Row counts always shrink through a summarize node (or stay the same in the degenerate "group by nothing" case).

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/summarize.json`. This file focuses on behavior and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the summarize shape via `nb.summarize(name, group_by, aggs)`, where `aggs` is a list of `(calc, field, output_name)`:

```python
f.add(nb.summarize("By Entity", group_by=["Entity"],
                   aggs=[("SUM", "Amount", "Total"),
                         ("COUNT", "Row", "Rows")]))   # COUNT-of-rows uses field="Row"
```

Verified facts the builder encodes:

- **COUNT-of-rows uses `field="Row"`** (it emits `arg.type:"row"`); any other agg names the column in `arg.selectedField`.
- **Each agg compiles with `tgt_col`** (NOT `alias`) and **`params` as a sibling of `arg`**. A wrong shape passes static validation but throws a runtime "Internal system error" the validator can't catch.
- Use `calc: "NUNIQUE"` for count-distinct (the UI may show "COUNT DISTINCT").
- For conditional counts after enrichments/left joins, add a row-level 0/1 indicator first with `nb.op_count_if(...)`, then aggregate that indicator with `SUM`. Do not count nullable right-side fields directly when unmatched rows should contribute zero.

## Invariants

- Empty `group_by` is valid — produces a single-row global aggregate.
- `sorts` must reference fields that exist after aggregation (group keys or agg output names); sorting on a dropped pre-agg column throws at run time.
- **A valid aggregation argument is Row or a non-grouped upstream column.** The app's Argument picker offers exactly `Row` plus the columns *not* currently in Group by, computed per node. A config whose `arg.selectedField` is also in `groupBy` executes (the engine does not enforce the rule) but is **undisplayable**: the settings panel renders a blank Argument *and* a blank Group-by slot for that field, and pressing Apply saves the blank state — silently dropping the group key and emptying the argument. Verified live 2026-06-11 on an Alteryx-converted production flow (eight affected nodes) and reproduced in a sandbox flow.

## Migration mapping

Alteryx's Summarize config is a flat list of `(field, action)` rows, and the same field legally appears in multiple rows — `GroupBy` and `Count` on one field is the standard Alteryx idiom for "group by X and count rows", because Alteryx `Count` ignores the field's values (null-inclusive record count) and merely needs a field anchor. Savant's model is different: roles are exclusive and `COUNT` of a field skips blanks. Map actions, never copy the anchor field:

| Alteryx action | Savant agg | Note |
|---|---|---|
| `Count` | `("COUNT", "Row", ...)` | Always Row; discard the anchor field. Copying the anchor produces the undisplayable both-roles config above and undercounts groups whose field is blank. |
| `CountNonNull` | `("COUNT", "<field>", ...)` | The only count that maps to field-COUNT. If the field is also grouped, build a 0/1 indicator upstream (`nb.op_count_if`) and `SUM` it instead. |
| `CountDistinct` | `("NUNIQUE", "<field>", ...)` | |
| `CountNull` | indicator + `SUM` | `nb.op_count_if(<flag>, cond(field, "is_null", ...))` then `("SUM", <flag>, ...)`. |

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `summarize_update(node, group_by, aggs)`. Output columns = `groupBy` + each agg's `tgt_col`, so changing the group keys or aggregations changes the schema: reconcile downstream references and verify output after save.

## Gotchas

- **A field can be grouped-by OR aggregated, not both.** Imported/converted configs can violate this (the engine still runs them); the settings panel then renders blank pickers and Apply destroys the config. See the argument-validity invariant and the Alteryx mapping table above.
- **Output row count = distinct group tuples.** The output has one row per distinct tuple of `groupBy` fields in the upstream data — G rows for G distinct group tuples. A summarize that produces the same row count as its input usually means `groupBy` is effectively identifying (uniquely keying every row), which is often a bug.
- **Dropped columns are invisible after summarize.** Output columns are exactly `groupBy` fields + each `aggs[].tgt_col.name`; nothing else carries through. Users often expect a summarize to "pass through" columns like edit does. It doesn't — anything not in `groupBy` or `aggs` disappears from downstream.
- **String joins need a delimiter.** `JOIN_STR` and `JOIN_STR_DISTINCT` default to `", "`. An empty delimiter collapses values with no separator, which is rarely intended.
- **`FIRST`, `LAST`, and `MODE` depend on ordering/ties.** `FIRST` and `LAST` use the group's current ordering. `MODE` needs a tie-breaking behavior if two values are equally common; do not use it where tie handling is business-critical unless verified.
- **Use `NUNIQUE`, not `COUNT DISTINCT`.** The UI may display "COUNT DISTINCT", but exported JSON uses `calc: "NUNIQUE"`.
- **Older exports may have bad output data types.** Several real exports use `"integer"` for string-returning aggregations. For generated workflows, set `JOIN_STR` and `JOIN_STR_DISTINCT` outputs to `"string"`.
- **Left joins need explicit zero handling for count-style measures.** Build fields such as `Returned Flag` or `Negative Review Flag` with `nb.op_count_if(...)`, then `SUM` the flag. For nullable numeric fields that should aggregate as zero, add a cleaned field with `nb.op_default_constant(..., 0, dt="number")` before summarizing.
