# Workflow Inspection Rules

## Objective

Use this to answer read-only questions about a live Savant workflow from recipe JSON, computed node outputs, and run/test evidence.

## Use When

- The user asks what a workflow, step, branch, output, run, or error is doing.
- A Creator or Editor needs post-change verification.
- A diagnosis needs data behavior evidence: row counts, sample rows, schemas, or node status.
- A layout/visual-organization question is answered from the recipe graph (there is no rendered-canvas inspection).

## Default Action

- For routine post-import or post-edit verification, run `savant.py workflow verify` (structural: folder, persistence, before/after diff, validation), then `savant.py workflow inspect` (data evidence). Both take the recipe re-fetched with MCP `fetch`.
- For status/debug/fix-readiness questions, run `savant.py workflow health` first.
- For targeted questions, orient with the API recipe, inspect the specific node/branch, then fetch preview/output evidence only when the question needs it.

## Do Not

- Do not edit, save, add, delete, or rewire during inspection.
- Do not use rendered canvas/DOM as a substitute for API recipe, config, schema, status, row-count, or sample-row evidence.
- Do not compute (Interactive/Analyze) or run Batch (Test/Run) unless the user's question or completion criteria require data behavior evidence and the run-mode rules allow it.
- Do not call a workflow fixed, clean, production-ready, or fully verified unless the applicable edit/create/full-verification path also ran.

## Helpers

The standard whole-flow verification pass is `savant.py workflow verify` followed by `savant.py workflow inspect` (see "Standard verification pass" below). Lower-level helpers: internal app API in `savant.py app`; compact recipe mapping in `savant.py workflow map` (file-only — it reads a fetched recipe and needs no API at all); validation-checkpoint targeting in `savant.py workflow targets`; batch node preview inspection in `savant.py preview nodes` (needs `--workflow-json`); run-mode side effects in `../substrate/run-modes.md`. There is no rendered-canvas visual inspection — inspect through the API only.

## Scope

Live inspection answers questions like:

- What does this node do?
- What data reaches this point?
- Why did this filter, join, summarize, or transform produce these rows?
- Which upstream step likely caused an unexpected result?
- Does the workflow's behavior match the intended logic?

Inspection is read-only. It may diagnose a likely fix, but remediation belongs to the editor, creator, builder, or downloader path depending on the task.

## Standard verification pass (use savant.py workflow inspect)

For the routine post-import (Creator) or post-edit (Editor) verification — "is the created/edited flow structurally sound and producing the right output?" — run `savant.py workflow inspect` instead of issuing per-node Analyze calls and interpreting each by hand:

```bash
savant.py workflow inspect "{flowUrl}" --recipe-json <after.json> \
  --imported-json <workflow.json> --expected-outputs-json <builder_to_creator.handoff.json> \
  --checkpoint "<stage>" [--checkpoint "<stage>" ...] \
  --output-path "$(savant.py session tmp-path "<task-name>" inspect.json)"
```

`--recipe-json` is required and is the live recipe from the MCP `fetch` tool on `savant://workflow/{flowId}`; the harness refuses a recipe whose flow id is not the target flow. It orchestrates `workflow_targets`/`node_previews`/`savant_app_api` and returns a pass/fail report over the standard checks: **persistence** (source JSON `nodes.length` + node names == live recipe after import — also checked independently by `savant.py workflow verify`), **runtime-smoke** (after create/save success, compute the requested checkpoints status-only and fail fast on Failed/Error/Canceled), **node-ok** (every checkpoint is `Ready`), **output-contract** (only after runtime-smoke passes, each planned output's destination/checkpoint schema matches that output's expected columns and grain/check contract), and **row-sanity** (a Ready-but-0-rows checkpoint is flagged). If runtime-smoke fails, the report includes `previewSkipped` and no output preview/schema checks are attempted. The verify pass computes at Interactive (1k) by default; pass `--mode analyze` only when a checkpoint needs full-data validation. `--expected-outputs-json` can point at a Builder-to-Creator handoff; the Inspector reads `sections.builder_preflight.output_destination_plan.outputs`. Name deterministic stages with `--checkpoint`; computing an AI/gen_ai terminal still costs that node's run time. The older `--expect-columns` flag is only for simple single-output checks.

