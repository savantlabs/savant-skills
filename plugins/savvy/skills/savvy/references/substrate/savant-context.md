# Savant Context

## Objective

Use this as the shared object model for Savant skills: what each object is, how objects relate, and which context must be preserved before live work.

## Use When

- A request names a workspace, folder, system, dataset, workflow, step, run, test, or admin usage surface.
- A request includes a Savant URL.
- A skill must discover, create, bind, inspect, edit, import, delete, or explain a Savant object.

## Default Action

- Preserve organization/workspace/session context before discovering or changing objects.
- Resolve folder/workflow/dataset/system identity inside the authenticated session, not globally.
- Use the owning substrate for mechanics: datasets, run modes, run history, admin usage, support, AI providers, or canvas.
- Use `../standards/business-user-response-rules.md` for chat wording.

## Do Not

- Do not assume ids, folders, datasets, systems, or workflows are portable across workspaces, browsers, tabs, or sessions.
- Do not assume a workflow ran because it exists or has valid JSON.
- Do not switch organization/workspace silently.
- Do not use product/internal vocabulary in user-facing responses unless it helps the user act in the app.

## Object definitions

- **User:** A person using Savant. A user can have access to one or more organizations, and through those organizations can access one or more workspaces.
- **Organization:** A company/account boundary. An organization can contain multiple workspaces, and a user may belong to multiple organizations.
- **Workspace:** A work area inside an organization. Each workspace has its own systems, datasets, folders, workflows, permissions, and run history.
- **Folder:** A workspace-level container for organizing workflows. Each folder can contain multiple workflows.
- **System:** A connected source or destination system available in a specific workspace, such as Snowflake, SharePoint, S3, Google Drive, SFTP, or an API. A workspace can have multiple systems. The workspace's Systems list is the available inventory, not the full set of systems Savant supports.
- **Dataset:** A reusable data input in a workspace. A dataset may be uploaded/static or system-backed. A dataset can be used by one or more workflows.
- **Workflow:** A Savant process artifact in a workspace/folder. It connects input data, preparation, matching, calculations, review branches, and outputs.
- **Workflow version:** A numbered workflow state. Submitted/reviewed versions are listed separately from the current active editable version; the current active version may be a draft that has not been submitted.
- **Node / Step:** A visible step in a workflow; *step* is the user-facing name.
- **Component:** The underlying type of step, such as source, transform, filter, blend, summarize, or destination. Internal vocabulary, not user-facing.
- **Source:** The step that brings a dataset into a workflow.
- **Destination / Output:** The step that sends, writes, or presents the final result.
- **Run history:** The workspace-level record of full workflow executions. The Run History area has a **Runs** tab that shows run id, workflow name, version, submitter, phase/status, progress, start time, finish time, and duration.
- **Test history:** The workspace-level record of test executions. The Run History area has a **Tests** tab separate from full runs.
- **Admin usage log:** The admin-only usage surface for date-range usage across admin-visible workflows. It shows workflow/run counts, processed rows, tokens when enabled, owner/workspace, source and destination connectors, and row-level usage events.
- **Interactive (1k):** The fast, no-write preview rung. Computes on at most ~1000 **input** rows (`sampleTier=1k`). Because the input is sampled, totals, distinct/dedup counts, and filter/join match-counts on this rung can be short or wrong. Default for iteration and structural/per-row checks.
- **Analyze (max):** A no-write validation rung on the same interactive endpoint with `sampleTier=max`. Reads the **real full source** and computes on full data, trimming intermediate results to a ~32 MB working cap. Use it when full-data fidelity matters (aggregates, dedup, match-counts). "Much fuller than 1k," not a guarantee of every row.
- **Test mode (batch):** A durable execution that reads real source data end to end while skipping destination side effects.
- **Run mode (batch):** The full durable execution. It reads source data and writes to destinations, sends emails, calls output APIs, or performs other configured side effects.
- **Sample tier is binary:** the backend honors only `max` (full-source Analyze) vs `1k` (interactive sample). There is no `2k`/`10k`/`50k` tier; any other value behaves as `1k`. Run-mode policy and the `--mode` vocabulary live in `run-modes.md`.

## Relationships

