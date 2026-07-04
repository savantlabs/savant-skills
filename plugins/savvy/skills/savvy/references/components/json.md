---
registry_summary: "Parses JSON from a column, either flattening keys into columns or exploding arrays into rows."
---

# json

## Business purpose

Parses a JSON-bearing column and flattens its keys into real columns (or, in explode mode, expands a JSON array into multiple rows). The canonical use is pairing with `gen_ai` (which produces a JSON-string column) or `service` (whose `"Response Body"` is a raw JSON string) — the `json` node turns that string into structured data downstream nodes can work with.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/json.json`. This file focuses on behavior, writing, and gotchas.

## Building a json node (use node_builders)

Do not hand-author json JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.json_node(...)`:

```python
j = f.add(nb.json_node("Flatten Response", "flatten", "Response Body", keep_input=False))
f.wire(prev, j)  # mode = "flatten" or "explode" (builder rejects other values)
```

## Invariants

- `inputField` must reference a real upstream column whose values are valid JSON strings. Rows with invalid JSON produce null values in the flattened columns for that row (not a run-time error, so errors are silent).
- `mode` must be `"flatten"` or `"explode"`. Other values fail to load.
- The set of output columns is determined at run time from the actual JSON values, not declared in config. Adding a new key to upstream JSON automatically produces a new column; removing a key removes the column. Downstream nodes that reference the flattened columns break silently when this happens.
- In `"explode"` mode, row count multiplies — each row becomes N rows, where N is the length of the array in `inputField`. Rows with empty arrays are dropped.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `json_update(node, mode, input_field, keep_input)`. Flatten/explode changes the output column set, so reconcile downstream references and verify after save.

## Gotchas

- **Mode determines the output shape.** Flatten leaves row count unchanged and adds one column per key discovered in the JSON values, removing `inputField` unless `keepInputField: true`. Explode grows row count, fanning each row out to one row per array element. If the output still shows the input column AND no new columns, the JSON couldn't be parsed — the `inputField` values are plain text, not JSON.
- **Output columns are not declared in config.** They emerge from the data at run time. Downstream column references break invisibly when the upstream JSON schema shifts.
- **Invalid JSON is silent.** A row whose `inputField` isn't parseable JSON produces nulls in the flattened columns — no error, no indicator. If the downstream preview has unexpected nulls, check the upstream JSON values.
- **Nested keys use dot notation.** `{"a": {"b": 1}}` becomes column `a.b`, which downstream nodes must reference with that exact dotted name. Some node types (blend on-keys, filter subjects) don't handle dotted names gracefully — watch for this.
- **Explode on an empty array drops the row.** Users sometimes expect `explode` to preserve rows with empty arrays (producing a single row with nulls); it doesn't.
