---
registry_summary: "Splits one text column into multiple rows or multiple columns."
---

# split (Split)

## Business purpose

Splits one text field into either multiple rows or multiple columns. Use Split when one field contains a delimited list, stacked values, or compound text that needs to become structured data.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/split.json`. This file focuses on behavior and gotchas.

## Building a split (use node_builders)

Do not hand-author split JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.split_node(...)`:

```python
sp = f.add(nb.split_node("Split Tags", "Tags", ",", mode="rows",
                         trim=True, keep_input=True))   # mode = "rows" or "columns"
f.wire(prev, sp)
```

The builder handles the literal-separator pairing (`separator` / `extra.originalSeparator`) — see the newline gotcha below. Don't hand-author the JSON.

## Invariants

- Exactly one inlet and one outlet.
- `mode` must be `"rows"` or `"columns"`.
- `inputField` must reference an upstream text-like column.
- `separator` should not be empty.
- In row mode, output row count can increase. In column mode, row count should stay the same.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, split_node("x", input_field, separator, mode)["config"])`. Row mode changes grain and column mode creates dynamic field names, so verify the row/column change downstream after save.

## Gotchas

- **Mode determines output shape.** `mode: "rows"` turns each input row into multiple output rows, one per split part (row-count expansion). `mode: "columns"` keeps each input row as one row, spreading split parts across generated columns (same row count, new headers).
- **Row mode changes grain.** Downstream summaries and joins operate at the split-part level, not the original row level.
- **Column mode creates dynamic field names.** Downstream references can break if the number of split parts changes.
- **Separators are literal.** A newline delimiter must be represented correctly in both `separator` and `extra.originalSeparator`.
- **Trim changes matching behavior.** Keeping whitespace can cause join/filter mismatches later.
