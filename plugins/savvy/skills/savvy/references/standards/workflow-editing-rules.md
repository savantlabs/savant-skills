# Workflow Editing Rules

## Objective

Use this to mutate an existing Savant workflow safely: confirm the edit scope, build the smallest supported change inside it, save through the documented API path, and verify only the scope the edit can affect.

## Use When

- The user asks to change, fix, rename, move, recolor, rewire, resize, regroup, or reconfigure an existing workflow.
- Creator has imported a workflow and needs safe same-flow fixes before final delivery.
- Inspector has diagnosed an issue and the user wants the fix applied.

## Default Action

1. Orient on the workflow and target.
2. Capture rollback evidence.
3. Confirm the edit scope when it is not already implicit in the request.
4. Build the smallest supported change that serves that scope.
5. Save through the API recipe helper.
6. Re-fetch and verify the changed surface.

## Do Not

- Do not edit from the UI, DOM, Redux, or undocumented browser state.
- Do not batch changes from different scopes under one confirmation.
- Do not add steps or groups for readability alone during cleanup. If one documented component can do the work and the business meaning is unchanged, consolidate by default; keep a split only for a real business boundary, branch, reusable checkpoint, distinct operation type, or an explicit readability-first request.
- Do not re-import to fix an existing workflow. Full rebuilds apply to the same flow via `workflow edit --replace-from-build` (see "Topology boundary"); a replacement import is a last resort that needs explicit user confirmation.
- Do not prove the whole workflow is production-ready unless the user asked for that scope and `definition-of-done.md` passed.
- Do not create new connector/upload definitions as an Editor shortcut; repointing an existing source is supported, creating a new source/destination definition is not.

Keep mechanics out of this file. API recipe read/write mechanics live in `../scripts/savant.py app` and are the only supported live-edit substrate. Node-type support lives in `../components/{type}.md`.

## Responsibility boundary

Editor owns:

- turning a user request into a precise proposed diff on the existing live workflow
- disambiguating the target node, group, text object, outlet, or insertion point
- asking discovery questions before changing business meaning
- requiring explicit scope confirmation before edits that are not already implicit in the user's request
- verifying the affected node, affected downstream shape, and rendered layout required by the request
- stopping cleanly when the requested edit has no documented API recipe diff

Editor does not own:

- answering read-only behavior questions; use Inspector and `workflow-inspection-rules.md`
- full import plus live verification; use Creator
- creating a brand-new source or destination *definition* (a new connector/upload added as a new node). Note: **repointing an existing source to a different dataset is owned by Editor** — see "Dataset replacement".
- deleting flows; Savvy never deletes — ask the user to delete in the Savant app
- proving that an entire workflow is production-ready unless the user explicitly asked for that scope and the applicable `definition-of-done.md` section passed

## Edit scope confirmation

Every live edit happens inside one of five scopes:

- **Optimize** — consolidate redundant steps/groups, push cleanup earlier, reduce noise, improve maintainability without changing the business result. *Offered* when inspection reveals a clear opportunity.
- **Visual polish** — layout, spacing, lanes, labels, group sizes, connector routing. *Offered* when the diagram can read more clearly.
- **Documentation** — refresh workflow/group/step/output descriptions. *Offered* when descriptions are missing, stale, or generic.
- **Error** — fix failures, invalid settings, broken sources, runtime/preview errors, validation blockers. **Implicit** when the user asks to fix an error or a blocker is found.
- **Logic** — fix or update business logic (filters, joins, formulas, summaries, outputs, exception rules). **Implicit** when the user asks for a logic or wrong-result fix.

One edit scope equals one confirmation. For an offered scope, a simple "Confirm?" is enough; an implicit Error/Logic scope is already authorized by the request. Once a scope is confirmed or implicit, iterate automatically inside it — do not ask the user to approve every internal move. Ask again only when the next change would leave the scope, alter business meaning beyond the request, need an unproven topology mutation, change group membership/colors/text meaning/output shape, or pose a genuine user-preference tradeoff.

The policy loop inside a scope:

1. Run the deterministic health precheck when the edit is a fix/debug/status-adjacent request.
2. Orient on the workflow and target.
3. Capture a rollback snapshot before mutation.
4. Build the smallest supported change that serves the scope.
5. Commit through the documented API helper.
6. Verify the committed state and relevant behavior.
7. Report what changed and what was verified.

Multi-node edits run upstream first inside the confirmed scope.

## Deterministic health precheck

Use `../scripts/savant.py workflow health` as the shared precheck for both Inspector debugging and Editor fix planning:

```bash
python3 ../scripts/savant.py workflow health "{flowUrl}" \
  --workflow-json <recipe.json> --sources-json <sources.json> \
  --output-path "$(../scripts/savant.py session tmp-path "<task-name>" health.json)"
```

`--workflow-json` is required: the recipe comes from the MCP `fetch` tool on
`savant://workflow/{flowId}`, not from the API. `--sources-json` (the MCP `search` result for
`types: ["source"]`) enables the dataset-matching leg; omit it and matching is *skipped*, not
reported as zero matches. Run history and the optional preview still need `api_enabled`.


Run it before proposing an edit when the user asks to fix, repair, debug, troubleshoot, make working, resolve errors, address warnings, or continue from a diagnosis. The precheck is intentionally narrow: it reads recipe/status/version/run history, checks source dataset matches, and detects placeholder-like sources, and does not compute by default. Add `--mode interactive` (or `--mode analyze` for full-data evidence) only when the user asked for data behavior evidence and you want the single earliest-checkpoint preview.

If the precheck finds source binding problems, missing datasets, ambiguous datasets, placeholder source steps, or a first-checkpoint preview failure, address that first. Do not patch downstream filters, joins, summaries, or destinations until the upstream source issue is resolved or the user explicitly asks for a downstream configuration-only review.

For clearly narrow cosmetic edits, such as renaming a label, moving a group, recoloring a group, or changing descriptive text, this precheck is optional because the edit does not depend on data health.

## Supported edit classes

Routine edits are allowed when the corresponding API recipe fields are documented:

- documented config edits for supported node types
- display-name and outlet-label renames represented in recipe JSON
- node movement that preserves current parent or group membership
- group resize, move, color, and title-text edits represented in recipe JSON
- layout-only API recipe saves
- **replacing the dataset behind an existing source node** (repoint `config.id`/`connector`), with mandatory downstream schema reconciliation and verification — see "Dataset replacement" below and `../components/source.md`

Topology edits are routine only when the exact graph mutation is documented as an API recipe diff. For every topology edit, compute the intended graph diff before mutating and verify the resulting node and edge delta after the write.

## Config edits — regenerate via node_builders (the shared rule)

A node's config is changed the same deterministic way the builder *creates* it: regenerate the config with the matching `node_builders` core and merge it onto the live node. This is the single rule for config edits across every node type — there is no per-component "is editing supported" matrix. Edit coverage equals builder coverage: any node type the library can author, the editor can change.

The path:

1. **Read the live node** from the recipe — you have its full current config, including fields the library doesn't model.
2. **Regenerate the changed config** in the library's vocabulary: a typed `*_update(existing, ...)` helper where one exists (`edit_update`, `filter_update`, `blend_update`, `gen_ai_update`, `summarize_update`, `pivot_update`, `rollup_update`, `unpivot_update`, `json_update`, `deduplicate_update`, `vision_update`), or the generic `update_config(existing, <constructor>(...)["config"])` for any other type.
3. **Merge, don't replace.** `update_config` overlays the regenerated keys and preserves every config field the library doesn't emit, so a real setting we don't model is never silently dropped. Coupled fields (an edit node's `expression`/`pipeline`/`lookup`) always regenerate together.
4. **Propagate downstream in one pass — do NOT hand-edit downstream nodes.** If the change alters the node's output columns (rename/drop/retype, a blend key-set change, a summarize/pivot output change), use the propagating engine `workflow/recipe_edit.py`: `apply_node_edit(recipe, node_id, rename=(old,new) | drop=col)` applies the target edit AND fixes every downstream reference in one call, or `propagate_schema_change(recipe, node_id, delta)` when the target change was made via a `*_update`. It returns `(new_recipe, report)` and is pure (it does not save). The engine auto-fixes mechanical references and returns genuine gaps in `report["unresolved"]` — resolve those with the user (re-call with `resolutions`) rather than guessing.
5. **Validate, confirm, save, verify.** Run the normal snapshot → diff → confirm → save → re-fetch loop on the assembled recipe (target edit + downstream repairs), then verify the affected nodes' output. Changes with no output-column impact (a filter threshold, a sample size) skip the propagation step — the delta is empty.

If the save response and immediate re-fetch show the JSON change but node preview still returns the
old output (unchanged node hash, stale row count, or stale config behavior), treat that as a preview
cache issue, not proof the edit is wrong. API recipe save can bypass the UI's Apply path, so post-edit
verification must recompute the affected checkpoints fresh rather than reading a stale cached preview.
The edit verify path (`workflow edit --confirm` → `workflow inspect`) already forces a fresh recompute
internally; for a manual re-check use `preview nodes --mode interactive --from "<edited node>"`, which
recomputes from the edited node forward (evicting its stale cache). Re-export the recipe and inspect
the changed node id only after that fresh recompute still disagrees with the saved config.

