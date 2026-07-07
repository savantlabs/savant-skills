#!/usr/bin/env python3
"""Read-only batch node preview helper.

This helper fetches preview output for multiple Savant workflow nodes. By default
it reads the latest available preview status without triggering Analyze. Pass
--analyze only when the calling skill has confirmed that no-write Analyze preview
execution is appropriate for the user's requested scope.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.cli import (  # noqa: E402
    SavantAppApiError,
    TERMINAL_NODE_STATUSES,
    discover_session,
    ensure_rns,
    fetch_node_output,
    get_recipe,
    graph_status,
    node_status_map,
    parse_flow_url,
    recipe_nodes,
    recipe_parameters,
    save_json,
    summarize_node_output,
    trigger_analysis,
)
from savant_api.fileio import workspace_tmp  # noqa: E402
from savant_api import runmode  # noqa: E402


DEFAULT_MAX_NODES = 10


def node_label(node: dict[str, Any]) -> str | None:
    for key in ("name", "label", "id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def node_by_id(recipe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node["id"]: node
        for node in recipe_nodes(recipe)
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }


def resolve_node_names(recipe: dict[str, Any], names: list[str]) -> list[str]:
    nodes = recipe_nodes(recipe)
    resolved: list[str] = []
    for name in names:
        matches = [
            node
            for node in nodes
            if isinstance(node, dict)
            and isinstance(node.get("id"), str)
            and node_label(node)
            and node_label(node).casefold() == name.strip().casefold()
        ]
        if not matches:
            raise SavantAppApiError(f"No node matched display name `{name}`.")
        if len(matches) > 1:
            labels = ", ".join(f"{node_label(node)} ({node.get('id')})" for node in matches[:10])
            raise SavantAppApiError(f"Node display name `{name}` matched multiple nodes: {labels}. Use node ids.")
        resolved.append(str(matches[0]["id"]))
    return resolved


def parse_node_ids(values: list[str], array_value: str | None) -> list[str]:
    node_ids = [value.strip() for value in values if value.strip()]
    if array_value:
        try:
            parsed = json.loads(array_value)
        except json.JSONDecodeError as exc:
            raise SavantAppApiError("--node-ids must be a JSON array of strings.") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) and item.strip() for item in parsed):
            raise SavantAppApiError("--node-ids must be a JSON array of non-empty strings.")
        node_ids.extend(item.strip() for item in parsed)
    unique: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        if node_id not in seen:
            unique.append(node_id)
            seen.add(node_id)
    return unique


def node_metadata(node_id: str, nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node = nodes_by_id.get(node_id)
    if node is not None:
        return {
            "nodeId": node_id,
            "name": node_label(node),
            "type": node.get("type"),
            "isOutlet": False,
        }
    parent_id, separator, outlet_id = node_id.partition("|")
    parent = nodes_by_id.get(parent_id) if separator else None
    if parent is not None:
        outlet = None
        outlets = parent.get("outlets")
        if isinstance(outlets, list):
            outlet = next(
                (
                    item
                    for item in outlets
                    if isinstance(item, dict)
                    and str(item.get("id") or item.get("outletId") or item.get("name") or "") == outlet_id
                ),
                None,
            )
        outlet_name = outlet.get("name") if isinstance(outlet, dict) else None
        return {
            "nodeId": node_id,
            "name": f"{node_label(parent) or parent_id} / {outlet_name or outlet_id}",
            "type": parent.get("type"),
            "parentNodeId": parent_id,
            "parentName": node_label(parent),
            "outletId": outlet_id,
            "outletName": outlet_name,
            "isOutlet": True,
        }
    return {
        "nodeId": node_id,
        "name": None,
        "type": None,
        "isOutlet": "|" in node_id,
        "warning": "Node id was not found in the recipe map; Analyze will still be attempted.",
    }


def preview_status(status: dict[str, Any]) -> str:
    value = status.get("status")
    return value if isinstance(value, str) and value else "Unknown"


def poll_statuses(
    context: Any,
    flow_id: str,
    node_ids: list[str],
    *,
    timeout_seconds: int,
    interval_seconds: float = 1.0,
) -> tuple[dict[str, dict[str, Any]], bool]:
    deadline = time.time() + timeout_seconds
    latest: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        latest = node_status_map(graph_status(context, flow_id))
        if node_ids and all((latest.get(node_id) or {}).get("status") in TERMINAL_NODE_STATUSES for node_id in node_ids):
            return latest, False
        time.sleep(interval_seconds)
    return latest, True


def build_preview_report(
    flow_url: str,
    node_ids: list[str],
    *,
    sample_tier: str = "1k",
    timeout_seconds: int = 90,
    row_limit: int = 5,
    include_raw: bool = False,
    node_names: list[str] | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    analyze: bool = False,
    from_nodes: list[str] | None = None,
    fetch_existing: bool = True,
) -> dict[str, Any]:
    parsed = parse_flow_url(flow_url)
    context = discover_session(parsed.namespace, origin=parsed.origin)
    recipe = get_recipe(context, parsed.flow_id)
    resolved_ids = list(node_ids)
    if node_names:
        resolved_ids.extend(resolve_node_names(recipe, node_names))
    unique_ids = []
    for node_id in resolved_ids:
        if node_id not in unique_ids:
            unique_ids.append(node_id)
    if not unique_ids:
        raise SavantAppApiError("Provide at least one node id or node name.")
    if len(unique_ids) > max_nodes:
        raise SavantAppApiError(f"Refusing to preview {len(unique_ids)} nodes; max is {max_nodes}.")

    nodes = recipe_nodes(recipe)
    parameters = recipe_parameters(recipe)
    nodes_by_id = node_by_id(recipe)
    # `--from` may arrive as ids or display names; resolve names to ids and keep ids as-is.
    starting_nodes: list[str] = []
    for token in from_nodes or []:
        if token in nodes_by_id:
            starting_nodes.append(token)
        else:
            starting_nodes.extend(resolve_node_names(recipe, [token]))
    trigger_response = None
    if analyze:
        trigger_response = trigger_analysis(
            context, parsed.flow_id, nodes, parameters, unique_ids,
            sample_tier=sample_tier, starting_nodes=starting_nodes or None,
        )
        statuses, timed_out = poll_statuses(context, parsed.flow_id, unique_ids, timeout_seconds=timeout_seconds)
    else:
        statuses = node_status_map(graph_status(context, parsed.flow_id))
        timed_out = False

    previews: list[dict[str, Any]] = []
    for node_id in unique_ids:
        status = statuses.get(node_id) or {}
        row: dict[str, Any] = {
            **node_metadata(node_id, nodes_by_id),
            "status": status,
            "previewStatus": preview_status(status),
        }
        if fetch_existing and status.get("status") == "Ready":
            try:
                raw_output = fetch_node_output(context, parsed.flow_id, node_id, sample_tier=sample_tier)
                row["output"] = summarize_node_output(raw_output, row_limit=row_limit)
                if include_raw:
                    row["rawOutput"] = raw_output
            except Exception as exc:  # keep per-node failures isolated
                row["outputError"] = str(exc)
        elif not fetch_existing:
            row["outputSkipped"] = "Output fetch disabled by caller."
        previews.append(row)

    return {
        "task": "node_previews",
        "flowUrl": ensure_rns(flow_url, context.namespace),
        "workflow": {
            "id": recipe.get("id") or parsed.flow_id,
            "name": recipe.get("name"),
            "namespace": context.namespace,
            "workspaceId": context.workspace_id,
            "workspaceName": (context.workspace or {}).get("name"),
            "organizationId": context.org_id,
            "organizationName": (context.organization or {}).get("name"),
        },
        "sampleTier": sample_tier,
        "mode": ("analyze" if analyze and sample_tier == "max" else "interactive" if analyze else "cached"),
        "analyzeTriggered": analyze,
        "startingNodes": starting_nodes,
        "fetchedExistingOutput": fetch_existing,
        "requestedNodeIds": unique_ids,
        "timedOut": timed_out,
        "warnings": (
            [f"Timed out waiting for all requested node previews after {timeout_seconds} seconds."]
            if timed_out
            else []
        ),
        "triggerResponse": trigger_response if include_raw else None,
        "previews": previews,
    }


def default_output_path(flow_id: str) -> Path:
    return workspace_tmp("node-previews", f"{flow_id}.node-previews.json")


def print_summary(report: dict[str, Any]) -> None:
    workflow = report.get("workflow", {})
    print(f"Workflow: {workflow.get('name') or workflow.get('id')}")
    print(f"Nodes requested: {len(report.get('requestedNodeIds') or [])}")
    for preview in report.get("previews", []):
        if not isinstance(preview, dict):
            continue
        output = preview.get("output") if isinstance(preview.get("output"), dict) else {}
        row_count = output.get("rowCount") if output else "n/a"
        suffix = f"; output error: {preview.get('outputError')}" if preview.get("outputError") else ""
        print(f"- {preview.get('name') or preview.get('nodeId')}: {preview.get('previewStatus')} ({row_count} row(s)){suffix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flow_url", help="Savant flow URL to inspect.")
    parser.add_argument("--node-id", action="append", default=[], help="Node id to preview. Repeat for multiple nodes.")
    parser.add_argument("--node-ids", help='JSON array of node ids, e.g. \'["source_a","filter_b|1"]\'.')
    parser.add_argument("--node-name", action="append", default=[], help="Exact node display name to resolve and preview.")
    runmode.add_run_mode_args(parser, default="cached")
    parser.add_argument("--timeout-seconds", type=int, default=90, help="Analyze polling timeout.")
    parser.add_argument("--status-only", action="store_true", help="Do not fetch preview output rows; return per-node status only.")
    parser.add_argument("--row-limit", type=int, default=5, help="Sample rows to keep per node output.")
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES, help="Safety cap for nodes per request.")
    parser.add_argument("--include-raw", action="store_true", help="Include raw trigger/output payloads.")
    parser.add_argument("--output-path", type=Path, help="Where to write node preview JSON.")
    parser.add_argument("--json-only", action="store_true", help="Do not print the text summary.")
    args = parser.parse_args(argv)

    node_ids = parse_node_ids(args.node_id, args.node_ids)
    mode = runmode.resolve_mode(args, default="cached")
    report = build_preview_report(
        args.flow_url,
        node_ids,
        sample_tier=runmode.sample_tier(mode),
        timeout_seconds=args.timeout_seconds,
        row_limit=args.row_limit,
        include_raw=args.include_raw,
        node_names=args.node_name,
        max_nodes=args.max_nodes,
        analyze=runmode.should_compute(mode) and not args._legacy_no_analyze,
        from_nodes=args.from_nodes,
        fetch_existing=not args.status_only,
    )
    workflow = report.get("workflow", {})
    output = args.output_path or default_output_path(str(workflow.get("id") or "workflow"))
    save_json(report, output)
    if args.json_only:
        print(output)
    else:
        print_summary(report)
        print("")
        print(f"Wrote node preview JSON to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"node_previews: {exc}", file=sys.stderr)
        raise SystemExit(2)
