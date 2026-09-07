# Changelog

User-facing changes to the Savvy plugin, newest first. This file covers the 1.x release line.

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
