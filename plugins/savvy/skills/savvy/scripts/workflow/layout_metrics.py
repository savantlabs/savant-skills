"""Deterministic connector-path quality metrics for Savant workflow layouts.

This is the shared edge-path model used by auto-layout, polish, and the workflow
validator. It approximates each rendered connector as a sampled cubic bezier
between the real output/input port positions (the same port geometry the
renderer uses), then measures the defects that make a canvas hard to read:

- connectors passing through unrelated node bodies,
- connectors cutting through group frames they do not belong to,
- connector crossings,
- right-to-left (backward) connectors,
- overlapping node bodies and overlapping group frames.

`score(...)` folds those into a lexicographic tuple so callers can compare two
layouts of the same workflow deterministically ("is the re-layout better than
what the user already had?").

Everything here is pure geometry over the recipe JSON; no browser, no API.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from workflow.geometry import (
    NODE_HEIGHT,
    NODE_WIDTH,
    input_port_y_offset,
    output_port_y_offset,
)

# Sampled-bezier path model. The renderer draws horizontal-out / horizontal-in
# curves; 16 segments is enough to tell "passes through" from "passes near".
BEZIER_SEGMENTS = 16
BEZIER_CONTROL_MIN = 40.0
BEZIER_CONTROL_MAX = 256.0
# Connectors that travel further than this are reported (not scored) so callers
# can see which taps span multiple stages.
LONG_EDGE_DX = 900.0

Box = tuple[float, float, float, float]
Point = tuple[float, float]


def _parent_id(node: dict[str, Any]) -> str:
    config = node.get("canvasConfig")
    if not isinstance(config, dict):
        return ""
    value = config.get("parentId")
    return value if isinstance(value, str) else ""


def _nodes(recipe_or_nodes: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(recipe_or_nodes, dict):
        raw = recipe_or_nodes.get("nodes") or []
    else:
        raw = recipe_or_nodes
    return [node for node in raw if isinstance(node, dict) and isinstance(node.get("id"), str)]


def absolute_position(
    node: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    _seen: frozenset[str] = frozenset(),
) -> Point | None:
    pos = node.get("position")
    if not isinstance(pos, dict):
        return None
    x, y = pos.get("x"), pos.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    node_id = str(node.get("id") or "")
    parent = _parent_id(node)
    if parent and parent != node_id and parent in by_id and node_id not in _seen:
        parent_pos = absolute_position(by_id[parent], by_id, _seen | {node_id})
        if parent_pos is not None:
            return float(x) + parent_pos[0], float(y) + parent_pos[1]
    return float(x), float(y)


# Outlet pseudo-nodes render as small port circles, not full node cards. Modeling them at full
# NODE_WIDTH manufactured phantom defects: between two normal columns (~230px apart) a fake
# 130px-wide outlet cannot fit without its ports overlapping a neighbor, so the model reported
# backward edges the rendered canvas never shows (live: the blend echo outlets, 2026-06-10).
# Measured from the live canvas DOM (2026-06-10): outlet pseudo-nodes render 48x48 with
# their ports at the vertical center (+24). The old 28x28 model put every "aligned"
# outlet 10px off its true port line, bending arms that should have been straight.
OUTLET_WIDTH = 48.0
OUTLET_HEIGHT = 48.0
# Rendered node anatomy (also DOM-measured): the stored position is the top-left of a
# 96x96 BODY; the name label renders as a centered box under it, wrapping at ~200px.
BODY_W = 96.0
BODY_H = 96.0
LABEL_MAX_W = 200.0
LABEL_CHAR_W = 7.2
LABEL_LINE_H = 17.0


def label_extent(node: dict[str, Any]) -> tuple[float, float, float]:
    """(left overhang beyond stored x, right extent beyond stored x, band height below body).

    Labels are centered boxes wrapping at LABEL_MAX_W — under the 96px body for nodes,
    under the 48px circle for outlets (whose labels also carry a status icon)."""
    name = str(node.get("name") or "")
    is_outlet = node.get("type") == "outlet"
    full = max(len(name), 1) * LABEL_CHAR_W + (10.0 if is_outlet else 0.0)
    est = min(LABEL_MAX_W, full)
    # Width is capped, so long names WRAP and the label grows DOWNWARD: the band is as
    # many lines as the text needs (user rule, 2026-06-10 — a tall label must never eat
    # into the room padding below it).
    lines = max(1, -(-int(full) // int(LABEL_MAX_W)))
    half = est / 2.0
    center = (OUTLET_WIDTH if is_outlet else BODY_W) / 2.0
    return max(0.0, half - center), center + half, 6.0 + lines * LABEL_LINE_H


def _node_size(node: dict[str, Any]) -> tuple[float, float]:
    if node.get("type") == "outlet":
        return OUTLET_WIDTH, OUTLET_HEIGHT
    return float(NODE_WIDTH), float(NODE_HEIGHT)


def node_box(node: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> Box | None:
    pos = absolute_position(node, by_id)
    if pos is None:
        return None
    width, height = _node_size(node)
    return pos[0], pos[1], pos[0] + width, pos[1] + height


def group_frame(group: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> Box | None:
    pos = absolute_position(group, by_id)
    config = group.get("config") if isinstance(group.get("config"), dict) else {}
    width, height = config.get("width"), config.get("height")
    if pos is None or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    return pos[0], pos[1], pos[0] + float(width), pos[1] + float(height)


def iter_edges(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    by_id = {node["id"] for node in nodes}
    rows: list[tuple[str, str, str]] = []
    for src in nodes:
        for outlet in src.get("outlets") or []:
            if not isinstance(outlet, dict):
                continue
            for target in outlet.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                tid = target.get("target")
                if isinstance(tid, str) and tid in by_id:
                    rows.append((src["id"], tid, str(target.get("targetInlet") or "in_0")))
    return rows


def edge_ports(
    edge: tuple[str, str, str], by_id: dict[str, dict[str, Any]]
) -> tuple[Point, Point] | None:
    src_id, target_id, inlet = edge
    src, target = by_id.get(src_id), by_id.get(target_id)
    if not src or not target:
        return None
    src_pos = absolute_position(src, by_id)
    target_pos = absolute_position(target, by_id)
    if src_pos is None or target_pos is None:
        return None
    src_w, _src_h = _node_size(src)
    out_y = output_port_y_offset(src)
    if src.get("type") == "outlet":
        out_y = OUTLET_HEIGHT / 2
    in_y = input_port_y_offset(target, inlet, src_id)
    if target.get("type") == "outlet":
        in_y = OUTLET_HEIGHT / 2
    p1 = (src_pos[0] + src_w, src_pos[1] + out_y)
    p2 = (target_pos[0], target_pos[1] + in_y)
    return p1, p2


def edge_polyline(p1: Point, p2: Point, segments: int | None = None) -> list[Point]:
    """Sampled horizontal-out/horizontal-in cubic bezier between two ports.

    The sample count adapts to the connector's length: a short link between
    adjacent nodes is nearly straight and needs few segments, while a long tap
    across the canvas keeps the full resolution. This keeps `measure` fast on
    dense canvases without losing accuracy where the curve actually bends.
    """
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    if segments is None:
        span = abs(dx) + abs(dy)
        segments = max(4, min(BEZIER_SEGMENTS, int(span / 90)))
    if dx >= 0:
        offset = min(max(dx * 0.5, BEZIER_CONTROL_MIN), BEZIER_CONTROL_MAX)
    else:
        offset = min(max(abs(dx), 64.0), 2 * BEZIER_CONTROL_MAX)
    c1x = x1 + offset
    c2x = x2 - offset
    points: list[Point] = []
    for i in range(segments + 1):
        t = i / segments
        mt = 1.0 - t
        a = mt * mt * mt
        b = 3.0 * mt * mt * t
        c = 3.0 * mt * t * t
        d = t * t * t
        points.append((a * x1 + b * c1x + c * c2x + d * x2, (a + b) * y1 + (c + d) * y2))
    return points


def _segment_intersects_box(p1: Point, p2: Point, box: Box) -> bool:
    """Liang-Barsky segment/AABB intersection."""
    x1, y1 = p1
    x2, y2 = p2
    xmin, ymin, xmax, ymax = box
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - xmin), (dx, xmax - x1), (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t0 < t1


def _polyline_bbox(points: list[Point]) -> Box:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def polyline_intersects_box(points: list[Point], box: Box, bbox: Box | None = None) -> bool:
    x1, y1, x2, y2 = bbox if bbox is not None else _polyline_bbox(points)
    if x2 < box[0] or x1 > box[2] or y2 < box[1] or y1 > box[3]:
        return False
    return any(_segment_intersects_box(a, b, box) for a, b in zip(points, points[1:]))


def _segments_cross(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    def ccw(p: Point, q: Point, r: Point) -> float:
        return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = ccw(b1, b2, a1), ccw(b1, b2, a2)
    d3, d4 = ccw(a1, a2, b1), ccw(a1, a2, b2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def polylines_cross(
    a: list[Point],
    b: list[Point],
    a_bbox: Box | None = None,
    b_bbox: Box | None = None,
) -> bool:
    ax1, ay1, ax2, ay2 = a_bbox if a_bbox is not None else _polyline_bbox(a)
    bx1, by1, bx2, by2 = b_bbox if b_bbox is not None else _polyline_bbox(b)
    if ax2 < bx1 or ax1 > bx2 or ay2 < by1 or ay1 > by2:
        return False
    # Inlined orientation tests: this pairwise kernel dominates `measure` on
    # dense canvases, so it avoids per-segment function-call overhead and
    # screens each segment pair with a cheap interval check first.
    for i in range(len(a) - 1):
        p1x, p1y = a[i]
        p2x, p2y = a[i + 1]
        s_xlo, s_xhi = (p1x, p2x) if p1x <= p2x else (p2x, p1x)
        s_ylo, s_yhi = (p1y, p2y) if p1y <= p2y else (p2y, p1y)
        if s_xhi < bx1 or s_xlo > bx2 or s_yhi < by1 or s_ylo > by2:
            continue
        rx = p2x - p1x
        ry = p2y - p1y
        for j in range(len(b) - 1):
            q1x, q1y = b[j]
            q2x, q2y = b[j + 1]
            if (
                (q1x if q1x <= q2x else q2x) > s_xhi
                or (q1x if q1x >= q2x else q2x) < s_xlo
                or (q1y if q1y <= q2y else q2y) > s_yhi
                or (q1y if q1y >= q2y else q2y) < s_ylo
            ):
                continue
            sx = q2x - q1x
            sy = q2y - q1y
            d1 = sx * (p1y - q1y) - sy * (p1x - q1x)
            d2 = sx * (p2y - q1y) - sy * (p2x - q1x)
            if (d1 > 0) == (d2 > 0):
                continue
            d3 = rx * (q1y - p1y) - ry * (q1x - p1x)
            d4 = rx * (q2y - p1y) - ry * (q2x - p1x)
            if (d3 > 0) != (d4 > 0):
                return True
    return False


def _boxes_overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def feeder_groups(nodes: list[dict[str, Any]]) -> dict[str, set[str]]:
    """For each group id, the set of *other* parents (group ids or "") feeding it."""
    by_id = {node["id"]: node for node in nodes}
    feeders: dict[str, set[str]] = {
        node["id"]: set() for node in nodes if node.get("type") == "group"
    }
    for src_id, target_id, _inlet in iter_edges(nodes):
        src_parent = _parent_id(by_id[src_id])
        target_parent = _parent_id(by_id[target_id])
        if target_parent in feeders and src_parent != target_parent:
            feeders[target_parent].add(src_parent)
    return feeders


def terminal_destination_group_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """Groups that contain a destination and feed nothing outside themselves."""
    by_id = {node["id"]: node for node in nodes}
    destination_parents = {
        _parent_id(node) for node in nodes if node.get("type") == "destination" and _parent_id(node)
    }
    outgoing_parents: set[str] = set()
    for src_id, target_id, _inlet in iter_edges(nodes):
        src_parent = _parent_id(by_id[src_id])
        if src_parent and src_parent != _parent_id(by_id[target_id]):
            outgoing_parents.add(src_parent)
    return {gid for gid in destination_parents if gid not in outgoing_parents}


def side_band_group_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """Terminal destination groups fed only by taps from two or more stages.

    These are review/validation/QA stages that tap several points of the main
    flow (e.g. "compare source totals to produced totals"). Forcing them into
    the main top band drags long feeder connectors across every stage in
    between, so layout places them in a band *below* the main flow instead of
    to the right of the final processing stage.

    "Tap" is the discriminator: every external feeder must ALSO feed something
    outside this group. A feeder whose only consumer is this group makes the
    group the main continuation of that stream — a downstream stage, not a
    side band — no matter how many stages feed it.
    """
    by_id = {node["id"]: node for node in nodes}
    edges = iter_edges(nodes)
    targets_by_src: dict[str, list[str]] = {}
    for src_id, target_id, _inlet in edges:
        targets_by_src.setdefault(src_id, []).append(target_id)
    feeders = feeder_groups(nodes)
    candidates = {
        gid
        for gid in terminal_destination_group_ids(nodes)
        if len(feeders.get(gid) or set()) >= 2
    }
    side: set[str] = set()
    for gid in candidates:
        member_ids = {node["id"] for node in nodes if _parent_id(node) == gid}
        feeder_sources = {
            src_id
            for src_id, target_id, _inlet in edges
            if target_id in member_ids and src_id not in member_ids
        }
        if feeder_sources and all(
            any(target not in member_ids for target in targets_by_src.get(src_id, []))
            for src_id in feeder_sources
        ):
            side.add(gid)
    return side


def lookup_branch_group_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """Groups whose every cross-group outgoing edge feeds a lookup port (in_1+).

    These are enrichment/lookup streams (e.g. an AI sentiment branch feeding a
    join's right side). They belong below the main row: kept inline they occupy
    the corridor that other lanes need.
    """
    by_id = {node["id"]: node for node in nodes}
    out_by_group: dict[str, list[str]] = {}
    for src_id, target_id, inlet in iter_edges(nodes):
        src_parent = _parent_id(by_id[src_id])
        target_parent = _parent_id(by_id[target_id])
        if src_parent and src_parent != target_parent:
            out_by_group.setdefault(src_parent, []).append(str(inlet or "in_0"))
    return {
        gid
        for gid, inlets in out_by_group.items()
        if inlets and all(inlet not in {"", "in_0"} for inlet in inlets)
    }


def tap_fed_branch_group_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """Non-terminal groups fed ONLY by taps (feeders that also feed other groups).

    A summary/branch stage hanging off a tee in the main stream (its feeder also
    continues elsewhere) reads best below the main row; keeping it inline forces
    the main continuation's connector across this group's frame.
    """
    by_id = {node["id"]: node for node in nodes}
    edges = iter_edges(nodes)
    targets_by_src: dict[str, list[str]] = {}
    for src_id, target_id, _inlet in edges:
        targets_by_src.setdefault(src_id, []).append(target_id)
    feeders_by_group: dict[str, set[str]] = {}
    outgoing_groups: set[str] = set()
    for src_id, target_id, _inlet in edges:
        src_parent = _parent_id(by_id[src_id])
        target_parent = _parent_id(by_id[target_id])
        if target_parent and src_parent != target_parent:
            feeders_by_group.setdefault(target_parent, set()).add(src_id)
        if src_parent and src_parent != target_parent:
            outgoing_groups.add(src_parent)
    result: set[str] = set()
    for gid, feeder_ids in feeders_by_group.items():
        if gid not in outgoing_groups:
            continue  # terminal groups are handled by side_band_group_ids
        member_ids = {node["id"] for node in nodes if _parent_id(node) == gid}
        if feeder_ids and all(
            any(t not in member_ids for t in targets_by_src.get(src_id, []))
            for src_id in feeder_ids
        ):
            result.add(gid)
    return result


def below_band_group_ids(nodes: list[dict[str, Any]]) -> set[str]:
    """All groups that belong in the band below the main flow.

    Union of: multi-tap terminal review stages (`side_band_group_ids`), lookup
    branches (`lookup_branch_group_ids`), and tap-fed branch stages
    (`tap_fed_branch_group_ids`). Pure source groups never qualify.
    """
    by_id = {node["id"]: node for node in nodes}
    sources_only = set()
    for node in nodes:
        if node.get("type") != "group":
            continue
        members = [n for n in nodes if _parent_id(n) == node["id"] and n.get("type") not in {"group", "text", "outlet"}]
        if members and all(n.get("type") == "source" for n in members):
            sources_only.add(node["id"])
    bands = (
        side_band_group_ids(nodes)
        | lookup_branch_group_ids(nodes)
        | tap_fed_branch_group_ids(nodes)
    )
    return {gid for gid in bands if gid in by_id and gid not in sources_only}


def vertical_band_clusters(bounds_by_id: dict[str, Box]) -> list[set[str]]:
    """Cluster group frames into horizontal bands by y-interval overlap.

    Groups in the same band are visual "peers" (same row of stages); groups in
    different bands (e.g. a validation band below the main flow) should not be
    held to peer alignment rules against each other.
    """
    ids = sorted(bounds_by_id)
    parent = {gid: gid for gid in ids}

    def find(gid: str) -> str:
        while parent[gid] != gid:
            parent[gid] = parent[parent[gid]]
            gid = parent[gid]
        return gid

    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            ay1, ay2 = bounds_by_id[a][1], bounds_by_id[a][3]
            by1, by2 = bounds_by_id[b][1], bounds_by_id[b][3]
            if ay1 < by2 and ay2 > by1:
                parent[find(a)] = find(b)
    clusters: dict[str, set[str]] = {}
    for gid in ids:
        clusters.setdefault(find(gid), set()).add(gid)
    return [clusters[root] for root in sorted(clusters)]


def measure(recipe_or_nodes: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Measure connector-path and overlap defects for a workflow layout."""
    nodes = _nodes(recipe_or_nodes)
    by_id = {node["id"]: node for node in nodes}
    edges = iter_edges(nodes)

    body_boxes: list[tuple[str, Box]] = []
    label_boxes: list[tuple[str, Box]] = []
    group_frames: list[tuple[str, Box]] = []
    for node in nodes:
        if node.get("type") == "group":
            frame = group_frame(node, by_id)
            if frame is not None:
                group_frames.append((node["id"], frame))
        elif node.get("type") != "text":
            box = node_box(node, by_id)
            if box is not None and node.get("type") != "outlet":
                body_boxes.append((node["id"], box))
            pos = absolute_position(node, by_id)
            if pos is not None:
                left_over, right_ext, band_h = label_extent(node)
                body_h = OUTLET_HEIGHT if node.get("type") == "outlet" else BODY_H
                label_boxes.append((
                    node["id"],
                    (pos[0] - left_over, pos[1] + body_h, pos[0] + right_ext,
                     pos[1] + body_h + band_h),
                ))

    polylines: dict[int, list[Point]] = {}
    through_nodes: list[tuple[str, str, str]] = []
    through_labels: list[tuple[str, str, str]] = []
    through_groups: list[tuple[str, str, str]] = []
    backward_edges: list[tuple[str, str]] = []
    long_edges: list[tuple[str, str, float]] = []
    total_length = 0.0
    missing_positions = sum(
        1
        for node in nodes
        if node.get("type") not in {"text"} and absolute_position(node, by_id) is None
    )

    bboxes: dict[int, Box] = {}
    for index, edge in enumerate(edges):
        ports = edge_ports(edge, by_id)
        if ports is None:
            continue
        p1, p2 = ports
        polyline = edge_polyline(p1, p2)
        polylines[index] = polyline
        bboxes[index] = _polyline_bbox(polyline)
        dx = p2[0] - p1[0]
        if dx < 0:
            backward_edges.append((edge[0], edge[1]))
        if dx > LONG_EDGE_DX:
            long_edges.append((edge[0], edge[1], dx))
        total_length += ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5

        def _edge_parent(node_id: str) -> str:
            """An outlet pseudo-node belongs to its base node's group: its frame wraps the
            outlet circle, so the connector leaving it exits its OWN frame, not a foreign one."""
            node = by_id[node_id]
            parent = _parent_id(node)
            if not parent and node.get("type") == "outlet" and "|" in str(node_id):
                base = str(node_id).partition("|")[0]
                if base in by_id:
                    parent = _parent_id(by_id[base])
            return parent

        src_parent = _edge_parent(edge[0])
        target_parent = _edge_parent(edge[1])
        for node_id, box in body_boxes:
            if node_id in (edge[0], edge[1]):
                continue
            if polyline_intersects_box(polyline, box, bboxes[index]):
                through_nodes.append((edge[0], edge[1], node_id))
        for node_id, box in label_boxes:
            if node_id in (edge[0], edge[1]):
                continue
            if polyline_intersects_box(polyline, box, bboxes[index]):
                through_labels.append((edge[0], edge[1], node_id))
        for group_id, frame in group_frames:
            if group_id in (src_parent, target_parent):
                continue
            if polyline_intersects_box(polyline, frame, bboxes[index]):
                through_groups.append((edge[0], edge[1], group_id))

    # LINE OVERLAPS (user finding, 2026-06-10): two connectors RIDING ON each other —
    # coincident runs, not crossings — read as a wiring error. Detected by hashing each
    # polyline's samples to a coarse grid and counting cells shared between edge pairs
    # that don't touch the same node.
    cell_edges: dict[tuple[int, int], set[int]] = {}
    for index, polyline in polylines.items():
        for x, y in polyline:
            cell_edges.setdefault((int(x // 12), int(y // 12)), set()).add(index)
    pair_cells: dict[tuple[int, int], int] = {}
    for shared in cell_edges.values():
        if len(shared) < 2:
            continue
        ordered = sorted(shared)
        for ii, a in enumerate(ordered):
            for b in ordered[ii + 1:]:
                pair_cells[(a, b)] = pair_cells.get((a, b), 0) + 1
    line_overlaps: list[tuple[str, str, str, str]] = []
    for (a, b), count in pair_cells.items():
        ea, eb = edges[a], edges[b]
        # Arms converging on a shared node legitimately share the LAST few pixels before
        # their ports — but a LONG shared run (two lines riding one channel) reads as a
        # wiring error even between sibling arms (user finding, 2026-06-10).
        threshold = 8 if set(ea[:2]) & set(eb[:2]) else 4
        if count < threshold:
            continue
        line_overlaps.append((ea[0], ea[1], eb[0], eb[1]))

    crossings: list[tuple[int, int]] = []
    indices = sorted(polylines)
    for i_pos, i in enumerate(indices):
        for j in indices[i_pos + 1 :]:
            if set(edges[i][:2]) & set(edges[j][:2]):
                continue
            if polylines_cross(polylines[i], polylines[j], bboxes[i], bboxes[j]):
                crossings.append((i, j))

    # Overlaps use the card envelope. (A footprint model — body + estimated label band —
    # was tried 2026-06-10 and reverted: char-count label estimates produced 9 false
    # overlaps on a known-good hand layout, and the overlap tier outranks everything, so
    # estimation error there silently dominates arbitration. Revisit only with
    # DOM-measured label widths.)
    node_overlaps = [
        (a_id, b_id)
        for idx, (a_id, a_box) in enumerate(body_boxes)
        for b_id, b_box in body_boxes[idx + 1 :]
        if _boxes_overlap(a_box, b_box)
    ]
    group_overlaps = [
        (a_id, b_id)
        for idx, (a_id, a_box) in enumerate(group_frames)
        for b_id, b_box in group_frames[idx + 1 :]
        if _boxes_overlap(a_box, b_box)
    ]

    # Neatness metrics (user-visible polish, 2026-06-10 review): a connector that COULD be a
    # straight horizontal run but bends, and multi-input nodes whose inlet order contradicts
    # their sources' vertical order (guaranteeing a needless crossing at the junction).
    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}
    for a, b, _inlet in edges:
        out_degree[a] = out_degree.get(a, 0) + 1
        in_degree[b] = in_degree.get(b, 0) + 1
    bent_chain_edges: list[tuple[str, str]] = []
    for index, edge in enumerate(edges):
        ports = edge_ports(edge, by_id)
        if ports is None:
            continue
        src_node, dst_node = by_id.get(edge[0].partition("|")[0]), by_id.get(edge[1])
        same_stage = (src_node is not None and dst_node is not None
                      and (src_node.get("canvasConfig") or {}).get("parentId")
                      == (dst_node.get("canvasConfig") or {}).get("parentId"))
        if same_stage and out_degree.get(edge[0], 0) == 1 and in_degree.get(edge[1], 0) == 1 \
                and abs(ports[0][1] - ports[1][1]) > 6.0:
            bent_chain_edges.append((edge[0], edge[1]))
    # Label containment (user rule, 2026-06-10): the rendered name label is a centered box
    # under the 96px body, wrapping at ~200px (DOM-measured). A group is a container for its
    # furniture INCLUDING label ink — a label closer than 8px to (or past) a frame edge clips.
    label_clips: list[tuple[str, str]] = []
    frame_by_id = dict(group_frames)
    for node in nodes:
        kind = node.get("type")
        if kind in {"group", "text"}:
            continue
        parent = _parent_id(node)
        if not parent and kind == "outlet" and "|" in str(node.get("id")):
            base = by_id.get(str(node["id"]).partition("|")[0])
            parent = _parent_id(base) if base else None
        frame = frame_by_id.get(parent)
        pos = absolute_position(node, by_id)
        if frame is None or pos is None:
            continue
        left_over, right_ext, band_h = label_extent(node)
        body_h = OUTLET_HEIGHT if kind == "outlet" else BODY_H
        if (pos[0] - left_over < frame[0] + 8.0
                or pos[0] + right_ext > frame[2] - 8.0
                or pos[1] + body_h + band_h > frame[3] - 8.0):
            label_clips.append((node["id"], parent))

    inlet_order_mismatches: list[tuple[str, ...]] = []
    sources_by_target: dict[str, list[tuple[str, str]]] = {}
    for a, b, inlet in edges:
        sources_by_target.setdefault(b, []).append((inlet, a))
    for target_id, sources in sources_by_target.items():
        if len(sources) < 2:
            continue
        rows: list[tuple[str, float, str]] = []
        for inlet, src_id in sources:
            src = by_id.get(src_id)
            pos = absolute_position(src, by_id) if src else None
            if pos is not None:
                rows.append((inlet, pos[1], src_id))
        by_inlet = [src_id for _inlet, _y, src_id in sorted(rows, key=lambda r: r[0])]
        by_height = [src_id for _inlet, _y, src_id in sorted(rows, key=lambda r: r[1])]
        if len(by_inlet) >= 2 and by_inlet != by_height:
            inlet_order_mismatches.append((target_id, *by_inlet))

    return {
        "edge_count": len(edges),
        "through_nodes": through_nodes,
        "through_labels": through_labels,
        "through_groups": through_groups,
        "crossings": [(edges[i], edges[j]) for i, j in crossings],
        "backward_edges": backward_edges,
        "long_edges": long_edges,
        "node_overlaps": node_overlaps,
        "group_overlaps": group_overlaps,
        "missing_positions": missing_positions,
        "total_edge_length": total_length,
        "bent_chain_edges": bent_chain_edges,
        "inlet_order_mismatches": inlet_order_mismatches,
        "label_clips": label_clips,
        "line_overlaps": line_overlaps,
        "canvas_area": _canvas_area(nodes, by_id),
    }


def _canvas_area(nodes: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> float:
    """Bounding-box area of the house (group frames; bare nodes when ungrouped)."""
    xs: list[float] = []
    ys: list[float] = []
    for node in nodes:
        if node.get("type") == "group":
            frame = group_frame(node, by_id)
            if frame is not None:
                xs.extend((frame[0], frame[2]))
                ys.extend((frame[1], frame[3]))
        elif node.get("type") not in {"text"}:
            box = node_box(node, by_id)
            if box is not None:
                xs.extend((box[0], box[2]))
                ys.extend((box[1], box[3]))
    if not xs:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


class LayoutScore(NamedTuple):
    """Named lexicographic badness tiers; lower is better."""

    missing_positions: float
    collisions: float
    through_nodes: float
    through_groups: float
    through_labels: float
    line_overlaps: float
    backward_edges: float
    inlet_order: float
    crossings: float
    label_clips: float
    bent_chains: float
    edge_length: float
    canvas_area: float

    @property
    def correctness(self) -> tuple[float, ...]:
        """Hard tiers used by repair: never trade correctness for neatness."""
        return (
            self.missing_positions,
            self.collisions,
            self.through_nodes,
            self.through_groups,
            self.through_labels,
            self.line_overlaps,
            self.backward_edges,
            self.inlet_order,
        )


def score(metrics: dict[str, Any]) -> LayoutScore:
    """Lexicographic badness score; lower is better.

    Order matters: a connector through a node body is worse than a crossing,
    a crossing is worse than extra edge length. Length is bucketed so float
    jitter never decides between two otherwise-equal layouts.
    """
    return LayoutScore(
        missing_positions=float(metrics["missing_positions"]),
        collisions=float(len(metrics["node_overlaps"]) + len(metrics["group_overlaps"])),
        through_nodes=float(len(metrics["through_nodes"])),
        through_groups=float(len(metrics["through_groups"])),
        # Label ink is furniture too: a connector through a wrapped label is less severe
        # than cutting a card body, but still worse than taking a longer open route.
        through_labels=float(len(metrics.get("through_labels") or [])),
        # connectors riding ON each other read as a wiring error — overlap tier
        line_overlaps=float(len(metrics.get("line_overlaps") or [])),
        backward_edges=float(len(metrics["backward_edges"])),
        # USER RULING (2026-06-10, fixed-asset junction review): wrong inlet order at a
        # junction — arms crossing AT the node — reads worse than long lines crossing in
        # open space, so inlet order outranks crossings.
        inlet_order=float(len(metrics.get("inlet_order_mismatches") or [])),
        crossings=float(len(metrics["crossings"])),
        # A label clipping its frame edge breaks the container rule — worse than neatness
        # nits, better than a real collision.
        label_clips=float(len(metrics.get("label_clips") or [])),
        bent_chains=float(len(metrics.get("bent_chain_edges") or [])),
        edge_length=float(int(metrics["total_edge_length"] // 200)),
        # smallest house LAST (user principle: minimize space WITHOUT compromising any
        # constraint above) — bucketed so float jitter never decides
        canvas_area=float(int(metrics.get("canvas_area", 0.0) // 50000)),
    )


def describe(metrics: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Human-readable defect lines for reports and debugging."""

    def label(node_id: str) -> str:
        if by_id and node_id in by_id:
            return str(by_id[node_id].get("name") or node_id)
        return node_id

    lines: list[str] = []
    for src, target, blocker in metrics["through_nodes"]:
        lines.append(f"connector `{label(src)}` -> `{label(target)}` passes through node `{label(blocker)}`")
    for src, target, group_id in metrics["through_groups"]:
        lines.append(f"connector `{label(src)}` -> `{label(target)}` cuts through group `{label(group_id)}`")
    for src, target, blocker in metrics.get("through_labels") or []:
        lines.append(
            f"connector `{label(src)}` -> `{label(target)}` passes through label `{label(blocker)}`"
        )
    for (a, b) in metrics["backward_edges"]:
        lines.append(f"connector `{label(a)}` -> `{label(b)}` runs right-to-left")
    for (a_edge, b_edge) in metrics["crossings"]:
        lines.append(
            f"connector `{label(a_edge[0])}` -> `{label(a_edge[1])}` crosses "
            f"`{label(b_edge[0])}` -> `{label(b_edge[1])}`"
        )
    return lines
