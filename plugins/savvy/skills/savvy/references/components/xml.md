---
registry_summary: "Parses XML content into selected fields, extracted rows, or JSON text."
---

# xml (XML)

## Business purpose

Parses XML content into rows, fields, or JSON text. XML is used when files or API responses arrive as XML and need to be selected, extracted, or converted before normal transformation steps.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/xml.json`. This file focuses on behavior and gotchas.

Use `../standards/node-builders-api.md` for the `nb.xml_node(...)` constructor. This component doc is for behavior, gotchas, and edit semantics.

## Invariants

- Exactly one inlet and one outlet.
- `mode` must be one of the supported XML modes: `SELECT`, `EXTRACT`, or `TO_JSON`.
- `inputField` must contain valid XML text.
- `path` is required for `SELECT` mode and should match the XML structure.
- `EXTRACT` usually follows `SELECT` when the process needs repeated nested elements as rows.

## API edit support

Use `xml_node(...)` for generation. Existing-node config edits use the shared regenerate-and-merge path by deriving config from `xml_node(...)` or `update_config(...)`, then validating with `savant.py validate workflow` and saving through the editor's normal loop. XML mode/path changes can change rows and output columns, so verify downstream references and row behavior after save.

## Gotchas

- **Each mode produces a distinct output.** `SELECT` keeps the selected XML fragments or records; `EXTRACT` produces structured columns from the selected XML; `TO_JSON` produces JSON text suitable for a downstream JSON step.
- **XML path errors look like empty data.** A wrong `path` often returns zero rows rather than a loud failure. If output is empty, first verify the `path` against the actual XML in `inputField`.
- **SELECT and EXTRACT often work as a pair.** SELECT isolates repeated nodes; EXTRACT turns them into fields.
- **TO_JSON is a bridge step.** Use it when downstream JSON flatten/explode tooling is easier than XML extraction.
- **Namespaces can hide matching tags.** If a path looks correct but returns no rows, check whether namespace handling is needed.
