---
registry_summary: "Joins two data streams on matching key fields. Supports inner, left-only, right-only, and full output branches. Output can be single stream for matched rows, or split into multiple streams to also include unmatched rows."
---

# blend (Join)

## Business purpose

Joins two data streams on matching key fields. This is Savant's `JOIN` primitive — inner, left outer, right outer, or full outer — with optional split-output outlets for unmatched rows on either side. The two inputs ("left" = `in_0`, "right" = `in_1`) can come from anywhere upstream; the blend produces matched rows from `|0` and, if enabled, unmatched rows from `|1` and/or `|2`.

Typical uses: joining invoices to payments, enriching transactions with reference data, or reconciling two sources against a shared key.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/blend.json`. This file focuses on behavior and gotchas.

## Building a blend (use node_builders)

Do not hand-author blend JSON. `../scripts/workflow/builders.py` owns the correct shape:

```python
b = f.add(nb.blend("Join", on=[("Sales Zip", "ZIP Code"),                 # eq (default)
                               ("Region", "Region", "eq"),
                               ("Amount", "Limit", "le")],                  # operator per condition
                   join="left",          # join TYPE only: inner / left / right / full
                   joiner="and",          # and / or across conditions (no mixed)
                   left_unmatched=True))   # optional split-output forks (independent flags)
