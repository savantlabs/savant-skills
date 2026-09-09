# Savant Workflow Applier (applier mode)

> **When this mode applies:** the user has a Savant workflow JSON (often one **author mode** just produced) and wants to create/upload/import/push/deploy/"make real" the flow in Savant, OR gives a Savant flow URL (.../en/app/flow/...) and wants to edit/update/modify/change/fix/rename/move/resize/recolor/reorganize that existing flow. The decisive question is whether the flow already exists: an existing flow (URL/flowId) is **edited in place** via recipe save; a net-new flow is **created** via import. Writes only inside an explicit or implicit user-confirmed edit scope, and routes JSON-generation defects to **author mode**.

## Goal

Applier takes a workflow that exists *as intent* — either a local workflow JSON, or a change the user wants to an existing live flow — and makes it real and verified in the Savant app. It has exactly two modes:

- **Create** — the flow does **not** exist yet. Import a complete workflow JSON into an explicit folder (`POST /api/recipes/import`), which mints a **new** flowId, then verify it renders, runs on its bound data, and is well organized.
- **Edit** — the flow **already** exists (you have a URL or flowId). Make a narrow, user-confirmed change in place via recipe save (`PUT /api/recipes`) on the **same flowId**, with a rollback snapshot and a `workflow verify` persistence check.

Applier always works against the live API and confirms the edit scope before writing. It routes JSON-generation defects to **author mode** and read-only behavior questions to **inspect mode**. It reuses the shared verification harness (`savant.py workflow verify`, then `savant.py workflow inspect`) after every create and every edit.

Write user-facing replies with the business-user response rules loaded at session start.

## Which mode am I in? (decide this first — read before anything else)

**The single decision that governs this whole skill: does the target flow already exist?**

- **You have a flow URL or flowId → you are EDITING.** Editing changes that same flow in place with `PUT /api/recipes` (recipe save). This includes **structural** changes — adding a node, removing a leaf node, inserting a schema-preserving node mid-edge are all proven for in-place recipe save (see Edit hard rule 5). Do **not** import to apply a change to a flow that already exists.
- **You have a workflow JSON and no existing target flow → you are CREATING.** Import mints a brand-new flowId. This is the *only* reason to import.

`POST /api/recipes/import` **always mints a new flowId.** Re-importing to "apply a fix" to an existing flow is the single biggest cause of duplicate-flow clutter, and it is the wrong tool whenever the target already exists. "I need to add/remove a node, therefore I must re-import" is **false** — structural edits go through recipe save. Reach for import only to create a genuinely new flow, or for the narrow rebuild path in Edit hard rule 5 where a mutation is not yet proven for save.

The `workflow create` helper blocks same-session duplicate imports by default; only pass `--allow-duplicate-import` after the user explicitly confirms they want another live copy. This guard backstops the decision above — but make the decision consciously, do not rely on the guard.

## Authentication

This skill calls the Savant web-app API directly, but it never mints its own credentials. The chat client holds the MCP connection and is the only thing that speaks MCP; the `savant.py` shell is a pure API executor that reads its credentials from the environment. The handoff:

1. **Resolve the workspace.** For an **edit**, **prefer the namespace already in the URL** — a flow URL with `?rns=<namespace>` names the owning workspace, so use it directly; fall back to the **`locate`** MCP tool only when the URL has no `rns` or you were handed a bare id. For a **create**, resolve the destination folder's namespace with `locate`. `locate` takes the entity's `savant://{type}/{id}` URI (the same form `search` returns) — **not** a Canvas URL or bare id; from a flow URL, extract the id after `/flow/` and pass `savant://workflow/{flowId}`. If the active session is not already in that namespace, call **`switch-workspace`** (passing the namespace `locate` returns) — or **`switch-folder`** — so the minted credentials are scoped to the workspace that owns the flow/folder, then read with `fetch`. (If switching to the URL's `rns` doesn't grant access, fall back to `locate` for the true owner.)
2. **Mint credentials.** Call the **`get-api-credentials`** MCP tool. It returns `apiBaseUrl`, `token`, and `tabId`.
3. **Supply the credentials to the toolchain — for this session only.** `savant.py` reads `SAVANT_API_TOKEN`, `SAVANT_API_TAB`, and `SAVANT_API_BASE_URL` (optionally `SAVANT_API_NAMESPACE`). Pass them inline on each call as **environment variables, never CLI flags** (an arg is visible to other local users via `ps`):

   ```sh
   SAVANT_API_TOKEN=<token> SAVANT_API_TAB=<tabId> SAVANT_API_BASE_URL=<apiBaseUrl> python3 scripts/savant.py …
   ```

   (`apiBaseUrl` may end in `/api`; the shell normalizes it.) **Do not set, invent, or export `SAVANT_AI_SESSION_ID`** — the session id is derived from the runtime automatically. *Optional file form (your discretion):* write the **`get-api-credentials` response** to the path from `savant.py session tmp-path savant-creds.json` and set `SAVANT_CREDS_FILE` to it — the response object is the file format. That path is user-private, OS-reaped temp outside the repo; never write credentials elsewhere (repo, `$HOME`, a `.env`) or keep them past the session.
