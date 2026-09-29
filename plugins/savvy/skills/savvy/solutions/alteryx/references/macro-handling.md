# Macro handling

Alteryx macros (`.yxmc`) are identified by `EngineSettings/@Macro` on the calling tool. `savant.py alteryx parse` classifies each against the `macros` patterns in `tool-mapping.json` and sets `macro_kind`.

| Kind | Examples | What the skill does | Guide entry |
|---|---|---|---|
| **standard** | Cleanse, Find/Replace, CrossTab/Transpose helpers, DateTime | Map to built-in Savant steps via the mapping table. In Savant there is no separate object: the macro's effect becomes ordinary steps (usually folded into a neighbouring Transform). Read the macro's parameter `Value`s to know which options are on — e.g. Cleanse `Check Box (84)` = replace nulls with blank (text), `(117)` = replace nulls with 0 (numeric), `(15)` = trim whitespace, `(77)` + `Drop Down (81)` = change case. | "Cleanse (34) → trim + blank→0 inside *Standardize labels…*" |
| **output** | Publish to Tableau Server, Publish to Power BI, Salesforce Output | Unsupported destination → **P1**. Propose the replacement (Snowflake write-back, OneDrive/Google Drive file, native CSV for validation) and note the downstream repoint (step 13). | P1 row |
| **custom** (bundled `.yxmc` in a `.yxzp`) | Client-built normalisation/lookup macros | Parse the macro XML as its own workflow (the parser already does when it's in the package). Inline its tools into the parent at each call site, substituting the call site's control-parameter values as constants. Document "macro X called at tool N → inlined as steps A–B; parameter P = value". If the same macro is called from several flows in the portfolio, flag it in the roll-up as a candidate for **one reusable Savant flow** instead of inlining it everywhere. | Appendix B rows tagged *inlined macro* |
| **iterative / batch** | Loop-until-empty, per-group batch runs | Cannot be inlined — it is a loop. **P1** with a redesign sketch: most Alteryx loops are either (a) "generate all combinations then filter", which becomes a scaffold (Summarize distinct + constant-key Blend) and a Filter, or (b) "run once per group", which becomes a single set-based step grouped by that field. Confirm the redesign with the owner before building. | P1 row |
| **custom, not bundled** | Macro referenced by path but not in the package | Ask for the `.yxmc`. Until then it is **P1** ("macro logic unknown"). | P1 row |

Rules of thumb
- Never present a macro as a "black box step" in the traceability map; the owner needs to see which business rule each inlined step carries.
- Macro control parameters that are credentials (`PAT_Name`, tokens) are never copied into the guide; the parser drops keys matching `password|token|secret`, and for **output** macros drops every free-text slot (`Text Box (n)`), keeping only URLs and drop-down/check-box choices, because those macros keep usernames and passwords in generically named slots. Project and data-source names therefore come from the tool annotation or the owner.
- The parser decodes the standard Cleanse macro's controls into `config.cleanse_options` (`fields`, `null_to_blank`, `null_to_zero`, `trim`, `case`); `List Box (11)` is the field list. Use that, not the raw control ids.
- A macro that only exists to work around an Alteryx limitation (Block Until Done, dynamic rename after a CrossTab) usually maps to *nothing* in Savant — say so explicitly rather than leaving the tool unmapped.
