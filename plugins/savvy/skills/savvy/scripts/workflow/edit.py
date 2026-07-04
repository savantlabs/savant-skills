#!/usr/bin/env python3
"""Editor orchestrator — the deterministic save-and-verify loop around an in-memory recipe edit.

The LLM is the intelligence hub; this tool does the mechanical work and hands structured data
back at each judgment boundary. Two phases, with the confirm gate between them (mirrors
`workflow create`):

  PROPOSE (default): fetch the live recipe, capture a rollback snapshot, diff it against the
  proposed recipe the caller built (via `recipe_edit` / `node_builders`), and validate. It does
  NOT save. Returns the `recipe_model_diff` + validation so the LLM/user can review and confirm.

  COMMIT (--confirm): save the proposed recipe (`PUT /api/recipes`), re-fetch, report the persisted
  diff, write the post-save recipe JSON to the standard session folder, then run the SHARED
  Inspector (`workflow.inspection.inspect` — the same verify process the Creator uses) over the
  caller-chosen `--checkpoint` nodes, and return the verification report. Layout quality is judged
  from `validate workflow` (which runs the deterministic layout checks) on the persisted JSON — no
  rendered-canvas inspection.

The proposal comes from exactly one of two inputs: `--proposed-recipe` (a live-shaped edited
recipe) or `--replace-from-build` (creation-shaped Builder output applied to THIS flow in place —
the rebuild-in-place path that replaces a second import after a failed verification; the rebuilt
content is merged onto the live identity envelope and the same content blockers as create
preflight run before save).

Control points the LLM owns: form the edit, resolve any propagation gaps, confirm the edit scope
between phases, and decide the next step (done / iterate / roll back to the snapshot). Routine
preview targets and evidence paths are deterministic defaults, with CLI flags only for overrides.

INTERNAL ONLY: uses the authenticated Savant API.
"""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path

from savant_api import cli as api
from savant_api import sources as sources_api
from savant_api.fileio import workspace_tmp
from savant_api.recipes import get_recipe, recipe_model_diff, update_workflow_recipe
from workflow import evidence as workflow_evidence
from workflow import inspection as savant_inspect
from workflow import polish as workflow_polish
from validators import workflow as vw


def _load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_flow(flow_url: str):
    su = api.parse_savant_url(flow_url)
    if su.kind != "flow" or not su.flow_id:
        raise SystemExit("workflow edit requires a Savant flow URL (.../flow/{flowId}).")
    ctx = api.discover_session(su.namespace, origin=su.origin)
    return su, ctx


def merge_rebuilt_recipe(live: dict, rebuilt: dict) -> dict:
    """Merge a creation-shaped rebuilt workflow JSON onto the live recipe's identity envelope.

    This is the deterministic rebuild-in-place path: after a failed verification the Builder
    regenerates the FULL workflow JSON, and instead of importing a second flow (which mints a new
    flowId and leaves a duplicate), the rebuilt model content replaces the existing flow's content
    via recipe save on the SAME flowId. The live envelope (id, folderId, namespace, version fields,
    audit fields, name) is kept; the model content (nodes, sourceProfiles, description) comes from
    the rebuild. The live name is kept deliberately — a rebuild must not rename a flow the user
    already knows; renames are their own edit.
    """
    if not isinstance(rebuilt, dict) or not isinstance(rebuilt.get("nodes"), list) or not rebuilt["nodes"]:
        raise SystemExit("--replace-from-build JSON must be a workflow object with a non-empty `nodes` array.")
    if rebuilt.get("id"):
        raise SystemExit(
            "--replace-from-build expects creation-shaped builder output (no `id`). "
            "A live-shaped edited recipe goes through --proposed-recipe instead."
        )
    merged = copy.deepcopy(live)
    merged["nodes"] = copy.deepcopy(rebuilt["nodes"])
    for key in ("sourceProfiles", "description"):
        if rebuilt.get(key) is not None:
            merged[key] = copy.deepcopy(rebuilt[key])
    return merged


