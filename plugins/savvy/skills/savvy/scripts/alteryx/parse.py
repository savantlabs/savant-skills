#!/usr/bin/env python3
"""Parse an Alteryx workflow package (.yxmd / .yxwz / .yxmc / .yxzp) into a migration inventory.

Output: one JSON file with
  - workflow metadata and every tool (id, type, category, annotation, config summary, parent container)
  - connections (origin tool/anchor -> destination tool/anchor)
  - inputs / outputs / macros / external dependencies
  - validation checkpoints (tools where row counts change) with inferred grain keys
  - behaviour-difference traps found in this workflow
  - dead-code / inconsistency heuristics
  - a coverage summary (mapped exact / equivalent / approximated / unsupported / dropped)

Usage (through the toolchain router):
  savant.py alteryx parse <file.yxmd|.yxzp> [--out inventory.json] [--markdown inventory.md]

With no --out the inventory lands in the session tmp dir (`savant.py session tmp-path alteryx`).
The tool-to-Savant mapping lives in solutions/alteryx/references/tool-mapping.json; edit that
file, not this script, to change how a tool type is classified. `--mapping` overrides the path.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from savant_api.fileio import workspace_tmp  # noqa: E402

# scripts/alteryx/parse.py -> skills/savvy/solutions/alteryx/references/tool-mapping.json
MAPPING_PATH = SCRIPTS_DIR.parent / "solutions" / "alteryx" / "references" / "tool-mapping.json"

# ----------------------------------------------------------------------------- loading

def load_package(path: Path) -> dict[str, ET.Element]:
    """Return {relative_name: root_element} for every workflow/macro XML in the input."""
    docs: dict[str, ET.Element] = {}
    if path.suffix.lower() == ".yxzp":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if Path(name).suffix.lower() in {".yxmd", ".yxwz", ".yxmc"}:
                    docs[name] = ET.fromstring(z.read(name))
    else:
        docs[path.name] = ET.parse(path).getroot()
    if not docs:
        raise SystemExit(f"No Alteryx workflow XML found in {path}")
    return docs


def plugin_of(node: ET.Element) -> str:
    gs = node.find("GuiSettings")
    return (gs.get("Plugin") or "") if gs is not None else ""


def tool_type(node: ET.Element) -> tuple[str, str | None]:
    """Return (type_name, macro_path). Macros are identified from EngineSettings."""
    es = node.find("EngineSettings")
    macro = es.get("Macro") if es is not None else None
    if macro:
        return ("Macro", macro.replace("\\\\", "\\"))
    plugin = plugin_of(node)
    if plugin.endswith(".0"):  # some macro/app plugins register as '<Name>.0'
        return ("Macro", plugin)
    name = plugin.split(".")[-1] or "Unknown"
    return (name, None)


def text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


# ----------------------------------------------------------------------------- config summaries

def summarize_config(ttype: str, node: ET.Element) -> dict:  # noqa: C901
    """Extract the business-relevant settings per tool type (best effort, lossless fallback)."""
    cfg = node.find("Properties/Configuration")
    out: dict = {}
    if cfg is None:
        return out
    if ttype == "DbFileInput":
        f = text(cfg.find("File"))
        conn, _, query = f.partition("|||")
        out["connection"] = conn
        fso = cfg.find("FormatSpecificOptions")
        if fso is not None:
            for tag in ("HeaderRow", "Delimeter", "CodePage", "FieldLen"):
                v = text(fso.find(tag))
                if v:
                    out[{"HeaderRow": "header_row", "Delimeter": "delimiter", "CodePage": "code_page", "FieldLen": "field_len"}[tag]] = v
        meta = node.find("Properties/MetaInfo/RecordInfo")
        if meta is not None:
            out["fields"] = [f.get("name") for f in meta.findall("Field")]
            out["field_types"] = {f.get("name"): f.get("type") for f in meta.findall("Field") if f.get("type")}
        if query:
            out["query"] = query
            out["tables"] = sorted(set(re.findall(r'(?:FROM|JOIN)\s+((?:"?[\w]+"?\.){0,2}"?[\w]+"?)', query, re.I)))
    elif ttype == "DbFileOutput":
        out["file"] = text(cfg.find("File"))
    elif ttype == "Filter":
        out["mode"] = text(cfg.find("Mode"))
        out["expression"] = text(cfg.find("Expression"))
        simple = cfg.find("Simple")
        if simple is not None:
            out["field"] = text(simple.find("Field"))
            out["operator"] = text(simple.find("Operator"))
            ops = simple.find("Operands")
            out["operand"] = text(ops.find("Operand")) if ops is not None else ""
    elif ttype in {"Formula", "MultiRowFormula"}:
        fields = []
        for ff in cfg.iter("FormulaField"):
            fields.append({"field": ff.get("field"), "expression": ff.get("expression"), "type": ff.get("type"), "size": ff.get("size")})
        if ttype == "MultiRowFormula":
            upd = cfg.find("UpdateField")
            updating = upd is not None and upd.get("value") == "True"
            fields.append({"field": text(cfg.find("UpdateField_Name")) if updating else text(cfg.find("CreateField_Name")),
                           "expression": text(cfg.find("Expression")),
                           "type": "(existing field)" if updating else text(cfg.find("CreateField_Type")),
                           "group_by": [f.get("field") for f in cfg.findall("GroupByFields/Field")],
                           "num_rows": (cfg.find("NumRows").get("value") if cfg.find("NumRows") is not None else ""),
                           "other_rows": text(cfg.find("OtherRows"))})
        out["fields"] = fields
    elif ttype == "AlteryxSelect":
        sel = [{"field": s.get("field"), "selected": s.get("selected"), "rename": s.get("rename"),
                "type": (f"{s.get('type')}({s.get('size')})" if s.get("type") and s.get("size") else s.get("type"))}
               for s in cfg.iter("SelectField")]
        out["deselected"] = [s["field"] for s in sel if s["selected"] == "False" and s["field"] != "*Unknown"]
        out["renamed"] = {s["field"]: s["rename"] for s in sel if s.get("rename")}
        out["retyped"] = {s["field"]: s["type"] for s in sel if s.get("type")}
        out["unknown_dropped"] = any(s["field"] == "*Unknown" and s["selected"] == "False" for s in sel)
    elif ttype == "Summarize":
        out["group_by"] = [s.get("field") for s in cfg.iter("SummarizeField") if s.get("action") == "GroupBy"]
        out["aggs"] = [{"field": s.get("field"), "action": s.get("action"), "rename": s.get("rename")}
                       for s in cfg.iter("SummarizeField") if s.get("action") != "GroupBy"]
    elif ttype in {"Join", "JoinMultiple"}:
        out["keys"] = [(text(j.find("Field")) if j.find("Field") is not None else j.get("field")) for j in cfg.findall("JoinInfo/Field")]
        li = [j for j in cfg.findall("JoinInfo") if j.get("connection") == "Left"]
        ri = [j for j in cfg.findall("JoinInfo") if j.get("connection") == "Right"]
        out["left_keys"] = [f.get("field") for j in li for f in j.findall("Field")]
        out["right_keys"] = [f.get("field") for j in ri for f in j.findall("Field")]
    elif ttype == "Unique":
        out["fields"] = [f.get("field") for f in cfg.findall("UniqueFields/Field")]
    elif ttype == "Sort":
        out["fields"] = [{"field": f.get("field"), "order": f.get("order")} for f in cfg.findall("SortInfo/Field")]
    elif ttype == "Union":
        out["mode"] = text(cfg.find("Mode"))
        out["by_name"] = text(cfg.find("ByName_ErrorMode"))
    elif ttype == "AppendFields":
        out["warn_on_multiple"] = text(cfg.find("Warn"))
    elif ttype == "TextBox":
        out["text"] = text(cfg.find("Text"))
    elif ttype in {"Browse", "BrowseV2"}:
        pass  # preview only; the config is a local temp path, not business logic
    elif ttype == "Macro":
        vals = {}
        for v in cfg.iter("Value"):
            k = v.get("name") or ""
            if re.search(r"allDatasources|totalNum|totalDatasources|currentPage|password|token|secret", k, re.I):
                continue
            vals[k] = (v.text or "").strip()[:200]
        out["parameters"] = vals
    else:
        raw = ET.tostring(cfg, encoding="unicode")
        out["raw_config"] = re.sub(r"\s+", " ", raw)[:600]
    return out


# ----------------------------------------------------------------------------- inventory

def walk_nodes(parent: ET.Element, container: str | None, acc: list, containers: dict):
    for node in parent.findall("Node"):
        tid = node.get("ToolID")
        ttype, macro = tool_type(node)
        ann = text(node.find("Properties/Annotation/AnnotationText"))
        default_ann = text(node.find("Properties/Annotation/DefaultAnnotationText"))
        pos = node.find("GuiSettings/Position")
        entry = {
            "tool_id": tid, "type": ttype, "macro": macro, "plugin": plugin_of(node),
            "annotation": ann, "default_annotation": default_ann[:300],
            "container": container,
            "position": {"x": float(pos.get("x", 0)), "y": float(pos.get("y", 0))} if pos is not None else None,
            "config": summarize_config(ttype, node),
        }
        if ttype == "ToolContainer":
            cap = text(node.find("Properties/Configuration/Caption"))
            containers[tid] = cap
            entry["caption"] = cap
            entry["disabled"] = text(node.find("Properties/Configuration/Disabled")) == "True"
        acc.append(entry)
        child = node.find("ChildNodes")
        if child is not None:
            walk_nodes(child, tid, acc, containers)


def parse_workflow(root: ET.Element, name: str) -> dict:
    tools: list = []
    containers: dict = {}
    walk_nodes(root.find("Nodes"), None, tools, containers)
    conns = []
    for c in root.findall("Connections/Connection"):
        o, d = c.find("Origin"), c.find("Destination")
        conns.append({"from": o.get("ToolID"), "from_anchor": o.get("Connection"),
                      "to": d.get("ToolID"), "to_anchor": d.get("Connection"), "wireless": c.get("Wireless") == "True"})
    meta = root.find("Properties/MetaInfo")
    notes = [{"tool_id": t["tool_id"], "text": t["config"].get("text", "")} for t in tools if t["type"] == "TextBox" and t["config"].get("text")]
    return {
        "file": name,
        "alteryx_version": root.get("yxmdVer"),
        "workflow_name": text(meta.find("Name")) if meta is not None else "",
        "workflow_description": text(meta.find("Description")) if meta is not None else "",
        "author": text(meta.find("Author")) if meta is not None else "",
        "containers": containers,
        "notes": notes,
        "tools": tools,
        "connections": conns,
    }


# ----------------------------------------------------------------------------- classification

def load_mapping(path: Path | None = None) -> dict:
    mapping_path = Path(path) if path else MAPPING_PATH
    if not mapping_path.exists():
        raise SystemExit(f"Tool mapping not found at {mapping_path}; the solution package is incomplete.")
    return json.loads(mapping_path.read_text())


def classify_tools(inv: dict, mapping: dict) -> None:
    """Attach savant target + mapping quality to each tool."""
    for t in inv["tools"]:
        if t["type"] == "Macro":
            key = Path(t["macro"] or "").name.lower()
            m = None
            for pattern, spec in mapping.get("macros", {}).items():
                if re.search(pattern, key, re.I):
                    m = spec
                    break
            if m is None:
                m = {"savant": "inline macro tools as steps (custom macro)", "mapping": "custom_macro"}
            t["savant"] = m["savant"]
            t["mapping"] = m["mapping"]
            t["macro_kind"] = m.get("kind", "custom")
            if m.get("p1"):
                t["p1"] = m["p1"]
            if t["macro_kind"] == "output":
                # Output macros (Tableau, Power BI, Salesforce...) carry server credentials in
                # generically named slots ("Text Box (14)") that a key-name filter cannot see.
                # Keep only what cannot be a secret: URLs and enumerated controls (drop downs,
                # check boxes, list boxes). Free-text slots are dropped; the destination name
                # comes from the annotation.
                kept, dropped = {}, 0
                for k, v in t["config"].get("parameters", {}).items():
                    if re.match(r"https?://", v or "", re.I) or re.match(r"(Drop Down|Check Box|List Box|Radio)", k or "", re.I):
                        kept[k] = v
                    else:
                        dropped += 1
                t["config"]["parameters"] = kept
                t["config"]["parameters_redacted"] = f"output macro: {dropped} free-text parameter(s) dropped (may carry credentials); URLs and drop-down choices kept"
        else:
            m = mapping.get("tools", {}).get(t["type"], mapping.get("default"))
            t["savant"] = m["savant"]
            t["mapping"] = m["mapping"]
            if m.get("p1"):
                t["p1"] = m["p1"]
            if m.get("trap"):
                t["trap_hint"] = m["trap"]


# ----------------------------------------------------------------------------- checkpoints

ROW_CHANGING = {"Filter", "Join", "JoinMultiple", "Union", "Summarize", "Unique", "AppendFields",
                "CrossTab", "Transpose", "Sample", "RecordID", "DbFileOutput", "TextToColumns", "RegEx"}


def infer_grain(tool: dict, tools_by_id: dict, upstream_keys: list[str]) -> list[str]:
    cfg = tool["config"]
    if tool["type"] == "Unique":
        return cfg.get("fields", [])
    if tool["type"] == "Summarize":
        return cfg.get("group_by", [])
    if tool["type"] in {"Join", "JoinMultiple"}:
        # A join does not change the grain of the driving (left) stream when the right side is
        # unique on the keys; the upstream Unique/Summarize grain stays the checkpoint grain.
        return upstream_keys or cfg.get("left_keys") or cfg.get("keys") or []
    return upstream_keys


def build_checkpoints(inv: dict) -> list[dict]:
    by_id = {t["tool_id"]: t for t in inv["tools"]}
    incoming: dict[str, list] = {}
    for c in inv["connections"]:
        incoming.setdefault(c["to"], []).append(c)
    checkpoints = []
    # propagate grain keys along the graph (simple: last Unique/Summarize/Join keys seen upstream)
    memo: dict[str, list[str]] = {}

    def grain_for(tid: str, depth=0) -> list[str]:
        if tid in memo or depth > 60:
            return memo.get(tid, [])
        t = by_id.get(tid)
        if t is None:
            return []
        ins = incoming.get(tid, [])
        if t["type"] in {"Join", "JoinMultiple"}:
            ins = [c for c in ins if c.get("to_anchor") == "Left"] + [c for c in ins if c.get("to_anchor") != "Left"]
        ups = [c["from"] for c in ins]
        up_keys: list[str] = []
        for u in ups:
            k = grain_for(u, depth + 1)
            if k:
                up_keys = k
                break
        memo[tid] = infer_grain(t, by_id, up_keys)
        return memo[tid]

    n = 0
    for t in inv["tools"]:
        if t["type"] in ROW_CHANGING or (t["type"] == "Macro" and t.get("macro_kind") == "output"):
            n += 1
            outs = sorted({c["from_anchor"] for c in inv["connections"] if c["from"] == t["tool_id"]}) or ["Output"]
            rel = {
                "Filter": "true + false = input rows",
                "Union": "sum of input rows",
                "Unique": "<= input rows; delta = duplicates",
                "Summarize": "one row per distinct group tuple",
                "Join": "J + L + R covers both inputs; J <= min(L,R) unless keys duplicate",
                "AppendFields": "left rows x right rows",
            }.get(t["type"], "compare row count and measure sums")
            checkpoints.append({
                "id": f"A{n}", "tool_id": t["tool_id"], "tool_type": t["type"],
                "anchors": outs, "grain_keys": grain_for(t["tool_id"]),
                "expected_relationship": rel,
                "is_output": t["type"] == "DbFileOutput" or t.get("macro_kind") == "output",
                "priority": 1 if (t["type"] == "DbFileOutput" or t.get("macro_kind") == "output") else (2 if t["type"] in {"Union", "Unique", "Summarize", "CrossTab", "Transpose"} else 3),
                "savant_step": "",  # filled by the migration author after the build
            })
    return checkpoints


# ----------------------------------------------------------------------------- traps and dead code

RUN_DATE_RE = re.compile(r"\b(DateTimeToday|DateTimeNow|DateTimeNowPrecise|Today|Now)\s*\(", re.I)
STRING_TYPES = {"string", "wstring", "v_string", "v_wstring"}
ID_LIKE_RE = re.compile(r"(^|_)(id|ids|code|codes|zip|postcode|postal|account|acct|sku|no|num|number|ref)($|_)", re.I)


def _ancestors(inv: dict) -> dict[str, set[str]]:
    incoming: dict[str, list[str]] = {}
    for c in inv["connections"]:
        incoming.setdefault(c["to"], []).append(c["from"])
    memo: dict[str, set[str]] = {}

    def anc(tid: str, depth=0) -> set[str]:
        if tid in memo or depth > 60:
            return memo.get(tid, set())
        acc: set[str] = set()
        for u in incoming.get(tid, []):
            acc.add(u)
            acc |= anc(u, depth + 1)
        memo[tid] = acc
        return acc

    for t in inv["tools"]:
        anc(t["tool_id"])
    return memo


def cleanse_options(params: dict) -> dict:
    """Decode the standard Cleanse macro's control ids (see references/macro-handling.md)."""
    on = lambda k: (params.get(k) or "").strip().lower() == "true"  # noqa: E731
    fields = [f.strip().strip('"') for f in (params.get("List Box (11)") or "").split(",") if f.strip()]
    return {"fields": fields, "null_to_blank": on("Check Box (84)"), "null_to_zero": on("Check Box (117)"),
            "trim": on("Check Box (15)"), "case_change": on("Check Box (77)"),
            "case": (params.get("Drop Down (81)") or "").strip() if on("Check Box (77)") else ""}


