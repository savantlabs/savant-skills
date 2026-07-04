---
registry_summary: "Pushes row filters down to a database source when the filter can run in the database."
---

# pdfilter (Filter Pushdown)

## Business purpose

A filter optimized for database source pushdown. When upstream is a warehouse connector (Snowflake, BigQuery, etc.), pdfilter pushes its conditions DOWN into the source query rather than filtering in-memory after pulling all the data. The result is the same filtering semantics but dramatically better performance - the source returns only the rows that match.

The authoring surface is the same clause array as regular `filter`, just pushed down to a DB connector source.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/pdfilter.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

## Building a pdfilter (use node_builders)

`nb.pdfilter_node(...)` is **identical to `filter_node` in every way** (conditions via `nb.cond`, `joiner`, `false_path`, `mode`, truth-field-only emission) — see `filter.md`. The only difference: it pushes the predicate into a DB source query.

**GOTCHA: pushdown is not supported on every source.** It errors on a non-DB / api source — use a regular `filter_node` there (see "When to use pdfilter vs filter" below). Pdfilter only helps when the source connector can push the predicate down.

## When to use pdfilter vs filter

- Use `pdfilter` when the source is a database connector and you want the filter pushed to the query for performance.
- Use regular `filter` for in-memory filtering on CSV/Excel sources or for post-join / post-transform filtering that can't be pushed down.

## API edit support

pdfilter shares filter's config core, so config edits work exactly like `filter.md`: regenerate via the generic `update_config(node, pdfilter_node("x", conditions, joiner)["config"])` (editing, adding, and removing clauses are all supported — full clause-list regeneration). See `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). The false-path toggle is topology, not a config edit. Pushdown validity still depends on the source connector (see the gotcha above).

## Gotchas

- **Output reflects source-side reduction.** Because pdfilter pushes the predicate into the source query, the node's output row count can be far smaller than the apparent upstream — the source returns already-filtered rows. The row-count delta analysis is otherwise the same as `filter.md`.
- **Pdfilter vs filter is a performance decision, not a semantics one.** Users sometimes add a pdfilter after a non-database source thinking it's faster. It isn't - it only helps when the source connector can push the predicate down.
- **Date-relative fields must stay paired correctly.** `_DAYS_AGO` and `_MONTHS_AGO` use `value`; `EXACT_DATE` uses `date`. Converting between filter types is mostly placement/performance; don't assume pdfilter changes semantics.
- **Author the truth field only.** Wizard `filter[]` clause rows (or `rules[0].expression` in expression mode) are the truth; the runtime/FE compile the pushdown SQL and any `dataFilterExpr`/`dataFilterLookUp` cache. Do not hand-build or hand-edit those caches — regenerate via `pdfilter_node`/`filter_update`, which emit them cleared.
- **Pushdown may not happen for all operators.** Some operators (e.g. `NOT IS_EMPTY`) may or may not be pushed down depending on the source connector. When users report pdfilter not being faster than filter, check whether their specific operator set supports pushdown for their source type.
