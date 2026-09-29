# Alteryx Migration Cleanup

## Objective

Clean converted Alteryx workflows only when the request or inspection supports it, preserving business behavior over visual neatness.

## Use When

- Existing Savant workflow + user mentions Alteryx, migration, conversion, slowness, hanging, optimization, maintainability, standards cleanup, or broad visual polish.
- Inspection shows likely migration artifacts: orphan nodes, dangling outlets, outlet-only routing leftovers, unsupported/migration-only config, very wide schemas with late cleanup, no-op transforms, duplicate-field errors, poor converted labels, grouped-field count arguments (a summarize COUNT whose argument is also a group-by field), or Blend plus Stack recombination.

## Default Action

1. Classify confidence:
   - **Strong:** user says Alteryx/migration, or 3+ signals, or hidden/migration config plus errors/hanging.
   - **Likely:** 2 signals.
   - **Weak:** 1 signal; mention only if relevant.
2. For a narrow edit, offer: requested edit only vs. broader cleanup pass.
3. For slowness/hanging/optimization/standards cleanup, treat cleanup as in scope after confirmation.
4. Inventory the whole workflow before editing:
   - connected vs disconnected nodes
   - dangling outlets
   - unsupported config
   - wide schemas and late deselection
   - no-op transforms
   - grouped-field count arguments (summarize COUNT of a field that is also in group-by — Alteryx `Count` translated literally; fix is COUNT of Row, per `../components/summarize.md` "Migration mapping". Note this changes Combo-Count-style values from 0 to the true row count for groups whose field is blank, so verify it as a business-impacting fix, not batch cleanup)
   - Blend plus Stack patterns
   - final outputs and expected grain
5. Batch low-risk cleanup first:
   - remove disconnected/orphan/dangling artifacts with no business role
   - remove unsupported migration-only config
   - remove no-op steps only after proving no row/column/type/name/business change
   - collapse adjacent preparation steps that one component can represent; do not keep readability-only stage breaks unless the user asked for them
   - rename converted labels only when meaning is clear
6. Reduce source pressure early: trace downstream-used columns, push safe field selection upstream, and verify row count/schema after pruning.
7. Verify every business-impacting simplification with row counts, schema, sample rows, and final output preservation.

## Do Not

- Do not use this for a new workflow from an Alteryx file or spec; that is the Alteryx migration solution (`../../solutions/alteryx/migration.md`).
- Do not treat detection as permission to edit.
- Do not silently perform broad cleanup during a narrow edit.
- Do not remove or simplify anything whose business role is unclear.
- Do not prune a shared source/dataset without checking or surfacing shared-use risk.
- Do not replace a left-preserving Blend plus Stack with an inner join unless unmatched rows are proven irrelevant or the user approves dropping them.

## Blend Plus Stack

Converted lookup/enrichment flows often use:

```text
source + lookup -> Blend
matched branch + unmatched branch -> Stack
```

Review before replacing:

- What rows appear in matched, unmatched, stacked/final, and downstream outputs?
- Does the Stack preserve all source rows?
- Are lookup fields optional context or required for the output?

Safe replacements:

- **Left-preserving enrichment:** use a left Blend when all source rows must remain and lookup fields are optional.
- **Exception split:** keep matched and unmatched as separate branches when unmatched rows need review.
- **No replacement:** keep Blend plus Stack when it encodes real business branching more clearly than a single native pattern.

## Done

Cleanup is done only when:

- rollback/export snapshot exists
- broad cleanup was confirmed when not explicit
- unsupported artifacts were removed or intentionally preserved with reason
- final output row count, schema, and key business fields are preserved unless user approved a change
- the deterministic layout metrics were checked when visual/layout cleanup was in scope