4. **On a 401**, the token has expired — call `get-api-credentials` again, re-supply the credentials, then retry. Do not re-parse or retry by hand beyond that.
5. **If re-minting doesn't help** — the MCP tools aren't callable, `get-api-credentials` returns not-connected, or a 401 persists after a fresh mint — the `savvy-*` connector is disconnected. Do **not** build an `oauth2/authorize` URL or ask the user to paste back a `localhost/callback` URL; that callback is dead once the connector drops. Tell them plainly to reconnect their Savant connector, then stop and wait.

**Never echo the token (or the creds file's contents) into a user-facing reply.**

There is no browser or rendered-canvas verification. The diagram is laid out in the workflow JSON, so layout quality is judged from `savant.py validate workflow` and the deterministic layout metrics (`canvas-layout-rules.md`) — never from a rendered view, and never claimed as a rendered pass.

## Before You Start

`savant.py ...` is shorthand for the bundled toolchain; the parent `SKILL.md` Toolchain section explains how to locate and run it.

With credentials supplied (per Authentication above), confirm API access: resolve the snapshot path with `savant.py session tmp-path savant-capabilities.json`, run `savant.py capabilities --output-path <resolved-capability-path>`, and proceed only when `api_enabled: true`. If it is false, stop — Applier cannot create or edit without live API access.

The deterministic helpers are the normal execution surface: `savant.py workflow create` owns import + create verification; `savant.py workflow edit` owns diff and save; `savant.py workflow verify` owns the post-write checks for both modes (folder placement, node persistence, the before/after diff); `savant.py workflow inspect` is the shared data-evidence harness. Recipes come from MCP `fetch`, not from a CLI route.

---

# Mode: Create

## Create boundaries

- Applier-create only creates **new** flows. Changing an existing flow is Edit mode.
- Create does **not** resolve datasets. Every source node must already carry a real dataset id (Author bound them).
- Create does **not** repair malformed workflow JSON. Route JSON-generation defects to **author mode**.

## Create needs

- Live API access and an active session (the precheck gate verifies `api_enabled` for the authenticated session).
- A Builder-to-Creator handoff, or a validated workflow JSON with a non-empty `name`, a `nodes` array, and real dataset ids on source nodes.
- Workflow name, destination workspace, and destination folder.
- **The destination workspace is user-named, never chosen.** The workspace comes from the user's own words (or a prior approved plan that names it) and is recorded in the handoff (`context_confirmation.workspace` + its `namespace` from MCP `search`/`whereami`). There is no default workspace: if the user has not named one, stop and ask. If the user later names a folder in a *different* workspace than the one confirmed earlier, that is a retarget — re-confirm the context and re-verify dataset bindings there before import.
- **The destination folder is a preference, with the Home folder as the announced default.** Prompt the user to name a folder, with the default in the question: *"Which folder in `<workspace>` should this go in? If you have no preference, I'll create it in the Home folder."* A user-named folder resolves to its id; a non-answer ("no preference", a dismissed or skipped question) resolves to the **Home folder of the confirmed workspace** (`--folder-id home`) — announce it plainly ("Creating in `<workspace>` → Home folder") and proceed. A workspace with no folders is **not** a blocker: the Home folder is always a valid destination. What a non-answer never earns: another existing folder of convenience, or any workspace the user did not name. Record the user's verbatim words (or their non-answer) in `context_confirmation.user_stated_destination`.
- **Folder-bound creation:** the created workflow must read back in the exact target folder — the same `folder.id` the user specified or confirmed, or no folder id when the target is the Home folder (namespace root, `--folder-id home`). If read-back reports a *different* folder than the target, treat create as failed; do not report success or silently use another folder.

Before creating, write/fill the Creator-ready section of `builder_to_creator.handoff.json` and run:

```bash
savant.py validate stage --role creator --gate precheck <builder_to_creator.handoff.json>
```

The capability probe runs against the authenticated session by default; the session must already be switched to the target folder's workspace.

Stop on any failure and follow the gate's `nextActions`. The later `workflow create` command also rechecks the target-folder API/session and folder id before import.

## Create procedure

1. **Prepare to create.** Run the Creator precheck stage gate on the Builder-to-Creator handoff to confirm API access, validated JSON, source bindings, requested scope, destination workspace/folder, and user approval to create. **When create is reached as the continuation of an approved Author plan, that plan approval (which covered "build this and create it in your workspace") *is* the create authorization** — don't stop to re-ask "do you want to create this?" as a fresh gate. Wire the reused approval into the handoff so the precheck passes on the first try: set `creation_confirmation.user_confirmed: true` and put the plan-approval quote in `creation_confirmation.user_confirmation_evidence` (it must cite the explicit go-live approval, not the user's broad "build me a flow" request). The **destination folder/workspace still needs its own `context_confirmation`** — that is a separate confirmation the plan approval does *not* cover, so resolve and confirm the folder before import. Only solicit a fresh creation confirmation when no plan approval exists (e.g. the user handed you a bare JSON file with no plan behind it). For the folder part of that context, remember the split above: the workspace needs a real user answer; the folder question carries its own Home-folder default, so a "no preference" there is resolved (announce the Home folder), not a blocker.
2. **Create the workflow.** Import the JSON into the confirmed folder.
3. **Confirm creation.** Capture the created workflow URL and confirm the live recipe matches the source JSON.
4. **Verify business logic.** Use the create/inspect results and preview data to confirm the workflow has no node errors and produces the expected business outputs.
5. **Check layout quality.** Use the deterministic layout metrics (auto-layout runs on the built flow); there is no rendered-canvas inspection.
6. **Report completion.** Validate completion evidence before saying the workflow is done, ready, working, or verified.

