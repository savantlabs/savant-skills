---
registry_summary: "Vertically stacks rows from two or more upstream inputs into a single output."
---

# multi_stack (Stack)

## Business purpose

Vertically stacks (UNION ALL) the rows from two or more upstream inputs into a single output. The product UI calls this "Stack"; the canonical type string in the workflow JSON is `multi_stack`. It's the SQL `UNION ALL` equivalent — append rows from each input end-to-end, with configurable rules about how to align columns when the inputs have different schemas.

Structurally, this is the only currently-documented node type whose inlet has `type: "multisource"` — a single inlet that holds an array of `sources`, one per upstream input. Inspectors and editors that read connectivity by walking `inlet.source` (singular) miss the upstream nodes; they need to walk `inlet.sources[]` instead. See "Multisource inlet" under Interpretation.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/multi_stack.json`. This file focuses on behavior, writing, and gotchas.

## Building (use node_builders)

`../scripts/workflow/builders.py` owns the stack shape via `nb.multi_stack(name, inputs=2, match_rule="by_name"|"by_pos", master_index=1, fields="match")`:

```python
s = f.add(nb.multi_stack("Combine", inputs=2, match_rule="by_name"))
f.wire(a, s, in_idx=0); f.wire(b, s, in_idx=1)
```

`wire(..., in_idx=...)` preserves the caller's input order, but the JSON stores every input under one
canvas-safe `type: "multisource"` inlet named `in_0`. `master_index` picks which input's column names
win (matters under `by_pos`); `fields` is `match` (intersection) or `all` (union).

## Invariants

- At least two inputs should be wired — a one-source stack is a degenerate passthrough (likely an authoring mistake).
- Output row count = sum of input row counts: the most reliable verification signal, invariant to `fields`/`match_rule`.
- Stack JSON must use a single `type: "multisource"` inlet holding `sources[]` (see "Reading the inlets").
  Split inlets such as `in_0`/`in_1` can pass generic edge checks but do not reliably render every
  connector on the canvas.

## Interpretation

**Row count.** Input row counts N₁, N₂, … Nₖ produce output row count ΣNᵢ. "Did the row count add up correctly" is the most useful check — anything else suggests a misconfigured node or upstream nulls being dropped.

**Column behavior** is where the two enums earn their keep:

- If two inputs have the same column conceptually but with different names (e.g. `customer_id` vs `cust_id`), `by_name` treats them as separate columns — output gets both, half-populated. `by_pos` aligns them as one column (using the master input's name).
- If one input has an extra column the others don't, `match` drops it; `all` keeps it with nulls in the other inputs' rows.

When a multi_stack appears to have "lost" columns, check the `match` vs `all` setting before chasing upstream issues.

**Multisource inlet.** Where every other node has `inlet.source` (a single string), multi_stack has `inlet.sources` (an array of `{source, sourceOutlet}` objects):

```
// Single-source inlet (filter, edit, blend, etc.)
node.inlets[0].source        // "edit_xxxx"
node.inlets[0].sourceOutlet  // "out_0"

// Multi-source inlet (multi_stack only)
node.inlets[0].type          // "multisource"
node.inlets[0].sources       // [{ source, sourceOutlet }, …]
```

Anything that reads upstream connectivity via `inlet.source` gets `undefined` for multi_stack and silently misses every upstream input; code that walks exported config must branch on `inlet.type === "multisource"` and read `inlet.sources[]`.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, multi_stack("x", inputs, match_rule, master_index, fields)["config"])`. Adding or removing inputs is an inlet/topology change, not a config edit. Prefer `by_name`; `by_pos` is order-fragile.

## Gotchas

- **`inlet.source` is undefined on multi_stack.** Code that walks the JSON to find upstream nodes via `inlet.source` silently fails on this node type. Always check `inlet.type === "multisource"` and walk `inlet.sources[]` when you see it.
- **`by_pos` is fragile.** Aligning by position is sensitive to column reordering anywhere upstream — an `edit` node that reorders columns silently changes which columns get stacked together. Prefer `by_name` unless inputs genuinely have identical schemas in identical order.
- **`match` silently drops columns.** Inputs that look "mostly aligned" but have one or two extra fields per side will lose those fields under `match`. The only signal is missing columns in the output preview; there's no warning.
- **Empty inputs still contribute (zero rows).** A `multi_stack` with one populated input and one empty input outputs the populated input unchanged. Inspectors should not treat "output looks like input" as a sign that the stack is misconfigured — it may just mean the other input is empty for this run.
- **`masterIndex` matters even when columns look aligned.** When `matchRule: "by_pos"`, the master input's column names win for the output; the others' names are discarded. Two stacks with otherwise-identical config but different `masterIndex` produce outputs with different column names.
- **The product name is "Stack."** When talking to a user, refer to it as the Stack step when a product term is needed, not `multi_stack` — `multi_stack` is the internal type string and showing it in conversation is the same UX mistake `business-user-response-rules.md` warns about with display names vs ids.
