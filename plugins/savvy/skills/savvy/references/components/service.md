---
registry_summary: "Legacy service node for existing API or AI-service flows; prefer apiService or gen_ai for new workflows."
---

# service (API)

## Business purpose

`service` is the legacy node type with **two modes**, distinguished by `config.serviceType`:

- `serviceType: "APIService"` — external HTTP API calls. This is the same node as the current **`apiService`** type; for HTTP behavior, invariants, canvas recipe, and gotchas read **`apiService.md`**. When *generating* new flows use `apiService`; treat `service` + `serviceType:"APIService"` as a read-only legacy alias.
- `serviceType: "LLMService"` — LLM inference, parallel to `gen_ai` (see below).

Both modes render with `react-flow__node-service` on the canvas; `serviceType` is the only way to tell them apart from the JSON, so inspectors/editors must branch on it before assuming a config shape.

## LLM mode (`serviceType: "LLMService"`)

This mode is **nearly identical to `gen_ai`** — read `gen_ai.md` for prompt semantics, schema-drift gotchas, downstream `json` flattening, and the paid-run verification caveat. Two differences:

- Outer `type` is `"service"`, not `"gen_ai"`.
- The input column field is `inputField` (singular) rather than `inputFields` (array) — LLM-mode service is a **single-column** call; `gen_ai` supports multi-column context.

Config edits use the shared regenerate-and-merge path (`update_config(...)`); there is no dedicated `service_config` builder yet, so preserve the `type: "service"` envelope and singular `inputField` (don't reshape it into gen_ai's `inputFields` array). Verifying a prompt change triggers a paid LLM run — get a run-mode decision first. For new LLM generation, prefer `gen_ai` unless a live/export-backed requirement proves `service` is required.

Both modes coexist in current flows (e.g. `R&D Tax Credit Agent` uses LLM-mode service); the product distinction from `gen_ai` isn't documented — treat both as valid LLM paths.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/service.json`. No dedicated `service` constructor exists. For new HTTP API calls, generate `apiService`; for existing `service` nodes, preserve the legacy/LLM envelope and edit only documented fields.
