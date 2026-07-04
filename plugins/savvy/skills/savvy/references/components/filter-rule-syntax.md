---
registry_summary: "Authoritative per-operator syntax for wizard-mode filter clauses (DataFilterRule): every conditional operator, value/date rules, and the date-operator vocabulary."
---

# Filter rule syntax (wizard mode — full reference)

This is the **long-tail lookup** for wizard-mode filter clauses — the exact contract for every operator, including the less-common date and value-list cases. For routing (wizard vs expression) and the `DataFilterRule` field overview, see `filter.md`; this file is the per-operator detail you reach for when a clause isn't a plain comparison.

**Source of truth.** Every rule below is taken from the BE filter compiler, which is a byte-for-byte port of the FE filter-builder:

- `savant-common/expr/.../DataFilterRule.java` — the clause-row model.
- `savant-common/expr/.../DataFilterRuleExpression.java` — per-rule → clause-string generation (`ruleToExpression`).
- `savant-common/expr/.../DataFilterCompiler.java` — multi-rule joining, value-strip, and validity gating (`toExpression`).

The wizard `filter[]` rows are compiled `DataFilterCompiler.toExpression(filter[])` → expression string → `ExpressionCompiler.createFilterConfig` → pipeline, at execution. The skill emits **only** the `filter[]` rows — never `pipeline`/`dataFilterExpr`/`dataFilterLookUp`.

## Clause row fields (`DataFilterRule`)

| Field | Meaning |
|---|---|
| `name` | column display name, unquoted (the compiler backtick-wraps it) |
| `conditionalOperator` | one of the operators below |
| `value` | literal value, as a **string**; required/empty per the operator rules below |
| `dataType` | lowercase `string`/`integer`/`number`/`date`/`datetime`/`boolean` |
| `dateOperator` | date sub-operator (date/datetime columns only) — see the date section |
| `date` | ISO date literal, used only with `dateOperator: "EXACT_DATE"` |
| `logicalOperator` | `AND`/`OR`; **ignored on the first row** |

`id` is **not** in `DataFilterRule` — it is a React-only FE key; the BE ignores it (`@JsonIgnoreProperties(ignoreUnknown=true)`). The builder emits it for FE-render compatibility only.

## Non-date operators

For non-date columns (and for the empty/null/boolean operators on any column), the clause is generated directly. `col` = `` `name` ``.

| `conditionalOperator` | Emitted clause | `value` |
|---|---|---|
| `=` `!=` `>` `>=` `<` `<=` | `col OP value` | required |
| `LIKE_CONTAINS` | `col LIKE "%value%"` | required |
| `LIKE_START` | `col LIKE "value%"` | required |
| `LIKE_END` | `col LIKE "%value"` | required |
| `NOT LIKE_CONTAINS` | `col NOT LIKE "%value%"` | required |
| `NOT LIKE_START` | `col NOT LIKE "value%"` | required |
| `NOT LIKE_END` | `col NOT LIKE "%value"` | required |
| `IS_EMPTY` | `IS_EMPTY(col)` | **must be empty** |
| `NOT IS_EMPTY` | `NOT IS_EMPTY(col)` | **must be empty** |
| `IS NULL` / `IS NOT NULL` | `col IS NULL` / `col IS NOT NULL` | **must be empty** |
| `IS TRUE` / `IS NOT TRUE` / `IS FALSE` / `IS NOT FALSE` | `col IS TRUE` (suffix form) | **must be empty** |

A no-value operator (`IS_EMPTY`, `IS NULL`/`IS NOT NULL`, the boolean `IS …` set) with a non-empty `value` is **silently dropped as invalid** — leave `value: ""`.

### Value formatting

- **Numeric** (`dataType` `number`/`integer`): emitted bare — `123`. Leading-zero fixup applies: `.5` → `0.5`.
- **String** (and other non-numeric): double-quoted — `"text"`. If the value *looks like JSON* (starts with `{` or `[` and parses), it is single-quoted instead — `'{"k":1}'`.
- **LIKE**: the value is wrapped in `%` per the table; a literal `%` in the value is escaped to `\%`.

## Date operators (date / datetime columns)

When `dataType` is `date`/`datetime` and the operator is not an empty/null op, the **date branch** runs. The `conditionalOperator` maps to a SQL comparison, and the `dateOperator` selects the date expression:

| `conditionalOperator` | SQL op |
|---|---|
| `IS`, `IS_IN` | `=` |
| `IS_NOT`, `IS_NOT_IN` | `!=` |
| `IS_BEFORE` | `<` |
| `IS_AFTER` | `>` |
| `IS_ON_OR_BEFORE` | `<=` |
| `IS_ON_OR_AFTER` | `>=` |