- A user can access multiple organizations.
- An organization can contain multiple workspaces.
- A user can access multiple workspaces through one or more organizations.
- A workspace belongs to one organization.
- A workspace can contain multiple folders.
- A workspace can contain multiple systems.
- A workspace can contain multiple datasets.
- A folder can contain multiple workflows.
- A workflow belongs to a workspace and is organized in a folder.
- A workflow can use multiple datasets.
- A dataset can be used by multiple workflows.
- A dataset belongs to a workspace and may be uploaded/static or provided by a connected system.
- A system belongs to a workspace and can provide multiple datasets.
- A system can be used by multiple workflows through its datasets or destinations.
- A workflow can have run history and test history records.
- Run and test history records belong to the workspace and point back to a workflow/version.
- Submitted/reviewed workflow versions and the current active workflow version are different surfaces. Count distinct version numbers across both, and if the current active version does not appear in the submitted-version list, say it has not been submitted. Do not infer a submitter or updater from `editor`, `modifiedBy`, or owner fields for an unsubmitted current version.

## Practical rules

- Always identify or preserve the correct organization and workspace context before discovering datasets, systems, folders, workflows, or run history.
- Do not assume organizations, workspaces, systems, datasets, folders, or workflows are interchangeable across sessions.
- Do not assume systems, datasets, folders, or workflows exist across workspaces, even when the workspace names are similar or the same user can access both.
- Treat folder URLs as session-scoped. A `folderId` from an analysis URL is only meaningful inside the workspace/session attached to the browser tab that opened it; do not treat folder ids as globally resolvable across workspaces, browsers, or tabs.
- When giving the user a clickable link to any Savant asset, make sure it carries `?rns=<namespace>` for the owning workspace — append it if the link lacks one, so the web app opens in the right workspace. Toolchain report `flowUrl`s already include it; an `rns` already present in a URL is authoritative, do not rewrite it.
- Do not assume a workflow has been executed just because it exists or has a valid recipe. Use Run History / Test History evidence when the question is whether the workflow was actually run or tested.
- When creating or importing a workflow, require an explicit folder.
- When binding data, use datasets available in the target workspace.
- When choosing source data, use the target workspace's connected systems and datasets as the available inventory.
- When a dataset or system is shared across workflows, surface that impact before making changes that could affect other processes.
- When explaining results, distinguish uploaded/static datasets from system-backed datasets when that affects repeatability or freshness.
- Treat Interactive, Analyze, Test, and Run as an increasing cost/risk ladder. Interactive (1k) and Analyze (max) are both no-write previews; Test reads real sources (no writes); Run creates files, sends emails, updates systems, or otherwise produces real outputs. Stay on the lowest rung that answers the question.
- Do not run Test or Run unless the user explicitly asked for that mode or confirmed the side effects. Default reads to Interactive; escalate to Analyze only when full-data fidelity is needed (aggregates, dedup, match-counts, or a result capped at ~1000). Visual-only edits and draft import/render checks do not need any compute. See `run-modes.md`.

## Run Modes And API Ownership

Run-mode behavior belongs in `run-modes.md`; this context file only records where the modes sit in the Savant object model and which substrate owns the mechanics.
Run/test execution evidence belongs in `run-history-substrate.md`.

Known API surface:

- **Analyze / node preview computation:** `POST /api/interactive/graph-computation?sampleTier={1k|max}` (add `&action=APPLY` only when recomputing from an edited starting node; there is no `action=ANALYZE`), followed by `GET /api/interactive/graph-computation-status?flowId={flowId}&sampleTier={1k|max}` and `POST /api/interactive/graph-computation-sort?flowId={flowId}&nodeId={nodeId}&sampleTier={1k|max}` to fetch preview output. `sampleTier` is binary (`1k` interactive sample vs `max` full-source). Run-mode choice is owned by `run-modes.md`.
- **Workflow map:** Use `../scripts/savant.py workflow map --input-json <recipe.json>` when a skill needs a compact recipe-derived map of workflow metadata, nodes, groups, edges, sources, destinations, and terminal steps. The recipe comes from the MCP `fetch` tool on `savant://workflow/{flowId}`; the route reads that file only, runs no data, and **needs no `api_enabled`** — it works with API access switched off entirely.
- **Workflow targets:** Use `../scripts/savant.py workflow targets` when a skill needs suggested validation checkpoints from a recipe. It is read-only, does not run data, and its output is advisory rather than a required checklist.
- **Post-write verification:** Use `../scripts/savant.py workflow verify --operation create|edit|metadata --workflow-json <after.json>` after every create, edit, or metadata save. The write commands no longer read their own result back, so this is what confirms the write landed: folder placement (`--expect-folder-id`), node persistence against the imported JSON (`--source-json`), the pre/post model diff proving an edit persisted (`--before-json`), metadata fields (`--expect-metadata-json`), and file-based validation. `<after.json>` is the MCP `fetch` result for `savant://workflow/{flowId}`. **It reads files only — no `api_enabled`, no credentials — and exits non-zero on failure. A write is not reportable as done until it exits 0.**

