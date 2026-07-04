"""Shared source-plan contract for Planner -> Builder handoff evidence.

The source plan is the Builder-facing workflow input object. It owns workflow
intent (`source_name`, `business_role`, `source_kind`, expected schema, parser
or extraction facts) and nests the resolved Savant dataset binding/profile.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.ai_provider import provider_id_or_default
from contracts.source_profile import (
    EXPECTED_SCHEMA_KEY,
    OBSERVED_SCHEMA_KEY,
    observed_schema_template,
    validate_expected_schema,
    validate_observed_schema,
)


SOURCE_NAME_KEY = "source_name"
BUSINESS_ROLE_KEY = "business_role"
SOURCE_KIND_KEY = "source_kind"
DATASET_KEY = "dataset"
DATASET_ID_KEY = "dataset_id"
CONNECTOR_KEY = "connector"
PROFILE_STATUS_KEY = "profile_status"
ROW_COUNT_KEY = "row_count"
DTYPE_KEY = "dtype"
EXTRACTION_KEY = "extraction"
PARSER_KEY = "parser"
JOIN_KEY_NORMALIZATIONS_KEY = "join_key_normalizations"

SOURCE_KINDS = {"tabular", "binary_document", "json_text", "xml_text"}
DATASET_PROFILE_STATUSES = {"full_profile", "schema_only", "id_only", "user_supplied"}

DATASET_PROFILE_TEMPLATE = {
    DATASET_ID_KEY: "",
    PROFILE_STATUS_KEY: "id_only",
    CONNECTOR_KEY: "",
    ROW_COUNT_KEY: None,
    OBSERVED_SCHEMA_KEY: [],
}

SOURCE_PLAN_TEMPLATE = {
    SOURCE_NAME_KEY: "",
    BUSINESS_ROLE_KEY: "",
    SOURCE_KIND_KEY: "tabular",
    DATASET_KEY: DATASET_PROFILE_TEMPLATE,
    JOIN_KEY_NORMALIZATIONS_KEY: [],
    EXPECTED_SCHEMA_KEY: [
        {"name": "", "dataType": "", "mappedFrom": "", "required": True},
    ],
}


def dataset_profile_template(*, include_observed_schema: bool = False) -> dict[str, Any]:
    template = deepcopy(DATASET_PROFILE_TEMPLATE)
    if include_observed_schema:
        template[PROFILE_STATUS_KEY] = "full_profile"
        template[OBSERVED_SCHEMA_KEY] = observed_schema_template()
    return template


def source_plan_template() -> dict[str, Any]:
    template = deepcopy(SOURCE_PLAN_TEMPLATE)
    template[DATASET_KEY] = dataset_profile_template(include_observed_schema=True)
    return template


def dataset_profile(source_plan: dict[str, Any]) -> dict[str, Any]:
    value = source_plan.get(DATASET_KEY)
    return value if isinstance(value, dict) else {}


def dataset_id(source_plan: dict[str, Any]) -> str:
    value = dataset_profile(source_plan).get(DATASET_ID_KEY)
    return value.strip() if isinstance(value, str) else ""


def connector(source_plan: dict[str, Any]) -> str:
    value = dataset_profile(source_plan).get(CONNECTOR_KEY)
    return value.strip() if isinstance(value, str) else ""


def observed_schema(source_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = dataset_profile(source_plan).get(OBSERVED_SCHEMA_KEY)
    return value if isinstance(value, list) else []


def row_count(source_plan: dict[str, Any]) -> int | None:
    value = dataset_profile(source_plan).get(ROW_COUNT_KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def expected_schema(source_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = source_plan.get(EXPECTED_SCHEMA_KEY)
    return value if isinstance(value, list) else []


def join_key_normalizations(source_plan: dict[str, Any]) -> list[dict[str, Any]]:
    value = source_plan.get(JOIN_KEY_NORMALIZATIONS_KEY)
    return value if isinstance(value, list) else []


def profile_status(source_plan: dict[str, Any]) -> str:
    value = dataset_profile(source_plan).get(PROFILE_STATUS_KEY)
    return value.strip() if isinstance(value, str) else ""


def has_dataset_profile(source_plan: dict[str, Any]) -> bool:
    return profile_status(source_plan) in {"full_profile", "schema_only", "user_supplied"}


def can_apply_sample_based_cleanup(source_plan: dict[str, Any]) -> bool:
    return profile_status(source_plan) in {"full_profile", "user_supplied"} and bool(observed_schema(source_plan))


def validate_dataset_profile(errors: list[str], dataset: Any, field_path: str, *, source_kind: str) -> None:
    if not isinstance(dataset, dict):
        errors.append(f"`{field_path}` must be an object.")
        return
    value = dataset.get(DATASET_ID_KEY)
    if not isinstance(value, str) or not value.strip():
        errors.append(
            f"`{field_path}.{DATASET_ID_KEY}` is required — the Builder needs a resolved dataset id for every source."
        )
    status = dataset.get(PROFILE_STATUS_KEY)
    if status not in DATASET_PROFILE_STATUSES:
        errors.append(
            f"`{field_path}.{PROFILE_STATUS_KEY}` must be one of: "
            f"{', '.join(sorted(DATASET_PROFILE_STATUSES))}."
        )
        status = "id_only"
    connector_value = dataset.get(CONNECTOR_KEY)
    if status != "id_only" and (not isinstance(connector_value, str) or not connector_value.strip()):
        errors.append(f"`{field_path}.{CONNECTOR_KEY}` is required unless profile_status is `id_only`.")
    if ROW_COUNT_KEY in dataset:
        row_count_value = dataset.get(ROW_COUNT_KEY)
        if row_count_value is not None and (
            not isinstance(row_count_value, int) or isinstance(row_count_value, bool) or row_count_value < 0
        ):
            errors.append(f"`{field_path}.{ROW_COUNT_KEY}` must be a non-negative integer when provided.")
    if source_kind == "tabular" and status in {"full_profile", "user_supplied"}:
        validate_observed_schema(errors, dataset.get(OBSERVED_SCHEMA_KEY), f"{field_path}.{OBSERVED_SCHEMA_KEY}")
    elif source_kind == "tabular" and status == "schema_only":
        observed = dataset.get(OBSERVED_SCHEMA_KEY)
        if not isinstance(observed, list) or not observed:
            errors.append(f"`{field_path}.{OBSERVED_SCHEMA_KEY}` is required when profile_status is `schema_only`.")
        else:
            for index, column in enumerate(observed):
                col_label = f"{field_path}.{OBSERVED_SCHEMA_KEY}[{index}]"
                if not isinstance(column, dict):
                    errors.append(f"`{col_label}` must be an object.")
                    continue
                if not isinstance(column.get("name"), str) or not column["name"].strip():
                    errors.append(f"`{col_label}.name` is required.")
                if not isinstance(column.get("dataType"), str) or not column["dataType"].strip():
                    errors.append(f"`{col_label}.dataType` is required.")


def validate_join_key_normalizations(errors: list[str], value: Any, field_path: str) -> None:
    if value in (None, []):
        return
    if not isinstance(value, list):
        errors.append(f"`{field_path}` must be an array when provided.")
        return
    allowed_cases = {"upper", "lower", "preserve"}
    for index, item in enumerate(value):
        item_path = f"{field_path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"`{item_path}` must be an object.")
            continue
        source_field = item.get("source_field")
        output_field = item.get("output_field")
        if not isinstance(source_field, str) or not source_field.strip():
            errors.append(f"`{item_path}.source_field` is required.")
        if not isinstance(output_field, str) or not output_field.strip():
            errors.append(f"`{item_path}.output_field` is required.")
        case_value = item.get("case", "upper")
        if case_value not in allowed_cases:
            errors.append(f"`{item_path}.case` must be one of: upper, lower, preserve.")


def validate_source_plan(errors: list[str], source: Any, field_path: str) -> None:
    if not isinstance(source, dict):
        errors.append(f"`{field_path}` must be an object.")
        return
    source_name = source.get(SOURCE_NAME_KEY)
    if not isinstance(source_name, str) or not source_name.strip():
        errors.append(f"`{field_path}.{SOURCE_NAME_KEY}` is required.")
    if not isinstance(source.get(BUSINESS_ROLE_KEY), str) or not source[BUSINESS_ROLE_KEY].strip():
        errors.append(f"`{field_path}.{BUSINESS_ROLE_KEY}` is required.")
    source_kind = source.get(SOURCE_KIND_KEY)
    if not isinstance(source_kind, str) or not source_kind.strip():
        errors.append(f"`{field_path}.{SOURCE_KIND_KEY}` is required (`tabular`, `binary_document`, `json_text`, or `xml_text`).")
        return
    source_kind = source_kind.strip()
    if source_kind not in SOURCE_KINDS:
        errors.append(f"`{field_path}.{SOURCE_KIND_KEY}` must be `tabular`, `binary_document`, `json_text`, or `xml_text`.")
        return
    validate_dataset_profile(errors, source.get(DATASET_KEY), f"{field_path}.{DATASET_KEY}", source_kind=source_kind)
    if source_kind == "tabular":
        validate_expected_schema(errors, source.get(EXPECTED_SCHEMA_KEY), f"{field_path}.{EXPECTED_SCHEMA_KEY}")
        validate_join_key_normalizations(
            errors,
            source.get(JOIN_KEY_NORMALIZATIONS_KEY, []),
            f"{field_path}.{JOIN_KEY_NORMALIZATIONS_KEY}",
        )
    elif source_kind == "binary_document":
        extraction = source.get(EXTRACTION_KEY)
        if not isinstance(extraction, dict):
            errors.append(f"`{field_path}.{EXTRACTION_KEY}` is required for binary document sources.")
        else:
            if not isinstance(extraction.get("prompt"), str) or not extraction["prompt"].strip():
                errors.append(f"`{field_path}.{EXTRACTION_KEY}.prompt` is required.")
            if "provider_id" in extraction:
                try:
                    provider_id_or_default(extraction.get("provider_id"))
                except ValueError as exc:
                    errors.append(f"`{field_path}.{EXTRACTION_KEY}.provider_id` is invalid: {exc}")
    elif source_kind in {"json_text", "xml_text"}:
        parser = source.get(PARSER_KEY)
        if not isinstance(parser, dict):
            errors.append(f"`{field_path}.{PARSER_KEY}` is required for `{source_kind}` sources.")
        elif source_kind == "xml_text" and parser.get("mode", "SELECT") == "SELECT":
            if not isinstance(parser.get("path"), str) or not parser["path"].strip():
                errors.append(f"`{field_path}.{PARSER_KEY}.path` is required for XML SELECT sources.")
