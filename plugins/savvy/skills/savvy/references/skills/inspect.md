# Savant Workflow Inspector (inspect mode)

> **When this mode applies:** the user points at a Savant flow URL (.../en/app/flow/...) and wants to (a) understand what the flow does, explain it, summarize it, or export/download/grab/fetch its JSON; or (b) inspect, debug, troubleshoot, drill into, walk through, or check the behavior of specific nodes, branches, row counts, previews, filters, joins, summaries, output records, run/test/schedule history, or whether the workflow ran/succeeded/failed. Covers both the zoomed-out "what is this flow for" business summary and the zoomed-in node-level data evidence. **Read-only** — never edits or saves. (The whole-flow business walkthrough can be delegated to the `flow-explainer` agent; see the parent `SKILL.md`.)

## Goal

The Inspector reads an existing Savant flow through the authenticated app API and answers the user's question about it, at whichever altitude they need:

- **Zoomed out — explain & export.** Hand over a flow URL, get back a plain-English explanation of **what the flow does for the business** (a flow usually represents a real task — reconcile GL against bank statements, apportion payroll by state, classify invoices) and, when asked, the exported workflow **JSON**.
- **Zoomed in — inspect a node.** Answer the **specific** question about what's happening at a node or branch — configuration, data shape, row counts, sample rows, branch behavior — grounded in the node's computed output.

It is **read-only**: it exports and explains, it never edits or saves. The zoomed-out summary is grounded in the recipe structure; the zoomed-in answer is grounded in live node evidence. Default to the altitude the user asked for — don't drill into nodes for a "what does this do?" question, and don't give a whole-flow essay for a single-node question.

## Inspector Procedure

1. **Prepare.** Confirm the flow URL, mint API credentials (see Authentication), confirm `api_enabled`, and identify whether the user wants the business summary, the JSON export, a node-level answer, or a combination.
2. **Read the right evidence.** Orient on the recipe map; for a summary read the business structure from the recipe; for a node question disambiguate the target and fetch only the output needed to answer.
3. **Answer and route.** Explain in business terms, cite the evidence read, and route changes to the Applier (edit/rebuild) — never edit here.

## Core responsibilities

This skill has three responsibilities:

1. **Explain & export** - export the workflow JSON through the API when asked, and summarize what the flow accomplishes as a business process (see "Explain a flow"). The default for "what does this do?" is a concise business explanation grounded in the workflow structure, not a node-by-node walkthrough.
2. **Workflow inspection** - follow `../../references/standards/workflow-inspection-rules.md` to read the recipe map, inspect selected nodes/branches, analyze/fetch node output when data evidence is needed, interpret row counts, and diagnose behavior from evidence.
3. **Question answering** - keep the conversation targeted, answer in business terms, cite the inspected evidence, and route changes to the Applier.

Internal app API mechanics are owned by `savant.py app`. Run-mode safety is owned by `../../references/substrate/run-modes.md`. Do not duplicate those mechanics here.

## Explain a flow (export + business summary)

When the user pastes a flow URL and wants to know **what the workflow does**, or asks to export/download/grab the JSON, answer at the business altitude before drilling into any node.

**Get the JSON** with the MCP `fetch` tool on `savant://workflow/{flowId}` — the flow id is the
segment after `/flow/` in the URL. It returns the same document the old CLI export downloaded — verified field-for-field against
`GET /api/recipes/{id}` before that route was removed — and needs no credentials, so a plain read
works even when `api_enabled` is false.

Write it under the session tmp dir unless the user asks for a durable path (e.g. Downloads):

```bash
savant.py session tmp-path "<task-name>" "{flowName-or-flowId}.json"   # resolve the path, then write the fetch result there
```

End by telling the user the local path. There is no CLI export route any more.

**Build the business summary from the recipe JSON.** Read the JSON first and reconstruct the declared process: inputs, major process blocks, branches, destinations, and likely business purpose. The default is **not** a node-by-node walkthrough — it is a concise business explanation grounded in the structure. Answer these in your head, then write flowing prose:

