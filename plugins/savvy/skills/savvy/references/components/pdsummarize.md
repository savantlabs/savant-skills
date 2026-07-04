---
registry_summary: "Pushes group-by aggregations down to a database source when the aggregation can run in the database."
registry_details: "Database pushdown supports totals, counts, averages, min/max, and distinct counts."
---

# pdsummarize (Summarize Pushdown)

## Business purpose

A group-by aggregation optimized for database source pushdown. When upstream is a warehouse connector, pdsummarize can push the aggregation into the source query so the warehouse returns grouped results instead of pulling all rows into Savant and summarizing afterward. The business result is the same as a normal summarize for supported functions, but the execution location is different.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/pdsummarize.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

No verified `node_builders` constructor yet. Inspect existing `pdsummarize` nodes with this doc and the registry, but do not generate a new node from registry hints until an export-backed shape and constructor are added.

## Invariants

- Use `pdsummarize` only when the upstream source can support pushdown. If the source is Excel, CSV, PDF, or a post-transform in-memory result, use normal `summarize`.
- Supported aggregate functions are narrower than `summarize`: `SUM`, `COUNT`, `NUNIQUE`, `MIN`, `MAX`, and `AVG`.
- Output columns are the group-by fields plus aggregate target columns. Other upstream columns are dropped, like normal `summarize`.
- Empty group-by is valid when a single global aggregate row is intended.
- Any generated pushdown expression must stay consistent with the visible group-by and aggregate rows.

## API edit support

Existing-node edits require documented recipe fields, validation with `savant.py validate workflow`, and the editor's normal save/verify loop. Creating a new `pdsummarize` node is not supported until `../standards/node-builders-api.md` moves it out of "Shape NOT verified" and a constructor exists.

## Gotchas

- **Output is one row per distinct group-by tuple.** The output row count equals the number of distinct group-by tuples returned by the pushed-down query. Because the aggregation happens at the source, the apparent upstream may already reflect query-side reduction. In the palette this node appears as **Summarize Pushdown**.
- **This is not PDF summarize.** The prefix is pushdown-related (`pd`), like `pdfilter`; it is unrelated to PDF documents.
- **Pushdown is a performance decision.** If the source cannot push aggregation into a query, the node gives little or no benefit over normal summarize.
- **Function support is smaller.** Do not generate `JOIN_STR`, `MEDIAN`, `STDDEV`, `VAR`, `FIRST`, `LAST`, or `MODE` for pdsummarize unless the registry is expanded and the app is revalidated.
- **Prefer normal summarize when unsure.** Normal `summarize` has broader coverage and is better documented in existing examples.
