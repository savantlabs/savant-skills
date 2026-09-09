---
registry_summary: "Visual component only; a standalone text label that does not process data. Typically used with a group as a header and brief description."
---

# text

## Business purpose

Canvas annotation — a standalone text label that doesn't process data. Builders use these as callouts ("INPUT", "OUTPUT", "TODO: handle duplicates") or as labels for sections that aren't wrapped in a `group`. They have no inlets and no outlets.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/text.json`. This file focuses on behavior and gotchas.

## Building (use node_builders)

`nb.text(title, description=None)` builds a text annotation with the full style set — it populates BOTH `inputText` (plain) and `config.text` (rendered rich HTML, kept in sync), sets `isInitialized:true`, includes the sizing/style fields Savant expects, and sets `backgroundColor:"transparent"`, so it never renders as a grey band. For a group header, prefer `Flow.group(..., header=..., description=...)` which creates and places the header for you. Don't hand-author the JSON.

## Invariants

- `inlets` and `outlets` must both be `[]`. A text node is not wired.
- `config.inputText` and `config.text` should agree semantically. If they diverge (common after bulk edits), the canvas shows `config.text` but exports may reference `inputText`. Treat `inputText` as authoritative for programmatic reads.
- `config.width` must be `>= config.minWidth`; same for height.
- Text nodes inside groups are group headers by default and must use the full initialized shape: `isInitialized:true`, rendered `text`, plain `inputText`, `backgroundColor`, `borderColor`, `color`, `fontSize`, bold/italic/underline/strikethrough flags, and positive `width`/`height`/`minWidth`/`minHeight`/`currentHeight`. Minimal text configs can import but may be pruned by Savant after ordinary blank-canvas interactions.
- Text nodes don't participate in data flow — running the workflow does not execute them.

## API edit support

Text-node edits are supported only when they can be represented as documented recipe JSON changes, such as `config.inputText`, `config.text`, position, size, and formatting fields. Use `savant.py workflow edit` to save the recipe diff, then re-fetch with MCP `fetch` and run `savant.py workflow verify --operation edit --before-json` for persistence verification. Keep `config.inputText` and `config.text` in sync on edit.

## Gotchas

- **`text` vs `inputText` drift.** The HTML `text` field can encode formatting the plain `inputText` doesn't capture. After a rich-formatting edit, `inputText` may lag. Read `inputText` for semantic content, `text` for rendering.
- **Text nodes can occlude real nodes if repositioned poorly.** They have z-order but builders don't always think about it, so a poorly placed text node can visually overlap a real node.
- **Don't confuse text nodes with group labels.** Groups have their own `name`-based label; text nodes are separate annotation nodes. Both can appear in a flow.
- **Text-node content is high signal.** A text node's label is something the builder placed intentionally (a callout or section header). When summarizing a flow, include text-node content rather than skipping it.