**Do not use repeated imports as a debugging loop.** Treat the first confirmed import as the live draft for this task. After one confirmed live create for a workflow name/folder, any defect found during inspection belongs to the already-created workflow: diagnose it, route safe same-flow fixes to Edit mode, or ask the user before creating a replacement copy. `workflow create` blocks same-session duplicate imports by default; only pass `--allow-duplicate-import` after the user explicitly confirms they want another live copy.

## Create and confirm

Use `workflow create` as the standard create path. The target folder is given as a **folder id** (`--folder-id`), or `--folder-id home` for the Home folder (namespace root); the workflow is created in the authenticated session's namespace — the same namespace `search`/`fetch` operate in — so find the folder id via MCP `search`/`fetch` on the `folder` entity (and make sure the session is already switched to that folder's workspace). `--confirmed-namespace` is required: pass the namespace of the **user-confirmed** destination workspace (the handoff's `context_confirmation.namespace`) — import hard-blocks if the session is in any other namespace, so a session that drifted (or was switched) away from the workspace the user named cannot create there. Always run it once without `--confirm-import` first — that pass validates the JSON, checks `api_enabled`, verifies the confirmed namespace, confirms bound dataset ids resolve in the target workspace, and surfaces blockers (missing AI providers, placeholder/unresolved dataset ids, same-session duplicates). The folder id itself is verified *after* import, by `workflow verify --operation create --expect-folder-id`, which hard-fails unless the created workflow reports the requested folder. Then rerun with `--confirm-import`:

- **Continuation of an approved Author plan:** if the dry-run pass is clean, proceed straight to `--confirm-import` — the plan approval already authorized creation, so don't pause for a fresh "shall I create it?" prompt. Pause and surface to the user **only** if the dry-run reports a blocker that needs a decision. A missing destination *folder* answer is not such a blocker — it resolves to the Home folder of the confirmed workspace, announced. A missing or retargeted destination *workspace* is: only an explicit user answer naming the workspace resolves it, never a choice of your own.
- **No prior plan approval** (bare JSON handed in, or destination still unconfirmed): present the dry-run summary and rerun with `--confirm-import` only after the user approves.

```bash
CREATE_REPORT="$(savant.py session tmp-path "<task-name>" create.json)"

# Preflight. --sources-json / --providers-json are the MCP `search` results for
# types: ["source"] and ["ai_provider"]; they catch bound ids that do not resolve in this
# workspace, which import drops SILENTLY. Omitting them skips those checks.
savant.py workflow create --folder-id <folderId> --confirmed-namespace <namespace> \
  --import-json <workflow.json> \
  --sources-json <sources.json> --providers-json <providers.json> \
  --expected-outputs-json <builder_to_creator.handoff.json> --output-path "$CREATE_REPORT"

savant.py workflow create --folder-id <folderId> --confirmed-namespace <namespace> \
  --import-json <workflow.json> \
  --sources-json <sources.json> --providers-json <providers.json> \
  --confirm-import --expected-outputs-json <builder_to_creator.handoff.json> \
  --checkpoint "<stage>" --output-path "$CREATE_REPORT"
```

**The create command no longer verifies itself.** It imports and returns `flowId`/`flowUrl` with
`status: "created-unverified"`, then prints the two commands to run next. Verification needs the
created recipe read back, and the toolchain does not read recipes — you do, with MCP `fetch`:

```bash
AFTER="$(savant.py session tmp-path "<task-name>" after-create.json)"
# Write the MCP `fetch` result for savant://workflow/{flowId} to "$AFTER", then:

savant.py workflow verify --operation create --workflow-json "$AFTER" \
  --expect-flow-id <flowId> --expect-folder-id <folderId> \
  --source-json <workflow.json> --block-documentation-gaps
```

`workflow verify` runs the folder-placement check and the node-persistence check that used to run
inside create, plus file-based validation. **It exits non-zero on failure. A create is not
reportable as created until it exits 0** — an import can return a flow that landed in the wrong
folder, or one node short because an AI provider did not resolve, and this is what catches both.

`--expected-outputs-json` can point at the Builder-to-Creator handoff; the shared inspector reads `builder_preflight.output_destination_plan.outputs` and verifies each final output separately. The older `--expect-columns` flag is only for simple single-output checks.

The command validates the JSON, checks `api_enabled` for the session, blocks unless the session namespace equals the user-confirmed `--confirmed-namespace`, resolves the folder id and confirms it lives in the session namespace, reports same-session existing creates for the same workflow name/folder during preflight, blocks missing AI providers or placeholder source dataset ids, blocks same-session duplicate imports unless explicitly overridden, imports after confirmation, and returns the created `flowUrl`. Capture that URL immediately; it is required delivery evidence. Whether the workflow persisted and landed in the requested folder is answered by `workflow verify` — a different folder is a hard failure there, even if the workflow exists and validates.

There is no rendered visual verification: a confirmed create is judged on persistence, structure, data evidence, and the deterministic layout metrics. Do not re-import to "complete" a layout check, and never claim a rendered layout pass that did not run.

## Verify business logic (create)

For full verified delivery, confirm the workflow works against the bound data: import succeeded, the shared inspector's runtime-smoke passed before any preview/schema reads, no node errors remain, expected columns exist, row counts are sane, preview data matches the business requirement, and important totals/exceptions/outputs make sense.

For extra named checkpoints after creation:

```bash
INSPECT_REPORT="$(savant.py session tmp-path "<task-name>" inspect.json)"

savant.py workflow inspect "{flowUrl}" --recipe-json "$AFTER" --imported-json <workflow.json> \
  --expected-outputs-json <builder_to_creator.handoff.json> --checkpoint "<stage>" \
  --output-path "$INSPECT_REPORT"
```

Read the inspection report in order. If `runtimeSmoke.status` is `fail`, stop on the failed node/error and route the defect; do not fetch or reason from downstream previews until that error is fixed. Draft import only requires creation and persistence; do not claim runtime correctness for draft imports.

The create-verify pass computes at **Interactive** (1k) — it is the first sanity check, and it is resilient to a just-created source whose full-data cache has not warmed yet. A node reported `Skipped`/not-ready with no `Failed` root **immediately after create** is usually that cold-source-cache warm-up, not a runtime defect: do not step up to Analyze in the same breath as the create — give the source time and re-run Interactive. See `../../references/substrate/run-modes.md`.

## Check layout quality (create)

Auto-layout positions and lanes the created flow deterministically; judge layout from the layout metrics against `../../references/standards/canvas-layout-rules.md` (group framing, label clarity, node placement, connector corridors). There is no rendered-canvas inspection, so judge layout from those metrics — never claim a rendered pass. If layout needs a safe same-flow fix, route it to Edit mode and re-check.

## Validate and report (create)

Before saying "done", "ready", "verified", or "working", write `completion_evidence.json` and validate it:

```bash
savant.py validate stage --role creator --gate done <completion_evidence.json> \
  --claim done
```

For draft import, done means the flow was created and persisted. For full verified delivery, done also requires the standard inspection to pass; there is no rendered visual verification, so report layout from the deterministic metrics and never claim a rendered pass. If the validator fails for a check outside the requested scope, make a qualified claim and state what was verified and what was not run.

Report back with: the business process name and clickable Savant workflow URL; a short business summary of what the workflow does; what was verified, including execution surface and key row/count/result checks when run; any checks not run or capability-blocked.

---

# Mode: Edit

## Edit boundaries

- **Edits in place, never re-imports.** The flow already exists, so changes go through recipe save (`PUT /api/recipes`) on the **same flowId**. Re-import mints a *new* flow and is Create mode.
- **Scoped and proven only.** Supports documented recipe-level edits (display labels, node/group positions, group/text layout, documented component config, the proven structural edits — adding a node, removing a leaf node, mid-edge schema-preserving insertion, and removing/replacing one single-input/single-output mid-graph node with a rehydration plan — and **replacing the dataset behind an existing source**, with downstream reconciliation). For mutations beyond the proven set, applies a full builder rebuild to the **same flow** via `workflow edit --replace-from-build` (rebuild-in-place); a fresh import is a last resort, never the default.

## Edit procedure

1. **Prepare the edit.** Confirm the flow URL, API access, supported scope, readiness questions, current recipe, exact target, and rollback snapshot.
2. **Confirm the edit scope.** Offer **Optimize**, **Visual polish**, or **Documentation** when those are optional improvements; treat **Error** and **Logic** as implicit when the user asked for that fix. Once a scope is confirmed or implicit, iterate inside it automatically — do not re-confirm every micro-step (see Hard rule 1 and `../../references/standards/workflow-editing-rules.md` §Edit scope confirmation).
3. **Save and verify.** Save in place through the API, re-fetch the recipe, confirm the change persisted, verify affected data or layout, and offer rollback if verification fails.

Rollback is the safety valve around every step: if a save fails or the user wants to revert, restore the snapshot (itself a confirmed save).

## Edit references

**Read `../../references/standards/workflow-editing-rules.md` before any write.** This is the policy layer for edit boundaries, proposal shape, confirmation, topology support modes, verification, and rollback.

**Read `../../references/standards/canvas-layout-rules.md` before layout-affecting edits** — visual organization rules for moving, grouping, wiring, and verifying canvas layout.

On-demand only:
- `../../references/standards/definition-of-done.md` — only when the final claim is broader than the narrow edit, or an unusual scope needs interpretation.
- `../../references/standards/alteryx-migration-cleanup.md` — only when a workflow appears migrated from Alteryx or the user asks for slowness, hanging, optimization, maintainability, or standards cleanup.
- `../../references/standards/data-prep-normalization.md` — only when deciding whether a data-quality fix belongs upstream.
- `../../references/substrate/run-modes.md` — only before Test/Run, or when choosing non-default execution evidence beyond affected-scope Analyze.

For component config edits, read the relevant `../../references/components/{type}.md` and `../../references/registry/components/{type}.json`. Only mutate config fields whose JSON behavior is documented and can be verified after save.

**Editor readiness lifecycle:** before planning or proposing an edit, write `editor_readiness_checkpoint.json` to the path from `savant.py session tmp-path <task-name> editor_readiness_checkpoint.json` and run `savant.py validate stage --role editor --gate precheck <checkpoint>`. Use `task_type: "editor_readiness_checkpoint"`. First run `stage: "questions_needed"` to record `open_questions` and `ready_for_questions: true`. After the user answers, run `stage: "ready"` with required answers in `answered_questions`, optional unresolved items in `deferred_questions`, and `ready_for_stage: true`. Required editor-readiness questions — missing flow URL, ambiguous target, unsupported inline edit scope, unresolved business meaning, missing confirmation path, or unavailable API access — block the editor until resolved.

**Run the deterministic workflow health precheck after readiness for fix/debug edits.** If the user asks to fix, repair, debug, troubleshoot, make working, resolve errors, address warnings, or edit after a diagnosis, run `savant.py workflow health` after the readiness gate passes and before proposing any diff. Add `--mode interactive` (or `--mode analyze` for full-data evidence) only when the user asked for data behavior evidence and you want the single earliest-checkpoint preview. Do not run it for visual-only edits unless the user also asks about data behavior. If it finds source issues, resolve or route those first.

## Hard rules — the safety contract

These rules are non-negotiable. If one of them would be violated, stop and surface the issue rather than proceeding. Cross-cutting user-facing response rules loaded at session start are additive.

1. **Never save without explicit or implicit scope confirmation.** A scope is *explicit* when the user accepts an offered Optimize/Visual polish/Documentation improvement, and *implicit* when they asked for an Error or Logic fix. Once the scope is set, iterate automatically inside it — apply the supported changes that serve that scope without asking the user to approve each individual move. Still stop and ask before a change that leaves the confirmed scope, alters business meaning beyond the request, needs an unproven topology mutation, changes group membership/colors/text meaning/output shape, or is a genuine user-preference tradeoff. A clear affirmative ("yes", "go ahead", "apply it", "confirmed") sets an offered scope; silence, ambiguity, "maybe", or a new unrelated request means stop.
2. **Never save without a pre-edit rollback snapshot captured first.** The full recipe snapshot is the rollback mechanism. If snapshot capture fails, stop.
3. **Never claim success from HTTP 200 alone.** After API save, re-fetch the recipe and confirm the expected diff persisted.
4. **Never operate on an undocumented recipe field.** If a config field does not map to documented JSON behavior in the registry/component notes, stop.
5. **Never perform a topology edit without a documented API recipe mutation and a precise target graph.** Adding, deleting, reparenting, or rewiring nodes is allowed only when the operation has been proven end-to-end through the API helper and the requested upstream/downstream shape is unambiguous. Otherwise use rebuild-in-place (below) or stop and surface the limitation.
   - **Proven in-place topology edits (use recipe save, never re-import):** (a) **adding a node** of a documented component type, wired onto an existing node's outlet (linear extension or an added branch); (b) **removing a leaf node** and cleaning the dangling target off its parent's outlet; (c) **inserting a node mid-edge** between two connected nodes **when it preserves the downstream schema**; and (d) **removing or replacing one single-input/single-output mid-graph node** with an explicit rehydration plan — redirect the sole upstream outlet to the sole downstream node, fix the downstream inlet, clean group/text membership, and reconcile downstream schema with documented config edits (e.g. collapsing a create/rename Transform and a hide/reorder Transform into one). All four were verified live: the `PUT /api/recipes` save kept the same flowId and the re-fetched `recipe_model_diff` matched the requested `added`/`removed`/`changed` set. Drive these through the normal loop (fetch → dry-run `recipe_model_diff` → confirm → save → re-fetch → `workflow verify`) and assert the persisted diff with `assert_expected_model_diff`. When collapsing leaves a group purposeless, re-evaluate it under confirmed Optimize scope.
   - **Beyond the proven set — rebuild in place, do not re-import:** for non-linear/arbitrary rewiring, multi-input/multi-output mid-graph removal, between-node connection replacement, or any larger reshape, rebuild the flow with **author mode** and apply it to the **same flow** via `savant.py workflow edit --replace-from-build <rebuilt.json> --confirm`. This merges the creation-shaped rebuild onto the live identity envelope (same flowId, folder, namespace, name — a rebuild never renames), runs the create-preflight content blockers, and goes through the normal confirm→save→verify loop (verified live 2026-06-10: a 41-node replace persisted on the same flowId). A fresh import is a last resort, used only if the in-place save itself fails and the user confirms a replacement. (Replacing the *dataset* behind an existing source is a separate supported task — see the Supported table and hard rule 10.)
6. **Prefer API recipe reads/writes.** For canvas layout, mutate recipe positions/config through the API helper whenever the operation maps to node position/config fields. There is no rendered-canvas verification; rely on the recipe diff and the deterministic layout metrics.
7. **Clarify business meaning before changing it.** If an edit changes output grain, amount basis, source-of-truth precedence, fallback behavior, join preservation, filter semantics, summarization grain, review flags, or final destination columns, ask one narrow question before proposing the diff.
8. **Refresh the Savvy tracking tag to the editing version.** The tracking tag records the Savvy version that last created OR edited the flow, e.g. `Savvy v0.0.1` (the canonical value is `capabilities.tracking_tag`). On any saved edit, update the top-level `tags`: remove any existing Savvy-family tag and add the current editing version, keeping exactly one Savvy tag. Include this in the dry-run diff like any other change, and pass the current tag to `savant.py validate workflow --required-tag` — it flags a leftover stale-version tag or a tag missing its version.
9. **Never create in a workspace the user did not name — and never resolve a folder non-answer to anything but the Home folder.** The destination workspace comes from the user's explicit words (or a prior approved plan that names it); recorded in `context_confirmation.workspace`/`.namespace` and enforced at import by `workflow create --confirmed-namespace`. Never switch the session to another workspace on your own — a retarget requires the user naming the new workspace. The destination folder is softer: prompt for one, and on a non-answer ("no preference", dismissed, skipped) default to the **Home folder of the confirmed workspace** (`--folder-id home`), announced — never another existing folder or workspace of convenience. Record the user's words (or their non-answer) in `context_confirmation.user_stated_destination`; the creator precheck rejects a non-answer paired with a non-Home folder, and any folder/workspace mismatch.
10. **Never replace a dataset as a bare `config.id` swap.** Repointing an existing source at a different dataset is supported (`api_enabled` only — resolve the new id from an existing dataset or a newly created one via `../../references/substrate/dataset-substrate.md`), but only as a reconcile-and-verify edit: capture old and new schemas, audit every downstream column reference, auto-reconcile the mechanical id mismatches, and **surface any genuine column gap for a user decision before saving** — do not save a flow with dangling references. After save, verify downstream data behavior. If the downstream can't be reconciled into a runnable flow, rebuild in place (Hard rule 5). See the "Dataset replacement" section of `../../references/standards/workflow-editing-rules.md` and `../../references/components/source.md`.
11. **Declare the edit class and keep documentation current.** Pass `--edit-class fix` for a behavior-preserving bug fix (documentation staleness surfaces as informational notes) or `--edit-class logic` (the default) for a meaning-changing edit (stale-documentation warnings must be resolved in the same edit or confirmed still-accurate). Misdeclaring `fix` for a meaning-changing edit is an auditable misdeclaration, not a shortcut; operational swaps such as an AI-provider change never flag. Any step whose configuration changed gets a refreshed description per `../../references/standards/node-documentation-rules.md`. When this flow was created earlier in the same session, the edit inherits create-level documentation strictness automatically. `--require-documentation` (the Documentation scope, or that auto-continuation) promotes node-description gaps and stale-doc warnings to errors; `--accept-stale-docs` is the deliberate override.

## Supported edits

Routine editor work should be represented as a dry-run recipe diff before saving:

| User request | Supported behavior |
|---|---|
| Rename node or outlet | Update the display `name` on the recipe node/outlet when the label is represented in JSON. |
| Move node or outlet | Update `position`; include branch outlet pseudo-nodes when the visual branch should move together. |
| Move/resize/recolor group | Update group `position` and `config.width` / `config.height` / `config.color`; verify via the deterministic layout metrics against `canvas-layout-rules.md` (there is no rendered-canvas inspection). |
| Rename or format text | Update text-node `config.inputText`, `config.text`, size, position, and uniform formatting; verify the persisted recipe diff (there is no rendered-canvas inspection). |
| Rename group title | Resolve the text node inside the group and edit that text node; the group's own `name` is not user-facing. |
| Edit workflow name / description / tags | Flow metadata is NOT written by the recipe save (`PUT /api/recipes` only updates nodes/parameters). Update it with `savant.py app --save-metadata-from <file> --confirm-live-save` (which `PUT`s the full flow object to `/api/recipes/{flowId}/metadata`). The `description` is **Markdown** — never HTML. Apply the tracking-tag refresh here too (rule 8). |
| Documented component config change | Mutate the component config only when the JSON behavior is documented in the registry/component notes and can be verified by re-fetch plus node-output inspection when data behavior changes. |
| Add a node (linear extension or branch) | Append a documented component-type node and wire it onto an existing node's outlet via recipe save. Confirm the re-fetched `recipe_model_diff` (from `workflow verify --before-json`) shows the expected `added` node + the parent's `outlets` change. Do NOT re-import for this. |
| Remove a leaf node | Drop the node and remove the dangling target from its parent's outlet via recipe save; confirm `recipe_model_diff` shows the expected `removed` node. |
| Remove/replace a single-in/single-out mid-graph node | Apply Hard rule 5d with a rehydration plan: redirect the sole upstream outlet to the sole downstream node, fix the inlet, clean group/text membership, reconcile downstream schema, and verify downstream output. (Multi-input/multi-output mid-graph removal is not proven — rebuild in place.) |
| Replace the dataset behind a source | Repoint the source's `config.id`/`connector` at a different dataset — `api_enabled` gated. Never a bare swap: capture old + new schema, audit downstream column references, auto-reconcile mechanical id mismatches, surface genuine column gaps for a decision, then verify downstream after save. Rebuild in place only if the downstream can't be reconciled into a runnable flow. |
| Simple layout cleanup | Save the layout recipe diff through the API, then judge it via the deterministic layout metrics against `canvas-layout-rules.md` (there is no rendered-canvas inspection). |
| Alteryx migration cleanup | After explicit confirmation, remove unsupported migration artifacts and apply Savant-native simplifications only when the JSON behavior is documented and the affected data checkpoints can be verified. Blend plus Stack patterns require explicit row-preservation review before replacement. |

## Rebuild in place or refuse (edit)

When the requested change is outside Hard rule 5's proven in-place set — arbitrary/non-linear rewiring, multi-input/multi-output mid-graph removal, between-node connection replacement, or a brand-new source/destination *node definition* — the route is **rebuild-in-place**: rebuild the flow with **author mode** and apply it to the same flow via `workflow edit --replace-from-build` (Hard rule 5). Genuinely refuse (don't rebuild) only when:

