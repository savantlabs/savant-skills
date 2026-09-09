#!/usr/bin/env python3
"""Live post-import inspection harness, the runtime counterpart to `savant.py validate workflow`.

Given a created Savant flow URL (plus the imported workflow JSON and the expected output
columns), this runs the standard creator verification checks in ONE orchestrated pass and emits
a structured pass/fail report:

  1. persistence    — live node count + node-name set match the imported JSON.
  2. runtime-smoke  — after create/save succeeds, Analyze requested checkpoints status-only and
                      fail fast on the first Failed/Error/Canceled node.
  3. node-ok        — every inspected checkpoint is `Ready`; this is populated from runtime-smoke.
  4. output-contract — only after runtime-smoke passes, read output columns and compare to expected
                      columns, in order (catches drift, leaked columns, wrong rename).
  5. row-sanity     — checkpoints don't silently collapse to 0 rows (WARN, not a hard fail).

It reuses `savant_api` for session/recipe/Analyze, and `--checkpoint` lets the caller name the
deterministic stages to verify (pivot/filter/top-N/etc.) without waiting on slow AI terminals.

INTERNAL ONLY: it uses the authenticated Savant API (Analyze), so it runs only when the live API
is available. It does not remove Analyze latency (each node is a live round-trip; gen_ai nodes
are slow). Layout quality is not inspected here; `savant.py validate workflow` covers the
deterministic layout geometry on the JSON.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

from savant_api import cli as api
from savant_api.fileio import workspace_tmp
from savant_api.recipe_input import assert_flow_id, load_recipe
from savant_api import runmode

ERROR, WARN = "error", "warn"
FAILED_STATUSES = {"Failed", "Error", "Canceled"}
READY_STATUS = "Ready"


def _schema_names(schema) -> list:
    names = []
    for col in schema or []:
        names.append(col.get("name") if isinstance(col, dict) else col)
    return names


def _by_name(nodes, name):
    return next((n for n in nodes if n.get("name") == name), None)


def _expected_output_node_name(output: dict) -> str:
    value = output.get("verification_node_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    value = output.get("output_name")
    return value.strip() if isinstance(value, str) else ""


def _expected_output_columns(output: dict) -> list[str]:
    values = output.get("expected_columns")
    if not isinstance(values, list):
        return []
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def load_expected_outputs(path: str | Path | None) -> list[dict] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    outputs = None
    if isinstance(payload, dict):
        if isinstance(payload.get("outputs"), list):
            outputs = payload.get("outputs")
        elif isinstance(payload.get("output_destination_plan"), dict):
            outputs = payload["output_destination_plan"].get("outputs")
        else:
            sections = payload.get("sections")
            if isinstance(sections, dict):
                builder = sections.get("builder_preflight")
                if isinstance(builder, dict) and isinstance(builder.get("output_destination_plan"), dict):
                    outputs = builder["output_destination_plan"].get("outputs")
    else:
        outputs = payload
    if not isinstance(outputs, list):
        raise ValueError(
            "expected outputs JSON must be a list, an object with `outputs`, "
            "a builder_preflight object, or a handoff containing sections.builder_preflight.output_destination_plan.outputs."
        )
    result = []
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise ValueError(f"expected outputs entry {index} must be an object.")
        result.append(output)
    return result


def _terminals(nodes: list[dict]) -> list[dict]:
    """Data nodes with no outgoing edge (destinations / leaves); skip canvas group/text/outlet."""
    has_downstream = set()
    for n in nodes:
        for outlet in (n.get("outlets") or []):
            if outlet.get("targets"):
                has_downstream.add(n["id"])
                break
    return [n for n in nodes
            if n.get("type") not in ("group", "text", "outlet") and n["id"] not in has_downstream]


def _node_by_id(nodes: list[dict]) -> dict[str, dict]:
    return {node["id"]: node for node in nodes if isinstance(node.get("id"), str)}


def _upstream_map(nodes: list[dict]) -> dict[str, list[str]]:
    upstream: dict[str, list[str]] = {}
    for node in nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        sources: list[str] = []
        for inlet in node.get("inlets") or []:
            if not isinstance(inlet, dict):
                continue
            source = inlet.get("source")
            if isinstance(source, str) and source:
                sources.append(source)
            for item in inlet.get("sources") or []:
                if isinstance(item, dict) and isinstance(item.get("source"), str):
                    sources.append(item["source"])
        upstream[node_id] = sources
    return upstream


def print_summary_lines(report: dict, *, indent: str = "  ") -> None:
    """Shared CLI summary used by create/edit/inspect — one loop, no variations.

    Prints output smoke, per-check marks, and — critically — the
    `previewSkipped.upstreamBlockers` root-cause lines. A `node-ok: Skipped` line
    alone is not actionable; the blocker line names the Failed node and its engine
    error so no follow-up status-probe call is ever needed.
    """
    output_smoke = report.get("outputSmoke") or []
    if output_smoke:
        print(f"{indent}Outputs:")
        for row in output_smoke:
            columns = row.get("columns") or []
            columns_text = ", ".join(columns) if columns else "n/a"
            print(
                f"{indent}  - {row.get('outputName')}: {row.get('status')} "
                f"({row.get('rowCount')} row(s)); columns: {columns_text}"
            )
    for c in report.get("checks") or []:
        mark = "ok " if c.get("ok") else ("FAIL" if c.get("severity") == ERROR else "warn")
        print(f"{indent}[{mark}] {c.get('check')}: {c.get('detail')}")
    blockers = (report.get("previewSkipped") or {}).get("upstreamBlockers") or {}
    for target_name, blocker in blockers.items():
        print(
            f"{indent}[FAIL] root-cause for {target_name}: "
            f"{blocker.get('name')} [{blocker.get('status')}] — {blocker.get('detail')}"
        )


def _nearest_upstream_non_ready(target_id: str, nodes: list[dict], statuses: dict[str, dict]) -> dict | None:
    """Return the actionable upstream blocker for a non-Ready target.

    Runtime smoke often reports a terminal as `Skipped` while the actual blocker is
    upstream. A `Skipped` node is a SYMPTOM — the engine skipped it because something
    above it failed — so the walk continues THROUGH Skipped nodes and prefers the
    first Failed/Error node, which carries the actionable errorMessage (verified
    live: three Skipped terminals traced to one Failed filter with the real engine
    error). Only when no Failed node exists does the nearest non-Ready node answer.
    """
    by_id = _node_by_id(nodes)
    upstream = _upstream_map(nodes)
    queue = list(upstream.get(target_id, []))
    seen = {target_id}
    nearest_non_ready: dict | None = None
    while queue:
        node_id = queue.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        node = by_id.get(node_id)
        status = statuses.get(node_id) or {}
        status_value = status.get("status")
        if node and node.get("type") not in {"group", "text", "outlet"} and status_value != READY_STATUS:
            entry = {
                "nodeId": node_id,
                "name": node.get("name"),
                "status": status_value,
                "detail": _status_message(status),
            }
            if status_value not in {"Skipped", None}:
                return entry  # the root cause, with its engine error message
            if nearest_non_ready is None:
                nearest_non_ready = entry
        queue.extend(upstream.get(node_id, []))
    return nearest_non_ready


def _status_message(status: dict) -> str:
    value = status.get("status")
    if value == "Ready":
        return "Ready"
    detail = status.get("errorMessage") or status.get("message") or status.get("reason") or ""
    return f"{value} — {detail}" if detail else str(value)


def _runtime_smoke_summary(targets: list[dict], results: dict[str, tuple[dict, dict]]) -> dict:
    failed_nodes = []
    not_ready_nodes = []
    for node in targets:
        node_result = (results.get(node["id"]) or ({}, {}))[1]
        status = node_result.get("status") or {}
        status_value = status.get("status")
        row = {
            "nodeId": node.get("id"),
            "name": node.get("name"),
            "status": status_value,
            "detail": _status_message(status),
        }
        if status_value in FAILED_STATUSES:
            failed_nodes.append(row)
        elif status_value != "Ready":
            not_ready_nodes.append(row)
    return {
        "status": "pass" if not failed_nodes and not not_ready_nodes else "fail",
        "checkedNodes": [{"nodeId": n.get("id"), "name": n.get("name")} for n in targets],
        "failedNodes": failed_nodes,
        "notReadyNodes": not_ready_nodes,
    }


def _output_smoke_rows(targets: list[dict], results: dict[str, tuple[dict, dict]]) -> list[dict]:
    rows = []
    for node in targets:
        if node.get("type") != "destination":
            continue
        result = (results.get(node["id"]) or ({}, {}))[1]
        status = result.get("status") or {}
        output = result.get("output") or {}
        rows.append({
            "outputName": node.get("name") or node.get("id"),
            "nodeId": node.get("id"),
            "status": status.get("status"),
            "rowCount": output.get("rowCount", output.get("numRows")),
            "columns": _schema_names(output.get("schema")),
        })
    return rows


def persistence_check(imported_nodes: list[dict], live_nodes: list[dict]) -> tuple[bool, str]:
    imported_names = [n.get("name") for n in imported_nodes]
    live_names = [n.get("name") for n in live_nodes]
    imported_count = len(imported_nodes)
    live_count = len(live_nodes)
    ok = imported_count == live_count and Counter(imported_names) == Counter(live_names)
    detail = f"source JSON nodes.length={imported_count}, live recipe nodes.length={live_count}"
    if not ok:
        imported_counter = Counter(imported_names)
        live_counter = Counter(live_names)
        imported_only = sorted((imported_counter - live_counter).elements())
        live_only = sorted((live_counter - imported_counter).elements())
        detail += f"; imported-only={imported_only}, live-only={live_only}"
    return ok, detail


def inspect(flow_url: str, *, imported_path: str | None, expect_columns: list[str] | None,
            checkpoints: list[str], sample_tier: str, timeout: int, skip_terminals: bool,
            recipe: dict | None = None, recipe_json: Path | None = None,
            expected_outputs: list[dict] | None = None,
            force_analyze: bool = False) -> dict:
    """Inspect a live flow against its recipe.

    The recipe is supplied, not fetched: pass `recipe` (an already-loaded dict, which is how
    `workflow/evidence.py` hands over the post-write recipe it was given) or `recipe_json` (a path
    to the MCP `fetch` result). Preview/status still use the API.
    """
    checks: list[tuple[str, bool, str, str]] = []  # (check, ok, detail, severity)

    su = api.parse_savant_url(flow_url)
    if su.kind != "flow" or not su.flow_id:
        raise SystemExit("workflow inspect requires a Savant flow URL (.../flow/{flowId}).")
    ctx = api.discover_session(su.namespace, origin=su.origin)
    if recipe is None:
        recipe = load_recipe(recipe_json, flag="--recipe-json")
    assert_flow_id(recipe, su.flow_id, flag="--recipe-json")
    live_nodes = [n for n in api.recipe_nodes(recipe) if isinstance(n, dict)]

    # 1. Persistence vs the imported JSON (import remaps ids but preserves names).
    if imported_path:
        imp = json.loads(Path(imported_path).read_text(encoding="utf-8"))
        imp_nodes = [n for n in (imp.get("nodes") or []) if isinstance(n, dict)]
        ok, detail = persistence_check(imp_nodes, live_nodes)
        checks.append(("persistence", ok, detail, ERROR))

    # 2. Pick checkpoints: terminals (unless skipped) plus any caller-named stages.
    targets: list[dict] = [] if skip_terminals else list(_terminals(live_nodes))
    target_ids = {t["id"] for t in targets}
    for name in checkpoints:
        n = _by_name(live_nodes, name)
        if n is None:
            checks.append((f"checkpoint:{name}", False, "named checkpoint not found in flow", ERROR))
        elif n["id"] not in target_ids:
            targets.append(n); target_ids.add(n["id"])
    for output in expected_outputs or []:
        name = _expected_output_node_name(output)
        if not name:
            checks.append(("output-contract", False, "expected output is missing output_name/verification_node_name", ERROR))
            continue
        n = _by_name(live_nodes, name)
        if n is None:
            checks.append((f"output-contract:{name}", False, "expected output node not found in flow", ERROR))
        elif n["id"] not in target_ids:
            targets.append(n); target_ids.add(n["id"])

    # 3. Runtime smoke first. This is deliberately status-only: after create/save succeeded, check
    #    whether requested checkpoints compute to Ready before touching preview/schema endpoints.
    #    That makes transform/config failures surface immediately instead of being hidden behind a
    #    slow or doomed output preview call. After an API recipe edit, force_analyze avoids stale
    #    Ready previews that have not yet been invalidated by the UI's Apply path.
    results: dict[str, tuple[dict, dict]] = {}
    try:
        fetched = api.analyze_and_fetch_many(
            ctx, recipe, su.flow_id, [n["id"] for n in targets],
            sample_tier=sample_tier, timeout_seconds=timeout, reuse_ready=not force_analyze,
            fetch_outputs=False,
        )
    except Exception as exc:  # noqa: BLE001 — a batch-level failure marks every checkpoint failed
        fetched = {n["id"]: {"status": {"status": "Error", "errorMessage": str(exc)}} for n in targets}
    for n in targets:
        r = fetched.get(n["id"]) or {"status": {"status": "Error", "errorMessage": "no result"}}
        results[n["id"]] = (n, r)
        st = r.get("status") or {}
        status = st.get("status")
        ok = status == "Ready"
        checks.append((f"node-ok:{n.get('name')}", ok,
                       _status_message(st), ERROR))

    runtime_smoke = _runtime_smoke_summary(targets, results)
    failed_errors = [c for c in checks if not c[1] and c[3] == ERROR]
    if failed_errors:
        try:
            status_map = api.node_status_map(api.graph_status(ctx, su.flow_id))
        except Exception:  # noqa: BLE001 - diagnostics should not mask the main failure.
            status_map = {
                node_id: (result.get("status") or {})
                for node_id, (_node, result) in results.items()
            }
        upstream_blockers = {}
        for target in targets:
            target_status = (results.get(target["id"]) or ({}, {}))[1].get("status") or {}
            if target_status.get("status") == READY_STATUS:
                continue
            blocker = _nearest_upstream_non_ready(target["id"], live_nodes, status_map)
            if blocker:
                upstream_blockers[target.get("name") or target["id"]] = blocker
        return {
            "flowId": su.flow_id,
            "overall": "fail",
            "runtimeSmoke": runtime_smoke,
            "outputSmoke": _output_smoke_rows(targets, results),
            "previewSkipped": {
                "reason": "runtime-smoke failed; output previews/contracts were not attempted",
                "upstreamBlockers": upstream_blockers,
            },
            "checks": [{"check": c, "ok": ok, "severity": sev, "detail": d} for c, ok, d, sev in checks],
            "rows": {},
        }

    # 4. Runtime smoke passed; now read output only for Ready checkpoints.
    for n in targets:
        raw_output = api.fetch_node_output(ctx, su.flow_id, n["id"], sample_tier=sample_tier)
        results[n["id"]][1]["output"] = api.summarize_node_output(raw_output)

    # 5. Output contract: terminal/destination schema == expected columns.
    if expected_outputs:
        for output in expected_outputs:
            output_name = str(output.get("output_name") or _expected_output_node_name(output) or "output")
            node_name = _expected_output_node_name(output)
            out_node = _by_name(targets, node_name)
            if out_node is None:
                continue
            output_result = results[out_node["id"]][1].get("output") or {}
            cols = _schema_names(output_result.get("schema"))
            expected = _expected_output_columns(output)
            required_checks = output.get("required_checks")
            checks_to_run = required_checks if isinstance(required_checks, list) and required_checks else ["columns_exact_order", "row_count_nonzero", "no_node_errors"]
            grain = output.get("expected_grain")
            grain_detail = f"; grain={grain}" if isinstance(grain, str) and grain.strip() else ""
            if "columns_exact_order" in checks_to_run:
                ok = cols == expected
                checks.append((f"output-contract:{output_name}:columns_exact_order", ok, f"expected {expected}; got {cols}{grain_detail}", ERROR))
            elif "columns_present" in checks_to_run:
                missing = [column for column in expected if column not in cols]
                checks.append((f"output-contract:{output_name}:columns_present", not missing, f"missing {missing}; got {cols}{grain_detail}", ERROR))
            if "row_count_nonzero" in checks_to_run:
                rc = output_result.get("rowCount", output_result.get("numRows"))
                checks.append((f"output-contract:{output_name}:row_count_nonzero", rc is None or rc > 0, f"rowCount={rc}{grain_detail}", ERROR))
            if "no_node_errors" in checks_to_run:
                st = results[out_node["id"]][1].get("status") or {}
                checks.append((f"output-contract:{output_name}:no_node_errors", st.get("status") == "Ready", _status_message(st), ERROR))
    elif expect_columns:
        dests = [n for n in targets if n.get("type") == "destination"]
        out_node = dests[0] if dests else (targets[0] if len(targets) == 1 else None)
        if out_node is None:
            checks.append(("output-contract", False,
                           "no single terminal/destination to check (name it with --checkpoint)", ERROR))
        else:
            cols = _schema_names((results[out_node["id"]][1].get("output") or {}).get("schema"))
            ok = cols == list(expect_columns)
            checks.append(("output-contract", ok, f"expected {list(expect_columns)}; got {cols}", ERROR))

    # 6. Row-count sanity: a Ready checkpoint with 0 rows is a likely silent collapse (WARN).
    for nid, (n, r) in results.items():
        out = r.get("output") or {}
        rc = out.get("rowCount", out.get("numRows"))
        if (r.get("status") or {}).get("status") == "Ready" and rc == 0:
            checks.append((f"row-sanity:{n.get('name')}", False, "0 rows — possible unintended collapse", WARN))

    failed_errors = [c for c in checks if not c[1] and c[3] == ERROR]
    report = {
        "flowId": su.flow_id,
        "overall": "pass" if not failed_errors else "fail",
        "runtimeSmoke": runtime_smoke,
        "outputSmoke": _output_smoke_rows(targets, results),
        "previewSamples": {
            n.get("name") or n.get("id"): (r.get("output") or {})
            for _, (n, r) in results.items()
        },
        "checks": [{"check": c, "ok": ok, "severity": sev, "detail": d} for c, ok, d, sev in checks],
        "rows": {n.get("name"): (r.get("output") or {}).get("rowCount", (r.get("output") or {}).get("numRows"))
                 for _, (n, r) in results.items()},
    }
    return report


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("flow_url", help="Savant flow URL, e.g. https://app.savantlabs.io/en/app/flow/{id}?rns={ns}")
    p.add_argument("--recipe-json", type=Path, required=True,
                   help="The flow's live recipe, fetched with the MCP `fetch` tool on "
                        "savant://workflow/{flowId}.")
    p.add_argument("--imported-json", help="The workflow JSON that was imported (for the persistence check).")
    p.add_argument("--expect-columns", help="Comma-separated expected final output columns, in order.")
    p.add_argument("--expected-outputs-json", help="JSON list/object of output contracts, or a handoff containing builder_preflight.output_destination_plan.outputs.")
    p.add_argument("--checkpoint", action="append", default=[], help="Node NAME to verify (repeatable).")
    p.add_argument("--skip-terminals", action="store_true", help="Only verify named checkpoints (skip auto terminals).")
    # The verify pass always computes, so it defaults to `interactive` (1k). `--mode analyze`
    # validates a checkpoint on full data. `--force-analyze` survives as a hidden alias.
    runmode.add_run_mode_args(p, default="interactive", legacy_analyze_flag=None, legacy_force_analyze=True)
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--post-save-recipe-path", type=Path,
                   help="Override where the re-fetched live workflow JSON is written.")
    p.add_argument("--no-post-save-recipe", action="store_true",
                   help="Skip writing the re-fetched live workflow JSON.")
    p.add_argument("--output-path", type=Path, help="Where to write the JSON report.")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def default_output_path(flow_id: str) -> Path:
    return workspace_tmp("workflow-inspections", f"{flow_id}.inspect.json")


def main(argv=None) -> int:
    args = parse_args(argv)
    expect = [c.strip() for c in args.expect_columns.split(",")] if args.expect_columns else None
    expected_outputs = load_expected_outputs(args.expected_outputs_json)
    mode = runmode.resolve_mode(args, default="interactive")
    from workflow import evidence as workflow_evidence

    su = api.parse_savant_url(args.flow_url)
    if su.kind != "flow" or not su.flow_id:
        raise SystemExit("workflow inspect requires a Savant flow URL (.../flow/{flowId}).")
    ctx = api.discover_session(su.namespace, origin=su.origin)
    live_recipe = load_recipe(args.recipe_json, flag="--recipe-json")
    assert_flow_id(live_recipe, su.flow_id, flag="--recipe-json")
    live_recipe_path = (
        None if args.no_post_save_recipe
        else args.post_save_recipe_path or workflow_evidence.default_post_write_recipe_path(su.flow_id, "inspect")
    )
    evidence = workflow_evidence.collect_post_write_evidence(
        ctx=ctx,
        flow_url=args.flow_url,
        flow_id=su.flow_id,
        operation="inspect",
        recipe=live_recipe,
        imported_path=args.imported_json,
        expect_columns=expect,
        expected_outputs=expected_outputs,
        checkpoints=args.checkpoint,
        sample_tier=runmode.sample_tier(mode),
        timeout=args.timeout_seconds,
        terminal_preview=not args.skip_terminals,
        force_analyze=getattr(args, "_legacy_force_analyze", False),
        post_write_recipe_path=live_recipe_path,
    )
    evidence.pop("refetchedRecipe", None)
    report = evidence.get("inspect") or {"flowId": su.flow_id, "overall": "fail", "checks": []}
    report["savedRecipePath"] = evidence.get("savedRecipePath")
    report["validation"] = evidence.get("validation")
    report["evidence"] = {k: v for k, v in evidence.items() if k not in {"savedRecipePath", "postSaveRecipePath", "inspect", "validation"}}
    api.save_json(report, args.output_path or default_output_path(str(report.get("flowId") or "workflow")))
    if not args.quiet:
        print(f"INSPECT {report['flowId']}: {report['overall'].upper()}")
        if report.get("savedRecipePath"):
            print(f"  [ok ] live-workflow-json: {report['savedRecipePath']}")
        validation = report.get("validation") or {}
        if validation and not validation.get("skipped"):
            mark = "ok " if validation.get("ok") else "FAIL"
            print(
                f"  [{mark}] validation: "
                f"{validation.get('errorCount', 0)} error(s), {validation.get('warningCount', 0)} warning(s)"
            )
        print_summary_lines(report)
    return 0 if evidence.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
