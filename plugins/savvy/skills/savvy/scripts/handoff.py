#!/usr/bin/env python3
"""Create and validate stage handoff envelopes.

A handoff is a single JSON file passed between Savant workflow stages. It hides
the fragmented checkpoint/evidence storage shape from the agent while preserving
the same validator-backed gates.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import handoff_sections  # noqa: E402
from savant_api.fileio import workspace_tmp  # noqa: E402
from validators import stage_gate  # noqa: E402


HANDOFF_TYPES = {"planner-to-builder", "builder-to-creator"}
DEFAULT_FILENAMES = {
    "planner-to-builder": "planner_to_builder.handoff.json",
    "builder-to-creator": "builder_to_creator.handoff.json",
}
TYPE_ALIASES = {value.replace("-", "_"): value for value in HANDOFF_TYPES}
TYPE_ALIASES.update({value: value for value in HANDOFF_TYPES})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_type(value: str) -> str:
    normalized = TYPE_ALIASES.get(value.strip())
    if normalized is None:
        raise ValueError(f"Unknown handoff type `{value}`. Choose from: {', '.join(sorted(HANDOFF_TYPES))}.")
    return normalized


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("Task name must contain at least one letter or number.")
    return slug


def task_path(task: str, filename: str) -> Path:
    return workspace_tmp(_slug(task), filename)


def default_handoff_path(handoff_type: str, task: str) -> Path:
    resolved = normalize_type(handoff_type)
    return task_path(task, DEFAULT_FILENAMES[resolved])


def _base(handoff_type: str) -> dict[str, Any]:
    producer, consumer = handoff_type.split("-to-", 1)
    return {
        "handoff_type": handoff_type.replace("-", "_"),
        "handoff_version": 1,
        "created_at": _now(),
        "producer": producer,
        "consumer": consumer,
        "status": "draft",
        "validity": {
            "invalid_if_user_changes": [],
            "notes": [],
        },
        "artifacts": {},
        "sections": {},
    }


def scaffold(handoff_type: str, *, stage: str | None = None) -> dict[str, Any]:
    resolved = normalize_type(handoff_type)
    handoff = _base(resolved)
    if resolved == "planner-to-builder":
        planner_stage = stage or "questions_needed"
        handoff["sections"] = {
            "planner_intake": handoff_sections.scaffold("planner_intake", planner_stage),
            "builder_preflight": handoff_sections.scaffold("builder_preflight", "ready"),
        }
        handoff["validity"]["invalid_if_user_changes"] = [
            "workflow purpose",
            "input dataset",
            "source schema",
            "output destination",
            "output grain",
            "final columns",
            "business process plan",
        ]
        handoff["next_stage_required_gate"] = {
            "role": "builder",
            "gate": "precheck",
        }
    elif resolved == "builder-to-creator":
        handoff["artifacts"] = {
            "workflow_json": "",
            "schema_hints": None,
            "required_tag": "",
        }
        handoff["sections"] = {
            "builder_preflight": handoff_sections.scaffold("builder_preflight", "ready"),
            "creator_preflight": handoff_sections.scaffold("creator_preflight", stage or "ready"),
        }
        handoff["validity"]["invalid_if_user_changes"] = [
            "workflow JSON",
            "schema hints",
            "source dataset id",
            "target folder",
            "requested scope",
            "business logic",
        ]
        handoff["next_stage_required_gate"] = {
            "role": "creator",
            "gate": "precheck",
        }
    return handoff


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Handoff JSON must be an object.")
    return value


def _write_json(value: dict[str, Any], path: Path | None) -> None:
    text = json.dumps(value, indent=2) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(path)


def _validate(args: argparse.Namespace) -> int:
    try:
        handoff = _load_json(args.handoff_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "ok": False,
            "status": "blocked",
            "checks": [{"name": "handoff_json", "ok": False, "detail": str(exc)}],
            "nextActions": [str(exc)],
        }
        _write_json(result, args.output_path)
        return 1

    result = stage_gate.evaluate(
        args.role,
        args.gate,
        handoff,
        api_check=args.api_check,
        workflow_json=args.workflow_json,
        claim=args.claim,
        required_tag=args.required_tag,
    )
    _write_json(result, args.output_path)
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scaffold = sub.add_parser("scaffold", help="Emit a handoff JSON scaffold.")
    p_scaffold.add_argument("handoff_type", choices=sorted(HANDOFF_TYPES))
    p_scaffold.add_argument("--stage", help="Optional lifecycle stage for the active evidence section.")
    p_scaffold.add_argument("--output-path", type=Path, help="Optional path to write the handoff JSON.")
    p_scaffold.add_argument("--task", help="Task name used to write under tmp/<ai-session-id>/<task-slug>/.")

    p_task_path = sub.add_parser("task-path", help="Print a session-scoped task artifact path.")
    p_task_path.add_argument("task")
    p_task_path.add_argument("filename")

    p_validate = sub.add_parser("validate", help="Validate a handoff through the unified stage gate.")
    p_validate.add_argument("handoff_json", type=Path)
    p_validate.add_argument("--role", choices=sorted(stage_gate.ROLES), required=True)
    p_validate.add_argument("--gate", choices=sorted(stage_gate.GATES), required=True)
    p_validate.add_argument("--api-check", choices=["auto", "required", "skip"], default="auto")
    p_validate.add_argument("--workflow-json", type=Path)
    p_validate.add_argument("--required-tag")
    p_validate.add_argument("--claim", choices=["done", "qualified"])
    p_validate.add_argument("--output-path", type=Path)

    args = parser.parse_args()
    if args.command == "scaffold":
        try:
            value = scaffold(args.handoff_type, stage=args.stage)
            output_path = args.output_path
            if args.task:
                if output_path is not None:
                    print("Use either --task or --output-path, not both.", file=sys.stderr)
                    return 2
                output_path = default_handoff_path(args.handoff_type, args.task)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _write_json(value, output_path)
        return 0
    if args.command == "task-path":
        try:
            print(task_path(args.task, args.filename))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "validate":
        return _validate(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