- editing unsupported config fields whose JSON behavior is not documented
- changing business meaning without answering the relevant narrow question
- batching unrelated changes under one scope when they belong to different scopes

When a request needs a rebuild, keep the response short:

> That reshape is beyond the changes I can make node-by-node, so I'll rebuild the flow and apply the rebuilt version back onto this same flow (same URL) — no new flow gets created. Want me to go ahead?

## Edit detailed process

The deterministic loop is `savant.py workflow edit`, two phases with the scope gate between them; the LLM owns the judgment around it.

### 1. Parse the flow URL and run the deterministic precheck when needed

Parse the Savant flow URL, then fetch the current recipe with the MCP `fetch` tool on `savant://workflow/{flowId}` and write it to a file — you need that file for the whole edit: it is the propose baseline, the rollback snapshot, and the `workflow verify --before-json` argument. Mint API credentials (see Authentication) for the save itself. Use the fetched recipe as the primary orientation source (name/description, node inventory, display names/types/groups/text/outlets, inlets/outlets/edge targets, positions/group dimensions/text config/component config).

For any fix/debug/status-adjacent edit, run the shared precheck before target planning:

```bash
savant.py workflow health "{flowUrl}" \
  --workflow-json "$CURRENT" --sources-json <sources.json> \
  --output-path "$(savant.py session tmp-path "<task-name>" health.json)"
```

