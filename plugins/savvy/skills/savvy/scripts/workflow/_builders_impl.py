"""node_builders — a small, tested vocabulary for assembling valid Savant workflow JSON.

Design: real Savant filter/transform nodes batch MANY operations in one node (a filter holds
several conditions joined by and/or; one Transform adds columns, renames, retypes, reorders,
and shows/hides all at once). So the op-builders here *compose* into a single node rather than
chaining. Each constructor enforces shape + local invariants in code (edge-both-sides, out_N
ids, CASE compilation, summarize/blend display-name refs, providerId presence, rowLimit int,
drop-via-hiddenFields), so that whole class of error is correct by construction. The `Flow`
object owns ids, edge wiring (both sides), layout, and a `compile()` that runs the deterministic
validator. The library guarantees *shape*; the validator still owns *graph/semantic* correctness
and is the gate for any-origin JSON. Judgment (when/why/which variant) stays in the component
specs; this module only guarantees the emitted JSON is well-formed.

Create vs. edit share one core. Each editable node type factors into a pure `*_config(...)`
builder (the "language of changes": filter conditions, edit ops, blend keys, gen_ai prompt) used
two ways: the create constructor (`filter_node`, `edit_node`, `blend`, `gen_ai`) wraps that config
in a NEW node envelope (fresh id, empty wiring), and the `*_update(existing, ...)` adapter MERGES the
SAME freshly generated config onto an EXISTING recipe node, preserving its id/inlets/outlets/
position/canvasConfig AND any config fields the builder does not model (the create path may not emit
them and the live app may add fields we don't know about — edit must never silently drop a real
setting). So the editor changes a node the same deterministic way the builder creates one — no
per-component edit JSON — coupled fields (an edit node's expression/pipeline/lookup) always
regenerate together, and unmodeled fields ride through untouched. See `update_config` and `*_update`.
"""
from __future__ import annotations
import copy, hashlib, json, os, re, random, warnings, html as _html
from pathlib import Path
from typing import Any

from savant_api.fileio import save_json, workspace_tmp
from contracts.output_destination import (
    destination_description,
    destination_file_name,
    normalize_destination_type,
)
from contracts.ai_provider import DEFAULT_AI_PROVIDER_ID, provider_id_or_default
from contracts.source_plan import (
    connector as source_plan_connector,
    dataset_id as source_plan_dataset_id,
    join_key_normalizations as source_plan_join_key_normalizations,
    observed_schema as source_plan_observed_schema,
    row_count as source_plan_row_count,
    validate_source_plan,
)
from contracts.source_profile import sample_values
try:
    from . import layout_solver as _layout_solver
    from . import outlets as _outlets
except ImportError:  # Direct module import when this folder is on sys.path.
    import layout_solver as _layout_solver  # type: ignore
    import outlets as _outlets  # type: ignore

__all__ = [
    "Flow",
    "adapter",
    "adapter_specs",
    "api_service",
    "blend",
    "blend_outlet",
    "blend_update",
    "cond",
    "deduplicate",
    "deduplicate_update",
    "default_schema_hints_output_path",
    "default_workflow_output_path",
    "description_from_plan",
    "destination_csv",
    "destination_file",
    "destination_from_plan",
    "edit_node",
    "edit_update",
    "explode_node",
    "filter_expression",
    "filter_node",
    "filter_outlet",
    "filter_update",
    "format_node",
    "fuzzy_match",
    "gen_ai",
    "gen_ai_json_flatten",
    "gen_ai_node_for_json_flatten",
    "gen_ai_output_field",
    "gen_ai_update",
    "hierarchy",
    "json_node",
    "json_update",
    "keep_only_columns",
    "multi_stack",
    "op_arith",
    "op_avg",
    "op_cast",
    "op_case",
    "op_const",
    "op_count_if",
    "op_default_constant",
    "op_date_diff",
    "op_expr",
    "op_excel_serial_date",
    "op_json_field",
    "op_json_number",
    "op_normalized_join_key",
    "op_rename",
    "op_retype",
    "op_transform",
    "op_window",
    "pdfilter_node",
    "pivot",
    "pivot_update",
    "rollup",
    "rollup_update",
    "sample_top",
    "schema_hints",
    "source",
    "source_prep_join_key_ops",
    "source_unit_from_plan",
    "split_node",
    "standardized_source",
    "summarize",
    "summarize_update",
    "text",
    "unpivot",
    "unpivot_update",
    "update_config",
    "vision",
    "vision_update",
    "write_workflow",
    "xml_node",
]

# ---------------------------------------------------------------- helpers

def _field_id(name: str) -> str:
    """Savant field id = lowercase(name) with non-alphanumerics -> '_'."""
    return re.sub(r"[^a-z0-9]", "_", str(name).lower())

def _field_control_ref(name: str) -> str:
    """Reference for id-style controls such as hiddenFields/orderedFields.

    Normal fields use normalized ids. Live Blend duplicate fields are the exception:
    Savant emits display names like `Amount (rhs)` and exact ids like `Amount_2`,
    and id-style controls only hide/reorder them when that exact display/id value is
    preserved. Keep this paired with validator.derive_id's duplicate-collision caveat:
    right-side Blend collisions are not derivable from display names, so they must pass
    through verbatim here and be modeled explicitly in the validator.
    """
    text = str(name)
    if re.fullmatch(r".+ \(rhs(?: \d+)?\)", text):
        return text
    if re.fullmatch(r".+_\d+", text) and _field_id(text) != text:
        return text
    return _field_id(text)

def _field_name_ref(value: Any) -> str:
    """Reference for the id-style shape controls (`hiddenFields`/`orderedFields`): emit the
    DISPLAY NAME verbatim, never a derived id.

    Real Savant exports put names here (`hiddenFields: ["Response Body Split 2"]`,
    `orderedFields: ["Last Updated (UTC)", ...]`), and the Edit launcher resolves these by
    name OR id, matching the full string case-insensitively (`SparkUtils.findField`). A derived
    id only matches when it equals the column's internal id, which is NOT guaranteed — e.g.
    `Last Updated (UTC)` has the stored id `last_updated`, not `last_updated__utc_`, so a derived
    id matches neither name nor id and the hide/reorder SILENTLY no-ops. Names are what the user
    sees and consented to; ids are internal, parquet-friendly handles. For a Blend right-side
    duplicate, pass the disambiguated display name (`Amount (rhs)`), which is unique on its own.
    """
    return str(value)

def _expr_field(name: str) -> str:
    """Field reference for Savant expression strings generated from structured builder inputs."""
    text = str(name)
    if "`" in text:
        raise ValueError(f"field names containing backticks are not supported in expressions: {text!r}.")
    return f"`{text}`"

def _expr_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return json.dumps(str(value))

def _nid(node_type: str, name: str) -> str:
    return f"{node_type}_{hashlib.md5(name.encode()).hexdigest()[:6]}"

def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "workflow"

def _safe_filename(value: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "-", str(value)).strip()
    return name or "workflow"

def default_workflow_output_path(name: str) -> Path:
    """Default persisted workflow JSON path: ``<workspace>/tmp/<ai-session-id>/<slug>/<Name>.json``."""
    return workspace_tmp(_slug(name), f"{_safe_filename(name)}.json")

def default_schema_hints_output_path(workflow_path: str | Path) -> Path:
    """Default validator sidecar path next to a workflow JSON file."""
    path = Path(workflow_path)
    return path.with_name(f"{path.stem}.schema-hints.json")

PLAN_SECTION_HEADING = "## Process"


def description_from_plan(handoff_evidence: dict) -> str:
    """Format the APPROVED Planner plan as the workflow description's documentation body.

    The user reviews and approves a process plan with the Planner; that plan should be the
    workflow's living documentation, not a parallel artifact that drifts. This renders the
    confirmed `workflow_plan_checkpoint` blocks, the planned outputs, and the material
    assumptions as Markdown (Savant renders workflow descriptions as Markdown). The builder's
    own one-paragraph business summary stays as the lead; this is appended after it by
    `write_workflow(...)`.
    """
    sections = handoff_evidence.get("sections") or {}
    bp = sections.get("builder_preflight") or handoff_evidence.get("builder_preflight") or {}
    wpc = bp.get("workflow_plan_checkpoint") or {}
    odp = bp.get("output_destination_plan") or {}
    lines: list[str] = [PLAN_SECTION_HEADING, ""]
    for i, block in enumerate(wpc.get("process_blocks") or [], 1):
        title = str(block.get("title") or "").strip()
        purpose = str(block.get("business_purpose") or "").strip().rstrip(".")
        if title:
            lines.append(f"{i}. **{title}** — {purpose}." if purpose else f"{i}. **{title}**")
    outputs = odp.get("outputs") or []
    if outputs:
        lines += ["", "## Outputs", ""]
        for out in outputs:
            name = str(out.get("output_name") or "").strip()
            purpose = str(out.get("business_purpose") or "").strip().rstrip(".")
            grain = str(out.get("expected_grain") or "").strip()
            entry = f"- **{name}**"
            if purpose:
                entry += f" — {purpose}."
            if grain:
                entry += f" One row per {grain}." if not grain.lower().startswith("one row") else f" {grain[0].upper()}{grain[1:]}."
            lines.append(entry)
    assumptions = wpc.get("material_assumptions") or []
    if assumptions:
        lines += ["", "## Assumptions", ""]
        lines.extend(f"- {str(a).strip()}" for a in assumptions)
    return "\n".join(lines).strip()


