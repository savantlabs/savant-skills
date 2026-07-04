# System Substrate

> **Naming.** Savant's UI calls these **systems** (Data → Systems). The app API calls the same
> object a **connection** (`/api/connections`, each with a `connector` type). They are
> interchangeable; this project standardizes on **system** for everything user- and agent-facing,
> and keeps "connection" only where it mirrors the raw API (the `list_connections` helper / the
> endpoint). When talking to a user, always say "system."

## Objective

Use this to discover and bind a connected **system** in the target workspace — a user-set-up system
(OneDrive, Google Drive, …) that a workflow can write to as a **destination**. It is the
system-level companion to `dataset-substrate.md`: datasets are uploaded/static or system-backed
inputs; systems are the live connections those system-backed inputs and file destinations bind to.

## Use When

- A request names an external service to **write to** ("write to OneDrive", "export to Google Drive").
- Builder/Creator/Editor needs to bind a file destination to a real connected system.
- A request asks to **read from** a connected system (handle per "Sources from a system" below).
- You need to confirm a connection exists, is active, or has not expired before relying on it.

## Default Action

- Require `api_enabled`.
- **Read-only.** Connections are created and authenticated by a person in Savant. The skills only
  read existing connections — never create a system, never enter credentials, never run or complete
  an OAuth/SSO flow, never re-authenticate. If no suitable connection exists, stop and ask the user
  to set it up in Savant.
- Discover existing connections and bind by connection `id`. Prefer an unambiguous match; when more
  than one connection of the right type exists, **ask which one** (same discipline as datasets).
- Supported connectors today: **OneDrive (`onedrive`)** and **Google Drive (`googledrive`)**. Others
  (`s3`, `gcs`, `sharepoint`, `sftp`, `box`, …) exist in Savant but are out of scope here for now;
  treat them as not-yet-supported and ask the user rather than guessing their config shape.

## Do Not

- Do not create, authenticate, or re-authenticate a connection, and do not enter any credential or
  OAuth consent — that is always a person-in-the-UI action.
- Do not invent connection ids, folder links/ids, file names, or paths. These are environment
  bindings; take them from a real connection or from the user.
- Do not assume "the connection exists" means "the credentials are still valid" — check `status` and
  `expiresAt` (see below).
- Do not treat a connection as a dataset. A destination binds a connection through
  `fileSystemConfig`; a *source* still binds a dataset id (see "Sources from a system").

For the object model, read `savant-context.md`. For destination config shape, read
`../components/destination.md`. For dataset discovery/binding, read `dataset-substrate.md`.

**Discovery runs off the MCP session and does not need `api_enabled`** (see below). **Binding a
destination** (building + importing the node) still hits the live app API and needs `api_enabled`; if
it is false you can still discover and name a connection but cannot import the change — say so rather
than claim it was applied.

## How do I discover a system?

Use the resources `search` tool (works without `api_enabled`):

