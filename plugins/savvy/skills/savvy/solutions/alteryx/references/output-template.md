# Migration guide — output template

Produce **one guide per flow** (`<flow>.migration-guide.md`). It is the skill's only output. A filled example is `example-guide.md`. Keep the section order exactly; users learn where to look.

```markdown
# Migration Guide — `{flow file}`

## What this workflow does
{2–3 sentences, business language: who runs it and when, what goes in, what rules it applies, what comes out and who uses it.
Then one sentence on how the Savant flow does the same thing, naming any deliberate change (P2 decisions).}

## Page 1 — Status
| Flow | {file} ({Alteryx version}) — {one-line business purpose} |
| Alteryx owner | {name/team} |
| Savant flow | [{name}]({url}) · {workspace › folder}   (or "not yet built") |
| Coverage | {N} tools → {M} steps · **{mapped} mapped · {approx} approximated · {unsup} unsupported — {tool names (IDs)}** |
| Progress | **{done} of 17 checklist steps complete** — blocked on step {n} ({reason}) |
| Guide generated | {date} · skill v{version} |

### Blocking items (P1)
| # | Item | Why it blocks | Owner | Status |

### Decisions that change a number (P2)
| # | Alteryx behaviour | Savant default | Effect if accepted | Decision | Applied in Savant flow |
(⚠ on rows whose default changes Alteryx behaviour. *Applied*: `yes` when the faithful build already implements it — always the case for defaults that preserve Alteryx behaviour; `step 17` when a ⚠ default was accepted and is applied after sign-off; `yes (faithful)` when the owner declined the ⚠ default at intake, with step 17 left optional; `open` only when the value can only be read from the baseline export, naming the checklist step that settles it.)

*{k} cleanup items (P3) found — none change the output. See Appendix C.*

## Page 2 — Production checklist
(17 rows from references/checklist.md, with Status and Evidence columns; then the Runbook block)

## Appendix A — Validation checkpoints
| # | Alteryx tool | Savant step (S-number) | Compare | Expected relationship | Result |
+ a short block "Deliberate non-matches" and one paragraph on how to capture the Alteryx baseline (which Output/Browse tools to export) and compare

## Appendix B — Logic traceability (Alteryx → Savant)
| Alteryx tool(s) | Business rule (R-number) | Savant step (S-number · name) | Mapping | Note |
Mapping ∈ exact / equivalent / approximated / unsupported / unsupported destination / inlined macro / added / n/a (Browse, comments, containers). Note = the behaviour difference handled at that step (blank keys, integer truncation, encoding, First/Last ordering…) or "—".

## Appendix C — Cleanup items (P3)
| # | Finding | Alteryx tools | Suggested change |
```

Savant steps are numbered **S1…Sn in execution order**, and the Savant flow's step names carry the same number as a prefix (`S4 · Keep one record per building per quarter`). The number is the join key between the guide, the flow and the conversation with the owner.

External dependencies (connections, destinations, macros, credentials) appear as P1 rows or in Appendix B's Note column — there is no separate inventory. Behaviour differences appear in Appendix B's Note column and, when they change a number, as P2 rows.

Rules
- The guide opens with the business description — a reader who knows nothing about the flow should understand it before seeing a single status row.
- Page 1 never lists P3 items individually.
- Every P2 row has a default; rows whose default changes Alteryx behaviour carry ⚠.
- ⚠ rows are built faithful first and applied as checklist step 17 after sign-off, one per versioned change, each followed by a reconciliation re-run — unless the owner chose the change at intake and the reconciliation pass condition is restated for it (small flows only). When the owner chose "match Alteryx exactly", every ⚠ default is declined: the row keeps its ⚠ (so a later reader still sees the sensible alternative), *Applied* = `yes (faithful)`, and step 17 is optional. The *Applied in Savant flow* column records which.
- Business rules R1…Rn are defined once at the top of Appendix B and cited by those numbers everywhere else in the guide.
- Unsupported tools are named in the coverage line when ≤ 3, else "see P1".
- Appendix B rows for inlined macros name the macro and the call site.
- Deliberate non-matches (decimal precision, column order, trimming both branches) are listed in a short block under Appendix A, never hidden in prose.
- Appendix B has one row per Alteryx tool or tool group, every Savant step appears at least once, and steps the skill *added* (blank-safe keys, technical constants) are shown with mapping `added` so nothing in the flow is unexplained.
