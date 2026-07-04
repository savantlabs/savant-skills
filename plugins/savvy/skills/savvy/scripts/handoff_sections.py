#!/usr/bin/env python3
"""Section templates used by stage handoff envelopes."""

from __future__ import annotations

import sys
from typing import Any

try:
    from contracts.output_destination import output_destination_template
    from contracts.source_plan import source_plan_template
except ImportError:  # Allows direct loading from this directory in deterministic tests.
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from contracts.output_destination import output_destination_template
    from contracts.source_plan import source_plan_template

PREFERENCE_SOURCES = ["conversation", "available memory/context", "project instructions"]
QUESTION_OBJECT_TEMPLATES = {
    "open_questions": [
        {
            "field": "documentation_mode",
            "required": True,
            "question": "Do you want a short working plan or a fuller process document?",
            "evidence": "This is required because documentation depth cannot be inferred from a broad build request.",
        }
    ],
    "answered_questions": [
        {
            "field": "documentation_mode",
            "required": True,
            "answer": "light",
            "answer_evidence": "User explicitly chose a short working plan in chat.",
        }
    ],
    "deferred_questions": [
        {
            "field": "owner",
            "required": False,
            "evidence": "Owner is optional for build-only/light scope and can be deferred.",
        }
    ],
    "ready_for_stage": True,
}


def _question_guidance() -> dict[str, Any]:
    return {
        "validator_ignores_this_key": True,
        "question_object_templates": QUESTION_OBJECT_TEMPLATES,
    }

SECTIONS = {
    "planner_intake": {
        "default_stage": "questions_needed",
        "stages": ("questions_needed", "ready"),
    },
    "builder_preflight": {
        "default_stage": "ready",
        "stages": ("questions_needed", "ready"),
    },
    "creator_preflight": {
        "default_stage": "ready",
        "stages": ("questions_needed", "ready"),
    },
}


def _planner_intake(stage: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "_guidance": _question_guidance(),
        "task_type": "planner_intake_checkpoint",
        "stage": stage,
        "status": "passed",
        "known_preferences_checked": True,
        "preference_sources_checked": list(PREFERENCE_SOURCES),
        "reusable_preferences_applied": [],
        "known_task_facts_applied": [],
        "open_questions": [],
        "answered_questions": [],
        "deferred_questions": [],
    }
    if stage == "ready":
        evidence["ready_for_stage"] = True
    else:
        evidence["ready_for_questions"] = True
    return evidence


def _builder_preflight(stage: str) -> dict[str, Any]:
    if stage == "questions_needed":
        return {
            "_guidance": _question_guidance(),
            "task_type": "builder_preflight",
            "stage": "questions_needed",
            "workflow_name": "",
            "requested_scope": "build_only",
            "open_questions": [],
            "answered_questions": [],
            "deferred_questions": [],
            "ready_for_questions": True,
        }
    return {
        "_guidance": {
            "validator_ignores_this_key": True,
            "question_object_templates": QUESTION_OBJECT_TEMPLATES,
            "common_builder_preflight_rules": [
                "process_metadata.documentation_mode_source must be exactly `user_answer` or `reusable_preference`.",
                "owner, cadence, escalation_owners, and approval fields are required only for detail/governed handoffs or create/import scopes.",
                "Every workflow_plan_checkpoint.process_blocks[].title must appear verbatim in workflow_plan_checkpoint.plan_presented.",
                "Every workflow_plan_checkpoint.material_decisions[] entry needs a non-empty decision and rationale; set reflected_in_handoff true only after verifying the handoff implements that approved decision and adds nothing material beyond the approved decisions (see material-decisions.md).",
                "If local files were supplied, input_dataset_plan.profile_evidence must point to ready source-profile JSON and brief JSON.",
                "Run `savant.py docs handoff-pack --scope <requested_scope>` for the compact source/output/process-block object rules.",
            ],
        },
        "task_type": "builder_preflight",
        "stage": "ready",
        "workflow_name": "",
        "requested_scope": "build_only",
        "process_metadata": {
            "process_name": "",
            "source_skill_or_domain": "",
            "documentation_mode": "",
            "documentation_mode_source": "",
            "documentation_mode_evidence": "",
            "owner": "",
            "cadence": "",
            "escalation_owners": [],
            "approval": {
                "drafted_by": "",
                "certified_by": "",
                "date_certified": "",
            },
        },
        "input_dataset_plan": {
            "required": True,
            "status": "passed",
            "plan_presented": "",
            "profile_evidence": {
                "local_files_provided": False,
                "source_profile_path": "",
                "source_profile_brief_path": "",
                "notes": "",
            },
            "sources": [source_plan_template()],
            "user_confirmed_or_revised": True,
            "user_confirmation_evidence": "",
        },
        "output_destination_plan": {
            "required": True,
            "status": "passed",
            "plan_presented": "",
            "included_in_workflow_plan": True,
            "outputs": [output_destination_template()],
        },
        "workflow_plan_checkpoint": {
            "required": True,
            "status": "passed",
            "format": "workflow_process_plan",
            "plan_presented": "",
            "process_blocks": [],
            "process_steps": [],
            "material_assumptions": [],
            "material_decisions": [],
            "user_confirmed_or_revised": True,
            "user_confirmation_evidence": "",
            "user_review_decision": "approved_as_presented",
        },
        "json_generation_allowed": True,
    }


def _creator_preflight(stage: str) -> dict[str, Any]:
    if stage == "questions_needed":
        return {
            "_guidance": _question_guidance(),
            "task_type": "creator_preflight",
            "stage": "questions_needed",
            "workflow_name": "",
            "workflow_json": "",
            "requested_scope": "draft_import",
            "open_questions": [],
            "answered_questions": [],
            "deferred_questions": [],
            "ready_for_questions": True,
        }
    return {
        "task_type": "creator_preflight",
        "stage": "ready",
        "workflow_name": "",
        "workflow_json": "",
        "requested_scope": "full_verified_workflow",
        "context_confirmation": {
            "status": "passed",
            "target_context": "",
            "user_confirmed": True,
            "user_confirmation_evidence": "",
        },
        "creation_confirmation": {
            "status": "passed",
            "summary_presented": "",
            "user_confirmed": True,
            "user_confirmation_evidence": "",
        },
        "workflow_validation": {"status": "passed"},
        "folder": {"status": "passed", "id": ""},
        "import_allowed": True,
    }


BUILDERS = {
    "planner_intake": _planner_intake,
    "builder_preflight": _builder_preflight,
    "creator_preflight": _creator_preflight,
}


def scaffold(section: str, stage: str | None = None) -> dict[str, Any]:
    if section not in SECTIONS:
        raise ValueError(
            f"Unknown handoff section `{section}`. Choose from: {', '.join(sorted(SECTIONS))}."
        )
    spec = SECTIONS[section]
    resolved_stage = stage or spec["default_stage"]
    if resolved_stage not in spec["stages"]:
        raise ValueError(
            f"`{section}` stage must be one of: {', '.join(spec['stages'])} (got `{resolved_stage}`)."
        )
    return BUILDERS[section](resolved_stage)
