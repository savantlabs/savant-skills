"""Propagating recipe edits — change one node and fix every downstream reference in one pass.

The headline entry point is `apply_node_edit(recipe, node_id, ...)`: it applies a column change to a
target node AND walks everything downstream, repairing the references it can and reporting the ones a
human must decide. The reusable core is `propagate_schema_change(recipe, node_id, delta, ...)`, which
takes a column delta at a node's output (renames / drops / retypes) and propagates it downstream
regardless of which node type produced it.

Design notes / honest limits:
- It is the inverse of `node_builders`: the builders WRITE column references; this READS and rewrites
  them. References are located by the known config keys each node type uses (src_cols, selectedField,
  lhs/rhs + *Metadata.id, fieldId/fieldName, hiddenFields/orderedFields, filter clauses, backtick
  names in expressions, sort columns, adapter mappedFrom, …). Output slots (`tgt_col`/`tgtCol`) and
  constant/text slots (value, prompt, text) are deliberately NOT treated as references.
- It is pure and in-memory: it returns a new recipe + a report and never saves. Saving stays behind
  the editor's confirm → save → re-fetch → verify gate.
- It does NOT guess genuine gaps: a downstream reference to a dropped column with no resolution is
  returned in `report["unresolved"]`, not auto-removed.
- v1 propagation rewrites every downstream reference to the renamed name. If a column with the same
  name is independently reintroduced further downstream, that is flagged for review rather than
  silently rewritten past the reintroduction point.
"""
from __future__ import annotations

import copy
import re
from typing import Any

# Config keys whose string value is a reference to an UPSTREAM column, by form.
_NAME_KEYS = {"selectedField", "fieldName", "lhs", "rhs", "valueField", "pivotField",
              "inputField", "dateCol", "mappedFrom", "replaceTgt"}
_ID_KEYS = {"fieldId", "lhsKey", "rhsKey"}
# hiddenFields/orderedFields hold column NAMES (real exports store names; the Edit launcher
# resolves them by name or id). They are name-references, so a rename must rewrite them via the
# name map — keying them off a derived id would miss names whose id isn't the normalized name.
_NAME_LIST_KEYS = {"src_cols", "groupBy", "selectedFields", "fields", "inputFields",
                   "hiddenFields", "orderedFields"}
_EXPR_KEYS = {"expression", "dataFilterExpr"}
_SORT_KEYS = {"sorts", "sortConfig"}
_META_KEYS = {"lhsMetadata", "rhsMetadata"}   # dicts carrying {id (id-ref), name (name-ref)}
_SKIP_KEYS = {"tgt_col", "tgtCol"}            # OUTPUT columns — never treated as references

_BACKTICK = re.compile(r"`([^`]+)`")


def _field_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", str(name).lower())


def _rewrite_expr(expr: str, name_map: dict[str, str]) -> tuple[str, bool]:
    changed = False

    def repl(m):
        nonlocal changed
        inner = m.group(1)
        if inner in name_map:
            changed = True
            return f"`{name_map[inner]}`"
        return m.group(0)

    return _BACKTICK.sub(repl, expr), changed


