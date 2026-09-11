#!/usr/bin/env python3
"""Unified Savant stage gate for prechecks and done checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from savant_api import capabilities as savant_capabilities  # noqa: E402
from validators import completion, planner_intake, preflight, skill_readiness, workflow  # noqa: E402


ROLES = {"planner", "builder", "creator", "editor", "q_and_a"}
GATES = {"precheck", "done"}
API_REQUIRED_ROLES = {"creator", "editor"}
HANDOFF_SECTIONS = {
    ("planner", "precheck"): "planner_intake",
    ("planner", "done"): "builder_preflight",
    ("builder", "precheck"): "builder_preflight",
    ("creator", "precheck"): "creator_preflight",
    ("creator", "done"): "completion_evidence",
    ("editor", "precheck"): "editor_readiness",
    ("q_and_a", "precheck"): "q_and_a_readiness",
}

FIELD_GUIDANCE = {
    "ready_for_questions": "Set this to boolean true only when the questions_needed section is ready to ask the user.",
    "ready_for_stage": "Set this to boolean true only after all required questions are answered or resolved.",
    "open_questions": "Use an array of question objects; keep original required questions here as the audit trail.",
    "answered_questions": "Use an array of answer objects for user-provided answers.",
    "deferred_questions": "Use an array of optional deferred question objects; required questions cannot be deferred.",
    "answer_evidence": "Use a short citation to the user's explicit answer or confirmation, not an invented placeholder.",
    "evidence": "Use a short citation to the source of the fact, preference, question, or decision.",
    "required": "Use a JSON boolean, not a string.",
}


def _load_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [f"Evidence file does not exist: {path}"]
    except json.JSONDecodeError as exc:
        return {}, [f"Evidence file is not valid JSON: {exc}"]
    if not isinstance(value, dict):
        return {}, ["Evidence must be a JSON object."]
    return value, []


def _load_optional_json(path: Path | None, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, []
    value, errors = _load_json(path)
    if errors:
        return None, [f"{label}: {error}" for error in errors]
    return value, []


def _verify_report(evidence: Any) -> dict[str, Any] | None:
    """A `workflow verify` report from the evidence, by explicit key or by shape.

    Accepting it by shape means a caller that passes the verify JSON directly (rather than nested
    under `verify_report`) is not silently treated as an unverified edit report.
    """
    if not isinstance(evidence, dict):
        return None
    for key in ("verify_report", "verifyReport"):
        candidate = evidence.get(key)
        if isinstance(candidate, dict):
            return candidate
    if evidence.get("operation") in ("create", "edit", "metadata") and "checks" in evidence:
        return evidence
    return None


def _status(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("status")
        if isinstance(raw, str):
            return raw.strip().lower()
    if isinstance(value, str):
        return value.strip().lower()
    return "unknown"


def _handoff_type(evidence: dict[str, Any]) -> str | None:
    value = evidence.get("handoff_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _handoff_section(evidence: dict[str, Any], role: str, gate: str) -> dict[str, Any]:
    section_name = HANDOFF_SECTIONS.get((role, gate))
    if not section_name:
        return evidence
    sections = evidence.get("sections")
    if not isinstance(sections, dict):
        return evidence
    section = sections.get(section_name)
    if isinstance(section, dict):
        return section
    return evidence


def _artifact_path(evidence: dict[str, Any], key: str) -> str | None:
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    value = artifacts.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _handoff_required_tag(evidence: dict[str, Any]) -> str | None:
    artifacts = evidence.get("artifacts")
    if isinstance(artifacts, dict):
        value = artifacts.get("required_tag")
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = evidence.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("required_tag")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _api_requirement(role: str, api_check: str) -> bool:
    if api_check == "required":
        return True
    if api_check == "skip":
        return False
    return role in API_REQUIRED_ROLES


def _check_result(name: str, ok: bool, detail: str, warnings: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "ok": ok,
        "detail": detail,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _error_field_path(error: str) -> str | None:
    match = re.search(r"`([^`]+)`", error)
    if match:
        return match.group(1)
    match = re.search(r"Required [^`]+ field `([^`]+)` is unresolved", error)
    if match:
        return match.group(1)
    return None


def _expected_shape(error: str) -> str:
    lowered = error.lower()
    if "must be true" in lowered:
        return "boolean true"
    if "must be false" in lowered:
        return "boolean false"
    if "must be a boolean" in lowered:
        return "boolean"
    if "must be an array" in lowered:
        return "array"
    if "must be an object" in lowered:
        return "object"
    if "non-empty string" in lowered:
        return "non-empty string"
    if "must include either" in lowered and "question" in lowered:
        return "object with non-empty question or conversation_goal"
    if "unresolved" in lowered:
        return "resolved required field, backed by known fact, reusable preference, or answered_questions[]"
    return "valid value matching the stage gate contract"


def _guidance_for_path(path: str | None, expected_shape: str) -> str:
    if not path:
        return "Update the evidence object and rerun the same stage gate."
    parts = re.split(r"[.\[]", path)
    last = parts[-1].rstrip("]") if parts else path
    if last in FIELD_GUIDANCE:
        return FIELD_GUIDANCE[last]
    if "question" in path and "object" in expected_shape:
        return "Question items should identify the business field, whether it is required, why it is needed, and what to ask."
    return "Fill this field from confirmed user input, reusable preference, source profile, or deterministic helper output."


def _fix_for_error(error: str) -> dict[str, str]:
    path = _error_field_path(error)
    expected_shape = _expected_shape(error)
    fix: dict[str, str] = {
        "error": error,
        "expectedShape": expected_shape,
        "guidance": _guidance_for_path(path, expected_shape),
    }
    if path:
        fix["fieldPath"] = path
    return fix


def _fixes_for_errors(errors: list[str]) -> list[dict[str, str]]:
    return [_fix_for_error(error) for error in errors]


def _validator_check(
    name: str,
    errors: list[str],
    warnings: list[str],
    *,
    pass_detail: str,
) -> dict[str, Any]:
    if errors:
        result = _check_result(name, False, "; ".join(errors), warnings)
        result["fixes"] = _fixes_for_errors(errors)
        return result
    return _check_result(name, True, pass_detail, warnings)


def _api_check() -> tuple[dict[str, Any], list[str]]:
    try:
        capability = savant_capabilities.detect(probe_live=True)
    except Exception as exc:  # noqa: BLE001 - gate reports capability failures plainly.
        capability = {"api_enabled": False, "reason": f"{type(exc).__name__}: {exc}"}
    if bool(capability.get("api_enabled")):
        return _check_result("api_enabled", True, "Savant API is enabled for the authenticated session."), []
    reason = capability.get("reason") or capability.get("detail") or "API is not available."
    actions = [
        "Re-mint credentials with the `get-api-credentials` MCP tool, then rerun this gate.",
        "If that does not clear it, sign in to Savant in the target workspace, or confirm the "
        "Savant host is reachable from this environment.",
    ]
    return _check_result("api_enabled", False, f"Savant API is not enabled: {reason}"), actions


def _validate_stage(
    role: str,
    gate: str,
    evidence: dict[str, Any],
    workflow_json: Path | None,
    claim: str | None,
    *,
    schema_hints: dict[str, Any] | None = None,
    required_tag: str | None = None,
) -> dict[str, Any]:
    if role == "planner" and gate == "precheck":
        errors, warnings = planner_intake.validate_planner_intake(evidence)
        return _validator_check(
            "planner_intake",
            errors,
            warnings,
            pass_detail="Planner intake is ready for the next planning step.",
        )
    if role == "planner" and gate == "done":
        errors, warnings = preflight.validate_builder_preflight(evidence)
        return _validator_check(
            "builder_handoff",
            errors,
            warnings,
            pass_detail="Planner handoff to Builder is complete.",
        )
    if role == "builder" and gate == "precheck":
        errors, warnings = preflight.validate_builder_preflight(evidence)
        return _validator_check(
            "builder_preflight",
            errors,
            warnings,
            pass_detail="Builder can generate workflow JSON.",
        )
    if role == "builder" and gate == "done":
        path_value = workflow_json or evidence.get("workflow_json")
        if not path_value:
            return _check_result(
                "workflow_json",
                False,
                "Builder done requires a workflow JSON path via --workflow-json or evidence.workflow_json.",
            )
        path = path_value if isinstance(path_value, Path) else Path(str(path_value))
        errors, warnings = workflow.validate(
            path,
            required_tag=required_tag,
            schema_hints=schema_hints,
            block_mergeable_pairs=True,
            block_documentation_gaps=True,
        )
        return _validator_check(
            "workflow_json",
            errors,
            warnings,
            pass_detail="Workflow JSON validation passed.",
        )
    if role == "creator" and gate == "precheck":
        errors, warnings = preflight.validate_creator_preflight(evidence)
        return _validator_check(
            "creator_preflight",
            errors,
            warnings,
            pass_detail="Creator can import into the confirmed folder.",
        )
    if role == "creator" and gate == "done":
        errors, warnings = completion.validate_completion_evidence(evidence, claim=claim)
        return _validator_check(
            "completion_evidence",
            errors,
            warnings,
            pass_detail="Creator completion evidence supports the requested claim.",
        )
    if role == "editor" and gate == "precheck":
        errors, warnings = skill_readiness.validate_skill_readiness(evidence)
        return _validator_check(
            "editor_readiness",
            errors,
            warnings,
            pass_detail="Editor readiness is complete.",
        )
    if role == "editor" and gate == "done":
        # `workflow edit --confirm` cannot report `verified` any more: proving a save persisted
        # needs the recipe read back, which is now an MCP `fetch` followed by `workflow verify`.
        # So the accepted evidence is that verify report — an edit report alone is not enough.
        verify_report = _verify_report(evidence)
        if verify_report is not None:
            if verify_report.get("ok") is True:
                return _check_result(
                    "verify_report",
                    True,
                    "workflow verify passed on the edited flow, which supports an in-place "
                    "completion claim.",
                )
            failed = verify_report.get("failedChecks") or []
            return _check_result(
                "verify_report",
                False,
                "Editor done requires workflow verify to pass; it failed"
                + (f" on: {', '.join(map(str, failed))}." if failed else "."),
            )

        report = evidence.get("edit_report") if isinstance(evidence.get("edit_report"), dict) else evidence
        status = _status(report)
        same_flow = report.get("sameFlowId") if isinstance(report, dict) else None
        if same_flow is False:
            return _check_result(
                "same_flow",
                False,
                "Editor done is blocked because the report indicates the flow id changed.",
            )
        if status == "verified":
            # A pre-Round-3 report, from when the edit command verified itself.
            return _check_result(
                "edit_report",
                True,
                "Edit report is verified and supports an in-place completion claim.",
            )
        return _check_result(
            "edit_report",
            False,
            f"Editor done requires a passing workflow verify report; the edit report status is "
            f"`{status}`. Re-fetch the flow with the MCP `fetch` tool and run "
            f"`savant.py workflow verify --operation edit --before-json <pre-edit recipe>`, then "
            f"pass that report as `verify_report`.",
        )
    if role == "q_and_a" and gate == "precheck":
        errors, warnings = skill_readiness.validate_skill_readiness(evidence)
        return _validator_check(
            "q_and_a_readiness",
            errors,
            warnings,
            pass_detail="Q&A context is ready.",
        )
    return _check_result(
        "stage_route",
        False,
        f"No stage gate is defined for role `{role}` and gate `{gate}`.",
    )


def evaluate(
    role: str,
    gate: str,
    evidence: dict[str, Any],
    *,
    api_check: str = "auto",
    workflow_json: Path | None = None,
    claim: str | None = None,
    schema_hints: dict[str, Any] | None = None,
    required_tag: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    next_actions: list[str] = []
    source_evidence = evidence
    stage_evidence = _handoff_section(evidence, role, gate)

    if role not in ROLES:
        checks.append(_check_result("role", False, f"Unknown role `{role}`."))
    if gate not in GATES:
        checks.append(_check_result("gate", False, f"Unknown gate `{gate}`."))
    if checks:
        return {
            "ok": False,
            "role": role,
            "gate": gate,
            "status": "blocked",
            "checks": checks,
            "nextActions": ["Use a supported role and gate."],
        }

    if workflow_json is None:
        workflow_json_value = _artifact_path(source_evidence, "workflow_json")
        if workflow_json_value:
            workflow_json = Path(workflow_json_value)
    if schema_hints is None:
        schema_hints_path = _artifact_path(source_evidence, "schema_hints")
        if schema_hints_path:
            schema_hints, hint_errors = _load_optional_json(Path(schema_hints_path), "schema_hints")
            if hint_errors:
                checks.append(_check_result("schema_hints", False, "; ".join(hint_errors)))
    if required_tag is None:
        required_tag = _handoff_required_tag(source_evidence)
    if _api_requirement(role, api_check):
        check, actions = _api_check()
        checks.append(check)
        next_actions.extend(actions)

    stage_check = _validate_stage(
        role,
        gate,
        stage_evidence,
        workflow_json,
        claim,
        schema_hints=schema_hints,
        required_tag=required_tag,
    )
    checks.append(stage_check)
    if not stage_check["ok"]:
        next_actions.append(stage_check["detail"])
        for fix in stage_check.get("fixes", [])[:5]:
            field = fix.get("fieldPath", "evidence")
            next_actions.append(
                f"Fix `{field}`: expected {fix['expectedShape']}. {fix['guidance']}"
            )

    ok = all(bool(check.get("ok")) for check in checks)
    if ok:
        next_actions.append(f"{role} {gate} gate is complete.")
    return {
        "ok": ok,
        "role": role,
        "gate": gate,
        "status": "passed" if ok else "blocked",
        "checks": checks,
        "nextActions": next_actions,
        "handoffType": _handoff_type(source_evidence),
    }


def _print_result(result: dict[str, Any], output_path: Path | None) -> None:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("--role", choices=sorted(ROLES), required=True)
    parser.add_argument("--gate", choices=sorted(GATES), required=True)
    parser.add_argument(
        "--api-check",
        choices=["auto", "required", "skip"],
        default="auto",
        help="auto requires API for creator/editor; required always checks; skip never checks.",
    )
    parser.add_argument("--workflow-json", type=Path, help="Workflow JSON path for builder done checks.")
    parser.add_argument(
        "--schema-hints",
        type=Path,
        help="Optional schema hints sidecar for builder done workflow validation.",
    )
    parser.add_argument("--required-tag", help="Required Savvy tracking tag for workflow validation.")
    parser.add_argument(
        "--claim",
        choices=["done", "qualified"],
        help="Completion claim for creator done checks.",
    )
    parser.add_argument("--output-path", type=Path, help="Optional path to write the JSON result.")
    args = parser.parse_args()

    evidence, load_errors = _load_json(args.evidence_json)
    if load_errors:
        result = {
            "ok": False,
            "role": args.role,
            "gate": args.gate,
            "status": "blocked",
            "checks": [_check_result("evidence_json", False, "; ".join(load_errors))],
            "nextActions": load_errors,
        }
        _print_result(result, args.output_path)
        return 1

    schema_hints, hint_errors = _load_optional_json(args.schema_hints, "schema_hints")
    if hint_errors:
        result = {
            "ok": False,
            "role": args.role,
            "gate": args.gate,
            "status": "blocked",
            "checks": [_check_result("schema_hints", False, "; ".join(hint_errors))],
            "nextActions": hint_errors,
        }
        _print_result(result, args.output_path)
        return 1

    result = evaluate(
        args.role,
        args.gate,
        evidence,
        api_check=args.api_check,
        workflow_json=args.workflow_json,
        claim=args.claim,
        schema_hints=schema_hints,
        required_tag=args.required_tag,
    )
    _print_result(result, args.output_path)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
