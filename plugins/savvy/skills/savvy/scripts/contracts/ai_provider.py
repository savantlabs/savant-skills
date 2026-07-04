"""Shared AI-provider defaults for generated Savant AI steps."""

from __future__ import annotations

from typing import Any


DEFAULT_AI_PROVIDER_NAME = "Savant Anthropic"
DEFAULT_AI_PROVIDER_ID = "savant_anthropic"

# Savant-managed trial providers in fallback-preference order, used only when the
# workspace has no customer-created provider. These ids are platform-stable across
# environments (dev/QA/UAT/prod all expose the same `savant_*` ids).
TRIAL_PROVIDER_PREFERENCE = ("savant_anthropic", "savant_openai", "savant_gemini")


def provider_id_or_default(provider_id: Any = None) -> str:
    """Return a usable provider id, defaulting offline builds to Savant Anthropic.

    API-enabled workflows should still prefer the live workspace provider list:
    `list_ai_providers` ranks customer-created providers first, then the trial
    providers in `TRIAL_PROVIDER_PREFERENCE` order, and marks the recommended pick.
    This helper is the deterministic fallback for build-only/offline generation, so
    users do not have to supply an id by hand.
    """
    if provider_id is None:
        return DEFAULT_AI_PROVIDER_ID
    if isinstance(provider_id, str) and not provider_id.strip():
        return DEFAULT_AI_PROVIDER_ID
    if not isinstance(provider_id, str):
        raise ValueError("providerId must be a string.")
    return provider_id.strip()
