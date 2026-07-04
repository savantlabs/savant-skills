---
registry_summary: "Removes duplicate rows using selected key columns, or keeps only fully distinct rows."
---

# deduplicate (Dedupe)

## Business purpose

Removes duplicate rows, where "duplicate" is defined by a set of key fields the user picks. Keeps one representative row per distinct key combination and drops the rest. A sort order can be specified to control which duplicate survives (e.g. "keep the most recent," "keep the one with the highest amount").

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/deduplicate.json`. This file focuses on behavior and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the dedupe shape via `nb.deduplicate(name, fields=[...]|None, sorts=[(col,"dsc")]|None, mode="distinct")`:

```python
f.add(nb.deduplicate("Latest per Customer", fields=["Customer"],
                     sorts=[("Order Date", "dsc")]))   # sort picks the survivor
```

- **`fields`** = the key columns; an empty/`None` list means whole-row distinct.
- **`sorts`** = `(col, "asc"|"dsc")` pairs that choose which duplicate survives (e.g. keep the most recent).
- **`mode`** defaults to `"distinct"`.

Don't hand-author the JSON.

## Invariants

The builder owns config shape (`mode`, `fields`, `sorts`). These behavioral rules still matter:

- Each `fields` entry must reference an upstream column; an empty list means whole-row distinct.
- `sorts` (when non-empty) must reference real columns and use direction `"asc"` or `"dsc"`.
- Output row count ≤ input row count.
- Without a `sorts` directive, which duplicate survives is non-deterministic across runs (upstream order is not guaranteed stable).

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `deduplicate_update(node, fields, sorts, mode)`. Columns are unchanged (same schema, fewer rows), so no downstream column reconciliation is needed — just verify the row-count change after save.

## Gotchas

- **The row-count delta is the duplicate count.** For input N rows, output is D (distinct key combinations) and N − D is the number of duplicates removed. Large deltas are often the signal users are looking for — "how many duplicates did we have?". With `includeDuplicates: true`, output row count instead matches input and an added column flags duplicates; this variant is for auditing, not dropping.
- **Without `sorts`, results are non-deterministic.** The same flow can produce different survivors across runs. Users chasing a "wrong" dedupe often just need to add a sort.
- **Key fields are compared as strings (usually).** Dedupe on a numeric column with `1.0` and `1` may or may not treat them as equal depending on upstream casts. Cast to a consistent type in an upstream `edit` if in doubt.
- **`includeDuplicates: true` inflates downstream row counts unexpectedly.** Users sometimes set this flag thinking "include ALL the duplicates in the output" without realizing they were dropping them before. Verify row counts after toggling.
- **Dedupe doesn't merge columns.** If two rows are key-duplicates but differ in other columns, only one row's values survive — the other values are dropped. If you need merging, use `summarize` with `LAST` or `JOIN_STR_DISTINCT`.