- **Who is this for?** Prefer workflow metadata (workspace, folder, workflow name, owner, source/destination names, connected systems, dataset names); infer the team/process lightly and say when context is limited.
- **What business objective does it serve?** Lead with the decision, control, review, payment, reporting, or operational outcome — not "this takes X and transforms Y" unless the user asks for mechanics.
- **What specialized terms need plain-English framing?** Define terms like royalty, commission, accrual, reconciliation, allocation, or journal entry briefly before explaining.
- **What is the real-world input?** Read source node configs: connector type, dataset name, file pattern, vision prompts.
- **What end deliverable does it produce?** Read destination nodes: file/email/writeback destinations, or the absence of one.
- **What is the core transformation?** Collapse node clusters into one or two sentences; name the pattern (extraction, reconciliation, apportionment, classification, enrichment, ETL, reporting) when recognizable.
- **What do branches mean in business terms?** Explain what each filter true/false or blend matched/unmatched path represents for the business.

Default response shape (unless the user asks for a technical walkthrough):

1. **Plain-English purpose** — one or two sentences defining any central business term and why the process exists.
2. **How you would use it** — when a business user runs it and what decision/review/approval/payment/filing/booking it supports.
3. **What it checks or decides** — the core checks in business language.
4. **What comes out** — the final deliverable and what to do with clean vs. exception items.
5. **Important caveats** — only those that change business trust or actionability.

Keep it tight. If you notice design gaps or likely Alteryx migration artifacts, mention them briefly (use `../../references/standards/alteryx-migration-cleanup.md` for signals) — but stay read-only and don't go deeper unless asked.

A JSON export plus business summary does **not** mean the workflow is verified, production-ready, or that it ran — say so when it matters, and never infer execution from the JSON. For "did it run / succeed / produce output?", follow `../../references/substrate/run-history-substrate.md`. When the business meaning is ambiguous and only live rows can settle it, drop into node inspection (below) as the same skill's zoomed-in mode — typically the primary source, a non-obvious secondary source, the key match/filter/join, and the final destination input.

## Authentication

This skill calls the Savant web-app API directly, but it never mints its own credentials. The chat client holds the MCP connection and is the only thing that speaks MCP; the `savant.py` shell is a pure API executor that reads its credentials from the environment. The handoff:

1. **Resolve the workspace.** **Prefer the namespace already in the URL** — a flow URL with `?rns=<namespace>` names the owning workspace, so use it directly. Only when there is no `rns` (an rns-less URL or a bare recipe id) call the **`locate`** MCP tool to resolve the owning namespace — pass the recipe's `savant://workflow/{flowId}` URI (the same form `search` returns), **not** a Canvas URL or bare id. If the active session is not already in that namespace, call **`switch-workspace`** (passing the namespace `locate` returns) — or **`switch-folder`** — so the minted credentials are scoped to the workspace that owns the flow, then read with `fetch`. (If switching to the URL's `rns` doesn't grant access, fall back to `locate` for the true owner.)
2. **Mint credentials.** Call the **`get-api-credentials`** MCP tool. It returns `apiBaseUrl`, `token`, and `tabId`.
3. **Supply the credentials to the toolchain — for this session only.** `savant.py` reads `SAVANT_API_TOKEN`, `SAVANT_API_TAB`, and `SAVANT_API_BASE_URL` (optionally `SAVANT_API_NAMESPACE`). Pass them inline on each call as **environment variables, never CLI flags** (an arg is visible to other local users via `ps`):

   ```sh
   SAVANT_API_TOKEN=<token> SAVANT_API_TAB=<tabId> SAVANT_API_BASE_URL=<apiBaseUrl> python3 scripts/savant.py …
   ```

   (`apiBaseUrl` may end in `/api`; the shell normalizes it.) **Do not set, invent, or export `SAVANT_AI_SESSION_ID`** — the session id is derived from the runtime automatically. *Optional file form (your discretion):* write the **`get-api-credentials` response** to the path from `savant.py session tmp-path savant-creds.json` and set `SAVANT_CREDS_FILE` to it — the response object is the file format. That path is user-private, OS-reaped temp outside the repo; never write credentials elsewhere (repo, `$HOME`, a `.env`) or keep them past the session.
