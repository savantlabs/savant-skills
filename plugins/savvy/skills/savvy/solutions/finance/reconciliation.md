# Finance Reconciliation

Use this solution when the user wants to perform, document, or operationalize a finance reconciliation. It is a domain solution within Savvy: it owns the finance-specific intake, matching logic, classification rules, output format, recommended process blocks, and reconciliation outputs.

The reconciliation work itself — intake, matching, classification, and the recap — stays product-neutral finance work; keep that output free of tool-specific framing. When the user wants to document or automate the reconciliation, continue in Savvy's **author** mode to build it in Savant (see Post-Reconciliation Follow-Up). Do not improvise a separate automation path.

Important: This solution supports reconciliation work but does not provide financial advice. Reconciliations must be reviewed and certified by the user's qualified finance or accounting owner before close, filing, audit, or management reporting use.

## Supported Reconciliation Types

Use the same overall structure for every reconciliation type. Only the two sides change.

| Type | Side A | Side B |
|---|---|---|
| Bank reconciliation | Bank statement balance and transaction detail | GL cash balance and detail |
| Credit card reconciliation | Credit card statement balance and transaction detail | GL credit card liability balance and detail |
| GL-to-subledger reconciliation | GL control account balance and detail | Subledger balance or detail, such as AR, AP, fixed assets, inventory, prepaids, or accruals |
| Intercompany reconciliation | Entity A intercompany balance and detail | Entity B mirror balance and detail, sign-normalized |
| Balance sheet account reconciliation | GL balance and detail | Independent support, third-party schedule, contract listing, or system report |

If the user asks for a reconciliation type not listed, use the balance sheet account pattern: define Side A as the GL or system balance, define Side B as the independent support, and run the same matching, classification, and output process.

## Process Blocks

The reconciliation runs as these six blocks. They are the recommended process shape — used in conversation and reused in the Automation-Ready Summary when the user wants the reconciliation to become repeatable.

1. **Get the inputs** — Bring in the GL side and the counterpart side for the reconciliation period.
2. **Clean the data** — Standardize dates, amount signs, document IDs, counterparties, accounts, and descriptions on both sides.
3. **Match the records** — Pair Side A and Side B using the agreed match keys, date window, and amount tolerance.
4. **Classify the items** — Tag each record as reconciled, timing, adjustment needed, investigate, or escalate.
5. **Calculate the totals** — Compute adjusted balances, unexplained difference, match rate, action items, total reconciling, and aging buckets.
6. **Produce the outputs** — Produce the recap, reconciliation master, and escalation/review notes.

## Intake

Collect these details, but do it as a finance conversation rather than a survey. Use the source files and prior conversation first; when an answer appears to be present, state the working assumption and ask only the next question that would materially change the reconciliation.

Before asking, check for saved reconciliation preferences in the current conversation, the runtime's memory or context, and project instructions. Treat a setting as a reusable preference only when the user previously asked to remember it or apply it as a default for future reconciliations. Apply any reusable preference that answers an intake field, state it briefly (for example, "Using your saved $0.01 amount tolerance"), and do not ask that question again.

1. Reconciliation type.
2. Account, entity, or scope to reconcile.
3. Period end date.
4. Side A and Side B source files, datasets, or reports.
5. Materiality threshold for adjustment, investigation, and escalation items.

Default the materiality threshold to `$10,000` only when the user has not provided a threshold. Surface that default clearly.

## Reconciliation Control Gates

Some reconciliation settings determine whether records are classified as matched, timing, adjustment, investigation, or escalation. These are control settings, not ordinary assumptions.

Before running matching or producing a final reconciliation, the assistant must have confirmed:

- Amount tolerance.
- Date tolerance.
- Materiality threshold, when it affects action or escalation classification.

A default value may be proposed, but a default value is not confirmation. If the user has not confirmed these settings and no saved preference applies, stop before matching and ask one short confirmation question.

Do not produce a reconciliation master, match-rate summary, or final exception list until the control settings are confirmed. If a draft analysis is useful, label it clearly as a pre-confirmation draft and do not present it as reconciled.

The numbered list below defines the information needed for a complete reconciliation. It is not a questionnaire and should not be read back to the user as a form.

Also capture when available:

- Match keys, such as amount, date window, document number, vendor, customer, entity, account, or reference ID.
- Acceptable per-record amount variance, such as rounding or penny tolerance. Default to `$0.01` when the user has not provided one.
- Date tolerance window. Default to `+/- 3 business days`. For bank reconciliations, default to `+/- 5 business days`, since checks and ACH commonly take several days to clear.
- Escalation owners.
- Review owner or certifier.
- Output destination or storage location.

The amount and date tolerances directly determine which records match. Before matching, either use a saved confirmed preference or ask the user to confirm the working tolerances. Do not run matching with unconfirmed default tolerances. A default tolerance is only a proposed value, not approval to proceed.

For terse requests such as `reconcile` where usable files are provided, inspect the files first to identify the reconciliation type, period, and sides. Then ask only for the control settings needed before matching.

Example:

