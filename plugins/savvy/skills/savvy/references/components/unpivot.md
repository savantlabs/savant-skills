---
registry_summary: "Turns multiple columns into rows."
---

# unpivot (Unpivot)

## Business purpose

Converts multiple columns into rows. The canonical use is "my data has one column per month (`Jan`, `Feb`, `Mar`), and I want one column called `Month` and one called `Value` instead." Each unpivoted column becomes one output row per input row. The inverse of `pivot`.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/unpivot.json`. This file focuses on behavior and gotchas.

## Building an unpivot (use node_builders)

Do not hand-author unpivot JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.unpivot(...)`:

```python
u = f.add(nb.unpivot("Months to Rows", name_field="Month", value_field="Value",
                     selected_fields=["Jan", "Feb", "Mar"], mode="unpivot"))
f.wire(prev, u)
```

`mode="unpivot"` unpivots `selected_fields`; `mode="keep"` keeps `selected_fields` as identity
columns and unpivots the remaining columns. `name_field`/`value_field` must not collide with
retained column names.

When the upstream schema is known, the builder/validator models the Unpivot output schema as the
retained identity columns plus `name_field` and `value_field`. That means the normal final-output
shaping helper works after Unpivot:

```python
u = f.add(nb.unpivot("Months to Rows", "Month", "Value", ["Jan", "Feb", "Mar"]))
f.wire(prev, u)
shape = f.add(nb.keep_only_columns(f, u, "Keep report columns", ["Account", "Month", "Value"]))
f.wire(u, shape)
```

If the upstream schema is unknown, first standardize the input with an Adapter or provide schema
hints; otherwise downstream column checks and `keep_only_columns(...)` cannot know what identity
columns remain.

## Invariants

- `nameField`/`valueField` must not collide with retained or unpivoted column names, or the output gets duplicate column names.
- Output row count = input rows × number of unpivoted columns.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `unpivot_update(node, name_field, value_field, selected_fields, mode)`. This reshapes columns → rows, so verify the row/column change downstream after save.

## Gotchas

- **Output shape is N×(M−K) rows × (K+2) columns.** For input of N rows × M columns where K are identity columns and M−K are unpivoted, the output has N×(M−K) rows and K+2 columns (the K identity columns plus `nameField` and `valueField`). If the row multiplier doesn't equal M−K, an unpivoted column likely had null values that got dropped — inspect a sample.
- **Type mixing collapses to string.** Unpivoting columns of mixed types (`Date`, `Amount`, `Description`) into one `valueField` forces everything to a common type — usually string. Values like `2025-01-15` and `123.45` become `"2025-01-15"` and `"123.45"`.
- **Identity column membership matters more than it looks.** Forgetting to list a column as identity means it gets unpivoted, which multiplies rows unintentionally. Users often discover this when their output has 10x the rows they expected.
- **The mode names are easy to invert.** If you want `ADJ`, `DED`, and `PMT` to become activity
  rows, use `mode: "unpivot"` with those fields in `selectedFields`. `mode: "keep"` keeps those
  fields as identity columns and unpivots everything else.
- **Column order in `nameField` is determined by upstream column order.** Reordering upstream columns changes the order of rows within each input row's output group.
- **Null unpivoted values.** Whether a row with nulls in the unpivoted columns produces null-valued rows or skips those combinations depends on provider behavior. Inspect carefully.
