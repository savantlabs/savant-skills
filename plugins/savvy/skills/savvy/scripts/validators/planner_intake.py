#!/usr/bin/env python3
"""Validate Savant workflow planner intake checkpoint evidence.

This runs before the planner presents a workflow process plan. It supports the
shared two-stage checkpoint lifecycle:

- questions_needed: known preferences/facts were considered first, and open
  questions are classified as required or optional.
- ready: required questions have been resolved through known facts, reusable
  preferences, or user answers. Optional questions may remain deferred.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkpoints.lifecycle import (  # noqa: E402
    is_truthy,
    require_non_empty_string,
    validate_checkpoint_lifecycle,
    validate_evidence_items,
)


PASSING = {"passed"}
KNOWN_STATUSES = PASSING | {"failed", "partial", "unknown"}
STAGES = {"questions_needed", "ready"}
DOCUMENTATION_MODES = {"light", "detail"}
REQUIRED_QUESTION_FIELDS = {
    "documentation_mode",
    "delivery_path",
    "savant_folder",
    "savant_location",
    "dataset_availability",
    "owner",
    "owner_cadence_and_approval",
    "cadence",
    "escalation_owners",
    "approval",
    "output_grain",
    "source_of_truth",
    "amount_basis",
    "join_preservation",
    "review_flags",
}


def status_of(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        raw = value.get("status")
        if isinstance(raw, str):
            return raw.strip().lower()
    return "unknown"


def validate_planner_intake(evidence: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if evidence.get("task_type") != "planner_intake_checkpoint":
        errors.append("`task_type` must be `planner_intake_checkpoint`.")

    stage = evidence.get("stage")
    if stage not in STAGES:
        errors.append("`stage` must be `questions_needed` or `ready`.")
        stage = "questions_needed"

    status = status_of(evidence)
    if status not in KNOWN_STATUSES:
        errors.append(f"`status` has unknown status `{status}`.")
    elif status not in PASSING:
        errors.append("Planner intake checkpoint must pass before presenting the process plan.")

    if not is_truthy(evidence.get("known_preferences_checked")):
        errors.append("`known_preferences_checked` must be true.")

    sources_checked = evidence.get("preference_sources_checked")
    if not isinstance(sources_checked, list) or not sources_checked:
        errors.append("`preference_sources_checked` must list the checked preference sources.")
    elif not all(isinstance(source, str) and source.strip() for source in sources_checked):
        errors.append("`preference_sources_checked` entries must be non-empty strings.")

    preference_items = validate_evidence_items(
        errors,
        evidence,
        "reusable_preferences_applied",
    )
    fact_items = validate_evidence_items(errors, evidence, "known_task_facts_applied")
    resolved_fields = set(preference_items) | set(fact_items)
    lifecycle = validate_checkpoint_lifecycle(
        errors,
        evidence,
        stage=stage,
        unresolved_error_template="Required planner intake field `{field}` is unresolved; planner cannot proceed.",
        resolved_fields=resolved_fields,
    )
    question_items = lifecycle.open_questions
    answered_fields = lifecycle.answered_fields

    # Documentation mode is a user preference/choice, not a safe task inference.
    # Do not allow agents to infer "light" merely because the user asked to build
    # a workflow; the user must either have a reusable preference or answer the
    # high-level-vs-detailed planning question in this checkpoint lifecycle.
    documentation_mode_known = "documentation_mode" in preference_items
    documentation_mode_inferred_as_fact = "documentation_mode" in fact_items
    documentation_mode_answered = "documentation_mode" in answered_fields
    documentation_mode_queued = "documentation_mode" in question_items
    if documentation_mode_inferred_as_fact:
        errors.append(
            "`documentation_mode` cannot be resolved from `known_task_facts_applied`; "
            "ask the user whether they want a high-level working plan or a detailed process document, "
            "or use an explicit reusable preference."
        )
    if not documentation_mode_known and not documentation_mode_queued:
        errors.append(
            "`documentation_mode` must come from a reusable preference or a question queued for the user."
        )

    documentation_mode = (
        evidence.get("documentation_mode")
        or (preference_items.get("documentation_mode") or {}).get("value")
        or (question_items.get("documentation_mode") or {}).get("answer")
    )
    if documentation_mode is not None and documentation_mode not in DOCUMENTATION_MODES:
        errors.append("`documentation_mode` must be `light` or `detail` when present.")
    if (
        stage == "questions_needed"
        and evidence.get("documentation_mode") in DOCUMENTATION_MODES
        and not documentation_mode_known
    ):
        errors.append(
            "`documentation_mode` may only be set before user response when backed by a reusable preference "
            "and must otherwise be queued as a user question."
        )
    if stage == "ready" and not (
        documentation_mode_known or documentation_mode_answered
    ):
        errors.append("`documentation_mode` must be resolved before planner can proceed.")

    unknown_question_fields = set(question_items) - REQUIRED_QUESTION_FIELDS
    if unknown_question_fields:
        warnings.append(
            "Planner intake includes non-standard question fields: "
            + ", ".join(sorted(unknown_question_fields))
            + "."
        )

    return errors, warnings