The harness is the runtime counterpart to `savant.py validate workflow` and owns the standard *mechanics*. The sections below are for what it does **not** do: targeted/diagnostic inspection (root-causing an unexpected result), interpreting row counts in business terms, no-data handling, and walkthroughs. Use the harness first; drop to the manual steps for judgment and for anything beyond the standard checks.

## API Authority

Use structured API inspection for every workflow fact the API can provide:

1. Use `savant.py app` or its Python functions to read the workflow recipe with `GET /api/recipes/{flowId}`. Keep this JSON in memory unless the user asks for an export or you need a debug artifact.
2. Use the recipe as the workflow map: node ids, labels, types, configs, expressions, source metadata, destinations, inlets, outlets, and branches.
3. When data evidence is needed for one node, first check whether existing preview output is available (`--mode cached`). Compute that node only when the user's request or confirmed scope calls for it — `--mode interactive` for a fast 1k sample, `--mode analyze` when the answer depends on full data (totals, dedup, match-counts).
4. When data evidence is needed for multiple selected checkpoints, use `savant.py preview nodes` with `--workflow-json <recipe.json>` so the helper returns output for each requested node id. The default (`--mode cached`) reads already-available preview status/output only; pass `--mode interactive` or `--mode analyze` to compute. See `../substrate/run-modes.md` for when to escalate.
5. The API recipe/output is the authoritative source for every workflow fact: recipe config, graph shape, row count, schema, sample rows, node status, and workflow errors. There is no browser/canvas source to consult.

Do not treat API failure as permission to invent or guess. If session discovery, recipe read, Analyze, or output fetch fails, report the API failure plainly and stop. If Analyze returns a node failure, report it as workflow evidence.

Do not run Analyze/node previews for layout-only questions or edits. Layout, label, group, note/text, color, and spacing changes are verified through recipe persistence plus the deterministic layout metrics (`canvas-layout-rules.md`); they do not need data preview evidence unless the user also asks about data behavior.

## Orient The Flow

1. Parse the `https://app.savantlabs.io/en/app/flow/{flowId}?rns=...` URL.
2. For status, health, issue, error, and fix questions, run `savant.py workflow health` first. It gathers recipe status, version status, Run/Test history, and source dataset matches, and does not compute by default. Add `--mode interactive` (or `--mode analyze`) only when the user asked for data behavior evidence and you want the single earliest-checkpoint preview. Do not start with downstream or parallel preview checks.
3. For targeted behavior questions, build the workflow map from the fetched recipe JSON. Use `savant.py workflow map --input-json <recipe.json>` when a compact graph map will speed orientation; it needs no API access.
4. If API orientation fails, stop and report that the workflow could not be inspected through the API. Do not reconstruct the workflow from the rendered canvas.
5. Visual-layout questions (label overlap, group readability, connector routing) cannot be answered — there is no rendered-canvas inspection. Answer structure and data from the API; for layout, describe what the recipe graph implies and say the rendered canvas was not inspected.
6. Capture the minimum map needed for the question:
   - flow name
   - nodes with id, type, label, and selection state
   - edges / outlet pseudo-nodes
   - group labels when present in the recipe

Use `savant.py workflow targets` when you need a starting list of likely validation checkpoints for inspection or full-delivery verification. Treat its output as suggestions, not a mandatory checklist; the user's question and workflow shape decide which targets matter.

The flow name is required evidence for any first response about a specific flow. If it cannot be read, say so.

## Health Check First

Use the health helper as the default first step when the user asks:

- "current status"
- "does it have issues?"
- "what is broken?"
- "what is the fix?"
- "why is this workflow not working?"
- "is this ready?"

Expected command shape:

```bash
savant.py workflow health "{flowUrl}" \
  --workflow-json <recipe.json> --sources-json <sources.json> \
  --output-path "$(savant.py session tmp-path "<task-name>" health.json)"
```

