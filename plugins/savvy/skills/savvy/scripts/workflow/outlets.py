#!/usr/bin/env python3
"""Deterministic outlet re-wiring for Savant workflow node lists.

Mirrors the platform's multi-outlet expansion convention: a multi-output tool is drawn
on the Canvas as the parent node fanning its
single `out_0` to one synthetic `{parent}|i` outlet child per branch, each child carrying
that branch's real downstream targets; a single-output tool wires straight from the
parent with no outlet child.

  - blend  : children iff `useLeftUnmatch`/`useRightUnmatch` (matched `|0` + the enabled
             unmatched side(s) `|1`/`|2`); inner/no-split → no child, wire from the blend.
  - filter : children iff `useFalsePath` (`|0` True, `|1` False); else wire from the filter.
  - other  : any node declaring more than one output port (structural — any multi-output node).

This pass is the SINGLE owner of outlet-child structure. Builders no longer hand-author
outlet children — they set the parent's config flags and the branch edges, and this pass
synthesizes the children. It is source-agnostic (builder output, hand-authored JSON, or an
imported flow all converge on the same shape) and idempotent.

It works in two phases:

  1. COLLAPSE — fold any existing `{parent}|i` outlet children back onto the parent's
     embedded `out_i` ports, rewriting downstream consumer inlets, and drop spurious
     `|i -> |j` edges between siblings of the same parent.
  2. EXPAND — re-synthesize children uniformly from each node's branch intent (config flags
     for blend/filter; declared embedded-outlet count otherwise).

Net effect: spurious `|0` children on single-output tools disappear, `|i -> |j`
self-references disappear, and an enabled branch always gets exactly one well-formed child.

It deliberately does NOT drop an enabled-but-unconsumed branch (e.g. an anti-join's unused
matched output): that intent-level call belongs to the validator, not to a structural
rewrite that must never silently delete a data path.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# `{parent}|{index}` — the id form of an outlet *pseudo-node*. The parent segment is
# itself a normal node id (which never contains a `|`), so a greedy left match is safe.
OUTLET_NODE_ID_RE = re.compile(r"^(?P<parent>.+)\|(?P<idx>\d+)$")
_EMBEDDED_OUTLET_RE = re.compile(r"^out_(?P<idx>\d+)$")

# Canonical branch labels, kept identical to the builder's historical outlet names so the
# canvas readout is unchanged.
_BLEND_LABELS = {"matched": "Blended", "left_unmatched": "❌️ Left Unmatched",
                 "right_unmatched": "❌️ Right Unmatched"}
_FILTER_LABELS = {0: "True", 1: "False"}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _config(node: dict) -> dict:
    config = node.get("config")
    return config if isinstance(config, dict) else {}


def blend_branch_indices(config: dict) -> dict[str, int]:
    """Map a blend's enabled output branches to their outlet index.

    `{}` (single output) when neither unmatched flag is set — the matched rows then wire
    straight from the blend node. Otherwise `matched` is always `0`; the enabled unmatched
    side is `1` (or `1`/`2` for left/right when both are on). Authoritative source of truth
    shared with the builder.
    """
    left = bool(config.get("useLeftUnmatch"))
    right = bool(config.get("useRightUnmatch"))
    if not (left or right):
        return {}
    indices = {"matched": 0}
    if left:
        indices["left_unmatched"] = 1
    if right:
        indices["right_unmatched"] = 2 if left else 1
    return indices


def _expected_branch_labels(node: dict) -> dict[int, str] | None:
    """`{index: label}` for a flag-driven node's branches, `{}` for a flag-driven node that
    is single-output, or `None` when the node's branch structure is not flag-driven (the
    caller then falls back to the declared embedded-outlet count)."""
    node_type = node.get("type")
    config = _config(node)
    if node_type == "blend":
        indices = blend_branch_indices(config)
        return {idx: _BLEND_LABELS[kind] for kind, idx in indices.items()}
    if node_type in ("filter", "pdfilter"):
        return dict(_FILTER_LABELS) if config.get("useFalsePath") else {}
    return None


def _embedded_outlet(node: dict, idx: int) -> dict:
    """Return the node's embedded `out_{idx}` port, creating it if absent."""
    oid = f"out_{idx}"
    for outlet in _as_list(node.get("outlets")):
        if isinstance(outlet, dict) and outlet.get("id") == oid:
            outlet.setdefault("targets", [])
            return outlet
    new_outlet = {"id": oid, "targets": []}
    if not isinstance(node.get("outlets"), list):
        node["outlets"] = []
    node["outlets"].append(new_outlet)
    return new_outlet


def _rewrite_inlet_source(consumer: Any, old_source: str, new_source: str,
                          new_outlet: str, old_outlet: str | None = None) -> None:
    """Repoint a downstream consumer's inlet from `(old_source, old_outlet)` to
    `(new_source, new_outlet)`. Handles both the single `source`/`sourceOutlet` form and
    the `multisource` `sources[]` form."""
    if not isinstance(consumer, dict):
        return
    for inlet in _as_list(consumer.get("inlets")):
        if not isinstance(inlet, dict):
            continue
        if inlet.get("source") == old_source and (old_outlet is None or inlet.get("sourceOutlet") == old_outlet):
            inlet["source"] = new_source
            inlet["sourceOutlet"] = new_outlet
        for entry in _as_list(inlet.get("sources")):
            if isinstance(entry, dict) and entry.get("source") == old_source \
                    and (old_outlet is None or entry.get("sourceOutlet") == old_outlet):
                entry["source"] = new_source
                entry["sourceOutlet"] = new_outlet