- **Batch node preview inspection:** Use `../scripts/savant.py preview nodes` with `--workflow-json <recipe.json>` (the MCP `fetch` result, which node ids and names resolve against) when inspection, creation verification, or edit verification needs data output from multiple known node ids. By default (`--mode cached`) it reads only already-available preview status/output. Use `--mode interactive` to compute at the 1k sample, or `--mode analyze` for full-data validation; see `run-modes.md` for when to escalate. Do not use it for visual-only verification.
- **Test and Run:** Treat as the same execution family conceptually, but do not assume helper support or endpoint shape unless the current app/API helper has proven it. These modes are higher risk because Test reads real data and Run writes outputs.
- **Run history:** Workspace-specific execution records. Use run-history APIs only through a documented helper/substrate once available; do not infer history from the workflow recipe alone.
- **Run vs. Test history:** The app separates full runs from tests. A full Run means the workflow was executed in the mode that can write outputs. A Test means the workflow was executed without destination side effects. When reporting execution evidence, say which one you found.

Execution-history evidence should include the workflow name, run/test id when available, version, status/phase, progress, submitter when useful, started/finished times, and duration. If no matching entry is found, say that no run/test history was found in the checked workspace and time range rather than saying the workflow never ran.

When adding or changing API helpers, keep the detailed endpoint recipes in the relevant substrate or script docs, not here. This file should stay a map of objects, relationships, risk, and ownership.

## Core Object API Ownership

Each core object below names the documented helper or MCP tool that owns its operations — use that path.

- **Organization/workspace/session context:** Read from the authenticated Savant app session. The helper should preserve organization, workspace, and namespace context and never switch the user's organization or workspace silently. **Discovery:** use the resources `search` tool — `search(types=["organization"])` (every org you can access, each with its namespace; the current org is flagged) and `search(types=["workspace"])` (active workspaces in the bound org, each with its namespace) — plus `whereami` for the current scope. These run off the MCP session and need no browser tab-session; the namespace they return is what `switch-workspace` consumes. See "Session auth and the token-only vs workspace-scoped split" below for the mandatory user-confirmation rule.
- **Folders:** **Folder targeting is by id**, in the authenticated session's namespace. Find a folder's id via MCP `search`/`fetch` on the `folder` entity, then pass it as `--folder-id` to `savant.py workflow create` (or `savant.py app --import-json`) and to `savant.py workflow verify --expect-folder-id` — use `--folder-id home` for the Home folder (the namespace root; the import API represents it as a null folderId; `root` is accepted as a legacy alias). **The Home folder is always a valid create destination** — a workspace with no folders is not a blocker. Folder ids are workspace-scoped, so switch to the folder's workspace (MCP `switch-workspace`) before creating — but only ever to a workspace the user named: `workflow create` requires `--confirmed-namespace` (the user-confirmed destination workspace's namespace) and blocks import when the session is in any other namespace. If a folder id is not present in the session, report that it could not be found there. **Folder-level orientation is answered through MCP, not a dedicated helper:** `fetch(folder)` for identity, `whereami`/`whoami` for the workspace/org/user, `search(types=["workflow"])` filtered by `folderId` for the workflows in a folder, and `search(types=["folder"])` plus each hit's parent `folderId` for sibling/child folders.
- **Workflows/recipes:** Workflow export/import/save is owned by the app API helper. Current helper coverage includes `GET /api/recipes/{flowId}`, `POST /api/recipes/import`, and `PUT /api/recipes` with post-save re-fetch verification.
- **Datasets/sources:** Dataset discovery and binding rules live in `dataset-substrate.md`. Discovery is via `search(types=["source"])` for name→id (filtered by `namespace`) and `fetch(source)` for schema/content type.
- **Systems:** Systems are workspace-level connected sources/destinations (user-set-up connections such as OneDrive or Google Drive). Discovery, read-only access, ambiguity handling, destination binding, and the source-via-system-backed-dataset boundary are owned by `system-substrate.md` (discovery: MCP `search(types=["connection"])` + `fetch`, filtered by `namespace` since connection search is org-wide). Skills never create or authenticate a connection. Dataset binding still prefers the dataset inventory visible in the target workspace (`dataset-substrate.md`).
- **Support:** Support contact is not a workflow API. The in-app assistant is covered by `support-api-substrate.md`.
- **Run/Test history:** Execution evidence is owned by `run-history-substrate.md`. Use it when the user asks whether a workflow actually ran, tested, succeeded, failed, produced outputs, or has execution history.
- **Admin usage log:** Aggregate usage analysis is owned by `admin-usage-substrate.md`. Use it when an admin asks usage questions across workflows, owners, workspaces, connectors, processed rows, runs, or token consumption.

