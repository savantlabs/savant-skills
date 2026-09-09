#!/usr/bin/env python3
"""Build a compact Savant workflow map.

This helper turns a Savant recipe into a small graph-oriented JSON report:
workflow metadata, nodes, groups, edges, sources, destinations, and terminal
steps. It is read-only and does not run Analyze/Test/Run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.cli import (  # noqa: E402
    SavantAppApiError,
    parse_flow_url,
    recipe_nodes,
    save_json,
)
from savant_api.fileio import workspace_tmp  # noqa: E402
from savant_api.recipe_input import assert_flow_id, load_recipe  # noqa: E402


STRUCTURAL_TYPES = {"group", "text"}
SOURCE_TYPES = {"source"}
DESTINATION_TYPES = {"destination", "outlet"}


def node_label(node: dict[str, Any]) -> str | None:
    for key in ("name", "label", "id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_map_input(*, flow_url: str | None, input_json: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The recipe to map, always from a file.

    This route used to accept a flow URL and fetch the recipe itself. It no longer reads the app
    API at all: the caller fetches the flow with the MCP `fetch` tool on savant://workflow/{flowId}
    and passes the resulting JSON. A flow URL may still be given, and is recorded as provenance,
    but it is not fetched.
    """
    recipe = load_recipe(input_json, flag="--input-json")
    source_context: dict[str, Any] = {"source": "file", "inputPath": str(input_json)}
    if flow_url:
        parsed = parse_flow_url(flow_url)
        source_context["flowUrl"] = flow_url
        source_context["namespace"] = parsed.namespace
        assert_flow_id(recipe, parsed.flow_id, flag="--input-json")
    return recipe, source_context