def _replace_content_blockers(nodes: list[dict], ctx) -> list[str]:
    """The same pre-write content checks `workflow create` preflight runs, applied before a
    full-content replace: a rebuilt model can carry exactly the same silent-drop hazards as a
    fresh import (placeholder/foreign dataset ids, AI nodes without a provider)."""
    blockers: list[str] = []
    missing_ai = vw.ai_missing_provider_nodes(nodes)
    if missing_ai:
        blockers.append(f"missing AI provider on: {', '.join(missing_ai)}")
    placeholders = vw.source_placeholder_nodes(nodes)
    if placeholders:
        blockers.append(f"placeholder/missing source dataset id on: {', '.join(placeholders)}")
    workspace_ids = sources_api.workspace_dataset_ids(ctx)
    if workspace_ids:
        unresolved = vw.unresolved_source_dataset_ids(nodes, workspace_ids)
        if unresolved:
            blockers.append(
                f"source dataset id(s) do not resolve in this flow's workspace: {', '.join(unresolved)} "
                "(datasets are workspace-scoped; saving anyway silently drops these source nodes)"
            )
    return blockers


_CREATE_CONTINUATION_STATUSES = {
    "verified",
    "created-with-issues",
    "imported",
    "import-unverified",
}


def same_session_create_context(flow_id: str) -> dict | None:
    """Return same-session create evidence for this flow, if the create helper produced it.

    A create task often imports a flow, finds issues during verification, then routes fixes
    through the editor. The editor should not depend on the model to carry that context in a
    flag; it can read the current AI session's create reports and infer that the edit is still
    part of the original create delivery.
    """
    if not flow_id:
        return None
    try:
        root = workspace_tmp()
    except RuntimeError:
        return None
    if not root.exists():
        return None
    matches: list[dict] = []
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("phase") != "create":
            continue
        if data.get("status") not in _CREATE_CONTINUATION_STATUSES:
            continue
        report_flow_id = str(data.get("flowId") or "")
        flow_url = str(data.get("flowUrl") or "")
        if report_flow_id != flow_id and f"/flow/{flow_id}" not in flow_url:
            continue
        matches.append({
            "reportPath": str(path),
            "status": data.get("status"),
            "workflowName": data.get("workflowName"),
            "flowId": report_flow_id or flow_id,
            "flowUrl": flow_url,
            "folder": data.get("folder"),
        })
    if not matches:
        return None
    matches.sort(key=lambda item: item["reportPath"])
    return matches[-1]


# Config keys whose change never alters what a step DOES in business terms; a swap here must
# not nag for a description rewrite (the description describes meaning, not plumbing).
_OPERATIONAL_CONFIG_KEYS = {"providerId"}


def _semantic_config_changed(before: dict | None, after: dict | None) -> bool:
    b = {k: v for k, v in (before or {}).items() if k not in _OPERATIONAL_CONFIG_KEYS}
    a = {k: v for k, v in (after or {}).items() if k not in _OPERATIONAL_CONFIG_KEYS}
    return b != a


def documentation_staleness(current: dict, proposed: dict, *, edit_class: str = "logic") -> list[dict]:
    """Deterministic check that an edit keeps the documentation in step with the change.

    Descriptions, group headers, and the workflow description are the user-facing record of
    what the workflow does. Detection is always deterministic; what changes with `edit_class`
    is the severity, because fix-vs-logic intent is a judgment the editor must DECLARE:

    - ``logic`` (default): the change alters business meaning — stale documentation is a
      "warn" the editor must resolve in the same edit.
    - ``fix``: a declared behavior-preserving bug fix (same business meaning, outputs, grain) —
      items become "note"s: no rewrite demanded, but the declaration is recorded in the report
      so a mis-declared logic change is auditable.

    Purely operational config changes (see _OPERATIONAL_CONFIG_KEYS) never flag at all.
    Returns [{"severity": "warn"|"note", "message": str}]. Node/group/text fields save with the
    recipe; the workflow description saves via the metadata path.
    """
    if edit_class not in {"logic", "fix"}:
        raise ValueError(f"edit_class must be 'logic' or 'fix', got {edit_class!r}")
    severity = "warn" if edit_class == "logic" else "note"
    cur = {n["id"]: n for n in current.get("nodes") or [] if isinstance(n, dict)}
    prop = {n["id"]: n for n in proposed.get("nodes") or [] if isinstance(n, dict)}
    warnings: list[dict] = []

    def name_of(node: dict) -> str:
        return str(node.get("name") or node.get("id"))

    def emit(message: str) -> None:
        if edit_class == "fix":
            message += " (declared as a behavior-preserving fix — no rewrite required if the wording still holds.)"
        warnings.append({"severity": severity, "message": message})

    body_types_excluded = {"group", "text", "outlet"}
    for nid in sorted(cur.keys() & prop.keys()):
        before, after = cur[nid], prop[nid]
        if (after.get("type") or before.get("type")) in body_types_excluded:
            continue
        if _semantic_config_changed(before.get("config"), after.get("config")) and \
                (before.get("description") or "") == (after.get("description") or ""):
            emit(
                f"Node '{name_of(after)}': configuration changed but its description did not — "
                "refresh the node-specific configuration readout in the description, or confirm it still "
                "accurately explains the current settings in business language."
            )

    def members_of(nodes: dict, gid: str) -> set[str]:
        return {nid for nid, n in nodes.items()
                if (n.get("canvasConfig") or {}).get("parentId") == gid
                and n.get("type") not in {"text"}}

    def header_text(nodes: dict, gid: str) -> str:
        for n in nodes.values():
            if n.get("type") == "text" and (n.get("canvasConfig") or {}).get("parentId") == gid:
                return str((n.get("config") or {}).get("text") or "")
        return ""

    for gid in sorted(nid for nid, n in prop.items() if n.get("type") == "group"):
        if gid not in cur:
            continue
        if members_of(cur, gid) != members_of(prop, gid) and \
                header_text(cur, gid) == header_text(prop, gid) and \
                (cur[gid].get("description") or "") == (prop[gid].get("description") or ""):
            emit(
                f"Group '{name_of(prop[gid])}': its steps changed but the header/description did not — "
                "update them or confirm they still describe the stage."
            )

    added = sorted(prop.keys() - cur.keys())
    removed = sorted(cur.keys() - prop.keys())
    structural = [nid for nid in added + removed
                  if (prop.get(nid) or cur.get(nid) or {}).get("type") not in body_types_excluded]
    if structural:
        emit(
            f"Workflow structure changed ({len(structural)} node(s) added/removed) — if the business "
            "process changed, refresh the workflow description too (saved via the metadata path, "
            "not the recipe save)."
        )
    return warnings