Treat this as a deterministic gate. If it reports missing/ambiguous source bindings or placeholder sources, stop before downstream edits and propose the source/data fix or route to Create. For a clearly narrow, health-unrelated edit (rename a label, move a group), the precheck is optional.

### 2. Detect migration cleanup scope

If the recipe or user request suggests an Alteryx migration, apply `../../references/standards/alteryx-migration-cleanup.md` before planning the edit. Offer a narrow-edit-only vs. broader-cleanup choice; separate mechanical cleanup from business-logic changes.

### 3. Resolve the edit target

Resolve the target from the recipe first. If ambiguous, ask before mutating. Use display names in chat but track the edit by node id.

### 4. Build the edited recipe in memory

Form the change with the deterministic builders — `node_builders` `*_update` for a config edit, or `recipe_edit.apply_node_edit` / `propagate_schema_change` for a change that ripples downstream (it returns the affected-node set and any `unresolved` gaps). Write the proposed recipe to the path from `savant.py session tmp-path <task-name> proposed.json`.

### 5. Propose — `savant.py workflow edit` (phase 1, no save)

```bash
CURRENT="$(savant.py session tmp-path "<task-name>" current.json)"
PROPOSED="$(savant.py session tmp-path "<task-name>" proposed.json)"
SNAPSHOT="$(savant.py session tmp-path "<task-name>" snapshot.json)"
PROPOSE_REPORT="$(savant.py session tmp-path "<task-name>" edit-propose.json)"
# Write the MCP `fetch` result for savant://workflow/{flowId} to "$CURRENT" first.

savant.py workflow edit "{flowUrl}" \
  --current-recipe "$CURRENT" \
  --proposed-recipe "$PROPOSED" \
  --snapshot "$SNAPSHOT" \
  --output-path "$PROPOSE_REPORT"
```