def _check_builder_preflight_gate(planner_handoff: str | Path | None) -> dict:
    """Load a Planner -> Builder handoff and require the Builder precheck gate to pass."""
    if planner_handoff is None:
        raise ValueError(
            "Persisting Builder workflow JSON requires planner_handoff=<planner_to_builder.handoff.json>. "
            "Run the Planner handoff through the Builder precheck gate before writing artifacts."
        )
    handoff_path = Path(planner_handoff)
    try:
        evidence = json.loads(handoff_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Planner handoff does not exist: {handoff_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Planner handoff is not valid JSON: {handoff_path}: {exc}") from exc
    if not isinstance(evidence, dict):
        raise ValueError(f"Planner handoff must be a JSON object: {handoff_path}")

    from validators import stage_gate

    result = stage_gate.evaluate("builder", "precheck", evidence, api_check="skip")
    if not result.get("ok"):
        actions = result.get("nextActions")
        if isinstance(actions, list) and actions:
            detail = "; ".join(str(action) for action in actions)
        else:
            detail = json.dumps(result, sort_keys=True)
        raise ValueError(f"Builder precheck gate failed for {handoff_path}: {detail}")
    return evidence

def _builder_processing_input_errors(workflow: dict) -> list[str]:
    """Catch builder-authored graph quality blockers before writing an artifact."""
    from validators.workflow import mergeable_pair_messages, node_label, node_requires_upstream_input

    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    if not isinstance(nodes, list):
        return []
    by_id = {node.get("id"): node for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for source_id, node in by_id.items():
        for outlet in node.get("outlets") or []:
            if not isinstance(outlet, dict):
                continue
            for target in outlet.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                target_id = target.get("target")
                if isinstance(target_id, str) and target_id in incoming:
                    incoming[target_id].append(source_id)

    errors = [
        f"Processing node `{node_label(node)}` has no upstream input."
        for node_id, node in by_id.items()
        if node_requires_upstream_input(node) and not incoming.get(node_id)
    ]
    errors.extend(mergeable_pair_messages(workflow))
    return errors

def _field(name: str, dt: str = "string", field_id_override: str | None = None) -> dict:
    """A `field` reference inside a lookup/expression tree. `fieldId` is the NORMALIZED Savant
    column id (lowercase/digits/underscore) and `fieldName` is the display name — matching the
    id/name split Savant uses everywhere (e.g. blend `lhsMetadata.id` vs `lhs`). Pass
    `field_id_override` for a known live id that differs from the derived one (e.g. a post-join
    duplicate like `amount_2`). Note: the engine runs `pipeline.steps` by column NAME via
    `src_cols`; this `fieldId` drives the lookup/expression representation and UI binding."""
    return {"type": "field", "fieldId": field_id_override or _field_id(name),
            "fieldName": name, "dataType": dt}

def _target_col(name: str, dt: str | None = None) -> dict:
    """Output column shape: normalized machine id, preserved business display name."""
    col = {"id": _field_id(name), "name": name}
    if dt is not None:
        col["dataType"] = dt
    return col

def _const(value: Any, dt: str = "string") -> dict:
    return {"type": "constant", "value": value, "dataType": dt}

def _node(node_type: str, name: str, config: dict, *, inlets: int = 1, outlets: int = 1,
          description: str = "") -> dict:
    return {
        "id": _nid(node_type, name), "name": name, "type": node_type,
        "inlets": [{"id": f"in_{i}", "source": None, "sourceOutlet": "out_0", "sources": []}
                   for i in range(inlets)],
        "outlets": [{"id": f"out_{i}", "targets": []} for i in range(outlets)],
        "description": description, "config": config,
    }

# ---------------------------------------------------------------- sources / outputs

def _profile_fields_from_observed_schema(observed_schema: list[dict] | None) -> list[dict]:
    fields: list[dict] = []
    for column in observed_schema or []:
        if not isinstance(column, dict):
            continue
        name = column.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        field: dict[str, Any] = {"id": column.get("id") or _field_id(name), "name": name}
        data_type = column.get("dataType")
        if isinstance(data_type, str) and data_type.strip():
            field["dataType"] = data_type
        samples = sample_values(column)
        if samples:
            field["sampleValues"] = list(samples)
        fields.append(field)
    return fields


def _source_description(name: str, connector: str, source_kind: str | None = None, business_role: str = "") -> str:
    role = str(business_role or "").strip()
    kind = str(source_kind or "").strip().replace("_", " ")
    connector_label = str(connector or "dataset").strip()
    if role:
        return f"Load {name} as the {role}; this is the source-of-truth input for the downstream workflow steps."
    if kind:
        return f"Load {name} as the {kind} source from the {connector_label} dataset for downstream workflow processing."
    return f"Load {name} from the {connector_label} dataset as a source input for downstream workflow processing."


def source(name: str, dataset_id: str, connector: str, dtype: str | None = None, description: str = "", *,
           observed_schema: list[dict] | None = None, row_count: int | None = None) -> dict:
    if not description:
        description = _source_description(name, connector)
    # The LIVE-PROVEN source config is exactly {id, name, type, connector}. Any extra
    # config key — `fields`, `rowCount` — makes Savant DROP the source node on import
    # (verified live: all decorated variants were silently removed; the bare shape
    # persisted). Profiling evidence therefore rides on the node under a private key
    # that `Flow.to_dict()` lifts into workflow-level `sourceProfiles`, where the
    # validator reads it and import metadata handling is irrelevant.
    cfg = {"id": dataset_id, "name": name, "type": dtype or connector, "connector": connector}
    node = _node("source", name, cfg, inlets=0, description=description)
    evidence: dict[str, Any] = {}
    fields = _profile_fields_from_observed_schema(observed_schema)
    if fields:
        evidence["fields"] = fields
    if isinstance(row_count, int) and not isinstance(row_count, bool) and row_count >= 0:
        evidence["rowCount"] = row_count
    if evidence:
        node["_profileEvidence"] = evidence
    return node

def destination_csv(name: str, file_name: str, sort: tuple[str, str] | None = None, description: str = "") -> dict:
    if not description:
        description = f"Native Savant CSV output for {name}."
    cfg = {"id": _field_id(file_name or name), "mode": "update", "name": "CSV",
           "type": "csv", "connector": "csv"}
    if sort:
        cfg["sortConfig"] = [[sort[0], sort[1]]]
    return _node("destination", name, cfg, outlets=0, description=description)

_FILE_DESTINATION_CONNECTORS = {"onedrive", "googledrive"}
_FILE_DESTINATION_FILE_TYPES = {"CSV", "EXCEL"}


def destination_file(
    name: str,
    *,
    connector: str,
    system_id: str,
    folder_link: str,
    file_name: str,
    file_type: str = "EXCEL",
    file_name_mode: str = "static",
    file_name_field: str | None = None,
    tab_name: str | None = None,
    tab_name_mode: str = "static",
    tab_name_field: str | None = None,
    sub_folder_name: str = "",
    sub_folder_name_mode: str = "static",
    sub_folder_name_field: str | None = None,
    top_left_cell: str = "",
    subsequent_mode: str = "replace",
    format_from_template: bool = False,
    sort: tuple[str, str] | None = None,
    description: str = "",
) -> dict:
    """Write the flow output to a file in a connected **system** (OneDrive / Google Drive).

    The destination binds to the system by `connector` (the system must already exist in the
    workspace — see ../substrate/system-substrate.md; the skills never create or authenticate it).
    `folder_link` is the target folder URL in that system (SharePoint share URL for OneDrive, a
    drive.google.com folder URL for Google Drive) — an environment binding the user supplies.

    Tabs: `tab_name_mode="static"` writes one tab (`tab_name`); `"field"` writes one tab per value
    of `tab_name_field` (must be a real upstream column). `file_name_mode` works the same for
    one-file vs file-per-value. `subsequent_mode` is `replace` (default) or `append`."""
    connector = str(connector).strip().lower()
    if connector not in _FILE_DESTINATION_CONNECTORS:
        raise ValueError(f"destination_file connector must be one of {sorted(_FILE_DESTINATION_CONNECTORS)}, got {connector!r}.")
    if not str(system_id or "").strip():
        raise ValueError(
            "destination_file requires system_id — the connected system's id. It becomes the node's "
            "config.id, which is how the destination binds to the system (discover/verify it via "
            "system-substrate.md; the system must already exist)."
        )
    file_type = str(file_type).strip().upper()
    if file_type not in _FILE_DESTINATION_FILE_TYPES:
        raise ValueError(f"destination_file file_type must be one of {sorted(_FILE_DESTINATION_FILE_TYPES)}, got {file_type!r}.")
    if not str(folder_link or "").strip():
        raise ValueError("destination_file requires folder_link (the target folder URL in the connected system).")
    if not str(file_name or "").strip():
        raise ValueError("destination_file requires file_name (without extension).")
    if file_name_mode not in ("static", "field"):
        raise ValueError("destination_file file_name_mode must be 'static' or 'field'.")
    if file_name_mode == "field" and not str(file_name_field or "").strip():
        raise ValueError("destination_file file_name_mode='field' requires file_name_field (a real upstream column).")
    if tab_name_mode not in ("static", "field"):
        raise ValueError("destination_file tab_name_mode must be 'static' or 'field'.")
    if tab_name_mode == "field" and not str(tab_name_field or "").strip():
        raise ValueError("destination_file tab_name_mode='field' requires tab_name_field (a real upstream column).")
    if sub_folder_name_mode not in ("static", "field"):
        raise ValueError("destination_file sub_folder_name_mode must be 'static' or 'field'.")
    if sub_folder_name_mode == "field" and not str(sub_folder_name_field or "").strip():
        raise ValueError("destination_file sub_folder_name_mode='field' requires sub_folder_name_field.")
    if subsequent_mode not in ("replace", "append"):
        raise ValueError("destination_file subsequent_mode must be 'replace' or 'append'.")

    file_system_config: dict = {
        "fileType": file_type,
        "folderLink": str(folder_link).strip(),
        "fileName": "" if file_name_mode == "field" else str(file_name).strip(),
        "fileNameMode": file_name_mode,
        "fileNameField": str(file_name_field).strip() if file_name_mode == "field" else "",
        "tabName": "" if tab_name_mode == "field" else str(tab_name or file_name or name).strip(),
        "tabNameMode": tab_name_mode,
        "tabNameField": str(tab_name_field).strip() if tab_name_mode == "field" else "",
        "subFolderName": str(sub_folder_name or "").strip(),
        "subFolderNameMode": sub_folder_name_mode,
        "subFolderNameField": str(sub_folder_name_field).strip() if sub_folder_name_mode == "field" else "",
        "topLeftCell": str(top_left_cell or "").strip(),
        "subsequentMode": subsequent_mode,
        "formatFromTemplate": bool(format_from_template),
        "flatFileConfig": {
            "headerless": False,
            "fileWriterProps": {"delimiter": ",", "qualifier": '"', "escape": "\\", "charset": "UTF_8"},
        },
    }
    if not description:
        kind = "Excel workbook" if file_type == "EXCEL" else "CSV file"
        where = "OneDrive" if connector == "onedrive" else "Google Drive"
        description = f"Write {name} as an {kind} to {where}."
    cfg = {
        "id": str(system_id).strip(),   # binds the destination to the connected system
        "name": name,
        "type": connector,
        "connector": connector,
        "fileSystemConfig": file_system_config,
    }
    if sort:
        cfg["sortConfig"] = [[sort[0], sort[1]]]
    return _node("destination", name, cfg, outlets=0, description=description)


def destination_from_plan(output_plan: dict, sort: tuple[str, str] | None = None) -> dict:
    """Compile one Planner output object into a supported destination node.

    Passing the full output object keeps the Planner/Builder handoff contract intact and avoids
    rediscovering names, fallback type, file name, and node description in separate arguments.
    Supports native Savant CSV and file destinations to connected systems (OneDrive / Google Drive).
    """
    if not isinstance(output_plan, dict):
        raise ValueError("destination_from_plan requires an output destination plan object.")
    name = output_plan.get("output_name")
    planned_type = normalize_destination_type(output_plan.get("planned_destination_type"))
    business_purpose = output_plan.get("business_purpose")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("destination_from_plan requires output_name.")
    if not isinstance(business_purpose, str) or not business_purpose.strip():
        raise ValueError("destination_from_plan requires business_purpose.")
    if planned_type == "csv":
        return destination_csv(
            name.strip(),
            destination_file_name(output_plan),
            sort=sort,
            description=destination_description(output_plan),
        )
    if planned_type in _FILE_DESTINATION_CONNECTORS:
        return destination_file(
            name.strip(),
            connector=planned_type,
            system_id=str(output_plan.get("system_id") or "").strip(),
            folder_link=str(output_plan.get("folder_link") or "").strip(),
            file_name=str(output_plan.get("file_name") or name).strip(),
            file_type=str(output_plan.get("file_type") or "EXCEL"),
            file_name_mode=str(output_plan.get("file_name_mode") or "static"),
            file_name_field=output_plan.get("file_name_field"),
            tab_name=output_plan.get("tab_name"),
            tab_name_mode=str(output_plan.get("tab_name_mode") or "static"),
            tab_name_field=output_plan.get("tab_name_field"),
            sub_folder_name=str(output_plan.get("sub_folder_name") or ""),
            sub_folder_name_mode=str(output_plan.get("sub_folder_name_mode") or "static"),
            sub_folder_name_field=output_plan.get("sub_folder_name_field"),
            top_left_cell=str(output_plan.get("top_left_cell") or ""),
            subsequent_mode=str(output_plan.get("subsequent_mode") or "replace"),
            format_from_template=bool(output_plan.get("format_from_template")),
            sort=sort,
            description=destination_description(output_plan),
        )
    raise ValueError(
        f"destination_from_plan supports planned_destination_type 'csv', 'onedrive', or 'googledrive'; got {planned_type!r}."
    )

# ---------------------------------------------------------------- json / reshape

def _json_config(mode: str, input_field: str, keep_input: bool = False) -> dict:
    """Shared config core for a json node. Used by `json_node` (create) and `json_update` (edit)."""
    if mode not in ("flatten", "explode"):
        raise ValueError(f"json mode must be 'flatten' or 'explode', got {mode!r}.")
    cfg = {"mode": mode, "inputField": input_field}
    if mode == "flatten":
        cfg["keepInputField"] = keep_input
    return cfg

def json_node(name: str, mode: str, input_field: str, keep_input: bool = False, description: str = "") -> dict:
    return _node("json", name, _json_config(mode, input_field, keep_input), description=description)


_GEN_AI_OUTPUT_FIELD = "AI Answer"


def gen_ai_output_field() -> str:
    """Well-known GenAI output column consumed by downstream JSON flattening."""
    return _GEN_AI_OUTPUT_FIELD


def gen_ai_json_flatten(
    flow,
    name: str,
    prompt: str,
    input_fields: list[str],
    provider_id: str | None = None,
    row_limit: int = 1000,
    *,
    flatten_name: str | None = None,
    keep_generated: bool = False,
    description: str = "",
    flatten_description: str = "",
) -> str:
    """Create and wire the canonical GenAI JSON extraction unit.

    Returns the JSON flatten node id. Downstream nodes should wire from that handle. The helper owns
    the generated-output field name so callers do not guess the GenAI output column.
    """
    ai_id = flow.add(gen_ai(name, prompt, input_fields, provider_id, row_limit, description=description))
    flat_id = flow.add(json_node(
        flatten_name or f"Flatten {name}",
        "flatten",
        gen_ai_output_field(),
        keep_input=keep_generated,
        description=flatten_description,
    ))
    flow.wire(ai_id, flat_id)
    if hasattr(flow, "_register_unit"):
        flow._register_unit(flat_id, [ai_id, flat_id])
    return flat_id


def gen_ai_node_for_json_flatten(flow, flatten_id: str) -> str:
    """Return the GenAI node id paired with a `gen_ai_json_flatten(...)` handle.

    `gen_ai_json_flatten(...)` returns the JSON flatten node id for downstream wiring. Use this
    helper when attaching schema hints, because expected generated columns belong to the opaque
    GenAI producer, not the JSON flatten node.
    """
    unit = getattr(flow, "_node_units", {}).get(flatten_id, [flatten_id])
    by_id = getattr(flow, "_by_id", {})
    for node_id in unit:
        node = by_id.get(node_id)
        if isinstance(node, dict) and node.get("type") == "gen_ai":
            return node_id
    raise ValueError(f"{flatten_id!r} is not a gen_ai_json_flatten handle in this flow.")

_XML_MODES = ("SELECT", "EXTRACT", "TO_JSON")

def xml_node(name: str, mode: str, input_field: str, path: str | None = None,
             unwrap_tag: bool = True, process_ns: bool = False, description: str = "") -> dict:
    """Select, extract, or convert XML held in a text/binary column (`input_field`, usually
    `Content`). `mode`: SELECT (pull matching elements — requires an XPath `path`), EXTRACT
    (flatten the document to columns), or TO_JSON (convert to a JSON string). `unwrap_tag` strips
    the outer element wrapper; `process_ns` enables namespace processing. Shape verified against
    real Savant exports across all three modes."""
    if mode not in _XML_MODES:
        raise ValueError(f"xml mode must be one of {_XML_MODES}, got {mode!r}.")
    if not input_field:
        raise ValueError("xml requires a non-empty inputField.")
    cfg: dict = {"mode": mode, "inputField": input_field}
    if mode == "SELECT":
        if not path:
            raise ValueError("xml SELECT mode requires a non-empty XPath `path`.")
        cfg["path"] = path
    elif path is not None:
        cfg["path"] = path
    if unwrap_tag:
        cfg["unwrapTag"] = True
    if process_ns:
        cfg["processNs"] = True
    return _node("xml", name, cfg, description=description)

def _pivot_config(pivot_field: str, value_field: str, calc: str = "AVG") -> dict:
    """Shared config core for a pivot. Used by `pivot` (create) and `pivot_update` (edit)."""
    return {"pivotField": pivot_field, "valueField": value_field, "aggregation": {"calc": calc}}

def pivot(name: str, pivot_field: str, value_field: str, calc: str = "AVG", description: str = "") -> dict:
    return _node("pivot", name, _pivot_config(pivot_field, value_field, calc), description=description)

def sample_top(name: str, n: int, sorts: list[tuple[str, str]] | None = None,
               group_by: list[str] | None = None, description: str = "") -> dict:
    return _node("sample", name, {"strategy": "FIRST_N", "n": int(n), "groupBy": group_by or [],
                                  "sorts": [[c, d] for c, d in (sorts or [])]}, description=description)

# ---------------------------------------------------------------- filter (multi-condition)

# Comparison ops: builder op -> (UI conditionalOperator symbol, binary transform operator).
_CMP = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "=", "neq": "!="}
# Text LIKE ops: builder op -> (conditionalOperator, pattern template, sql_like operator). The
# pattern wraps the user's value with SQL wildcards (contains=%v%, starts=v%, ends=%v); NOT
# variants use the `not_like` operator. Verified against real exports.
_LIKE = {"contains": ("LIKE_CONTAINS", "%{v}%", "like"),
         "starts_with": ("LIKE_START", "{v}%", "like"),
         "ends_with": ("LIKE_END", "%{v}", "like"),
         "not_contains": ("NOT LIKE_CONTAINS", "%{v}%", "nlike"),
         "not_starts_with": ("NOT LIKE_START", "{v}%", "nlike"),
         "not_ends_with": ("NOT LIKE_END", "%{v}", "nlike")}
# Unary presence ops (no value): builder op -> (conditionalOperator, unary transform operator).
_NULL = {"is_null": ("IS NULL", "is_null"), "not_null": ("IS NOT NULL", "not_null")}
# Boolean-column ops: builder op -> (conditionalOperator, rhs constant).
_BOOL = {"is_true": ("IS TRUE", True), "is_false": ("IS FALSE", False)}

def cond(field: str, op: str, value=None, dtype: str = "number") -> dict:
    """A single filter condition. op (and what `value` means):
      comparison: gte/lte/gt/lt/eq/neq        — value is the threshold
      text:       contains/starts_with/ends_with (+ not_*) — value is the substring
      presence:   is_empty/not_empty (blank string), is_null/not_null (missing value)
      boolean:    is_true/is_false             — for boolean columns, no value
    `dtype` is the column's data type (string/number/integer/date/datetime/boolean)."""
    # A numeric condition with a string literal compiles to a TEXT operand and the
    # engine fails at runtime ("Unsupported type for operator lte: NUMBER and TEXT")
    # — verified live. Coerce numeric literals deterministically; refuse junk.
    if dtype in {"number", "integer"} and isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                value = int(stripped) if dtype == "integer" else float(stripped)
            except ValueError:
                raise ValueError(
                    f"cond({field!r}, {op!r}): dtype={dtype!r} requires a numeric value, got {value!r}."
                ) from None
    return {"field": field, "op": op, "value": value, "dtype": dtype}

def _cond_parts(c: dict, joiner: str, idx: int, name: str):
    """Return (filter_entry, expr) for one condition.

    ``filter_entry`` is the wizard clause row (the truth field for wizard mode); ``expr`` is the
    equivalent boolean expression (the truth field for expression mode, and reused by ``op_case``).
    The runtime/FE compile these truth fields to a pipeline server-side (PLAT-5786) — the skill does
    not hand-build ``pipeline``/``dataFilterExpr``/``dataFilterLookUp``."""
    field, op, value, dt = c["field"], c["op"], c.get("value"), c.get("dtype", "number")
    lop = "AND" if idx == 0 else joiner.upper()

    def entry(cop, val="", data_type=dt, extra=None):
        e = {"id": _field_id(field), "name": field, "value": val, "dataType": data_type,
             "logicalOperator": lop, "conditionalOperator": cop}
        if extra:
            e.update(extra)
        return e

    if op in _CMP:
        sym = _CMP[op]
        return entry(sym, str(value)), f"{_expr_field(field)} {sym} {_expr_literal(value)}"
    if op in _LIKE:
        cop, tmpl, like_op = _LIKE[op]
        pattern = tmpl.format(v=value)
        return entry(cop, str(value), "string", {"date": ""}), f"{_expr_field(field)} {like_op} {_expr_literal(pattern)}"
    if op in _NULL:
        cop, uop = _NULL[op]
        return entry(cop), f"{uop.upper()}({_expr_field(field)})"
    if op in _BOOL:
        cop, rhs = _BOOL[op]
        return entry(cop, "", "boolean"), f"{_expr_field(field)} = {_expr_literal(rhs)}"
    if op in ("is_empty", "not_empty"):
        cop = "IS_EMPTY" if op == "is_empty" else "NOT IS_EMPTY"
        expr = f"IS_EMPTY({_expr_field(field)})" if op == "is_empty" else f"NOT IS_EMPTY({_expr_field(field)})"
        return entry(cop, "", "string"), expr
    raise ValueError(f"unsupported filter op {op!r}; supported: "
                     f"{sorted(set(_CMP) | set(_LIKE) | set(_NULL) | set(_BOOL) | {'is_empty', 'not_empty'})}.")

def _filter_config(name: str, conditions: list[dict], joiner: str, false_path: bool = False,
                   mode: str = "wizard") -> dict:
    if not conditions:
        raise ValueError("filter needs at least one condition.")
    if joiner not in ("and", "or"):
        raise ValueError(f"filter joiner must be 'and' or 'or', got {joiner!r}.")
    if mode not in ("wizard", "expression"):
        raise ValueError(f"filter mode must be 'wizard' or 'expression', got {mode!r}.")
    entries, exprs = [], []
    for i, c in enumerate(conditions):
        e, ex = _cond_parts(c, joiner, i, name)
        entries.append(e); exprs.append(ex)
    data_expr = exprs[0] if len(conditions) == 1 else f" {joiner.upper()} ".join(f"({e})" for e in exprs)
    # Truth-field-only config. The runtime/FE compile filter[]/rules[] to a pipeline server-side
    # (PLAT-5786); the skill must not hand-build pipeline/dataFilterExpr/dataFilterLookUp. The
    # deprecated cache keys are emitted as cleared (None) so update_config overwrites any stale
    # hand-built caches on an existing node (update_config replaces builder-owned keys wholesale).
    cfg = {"joiner": joiner, "useFalsePath": bool(false_path),
           "pipeline": None, "dataFilterExpr": None, "dataFilterLookUp": None}
    if mode == "wizard":
        # Wizard: clause rows in `filter[]` are the truth field; `rules` stays empty.
        cfg.update({"mode": "wizard", "rules": [], "filter": entries})
    else:
        # Expression: `filter[]` empty; the whole boolean expression lives in `rules[0].expression`.
        cfg.update({"mode": "expression", "filter": [], "rules": [{"expression": data_expr}]})
    return cfg

def filter_node(name: str, conditions: list[dict], joiner: str = "and", false_path: bool = False,
                mode: str = "wizard", description: str = "") -> dict:
    """One in-memory filter node with one or more conditions joined by `joiner` (and/or).

    `mode`: "wizard" (clause rows in `filter[]`, the default) or "expression" (the same conditions
    rendered as a free-form boolean expression in `rules[0].expression`). Both are truth fields the
    runtime/FE compile to a pipeline server-side, so the same operators/functions evaluate either
    way — expression mode just also allows richer free-form expressions in the UI.
    Set `false_path=True` to split into a True branch (kept rows) and a False branch (dropped
    rows); wire each with filter_outlet(flow, filter_id, "true"|"false")."""
    return _node("filter", name, _filter_config(name, conditions, joiner, false_path, mode), description=description)

def pdfilter_node(name: str, conditions: list[dict], joiner: str = "and", false_path: bool = False,
                  mode: str = "wizard", description: str = "") -> dict:
    """Database-pushdown filter (same shape; use when the upstream source is a DB connector)."""
    return _node("pdfilter", name, _filter_config(name, conditions, joiner, false_path, mode), description=description)

def filter_expression(name: str, expression: str, false_path: bool = False, description: str = "") -> dict:
    """Filter on a free-form boolean EXPRESSION (e.g. 'CONTAINS(`Name`,"x") AND `Amt` >= 0').
    The expression is the truth field; the runtime and FE compile it to a pipeline server-side
    (PLAT-5786) — the skill does not hand-build `pipeline`/`dataFilterExpr`/`dataFilterLookUp`. The
    expression grammar authority is `savant-common/expr` (see `expression-language.md`). For
    structured clause filters, prefer `filter_node`."""
    cfg = {"mode": "expression", "joiner": "and", "filter": [],
           "rules": [{"expression": expression}], "useFalsePath": bool(false_path),
           "pipeline": None, "dataFilterExpr": None, "dataFilterLookUp": None}
    return _node("filter", name, cfg, description=description)

def filter_outlet(flow, filter_id: str, which: str, label: str | None = None) -> str:
    """Return a wireable handle for a dual-path filter's True (`which="true"`, `|0`) or False
    (`which="false"`, `|1`) branch: `flow.wire(filter_outlet(flow, f, "false"), exc)`. Only valid
    when the filter was built with false_path=True.

    No outlet child node is created here — the handle routes the edge onto the filter's embedded
    branch, and `normalize_outlets` synthesizes the canonical `{filter}|i` child deterministically
    at finalize time. `label` is accepted for back-compat but ignored; outlet names are canonical
    ("True"/"False")."""
    f = flow._by_id[filter_id]
    if f.get("type") not in ("filter", "pdfilter"):
        raise ValueError(f"{filter_id} is not a filter node.")
    if not f["config"].get("useFalsePath"):
        raise ValueError("filter has no false path; build it with false_path=True to fork.")
    idx = {"true": 0, "false": 1}.get(which)
    if idx is None:
        raise ValueError(f"which must be 'true' or 'false', got {which!r}.")
    return f"{filter_id}|{idx}"

# ---------------------------------------------------------------- joins / stacks / reshape / misc

# Join type is the `regions` set (the Venn "Main Path"); it is INDEPENDENT of the
# unmatched-output split (`useLeftUnmatch`/`useRightUnmatch` → the "Include Unmatched"
# checkboxes, which fork rows onto `|1`/`|2` outlets). An OUTER join keeps unmatched rows in
# the main `|0` output with nulls; the unmatched-output split routes them to their own branch.
# These were conflated before — left/right/full must NOT auto-enable the unmatch flags.
_BLEND_REGIONS = {"inner": ["T1_N_T2"], "left": ["T1_N_T2", "T1"],
                  "right": ["T1_N_T2", "T2"], "full": ["T1_N_T2", "T1", "T2"]}
# Blend join operators (the 8-value operator dropdown). NOTE: two-letter comparison forms
# (`ge`/`le`/`gt`/`lt`/`ne`), NOT the filter's `gte`/`lte` — verified against real exports.
_BLEND_OPS = {"eq", "ne", "gt", "ge", "lt", "le", "contains", "is_part_of"}
_NORMALIZED_JOIN_KEY_RE = re.compile(
    r"\b("
    r"normalized|normalised|canonical|clean|cleaned|trim|trimmed|standardized|standardised|"
    r"join\s*key|match\s*key|key|digits?|numeric|text|padded|unpadded|stripped|derived"
    r")\b",
    re.IGNORECASE,
)


def _join_key_looks_normalized(name: Any) -> bool:
    return isinstance(name, str) and bool(_NORMALIZED_JOIN_KEY_RE.search(name))


def _flag_raw_blend_join_keys(conditions: list[dict]) -> None:
    risky = [
        (idx, cond.get("lhs"), cond.get("rhs"))
        for idx, cond in enumerate(conditions)
        if isinstance(cond, dict)
        and not (_join_key_looks_normalized(cond.get("lhs")) and _join_key_looks_normalized(cond.get("rhs")))
    ]
    if not risky:
        return
    details = ", ".join(f"{idx}: {lhs!r} -> {rhs!r}" for idx, lhs, rhs in risky)
    message = (
        "Blend joins should use explicit normalized/derived key fields on both sides; "
        "join keys should usually be the type-safe UPPER(TRIM(TO_TEXT(...))) unless case or spaces are business-significant. "
        f"Raw-looking join key(s): {details}."
    )
    if os.environ.get("SAVANT_STRICT_JOIN_KEYS") == "1":
        raise ValueError(message)
    warnings.warn(message, UserWarning, stacklevel=3)

def _blend_cond(c: tuple) -> dict:
    """Normalize one match condition. Accepts (lhs, rhs), (lhs, rhs, op), or (lhs, rhs, op, dt).
    lhs/rhs are display NAMES (the engine matches by name); the normalized id lives in
    *Metadata.id. dt must match on both sides or the join silently yields zero rows."""
    if not isinstance(c, (tuple, list)) or not (2 <= len(c) <= 4):
        raise ValueError(f"blend condition must be (lhs, rhs[, op[, dt]]), got {c!r}.")
    l, r = c[0], c[1]
    op = c[2] if len(c) >= 3 else "eq"
    dt = c[3] if len(c) >= 4 else "string"
    if op not in _BLEND_OPS:
        raise ValueError(f"blend match op {op!r} not supported; use one of {sorted(_BLEND_OPS)}.")
    return {"op": op, "lhs": l, "rhs": r,
            "lhsMetadata": {"id": _field_id(l), "name": l, "dataType": dt},
            "rhsMetadata": {"id": _field_id(r), "name": r, "dataType": dt}}

def blend(name: str, on: list, join: str = "inner", joiner: str = "and",
          left_unmatched: bool = False, right_unmatched: bool = False, description: str = "") -> dict:
    """JOIN two inputs (left = in_0, right = in_1). EXACT matching (for fuzzy, use fuzzy_match()).

    on        = list of conditions, each (lhs, rhs[, op[, dt]]); op in
                eq/ne/gt/ge/lt/le/contains/is_part_of (default eq). Multiple conditions are
                combined by `joiner` (and/or — no mixed AND/OR).
    join      = inner / left / right / full — sets the `regions` (join type) ONLY.
    left_unmatched / right_unmatched = enable separate unmatched-row OUTPUT branches.
                When either is set, the blend forks: matched rows on `|0` plus unmatched rows
                on `|1`/`|2`. Wire each fork downstream with blend_outlet(flow, blend_id, which).
                For a plain join with no split, wire the blend node directly for matched rows."""
    n = _node("blend", name, _blend_config(on, join, joiner, left_unmatched, right_unmatched),
              inlets=2, description=description)
    n["outlets"][0]["id"] = "out_0"  # blend embedded outlet id is out_0
    return n

def _blend_config(on: list, join: str = "inner", joiner: str = "and",
                 left_unmatched: bool = False, right_unmatched: bool = False) -> dict:
    """Shared 'language of changes' for a blend, as a pure config dict (no node envelope). Used by
    BOTH `blend` (create) and `blend_update` (edit). See `blend` for argument meanings."""
    if join not in _BLEND_REGIONS:
        raise ValueError(f"blend join must be inner/left/right/full, got {join!r}.")
    if joiner not in ("and", "or"):
        raise ValueError(f"blend joiner must be 'and' or 'or', got {joiner!r}.")
    if not on:
        raise ValueError("blend needs at least one match condition.")
    if join != "inner" and (left_unmatched or right_unmatched):
        # Verified live: the main output of a left/right/full join already CONTAINS the
        # unmatched rows (null columns from the other side), so a split's "matched" fork is
        # NOT matched-only — downstream summaries silently include null-key rows. The
        # matched-vs-unmatched split pattern is inner join + unmatched fork(s).
        warnings.warn(
            f"Blend split with join={join!r}: a {join} join's main output already includes "
            "unmatched rows, so the 'matched' fork is not matched-only. For a matched-vs-"
            "unmatched split, use join='inner' with left_unmatched/right_unmatched. Keep a "
            "non-inner join + unmatched fork only when downstream intentionally consumes the "
            "full main output AND a separate unmatched list.",
            stacklevel=3,
        )
    conditions = [_blend_cond(c) for c in on]
    _flag_raw_blend_join_keys(conditions)
    return {"on": conditions, "joiner": joiner, "regions": _BLEND_REGIONS[join],
            "useLeftUnmatch": bool(left_unmatched), "useRightUnmatch": bool(right_unmatched)}

def _blend_outlet_indices(b: dict) -> dict[str, int]:
    """Blend output branch -> outlet index ({} for a no-split blend). Thin wrapper over the
    shared `outlets.blend_branch_indices` so the builder and `normalize_outlets` agree."""
    return _outlets.blend_branch_indices(b.get("config") or {})

def blend_outlet(flow, blend_id: str, which: str, label: str | None = None) -> str:
    """Return a wireable handle for one of a split blend's output forks, so you can wire it
    downstream like any node: `flow.wire(blend_outlet(flow, b, "left_unmatched"), exc)`.

    `which` in matched / left_unmatched / right_unmatched. Index follows the flags
    (|0 = matched; |1 = the single enabled side, or left when both; |2 = right when both).
    Only valid once the corresponding unmatch flag is set on the blend; a no-split blend wires
    its matched rows directly from the blend node (no outlet child).

    No outlet child node is created here — the handle routes the edge onto the blend's embedded
    branch, and `normalize_outlets` synthesizes the canonical `{blend}|i` child deterministically
    at finalize time. `label` is accepted for back-compat but ignored; outlet names are canonical."""
    b = flow._by_id[blend_id]
    if b.get("type") != "blend":
        raise ValueError(f"{blend_id} is not a blend node.")
    if which not in ("matched", "left_unmatched", "right_unmatched"):
        raise ValueError(f"which must be matched/left_unmatched/right_unmatched, got {which!r}.")
    indices = _blend_outlet_indices(b)
    if not indices:
        raise ValueError("blend has no split outputs; wire the blend node directly for matched rows "
                         "(set left_unmatched/right_unmatched to fork).")
    if which not in indices:
        raise ValueError(f"{which} is not enabled on this blend.")
    return f"{blend_id}|{indices[which]}"

def fuzzy_match(name: str, lhs_key: str, rhs_key: str, provider_id: str | None = None,
                show_demo_provider: bool = True, description: str = "") -> dict:
    """AI fuzzy join of two inputs (left = in_0, right = in_1) on ONE text key each. Unlike
    blend (exact, can fork matched/unmatched), fuzzy_match has a SINGLE output and adds a
    `Confidence Score` column; unmatched rows are dropped. Missing provider_id defaults to the
    standard Savant Trial provider when omitted.
    Keys are normalized field ids (e.g. 'Legal Names' -> 'legal_names')."""
    provider_id = provider_id_or_default(provider_id)
    return _node("fuzzy_match", name, {"lhsKey": _field_id(lhs_key), "rhsKey": _field_id(rhs_key),
                                       "providerId": provider_id, "showDemoProvider": bool(show_demo_provider)},
                 inlets=2, description=description)

def multi_stack(name: str, inputs: int = 2, match_rule: str = "by_name",
                master_index: int = 1, fields: str = "match", description: str = "") -> dict:
    """Stack/append several inputs. match_rule in by_name/by_pos."""
    node = _node("multi_stack", name, {"matchRule": match_rule, "masterIndex": master_index,
                                       "fieldsToInclude": fields}, inlets=0, description=description)
    node["inlets"] = [{"id": "in_0", "type": "multisource", "sources": []}]
    return node

def split_node(name: str, input_field: str, separator: str, mode: str = "rows",
               trim: bool = True, keep_input: bool = True, description: str = "") -> dict:
    """Split a delimited text column into rows or columns."""
    if mode not in ("rows", "columns"):
        raise ValueError(f"split_node mode must be 'rows' or 'columns', got {mode!r}.")
    return _node("split", name, {"mode": mode, "trim": trim, "extra": {"originalSeparator": separator},
                                 "separator": separator, "inputField": input_field,
                                 "keepInputField": keep_input}, description=description)

def _unpivot_config(name_field: str, value_field: str, selected_fields: list[str], mode: str = "unpivot") -> dict:
    """Shared config core for unpivot. Used by `unpivot` (create) and `unpivot_update` (edit)."""
    return {"mode": mode, "nameField": name_field, "valueField": value_field,
            "selectedFields": list(selected_fields)}

def unpivot(name: str, name_field: str, value_field: str, selected_fields: list[str],
            mode: str = "unpivot", description: str = "") -> dict:
    """Columns -> rows. mode 'unpivot' unpivots selected_fields; 'keep' keeps selected_fields as identity."""
    return _node("unpivot", name, _unpivot_config(name_field, value_field, selected_fields, mode),
                 description=description)

def explode_node(name: str, max_small_side_rows: int | None = None, description: str = "") -> dict:
    """Small-side row expansion (two inputs). Wire large side to in_0, small side to in_1."""
    cfg = {} if max_small_side_rows is None else {"maxSmallSideRows": int(max_small_side_rows)}
    return _node("explode", name, cfg, inlets=2, description=description)

def _deduplicate_config(fields: list[str] | None = None, sorts: list[tuple[str, str]] | None = None,
                       mode: str = "distinct") -> dict:
    """Shared config core for deduplicate. Used by `deduplicate` (create) / `deduplicate_update`."""
    return {"mode": mode, "fields": list(fields or []), "sorts": [[c, d] for c, d in (sorts or [])]}

def deduplicate(name: str, fields: list[str] | None = None, sorts: list[tuple[str, str]] | None = None,
                mode: str = "distinct", description: str = "") -> dict:
    """Deduplicate rows. fields = key columns (empty = whole-row distinct). sorts pick survivor."""
    return _node("deduplicate", name, _deduplicate_config(fields, sorts, mode), description=description)

# Aggregations that return TEXT, not a number. Two consequences, and getting either wrong is
# invisible until a user looks at the result: the output column's dataType must be "string" (each
# node's registry entry under references/registry/components/ declares exactly this), and the
# values are concatenated with a caller-chosen separator instead of a numeric reduction.
_STRING_CALCS = ("JOIN_STR", "JOIN_STR_DISTINCT")

# Savant's own config key is misspelled (`delimeter`, and `originalDelimeter` under `extra`).
# That spelling IS the wire contract — the app reads those exact keys, so do not "correct" it.
_DEFAULT_DELIMITER = ", "


def _agg_out_dt(calc: str) -> str:
    """Output dataType for an aggregation calc token. Shared by summarize/rollup/hierarchy so the
    string case cannot be fixed in one builder and missed in another (PLAT-6240: summarize and
    rollup both stamped JOIN_STR outputs as `number`, contradicting their own registry)."""
    if calc in _STRING_CALCS:
        return "string"
    return "integer" if calc in ("COUNT", "NUNIQUE") else "number"


def _agg_delimiter_params(calc: str, delimiter: str | None, *, legacy_extra: bool = False) -> dict:
    """The config fragment carrying a string-join separator.

    `params.delimeter` is the contract the app reads (references/components/hierarchy.md:25).
    `extra.originalDelimeter` is only what older exports *also* preserve, so it is opt-in per
    node: hierarchy has always emitted it and its shape is verified against real exports, so it
    keeps doing so; summarize/rollup exports do not carry it and we do not invent it."""
    delim = _DEFAULT_DELIMITER if delimiter is None else delimiter
    fragment: dict = {"params": {"delimeter": delim}}
    if legacy_extra:
        fragment["extra"] = {"originalDelimeter": delim}
    return fragment


def _unpack_agg(agg: Any, *, label: str, kind: str) -> tuple[str, str, str, str | None]:
    """Normalize one agg entry to (calc, field, output_name, delimiter|None).

    Accepts `(calc, field, output_name)` or `(calc, field, output_name, delimiter)`; the 4th
    element sets the separator for JOIN_STR/JOIN_STR_DISTINCT."""
    if not isinstance(agg, (tuple, list)) or not (3 <= len(agg) <= 4):
        raise ValueError(
            f"{kind}{label}: agg must be (calc, field, output_name[, delimiter]), got {agg!r}."
        )
    delim = agg[3] if len(agg) == 4 else None
    if delim is not None:
        if not isinstance(delim, str):
            raise ValueError(
                f"{kind}{label}: delimiter for output `{agg[2]}` must be a string, got {delim!r}."
            )
        if agg[0] not in _STRING_CALCS:
            raise ValueError(
                f"{kind}{label}: `{agg[0]}` does not concatenate values, so a delimiter is "
                f"meaningless for output `{agg[2]}`. Only {'/'.join(_STRING_CALCS)} take one."
            )
    return agg[0], agg[1], agg[2], delim


def _rollup_config(date_col: str, group_by: list[str], aggs: list[tuple[str, str, str]],
                  periodicity: str = "day") -> dict:
    """Shared config core for rollup. aggs = [(calc, field, alias[, delimiter])]. Used by
    `rollup` / `rollup_update`."""
    agg_list = []
    for agg in aggs:
        calc, fld, alias, delim = _unpack_agg(agg, label="", kind="rollup")
        agg_list.append({
            "arg": {"expr": "", "type": "field", "error": "", "constantValue": "", "selectedField": fld},
            "calc": calc,
            **_agg_delimiter_params(calc, delim),
            "tgt_col": _target_col(alias, _agg_out_dt(calc)),
        })
    return {"aggs": agg_list, "dateCol": date_col, "groupBy": list(group_by), "periodicity": periodicity}

def rollup(name: str, date_col: str, group_by: list[str], aggs: list[tuple[str, str, str]],
           periodicity: str = "day", description: str = "") -> dict:
    """Time-series aggregation: one row per period. aggs = [(calc, field, alias)]."""
    return _node("rollup", name, _rollup_config(date_col, group_by, aggs, periodicity), description=description)

# hierarchy calc tokens and the output dataType each produces (registry-derived).
_HIERARCHY_CALCS = {"SUM", "COUNT", "NUNIQUE", "MIN", "MAX", "AVG",
                    "JOIN_STR", "JOIN_STR_DISTINCT", "MEDIAN", "STDDEV", "VAR"}

def hierarchy(name: str, id_field: str, parent_id_field: str,
              aggs: list[tuple], description: str = "") -> dict:
    """Recursive parent/child hierarchy node. `id_field` and `parent_id_field` are the row id and
    its parent id; the node walks the chain and produces one path-aggregation column per agg.
    `aggs` is a list of `(calc, field, output_name)` or `(calc, field, output_name, delimiter)`;
    JOIN_STR/JOIN_STR_DISTINCT concatenate the path with `delimiter` (default ", "). Calc tokens:
    SUM, COUNT, NUNIQUE, MIN, MAX, AVG, JOIN_STR, JOIN_STR_DISTINCT, MEDIAN, STDDEV, VAR. Shape
    verified against real Savant exports."""
    if not id_field or not parent_id_field:
        raise ValueError("hierarchy requires non-empty id_field and parent_id_field.")
    if not aggs:
        raise ValueError("hierarchy needs at least one agg.")
    agg_list = []
    for a in aggs:
        calc, fld, out, delim = _unpack_agg(a, label="", kind="hierarchy")
        if calc not in _HIERARCHY_CALCS:
            raise ValueError(f"hierarchy calc {calc!r} not supported; use one of {sorted(_HIERARCHY_CALCS)}.")
        arg_type = "row" if (calc == "COUNT" and fld in ("Row", "row")) else "field"
        agg_list.append({
            "arg": {"expr": "", "type": arg_type, "error": "", "constantValue": "", "selectedField": fld},
            "calc": calc,
            **_agg_delimiter_params(calc, delim, legacy_extra=True),
            "tgt_col": _target_col(out, _agg_out_dt(calc)),
        })
    return _node("hierarchy", name,
                 {"aggs": agg_list, "idField": id_field, "parentIdField": parent_id_field},
                 description=description)

def _vision_config(prompt: str, input_field: str, provider_id: str | None = None) -> dict:
    """Shared config core for vision. Used by `vision` / `vision_update`."""
    provider_id = provider_id_or_default(provider_id)
    return {"prompt": prompt, "inputField": input_field, "providerId": provider_id}

def vision(name: str, prompt: str, input_field: str, provider_id: str | None = None, description: str = "") -> dict:
    """Extract structured data from a PDF/image binary column."""
    return _node("vision", name, _vision_config(prompt, input_field, provider_id), description=description)

def format_node(name: str, header_row: int | None = None, steps: list[dict] | None = None,
                description: str = "") -> dict:
    """Bulk schema cleanup (Format). header_row promotes a row to headers (replaceNamesWithRow)."""
    cfg = {"extra": {}, "steps": steps or [], "replace": True}
    if header_row is not None:
        cfg["replaceNamesWithRow"] = int(header_row)
    return _node("format", name, cfg, description=description)

def api_service(name: str, url: str, method: str = "GET", result_format: str = "JSON",
                description: str = "") -> dict:
    """Call an external API per row. (Basic shape; bind real auth/config in Savant.)"""
    return _node("apiService", name, {"serviceType": "APIService",
                 "apiServiceConfig": {"url": url, "method": method, "resultFormat": result_format}},
                 description=description)

# ---------------------------------------------------------------- edit ops (compose into one Transform)

def op_json_field(tgt: str, src: str, path: str, dt: str = "string") -> dict:
    return op_expr(tgt, f"JSON_FIELD({_expr_field(src)},{_expr_literal(path)})", dt)

def op_json_number(tgt: str, src: str, path: str) -> dict:
    """Add numeric column tgt = TO_NUMBER(JSON_FIELD(src, path)) as one op with a nested pipeline."""
    return op_expr(tgt, f"TO_NUMBER(JSON_FIELD({_expr_field(src)},{_expr_literal(path)}))", "number")

def _compiled_expr_op(
    tgt: str,
    expression: str,
    dtype: str = "string",
    action: str = "add_col",
    *,
    include_tgt_dtype: bool = True,
    replace_tgt: str | None = None,
) -> dict:
    """Add/replace ``tgt`` from an EXPRESSION, emitting the expression truth field only.

    The skill does NOT hand-build ``pipeline``/``lookup``. The runtime compiles the expression to a
    pipeline server-side at Spark time when no pipeline is present (see ``EditConfig`` /
    ``Edit.scala`` ``compileExpressionPipeline``), and the FE re-derives the display caches — the
    same contract the ``EditNodeHydrater``/``FilterNodeHydrater`` follow. A hand-built pipeline can
    diverge from the expression and fail at runtime (e.g. ``TO_DATE(<const>)`` compiling to a step
    with empty ``src_cols``), so we let the authoritative compiler own it. Grammar authority:
    ``savant-common/expr`` (Pratt parser + ``ScalarFunctions``); see ``expression-language.md``.
    """
    if action not in {"add_col", "replace"}:
        raise ValueError(f"op_expr action must be add_col or replace, got {action!r}.")
    out_tgt = _target_col(tgt, dtype) if include_tgt_dtype else _target_col(tgt)
    out = {"mode": "expression", "action": action, "tgtCol": out_tgt, "expression": expression}
    if action == "replace":
        out["replaceTgt"] = replace_tgt or tgt
    return out

def op_expr(tgt: str, expression: str, dtype: str = "string", action: str = "add_col",
            replace_tgt: str | None = None) -> dict:
    """Add (`action="add_col"`, default) or replace (`action="replace"`) `tgt` from an expression.

    For an in-place replace that consumes a DIFFERENTLY-named source column, pass `replace_tgt`
    (the source's name) — e.g. `op_expr("Vendor Key", "UPPER(TRIM(\\`AI Answer\\`))", action="replace",
    replace_tgt="AI Answer")`. Prefer the `op_transform` wrapper for that case; it reads clearer.
    `replace_tgt` is ignored for `add_col`."""
    return _compiled_expr_op(tgt, expression, dtype, action, replace_tgt=replace_tgt)

def op_transform(new: str, src: str, expression: str, dt: str = "string") -> dict:
    """Rename / retype / transform a column IN PLACE in ONE `replace` edit — consume `src`,
    emit `new` from `expression`. One column in, one out; no new intermediate column, no hidden
    original, position preserved (the Edit launcher's REPLACE overwrites `src`'s slot and renames
    it to `new`; see `Edit.scala`). This is the general form behind `op_rename` (pass-through),
    `op_retype` (cast), and `op_excel_serial_date` (serial->date).

    Use it to fold a rename + cast + normalization into a single op instead of adding a new column
    and hiding the original — e.g.
        op_transform("Vendor Key", "AI Answer", "UPPER(TRIM(`AI Answer`))")
        op_transform("GL Date", "PostDate", "TO_DATE(`PostDate`)", "date")
    `src` and every column referenced inside `expression` are named (backtick-quote names with
    spaces); the runtime resolves them by name. `new` may equal `src` (in-place retype keeping the
    name)."""
    return _compiled_expr_op(new, expression, dt, "replace", replace_tgt=src)

def op_const(tgt: str, value, dtype: str = "string") -> dict:
    """Add a pure constant column."""
    return op_expr(tgt, _expr_literal(value), dtype)

def op_case(tgt: str, cases: list[tuple[str | dict, object]], default, dtype: str = "string") -> dict:
    """Add ``tgt`` from CASE-like flag logic.

    ``cases`` is a list of ``(condition, then_value)`` tuples. ``condition`` can be either a raw
    boolean expression string or a structured ``cond(...)`` object; branch values are constants.
    """
    if not cases:
        raise ValueError("op_case needs at least one case.")
    expr_parts = []
    for idx, (condition, then_value) in enumerate(cases, start=1):
        if isinstance(condition, dict):
            _entry, condition_expr = _cond_parts(condition, "and", idx - 1, f"{tgt}_case_{idx}")
        else:
            condition_expr = str(condition)
        expr_parts.append(f"WHEN {condition_expr} THEN {_expr_literal(then_value)}")
    return op_expr(tgt, "CASE " + " ".join(expr_parts) + f" ELSE {_expr_literal(default)} END", dtype)

def op_count_if(tgt: str, condition: str | dict, dtype: str = "integer") -> dict:
    """Add a null-safe 0/1 indicator column for count-style summaries.

    Use this before summarize for measures such as "returned orders" or "negative reviews",
    especially after left joins where unmatched rows are null. Summarize the generated field with
    ``SUM`` instead of counting nullable joined fields directly.
    """
    normalized = _norm_dt(dtype)
    if normalized not in {"integer", "number"}:
        raise ValueError(f"op_count_if dtype must be integer or number, got {dtype!r}.")
    return op_case(tgt, [(condition, 1)], 0, normalized)

def op_arith(tgt: str, left: str, op: str, right, right_is_const: bool = False, dt: str = "number") -> dict:
    if op not in ("add", "sub", "mul", "div"):
        raise ValueError(f"op_arith op must be add/sub/mul/div, got {op!r}.")
    sym = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[op]
    right_expr = _expr_literal(right) if right_is_const else _expr_field(right)
    return op_expr(tgt, f"{_expr_field(left)} {sym} {right_expr}", dt)

def op_avg(tgt: str, fields: list[str]) -> dict:
    """Add column tgt = (f0 + f1 + ...) / n as one op with a nested pipeline + lookup."""
    n = len(fields)
    if n < 2:
        raise ValueError(f"op_avg needs at least 2 fields, got {n}.")
    expr = "(" + " + ".join(_expr_field(f) for f in fields) + f") / {n}"
    return op_expr(tgt, expr, "number")

def op_cast(tgt: str, src: str, to: str = "to_number") -> dict:
    dt = {"to_number": "number", "to_integer": "integer", "to_text": "string",
          "to_date": "date", "to_datetime": "datetime", "to_boolean": "boolean"}.get(to, "string")
    return op_expr(tgt, f"{to.upper()}({_expr_field(src)})", dt)

def op_normalized_join_key(tgt: str, src: str, *, case: str = "upper") -> dict:
    """Create a text join key with whitespace normalized and case-insensitive matching by default.

    Use this for exact-join keys unless the user confirms that case or leading/trailing spaces are
    business-significant. It preserves letters and digits; it does not convert alphanumeric codes
    like ``CT2`` or ``X01`` to numbers.

    The key is always cast to text first (``TO_TEXT``) so a numerically-typed id column — ZIP and
    postal codes, account numbers, store ids — cannot fail at runtime: ``TRIM`` on an integer
    column errors live, and that failure surfaces only after import, as an empty join. Casting is
    a no-op for columns that are already text. (Leading-zero alignment is a separate, confirmed
    decision; see the data-prep standard.)
    """
    normalized_case = str(case or "upper").strip().lower()
    if normalized_case not in {"upper", "lower", "preserve"}:
        raise ValueError("op_normalized_join_key case must be 'upper', 'lower', or 'preserve'.")
    inner = f"TRIM(TO_TEXT({_expr_field(src)}))"
    if normalized_case == "upper":
        expression = f"UPPER({inner})"
    elif normalized_case == "lower":
        expression = f"LOWER({inner})"
    else:
        expression = inner
    return op_expr(tgt, expression, "string")

def op_date_diff(tgt: str, end_date: str, start_date: str, unit: str = "day") -> dict:
    """Add integer date difference: ``DATE_DIFF(end_date, start_date, "unit")``.

    The argument order matches Savant's formula UI and exported workflows: later/end date first,
    earlier/start date second. Direct field operands are supported here; use a prior Transform for
    nested date expressions such as TODAY()/NOW() until the general expression compiler supports
    date-diff expression trees.
    """
    normalized = str(unit).strip().lower()
    if normalized not in {"day", "week", "month", "quarter", "year"}:
        raise ValueError(f"op_date_diff unit must be day/week/month/quarter/year, got {unit!r}.")
    return op_expr(tgt, f"DATE_DIFF({_expr_field(end_date)},{_expr_field(start_date)},{_expr_literal(normalized)})", "integer")

def op_excel_serial_date(tgt: str, src: str, dtype: str = "date", src_dtype: str = "integer") -> dict:
    """Convert an Excel serial day number into a Savant date/datetime column.

    Excel stores dates as days from 1899-12-30. This op is used when source profiling shows
    a date-intent Excel column arriving as a numeric serial value.
    """
    normalized_dtype = _norm_dt(dtype)
    if normalized_dtype not in {"date", "datetime"}:
        normalized_dtype = "date"
    base_expr = "DATETIME(1899,12,30,0,0,0)" if normalized_dtype == "datetime" else "DATE(1899,12,30)"
    return _compiled_expr_op(
        tgt,
        f"DATE_ADD({base_expr},{_expr_field(src)},\"day\")",
        normalized_dtype,
        "replace",
        replace_tgt=src,
    )

def op_default_constant(tgt: str, src: str, default, dt: str = "string") -> dict:
    """Add column `tgt` = COALESCE(src, default). Coalesce only accepts columns at runtime, so
    materialize the constant as a transient column first, then coalesce the source + transient."""
    return op_expr(tgt, f"COALESCE({_expr_field(src)},{_expr_literal(default)})", dt)

def op_window(tgt: str, calc: str, sorts: list[tuple[str, str]] | None = None,
              partitions: list[str] | None = None, arg_field: str | None = None, params: dict | None = None) -> dict:
    arg = None if arg_field is None else {"expr": "", "type": "field", "error": "", "constantValue": "", "selectedField": arg_field}
    return {"calc": {"arg": arg, "calc": calc, "sorts": [[c, d] for c, d in (sorts or [])],
                     "params": {"delimeter": ", ", **(params or {})}, "partitions": partitions or []},
            "mode": "builder", "action": "add_col", "tgtCol": _target_col(tgt), "expression": ""}

# Map a target dataType to the cast transform that produces it.
_CAST_FOR_DT = {"number": "to_number", "integer": "to_integer", "string": "to_text",
                "date": "to_date", "datetime": "to_datetime", "boolean": "to_boolean"}

def op_rename(old: str, new: str, dt: str = "string") -> dict:
    """Rename a column `old` -> `new` (same value/type) as a `replace` edit — the real
    mechanism (the old `config.modify` map is ignored by Savant). Emits the canonical
    `field`-transform replace shape with `replaceTgt`."""
    return _compiled_expr_op(new, _expr_field(old), dt, "replace", include_tgt_dtype=False, replace_tgt=old)

def op_retype(col: str, to: str = "to_number") -> dict:
    """Change a column's data type IN PLACE (e.g. text -> number) as a `replace` edit, applying
    the cast `to` (to_number/to_integer/to_text/to_date/to_datetime/to_boolean)."""
    dt = {"to_number": "number", "to_integer": "integer", "to_text": "string",
          "to_date": "date", "to_datetime": "datetime", "to_boolean": "boolean"}.get(to, "string")
    return _compiled_expr_op(col, f"{to.upper()}({_expr_field(col)})", dt, "replace", replace_tgt=col)

def _edit_config(ops: list[dict] | None = None, modify: dict | None = None,
                drop: list[str] | None = None, order: list[str] | None = None) -> dict:
    """The shared 'language of changes' for a Transform node, as a pure config dict (no node
    envelope). Used by BOTH `edit_node` (create) and `edit_update` (edit) so the two paths emit
    byte-identical config for the same arguments. See `edit_node` for the argument meanings."""
    edits = list(ops or [])
    for col, spec in (modify or {}).items():
        new_name = spec.get("name", col)
        if new_name != col:
            edits.append(op_rename(col, new_name, spec.get("dataType", "string")))
        if "dataType" in spec:
            cast = _CAST_FOR_DT.get(spec["dataType"])
            if cast is None:
                raise ValueError(f"edit_node modify dataType {spec['dataType']!r} unsupported; "
                                 f"use one of {sorted(_CAST_FOR_DT)}.")
            edits.append(op_retype(new_name, cast))
    return {
        "edits": edits,
        "hiddenFields": [_field_name_ref(c) for c in (drop or [])],
        "orderedFields": [_field_name_ref(c) for c in (order or [])],
    }

def edit_node(name: str, ops: list[dict] | None = None, modify: dict | None = None,
              drop: list[str] | None = None, order: list[str] | None = None, description: str = "") -> dict:
    """One Transform node composing many column ops, all in `edits[]`:
      ops    = add_col/window/replace ops (op_json_field, op_arith, op_cast, op_window, op_rename,
               op_retype, ...). Ops are ordered; later ops may reference fields created or
               replaced by earlier ops in this same Transform.
      modify = {col: {"name": new, "dataType": dt}} convenience for renames/retypes; compiled to
               `op_rename`/`op_retype` `replace` edits (NOT the legacy `config.modify` map, which
               Savant ignores — that was a silent no-op).
      drop   = columns to hide (`hiddenFields`); order = column order (`orderedFields`).
    Note: orderedFields only REORDERS — it never drops; use `drop` to remove columns."""
    return _node("edit", name, _edit_config(ops, modify, drop, order), description=description)

def keep_only_columns(flow: "Flow", upstream: str, name: str, columns: list[str], description: str = "") -> dict:
    """Create a Transform that keeps exactly `columns` from an upstream node.

    This is the safe final-output shaping helper: it computes every upstream passthrough column
    not listed in `columns` and writes those fields to `hiddenFields`, while also setting
    `orderedFields` to the requested output order. Use it after calculations/renames are complete;
    it intentionally does not combine with `ops` because it derives hidden fields from the upstream
    schema at helper-call time.
    """
    requested = [str(c) for c in columns]
    if not requested:
        raise ValueError("keep_only_columns requires at least one column.")
    schema = flow.schema_at(upstream)
    if not schema.get("known", True):
        raise ValueError(f"Cannot keep only columns after {upstream!r}: upstream output schema is unknown.")
    upstream_columns = [str(c) for c in (schema.get("columns") or [])]
    upstream_keys: dict[str, str] = {}
    for col in upstream_columns:
        upstream_keys.setdefault(_field_control_ref(col), col)
        upstream_keys.setdefault(col, col)
    missing = [
        col for col in requested
        if _field_control_ref(col) not in upstream_keys and col not in upstream_keys
    ]
    if missing:
        raise ValueError(f"Cannot keep missing column(s) after {upstream!r}: {', '.join(missing)}.")
    requested_keys = {_field_control_ref(c) for c in requested} | set(requested)
    drop = [
        col for col in upstream_columns
        if _field_control_ref(col) not in requested_keys and col not in requested_keys
    ]
    return edit_node(name, drop=drop, order=requested, description=description)

# ---------------------------------------------------------------- summarize / adapter / gen_ai

def _summarize_config(group_by: list[str], aggs: list[tuple[str, str, str]], *,
                      node_name: str | None = None) -> dict:
    """Shared config core for summarize (GROUP BY). aggs: list of (calc, field, output_name);
    COUNT-of-rows uses field='Row'. Used by `summarize` (create) and `summarize_update` (edit).

    A valid aggregation argument is Row (COUNT only) or a non-grouped column — the app's
    Argument picker offers exactly that set, and a config violating it executes but renders
    blank pickers (Apply then destroys it). Enforced here so create and edit are both covered:
    COUNT of a group-by field is normalized to a Row count with a printed notice (the Alteryx
    `Count` idiom — Alteryx Count ignores its anchor field's values, while Savant field-COUNT
    skips blanks); any other calc with `Row` or a group-by field as its argument raises."""
    label = f" `{node_name}`" if node_name else ""
    agg_list = []
    for agg in aggs:
        calc, fld, out, delim = _unpack_agg(agg, label=label, kind="summarize")
        if calc == "COUNT":
            if fld != "Row" and fld in group_by:
                print(f"notice: summarize{label}: COUNT argument `{fld}` is also a group-by field; "
                      f"normalized to a Row count for output `{out}`. Pass ('COUNT', 'Row', ...) "
                      f"to make this explicit.")
                fld = "Row"
        elif fld == "Row":
            raise ValueError(
                f"summarize{label}: `{calc}` cannot aggregate `Row`; only COUNT supports the Row argument."
            )
        elif fld in group_by:
            raise ValueError(
                f"summarize{label}: `{calc}` argument `{fld}` is also a group-by field. A field is "
                f"either grouped or aggregated, never both — the app cannot display this config and "
                f"Apply would destroy it. Aggregate a different column or remove `{fld}` from group_by."
            )
        arg_type = "row" if (calc == "COUNT" and fld == "Row") else "field"
        agg_list.append({"arg": {"expr": "", "type": arg_type, "error": "", "selectedField": fld},
                         "calc": calc,
                         **_agg_delimiter_params(calc, delim),
                         "tgt_col": _target_col(out, _agg_out_dt(calc))})
    return {"aggs": agg_list, "sorts": [], "window": [0, None],
            "groupBy": list(group_by), "useWindow": False}

def summarize(name: str, group_by: list[str], aggs: list[tuple[str, str, str]], description: str = "") -> dict:
    """aggs: list of (calc, field, output_name). COUNT-of-rows uses field='Row'. COUNT of a
    group-by field is normalized to Row (with a printed notice); other calcs reject Row or a
    group-by field as the argument — see `_summarize_config`."""
    return _node("summarize", name, _summarize_config(group_by, aggs, node_name=name), description=description)

def adapter(name: str, specs: list[dict], passthrough: bool = False, description: str = "") -> dict:
    return _node("adapter", name, {"passthroughUnmapped": passthrough, "specs": specs}, description=description)

def adapter_specs(schema: list[dict]) -> list[dict]:
    """Build adapter `specs` from a schema contract: a list of {name, dataType?, mappedFrom?,
    required?}. `name` is the canonical (downstream) name, `dataType` the target type (default
    string), `mappedFrom` the raw source column it maps from (default = canonical name), `required`
    whether it must be present (default True)."""
    if not isinstance(schema, list) or not schema:
        raise ValueError("adapter schema must be a non-empty list of column contracts.")
    for i, c in enumerate(schema):
        if not isinstance(c, dict):
            raise ValueError(f"adapter schema[{i}] must be an object.")
        if not isinstance(c.get("name"), str) or not c["name"].strip():
            raise ValueError(f"adapter schema[{i}].name is required.")
        if not isinstance(c.get("dataType"), str) or not c["dataType"].strip():
            raise ValueError(f"adapter schema[{i}].dataType is required.")
    return [{"name": c["name"], "dataType": c.get("dataType", "string"),
             "mappedFrom": c.get("mappedFrom", c["name"]), "required": c.get("required", True)}
            for c in schema]

def _norm_dt(value: Any) -> str:
    return str(value or "").strip().lower()

def _observed_by_name(observed_schema: list[dict] | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for col in observed_schema or []:
        if isinstance(col, dict) and isinstance(col.get("name"), str):
            out[col["name"].casefold()] = col
    return out

def _looks_like_excel_serial_date(values: list) -> bool:
    numeric: list[float] = []
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            numeric.append(float(v))
        elif isinstance(v, str):
            # Evidence values round-trip through JSON/CSV as strings; a numeric
            # string serial is the same evidence and must not defeat the rule.
            try:
                numeric.append(float(v.strip()))
            except ValueError:
                return False
    if not numeric:
        return False
    # 20000-60000 covers roughly 1954-2064, which is broad enough for business data while
    # avoiding ordinary small counts/ids. Fractional values are valid Excel date-times.
    return all(20000 <= v <= 60000 for v in numeric)

def _excel_serial_date_plan(connector: str, expected_schema: list[dict], observed_schema: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """Return adapter schema + post-adapter date normalizations for Excel serial date columns.

    The adapter should not cast Excel serial day numbers directly to `date`; that runtime cast
    treats the integer like an epoch value and produces 1970-era dates. Keep the adapter aligned to
    the observed numeric type, then normalize the canonical output field after the adapter.
    """
    adapter_schema: list[dict] = []
    date_ops: list[dict] = []
    observed = _observed_by_name(observed_schema)
    is_excel = str(connector or "").strip().lower() == "excel"
    for spec in expected_schema or []:
        if not isinstance(spec, dict):
            continue
        adapted = dict(spec)
        expected_type = _norm_dt(spec.get("dataType"))
        raw_name = spec.get("mappedFrom") or spec.get("name")
        canonical_name = spec.get("name")
        raw = observed.get(raw_name.casefold()) if isinstance(raw_name, str) else None
        observed_type = _norm_dt(raw.get("dataType")) if isinstance(raw, dict) else ""
        if (
            is_excel
            and expected_type in {"date", "datetime"}
            and isinstance(canonical_name, str)
            and observed_type in {"integer", "number"}
            and _looks_like_excel_serial_date(sample_values(raw))
        ):
            adapted["dataType"] = observed_type
            date_ops.append(op_excel_serial_date(canonical_name, canonical_name, expected_type, observed_type))
        adapter_schema.append(adapted)
    return adapter_schema, date_ops

def source_prep_join_key_ops(join_key_specs: list[dict] | None) -> list[dict]:
    """Return source-prep operations for planned join keys.

    This is shared by create/build paths and edit/reconciliation paths so known join keys are
    normalized once at the source-prep stage instead of rebuilt near every Blend.
    """
    ops: list[dict] = []
    seen_outputs: set[str] = set()
    for index, spec in enumerate(join_key_specs or []):
        if not isinstance(spec, dict):
            raise ValueError(f"join_key_normalizations[{index}] must be an object.")
        source_field = spec.get("source_field")
        output_field = spec.get("output_field")
        if not isinstance(source_field, str) or not source_field.strip():
            raise ValueError(f"join_key_normalizations[{index}].source_field is required.")
        if not isinstance(output_field, str) or not output_field.strip():
            raise ValueError(f"join_key_normalizations[{index}].output_field is required.")
        if output_field.casefold() in seen_outputs:
            raise ValueError(f"duplicate join key output field {output_field!r}.")
        seen_outputs.add(output_field.casefold())
        ops.append(op_normalized_join_key(output_field, source_field, case=spec.get("case", "upper")))
    return ops

def standardized_source(flow, name: str, dataset_id: str, connector: str, schema: list[dict], *,
                        dtype: str | None = None, source_description: str = "",
                        adapter_name: str | None = None, adapter_description: str | None = None,
                        observed_schema: list[dict] | None = None, row_count: int | None = None,
                        business_role: str = "") -> str:
    """Public tabular source shortcut.

    This intentionally routes through the same implementation as `source_unit_from_plan(...)`.
    That keeps source setup behavior identical whether a workflow is created from a structured plan
    or by direct builder calls, including post-adapter Excel serial date normalization.
    """
    return _source_unit(
        flow,
        name,
        dataset_id,
        connector,
        "tabular",
        schema=schema,
        observed_schema=observed_schema,
        row_count=row_count,
        dtype=dtype,
        source_description=source_description,
        business_role=business_role,
        adapter_name=adapter_name,
        adapter_description=adapter_description,
    )

def _source_unit(flow, name: str, dataset_id: str, connector: str, source_kind: str, *,
                schema: list[dict] | None = None, expected_schema: list[dict] | None = None,
                observed_schema: list[dict] | None = None,
                row_count: int | None = None,
                dtype: str | None = None,
                source_description: str = "", adapter_name: str | None = None,
                adapter_description: str | None = None, extraction: dict | None = None,
                parser: dict | None = None, business_role: str = "",
                join_key_normalizations: list[dict] | None = None) -> str:
    """Compile a structured source plan into the right input unit and return the downstream handle.

    `source_kind` is supplied by Planner/dataset discovery, not inferred here:
      - tabular: Source -> Adapter; requires `schema`.
      - binary_document: Source -> Vision; requires `extraction` with prompt/provider_id.
      - json_text: Source -> JSON; parser may set mode/input_field/keep_input.
      - xml_text: Source -> XML; parser may set mode/input_field/path/unwrap_tag/process_ns.
    The unit is registered so `Flow.group(..., [handle])` visually groups the whole source unit.
    """
    kind = str(source_kind or "").strip().lower()
    resolved_source_description = source_description or _source_description(name, connector, kind, business_role)
    if kind == "tabular":
        schema = schema or expected_schema
        if not schema:
            raise ValueError("_source_unit(tabular) requires a schema contract for the adapter.")
        adapter_schema, date_ops = _excel_serial_date_plan(connector, schema, observed_schema)
        # Join keys are typed at the ADAPTER, deterministically: a field that the plan
        # declares as a join key must reach the join as text on both sides, so a
        # numerically-typed id column (ZIP, account number, store id) is standardized to
        # string here — the adapter is the type authority. The downstream normalization op
        # then applies text cleanup; its TO_TEXT stays as defense for non-plan paths.
        join_key_fields = {
            str(spec.get("source_field")).strip()
            for spec in join_key_normalizations or []
            if isinstance(spec, dict) and isinstance(spec.get("source_field"), str)
        }
        if join_key_fields:
            adapter_schema = [
                {**col, "dataType": "string"}
                if str(col.get("name") or "").strip() in join_key_fields
                and _norm_dt(col.get("dataType")) in {"number", "integer"}
                else col
                for col in adapter_schema
            ]
        join_key_ops = source_prep_join_key_ops(join_key_normalizations)
        src = flow.add(source(
            name,
            dataset_id,
            connector,
            dtype=dtype,
            description=resolved_source_description,
            observed_schema=observed_schema,
            row_count=row_count,
        ))
        desc = adapter_description or f"Standardize {name} to canonical field names and data types for downstream logic."
        aid = flow.add(adapter(adapter_name or f"Standardize {name}", adapter_specs(adapter_schema), description=desc))
        flow.wire(src, aid)
        source_prep_ops = [*date_ops, *join_key_ops]
        if not source_prep_ops:
            if hasattr(flow, "_register_unit"):
                flow._register_unit(aid, [src, aid])
            return aid
        prep_parts = []
        if date_ops:
            prep_parts.append("Dates")
        if join_key_ops:
            prep_parts.append("Join Keys")
        normalizer = flow.add(edit_node(
            f"Normalize {name} {' and '.join(prep_parts)}",
            ops=source_prep_ops,
            description=f"Prepare standardized {name} fields for downstream business logic.",
        ))
        flow.wire(aid, normalizer)
        if hasattr(flow, "_register_unit"):
            flow._register_unit(normalizer, [src, aid, normalizer])
        return normalizer

    src = flow.add(source(name, dataset_id, connector, dtype=dtype, description=resolved_source_description))
    handle = src
    if kind == "binary_document":
        cfg = extraction or {}
        prompt, provider_id = cfg.get("prompt"), cfg.get("provider_id", DEFAULT_AI_PROVIDER_ID)
        if not prompt:
            raise ValueError("_source_unit(binary_document) requires extraction.prompt.")
        handle = flow.add(vision(cfg.get("name") or f"Extract {name}", prompt,
                                 cfg.get("input_field", "content"), provider_id,
                                 description=cfg.get("description", "")))
        flow.wire(src, handle)
    elif kind == "json_text":
        cfg = parser or {}
        handle = flow.add(json_node(cfg.get("name") or f"Parse {name}",
                                    cfg.get("mode", "flatten"),
                                    cfg.get("input_field", "Content"),
                                    keep_input=cfg.get("keep_input", False),
                                    description=cfg.get("description", "")))
        flow.wire(src, handle)
    elif kind == "xml_text":
        cfg = parser or {}
        handle = flow.add(xml_node(cfg.get("name") or f"Parse {name}",
                                   cfg.get("mode", "SELECT"),
                                   cfg.get("input_field", "Content"),
                                   path=cfg.get("path"),
                                   unwrap_tag=cfg.get("unwrap_tag", True),
                                   process_ns=cfg.get("process_ns", False),
                                   description=cfg.get("description", "")))
        flow.wire(src, handle)
    else:
        raise ValueError("_source_unit source_kind must be one of tabular, binary_document, json_text, xml_text.")

    if hasattr(flow, "_register_unit"):
        flow._register_unit(handle, [src, handle])
    return handle

def source_unit_from_plan(flow, source_plan: dict) -> str:
    """Compile one Planner source object into the right input unit.

    Passing the full source object keeps Planner evidence, such as observed sample values, available
    to deterministic generation without expanding `_source_unit(...)` every time the handoff grows.
    """
    if not isinstance(source_plan, dict):
        raise ValueError("source_unit_from_plan requires a source plan object.")
    contract_errors: list[str] = []
    validate_source_plan(contract_errors, source_plan, "source_plan")
    if contract_errors:
        raise ValueError("source_unit_from_plan received an invalid source plan: " + "; ".join(contract_errors))
    name = source_plan.get("source_name")
    dataset_id = source_plan_dataset_id(source_plan)
    connector = source_plan_connector(source_plan)
    source_kind = source_plan.get("source_kind")
    if not all(isinstance(v, str) and v.strip() for v in (name, dataset_id, source_kind)):
        raise ValueError("source_unit_from_plan requires source_name, dataset.dataset_id, and source_kind.")
    if not connector:
        connector = "dataset"
    return _source_unit(
        flow,
        name,
        dataset_id,
        connector,
        source_kind,
        expected_schema=source_plan.get("expected_schema"),
        observed_schema=source_plan_observed_schema(source_plan),
        row_count=source_plan_row_count(source_plan),
        dtype=source_plan.get("dtype"),
        source_description=source_plan.get("source_description") or "",
        business_role=source_plan.get("business_role") or "",
        adapter_name=source_plan.get("adapter_name"),
        adapter_description=source_plan.get("adapter_description"),
        extraction=source_plan.get("extraction"),
        parser=source_plan.get("parser"),
        join_key_normalizations=source_plan_join_key_normalizations(source_plan),
    )

def _gen_ai_config(prompt: str, input_fields: list[str], provider_id: str | None = None, row_limit: int = 1000) -> dict:
    """Shared 'language of changes' for a gen_ai node, as a pure config dict (no node envelope).
    Used by BOTH `gen_ai` (create) and `gen_ai_update` (edit)."""
    provider_id = provider_id_or_default(provider_id)
    # No hardcoded type/connector — Savant resolves the connector from providerId on
    # import (as vision/fuzzy_match already do). A literal connector like "openai" fails
    # to resolve for non-OpenAI providers and the whole gen_ai node is silently dropped.
    return {"mode": "BATCH", "providerId": provider_id,
            "inputFields": list(input_fields), "serviceType": "LLMService", "prompt": prompt,
            "rowLimit": int(row_limit)}

def gen_ai(name: str, prompt: str, input_fields: list[str], provider_id: str | None = None, row_limit: int = 1000, description: str = "") -> dict:
    return _node("gen_ai", name, _gen_ai_config(prompt, input_fields, provider_id, row_limit), description=description)

def schema_hints(*entries: tuple[Any, list[str]]) -> dict[str, list[str]]:
    """Build a validator `--schema-hints` mapping from `(node_or_id, columns)` pairs.

    `node_or_id` may be a node dict (preferred, uses its id) or a node id/name string.
    Use for AI/reshape nodes whose output columns are known by design but not derivable
    from upstream schema.
    """
    hints: dict[str, list[str]] = {}
    for node_or_id, columns in entries:
        key = node_or_id.get("id") if isinstance(node_or_id, dict) else str(node_or_id)
        if not isinstance(key, str) or not key.strip():
            raise ValueError("schema_hints entries need a node id/name or node dict with an id.")
        if not isinstance(columns, list) or not columns or not all(isinstance(c, str) and c.strip() for c in columns):
            raise ValueError(f"schema_hints for {key!r} must be a non-empty list of column names.")
        hints[key] = list(columns)
    return hints

# ---------------------------------------------------------------- edit (update an EXISTING node in place)

# The create constructors above MINT a new node (fresh id, empty wiring) from a config core.
# The update adapters below take an EXISTING node (read from a live recipe) and swap in a freshly
# generated config from the SAME core, preserving identity and wiring. Same 'language of changes',
# two directions: create = config + new envelope; edit = config + existing envelope. This is what
# lets the editor change any node type the builder can generate, without per-component edit JSON.

# Fields that are node IDENTITY / WIRING, never touched by a config update.
_IDENTITY_FIELDS = ("id", "type", "inlets", "outlets", "position", "canvasConfig",
                    "isPristine", "isComputing", "isConfigured")

def update_config(existing: dict, config: dict, *, name: str | None = None,
                  description: str | None = None) -> dict:
    """EDIT counterpart to the create constructors: return a copy of an existing recipe node with
    the config fields we generate updated, while PRESERVING identity, wiring, and any config fields
    we did not generate. `config` MUST come from the same shared `*_config` builder the create path
    uses, so create and edit stay shape-identical and coupled fields (e.g. an edit node's
    expression/pipeline/lookup) always regenerate together.

    Merge, don't replace. `node_builders` does not necessarily model every field a live node
    carries — the create path may not emit them, and the app may add fields we don't know about.
    So the new config is merged OVER the existing config at the top level: every key the builder
    emits is replaced wholesale (which is why each `*_config` must emit the complete value for the
    keys it owns, including cleared ones), and every key the builder does NOT emit is kept exactly
    as read from the live node. This guarantees we never silently drop a real setting we didn't
    model. (Unknown structure nested *inside* a key the builder owns is not separately preserved —
    the builder owns that whole key.)

    This is a node-level, config-only update. It does NOT change the node's outlet topology, so it
    is not the path for toggling a filter's false path or otherwise adding/removing branches — those
    are topology edits owned by the editor's add/remove-node rules."""
    if not isinstance(existing, dict) or not isinstance(existing.get("config"), dict):
        raise ValueError("update_config needs an existing recipe node dict with a `config` object.")
    updated = copy.deepcopy(existing)
    updated["config"] = {**updated["config"], **config}  # generated keys win; unknown keys preserved
    if name is not None:
        updated["name"] = name
    if description is not None:
        updated["description"] = description
    return updated

def edit_update(existing: dict, ops: list[dict] | None = None, modify: dict | None = None,
                drop: list[str] | None = None, order: list[str] | None = None, *,
                name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing Transform node's config (same args as `edit_node`) in place."""
    return update_config(existing, _edit_config(ops, modify, drop, order), name=name, description=description)

def filter_update(existing: dict, conditions: list[dict], joiner: str = "and", false_path: bool = False,
                  mode: str = "wizard", *, name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing filter/pdfilter node's config (same args as `filter_node`) in place.
    Note: changing `false_path` changes branch topology, which this config-only update does not wire
    up — the editor handles branch add/remove separately."""
    label = name or existing.get("name", "filter")
    return update_config(existing, _filter_config(label, conditions, joiner, false_path, mode),
                         name=name, description=description)

def blend_update(existing: dict, on: list, join: str = "inner", joiner: str = "and",
                 left_unmatched: bool = False, right_unmatched: bool = False, *,
                 name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing blend node's config (same args as `blend`) in place. Note: toggling
    `left_unmatched`/`right_unmatched` changes the split-outlet topology, which the editor wires
    separately; this updates the matching config only."""
    return update_config(existing, _blend_config(on, join, joiner, left_unmatched, right_unmatched),
                         name=name, description=description)

def gen_ai_update(existing: dict, prompt: str, input_fields: list[str], provider_id: str | None = None,
                  row_limit: int = 1000, *, name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing gen_ai node's config (same args as `gen_ai`) in place. Verifying the
    result requires a live run, which can trigger paid LLM calls — that caveat is the editor's."""
    return update_config(existing, _gen_ai_config(prompt, input_fields, provider_id, row_limit),
                         name=name, description=description)

def summarize_update(existing: dict, group_by: list[str], aggs: list[tuple[str, str, str]], *,
                     name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing summarize node's config (same args as `summarize`) in place,
    applying the same argument-validity normalization/guard as `summarize`."""
    node_name = name or (existing.get("name") if isinstance(existing, dict) else None)
    return update_config(existing, _summarize_config(group_by, aggs, node_name=node_name),
                         name=name, description=description)

def pivot_update(existing: dict, pivot_field: str, value_field: str, calc: str = "AVG", *,
                 name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing pivot node's config (same args as `pivot`) in place."""
    return update_config(existing, _pivot_config(pivot_field, value_field, calc), name=name, description=description)

def rollup_update(existing: dict, date_col: str, group_by: list[str], aggs: list[tuple[str, str, str]],
                  periodicity: str = "day", *, name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing rollup node's config (same args as `rollup`) in place."""
    return update_config(existing, _rollup_config(date_col, group_by, aggs, periodicity),
                         name=name, description=description)

def unpivot_update(existing: dict, name_field: str, value_field: str, selected_fields: list[str],
                   mode: str = "unpivot", *, name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing unpivot node's config (same args as `unpivot`) in place."""
    return update_config(existing, _unpivot_config(name_field, value_field, selected_fields, mode),
                         name=name, description=description)

def json_update(existing: dict, mode: str, input_field: str, keep_input: bool = False, *,
                name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing json node's config (same args as `json_node`) in place."""
    return update_config(existing, _json_config(mode, input_field, keep_input), name=name, description=description)

def deduplicate_update(existing: dict, fields: list[str] | None = None,
                       sorts: list[tuple[str, str]] | None = None, mode: str = "distinct", *,
                       name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing deduplicate node's config (same args as `deduplicate`) in place."""
    return update_config(existing, _deduplicate_config(fields, sorts, mode), name=name, description=description)

def vision_update(existing: dict, prompt: str, input_field: str, provider_id: str | None = None, *,
                  name: str | None = None, description: str | None = None) -> dict:
    """Regenerate an existing vision node's config (same args as `vision`) in place. Like gen_ai,
    verifying the result requires a paid per-document run — that caveat is the editor's."""
    return update_config(existing, _vision_config(prompt, input_field, provider_id),
                         name=name, description=description)

# Node types without a dedicated `*_config`/`*_update` above (adapter, format, split, multi_stack,
# api_service, sample, fuzzy_match, explode, …) are still editable via the generic path: build a
# fresh node with the create constructor and merge its config, e.g.
#     update_config(live_node, adapter("x", specs)["config"])
# The constructors' config is independent of the node name, so the throwaway name is irrelevant.

# ---------------------------------------------------------------- canvas annotation (group / text)

# A broad, deliberately varied pastel palette (HSL hues across the wheel, ~75-82% lightness so
# black header text stays readable). Flow.group picks from a PER-FLOW shuffled copy so different
# workflows look different and groups within one flow get distinct colors — colorful, not the same
# fixed green every time — while staying deterministic (re-compiling a flow reproduces its colors).
_GROUP_PALETTE = [
    "hsl(78, 42%, 75%)", "hsl(207, 44%, 78%)", "hsl(8, 55%, 81%)", "hsl(45, 62%, 77%)",
    "hsl(280, 38%, 81%)", "hsl(170, 42%, 75%)", "hsl(330, 48%, 83%)", "hsl(24, 60%, 80%)",
    "hsl(125, 32%, 78%)", "hsl(250, 44%, 83%)", "hsl(192, 48%, 76%)", "hsl(55, 58%, 76%)",
]

def _group(name: str, color: str | None = None) -> dict:
    """A canvas GROUP frame (background rectangle that visually contains member nodes). Size and
    on-canvas position are set by Flow layout; use Flow.group(...) rather than adding this directly."""
    return {"id": _nid("group", name), "name": name, "type": "group", "inlets": [], "outlets": [],
            "config": {"color": color or _GROUP_PALETTE[0], "width": 240, "height": 200},
            "position": {"x": 40, "y": 0}, "canvasConfig": {},
            "isPristine": True, "isComputing": False, "isConfigured": True}

# Numeric thresholds in a group description ($0.01, 5 days, 5%) are the part a reviewer scans for,
# so they render bold. Detection is intentionally conservative — currency, percentages, and a
# number followed by a tolerance unit — because a miss is merely un-bolded text, never a logic
# change (this only decorates `config.text`, a display field the engine never traverses).
_THRESHOLD_RE = re.compile(
    r"(?<!\w)("
    r"\$\s?\d[\d,]*(?:\.\d+)?"                                              # $0.01, $1,000.50
    r"|\d[\d,]*(?:\.\d+)?\s?%"                                              # 5%, 2.5 %
    r"|\d[\d,]*(?:\.\d+)?\s(?:days?|hours?|hrs?|minutes?|mins?|seconds?|secs?"
    r"|weeks?|months?|years?|bps|cents?|dollars?|usd|eur|gbp)"              # 5 days, 0.01 USD
    r")([.,;:)]?)(?!\w)",                                                   # absorb trailing punctuation
    re.IGNORECASE,
)

def _strip_collapsed(s: str) -> str:
    """Mirror the validator's `rich_text_plain`: tags -> space, then whitespace-collapsed. Used to
    prove a bolded line still strips back to the same words as the plain line."""
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", s)).split())

def _emphasize_thresholds(escaped: str) -> str:
    """Wrap detected threshold tokens (plus any trailing punctuation) in `<strong>`. Operates on
    already-HTML-escaped text; threshold tokens carry no HTML-special characters, so
    emphasis-after-escape is injection-safe. Trailing punctuation is absorbed so the closing tag
    never lands between a token and a comma/period — which would otherwise insert a stray space
    when the validator strips tags and break `config.text`/`inputText` sync."""
    return _THRESHOLD_RE.sub(lambda m: f"<strong>{m.group(1)}{m.group(2)}</strong>", escaped)

def _header_html(title: str, description: str | None = None) -> str:
    """Rendered rich-text HTML for a group header (Savant renders `config.text`, not `inputText`).
    Title on the first line; each non-empty description line becomes its own smaller line below,
    with numeric thresholds auto-emphasized. Markdown is NOT interpreted — write descriptions as
    plain business text with real line breaks (`\\n`); `**bold**` would render literally. Each line
    is HTML-escaped before emphasis, so the rendered text stays in sync with `inputText` (the
    group-header validator strips tags and checks every `inputText` line survives)."""
    html = (f'<p style="margin: 0px; padding: 0px; text-align: center;">'
            f'<span class="text-style" style="font-size: 1.5rem;"><strong>{_html.escape(title)}</strong></span></p>')
    for line in (description or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        escaped = _html.escape(line)
        inner = _emphasize_thresholds(escaped)
        # Guarantee config.text/inputText sync: if emphasis would change the stripped, collapsed
        # words of this line (a rare punctuation-adjacency case the regex did not absorb), render
        # it plain. The cosmetic bold degrades gracefully; the done-gate sync invariant never does.
        if _strip_collapsed(inner) != _strip_collapsed(escaped):
            inner = escaped
        html += (f'<p style="margin: 0px; padding: 0px; text-align: center;">'
                 f'<span class="text-style" style="font-size: 0.875rem;">{inner}</span></p>')
    return html

def text(title: str, description: str | None = None, font_size: str = "1.5rem", bold: bool = True,
         color: str = "#000000", background: str = "transparent") -> dict:
    """A canvas TEXT annotation (e.g. a group header). `title` is the heading; optional
    `description` is a smaller second line. Both `inputText` (plain) and `config.text` (rendered
    rich HTML) are populated and kept in sync, with the full style set so it never renders as a
    grey band (headers use a transparent background)."""
    input_text = title + (f"\n{description}" if description else "")
    return {"id": _nid("text", title), "name": "Text", "type": "text", "inlets": [], "outlets": [],
            "config": {"bold": bold, "text": _header_html(title, description), "color": color,
                       "width": 174, "height": 69, "italic": False, "fontSize": font_size,
                       "minWidth": 150, "inputText": input_text, "minHeight": 69, "underline": False,
                       "borderColor": "#999999", "currentHeight": 69, "isInitialized": True,
                       "strikethrough": False, "backgroundColor": background},
            "position": {"x": 8, "y": 8}, "canvasConfig": {},
            "isPristine": True, "isComputing": False, "isConfigured": True}

# ---------------------------------------------------------------- Flow assembly

class Flow:
    def __init__(self, name: str, tag: str | None = None, description: str = ""):
        from contracts.tracking_tag import tracking_tag

        self.name, self.tag, self.description = name, tag or tracking_tag(), description
        self.nodes: list[dict] = []
        self._by_id: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}  # group_id -> {"header": text_id|None, "members": [ids]}
        self._node_units: dict[str, list[str]] = {}
        self._schema_hints: dict[str, list[str]] = {}

    def hint_schema(self, *entries: tuple) -> None:
        """Register AI-output schema hints (same `(node_or_id, [columns])` pairs as
        `nb.schema_hints`) ON the flow, at build time.

        Without this, every node downstream of a `vision`/`gen_ai`/`fuzzy_match` node has an
        unknown modeled schema during construction, so helpers like `keep_only_columns(...)`
        fail mid-build even though the hints exist — they were previously only passed at
        `write_workflow(...)` time, after construction (recurred on two real builds). Registered
        hints feed every `schema_at`/`schema_map`/`summary`/`compile` call automatically, and
        `write_workflow(...)` uses them when no explicit `schema_hints` argument is given."""
        self._schema_hints.update(schema_hints(*entries))

    def _merged_schema_hints(self, schema_hints: dict | None) -> dict | None:
        merged = dict(self._schema_hints)
        if schema_hints:
            merged.update(schema_hints)
        return merged or None

    def add(self, node: dict) -> str:
        if node["id"] in self._by_id:
            raise ValueError(f"duplicate node id {node['id']} (name collision: {node['name']!r})")
        self.nodes.append(node); self._by_id[node["id"]] = node
        return node["id"]

    def wire(self, a: str, b: str, out_idx: int = 0, in_idx: int = 0) -> None:
        # `a` may be a node id or a branch handle `{parent}|{idx}` from blend_outlet/filter_outlet.
        # A handle routes the edge onto the parent's embedded `out_{idx}` port; normalize_outlets
        # later expands that into the canonical `{parent}|{idx}` outlet child node.
        src_id, direct = a, a in self._by_id
        if not direct:
            handle = re.match(r"^(.+)\|(\d+)$", a)
            if handle and handle.group(1) in self._by_id:
                src_id, out_idx = handle.group(1), int(handle.group(2))
        src, dst = self._by_id[src_id], self._by_id[b]
        if direct and src.get("type") == "blend" and _blend_outlet_indices(src):
            raise ValueError("split blend outputs must be wired through blend_outlet(flow, blend_id, which).")
        outlets = src.setdefault("outlets", [])
        if not isinstance(outlets, list):
            outlets = src["outlets"] = []
        while len(outlets) <= out_idx:
            outlets.append({"id": f"out_{len(outlets)}", "targets": []})
        if dst.get("type") == "multi_stack":
            if not dst.get("inlets") or dst["inlets"][0].get("type") != "multisource":
                existing_sources: list[dict] = []
                for inlet in dst.get("inlets") or []:
                    if not isinstance(inlet, dict):
                        continue
                    if inlet.get("source"):
                        existing_sources.append({"source": inlet.get("source"), "sourceOutlet": inlet.get("sourceOutlet", "out_0")})
                    existing_sources.extend(source for source in inlet.get("sources") or [] if isinstance(source, dict))
                dst["inlets"] = [{"id": "in_0", "type": "multisource", "sources": existing_sources}]
            src["outlets"][out_idx]["targets"].append({"target": b, "targetInlet": "in_0"})
            dst["inlets"][0].setdefault("sources", []).append({"source": src_id, "sourceOutlet": f"out_{out_idx}"})
            return
        src["outlets"][out_idx]["targets"].append({"target": b, "targetInlet": f"in_{in_idx}"})
        dst["inlets"][in_idx]["source"] = src_id
        dst["inlets"][in_idx]["sourceOutlet"] = f"out_{out_idx}"

    def chain(self, *ids: str) -> None:
        for a, b in zip(ids, ids[1:]):
            self.wire(a, b)

    def _register_unit(self, handle: str, members: list[str]) -> None:
        unit = []
        for mid in members:
            if mid not in self._by_id:
                raise ValueError(f"unit member {mid!r} was not added to the flow.")
            if mid not in unit:
                unit.append(mid)
        if handle not in unit:
            raise ValueError(f"unit handle {handle!r} must be one of its members.")
        for mid in unit:
            self._node_units[mid] = list(unit)

    def _expand_group_members(self, members: list[str]) -> list[str]:
        expanded = []
        for mid in members:
            unit = self._node_units.get(mid, [mid])
            for uid in unit:
                if uid not in expanded:
                    expanded.append(uid)
        return expanded

    def group(self, name: str, members: list[str], header: str | None = None,
              description: str | None = None, color: str | None = None) -> str:
        """Put `members` (already-added node ids) into a labeled canvas group. `header` is the stage
        title and `description` an optional second line (recommended: a clear title+description reads
        well and satisfies the layout contract). Group membership is encoded ONLY in each node's
        `canvasConfig` (never top-level parentId — that collapses on import); Flow layout sizes the
        frame and positions members relative to it. Color defaults to a varied per-flow palette pick.
        Returns the group node id."""
        members = self._expand_group_members(members)
        if color is None:
            pal = list(_GROUP_PALETTE)
            random.Random(self.name).shuffle(pal)          # deterministic per-flow, varied across flows
            color = pal[len(self._groups) % len(pal)]
        gid = self.add(_group(name, color))
        header_id = None
        if header:
            tnode = text(header, description)
            tnode["canvasConfig"] = {"extent": "parent", "parentId": gid}
            header_id = self.add(tnode)
        for mid in members:
            if mid not in self._by_id:
                raise ValueError(f"group member {mid!r} was not added to the flow.")
            self._by_id[mid]["canvasConfig"] = {"extent": "parent", "parentId": gid}
        self._groups[gid] = {"header": header_id, "members": list(members)}
        return gid

    def to_dict(self) -> dict:
        # Synthesize/normalize outlet child nodes deterministically from each tool's branch
        # intent (collapse any existing children, re-expand from config flags). Idempotent, so
        # repeated to_dict()/schema_at() calls are stable. Rebuild the id index afterward since
        # this adds/removes `{parent}|i` outlet nodes.
        _outlets.normalize_outlets(self.nodes)
        self._by_id = {n["id"]: n for n in self.nodes if isinstance(n, dict) and isinstance(n.get("id"), str)}
        _layout_solver.solve(self.nodes)
        # Lift per-source profiling evidence to workflow-level `sourceProfiles`
        # (validator-readable). The private node key must never ship — extra source
        # config/node keys make import drop the node (verified live) — so the
        # emitted nodes are sanitized shallow copies; the in-memory flow keeps the
        # evidence so repeated to_dict()/schema_at() calls stay stable.
        source_profiles: dict[str, Any] = {}
        out_nodes: list[dict] = []
        for node in self.nodes:
            evidence = node.get("_profileEvidence")
            if evidence and isinstance(node.get("id"), str):
                source_profiles[node["id"]] = evidence
                node = {k: v for k, v in node.items() if k != "_profileEvidence"}
            out_nodes.append(node)
        out = {"name": self.name, "description": self.description, "tags": [self.tag], "nodes": out_nodes}
        if source_profiles:
            out["sourceProfiles"] = source_profiles
        return out

    def schema_at(self, node_id_or_name: str, *, schema_hints: dict | None = None) -> dict:
        """Return the validator-modeled output schema for a node id or unique display name."""
        from validators.workflow import infer_output_schemas

        schemas = infer_output_schemas(self.to_dict(), schema_hints=self._merged_schema_hints(schema_hints))
        if node_id_or_name in schemas:
            return schemas[node_id_or_name]
        matches = [schema for schema in schemas.values() if schema.get("name") == node_id_or_name]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"no node found for {node_id_or_name!r}.")
        raise ValueError(f"multiple nodes named {node_id_or_name!r}; pass the node id instead.")

    def summary(self, *, schema_hints: dict | None = None) -> str:
        """Compact graph summary: node names/types plus resolved output columns when knowable."""
        schemas = {item["id"]: item for item in self.schema_map(schema_hints=schema_hints)}
        lines = [f"{self.name}"]
        for node in self.nodes:
            if node.get("type") in {"group", "text", "outlet"}:
                continue
            schema = schemas.get(node.get("id"), {})
            columns = schema.get("columns") or []
            col_text = ", ".join(columns) if columns else ("unknown schema" if not schema.get("known") else "no columns")
            lines.append(f"- {node.get('name')} [{node.get('type')}] -> {col_text}")
        return "\n".join(lines)

    def schema_map(self, *, schema_hints: dict | None = None) -> list[dict]:
        """Return resolved output schemas for all nodes in flow order."""
        from validators.workflow import infer_output_schemas

        schemas = infer_output_schemas(self.to_dict(), schema_hints=self._merged_schema_hints(schema_hints))
        return [schemas[node["id"]] for node in self.nodes if node.get("id") in schemas]

    def compile(self, *, validate: bool = True, schema_hints: dict | None = None,
                required_tag: str | None = None, allow_warnings: bool = True,
                out: str | Path | bool | None = None,
                planner_handoff: str | Path | None = None) -> dict:
        """Assemble and (by default) validate via `savant.py validate workflow`. Returns the workflow
        dict, or raises ValueError with the validator's ERROR/WARN lines if it does not pass.

        By default, also persists the validated workflow to
        ``tmp/<ai-session-id>/<workflow-slug>/<Workflow Name>.json``. If ``validate=False``, default persistence is
        disabled so unchecked drafts do not silently land in ``tmp``; pass a path to ``out=...`` only
        when the Builder artifact should still pass the Planner handoff gate before writing.
        Any persisted Builder artifact requires ``planner_handoff`` and a passing Builder precheck
        gate; pass ``out=False`` for in-memory schema probes.
        """
        wf = self.to_dict()
        schema_hints = self._merged_schema_hints(schema_hints)
        # Enforce the flow's own tracking tag by default so every built flow is validated
        # against a versioned Savvy tag without the caller having to pass it.
        if required_tag is None:
            required_tag = self.tag
        will_persist = out is not False and (validate or out is not None)
        if will_persist:
            _check_builder_preflight_gate(planner_handoff)
        if validate or will_persist:
            processing_input_errors = _builder_processing_input_errors(wf)
            if processing_input_errors:
                raise ValueError("compile() graph validation failed:\n" + "\n".join(f"ERROR: {e}" for e in processing_input_errors))
        if validate:
            import json as _json, subprocess, tempfile, os, sys
            here = Path(__file__).resolve().parents[1]
            with tempfile.TemporaryDirectory() as td:
                wf_path = os.path.join(td, "wf.json")
                Path(wf_path).write_text(_json.dumps(wf))
                cmd = [sys.executable, str(here / "savant.py"), "validate", "workflow", wf_path]
                if schema_hints:
                    sh_path = os.path.join(td, "hints.json")
                    Path(sh_path).write_text(_json.dumps(schema_hints))
                    cmd += ["--schema-hints", sh_path]
                if required_tag:
                    cmd += ["--required-tag", required_tag]
                cmd += ["--block-mergeable-pairs"]
                if allow_warnings:
                    cmd += ["--allow-warnings"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    raise ValueError("compile() validation failed:\n" + (res.stdout or res.stderr))
        if will_persist:
            output_path = Path(out) if out is not None else default_workflow_output_path(self.name)
            save_json(wf, output_path)
        return wf


def write_workflow(
    flow: Flow | dict,
    name: str | None = None,
    out: str | Path | None = None,
    schema_hints: dict | None = None,
    hints_out: str | Path | bool | None = None,
    planner_handoff: str | Path | None = None,
    **compile_kwargs,
) -> Path:
    """Persist a workflow through the library-owned default path resolver.

    ``flow`` may be a ``Flow`` instance or an already-compiled workflow dict. When no output path
    is supplied, the file is written under ``tmp/<ai-session-id>/<workflow-slug>/<Workflow Name>.json``. When
    ``schema_hints`` is supplied, a validator sidecar is written next to the workflow as
    ``<Workflow Name>.schema-hints.json`` unless ``hints_out=False``. A Planner -> Builder handoff
    is required and must pass the Builder precheck gate before any artifact is written.
    """
    handoff_evidence = _check_builder_preflight_gate(planner_handoff)
    # The approved plan IS the documentation: the formatted process/outputs/assumptions from the
    # Planner handoff become the workflow description's body, appended to the builder's lead summary.
    plan_body = description_from_plan(handoff_evidence)
    has_plan_body = bool(plan_body) and plan_body != PLAN_SECTION_HEADING

    def _with_plan_body(description: str | None) -> str:
        # Append the plan body once (idempotent on re-write); the `## Process` heading is the marker.
        text = description or ""
        if has_plan_body and PLAN_SECTION_HEADING not in text:
            text = (text.rstrip() + "\n\n" + plan_body).strip()
        return text

    if isinstance(flow, Flow):
        workflow_name = name or flow.name
        flow.description = _with_plan_body(flow.description)
        schema_hints = flow._merged_schema_hints(schema_hints)
        wf = flow.compile(out=False, schema_hints=schema_hints, **compile_kwargs)
    else:
        wf = flow
        workflow_name = name or str(wf.get("name") or "workflow")
        if isinstance(wf, dict):
            wf["description"] = _with_plan_body(wf.get("description"))
    # Enforce the rule on the artifact itself: a workflow built from a Planner handoff must carry the
    # approved plan in its description. write_workflow is the sole sanctioned write path, so this is the
    # chokepoint — fail rather than emit a workflow whose documentation drifted from the approved plan.
    if has_plan_body:
        final_description = wf.get("description") if isinstance(wf, dict) else None
        if not isinstance(final_description, str) or plan_body not in final_description:
            raise ValueError(
                "write_workflow() plan-fidelity check failed: the workflow description must include the "
                "approved Planner plan (the `## Process` section rendered from the planner handoff). "
                "write_workflow appends it for you from planner_handoff — do not overwrite or omit it."
            )
    processing_input_errors = _builder_processing_input_errors(wf)
    if processing_input_errors:
        raise ValueError("write_workflow() graph validation failed:\n" + "\n".join(f"ERROR: {e}" for e in processing_input_errors))
    # Layout quality is part of the artifact, not a silent warning. A connector through a node
    # or group frame makes the canvas unreadable, and burying it in --allow-warnings output is
    # how an unreadable layout shipped live (2026-06-10). Print the measured counts every time
    # and flag corridor defects explicitly so the builder fixes them before handoff.
    try:
        from . import layout_metrics as _lm
        layout = _lm.measure(wf)
        through_n = len(layout.get("through_nodes") or [])
        through_g = len(layout.get("through_groups") or [])
        overlaps = len(layout.get("node_overlaps") or []) + len(layout.get("group_overlaps") or [])
        summary = (f"layout: {through_n} connector(s) through nodes, {through_g} through group frames, "
                   f"{overlaps} overlap(s), {len(layout.get('crossings') or [])} crossing(s)")
        if through_n or through_g or overlaps:
            print(f"  [warn] {summary} — fix the layout before handing off; "
                  "a connector through a node/frame is a delivery defect, not a style preference.")
        else:
            print(f"  [ok ] {summary}")
    except Exception:  # noqa: BLE001 — metrics must never block writing the artifact itself
        pass
    output_path = Path(out) if out is not None else default_workflow_output_path(workflow_name)
    save_json(wf, output_path)
    if schema_hints and hints_out is not False:
        hints_path = Path(hints_out) if hints_out is not None else default_schema_hints_output_path(output_path)
        save_json(schema_hints, hints_path)
    return output_path
