---
registry_summary: "Builds parent-child paths and optional rollups for self-referential data such as employee-manager or account-parent structures."
registry_details: "Supports rollups such as totals, counts, averages, min/max, distinct counts, and joined text."
---

# hierarchy (Recursion)

## Business purpose

Builds a recursive parent/child path over self-referential data, such as employee-to-manager, account-to-parent-account, or part-to-assembly relationships. It starts from an id field and a parent id field, walks the chain, and can aggregate values along that path into hierarchy columns.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/hierarchy.json`. This file focuses on behavior, writing, and gotchas.

Use `../standards/node-builders-api.md` for the `nb.hierarchy(...)` constructor. This component doc is for behavior, gotchas, and edit semantics.

## Invariants

- In the current app palette this appears as **Recursion**; the exported type string is `hierarchy`.
- `idField` must identify the current row's entity. `parentIdField` must reference the parent entity using the same key domain.
- The parent chain must terminate. Cycles or self-parenting records can produce invalid hierarchy output or run failures.
- Rows with blank parent ids are roots.
- Aggregation output columns must have unique `tgt_col.id` values.
- `JOIN_STR` and `JOIN_STR_DISTINCT` path-style aggregations should include a delimiter in `params.delimeter`; old exports also preserve it in `extra.originalDelimeter`.
- Output columns from hierarchy are additive: the original row data remains, and configured hierarchy aggregate columns are appended or replaced according to their target names.

## API edit support

Use `hierarchy(...)` for generation. Existing-node config edits use the shared regenerate-and-merge path by deriving config from `hierarchy(...)` or `update_config(...)`, then validating with `savant.py validate workflow` and saving through the editor's normal loop. Changing id/parent fields or aggregations can change hierarchy output columns, so verify downstream references and row behavior after save.

## Gotchas

- **Row count is unchanged; columns are additive.** Each input row stays one output row, enriched with the configured hierarchy/path columns. For employee-manager data, path columns typically hold a delimiter-separated management chain from the row up to the root.
- **Use the app label when talking to users.** Business users will recognize **Recursion** more readily than `hierarchy`.
- **Cycles are data problems, not configuration details.** If output is missing or the run fails, check for records where an id eventually points back to itself through the parent chain.
- **Delimiter is misspelled in exports.** Existing JSON uses `params.delimeter` and sometimes `extra.originalDelimeter`; preserve that spelling when generating or editing JSON.
- **Older exports may have bad output data types.** At least one real export uses `"integer"` for `JOIN_STR` hierarchy outputs. For generated workflows, path/string joins should use `"string"` outputs.
