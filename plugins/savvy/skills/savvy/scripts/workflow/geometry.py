"""Shared approximate Savant canvas geometry for builders and validators.

These values model the rendered node body closely enough for deterministic
layout and preflight checks. They are not a replacement for screenshot review.
"""

from __future__ import annotations

from typing import Any


NODE_WIDTH = 130
NODE_HEIGHT = 145
NODE_BODY_HEIGHT = 96

OUTPUT_Y = NODE_BODY_HEIGHT / 2
INPUT_SINGLE_Y = NODE_BODY_HEIGHT / 2
INPUT_MULTI_TOP_Y = 32
INPUT_MULTI_BOTTOM_Y = NODE_BODY_HEIGHT - 32

PORT_ALIGNMENT_TOLERANCE = 16
PORT_NEAR_MISS_TOLERANCE = 72
EXTERNAL_INPUT_LANDING_MIN = 180

LABEL_AVG_CHAR_WIDTH = 6.5
LABEL_WIDTH_MIN = 130
LABEL_WIDTH_MAX = 260


def inlet_index(inlet_id: str | None) -> int:
    if not inlet_id:
        return 0
    digits = ""
    for ch in reversed(inlet_id):
        if ch.isdigit():
            digits = ch + digits
        elif digits:
            break
    return int(digits) if digits else 0


def multi_port_y_offset(index: int, count: int) -> float:
    if count <= 1:
        return INPUT_SINGLE_Y
    if count == 2:
        return INPUT_MULTI_TOP_Y if index <= 0 else INPUT_MULTI_BOTTOM_Y
    usable_height = NODE_BODY_HEIGHT - (2 * INPUT_MULTI_TOP_Y)
    step = usable_height / max(count - 1, 1)
    return INPUT_MULTI_TOP_Y + min(max(index, 0), count - 1) * step


def input_port_y_offset(node: dict[str, Any], inlet_id: str | None = None, source_id: str | None = None) -> float:
    inlets = [inlet for inlet in node.get("inlets") or [] if isinstance(inlet, dict)]
    if len(inlets) <= 1:
        return INPUT_SINGLE_Y
    return multi_port_y_offset(inlet_index(inlet_id), len(inlets))


def output_port_y_offset(_node: dict[str, Any] | None = None) -> float:
    return OUTPUT_Y


def label_width_estimate(label: Any) -> float:
    text = str(label or "")
    return min(LABEL_WIDTH_MAX, max(LABEL_WIDTH_MIN, len(text) * LABEL_AVG_CHAR_WIDTH))
