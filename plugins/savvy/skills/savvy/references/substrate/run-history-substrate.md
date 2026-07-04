# Run History Substrate

## Objective

Use this to answer whether a workflow was actually tested or run, whether a past execution succeeded or failed, or what happened during a specific execution.

## Use When

- The user asks whether a workflow ran, tested, succeeded, failed, or was scheduled.
- A status/debug answer needs execution-history evidence.
- A workflow has Analyze evidence but the user is asking about full Run/Test history.

## Default Action

- Check workflow-specific Run/Test history through the API helper when `api_enabled` is true.
- Report the exact history surface checked, time range when known, and execution type found.
- If no matching history is found, say no matching Run/Test history was found in the checked scope.

## Do Not

- Do not infer Run/Test history from recipe existence, import status, canvas rendering, or Analyze preview.
- Do not say "never ran" unless the complete relevant history range is known and checked.
- Do not trigger Analyze/Test/Run from this substrate; use `run-modes.md`.

## Product model

Savant separates execution history into two surfaces:

- **Runs:** Full workflow executions. These can write outputs, send emails, update destination systems, call output APIs, or perform any other configured destination side effect.
- **Tests:** Test executions. These read source data and execute the process without destination side effects.

Each workflow can have both run history and test history. History is workspace-specific and should be checked in the same workspace as the workflow.

## What Counts As Evidence

A workflow's recipe, import status, canvas rendering, or Analyze preview does not prove the workflow had a full Run or Test.

Execution evidence should come from Run History or Test History and include as many of these fields as available:

- type: `run` or `test`
- run/test id
- workflow name
- workflow id, if available
- version
- submitter
- phase or status
- progress
- started time
- finished time
- duration
- output or error details, if the expanded record exposes them

When a user asks "did this workflow run?", distinguish:

- full Run history found
- Test history found
- Analyze/preview evidence found, but no Run/Test history checked or found
- no matching Run/Test history found in the checked workspace/time range

Do not say "this workflow never ran" unless the complete relevant history range is known and checked. Prefer:

> I did not find a matching full run in the workspace history I checked.

## Accessing Run/Test history

Before using Run/Test history APIs, resolve the snapshot path with `savant.py session tmp-path savant-capabilities.json`, read that file, and proceed only when `api_enabled: true`. If the snapshot is missing or stale for the current task, refresh it with `savant.py capabilities --output-path <resolved-capability-path>`. If `api_enabled` is false, answer only from local/exported evidence and state that live Run/Test history was not checked.

Run/Test history comes from the executions API helper — the confirmed endpoints below.

Confirmed app API endpoints:

- `GET /api/recipes/{flowId}/executions?types=run_now,scheduled,test_run` lists execution history for one workflow.
- `GET /api/recipes/{flowId}/executions?types=run_now,scheduled` lists full Run-style executions for one workflow.
- `GET /api/recipes/{flowId}/executions?types=test_run` lists Test executions for one workflow.
- `GET /api/executions/{executionId}` is the app's execution-detail endpoint. Treat it as best-effort until it is proven in the current workspace/session; workflow-specific execution lists are the reliable first evidence source.

The shared helper `savant.py app` owns the API path:

```bash
savant.py app "{flowUrl}" --list-executions --execution-types run,test --output-path "{outputPath}"
```

The helper supports:

- listing full runs and tests for a workflow
- filtering by workflow id from the flow URL
- filtering execution type with `run`, `test`, `scheduled`, `run_now`, and `test_run`
- best-effort fetching of details for a specific run/test id
- normalizing the result before skill use

Future helper work may add workspace-wide list filters by workflow name, date range, status/phase, submitter, and version. Until those are proven, prefer workflow-specific history by flow URL.

Normalize results before passing them back to skills:

```json
{
  "type": "run",
  "id": "run_id",
  "workflowName": "Workflow name",
  "workflowId": "flow_id_if_available",
  "version": "v1",
  "submitter": "name_or_id_if_available",
  "status": "Succeeded",
  "progress": "100%",
  "startedAt": "2026-05-11T09:00:00-07:00",
  "finishedAt": "2026-05-11T09:01:00-07:00",
  "duration": "1 m 1 s",
  "details": {}
}
```

If workflow-specific API lookup fails, say that run-history API lookup could not be completed safely and stop.

## Business-user Response Patterns

When history is found:

> I found a successful full run for `Send Report from a Database`. It started May 11, 2026 at 9:00 AM, finished at 9:01 AM, and took 1 minute 1 second.

When only test history is found:

> I found test history for this workflow, but I did not find a matching full run in the checked workspace history.

When no matching history is found:

> I did not find a matching run or test entry in the workspace history I checked. That means I cannot confirm it was executed from history evidence.

When Analyze evidence exists but no Run/Test evidence:

> I can confirm the workflow produced preview results in Analyze mode, but I do not see Run/Test history evidence from the checked history source.

## Skill Coordination

- **Creator:** use run history only when the delivery claim depends on full Run/Test evidence. Analyze validation alone should be described as Analyze validation.
- **Inspector:** use run history when debugging depends on whether a workflow has actually executed, whether a specific run failed, or whether outputs should exist.
- **Downloader:** run history can support a business summary only when the user asks about execution evidence; JSON export alone is not execution evidence.
- **Support:** include relevant run/test history in support notes when the issue concerns execution failures, missing outputs, or unexpected results.
