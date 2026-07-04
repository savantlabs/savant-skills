"""Plan-first layout solver.

The legacy engine placed nodes with a pipeline of local heuristics whose clean-up passes did
not know about each other — every fix changed what the next pass saw, which made results
inconsistent across graph shapes (live incidents 2026-06-10). This module computes the WHOLE
plan from the graph structure first, then positions fall out of it:

1. Groups are stages: each gets a disjoint COLUMN BAND, ordered by dependency, so stage
   frames can never overlap or interleave.
2. Within a band, every maximal chain is a STREAM on one LANE: chains run straight, a
   split's branches step down one lane each (first branch continues), the longest edge from
   a multi-successor node keeps the spine lane, and corridors under long straight runs are
   reserved so nothing parks inside them.
3. Junction inlet order matches the sources' vertical order, so connectors never cross at
   a join for no reason.
4. A stream fed by a LONG TAP from an earlier stage dives below every band the tap crosses,
   so the connector travels open space instead of cutting stage frames.
5. Cross-band chain connectors keep row continuity (the consumer's first node aligns to its
   feeder's row).

`workflow.layout_metrics` is the acceptance check, not the repair driver. Scope: positions,
outlet anchors, group frames, header text geometry. Colors and text content are styling and
live in `workflow.polish`.
"""
from __future__ import annotations

from typing import Any

from workflow.geometry import NODE_HEIGHT, NODE_WIDTH, input_port_y_offset, output_port_y_offset
from workflow import layout_metrics as lm
from workflow import layout_model as model

# LAYOUT OBJECTIVE (user, 2026-06-10): each group is a ROOM, the workflow is the HOME.
# Furniture (cards, outlets, labels) is arranged neatly inside the smallest room that
# satisfies the constraints (containment, min gaps, straight runs); rooms then pack into
# the smallest home. Constraints always win over compactness — never the other way round.
#
# Equivalently, this is the classic web/CSS box model (user framing): a group is a
# container; its FRAME_PAD is `padding` measured from rendered content ink (body, outlet
# circle, label box — never envelope fictions); MIN_GAP_* are the children's margins;
# ROOM_GAP_* is the `gap` between containers in both axes, set on real edges after
# sizing; band alignment is `align-items: stretch` across a row of containers. When a
# layout looks wrong, find which box-model rule was broken — don't nudge coordinates.
#
# Minimum clear space between ANY two elements (node cards and outlet circles), both axes.
MIN_GAP_X = model.MIN_GAP_X
MIN_GAP_Y = model.MIN_GAP_Y
COL_DX = model.COL_DX                # normal column pitch (card + connector run)
SPLIT_COL_DX = model.SPLIT_COL_DX
# Label geometry is shared with layout_metrics (single source of truth, DOM-measured).
BODY_W = model.BODY_W
LABEL_MARGIN = model.LABEL_MARGIN    # min clearance between label ink and a frame edge
# (raised from 16 per the user's widened reference: label-bound edges read cramped next
# to the 48px body padding; 32 keeps the padding rhythm even without envelope fictions)
ROW_DY = model.ROW_DY                # lane pitch: card + label band clearance
# Frame padding is EQUAL on all four content sides (left, right, below header, bottom), so the
# member block sits centered in its frame both axes by construction (user rule, 2026-06-10).
HEADER_H = model.HEADER_H
FRAME_PAD = model.FRAME_PAD
CONTENT_TOP = model.CONTENT_TOP
PAD_X = model.PAD_X
PAD_BOT = model.PAD_BOT
GROUP_FRAME_GAP = model.GROUP_FRAME_GAP
CANVAS_X0 = model.CANVAS_X0
CANVAS_Y0 = model.CANVAS_Y0
OUTLET_GAP = model.OUTLET_GAP        # outlet circle sits a min-gap after its split
# An outlet RENDERS bigger than its 28px circle: a status icon and a name label hang below
# it. The frame must contain that whole footprint — a group is a container and nothing but
# connectors may leak out of it (user rule, Sales by State live review 2026-06-10).
OUTLET_LABEL_CLEARANCE = model.OUTLET_LABEL_CLEARANCE
OUTLET_STEP = model.OUTLET_STEP
# (matches the user's manual reference: sibling outlet centers ~120px apart)
OUTLET_PORT_ALIGN_GAP = lm.OUTLET_HEIGHT + 8.0
OUTLET_LABEL_GAP = 24.0
REPAIR_MAX_MOVES = 24
REPAIR_STEP = ROW_DY
REPAIR_STEP_X = COL_DX
# Long connectors need a full lane of breathing room from unrelated rooms; the normal
# frame-to-frame gap is enough between rooms, but reads too tight when a connector has to
# pass the room edge for hundreds of pixels.
CORRIDOR_ROOM_GAP = ROW_DY
# Members must stay below the group header band; a repair move may never push one above it.
HEADER_CONTENT_TOP_MIN = 90.0


_label_box = lm.label_extent
TAP_SPAN_COLUMNS = model.TAP_SPAN_COLUMNS
TAP_CLEARANCE_LANES = model.TAP_CLEARANCE_LANES


def _parent_id(node: dict[str, Any]) -> str | None:
    return model.parent_id(node)