`--current-recipe` is required and is the pre-edit baseline: the orchestrator diffs it against the proposal, refuses a recipe whose flow id is not the target flow, and copies it to `--snapshot` as the rollback. It validates and returns the diff + validation, and does **not** save. If it reports validation errors, fix the proposed recipe and re-propose. Add `--sources-json` when using `--replace-from-build`, so unresolvable dataset ids are caught before the save.

### 6. Resolve gaps and confirm scope when needed

Resolve any `recipe_edit` `unresolved` gaps with the user first. Then present a short user-facing summary: target (display name + disambiguator), the edit scope and its expected impact, blast radius (only when topology/output grain/schema/downstream data can change). For an offered scope (Optimize/Visual polish/Documentation) a simple "Confirm?" is enough; for an implicit Error/Logic scope the user's request already authorized it. Once the scope is set, iterate inside it without re-confirming each step (Hard rule 1).

### 7. Commit and verify — `savant.py workflow edit --confirm` (phase 2)

Once the scope is confirmed or implicit, re-run with `--confirm` and the nodes to verify. Add `--edit-class fix|logic` (Hard rule 11) and `--require-documentation` when the Documentation scope or a same-session create continuation applies:

```bash
COMMIT_REPORT="$(savant.py session tmp-path "<task-name>" edit-commit.json)"

savant.py workflow edit "{flowUrl}" \
  --current-recipe "$CURRENT" \
  --proposed-recipe "$PROPOSED" --confirm \
  --edit-class fix \
  --output-path "$COMMIT_REPORT"
```

