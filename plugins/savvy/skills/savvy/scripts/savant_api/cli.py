#!/usr/bin/env python3
"""Internal Savant app API helper CLI."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from contracts.folder_target import is_root_folder_target
from savant_api.context import list_ai_providers
from savant_api.executions import (
    TERMINAL_NODE_STATUSES,
    _normalize_execution_types,
    analyze_and_fetch_many,
    analyze_and_fetch_node,
    fetch_node_output,
    get_execution,
    graph_status,
    list_recipe_executions,
    node_status_map,
    normalize_execution,
    poll_analysis_status,
    summarize_node_output,
    trigger_analysis,
)
from savant_api.httpclient import (
    _format_url_error,
    poll_promise,
    promise_id_from_response,
    promise_status_value,
    request,
    request_multipart,
)
from savant_api import runmode
from savant_api.fileio import (
    _default_ai_providers_output_path,
    _default_executions_output_path,
    _default_import_output_path,
    _default_execution_detail_output_path,
    _default_output_path,
    _default_save_report_path,
    _default_source_matches_output_path,
    load_json,
    save_json,
)
from savant_api.recipes import (
    assert_expected_model_diff,
    backup_recipe,
    create_workflow_from_json,
    created_flow_id_from_import,
    get_recipe,
    import_recipe_json,
    list_folder_recipes,
    prepare_recipe_for_save,
    recipe_nodes,
    recipe_parameters,
    save_metadata,
    update_workflow_recipe,
)
from savant_api.session import (
    discover_session,
    parse_flow_url,
    parse_savant_url,
)
from savant_api.sources import (
    create_source,
    discover_workflow_source_matches,
    upload_file_async,
)
from savant_api.models import (
    DEFAULT_ORIGIN,
    FlowUrl,
    SavantAppApiError,
    SavantSessionContext,
    SavantUrl,
)


# Every operation the `app` command can perform, paired with the flag that selects it. The command
# has no implicit default: at least one of these must be chosen, or it errors. Single source of
# truth for both the "you must pick an operation" guard and the per-operation URL-kind check below.
_OPERATIONS = (
    (lambda a: a.export_recipe, "--export-recipe"),
    (lambda a: bool(a.inspect_node), "--inspect-node"),
    (lambda a: a.list_ai_providers, "--list-ai-providers"),
    (lambda a: bool(a.discover_source_matches), "--discover-source-matches"),
    (lambda a: a.list_executions, "--list-executions"),
    (lambda a: bool(a.execution_detail), "--execution-detail"),
    (lambda a: bool(a.import_json), "--import-json"),
    (lambda a: bool(a.save_recipe_from), "--save-recipe-from"),
    (lambda a: bool(a.save_metadata_from), "--save-metadata-from"),
)

# The operations that require a flow URL (.../flow/{flowId}); the rest accept a folder or flow URL.
_FLOW_URL_OPERATIONS = {
    "--export-recipe",
    "--inspect-node",
    "--list-executions",
    "--save-recipe-from",
    "--save-metadata-from",
}


def _selected_operations(args: argparse.Namespace) -> list[str]:
    return [label for predicate, label in _OPERATIONS if predicate(args)]


def _require_operation(args: argparse.Namespace) -> None:
    """The app command has no implicit default — it must be told what to do, so a bare URL (the old
    "just export a recipe" magic) fails clearly instead of guessing."""
    if not _selected_operations(args):
        raise SavantAppApiError(
            "No operation specified. The app command does not default to anything — pass an "
            "operation, e.g.: --export-recipe (download the workflow JSON), "
            "--list-executions, --inspect-node, "
            "--discover-source-matches, --import-json, --save-recipe-from, --save-metadata-from."
        )


def _validate_url_kind_for_operation(args: argparse.Namespace, savant_url: SavantUrl) -> None:
    """Fail fast, before any API work, when a selected operation needs a flow URL but a folder URL
    was passed. Names the operation and the kind it got, replacing the generic late errors."""
    if savant_url.kind == "flow":
        return
    for label in _selected_operations(args):
        if label in _FLOW_URL_OPERATIONS:
            raise SavantAppApiError(
                f"{label} requires a Savant flow URL (.../flow/{{flowId}}). "
                f"You passed a {savant_url.kind} URL: {savant_url.url}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read a Savant workflow recipe through the internal app API.")
    parser.add_argument(
        "url",
        nargs="?",
        help=(
            "Savant flow URL (.../app/flow/{flowId}?rns=...) or folder URL "
            "(.../app/analysis?folderId={folderId}). The operation flag decides which kind is "
            "required: --export-recipe, --inspect-node, --list-executions, and "
            "--save-* need a flow URL. Optional otherwise: when omitted, the operation runs in the "
            "authenticated session's namespace (the credentials' namespace) — e.g. "
            "--list-ai-providers, or --import-json with --folder-id."
        ),
    )
    parser.add_argument("--export-recipe", action="store_true", help="Export (download) the flow's workflow JSON (the 'recipe'). Requires a flow URL.")
    parser.add_argument("--output-path", type=Path, help="Where to write this operation's JSON result. Optional; defaults to a deterministic path under tmp/savant-api-exports/. Use --stdout to print the result inline instead.")
    parser.add_argument("--import-json", type=Path, help="Create a workflow by importing this workflow JSON through the API.")
    parser.add_argument("--folder-id", help="Target folder id, required for --import-json (use `root` for the namespace root/Home). The workflow is created in the authenticated session's namespace. Find the id via MCP search/fetch on the folder entity.")
    parser.add_argument("--no-import-poll", action="store_true", help="Do not poll the import promise after uploading.")
    parser.add_argument("--save-recipe-from", type=Path, help="Update an existing workflow from a full live-recipe JSON. Rejects creation-shaped workflow JSON.")
    parser.add_argument("--save-metadata-from", type=Path, help="Live-save flow metadata (name/description/tags) through PUT /api/recipes/{flowId}/metadata. description renders as Markdown.")
    parser.add_argument("--confirm-live-save", action="store_true", help="Required with --save-recipe-from to prevent accidental workflow mutation.")
    parser.add_argument("--sources-current-page-only", action="store_true", help="Call /api/sources without showAll=true.")
    parser.add_argument("--list-ai-providers", action="store_true", help="Write the AI/LLM providers (id + name) available in this session's workspace.")
    parser.add_argument("--discover-source-matches", type=Path, help="Write dataset-match candidates for source nodes in this workflow JSON.")
    parser.add_argument("--source-match-limit", type=int, default=10, help="Maximum candidate datasets to keep per source match report.")
    parser.add_argument("--list-executions", action="store_true", help="Write normalized Run/Test history for this workflow.")
    parser.add_argument(
        "--execution-types",
        action="append",
        help="Execution types to include: run, test, scheduled, run_now, or test_run. Can be comma-separated.",
    )
    parser.add_argument("--execution-detail", help="Fetch details for a specific execution id.")
    parser.add_argument("--inspect-node", action="append", default=[], help="Analyze a node id and write a compact output report.")
    # `--inspect-node` run mode: cached/interactive/analyze, plus `--from` to recompute from a
    # changed node. The inspected node is itself the stopping node, so `--up-to` is not consumed
    # here. Legacy `--sample-tier`/`--force-analyze` survive as hidden aliases.
    runmode.add_run_mode_args(parser, default="interactive", legacy_analyze_flag=None, legacy_force_analyze=True)
    parser.add_argument("--quiet", action="store_true", help="Only print the output path.")
    parser.add_argument("--stdout", action="store_true", help="Also print the discovery result(s) as JSON to stdout, so a small result can be read in one call without a separate file read. The file is still written.")
    args = parser.parse_args(argv)

    savant_url = parse_savant_url(args.url) if args.url else None
    _require_operation(args)
    if savant_url is not None:
        _validate_url_kind_for_operation(args, savant_url)
    else:
        flow_ops = [label for label in _selected_operations(args) if label in _FLOW_URL_OPERATIONS]
        if flow_ops:
            raise SavantAppApiError(
                f"{', '.join(flow_ops)} require a Savant flow URL positional argument."
            )
    if savant_url is not None:
        context = discover_session(savant_url.namespace, origin=savant_url.origin)
    else:
        context = discover_session(None)
    flow_id = savant_url.flow_id if savant_url is not None else None
    sources_path = None
    connections_path = None
    source_matches_path = None
    executions_path = None
    execution_detail_path = None
    stdout_payloads: dict[str, Any] = {}
    if args.list_ai_providers:
        providers_path = args.output_path or _default_ai_providers_output_path(context.namespace)
        providers = list_ai_providers(context)
        save_json(providers, providers_path)
        stdout_payloads["aiProviders"] = providers
        if not args.stdout:
            names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in providers) or "(none)"
            print(f"Found {len(providers)} AI provider(s): {names}")
    if args.discover_source_matches:
        source_matches_path = args.output_path or _default_source_matches_output_path(args.discover_source_matches.stem)
        source_matches_data = discover_workflow_source_matches(
            context,
            args.discover_source_matches,
            show_all=not args.sources_current_page_only,
            candidate_limit=args.source_match_limit,
        )
        save_json(source_matches_data, source_matches_path)
        stdout_payloads["sourceMatches"] = source_matches_data
    if args.list_executions:
        executions_path = args.output_path or _default_executions_output_path(flow_id)
        executions = list_recipe_executions(context, flow_id, execution_types=args.execution_types)
        executions_data = {
            "flowId": flow_id,
            "namespace": context.namespace,
            "executionTypes": _normalize_execution_types(args.execution_types),
            "executions": executions,
        }
        save_json(executions_data, executions_path)
        stdout_payloads["executions"] = executions_data
    if args.execution_detail:
        execution_detail_path = args.output_path or _default_execution_detail_output_path(args.execution_detail)
        execution_detail_data = get_execution(context, args.execution_detail)
        save_json(execution_detail_data, execution_detail_path)
        stdout_payloads["executionDetail"] = execution_detail_data
    if args.import_json:
        if not args.folder_id:
            raise SavantAppApiError(
                "API workflow creation requires --folder-id (use `root` for the namespace root). "
                "Find a folder's id via MCP search/fetch on the folder entity; the workflow is "
                "created in the authenticated session's namespace."
            )
        target_folder_id = None if is_root_folder_target(args.folder_id) else args.folder_id
        import_result = create_workflow_from_json(
            context,
            args.import_json,
            folder_id=target_folder_id,
            poll=not args.no_import_poll,
        )
        import_path = args.output_path or _default_import_output_path(args.import_json)
        save_json(import_result, import_path)
        if args.quiet:
            print(import_result.get("flowUrl") or import_result.get("flowId") or import_path)
        else:
            created = import_result.get("flowUrl") or import_result.get("flowId") or "created flow id not returned by import promise"
            print(f"Imported {args.import_json} into folder {target_folder_id or '(namespace root)'}: {created}")
            print(f"Wrote import result to {import_path}")
        return 0

    if args.save_recipe_from:
        if not args.confirm_live_save:
            raise SavantAppApiError("--save-recipe-from requires --confirm-live-save.")
        desired = load_json(args.save_recipe_from)
        if not isinstance(desired, dict):
            raise SavantAppApiError("--save-recipe-from must point to a JSON object.")
        report = update_workflow_recipe(context, flow_id, desired)
        report_path = args.output_path or _default_save_report_path(flow_id)
        save_json(report, report_path)
        if args.quiet:
            print(report_path)
        else:
            print(f"Updated workflow {flow_id}; wrote verification report to {report_path}")
        return 0

    if args.save_metadata_from:
        if not args.confirm_live_save:
            raise SavantAppApiError("--save-metadata-from requires --confirm-live-save.")
        desired = load_json(args.save_metadata_from)
        if not isinstance(desired, dict):
            raise SavantAppApiError("--save-metadata-from must point to a JSON object.")
        desired_id = desired.get("id")
        if isinstance(desired_id, str) and desired_id and desired_id != flow_id:
            raise SavantAppApiError(f"Metadata id `{desired_id}` does not match URL flow id `{flow_id}`.")
        save_response = save_metadata(context, flow_id, desired)
        after = get_recipe(context, flow_id)
        report = {
            "flowId": flow_id,
            "requestedName": desired.get("name"),
            "requestedDescriptionStart": (desired.get("description") or "")[:80],
            "persistedName": after.get("name") if isinstance(after, dict) else None,
            "persistedDescriptionStart": (after.get("description") or "")[:80] if isinstance(after, dict) else None,
            "persistedTags": after.get("tags") if isinstance(after, dict) else None,
            "saveResponse": save_response,
        }
        report_path = args.output_path or _default_save_report_path(flow_id)
        save_json(report, report_path)
        if args.quiet:
            print(report_path)
        else:
            print(f"Saved metadata for {flow_id}; wrote verification report to {report_path}")
        return 0

    if (
        args.list_ai_providers
        or args.discover_source_matches
        or args.list_executions
        or args.execution_detail
    ) and not args.inspect_node:
        if args.stdout:
            if stdout_payloads:
                payload = next(iter(stdout_payloads.values())) if len(stdout_payloads) == 1 else stdout_payloads
            else:
                payload = None
            print(json.dumps(payload, indent=2))
            return 0
        if args.quiet:
            print(
                execution_detail_path
                or executions_path
                or source_matches_path
                or sources_path
                or connections_path
            )
        else:
            if sources_path:
                print(f"Wrote dataset discovery to {sources_path}")
            if source_matches_path:
                print(f"Wrote source match discovery to {source_matches_path}")
            if executions_path:
                print(f"Wrote execution history to {executions_path}")
            if execution_detail_path:
                print(f"Wrote execution detail to {execution_detail_path}")
        return 0

    # Only --export-recipe and --inspect-node reach here; both need the flow's recipe. The
    # operation guard above and the upfront URL-kind check guarantee a flow URL, so flow_id is set.
    if not (args.export_recipe or args.inspect_node):
        raise SavantAppApiError("No supported operation matched the provided flags.")
    recipe = get_recipe(context, flow_id)
    output = None
    if args.export_recipe:
        output = args.output_path or _default_output_path(flow_id)
        save_json(recipe, output)
    inspection_path = None
    if args.inspect_node:
        mode = runmode.resolve_mode(args, default="interactive")
        force_analyze = getattr(args, "_legacy_force_analyze", False)
        report = {
            node_id: analyze_and_fetch_node(
                context,
                recipe,
                flow_id,
                node_id,
                sample_tier=runmode.sample_tier(mode),
                starting_nodes=args.from_nodes or None,
                reuse_ready=not force_analyze,
            )
            for node_id in args.inspect_node
        }
        inspection_path = (output or args.output_path or _default_output_path(flow_id)).with_suffix(".inspection.json")
        save_json(report, inspection_path)
    if args.quiet:
        print(output or inspection_path)
    else:
        node_count = len(recipe_nodes(recipe))
        if output:
            print(f"Exported {flow_id} with {node_count} node(s) to {output}")
        if inspection_path:
            print(f"Inspected {len(args.inspect_node)} node(s); wrote {inspection_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"savant api: {exc}", file=sys.stderr)
        raise SystemExit(2)
