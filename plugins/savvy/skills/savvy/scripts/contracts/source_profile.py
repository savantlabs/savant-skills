"""Shared observed/expected schema helpers for source-plan contracts.

`source_plan.py` owns the full Planner -> Builder source object. This module owns
the reusable tabular schema/profile pieces nested inside that contract.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


OBSERVED_SCHEMA_KEY = "observed_schema"
EXPECTED_SCHEMA_KEY = "expected_schema"
SAMPLE_VALUES_KEY = "sampleValues"

OBSERVED_FIELD_TEMPLATE = {
    "name": "",
    "dataType": "",
    SAMPLE_VALUES_KEY: [],
}


def observed_schema_template() -> list[dict[str, Any]]:
    return [deepcopy(OBSERVED_FIELD_TEMPLATE)]


def sample_values(column: dict[str, Any]) -> list[Any]:
    values = column.get(SAMPLE_VALUES_KEY)
    return values if isinstance(values, list) else []


def validate_observed_schema(errors: list[str], value: Any, field_path: str) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"`{field_path}` is required for tabular sources and must list observed source fields.")
        return
    for index, column in enumerate(value):
        col_label = f"{field_path}[{index}]"
        if not isinstance(column, dict):
            errors.append(f"`{col_label}` must be an object.")
            continue
        if not isinstance(column.get("name"), str) or not column["name"].strip():
            errors.append(f"`{col_label}.name` is required.")
        if not isinstance(column.get("dataType"), str) or not column["dataType"].strip():
            errors.append(f"`{col_label}.dataType` is required.")
        if not sample_values(column):
            errors.append(f"`{col_label}.{SAMPLE_VALUES_KEY}` must include at least one source sample value.")


def validate_expected_schema(errors: list[str], value: Any, field_path: str) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"`{field_path}` is required for tabular sources.")
        return
    for index, column in enumerate(value):
        col_label = f"{field_path}[{index}]"
        if not isinstance(column, dict):
            errors.append(f"`{col_label}` must be an object.")
            continue
        if not isinstance(column.get("name"), str) or not column["name"].strip():
            errors.append(f"`{col_label}.name` is required.")
        if not isinstance(column.get("dataType"), str) or not column["dataType"].strip():
            errors.append(f"`{col_label}.dataType` is required.")


def validate_tabular_source_profile(errors: list[str], source: dict[str, Any], field_path: str) -> None:
    validate_observed_schema(errors, source.get(OBSERVED_SCHEMA_KEY), f"{field_path}.{OBSERVED_SCHEMA_KEY}")
    validate_expected_schema(errors, source.get(EXPECTED_SCHEMA_KEY), f"{field_path}.{EXPECTED_SCHEMA_KEY}")