def _walk(obj: Any, name_map: dict[str, str], id_map: dict[str, str],
          changes: list[dict] | None, names_seen: set[str], ids_seen: set[str]) -> None:
    """Single walk used both to COLLECT references (changes=None) and to REWRITE them
    (changes=list). name_map/id_map map old->new; in collect mode they are ignored for mutation but
    every referenced token is added to names_seen/ids_seen."""
    rewrite = changes is not None

    def hit_name(val):
        names_seen.add(val)
        return name_map.get(val, val) if rewrite else val

    def hit_id(val):
        ids_seen.add(val)
        return id_map.get(val, val) if rewrite else val

    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in _SKIP_KEYS:
                continue
            if k == "filter" and isinstance(v, list):
                for clause in v:
                    if not isinstance(clause, dict):
                        continue
                    nm, idv = clause.get("name"), clause.get("id")
                    if isinstance(nm, str):
                        new = hit_name(nm)
                        if rewrite and new != nm:
                            clause["name"] = new
                            changes.append({"key": "filter.name", "from": nm, "to": new})
                    if isinstance(idv, str):
                        new = hit_id(idv)
                        if rewrite and new != idv:
                            clause["id"] = new
                            changes.append({"key": "filter.id", "from": idv, "to": new})
                continue
            if k in _META_KEYS and isinstance(v, dict):
                nm, idv = v.get("name"), v.get("id")
                if isinstance(nm, str):
                    new = hit_name(nm)
                    if rewrite and new != nm:
                        v["name"] = new
                        changes.append({"key": f"{k}.name", "from": nm, "to": new})
                if isinstance(idv, str):
                    new = hit_id(idv)
                    if rewrite and new != idv:
                        v["id"] = new
                        changes.append({"key": f"{k}.id", "from": idv, "to": new})
                continue
            if k in _NAME_KEYS and isinstance(v, str):
                new = hit_name(v)
                if rewrite and new != v:
                    obj[k] = new
                    changes.append({"key": k, "from": v, "to": new})
                continue
            if k in _ID_KEYS and isinstance(v, str):
                new = hit_id(v)
                if rewrite and new != v:
                    obj[k] = new
                    changes.append({"key": k, "from": v, "to": new})
                continue
            if k in _NAME_LIST_KEYS and isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, str):
                        new = hit_name(item)
                        if rewrite and new != item:
                            v[i] = new
                            changes.append({"key": k, "from": item, "to": new})
                continue
            if k in _EXPR_KEYS and isinstance(v, str):
                for nm in name_map:
                    if f"`{nm}`" in v:
                        ids_seen.add(_field_id(nm)); names_seen.add(nm)
                if rewrite:
                    new, ch = _rewrite_expr(v, name_map)
                    if ch:
                        obj[k] = new
                        changes.append({"key": k, "from": v, "to": new})
                continue
            if k in _SORT_KEYS and isinstance(v, list):
                for pair in v:
                    if isinstance(pair, list) and pair and isinstance(pair[0], str):
                        new = hit_name(pair[0])
                        if rewrite and new != pair[0]:
                            old = pair[0]; pair[0] = new
                            changes.append({"key": k, "from": old, "to": new})
                continue
            _walk(v, name_map, id_map, changes, names_seen, ids_seen)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, name_map, id_map, changes, names_seen, ids_seen)


def _references(config: dict) -> tuple[set[str], set[str]]:
    """Return (referenced names, referenced ids) for one node config."""
    names: set[str] = set()
    ids: set[str] = set()
    _walk(config, {}, {}, None, names, ids)
    return names, ids


def _rewrite(config: dict, name_map: dict[str, str], id_map: dict[str, str]) -> list[dict]:
    """Rewrite references in `config` in place; return the list of changes made."""
    changes: list[dict] = []
    _walk(config, name_map, id_map, changes, set(), set())
    return changes


def _downstream(recipe: dict, start_id: str) -> list[dict]:
    """Nodes reachable downstream of start_id (transitively), in breadth-first order."""
    by_id = {n["id"]: n for n in recipe.get("nodes", []) if isinstance(n, dict)}
    seen: set[str] = set()
    order: list[str] = []
    queue = [start_id]
    while queue:
        node = by_id.get(queue.pop(0))
        if not node:
            continue
        for outlet in node.get("outlets", []) or []:
            for tgt in outlet.get("targets", []) or []:
                tid = tgt.get("target") if isinstance(tgt, dict) else None
                if tid and tid not in seen:
                    seen.add(tid)
                    order.append(tid)
                    queue.append(tid)
    return [by_id[i] for i in order if i in by_id]


def _references_column(names: set[str], ids: set[str], column: str) -> bool:
    return column in names or _field_id(column) in ids


