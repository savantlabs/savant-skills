"""Shared geometry constants and graph helpers for workflow layout.

The solver, polish arbiter, and metrics module each own different parts of layout.
This module holds the small vocabulary they can safely share without making the
plan solver responsible for every layout concern.
"""
from __future__ import annotations

from typing import Any

from workflow.geometry import NODE_HEIGHT, NODE_WIDTH
from workflow import layout_metrics as lm

# Minimum clear space between any two rendered elements.
MIN_GAP_X = 60.0
MIN_GAP_Y = 45.0

# Card and lane pitch.
COL_DX = NODE_WIDTH + 100.0
SPLIT_COL_DX = NODE_WIDTH + MIN_GAP_X + 48.0 + MIN_GAP_X
ROW_DY = NODE_HEIGHT + MIN_GAP_Y

# Group frame model.
HEADER_H = 116.0
FRAME_PAD = 48.0
CONTENT_TOP = HEADER_H + FRAME_PAD
PAD_X = FRAME_PAD
PAD_BOT = FRAME_PAD
# The enforced clear gap between room frames, BOTH axes. Packing and compaction set
# gaps to exactly this on real frame edges.
GROUP_FRAME_GAP = 60.0

# Canvas origin.
CANVAS_X0 = 40.0
CANVAS_Y0 = 40.0

# Label and outlet footprints.
BODY_W = lm.BODY_W
LABEL_MARGIN = 32.0
OUTLET_GAP = NODE_WIDTH + MIN_GAP_X
OUTLET_LABEL_CLEARANCE = 68.0
OUTLET_STEP = 48.0 + OUTLET_LABEL_CLEARANCE

# Cross-stage tap policy.
TAP_SPAN_COLUMNS = 3
TAP_CLEARANCE_LANES = 1.5

# Validator-facing layout thresholds. Keep canvas geometry here so the solver,
# metrics, and validator do not drift into separate box models.
GROUP_HEADER_TEXT_MIN_HEIGHT = int(HEADER_H)
GROUP_HEADER_BAND_MIN_Y = int(HEADER_H)
GROUPED_NODE_VISUAL_HEIGHT = NODE_HEIGHT
GROUPED_NODE_VERTICAL_ROW_GAP_MIN = int(ROW_DY)
GROUP_BOTTOM_PADDING_MIN = int(PAD_BOT)
PARALLEL_BUSINESS_LANE_MIN_GAP = 420
PARALLEL_BUSINESS_GROUP_MIN_HEIGHT = 850
GROUP_VISUAL_MEMBERSHIP_PADDING = 12
GROUP_SIDE_PADDING_MIN = int(PAD_X)
GROUP_COLUMN_GAP_MIN = int(MIN_GAP_X)
GROUP_WIDTH_EXTRA_ALLOWANCE = 280
GROUP_COLUMN_CLUSTER_TOLERANCE = 96
NODE_LABEL_GUTTER_MIN = int(LABEL_MARGIN)
GROUP_TOP_ALIGNMENT_TOLERANCE = 24
GROUP_HEIGHT_ALIGNMENT_TOLERANCE = 48
GROUP_HEIGHT_EXCESS_ALLOWANCE = 260
GROUP_HEIGHT_EXCESS_RATIO = 0.35
UNIFORM_LARGE_GROUP_HEIGHT_MIN = 850
UNIFORM_GROUP_EMPTY_RATIO_MIN = 0.25
GROUP_GUTTER_ALIGNMENT_TOLERANCE = 32
GROUP_GUTTER_MIN = int(GROUP_FRAME_GAP)
GROUP_GUTTER_MAX = 160
GROUP_CONTENT_CENTERING_TOLERANCE = 64
OUTPUT_GROUP_BELOW_MAIN_LANE_TOLERANCE = 220


def parent_id(node: dict[str, Any]) -> str | None:
    parent = (node.get("canvasConfig") or {}).get("parentId")
    return parent if isinstance(parent, str) and parent else None


def raw_edges(nodes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    ids = {n.get("id") for n in nodes}
    rows: list[tuple[str, str, str]] = []
    for src in nodes:
        for outlet in src.get("outlets") or []:
            if not isinstance(outlet, dict):
                continue
            for target in outlet.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                tid = target.get("target")
                if isinstance(tid, str) and tid in ids:
                    rows.append((str(src.get("id")), tid, str(target.get("targetInlet") or "in_0")))
    return rows


def inlet_rank(node: dict[str, Any], inlet: str, src_id: str) -> int:
    """Vertical order of this connection at the target: lower renders higher."""
    if node.get("type") == "multi_stack":
        inlets = [i for i in node.get("inlets") or [] if isinstance(i, dict)]
        if inlets:
            sources = [s for s in inlets[0].get("sources") or [] if isinstance(s, dict)]
            for index, s in enumerate(sources):
                if s.get("source") == src_id:
                    return index
    digits = "".join(ch for ch in inlet if ch.isdigit())
    return int(digits) if digits else 0