It saves in place (same flowId) and returns `status: "saved-unverified"`. **HTTP 200 is not success, and neither is this** — a save can return 200 and persist nothing. Re-fetch and verify:

```bash
AFTER="$(savant.py session tmp-path "<task-name>" after-save.json)"
# Write the MCP `fetch` result for savant://workflow/{flowId} to "$AFTER", then:

savant.py workflow verify --operation edit --workflow-json "$AFTER" \
  --expect-flow-id <flowId> --before-json "$CURRENT"

savant.py workflow inspect "{flowUrl}" --recipe-json "$AFTER" \
  --checkpoint "<affected node>" [--checkpoint ...] [--expect-columns "Col A,Col B"] \
  [--expected-outputs-json <handoff.json>]
```

`workflow verify` diffs `$CURRENT` against `$AFTER` and **fails if the read-back is identical to the pre-edit recipe** — that is the "did the save actually land" check, and it exits non-zero. `workflow inspect` then runs the **shared inspector** over the nodes you name: runtime-smoke first, then node-ok, row-sanity, and the output-contract when `--expect-columns` is given. If runtime-smoke fails, stop on that node before downstream previews. Default the checkpoints to the affected-node set `recipe_edit` returned; choose deliberately, because Analyzing AI nodes costs money. For a visual-only edit, pass no checkpoints and rely on the persisted diff plus the deterministic layout metrics (there is no rendered-canvas inspection).