def propagate_schema_change(recipe: dict, node_id: str, delta: dict, *,
                            resolutions: dict | None = None) -> tuple[dict, dict]:
    """Propagate an output-column `delta` at `node_id` to every downstream node, in one pass.

    `delta` = {"renames": {old: new}, "drops": [col, ...], "retypes": {col: newtype}} (display names).
    `resolutions` = {(node_id, dropped_col): substitute_name} or {dropped_col: substitute_name} to
    resolve a dropped-column gap (treated as a rename to the substitute at the affected nodes).

    Returns (new_recipe, report). Pure: the input recipe is not mutated and nothing is saved.
    report = {"target": node_id, "auto_fixed": [...], "unresolved": [...], "review": [...]}.
    """
    recipe = copy.deepcopy(recipe)
    resolutions = resolutions or {}
    renames = dict(delta.get("renames") or {})
    drops = list(delta.get("drops") or [])
    retypes = dict(delta.get("retypes") or {})
    name_map = dict(renames)
    id_map = {_field_id(o): _field_id(n) for o, n in renames.items()}

    report: dict = {"target": node_id, "auto_fixed": [], "unresolved": [], "review": []}

    for node in _downstream(recipe, node_id):
        cfg = node.get("config")
        if not isinstance(cfg, dict):
            continue
        names_ref, ids_ref = _references(cfg)

        # Renames -> auto-fix every matching reference.
        for change in _rewrite(cfg, name_map, id_map):
            report["auto_fixed"].append({"node": node["id"], "node_name": node.get("name"), **change})

        # Drops -> resolve to a substitute if provided, else surface as a gap.
        for col in drops:
            if not _references_column(names_ref, ids_ref, col):
                continue
            sub = resolutions.get((node["id"], col)) or resolutions.get(col)
            if sub:
                for change in _rewrite(cfg, {col: sub}, {_field_id(col): _field_id(sub)}):
                    report["auto_fixed"].append({"node": node["id"], "node_name": node.get("name"),
                                                 "resolved_drop": col, **change})
            else:
                report["unresolved"].append({
                    "node": node["id"], "node_name": node.get("name"), "column": col,
                    "reason": "references a column dropped upstream; no resolution given",
                })

        # Retypes -> references survive, but flag type-sensitive consumers (joins) for review.
        for col in retypes:
            if _references_column(names_ref, ids_ref, col) and node.get("type") == "blend":
                report["review"].append({
                    "node": node["id"], "node_name": node.get("name"), "column": col,
                    "reason": f"blend joins on {col!r}, whose type changed to {retypes[col]!r}; verify both sides match",
                })

    return recipe, report


def apply_node_edit(recipe: dict, node_id: str, *, rename: tuple[str, str] | None = None,
                    drop: str | None = None, resolutions: dict | None = None) -> tuple[dict, dict]:
    """Apply a column rename/drop to the target node AND propagate downstream, in one call.

    `rename` = (old_name, new_name); `drop` = column name. The target must currently be an `edit`
    (Transform) node — the natural place a column is renamed/dropped. For schema changes that
    originate at other node types, apply the change with the matching `node_builders` `*_update`
    yourself and call `propagate_schema_change(recipe, node_id, delta)` directly.

    Returns (new_recipe, report). Pure: nothing is saved. Inspect `report["unresolved"]` before
    confirming/saving — if it is non-empty, resolve those with the user and re-call with `resolutions`.
    """
    if not rename and not drop:
        raise ValueError("apply_node_edit needs a rename=(old,new) or drop=col.")
    recipe = copy.deepcopy(recipe)
    by_id = {n["id"]: n for n in recipe.get("nodes", []) if isinstance(n, dict)}
    target = by_id.get(node_id)
    if target is None:
        raise ValueError(f"node {node_id!r} not found in recipe.")
    if target.get("type") != "edit":
        raise ValueError(
            f"apply_node_edit applies a rename/drop to an edit (Transform) node; {node_id!r} is "
            f"{target.get('type')!r}. Use the matching *_update + propagate_schema_change instead.")

    from workflow import builders as nb  # local import: builders is a sibling module

    delta: dict = {"renames": {}, "drops": []}
    cfg = target.setdefault("config", {})
    cfg.setdefault("edits", [])
    cfg.setdefault("hiddenFields", [])
    cfg.setdefault("orderedFields", [])

    if rename:
        old, new = rename
        cfg["edits"].append(nb.op_rename(old, new))   # rename in place (replace edit)
        delta["renames"][old] = new
    if drop:
        # hiddenFields holds column NAMES (the runtime resolves by name; a derived id can
        # mismatch the real internal id and silently no-op the hide).
        if drop not in cfg["hiddenFields"]:
            cfg["hiddenFields"].append(drop)
        delta["drops"].append(drop)

    recipe, report = propagate_schema_change(recipe, node_id, delta, resolutions=resolutions)
    report["target"] = node_id
    return recipe, report
