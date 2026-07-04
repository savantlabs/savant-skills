#!/usr/bin/env python3
"""Validate generic Savant skill readiness checkpoint evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkpoints.lifecycle import validate_checkpoint_lifecycle  # noqa: E402


CHECKPOINTS = {
    "editor_readiness_checkpoint": {
        "stages": {"questions_needed", "ready"},
        "unresolved": "Required editor readiness field `{field}` is unresolved; editor cannot proceed.",
    },
    "q_and_a_intake_checkpoint": {
        "stages": {"questions_needed", "ready"},
        "unresolved": "Required Q&A context field `{field}` is unresolved; answer cannot proceed.",
    },
}


def _require_non_empty_string(errors: list[str], value: Any, field_path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"`{field_path}` must be a non-empty string.")


def validate_skill_readiness(evidence: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    task_type = evidence.get("task_type")
    config = CHECKPOINTS.get(task_type)
    if config is None:
        errors.append(
            "`task_type` must be `editor_readiness_checkpoint` or `q_and_a_intake_checkpoint`."
        )
        return errors, warnings

    stage = evidence.get("stage")
    if stage not in config["stages"]:
        allowed = " or ".join(f"`{value}`" for value in sorted(config["stages"]))
        errors.append(f"`stage` must be {allowed}.")
        stage = "questions_needed"

    _require_non_empty_string(errors, evidence.get("request_summary"), "request_summary")

    validate_checkpoint_lifecycle(
        errors,
        evidence,
        stage=stage,
        unresolved_error_template=config["unresolved"],
    )

    return errors, warnings
