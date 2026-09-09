---
registry_summary: "A visual container only. It is used to group nodes together and is used to organize the workflow for ease of use. Has no data operations."
---

# group

## Business purpose

A visual container on the canvas — not a data operation. Groups exist purely to help the builder organize the flow visually, typically with a numbered-step label like "1. Extract from PDF" or "2. Compute State Sums". Child nodes live inside the group's bounds and their canvas positions become relative to the group. Groups have no inlets, no outlets, and do not transform data.

For the inspector, the visible labels inside groups are one of the strongest hints about builder intent — they're how the author tells the reader "these three nodes go together and achieve X." But the labels are not the group's `name` field — see the next note.

> **The group itself has no on-canvas label.** The `name` field on a group's JSON (e.g. `"group 1"`) is an internal auto-assigned placeholder; Savant does not render it on the canvas. To label a group visually, builders place a `text` node inside it (see `./text.md`). The standard generated header is one rich text node whose first line is the title and whose second content line is a short description, with different formatting per line encoded in `config.text` HTML. This can be generated directly in workflow JSON; it is not UI-only. When an inspector asks "what is this group called?", the answer comes from reading the text node whose `canvasConfig.parentId` equals the group's id, not from the group's own `name`.

For layout edits, treat a group as a semantic stage boundary, not just a rectangle. Before resizing or moving it for readability, infer what work the title says the group is framing, which nodes actually perform that work, and where the next stage begins. Propose that interpretation before editing so the layout change reflects the workflow's meaning rather than simply enclosing every nearby connected node.

For readability edits, apply the general standards in `../standards/canvas-layout-rules.md`; group-specific emphasis: use the title, description, and contained nodes to decide whether the group is a peer stage, side reference, output, exception, or review block.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/group.json`. This file focuses on behavior, writing, and gotchas.

## Building (use node_builders)

Don't hand-author group/membership/layout JSON. Use `Flow.group(name, members, header=..., description=..., color=None)`:

```python
f.group("Match statement charges to GL postings", [src, edit, filt],
        header="Match statement charges to GL postings",
        description="Matches charges to GL postings when the vendor matches, the amount is within "
                    "$0.01, and dates are within 5 days.\nKeeps the closest match when several "
                    "qualify and prevents reusing a line twice.")
```

It creates the frame + header text node, lays out the stage, and encodes membership ONLY in each member's `canvasConfig.parentId` — **never a top-level `parentId`, which collapses the layout on import**. Color defaults to a per-flow palette pick; pass `color="hsl(...)"` to override.

The `header` and `description` are **canvas rich text the builder renders, not Markdown** — pass plain business text. Use a real line break (`\n`) in the description to split dense clauses; numeric thresholds (`$0.01`, `5 days`, `5%`) are auto-emphasized. The header names the business phase in the user's words (business object + action — e.g. "Match statement charges to GL postings", not "Match the records" and not "Join"); the description explains the *logic and its thresholds*, not the step sequence. See `../standards/node-documentation-rules.md` ("Group Headers and Descriptions", "Step Labels") for the full standard. `**bold**` would render literally — do not use Markdown here.

## Invariants

- `inlets` and `outlets` must both be `[]`. Groups are not wired.
- Child membership is expressed on the CHILDREN (via `canvasConfig.parentId`), not on the group. A group node with no children is valid (empty group) but usually an authoring oversight.
- Child positions inside a group are relative, not absolute. A child with `parentId: "group_xxxxxx"` at position `(20, 20)` is 20px from the group's top-left, not canvas (20, 20).
- Changing a group's position moves all its children with it (positions are relative).
- Removing a group should re-parent its children by clearing `canvasConfig.parentId` / `extent`, or their positions will be wrong on next render.

## Interpretation

Group config is genuinely visual: the only editable fields are color and size. A group carries no user-facing name field — renaming a group is done by editing the `text` node that sits inside it, not the group's own `name`.

**Resolving a group's visible title** — the title is a `text` node placed inside the group's bounds. To answer "what is this group called?":

1. Enumerate text nodes in the flow JSON with `canvasConfig.parentId === groupId`.
2. If exactly one: its `config.inputText` is the group's title.
3. If multiple: the text node with the largest `config.fontSize` and/or positioned near the group's top-left is usually the title; the others are likely annotations / callouts. Surface all of them with positions if it's not obvious.
4. If zero: the group is unnamed. Say so explicitly rather than falling back to the internal `"group 1"` string — that name is not meant for display.

Child membership is read the same way: a node belongs to a group when its `canvasConfig.parentId` equals the group's id. This mapping is what lets an inspector summarize flow organization ("Group 1 contains the extraction nodes; its text label reads 'Extract from PDF'.").

## API edit support

Group edits are supported only when they can be represented as documented recipe JSON changes, such as position, size, color, and title text-node fields. Use `savant.py workflow edit` to save the recipe diff, then re-fetch with MCP `fetch` and run `savant.py workflow verify --operation edit --before-json` for persistence verification. Do not use mouse dragging, DOM edits, or store dispatches as live edit mechanisms. After an API save, reload and visually verify rendered group layout, child containment, connector routing, and text clipping. Extract-from-group, creating/deleting groups, and moving nodes into groups are unsupported unless an exact API recipe mutation is documented; otherwise use the downloader -> builder -> creator rebuild path.

## Gotchas

- **The visible title is a text node, not the group's `name`.** Step-title labels ("1. Extract from PDF") are text nodes inside the group; the group's own `name` is an internal identifier Savant doesn't render. Prioritize the text-node titles when orienting, and rename a group by editing that child text node (via API recipe diff), not the group `name`.
- **Groups don't appear in data-flow traversal.** When walking the DAG by inlets/outlets, groups are invisible — they have none. Don't let a group node confuse a path-finding algorithm.
- **Positional bugs after ungrouping.** If a group is deleted without clearing children's `parentId`, the children render at their (now stale) relative positions against (0, 0), which can throw them off-canvas.