def detect_traps(inv: dict) -> list[dict]:
    traps = []
    by_id = {t["tool_id"]: t for t in inv["tools"]}
    ancestors = _ancestors(inv)
    for t in inv["tools"]:
        cfg = t["config"]
        expr_text = " ".join(f.get("expression") or "" for f in cfg.get("fields", []) if isinstance(f, dict)) + " " + (cfg.get("expression") or "")
        if t["type"] in {"Formula", "MultiRowFormula", "Filter"} and RUN_DATE_RE.search(expr_text):
            traps.append({"trap": "run_date_dependency", "tool_id": t["tool_id"],
                          "detail": "Expression uses the run date (DateTimeToday/Now): results differ by run day. Pin the as-of date to the Alteryx baseline run date for the comparison, and make it a parameter or a documented constant in Savant"})
        if t["type"] == "AlteryxSelect":
            forced = {f: ty for f, ty in cfg.get("retyped", {}).items() if (ty or "").split("(")[0].lower() in STRING_TYPES}
            if forced:
                traps.append({"trap": "text_type_forced", "tool_id": t["tool_id"],
                              "detail": f"Select forces {sorted(forced)} to text; keep them text in the Savant dataset — type inference would strip leading zeros (00042 → 42) before any step runs"})
        if t["type"] == "DbFileInput":
            idish = [f for f, ty in cfg.get("field_types", {}).items() if (ty or "").lower() in STRING_TYPES and ID_LIKE_RE.search(f or "")]
            if idish:
                traps.append({"trap": "id_like_text_fields", "tool_id": t["tool_id"],
                              "detail": f"Input reads {idish} as text; confirm the Savant dataset keeps them text (leading zeros, mixed codes)"})
        if t["type"] in {"Formula", "MultiRowFormula"}:
            for f in cfg.get("fields", []):
                if (f.get("type") or "").lower() in {"int16", "int32", "int64", "byte"} and f.get("expression"):
                    if re.search(r"[\w\]]\s*[-+*/]|Row-|Row\+|\.\d", f["expression"]):
                        traps.append({"trap": "integer_cast_truncation", "tool_id": t["tool_id"],
                                      "detail": f"{f['field']} typed {f['type']} from expression `{f['expression'][:80]}`; decimals truncated in Alteryx"})
                literals = re.findall(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", f.get("expression") or "")
                if any("\n" in lit for lit in literals):
                    traps.append({"trap": "literal_with_line_break", "tool_id": t["tool_id"],
                                  "detail": f"{f['field']}: a string literal contains a line break; likely never matches after trimming"})
            if t["type"] == "MultiRowFormula":
                mr = cfg["fields"][-1] if cfg.get("fields") else {}
                traps.append({"trap": "multi_row_first_row_behaviour", "tool_id": t["tool_id"],
                              "detail": f"Multi-Row Formula ({mr.get('field')}): first row of each group uses '{mr.get('other_rows') or 'null'}' for missing rows; Savant LAG returns blank"})
        if t["type"] == "Filter" and cfg.get("operator") in {"!=", "<>"}:
            blanked = [a for a in ancestors.get(t["tool_id"], set())
                       if by_id.get(a, {}).get("type") == "Macro" and "cleanse" in (by_id[a].get("macro") or "").lower()
                       and cleanse_options(by_id[a]["config"].get("parameters", {}))["null_to_blank"]
                       and (cfg.get("field") in cleanse_options(by_id[a]["config"].get("parameters", {}))["fields"]
                            or not cleanse_options(by_id[a]["config"].get("parameters", {}))["fields"])]
            if blanked:
                detail = (f"Filter `{cfg.get('field')} {cfg.get('operator')} {cfg.get('operand')}`: NULL {cfg.get('field')} was already turned "
                          f"into blank by Cleanse {', '.join(sorted(blanked))} upstream, so those rows are kept; keep the same order in Savant")
            else:
                detail = f"Filter `{cfg.get('field')} {cfg.get('operator')} {cfg.get('operand')}`: Alteryx drops NULL rows; verify Savant treats NULL the same"
            traps.append({"trap": "not_equal_with_null", "tool_id": t["tool_id"], "detail": detail})
        if t["type"] == "Summarize" and any(a["action"] in {"First", "Last"} for a in cfg.get("aggs", [])):
            traps.append({"trap": "first_last_depends_on_sort", "tool_id": t["tool_id"],
                          "detail": "Summarize First/Last depends on upstream Sort order; use a deterministic rank in Savant"})
        if t["type"] == "Union" and (cfg.get("mode") or "").lower().startswith("bypos"):
            traps.append({"trap": "union_by_position", "tool_id": t["tool_id"], "detail": "Union by position; Savant Stack should match by name"})
        if t["type"] == "Macro" and "cleanse" in (t.get("macro") or "").lower():
            o = cleanse_options(cfg.get("parameters", {}))
            onoff = lambda b: "on" if b else "off"  # noqa: E731
            traps.append({"trap": "cleanse_macro_defaults", "tool_id": t["tool_id"],
                          "detail": (f"Cleanse on {o['fields'] or 'all fields'}: null→blank {onoff(o['null_to_blank'])}, null→0 {onoff(o['null_to_zero'])}"
                                     f" (inert on text), trim {onoff(o['trim'])}, case change {o['case'] or 'off'}; "
                                     "reproduce exactly these on exactly these fields, and check other branches are cleaned the same way")})
            cfg["cleanse_options"] = o
        if t["type"] in {"Join", "JoinMultiple", "Unique", "Summarize"}:
            keys = cfg.get("left_keys") or cfg.get("keys") or cfg.get("fields") or cfg.get("group_by") or []
            if keys:
                traps.append({"trap": "blank_keys", "tool_id": t["tool_id"],
                              "detail": f"{t['type']} on {keys}: Alteryx treats blank keys as equal; a Savant Blend/Summarize on a NULL key drops or splits the group — build blank-safe keys (COALESCE(TO_TEXT(x), \"\")) first"})
        if t["type"] in {"Join", "JoinMultiple"}:
            traps.append({"trap": "join_key_types_and_case", "tool_id": t["tool_id"],
                          "detail": f"Join on {cfg.get('left_keys') or cfg.get('keys')}: Alteryx string joins are case-sensitive and do not trim; confirm key normalisation"})
        if t["type"] == "Unique":
            used = {c["from_anchor"] for c in inv["connections"] if c["from"] == t["tool_id"]}
            if "Duplicates" in used:
                traps.append({"trap": "unique_duplicates_anchor", "tool_id": t["tool_id"],
                              "detail": f"Unique 'Duplicates' output is used: Alteryx emits only the 2nd+ occurrence of each key {cfg.get('fields')}; Savant's duplicate flag marks every member of the group — decide which the business wants"})
        if t["type"] == "DbFileInput" and t["config"].get("code_page") not in (None, "", "65001"):
            traps.append({"trap": "file_encoding", "tool_id": t["tool_id"],
                          "detail": f"Input code page {t['config']['code_page']} (not UTF-8); set the Savant dataset charset to match or accented characters are mangled"})
        if t["type"] == "DbFileInput" and t["config"].get("header_row") == "False":
            traps.append({"trap": "headerless_input", "tool_id": t["tool_id"],
                          "detail": "Input has no header row; fields are positional (Field_1…). Savant dataset needs a header or an explicit column map; confirm column meanings with the owner"})
        if t["type"] == "AppendFields":
            traps.append({"trap": "cartesian_append", "tool_id": t["tool_id"], "detail": "Append Fields is a cartesian product; replicate with a constant-key join or window aggregate"})
        if t["type"] == "Formula":
            for f in cfg.get("fields", []):
                if f.get("type") == "FixedDecimal":
                    traps.append({"trap": "fixed_decimal_precision", "tool_id": t["tool_id"],
                                  "detail": f"{f['field']} FixedDecimal {f.get('size')}: Alteryx rounds to declared scale"})
                    break
    return traps


def detect_dead_code(inv: dict) -> list[dict]:
    findings = []
    outgoing: dict[tuple, int] = {}
    incoming_count: dict[str, int] = {}
    for c in inv["connections"]:
        outgoing[(c["from"], c["from_anchor"])] = outgoing.get((c["from"], c["from_anchor"]), 0) + 1
        incoming_count[c["to"]] = incoming_count.get(c["to"], 0) + 1
    by_id = {t["tool_id"]: t for t in inv["tools"]}
    for t in inv["tools"]:
        if t["type"] in {"TextBox", "ToolContainer", "BrowseV2", "Browse"} or t.get("mapping") == "not_applicable":
            continue
        outs = [k for k in outgoing if k[0] == t["tool_id"]]
        if not outs and t["type"] not in {"DbFileOutput"} and t.get("mapping") != "output" and t.get("macro_kind") != "output":
            findings.append({"finding": "unused_tool", "tool_id": t["tool_id"], "detail": f"{t['type']} has no downstream connection"})
        if t["type"] in {"Join", "JoinMultiple"}:
            for anchor in ("Left", "Right"):
                if (t["tool_id"], anchor) not in outgoing:
                    findings.append({"finding": "unused_join_anchor", "tool_id": t["tool_id"], "detail": f"Join {anchor} output not used (unmatched rows dropped)"})
        if t["type"] == "AlteryxSelect" and not t["config"].get("deselected") and not t["config"].get("renamed") and not t["config"].get("retyped"):
            findings.append({"finding": "no_op_select", "tool_id": t["tool_id"], "detail": "Select tool changes nothing"})
        if t["type"] == "ToolContainer" and t.get("disabled"):
            findings.append({"finding": "disabled_container", "tool_id": t["tool_id"], "detail": f"Container '{t.get('caption')}' is disabled; contents do not run"})
    # duplicated filter/formula chains: same config on two tools
    seen: dict[str, str] = {}
    for t in inv["tools"]:
        if t["type"] in {"Filter", "Formula"}:
            sig = t["type"] + json.dumps(t["config"], sort_keys=True)
            if sig in seen:
                findings.append({"finding": "duplicated_logic", "tool_id": t["tool_id"],
                                 "detail": f"Same {t['type']} configuration as tool {seen[sig]} — do once upstream"})
            else:
                seen[sig] = t["tool_id"]
    # multiple inputs hitting the same connection/table
    inputs = [t for t in inv["tools"] if t["type"] == "DbFileInput"]
    for i, a in enumerate(inputs):
        for b in inputs[i + 1:]:
            ta, tb = set(a["config"].get("tables", [])), set(b["config"].get("tables", []))
            if ta and (ta <= tb or tb <= ta):
                findings.append({"finding": "overlapping_inputs", "tool_id": b["tool_id"],
                                 "detail": f"Input {b['tool_id']} reads a subset/superset of input {a['tool_id']} ({', '.join(sorted(ta & tb))}); consider a single input"})
    return findings


# ----------------------------------------------------------------------------- dataset configuration

# Alteryx code page -> Savant file-parser charset (the API enum has exactly UTF_8 and WINDOWS_1252).
CODE_PAGE_TO_CHARSET = {
    "65001": ("UTF_8", ""),
    "1252": ("WINDOWS_1252", ""),
    "28591": ("WINDOWS_1252", "Alteryx code page 28591 is ISO-8859-1; Savant has no Latin-1 option. WINDOWS_1252 decodes every printable Latin-1 byte identically (only the unused 0x80–0x9F control range differs)."),
    "28605": ("WINDOWS_1252", "Alteryx code page 28605 is ISO-8859-15; WINDOWS_1252 matches except for the euro sign and seven rare glyphs — check accented output."),
    "": ("UTF_8", "No code page in the Input tool (Designer default); confirm the file is UTF-8 — if accents break, use WINDOWS_1252."),
}


def dataset_configs(inv: dict) -> list[dict]:
    """One suggested Savant dataset configuration per Input tool: charset, delimiter and the
    columns that must stay text (from downstream Select retypes and id-like string fields)."""
    ancestors = _ancestors(inv)
    out = []
    for t in inv["tools"]:
        if t["type"] != "DbFileInput":
            continue
        cfg = t["config"]
        code_page = str(cfg.get("code_page") or "")
        charset, note = CODE_PAGE_TO_CHARSET.get(code_page, (None, f"Alteryx code page {code_page} has no Savant charset (UTF_8 / WINDOWS_1252); convert the file to UTF-8 before upload."))
        text_columns: dict[str, str] = {}
        for f, ty in cfg.get("field_types", {}).items():
            if (ty or "").lower() in STRING_TYPES and ID_LIKE_RE.search(f or ""):
                text_columns[f] = "input reads it as text"
        for s in inv["tools"]:
            if s["type"] == "AlteryxSelect" and t["tool_id"] in ancestors.get(s["tool_id"], set()):
                for f, ty in s["config"].get("retyped", {}).items():
                    if (ty or "").split("(")[0].lower() in STRING_TYPES:
                        text_columns[f] = f"Select {s['tool_id']} forces {ty}"
        delimiter = cfg.get("delimiter") or ","
        stem = Path((cfg.get("connection") or "").replace("\\", "/")).name or f"input_{t['tool_id']}"
        entry = {
            "tool_id": t["tool_id"], "source": cfg.get("connection", ""), "code_page": code_page,
            "charset": charset, "charset_note": note, "delimiter": delimiter,
            "text_columns": text_columns, "p1": charset is None,
        }
        if charset:
            cmd = f"savant.py dataset create --file <path to {stem}> --name \"{Path(stem).stem}\" --delimiter '{delimiter}' --charset {charset}"
            if text_columns:
                cmd += " --column-type " + ",".join(f"{c}=string" for c in text_columns)
            entry["suggested_command"] = cmd
        else:
            t["p1"] = (t.get("p1", "") + "; " if t.get("p1") else "") + f"file code page {code_page} is not supported by the Savant file parser — convert to UTF-8 first"
        out.append(entry)
    return out


# ----------------------------------------------------------------------------- dependencies and coverage

def dependencies(inv: dict) -> list[dict]:
    deps = []
    for t in inv["tools"]:
        c = t["config"]
        if t["type"] == "DbFileInput":
            deps.append({"kind": "input", "tool_id": t["tool_id"], "target": c.get("connection", ""), "tables": c.get("tables", [])})
        elif t["type"] == "DbFileOutput":
            deps.append({"kind": "output", "tool_id": t["tool_id"], "target": c.get("file", "")})
        elif t["type"] == "Macro":
            deps.append({"kind": "macro", "tool_id": t["tool_id"], "target": t.get("macro"), "macro_kind": t.get("macro_kind"),
                         "parameters": {k: v for k, v in c.get("parameters", {}).items() if v and not re.search("password|token|secret", k or "", re.I)}})
        elif t["type"] in {"RunCommand", "DownloadData", "PythonTool", "RTool", "Email"}:
            deps.append({"kind": "external", "tool_id": t["tool_id"], "target": t["type"]})
    return deps


def coverage(inv: dict) -> dict:
    counts = {"exact": 0, "equivalent": 0, "approximated": 0, "unsupported": 0, "custom_macro": 0, "not_applicable": 0, "review": 0}
    unsupported_by: dict[str, list] = {}
    approximated_by: dict[str, list] = {}
    for t in inv["tools"]:
        m = t.get("mapping", "review")
        counts[m] = counts.get(m, 0) + 1
        label = t['type'] if t['type'] != 'Macro' else Path((t['macro'] or '').replace('\\', '/')).stem
        if m == "unsupported":
            unsupported_by.setdefault(label, []).append(t['tool_id'])
        if m == "approximated":
            approximated_by.setdefault(label, []).append(t['tool_id'])
    fmt = lambda d: [f"{k} (tool{'s' if len(v) > 1 else ''} {', '.join(v)})" for k, v in d.items()]
    unsupported, approximated = fmt(unsupported_by), fmt(approximated_by)
    working = len(inv["tools"]) - counts.get("not_applicable", 0)
    headline = (f"{counts['exact'] + counts['equivalent']} mapped · {counts['approximated']} approximated · "
                f"{counts['unsupported']} unsupported" + (f" — {'; '.join(unsupported)}" if unsupported else "") +
                (f" · {counts['custom_macro']} custom macro(s) to inline" if counts['custom_macro'] else ""))
    return {"total_tools": len(inv["tools"]), "working_tools": working, "counts": counts,
            "unsupported": unsupported, "approximated": approximated, "headline": headline}


# ----------------------------------------------------------------------------- markdown

def to_markdown(result: dict) -> str:
    inv = result["workflows"][0]
    lines = [f"# Alteryx inventory — {inv['file']}", "",
             f"**Coverage:** {result['coverage']['headline']}", ""]
    lines += ["## Tools", "", "| ID | Type | Container | Annotation / summary | Savant | Mapping |", "|---|---|---|---|---|---|"]
    for t in inv["tools"]:
        summ = t["config"].get("text") if t["type"] == "TextBox" else (t["annotation"] or t["default_annotation"] or json.dumps(t["config"])[:80])
        lines.append(f"| {t['tool_id']} | {t['type'] if t['type'] != 'Macro' else 'Macro: ' + Path(t['macro'] or '').name} | {inv['containers'].get(t['container'], '') if t['container'] else ''} | {summ.replace('|', '/')[:90]} | {t.get('savant', '')} | {t.get('mapping', '')} |")
    if inv.get("notes"):
        lines += ["", "## Workflow notes (Text Box tools)", ""] + [f"- (tool {n['tool_id']}) {n['text'].replace(chr(10), ' ')[:300]}" for n in inv["notes"]]
    if result.get("dataset_configs"):
        lines += ["", "## Dataset configuration (P1 until done)", "", "| Input tool | Source | Charset | Delimiter | Keep as text | Create command |", "|---|---|---|---|---|---|"]
        for d in result["dataset_configs"]:
            lines.append(f"| {d['tool_id']} | {d['source'].replace('|', '/')[:60]} | {d['charset'] or 'unsupported: code page ' + d['code_page']} | `{d['delimiter']}` | {', '.join(d['text_columns']) or '—'} | `{d.get('suggested_command', 'convert the file to UTF-8 first')}` |")
        notes = [d["charset_note"] for d in result["dataset_configs"] if d["charset_note"]]
        if notes:
            lines += [""] + [f"- {n}" for n in dict.fromkeys(notes)]
    lines += ["", "## Validation checkpoints", "", "| # | Tool | Type | Grain keys | Expected |", "|---|---|---|---|---|"]
    for c in result["checkpoints"]:
        lines.append(f"| {c['id']} | {c['tool_id']} | {c['tool_type']} | {', '.join(c['grain_keys'])} | {c['expected_relationship']} |")
    lines += ["", "## Traps found", ""] + [f"- **{x['trap']}** (tool {x['tool_id']}): {x['detail']}" for x in result["traps"]]
    lines += ["", "## Dead code / inconsistencies", ""] + [f"- **{x['finding']}** (tool {x['tool_id']}): {x['detail']}" for x in result["dead_code"]]
    lines += ["", "## External dependencies", ""] + [f"- {d['kind']} (tool {d['tool_id']}): {d['target']} {d.get('tables', '') or ''}" for d in result["dependencies"]]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- main

def parse_package(path: Path, mapping: dict) -> dict:
    """Parse one Alteryx package into the inventory result (pure; no file writes)."""
    docs = load_package(path)
    workflows = []
    for name, root in docs.items():
        inv = parse_workflow(root, name)
        classify_tools(inv, mapping)
        workflows.append(inv)
    primary = workflows[0]
    return {
        "source_path": str(path),
        "package_members": list(docs.keys()),
        "workflows": workflows,
        "checkpoints": build_checkpoints(primary),
        "dataset_configs": dataset_configs(primary),
        "traps": detect_traps(primary),
        "dead_code": detect_dead_code(primary),
        "dependencies": dependencies(primary),
        "coverage": coverage(primary),
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="savant.py alteryx parse", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="Alteryx .yxmd / .yxwz / .yxmc / .yxzp file")
    ap.add_argument("--out", default=None, help="inventory JSON path (default: session tmp alteryx/<stem>.inventory.json)")
    ap.add_argument("--markdown", default=None, help="also write a human-readable inventory .md")
    ap.add_argument("--mapping", default=None, help="override the tool-mapping.json path")
    args = ap.parse_args()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"Alteryx file not found: {path}")
    mapping = load_mapping(args.mapping)
    result = parse_package(path, mapping)
    out = Path(args.out) if args.out else workspace_tmp("alteryx", f"{path.stem}.inventory.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out}")
    if args.markdown:
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(to_markdown(result))
        print(f"Wrote {args.markdown}")
    print(result["coverage"]["headline"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
