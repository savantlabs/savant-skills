#!/usr/bin/env python3
"""Suggest Savant workflow validation checkpoints from recipe structure.

This helper is read-only and recipe-derived. It does not run Analyze/Test/Run.
Use its output as a starting point for inspection or Creator verification; the
calling skill still decides which checkpoints are relevant to the user's task.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.cli import SavantAppApiError, save_json  # noqa: E402
from savant_api.fileio import workspace_tmp  # noqa: E402
from workflow.map import build_workflow_map, load_recipe  # noqa: E402


HIGH_VALUE_TYPES = {
    "source",
    "filter",
    "blend",
    "join",
    "summarize",
    "rollup",
    "pivot",
    "deduplicate",
    "destination",
    "outlet",
}
TRANSFORM_TYPES = {"edit", "format", "json", "xml", "unpivot", "explode", "sample"}


def outgoing_outlet_preview_ids(node: dict[str, Any]) -> list[str]:
    preview_ids: list[str] = []
    for edge in node.get("outgoing") or []:
        if not isinstance(edge, dict):
            continue
        outlet_id = edge.get("sourceOutletId")
        if isinstance(outlet_id, str) and outlet_id:
            preview_id = f"{node.get('id')}|{outlet_id}"
            if preview_id not in preview_ids:
                preview_ids.append(preview_id)
    return preview_ids


def add_target(
    targets: list[dict[str, Any]],
    node: dict[str, Any],
    *,
    role: str,
    reason: str,
    priority: int,
    preview_node_ids: list[str] | None = None,
) -> None:
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        return
    previews = preview_node_ids or [node_id]
    key = (node_id, role)
    if any((target.get("nodeId"), target.get("role")) == key for target in targets):
        return
    targets.append(
        {
            "nodeId": node_id,
            "name": node.get("name"),
            "type": node.get("type"),
            "role": role,
            "reason": reason,
            "priority": priority,
            "previewNodeIds": previews,
        }
    )


def build_targets(workflow_map: dict[str, Any]) -> dict[str, Any]:
    nodes = workflow_map.get("nodes") if isinstance(workflow_map.get("nodes"), list) else []
    targets: list[dict[str, Any]] = []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        incoming_count = len(node.get("incoming") or [])
        outgoing_count = len(node.get("outgoing") or [])
        if node_type == "source":
            add_target(targets, node, role="source", reason="Confirms source data is bound and previewable.", priority=10)
        elif node_type in {"blend", "join"}:
            add_target(
                targets,
                node,
                role="join_or_blend",
                reason="Confirms row preservation, matching behavior, and joined output grain.",
                priority=30,
            )
        elif node_type == "filter":
            outlet_previews = outgoing_outlet_preview_ids(node)
            add_target(
                targets,
                node,
                role="branching_filter",
                reason="Confirms kept/dropped row counts and branch behavior.",
                priority=35,
                preview_node_ids=outlet_previews or [str(node.get("id"))],
            )
        elif node_type in {"summarize", "rollup", "pivot"}:
            add_target(
                targets,
                node,
                role="grain_change",
                reason="Confirms output grain, group-by keys, and aggregate row count.",
                priority=40,
            )
        elif node_type == "deduplicate":
            add_target(
                targets,
                node,
                role="row_reduction",
                reason="Confirms duplicate handling and row-count reduction.",
                priority=45,
            )
        elif node_type in {"destination", "outlet"}:
            add_target(targets, node, role="final_output", reason="Confirms final output shape before delivery.", priority=60)
        elif node_type in TRANSFORM_TYPES and outgoing_count > 0:
            add_target(
                targets,
                node,
                role="transform_checkpoint",
                reason="Confirms transformed columns and representative values after cleanup.",
                priority=50,
            )
        elif incoming_count > 1:
            add_target(
                targets,
                node,
                role="multi_input_checkpoint",
                reason="Confirms behavior after multiple upstream paths converge.",
                priority=55,
            )

    terminal_nodes = workflow_map.get("terminalNodes") if isinstance(workflow_map.get("terminalNodes"), list) else []
    for node in terminal_nodes:
        if isinstance(node, dict) and node.get("type") not in {"group", "text", "destination", "outlet"}:
            add_target(
                targets,
                node,
                role="terminal_checkpoint",
                reason="Terminal processing step with no downstream target; likely final report-shaping output.",
                priority=65,
            )

    targets.sort(key=lambda item: (int(item.get("priority") or 999), str(item.get("name") or item.get("nodeId"))))
    preview_ids: list[str] = []
    for target in targets:
        for preview_id in target.get("previewNodeIds") or []:
            if isinstance(preview_id, str) and preview_id not in preview_ids:
                preview_ids.append(preview_id)
    return {
        "task": "workflow_targets",
        "workflow": workflow_map.get("workflow"),
        "sourceContext": workflow_map.get("sourceContext"),
        "targetCount": len(targets),
        "targets": targets,
        "suggestedPreviewNodeIds": preview_ids,
        "nodePreviewsCommandHint": (
            "python3 savant.py preview nodes <flow-url> "
            f"--node-ids '{json.dumps(preview_ids)}'"
            if preview_ids
            else None
        ),
    }


def default_output_path(report: dict[str, Any]) -> Path:
    workflow = report.get("workflow") if isinstance(report.get("workflow"), dict) else {}
    label = workflow.get("id") or "workflow"
    return workspace_tmp("workflow-targets", f"{label}.targets.json")


def print_summary(report: dict[str, Any]) -> None:
    workflow = report.get("workflow", {})
    print(f"Workflow: {workflow.get('name') or workflow.get('id')}")
    print(f"Suggested targets: {report.get('targetCount', 0)}")
    for target in (report.get("targets") or [])[:12]:
        if isinstance(target, dict):
            print(f"- {target.get('name') or target.get('nodeId')}: {target.get('role')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flow_url", nargs="?", help="Savant flow URL to analyze.")
    parser.add_argument("--input-json", type=Path, help="Local workflow JSON file to analyze instead of a live flow URL.")
    parser.add_argument("--map-output", type=Path, help="Optional path to also write the workflow map JSON.")
    parser.add_argument("--output-path", type=Path, help="Where to write workflow targets JSON.")
    parser.add_argument("--json-only", action="store_true", help="Do not print the text summary.")
    args = parser.parse_args(argv)

    recipe, source_context = load_recipe(flow_url=args.flow_url, input_json=args.input_json)
    workflow_map = build_workflow_map(recipe, source_context=source_context)
    if args.map_output:
        save_json(workflow_map, args.map_output)
    report = build_targets(workflow_map)
    output = args.output_path or default_output_path(report)
    save_json(report, output)
    if args.json_only:
        print(output)
    else:
        print_summary(report)
        print("")
        print(f"Wrote workflow targets JSON to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"workflow_targets: {exc}", file=sys.stderr)
        raise SystemExit(2)