1. `search(types=["connection"])` — paginate via `cursor`. Each hit carries `id`, `title` (name),
   `summary` (`<connector> connection (<status>)`), and **`namespace`** (the connection's true owner).
2. **Filter by namespace.** Connection search is **org-wide**: it returns this workspace's own
   connections *and* org-shared ones owned by other workspaces, each tagged with its own `namespace`
   (not your session's). Keep only hits whose `namespace` matches the workspace you'll bind in — a
   destination must bind a connection usable in the target workspace.
3. **Filter by connector** client-side from the `summary` token (`onedrive` / `googledrive` / …);
   there is no server-side connector argument.
4. For one connection's detail — `owner`, `expiresAt` (token expiry, epoch ms), `status` — call
   `fetch(savant://connection/{id})`.

- Turn a connection **name** into its **id** from the search hits; bind by id.
- If several connections of the wanted connector exist (after the namespace + connector filter), ask
  which one by display name — do not pick for the user:
  > I see two Google Drive connections — `Anil Google Drive` and `Finance GDrive`. Which should this output write to?
- If none of the wanted connector exists in the target namespace, stop: the user must create and
  authenticate it in Savant first. Name what's missing.

## How a user finds a system id by hand (no API)

When MCP connection search is unavailable, the user supplies the system id.
Tell them how to get it from the Savant UI:

1. Open Savant → **Data** → **Systems** tab.
2. Find the system, open its row menu (the `⌄`/caret), and click **Edit**.
3. The id is in the browser URL: `app.savantlabs.io/en/app/connection/{id}/edit` — e.g.
   `.../connection/jdvyptumte/edit` means the system id is `jdvyptumte`.

That Edit screen also shows the account, the auth **expiry date**, and a **Re-authenticate** button —
useful if a run fails on expired credentials (re-auth is the user's action, never ours).

## Auth / lifecycle: existence is not validity

A connection can exist and still fail at run time if its token has expired or it was revoked.

- `status` should be `Active`; `expiresAt` is the token expiry (epoch ms). If `expiresAt` is in the
  past or `status` is not active, say so — a run will fail to authenticate, and that surfaces at
  **run time**, not when you wire the node.
- The skills cannot refresh or re-authenticate — re-auth is a person-in-the-UI step.

## Destinations: writing to a connected system (supported)

A file destination binds to a connection and writes a file into it. The node shape lives in
`../components/destination.md` / `../registry/components/destination.json`; this substrate owns the
**discovery and binding** layer around it.

- Resolve the target system **id** via connection `search` (filtered to the target namespace; ask if
  ambiguous), then build the
  destination with `connector`/`type` set to that connector (`onedrive` / `googledrive`) and a
  `fileSystemConfig` describing the write. **The destination binds to the system by `config.id` =
  the system id** (e.g. the Google Drive system `jdvyptumte` → the node's `config.id`), exactly as a
  source binds a dataset id. File destinations carry no `mode` (unlike native CSV). Build with
  `nb.destination_file(name, connector=..., system_id=..., folder_link=..., file_name=...,
  file_type="EXCEL"|"CSV", tab_name_mode=..., tab_name_field=..., subsequent_mode=...)`.
- **Offline (`api_enabled` false):** you can still build the node if the user supplies the system
  **id** (the `config.id` binding), the connector type, and the `folder_link`. You cannot verify the
  id resolves — a wrong/missing id is silently dropped on import — so the id must be correct.
- **Import-drop gotcha (verified).** A file destination whose connector has **no matching connection
  in the target workspace is silently dropped on import** — Savant removes the node, the created flow
  comes back one node short, and there is no import error. This mirrors the AI-provider behavior in
  `ai-provider-substrate.md`. So Creator must confirm the connection exists *before* import; the only
  signal otherwise is a node-count shortfall against the source JSON.
- **Never invent the folder binding.** `folderLink` (OneDrive/SharePoint share URL) and the Google
  Drive folder reference are environment values — take them from the user or a real connection, or
  leave a clearly labelled placeholder for the user to bind in Savant.

Observed OneDrive destination `fileSystemConfig` (reference shape):

```json
{
  "fileType": "EXCEL",            // EXCEL or CSV
  "fileName": "Fixed Asset by Legal Entity",
  "fileNameMode": "static",       // or "field" + "fileNameField" (a real upstream column)
  "tabNameMode": "field",         // one tab per value of "tabNameField"
  "tabNameField": "Legal Entity",
  "folderLink": "https://…sharepoint.com/…",
  "subsequentMode": "replace",    // default replace; "append" accumulates across runs
  "flatFileConfig": {"fileWriterProps": {"delimiter": ",", "qualifier": "\"", "escape": "\\", "charset": "UTF_8"}}
}
```

Google Drive (`googledrive`) is the same `fileSystemConfig` family with its own folder reference
instead of a SharePoint `folderLink`. The exact folder field is environment-bound — read it from the
chosen Google Drive connection / a real node rather than assuming it, and confirm with the user.

## Writing to the same file from several destinations (assembling a workbook)

A file destination **updates an existing file in place — it does not recreate it.** So several
destinations can point at the **same file** (same folder + file name), within one workflow or across
workflows, to build up one workbook:

- **Different tabs → one workbook.** Point destination A at file `X` tab "Summary" and destination B
  at the same file `X` tab "Detail" (or use `tab_name_mode="field"` to fan out tabs); the file ends
  up with all the tabs. This is how you assemble a multi-tab Excel from multiple branches or flows.
- **Updating / adding data.** A later write to file `X` updates it rather than replacing the whole
  file; tabs not touched by a write are left intact. `subsequent_mode="replace"` replaces the
  content of the tab being written; `"append"` adds rows to it.
- **Last write wins.** If two writes target the **same tab** (same file + same tab name), the later
  one overwrites the earlier — there is no merge. Within a single run, ordering is not something you
  control finely, so don't have two destinations write the same tab of the same file expecting both
  to survive; give them distinct tab names (or distinct files). Across separate runs/flows, the most
  recent run's write is what remains.

Design implication: to build one workbook with one tab per legal entity, a *single* destination with
`tab_name_mode="field"` is cleaner than many destinations; use multiple destinations to the same file
when the tabs come from genuinely different branches/flows, and keep their tab names distinct.

## Sources from a system (not yet supported — coming soon)

Reading from OneDrive/Google Drive is **not** a direct source-to-connection bind. In Savant you
create a **dataset from the system** (New Dataset → Connect → Select System → pick the file), which
produces a *system-backed dataset*; the source node then binds that dataset id like any other.

The skills do not create system-backed datasets (creating connector-backed/credentialed datasets is
out of scope — see `dataset-substrate.md`). So today:

- **Treat "read from OneDrive/Google Drive" as not yet supported / coming soon.** Tell the user the
  source must first exist as a dataset created from that system in Savant.
- Once the user has created that dataset, it appears in `search(types=["source"])` and is bound
  exactly like any uploaded dataset via `dataset-substrate.md` — no special handling.

## Enforcement / boundaries

- Connection discovery is read-only; binding a connection (create/import/edit) is a state-changing
  action and follows the usual confirm-before-acting rule.
- The validator does not check connector strings (300+ vary per workspace); validity for a
  destination comes from binding to a real connection that exists in the workspace — which is exactly
  why the existence check here matters before import.
