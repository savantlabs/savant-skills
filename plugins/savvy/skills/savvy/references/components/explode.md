---
registry_summary: "Expands a small-side input across a main input."
---

# explode (Explode)

## Business purpose

Expands a small-side input across a main input. In real workflows, Explode is commonly used to attach a small set of rows, such as validation results or parameter rows, to each row of another stream. It behaves like a controlled cross expansion and is often used around exception handling or file-splitting patterns.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/explode.json`. This file focuses on behavior and gotchas.

## Building an explode (use node_builders)

Do not hand-author explode JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.explode_node(...)`:

```python
x = f.add(nb.explode_node("Attach Params", max_small_side_rows=None))  # cap is optional
f.wire(large, x, in_idx=0)   # LARGE / main side → in_0
f.wire(small, x, in_idx=1)   # SMALL side → in_1 (explode requires one small input)
```

Wiring is load-bearing: the large/main stream goes to `in_0`, the small side to `in_1`. Leave `max_small_side_rows` as `None` (empty config) unless the business process needs a cap. Don't hand-author the JSON.

## Invariants

- Exactly two inlets and one outlet.
- The second input should be small. Exploding two large inputs can multiply row counts quickly.
- `maxSmallSideRows`, when present, should be a positive integer.
- Output row count can exceed either input. Inspect row-count multiplication before assuming duplicates are upstream errors.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, explode_node("x", max_small_side_rows)["config"])`. Changing which inputs feed it is an inlet/topology change. Explode is row-multiplying, so verify the output row count after save.

## Gotchas

- **Explode is row-multiplying.** It can create many more rows than either input. With a main input of N rows and a small side of M rows, expect up to N x M output rows; if the small side has zero rows, output may be zero rows. When the output is unexpectedly large, inspect the small-side input first.
- **Small side really means small.** Large second inputs can create runaway outputs.
- **Empty config is common.** `{}` is valid in many exported workflows; do not invent a cap unless the business process needs one.
- **Do not confuse with JSON explode.** `json` mode `"explode"` expands arrays inside one JSON field. `explode` is a separate two-input step.
