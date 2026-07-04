from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from .models import SavantAppApiError, SavantSessionContext


PROCESSING_PROMISE_STATUSES = {"PROCESSING", "PENDING", "RUNNING"}


def _format_url_error(method: str, path: str, exc: urllib.error.URLError) -> str:
    reason = exc.reason
    base = f"{method} {path} failed: {exc}"
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1":
        return (
            f"{base}. The local Codex shell has network disabled "
            "(`CODEX_SANDBOX_NETWORK_DISABLED=1`), so API calls cannot reach Savant from this process."
        )
    if isinstance(reason, socket.gaierror):
        return (
            f"{base}. DNS resolution failed before the request reached Savant; "
            "check local DNS/network access for the shell process."
        )
    return base


# Gateway timeouts (504) and transient gateway errors (502/503) are frequently
# transient — an observed `PUT /api/recipes` save returned 504 twice in a row and then
# succeeded unchanged on retry. Retry only IDEMPOTENT methods so we never re-send a
# POST that may have already taken effect (e.g. import, which could create a duplicate
# flow). Import goes through `request_multipart`, which is intentionally not retried here.
RETRYABLE_STATUSES = {502, 503, 504}
IDEMPOTENT_METHODS = {"GET", "PUT"}
MAX_REQUEST_ATTEMPTS = 3
# A stale bearer token (e.g. after a refresh inside a long-lived `serve` process)
# surfaces as 401/403. Drop the cached session parse so the next discovery re-reads
# the current token from the browser. We do NOT auto-retry the in-flight call: it
# self-heals on the caller's next request, and silently retrying a non-idempotent
# POST (import) could create a duplicate flow.
AUTH_FAILURE_STATUSES = {401, 403}


def _invalidate_session_on_auth_failure(code: int) -> None:
    if code not in AUTH_FAILURE_STATUSES:
        return
    try:
        from .session import invalidate_session_cache

        invalidate_session_cache()
    except Exception:
        pass


def request(context: SavantSessionContext, path: str, method: str = "GET", body: Any | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        context.origin + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {context.access_token}",
            "X-SAVANT-TAB": context.tab_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    attempts = MAX_REQUEST_ATTEMPTS if method.upper() in IDEMPOTENT_METHODS else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
                return None if not raw else json.loads(raw)
        except urllib.error.HTTPError as exc:
            _invalidate_session_on_auth_failure(exc.code)
            if exc.code in RETRYABLE_STATUSES and attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            detail = exc.read().decode(errors="replace")
            raise SavantAppApiError(f"{method} {path} failed: {exc.code} {detail[:800]}") from exc
        except urllib.error.URLError as exc:
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise SavantAppApiError(_format_url_error(method, path, exc)) from exc


def request_multipart(
    context: SavantSessionContext,
    path: str,
    *,
    fields: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]],
) -> Any:
    boundary = f"----SavantCodexBoundary{uuid.uuid4().hex}"
    body_parts: list[bytes] = []
    for name, value in (fields or {}).items():
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for name, (filename, content, content_type) in files.items():
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
            ]
        )
    body_parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        context.origin + path,
        data=b"".join(body_parts),
        method="POST",
        headers={
            "Authorization": f"Bearer {context.access_token}",
            "X-SAVANT-TAB": context.tab_id,
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return None if not raw else json.loads(raw)
    except urllib.error.HTTPError as exc:
        _invalidate_session_on_auth_failure(exc.code)
        detail = exc.read().decode(errors="replace")
        raise SavantAppApiError(f"POST {path} failed: {exc.code} {detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise SavantAppApiError(_format_url_error("POST", path, exc)) from exc

def promise_id_from_response(response: dict[str, Any]) -> str:
    promise_id = response.get("promiseId") or response.get("id")
    if not isinstance(promise_id, str) or not promise_id:
        raise SavantAppApiError("Import response did not include a promise id.")
    return promise_id


def promise_status_value(promise: dict[str, Any]) -> str | None:
    status = promise.get("status")
    return status if isinstance(status, str) else None


def poll_promise(
    context: SavantSessionContext,
    promise_id: str,
    *,
    timeout_seconds: int = 90,
    interval_seconds: float = 1.0,
) -> dict[str, Any]:
    """Wait for an async server job. Polling starts fast and backs off to `interval_seconds`.

    Most promises behind small uploads/samples/creates finish in well under a second; a fixed
    1s sleep made every such job cost a full second regardless (measured live 2026-06-10:
    8.6s to create two ~10KB datasets, ~5s of it pure sleep across five promises). The
    adaptive cadence keeps fast jobs fast without hammering the API on slow ones.
    """
    deadline = time.time() + timeout_seconds
    delay = min(0.15, float(interval_seconds))
    while time.time() < deadline:
        response = request(context, f"/api/promises/{urllib.parse.quote(promise_id)}")
        if not isinstance(response, dict):
            raise SavantAppApiError(f"Promise {promise_id} did not return a JSON object.")
        status = promise_status_value(response)
        if status is None or status.upper() not in PROCESSING_PROMISE_STATUSES:
            return response
        time.sleep(delay)
        delay = min(delay * 2, float(interval_seconds))
    raise SavantAppApiError(f"Timed out waiting for promise {promise_id}.")