`--workflow-json` is required: the recipe comes from the MCP `fetch` tool on
`savant://workflow/{flowId}`, not from the API. `--sources-json` (the MCP `search` result for
`types: ["source"]`) enables the dataset-matching leg; omit it and matching is *skipped*, not
reported as zero matches. Run history and the optional preview still need `api_enabled`.

The helper's source findings are enough to stop early when source steps are missing, ambiguous, or placeholder-like. In that case, report the source binding issue as the likely first blocker and avoid downstream Analyze calls until the sources are healthy.

If Analyze preview was explicitly included and the health helper's single preview fails, report that first failing checkpoint and its API error. Do not fan out to other nodes in the same workflow during the same health pass.

## Inspect A Node Or Branch

This section is for **targeted/diagnostic** inspection — answering a specific question about one node or branch, or root-causing an unexpected result — beyond the standard pass that `savant.py workflow inspect` already runs. For each requested node, branch, or data point:

1. Resolve the target unambiguously from the recipe node list. If the user says "the filter" and there are multiple filters, ask which one before inspecting.
2. Read configuration from the recipe JSON first:
   - display name and description
   - mode or type selector
   - filter clauses, formulas, join keys, aggregation keys, flatten/explode paths, service settings, or other type-specific config
   - modifiers that affect graph shape, such as "Include false path"
3. For data evidence, use API output first. For one checkpoint, read existing preview output (`--mode cached`), then compute that node only when the scope calls for it; for several, use `savant.py preview nodes "{flowUrl}" --workflow-json <recipe.json> --node-ids '["node_a","node_b"]' --output-path "$(savant.py session tmp-path "<task-name>" node-previews.json)"` (add `--mode interactive` or `--mode analyze` to compute). Answer from the returned per-node status, schema, row count, and sample rows, and compare upstream vs downstream when the question is about data loss, joins, filters, summaries, or branches. (For the *standard* whole-flow pass, prefer `savant.py workflow inspect` above.)
4. If API data inspection cannot provide output, stop and report what could not be inspected. Do not substitute browser Data Preview reads for API output evidence.
5. For unfamiliar config keys or node-type behavior, read `../components/{type}.md` before explaining the node.

Do not treat configuration alone as enough unless the user explicitly asks only about configuration. The value of live inspection is config plus data behavior.

## Interpret The Evidence

Answer in business terms, not UI terms. Describe what the step does to the data and cite the evidence that proves it.

Bad:

```text
Filter node in Builder mode with one clause: Entity, Contains, RRH.
```

Good:

```text
The filter keeps only files whose Entity path contains "RRH". After the filter, 1 of 1 rows remain, so for this dataset every file already matches.
```

Always cite the row count delta when it is relevant. "Went from N to M rows" is how you catch dropped joins, overly aggressive filters, and broken summaries.

Use row counts whenever they matter:

- filters: upstream row count -> true/false output row counts
- blends: left/right input counts -> matched/unmatched/output counts
- summaries/rollups: input grain -> grouped output grain and row count
- transforms: changed columns, fallback fields, review flags, and sample values
- destinations: final output shape and whether it is usable for the user

When debugging, work upstream from the first unexpected row count or missing value. Distinguish:

- **Zero rows:** table/grid exists and count is 0. This is real evidence that upstream logic produced no rows.
- **No data:** no preview grid exists. The node probably has not run for the selected source.

If API output and UI previews are missing and live execution is needed beyond Analyze, read `../substrate/run-modes.md` and follow its execution-mode confirmation rules.

## Full Walkthroughs

Do a node-by-node walkthrough only when the user explicitly asks for it. Keep it data-grounded:

- node display name
- business purpose
- important config
- input/output row count where available
- one short note on what changed or what risk to check next

A node walkthrough is for showing behavior at each step; don't pad it with the flow's business-level summary (that is the "Explain a flow" altitude — give it once, separately, if the user wants it).

## Boundaries

- Do not edit, save, add, delete, or rewire anything during inspection.
- Do not inspect a pre-selected node unless it is relevant to the user's current question.
- Do not invent data, row counts, field meanings, or business intent.
- Do not call the workflow fixed, clean, production-ready, or fully verified unless the applicable creator/editor/full-verification path also ran.
