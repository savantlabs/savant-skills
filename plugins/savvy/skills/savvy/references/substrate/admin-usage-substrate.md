# Admin Usage Substrate

## Objective

Use this to answer admin Usage Log questions across the admin-visible organization/workspace scope: workflows, owners, workspaces, runs, rows processed, connectors, and tokens.

## Use When

- The user asks for usage by workflow, owner, workspace, connector, date range, rows, runs, or tokens.
- The question is about aggregate usage, not the execution evidence for one specific workflow.

## Default Action

- Require `api_enabled: true`.
- Use the admin usage helper/API.
- State the checked date range and visible admin scope.
- Group and summarize only by fields present in the returned usage events/metrics.

## Do Not

- Do not use this as workflow run-history proof for one workflow; use `run-history-substrate.md`.
- Do not claim complete organization-wide usage unless the authenticated admin scope proves it.
- Do not infer cost from rows/tokens unless a separate billing source is provided.
- Do not bypass 401/403 or persist auth tokens, cookies, or request headers.

## Product model

The Usage Log page is admin-only and date-range driven. It shows:

- summary metrics: flow count, run count, processed row count, and token count when token consumption is enabled
- row-level usage events: run id, workflow name, owner, run type, started time in UTC, workspace, source connectors, destination connectors, processed rows, and tokens
- a CSV export for the selected date range

The page currently uses usage event type `bot_run` for workflow run usage.

## Confirmed app API endpoints

Before using admin usage APIs, resolve the snapshot path with `savant.py session tmp-path savant-capabilities.json`, read that file, and proceed only when `api_enabled: true`. If the snapshot is missing or stale for the current task, refresh it with `savant.py capabilities --output-path <resolved-capability-path>`. If `api_enabled` is false, say that live admin usage data is not available from this package/session and do not claim usage logs were checked.

Admin usage data comes from the endpoints below; they return the usage log directly when the session's account has admin access (the bound session carries that permission).

All three endpoints accept the same payload shape:

```json
{
  "timeRange": {
    "from": "2026-05-01",
    "to": "2026-05-31"
  },
  "eventType": "bot_run"
}
```

The app also sends full ISO date strings for the default current-month range. Date-only `YYYY-MM-DD` values match the visible picker behavior after a user changes the range.

Confirmed endpoints:

- `POST /api/usage-events/events/async` returns detailed usage events after promise polling.
- `POST /api/usage-events/metrics/async` returns aggregate metrics after promise polling.
- `POST /api/usage-events/csv/async` returns the CSV export data as event rows after promise polling; the browser builds the CSV client-side.

These endpoints are internal app APIs, not a public SDK contract. Treat them as proven for the current app generation, and verify again if responses stop matching the expected shape.

## Helper

The shared helper is:

```bash
savant.py usage admin \
  --from 2026-05-01 \
  --to 2026-05-31 \
  --events-output tmp/admin-usage/events.json \
  --metrics-output tmp/admin-usage/metrics.json \
  --csv-output tmp/admin-usage/usage_log.csv
```

The helper uses the bound session, polls the async promises, normalizes `totalTokens` as `inputTokens + outputTokens`, and writes only requested outputs.

## Expected event fields

Usage event rows commonly include:

- `executionId`
- `recipeName`
- `recipeOwner`
- `runType`: `scheduled`, `run_now`, or `test_run`
- `startedAt`
- `workspace`
- `srcConnectors`
- `dstConnectors`
- `processedRecords`
- `inputTokens`
- `outputTokens`
- `totalTokens`

The UI labels run types as:

- `scheduled` -> Scheduled
- `run_now` -> On demand
- `test_run` -> Test

## Expected metric fields

Metrics commonly include:

- `botCount`: distinct workflows shown as "Flows"
- `runCount`: runs
- `rowCount`: processed rows
- `inputTokens`
- `outputTokens`
- `totalTokens`

## Answering usage questions

When answering, always state the checked date range and scope available from the admin session. Use concrete numbers and groupings that match the user's question.

Good usage analyses include:

- top workflows by runs, processed rows, or tokens
- top owners by runs, processed rows, or tokens
- scheduled versus on-demand/test breakdown
- connector usage from source/destination connector arrays
- workspace-level usage when multiple workspaces appear in the event rows
- daily or weekly trends from `startedAt`

Do not infer billable cost from tokens or processed rows unless a separate billing/pricing source is provided. Say "usage volume" rather than "cost" unless cost data is available.

Do not claim complete organization-wide usage unless the admin session and selected page scope make that clear. Prefer:

> For the admin-visible usage log from May 1, 2026 through May 31, 2026, I found...

## Failure modes

- If the session is missing or a call returns 401, re-bind the toolchain with `bind-toolchain` (see SKILL.md auth) and retry.
- If the endpoints return 401/403, the current user likely lacks admin usage access; do not try to bypass permissions.
- If the response shape changes, record the mismatch and report it; do not fall back to UI scraping.
- Do not print, log, or persist auth tokens, cookies, or full request headers.