**MCP search hits carry scope.** Every `search` result includes `namespace` and `folderId`. Most types are workspace-scoped, but **connections are org-wide** — a connection hit's `namespace` is its true owner, not your session's, so always check it before binding or acting. Use `folderId` to scope a workflow list to a folder (`search(types=["workflow"])` + filter by the target folder). The `namespace` round-trips into `switch-workspace`; to *act* in another namespace, switch there first.

If a needed object API is not documented yet, run a narrow discovery probe on a safe/read-only path first and record the finding in the relevant substrate before relying on it in a skill.

## Session auth and the token-only vs workspace-scoped split

The helper authenticates from the browser profile's localStorage (it sends **no cookies**): the access token comes from the `savant/session` record and is sent as `Authorization: Bearer …`; the workspace context comes from the `savant/tab_session` record and is sent as `X-SAVANT-TAB: <tab_id>`. The server uses that **tab id**, not the URL namespace, to decide which workspace a request runs in.

Two consequences worth internalizing:

- **Token-only (no tab session needed):** organization list (`/api/sessions/organizations`). It resolves from the token alone — useful even before any workspace has been opened. AI providers are no longer read over the API at all: use MCP `search` with `types: ["ai_provider"]` (see `ai-provider-substrate.md`), which needs a workspace bound but no `api_enabled`.
- **Workspace-scoped (require a valid tab session):** workspaces, folders, recipes, sources, node analyze, and import/save. Without a tab session for the target workspace these fail or return the wrong/empty result.

The tab id is **durable**: the Savant web app writes the `tab_session` record when a workspace is active, and it persists after the tab is closed. So the real precondition for workspace-scoped work is "this workspace was opened in the browser at least once," not "a tab is open right now." If no session exists for the target workspace, `resolve_folder_url` now returns an actionable error listing the workspaces it can see and telling the user to open the target workspace once (or pass `&rns=<namespace>`).

### How to use these (trigger model)

Resolve from what is already given first; only call these discovery APIs to break a genuine ambiguity or recover from a resolution failure:

- A folder/flow URL that resolves through an existing session → use it; do not list orgs/workspaces.
- The user names a workspace, or a URL fails to resolve, or several workspaces are plausible → `search(types=["workspace"])` to map the name to a namespace or to show the options.
- The user spans multiple organizations and has not indicated which → `search(types=["organization"])` (rare; most users are in one org).
- Folder resolution itself is the always-needed step for create/import and is already owned by the folder helpers above; it just needs the right workspace session.

### Mandatory: confirm before acting on any resolved org/workspace/folder

These listing calls are **read-only discovery**. Any organization, workspace, or folder selected from their output is a decision that must be **confirmed by the user before any create, import, save, or other state-changing action** — never auto-selected or assumed, even when there is a single candidate. When more than one option is plausible, present the options (by display name) and ask; when one is implied, state it and get explicit confirmation. This preserves the Creator's context/creation-confirmation gates and prevents accidentally operating in the wrong workspace or folder.
