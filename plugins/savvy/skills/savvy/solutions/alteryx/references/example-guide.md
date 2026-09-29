# Migration Guide — `office_vacancy.yxmd`

## What this workflow does

Every quarter this workflow pulls the company's office-stock data from the corporate Snowflake warehouse, keeps the Rome market, and publishes two Tableau data sources: a complete building-by-quarter vacancy history with a "Previous vacancy" column (`Office_Roma_Vacancy_Live`), and a one-row-per-building snapshot of the latest closed quarter against the prior quarter (`Office_Roma_Vacancy_KPI_Live`). Along the way it normalises "Roma" to "Rome", excludes the LEGACY_IMPORT lineage, treats blank areas as 0, back-fills quarters where a building was not in stock, and zeroes vacancy for buildings under renovation or out of use.

The Savant flow reproduces this behaviour exactly, including the Alteryx inconsistency that the KPI branch does not apply the renovation rule (P2-1), and writes both tables as CSV until the Tableau replacement is decided.

## Page 1 — Status

| | |
|---|---|
| **Flow** | office_vacancy.yxmd (Alteryx 2024.2) — Rome office vacancy history and quarterly KPI |
| **Alteryx owner** | Research & Data team |
| **Savant flow** | [Rome Office Vacancy – History & KPI]({flow-url}) · Example Property Co › Migration › Test |
| **Coverage** | 55 Alteryx tools → 17 Savant steps · **38 mapped · 0 approximated · 2 unsupported — Publish to Tableau Server (tools 30, 50)** · 15 comments/containers/browse need nothing built |
| **Progress** | **5 of 17 checklist steps complete** — blocked on step 2 (baseline) and step 3 (Snowflake connection, Tableau destination) |
| **Guide generated** | 2026-09-23 · skill v0.1 |

### Blocking items (P1) — must be resolved before production

| # | Item | Why it blocks | Owner | Status |
|---|---|---|---|---|
| P1-1 | No Snowflake connection to `PROD_DW.CURATED` in the target workspace | Flow currently runs on a dummy dataset | Customer Savant admin | ☐ |
| P1-2 | Alteryx publishes to Tableau Server (`.hyper`, 2 data sources) — no Savant equivalent | Downstream workbooks need a new source | Research & Data team + Savant customer success | ☐ decide: Snowflake write-back / OneDrive file |
| P1-3 | Alteryx baseline not captured | Reconciliation (step 9) cannot run | Research & Data team | ☐ export 2 outputs + input result set |

### Decisions that change a number (P2) — accept defaults or override

| # | Alteryx behaviour | Savant default | Effect if accepted | Decision | Applied in Savant flow |
|---|---|---|---|---|---|
| P2-1 | KPI branch does **not** apply the Out-of-Use / Under-Renovation → 0 rule; history branch does (tool 49 vs tools 9–16) | **Match Alteryx** (rule on history only) | KPI tile and trend can disagree for the same building | ☑ match (decided 2026-09-18) | yes (faithful — rule not applied to KPI, as Alteryx) |
| P2-2 ⚠ | "Previous vacancy" in history typed Int32 (tool 47) — decimals truncated | **Keep decimals** | Up to 1 m² difference per row vs Alteryx history | ☑ keep decimals (chosen at intake; pass condition restated in Appendix A) | yes (decimals kept — small-flow exception, not step 17) |
| P2-3 | KPI branch has no dedupe on building + quarter (history has Unique 45) | **Match Alteryx** (no dedupe) | Duplicate source rows would multiply KPI rows | ☑ match | yes (faithful — no dedupe on KPI) |
| P2-4 | Previous quarter = max date of `OFFICE_STOCK_DATA_HIST` (second query, tool 5) | Latest closing date **before** the current one, from the single input | Identical while HIST lags the current snapshot by one quarter | ☑ accept | yes |

*6 cleanup items (P3) found — none change the output. See Appendix C.*

---

## Page 2 — Production checklist

