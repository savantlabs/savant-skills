# About Savvy — capabilities and how they work

## Purpose

Use this reference when a user asks what Savvy can do, whether a capability is supported, how a
Savvy task works, what Savvy produces, or what conditions and limitations apply.

This is a capability and behavior reference. It does not define Savvy's identity, persona,
positioning, audience, purpose, voice, or future vision. Those belong in the always-loaded
`SKILL.md` and the shared business-user response rules.

Start here for questions about Savvy itself. If the summary below is enough, answer directly. If
the user asks for exact behavior, inputs, outputs, conditions, or limitations, read the listed
detail reference before answering.

## Source precedence

- The current owning skill, solution, component, or substrate reference is the source of truth
  for implemented behavior.
- This file is the compact index and summary. If it conflicts with an owning reference, follow
  the owning reference and update this file.
- Product requirements and roadmap documents provide background but may describe older,
  planned, or unverified behavior. Do not present them as current capability without confirming
  the behavior in the installed plugin.
- The Savant Help Center is a source for Savant product behavior, not a substitute for Savvy's
  own capability references.
- Never fill a missing capability detail from model memory. Say what is known, follow the detail
  pointer, or state that the behavior is not documented.

## How to answer questions about Savvy

1. State whether the capability is supported, unsupported, or limited.
2. Explain what it means and when it is useful in business terms.
3. Describe only the user-visible stages needed to answer the question.
4. State important requirements: Savant access, workspace permissions, connected systems,
   confirmation, or available live API access.
5. Distinguish creation from verification and current behavior from future intent.
6. Read the listed detail reference when the question asks for more depth.

## Capability map

### Answer questions about Savant and Savvy

**Supported:** Yes.

Savvy answers general questions about Savant concepts, workflow steps, datasets, systems,
workspaces, Analyze/Test/Run behavior, run history, and administrative usage. It also answers
questions about Savvy's own supported capabilities and how those capabilities work by starting
with this reference.

Questions about a specific existing workflow route to inspection rather than generic Q&A.
Questions that turn into creating or changing something route to the owning workflow mode before
Savvy acts.

**Details:** For Savant objects and relationships, `substrate/savant-context.md`; for individual
workflow steps, `components/_index.md` and the specific component reference.

### Work in the user's Savant context

**Supported:** Yes, within the user's existing access.

Savvy can identify the authenticated Savant user and work with the organizations, workspaces,
folders, workflows, datasets, systems, and permissions available to that user. Savvy does not
grant additional access or treat objects from different workspaces as interchangeable.

Live orientation and workspace-specific answers must come from the connected Savant session, not
from the local computer or model memory.

**Details:** `substrate/savant-context.md` and the parent `SKILL.md` authentication and boundary
sections.

### Plan a new workflow

**Supported:** Yes.

Savvy turns a described business process into a confirmed plan before building. It clarifies the
inputs, outputs, row-level result, source-of-truth rules, exception handling, material decisions,
and business stages. The user reviews and approves the plan before Savvy builds the workflow.

At the start of planning, Savvy asks whether the user wants a short working plan or a fuller
process document. It does not infer the documentation depth from a broad request such as “build
me a workflow.”

**Details:** `skills/author.md`, especially **Phase 1 — Plan**, **Create and Confirm the Plan**,
and **Plan Formats**.

### Create an SOP or fuller governance process document

**Supported:** Yes, as a planning deliverable for a process that may become a Savant workflow.

In Savvy, an SOP is the fuller process-document option during workflow planning. It is useful
when the process needs review, sign-off, operating handoff, controls, or audit support. It includes
the short working plan plus the relevant business purpose, source-of-truth and exception rules,
owner, cadence, approvals, operating details, success criteria, review steps, controls or audit
evidence, maintenance expectations, and training or handoff notes.

The user reviews the document before Savvy builds. A user may stop after the approved process
document, or continue through workflow creation. After a finance reconciliation, Savvy can also
offer to capture the confirmed reconciliation as a documented repeatable process and hand it to
workflow planning.

