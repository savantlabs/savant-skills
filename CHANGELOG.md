# Changelog

User-facing changes to the Savvy plugin, newest first. This file covers the 1.x release line.

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
