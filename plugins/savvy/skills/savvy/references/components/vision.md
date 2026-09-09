---
registry_summary: "Extracts structured data from PDFs, images, or scanned documents from a prompt, using an LLM."
---

# vision (AI Document Extraction)

## Business purpose

Extracts structured data from PDFs, images, or scanned documents using AI vision. Upstream of this node is almost always a `source` with `type: "binary"` (PDFs/images uploaded as files); downstream is usually a `json` node to flatten the extracted fields. The typical shape: "here's a folder of invoices, extract date / amount / line items from each page into columns."

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/vision.json`. This file focuses on behavior and gotchas.

## Building a vision node (use node_builders)

Do not hand-author vision JSON. `../scripts/workflow/builders.py` owns the shape:

```python
f.add(nb.vision("Extract Invoice", prompt, input_field="content",
                provider_id="savant_anthropic"))
```

Verified facts the builder encodes:

- **`providerId` defaults to Savant Anthropic (`savant_anthropic`) when omitted.** When API access is available, resolve the live workspace provider per `../substrate/ai-provider-substrate.md` and ask only if there are multiple providers. Without API, the builder uses `savant_anthropic` instead of asking the user. Do **not** use the legacy unified id `savant-ai-provider-gzilpzflks` here — the canvas migrates vision nodes off it on load, and the per-vendor ids are what the picker shows. (`fuzzy_match` is the exception: it *requires* the legacy id. See `fuzzy_match.md`.) Any unresolvable provider id is **SILENTLY DROPPED on import** — Savant removes the whole node, not just the provider.
- `input_field` must reference the upstream column holding binary content (usually `"content"` from a `source` with `config.type: "binary"`). Pointing vision at a non-binary column produces errors or empty output.
- Output schema is implicit in `prompt` — downstream columns are whatever the provider returns, so editing the prompt can change column names silently. One input row (one document) can produce MULTIPLE output rows when the prompt asks for line items.

## API edit support

Config edits use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders"). Regenerate with `vision_update(node, prompt, input_field, provider_id=None)` (missing provider defaults to Savant Trial). Like `gen_ai`, **verifying the result triggers a paid per-document run** (see the "Preview is slow and costly" gotcha below), so surface the cost and get a run-mode decision before any verification run. Changing the prompt's output schema also shifts the downstream `json`-flatten columns — reconcile those.

## Gotchas

- **Prompt schema drives output columns, not config.** The set of output columns is whatever the vision provider returns from the prompt. Edit the prompt, and column names can change silently. Output shape varies: one doc → one row with N columns (header-style field extraction), or one doc → many rows (line-item prompts asking for repeating entities).
- **No `skill` key in config.** A `vision` node's `config` is exactly `{ prompt, inputField, providerId }` (verified on `Vision for Bank Statements`, flow id `pkkvjxgypv`). The "Skills" picker is a product-managed UI affordance that simply writes the `prompt` text when a skill is chosen; the only durable artifact is the resulting prompt, so selecting a skill is structurally equivalent to a prompt overwrite. There is no skill enumeration — to reproduce a "Bank Statement skill" prompt programmatically, copy the prompt text from a real Bank Statement vision node rather than reference the skill by name.
- **Binary-content upstream is required.** Vision fed from a non-binary source produces no useful output. Check upstream's `config.type`.
- **Line-item prompts multiply row counts.** Documents with 10 line items produce 10 rows from one input row. Downstream joins and aggregations need to handle this.
- **Preview is slow and costly.** Each row is a vision API call.
