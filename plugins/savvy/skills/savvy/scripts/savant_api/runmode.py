"""Shared run-mode vocabulary for the compute/inspect CLIs.

One vocabulary across `preview nodes`, `workflow health`, `workflow inspect`, and
`app --inspect-node` so the AI expresses run mode the same way everywhere:

    --mode cached       read the existing Ready preview; do NOT compute (fastest; default for reads)
    --mode interactive  compute at the 1k INPUT sample (fast; aggregates/filters may be short)
    --mode analyze      compute at the full-source `max` tier, no destination writes (fuller validation)

Plus the two scope levers that make full-data Analyze affordable (both repeatable):

    --up-to NODE        stopping node(s): compute only the path TO these; prune downstream
    --from  NODE        starting node(s): recompute from this changed node forward, reuse upstream cache

Cache reuse-vs-bust is intentionally NOT a flag: reads reuse the Ready cache; the edit/applier
path forces a fresh recompute internally. The legacy flags (`--analyze`, `--no-analyze`,
`--analyze-preview`, `--sample-tier`, `--force-analyze`) are accepted as hidden, deprecated
aliases for one release so in-flight skill prose keeps working.
"""

from __future__ import annotations

import argparse

MODES = ("cached", "interactive", "analyze")

# The backend sampleTier is binary: only `max` triggers the full debug-session path.
_TIER = {"cached": "1k", "interactive": "1k", "analyze": "max"}
_COMPUTE = {"interactive", "analyze"}


def add_run_mode_args(
    parser: argparse.ArgumentParser,
    *,
    default: str = "cached",
    legacy_analyze_flag: str | None = "--analyze",
    legacy_force_analyze: bool = False,
) -> None:
    """Register `--mode`, `--up-to`, `--from`, and the hidden deprecated aliases.

    ``default`` is the mode used when the caller passes nothing (``cached`` for read helpers,
    ``interactive`` for verification passes that always compute). ``legacy_analyze_flag`` names
    the old opt-in-to-compute flag this command used (e.g. ``--analyze`` or ``--analyze-preview``);
    pass ``None`` if the command had none. ``legacy_force_analyze`` adds the hidden
    ``--force-analyze`` alias for commands that used it.
    """
    parser.add_argument(
        "--mode",
        choices=list(MODES),
        default=default,
        help=(
            "Compute posture: cached (read existing preview, no compute), "
            "interactive (compute at 1k input sample), "
            "analyze (compute at full-source max tier, no writes). "
            f"Default: {default}."
        ),
    )
    parser.add_argument(
        "--up-to",
        dest="up_to",
        action="append",
        default=[],
        metavar="NODE",
        help="Stopping node id/name: compute only the path TO these node(s); prune downstream. Repeatable.",
    )
    parser.add_argument(
        "--from",
        dest="from_nodes",
        action="append",
        default=[],
        metavar="NODE",
        help="Starting node id/name: recompute from this changed node forward, reusing upstream cache. Repeatable.",
    )
    # Hidden deprecated aliases.
    if legacy_analyze_flag:
        parser.add_argument(legacy_analyze_flag, dest="_legacy_analyze", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-analyze", dest="_legacy_no_analyze", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sample-tier", dest="_legacy_sample_tier", default=None, help=argparse.SUPPRESS)
    if legacy_force_analyze:
        parser.add_argument("--force-analyze", dest="_legacy_force_analyze", action="store_true", help=argparse.SUPPRESS)


def resolve_mode(args: argparse.Namespace, *, default: str = "cached") -> str:
    """Fold the deprecated aliases into the effective `--mode`.

    Precedence: an explicit non-default ``--mode`` always wins. Otherwise legacy flags map on:
    ``--sample-tier max`` -> analyze; a legacy compute opt-in (``--analyze`` / ``--analyze-preview``
    / ``--force-analyze``) -> interactive (the old default was a fresh 1k compute).
    """
    mode = getattr(args, "mode", default)
    if mode == default:
        legacy_tier = getattr(args, "_legacy_sample_tier", None)
        if isinstance(legacy_tier, str) and legacy_tier.strip().lower() == "max":
            return "analyze"
        if getattr(args, "_legacy_analyze", False) or getattr(args, "_legacy_force_analyze", False):
            return "interactive"
    return mode


def sample_tier(mode: str) -> str:
    return _TIER.get(mode, "1k")


def should_compute(mode: str) -> bool:
    return mode in _COMPUTE
