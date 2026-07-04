#!/usr/bin/env python3
"""Validate Savant workflow completion evidence before completion claims."""

from __future__ import annotations

from typing import Any


PASSING = {"passed", "not_required"}
NONPASSING = {"not_run", "partial", "failed", "unknown"}
KNOWN_STATUSES = PASSING | NONPASSING

BASE_REQUIRED_CHECKS_BY_SCOPE = {
    "draft_import": {
        "workflow_created",
    },
    "full_verified_workflow": {
        "workflow_created",
        "validator_passed",
        "pre_import_validator_passed",
        "execution_completed",
        "no_visible_errors",
        "final_row_count_verified",
        "checkpoint_counts_verified",
        "business_logic_spot_checked",
        "reference_outputs_reconciled",
        "output_usability_reviewed",
        "descriptions_reviewed",
    },
}

EXECUTION_MODES = {"analyze", "test", "run"}

RECOMMENDED_FIELDS = {
    "task_type",
    "scope",
    "completion_claim",
    "workflow_name",
    "workflow_url",
    "checks",
}


def status_of(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        raw = value.get("status")
        if isinstance(raw, str):
            return raw.strip().lower()
    return "unknown"


def validate_completion_evidence(
    evidence: dict[str, Any],
    *,
    claim: str | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(evidence, dict):
        errors.append("Completion evidence must be a JSON object.")
        evidence = {}

    for field in sorted(RECOMMENDED_FIELDS):
        if field not in evidence:
            errors.append(f"Missing required top-level field `{field}`.")

    scope = evidence.get("scope")
    if not isinstance(scope, str) or scope not in BASE_REQUIRED_CHECKS_BY_SCOPE:
        errors.append(
            f"`scope` must be one of: {', '.join(sorted(BASE_REQUIRED_CHECKS_BY_SCOPE))}."
        )
        scope = ""

    execution_mode = evidence.get("execution_mode")
    if scope == "full_verified_workflow":
        if not isinstance(execution_mode, str) or execution_mode not in EXECUTION_MODES:
            errors.append(
                "`execution_mode` must be one of "
                f"{', '.join(sorted(EXECUTION_MODES))} for full workflow verification."
            )
    elif execution_mode is not None and execution_mode not in EXECUTION_MODES:
        errors.append(
            f"`execution_mode`, when present, must be one of: {', '.join(sorted(EXECUTION_MODES))}."
        )

    resolved_claim = claim or evidence.get("completion_claim")
    if resolved_claim not in {"done", "qualified"}:
        errors.append("`completion_claim` must be `done` or `qualified`.")
        resolved_claim = "qualified"

    checks = evidence.get("checks")
    if not isinstance(checks, dict):
        errors.append("`checks` must be an object keyed by Definition of Done check name.")
        checks = {}

    required = set(BASE_REQUIRED_CHECKS_BY_SCOPE.get(scope, set()))
    for check_name in sorted(required):
        if check_name not in checks:
            errors.append(f"Missing required check `{check_name}` for scope `{scope}`.")
            continue
        status = status_of(checks[check_name])
        if status not in KNOWN_STATUSES:
            errors.append(
                f"Check `{check_name}` has unknown status `{status}`. "
                f"Use one of: {', '.join(sorted(KNOWN_STATUSES))}."
            )
        if resolved_claim == "done" and status not in PASSING:
            errors.append(
                f"Unqualified completion is blocked: check `{check_name}` is `{status}`."
            )

    for check_name, value in sorted(checks.items()):
        status = status_of(value)
        if status not in KNOWN_STATUSES:
            errors.append(
                f"Check `{check_name}` has unknown status `{status}`. "
                f"Use one of: {', '.join(sorted(KNOWN_STATUSES))}."
            )
        if check_name not in required and status in NONPASSING and resolved_claim == "done":
            warnings.append(
                f"Non-required check `{check_name}` is `{status}`; mention this if it affects user expectations."
            )

    if resolved_claim == "qualified":
        incomplete_required = [
            name
            for name in sorted(required)
            if status_of(checks.get(name)) not in PASSING
        ]
        if not incomplete_required:
            warnings.append(
                "Completion claim is qualified even though required checks pass; unqualified completion is allowed."
            )

    return errors, warnings
