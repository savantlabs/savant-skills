---
name: savvy
description: Work with the Savant Labs analytics platform in natural language — answer product/usage questions, build a new flow from a described process (planning it, then creating and verifying it live), apply (create or edit) a workflow in the live app, and inspect/export/explain an existing flow. Use this skill whenever the user mentions Savant or Savvy, pastes a Savant flow URL (.../en/app/flow/...), has a workflow JSON file, asks to build/design/create/import/edit/fix/inspect/debug/explain/export a data workflow or pipeline, or asks a conceptual question about Savant objects (dataset, system, folder, workspace, tool/step, Analyze mode, run/test history, admin usage). Also runs finance reconciliations — bank, credit-card, GL-to-subledger, intercompany, and balance-sheet account tie-outs ("reconcile", "bank rec", "recon", "tie out", month-end close). Covers the whole lifecycle from "what is Savant?" through building, deploying, and inspecting flows.
---

# Savvy

Savvy is the Savant Labs platform skill. It runs in **one of four modes** plus an optional
agent — pick the mode that matches the user's request, then read that mode's reference file and
follow it. The modes share one toolchain, one authentication handshake, and one run-mode
vocabulary, all defined below so the mode files don't repeat them.

## Pick the mode

Decide the user's intent and route to the matching reference file. Read it before acting; it is
the full playbook for that mode.

| The user wants to… | Mode | Read |
|---|---|---|
| Ask a conceptual / product / usage question, or admin Usage Log data — no specific flow to change | **q-and-a** | `references/skills/q-and-a.md` |
| Build a new flow from a described process ("build me a workflow that…", "turn these files into a flow") — plan it, then create it live and verify | **author** (continues into **applier**) | `references/skills/author.md` |
| Make a flow real or change it live — import a JSON to create a flow, or edit an existing flow (URL/flowId) in place | **applier** | `references/skills/applier.md` |
| Understand, debug, drill into, or export an existing flow (has a flow URL); single-node or targeted questions | **inspect** | `references/skills/inspect.md` |
| Get a complete, business-level walkthrough of an **entire** flow node by node | **inspect**, or delegate the sweep to the **`flow-explainer`** agent | `references/skills/inspect.md` / `agents/flow-explainer.md` |

Routing notes:

- The decisive question for a flow URL is **what they want to do with it**: understand/export/debug → inspect; change it → applier (edit). A workflow definition with no existing flow + "make it real" → applier (create).
- A request that starts conceptual but turns into building/changing a specific flow should switch modes before acting.
- Author is **offline** (no live API); applier and inspect are **live** (need credentials, below). Q&A is usually offline but can check live state.
- **"Build me a flow" is a continuous journey, not a file hand-off.** Author plans + builds offline, then — when the live API is available — hands its validated workflow definition to applier-create, which makes the flow real and verifies it. The plan approval the user already gave authorizes the live create; don't re-gate it. The workflow-definition (JSON) intermediate is **internal plumbing** — never offer "do you want the JSON, or shall I create it live?" Surface the definition to the user only when `api_enabled` is false (the file is then the deliverable) or the user explicitly asks to export/download/back it up.

## Solutions (domain playbooks)

A solution is a domain playbook layered on the four modes: it owns the domain intake, rules, and
output format, then continues into a mode (usually **author**) to build it in Savant. If a request
matches a row, read that file and follow it.

| Domain | Use when the user wants to… | Read |
|---|---|---|
| Finance | Reconcile an account — bank, credit-card, GL-to-subledger, intercompany, balance-sheet; "tie out"; month-end close | `solutions/finance/reconciliation.md` |

## Toolchain

`savant.py` is the bundled Python toolchain at **`scripts/savant.py`**, one directory below this
`SKILL.md` (its siblings are `references/` and `agents/`). Throughout the mode files, `savant.py`
is shorthand for it. Run it with the host's Python 3 — `python3` on most macOS/Linux setups,
`py -3` or `python` on Windows. If you can't find `scripts/savant.py` next to this file, the
toolchain isn't installed: say so and stop, rather than hand-authoring or simulating its output.

## Response rules

Before writing any user-facing reply, follow `references/standards/business-user-response-rules.md`
— business-first, concise, display-name-driven, honest about what was and wasn't verified. This
applies to every mode.

## Authentication (live modes)

Applier and inspect call the Savant web-app API directly but never mint their own credentials. The
chat client holds the MCP connection; the `savant.py` shell is a pure API executor that reads its
credentials from the environment. The handshake:

1. **Resolve the workspace.** **Prefer the namespace already in the URL** — a flow URL with `?rns=<namespace>` names the owning workspace, so use it directly. Only when there is no `rns` (a bare recipe id, an rns-less URL) — or, for a create, to resolve the destination folder — call the **`locate`** MCP tool to find the owning namespace. `locate` takes the entity's `savant://{type}/{id}` URI (the same form `search` returns) — **not** a Canvas URL or bare id; from a flow URL, extract the id after `/flow/` and pass `savant://workflow/{id}`. Either way, if the active session isn't in that namespace, call **`switch-workspace`** (passing the namespace `locate` returns) — or **`switch-folder`** — so the minted credentials are scoped correctly, then read the entity with `fetch`. (If switching to the URL's `rns` doesn't grant access, fall back to `locate` for the true owner.) For an entity already in the current workspace, skip `locate` and just use `search`/`fetch` — `locate` is only for cross-workspace targets.
2. **Mint credentials.** Call the **`get-api-credentials`** MCP tool. It returns `apiBaseUrl`, `token`, and `tabId`.
3. **Supply the credentials to the toolchain — for this session only.** `savant.py` reads `SAVANT_API_TOKEN`, `SAVANT_API_TAB`, and `SAVANT_API_BASE_URL` (optionally `SAVANT_API_NAMESPACE`). Pass them inline on each call:

   ```sh
   SAVANT_API_TOKEN=<token> SAVANT_API_TAB=<tabId> SAVANT_API_BASE_URL=<apiBaseUrl> python3 scripts/savant.py …
   ```

   Set them as **environment variables, never as CLI flags** (an arg is visible to other local users via `ps`; an inline env assignment is not). (`apiBaseUrl` may end in `/api`; the shell normalizes it.) **Do not set, invent, or export `SAVANT_AI_SESSION_ID`** — the session id is derived from the runtime automatically.

   *Optional file form (your discretion — e.g. a long session where per-call prefixing is noisy):* write the **`get-api-credentials` response** to the path from `savant.py session tmp-path savant-creds.json` and set `SAVANT_CREDS_FILE` to it. The response object *is* the file format — no transformation. That path is a user-private, OS-reaped temp dir outside the repo; **never write credentials anywhere else** (repo, `$HOME`, a `.env`), and don't keep them past the session.
4. **On a 401**, the token expired — call `get-api-credentials` again, re-supply the credentials, and retry. Don't re-parse or hand-retry beyond that.

**Never echo the token (or the creds file's contents) into a user-facing reply.**

Then confirm access: `savant.py capabilities --output-path "$(savant.py session tmp-path savant-capabilities.json)"` and proceed only when `api_enabled: true`.

## Run modes (data-evidence ladder)

When a mode needs computed data evidence, choose the cheapest rung that can answer correctly and
step down only on a clear need. Full rules and caveats: `references/substrate/run-modes.md`.

- **`--mode cached`** (default for read helpers) — read the node's existing `Ready` preview, compute nothing. Try this first.
- **`--mode interactive`** (sampleTier `1k`) — compute on **≤1000 input rows**, no writes. Fast-iteration default. Because the *input* is sampled, totals/aggregates/distinct counts/filter-join match-counts can be **short or wrong** — escalate when correctness on those depends on the full dataset.
- **`--mode analyze`** (sampleTier `max`) — read the **real full source**, no writes, intermediates trimmed to a ~32 MB working volume. The validation rung for full-data correctness.
- **Batch (Test / Run)** — durable job execution. **Savvy does not submit Batch executions**; use `POST /executions` only where explicitly directed elsewhere.

Advanced scoping (analyze/interactive): `--up-to <node>` prunes downstream compute to a stopping
node; `--from <node>` recomputes forward from a changed node, reusing upstream cache. See
`references/substrate/run-modes.md`.

## Boundaries

- **Never deletes.** Savvy never deletes a flow, node, or edge — ask the user to delete in the Savant app.
- **Live writes need confirmation.** Applier never creates or edits without explicit in-chat confirmation (see applier mode's safety contract).
- **Stay honest about verification.** Don't claim a flow ran, a row count, or a preview you didn't actually fetch; assert live state only when `api_enabled` was true and the data was read.
- **Live Savant state comes from MCP tools, not the local machine.** When this skill is active, orientation and state questions ("where am I?", "who am I?", "what workspace/flow am I in?") are answered with the plugin's MCP tools (e.g. `whereami`, `whoami`) — never the host's shell, cwd, or local filesystem. Only read local files when the user explicitly asks about local files or artifacts.