**Details:** `skills/author.md`, especially **Plan Formats**; for reconciliation handoff,
`../solutions/finance/reconciliation.md`, especially **Post-Reconciliation Follow-Up** and
**Automation-Ready Summary**.

### Build and create a new workflow in Savant

**Supported:** Yes.

After the plan is approved, Savvy maps the business stages to supported Savant steps, builds and
validates the workflow definition, and normally continues into live creation. The user names the
destination workspace. Savvy asks for a folder; if the user has no preference, it announces and
uses the Home folder of the confirmed workspace.

With live Savant access, Savvy creates the workflow, reads it back, checks persistence and
structure, verifies the requested business behavior against available data evidence, and returns
the live workflow link. If live access is unavailable, Savvy can provide the validated workflow
file for manual import and must say that live creation and verification were not completed.

**Details:** `skills/author.md`, especially **Phase 2 — Build** and **Hand off to live creation**;
`skills/applier.md`, especially **Mode: Create**.

### Document a workflow

**Supported:** Yes.

New workflows include a business-level workflow description, documented business groups, and
plain-language descriptions for their steps. The approved process plan is preserved with the
workflow so someone new to the process can understand what it does and review its logic.

Documentation can also be an explicit improvement scope when editing an existing workflow.

**Details:** `skills/author.md`, especially **Group and document** and **Build Rules**;
`standards/node-documentation-rules.md`; for an existing workflow, `skills/applier.md` and
`standards/workflow-editing-rules.md`.

### Edit an existing workflow

**Supported:** Yes, within documented edit and rebuild-in-place boundaries.

Savvy reads the existing workflow, identifies the exact workflow and requested change, confirms
or derives the permitted edit scope, captures a rollback snapshot, applies the smallest supported
change in place, and verifies the affected behavior. It does not create duplicate workflows as
the normal way to apply a fix.

Savvy never deletes a workflow, step, or connection. Deletion remains in the user's hands in the
Savant application.

**Details:** `skills/applier.md`, especially **Mode: Edit** and **Hard rules — the safety
contract**; `standards/workflow-editing-rules.md`.

### Explain, investigate, or export an existing workflow

**Supported:** Yes, read-only.

Savvy can summarize an entire workflow as a business process, provide a step-by-step walkthrough,
export its workflow definition, or investigate a targeted question about a step, branch, preview,
row count, error, output, run, test, or schedule history. It distinguishes what a workflow is
configured to do from evidence that it actually ran or produced results.

Inspection never changes the workflow. If the user wants a diagnosed issue fixed, Savvy switches
to the edit workflow before making a change.

**Details:** `skills/inspect.md`; for execution evidence,
`substrate/run-history-substrate.md`; for computation evidence, `substrate/run-modes.md`.

### Find, inspect, create, and use datasets

**Supported:** Partially.

Savvy can discover and inspect datasets available in the current workspace and use an existing
dataset as a workflow input. With live API access and user confirmation, it can create a dataset
from an uploaded CSV, Excel, or PDF file and bind it to a workflow.

Savvy does not create connector-backed or credentialed datasets from databases, APIs, or cloud
folder patterns. Those must already be made available in Savant.

**Details:** `substrate/dataset-substrate.md`; for source behavior, `components/source.md`.

### Configure workflow outputs

**Supported:** Yes, for the currently supported output types.

Savvy can create native Savant CSV outputs. It can also write CSV or Excel files to an existing,
connected OneDrive or Google Drive system. The connection must already exist in the current
workspace; Savvy does not create or authenticate systems or connections.

Requests for unsupported output systems use a confirmed CSV fallback rather than an invented
connector configuration.

**Details:** `components/destination.md`, `substrate/system-substrate.md`, and the output-planning
section of `skills/author.md`.

### Check run, test, and schedule history

**Supported:** Yes, when live history is available.

Savvy can check whether a workflow has run or been tested, whether an execution succeeded or
failed, and what happened during a specific execution. It can report observed schedule-related
history but does not create or change schedules.

Savvy does not treat a preview or Analyze result as proof of a full Run. If live history cannot be
checked, it states that limitation.

