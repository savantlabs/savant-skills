---
registry_summary: "Filters rows based on conditions, including comparisons, empty checks, text matching, ranges, and formulas."
---

# filter

## Business purpose

Row-level filtering. Keeps rows that match one or more conditions on specific columns; drops the rest. Optionally splits the flow into two outputs — rows that matched (True path) and rows that didn't (False path) — when "Include false path" is on. This is the node builders reach for when they want to exclude bad data, route rows down different branches, or narrow a dataset before an expensive downstream step.

Typical shapes:

- Single-condition retain: `Status = "Approved"` — keep approved rows only, one output.
- Multi-condition AND: `Status = "Approved" AND Amount >= 1000` — both must hold.
- Dual-path split: same conditions, but `useFalsePath: true` so downstream nodes can process the kept and dropped rows differently.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/filter.json`. This file focuses on behavior and gotchas.

## Building a filter (use node_builders)

`../scripts/workflow/builders.py` owns the wizard-filter shape — flat `filter[]` clause rows are the truth field; the runtime and FE compile them to a pipeline server-side (PLAT-5786), so the skill emits NO `pipeline`/`dataFilterExpr`/`dataFilterLookUp`:

```python
f.add(nb.filter_node("Keep", [
    nb.cond("Status", "eq", "Approved", "string"),
    nb.cond("Amount", "gte", 1000),
], joiner="and"))
```

Operators come from `cond()` and the registry (comparison / text-LIKE / presence / boolean). Two non-obvious facts the builder encodes: NOT-LIKE variants compile to operator **`nlike`** (not `not_like`), and **`is_null`/`not_null` ARE supported** (they compile to a `unary` transform — an earlier builder wrongly rejected them).

Multiple conditions combine by `joiner` (`and`/`or` — no mixed AND/OR). For a **dual-path** filter, build with `filter_node(..., false_path=True)` and wire the branches with `filter_outlet(flow, filter_id, "true")` (`|0`, kept) and `"false"` (`|1`, dropped).

### Choosing the mode — prefer wizard

**Default to wizard mode (`filter_node`).** It is the structured, lower-risk surface: each clause is one `DataFilterRule` row the BE compiles deterministically, and it round-trips cleanly through the FE filter-builder UI. Reach for **expression mode (`filter_expression`) only when the filter genuinely cannot be expressed as a flat list of column-vs-value clauses** — specifically:

- **Inline transformation of a column before comparing** — e.g. `` UPPER(`Code`) = "X" ``, `` TO_NUMBER(`Amt`) >= 0 ``, `` LENGTH(`Id`) > 8 ``, arithmetic like `` `Gross` - `Tax` > 0 ``. Wizard clauses compare a raw column to a value; any function/arithmetic on the left side needs expression mode.
- **Nested or mixed AND/OR logic** — e.g. `(a AND b) OR c`. Wizard joins clauses with a single `joiner` (all-AND or all-OR), so anything with grouping/precedence needs expression mode.

A simple column-vs-value filter — even multi-clause, as long as it's all-AND or all-OR — should be wizard. If you find yourself writing an expression that is just `` `Col` = "x" AND `N` >= 0 ``, use wizard instead.

### Wizard clause contract — `DataFilterRule` is the source of truth

Each `filter[]` row mirrors **`DataFilterRule`** (`savant-common/expr/.../DataFilterRule.java`), the exact shape the BE wizard compiler (`DataFilterCompiler.toExpression` → `ExpressionCompiler.createFilterConfig`) consumes. Build rows with `nb.cond(...)`; the fields are:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | column display name, unquoted (the compiler backtick-wraps it) |
| `conditionalOperator` | yes | from the registry `conditionalOperators` (e.g. `=`, `!=`, `LIKE_CONTAINS`, `IS_EMPTY`, `IS NULL`, `IS_BEFORE`) |
| `value` | for value-taking ops | **must be empty/absent** for no-input ops (`IS_EMPTY`, `IS NULL`/`IS NOT NULL`, boolean `IS …`, relative-date ops) — a no-input op with a value is dropped as invalid |
| `dataType` | yes | lowercase `string`/`integer`/`number`/`date`/`datetime`/`boolean` (round-trips to the `LogicalDataType` enum); drives number-vs-string formatting and `TO_DATE` wrapping |
| `logicalOperator` | per row | `AND`/`OR`; **ignored on the first row** |
| `dateOperator` + `date` | date clauses | `EXACT_DATE` uses an ISO `date`; relative ops (`_DAYS_AGO`, …) strip `value` |

`id` is **not** part of `DataFilterRule` — it is a React-only key the FE editor uses; the BE ignores it (`@JsonIgnoreProperties(ignoreUnknown=true)`). The builder emits it for FE-render compatibility, but it is not part of the truth contract.

**For the exact per-operator syntax** — every conditional operator's emitted clause, value/date rules, the full `dateOperator` vocabulary, `IS_IN`/`LIKE` shapes, and multi-rule joining — see `filter-rule-syntax.md`. Reach for it for any clause that isn't a plain comparison (dates, value lists, empty/null/boolean).

### Free-form expressions: `filter_expression(name, expression)`

For the complex cases above, `filter_expression(...)` emits the boolean expression as the truth field in `rules[0].expression`; the runtime compiles it server-side (the skill builds no pipeline). The expression grammar authority is `savant-common/expr` (Pratt parser + `ScalarFunctions`) — author only from the supported subset in `node-builders-api.md` / `expression-language.md`. A filter expression must return a boolean. Backtick-quote column names with spaces: `` CONTAINS(`Country`,"a") AND `IdNum` >= 0 ``.

Not yet in the builder: `IS_IN`/`IS_NOT_IN` (period buckets) and date comparisons (`IS_BEFORE/AFTER/IS_ON_OR_BEFORE/AFTER` with a `dateOperator`). Author those by emitting the `DataFilterRule` row directly per `filter-rule-syntax.md` until `cond()` supports them.

## Invariants

- For unary operators (`IS NOT NULL`, `IS NULL`, `IS_EMPTY`, `NOT IS_EMPTY`, boolean `IS ...` operators), `value` must be `""` (empty string), not null or omitted; `date` must also be `""` and `dateOperator` must be omitted.
- For date-comparison clauses with `dateOperator: "EXACT_DATE"`, `value` must be `""` and `date` must be a non-empty ISO date string. The reverse pairing (date in `value`, empty `date`) does not load.
- For date-comparison clauses with `dateOperator: "_DAYS_AGO"` or `"_MONTHS_AGO"`, `value` must be the count as a string (e.g. `"120"`) and `date` must be `""`. The product computes the actual cutoff at evaluation time relative to `TODAY()`.
- `dateOperator` is only meaningful when the clause uses a date-comparison `conditionalOperator` (e.g. `IS_ON_OR_AFTER`, `IS_ON_OR_BEFORE`). Setting `dateOperator` on a non-date clause is ignored.
- `filter[].dataType` must match the column's actual type. Mixing (e.g. `dataType: "string"` on a date column) produces incorrect comparisons, not a load error — so it won't surface until the flow runs.
- Author the truth field only: wizard `filter[]` clause rows, or `rules[0].expression` for expression mode. Do **not** hand-build `pipeline`/`dataFilterExpr`/`dataFilterLookUp` — the runtime/FE compile from the truth field (PLAT-5786). `node_builders` emits these deprecated cache keys as cleared (`null`) so editing a legacy node clears any stale hand-built caches on save.
- **Building a dual-path filter is one rule:** set `false_path=True` and wire each branch with `filter_outlet(flow, filter_id, "true"|"false")`. Do not author outlet child nodes, set their ids, or wire the parent's embedded `out_1` — the toolchain builds the children at finalize. *(Finalized shape, for inspection only: two outlet children `{parent}|0` (True) and `{parent}|1` (False); the parent's single `out_0` fans to both. Index is positional — always `|0`=True, `|1`=False. A no-split filter has no `|N` children and wires straight downstream.)*
- `useFalsePath` cannot be toggled via JSON alone on a live flow — the canvas maintains the outlet children separately. If you're writing config via the canvas and flipping this toggle, the DOM will add/remove the outlet pseudo-nodes for you; don't try to synthesize them manually in the browser.

## Interpretation

### Reading the filter's effect on row counts

The row count delta is the whole point of inspecting a filter. Compare the filter's input row count to its output. Two paths, two deltas when `useFalsePath` is on:

- Input: N rows.
- True path (or sole output): N_true rows.
- False path (if dual): N_false rows. Should satisfy `N_true + N_false == N` exactly.

If the sum doesn't match, the filter likely hasn't run or you're looking at stale output.

A real zero-row output means upstream produced rows and the filter dropped all of them — investigate the clauses. (This is distinct from a filter that simply hasn't been run yet, which produces no output at all.)

### Operator labels differ from JSON

UI operator labels differ from the JSON `conditionalOperator`: "contains"→`LIKE_CONTAINS`, "does not contain"→`NOT LIKE_CONTAINS`, "is on or after"→`IS_ON_OR_AFTER`, and so on. Expression-mode filters carry `config.mode: "expression"` with the real logic in `rules[0].expression` (legacy wizard fields blank; older exports may also carry a stale compiled `pipeline.steps`, but the truth field is the expression).

## API edit support

Filter edits are made through the deterministic regenerate-and-merge path: `_filter_config(...)` / `filter_update(existing_node, ...)` regenerate the truth-field config (wizard `filter[]` clause rows or `rules[0].expression`, with the deprecated `pipeline`/`dataFilterExpr`/`dataFilterLookUp` cache keys emitted as cleared `null`) and merge it onto the live node, preserving id, wiring, and unmodeled fields. Clearing those keys overwrites any stale hand-built caches a legacy node carried. Because `filter_update` takes the **full conditions list**, this covers editing an existing clause AND **adding or removing clauses** — the clause count is just the length of the list, and it doesn't change the node's outlets. Verify by re-fetching the recipe and inspecting API output when data behavior changes. Do not use config-panel, on-canvas inline, DOM, or recipe state write paths.

The one filter change that is NOT this path is **toggling the false path** (`useFalsePath`): that adds or removes the `|0`/`|1` outlet branches, so it is topology, handled by the editor's add/remove-node rules — not a config-only update. If a requested change cannot be represented safely in recipe JSON, route through the downloader -> builder -> creator rebuild path.

## Gotchas

- **API save stays enabled with no pending changes.** Known product bug. The editor must not use `button.disabled` as the dirty signal; diff the current form values against a pre-edit snapshot instead. 
- **Preview row count unchanged across filter tweaks doesn't mean the change failed.** The preview may be showing the input rather than the output, or both branches of a dual-path filter may partition the same dataset without narrowing totals. Always verify the persisted recipe and active output source before concluding an edit did not land.
- **Preview menu title may read "undefined".** The button title pattern is `"Preview the <source> of the <Type> node."` but when the product can't resolve `<source>` it renders `"Preview the undefined of the Filter node."`. Don't over-constrain title-based selectors.
- **Outlet pseudo-nodes disappear when `useFalsePath` is false.** Toggling off doesn't just mark `|1` inactive — it removes both `|0` and `|1` from the DOM and reverts to direct edges. If your snapshot logic is keyed on outlet presence, account for this transition.
