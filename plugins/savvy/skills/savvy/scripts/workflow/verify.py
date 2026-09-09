#!/usr/bin/env python3
"""Verify a write landed, from the recipe the caller re-fetched through MCP.

Every write route used to read its own result back over `GET /api/recipes/{id}` and check it
in-process. That read is gone, so the write and the verification are now two steps with an MCP
fetch between them:

    workflow create --confirm-import ...        # returns flowId + flowUrl, no read-back
    fetch savant://workflow/{flowId}  -> after.json
    workflow verify --operation create --workflow-json after.json --expect-folder-id <id> ...

The checks themselves are unchanged — same folder comparison, same node-count/name persistence
test, same before/after model diff, same file-based validation. Only where the recipe comes from
changed.

**This route is the write path's verification gate, and it is a separate command, so it can be
skipped in a way the old in-process read-back could not.** A create or edit is not reportable as
verified until this has run and returned ok. `workflow create` and `workflow edit` both print the
exact command to run next, so the follow-up is mechanical rather than remembered.

Needs no API access: it reads files only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from savant_api.fileio import save_json, workspace_tmp  # noqa: E402
from savant_api.models import SavantAppApiError  # noqa: E402
from savant_api.recipe_input import assert_flow_id, load_recipe  # noqa: E402
from savant_api.recipes import diff_has_changes, recipe_model_diff, recipe_nodes  # noqa: E402
from validators import workflow as workflow_validator  # noqa: E402
from workflow.inspection import persistence_check  # noqa: E402


OPERATIONS = ("create", "edit", "metadata")

# None and "" both mean the Home folder (namespace root); normalize before comparing so a
# Home-folder create does not read as a mismatch against the other spelling.
def _folder(value: Any) -> str | None:
    return (value or None) if isinstance(value, (str, type(None))) else None


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail}


def verify(
    *,
    operation: str,
    recipe: dict[str, Any],
    recipe_path: Path,
    expect_flow_id: str | None = None,
    expect_folder_id: str | None = None,
    source_json: Path | None = None,
    before_json: Path | None = None,
    expect_metadata_json: Path | None = None,
    block_documentation_gaps: bool = False,
) -> dict[str, Any]:
    if operation not in OPERATIONS:
        raise SavantAppApiError(f"--operation must be one of {', '.join(OPERATIONS)}; got `{operation}`.")
    assert_flow_id(recipe, expect_flow_id)
    checks: list[dict[str, Any]] = []
    flow_id = recipe.get("id") if isinstance(recipe.get("id"), str) else expect_flow_id

    # 1. The write reached the flow the caller targeted. assert_flow_id already raised on a
    # mismatch; this records the positive result so the report is self-contained evidence.
    if expect_flow_id:
        checks.append(_check("flow-id", True, f"re-fetched recipe is flow `{expect_flow_id}`"))

    # 2. Folder placement (create). A workflow that imported into the wrong folder exists and
    # validates, so nothing else here would catch it.
    if operation == "create" and expect_folder_id is not None:
        want, got = _folder(expect_folder_id), _folder(recipe.get("folderId"))
        checks.append(_check(
            "folder", want == got,
            f"requested `{want or '(Home folder)'}`, created in `{got or '(Home folder)'}`",
        ))

    # 3. Persistence against the JSON that was imported. Import remaps node ids but preserves
    # names, so this compares counts and name multisets — an AI node silently dropped for an
    # unresolved providerId shows up here and only here.
    if source_json is not None:
        imported = json.loads(source_json.read_text(encoding="utf-8"))
        imported_nodes = [n for n in (imported.get("nodes") or []) if isinstance(n, dict)]
        live_nodes = [n for n in recipe_nodes(recipe) if isinstance(n, dict)]
        ok, detail = persistence_check(imported_nodes, live_nodes)
        checks.append(_check("persistence", ok, detail))

    # 4. The edit actually persisted: the pre-edit recipe vs what came back. A save that returns
    # 200 but changes nothing is the failure this catches.
    persisted_diff = None
    if before_json is not None:
        before = load_recipe(before_json, flag="--before-json")
        assert_flow_id(before, flow_id, flag="--before-json")
        persisted_diff = recipe_model_diff(before, recipe)
        changed = diff_has_changes(persisted_diff)
        checks.append(_check(
            "persisted-diff", changed,
            "read-back differs from the pre-edit recipe" if changed
            else "read-back is identical to the pre-edit recipe, so the save did not persist",
        ))

    # 5. Metadata fields, for the name/description/tags save path.
    if expect_metadata_json is not None:
        desired = json.loads(expect_metadata_json.read_text(encoding="utf-8"))
        if not isinstance(desired, dict):
            raise SavantAppApiError("--expect-metadata-json must point to a JSON object.")
        for field in ("name", "description", "tags"):
            if field not in desired:
                continue
            want, got = desired.get(field), recipe.get(field)
            checks.append(_check(
                f"metadata:{field}", want == got,
                f"requested {want!r}, persisted {got!r}" if want != got else f"persisted {field} matches",
            ))

    # 6. File-based validation of what actually landed, including the layout checks.
    errors, warnings = workflow_validator.validate(
        recipe_path, block_documentation_gaps=block_documentation_gaps
    )
    checks.append(_check(
        "validation", not errors,
        f"{len(errors)} error(s), {len(warnings)} warning(s)",
    ))

    failed = [c["check"] for c in checks if not c["ok"]]
    return {
        "operation": operation,
        "flowId": flow_id,
        "recipePath": str(recipe_path),
        "nodeCount": len(recipe_nodes(recipe)),
        "checks": checks,
        "failedChecks": failed,
        "validationErrors": errors,
        "validationWarnings": warnings,
        "persistedDiff": persisted_diff,
        "ok": not failed,
    }


def print_summary(report: dict[str, Any]) -> None:
    verdict = "VERIFIED" if report["ok"] else "FAILED"
    print(f"{verdict}: {report['operation']} of flow {report.get('flowId')} "
          f"({report['nodeCount']} node(s))")
    for check in report["checks"]:
        print(f"  [{'ok' if check['ok'] else 'FAIL'}] {check['check']}: {check['detail']}")
    if not report["ok"]:
        print("")
        print(f"Failed checks: {', '.join(report['failedChecks'])}")
        print("Do NOT report this write as verified.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--operation", required=True, choices=list(OPERATIONS),
                   help="Which write is being verified.")
    p.add_argument("--workflow-json", type=Path, required=True,
                   help="The post-write recipe, fetched with the MCP `fetch` tool on "
                        "savant://workflow/{flowId}.")
    p.add_argument("--expect-flow-id", help="Flow id the write targeted; mismatch is a hard failure.")
    p.add_argument("--expect-folder-id", help="Folder id the create requested; omit or pass an empty "
                                              "string for the Home folder.")
    p.add_argument("--source-json", type=Path,
                   help="The workflow JSON that was imported (create persistence check).")
    p.add_argument("--before-json", type=Path,
                   help="The pre-edit recipe (edit persisted-diff check).")
    p.add_argument("--expect-metadata-json", type=Path,
                   help="The metadata that was saved (name/description/tags check).")
    p.add_argument("--block-documentation-gaps", action="store_true",
                   help="Treat missing node documentation as a validation error.")
    p.add_argument("--output-path", type=Path, help="Where to write the verification JSON.")
    p.add_argument("--json-only", action="store_true", help="Print the report path only.")
    args = p.parse_args(argv)

    try:
        recipe = load_recipe(args.workflow_json)
        report = verify(
            operation=args.operation,
            recipe=recipe,
            recipe_path=args.workflow_json,
            expect_flow_id=args.expect_flow_id,
            expect_folder_id=args.expect_folder_id,
            source_json=args.source_json,
            before_json=args.before_json,
            expect_metadata_json=args.expect_metadata_json,
            block_documentation_gaps=args.block_documentation_gaps,
        )
    except SavantAppApiError as exc:
        print(f"workflow verify: {exc}", file=sys.stderr)
        return 2
    output = args.output_path or workspace_tmp(
        "workflow-verify", f"{report.get('flowId') or 'unknown'}.{args.operation}.verify.json"
    )
    save_json(report, output)
    if args.json_only:
        print(output)
    else:
        print_summary(report)
        print("")
        print(f"Wrote verification JSON to {output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"workflow_verify: {exc}", file=sys.stderr)
        raise SystemExit(2)