def source_refs_from_inlets(node: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    inlets = node.get("inlets")
    if not isinstance(inlets, list):
        return refs
    for inlet in inlets:
        if not isinstance(inlet, dict):
            continue
        sources = inlet.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            source_id = None
            outlet_id = None
            if isinstance(source, str):
                source_id = source
            elif isinstance(source, dict):
                source_id = source.get("nodeId") or source.get("source") or source.get("id")
                outlet_id = source.get("outletId") or source.get("outlet")
            if isinstance(source_id, str) and source_id:
                refs.append(
                    {
                        "sourceNodeId": source_id,
                        "sourceOutletId": outlet_id if isinstance(outlet_id, str) else None,
                        "targetInletId": inlet.get("id"),
                    }
                )
    return refs


def target_refs_from_outlets(node: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    outlets = node.get("outlets")
    if not isinstance(outlets, list):
        return refs
    for outlet in outlets:
        if not isinstance(outlet, dict):
            continue
        outlet_id = outlet.get("id")
        targets = outlet.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            target_id = None
            target_inlet_id = None
            if isinstance(target, str):
                target_id = target
            elif isinstance(target, dict):
                target_id = target.get("nodeId") or target.get("target") or target.get("id")
                target_inlet_id = target.get("inletId") or target.get("inlet")
            if isinstance(target_id, str) and target_id:
                refs.append(
                    {
                        "sourceOutletId": outlet_id if isinstance(outlet_id, str) else None,
                        "targetNodeId": target_id,
                        "targetInletId": target_inlet_id if isinstance(target_inlet_id, str) else None,
                    }
                )
    return refs


def build_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        for target in target_refs_from_outlets(node):
            key = (node_id, target["targetNodeId"], target.get("sourceOutletId"), target.get("targetInletId"))
            if key not in seen:
                edges.append(
                    {
                        "sourceNodeId": node_id,
                        "sourceOutletId": target.get("sourceOutletId"),
                        "targetNodeId": target["targetNodeId"],
                        "targetInletId": target.get("targetInletId"),
                    }
                )
                seen.add(key)
    if edges:
        return edges
    for node in nodes:
        target_id = node.get("id")
        if not isinstance(target_id, str):
            continue
        for source in source_refs_from_inlets(node):
            key = (source["sourceNodeId"], target_id, source.get("sourceOutletId"), source.get("targetInletId"))
            if key not in seen:
                edges.append(
                    {
                        "sourceNodeId": source["sourceNodeId"],
                        "sourceOutletId": source.get("sourceOutletId"),
                        "targetNodeId": target_id,
                        "targetInletId": source.get("targetInletId"),
                    }
                )
                seen.add(key)
    return edges


def compact_node(node: dict[str, Any], incoming: dict[str, list[dict[str, Any]]], outgoing: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    node_id = node.get("id")
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return {
        "id": node_id,
        "name": node_label(node),
        "type": node.get("type"),
        "groupId": node.get("parentId") or node.get("groupId"),
        "position": node.get("position") if isinstance(node.get("position"), dict) else None,
        "sourceDatasetId": config.get("id") if node.get("type") == "source" else None,
        "sourceDatasetName": config.get("name") if node.get("type") == "source" else None,
        "incoming": incoming.get(str(node_id), []),
        "outgoing": outgoing.get(str(node_id), []),
        "outletCount": len(node.get("outlets") or []) if isinstance(node.get("outlets"), list) else 0,
        "inletCount": len(node.get("inlets") or []) if isinstance(node.get("inlets"), list) else 0,
    }


def build_workflow_map(recipe: dict[str, Any], *, source_context: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes = [node for node in recipe_nodes(recipe) if isinstance(node, dict)]
    edges = build_edges(nodes)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        incoming[edge["targetNodeId"]].append(edge)
        outgoing[edge["sourceNodeId"]].append(edge)

    compact_nodes = [compact_node(node, incoming, outgoing) for node in nodes if isinstance(node.get("id"), str)]
    by_type = Counter(str(node.get("type") or "unknown") for node in nodes)
    terminal_ids = {node["id"] for node in compact_nodes if node.get("id") and not outgoing.get(str(node["id"]))}
    return {
        "task": "workflow_map",
        "sourceContext": source_context or {},
        "workflow": {
            "id": recipe.get("id"),
            "name": recipe.get("name"),
            "description": recipe.get("description"),
            "folderId": recipe.get("folderId"),
            "namespace": recipe.get("namespace"),
            "version": recipe.get("version"),
            "status": recipe.get("status"),
        },
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "byType": dict(sorted(by_type.items())),
        },
        "groups": [node for node in compact_nodes if node.get("type") == "group"],
        "sources": [node for node in compact_nodes if node.get("type") in SOURCE_TYPES],
        "destinations": [node for node in compact_nodes if node.get("type") in DESTINATION_TYPES],
        "terminalNodes": [node for node in compact_nodes if node.get("id") in terminal_ids],
        "edges": edges,
        "nodes": compact_nodes,
    }


def default_output_path(report: dict[str, Any]) -> Path:
    workflow = report.get("workflow") if isinstance(report.get("workflow"), dict) else {}
    label = workflow.get("id") or "workflow"
    return workspace_tmp("workflow-maps", f"{label}.map.json")


def print_summary(report: dict[str, Any]) -> None:
    workflow = report.get("workflow", {})
    counts = report.get("counts", {})
    print(f"Workflow: {workflow.get('name') or workflow.get('id')}")
    print(f"Nodes: {counts.get('nodes', 0)}")
    print(f"Edges: {counts.get('edges', 0)}")
    print(f"Sources: {len(report.get('sources') or [])}")
    print(f"Destinations: {len(report.get('destinations') or [])}")
    print(f"Terminal steps: {len(report.get('terminalNodes') or [])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flow_url", nargs="?",
                        help="Optional Savant flow URL, recorded as provenance and checked against "
                             "the JSON's flow id. Not fetched.")
    parser.add_argument("--input-json", type=Path, required=True,
                        help="The workflow JSON to map, fetched with the MCP `fetch` tool on "
                             "savant://workflow/{flowId}. This route never reads the API.")
    parser.add_argument("--output-path", type=Path, help="Where to write workflow map JSON.")
    parser.add_argument("--json-only", action="store_true", help="Do not print the text summary.")
    args = parser.parse_args(argv)

    recipe, source_context = load_map_input(flow_url=args.flow_url, input_json=args.input_json)
    report = build_workflow_map(recipe, source_context=source_context)
    output = args.output_path or default_output_path(report)
    save_json(report, output)
    if args.json_only:
        print(output)
    else:
        print_summary(report)
        print("")
        print(f"Wrote workflow map JSON to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"workflow_map: {exc}", file=sys.stderr)
        raise SystemExit(2)
