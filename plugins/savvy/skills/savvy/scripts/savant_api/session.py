from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fileio import workspace_tmp
from .models import DEFAULT_ORIGIN, FlowUrl, SavantAppApiError, SavantSessionContext, SavantUrl


# Pairing (ENG-985). This shell generates its own api bearer secret (`session pair`) and
# keeps it in the pair file below; only the secret's SHA-256 ever crosses the chat client,
# which hands it to the `bind-toolchain` MCP tool. The server stores the hash and accepts
# the secret as a session. No credential is ever minted server-side or returned over MCP.
# `SAVANT_PAIR_FILE` overrides the path.
PAIR_FILE_NAME = "savant-pair.json"
PAIR_SECRET_PREFIX = "xmp-"
# Bytes of entropy behind the secret; hex-encoded to 64 chars. The server refuses paired
# secrets shorter than 32 chars after the prefix.
PAIR_SECRET_BYTES = 32

# Creds file under the session tmp dir: { token, tabId, apiBaseUrl, namespace }. Written by
# `session bind` from the pair file plus the non-secret `bind-toolchain` response; read by
# every API call in this package. `SAVANT_CREDS_FILE` overrides the path.
CREDS_FILE_NAME = "savant-creds.json"


# --- Browser-spec compatibility surface -------------------------------------------------
#
# The old session resolver scraped the browser's localStorage (LevelDB) to lift the
# logged-in token. That dependency is gone: the shell pairs its own secret with the MCP
# grant (see the pairing section below). These types remain only so the `--browser` CLI
# flag still parses; they no longer select a real code path.


@dataclass(frozen=True)
class BrowserSpec:
    """Inert compatibility shim. Browser-session scraping was removed; the `--browser`
    flag is accepted but ignored. Credentials come from the paired creds file."""

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


def ensure_rns(url: str, namespace: str | None) -> str:
    """Return `url` with `rns=<namespace>` appended when the URL lacks one.

    A Savant link handed to the user should always carry the owning workspace's namespace
    so the web app opens in the right workspace. An `rns` already present in the URL is
    authoritative and left untouched, even if it differs from `namespace`; a blank `rns=`
    is treated as missing. With no namespace to add, the URL is returned unchanged.
    """
    if not url or not namespace:
        return url
    parsed = urllib.parse.urlparse(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == "rns" and value for key, value in pairs):
        return url
    pairs = [(key, value) for key, value in pairs if key != "rns"]
    pairs.append(("rns", namespace))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(pairs)))


# --- Toolchain pairing (ENG-985) --------------------------------------------------------
#
# Reverse-direction credential handoff. The secret is born here and never leaves this
# machine: `session pair` generates it, stores it 0600 in the session tmp dir, and prints
# only its SHA-256. The chat client passes that hash to the `bind-toolchain` MCP tool; the
# server records `xmp-<hash>` against the caller's OAuth grant and, on the api side, hashes
# every presented `xmp-` bearer before lookup. Knowing the hash (or the stored row) is not
# enough to authenticate. `session bind` then completes the creds file from the tool's
# non-secret response (apiBaseUrl, tabId).


def pair_file_path() -> Path:
    """Resolve the pair-file path: SAVANT_PAIR_FILE if set, else the session tmp dir."""
    override = os.environ.get("SAVANT_PAIR_FILE")
    if override:
        return Path(override).expanduser()
    return workspace_tmp(PAIR_FILE_NAME)


def generate_pairing_secret() -> str:
    return PAIR_SECRET_PREFIX + secrets.token_hex(PAIR_SECRET_BYTES)


def is_pairing_secret(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(PAIR_SECRET_PREFIX)
        and len(value) - len(PAIR_SECRET_PREFIX) >= 32
    )


def pairing_hash(secret: str) -> str:
    """Lowercase hex SHA-256 of the WHOLE secret, prefix included — must match the server."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Write `payload` to `path` readable by this user only, creating parents 0700."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _read_pairing_secret(path: Path) -> str | None:
    """Return the secret held in an existing pair file, or None if absent/unusable."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    secret = raw.get("secret") if isinstance(raw, dict) else None
    return secret if is_pairing_secret(secret) else None


def ensure_pairing(path: Path | None = None) -> dict[str, Any]:
    """Create the pair file if needed and return `{pairingHash, pairFile, created}`.

    Idempotent per AI session: an existing usable pair file is reused so that a re-bind
    renews the same server session instead of minting a new one. The returned dict never
    contains the secret — it is what `session pair` prints and what the chat client sees.
    """
    resolved = pair_file_path() if path is None else path
    secret = _read_pairing_secret(resolved)
    created = secret is None
    if created:
        secret = generate_pairing_secret()
        _write_private_json(
            resolved, {"secret": secret, "pairingHash": pairing_hash(secret)}
        )
    return {"pairingHash": pairing_hash(secret), "pairFile": str(resolved), "created": created}


