# node_builders API Reference

## Objective

Use this as the compact constructor reference for generating or updating Savant workflow JSON with `workflow.builders`.

Template note: intentionally a pure API reference; use `## Route` instead of `## Default Action`.

## Use When

- Builder needs to author source, transform, filter, blend, summarize, reshape, AI, destination, group, or output JSON.
- Editor needs the matching update helper for a supported config edit.
- A validator warning points to a builder-produced shape and the constructor call needs to be checked.

## Do Not

- Do not open `builders.py` first for routine generation.
- Do not hand-author JSON for a supported constructor.
- Do not guess unsupported node shapes from registry hints.

Compact calling reference for `from workflow import builders as nb`. Use this before opening `../scripts/workflow/builders.py`; do not open the full `builders.py` source unless this file lacks the needed constructor, a validator error needs source-level investigation, or you are changing the library.

## Reference Boundaries

- This file is the call card for supported `node_builders` constructors and update helpers.
- `../components/_index.md` is the component catalog; `../components/{type}.md` explains behavior, gotchas, and edit semantics.
- `../registry/components/{type}.json` owns schema, enum, and validator-facing config facts.
- If a constructor exists here, use it. If no constructor exists, hand-author only when this file and the component doc both say the shape is documented. If this file says shape is not verified, do not create that node from registry hints.

## Mental Model

Use Reference Boundaries above for which file owns which facts. Operationally:

- A workflow is a DAG of steps.
- Each step transforms data deterministically or with AI.
- Components are the capabilities; the registry is the catalog.
- The workflow is JSON.
- `node_builders` emits nodes deterministically.
- `builders.py` is the compiler: deterministic code emits workflow JSON; do not read it for routine generation or edits.
- `savant.py validate workflow` is the type checker: errors block; warnings are visible and must be fixed or explained for the requested scope. Use `--strict` only when warnings should fail the command.
- Savant is the runtime: import, Analyze/Test/Run, previews, connectors, AI/API calls, and row-count behavior are verified there.

## Route

- Flow shell/layout: **Flow**
- Inputs/outputs: **Source / Destination**
- Column cleanup/formulas: **Transform**
- Keep/drop rows: **Filter**
- Join datasets: **Blend**
- Totals/dedupe/top rows: **Aggregate**
- Pivot/JSON/XML/stack: **Reshape**
- AI/provider/API calls: **AI / Service**
- Existing-node edits: **Editor Updates**
- Missing constructors: **Unsupported**

## Flow

```python
f = nb.Flow(name, tag=None, description="")
node_id = f.add(node)
f.wire(left_id, blend_id, in_idx=0); f.wire(right_id, blend_id, in_idx=1)
f.chain(a, b, c)
f.group(name, members, header=None, description=None, color=None)
nb.text(title, description=None, font_size="1.5rem", bold=True, color="#000000", background="transparent")
workflow = f.compile(validate=True, schema_hints=None, required_tag=None, allow_warnings=True, out=None, planner_handoff=handoff_path)
path = nb.write_workflow(f, planner_handoff=handoff_path, out=None, validate=True, schema_hints=None, hints_out=None, required_tag=None, allow_warnings=True)
path = nb.default_workflow_output_path(name)
path = nb.default_schema_hints_output_path(workflow_path)
```

`tag` is the single Savvy tracking tag; leave it as `None` and `Flow` stamps the canonical versioned tag (e.g. `Savvy v0.0.1`) automatically — `compile`/`write_workflow` then validate against it without an explicit `required_tag`. `group(...)` writes correct group/header membership; do not hand-author group parent fields.
`wire(..., in_idx=...)` controls the target input order. For two-input joins, `in_idx=0` is the blend's left input (`in_0`) and `in_idx=1` is the right input (`in_1`); put the business-driving rows on the left and the lookup/dimension side on the right unless the plan says otherwise.
`compile(...)` validates and, by default when `validate=True`, writes the workflow JSON to `tmp/<ai-session-id>/<workflow-slug>/<Workflow Name>.json`; pass `out=False` for in-memory tests or probes. Any persisted Builder artifact requires `planner_handoff=<planner_to_builder.handoff.json>`; `compile(...)` and `write_workflow(...)` run the Builder precheck gate internally and refuse to write if it fails. When `write_workflow(...)` receives `schema_hints`, it writes `<Workflow Name>.schema-hints.json` next to the workflow unless `hints_out=False`; use that file with `savant.py validate workflow <workflow.json> --schema-hints <schema-hints.json>`.

