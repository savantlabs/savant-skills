---
registry_summary: "Applies one or more find/replace rules across selected fields."
---

# search_replace

## Business purpose

Applies one or more find/replace rules across selected fields. It is meant for targeted text cleanup such as replacing known tokens, standardizing labels, removing unwanted substrings, or applying the same replacement rule to several columns.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/search_replace.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

No verified `node_builders` constructor yet. Inspect existing `search_replace` nodes with this doc and the registry, but do not generate a new node from registry hints until an export-backed shape and constructor are added.

## Invariants

- In the current app palette this appears as **Search and Replace**; the exported type string is `search_replace`.
- `fields` must reference existing upstream columns.
- `rules` should be evaluated as text replacement rules, not as formulas or expression-language operations.
- `caseSensitive` changes matching behavior for all configured rules.
- `wholeWord` changes whether partial substring matches are replaced.
- Row count should not change. This node changes values in selected fields; it does not filter, split, or aggregate rows.

## API edit support

Existing-node edits require documented recipe fields, validation with `savant.py validate workflow`, and the editor's normal save/verify loop. Creating a new `search_replace` node is not supported until `../standards/node-builders-api.md` moves it out of "Shape NOT verified" and a constructor exists.

## Gotchas

- **Effect is value-only on selected fields.** The same rows remain in the same order; only matched text in the selected `fields` changes, and unselected fields are unchanged.
- **Use this for literal cleanup, not complex formulas.** For conditional logic, derived columns, regex-like transforms, or type-aware calculations, use `edit`.
- **Scope matters.** Selecting too many fields can replace matching text in columns that should remain untouched.
- **Whole-word behavior needs verification for punctuation.** Before relying on word-boundary behavior around symbols, validate against a small sample.
- **Registry coverage is authoritative.** Treat the current palette and `../registry/components/search_replace.json` as the production source of truth until live write probes expand the registry.
