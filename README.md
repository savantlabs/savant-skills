# Savant Skills

Official marketplace for **Savant** AI skills and plugins. Connect your AI agent to Savant to describe, build, and inspect data workflows in natural language.

Works with both **Claude Code** and **Codex**.

## Install

### Claude Code

```bash
/plugin marketplace add savantlabs/savant-skills
/plugin install savvy@savant
```

### Codex

```bash
codex plugin marketplace add https://github.com/savantlabs/savant-skills
codex plugin install savvy
```

Both surfaces pull from this repo's `main` branch and connect to the Savant production backend at `savvy.savantlabs.io`.

## What's Included

### Savvy Plugin

The **Savvy** plugin lets you work with Savant in natural language:

- **Answer questions** about Savant concepts (datasets, systems, folders, workspaces, tools, analyze mode)
- **Build workflows** from a described process — plan it, create it live, and verify it
- **Edit workflows** in the live app (create or modify steps)
- **Inspect/export** existing workflows and explain how they work
- **Finance reconciliation** — specialized skill for bank, credit card, GL-to-subledger, intercompany, and balance sheet account reconciliations

Use this whenever you mention Savant, paste a Savant flow URL (`https://app.savantlabs.io/en/app/flow/...`), have a workflow JSON file, or ask to build/design/create/import/edit/fix/inspect/debug/explain/export a data workflow or pipeline.

## Authentication

The plugin connects to Savant through your AI client's MCP integration. On first use, you'll be prompted to authenticate with your Savant account. Credentials are session-scoped and managed automatically — they're minted per session and never persisted to the repository, your project, or any long-lived file.

## Structure

This marketplace serves both Claude Code and Codex via dual manifest files:

- `.claude-plugin/marketplace.json` — Claude Code marketplace
- `.agents/plugins/marketplace.json` — Codex marketplace

Each plugin carries both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` so the same source works for both tools.

## Support

This repository is an automatically generated distribution — please don't open pull requests here, as they will be overwritten on the next release. For questions, issues, or feedback, contact Savant at [https://www.savantlabs.io](https://www.savantlabs.io).

## License

See [LICENSE](LICENSE) for details.
