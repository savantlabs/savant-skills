# Node Documentation Rules

## Objective

Use this when writing or refreshing Savant step descriptions. A step description is the business-readable readout of that step's configuration: comprehensive enough for a reviewer or auditor to understand the data impact, but written for a domain expert who should not need to know Savant component names, JSON, or settings-panel mechanics.

## Default Action

For every data-processing step, describe the configuration in the language of the business process:

1. Start with one sentence for the step's purpose.
2. List the material settings that affect rows, columns, matches, calculations, grouping, branches, or outputs.
3. State the data impact: rows kept/removed, columns added/hidden/reordered, grain changed, records matched, outputs written, or AI/API result created.
4. Include formulas only for calculated fields or formula-based rules, translated to Excel-style notation when possible.
5. Include important edge handling: blanks, zero division, rounding, sign changes, absolute values, duplicate keys, unmatched rows, default values, date cutoffs, or confidence thresholds.

Descriptions should be generated from the node's actual configuration whenever possible. If a configuration changes, the description must be refreshed in the same edit. User-authored notes may add business context, but they must not contradict the generated configuration readout.

## Step Labels

A step's label (the node's display `name`) is what a reader scans on the canvas before opening anything. Make it understandable on its own:

- Use a short **business action** in the user's words: "Find possible GL matches", "Compare amount and date", "Keep reasonable matches", "Choose best GL match for each statement charge", "Resolve duplicate GL matches", "Keep final one-to-one matches".
- Do **not** name the Savant component (Transform, Filter, Blend, Join, Rank, Stack, Output, Source, Destination) unless that is genuinely how the business user would describe the step.
- Keep it short enough to scan under a node; the precise configuration belongs in the description, not the label.
- A label may trade a little technical precision for understandability — "Keep reasonable matches" beats "Filter on confidence ≥ 0.8".
- Seed labels from the plan's `business_steps`; do not invent generic names like "Transform 1" or "Step 3".

## Group Headers and Descriptions

A group frames a business phase. Its header and description are **canvas rich text rendered by the builder, not Markdown** — pass them to `Flow.group(name, members, header=..., description=...)` as plain business text. Do not write `**bold**` (it renders literally) or hand-author HTML.

**Header** — name the business phase in the user's language: the business object and action ("Match statement charges to GL postings", "Classify reconciled and exception items", "Prepare statement activity", "Produce reconciliation reports"). Avoid technical component words (join, filter, transform, rank, stack) and vague generic stage names ("Match the records", "Classify the items", "Produce the outputs"). The header answers: *what business job is this section doing?*

**Description** — explain the business logic or reasoning, not the step sequence. The description answers: *what logic is this section applying, and why does it exist?*

- Let a reader understand the section without opening every node.
- State exact thresholds and rules when they are central to the logic — they are auto-emphasized in the rendered header, so write the real number (`within $0.01`, `within 5 days`), never a vague stand-in like "close enough", "confirmed tolerance", or "best match".
- Do not list every step in order unless the order itself is the business logic.
- Keep it to 1–2 sentences; use a real line break (`\n`) to separate dense clauses so each renders on its own line.

Example description (one line break between two clauses):

```text
Matches statement charges to GL postings when the vendor matches, the amount is within $0.01, and the dates are within 5 days.
If more than one match qualifies, it keeps the closest one and prevents the same statement line or GL posting from being used twice.
```

## Fidelity Rules

- Do not write generic descriptions such as "Prepare data" or "Calculate metrics" when the config contains specific operations.
- Do not hide material behavior behind product terms. Explain what the setting does to the data.
- Do not mention formulas for a node type unless that configuration actually contains a formula or calculated expression.
- Do not copy raw internal expression syntax when an Excel-readable formula is clearer. Preserve exact field names and calculation logic.
- Do not omit configuration details that would change an audit walkthrough, downstream output, or business interpretation.
- If the config includes a technical expression that cannot be safely simplified, show the closest Excel-style formula first and then add the exact expression under "Implementation expression" only when fidelity requires it.

## Recommended Shape

Use concise Markdown. For simple steps, one paragraph is enough. For multi-operation steps, group related changes under labeled sections in a consistent order (see the Transform readout below for the canonical Transform sections):

```markdown
Prepare the reconciliation summary measures used in the final output.

**New / calculated columns**
- `Total Reconciling Items`: total amount requiring reconciliation review.
- `Match Rate (%)`: `Matched Pairs / Statement Activity Total * 100`.
- `Unexplained Difference`: remaining amount after matched and explained items are accounted for.

**Column order**
- Summary totals before the supporting activity columns.

**Hidden columns**
- Intermediate calculation fields not part of the reviewer-facing output.
```

## Node-Specific Readouts

### Source / Input Data

Describe what data enters the process:

