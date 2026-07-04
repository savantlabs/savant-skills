"""Shared two-stage checkpoint lifecycle validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CheckpointLifecycleResult:
    open_questions: dict[str, dict[str, Any]]
    answered_questions: dict[str, dict[str, Any]]
    deferred_questions: dict[str, dict[str, Any]]
    answered_fields: set[str]
    resolved_fields: set[str]


def is_truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def value_is_resolved(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def require_non_empty_string(errors: list[str], value: Any, field_path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"`{field_path}` must be a non-empty string.")


def validate_evidence_items(
    errors: list[str],
    evidence: dict[str, Any],
    field_name: str,
    *,
    require_value: bool = True,
) -> dict[str, dict[str, Any]]:
    items = evidence.get(field_name)
    seen_fields: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(f"`{field_name}` must be an array.")
        return seen_fields
    for index, item in enumerate(items):
        label = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{label}` must be an object.")
            continue
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            errors.append(f"`{label}.field` must be a non-empty string.")
        else:
            seen_fields[field.strip()] = item
        if require_value:
            require_non_empty_string(errors, item.get("value"), f"{label}.value")
        require_non_empty_string(errors, item.get("evidence"), f"{label}.evidence")
    return seen_fields


def _validate_open_question_items(
    errors: list[str],
    evidence: dict[str, Any],
    field_name: str,
) -> dict[str, dict[str, Any]]:
    items = evidence.get(field_name)
    seen: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(f"`{field_name}` must be an array.")
        return seen
    for index, item in enumerate(items):
        label = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{label}` must be an object.")
            continue
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            errors.append(f"`{label}.field` must be a non-empty string.")
        else:
            seen[field.strip()] = item
        if not isinstance(item.get("required"), bool):
            errors.append(f"`{label}.required` must be a boolean.")
        require_non_empty_string(errors, item.get("evidence"), f"{label}.evidence")
        question = item.get("question")
        conversation_goal = item.get("conversation_goal")
        if not (
            isinstance(question, str)
            and question.strip()
            or isinstance(conversation_goal, str)
            and conversation_goal.strip()
        ):
            errors.append(
                f"`{label}` must include either a non-empty `question` or `conversation_goal`."
            )
    return seen


def _validate_answered_question_items(
    errors: list[str],
    evidence: dict[str, Any],
    field_name: str,
) -> dict[str, dict[str, Any]]:
    items = evidence.get(field_name, [])
    seen: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(f"`{field_name}` must be an array.")
        return seen
    for index, item in enumerate(items):
        label = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{label}` must be an object.")
            continue
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            errors.append(f"`{label}.field` must be a non-empty string.")
        else:
            seen[field.strip()] = item
        if "required" in item and not isinstance(item.get("required"), bool):
            errors.append(f"`{label}.required` must be a boolean when present.")
        require_non_empty_string(errors, item.get("answer"), f"{label}.answer")
        require_non_empty_string(errors, item.get("answer_evidence"), f"{label}.answer_evidence")
    return seen


def _validate_deferred_question_items(
    errors: list[str],
    evidence: dict[str, Any],
    field_name: str,
) -> dict[str, dict[str, Any]]:
    items = evidence.get(field_name, [])
    seen: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(f"`{field_name}` must be an array.")
        return seen
    for index, item in enumerate(items):
        label = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{label}` must be an object.")
            continue
        field = item.get("field")
        if not isinstance(field, str) or not field.strip():
            errors.append(f"`{label}.field` must be a non-empty string.")
        else:
            seen[field.strip()] = item
        if item.get("required") is True:
            errors.append(f"`{label}.required` must be false for deferred questions.")
        require_non_empty_string(errors, item.get("evidence"), f"{label}.evidence")
    return seen


def validate_checkpoint_lifecycle(
    errors: list[str],
    evidence: dict[str, Any],
    *,
    stage: str,
    unresolved_error_template: str,
    resolved_fields: set[str] | None = None,
) -> CheckpointLifecycleResult:
    open_questions = _validate_open_question_items(errors, evidence, "open_questions")
    answered_questions = _validate_answered_question_items(errors, evidence, "answered_questions")
    deferred_questions = _validate_deferred_question_items(errors, evidence, "deferred_questions")
    answered_fields = {
        field
        for field, question in answered_questions.items()
        if value_is_resolved(question.get("answer"))
    }
    all_resolved_fields = set(resolved_fields or set()) | answered_fields

    for field, question in open_questions.items():
        if stage == "ready" and question.get("required") is True and field not in all_resolved_fields:
            errors.append(unresolved_error_template.format(field=field))

    for field in deferred_questions:
        if field not in open_questions:
            errors.append(f"`deferred_questions` item `{field}` must also appear in `open_questions`.")

    if stage == "questions_needed" and not is_truthy(evidence.get("ready_for_questions")):
        errors.append("`ready_for_questions` must be true.")
    if stage == "ready" and not is_truthy(evidence.get("ready_for_stage")):
        errors.append("`ready_for_stage` must be true.")

    return CheckpointLifecycleResult(
        open_questions=open_questions,
        answered_questions=answered_questions,
        deferred_questions=deferred_questions,
        answered_fields=answered_fields,
        resolved_fields=all_resolved_fields,
    )
