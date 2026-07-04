#!/usr/bin/env python3
"""Deterministic workflow JSON polish shared by create/build and edit paths.

SYSTEM MAP (ownership, 2026-06-10 review): the shipping layout system is three parts —
- `workflow.layout_solver`  : PLAN GENERATOR. Plan-first placement; measured
  hypotheses (relocation, junction fallback) and solver-owned measured repairs.
- `workflow.polish` (here)  : SHIPPING ARBITER. Runs the solver and enforces the
  non-degrading guard. What leaves this
  function IS the user-facing layout contract (zero hard defects — pinned corpus-wide
  by ShippingContractTests).
- `workflow.layout_metrics` : REFEREE. The only judge either of the above answers to.
The legacy `Flow._autolayout` path is no longer a competing shipping candidate; remaining
cleanup is to retire unused implementation after generated-builder parity is confirmed.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from savant_api import cli as api
from savant_api.fileio import workspace_tmp
from workflow import layout_metrics
from workflow import layout_solver
from workflow import outlets
from validators import workflow as vw


def _workflow_label(recipe: dict[str, Any]) -> str:
    return str(recipe.get("name") or recipe.get("id") or "workflow").strip() or "workflow"


def _group_flow_order(nodes: list[dict[str, Any]]) -> list[str]:
    """Group ids in DATA-FLOW order (dependency levels, then appearance).

    Colors follow the data as it moves through the workflow (user rule, 2026-06-10):
    assigning hues along this order means connected stages never look alike."""
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    groups = [n["id"] for n in nodes if n.get("type") == "group" and isinstance(n.get("id"), str)]
    gset = set(groups)
    deps: dict[str, set[str]] = {g: set() for g in groups}
    for edge in layout_metrics.iter_edges(nodes):
        src = by_id.get(str(edge[0]).partition("|")[0])
        dst = by_id.get(edge[1])
        a = ((src or {}).get("canvasConfig") or {}).get("parentId")
        b = ((dst or {}).get("canvasConfig") or {}).get("parentId")
        if a in gset and b in gset and a != b:
            deps[b].add(a)
    level = {g: 0 for g in groups}
    for _ in range(len(groups) + 1):
        changed = False
        for g in groups:
            for d in deps[g]:
                if level[g] <= level[d]:
                    level[g] = level[d] + 1
                    changed = True
        if not changed:
            break
    return sorted(groups, key=lambda g: (level[g], groups.index(g)))


def _flow_palette(seed_text: str, count: int) -> list[str]:
    """Deterministic per-workflow palette: a golden-angle hue walk from a seeded start.

    - Seeded by the workflow id, so every workflow gets its own family of colors while
      the same workflow always renders identically (no fixed shared palette look).
    - Consecutive hues sit 137 degrees apart, so stages that feed each other can never
      wear the same or a look-alike color.
    - Lightness stays in the 76-83%% band: the canvas softens fills, and anything
      lighter renders invisible (live finding, 2026-06-10)."""
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    start = seed % 360
    n = max(count, 1)
    # Evenly spaced hues = the maximum possible PAIRWISE separation (360/n): at pastel
    # lightness, hue families collapse, so every room must differ from EVERY other room,
    # not just from the rooms it connects to (user review, 2026-06-10: two blues read
    # as the same color across the canvas). The interleaved visit order (first half
    # alternating with the second half of the wheel) puts flow-adjacent stages on
    # opposite sides, so neighbors differ by ~180 degrees, never the minimum.
    slots: list[int] = []
    for i in range((n + 1) // 2):
        slots.append(i)
        if i + (n + 1) // 2 < n:
            slots.append(i + (n + 1) // 2)
    out: list[str] = []
    for i in range(n):
        hue = (start + slots[i] * (360 // n)) % 360
        sat = 48 + (i * 5 + seed % 5) % 13        # 48-60%
        light = 76 + (i * 3 + seed % 3) % 6       # 76-81%
        out.append(f"hsl({hue}, {sat}%, {light}%)")
    return out


def _position(node: dict[str, Any]) -> dict[str, float] | None:
    pos = node.get("position")
    if not isinstance(pos, dict):
        return None
    try:
        return {"x": float(pos.get("x")), "y": float(pos.get("y"))}
    except (TypeError, ValueError):
        return None


def _parent_id(node: dict[str, Any]) -> str | None:
    config = node.get("canvasConfig") if isinstance(node.get("canvasConfig"), dict) else {}
    parent = config.get("parentId")
    return parent if isinstance(parent, str) and parent else None


def _geometry_snapshot(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        entry: dict[str, Any] = {"position": copy.deepcopy(node.get("position"))}
        # group MEMBERSHIP is geometry too: the solver may relocate steps between groups,
        # and a restore that brings back positions without parents corrupts both layouts.
        entry["parentId"] = (node.get("canvasConfig") or {}).get("parentId")
        if node.get("type") in {"group", "text"} and isinstance(node.get("config"), dict):
            entry["config"] = {
                key: node["config"].get(key)
                for key in ("width", "height", "currentHeight")
                if key in node["config"]
            }
        snapshot[node_id] = entry
    return snapshot


def _restore_geometry(nodes: list[dict[str, Any]], snapshot: dict[str, dict[str, Any]]) -> None:
    for node in nodes:
        entry = snapshot.get(node.get("id") or "")
        if entry is None:
            continue
        if entry.get("position") is not None:
            node["position"] = copy.deepcopy(entry["position"])
        elif "position" in node:
            del node["position"]
        if "parentId" in entry:
            cc = node.setdefault("canvasConfig", {})
            if entry["parentId"] is None:
                cc.pop("parentId", None)
            else:
                cc["parentId"] = entry["parentId"]
        for key, value in (entry.get("config") or {}).items():
            if isinstance(node.get("config"), dict):
                node["config"][key] = value


def polish_recipe(recipe: dict[str, Any], *, autolayout: bool = True, colors: bool = True,
                  recolor: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a polished recipe copy plus a small report.

    This does not change business logic. It only applies deterministic visual/layout mechanics:
    group colors, group sizing, node placement, header sizing, and ungrouped outlet placement.

    Re-layout is NON-DEGRADING: the incoming layout and the re-laid layout are both
    scored with `layout_metrics` (connectors through nodes/frames, crossings,
    backward edges, overlaps), and the better one is kept. Polishing a workflow a
    user already organized never makes it visually worse.
    """
    polished = copy.deepcopy(recipe)
    workflow_name = _workflow_label(polished)
    changed: list[str] = []

    # Re-wire outlet pseudo-nodes to the canonical shape before layout: collapse any existing
    # `{parent}|i` children and re-expand from each tool's branch intent. Source-agnostic and
    # idempotent, so it cleans up builder output, hand-authored JSON, and imported flows alike.
    if isinstance(polished.get("nodes"), list):
        changed.extend(outlets.normalize_outlets(polished["nodes"]))
    nodes = [node for node in polished.get("nodes") or [] if isinstance(node, dict)]

    if autolayout and any(node.get("type") == "group" for node in nodes):
        baseline_metrics = layout_metrics.measure(nodes)
        baseline_geometry = _geometry_snapshot(nodes)
        # Solver path: plan-first layout plus solver-owned measured repairs.
        layout_changes = list(layout_solver.solve(nodes))
        if layout_metrics.score(layout_metrics.measure(nodes)) > layout_metrics.score(baseline_metrics):
            _restore_geometry(nodes, baseline_geometry)
            changed.append("kept-existing-layout")
        else:
            changed.extend(layout_changes)
            changed.append("autolayout")

    if colors:
        by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
        order = _group_flow_order(nodes)
        palette = _flow_palette(str(polished.get("id") or workflow_name), len(order))
        for i, gid in enumerate(order):
            config = by_id[gid].setdefault("config", {})
            if recolor or not config.get("color"):
                config["color"] = palette[i]
                changed.append(f"group-color:{gid}")

    # Structured relocation contract (user rule, 2026-06-10): callers must not have to
    # parse prose notes — the FINAL membership diff vs the incoming recipe is reported
    # machine-readably so edit/write paths can enforce the documentation-with-the-move
    # rule. (A kept-existing layout restores memberships and reports nothing.)
    incoming_by_id = {n.get("id"): n for n in recipe.get("nodes") or [] if isinstance(n, dict)}
    by_id_final = {n.get("id"): n for n in nodes if isinstance(n.get("id"), str)}
    relocations: list[dict[str, Any]] = []
    for nid, node in by_id_final.items():
        before = incoming_by_id.get(nid)
        if before is None or node.get("type") in {"group", "text", "outlet"}:
            continue
        p0 = (before.get("canvasConfig") or {}).get("parentId")
        p1 = (node.get("canvasConfig") or {}).get("parentId")
        if p0 != p1:
            relocations.append({
                "nodeId": nid,
                "node": node.get("name"),
                "fromGroupId": p0,
                "fromGroup": (incoming_by_id.get(p0) or {}).get("name"),
                "toGroupId": p1,
                "toGroup": (by_id_final.get(p1) or {}).get("name"),
            })
    report = {
        "applied": changed,
        "autolayout": bool(autolayout),
        "colors": bool(colors),
        "groupCount": sum(1 for node in nodes if node.get("type") == "group"),
        "relocations": relocations,
        "documentationRequired": bool(relocations),
    }
    return polished, report


