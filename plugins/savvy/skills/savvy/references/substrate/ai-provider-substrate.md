# AI Provider Substrate

## Objective

Use this to resolve a real AI provider id before importing or editing AI-backed nodes.

## Use When

- A workflow contains `gen_ai`, `vision`, `fuzzy_match`, or LLM-mode `service`.
- Builder/Creator/Editor needs a `providerId`.
- Validation reports a missing provider.

## Default Action

List providers with MCP `search`, `types: ["ai_provider"]`, and pick by this rule. **The store
already did the hard part**: it returns bring-your-own-key (BYOK) providers when the workspace has
any, and Savant-managed ones *only* when it has none. The two sets never arrive mixed, so there is
nothing to rank — just count what came back.

- **BYOK providers win, and they are what you get.** If exactly one came back, use it. If several,
  **ask which** by display name (same discipline as ambiguous datasets/systems) — don't guess.
- **Savant-managed providers appearing at all means the workspace has no key of its own.** Take
  **`savant_anthropic`** ("Savant Anthropic"); the platform-stable alternatives are
  `savant_openai` and `savant_gemini`. Seeing these is not "no AI access" — it means "this account
  has not connected its own AI keys yet".
- Results are scoped to the workspace **and its organization**, so an org-shared key is included.
  Bind the bare id, not the `savant://ai_provider/{id}` URI.
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

MCP `search` with `types: ["ai_provider"]` (the type must be named explicitly — this type is
excluded from untyped searches, so a bare query returns none of it). Each hit's summary states the
connector, the status, and whether it is Savant-managed or org-shared.

There is no CLI route for this any more, and no ranking step: `--list-ai-providers` and its
`recommended` tag are gone. Apply the rule above to what `search` returns. An empty result means
AI is not available in that workspace for live verification — tell the user before import/edit
verification. For offline/build-only JSON, use `savant_anthropic` instead of asking the user
for an id.

**Feeding the preflight.** `workflow create` and `workflow edit --replace-from-build` can check
every bound `providerId` against the workspace before writing — an unresolvable one gets the whole
node silently dropped on import. Write the `search` result to a file and pass it:

```bash
python3 ../scripts/savant.py workflow create --import-json <flow.json> --folder-id <id> \
  --confirmed-namespace <ns> --providers-json <providers.json>
```

Omitting `--providers-json` skips the check rather than failing it — so pass it whenever the
workflow has an AI node.

## Enforcement

`savant.py validate workflow` requires a `providerId` on every AI node — missing/empty is a hard error. `node_builders` defaults missing AI provider ids to `savant_anthropic`. Builder resolves a live provider when API access exists (preferring a customer provider, else the trial preference order); Creator confirms the node survived after import — an AI-node shortfall is the signature of an unresolved provider.
