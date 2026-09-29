# Priority rules — what goes on page 1

Every call-out the skill generates is assigned exactly one tier. The front page shows P1 and P2 only; P3 is one summary line plus an appendix. The reason is scale: a user migrating ten flows reads ten page-ones, and a page one that lists thirty findings is a page one nobody reads.

| Tier | Test | Where it appears | Needs |
|---|---|---|---|
| **P1 — Blocks production** | The flow cannot run in Savant, or cannot be trusted, until this is resolved | Page 1 table, sorted first | Owner + status |
| **P2 — Changes a number** | Following Alteryx exactly and following the sensible default give *different output values*; someone must choose | Page 1 decision table with a recommended default | Decision |
| **P3 — Cleanup** | Dead code, redundancy, optimisation; output identical either way | One line on page 1 ("N cleanup items, none change the output"); Appendix C | Nothing before cut-over |

## P1 — always
- Input connection or dataset missing in the target workspace (`DbFileInput` with no matching connection/dataset)
- Destination with no Savant equivalent (Tableau publish, Run Command, email-without-attachment patterns, custom API without auth configured)
- Python / R / Run Command tools
- Iterative or batch macros (loops)
- Baseline not captured (no Alteryx exports to reconcile against)
- Any tool whose `mapping` is `unsupported` or `review` in `tool-mapping.json`

## P2 — the "decision table"
Each row: *Alteryx behaviour → Savant default → effect if accepted → decision → applied in Savant flow*. Always propose a default. Mark rows where the default **changes** Alteryx behaviour with ⚠ so a rushed "accept all" still sees them.

When the default is applied depends on the kind:
- **Preserves Alteryx behaviour** (blank keys equal, case-sensitive keys, single-input substitution that is provably equivalent): built into the faithful flow immediately — *Applied = yes*.
- **Changes Alteryx behaviour** (⚠): build faithful first, reconcile, sign off, then apply as checklist step 17 in edit mode on the same flow, one P2 per versioned change with the comparison repeated after each — *Applied = step 17*. Changing logic and engine in one step makes every delta ambiguous (defect or intended?). Exception: a small flow where the owner chose the change at intake and the pass condition can be restated up front (e.g. "Alteryx-only rows = 0").
- **Declined ⚠ default** (owner chose "match Alteryx exactly"): keep the ⚠ on the row, build faithful — *Applied = yes (faithful)*; step 17 becomes optional and lists the declined rows.

Typical P2 sources:
- Two branches applying different rules to the same measure (e.g. a status rule in one output but not the other)
- Integer typing that truncates decimals (`Int16/32/64` on a computed decimal)
- Dedupe present on one branch and absent on another
- `First`/`Last` aggregations that depend on sort order
- A rule replicated from a *different* market/entity (copied-workflow residue) that *does* fire on this data
- Single-input substitution for two overlapping queries where the equivalence depends on an assumption
- Null handling on `!=`, blank vs 0, trim/case on join keys when the data has variation
- Tolerance and formatting choices for the reconciliation (decimals, dates, text case)

## P3 — everything else
Duplicated filter/formula chains, no-op Selects, unused join anchors, dead literals, overlapping inputs, Sort tools, seven Selects that only drop `Right_*` fields, "derive output B from output A" refactors.

## Coverage headline
`{mapped} mapped · {approximated} approximated · {unsupported} unsupported — {tool names with IDs}` and, when present, `· {n} custom macro(s) to inline`.
Name the unsupported and approximated tools in the headline whenever there are three or fewer; otherwise say "see P1". A count with no name is not actionable.