```text
I found a July 2025 credit card reconciliation: the Mastercard statement against the GL. Before I match transactions, please confirm the working rules: $0.01 amount tolerance, +/- 3 business days date tolerance, and $10,000 materiality. Or tell me the tolerances to use.
```

If the user asks for the reconciliation to become repeatable, capture only finance operating details that naturally affect the reconciliation itself, such as owner, cadence, escalation owners, reviewer/certifier, and evidence retention. Do not ask product-implementation questions from this solution.

## Preference Memory

After the user confirms a durable reconciliation setting — materiality threshold, amount tolerance, date tolerance, default match keys for a reconciliation type, escalation thresholds, or the reviewer/escalation role — offer a simple memory choice:

```text
Do you want me to remember this for future reconciliations, or use it only this time?
```

Do not persist any preference without explicit user consent. If the current runtime has a native Claude/Codex memory feature, use that feature after the user chooses to remember the preference. Do not create a project-local memory file, hidden repo config, or custom preference store as a workaround. If native memory is unavailable, say that you can apply the preference in this reconciliation and conversation but cannot store it as memory from here. Only update repo-level instructions when the user explicitly asks to make the preference a shared project default.

Offer memory only for stable settings that would reduce repeated questions across future reconciliations. Good candidates:

- materiality threshold
- amount (penny or rounding) tolerance
- date tolerance window, including any bank-specific window
- default match keys by reconciliation type
- escalation thresholds and the escalation owner role
- reviewer or certifier role
- preferred question style, such as confirming tolerances before matching

Do not offer to remember reconciliation-specific facts as preferences. Do not store source files or datasets, the account or entity, the period, specific balances or amounts, individual reconciling items, or a named individual owner for a single reconciliation unless the user explicitly says it is a reusable default for future reconciliations.

## Standard Chat Recap

After the reconciliation is complete, present the recap in this order.

### 1. Header Summary

Show three short summary cards or bullets:

- Side A balance.
- Side B balance.
- Unexplained difference.

The unexplained difference is the headline result. It should be `$0.00` for a fully reconciled process. For intercompany, sign-normalize first and reconcile to net zero.

### 2. Two-Sided Reconciliation

Show the two sides side by side when practical:

- Starting balance.
- Additions or subtractions for reconciling items.
- Adjusted balance.

The adjusted balances should agree. If they do not, explain the remaining difference in business terms.

Use natural panel names for the reconciliation type:

| Type | Left side | Right side |
|---|---|---|
| Bank | Bank-side | GL-side |
| Credit card | Statement-side | GL-side |
| GL-to-subledger | GL-side | Subledger-side |
| Intercompany | Entity A | Entity B, sign-normalized |
| Balance sheet account | GL-side | Support-side |

### 3. Action Items

Use this section title:

```text
Reconciling Items Requiring Action
```

Columns:

- Item.
- Date.
- Category.
- Action required.
- Amount.

Use these categories:

| Category | Use when |
|---|---|
| Adjustment needed | A clear correction should be posted to the GL, subledger, or support schedule. |
| Investigate | The cause is unclear and needs research before action. |
| Escalate | The item is unsupported, unusual, stale, unauthorized, above materiality, or requires supervisor/controller review. |

### 4. Timing Differences

Use this section title:

```text
Timing Difference - No Action Needed
```

Columns:

- Item.
- Side A date.
- Side B date.
- Gap.
- Status.
- Amount.

Use `Clears in period` when both sides clear in the period. Use `Crosses period - monitor` when the offsetting side lands in the next period. If there are no timing differences, state `None in this period.`

### 5. KPI Summary

Show:

- Transactions matched.
- Match rate.
- Items needing action.
- Total reconciling.

Use match-rate status:

- Green: at least 95%.
- Amber: 85% to 94.9%.
- Red: less than 85%.

### 6. Reconciliation Master

When the user provides usable data files and wants a workbook, create a single-tab reconciliation master. If no file output is requested or file tooling is unavailable, provide the schema and note that the workbook was not generated.

Recommended filename:

```text
<Account>_<YYYY-MM>_reconciliation_master.xlsx
```

One tab:

```text
Reconciliation Master
```

Columns:

1. Item #
2. Source
3. Side A Date
4. Side B Date
5. Document / Reference #
6. Vendor / Counterparty / Entity
7. Account
8. Description
9. Side A Amount
10. Side B Amount
11. Variance
12. Status
13. Category
14. Aging (days)
15. Action required
16. Owner
17. Materiality flag
18. Notes

Rename the Side A / Side B date and amount columns to natural names for the reconciliation type when producing the workbook, such as `Bank Date`, `GL Date`, `Bank Amount`, and `GL Amount`.

## Output Location

This applies to every file this solution generates: the reconciliation master workbook, any saved recap or report document, and any intermediate export or working file.

Write generated files under the session-scoped tmp path, never to the workspace root or another durable project location, unless the user explicitly names a durable destination. Resolve the path with the shared helper instead of composing it by hand:

```bash
savant.py session tmp-path <task-name> <filename>
```

