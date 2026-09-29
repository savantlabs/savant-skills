#!/usr/bin/env python3
"""Report this package's Savant capabilities and probe live API availability.

Capability detection has layers, resolved in this order:

1. **Static (`api_supported`)** — read from the package's `capabilities.json`. A package without
   the live API ships `api_supported: false` (no API scripts, no creator); a package that ships
   the API has `true`. If false, the answer is "not supported" — no dynamic probe, manual mode only.
2. **Dynamic session probe** (only when `api_supported` is true) — is there a usable authenticated
   session we can reach? Resolving the MCP-written credentials (no request) decides
   available vs unavailable + reason.

The **execution-bridge** layer (e.g. Desktop Commander in Cowork) is detected by the agent, not
here: if there is no way to run this helper on the host at all, that itself signals "no API".

`api_enabled` is the final gate skills branch on. It is true only when the package supports the
API and the dynamic probe succeeds. `mode` is the human-readable equivalent: `api` or `manual`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.fileio import save_json, workspace_tmp  # noqa: E402


def find_capabilities_file() -> Path | None:
    """Walk up from this module to find the skill's references/capabilities.json (works in
    both the source tree and a shipped package, since the relative layout is the same)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "references" / "capabilities.json"
        if candidate.exists():
            return candidate
    return None


def read_capabilities() -> dict:
    path = find_capabilities_file()
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


LIVE_PROBE_PATH = "/api/sessions/tab"


def _live_probe_reason(exc: Exception) -> str:
    """Name the cause of a failed live probe, so the caller does not have to guess."""
    text = str(exc)
    if " failed: 401" in text:
        return (
            "live session probe returned 401: the paired session is idle-expired or its grant "
            "was disconnected. Call the `bind-toolchain` MCP tool again with the pairingHash "
            "from `savant.py session pair`, then retry."
        )
    if " failed: 403" in text:
        return (
            "live session probe returned 403: the request was refused before it could act as this "
            "session. On a sandboxed host this is usually a network egress policy blocking the "
            "Savant host rather than a Savant permission — check whether the host is reachable at "
            "all before treating it as an access problem."
        )
    return f"live session probe failed: {text[:300]}"


def probe_session(probe_live: bool = False) -> tuple[str, str | None]:
    """Read-only check that a usable Savant session exists. Returns (status, reason)
    with status in {available, unavailable}.

    Two depths:

    - **Default — shape only, no request.** Resolves the MCP-written creds file (or the env vars)
      and validates its shape. Read-only routes take this path, which is what keeps explaining,
      mapping and exporting a workflow off the app API entirely.
    - **`probe_live=True` — one authenticated `GET /api/sessions/tab`.** Proves the token, the
      workspace tab, and that the host is reachable at all; the endpoint returns 401 on a stale
      token (verified live 2026-09-11 against a valid and a corrupted token).

    A shape-only check sees neither a stale token nor a blocked egress path: both read as
    `available` and surface at the first write instead. Write routes therefore pass
    `probe_live=True` — they are about to call the API anyway, so the extra request buys fail-fast
    for free, turning a failure *after* a flow is built and user-confirmed into one at the gate.
    Do not make the live probe unconditional: that would put every capability check, including the
    offline and read-only ones, back on the app API.
    """
    try:
        from savant_api.session import discover_session

        context = discover_session(None)
        if not context.access_token or not context.tab_id or not context.origin:
            return "unavailable", "credentials resolved without a token, tab id or API base URL"
    except Exception as exc:  # any failure here means no usable session/bridge
        return "unavailable", f"{type(exc).__name__}: {exc}"

    if not probe_live:
        return "available", None

    try:
        from savant_api.httpclient import request

        request(context, LIVE_PROBE_PATH)
    except Exception as exc:  # stale token, unreachable host, blocked egress
        return "unavailable", _live_probe_reason(exc)
    return "available", None


def detect(probe_live: bool = False) -> dict:
    """Build the capability snapshot. `probe_live` selects the probe depth — see `probe_session`.

    The emitted `probe` field records which depth backed `api_enabled`, so a consumer reading a
    cached snapshot can tell a proven session from an assumed one."""
    from contracts.tracking_tag import savvy_version, tracking_tag

    caps = read_capabilities()
    result: dict = {
        "savvy_version": savvy_version(),
        "tracking_tag": tracking_tag(),
        "api_supported": bool(caps.get("api_supported")),
        "api_enabled": False,
        "probe": "live" if probe_live else "shape",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if not result["api_supported"]:
        result["session"] = "not_supported"
        result["mode"] = "manual"
        result["detail"] = (
            "This package does not ship the live API. Use existing dataset ids the user provides; "
            "build workflow JSON only; no creator step."
        )
        return result
    session, reason = probe_session(probe_live)
    result["session"] = session
    result["api_enabled"] = session == "available"
    result["mode"] = "api" if result["api_enabled"] else "manual"
    if reason:
        result["reason"] = reason
    if session != "available":
        result["detail"] = (
            "The live session probe failed, so a write would fail too. Re-bind the toolchain: call "
            "the `bind-toolchain` MCP tool with the pairingHash from `savant.py session pair` and "
            "retry; if that does not help, the Savant host is not reachable from this environment. "
            "Do not start a create or edit until this resolves."
            if probe_live
            else "API is supported but no usable session was found. Ask the user to sign in to the "
            "target workspace in Savant, or proceed in manual mode with user-provided dataset ids."
        )
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Report package capabilities and probe API availability.")
    p.add_argument(
        "--output-path",
        help="Optional path to write the capabilities JSON. Defaults to tmp/<ai-session-id>/savant-capabilities.json.",
    )
    p.add_argument("--quiet", action="store_true", help="Print only the resolved mode (api/manual).")
    p.add_argument(
        "--probe-live",
        action="store_true",
        help="Prove the session with one authenticated GET /api/sessions/tab instead of only checking "
        "that credentials resolve. Use before a write (create/edit): it catches a stale token or an "
        "unreachable host at the gate rather than at the first write. Read-only routes omit it.",
    )
    args = p.parse_args(argv)
    result = detect(probe_live=args.probe_live)
    output_path = Path(args.output_path) if args.output_path else workspace_tmp("savant-capabilities.json")
    save_json(result, output_path)
    print(result.get("mode") if args.quiet else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
