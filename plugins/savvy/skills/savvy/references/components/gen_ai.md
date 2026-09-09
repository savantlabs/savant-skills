---
registry_summary: "Runs an AI prompt on row data and writes the model response to a new column called `AI Answer`."
---

# gen_ai (Infer)

## Business purpose

LLM inference on row data. For each row, sends a selection of fields to an LLM along with a prompt, and stores the LLM's response as a new column (typically JSON that a downstream `json` node flattens into real columns). This is how Savant workflows do things like "classify this invoice," "extract vendor name from this text," or "score this customer description against these criteria."

Not to be confused with Edit's Copilot mode (which generates the expression at author time). Gen_ai runs the LLM at execution time, once per row.

> **Cousin node type — `service` with `serviceType: "LLMService"`.** Some agentic flows do LLM inference via a `service` node configured in LLM mode rather than a `gen_ai` node. The two share `mode`, `type`, `prompt`, `rowLimit`, `connector`, `providerId`, and `serviceType: "LLMService"`. The user-visible difference is that `gen_ai` takes `inputFields` (an array, plural) while LLM-mode service takes `inputField` (a single string). When inspecting an unfamiliar agentic flow, check the outer `type` and `config.serviceType` to know which file to consult — see `service.md` → "LLM mode" for the service-side shape.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/gen_ai.json`. This file focuses on behavior, writing, and gotchas.

## Building a gen_ai (use node_builders)

Do not hand-author gen_ai JSON. `../scripts/workflow/builders.py` owns the shape:

```python
f.add(nb.gen_ai("Classify", prompt, input_fields=["Description", "Vendor"],
                provider_id="savant_anthropic",
                row_limit=1000))
```

Verified facts the builder encodes:

- **`providerId` defaults to Savant Anthropic (`savant_anthropic`) when omitted.** When API access is available, resolve the live workspace provider per `../substrate/ai-provider-substrate.md` and ask only if there are multiple providers. Without API, the builder uses `savant_anthropic` instead of asking the user. Do **not** use the legacy unified id `savant-ai-provider-gzilpzflks` here — the canvas migrates gen_ai nodes off it on load, and the per-vendor ids are what the picker shows. (`fuzzy_match` is the exception: it *requires* the legacy id. See `fuzzy_match.md`.) Any unresolvable provider id is **SILENTLY DROPPED on import** — Savant removes the whole node, so the created flow comes back one node short with the downstream consumer left dangling, and no import error.
- Config is emitted as `mode: "BATCH"`, `serviceType: "LLMService"`, and `rowLimit` as an **int** (the current UI's "Max New Rows Processed per Run", default 1000; it's a cap in upstream order — one LLM call per row — NOT the prompt-size limit). The same shape applies to a `service` node's `rowLimit` in LLM mode.
- `inputFields` is plural (array). It must reference real upstream columns — **typos are silently dropped** (the LLM just sees the other fields), so verify against the upstream preview.
- The output column name is product-determined (not author-controllable); downstream nodes key off the well-known name. Downstream parsing assumes the LLM response matches the schema in `prompt` — if the prompt doesn't specify a structure, downstream `json` flattens fail.
- **No `type`/`connector` in config.** The builder omits them on purpose: the connector is resolved from `providerId` at import. Never copy `type`/`connector` from an existing workflow export into a gen_ai config — a literal connector that doesn't match the provider **silently drops the whole node on import**. The validator now errors on these keys before import.

## API edit support

### Supported

**Display-name rename** via the generic API recipe diff. **Config edits — prompt, `inputFields`, provider, and `rowLimit`** — are supported through the deterministic regenerate-and-merge path: `gen_ai_update(existing_node, ...)` regenerates the config (defaulting a missing provider to Savant Trial) and merges it onto the live node, preserving id, wiring, and any unmodeled fields. Settings-panel probes are not the mutation path; use the library plus the normal snapshot → diff → confirm → save → re-fetch loop. The **paid-run verification caveat below still governs** — config regeneration is free and deterministic, but confirming the *result* costs money, so surface that and get a run-mode decision before any verification run.

### Verification caveat — previews cost money

Prompt / `inputFields` / provider edits trigger LLM re-runs on the next live execution. For routine prompt touch-ups the cost is bounded by the `rowLimit` (default 1000), but bulk experimentation on gen_ai is expensive in a way that filter edits are not. The editor should surface this to the user before any rebuild or verification that would trigger a re-run; reading cached preview results is not proof because the prompt change invalidates the cache.

## Gotchas

- **Gen_ai previews cost money.** Every row triggers an LLM call against the configured provider. Don't re-run previews casually.
- **Prompt changes require a full re-run for verification.** Unlike filter or edit, where Apply refreshes the preview from cached upstream data, gen_ai requires a new LLM call per row. The preview delta is not a cheap verification step for this node.
- **Unresolved providers are dropped on import.** A node carrying any `providerId` that doesn't resolve in the target workspace is silently removed during import; the canvas does NOT swap it in. Real exports always carry a resolved id (e.g. `savant_anthropic`, or a workspace's own connection id). Use the live provider when available; otherwise use the `savant_anthropic` default per `../substrate/ai-provider-substrate.md`. If you inspect a flow and a gen_ai node is unexpectedly absent right after creation, an unresolved provider on import is the first thing to check.
- **One row in, one row out.** Row count does not change through gen_ai; the effect is a new output column carrying the LLM's response (a raw string, or JSON if the prompt requested structure).
- **Schema drift between prompt and downstream json.** The most common bug on gen_ai nodes is a prompt that asks for one schema and a downstream `json` node that expects another. When a `json` node follows, read both outputs together — the gen_ai raw response and the post-flatten columns. If the flatten produces null columns for values clearly present in the raw string, the prompt's output schema is out of sync with the `json` node's expectations.
- **`inputFields` typos are silent.** A misspelled column name in `inputFields` is dropped without error; the LLM just sees the other fields. Verify names against the upstream preview.