Two things this rule does NOT cover, by design:

- **Outlet topology.** Toggling a filter's false path or a blend's unmatched-output split adds/removes branch outlets — that is a topology edit (add/remove node), not a config merge.
- **Verification cost.** For AI nodes (`gen_ai`, `vision`, `service` LLM-mode, `fuzzy_match`), regenerating config is free but *verifying the result* triggers a paid run — surface that and get a run-mode decision before verifying.

Each `../components/{type}.md` documents only its node-specific caveat (if any); the mechanism lives here.

## Dataset replacement

Repointing an existing source at a different dataset is a supported Editor task — the user keeps the same flow and just changes the data it runs on. The Editor can do this safely where a UI user often can't, because it can reconcile every downstream column reference in place rather than leaving them dangling.

Resolve the new dataset the same way the Planner does, gated on `api_enabled` (`../substrate/dataset-substrate.md`): pick an **existing** dataset (discovery returns its id) or **create a new** one from a file (creation returns its id). When `api_enabled` is false, the Editor cannot resolve a new id and must stop and ask the user to supply one or open the workspace.

**First check whether the source is standardized** (does a standardizing adapter immediately follow it — the schema contract defined in `../components/source.md`?). That decides how much work the replacement is:

- **Standardized source → re-map the adapter, downstream untouched.** Because every downstream node references the adapter's canonical names, the replacement is: repoint the source's `config.id`/`connector`, then update the adapter's `mappedFrom` (and types) to the new dataset's columns. Downstream is insulated by construction — no downstream reconciliation. Just verify the adapter output and re-verify the first downstream node. This is the easy, contained case the convention exists to produce.
- **Non-standardized source → retrofit the adapter first, then re-map.** Insert a standardizing adapter that **mimics the current source schema** (canonical names = the names downstream already references, `mappedFrom` = the current raw columns, types = the current types, `passthroughUnmapped: true` so nothing is dropped). Because it reproduces exactly what downstream already sees, the flow is unchanged by the retrofit — and the flow is now standardized. This **mid-edge insertion is proven for in-place save** (verified live: a node inserted between a source and its consumer kept the same flowId, and the downstream node stayed Ready with an unchanged output contract). Do it through the normal `workflow edit` loop — build the proposed recipe with the adapter spliced in (redirect the source's outlet through the adapter, point the consumer's inlet at the adapter), then propose → confirm → commit. After the one-time retrofit, future source edits on that flow are simple inline adapter re-maps. (This applies only to a schema-*preserving* insertion like a mimicking adapter; an inserted node that changes the downstream columns still needs the usual reconciliation.)

If the source is not standardized and you are not retrofitting the adapter, fall back to the full in-place reconciliation, which fixes downstream references directly. This is exactly what the propagating engine does — **use `propagate_schema_change(recipe, source_id, delta)` in `workflow/recipe_edit.py`; do not hand-walk references.** The steps it performs:

1. Capture the **old source schema** (current live `{id,name,dataType}`) and fetch the **new dataset's schema** before saving; express the difference as the `delta` (renames / drops / retypes).
2. The engine enumerates every downstream reference to the source's columns (`field`/`replace`, `hiddenFields`, `orderedFields`, filter clauses, summarize/blend keys, sort columns, adapter `mappedFrom`, …) and **auto-reconciles the mechanical mismatches** (remaps renamed columns by name in `hiddenFields`/`orderedFields`/expressions, and re-derives the genuine id references like `fieldId` and join keys), returning them in `report["auto_fixed"]`.
3. It **surfaces genuine gaps** in `report["unresolved"]` — a downstream step referencing a column the new dataset lacks. Resolve those with the user (re-call with `resolutions`) rather than saving a flow with dangling references.
4. Propose the full diff (the source repoint + every downstream repair + any unresolved gaps), confirm, save, re-fetch, and **verify downstream data behavior** (this is a logic-changing edit, so node-output verification is required, not optional).

If the downstream cannot be reconciled into a runnable flow (pervasive schema change, mid-graph orphaning), rebuild the flow and apply it to the same flow via the rebuild-in-place path (see "Topology boundary") rather than forcing it inline.

## Topology boundary

Import is for creating a new flow; it always mints a new flowId. An edit to an existing flow — including a structural one — goes through `PUT /api/recipes` (recipe save) on that same flowId. Do not re-import to apply a fix.

**Proven in-place topology edits (do these via recipe save, not rebuild/re-import):**