A datetime column is wrapped as `TO_DATE(col)` in this branch; a date column is used bare. Below, `colRef` = that column reference and `OP` = the SQL op above.

### EXACT_DATE
`dateOperator: "EXACT_DATE"`, `date` = ISO string (e.g. `"2025-07-31"`), `value` = `""`:

```
colRef OP TO_DATE('2025-07-31')
```

### Named relative offsets (no `value`)
`value` is not used (leave empty). Offset and period come from the operator:

| `dateOperator` | offset | period |
|---|---|---|
| `TODAY`, `THIS_WEEK`, `THIS_MONTH`, `THIS_YEAR` | `0` | DAY/WEEK/MONTH/YEAR |
| `YESTERDAY`, `THE_LAST_WEEK`, `THE_LAST_MONTH`, `THE_LAST_YEAR` | `-1` | DAY/WEEK/MONTH/YEAR |
| `TOMORROW`, `THE_NEXT_WEEK`, `THE_NEXT_MONTH`, `THE_NEXT_YEAR` | `+1` | DAY/WEEK/MONTH/YEAR |

Emitted clause:
- offset `0` → `colRef OP TODAY()`
- offset `±n` → `colRef OP TODAY() + INTERVAL n PERIOD` (or `- INTERVAL n PERIOD`)

### Integer relative offsets (`value` = count, **required**)
`value` is the count as a string (e.g. `"120"`); `_AGO` negates it, `_FROM_NOW` keeps it positive. Period is DAY/MONTH/YEAR per the operator family.

| `dateOperator` | sign | period |
|---|---|---|
| `_DAYS_AGO` / `_DAYS_FROM_NOW` | − / + | DAY |
| `_MONTHS_AGO` / `_MONTHS_FROM_NOW` | − / + | MONTH |
| `_YEARS_AGO` / `_YEARS_FROM_NOW` | − / + | YEAR |

Emitted clause: `colRef OP TODAY() + INTERVAL <count> <PERIOD>` (sign flips for `_AGO`). Example — "posted in the last 120 days", `IS_ON_OR_AFTER` + `_DAYS_AGO` + `value:"120"` → `` `Post Date` >= TODAY() - INTERVAL 120 DAY ``.

> **`value` for `_…_AGO` is the count, not empty.** This is the one date case where `value` is required even though it has a `dateOperator` — confirmed in `DataFilterCompiler.isValid` (integer date ops require a non-empty value) and `DataFilterRuleExpression.signedIntValue` (parses it as the offset).

### IS_IN / IS_NOT_IN (period bucket)
These don't compare to a date; they test that the row's period bucket matches the named/relative offset, via `TIME_PERIOD_OFFSET`:

```
TIME_PERIOD_OFFSET(col, 'PERIOD') OP <offset>
```

where `OP` is `=` (`IS_IN`) or `!=` (`IS_NOT_IN`), `PERIOD` comes from the `dateOperator` family, and `<offset>` is the named offset (`0`/`-1`/`+1`) or the signed integer count. Example — "in this month", `IS_IN` + `THIS_MONTH` → `TIME_PERIOD_OFFSET(\`Date\`, 'MONTH') = 0`.

## Multi-rule joining

A filter is a flat `filter[]` list. `DataFilterCompiler.toExpression` joins them:
- Each row's `logicalOperator` (`AND`/`OR`) connects it to the **previous** row; the first row's connector is ignored (missing → defaults to `AND`).
- When more than one rule produces a clause, **every clause is parenthesized**: `(a = 1) AND (b > 0) OR (c IS NULL)`. A single rule is emitted bare.
- Invalid rows (missing `name`/`conditionalOperator`, or a value-rule violation) are **silently skipped** — same as the FE.

This flat, single-connector model is exactly why **mixed/nested AND-OR needs expression mode** (see `filter.md` → "Choosing the mode").

## Builder coverage

`nb.cond(field, op, value, dtype)` currently builds the comparison, `LIKE_*`, presence (`is_empty`/`not_empty`/`is_null`/`not_null`), and boolean operators. **Date operators (`IS_BEFORE`/`IS_AFTER`/`IS_ON_OR_BEFORE`/`IS_ON_OR_AFTER`, `IS_IN`/`IS_NOT_IN`) and the `dateOperator`/`date` fields are not yet in `cond()`** — until they are, author a date clause by emitting the `DataFilterRule` row directly per the rules above, or use expression mode if it also needs an inline transform. The full `conditionalOperators` list lives in `../registry/components/filter.json`.