f.wire(left, b, in_idx=0); f.wire(right, b, in_idx=1)
f.wire(nb.blend_outlet(f, b, "matched"), next_node)        # |0 matched rows
f.wire(nb.blend_outlet(f, b, "left_unmatched"), exceptions) # |1 unmatched-left fork
```

The builder encodes these (the judgment, not the JSON shape):

- **Join type (`join=`) is independent of the unmatched-output forks.** An outer join already keeps unmatched rows in `|0` with nulls — do NOT set the unmatch flags just because the join is outer (a real past bug: phantom "Include Unmatched" checkbox + orphan outlet).
- **Matched-vs-unmatched split = inner join + unmatched fork.** Because a left/right/full join's main output already includes unmatched rows, `join="left"` + `left_unmatched=True` sends unmatched (null-right) rows down the `|0` "matched" fork too — verified live, and downstream summaries silently include null-key rows. Use `join="inner"` with the unmatched fork(s) for a clean split; the builder and validator warn on the non-inner combination.
- **Match operators differ from filter's**: `eq/ne/gt/ge/lt/le/contains/is_part_of` (two-letter forms, not `gte`/`lte`).
- **Join keys must have matching dataTypes on both sides**, or the join silently yields **zero rows**.
- **Unmatched outputs are an opt-in fork** per side; wire each with `blend_outlet(flow, blend_id, which)` (`|0` matched; `|1` the enabled side or left-when-both; `|2` right-when-both). A no-split blend wires matched rows directly.

**Exact vs fuzzy:** blend is EXACT-match only. For approximate/AI matching (`"Acme, Inc."` ↔ `"ACME Incorporated"`) use `nb.fuzzy_match(name, lhs_key, rhs_key, provider_id)` — a separate node with a single output plus a `Confidence Score` column (no matched/unmatched split; unmatched rows are dropped). Keys must be text. See `fuzzy_match.md`.

## Interpretation

### Row count deltas — the three things to check

For an inner join on N_left and N_right rows with no duplicates:
- Matched `|0`: M rows, where M ≤ min(N_left, N_right).
- Left unmatched `|1` (if on): N_left − M rows.
- Right unmatched (if on): N_right − M rows.

For left outer (`regions: ["T1_N_T2", "T1"]`): `|0` count = N_left (all left rows, matched ones enriched with right columns).

For full outer: `|0` count = M (matched) + (N_left − M) left-only + (N_right − M) right-only.

A join that produces far more rows than either input usually indicates a one-to-many relationship (duplicates on one side). A join that produces far fewer rows than expected usually indicates a type mismatch or a stale key.

### Lookup enrichment convention

For initial workflow generation, lookup-style blends should usually put the business/report-driving rows on the left input (`in_0`) and the reference/lookup table on the right input (`in_1`). Examples: transactions plus customer master, obligations plus FX rates, invoices plus payment terms, or records plus mapping tables.

When the business rows must be retained, configure the outer-join region for whichever side currently holds those business rows:

- Business rows on `in_0`: `regions: ["T1_N_T2", "T1"]`.
- Business rows on `in_1`: `regions: ["T1_N_T2", "T2"]`.

The generation convention is not a visual-design law. It can be valid to swap Blend inputs for clarity. Treat that as a schema-bound rebuild unless an exact API recipe mutation is documented: preserve join fields and downstream references, swap inlets, update `regions` so the report-driving rows are still retained, and verify both blend output and downstream destination behavior through the API.

## API edit support

**Join conditions (`on`) and join type (`regions`) are supported** through the deterministic regenerate-and-merge path: `blend_update(existing_node, ...)` regenerates the match config and merges it onto the live node, preserving id, wiring, and unmodeled fields. These are config-only (they don't change the node's outlets), so they go through the normal snapshot → diff → confirm → save → re-fetch loop. A join change can change row counts and the output column set, so verify output after save and reconcile downstream references if the schema changed.

**Topology-changing blend edits are NOT this path.** Toggling the unmatched-output flags (`useLeftUnmatch` / `useRightUnmatch`) adds or removes the `|1`/`|2` outlet branches, and swapping which inputs feed the blend rewires inlets — both are topology, handled by the editor's add/remove-node rules (and inlet swaps that would orphan downstream still route to the downloader → builder → creator rebuild path).

Renaming the blend node or an outlet label uses the generic recipe diff (verify by re-fetch). When renaming an outlet, confirm which path the user means from the current label text rather than the positional index, and note the default unmatched labels include an emoji (`❌️ Left Unmatched`) — a rename replaces the whole label, so keep the emoji if wanted.

## Gotchas

- **Type mismatches are silent.** Joining integer to string produces zero matches, not an error. Check `dataType` on both sides of every `on[]` entry.
- **Duplicate keys explode row counts.** If the left side has N rows with the same key and the right side has M, the match count is N × M. This is SQL-standard behavior but surprises users who expect 1:1 joins.
- **Right-side duplicate columns get Savant's `(rhs)` names — on the main joined output (`|0`) only.** Verified live behavior: left columns appear first. Conflicting right-side non-key columns become display names like `Amount (rhs)` with schema ids like `Amount_2`. Expressions and value transforms should use the display name. `hiddenFields`/`orderedFields` likewise take the exact display name (`Amount (rhs)`); a normalized guess like `shared_amount_2` matches neither the name nor the live id, so it won't hide the field. For an inner join, a same-named right join key is suppressed. For left/right/full main outputs, the same-named right join key is retained as `Account (rhs)` / `Account_2` because unmatched rows may need it. **The unmatched forks never carry a suffix:** `|1` (left unmatched) holds only left columns and `|2` (right unmatched) holds only right columns, each under its original field name — there is no `(lhs)`, and a field that is `Amount (rhs)` in `|0` is plain `Amount` in `|2`. A suffix can only arise where both sides' columns coexist, which is only the joined output.
- **Unmatch outlet indexing shifts when you toggle flags.** `|1` means "left unmatched" if only left is on, but "left unmatched" AND `|2` is "right unmatched" when both are on. Don't hardcode `|1` = left; it depends on flags.
- **Full outer uses explicit regions:** `["T1_N_T2", "T1", "T2"]`. Downstream edits that assume both sides' columns are present must handle nulls.
- **The Venn UI is region-by-region; `regions` is the array of selected regions.** Selecting "matched" + "left-only" in the Venn produces `regions: ["T1_N_T2", "T1"]`, which is left outer. Earlier docs treated `regions` as a single-token enum (e.g. `"T1"` alone = left outer) — that's wrong; left outer is the two-element array. Do not use the older `"T1_U_T2"` shortcut for full outer; it has produced live Blend runtime failures after import.
