#!/usr/bin/env python3
"""Assemble compact Builder reference packets from canonical live docs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# Human-readable docs and the registry JSON both live under references/.
COMPONENTS = ROOT / "references" / "components"
STANDARDS = ROOT / "references" / "standards"
REGISTRY = ROOT / "references" / "registry" / "components"
API_DOC = STANDARDS / "node-builders-api.md"
DATA_PREP_DOC = STANDARDS / "data-prep-normalization.md"
NODE_DOC_DOC = STANDARDS / "node-documentation-rules.md"

ALIASES = {
    "api_service": "apiService",
    "api-service": "apiService",
    "api": "apiService",
    "join": "blend",
    "stack": "multi_stack",
    "transform": "edit",
}

API_SECTION = {
    "source": "Source / Destination",
    "adapter": "Reshape",
    "destination": "Source / Destination",
    "edit": "Transform",
    "filter": "Filter",
    "pdfilter": "Filter",
    "blend": "Blend",
    "summarize": "Aggregate",
    "rollup": "Aggregate",
    "deduplicate": "Aggregate",
    "sample": "Aggregate",
    "hierarchy": "Aggregate",
    "json": "Reshape",
    "xml": "Reshape",
    "pivot": "Reshape",
    "unpivot": "Reshape",
    "format": "Reshape",
    "split": "Reshape",
    "explode": "Reshape",
    "multi_stack": "Reshape",
    "gen_ai": "AI / Service",
    "vision": "AI / Service",
    "fuzzy_match": "AI / Service",
    "apiService": "AI / Service",
    "service": "AI / Service",
    "group": "Flow",
    "text": "Flow",
    "flow": "Flow",
}

CONSTRUCTOR_NAMES = {
    "source": ["source_unit_from_plan", "source", "standardized_source"],
    "adapter": ["adapter", "adapter_specs"],
    "destination": ["destination_from_plan", "destination_csv"],
    "edit": ["edit_node", "op_json_field", "op_json_number", "op_cast", "op_date_diff", "op_const", "op_expr",
             "op_case", "op_count_if", "op_default_constant", "op_arith", "op_avg", "op_window",
             "op_rename", "op_retype", "op_transform", "edit_update"],
    "filter": ["filter_node", "filter_expr", "filter_outlet", "filter_update"],
    "pdfilter": ["filter_node", "filter_expr", "filter_update"],
    "blend": ["blend", "blend_outlet", "blend_update"],
    "summarize": ["summarize", "summarize_update"],
    "rollup": ["rollup", "rollup_update"],
    "deduplicate": ["deduplicate", "deduplicate_update"],
    "sample": ["sample_top"],
    "hierarchy": ["hierarchy"],
    "json": ["json_node", "json_update"],
    "xml": ["xml_node"],
    "pivot": ["pivot"],
    "unpivot": ["unpivot"],
    "format": ["format_node"],
    "split": ["split_node"],
    "explode": ["explode_node"],
    "multi_stack": ["multi_stack"],
    "gen_ai": ["gen_ai", "gen_ai_json_flatten", "gen_ai_node_for_json_flatten", "gen_ai_output_field", "schema_hints", "gen_ai_update"],
    "vision": ["vision", "schema_hints", "vision_update"],
    "fuzzy_match": ["fuzzy_match", "schema_hints", "fuzzy_match_update"],
    "apiService": ["api_service"],
    "group": ["Flow"],
    "text": ["text"],
    "flow": ["Flow", "write_workflow", "default_workflow_output_path"],
}

COMPONENT_GUIDANCE = {
    "notes": "Canvas note only. No supported constructor; do not generate for new data workflows. If preserving an existing note, keep it as annotation only.",
    "outlet": "Do not author directly. Create outlets through the parent helper: `nb.filter_outlet(...)` or `nb.blend_outlet(...)` after enabling the parent split/unmatched path.",
    "pdsummarize": "Inspect/edit existing pushdown summarize nodes only. Do not generate new nodes until an export-backed constructor is added; use `nb.summarize(...)` when unsure.",
    "search_replace": "Inspect/edit existing search-and-replace nodes only. Do not generate new nodes until an export-backed constructor is added; use `nb.edit_node(...)` expression or regex operations when possible.",
    "service": "Legacy service node. Preserve existing nodes with `nb.update_config(...)`; for new HTTP calls use `nb.api_service(...)`, and for new AI prompts use `nb.gen_ai(...)`.",
}

LIST_KEYS = (
    "modes",
    "generationModes",
    "joiners",
    "regions",
    "conditionalOperators",
    "calcs",
    "serviceTypes",
    "connectorTypes",
    "specDataTypes",
    "subsequentModes",
    "profileEvidenceConnectorTypes",
)
CAP = 30

COOKBOOK = """## Builder cookbook

