---
registry_summary: "LLM-powered matching between two data streams - need to specify matching columns from both the streams."
---

# fuzzy_match (AI Fuzzy Matching)

## Business purpose

AI-powered fuzzy join between two data streams. Where `blend` does exact-match joins on keys, `fuzzy_match` uses an AI provider to match approximately — pairing `"Acme, Inc."` with `"ACME Incorporated"`, or `"Apple Computer"` with `"Apple Inc."`. Each matched row gets a `Confidence Score` column indicating how strong the match is.

Unlike blend, fuzzy_match produces a **single output** — no matched/unmatched split. Downstream nodes filter on `Confidence Score` if they need to separate high-confidence matches from low.

## Registry

Schema, enum values, and validator-facing config rules live in `../registry/components/fuzzy_match.json`. This file focuses on behavior, writing, and gotchas.

## Building a fuzzy_match (use node_builders)

Do not hand-author fuzzy_match JSON. `../scripts/workflow/builders.py` owns the shape:

```python
fm = f.add(nb.fuzzy_match("Match Vendors", lhs_key="Legal Names", rhs_key="Vendor Name",
                          provider_id="savant-ai-provider-gzilpzflks",
                          show_demo_provider=True))
f.wire(left, fm, in_idx=0); f.wire(right, fm, in_idx=1)
```

This is a **separate AI node from blend**, not a blend variant. Verified facts the builder encodes:

- **`providerId` defaults to Savant Trial when omitted.** When API access is available, resolve the live workspace provider per `../substrate/ai-provider-substrate.md` and ask only if there are multiple providers. Without API, the builder uses the standard Savant Trial id (`savant-ai-provider-gzilpzflks`) instead of asking the user. An unresolvable provider id is **SILENTLY DROPPED on import**.
- **Single output + a `Confidence Score` column** — no matched/unmatched split like blend. Unmatched rows are **dropped** (a left row with no right candidate is gone). If you need unmatched handling, use blend instead.
- Two inlets: `in_0` (left), `in_1` (right). `lhs_key`/`rhs_key` must be **TEXT columns** (fuzzy matching numbers/booleans is meaningless) and are normalized to field ids (e.g. `"Legal Names"` → `legal_names`).

## API edit support

Config edits (match keys, provider) use the shared regenerate-and-merge path — see `../standards/workflow-editing-rules.md` ("Config edits — regenerate via node_builders") — via the generic `update_config(node, fuzzy_match("x", lhs_key, rhs_key, provider_id=None)["config"])` (missing provider defaults to Savant Trial). Two caveats: **verifying the result triggers a paid run** (the AI match runs per row), and changing *which inputs* feed the match is an inlet/topology change, not a config edit.

## Gotchas

- **Output columns are all-left + all-right + `Confidence Score`.** One output row per high-confidence match (provider-dependent threshold); unmatched left or right rows are dropped. A duplicate column name across sides is typically disambiguated with a suffix.
- **Always check the `Confidence Score` distribution.** An output where every score is 1.0 suggests the matcher fell back to exact matching (the AI didn't actually help). Mixed scores (some 0.85, some 0.95, some 0.70) are normal.
- **Unmatched rows are dropped.** Users coming from blend expect to see unmatched rows somewhere; fuzzy_match doesn't emit them. If unmatched handling matters, use blend instead or chain fuzzy_match with a downstream join-back pattern.
- **Row count can exceed either input.** A left row may fuzzy-match multiple right candidates; a right row may match multiple lefts. The Cartesian-product risk is lower than blend because of the confidence filter, but not zero.
- **Confidence threshold is provider-dependent.** What counts as a "match" versus "not a match" depends on the configured provider. Different providers will produce different output row counts on the same inputs.
- **Previews are paid calls.** Each row-pair comparison costs money (via the LLM/AI provider). Don't preview casually on large inputs.
