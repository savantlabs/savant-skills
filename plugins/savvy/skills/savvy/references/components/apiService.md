---
registry_summary: "External HTTP API calls, normally one request per incoming row."
---

# apiService (API)

## Business purpose

External HTTP API calls, normally one request per incoming row. URL, headers, and body can include templated values from upstream columns or workflow parameters, so common uses are "look up each customer id," "submit each order to an endpoint," or "pull detail records for each source row." The response is added to the row for downstream parsing, usually by a `json` node.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/apiService.json`. This file focuses on behavior and gotchas.

## Building an apiService (use node_builders)

Do not hand-author apiService JSON. `../scripts/workflow/builders.py` owns the **basic shape**:

```python
f.add(nb.api_service("Lookup Customer", url="https://api.example.com/customers/{{CustomerId}}",
                     method="GET", result_format="JSON"))
```

This is the basic shape only — it emits `serviceType: "APIService"` with `apiServiceConfig.{url, method, resultFormat}`. **Bind real auth / headers / body / rate-limiting / pagination in Savant** after import; the builder does not author those. `{{FieldName}}` templates reference upstream columns and `{{Parameter Name}}` templates reference flow-level parameters (use parameters for credentials — never hardcode secrets). Failed requests come back as data in the response columns, not as an auto-dropping branch.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, api_service("x", url, method, result_format)["config"])`. Real auth/connection binding is environment-specific (done in Savant), not a recipe edit; the response shape can change, so reconcile any downstream `json`-flatten columns.

## Gotchas

- **Row count usually stays the same.** One incoming row produces one outgoing row with request/response metadata and the response body. A `json` node often follows the API node to flatten the response into useful columns.
- **Current palette name differs from legacy JSON names.** The app shows **API**; the current type string is `apiService`. Legacy recipe JSON may still use `service` plus `serviceType: "APIService"`; treat that as an alias only when reading existing workflows, not when generating new ones.
- **Template substitution is not URL-aware.** If a templated field contains spaces, slashes, question marks, or ampersands, encode it upstream before inserting it into a URL.
- **Previewing can hit the real endpoint.** Use row limits and rate limits when the endpoint has side effects, quotas, or cost.
- **Do not hardcode secrets.** Use workflow parameters for API keys and tokens rather than putting them directly in URLs, headers, or bodies.
