"""Caller-supplied inputs that used to be authenticated GETs.

v1 no longer reads workflows, datasets or AI providers over the app API. Each of those
reads has an MCP equivalent the caller already has, so the data arrives here as a file
the caller wrote from an MCP result rather than as a GET this toolchain makes itself:

| was                                  | now                                          |
|--------------------------------------|----------------------------------------------|
| `GET /api/recipes/{id}`              | `fetch savant://workflow/{flowId}`           |
| `GET /api/sources`                   | `search` with `types: ["source"]`            |
| `GET /api/connections/AIProviders`   | `search` with `types: ["ai_provider"]`       |

The workflow equivalence is verified, not assumed: a live QA comparison of
`fetch savant://workflow/{id}` against `GET /api/recipes/{id}` matched on top-level keys,
node keys and deep values. That is what lets the read-only routes drop API access entirely.

MCP `search` returns ids as `savant://{type}/{id}` URIs while node configs bind the bare
id, so `load_id_set` accepts either and normalizes to bare ids.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import SavantAppApiError


FETCH_HINT = (
    "Fetch it with the MCP `fetch` tool on savant://workflow/{flowId}, write the result to a "
    "JSON file, and pass that path."
)

_URI = re.compile(r"^savant://[a-z_]+/")


def _read_json(path: Path, flag: str) -> Any:
    if path is None:
        raise SavantAppApiError(f"{flag} is required.")
    if not path.exists() or not path.is_file():
        raise SavantAppApiError(f"{flag} file does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SavantAppApiError(f"{flag} is not valid JSON ({path}): {exc}") from exc


def load_recipe(path: Path, *, flag: str = "--workflow-json") -> dict[str, Any]:
    """An MCP-fetched workflow recipe. Raises with the fetch hint on anything unusable."""
    if path is None:
        raise SavantAppApiError(f"{flag} is required. {FETCH_HINT}")
    if not path.exists() or not path.is_file():
        raise SavantAppApiError(f"{flag} file does not exist: {path}. {FETCH_HINT}")
    recipe = _read_json(path, flag)
    if not isinstance(recipe, dict):
        raise SavantAppApiError(f"{flag} must contain a workflow JSON object: {path}. {FETCH_HINT}")
    if not isinstance(recipe.get("nodes"), list):
        raise SavantAppApiError(
            f"{flag} has no `nodes` array, so it is not a workflow recipe: {path}. {FETCH_HINT}"
        )
    return recipe


def assert_flow_id(recipe: dict[str, Any], expected: str | None, *, flag: str = "--workflow-json") -> None:
    """Refuse a recipe for a different flow than the one being operated on.

    Verifying the wrong file is the failure mode a caller-supplied recipe introduces that a
    self-issued GET could not have, so it is checked wherever a flow id is known.
    """
    actual = recipe.get("id")
    if expected and isinstance(actual, str) and actual and actual != expected:
        raise SavantAppApiError(
            f"{flag} holds flow `{actual}`, but the target flow is `{expected}`. Re-fetch the "
            "target workflow before continuing."
        )


def bare_id(value: Any) -> str | None:
    """`savant://source/abc` -> `abc`; a bare id passes through unchanged."""
    if not isinstance(value, str) or not value.strip():
        return None
    return _URI.sub("", value.strip()) or None


def _entries(payload: Any) -> list[Any]:
    """Rows out of an MCP `search` envelope, a bare list, or a single object."""
    if isinstance(payload, dict):
        for key in ("results", "hits", "slice", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return payload if isinstance(payload, list) else []


def load_id_set(path: Path | None, *, flag: str) -> set[str] | None:
    """Bare ids from an MCP `search` result file, or None when the caller passed no file.

    None means "the caller did not supply this list", which every consumer treats as
    `check unavailable` — never as `the workspace has none`. Conflating those would turn a
    missing file into a false blocker on every dataset or provider a workflow binds.
    """
    if path is None:
        return None
    ids = {
        found
        for entry in _entries(_read_json(path, flag))
        for found in (bare_id(entry if isinstance(entry, str) else (entry or {}).get("id")),)
        if found
    }
    if not ids:
        raise SavantAppApiError(
            f"{flag} contained no ids ({path}). Pass the MCP `search` result, or omit the flag "
            "to skip the check rather than passing an empty list."
        )
    return ids


def load_records(path: Path | None, *, flag: str) -> list[dict[str, Any]]:
    """Rows (with a normalized bare `id`) from an MCP `search` result file; [] when absent."""
    if path is None:
        return []
    records = []
    for entry in _entries(_read_json(path, flag)):
        if not isinstance(entry, dict):
            continue
        record = dict(entry)
        resolved = bare_id(entry.get("id"))
        if resolved:
            record["id"] = resolved
        records.append(record)
    return records