4. **On a 401**, the token has expired — call `get-api-credentials` again, re-supply the credentials, then retry. Do not re-parse or retry by hand beyond that.

**Never echo the token (or the creds file's contents) into a user-facing reply.**

There is no browser session and no rendered-canvas inspection. Inspect through the API only.

## Shared post-change verification

The deterministic inspection harness `savant.py workflow inspect` (node-ok / row-sanity / output-contract / persistence, governed by `workflow-inspection-rules.md`) is the **shared verify process** that runs after a workflow changes — not only when the user asks to inspect. The **Applier** calls it after an import (`workflow create`) and after a save (`workflow edit --confirm`), passing the node set it wants checked. So the "preview these nodes, are there errors, what are the row counts" step is one process, owned here and reused by the Applier's create and edit modes; the Applier supplies the node selection and the LLM interprets the report. Keep the inspection mechanics in this skill and `workflow-inspection-rules.md`, not duplicated in the create/edit orchestrators.

## Before You Start

User-facing replies follow the shared business-user response rules loaded at session start.

`savant.py ...` is shorthand for the bundled toolchain; the parent `SKILL.md` Toolchain section explains how to locate and run it.

**Before inspecting a workflow, read `../../references/standards/workflow-inspection-rules.md`** - the shared live-inspection playbook for orientation, node/branch inspection, row-count interpretation, no-data handling, full walkthroughs, and read-only boundaries.

**Read `../../references/standards/definition-of-done.md` when inspection turns into debugging or verification** - use the inspect/debug section for answering a targeted question. A workflow is not fixed, clean, or production-ready until the edit/import/full-verification criteria are also met.

**Read `../../references/standards/alteryx-migration-cleanup.md` when the user mentions Alteryx/migration/conversion, slowness, hanging, optimization, or when inspection shows migration artifacts.** Use it to classify likely migration signals and recommend the right cleanup handoff. This skill remains read-only.

**Read `../../references/substrate/run-history-substrate.md` when the user asks whether a workflow ran, tested, scheduled, succeeded, failed, produced outputs, or has execution history.** It owns execution-history evidence rules and the API helper path for workflow-specific Run/Test history.

1. **Credentials minted and supplied to the toolchain.** Follow Authentication above before any API call.
2. **API enabled in the shared capability snapshot.** With credentials supplied, resolve the snapshot path with `savant.py session tmp-path savant-capabilities.json`, run `savant.py capabilities --output-path <resolved-capability-path>`, and proceed only when `api_enabled: true`. If it is false, stop or answer only from already-provided local JSON; do not imply live row counts, preview status, run history, or workflow health were checked.
3. **The flow's URL.** Name-based identification is not acceptable. If the user gave only a name, ask for the URL.

For debugging issues involving raw source fields, joins, filters, summaries, or confusing output columns, also read `../../references/standards/data-prep-normalization.md` so recommendations point toward upstream normalization when that is the stable fix.

## Inspector Fix-Question Rules

When inspection reveals a likely fix, classify the issue before recommending or handing off the edit:

- **Mechanical defect:** the node errors, a field reference is invalid, a type cast fails, or the flow does not run.
- **Business-logic defect:** the flow runs but uses the wrong field, fallback, filter, join type, amount basis, or grain.
- **Normalization defect:** downstream nodes depend on raw source columns that should be cleaned, typed, renamed, or canonicalized upstream.
- **Usability/output defect:** the flow works, but output columns are confusing, too technical, missing review flags, or poorly ordered.
- **Performance/maintainability improvement:** the flow works, but duplicated formulas, repeated cleanup, or fragile downstream raw-field references make it hard to maintain.

Ask only the small question that changes the recommended fix. Do not front-load a questionnaire. If the answer is obvious from source data, prior context, or the user's explicit request, proceed and state the assumption. Ask before recommending a fix that changes output grain, amount basis, source-of-truth precedence, fallback behavior, join preservation, filter semantics, summarization grain, review flags, or final destination columns.

Use business wording, not component names. Examples: ask whether unmatched records should be kept and flagged or dropped; whether a corrected value should be fixed once upstream and reused; what the total should be grouped by; who reads the final output and whether column names should be business-friendly.

## Detailed Process Reference

### 1. Parse the flow URL

Savant flow URLs are `https://<host>/en/app/flow/{flowId}` with optional query params (e.g. `?rns={namespace}`). Extract the `flowId` — and the `rns` when present, which **is** the owning namespace, so use it directly. Only when there is no `rns` (or you were given a bare id) build the `savant://workflow/{flowId}` URI and pass it to the `locate` MCP tool to resolve the owning namespace before minting credentials (see Authentication). (`locate` takes the `savant://` URI, not the raw Canvas URL.)

If the URL does not match this pattern, ask the user to paste a flow URL.

### 2. Run the first-pass health check for status/issue questions

When the user asks for current status, health, issues, errors, broken sources, whether the workflow works, or what to fix, start with the read-only health helper before targeted node inspection:

```bash
savant.py workflow health "{flowUrl}" \
  --workflow-json <recipe.json> --sources-json <sources.json> \
  --output-path "$(savant.py session tmp-path "<task-name>" health.json)"
```

`--workflow-json` is required: the recipe comes from the MCP `fetch` tool on
`savant://workflow/{flowId}`, not from the API. `--sources-json` (the MCP `search` result for
`types: ["source"]`) enables the dataset-matching leg; omit it and matching is *skipped*, not
reported as zero matches. Run history and the optional preview still need `api_enabled`.

The helper reads the recipe, version status, Run/Test history, and source dataset matches. It does not compute by default. Add `--mode interactive` (or `--mode analyze` for full-data evidence) only when the user asked for data behavior evidence and you want the single earliest-checkpoint preview. It is designed to stop at the first likely blocker before downstream inspection.

Use the health-check JSON as the orientation evidence for:
- draft/submitted status
- missing or ambiguous source bindings
- likely placeholder source steps
- first preview failure, only when Analyze preview was explicitly included
- the next recommended fix

If the health check finds source issues, report those first and do not inspect downstream joins, summaries, or destinations until the sources are fixed or the user explicitly asks for downstream configuration review.

When the user's question is specifically about Run History, Test History, schedule execution, or whether a workflow actually ran, follow `../../references/substrate/run-history-substrate.md` instead of treating Analyze preview evidence as execution history.

### 3. Get oriented from the recipe map first

Use `savant.py app` to read the recipe JSON in memory, then build the node inventory and graph shape from that recipe. Do not save the JSON unless the user asks for it or you need a task-local debug artifact.

After orientation, you should know the flow name, node inventory, branch/outlet shape, groups/text nodes, and enough structure to answer simple orienting questions without inspecting any node output.

If the recipe shows likely Alteryx migration artifacts, classify them with `../../references/standards/alteryx-migration-cleanup.md`. Report them as diagnosis only: this skill can explain why they may cause errors, slowness, hanging, or maintenance risk, but it must hand cleanup to **applier mode** (edit in place, or the export → author → applier rebuild path).

If API orientation fails because credentials are missing/expired or the recipe endpoint does not return a workflow-like object, stop and report that the workflow could not be inspected through the API.

### 4. Wait for the user's question unless they already asked one

If the user only gave a URL, stop after orientation. Your reply must do three things, in order:

1. **Name the flow.** Start with `This is {flowName}.`
2. **Describe the shape** in one sentence: node count and either group labels or a quick structural note like "three-way branch after extraction, converging in a join."
3. **End with a question** inviting the user to pick something to inspect.

The whole reply should fit in 3-5 short sentences. Do not inspect a node just because it looks interesting.

If the user explicitly asks for a full walkthrough, do one, but keep it data-grounded: config, row count, and a sample at each important node.

**Disambiguate when the question is ambiguous.** If the user asks about "the filter" and the flow has multiple filter nodes, list the candidates in human terms before inspecting. Do not guess.

### 5. Inspect a specific node or branch

Use `../../references/standards/workflow-inspection-rules.md` for the evidence-gathering sequence:

- resolve the target from the recipe graph
- read configuration from the recipe
- fetch existing node output through the API when data evidence is needed; trigger Analyze only when the user's request or confirmed scope calls for no-write preview evidence
- inspect upstream and downstream checkpoints only as needed to answer the question
- read the component file for unfamiliar node-specific semantics

For branch questions, inspect the parent node, the relevant outlet/target path, and enough downstream output to explain what the branch represents.

When the question requires comparing multiple checkpoints, follow `../../references/standards/workflow-inspection-rules.md` and use the shared batch preview helper rather than running separate one-node preview calls.

### 6. Translate to business terms

When answering, describe what the node does for the data, not the internal config shape alone.

Bad:

```text
Filter node in Builder mode with one clause: Entity, Contains, RRH.
```

Good:

```text
The filter keeps only files whose Entity path contains "RRH". After the filter, 1 of 1 rows remain, so for this dataset every file already matches.
```

Always cite the row count delta when it is relevant. "Went from N to M rows" is how you catch dropped joins, overly aggressive filters, and broken summaries.

### 7. Handle the no-data case

Follow `../../references/standards/workflow-inspection-rules.md`: distinguish zero rows from no preview data. If live execution is needed, read `../../references/substrate/run-modes.md` and follow its execution-mode confirmation rules.

### 8. Visual-layout questions

There is no rendered-canvas inspection. For questions about visual organization, label overlap, group readability, or connector routing, answer what the recipe graph implies (groups, node ordering, branch structure) and state that the rendered canvas was not inspected. Do not reconstruct or guess at pixel-level layout.

### 9. Keep the conversation going

Inspector work is often a sequence of questions, not one report. After answering the first question, invite the next targeted check instead of dumping a large walkthrough the user did not ask for.

## Definition of done

A read is done when the user's question is answered and **grounded in cited evidence** at the right altitude. For an explain/export request: the business summary (and the local JSON path when exported) — grounded in the recipe structure, with execution/verification claims only when actually checked. For a node question: the node's config and, when behavior is in question, its computed output (row counts / sample rows). Don't claim a preview or Analyze result you didn't actually fetch, and only assert live data when `api_enabled` and the data was read. No unrequested node-by-node walkthrough. When this skill runs as the shared post-change verify for the Applier, "done" is the inspect report (node-ok / row-sanity / output-contract) over the requested nodes. Apply the explain/inspect section of `../../references/standards/definition-of-done.md`.

## Working with other Savant skills

A business-level summary or flow JSON export is **this skill's** zoomed-out mode (see "Explain a flow") — handle it here, don't route it elsewhere. If inspection reveals a likely change, distinguish diagnosis from remediation and hand off to **applier mode** (edit in place, or the export → author → applier rebuild path); this skill never edits. For unfamiliar node types whose config keys you do not recognize, read the matching component reference under `../../references/components/{type}.md` if available.

## What not to do

- **Don't do a systematic node-by-node pass by default.** Wait for the user's question unless they explicitly ask for a full walkthrough.
- **Don't inspect a pre-selected node unprompted.** Prior canvas state is not the user's current question.
- **Don't invent execution mode policy.** If the flow has not produced data and the user wants a preview, follow `run-modes.md`.
- **Don't modify the flow.** This is a read-only skill: no editing configs, no adding nodes, no saving.
- **Don't invent data.** If the inspected output shows N rows, report N rows. If you cannot tell why a filter produced 0 rows, say so and investigate upstream.
- **Don't paraphrase the config without looking at data when data matters.** The value of this skill is grounding explanations in real samples and row counts.