| # | Step | Status | Evidence / note |
|---|---|---|---|
| **Before build** | | | |
| 1 | Confirm flow is in use and who owns it | ☑ | Research & Data team, quarterly |
| 2 | Capture Alteryx baseline: run once, export every Output tool result + the input result set as CSV, note run date | ☐ | Outputs: `Office_Roma_Vacancy_Live`, `Office_Roma_Vacancy_KPI_Live`; input: tool 1 SQL result |
| 3 | Resolve P1 items | ☐ | P1-1, P1-2 open |
| 4 | Answer P2 decision table | ☑ | all four decided |
| 5 | Choose target workspace and folder | ☑ | Example Property Co › Migration › Test (move before cut-over) |
| **Build** | | | |
| 6 | Build faithful flow; every step cites Alteryx tool IDs | ☑ | 17 steps, 3 groups |
| 7 | Bind the real dataset (or a snapshot of the input Alteryx used) | ☐ | dummy dataset bound; swap at input step |
| 8 | Analyze run: no step errors; checkpoint counts match Appendix A expectations | ☑ (dummy) | 40 history rows, 8 KPI rows |
| **Validate** | | | |
| 9 | Compare Savant output with the Alteryx baseline on the same input, per Appendix A | ☐ | needs step 2 + 7 |
| 10 | Classify every difference as *intended* (P2) or *defect*; defects → step 6 | ☐ | |
| 11 | Flow owner signs off the difference log | ☐ | |
| **Cut over** | | | |
| 12 | Configure production destination and schedule | ☐ | depends on P1-2 |
| 13 | Repoint downstream consumers | ☐ | 2 Tableau workbooks |
| 14 | One parallel run on live data; recheck reconciliation | ☐ | |
| 15 | Disable Alteryx schedule; archive `.yxmd` with link to this guide | ☐ | |
| 16 | Fill runbook block (below) | ☐ | |
| **After sign-off** | | | |
| 17 | Apply any remaining ⚠ P2 defaults, then P3 cleanups / optimised variant, one versioned change each with the comparison repeated | ☐ optional | no ⚠ rows pending (P2-2 applied at intake); see Appendix C |

### Runbook block (fill at step 16)

| | |
|---|---|
| Cadence | Quarterly, after `KPI_QUARTERLY_CLOSING_PERFORMANCE` is updated |
| Trigger | `{schedule / manual}` |
| Expected volumes | History: buildings × quarters (was 40 on test data) · KPI: buildings in current or previous quarter |
| Signs of a bad run | KPI rows > distinct buildings in current+previous quarter (duplicates); history rows not a multiple of quarter count |
| Owner / escalation | Research & Data team → Savant customer success |
| Rollback | Re-enable Alteryx schedule; Tableau sources still exist until step 15 |

---

## Appendix A — Validation checkpoints

| # | Alteryx tool | Savant step | Compare | Expected relationship | Result (dummy) |
|---|---|---|---|---|---|
| A1 | 4/8 Filter → 54/55 Filter | S3 | row count | equal | ✓ 8 Rome buildings; Milan and LEGACY_IMPORT rows excluded |
| A2 | 45 Unique | S4 | row count | equal; delta from A1 = duplicates | ✓ RM-0001 duplicate collapsed |
| A3 | 33 Summarize | S5 | row count | = # quarters | ✓ 5 |
| A4 | 32 Summarize | S6–S7 | row count | = # buildings | ✓ 8 |
| A5 | 40 Join (ID=1) | S8 | row count | A3 × A4 | ✓ 40 |
| A6 | 42 Union | S9–S10 | row count | = A5 | ✓ 40 |
| A7 | 50 Publish (history) | **S11 Office_Roma_Vacancy** | rows on (building, Closing_Date); Σ total_vacant_area by quarter; Σ Previous vacancy | rows equal; sums equal except P2-2 decimals | ✓ 40 rows; RM-0004 gap = 0; RM-0005 renovation = 0 |
| A8 | 15 Union | S16 | row count | equal | ✓ 8 |
| A9 | 30 Publish (KPI) | **S18 Office_Roma_Vacancy_KPI** | rows on building; Σ total_vacant_area; Σ Previous vacancy | equal | ✓ 8 rows; RM-0003 dropped → 0 with previous 791.66; RM-0008 new → previous blank; RM-0005 shows 2100.25 (rule not applied, as Alteryx) |

**Deliberate non-matches:** `Previous vacancy` keeps decimals in the history output (Alteryx Int32 truncated — P2-2); `Closing_Date` is the first column of the KPI output (Alteryx placed it last); text is trimmed before both branches (Alteryx trimmed the history branch only); "previous quarter" = latest closing date before the current one (P2-4).

**Baseline capture (step 2):** in Alteryx add Browse/Output tools on tools 45, 33, 32, 42, 15 and on the streams feeding 30 and 50 (tools 16 and 48), plus the two Input tools (1, 5); run once; export each as UTF-8 CSV named `tool<ID>.csv`. Bind the exported input result sets as the Savant source for the comparison run so both engines see identical data.

---

## Appendix B — Logic traceability (Alteryx → Savant)

Savant steps are numbered in execution order; the flow's step names carry the same prefix (`S4 · Keep one record per building per quarter`).

