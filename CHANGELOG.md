# Changelog

User-facing changes to the Savvy plugin, newest first. This file covers the 1.x release line.

## 1.1.1 — 2026-10-06

- The plugin's connection is now listed as "Savant V1".

## 1.1.0 — 2026-09-24

- Savvy can migrate an Alteryx workflow. Give it a `.yxmd`, `.yxwz` or `.yxzp` file and it produces a
  migration guide — what the workflow does, which Alteryx tools have no Savant equivalent, the
  decisions that would change a number, a production checklist and a tool-by-tool traceability map —
  then builds the Savant flow from that plan with every step numbered back to the guide.
- Profiling local files before a build now reads files that are not UTF-8 instead of failing, says
  so, and accepts a separate delimiter for each file.
- `savant.py <group>` and `--help` on any command work without a signed-in session.
- Creating a CSV dataset can now set the file's encoding (`--charset`, UTF-8 or Windows-1252) and
  pin a column's type before inference (`--column-type Customer_ID=string`), so Latin-1 files and
  codes with leading zeros load correctly. The Alteryx inventory suggests the exact command per
  input file.

## 1.0.6 — 2026-09-29

- The plugin now shows the Savant icon and links to Savant's privacy policy in the plugin
  directory.
- Savvy's local toolchain signs in only through the key it pairs with your conversation. It no
  longer accepts a sign-in token, or a different location for its sign-in files, from environment
  variables.

## 1.0.5 — 2026-09-26

- Savvy's local toolchain now signs in with a key it generates on your machine and never shares
  with the chat. Previously a sign-in token was handed to the assistant over the connection.
  The assistant now links that key to your conversation instead, so no credential ever appears
  in the chat.
- An active session stays signed in on its own; re-linking is only needed after a long idle
  period or after the connector is reconnected.
- The plugin's connection is now listed as "Savvy Plugin" instead of "Savvy". You will be asked
  to sign in to it again once after upgrading.

## 1.0.4 — 2026-09-11

- Renaming a workflow or editing its description or tags reports what happened. The change was
  reaching Savant, but the command stopped with an error straight afterwards, so there was no way
  to tell whether it had been saved.
- Suggested validation checkpoints work again, and no longer need a live connection.
- An expired sign-in is now caught before a workflow is built rather than at the moment it is
  saved, so the work isn't finished and then lost to a session that had already lapsed.

## 1.0.3 — 2026-09-08

- Explaining a workflow, mapping its structure, and exporting its definition no longer need live
  app access switched on, so those answers work in workspaces where the live connection is
  unavailable. Creating, editing, running previews, and reading run history still need it.
- AI fuzzy-match steps are built with an AI provider the step settings accept. Previously the
  provider arrived as an invalid selection that had to be chosen again by hand before the step
  would run.
- A sign-in that expired mid-session is reported when Savvy tries to save rather than when it
  first checks access, so the message names the step that could not be completed.

## 1.0.2 — 2026-09-07

- Summarize and Rollup combine values with the separator you ask for — a pipe, a semicolon, a
  newline — instead of always falling back to a comma.
- Columns that combine text values are labelled as text rather than as numbers. The values
  themselves were always treated as text; only the label was wrong.

## 1.0.1 — 2026-07-23

- Savvy introduces itself accurately and can answer questions about its own
  capabilities, requirements, and limitations.
- Responses and progress updates are written for finance and business users:
  business outcome first, verification made clear, internal mechanics left out.

## 1.0.0 — 2026-07-07

- Initial release: build new Savant workflows from a described process, edit and inspect existing
  workflows live, answer Savant product and usage questions, and run finance reconciliations
  (bank, credit-card, GL-to-subledger, intercompany, balance-sheet).