## Source / Destination

```python
handle_id = nb.source_unit_from_plan(flow, source_plan)
nb.source(name, dataset_id, connector, dtype=None, description="", observed_schema=None, row_count=None)
adapter_id = nb.standardized_source(f, name, dataset_id, connector, schema, dtype=None, source_description="", adapter_name=None, adapter_description=None, observed_schema=None, row_count=None)
nb.destination_from_plan(output_plan, sort=None)
nb.destination_csv(name, file_name, sort=None, description="")
```

Prefer `source_unit_from_plan(...)` when consuming Planner handoff entries from `input_dataset_plan.sources[]`; it consumes the shared source-plan contract (`source.dataset.dataset_id`, optional dataset profile evidence, and workflow intent). `source_kind`: `tabular` -> `Source -> Adapter` using `expected_schema`; `binary_document` -> `Source -> Vision`; `json_text` -> `Source -> JSON`; `xml_text` -> `Source -> XML`. It returns the downstream handle and registers the whole unit so `Flow.group(..., [handle])` groups the source with its adapter/extraction/parser. For tabular inputs, `dataset.observed_schema` and optional `dataset.row_count` are emitted as source profiling evidence automatically. For Excel tabular inputs, numeric observed date fields with plausible serial sample values use `Source -> Adapter -> Normalize Dates`: the adapter keeps the observed numeric type, then the Normalize Transform converts the canonical field to `date`/`datetime`.

Use `standardized_source(...)` directly for known tabular sources; it creates `Source -> Adapter`, wires it, returns the adapter id, and gives the adapter a default business description unless overridden. `schema` entries are `{"name": ..., "dataType": ..., "mappedFrom": ..., "required": ...}`. Downstream nodes use canonical `name`.

Prefer `destination_from_plan(...)` when consuming Planner handoff entries from `output_destination_plan.outputs[]`; it passes the full output object through so the destination name, planned type, file name, and description follow the shared output-destination contract. Builder currently supports planned CSV outputs only, including confirmed CSV fallbacks for unsupported requested destination types.

`destination_csv(...)` creates a native Savant CSV output (`connector: "csv"`, `type: "csv"`, `mode: "update"`). It does not create a cloud-file destination and must not include `fileSystemConfig`; use a real file-system connector in Savant when the output needs a folder-backed CSV file.

Callers should pass business-specific `description` text for every meaningful node. Constructor defaults are fallback text only; they are not a substitute for explaining the step's input, transformation, review purpose, or output audience.
Descriptions must follow `node-documentation-rules.md`: a node-specific readout of the configuration in plain business language. When a constructor call adds calculations, conditions, joins, groups, AI prompts, output settings, hidden fields, or ordered fields, the description should name those settings and explain their data impact. Formulas should appear only for calculated fields or formula-based rules.

## Transform

```python
nb.edit_node(name, ops=None, modify=None, drop=None, order=None, description="")
nb.op_json_field(tgt, src, path, dt="string")
nb.op_json_number(tgt, src, path)
nb.op_arith(tgt, left, op, right, right_is_const=False, dt="number")  # add/sub/mul/div
nb.op_avg(tgt, fields)
nb.op_cast(tgt, src, to="to_number")
nb.op_date_diff(tgt, end_date, start_date, unit="day")
nb.op_expr(tgt, expression, dtype="string", action="add_col", replace_tgt=None)
nb.op_const(tgt, value, dtype="string")
nb.op_case(tgt, cases, default, dtype="string")
nb.op_count_if(tgt, condition, dtype="integer")
nb.op_default_constant(tgt, src, default, dt="string")
nb.op_window(tgt, calc, sorts=None, partitions=None, arg_field=None, params=None)
nb.op_rename(old, new, dt="string")
nb.op_retype(col, to="to_number")
nb.op_transform(new, src, expression, dt="string")
nb.keep_only_columns(flow, upstream, name, columns, description="")
```