def _rebuild_index(nodes: list) -> dict[str, dict]:
    return {n["id"]: n for n in nodes if isinstance(n, dict) and isinstance(n.get("id"), str)}


def _collapse(nodes: list, by_id: dict[str, dict], changes: list[str]) -> None:
    """Fold existing `{parent}|i` outlet children back onto parent embedded `out_i`."""
    collapsed: set[str] = set()
    for node in list(nodes):
        if not isinstance(node, dict) or node.get("type") != "outlet":
            continue
        match = OUTLET_NODE_ID_RE.match(str(node.get("id") or ""))
        if not match:
            continue
        parent_id = match.group("parent")
        idx = int(match.group("idx"))
        parent = by_id.get(parent_id)
        if parent is None or parent.get("type") == "outlet":
            continue

        parent_outlet = _embedded_outlet(parent, idx)
        for outlet in _as_list(node.get("outlets")):
            for target in _as_list(outlet.get("targets")):
                if not isinstance(target, dict):
                    continue
                target_id = str(target.get("target") or "")
                sibling = OUTLET_NODE_ID_RE.match(target_id)
                if sibling and sibling.group("parent") == parent_id:
                    # `|i -> |j` self-reference among siblings of the same parent: spurious.
                    changes.append(f"drop-outlet-self-edge:{node.get('id')}->{target_id}")
                    continue
                parent_outlet["targets"].append(target)
                _rewrite_inlet_source(by_id.get(target_id), node["id"], parent_id, f"out_{idx}")
        collapsed.add(node["id"])
        changes.append(f"collapse-outlet:{node['id']}")

    if not collapsed:
        return
    # Drop the parent->child fanout edges and the child nodes themselves.
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for outlet in _as_list(node.get("outlets")):
            outlet["targets"] = [
                t for t in _as_list(outlet.get("targets"))
                if not (isinstance(t, dict) and t.get("target") in collapsed)
            ]
    nodes[:] = [n for n in nodes if not (isinstance(n, dict) and n.get("id") in collapsed)]


def _expand(nodes: list, by_id: dict[str, dict], changes: list[str]) -> None:
    """Synthesize `{parent}|i` outlet children for every multi-output node from intent."""
    new_children: dict[str, list[dict]] = {}
    for node in list(nodes):
        if not isinstance(node, dict) or node.get("type") == "outlet":
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue

        expected = _expected_branch_labels(node)
        if expected is None:
            # Not flag-driven: expand only when the node declares >1 output port.
            present = sorted(
                int(m.group("idx"))
                for outlet in _as_list(node.get("outlets"))
                if isinstance(outlet, dict)
                for m in [_EMBEDDED_OUTLET_RE.match(str(outlet.get("id") or ""))]
                if m
            )
            if len(present) <= 1:
                continue
            labels = {idx: f"Output {idx + 1}" for idx in present}
        elif not expected:
            continue  # flag-driven single output → no children
        else:
            labels = expected

        embedded_targets: dict[int, list] = {}
        for outlet in _as_list(node.get("outlets")):
            if not isinstance(outlet, dict):
                continue
            m = _EMBEDDED_OUTLET_RE.match(str(outlet.get("id") or ""))
            if m:
                embedded_targets[int(m.group("idx"))] = _as_list(outlet.get("targets"))

        fanout: list[dict] = []
        children: list[dict] = []
        for idx in sorted(labels):
            child_id = f"{node_id}|{idx}"
            branch_targets = list(embedded_targets.get(idx, []))
            children.append({
                "id": child_id, "name": labels[idx], "type": "outlet",
                "config": {"outlet": f"out|{idx}"},
                "inlets": [{"id": "in_0", "source": node_id, "sourceOutlet": "out_0", "sources": []}],
                "outlets": [{"id": "out_0", "targets": branch_targets}],
            })
            fanout.append({"target": child_id, "targetInlet": "in_0"})
            for target in branch_targets:
                if isinstance(target, dict):
                    _rewrite_inlet_source(by_id.get(target.get("target")), node_id, child_id,
                                          "out_0", old_outlet=f"out_{idx}")

        node["outlets"] = [{"id": "out_0", "targets": fanout}]
        new_children[node_id] = children
        changes.append(f"expand-outlets:{node_id}:{','.join(str(i) for i in sorted(labels))}")

    if not new_children:
        return
    # Insert each parent's synthetic children immediately after it (preserve topo order).
    result: list = []
    for node in nodes:
        result.append(node)
        if isinstance(node, dict) and node.get("id") in new_children:
            result.extend(new_children[node["id"]])
            by_id.update({c["id"]: c for c in new_children[node["id"]]})
    nodes[:] = result


def normalize_outlets(nodes: list) -> list[str]:
    """Re-wire outlet pseudo-nodes to the canonical shape, in place. Returns a list of
    change descriptions (empty when the input was already canonical)."""
    if not isinstance(nodes, list):
        return []
    before = copy.deepcopy(nodes)
    changes: list[str] = []
    by_id = _rebuild_index(nodes)
    _collapse(nodes, by_id, changes)
    by_id = _rebuild_index(nodes)
    _expand(nodes, by_id, changes)
    # The collapse->expand round-trip emits change records even for an already-canonical
    # input; report changes only when the node list actually differs, so callers (polish's
    # change log) and idempotent re-runs see a true no-op.
    if nodes == before:
        return []
    return changes
