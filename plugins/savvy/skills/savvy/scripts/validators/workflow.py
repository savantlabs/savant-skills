#!/usr/bin/env python3
"""Deterministic preflight checks for Savant workflow JSON."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from contracts.ai_provider import SAVANT_MANAGED_PROVIDER_IDS
from contracts.tracking_tag import is_savvy_tracking_tag, is_versioned_tracking_tag
from workflow import layout_metrics
from workflow import layout_model
from workflow.geometry import (
    EXTERNAL_INPUT_LANDING_MIN,
    NODE_HEIGHT as APPROX_NODE_HEIGHT,
    NODE_WIDTH as APPROX_NODE_WIDTH,
    PORT_ALIGNMENT_TOLERANCE as APPROX_PORT_ALIGNMENT_TOLERANCE,
    PORT_NEAR_MISS_TOLERANCE as APPROX_PORT_NEAR_MISS_TOLERANCE,
    input_port_y_offset,
    label_width_estimate,
    output_port_y_offset,
)


NODE_ID_RE = re.compile(r"^[a-z]+(?:_[a-z]+)*_[a-z0-9]{6}(?:\|\d+)?$")
PROCESSING_TYPES = {
    "adapter",
    "apiService",
    "blend",
    "deduplicate",
    "edit",
    "explode",
    "filter",
    "format",
    "fuzzy_match",
    "gen_ai",
    "hierarchy",
    "json",
    "multi_stack",
    "pdfilter",
    "pdsummarize",
    "pivot",
    "rollup",
    "sample",
    "search_replace",
    "service",
    "split",
    "summarize",
    "unpivot",
    "vision",
    "xml",
}
REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "references" / "registry"
GROUP_HEADER_TEXT_MIN_HEIGHT = layout_model.GROUP_HEADER_TEXT_MIN_HEIGHT
GROUP_HEADER_BAND_MIN_Y = layout_model.GROUP_HEADER_BAND_MIN_Y
GROUP_HEADER_REQUIRED_TEXT_CONFIG_KEYS = {
    "backgroundColor",
    "bold",
    "borderColor",
    "color",
    "currentHeight",
    "fontSize",
    "height",
    "inputText",
    "isInitialized",
    "italic",
    "minHeight",
    "minWidth",
    "strikethrough",
    "text",
    "underline",
    "width",
}
APPROX_GROUPED_NODE_VISUAL_HEIGHT = layout_model.GROUPED_NODE_VISUAL_HEIGHT
GROUPED_NODE_VERTICAL_ROW_GAP_MIN = layout_model.GROUPED_NODE_VERTICAL_ROW_GAP_MIN
GROUP_BOTTOM_PADDING_MIN = layout_model.GROUP_BOTTOM_PADDING_MIN
PARALLEL_BUSINESS_LANE_MIN_GAP = layout_model.PARALLEL_BUSINESS_LANE_MIN_GAP
PARALLEL_BUSINESS_GROUP_MIN_HEIGHT = layout_model.PARALLEL_BUSINESS_GROUP_MIN_HEIGHT
GROUP_VISUAL_MEMBERSHIP_PADDING = layout_model.GROUP_VISUAL_MEMBERSHIP_PADDING
GROUP_SIDE_PADDING_MIN = layout_model.GROUP_SIDE_PADDING_MIN
GROUP_COLUMN_GAP_MIN = layout_model.GROUP_COLUMN_GAP_MIN
GROUP_WIDTH_EXTRA_ALLOWANCE = layout_model.GROUP_WIDTH_EXTRA_ALLOWANCE
GROUP_COLUMN_CLUSTER_TOLERANCE = layout_model.GROUP_COLUMN_CLUSTER_TOLERANCE
NODE_LABEL_GUTTER_MIN = layout_model.NODE_LABEL_GUTTER_MIN
GROUP_TOP_ALIGNMENT_TOLERANCE = layout_model.GROUP_TOP_ALIGNMENT_TOLERANCE
GROUP_HEIGHT_ALIGNMENT_TOLERANCE = layout_model.GROUP_HEIGHT_ALIGNMENT_TOLERANCE
GROUP_HEIGHT_EXCESS_ALLOWANCE = layout_model.GROUP_HEIGHT_EXCESS_ALLOWANCE
GROUP_HEIGHT_EXCESS_RATIO = layout_model.GROUP_HEIGHT_EXCESS_RATIO
UNIFORM_LARGE_GROUP_HEIGHT_MIN = layout_model.UNIFORM_LARGE_GROUP_HEIGHT_MIN
UNIFORM_GROUP_EMPTY_RATIO_MIN = layout_model.UNIFORM_GROUP_EMPTY_RATIO_MIN
GROUP_GUTTER_ALIGNMENT_TOLERANCE = layout_model.GROUP_GUTTER_ALIGNMENT_TOLERANCE
GROUP_GUTTER_MIN = layout_model.GROUP_GUTTER_MIN
GROUP_GUTTER_MAX = layout_model.GROUP_GUTTER_MAX
GROUP_CONTENT_CENTERING_TOLERANCE = layout_model.GROUP_CONTENT_CENTERING_TOLERANCE
OUTPUT_GROUP_BELOW_MAIN_LANE_TOLERANCE = layout_model.OUTPUT_GROUP_BELOW_MAIN_LANE_TOLERANCE
MIN_WORKFLOW_DESCRIPTION_CHARS = 80
MIN_NODE_DESCRIPTION_CHARS = 40
MIN_GROUP_HEADER_CHARS = 24
PROFILE_EVIDENCE_KEYS = {
    "liveSourceProfiles",
    "sourceProfiles",
    "sourceProfiling",
    "sourceProfile",
    "validationEvidence",
    "reconciliationEvidence",
}
FIELD_REF_KEYS = {"fieldId", "fieldName", "src_cols"}
BUSINESS_PROCESSING_TYPES = PROCESSING_TYPES - {"adapter"}
BUSINESS_RECORD_TERMS = (
    "obligation",
    "loan",
    "transaction",
    "invoice",
)
ENRICHMENT_TYPES = {"blend", "fuzzy_match", "summarize", "rollup", "destination"}
FILTER_PUSHDOWN_REVIEW_TYPES = {
    "apiService",
    "blend",
    "fuzzy_match",
    "gen_ai",
    "multi_stack",
    "pivot",
    "rollup",
    "service",
    "summarize",
    "unpivot",
    "vision",
}
DESCRIBED_NODE_TYPES = PROCESSING_TYPES | {"source", "destination"}
# AI components whose output schema is not knowable from the registry or config at
# design time: vision/gen_ai produce columns from a prompt (materialized at runtime,
# often after a downstream `json` flatten); fuzzy_match adds match columns. The
# schema-inference pass must NOT pretend their output equals the upstream schema —
# doing so makes downstream references to AI-produced columns fail with false
# "column not found" errors. Either the build supplies an expected-output-columns
# hint (see --schema-hints) and we treat the declared schema as known, or we mark
# the output schema unknown so downstream column checks are skipped.
AI_OPAQUE_OUTPUT_TYPES = {"gen_ai", "vision", "fuzzy_match"}
PLACEHOLDER_BINDING_TOKENS = (
    "placeholder",
    "replace-me",
    "replace_me",
    "todo",
    "dummy",
    "example",
    "sample",
)


def read_registry_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    return value if isinstance(value, dict) else {}


def load_registry(root: Path = REGISTRY_ROOT) -> dict[str, Any]:
    index = read_registry_json(root / "index.json")
    common: dict[str, Any] = {}
    common_rel = (index.get("common") or {}).get("lookupOperators") if isinstance(index.get("common"), dict) else None
    if isinstance(common_rel, str):
        common = read_registry_json(root / common_rel)
    components: dict[str, Any] = {}
    for component_type, rel_path in (index.get("components") or {}).items():
        if isinstance(component_type, str) and isinstance(rel_path, str):
            components[component_type] = read_registry_json(root / rel_path)
    return {"index": index, "common": common, "components": components}


def enum_values(rule: dict[str, Any], key: str) -> set[Any]:
    enums = rule.get("enumParams")
    if not isinstance(enums, dict):
        return set()
    values = enums.get(key)
    return set(values) if isinstance(values, list) else set()


def validate_required_params(
    params: dict[str, Any],
    required: Any,
    context: str,
    errors: list[str],
    allow_empty: Any = None,
) -> None:
    allow_empty_params = set(allow_empty) if isinstance(allow_empty, list) else set()
    for key in required if isinstance(required, list) else []:
        if key not in params or params.get(key) is None or (params.get(key) == "" and key not in allow_empty_params):
            errors.append(f"{context} is missing required parameter `{key}`.")


def validate_enum_params(
    params: dict[str, Any],
    rule: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    enums = rule.get("enumParams")
    if not isinstance(enums, dict):
        return
    for key, values in enums.items():
        if key not in params or not isinstance(values, list):
            continue
        if params.get(key) not in values:
            allowed = ", ".join(f"`{value}`" for value in values)
            errors.append(f"{context} has invalid `{key}` value `{params.get(key)}`. Use one of: {allowed}.")


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def ai_missing_provider_nodes(nodes: list[dict]) -> list[str]:
    """Names of AI-backed nodes with no providerId — Savant silently drops these on import.

    Shared pre-write content check used by `workflow create` preflight and the
    `workflow edit --replace-from-build` path (one implementation, both gates)."""
    bad = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") in AI_OPAQUE_OUTPUT_TYPES:
            if not (n.get("config") or {}).get("providerId"):
                bad.append(n.get("name") or n.get("id"))
    return bad


# Export-only config envelope keys. The GenAI builder never emits these; an AI node's
# connector is resolved from `providerId` at import. A copied workflow export carries them,
# and a literal connector silently drops the whole node — see `_gen_ai_config` in the builder.
_AI_EXPORT_ONLY_CONFIG_KEYS = ("type", "connector")


def ai_node_export_keys(config: dict) -> list[str]:
    """Export-only keys (`type`/`connector`) present on an AI node's config, in declared order.

    Empty when the config is builder-shaped. Pure predicate shared by `validate` and tests."""
    if not isinstance(config, dict):
        return []
    return [k for k in _AI_EXPORT_ONLY_CONFIG_KEYS if k in config]


def source_placeholder_nodes(nodes: list[dict]) -> list[str]:
    """Names of source nodes whose dataset binding is a placeholder, not a real dataset id."""
    bad = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "source":
            if looks_placeholder_binding_id((n.get("config") or {}).get("id")):
                bad.append(n.get("name") or n.get("id"))
    return bad


def unresolved_source_dataset_ids(nodes: list[dict], workspace_ids: set[str]) -> list[str]:
    """`Name (dataset_id)` for each source whose bound dataset id does not resolve in the
    target workspace. Dataset ids are WORKSPACE-scoped; an id from another workspace looks
    real but Savant silently drops that source node on import/save (verified live 2026-06-10)."""
    unresolved = []
    for n in nodes:
        if not isinstance(n, dict) or n.get("type") != "source":
            continue
        dataset_id = (n.get("config") or {}).get("id")
        if isinstance(dataset_id, str) and dataset_id and not looks_placeholder_binding_id(dataset_id) \
                and dataset_id not in workspace_ids:
            unresolved.append(f"{n.get('name') or n.get('id')} ({dataset_id})")
    return unresolved


def unresolved_ai_provider_nodes(nodes: list[dict], provider_ids: set[str]) -> list[str]:
    """`Name (providerId)` for each AI node whose bound `providerId` does not resolve in the
    target workspace. Provider ids are WORKSPACE-scoped (customer-created); an id copied from
    another workspace's export looks real but Savant silently drops the AI node on import.

    The platform-managed ids (`savant_anthropic`/`savant_openai`/`savant_gemini` and the legacy
    unified `savant-ai-provider-gzilpzflks`) are exempt: they are NOT workspace-scoped, so they
    cannot be unresolved here, and `provider_ids` does not necessarily list them. MCP `search`
    returns the managed providers only when the workspace has no key of its own, and never
    returns the legacy Fuse id at all — so checking them against that listing would flag every
    builder-default AI node in a workspace that has its own keys, and every correctly-built
    `fuzzy_match` node everywhere. Nodes with no `providerId` are left to
    `ai_missing_provider_nodes` (one cause, one message)."""
    unresolved = []
    for n in nodes:
        if not isinstance(n, dict) or n.get("type") not in AI_OPAQUE_OUTPUT_TYPES:
            continue
        provider_id = (n.get("config") or {}).get("providerId")
        if not isinstance(provider_id, str) or not provider_id:
            continue
        if provider_id in SAVANT_MANAGED_PROVIDER_IDS:
            continue
        if provider_id not in provider_ids:
            unresolved.append(f"{n.get('name') or n.get('id')} ({provider_id})")
    return unresolved


def looks_placeholder_binding_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    normalized = value.strip().casefold()
    return (
        normalized in {"id", "dataset_id", "dataset-id", "source_id", "source-id"}
        or normalized.endswith("-placeholder")
        or normalized.endswith("_placeholder")
        or any(token in normalized for token in PLACEHOLDER_BINDING_TOKENS)
    )


def validate_config_schema(
    config: dict[str, Any],
    schema: Any,
    context: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(schema, dict):
        return
    validate_required_params(
        config,
        schema.get("required"),
        context,
        errors,
        schema.get("allowEmptyParams"),
    )
    validate_enum_params(config, {"enumParams": schema.get("enum")}, context, errors)
    for key in schema.get("nonEmptyString") if isinstance(schema.get("nonEmptyString"), list) else []:
        if key in config and (not isinstance(config.get(key), str) or not config.get(key).strip()):
            errors.append(f"{context} has invalid `{key}`; expected a non-empty string.")
    for key in schema.get("nonEmptyList") if isinstance(schema.get("nonEmptyList"), list) else []:
        if key in config and (not isinstance(config.get(key), list) or not config.get(key)):
            errors.append(f"{context} has invalid `{key}`; expected a non-empty list.")
    for key in schema.get("list") if isinstance(schema.get("list"), list) else []:
        if key in config and not isinstance(config.get(key), list):
            errors.append(f"{context} has invalid `{key}`; expected a list.")
    for key in schema.get("object") if isinstance(schema.get("object"), list) else []:
        if key in config and not isinstance(config.get(key), dict):
            errors.append(f"{context} has invalid `{key}`; expected an object.")
    for key in schema.get("bool") if isinstance(schema.get("bool"), list) else []:
        if key in config and not isinstance(config.get(key), bool):
            errors.append(f"{context} has invalid `{key}`; expected true or false.")
    for key in schema.get("positiveInt") if isinstance(schema.get("positiveInt"), list) else []:
        if key in config and not is_positive_int(config.get(key)):
            errors.append(f"{context} has invalid `{key}`; expected a positive integer.")
    # Savant stores some numeric fields (e.g. gen_ai/service `rowLimit`) as either an int
    # (current UI) or a numeric string (older exports) — both are accepted live. Verified by
    # round-trip: saving "1000" persists as the string "1000"; saving 1000 persists as int.
    for key in schema.get("positiveIntOrNumericString") if isinstance(schema.get("positiveIntOrNumericString"), list) else []:
        if key in config:
            value = config.get(key)
            ok = is_positive_int(value) or (
                isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0
            )
            if not ok:
                errors.append(
                    f"{context} has invalid `{key}`; expected a positive integer or a positive numeric string."
                )
    for key in schema.get("positiveNumber") if isinstance(schema.get("positiveNumber"), list) else []:
        if key in config and not is_positive_number(config.get(key)):
            errors.append(f"{context} has invalid `{key}`; expected a positive number.")
    for key in schema.get("warnIfMissing") if isinstance(schema.get("warnIfMissing"), list) else []:
        if key not in config or config.get(key) in (None, ""):
            warnings.append(f"{context} is missing recommended parameter `{key}`.")


def validate_sort_pairs(value: Any, directions: set[str], context: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        return
    for idx, item in enumerate(value):
        if not isinstance(item, list) or len(item) < 2:
            errors.append(f"{context} sort {idx} should be `[field, direction]`.")
            continue
        direction = item[1]
        if isinstance(direction, str) and directions and direction not in directions:
            allowed = ", ".join(f"`{value}`" for value in sorted(directions))
            errors.append(f"{context} sort {idx} uses unsupported direction `{direction}`. Use one of: {allowed}.")


def validate_csv_destination_config(config: dict[str, Any], context: str, errors: list[str]) -> None:
    if "fileSystemConfig" in config:
        errors.append(
            f"{context} is a native CSV destination but includes `fileSystemConfig`; "
            "use the native CSV shape (`id`, `name`, `type: csv`, `connector: csv`, `mode: update`) "
            "or use a real file-system connector such as OneDrive, SharePoint, S3, or SFTP for file writes."
        )
        return

    for key in ("id", "name", "type", "connector", "mode"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            errors.append(f"{context} native CSV `{key}` is required.")
    if config.get("type") != "csv":
        errors.append(f"{context} native CSV `type` must be `csv`.")
    if config.get("connector") != "csv":
        errors.append(f"{context} native CSV `connector` must be `csv`.")
    if config.get("mode") != "update":
        errors.append(f"{context} native CSV `mode` must be `update`.")


# File destinations write to a connected system (OneDrive / Google Drive / SharePoint / S3 / GCS /
# Box / SFTP). The output file is a CSV or an Excel workbook (Excel can write one tab, or a tab per
# field value). The connected system itself is verified through system-substrate.md, not here.
_FILE_SYSTEM_DESTINATION_FILE_TYPES = {"CSV", "EXCEL"}


def validate_file_system_destination_config(config: dict[str, Any], context: str, errors: list[str]) -> None:
    if not isinstance(config.get("id"), str) or not config["id"].strip():
        errors.append(
            f"{context} file-system destination requires `config.id` — the connected system's id, which "
            "binds the destination to the system (must already exist; see system-substrate.md)."
        )
    file_system = config.get("fileSystemConfig")
    if not isinstance(file_system, dict):
        errors.append(f"{context} file-system destination is missing `fileSystemConfig`.")
        return

    for key in ("fileNameMode", "fileType", "subsequentMode"):
        if not isinstance(file_system.get(key), str) or not file_system[key].strip():
            errors.append(f"{context} file-system `fileSystemConfig.{key}` is required.")

    file_type = file_system.get("fileType")
    if file_type not in _FILE_SYSTEM_DESTINATION_FILE_TYPES:
        errors.append(
            f"{context} file-system `fileSystemConfig.fileType` must be one of: "
            f"{', '.join(sorted(_FILE_SYSTEM_DESTINATION_FILE_TYPES))}."
        )
    if not str(file_system.get("folderLink") or "").strip():
        errors.append(
            f"{context} file-system `fileSystemConfig.folderLink` is required — the target folder URL "
            "in the connected system. The system must already exist (see system-substrate.md)."
        )

    if file_system.get("fileNameMode") not in {"static", "field"}:
        errors.append(f"{context} file-system `fileSystemConfig.fileNameMode` must be `static` or `field`.")
    if file_system.get("fileNameMode") == "static" and not str(file_system.get("fileName") or "").strip():
        errors.append(f"{context} file-system static file naming requires a non-empty `fileSystemConfig.fileName`.")
    if file_system.get("fileNameMode") == "field" and not str(file_system.get("fileNameField") or "").strip():
        errors.append(f"{context} file-system field-based file naming requires `fileSystemConfig.fileNameField`.")
    if file_system.get("subsequentMode") not in {"replace", "append"}:
        errors.append(f"{context} file-system `fileSystemConfig.subsequentMode` must be `replace` or `append`.")

    for key in ("subFolderNameMode", "tabNameMode"):
        value = file_system.get(key)
        if value is not None and value not in {"static", "field"}:
            errors.append(f"{context} file-system `fileSystemConfig.{key}` must be `static` or `field` when present.")
    if file_system.get("subFolderNameMode") == "field" and not str(file_system.get("subFolderNameField") or "").strip():
        errors.append(f"{context} file-system field-based subfolder naming requires `fileSystemConfig.subFolderNameField`.")
    if file_system.get("tabNameMode") == "static" and file_type == "EXCEL" and not str(file_system.get("tabName") or "").strip():
        errors.append(f"{context} file-system Excel with static tab naming requires a non-empty `fileSystemConfig.tabName`.")
    if file_system.get("tabNameMode") == "field" and not str(file_system.get("tabNameField") or "").strip():
        errors.append(f"{context} file-system field-based tab naming requires `fileSystemConfig.tabNameField`.")

    flat_file = file_system.get("flatFileConfig")
    if not isinstance(flat_file, dict):
        errors.append(f"{context} file-system `fileSystemConfig.flatFileConfig` is required.")
        return
    writer_props = flat_file.get("fileWriterProps")
    if not isinstance(writer_props, dict):
        errors.append(f"{context} file-system `fileSystemConfig.flatFileConfig.fileWriterProps` is required.")
        return
    for key in ("charset", "delimiter", "escape", "qualifier"):
        if not isinstance(writer_props.get(key), str) or writer_props[key] == "":
            errors.append(
                f"{context} file-system `fileSystemConfig.flatFileConfig.fileWriterProps.{key}` is required."
            )


def validate_adapter_specs(
    config: dict[str, Any],
    component: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    specs = config.get("specs")
    if not isinstance(specs, list):
        return
    if not specs:
        errors.append(f"{context} has empty `specs`; Adapter needs at least one mapped output field.")
        return
    names: list[str] = []
    allowed_types = set(component.get("specDataTypes") or [])
    spec_schema = component.get("specSchema") if isinstance(component.get("specSchema"), dict) else {}
    for idx, spec in enumerate(specs):
        if not isinstance(spec, dict):
            errors.append(f"{context} spec {idx} is not an object.")
            continue
        validate_config_schema(spec, spec_schema, f"{context} spec {idx}", errors, [])
        name = spec.get("name")
        if isinstance(name, str):
            names.append(name)
        data_type = spec.get("dataType")
        if isinstance(data_type, str) and allowed_types and data_type not in allowed_types:
            allowed = ", ".join(f"`{value}`" for value in allowed_types)
            errors.append(f"{context} spec `{name or idx}` has unsupported data type `{data_type}`. Use one of: {allowed}.")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"{context} has duplicate spec output name(s): {', '.join(f'`{name}`' for name in duplicates)}.")


def validate_format_steps(
    config: dict[str, Any],
    component: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    actions = set(component.get("stepActions") or [])
    matchers = set(component.get("matchers") or [])
    data_types = set(component.get("dataTypes") or [])
    for idx, step in enumerate(as_list(config.get("steps"))):
        if not isinstance(step, dict):
            errors.append(f"{context} step {idx} is not an object.")
            continue
        action = step.get("action")
        if isinstance(action, str) and actions and action not in actions:
            errors.append(f"{context} step {idx} uses unsupported action `{action}`.")
        matcher = step.get("matcher")
        if isinstance(matcher, str) and matchers and matcher not in matchers:
            errors.append(f"{context} step {idx} uses unsupported matcher `{matcher}`.")
        params = step.get("params")
        if action == "change_type" and isinstance(params, list) and params:
            data_type = params[0]
            if isinstance(data_type, str) and data_types and data_type not in data_types:
                allowed = ", ".join(f"`{value}`" for value in data_types)
                errors.append(f"{context} step {idx} uses unsupported target data type `{data_type}`. Use one of: {allowed}.")
    sort = config.get("sort")
    if isinstance(sort, dict):
        direction = sort.get("direction")
        directions = set(component.get("sortDirections") or [])
        if isinstance(direction, str) and directions and direction not in directions:
            errors.append(f"{context} sort uses unsupported direction `{direction}`.")


def validate_service_config(
    config: dict[str, Any],
    component: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    service_type = config.get("serviceType")
    if service_type == "APIService":
        api_config = config.get("apiServiceConfig")
        if not isinstance(api_config, dict):
            errors.append(f"{context} API service is missing object `apiServiceConfig`.")
            return
        validate_required_params(api_config, ["url", "method"], f"{context} API service config", errors)
        method = api_config.get("method")
        methods = set(component.get("apiMethods") or [])
        if isinstance(method, str) and methods and method not in methods:
            errors.append(f"{context} API service uses unsupported method `{method}`.")
        period = api_config.get("period")
        periods = set(component.get("periods") or [])
        if isinstance(period, str) and periods and period not in periods:
            errors.append(f"{context} API service uses unsupported rate-limit period `{period}`.")
        result_format = api_config.get("resultFormat")
        formats = set(component.get("resultFormats") or [])
        if isinstance(result_format, str) and formats and result_format not in formats:
            errors.append(f"{context} API service uses unsupported result format `{result_format}`.")
    elif service_type == "LLMService":
        validate_required_params(config, ["mode", "prompt", "inputField", "providerId"], f"{context} LLM service", errors)


def workflow_parameter_names(workflow: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for param in as_list(workflow.get("parameters")):
        if isinstance(param, dict) and isinstance(param.get("name"), str):
            names.add(param["name"])
    return names


def validate_lookup_operators(
    value: Any,
    allowed: set[str],
    unsupported: set[str],
    context: str,
    errors: list[str],
) -> None:
    if isinstance(value, dict):
        operator = value.get("operator")
        if isinstance(operator, str):
            if operator in unsupported:
                errors.append(f"{context} uses unsupported lookup operator `{operator}`.")
            elif operator not in allowed:
                errors.append(f"{context} uses unknown lookup operator `{operator}`.")
        for child in value.values():
            validate_lookup_operators(child, allowed, unsupported, context, errors)
    elif isinstance(value, list):
        for child in value:
            validate_lookup_operators(child, allowed, unsupported, context, errors)


def derive_id(name: Any) -> str:
    """Derive a Savant field id from a column display name.

    Savant assigns column ids by lowercasing the name and replacing every
    non-alphanumeric character with `_`. This is the shared mechanism the
    builder uses to compute ids offline and the validator uses to check them.
    Verified against 114 real (name, id) pairs: it matches for every uniquely
    named column. The only divergence is duplicate-name collisions (e.g. a
    second `Amount` after a join becomes `amount_2`, not derivable from the
    display name) — those must be reconciled from the live dataset schema at
    creation time, not derived here.
    """
    return re.sub(r"[^a-z0-9]", "_", str(name).lower())


VALID_FIELD_ID = re.compile(r"[a-z0-9_]+")
OUTLET_ID_RE = re.compile(r"out_\d+")


def is_live_blend_duplicate_field_id(field_id: Any, field_name: Any) -> bool:
    if not isinstance(field_id, str) or not isinstance(field_name, str):
        return False
    match = re.fullmatch(r"(.+) \(rhs(?: (\d+))?\)", field_name)
    if not match:
        return False
    base = match.group(1)
    suffix = int(match.group(2) or "1") + 1
    return field_id == f"{base}_{suffix}"


def validate_pipeline_steps(
    steps: list[Any],
    transforms: dict[str, Any],
    unsupported: set[str],
    declared_params: set[str],
    context: str,
    errors: list[str],
) -> None:
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        transform = step.get("transform")
        if not isinstance(transform, str):
            errors.append(f"{context} pipeline step {idx} has no string `transform`.")
            continue
        if transform in unsupported:
            errors.append(f"{context} pipeline step {idx} uses unsupported transform `{transform}`.")
            continue
        rule = transforms.get(transform)
        if not isinstance(rule, dict):
            errors.append(f"{context} pipeline step {idx} uses unknown transform `{transform}`.")
            continue
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        required_params = rule.get("requiredParams")
        if transform == "date_add" and "offset" not in params:
            src_cols = step.get("src_cols")
            if isinstance(src_cols, list) and len(src_cols) >= 2:
                required_params = [p for p in (required_params or []) if p != "offset"]
        validate_required_params(
            params,
            required_params,
            f"{context} `{transform}` step",
            errors,
            rule.get("allowEmptyParams"),
        )
        validate_enum_params(params, rule, f"{context} `{transform}` step", errors)
        if transform == "variable":
            name = params.get("name")
            if isinstance(name, str) and declared_params and name not in declared_params:
                errors.append(f"{context} references undeclared workflow parameter `{name}`.")


EXPRESSION_FUNCTION_ALIASES = {
    "ceil": "ceiling",
    "length": "length",
}
EXPRESSION_KEYWORDS = {
    "and",
    "or",
    "not",
    "is",
    "null",
    "true",
    "false",
    "case",
    "when",
    "then",
    "else",
    "end",
    "interval",
}
EXPRESSION_BINARY_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "+", "-", "*", "/", "&&", "||"}
EXPRESSION_OPERATOR_ALIASES = {
    "=": "eq",
    "!=": "neq",
    "<>": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "+": "add",
    "-": "sub",
    "*": "mul",
    "/": "div",
    "&&": "and",
    "||": "or",
}
EXPRESSION_PIPELINE_EQUIVALENTS = {
    "length": {"text_len"},
    "lower": {"text_case", "lower"},
    "upper": {"text_case", "upper"},
    "proper": {"text_case"},
    # presence ops compile to a `unary` pipeline transform (operator is_null/not_null);
    # corpus-verified filter shape — see node_builders filter `is_null`/`not_null`.
    "is_null": {"unary"},
    "not_null": {"unary"},
}
def tokenize_expression(expression: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    tokens: list[tuple[str, str, int]] = []
    errors: list[str] = []
    idx = 0
    while idx < len(expression):
        char = expression[idx]
        if char.isspace():
            idx += 1
            continue
        if char == "`":
            end = expression.find("`", idx + 1)
            if end == -1:
                errors.append("unterminated field reference")
                break
            tokens.append(("FIELD", expression[idx + 1 : end], idx))
            idx = end + 1
            continue
        if char in {"'", '"'}:
            quote = char
            start = idx
            idx += 1
            escaped = False
            while idx < len(expression):
                current = expression[idx]
                if current == "\\" and not escaped:
                    escaped = True
                    idx += 1
                    continue
                if current == quote and not escaped:
                    break
                escaped = False
                idx += 1
            if idx >= len(expression):
                errors.append("unterminated string literal")
                break
            tokens.append(("STRING", expression[start + 1 : idx], start))
            idx += 1
            continue
        if char == "@":
            match = re.match(r"@[A-Za-z_][A-Za-z0-9_]*", expression[idx:])
            if not match:
                errors.append(f"invalid variable reference near position {idx}")
                idx += 1
                continue
            tokens.append(("VARIABLE", match.group(0)[1:], idx))
            idx += len(match.group(0))
            continue
        if char.isdigit() or (char == "." and idx + 1 < len(expression) and expression[idx + 1].isdigit()):
            match = re.match(r"(?:\d+(?:\.\d*)?|\.\d+)", expression[idx:])
            assert match is not None
            tokens.append(("NUMBER", match.group(0), idx))
            idx += len(match.group(0))
            continue
        if char.isalpha() or char == "_":
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", expression[idx:])
            assert match is not None
            tokens.append(("IDENT", match.group(0), idx))
            idx += len(match.group(0))
            continue
        two = expression[idx : idx + 2]
        if two in {">=", "<=", "!=", "<>", "&&", "||"}:
            tokens.append(("OP", two, idx))
            idx += 2
            continue
        if char in "=+-*/><(),":
            token_type = "PUNCT" if char in "()," else "OP"
            tokens.append((token_type, char, idx))
            idx += 1
            continue
        errors.append(f"unexpected character `{char}` near position {idx}")
        idx += 1
    return tokens, errors


def normalize_expression_function(name: str) -> str:
    lowered = name.lower()
    return EXPRESSION_FUNCTION_ALIASES.get(lowered, lowered)


def expression_function_calls(tokens: list[tuple[str, str, int]]) -> tuple[list[tuple[str, int, int]], list[str]]:
    calls: list[tuple[str, int, int]] = []
    errors: list[str] = []
    stack: list[int] = []
    for idx, token in enumerate(tokens):
        token_type, value, pos = token
        if value == "(":
            stack.append(idx)
        elif value == ")":
            if not stack:
                errors.append(f"unmatched closing parenthesis near position {pos}")
            else:
                stack.pop()
        if token_type == "IDENT" and value.lower() not in EXPRESSION_KEYWORDS:
            if idx + 1 < len(tokens) and tokens[idx + 1][1] == "(":
                calls.append((normalize_expression_function(value), idx, idx + 1))
    for open_idx in stack:
        errors.append(f"unclosed parenthesis near position {tokens[open_idx][2]}")
    return calls, errors


def expression_call_arg_count(tokens: list[tuple[str, str, int]], open_idx: int) -> tuple[int | None, str | None]:
    depth = 0
    count = 0
    saw_arg = False
    previous_comma = False
    for idx in range(open_idx, len(tokens)):
        value = tokens[idx][1]
        if value == "(":
            depth += 1
            if depth > 1:
                saw_arg = True
        elif value == ")":
            depth -= 1
            if depth == 0:
                if previous_comma:
                    return None, f"trailing comma near position {tokens[idx][2]}"
                return (count + 1 if saw_arg else 0), None
            if depth < 0:
                return None, f"unmatched closing parenthesis near position {tokens[idx][2]}"
        elif depth == 1 and value == ",":
            if previous_comma or not saw_arg:
                return None, f"empty function argument near position {tokens[idx][2]}"
            count += 1
            previous_comma = True
            continue
        elif depth >= 1:
            saw_arg = True
        previous_comma = False if value != "," else previous_comma
    return None, f"unclosed function call near position {tokens[open_idx][2]}"


def validate_expression_arity(
    function_name: str,
    arity: Any,
    actual: int,
    context: str,
    errors: list[str],
) -> None:
    if arity is None:
        return
    if isinstance(arity, int):
        if actual != arity:
            errors.append(f"{context} function `{function_name}` expects {arity} argument(s), got {actual}.")
    elif isinstance(arity, list) and all(isinstance(item, int) for item in arity):
        if actual not in arity:
            allowed = ", ".join(str(item) for item in arity)
            errors.append(f"{context} function `{function_name}` expects one of [{allowed}] argument(s), got {actual}.")
    elif arity == "variadic_pairs":
        if actual == 0 or actual % 2 != 0:
            errors.append(f"{context} function `{function_name}` expects condition/value argument pairs, got {actual}.")


def lookup_operator_set(value: Any) -> set[str]:
    operators: set[str] = set()
    if isinstance(value, dict):
        operator = value.get("operator")
        if isinstance(operator, str):
            operators.add(operator)
        for child in value.values():
            operators.update(lookup_operator_set(child))
    elif isinstance(value, list):
        for child in value:
            operators.update(lookup_operator_set(child))
    return operators


def pipeline_transform_set(steps: list[Any]) -> set[str]:
    transforms: set[str] = set()
    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("transform"), str):
            transforms.add(step["transform"])
    return transforms


def validate_expression_text(
    expression: Any,
    common: dict[str, Any],
    context: str,
    errors: list[str],
    *,
    require_boolean: bool = False,
    lookup: Any = None,
    pipeline_steps: list[Any] | None = None,
    upstream_fields: dict[str, str] | None = None,
    declared_params: set[str] | None = None,
) -> None:
    if not isinstance(expression, str) or not expression.strip():
        return
    lookup_rules = common.get("lookupOperators") if isinstance(common.get("lookupOperators"), dict) else {}
    allowed = set(lookup_rules.keys())
    unsupported = set(common.get("unsupportedLookupOperators") or [])
    tokens, token_errors = tokenize_expression(expression)
    for error in token_errors:
        errors.append(f"{context} has invalid expression syntax: {error}.")
    if token_errors:
        return

    calls, call_errors = expression_function_calls(tokens)
    for error in call_errors:
        errors.append(f"{context} has invalid expression syntax: {error}.")

    expression_ops: set[str] = set()
    for function_name, _ident_idx, open_idx in calls:
        expression_ops.add(function_name)
        if function_name in unsupported:
            errors.append(f"{context} uses unsupported expression function `{function_name}`.")
            continue
        if function_name not in allowed:
            errors.append(f"{context} uses unknown expression function `{function_name}`.")
            continue
        actual, error = expression_call_arg_count(tokens, open_idx)
        if error:
            errors.append(f"{context} has invalid expression syntax: {error}.")
        elif actual is not None and isinstance(lookup_rules.get(function_name), dict):
            validate_expression_arity(function_name, lookup_rules[function_name].get("arity"), actual, context, errors)

    for token_type, value, pos in tokens:
        if token_type == "OP" and value in EXPRESSION_BINARY_OPERATORS:
            expression_ops.add(EXPRESSION_OPERATOR_ALIASES.get(value, value))
        if token_type == "VARIABLE" and declared_params and value not in declared_params:
            errors.append(f"{context} references undeclared workflow parameter `{value}`.")
        if token_type == "FIELD" and upstream_fields is not None:
            if canonical_column_name(value) not in upstream_fields:
                errors.append(f"{context} references field `{value}`, but that column was not found upstream.")

    if require_boolean and expression_ops and not (expression_ops & {"eq", "neq", "gt", "gte", "lt", "lte", "and", "or", "not_true", "is_null", "not_null", "is_empty", "regex_match", "contains", "in", "like", "nlike"}):
        errors.append(f"{context} expression should return boolean for this component context.")

    lookup_ops = lookup_operator_set(lookup)
    transforms = pipeline_transform_set(pipeline_steps or [])
    for operator in expression_ops:
        if operator in EXPRESSION_OPERATOR_ALIASES.values():
            continue
        equivalents = {operator} | EXPRESSION_PIPELINE_EQUIVALENTS.get(operator, set())
        if lookup_ops and operator not in lookup_ops:
            errors.append(f"{context} expression uses `{operator}`, but lookup does not contain matching operator `{operator}`.")
        if transforms and not (equivalents & transforms):
            errors.append(f"{context} expression uses `{operator}`, but pipeline steps do not contain a matching transform.")


def validate_arg_type(
    arg: Any,
    rule: dict[str, Any],
    context: str,
    errors: list[str],
) -> None:
    if not isinstance(arg, dict):
        return
    actual = arg.get("type")
    allowed: list[Any] = []
    if "argTypes" in rule and isinstance(rule["argTypes"], list):
        allowed = rule["argTypes"]
    elif "argType" in rule:
        allowed = [rule.get("argType")]
    if allowed and actual not in allowed:
        rendered = ", ".join("null" if value is None else f"`{value}`" for value in allowed)
        errors.append(f"{context} has arg type `{actual}`; expected {rendered}.")


def validate_registry_capabilities(
    workflow: dict[str, Any],
    node: dict[str, Any],
    registry: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    node_type = node.get("type")
    node_name = node_label(node)
    index = registry.get("index") if isinstance(registry.get("index"), dict) else {}
    components = registry.get("components") if isinstance(registry.get("components"), dict) else {}
    legacy_aliases = index.get("legacyAliases") if isinstance(index.get("legacyAliases"), dict) else {}
    unsupported_types = set(index.get("unsupportedNodeTypes") or [])

    if not isinstance(node_type, str):
        return
    if node_type in legacy_aliases:
        errors.append(f"Node `{node_name}` uses legacy type `{node_type}`. Use `{legacy_aliases[node_type]}` instead.")
        return
    if node_type in unsupported_types:
        errors.append(f"Node `{node_name}` uses unsupported type `{node_type}`.")
        return
    component = components.get(node_type)
    if not isinstance(component, dict):
        errors.append(f"Node `{node_name}` uses type `{node_type}`, which is not in the shared component registry.")
        return

    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    context = f"Node `{node_name}`"
    validate_config_schema(config, component.get("configSchema"), context, errors, warnings)
    mode_required = component.get("modeRequiredConfig")
    if isinstance(mode_required, dict):
        mode_value = config.get("mode")
        required_for_mode = mode_required.get(mode_value)
        if required_for_mode:
            validate_required_params(config, required_for_mode, f"{context} mode `{mode_value}`", errors)

    mode = config.get("mode")
    if isinstance(mode, str) and isinstance(component.get("modes"), list) and mode not in component["modes"]:
        allowed = ", ".join(f"`{value}`" for value in component["modes"])
        errors.append(f"Node `{node_name}` has unsupported mode `{mode}` for `{node_type}`. Use one of: {allowed}.")

    if node_type in {"source", "destination"}:
        connector_type = config.get("connector") or config.get("type")
        # Connector validity is NOT validated against a static allowlist. Savant has 300+
        # connectors and each workspace has a different set; a hard-coded list is always
        # incomplete and only ever produces false positives or false confidence. A source's
        # real validity is established dynamically at creation time: its `config.id` must
        # resolve to an actual dataset in the target workspace (see dataset-substrate.md
        # and the Creator dataset gate). The connector string is descriptive metadata; the
        # dataset id is the binding. Only the structural checks below are enforced here.
        if node_type == "destination" and isinstance(connector_type, str):
            if connector_type.lower() == "csv":
                validate_csv_destination_config(config, context, errors)
            elif isinstance(config.get("fileSystemConfig"), dict):
                validate_file_system_destination_config(config, context, errors)

    common = registry.get("common") if isinstance(registry.get("common"), dict) else {}
    lookup_ops = set((common.get("lookupOperators") or {}).keys())
    unsupported_lookup_ops = set(common.get("unsupportedLookupOperators") or [])
    edit_component = components.get("edit") if isinstance(components.get("edit"), dict) else {}
    transforms = edit_component.get("pipelineTransforms") if isinstance(edit_component.get("pipelineTransforms"), dict) else {}
    unsupported_transforms = set(edit_component.get("unsupportedPipelineTransforms") or [])
    declared_params = workflow_parameter_names(workflow)

    if node_type == "edit":
        for edit_idx, edit in enumerate(as_list(config.get("edits"))):
            if not isinstance(edit, dict):
                continue
            edit_mode = edit.get("mode")
            context = f"Transform `{node_name}` edit {edit_idx}"
            if edit_mode not in component.get("modes", []):
                errors.append(f"{context} has unsupported mode `{edit_mode}`.")
                continue
            if edit_mode in {"expression", "copilot"}:
                # Expression-mode edits carry the EXPRESSION truth field only. The runtime compiles
                # it to a pipeline server-side when none is present (EditConfig / Edit.scala
                # `compileExpressionPipeline`) and the FE re-derives the display caches — the skill
                # no longer hand-builds `pipeline`/`lookup`, so there is nothing to cross-check.
                # Validate the expression itself (grammar authority: `savant-common/expr`).
                if not isinstance(edit.get("expression"), str) or not edit.get("expression").strip():
                    errors.append(f"{context} (mode `{edit_mode}`) is missing the `expression` truth field.")
                if not isinstance(edit.get("tgtCol"), dict) or not (
                    edit["tgtCol"].get("name") or edit["tgtCol"].get("id")
                ):
                    errors.append(f"{context} is missing a `tgtCol` with a `name` or `id`.")
                validate_expression_text(
                    edit.get("expression"),
                    common,
                    context,
                    errors,
                    declared_params=declared_params,
                )
            elif edit_mode == "builder":
                calc = edit.get("calc") if isinstance(edit.get("calc"), dict) else {}
                calc_name = calc.get("calc")
                calcs = component.get("builderCalcs") if isinstance(component.get("builderCalcs"), dict) else {}
                rule = calcs.get(calc_name)
                if not isinstance(calc_name, str) or not isinstance(rule, dict):
                    errors.append(f"{context} uses unsupported builder calc `{calc_name}`.")
                else:
                    params = calc.get("params") if isinstance(calc.get("params"), dict) else {}
                    validate_required_params(params, rule.get("requiredParams"), f"{context} `{calc_name}`", errors)
                    validate_enum_params(params, rule, f"{context} `{calc_name}`", errors)
                    validate_arg_type(calc.get("arg"), rule, f"{context} `{calc_name}`", errors)
                    if rule.get("orderSensitive") and not as_list(calc.get("sorts")):
                        warnings.append(f"{context} `{calc_name}` is order-sensitive but has no deterministic sort.")

    if node_type == "adapter":
        validate_adapter_specs(config, component, f"Adapter `{node_name}`", errors)

    if node_type == "format":
        validate_format_steps(config, component, f"Format `{node_name}`", errors)

    if node_type in {"deduplicate", "sample"}:
        validate_sort_pairs(config.get("sorts"), set(component.get("sortDirections") or ["asc", "dsc"]), f"Node `{node_name}`", errors)

    if node_type in {"service", "apiService"}:
        validate_service_config(config, component, f"Service `{node_name}`", errors)

    # Source nodes can be silently absent after import when the bound dataset id is a
    # placeholder/non-resolving value. Missing ids are allowed here for legacy offline
    # fixtures, but placeholder-looking ids are always pre-import blockers.
    if node_type == "source":
        dataset_id = config.get("id")
        if isinstance(dataset_id, str) and looks_placeholder_binding_id(dataset_id):
            warnings.append(
                f"Source node `{node_name}` uses a placeholder dataset id (`{dataset_id}`). Resolve a real "
                f"dataset_id before import; Savant may silently drop or fail to bind placeholder sources."
            )

    # AI nodes are silently dropped on import when their provider does not resolve in the
    # target workspace. See ../substrate/ai-provider-substrate.md.
    # `providerId` presence/non-emptiness is a hard error via each AI component's
    # configSchema.required (gen_ai, vision) and validate_service_config (LLMService).

    if node_type in {"filter", "pdfilter"}:
        # Filter carries a truth field only — wizard clause rows in `filter[]`, or a boolean
        # expression in `rules[0].expression`. The runtime/FE compile it to a pipeline server-side
        # (PLAT-5786); the skill no longer hand-builds `pipeline`/`dataFilterExpr`/`dataFilterLookUp`,
        # so nothing pipeline-shaped is validated here.
        operators = set(component.get("conditionalOperators") or [])
        if config.get("mode") == "expression":
            rules = as_list(config.get("rules"))
            expr = rules[0].get("expression") if rules and isinstance(rules[0], dict) else None
            if not isinstance(expr, str) or not expr.strip():
                errors.append(f"Filter `{node_name}` (expression mode) is missing `rules[0].expression`.")
            validate_expression_text(
                expr, common, f"Filter `{node_name}`", errors,
                require_boolean=True, declared_params=declared_params,
            )
        else:
            for clause in as_list(config.get("filter")):
                if not isinstance(clause, dict):
                    continue
                operator = clause.get("conditionalOperator")
                if isinstance(operator, str) and operator not in operators:
                    errors.append(f"Filter `{node_name}` uses unsupported conditional operator `{operator}`.")

    if node_type == "summarize":
        calcs = component.get("calcs") if isinstance(component.get("calcs"), dict) else {}
        unsupported = set(component.get("unsupportedCalcs") or [])
        # `groupBy` entries must be field DISPLAY-NAME strings, not objects. Savant resolves
        # group keys by name string (e.g. "State Final"); an object `{id,name,dataType}` is
        # rejected at runtime with "Internal system error". Real exports are always strings.
        for gb_idx, gb in enumerate(as_list(config.get("groupBy"))):
            if isinstance(gb, dict):
                suggestion = gb.get("name") or gb.get("id")
                errors.append(
                    f"Summarize `{node_name}` groupBy {gb_idx} is an object; it must be the field "
                    f"display-name string (e.g. \"{suggestion}\"). Object group keys fail at runtime."
                )
        for agg_idx, agg in enumerate(as_list(config.get("aggs"))):
            if not isinstance(agg, dict):
                continue
            calc_name = agg.get("calc")
            if calc_name in unsupported or calc_name not in calcs:
                errors.append(f"Summarize `{node_name}` aggregation {agg_idx} uses unsupported calc `{calc_name}`.")
                continue
            # `arg.selectedField` must be a field DISPLAY-NAME string, not an object. Same
            # name-resolution rule as groupBy; an object selectedField fails at runtime.
            arg = agg.get("arg")
            if isinstance(arg, dict) and arg.get("type") == "field" and isinstance(arg.get("selectedField"), dict):
                sf = arg.get("selectedField")
                suggestion = sf.get("name") or sf.get("id")
                errors.append(
                    f"Summarize `{node_name}` aggregation {agg_idx} (`{calc_name}`) has an object "
                    f"`arg.selectedField`; it must be the field display-name string (e.g. \"{suggestion}\"). "
                    f"Object field references fail at runtime."
                )
            validate_arg_type(agg.get("arg"), calcs[calc_name], f"Summarize `{node_name}` aggregation `{calc_name}`", errors)
            # A valid aggregation argument is Row (COUNT only) or a NON-GROUPED column: the app's
            # Argument picker offers exactly `Row` + columns not in Group by. A config whose
            # argument is also a group-by field executes (the engine does not enforce the rule)
            # but is undisplayable — the settings panel renders a blank Argument AND a blank
            # group-by slot, and Apply saves that blank state, destroying the config. Seen in
            # Alteryx conversions, where `Count` is anchored to a group-by field; field-COUNT
            # also skips blanks, silently undercounting groups whose key is blank. Warning, not
            # error, so editing a legacy flow that already carries the defect is not blocked.
            group_by_names = {gb for gb in as_list(config.get("groupBy")) if isinstance(gb, str)}
            if (isinstance(arg, dict) and arg.get("type") == "field"
                    and isinstance(arg.get("selectedField"), str)
                    and arg.get("selectedField") in group_by_names):
                fix = ("use the Row argument for a per-group row count"
                       if calc_name == "COUNT" else "aggregate a non-grouped column")
                warnings.append(
                    f"Summarize `{node_name}` aggregation {agg_idx} (`{calc_name}`) argument "
                    f"`{arg.get('selectedField')}` is also a group-by field. The app cannot display "
                    f"this config (blank Argument and group-by pickers; Apply destroys it), and "
                    f"COUNT of a field skips blank values. Likely a literal Alteryx `Count` "
                    f"translation — {fix}."
                )

    if node_type == "pdsummarize":
        calcs = component.get("calcs") if isinstance(component.get("calcs"), dict) else {}
        for agg_idx, agg in enumerate(as_list(config.get("aggs"))):
            if not isinstance(agg, dict):
                continue
            calc_name = agg.get("calc")
            if calc_name not in calcs:
                errors.append(f"Summarize Pushdown `{node_name}` aggregation {agg_idx} uses unsupported calc `{calc_name}`.")

    if node_type == "rollup":
        periodicity = config.get("periodicity")
        if isinstance(periodicity, str) and periodicity not in set(component.get("periodicity") or []):
            errors.append(f"Time Series `{node_name}` uses unsupported periodicity `{periodicity}`.")
        calcs = component.get("calcs") if isinstance(component.get("calcs"), dict) else {}
        unsupported = set(component.get("unsupportedCalcs") or [])
        for agg_idx, agg in enumerate(as_list(config.get("aggs"))):
            if not isinstance(agg, dict):
                continue
            calc_name = agg.get("calc")
            if calc_name in unsupported or calc_name not in calcs:
                errors.append(f"Time Series `{node_name}` aggregation {agg_idx} uses unsupported calc `{calc_name}`.")
                continue
            if "params" in agg:
                warnings.append(f"Time Series `{node_name}` aggregation `{calc_name}` includes ignored `params`; remove them.")
            validate_arg_type(agg.get("arg"), calcs[calc_name], f"Time Series `{node_name}` aggregation `{calc_name}`", errors)

    if node_type == "pivot":
        agg = config.get("aggregation") if isinstance(config.get("aggregation"), dict) else {}
        calc = agg.get("calc")
        allowed = set(component.get("aggregationCalcs") or [])
        if isinstance(calc, str) and allowed and calc not in allowed:
            errors.append(f"Pivot `{node_name}` uses unsupported aggregation calc `{calc}`.")

    if node_type == "blend":
        allowed_regions = set(component.get("regions") or [])
        regions = config.get("regions")
        if isinstance(regions, str):
            regions = [regions]
        for region in as_list(regions):
            if isinstance(region, str) and allowed_regions and region not in allowed_regions:
                errors.append(f"Blend `{node_name}` uses unsupported retained region `{region}`.")
            if region == "T1_U_T2":
                errors.append(
                    f"Blend `{node_name}` uses legacy retained region `T1_U_T2`; use explicit full-outer "
                    "`regions: [\"T1_N_T2\", \"T1\", \"T2\"]`. The legacy shortcut has produced live "
                    "Blend runtime failures after import."
                )
        allowed_joiners = set(component.get("joiners") or [])
        for key in ("joiner", "joinOperator"):
            joiner = config.get(key)
            if isinstance(joiner, str) and allowed_joiners and joiner not in allowed_joiners:
                errors.append(f"Blend `{node_name}` uses unsupported `{key}` value `{joiner}`.")
        # Join keys `on[].lhs`/`rhs` must be the field DISPLAY NAME (e.g. "Sales ZIP Key"),
        # with the internal id living in `lhsMetadata.id`/`rhsMetadata.id`. Putting the id in
        # lhs/rhs fails at runtime with "Internal system error" (real exports always use names).
        # Only flag when the value equals the metadata id AND differs from the metadata name,
        # so a column whose name already equals its id is not falsely flagged.
        for cond_idx, cond in enumerate(as_list(config.get("on"))):
            if not isinstance(cond, dict):
                continue
            for side, meta_key in (("lhs", "lhsMetadata"), ("rhs", "rhsMetadata")):
                value = cond.get(side)
                meta = cond.get(meta_key) if isinstance(cond.get(meta_key), dict) else {}
                mid, mname = meta.get("id"), meta.get("name")
                if isinstance(value, str) and mid and mname and value == mid and value != mname:
                    errors.append(
                        f"Blend `{node_name}` join condition {cond_idx} `{side}` uses the field id "
                        f"`{value}`; it must be the display name \"{mname}\" (the id stays in `{meta_key}.id`). "
                        f"Id-valued join keys fail at runtime."
                    )

    if node_type in {"json", "split", "xml", "deduplicate", "unpivot"}:
        modes = set(component.get("modes") or [])
        if isinstance(mode, str) and modes and mode not in modes:
            errors.append(f"Node `{node_name}` uses unsupported `{node_type}` mode `{mode}`.")

    if node_type == "sample":
        strategy = config.get("strategy")
        allowed = set(component.get("strategies") or [])
        if isinstance(strategy, str) and allowed and strategy not in allowed:
            errors.append(f"Sample `{node_name}` uses unsupported strategy `{strategy}`.")

    if node_type == "multi_stack":
        for key in ("fieldsToInclude", "matchRule"):
            allowed = set(component.get(key) or [])
            value = config.get(key)
            if isinstance(value, str) and allowed and value not in allowed:
                errors.append(f"Stack `{node_name}` uses unsupported `{key}` value `{value}`.")
        inlets = [inlet for inlet in as_list(node.get("inlets")) if isinstance(inlet, dict)]
        sources = as_list(inlets[0].get("sources")) if inlets else []
        uses_single_source_inlet = bool(inlets and inlets[0].get("source"))
        if (
            len(inlets) != 1
            or inlets[0].get("id") != "in_0"
            or inlets[0].get("type") != "multisource"
            or uses_single_source_inlet
            or len([source for source in sources if isinstance(source, dict) and source.get("source")]) < 2
        ):
            errors.append(
                f"Stack `{node_name}` must use one `multisource` inlet `in_0` with all upstream inputs in "
                "`inlets[0].sources[]`. Separate Stack inlets such as `in_0`/`in_1` can look structurally "
                "connected in JSON, but Savant's canvas only renders the canonical multi-source inlet."
            )

    if node_type == "text":
        # A text node with no `backgroundColor` renders a grey header band in Savant
        # (real exports always set it; group headers use "transparent"). This is a
        # presentation defect, not a load failure, so warn rather than error.
        if isinstance(config, dict) and "backgroundColor" not in config:
            warnings.append(
                f"Text `{node_name}` has no `backgroundColor`; Savant renders a grey header band. "
                f"Set `backgroundColor: \"transparent\"` (the standard for group headers)."
            )


def walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def unsupported_expression_tokens(registry: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    common = registry.get("common") if isinstance(registry.get("common"), dict) else {}
    tokens.update(str(value).lower() for value in common.get("unsupportedLookupOperators") or [])
    components = registry.get("components") if isinstance(registry.get("components"), dict) else {}
    edit_component = components.get("edit") if isinstance(components.get("edit"), dict) else {}
    tokens.update(str(value).lower() for value in edit_component.get("unsupportedPipelineTransforms") or [])
    return {token for token in tokens if token}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def rich_text_plain(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def get_description(node: dict[str, Any]) -> str:
    desc = node.get("description")
    return rich_text_plain(desc)


def get_config_description(node: dict[str, Any]) -> str:
    config = node.get("config")
    if isinstance(config, dict):
        desc = config.get("description")
        return rich_text_plain(desc)
    return ""


def description_search_text(node: dict[str, Any]) -> str:
    return rich_text_plain(node.get("description")).casefold()


def compact_search_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def description_mentions(desc: str, term: Any) -> bool:
    if not isinstance(term, str) or not term.strip():
        return True
    needle = term.strip().casefold()
    if needle in desc:
        return True
    compact_desc = compact_search_text(desc)
    compact_needle = compact_search_text(needle)
    return bool(compact_needle and compact_needle in compact_desc)


def missing_description_terms(node: dict[str, Any], terms: list[str], *, limit: int = 6) -> list[str]:
    desc = description_search_text(node)
    missing: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            continue
        key = compact_search_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        if not description_mentions(desc, term):
            missing.append(term)
            if len(missing) >= limit:
                break
    return missing


def field_names_from_keys(keys: set[str], fields: dict[str, str] | None = None) -> list[str]:
    fields = fields or {}
    names: list[str] = []
    seen: set[str] = set()
    for key in sorted(keys):
        name = fields.get(key) or key
        text = str(name)
        marker = compact_search_text(text)
        if marker and marker not in seen:
            names.append(text)
            seen.add(marker)
    return names


def edit_added_field_names(node: dict[str, Any]) -> list[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    names: list[str] = []
    for edit in as_list(config.get("edits")):
        if not isinstance(edit, dict) or edit.get("action") != "add_col":
            continue
        tgt_col = edit.get("tgtCol") if isinstance(edit.get("tgtCol"), dict) else {}
        name = tgt_col.get("name") or tgt_col.get("id")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def edit_replace_field_names(node: dict[str, Any]) -> list[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    names: list[str] = []
    for edit in as_list(config.get("edits")):
        if not isinstance(edit, dict) or edit.get("action") != "replace":
            continue
        tgt_col = edit.get("tgtCol") if isinstance(edit.get("tgtCol"), dict) else {}
        for candidate in (edit.get("replaceTgt"), tgt_col.get("name"), tgt_col.get("id")):
            if isinstance(candidate, str) and candidate.strip():
                names.append(candidate.strip())
                break
    return names


def summarize_group_names(node: dict[str, Any]) -> list[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return [value.strip() for value in as_list(config.get("groupBy")) if isinstance(value, str) and value.strip()]


def summarize_measure_names(node: dict[str, Any]) -> list[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    names: list[str] = []
    for agg in as_list(config.get("aggs")):
        if not isinstance(agg, dict):
            continue
        tgt_col = agg.get("tgt_col") if isinstance(agg.get("tgt_col"), dict) else {}
        name = tgt_col.get("name") or tgt_col.get("id")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def blend_join_key_names(node: dict[str, Any]) -> list[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    names: list[str] = []
    for condition in as_list(config.get("on")):
        if not isinstance(condition, dict):
            continue
        for side in ("lhs", "rhs"):
            name = blend_join_side_name(condition, side)
            if name:
                names.append(name)
    return names


def validate_node_description_fidelity(
    node: dict[str, Any],
    upstream_fields: dict[str, str],
    issues: list[str],
) -> None:
    """Deterministic minimum coverage for node-specific configuration readouts.

    This does not judge prose quality. It only checks that the description names the
    material settings a reviewer would need to trace: created columns, predicate
    fields, join keys, group/measure columns, and output identity.
    """
    node_type = node.get("type")
    if node_type not in DESCRIBED_NODE_TYPES:
        return
    desc = description_search_text(node)
    if len(desc) < MIN_NODE_DESCRIPTION_CHARS:
        return
    label = node_label(node)
    if node_type == "edit":
        added = edit_added_field_names(node)
        missing_added = missing_description_terms(node, added)
        if missing_added:
            issues.append(
                f"Transform `{label}` description does not mention calculated/new column(s) "
                f"{', '.join(f'`{name}`' for name in missing_added)}. Step descriptions should read out "
                "the actual Transform config, including formulas for calculated fields."
            )
        replaced = edit_replace_field_names(node)
        missing_replaced = missing_description_terms(node, replaced, limit=4)
        if missing_replaced:
            issues.append(
                f"Transform `{label}` description does not mention renamed/retyped/replaced column(s) "
                f"{', '.join(f'`{name}`' for name in missing_replaced)}."
            )
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        hidden = field_names_from_keys(field_control_keys(config.get("hiddenFields")), upstream_fields)
        if hidden and not any(word in desc for word in ("hide", "hidden", "suppress", "exclude", "remove")):
            issues.append(
                f"Transform `{label}` hides column(s) such as `{hidden[0]}`, but the description does not say "
                "columns are hidden or excluded."
            )
        ordered = field_names_from_keys(field_control_keys(config.get("orderedFields")), upstream_fields)
        if ordered and not any(word in desc for word in ("order", "reorder", "arrange", "sequence", "first", "before")):
            issues.append(
                f"Transform `{label}` sets output column order, but the description does not mention ordering."
            )
    elif node_type in {"filter", "pdfilter"}:
        fields = field_names_from_keys(filter_predicate_field_keys(node), upstream_fields)
        missing = missing_description_terms(node, fields)
        if missing:
            issues.append(
                f"Filter `{label}` description does not mention predicate field(s) "
                f"{', '.join(f'`{name}`' for name in missing)}."
            )
    elif node_type == "blend":
        keys = blend_join_key_names(node)
        missing = missing_description_terms(node, keys)
        if missing:
            issues.append(
                f"Blend `{label}` description does not mention join key(s) "
                f"{', '.join(f'`{name}`' for name in missing)}."
            )
    elif node_type in {"summarize", "pdsummarize", "rollup"}:
        groups = summarize_group_names(node)
        measures = summarize_measure_names(node)
        missing_groups = missing_description_terms(node, groups)
        missing_measures = missing_description_terms(node, measures)
        if missing_groups:
            issues.append(
                f"Summarize `{label}` description does not mention group-by field(s) "
                f"{', '.join(f'`{name}`' for name in missing_groups)}."
            )
        if missing_measures:
            issues.append(
                f"Summarize `{label}` description does not mention output measure(s) "
                f"{', '.join(f'`{name}`' for name in missing_measures)}."
            )
    elif node_type == "destination":
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        terms = [
            value for value in (
                node.get("name"),
                config.get("fileName"),
                config.get("connector"),
                config.get("type"),
            )
            if isinstance(value, str) and value.strip()
        ]
        if terms and not any(description_mentions(desc, term) for term in terms):
            issues.append(
                f"Destination `{label}` description does not mention the output name, file, or destination type."
            )


def text_plain(node: dict[str, Any]) -> str:
    config = node.get("config")
    if not isinstance(config, dict):
        return ""
    value = config.get("inputText")
    return value.strip() if isinstance(value, str) else ""


def text_rendered_plain(node: dict[str, Any]) -> str:
    config = node.get("config")
    if not isinstance(config, dict):
        return ""
    value = config.get("text")
    return rich_text_plain(value)


def is_group_child(node: dict[str, Any]) -> bool:
    canvas_config = node.get("canvasConfig")
    return isinstance(canvas_config, dict) and isinstance(canvas_config.get("parentId"), str) and bool(canvas_config.get("parentId"))


def number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def node_label(node: dict[str, Any]) -> str:
    return str(node.get("name") or node.get("id") or "<unnamed>")


def node_requires_upstream_input(node: dict[str, Any]) -> bool:
    return node.get("type") in PROCESSING_TYPES


def normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def is_normalize_node(node: dict[str, Any]) -> bool:
    return node.get("type") == "edit" and "normalize" in normalized_text(node.get("name"))


def is_standardizing_node(node: dict[str, Any]) -> bool:
    """The standardization layer a source is expected to feed first.

    Per `data-prep-normalization.md`, every source is created as a `Source -> Adapter` unit, where
    the Adapter is the schema contract (canonical names + types + `mappedFrom`) that insulates
    downstream logic from source changes — this is also what `node_builders.standardized_source`
    emits. A `Normalize ...` Transform fed directly from the source is the alternative shape. Either
    one means the source was standardized before downstream logic, so both satisfy the
    "standardize at the source" check. (The Adapter was previously not recognized here, which
    warned on the documented convention — see the standard's "Source standardization" section.)"""
    return node.get("type") == "adapter" or is_normalize_node(node)


def is_source_requiring_profile(node: dict[str, Any], registry: dict[str, Any] | None = None) -> bool:
    if node.get("type") != "source":
        return False
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    connector = normalized_text(config.get("connector") or config.get("type"))
    components = registry.get("components") if registry and isinstance(registry.get("components"), dict) else {}
    source_component = components.get("source") if isinstance(components.get("source"), dict) else {}
    profile_connectors = set(source_component.get("profileEvidenceConnectorTypes") or [])
    return connector in profile_connectors


def has_profile_evidence(workflow: dict[str, Any], node: dict[str, Any]) -> bool:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    if has_inline_source_profile_evidence(node):
        return True
    source_id = config.get("id")
    if isinstance(source_id, str) and source_id:
        for candidate in as_list(workflow.get("nodes")):
            if not isinstance(candidate, dict) or candidate is node or candidate.get("type") != "source":
                continue
            candidate_config = candidate.get("config") if isinstance(candidate.get("config"), dict) else {}
            if candidate_config.get("id") == source_id and has_inline_source_profile_evidence(candidate):
                return True
    for key in PROFILE_EVIDENCE_KEYS | {"rowCount", "fieldIds", "fields", "profiledFields", "schema"}:
        if config.get(key):
            return True
    node_keys = {
        str(node.get("id") or ""),
        str(node.get("name") or ""),
        str(config.get("id") or ""),
        str(config.get("name") or ""),
    }
    node_keys = {key for key in node_keys if key}
    for key in PROFILE_EVIDENCE_KEYS:
        value = workflow.get(key)
        if not value:
            continue
        if isinstance(value, dict):
            if any(value.get(node_key) for node_key in node_keys):
                return True
            sources = value.get("sources")
            if isinstance(sources, dict) and any(sources.get(node_key) for node_key in node_keys):
                return True
            if isinstance(sources, list):
                for item in sources:
                    if not isinstance(item, dict):
                        continue
                    item_keys = {
                        str(item.get("id") or ""),
                        str(item.get("name") or ""),
                        str(item.get("sourceId") or ""),
                        str(item.get("sourceName") or ""),
                    }
                    if node_keys & item_keys:
                        return True
        elif isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                item_keys = {
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    str(item.get("sourceId") or ""),
                    str(item.get("sourceName") or ""),
                }
                if node_keys & item_keys:
                    return True
    return False


def is_fragile_field_ref(value: str) -> bool:
    if "\n" in value or "\r" in value:
        return True
    if value != value.strip():
        return True
    if re.search(r"_[0-9]+$", value):
        return True
    if re.search(r"^Unnamed[:_ ]", value, re.IGNORECASE):
        return True
    return False


def collect_field_refs(value: Any, parent_key: str = "") -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FIELD_REF_KEYS:
                if isinstance(child, str):
                    refs.append(child)
                elif isinstance(child, list):
                    refs.extend(item for item in child if isinstance(item, str))
            refs.extend(collect_field_refs(child, key))
    elif isinstance(value, list):
        for child in value:
            refs.extend(collect_field_refs(child, parent_key))
    return refs


def collect_transient_output_fields(value: Any) -> set[str]:
    transients: set[str] = set()
    if isinstance(value, dict):
        tgt_col = value.get("tgt_col")
        if isinstance(tgt_col, dict):
            for candidate in (tgt_col.get("id"), tgt_col.get("name")):
                if isinstance(candidate, str) and candidate.startswith("__transient_"):
                    transients.add(candidate)
        for child in value.values():
            transients.update(collect_transient_output_fields(child))
    elif isinstance(value, list):
        for child in value:
            transients.update(collect_transient_output_fields(child))
    return transients


def validate_known_field_refs(
    value: Any,
    available_fields: dict[str, str],
    context: str,
    errors: list[str],
) -> None:
    """Validate explicit lookup/pipeline field refs against fields available at this point.

    Expression text itself is parsed by `validate_expression_text`; this catches the
    adjacent case where lookup or pipeline JSON references a field that is absent from the
    attached/profiled source schema or from earlier ordered Transform edits.
    """
    if not available_fields:
        return
    transients = collect_transient_output_fields(value)
    for ref in sorted(set(collect_field_refs(value))):
        if not isinstance(ref, str) or not ref.strip():
            continue
        if ref.startswith("__transient_") or ref.startswith("__src_col_") or ref in transients:
            continue
        if canonical_column_name(ref) not in available_fields:
            errors.append(f"{context} references field `{ref}`, but that column was not found upstream.")


def validate_known_input_field_refs(
    node: dict[str, Any],
    upstream_fields: dict[str, str],
    errors: list[str],
) -> None:
    """Validate explicit lookup/pipeline field refs against known upstream schema."""
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    validate_known_field_refs(config, upstream_fields, f"Node `{node_label(node)}`", errors)


def canonical_column_name(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def field_identity(field: Any) -> tuple[str, str] | None:
    if not isinstance(field, dict):
        return None
    name = field.get("name")
    field_id = field.get("id")
    if not isinstance(name, str) and isinstance(field_id, str):
        name = field_id
    if not isinstance(field_id, str) and isinstance(name, str):
        field_id = name
    if not isinstance(name, str) or not name.strip():
        return None
    return field_id or name, name


def add_output_field(fields: dict[str, str], field_id: Any, name: Any = None) -> None:
    if not isinstance(name, str) or not name.strip():
        name = field_id
    if not isinstance(field_id, str) or not field_id.strip():
        field_id = name
    if not isinstance(name, str) or not name.strip():
        return
    fields[canonical_column_name(name)] = name
    derived_name_id = derive_id(name)
    if derived_name_id:
        fields[canonical_column_name(derived_name_id)] = name
    if isinstance(field_id, str) and field_id.strip():
        fields[canonical_column_name(field_id)] = name


def remove_output_field(fields: dict[str, str], field_id: Any) -> None:
    key = canonical_column_name(field_id)
    if not key:
        return
    display = fields.get(key)
    fields.pop(key, None)
    if display:
        display_key = canonical_column_name(display)
        for existing_key, existing_display in list(fields.items()):
            if existing_key == display_key or existing_display == display:
                fields.pop(existing_key, None)


def field_control_keys(values: Any) -> set[str]:
    keys: set[str] = set()
    for value in as_list(values):
        if isinstance(value, str):
            key = canonical_column_name(value)
            if key:
                keys.add(key)
            continue
        identity = field_identity(value)
        if identity:
            field_id, name = identity
            for candidate in (field_id, name):
                key = canonical_column_name(candidate)
                if key:
                    keys.add(key)
    return keys


def expression_field_ref_keys(expression: Any) -> set[str]:
    if not isinstance(expression, str) or not expression.strip():
        return set()
    tokens, _errors = tokenize_expression(expression)
    return {
        canonical_column_name(value)
        for token_type, value, _pos in tokens
        if token_type == "FIELD" and canonical_column_name(value)
    }


def edit_tgt_field_keys(edit: dict[str, Any]) -> set[str]:
    tgt_col = edit.get("tgtCol") if isinstance(edit.get("tgtCol"), dict) else {}
    identity = field_identity(tgt_col)
    if not identity:
        return set()
    fields: dict[str, str] = {}
    add_output_field(fields, identity[0], identity[1])
    return set(fields)


def edit_node_created_field_keys(node: dict[str, Any]) -> set[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    keys: set[str] = set()
    for edit in as_list(config.get("edits")):
        if isinstance(edit, dict):
            keys.update(edit_tgt_field_keys(edit))
    return keys


def edit_node_read_field_keys(node: dict[str, Any]) -> set[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    keys: set[str] = set()
    for edit in as_list(config.get("edits")):
        if not isinstance(edit, dict):
            continue
        transients = collect_transient_output_fields(edit)
        target_keys = edit_tgt_field_keys(edit)
        for ref in collect_field_refs(edit):
            ref_key = canonical_column_name(ref)
            if not ref_key:
                continue
            if ref.startswith("__transient_") or ref.startswith("__src_col_") or ref in transients:
                continue
            if ref_key in target_keys:
                continue
            keys.add(ref_key)
        keys.update(expression_field_ref_keys(edit.get("expression")) - target_keys)
    return keys


def edit_node_shape_field_keys(node: dict[str, Any]) -> set[str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    return field_control_keys(as_list(config.get("orderedFields")) + as_list(config.get("hiddenFields")))


def filter_predicate_field_keys(node: dict[str, Any]) -> set[str]:
    """Field keys a Filter/PDF Filter uses to decide whether a row survives."""
    if node.get("type") not in {"filter", "pdfilter"}:
        return set()
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    keys = field_control_keys(collect_field_refs(config))
    for clause in as_list(config.get("filter")):
        if not isinstance(clause, dict):
            continue
        for candidate in (clause.get("id"), clause.get("name")):
            key = canonical_column_name(candidate)
            if key:
                keys.add(key)
    keys.update(expression_field_ref_keys(config.get("dataFilterExpr")))
    return {key for key in keys if key}


def blend_join_side_name(condition: dict[str, Any], side: str) -> str:
    meta_key = "lhsMetadata" if side == "lhs" else "rhsMetadata"
    value = condition.get(side)
    meta = condition.get(meta_key) if isinstance(condition.get(meta_key), dict) else {}
    if not isinstance(value, str) or not value.strip():
        value = meta.get("name")
    return value.strip() if isinstance(value, str) else ""


NORMALIZED_JOIN_KEY_RE = re.compile(
    r"\b("
    r"normalized|normalised|canonical|clean|cleaned|trim|trimmed|standardized|standardised|"
    r"join\s*key|match\s*key|key|digits?|numeric|text|padded|unpadded|stripped|derived"
    r")\b",
    re.IGNORECASE,
)


def blend_join_side_type(condition: dict[str, Any], side: str) -> str:
    meta_key = "lhsMetadata" if side == "lhs" else "rhsMetadata"
    meta = condition.get(meta_key) if isinstance(condition.get(meta_key), dict) else {}
    data_type = meta.get("dataType")
    return data_type.strip().casefold() if isinstance(data_type, str) else ""


def blend_join_key_looks_normalized(name: str) -> bool:
    return bool(name and NORMALIZED_JOIN_KEY_RE.search(name))


def validate_blend_join_fields(
    node: dict[str, Any],
    left_fields: dict[str, str],
    right_fields: dict[str, str],
    errors: list[str],
) -> None:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for cond_idx, condition in enumerate(as_list(config.get("on"))):
        if not isinstance(condition, dict):
            continue
        for side, fields, input_name in (
            ("lhs", left_fields, "left"),
            ("rhs", right_fields, "right"),
        ):
            field_name = blend_join_side_name(condition, side)
            if not field_name:
                continue
            if canonical_column_name(field_name) not in fields:
                errors.append(
                    f"Blend `{node_label(node)}` join condition {cond_idx} references {input_name} field "
                    f"`{field_name}`, but that column was not found on the {input_name} input."
                )


def validate_blend_join_key_normalization(
    node: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for cond_idx, condition in enumerate(as_list(config.get("on"))):
        if not isinstance(condition, dict):
            continue
        lhs_name = blend_join_side_name(condition, "lhs")
        rhs_name = blend_join_side_name(condition, "rhs")
        lhs_type = blend_join_side_type(condition, "lhs")
        rhs_type = blend_join_side_type(condition, "rhs")
        if lhs_type and rhs_type and lhs_type != rhs_type:
            errors.append(
                f"Blend `{node_label(node)}` join condition {cond_idx} uses different key types: "
                f"`{lhs_name}` is `{lhs_type}` and `{rhs_name}` is `{rhs_type}`. Join keys must be the same type."
            )
        if lhs_name and rhs_name and not (
            blend_join_key_looks_normalized(lhs_name) and blend_join_key_looks_normalized(rhs_name)
        ):
            warnings.append(
                f"Blend `{node_label(node)}` join condition {cond_idx} joins `{lhs_name}` to `{rhs_name}` "
                "without explicit normalized/derived key field names on both sides. Create normalized keys "
                "for type, whitespace, leading-zero, and prefix/suffix handling, or document that both source "
                "fields are already canonical."
            )


def unique_output_field_names(fields: dict[str, str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for name in fields.values():
        key = canonical_column_name(name)
        if not key or key in seen:
            continue
        names.append(name)
        seen.add(key)
    return names


def rhs_duplicate_id(name: str, suffix: int) -> str:
    return f"{name}_{suffix}" if isinstance(name, str) and name.strip() else f"field_{suffix}"


def rhs_duplicate_name(name: str, suffix: int) -> str:
    if suffix == 2:
        return f"{name} (rhs)"
    return f"{name} (rhs {suffix - 1})"


def blend_is_inner_main_output(config: dict[str, Any]) -> bool:
    regions = config.get("regions")
    if isinstance(regions, str):
        regions = [regions]
    return {region for region in as_list(regions) if isinstance(region, str)} == {"T1_N_T2"}


def blend_rhs_join_key_names(config: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for condition in as_list(config.get("on")):
        if not isinstance(condition, dict):
            continue
        rhs = condition.get("rhs")
        meta = condition.get("rhsMetadata") if isinstance(condition.get("rhsMetadata"), dict) else {}
        if not isinstance(rhs, str) or not rhs.strip():
            rhs = meta.get("name")
        key = canonical_column_name(rhs)
        if key:
            keys.add(key)
    return keys


def blend_output_fields(
    left_fields: dict[str, str],
    right_fields: dict[str, str],
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Model live Blend output names for the main output path."""
    output_fields: dict[str, str] = {}
    used: set[str] = set()
    for name in unique_output_field_names(left_fields):
        add_output_field(output_fields, name)
        used.add(canonical_column_name(name))

    config = config or {}
    suppress_duplicate_rhs_keys = blend_is_inner_main_output(config)
    rhs_join_keys = blend_rhs_join_key_names(config)
    for name in unique_output_field_names(right_fields):
        output_id = name
        output_name = name
        key = canonical_column_name(name)
        if suppress_duplicate_rhs_keys and key in rhs_join_keys and key in used:
            continue
        if key in used:
            suffix = 2
            while True:
                candidate_id = rhs_duplicate_id(name, suffix)
                candidate_name = rhs_duplicate_name(name, suffix)
                candidate_key = canonical_column_name(candidate_name)
                if candidate_key not in used:
                    output_id = candidate_id
                    output_name = candidate_name
                    key = candidate_key
                    break
                suffix += 1
        add_output_field(output_fields, output_id, output_name)
        if key:
            used.add(key)
    return output_fields


def unpivot_output_fields(upstream_fields: dict[str, str], config: dict[str, Any] | None = None) -> dict[str, str]:
    """Model Unpivot output columns when the upstream schema is known.

    Unlike Pivot, Unpivot's output column names are declared in config: retained identity columns
    plus the configured name/value columns. Row counts and value types are runtime concerns, but
    the column list is deterministic enough for downstream shaping and field-reference checks.
    """
    config = config or {}
    selected_keys = field_control_keys(config.get("selectedFields"))
    mode = config.get("mode") or "unpivot"
    output_fields: dict[str, str] = {}
    for name in unique_output_field_names(upstream_fields):
        name_key = canonical_column_name(name)
        keep = name_key in selected_keys if mode == "keep" else name_key not in selected_keys
        if keep:
            add_output_field(output_fields, name)
    add_output_field(output_fields, config.get("nameField"))
    add_output_field(output_fields, config.get("valueField"))
    return output_fields


def source_nested_config(config: dict[str, Any]) -> dict[str, Any]:
    nested = config.get("config")
    return nested if isinstance(nested, dict) else {}


def source_output_fields(node: dict[str, Any], workflow: dict[str, Any] | None = None) -> dict[str, str]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    fields: dict[str, str] = {}
    for key in ("fields", "profiledFields"):
        for field in as_list(config.get(key)):
            identity = field_identity(field)
            if not identity:
                continue
            field_id, name = identity
            add_output_field(fields, field_id, name)
    if not fields and isinstance(workflow, dict):
        # Builder-emitted JSON keeps the source config at the live-proven bare shape
        # ({id,name,type,connector} — extra keys make import drop the node) and lifts
        # profiling evidence to workflow-level `sourceProfiles` keyed by node id/name.
        profiles = workflow.get("sourceProfiles")
        if isinstance(profiles, dict):
            entry = (
                profiles.get(str(node.get("id") or ""))
                or profiles.get(str(node.get("name") or ""))
                or profiles.get(str(config.get("id") or ""))
            )
            if isinstance(entry, dict):
                for field in as_list(entry.get("fields")):
                    identity = field_identity(field)
                    if identity:
                        add_output_field(fields, identity[0], identity[1])
    for field in as_list(config.get("schema")):
        identity = field_identity(field)
        if not identity:
            continue
        field_id, name = identity
        add_output_field(fields, field_id, name)
    nested = source_nested_config(config)
    for selected in as_list(nested.get("selected")):
        add_output_field(fields, selected)
    return fields


def node_schema_hint(node: dict[str, Any], schema_hints: dict[str, Any] | None) -> list[str] | None:
    """Return author-declared expected output columns for an AI node, or None.

    The hint is keyed by node id or node display name in a validator-only sidecar
    (see `--schema-hints`). It is never read from the workflow JSON itself, so the
    workflow file stays free of non-product keys on every delivery path. An empty or
    malformed hint is treated as "no declaration" so the node falls back to unknown.
    """
    if not isinstance(schema_hints, dict):
        return None
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    candidate_keys = [node.get("id"), node_label(node), config.get("name")]
    for key in candidate_keys:
        if not isinstance(key, str) or not key.strip():
            continue
        columns = schema_hints.get(key)
        if not isinstance(columns, list):
            continue
        cleaned = [column for column in columns if isinstance(column, str) and column.strip()]
        if cleaned:
            return cleaned
    return None


def node_schema_hint_keys(node: dict[str, Any], schema_hints: dict[str, Any] | None) -> list[str]:
    if not isinstance(schema_hints, dict):
        return []
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    keys: list[str] = []
    for key in [node.get("id"), node_label(node), config.get("name")]:
        if not isinstance(key, str) or not key.strip() or key in keys:
            continue
        columns = schema_hints.get(key)
        if isinstance(columns, list) and any(isinstance(column, str) and column.strip() for column in columns):
            keys.append(key)
    return keys


def infer_output_schemas(
    workflow: dict[str, Any],
    schema_hints: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Infer each node's resolved output schema using the validator's column model.

    The returned mapping is keyed by node id. Each value includes node display
    metadata plus `known` and `columns`. `columns` is a display-name list in the
    same schema model used by validation, including Blend duplicate names such as
    `Amount (rhs)`.
    """
    nodes = as_list(workflow.get("nodes"))
    by_id = {node.get("id"): node for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)}
    incoming: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for node in by_id.values():
        node_id = node["id"]
        for inlet in as_list(node.get("inlets")):
            if not isinstance(inlet, dict):
                continue
            for source, _source_outlet in inlet_source_refs(inlet):
                if source in by_id:
                    incoming[node_id].append(source)
                    adjacency[source].append(node_id)

    inferred_fields: dict[str, dict[str, str]] = {}
    inferred_schema_known: dict[str, bool] = {}
    remaining = {node_id: len(incoming.get(node_id, [])) for node_id in by_id}
    field_queue = deque([node_id for node_id, count in remaining.items() if count == 0])
    field_visited: set[str] = set()
    while field_queue:
        node_id = field_queue.popleft()
        if node_id in field_visited:
            continue
        field_visited.add(node_id)
        node = by_id[node_id]
        node_type = node.get("type")
        upstream_fields: dict[str, str] = {}
        upstream_ref_count = 0
        upstream_schema_known = True
        for inlet in as_list(node.get("inlets")):
            if not isinstance(inlet, dict):
                continue
            for source, _ in inlet_source_refs(inlet):
                upstream_ref_count += 1
                upstream_fields.update(inferred_fields.get(source, {}))
                upstream_schema_known = upstream_schema_known and inferred_schema_known.get(source, False)
        if upstream_ref_count == 0:
            upstream_schema_known = False

        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if node_type == "source":
            output_fields = source_output_fields(node, workflow)
            if not output_fields:
                hinted = node_schema_hint(node, schema_hints)
                if hinted:
                    for column in hinted:
                        add_output_field(output_fields, column)
            output_schema_known = bool(output_fields)
        elif node_type == "adapter":
            output_fields = {}
            for spec in as_list(config.get("specs")):
                identity = field_identity(spec)
                if identity:
                    add_output_field(output_fields, identity[0], identity[1])
            output_schema_known = bool(output_fields)
        elif node_type == "edit":
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known
            for edit in as_list(config.get("edits")):
                if not isinstance(edit, dict):
                    continue
                tgt_col = edit.get("tgtCol") if isinstance(edit.get("tgtCol"), dict) else {}
                tgt_name = tgt_col.get("name")
                tgt_id = tgt_col.get("id")
                if not isinstance(tgt_name, str) or not tgt_name.strip():
                    continue
                name_key = canonical_column_name(tgt_name)
                id_key = canonical_column_name(tgt_id)
                if edit.get("action") == "replace":
                    replace_target = edit.get("replaceTgt")
                    replace_keys = []
                    if isinstance(replace_target, str) and replace_target.strip():
                        replace_keys.append(canonical_column_name(replace_target))
                    else:
                        replace_keys.append(name_key)
                        if id_key:
                            replace_keys.append(id_key)
                    for key in replace_keys:
                        remove_output_field(output_fields, key)
                output_fields[name_key] = tgt_name
                if id_key:
                    output_fields[id_key] = tgt_name
            for field_id in as_list(config.get("hiddenFields")):
                remove_output_field(output_fields, field_id)
        elif node_type in {"filter", "pdfilter"}:
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known
        elif node_type == "summarize":
            output_fields = {}
            for group_key in as_list(config.get("groupBy")):
                if isinstance(group_key, str) and group_key.strip():
                    add_output_field(output_fields, group_key)
            for agg in as_list(config.get("aggs")):
                identity = field_identity(agg.get("tgt_col")) if isinstance(agg, dict) else None
                if identity:
                    add_output_field(output_fields, identity[0], identity[1])
            output_schema_known = True
        elif node_type == "rollup":
            output_fields = {}
            for group_key in as_list(config.get("groupBy")):
                if isinstance(group_key, str) and group_key.strip():
                    add_output_field(output_fields, group_key)
            add_output_field(output_fields, "period_name", "Period Name")
            add_output_field(output_fields, "period_offset", "Period Offset")
            for agg in as_list(config.get("aggs")):
                identity = field_identity(agg.get("tgt_col")) if isinstance(agg, dict) else None
                if identity:
                    add_output_field(output_fields, identity[0], identity[1])
            output_schema_known = True
        elif node_type == "blend":
            inlet_fields: dict[str, dict[str, str]] = {}
            inlet_known: dict[str, bool] = {}
            for inlet in as_list(node.get("inlets")):
                if not isinstance(inlet, dict):
                    continue
                inlet_id = inlet.get("id")
                if not isinstance(inlet_id, str):
                    continue
                fields: dict[str, str] = {}
                known = True
                refs = inlet_source_refs(inlet)
                if not refs:
                    known = False
                for source, _ in refs:
                    fields.update(inferred_fields.get(source, {}))
                    known = known and inferred_schema_known.get(source, False)
                inlet_fields[inlet_id] = fields
                inlet_known[inlet_id] = known
            if inlet_known.get("in_0") and inlet_known.get("in_1"):
                output_fields = blend_output_fields(inlet_fields.get("in_0", {}), inlet_fields.get("in_1", {}), config)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type in AI_OPAQUE_OUTPUT_TYPES:
            declared = node_schema_hint(node, schema_hints)
            if declared is not None:
                output_fields = dict(upstream_fields) if upstream_schema_known else {}
                for column in declared:
                    add_output_field(output_fields, column)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type == "pivot":
            declared = node_schema_hint(node, schema_hints)
            if declared is not None:
                output_fields = {}
                for column in declared:
                    add_output_field(output_fields, column)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type == "unpivot":
            if upstream_schema_known:
                output_fields = unpivot_output_fields(upstream_fields, config)
                output_schema_known = bool(output_fields)
            else:
                declared = node_schema_hint(node, schema_hints)
                if declared is not None:
                    output_fields = {}
                    for column in declared:
                        add_output_field(output_fields, column)
                    output_schema_known = True
                else:
                    output_fields = {}
                    output_schema_known = False
        else:
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known

        inferred_fields[node_id] = output_fields
        inferred_schema_known[node_id] = output_schema_known
        for target in adjacency.get(node_id, []):
            remaining[target] = max(0, remaining.get(target, 0) - 1)
            if remaining[target] == 0:
                field_queue.append(target)

    result: dict[str, dict[str, Any]] = {}
    for node_id, node in by_id.items():
        result[node_id] = {
            "id": node_id,
            "name": node_label(node),
            "type": node.get("type"),
            "known": bool(inferred_schema_known.get(node_id, False)),
            "columns": unique_output_field_names(inferred_fields.get(node_id, {})),
        }
    return result


def has_inline_source_profile_evidence(node: dict[str, Any]) -> bool:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    if source_output_fields(node):
        return True
    nested = source_nested_config(config)
    if nested:
        for key in ("fileId", "tabName", "tabNames", "selected"):
            if nested.get(key):
                return True
    return False


def has_business_record_language(node: dict[str, Any]) -> bool:
    # Use the source display name only. Descriptions for reference sources often
    # mention business records they support, but that does not make the reference
    # source itself a transaction/obligation stream that requires a grain filter.
    text = str(node.get("name") or "").lower()
    return any(term in text for term in BUSINESS_RECORD_TERMS)


def absolute_position(node: dict[str, Any], by_id: dict[str, dict[str, Any]], seen: set[str] | None = None) -> tuple[float, float] | None:
    pos = node.get("position")
    if not isinstance(pos, dict) or not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("y"), (int, float)):
        return None
    x = float(pos["x"])
    y = float(pos["y"])
    parent_id = (node.get("canvasConfig") or {}).get("parentId") if isinstance(node.get("canvasConfig"), dict) else None
    if not isinstance(parent_id, str) or not parent_id:
        return x, y
    seen = seen or set()
    node_id = str(node.get("id") or "")
    if node_id in seen:
        return x, y
    parent = by_id.get(parent_id)
    if not parent:
        return x, y
    parent_pos = absolute_position(parent, by_id, seen | {node_id})
    if not parent_pos:
        return x, y
    return parent_pos[0] + x, parent_pos[1] + y


def parent_id(node: dict[str, Any]) -> str:
    return layout_model.parent_id(node) or ""


def inlet_index(inlet_id: Any) -> int | None:
    if not isinstance(inlet_id, str):
        return None
    match = re.search(r"(\d+)$", inlet_id)
    return int(match.group(1)) if match else None


def resolve_field_data_type(
    by_id: dict[str, dict[str, Any]],
    start_node_id: str | None,
    field_name: str,
    max_depth: int = 12,
) -> str | None:
    """Resolve a field's declared dataType by walking upstream from a node.

    Checks, at each node on the single-input upstream chain, the places a type is
    DECLARED: edit `tgtCol` (calculated/normalized fields), adapter `specs`, and
    source `fields`. Stops without an answer at multi-input nodes or when nothing
    declares the field — callers must treat None as "unknown", never as a pass.
    """
    wanted = str(field_name or "").strip().casefold()
    if not wanted:
        return None
    current = start_node_id
    for _ in range(max_depth):
        node = by_id.get(current or "")
        if not node:
            return None
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        node_type = node.get("type")
        if node_type == "edit":
            for edit in as_list(config.get("edits")):
                tgt = edit.get("tgtCol") if isinstance(edit, dict) and isinstance(edit.get("tgtCol"), dict) else {}
                if str(tgt.get("name") or "").strip().casefold() == wanted:
                    value = tgt.get("dataType")
                    return str(value).strip().lower() if isinstance(value, str) else None
        elif node_type == "adapter":
            for spec in as_list(config.get("specs")):
                if isinstance(spec, dict) and str(spec.get("name") or "").strip().casefold() == wanted:
                    value = spec.get("dataType")
                    return str(value).strip().lower() if isinstance(value, str) else None
        elif node_type == "source":
            for field in as_list(config.get("fields")):
                if isinstance(field, dict) and str(field.get("name") or "").strip().casefold() == wanted:
                    value = field.get("dataType")
                    return str(value).strip().lower() if isinstance(value, str) else None
        inlets = [inlet for inlet in as_list(node.get("inlets")) if isinstance(inlet, dict)]
        upstream = [inlet.get("source") for inlet in inlets if isinstance(inlet.get("source"), str) and inlet.get("source")]
        if len(upstream) != 1:
            return None
        current = upstream[0]
    return None


def edge_targets(node: dict[str, Any]) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []
    for outlet in as_list(node.get("outlets")):
        outlet_id = outlet.get("id")
        if not isinstance(outlet_id, str):
            continue
        for target in as_list(outlet.get("targets")):
            if isinstance(target, dict):
                target_id = target.get("target")
                target_inlet = target.get("targetInlet")
            else:
                target_id = target
                target_inlet = None
            if isinstance(target_id, str):
                edges.append((outlet_id, target_id, target_inlet or ""))
    return edges


def inlet_source_refs(inlet: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    source = inlet.get("source")
    source_outlet = inlet.get("sourceOutlet")
    if isinstance(source, str) and source:
        refs.append((source, source_outlet if isinstance(source_outlet, str) else ""))
    for item in as_list(inlet.get("sources")):
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        source_outlet = item.get("sourceOutlet")
        if isinstance(source, str) and source:
            refs.append((source, source_outlet if isinstance(source_outlet, str) else ""))
    return refs


def grouped_workflow_children(workflow: dict[str, Any], group_id: str) -> list[dict[str, Any]]:
    return [
        n
        for n in as_list(workflow.get("nodes"))
        if n.get("canvasConfig", {}).get("parentId") == group_id
        and n.get("type") not in {"text", "group", "outlet"}
        and not str(n.get("id", "")).endswith("|0")
    ]


def grouped_readable_children(workflow: dict[str, Any], group_id: str) -> list[dict[str, Any]]:
    """Visible group objects whose labels need readable horizontal spacing."""
    return [
        n
        for n in as_list(workflow.get("nodes"))
        if n.get("canvasConfig", {}).get("parentId") == group_id
        and n.get("type") not in {"text", "group"}
    ]


def clustered_column_count(children: list[dict[str, Any]]) -> int:
    xs = sorted(
        x
        for x in (
            number((child.get("position") or {}).get("x"))
            for child in children
            if isinstance(child.get("position"), dict)
        )
        if x is not None
    )
    if not xs:
        return 0
    columns = [xs[0]]
    for x in xs[1:]:
        if abs(x - columns[-1]) > GROUP_COLUMN_CLUSTER_TOLERANCE:
            columns.append(x)
        else:
            columns[-1] = (columns[-1] + x) / 2
    return len(columns)


def horizontal_column_positions(children: list[dict[str, Any]]) -> list[float]:
    xs = sorted(
        x
        for x in (
            number((child.get("position") or {}).get("x"))
            for child in children
            if isinstance(child.get("position"), dict)
        )
        if x is not None
    )
    if not xs:
        return []
    columns = [xs[0]]
    for x in xs[1:]:
        if abs(x - columns[-1]) > GROUP_COLUMN_CLUSTER_TOLERANCE:
            columns.append(x)
        else:
            columns[-1] = (columns[-1] + x) / 2
    return columns


def estimated_label_width(node: dict[str, Any]) -> float:
    return label_width_estimate(node_label(node))


def horizontal_label_columns(children: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
    positioned = sorted(
        (
            (x, child)
            for child in children
            if isinstance(child.get("position"), dict)
            for x in [number((child.get("position") or {}).get("x"))]
            if x is not None
        ),
        key=lambda item: item[0],
    )
    if not positioned:
        return []
    clusters: list[list[tuple[float, dict[str, Any]]]] = [[positioned[0]]]
    for x, child in positioned[1:]:
        current_x = sum(item[0] for item in clusters[-1]) / len(clusters[-1])
        if abs(x - current_x) > GROUP_COLUMN_CLUSTER_TOLERANCE:
            clusters.append([(x, child)])
        else:
            clusters[-1].append((x, child))

    columns: list[tuple[float, float, str]] = []
    for cluster in clusters:
        x = sum(item[0] for item in cluster) / len(cluster)
        widest = max(cluster, key=lambda item: estimated_label_width(item[1]))[1]
        columns.append((x, estimated_label_width(widest), node_label(widest)))
    return columns


def expected_group_width_for_columns(column_count: int) -> tuple[float, float]:
    if column_count <= 0:
        return 0.0, float("inf")
    min_width = (
        GROUP_SIDE_PADDING_MIN * 2
        + column_count * APPROX_NODE_WIDTH
        + max(0, column_count - 1) * GROUP_COLUMN_GAP_MIN
    )
    return min_width, min_width + GROUP_WIDTH_EXTRA_ALLOWANCE


def expected_group_width_for_label_columns(label_columns: list[tuple[float, float, str]]) -> tuple[float, float] | None:
    if not label_columns:
        return None
    total_label_width = sum(max(APPROX_NODE_WIDTH, width) for _, width, _ in label_columns)
    min_width = (
        GROUP_SIDE_PADDING_MIN * 2
        + total_label_width
        + max(0, len(label_columns) - 1) * NODE_LABEL_GUTTER_MIN
    )
    return min_width, min_width + GROUP_WIDTH_EXTRA_ALLOWANCE


def horizontal_content_bounds(children: list[dict[str, Any]]) -> tuple[float, float] | None:
    xs = [
        x
        for x in (
            number((child.get("position") or {}).get("x"))
            for child in children
            if isinstance(child.get("position"), dict)
        )
        if x is not None
    ]
    if not xs:
        return None
    return min(xs), max(xs) + APPROX_NODE_WIDTH


def group_bounds(group: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[float, float, float, float] | None:
    pos = absolute_position(group, by_id)
    config = group.get("config") if isinstance(group.get("config"), dict) else {}
    width = number(config.get("width"))
    height = number(config.get("height"))
    if not pos or width is None or height is None:
        return None
    return pos[0], pos[1], pos[0] + width, pos[1] + height


def node_center(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[float, float] | None:
    pos = absolute_position(node, by_id)
    if not pos:
        return None
    return pos[0] + (APPROX_NODE_WIDTH / 2), pos[1] + (APPROX_NODE_HEIGHT / 2)


def node_output_port(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[float, float] | None:
    pos = absolute_position(node, by_id)
    if not pos:
        return None
    return pos[0] + APPROX_NODE_WIDTH, pos[1] + output_port_y_offset(node)


def node_input_port(
    node: dict[str, Any],
    inlet_id: str | None,
    by_id: dict[str, dict[str, Any]],
    source_id: str | None = None,
) -> tuple[float, float] | None:
    pos = absolute_position(node, by_id)
    if not pos:
        return None
    return pos[0], pos[1] + input_port_y_offset(node, inlet_id, source_id)


def target_inlet_id(node: dict[str, Any], source_id: str, source_outlet: str | None = None) -> str | None:
    for inlet in as_list(node.get("inlets")):
        if not isinstance(inlet, dict):
            continue
        if inlet.get("source") == source_id and (source_outlet is None or inlet.get("sourceOutlet") == source_outlet):
            value = inlet.get("id")
            return value if isinstance(value, str) else None
        for source in as_list(inlet.get("sources")):
            if isinstance(source, dict) and source.get("source") == source_id:
                value = inlet.get("id")
                return value if isinstance(value, str) else None
    return None


def node_inside_bounds(node: dict[str, Any], bounds: tuple[float, float, float, float], by_id: dict[str, dict[str, Any]]) -> bool:
    center = node_center(node, by_id)
    if not center:
        return False
    left, top, right, bottom = bounds
    return left <= center[0] <= right and top <= center[1] <= bottom


def point_inside_padded_bounds(point: tuple[float, float], bounds: tuple[float, float, float, float], padding: float = 0) -> bool:
    left, top, right, bottom = bounds
    return left + padding <= point[0] <= right - padding and top + padding <= point[1] <= bottom - padding


def group_visual_children(
    group: dict[str, Any],
    candidates: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    group_id = str(group.get("id") or "")
    bounds = group_bounds(group, by_id)
    children: list[dict[str, Any]] = []
    for node in candidates:
        if node.get("id") == group_id:
            continue
        if parent_id(node) == group_id or (bounds and node_inside_bounds(node, bounds, by_id)):
            children.append(node)
    return children


def visual_stage_categories(nodes: list[dict[str, Any]]) -> set[str]:
    categories: set[str] = set()
    for node in nodes:
        node_type = node.get("type")
        name = normalized_text(node.get("name"))
        if node_type == "source":
            categories.add("source")
        if node_type in {"edit", "filter", "pdfilter", "deduplicate", "multi_stack"}:
            categories.add("prep")
        if node_type in {"blend", "fuzzy_match"}:
            categories.add("enrichment")
        if node_type == "destination" or "final" in name or "output" in name:
            categories.add("output")
    return categories


def workflow_tags(workflow: dict[str, Any]) -> list[str]:
    tags = workflow.get("tags")
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str)]


# Workflow/node `description` fields render as Markdown in Savant's panel; HTML tags there
# show as literal text. Match real tags (`<p>`, `</b>`, `<code ...>`) without flagging
# comparison operators like "amount > 1000" or "x < y" (no letter immediately after `<`).
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?>")


def description_has_html(text: Any) -> bool:
    return isinstance(text, str) and bool(HTML_TAG_RE.search(text))


def validate_required_tracking_tag(workflow: dict[str, Any], required_tag: str | None, errors: list[str]) -> None:
    if not required_tag:
        return
    tags = workflow_tags(workflow)
    if required_tag not in tags:
        errors.append(
            f"Top-level `tags` must include required workflow tracking tag `{required_tag}`."
        )
    # A Savvy tag must carry a version (e.g. `Savvy v0.0.1`) so we can tell which Savvy
    # version created or edited a flow. A bare `Savvy` is treated as a stale/unversioned tag.
    if is_savvy_tracking_tag(required_tag) and not is_versioned_tracking_tag(required_tag):
        errors.append(
            f"Savvy tracking tag `{required_tag}` is missing a version; use a versioned tag like `Savvy v0.0.1`."
        )
    # The Savvy tracking tag records the distribution + version that last CREATED OR EDITED
    # the flow, so there must be exactly one Savvy-family tag and it must be the current one.
    # A different Savvy-family tag is a stale version (e.g. created with `Savvy v5`, then
    # edited with `Savvy v6` without updating the tag) and must be replaced, not kept beside it.
    if is_savvy_tracking_tag(required_tag):
        stale = sorted({t for t in tags if is_savvy_tracking_tag(t) and t != required_tag})
        if stale:
            joined = ", ".join(f"`{t}`" for t in stale)
            errors.append(
                f"Workflow carries stale Savvy tracking tag(s) {joined}; the tag must reflect the version "
                f"that last created or edited the flow. Replace with `{required_tag}` and keep exactly one Savvy tag."
            )


def _mergeable_pair_messages(
    by_id: dict[str, dict[str, Any]],
    adjacency: dict[str, list[str]],
    incoming: dict[str, list[str]],
) -> list[str]:
    """Strict adjacent multi-operation tool pairs.

    These are warnings for existing/live workflow validation, but Builder treats them as
    blockers because newly generated workflows should use one Transform/filter when the
    product component supports multiple operations in one step.
    """
    messages: list[str] = []
    _MERGEABLE = {"edit": "Transforms", "filter": "filters", "pdfilter": "filters"}
    for a_id, a_targets in adjacency.items():
        a = by_id.get(a_id) or {}
        a_type = a.get("type")
        if a_type not in _MERGEABLE or len(a_targets) != 1:
            continue
        b_id = a_targets[0]
        b = by_id.get(b_id) or {}
        b_type = b.get("type")
        same = a_type == b_type or {a_type, b_type} == {"filter", "pdfilter"}
        if not same or len(incoming.get(b_id, [])) != 1:
            continue
        if a_type in {"filter", "pdfilter"} and (
            (a.get("config") or {}).get("useFalsePath") or (b.get("config") or {}).get("useFalsePath")
        ):
            continue  # a false-path split is a deliberate fork, not a mergeable pair
        messages.append(
            f"Consecutive {_MERGEABLE[a_type]} `{node_label(a)}` -> `{node_label(b)}` can usually be merged "
            f"into one node (one Transform does add/rename/retype/hide/reorder; one filter holds multiple "
            f"AND/OR conditions). Combine this strict linear pair into one node."
        )
    return messages


def mergeable_pair_messages(workflow: dict[str, Any]) -> list[str]:
    """Return strict adjacent Transform/filter pairs without running full validation."""
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if not isinstance(nodes, list):
        return []
    by_id = {
        node.get("id"): node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for node_id, node in by_id.items():
        for _outlet_id, target_id, _target_inlet in edge_targets(node):
            if target_id in by_id:
                adjacency[node_id].append(target_id)
                incoming[target_id].append(node_id)
    return _mergeable_pair_messages(by_id, adjacency, incoming)


def _excel_destination_workbook_key(config: Any) -> tuple | None:
    """Identity of the Excel workbook a file destination writes to, for collision grouping.

    Returns None for anything that is not an Excel file destination (native CSV, CSV file output,
    non-dict config). The key includes the full target path — system, folder, subfolder, file name —
    so two destinations only group together when they truly point at the same workbook. Static path
    parts are normalized (cased/stripped); a field-driven part keys on the column name, since the
    real value is resolved per row at run time."""
    if not isinstance(config, dict):
        return None
    fsc = config.get("fileSystemConfig")
    if not isinstance(fsc, dict):
        return None
    if str(fsc.get("fileType") or "").strip().upper() != "EXCEL":
        return None
    connector = str(config.get("connector") or config.get("type") or "").strip().lower()
    system_id = str(config.get("id") or "").strip()
    folder = str(fsc.get("folderLink") or "").strip().casefold()

    def _path_part(mode_key: str, static_key: str, field_key: str) -> tuple[str, str]:
        if str(fsc.get(mode_key) or "static").strip().lower() == "field":
            return ("field", str(fsc.get(field_key) or "").strip().casefold())
        return ("static", str(fsc.get(static_key) or "").strip().casefold())

    subfolder = _path_part("subFolderNameMode", "subFolderName", "subFolderNameField")
    filename = _path_part("fileNameMode", "fileName", "fileNameField")
    return (connector, system_id, folder, subfolder, filename)


def _template_flag_is_set(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    fsc = config.get("fileSystemConfig")
    flag = fsc.get("formatFromTemplate") if isinstance(fsc, dict) else None
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str):
        return flag.strip().casefold() in {"true", "yes", "1"}
    return False


def excel_template_overwrite_groups(nodes: list[dict]) -> list[tuple[list[str], bool]]:
    """Find Excel workbooks that more than one destination would recreate from a template.

    A file destination with `formatFromTemplate=true` rebuilds the whole workbook from its template
    when it writes. Two or more pointed at the same workbook means whichever runs last wipes the tabs
    the others wrote — the file imports and runs without error but silently loses tabs/data. Returns
    `(destination_labels, certain)` per offending workbook: `certain` is True when the target path is
    fully static (a guaranteed collision) and False when any path part is field-driven (resolved per
    row, so only a probable collision)."""
    groups: dict[tuple, list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "destination":
            continue
        config = node.get("config")
        key = _excel_destination_workbook_key(config)
        if key is None or not _template_flag_is_set(config):
            continue
        groups.setdefault(key, []).append(node_label(node))
    return [
        (labels, key[3][0] == "static" and key[4][0] == "static")
        for key, labels in groups.items()
        if len(labels) >= 2
    ]


def validate(
    path: Path,
    required_tag: str | None = None,
    schema_hints: dict[str, Any] | None = None,
    block_mergeable_pairs: bool = False,
    block_documentation_gaps: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        workflow = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - CLI should report parse failures plainly.
        return [f"Cannot parse JSON: {exc}"], []

    if not isinstance(workflow, dict):
        return ["Top-level workflow must be a JSON object."], []

    validate_required_tracking_tag(workflow, required_tag, errors)

    if description_has_html(workflow.get("description")):
        warnings.append(
            "Workflow `description` contains HTML tags. The Description panel renders Markdown, so HTML "
            "displays as literal text. Write the workflow description in Markdown (`**bold**`, `*`/`-` bullets, "
            "headings, backtick `code`); HTML belongs only in group header text nodes (`config.text`)."
        )

    try:
        registry = load_registry()
    except Exception as exc:  # noqa: BLE001 - report registry failures plainly.
        return [f"Cannot load workflow capability registry: {exc}"], []
    common = registry.get("common") if isinstance(registry.get("common"), dict) else {}

    name = workflow.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("Top-level `name` must be a non-empty string.")
    workflow_description = rich_text_plain(workflow.get("description"))
    if len(workflow_description) < MIN_WORKFLOW_DESCRIPTION_CHARS:
        warnings.append(
            "Workflow has no clear top-level description; add a business-readable summary of the inputs, "
            "main processing stages, assumptions, and outputs."
        )

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return errors + ["Top-level `nodes` must be an array."], warnings

    if not nodes:
        warnings.append("Workflow has no nodes.")

    ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"Node at index {idx} is not an object.")
            continue
        node_id = node.get("id")
        node_type = node.get("type")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"Node at index {idx} has no string `id`.")
            continue
        if node_id in ids:
            errors.append(f"Duplicate node id `{node_id}`.")
        ids.add(node_id)
        by_id[node_id] = node
        if not NODE_ID_RE.match(node_id):
            warnings.append(f"Node `{node_id}` does not match the standard id pattern.")
        if not isinstance(node_type, str) or not node_type:
            errors.append(f"Node `{node_id}` has no string `type`.")
        if not isinstance(node.get("name"), str) or not node.get("name", "").strip():
            warnings.append(f"Node `{node_id}` has no readable display name.")
        if node_type == "text":
            plain = text_plain(node)
            rendered = text_rendered_plain(node)
            if plain and not rendered:
                errors.append(
                    f"Text node `{node_id}` has `inputText` but empty rendered `config.text`. "
                    "Savant renders text nodes from `config.text`; populate the matching rich-text HTML."
                )
            if is_group_child(node):
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                missing = sorted(GROUP_HEADER_REQUIRED_TEXT_CONFIG_KEYS - set(config))
                if missing:
                    errors.append(
                        f"Group header text node `{node_id}` is missing initialized text config key(s): "
                        f"{', '.join(f'`{key}`' for key in missing)}. Group headers must use the full "
                        "initialized text-node shape; under-initialized group text can be pruned by Savant "
                        "after normal blank-canvas interactions."
                    )
                if config.get("isInitialized") is not True:
                    errors.append(
                        f"Group header text node `{node_id}` must set `config.isInitialized` to true. "
                        "Under-initialized group text can be pruned by Savant after normal blank-canvas interactions."
                    )
                for key in ("width", "height", "minWidth", "minHeight", "currentHeight"):
                    if key in config and not is_positive_number(config.get(key)):
                        errors.append(
                            f"Group header text node `{node_id}` has invalid `config.{key}`; expected a positive number."
                        )
        pos = node.get("position")
        if not isinstance(pos, dict) or not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("y"), (int, float)):
            warnings.append(f"Node `{node_id}` has no numeric canvas position.")

    adjacency: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)

    for node_id, node in by_id.items():
        node_type = node.get("type")
        inlets = as_list(node.get("inlets"))
        outlets = as_list(node.get("outlets"))

        if node_type == "source" and inlets:
            errors.append(f"Source `{node.get('name', node_id)}` has inlets; sources should have none.")
        if node_type == "destination":
            for outlet in outlets:
                if as_list(outlet.get("targets")):
                    errors.append(f"Destination `{node.get('name', node_id)}` has downstream targets.")

        inlet_ids = {i.get("id") for i in inlets if isinstance(i, dict)}
        outlet_ids = {o.get("id") for o in outlets if isinstance(o, dict)}

        # An embedded `outlets[].id` must be `out_N` (out_0, out_1, ...). Every node type in
        # real exports uses this form (0 exceptions in ~30k outlets). A non-standard id such
        # as a blend's `blend|0` breaks the FIRST downstream node's column resolution, which
        # fails at runtime with "Index 1 out of bounds for length 1". (The `{id}|{index}` form
        # is only valid as a separate outlet *node*'s top-level id, never as an `outlets[].id`.)
        for outlet in outlets:
            if not isinstance(outlet, dict):
                continue
            oid = outlet.get("id")
            if isinstance(oid, str) and not OUTLET_ID_RE.fullmatch(oid):
                errors.append(
                    f"Node `{node_id}` has embedded outlet id `{oid}`; embedded outlet ids must be "
                    f"`out_0`, `out_1`, ... A non-standard id (e.g. a blend's `blend|0`) breaks the first "
                    f"downstream node at runtime (\"Index N out of bounds\"). Rename it to `out_0` and update "
                    f"the consumer inlet's `sourceOutlet`."
                )
            if node_type == "filter" and oid != "out_0" and as_list(outlet.get("targets")):
                errors.append(
                    f"Filter `{node.get('name', node_id)}` has downstream targets on embedded outlet `{oid}`. "
                    "Filter parent nodes may carry an empty `out_1` placeholder, but direct `out_1` targets "
                    "are not exposed at runtime unless the filter is represented as an enabled false path. "
                    "Direct filter `out_1` wiring fails at runtime."
                )

        for inlet in inlets:
            if not isinstance(inlet, dict):
                continue
            for source, source_outlet in inlet_source_refs(inlet):
                if source not in by_id:
                    errors.append(f"Node `{node_id}` inlet `{inlet.get('id')}` references missing source `{source}`.")
                    continue
                if source_outlet:
                    source_outlets = {o.get("id") for o in as_list(by_id[source].get("outlets")) if isinstance(o, dict)}
                    if source_outlet not in source_outlets:
                        errors.append(f"Node `{node_id}` inlet `{inlet.get('id')}` references missing outlet `{source}.{source_outlet}`.")
                # Inlet-only edge: the inlet names a source, but that source node's outlet does
                # not list this node back in its `targets`. Savant builds the live DAG from
                # outlet `targets` (real exports never have inlet-only edges), so an edge present
                # only on the inlet side does not exist at runtime — the downstream node loads
                # with no input and fails with "Internal system error". Every edge must be on
                # BOTH sides. This commonly happens for edges that cross a group boundary.
                inlet_id = inlet.get("id")
                has_back_target = any(
                    target_id == node_id
                    and (not source_outlet or outlet_id == source_outlet)
                    and (not target_inlet or not inlet_id or target_inlet == inlet_id)
                    for outlet_id, target_id, target_inlet in edge_targets(by_id[source])
                )
                if not has_back_target:
                    errors.append(
                        f"Node `{node_id}` inlet `{inlet_id}` is fed by `{source}.{source_outlet or 'out_0'}`, "
                        f"but that outlet does not list `{node_id}` in its `targets`. Savant builds the graph "
                        f"from outlet targets, so this inlet-only edge does not exist at runtime (the node loads "
                        f"with no input and fails). Add `{node_id}` to `{source}`'s outlet `targets`."
                    )

        for outlet_id, target_id, target_inlet in edge_targets(node):
            if outlet_id not in outlet_ids:
                errors.append(f"Node `{node_id}` has target on undeclared outlet `{outlet_id}`.")
            if target_id not in by_id:
                errors.append(f"Node `{node_id}` outlet `{outlet_id}` targets missing node `{target_id}`.")
                continue
            adjacency[node_id].append(target_id)
            incoming[target_id].append(node_id)
            if target_inlet:
                target_inlets = {i.get("id") for i in as_list(by_id[target_id].get("inlets")) if isinstance(i, dict)}
                if target_inlet not in target_inlets:
                    errors.append(f"Node `{node_id}` targets `{target_id}.{target_inlet}`, but that inlet is not declared.")
            matching_inlets = [
                inlet
                for inlet in as_list(by_id[target_id].get("inlets"))
                if isinstance(inlet, dict)
                and (not target_inlet or inlet.get("id") == target_inlet)
                and any(source == node_id for source, _ in inlet_source_refs(inlet))
            ]
            if not matching_inlets:
                errors.append(f"Edge `{node_id}` -> `{target_id}` is missing the matching target inlet source.")

    # Optimization nudge: two same-type edit/filter nodes directly in a line can usually be merged.
    for message in _mergeable_pair_messages(by_id, adjacency, incoming):
        if block_mergeable_pairs:
            errors.append(message)
        else:
            warnings.append(message)

    for node_id, node in by_id.items():
        if node_requires_upstream_input(node) and not incoming.get(node_id):
            errors.append(f"Processing node `{node_label(node)}` has no upstream input.")

    for node_id, node in by_id.items():
        if node.get("type") != "gen_ai":
            continue
        upstream_ids = incoming.get(node_id, [])
        optional_blends = [
            by_id.get(src)
            for src in upstream_ids
            if (by_id.get(src) or {}).get("type") == "blend"
            and not blend_is_inner_main_output((by_id.get(src) or {}).get("config") or {})
        ]
        if optional_blends:
            input_fields = (node.get("config") or {}).get("inputFields")
            fields = ", ".join(input_fields) if isinstance(input_fields, list) else "configured input fields"
            blend_names = ", ".join(f"`{node_label(blend)}`" for blend in optional_blends if blend)
            warnings.append(
                f"AI step `{node_label(node)}` is fed directly from optional Blend {blend_names}. Optional joins can produce blank "
                f"values for {fields}; add a small Transform before the AI step that defaults missing review/comment "
                f"text to an explicit neutral placeholder, and mention that placeholder in the AI prompt."
            )

    for node_id, node in by_id.items():
        if node.get("type") != "json":
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if config.get("mode") != "flatten":
            continue
        hint_keys = node_schema_hint_keys(node, schema_hints)
        if not hint_keys:
            continue
        ai_sources = [
            by_id.get(src)
            for src in incoming.get(node_id, [])
            if (by_id.get(src) or {}).get("type") in {"gen_ai", "vision"}
        ]
        if not ai_sources:
            continue
        upstream = ai_sources[0]
        errors.append(
            f"Schema hint `{hint_keys[0]}` is attached to JSON flatten node `{node_label(node)}`, but the "
            f"opaque output producer is `{node_label(upstream)}`. Move the expected generated columns to "
            f"the AI node in `--schema-hints` using key `{upstream.get('id')}` or `{node_label(upstream)}`; "
            "JSON flatten hints do not make the AI output schema known."
        )

    # Cycle detection.
    indegree = {node_id: 0 for node_id in by_id}
    for src, targets in adjacency.items():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    queue = deque([node_id for node_id, degree in indegree.items() if degree == 0])
    visited = 0
    while queue:
        src = queue.popleft()
        visited += 1
        for target in adjacency.get(src, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(by_id):
        errors.append("Workflow graph contains a cycle or unresolved cyclic dependency.")

    inferred_fields: dict[str, dict[str, str]] = {}
    inferred_schema_known: dict[str, bool] = {}
    remaining = {node_id: len(incoming.get(node_id, [])) for node_id in by_id}
    field_queue = deque([node_id for node_id, count in remaining.items() if count == 0])
    field_visited: set[str] = set()
    while field_queue:
        node_id = field_queue.popleft()
        if node_id in field_visited:
            continue
        field_visited.add(node_id)
        node = by_id[node_id]
        node_type = node.get("type")
        upstream_fields: dict[str, str] = {}
        upstream_ref_count = 0
        upstream_schema_known = True
        for inlet in as_list(node.get("inlets")):
            if not isinstance(inlet, dict):
                continue
            for source, _ in inlet_source_refs(inlet):
                upstream_ref_count += 1
                upstream_fields.update(inferred_fields.get(source, {}))
                upstream_schema_known = upstream_schema_known and inferred_schema_known.get(source, False)
        if upstream_ref_count == 0:
            upstream_schema_known = False
        if node_type != "edit" and upstream_schema_known and upstream_ref_count > 0:
            validate_known_input_field_refs(node, upstream_fields, errors)

        if node_type == "source":
            output_fields = source_output_fields(node, workflow)
            if not output_fields:
                # A dataset-bound source carries no inline schema, so downstream column
                # references would go unchecked. The planner/builder can pass the sample
                # (or profiled) column names via the `--schema-hints` sidecar keyed to the
                # source node; treat those as the source's output schema so references are
                # validated. Sidecar-only — never written into the workflow JSON.
                hinted = node_schema_hint(node, schema_hints)
                if hinted:
                    for column in hinted:
                        add_output_field(output_fields, column)
            output_schema_known = bool(output_fields)
        elif node_type == "adapter":
            output_fields = {}
            for spec in as_list((node.get("config") or {}).get("specs") if isinstance(node.get("config"), dict) else None):
                identity = field_identity(spec)
                if not identity:
                    continue
                field_id, name = identity
                add_output_field(output_fields, field_id, name)
            output_schema_known = bool(output_fields)
        elif node_type == "edit":
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known
            for edit in as_list((node.get("config") or {}).get("edits") if isinstance(node.get("config"), dict) else None):
                if not isinstance(edit, dict):
                    continue
                if upstream_schema_known:
                    validate_known_field_refs(edit, output_fields, f"Transform `{node_label(node)}`", errors)
                if edit.get("mode") in {"expression", "copilot"}:
                    pipeline = edit.get("pipeline") if isinstance(edit.get("pipeline"), dict) else {}
                    validate_expression_text(
                        edit.get("expression"),
                        common,
                        f"Transform `{node_label(node)}` expression",
                        errors,
                        lookup=edit.get("lookup"),
                        pipeline_steps=as_list(pipeline.get("steps")),
                        upstream_fields=output_fields if upstream_schema_known else None,
                        declared_params=workflow_parameter_names(workflow),
                    )
                tgt_col = edit.get("tgtCol") if isinstance(edit.get("tgtCol"), dict) else {}
                tgt_name = tgt_col.get("name")
                tgt_id = tgt_col.get("id")
                if not isinstance(tgt_name, str) or not tgt_name.strip():
                    continue
                name_key = canonical_column_name(tgt_name)
                id_key = canonical_column_name(tgt_id)
                action = edit.get("action")
                if action == "add_col":
                    if upstream_schema_known and (name_key in output_fields or (id_key and id_key in output_fields)):
                        existing = output_fields.get(name_key) or output_fields.get(id_key) or tgt_name
                        errors.append(
                            f"Transform `{node_label(node)}` adds calculated field `{tgt_name}`, but upstream already has "
                            f"column `{existing}`. Use `replace` for the existing column or choose a unique reporting alias."
                        )
                    output_fields[name_key] = tgt_name
                    if id_key:
                        output_fields[id_key] = tgt_name
                elif action == "replace":
                    replace_target = edit.get("replaceTgt")
                    replace_keys = []
                    if isinstance(replace_target, str) and replace_target.strip():
                        replace_keys.append(canonical_column_name(replace_target))
                    else:
                        replace_keys.append(name_key)
                        if id_key:
                            replace_keys.append(id_key)
                    if upstream_schema_known and not any(key in output_fields for key in replace_keys):
                        rendered_target = replace_target if isinstance(replace_target, str) and replace_target.strip() else tgt_name
                        errors.append(
                            f"Transform `{node_label(node)}` replaces `{rendered_target}`, but that column was not found upstream. "
                            "A Savant replace can behave like an add and create duplicate/broken fields; use an existing "
                            "field id/name or change the action to `add_col` with a unique name."
                        )
                    for key in replace_keys:
                        remove_output_field(output_fields, key)
                    output_fields[name_key] = tgt_name
                    if id_key:
                        output_fields[id_key] = tgt_name
                else:
                    output_fields[name_key] = tgt_name
                    if id_key:
                        output_fields[id_key] = tgt_name
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            hidden_fields = as_list(config.get("hiddenFields"))
            for field_id in hidden_fields:
                remove_output_field(output_fields, field_id)
            # NOTE: `orderedFields` is a pin-to-front list, NOT an exhaustive output whitelist.
            # The Edit launcher emits the listed fields first (in order) and then appends every
            # other column in natural schema order (`ordered ++ unordered` in Edit.scala) — unlisted
            # columns are kept, not dropped. So a partial `orderedFields` is correct and expected;
            # we do not require every visible column to appear in it. Removing unwanted passthrough
            # columns is `hiddenFields`' job (or `keep_only_columns`), checked elsewhere.
        elif node_type in {"filter", "pdfilter"}:
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            pipeline = config.get("pipeline") if isinstance(config.get("pipeline"), dict) else {}
            validate_expression_text(
                config.get("dataFilterExpr"),
                common,
                f"Filter `{node_label(node)}` expression",
                errors,
                require_boolean=True,
                lookup=config.get("dataFilterLookUp"),
                pipeline_steps=as_list(pipeline.get("steps")),
                upstream_fields=upstream_fields if upstream_schema_known else None,
                declared_params=workflow_parameter_names(workflow),
            )
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known
        elif node_type == "summarize":
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            output_fields = {}
            for group_key in as_list(config.get("groupBy")):
                if isinstance(group_key, str) and group_key.strip():
                    add_output_field(output_fields, group_key)
            for agg in as_list(config.get("aggs")):
                if not isinstance(agg, dict):
                    continue
                identity = field_identity(agg.get("tgt_col"))
                if identity:
                    field_id, name = identity
                    add_output_field(output_fields, field_id, name)
            output_schema_known = True
        elif node_type == "rollup":
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            output_fields = {}
            for group_key in as_list(config.get("groupBy")):
                if isinstance(group_key, str) and group_key.strip():
                    add_output_field(output_fields, group_key)
            add_output_field(output_fields, "period_name", "Period Name")
            add_output_field(output_fields, "period_offset", "Period Offset")
            for agg in as_list(config.get("aggs")):
                if not isinstance(agg, dict):
                    continue
                identity = field_identity(agg.get("tgt_col"))
                if identity:
                    field_id, name = identity
                    add_output_field(output_fields, field_id, name)
            output_schema_known = True
        elif node_type == "blend":
            inlet_fields: dict[str, dict[str, str]] = {}
            inlet_known: dict[str, bool] = {}
            for inlet in as_list(node.get("inlets")):
                if not isinstance(inlet, dict):
                    continue
                inlet_id = inlet.get("id")
                if not isinstance(inlet_id, str):
                    continue
                fields: dict[str, str] = {}
                known = True
                refs = inlet_source_refs(inlet)
                if not refs:
                    known = False
                for source, _ in refs:
                    fields.update(inferred_fields.get(source, {}))
                    known = known and inferred_schema_known.get(source, False)
                inlet_fields[inlet_id] = fields
                inlet_known[inlet_id] = known
            if inlet_known.get("in_0") and inlet_known.get("in_1"):
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                validate_blend_join_fields(
                    node,
                    inlet_fields.get("in_0", {}),
                    inlet_fields.get("in_1", {}),
                    errors,
                )
                validate_blend_join_key_normalization(node, errors, warnings)
                output_fields = blend_output_fields(inlet_fields.get("in_0", {}), inlet_fields.get("in_1", {}), config)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type in AI_OPAQUE_OUTPUT_TYPES:
            # AI components materialize their output columns at runtime from a prompt,
            # so the upstream schema does not describe what they emit. If the build
            # declared the expected output columns, treat the declared set (plus any
            # known pass-through columns) as the node's known schema. Otherwise mark
            # the output schema unknown so downstream column references are not
            # checked against a schema that is missing the AI-produced columns.
            declared = node_schema_hint(node, schema_hints)
            if declared is not None:
                output_fields = dict(upstream_fields) if upstream_schema_known else {}
                for column in declared:
                    add_output_field(output_fields, column)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type == "pivot":
            # Pivot emits data-dependent columns (one per distinct value) the validator cannot
            # enumerate. If the build declared the output columns via `--schema-hints`, treat
            # that as the node's full output schema; otherwise mark the schema unknown.
            declared = node_schema_hint(node, schema_hints)
            if declared is not None:
                output_fields = {}
                for column in declared:
                    add_output_field(output_fields, column)
                output_schema_known = True
            else:
                output_fields = {}
                output_schema_known = False
        elif node_type == "unpivot":
            # Unpivot's row count is data-dependent, but the column list is deterministic when
            # the upstream schema is known: identity columns plus the configured name/value fields.
            # Keep schema hints as the fallback for unknown-source builds.
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            if upstream_schema_known:
                output_fields = unpivot_output_fields(upstream_fields, config)
                output_schema_known = bool(output_fields)
            else:
                declared = node_schema_hint(node, schema_hints)
                if declared is not None:
                    output_fields = {}
                    for column in declared:
                        add_output_field(output_fields, column)
                    output_schema_known = True
                else:
                    output_fields = {}
                    output_schema_known = False
        else:
            output_fields = dict(upstream_fields)
            output_schema_known = upstream_schema_known
        inferred_fields[node_id] = output_fields
        inferred_schema_known[node_id] = output_schema_known

        for target in adjacency.get(node_id, []):
            remaining[target] = max(0, remaining.get(target, 0) - 1)
            if remaining[target] == 0:
                field_queue.append(target)

    for node_id, node in by_id.items():
        if node.get("type") not in {"filter", "pdfilter"}:
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if config.get("useFalsePath"):
            continue
        refs = filter_predicate_field_keys(node)
        if not refs:
            continue
        upstream_ids = incoming.get(node_id, [])
        if len(upstream_ids) != 1:
            continue
        immediate_upstream_id = upstream_ids[0]
        immediate_upstream = by_id.get(immediate_upstream_id)
        if not immediate_upstream or immediate_upstream.get("type") not in FILTER_PUSHDOWN_REVIEW_TYPES:
            continue
        if len(adjacency.get(immediate_upstream_id, [])) != 1:
            continue
        prior_sources = incoming.get(immediate_upstream_id, [])
        if not prior_sources:
            continue
        prior_fields: dict[str, str] = {}
        prior_schema_known = True
        for source_id in prior_sources:
            prior_fields.update(inferred_fields.get(source_id, {}))
            prior_schema_known = prior_schema_known and inferred_schema_known.get(source_id, False)
        if not prior_schema_known:
            continue
        if refs <= set(prior_fields):
            field_names = sorted({prior_fields.get(ref, ref) for ref in refs})
            preview = ", ".join(f"`{name}`" for name in field_names[:5])
            suffix = " ..." if len(field_names) > 5 else ""
            warnings.append(
                f"Filter `{node_label(node)}` runs after `{node_label(immediate_upstream)}`, but its predicate field(s) "
                f"{preview}{suffix} were already available before that step. Review whether this row filter should move "
                "earlier so later joins, stacks, summaries, AI, or destinations carry fewer rows."
            )

    # Layout and terminal checks.
    destination_nodes = [n for n in by_id.values() if n.get("type") == "destination"]
    group_nodes_for_layout = [n for n in by_id.values() if n.get("type") == "group"]
    destination_group_ids = {
        parent_id(destination)
        for destination in destination_nodes
        if parent_id(destination)
    }
    group_outgoing_targets: dict[str, set[str]] = defaultdict(set)
    for src, targets in adjacency.items():
        src_group = parent_id(by_id.get(src, {}))
        if not src_group:
            continue
        for target in targets:
            target_group = parent_id(by_id.get(target, {}))
            if target_group and target_group != src_group:
                group_outgoing_targets[src_group].add(target_group)
    terminal_output_group_ids = {
        gid for gid in destination_group_ids
        if not group_outgoing_targets.get(gid)
    }
    # Side-band groups are terminal destination groups fed by 2+ distinct stages
    # (review/validation taps). The right place for them is a band BELOW the main
    # flow, so the "terminal outputs sit to the right" placement rules exempt them.
    side_band_layout_group_ids = layout_metrics.side_band_group_ids(list(by_id.values()))
    if not destination_nodes:
        warnings.append("Workflow has no destination nodes; this is fine for a draft, but not for a deliverable output workflow.")
    for destination in destination_nodes:
        destination_id = destination.get("id")
        if not isinstance(destination_id, str):
            continue
        upstream_ids = incoming.get(destination_id, [])
        if not upstream_ids:
            errors.append(f"Destination `{node_label(destination)}` has no upstream input.")
            continue
        destination_schema_known = inferred_schema_known.get(destination_id, False)
        destination_fields = inferred_fields.get(destination_id, {})
        if destination_schema_known and not unique_output_field_names(destination_fields):
            errors.append(
                f"Destination `{node_label(destination)}` has an empty known output schema; attach a shaped upstream table "
                "with at least one visible business column."
            )
        elif not destination_schema_known:
            warnings.append(
                f"Destination `{node_label(destination)}` output schema is unknown at validation time; verify the upstream "
                "node's live preview before treating the workflow as ready."
            )

        seen: set[str] = set()
        stack = list(upstream_ids)
        has_business_processing = False
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            current_node = by_id.get(current)
            if not current_node:
                continue
            current_type = current_node.get("type")
            if current_type in BUSINESS_PROCESSING_TYPES:
                has_business_processing = True
                break
            stack.extend(incoming.get(current, []))
        if not has_business_processing:
            warnings.append(
                f"Destination `{node_label(destination)}` is fed without any business processing node between source "
                "standardization and output. Verify this pass-through output is intentional."
            )

    for src, targets in adjacency.items():
        src_node = by_id.get(src, {})
        src_pos = absolute_position(src_node, by_id)
        src_x = src_pos[0] if src_pos else None
        for target in targets:
            target_node = by_id.get(target, {})
            target_pos = absolute_position(target_node, by_id)
            target_x = target_pos[0] if target_pos else None
            if isinstance(src_x, (int, float)) and isinstance(target_x, (int, float)) and target_x <= src_x:
                target_group = parent_id(target_node)
                if target_group in terminal_output_group_ids:
                    errors.append(
                        f"Terminal output group `{target_group}` receives a backward edge `{node_label(src_node)}` -> "
                        f"`{node_label(target_node)}`. Place terminal output groups to the right of the final "
                        "processing step; do not route final delivery underneath or back into the main flow."
                    )
                else:
                    warnings.append(f"Edge `{src}` -> `{target}` is not left-to-right by saved x position.")

    if terminal_output_group_ids:
        group_bounds_for_output = {
            str(group.get("id")): bounds
            for group in group_nodes_for_layout
            if isinstance(group.get("id"), str)
            for bounds in [group_bounds(group, by_id)]
            if bounds is not None
        }
        processing_group_bounds = [
            bounds
            for gid, bounds in group_bounds_for_output.items()
            if gid not in terminal_output_group_ids
        ]
        if processing_group_bounds:
            main_top = min(bounds[1] for bounds in processing_group_bounds)
            final_processing = max(processing_group_bounds, key=lambda bounds: bounds[2])
            for gid in sorted(terminal_output_group_ids):
                if gid in side_band_layout_group_ids:
                    continue
                bounds = group_bounds_for_output.get(gid)
                if bounds is None:
                    continue
                if bounds[1] > main_top + OUTPUT_GROUP_BELOW_MAIN_LANE_TOLERANCE:
                    warnings.append(
                        f"Terminal output group `{gid}` is positioned far below the main flow; it is likely to be "
                        "hidden or awkward when the preview panel is open. Place terminal outputs to the right of "
                        "the final processing stage."
                    )
                horizontally_under_final = bounds[0] < final_processing[2] and bounds[2] > final_processing[0]
                below_final = bounds[1] > final_processing[3] + GROUP_GUTTER_MIN
                if horizontally_under_final and below_final:
                    errors.append(
                        f"Terminal output group `{gid}` is underneath the final processing stage. Terminal output "
                        "groups should generally sit to the right of the final processing step, not below it."
                    )

    for source in [n for n in by_id.values() if n.get("type") == "source"]:
        targets = [by_id[t] for _, t, _ in edge_targets(source) if t in by_id]
        if targets and not any(is_standardizing_node(t) for t in targets):
            warnings.append(
                f"Source `{source.get('name', source.get('id'))}` does not feed a standardizing "
                f"Adapter or `Normalize ...` Transform first."
            )
        if is_source_requiring_profile(source, registry) and not has_profile_evidence(workflow, source):
            warnings.append(
                f"Source `{node_label(source)}` has a file/spreadsheet connector but no live schema profiling evidence "
                "in the workflow metadata or source config; verify exact live field names/ids and row counts before import."
            )

    for node_id, node in by_id.items():
        if node.get("type") in {"source", "group", "text"} or is_normalize_node(node):
            continue
        fragile_refs = sorted({ref for ref in collect_field_refs(node) if is_fragile_field_ref(ref)})
        if fragile_refs:
            preview = ", ".join(f"`{ref}`" for ref in fragile_refs[:5])
            suffix = " ..." if len(fragile_refs) > 5 else ""
            warnings.append(
                f"Node `{node_label(node)}` references fragile raw-looking field(s) outside normalization: "
                f"{preview}{suffix}. Create stable normalized aliases and use those downstream."
            )

    for source in [n for n in by_id.values() if n.get("type") == "source" and is_source_requiring_profile(n, registry)]:
        if not has_business_record_language(source):
            continue
        first_targets = [by_id[t] for _, t, _ in edge_targets(source) if t in by_id]
        normalize_targets = [target for target in first_targets if is_normalize_node(target)]
        for normalize in normalize_targets:
            queue = deque(adjacency.get(normalize.get("id"), []))
            seen: set[str] = set()
            reached_enrichment_before_filter = False
            while queue:
                target_id = queue.popleft()
                if target_id in seen:
                    continue
                seen.add(target_id)
                target = by_id.get(target_id)
                if not target:
                    continue
                target_type = target.get("type")
                if target_type in {"filter", "pdfilter"}:
                    continue
                if target_type in ENRICHMENT_TYPES:
                    reached_enrichment_before_filter = True
                    break
                queue.extend(adjacency.get(target_id, []))
            if reached_enrichment_before_filter:
                warnings.append(
                    f"Business-record source `{node_label(source)}` reaches enrichment/output after `{node_label(normalize)}` "
                    "without an intervening grain filter; verify subtotal/footer/non-business rows are excluded before joins, FX, or destinations."
                )

    for node_id, node in by_id.items():
        node_type = node.get("type")
        validate_registry_capabilities(workflow, node, registry, errors, warnings)
        # Group membership must live ONLY in `canvasConfig` ({"parentId": ..., "extent": "parent"}).
        # Savant remaps node/group ids on import and updates `canvasConfig.parentId`, but it does
        # NOT remap React Flow's native top-level `parentId`/`parentNode`/`extent`. If those are
        # present they point at pre-import ids after import and the renderer collapses every node
        # to the origin. The working examples never set them. Keep canvasConfig-only.
        if node_type == "source":
            # Verified live: Savant silently DROPS source nodes whose config carries
            # `fields`/`rowCount` (anything beyond {id, name, type, connector}) on
            # import. Warning (not error) for now because synthetic validator
            # fixtures still drive schema inference through config.fields; the
            # builder no longer emits them (evidence rides workflow-level
            # `sourceProfiles`). TODO: teach schema inference to read
            # sourceProfiles, migrate fixtures, then upgrade this to an error.
            extra_source_keys = sorted(
                set((node.get("config") or {}).keys()) - {"id", "name", "type", "connector"}
            )
            if extra_source_keys:
                warnings.append(
                    f"Source `{node_label(node)}` config carries extra key(s) {', '.join(f'`{k}`' for k in extra_source_keys)}; "
                    "Savant drops source nodes with extra config keys on import (verified live). Keep profiling "
                    "evidence in workflow-level `sourceProfiles` before importing this JSON."
                )
        if node_type in AI_OPAQUE_OUTPUT_TYPES:
            # AI nodes resolve their connector from `providerId` at import (gen_ai/vision/
            # fuzzy_match all do). A copied workflow export carries the export-only envelope
            # keys `type`/`connector` in config; a literal connector (e.g. "openai") fails to
            # resolve for a non-matching provider and Savant SILENTLY DROPS the whole AI node.
            # Hard error (not warning like sources): no fixture depends on these keys, and the
            # drop is invisible until the live workflow is found broken downstream.
            export_keys = ai_node_export_keys(node.get("config") or {})
            if export_keys:
                errors.append(
                    f"AI node `{node_label(node)}` config carries export-only key(s) "
                    f"{', '.join(f'`{k}`' for k in export_keys)}; remove them. The connector is derived from "
                    "`providerId`, and Savant silently drops the node on import when a literal connector is set. "
                    "Build AI nodes with the GenAI builder rather than copying config from an existing export."
                )
        stale_parent_fields = [k for k in ("parentId", "parentNode", "extent") if node.get(k) is not None]
        if stale_parent_fields:
            fields = ", ".join(f"`{k}`" for k in stale_parent_fields)
            errors.append(
                f"Node `{node_label(node)}` sets top-level {fields}. Savant does not remap these on import, "
                f"so the rendered canvas collapses (nodes pile at the origin). Encode group membership only in "
                f'`canvasConfig` (`parentId` + `extent: "parent"`) and remove the top-level field(s).'
            )
        if description_has_html(node.get("description")):
            warnings.append(
                f"Node `{node_label(node)}` `description` contains HTML tags. The Description panel renders "
                f"Markdown, so HTML displays as literal text. Write the description in Markdown (`**bold**`, "
                f"`*`/`-` bullets, backtick `code`); HTML belongs only in group header text nodes (`config.text`)."
            )
        if node_type in DESCRIBED_NODE_TYPES:
            desc = get_description(node)
            if len(desc) < MIN_NODE_DESCRIPTION_CHARS:
                config_desc = get_config_description(node)
                if len(config_desc) >= MIN_NODE_DESCRIPTION_CHARS:
                    warnings.append(
                        f"Node `{node_label(node)}` has a business description only inside its config; "
                        "copy it to the node-level description field so Savant shows it in the Description panel."
                    )
                else:
                    warnings.append(
                        f"Node `{node_label(node)}` has no clear business description; write a node-specific "
                        "configuration readout in plain language, including row/column/match/grain/output impact "
                        "and formulas only where the node config has calculations."
                    )
            else:
                upstream_fields_for_description: dict[str, str] = {}
                for upstream_id in incoming.get(node_id, []):
                    upstream_fields_for_description.update(inferred_fields.get(upstream_id, {}))
                description_issues = errors if block_documentation_gaps else warnings
                validate_node_description_fidelity(node, upstream_fields_for_description, description_issues)
        if node_type == "blend":
            inlets = as_list(node.get("inlets"))
            if len(inlets) < 2:
                warnings.append(f"Blend `{node.get('name', node_id)}` has fewer than two inputs.")
            blend_config = node.get("config") if isinstance(node.get("config"), dict) else {}
            regions = blend_config.get("regions")
            if not regions:
                warnings.append(f"Blend `{node.get('name', node_id)}` has no explicit retained-region config.")
            if (
                isinstance(regions, list)
                and set(regions) != {"T1_N_T2"}
                and (blend_config.get("useLeftUnmatch") or blend_config.get("useRightUnmatch"))
            ):
                warnings.append(
                    f"Blend `{node_label(node)}` combines a non-inner join with an unmatched-output split. "
                    "The main output of a left/right/full join already includes unmatched rows (null columns "
                    "from the other side), so the 'matched' fork is not matched-only and downstream summaries "
                    "can silently include null-key rows. For a matched-vs-unmatched split, use an inner join "
                    "with the unmatched fork; keep this shape only if downstream intentionally consumes the "
                    "full main output plus a separate unmatched list."
                )
            # Join keys must carry the SAME declared dataType on both sides; a type
            # mismatch (e.g. integer ZIP vs text ZIP) silently yields zero matches at
            # runtime. The plan/profiler know the types and the adapter standardizes
            # them, so a surviving mismatch is a build defect — refuse before import.
            left_input = next((inlet.get("source") for inlet in inlets if str(inlet.get("id") or "") == "in_0"), None)
            right_input = next((inlet.get("source") for inlet in inlets if str(inlet.get("id") or "") == "in_1"), None)
            for condition in as_list(blend_config.get("on")):
                if not isinstance(condition, dict):
                    continue
                lhs_name = condition.get("lhs")
                rhs_name = condition.get("rhs")
                lhs_type = resolve_field_data_type(by_id, left_input, str(lhs_name or ""))
                rhs_type = resolve_field_data_type(by_id, right_input, str(rhs_name or ""))
                if lhs_type and rhs_type and lhs_type != rhs_type:
                    errors.append(
                        f"Blend `{node_label(node)}` joins `{lhs_name}` ({lhs_type}) to `{rhs_name}` ({rhs_type}) "
                        "with mismatched data types; the join will silently produce zero matches at runtime. "
                        "Standardize both key fields to the same type at the source adapter (join keys should "
                        "reach the join as text) before importing."
                    )
            if len(inlets) == 2:
                inlet_positions: list[tuple[int, float, str]] = []
                for inlet in inlets:
                    idx = inlet_index(inlet.get("id"))
                    refs = inlet_source_refs(inlet)
                    if idx is None or not refs:
                        continue
                    source_node = by_id.get(refs[0][0])
                    source_pos = absolute_position(source_node, by_id) if source_node else None
                    if source_pos:
                        inlet_positions.append((idx, source_pos[1], node_label(source_node)))
                if len(inlet_positions) == 2:
                    by_port = sorted(inlet_positions, key=lambda item: item[0])
                    by_y = sorted(inlet_positions, key=lambda item: item[1])
                    if [item[2] for item in by_port] != [item[2] for item in by_y]:
                        warnings.append(
                            f"Blend `{node_label(node)}` has input-port order opposite the vertical source order; "
                            "inspect for crossing connectors and swap inputs only with an equivalent retained-region/config update."
                        )
        if node_type in {"filter", "pdfilter"}:
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            lookup = config.get("dataFilterLookUp")
            if isinstance(lookup, dict) and lookup.get("type") == "logical" and "arguments" in lookup and "children" not in lookup:
                errors.append(
                    f"Filter `{node_label(node)}` uses `dataFilterLookUp.arguments` for a logical filter. "
                    "Real Savant filter JSON uses `children`; `arguments` can render as a broken filter."
                )
            for step in as_list((config.get("pipeline") or {}).get("steps") if isinstance(config.get("pipeline"), dict) else None):
                if not isinstance(step, dict) or step.get("transform") != "logical":
                    continue
                parameters = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
                if isinstance(parameters.get("extra_args"), int):
                    errors.append(
                        f"Filter `{node_label(node)}` has a logical pipeline step with integer `extra_args`. "
                        "Use the proven filter pipeline shape from examples, where `extra_args` is an array."
                    )

    unsupported_tokens = unsupported_expression_tokens(registry)
    for value in walk(workflow):
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        matched = sorted(token for token in unsupported_tokens if token in lowered)
        if matched:
            rendered = ", ".join(f"`{token}`" for token in matched)
            errors.append(f"Workflow references unsupported expression token(s) {rendered}; use supported registry alternatives.")
            break

    text_nodes = [n for n in by_id.values() if n.get("type") == "text"]
    group_nodes = [n for n in by_id.values() if n.get("type") == "group"]
    substantial_nodes = [
        n for n in by_id.values()
        if n.get("type") not in {"group", "text", "outlet"} and not str(n.get("id", "")).endswith("|0")
    ]
    if len(substantial_nodes) >= 8 and not group_nodes:
        warnings.append(
            "Workflow has many nodes but no semantic group nodes; add stage groups with text headers so a new user can scan the flow."
        )
    if len(substantial_nodes) >= 8 and len(group_nodes) == 1:
        visual_children = group_visual_children(group_nodes[0], substantial_nodes, by_id)
        coverage = len(visual_children) / len(substantial_nodes) if substantial_nodes else 0
        categories = visual_stage_categories(visual_children)
        if coverage > 0.70:
            errors.append(
                f"Workflow has one catch-all visual group containing {len(visual_children)} of "
                f"{len(substantial_nodes)} substantial workflow nodes. Canvas layout rules require semantic stage "
                "groups, not one wrapper around most of the process."
            )
        if {"source", "prep", "enrichment", "output"}.issubset(categories):
            errors.append(
                f"Group `{group_nodes[0].get('id')}` mixes inputs, preparation, enrichment/joining, and final output. "
                "Split the canvas into semantic stage groups so each group frames only the work for that stage."
            )
    group_bounds_by_id = {
        str(group.get("id")): bounds
        for group in group_nodes
        if isinstance(group.get("id"), str)
        for bounds in [group_bounds(group, by_id)]
        if bounds is not None
    }
    for node in substantial_nodes:
        node_id = str(node.get("id") or "")
        center = node_center(node, by_id)
        if center is None:
            continue
        assigned_parent = parent_id(node)
        if assigned_parent:
            bounds = group_bounds_by_id.get(assigned_parent)
            if bounds is not None and not point_inside_padded_bounds(center, bounds, GROUP_VISUAL_MEMBERSHIP_PADDING):
                warnings.append(
                    f"Node `{node_label(node)}` is assigned to group `{assigned_parent}` but its saved position is outside "
                    "that group. Move the node inside the group or remove the group membership before import."
                )
            continue
        containing_groups = [
            group_id
            for group_id, bounds in group_bounds_by_id.items()
            if point_inside_padded_bounds(center, bounds, GROUP_VISUAL_MEMBERSHIP_PADDING)
        ]
        if containing_groups:
            warnings.append(
                f"Node `{node_label(node)}` visually sits inside group `{containing_groups[0]}` but is not assigned to that group. "
                "Set `canvasConfig.parentId`/`extent` or move it outside the group so the rendered canvas matches the JSON."
            )
    for group in group_nodes:
        group_id = group.get("id")
        headers = [n for n in text_nodes if n.get("canvasConfig", {}).get("parentId") == group_id]
        if not headers:
            warnings.append(f"Group `{group_id}` has no text header.")
            continue
        header = sorted(
            headers,
            key=lambda n: ((n.get("position") or {}).get("y", 999999), (n.get("position") or {}).get("x", 999999)),
        )[0]
        plain = text_plain(header)
        rendered = text_rendered_plain(header)
        if plain and not rendered:
            errors.append(
                f"Group `{group_id}` header `{plain}` has empty rendered rich text. "
                "Savant renders text nodes from `config.text`, not just `config.inputText`; populate both fields."
            )
        elif plain and rendered:
            missing_lines = [
                line
                for line in (line.strip() for line in plain.splitlines())
                if line and line not in rendered
            ]
            if missing_lines:
                errors.append(
                    f"Group `{group_id}` header rendered text does not match `inputText`; missing "
                    f"{', '.join(repr(line) for line in missing_lines[:3])}. Keep `config.text` and "
                    "`config.inputText` semantically in sync."
                )
        content_lines = [line.strip() for line in plain.splitlines() if line.strip()]
        if len(content_lines) < 2:
            warnings.append(f"Group `{group_id}` header `{plain or header.get('id')}` has no description line.")
        if len(plain) < MIN_GROUP_HEADER_CHARS:
            warnings.append(f"Group `{group_id}` header is too short to explain the stage purpose.")
        config = header.get("config") if isinstance(header.get("config"), dict) else {}
        group_width = (group.get("config") or {}).get("width") if isinstance(group.get("config"), dict) else None
        header_width = config.get("width")
        header_x = (header.get("position") or {}).get("x")
        if isinstance(group_width, (int, float)) and isinstance(header_width, (int, float)) and header_width < group_width * 0.9:
            warnings.append(f"Group `{group_id}` header is not using the full group width.")
        if isinstance(header_x, (int, float)) and abs(header_x) > 2:
            warnings.append(f"Group `{group_id}` header x-position is not aligned to the group left edge.")

        header_height = number(config.get("height"))
        if len(content_lines) >= 2 and header_height is not None and header_height < GROUP_HEADER_TEXT_MIN_HEIGHT:
            warnings.append(f"Group `{group_id}` header height is too small for a title plus description.")

        children = [
            n
            for n in by_id.values()
            if n.get("canvasConfig", {}).get("parentId") == group_id and n.get("type") not in {"text", "group"}
        ]
        workflow_children = grouped_workflow_children(workflow, str(group_id))
        readable_children = grouped_readable_children(workflow, str(group_id))
        has_external_input = any(
            target in {str(child.get("id") or "") for child in children}
            and parent_id(by_id.get(src, {})) != str(group_id)
            for src, targets in adjacency.items()
            for target in targets
        )
        column_count = clustered_column_count(readable_children)
        label_columns = horizontal_label_columns(readable_children)
        for left_column, right_column in zip(label_columns, label_columns[1:]):
            left_x, left_label_width, left_label = left_column
            right_x, right_label_width, right_label = right_column
            required_gap = (left_label_width / 2) + (right_label_width / 2) + NODE_LABEL_GUTTER_MIN
            actual_gap = right_x - left_x
            if actual_gap < required_gap:
                warnings.append(
                    f"Group `{group_id}` visible columns for `{left_label}` and `{right_label}` are too close for their label sizes; "
                    "increase internal spacing or group width before optimizing centering."
                )
        if isinstance(group_width, (int, float)) and column_count:
            min_width, max_width = expected_group_width_for_columns(column_count)
            label_width_bounds = expected_group_width_for_label_columns(label_columns)
            if label_width_bounds is not None:
                min_width = max(min_width, label_width_bounds[0])
                max_width = max(max_width, label_width_bounds[1])
            if group_width < min_width:
                warnings.append(
                    f"Group `{group_id}` is narrow for its {column_count} horizontal workflow columns and visible label lengths; "
                    "increase width or reduce column crowding so labels and connector ports have room."
                )
            if group_width > max_width:
                if not has_external_input:
                    warnings.append(
                        f"Group `{group_id}` is much wider than expected for its {column_count} horizontal workflow columns and visible label lengths; "
                        "shrink excess whitespace unless it is intentionally reserving routing space."
                    )
            content_bounds = horizontal_content_bounds(readable_children)
            if content_bounds:
                content_left, content_right = content_bounds
                left_padding = content_left
                right_padding = group_width - content_right
                reserved_landing_lane = has_external_input and left_padding > right_padding
                if (
                    min(left_padding, right_padding) >= 0
                    and abs(left_padding - right_padding) > GROUP_CONTENT_CENTERING_TOLERANCE
                    and not reserved_landing_lane
                ):
                    warnings.append(
                        f"Group `{group_id}` workflow nodes are not horizontally centered; "
                        "adjust internal node positions so left and right padding are balanced."
                    )
        child_ys = [
            number((child.get("position") or {}).get("y"))
            for child in children
            if isinstance(child.get("position"), dict)
        ]
        child_ys = [y for y in child_ys if y is not None]
        if child_ys and min(child_ys) < GROUP_HEADER_BAND_MIN_Y:
            warnings.append(f"Group `{group_id}` has workflow nodes inside the reserved header band.")
        row_ys: list[float] = []
        for y in sorted(child_ys):
            if not row_ys or abs(y - row_ys[-1]) > APPROX_NODE_HEIGHT / 2:
                row_ys.append(y)
        for upper_y, lower_y in zip(row_ys, row_ys[1:]):
            if lower_y - upper_y < GROUPED_NODE_VERTICAL_ROW_GAP_MIN:
                warnings.append(
                    f"Group `{group_id}` has vertically stacked workflow rows too close for node labels; "
                    "increase row spacing so each step has room for its icon, label, and a small gap."
                )
                break

        group_height = number((group.get("config") or {}).get("height")) if isinstance(group.get("config"), dict) else None
        if group_height is not None and child_ys:
            needed_height = max(child_ys) + APPROX_GROUPED_NODE_VISUAL_HEIGHT + GROUP_BOTTOM_PADDING_MIN
            if group_height < needed_height:
                warnings.append(f"Group `{group_id}` height may be too tight for node labels and bottom padding.")
            excess_height = group_height - needed_height
            has_multiple_lanes = len({round(y) for y in child_ys}) >= 2
            has_branch_or_terminal_children = any(
                child.get("type") in {"outlet", "destination"}
                for child in children
            )
            if (
                excess_height > GROUP_HEIGHT_EXCESS_ALLOWANCE
                and excess_height / max(needed_height, 1) > GROUP_HEIGHT_EXCESS_RATIO
                and not (has_multiple_lanes and has_branch_or_terminal_children)
            ):
                warnings.append(
                    f"Group `{group_id}` has a large empty lower area; shrink it, reserve that space for a branch, "
                    "or keep it only if the same-height peer row is cleaner in the rendered canvas."
                )

        business_lane_children = [
            child
            for child in children
            if child.get("type") != "outlet"
            and any(term in normalized_text(child.get("name")) for term in ("employee", "prec/ic", "prec ic"))
        ]
        business_lane_ys = sorted({
            round(y)
            for y in (
                number((child.get("position") or {}).get("y"))
                for child in business_lane_children
                if isinstance(child.get("position"), dict)
            )
            if y is not None
        })
        if len(business_lane_ys) >= 2:
            gaps = [b - a for a, b in zip(business_lane_ys, business_lane_ys[1:])]
            if gaps and min(gaps) < PARALLEL_BUSINESS_LANE_MIN_GAP:
                warnings.append(
                    f"Group `{group_id}` has compressed parallel business lanes; add vertical space so Employee and PREC/IC paths do not visually merge."
                )
            if group_height is not None and group_height < PARALLEL_BUSINESS_GROUP_MIN_HEIGHT:
                warnings.append(
                    f"Group `{group_id}` is short for multiple business lanes; make the container taller so shared-input routes have empty space."
                )

    group_metrics: list[dict[str, float | str | int]] = []
    for group in group_nodes:
        pos = group.get("position") if isinstance(group.get("position"), dict) else {}
        config = group.get("config") if isinstance(group.get("config"), dict) else {}
        x = number(pos.get("x"))
        y = number(pos.get("y"))
        width = number(config.get("width"))
        height = number(config.get("height"))
        if x is None or y is None or width is None or height is None:
            continue
        group_metrics.append(
            {
                "id": str(group.get("id") or ""),
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "columns": clustered_column_count(grouped_workflow_children(workflow, str(group.get("id") or ""))),
                "empty_ratio": 0.0,
            }
        )
        children = [
            n
            for n in by_id.values()
            if n.get("canvasConfig", {}).get("parentId") == group.get("id") and n.get("type") not in {"text", "group"}
        ]
        child_ys = [
            number((child.get("position") or {}).get("y"))
            for child in children
            if isinstance(child.get("position"), dict)
        ]
        child_ys = [value for value in child_ys if value is not None]
        if child_ys:
            needed_height = max(child_ys) + APPROX_GROUPED_NODE_VISUAL_HEIGHT + GROUP_BOTTOM_PADDING_MIN
            group_metrics[-1]["empty_ratio"] = max(0.0, (height - needed_height) / max(height, 1))
    if len(group_metrics) >= 3:
        # Peer rules apply within a horizontal band of stages. A review/validation
        # band placed below the main flow is not a peer of the main row, so it is
        # clustered separately by vertical overlap instead of being compared by x.
        metrics_by_group_id = {str(item["id"]): item for item in group_metrics}
        band_bounds = {
            gid: (
                float(item["x"]),
                float(item["y"]),
                float(item["x"]) + float(item["width"]),
                float(item["y"]) + float(item["height"]),
            )
            for gid, item in metrics_by_group_id.items()
        }
        for band in layout_metrics.vertical_band_clusters(band_bounds):
            band_metrics = [metrics_by_group_id[gid] for gid in band]
            if len(band_metrics) < 3:
                continue
            sorted_groups = sorted(band_metrics, key=lambda item: float(item["x"]))
            top_values = [float(item["y"]) for item in sorted_groups]
            if max(top_values) - min(top_values) > GROUP_TOP_ALIGNMENT_TOLERANCE:
                warnings.append("Peer stage groups are not top-aligned; align group tops to improve visual rhythm.")
            height_values = [float(item["height"]) for item in sorted_groups]
            if max(height_values) - min(height_values) <= GROUP_HEIGHT_ALIGNMENT_TOLERANCE and max(height_values) >= UNIFORM_LARGE_GROUP_HEIGHT_MIN:
                column_counts = [int(item["columns"]) for item in sorted_groups]
                empty_ratios = [float(item.get("empty_ratio") or 0) for item in sorted_groups]
                if max(column_counts) - min(column_counts) >= 2 and max(empty_ratios) >= UNIFORM_GROUP_EMPTY_RATIO_MIN:
                    warnings.append(
                        "Peer stage groups use the same large height with substantial empty space in at least one group; "
                        "keep the equal-height row only if it looks cleaner than compact or stacked terminal/review groups in the rendered canvas."
                    )
            gutters = [
                float(right["x"]) - (float(left["x"]) + float(left["width"]))
                for left, right in zip(sorted_groups, sorted_groups[1:])
            ]
            overlapping_gutters = [g for g in gutters if g < 0]
            if overlapping_gutters:
                warnings.append(
                    "Peer stage groups overlap horizontally; move or resize adjacent groups so every group has visible separation."
                )
            positive_gutters = [g for g in gutters if g >= 0]
            too_small_gutters = [g for g in positive_gutters if g < GROUP_GUTTER_MIN]
            if too_small_gutters:
                warnings.append(
                    f"Peer stage group gutters are too tight; use at least {GROUP_GUTTER_MIN}px between adjacent groups."
                )
            too_large_gutters = [g for g in positive_gutters if g > GROUP_GUTTER_MAX]
            if too_large_gutters:
                warnings.append(
                    f"Peer stage group gutters are excessive; keep adjacent group spacing at or below {GROUP_GUTTER_MAX}px unless routing requires a documented exception."
                )
            if len(positive_gutters) >= 2 and max(positive_gutters) - min(positive_gutters) > GROUP_GUTTER_ALIGNMENT_TOLERANCE:
                warnings.append("Peer stage groups use inconsistent horizontal gutters; make spacing between adjacent groups regular unless routing requires an exception.")

    visual_nodes = [
        n for n in by_id.values()
        if n.get("type") not in {"group", "text"}
        and absolute_position(n, by_id) is not None
    ]
    for idx, left in enumerate(visual_nodes):
        left_pos = absolute_position(left, by_id)
        if not left_pos:
            continue
        for right in visual_nodes[idx + 1:]:
            right_pos = absolute_position(right, by_id)
            if not right_pos:
                continue
            if abs(left_pos[0] - right_pos[0]) < 96 and abs(left_pos[1] - right_pos[1]) < 72:
                warnings.append(
                    f"Nodes `{node_label(left)}` and `{node_label(right)}` are positioned close enough to risk overlap; "
                    "inspect rendered layout for label or connector collisions."
                )

    for src, targets in adjacency.items():
        src_node = by_id.get(src)
        if not src_node or src_node.get("type") in {"group", "text", "outlet"}:
            continue
        src_pos = absolute_position(src_node, by_id)
        if not src_pos:
            continue
        for target in targets:
            target_node = by_id.get(target)
            if not target_node or target_node.get("type") in {"group", "text", "outlet"}:
                continue
            target_pos = absolute_position(target_node, by_id)
            if not target_pos:
                continue
            src_port = node_output_port(src_node, by_id)
            target_inlet = target_inlet_id(target_node, src)
            target_port = node_input_port(target_node, target_inlet, by_id, src)
            if src_port and target_port:
                port_dx = target_port[0] - src_port[0]
                port_dy = abs(target_port[1] - src_port[1])
                if (
                    port_dx > 0
                    and APPROX_PORT_ALIGNMENT_TOLERANCE < port_dy <= APPROX_PORT_NEAR_MISS_TOLERANCE
                    and parent_id(src_node) == parent_id(target_node)
                ):
                    warnings.append(
                        f"Edge `{node_label(src_node)}` -> `{node_label(target_node)}` has connected handles "
                        "that are close but not aligned; use the node port geometry to put the output and input "
                        "on the same centerline."
                    )
                target_parent = parent_id(target_node)
                src_parent = parent_id(src_node)
                bounds = group_bounds_by_id.get(target_parent)
                if bounds is not None and target_parent and target_parent != src_parent:
                    landing = target_port[0] - bounds[0]
                    if landing < EXTERNAL_INPUT_LANDING_MIN:
                        warnings.append(
                            f"Node `{node_label(target_node)}` receives an input from outside its group with only "
                            f"{int(landing)}px of left-side landing space; move it right or widen/reposition the "
                            "group so the connector has breathing room before the input handle."
                        )
            dx = target_pos[0] - src_pos[0]
            dy = abs(target_pos[1] - src_pos[1])
            if dx > 0 and dx < 500 and dy > 240:
                warnings.append(
                    f"Edge `{node_label(src_node)}` -> `{node_label(target_node)}` spans a large vertical offset over a short distance; "
                    "inspect rendered layout for avoidable doglegs or line crossings."
                )
            if dx > 0 and dx < 900 and 24 < dy < 120 and parent_id(src_node) == parent_id(target_node):
                warnings.append(
                    f"Edge `{node_label(src_node)}` -> `{node_label(target_node)}` has a small same-lane vertical offset; "
                    "align connected nodes to avoid an unnecessary bent connector."
                )
    # Connector-path corridor checks. The shared layout-metrics module models every
    # connector as the rendered bezier between real ports; an edge that passes
    # through an unrelated node body or cuts through a stage frame it does not
    # belong to is exactly what makes a canvas hard to trace.
    connector_metrics = layout_metrics.measure(list(by_id.values()))
    for src_id, target_id, blocker_id in connector_metrics["through_nodes"]:
        warnings.append(
            f"Edge `{node_label(by_id.get(src_id, {}))}` -> `{node_label(by_id.get(target_id, {}))}` routes through "
            f"node `{node_label(by_id.get(blocker_id, {}))}`; move the blocking node or the consuming stage so the "
            "connector path stays in open space."
        )
    for src_id, target_id, group_id in connector_metrics["through_groups"]:
        warnings.append(
            f"Edge `{node_label(by_id.get(src_id, {}))}` -> `{node_label(by_id.get(target_id, {}))}` cuts through "
            f"group `{node_label(by_id.get(group_id, {}))}` it does not belong to; route the connector through the "
            "open gutter between stage bands or move the consuming stage below the main flow."
        )

    for labels, certain in excel_template_overwrite_groups(nodes):
        named = ", ".join(f"`{label}`" for label in labels)
        if certain:
            errors.append(
                f"Excel destinations {named} all set `formatFromTemplate=true` and write to the same workbook. "
                "Each one recreates the workbook from its template, so whichever runs last wipes the tabs the "
                "others wrote — the file imports and runs without error but silently loses tabs/data. Only the "
                "destination that creates the workbook may set `formatFromTemplate=true`; the rest must set it to "
                "false so they add their tabs to the existing workbook."
            )
        else:
            warnings.append(
                f"Excel destinations {named} set `formatFromTemplate=true` and write to what looks like the same "
                "workbook (the file name or subfolder is field-driven, so the target is resolved per row). If they "
                "resolve to the same workbook at run time, each recreates it from its template and the last to run "
                "wipes the others' tabs. Only the workbook's creator should set `formatFromTemplate=true`; confirm "
                "the field-driven paths cannot collide, or set the flag to false on the tab-writers."
            )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_json", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Compatibility no-op. Warnings are nonblocking by default; use --strict to block on warnings.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return failure when warnings are present, even if there are no errors.",
    )
    parser.add_argument(
        "--block-mergeable-pairs",
        action="store_true",
        help=(
            "Treat strict adjacent Transform/filter pairs as errors. Builder uses this so "
            "multi-operation tools are consolidated before handoff; routine validation keeps "
            "them as warnings for existing/live workflows."
        ),
    )
    parser.add_argument(
        "--block-documentation-gaps",
        action="store_true",
        help=(
            "Treat node-description coverage gaps as errors. Builder uses this so generated "
            "steps explain the material config instead of shipping generic descriptions."
        ),
    )
    parser.add_argument(
        "--required-tag",
        help="Require a top-level workflow tag, such as the versioned Savvy tracking tag `Savvy v0.0.1`.",
    )
    parser.add_argument(
        "--schema-hints",
        type=Path,
        default=None,
        help=(
            "Optional validator-only JSON sidecar mapping node id or node name to the "
            "expected output columns for AI components (vision/gen_ai/fuzzy_match) whose "
            "output schema is not knowable at design time. Lets downstream column checks "
            "run against the declared schema. This file is never part of the workflow JSON."
        ),
    )
    parser.add_argument(
        "--show-schema",
        metavar="NODE_ID_OR_NAME",
        help="Print the validator's resolved output schema for one node and exit.",
    )
    args = parser.parse_args()

    schema_hints: dict[str, Any] | None = None
    if args.schema_hints is not None:
        try:
            loaded_hints = json.loads(args.schema_hints.read_text())
        except Exception as exc:  # noqa: BLE001 - CLI should report read/parse failures plainly.
            print(f"FAIL: cannot read --schema-hints file `{args.schema_hints}`: {exc}")
            return 1
        if not isinstance(loaded_hints, dict):
            print("FAIL: --schema-hints file must be a JSON object mapping node id/name to a list of column names.")
            return 1
        schema_hints = loaded_hints

    if args.show_schema:
        try:
            workflow = json.loads(args.workflow_json.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: cannot read workflow JSON `{args.workflow_json}`: {exc}")
            return 1
        schemas = infer_output_schemas(workflow, schema_hints=schema_hints)
        target = args.show_schema
        schema = schemas.get(target)
        if schema is None:
            matches = [item for item in schemas.values() if item.get("name") == target]
            if len(matches) == 1:
                schema = matches[0]
        if schema is None:
            print(f"FAIL: no node found for `{target}`.")
            return 1
        if args.json:
            print(json.dumps(schema, indent=2))
        else:
            known = "known" if schema.get("known") else "unknown"
            print(f"{schema['name']} ({schema['id']}, {schema.get('type')}): {known} schema")
            for column in schema.get("columns") or []:
                print(f"- {column}")
        return 0

    errors, warnings = validate(
        args.workflow_json,
        required_tag=args.required_tag,
        schema_hints=schema_hints,
        block_mergeable_pairs=args.block_mergeable_pairs,
        block_documentation_gaps=args.block_documentation_gaps,
    )
    warnings_block = bool(warnings and args.strict)
    result = {
        "path": str(args.workflow_json),
        "ok": not errors and not warnings_block,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "warnings_blocking": warnings_block,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"{status}: {args.workflow_json}")
        for error in errors:
            print(f"ERROR: {error}")
        for warning in warnings:
            print(f"WARN: {warning}")

    if errors:
        return 1
    if warnings_block:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