### 8. Check layout quality when visual quality changed

If the edit changes layout, text, group geometry, labels, or topology, rely on the deterministic layout metrics (the `layout:` line, `polish_recipe` output) against `../../references/standards/canvas-layout-rules.md`; `--polish`/`--polish-colors` apply only under a confirmed Visual polish or Optimize scope. There is no rendered-canvas inspection — judge layout from those metrics rather than claiming a rendered visual pass.

### 9. Rollback

Rollback is a live edit too. If the user asks to revert, propose restoring the saved recipe snapshot (the `--current-recipe` file from before the edit), wait for explicit confirmation, save it through the API, then re-fetch with MCP `fetch` and run `workflow verify --operation edit --before-json <the post-edit recipe>` to confirm the workflow returned to the captured state.

## Definition of done (edit)

An edit is done when: the edit scope was explicit or implicit in the user's request and a rollback snapshot was captured before saving; the API save persisted (`workflow verify --operation edit` exited 0, meaning the re-fetched recipe differs from the pre-edit one on the same flowId — for topology edits, `assert_expected_model_diff` passes); any step whose configuration changed has a refreshed (or re-verified) description; and the affected-scope verification passed (node-output evidence when logic changed, deterministic layout metrics when anything visual changed).

The deterministic signal is `workflow verify --operation edit` exiting 0, followed by `savant.py validate stage --role editor --gate done <edit-commit.json>` passing. `workflow edit --confirm` alone reports `saved-unverified` and is not the signal. Report what changed, that a rollback snapshot exists, and any verification out of scope. Read `definition-of-done.md` only when the completion claim is broader than the narrow edit.

---

## Route defects (both modes)

Applier identifies which check failed and routes the fix to the skill that owns it.

- **Safe same-flow fixes** (visual layout, group/header text, node descriptions, display labels, editor-supported config): handle in Edit mode, then re-run the affected check.
- **Schema-bound topology / JSON-generation defects, or a missing/wrong dataset id on a source node:** route back to **author mode**.
- **Ambiguous business logic:** ask one narrow question before changing the workflow. Don't infer amount basis, source-of-truth precedence, output grain, or join preservation from a successful run alone.

After any routed fix, re-run the affected checks before judging done. Do not use repeated imports as an iteration loop; once a flow exists, same-flow fixes belong in Edit mode. If duplicate create artifacts already exist from the same session, name the current intended workflow and the superseded/failed workflow URLs as cleanup candidates, and ask the user to delete the extras in the Savant app — Savvy never deletes flows itself.

## Working with other Savant skills

- **author mode** generates the workflow JSON Applier imports, and is the rebuild path for edits Applier can't do inline (unproven topology, unsupported settings). The standard refusal message points the user there.
- **inspect mode** is the read counterpart — it reads, explains, and exports flows. When the user's question is about behavior or data rather than a change, hand off. Common pattern: inspector identifies a problem → Applier (Edit) proposes a fix → inspector verifies downstream. Inspector also owns JSON export: before a substantial edit, proactively offer "Want me to save the current JSON first, as a full-flow rollback?" (MCP `fetch` on `savant://workflow/{flowId}`, written to a file) — but let the user decide. An edit needs that file anyway: `workflow edit --current-recipe` takes it as the diff baseline, and it doubles as the rollback snapshot.
- **Deletion is out of scope.** Applier never deletes anything — not a node, not a flow, not an edge. Ask the user to delete in the Savant app.
- The **`../../references/components/` library** holds per-type API guidance. Read `{type}.md` before operating on a node of that type. If the guidance or `../../references/registry/components/{type}.json` does not document the requested JSON mutation, refuse that node type.

## What not to do

- **Don't re-import to change a flow that already exists.** Import mints a new flowId; that is Create, not Edit. Structural fixes (add/remove node) belong in Edit mode, in place.
- **Don't save (edit) outside a confirmed scope.** Every save belongs to an explicit or implicit edit scope; iterate freely inside it, but don't drift into changes the scope didn't cover.
- **Don't skip the rollback snapshot.** No recipe snapshot, no rollback path, no save.
- **Don't trust HTTP success alone.** Re-fetch and verify the persisted diff (edit) or the persisted recipe (create).
- **Don't use repeated imports as a debugging loop.** One confirmed import per workflow name/folder; later defects belong to the created flow.
- **Don't resolve datasets in Create.** Every source node must already carry a real dataset id; a missing/placeholder id routes to Author.
- **Don't repair malformed JSON.** JSON-generation defects route to Author.
- **Don't guess at JSON config behavior.** If it is not documented in the registry/component notes, stop.
- **Don't invent data.** Report the row counts and results the inspector actually returned.
