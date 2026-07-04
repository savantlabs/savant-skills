---
registry_summary: "Aggregates data by time period, with optional grouping columns."
registry_details: "Supports time buckets plus totals, counts, averages, min/max, distinct counts, medians, and joined text."
---

# rollup (Time Series)

## Business purpose

Aggregates data across time periods, producing one row per period per group. This is how Savant expresses time-series analyses like "monthly revenue by organization," "weekly active users by cohort," or "daily volume by SKU." Conceptually a `summarize` that also bucketizes by a date column.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/rollup.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the rollup shape via `nb.rollup(name, date_col, group_by, aggs, periodicity="day")`, where `aggs` is a list of `(calc, field, alias)`:

```python
f.add(nb.rollup("Monthly Revenue", date_col="Order Date", group_by=["Org"],
                aggs=[("SUM", "Amount", "Revenue")], periodicity="month"))
```

`periodicity` ∈ `day/week/month/quarter/year`. Aggs follow the summarize agg shape; **rollup does not use `params`** — don't carry one over from a summarize.

## Invariants

- `date_col` must reference a real date/datetime upstream column — non-date columns produce run-time errors.
- Output columns = `group_by` + `Period Name` + `Period Offset` + the agg output names; everything else from upstream is dropped.

## Interpretation

- **Row count** after rollup = number of (periods × groups) that have at least one upstream row. The delta from upstream rows can be large in either direction:
  - If each period-group combo has many upstream rows, output is much smaller than input.
  - If each upstream row falls into a distinct period-group combo, output is similar to or smaller than input.
- The `Period Name` column is the most useful verification signal — its values confirm whether bucketing matches the user's intent (e.g. monthly labels like `"Jan 2025"` vs quarterly `"Q1 2025"`).

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `rollup_update(node, date_col, group_by, aggs, periodicity)`. Changing group keys, aggregations, or periodicity changes the output columns/rows: reconcile downstream and verify after save.

## Gotchas

- **Empty periods are emitted as rows.** If `startDate`/`endDate` span periods with no upstream data, rollup may or may not emit zero-value rows for the empty periods depending on provider behavior. Check the `Period Offset` sequence for gaps.
- **`Period Name` format depends on `periodicity`.** Downstream nodes expecting `"2025-01"` will break if `periodicity` switches from `month` to `quarter` (`"Q1 2025"`).
- **`params` is silently ignored.** Copying a string-join aggregation definition from a summarize can bring along delimiter params that rollup does not use. Drop `params` when converting.
- **`groupBy` before `aggs`, but "unlike summarize" a groupBy field can't also be aggregated.** Same rule as summarize — don't put a field in both.