def _raw_edges(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return model.raw_edges(nodes)


def _inlet_rank(node: dict[str, Any], inlet: str, src_id: str) -> int:
    return model.inlet_rank(node, inlet, src_id)


def _port_source_id(src_id: str, outlet_idx: int) -> str:
    return f"{src_id}|{outlet_idx}" if outlet_idx >= 0 else src_id


def _outlet_sibling_gap(upper: dict[str, Any]) -> float:
    """Top-to-top gap so the next outlet clears the upper outlet's rendered label."""
    return lm.OUTLET_HEIGHT + lm.label_extent(upper)[2] + OUTLET_LABEL_GAP


def _position(node: dict[str, Any]) -> dict[str, float] | None:
    pos = node.get("position")
    if not isinstance(pos, dict):
        return None
    try:
        return {"x": float(pos.get("x")), "y": float(pos.get("y"))}
    except (TypeError, ValueError):
        return None


class _Plan:
    def __init__(self, nodes: list[dict[str, Any]], junction_fallback: bool = True,
                 room_compression: bool = True, bypass_merge_spine: bool = True,
                 side_tap_can_rise: bool = True):
        self.junction_fallback = junction_fallback
        self.room_compression = room_compression
        self.bypass_merge_spine = bypass_merge_spine
        self.side_tap_can_rise = side_tap_can_rise
        self.nodes = nodes
        self.by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
        self.body = [n for n in nodes if n.get("type") not in {"group", "text", "outlet"}]
        self.body_ids = {n["id"] for n in self.body}
        self.groups = [n for n in nodes if n.get("type") == "group"]
        self.order = {n["id"]: i for i, n in enumerate(self.body)}
        # edges resolved THROUGH outlet pseudo-nodes: (src_base, dst, inlet, outlet_idx)
        self.edges: list[tuple[str, str, str, int]] = []
        for a, b, inlet in _raw_edges(nodes):
            base, _, idx = a.partition("|")
            outlet_idx = int(idx) if idx.isdigit() else -1
            if base in self.body_ids and b in self.body_ids:
                self.edges.append((base, b, inlet, outlet_idx))
        self.preds: dict[str, list[tuple[str, str, int]]] = {}
        self.succs: dict[str, list[tuple[str, int]]] = {}
        for a, b, inlet, k in self.edges:
            self.preds.setdefault(b, []).append((a, inlet, k))
            self.succs.setdefault(a, []).append((b, k))

        def block_of(nid: str) -> str:
            return _parent_id(self.by_id[nid]) or f"__solo__{nid}"

        self.block_of = block_of
        self.blocks: list[str] = []
        seen: set[str] = set()
        for n in self.body:
            b = block_of(n["id"])
            if b not in seen:
                seen.add(b)
                self.blocks.append(b)

        self.relocations: list[tuple[int, str, str]] = []
        self.col: dict[str, int] = {}
        self.lane: dict[str, float] = {}
        self.stream_of: dict[str, int] = {}
        self.streams: list[list[str]] = []
        self.band_start: dict[str, int] = {}
        self.block_order: list[str] = []
        self.satellite_group: dict[str, str] = {}

    # --- phase 1: stage bands (groups in dependency order own disjoint column ranges) -------
    def compute_bands(self) -> None:
        deps: dict[str, set[str]] = {b: set() for b in self.blocks}
        for a, t, _i, _k in self.edges:
            ba, bt = self.block_of(a), self.block_of(t)
            if ba != bt:
                deps[bt].add(ba)
        # Levels over the stage DAG: independent stages (e.g. two parallel prep stages feeding
        # the same join stage) share ONE column range and stack vertically, instead of being
        # serialized into the path of every connector that crosses between their neighbors.
        level: dict[str, int] = {b: 0 for b in self.blocks}
        for _ in range(len(self.blocks) + 1):
            changed = False
            for b in self.blocks:
                for dep in deps[b]:
                    if level[b] <= level[dep]:
                        level[b] = level[dep] + 1
                        changed = True
            if not changed:
                break
        self.block_level = level
        self.block_order = sorted(self.blocks, key=lambda b: (level[b], self.blocks.index(b)))

        # local ranks: longest path over in-block edges (externally fed nodes start at 0)
        self.local_rank: dict[str, int] = {n["id"]: 0 for n in self.body}
        for _ in range(len(self.body) + 1):
            changed = False
            for a, t, _i, _k in self.edges:
                if self.block_of(a) == self.block_of(t) and self.local_rank[t] <= self.local_rank[a]:
                    self.local_rank[t] = self.local_rank[a] + 1
                    changed = True
            if not changed:
                break
        # Right-align chain tails toward their consumers (slack pull): a junction's feeders
        # land in the SAME column just before it, so the join connectors form a clean
        # symmetric bracket instead of one long and one short run (user rule, 2026-06-10).
        for _ in range(len(self.body) + 1):
            changed = False
            for n in self.body:
                nid = n["id"]
                nxt_cols = [self.local_rank[t] for t, _k in self.succs.get(nid) or []
                            if self.block_of(t) == self.block_of(nid)]
                if nxt_cols:
                    slack = min(nxt_cols) - 1
                    if slack > self.local_rank[nid]:
                        self.local_rank[nid] = slack
                        changed = True
            if not changed:
                break

        width = {b: 0 for b in self.blocks}
        for n in self.body:
            b = self.block_of(n["id"])
            width[b] = max(width[b], self.local_rank[n["id"]] + 1)
        # Stage-exit alignment: a chain whose only successors live in LATER stages ends at its
        # own stage's last column, so parallel rows leave the stage at the same x (user rule).
        for n in self.body:
            nid = n["id"]
            succs = self.succs.get(nid) or []
            if succs and all(self.block_of(t) != self.block_of(nid) for t, _k in succs):
                self.local_rank[nid] = width[self.block_of(nid)] - 1
        levels = sorted(set(self.block_level.values()))
        level_width = {lv: max([width[b] for b in self.blocks if self.block_level[b] == lv] or [1])
                       for lv in levels}
        cursor = 0
        level_start: dict[int, int] = {}
        for lv in levels:
            level_start[lv] = cursor
            cursor += level_width[lv]       # frames get a fixed pixel gap, not a phantom column
        for b in self.blocks:
            self.band_start[b] = level_start[self.block_level[b]]
        # Pixel x per global column, with split columns widened so split -> outlet -> consumer
        # keeps MIN_GAP_X on both sides of the outlet circle, and a fixed frame gap per level.
        has_split_outlets = {n["id"] for n in self.nodes if n.get("type") == "outlet"}
        split_cols: set[int] = set()
        for n in self.body:
            if any(f"{n['id']}|{i}" in has_split_outlets for i in range(4)):
                split_cols.add(self.band_start[self.block_of(n["id"])]
                               + self.local_rank[n["id"]])
        self.split_cols = split_cols
        total_cols = cursor
        level_of_col: dict[int, int] = {}
        for b in self.blocks:
            lv = self.block_level[b]
            w = width[b]
            for c in range(self.band_start[b], self.band_start[b] + w):
                level_of_col[c] = lv
        self.col_x: dict[int, float] = {}
        x = 0.0
        prev_level = None
        prev_extent = NODE_WIDTH
        prev_pitch = COL_DX
        for c in range(total_cols):
            lv = level_of_col.get(c)
            if prev_level is not None and lv is not None and lv != prev_level:
                # frame boundary: prev column's occupied extent (card, or card + outlet for a
                # split) + symmetric frame padding + the fixed clear gap between frames.
                x += GROUP_FRAME_GAP + 2 * PAD_X - (prev_pitch - prev_extent)
            self.col_x[c] = x
            if c in split_cols:
                prev_pitch = SPLIT_COL_DX
                prev_extent = NODE_WIDTH + MIN_GAP_X + lm.OUTLET_WIDTH
            else:
                prev_pitch = COL_DX
                prev_extent = NODE_WIDTH
            x += prev_pitch
            if lv is not None:
                prev_level = lv
        for n in self.body:
            nid = n["id"]
            self.col[nid] = self.band_start[self.block_of(nid)] + self.local_rank[nid]
        self._compute_satellites()

    def _compute_satellites(self) -> None:
        """Parentless one-node blocks can be visually attached to one room.

        This is layout affinity only. It does not change group membership; it just keeps
        a singleton that only talks to one grouped neighbor moving with that room when
        rooms are later packed and compacted.
        """
        self.satellite_group = {}
        for n in self.body:
            nid = n["id"]
            if _parent_id(n) is not None or self.block_of(nid) != f"__solo__{nid}":
                continue
            neighbors: set[str] = set()
            for src, _inlet, _k in self.preds.get(nid) or []:
                b = self.block_of(src)
                if b in self.by_id and self.by_id[b].get("type") == "group":
                    neighbors.add(b)
            for target, _k in self.succs.get(nid) or []:
                b = self.block_of(target)
                if b in self.by_id and self.by_id[b].get("type") == "group":
                    neighbors.add(b)
            if len(neighbors) == 1:
                self.satellite_group[nid] = next(iter(neighbors))

    # --- phase 1b: furniture belongs with its consumers (user reference, superstore
    # 2026-06-10): a SOURCE component (no inputs from other rooms) whose every outgoing
    # edge feeds ONE room ≥2 levels away is RELOCATED into that room. This removes the
    # long tap instead of routing it — fewer lines crossing rooms, smaller house. -------------
    def relocate_far_source_streams(self) -> int:
        moved = 0
        for block in list(self.blocks):
            if block.startswith("__solo__"):
                continue
            members = [n["id"] for n in self.body if self.block_of(n["id"]) == block]
            uf = {m: m for m in members}

            def find(i: str) -> str:
                while uf[i] != i:
                    uf[i] = uf[uf[i]]
                    i = uf[i]
                return i

            for a, b, _i, _k in self.edges:
                if a in uf and b in uf:
                    uf[find(a)] = find(b)
            comps: dict[str, list[str]] = {}
            for m in members:
                comps.setdefault(find(m), []).append(m)
            for comp in comps.values():
                if len(comp) == len(members):
                    continue   # never empty a room
                comp_set = set(comp)
                ext_out = {self.block_of(t) for a in comp
                           for t, _k in self.succs.get(a) or [] if t not in comp_set}
                ext_in = any(s not in comp_set and self.block_of(s) != block
                             for n in comp for s, _i, _k in self.preds.get(n) or [])
                if ext_in or len(ext_out) != 1:
                    continue
                target = ext_out.pop()
                if target.startswith("__solo__") or target == block:
                    continue
                if self.block_level[target] - self.block_level[block] < 2:
                    continue   # adjacent rooms connect cleanly; no need to move
                for nid in comp:
                    cc = self.by_id[nid].setdefault("canvasConfig", {})
                    cc["parentId"] = target
                src_name = (self.by_id.get(block) or {}).get("name") or block
                dst_name = (self.by_id.get(target) or {}).get("name") or target
                self.relocations.append((len(comp), str(src_name), str(dst_name)))
                moved += len(comp)
        return moved

    # --- phase 2: streams ---------------------------------------------------------------------
    def compute_streams(self) -> None:
        def chain_next(nid: str) -> str | None:
            nxt = self.succs.get(nid) or []
            if len(nxt) != 1:
                return None
            target = nxt[0][0]
            if len(self.preds.get(target) or []) != 1:
                return None
            if self.block_of(target) != self.block_of(nid):
                return None   # streams stay inside one band; continuity handled at placement
            return target

        heads: list[str] = []
        for n in self.body:
            nid = n["id"]
            p = self.preds.get(nid) or []
            is_head = len(p) != 1
            if not is_head:
                src = p[0][0]
                if len(self.succs.get(src) or []) != 1 or self.block_of(src) != self.block_of(nid):
                    is_head = True
            if is_head:
                heads.append(nid)
        heads.sort(key=lambda nid: (self.col[nid], self.order.get(nid, 0)))
        seen: set[str] = set()
        for head in heads:
            if head in seen:
                continue
            stream = [head]
            seen.add(head)
            cur = head
            while True:
                nxt = chain_next(cur)
                if nxt is None or nxt in seen:
                    break
                stream.append(nxt)
                seen.add(nxt)
                cur = nxt
            sid = len(self.streams)
            self.streams.append(stream)
            for nid in stream:
                self.stream_of[nid] = sid
        for n in self.body:   # cycle guard
            if n["id"] not in self.stream_of:
                sid = len(self.streams)
                self.streams.append([n["id"]])
                self.stream_of[n["id"]] = sid

    # --- phase 3: lanes -------------------------------------------------------------------------
    def assign_lanes(self) -> None:
        span: dict[int, tuple[int, int]] = {}
        for sid, stream in enumerate(self.streams):
            span[sid] = (min(self.col[n] for n in stream), max(self.col[n] for n in stream))
        # occupancy is GLOBAL (lane, col_from, col_to): bands are column-disjoint, so streams of
        # different stages only conflict when a dive lane or corridor genuinely shares columns.
        occupied: list[tuple[str, float, int, int]] = []
        stream_corridor: dict[int, tuple[int, int]] = {}
        BLOCK_GAP_LANES = 2.0   # vertical clearance between STREAMS of different stages, so
                                # stage frames (header band + padding) never touch.

        def free_lane(block: str, desired: float, col_from: int, col_to: int,
                      prefer_down: bool = False) -> float:
            def blocked(lane: float) -> bool:
                return any(not (col_to < f or col_from > t)
                           and abs(lane - other) < (0.999 if b == block else BLOCK_GAP_LANES)
                           for b, other, f, t in occupied)

            if not blocked(desired):
                return desired
            if prefer_down:
                # DIVES search downward only: their desired lane is already "below
                # everything crossed" — rising again would re-enter the crossed band.
                lane = desired
                while blocked(lane):
                    lane += 1.0
                return lane
            # Everything else takes the NEAREST free lane, below or above: a join crowded
            # out of its desired row belongs just beside it (user reference: the near
            # feeder bends SHORT, above the join), not at the bottom of the room. Negative
            # lanes are legal; place() re-anchors the home at the canvas origin.
            for step in range(1, 64):
                for lane in (desired + step, desired - step):
                    if not blocked(lane):
                        return lane
            return desired + 64.0

        def span_blocked(block: str, lane: float, col_from: int, col_to: int,
                         clearance: float | None = None) -> bool:
            # Corridor checks ask whether a LINE can travel this lane. Default clearance is
            # conservative (BLOCK_GAP_LANES for foreign streams — their rooms may grow
            # below their cards for outlets/labels); callers that know the crossed room's
            # real extent may pass a tighter clearance.
            return any(not (col_to < f or col_from > t)
                       and abs(lane - other) < (clearance if clearance is not None
                                                else (0.999 if b == block
                                                      else BLOCK_GAP_LANES))
                       for b, other, f, t in occupied)

        def tap_lane(block: str, feeder_id: str, head: str) -> tuple[float, tuple[int, int]]:
            """A long tap PREFERS its feeder's own lane — a straight, reserved corridor is the
            best possible shape. It dives below everything the tap crosses only when that lane
            is already occupied across the span (e.g. another stage's band sits in the way)."""
            lane = self.lane[feeder_id]
            corridor = (self.col[feeder_id] + 1, self.col[head] - 1)
            if not span_blocked(block, lane, corridor[0], corridor[1]):
                return lane, corridor
            spanned = [other for _b, other, f, t in occupied
                       if not (corridor[1] < f or corridor[0] > t)]
            dive = (max(spanned) + TAP_CLEARANCE_LANES) if spanned else lane
            return dive, corridor

        def inlet_hint(sid: int) -> int:
            """Earliest junction inlet this stream ultimately feeds: streams headed for in_0
            get assigned (and therefore stacked) above streams headed for in_1, so the wiring
            at the junction matches the vertical order from the very first column."""
            hint = 99
            for nid in self.streams[sid]:
                for t, _k in self.succs.get(nid) or []:
                    if len(self.preds.get(t) or []) >= 2:
                        for a, inlet, _kk in self.preds[t]:
                            if a == nid:
                                hint = min(hint, _inlet_rank(self.by_id[t], inlet, a))
            return hint

        def is_source_stream(sid: int) -> bool:
            return not (self.preds.get(self.streams[sid][0]) or [])

        # TOP-DOWN SWEEP (user crossing review, 2026-06-10): estimate every stream's
        # desired lane first (entry continuity, sibling order, inlet-relative placement
        # for source chains), then assign rooms in column order and streams within a room
        # from the TOP DOWN. Assigning in desired-lane order means an entry row claims its
        # lane and corridor before lower furniture parks there, and a deep entry (e.g. a
        # sentiment line) is assigned after the furniture it must dive beneath.
        est: dict[str, float] = {n["id"]: 0.0 for n in self.body}
        for _ in range(len(self.streams) + 1):
            for stream in self.streams:
                head = stream[0]
                feeders = sorted(self.preds.get(head) or [],
                                 key=lambda p: _inlet_rank(self.by_id[head], p[1], p[0]))
                if feeders and len(feeders) >= 2:
                    e = sum(est[p[0]] for p in feeders) / len(feeders)
                elif feeders:
                    primary_id = feeders[0][0]
                    sibs = [t for t, _k in self.succs.get(primary_id) or []]
                    e = est[primary_id] + float(sibs.index(head) if head in sibs else 0)
                else:
                    # source chain: sit where the junction it feeds expects it (inlet
                    # rank relative to the junction's first-ranked feeder)
                    tail = stream[-1]
                    e = 0.0
                    for t, _k in self.succs.get(tail) or []:
                        ranked = sorted(self.preds.get(t) or [],
                                        key=lambda p: _inlet_rank(self.by_id[t], p[1], p[0]))
                        if len(ranked) >= 2:
                            ranks = [p[0] for p in ranked]
                            if tail in ranks and ranks[0] != tail:
                                e = est[ranks[0]] + float(ranks.index(tail))
                        break
                for nid in stream:
                    est[nid] = e
        # Bands assign left-to-right; WITHIN a band the order is decided at that moment,
        # top-down by REAL entry lanes (external feeders are already assigned) with the
        # estimate filling in for in-room streams. A static global order mis-ranked deep
        # entries (the estimate cannot see room stacking) and their corridors trapped
        # in-room furniture (user crossing review, 2026-06-10).
        by_band: dict[int, list[int]] = {}
        for sid in range(len(self.streams)):
            by_band.setdefault(self.band_start[self.block_of(self.streams[sid][0])], []).append(sid)

        def entry_key(sid: int) -> float:
            head = self.streams[sid][0]
            real = [self.lane[s] for s, _i, _k in self.preds.get(head) or [] if s in self.lane]
            return min(real) if real else est[head]

        def _assign_stream(sid: int) -> None:
            head = self.streams[sid][0]
            col_from, col_to = span[sid]
            corridor: tuple[int, int] | None = None
            dive = False
            feeders = sorted(self.preds.get(head) or [],
                             key=lambda p: _inlet_rank(self.by_id[head], p[1], p[0]))
            assigned = [p for p in feeders if p[0] in self.lane]
            if not assigned:
                # source chain: aim at its estimated slot (inlet-relative to the junction
                # it feeds), not blindly at the top row
                desired = est[head]
            elif len(assigned) >= 2:
                def sibling_branch_lane(primary: str, target: str) -> float:
                    base = self.lane[primary]

                    def band_dist(t: str) -> int:
                        if self.block_of(t) == self.block_of(primary):
                            return 0
                        return abs(self.block_order.index(self.block_of(t))
                                   - self.block_order.index(self.block_of(primary)))

                    siblings = sorted(self.succs.get(primary) or [],
                                      key=lambda bk: (max(bk[1], 0),
                                                      -band_dist(bk[0]),
                                                      -(self.col[bk[0]] - self.col[primary]),
                                                      self.order.get(bk[0], 0)))
                    sib_index = next((i for i, (t, _kk) in enumerate(siblings) if t == target), 0)
                    half = (sib_index + 1) // 2
                    return base + float(half if sib_index % 2 == 0 else -half)

                def feeder_start_outlet(feeder: str, split: str) -> int | None:
                    seen: set[str] = set()
                    cur = feeder
                    while cur not in seen:
                        seen.add(cur)
                        preds = self.preds.get(cur) or []
                        if len(preds) != 1:
                            return None
                        src, _inlet, k = preds[0]
                        if src == split:
                            return k if k >= 0 else None
                        cur = src
                    return None

                def feeder_starts_from_sibling(feeder: str, split: str, direct_k: int) -> bool:
                    k = feeder_start_outlet(feeder, split)
                    return k is not None and k != direct_k

                bypass_anchor: tuple[str, int] | None = None
                for src_id, _inlet, k in assigned:
                    if k < 0:
                        continue
                    if any(other != src_id and feeder_starts_from_sibling(other, src_id, k)
                           for other, _other_inlet, _other_k in assigned):
                        bypass_anchor = (src_id, k)
                        break
                # JOIN: midpoint of the feeders gives the symmetric bracket (user rule). A join
                # fed by a LONG TAP instead follows the tap's lane when that straight corridor
                # is free, and dives below the blockage when it is not — symmetry never licenses
                # riding through occupied space.
                tap_feeders = [p for p in assigned
                               if self.col[head] - self.col[p[0]] >= TAP_SPAN_COLUMNS]
                using_bypass_anchor = bypass_anchor is not None and self.bypass_merge_spine
                if using_bypass_anchor:
                    # Split-repair-merge: one branch bypasses straight to the merge while a
                    # sibling branch performs cleanup and returns. The bypass is the continuing
                    # spine, so the merge row belongs to that branch; the repair branch bends
                    # back in. This matches the hand layout for filter -> blank/fix -> merge
                    # patterns without hard-coding True/False.
                    desired = sibling_branch_lane(bypass_anchor[0], head)
                    direct_k = bypass_anchor[1]
                    repair_lanes = []
                    repair_outlets = []
                    for other, _other_inlet, _other_k in assigned:
                        if other == bypass_anchor[0]:
                            continue
                        start_k = feeder_start_outlet(other, bypass_anchor[0])
                        if start_k is not None and start_k != direct_k:
                            repair_lanes.append(self.lane[other])
                            repair_outlets.append(start_k)
                    if repair_lanes and any(abs(desired - lane) < 0.999 for lane in repair_lanes):
                        # If the sibling repair stream has already claimed the same row, give
                        # the direct bypass a separate clear lane. Outlet order decides the side:
                        # later branch labels usually sit visually below the split, so its direct
                        # merge row goes above the repair lane in the common True-repair/False-keep
                        # pattern seen in manual layouts.
                        if min(repair_outlets) < direct_k:
                            desired = min(repair_lanes) - 1.0
                        else:
                            desired = max(repair_lanes) + 1.0
                elif tap_feeders:
                    far = min(tap_feeders, key=lambda p: self.col[p[0]])
                    desired, corridor = tap_lane(self.block_of(head), far[0], head)
                    dive = desired != self.lane[far[0]]   # tap_lane dove below a blockage
                else:
                    # Midpoint of the feeders: the join's two arms bend symmetrically (a join's
                    # inlet ports sit closer together than two cards can, so SOME bend is
                    # unavoidable — the user's manual reference layout, 2026-06-10, centers the
                    # join and splits the bend evenly across both arms).
                    desired = sum(self.lane[p[0]] for p in assigned) / len(assigned)
                if len(assigned) >= 2 and not using_bypass_anchor:
                    feeder_lanes = {round(self.lane[p[0]], 3) for p in assigned}
                    lower_ports = [
                        input_port_y_offset(self.by_id[head], p[1], _port_source_id(p[0], p[2]))
                        for p in assigned
                    ]
                    if len(feeder_lanes) == 1 and max(lower_ports) > output_port_y_offset(self.by_id[head]):
                        # Same-row feeders plus lower join ports create a connector lane that
                        # runs through labels below the feeder row. Keep the join stream in the
                        # same stage, but drop it one lane so the lower inlet has clear air.
                        desired += 1.0
            else:
                primary, _inlet, _k = assigned[0]
                base = self.lane[primary]

                def band_dist(t: str) -> int:
                    if self.block_of(t) == self.block_of(primary):
                        return 0
                    return abs(self.block_order.index(self.block_of(t))
                               - self.block_order.index(self.block_of(primary)))

                # Sibling order at the feeder decides who continues the lane: first outlet,
                # then the FARTHEST stage — the longest run should be the straightest (user
                # reference, superstore 2026-06-10): the far branch keeps the spine and its
                # reserved corridor pushes intermediate stages OFF that lane, so it travels
                # clean open space; near branches take the bend, which stays short.
                siblings = sorted(self.succs.get(primary) or [],
                                  key=lambda bk: (max(bk[1], 0),
                                                  -band_dist(bk[0]),
                                                  -(self.col[bk[0]] - self.col[primary]),
                                                  self.order.get(bk[0], 0)))
                sib_index = next((i for i, (t, _kk) in enumerate(siblings) if t == head), 0)
                # Branches FAN SYMMETRICALLY around the spine (user: "design is all about
                # symmetry"): spine straight, next branch one lane UP, next one DOWN —
                # all-downward stacking left rooms hanging below the axis and forced the
                # centering pass to bend line order later. Measured across the corpus,
                # this also resolves the recon tap class; outlet-ordered splits stay
                # readable because the inlet-order metric/swap still police the junctions.
                half = (sib_index + 1) // 2
                desired = base + float(half if sib_index % 2 == 0 else -half)
                # FAN (user's manual reference, 2026-06-10): when a split's branches each lead
                # into a DIFFERENT stage of the same next level, the branch rooms bracket the
                # split's row symmetrically (one up, one down) instead of spine-plus-dive —
                # the home stays short and the split sits centered between its consumers.
                fan_targets = [t for t, _kk in siblings
                               if self.block_of(t) != self.block_of(primary)]
                fan_blocks = [self.block_of(t) for t in fan_targets]
                if (len(fan_targets) >= 2 and len(set(fan_blocks)) == len(fan_blocks)
                        and len({self.block_level[b] for b in fan_blocks}) == 1
                        and head in fan_targets):
                    # ±1 lane around the split: adjacent fan branches end up exactly
                    # BLOCK_GAP_LANES apart (the rooms share columns), and the home stays
                    # short — the user's manual reference brackets at roughly this pitch.
                    i = fan_targets.index(head)
                    desired = base + (i - (len(fan_targets) - 1) / 2.0) * 2.0
                tap_span = self.col[head] - self.col[primary]
                if sib_index > 0 and tap_span >= TAP_SPAN_COLUMNS:
                    # side tap: the spine keeps the feeder's lane, so this one dives below
                    # everything it crosses (stage frames included).
                    spanned = [other for _b, other, f, t in occupied
                               if not (self.col[head] - 1 < f or self.col[primary] + 1 > t)]
                    if spanned:
                        if self.side_tap_can_rise and desired < base:
                            # A long independent branch does not always have to dive. If its
                            # natural fan position is above the trunk, route it above the
                            # occupied band; this is the generic version of the hand layout
                            # that moved summarization streams above to clear the dense middle.
                            desired = min(min(spanned) - TAP_CLEARANCE_LANES, desired)
                            dive = False
                        else:
                            desired = max(max(spanned) + TAP_CLEARANCE_LANES, desired)
                            dive = True
                    corridor = (self.col[primary] + 1, self.col[head] - 1)
                elif sib_index == 0 and tap_span >= 2:
                    # spine run: reserve the corridor so no later stream parks inside the
                    # straight run. A LONG spine keeps the feeder's lane only while that
                    # corridor is still free — stages assigned earlier can't be pushed
                    # aside, so a blocked long spine dives below them like any tap.
                    corridor = (self.col[primary] + 1, self.col[head] - 1)
                    if tap_span >= TAP_SPAN_COLUMNS \
                            and span_blocked(self.block_of(head), desired,
                                             corridor[0], corridor[1], clearance=0.999):
                        # A long spine keeps its lane while every crossed stream sits a
                        # full lane away — one lane clears a room's frame by ~25px (the
                        # user's straight detail line beneath the Summarize room). Any
                        # closer blockage means the spine dives below everything instead.
                        spanned = [other for _b, other, f, t in occupied
                                   if not (corridor[1] < f or corridor[0] > t)]
                        if spanned:
                            desired = max(spanned) + TAP_CLEARANCE_LANES
                            dive = True
            block = self.block_of(head)
            lane = free_lane(block, desired, col_from, col_to, prefer_down=dive)
            for nid in self.streams[sid]:
                self.lane[nid] = lane
            occupied.append((block, lane, col_from, col_to))
            if corridor is not None and corridor[0] <= corridor[1]:
                occupied.append((block, lane, corridor[0], corridor[1]))
                stream_corridor[sid] = (corridor[0], corridor[1])

        # drive band by band: each band's order is computed AFTER the previous bands have
        # real lanes, so entry keys are actual feeder rows, not estimates.
        for band in sorted(by_band):
            for sid in sorted(by_band[band],
                              key=lambda s: (entry_key(s), span[s][0],
                                             self.order.get(self.streams[s][0], 0))):
                _assign_stream(sid)

        # FURNITURE COMPACTION (user references, 2026-06-10): the smallest-house rule
        # applies INSIDE rooms too — streams pull UP to close empty lane bands (collision
        # bumps and dive clearances leave fractional gaps), keeping their order, the
        # 1-lane pitch, cross-room gaps, and straight external feeds pinned.
        def _lane_conflicts(sid: int, lane: float) -> bool:
            b1 = self.block_of(self.streams[sid][0])
            own = [span[sid]] + ([stream_corridor[sid]] if sid in stream_corridor else [])
            for sid2 in range(len(self.streams)):
                if sid2 == sid:
                    continue
                l2 = self.lane[self.streams[sid2][0]]
                b2 = self.block_of(self.streams[sid2][0])
                gap = 0.999 if b1 == b2 else BLOCK_GAP_LANES
                if abs(lane - l2) >= gap:
                    continue
                others = [span[sid2]] + ([stream_corridor[sid2]] if sid2 in stream_corridor else [])
                for f1, t1 in own:
                    for f2, t2 in others:
                        if not (t2 < f1 or f2 > t1):
                            return True
            return False

        # blocks compact in DEPENDENCY order so a stream that moves is seen by its
        # followers in later blocks, which compact to their entry-continuity lane —
        # feeders never leave their straight followers behind (trace finding, 2026-06-10).
        for block in self.block_order:
            sids = sorted((sid for sid in range(len(self.streams))
                           if self.block_of(self.streams[sid][0]) == block),
                          key=lambda s: self.lane[self.streams[s][0]])
            prev_lane: float | None = None
            for sid in sids:
                head = self.streams[sid][0]
                cur = self.lane[head]
                feeder_lanes = [self.lane[s] for s, _i, _k in self.preds.get(head) or []
                                if s in self.lane]
                if prev_lane is None:
                    # first stream of the block: pull up to its entry continuity lane
                    target = min(feeder_lanes) if feeder_lanes else None
                else:
                    target = prev_lane + 1.0
                if target is not None and cur > target + 0.01:
                    pinned = any(abs(fl - cur) < 0.01 for fl in feeder_lanes)
                    feeders = [p for p in self.preds.get(head) or [] if p[0] in self.lane]
                    label_clearance_pinned = False
                    if len(feeders) >= 2 and len({round(self.lane[p[0]], 3) for p in feeders}) == 1:
                        lower_ports = [
                            input_port_y_offset(self.by_id[head], p[1], _port_source_id(p[0], p[2]))
                            for p in feeders
                        ]
                        label_clearance_pinned = (
                            max(lower_ports) > output_port_y_offset(self.by_id[head])
                            and cur >= min(feeder_lanes) + 0.99
                        )
                    if not pinned and not label_clearance_pinned:
                        t = target
                        while t < cur - 0.01 and _lane_conflicts(sid, t):
                            t += 0.5
                        if t < cur - 0.01:
                            for nid in self.streams[sid]:
                                self.lane[nid] = t
                            cur = t
                prev_lane = cur

        # junction neatness: inlet order must match vertical order; swap dedicated input
        # streams when they contradict it — TRANSACTIONALLY: a swap that would land two
        # streams closer than a lane apart (or break the stage gap) is reverted, because the
        # swap pass writes lanes directly and used to bypass collision checking (live: source
        # trios ending up half a lane apart, cards overlapping).
        def lane_map_valid() -> bool:
            spans: list[tuple[str, float, int, int]] = []
            for sid2, stream2 in enumerate(self.streams):
                b2 = self.block_of(stream2[0])
                f2 = min(self.col[n] for n in stream2)
                t2 = max(self.col[n] for n in stream2)
                spans.append((b2, self.lane[stream2[0]], f2, t2))
            for i, (b1, l1, f1, t1) in enumerate(spans):
                for b2, l2, f2, t2 in spans[i + 1:]:
                    if t2 < f1 or f2 > t1:
                        continue
                    gap = 0.999 if b1 == b2 else BLOCK_GAP_LANES
                    if abs(l1 - l2) < gap:
                        return False
            return True

        for n in self.body:
            feeders = self.preds.get(n["id"]) or []
            if len(feeders) < 2:
                continue
            ranked = sorted(feeders, key=lambda p: _inlet_rank(self.by_id[n["id"]], p[1], p[0]))
            lanes = [self.lane[p[0]] for p in ranked]
            if lanes == sorted(lanes):
                continue
            movable = all(len(self.succs.get(p[0]) or []) == 1 for p in ranked)
            if not movable:
                continue
            # Swaps only reorder streams that live in the SAME room as each other (e.g. two
            # source rows): swapping across rooms teleports a whole room's content to a
            # foreign lane (live: the review room landed 2.5 lanes deep, 2026-06-10).
            if len({self.block_of(p[0]) for p in ranked}) != 1:
                continue
            before = dict(self.lane)
            for (src, _inlet, _k), new_lane in zip(ranked, sorted(lanes)):
                sid = self.stream_of[src]
                for nid in self.streams[sid]:
                    self.lane[nid] = new_lane
            if not lane_map_valid():
                self.lane = before
                if not self.junction_fallback:
                    continue
                # FALLBACK (user junction review, 2026-06-10): a full swap collides when
                # one feeder is a JOIN whose row is pinned by its own bracket. Do what a
                # person does instead — the join keeps its row, and each misplaced plain
                # chain relocates to the nearest free lane on its correct side.
                anchor = max(ranked, key=lambda p: len(self.preds.get(p[0]) or []))
                a_lane = self.lane[anchor[0]]
                a_rank = ranked.index(anchor)
                for r_i, (src, _inlet2, _k2) in enumerate(ranked):
                    if src == anchor[0]:
                        continue
                    want_below = r_i > a_rank
                    cur = self.lane[src]
                    if (cur > a_lane + 0.01) == want_below and abs(cur - a_lane) > 0.01:
                        continue   # already on the correct side
                    sid2 = self.stream_of[src]
                    saved = dict(self.lane)
                    step = 1.0 if want_below else -1.0
                    t = a_lane + step
                    placed_ok = False
                    while abs(t - a_lane) < 8.0:
                        for nid in self.streams[sid2]:
                            self.lane[nid] = t
                        if lane_map_valid():
                            placed_ok = True
                            break
                        self.lane = dict(saved)
                        t += step
                    if not placed_ok:
                        self.lane = saved

    # --- phase 4: positions, outlets, frames -----------------------------------------------------
    def place(self) -> None:
        for n in self.body:
            nid = n["id"]
            n["position"] = {
                "x": CANVAS_X0 + PAD_X + self.col_x.get(self.col[nid], self.col[nid] * COL_DX),
                "y": CANVAS_Y0 + CONTENT_TOP + self.lane[nid] * ROW_DY,
            }
        # Justify-spread (user rule): when a stage row is shorter than its column span (its
        # exit is pinned to the stage edge), distribute the interior nodes evenly instead of
        # clustering left and jumping — the in-between space is used, and rows read balanced.
        for stream in self.streams:
            if len(stream) < 3:
                continue
            xs = [self.by_id[nid]["position"]["x"] for nid in stream]
            if xs[-1] - xs[0] <= (len(stream) - 1) * COL_DX + 1:
                continue
            lane = self.lane[stream[0]]
            members = set(stream)
            # never spread into a lane interval another stream also occupies — fractional
            # columns next to a neighbor's integer column read as overlapping cards.
            shared = any(abs(self.lane[n["id"]] - lane) < 0.75 and n["id"] not in members
                         and xs[0] - COL_DX < n["position"]["x"] < xs[-1] + COL_DX
                         for n in self.body)
            if shared:
                continue
            step = (xs[-1] - xs[0]) / (len(stream) - 1)
            for i, nid in enumerate(stream[1:-1], 1):
                self.by_id[nid]["position"]["x"] = xs[0] + i * step

        # TAP-EXIT DROP (user crossing review, 2026-06-10): a node whose chain continues on
        # its own row AND that fires a far cross-room tap gets dropped half a row — the tap
        # then exits through clear space under its own chain instead of slicing through the
        # next cards (a flat bezier exit cannot sag fast enough to clear same-row
        # neighbors). The half-row bend at the chain head is the intended, readable shape.
        for n in self.body:
            nid = n["id"]
            succs = self.succs.get(nid) or []
            if len(succs) < 2:
                continue
            same_lane_chain = any(abs(self.lane.get(t, -99) - self.lane[nid]) < 0.01
                                  and self.block_of(t) == self.block_of(nid)
                                  for t, _k in succs)
            far_tap = any(self.col[t] - self.col[nid] >= TAP_SPAN_COLUMNS
                          and self.block_of(t) != self.block_of(nid)
                          for t, _k in succs)
            if same_lane_chain and far_tap:
                n["position"]["y"] += ROW_DY / 2.0

        # straighten: single-feeder nodes whose feeder has a single successor align ports
        # exactly, including across stage boundaries (row continuity).
        for n in sorted(self.body, key=lambda n: self.col[n["id"]]):
            p = self.preds.get(n["id"]) or []
            if len(p) != 1:
                continue
            src_id, inlet, _k = p[0]
            src = self.by_id[src_id]
            if len(self.succs.get(src_id) or []) != 1 or "position" not in src:
                continue
            # Cross-stage port-snap only when the plan already put feeder and consumer on the
            # same lane: a deliberate cross-stage offset (stage separation, dive) must never be
            # "straightened" away — that collapse re-created frame overlaps the plan prevented.
            # In-stage snaps are always plan-consistent (chains share their stream's lane).
            if self.block_of(n["id"]) != self.block_of(src_id) \
                    and abs(self.lane[n["id"]] - self.lane[src_id]) > 0.5:
                continue
            n["position"]["y"] = (src["position"]["y"] + output_port_y_offset(src)
                                  - input_port_y_offset(n, inlet, _port_source_id(src_id, _k)))
        # outlets: a min-gap after the split. The row comes from the consumer when that keeps
        # the outlet's FULL footprint (circle + label) inside the stage; otherwise the outlet
        # fans symmetrically around the split's out port (the user's manual reference layout)
        # and the frame grows to contain it. The connector takes its bend outside the frame.
        block_y: dict[str, tuple[float, float]] = {}
        for n in self.body:
            b = self.block_of(n["id"])
            y = n["position"]["y"]
            lo, bot = block_y.get(b, (y, y))
            block_y[b] = (min(lo, y), max(bot, y + NODE_HEIGHT))
        outlets_by_src: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for n in self.nodes:
            if n.get("type") != "outlet" or "|" not in str(n.get("id")):
                continue
            base, _, idx = str(n["id"]).partition("|")
            if base in self.by_id and "position" in self.by_id[base]:
                outlets_by_src.setdefault(base, []).append(
                    (int(idx) if idx.isdigit() else -1, n))

        for base, items in outlets_by_src.items():
            src = self.by_id[base]
            lo, member_bot = block_y.get(self.block_of(base),
                                         (src["position"]["y"],
                                          src["position"]["y"] + NODE_HEIGHT))
            port_y = src["position"]["y"] + output_port_y_offset(src)
            items.sort(key=lambda kn: max(kn[0], 0))
            rows: dict[str, float] = {}
            fallback: list[tuple[int, dict[str, Any]]] = []
            for k, n in items:
                consumers = [(b, inlet) for a, b, inlet, kk in self.edges if a == base and kk == k]
                row = None
                if consumers and all("position" in self.by_id[c] for c, _inlet in consumers):
                    row = min(self.by_id[c]["position"]["y"]
                              + input_port_y_offset(self.by_id[c], inlet, f"{base}|{k}")
                              for c, inlet in consumers) - lm.OUTLET_HEIGHT / 2
                # consumer row counts only when the full footprint stays inside the frame
                if row is not None and lo <= row <= member_bot + PAD_BOT \
                        - lm.OUTLET_HEIGHT - OUTLET_LABEL_CLEARANCE:
                    rows[n["id"]] = row
                else:
                    fallback.append((k, n))
            # highest row whose full footprint still fits the un-grown room: prefer slots in
            # this range so the room only grows when it truly has no space left (smallest room).
            hi = member_bot + PAD_BOT - lm.OUTLET_HEIGHT - OUTLET_LABEL_CLEARANCE
            m = len(fallback)
            for i, (_k, n) in enumerate(fallback):
                row = port_y - lm.OUTLET_HEIGHT / 2 + (i - (m - 1) / 2.0) * OUTLET_STEP
                rows[n["id"]] = min(max(row, lo), max(hi, lo))

            # Keep branch markers close to the input port they feed. The old placement used
            # the full circle+label height as sibling spacing, so a False branch feeding a
            # nearby lower inlet was pushed far below the target and rendered as a stair-step.
            # Use physical circle clearance for port alignment; the frame still grows later
            # to contain label ink.
            ordered = sorted(items, key=lambda kn: rows[kn[1]["id"]])
            placed: dict[str, float] = {}
            last: float | None = None
            last_node: dict[str, Any] | None = None
            for _k, n in ordered:
                row = rows[n["id"]]
                if last is not None and last_node is not None:
                    row = max(row, last + _outlet_sibling_gap(last_node))
                placed[n["id"]] = row
                last = row
                last_node = n
            if ordered:
                preferred_avg = sum(rows[n["id"]] for _k, n in ordered) / len(ordered)
                placed_avg = sum(placed[n["id"]] for _k, n in ordered) / len(ordered)
                shift = preferred_avg - placed_avg
                min_shift = max(lo - placed[n["id"]] for _k, n in ordered)
                if all(rows[n["id"]] <= hi for _k, n in ordered):
                    max_shift = min(hi - placed[n["id"]] for _k, n in ordered)
                else:
                    max_shift = shift
                shift = min(max(shift, min_shift), max_shift)
                for _k, n in ordered:
                    placed[n["id"]] += shift

            for _k, n in items:
                n["position"] = {"x": src["position"]["x"] + OUTLET_GAP, "y": placed[n["id"]]}
                n["canvasConfig"] = n.get("canvasConfig") or {}
        # group frames wrap members; member positions become group-relative; headers span frames.
        for g in self.groups:
            # outlets are never sized as cards — even when the saved recipe parents them to
            # the group (the UI does this), they get footprint treatment via `tails` below.
            members = [n for n in self.nodes if _parent_id(n) == g["id"]
                       and n.get("type") not in {"text", "outlet"}]
            texts = [n for n in self.nodes if _parent_id(n) == g["id"] and n.get("type") == "text"]
            placed = [m for m in members if isinstance(m.get("position"), dict)]
            if not placed:
                continue
            member_ids = {m["id"] for m in placed}
            # A split's outlets belong to its stage: the frame wraps them too (same padding),
            # so outlet circles never bleed past the frame edge.
            tails = [n for n in self.nodes if n.get("type") == "outlet"
                     and str(n.get("id")).partition("|")[0] in member_ids
                     and isinstance(n.get("position"), dict)]
            # The room wraps the FURNITURE INK with ONE rule, identical for every room
            # (user: the middle room's padding looked different from its neighbors):
            # FRAME_PAD from the rendered body/circle, or LABEL_MARGIN from label ink,
            # whichever binds. No card-envelope fictions — ink only.
            lefts, rights, bottoms = [], [], []
            for m in placed:
                lo_over, r_ext, band = _label_box(m)
                lefts.append(min(m["position"]["x"] - PAD_X,
                                 m["position"]["x"] - lo_over - LABEL_MARGIN))
                rights.append(max(m["position"]["x"] + BODY_W + PAD_X,
                                  m["position"]["x"] + r_ext + LABEL_MARGIN))
                bottoms.append(m["position"]["y"] + lm.BODY_H + band + PAD_BOT)
            for t in tails:
                _lo, t_right, t_band = lm.label_extent(t)   # outlet labels are ink too
                rights.append(max(t["position"]["x"] + lm.OUTLET_WIDTH + PAD_X,
                                  t["position"]["x"] + t_right + LABEL_MARGIN))
                bottoms.append(t["position"]["y"] + lm.OUTLET_HEIGHT + t_band + PAD_BOT)
            # The room's header band is as tall as its text actually renders at this width
            # (title ~30px/line at 1.5rem, description ~19px/line) — never a stale stored
            # height and never a worst-case constant. Short headers mean shorter rooms.
            gx = min(lefts)
            gw = max(rights) - gx
            header_h = HEADER_H
            for t in texts:
                tcfg = t.setdefault("config", {})
                raw = str(tcfg.get("inputText") or "")
                if raw.strip():
                    first, _, rest = raw.partition("\n")
                    title_lines = max(1, -(-len(first) // max(int(gw / 14.0), 8)))
                    # Each explicit description line is a forced break, so wrap-estimate them
                    # independently and sum — a flattened single-paragraph estimate would
                    # undercount multi-line descriptions and clip the header band.
                    chars_per = max(int(gw / 7.8), 14)
                    desc_lines = sum(
                        max(1, -(-len(dl) // chars_per))
                        for dl in (line.strip() for line in rest.split("\n"))
                        if dl
                    )
                    est = 18.0 + title_lines * 30.0 + desc_lines * 19.0
                    h = max(int(HEADER_H), int(est))
                    tcfg["height"] = h
                    tcfg["currentHeight"] = h
                header_h = max(header_h, float(tcfg.get("currentHeight")
                                               or tcfg.get("height") or HEADER_H))
            gy = min(m["position"]["y"] for m in placed) - (header_h + FRAME_PAD)
            gh = max(
                max(bottoms) - gy,
                max(m["position"]["y"] - gy + NODE_HEIGHT + PAD_BOT for m in placed),
            )
            g["position"] = {"x": gx, "y": gy}
            cfg = g.setdefault("config", {})
            cfg["width"], cfg["height"] = gw, gh
            for m in placed:
                m["position"] = {"x": m["position"]["x"] - gx, "y": m["position"]["y"] - gy}
            for t in tails:   # parented outlets are group-relative like any member
                if _parent_id(t) == g["id"]:
                    t["position"] = {"x": t["position"]["x"] - gx, "y": t["position"]["y"] - gy}
            for t in texts:
                t["position"] = {"x": 0.0, "y": 0.0}
                tcfg = t.setdefault("config", {})
                tcfg["width"] = int(gw)
                tcfg["height"] = max(int(tcfg.get("height") or HEADER_H), int(HEADER_H))
                tcfg["currentHeight"] = tcfg["height"]

        # In-room row compression: long tap clearances can leave empty lane bands inside a
        # room after all furniture has been wrapped. Pull whole lower row stacks upward to
        # the shared lane pitch, but keep only moves accepted by the shared score. This is
        # a constructive packing step, not a second geometry vocabulary.
        def _group_children(gid: str) -> list[dict[str, Any]]:
            return [
                n for n in self.nodes
                if _parent_id(n) == gid and n.get("type") not in {"group", "text", "outlet"}
                and isinstance(n.get("position"), dict)
            ]

        def _set_group_height_to_contents(g: dict[str, Any]) -> None:
            children = _group_children(g["id"])
            if not children:
                return
            bottom = max(
                n["position"]["y"] + NODE_HEIGHT + _label_box(n)[2] + PAD_BOT
                for n in children
            )
            for n in self.nodes:
                if _parent_id(n) == g["id"] and n.get("type") == "outlet" \
                        and isinstance(n.get("position"), dict):
                    _lo, _right, band = lm.label_extent(n)
                    bottom = max(bottom, n["position"]["y"] + lm.OUTLET_HEIGHT + band + PAD_BOT)
            g.setdefault("config", {})["height"] = bottom

        def _realign_group_outlets(g: dict[str, Any]) -> None:
            if not isinstance(g.get("position"), dict):
                return
            group_y = float(g["position"]["y"])
            group_outlets = [
                n for n in self.nodes
                if _parent_id(n) == g["id"] and n.get("type") == "outlet"
                and "|" in str(n.get("id")) and isinstance(n.get("position"), dict)
            ]
            by_base: dict[str, list[tuple[int, dict[str, Any]]]] = {}
            for n in group_outlets:
                base, _, idx = str(n["id"]).partition("|")
                if base in self.by_id and idx.isdigit():
                    by_base.setdefault(base, []).append((int(idx), n))

            for base, items in by_base.items():
                rows: dict[str, float] = {}
                for k, n in items:
                    consumers = [(b, inlet) for a, b, inlet, kk in self.edges if a == base and kk == k]
                    targets = [
                        self.by_id[c] for c, _inlet in consumers
                        if c in self.by_id and isinstance(self.by_id[c].get("position"), dict)
                    ]
                    if not targets:
                        rows[n["id"]] = float(n["position"]["y"])
                        continue
                    target_rows = []
                    for c, inlet in consumers:
                        target = self.by_id.get(c)
                        if target is None or not isinstance(target.get("position"), dict):
                            continue
                        pos = lm.absolute_position(target, self.by_id)
                        if pos is None:
                            continue
                        target_rows.append(
                            pos[1] + input_port_y_offset(target, inlet, _port_source_id(base, k))
                            - lm.OUTLET_HEIGHT / 2
                            - group_y
                        )
                    rows[n["id"]] = min(target_rows) if target_rows else float(n["position"]["y"])

                ordered = sorted(items, key=lambda kn: rows[kn[1]["id"]])
                placed: dict[str, float] = {}
                last: float | None = None
                last_node: dict[str, Any] | None = None
                for _k, n in ordered:
                    row = rows[n["id"]]
                    if last is not None and last_node is not None:
                        row = max(row, last + _outlet_sibling_gap(last_node))
                    placed[n["id"]] = row
                    last = row
                    last_node = n
                if ordered:
                    preferred_avg = sum(rows[n["id"]] for _k, n in ordered) / len(ordered)
                    placed_avg = sum(placed[n["id"]] for _k, n in ordered) / len(ordered)
                    shift = preferred_avg - placed_avg
                    for _k, n in ordered:
                        placed[n["id"]] += shift
                        n["position"]["y"] = placed[n["id"]]

        if self.room_compression:
            for g in self.groups:
                if not isinstance(g.get("position"), dict) or not isinstance(g.get("config"), dict):
                    continue
                children = _group_children(g["id"])
                if len(children) < 2:
                    continue
                rows: list[tuple[float, list[dict[str, Any]]]] = []
                for child in sorted(children, key=lambda n: n["position"]["y"]):
                    y = float(child["position"]["y"])
                    if rows and abs(rows[-1][0] - y) < ROW_DY / 2:
                        rows[-1][1].append(child)
                    else:
                        rows.append((y, [child]))
                if len(rows) < 2:
                    continue
                best_metrics = lm.measure(self.nodes)
                best_score = lm.score(best_metrics)
                for row_index in range(1, len(rows)):
                    prev_y = rows[row_index - 1][0]
                    row_y = rows[row_index][0]
                    slack = row_y - (prev_y + ROW_DY)
                    if slack <= 1.0:
                        continue
                    movers = [node for _y, row_nodes in rows[row_index:] for node in row_nodes]
                    saved_positions = {node["id"]: dict(node["position"]) for node in movers}
                    outlets = [
                        n for n in self.nodes
                        if _parent_id(n) == g["id"] and n.get("type") == "outlet"
                        and isinstance(n.get("position"), dict)
                    ]
                    saved_outlets = {node["id"]: dict(node["position"]) for node in outlets}
                    saved_height = g["config"].get("height")
                    for node in movers:
                        node["position"]["y"] -= slack
                    for i in range(row_index, len(rows)):
                        rows[i] = (rows[i][0] - slack, rows[i][1])
                    _realign_group_outlets(g)
                    _set_group_height_to_contents(g)
                    candidate_metrics = lm.measure(self.nodes)
                    candidate_score = lm.score(candidate_metrics)
                    if candidate_score <= best_score:
                        best_score = candidate_score
                        continue
                    for node in movers:
                        node["position"] = saved_positions[node["id"]]
                    for node in outlets:
                        node["position"] = saved_outlets[node["id"]]
                    g["config"]["height"] = saved_height
                    for i in range(row_index, len(rows)):
                        rows[i] = (rows[i][0] + slack, rows[i][1])
        # SIBLING ROOM WIDTHS (user rule, 2026-06-10): rooms in the same level share their
        # left/right edges — the widest room already sets the home's width there, so a
        # narrower sibling saves nothing and just looks ragged.
        by_level: dict[int, list[dict[str, Any]]] = {}
        for g in self.groups:
            if g["id"] in self.block_level and isinstance(g.get("position"), dict):
                by_level.setdefault(self.block_level[g["id"]], []).append(g)
        for peers in by_level.values():
            if len(peers) < 2:
                continue
            left = min(p["position"]["x"] for p in peers)
            right = max(p["position"]["x"] + p["config"]["width"] for p in peers)
            for p in peers:
                shift_x = p["position"]["x"] - left
                if shift_x > 0.5:   # widen leftward: members/parented tails keep abs position
                    p["position"]["x"] = left
                    for n in self.nodes:
                        if _parent_id(n) == p["id"] and n.get("type") != "text" \
                                and isinstance(n.get("position"), dict):
                            n["position"]["x"] += shift_x
                p["config"]["width"] = right - left
                for n in self.nodes:   # header text spans the widened frame
                    if _parent_id(n) == p["id"] and n.get("type") == "text":
                        (n.setdefault("config", {}))["width"] = int(right - left)

        # ROOM PACKING: rooms are sized only after their furniture (cards, labels, outlets)
        # is placed, so clearance between rooms is enforced HERE, on real room edges — one
        # shared gap constant in BOTH axes, never leftovers of pitch math (user: room
        # spacing must be consistent everywhere).
        ROOM_GAP_Y = GROUP_FRAME_GAP
        ROOM_GAP_X = GROUP_FRAME_GAP

        def _shift_room_x(g: dict[str, Any], dx: float) -> None:
            g["position"]["x"] += dx
            member_ids = {n["id"] for n in self.nodes if _parent_id(n) == g["id"]}
            for n in self.nodes:
                if n.get("type") == "outlet" and _parent_id(n) is None \
                        and str(n.get("id")).partition("|")[0] in member_ids \
                        and isinstance(n.get("position"), dict):
                    n["position"]["x"] += dx
                elif self.satellite_group.get(n.get("id")) == g["id"] \
                        and isinstance(n.get("position"), dict):
                    n["position"]["x"] += dx

        # Horizontal level packing: the gap between a level's real left edge and the
        # previous level's real right edge becomes exactly ROOM_GAP_X. Horizontal shifts
        # cannot bend a connector (ports sit on the left/right card edges).
        frames_by_level: dict[int, list[dict[str, Any]]] = {}
        for g in self.groups:
            if g["id"] in self.block_level and isinstance(g.get("position"), dict):
                frames_by_level.setdefault(self.block_level[g["id"]], []).append(g)
        cursor_right: float | None = None
        for lv in sorted(frames_by_level):
            rooms = frames_by_level[lv]
            left = min(r["position"]["x"] for r in rooms)
            right = max(r["position"]["x"] + r["config"]["width"] for r in rooms)
            if cursor_right is not None:
                dx = (cursor_right + ROOM_GAP_X) - left
                if abs(dx) > 0.5:
                    for r in rooms:
                        _shift_room_x(r, dx)
                    right += dx
            cursor_right = right

        def _shift_room(g: dict[str, Any], dy: float) -> None:
            g["position"]["y"] += dy
            member_ids = {n["id"] for n in self.nodes if _parent_id(n) == g["id"]}
            for n in self.nodes:   # parentLESS outlets move with their room; parented ones
                if n.get("type") == "outlet" and _parent_id(n) is None \
                        and str(n.get("id")).partition("|")[0] in member_ids \
                        and isinstance(n.get("position"), dict):
                    n["position"]["y"] += dy   # already ride along via the group
                elif self.satellite_group.get(n.get("id")) == g["id"] \
                        and isinstance(n.get("position"), dict):
                    n["position"]["y"] += dy

        frames = sorted((g for g in self.groups if isinstance(g.get("position"), dict)),
                        key=lambda g: g["position"]["y"])
        for i, g in enumerate(frames):
            for h in frames[:i]:
                gx1, gw1 = g["position"]["x"], g["config"]["width"]
                hx1, hw1 = h["position"]["x"], h["config"]["width"]
                if gx1 + gw1 <= hx1 or hx1 + hw1 <= gx1:
                    continue   # no horizontal overlap: side-by-side rooms
                h_bottom = h["position"]["y"] + h["config"]["height"]
                if g["position"]["y"] < h_bottom + ROOM_GAP_Y:
                    _shift_room(g, h_bottom + ROOM_GAP_Y - g["position"]["y"])

        # COMPACTION (user rule, 2026-06-10): the home takes the minimum space the
        # constraints allow. Stacked rooms in a level CLOSE UP to ROOM_GAP_Y — slack from
        # lane quantization is not a chosen gap. Guard: a room fed by a perfectly straight
        # connector keeps its row; straightness outranks compactness.
        def _abs_y(node: dict[str, Any]) -> float | None:
            if not isinstance(node.get("position"), dict):
                return None
            y = node["position"]["y"]
            parent = _parent_id(node)
            if parent and parent in self.by_id \
                    and isinstance(self.by_id[parent].get("position"), dict):
                y += self.by_id[parent]["position"]["y"]
            return y

        def _pullable(g: dict[str, Any]) -> bool:
            member_ids = {n["id"] for n in self.nodes if _parent_id(n) == g["id"]}
            for a, b, inlet, k in self.edges:
                if b not in member_ids or self.block_of(a) == self.block_of(b):
                    continue
                vis = self.by_id.get(f"{a}|{k}") if k >= 0 else None
                src = vis if vis is not None and isinstance(vis.get("position"), dict) \
                    else self.by_id.get(a)
                tgt = self.by_id.get(b)
                sy, ty = (_abs_y(src) if src else None), (_abs_y(tgt) if tgt else None)
                if sy is None or ty is None:
                    continue
                out_y = sy + (lm.OUTLET_HEIGHT / 2 if src.get("type") == "outlet"
                              else output_port_y_offset(src))
                in_y = ty + input_port_y_offset(tgt, inlet, _port_source_id(a, k))
                if abs(out_y - in_y) <= 1.0:
                    return False   # a straight feed pins this room
            return True

        for peers in by_level.values():
            stack = sorted((p for p in peers if isinstance(p.get("position"), dict)),
                           key=lambda p: p["position"]["y"])
            for prev, cur in zip(stack, stack[1:]):
                target = prev["position"]["y"] + prev["config"]["height"] + ROOM_GAP_Y
                slack = cur["position"]["y"] - target
                if slack > 0.5 and _pullable(cur):
                    _shift_room(cur, -slack)

        # CENTER ALIGNMENT (user reference layout, 2026-06-10, superseding edge-stretch):
        # rooms keep their natural compact heights and each level's stack CENTERS on the
        # home's horizontal axis — `align-items: center` in the box model. Gentle bends
        # between rooms are the accepted price; a shift is reverted if it creates any new
        # frame cut or through-node.
        if frames_by_level:
            def _cut_count() -> int:
                m = lm.measure(self.nodes)
                # crossings count too: a centering shift must never flip the vertical
                # order of connected rows (that manufactures crossings, 2026-06-10)
                return (len(m["through_groups"]) + len(m["through_nodes"])
                        + len(m["crossings"]))

            level_span: dict[int, tuple[float, float]] = {}
            for lv, rooms in frames_by_level.items():
                level_span[lv] = (min(r["position"]["y"] for r in rooms),
                                  max(r["position"]["y"] + r["config"]["height"] for r in rooms))
            # axis = center of the tallest level (the home's height is set there anyway)
            axis_lv = max(level_span, key=lambda lv: level_span[lv][1] - level_span[lv][0])
            axis = sum(level_span[axis_lv]) / 2.0
            cuts_before = _cut_count()
            for lv in sorted(frames_by_level):
                if lv == axis_lv:
                    continue
                top, bottom = level_span[lv]
                dy = axis - (top + bottom) / 2.0
                if abs(dy) < 1.0:
                    continue
                moved: list[dict[str, Any]] = []
                for r in frames_by_level[lv]:
                    _shift_room(r, dy)
                    moved.append(r)
                cuts_after = _cut_count()
                if cuts_after > cuts_before:
                    for r in moved:
                        _shift_room(r, -dy)
                else:
                    cuts_before = cuts_after

        for nid in sorted(self.satellite_group):
            node = self.by_id.get(nid)
            if node is None or not isinstance(node.get("position"), dict):
                continue
            preds = self.preds.get(nid) or []
            succs = self.succs.get(nid) or []
            if len(preds) == 1:
                src_id, inlet, k = preds[0]
                src = self.by_id.get(src_id)
                sy = _abs_y(src) if src else None
                if sy is not None:
                    node["position"]["y"] = (
                        sy + output_port_y_offset(src)
                        - input_port_y_offset(node, inlet, _port_source_id(src_id, k))
                    )
            elif len(succs) == 1:
                target_id, k = succs[0]
                target = self.by_id.get(target_id)
                ty = _abs_y(target) if target else None
                if ty is not None:
                    inlet = next((i for s, i, kk in self.preds.get(target_id) or []
                                  if s == nid and kk == k), "in_0")
                    node["position"]["y"] = (
                        ty + input_port_y_offset(target, inlet, _port_source_id(nid, k))
                        - output_port_y_offset(node)
                    )

        # re-anchor the home: fan branches may have used negative lanes, so shift every
        # parentless element down until the topmost frame/card sits at the canvas origin.
        tops = [g["position"]["y"] for g in self.groups if isinstance(g.get("position"), dict)]
        tops += [n["position"]["y"] for n in self.nodes
                 if n.get("type") not in {"group", "text"} and _parent_id(n) is None
                 and isinstance(n.get("position"), dict)]
        if tops and abs(min(tops) - CANVAS_Y0) > 0.5:
            dy = CANVAS_Y0 - min(tops)
            for n in self.nodes:
                if n.get("type") == "text" or not isinstance(n.get("position"), dict):
                    continue
                if n.get("type") == "group" or _parent_id(n) is None:
                    n["position"]["y"] += dy


def _plan_and_place(nodes: list[dict[str, Any]], junction_fallback: bool = True,
                    room_compression: bool = True, bypass_merge_spine: bool = True,
                    side_tap_can_rise: bool = True) -> None:
    plan = _Plan(
        nodes,
        junction_fallback=junction_fallback,
        room_compression=room_compression,
        bypass_merge_spine=bypass_merge_spine,
        side_tap_can_rise=side_tap_can_rise,
    )
    plan.compute_bands()
    plan.compute_streams()
    plan.assign_lanes()
    plan.place()


def _repair_outlet_target_alignment(nodes: list[dict[str, Any]]) -> None:
    """Straighten tiny outlet-to-target bends against the rendered target port.

    This is deliberately local and guarded by the shared metrics. It catches the visual case
    where a branch marker is a few pixels off the single rendered input port even though there
    is clear space, without letting a full re-layout trade a local straight line for new
    connector-through-node defects elsewhere.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    hard_keys = (
        "missing_positions", "node_overlaps", "group_overlaps", "through_nodes",
        "through_groups", "through_labels", "line_overlaps", "backward_edges",
        "label_clips",
    )

    def hard_counts(metrics: dict[str, Any]) -> tuple[float, ...]:
        counts: list[float] = []
        for key in hard_keys:
            value = metrics.get(key)
            counts.append(float(len(value)) if isinstance(value, list) else float(value or 0))
        return tuple(counts)

    for outlet in nodes:
        if outlet.get("type") != "outlet" or "|" not in str(outlet.get("id")):
            continue
        if not isinstance(outlet.get("position"), dict):
            continue
        targets = []
        for out in outlet.get("outlets") or []:
            if isinstance(out, dict):
                targets.extend(t for t in out.get("targets") or [] if isinstance(t, dict))
        if len(targets) != 1:
            continue
        target_id = targets[0].get("target")
        target = by_id.get(target_id)
        if target is None or not isinstance(target.get("position"), dict):
            continue
        outlet_pos = lm.absolute_position(outlet, by_id)
        target_pos = lm.absolute_position(target, by_id)
        if outlet_pos is None or target_pos is None:
            continue
        inlet = str(targets[0].get("targetInlet") or "in_0")
        desired_y = (
            target_pos[1]
            + input_port_y_offset(target, inlet, str(outlet["id"]))
            - lm.OUTLET_HEIGHT / 2
        )
        delta = desired_y - outlet_pos[1]
        if abs(delta) < 1.0 or abs(delta) > 80.0:
            continue

        edge = (str(outlet["id"]), str(target_id), inlet)
        before = lm.measure(nodes)
        before_hard = hard_counts(before)
        before_ports = lm.edge_ports(edge, by_id)
        before_delta = abs(before_ports[0][1] - before_ports[1][1]) if before_ports else abs(delta)
        old_y = outlet["position"]["y"]
        outlet["position"]["y"] = old_y + delta
        after = lm.measure(nodes)
        after_ports = lm.edge_ports(edge, by_id)
        after_delta = abs(after_ports[0][1] - after_ports[1][1]) if after_ports else before_delta
        if all(a <= b for a, b in zip(hard_counts(after), before_hard)) \
                and after_delta < before_delta:
            continue
        outlet["position"]["y"] = old_y


def _repair_multi_input_continuation_alignment(nodes: list[dict[str, Any]]) -> None:
    """Snap same-row continuations into multi-input nodes to the rendered inlet port.

    Box alignment is correct for ordinary one-input nodes because the input and output ports
    share the same vertical center. Multi-input nodes render their first/second physical
    inlets above/below center, so a same-row continuation can still get a tiny dogleg. This
    local repair moves the multi-input target by that small port delta only when the shared
    layout metrics do not worsen.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}
    for src_id, target_id, _inlet in lm.iter_edges(nodes):
        out_degree[src_id] = out_degree.get(src_id, 0) + 1
        in_degree[target_id] = in_degree.get(target_id, 0) + 1

    guarded_keys = (
        "missing_positions", "node_overlaps", "group_overlaps", "through_nodes",
        "through_groups", "through_labels", "line_overlaps", "backward_edges",
        "inlet_order_mismatches", "crossings", "label_clips", "bent_chain_edges",
    )

    def guarded_counts(metrics: dict[str, Any]) -> tuple[float, ...]:
        counts: list[float] = []
        for key in guarded_keys:
            value = metrics.get(key)
            counts.append(float(len(value)) if isinstance(value, list) else float(value or 0))
        return tuple(counts)

    def parent_id(node: dict[str, Any]) -> Any:
        return (node.get("canvasConfig") or {}).get("parentId")

    def inside_parent_bottom(node: dict[str, Any]) -> bool:
        pid = parent_id(node)
        frame = by_id.get(pid)
        if frame is None:
            return True
        node_pos = lm.absolute_position(node, by_id)
        frame_pos = lm.absolute_position(frame, by_id)
        if node_pos is None or frame_pos is None:
            return False
        frame_h = ((frame.get("config") or {}).get("height") or 0)
        return node_pos[1] + NODE_HEIGHT + lm.label_extent(node)[2] <= frame_pos[1] + frame_h - 8.0

    moved_targets: set[str] = set()
    for edge in lm.iter_edges(nodes):
        src_id, target_id, _inlet = edge
        if target_id in moved_targets:
            continue
        src = by_id.get(src_id)
        target = by_id.get(target_id)
        if src is None or target is None:
            continue
        if src.get("type") in {"group", "text", "outlet"} \
                or target.get("type") in {"group", "text", "outlet"}:
            continue
        physical_inlets = [i for i in target.get("inlets") or [] if isinstance(i, dict)]
        if len(physical_inlets) <= 1 or in_degree.get(target_id, 0) <= 1:
            continue
        if out_degree.get(src_id, 0) != 1 or parent_id(src) != parent_id(target):
            continue
        src_pos = lm.absolute_position(src, by_id)
        target_pos = lm.absolute_position(target, by_id)
        ports = lm.edge_ports(edge, by_id)
        if src_pos is None or target_pos is None or ports is None:
            continue
        if abs(src_pos[1] - target_pos[1]) > 1.0:
            continue
        before_delta = abs(ports[0][1] - ports[1][1])
        if before_delta < 1.0 or before_delta > 32.0:
            continue

        old_y = target["position"]["y"]
        delta = ports[0][1] - ports[1][1]
        before = lm.measure(nodes)
        before_guarded = guarded_counts(before)
        target["position"]["y"] = old_y + delta
        after = lm.measure(nodes)
        after_ports = lm.edge_ports(edge, by_id)
        after_delta = abs(after_ports[0][1] - after_ports[1][1]) if after_ports else before_delta
        if inside_parent_bottom(target) \
                and all(a <= b for a, b in zip(guarded_counts(after), before_guarded)) \
                and after_delta < before_delta:
            moved_targets.add(target_id)
            continue
        target["position"]["y"] = old_y


def _edge_parent(node_id: str, by_id: dict[str, dict[str, Any]]) -> str | None:
    node = by_id.get(node_id)
    if node is None:
        return None
    parent = _parent_id(node)
    if not parent and node.get("type") == "outlet" and "|" in str(node_id):
        source = by_id.get(str(node_id).partition("|")[0])
        if source is not None:
            parent = _parent_id(source)
    return parent


def _shift_room_y(nodes: list[dict[str, Any]], room: dict[str, Any], dy: float) -> None:
    if not isinstance(room.get("position"), dict):
        return
    room["position"]["y"] += dy
    member_ids = {n["id"] for n in nodes if _parent_id(n) == room["id"]}
    for n in nodes:
        if n.get("type") == "outlet" and _parent_id(n) is None \
                and str(n.get("id")).partition("|")[0] in member_ids \
                and isinstance(n.get("position"), dict):
            n["position"]["y"] += dy


def _corridor_room_pressure(nodes: list[dict[str, Any]]) -> list[tuple[float, str, float]]:
    """Rooms that sit too close to long connector corridors.

    A long connector may be technically clear while visually skirting a nearby unrelated
    room. That reads as the connector routing around the room. Return the missing clearance
    and the smallest y-shift that restores the normal room gap.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    groups = [
        n for n in nodes
        if n.get("type") == "group"
        and isinstance(n.get("id"), str)
        and isinstance(n.get("position"), dict)
        and isinstance((n.get("config") or {}).get("width"), (int, float))
        and isinstance((n.get("config") or {}).get("height"), (int, float))
    ]
    pressure_by_group: dict[str, tuple[float, float]] = {}
    for edge in lm.iter_edges(nodes):
        ports = lm.edge_ports(edge, by_id)
        if ports is None:
            continue
        p1, p2 = ports
        if p2[0] - p1[0] < COL_DX * 2:
            continue
        poly = lm.edge_polyline(p1, p2)
        x1, y1, x2, y2 = (
            min(p[0] for p in poly),
            min(p[1] for p in poly),
            max(p[0] for p in poly),
            max(p[1] for p in poly),
        )
        src_parent = _edge_parent(edge[0], by_id)
        target_parent = _edge_parent(edge[1], by_id)
        for group in groups:
            gid = group["id"]
            if gid in {src_parent, target_parent}:
                continue
            gx1 = float(group["position"]["x"])
            gy1 = float(group["position"]["y"])
            gx2 = gx1 + float(group["config"]["width"])
            gy2 = gy1 + float(group["config"]["height"])
            if gx2 <= x1 or gx1 >= x2:
                continue
            # Hard intersections are handled by the normal measured repair path; this pass
            # only restores clearance for corridors that narrowly pass above/below a room.
            if gy1 < y2 and gy2 > y1:
                continue
            if gy2 <= y1:
                clearance = y1 - gy2
                shift = -(CORRIDOR_ROOM_GAP - clearance)
            else:
                clearance = gy1 - y2
                shift = CORRIDOR_ROOM_GAP - clearance
            missing = CORRIDOR_ROOM_GAP - clearance
            if missing <= 1.0:
                continue
            old = pressure_by_group.get(gid)
            if old is None or missing > old[0]:
                pressure_by_group[gid] = (missing, shift)
    return [
        (missing, gid, shift)
        for gid, (missing, shift) in sorted(pressure_by_group.items(), key=lambda item: -item[1][0])
    ]


def _nudge_corridor_blocking_groups(nodes: list[dict[str, Any]]) -> list[str]:
    """Move unrelated rooms away from long connector corridors when there is free space."""
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    changed: list[str] = []

    def guard(metrics: dict[str, Any]) -> tuple[float, ...]:
        score = lm.score(metrics)
        return (
            score.missing_positions,
            score.collisions,
            score.through_nodes,
            score.through_groups,
            score.through_labels,
            score.line_overlaps,
            score.backward_edges,
            score.inlet_order,
            score.crossings,
            score.label_clips,
            score.bent_chains,
        )

    for _ in range(8):
        pressures = _corridor_room_pressure(nodes)
        if not pressures:
            break
        before = lm.measure(nodes)
        before_guard = guard(before)
        before_pressure = sum(p[0] for p in pressures)
        improved = False
        for missing, gid, shift in pressures:
            room = by_id.get(gid)
            if room is None or not isinstance(room.get("position"), dict):
                continue
            old_y = room["position"]["y"]
            outlet_positions = {
                n["id"]: n["position"]["y"]
                for n in nodes
                if n.get("type") == "outlet"
                and _parent_id(n) is None
                and isinstance(n.get("id"), str)
                and isinstance(n.get("position"), dict)
                and str(n.get("id")).partition("|")[0] in {
                    member["id"] for member in nodes if _parent_id(member) == gid
                }
            }
            _shift_room_y(nodes, room, shift)
            after = lm.measure(nodes)
            after_pressure = sum(p[0] for p in _corridor_room_pressure(nodes))
            if guard(after) <= before_guard and after_pressure < before_pressure - 1.0:
                changed.append(f"corridor-room-gap:{room.get('name') or gid}:{int(round(shift))}")
                improved = True
                break
            room["position"]["y"] = old_y
            for n in nodes:
                nid = n.get("id")
                if nid in outlet_positions and isinstance(n.get("position"), dict):
                    n["position"]["y"] = outlet_positions[nid]
        if not improved:
            break
    return changed


def _realign_group_branch_outlets(nodes: list[dict[str, Any]], group_id: str) -> None:
    """Keep split/blend branch markers on the rows their consumers render on.

    Row repair moves body nodes after the main outlet placement pass has already run. If
    branch markers keep their stale y, the metric correctly sees artificial crossings. This
    mirrors the primary placement rule: a branch marker belongs near the target port it feeds,
    with sibling labels kept clear.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    group = by_id.get(group_id)
    if group is None or not isinstance(group.get("position"), dict):
        return
    group_y = float(group["position"]["y"])
    member_ids = {
        n["id"] for n in nodes
        if _parent_id(n) == group_id and isinstance(n.get("id"), str)
    }
    by_base: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for node in nodes:
        if node.get("type") != "outlet" or "|" not in str(node.get("id")):
            continue
        base, _, idx = str(node["id"]).partition("|")
        if base not in member_ids or not idx.isdigit() or not isinstance(node.get("position"), dict):
            continue
        by_base.setdefault(base, []).append((int(idx), node))

    for base, items in by_base.items():
        desired: dict[str, float] = {}
        for _idx, outlet in items:
            target_rows: list[float] = []
            for out in outlet.get("outlets") or []:
                if not isinstance(out, dict):
                    continue
                for target_ref in out.get("targets") or []:
                    if not isinstance(target_ref, dict):
                        continue
                    target = by_id.get(target_ref.get("target"))
                    if target is None or not isinstance(target.get("position"), dict):
                        continue
                    target_pos = lm.absolute_position(target, by_id)
                    if target_pos is None:
                        continue
                    inlet = str(target_ref.get("targetInlet") or "in_0")
                    target_rows.append(
                        target_pos[1]
                        + input_port_y_offset(target, inlet, str(outlet["id"]))
                        - lm.OUTLET_HEIGHT / 2
                        - group_y
                    )
            desired[outlet["id"]] = min(target_rows) if target_rows else float(outlet["position"]["y"])

        ordered = sorted(items, key=lambda item: desired[item[1]["id"]])
        placed: dict[str, float] = {}
        last: float | None = None
        last_node: dict[str, Any] | None = None
        for _idx, outlet in ordered:
            row = desired[outlet["id"]]
            if last is not None and last_node is not None:
                row = max(row, last + _outlet_sibling_gap(last_node))
            placed[outlet["id"]] = row
            last = row
            last_node = outlet
        if ordered:
            preferred_avg = sum(desired[outlet["id"]] for _idx, outlet in ordered) / len(ordered)
            placed_avg = sum(placed[outlet["id"]] for _idx, outlet in ordered) / len(ordered)
            shift = preferred_avg - placed_avg
            for _idx, outlet in ordered:
                outlet["position"]["y"] = placed[outlet["id"]] + shift


def _repair_in_group_row_crossings(nodes: list[dict[str, Any]]) -> list[str]:
    """Try small in-room row reassignments that remove connector crossings.

    The planner assigns rows locally from graph depth. A common human fix is to slide a
    source row into open space between two existing rows so a long upward connector stops
    cutting through a split branch. This pass explores only the group(s) participating in
    measured crossings and accepts the best candidate only when the shared layout score
    improves and no hard containment/overlap defect is introduced.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    before = lm.measure(nodes)
    if not before.get("crossings"):
        return []

    hard_keys = (
        "missing_positions", "node_overlaps", "group_overlaps", "through_nodes",
        "through_groups", "through_labels", "line_overlaps", "backward_edges",
        "label_clips",
    )

    def hard_counts(metrics: dict[str, Any]) -> tuple[float, ...]:
        counts: list[float] = []
        for key in hard_keys:
            value = metrics.get(key)
            counts.append(float(len(value)) if isinstance(value, list) else float(value or 0))
        return tuple(counts)

    def visual_group(edge_node_id: str) -> str | None:
        node = by_id.get(edge_node_id)
        if node is None:
            return None
        parent = _parent_id(node)
        if parent:
            return parent
        if node.get("type") == "outlet" and "|" in edge_node_id:
            source = by_id.get(edge_node_id.partition("|")[0])
            if source is not None:
                return _parent_id(source)
        return None

    candidate_groups: set[str] = set()
    for edge_a, edge_b in before.get("crossings") or []:
        groups = {visual_group(edge_a[0]), visual_group(edge_a[1]), visual_group(edge_b[0]), visual_group(edge_b[1])}
        groups.discard(None)
        if len(groups) == 1:
            candidate_groups.update(g for g in groups if g)

    def snapshot() -> dict[str, dict[str, Any]]:
        saved: dict[str, dict[str, Any]] = {}
        for n in nodes:
            nid = n.get("id")
            if isinstance(nid, str) and isinstance(n.get("position"), dict):
                saved[nid] = {"position": dict(n["position"])}
                if n.get("type") == "group" and isinstance(n.get("config"), dict):
                    saved[nid]["config"] = {
                        key: n["config"].get(key)
                        for key in ("width", "height", "currentHeight")
                        if key in n["config"]
                    }
        return saved

    def restore(saved: dict[str, dict[str, Any]]) -> None:
        for n in nodes:
            nid = n.get("id")
            if not isinstance(nid, str) or nid not in saved:
                continue
            if "position" in saved[nid]:
                n["position"] = dict(saved[nid]["position"])
            if "config" in saved[nid] and isinstance(n.get("config"), dict):
                for key, value in saved[nid]["config"].items():
                    n["config"][key] = value

    def grouped_units(group_id: str) -> list[list[dict[str, Any]]]:
        members = [
            n for n in nodes
            if _parent_id(n) == group_id and n.get("type") not in {"group", "text", "outlet"}
            and isinstance(n.get("position"), dict) and isinstance(n.get("id"), str)
        ]
        member_by_id = {n["id"]: n for n in members}
        parent: dict[str, str] = {n["id"]: n["id"] for n in members}

        def find(a: str) -> str:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        body_succs: dict[str, set[str]] = {}
        for src_id, target_id, _inlet in lm.iter_edges(nodes):
            base = src_id.partition("|")[0]
            if base in member_by_id and target_id in member_by_id:
                body_succs.setdefault(base, set()).add(target_id)

        for src_id, target_id, _inlet in lm.iter_edges(nodes):
            base = src_id.partition("|")[0]
            if base not in member_by_id or target_id not in member_by_id:
                continue
            src = member_by_id[base]
            target = member_by_id[target_id]
            if abs(float(src["position"]["y"]) - float(target["position"]["y"])) > 8.0:
                continue
            # Keep ordinary same-row chains together. For branch pseudo-nodes, keep the
            # branch marker's source with the same-row branch consumer, but do not pull a
            # later multi-input merge into that source row just because one branch continues.
            if "|" in src_id or len(body_succs.get(base) or ()) <= 1:
                union(base, target_id)

        buckets: dict[str, list[dict[str, Any]]] = {}
        for n in members:
            buckets.setdefault(find(n["id"]), []).append(n)
        return list(buckets.values())

    changed: list[str] = []
    for group_id in sorted(candidate_groups):
        group = by_id.get(group_id)
        if group is None or not isinstance(group.get("position"), dict) or not isinstance(group.get("config"), dict):
            continue
        units = grouped_units(group_id)
        if len(units) < 2 or len(units) > 6:
            continue
        current_rows = sorted({round(float(unit[0]["position"]["y"]), 3) for unit in units})
        row_slots = set(current_rows)
        for upper, lower in zip(current_rows, current_rows[1:]):
            gap = lower - upper
            if gap >= NODE_HEIGHT + MIN_GAP_Y:
                row_slots.add(round((upper + lower) / 2.0, 3))
        row_slots = {
            row for row in row_slots
            if row >= HEADER_CONTENT_TOP_MIN
            and row + NODE_HEIGHT + PAD_BOT <= float(group["config"].get("height") or 0.0)
        }
        if len(row_slots) < 2 or len(row_slots) > 8:
            continue

        saved_before_group = snapshot()
        best_saved: dict[str, dict[str, Any]] | None = None
        best_metrics = before
        best_score = lm.score(before)
        best_hard = hard_counts(before)
        # Search deterministic row slots. Units keep their internal same-row shape.
        import itertools
        for assignment in itertools.product(sorted(row_slots), repeat=len(units)):
            if all(abs(float(unit[0]["position"]["y"]) - row) < 0.5 for unit, row in zip(units, assignment)):
                continue
            restore(saved_before_group)
            for unit, row in zip(units, assignment):
                delta = row - float(unit[0]["position"]["y"])
                for node in unit:
                    node["position"]["y"] = float(node["position"]["y"]) + delta
            _realign_group_branch_outlets(nodes, group_id)
            metrics = lm.measure(nodes)
            score = lm.score(metrics)
            if hard_counts(metrics) <= best_hard and score < best_score:
                best_score = score
                best_metrics = metrics
                best_saved = snapshot()

        restore(best_saved or saved_before_group)
        if best_saved is not None and lm.score(best_metrics) < lm.score(before):
            before = best_metrics
            changed.append(f"row-crossing-repair:{group.get('name') or group_id}")
        else:
            restore(saved_before_group)
    return changed


def _hard_defects(metrics: dict[str, Any]) -> int:
    return (
        len(metrics.get("through_nodes") or [])
        + len(metrics.get("through_groups") or [])
        + len(metrics.get("through_labels") or [])
        + len(metrics.get("line_overlaps") or [])
        + len(metrics.get("backward_edges") or [])
        + len(metrics.get("node_overlaps") or [])
        + len(metrics.get("group_overlaps") or [])
        + len(metrics.get("inlet_order_mismatches") or [])
    )


def _same_row_chain(node: dict[str, Any], nodes: list[dict[str, Any]],
                    by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The node plus its single-linked same-row chain neighbors, walked both ways."""
    out_map: dict[str, list[str]] = {}
    in_map: dict[str, list[str]] = {}
    for src, dst, _inlet in lm.iter_edges(nodes):
        base = str(src).partition("|")[0]
        out_map.setdefault(base, []).append(dst)
        in_map.setdefault(dst, []).append(base)

    def same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
        pa, pb = a.get("position") or {}, b.get("position") or {}
        return (
            _parent_id(a) == _parent_id(b)
            and abs(float(pa.get("y", 0)) - float(pb.get("y", 1e9))) < 8.0
        )

    members = [node]
    seen = {node.get("id")}
    frontier = [node]
    while frontier:
        cur = frontier.pop()
        cid = cur.get("id")
        links: list[str] = []
        if len(out_map.get(cid) or []) == 1:
            target_id = out_map[cid][0]
            if len(in_map.get(target_id) or []) == 1:
                links.append(target_id)
        if len(in_map.get(cid) or []) == 1:
            source_id = in_map[cid][0]
            if len(out_map.get(source_id) or []) == 1:
                links.append(source_id)
        for other_id in links:
            other = by_id.get(other_id)
            if other is None or other_id in seen or other.get("type") in {"group", "text", "outlet"}:
                continue
            if same_row(cur, other):
                seen.add(other_id)
                members.append(other)
                frontier.append(other)
    return members


def _repair_measured_defects(nodes: list[dict[str, Any]]) -> list[str]:
    """Bounded repair for measured hard defects, owned by the solver path.

    This is not a second auto-layout strategy: it is the solver's final local search over
    defects reported by `layout_metrics`. Accepted moves must improve the correctness tier.
    """
    by_id = {node.get("id"): node for node in nodes if isinstance(node.get("id"), str)}

    def shift(node: dict[str, Any], dx: float, dy: float) -> None:
        pos = node.get("position") or {}
        node["position"] = {
            "x": float(pos.get("x", 0.0)) + dx,
            "y": float(pos.get("y", 0.0)) + dy,
        }

    reject = object()

    def snapshot_geometry() -> dict[str, dict[str, Any]]:
        saved: dict[str, dict[str, Any]] = {}
        for n in nodes:
            nid = n.get("id")
            if not isinstance(nid, str):
                continue
            entry: dict[str, Any] = {}
            if isinstance(n.get("position"), dict):
                entry["position"] = dict(n["position"])
            if n.get("type") == "group" and isinstance(n.get("config"), dict):
                entry["config"] = {
                    key: n["config"].get(key)
                    for key in ("width", "height", "currentHeight")
                    if key in n["config"]
                }
            if entry:
                saved[nid] = entry
        return saved

    def restore_geometry(saved: dict[str, dict[str, Any]]) -> None:
        for n in nodes:
            nid = n.get("id")
            if not isinstance(nid, str) or nid not in saved:
                continue
            entry = saved[nid]
            if "position" in entry:
                n["position"] = dict(entry["position"])
            if "config" in entry and isinstance(n.get("config"), dict):
                for key, value in entry["config"].items():
                    n["config"][key] = value

    def visual_parent_id(node: dict[str, Any]) -> str | None:
        parent = _parent_id(node)
        if parent:
            return parent
        if node.get("type") == "outlet" and "|" in str(node.get("id")):
            base = str(node["id"]).partition("|")[0]
            source = by_id.get(base)
            if source is not None:
                return _parent_id(source)
        return None

    def rewrap(parent_id: str | None):
        if not parent_id or parent_id not in by_id:
            return None
        group = by_id[parent_id]
        config = group.get("config")
        if not isinstance(config, dict) or not isinstance(group.get("position"), dict):
            return None
        member_ids = {
            n["id"] for n in nodes
            if _parent_id(n) == parent_id and n.get("type") not in {"group", "text", "outlet"}
            and isinstance(n.get("id"), str)
        }
        members = [
            n for n in nodes
            if _parent_id(n) == parent_id and n.get("type") != "text"
            and isinstance(n.get("position"), dict)
        ]
        members.extend(
            n for n in nodes
            if n.get("type") == "outlet" and _parent_id(n) is None
            and str(n.get("id")).partition("|")[0] in member_ids
            and isinstance(n.get("position"), dict)
        )
        if not members:
            return None

        def local_position(n: dict[str, Any]) -> tuple[float, float]:
            pos = _position(n) or {"x": 0.0, "y": 0.0}
            if _parent_id(n) == parent_id:
                return pos["x"], pos["y"]
            # Parentless outlet marker that visually belongs to this source room.
            return pos["x"] - float(group["position"]["x"]), pos["y"] - float(group["position"]["y"])

        def shift_frame(dx: float, dy: float) -> None:
            group["position"]["x"] -= dx
            group["position"]["y"] -= dy
            for child in nodes:
                if _parent_id(child) == parent_id and child.get("type") != "text" \
                        and isinstance(child.get("position"), dict):
                    child["position"]["x"] += dx
                    child["position"]["y"] += dy

        top = min(local_position(m)[1] for m in members)
        left = min(local_position(m)[0] for m in members)
        shift_frame(max(PAD_X / 2 - left, 0.0), max(HEADER_CONTENT_TOP_MIN - top, 0.0))

        bottom = 0.0
        right = 0.0
        for m in members:
            x, y = local_position(m)
            if m.get("type") == "outlet":
                _lo, label_right, label_band = lm.label_extent(m)
                right = max(right, x + lm.OUTLET_WIDTH + PAD_X, x + label_right + LABEL_MARGIN)
                bottom = max(bottom, y + lm.OUTLET_HEIGHT + label_band + PAD_BOT)
            else:
                _lo, label_right, label_band = lm.label_extent(m)
                right = max(right, x + BODY_W + PAD_X, x + label_right + LABEL_MARGIN)
                bottom = max(bottom, y + NODE_HEIGHT + label_band + PAD_BOT)
        config["height"] = max(float(config.get("height") or 0.0), bottom)
        config["width"] = max(float(config.get("width") or 0.0), right)
        return True

    changed: list[str] = []
    metrics = lm.measure(nodes)
    best = lm.score(metrics)
    moves = 0

    def visible_guard(metrics: dict[str, Any]) -> tuple[int, int]:
        return (
            len(metrics.get("label_clips") or []),
            len(metrics.get("bent_chain_edges") or []),
        )

    def crossing_guard(before: dict[str, Any], after: dict[str, Any]) -> bool:
        before_crossings = len(before.get("crossings") or [])
        after_crossings = len(after.get("crossings") or [])
        if after_crossings <= before_crossings:
            return True
        return len(after.get("through_groups") or []) < len(before.get("through_groups") or [])

    while _hard_defects(metrics) > 0 and moves < REPAIR_MAX_MOVES:
        defects: list[tuple[str, ...]] = list(metrics.get("through_nodes") or [])
        defects += list(metrics.get("through_groups") or [])
        defects += list(metrics.get("through_labels") or [])
        defects += list(metrics.get("backward_edges") or [])
        defects += list(metrics.get("node_overlaps") or [])
        defects += [
            (row[1], row[-1], row[0])
            for row in metrics.get("inlet_order_mismatches") or []
            if len(row) >= 3
        ]
        improved = False
        for defect in defects:
            candidates = [defect[2], defect[0], defect[1]] if len(defect) >= 3 else list(defect[:2])[::-1]
            for nid in candidates:
                node = by_id.get(str(nid))
                if node is None or node.get("type") in {"group", "text"}:
                    continue
                unit = _same_row_chain(node, nodes, by_id)
                for dx_steps, dy_steps in (
                    (0, 1), (0, -1), (0, 2), (0, -2), (0, 3), (0, -3),
                    (1, 0), (1, 1), (1, -1),
                    (2, 0), (2, 1), (2, -1), (-1, 0),
                ):
                    dx, dy = dx_steps * REPAIR_STEP_X, dy_steps * REPAIR_STEP
                    movers = unit if dy and not dx else [node]
                    saved = snapshot_geometry()
                    for m in movers:
                        shift(m, dx, dy)
                    frame_before = rewrap(visual_parent_id(node))
                    if frame_before is not reject:
                        candidate_metrics = lm.measure(nodes)
                        candidate = lm.score(candidate_metrics)
                        if (
                            candidate.correctness < best.correctness
                            and len(candidate_metrics["backward_edges"]) <= len(metrics["backward_edges"])
                            and visible_guard(candidate_metrics) <= visible_guard(metrics)
                            and crossing_guard(metrics, candidate_metrics)
                        ):
                            best, metrics = candidate, candidate_metrics
                            changed.append(f"measure-repair:{node.get('name') or nid}:{int(dx)},{int(dy)}")
                            improved = True
                            break
                    restore_geometry(saved)
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
        moves += 1
    return changed


def _compact_terminal_output_groups(nodes: list[dict[str, Any]]) -> None:
    """Pull terminal rooms toward the house center when a small blocker nudge keeps corridors clean."""
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    terminal_ids = lm.terminal_destination_group_ids(nodes)
    groups = [
        n for n in nodes
        if n.get("type") == "group"
        and isinstance(n.get("position"), dict)
        and isinstance((n.get("config") or {}).get("height"), (int, float))
    ]
    if not terminal_ids or not groups:
        return

    axis_candidates = [g for g in groups if g["id"] not in terminal_ids]
    if not axis_candidates:
        return
    axis_group = max(axis_candidates, key=lambda g: (g.get("config") or {}).get("height") or 0.0)
    axis = axis_group["position"]["y"] + axis_group["config"]["height"] / 2.0

    guarded_keys = (
        "missing_positions", "node_overlaps", "group_overlaps", "through_nodes",
        "through_groups", "through_labels", "line_overlaps", "backward_edges",
        "inlet_order_mismatches", "crossings", "label_clips", "bent_chain_edges",
    )

    def guarded_counts(metrics: dict[str, Any]) -> tuple[float, ...]:
        counts: list[float] = []
        for key in guarded_keys:
            value = metrics.get(key)
            counts.append(float(len(value)) if isinstance(value, list) else float(value or 0))
        return tuple(counts)

    def snapshot() -> dict[str, tuple[float, float]]:
        return {
            n["id"]: (n["position"]["x"], n["position"]["y"])
            for n in nodes
            if isinstance(n.get("id"), str) and isinstance(n.get("position"), dict)
        }

    def restore(saved: dict[str, tuple[float, float]]) -> None:
        for n in nodes:
            nid = n.get("id")
            if nid in saved and isinstance(n.get("position"), dict):
                n["position"]["x"], n["position"]["y"] = saved[nid]

    def shift(room: dict[str, Any], dy: float) -> None:
        room["position"]["y"] += dy

    terminal_groups = sorted(
        (g for g in groups if g["id"] in terminal_ids),
        key=lambda g: g["position"]["x"],
    )
    for room in terminal_groups:
        current_center = room["position"]["y"] + room["config"]["height"] / 2.0
        dy = axis - current_center
        if abs(dy) < 1.0:
            continue

        before = lm.measure(nodes)
        before_guarded = guarded_counts(before)
        before_score = lm.score(before)
        original = snapshot()
        best: tuple[tuple[Any, float], list[tuple[dict[str, Any], float]]] | None = None

        def center_gap() -> float:
            return abs(axis - (room["position"]["y"] + room["config"]["height"] / 2.0))

        def try_moves(moves: list[tuple[dict[str, Any], float]]) -> None:
            nonlocal best
            restore(original)
            for candidate_room, candidate_dy in moves:
                shift(candidate_room, candidate_dy)
            metrics = lm.measure(nodes)
            if not all(a <= b for a, b in zip(guarded_counts(metrics), before_guarded)):
                return
            score = lm.score(metrics)
            if score > before_score:
                return
            key = (score, center_gap())
            if best is None or key < best[0]:
                best = (key, moves)

        exact = [(room, dy)]
        try_moves(exact)

        restore(original)
        shift(room, dy)
        exact_metrics = lm.measure(nodes)
        blocker_ids = {
            group_id
            for _src, _target, group_id in exact_metrics.get("through_groups") or []
            if group_id not in {room["id"], axis_group["id"]}
            and group_id in by_id
            and by_id[group_id].get("type") == "group"
            and isinstance(by_id[group_id].get("position"), dict)
        }
        restore(original)
        nudge_direction = -1.0 if dy < 0 else 1.0
        for blocker_id in sorted(blocker_ids):
            blocker = by_id[blocker_id]
            for step in (15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0):
                if step <= abs(dy) + 0.1:
                    try_moves(exact + [(blocker, nudge_direction * step)])

        for fraction in (0.95, 0.875, 0.75, 0.5, 0.25):
            try_moves([(room, dy * fraction)])

        restore(original)
        if best is not None:
            for candidate_room, candidate_dy in best[1]:
                shift(candidate_room, candidate_dy)


def _stretch_terminal_output_groups_for_straight_feeds(nodes: list[dict[str, Any]]) -> None:
    """Use free vertical room slack to straighten terminal output feeds.

    If the house height is already set by another room, a terminal room can grow within that
    height at no canvas-area cost. Use that slack to place output rows on their incoming port
    lines, carrying same-row terminal chains with them.
    """
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    terminal_ids = lm.terminal_destination_group_ids(nodes)
    groups = [
        n for n in nodes
        if n.get("type") == "group"
        and isinstance(n.get("position"), dict)
        and isinstance((n.get("config") or {}).get("height"), (int, float))
    ]
    if not terminal_ids or not groups:
        return
    house_top = min(g["position"]["y"] for g in groups)
    house_bottom = max(g["position"]["y"] + g["config"]["height"] for g in groups)
    axis_candidates = [g for g in groups if g["id"] not in terminal_ids]
    if not axis_candidates:
        return
    axis_group = max(axis_candidates, key=lambda g: (g.get("config") or {}).get("height") or 0.0)
    axis = axis_group["position"]["y"] + axis_group["config"]["height"] / 2.0

    guarded_keys = (
        "missing_positions", "node_overlaps", "group_overlaps", "through_nodes",
        "through_groups", "through_labels", "line_overlaps", "backward_edges",
        "inlet_order_mismatches", "crossings", "label_clips", "bent_chain_edges",
    )

    def guarded_counts(metrics: dict[str, Any]) -> tuple[float, ...]:
        counts: list[float] = []
        for key in guarded_keys:
            value = metrics.get(key)
            counts.append(float(len(value)) if isinstance(value, list) else float(value or 0))
        return tuple(counts)

    def snapshot() -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
        positions = {
            n["id"]: (n["position"]["x"], n["position"]["y"])
            for n in nodes
            if isinstance(n.get("id"), str) and isinstance(n.get("position"), dict)
        }
        heights = {
            g["id"]: float(g["config"]["height"])
            for g in groups
        }
        return positions, heights

    def restore(saved: tuple[dict[str, tuple[float, float]], dict[str, float]]) -> None:
        positions, heights = saved
        for n in nodes:
            nid = n.get("id")
            if nid in positions and isinstance(n.get("position"), dict):
                n["position"]["x"], n["position"]["y"] = positions[nid]
            if nid in heights and n.get("type") == "group":
                n.setdefault("config", {})["height"] = heights[nid]

    def same_row_chain(start: dict[str, Any], group_id: str) -> list[dict[str, Any]]:
        out_map: dict[str, list[str]] = {}
        in_map: dict[str, list[str]] = {}
        for src, dst, _inlet in lm.iter_edges(nodes):
            base = str(src).partition("|")[0]
            out_map.setdefault(base, []).append(dst)
            in_map.setdefault(dst, []).append(base)

        def same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
            return (
                _parent_id(a) == group_id
                and _parent_id(b) == group_id
                and isinstance(a.get("position"), dict)
                and isinstance(b.get("position"), dict)
                and abs(float(a["position"]["y"]) - float(b["position"]["y"])) < 8.0
            )

        members = [start]
        seen = {start.get("id")}
        frontier = [start]
        while frontier:
            cur = frontier.pop()
            cid = cur.get("id")
            links: list[str] = []
            if len(out_map.get(cid) or []) == 1:
                target_id = out_map[cid][0]
                if len(in_map.get(target_id) or []) == 1:
                    links.append(target_id)
            if len(in_map.get(cid) or []) == 1:
                source_id = in_map[cid][0]
                if len(out_map.get(source_id) or []) == 1:
                    links.append(source_id)
            for other_id in links:
                other = by_id.get(other_id)
                if other is None or other_id in seen or other.get("type") in {"group", "text", "outlet"}:
                    continue
                if same_row(cur, other):
                    seen.add(other_id)
                    members.append(other)
                    frontier.append(other)
        return members

    def center_room_frame_around_axis(room: dict[str, Any]) -> bool:
        children = [
            n for n in nodes
            if _parent_id(n) == room["id"]
            and n.get("type") not in {"group", "text"}
            and isinstance(n.get("position"), dict)
        ]
        if not children:
            return True
        old_top = float(room["position"]["y"])
        required_abs_bottom = max(
            old_top + n["position"]["y"] + lm.BODY_H + lm.label_extent(n)[2] + PAD_BOT
            for n in children
        )
        required_content_top = min(
            old_top + n["position"]["y"] - CONTENT_TOP
            for n in children
        )
        required_height = max(
            float(room["config"]["height"]),
            2.0 * (required_abs_bottom - axis),
            2.0 * (axis - required_content_top),
        )
        max_centered_height = 2.0 * min(axis - house_top, house_bottom - axis)
        if required_height > max_centered_height + 0.5:
            return False
        new_top = axis - required_height / 2.0
        if new_top < house_top - 0.5 or new_top + required_height > house_bottom + 0.5:
            return False
        top_delta = new_top - old_top
        room["position"]["y"] = new_top
        room["config"]["height"] = required_height
        # Keep furniture on the straight connector rows while the frame grows around it.
        for child in children:
            child["position"]["y"] -= top_delta
        return True

    for room in sorted((g for g in groups if g["id"] in terminal_ids), key=lambda g: g["position"]["x"]):
        max_centered_height = 2.0 * min(axis - house_top, house_bottom - axis)
        if max_centered_height <= room["config"]["height"] + 1.0:
            continue
        member_ids = {
            n["id"] for n in nodes
            if _parent_id(n) == room["id"] and n.get("type") not in {"group", "text", "outlet"}
        }
        incoming = [
            edge for edge in lm.iter_edges(nodes)
            if edge[1] in member_ids and str(edge[0]).partition("|")[0] not in member_ids
        ]
        for edge in incoming:
            src_id, target_id, inlet = edge
            src = by_id.get(src_id)
            target = by_id.get(target_id)
            if src is None or target is None or not isinstance(target.get("position"), dict):
                continue
            ports = lm.edge_ports(edge, by_id)
            if ports is None:
                continue
            before_delta = abs(ports[0][1] - ports[1][1])
            if before_delta <= 1.0:
                continue
            desired_target_y = (
                ports[0][1]
                - room["position"]["y"]
                - input_port_y_offset(target, inlet, src_id)
            )
            delta = desired_target_y - target["position"]["y"]
            if abs(delta) < 1.0:
                continue
            unit = same_row_chain(target, room["id"])
            saved = snapshot()
            before = lm.measure(nodes)
            before_guarded = guarded_counts(before)
            before_score = lm.score(before)
            for node in unit:
                node["position"]["y"] += delta
            if not center_room_frame_around_axis(room):
                restore(saved)
                continue
            after = lm.measure(nodes)
            after_ports = lm.edge_ports(edge, by_id)
            after_delta = abs(after_ports[0][1] - after_ports[1][1]) if after_ports else before_delta
            if all(a <= b for a, b in zip(guarded_counts(after), before_guarded)) \
                    and lm.score(after) <= before_score \
                    and after.get("total_edge_length", 0.0) <= before.get("total_edge_length", 0.0) \
                    and after_delta < before_delta:
                continue
            restore(saved)


def solve(nodes: list[dict[str, Any]]) -> list[str]:
    """Compute the layout plan and place every body node, outlet, and group frame.

    Discrete layout HYPOTHESES (relocating far source streams; the junction-order chain
    fallback) are measured, not assumed: every combination is solved and scored, and the
    best layout wins — lane space cannot predict bezier crossings, so the metric decides.
    """
    probe = _Plan(nodes)
    if not probe.body:
        return []
    probe.compute_bands()
    original_parents = {n["id"]: (n.get("canvasConfig") or {}).get("parentId")
                        for n in nodes if isinstance(n.get("id"), str)}
    moved = probe.relocate_far_source_streams()
    relocated_parents = {n["id"]: (n.get("canvasConfig") or {}).get("parentId")
                        for n in nodes if isinstance(n.get("id"), str)}

    def _apply_parents(parents: dict[str, Any]) -> None:
        for n in nodes:
            nid = n.get("id")
            if nid in parents:
                cc = n.setdefault("canvasConfig", {})
                if parents[nid] is None:
                    cc.pop("parentId", None)
                else:
                    cc["parentId"] = parents[nid]

    reloc_notes = [
        f"regrouped:{count} step(s) moved from '{src}' into '{dst}' — "
        f"review both groups' and the workflow's descriptions with the user and "
        f"update them as part of this same change"
        for count, src, dst in probe.relocations]
    parent_options = [(original_parents, [])]
    if moved:
        parent_options.append((relocated_parents, reloc_notes))

    best: tuple | None = None
    for parents, notes in parent_options:
        for jf in (True, False):
            for compress in (True, False):
                for bypass_merge in (True, False):
                    for side_tap_rise in (True, False):
                        _apply_parents(parents)
                        _plan_and_place(
                            nodes,
                            junction_fallback=jf,
                            room_compression=compress,
                            bypass_merge_spine=bypass_merge,
                            side_tap_can_rise=side_tap_rise,
                        )
                        score = lm.score(lm.measure(nodes))
                        if best is None or score < best[0]:
                            best = (score, parents, jf, compress, bypass_merge, side_tap_rise, notes)
    _apply_parents(best[1])
    _plan_and_place(
        nodes,
        junction_fallback=best[2],
        room_compression=best[3],
        bypass_merge_spine=best[4],
        side_tap_can_rise=best[5],
    )
    _compact_terminal_output_groups(nodes)
    _stretch_terminal_output_groups_for_straight_feeds(nodes)
    repair_changes = _repair_measured_defects(nodes)
    corridor_changes = _nudge_corridor_blocking_groups(nodes)
    _repair_multi_input_continuation_alignment(nodes)
    _repair_outlet_target_alignment(nodes)
    row_changes = _repair_in_group_row_crossings(nodes)
    if row_changes:
        _repair_outlet_target_alignment(nodes)
    return ["layout-solver"] + best[6] + repair_changes + corridor_changes + row_changes