def bind_credentials(
    api_base_url: str,
    tab_id: str,
    namespace: str | None = None,
    *,
    pair_path: Path | None = None,
    creds_path: Path | None = None,
) -> dict[str, Any]:
    """Write the creds file from the pair secret plus the `bind-toolchain` response.

    Returns `{credsFile, apiBaseUrl, tabId, namespace}` — never the secret. Fails if no
    pair file exists: binding without pairing means the server never saw this secret's
    hash, so the API would reject it anyway."""
    if not api_base_url or not api_base_url.strip():
        raise SavantAppApiError("--api-base-url is required (the `bind-toolchain` apiBaseUrl).")
    if not tab_id or not tab_id.strip():
        raise SavantAppApiError("--tab-id is required (the `bind-toolchain` tabId).")
    resolved_pair = pair_file_path() if pair_path is None else pair_path
    secret = _read_pairing_secret(resolved_pair)
    if secret is None:
        raise SavantAppApiError(
            f"No pairing secret at `{resolved_pair}`. Run `savant.py session pair` first, "
            "have the assistant call `bind-toolchain` with the printed pairingHash, then bind."
        )
    resolved_creds = _creds_file_path() if creds_path is None else creds_path
    payload = {
        "token": secret,
        "tabId": tab_id.strip(),
        "apiBaseUrl": api_base_url.strip(),
        "namespace": namespace.strip() if isinstance(namespace, str) and namespace.strip() else None,
    }
    _write_private_json(resolved_creds, payload)
    invalidate_session_cache()
    return {
        "credsFile": str(resolved_creds),
        "apiBaseUrl": payload["apiBaseUrl"],
        "tabId": payload["tabId"],
        "namespace": payload["namespace"],
    }


# --- Creds-file session resolution ------------------------------------------------------
#
# The creds file is the handoff between the pairing step and the API executor. `session
# bind` writes { token, tabId, apiBaseUrl, namespace } (token = the locally generated
# pairing secret); we read it and build the SavantSessionContext every downstream module
# already expects. Nothing here speaks MCP.

# Parsed-creds cache, keyed by resolved file path. invalidate_session_cache() clears it on
# a 401/403 so the next call re-reads the file. The bearer secret lives only in this
# process's memory and the 0600 pair/creds files.
_CREDS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _session_cache_enabled() -> bool:
    return os.environ.get("SAVANT_SESSION_CACHE", "1").strip().lower() not in ("0", "false", "no", "off")


def invalidate_session_cache() -> None:
    """Drop the cached creds parse so the next discovery re-reads the file.

    Called by the HTTP layer on a 401/403. The session's sliding window (4h idle) lapsed
    or the grant was revoked; the chat client is expected to call `bind-toolchain` again
    with the same pairingHash, which renews the server row without changing the secret.
    Clearing the cache also covers a `session bind` that rewrote the creds file."""
    _CREDS_CACHE.clear()


def _creds_file_path() -> Path:
    """Resolve the creds-file path: SAVANT_CREDS_FILE if set, else the session tmp dir."""
    override = os.environ.get("SAVANT_CREDS_FILE")
    if override:
        return Path(override).expanduser()
    return workspace_tmp(CREDS_FILE_NAME)


def _read_creds() -> dict[str, Any]:
    """Return the creds dict from the creds file written by `session bind`. Raises if unusable."""
    path = _creds_file_path()
    cache_key = str(path)
    if _session_cache_enabled() and cache_key in _CREDS_CACHE:
        return _CREDS_CACHE[cache_key][1]

    if not path.exists():
        raise SavantAppApiError(
            f"No Savant credentials found at `{path}`. Pair the toolchain first: run "
            "`savant.py session pair` (prints a pairingHash), have the assistant call the "
            "`bind-toolchain` MCP tool with that hash, then run `savant.py session bind "
            "--api-base-url <apiBaseUrl> --tab-id <tabId>` with the values it returned."
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
    # `bind-toolchain` tool returns apiBaseUrl WITH a trailing `/api`, but every endpoint
    # path in this package already starts with `/api` (httpclient does `origin + path`).
    # Normalize to a bare origin so we don't double-prefix to `/api/api/...`.
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
    """Build the authenticated session context from the paired creds file.

    `browser_override` is accepted so the `--browser` CLI flag still parses, but it no
    longer selects anything — credentials come from the creds file (or env vars), never
    from a browser."""
    return _context_from_creds(_read_creds(), namespace, origin)
