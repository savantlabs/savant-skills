# Finance Workpapers

Use this solution when the user wants to document or build a recurring finance workpaper other
than an account reconciliation: a rollforward, an accrual, a tax schedule, a consolidation, a
variance or flux analysis, a review or test a preparer signs. It supplies the finance content of
the plan (what the workpaper proves, its inputs, controls, exception types and outputs) from
Savant's finance knowledge, then continues in **author** mode, which owns the plan gates and the
build.

Account reconciliations (bank, credit card, GL-to-subledger, intercompany, balance sheet) stay
with `reconciliation.md`, which also performs the reconciliation in chat.

Important: this knowledge describes common finance practice. It does not provide accounting or
tax advice, and every company-specific value in it is a starting guess the user confirms. The
user's qualified finance, accounting or tax owner reviews the workpaper before it is relied on.

## Where the knowledge lives

Savant keeps two finance knowledge corpora on the connector and updates them between plugin
releases, so read them live each time and do not rely on a list remembered from this file.

| Corpus | Holds | Read it when |
|---|---|---|
| `finance-workpapers` | One entry per workpaper: what it proves, inputs, standard controls, company-specific controls with a best guess, process steps, exception types, outputs, and situations it does not handle | The user's process matches an entry |
| `finance-foundation` | What every finance workpaper shares, one fragment per section of a process document | The user chose the fuller process document, or no entry matches |

Both are reached with the MCP `search` and `fetch` tools. Knowledge is returned only when
`types` names it:

```text
search(types=["knowledge"], filters={"corpus": "finance-workpapers"}, query="<the user's words for the process>")
fetch("savant://knowledge/finance-workpapers/<entry-id>")
```

The `search` tool's own description lists the corpora currently available and what each covers.
Use only these two from this solution. Other corpora on the connector describe a different Savvy
experience; for how Savant and this skill work, the references in this skill remain the
authority.

## Find the entry

1. Search `finance-workpapers` with the user's own name for the process, plus the obvious
   synonyms (for example "tax reserve rollforward", "FIN 48", "uncertain tax positions").
2. Match on the entry's title, description and "also called" names. Fetch the one best entry.
   Fetch a second only when the user's process plainly spans two workpapers.
3. Check the entry's "Not this workpaper" line. If the user's process is one of the neighbors it
   names, search again for that neighbor.
4. Tell the user in one sentence which standard workpaper the plan starts from, in business
   words, and let them correct it. Do not mention corpora, entries, fragments or URIs.

**If nothing matches**, or the search returns no knowledge, or the corpus is not available on
this connector, plan from the user's description exactly as author mode does without this
solution. When `finance-foundation` is available, use its fragments for the section being
written. Never tell the user a process is unsupported because it has no entry, and never invent
an entry's content.

## Turn the entry into the plan

The entry fills in the plan author mode presents; it does not replace author's plan-depth
question, state tracker, validators or confirmation.

| Entry section | Goes into the plan as |
|---|---|
| What this process proves | Business outcome and output purpose; the "Not this workpaper" line bounds the scope |
| Inputs | Source roles. A mapping table or period adjustment is an input the user supplies, so ask for it only when the build needs it |
| Standard controls | Rules written into the plan as stated, with their thresholds. Do not ask the user to confirm standard practice one rule at a time |
| Company-specific controls | The best guess for each, written in as an assumption the user can change |
| The entry's "Decide" paragraph | The choices to put to the user as questions, best guess first, within the question budget below. Everything else stays an assumption |
| Process steps | The numbered business process steps and the business blocks that become groups |
| Exception types | The exception and review flags, each with the control that raises it |
| Outputs | The output plan: the result, the exception list and the support behind them |
| Watch for | Key assumptions and out-of-scope notes in the plan |

Rules for using it:

- **The user's facts win.** Their files, their stated rules and their saved preferences override
  the entry. Where the files disagree with the entry (a column the entry expects is absent, a
  key has more parts), follow the files and say what changed.
- **Build only what the inputs support.** An entry describes the full workpaper. When the user
  has supplied only some inputs, plan the controls those inputs can support and list the rest as
  not yet covered.
- **Keep the entry's finance wording.** Its control names, movement types and exception names
  are the terms a preparer and reviewer expect; carry them into step labels and group titles.
- **A control is not evidence.** Writing a tie-out into the plan does not mean it tied. Report a
  control as met only after the built workflow's data was read, under the skill's verification
  rules.

For the **fuller process document**, fetch the `finance-foundation` fragment for each section as
it is written (for example `key-controls` or `exception-types`) and use it for what belongs in
that section; the entry supplies the workpaper-specific content.

## Question budget

A finance user expects a workpaper plan they can correct, and a long interview loses them. For
this solution the budget below takes precedence over author's rules to confirm each material
decision and each output separately.

- **Ask at most three questions** beyond author's plan-depth question. Take them from the
  entry's "Decide" paragraph, the ones that most change the result first, each with the best
  guess offered as the default. Skip any the user's files, words or saved preferences already
  answer.
- **Assume the rest and show it once.** Every other company-specific value goes into the plan
  at its best guess. List these together under one "Assumptions to check" heading in the plan,
  so the user approves or corrects them in the same reply that confirms the plan. Record each
  as a material decision with the rationale `user approved assumption` once the plan is
  approved.
- **Showing is confirming.** The entry's standard controls, exception types and outputs count
  as presented when the plan shows them. Do not confirm them one control, one exception type or
  one output at a time.
- **Ask for a missing input only when the build cannot proceed without it.** Otherwise plan
  what the supplied inputs support and list the missing input as not yet covered.
- **No entry, same budget.** When planning from the user's description, pick the three choices
  that most change the result, ask those, and assume the rest the same way.

A correction from the user is not a new question; apply it and continue. If the user asks to be
walked through every choice, do that.

## Questions with no build

When the user only asks what a workpaper involves ("what controls belong on a payroll accrual?"),
answer from the entry in plain finance language, note that company-specific values are starting
points, and offer to turn it into a documented, repeatable Savant process.
