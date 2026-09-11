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
    _default_executions_output_path,
    _default_import_output_path,
    _default_execution_detail_output_path,
    _default_output_path,
    _default_save_report_path,
    load_json,
    save_json,
)
from savant_api.recipes import (
    assert_expected_model_diff,
    create_workflow_from_json,
    created_flow_id_from_import,
    import_recipe_json,
    list_folder_recipes,
    prepare_recipe_for_save,
    recipe_nodes,
    recipe_parameters,
    save_metadata,
    update_workflow_recipe,
)
from savant_api.recipe_input import assert_flow_id, load_recipe
from savant_api.session import (
    discover_session,
    ensure_rns,
    parse_flow_url,
    parse_savant_url,
)
from savant_api.sources import (
    create_source,
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
    (lambda a: bool(a.inspect_node), "--inspect-node"),
    (lambda a: a.list_executions, "--list-executions"),
    (lambda a: bool(a.execution_detail), "--execution-detail"),
    (lambda a: bool(a.import_json), "--import-json"),
    (lambda a: bool(a.save_recipe_from), "--save-recipe-from"),
    (lambda a: bool(a.save_metadata_from), "--save-metadata-from"),
)

# The operations that require a flow URL (.../flow/{flowId}); the rest accept a folder or flow URL.
_FLOW_URL_OPERATIONS = {
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
            "operation, e.g.: --list-executions, --inspect-node, --import-json, "
            "--save-recipe-from, --save-metadata-from.\n"
            "Reading a workflow is not one of them any more: use the MCP `fetch` tool on "
            "savant://workflow/{flowId}. Listing datasets and AI providers moved to MCP `search` "
            "with types: [\"source\"] / [\"ai_provider\"]. For dataset matching, feed those "
            "results to `savant.py dataset discover`."
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
            "required: --inspect-node, --list-executions, and "
            "--save-* need a flow URL. Optional otherwise: when omitted, the operation runs in the "
            "authenticated session's namespace (the credentials' namespace) — e.g. --import-json "
            "with --folder-id."
        ),
    )
    parser.add_argument("--output-path", type=Path, help="Where to write this operation's JSON result. Optional; defaults to a deterministic path under tmp/savant-api-exports/. Use --stdout to print the result inline instead.")
    parser.add_argument("--import-json", type=Path, help="Create a workflow by importing this workflow JSON through the API.")
    parser.add_argument("--folder-id", help="Target folder id, required for --import-json (use `home` for the Home folder/namespace root; `root` is a legacy alias). The workflow is created in the authenticated session's namespace. Find the id via MCP search/fetch on the folder entity.")
    parser.add_argument("--confirmed-namespace", help="Required for --import-json: namespace of the workspace the USER confirmed as the destination. Import is blocked if the session is in any other namespace — the destination workspace is user-named, never agent-chosen.")
    parser.add_argument("--no-import-poll", action="store_true", help="Do not poll the import promise after uploading.")
    parser.add_argument("--save-recipe-from", type=Path, help="Update an existing workflow from a full live-recipe JSON. Rejects creation-shaped workflow JSON.")
    parser.add_argument("--before-json", type=Path,
                        help="The pre-edit recipe, fetched with the MCP `fetch` tool on "
                             "savant://workflow/{flowId}. Required by --save-recipe-from: it proves "
                             "the requested change is non-empty before anything is written, and is "
                             "the baseline `workflow verify --before-json` diffs the result against.")
    parser.add_argument("--save-metadata-from", type=Path, help="Live-save flow metadata (name/description/tags) through PUT /api/recipes/{flowId}/metadata. description renders as Markdown.")
    parser.add_argument("--confirm-live-save", action="store_true", help="Required with --save-recipe-from to prevent accidental workflow mutation.")
    parser.add_argument("--list-executions", action="store_true", help="Write normalized Run/Test history for this workflow.")
    parser.add_argument(
        "--execution-types",
        action="append",
        help="Execution types to include: run, test, scheduled, run_now, or test_run. Can be comma-separated.",
    )
    parser.add_argument("--execution-detail", help="Fetch details for a specific execution id.")
    parser.add_argument("--inspect-node", action="append", default=[], help="Analyze a node id and write a compact output report.")
    parser.add_argument("--recipe-json", type=Path,
                        help="The flow's recipe, fetched with the MCP `fetch` tool on "
                             "savant://workflow/{flowId}. Required by --inspect-node, which "
                             "resolves node ids against it.")
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
    executions_path = None
    execution_detail_path = None
    stdout_payloads: dict[str, Any] = {}
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
                "API workflow creation requires --folder-id (use `home` for the Home folder). "
                "Find a folder's id via MCP search/fetch on the folder entity; the workflow is "
                "created in the authenticated session's namespace."
            )
        confirmed_ns = (args.confirmed_namespace or "").strip()
        if not confirmed_ns:
            raise SavantAppApiError(
                "API workflow creation requires --confirmed-namespace: the namespace of the "
                "workspace the USER confirmed as the destination. The destination workspace is "
                "user-named, never agent-chosen."
            )
        session_ns = (context.namespace or "").strip()
        if session_ns != confirmed_ns:
            raise SavantAppApiError(
                f"Session namespace `{session_ns or '(unknown)'}` does not match the "
                f"user-confirmed workspace namespace `{confirmed_ns}` — the session is not in "
                "the workspace the user confirmed as the destination. Switch back (MCP "
                "switch-workspace) or have the user explicitly name the new destination "
                "workspace; never retarget on your own."
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
            print(f"Imported {args.import_json} into folder {target_folder_id or '(Home folder)'}: {created}")
            print(f"Wrote import result to {import_path}")
        return 0

    if args.save_recipe_from:
        if not args.confirm_live_save:
            raise SavantAppApiError("--save-recipe-from requires --confirm-live-save.")
        desired = load_json(args.save_recipe_from)
        if not isinstance(desired, dict):
            raise SavantAppApiError("--save-recipe-from must point to a JSON object.")
        before = load_recipe(args.before_json, flag="--before-json")
        report = update_workflow_recipe(context, flow_id, desired, before=before)
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
        report = {
            "flowId": flow_id,
            "requestedName": desired.get("name"),
            "requestedDescriptionStart": (desired.get("description") or "")[:80],
            "requestedTags": desired.get("tags"),
            "saveResponse": save_response,
            # Whether the save landed is not knowable from here any more — it needs the flow read
            # back after the write, and this toolchain no longer reads recipes. The caller
            # re-fetches through MCP and runs the verify below, which diffs name/description/tags.
            "verified": False,
            "verifyCommand": (
                f"fetch savant://workflow/{flow_id} -> after.json, then: python3 savant.py workflow "
                f"verify --operation metadata --workflow-json after.json --expect-flow-id {flow_id} "
                f"--expect-metadata-json {args.save_metadata_from}"
            ),
        }
        report_path = args.output_path or _default_save_report_path(flow_id)
        save_json(report, report_path)
        if args.quiet:
            print(report_path)
        else:
            print(f"Saved metadata for {flow_id} (not yet verified); wrote report to {report_path}")
        return 0

    if (args.list_executions or args.execution_detail) and not args.inspect_node:
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
                or sources_path
                or connections_path
            )
        else:
            if sources_path:
                print(f"Wrote dataset discovery to {sources_path}")
            if executions_path:
                print(f"Wrote execution history to {executions_path}")
            if execution_detail_path:
                print(f"Wrote execution detail to {execution_detail_path}")
        return 0

    # Only --inspect-node reaches here. It needs the flow's recipe to resolve node ids, and takes
    # it as --recipe-json: exporting a recipe over the API is gone, because the MCP `fetch` tool on
    # savant://workflow/{flowId} returns the same document.
    if not args.inspect_node:
        raise SavantAppApiError("No supported operation matched the provided flags.")
    recipe = load_recipe(args.recipe_json, flag="--recipe-json")
    assert_flow_id(recipe, flow_id, flag="--recipe-json")
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
        inspection_path = (args.output_path or _default_output_path(flow_id)).with_suffix(".inspection.json")
        save_json(report, inspection_path)
    if args.quiet:
        print(inspection_path)
    else:
        print(f"Inspected {len(args.inspect_node)} node(s) of {flow_id} "
              f"({len(recipe_nodes(recipe))} node(s) in the recipe); wrote {inspection_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"savant api: {exc}", file=sys.stderr)
        raise SystemExit(2)
