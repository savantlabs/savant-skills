# Validation — checkpoints and baseline comparison (guide content only)

The skill documents *how* to validate; it does not build validation flows in this version. Appendix A of the guide carries the checkpoints; the owner compares exports by hand or with Savvy's help in a later conversation.

## Checkpoints (`inventory.checkpoints`)
`savant.py alteryx parse` marks every tool where the row count changes: Filter, Join, Union, Summarize, Unique, Append Fields, CrossTab/Transpose, Sample and every output (including output macros). Each carries inferred grain keys (from the nearest Unique / Summarize / Join config), an expected relationship and a priority:

| Priority | Tools | Shown in Appendix A |
|---|---|---|
| 1 | Outputs | always — reconciled row-for-row and measure-for-measure |
| 2 | Union, Unique, Summarize, CrossTab/Transpose | always — where logic errors show first |
| 3 | Filter, Join | only when a defect needs localising |

After the build, fill the *Savant step (S-number)* column so each row reads *Alteryx tool → Savant step → compare → expected*.

## Baseline capture (checklist step 2) — manual for now
Tell the owner exactly which Alteryx tools to export: add a Browse or Output Data tool on each priority-1/2 checkpoint listed in Appendix A, plus one on each Input Data tool so the exact input result set is kept; run once; save every file as UTF-8 CSV named `tool<ID>.csv`. Use the same input snapshot for the Savant validation run — comparing runs on data pulled on different days produces false differences.

## Comparing
For each checkpoint: row counts must satisfy the expected relationship; for outputs, match on the grain keys and compare measures within tolerance (default 0.01; text trimmed, keys case-insensitive unless the P2 table says otherwise). Every difference is classified *intended* (cite the P2 row) or *defect* (name the S-step; fix; re-run). Sign-off (step 11) is on the classified list.

Savvy can build the comparison as a Savant flow when asked ("reconcile the baseline export against the Savant output on keys …"); that is a normal Savvy build, not part of this skill's output.
