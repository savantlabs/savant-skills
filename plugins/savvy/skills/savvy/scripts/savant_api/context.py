"""AI provider resolution notes.

`GET /api/connections/AIProviders` and the local `_rank_ai_providers` ranking that wrapped it are
gone. The MCP `search` tool with `types: ["ai_provider"]` replaces both, and does the harder half
better:

- **The customer/trial split is enforced server-side, as mutual exclusion.** `AiProviderStore`
  returns Savant-managed providers ONLY when the workspace has no bring-your-own-key provider at
  all. The old endpoint returned both sets concatenated and left this toolchain to sort them and
  mark a `recommended` pick, so a trial provider could be chosen in a workspace that had its own
  keys.
- **Its scope is wider, which fixes a real gap.** The store reads the bound namespace *and* the
  organization namespace; the endpoint read the bound namespace only, so an org-shared AI key was
  invisible to the skill. savant-api records the endpoint's narrower scope as a defect, not as
  behavior to preserve.

The selection rule itself (`references/substrate/ai-provider-substrate.md`) needs no ranking code:
one customer provider means use it, several means ask the user, none means the zero state — where
the managed providers come back name-ordered and `Savant Anthropic` leads either way. The
deterministic offline default stays in `contracts/ai_provider.py`.

Preflight checks that need the set of resolvable provider ids take it as `--providers-json`, the
MCP `search` result written to a file. `savant_api.recipe_input.load_id_set` normalizes the
`savant://ai_provider/{id}` URIs to the bare ids node configs bind.
"""
from __future__ import annotations
