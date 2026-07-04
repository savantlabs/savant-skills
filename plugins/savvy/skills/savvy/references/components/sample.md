---
registry_summary: "Keeps a limited sample of rows, commonly first rows or top rows after sorting."
---

# sample (Sample)

## Business purpose

Restricts a flow to a representative subset of rows — used for keeping previews fast on large datasets, for picking the top-N rows after a sort, or for audit-style "give me one example per category" patterns. Unlike `filter`, sample is row-count driven (take N rows) rather than predicate driven (keep rows where X). Common in audit/reconciliation flows where a reviewer wants a manageable number of cases to spot-check.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/sample.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

## Building a sample (use node_builders)

Do not hand-author sample JSON. `../scripts/workflow/builders.py` owns the correct shape via `nb.sample_top(...)` (FIRST_N strategy):

```python
s = f.add(nb.sample_top("Top Rate per Jurisdiction", 1,
                        sorts=[("Rate_Percent", "dsc")],     # direction is "dsc", not "desc"
                        group_by=["Jurisdiction_Code"]))      # omit for global top-N
f.wire(prev, s)
```

`n` is the per-group cap when `group_by` is set; sort direction is `"dsc"`/`"asc"` (same convention as `deduplicate`).

## Invariants

- `groupBy` entries must reference real upstream columns; empty `groupBy` means "sample globally."
- With `FIRST_N`, output row count ≤ input, and ≤ `n × distinct(groupBy)` when grouped.

## Interpretation

The `Audit> Sales Tax and VAT` flow is the canonical example: a sample with `strategy: "FIRST_N"`, `n: 1`, `groupBy: ["Jurisdiction_Code"]`, `sorts: [["Rate_Percent", "dsc"]]` — i.e. "for each tax jurisdiction, keep the single tax rule with the highest rate." That's the audit pattern this node is built for.

Reading the effect:

1. **Row-count delta.** Input row count N; output row count at most `n × distinct(groupBy)`. If `groupBy` is empty, output should be ≤ `n`. If `groupBy` is set, expect roughly `n × distinct(groupBy)`.
2. **Per-group selection.** With `groupBy` + `sorts`, within each group the top N by the sort key survive. The surviving row(s) for any group value should be the top N of that group's upstream rows by the sort column.

For audit flows the sampled rows are usually fed to a human reviewer (via a destination node or an outlet). The sort direction must match the audit intent — "highest rate per jurisdiction" vs. "lowest rate per jurisdiction" produce very different review behavior.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, sample_top("x", n, sorts, group_by)["config"])`. Same columns, fewer rows (no schema reconciliation needed) — but adding `groupBy` flips the row-count semantics (top-N per group vs. overall), so re-state the intent and verify after save.

## Gotchas

- **`groupBy` changes the semantics, not just the cardinality.** Without `groupBy`, sample is "top N rows overall." With `groupBy`, it's "top N rows per group." Builders editing a sample node sometimes add a `groupBy` thinking they're adding a partitioning hint without realizing the row count interpretation flips. Always re-state the intent in business terms after edits.
- **`FIRST_N` without `sorts` is order-of-arrival.** Like `deduplicate` without `sorts`, the rows that survive depend on upstream order, which is not guaranteed deterministic across runs. For reproducible samples, always specify `sorts`.
- **Sampling is not random by default.** `FIRST_N` is the observed default and it's a deterministic top-N, not a random sample. For statistical sampling, `strategy` needs to be explicitly set to a random variant (the exact enum value isn't yet confirmed by capture).
- **Sort direction is `"dsc"`, not `"desc"`.** Same convention as `deduplicate`. Builders coming from SQL muscle memory write `"desc"` and silently get the default sort direction.
- **Downstream row-count assumptions break.** Anything downstream of a sample node is operating on a subset, not the full dataset. Aggregations (`summarize`, `rollup`) compute against the subset; reconciliations against external totals will appear "off" by the sampling ratio. Sample is for inspection / review / audit flows, not for production aggregation.
