from __future__ import annotations

from typing import Any

from contracts.ai_provider import TRIAL_PROVIDER_PREFERENCE

from .httpclient import request
from .models import SavantAppApiError, SavantSessionContext


def _ai_provider_kind(provider: dict[str, Any]) -> str:
    """`customer` for a workspace-created provider, else `trial`.

    Customer-created providers carry an `owner`/`createdBy` (and a `connector`);
    Savant-managed trial providers come back as the sparse `{id, name}` shape with a
    stable `savant_*` id.
    """
    return "customer" if (provider.get("owner") or provider.get("createdBy")) else "trial"


def _rank_ai_providers(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort customer-created providers first, then trial providers in
    `TRIAL_PROVIDER_PREFERENCE` order, tagging each with `kind` and a single
    `recommended` default.

    The recommendation follows the skill's selection rule: exactly one customer
    provider -> recommend it; several -> leave none recommended so the agent asks
    which to use; none -> recommend the top trial provider by preference.
    """
    customer = [p for p in providers if _ai_provider_kind(p) == "customer"]
    trial = [p for p in providers if _ai_provider_kind(p) == "trial"]

    def trial_rank(provider: dict[str, Any]) -> int:
        try:
            return TRIAL_PROVIDER_PREFERENCE.index(provider.get("id"))
        except ValueError:
            return len(TRIAL_PROVIDER_PREFERENCE)

    trial.sort(key=trial_rank)
    ranked = customer + trial
    for provider in ranked:
        provider["kind"] = _ai_provider_kind(provider)
        provider["recommended"] = False
    if len(customer) == 1:
        customer[0]["recommended"] = True
    elif not customer and trial:
        trial[0]["recommended"] = True
    return ranked


def list_ai_providers(context: SavantSessionContext) -> list[dict[str, Any]]:
    """Return the AI/LLM providers configured in the session's workspace, ranked.

    Each entry is tagged with `kind` (`customer`/`trial`) and `recommended` (the
    single default pick). Customer-created providers carry full detail
    (`connector`, `owner`, `namespace`, `status`, …); Savant-managed trial providers
    come back as `{id, name}` with stable `savant_*` ids (`savant_anthropic`,
    `savant_openai`, `savant_gemini`). Results are ordered customer-first, then trial
    in anthropic > openai > gemini preference. `gen_ai`/`vision`/LLM-`service` nodes
    bind to one of these ids via `config.providerId`; an unresolved id is silently
    dropped on import.
    """
    response = request(context, "/api/connections/AIProviders?showAll=true")
    providers = response.get("slice") if isinstance(response, dict) else response
    if not isinstance(providers, list):
        raise SavantAppApiError("GET /api/connections/AIProviders did not return a provider array.")
    return _rank_ai_providers([item for item in providers if isinstance(item, dict)])

