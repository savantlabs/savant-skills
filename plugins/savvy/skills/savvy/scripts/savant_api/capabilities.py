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


def probe_session() -> tuple[str, str | None]:
    """Read-only check that usable Savant credentials exist. Returns (status, reason)
    with status in {available, unavailable}.

    Resolves the MCP-written creds file (or the env vars) and validates its shape. This used to be
    an authenticated `GET /api/sessions/tab`, which additionally proved the token and workspace tab
    were still live by returning 401 when stale. That endpoint is gone, and no MCP tool reports
    bridge-token liveness, so **a stale token now reads as `available` here and fails at the first
    write instead** — with a 401 naming the operation. Credentials are minted per session by the
    `get-api-credentials` MCP tool, so a stale one is the uncommon case; the trade was accepted to
    take the read-only routes off the API entirely. Do not re-add a probe request: it would put
    every capability check back on the app API.
    """
    try:
        from savant_api.session import discover_session

        context = discover_session(None)
        if not context.access_token or not context.tab_id or not context.origin:
            return "unavailable", "credentials resolved without a token, tab id or API base URL"
        return "available", None
    except Exception as exc:  # any failure here means no usable session/bridge
        return "unavailable", f"{type(exc).__name__}: {exc}"


def detect() -> dict:
    from contracts.tracking_tag import savvy_version, tracking_tag

    caps = read_capabilities()
    result: dict = {
        "savvy_version": savvy_version(),
        "tracking_tag": tracking_tag(),
        "api_supported": bool(caps.get("api_supported")),
        "api_enabled": False,
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
    session, reason = probe_session()
    result["session"] = session
    result["api_enabled"] = session == "available"
    result["mode"] = "api" if result["api_enabled"] else "manual"
    if reason:
        result["reason"] = reason
    if session != "available":
        result["detail"] = (
            "API is supported but no usable session was found. Ask the user to sign in to the target "
            "workspace in Savant, or proceed in manual mode with user-provided dataset ids."
        )
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Report package capabilities and probe API availability.")
    p.add_argument(
        "--output-path",
        help="Optional path to write the capabilities JSON. Defaults to tmp/<ai-session-id>/savant-capabilities.json.",
    )
    p.add_argument("--quiet", action="store_true", help="Print only the resolved mode (api/manual).")
    args = p.parse_args(argv)
    result = detect()
    output_path = Path(args.output_path) if args.output_path else workspace_tmp("savant-capabilities.json")
    save_json(result, output_path)
    print(result.get("mode") if args.quiet else json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