- adding a node of a documented component type, wired onto an existing node's outlet (linear extension or an added branch)
- removing a *leaf* node and clearing the dangling target from its parent's outlet
- **inserting a node mid-edge** between two connected nodes (redirect the upstream node's outlet through the new node, point the downstream node's inlet at it) **when the inserted node preserves the downstream schema** — e.g. retrofitting a `passthroughUnmapped` standardizing adapter. Verified live: the inserted node kept the same flowId and the downstream node stayed Ready with an unchanged output contract. If the inserted node changes the downstream columns, pair it with the usual reconciliation.
- **removing or replacing one single-input/single-output mid-graph node** with an explicit rehydration plan: redirect the sole upstream outlet to the sole downstream node, fix the downstream inlet, clean group/text membership, and reconcile the downstream schema with documented config edits (for example collapsing a create/rename Transform and a hide/reorder Transform into one). When the collapse leaves a group without a distinct business phase, re-evaluate it under confirmed Optimize scope and drop or merge it (surfacing the change for live edits).

These were verified live: `PUT /api/recipes` saves that added a node, removed a leaf node, inserted a node mid-edge, and collapsed a single-input/single-output mid-graph node each preserved the flowId, and the re-fetched `recipe_model_diff` matched the requested `added`/`removed`/`changed` set. Drive them through the standard loop (MCP `fetch` → dry-run `recipe_model_diff` → confirm → save → MCP `fetch` → `workflow verify --operation edit --before-json`) and assert the persisted diff equals the requested diff (`assert_expected_model_diff`). The re-fetch is an MCP `fetch`, not a toolchain call: `workflow edit --confirm` reports `saved-unverified` and the verify step is what proves persistence. The added node's config must be documented and verifiable like any other component edit.

**Beyond the proven set — rebuild in place:**

- arbitrary rewiring between existing nodes
- non-linear topology rewrites
- replacing or deleting input connections
- multi-input/multi-output mid-graph node/edge removal that orphans the downstream
- moving a node into a group
- creating a brand-new source or destination definition (adding a new connector/upload as a new node) — distinct from repointing an *existing* source's dataset, which is supported (see "Dataset replacement")
- changing schema-bound connections *between nodes* without a rehydration plan (this is about node-to-node edges; replacing the *dataset* a source points to has its own supported path with reconciliation)

For reshapes beyond the proven set, rebuild the flow with the builder and apply it to the **same flow** via `workflow edit --replace-from-build <rebuilt.json> --current-recipe <fetched.json> --confirm`. This merges the creation-shaped rebuild onto the live identity envelope — same flowId, folder, namespace, and live name (a rebuild never renames) — runs the create-preflight content blockers (placeholder/foreign dataset ids, missing AI provider), and goes through the normal propose → confirm → save → verify loop. Verified live 2026-06-10: a 41-node `--replace-from-build` persisted on the same flowId with every destination Ready. A replacement import is a last resort, used only when the in-place save itself fails and the user confirms a new flow naming the superseded one. Do not probe DOM, Redux, or UI write mechanisms in a production workflow.

## Proposal shape

A scope proposal should be short and concrete:

- target: display name plus human disambiguator when needed
- scope: which of Optimize / Visual polish / Documentation / Error / Logic, or a narrow named edit
- expected impact: what improves and what will not change (business meaning, output shape)
- blast radius: include only when the edit changes topology, outlets, grouping, output grain, business meaning, or downstream schema assumptions
- confirmation: a simple "Confirm?" is enough for an offered scope (an implicit Error/Logic scope is already authorized)

Use business-user language and display names. Product terms are fine only when they help the user act in the app; internal ids, DOM details, selectors, Redux, JavaScript, and widget names belong in internal reasoning, not in the chat proposal.

## Verification

Use API re-fetch and targeted output/layout checks for the edit class. At the policy level:

- config edits verify committed form values first; preview row counts are advisory
- any step whose configuration changed verifies that its description was refreshed or still accurately reads out the new settings (per `node-documentation-rules.md`)
- outlet, label, text, and layout edits verify the changed canvas object and persistence path documented by the recipe
- topology edits verify graph diff first, then selection, persistence, and layout metrics when relevant
- layout-affecting edits apply `canvas-layout-rules.md` (deterministic layout metrics; there is no rendered-canvas inspection)
- meaningful logic changes verify affected downstream behavior, but full workflow validation belongs to Creator or an explicitly requested full-verification scope

If an expected verification cannot be run, report that directly in the final response.

## Rollback

Every write needs a rollback story before it happens. For API recipe edits, capture the pre-edit recipe JSON and know the exact reverse diff before saving. For substantial multi-node work, offer a downloader backup before editing. Product undo is only for immediate accidental manual canvas mutations; it is not the rollback plan for direct recipe saves, reloads, or schema-bound topology changes.