def relocation_documentation_gate(current: dict, proposed: dict) -> list[str]:
    """BLOCKING check (canvas-layout-rules.md, user rule 2026-06-10): moving steps between
    groups changes what both groups MEAN, so the SAME change must update the affected
    groups' names/headers and the workflow description. A relocation delivered without its
    documentation is an incomplete edit — this gate refuses it (override deliberately with
    --accept-stale-docs)."""
    cur = {n["id"]: n for n in current.get("nodes") or [] if isinstance(n, dict)}
    prop = {n["id"]: n for n in proposed.get("nodes") or [] if isinstance(n, dict)}
    moves: list[tuple[str, str, str]] = []
    for nid in cur.keys() & prop.keys():
        n0, n1 = cur[nid], prop[nid]
        if (n1.get("type") or n0.get("type")) in {"group", "text", "outlet"}:
            continue
        p0 = (n0.get("canvasConfig") or {}).get("parentId")
        p1 = (n1.get("canvasConfig") or {}).get("parentId")
        if p0 != p1 and p0 in cur and p1 in cur:
            moves.append((nid, p0, p1))
    if not moves:
        return []

    def header_text(nodes: dict, gid: str) -> str:
        for n in nodes.values():
            if n.get("type") == "text" and (n.get("canvasConfig") or {}).get("parentId") == gid:
                cfg = n.get("config") or {}
                return str(cfg.get("inputText") or cfg.get("text") or "")
        return ""

    affected = sorted({g for _nid, a, b in moves for g in (a, b) if g})
    stale = [g for g in affected
             if header_text(cur, g) == header_text(prop, g)
             and (cur.get(g, {}).get("name") or "") == (prop.get(g, {}).get("name") or "")]
    wf_unchanged = (current.get("description") or "") == (proposed.get("description") or "")
    if not stale and not wf_unchanged:
        return []
    missing: list[str] = []
    if stale:
        missing.append("group header/description updates for "
                       + ", ".join(f"'{prop[g].get('name') or g}'" for g in stale))
    if wf_unchanged:
        missing.append("a workflow description update")
    names = ", ".join(f"'{prop[g].get('name') or g}'" for g in affected)
    return [
        f"{len(moves)} step(s) moved between groups ({names}) but this change is missing "
        + " and ".join(missing)
        + ". Relocation must ship WITH its documentation in the same change "
        "(canvas-layout-rules.md). Update them, or re-run with --accept-stale-docs to "
        "override deliberately."
    ]