Cast tokens: `to_number, to_integer, to_text, to_date, to_datetime, to_boolean`.
Use `op_date_diff("Ship Days", "Ship Date", "Order Date", unit="day")` for simple ship-days style columns; it emits the same shape as `op_expr("Ship Days", 'DATE_DIFF(`Ship Date`,`Order Date`,"day")', "integer")`. The first date is the later/end date, the second is the earlier/start date, and the output is an integer.
`op_expr` emits the `expression` as the **truth field** — it does NOT hand-build a pipeline. The runtime compiles the expression to a pipeline server-side (and the FE re-derives the display caches), so nested expressions such as ``TO_INTEGER(REGEX_EXTRACT(`Field`, "([0-9]+)"))`` are authored as plain expression text. `op_case` accepts either raw condition strings or structured `cond(...)` objects, e.g. `op_case("Flag", [(cond("Grand Total", "eq", "Open", "string"), "keep")], "drop")`; prefer structured conditions for simple comparisons so field quoting is generated deterministically. `op_count_if(...)` is the standard null-safe count helper: create a 0/1 field from a condition, then summarize it with `("SUM", "<Flag>", "<Count>")`.
`savant-common/expr` is the underlying compiler, but author only from the **supported subset below** — the validator rejects any function outside the registry allow-list, and the subset is deliberately limited to high-confidence functions. Don't reach for the broader Savant language even though the runtime would compile it. See `../components/expression-language.md`. For routine null defaults, prefer `op_default_constant(...)`; for routine flags, prefer `op_case(...)` / `op_count_if(...)`.
`op_rename(...)`, `op_retype(...)`, and `op_transform(...)` all emit Savant's `replace` shape, which renames/retypes/transforms a column **in place** — it consumes the source column (one in, one out) and keeps its position. Never express a rename as an `add_col` of `new = old` plus `drop=[old]`: that leaves the original to leak downstream. `op_transform` is the general form — fold a rename + cast + normalization into one op, e.g. ``op_transform("Vendor Key", "AI Answer", "UPPER(TRIM(`AI Answer`))")``. Reference the source and `drop`/`order` columns by **display name**; the runtime resolves by name and a derived id can mismatch the real internal id and silently no-op.
Transform edits are ordered. A later op may reference a column created or replaced by an earlier op in the same `edit_node`; keep the `ops` list in dependency order and do not forward-reference fields that are created later.
When an upstream AI prompt constrains a field to exact labels (for example exactly `Negative` / `Positive`), prefer exact CASE conditions such as `` `Sentiment` = "Negative" `` instead of adding `UPPER(...)` normalization.

Supported expression functions for `op_expr(...)` and `filter_expression(...)` — **author only from this list**; the validator rejects anything outside it:

```text
casts: TO_NUMBER, TO_INTEGER, TO_TEXT, TO_DATE, TO_DATETIME, TO_BOOLEAN
numeric unary scalars: ABS, CEILING, FLOOR, ROUNDDOWN, ROUNDUP
date parts: DAY, MONTH, YEAR, HOUR, MINUTE, SECOND, QUARTER, WEEK,
            DAY_OF_WEEK, DAY_OF_YEAR, DAYS_IN_MONTH, DAYS_IN_YEAR,
            WEEK_OF_YEAR, DAY_NAME, MONTH_NAME
date diff: DATE_DIFF(end_date, start_date, "day|week|month|quarter|year")
text: TRIM, LENGTH, UPPER, LOWER, PROPER
predicates/regex: IS_EMPTY, CONTAINS, REGEX_MATCH, REGEX_EXTRACT, REGEX_REPLACE
special expression forms: CONCAT, COALESCE, IF with literal true/false results, searched CASE WHEN with literal THEN/ELSE results
```

Stay within the list above. The skill emits the expression as the truth field and the runtime compiles it, but the validator rejects functions outside the supported subset — by design, to keep generation on a high-confidence surface. If a needed function is genuinely missing from the subset, raise it for the registry to be widened rather than working around the validator.

`drop` hides via `hiddenFields`; `order` only reorders and never drops. `order`/`orderedFields` is a **pin-to-front** list — list only the columns you want at the front (in order); the launcher appends every other column after them in natural schema order, so a partial list is correct and you never enumerate the whole output.
Use `keep_only_columns(...)` for final output shaping once calculations and renames are complete:
it reads the upstream schema, sets `orderedFields` to the requested columns, and hides every other
upstream passthrough field so extra columns cannot leak into destinations. If you still need to add
or rename fields, do that in an earlier Transform, then call `keep_only_columns(...)`.

Transform descriptions should read out the specific column-level operations. For each calculated column, include an Excel-style formula or a faithful plain-English equivalent; for renames, type changes, hidden fields, and ordering, describe the operation without inventing a formula.

## Schema Debugging

Use `flow.schema_at(node_id_or_name)` to inspect one node's validator-modeled output columns before writing the workflow. Use `flow.summary()` when a compiled flow would be too large to print; it lists node names, types, and resolved column lists. From the CLI, use:

```bash
savant.py validate workflow workflow.json --show-schema <nodeId-or-name>
```

