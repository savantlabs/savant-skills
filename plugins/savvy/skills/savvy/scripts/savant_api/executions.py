from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from .httpclient import request
from .recipes import recipe_nodes, recipe_parameters
from .models import SavantAppApiError, SavantSessionContext


TERMINAL_NODE_STATUSES = {"Ready", "Failed", "Error", "Canceled", "Skipped"}
FAILED_NODE_STATUSES = {"Failed", "Error", "Canceled"}
EXECUTION_TYPE_ALIASES = {
    "run": "run_now",
    "runs": "run_now",
    "run_now": "run_now",
    "on_demand": "run_now",
    "test": "test_run",
    "tests": "test_run",
    "test_run": "test_run",
    "scheduled": "scheduled",
    "schedule": "scheduled",
}
DEFAULT_EXECUTION_TYPES = ["run_now", "scheduled", "test_run"]


def _normalize_execution_types(values: list[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_EXECUTION_TYPES)
    normalized: list[str] = []
    for value in values:
        for part in str(value).split(","):
            key = part.strip().lower().replace("-", "_")
            if not key:
                continue
            execution_type = EXECUTION_TYPE_ALIASES.get(key)
            if not execution_type:
                allowed = ", ".join(sorted(EXECUTION_TYPE_ALIASES))
                raise SavantAppApiError(f"Unsupported execution type `{part}`. Use one of: {allowed}.")
            if execution_type not in normalized:
                normalized.append(execution_type)
    return normalized or list(DEFAULT_EXECUTION_TYPES)


def _timestamp_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric <= 0:
        return None
    if numeric > 10_000_000_000:
        numeric = numeric / 1000
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _format_duration_ms(started_at: Any, finished_at: Any) -> str | None:
    try:
        started = float(started_at)
        finished = float(finished_at)
    except (TypeError, ValueError):
        return None
    if started <= 0 or finished <= 0 or finished < started:
        return None
    seconds = int(round((finished - started) / 1000))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} m {seconds} s"
    if minutes:
        return f"{minutes} m {seconds} s"
    return f"{seconds} s"


def normalize_execution(execution: dict[str, Any]) -> dict[str, Any]:
    execution_type = execution.get("type")
    type_label = {
        "run_now": "run",
        "scheduled": "run",
        "test_run": "test",
    }.get(str(execution_type), str(execution_type) if execution_type else None)
    started_at = execution.get("startedAt")
    finished_at = execution.get("finishedAt")
    progress = execution.get("progress")
    if isinstance(progress, (int, float)):
        progress_value: float | str | None = progress
        progress_label = f"{round(progress * 100)}%"
    else:
        progress_value = progress
        progress_label = str(progress) if progress not in (None, "") else None
    return {
        "type": type_label,
        "executionType": execution_type,
        "id": execution.get("id"),
        "name": execution.get("name"),
        "workflowId": execution.get("recipeId") or execution.get("flowId"),
        "workflowName": execution.get("recipeName"),
        "version": execution.get("recipeVersion"),
        "submitter": execution.get("submitterName") or execution.get("submitter"),
        "submitterEmail": execution.get("submitter") if "@" in str(execution.get("submitter") or "") else None,
        "status": execution.get("phase"),
        "phase": execution.get("phase"),
        "progress": progress_value,
        "progressLabel": progress_label,
        "startedAt": _timestamp_to_iso(started_at),
        "finishedAt": _timestamp_to_iso(finished_at),
        "startedAtEpochMs": started_at,
        "finishedAtEpochMs": finished_at,
        "duration": execution.get("duration") or _format_duration_ms(started_at, finished_at),
    }