| Alteryx tool(s) | Business rule | Savant step | Mapping | Note |
|---|---|---|---|---|
| 1, 5 Input Data (ODBC `PROD_DW`) | R1 Italy history ∪ current stock stamped with latest closed quarter | S1 · Office Stock Italy (input + adapter to lowercase names, `Closing_Date` as date) | exact | Single input replaces two queries (P2-4); **connection to `PROD_DW.CURATED` needed in workspace (P1-1)** |
| 51, 52 Formula | R2 Roma → Rome | S2 · Standardize labels and treat blank areas as 0 | exact | — |
| 3 Formula (sub-market relabels) | R6 Milan sub-market relabels | S2 | exact | dead code in a Rome flow (C-2) |
| 2 Select, 3 Formula (null→0), 34 Cleanse macro | R5 blank areas → 0; renames; trim | S2 | exact | Cleanse options: trim + null→0 numeric + null→blank text; now applied to both branches |
| 38, 39 Formula (`ID = 1`) | technical | S2 (`All Rows Key` constant) | added | constant key for the all-to-all pairing |
| 4, 8 Filter; 54, 55 Filter | R3 Rome only; R4 exclude LEGACY_IMPORT | S3 · Keep Rome records outside the LEGACY_IMPORT lineage | exact | `!=` on lineage: Alteryx drops NULL lineage rows; test a NULL row before cut-over |
| 45 Unique | R7 one row per building-quarter | S4 · Keep one record per building per quarter | exact | history branch only, as Alteryx (P2-3) |
| 33 Summarize, 35 Sort | R8 quarter list | S5 · List every closing quarter | exact | — |
| 31 Sort, 32 Summarize (Last) | R8 latest attributes per building | S6 · Rank each building's quarters (latest = 1) → S7 · Take each building's most recent attributes | equivalent | Alteryx `Last` depends on Sort 31; replaced by a deterministic rank |
| 40 Join on ID | R8 cross join | S8 · Pair every building with every quarter | exact | constant-key join |
| 36 Join, 43/44 Select, 42 Union, 37 Sort | R8 fill missing quarters | S9 · Attach reported vacancy to each building-quarter → S10 · Fill missing quarters, apply the renovation rule and add previous vacancy | equivalent | left join + `COALESCE(reported, latest)` replaces join + two selects + union |
| 49 Formula, 41 Select | R9 status → 0 | S10 | exact | five sequential IFs → one expression; `'Under Renovation\n'` variant dead (C-4) |
| 47 Multi-Row Formula, 48 Select | R10 previous vacancy (history) | S10 (`Previous vacancy` = LAG per building by quarter) | exact except P2-2 | Alteryx Int32 truncated decimals; kept as decimal |
| 50 Publish to Tableau Server (macro) | Output 1 | S11 · Office_Roma_Vacancy (CSV) | unsupported destination | **Tableau publish has no Savant equivalent — P1-2**; CSV until decided |
| 6, 7 Summarize | R11 current / previous quarter dates | S12 · List closing quarters in the Rome series → S13 · Rank closing quarters (1 = current, 2 = previous) → S14 · Current quarter / S15 · Previous quarter | exact | previous = latest date before current (P2-4) |
| 11, 12 Join | R11 select current / previous records | S16 · Take the current-quarter records / Take the previous-quarter records | exact | not de-duplicated, as Alteryx (P2-3) |
| 14 Join + 15 Union (L, J, R) | R12 buildings in either quarter | S17 · Keep buildings present in either quarter | equivalent | L+J+R union → full outer join |
| 9 Formula, 10/13 Select, 16 Append Fields | R10 (KPI), R12 fallback attributes, stamp current date | S18 · Fill dropped buildings and stamp the current date → Office_Roma_Vacancy_KPI | exact | Append Fields cartesian → window MAX; status rule **not** applied, as Alteryx (P2-1); `Closing_Date` first not last |
| 30 Publish to Tableau Server (macro) | Output 2 | S18 → Office_Roma_Vacancy_KPI (CSV) | unsupported destination | **P1-2** |
| 46 Browse; 17–29 Comments; 53 Container | — | step descriptions / groups | n/a | — |

---

## Appendix C — Cleanup items (P3)

None of these change the output. Apply after sign-off (step 17) if wanted.

| # | Finding | Alteryx tools | Suggested change |
|---|---|---|---|
| C-1 | Second Snowflake query is a strict subset of the first | 1, 5 | Single input (already done in Savant) |
| C-2 | Milan sub-market relabels in a Rome-only flow | 3 | Remove, or parameterise market if the flow is cloned for Milan |
| C-3 | Roma→Rome, Rome filter and lineage filter duplicated per branch | 4, 8, 51, 52, 54, 55 | Once, upstream (done); push into SQL when Snowflake connected |
| C-4 | `'Under Renovation\n'` status variant can never match after Cleanse trim | 49 | Drop |
| C-5 | Seven Select tools exist only to drop `Right_*` fields | 10, 13, 41, 43, 44, 48, 2 | Absorbed into Transform steps (done) |
| C-6 | KPI output is derivable from the history output (filter to current quarter) | 6–16, 30 | Remove Group 3 entirely; fixes P2-1 and P2-3 at the same time |