Blend duplicate naming in the modeled main output matches live Savant: non-key right-side duplicates become display names such as `Field (rhs)`, while id-only controls may need exact ids/display names. Use the schema helpers above before filling `drop=` or `order=`.

## Filter

```python
c = nb.cond(field, op, value=None, dtype="number")
nb.filter_node(name, [c], joiner="and", false_path=False, mode="wizard", description="")
nb.pdfilter_node(name, [c], joiner="and", false_path=False, mode="wizard", description="")
nb.filter_expression(name, expression, false_path=False, description="")
true_id = nb.filter_outlet(f, filter_id, "true")
false_id = nb.filter_outlet(f, filter_id, "false")
```

**Prefer `filter_node` (wizard).** Each clause is a `DataFilterRule` row (`name`/`conditionalOperator`/`value`/`dataType`/`logicalOperator`) the BE compiles deterministically. Use `filter_expression` only when the filter needs an inline transformation on a column (`UPPER(...)`, `TO_NUMBER(...)`, arithmetic) or nested/mixed AND/OR — see `../components/filter.md` → "Choosing the mode".

Tokens:

```text
joiner: and, or
mode: wizard, expression
comparison: gte, lte, gt, lt, eq, neq
text: contains, starts_with, ends_with, not_contains, not_starts_with, not_ends_with
presence: is_empty, not_empty, is_null, not_null
boolean: is_true, is_false
```

Use `false_path=True` before `filter_outlet(...)`; wire returned branch ids, not hand-authored outlets.

## Blend

```python
nb.blend(name, on, join="inner", joiner="and", left_unmatched=False, right_unmatched=False, description="")
matched = nb.blend_outlet(f, blend_id, "matched")
left_only = nb.blend_outlet(f, blend_id, "left_unmatched")
right_only = nb.blend_outlet(f, blend_id, "right_unmatched")
```

`on` tuples: `("Left Field", "Right Field")`, `("Left Field", "Right Field", "eq")`, or `("Left Field", "Right Field", "eq", "string")`.

Tokens: `join: inner, left, right, full`; `joiner: and, or`; blend ops: `eq, ne, gt, ge, lt, le, contains, is_part_of`.

Outer join type and unmatched-output branches are independent. If split branches are enabled, wire `blend_outlet(...)` ids.

## Aggregate

```python
nb.summarize(name, group_by, aggs, description="")
nb.rollup(name, date_col, group_by, aggs, periodicity="day", description="")
nb.deduplicate(name, fields=None, sorts=None, mode="distinct", description="")
nb.sample_top(name, n, sorts=None, group_by=None, description="")
nb.hierarchy(name, id_field, parent_id_field, aggs, description="")
```

Agg tuples: `(calc, field, output_name)` or `(calc, field, output_name, delimiter)` — the 4th element sets the separator for the string-joining calcs and raises on any other calc. Examples: `("SUM", "Amount", "Total Amount")`, `("COUNT", "Row", "Rows")`, `("JOIN_STR", "Employee Name", "Hierarchy", ">")`, `("JOIN_STR_DISTINCT", "Category", "Categories", " | ")`. Same form for `summarize`, `rollup`, and `hierarchy`.

Calc tokens: `SUM, COUNT, AVG, MIN, MAX, NUNIQUE, MEDIAN, STDDEV, VAR, MODE, JOIN_STR, JOIN_STR_DISTINCT`; `summarize` also has `FIRST, LAST`. Per-node truth is `../registry/components/{type}.json` (`calcs`, plus `unsupportedCalcs` — e.g. summarize rejects `COUNT DISTINCT`/`CONCAT`, use `NUNIQUE`/`JOIN_STR`).

`JOIN_STR`/`JOIN_STR_DISTINCT` outputs are typed `string`; `COUNT`/`NUNIQUE` are `integer`; the rest are `number`. The builders stamp this from the calc token, matching each registry's `outputType` — never hand-write a numeric dataType on a string join.

## Reshape

```python
nb.adapter(name, specs, passthrough=False, description="")
nb.adapter_specs(schema)
nb.format_node(name, header_row=None, steps=None, description="")
nb.json_node(name, mode, input_field, keep_input=False, description="")  # flatten/explode
nb.xml_node(name, mode, input_field, path=None, unwrap_tag=True, process_ns=False, description="")  # SELECT/EXTRACT/TO_JSON
nb.pivot(name, pivot_field, value_field, calc="AVG", description="")
nb.unpivot(name, name_field, value_field, selected_fields, mode="unpivot", description="")
nb.split_node(name, input_field, separator, mode="rows", trim=True, keep_input=True, description="")
nb.explode_node(name, max_small_side_rows=None, description="")
nb.multi_stack(name, inputs=2, match_rule="by_name", master_index=1, fields="match", description="")
```