Verified canonical snippets for common builds. Prefer these patterns before opening `builders.py`.

### Source + standardize

```python
src = nb.source_unit_from_plan(f, source_plan)
```

Use the full Planner source object. It creates the source plus the standardizing Adapter when schema/date evidence requires it.

### Left join with resolved duplicate fields

```python
join = f.add(nb.blend("Enrich orders with returns", [("Order ID", "Order ID")], join="left"))
f.wire(orders, join, in_idx=0)
f.wire(returns, join, in_idx=1)
flag = f.add(nb.edit_node("Returned flag", ops=[
    nb.op_count_if("Returned Flag", nb.cond("Returned", "not_null", dtype="string"))
]))
f.wire(join, flag)
```

After Blend, right-side duplicate fields use display names like `Field (rhs)` and exact live ids like `Field_2`. Use display-name expressions such as `` `Amount (rhs)` ``; for `drop=`/`order=`, pass the exact live id/display name.
Use `flow.schema_at(join)` or `savant.py validate workflow workflow.json --show-schema <nodeId>` to copy the resolved duplicate names before hiding/reordering them.

### Source-prep normalized keys before Blend

```python
orders_prep = f.add(nb.edit_node("Normalize order keys", ops=[
    nb.op_normalized_join_key("Customer Key", "Customer ID"),
    nb.op_expr("Order ID Digits", 'REGEX_EXTRACT(`Order ID`, "([0-9]+)$")', "string")
]))
returns_prep = f.add(nb.edit_node("Normalize return keys", ops=[
    nb.op_normalized_join_key("Customer Key", "Customer ID"),
    nb.op_normalized_join_key("Return Order ID Text", "Order ID")
]))
join = f.add(nb.blend("Match returns", [("Order ID Digits", "Return Order ID Text")], join="left"))
```

Create known join keys once in each source-prep stream, immediately after the adapter/extraction/parser, then reuse those fields everywhere downstream. Join keys should usually use the type-safe `UPPER(TRIM(TO_TEXT(...)))` through `nb.op_normalized_join_key(...)` (the cast keeps numeric ids like ZIP codes from failing at runtime) unless the user confirms case or spaces are business-significant. Use prefix/suffix/digit extraction only when the source profile or user confirms the derived relationship.

### Matched vs unmatched split (verified live)

```python
join = f.add(nb.blend("Match stores", [("Zip Key", "Zip Key")], join="inner", left_unmatched=True))
f.wire(sales_prep, join, in_idx=0)
f.wire(stores_prep, join, in_idx=1)
f.wire(nb.blend_outlet(f, join, "matched"), by_state_summary)
f.wire(nb.blend_outlet(f, join, "left_unmatched"), unmatched_report)
```

Use an **inner** join when splitting matched vs unmatched. A left/right/full join's main output already
includes the unmatched rows (null columns from the other side), so a `join="left"` split sends
unmatched rows down the "matched" fork and downstream summaries silently include null-key rows.
The builder and validator both warn on a non-inner join combined with an unmatched fork.

### Null-safe count then summarize

```python
flag = f.add(nb.edit_node("Review flags", ops=[
    nb.op_count_if("Negative Review Flag", nb.cond("Sentiment", "eq", "Negative", "string"))
]))
summary = f.add(nb.summarize("By region", ["Region"], [
    ("COUNT", "Row", "Total Items"),
    ("SUM", "Returned Flag", "Returned Items"),
    ("SUM", "Negative Review Flag", "Negative Reviews"),
    ("AVG", "Ship Days", "Average Ship Days"),
]))
```

Do not count nullable right-side join fields when unmatched rows should contribute zero.

### Compute, clean nulls, arrange output

```python
calc = f.add(nb.edit_node("Prepare report fields", ops=[
    nb.op_date_diff("Ship Days", "Ship Date", "Order Date", "day"),
    nb.op_default_constant("Profit Safe", "Profit", 0, dt="number"),
], order=["Order ID", "Order Date", "Ship Date", "Ship Days", "Region", "Profit Safe"]))
```

One edit node can hold ordered dependent calculations plus ordering/drops. Put prerequisite calculations earlier in `ops`, then later calculations that reference those new fields.
`order=`/`drop=` also work downstream of a Blend; the validator resolves normal columns by derived id, while Blend `(rhs)` duplicates still need their exact live id/display name.

### GenAI JSON extraction

