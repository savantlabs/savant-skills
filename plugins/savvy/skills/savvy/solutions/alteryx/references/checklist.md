# Production checklist — fixed order, one per flow

Same 17 steps, same order, every guide. Status values: `☐` (open) · `☑` (done) · `☑ (dummy)` (done on dummy data only) · `n/a`. The guide's progress line is "N of 17 complete — blocked on step X".

| # | Step | Who | Evidence to record |
|---|---|---|---|
| **Before build** | | | |
| 1 | Confirm the flow is still in use and who owns it. Kill dead flows before migrating them. | Migration lead | owner name, cadence |
| 2 | Capture the Alteryx baseline: export the checkpoints listed in Appendix A (Browse/Output tools) and each input result set as CSV; note the run date. | Alteryx owner | run date, file list |
| 3 | Resolve P1 items (connections, unsupported destinations, code tools, loops). | Savant admin / owner | each P1 resolved |
| 4 | Answer the P2 decision table (accept defaults or override). | Alteryx owner | decisions recorded |
| 5 | Choose target workspace and folder (import requires a folder). | Migration lead | namespace, folder id |
| **Build** | | | |
| 6 | Savvy builds the faithful flow; every step description cites Alteryx tool IDs and rule numbers. | Savvy | flow URL |
| 7 | Bind the real dataset — or the input snapshot captured in step 2 for validation. | Savvy / admin | dataset ids |
| 8 | Analyze run: no step errors; checkpoint row counts match Appendix A expectations. | Savvy | counts per checkpoint |
| **Validate** | | | |
| 9 | Compare Savant output with the baseline on the same input, per Appendix A. | Savvy + owner | counts and deltas per checkpoint |
| 10 | Classify every difference as *intended* (maps to a P2 decision) or *defect* (back to step 6). | Savvy + owner | difference log |
| 11 | Alteryx owner signs off the difference log. | Alteryx owner | name, date |
| **Cut over** | | | |
| 12 | Configure the production destination and schedule. | Savant admin | destination, schedule |
| 13 | Repoint downstream consumers (Tableau workbooks, reports, downstream flows). | Owner | list |
| 14 | One parallel run on live data; repeat the comparison. | Savvy + owner | counts and deltas |
| 15 | Disable the Alteryx schedule; archive the `.yxmd` with a link to this guide. | Alteryx owner | archive location |
| 16 | Fill the runbook block: cadence, trigger, expected volumes, bad-run signals, owner/escalation, rollback. | Migration lead | runbook complete |
| **After sign-off** | | | |
| 17 | Apply the ⚠ P2 defaults (one per versioned change, comparison repeated after each; the guide's P2 row is the full instruction), then P3 cleanups / optimised variant. | Savvy | new flow version, updated *Applied* column |

## Runbook block (step 16)
| | |
|---|---|
| Cadence | |
| Trigger | schedule / manual / upstream event |
| Expected volumes | rows per output and how they relate (e.g. buildings × quarters) |
| Signs of a bad run | e.g. output rows exceed distinct keys; a checkpoint ratio breaks |
| Owner / escalation | |
| Rollback | re-enable the Alteryx schedule; keep old outputs until step 15 |
