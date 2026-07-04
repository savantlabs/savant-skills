# AI Provider Substrate

## Objective

Use this to resolve a real AI provider id before importing or editing AI-backed nodes.

## Use When

- A workflow contains `gen_ai`, `vision`, `fuzzy_match`, or LLM-mode `service`.
- Builder/Creator/Editor needs a `providerId`.
- Validation reports a missing provider.

## Default Action

With `api_enabled`, list providers via `--list-ai-providers` and pick by this rule (the
toolchain already ranks the list and marks the `recommended` pick):

- **Customer-created providers win.** A provider the workspace created carries `kind: "customer"`
  (it has an `owner`/`connector`). If there is exactly one, use it. If there are several, **ask
  which** by display name (same discipline as ambiguous datasets/systems) — don't guess.
- **Otherwise fall back to a Savant trial provider**, in preference order
  **`savant_anthropic` > `savant_openai` > `savant_gemini`**. The trial providers come back as the
  sparse `{id, name}` shape (`kind: "trial"`) with these stable `savant_*` ids.
- **Without API (offline/build-only), default to `savant_anthropic`.** Do not ask the user for this
  standard id.
- If the API returns no providers at all, use `savant_anthropic` only for offline/build-only JSON.
  For a live import/edit in that workspace, treat the absence as a workspace setup issue and do not
  claim the AI step was verified.

## Do Not

- Do not guess a provider id from name alone.
- Do not ignore a missing provider because validation still passes structurally.

**Why this matters.** Any `providerId` that doesn't resolve in the target workspace is **silently dropped on import**: Savant removes the whole node, the created flow comes back one node short, the downstream consumer is left dangling, and there is no import error. The only signal is a node-count mismatch against the source JSON. So a real `providerId` is mandatory before import. In offline/build-only mode, `savant_anthropic` is the deterministic default. Bind AI nodes by `providerId` **only** — don't set a `connector`/`type` on the node (Savant resolves the connector from `providerId`; a literal connector that doesn't match is itself a cause of the silent drop).

## How do I get the provider name + id?

```bash
python3 ../scripts/savant.py app <reference-flow-or-folder-url> --list-ai-providers
```

GETs `/api/connections/AIProviders` and returns the providers **ranked** — customer-created first, then trial in `savant_anthropic` > `savant_openai` > `savant_gemini` order — each tagged with `kind` (`customer`/`trial`) and a single `recommended` default. Take the `recommended` entry; if several customer providers exist none is marked, so ask which to use. It's **token-only** (no workspace/tab session needed), so it runs headless. An empty list means AI isn't enabled in that workspace for live verification — tell the user before import/edit verification. For offline/build-only JSON, use `savant_anthropic` instead of asking the user for an id.

## Enforcement

`savant.py validate workflow` requires a `providerId` on every AI node — missing/empty is a hard error. `node_builders` defaults missing AI provider ids to `savant_anthropic`. Builder resolves a live provider when API access exists (preferring a customer provider, else the trial preference order); Creator confirms the node survived after import — an AI-node shortfall is the signature of an unresolved provider.
