# Savant Q&A (q-and-a mode)

> **When this mode applies:** general Savant product/usage questions that are not primarily requests to build, create, inspect, edit, or export a specific workflow — "what is Savant?", "what is a dataset/system/folder/workspace?", "what does this tool/step mean?", "how do people use Savant?", "what is Analyze mode?", or conceptual questions about Savant objects, workflow steps, source data, systems, datasets, and common use cases. Also covers admin Usage Log questions (usage by workflow, owner, workspace, connector, rows, runs, tokens).

## Goal

The job of Q&A is to answer general Savant product and usage questions in plain business language — orientation and explanation, not changes. The user should come away understanding the concept, why it matters in Savant, and (when useful) one concrete example.

This is the **generic-knowledge** skill: it answers conceptual questions that have no specific flow target. When the user points at a specific flow URL, or wants to build/create/edit something, route to the matching workflow skill (see Boundaries).

## Q&A Procedure

Use this numbered checklist before any reference lookup:

1. **Pre-check the question.** Decide whether this is conceptual Q&A or an action that belongs to a workflow skill; if live Savant state matters, gate on `api_enabled`.
2. **Identify the needed reference.** Load only the specific component, substrate, run-mode, usage, or layout reference the question needs.
3. **Answer in business terms.** Define the concept, why it matters, workspace/data impact when relevant, and one example when it clarifies.
4. **Route actions.** If the question turns into build/create/export/inspect/edit, switch to the matching skill before acting.

## Before answering

`savant.py ...` is shorthand for the bundled toolchain; the parent `SKILL.md` Toolchain section explains how to locate and run it.

Read these shared references first:

- User-facing replies follow the shared business-user response rules loaded at session start.
- `../../references/substrate/savant-context.md` for core objects and relationships.

For any answer that depends on live Savant data (folder contents, workflow recipe, run/test history, admin usage logs, datasets, systems, or workspace-specific availability), resolve the snapshot path with `savant.py session tmp-path savant-capabilities.json`, read that file, and use `api_enabled` as the gate. If it is missing, refresh it with `savant.py capabilities --output-path <resolved-capability-path>`. If `api_enabled` is false, answer only from local/shared docs or ask the user for the missing exported/context data; do not claim live Savant state was checked.

