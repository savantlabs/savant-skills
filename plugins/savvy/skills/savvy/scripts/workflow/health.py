#!/usr/bin/env python3
"""Read-only Savant workflow health check.

This helper gathers the first-pass evidence an inspector usually needs before
drilling into a workflow:

- recipe/status/version/run history
- source placeholder and dataset-match health
- optional one serial Analyze preview at the earliest useful checkpoint

It intentionally avoids parallel Analyze calls. The goal is to find the first
likely blocker quickly, then stop with a concise report.
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

from savant_api.cli import (  # noqa: E402
    SavantAppApiError,
    analyze_and_fetch_node,
    discover_session,
    get_recipe,
    list_recipe_executions,
    parse_flow_url,
    recipe_nodes,
    save_json,
)
from savant_api.sources import list_sources  # noqa: E402
from workflow.discovery import build_discovery_report  # noqa: E402
from savant_api.fileio import workspace_tmp  # noqa: E402
from savant_api import runmode  # noqa: E402


SOURCE_TYPES = {"source"}
STRUCTURAL_TYPES = {"group", "text"}


def node_label(node: dict[str, Any]) -> str:
    for key in ("name", "label", "id"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unnamed step"


def source_config_name(node: dict[str, Any]) -> str | None:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for value in (node.get("name"), config.get("name"), config.get("id")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def source_has_embedded_schema(node: dict[str, Any]) -> bool:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    schema = config.get("schema")
    return isinstance(schema, list) and bool(schema)


def source_connector(node: dict[str, Any]) -> str | None:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    value = config.get("connector") or config.get("type")
    return value if isinstance(value, str) and value.strip() else None


def source_nodes(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in recipe_nodes(recipe) if isinstance(node, dict) and node.get("type") in SOURCE_TYPES]


def non_structural_nodes(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        node
        for node in recipe_nodes(recipe)
        if isinstance(node, dict) and node.get("type") not in STRUCTURAL_TYPES
    ]


def map_source_matches(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matches = report.get("sources")
    if not isinstance(matches, list):
        return {}
    return {
        str(match.get("node_id")): match
        for match in matches
        if isinstance(match, dict) and match.get("node_id")
    }


def best_candidate(match: dict[str, Any]) -> dict[str, Any] | None:
    search = match.get("dataset_search") if isinstance(match.get("dataset_search"), dict) else {}
    candidates = search.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        return candidates[0]
    return None


def source_health(recipe: dict[str, Any], source_match_report: dict[str, Any]) -> list[dict[str, Any]]:
    matches = map_source_matches(source_match_report)
    rows: list[dict[str, Any]] = []
    for node in source_nodes(recipe):
        node_id = node.get("id")
        match = matches.get(str(node_id), {})
        status = match.get("match_status") or "unknown"
        candidate = best_candidate(match) if isinstance(match, dict) else None
        config_name = source_config_name(node)
        issues: list[str] = []
        if status in {"missing", "ambiguous", "unknown"}:
            issues.append(f"dataset match is {status}")
        if config_name and "." in Path(config_name).name:
            issues.append("source name looks like an imported file placeholder")
        if source_has_embedded_schema(node) and status != "matched":
            issues.append("recipe has embedded schema, but no unique dataset binding was confirmed")
        rows.append(
            {
                "nodeId": node_id,
                "name": node_label(node),
                "connector": source_connector(node),
                "matchStatus": status,
                "matchedDatasetId": match.get("matched_dataset_id") if isinstance(match, dict) else None,
                "matchedDatasetName": match.get("matched_dataset_name") if isinstance(match, dict) else None,
                "bestCandidate": candidate,
                "issues": issues,
            }
        )
    return rows


def choose_preview_node(recipe: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, str] | None:
    for source in sources:
        if source.get("issues") and isinstance(source.get("nodeId"), str):
            return {
                "nodeId": source["nodeId"],
                "name": str(source.get("name") or source["nodeId"]),
                "reason": "first source with unresolved binding/match issue",
            }
    source_list = source_nodes(recipe)
    if source_list:
        first = source_list[0]
        return {
            "nodeId": str(first.get("id")),
            "name": node_label(first),
            "reason": "first source checkpoint",
        }
    for node in non_structural_nodes(recipe):
        node_id = node.get("id")
        if isinstance(node_id, str):
            return {
                "nodeId": node_id,
                "name": node_label(node),
                "reason": "first non-structural checkpoint",
            }
    return None


def compact_preview_error(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    status_code = None
    for code in ("429", "500", "404", "403", "401"):
        if f" {code} " in message or message.startswith(code) or f": {code} " in message:
            status_code = int(code)
            break
    return {
        "status": "failed",
        "error": message,
        "httpStatus": status_code,
    }


def build_recommendations(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    problematic_sources = [
        source
        for source in report.get("sources", [])
        if isinstance(source, dict) and source.get("issues")
    ]
    if problematic_sources:
        bind_parts = []
        for source in problematic_sources:
            candidate = source.get("bestCandidate") if isinstance(source.get("bestCandidate"), dict) else None
            if candidate and candidate.get("name"):
                bind_parts.append(f"{source.get('name')} -> {candidate.get('name')}")
        if bind_parts:
            recommendations.append("Bind source datasets: " + "; ".join(bind_parts) + ".")
        else:
            recommendations.append("Resolve missing or ambiguous source datasets before inspecting downstream steps.")
    preview = report.get("preview")
    if isinstance(preview, dict) and preview.get("status") == "failed":
        recommendations.append("Do not debug downstream joins, summaries, or destinations until the first failing checkpoint previews successfully.")
    if not recommendations:
        recommendations.append("Sources did not show an obvious binding issue; inspect the first grain-changing step next.")
    return recommendations


def health_status(report: dict[str, Any]) -> str:
    if any(source.get("issues") for source in report.get("sources", []) if isinstance(source, dict)):
        return "source_attention_required"
    preview = report.get("preview")
    if isinstance(preview, dict) and preview.get("status") == "failed":
        return "preview_failed"
    return "no_first-pass_blocker_found"


def print_summary(report: dict[str, Any]) -> None:
    workflow = report.get("workflow", {})
    print(f"Workflow: {workflow.get('name') or workflow.get('id')}")
    print(f"Status: {workflow.get('status') or 'unknown'}")
    print(f"Version: {workflow.get('version') or 'unknown'}")
    executions = report.get("executionHistory", {}).get("executions") if isinstance(report.get("executionHistory"), dict) else []
    print(f"Run/Test history: {len(executions) if isinstance(executions, list) else 0} execution(s)")
    print(f"Health: {report.get('health')}")
    print("")
    print("Sources:")
    for source in report.get("sources", []):
        if not isinstance(source, dict):
            continue
        candidate = source.get("bestCandidate") if isinstance(source.get("bestCandidate"), dict) else None
        suffix = f"; best match: {candidate.get('name')}" if candidate and candidate.get("name") else ""
        issues = "; ".join(source.get("issues") or []) or "no first-pass issue"
        print(f"- {source.get('name')}: {source.get('matchStatus')}{suffix} ({issues})")
    preview = report.get("preview")
    if isinstance(preview, dict):
        print("")
        print(f"Preview checkpoint: {preview.get('name')} ({preview.get('reason')})")
        if preview.get("status") == "passed":
            output = preview.get("output") if isinstance(preview.get("output"), dict) else {}
            print(f"Preview result: passed, {output.get('rowCount', 0)} row(s)")
        elif preview.get("status") == "skipped":
            print(f"Preview result: skipped ({preview.get('reason')})")
        else:
            print(f"Preview result: failed ({preview.get('error')})")
    print("")
    print("Recommended next step:")
    for item in report.get("recommendations", []):
        print(f"- {item}")


def build_health_report(
    flow_url: str,
    *,
    sample_tier: str = "1k",
    preview: bool = False,
    preview_timeout_seconds: int = 60,
) -> dict[str, Any]:
    parsed = parse_flow_url(flow_url)
    context = discover_session(parsed.namespace, origin=parsed.origin)
    recipe = get_recipe(context, parsed.flow_id)
    source_match_report = build_discovery_report(recipe, list_sources(context), limit=10)
    sources = source_health(recipe, source_match_report)
    execution_types = ["run_now", "scheduled", "test_run"]
    report: dict[str, Any] = {
        "task": "savant_workflow_health_check",
        "flowUrl": flow_url,
        "workflow": {
            "id": recipe.get("id") or parsed.flow_id,
            "name": recipe.get("name"),
            "status": recipe.get("status"),
            "version": recipe.get("version"),
            "nodeCount": len(recipe_nodes(recipe)),
            "namespace": context.namespace,
            "workspaceId": context.workspace_id,
        },
        "executionHistory": {
            "executionTypes": execution_types,
            "executions": list_recipe_executions(context, parsed.flow_id, execution_types=execution_types),
        },
        "sourceMatchReport": source_match_report,
        "sources": sources,
    }
    checkpoint = choose_preview_node(recipe, sources)
    if not preview:
        report["preview"] = {"status": "skipped", "reason": "preview disabled by caller"}
    elif checkpoint is None:
        report["preview"] = {"status": "skipped", "reason": "no preview checkpoint found"}
    else:
        preview_result: dict[str, Any] = {**checkpoint}
        try:
            inspected = analyze_and_fetch_node(
                context,
                recipe,
                parsed.flow_id,
                checkpoint["nodeId"],
                sample_tier=sample_tier,
                timeout_seconds=preview_timeout_seconds,
            )
            preview_result.update(inspected)
            preview_result["status"] = "passed" if inspected.get("status", {}).get("status") == "Ready" else "not_ready"
        except Exception as exc:  # keep health checks diagnostic, not crash-only
            preview_result.update(compact_preview_error(exc))
        report["preview"] = preview_result
    report["health"] = health_status(report)
    report["recommendations"] = build_recommendations(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flow_url", help="Savant flow URL to inspect.")
    parser.add_argument("--output-path", type=Path, help="Where to write health-check JSON.")
    # Health defaults to no-compute: it reads recipe/status/version/run-history/source matches.
    # `--mode interactive|analyze` opts into the single earliest-checkpoint preview.
    runmode.add_run_mode_args(parser, default="cached", legacy_analyze_flag="--analyze-preview")
    parser.add_argument("--preview-timeout-seconds", type=int, default=60)
    parser.add_argument("--skip-preview", action="store_true", help="Compatibility flag; preview is skipped unless a compute mode is set.")
    parser.add_argument("--json-only", action="store_true", help="Do not print the text summary.")
    args = parser.parse_args(argv)

    mode = runmode.resolve_mode(args, default="cached")
    report = build_health_report(
        args.flow_url,
        sample_tier=runmode.sample_tier(mode),
        preview=runmode.should_compute(mode) and not args.skip_preview,
        preview_timeout_seconds=args.preview_timeout_seconds,
    )
    output = args.output_path or workspace_tmp("savant-health-checks", f"{report['workflow']['id']}.health.json")
    save_json(report, output)
    if args.json_only:
        print(output)
    else:
        print_summary(report)
        print("")
        print(f"Wrote health check JSON to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"savant_workflow_health_check: {exc}", file=sys.stderr)
        raise SystemExit(2)
