# Dataset Substrate

## Objective

Use this to turn a workflow input into a real dataset binding in the target workspace: discover an existing dataset, create one from a user-provided file, and bind a source node to the dataset id.

## Use When

- Planner, Creator, or Editor needs to resolve a source dataset.
- A workflow JSON has unresolved source bindings.
- The user provides a file that may need to become a Savant dataset.
- An existing source needs to be repointed to another dataset.

## Default Action

- Require `api_enabled: true`.
- Prefer an existing dataset when the match is unambiguous.
- Create a dataset only from a user-provided local file and only after explicit approval.
- Bind source nodes by dataset `id`; let the dataset own connection/path/schema details.

## Do Not

- Do not claim the workspace was checked when API is unavailable.
- Do not invent dataset ids.
- Do not create connector-backed or credentialed datasets.
- Do not treat folder orientation as dataset discovery; list sources instead.

For the object model, read `savant-context.md`.

**Discovery, schema and source-matching all come from MCP** — `search(types=["source"])` (name→id) and `fetch(savant://source/{id})` (schema + content type) run off the MCP session and need no `api_enabled`. Source-matching is now local logic fed by that search result, so it needs no API either. **Only dataset *creation* still hits the live app API** (`api_enabled` required): resolve the snapshot with `python3 ../scripts/savant.py session tmp-path savant-capabilities.json` and read it first. If `api_enabled` is false you can still discover, name, inspect and match datasets via MCP, but cannot create anything — say so; don't claim the workspace was fully checked.

## How do I discover a dataset?

**Name → id + schema (no `api_enabled` needed):** `search(types=["source"])` lists datasets, paginating via `cursor`; each hit carries `id`, `title` (name), `summary` (e.g. `csv dataset` / `binary dataset`), and `namespace`. Sources are workspace-level, so filter hits to the target `namespace`. This turns a dataset **name** into its **id**. For one dataset's **schema + content type**, call `fetch(savant://source/{id})` — the payload's `schema` array gives column names + `dataType`, and `config` gives the format.

- **Binary vs tabular (does it need a Vision/parse step?):** a binary/PDF/image dataset shows `summary: "binary dataset"`, `config.connector: "binary"` / `dataFormat: "BINARY"` (+ `binaryFormat`, e.g. `PDF`), and a single `content` column with `dataType: "binary"`. Treat those as needing an extraction step before any table logic; a real tabular source (csv/excel) has named columns with real dataTypes.

**Source-matching against a built flow (API, needs `api_enabled`):**

```bash
# Match a built flow's sources to datasets: write the MCP search result to sources.json, then
python3 ../scripts/savant.py dataset discover --workflow-json <workflow.json> --sources-json <sources.json>
```

- Datasets are workspace-level objects; a workflow *source* node just binds one by id. To write to (or, when supported, read from) a connected system like OneDrive/Google Drive, see `system-substrate.md`.
- Prefer an existing dataset over creating one. Bind only when the match is unambiguous; if several are plausible, ask for the exact one:
  > I found two datasets that could be the sales input — `Sales Transactions` and `Sales Transactions Export`. Which should this process use?
- A binding does not prove the schema. Take field names from the dataset's own schema/sample (via `fetch`), a node preview, or a user-provided sample — and note that binary/PDF/image datasets need a Vision/parse step before any table logic.

## How a user finds a dataset id by hand (no API)

When MCP source search is unavailable, the user supplies the dataset id.
Tell them how to get it from the Savant UI:

1. Open Savant → **Data** → **Datasets** tab.
2. **Click the dataset** (no Edit needed — just open it).
3. The id is in the browser URL: `app.savantlabs.io/en/app/source/{id}` — e.g. `.../source/zmgxjctzlk`
   means the dataset id is `zmgxjctzlk`. (Note the path segment is `source`, but this is the
   workspace **dataset** id that a source node binds via `config.id`.)

(Contrast with a connected **system**, whose id comes from Data → Systems → row menu → **Edit**, URL
`.../connection/{id}/edit` — see `system-substrate.md`.)

## How do I create a dataset?

```bash
python3 ../scripts/savant.py dataset create --file <local-file> --name "<Dataset Name>"
```

Datasets are workspace-scoped and created in the authenticated session's namespace, so switch to the target workspace first (no folder/URL argument).

CSV options that must be right at creation, because type inference cannot be undone afterwards:

- `--delimiter ';'` when the file is not comma-separated.
- `--charset WINDOWS_1252` for Latin-1 / ISO-8859-1 / Windows-1252 files (the server accepts only `UTF_8` and `WINDOWS_1252`; other encodings must be converted first). Symptom of the wrong charset: accented names come out as `Ã‰`.
- `--column-type Customer_ID=string,Postcode=string` to keep codes with leading zeros as text; repeatable. Types: string, integer, number, boolean, date, datetime. The command warns if the stored type differs from what was declared — treat that as unresolved.
- The same keys work per item in a `--manifest` (`"charset"`, `"types": {"Customer_ID": "string"}`).

- Before creating datasets from a workbook, profile the workbook's sheets and compare their headers to the workflow's expected source schemas. A reconciliation master, support tie-out, summary, or carryforward workpaper is usually an output/review workbook, not the raw source extract package. Do not bind an output workbook as if it were the raw source data; either create minimal validation datasets for runtime smoke testing and say so, or ask for the missing raw extracts.
- Only from a local file the user provided, of a supported type, and only with the user's explicit approval:
  > I don't see `Service Orders 2026-04-03` in this workspace. I have the file you gave me — create that dataset and bind to it? (Ask once, listing all if several are missing.)
- Do not create connector-backed or credentialed datasets — databases, cloud folders, API sources. Ask the user to make those available in Savant instead.
- After creating, re-list sources and bind only once the new id is visible.

## Binding

A source node just points at the dataset `id`; the dataset owns its connection, file path, parsing, selected fields, and schema. Don't recreate any of that in the workflow JSON, and don't invent an id. The Planner resolves a real `dataset_id` (and connector) for every source before handing off to the Builder; a missing or unresolved binding goes back to the Planner rather than being guessed downstream.