def propose(flow_url: str, proposed_path: str | None = None, *, snapshot_path: Path | None = None,
            replace_from_build: str | None = None, merged_path: Path | None = None,
            polish: bool = False, polish_autolayout: bool = True, polish_colors: bool = True,
            polished_path: Path | None = None, edit_class: str = "logic",
            accept_stale_docs: bool = False, require_documentation: bool = False):
    """Phase 1: fetch current recipe, snapshot it, diff vs the proposed recipe, validate. No save.

    Exactly one of `proposed_path` (live-shaped edited recipe) or `replace_from_build`
    (creation-shaped builder output, merged onto the live envelope) provides the proposal."""
    if (proposed_path is None) == (replace_from_build is None):
        raise SystemExit("Provide exactly one of --proposed-recipe or --replace-from-build.")
    su, ctx = _resolve_flow(flow_url)
    create_context = same_session_create_context(su.flow_id)
    effective_require_documentation = require_documentation or bool(create_context)
    current = get_recipe(ctx, su.flow_id)
    if snapshot_path is not None:
        api.save_json(current, snapshot_path)            # rollback snapshot, captured before any save
    replace_blockers: list[str] = []
    if replace_from_build is not None:
        rebuilt = _load(replace_from_build)
        proposed = merge_rebuilt_recipe(current, rebuilt)
        replace_blockers = _replace_content_blockers(
            [n for n in proposed.get("nodes", []) if isinstance(n, dict)], ctx)
        merged_path = merged_path or default_replace_merged_path(su.flow_id)
        api.save_json(proposed, merged_path)
        proposed_path = str(merged_path)
    else:
        proposed = _load(proposed_path)
    polish_report = {"applied": [], "autolayout": False, "colors": False, "groupCount": 0}
    validation_path = Path(proposed_path)
    if polish:
        proposed, polish_report = workflow_polish.polish_recipe(
            proposed,
            autolayout=polish_autolayout,
            colors=polish_colors,
        )
        if polished_path is not None:
            api.save_json(proposed, polished_path)
            validation_path = polished_path
        else:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            try:
                json.dump(proposed, tmp)
                tmp.close()
                validation_path = Path(tmp.name)
            finally:
                if not tmp.closed:
                    tmp.close()
    diff = recipe_model_diff(current, proposed)
    errors, warnings = vw.validate(validation_path, block_documentation_gaps=effective_require_documentation)
    # Rebuild-in-place arrives with freshly generated documentation; staleness only applies
    # to inline edits of the existing recipe.
    doc_warnings = [] if replace_from_build is not None \
        else documentation_staleness(current, proposed, edit_class=edit_class)
    documentation_errors = [
        f"Documentation scope requires this to be resolved: {item['message']}"
        for item in doc_warnings
        if effective_require_documentation and item.get("severity") == "warn"
    ]
    # Relocation gate: BLOCKS (not warns) when steps moved between groups without the
    # documentation updates the move requires — unless deliberately overridden.
    relocation_errors = [] if (replace_from_build is not None or accept_stale_docs) \
        else relocation_documentation_gate(current, proposed)
    errors = list(errors) + documentation_errors + relocation_errors
    blocked_reasons = [f"{len(errors)} validation error(s)"] if errors else []
    blocked_reasons.extend(replace_blockers)
    report = {
        "phase": "propose",
        "flowId": su.flow_id,
        "flowUrl": flow_url,
        "snapshotPath": str(snapshot_path) if snapshot_path else None,
        "replaceFromBuild": replace_from_build,
        "mergedRecipePath": str(merged_path) if replace_from_build is not None else None,
        "polishedRecipePath": str(polished_path) if polished_path else None,
        "polish": polish_report,
        "diff": diff,
        "validation": {"errors": errors, "warnings": warnings},
        "documentation": doc_warnings,
        "documentationRequired": effective_require_documentation,
        "createContinuation": create_context,
        "blocked": bool(blocked_reasons),
        "blockedReasons": blocked_reasons,
    }
    return report, ctx, su, proposed


