---
registry_summary: "Does not perform any data operations — just a visual component used for annotating workflows."
---

# notes (Notes)

## Business purpose

Canvas annotation. Notes are sticky-note style callouts used to document instructions, destination settings, handoff details, or process reminders. They do not process data.

The product currently exposes both Text and Notes. Use Text for structured section headers and richer formatted labels. Use Notes for compact sticky callouts that should look like annotations rather than workflow-stage headers.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/notes.json`. This file focuses on behavior, writing, and gotchas.

No node_builders constructor yet — canvas/layout node; created in the app or via raw JSON.

## Invariants

- Notes do not participate in data flow. Their outlet target list should be empty.
- Exports commonly include one dummy inlet and one dummy outlet, but neither should be wired to data steps.
- `config.text` should be concise enough to fit the configured dimensions.

## API edit support

Note-node edits (the note text and formatting) are documented recipe JSON changes, saved via `savant.py app` and verified by re-fetch — the same approach as `text.md`. Do not use DOM or store automation. A note's content is a plain recipe field, so no `node_builders` constructor is required; see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") for the shared edit loop.

## Gotchas

- **Notes are not executable.** They can describe an email, Slack message, or file path, but the real output settings live on Destination steps.
- **Notes carry no data, only text/style.** A note exposes text, color, size, and basic style — there is no data preview. Its content (`config.text`) can be useful context for destinations or manual handoffs, but in business summaries use note text only when it explains intent not already visible from real data steps.
- **Notes can become stale.** Treat them as helpful context, not authoritative configuration.
- **Do not use Notes for standard group headers.** The shared layout guidance expects `text` nodes for group headers.
