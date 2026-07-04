---
registry_summary: "Writes the final workflow output to a destination, either creating a new output or updating an existing one. Currently only support Native CSV destination."
---

# destination

## Business purpose

Terminal output node. Writes or exposes the flow's rows as an output — a native Savant CSV, a file in OneDrive/S3/GCS/SFTP, an email attachment, or another connected destination. Every flow that produces useful output has at least one destination; a destination has inlets but no outlets, so the data stops here.

Destinations can also serve as write-back points (via `mode: "update"`) for round-tripping data into source systems.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/destination.json`. This file focuses on behavior and gotchas.

## Building a destination (use node_builders)

`../scripts/workflow/builders.py` owns the shape via `nb.destination_from_plan(output_plan, sort=(col, "asc"|"dsc"))` when consuming Planner handoff objects, which routes by `planned_destination_type`:

- **Native Savant CSV** (`planned_destination_type: "csv"`) → `nb.destination_csv(name, file_name, sort=...)`. Not a cloud file write; no folder needed; `connector/type: "csv"`, `mode: "update"`, no `fileSystemConfig`.
- **File destination to a connected system** (`planned_destination_type: "onedrive"` or `"googledrive"`) → `nb.destination_file(name, connector=..., folder_link=..., file_name=..., file_type="EXCEL"|"CSV", tab_name_mode="static"|"field", tab_name_field=..., subsequent_mode="replace"|"append", format_from_template=...)`. Writes a CSV or Excel workbook into the system's folder. Excel writes one tab (`tab_name_mode="static"` + `tab_name`) or a tab per field value (`tab_name_mode="field"` + `tab_name_field`).

The handoff object shape is defined in `../scripts/contracts/output_destination.py` (file-destination plans add `folder_link`, `file_type`, `file_name_mode`, `tab_name_mode`/`tab_name_field`, `subsequent_mode`). A file destination must bind to a **connected system that already exists** in the workspace — discover/verify it (and heed the silently-dropped-on-import gotcha and the status/expiry caveat) via `../substrate/system-substrate.md`; the skills never create or authenticate a system, and `folder_link` is a user-supplied environment binding, never invented. OneDrive and Google Drive are supported today; other file connectors (S3/GCS/SharePoint/SFTP/Box) are not yet built. The builder derives a default node-level description from `business_purpose` when `output_description` is not provided; pass `output_description` when the output audience or review purpose needs more precise wording.

## Invariants

- Native CSV destinations use `connector: "csv"`, `type: "csv"`, `mode: "update"`, and a destination `id`; they must not carry `fileSystemConfig`.
- File-system CSV outputs use a real file connector such as OneDrive, SharePoint, S3, GCS, Box, or SFTP plus `fileSystemConfig.fileType: "CSV"`.
- When `fileNameMode: "field"`, `fileNameField` must reference a real upstream column.
- Same rule for `tabNameMode` / `tabNameField` and `subFolderNameMode` / `subFolderNameField`.
- `fileType` must match the connector — OneDrive/GCS/S3 support `EXCEL` or `CSV`; email attachments default to `EXCEL` unless overridden.
- `sortConfig` references fields that must exist in the upstream output. Sorting on a dropped column throws at run time.
- `emailConfig.emailTo` is a list of strings; an empty list is a config error (no recipients).
- `subsequentMode: "append"` assumes schema-compatible existing content. Appending mismatched columns fails the write.
- **One workbook, one template creator.** When several Excel destinations write tabs into the *same* workbook (same system + folder + subfolder + file name), exactly one — the destination that creates the workbook — may set `format_from_template=true`; every other destination writing to that workbook must set it to `false`. `formatFromTemplate=true` recreates the whole workbook from its template on write, so two of them clobber each other: the last to run wipes the tabs the earlier ones wrote. The validator errors when two static-path destinations collide and warns when the colliding paths are field-driven. (It cannot police execution order — the template creator must also run before the tab-writers, which stays an authoring responsibility.)

## API edit support

Config edits to an existing native CSV destination (output binding and sort) use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, destination_csv("x", file_name, sort)["config"])`. Defining a brand-new destination, or changing the connector/output system the node writes to, is creation/topology — not a config edit — and routes to the builder/creator path.

## Registry-backed generation notes

- **Destination type follows the output audience** (file, alert, review sheet, write-back, data product). No static connector allowlist — 300+ connectors vary per workspace, so the validator doesn't check the connector string; validity comes from binding to a real target in the workspace.
- **Do not invent target ids, folder links, channels, recipients, credentials, or table ids.** These values are customer/environment bindings. A generated workflow may include clearly labeled placeholders, but final delivery must bind them in Savant.
- **Do not model native CSV as a file-system destination.** A native CSV destination is the app-created `connector: "csv"` / `type: "csv"` / `mode: "update"` shape. Adding `fileSystemConfig` to `connector: "csv"` creates a locked/broken output.
- **Default file handoffs to replace, not append.** For file-system destinations, default to replace; only switch to `append`, `upsert`, `groupReplace`, or `update` (which require stable keys or schema compatibility) when the user explicitly wants cumulative history.
- **Field-driven filenames and tabs require upstream columns.** When using `fileNameMode: "field"`, `tabNameMode: "field"`, or subfolder field mode, create and preserve the naming fields upstream and validate they are present at the destination.
- **Sorting belongs at the destination only when the delivered artifact needs a fixed order.** If a report or file handoff requires ordering, `sortConfig` is appropriate, but the fields must exist in the final output.

## Gotchas

- **The destination's output is the rows that WILL be written.** It is ordered by `sortConfig` if set, and its row count matches the upstream output.
- **The destination's display name is usually the output's business name** ("Customer Extract", "Monthly Report") — for the user, this is often the most recognizable node in the flow.
- **`"append"` mode can silently grow output files.** A destination left in append mode across multiple runs accumulates rows in the target. Users discover this when their output file is 10x the expected size.
- **Field-mode file naming requires column stability.** When `fileNameMode: "field"`, each run's filename depends on the value of `fileNameField`. Upstream edits that rename or drop that column silently change file names.
- **No-data handling is email-only in config.** `emailConfig.noDataOption.strategy` controls what happens when upstream has zero rows (typically `"same"` to still send an empty-attachment email). Other destination types handle no-data with default behavior.
- **Write-back mode (`mode: "update"`) is distinct from `subsequentMode`.** Update writes back to the source system; subsequentMode controls file-level replace vs append. Don't confuse them.
