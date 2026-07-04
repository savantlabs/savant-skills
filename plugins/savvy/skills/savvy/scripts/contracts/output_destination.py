"""Shared output-destination contract for Planner -> Builder handoff evidence.

This module owns the planned output shape used by handoff section templates,
preflight validation, and workflow generation handoffs. Keep destination field
requirements here instead of restating them across skills.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# Native Savant CSV plus file destinations to connected systems (OneDrive / Google Drive).
# Other file connectors (s3, gcs, sharepoint, sftp, box) exist in Savant but are not yet built here.
SUPPORTED_DESTINATION_TYPES = {"csv", "onedrive", "googledrive"}
FILE_DESTINATION_TYPES = {"onedrive", "googledrive"}
FILE_DESTINATION_FILE_TYPES = {"CSV", "EXCEL"}

OUTPUT_NAME_KEY = "output_name"
BUSINESS_PURPOSE_KEY = "business_purpose"
REQUESTED_DESTINATION_TYPE_KEY = "requested_destination_type"
PLANNED_DESTINATION_TYPE_KEY = "planned_destination_type"
OUTPUT_DESCRIPTION_KEY = "output_description"
FILE_NAME_KEY = "file_name"
EXPECTED_GRAIN_KEY = "expected_grain"
EXPECTED_COLUMNS_KEY = "expected_columns"
REQUIRED_CHECKS_KEY = "required_checks"
VERIFICATION_NODE_NAME_KEY = "verification_node_name"

# File-destination (OneDrive / Google Drive) plan keys. The system itself must already exist in the
# workspace (discover/verify via system-substrate.md); `folder_link` is the only hard environment
# binding the user must supply — the rest is inferred from the problem and defaulted.
SYSTEM_ID_KEY = "system_id"               # the connected system's id -> becomes the node config.id binding
FOLDER_LINK_KEY = "folder_link"
FILE_TYPE_KEY = "file_type"               # EXCEL (default) or CSV
FILE_NAME_MODE_KEY = "file_name_mode"     # static | field
FILE_NAME_FIELD_KEY = "file_name_field"
TAB_NAME_MODE_KEY = "tab_name_mode"       # static | field
TAB_NAME_FIELD_KEY = "tab_name_field"
SUBSEQUENT_MODE_KEY = "subsequent_mode"   # replace (default) | append

UNSUPPORTED_REQUESTED_DESTINATION_KEY = "unsupported_requested_destination"
UNSUPPORTED_NOTICE_PRESENTED_KEY = "unsupported_notice_presented"
UNSUPPORTED_NOTICE_KEY = "unsupported_notice"
SUPPORTED_REQUIRED_CHECKS = {"columns_present", "columns_exact_order", "row_count_nonzero", "no_node_errors"}

OUTPUT_DESTINATION_TEMPLATE = {
    OUTPUT_NAME_KEY: "",
    BUSINESS_PURPOSE_KEY: "",
    REQUESTED_DESTINATION_TYPE_KEY: "csv",
    PLANNED_DESTINATION_TYPE_KEY: "csv",
    OUTPUT_DESCRIPTION_KEY: "",
    FILE_NAME_KEY: "",
    EXPECTED_GRAIN_KEY: "",
    EXPECTED_COLUMNS_KEY: [],
    REQUIRED_CHECKS_KEY: ["columns_exact_order", "row_count_nonzero", "no_node_errors"],
    VERIFICATION_NODE_NAME_KEY: "",
}


def output_destination_template() -> dict[str, Any]:
    return deepcopy(OUTPUT_DESTINATION_TEMPLATE)


def normalize_destination_type(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "").replace("_", "") if value is not None else ""


def is_supported_destination_type(value: Any) -> bool:
    return normalize_destination_type(value) in SUPPORTED_DESTINATION_TYPES


def is_file_destination_type(value: Any) -> bool:
    return normalize_destination_type(value) in FILE_DESTINATION_TYPES


def _validate_file_destination(errors: list[str], output: dict, field_path: str) -> None:
    """Validate the extra fields a file destination (OneDrive / Google Drive) needs. The connected
    system is verified/discovered through system-substrate.md, not here; this only checks the plan."""
    system_id = output.get(SYSTEM_ID_KEY)
    if not isinstance(system_id, str) or not system_id.strip():
        errors.append(
            f"`{field_path}.{SYSTEM_ID_KEY}` is required for a file destination — the connected system's id "
            "(it becomes the destination node's config.id binding). The system must already exist; discover/"
            "verify it via system-substrate.md."
        )
    folder_link = output.get(FOLDER_LINK_KEY)
    if not isinstance(folder_link, str) or not folder_link.strip():
        errors.append(
            f"`{field_path}.{FOLDER_LINK_KEY}` is required for a file destination — the target folder "
            "URL in the connected system (the user supplies it; it cannot be inferred)."
        )
    file_type = str(output.get(FILE_TYPE_KEY) or "EXCEL").strip().upper()
    if file_type not in FILE_DESTINATION_FILE_TYPES:
        errors.append(f"`{field_path}.{FILE_TYPE_KEY}` must be one of: {', '.join(sorted(FILE_DESTINATION_FILE_TYPES))}.")
    for mode_key, field_key in ((FILE_NAME_MODE_KEY, FILE_NAME_FIELD_KEY), (TAB_NAME_MODE_KEY, TAB_NAME_FIELD_KEY)):
        mode = output.get(mode_key)
        if mode is None:
            continue
        if mode not in ("static", "field"):
            errors.append(f"`{field_path}.{mode_key}` must be `static` or `field` when present.")
        elif mode == "field" and not str(output.get(field_key) or "").strip():
            errors.append(f"`{field_path}.{mode_key}=field` requires `{field_path}.{field_key}` (a real upstream column).")
    subsequent = output.get(SUBSEQUENT_MODE_KEY)
    if subsequent is not None and subsequent not in ("replace", "append"):
        errors.append(f"`{field_path}.{SUBSEQUENT_MODE_KEY}` must be `replace` or `append` when present.")


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "y", "1", "confirmed", "passed"}
    return bool(value)


def default_destination_description(output_plan: dict[str, Any]) -> str:
    name = str(output_plan.get(OUTPUT_NAME_KEY, "")).strip()
    purpose = str(output_plan.get(BUSINESS_PURPOSE_KEY, "")).strip()
    if purpose:
        return f"Native Savant CSV output for {name}: {purpose}"
    return f"Native Savant CSV output for {name}."


def destination_description(output_plan: dict[str, Any]) -> str:
    value = output_plan.get(OUTPUT_DESCRIPTION_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default_destination_description(output_plan)


def destination_file_name(output_plan: dict[str, Any]) -> str:
    value = output_plan.get(FILE_NAME_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    name = str(output_plan.get(OUTPUT_NAME_KEY, "")).strip()
    return f"{name}.csv" if name and not name.casefold().endswith(".csv") else name


def validate_output_destination(errors: list[str], warnings: list[str], output: Any, field_path: str) -> None:
    if not isinstance(output, dict):
        errors.append(f"`{field_path}` must be an object.")
        return
    if not isinstance(output.get(OUTPUT_NAME_KEY), str) or not output[OUTPUT_NAME_KEY].strip():
        errors.append(f"`{field_path}.{OUTPUT_NAME_KEY}` is required.")
    if not isinstance(output.get(BUSINESS_PURPOSE_KEY), str) or not output[BUSINESS_PURPOSE_KEY].strip():
        errors.append(f"`{field_path}.{BUSINESS_PURPOSE_KEY}` is required.")
    if not isinstance(output.get(EXPECTED_GRAIN_KEY), str) or not output[EXPECTED_GRAIN_KEY].strip():
        errors.append(f"`{field_path}.{EXPECTED_GRAIN_KEY}` is required so verification knows the output grain.")
    expected_columns = output.get(EXPECTED_COLUMNS_KEY)
    if not isinstance(expected_columns, list) or not expected_columns:
        errors.append(f"`{field_path}.{EXPECTED_COLUMNS_KEY}` must list the expected output columns.")
    elif not all(isinstance(column, str) and column.strip() for column in expected_columns):
        errors.append(f"`{field_path}.{EXPECTED_COLUMNS_KEY}` entries must be non-empty strings.")
    required_checks = output.get(REQUIRED_CHECKS_KEY)
    if not isinstance(required_checks, list) or not required_checks:
        errors.append(f"`{field_path}.{REQUIRED_CHECKS_KEY}` must list at least one verification check.")
    elif not all(isinstance(check, str) and check.strip() for check in required_checks):
        errors.append(f"`{field_path}.{REQUIRED_CHECKS_KEY}` entries must be non-empty strings.")
    else:
        unknown = sorted(set(required_checks) - SUPPORTED_REQUIRED_CHECKS)
        if unknown:
            errors.append(
                f"`{field_path}.{REQUIRED_CHECKS_KEY}` has unsupported check(s): {', '.join(unknown)}. "
                f"Supported checks: {', '.join(sorted(SUPPORTED_REQUIRED_CHECKS))}."
            )
    verification_node_name = output.get(VERIFICATION_NODE_NAME_KEY)
    if verification_node_name is not None and (
        not isinstance(verification_node_name, str)
    ):
        errors.append(f"`{field_path}.{VERIFICATION_NODE_NAME_KEY}` must be a string when provided.")

    requested_type = normalize_destination_type(output.get(REQUESTED_DESTINATION_TYPE_KEY))
    planned_type = normalize_destination_type(output.get(PLANNED_DESTINATION_TYPE_KEY))
    if not requested_type:
        errors.append(f"`{field_path}.{REQUESTED_DESTINATION_TYPE_KEY}` is required.")
    if planned_type not in SUPPORTED_DESTINATION_TYPES:
        errors.append(
            f"`{field_path}.{PLANNED_DESTINATION_TYPE_KEY}` must be one of: "
            f"{', '.join(sorted(SUPPORTED_DESTINATION_TYPES))}."
        )
    elif planned_type in FILE_DESTINATION_TYPES:
        _validate_file_destination(errors, output, field_path)

    requested_supported = requested_type in SUPPORTED_DESTINATION_TYPES
    if requested_type and not requested_supported:
        if not _is_truthy(output.get(UNSUPPORTED_REQUESTED_DESTINATION_KEY)):
            errors.append(f"`{field_path}.{UNSUPPORTED_REQUESTED_DESTINATION_KEY}` must be true for non-CSV requested outputs.")
        if not _is_truthy(output.get(UNSUPPORTED_NOTICE_PRESENTED_KEY)):
            errors.append(f"`{field_path}.{UNSUPPORTED_NOTICE_PRESENTED_KEY}` must be true for non-CSV requested outputs.")
        notice = output.get(UNSUPPORTED_NOTICE_KEY)
        if not isinstance(notice, str) or not notice.strip():
            errors.append(f"`{field_path}.{UNSUPPORTED_NOTICE_KEY}` must tell the user that only CSV is supported today.")
        if planned_type != "csv":
            errors.append(f"`{field_path}` requested an unsupported output, so the planned fallback must be CSV.")
    elif output.get(UNSUPPORTED_REQUESTED_DESTINATION_KEY) is True:
        warnings.append(f"`{field_path}` marks a supported requested output as unsupported.")


def validate_output_destinations(errors: list[str], warnings: list[str], outputs: Any, field_path: str) -> None:
    if not isinstance(outputs, list) or not outputs:
        errors.append(f"`{field_path}` must list the planned workflow outputs.")
        return
    for index, output in enumerate(outputs):
        validate_output_destination(errors, warnings, output, f"{field_path}[{index}]")
