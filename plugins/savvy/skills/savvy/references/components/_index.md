# Savant components — shared reference library

This directory is a **reference library, not a skill**. It has no `SKILL.md` and is never loaded automatically. The Savant workflow skills (builder, inspector, editor) read from it by relative path when they need type-specific knowledge.

Each file here is **one Savant node type**, named `{type}.md` to match the canonical type string used in the workflow JSON (`filter`, `edit`, `source`, `blend`, `summarize`, ...).

## Why this exists

Before this library, knowledge about each node type was split across three places:

- The builder's `schema-reference.md` had the JSON schema.
- The inspector's `SKILL.md` had its own per-node notes.
- The editor needed its own API recipe guidance.

Three copies drift. One copy per node type, read by all three skills, stays consistent.

## File conventions

Every component file follows the same section order:

1. **Business purpose** — one paragraph. What this node does for a workflow in business terms, not JSON terms. This is what a human would say to explain the node to another human.
2. **Registry** — a short pointer to the matching JSON registry file under `../registry/components/`. Schema, enum values, and validator-facing rules belong there, not in Markdown.
3. **Invariants** — behavior rules and failure modes that are useful for humans to understand. If the rule is only a config enum or structural schema check, put it in the registry JSON instead.
4. **API/config semantics** — how this node type is represented in recipe JSON, what fields matter, and how to interpret API output evidence. Browser/DOM notes belong here only when they describe a rendered visual or UI-only fact that the API cannot represent.
5. **Edit support notes** — which recipe fields can be safely changed through the API helper. If an edit cannot be represented as a documented API recipe diff, route through the downloader -> builder -> creator rebuild path instead of using DOM or store writes.
6. **Gotchas** (optional) — known product bugs, templating quirks, or counterintuitive behaviors specific to this type. Cross-reference substrate docs when the behavior is broader than one type.

## Cross-cutting references

- **Expression language** (functions, operators, compilation rules for formatting casts, CASE/IF type-consistency rule): [`expression-language.md`](./expression-language.md). Used by `edit`, `filter`, `pdfilter`, `summarize`, `rollup`, `gen_ai`.
- **Run modes** (Analyze / Test / Run): `../substrate/run-modes.md`
- **Business-user response rules** (finance business-user language, display names vs ids, limited product terms, and response shape): `../standards/business-user-response-rules.md`. Applies to every skill, not just node-specific logic.
- **Canvas layout rules** (readable layout, group composition, edge routing — how the builder lays out the diagram in JSON): `../standards/canvas-layout-rules.md`. Applies when a skill creates or changes layout.

Component files should link to these rather than duplicating their content. API save mechanics belong in `../scripts/savant.py app`.

## Reference precedence

- Use `../standards/node-builders-api.md` first for supported Builder/Editor constructor calls.
- Use this index and the registry to identify which component types exist.
- Use `{type}.md` for behavior, failure modes, and documented edit semantics.
- Use registry JSON for enum/schema facts, but never create a node from registry hints when the API reference marks the shape unverified.

## Catalog

| Type | File | Primary use |
|---|---|---|
| filter | [filter.md](./filter.md) | Row-level filtering, optional T/F split |
| edit | [edit.md](./edit.md) | Column transformations, formulas, type changes |
| source | [source.md](./source.md) | Data ingestion (Excel, CSV, PDFs, connectors) |
| adapter | [adapter.md](./adapter.md) | Header mapping and schema normalization |
| format | [format.md](./format.md) | Bulk column cleanup, hiding, type changes, header replacement |
| search_replace | [search_replace.md](./search_replace.md) | Literal find/replace cleanup across selected fields |
| summarize | [summarize.md](./summarize.md) | Group-by aggregations |
| pdsummarize | [pdsummarize.md](./pdsummarize.md) | Group-by aggregations pushed into supported database sources |
| hierarchy | [hierarchy.md](./hierarchy.md) | Recursive parent/child hierarchy paths and path aggregations |
| blend | [blend.md](./blend.md) | Joins (inner/left/right/outer), matched vs outliers |
| fuzzy_match | [fuzzy_match.md](./fuzzy_match.md) | AI-assisted fuzzy joining |
| deduplicate | [deduplicate.md](./deduplicate.md) | Remove duplicate rows |
| vision | [vision.md](./vision.md) | AI document extraction (PDFs, images) |
| gen_ai | [gen_ai.md](./gen_ai.md) | LLM inference on row data |
| json | [json.md](./json.md) | Flatten / explode nested JSON |
| xml | [xml.md](./xml.md) | Select, extract, or convert XML content |
| split | [split.md](./split.md) | Split delimited text into rows or columns |
| explode | [explode.md](./explode.md) | Expand a small-side input across a main input |
| apiService | [apiService.md](./apiService.md) | Current API request tool; legacy exports may use service/APIService |
| service | [service.md](./service.md) | Legacy API calls or LLM service mode |
| destination | [destination.md](./destination.md) | Data output (files, connectors) |
| group | [group.md](./group.md) | Visual section box around child nodes |
| text | [text.md](./text.md) | Canvas annotation, no data |
| notes | [notes.md](./notes.md) | Sticky-note canvas annotation, no data |
| outlet | [outlet.md](./outlet.md) | Pseudo-node for split outputs (filter T/F, blend matched/outliers) |
| rollup | [rollup.md](./rollup.md) | Time-series aggregations |
| unpivot | [unpivot.md](./unpivot.md) | Wide → long reshape |
| pivot | [pivot.md](./pivot.md) | Long → wide reshape |
| pdfilter | [pdfilter.md](./pdfilter.md) | Filter pushdown into source reads |
| sample | [sample.md](./sample.md) | Row-count restriction (FIRST_N / random sample) for previews and audit reviews |
| multi_stack | [multi_stack.md](./multi_stack.md) | Stack rows from N inputs (UNION ALL); the only N-ary inlet node |

Catalog is the source of truth for "which node types exist"; if you add a new file here, add a row above.

Cross-cutting (not a node type): [expression-language.md](./expression-language.md) — embedded grammar for expressions used in edit/filter/pdfilter/summarize/rollup/gen_ai.

## Authoring notes

- **Shape is owned elsewhere — don't restate it.** The deterministic builder (`../scripts/workflow/builders.py`) emits correct node JSON by construction, and the registry JSON owns schema/enums. A component file carries only what those can't: when/why to use the node, and runtime gotchas and failure modes. A "Building" section should be one example plus a pointer, not a field-by-field walkthrough; if you're enumerating config fields or copying enum/operator lists, trim it. `source.md` and `edit.md` are the reference for the right length.
- Keep Markdown focused on how the component behaves, when to use it, how its recipe/config/API output should be interpreted, and what commonly breaks. Keep schema, enum lists, supported operators, and validator-facing config details in the JSON registry.
- Prefer "what breaks when you violate this" framing for invariants. Invariants without a failure mode are usually taste, not rules.
- Edit recipes should use the documented API path and be tested against the live app before they land here. Speculative selectors belong in plan docs, not reference files.
- Keep business purpose short. Anyone reading a component spec is already past "what does this do at a high level" — they're here for specifics.