```python
flat = nb.gen_ai_json_flatten(
    f,
    "Classify review sentiment",
    "Return JSON with sentiment, evidence, confidence for: {Review}",
    ["Review"],
    provider_id,
    flatten_description="Flatten sentiment JSON for reporting.",
)
hints = nb.schema_hints((nb.gen_ai_node_for_json_flatten(f, flat), ["sentiment", "evidence", "confidence"]))
```

Attach downstream schema hints to the AI node when generated columns are referenced later; the JSON flatten
handle is for downstream wiring/grouping, not for schema hints.

### Multiple report outputs

```python
summary_out = f.add(nb.destination_from_plan(output_plan["outputs"][0]))
detail_out = f.add(nb.destination_from_plan(output_plan["outputs"][1]))
```

Build one destination per planned output so Creator/Inspector can verify expected columns per output.

### Layout and handoff

```python
f.group("Summarize returns", [summary], header="Summarize returns", description="Compute regional return metrics.")
path = nb.write_workflow(f, planner_handoff=planner_to_builder_handoff_path, schema_hints=hints)
```

`write_workflow(...)` runs the Builder precheck gate from the Planner handoff before writing JSON.
Descriptions and grouped business blocks are part of validation; live import and verification belong to Creator.
"""


def canonical_component(value: str) -> str:
    key = value.strip()
    return ALIASES.get(key, key)


def sections(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        match = re.match(r"^##\s+(.*)$", line)
        if match:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = match.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + len("\n---\n") :]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        metadata[key.strip()] = value
    return metadata, text[end + len("\n---\n") :]


def data_prep_excerpt() -> str:
    data_prep_sections = sections(strip_frontmatter(DATA_PREP_DOC.read_text(encoding="utf-8")))
    wanted = [
        "Default Action",
        "Do Not",
        "Normalize Values",
        "Verify Data Prep",
    ]
    out: list[str] = [
        "## Data prep and normalization",
        "",
        "> Source of truth: `data-prep-normalization.md`. This excerpt is included in Builder packets so Builder does not maintain a second copy of data-prep rules.",
        "",
    ]
    for heading in wanted:
        body = data_prep_sections.get(heading)
        if body is None:
            raise SystemExit(
                f"section {heading!r} not found in {DATA_PREP_DOC.name}; "
                "update data_prep_excerpt() in docs/builder_pack.py to match the document headings"
            )
        out.extend([f"### {heading}", "", body, ""])
    return "\n".join(out).rstrip()


def node_documentation_excerpt() -> str:
    node_doc_sections = sections(strip_frontmatter(NODE_DOC_DOC.read_text(encoding="utf-8")))
    wanted = [
        "Default Action",
        "Fidelity Rules",
        "Node-Specific Readouts",
        "Auto-Update Rule",
    ]
    out: list[str] = [
        "## Node documentation",
        "",
        "> Source of truth: `node-documentation-rules.md`. This excerpt is included in Builder packets so generated step descriptions are node-specific configuration readouts, not generic summaries.",
        "",
    ]
    for heading in wanted:
        body = node_doc_sections.get(heading)
        if body is None:
            raise SystemExit(
                f"section {heading!r} not found in {NODE_DOC_DOC.name}; "
                "update node_documentation_excerpt() in docs/builder_pack.py to match the document headings"
            )
        out.extend([f"### {heading}", "", body, ""])
    return "\n".join(out).rstrip()


def first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    match = re.search(r"(.+?[.!?])(\s|$)", compact)
    return (match.group(1) if match else compact)[:240]


def api_call_names(api_sections: dict[str, str]) -> set[str]:
    names: set[str] = set()
    for body in api_sections.values():
        names.update(match.group(1) for match in re.finditer(r"\bnb\.([A-Za-z_]\w*)\(", body))
    return names


def constructors_for(stem: str, api_sections: dict[str, str]) -> list[str]:
    available = api_call_names(api_sections)
    wanted = CONSTRUCTOR_NAMES.get(stem, [])
    return [name for name in wanted if name == "Flow" or name in available]


def capped(values: list[Any]) -> str:
    rendered = [str(value) for value in values]
    suffix = f", ... (+{len(rendered) - CAP})" if len(rendered) > CAP else ""
    return ", ".join(rendered[:CAP]) + suffix


def registry_summary(stem: str) -> str:
    path = REGISTRY / f"{stem}.json"
    if not path.exists():
        return "_(no registry entry)_"
    data = json.loads(path.read_text(encoding="utf-8"))
    lines: list[str] = []

    config_schema = data.get("configSchema")
    if isinstance(config_schema, dict):
        if config_schema.get("required"):
            lines.append(f"- **required:** {capped(config_schema['required'])}")
        if isinstance(config_schema.get("enum"), dict):
            for key, value in config_schema["enum"].items():
                lines.append(f"- **enum `{key}`:** {capped(value)}")
        for key in ("nonEmptyString", "nonEmptyList", "positiveIntOrNumericString"):
            if config_schema.get(key):
                lines.append(f"- **{key}:** {capped(config_schema[key])}")
    for key in LIST_KEYS:
        value = data.get(key)
        if isinstance(value, list) and value:
            lines.append(f"- **{key}:** {capped(value)}")
    for key, value in data.items():
        if isinstance(value, dict) and key != "configSchema":
            lines.append(f"- **{key}:** {capped(list(value.keys()))}")
    for key, value in data.items():
        if key.lower().startswith("unsupported") and isinstance(value, list) and value:
            lines.append(f"- **{key} (DO NOT USE):** {capped(value)}")
    return "\n".join(lines) if lines else "_(registry entry has no enum/required facts)_"


def known_components() -> list[str]:
    return sorted(path.stem for path in COMPONENTS.glob("*.md") if path.stem != "_index")


def build_packet(components: list[str], include_frame: bool = True) -> str:
    api_sections = sections(API_DOC.read_text(encoding="utf-8"))
    out: list[str] = ["# Builder packet", ""]

    if include_frame:
        out.extend(["> Shared frame. Use `--no-frame` to omit on follow-up calls.", ""])
        reference_boundaries = api_sections.get("Reference Boundaries", "").strip()
        if reference_boundaries:
            out.extend(["## Reference boundaries", "", reference_boundaries, ""])
        mental_model = api_sections.get("Mental Model", "").strip()
        if mental_model:
            out.extend(["## Mental model", "", mental_model, ""])
        route = api_sections.get("Route", "").strip()
        if route:
            out.extend(["## Route", "", route, ""])
        out.extend(["---", ""])

    flow = api_sections.get("Flow", "").strip()
    if flow:
        out.extend([
            "## Flow assembly",
            "",
            "Every Builder packet includes this section because component constructors are not enough to safely assemble a workflow.",
            "",
            "### Route / API - node-builders-api.md > Flow",
            "",
            flow,
            "",
            "---",
            "",
        ])

    out.extend([COOKBOOK, "", "---", ""])
    out.extend([node_documentation_excerpt(), "", "---", ""])
    out.extend([data_prep_excerpt(), "", "---", ""])

    for raw in components:
        stem = canonical_component(raw)
        doc = COMPONENTS / f"{stem}.md"
        title = f"## {stem}" if stem == raw else f"## {stem} (alias: {raw})"
        out.append(title)
        if not doc.exists():
            out.extend([
                f"_No component doc `{stem}.md`. Known types: {', '.join(known_components())}._",
                "",
            ])
            continue
        component_meta, component_body = parse_frontmatter(doc.read_text(encoding="utf-8"))
        component_sections = sections(component_body)
        purpose = component_meta.get("registry_summary") or first_sentence(component_sections.get("Business purpose", ""))
        if purpose:
            out.append(f"_{purpose}_")

        section_name = API_SECTION.get(stem)
        if section_name and section_name in api_sections:
            out.extend(["", f"### Route / API - node-builders-api.md > {section_name}", "", api_sections[section_name].strip()])

        constructors = constructors_for(stem, api_sections)
        out.extend(["", "### node_builders constructors", ""])
        if constructors:
            out.append(", ".join(f"`nb.{name}(...)`" if name != "Flow" else "`nb.Flow(...)`" for name in constructors))
        else:
            out.append("_No component-specific constructor in node-builders-api.md; hand-author only when the documented unsupported guidance allows it._")

        guidance = COMPONENT_GUIDANCE.get(stem)
        if guidance:
            out.extend(["", "### Build guidance", "", guidance])

        out.extend(["", "### Config contract (registry)", "", registry_summary(stem)])
        invariants = component_sections.get("Invariants", "").strip()
        gotchas = component_sections.get("Gotchas", "").strip()
        migration = component_sections.get("Migration mapping", "").strip()
        if invariants:
            out.extend(["", "### Invariants", "", invariants])
        if gotchas:
            out.extend(["", "### Gotchas", "", gotchas])
        if migration:
            out.extend(["", "### Migration mapping", "", migration])
        out.extend(["", "---", ""])

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact Builder packet for one or more component types.")
    parser.add_argument("components", nargs="+", help="component type(s), e.g. source blend summarize gen_ai")
    parser.add_argument("--no-frame", action="store_true", help="omit Reference Boundaries, Mental Model, and Route")
    args = parser.parse_args()
    sys.stdout.write(build_packet(args.components, include_frame=not args.no_frame))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
