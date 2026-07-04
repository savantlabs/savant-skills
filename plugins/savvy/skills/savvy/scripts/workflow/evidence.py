#!/usr/bin/env python3
"""Shared post-write evidence collection for Savant workflow create/edit helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from savant_api import cli as api
from savant_api.fileio import workspace_tmp
from validators import workflow as workflow_validator
from workflow import inspection as savant_inspect


def default_post_write_recipe_path(flow_id: str, operation: str) -> Path:
    if operation == "edit":
        folder, suffix = "workflow-edits", "after-save"
    elif operation == "create":
        folder, suffix = "workflow-create", "after-create"
    else:
        folder, suffix = "workflow-inspections", "live-recipe"
    return workspace_tmp(folder, f"{flow_id}.{suffix}.json")


def collect_post_write_evidence(
    *,
    ctx,
    flow_url: str,
    flow_id: str,
    operation: str,
    imported_path: str | None,
    checkpoints: list[str],
    expect_columns: list[str] | None,
    expected_outputs: list[dict] | None,
    sample_tier: str,
    timeout: int,
    inspect_enabled: bool = True,
    terminal_preview: bool = True,
    force_analyze: bool = False,
    post_write_recipe_path: Path | None = None,
    block_documentation_gaps: bool = False,
) -> dict[str, Any]:
    """Fetch saved recipe and inspect previews with shared defaults.

    The caller owns only the write operation. Once a flow exists or has been saved, this helper
    deterministically chooses the routine evidence surfaces for both create and edit: the
    re-fetched recipe, file-based workflow validation (which includes the deterministic layout
    checks), and node/output inspection. There is no rendered-canvas/visual leg — layout quality
    is judged from the validated JSON, not a rendered view.
    """
    refetched_recipe = api.get_recipe(ctx, flow_id)
    if post_write_recipe_path is not None:
        api.save_json(refetched_recipe, post_write_recipe_path)
        validation_errors, validation_warnings = workflow_validator.validate(
            post_write_recipe_path,
            block_documentation_gaps=block_documentation_gaps,
        )
        validation_report = {
            "ok": not validation_errors,
            "errorCount": len(validation_errors),
            "warningCount": len(validation_warnings),
            "errors": validation_errors,
            "warnings": validation_warnings,
            "warningsBlocking": False,
            "documentationGapsBlocking": block_documentation_gaps,
        }
    else:
        validation_report = {
            "ok": None,
            "skipped": True,
            "reason": "post-write recipe JSON was not saved, so file-based validation was skipped.",
        }

    inspect_report = None
    if inspect_enabled:
        inspect_report = savant_inspect.inspect(
            flow_url,
            imported_path=imported_path,
            expect_columns=expect_columns,
            expected_outputs=expected_outputs,
            checkpoints=checkpoints,
            sample_tier=sample_tier,
            timeout=timeout,
            skip_terminals=not terminal_preview,
            force_analyze=force_analyze,
        )

    validation_ok = validation_report.get("ok")
    data_ok = None if inspect_report is None else inspect_report.get("overall") == "pass"
    required_checks = []
    if data_ok is not None:
        required_checks.append(bool(data_ok))
    if validation_ok is not None:
        required_checks.append(bool(validation_ok))
    evidence_ok = all(required_checks)
    return {
        "operation": operation,
        "refetchedRecipe": refetched_recipe,
        "savedRecipePath": str(post_write_recipe_path) if post_write_recipe_path else None,
        "postSaveRecipePath": str(post_write_recipe_path) if post_write_recipe_path else None,
        "inspect": inspect_report,
        "validation": validation_report,
        "dataOk": data_ok,
        "ok": evidence_ok,
    }
