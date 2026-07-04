#!/usr/bin/env python3
"""Print the compact Planner -> Builder handoff contract."""

from __future__ import annotations

import argparse
import sys

SCOPES = {"build_only", "draft_import", "full_verified_workflow"}


def build_packet(scope: str) -> str:
    governance_required = scope in {"draft_import", "full_verified_workflow"}
    governance_line = (
        "Required for this scope: owner, cadence, escalation owners, and approval fields."
        if governance_required
        else "Optional for this scope unless `documentation_mode` is `detail`."
    )
    return f"""# Builder handoff packet

Use this while filling `planner_to_builder.handoff.json`. Scaffold first, fill the objects below, then run `savant.py validate stage --role planner --gate done`.

## Scope

- `requested_scope`: `{scope}`
- Governance metadata: {governance_line}
- If `process_metadata.documentation_mode` is `detail`, governance metadata is required even for `build_only`.

## Required top-level sections

- `task_type`: `builder_preflight`
- `stage`: `ready`
- `workflow_name`: non-empty display name
- `requested_scope`: `build_only`, `draft_import`, or `full_verified_workflow`
- `process_metadata`: process identity and scope-relevant metadata
- `input_dataset_plan`: confirmed source plan
- `output_destination_plan`: confirmed output plan
- `workflow_plan_checkpoint`: confirmed business plan and process blocks
- `json_generation_allowed`: `true`

## process_metadata

Always fill:

- `process_name`: business process name
- `source_skill_or_domain`: source of the plan, such as `general workflow planning` or a domain skill name
- `documentation_mode`: `light` or `detail`
- `documentation_mode_source`: `user_answer` or `reusable_preference`
- `documentation_mode_evidence`: explicit user answer or reusable preference evidence when source is `user_answer`

Fill only when governance metadata is required:

- `owner`
- `cadence`
- `escalation_owners[]`
- `approval.drafted_by`
- `approval.certified_by`
- `approval.date_certified` as `YYYY-MM-DD`

## input_dataset_plan

- `required`: `true`
- `status`: `passed`
- `plan_presented`: input plan shown to the user
- `profile_evidence.local_files_provided`: boolean; `true` when the user supplied local CSV, Excel, or PDF files for this plan
- `profile_evidence.source_profile_path`: required when `local_files_provided` is `true`; must point to a ready `savant.py source profile` full report
- `profile_evidence.source_profile_brief_path`: required when `local_files_provided` is `true`; must match the full profile report's embedded `brief`
- `sources[]`: one source-plan object per input
- `user_confirmed_or_revised`: `true`
- `user_confirmation_evidence`: explicit user approval or correction of the input plan

## sources[] object

Every source has:

- `source_name`: user-recognizable input name
- `business_role`: what this input contributes to the process
- `source_kind`: `tabular`, `binary_document`, `json_text`, or `xml_text`
- `dataset.dataset_id`: resolved Savant dataset id; never invent it
- `dataset.profile_status`: `id_only`, `schema_only`, `full_profile`, or `user_supplied`

For tabular sources, also include:

- `expected_schema[]`: canonical fields the workflow uses
- `expected_schema[].name`: downstream field name
- `expected_schema[].dataType`: `string`, `number`, `integer`, `date`, `datetime`, or `boolean`
- `expected_schema[].mappedFrom`: raw source field when renamed or standardized
- `expected_schema[].required`: `true` when the workflow depends on the field

When `dataset.profile_status` is `schema_only`, `full_profile`, or `user_supplied`, also include:

- `dataset.connector`: connector/type string from the dataset evidence
- `dataset.observed_schema[]`: raw fields observed in the source
- `dataset.observed_schema[].name`
- `dataset.observed_schema[].dataType`

When `dataset.profile_status` is `full_profile` or `user_supplied`, each observed field also needs:

- `dataset.observed_schema[].sampleValues`: at least one representative source value

Optional:

- `dataset.row_count`: non-negative integer when known
- `extraction.prompt`: required for `binary_document`
- `parser`: required for `json_text` and `xml_text`; XML `SELECT` needs `parser.path`

## output_destination_plan

- `required`: `true`
- `status`: `passed`
- `plan_presented`: output plan shown to the user
- `included_in_workflow_plan`: `true`
- `outputs[]`: one output object per final output

## outputs[] object

- `output_name`: output display name
- `business_purpose`: how the business user will use it
- `requested_destination_type`: what the user asked for
- `planned_destination_type`: `csv`, or `onedrive`/`googledrive` for a file destination bound to an already-connected system (file-destination plans add `folder_link`, `file_type`, `file_name_mode`, `tab_name_mode`/`tab_name_field`, `subsequent_mode` — see `contracts/output_destination.py`)
- `output_description`: optional, overrides the default node description
- `file_name`: optional, defaults from `output_name`
- `expected_grain`: business row grain for this specific output, e.g. `one row per region`
- `expected_columns[]`: final columns expected in this specific output, in order
- `required_checks[]`: output-specific verification checks; use `columns_exact_order`, `row_count_nonzero`, and `no_node_errors` unless the user approved a narrower check
- `verification_node_name`: optional destination/checkpoint node name when it differs from `output_name`

If the user requested a non-CSV output:

- `unsupported_requested_destination`: `true`
- `unsupported_notice_presented`: `true`
- `unsupported_notice`: tell the user Builder will generate a CSV fallback

## workflow_plan_checkpoint

- `required`: `true`
- `status`: `passed`
- `format`: `workflow_process_plan`, `numbered_business_process_map`, or `compact_sentence`
- `plan_presented`: the user-facing approved plan
- `process_blocks[]`: business-facing groups in order
- `process_steps[]`: business process steps
- `material_assumptions[]`: assumptions that affect interpretation
- `material_decisions[]`: material logic the user approved (see material_decisions[] object)
- `user_confirmed_or_revised`: `true`
- `user_confirmation_evidence`: explicit plan approval or revision evidence
- `user_review_decision`: `approved_as_presented` or `revised_then_approved`

## process_blocks[] object

- `title`: business-facing group title; must appear in `plan_presented`
- `business_purpose`: why this block exists
- `business_steps[]`: what happens in business terms

Avoid component names such as Source, Filter, Blend, Transform, Destination, Node, or Schema in block titles.

## material_decisions[] object

Material decisions are choices that change what the workflow does to the data and that the user signed off on — AI use, fuzzy matching, normalization strategy, thresholds, fallback logic, ranking/tiebreaking, one-to-one match rules, source-of-truth precedence, exception categories, output grain, audit fields. AI use is one decision among equals, not a special case. See `../../references/standards/material-decisions.md`.

- `decision`: the approved choice, in business terms
- `rationale`: why it was made (e.g. `user requested`, `user approved assumption`, `complex text processing`)
- `reflected_in_handoff`: `true` — set only after verifying the handoff implements this decision and adds nothing material beyond the approved decisions
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact Planner -> Builder handoff contract.")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="build_only",
        help="Requested Builder scope. Defaults to build_only.",
    )
    args = parser.parse_args()
    sys.stdout.write(build_packet(args.scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