def commit(ctx, su, proposed: dict, *, flow_url: str, checkpoints: list[str],
           expect_columns: list[str] | None, expected_outputs: list[dict] | None = None,
           sample_tier: str, timeout: int,
           post_save_recipe_path: Path | None = None,
           terminal_preview: bool = True,
           block_documentation_gaps: bool = False) -> dict:
    """Phase 2: save the proposed recipe, re-fetch, then run the shared Inspector on chosen nodes."""
    update_report = update_workflow_recipe(ctx, su.flow_id, proposed)
    evidence = workflow_evidence.collect_post_write_evidence(
        ctx=ctx,
        flow_url=flow_url,
        flow_id=su.flow_id,
        operation="edit",
        imported_path=None,
        expect_columns=expect_columns,
        expected_outputs=expected_outputs,
        checkpoints=checkpoints,
        sample_tier=sample_tier,
        timeout=timeout,
        terminal_preview=terminal_preview,
        force_analyze=True,                              # recipe saves can leave old Ready previews cached
        post_write_recipe_path=post_save_recipe_path,
        block_documentation_gaps=block_documentation_gaps,
    )
    refetched = evidence.pop("refetchedRecipe")
    persisted = recipe_model_diff(proposed, refetched)   # residual node-field diffs after save (normalization)
    return {
        "phase": "commit",
        "flowId": su.flow_id,
        "flowUrl": flow_url,
        "update": update_report,
        "persistedDiff": persisted,
        "postSaveRecipePath": evidence.get("postSaveRecipePath"),
        "inspect": evidence.get("inspect"),
        "createContinuation": same_session_create_context(su.flow_id),
        "documentationRequired": block_documentation_gaps,
        "evidence": {k: v for k, v in evidence.items() if k not in {"postSaveRecipePath", "inspect"}},
        "status": "verified" if evidence.get("ok") else "saved-with-issues",
    }


def default_output_path(flow_id: str, phase: str) -> Path:
    return workspace_tmp("workflow-edits", f"{flow_id}.edit-{phase}.json")


def default_snapshot_path(flow_id: str) -> Path:
    return workspace_tmp("workflow-edits", f"{flow_id}.rollback.json")


def default_replace_merged_path(flow_id: str) -> Path:
    return workspace_tmp("workflow-edits", f"{flow_id}.proposed-replace.json")


def default_polished_recipe_path(flow_id: str) -> Path:
    return workspace_tmp("workflow-edits", f"{flow_id}.proposed-polished.json")


