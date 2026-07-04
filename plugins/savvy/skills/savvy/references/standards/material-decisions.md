# Material Decisions

A **material decision** is any choice that changes *what the workflow does to the data* and that a user would reasonably want to sign off on. It is the unit that must stay consistent between **what the user approves** and **what gets handed to the Builder**.

The bug this guards against: the planner asks the user to approve one thing ("normalized vendor") but hands the Builder another ("AI canonical vendor name, then uppercase/trim text key"), so material logic the user never plainly approved gets built. Material decisions close that gap — every material choice is written down, approved, and then verified to be reflected in the handoff.

## What counts as material

A decision is material if it changes the output, the matching, or the interpretation of the data. Typical families:

- **AI use** — any step that uses a model (extraction, classification, canonicalization, enrichment, sentiment, summarization). Whether to use AI *at all* is itself a material decision — see [Choosing AI vs deterministic](#choosing-ai-vs-deterministic) below.
- **Fuzzy / approximate matching** — non-exact joins or dedup.
- **Normalization strategy** — case folding, trimming, canonical forms, standardizing codes/units.
- **Thresholds** — confidence cutoffs, tolerance bands, amount/quantity limits that gate behavior.
- **Fallback logic** — what happens when a lookup misses, a field is null, or a parse fails.
- **Ranking / tiebreaking** — how the "winner" is chosen when multiple candidates qualify.
- **One-to-one match rules** — deduplication and "pick one" rules that collapse rows.
- **Source-of-truth precedence** — which source wins when sources disagree.
- **Exception categories** — how rows are classified as matched / unmatched / needs-review.
- **Output grain** — the row level of each output (per transaction, per account, per period).
- **Audit fields** — derived columns added for traceability, review, or controls.

This list is a guide, not a closed enum. If a choice changes results and a reviewer would want to see it, treat it as material.

AI use is **not** privileged over the other families — it is one material decision among equals. It is called out first only because it is the most common source of undisclosed logic, not because it gets special validation.

## Choosing AI vs deterministic

Many steps can be built either way, so the planner must make the call **before presenting the plan** — never leave it for the Builder to infer, and never hide it behind a vague verb like "normalize." The default rule:

> **Prefer deterministic** logic when the rules are limited, stable, and definable. **Prefer AI** when the inputs are messy, meaning-based, open-ended, or changing enough that deterministic rules would be brittle or high-maintenance.

There are two kinds of AI use, disclosed differently:

- **Required AI** — Savant needs AI/vision to turn unstructured documents or images into structured data: PDF statements, invoices, receipts, scanned forms. There is no deterministic alternative, so disclose *that* AI does the extraction; the "why" is self-evident.
- **Chosen AI** — both a deterministic and an AI approach are possible, but the input variation is too broad or meaning-based for rules to be practical: vendor normalization, sentiment, free-text classification, memo interpretation. Here the plan must say *what the AI is doing and why it was chosen over the deterministic alternative*, and that reason goes in the decision's `rationale`.

Keep these deterministic unless there is a clear reason not to: amount thresholds, date tolerances, exact formulas, known mappings, and fixed/controlled categories.

## Material decisions vs. material assumptions

The checkpoint carries both `material_decisions[]` and `material_assumptions[]`; they are different:

- **Assumption** — an interpretation the planner made because information was missing or ambiguous (e.g. "treated blank region as Domestic"). It affects how to *read* the request.
- **Decision** — material logic the workflow *performs* and the user approved (e.g. "match vendors with AI canonicalization"). It affects what the workflow *does*.

An assumption can become the rationale for a decision ("user approved the assumption"), but the decision is the thing that must be reflected in the handoff.

## The contract

1. **Write them down and get approval.** During planning, capture every material decision in `workflow_plan_checkpoint.material_decisions[]` and present them to the user in business language. Each entry records:
   - `decision` — the approved choice, in business terms.
   - `rationale` — why it was made. Free text; common values: `user requested`, `user approved assumption`, `complex text processing`, `data-quality necessity`.
   - `reflected_in_handoff` — a boolean the planner ticks **after** building the handoff.
2. **Build the handoff to match.** Generate `process_blocks`, `business_steps`, `sources`, and the rest to implement exactly the approved decisions — and add nothing material beyond them.
3. **Self-review, then tick.** After the handoff is composed, re-read it against each decision and set `reflected_in_handoff: true`. This is a judgment step (the planner is the reviewer); the planner-`done` gate enforces that the review happened — it fails unless every decision is present, has a rationale, and is marked reflected.

If the handoff contains material logic that is not in `material_decisions[]`, the planner either missed a decision (add it, and confirm it was approved) or introduced unapproved logic (remove it, or get approval first).

## Why the validator is deterministic but the judgment is the planner's

Whether a decision is "truly reflected" and whether the list is "complete" require reading the plan and the handoff — judgment that cannot be reliably codified. So the validator does not attempt it. It enforces the *shape* of the recorded review (every decision present, rationale non-empty, `reflected_in_handoff: true`), the same way `user_confirmation_evidence` is enforced today: deterministic proof that the AI did a disclosed reconciliation, not a claim that code understood the plan.
