# Data Prep And Normalization

## Objective

Create stable, typed, business-ready fields after source ingestion so downstream logic never depends on raw file quirks.

## Use When

- Building or validating workflows from spreadsheets, CSVs, exported reports, PDFs/images, or mixed systems.
- Raw values need cleanup: blanks/nulls, currency symbols, accounting parentheses, date parsing, typed join keys, fallback amounts, output-grain filters, or review flags.
- Inspection/validation shows fragile headers, live schema mismatch, subtotal/footer rows, or downstream references to raw fields.

## Default Action

1. Use source facts from the handoff. Tabular sources use `Source -> Adapter`; binary/PDF/image sources use extraction first; JSON/XML text sources use a parser first.
2. Treat the first tabular node after ingestion as the schema contract. The adapter owns canonical names and types when the source is tabular.
3. Add `Normalize ...` Transform only for value cleanup beyond that contract, and do it immediately after the adapter/extraction/parser.
4. Use normalized fields in filters, joins, summaries, FX, dates, amounts, and final formulas.
5. Add output-grain filters immediately after normalization when source exports include subtotal/footer/spacer/non-business rows.
6. Use a finalization Transform before destinations for report-facing selection, order, hides, and renames.
7. Verify row counts, key totals, and targeted sample rows at the grain the business expects.

## Do Not

- Do not redefine source names/types in normalization; that belongs to the source unit's adapter/extraction/parser contract.
- Do not put raw source fields directly into joins, filters, summaries, or final formulas.
- Do not apply the default `UPPER(TRIM(TO_TEXT(...)))` key normalization to keys an Alteryx migration guide says Alteryx compared raw; those keys use blank-safe `COALESCE(TO_TEXT(x), "")` and the difference is a recorded P2 decision (see `../../solutions/alteryx/migration.md`).
- Do not defer data prep to a later stage when the required source field already exists. Move cleanup upstream unless the field is created by a later join, aggregate, pivot, AI/classification step, or branch decision.
- Do not treat a binary/PDF/image source as tabular without an extraction step.
- Do not claim live schema correctness from a local sample when no evidence links that sample to the Savant dataset.
- Do not use `orderedFields` to drop columns. Use `hiddenFields`; `orderedFields` only reorders.

## Schema Source

- **Build-only without API, dataset backed by a session file:** treat the file as the authoritative schema, shape, and representative data for the matching Savant dataset, assuming the live dataset mirrors the upload. Use it to build a `user_supplied` profile with `observed_schema`, expected schema, join-key types, date/number cleanup, and output-column decisions.
- **Build-only without API, no matching file:** use a provided schema/sample if one exists, but mark live references as assumed from that evidence and unverified against the live dataset. If schema-driven workflow choices matter, ask for the file or schema instead of guessing from names.
- **Creation/import with API:** profile the live Savant source and replace sample assumptions with actual field names, ids, types, content type, and row/sample evidence.
- **Tabular sample:** use its columns/types and pass schema hints keyed to the source node when needed.
- **PDF/image/binary sample:** source has `Content`; add extraction (`vision`/parse) and schema-hint the extraction output, not the binary source.

## Normalize Values

Use one `Normalize ...` Transform immediately after each source adapter/extraction/parser when values need cleanup. This is the first stable point where raw source quirks should be isolated. If a field will be used as a join/group/filter key anywhere downstream, normalize it in that source-prep step once and reuse the prepared field; do not recreate key-cleanup logic at each later join. If you discover later cleanup that only depends on existing source fields, move it back into this source-prep step.

- text: trim, normalize missing tokens, standardize case for comparisons, preserve raw audit text when useful
- numbers: strip currency/thousands/accounting parentheses, cast once, keep missing as `NULL` unless zero is confirmed
- dates: parse to canonical date fields; flag missing or invalid ranges
- join keys: create explicit normalized key fields during source prep for every field that will be used as a join key anywhere in the workflow. For string/alphanumeric keys, default to text + trim + case-insensitive matching (`UPPER(TRIM(TO_TEXT(...)))` or equivalent) unless the user confirms that case or spaces are business-significant. Normalize formatting characters and flag missing keys. When source data shows shape differences such as `0245` vs `245`, prefixes/suffixes, embedded labels, or trailing digits, derive comparable key fields only from profiled evidence or confirmed business intent, then join on those derived fields rather than raw source columns.
- amounts: create one canonical business amount plus source/fallback/flag fields
- quality: add explicit review flags for missing ids, fallback values, missing FX, duplicate keys, unexpected categories, or invalid dates

Downstream logic references normalized business fields such as `Reporting Amount`, `Currency Code`, `Join ID`, `Start Date`, `End Date`, and `Review Flag`.

## Verify Data Prep

For data-prep validation, confirm:

- live schema was profiled when available
- downstream nodes reference adapter/normalized names, not raw headers
- known join keys are normalized once in source prep, immediately after each source adapter/extraction/parser, then reused by every downstream Blend/Join
- late cleanup steps are justified by fields created later; cleanup on already-available source fields has been pushed back into source prep
- output-grain filters run before enrichment joins
- joins use same-type normalized keys and preserve expected rows
- every Blend/Join condition uses explicit normalized key fields or has a documented reason why the source fields are already canonical
- filters use typed normalized fields and row-count deltas make sense
- summaries reconcile additive totals before and after aggregation
- FX/currency logic has explicit reporting currency and missing-rate flags
- destination rows/columns match the intended business grain
- mismatches against reference output are classified as a workflow defect or documented assumption change

## Failure Pattern To Prevent

Report exports often need post-import fixes when preflight misses live source quirks: embedded newlines in headers, subtotal/footer rows, raw amount ambiguity, or leaked staging columns. Prevent that by profiling the live source, isolating fragile values in normalization, filtering to business grain before enrichment, defining the canonical amount once, flagging fallbacks, and reusing normalized fields everywhere.