def default_post_save_recipe_path(flow_id: str) -> Path:
    return workflow_evidence.default_post_write_recipe_path(flow_id, "edit")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("flow_url", help="Savant flow URL: .../flow/{flowId}?rns={ns}")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--proposed-recipe",
                       help="The edited recipe JSON the caller built (via recipe_edit / node_builders).")
    group.add_argument("--replace-from-build",
                       help="Creation-shaped builder workflow JSON to apply to THIS flow in place "
                            "(rebuild-in-place). The rebuilt nodes/sourceProfiles replace the flow's "
                            "content via recipe save on the same flowId — never a second import. The "
                            "merged proposal is written for review, and the same content blockers as "
                            "create preflight (placeholder/foreign dataset ids, missing AI provider) "
                            "block before save.")
    p.add_argument("--snapshot", type=Path, help="Where to write the pre-edit rollback snapshot.")
    p.add_argument("--polish", action="store_true",
                   help="Apply shared JSON polish before diff/validation/save after the user confirms visual polish is in scope.")
    p.add_argument("--no-polish-autolayout", action="store_true",
                   help="During shared JSON polish, keep existing layout positions/sizes.")
    p.add_argument("--polish-colors", action="store_true",
                   help="During shared JSON polish on an EDIT, fill missing group colors. Off by "
                        "default: editing should not change a flow's colors without the user asking, "
                        "since they may not want color edits. (Creation auto-colors by default.)")
    p.add_argument("--polished-recipe-path", type=Path,
                   help="Override where the polished proposed recipe JSON is written.")
    p.add_argument("--edit-class", choices=["logic", "fix"], default="logic",
                   help="Documentation intent of this edit. 'logic' (default): the change alters business "
                        "meaning, so stale node/group/workflow documentation is a warning to resolve in the "
                        "same edit. 'fix': a declared behavior-preserving bug fix — staleness items become "
                        "informational notes, and the declaration is recorded in the report. Declare 'fix' "
                        "ONLY when business meaning, outputs, and grain are unchanged.")
    p.add_argument("--confirm", action="store_true",
                   help="Proceed past propose to save + verify. Set ONLY after the user confirmed the diff in chat.")
    p.add_argument("--checkpoint", action="append", default=[],
                   help="Node display name to Analyze in the verify phase (repeatable). Default to the edit's "
                        "affected nodes; choose deliberately — Analyzing AI nodes costs money.")
    p.add_argument("--expect-columns", help="Comma-separated expected terminal columns (runs the output-contract check).")
    p.add_argument("--expected-outputs-json",
                   help="JSON list/object of output contracts for richer output checks; same format as workflow inspect.")
    p.add_argument("--no-terminal-preview", action="store_true",
                   help="On --confirm, skip the default terminal output preview and inspect only named checkpoints/contracts.")
    p.add_argument("--sample-tier", default="1k")
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--post-save-recipe-path", type=Path,
                   help="Override where --confirm writes the re-fetched post-save workflow JSON.")
    p.add_argument("--no-post-save-recipe", action="store_true",
                   help="On --confirm, skip writing the re-fetched post-save workflow JSON.")
    p.add_argument("--accept-stale-docs", action="store_true",
                   help="Deliberately override the relocation documentation gate (steps moved "
                        "between groups without group/workflow description updates).")
    p.add_argument("--require-documentation", action="store_true",
                   help="Promote node-description coverage gaps and stale documentation warnings to errors. "
                        "Use after the user confirms Documentation scope, or when a config/logic edit must ship "
                        "with complete step documentation in the same change.")
    p.add_argument("--output-path", type=Path, help="Where to write the JSON report.")
    args = p.parse_args(argv)

    parsed = api.parse_savant_url(args.flow_url)
    snapshot_path = args.snapshot or default_snapshot_path(parsed.flow_id or "workflow")
    polished_path = args.polished_recipe_path or default_polished_recipe_path(parsed.flow_id or "workflow") if args.polish else None
    report, ctx, su, proposed = propose(
        args.flow_url,
        args.proposed_recipe,
        replace_from_build=args.replace_from_build,
        snapshot_path=snapshot_path,
        polish=args.polish,
        polish_autolayout=not args.no_polish_autolayout,
        polish_colors=args.polish_colors,
        polished_path=polished_path,
        edit_class=args.edit_class,
        accept_stale_docs=args.accept_stale_docs,
        require_documentation=args.require_documentation,
    )

    def emit(rep):
        phase = "commit" if rep.get("phase") == "commit" else "propose"
        api.save_json(rep, args.output_path or default_output_path(su.flow_id, phase))

    if report["blocked"]:
        emit(report)
        print(f"EDIT [propose] BLOCKED — {'; '.join(report['blockedReasons'])}; resolve, then re-run.")
        for e in report["validation"]["errors"]:
            print(f"    ERROR: {e}")
        return 2
    if not args.confirm:
        emit(report)
        d = report["diff"]["nodes"]
        print(f"EDIT [propose] flow={su.flow_id}: +{len(d['added'])} added, -{len(d['removed'])} removed, "
              f"~{len(d['changed'])} changed; snapshot={report['snapshotPath']}")
        if report.get("mergedRecipePath"):
            print(f"  -> merged rebuild-in-place proposal: {report['mergedRecipePath']}")
        if report.get("polishedRecipePath"):
            print(f"  -> polished proposed recipe: {report['polishedRecipePath']}")
        for w in report.get("documentation") or []:
            print(f"  [{w['severity']}] documentation: {w['message']}")
        print("  -> review the diff, get the user's confirmation in chat, then re-run with --confirm.")
        return 0

    expect = [c.strip() for c in args.expect_columns.split(",")] if args.expect_columns else None
    expected_outputs = savant_inspect.load_expected_outputs(args.expected_outputs_json)
    post_save_recipe_path = (
        None if args.no_post_save_recipe else args.post_save_recipe_path or default_post_save_recipe_path(su.flow_id)
    )

    out = commit(ctx, su, proposed, flow_url=args.flow_url, checkpoints=args.checkpoint,
                 expect_columns=expect, expected_outputs=expected_outputs,
                 sample_tier=args.sample_tier, timeout=args.timeout_seconds,
                 post_save_recipe_path=post_save_recipe_path,
                 terminal_preview=not args.no_terminal_preview,
                 block_documentation_gaps=report.get("documentationRequired", False))
    out["documentation"] = report.get("documentation") or []
    emit(out)
    print(f"EDIT: {out['status']} — {out['flowUrl']}")
    if out.get("postSaveRecipePath"):
        print(f"  [ok ] post-save-workflow-json: {out['postSaveRecipePath']}")
    for w in out["documentation"]:
        print(f"  [{w['severity']}] documentation: {w['message']}")
    summary = dict(out.get("inspect") or {})
    savant_inspect.print_summary_lines(summary)
    return 0 if out["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
