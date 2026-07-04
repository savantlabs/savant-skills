from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fileio import workspace_tmp
from .models import DEFAULT_ORIGIN, FlowUrl, SavantAppApiError, SavantSessionContext, SavantUrl


# Default creds-file name under the session tmp dir. The chat client (the only MCP
# speaker) calls `get-api-credentials` and writes the minted bridge token here; this
# shell process reads it. `SAVANT_CREDS_FILE` overrides the path. See
# `context/architecture/skill-api-migration.md`.
CREDS_FILE_NAME = "savant-creds.json"


# --- Browser-spec compatibility surface -------------------------------------------------
#
# The old session resolver scraped the browser's localStorage (LevelDB) to lift the
# logged-in token. That dependency is gone: the chat client now mints a bridge token over
# MCP and hands it to us via a creds file. These types remain only so the `--browser` CLI
# flag still parses; they no longer select a real code path. See
# `context/architecture/skill-api-migration.md`.


@dataclass(frozen=True)
class BrowserSpec:
    """Inert compatibility shim. Browser-session scraping was removed; the `--browser`
    flag is accepted but ignored. Credentials come from the MCP-written creds file."""

    name: str
    macos_bundle_id: str = ""
    windows_progid: str = ""
    macos_profile_root: str = ""
    windows_profile_root: str = ""


SUPPORTED_BROWSERS: tuple[BrowserSpec, ...] = (
    BrowserSpec(name="Chrome"),
    BrowserSpec(name="Edge"),
)


def browser_spec_by_name(name: str) -> BrowserSpec | None:
    needle = name.strip().lower()
    for browser in SUPPORTED_BROWSERS:
        if browser.name.lower() == needle:
            return browser
    return None


# --- URL parsing (unchanged, pure) ------------------------------------------------------


def parse_flow_url(url: str) -> FlowUrl:
    parsed_url = parse_savant_url(url)
    if parsed_url.kind != "flow" or not parsed_url.flow_id:
        raise SavantAppApiError(f"URL does not contain `/flow/{{flowId}}`: {url}")
    return FlowUrl(
        origin=parsed_url.origin,
        flow_id=parsed_url.flow_id,
        namespace=parsed_url.namespace,
        url=parsed_url.url,
    )


def parse_savant_url(url: str) -> SavantUrl:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise SavantAppApiError(f"Expected a full Savant URL, got: {url}")
    parts = [part for part in parsed.path.split("/") if part]
    query = urllib.parse.parse_qs(parsed.query)
    namespace = (query.get("rns") or [None])[0]
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if "flow" in parts:
        try:
            flow_index = parts.index("flow")
            flow_id = parts[flow_index + 1]
        except IndexError as exc:
            raise SavantAppApiError(f"URL does not contain a flow id: {url}") from exc
        if not flow_id:
            raise SavantAppApiError(f"URL does not contain a flow id: {url}")
        return SavantUrl(origin=origin, url=url, kind="flow", flow_id=flow_id, namespace=namespace)
    if "analysis" in parts:
        folder_id = (query.get("folderId") or [None])[0]
        if not folder_id:
            raise SavantAppApiError(f"Analysis URL does not contain a folderId: {url}")
        return SavantUrl(origin=origin, url=url, kind="folder", folder_id=folder_id, namespace=namespace)
    raise SavantAppApiError(f"URL is not a supported Savant flow or folder URL: {url}")


# --- Creds-file session resolution ------------------------------------------------------
#
# The creds file is the handoff between the chat client (MCP speaker) and this shell (API
# executor). The client writes { token, tabId, apiBaseUrl, namespace } after calling
# `get-api-credentials`; we read it and build the SavantSessionContext every downstream
# module already expects. Nothing here speaks MCP. See skill-api-migration.md.

# Parsed-creds cache, keyed by resolved file path. invalidate_session_cache() clears it on
# a 401/403 so the next call re-reads the file (the client may have re-minted a fresh
# token). The bearer token lives only in this process's memory.
_CREDS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _session_cache_enabled() -> bool:
    return os.environ.get("SAVANT_SESSION_CACHE", "1").strip().lower() not in ("0", "false", "no", "off")


def invalidate_session_cache() -> None:
    """Drop the cached creds parse so the next discovery re-reads the file.

    Called by the HTTP layer on a 401/403 (the cached token is stale). The client is
    expected to re-mint via `get-api-credentials` and rewrite the creds file; the next
    discover_session() then picks up the fresh token."""
    _CREDS_CACHE.clear()