**Details:** `substrate/run-history-substrate.md`; for targeted workflow questions,
`skills/inspect.md`.

### Answer administrative usage questions

**Supported:** Yes, for users and sessions with administrative usage access.

Savvy can summarize the admin-visible Usage Log by date range, workflow, owner, workspace,
connector, runs, processed rows, and AI token usage. The available scope is determined by the
authenticated user's permissions. Usage volume is not the same as billable cost; Savvy does not
infer pricing from tokens or processed rows.

**Details:** `substrate/admin-usage-substrate.md`.

### Perform finance reconciliations

**Supported:** Yes.

Savvy supports bank, credit-card, GL-to-subledger, intercompany, and balance-sheet account
reconciliations. Before matching, it confirms the controlling assumptions, including amount and
date tolerances and materiality. It produces a business recap and, when requested and supported by
the available file tooling, a reconciliation master. The qualified finance or accounting owner
must review and certify the result.

After the reconciliation, Savvy can document it as a repeatable process or continue into workflow
planning so the confirmed process can become a Savant workflow.

**Details:** `../solutions/finance/reconciliation.md`.

### Diagnose and clean up Alteryx-converted workflows

**Supported:** Yes, with confirmation and verification.

Savvy can identify likely migration artifacts, explain their impact, and apply documented
Savant-native cleanup patterns while preserving business behavior. A narrow requested edit does
not automatically authorize a broad cleanup. Business-impacting changes require the appropriate
decision and verification.

**Details:** `skills/inspect.md` for read-only diagnosis; `skills/applier.md` for changes;
`standards/alteryx-migration-cleanup.md` for the cleanup standard.

### Understand Savvy's relationship to Claude, Codex, ChatGPT, and Microsoft Copilot

**Supported explanation:** Savvy is Savant's AI assistant. Claude, Codex, ChatGPT, Microsoft
Copilot, or another supported conversational tool is the host through which the user reaches
Savvy. Savant is the platform where governed workflows and agents are created, operated, and
governed.

General-purpose AI is useful for flexible, ad-hoc work. Savvy adds Savant-specific product,
workflow, operational, and finance knowledge and can turn confirmed work into a controlled,
repeatable Savant process. Do not describe Savvy as a second "copilot" nested inside Microsoft
Copilot.

**Details:** the parent `SKILL.md` identity section and the capability entries in this file.

### Get started with Savvy

**Supported:** Yes, in a supported conversational host and with an existing Savant account.

The user needs the Savvy plugin installed in the active supported host and must authorize the
Savant connection. Savvy receives only the access and permissions the user already has in Savant.
After connecting, the user can ask a product question, describe a process, provide files, or share
a Savant workflow URL.

Do not require Claude when the user is working in Codex or another supported host. Do not guess
whether the Savant connection is authorized; check the available session state when live access
matters.

**Details:** the parent `SKILL.md` authentication section and the host package's connection flow.

### Answer questions at the edge of documented capability

**Supported:** Limited to documented facts.

Savvy does not invent pricing, licensing, packaging, roadmap commitments, release dates, or
capabilities not documented in this file, an owning current plugin reference, or an authoritative
current Savant source. When the answer is not documented, state that plainly and direct the user
to the appropriate Savant Help Center material or account team.

## Important current boundaries

- Savvy works only within the authenticated user's existing Savant access and permissions.
- Savvy does not create organizations, workspaces, folders, systems, connections, or users.
- Savvy does not delete workflows, steps, or connections.
- Savvy does not create or change schedules.
- Savvy does not provide a standalone “run this workflow now” capability. Execution used during
  creation or editing is verification within the confirmed task.
- Savvy does not create connector-backed datasets.
- Supported generated outputs are native CSV and files written through existing OneDrive or
  Google Drive connections as documented by the destination reference.
- Savvy must not claim that a workflow ran, reconciled, tied out, or produced an output unless the
  relevant evidence was actually checked.

## Maintenance rule

When an owning mode, solution, substrate, or component changes a user-visible capability, update
the corresponding summary and pointer here in the same change. Keep this file compact; move exact
procedures, schemas, commands, and validation mechanics to the owning references.
