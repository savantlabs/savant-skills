"""Shared AI-provider defaults for generated Savant AI steps."""

from __future__ import annotations

from typing import Any


DEFAULT_AI_PROVIDER_NAME = "Savant Anthropic"
DEFAULT_AI_PROVIDER_ID = "savant_anthropic"

# Savant-managed trial providers in fallback-preference order, used only when the
# workspace has no customer-created provider. These ids are platform-stable across
# environments (dev/QA/UAT/prod all expose the same `savant_*` ids).
TRIAL_PROVIDER_PREFERENCE = ("savant_anthropic", "savant_openai", "savant_gemini")

# The legacy unified provider. Deprecated for the per-vendor ids above — but
# `@Deprecated(forRemoval = false)`, retained deliberately, and **required for fuzzy_match**.
#
# `fuzzy_match` is the Fuse agent, and the Canvas Fuse picker (`useLLMProviders`, agentType
# "fuse") builds its list as exactly this id plus the workspace's own openai-connector
# providers, filtering every per-vendor Savant id out of the second half. A Fuse node bound to
# `savant_anthropic` therefore matches nothing in that list, and `isSelectionInvalid` fires —
# it exempts only this id. `migrateLegacyProviderIds` skips `fuzzy_match`, so nothing repairs it
# after the fact. Vision and Infer nodes ARE migrated off this id on canvas load, which is why
# they should use the per-vendor default instead.
FUSE_DEFAULT_AI_PROVIDER_ID = "savant-ai-provider-gzilpzflks"
FUSE_DEFAULT_AI_PROVIDER_NAME = "Savant Service"

# Every platform-managed id, across both the per-vendor and legacy sets. These are NOT
# workspace-scoped: they resolve in any workspace, so they can never be "unresolved here".
# Kept separate from what MCP `search` returns, which lists the managed providers only when the
# workspace has no key of its own — treating that listing as the whole truth would flag a
# builder-default AI node as unresolvable in every workspace that has its own keys.
SAVANT_MANAGED_PROVIDER_IDS = frozenset(TRIAL_PROVIDER_PREFERENCE) | {FUSE_DEFAULT_AI_PROVIDER_ID}


def fuse_provider_id_or_default(provider_id: Any = None) -> str:
    """Like `provider_id_or_default`, but defaults to the Fuse-compatible id.

    Separate because the Fuse picker rejects the per-vendor Savant ids — see
    `FUSE_DEFAULT_AI_PROVIDER_ID`. Do not "simplify" this back to the shared default.
    """
    if provider_id is None or (isinstance(provider_id, str) and not provider_id.strip()):
        return FUSE_DEFAULT_AI_PROVIDER_ID
    if not isinstance(provider_id, str):
        raise ValueError("providerId must be a string.")
    return provider_id.strip()


def provider_id_or_default(provider_id: Any = None) -> str:
    """Return a usable provider id, defaulting offline builds to Savant Anthropic.

    For `fuzzy_match`/Fuse nodes use `fuse_provider_id_or_default` instead.

    Live workflows should still prefer a real workspace provider: MCP `search` with
    `types: ["ai_provider"]` returns the workspace's own keys when it has any, and the
    Savant-managed providers only when it has none, so there is nothing to rank — see
    `references/substrate/ai-provider-substrate.md` for the selection rule. This helper is
    the deterministic fallback for build-only/offline generation, so users do not have to
    supply an id by hand. `TRIAL_PROVIDER_PREFERENCE` remains the tie-break order for the
    Savant-managed set.
    """
    if provider_id is None:
        return DEFAULT_AI_PROVIDER_ID
    if isinstance(provider_id, str) and not provider_id.strip():
        return DEFAULT_AI_PROVIDER_ID
    if not isinstance(provider_id, str):
        raise ValueError("providerId must be a string.")
    return provider_id.strip()