def _creds_file_path() -> Path:
    """Resolve the creds-file path: SAVANT_CREDS_FILE if set, else the session tmp dir."""
    override = os.environ.get("SAVANT_CREDS_FILE")
    if override:
        return Path(override).expanduser()
    return workspace_tmp(CREDS_FILE_NAME)


def _env_creds() -> dict[str, Any] | None:
    """Build creds from the environment — the primary credential path.

    Set SAVANT_API_TOKEN + SAVANT_API_TAB + SAVANT_API_BASE_URL (and optionally
    SAVANT_API_NAMESPACE). Returns None when they aren't all set, so the caller
    falls back to the creds file."""
    token = os.environ.get("SAVANT_API_TOKEN")
    tab_id = os.environ.get("SAVANT_API_TAB")
    base_url = os.environ.get("SAVANT_API_BASE_URL")
    if token and tab_id and base_url:
        return {
            "token": token,
            "tabId": tab_id,
            "apiBaseUrl": base_url,
            "namespace": os.environ.get("SAVANT_API_NAMESPACE"),
        }
    return None


def _read_creds() -> dict[str, Any]:
    """Return the creds dict from env vars or the creds file. Raises if neither is usable."""
    env_creds = _env_creds()
    if env_creds is not None:
        return env_creds

    path = _creds_file_path()
    cache_key = str(path)
    if _session_cache_enabled() and cache_key in _CREDS_CACHE:
        return _CREDS_CACHE[cache_key][1]

    if not path.exists():
        raise SavantAppApiError(
            "No Savant credentials found. Set SAVANT_API_TOKEN, SAVANT_API_TAB, and "
            "SAVANT_API_BASE_URL (optionally SAVANT_API_NAMESPACE), or write the "
            f"`get-api-credentials` response to a creds file at `{path}`. Have the "
            "assistant call the `get-api-credentials` MCP tool first."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SavantAppApiError(f"Could not read creds file `{path}`: {exc}") from exc
    if not isinstance(raw, dict):
        raise SavantAppApiError(f"Creds file `{path}` must contain a JSON object.")

    missing = [k for k in ("token", "tabId", "apiBaseUrl") if not raw.get(k)]
    if missing:
        raise SavantAppApiError(
            f"Creds file `{path}` is missing required field(s): {', '.join(missing)}. "
            "Expected { token, tabId, apiBaseUrl, namespace }."
        )

    if _session_cache_enabled():
        _CREDS_CACHE[cache_key] = (0.0, raw)
    return raw


def _context_from_creds(
    creds: dict[str, Any], namespace: str | None, origin: str
) -> SavantSessionContext:
    # apiBaseUrl from the creds file is the authority for the origin; fall back to the
    # caller-supplied origin (parsed from a flow/folder URL) only when absent. The MCP
    # `get-api-credentials` tool returns apiBaseUrl WITH a trailing `/api`, but every
    # endpoint path in this package already starts with `/api` (httpclient does
    # `origin + path`). Normalize to a bare origin so we don't double-prefix to
    # `/api/api/...`.
    resolved_origin = str(creds.get("apiBaseUrl") or origin or DEFAULT_ORIGIN).rstrip("/")
    if resolved_origin.endswith("/api"):
        resolved_origin = resolved_origin[: -len("/api")]
    creds_namespace = creds.get("namespace")
    active_namespace = namespace or (creds_namespace if isinstance(creds_namespace, str) else None)
    return SavantSessionContext(
        origin=resolved_origin,
        namespace=active_namespace,
        tab_id=str(creds["tabId"]),
        access_token=str(creds["token"]),
        browser_profile="mcp-creds",
        workspace_id=creds.get("workspaceId"),
        org_id=creds.get("orgId"),
    )


def discover_session(
    namespace: str | None,
    origin: str = DEFAULT_ORIGIN,
    *,
    browser_override: BrowserSpec | None = None,  # accepted for compat; ignored
) -> SavantSessionContext:
    """Build the authenticated session context from the MCP-written creds file.

    `browser_override` is accepted so the `--browser` CLI flag still parses, but it no
    longer selects anything — credentials come from the creds file (or env vars), never
    from a browser."""
    return _context_from_creds(_read_creds(), namespace, origin)
