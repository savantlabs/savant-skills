# Expression Language (cross-cutting)

Savant's SQL-like expression language is used inside `edit` (copilot and expression modes), `filter` (expression mode), `summarize` and `rollup` aggregation args, and `gen_ai` prompt templates. It is not a node type — it's the string grammar that many node configs embed.

**Grammar authority: `savant-common/expr`** (a Pratt parser + `ScalarFunctions` — the same compiler the BE runs at execution and the FE runs in the formula editor). When generating an edit/filter, author the **`expression` truth field only**; the runtime and FE compile it to a pipeline server-side (see `edit.md`/`filter.md`). The skill does **not** hand-build `pipeline.steps`/`lookup`/`dataFilterExpr` — a hand-built pipeline can diverge from the expression and fail at runtime. `nb.op_expr(...)`, `nb.op_case(...)`, `nb.filter_expression(...)` emit the expression verbatim.

**Author only from the supported subset.** Function names, arity, and runtime metadata live in `../registry/expression-common.json`, which the validator enforces as an allow-list — **an expression using any function outside it is rejected**. `savant-common/expr` is the underlying compiler, but it supports a much larger surface than we have high confidence in; deliberately stay within the validated subset (`expression-common.json` and the list in `node-builders-api.md`) rather than reaching for the broader language. This Markdown file is explanatory guidance; do not treat its tables as the source of truth when generating JSON.

The workflow validator parses expression strings to enforce the shared grammar surface deterministically: balanced strings/field references/parentheses, known functions (against the registry allow-list), function arity, workflow parameter references, upstream field references when schema is known, and boolean return expectations for filters. It no longer cross-checks against a hand-built lookup tree or pipeline (there is none). Runtime probes under `tests/runtime/` cover app behavior that cannot be proven from grammar alone.

## Functions

The full operator set — every supported function with its **arity and runtime metadata** — lives in the registry json `../registry/expression-common.json`; that is the source of truth, so this file does not restate the catalog. Use the registry to check what exists and the per-function probe facts it records (e.g. `day_of_week` Monday = 1, `str_pos` 1-based and `-1` when not found, `hour` date-only input = 0, `regex_extract` returns the first capture group). Its `unsupportedLookupOperators` list is authoritative — notably **all `GEO_*` geospatial functions, plus `to_decimal` and `first_not_empty`, are NOT supported**. Categories span date/datetime, text, math, conditional, multi-row aggregation/window, and formatting/type conversion (the last two carry compilation rules, below).

## Operators

| Category | Operators |
|----------|-----------|
| Comparison | `=`, `!=`, `>`, `>=`, `<`, `<=` |
| Logical | `AND`, `OR`, `NOT`, `IS NULL`, `IS NOT NULL` |
| Math | `+` (add / date add), `-` (subtract / negate), `*`, `/` |
| Conditional | `CASE WHEN ... THEN ... ELSE ... END` |
| Date | `INTERVAL` (add duration to date) |

## Syntax

- **Field references** use backtick-quoted names: `` `field_name` ``.
- **String literals** use double quotes `"value"` or single quotes `'value'` — both are supported.

## Formatting / type conversion

The six casts are `TO_BOOLEAN`, `TO_DATE`, `TO_DATETIME`, `TO_INTEGER`, `TO_NUMBER`, `TO_TEXT`. Write them in the expression directly — e.g. `` TO_NUMBER(`Amount`) ``, `` TO_DATE(`PostDate`) ``. `TO_DATE`/`TO_DATETIME`/`TO_TEXT` accept an optional second string-literal format argument. The runtime compiles the cast to the right pipeline transform; you do not author the transform.

> **Reading legacy exports (not authoring).** Older exports carry a compiled `pipeline.steps`/`lookup` alongside the expression — e.g. `TO_NUMBER` as a `"to_number"` transform with one `src_col`. You may see these when inspecting an existing flow; they are no longer authored by the skill and are recompiled from the expression on save. (Note: very old exports may carry `"to_decimal"`, which current runtimes reject with "Cannot find transform: to_decimal" — re-author as `TO_NUMBER`.)

**Lookup tree pattern** — wraps the inner expression in an operation node:

```json
{
  "type": "operation",
  "dataType": "number",
  "operator": "to_number",
  "arguments": [
    { "type": "conditional", "cases": [...], "default": {...}, "dataType": "number" }
  ]
}
```

**Critical use case — CASE/IF data type consistency.** Savant requires ALL branches of a `CASE` or `IF` expression to produce the same data type. When one branch returns a computed value and another returns `NULL`, Savant rejects the expression with: *"All cases must generate the same data type."* Fix this by wrapping the entire CASE/IF in a formatting function:

```
TO_NUMBER(CASE WHEN condition THEN numeric_expr ELSE NULL END)
```

In the compiled pipeline this produces two steps:

1. The `"case"` transform outputs to a **transient intermediate column** (e.g. `__t_raw__`).
2. A subsequent `"to_number"` step casts that intermediate to the final output column.
3. The intermediate column is listed in `transient_cols` of the cast step so it is dropped from the output.

## Conditional and multi-row functions

- **`CASE` / `IF` / `IFS`** branch on conditions; **all branches must return the same data type** — wrap the whole expression in a formatting cast (see above). `IN(value, set)` tests membership. The local builder compiler supports searched `CASE WHEN ... THEN ... ELSE ... END` and `IF(condition, true, false)` only when branch result values are literal constants. It does not compile computed branch results such as `IF(x > n, prev + 0.01, x)` or `CASE WHEN ... THEN `Amount` * 0.1 ELSE `Amount` END`; build helper fields and select with flags/arithmetic, or use a separately verified pattern. Use `op_case(...)` for structured literal-result generation when possible.
- **`COALESCE` can use literal defaults only when compiled correctly** — the runtime shape materializes each literal as a transient `constant` step, then passes all choices through `src_cols` with `parts` and `src_col_placeholder`. Use `op_default_constant(...)` or `op_expr("Out", 'COALESCE(`Field`, "default")')`; do not hand-author a `coalesce` step with `parameters.value`.
- **Aggregation / window functions** (`SUM`, `COUNT`, `AVG`, `MIN`, `MAX`, `CUM_SUM`, `ROW_NUM`, `RANK`, `NTILE`, `LEAD`, `LAG`, `FILL_DOWN`, `FIRST`, `LAST`, `JOIN_STR`) compile **only** in builder-mode `edit`, `summarize`, or `rollup` — using one in a plain expression-mode edit passes parse but fails at run time. Summarize/rollup calcs are documented in `summarize.md` / `rollup.md`.

## Where this expression language appears

- **`edit`** — copilot-mode natural-language expressions compile to this grammar, then to the pipeline. Expression-mode authors it directly. See `edit.md` for the `pipeline` / `dataFilterLookUp` compilation targets.
- **`filter`** — expression mode (`mode: "expression"`) stores the string in `dataFilterExpr`. Wizard mode generates the expression from clauses.
- **`pdfilter`** — same `dataFilterExpr` shape as filter, but compiled down into the upstream source query for pushdown.
- **`summarize`** / **`rollup`** — the aggregation `arg.expr` field holds an expression string when `arg.type` is `"expression"` rather than `"field"` or `"constant"`.
- **`gen_ai`** — prompt templates can reference row fields via the backtick syntax, which the runtime substitutes before sending to the LLM.

## Gotchas

- **Backticks are required for any field name that isn't a simple identifier.** Field names with spaces, punctuation, or reserved words MUST be backtick-quoted. `Order Date` without backticks is parsed as two tokens.
- **Builder-generated expressions quote structured field inputs.** Prefer node-builder helpers such as `cond(...)`, `op_arith(...)`, `op_cast(...)`, and `op_case(..., [(cond(...), value)], ...)` for routine transforms; they render field references like `` `Grand Total` `` deterministically. Raw strings passed to `op_expr(...)` or `filter_expression(...)` remain caller-authored formulas and must already quote field references correctly.
- **String quotes are interchangeable in the source text, but Savant normalizes on save.** A workflow authored with single quotes may round-trip back with double quotes. Do not diff expressions on quote style.
- **`IS_EMPTY` compiles differently depending on where it appears.** In pipeline transforms it's an `is_empty` transform; in lookup trees it's an `is_empty` operator. See `edit.md` for the cross-reference and the critical rule that a single expression node must not mix the two representations.
- **`CONCAT` and `COALESCE` use the same parts shape.** Literal string/number pieces must become transient constants first; the final transform uses `parameters.parts` plus `parameters.src_col_placeholder`.
- **Aggregation and windowing functions only compile inside builder mode (`edit`), `summarize`, or `rollup`.** Using `SUM` or `ROW_NUM` in a plain expression-mode edit will not error at parse time but will fail during run.
- **`TO_NUMBER` is the canonical cast when unifying branch types in CASE/IF.** Even if every branch looks numeric, wrap the outer expression in `TO_NUMBER(...)` to avoid the "All cases must generate the same data type" error.