When live state is needed, the chat client mints credentials the same way the other live skills do — call the **`get-api-credentials`** MCP tool and supply the result to `savant.py` via the `SAVANT_API_TOKEN` / `SAVANT_API_TAB` / `SAVANT_API_BASE_URL` environment variables, for this session only (see any live skill's Authentication section). Most Q&A answers are conceptual and need no credentials at all; only the admin Usage Log path and "check live state" answers do.

Run the Q&A intake checkpoint before answering when the question depends on a specific Savant object, scope, time range, URL, workspace, folder, workflow, dataset, run history, or usage-log context. Write the checkpoint to a path from `savant.py session tmp-path <task-name> q_and_a_intake_checkpoint.json` and run `savant.py validate stage --role q_and_a --gate precheck <checkpoint>`. Use `task_type: "q_and_a_intake_checkpoint"`. First run `stage: "questions_needed"` to record `open_questions` and `ready_for_questions: true`. After the user answers, run `stage: "ready"` with required answers in `answered_questions`, optional unresolved items in `deferred_questions`, and `ready_for_stage: true`. Required context questions block the answer or force a narrower answer.

Then load only the specific extra reference needed:

- For a question about a workflow step/tool type, start with `../../references/components/_index.md`, then read the specific component file such as `filter.md`, `edit.md`, `blend.md`, `summarize.md`, `destination.md`, `source.md`, `gen_ai.md`, or `vision.md`.
- For Analyze/Test/Run questions, read `../../references/substrate/run-modes.md`.
- For Run History, Test History, schedule-history, "did it run?", or "what happened when it ran?" questions, read `../../references/substrate/run-history-substrate.md`.
- For admin-only usage-log questions, read `../../references/substrate/admin-usage-substrate.md`.
- For questions about datasets, connected systems, workspace availability, or source binding, read `../../references/substrate/dataset-substrate.md`.
- For questions about workflow diagrams, groups, readability, or layout, read `../../references/standards/canvas-layout-rules.md`.
- For questions about inspecting live workflow results, read `../../references/standards/workflow-inspection-rules.md`.

## External references

Use local shared docs first for stable Savant concepts, current component behavior, and project-specific workflow behavior. Use external Savant references when the user asks for current product documentation, connector setup, templates, broader product usage examples, or recent release information.

- **Component definitions:** `../../references/components/` and `../../references/registry/` are the source of truth for supported workflow component behavior in this skill. If Help Center wording conflicts with local component definitions, compare update dates and prefer the newest reliable source. If dates are unclear, prefer the local component definitions for workflow behavior and note that Help Center may describe older UI/product language.
- **Savant Help Center:** `https://help.savantlabs.io/en/` is the official help and onboarding reference. Use it for product walkthroughs, agents/functions, connector setup, templates, "how do I..." questions, and "what's new" / latest-release questions. Cite the relevant Help Center URL when you use it.
- **Savant Community:** `https://app.savantlabs.io/en/app/community` is an in-app, authenticated community/templates surface. Use it only when accessible in the user's session and when the user asks about examples, templates, or how people use Savant. Treat it as usage inspiration, not the source of truth for product behavior.

Do not block a general Q&A answer on Community access. If Community is not accessible, answer from local docs and the Help Center, and say that Community examples were not checked only when that limitation matters.

For "latest", "current", "new release", "what's new", or similar time-sensitive questions, check the Help Center release/update pages and compare article dates against local docs or known component-definition dates where available. Be explicit about the date of the release information you used. Do not answer latest-release questions from memory.

## Boundaries

- If the user asks to build a new workflow or turn a process/files into a Savant flow, use **author mode**.
- If the user asks to create/import/upload a workflow JSON into Savant, or to edit/change an existing flow, use **applier mode**.
- If the user provides a flow URL and asks what it does overall, or to export/download its JSON, use **inspect mode** (its zoomed-out "explain & export" mode).
- If the user provides a flow URL and asks about live behavior, row counts, previews, errors, or a specific step, use **inspect mode**.
- If the user provides a flow URL and asks whether it ran, tested, scheduled, succeeded, failed, or produced outputs from execution history, use **inspect mode**.
- If an admin user asks about Usage Log data across workflows, owners, workspaces, connectors, rows, runs, or tokens, stay in this Q&A skill and use the admin usage substrate.

If a question starts conceptual but clearly turns into an action request, switch to the appropriate workflow skill before acting.

## Answer shape

Keep answers short and practical:

1. Define the concept in business terms.
2. Explain why it matters in Savant.
3. Mention workspace/data impact when relevant.
4. Give one concrete example when it improves clarity.

Avoid implementation terms by default. Prefer "step" over "node", "process" over "workflow" when explaining business work, and "output" over "destination" unless the user is asking about the app UI.

## Definition of done

A Q&A answer is done when it's concise, in business language, and grounded in the right reference. Claim live Savant state only when `api_enabled` was true and the data was actually checked — otherwise answer from local/shared docs and say what wasn't checked. For "latest / what's new / current release" questions, base the answer on dated Help Center content, not memory, and state the date. If the question turned into an action (build / create / edit / inspect / export), hand off to that skill rather than answering as if it were conceptual.

## Common explanations

- **Savant:** A platform for turning repeatable data work into automated business processes: bring in data, clean it, match it, calculate results, flag exceptions, and deliver outputs.
- **Workspace:** The user's current work area. Systems, datasets, folders, workflows, permissions, and run history are specific to that workspace.
- **System:** A connected source or destination available in the current workspace, such as Snowflake, SharePoint, S3, Google Drive, SFTP, or an API.
- **Dataset:** A reusable input. It can be an uploaded/static file or come from a connected system. One dataset can be used by multiple workflows.
- **Workflow / process:** The saved Savant process that connects inputs, cleanup, matching, calculations, reviews, and outputs.
- **Step/tool:** One action inside the process, such as filtering rows, transforming fields, matching records, summarizing totals, or writing an output.
