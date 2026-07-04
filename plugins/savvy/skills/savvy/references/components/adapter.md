---
registry_summary: "Standardize column names and types, including dropping columns. Helps in normalizing schema"
---

# adapter (Adapter)

## Business purpose

Header mapping and schema normalization. Adapter maps incoming source headers to a required downstream schema, optionally dropping unmapped columns. It is useful when customer files arrive with slightly different header names but the rest of the process expects stable canonical fields.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/adapter.json`. This file focuses on behavior and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the Adapter shape via `nb.adapter(name, specs, passthrough=False)`, where `specs` is a list of `{"name", "dataType", "mappedFrom", "required"?}`:

```python
f.add(nb.adapter("Normalize",
    specs=[{"name": "Customer", "dataType": "string", "mappedFrom": "Cust Name", "required": True},
           {"name": "Amount",   "dataType": "number", "mappedFrom": "Amt"}]))
```

`passthrough=True` (`passthroughUnmapped`) also passes through unmapped source columns; the default `False` keeps only the configured `specs[]`.

## Invariants

- Every `mappedFrom` should reference an upstream column. Missing mappings produce null, or failed-required-field behavior, depending on runtime settings.
- `specs[].name` values must be unique — duplicates make downstream references ambiguous.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, adapter("x", specs, passthrough)["config"])`. Changing the mapped `specs` changes the output schema, so reconcile downstream references and verify after save.

## Gotchas

- **Adapter does not change row count; it reshapes the schema.** Output columns are the `specs[]` fields (plus unmapped source columns when `passthroughUnmapped: true`). If downstream steps can't find expected fields, check the Adapter mapping before the later transforms.
- **Adapter is schema normalization, not a formula tool.** It maps headers and types. Calculations belong in Transform.
- **Dropping unmapped fields can break later steps.** With `passthroughUnmapped: false`, any source field not listed in `specs[]` disappears.
- **Required fields are business rules.** Do not mark a field required just because it is convenient downstream. Required should mean the incoming file is invalid without that mapping.
- **Display names matter.** `mappedFrom` uses the upstream display header. If the source header changes from `First Name` to `first_name`, the mapping must change too.