def list_recipe_executions(
    context: SavantSessionContext,
    flow_id: str,
    *,
    execution_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    types = _normalize_execution_types(execution_types)
    query = urllib.parse.urlencode({"types": ",".join(types)})
    response = request(context, f"/api/recipes/{urllib.parse.quote(flow_id)}/executions?{query}")
    executions = response.get("executions") if isinstance(response, dict) else None
    if not isinstance(executions, list):
        raise SavantAppApiError(f"GET /api/recipes/{flow_id}/executions did not return an execution array.")
    return [normalize_execution(item) for item in executions if isinstance(item, dict)]


def get_execution(context: SavantSessionContext, execution_id: str) -> dict[str, Any]:
    response = request(context, f"/api/executions/{urllib.parse.quote(execution_id)}")
    execution = response.get("execution") if isinstance(response, dict) else None
    if not isinstance(execution, dict):
        raise SavantAppApiError(f"GET /api/executions/{execution_id} did not return an execution object.")
    normalized = normalize_execution(execution)
    return {"execution": normalized, "raw": execution}


def _normalize_sample_tier(value: Any) -> str:
    """The backend sampleTier is BINARY: only the literal ``max`` triggers the full
    debug-session (Analyze) path; every other value is the 1k interactive path. Collapse
    anything that is not ``max`` to ``1k`` so a stray ``10k``/``2k`` does not masquerade as a
    larger tier that does not exist."""
    return "max" if isinstance(value, str) and value.strip().lower() == "max" else "1k"


def trigger_analysis(
    context: SavantSessionContext,
    flow_id: str,
    nodes: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
    stopping_nodes: list[str],
    *,
    sample_tier: str = "1k",
    starting_nodes: list[str] | None = None,
    action: str | None = None,
) -> Any:
    if not stopping_nodes:
        raise SavantAppApiError("At least one stopping node is required for analysis.")
    body: dict[str, Any] = {
        "flowId": flow_id,
        "nodes": nodes,
        "parameters": parameters,
        "stoppingNodes": stopping_nodes,
    }
    if starting_nodes:
        body["startingNodes"] = starting_nodes
        # A starting node means "recompute from this edited node forward". APPLY evicts its
        # cache first so the recompute is fresh; it is the only backend-honored action (the
        # old ANALYZE value mapped to a no-op OTHER).
        if action is None:
            action = "APPLY"
    tier = _normalize_sample_tier(sample_tier)
    path = f"/api/interactive/graph-computation?sampleTier={urllib.parse.quote(tier)}"
    if action:
        path += f"&action={urllib.parse.quote(action)}"
    return request(context, path, method="POST", body=body)


def graph_status(context: SavantSessionContext, flow_id: str) -> dict[str, Any]:
    status = request(context, f"/api/interactive/graph-computation-status?flowId={urllib.parse.quote(flow_id)}")
    if not isinstance(status, dict):
        raise SavantAppApiError(f"Graph status for {flow_id} did not return a JSON object.")
    return status


def node_status_map(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = status.get("nodeStatusDetails")
    if not isinstance(details, list):
        return {}
    return {item.get("nodeId"): item for item in details if isinstance(item, dict) and isinstance(item.get("nodeId"), str)}


def poll_analysis_status(
    context: SavantSessionContext,
    flow_id: str,
    stopping_nodes: list[str],
    *,
    timeout_seconds: int = 90,
    interval_seconds: float = 1.0,
    fail_fast_on_error: bool = False,
) -> dict[str, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        latest = node_status_map(graph_status(context, flow_id))
        if fail_fast_on_error and any((latest.get(node_id) or {}).get("status") in FAILED_NODE_STATUSES for node_id in stopping_nodes):
            return latest
        if stopping_nodes and all((latest.get(node_id) or {}).get("status") in TERMINAL_NODE_STATUSES for node_id in stopping_nodes):
            return latest
        time.sleep(interval_seconds)
    raise SavantAppApiError(f"Timed out waiting for analysis of node(s): {', '.join(stopping_nodes)}")


def fetch_node_output(
    context: SavantSessionContext,
    flow_id: str,
    node_id: str,
    *,
    sample_tier: str = "1k",
    sorts: list[Any] | None = None,
) -> dict[str, Any]:
    path = (
        f"/api/interactive/graph-computation-sort"
        f"?flowId={urllib.parse.quote(flow_id)}"
        f"&nodeId={urllib.parse.quote(node_id)}"
        f"&sampleTier={urllib.parse.quote(_normalize_sample_tier(sample_tier))}"
    )
    output = request(context, path, method="POST", body={"sorts": sorts or []})
    if not isinstance(output, dict):
        raise SavantAppApiError(f"Output for node {node_id} did not return a JSON object.")
    return output


def summarize_node_output(output: dict[str, Any], *, row_limit: int = 5) -> dict[str, Any]:
    blocks = output.get("outputData")
    if not isinstance(blocks, list) or not blocks:
        return {"schema": [], "rows": [], "rowCount": 0}
    block = blocks[0]
    if not isinstance(block, dict):
        return {"schema": [], "rows": [], "rowCount": 0}
    schema = block.get("schema") if isinstance(block.get("schema"), list) else []
    data = block.get("data") if isinstance(block.get("data"), list) else []
    names = [column.get("name") for column in schema if isinstance(column, dict)]
    rows = [dict(zip(names, row)) for row in data[:row_limit] if isinstance(row, list)]
    return {
        "schema": schema,
        "rows": rows,
        "rowCount": block.get("totalRows") or block.get("rowCount") or len(data),
    }


def analyze_and_fetch_node(
    context: SavantSessionContext,
    recipe: dict[str, Any],
    flow_id: str,
    node_id: str,
    *,
    sample_tier: str = "1k",
    starting_nodes: list[str] | None = None,
    timeout_seconds: int = 90,
    reuse_ready: bool = True,
    fetch_outputs: bool = True,
) -> dict[str, Any]:
    """Fetch one node's output, computing it first only when needed.

    With ``reuse_ready`` (default), if the node is already in a terminal ``Ready`` state in the
    live graph status, its cached output is read directly — the same data the canvas already shows —
    instead of forcing a fresh Analyze and blocking on the poll. Set ``reuse_ready=False`` to force
    a recompute (e.g. after an edit that the caller knows invalidated the cache but the status has
    not caught up)."""
    return analyze_and_fetch_many(
        context,
        recipe,
        flow_id,
        [node_id],
        sample_tier=sample_tier,
        starting_nodes=starting_nodes,
        timeout_seconds=timeout_seconds,
        reuse_ready=reuse_ready,
        fetch_outputs=fetch_outputs,
    )[node_id]


def _with_upstream_ids(nodes: list[dict[str, Any]], node_ids: list[str]) -> list[str]:
    """Return node_ids plus every upstream ancestor, deduplicated, sources first.

    Used by forced (cache-busting) Analyze so the engine recomputes the full chain
    feeding each requested node instead of reusing stale intermediate caches.

    Outlet pseudo-nodes (split-blend/filter forks like ``blend_x|1``) are traversed
    but NEVER included in the returned ids: the engine's computation-status map does
    not report them, so triggering/polling them waits out the full timeout even when
    every real node finished — verified live. Their parent real node is what computes.
    """
    by_id: dict[str, dict[str, Any]] = {
        node["id"]: node for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    sources_by_id: dict[str, list[str]] = {}
    for node_id, node in by_id.items():
        upstream: list[str] = []
        for inlet in node.get("inlets") or []:
            if not isinstance(inlet, dict):
                continue
            if isinstance(inlet.get("source"), str) and inlet["source"]:
                upstream.append(inlet["source"])
            for src in inlet.get("sources") or []:
                if isinstance(src, dict) and isinstance(src.get("source"), str) and src["source"]:
                    upstream.append(src["source"])
        sources_by_id[node_id] = upstream

    def _is_pseudo(nid: str) -> bool:
        node = by_id.get(nid) or {}
        return node.get("type") == "outlet" or "|" in nid

    ordered: list[str] = []
    seen: set[str] = set()

    def _visit(nid: str) -> None:
        if nid in seen or nid not in sources_by_id:
            return
        seen.add(nid)
        for upstream_id in sources_by_id[nid]:
            _visit(upstream_id)
        if not _is_pseudo(nid):
            ordered.append(nid)

    for nid in node_ids:
        _visit(nid)
    # Callers asked for these ids; keep any pseudo-node the caller explicitly
    # requested at the end so its result row still appears in the report.
    for nid in node_ids:
        if nid not in ordered and _is_pseudo(nid):
            ordered.append(nid)
    return ordered


def analyze_and_fetch_many(
    context: SavantSessionContext,
    recipe: dict[str, Any],
    flow_id: str,
    node_ids: list[str],
    *,
    sample_tier: str = "1k",
    starting_nodes: list[str] | None = None,
    timeout_seconds: int = 90,
    reuse_ready: bool = True,
    fail_fast_on_error: bool = True,
    fetch_outputs: bool = True,
) -> dict[str, dict[str, Any]]:
    """Fetch several nodes' outputs in one status-aware pass.

    Reading the live ``graph-computation-status`` once, nodes already ``Ready`` are served from
    their cached output (no recompute). Only the remaining "cold" nodes are recomputed, and they are
    triggered together in a SINGLE Analyze with one shared poll for all of them — rather than a
    sequential trigger+poll per node — so verifying N terminals costs one Analyze cycle, not N.
    When ``fetch_outputs`` is false, this is a status-only runtime smoke test: it triggers/polls
    the requested nodes but never reads preview output. Use that before schema/row inspection so a
    failed transform reports immediately instead of burning time on preview endpoints that cannot
    succeed.
    Returns ``{node_id: {"nodeId", "status", "output"?}}`` for every requested node."""
    nodes = recipe_nodes(recipe)
    parameters = recipe_parameters(recipe)
    valid_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
    missing = [nid for nid in node_ids if nid not in valid_ids]
    if missing:
        raise SavantAppApiError(
            f"Workflow {flow_id} does not contain node(s): {', '.join(missing)}."
        )

    statuses = node_status_map(graph_status(context, flow_id))
    if reuse_ready:
        cold = [nid for nid in node_ids if (statuses.get(nid) or {}).get("status") != "Ready"]
    else:
        # Forced refresh: bust the whole upstream chain, not just the requested nodes, so the
        # engine cannot serve a requested node from a stale intermediate cache.
        cold = _with_upstream_ids(nodes, node_ids)

    if cold:
        trigger_analysis(
            context, flow_id, nodes, parameters, cold,
            sample_tier=sample_tier, starting_nodes=starting_nodes,
        )
        # poll_analysis_status returns the FULL live status map (all nodes), so this also refreshes
        # the statuses we use below for the already-warm nodes.
        statuses = poll_analysis_status(
            context,
            flow_id,
            cold,
            timeout_seconds=timeout_seconds,
            fail_fast_on_error=fail_fast_on_error,
        )

    results: dict[str, dict[str, Any]] = {}
    for nid in node_ids:
        node_status = statuses.get(nid) or {}
        result: dict[str, Any] = {"nodeId": nid, "status": node_status}
        if fetch_outputs and node_status.get("status") == "Ready":
            raw_output = fetch_node_output(context, flow_id, nid, sample_tier=sample_tier)
            result["output"] = summarize_node_output(raw_output)
        results[nid] = result
    return results
