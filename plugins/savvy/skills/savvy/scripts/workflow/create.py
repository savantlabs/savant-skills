#!/usr/bin/env python3
"""Creator orchestrator — chains the deterministic create-and-verify loop in one call.

Two phases, with the user-confirmation gate between them:

  PREFLIGHT (always): validate the workflow JSON, resolve the exact target
  folder + session, and check for blockers (validation errors, or an AI-backed
  node with a missing providerId). Emits a
  summary. It does NOT import.

  CREATE + VERIFY (only with --confirm-import, and only if preflight is clean): import the JSON
  into the folder, then run the shared post-write evidence loop over the created flow: re-fetch
  and save the live recipe JSON and inspect terminal/output previews. This is the same evidence
  path used by workflow edit after it saves a recipe. Layout quality is judged from `validate
  workflow` (which runs the deterministic layout checks) on the persisted JSON — no rendered-canvas inspection.

Creation is folder-bound: the imported workflow must read back with the same folder id the user
specified. A different or missing folder id is a hard failure, not a successful create.

Datasets are already bound in the JSON (each source node carries a resolved dataset id), so this
orchestrator does no dataset discovery, matching, or binding — Creator is dataset-free. Pass
`--confirm-import` only AFTER the user has confirmed creation in chat. INTERNAL ONLY: uses the
authenticated Savant API.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from savant_api import cli as api
from savant_api import capabilities as savant_capabilities
from savant_api import sources as sources_api
from contracts.folder_target import is_root_folder_target
from savant_api.fileio import workspace_tmp
from workflow import evidence as workflow_evidence
from workflow import inspection as savant_inspect
from validators import workflow as vw

_CREATE_STATUSES = {
    "verified",
    "created-with-issues",
    "imported",
    "import-unverified",
}


def preflight(json_path: str, *, folder_id: str):
    wf = json.loads(Path(json_path).read_text(encoding="utf-8"))
    nodes = [n for n in (wf.get("nodes") or []) if isinstance(n, dict)]
    errors, warnings = vw.validate(Path(json_path), block_documentation_gaps=True)
    missing_ai_providers = vw.ai_missing_provider_nodes(nodes)
    placeholder_sources = vw.source_placeholder_nodes(nodes)

    capability = savant_capabilities.detect()
    api_enabled = bool(capability.get("api_enabled"))
    ctx = None
    # The target workspace/namespace is the authenticated session's — the credentials' namespace,
    # the same one create and fetch all operate in. `root`/`home` targets the namespace root
    # (Home), which the import API represents as a null folder id. The folder id itself is not
    # pre-resolved here: create_workflow_from_json reads the created workflow back and hard-fails
    # unless created.folderId equals the requested id, so a bad/foreign id is caught at import.
    root_target = is_root_folder_target(folder_id)
    folder: dict = {"id": None, "path": "(namespace root)"} if root_target else {"id": folder_id, "path": None}
    if api_enabled:
        ctx = api.discover_session(None)

    # Dataset ids are WORKSPACE-scoped. A real-looking id from another workspace
    # does not resolve in the import target and Savant silently DROPS that source
    # node (verified live 2026-06-10: four sources discovered via one folder,
    # imported via another — all four vanished, twice, before this check existed).
    # Resolve every bound id against the target workspace BEFORE import.
    unresolved_sources: list[str] = []
    # AI providers are WORKSPACE-scoped too: a `providerId` copied from another workspace's
    # export looks real but does not resolve here, and Savant silently DROPS the AI node on
    # import. Resolve every bound providerId against the target workspace BEFORE import. Trial
    # providers (`savant_*`) are platform-stable and always returned, so the builder default
    # never false-positives.
    unresolved_ai_providers: list[str] = []
    if ctx is not None:
        workspace_ids = sources_api.workspace_dataset_ids(ctx)
        if workspace_ids:
            unresolved_sources = vw.unresolved_source_dataset_ids(nodes, workspace_ids)
        provider_ids = {p.get("id") for p in api.list_ai_providers(ctx) if isinstance(p, dict) and p.get("id")}
        if provider_ids:
            unresolved_ai_providers = vw.unresolved_ai_provider_nodes(nodes, provider_ids)

    blocked_reasons = []
    if not api_enabled:
        blocked_reasons.append(
            "Savant API is not enabled for this session/package; workflow creation through the API is unavailable."
        )
    if errors:
        blocked_reasons.append(f"{len(errors)} validation error(s)")
    if missing_ai_providers:
        blocked_reasons.append(f"missing AI provider on: {', '.join(missing_ai_providers)} "
                               "(resolve the workspace provider or use the Savant Trial default before import)")
    if placeholder_sources:
        blocked_reasons.append(f"placeholder/missing source dataset id on: {', '.join(placeholder_sources)} "
                               "(supply a real dataset_id from Planner/dataset discovery before import)")
    if unresolved_sources:
        blocked_reasons.append(
            f"source dataset id(s) do not resolve in the TARGET workspace: {', '.join(unresolved_sources)} "
            "(datasets are workspace-scoped; discover or create them in the target workspace — "
            "importing anyway silently drops these source nodes)"
        )
    if unresolved_ai_providers:
        blocked_reasons.append(
            f"AI provider id(s) do not resolve in the TARGET workspace: {', '.join(unresolved_ai_providers)} "
            "(providers are workspace-scoped; use a provider from the target workspace's list_ai_providers "
            "or the Savant Trial default — importing anyway silently drops these AI nodes)"
        )
    report = {
        "phase": "preflight",
        "validation": {"errors": errors, "warnings": warnings},
        "folder": {"id": folder.get("id"), "path": folder.get("path")},
        "namespace": ctx.namespace if ctx is not None else None,
        "capability": capability,
        "missingAiProviders": missing_ai_providers,
        "sourceDatasetPlaceholders": placeholder_sources,
        "sourceDatasetUnresolvedInWorkspace": unresolved_sources,
        "aiProvidersUnresolvedInWorkspace": unresolved_ai_providers,
        "nodeCount": len([n for n in nodes if n.get("type") not in ("group", "text", "outlet")]),
        "blocked": bool(blocked_reasons),
        "blockedReasons": blocked_reasons,
    }
    return report, ctx, folder


def default_output_path(import_json: str | Path) -> Path:
    stem = Path(import_json).stem or "workflow"
    return workspace_tmp("workflow-create", f"{stem}.create.json")


def _workflow_name(json_path: str | Path) -> str:
    wf = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return str(wf.get("name") or Path(json_path).stem or "").strip()


def _session_tmp_root() -> Path:
    return workspace_tmp()


def duplicate_import_candidates(*, workflow_name: str, folder_id: str, report_path: Path) -> list[dict]:
    """Return same-session live creates for the same workflow name and folder.

    Creator must not use repeated imports as an iteration loop. This guard is intentionally scoped
    to the current AI session tmp tree because that is where the helper has durable evidence of
    flows it created during this run.
    """
    candidates: list[dict] = []
    root = _session_tmp_root()
    if not root.exists():
        return candidates
    resolved_report = report_path.resolve()
    for path in root.rglob("*.json"):
        try:
            if path.resolve() == resolved_report:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("phase") != "create":
            continue
        if data.get("status") not in _CREATE_STATUSES:
            continue
        existing_folder = str((data.get("folder") or {}).get("id") or data.get("verifiedFolderId") or "")
        existing_name = str(data.get("workflowName") or "").strip()
        if not existing_name and isinstance(data.get("importJson"), str):
            try:
                existing_name = _workflow_name(data["importJson"])
            except Exception:  # noqa: BLE001 - best-effort compatibility with older reports.
                existing_name = Path(data["importJson"]).stem
        if existing_folder == str(folder_id) and existing_name == workflow_name and data.get("flowUrl"):
            candidates.append({
                "reportPath": str(path),
                "status": data.get("status"),
                "flowId": data.get("flowId"),
                "flowUrl": data.get("flowUrl"),
            })
    return candidates


def create_status(*, data_verified: bool | None, skip_inspect: bool) -> str:
    if skip_inspect:
        return "imported"
    if data_verified:
        return "verified"
    return "created-with-issues"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--import-json", required=True, help="Workflow JSON to create.")
    p.add_argument("--folder-id", required=True, help="Target folder id, or `root` for the namespace root (Home). The workflow is created in the authenticated session's namespace. Find the id via MCP search/fetch on the folder entity.")
    p.add_argument("--confirm-import", action="store_true",
                   help="Proceed past preflight to import + verify. Set ONLY after the user confirmed creation in chat.")
    p.add_argument("--expect-columns", help="Comma-separated expected final output columns (for the inspect contract).")
    p.add_argument("--expected-outputs-json", help="JSON list/object of output contracts, or a handoff containing builder_preflight.output_destination_plan.outputs.")
    p.add_argument("--checkpoint", action="append", default=[], help="Deterministic stage NAME to verify (repeatable).")
    p.add_argument("--no-terminal-preview", action="store_true",
                   help="On --confirm-import, skip the default terminal output preview and inspect only named checkpoints/contracts.")
    p.add_argument("--sample-tier", default="1k")
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--skip-inspect", action="store_true", help="Import only; do not run the verification pass.")
    p.add_argument("--allow-duplicate-import", action="store_true",
                   help="Allow creating another live workflow with the same name in the same folder during this AI session. Use only after explicit user confirmation.")
    p.add_argument("--post-save-recipe-path", type=Path,
                   help="Override where --confirm-import writes the re-fetched created workflow JSON.")
    p.add_argument("--no-post-save-recipe", action="store_true",
                   help="On --confirm-import, skip writing the re-fetched created workflow JSON.")
    p.add_argument("--output-path", type=Path, help="Where to write the JSON report.")
    args = p.parse_args(argv)

    report_path = args.output_path or default_output_path(args.import_json)

    report, ctx, folder = preflight(args.import_json, folder_id=args.folder_id)

    def emit(rep):
        api.save_json(rep, report_path)
        print(f"CREATE [{rep['phase']}] folder={rep.get('folder',{}).get('path') or rep.get('folder',{}).get('id')}")
        v = rep.get("validation", {})
        if rep["phase"] != "create":
            print(f"  validation: {len(v.get('errors', []))} errors, {len(v.get('warnings', []))} warnings")
            for e in v.get("errors", []):
                print(f"    ERROR: {e}")
            for w in v.get("warnings", []):
                print(f"    warn: {w}")
            if rep["blocked"]:
                print("  BLOCKED:")
                for r in rep["blockedReasons"]:
                    print(f"    - {r}")

    # Preflight blocked, or not yet confirmed -> stop before import.
    if report["blocked"]:
        emit(report)
        print("  -> resolve the blockers above, then re-run.")
        return 2
    workflow_name = _workflow_name(args.import_json)
    duplicates = duplicate_import_candidates(
        workflow_name=workflow_name,
        folder_id=str(folder.get("id") or ""),
        report_path=report_path,
    )
    report["workflowName"] = workflow_name
    report["sameSessionExistingCreates"] = duplicates
    if not args.confirm_import:
        emit(report)
        if duplicates:
            print("  duplicate guard:")
            for item in duplicates:
                print(f"    [{item['status']}] {item['flowUrl']}")
            print("  -> this name/folder already has a same-session create; inspect/edit it instead of creating another copy.")
            return 2
        print("  -> preflight clean. Confirm creation with the user, then re-run with --confirm-import.")
        return 0

    if duplicates and not args.allow_duplicate_import:
        blocked = {
            "phase": "duplicate-import-guard",
            "status": "blocked",
            "workflowName": workflow_name,
            "folder": report["folder"],
            "existingCreates": duplicates,
            "nextActions": [
                "Inspect or edit the already-created workflow instead of creating another copy.",
                "If the user explicitly confirms a replacement copy is desired, rerun with --allow-duplicate-import.",
            ],
        }
        api.save_json(blocked, report_path)
        print(f"CREATE BLOCKED: same-session workflow already exists — {workflow_name}")
        for item in duplicates:
            print(f"  [{item['status']}] {item['flowUrl']}")
        print("  -> inspect/edit the existing workflow, or rerun with --allow-duplicate-import after explicit user confirmation.")
        return 2

    # Create + verify.
    import_result = api.create_workflow_from_json(ctx, Path(args.import_json), folder_id=folder.get("id"), poll=True)
    flow_url = import_result.get("flowUrl")
    flow_id = import_result.get("flowId")
    out = {"phase": "create", "workflowName": workflow_name, "folder": report["folder"], "flowId": flow_id, "flowUrl": flow_url,
           "importJson": str(Path(args.import_json).resolve()),
           "supersededCandidates": duplicates if args.allow_duplicate_import else [],
           "verifiedFolderId": import_result.get("verifiedFolderId"), "preflight": report}
    if not flow_url:
        out["status"] = "import-unverified"
        out["note"] = "import promise did not return a flow id/url"
        emit(out)
        print("CREATE: import did not return a flow id — verify manually.")
        return 1
    expect = [c.strip() for c in args.expect_columns.split(",")] if args.expect_columns else None
    expected_outputs = savant_inspect.load_expected_outputs(args.expected_outputs_json)
    post_save_recipe_path = (
        None if args.no_post_save_recipe
        else args.post_save_recipe_path or workflow_evidence.default_post_write_recipe_path(str(flow_id), "create")
    )
    evidence = workflow_evidence.collect_post_write_evidence(
        ctx=ctx,
        flow_url=flow_url,
        flow_id=str(flow_id),
        operation="create",
        imported_path=args.import_json,
        expect_columns=expect,
        expected_outputs=expected_outputs,
        checkpoints=args.checkpoint,
        sample_tier=args.sample_tier,
        timeout=args.timeout_seconds,
        inspect_enabled=not args.skip_inspect,
        terminal_preview=not args.no_terminal_preview,
        force_analyze=False,
        post_write_recipe_path=post_save_recipe_path,
        block_documentation_gaps=True,
    )
    evidence.pop("refetchedRecipe", None)
    out["postSaveRecipePath"] = evidence.get("postSaveRecipePath")
    out["inspect"] = evidence.get("inspect")
    out["evidence"] = {k: v for k, v in evidence.items() if k not in {"postSaveRecipePath", "inspect"}}
    out["status"] = create_status(
        data_verified=evidence.get("dataOk"),
        skip_inspect=args.skip_inspect,
    )
    api.save_json(out, report_path)
    print(f"CREATE: {out['status']} — {flow_url}")
    if out.get("postSaveRecipePath"):
        print(f"  [ok ] post-save-workflow-json: {out['postSaveRecipePath']}")
    summary = dict(out.get("inspect") or {})
    savant_inspect.print_summary_lines(summary)
    return 0 if out["status"] in ("verified", "imported") else 1


if __name__ == "__main__":
    raise SystemExit(main())
