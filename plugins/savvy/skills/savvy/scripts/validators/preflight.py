#!/usr/bin/env python3
"""Validate Savant workflow Builder/Creator preflight evidence.

Builder uses this before JSON generation to enforce the business-process plan
checkpoint. Creator uses this after workflow validation, folder resolution, and
dataset discovery, but before calling /api/recipes/import.

The Creator path is deliberately strict about missing or ambiguous source
datasets: imports are blocked unless every source is matched or the user made an
explicit decision.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkpoints.lifecycle import (  # noqa: E402
    is_truthy,
    require_non_empty_string,
    validate_checkpoint_lifecycle,
)
from contracts.folder_target import is_root_folder_target  # noqa: E402
from contracts.output_destination import validate_output_destinations  # noqa: E402
from contracts.source_plan import validate_source_plan  # noqa: E402


PASSING = {"passed", "not_required"}
KNOWN_STATUSES = PASSING | {"not_run", "partial", "failed", "unknown"}
REQUIRED_TOP_LEVEL_FIELDS = {
    "task_type",
    "workflow_name",
    "workflow_json",
    "requested_scope",
    "context_confirmation",
    "creation_confirmation",
    "folder",
    "workflow_validation",
    "import_allowed",
}
CREATOR_DISCOVERY_TOP_LEVEL_FIELDS = {
    "task_type",
    "workflow_name",
    "workflow_json",
    "requested_scope",
    "open_questions",
    "answered_questions",
    "deferred_questions",
    "ready_for_questions",
}
CREATOR_STAGES = {"questions_needed", "ready"}
BUILDER_REQUIRED_TOP_LEVEL_FIELDS = {
    "task_type",
    "workflow_name",
    "requested_scope",
    "process_metadata",
    "input_dataset_plan",
    "output_destination_plan",
    "workflow_plan_checkpoint",
    "json_generation_allowed",
}
BUILDER_DISCOVERY_TOP_LEVEL_FIELDS = {
    "task_type",
    "workflow_name",
    "requested_scope",
    "open_questions",
    "answered_questions",
    "deferred_questions",
    "ready_for_questions",
}
BUILDER_PLAN_FORMATS = {"numbered_business_process_map", "compact_sentence", "workflow_process_plan"}
BUILDER_STAGES = {"questions_needed", "ready"}
BUILDER_REQUESTED_SCOPES = {"build_only", "draft_import", "full_verified_workflow"}
BUILDER_DOCUMENTATION_MODES = {"light", "detail"}
BUILDER_DOCUMENTATION_MODE_SOURCES = {"user_answer", "reusable_preference"}
TECHNICAL_GROUP_TITLE_STARTS = {
    "adapter",
    "api",
    "blend",
    "destination",
    "edit",
    "filter",
    "join",
    "json",
    "node",
    "schema",
    "source",
    "sql",
    "transform",
}
UNRESOLVED_METADATA_VALUES = {
    "n/a",
    "na",
    "none",
    "not applicable",
    "not specified",
    "pending",
    "pending user confirmation",
    "tbd",
    "to be determined",
    "unknown",
}
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Phrases that mark confirmation "evidence" as a NON-answer: the user was asked but did not
# actually choose. A dismissed, skipped, or "no preference" response is not consent. The only
# question with a sanctioned default is the destination FOLDER, which resolves to the Home
# folder (`folder.id: home`) of the user-confirmed workspace — announced, never silent, and
# never another folder or workspace. Matched with `_normalize_for_contains` (casefolded,
# -/_ collapsed to spaces).
NON_ANSWER_EVIDENCE_PHRASES = (
    "no preference",
    "no answer",
    "not answered",
    "did not answer",
    "didn't answer",
    "didnt answer",
    "no response",
    "did not respond",
    "didn't respond",
    "didnt respond",
    "no user response",
    "declined to answer",
    "declined to choose",
    "dismissed the question",
    "question was dismissed",
    "skipped the question",
    "question was skipped",
    "left blank",
    "left the question blank",
    "blank answer",
    "without an answer",
    "without a user answer",
    "without asking",
    "on the user's behalf",
    "on the users behalf",
    "on behalf of the user",
    "as a fallback",
    "low friction option",
    "low friction default",
    "proceeding with default",
    "defaulted to",
)


def status_of(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        raw = value.get("status")
        if isinstance(raw, str):
            return raw.strip().lower()
    return "unknown"


def _normalize_for_contains(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").replace("_", " ").split())


def _load_profile_json(errors: list[str], path_value: Any, field_path: str) -> dict[str, Any] | None:
    if not isinstance(path_value, str) or not path_value.strip():
        errors.append(f"`{field_path}` is required when local files were provided.")
        return None
    path = Path(path_value).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"`{field_path}` does not exist: {path}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"`{field_path}` is not valid JSON: {exc}")
        return None
    except OSError as exc:
        errors.append(f"`{field_path}` could not be read: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"`{field_path}` must contain a JSON object.")
        return None
    return payload


def _validate_ready_source_profile(errors: list[str], profile: dict[str, Any], field_path: str) -> None:
    if profile.get("task") != "source_profile":
        errors.append(f"`{field_path}` must be a source profile report from `savant.py source profile`.")
    if profile.get("status") != "ready":
        errors.append(
            f"`{field_path}.status` must be `ready`; current value is `{profile.get('status')}`. "
            "If it is `needs_ai_profile`, create hints and rerun the profiler before handoff."
        )
    if profile.get("readyForSourcePlanning") is not True:
        errors.append(f"`{field_path}.readyForSourcePlanning` must be true before Builder handoff.")
    if profile.get("aiProfileRequests"):
        errors.append(f"`{field_path}.aiProfileRequests` must be empty before Builder handoff.")
    if profile.get("errors"):
        errors.append(f"`{field_path}.errors` must be empty before Builder handoff.")


def _validate_profile_evidence(errors: list[str], input_plan: dict[str, Any]) -> None:
    evidence = input_plan.get("profile_evidence")
    if not isinstance(evidence, dict):
        errors.append("`input_dataset_plan.profile_evidence` must be an object.")
        return
    local_files_provided = evidence.get("local_files_provided")
    if not isinstance(local_files_provided, bool):
        errors.append("`input_dataset_plan.profile_evidence.local_files_provided` must be a boolean.")
        return
    if not local_files_provided:
        return

    profile = _load_profile_json(
        errors,
        evidence.get("source_profile_path"),
        "input_dataset_plan.profile_evidence.source_profile_path",
    )
    brief = _load_profile_json(
        errors,
        evidence.get("source_profile_brief_path"),
        "input_dataset_plan.profile_evidence.source_profile_brief_path",
    )
    if profile is None or brief is None:
        return
    _validate_ready_source_profile(errors, profile, "source_profile")
    _validate_ready_source_profile(errors, brief, "source_profile_brief")
    if "brief" not in profile:
        errors.append("`source_profile.brief` is required so the brief can be verified against the full report.")
    elif profile.get("brief") != brief:
        errors.append("`input_dataset_plan.profile_evidence.source_profile_brief_path` must match the full profile's embedded `brief`.")
    _validate_observed_schema_matches_profile(errors, input_plan, profile)


def _profile_observed_signatures(profile: dict[str, Any]) -> list[dict[str, str]]:
    """Per profiled source: {column-name-casefold: dataType} from sourcePlanSuggestion."""
    signatures: list[dict[str, str]] = []
    for source in profile.get("sources") or []:
        if not isinstance(source, dict):
            continue
        suggestion = source.get("sourcePlanSuggestion")
        dataset = suggestion.get("dataset") if isinstance(suggestion, dict) else None
        columns = dataset.get("observed_schema") if isinstance(dataset, dict) else None
        if not isinstance(columns, list):
            continue
        signature = {
            str(col.get("name") or "").strip().casefold(): str(col.get("dataType") or "").strip().lower()
            for col in columns
            if isinstance(col, dict) and col.get("name")
        }
        if signature:
            signatures.append(signature)
    return signatures


def _validate_observed_schema_matches_profile(
    errors: list[str], input_plan: dict[str, Any], profile: dict[str, Any]
) -> None:
    """Hand-written observed schemas must not be able to pass the gate.

    The profiler is the evidence authority for user-supplied files. A plan whose
    observed_schema disagrees with the profile (typically a hand-typed schema using
    the PARSED view, e.g. Excel serial date columns recorded as `date` instead of
    the raw `integer`) silently disarms deterministic source-construction rules —
    verified live: the Excel serial-date conversion was skipped and the imported
    workflow showed 1970-era dates. Match each plan source to a profiled source by
    column-name signature and require identical dataTypes.
    """
    signatures = _profile_observed_signatures(profile)
    if not signatures:
        return
    for index, source in enumerate(input_plan.get("sources") or []):
        if not isinstance(source, dict):
            continue
        dataset = source.get("dataset")
        observed = dataset.get("observed_schema") if isinstance(dataset, dict) else None
        if not isinstance(observed, list) or not observed:
            continue
        plan_signature = {
            str(col.get("name") or "").strip().casefold(): str(col.get("dataType") or "").strip().lower()
            for col in observed
            if isinstance(col, dict) and col.get("name")
        }
        by_names = [sig for sig in signatures if set(sig) == set(plan_signature)]
        if not by_names:
            continue  # source not covered by this profile (e.g. an existing dataset)
        if not any(sig == plan_signature for sig in by_names):
            profiled = by_names[0]
            diffs = [
                f"`{name}` plan={plan_signature[name] or '?'} profile={profiled.get(name) or '?'}"
                for name in sorted(plan_signature)
                if plan_signature[name] != profiled.get(name)
            ]
            errors.append(
                f"`input_dataset_plan.sources[{index}].dataset.observed_schema` dataTypes diverge from the "
                f"profiler report for the matching source ({'; '.join(diffs[:4])}). Fill observed_schema from "
                "the profile's `sourcePlanSuggestion` — do not hand-write it; divergence disarms deterministic "
                "source-construction rules such as Excel serial-date conversion."
            )


def _starts_with_technical_group_title(title: str) -> bool:
    normalized = _normalize_for_contains(title)
    first_word = normalized.split(" ", 1)[0] if normalized else ""
    return first_word in TECHNICAL_GROUP_TITLE_STARTS


def _require_non_empty_string(errors: list[str], value: Any, field_path: str) -> None:
    require_non_empty_string(errors, value, field_path)


def _require_resolved_metadata_string(errors: list[str], value: Any, field_path: str) -> None:
    _require_non_empty_string(errors, value, field_path)
    if isinstance(value, str) and value.strip().casefold() in UNRESOLVED_METADATA_VALUES:
        errors.append(f"`{field_path}` must be resolved before JSON generation.")


def _non_answer_hits(value: str) -> list[str]:
    normalized = _normalize_for_contains(value)
    return sorted(phrase for phrase in NON_ANSWER_EVIDENCE_PHRASES if phrase in normalized)


def _reject_non_answer_evidence(errors: list[str], value: Any, field_path: str) -> None:
    """A recorded non-answer can never satisfy a user-consent gate.

    "The user was asked and answered 'no preference'" is a truthful sentence, but it is not
    consent. Workspace and creation consent have no default — stop and ask. Only the
    destination FOLDER has one: the Home folder of the user-confirmed workspace, recorded in
    `context_confirmation.user_stated_destination` with `folder.id: home` and announced to
    the user — never another folder or workspace.
    """
    if not isinstance(value, str):
        return
    hits = _non_answer_hits(value)
    if hits:
        errors.append(
            f"`{field_path}` records a non-answer ({', '.join(repr(h) for h in hits)}). "
            "A dismissed, skipped, or 'no preference' response is not consent — stop, keep the "
            "built artifacts, and ask the user again. Exception: a folder non-answer resolves to "
            "the Home folder of the user-confirmed workspace (`folder.id: home`, announced) — "
            "record that in `context_confirmation.user_stated_destination`, and keep this field "
            "to the user's actual approval words."
        )


def _require_explicit_user_evidence(errors: list[str], value: Any, field_path: str) -> None:
    _require_non_empty_string(errors, value, field_path)
    if not isinstance(value, str):
        return
    _reject_non_answer_evidence(errors, value, field_path)
    normalized = _normalize_for_contains(value)
    weak_only_phrases = (
        "user asked to create",
        "user asked to build",
        "user requested workflow creation",
        "user said they will create it in savant",
        "user instructed codex to create",
        "create the workflow",
        "build the workflow",
    )
    explicit_terms = (
        "confirmed",
        "approved",
        "selected",
        "chose",
        "answered",
        "provided",
    )
    if any(phrase in normalized for phrase in weak_only_phrases) and not any(
        term in normalized for term in explicit_terms
    ):
        errors.append(
            f"`{field_path}` must cite an explicit user answer or approval, not just the user's broad request to create/build the workflow."
        )


def _validate_builder_question_cycle(
    evidence: dict[str, Any],
    stage: str,
    errors: list[str],
) -> None:
    validate_checkpoint_lifecycle(
        errors,
        evidence,
        stage=stage,
        unresolved_error_template="Required builder readiness field `{field}` is unresolved; builder cannot proceed.",
    )


def validate_builder_preflight(
    evidence: dict[str, Any], *, require_generation_allowed: bool = True
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    stage = evidence.get("stage")
    if stage not in BUILDER_STAGES:
        errors.append("`stage` must be `questions_needed` or `ready`.")
        stage = "ready"

    required_top_level_fields = (
        BUILDER_DISCOVERY_TOP_LEVEL_FIELDS
        if stage == "questions_needed"
        else BUILDER_REQUIRED_TOP_LEVEL_FIELDS | {"stage"}
    )
    for field in sorted(required_top_level_fields):
        if field not in evidence:
            errors.append(f"Missing required top-level field `{field}`.")

    if evidence.get("task_type") != "builder_preflight":
        errors.append("`task_type` must be `builder_preflight`.")

    workflow_name = evidence.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name.strip():
        errors.append("`workflow_name` must be a non-empty string.")

    requested_scope = evidence.get("requested_scope")
    if requested_scope not in BUILDER_REQUESTED_SCOPES:
        errors.append(
            "`requested_scope` must be `build_only`, `draft_import`, or `full_verified_workflow`."
        )

    if "open_questions" in evidence or "answered_questions" in evidence or "deferred_questions" in evidence:
        _validate_builder_question_cycle(evidence, stage, errors)

    if stage == "questions_needed":
        return errors, warnings

    process_metadata = evidence.get("process_metadata")
    if not isinstance(process_metadata, dict):
        errors.append("`process_metadata` must be an object.")
        process_metadata = {}

    _require_resolved_metadata_string(errors, process_metadata.get("process_name"), "process_metadata.process_name")
    _require_resolved_metadata_string(
        errors,
        process_metadata.get("source_skill_or_domain"),
        "process_metadata.source_skill_or_domain",
    )
    documentation_mode = process_metadata.get("documentation_mode")
    if documentation_mode not in BUILDER_DOCUMENTATION_MODES:
        errors.append("`process_metadata.documentation_mode` must be `light` or `detail`.")
    documentation_mode_source = process_metadata.get("documentation_mode_source")
    if documentation_mode_source not in BUILDER_DOCUMENTATION_MODE_SOURCES:
        errors.append(
            "`process_metadata.documentation_mode_source` must be `user_answer` or `reusable_preference`; "
            "do not infer documentation mode from the request to build a workflow."
        )
    if documentation_mode_source == "user_answer":
        _require_explicit_user_evidence(
            errors,
            process_metadata.get("documentation_mode_evidence"),
            "process_metadata.documentation_mode_evidence",
        )
    governance_required = requested_scope in {"draft_import", "full_verified_workflow"} or documentation_mode == "detail"
    if governance_required:
        _require_resolved_metadata_string(errors, process_metadata.get("owner"), "process_metadata.owner")
        _require_resolved_metadata_string(errors, process_metadata.get("cadence"), "process_metadata.cadence")
        escalation_owners = process_metadata.get("escalation_owners")
        if not isinstance(escalation_owners, list) or not escalation_owners:
            errors.append("`process_metadata.escalation_owners` must list at least one owner or role.")
        elif not all(isinstance(owner, str) and owner.strip() for owner in escalation_owners):
            errors.append("`process_metadata.escalation_owners` entries must be non-empty strings.")
        elif any(owner.strip().casefold() in UNRESOLVED_METADATA_VALUES for owner in escalation_owners):
            errors.append("`process_metadata.escalation_owners` entries must be resolved before JSON generation.")
        approval = process_metadata.get("approval")
        if not isinstance(approval, dict):
            errors.append("`process_metadata.approval` must be an object.")
            approval = {}
        _require_resolved_metadata_string(errors, approval.get("drafted_by"), "process_metadata.approval.drafted_by")
        _require_resolved_metadata_string(errors, approval.get("certified_by"), "process_metadata.approval.certified_by")
        date_certified = approval.get("date_certified")
        _require_resolved_metadata_string(errors, date_certified, "process_metadata.approval.date_certified")
        if isinstance(date_certified, str) and date_certified.strip() and not ISO_DATE_PATTERN.match(date_certified.strip()):
            errors.append("`process_metadata.approval.date_certified` must use YYYY-MM-DD format.")

    input_plan = evidence.get("input_dataset_plan")
    if not isinstance(input_plan, dict):
        errors.append("`input_dataset_plan` must be an object.")
        input_plan = {}

    input_plan_required = input_plan.get("required")
    if not isinstance(input_plan_required, bool):
        errors.append("`input_dataset_plan.required` must be a boolean.")
        input_plan_required = True
    elif input_plan_required is not True:
        errors.append("`input_dataset_plan.required` must be true for Savant workflow generation.")

    input_plan_status = status_of(input_plan)
    if input_plan_status not in KNOWN_STATUSES:
        errors.append(f"`input_dataset_plan.status` has unknown status `{input_plan_status}`.")

    if input_plan_status not in PASSING:
        errors.append("Input dataset plan must pass before JSON generation.")
    if not isinstance(input_plan.get("plan_presented"), str) or not input_plan["plan_presented"].strip():
        errors.append("`input_dataset_plan.plan_presented` must describe the planned inputs.")
    _validate_profile_evidence(errors, input_plan)
    sources = input_plan.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("`input_dataset_plan.sources` must list the planned workflow inputs.")
        sources = []
    # The Builder is dataset-resolution-free. By handoff time every source follows the shared
    # source-plan contract: workflow intent plus a nested resolved dataset binding/profile.
    for index, source in enumerate(sources):
        label = f"input_dataset_plan.sources[{index}]"
        validate_source_plan(errors, source, label)

    if not is_truthy(input_plan.get("user_confirmed_or_revised")):
        errors.append("`input_dataset_plan.user_confirmed_or_revised` must be true.")
    if not isinstance(input_plan.get("user_confirmation_evidence"), str) or not input_plan[
        "user_confirmation_evidence"
    ].strip():
        errors.append("`input_dataset_plan.user_confirmation_evidence` is required.")
    else:
        _require_explicit_user_evidence(
            errors,
            input_plan.get("user_confirmation_evidence"),
            "input_dataset_plan.user_confirmation_evidence",
        )
    output_plan = evidence.get("output_destination_plan")
    if not isinstance(output_plan, dict):
        errors.append("`output_destination_plan` must be an object.")
        output_plan = {}

    output_plan_required = output_plan.get("required")
    if not isinstance(output_plan_required, bool):
        errors.append("`output_destination_plan.required` must be a boolean.")
        output_plan_required = True
    elif output_plan_required is not True:
        errors.append("`output_destination_plan.required` must be true for Savant workflow generation.")

    output_plan_status = status_of(output_plan)
    if output_plan_status not in KNOWN_STATUSES:
        errors.append(f"`output_destination_plan.status` has unknown status `{output_plan_status}`.")
    elif output_plan_status not in PASSING:
        errors.append("Output destination plan must pass before JSON generation.")
    if not isinstance(output_plan.get("plan_presented"), str) or not output_plan["plan_presented"].strip():
        errors.append("`output_destination_plan.plan_presented` must describe the planned output destination.")
    if not is_truthy(output_plan.get("included_in_workflow_plan")):
        errors.append("`output_destination_plan.included_in_workflow_plan` must be true.")
    outputs = output_plan.get("outputs")
    validate_output_destinations(errors, warnings, outputs, "output_destination_plan.outputs")

    checkpoint = evidence.get("workflow_plan_checkpoint")
    if not isinstance(checkpoint, dict):
        errors.append("`workflow_plan_checkpoint` must be an object.")
        checkpoint = {}

    checkpoint_required = checkpoint.get("required")
    if not isinstance(checkpoint_required, bool):
        errors.append("`workflow_plan_checkpoint.required` must be a boolean.")
        checkpoint_required = True
    elif checkpoint_required is not True:
        errors.append("`workflow_plan_checkpoint.required` must be true for Savant workflow generation.")

    checkpoint_status = status_of(checkpoint)
    if checkpoint_status not in KNOWN_STATUSES:
        errors.append(f"`workflow_plan_checkpoint.status` has unknown status `{checkpoint_status}`.")

    plan_format = checkpoint.get("format")
    if checkpoint_status not in PASSING:
        errors.append("Workflow plan checkpoint must pass before JSON generation.")
    if plan_format not in BUILDER_PLAN_FORMATS:
        errors.append(
            "`workflow_plan_checkpoint.format` must be `numbered_business_process_map`, "
            "`compact_sentence`, or `workflow_process_plan`."
        )
    if not isinstance(checkpoint.get("plan_presented"), str) or not checkpoint["plan_presented"].strip():
        errors.append("`workflow_plan_checkpoint.plan_presented` must include the user-facing plan.")
        plan_presented = ""
    else:
        plan_presented = checkpoint["plan_presented"]
    if plan_format == "numbered_business_process_map":
        process_steps = checkpoint.get("process_steps")
        if not isinstance(process_steps, list) or len(process_steps) < 2:
            errors.append(
                "`workflow_plan_checkpoint.process_steps` must list at least two business steps "
                "for a numbered business process map."
            )
        elif not all(isinstance(step, str) and step.strip() for step in process_steps):
            errors.append("`workflow_plan_checkpoint.process_steps` entries must be non-empty strings.")
    process_blocks = checkpoint.get("process_blocks")
    if not isinstance(process_blocks, list) or len(process_blocks) < 2:
        errors.append(
            "`workflow_plan_checkpoint.process_blocks` must list at least two business-facing process blocks."
        )
        process_blocks = []
    plan_text = _normalize_for_contains(plan_presented)
    for index, block in enumerate(process_blocks):
        label = f"workflow_plan_checkpoint.process_blocks[{index}]"
        if not isinstance(block, dict):
            errors.append(f"`{label}` must be an object.")
            continue
        title = block.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"`{label}.title` is required.")
            title = ""
        elif _starts_with_technical_group_title(title):
            errors.append(
                f"`{label}.title` must be business-facing, not a Savant component or technical operation name."
            )
        elif _normalize_for_contains(title) not in plan_text:
            errors.append(f"`{label}.title` must appear in `workflow_plan_checkpoint.plan_presented`.")
        if not isinstance(block.get("business_purpose"), str) or not block["business_purpose"].strip():
            errors.append(f"`{label}.business_purpose` is required.")
        business_steps = block.get("business_steps")
        if not isinstance(business_steps, list) or not business_steps:
            errors.append(f"`{label}.business_steps` must list what happens in business terms.")
        elif not all(isinstance(step, str) and step.strip() for step in business_steps):
            errors.append(f"`{label}.business_steps` entries must be non-empty strings.")
        if "technical_components" in block:
            warnings.append(
                f"`{label}.technical_components` is optional implementation detail; keep user-facing block titles and purposes business-oriented."
            )
    assumptions = checkpoint.get("material_assumptions")
    if assumptions is None:
        warnings.append("`workflow_plan_checkpoint.material_assumptions` is missing.")
    elif not isinstance(assumptions, list):
        errors.append("`workflow_plan_checkpoint.material_assumptions` must be an array when present.")
    elif not all(isinstance(item, str) and item.strip() for item in assumptions):
        errors.append("`workflow_plan_checkpoint.material_assumptions` entries must be non-empty strings.")

    # Material decisions: the choices the user approved must be written down and each
    # verified to be reflected in the handoff before the Builder consumes it. The
    # validator enforces the shape of the recorded self-review (every decision present,
    # rationale non-empty, reflected_in_handoff true); judging whether a decision is
    # truly reflected, or whether the list is complete, stays with the planner. See
    # ../../references/standards/material-decisions.md.
    decisions = checkpoint.get("material_decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append(
            "`workflow_plan_checkpoint.material_decisions` must list the material decisions the user approved "
            "(AI use, fuzzy matching, normalization, thresholds, fallback, ranking/tiebreaking, one-to-one match "
            "rules, source-of-truth precedence, exception categories, output grain, audit fields). See "
            "material-decisions.md."
        )
    else:
        for index, decision in enumerate(decisions):
            label = f"workflow_plan_checkpoint.material_decisions[{index}]"
            if not isinstance(decision, dict):
                errors.append(
                    f"`{label}` must be an object with `decision`, `rationale`, and `reflected_in_handoff`."
                )
                continue
            if not isinstance(decision.get("decision"), str) or not decision["decision"].strip():
                errors.append(f"`{label}.decision` is required.")
            if not isinstance(decision.get("rationale"), str) or not decision["rationale"].strip():
                errors.append(
                    f"`{label}.rationale` is required — record why the decision was made "
                    "(e.g. `user requested`, `user approved assumption`, `complex text processing`)."
                )
            reflected = decision.get("reflected_in_handoff")
            if not isinstance(reflected, bool):
                errors.append(f"`{label}.reflected_in_handoff` must be a boolean.")
            elif reflected is not True:
                errors.append(
                    f"`{label}.reflected_in_handoff` is not true — the planner must verify the handoff implements "
                    "this approved decision and adds nothing material beyond the approved decisions."
                )
    if not is_truthy(checkpoint.get("user_confirmed_or_revised")):
        errors.append("`workflow_plan_checkpoint.user_confirmed_or_revised` must be true.")
    if not isinstance(checkpoint.get("user_confirmation_evidence"), str) or not checkpoint[
        "user_confirmation_evidence"
    ].strip():
        errors.append("`workflow_plan_checkpoint.user_confirmation_evidence` is required.")
    else:
        _require_explicit_user_evidence(
            errors,
            checkpoint.get("user_confirmation_evidence"),
            "workflow_plan_checkpoint.user_confirmation_evidence",
        )
    review_decision = checkpoint.get("user_review_decision")
    if review_decision not in {"approved_as_presented", "revised_then_approved"}:
        errors.append(
            "`workflow_plan_checkpoint.user_review_decision` must be `approved_as_presented` or `revised_then_approved`; "
            "the process plan and assumptions must be shown to the user before JSON generation."
        )

    json_generation_allowed = evidence.get("json_generation_allowed")
    if not isinstance(json_generation_allowed, bool):
        errors.append("`json_generation_allowed` must be a boolean.")
    elif require_generation_allowed and not json_generation_allowed:
        errors.append("`json_generation_allowed` is false; do not generate JSON.")

    return errors, warnings


def validate_creator_preflight(evidence: dict[str, Any], *, require_import_allowed: bool = True) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    stage = evidence.get("stage")
    if stage not in CREATOR_STAGES:
        errors.append("`stage` must be `questions_needed` or `ready`.")
        stage = "ready"

    required_top_level_fields = (
        CREATOR_DISCOVERY_TOP_LEVEL_FIELDS
        if stage == "questions_needed"
        else REQUIRED_TOP_LEVEL_FIELDS | {"stage"}
    )
    for field in sorted(required_top_level_fields):
        if field not in evidence:
            errors.append(f"Missing required top-level field `{field}`.")

    if evidence.get("task_type") != "creator_preflight":
        errors.append("`task_type` must be `creator_preflight`.")

    workflow_json = evidence.get("workflow_json")
    if not isinstance(workflow_json, str) or not workflow_json.strip():
        errors.append("`workflow_json` must be a non-empty path string.")

    requested_scope = evidence.get("requested_scope")
    if requested_scope not in {"draft_import", "full_verified_workflow"}:
        errors.append("`requested_scope` must be `draft_import` or `full_verified_workflow`.")

    if "open_questions" in evidence or "answered_questions" in evidence or "deferred_questions" in evidence:
        validate_checkpoint_lifecycle(
            errors,
            evidence,
            stage=stage,
            unresolved_error_template="Required creator readiness field `{field}` is unresolved; import cannot proceed.",
        )

    if stage == "questions_needed":
        return errors, warnings

    context_confirmation = evidence.get("context_confirmation")
    if not isinstance(context_confirmation, dict):
        errors.append("`context_confirmation` must be an object.")
        context_confirmation = {}
    context_status = status_of(context_confirmation)
    if context_status not in KNOWN_STATUSES:
        errors.append(f"`context_confirmation.status` has unknown status `{context_status}`.")
    elif context_status not in PASSING:
        errors.append("Folder/workspace context confirmation is required before dataset discovery and import.")
    if not isinstance(context_confirmation.get("target_context"), str) or not context_confirmation["target_context"].strip():
        errors.append("`context_confirmation.target_context` must describe the selected folder/workspace context.")
    if not isinstance(context_confirmation.get("workspace"), str) or not context_confirmation["workspace"].strip():
        errors.append(
            "`context_confirmation.workspace` must name the workspace the user confirmed as the "
            "destination. The workspace has no default — if the user has not named one, stop and ask."
        )
    if not isinstance(context_confirmation.get("namespace"), str) or not context_confirmation["namespace"].strip():
        errors.append(
            "`context_confirmation.namespace` must record the confirmed workspace's namespace "
            "(from MCP `search`/`whereami`) — `workflow create --confirmed-namespace` verifies the "
            "session against it at import time."
        )
    user_stated = context_confirmation.get("user_stated_destination")
    destination_non_answer = False
    if not isinstance(user_stated, str) or not user_stated.strip():
        errors.append(
            "`context_confirmation.user_stated_destination` is required — quote the user's own words "
            "naming the destination folder, or record their non-answer verbatim (e.g. \"answered "
            "'no preference'\"). A non-answer resolves to the Home folder of the confirmed workspace "
            "(`folder.id: home`), announced to the user — never another folder or workspace."
        )
    else:
        destination_non_answer = bool(_non_answer_hits(user_stated))
    if not is_truthy(context_confirmation.get("user_confirmed")):
        errors.append("`context_confirmation.user_confirmed` must be true before dataset discovery/import.")
    if not isinstance(context_confirmation.get("user_confirmation_evidence"), str) or not context_confirmation[
        "user_confirmation_evidence"
    ].strip():
        errors.append("`context_confirmation.user_confirmation_evidence` is required.")
    else:
        _require_explicit_user_evidence(
            errors,
            context_confirmation["user_confirmation_evidence"],
            "context_confirmation.user_confirmation_evidence",
        )

    confirmation = evidence.get("creation_confirmation")
    if not isinstance(confirmation, dict):
        errors.append("`creation_confirmation` must be an object.")
        confirmation = {}
    confirmation_status = status_of(confirmation)
    if confirmation_status not in KNOWN_STATUSES:
        errors.append(f"`creation_confirmation.status` has unknown status `{confirmation_status}`.")
    elif confirmation_status not in PASSING:
        errors.append("User creation confirmation is required before import.")
    if not isinstance(confirmation.get("summary_presented"), str) or not confirmation["summary_presented"].strip():
        errors.append("`creation_confirmation.summary_presented` must describe the planned creation process.")
    if not is_truthy(confirmation.get("user_confirmed")):
        errors.append("`creation_confirmation.user_confirmed` must be true before import.")
    if not isinstance(confirmation.get("user_confirmation_evidence"), str) or not confirmation["user_confirmation_evidence"].strip():
        errors.append("`creation_confirmation.user_confirmation_evidence` is required.")
    else:
        _require_explicit_user_evidence(
            errors,
            confirmation["user_confirmation_evidence"],
            "creation_confirmation.user_confirmation_evidence",
        )

    validation_status = status_of(evidence.get("workflow_validation"))
    if validation_status not in KNOWN_STATUSES:
        errors.append(f"`workflow_validation.status` has unknown status `{validation_status}`.")
    elif validation_status not in PASSING:
        errors.append("Workflow JSON validation must pass before import.")

    folder = evidence.get("folder")
    if not isinstance(folder, dict):
        errors.append("`folder` must be an object.")
        folder = {}
    folder_status = status_of(folder)
    if folder_status not in KNOWN_STATUSES:
        errors.append(f"`folder.status` has unknown status `{folder_status}`.")
    elif folder_status not in PASSING:
        errors.append("Destination folder must be explicitly resolved before import.")
    folder_id = folder.get("id")
    if is_root_folder_target(folder_id):
        pass  # Home folder (namespace root): expressed as the `home`/`root` sentinel, no real id needed
    elif not isinstance(folder_id, str) or not folder_id.strip():
        errors.append("Destination `folder.id` is required (use `home` for the Home folder/namespace root).")
    elif destination_non_answer:
        errors.append(
            f"`context_confirmation.user_stated_destination` records a non-answer, but `folder.id` "
            f"is `{str(folder_id).strip()}` — a non-answer resolves ONLY to the Home folder of the "
            "confirmed workspace (`folder.id: home`), announced to the user. Never substitute another "
            "existing folder or a different workspace the user did not name."
        )
    folder_workspace = folder.get("workspace")
    if not isinstance(folder_workspace, str) or not folder_workspace.strip():
        errors.append(
            "`folder.workspace` must name the workspace the destination folder lives in, so it can "
            "be checked against the user-confirmed workspace."
        )
    else:
        confirmed_workspace = context_confirmation.get("workspace")
        if (
            isinstance(confirmed_workspace, str)
            and confirmed_workspace.strip()
            and _normalize_for_contains(confirmed_workspace) != _normalize_for_contains(folder_workspace)
        ):
            errors.append(
                f"Destination folder workspace `{folder_workspace.strip()}` does not match the "
                f"user-confirmed workspace `{confirmed_workspace.strip()}`. Retargeting to a different "
                "workspace invalidates the earlier confirmation — stop and get the user to name the "
                "new destination explicitly before import."
            )

    import_allowed = evidence.get("import_allowed")
    if not isinstance(import_allowed, bool):
        errors.append("`import_allowed` must be a boolean.")
    elif require_import_allowed and not import_allowed:
        errors.append("`import_allowed` is false; do not import.")

    return errors, warnings


def validate_preflight(evidence: dict[str, Any], *, require_import_allowed: bool = True) -> tuple[list[str], list[str]]:
    task_type = evidence.get("task_type")
    if task_type == "builder_preflight":
        return validate_builder_preflight(evidence, require_generation_allowed=require_import_allowed)
    if task_type == "creator_preflight":
        return validate_creator_preflight(evidence, require_import_allowed=require_import_allowed)
    return [f"`task_type` must be `builder_preflight` or `creator_preflight`, got `{task_type}`."], []
