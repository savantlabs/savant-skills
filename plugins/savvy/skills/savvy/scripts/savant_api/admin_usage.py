#!/usr/bin/env python3
"""Read Savant Admin > Usage Log data through the internal app API.

This helper reuses the user's authenticated browser session. It is intentionally
read-only and narrow because these are internal app APIs, not a public SDK.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from savant_api.cli import (  # noqa: E402
    DEFAULT_ORIGIN,
    SavantAppApiError,
    SavantSessionContext,
    discover_session,
    poll_promise,
    request,
    save_json,
)
from savant_api.fileio import workspace_tmp  # noqa: E402


USAGE_EVENT_TYPE = "bot_run"
USAGE_EVENT_FIELDS = [
    "executionId",
    "recipeName",
    "recipeOwner",
    "runType",
    "startedAt",
    "workspace",
    "srcConnectors",
    "dstConnectors",
    "processedRecords",
    "inputTokens",
    "outputTokens",
    "totalTokens",
]


def _promise_id(response: Any, endpoint: str) -> str:
    if not isinstance(response, dict):
        raise SavantAppApiError(f"{endpoint} did not return a JSON object.")
    promise_id = response.get("promiseId") or response.get("id")
    if not isinstance(promise_id, str) or not promise_id:
        raise SavantAppApiError(f"{endpoint} did not return a promise id.")
    return promise_id


def _usage_payload(from_date: str, to_date: str) -> dict[str, Any]:
    return {
        "timeRange": {
            "from": from_date,
            "to": to_date,
        },
        "eventType": USAGE_EVENT_TYPE,
    }


def _result_from_promise(promise: dict[str, Any]) -> Any:
    if "exception" in promise and promise["exception"]:
        raise SavantAppApiError(f"Usage promise failed: {promise['exception']}")
    return promise.get("result", promise)


def _normalize_tokens(row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    input_tokens = row.get("inputTokens") if isinstance(row.get("inputTokens"), (int, float)) else 0
    output_tokens = row.get("outputTokens") if isinstance(row.get("outputTokens"), (int, float)) else 0
    return {
        **row,
        "totalTokens": row.get("totalTokens") if isinstance(row.get("totalTokens"), (int, float)) else input_tokens + output_tokens,
    }


def _normalize_result(result: Any) -> Any:
    if isinstance(result, list):
        return [_normalize_tokens(row) for row in result]
    if isinstance(result, dict):
        return _normalize_tokens(result)
    return result


def fetch_usage(context: SavantSessionContext, endpoint: str, from_date: str, to_date: str) -> Any:
    response = request(context, endpoint, method="POST", body=_usage_payload(from_date, to_date))
    promise = poll_promise(context, _promise_id(response, endpoint), timeout_seconds=120, interval_seconds=1.0)
    return _normalize_result(_result_from_promise(promise))


def _csv_value(value: Any) -> str | int | float:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return value
    return json.dumps(value, sort_keys=True)


def save_usage_csv(rows: Any, output_path: Path) -> None:
    if not isinstance(rows, list):
        raise SavantAppApiError("CSV output expected usage events as an array.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(USAGE_EVENT_FIELDS)
    extras = sorted({key for row in rows if isinstance(row, dict) for key in row.keys()} - set(keys))
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*keys, *extras])
        writer.writeheader()
        for row in rows:
            if not isinstance(row, dict):
                continue
            writer.writerow({key: _csv_value(row.get(key)) for key in [*keys, *extras]})


def _safe_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-") or "usage"


def default_output_paths(from_date: str, to_date: str) -> dict[str, Path]:
    label = _safe_label(f"{from_date}_to_{to_date}")
    root = workspace_tmp("admin-usage", label)
    return {
        "events": root / "events.json",
        "metrics": root / "metrics.json",
        "csv": root / "usage_log.csv",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Savant Admin Usage Log data through the internal app API.")
    parser.add_argument("--from", dest="from_date", required=True, help="Start date, usually YYYY-MM-DD.")
    parser.add_argument("--to", dest="to_date", required=True, help="End date, usually YYYY-MM-DD.")
    parser.add_argument("--namespace", help="Optional Savant namespace/rns to match a specific browser tab session.")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, help="Savant app origin. Defaults to https://app.savantlabs.io.")
    parser.add_argument("--events-output", type=Path, help="Where to write detailed usage events JSON.")
    parser.add_argument("--metrics-output", type=Path, help="Where to write aggregate usage metrics JSON.")
    parser.add_argument("--csv-output", type=Path, help="Where to write usage_log.csv from CSV-export event rows.")
    parser.epilog = (
        "If none of the output flags are supplied, all three outputs are written under "
        "tmp/admin-usage/{from}_to_{to}/."
    )
    parser.add_argument("--quiet", action="store_true", help="Only print written output paths.")
    args = parser.parse_args(argv)

    context = discover_session(args.namespace, origin=args.origin)
    written: list[Path] = []
    defaults = default_output_paths(args.from_date, args.to_date)
    write_all_defaults = not (args.events_output or args.metrics_output or args.csv_output)
    events_output = args.events_output or (defaults["events"] if write_all_defaults else None)
    metrics_output = args.metrics_output or (defaults["metrics"] if write_all_defaults else None)
    csv_output = args.csv_output or (defaults["csv"] if write_all_defaults else None)

    if events_output:
        events = fetch_usage(context, "/api/usage-events/events/async", args.from_date, args.to_date)
        save_json(
            {
                "namespace": context.namespace,
                "from": args.from_date,
                "to": args.to_date,
                "eventType": USAGE_EVENT_TYPE,
                "events": events,
            },
            events_output,
        )
        written.append(events_output)

    if metrics_output:
        metrics = fetch_usage(context, "/api/usage-events/metrics/async", args.from_date, args.to_date)
        save_json(
            {
                "namespace": context.namespace,
                "from": args.from_date,
                "to": args.to_date,
                "eventType": USAGE_EVENT_TYPE,
                "metrics": metrics,
            },
            metrics_output,
        )
        written.append(metrics_output)

    if csv_output:
        rows = fetch_usage(context, "/api/usage-events/csv/async", args.from_date, args.to_date)
        save_usage_csv(rows, csv_output)
        written.append(csv_output)

    if not written:
        raise SavantAppApiError("No usage outputs were written.")

    if args.quiet:
        for path in written:
            print(path)
    else:
        print("Wrote:")
        for path in written:
            print(f"- {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SavantAppApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
