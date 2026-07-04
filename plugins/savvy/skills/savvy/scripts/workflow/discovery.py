#!/usr/bin/env python3
"""Discover candidate Savant datasets for workflow source placeholders.

This helper is intentionally local and deterministic: it consumes a workflow
JSON plus a previously captured Savant source list, then emits source-match
evidence suitable for Creator preflight. It does not call Savant APIs itself;
capture the visible dataset list first via the MCP `search(types=["source"])`
results, or use `savant.py app <url> --discover-source-matches` (which lists
sources for you).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.fileio import save_json, workspace_tmp  # noqa: E402


WORD_RE = re.compile(r"[a-z0-9]+")


def normalize(value: Any) -> str:
    return " ".join(WORD_RE.findall(str(value or "").casefold()))


def tokens(value: Any) -> set[str]:
    return set(WORD_RE.findall(str(value or "").casefold()))


def source_display_name(node: dict[str, Any]) -> str:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    for value in (node.get("name"), config.get("name"), config.get("id")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(node.get("id") or "source")


def field_names_from_value(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        for key in ("name", "id", "fieldName", "fieldId"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                names.add(normalize(item))
        for child_key in ("fields", "schema", "selected", "columns"):
            names.update(field_names_from_value(value.get(child_key)))
    elif isinstance(value, list):
        for item in value:
            names.update(field_names_from_value(item))
    elif isinstance(value, str) and value.strip():
        names.add(normalize(value))
    return {name for name in names if name}


def workflow_source_specs(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return specs
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "source":
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        expected_fields = field_names_from_value(config)
        specs.append(
            {
                "node_id": node.get("id"),
                "source_name": source_display_name(node),
                "local_path": _local_path_for_source(workflow, source_display_name(node)),
                "expected_fields": sorted(expected_fields),
            }
        )
    return specs


def _local_path_for_source(workflow: dict[str, Any], source_name: str) -> str | None:
    parameters = workflow.get("parameters")
    source_files: list[Any] = []
    if isinstance(parameters, dict) and isinstance(parameters.get("sourceFiles"), list):
        source_files = parameters["sourceFiles"]
    for item in source_files:
        if not isinstance(item, dict):
            continue
        dataset_name = item.get("datasetName")
        local_path = item.get("localPath")
        if isinstance(dataset_name, str) and normalize(dataset_name) == normalize(source_name):
            return local_path if isinstance(local_path, str) else None
    return None


def dataset_name(dataset: dict[str, Any]) -> str:
    for key in ("name", "sourceName", "displayName"):
        value = dataset.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = dataset.get("id")
    return value if isinstance(value, str) else ""


def dataset_fields(dataset: dict[str, Any]) -> set[str]:
    names = field_names_from_value(
        {
            "fields": dataset.get("fields"),
            "schema": dataset.get("schema"),
            "config": dataset.get("config"),
        }
    )
    return {name for name in names if name}


def score_dataset(source_name: str, expected_fields: set[str], dataset: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    name = dataset_name(dataset)
    source_norm = normalize(source_name)
    dataset_norm = normalize(name)
    source_tokens = tokens(source_name)
    dataset_tokens = tokens(name)
    field_hits = sorted(expected_fields & dataset_fields(dataset))
    methods: list[str] = []
    score = 0.0

    if source_norm and dataset_norm and source_norm == dataset_norm:
        score += 100
        methods.append("exact")

    source_stem = normalize(Path(source_name).stem)
    if source_stem and dataset_norm and source_stem == dataset_norm:
        score += 90
        methods.append("normalized_name")
    elif source_tokens and dataset_tokens:
        overlap = source_tokens & dataset_tokens
        if overlap:
            score += 20 * (len(overlap) / len(source_tokens | dataset_tokens))
            methods.append("normalized_name")
        if source_stem and (source_stem in dataset_norm or dataset_norm in source_stem):
            score += 35
            if "normalized_name" not in methods:
                methods.append("normalized_name")

    if field_hits:
        score += min(30, len(field_hits) * 5)
        methods.append("schema_signal")

    return score, methods, field_hits


def discover_candidates(
    source_spec: dict[str, Any],
    datasets: list[dict[str, Any]],
    *,
    limit: int = 10,
    min_score: float = 1.0,
) -> dict[str, Any]:
    source_name = str(source_spec.get("source_name") or "")
    expected_fields = set(source_spec.get("expected_fields") or [])
    scored: list[tuple[float, list[str], list[str], dict[str, Any]]] = []
    all_methods = {"exact", "normalized_name"}
    if expected_fields:
        all_methods.add("schema_signal")

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        score, methods, field_hits = score_dataset(source_name, expected_fields, dataset)
        if score >= min_score:
            scored.append((score, methods, field_hits, dataset))

    scored.sort(key=lambda item: (-item[0], dataset_name(item[3]).casefold()))
    candidates = []
    for score, methods, field_hits, dataset in scored[:limit]:
        candidates.append(
            {
                "id": dataset.get("id") or dataset.get("sourceId"),
                "name": dataset_name(dataset),
                "connector": dataset.get("connector") or dataset.get("type"),
                "score": round(score, 3),
                "matched_by": methods,
                "field_hits": field_hits,
            }
        )

    exact_candidates = [candidate for candidate in candidates if "exact" in candidate.get("matched_by", [])]
    if len(exact_candidates) == 1:
        match_status = "matched"
        selected = exact_candidates[0]
    elif candidates:
        match_status = "ambiguous"
        selected = None
    else:
        match_status = "missing"
        selected = None

    result = {
        "node_id": source_spec.get("node_id"),
        "source_name": source_name,
        "match_status": match_status,
        "dataset_search": {
            "status": "passed",
            "methods": sorted(all_methods),
            "candidates": candidates,
        },
    }
    if source_spec.get("local_path"):
        result["local_path"] = source_spec["local_path"]
    if selected:
        result["matched_dataset_id"] = selected["id"]
        result["matched_dataset_name"] = selected["name"]
    return result


def build_discovery_report(workflow: dict[str, Any], datasets: list[dict[str, Any]], *, limit: int = 10) -> dict[str, Any]:
    specs = workflow_source_specs(workflow)
    return {
        "status": "passed",
        "source_count": len(datasets),
        "sources": [discover_candidates(spec, datasets, limit=limit) for spec in specs],
    }


def default_output_path(workflow_json: Path) -> Path:
    label = workflow_json.stem or "workflow"
    return workspace_tmp("source-matches", f"{label}.source-matches.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-json", type=Path, required=True)
    parser.add_argument("--sources-json", type=Path, required=True)
    parser.add_argument(
        "--output-path",
        type=Path,
        help="Where to write the dataset discovery report. Defaults to workspace tmp/source-matches/.",
    )
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)

    workflow = json.loads(args.workflow_json.read_text(encoding="utf-8"))
    datasets = json.loads(args.sources_json.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise SystemExit("workflow JSON must be an object")
    if not isinstance(datasets, list):
        raise SystemExit("sources JSON must be an array")
    report = build_discovery_report(workflow, datasets, limit=args.limit)
    output_path = args.output_path or default_output_path(args.workflow_json)
    save_json(report, output_path)
    print(f"Wrote dataset discovery report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