- source file, dataset, or connected system display name
- business role of the data, such as statement activity, GL activity, customer master, or invoice detail
- static/uploaded vs system-backed context when it affects refresh or trust
- standardization or extraction that happens immediately after source intake, if this source unit owns it

### Adapter / Standardization

Describe the schema contract:

- source columns mapped to canonical business column names
- type changes such as text to number, text to date, or boolean normalization
- whether unmapped fields pass through or are intentionally excluded
- required fields and what downstream logic depends on them

### Transform

Describe column-level changes. A Transform does not add or remove rows. A single Transform may legitimately add columns, rename/convert, reorder, and hide fields all at once — that is the preferred design over splitting the work across separate nodes — so document it with a predictable, labeled structure instead of one flat list.

Lead with one sentence for the step's purpose, then group the remaining readout into these sections, **always in this order**, including only the sections whose operations are present in the config:

1. **New / calculated columns** — each added column, in dependency order, with its Excel-style formula and business meaning.
2. **Renamed / converted columns** — renames (`old` → `new`) and type changes (text→number, text→date, boolean normalization), plus any default-value or null handling.
3. **Column order** — the output ordering, when column order is set.
4. **Hidden columns** — fields suppressed from the output, and why (e.g. intermediate calculation fields).

Use each section's name as a bold sub-heading. Omit any section with no corresponding operation — never write an empty or "N/A" section. Do not imply a formula exists for a renamed, reordered, or hidden column. For a single-operation Transform, one sentence or a single section is enough; the labeled structure is for multi-operation steps.

Use Excel-style notation for formulas — one notation only (per Fidelity Rules); add the exact expression under "Implementation expression" only when fidelity requires it.

```markdown
Prepare the reconciliation summary measures and tidy the reviewer-facing column set.

**New / calculated columns**
- `Match Rate (%)`: `Matched Pairs / Statement Activity Total * 100` — percentage of statement activity that matched; rounded to one decimal place.
- `Unexplained Difference`: remaining amount after matched and explained items are accounted for.

**Renamed / converted columns**
- `Cust` → `Customer`.
- `Post Date` converted from text to date.

**Column order**
- Summary totals first (`Match Rate (%)`, `Unexplained Difference`), then the supporting activity columns.

**Hidden columns**
- Intermediate calculation fields that are not part of the reviewer-facing output.
```

### Filter

Describe row-level rules:

- rows kept by the true/kept path
- rows removed or routed to the false path
- all conditions and whether they combine with AND or OR
- formula expression only when the filter is expression-based
- business consequence, such as excluding closed periods or routing exceptions for review

### Blend / Join

Describe record matching or enrichment:

- left/business-driving input and right/reference input
- match keys and operators
- join behavior: matched only, retain all left records, retain all right records, or full outer
- unmatched-output branches, if enabled
- duplicate-key or one-to-many risk when relevant
- right-side fields brought forward or duplicate fields renamed by Savant

### Fuzzy Match

Describe approximate matching:

- two sources compared and the key fields used
- provider/model if it affects business trust
- confidence score output
- threshold or review routing, if present downstream
- dropped/unmatched behavior

### Summarize / Rollup / Aggregate

Describe the grain change:

- grouping fields, stated as "one row per ..."
- each measure and aggregation method
- row-count change expectation
- count behavior: row count, nonblank count, distinct count, or sum of indicator flags
- date rollup period for rollups

Example:

```markdown
Summarizes statement activity to one row per account and period.

- Groups by `Account` and `Period`.
- Calculates `Statement Activity Total` as the sum of `Amount`.
- Calculates `Statement Activity Count` as the count of rows in each group.
```

### Deduplicate / Sample

Describe which rows survive:

- duplicate definition fields
- sort/tie-break fields used to choose the retained row
- top-N count and whether it is per group or overall
- business reason for keeping or excluding records

### Pivot / Unpivot / Stack / JSON / XML / Split / Explode

Describe the shape change:

- columns converted to rows or rows converted to columns
- identity fields preserved
- value/name fields created
- JSON/XML path or repeated element extracted
- stacked inputs and how their columns align
- row multiplication risk for explode/split

### GenAI / Vision / API Service

Describe the external or AI-assisted result:

- input fields sent to the model/service
- output fields expected
- prompt or instruction summary in business language
- row limit or batching limits when configured
- provider or endpoint only when it affects trust, cost, or review
- confidence, evidence, or manual-review fields generated

### Destination / Output

Describe what leaves the process:

- output name and file/system type
- intended audience or review use
- expected grain and key columns
- sorting when configured
- whether this output writes externally during Run mode

## Auto-Update Rule

Any create or edit that changes a step's configuration must update that step's description in the same change. This includes formulas, columns, filters, join keys, grouping, sorting, output definitions, branches, AI prompts, and schema-shaping settings.

When a change has no business impact on the description, explicitly verify that the existing description still reads correctly rather than leaving it stale by accident.
