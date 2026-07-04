---
registry_summary: "Performs bulk structural and formatting changes on columns, including renaming, reordering, hiding, type conversion, and header promotion."
---

# format (Format)

## Business purpose

Bulk field cleanup and formatting. Format applies UI-style column operations such as hiding fields, changing data types, renaming matched fields, filling blanks with default values, using a row as headers, sorting fields, and simple field reordering. It is most useful for broad structural cleanup after messy file ingestion.

For generated workflows, prefer Transform (`edit`) for calculated values and explicit final shaping. Use Format when the desired operation is a direct column-formatting action that matches the product's Format step.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/format.json`. This file focuses on behavior, writing, and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the Format shape via `nb.format_node(name, header_row=None, steps=None)`:

```python
f.add(nb.format_node("Promote Header", header_row=0))   # promote a data row to headers
f.add(nb.format_node("Clean", steps=[...]))             # matcher-based bulk actions
```

- **`header_row`** promotes that row index to column headers (emits `replaceNamesWithRow`).
- **`steps`** are matcher-based bulk actions — `rename` / `change_type` / `hide` / `fill`, each keyed by a `matcher` (`contain`/`start_with`/`end_with`/`is_empty`). These pattern-based actions are a Format feature, **distinct from the Transform/`edit` node** (which renames/retypes specific columns by id, not by matched pattern).

Don't hand-author the JSON.

## Invariants

The builder owns node shape and the `header_row` (`replaceNamesWithRow`) wiring. The `steps[]` entries you pass it still follow these matcher-based rules:

- `steps[]` actions should match product-supported actions. Unknown actions may load but fail during run.
- `change_type` params should use Savant data type strings such as `"string"`, `"integer"`, `"number"`, `"date"`, `"datetime"`, or `"boolean"`.
- `rename` uses `params: [searchText, replacementText]` with `changeNameAction` controlling whether the replacement is applied at the start, end, or anywhere in the matched field name.
- `fill` uses `params: [defaultValue]` and fills matching fields' blank values with that default.
- `matcher: "is_empty"` does not require `matchingText`; it targets fields whose values are empty.
- Header replacement should be used only when the incoming file truly has field names in a data row.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, format_node("x", header_row, steps)["config"])`. Format steps (hide/rename/retype/header promotion) change the schema broadly, so reconcile downstream references and verify after save.

## Gotchas

- **Row count is unchanged; the schema is what moves.** Format never adds or drops rows. Its effect shows up in the output columns: hidden fields disappear, changed types alter sorting/filtering/downstream calculations, renamed fields change downstream headers and field references, filled fields replace blank values in matched columns, and header replacement (`replaceNamesWithRow`) rewrites every downstream field reference.
- **Format can break downstream references.** Hiding, renaming, or changing headers affects later filters, joins, and transforms.
- **Bulk matchers are broad.** `matcher: "contain"`, `matcher: "start_with"`, and `matcher: "end_with"` can catch more columns than intended.
- **UI labels differ from JSON.** The app says "end with", "start with", "are empty", and "fill with default"; JSON uses `end_with`, `start_with`, `is_empty`, and `fill`.
- **Use Transform for explicit calculations.** Format is best for column presentation/schema cleanup, not business logic.
- **Keep `steps` and `extra.originalSteps` aligned.** Many exports duplicate the same action list in both places.