def default_output_path(flow_id: str, phase: str = "polished") -> Path:
    return workspace_tmp("workflow-polish", f"{flow_id}.{phase}.json")


def main(argv=None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_json", help="Workflow recipe JSON to polish.")
    parser.add_argument("--no-autolayout", action="store_true", help="Skip deterministic auto-layout.")
    parser.add_argument("--no-colors", action="store_true", help="Skip filling missing group colors.")
    parser.add_argument("--recolor", action="store_true",
                        help="Reassign ALL group colors from the workflow's own flow-ordered palette.")
    parser.add_argument("--accept-relocations-without-docs", action="store_true",
                        help="Write relocated group membership even though group/workflow descriptions still need review.")
    parser.add_argument("--validate", action="store_true", help="Run workflow validator after polish.")
    parser.add_argument("--output-path", type=Path, help="Where to write the polished JSON.")
    args = parser.parse_args(argv)

    source = Path(args.workflow_json)
    recipe = json.loads(source.read_text(encoding="utf-8"))
    polished, report = polish_recipe(recipe, autolayout=not args.no_autolayout, colors=not args.no_colors,
                                     recolor=args.recolor)
    if report.get("documentationRequired") and not args.accept_relocations_without_docs:
        print("POLISH: blocked because layout relocated steps between groups.")
        print("  Update the affected group headers/names and workflow description in the same change,")
        print("  or rerun with --accept-relocations-without-docs after deliberately accepting stale docs.")
        for item in report.get("relocations") or []:
            print(
                f"  moved {item.get('node') or item.get('nodeId')} "
                f"from {item.get('fromGroup') or item.get('fromGroupId')} "
                f"to {item.get('toGroup') or item.get('toGroupId')}"
            )
        return 2
    output_path = args.output_path or default_output_path(str(polished.get("id") or source.stem))
    api.save_json(polished, output_path)
    print(f"POLISH: wrote {output_path}")
    if args.validate:
        errors, warnings = vw.validate(output_path)
        report["validation"] = {"errors": errors, "warnings": warnings}
        for error in errors:
            print(f"  ERROR: {error}")
        for warning in warnings:
            print(f"  warn: {warning}")
        return 2 if errors else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
