---
registry_summary: "Special components that represent external data processed by the workflow. It can be tabular (e.g. csv, excel) or binary (e.g. pdf, image). It knows how to extract data from system and convert it into a tabular format for use in a workflow."
---

# source

## Business purpose

Data ingestion. Always the starting point of a workflow branch — every flow has at least one source, and there are no inlets on this type. The source points at a dataset that's already been uploaded or connected to Savant (an Excel file, a CSV, a PDF, or rows from an enterprise connector like SAP or Workday). Its job is only to pull that data into the canvas; any reshaping happens in downstream nodes.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/source.json`. This file focuses on behavior, canvas reading/writing, and gotchas.

## Building a source (use node_builders)

`../scripts/workflow/builders.py` owns the shape (`nb.source(...)`; pass `dtype="binary"` only for a downstream vision node). The only field that binds a source to a real dataset is the source-plan contract's `dataset.dataset_id` (→ `config.id`) — discover it via `../substrate/dataset-substrate.md`, don't invent it. Connector strings are dynamic (300+ per workspace; the validator doesn't check them), so the connector follows from the nested dataset profile when available. Generated sources get a node-level Markdown description from `source_description` when supplied, otherwise from the source plan's `business_role`; direct `nb.source(...)` calls get a fallback input description.

## Source Units

Build Planner-handoff sources through `nb.source_unit_from_plan(...)` so the full source-plan object, including the nested dataset profile, reaches deterministic generation. The source-plan contract lives in `../scripts/contracts/source_plan.py`. The helper chooses the source pattern:

- **Tabular:** `Source -> Adapter`.
- **Binary/PDF/image:** `Source -> Vision` or extraction.
- **JSON text:** `Source -> JSON`.
- **XML text:** `Source -> XML`.

For file/spreadsheet tabular sources, `dataset.observed_schema` and optional `dataset.row_count` from the source plan are written to the source node as profiling evidence automatically. Do not hand-inject source `fields` or `rowCount`; fix the source plan instead. If the default source description is too generic, improve `business_role` or pass `source_description` in the source plan; do not patch descriptions after construction.

Excel serial dates are the one source-standardization case that may add a post-adapter cleanup step. When `dataset.observed_schema` shows a planned `date`/`datetime` field arriving from Excel as numeric serial values, `nb.source_unit_from_plan(...)` emits `Source -> Adapter -> Normalize <Source> Dates`: the Adapter preserves the observed numeric type, and the Normalize Transform converts the canonical field into a real date/datetime. If there is only `Source -> Adapter`, one of the required triggers was missing: connector must be `excel`, expected type must be `date`/`datetime`, observed type must be `integer`/`number`, and numeric sample values must look like Excel serial dates.

For tabular data, creating a source is not finished until it is paired with a standardizing **Adapter**: `Source -> Adapter` is one unit, never a bare source. The adapter is the **schema contract** and the single node coupled to the physical source. It declares, for every column the flow depends on:

- the **canonical name** (business-stable; downstream references this),
- the **data type** (`string` / `number` / `integer` / `date` / `datetime` / `boolean`),
- the **raw column it maps from** (`mappedFrom`), and
- whether it is **required**.

For simple hand-authored tabular examples, `nb.standardized_source(...)` adds the source and its adapter, wires them, and returns the **adapter id** that downstream wires from. Why this belongs to the source definition (and not to data-prep):

- **Source swap / edit = re-map the adapter, nothing else.** Because downstream nodes reference only canonical names, repointing the source at a different or updated dataset is a change to this adapter's `mappedFrom`/types only — the rest of the flow is insulated. The editor's dataset-replacement path keys on exactly this (see "API edit support" below and `../standards/workflow-editing-rules.md`).
- **It forces clarity up front** — you cannot write the adapter without naming the required columns and their types, which removes the name/type ambiguity that otherwise surfaces as silent runtime breaks.

Keep the adapter to the contract only — names, types, mapping, required. **Value cleanup** (blanks → null, currency/parentheses stripping, typed join keys, fallbacks, derived columns, review flags) is a separate concern that runs *after* the contract in a `Normalize ...` Transform; how to do that cleanup is owned by `../standards/data-prep-normalization.md`, not here. Binary/PDF/image sources are not tabular yet, so extract first and add an Adapter only after extraction if a stable tabular schema contract exists. Skip the adapter only for a source that is already canonical (trusted names + types), and say so.

`savant.py validate workflow` enforces this for tabular logic: a source must feed a standardizing adapter, an extraction/parser step, or a `Normalize ...` Transform before downstream logic.

## Invariants

- `inlets` must be `[]`. A source with inlets will not load.
- `config.id` is the only field that ties the canvas node to an actual dataset. If it's missing or doesn't resolve, the node renders but the preview will be empty.
- `config.type` and `config.connector` must be consistent — a CSV source should have both as `"csv"`. Mixing (e.g. `type: "csv"`, `connector: "excel"`) produces undefined behavior.
- `config.type: "binary"` is only valid for sources consumed by a `vision` node downstream. Don't point a non-vision node at a binary source.
- Renaming the node's display name via the pencil icon updates `name` on the node, not `config.name`. The two can diverge; inspector should trust the outer `name` as the user-facing label.

## API edit support

> **Status: supported source edits are (1) display-name/layout fields and (2) replacing the dataset the source points at, done as an in-place recipe save WITH downstream schema reconciliation. Source description is dataset-level metadata and is not a flow-recipe edit.**

Source edits have outsized downstream blast radius, so dataset replacement is never a bare `config.id` swap — it is a reconcile-and-verify flow (see "Swap the dataset" below and the "Dataset replacement" section of `../standards/workflow-editing-rules.md`). When the downstream cannot be reconciled into a runnable flow, the editor routes that part through the downloader -> builder -> creator rebuild path.

## Registry-backed generation notes

- **Discover existing datasets through the shared substrate.** Follow `../substrate/dataset-substrate.md` when binding a source node to an existing dataset. The source node can point at the existing dataset without recreating its connection, file path, parsing rules, or credentials.
- **Reading from a connected system (OneDrive/Google Drive) is a system-backed dataset.** A source node never binds a connection directly; the user first creates a dataset *from* that system in Savant, after which it is discovered and bound like any dataset. The skills do not create system-backed datasets, so treat "read from OneDrive/Google Drive" as not yet supported / coming soon. See `../substrate/system-substrate.md`.
- **Do not invent dataset bindings.** Real exports often include `config.id`, `connectionId`, `namespace`, owner metadata, table paths, file patterns, selected fields, and schema arrays. These are environment-specific. Generated draft flows should use plausible labels and connector type only; live delivery must bind the actual dataset through Savant. (`nb.source` keeps the config as a placeholder until a concrete `dataset_id` is bound.)
- **Database sources need concrete discovery before pushdown design.** Table/query, selected columns, and refresh/run expectations matter before adding pushdown filters or summaries.
- **File sources often expose file-pattern settings.** SFTP/S3/cloud-file sources commonly include file type, folder/path, latest-file or pattern handling, tab names, delimiter/charset/quote settings, header handling, subfolder inclusion, and metadata inclusion. Ask for these only when they affect correctness.
- **Descriptions are not reliable on sources.** Many sample sources have little or no useful flow-level description. Use the outer node name for business readability and describe source purpose in workflow/group context where needed.

### What a source edit actually does

Three user-level edits, in order of risk:

1. **Rename the node** (low risk): changes the displayed `name` only; `config.id` and the dataset are untouched, downstream unaffected.
2. **Edit the description** (not a flow edit): the source `config` has no `description` key (only `id, name, type, connector`) — source description is **dataset-level metadata** saved through a separate backend path, not the flow recipe (probe-confirmed on `source_qomnws`). If asked, decline and explain it lives in the dataset's own settings.
3. **Swap the dataset** (high risk): repoints `config.id`/`connector` at a different dataset — the single most destructive edit, since every downstream reference to the old columns can break. The editor never does a bare swap. If the source is **standardized** (adapter follows), the swap collapses to remapping the adapter and downstream is insulated; otherwise it retrofits a mimicking adapter or runs full downstream reconciliation. The procedure (capture/diff schemas, audit references, auto-reconcile ids, surface gaps, verify) is owned by the **"Dataset replacement" section of `../standards/workflow-editing-rules.md`** — don't re-derive it here.

## Gotchas

- **A source's output is the raw dataset.** It emits the raw rows from the dataset with the original column headers as the file defined them, and its row count is the dataset's full row count (modulo any pushdown filters — see `pdfilter.md`). This is the baseline against which every downstream node's row count is compared. Sources have no clauses or formulas — the "configuration" is just which dataset to point at.
- **Connector-backed sources may load slowly.** Live-connector sources fetch fresh data on each run, which can take 10+ seconds to populate the preview. Don't interpret an empty grid as "no data" until you've waited or checked for a progress indicator.
- **`config.name` vs node `name`.** They drift after a rename. The outer `name` is what the user sees; `config.name` is often stale. Don't trust `config.name` for identification.
