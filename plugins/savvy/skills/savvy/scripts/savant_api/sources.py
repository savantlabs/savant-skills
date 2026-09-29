from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .httpclient import poll_promise, promise_id_from_response, request, request_multipart
from .models import SavantAppApiError, SavantSessionContext


# Dataset listing lives on the MCP side now. `GET /api/sources` had three consumers here —
# list_sources, workspace_dataset_ids and discover_workflow_source_matches — and all three took
# the same shape: read every visible dataset, then match locally. The reading half is the MCP
# `search` tool with `types: ["source"]`; the matching half stayed put, in workflow/discovery.py
# (`dataset discover`) and in the create/edit preflights, which now take the search result as
# `--sources-json`. See savant_api/recipe_input.load_id_set for the id normalization.

# Connector strings for connected systems the skills can read and bind today. Users set these up
# (and authenticate them) manually in Savant; the skills only READ existing connections, never
# create or authenticate them. Expand this set as more systems are supported.
SUPPORTED_SYSTEM_CONNECTORS = {"onedrive", "googledrive"}


def upload_file_async(
    context: SavantSessionContext,
    path: Path,
    content_type: str = "application/octet-stream",
) -> str:
    """Stage a local file in Savant storage. POST /api/upload/file-async (multipart `file`)
    returns a promise; the resolved result carries the server `fileId` used to create a dataset.
    Uploading does NOT create a dataset by itself."""
    path = Path(path)
    response = request_multipart(
        context, "/api/upload/file-async",
        files={"file": (path.name, path.read_bytes(), content_type)},
    )
    result = poll_promise(context, response["promiseId"])
    file_id = (result.get("result") or {}).get("fileId") if isinstance(result, dict) else None
    if not file_id:
        raise SavantAppApiError(f"upload/file-async did not return a fileId: {json.dumps(result)[:400]}")
    return file_id


def sample_uploaded_file(
    context: SavantSessionContext,
    file_id: str,
    *,
    data_format: str,
    tab: str | None = None,
    skip_rows: int = 0,
    read_as_stored: bool = True,
    delimiter: str = ",",
    charset: str = "UTF_8",
    overwritten_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Profile a staged upload exactly as the upload wizard's Configure step does, returning the
    server's ``{"schema": [...], "data": [...], "length": int}``.

    This is the single source of truth the UI uses to build a dataset, and using it keeps an
    API-created dataset identical to a manual upload in three ways the local parser gets wrong:

    1. Duplicate column names are deduplicated HERE (server-side): the second and later
       occurrences of a name (compared case-insensitively) get a ``_2`` / ``_3`` suffix while
       the first is kept; blank headers become ``Column``/``Column_1``... The local parsers keep
       raw names, so a sheet with repeated headers (e.g. an SAP BI export with two
       "Asset super number" columns, or "Asset class"/"Asset Class") produces duplicate
       ``selected`` names that ``create-async`` rejects with SYSTEM_000.
    2. Data types are inferred by the server (e.g. "Fiscal year" -> integer), not guessed
       locally from a small sample.
    3. The sample is the server's (~1000 rows), matching the preview a UI upload shows, rather
       than an arbitrary locally-truncated slice.

    ``charset`` is the server's file-parser charset (``UTF_8`` or ``WINDOWS_1252``) and
    ``overwritten_types`` a column-name -> logical-type map the profiler honours *during*
    inference, so a code column declared ``string`` keeps its leading zeros.

    POST /api/upload/files/{fileId}/sample-async -> promise -> result {length, schema, data}."""
    body: dict[str, Any] = {
        "skipRows": int(skip_rows),
        "readAsStored": bool(read_as_stored),
        "dataFormat": data_format,
        "fileParserProps": {"delimiter": delimiter, "qualifier": '"', "escape": "\\", "charset": charset},
    }
    if overwritten_types:
        body["overwrittenTypes"] = dict(overwritten_types)
    if tab is not None:
        body["tab"] = tab
    response = request(context, f"/api/upload/files/{file_id}/sample-async", method="POST", body=body)
    result = poll_promise(context, promise_id_from_response(response))
    if isinstance(result, dict) and result.get("exception"):
        exc = result["exception"]
        raise SavantAppApiError(f"upload sample-async failed: {exc.get('code')} {exc.get('message')}")
    payload = result.get("result") if isinstance(result, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("schema"), list):
        raise SavantAppApiError(f"sample-async did not return schema/data: {json.dumps(result)[:400]}")
    return {
        "schema": [f for f in payload["schema"] if isinstance(f, dict)],
        "data": payload.get("data") or [],
        "length": payload.get("length") or 0,
    }


def create_source(context: SavantSessionContext, body: dict[str, Any]) -> dict[str, Any]:
    """Create a dataset (source) from a prepared create body. POST /api/sources/create-async
    returns a promise; this polls it and returns the created source object (result.id is the new
    dataset id). Raises on a FAILED promise. The `body` (name/config/profile, including the staged
    `fileId`) is built per file format by `savant_api.datasets`."""
    response = request(context, "/api/sources/create-async", method="POST", body=body)
    result = poll_promise(context, response["promiseId"])
    if isinstance(result, dict) and result.get("exception"):
        exc = result["exception"]
        raise SavantAppApiError(f"sources/create-async failed: {exc.get('code')} {exc.get('message')}")
    return (result.get("result") if isinstance(result, dict) else None) or result