XML `SELECT` requires `path`. `unpivot(..., mode="unpivot")` converts `selected_fields` into rows;
`mode="keep"` keeps `selected_fields` as identity columns and unpivots everything else.
`multi_stack(..., inputs=N)` is wired with `wire(..., in_idx=...)`;
the emitted JSON stores all Stack inputs in one canvas-safe `multisource` inlet.
When the upstream schema is known, `unpivot(...)` has a modeled output schema: retained identity
columns plus `name_field` and `value_field`. `keep_only_columns(...)` can be used immediately after
Unpivot for final output shaping. If the upstream schema is unknown, standardize with an Adapter or
provide schema hints before relying on downstream column checks.

## AI / Service

```python
nb.gen_ai(name, prompt, input_fields, provider_id=None, row_limit=1000, description="")
handle = nb.gen_ai_json_flatten(flow, name, prompt, input_fields, provider_id=None, row_limit=1000,
                                flatten_name=None, keep_generated=False, description="", flatten_description="")
nb.gen_ai_node_for_json_flatten(flow, flatten_handle)
nb.gen_ai_output_field()
nb.vision(name, prompt, input_field, provider_id=None, description="")
nb.fuzzy_match(name, lhs_key, rhs_key, provider_id=None, show_demo_provider=True, description="")
nb.api_service(name, url, method="GET", result_format="JSON", description="")
nb.schema_hints((node_or_id, ["Output Column"]))
```

AI/provider-backed nodes default missing `provider_id` to Savant Trial (`savant-ai-provider-gzilpzflks`). When API access is available, use the live provider list first and ask only if more than one provider is available. Use `schema_hints(...)` for generated columns referenced downstream.
For JSON extraction with GenAI, prefer `gen_ai_json_flatten(...)`. It wires `gen_ai -> json(flatten)` and owns the GenAI output field name through `gen_ai_output_field()`, so callers do not guess the JSON node `inputField`. The returned handle is the JSON flatten node id for downstream wiring and grouping. Attach schema hints to the GenAI node, not the JSON node: `ai = nb.gen_ai_node_for_json_flatten(f, flat); hints = nb.schema_hints((ai, ["sentiment", "evidence"]))`.

## Editor Updates

```python
nb.update_config(existing, config, name=None, description=None)
nb.edit_update(existing, ops=None, modify=None, drop=None, order=None, name=None, description=None)
nb.filter_update(existing, conditions, joiner="and", false_path=False, mode="wizard", name=None, description=None)
nb.blend_update(existing, on, join="inner", joiner="and", left_unmatched=False, right_unmatched=False, name=None, description=None)
nb.gen_ai_update(existing, prompt, input_fields, provider_id=None, row_limit=1000, name=None, description=None)
nb.summarize_update(existing, group_by, aggs, name=None, description=None)
nb.pivot_update(existing, pivot_field, value_field, calc="AVG", name=None, description=None)
nb.rollup_update(existing, date_col, group_by, aggs, periodicity="day", name=None, description=None)
nb.unpivot_update(existing, name_field, value_field, selected_fields, mode="unpivot", name=None, description=None)
nb.json_update(existing, mode, input_field, keep_input=False, name=None, description=None)
nb.deduplicate_update(existing, fields=None, sorts=None, mode="distinct", name=None, description=None)
nb.vision_update(existing, prompt, input_field, provider_id=None, name=None, description=None)
```

Updates preserve id, type, wiring, position, `canvasConfig`, and unmodeled config keys. They do not add/remove branch topology.

## Unsupported

No dedicated constructor, shape documented:

- `notes`: canvas note only; hand-author from component doc + registry when needed.
- `outlet`: do not author directly; use `filter_outlet(...)` or `blend_outlet(...)` from the parent node.
- `service`: existing legacy/LLM service nodes may be edited with `update_config(...)` while preserving the `service` envelope. For new HTTP API calls, generate `apiService`; for new LLM steps, prefer `gen_ai` unless a live/export-backed requirement proves `service` is needed.

Shape NOT verified for generation: `pdsummarize`, `search_replace`. Component docs and registry can support inspection or conservative edits of existing nodes, but do not create new nodes from hints; get a real export and add a constructor first.
