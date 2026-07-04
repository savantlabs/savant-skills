# Run Modes

## Objective

Use this to choose how fully to compute a workflow when you need data evidence, and to keep the
cost/risk ladder honest: stay on the cheapest rung that can answer the question correctly.

## Use When

- A node preview is blank and the question needs data behavior evidence.
- Inspection, edit verification, or full delivery needs computed output.
- The user asks to validate a total, check a real row count, test, or run a workflow.

## The three rungs

Cost and risk increase strictly down the list. Default to the top; step down only on a clear
need.

- **Interactive (`--mode interactive`, sampleTier `1k`)** — computes on **≤1000 input rows**,
  no destination writes. Fast iteration default. Because the *input* is sampled, aggregates,
  totals, distinct/dedup counts, and filter/join match-counts on this rung can be **short or
  wrong** — they are computed over at most 1000 rows, not the full data.
- **Analyze (`--mode analyze`, sampleTier `max`)** — reads the **real full source**, computes on
  full data, **no destination writes**. Intermediate results are trimmed to a working volume cap
  (~32 MB), so it is "much fuller than 1k," not a guarantee of every row on very large/wide
  intermediates. This is the validation rung for full-data correctness.
- **Batch (Test / Run)** — durable execution submitted as a job, queried by execution id.
  **Test** reads real sources but skips destination writes; **Run** reads real data **and writes
  destinations** (files, emails, API calls, system updates). Savvy does **not** submit
  Batch executions — see "Batch is read-only here."

There is also **cached** (`--mode cached`, the default for read helpers): read the node's
existing `Ready` preview without computing anything. Use it first whenever a preview is already
available.

## Default Action

- Use existing preview/output first (`--mode cached`) when a `Ready` preview is available.
- Compute at **Interactive** (`--mode interactive`) when you need fresh data and the question
  does not depend on seeing all rows.
- Step up to **Analyze** (`--mode analyze`) only on a clear need for full-data fidelity (below).
- Never auto-run **Batch**. Test and Run require explicit user confirmation of the mode and side
  effects.

## Interactive first, then decide

Interactive is always the first pass (see Default Action), including the first sanity check of a
newly created workflow. Let its result decide whether Analyze is needed at all:

- **Returned fewer than ~1000 rows end-to-end (not capped)** — the full source fit inside the 1k
  sample, so Analyze would compute the identical numbers. Don't escalate; the Interactive result
  is final, even for totals and counts.
- **Capped at ~1000 rows** (real volume exceeds 1000 somewhere) **and** the answer needs full-data
  correctness — a **sum / total / aggregate**, a **distinct or dedup count**, or a **filter or
  join match-count** ("how many rows actually pass / match?"). Only then step up to Analyze, with
  a one-line heads-up to the user.
- **User explicitly signals it** — "validate," "check the real total," "is this right on full
  data," "the preview number looks wrong." Honor it.

Example heads-up: *"The 1k preview is capped at 1000 input rows and your real data is larger, so
this total isn't trustworthy — running a full-data Analyze (no writes) to confirm."*

Do not escalate for config/schema/column checks, "did it produce rows," structural questions,
per-row spot checks, post-edit smoke, or any case where Interactive was not capped — those are
final on Interactive.

## Newly created sources: let the cache warm

A just-created source's full-data cache takes minutes to populate (size-dependent). Analyze
(`sampleTier=max`) reads that cache, so an Analyze run fired immediately after a create returns
the source — and everything downstream — as **Skipped**. That `Skipped`-with-no-`Failed`-root
state right after a create is **cache warm-up, not a defect**: don't diagnose it as a broken
workflow, and don't step up to Analyze in the same breath as the create.

This is another reason Interactive is the first pass — the 1k sample is available much sooner
than the full cache. Validate a fresh flow on Interactive first; if you genuinely need Analyze on
a newly created source (per the gate above), give the cache time and re-run rather than reading
the early Skipped as failure.

## When to step up to Batch

Only on a **clear user intent for a real run**, and always with explicit confirmation:

- **Test** when the user wants true end-to-end behavior against real sources without side
  effects.
- **Run** when the user wants the workflow to actually execute and write outputs.

Batch is never agent-initiated from a read question. Treat Run as a destructive action: confirm
the side effects first.

## Do Not

- Do not trigger any compute for visual-only verification (layout, label, group, color, spacing).
- Do not treat a blank preview as zero rows. Zero rows is a real signal; blank means "not
  computed yet."
- Do not present a 1k aggregate/total/match-count as the final answer without noting it is a
  sample, or escalating to Analyze.
- Do not run Test or Run without explicit user confirmation of the mode and its side effects.
- Do not pass a fictional sample tier. The backend tier is **binary**: only `analyze`/`max`
  computes on full data; `interactive`/`1k` is the sample. There is no `2k`/`10k`/`50k` rung —
  any such value silently behaves as 1k.

## How to trigger

Use the helpers; they own the API path and speak one run-mode vocabulary across
`preview nodes`, `workflow health`, `workflow inspect`, and `app --inspect-node`:

```
--mode cached       # read existing Ready preview; no compute (default for reads)
--mode interactive  # compute at 1k input sample
--mode analyze      # compute at the full-source max tier, no writes
```

Two advanced scope levers (both repeatable) make full-data Analyze affordable — see
"Advanced: scope the computation" below.

Confirmed compute API surface:

- Trigger node computation: `POST /api/interactive/graph-computation?sampleTier={1k|max}`
  (add `&action=APPLY` only when recomputing from an edited starting node, to evict its cache
  first). There is no `action=ANALYZE` — that value is a no-op.
- Poll status: `GET /api/interactive/graph-computation-status?flowId={flowId}&sampleTier={1k|max}`.
- Fetch preview output:
  `POST /api/interactive/graph-computation-sort?flowId={flowId}&nodeId={nodeId}&sampleTier={1k|max}`.

The shared helper `savant.py app` owns the low-level path for single-node inspection
(`--inspect-node`, with `--mode`). For multiple node previews in one pass, use
`savant.py preview nodes` (default `--mode cached`; pass `--mode interactive` or
`--mode analyze` to compute).

Do not run a compute mode merely for visual verification. Layout, text, group, label, color, and
spacing checks are not data-preview questions.

## Advanced: scope the computation

These levers only matter on `interactive`/`analyze`, and they are the main way to keep a
full-data Analyze cheap. They are exposed as flags on the compute helpers:

- **`--up-to NODE` (stopping node)** — compute only the path **up to** the node(s) you care
  about; everything downstream is pruned and never computed. Validate one aggregate without
  running the whole flow to its destination. (For `preview nodes`, the requested nodes are
  themselves the stopping set.)
- **`--from NODE` (starting node)** — recompute **from** a changed node forward, reusing the
  cached upstream results. "Validate my edit without re-reading the sources." Pairs with
  `--up-to` to compute a minimal segment of the DAG. When a starting node is given, the helper
  sends `action=APPLY` so the edited node's stale cache is evicted before recompute.

Cache reuse vs. bust is **not** a user-facing lever: reads reuse the `Ready` cache; the
edit/applier verification path forces a fresh recompute internally. Don't try to manage the
cache by hand.

Caveat: Analyze's ~32 MB intermediate volume cap means a very large/wide intermediate may still
be trimmed. Analyze is "full source, bounded working volume," not "every row guaranteed." If a
result must reflect every row with certainty, that is a Batch concern, not Analyze.

## Batch is read-only here

Savvy reads Batch **history** but does not submit Batch executions. To actually Test or Run
a workflow, the user triggers it in the Savant UI (the Analyze split button's Test/Run options,
top bar). For "did it run / test / succeed / fail / produce output?" questions, use
`../standards/run-history-substrate.md` (it reads `GET /api/recipes/{flowId}/executions` and
execution detail). Do not infer execution from the recipe JSON or from an Analyze preview — an
Analyze result is not a run.