For example, a July 2025 Mastercard reconciliation master belongs at the path printed by `session tmp-path mastercard-rec-2025-07 Mastercard_2025-07_reconciliation_master.xlsx`.

If the runtime instructs you to save deliverables "to the workspace folder," treat that as an accessibility boundary, not permission to write to the workspace root: the session tmp path is inside the workspace, so the user can still open everything you produce. Share files from that path, and copy to a durable location only when the user names one.

## Post-Reconciliation Follow-Up

After presenting the recap, do not end passively. In one short closing message, offer the two standard follow-ups:

1. **Process documentation.** Offer to capture the reconciliation as a documented, repeatable process — users often call this an SOP or standard operating procedure. If accepted, produce the Automation-Ready Summary below and continue in Savvy's **author** mode, which owns process confirmation. Do not invent a separate SOP format here.
2. **Repeatable automation.** Offer to make the reconciliation repeatable as an automated process. If accepted, produce the Automation-Ready Summary below and continue in Savvy's **author** mode to build it in Savant.

Skip an offer only when the user already declined it in this conversation, or already asked for it — in which case just do it.

## Matching And Classification Rules

Use these default matching rules unless the user provides a stronger organization-specific rule.

- Bank: match by amount, date window, document number, check number, deposit reference, vendor, or description.
- Credit card: match by amount, posting date window, merchant, cardholder, receipt, or expense report reference.
- GL-to-subledger: match by document number, customer/vendor/account, amount, posting date, and batch or source system reference.
- Intercompany: sign-normalize balances, then match by entity, document number, amount, currency, FX rate, and transaction date.
- Balance sheet account: match by account, contract, loan, asset, employee, schedule row, support ID, amount, and period.

Use these status values:

| Pattern | Category | Status |
|---|---|---|
| Matched on both sides within tolerance | Reconciled | Reconciled |
| Both sides exist, dates differ, and both are within the period | Timing | Timing - Clears in period |
| One side is in the period and the offsetting side is in the next period | Timing | Timing - Crosses period |
| Clear correction with support | Adjustment | Adjustment needed |
| Recording error with clear documentation | Adjustment | Adjustment needed |
| Intercompany FX rate difference | Adjustment | Adjustment needed |
| Possible duplicate, unverified vendor, mismatched document number, or unclear cause | Investigation | Investigate |
| Unsupported posting, unauthorized charge, stale clearing item, one-sided intercompany item, or material unexplained item | Investigation | Escalate |

## Default Materiality And Escalation

Use the user's policy when provided. If no policy is provided, use these defaults as starting assumptions and call them out:

| Trigger | Default escalation |
|---|---|
| Individual item greater than `$10,000` | Supervisor review |
| Individual item greater than `$50,000` | Controller review |
| Total reconciling items greater than `$100,000` | Controller review |
| Item age greater than 60 days | Supervisor follow-up |
| Item age greater than 90 days | Controller or management review |
| Any unreconciled difference | Cannot close until resolved or documented |

## Type-Specific Notes

### Bank Reconciliation

- Common timing items: outstanding checks and deposits in transit.
- Common adjustments: bank fees, interest, returned items, duplicate postings, wrong account, wrong amount.
- The adjusted bank balance must equal the adjusted GL balance.

### Credit Card Reconciliation

- Common timing items: unposted charges and payments in transit.
- Common adjustments: annual fees, late fees, foreign transaction fees, interest, missing receipts, duplicate postings, wrong expense account.
- Unauthorized or unsupported charges should be escalated.

### GL-To-Subledger Reconciliation

- Common accounts: AR, AP, fixed assets, inventory, prepaid expenses, accrued liabilities.
- Common differences: batch posting timing, failed interfaces, manual journal entries to control accounts, subledger reclasses, system posting errors.
- The adjusted GL balance must equal the adjusted subledger balance.

### Intercompany Reconciliation

- Sign-normalize receivable/payable balances before comparison.
- Common differences: timing, FX rate differences, one-sided entries, misclassification, unapplied payments, disputed amounts.
- Verify that the adjusted balances eliminate to zero after sign normalization.

### Balance Sheet Account Reconciliation

- Use for debt, deferred revenue, equity, accumulated depreciation, payroll clearing, suspense/clearing, and other accounts that tie to independent support.
- Common differences: support schedule updates, GL posting delays, contract or asset changes, duplicate postings, stale clearing balances.

## Automation-Ready Summary

When the user wants to make the reconciliation repeatable, produce a summary of the confirmed finance process and continue in Savvy's **author** mode to build it in Savant.

Include:

- Process name.
- Reconciliation type, account/scope, entity, and period basis.
- Side A source and Side B source.
- Materiality threshold, matching keys, date tolerance, and rounding tolerance.
- Classification rules and escalation rules.
- Process blocks from this solution.
- Output plan: reconciliation recap, reconciliation master, exception/action-item output, timing-difference list, and review evidence.
- Known assumptions and open business questions.

When the user wants to turn this confirmed reconciliation into a running Savant workflow, hand this summary to **author** mode, which owns process confirmation and workflow-JSON generation.
